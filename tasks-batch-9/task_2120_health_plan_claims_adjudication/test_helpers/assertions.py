"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AuthorizationStatus,
    ClaimLineStatus,
    ClaimPaymentStatus,
    ClaimStatus,
    ClaimType,
    CobMethod,
    CobRole,
    ContractStatus,
    CoverageStatus,
    CoverageTier,
    EditSeverity,
    EditType,
    EventType,
    MemberStatus,
    NetworkStatus,
    PricingMethod,
    PricingVariant,
    RemittanceStatus,
)


def _assert_common_fields(data: dict, label: str) -> None:
    """id / created_at / updated_at / version, carried by every resource but the event log."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_benefit_plan(data: dict) -> None:
    _assert_common_fields(data, "BenefitPlan")
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["plan_year_start_date"], str)
    assert isinstance(data["deductible_individual_cents"], int)
    assert data["deductible_individual_cents"] >= 0
    assert isinstance(data["oop_max_individual_cents"], int)
    assert data["oop_max_individual_cents"] >= 0
    assert 0 <= data["coinsurance_member_pct"] <= 1
    assert isinstance(data["copay_office_visit_cents"], int)
    assert data["copay_office_visit_cents"] >= 0
    assert 0 <= data["out_of_network_penalty_pct"] <= 1
    assert isinstance(data["timely_filing_days"], int) and data["timely_filing_days"] >= 1
    assert data["cob_method"] in _values(CobMethod)


def assert_member(data: dict) -> None:
    _assert_common_fields(data, "Member")
    assert isinstance(data["member_number"], str) and data["member_number"]
    assert is_valid_uuid(data.get("plan_id", "")), "Member.plan_id must be a UUID string"
    assert isinstance(data["first_name"], str)
    assert isinstance(data["last_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in _values(MemberStatus)


def assert_member_coverage(data: dict) -> None:
    _assert_common_fields(data, "MemberCoverage")
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["effective_date"], str)
    assert data["term_date"] is None or isinstance(data["term_date"], str)
    assert data["cob_order"] in ["PRIMARY", "SECONDARY", "TERTIARY"]
    assert data["coverage_tier"] in _values(CoverageTier)
    assert data["status"] in _values(CoverageStatus)


def assert_benefit_accumulator(data: dict) -> None:
    _assert_common_fields(data, "BenefitAccumulator")
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["plan_year"], int)
    for field in ("deductible_applied_cents", "oop_applied_cents", "remitted_claim_count"):
        assert isinstance(data[field], int), f"BenefitAccumulator.{field} must be an integer"
        assert data[field] >= 0, f"BenefitAccumulator.{field} must stay at zero or above"


def assert_provider(data: dict) -> None:
    _assert_common_fields(data, "Provider")
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["network_status"] in _values(NetworkStatus)
    assert isinstance(data["specialty_code"], str)


def assert_provider_contract(data: dict) -> None:
    _assert_common_fields(data, "ProviderContract")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["term_date"], str)
    assert data["pricing_method"] in _values(PricingMethod)
    assert data["status"] in _values(ContractStatus)
    if data["pricing_method"] == PricingMethod.PCT_OF_FEE_SCHEDULE.value:
        assert data["contract_pct"] is not None
        assert 0 < data["contract_pct"] <= 5
    if data["pricing_method"] == PricingMethod.CASE_RATE.value:
        assert data["case_rate_cents"] is not None
        assert data["case_rate_cents"] >= 0


def assert_fee_schedule_rate(data: dict) -> None:
    _assert_common_fields(data, "FeeScheduleRate")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert isinstance(data["allowed_amount_cents"], int)
    assert data["allowed_amount_cents"] >= 0
    assert isinstance(data["effective_date"], str)


def assert_edit_rule(data: dict) -> None:
    _assert_common_fields(data, "EditRule")
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["edit_type"] in _values(EditType)
    assert isinstance(data["primary_code"], str) and data["primary_code"]
    assert data["severity"] in _values(EditSeverity)
    assert isinstance(data["precedence_rank"], int) and data["precedence_rank"] >= 1
    assert isinstance(data["reason_code"], str) and data["reason_code"]


def assert_authorization(data: dict) -> None:
    _assert_common_fields(data, "Authorization")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert isinstance(data["authorized_units"], int) and data["authorized_units"] >= 1
    assert isinstance(data["units_consumed"], int) and data["units_consumed"] >= 0
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in _values(AuthorizationStatus)


def assert_authorization_status_derived(data: dict) -> None:
    """The authorization status is re-derived from units_consumed every time it moves."""
    if data["status"] == AuthorizationStatus.REVOKED.value:
        return
    consumed, granted = data["units_consumed"], data["authorized_units"]
    if consumed == 0:
        expected = AuthorizationStatus.ACTIVE.value
    elif consumed >= granted:
        expected = AuthorizationStatus.EXHAUSTED.value
    else:
        expected = AuthorizationStatus.PARTIALLY_CONSUMED.value
    assert data["status"] == expected, (
        f"Authorization with {consumed}/{granted} units consumed must derive to "
        f"{expected}, got {data['status']}"
    )


def assert_claim(data: dict) -> None:
    _assert_common_fields(data, "Claim")
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["claim_type"] in _values(ClaimType)
    assert data["status"] in _values(ClaimStatus)
    assert data["payment_status"] in _values(ClaimPaymentStatus)
    assert data["cob_role"] in _values(CobRole)
    assert data["pricing_variant"] in _values(PricingVariant)
    assert is_iso8601_timestamp(data.get("received_at", "")), (
        f"Claim.received_at must be an ISO 8601 UTC timestamp, got {data.get('received_at')!r}"
    )
    for field in (
        "total_billed_cents",
        "total_allowed_cents",
        "total_deductible_applied_cents",
        "total_member_liability_cents",
        "total_plan_paid_cents",
    ):
        assert isinstance(data[field], int), f"Claim.{field} must be integer cents"
        assert data[field] >= 0, f"Claim.{field} must not go negative"
    assert isinstance(data["adjudication_pass"], int) and data["adjudication_pass"] >= 0
    assert data["other_payer_paid_cents"] is None or isinstance(
        data["other_payer_paid_cents"], int
    )


def assert_claim_line(data: dict) -> None:
    _assert_common_fields(data, "ClaimLine")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["billed_amount_cents"], int) and data["billed_amount_cents"] >= 0
    assert isinstance(data["service_date"], str)
    assert data["line_status"] in _values(ClaimLineStatus)
    for field in (
        "allowed_amount_cents",
        "deductible_applied_cents",
        "copay_cents",
        "coinsurance_cents",
        "member_liability_cents",
        "plan_paid_cents",
    ):
        assert isinstance(data[field], int), f"ClaimLine.{field} must be integer cents"
        assert data[field] >= 0, f"ClaimLine.{field} must not go negative"


def assert_remittance_advice(data: dict) -> None:
    _assert_common_fields(data, "RemittanceAdvice")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["remit_number"], str) and data["remit_number"].startswith("RA-")
    for field in (
        "total_allowed_cents",
        "total_plan_paid_cents",
        "total_member_liability_cents",
        "total_other_payer_paid_cents",
    ):
        assert isinstance(data[field], int), f"RemittanceAdvice.{field} must be integer cents"
    assert data["status"] in _values(RemittanceStatus)
    assert is_iso8601_timestamp(data.get("issued_at", ""))


def assert_adjudication_event(data: dict) -> None:
    """An adjudication event carries id and created_at and nothing else from the common set."""
    assert is_valid_uuid(data.get("id", "")), "AdjudicationEvent.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["pass_number"], int) and data["pass_number"] >= 0
    assert data["event_type"] in _values(EventType)
    assert isinstance(data["to_status"], str) and data["to_status"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert "version" not in data, "An adjudication event must expose no version field"
    assert "updated_at" not in data, "An adjudication event must expose no updated_at field"


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_line_money_is_zero(line: dict) -> None:
    """Lines that ended BUNDLED, DENIED or PENDED keep every money field at zero."""
    for field in (
        "allowed_amount_cents",
        "deductible_applied_cents",
        "copay_cents",
        "coinsurance_cents",
        "member_liability_cents",
        "plan_paid_cents",
    ):
        assert line[field] == 0, (
            f"line {line['line_number']} at {line['line_status']} must keep "
            f"{field} at 0, got {line[field]}"
        )


def assert_line_cost_share_adds_up(line: dict) -> None:
    """member_liability = copay + deductible + coinsurance, and plan_paid closes the gap."""
    assert line["member_liability_cents"] + line["plan_paid_cents"] == line[
        "allowed_amount_cents"
    ], (
        f"line {line['line_number']}: member_liability_cents + plan_paid_cents must equal "
        f"allowed_amount_cents"
    )


def assert_claim_totals_reconcile(claim: dict, lines: list) -> None:
    """Claim totals are the sums of the per-line values over the pricing lines."""
    pricing = [line for line in lines if line["line_status"] in ("PRICED", "PAID")]
    assert claim["total_allowed_cents"] == sum(
        line["allowed_amount_cents"] for line in pricing
    ), "total_allowed_cents must be the sum of the per-line allowed amounts"
    assert claim["total_deductible_applied_cents"] == sum(
        line["deductible_applied_cents"] for line in pricing
    ), "total_deductible_applied_cents must be the sum of the per-line deductible draws"


def assert_accumulator_conserved(before: dict, after: dict) -> None:
    """A finalize followed by its compensating reversal must leave no drift."""
    for field in ("deductible_applied_cents", "oop_applied_cents", "remitted_claim_count"):
        assert after[field] == before[field], (
            f"BenefitAccumulator.{field} drifted: {before[field]} -> {after[field]}"
        )
