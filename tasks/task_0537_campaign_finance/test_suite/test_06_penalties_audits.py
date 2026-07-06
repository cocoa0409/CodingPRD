"""Late-filing penalties, the filing->penalty->solvency cascade, audit loop, amendments,
and penalty waivers."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_treasurer_headers,
    set_clock, create_active_committee, add_deposited_contribution, add_expenditure,
    create_closed_reporting_period, create_draft_report, get_committee,
)

REGULATOR = TEST_USERS["regulator_headers"]


def _filed_report(api, cid, period_id):
    report = create_draft_report(api, cid, period_id)
    return validate_success(api.file_report(report["id"], make_treasurer_headers(cid)))


# --------------------------------------------------------------------------- #
# Tiered late-filing penalty
# --------------------------------------------------------------------------- #
def test_late_filing_flags_report_and_assesses(api):
    """PRD §3.6: "When a filed report is late, the system assesses a tiered penalty and pins
    it on the report as penalty_amount_cents, setting penalty_status from NONE to ASSESSED."

    Design: Difficulty/combinatorial_formula/late_filing_penalty_tiered
    """
    set_clock(api, "2026-04-20T00:00:00Z")  # 5 days after the 2026-04-15 deadline
    committee = create_active_committee(api, name="Beta", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=300000)
    filed = _filed_report(api, cid, period["id"])
    assert filed["is_late"] is True
    assert filed["days_late"] == 5
    assert filed["penalty_status"] == "ASSESSED"


def test_late_filing_penalty_small_tier_amount(api):
    """PRD §3.6: "The per-day rate is 1000 cents for a SMALL report ... The raw penalty is a
    base fee of 2500 cents plus the tier's per-day rate multiplied by days_late."

    Design: Difficulty/combinatorial_formula/late_filing_penalty_tiered
    """
    set_clock(api, "2026-04-20T00:00:00Z")
    committee = create_active_committee(api, name="Beta2", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=300000)  # SMALL tier (<=500000)
    filed = _filed_report(api, cid, period["id"])
    assert filed["penalty_amount_cents"] == 7500, "2500 + 1000*5, under the 1000000 cap"


def test_late_penalty_medium_tier_amount(api):
    """PRD §3.6: "The size tier is ... MEDIUM when they are above that but at most 5000000
    cents ... The per-day rate is ... 5000 cents for a MEDIUM report."

    Design: Corner/calculations/late_penalty_medium_tier
    """
    set_clock(api, "2026-04-18T00:00:00Z")  # 3 days late
    committee = create_active_committee(api, name="MedCo", committee_type="PARTY")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=1000000)  # MEDIUM tier
    filed = _filed_report(api, cid, period["id"])
    assert filed["days_late"] == 3
    assert filed["penalty_amount_cents"] == 17500, "2500 + 5000*3"


def test_late_penalty_cap_applied(api):
    """PRD §3.6: "The final penalty_amount_cents is the smaller of that raw amount and a
    ceiling of 1000000 cents."

    Design: Corner/calculations/late_penalty_cap_applied
    """
    set_clock(api, "2026-06-14T00:00:00Z")  # 60 days late
    committee = create_active_committee(api, name="CapCo", committee_type="PARTY")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=4000000)
    add_deposited_contribution(api, cid, contributor_ref="r2", amount_cents=2000000)  # LARGE tier (>5000000)
    filed = _filed_report(api, cid, period["id"])
    assert filed["days_late"] == 60
    assert filed["penalty_amount_cents"] == 1000000, "raw 2500 + 20000*60 = 1202500 capped at MAX"


# --------------------------------------------------------------------------- #
# Late-file -> penalty -> committee solvency cascade
# --------------------------------------------------------------------------- #
def test_late_penalty_flows_into_committee_total_penalties(api):
    """PRD §3.6: "An assessed penalty immediately flows through the committee:
    total_penalties_cents is recomputed to include this report's penalty."

    Design: Difficulty/transitive_cascade/late_file_penalty_solvency_cascade
    """
    set_clock(api, "2026-04-20T00:00:00Z")
    committee = create_active_committee(api, name="Zeta", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=300000)
    add_expenditure(api, cid, amount_cents=298000)
    filed = _filed_report(api, cid, period["id"])
    assert filed["penalty_amount_cents"] == 7500, "hop1: penalty assessed"
    committee_after = get_committee(api, cid)
    assert committee_after["total_penalties_cents"] == 7500, "hop2: committee total_penalties_cents"


def test_late_penalty_drives_committee_into_deficit(api):
    """PRD §2.9: "When a report is filed late, the newly assessed penalty flows into total
    penalties, then into cash on hand, then into solvency" and "it is DEFICIT when
    cash_on_hand_cents is strictly below zero."

    Design: Difficulty/transitive_cascade/late_file_penalty_solvency_cascade
    """
    set_clock(api, "2026-04-20T00:00:00Z")
    committee = create_active_committee(api, name="Zeta2", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    add_deposited_contribution(api, cid, contributor_ref="r1", amount_cents=300000)
    add_expenditure(api, cid, amount_cents=298000)
    _filed_report(api, cid, period["id"])
    committee_after = get_committee(api, cid)
    assert committee_after["cash_on_hand_cents"] == -5500, "hop3: 300000 - 298000 - 7500"
    assert committee_after["solvency_status"] == "DEFICIT", "hop4: negative cash on hand is DEFICIT"


# --------------------------------------------------------------------------- #
# Report audit cycle
# --------------------------------------------------------------------------- #
def test_audit_open_moves_report_under_audit(api):
    """PRD §3.6: "An agency auditor opens an audit, moving the report from FILED to
    UNDER_AUDIT; this requires the report to be FILED and is otherwise rejected with
    ERR_REPORT_NOT_FILED."

    Design: Difficulty/non_linear_state_machine/report_audit_cycle
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Eps", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    filed = _filed_report(api, cid, period["id"])
    opened = validate_success(api.audit_open_report(filed["id"], REGULATOR))
    assert opened["status"] == "UNDER_AUDIT"


def test_audit_close_returns_report_to_filed(api):
    """PRD §3.6: "The auditor closes the audit with no finding, moving it from UNDER_AUDIT
    back to FILED; this requires the report to be UNDER_AUDIT and is otherwise rejected with
    ERR_REPORT_NOT_UNDER_AUDIT. This loop may repeat."

    Design: Difficulty/non_linear_state_machine/report_audit_cycle
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Eps2", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    filed = _filed_report(api, cid, period["id"])
    validate_success(api.audit_open_report(filed["id"], REGULATOR))
    closed = validate_success(api.audit_close_report(filed["id"], REGULATOR))
    assert closed["status"] == "FILED", "audit-close returns the report to the FILED state it already occupied"


def test_audit_close_on_filed_report_rejected(api):
    """PRD §3.6: "The auditor closes the audit with no finding, moving it from UNDER_AUDIT
    back to FILED; this requires the report to be UNDER_AUDIT and is otherwise rejected with
    ERR_REPORT_NOT_UNDER_AUDIT."

    Design: Corner/state_machines/report_audit_close_without_open_rejected
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="Psi", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    filed = _filed_report(api, cid, period["id"])
    validate_error(api.audit_close_report(filed["id"], REGULATOR),
                   ApiErrorId.ERR_REPORT_NOT_UNDER_AUDIT.value)


# --------------------------------------------------------------------------- #
# Amendment chain
# --------------------------------------------------------------------------- #
def test_amend_supersedes_old_and_creates_revision(api):
    """PRD §3.6: "Amending moves the old report to the terminal SUPERSEDED state and creates
    a new report in DRAFT for the same committee and period, with its supersedes_report_id
    pointing at the old report's id and its amendment_seq set to one greater than the old
    report's amendment_seq, forming an amendment chain."

    Design: Corner/state_machines/report_amend_creates_supersede_revision
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="AmendCo", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    filed = _filed_report(api, cid, period["id"])
    amendment = validate_success(api.amend_report(filed["id"], make_treasurer_headers(cid)), expected_status=201)
    assert amendment["amendment_seq"] == 1
    assert amendment["supersedes_report_id"] == filed["id"]
    old = validate_success(api.get_report(filed["id"], make_treasurer_headers(cid)))
    assert old["status"] == "SUPERSEDED"
    revisions, _meta = validate_paginated(api.list_report_revisions(filed["id"], make_treasurer_headers(cid)))
    assert amendment["id"] in [r["id"] for r in revisions], "amendment discoverable via /revisions"


# --------------------------------------------------------------------------- #
# Penalty waiver precondition
# --------------------------------------------------------------------------- #
def test_waive_penalty_on_on_time_report_rejected(api):
    """PRD §3.6: "An agency auditor may waive an assessed penalty, moving the report's
    penalty_status from ASSESSED to WAIVED; this requires the penalty to be currently
    ASSESSED and is otherwise rejected with ERR_PENALTY_NOT_ASSESSED."

    Design: Corner/validations/penalty_waive_without_assessment_rejected
    """
    set_clock(api, "2026-04-10T00:00:00Z")  # on time -> penalty_status NONE
    committee = create_active_committee(api, name="WaiveCo", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    filed = _filed_report(api, cid, period["id"])
    validate_error(api.waive_penalty(filed["id"], REGULATOR), ApiErrorId.ERR_PENALTY_NOT_ASSESSED.value)
