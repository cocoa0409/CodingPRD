"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["state_code"], str)
    assert data["schedule_status"] in (
        "UP_TO_DATE", "BEHIND", "CONDITIONAL", "NON_COMPLIANT")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["vfc_pin"], str) and len(data["vfc_pin"]) > 0
    assert isinstance(data["authorized_product_codes"], list)
    assert data["status"] in ("ENROLLED", "SUSPENDED")


def assert_vaccine_product(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and len(data["product_code"]) > 0
    assert isinstance(data["antigen"], str)
    assert data["doses_in_series"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_vaccine_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["lot_number"], str)
    assert data["doses_total"] >= 1
    assert isinstance(data["administered_count"], int)
    assert data["status"] in ("AVAILABLE", "RECALLED")


def assert_immunization(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["provider_id"], str)
    assert isinstance(data["administered_date"], str)
    assert data["validity"] in (
        "VALID", "INVALID_INTERVAL", "INVALID_AGE", "INVALID_RECALL")
    assert data["status"] in ("RECORDED", "AMENDED", "INVALIDATED", "DELETED")


def assert_allergy_record(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["antigen"], str)
    assert data["severity"] in ("CONTRAINDICATED", "PRECAUTION")
    assert data["origin"] in ("MANUAL", "ADVERSE_EVENT")


def assert_provider_report(data: dict):
    _assert_common(data)
    assert isinstance(data["provider_id"], str)
    assert data["line_count"] >= 1
    assert isinstance(data["accepted_count"], int)
    assert isinstance(data["rejected_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "PARTIALLY_REJECTED", "REJECTED")


def assert_adverse_event(data: dict):
    _assert_common(data)
    assert isinstance(data["immunization_id"], str)
    assert isinstance(data["patient_id"], str)
    assert data["seriousness"] in ("SERIOUS", "NON_SERIOUS")
    assert data["status"] in ("REPORTED", "UNDER_REVIEW", "CONFIRMED", "DISMISSED")


def assert_schedule_evaluation(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert data["overall_status"] in (
        "UP_TO_DATE", "BEHIND", "CONDITIONAL", "NON_COMPLIANT")
    assert isinstance(data["antigen_results"], list)
    assert isinstance(data["completeness_pct"], (int, float))


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["evaluation_id"], str)
    assert data["certificate_type"] in ("COMPLETE", "CONDITIONAL")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED")


def assert_lot_recall(data: dict):
    _assert_common(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["invalidated_count"], int)


def find_antigen_result(evaluation: dict, antigen: str) -> dict:
    """Return the per-antigen result object for `antigen` in a ScheduleEvaluation."""
    for r in evaluation.get("antigen_results", []):
        if r.get("antigen") == antigen:
            return r
    raise AssertionError(
        f"antigen {antigen!r} not present in antigen_results: "
        f"{[r.get('antigen') for r in evaluation.get('antigen_results', [])]}")
