"""Request payload factories.

Each factory returns only the *client-supplied* input fields of the matching
endpoint in PRD §4; computed fields are never sent.  Optional fields are
omitted unless the caller passes them, so a bare factory call exercises the
PRD's documented defaults.  `None` passed explicitly means "omit".
"""

from typing import Any, Dict, Optional

# The canonical plan model used across the suite.  Under `IECC_2021` / `CZ4`
# its §3.1 projected index is 43.
CANONICAL_PLAN = {
    "plan_code": "STD-2400",
    "conditioned_floor_area_sqft": 2400,
    "conditioned_volume_cuft": 21600,
    "bedrooms": 4,
    "envelope_ua_btu_per_hr_f": 320,
    "design_ach50": 3.00,
    "design_duct_leakage_cfm25_per_100sqft": 3.00,
    "hvac_efficiency_index": 9,
    "pv_capacity_kw_dc": 0,
}


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def builder_payload(
    *,
    name: str = "Anchor Homes",
    builder_type: str = "PRODUCTION",
    utility_program_budget_cents: int = 250000,
) -> Dict[str, Any]:
    return {
        "name": name,
        "builder_type": builder_type,
        "utility_program_budget_cents": utility_program_budget_cents,
    }


def subdivision_payload(
    builder_id: str,
    *,
    name: str = "Mill Race",
    code_edition: str = "IECC_2021",
    climate_zone: str = "CZ4",
    sampling_enabled: Optional[bool] = None,
    compliance_path_preference: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "builder_id": builder_id,
            "name": name,
            "code_edition": code_edition,
            "climate_zone": climate_zone,
            "sampling_enabled": sampling_enabled,
            "compliance_path_preference": compliance_path_preference,
        }
    )


def plan_model_payload(subdivision_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"subdivision_id": subdivision_id}
    payload.update(CANONICAL_PLAN)
    payload.update(overrides)
    return _drop_none(payload)


def home_payload(
    subdivision_id: str,
    plan_model_id: str,
    *,
    lot_number: str = "L-1001",
    permit_date: str = "2026-08-10",
) -> Dict[str, Any]:
    return {
        "subdivision_id": subdivision_id,
        "plan_model_id": plan_model_id,
        "lot_number": lot_number,
        "permit_date": permit_date,
    }


def rater_payload(
    *,
    full_name: str = "Rae Tarrant",
    cert_level: str = "RATER",
    cert_expires_at: str = "2027-06-30T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "full_name": full_name,
        "cert_level": cert_level,
        "cert_expires_at": cert_expires_at,
    }


def rating_payload(
    home_id: str, rater_id: str, *, supersedes_rating_id: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none(
        {
            "home_id": home_id,
            "rater_id": rater_id,
            "supersedes_rating_id": supersedes_rating_id,
        }
    )


def inspection_payload(
    rating_id: str,
    inspector_id: str,
    *,
    checkpoint: str = "FINAL",
    scheduled_start_utc: str = "2026-08-21T09:00:00Z",
    scheduled_end_utc: str = "2026-08-21T11:00:00Z",
    air_handler_installed: Optional[bool] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "rating_id": rating_id,
            "inspector_id": inspector_id,
            "checkpoint": checkpoint,
            "scheduled_start_utc": scheduled_start_utc,
            "scheduled_end_utc": scheduled_end_utc,
            "air_handler_installed": air_handler_installed,
        }
    )


def diagnostic_test_payload(test_type: str, measured_value: float) -> Dict[str, Any]:
    return {"test_type": test_type, "measured_value": measured_value}


def sample_set_payload(
    subdivision_id: str,
    *,
    window_start_date: str = "2026-08-01",
    window_end_date: str = "2026-08-31",
) -> Dict[str, Any]:
    return {
        "subdivision_id": subdivision_id,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }


def sample_set_membership_payload(home_id: str, expected_sample_set_version: int) -> Dict[str, Any]:
    return {
        "home_id": home_id,
        "expected_sample_set_version": expected_sample_set_version,
    }


def sample_set_withdraw_payload(expected_sample_set_version: int) -> Dict[str, Any]:
    return {"expected_sample_set_version": expected_sample_set_version}


def qa_review_payload(
    rating_id: str, reviewer_id: str, *, review_type: str = "FILE_REVIEW"
) -> Dict[str, Any]:
    return {
        "rating_id": rating_id,
        "reviewer_id": reviewer_id,
        "review_type": review_type,
    }


def qa_review_completion_payload(
    result: str, *, findings_note: str = "Reviewed against the submitted file"
) -> Dict[str, Any]:
    return {"result": result, "findings_note": findings_note}


def corrective_action_submission_payload(
    *, remediation_note: str = "Air sealing completed at rim joists and top plates"
) -> Dict[str, Any]:
    return {"remediation_note": remediation_note}


def corrective_action_review_payload(
    decision: str, *, note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"decision": decision, "note": note})


def document_package_payload(
    rating_id: str, expected_rating_version: int, *, package_type: str = "TAX_CREDIT_45L"
) -> Dict[str, Any]:
    return {
        "rating_id": rating_id,
        "package_type": package_type,
        "expected_rating_version": expected_rating_version,
    }


def registry_decision_payload(
    outcome: str,
    *,
    confirmation_number: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "outcome": outcome,
            "confirmation_number": confirmation_number,
            "rejection_reason": rejection_reason,
        }
    )


def void_payload(*, reason: str = "Registry dispute on the duct worksheet") -> Dict[str, Any]:
    return {"reason": reason}


def reinstate_payload(
    *, training_completed_at: str = "2026-08-05T00:00:00Z", note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"training_completed_at": training_completed_at, "note": note})


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
