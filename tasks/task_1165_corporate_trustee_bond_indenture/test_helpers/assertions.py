"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_ISO8601_MS_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_iso8601_ms_utc(value: str, field: str = "timestamp"):
    """PRD §2.2/§2.4: ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and _ISO8601_MS_UTC.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def assert_indenture(data: dict):
    _assert_common_fields(data, "Indenture")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["issuer_ref"], str) and data["issuer_ref"]
    assert isinstance(data["governing_law"], str)
    assert isinstance(data["initial_trustee_ref"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "DEFAULTED", "ACCELERATED", "SATISFIED"]
    assert isinstance(data["annual_admin_fee_cents"], int)
    assert isinstance(data["extraordinary_hourly_rate_cents"], int)
    assert isinstance(data["default_hourly_rate_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int) and data["outstanding_principal_cents"] >= 0
    assert data["covenant_posture"] in ["CURRENT", "GRACE", "BREACH"]
    assert isinstance(data["active_default_count"], int) and data["active_default_count"] >= 0


def assert_tranche(data: dict):
    _assert_common_fields(data, "Tranche")
    assert isinstance(data["indenture_id"], str)
    assert isinstance(data["series_code"], str) and data["series_code"]
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int) and data["outstanding_principal_cents"] >= 0
    assert isinstance(data["interest_rate_bps"], int)
    assert data["day_count_convention"] in ["ACT_360", "ACT_365", "THIRTY_360"]
    assert data["payment_frequency"] in ["QUARTERLY", "SEMI_ANNUAL", "ANNUAL"]
    assert isinstance(data["maturity_date"], str)
    assert isinstance(data["notice_period_days"], int)
    assert data["status"] in ["ACTIVE", "REDEEMED", "MATURED", "ACCELERATED"]


def assert_noteholder_account(data: dict):
    _assert_common_fields(data, "NoteholderAccount")
    assert isinstance(data["holder_ref"], str) and data["holder_ref"]
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["contact_email"], str)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["total_unpaid_cents"], int) and data["total_unpaid_cents"] >= 0
    assert isinstance(data["total_received_cents"], int) and data["total_received_cents"] >= 0


def assert_position(data: dict):
    _assert_common_fields(data, "Position")
    assert isinstance(data["tranche_id"], str)
    assert isinstance(data["noteholder_account_id"], str)
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["principal_amount_cents"], int) and data["principal_amount_cents"] >= 0
    assert isinstance(data["principal_history"], list) and len(data["principal_history"]) >= 1
    for entry in data["principal_history"]:
        assert "effective_from" in entry and "principal_cents" in entry
        assert isinstance(entry["principal_cents"], int)
    assert data["status"] in ["ACTIVE", "REDEEMED"]


def assert_covenant_obligation(data: dict):
    _assert_common_fields(data, "CovenantObligation")
    assert isinstance(data["indenture_id"], str)
    assert data["covenant_type"] in [
        "FINANCIAL_REPORT", "INSURANCE_CERT", "DEBT_SERVICE_COVERAGE",
        "LEVERAGE_RATIO", "TAX_COMPLIANCE",
    ]
    assert data["frequency"] in ["QUARTERLY", "SEMI_ANNUAL", "ANNUAL"]
    assert isinstance(data["period_anchor_date"], str)
    assert isinstance(data["next_due_date"], str)
    assert isinstance(data["grace_period_days"], int)
    assert data["status"] in ["OPEN", "LATE", "BREACHED", "WAIVED"]


def assert_covenant_certificate(data: dict):
    _assert_common_fields(data, "CovenantCertificate")
    assert isinstance(data["covenant_obligation_id"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["document_ref"], str)
    assert isinstance(data["submitted_at"], str)
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_payment_run(data: dict):
    _assert_common_fields(data, "PaymentRun")
    assert isinstance(data["tranche_id"], str)
    assert data["payment_type"] in [
        "INTEREST", "SINKING_FUND_REDEMPTION", "FULL_REDEMPTION", "FINAL_MATURITY",
    ]
    assert isinstance(data["scheduled_payment_date"], str)
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 0
    assert isinstance(data["funded_amount_cents"], int) and data["funded_amount_cents"] >= 0
    assert data["funding_status"] in ["UNFUNDED", "PARTIALLY_FUNDED", "FUNDED"]
    assert data["distribution_status"] in ["SCHEDULED", "DISTRIBUTED", "SUSPENDED", "REVERSED"]


def assert_distribution_record(data: dict):
    _assert_common_fields(data, "DistributionRecord")
    assert isinstance(data["payment_run_id"], str)
    assert isinstance(data["position_id"], str)
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert data["status"] in ["PENDING", "PAID", "HELD", "RETURNED"]


def assert_default_case(data: dict):
    _assert_common_fields(data, "DefaultCase")
    assert isinstance(data["indenture_id"], str)
    assert data["default_type"] in [
        "PAYMENT", "COVENANT_BREACH", "CROSS_DEFAULT", "BANKRUPTCY", "SINKING_FUND_MISS",
    ]
    assert isinstance(data["declared_at"], str)
    assert isinstance(data["cure_deadline"], str)
    assert data["status"] in ["ALLEGED", "CONFIRMED", "CURED", "WAIVED", "ACCELERATED"]
    assert isinstance(data["declared_by_user_id"], str)


def assert_noteholder_direction(data: dict):
    _assert_common_fields(data, "NoteholderDirection")
    assert isinstance(data["default_case_id"], str)
    assert data["instruction_type"] in ["ACCELERATE", "RESCIND_ACCELERATION", "WAIVE_DEFAULT"]
    assert isinstance(data["expires_at"], str)
    assert isinstance(data["eligible_principal_cents"], int) and data["eligible_principal_cents"] >= 0
    assert isinstance(data["supporting_principal_cents"], int) and data["supporting_principal_cents"] >= 0
    assert data["status"] in ["CIRCULATING", "EFFECTIVE", "EXECUTED", "SUPERSEDED", "LAPSED"]


def assert_direction_endorsement(data: dict):
    _assert_common_fields(data, "DirectionEndorsement")
    assert isinstance(data["direction_id"], str)
    assert isinstance(data["noteholder_account_id"], str)
    assert isinstance(data["endorsed_principal_cents"], int) and data["endorsed_principal_cents"] >= 0
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_consent_solicitation(data: dict):
    _assert_common_fields(data, "ConsentSolicitation")
    assert isinstance(data["indenture_id"], str)
    assert data["subject_type"] in ["AMEND_TERMS", "WAIVE_COVENANT"]
    assert isinstance(data["consent_threshold_bps"], int)
    assert data["tabulation_basis"] in ["RECORD_DATE", "CURRENT_OUTSTANDING"]
    assert isinstance(data["record_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert isinstance(data["ballots"], list)
    for ballot in data["ballots"]:
        assert isinstance(ballot["noteholder_account_id"], str)
        assert ballot["vote"] in ["CONSENT", "WITHHOLD"]
        assert isinstance(ballot["principal_voted_cents"], int)
        assert isinstance(ballot["cast_at"], str)
    assert isinstance(data["consenting_principal_cents"], int) and data["consenting_principal_cents"] >= 0
    assert data["status"] in ["DRAFT", "OPEN", "PASSED", "FAILED", "EXPIRED", "REVOKED"]


def assert_collateral_item(data: dict):
    _assert_common_fields(data, "CollateralItem")
    assert isinstance(data["indenture_id"], str)
    assert isinstance(data["description"], str)
    assert data["collateral_type"] in ["REAL_ESTATE", "EQUIPMENT", "SECURITIES", "GUARANTEE"]
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["valuation_date"], str)
    assert data["status"] in ["PLEDGED", "RELEASED", "SUBSTITUTED"]


def assert_collateral_release_request(data: dict):
    _assert_common_fields(data, "CollateralReleaseRequest")
    assert isinstance(data["collateral_item_id"], str)
    assert data["request_type"] in ["RELEASE", "SUBSTITUTION"]
    assert data["status"] in ["SUBMITTED", "VERIFIED", "APPROVED", "REJECTED", "EFFECTED", "SUPERSEDED"]


def assert_fee_invoice(data: dict):
    _assert_common_fields(data, "FeeInvoice")
    assert isinstance(data["indenture_id"], str)
    assert data["invoice_type"] in ["ANNUAL_ADMIN", "EXTRAORDINARY_SERVICE"]
    assert isinstance(data["service_period_start"], str)
    assert isinstance(data["service_period_end"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "DISPUTED", "AMENDED", "VOID"]
    assert isinstance(data["drafted_by_user_id"], str)


def assert_trustee_appointment(data: dict):
    _assert_common_fields(data, "TrusteeAppointment")
    assert isinstance(data["indenture_id"], str)
    assert isinstance(data["outgoing_trustee_ref"], str)
    assert isinstance(data["incoming_trustee_ref"], str) and data["incoming_trustee_ref"]
    assert data["reason"] in ["RESIGNATION", "REMOVAL", "CONSOLIDATION"]
    assert isinstance(data["proposed_effective_date"], str)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "EFFECTIVE", "RESCINDED", "SUPERSEDED"]


def assert_principal_conservation(tranche: dict, positions: list, indenture: dict):
    """Principal conservation rule (PRD §3.2): tranche outstanding equals the
    sum of principal_amount_cents over ACTIVE positions, and the indenture
    outstanding equals the sum of its tranches' outstanding principal."""
    active_sum = sum(p["principal_amount_cents"] for p in positions if p["status"] == "ACTIVE")
    assert tranche["outstanding_principal_cents"] == active_sum, (
        f"Tranche outstanding {tranche['outstanding_principal_cents']} != "
        f"sum of ACTIVE position principal {active_sum}"
    )
    assert indenture["outstanding_principal_cents"] == tranche["outstanding_principal_cents"], (
        f"Indenture outstanding {indenture['outstanding_principal_cents']} != "
        f"tranche outstanding {tranche['outstanding_principal_cents']} (single-tranche indenture)"
    )
