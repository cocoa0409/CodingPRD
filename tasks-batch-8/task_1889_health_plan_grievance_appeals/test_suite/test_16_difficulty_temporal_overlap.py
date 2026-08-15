"""Difficulty queue: resource temporal overlap (PRD §2.9, §3.2, §3.8).

Three interval semantics: policy key-point replacement, the duplicate-intake
sliding window, and the reopening fixed-deadline interval.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_same_instant, api_client,
    TEST_USERS,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, create_and_send_decision_notification,
    setup_closed_case, create_and_review_reopening,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def test_policy_create_evicts_incumbent_active_row(api):
    """PRD §2.9: "Uniqueness is enforced on the active policy per triple: only one policy
    for a given (`program`, `case_kind`, `priority_track`) may have
    `active` set to `true` at any time, and creating a new active policy
    for a triple deactivates whichever policy was previously active for
    it."

    Design: Difficulty/resource_temporal_overlap/deadline_policy_active_uniqueness_point_overlap
    """
    pol1 = create_policy("MEDICARE", "APPEAL", "STANDARD",
                         resolution_hours=168, extension_hours=0,
                         effectuation_hours=72)
    pol2 = create_policy("MEDICARE", "APPEAL", "STANDARD",
                         resolution_hours=120, extension_hours=0,
                         effectuation_hours=48)
    assert pol2["active"] is True
    rows = get_success_data(api.list_deadline_policies(
        COMPLIANCE,
        params={"program": "MEDICARE", "case_kind": "APPEAL",
                "priority_track": "STANDARD"}))
    by_id = {row["id"]: row for row in rows}
    assert by_id[pol1["id"]]["active"] is False, (
        "The incumbent policy must be deactivated by the replacement")
    assert by_id[pol2["id"]]["active"] is True


def test_policy_active_filter_returns_single_row_per_triple(api):
    """PRD §2.9: "Uniqueness is enforced on the active policy per triple: only one policy
    for a given (`program`, `case_kind`, `priority_track`) may have
    `active` set to `true` at any time, and creating a new active policy
    for a triple deactivates whichever policy was previously active for
    it."
PRD §2.9: "Policies may be listed with filters on `program`, `case_kind`,
    `priority_track`, and `active`."

    Design: Difficulty/resource_temporal_overlap/deadline_policy_active_uniqueness_point_overlap
    """
    create_policy("MEDICARE", "ORG_DETERMINATION", "STANDARD",
                  resolution_hours=336)
    create_policy("MEDICARE", "ORG_DETERMINATION", "STANDARD",
                  resolution_hours=120)
    rows = get_success_data(api.list_deadline_policies(
        COMPLIANCE,
        params={"program": "MEDICARE", "case_kind": "ORG_DETERMINATION",
                "priority_track": "STANDARD", "active": True}))
    assert len(rows) == 1, f"Exactly one active policy per triple; got {len(rows)}"
    assert rows[0]["resolution_hours"] == 120


def test_duplicate_intake_inside_one_hour_window_rejected(api):
    """PRD §3.2: "The duplicate-intake guard rejects a new case when an identical case —
    same `member_id`, same `case_kind`, same `provider_id` — was received
    within the prior one hour and is still in a non-terminal state; the
    rejection is `ERR_DUPLICATE_CASE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_case_intake_one_hour_window
    """
    member = create_member("MBR-TO2", full_name="Gus Yang", program="MEDICARE")
    set_clock("2026-08-01T00:00:00Z")
    intake_case(member["id"], case_kind="GRIEVANCE")
    set_clock("2026-08-01T00:30:00Z")
    validate_error(
        api.create_case({"member_id": member["id"], "case_kind": "GRIEVANCE"},
                        INTAKE),
        ApiErrorId.ERR_DUPLICATE_CASE)


def test_duplicate_intake_outside_one_hour_window_allowed(api):
    """PRD §3.2: "The duplicate-intake guard rejects a new case when an identical case —
    same `member_id`, same `case_kind`, same `provider_id` — was received
    within the prior one hour and is still in a non-terminal state; the
    rejection is `ERR_DUPLICATE_CASE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_case_intake_one_hour_window
    """
    member = create_member("MBR-TO2B", full_name="Gus Yang B",
                           program="MEDICARE")
    set_clock("2026-08-01T00:00:00Z")
    intake_case(member["id"], case_kind="GRIEVANCE")
    # +61 minutes: outside the prior-one-hour look-back window.
    set_clock("2026-08-01T01:01:00Z")
    data = validate_success(api.create_case(
        {"member_id": member["id"], "case_kind": "GRIEVANCE"}, INTAKE),
        expected_status=201)
    assert data["status"] == "RECEIVED"
    assert_same_instant(data["received_at"], "2026-08-01T01:01:00Z")


def _close_grievance_at(member, close_at):
    """Walk a GRIEVANCE to CLOSED, stamping closed_at at ``close_at``."""
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    set_clock(close_at)
    case = decide_grievance_from_in_review(case["id"],
                                           decision_outcome="UNFAVORABLE")
    create_and_send_decision_notification(case["id"])
    return get_success_data(api_client.close_case(case["id"], COMPLIANCE))


def test_reopening_at_exactly_180_days_accepted(api):
    """PRD §3.8: "The reopening window is measured from the source case's `closed_at`:
    `NEW_EVIDENCE` and `CLERICAL_ERROR` requests must arrive within 180
    days of closure, while `FRAUD_OR_SIMILAR_FAULT` is exempt from any
    window — a request outside its window is rejected with
    `ERR_REOPEN_WINDOW_MISSED`."

    Design: Difficulty/resource_temporal_overlap/reopening_window_180_day_interval_membership
    """
    member = create_member("MBR-TO3", full_name="Hana Lee", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    closed = _close_grievance_at(member, "2026-08-02T00:00:00Z")
    # closed_at 2026-08-02 + 180 days == 2027-01-29 (inclusive end).
    set_clock("2027-01-29T00:00:00Z")
    data = validate_success(api.create_reopening(
        {"case_id": closed["id"], "request_reason": "NEW_EVIDENCE"},
        COMPLIANCE), expected_status=201)
    assert data["status"] == "REQUESTED"


def test_reopening_one_hour_past_180_days_rejected(api):
    """PRD §3.8: "The reopening window is measured from the source case's `closed_at`:
    `NEW_EVIDENCE` and `CLERICAL_ERROR` requests must arrive within 180
    days of closure, while `FRAUD_OR_SIMILAR_FAULT` is exempt from any
    window — a request outside its window is rejected with
    `ERR_REOPEN_WINDOW_MISSED`."

    Design: Difficulty/resource_temporal_overlap/reopening_window_180_day_interval_membership
    """
    member = create_member("MBR-TO3B", full_name="Hana Lee B",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    closed = _close_grievance_at(member, "2026-08-02T00:00:00Z")
    # One hour past closed_at + 180 days: outside the window.
    set_clock("2027-01-29T01:00:00Z")
    validate_error(
        api.create_reopening({"case_id": closed["id"],
                              "request_reason": "NEW_EVIDENCE"}, COMPLIANCE),
        ApiErrorId.ERR_REOPEN_WINDOW_MISSED)
