"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual: str, expected: str):
    """PRD pins the instant a clock-derived field records (e.g. "thirty days
    out from the logical clock", §3.5); the string serialization (fractional
    digits) is not pinned for these fields, so compare parsed instants."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict):
    """PRD §2.4: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["school_name"], str) and len(data["school_name"]) > 0
    assert isinstance(data["founding_group"], str) and len(data["founding_group"]) > 0
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["proposed_grades"], str)
    assert isinstance(data["review_scores"], list)
    assert isinstance(data["rubric_complete"], bool)
    assert data.get("rubric_score") is None or isinstance(data["rubric_score"], (int, float))
    assert data.get("interview_score") is None or isinstance(data["interview_score"], (int, float))
    assert data.get("composite_score") is None or isinstance(data["composite_score"], (int, float))
    assert data.get("composite_variant") in (None, "PROVISIONAL", "FINAL")
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "BOARD_REVIEW", "APPROVED", "DENIED"]
    assert data.get("decided_by_user_id") is None or isinstance(data["decided_by_user_id"], str)
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)


def assert_interview(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert isinstance(data["panelist_user_ids"], list)
    assert data.get("panel_score") is None or isinstance(data["panel_score"], (int, float))
    assert data["status"] in ["SCHEDULED", "SCORED", "CANCELLED"]


def assert_school(data: dict):
    _assert_common(data)
    assert isinstance(data["school_name"], str) and len(data["school_name"]) > 0
    assert data["status"] in ["PRE_OPENING", "OPEN", "CLOSING", "CLOSED"]
    for field in ("academic_standing", "financial_standing", "operational_standing"):
        assert data[field] in ["GOOD", "NOTICE", "PROBATION", "CRITICAL"], f"{field} invalid"
    assert data.get("current_contract_id") is None or isinstance(data["current_contract_id"], str)


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("school_id", "")), "school_id must be a UUID"
    assert data.get("prior_contract_id") is None or isinstance(data["prior_contract_id"], str)
    assert isinstance(data["framework_version"], str)
    assert isinstance(data["term_start"], str) and isinstance(data["term_end"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RENEWED", "REVOKED", "EXPIRED"]
    assert isinstance(data["targets_weight_total"], (int, float))


def assert_target(data: dict):
    _assert_common(data)
    assert data["domain"] in ["ACADEMIC", "FINANCIAL", "OPERATIONAL"]
    assert isinstance(data["metric_code"], str) and len(data["metric_code"]) > 0
    assert isinstance(data["target_value"], (int, float))
    assert isinstance(data["floor_value"], (int, float))
    assert isinstance(data["weight"], (int, float)) and 0 < data["weight"] <= 1


def assert_monitoring_report(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    for field in ("academic_score", "financial_score", "operational_score"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["compliance_index"], (int, float))
    assert isinstance(data["submitted_by_user_id"], str)
    assert data.get("return_notes") is None or isinstance(data["return_notes"], str)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "RETURNED"]


def assert_lottery(data: dict):
    _assert_common(data)
    assert isinstance(data["academic_year"], int)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert data["status"] in ["DRAFT", "OPEN", "SEALED", "EXECUTED", "CERTIFIED",
                              "AUDIT_FAILED", "CANCELLED"]


def assert_lottery_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["student_ref"], str)
    assert isinstance(data["grade_level"], str)
    assert isinstance(data["preference_codes"], list)
    assert data["preference_status"] in ["PENDING", "VERIFIED", "REJECTED"]
    assert data.get("preference_verified_by") is None or isinstance(data["preference_verified_by"], str)
    assert data["outcome"] in ["ENTERED", "OFFERED", "WAITLISTED", "DECLINED", "VOIDED"]
    assert data.get("rank_position") is None or isinstance(data["rank_position"], int)


def assert_intervention_notice(data: dict):
    _assert_common(data)
    assert data["level"] in ["NOTICE", "PROBATION", "REVOCATION_REVIEW"]
    assert data["domain"] in ["ACADEMIC", "FINANCIAL", "OPERATIONAL", "COMPLIANCE"]
    assert isinstance(data["reason"], str)
    assert data.get("issued_by_user_id") is None or isinstance(data["issued_by_user_id"], str)
    assert data.get("resolved_by_user_id") is None or isinstance(data["resolved_by_user_id"], str)
    assert data.get("successor_notice_id") is None or isinstance(data["successor_notice_id"], str)
    assert data["status"] in ["DRAFT", "ISSUED", "RESOLVED", "ESCALATED", "MOOT"]


def assert_corrective_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_text"], str)
    assert isinstance(data["submitted_at"], str)
    assert data.get("reviewed_by_user_id") is None or isinstance(data["reviewed_by_user_id"], str)
    assert data.get("review_notes") is None or isinstance(data["review_notes"], str)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "RETURNED"]


def assert_renewal_decision(data: dict):
    _assert_common(data)
    assert isinstance(data["eligible_term_years"], int)
    assert data.get("decision") in (None, "RENEWED", "RENEWED_WITH_CONDITIONS", "DENIED")
    assert data.get("granted_term_years") is None or isinstance(data["granted_term_years"], int)
    assert data.get("decided_by_user_id") is None or isinstance(data["decided_by_user_id"], str)
    assert data.get("decided_at") is None or isinstance(data["decided_at"], str)
    assert data["status"] in ["PENDING", "DECIDED", "FINAL", "REVERTED"]


def assert_closure_plan(data: dict):
    _assert_common(data)
    assert data["reason"] in ["REVOCATION", "NON_RENEWAL", "VOLUNTARY"]
    assert isinstance(data["closure_date"], str)
    assert data["status"] in ["INITIATED", "TRANSITION_IN_PROGRESS", "RECORDS_COMPLETE",
                              "CLOSED", "CANCELLED"]


def assert_student_transition(data: dict):
    _assert_common(data)
    assert isinstance(data["student_ref"], str)
    assert data.get("destination_school") is None or isinstance(data["destination_school"], str)
    assert data["status"] in ["PENDING", "PLACED", "RECORDS_SENT"]


def assert_fee_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["estimated_enrollment"], int)
    assert data.get("audited_enrollment") is None or isinstance(data["audited_enrollment"], int)
    assert isinstance(data["base_per_pupil_cents"], int)
    assert isinstance(data["qualifying_supplemental_pupils"], int)
    for field in ("base_funding_cents", "supplemental_cents", "total_funding_cents",
                  "billed_amount_cents", "paid_cents", "waived_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["fee_rate"], (int, float))
    assert data["billed_variant"] in ["ESTIMATED", "FINAL"]
    assert data["status"] in ["ESTIMATED", "FINALIZED", "PAID", "DISPUTED", "WAIVED"]


def assert_appeal(data: dict):
    _assert_common(data)
    assert data.get("school_id") is None or isinstance(data["school_id"], str)
    assert data["target_type"] in ["APPLICATION_DENIAL", "RENEWAL_DENIAL", "REVOCATION", "FEE_INVOICE"]
    assert isinstance(data["target_id"], str)
    assert isinstance(data["grounds"], str)
    assert isinstance(data["filed_by_user_id"], str)
    assert data.get("hearing_officer_user_id") is None or isinstance(data["hearing_officer_user_id"], str)
    assert data.get("ruling") in (None, "UPHELD", "OVERTURNED")
    assert data["status"] in ["FILED", "HEARING_SCHEDULED", "RULED_UPHELD", "RULED_OVERTURNED"]


# ---------------------------------------------------------------------------
# Domain invariants (PRD §3.4 seat conservation, §3.8 fee ledger)
# ---------------------------------------------------------------------------
def assert_invoice_ledger_invariant(invoice: dict):
    """PRD §3.8: paid_cents plus waived_cents plus the outstanding remainder
    always equals billed_amount_cents, and the remainder never goes negative."""
    billed = invoice["billed_amount_cents"]
    outstanding = billed - invoice["paid_cents"] - invoice["waived_cents"]
    assert outstanding >= 0, (
        f"outstanding remainder went negative: billed={billed}, "
        f"paid={invoice['paid_cents']}, waived={invoice['waived_cents']}"
    )
    if invoice["status"] == "PAID":
        assert invoice["paid_cents"] == billed, "paid invoice must settle in full"
    if invoice["status"] == "WAIVED":
        assert invoice["paid_cents"] + invoice["waived_cents"] == billed


def assert_lottery_seat_partition(entries: list, capacity: int):
    """PRD §3.4: OFFERED + WAITLISTED + DECLINED == N, and
    OFFERED == min(capacity, N - DECLINED)."""
    n = len(entries)
    offered = sum(1 for e in entries if e["outcome"] == "OFFERED")
    waitlisted = sum(1 for e in entries if e["outcome"] == "WAITLISTED")
    declined = sum(1 for e in entries if e["outcome"] == "DECLINED")
    assert offered + waitlisted + declined == n, (
        f"seat partition broken: {offered}+{waitlisted}+{declined} != {n}"
    )
    assert offered == min(capacity, n - declined), (
        f"offered count {offered} != min(capacity={capacity}, N-DECLINED={n - declined})"
    )
    return {"offered": offered, "waitlisted": waitlisted, "declined": declined}
