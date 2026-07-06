"""Draft/file reports: provisional-vs-final receipts, matching-funds rounding, filing
boundary, cash-on-hand, and filing preconditions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_treasurer_headers,
    set_clock, create_active_committee, add_contribution, add_deposited_contribution,
    add_expenditure, create_reporting_period, create_closed_reporting_period,
    create_draft_report, committee_version,
)

REGULATOR = TEST_USERS["regulator_headers"]
PUBLIC = TEST_USERS["public_headers"]


# --------------------------------------------------------------------------- #
# Provisional vs final receipts
# --------------------------------------------------------------------------- #
def test_draft_report_receipts_are_provisional(api):
    """PRD §3.5: "The provisional variant, used while the report is a draft, counts
    contributions whose settlement_status is RECORDED or DEPOSITED."

    Design: Difficulty/dual_variant_calc/report_provisional_vs_final_receipts
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Alpha", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_contribution(api, cid, contributor_ref="r1", amount_cents=200000)          # RECORDED
    add_deposited_contribution(api, cid, contributor_ref="r2", amount_cents=150000)  # DEPOSITED
    report = create_draft_report(api, cid, period["id"])
    assert report["total_receipts_cents"] == 350000, "provisional counts RECORDED (200000) + DEPOSITED (150000)"


def test_filed_report_receipts_are_final_deposited_only(api):
    """PRD §3.5: "The final variant, computed when the report is filed, counts only DEPOSITED
    contributions; because recorded-but-not-yet-deposited money drops out, the final total is
    always less than or equal to the provisional total."

    Design: Difficulty/dual_variant_calc/report_provisional_vs_final_receipts
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Alpha2", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_contribution(api, cid, contributor_ref="r1", amount_cents=200000)          # RECORDED, undeposited
    add_deposited_contribution(api, cid, contributor_ref="r2", amount_cents=150000)  # DEPOSITED
    report = create_draft_report(api, cid, period["id"])
    filed = validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))
    assert filed["total_receipts_cents"] == 150000, "final counts DEPOSITED only"
    assert report["total_receipts_cents"] != filed["total_receipts_cents"], "the 200000 RECORDED gift is the divergence"


# --------------------------------------------------------------------------- #
# Matching funds — per-line rounding
# --------------------------------------------------------------------------- #
def test_matching_funds_rounds_per_line_item_draft(api):
    """PRD §3.5: "For each eligible line item, its matchable_amount_cents is multiplied by the
    one-third matching rate (0.3333333333333333) and that product is rounded half up to a
    whole number of cents; the rounded per-line results are then summed."

    Design: Difficulty/combinatorial_formula/report_matching_funds_rounding
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Gamma", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    for ref in ("r1", "r2", "r3"):
        add_deposited_contribution(api, cid, contributor_ref=ref, contributor_type="INDIVIDUAL", amount_cents=100)
    report = create_draft_report(api, cid, period["id"])
    assert report["matching_funds_cents"] == 99, "round_half_up(100/3)=33 per line, summed 3x = 99"


def test_matching_funds_per_line_rounding_pinned_on_file(api):
    """PRD §3.5: "The rounding is applied per line item and then summed — never by summing the
    matchable amounts first and rounding once; that sum-then-round order is explicitly rejected."

    Design: Difficulty/combinatorial_formula/report_matching_funds_rounding
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Gamma2", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    for ref in ("r1", "r2", "r3"):
        add_deposited_contribution(api, cid, contributor_ref=ref, contributor_type="INDIVIDUAL", amount_cents=100)
    report = create_draft_report(api, cid, period["id"])
    filed = validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))
    assert filed["matching_funds_cents"] == 99, "sum-then-round would wrongly give 100; per-line gives 99"


# --------------------------------------------------------------------------- #
# Filing deadline boundary (strict >)
# --------------------------------------------------------------------------- #
def test_filing_exactly_at_deadline_is_on_time(api):
    """PRD §2.5: "a report is late only when its filed_at is strictly later than the covered
    period's filing_deadline; filing exactly at the deadline is on time."

    Design: Difficulty/boundary_precision_check/filing_deadline_boundary
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="A", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)  # filing_deadline 2026-04-15T00:00:00Z
    report = create_draft_report(api, cid, period["id"])
    set_clock(api, "2026-04-15T00:00:00Z")  # exactly the deadline
    filed = validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))
    assert filed["is_late"] is False, "filing exactly at the deadline is on time"
    assert filed["penalty_status"] == "NONE"


def test_filing_one_second_after_deadline_is_late(api):
    """PRD §2.5: "The whole-days-late count is the difference between filed_at and
    filing_deadline divided into 24-hour days and rounded up to the next whole day (any
    positive fractional day counts as a full day)."

    Design: Difficulty/boundary_precision_check/filing_deadline_boundary
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="B", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)  # filing_deadline 2026-04-15T00:00:00Z
    report = create_draft_report(api, cid, period["id"])
    set_clock(api, "2026-04-15T00:00:01Z")  # one second late
    filed = validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))
    assert filed["is_late"] is True, "filing one second after the deadline is late"
    assert filed["days_late"] == 1, "a positive fractional day rounds up to 1 whole day"


# --------------------------------------------------------------------------- #
# Cash-on-hand derivation (corner)
# --------------------------------------------------------------------------- #
def test_cash_on_hand_derivation(api):
    """PRD §2.9: "cash_on_hand_cents as total_receipts_cents minus total_disbursements_cents
    minus total_penalties_cents ... solvency_status ... is SOLVENT otherwise (a value of
    exactly zero is SOLVENT)."

    Design: Corner/calculations/committee_cash_on_hand_derivation
    """
    committee = create_active_committee(api, name="CashCo", committee_type="PARTY")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", amount_cents=500000)  # RECORDED, counts toward receipts
    add_expenditure(api, cid, amount_cents=100000)
    fetched = validate_success(api.get_committee(cid, make_treasurer_headers(cid)))
    assert fetched["cash_on_hand_cents"] == 400000, "500000 - 100000 - 0"
    assert fetched["solvency_status"] == "SOLVENT"


# --------------------------------------------------------------------------- #
# Filing preconditions (corner)
# --------------------------------------------------------------------------- #
def test_file_report_period_still_open_rejected(api):
    """PRD §3.5: "Filing requires the report to be a draft ..., the acting treasurer to own
    the committee, and the covered period to be CLOSED (otherwise ERR_PERIOD_NOT_CLOSED)."

    Design: Corner/validations/file_report_period_not_closed_rejected
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="OpenCo", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_reporting_period(api)  # left OPEN
    report = create_draft_report(api, cid, period["id"])
    validate_error(api.file_report(report["id"], make_treasurer_headers(cid)),
                   ApiErrorId.ERR_PERIOD_NOT_CLOSED.value)


def test_file_already_filed_report_rejected(api):
    """PRD §3.5: "To file, the treasurer transitions the report from DRAFT to FILED. Filing
    requires the report to be a draft (otherwise ERR_REPORT_NOT_DRAFT)."

    Design: Corner/state_machines/report_file_when_not_draft_rejected
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Chi", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    report = create_draft_report(api, cid, period["id"])
    validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))
    validate_error(api.file_report(report["id"], make_treasurer_headers(cid)),
                   ApiErrorId.ERR_REPORT_NOT_DRAFT.value)


# --------------------------------------------------------------------------- #
# Reverse-FK reachability (corner)
# --------------------------------------------------------------------------- #
def test_reports_covering_period_reverse_list(api):
    """PRD §3.8: "the reports covering a given period can be listed with an optional
    committee_id filter."

    Design: Corner/endpoints/report_period_reverse_list
    """
    committee = create_active_committee(api, name="PRco", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_reporting_period(api)
    report = create_draft_report(api, cid, period["id"])
    data, _meta = validate_paginated(api.list_period_reports(period["id"], PUBLIC))
    ids = [r["id"] for r in data]
    assert report["id"] in ids, "the created report must appear in the period's reports listing"
