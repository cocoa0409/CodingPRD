"""Capacity, uniqueness, precondition and priority-ordering rejections."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage, assert_burden, assert_money
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ANALYST_HEADERS,
    MANAGER_ALT_HEADERS,
    MANAGER_HEADERS,
    OPERATOR_HEADERS,
)


def test_a_unit_may_be_committed_to_the_acre_but_not_past_it(api):
    """320.0000 plus 960.0000 exactly fills 1280.0000; one ten-thousandth more fails.

    PRD: "The sum of `allocated_acres` across the unit's allocations whose
    `allocation_status` is `ACTIVE` or `PUGH_RELEASED`, plus the requested
    `allocated_acres`, rounded to 4 decimal places, must not exceed the unit's
    `unit_gross_acres`. Equality is allowed — a unit may be committed to the acre.
    Exceeding it is `ERR_UNIT_ACREAGE_OVERSUBSCRIBED`."

    Design: Corner/validations/unit_capacity_exact_equality_accepted_then_next_acre_oversubscribes
    """
    first = fx.create_certified_tract(api)
    second = fx.create_certified_tract(api, gross_acres=1280.0000, operator_activity_tier="MODERATE")
    third = fx.create_certified_tract(api, operator_activity_tier="LOW")
    unit = fx.create_unit(api, unit_name="Reeves Unit 31H")

    fx.create_allocation(api, unit["id"], first["id"], allocated_acres=320.0000)
    fx.create_allocation(api, unit["id"], second["id"], allocated_acres=960.0000)
    filled = fx.read_unit(api, unit["id"])
    assert_acreage(filled["unallocated_acres"], "0.0000", "unallocated_acres")
    assert filled["active_allocation_count"] == 2

    response = api.create_allocation(
        f.allocation_payload(unit["id"], third["id"], allocated_acres=0.0001), OPERATOR_HEADERS
    )

    validate_error(response, "ERR_UNIT_ACREAGE_OVERSUBSCRIBED", 422)
    reread = fx.read_unit(api, unit["id"])
    assert_acreage(reread["unallocated_acres"], "0.0000", "unallocated_acres")
    assert reread["active_allocation_count"] == 2


def test_the_overlap_rule_outranks_the_capacity_rule(api):
    """A request breaking both rules reports the lower-numbered overlap rung.

    PRD: "When more than one rule could reject a request, the rule that fires is
    always the lowest-numbered rule in the ladder below, and the client sees that
    rule's error and status."

    Design: Corner/validations/overlapping_interval_beats_oversubscribed_acreage
    """
    world = fx.unit_with_allocation_ready(api, unit_overrides={"unit_name": "Reeves Unit 32H"})

    response = api.create_allocation(
        f.allocation_payload(
            world["unit"]["id"],
            world["tract"]["id"],
            allocated_acres=1000.0000,
            effective_from="2027-01-01",
            effective_to="2029-01-01",
        ),
        OPERATOR_HEADERS,
    )

    validate_error(response, "ERR_ALLOCATION_INTERVAL_OVERLAP", 409)
    unit = fx.read_unit(api, world["unit"]["id"])
    assert_acreage(unit["unallocated_acres"], "960.0000", "unallocated_acres")
    assert unit["active_allocation_count"] == 1


def test_the_capacity_rule_is_live_once_the_overlap_is_gone(api):
    """The same oversized request over a free window earns the capacity error.

    PRD: "46. (Priority 80) Unit acreage capacity is not oversubscribed — otherwise
    `ERR_UNIT_ACREAGE_OVERSUBSCRIBED` (422). Guards committing acreage."

    Design: Corner/validations/overlapping_interval_beats_oversubscribed_acreage
    """
    world = fx.unit_with_allocation_ready(api, unit_overrides={"unit_name": "Reeves Unit 32H"})

    response = api.create_allocation(
        f.allocation_payload(
            world["unit"]["id"],
            world["tract"]["id"],
            allocated_acres=1000.0000,
            effective_from="2028-01-01",
            effective_to="2029-01-01",
        ),
        OPERATOR_HEADERS,
    )

    validate_error(response, "ERR_UNIT_ACREAGE_OVERSUBSCRIBED", 422)


def test_a_repeated_book_page_on_the_same_tract_is_refused(api):
    """The clerk's citation is unique per tract chain.

    PRD: "A `county_book_page` that already appears on this tract's chain is
    rejected with `ERR_DUPLICATE_BOOK_PAGE`; uniqueness is scoped per tract, so the
    same citation may legitimately appear on two different tracts."

    Design: Corner/validations/duplicate_county_book_page_on_same_tract_returns_400_class_conflict
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(api, tract["id"], f.deed_entry_payload())

    response = api.create_title_chain_entry(
        tract["id"],
        f.deed_entry_payload(instrument_date="1960-04-04", conveyed_acres=10.0000),
        ANALYST_HEADERS,
    )

    validate_error(response, "ERR_DUPLICATE_BOOK_PAGE", 409)
    assert (
        validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)["chain_entry_count"] == 2
    )


def test_a_second_line_for_the_same_month_and_product_is_refused(api):
    """OIL for 2026-06 is already reported; GAS for 2026-06 is a different stream.

    PRD: "The line's `severance_tax_rate` is looked up from the statutory table by
    the unit's `state_code` and the line's `product_code`. Texas withholds 4.6000
    percent on oil and on natural-gas liquids and 7.5000 percent on gas; Oklahoma
    withholds a flat 7.0000 percent across all three streams; New Mexico withholds a
    flat 3.7500 percent across all three; and North Dakota withholds 5.0000 percent
    on oil and on liquids and 6.5000 percent on gas."

    Design: Corner/validations/duplicate_production_month_for_same_product_is_rejected
    """
    world = fx.executed_division_order_ready(api)
    fx.report_revenue(api, world["order"]["id"], operator_decimal_used=0.00195313)

    duplicate = api.create_revenue_check_detail(
        world["order"]["id"],
        f.revenue_check_detail_payload(
            gross_volume=900.0000, gross_value=55000.00, operator_decimal_used=0.00195313
        ),
        OPERATOR_HEADERS,
    )
    validate_error(duplicate, "ERR_DUPLICATE_PRODUCTION_MONTH", 409)

    gas = fx.report_revenue(
        api,
        world["order"]["id"],
        product_code="GAS",
        gross_volume=9000.0000,
        gross_value=21000.00,
        operator_decimal_used=0.00195313,
    )

    assert_money(gas["reported_gross_royalty"], "41.02", "reported_gross_royalty")
    assert_money(gas["severance_tax_amount"], "3.08", "severance_tax_amount")
    assert_money(gas["net_amount"], "37.94", "net_amount")
    assert_money(
        fx.read_division_order(api, world["order"]["id"])["paid_net_total"],
        "153.46",
        "paid_net_total",
    )


def test_a_defect_cannot_impair_more_acreage_than_was_bought(api):
    """50.0000 acres exceeds the 40.0000 bought; exactly 40.0000 is accepted.

    PRD: "50. (Priority 84) A defect cannot impair more acreage than was bought —
    otherwise `ERR_DEFECT_ACREAGE_EXCEEDS_INTEREST` (422). Guards raising a defect."

    Design: Corner/validations/defect_acreage_above_interest_net_acres_is_rejected
    """
    world = fx.psa_ready(api)

    too_big = api.create_title_defect(
        world["psa"]["id"],
        f.title_defect_payload(
            defect_type="UNRELEASED_LEASE",
            affected_nma=50.0000,
            description="Lien clouding more acreage than the interest holds",
        ),
        ANALYST_HEADERS,
    )
    validate_error(too_big, "ERR_DEFECT_ACREAGE_EXCEEDS_INTEREST", 422)

    exact = fx.raise_defect(
        api,
        world["psa"]["id"],
        defect_type="UNRELEASED_LEASE",
        affected_nma=40.0000,
        description="Lien clouding the entire interest",
    )

    assert exact["defect_status"] == "RAISED"
    assert_acreage(exact["affected_nma"], "40.0000", "affected_nma")


def test_an_interest_cannot_be_carved_from_an_uncertified_tract(api):
    """The carve waits for certification, then freezes 40.0000 acres.

    PRD: "The tract must be `CERTIFIED` at this moment, or the request is
    `ERR_TRACT_NOT_CERTIFIED`."

    Design: Corner/validations/mineral_interest_on_research_tract_returns_tract_not_certified
    """
    tract = fx.create_tract(api)
    fx.add_canonical_chain(api, tract["id"])
    owner = fx.create_owner(api)

    early = api.create_mineral_interest(
        f.mineral_interest_payload(tract["id"], owner["id"]), MANAGER_HEADERS
    )
    validate_error(early, "ERR_TRACT_NOT_CERTIFIED", 409)

    fx.certify_tract(api, tract["id"])
    interest = fx.create_interest(api, tract["id"], owner["id"])

    assert_acreage(interest["net_mineral_acres"], "40.0000", "net_mineral_acres")
    assert_burden(interest["existing_burden_fraction"], "0.0625", "existing_burden_fraction")
    assert interest["interest_status"] == "PROSPECT"
    assert interest["current_valuation_id"] is None


def test_an_offer_needs_a_live_valuation_behind_it(api):
    """No valuation, no bid band, no offer; filing one unblocks the identical bid.

    PRD: "15. (Priority 24) A live valuation exists for the interest — otherwise
    `ERR_NO_CURRENT_VALUATION` (409). Guards issuing an offer letter and revising
    one."

    Design: Corner/validations/offer_letter_without_current_valuation_returns_no_current_valuation
    """
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    interest = fx.create_interest(api, tract["id"], owner["id"])

    early = api.create_offer_letter(
        interest["id"], f.offer_letter_payload(), MANAGER_ALT_HEADERS
    )
    validate_error(early, "ERR_NO_CURRENT_VALUATION", 409)
    unchanged = fx.read_interest(api, interest["id"])
    assert unchanged["interest_status"] == "PROSPECT"
    assert unchanged["current_valuation_id"] is None

    fx.create_valuation(api, interest["id"])
    offer = fx.create_offer(api, interest["id"])

    assert offer["offer_status"] == "SENT"
    assert fx.read_interest(api, interest["id"])["interest_status"] == "OFFERED"


def test_accepting_a_lapsed_offer_expires_it_and_then_fails(api):
    """The lazy transition lands durably before the acceptance is refused.

    PRD: "At the start of a counter, a revision or an acceptance, if the letter's
    `offer_status` is `SENT`, `COUNTERED` or `REVISED` and the logical clock's date
    is strictly after `expires_on`, the system first drives the letter
    `SENT → EXPIRED` (or from whichever of those three postures it held), sets the
    interest's `interest_status` to `RELEASED`, and only then rejects the triggering
    write with `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/accepting_an_expired_offer_returns_offer_expired
    """
    world = fx.offer_ready(api)
    fx.set_clock(api, "2026-09-02T00:00:00Z")

    response = api.accept_offer_letter(
        world["offer"]["id"], fx.make_royalty_owner_headers(world["owner"]["id"])
    )

    validate_error(response, "ERR_OFFER_EXPIRED", 409)
    offer = fx.read_offer(api, world["offer"]["id"])
    assert offer["offer_status"] == "EXPIRED"
    assert offer["accepted_at"] is None
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "RELEASED"


def test_the_expiry_error_is_reachable_only_once(api):
    """EXPIRED is terminal, so the second acceptance hits the state rung instead.

    PRD: "`ACCEPTED`, `REJECTED`, `EXPIRED` and `VOIDED` are all terminal postures
    for an offer letter; the fourth of them, `VOIDED`, is reached only by the cascade
    described in §3.5."

    Design: Corner/validations/accepting_an_expired_offer_returns_offer_expired
    """
    world = fx.offer_ready(api)
    fx.set_clock(api, "2026-09-02T00:00:00Z")
    owner_headers = fx.make_royalty_owner_headers(world["owner"]["id"])
    api.accept_offer_letter(world["offer"]["id"], owner_headers)

    second = api.accept_offer_letter(world["offer"]["id"], owner_headers)

    validate_error(second, "ERR_OFFER_STATE_INVALID", 409)
    assert fx.read_offer(api, world["offer"]["id"])["offer_status"] == "EXPIRED"


def test_no_disbursement_without_a_tax_form_on_file(api):
    """The release waits for tax_id_on_file, then pays the same 106.47.

    PRD: "That owner's `tax_id_on_file` must be true, or the request is
    `ERR_OWNER_TAX_ID_MISSING` — the firm does not disburse without a signed
    tax-identification form."

    Design: Corner/validations/suspense_release_without_tax_id_returns_owner_tax_id_missing
    """
    world = fx.variance_held_ready(api, owner_overrides={"tax_id_on_file": False})

    response = api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS)

    validate_error(response, "ERR_OWNER_TAX_ID_MISSING", 409)
    account = fx.read_suspense(api, world["suspense"]["id"])
    assert account["suspense_status"] == "ACCRUING"
    assert account["suspense_reason"] == "DECIMAL_VARIANCE"
    assert_money(account["accrued_amount"], "106.47", "accrued_amount")
    assert account["released_by_user_id"] is None

    fx.patch_owner(api, world["owner"]["id"], {"tax_id_on_file": True})
    released = validate_success(
        api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS), 200
    )
    assert released["suspense_status"] == "RELEASED"


def test_the_escheat_reason_gate_fires_before_the_dormancy_gate(api):
    """A variance-held account is refused for its reason, not its two months.

    PRD: "29. (Priority 54) Escheat is only lawful for an unlocatable-owner account
    — otherwise `ERR_ESCHEAT_REASON_INVALID` (409). Guards escheat."

    PRD: "34. (Priority 64) The statutory dormancy period has elapsed — otherwise
    `ERR_ESCHEAT_PERIOD_NOT_ELAPSED` (409). Guards escheat."

    Design: Corner/validations/escheat_reason_check_precedes_escheat_period_check
    """
    world = fx.variance_held_ready(api)

    response = api.escheat_suspense(
        world["suspense"]["id"], f.escheat_payload(), ADMIN_ALT_HEADERS
    )

    validate_error(response, "ERR_ESCHEAT_REASON_INVALID", 409)
    account = fx.read_suspense(api, world["suspense"]["id"])
    assert account["suspense_status"] == "ACCRUING"
    assert account["escheat_state_code"] is None
    assert account["months_held"] == 2
    assert_money(account["interest_accrued"], "1.06", "interest_accrued")
