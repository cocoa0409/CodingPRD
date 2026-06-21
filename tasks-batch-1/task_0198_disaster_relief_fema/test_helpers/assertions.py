"""Entity assertions and domain invariant checkers.

Shape assertions verify field presence/type/identity formatting per PRD §2.4;
domain invariant checkers verify the obligation and DOB invariants of PRD §2.9.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields present on every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_declaration(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_iso8601_timestamp(data["incident_start"])
    assert is_iso8601_timestamp(data["incident_end"])
    assert isinstance(data["ihp_max_grant_cents"], int)
    assert is_iso8601_timestamp(data["registration_deadline"])
    assert data["status"] in ("OPEN", "REGISTRATION_CLOSED", "CLOSED")


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["travel_buffer_minutes"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_caseworker(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["employee_id"], str) and len(data["employee_id"]) > 0
    assert isinstance(data["can_approve_awards"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_applicant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["declaration_id"])
    assert isinstance(data["household_name"], str) and len(data["household_name"]) > 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert is_iso8601_timestamp(data["damage_date"])
    assert isinstance(data["reported_repair_cost_cents"], int)
    assert isinstance(data["reported_personal_property_cents"], int)
    assert isinstance(data["reported_rental_months"], int)
    assert isinstance(data["total_dob_cents"], int)
    assert data["status"] in (
        "REGISTERED", "INSPECTION_SCHEDULED", "INSPECTED",
        "ELIGIBILITY_PENDING", "ELIGIBLE", "INELIGIBLE", "WITHDRAWN",
    )


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "INSPECTED", "VERIFIED", "CANCELLED")


def assert_ihp_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["assessment_id"])
    assert isinstance(data["monthly_fmr_cents"], int)
    for f in (
        "gross_eligible_cents", "capped_eligible_cents", "net_eligible_cents",
        "dob_offset_cents", "total_approved_cents", "disbursed_total_cents",
        "remaining_obligation_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an int"
    assert data["status"] in (
        "DRAFT", "ELIGIBILITY_PENDING", "AWARD_APPROVED", "DENIED",
        "DISBURSING", "UNDER_APPEAL", "CLOSED",
    )


def assert_award_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert data["category"] in (
        "RENTAL_ASSISTANCE", "REPAIR_ASSISTANCE", "PERSONAL_PROPERTY", "REPLACEMENT",
    )
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["approved_amount_cents"], int)
    assert data["li_status"] in ("PENDING", "APPROVED", "DISBURSED", "VOIDED")


def assert_dob_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert data["source_type"] in ("INSURANCE", "SBA_LOAN", "CHARITY", "OTHER_FEDERAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data["received_at"])
    assert data["dob_status"] in ("RECORDED", "REVERSED")


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert isinstance(data["expected_ihp_case_version"], int)
    assert isinstance(data["reason"], str)
    assert data["status"] in ("SUBMITTED", "GRANTED", "DENIED")


def assert_sba_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert isinstance(data["referred_loss_cents"], int)
    assert data["status"] in ("REFERRED", "SBA_APPROVED", "SBA_DECLINED")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert is_valid_uuid(data["line_item_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["disb_status"] in ("PAID", "VOIDED")


def assert_recoupment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert data["origin"] in ("LATE_DOB", "APPEAL_REDUCTION", "MANUAL")
    assert isinstance(data["debt_amount_cents"], int)
    assert isinstance(data["recovered_cents"], int) and data["recovered_cents"] >= 0
    assert data["status"] in ("ESTABLISHED", "SATISFIED", "WAIVED")


def assert_rental_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ihp_case_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in ("ACTIVE", "CLOSED")


# ─── Domain invariant checkers (PRD §2.9) ──────────────────────────────────
def assert_obligation_invariant(case: dict):
    """disbursed_total_cents + remaining_obligation_cents == total_approved_cents."""
    disbursed = case["disbursed_total_cents"]
    remaining = case["remaining_obligation_cents"]
    total = case["total_approved_cents"]
    assert disbursed + remaining == total, (
        f"Obligation invariant broken: disbursed {disbursed} + remaining {remaining} "
        f"!= total_approved {total}"
    )


def assert_net_eligible_invariant(case: dict):
    """net_eligible_cents == max(0, capped_eligible_cents - dob_offset_cents)."""
    expected = max(0, case["capped_eligible_cents"] - case["dob_offset_cents"])
    assert case["net_eligible_cents"] == expected, (
        f"net_eligible invariant broken: net {case['net_eligible_cents']} != "
        f"max(0, capped {case['capped_eligible_cents']} - offset {case['dob_offset_cents']}) "
        f"= {expected}"
    )
