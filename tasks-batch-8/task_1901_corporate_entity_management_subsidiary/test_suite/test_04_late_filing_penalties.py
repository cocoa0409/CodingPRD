"""Late-filing penalty depth claims: the pinned per-component rounding order
and the closed/open boundary at the grace end.

Canonical calendar for this file (J1, US-DE): period-2026 filings are due
2026-12-31 with a 10-day grace period, so grace end is 2027-01-10. An entity
with 10000 authorized shares assesses 26000 cents of franchise tax.
"""
from test_helpers import (
    SEC1,
    find_filing,
    prepare_filing,
    set_clock,
    setup_base_entity,
    submit_filing,
    validate_success,
)


def _setup_prepared_franchise_filing():
    ctx = setup_base_entity(legal_name="Latefiler Inc", authorized_shares=10000)
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])
    return entity, filing


def test_late_fee_components_rounded_before_summation(api):
    """PRD 2.6: "The late-filing penalty calculation rounds each component —
    the tax component and the report-fee component — to whole cents
    individually, then sums them and applies the cap. Summing unrounded
    components and rounding once afterwards is non-conformant."
    PRD 3.7: "The tax component is `tax_assessed_cents` multiplied by 0.00037
    and then by `days_late`, rounded half-up to whole cents. The report-fee
    component is `report_fee_cents` multiplied by 0.00041 and then by
    `days_late`, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/late_fee_component_rounding_order
    """
    entity, filing = _setup_prepared_franchise_filing()
    # grace_end = 2026-12-31 + 10 days = 2027-01-10; submitting on 2027-01-14
    # puts 4 days in the half-open counting interval (grace_end, submitted].
    set_clock("2027-01-14T00:00:00Z")

    submitted = submit_filing(filing["id"])

    assert submitted["days_late"] == 4
    assert submitted["tax_assessed_cents"] == 26000
    # tax component: round_half_up(26000 * 0.00037 * 4) = round_half_up(38.48) = 38
    # report component: round_half_up(5000 * 0.00041 * 4) = round_half_up(8.20) = 8
    # penalty = min(50000, 12500 + 38 + 8) = 12546; sum-then-round would give 12547.
    assert submitted["penalty_cents"] == 12546
    assert submitted["fee_cents"] == 43546, "5000 report fee + 26000 tax + 12546 penalty"


def test_late_submit_from_overdue_status(api):
    """PRD 3.6: "Submitting a filing — allowed from `PREPARED` or `OVERDUE` —
    transitions it to `SUBMITTED`."
    PRD 3.6: "When the current logical date passes the `due_date`, the filing
    transitions to `OVERDUE`; a filing on its due date is not yet overdue."

    Design: Difficulty/combinatorial_formula/late_fee_component_rounding_order
    """
    entity, filing = _setup_prepared_franchise_filing()
    set_clock("2027-01-14T00:00:00Z")

    # The read path lazily flips the filing to OVERDUE before the submit.
    overdue = validate_success(api.get_filing(filing["id"], SEC1))
    assert overdue["status"] == "OVERDUE"

    submitted = submit_filing(filing["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["days_late"] == 4

    persisted = validate_success(api.get_filing(filing["id"], SEC1))
    assert persisted["status"] == "SUBMITTED"
    assert persisted["penalty_cents"] == 12546
    assert persisted["fee_cents"] == 43546


def test_grace_boundary_submit_on_grace_end(api):
    """PRD 3.7: "The grace end is `due_date` plus `grace_period_days`.
    `days_late` counts the days in the half-open interval from the day after
    grace end through `submitted_date`, inclusive of the submission day."
    PRD 3.7: "If `days_late` is zero, `penalty_cents` is zero."

    Design: Difficulty/boundary_precision_check/late_filing_grace_boundary
    """
    entity, filing = _setup_prepared_franchise_filing()
    # Submit exactly on grace end (2026-12-31 + 10 = 2027-01-10): the counting
    # interval is empty.
    set_clock("2027-01-10T00:00:00Z")

    submitted = submit_filing(filing["id"])
    assert submitted["days_late"] == 0
    assert submitted["penalty_cents"] == 0
    assert submitted["fee_cents"] == 31000, "5000 report fee + 26000 tax + 0 penalty"


def test_grace_boundary_submit_one_day_late(api):
    """PRD 3.7: "The grace end is `due_date` plus `grace_period_days`.
    `days_late` counts the days in the half-open interval from the day after
    grace end through `submitted_date`, inclusive of the submission day."
    PRD 3.6: "Rejection transitions the filing to `REJECTED` and reverses the
    fee accrual exactly, decrementing `fees_accrued_cents` by `fee_cents`."

    Design: Difficulty/boundary_precision_check/late_filing_grace_boundary
    """
    entity, filing = _setup_prepared_franchise_filing()
    # First submit exactly on grace end, then reject (by a different user than
    # the submitter) and re-prepare so the boundary can be re-crossed.
    set_clock("2027-01-10T00:00:00Z")
    first = submit_filing(filing["id"])
    assert first["days_late"] == 0
    validate_success(
        api.reject_filing(filing["id"], {"reason": "refile to observe the boundary"}, SEC1)
    )
    prepare_filing(filing["id"])

    # One day past grace end: exactly one day falls in (grace_end, submitted].
    set_clock("2027-01-11T00:00:00Z")
    second = submit_filing(filing["id"])
    assert second["days_late"] == 1
    # 12500 base + round_half_up(26000*0.00037)=10 + round_half_up(5000*0.00041)=2
    assert second["penalty_cents"] == 12512
    assert second["fee_cents"] == 43512, "5000 report fee + 26000 tax + 12512 penalty"
