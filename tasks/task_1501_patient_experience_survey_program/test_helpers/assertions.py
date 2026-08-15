"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COMPOSITE_KEYS


def _assert_common(data: dict):
    """PRD §2.5: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["sampling_protocol"] in (
        "SIMPLE_RANDOM", "STRATIFIED_BY_UNIT", "CENSUS")
    assert data["admin_mode"] in ("MAIL_ONLY", "PHONE_ONLY", "MIXED_MODE")
    assert "active_vendor_id" in data


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cycle_budget_cents"], int)
    assert data["cycle_budget_cents"] >= 0
    assert isinstance(data["cycle_budget_remaining_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "SUPERSEDED")
    assert "superseded_at" in data


def assert_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["target_sample_size"], int)
    assert data["target_sample_size"] >= 1
    assert data["status"] in (
        "DRAFT", "SAMPLING_OPEN", "FIELDING", "RECONCILIATION", "SCORING",
        "PUBLISHED", "VOIDED")
    assert isinstance(data["sampled_count"], int)
    assert isinstance(data["completed_responses"], int)
    assert isinstance(data["eligible_denominator"], int)
    assert "response_rate" in data
    if data["response_rate"] is not None:
        assert isinstance(data["response_rate"], (int, float))
    assert isinstance(data["publication_eligible"], bool)


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["unit_code"], str) and data["unit_code"]


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["specialty"], str)


def assert_discharge(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["provider_id"], str)
    assert data["discharge_disposition"] in (
        "HOME", "SNF", "EXPIRED", "PSYCH_FACILITY", "REHAB", "HOSPICE")
    assert data["primary_dx_group"] in (
        "MEDICAL", "SURGICAL", "PSYCHIATRIC", "MATERNITY")
    assert data["payer"] in ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert isinstance(data["address_country"], str)
    assert isinstance(data["no_publicity_flag"], bool)
    assert data["custody_status"] in ("NONE", "LAW_ENFORCEMENT")
    assert data["status"] in ("ELIGIBILITY_PENDING", "ELIGIBLE", "EXCLUDED")
    assert isinstance(data["exclusion_reasons"], list)


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["discharge_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["provider_id"], str)
    assert data["mode_assigned"] in ("MAIL", "PHONE")
    assert isinstance(data["postage_cost_cents"], int)
    assert data["postage_cost_cents"] > 0
    assert data["billing_status"] in ("CHARGED", "CREDITED")
    assert data["status"] in (
        "SAMPLED", "IN_FIELD", "RESPONDED", "NONRESPONSE", "UNDELIVERABLE",
        "EXCLUDED_POST_SAMPLE", "VOIDED")


def assert_response(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["cycle_id"], str)
    assert data["mode_used"] in ("MAIL", "PHONE")
    for key in ("nurse_comm_score", "doctor_comm_score", "cleanliness_score",
                "overall_rating_score"):
        assert isinstance(data[key], int), f"{key} must be an integer"
        assert 1 <= data[key] <= 4, f"{key} must be within 1..4"
    assert "comment_text" in data
    assert is_iso8601_timestamp(data.get("received_at", "")), \
        "received_at must be ISO 8601"
    assert isinstance(data["is_late"], bool)
    assert data["status"] in (
        "ACCEPTED", "PENDING_REVIEW", "INCLUDED", "EXCLUDED", "VOIDED")
    assert isinstance(data["has_escalated_recovery"], bool)


def assert_initiative(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["domain"] in (
        "NURSE_COMM", "DOCTOR_COMM", "CLEANLINESS", "OVERALL_RATING")
    assert isinstance(data["baseline_cycle_id"], str)
    assert isinstance(data["evaluation_cycle_id"], str)
    assert isinstance(data["target_score"], (int, float))
    assert "baseline_score" in data
    assert "progress_pinned" in data
    assert "progress_rolling" in data
    assert "achieved_at" in data
    assert data["status"] in (
        "DRAFT", "ACTIVE", "UNDER_EVALUATION", "TARGET_MET", "TARGET_MISSED",
        "CANCELLED")


def assert_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["response_id"], str)
    assert data["domain"] in (
        "NURSE_COMM", "DOCTOR_COMM", "CLEANLINESS", "OVERALL_RATING")
    assert data["priority"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED")
    assert "acknowledged_at" in data
    assert "acknowledged_within_sla" in data
    assert "resolution_note" in data


def assert_scored_snapshot(data: dict):
    """PRD §3.6: after begin-scoring the cycle carries the frozen snapshot —
    both composite maps keyed by the four composites, both breakdowns, and the
    frozen counters."""
    for field in ("scored_raw_composite_pcts", "scored_adjusted_composite_pcts"):
        pcts = data.get(field)
        assert isinstance(pcts, dict), f"{field} must be an object once scored"
        for key in COMPOSITE_KEYS:
            assert key in pcts, f"{field} must carry {key}"
            assert pcts[key] is None or isinstance(pcts[key], (int, float))
    for field in ("scored_unit_breakdown", "scored_provider_breakdown"):
        assert isinstance(data.get(field), list), f"{field} must be an array"
    assert isinstance(data.get("scored_completed_responses"), int)
    assert "scored_response_rate" in data


def assert_vendor_budget_invariant(vendor: dict, charged_postage_sum: int):
    """PRD §2.8: at all times cycle_budget_cents equals
    cycle_budget_remaining_cents plus the sum of CHARGED postage."""
    assert vendor["cycle_budget_cents"] == (
        vendor["cycle_budget_remaining_cents"] + charged_postage_sum
    ), (
        f"vendor budget ledger drifted: {vendor['cycle_budget_cents']} != "
        f"{vendor['cycle_budget_remaining_cents']} + {charged_postage_sum}"
    )
