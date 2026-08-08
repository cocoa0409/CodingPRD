"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_program(data: dict):
    _common(data)
    assert isinstance(data["program_name"], str)
    assert data["incentive_type"] in ("TIF", "ABATEMENT", "GRANT")
    for f in ("total_budget_cents", "committed_cents", "disbursed_cents", "available_budget_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer cent value"
    assert_program_partition(data)


def assert_program_partition(data: dict):
    """§2.6: available + committed + disbursed == total_budget_cents, always."""
    total = data["total_budget_cents"]
    part = data["available_budget_cents"] + data["committed_cents"] + data["disbursed_cents"]
    assert part == total, f"budget partition {part} != total {total}"
    assert data["committed_cents"] >= 0
    assert data["disbursed_cents"] >= 0
    assert data["available_budget_cents"] >= 0


def assert_parcel(data: dict):
    _common(data)
    assert isinstance(data["base_assessed_value_cents"], int)
    assert isinstance(data["current_assessed_value_cents"], int)


def assert_application(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert isinstance(data["proposed_jobs"], int)
    assert isinstance(data["proposed_investment_cents"], int)


def assert_eligibility_review(data: dict):
    """§2.4: an eligibility review is append-only — id + created_at only, no version/updated_at."""
    _common(data)
    assert data["finding"] in ("PASS", "FAIL")
    assert "version" not in data, "eligibility review must not carry a version field"
    assert "updated_at" not in data, "eligibility review must not carry an updated_at field"


def assert_agreement(data: dict):
    _common(data)
    assert data["status"] in ("EXECUTED", "ACTIVE", "COMPLETED", "DEFAULTED", "CLOSED")
    assert data["incentive_type"] in ("TIF", "ABATEMENT", "GRANT")
    for f in ("max_incentive_cents", "gross_disbursed_cents", "net_disbursed_cents", "clawed_back_cents"):
        assert isinstance(data[f], int)
    assert_agreement_ledger(data)


def assert_agreement_ledger(data: dict):
    """§2.7: gross_disbursed_cents == net_disbursed_cents + clawed_back_cents."""
    assert data["gross_disbursed_cents"] == data["net_disbursed_cents"] + data["clawed_back_cents"], (
        "ledger partition violated: gross != net + clawed_back"
    )
    assert data["gross_disbursed_cents"] >= 0
    assert data["clawed_back_cents"] >= 0


def assert_covenant(data: dict):
    _common(data)
    assert data["covenant_type"] in ("JOBS", "INVESTMENT")
    assert data["status"] in ("ACTIVE", "MET", "BREACHED", "WAIVED")


def assert_compliance_report(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "RETURNED", "ACCEPTED")


def assert_disbursement(data: dict):
    _common(data)
    assert data["status"] in ("CALCULATED", "APPROVED", "PAID", "CLAWED_BACK")
    assert isinstance(data["gross_entitlement_cents"], int)
    assert isinstance(data["disbursed_amount_cents"], int)


def assert_recapture_assessment(data: dict):
    _common(data)
    assert data["severity"] in ("PARTIAL", "MATERIAL")
    assert data["status"] in ("ASSESSED", "DISPUTED", "FINALIZED", "WAIVED")
    assert isinstance(data["assessed_amount_cents"], int)


def assert_disclosure(data: dict):
    _common(data)
    assert data["status"] == "PUBLISHED"
    assert data["disclosed_incentive_type"] in ("TIF", "ABATEMENT", "GRANT")
