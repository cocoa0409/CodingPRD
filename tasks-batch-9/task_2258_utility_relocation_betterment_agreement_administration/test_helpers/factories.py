"""Request payload builders.  Each returns the canonical body with overrides applied."""
from .constants import (
    AGREEMENT_NOT_TO_EXCEED_CENTS,
    COMMITMENT_PAYLOAD,
    CONFLICT_PAYLOAD,
    FACILITY_PAYLOAD,
    OWNER_PAYLOAD,
    PERMIT_PAYLOAD,
    PLAN_PAYLOAD,
    PRIOR_RIGHTS_PAYLOAD,
    PROJECT_PAYLOAD,
    SECOND_FACILITY_PAYLOAD,
    THIRD_FACILITY_PAYLOAD,
)


def _merge(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    payload.update(overrides)
    return payload


def project_payload(**overrides) -> dict:
    return _merge(PROJECT_PAYLOAD, overrides)


def owner_payload(**overrides) -> dict:
    return _merge(OWNER_PAYLOAD, overrides)


def facility_payload(owner_id: str, **overrides) -> dict:
    return _merge({**FACILITY_PAYLOAD, "owner_id": owner_id}, overrides)


def second_facility_payload(owner_id: str, **overrides) -> dict:
    return _merge({**SECOND_FACILITY_PAYLOAD, "owner_id": owner_id}, overrides)


def third_facility_payload(owner_id: str, **overrides) -> dict:
    return _merge({**THIRD_FACILITY_PAYLOAD, "owner_id": owner_id}, overrides)


def investigation_payload(
    project_id: str,
    facility_id: str,
    quality_level: str = "QL_A",
    method: str = "VACUUM_TEST_HOLE",
    measured_depth_in: int = 48,
    station_at_investigation: float = 120.0,
    **overrides,
) -> dict:
    return _merge(
        {
            "project_id": project_id,
            "facility_id": facility_id,
            "quality_level": quality_level,
            "method": method,
            "measured_depth_in": measured_depth_in,
            "station_at_investigation": station_at_investigation,
        },
        overrides,
    )


def conflict_payload(project_id: str, facility_id: str, **overrides) -> dict:
    return _merge(
        {**CONFLICT_PAYLOAD, "project_id": project_id, "facility_id": facility_id},
        overrides,
    )


def prior_rights_payload(conflict_id: str, **overrides) -> dict:
    return _merge({**PRIOR_RIGHTS_PAYLOAD, "conflict_id": conflict_id}, overrides)


def permit_payload(conflict_id: str, **overrides) -> dict:
    return _merge({**PERMIT_PAYLOAD, "conflict_id": conflict_id}, overrides)


def plan_payload(conflict_id: str, expected_conflict_version: int, **overrides) -> dict:
    return _merge(
        {
            **PLAN_PAYLOAD,
            "conflict_id": conflict_id,
            "expected_conflict_version": expected_conflict_version,
        },
        overrides,
    )


def plan_resubmit_payload(**overrides) -> dict:
    return _merge(PLAN_PAYLOAD, overrides)


def joint_trench_slot_payload(
    project_id: str,
    segment_code: str = "SEG-A",
    trench_open_start: str = "2027-04-01T00:00:00Z",
    trench_open_end: str = "2027-05-01T00:00:00Z",
    max_occupants: int = 2,
    **overrides,
) -> dict:
    return _merge(
        {
            "project_id": project_id,
            "segment_code": segment_code,
            "trench_open_start": trench_open_start,
            "trench_open_end": trench_open_end,
            "max_occupants": max_occupants,
        },
        overrides,
    )


def commitment_payload(plan_id: str, **overrides) -> dict:
    return _merge({**COMMITMENT_PAYLOAD, "plan_id": plan_id}, overrides)


def agreement_payload(
    plan_id: str,
    expected_plan_version: int,
    not_to_exceed_cents: int = AGREEMENT_NOT_TO_EXCEED_CENTS,
    **overrides,
) -> dict:
    return _merge(
        {
            "plan_id": plan_id,
            "expected_plan_version": expected_plan_version,
            "not_to_exceed_cents": not_to_exceed_cents,
        },
        overrides,
    )


def cost_document_payload(
    agreement_id: str,
    doc_type: str = "LABOR",
    amount_cents: int = 12_345_678,
    incurred_on: str = "2027-04-02T00:00:00Z",
    support_reference: str = "PR-1001",
    **overrides,
) -> dict:
    return _merge(
        {
            "agreement_id": agreement_id,
            "doc_type": doc_type,
            "amount_cents": amount_cents,
            "incurred_on": incurred_on,
            "support_reference": support_reference,
        },
        overrides,
    )


def audit_finding_payload(
    agreement_id: str,
    finding_type: str = "UNSUPPORTED_COST",
    questioned_cost_cents: int = 500_000,
    narrative: str = "Labour hours are not supported by certified payrolls.",
    **overrides,
) -> dict:
    return _merge(
        {
            "agreement_id": agreement_id,
            "finding_type": finding_type,
            "questioned_cost_cents": questioned_cost_cents,
            "narrative": narrative,
        },
        overrides,
    )


def delay_claim_payload(
    commitment_id: str,
    project_id: str,
    contractor_name: str = "Granite Ridge Constructors",
    claimed_days: int = 4,
    claimed_amount_cents: int = 1_200_000,
    **overrides,
) -> dict:
    return _merge(
        {
            "commitment_id": commitment_id,
            "project_id": project_id,
            "contractor_name": contractor_name,
            "claimed_days": claimed_days,
            "claimed_amount_cents": claimed_amount_cents,
        },
        overrides,
    )


__all__ = [
    "project_payload",
    "owner_payload",
    "facility_payload",
    "second_facility_payload",
    "third_facility_payload",
    "investigation_payload",
    "conflict_payload",
    "prior_rights_payload",
    "permit_payload",
    "plan_payload",
    "plan_resubmit_payload",
    "joint_trench_slot_payload",
    "commitment_payload",
    "agreement_payload",
    "cost_document_payload",
    "audit_finding_payload",
    "delay_claim_payload",
]
