"""Business rules: the exact-match, boundary, uniqueness, site-type, temporal and
cross-entity refusals, each checked with the state it must leave untouched."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MONTH_WINDOWS,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    assert_gallons_equal,
    assert_instant_equals,
    factories,
    fixtures,
    make_member_headers,
    make_pump_terminal_headers,
    make_settlement_clerk_headers,
    make_store_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]


def test_a_keypad_number_with_a_leading_zero_is_not_the_stored_alternate_id():
    """Two legal digit strings differing only by a padded zero are different
    identifiers, and the refusal costs the member no version.

    PRD: "The `alt_id_presented` must equal the member's stored `alt_id`
    **exactly**, character for character, with no normalisation, trimming or case
    folding of any kind; a mismatch is `ERR_ALT_ID_MISMATCH`."

    PRD: "The guard exists because a member's `version` advances whenever anything
    moves that member's balance — a prior authorization that this one would
    legitimately supersede, an accrual, a reversal, a transfer, a sweep row or an
    approved adjustment — so a mismatch means the pump decided its
    `points_committed` against a balance that no longer exists."

    Design: Corner/validations/alt_id_at_the_pump_must_match_the_stored_string_exactly
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    observed_version = fixtures.member_version(member_id)

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "06660000001", 300, observed_version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_ALT_ID_MISMATCH.value,
    )
    assert fixtures.member_version(member_id) == observed_version

    redemption = validate_success(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "6660000001", 300, observed_version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        201,
    )

    assert redemption["points_debited_at_auth"] == 300
    assert fixtures.get_member(member_id)["available_points"] == 0


def test_the_smallest_acceptable_offer_is_the_minimum_itself():
    """Ninety-nine points is refused as too small rather than quietly floored to
    no blocks at all, and one hundred buys a block.

    PRD: "And `points_committed` must be at least the banner's
    `min_points_per_redemption`, or `ERR_BELOW_MIN_REDEMPTION`."

    PRD: "`min_points_per_redemption` (default 100, and never less than
    `points_per_discount_block`) is the smallest offer the pump will accept."

    PRD: "The offer is first converted to whole discount blocks: the number of
    blocks requested is `points_committed` divided by the banner's
    `points_per_discount_block`, **rounded down** to a whole number."

    Design: Corner/validations/minimum_redemption_boundary_refuses_ninety_nine_and_accepts_one_hundred
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300,
        alt_id="6660000001",
        banner_code="CORE",
        name="Corner Banner",
        min_points_per_redemption=100,
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    observed_version = fixtures.member_version(member_id)

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "6660000001", 99, observed_version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_BELOW_MIN_REDEMPTION.value,
    )

    redemption = validate_success(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "6660000001", 100, observed_version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        201,
    )

    assert redemption["cents_off_per_gallon"] == 10
    assert redemption["blocks_effective"] == 1
    assert redemption["points_debited_at_auth"] == 100
    assert fixtures.get_member(member_id)["available_points"] == 200


def test_the_balance_is_weighed_against_the_derived_debit_not_the_offer():
    """An offer the cap would shrink is still refused outright: the pump never
    receives a partial authorization.

    PRD: "The balance test uses the derived debit, not the offer: the member's
    `available_points` must be at least `points_debited_at_auth` as computed above,
    or the request fails with `ERR_INSUFFICIENT_POINTS`."

    PRD: "The debit is then **back-derived from the capped cents**, which is the
    whole point of the design: `blocks_effective` is `cents_off_per_gallon` divided
    by `cents_off_per_block`, and `points_debited_at_auth` is `blocks_effective`
    multiplied by `points_per_discount_block`."

    Design: Corner/validations/insufficient_points_is_measured_against_the_computed_debit
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    observed_version = fixtures.member_version(member_id)

    for committed in (500, 1500):
        validate_error(
            api_client.create_fuel_redemption(
                factories.fuel_redemption_payload(
                    member_id, fuel_id, "6660000001", committed, observed_version
                ),
                make_pump_terminal_headers(fuel_id),
            ),
            ApiErrorId.ERR_INSUFFICIENT_POINTS.value,
        )

    _rows, meta = validate_paginated(
        api_client.list_fuel_redemptions(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 0
    member = fixtures.get_member(member_id)
    assert member["available_points"] == 300
    assert member["version"] == observed_version


def test_each_uniqueness_rule_fires_on_its_own_scope():
    """Five constraints that share a precedence level are reachable one at a time,
    each answering with its own code.

    PRD: "Reusing an `alt_id` inside a banner is rejected with
    `ERR_ALT_ID_DUPLICATE`."

    PRD: "A household is opened against a `banner_id` with a `household_code` of
    four to twenty-four characters unique within that banner; a repeat is rejected
    with `ERR_HOUSEHOLD_CODE_DUPLICATE`."

    PRD: "A cycle is defined for a `banner_id` with a `cycle_month` in
    four-digit-year-dash-two-digit-month form, unique within the banner (a repeat
    yields `ERR_CYCLE_MONTH_DUPLICATE`), an inclusive `opens_at`, and a `closes_at`
    strictly later than `opens_at` that serves both as the inclusive end of the
    window and as the expiry cut-off the sweep uses."

    PRD: "Two structural rules guard creation: no other linkage for the same
    household-and-member pair may be in `PENDING`, `ACTIVE` or `SUSPENDED` status,
    or the proposal fails with `ERR_DUPLICATE_ACTIVE_LINK`; and if the proposed
    `link_role` is `PRIMARY`, no other linkage of that household may already hold
    `PRIMARY` in any of those three statuses, or the proposal fails with
    `ERR_PRIMARY_LINK_EXISTS`."

    Design: Corner/validations/the_five_uniqueness_rules_at_priority_sixty_nine_each_fire_on_their_own_scope
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    member = fixtures.create_member(banner["id"], alt_id="6660000001")
    housemate = fixtures.create_member(
        banner["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    fixtures.create_link(household["id"], member["id"], "PRIMARY", activate=True)

    validate_error(
        api_client.create_member(
            factories.member_payload(
                banner["id"],
                alt_id="6660000001",
                card_number="4100000000000077",
                full_name="Corner Clone",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_ALT_ID_DUPLICATE.value,
    )
    validate_error(
        api_client.create_household(
            factories.household_payload(banner["id"], "HH-CORE-1"), ANALYST
        ),
        ApiErrorId.ERR_HOUSEHOLD_CODE_DUPLICATE.value,
    )
    validate_error(
        api_client.create_point_cycle(
            factories.point_cycle_payload(banner["id"], "2026-08"), ADMIN
        ),
        ApiErrorId.ERR_CYCLE_MONTH_DUPLICATE.value,
    )
    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(
                household["id"], member["id"], "SECONDARY"
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_LINK.value,
    )
    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(
                household["id"], housemate["id"], "PRIMARY"
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_PRIMARY_LINK_EXISTS.value,
    )

    assert fixtures.get_household(household["id"])["linked_member_count"] == 1
    _links, meta = validate_paginated(
        api_client.list_household_links(ADMIN, {"household_id": household["id"]})
    )
    assert meta["total_count"] == 1


def test_each_endpoint_insists_on_its_own_kind_of_site():
    """A grocery lane, a fuel dispenser and a settlement counterparty are not
    interchangeable, and an owned fuel centre is never settleable.

    PRD: "The site must be of type `GROCERY`, or the recording is rejected with
    `ERR_GROCERY_SITE_REQUIRED`."

    PRD: "The site's `site_type` must be `OWNED_FUEL_CENTER` or `PARTNER_STATION`,
    or the request fails with `ERR_FUEL_SITE_REQUIRED`; a grocery site never
    authorizes fuel."

    PRD: "The site must be a `PARTNER_STATION` with a non-null `partner_code`, or
    the request fails with `ERR_PARTNER_SITE_REQUIRED`."

    Design: Corner/validations/each_site_type_gate_at_priority_sixty_three_rejects_the_wrong_site_kind
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    grocery_id = program["grocery"]["id"]
    fuel_id = program["fuel"]["id"]

    validate_error(
        api_client.create_purchase_transaction(
            factories.purchase_transaction_payload(
                member_id,
                fuel_id,
                "2026-08-01T00:00:00Z",
                [factories.purchase_line("GROCERY", 10000, 1)],
            ),
            make_store_operator_headers(fuel_id),
        ),
        ApiErrorId.ERR_GROCERY_SITE_REQUIRED.value,
    )
    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id,
                grocery_id,
                "6660000001",
                300,
                fixtures.member_version(member_id),
            ),
            make_pump_terminal_headers(grocery_id),
        ),
        ApiErrorId.ERR_FUEL_SITE_REQUIRED.value,
    )
    validate_error(
        api_client.create_settlement_batch(
            factories.settlement_batch_payload(
                fuel_id, AUGUST_START, AUGUST_END, fixtures.site_version(fuel_id)
            ),
            make_settlement_clerk_headers(fuel_id),
        ),
        ApiErrorId.ERR_PARTNER_SITE_REQUIRED.value,
    )

    _batches, meta = validate_paginated(
        api_client.list_settlement_batches(ADMIN, {"site_id": fuel_id})
    )
    assert meta["total_count"] == 0
    assert fixtures.get_member(member_id)["available_points"] == 300


def test_points_cannot_be_earned_until_the_following_month_exists():
    """The lot needs an expiry instant to be stamped with, so the post waits for
    the next month's cycle to be defined.

    PRD: "And — this is the one implementers most often miss — a cycle must also
    exist for that banner whose `cycle_month` is the calendar month **immediately
    after** the open cycle's `cycle_month`, because the accrual lot needs that next
    cycle's `closes_at` as its expiry instant; if it does not exist, posting fails
    with `ERR_NEXT_CYCLE_NOT_DEFINED`."

    PRD: "When `gross_points_awarded` is greater than zero it appends exactly one
    `ACCRUAL` ledger row whose `points_delta` equals `gross_points_awarded`, whose
    `point_cycle_id` is the open cycle, whose `lot_expires_at` is the **next**
    cycle's `closes_at`, whose `source_kind` is `PURCHASE_TRANSACTION` and whose
    `source_ref_id` is this transaction's identifier; when `gross_points_awarded`
    is exactly zero, no ledger row is written at all."

    Design: Corner/validations/accrual_is_refused_when_the_following_month_has_no_cycle_to_expire_into
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.standard_program(
        months=("2026-08",), banner_code="CORE", name="Corner Banner"
    )
    grocery_id = program["grocery"]["id"]
    member = fixtures.create_member(program["banner"]["id"], alt_id="6660000001")
    basket = fixtures.record_basket(
        member["id"],
        grocery_id,
        [factories.purchase_line("GROCERY", 30000, 1)],
        "2026-08-01T00:00:00Z",
    )

    validate_error(
        api_client.post_purchase_transaction(
            basket["id"], make_store_operator_headers(grocery_id)
        ),
        ApiErrorId.ERR_NEXT_CYCLE_NOT_DEFINED.value,
    )
    refused = validate_success(
        api_client.get_purchase_transaction(basket["id"], ADMIN)
    )
    assert refused["posting_status"] == "RECORDED"
    assert refused["accrual_status"] == "NOT_ACCRUED"

    fixtures.create_cycle(program["banner"]["id"], "2026-09")
    posted = fixtures.post_basket(basket["id"], grocery_id)

    assert posted["gross_points_awarded"] == 300
    accruals, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member["id"], "entry_type": "ACCRUAL"}
        )
    )
    assert meta["total_count"] == 1
    assert_instant_equals(accruals[0]["lot_expires_at"], "2026-09-30T23:59:59.999Z")


def test_a_suspended_banner_stops_the_post_without_disturbing_the_basket():
    """Suspension is a gate on earning, not an edit of what has already been rung
    up.

    PRD: "The member's banner must be `ACTIVE` (otherwise `ERR_BANNER_SUSPENDED`)
    and the site must be `ACTIVE` (otherwise `ERR_SITE_SUSPENDED`)."

    PRD: "Its `status` is either `ACTIVE` or `SUSPENDED` and defaults to `ACTIVE`;
    a suspended banner stops accepting the accrual, redemption, transfer,
    link-activation, promotion-activation and settlement-submission operations
    named in §2.10, each rejected with `ERR_BANNER_SUSPENDED`."

    Design: Corner/validations/posting_into_a_suspended_banner_is_refused
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
    suspended = fixtures.suspend_banner(program["banner"]["id"])
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api_client.post_purchase_transaction(
            basket["id"], make_store_operator_headers(grocery_id)
        ),
        ApiErrorId.ERR_BANNER_SUSPENDED.value,
    )

    read = validate_success(api_client.get_purchase_transaction(basket["id"], ADMIN))
    assert read["posting_status"] == "RECORDED"
    assert read["gross_points_awarded"] == 0
    assert read["subtotal_cents"] == 30000
    assert fixtures.get_member(member_id)["available_points"] == 0


def test_a_cycle_that_is_open_but_elapsed_cannot_absorb_a_post():
    """The window is read against the logical clock, so a still-`OPEN` cycle whose
    window has passed accrues nothing.

    PRD: "A cycle of the member's banner must be `OPEN` with the logical clock
    inside its inclusive `opens_at`-to-`closes_at` window (otherwise
    `ERR_CYCLE_NOT_OPEN`)."

    Design: Corner/validations/posting_outside_every_open_cycle_window_is_refused
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
    fixtures.set_clock("2026-10-01T00:00:00Z")

    validate_error(
        api_client.post_purchase_transaction(
            basket["id"], make_store_operator_headers(grocery_id)
        ),
        ApiErrorId.ERR_CYCLE_NOT_OPEN.value,
    )

    _cycles, cycle_meta = validate_paginated(
        api_client.list_point_cycles(
            ADMIN, {"banner_id": program["banner"]["id"], "status": "OPEN"}
        )
    )
    assert cycle_meta["total_count"] == 2
    _rows, ledger_meta = validate_paginated(
        api_client.list_point_ledger_entries(ADMIN, {"member_id": member_id})
    )
    assert ledger_meta["total_count"] == 0


def test_one_thousandth_of_a_gallon_over_the_authorization_is_a_hard_refusal():
    """The authorized volume is an inclusive ceiling read at the third decimal,
    and an over-dispense is never clamped down to it.

    PRD: "Over-dispense is a **hard rejection** with
    `ERR_GALLONS_EXCEED_AUTHORIZATION`, never a silent clamp down to
    `gallons_authorized`; when it is rejected the redemption stays `AUTHORIZED`,
    `discount_amount_cents` stays null, and nothing else moves."

    PRD: "A volume exactly equal to `gallons_authorized` is accepted."

    PRD: "At an `OWNED_FUEL_CENTER`, `settlement_status` **stays**
    `NOT_APPLICABLE`, no site figure is recomputed and the site's `version` does not
    move; the retailer owes itself nothing."

    Design: Corner/validations/dispensing_one_thousandth_of_a_gallon_over_the_authorization_is_refused
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300,
        alt_id="6660000001",
        banner_code="CORE",
        name="Corner Banner",
        owned_max_gallons_per_redemption=35,
    )
    fuel_id = program["fuel"]["id"]
    redemption = fixtures.authorize_redemption(
        program["member"]["id"], fuel_id, "6660000001", 300
    )
    assert_gallons_equal(redemption["gallons_authorized"], "35.000")

    validate_error(
        api_client.complete_fuel_redemption(
            redemption["id"],
            {"gallons_dispensed": 35.001},
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_GALLONS_EXCEED_AUTHORIZATION.value,
    )
    refused = fixtures.get_redemption(redemption["id"])
    assert refused["authorization_status"] == "AUTHORIZED"
    assert refused["gallons_dispensed"] is None
    assert refused["discount_amount_cents"] is None

    dispensed = fixtures.complete_fill(redemption["id"], fuel_id, 35.0)

    assert dispensed["discount_amount_cents"] == 1050
    assert dispensed["settlement_status"] == "NOT_APPLICABLE"
    site = fixtures.get_site(fuel_id)
    assert_gallons_equal(site["unbatched_gallons"], "0.000")
    assert site["unbatched_discount_cents"] == 0


def test_an_empty_period_may_be_drafted_but_never_submitted():
    """Opening a batch over a month with no dispensed fills is legal; claiming
    money for it is not.

    PRD: "A new batch is `DRAFT` with `redemption_count`, `gallons_total`,
    `gross_discount_cents`, `tier_rate_pct`, `pre_fee_reimbursement_cents`,
    `admin_fee_cents` and `reimbursement_cents` all zero, and
    `submitted_by_user_id`, `approved_by_user_id`, `submitted_at` and `decided_at`
    all null."

    PRD: "Submission requires the batch to be `DRAFT`, the site to be `ACTIVE`
    (otherwise `ERR_SITE_SUSPENDED`), the site's banner to be `ACTIVE` (otherwise
    `ERR_BANNER_SUSPENDED`), and at least one redemption at that site to have
    `settlement_status` `PENDING` with a `dispensed_at` inside the batch's inclusive
    period — a period with nothing settleable in it is rejected with
    `ERR_NO_SETTLEABLE_GALLONS`."

    Design: Corner/validations/submitting_a_batch_with_no_pending_gallons_is_refused
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    partner = fixtures.create_partner_station(
        banner["id"], site_number="P-100", partner_code="PTR100"
    )

    batch = fixtures.open_batch(partner["id"], AUGUST_START, AUGUST_END)
    assert batch["status"] == "DRAFT"
    assert batch["redemption_count"] == 0
    assert_gallons_equal(batch["gallons_total"], "0.000")

    validate_error(
        api_client.submit_settlement_batch(
            batch["id"], make_settlement_clerk_headers(partner["id"])
        ),
        ApiErrorId.ERR_NO_SETTLEABLE_GALLONS.value,
    )

    read = fixtures.get_batch(batch["id"])
    assert read["status"] == "DRAFT"
    assert read["submitted_by_user_id"] is None
    assert read["submitted_at"] is None


def test_a_month_cannot_be_retired_before_the_month_that_precedes_it():
    """Cycles are retired in month order, and the refused August close succeeds
    unchanged once July is closed.

    PRD: "The cycle must currently be `OPEN`; the logical clock must be **strictly
    after** its `closes_at`, or the request is refused with `ERR_CYCLE_NOT_ENDED`;
    and every cycle of the same banner whose `cycle_month` sorts lexicographically
    before this one must already be `CLOSED`, or the request is refused with
    `ERR_PRIOR_CYCLE_NOT_CLOSED`."

    PRD: "**Prior-cycle ordering.** `POST /point-cycles/{id}/begin-close`
    additionally requires every cycle of the same banner with a lexicographically
    smaller `cycle_month` to be `CLOSED` — otherwise `ERR_PRIOR_CYCLE_NOT_CLOSED`."

    Design: Corner/validations/closing_august_is_refused_while_july_is_still_open
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    cycles = fixtures.create_month_cycles(
        banner["id"], ("2026-07", "2026-08", "2026-09")
    )
    july_id = cycles["2026-07"]["id"]
    august_id = cycles["2026-08"]["id"]
    fixtures.set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api_client.begin_close_point_cycle(august_id, SUPERVISOR),
        ApiErrorId.ERR_PRIOR_CYCLE_NOT_CLOSED.value,
    )
    assert (
        validate_success(api_client.get_point_cycle(august_id, ADMIN))["status"]
        == "OPEN"
    )

    fixtures.begin_close(july_id)
    july = fixtures.close_cycle(july_id)
    assert july["status"] == "CLOSED"
    assert_instant_equals(july["closed_at"], "2026-09-01T00:00:00Z")

    august = fixtures.begin_close(august_id)
    assert august["status"] == "CLOSING"


def test_a_dispute_must_name_its_filer_s_own_row_and_a_denied_predecessor():
    """A housemate cannot dispute someone else's row, and a refiling waits for the
    dispute it replaces to be denied.

    PRD: "The disputed ledger row must belong to the member the dispute names, or
    the filing is rejected with `ERR_DISPUTE_ENTRY_MEMBER_MISMATCH`."

    PRD: "A refiling is only legal when the superseded dispute is in
    `RESOLVED_DENIED` status and the resulting chain is at most three disputes long
    — a fourth link, or a superseded dispute in any other status, is refused with
    `ERR_SUPERSEDE_CHAIN_TOO_LONG`."

    PRD: "Denying from `INVESTIGATING` sets `status` to `RESOLVED_DENIED` and
    stamps `resolved_at`, writes **no** ledger row, and unlocks refiling — a new
    dispute may now name this one in its `supersedes_dispute_id`."

    Design: Corner/validations/dispute_filing_checks_entry_ownership_and_the_supersede_chain
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(
        program["household"]["id"], housemate["id"], "SECONDARY", activate=True
    )
    transfer_out = fixtures.transfer_points(
        member_id, housemate["id"], 100, headers=make_member_headers(member_id)
    )
    dispute = fixtures.file_dispute(
        member_id,
        transfer_out["id"],
        100,
        "UNAUTHORIZED_REDEMPTION",
        headers=make_member_headers(member_id),
    )

    validate_error(
        api_client.create_point_dispute(
            factories.point_dispute_payload(
                housemate["id"], transfer_out["id"], 100, "MISSING_ACCRUAL"
            ),
            make_member_headers(housemate["id"]),
        ),
        ApiErrorId.ERR_DISPUTE_ENTRY_MEMBER_MISMATCH.value,
    )
    validate_error(
        api_client.create_point_dispute(
            factories.point_dispute_payload(
                member_id,
                transfer_out["id"],
                100,
                "UNAUTHORIZED_REDEMPTION",
                supersedes_dispute_id=dispute["id"],
            ),
            make_member_headers(member_id),
        ),
        ApiErrorId.ERR_SUPERSEDE_CHAIN_TOO_LONG.value,
    )

    fixtures.investigate_dispute(dispute["id"])
    fixtures.deny_dispute(dispute["id"])
    refiled = fixtures.file_dispute(
        member_id,
        transfer_out["id"],
        100,
        "UNAUTHORIZED_REDEMPTION",
        headers=make_member_headers(member_id),
        supersedes_dispute_id=dispute["id"],
    )

    assert refiled["status"] == "FILED"
    assert refiled["supersedes_dispute_id"] == dispute["id"]
    chain, meta = validate_paginated(
        api_client.list_point_disputes(ADMIN, {"supersedes_dispute_id": dispute["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in chain] == [refiled["id"]]
