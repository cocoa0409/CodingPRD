"""Pump authorization: compensating voids, precedence pairs and the
cross-banner coverage gate."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_member_headers,
    make_pump_terminal_headers,
    validate_error,
    validate_paginated,
)


def _authorized_but_unfilled_redemption():
    """A member funded with 500 points holding one live 400-point pump
    authorization at an owned fuel center."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="INV", name="Invariant Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-017")
    fuel = fixtures.create_owned_fuel_center(banner["id"], "F-017")
    member = fixtures.create_member(banner["id"], alt_id="5550000017")
    fixtures.accrue_points(member["id"], grocery["id"], 500)
    redemption = fixtures.authorize_redemption(
        member["id"], fuel["id"], "5550000017", 400
    )
    return {"member": member, "fuel": fuel, "redemption": redemption}


def test_voiding_an_authorization_restores_the_balance_with_a_new_write():
    """The release is a fresh compensating write, so the member's version keeps
    advancing rather than rolling back.

    PRD: "Abandoning an open authorization drives it from `AUTHORIZED` to
    `VOIDED`, appends a `REDEMPTION_RELEASE` row of the positive
    `points_debited_at_auth` with `lot_expires_at` null and `source_kind`
    `FUEL_REDEMPTION`, and performs the balance propagation of §2.11."

    PRD: "Any write that appends a ledger row recomputes the affected member's
    `available_points` and, where the row is an `ACCRUAL` or `REVERSAL`, their
    `lifetime_points`, and increments that member's `version` by one."

    Design: Difficulty/compensating_invariant/redemption_void_restores_member_ledger_sum_without_deleting_history
    """
    scenario = _authorized_but_unfilled_redemption()
    member_id = scenario["member"]["id"]

    voided = fixtures.void_redemption(
        scenario["redemption"]["id"], scenario["fuel"]["id"]
    )

    assert voided["authorization_status"] == "VOIDED"

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 500
    assert member["lifetime_points"] == 500
    assert member["version"] == 4, (
        "the release is a new write on top of accrual and authorization"
    )


def test_voiding_an_authorization_preserves_the_original_debit_row():
    """History is never rewritten: the debit and its release both stay on the
    ledger and their sum is the balance.

    PRD: "This is a true compensating action: the sum of the member's ledger
    returns to exactly its pre-authorization value, with no drift."

    PRD: "`available_points` is the sum of `points_delta` over **every** entry of
    that member with no status filter whatsoever — the ledger is append-only, so
    every row counts."

    Design: Difficulty/compensating_invariant/redemption_void_restores_member_ledger_sum_without_deleting_history
    """
    scenario = _authorized_but_unfilled_redemption()
    member_id = scenario["member"]["id"]

    fixtures.void_redemption(scenario["redemption"]["id"], scenario["fuel"]["id"])

    rows = fixtures.ledger_entries(member_id)
    assert len(rows) == 3
    assert [row["points_delta"] for row in rows] == [500, -400, 400]
    assert sum(row["points_delta"] for row in rows) == 500

    debits, debit_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION"}
        )
    )
    assert debit_meta["total_count"] == 1
    assert debits[0]["points_delta"] == -400

    releases, release_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION_RELEASE"}
        )
    )
    assert release_meta["total_count"] == 1
    assert releases[0]["points_delta"] == 400
    assert releases[0]["source_kind"] == "FUEL_REDEMPTION"


def _frozen_household_with_empty_member():
    """A member with no points at all whose household has been frozen by hand."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="PRI", name="Priority Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    fuel = fixtures.create_owned_fuel_center(banner["id"], "F-009")
    member = fixtures.create_member(banner["id"], alt_id="5550000009")
    household = fixtures.create_household(banner["id"], "HH-PRI-1")
    fixtures.create_link(household["id"], member["id"], "PRIMARY", activate=True)
    fixtures.freeze_household(household["id"])
    return {"member": member, "fuel": fuel, "household": household}


def test_frozen_household_outranks_an_empty_balance_at_the_pump():
    """Both the freeze and the balance are violated; the freeze is the answer.

    PRD: "A frozen household combined with an empty balance at the pump returns
    HTTP 409 `ERR_HOUSEHOLD_FROZEN`, never HTTP 422 `ERR_INSUFFICIENT_POINTS`,
    because the freeze check (step 11) precedes the balance check (step 29)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_household_outranks_insufficient_points_on_fuel_redemption
    """
    scenario = _frozen_household_with_empty_member()
    member_id = scenario["member"]["id"]
    fuel_id = scenario["fuel"]["id"]
    version = fixtures.member_version(member_id)

    error = validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "5550000009", 500, version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_HOUSEHOLD_FROZEN.value,
    )

    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_POINTS.value


def test_a_refused_pump_authorization_writes_nothing_at_all():
    """The rejected request leaves no redemption behind and advances no version.

    PRD: "Every household reachable from the member by an `ACTIVE` linkage must
    itself be `ACTIVE`, or the request fails with `ERR_HOUSEHOLD_FROZEN`; note
    that this check is not limited to the cross-banner case, so a frozen
    household blocks the member even at their own banner's pumps."

    PRD: "A successful authorization creates the redemption in `AUTHORIZED`
    status on the pump dimension and `NOT_APPLICABLE` on the settlement
    dimension, stamps `authorized_at` from the logical clock, and writes
    `blocks_effective`, `cents_off_per_gallon`, `points_debited_at_auth` and
    `gallons_authorized`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_household_outranks_insufficient_points_on_fuel_redemption
    """
    scenario = _frozen_household_with_empty_member()
    member_id = scenario["member"]["id"]
    fuel_id = scenario["fuel"]["id"]
    version_before = fixtures.member_version(member_id)

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "5550000009", 500, version_before
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_HOUSEHOLD_FROZEN.value,
    )

    household = fixtures.get_household(scenario["household"]["id"])
    assert household["status"] == "FROZEN"
    assert household["frozen_reason"] == "MANUAL"

    _rows, meta = validate_paginated(
        api_client.list_fuel_redemptions(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 0

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 0
    assert member["version"] == version_before


def test_cross_banner_authorization_stops_when_the_linkage_leaves_active():
    """The same pump accepts the fill while the linkage is active and refuses it
    once the linkage is suspended.

    PRD: "When the site's banner differs from the member's own banner, the member
    must hold a linkage in `ACTIVE` status to a household whose banner is the
    **site's** banner, or the request fails with `ERR_CROSS_BANNER_LINK_REQUIRED`
    — this is the entire mechanism by which a shopper enrolled at one banner
    fuels at another."

    Design: Difficulty/cross_entity_state_dependency/cross_banner_redemption_gated_by_household_link_active_state
    """
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.cross_banner_program(points=600, alt_id="5550000014")
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]

    first = fixtures.authorize_redemption(member_id, fuel_id, "5550000014", 300)
    assert first["points_debited_at_auth"] == 300

    suspended = fixtures.suspend_link(program["link"]["id"])
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id,
                fuel_id,
                "5550000014",
                300,
                fixtures.member_version(member_id),
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_CROSS_BANNER_LINK_REQUIRED.value,
    )


def test_suspending_a_linkage_leaves_an_existing_authorization_standing():
    """Losing coverage blocks new authorizations but does not reach back into
    one already granted.

    PRD: "Suspension takes an `ACTIVE` linkage to `SUSPENDED`. It performs the
    same coverage propagation — `linked_member_count`,
    `aggregate_available_points` and `cross_banner_member_ids` recomputed,
    household `version` incremented — and nothing more. In particular, and this
    asymmetry is deliberate, **suspension does not void the member's open fuel
    authorizations**; only revocation does."

    Design: Difficulty/cross_entity_state_dependency/cross_banner_redemption_gated_by_household_link_active_state
    """
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.cross_banner_program(points=600, alt_id="5550000014")
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]

    first = fixtures.authorize_redemption(member_id, fuel_id, "5550000014", 300)
    fixtures.suspend_link(program["link"]["id"])

    assert fixtures.get_redemption(first["id"])["authorization_status"] == "AUTHORIZED"

    household = fixtures.get_household(program["household"]["id"])
    assert household["cross_banner_member_ids"] == []

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 300

    _rows, meta = validate_paginated(
        api_client.list_fuel_redemptions(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 1


def _fraud_locked_sender_and_a_stranger():
    """A funded sender whose household carries one open `RAPID_TRANSFER` signal,
    plus a second member who shares no household with them."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="TRF", name="Transfer Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-010")
    sender = fixtures.create_member(banner["id"], alt_id="5550000010")
    stranger = fixtures.create_member(
        banner["id"], alt_id="5550000011", card_number="4000000000000011"
    )
    household = fixtures.create_household(banner["id"], "HH-TR-1")
    fixtures.create_link(household["id"], sender["id"], "PRIMARY", activate=True)
    fixtures.accrue_points(sender["id"], grocery["id"], 300)
    fixtures.raise_signal(household["id"], "RAPID_TRANSFER", 10)
    return {"sender": sender, "stranger": stranger, "household": household}


def test_transfer_fraud_lock_outranks_the_recipient_relationship_check():
    """A locked sender naming a stranger sees the lock, not the relationship
    error.

    PRD: "A fraud-locked sender naming a recipient who is not in their household
    returns HTTP 403 `ERR_TRANSFER_FRAUD_LOCK`, never HTTP 422
    `ERR_RECIPIENT_NOT_IN_HOUSEHOLD`, because the fraud lock (step 17) precedes
    the referential check (step 23)."

    Design: Difficulty/priority_pair_validation_conflict/transfer_fraud_lock_outranks_recipient_not_in_household
    """
    scenario = _fraud_locked_sender_and_a_stranger()

    error = validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(
                scenario["sender"]["id"], scenario["stranger"]["id"], 100
            ),
            make_member_headers(scenario["sender"]["id"]),
        ),
        ApiErrorId.ERR_TRANSFER_FRAUD_LOCK.value,
    )

    assert error["error_id"] != ApiErrorId.ERR_RECIPIENT_NOT_IN_HOUSEHOLD.value


def test_a_single_rapid_transfer_signal_locks_transfers_without_freezing():
    """One open `RAPID_TRANSFER` signal is enough to lock transfers even though
    its weight is far below the freeze threshold, and the refusal moves no
    points.

    PRD: "The **fraud lock** comes first: the sending member's household must
    carry fewer than two fraud signals in `OPEN` status, and none of its open
    signals may have a `signal_type` of `RAPID_TRANSFER` or `ALT_ID_SHARING`."

    Design: Difficulty/priority_pair_validation_conflict/transfer_fraud_lock_outranks_recipient_not_in_household
    """
    scenario = _fraud_locked_sender_and_a_stranger()
    sender_id = scenario["sender"]["id"]
    stranger_id = scenario["stranger"]["id"]

    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, stranger_id, 100),
            make_member_headers(sender_id),
        ),
        ApiErrorId.ERR_TRANSFER_FRAUD_LOCK.value,
    )

    household = fixtures.get_household(scenario["household"]["id"])
    assert household["status"] == "ACTIVE"
    assert household["fraud_score"] == 10

    _out, out_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": sender_id, "entry_type": "TRANSFER_OUT"}
        )
    )
    assert out_meta["total_count"] == 0

    _in, in_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": stranger_id, "entry_type": "TRANSFER_IN"}
        )
    )
    assert in_meta["total_count"] == 0

    assert fixtures.get_member(sender_id)["available_points"] == 300
    assert fixtures.get_member(stranger_id)["available_points"] == 0
