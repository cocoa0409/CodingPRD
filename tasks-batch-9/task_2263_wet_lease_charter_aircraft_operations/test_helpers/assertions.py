"""Entity assertions and domain invariant checkers for the wet lease API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AircraftStatus,
    BillingState,
    CrewMemberStatus,
    CrewQualificationStatus,
    Determination,
    FlightLegStatus,
    InsuranceCertificateStatus,
    LeaseAgreementStatus,
    LesseeStatus,
    ReliabilityReportStatus,
    ReturnConditionStatus,
    SettlementInvoiceStatus,
    SubstitutionStatus,
    UtilizationPeriodStatus,
)


def _assert_common_fields(data: dict, label: str) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _statuses(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_lessee(data: dict) -> None:
    _assert_common_fields(data, "Lessee")
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["icao_code"]) == 3 and data["icao_code"].isupper()
    assert len(data["home_base_icao"]) == 4 and data["home_base_icao"].isupper()
    assert isinstance(data["credit_limit_usd_cents"], int)
    assert data["credit_limit_usd_cents"] >= 0
    assert isinstance(data["outstanding_balance_usd_cents"], int)
    assert data["status"] in _statuses(LesseeStatus), f"unexpected status {data['status']}"


def assert_aircraft(data: dict) -> None:
    _assert_common_fields(data, "Aircraft")
    assert 5 <= len(data["tail_number"]) <= 7
    assert isinstance(data["type_designator"], str) and data["type_designator"]
    assert isinstance(data["type_family"], str) and data["type_family"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["mtow_kg"], int) and data["mtow_kg"] >= 1
    assert isinstance(data["maintenance_program_ref"], str)
    assert float(data["airframe_hours_total"]) >= 0
    assert float(data["hours_since_last_check"]) >= 0
    assert isinstance(data["cycles_since_last_check"], int)
    assert data["cycles_since_last_check"] >= 0
    assert data["status"] in _statuses(AircraftStatus), f"unexpected status {data['status']}"


def assert_crew_member(data: dict) -> None:
    _assert_common_fields(data, "CrewMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_no"], str) and data["employee_no"]
    assert data["crew_role"] in ["CAPTAIN", "FIRST_OFFICER", "CABIN"]
    assert isinstance(data["type_ratings"], list) and len(data["type_ratings"]) >= 1
    assert isinstance(data["rolling_duty_minutes_7d"], int)
    assert isinstance(data["rolling_block_minutes_28d"], int)
    assert data["status"] in _statuses(CrewMemberStatus)


def assert_lease_agreement(data: dict) -> None:
    _assert_common_fields(data, "LeaseAgreement")
    assert is_valid_uuid(data["lessee_id"])
    assert is_valid_uuid(data["primary_aircraft_id"])
    assert len(data["term_start_date"]) == 10
    assert len(data["term_end_date"]) == 10
    assert data["term_end_date"] >= data["term_start_date"]
    assert isinstance(data["block_hour_rate_usd_cents"], int)
    assert data["block_hour_rate_usd_cents"] >= 1
    assert float(data["min_guaranteed_block_hours_per_month"]) > 0
    assert 0 <= float(data["shortfall_credit_pct"]) <= 1
    for field in (
        "crew_provided_by",
        "maintenance_provided_by",
        "insurance_provided_by",
        "operational_control",
    ):
        assert data[field] in ["LESSOR", "LESSEE"], f"unexpected {field}={data[field]}"
    assert data["substitution_rights"] in [
        "LESSOR_UNILATERAL",
        "LESSEE_CONSENT_REQUIRED",
    ]
    assert data["reliability_basis"] in ["DEPARTURE", "SCHEDULED"]
    assert len(data["redelivery_icao"]) == 4
    assert data["status"] in _statuses(LeaseAgreementStatus)
    if data.get("suspension_reason") is not None:
        assert data["suspension_reason"] in [
            "INSURANCE_LAPSED",
            "REGULATORY_APPROVAL_REVOKED",
            "AIRFRAME_AOG",
        ]


def assert_regulatory_approval(data: dict) -> None:
    _assert_common_fields(data, "RegulatoryApproval")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["authority_docket_no"], str) and data["authority_docket_no"]
    assert data["determination"] in _statuses(Determination)
    assert isinstance(data["conditions"], list)
    assert isinstance(data["open_condition_codes"], list)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_insurance_certificate(data: dict) -> None:
    _assert_common_fields(data, "InsuranceCertificate")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["certificate_no"], str) and data["certificate_no"]
    assert isinstance(data["hull_limit_usd_cents"], int)
    assert isinstance(data["liability_limit_usd_cents"], int)
    assert isinstance(data["breach_of_warranty_endorsed"], bool)
    assert isinstance(data["additional_insured_lessee"], bool)
    assert data["status"] in _statuses(InsuranceCertificateStatus)


def assert_crew_qualification(data: dict) -> None:
    _assert_common_fields(data, "CrewQualification")
    assert is_valid_uuid(data["crew_member_id"])
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in _statuses(CrewQualificationStatus)


def assert_flight_leg(data: dict) -> None:
    _assert_common_fields(data, "FlightLeg")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert is_valid_uuid(data["captain_id"])
    assert is_valid_uuid(data["first_officer_id"])
    assert len(data["origin_icao"]) == 4
    assert len(data["dest_icao"]) == 4
    assert data["leg_class"] in ["REVENUE", "REPOSITIONING", "MAINTENANCE_FERRY"]
    assert isinstance(data["scheduled_block_minutes"], int)
    assert isinstance(data["block_minutes"], int)
    assert isinstance(data["billable_block_minutes"], int)
    assert data["status"] in _statuses(FlightLegStatus)
    assert data["billing_state"] in _statuses(BillingState)


def assert_aircraft_substitution(data: dict) -> None:
    _assert_common_fields(data, "AircraftSubstitution")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["original_aircraft_id"])
    assert data["reason"] in ["AOG", "SCHEDULED_MAINTENANCE", "IRREGULAR_OPS"]
    assert isinstance(data["seat_delta"], int)
    assert isinstance(data["repointed_leg_count"], int)
    assert data["status"] in _statuses(SubstitutionStatus)
    if data.get("selection_basis") is not None:
        assert data["selection_basis"] in ["CLIENT_SPECIFIED", "SERVER_SELECTED"]


def assert_utilization_period(data: dict) -> None:
    _assert_common_fields(data, "UtilizationPeriod")
    assert is_valid_uuid(data["lease_id"])
    assert len(data["period_month"]) == 7 and data["period_month"][4] == "-"
    for cents_field in (
        "base_charge_cents",
        "shortfall_credit_cents",
        "overrun_charge_cents",
        "gross_charge_cents",
        "reliability_penalty_cents",
        "provisional_charge_cents",
        "final_charge_cents",
    ):
        assert isinstance(
            data[cents_field], int
        ), f"{cents_field} must be an integer count of cents"
    assert isinstance(data["credited_block_minutes"], int)
    assert data["variant_applied"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in _statuses(UtilizationPeriodStatus)


def assert_settlement_invoice(data: dict) -> None:
    _assert_common_fields(data, "SettlementInvoice")
    assert is_valid_uuid(data["period_id"])
    assert is_valid_uuid(data["lease_id"])
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["line_items"], list)
    assert data["status"] in _statuses(SettlementInvoiceStatus)


def assert_reliability_report(data: dict) -> None:
    _assert_common_fields(data, "ReliabilityReport")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert len(data["period_month"]) == 7
    for counter in (
        "revenue_departures",
        "scheduled_revenue_legs",
        "technical_delay_events",
        "technical_cancellations",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["status"] in _statuses(ReliabilityReportStatus)


def assert_return_condition(data: dict) -> None:
    _assert_common_fields(data, "ReturnCondition")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert isinstance(data["discrepancy_codes"], list)
    assert isinstance(data["discrepancy_cost_cents"], int)
    assert isinstance(data["billed_to_lessee_cents"], int)
    assert data["status"] in _statuses(ReturnConditionStatus)


# --------------------------------------------------------------------------- #
# Domain invariants — the conserved quantities the PRD states must always hold #
# --------------------------------------------------------------------------- #


def assert_hours_precision(value, label: str = "hours") -> None:
    """Hour-denominated quantities are carried to four decimal places."""
    quantised = round(float(value) + 1e-12, 4)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must be carried to four decimal places, got {value!r}"
    )


def assert_percentage_precision(value, label: str = "percentage") -> None:
    """Reliability percentages are carried to two decimal places."""
    quantised = round(float(value) + 1e-12, 2)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must be carried to two decimal places, got {value!r}"
    )


def assert_deposit_conservation(lease: dict) -> None:
    """The deposit applied plus the deposit remaining always equals the deposit seeded."""
    total = lease["return_deposit_applied_cents"] + lease["return_deposit_remaining_cents"]
    assert total == lease["return_deposit_cents"], (
        "return_deposit_applied_cents + return_deposit_remaining_cents must equal "
        f"return_deposit_cents, got {total} vs {lease['return_deposit_cents']}"
    )
    assert lease["return_deposit_applied_cents"] >= 0
    assert lease["return_deposit_remaining_cents"] >= 0


def assert_gross_charge_composition(period: dict) -> None:
    """gross_charge_cents is the base charge less the shortfall credit plus overrun."""
    expected = (
        period["base_charge_cents"]
        - period["shortfall_credit_cents"]
        + period["overrun_charge_cents"]
    )
    assert period["gross_charge_cents"] == expected, (
        "gross_charge_cents must equal base_charge_cents - shortfall_credit_cents + "
        f"overrun_charge_cents, got {period['gross_charge_cents']} vs {expected}"
    )
