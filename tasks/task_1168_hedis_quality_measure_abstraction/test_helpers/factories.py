"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""

SEASON_DEFAULTS = {
    "measurement_year": 2025,
    "submission_deadline": "2026-06-15T00:00:00Z",
    "admin_data_cutoff": "2026-03-31T00:00:00Z",
    "approved_supplemental_sources": ["LAB_FEED"],
}

SPEC_DEFAULTS = {
    "hedis_measure_code": "BCS",
    "version_label": "2025.1",
    "collection_method": "ADMINISTRATIVE",
    "age_min": 0,
    "age_max": 100,
    "gender_requirement": "ANY",
    "continuous_enrollment_months": 12,
    "anchor_date": "2025-12-31T00:00:00Z",
}

MEMBER_DEFAULTS = {
    "birth_date": "1990-01-01T00:00:00Z",
    "gender": "F",
}

FULL_YEAR_2025 = ("2025-01-01T00:00:00Z", "2025-12-31T00:00:00Z")


def create_season_payload(**overrides) -> dict:
    payload = dict(SEASON_DEFAULTS)
    payload.update(overrides)
    return payload


def create_spec_payload(season_id, expected_season_version, **overrides) -> dict:
    payload = dict(SPEC_DEFAULTS)
    payload.update(overrides)
    payload["season_id"] = season_id
    payload["expected_season_version"] = expected_season_version
    return payload


def create_member_payload(member_ref="M1", **overrides) -> dict:
    payload = dict(MEMBER_DEFAULTS)
    payload.update(overrides)
    payload["member_ref"] = member_ref
    return payload


def create_enrollment_segment_payload(member_id, span_start=None, span_end=None, **overrides) -> dict:
    start, end = FULL_YEAR_2025
    payload = {
        "member_id": member_id,
        "span_start": span_start or start,
        "span_end": span_end or end,
    }
    payload.update(overrides)
    return payload


def create_provider_payload(provider_ref="P1", name=None, **overrides) -> dict:
    payload = {"provider_ref": provider_ref, "name": name or f"Provider {provider_ref}"}
    payload.update(overrides)
    return payload


def create_run_payload(season_id, spec_id) -> dict:
    return {"season_id": season_id, "spec_id": spec_id}


def create_sample_payload(run_id) -> dict:
    return {"run_id": run_id}


def create_exclusion_payload(reason="DISENROLLED") -> dict:
    return {"reason": reason}


def create_abstraction_payload(chase_id, result="HIT") -> dict:
    return {"chase_id": chase_id, "result": result}


def create_overread_payload(abstraction_id, outcome="AGREE", final_result=None) -> dict:
    payload = {"abstraction_id": abstraction_id, "outcome": outcome}
    if final_result is not None:
        payload["final_result"] = final_result
    return payload


def create_batch_payload(run_id, source_type="LAB_FEED") -> dict:
    return {"run_id": run_id, "source_type": source_type}


def create_record_payload(batch_id, member_ref, service_date, evidence_code="A1C") -> dict:
    return {
        "batch_id": batch_id,
        "member_ref": member_ref,
        "service_date": service_date,
        "evidence_code": evidence_code,
    }


def create_chase_exclusion_payload(reason="DECEASED") -> dict:
    return {"reason": reason}


def create_gap_close_payload(outcome="CLOSED_COMPLIANT") -> dict:
    return {"outcome": outcome}


def create_engagement_payload(season_id, measure_run_id, auditor_user_id="aud-1",
                              window_start="2026-01-01T00:00:00Z",
                              window_end="2026-07-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "measure_run_id": measure_run_id,
        "auditor_user_id": auditor_user_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_finding_payload(engagement_id, severity="MINOR", summary="finding") -> dict:
    return {"engagement_id": engagement_id, "severity": severity, "summary": summary}


def create_certify_payload(decision="CERTIFIED") -> dict:
    return {"decision": decision}
