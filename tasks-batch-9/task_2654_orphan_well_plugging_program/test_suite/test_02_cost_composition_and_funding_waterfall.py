"""Multi-term cost composition and the single-pass funding waterfall."""

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_cents, assert_fields, updated
from test_helpers.constants import CANONICAL_JOB_ESTIMATE


def _mobilized_job(api):
    """One MOBILIZED job on the canonical contract, ready for a field report."""
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-09-01T00:00:00Z")
    fx.mobilize(api, bundle["job"]["id"])
    return bundle


def test_administrative_fee_is_rounded_per_line_item_before_it_is_summed(api):
    """The 4.25 percent fee is quantised line by line, not once on the subtotal.

    The four line items 488166 / 3399996 / 776320 / 2499999 sum to 7164481, and their
    individual fees 20747 + 144500 + 32994 + 106250 sum to 304491, one cent more than
    the 304490 that a single fee on the subtotal would yield, so the round cost is
    7468972. A second round then bills half the mobilization fee and adds 2275505.

    PRD: "the fee is computed on each line item separately and rounded half up to
    whole cents *per line*, and only then are the four rounded fees added together to
    form the administrative fee for the round. Applying 4.25 percent to the combined
    line subtotal and rounding once produces a different number and is wrong."

    Design: Difficulty/combinatorial_formula/admin_fee_rounded_per_line_then_summed_plus_remobilization_branch
    """
    bundle = _mobilized_job(api)
    job_id = bundle["job"]["id"]
    contract_id = bundle["contract"]["id"]
    assert_cents(
        bundle["job"]["plugging_cost_estimate_cents"],
        CANONICAL_JOB_ESTIMATE,
        "plugging_cost_estimate_cents",
    )

    first = fx.file_field_report(
        api,
        job_id,
        cement_sacks_used=118,
        rig_days_used=4,
        casing_removed_ft=640,
        downhole_conditions="open annulus 3880-4200 ft; no casing collapse observed",
        plug_intervals=[
            {"top_ft": 3900, "bottom_ft": 4200, "sacks": 60},
            {"top_ft": 0, "bottom_ft": 120, "sacks": 58},
        ],
    )
    assert_cents(first["last_round_cost_cents"], 7468972, "round one cost")
    assert_cents(first["actual_cost_cents"], 7468972, "cumulative actual cost")
    assert_cents(
        updated(api.get_unit_cost_contract(contract_id, users.PROCUREMENT))[
            "obligated_cents"
        ],
        7468972,
        "obligated_cents after round one",
    )

    reworked = fx.review_job(api, job_id, "REWORK", "surface plug top too deep")
    assert_fields(reworked, status="REWORK_REQUIRED", rework_round=1)

    second = fx.file_field_report(
        api,
        job_id,
        cement_sacks_used=20,
        rig_days_used=1,
        casing_removed_ft=0,
        downhole_conditions="surface plug re-set 0-60 ft",
        plug_intervals=[{"top_ft": 0, "bottom_ft": 60, "sacks": 20}],
    )
    assert_cents(second["last_round_cost_cents"], 2275505, "round two cost")
    assert_cents(second["actual_cost_cents"], 9744477, "cumulative actual cost")
    assert_fields(second, status="FIELD_REPORTED")

    contract = updated(api.get_unit_cost_contract(contract_id, users.PROCUREMENT))
    assert_cents(contract["obligated_cents"], 9744477, "obligated_cents after round two")
    assert_fields(contract, status="ACTIVE")


def test_identical_field_quantities_cost_less_on_a_rework_round(api):
    """The mobilization line is the only term that depends on the round number.

    The same 20 sacks, one rig day and no casing recovery bills 3578629 as round one,
    which carries the whole 2499999 mobilization fee, and 2275505 as round two, which
    carries only 1250000 of it. Because both rounds together stay under the 6070196
    estimate, the contract obligation is still held at the estimate.

    PRD: "The mobilization line is the contract's full `mobilization_fee_cents` on
    round number 1, and on every later round it is half of that fee - 50 percent of
    `mobilization_fee_cents`, rounded half up to whole cents - because a
    remobilization costs less than an original mobilization."

    Design: Difficulty/combinatorial_formula/admin_fee_rounded_per_line_then_summed_plus_remobilization_branch
    """
    bundle = _mobilized_job(api)
    job_id = bundle["job"]["id"]
    contract_id = bundle["contract"]["id"]

    quantities = dict(
        cement_sacks_used=20,
        rig_days_used=1,
        casing_removed_ft=0,
        downhole_conditions="upper plug re-set with returns",
        plug_intervals=[{"top_ft": 0, "bottom_ft": 60, "sacks": 20}],
    )

    first = fx.file_field_report(api, job_id, **quantities)
    assert_cents(first["last_round_cost_cents"], 3578629, "round one cost")
    assert_cents(first["actual_cost_cents"], 3578629, "cumulative actual cost")

    fx.review_job(api, job_id, "REWORK", "tag test still not documented")
    second = fx.file_field_report(api, job_id, **quantities)

    assert_cents(second["last_round_cost_cents"], 2275505, "round two cost")
    assert second["last_round_cost_cents"] < first["last_round_cost_cents"], (
        "the remobilization branch must bill less than the first mobilization"
    )
    assert_cents(second["actual_cost_cents"], 5854134, "cumulative actual cost")

    contract = updated(api.get_unit_cost_contract(contract_id, users.PROCUREMENT))
    assert_cents(
        contract["obligated_cents"],
        CANONICAL_JOB_ESTIMATE,
        "obligated_cents while actual stays below the estimate",
    )


def test_the_federal_cap_is_fixed_by_the_base_committed_ahead_of_the_grant(api):
    """A 40 percent grant is throttled by the 1000000 forfeited bond above it.

    The waterfall runs bond, then grant, then state fund. At the grant's turn only
    1000000 of non federal money has been committed, so its entitlement is
    floor(1000000 * 60 / 40) = 1500000; the 3570196 the state fund puts in afterwards
    never raises that entitlement to 6855294.

    PRD: "It is a **single pass with a pinned order**: non-federal cents committed
    *later* in the same pass - a `STATE_FUND` reached after the grant - do not
    retroactively raise the grant's entitlement cap, and the waterfall never runs a
    second pass to try again."

    Design: Difficulty/combinatorial_formula/federal_match_cap_single_pass_no_retroactive_match_expansion
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-09-01T00:00:00Z")
    job_id = bundle["job"]["id"]
    operator_id = bundle["operator"]["id"]

    bond = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Forfeited bond - Basin Orphan Holdings",
        authorized_cents=1000000,
        bond_operator_id=operator_id,
    )
    federal = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-06-30T00:00:00Z",
        federal_match_required_pct=40,
    )
    state = fx.make_funding_source(
        api, kind="STATE_FUND", name="Oilfield cleanup fund", authorized_cents=10000000
    )

    allocations = fx.commit_funding(api, job_id)
    assert len(allocations) == 3, "expected three allocations, got %r" % (allocations,)

    by_rank = {row["waterfall_rank"]: row for row in allocations}
    assert sorted(by_rank) == [1, 2, 3], "unexpected ranks: %r" % (allocations,)
    assert_fields(by_rank[1], source_id=bond["id"])
    assert_cents(by_rank[1]["allocated_cents"], 1000000, "bond allocation")
    assert_fields(by_rank[2], source_id=federal["id"])
    assert_cents(by_rank[2]["allocated_cents"], 1500000, "grant allocation")
    assert_fields(by_rank[3], source_id=state["id"])
    assert_cents(by_rank[3]["allocated_cents"], 3570196, "state fund allocation")

    federal_row = updated(api.get_funding_source(federal["id"], users.FUNDING))
    assert_cents(federal_row["committed_cents"], 1500000, "grant committed_cents")
    bond_row = updated(api.get_funding_source(bond["id"], users.FUNDING))
    assert_cents(bond_row["committed_cents"], 1000000, "bond committed_cents")
    assert_fields(bond_row, status="EXHAUSTED")
    state_row = updated(api.get_funding_source(state["id"], users.FUNDING))
    assert_cents(state_row["committed_cents"], 3570196, "state fund committed_cents")
    assert_fields(state_row, status="ACTIVE")

    job = updated(api.get_plugging_job(job_id, users.FUNDING))
    assert_cents(job["funded_cents"], CANONICAL_JOB_ESTIMATE, "funded_cents")


def test_doubling_the_bond_ahead_of_the_grant_doubles_the_grants_entitlement(api):
    """The entitlement tracks only what was committed before the grant's turn.

    With a 2000000 forfeited bond at rank 1 the same 40 percent grant may put in
    floor(2000000 * 60 / 40) = 3000000 rather than 1500000, and the state fund is left
    with the 1070196 remainder. The grant is still not lifted to floor(3070196 * 60 /
    40) by that remainder.

    PRD: "otherwise the cap is the non-federal cents already committed on this job at
    the moment this source is evaluated, multiplied by 100 minus the required match
    percentage, divided by the required match percentage, with that quotient taken
    **as a floor**".

    Design: Difficulty/combinatorial_formula/federal_match_cap_single_pass_no_retroactive_match_expansion
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-09-01T00:00:00Z")
    job_id = bundle["job"]["id"]

    bond = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Forfeited bond - larger call",
        authorized_cents=2000000,
        bond_operator_id=bundle["operator"]["id"],
    )
    federal = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-06-30T00:00:00Z",
        federal_match_required_pct=40,
    )
    state = fx.make_funding_source(
        api, kind="STATE_FUND", name="Oilfield cleanup fund", authorized_cents=10000000
    )

    allocations = fx.commit_funding(api, job_id)
    by_rank = {row["waterfall_rank"]: row for row in allocations}
    assert sorted(by_rank) == [1, 2, 3], "unexpected ranks: %r" % (allocations,)

    assert_fields(by_rank[1], source_id=bond["id"])
    assert_cents(by_rank[1]["allocated_cents"], 2000000, "bond allocation")
    assert_fields(by_rank[2], source_id=federal["id"])
    assert_cents(by_rank[2]["allocated_cents"], 3000000, "grant allocation")
    assert_fields(by_rank[3], source_id=state["id"])
    assert_cents(by_rank[3]["allocated_cents"], 1070196, "state fund allocation")

    assert_cents(
        updated(api.get_funding_source(federal["id"], users.FUNDING))["committed_cents"],
        3000000,
        "grant committed_cents",
    )
    assert_cents(
        updated(api.get_plugging_job(job_id, users.FUNDING))["funded_cents"],
        CANONICAL_JOB_ESTIMATE,
        "funded_cents",
    )
