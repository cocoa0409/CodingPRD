"""Status machines: initial states, the legal edges, the refused edges out of
terminal states, and the side effects a transition owns."""
from test_helpers import (
    ADMIN,
    ANALYST,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    assert_gallons_equal,
    assert_instant_equals,
    factories,
    fixtures,
    make_pump_terminal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_scheduled_promotion_earns_nothing_until_it_is_activated():
    """A promotion whose window already contains the logical clock still sits
    outside the multiplier stack until activation moves it.

    PRD: "A scheduled event begins life with `status` `SCHEDULED` and contributes
    nothing to accrual until it is activated into `ACTIVE`."

    PRD: "For each line, the eligible events are those belonging to the member's
    banner, in `ACTIVE` status, whose half-open window contains `transacted_at`
    (that is, whose `starts_at` is at or before `transacted_at` and whose `ends_at`
    is strictly after it), and whose `applies_to_categories` contains that line's
    `category`."

    Design: Corner/state_machines/promo_event_is_born_scheduled_and_activation_moves_it_to_active
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    grocery_id = program["grocery"]["id"]
    promo = fixtures.create_promo(
        program["banner"]["id"],
        promo_code="P_SCHED",
        applies_to_categories=["GROCERY"],
        activate=False,
    )
    assert promo["status"] == "SCHEDULED"

    basket = fixtures.record_basket(
        program["member"]["id"],
        grocery_id,
        [factories.purchase_line("GROCERY", 30000, 1)],
        "2026-08-01T00:00:00Z",
    )
    posted = fixtures.post_basket(basket["id"], grocery_id)
    assert posted["gross_points_awarded"] == 300
    assert posted["applied_promo_event_ids"] == []

    activated = validate_success(api_client.activate_promo_event(promo["id"], ADMIN))

    assert activated["status"] == "ACTIVE"
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 300


def test_clearing_a_signal_twice_is_refused_the_second_time():
    """The clear is a one-way edge out of `OPEN`, so replaying it is a state
    failure rather than a second success.

    PRD: "Clearing takes an `OPEN` signal to `CLEARED`, stamping `cleared_at` from
    the logical clock and `cleared_by_user_id` with the acting `X-User-ID`."

    PRD: "The target resource's current state must permit the requested transition
    — otherwise `ERR_INVALID_STATE_TRANSITION`. This guards every action endpoint,
    and explicitly covers re-running a transition out of a terminal state,
    repeating an action already performed, activating a promotional event that has
    already `ENDED`, clearing a signal that is already `CLEARED`, thawing a
    household that still carries an open `ALT_ID_SHARING` or `GEO_IMPOSSIBLE`
    signal, completing a redemption that is not `AUTHORIZED`, and closing a cycle
    that is not `CLOSING`."

    Design: Corner/state_machines/fraud_signal_clear_is_not_idempotent_and_the_second_attempt_is_refused
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    signal = fixtures.raise_signal(household["id"], "CROSS_BANNER_VELOCITY", 30)

    cleared = fixtures.clear_signal(signal["id"])
    assert cleared["status"] == "CLEARED"
    assert_instant_equals(cleared["cleared_at"], "2026-08-01T00:00:00Z")
    assert cleared["cleared_by_user_id"] == "analyst-1"

    validate_error(
        api_client.clear_fraud_signal(signal["id"], ANALYST),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    read = fixtures.get_household(household["id"])
    assert read["fraud_score"] == 0
    assert read["status"] == "ACTIVE"

    _open_signals, meta = validate_paginated(
        api_client.list_household_fraud_signals(
            household["id"], ADMIN, {"status": "OPEN"}
        )
    )
    assert meta["total_count"] == 0


def test_a_cycle_cannot_begin_closing_before_its_window_has_elapsed():
    """The precondition is on the logical clock, and the same call succeeds once
    the clock has passed the window.

    PRD: "The cycle must currently be `OPEN`; the logical clock must be
    **strictly after** its `closes_at`, or the request is refused with
    `ERR_CYCLE_NOT_ENDED`; and every cycle of the same banner whose `cycle_month`
    sorts lexicographically before this one must already be `CLOSED`, or the
    request is refused with `ERR_PRIOR_CYCLE_NOT_CLOSED`."

    Design: Corner/state_machines/cycle_begin_close_before_the_window_ends_is_refused_as_not_ended
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    cycles = fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    august_id = cycles["2026-08"]["id"]

    validate_error(
        api_client.begin_close_point_cycle(august_id, SUPERVISOR),
        ApiErrorId.ERR_CYCLE_NOT_ENDED.value,
    )
    assert validate_success(api_client.get_point_cycle(august_id, ADMIN))["status"] == "OPEN"

    fixtures.set_clock("2026-09-01T00:00:00Z")
    closing = fixtures.begin_close(august_id)

    assert closing["status"] == "CLOSING"
    assert closing["closed_at"] is None


def test_a_cycle_cannot_jump_from_open_straight_to_closed():
    """`CLOSED` is reachable only from `CLOSING`, so the two-phase close cannot be
    collapsed into one call.

    PRD: "**Phase two** takes the cycle from `CLOSING` to `CLOSED` and runs the
    month-boundary sweep."

    PRD: "It requires the cycle to be `CLOSING`, and it also requires a cycle to
    exist for the calendar month immediately after this cycle's `cycle_month`,
    because a rescued lot must be given a new expiry instant; without it the close
    fails with `ERR_NEXT_CYCLE_NOT_DEFINED`."

    Design: Corner/state_machines/cycle_close_from_open_skips_the_closing_step_and_is_refused
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    cycles = fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    august_id = cycles["2026-08"]["id"]
    fixtures.set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api_client.close_point_cycle(august_id, SUPERVISOR),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    august = validate_success(api_client.get_point_cycle(august_id, ADMIN))
    assert august["status"] == "OPEN"
    assert august["closed_at"] is None
    assert august["expired_points_total"] == 0
    assert august["swept_member_count"] == 0


def test_voiding_an_unposted_basket_writes_no_ledger_row_at_all():
    """The accrual dimension never left `NOT_ACCRUED`, so there is nothing to
    reverse and no member figure moves.

    PRD: "The effect is a bare status flip: `posting_status` becomes `VOIDED`,
    `voided_at` is stamped from the logical clock, `accrual_status` stays
    `NOT_ACCRUED`, and **no ledger row whatsoever is written**, because nothing was
    ever accrued."

    PRD: "No member figure moves, no member `version` advances, no household
    figure is recomputed."

    Design: Corner/state_machines/purchase_void_before_posting_reverses_nothing_and_writes_no_ledger_row
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    grocery_id = program["grocery"]["id"]
    basket = fixtures.record_basket(
        member_id,
        grocery_id,
        [factories.purchase_line("GROCERY", 30000, 1)],
        "2026-08-01T00:00:00Z",
    )
    version_before = fixtures.member_version(member_id)

    voided = fixtures.void_basket(basket["id"], grocery_id)

    assert voided["posting_status"] == "VOIDED"
    assert voided["accrual_status"] == "NOT_ACCRUED"
    assert_instant_equals(voided["voided_at"], "2026-08-01T00:00:00Z")

    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 0

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 0
    assert member["lifetime_points"] == 0
    assert member["version"] == version_before


def test_a_voided_authorization_can_never_be_completed():
    """`VOIDED` is terminal on the pump dimension, and the refused completion
    leaves every fill figure unwritten.

    PRD: "The pump submits the `gallons_dispensed` actually pumped; the redemption
    must be `AUTHORIZED`, and the submitted volume must be strictly greater than
    zero and no greater than the stored `gallons_authorized`."

    PRD: "Abandoning an open authorization drives it from `AUTHORIZED` to
    `VOIDED`, appends a `REDEMPTION_RELEASE` row of the positive
    `points_debited_at_auth` with `lot_expires_at` null and `source_kind`
    `FUEL_REDEMPTION`, and performs the balance propagation of §2.11."

    Design: Corner/state_machines/completing_a_voided_redemption_is_refused_from_a_terminal_authorization
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    fuel_id = program["fuel"]["id"]
    redemption = fixtures.authorize_redemption(
        program["member"]["id"], fuel_id, "6660000001", 300
    )
    fixtures.void_redemption(redemption["id"], fuel_id)

    validate_error(
        api_client.complete_fuel_redemption(
            redemption["id"],
            {"gallons_dispensed": 10.0},
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    read = fixtures.get_redemption(redemption["id"])
    assert read["authorization_status"] == "VOIDED"
    assert read["settlement_status"] == "NOT_APPLICABLE"
    assert read["gallons_dispensed"] is None
    assert read["dispensed_at"] is None
    assert read["discount_amount_cents"] is None
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 300


def test_a_revoked_linkage_has_no_way_back_to_active():
    """Revocation is the one linkage state with no back-edge, in deliberate
    contrast to suspension.

    PRD: "From either source state, activation requires that the linkage actually
    be in that state, that the household be `ACTIVE` (otherwise
    `ERR_HOUSEHOLD_FROZEN`), and that the household's banner be `ACTIVE`
    (otherwise `ERR_BANNER_SUSPENDED`)."

    PRD: "Revocation is terminal and can be reached from any of the three live
    states, but its consequences differ sharply by source."

    Design: Corner/state_machines/revoked_household_link_cannot_be_reactivated
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    member = fixtures.create_member(banner["id"], alt_id="6660000001")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    link = fixtures.create_link(household["id"], member["id"], "PRIMARY", activate=True)
    fixtures.revoke_link(link["id"])

    validate_error(
        api_client.activate_household_link(link["id"], ANALYST),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    read_link = fixtures.get_link(link["id"])
    assert read_link["status"] == "REVOKED"
    assert_instant_equals(read_link["revoked_at"], "2026-08-01T00:00:00Z")

    read_household = fixtures.get_household(household["id"])
    assert read_household["linked_member_count"] == 0
    assert read_household["aggregate_available_points"] == 0


def test_denying_a_dispute_under_investigation_records_no_adjustment():
    """The dispute reaches its denied terminal state without ever visiting the
    proposal branch.

    PRD: "Denying from `INVESTIGATING` sets `status` to `RESOLVED_DENIED` and
    stamps `resolved_at`, writes **no** ledger row, and unlocks refiling — a new
    dispute may now name this one in its `supersedes_dispute_id`."

    PRD: "A new dispute is `FILED` with `proposed_points_delta`, `authority_tier`,
    `proposed_by_user_id`, `approved_by_user_id`, `applied_ledger_entry_id` and
    `resolved_at` all null."

    Design: Corner/state_machines/dispute_denial_from_investigating_skips_the_adjustment_branch
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    sender_id = program["member"]["id"]
    recipient = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(
        program["household"]["id"], recipient["id"], "SECONDARY", activate=True
    )
    transfer_out = fixtures.transfer_points(sender_id, recipient["id"], 100)
    dispute = fixtures.file_dispute(
        sender_id, transfer_out["id"], 100, "UNAUTHORIZED_REDEMPTION"
    )
    fixtures.investigate_dispute(dispute["id"])

    denied = fixtures.deny_dispute(dispute["id"])

    assert denied["status"] == "RESOLVED_DENIED"
    assert_instant_equals(denied["resolved_at"], "2026-08-01T00:00:00Z")
    assert denied["proposed_points_delta"] is None
    assert denied["authority_tier"] is None
    assert denied["proposed_by_user_id"] is None
    assert denied["applied_ledger_entry_id"] is None
    assert denied["approved_by_user_id"] is None

    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": sender_id, "entry_type": "ADJUSTMENT"}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.get_member(sender_id)["available_points"] == 200


def test_a_thaw_is_blocked_by_an_open_alt_id_sharing_signal():
    """The back-edge out of `FROZEN` is guarded by signal type rather than by
    score, and clearing the signal opens it.

    PRD: "That thaw itself has a precondition: no fraud signal against the
    household may be `OPEN` with a `signal_type` of `ALT_ID_SHARING` or
    `GEO_IMPOSSIBLE`, and an attempt in the face of one is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    PRD: "A recomputed score that falls back below the threshold leaves the
    household `FROZEN`; only an explicit thaw by a `LoyaltySupervisor` returns it
    to `ACTIVE`, clearing `frozen_reason` and `frozen_at` back to null."

    Design: Corner/state_machines/unfreeze_is_blocked_while_an_alt_id_sharing_signal_is_still_open
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    frozen = fixtures.freeze_household(household["id"])
    assert frozen["status"] == "FROZEN"
    assert frozen["frozen_reason"] == "MANUAL"
    assert_instant_equals(frozen["frozen_at"], "2026-08-01T00:00:00Z")
    signal = fixtures.raise_signal(household["id"], "ALT_ID_SHARING", 10)

    validate_error(
        api_client.unfreeze_household(household["id"], SUPERVISOR),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )
    guarded = fixtures.get_household(household["id"])
    assert guarded["status"] == "FROZEN"
    assert guarded["frozen_reason"] == "MANUAL"

    fixtures.clear_signal(signal["id"])
    thawed = fixtures.unfreeze_household(household["id"])

    assert thawed["status"] == "ACTIVE"
    assert thawed["frozen_reason"] is None
    assert thawed["frozen_at"] is None
    assert thawed["fraud_score"] == 0


def test_a_partner_fill_pushes_its_gallons_into_the_unbatched_pool():
    """Completion prices the fill and moves the settlement dimension off
    `NOT_APPLICABLE` without touching the member's balance.

    PRD: "The discount owed is `gallons_dispensed` multiplied by the redemption's
    stored `cents_off_per_gallon`, rounded half up to whole cents, and it is
    written to `discount_amount_cents`."

    PRD: "At a `PARTNER_STATION`, `settlement_status` moves from `NOT_APPLICABLE`
    to `PENDING`, and the site's `unbatched_gallons` and `unbatched_discount_cents`
    are recomputed with the site's `version` incremented by one — the gallons have
    entered the reimbursement pipeline."

    Design: Corner/state_machines/redemption_completion_side_effects_fill_the_partner_unbatched_pool
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    partner_id = program["partner"]["id"]
    redemption = fixtures.authorize_redemption(
        program["member"]["id"], partner_id, "6660000001", 300
    )

    dispensed = fixtures.complete_fill(redemption["id"], partner_id, 12.0)

    assert dispensed["authorization_status"] == "DISPENSED"
    assert dispensed["settlement_status"] == "PENDING"
    assert dispensed["discount_amount_cents"] == 360
    assert_gallons_equal(dispensed["gallons_dispensed"], "12.000")
    assert_instant_equals(dispensed["dispensed_at"], "2026-08-01T00:00:00Z")

    site = fixtures.get_site(partner_id)
    assert_gallons_equal(site["unbatched_gallons"], "12.000")
    assert site["unbatched_discount_cents"] == 360
    assert site["settlement_balance_cents"] == 0

    assert fixtures.get_member(program["member"]["id"])["available_points"] == 0


def test_a_fresh_authorization_starts_not_applicable_on_the_settlement_axis():
    """The two dimensions of a redemption are initialised separately, and every
    fill figure waits for the pump to report.

    PRD: "A successful authorization creates the redemption in `AUTHORIZED` status
    on the pump dimension and `NOT_APPLICABLE` on the settlement dimension, stamps
    `authorized_at` from the logical clock, and writes `blocks_effective`,
    `cents_off_per_gallon`, `points_debited_at_auth` and `gallons_authorized`."

    PRD: "It leaves `gallons_dispensed`, `discount_amount_cents` and
    `settlement_batch_id` null and `dispensed_at` null."

    Design: Corner/state_machines/redemption_authorization_and_settlement_axes_start_independently
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )

    redemption = fixtures.authorize_redemption(
        program["member"]["id"], program["fuel"]["id"], "6660000001", 300
    )

    assert redemption["authorization_status"] == "AUTHORIZED"
    assert redemption["settlement_status"] == "NOT_APPLICABLE"
    assert redemption["settlement_batch_id"] is None
    assert redemption["gallons_dispensed"] is None
    assert redemption["discount_amount_cents"] is None
    assert redemption["dispensed_at"] is None
    assert_instant_equals(redemption["authorized_at"], "2026-08-01T00:00:00Z")
    assert redemption["blocks_effective"] == 3
    assert redemption["cents_off_per_gallon"] == 30
    assert redemption["points_debited_at_auth"] == 300
    assert_gallons_equal(redemption["gallons_authorized"], "35.000")
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 0
