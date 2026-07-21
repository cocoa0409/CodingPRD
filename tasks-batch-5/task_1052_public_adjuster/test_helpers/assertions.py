"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_adjuster(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["firm_name"], str)
    assert isinstance(data["email"], str)


def assert_license(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data["state_code"], str)


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"


def assert_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert_policy_invariants(data)


def assert_policy_invariants(data: dict):
    """coverage_limit_cents == remaining_limit_cents + committed_cents (PRD §2.9)."""
    assert data["committed_cents"] >= 0, "committed_cents must be non-negative"
    assert data["forward_exposure_cents"] >= 0, "forward_exposure_cents must be non-negative"
    assert data["coverage_limit_cents"] == data["remaining_limit_cents"] + data["committed_cents"], (
        "invariant coverage_limit_cents == remaining_limit_cents + committed_cents violated: "
        f"{data['coverage_limit_cents']} != {data['remaining_limit_cents']} + {data['committed_cents']}"
    )


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SIGNED", "ACTIVE", "RESCINDED", "COMPLETED", "CANCELLED")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "FILED", "NEGOTIATING", "OFFER_RECEIVED",
        "IN_APPRAISAL", "SETTLED", "PAID", "WITHDRAWN",
    )


def assert_supplement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "VOIDED")


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INVOKED", "APPRAISERS_NAMED", "UMPIRE_SELECTED", "AWARDED", "CANCELLED",
    )


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "CLEARED", "REVERSED")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "RELEASED", "HELD", "VOIDED")


def assert_disbursement_waterfall(data: dict):
    """gross = fee + advance_recoup + client (PRD §3.7)."""
    assert data["gross_cents"] == (
        data["fee_cents"] + data["advance_recoup_cents"] + data["client_cents"]
    ), (
        "disbursement waterfall must conserve gross: "
        f"{data['gross_cents']} != {data['fee_cents']} + "
        f"{data['advance_recoup_cents']} + {data['client_cents']}"
    )


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED", "WITHDRAWN")
