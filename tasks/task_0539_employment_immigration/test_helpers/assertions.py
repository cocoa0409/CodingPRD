"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["fein"], str) and len(data["fein"]) > 0
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["employee_count"], int) and data["employee_count"] >= 1
    assert isinstance(data["h1b_dependent"], bool)
    assert isinstance(data["total_wage_obligation_cents"], int)
    assert data["total_wage_obligation_cents"] >= 0


def assert_pwd(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ISSUED", "SUPERSEDED", "EXPIRED")
    assert data["wage_source"] in ("OES", "EMPLOYER_SURVEY")
    assert data["wage_level"] in ("LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV")
    assert isinstance(data["oes_wage_cents"], int) and data["oes_wage_cents"] >= 0


def assert_perm_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "RECRUITING", "QUIET_PERIOD", "FILED", "AUDIT", "CERTIFIED", "DENIED")
    assert isinstance(data["offered_wage_cents"], int) and data["offered_wage_cents"] >= 0


def assert_recruitment_step(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOID")
    assert data["step_type"] in ("JOB_ORDER", "NEWSPAPER_AD", "PROFESSIONAL_JOURNAL",
                                 "EMPLOYER_WEBSITE", "JOB_FAIR")


def assert_lca(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "CERTIFIED", "WITHDRAWN", "EXPIRED")
    assert data["paf_status"] in ("OPEN", "COMPLETE", "DEFICIENT")
    assert isinstance(data["required_wage_cents"], int)
    assert isinstance(data["aggregate_wage_obligation_cents"], int)
    assert isinstance(data["worksite_areas"], list) and len(data["worksite_areas"]) >= 1


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert data["current_status_code"] in ("NONE", "H1B_ACTIVE", "H1B_EXPIRED")


def assert_cap_program(data: dict):
    _assert_common(data)
    assert isinstance(data["selection_quota"], int) and data["selection_quota"] >= 0
    assert isinstance(data["selected_count"], int)
    assert isinstance(data["available_seats"], int)
    assert isinstance(data["lottery_run"], bool)
    # PRD §3.5 invariant: available_seats + selected_count == selection_quota
    assert data["available_seats"] + data["selected_count"] == data["selection_quota"]


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "SELECTED", "NOT_SELECTED", "WITHDRAWN")


def assert_h1b_petition(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RFE_ISSUED", "APPROVED", "DENIED")
    assert data["rfe_status"] in ("NONE", "ISSUED", "RESPONDED")
    assert isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0


def assert_i140_petition(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED")
    assert data["category"] in ("EB1", "EB2", "EB3")


def assert_cap_seat_invariant(data: dict):
    """PRD §3.5: available_seats + selected_count == selection_quota at all times."""
    assert data["available_seats"] + data["selected_count"] == data["selection_quota"], (
        f"cap-seat invariant violated: {data['available_seats']} + "
        f"{data['selected_count']} != {data['selection_quota']}"
    )
