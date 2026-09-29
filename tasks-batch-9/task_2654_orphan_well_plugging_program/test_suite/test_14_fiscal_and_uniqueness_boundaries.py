"""Uniqueness, limit and fiscal gates, each pinned to the cent or the counter it turns on."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_null_fields,
    assert_page,
    assert_score,
)
from test_helpers.constants import ROUND_BID_RATES, ROUND_BID_UNIT_COST

SOLVENT_WELL = dict(spud_year=1961, total_depth_ft=2500, casing_strings=1)
SECOND_BID_RATES = {
    "cement_per_sack_cents": 4100,
    "rig_day_rate_cents": 810000,
    "casing_per_ft_cents": 1250,
    "mobilization_fee_cents": 2450000,
}
OVER_CEILING_RATES = {
    "cement_per_sack_cents": 10000,
    "rig_day_rate_cents": 3000000,
    "casing_per_ft_cents": 5000,
    "mobilization_fee_cents": 5000000,
}


def test_a_bid_that_breaks_three_rules_at_once_reports_the_duplicate(api):
    """One request violates duplication, the deadline and the ceiling together.

    The declared order settles which of the three answers, and the two later rules are
    then shown to be live in isolation: the same over-ceiling basket reports the deadline
    on a solicitation the contractor has no bid on, and reports the ceiling on a
    solicitation whose deadline is months away.

    PRD: "**Uniqueness and limit constraints**, in this order: `ERR_DUPLICATE_BID`,
    `ERR_DUPLICATE_PRODUCTION_MONTH`, `ERR_BID_DEADLINE_PASSED`,
    `ERR_TECHNICAL_SCORE_BELOW_MINIMUM`, `ERR_BID_EXCEEDS_CEILING`, `ERR_NO_RESPONSIVE_BIDS`"

    Design: Corner/validations/duplicate_late_over_ceiling_bid_reports_the_duplicate_first
    """
    incumbent = fx.make_contractor(
        api, name="Bighorn Plugging", license_number="P-A0001", performance_score=89
    )
    rival = fx.make_contractor(
        api, name="Teton Cementing", license_number="P-A0002", performance_score=91
    )
    outsider = fx.make_contractor(
        api,
        name="Laramie Wellhead Services",
        license_number="P-A0003",
        performance_score=77,
    )
    closing_soon = fx.make_open_solicitation(
        api, scope_description="district 6 orphan well plugging"
    )
    held_bid = fx.place_bid(
        api,
        closing_soon["id"],
        incumbent["id"],
        rates=ROUND_BID_RATES,
        technical_score=80,
    )
    closing_later = fx.make_open_solicitation(
        api,
        scope_description="district 7 orphan well plugging",
        bid_due_at="2026-12-31T00:00:00Z",
    )
    fx.set_clock(api, "2026-08-21T00:00:00Z")

    duplicate = api.create_bid(
        closing_soon["id"],
        f.bid_payload(incumbent["id"], rates=OVER_CEILING_RATES, technical_score=88),
        users.PROCUREMENT,
    )
    validate_error(duplicate, e.ERR_DUPLICATE_BID, 409)

    late = api.create_bid(
        closing_soon["id"],
        f.bid_payload(rival["id"], rates=OVER_CEILING_RATES, technical_score=88),
        users.PROCUREMENT,
    )
    validate_error(late, e.ERR_BID_DEADLINE_PASSED, 422)

    too_expensive = api.create_bid(
        closing_later["id"],
        f.bid_payload(outsider["id"], rates=OVER_CEILING_RATES, technical_score=88),
        users.PROCUREMENT,
    )
    validate_error(too_expensive, e.ERR_BID_EXCEEDS_CEILING, 422)

    assert_page(
        api.list_bids(users.PROCUREMENT, {"solicitation_id": closing_soon["id"]}),
        1,
        expected_total=1,
    )
    assert_page(
        api.list_bids(users.PROCUREMENT, {"solicitation_id": closing_later["id"]}),
        0,
        expected_total=0,
    )
    survivor = fx.read_bid(api, held_bid["id"])
    assert_fields(survivor, status="SUBMITTED")
    assert_cents(
        survivor["evaluated_unit_cost_cents"],
        ROUND_BID_UNIT_COST,
        "evaluated_unit_cost_cents",
    )


def test_the_same_production_month_cannot_be_filed_twice(api):
    """The ledger refuses a second row for a month it already holds.

    The duplicate carries a wildly different volume, so an implementation that appended it
    would show up immediately in the well's aggregate; and the later back-filled month
    proves the stored high-water mark only ever advances.

    PRD: "A month may be reported only once per well; a second attempt for the same well
    and the same month is rejected with `ERR_DUPLICATE_PRODUCTION_MONTH` (HTTP 409). When
    the reported `month` is later than the value already stored, the well's
    `last_production_month` advances to it"

    Design: Corner/validations/reporting_the_same_production_month_twice_is_rejected
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )
    well = fx.make_well(api, operator["id"], **SOLVENT_WELL)
    well_id = well["id"]

    first = fx.report_production(api, well_id, "2026-05", oil_bbl=10)
    assert_fields(first, month="2026-05")
    assert_score(first["boe"], 10.0, "boe")

    duplicate = api.create_production_record(
        well_id, f.production_payload("2026-05", 999, 0), users.INSPECTOR
    )
    validate_error(duplicate, e.ERR_DUPLICATE_PRODUCTION_MONTH, 409)
    assert_score(
        fx.read_well(api, well_id)["cumulative_boe_60mo"], 10.00, "cumulative_boe_60mo"
    )

    back_filled = fx.report_production(api, well_id, "2026-04", oil_bbl=5)
    assert_fields(back_filled, month="2026-04")

    assert_page(
        api.list_production_records(well_id, users.INSPECTOR), 2, expected_total=2
    )
    final = fx.read_well(api, well_id)
    assert_fields(final, last_production_month="2026-05", idle_months=3)
    assert_score(final["cumulative_boe_60mo"], 15.00, "cumulative_boe_60mo at the end")


def test_the_technical_minimum_binds_responsiveness_only(api):
    """The score floor guards one outcome of the evaluation endpoint, not the endpoint.

    A bid scoring 69 against a minimum of 70 cannot be called responsive, yet the same bid
    may be marked unresponsive on the spot; and a bid scoring exactly 70 is responsive,
    because the rule rejects only a strictly lower score.

    PRD: "A technical score strictly below the minimum is rejected with
    `ERR_TECHNICAL_SCORE_BELOW_MINIMUM` (HTTP 422); equality passes."

    Design: Corner/validations/responsive_evaluation_needs_the_minimum_score_but_nonresponsive_does_not
    """
    below = fx.make_contractor(
        api, name="Bighorn Plugging", license_number="P-B0001", performance_score=69
    )
    at_the_edge = fx.make_contractor(
        api, name="Teton Cementing", license_number="P-B0002", performance_score=70
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="district 8 orphan well plugging"
    )
    short_bid = fx.place_bid(
        api,
        solicitation["id"],
        below["id"],
        rates=ROUND_BID_RATES,
        technical_score=69,
    )
    edge_bid = fx.place_bid(
        api,
        solicitation["id"],
        at_the_edge["id"],
        rates=SECOND_BID_RATES,
        technical_score=70,
    )
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")

    refused = api.evaluate_bid(
        short_bid["id"], f.bid_evaluation_payload("RESPONSIVE"), users.PROCUREMENT
    )
    validate_error(refused, e.ERR_TECHNICAL_SCORE_BELOW_MINIMUM, 422)
    held = fx.read_bid(api, short_bid["id"])
    assert_fields(held, status="SUBMITTED")
    assert_null_fields(held, "nonresponsive_reason", "evaluated_by_user_id")

    marked_out = fx.evaluate_bid(
        api,
        short_bid["id"],
        "NONRESPONSIVE",
        reason="technical score 69 below the 70 minimum",
    )
    assert_fields(marked_out, status="NONRESPONSIVE")

    accepted = fx.evaluate_bid(api, edge_bid["id"], "RESPONSIVE")
    assert_fields(accepted, status="RESPONSIVE")

    assert_null_fields(fx.read_bid(api, short_bid["id"]), "price_score")
    assert_null_fields(fx.read_bid(api, edge_bid["id"]), "price_score")


def test_an_award_needs_a_responsive_bid_and_a_reevaluation_supplies_one(api):
    """The candidate pool is read at the instant of the award, not at evaluation time.

    The only bid stands at NONRESPONSIVE, so the pool is empty and the award is refused
    without a contract or a score appearing anywhere; flipping that same bid back to
    responsive fills the pool and the identical call now writes the contract.

    PRD: "The candidate pool is fixed **before any score is computed**: it is exactly the
    bids of this solicitation whose `status` is `RESPONSIVE` at the instant the award runs"
    ... "An empty pool is rejected with `ERR_NO_RESPONSIVE_BIDS` (HTTP 422)"

    Design: Corner/validations/awarding_with_no_responsive_bid_is_rejected_until_one_is_reevaluated
    """
    contractor = fx.make_contractor(
        api, name="Bighorn Plugging", license_number="P-C0001", performance_score=89
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="district 9 orphan well plugging"
    )
    solicitation_id = solicitation["id"]
    bid = fx.place_bid(
        api,
        solicitation_id,
        contractor["id"],
        rates=ROUND_BID_RATES,
        technical_score=80,
    )
    fx.advance_solicitation(api, solicitation_id, "CLOSE")
    fx.evaluate_bid(
        api, bid["id"], "NONRESPONSIVE", reason="missing bonding certificate"
    )

    refused = api.award_solicitation(solicitation_id, users.AWARD)
    validate_error(refused, e.ERR_NO_RESPONSIVE_BIDS, 422)
    assert_fields(fx.read_solicitation(api, solicitation_id), status="EVALUATING")
    assert_page(
        api.list_unit_cost_contracts(
            users.PROCUREMENT, {"solicitation_id": solicitation_id}
        ),
        0,
        expected_total=0,
    )
    unscored = fx.read_bid(api, bid["id"])
    assert_fields(unscored, status="NONRESPONSIVE")
    assert_null_fields(unscored, "price_score", "composite_score")

    revived = fx.evaluate_bid(api, bid["id"], "RESPONSIVE")
    assert_fields(revived, status="RESPONSIVE")

    contract = validate_success(
        api.award_solicitation(solicitation_id, users.AWARD), 201
    )
    assert_fields(
        contract,
        status="ACTIVE",
        winning_bid_id=bid["id"],
        awarded_by_user_id="u_award",
    )
    assert_cents(contract["obligated_cents"], 0, "obligated_cents")
    assert_cents(contract["ceiling_cents"], 20000000, "ceiling_cents")

    awarded = fx.read_bid(api, bid["id"])
    assert_fields(awarded, status="AWARDED")
    assert_score(awarded["price_score"], 100.00, "price_score")
    assert_score(awarded["composite_score"], 92.00, "composite_score")
    assert_fields(fx.read_solicitation(api, solicitation_id), status="AWARDED")


def test_a_second_reopen_is_refused_at_the_declared_limit(api):
    """The reopen ceiling is a counter, not a missing edge.

    The solicitation is back in EVALUATING with one completed reopen cycle behind it, so
    the edge it is asking for exists; it is the exhausted counter that refuses, and the
    deadline the rejected call carried is not written anywhere.

    PRD: "A second reopen attempt, made when `reopen_round` already stands at 1, is
    rejected with `ERR_REOPEN_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/a_second_reopen_is_rejected_at_the_declared_limit
    """
    solicitation = fx.make_solicitation(
        api, scope_description="district 10 orphan well plugging"
    )
    solicitation_id = solicitation["id"]
    fx.advance_solicitation(api, solicitation_id, "OPEN")
    fx.advance_solicitation(api, solicitation_id, "CLOSE")
    fx.advance_solicitation(
        api, solicitation_id, "REOPEN", new_bid_due_at="2026-08-28T00:00:00Z"
    )
    fx.advance_solicitation(api, solicitation_id, "CLOSE")

    before = fx.read_solicitation(api, solicitation_id)
    assert_fields(
        before,
        status="EVALUATING",
        reopen_round=1,
        bid_due_at="2026-08-28T00:00:00Z",
    )

    refused = api.solicitation_lifecycle(
        solicitation_id,
        f.lifecycle_payload("REOPEN", new_bid_due_at="2026-09-04T00:00:00Z"),
        users.PROCUREMENT,
    )
    validate_error(refused, e.ERR_REOPEN_LIMIT_EXCEEDED, 422)

    after = fx.read_solicitation(api, solicitation_id)
    assert_fields(
        after,
        status="EVALUATING",
        reopen_round=1,
        bid_due_at="2026-08-28T00:00:00Z",
    )


def test_a_transferee_one_cent_short_of_its_requirement_is_refused(api):
    """Approval compares the posted bond against the forward-looking requirement.

    Two transferees face the identical 250000 cent requirement and differ by a single cent
    of posted assurance: 249999 is refused and nothing moves, 250000 passes and the well,
    both counters and both requirements settle on the far side of the transfer.

    PRD: "If the posted bond is strictly less than that forward-looking requirement, the
    approval is rejected with `ERR_TRANSFEREE_ASSURANCE_INSUFFICIENT` (HTTP 422) - equality
    is sufficient and passes."

    Design: Corner/validations/approval_is_refused_when_the_transferee_is_one_cent_under_bonded
    """
    releasing = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    first_well = fx.make_well(api, releasing["id"])
    second_well = fx.make_well(api, releasing["id"])
    short = fx.make_operator(
        api,
        name="Shoshone Shell Co",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=249999,
    )
    exact = fx.make_operator(
        api,
        name="Teton Basin Resources",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=250000,
    )
    to_short = fx.transfer_well(api, first_well["id"], short["id"])
    to_exact = fx.transfer_well(api, second_well["id"], exact["id"])
    assert_cents(
        to_short["transferee_required_bond_cents"],
        250000,
        "short transferee_required_bond_cents",
    )
    assert_cents(
        to_exact["transferee_required_bond_cents"],
        250000,
        "exact transferee_required_bond_cents",
    )
    before = fx.read_operator(api, short["id"])
    assert_fields(before, status="ACTIVE", active_well_count=0)
    assert_cents(before["required_bond_cents"], 0, "required_bond_cents before")

    refused = api.decide_well_transfer(
        to_short["id"],
        f.transfer_decision_payload("APPROVE", "operator change requested"),
        users.ADMIN,
    )
    validate_error(refused, e.ERR_TRANSFEREE_ASSURANCE_INSUFFICIENT, 422)
    still_pending = validate_success(
        api.get_well_transfer(to_short["id"], users.ADMIN), 200
    )
    assert_fields(still_pending, status="PENDING")
    assert_null_fields(still_pending, "approved_at")
    assert_fields(
        fx.read_well(api, first_well["id"]), operator_id=releasing["id"]
    )
    unchanged = fx.read_operator(api, short["id"])
    assert_fields(unchanged, active_well_count=0)
    assert_cents(unchanged["required_bond_cents"], 0, "required_bond_cents after")

    approved = fx.decide_transfer(
        api, to_exact["id"], "APPROVE", "operator change requested"
    )
    assert_fields(
        approved, status="APPROVED", approved_at="2026-08-01T00:00:00Z"
    )
    assert_fields(fx.read_well(api, second_well["id"]), operator_id=exact["id"])
    receiving = fx.read_operator(api, exact["id"])
    assert_fields(receiving, status="ACTIVE", active_well_count=1)
    assert_cents(
        receiving["required_bond_cents"], 250000, "receiving required_bond_cents"
    )
    remaining = fx.read_operator(api, releasing["id"])
    assert_fields(remaining, status="ACTIVE", active_well_count=1)
    assert_cents(
        remaining["required_bond_cents"], 250000, "releasing required_bond_cents"
    )


def test_the_contract_ceiling_refuses_one_cent_over_and_accepts_exact_equality(api):
    """The ceiling is tested against the whole obligation, including the new job.

    The contract already carries 5800000 cents of obligation, so a 14204000 cent order
    would land four cents' worth of sacks over the 20000000 ceiling and is refused whole;
    one sack fewer lands the obligation exactly on the ceiling, which is not a violation.

    PRD: "If the contract's obligation computed that way, including the new job's estimate,
    would be strictly greater than the contract's `ceiling_cents`, the order is rejected
    with `ERR_CONTRACT_CEILING_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/contract_ceiling_rejects_one_cent_over_and_accepts_exact_equality
    """
    operator = fx.make_unbonded_operator(api, name="Cottonwood Energy LLC")
    first = fx.make_confirmed_orphan_well(api, operator=operator)
    second = fx.make_confirmed_orphan_well(api, operator=operator)
    procurement = fx.make_active_contract(
        api, rates=ROUND_BID_RATES, scope_description="two well plugging package"
    )
    contract_id = procurement["contract"]["id"]
    second_well_id = second["well"]["id"]

    first_job = fx.make_plugging_job(
        api,
        first["well"]["id"],
        contract_id,
        scheduled_start="2026-08-05T00:00:00Z",
    )
    assert_cents(
        first_job["plugging_cost_estimate_cents"],
        5800000,
        "plugging_cost_estimate_cents",
    )
    assert_cents(
        fx.read_contract(api, contract_id)["obligated_cents"], 5800000, "obligated_cents"
    )

    over_the_edge = api.create_plugging_job(
        f.plugging_job_payload(
            second_well_id,
            contract_id,
            scheduled_start="2026-09-01T00:00:00Z",
            planned_cement_sacks=201,
            planned_rig_days=13,
            planned_casing_ft=500,
        ),
        users.ADMIN,
    )
    validate_error(over_the_edge, e.ERR_CONTRACT_CEILING_EXCEEDED, 422)
    assert_cents(
        fx.read_contract(api, contract_id)["obligated_cents"],
        5800000,
        "obligated_cents after the rejection",
    )
    assert_fields(fx.read_well(api, second_well_id), status="ORPHAN_CONFIRMED")
    assert_page(
        api.list_plugging_jobs(users.ADMIN, {"contract_id": contract_id}),
        1,
        expected_total=1,
    )

    exactly_on_it = validate_success(
        api.create_plugging_job(
            f.plugging_job_payload(
                second_well_id,
                contract_id,
                scheduled_start="2026-09-01T00:00:00Z",
                planned_cement_sacks=200,
                planned_rig_days=13,
                planned_casing_ft=500,
            ),
            users.ADMIN,
        ),
        201,
    )
    assert_cents(
        exactly_on_it["plugging_cost_estimate_cents"],
        14200000,
        "plugging_cost_estimate_cents on the ceiling",
    )
    assert_fields(exactly_on_it, crew_window_end_at="2026-09-16T00:00:00Z")

    contract = fx.read_contract(api, contract_id)
    assert_fields(contract, status="ACTIVE")
    assert_cents(contract["obligated_cents"], 20000000, "obligated_cents on the ceiling")
    assert_fields(fx.read_well(api, second_well_id), status="PLUGGING_SCHEDULED")


def test_a_throttled_federal_grant_reports_the_match_error_not_the_shortfall(api):
    """The two funding failures are told apart by whether a match cap did the throttling.

    With only a small state fund the pass simply runs out of appropriation; adding a
    federal grant that is evaluated first, while no non-federal cents have been committed
    on this job, entitles it to nothing at all and changes the diagnosis. The grant's
    position in the ordered pool survives into the ranks of the eventual allocations.

    PRD: "When at least one `FEDERAL_GRANT` contribution was throttled below the lesser of
    the cents then needed and its own available authority by the match cap, the answer is
    `ERR_FEDERAL_MATCH_INSUFFICIENT` (HTTP 422)" ... "The match error outranks the
    shortfall error."

    Design: Corner/validations/match_throttled_shortfall_reports_the_match_error_not_the_shortfall
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-08-05T00:00:00Z")
    job_id = bundle["job"]["id"]
    assert_cents(
        bundle["job"]["plugging_cost_estimate_cents"],
        6070196,
        "plugging_cost_estimate_cents",
    )

    small = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Wyoming orphan well account - small balance",
        authorized_cents=1000000,
        expires_at="2027-12-31T00:00:00Z",
    )
    plain_shortfall = api.create_funding_commitments(job_id, users.FUNDING)
    validate_error(plain_shortfall, e.ERR_FUNDING_SHORTFALL, 422)
    assert_cents(
        fx.read_source(api, small["id"])["committed_cents"], 0, "committed_cents"
    )
    assert_cents(fx.read_job(api, job_id)["funded_cents"], 0, "funded_cents")

    federal = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-12-31T00:00:00Z",
        federal_match_required_pct=40,
    )
    throttled = api.create_funding_commitments(job_id, users.FUNDING)
    validate_error(throttled, e.ERR_FEDERAL_MATCH_INSUFFICIENT, 422)
    assert_cents(
        fx.read_source(api, federal["id"])["committed_cents"],
        0,
        "federal committed_cents",
    )
    assert_page(
        api.list_funding_allocations(users.FUNDING, {"job_id": job_id}),
        0,
        expected_total=0,
    )

    big = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Wyoming orphan well account - biennium carryover",
        authorized_cents=20000000,
        expires_at="2027-12-31T00:00:00Z",
    )
    allocations = fx.commit_funding(api, job_id)
    assert len(allocations) == 2, "expected exactly two allocations, got %r" % (
        allocations,
    )
    assert_fields(allocations[0], source_id=small["id"], waterfall_rank=2)
    assert_cents(allocations[0]["allocated_cents"], 1000000, "small allocated_cents")
    assert_fields(allocations[1], source_id=big["id"], waterfall_rank=3)
    assert_cents(allocations[1]["allocated_cents"], 5070196, "big allocated_cents")
    assert_cents(
        fx.read_source(api, federal["id"])["committed_cents"],
        0,
        "federal committed_cents at the end",
    )
    assert_cents(fx.read_job(api, job_id)["funded_cents"], 6070196, "funded_cents")


def test_a_disbursement_one_cent_over_the_allocation_is_refused(api):
    """The invoice is compared against the allocation to the cent.

    The paying officer is not the committing one, so the segregation gate is satisfied and
    cannot mask this rule; 6070197 cents against a 6070196 cent allocation is refused with
    nothing written on either the allocation or its source, and the exact figure pays.

    PRD: "and `invoice_cents` must be no greater than the allocation's `allocated_cents`,
    with a strictly greater invoice rejected as `ERR_DISBURSEMENT_EXCEEDS_ALLOCATION`
    (HTTP 422)."

    Design: Corner/validations/disbursing_one_cent_more_than_the_allocation_is_rejected
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-08-05T00:00:00Z")
    job_id = bundle["job"]["id"]
    source = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Cottonwood Energy forfeited bond",
        authorized_cents=9000000,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=bundle["operator"]["id"],
    )
    allocations = fx.commit_funding(api, job_id)
    assert len(allocations) == 1, "expected exactly one allocation, got %r" % (
        allocations,
    )
    allocation_id = allocations[0]["id"]
    assert_fields(allocations[0], committed_by_user_id="u_fund1")
    assert_cents(allocations[0]["allocated_cents"], 6070196, "allocated_cents")

    fx.mobilize(api, job_id)
    fx.file_field_report(api, job_id)

    one_cent_over = api.transition_funding_allocation(
        allocation_id,
        f.allocation_transition_payload("DISBURSE", 6070197),
        users.FUNDING_2,
    )
    validate_error(one_cent_over, e.ERR_DISBURSEMENT_EXCEEDS_ALLOCATION, 422)
    held = fx.read_allocation(api, allocation_id)
    assert_fields(held, status="COMMITTED")
    assert_cents(held["disbursed_cents"], 0, "disbursed_cents")
    assert_null_fields(held, "disbursed_at", "disbursed_by_user_id")
    unpaid_source = fx.read_source(api, source["id"])
    assert_cents(unpaid_source["disbursed_cents"], 0, "source disbursed_cents")
    assert_cents(unpaid_source["committed_cents"], 6070196, "source committed_cents")

    paid = fx.transition_allocation(
        api, allocation_id, "DISBURSE", invoice_cents=6070196
    )
    assert_fields(
        paid,
        status="DISBURSED",
        disbursed_at="2026-08-01T00:00:00Z",
        disbursed_by_user_id="u_fund2",
    )
    assert_cents(paid["disbursed_cents"], 6070196, "disbursed_cents after payment")
    final_source = fx.read_source(api, source["id"])
    assert_fields(final_source, status="ACTIVE")
    assert_cents(final_source["disbursed_cents"], 6070196, "source disbursed_cents")
    assert_cents(final_source["committed_cents"], 6070196, "source committed_cents")
