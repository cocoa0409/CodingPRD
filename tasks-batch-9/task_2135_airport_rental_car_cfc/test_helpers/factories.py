"""Payload factories — one per creatable resource, input fields only."""

from .constants import TEST_DEFAULTS


def facility_payload(**overrides) -> dict:
    payload = {
        "code": "DEN",
        "name": "DEN ConRAC",
        "cfc_rate_per_transaction_day_cents": TEST_DEFAULTS[
            "CFC_RATE_PER_TRANSACTION_DAY_CENTS"
        ],
        "ds_reserve_requirement_cents": TEST_DEFAULTS["DS_RESERVE_REQUIREMENT_CENTS"],
        "om_reserve_requirement_cents": TEST_DEFAULTS["OM_RESERVE_REQUIREMENT_CENTS"],
        "capital_fund_cap_cents": TEST_DEFAULTS["CAPITAL_FUND_CAP_CENTS"],
        "overflow_lot_stalls": TEST_DEFAULTS["OVERFLOW_LOT_STALLS"],
        "overflow_daily_surcharge_cents": TEST_DEFAULTS["OVERFLOW_DAILY_SURCHARGE_CENTS"],
        "remittance_grace_days": 20,
    }
    payload.update(overrides)
    return payload


def concessionaire_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "legal_name": "Avex Rent A Car",
        "brand_code": "AVX",
        "contact_email": "ops@avex.example",
    }
    payload.update(overrides)
    return payload


def agreement_payload(facility_id: str, concessionaire_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "concessionaire_id": concessionaire_id,
        "contract_year_index": 1,
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "mag_annual_cents": TEST_DEFAULTS["MAG_ANNUAL_CENTS"],
        "percentage_rent_rate_bps": TEST_DEFAULTS["PERCENTAGE_RENT_RATE_BPS"],
        "rent_settlement_basis": "CUMULATIVE_YTD",
    }
    payload.update(overrides)
    return payload


def counter_space_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "terminal_code": "T1",
        "space_label": "T1-A02",
        "space_class": "COUNTER",
    }
    payload.update(overrides)
    return payload


def counter_assignment_payload(
    agreement_id: str,
    counter_space_id: str,
    expected_agreement_version: int,
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "counter_space_id": counter_space_id,
        "effective_start_date": "2026-02-01",
        "effective_end_date": "2026-05-01",
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def fleet_zone_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "zone_label": "Z1",
        "stall_capacity": 100,
    }
    payload.update(overrides)
    return payload


def fleet_allocation_payload(
    agreement_id: str, zone_id: str, expected_zone_version: int, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "zone_id": zone_id,
        "start_date": "2026-03-01",
        "end_date": "2026-03-10",
        "stalls_requested": 10,
        "allow_overflow": False,
        "expected_zone_version": expected_zone_version,
    }
    payload.update(overrides)
    return payload


def report_payload(agreement_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "period_year": 2026,
        "period_month": 1,
        "reported_gross_revenue_cents": 5_000_000,
        "reported_on_airport_transaction_days": 4_000,
    }
    payload.update(overrides)
    return payload


def accept_report_payload(**overrides) -> dict:
    payload = {
        "audited_gross_revenue_cents": 5_000_000,
        "audited_on_airport_transaction_days": 4_000,
    }
    payload.update(overrides)
    return payload


def reject_report_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Understated on-airport transaction days"}
    payload.update(overrides)
    return payload


def remittance_payload(agreement_id: str, report_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "report_id": report_id,
        "remittance_basis": "FINAL",
    }
    payload.update(overrides)
    return payload


def receive_payload(amount_received_cents: int) -> dict:
    return {"amount_received_cents": amount_received_cents}


def obligation_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "series_label": "Series 2026A",
        "due_date": "2026-12-01",
        "amount_due_cents": 4_000_000,
        "coverage_requirement_bps": 12_500,
    }
    payload.update(overrides)
    return payload


def shuttle_period_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "period_year": 2026,
        "period_month": 1,
        "total_cost_cents": 1_000_000,
        "allocation_basis": "TRANSACTION_DAYS",
    }
    payload.update(overrides)
    return payload


def project_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "project_name": "Ready-return deck resurfacing",
        "budget_cents": 2_000_000,
    }
    payload.update(overrides)
    return payload


def disbursement_payload(
    project_id: str, amount_cents: int, expected_project_version: int, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "amount_cents": amount_cents,
        "memo": "Mobilisation",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def settlement_payload(agreement_id: str, **overrides) -> dict:
    payload = {"agreement_id": agreement_id, "contract_year_index": 1}
    payload.update(overrides)
    return payload


def settle_payload(amount_paid_cents: int) -> dict:
    return {"amount_paid_cents": amount_paid_cents}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
