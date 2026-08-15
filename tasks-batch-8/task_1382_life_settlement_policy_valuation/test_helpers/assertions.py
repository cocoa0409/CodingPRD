"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
        )


def assert_broker(data: dict):
    _assert_common(data, "Broker")
    assert data["status"] == "ACTIVE"
    for f in ("name", "license_number", "state_code"):
        assert isinstance(data[f], str) and data[f]


def assert_investor(data: dict):
    _assert_common(data, "Investor")
    assert data["status"] == "ACTIVE"
    assert data["investor_type"] in ("INDIVIDUAL", "FUND")


def assert_insured(data: dict):
    _assert_common(data, "Insured")
    assert data["status"] in ("LIVING", "DECEASED")
    assert data["gender"] in ("M", "F")
    assert data["smoker_status"] in ("TOBACCO", "NON_TOBACCO", "UNKNOWN")
    assert isinstance(data["age_years"], int)


def assert_state_license(data: dict):
    _assert_common(data, "StateLicense")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    for f in ("state_code", "license_number", "effective_date", "expiry_date"):
        assert isinstance(data[f], str) and data[f]


def assert_policy(data: dict):
    _assert_common(data, "Policy")
    assert data["status"] in ("IN_FORCE", "LAPSED", "MATURED")
    assert data["policy_type"] in (
        "WHOLE_LIFE", "UNIVERSAL_LIFE", "VARIABLE", "TERM_CONVERTIBLE", "TERM_NONCONVERTIBLE"
    )
    assert isinstance(data["face_amount_cents"], int)
    assert isinstance(data["annual_premium_cents"], int)
    assert isinstance(data["in_contestability"], bool)


def assert_policy_case(data: dict):
    _assert_common(data, "PolicyCase")
    assert data["status"] in (
        "DRAFT", "SCREENING", "SCREEN_FAILED", "UNDERWRITING", "UW_DECLINED", "MARKETED",
        "IN_CLOSING", "ACQUIRED", "RESCINDED", "WITHDRAWN", "EXPIRED", "MATURED", "LAPSED",
    )
    assert data["hold_status"] in ("CLEAR", "COMPLIANCE_HOLD")
    assert isinstance(data["screening_failure_reasons"], list)
    assert isinstance(data["disclosures_delivered"], bool)


def assert_eligibility_screening(data: dict):
    # Immutable record entity: id + created_at only, no updated_at / version (PRD §2.4)
    _assert_common(data, "EligibilityScreening", with_version=False)
    assert data["result"] in ("PASSED", "FAILED")
    checks = data["checks"]
    for k in ("license_ok", "face_ok", "age_ok", "contestability_ok", "type_ok"):
        assert isinstance(checks[k], bool), f"checks.{k} must be boolean"
    assert isinstance(data["failure_reasons"], list)


def assert_le_report(data: dict):
    _assert_common(data, "LifeExpectancyReport")
    assert data["status"] in ("ORDERED", "DELIVERED", "SUPERSEDED", "EXPIRED")
    assert data["underwriter_tier"] in ("A", "B")


def assert_offer(data: dict):
    _assert_common(data, "Offer")
    assert data["status"] in ("PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["round_number"], int)


def assert_closing_package(data: dict):
    _assert_common(data, "ClosingPackage")
    assert data["status"] in (
        "ASSEMBLED", "OUT_FOR_SIGNATURE", "COMPLIANCE_REVIEW", "APPROVED",
        "CARRIER_SUBMITTED", "OWNERSHIP_CONFIRMED", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["documents"], list)
    for row in data["documents"]:
        assert isinstance(row["doc_type"], str)
        assert isinstance(row["signed"], bool)


def assert_escrow_account(data: dict):
    _assert_common(data, "EscrowAccount")
    assert data["status"] in ("OPEN", "FUNDED", "RELEASED", "REVERSED", "CLOSED")
    assert isinstance(data["expected_funding_cents"], int)
    assert isinstance(data["balance_cents"], int)


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert data["bucket"] in ("ESCROW_FEE", "SERVICING_FEE", "BROKER_COMMISSION", "SELLER_NET")
    assert data["status"] in ("PENDING", "SETTLED")
    assert isinstance(data["amount_cents"], int)


def assert_premium_schedule(data: dict):
    _assert_common(data, "PremiumSchedule")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "TERMINATED")
    assert data["strategy"] in ("PAY_AS_DUE", "REDUCED_PAID_UP", "MINIMUM_FUNDING")
    assert isinstance(data["optimized_monthly_premium_cents"], int)
    assert isinstance(data["planned_months"], int)


def assert_premium_payment(data: dict):
    _assert_common(data, "PremiumPayment")
    assert data["status"] in ("SCHEDULED", "PAID", "MISSED")
    assert isinstance(data["amount_cents"], int)


def assert_tracking_event(data: dict):
    _assert_common(data, "TrackingEvent")
    assert data["status"] in ("RECORDED", "VERIFIED", "REJECTED")
    assert data["event_type"] in ("WELLNESS_CALL", "OBIT_SEARCH", "DMF_MATCH", "FAMILY_REPORT", "MEDICAL_RECORDS")
    assert data["outcome"] in ("ALIVE_CONFIRMED", "DEATH_INDICATED", "UNREACHABLE")
    assert data["source_channel"] in ("CALL", "OBIT", "DMF", "MEDICAL", "FAMILY")


def assert_death_claim(data: dict):
    _assert_common(data, "DeathClaim")
    assert data["status"] in ("REPORTED", "VERIFIED", "FILED", "CONTESTED", "PAID", "DENIED")
    assert isinstance(data["verification_source_count"], int)
    assert isinstance(data["certificate_received"], bool)


def assert_portfolio(data: dict):
    _assert_common(data, "Portfolio")
    assert data["valuation_method"] in ("PROSPECTIVE", "INVESTMENT")
    assert isinstance(data["allocations"], list)
    assert isinstance(data["holding_count"], int)
    assert isinstance(data["invested_capital_cents"], int)
    assert isinstance(data["nav_stale"], bool)


def assert_valuation_snapshot(data: dict):
    _assert_common(data, "ValuationSnapshot")
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    assert data["method_used"] in ("PROSPECTIVE", "INVESTMENT")
    assert isinstance(data["nav_cents"], int)
    assert isinstance(data["policy_valuations"], list)


def assert_escrow_cash_invariant(funded_amount_cents: int, settled_total: int,
                                 balance_cents: int, refund_cents: int):
    """Escrow cash conservation: funded == settled + balance + refund (PRD §3.5)."""
    assert funded_amount_cents == settled_total + balance_cents + refund_cents, (
        f"escrow cash not conserved: funded {funded_amount_cents} != settled {settled_total} "
        f"+ balance {balance_cents} + refund {refund_cents}"
    )
