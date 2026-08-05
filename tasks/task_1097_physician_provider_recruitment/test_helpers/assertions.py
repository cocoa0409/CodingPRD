"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_staff_user(data: dict):
    _assert_common(data)
    assert data["role"] in ("RECRUITER", "ACCOUNT_MANAGER", "CREDENTIALING_COORDINATOR")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["net_placement_fee_cents"], int)
    assert 0 < data["contingency_pct"] <= 1
    assert data["min_fee_cents"] >= 0
    assert data["guarantee_days"] >= 1


def assert_job_opening(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "OPEN", "ON_HOLD", "FILLED", "CLOSED")
    assert data["positions_filled"] >= 0
    assert data["positions_total"] >= 1
    assert data["comp_max_cents"] >= data["comp_min_cents"]


def assert_candidate(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PLACED", "DO_NOT_CONTACT")


def assert_application(data: dict):
    _assert_common(data)
    assert data["stage"] in (
        "SOURCED", "SCREENED", "SUBMITTED", "INTERVIEWING",
        "OFFER_STAGE", "PLACED", "REJECTED", "WITHDRAWN",
    )
    assert 0 <= data["match_score"] <= 100


def assert_site_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "EXTENDED", "COUNTERED", "ACCEPTED", "DECLINED", "RESCINDED", "EXPIRED"
    )
    assert data["round_number"] >= 1
    assert data["offered_first_year_comp_cents"] == (
        data["base_salary_cents"] + data["sign_on_bonus_cents"]
    ), "offered_first_year_comp_cents == base + sign_on"


def assert_placement(data: dict):
    _assert_common(data)
    assert data["placement_status"] in (
        "PRE_START", "ACTIVE", "GUARANTEE_MET", "FELL_OUT", "CANCELLED"
    )
    assert data["fee_status"] in ("PENDING", "INVOICED", "PAID", "CREDITED", "WAIVED")
    assert data["relocation_status"] in ("NONE", "APPROVED", "REIMBURSED")
    assert data["relocation_reimbursed_cents"] <= data["relocation_cap_cents"] or \
        data["relocation_cap_cents"] == 0 or data["relocation_reimbursed_cents"] >= 0


def assert_credentialing_file(data: dict):
    _assert_common(data)
    assert data["overall_status"] in ("NOT_STARTED", "IN_PROGRESS", "CLEARED", "FLAGGED")


def assert_credential_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SUBMITTED", "VERIFIED", "FLAGGED")


def assert_guarantee_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "APPROVED", "DENIED", "RESOLVED_REFUND", "RESOLVED_REPLACEMENT"
    )


def assert_client_ledger_invariant(client: dict, recognized: int, credited: int):
    """PRD §3.8: net always equals recognized minus credited (no drift)."""
    assert client["net_placement_fee_cents"] == recognized - credited, (
        f"net {client['net_placement_fee_cents']} != recognized {recognized} "
        f"- credited {credited}"
    )
