"""Entity assertions and domain invariant checkers (PRD field names only)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_admission_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["SETUP", "OPEN", "REVIEW_CLOSED",
                              "DECISIONS_RELEASED", "ENROLLMENT_TRACKING",
                              "CLOSED"]
    for field in ("target_class_size", "inquiry_count", "application_count",
                  "admitted_count", "deposited_count", "enrolled_count",
                  "decisioned_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["admit_rate"], (int, float))


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cycle_id"], str)
    for field in ("capacity_seats", "target_enrollment", "tuition_cents",
                  "scholarship_budget_cents", "deposit_amount_cents",
                  "admitted_count", "deposited_count", "enrolled_count",
                  "seats_open", "scholarship_committed_cents",
                  "scholarship_available_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["intake_posture"] in ["OPEN", "PAUSED", "CLOSED"]
    assert isinstance(data["auto_waitlist_activation"], bool)


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["applicant_type"] in ["FIRST_YEAR", "TRANSFER", "READMIT"]
    assert data["inquiry_source"] in ["WEB_FORM", "CAMPUS_VISIT",
                                      "COLLEGE_FAIR", "REFERRAL",
                                      "PURCHASED_LIST"]
    assert data["distance_band"] in ["LOCAL", "REGIONAL", "NATIONAL",
                                     "INTERNATIONAL"]
    assert data["funnel_stage"] in ["INQUIRY", "APPLIED"]


def assert_application(data: dict):
    _assert_common(data)
    for field in ("applicant_id", "program_id", "cycle_id"):
        assert isinstance(data[field], str)
    assert isinstance(data["academic_score"], (int, float))
    assert 0 <= data["academic_score"] <= 100
    assert isinstance(data["efc_cents"], int) and data["efc_cents"] >= 0
    assert is_iso8601_timestamp(data["submitted_at"])
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert isinstance(data["submitted_read_count"], int)
    assert isinstance(data["aid_accepted_cents"], int)
    assert isinstance(data["aid_gap_cents"], int) and data["aid_gap_cents"] >= 0
    assert isinstance(data["melt_risk_score"], (int, float))
    assert 0 <= data["melt_risk_score"] <= 1
    assert data["status"] in [
        "SUBMITTED", "IN_REVIEW", "COMMITTEE_REVIEW", "DECISION_PENDING",
        "ADMITTED", "DENIED", "WAITLISTED", "DEPOSITED", "ENROLLED",
        "MELTED", "WITHDRAWN",
    ]


def assert_committee_review(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["reader_id"], str) and data["reader_id"]
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["status"] in ["ASSIGNED", "SUBMITTED", "CANCELLED"]


def assert_aid_offer(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert data["fund_type"] in ["MERIT", "NEED_BASED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "REVOKED",
                              "SUPERSEDED", "REVISION_REQUESTED"]


def assert_deposit(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["paid_at"])
    assert data.get("refund_amount_cents") is None or \
        isinstance(data["refund_amount_cents"], int)
    assert data["status"] in ["PAID", "REFUNDED", "FORFEITED"]


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["rank_score"], (int, float))
    assert data["status"] in ["ACTIVE", "ACTIVATED", "EXPIRED", "REMOVED"]


def assert_melt_intervention(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["advisor_id"], str) and data["advisor_id"]
    assert data["intervention_type"] in ["OUTREACH_CALL", "ADVISOR_MEETING",
                                         "EMAIL_CAMPAIGN"]
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["trigger_source"] in ["MANUAL", "AUTO_THRESHOLD"]
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_seat_ledger_conserved(program: dict):
    """PRD: seats_open never drifts from
    capacity_seats - deposited_count - enrolled_count."""
    assert program["seats_open"] == (
        program["capacity_seats"]
        - program["deposited_count"]
        - program["enrolled_count"]
    ), "Seat ledger drifted: seats_open != capacity - deposited - enrolled"


def assert_scholarship_ledger_conserved(program: dict):
    """PRD: scholarship_available_cents == scholarship_budget_cents -
    scholarship_committed_cents."""
    assert program["scholarship_available_cents"] == (
        program["scholarship_budget_cents"]
        - program["scholarship_committed_cents"]
    ), "Scholarship ledger drifted: available != budget - committed"
