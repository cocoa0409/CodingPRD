"""Per-entity assertions for the Scholarship Review API.

PRD §2.4 splits entities into two field-shapes:
- Versioned (id + created_at + updated_at + version):
  Scholarship, QuotaAllocation, Reviewer, Application, Objection,
  DisbursementPlan.
- Append-only (id + created_at only; no updated_at, no version):
  ReviewerAssignment, Score, DisbursementRecord, AuditEvent,
  ExternalSyncEvent.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared field shape checkers
# ---------------------------------------------------------------------------
def _check_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """PRD §2.4 versioned fields: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity_name}.updated_at must be ISO 8601"
    assert "version" in data, f"{entity_name} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity_name}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any],
                              entity_name: str) -> None:
    """PRD §2.4: append-only entities carry only id + created_at."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity_name}.created_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Scholarship
# ---------------------------------------------------------------------------
SCHOLARSHIP_STATES = {
    "DRAFT", "OPEN", "REVIEWING", "ANNOUNCED", "FINALIZED", "DISBURSED",
}
SCHOLARSHIP_CATEGORIES = {"MERIT", "NEED", "RESEARCH", "SPECIAL_GROUP"}


def assert_scholarship(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Scholarship")
    assert isinstance(data.get("code"), str) and len(data["code"]) >= 3
    assert isinstance(data.get("name"), str)
    assert data.get("category") in SCHOLARSHIP_CATEGORIES, (
        f"category must be one of MERIT/NEED/RESEARCH/SPECIAL_GROUP, "
        f"got {data.get('category')!r}"
    )
    assert isinstance(data.get("per_award_amount_cents"), int)
    assert data["per_award_amount_cents"] >= 1
    assert isinstance(data.get("total_quota"), int)
    assert data["total_quota"] >= 1
    assert isinstance(data.get("gpa_threshold_x100"), int)
    assert isinstance(data.get("eligible_majors"), list)
    assert isinstance(data.get("eligible_grades"), list)
    assert isinstance(data.get("required_materials"), list)
    assert isinstance(data.get("application_window_start"), str)
    assert isinstance(data.get("application_window_end"), str)
    assert isinstance(data.get("announcement_window_end"), str)
    assert data.get("status") in SCHOLARSHIP_STATES
    assert isinstance(data.get("rubric_weights"), dict)
    # PRD §3.1: weights sum to exactly 100
    assert sum(data["rubric_weights"].values()) == 100, (
        f"rubric_weights values must sum to exactly 100, "
        f"got {sum(data['rubric_weights'].values())}"
    )
    # PRD §3.1: non-NEED -> family_income_ceiling_cents must be null
    if data["category"] != "NEED":
        assert data.get("family_income_ceiling_cents") is None, (
            "Non-NEED scholarship must carry "
            "family_income_ceiling_cents=null"
        )


# ---------------------------------------------------------------------------
# QuotaAllocation
# ---------------------------------------------------------------------------
SPECIAL_GROUPS = {
    "NONE", "GENDER_FEMALE", "GENDER_MALE",
    "ETHNIC_MINORITY", "DISABILITY",
}


def assert_quota_allocation(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "QuotaAllocation")
    assert is_valid_uuid(data.get("scholarship_id", ""))
    assert isinstance(data.get("department_code"), str)
    assert isinstance(data.get("grade"), int)
    assert data.get("special_group") in SPECIAL_GROUPS
    assert isinstance(data.get("initial_slots"), int)
    assert data["initial_slots"] >= 0
    assert isinstance(data.get("current_slots"), int)
    assert isinstance(data.get("filled_slots"), int)
    assert data["filled_slots"] >= 0
    assert isinstance(data.get("reallocated_from_ids"), list)


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------
REVIEWER_STATES = {"ACTIVE", "SUSPENDED"}


def assert_reviewer(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Reviewer")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("department_code"), str)
    assert isinstance(data.get("family_relation_student_ids"), list)
    assert data.get("status") in REVIEWER_STATES


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APPLICATION_STATES = {
    "DRAFT", "SUBMITTED",
    "DEPT_PRELIM_PASSED", "DEPT_PRELIM_REJECTED",
    "UNDER_REVIEW", "REVIEW_COMPLETE",
    "AWARDED", "NOT_AWARDED",
    "WITHDRAWN", "DISBURSED", "REVOKED",
}
REVOCATION_REASONS = {"OBJECTION_UPHELD", "AUDIT_FAILURE", None}


def assert_application(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Application")
    assert is_valid_uuid(data.get("scholarship_id", ""))
    assert isinstance(data.get("student_id"), str) and data["student_id"]
    assert isinstance(data.get("student_department_code"), str)
    assert isinstance(data.get("student_major"), str)
    assert isinstance(data.get("student_grade"), int)
    assert isinstance(data.get("student_gpa_x100"), int)
    assert isinstance(data.get("uploaded_materials"), list)
    assert data.get("status") in APPLICATION_STATES, (
        f"Application.status invalid: {data.get('status')!r}"
    )
    assert data.get("revocation_reason") in REVOCATION_REASONS


# ---------------------------------------------------------------------------
# Objection
# ---------------------------------------------------------------------------
OBJECTION_STATES = {"PENDING", "UPHELD", "DISMISSED"}
OBJECTION_REASON_CODES = {
    "MATERIAL_FALSE", "SCORING_ERROR",
    "ELIGIBILITY_BREACH", "COI_BREACH",
}


def assert_objection(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Objection")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("objector_student_id"), str)
    assert data.get("reason_code") in OBJECTION_REASON_CODES
    assert isinstance(data.get("description"), str)
    assert data.get("status") in OBJECTION_STATES


# ---------------------------------------------------------------------------
# DisbursementPlan
# ---------------------------------------------------------------------------
DISBURSEMENT_PLAN_STATES = {
    "DRAFT", "DEPT_APPROVED", "FINANCE_APPROVED", "EXECUTED", "ARCHIVED",
}
PAYMENT_CHANNELS = {"BANK", "CAMPUS_CARD"}


def assert_disbursement_plan(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "DisbursementPlan")
    assert is_valid_uuid(data.get("scholarship_id", ""))
    assert data.get("payment_channel") in PAYMENT_CHANNELS
    assert data.get("status") in DISBURSEMENT_PLAN_STATES
    assert isinstance(data.get("total_gross_cents"), int)
    assert data["total_gross_cents"] >= 0
    assert isinstance(data.get("total_tax_cents"), int)
    assert data["total_tax_cents"] >= 0
    assert isinstance(data.get("total_net_cents"), int)
    # PRD §3.10: 'total_net_cents equals total_gross_cents minus
    # total_tax_cents'
    assert (
        data["total_net_cents"]
        == data["total_gross_cents"] - data["total_tax_cents"]
    ), (
        "DisbursementPlan invariant: total_net_cents == "
        "total_gross_cents - total_tax_cents"
    )


# ---------------------------------------------------------------------------
# Append-only entities
# ---------------------------------------------------------------------------
def assert_reviewer_assignment(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "ReviewerAssignment")
    # No updated_at / version per PRD §2.4
    assert "updated_at" not in data, (
        "ReviewerAssignment is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "ReviewerAssignment is append-only and must not carry version"
    )
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))


def assert_score(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "Score")
    assert "updated_at" not in data, (
        "Score is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "Score is append-only and must not carry version"
    )
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))
    assert isinstance(data.get("criterion_scores"), dict)
    assert isinstance(data.get("raw_total_x100"), int)
    assert isinstance(data.get("is_outlier"), bool)


def assert_disbursement_record(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "DisbursementRecord")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("gross_cents"), int)
    assert isinstance(data.get("tax_withheld_cents"), int)
    assert isinstance(data.get("net_cents"), int)
    # PRD §3.10: 'net_cents (equal to gross_cents minus tax_withheld_cents)'
    assert data["net_cents"] == (
        data["gross_cents"] - data["tax_withheld_cents"]
    ), (
        "DisbursementRecord invariant: net_cents == "
        "gross_cents - tax_withheld_cents"
    )
    assert data.get("payment_channel") in PAYMENT_CHANNELS


def assert_audit_event(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditEvent")
    assert isinstance(data.get("event_type"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)
    assert isinstance(data.get("payload"), dict)


def assert_external_sync_event(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "ExternalSyncEvent")
    assert data.get("kind") in {
        "ACADEMIC_AFFAIRS_FINALIZED", "FINANCE_DISBURSED",
        "IM_NOTIFY_AWARD", "IM_NOTIFY_REJECT",
        "IM_NOTIFY_OBJECTION_RULING",
    }
    assert isinstance(data.get("scholarship_id"), str)
    assert isinstance(data.get("payload"), dict)


# ---------------------------------------------------------------------------
# Helpers to search audit / external-sync streams
# ---------------------------------------------------------------------------
def find_audit_events(events: List[Dict[str, Any]], *,
                      event_type: Optional[str] = None,
                      target_entity: Optional[str] = None,
                      target_id: Optional[str] = None,
                      ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events:
        if event_type is not None and ev.get("event_type") != event_type:
            continue
        if (target_entity is not None and
                ev.get("target_entity") != target_entity):
            continue
        if target_id is not None and ev.get("target_id") != target_id:
            continue
        out.append(ev)
    return out


def find_external_sync_events(
    events: List[Dict[str, Any]], *,
    kind: Optional[str] = None,
    application_id: Optional[str] = None,
    scholarship_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events:
        if kind is not None and ev.get("kind") != kind:
            continue
        if (application_id is not None and
                ev.get("application_id") != application_id):
            continue
        if (scholarship_id is not None and
                ev.get("scholarship_id") != scholarship_id):
            continue
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_quota_slot_invariant(slices: Iterable[Dict[str, Any]],
                                applications: Iterable[Dict[str, Any]],
                                ) -> None:
    """PRD §3.1 / §3.8: filled_slots reflects 'the running count of
    applications in the slice with status AWARDED or DISBURSED'. The
    summed conservation invariant: sum(filled_slots) ==
    count(Application.status in {AWARDED, DISBURSED}) for this
    scholarship.
    """
    total_filled = sum(int(s.get("filled_slots", 0)) for s in slices)
    awarded_or_disbursed = sum(
        1 for a in applications
        if a.get("status") in {"AWARDED", "DISBURSED"}
    )
    assert total_filled == awarded_or_disbursed, (
        f"Quota-slot invariant violated: sum(filled_slots)={total_filled} "
        f"!= count(Application.status in AWARDED/DISBURSED)"
        f"={awarded_or_disbursed}"
    )


__all__ = [
    "assert_scholarship",
    "assert_quota_allocation",
    "assert_reviewer",
    "assert_application",
    "assert_objection",
    "assert_disbursement_plan",
    "assert_reviewer_assignment",
    "assert_score",
    "assert_disbursement_record",
    "assert_audit_event",
    "assert_external_sync_event",
    "find_audit_events",
    "find_external_sync_events",
    "assert_quota_slot_invariant",
    "SCHOLARSHIP_STATES",
    "APPLICATION_STATES",
    "DISBURSEMENT_PLAN_STATES",
]
