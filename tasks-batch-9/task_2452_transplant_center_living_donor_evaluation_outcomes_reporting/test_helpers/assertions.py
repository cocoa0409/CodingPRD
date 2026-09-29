"""Entity assertions and domain invariant checkers for the PRD's resources."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DONOR_LIFETIME_CAP_CENTS


def _assert_common(data: dict) -> None:
    """id + created_at + updated_at + version, as almost every resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')}"
    )


def assert_program(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["center_code"], str) and data["center_code"]
    assert data["organ_type"] in ["KIDNEY", "LIVER"]
    assert data["compliance_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert isinstance(data["cit_breach_count"], int) and data["cit_breach_count"] >= 0
    assert_donor_fund_ledger(data)


def assert_donor_fund_ledger(program: dict) -> None:
    """Committed plus remaining always equals the pool, and remaining is always
    between 0 and the pool inclusive."""
    pool = program["donor_fund_pool_cents"]
    committed = program["donor_fund_committed_cents"]
    remaining = program["donor_fund_remaining_cents"]
    assert committed + remaining == pool, (
        f"committed {committed} + remaining {remaining} must equal pool {pool}"
    )
    assert 0 <= remaining <= pool, f"remaining {remaining} must lie in [0, {pool}]"


def assert_staff_member(data: dict) -> None:
    _assert_common(data)
    assert data["staff_role"] in [
        "TRANSPLANT_COORDINATOR",
        "LIVING_DONOR_ADVOCATE",
        "EVALUATION_REVIEWER",
        "QUALITY_OFFICER",
        "SURGEON",
    ]
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["npi"], str) and data["npi"]


def assert_recipient_candidate(data: dict) -> None:
    _assert_common(data)
    assert data["abo_blood_type"] in ["O", "A", "B", "AB"]
    assert data["listing_status"] in [
        "WORKUP",
        "APPROVED_NOT_LISTED",
        "DECLINED",
        "ACTIVE",
        "INACTIVE_HOLD",
        "REMOVED",
        "TRANSPLANTED",
    ]
    assert isinstance(data["active_days_total"], int) and data["active_days_total"] >= 0
    assert data["waitlist_priority_score"] >= 0
    assert isinstance(data["offer_decline_count"], int) and data["offer_decline_count"] >= 0
    assert 0 <= data["cpra"] <= 1, "cpra is a fraction between 0 and 1 inclusive"


def assert_waitlist_status_event(data: dict) -> None:
    """A waitlist event is an immutable audit record: it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a waitlist event has no updated_at"
    assert "version" not in data, "a waitlist event has no version"
    assert is_valid_uuid(data["recipient_candidate_id"])
    assert isinstance(data["to_status"], str) and data["to_status"]
    assert isinstance(data["effective_at"], str) and data["effective_at"]


def assert_donor_candidate(data: dict) -> None:
    _assert_common(data)
    assert data["abo_blood_type"] in ["O", "A", "B", "AB"]
    assert data["advocacy_status"] in [
        "UNASSIGNED",
        "ASSIGNED",
        "DISCLOSED",
        "ATTESTED",
        "OBJECTED",
    ]
    for dimension in ("medical_status", "psychosocial_status"):
        assert data[dimension] in ["PENDING", "CLEARED", "EXCLUDED", "DEFERRED"], (
            f"{dimension} carries an unexpected value {data[dimension]}"
        )
    assert data["overall_status"] in [
        "REFERRED",
        "EVAL_IN_PROGRESS",
        "APPROVED",
        "CONDITIONAL_APPROVED",
        "EXCLUDED",
        "ADVOCATE_BLOCKED",
        "CHAIN_COMMITTED",
        "DONATED",
    ]
    assert data["medical_risk_points"] >= 0 and data["psychosocial_risk_points"] >= 0
    assert data["deferral_count"] >= 0
    assert data["screening_risk_index"] >= 0


def assert_donor_evaluation(data: dict) -> None:
    _assert_common(data)
    assert data["domain"] in ["MEDICAL", "PSYCHOSOCIAL"]
    assert data["status"] in ["SUBMITTED", "CLEARED", "EXCLUDED", "DEFERRED"]
    assert isinstance(data["exclusion_codes"], list)
    assert data["hard_exclusion_count"] == len(data["exclusion_codes"]), (
        "hard_exclusion_count is the length of exclusion_codes"
    )
    assert isinstance(data["risk_points"], int) and data["risk_points"] >= 0, (
        "risk_points is always a non-negative integer"
    )
    assert data["exclusion_codes"] == sorted(data["exclusion_codes"]), (
        "exclusion_codes is the sorted list of hard exclusion codes that fired"
    )
    assert data["submission_count"] >= 1


def assert_exchange_chain(data: dict) -> None:
    _assert_common(data)
    assert data["chain_type"] in ["PAIRED_LOOP", "NDD_CHAIN"]
    assert data["status"] in [
        "DRAFT",
        "VALIDATED",
        "SUSPENDED",
        "COMMITTED",
        "EXECUTING",
        "COMPLETED",
        "BROKEN",
    ]
    assert isinstance(data["is_closed_loop"], bool)
    assert data["segment_count"] >= 0
    assert data["total_planned_cit_minutes"] >= 0
    assert data["committed_donor_count"] >= 0
    if data["status"] not in ("COMMITTED", "EXECUTING"):
        assert data["committed_donor_count"] == 0, (
            "committed_donor_count is 0 for every chain status other than "
            "COMMITTED or EXECUTING"
        )


def assert_chain_segment(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in [
        "PLANNED",
        "OFFER_SENT",
        "DECLINED",
        "ACCEPTED",
        "WITHDRAWN",
        "TRANSPLANTED",
    ]
    assert data["position"] >= 1
    assert isinstance(data["cit_breach"], bool)


def assert_operating_room(data: dict) -> None:
    _assert_common(data)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["reserved_minutes_total"] >= 0


def assert_procedure_booking(data: dict) -> None:
    _assert_common(data)
    assert data["booking_role"] in ["DONOR_RECOVERY", "RECIPIENT_IMPLANT"]
    assert data["status"] in ["ACTIVE", "CANCELLED", "COMPLETED"]
    assert data["duration_minutes"] >= 0


def assert_donor_follow_up(data: dict) -> None:
    _assert_common(data)
    assert data["interval_code"] in ["SIX_MONTH", "ONE_YEAR", "TWO_YEAR"]
    assert data["status"] in [
        "DUE",
        "SUBMITTED_COMPLETE",
        "INCOMPLETE",
        "DELINQUENT",
        "WAIVED",
    ]
    assert data["required_fields_count"] in (12, 14, 10)
    if data.get("completeness_pct") is not None:
        assert 0 <= data["completeness_pct"] <= 100.00, (
            "completeness_pct never exceeds 100.00"
        )


def assert_outcome_review(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert data["flag_level"] in ["NONE", "WATCH", "FLAGGED"]
    assert isinstance(data["requires_improvement_plan"], bool)
    assert data["observed_survivor_count"] <= data["cohort_size"], (
        "observed_survivor_count must not exceed cohort_size"
    )
    assert data["requires_improvement_plan"] == (data["flag_level"] == "FLAGGED"), (
        "requires_improvement_plan is true exactly when flag_level is FLAGGED"
    )


def assert_improvement_plan(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in [
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "CLOSED",
        "SUPERSEDED",
    ]
    assert data["milestone_count"] >= 1


def assert_donor_cost_claim(data: dict) -> None:
    _assert_common(data)
    assert data["claim_type"] in ["MEDICAL", "TRAVEL", "LOST_WAGES"]
    assert data["coverage_source"] in [
        "RECIPIENT_INSURANCE",
        "NLDAC_GRANT",
        "PROGRAM_FUND",
    ]
    assert data["status"] in ["SUBMITTED", "ADJUDICATED", "DENIED", "REVERSED"]
    assert data["submitted_amount_cents"] > 0
    assert data["estimated_reimbursement_cents"] >= 0
    for part in ("insurance_part_cents", "grant_part_cents", "fund_part_cents"):
        assert data[part] >= 0, f"{part} may not be negative"
    if data["adjudicated_reimbursement_cents"] is not None:
        assert data["adjudicated_reimbursement_cents"] == (
            data["insurance_part_cents"] + data["grant_part_cents"] + data["fund_part_cents"]
        ), "adjudicated_reimbursement_cents is the sum of the three parts"
        assert data["unfunded_cents"] == (
            data["estimated_reimbursement_cents"] - data["adjudicated_reimbursement_cents"]
        ), "unfunded_cents is estimated less adjudicated"
        assert data["adjudicated_reimbursement_cents"] <= DONOR_LIFETIME_CAP_CENTS


def assert_room_minute_conservation(room: dict, bookings: list) -> None:
    """A room's reserved_minutes_total is the sum of duration_minutes over that
    room's procedure bookings whose status is ACTIVE or COMPLETED."""
    expected = sum(
        b["duration_minutes"]
        for b in bookings
        if b["operating_room_id"] == room["id"] and b["status"] in ("ACTIVE", "COMPLETED")
    )
    assert room["reserved_minutes_total"] == expected, (
        f"room {room['room_code']} reserved_minutes_total {room['reserved_minutes_total']} "
        f"must equal the ACTIVE+COMPLETED booking sum {expected}"
    )


def assert_chain_commitment_conservation(chains: list, donors: list) -> None:
    """Summed over all chains of a program, committed_donor_count must equal the
    number of that program's donor candidates whose overall_status is
    CHAIN_COMMITTED."""
    chain_side = sum(c["committed_donor_count"] for c in chains)
    donor_side = sum(1 for d in donors if d["overall_status"] == "CHAIN_COMMITTED")
    assert chain_side == donor_side, (
        f"committed_donor_count sum {chain_side} must equal the count of "
        f"CHAIN_COMMITTED donors {donor_side}"
    )
