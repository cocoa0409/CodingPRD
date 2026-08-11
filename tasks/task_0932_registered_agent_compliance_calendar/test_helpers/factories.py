"""Payload factories.

The jurisdiction-rule payloads below are reproduced exactly as the test designs
state them; tests pass them through unmodified so that every derived date and
every derived money figure can be re-derived by hand from the PRD formulas.
"""
import copy


def _copy(payload: dict, **overrides) -> dict:
    out = copy.deepcopy(payload)
    out.update(overrides)
    return out


# --- Jurisdiction rules ------------------------------------------------------

DE_SHARE_TIERS = [
    {"up_to_shares": 5000, "tax_cents": 17500},
    {"up_to_shares": 10000, "tax_cents": 25000},
    {"up_to_shares": None, "tax_cents": 40000},
]

TX_RECEIPTS_BRACKETS = [
    {"up_to_cents": 123000000, "tax_cents": 0},
    {"up_to_cents": 2000000000, "tax_cents": 37500},
    {"up_to_cents": None, "tax_cents": 95000},
]

#: The full Delaware rule used across the depth scenarios.
DE_RULE_FULL = {
    "state_code": "DE",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 3,
    "fixed_due_day": 1,
    "franchise_tax_basis": "AUTHORIZED_SHARES_TIERS",
    "authorized_shares_tiers": DE_SHARE_TIERS,
    "grace_days": 30,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 20000,
    "delinquency_to_dissolution_days": 90,
    "reinstatement_window_days": 365,
    "annual_report_fee_cents": 5000,
    "franchise_tax_filing_fee_cents": 5000,
    "foreign_qualification_fee_cents": 25000,
    "withdrawal_fee_cents": 4900,
    "dissolution_fee_cents": 4900,
    "reinstatement_fee_cents": 16900,
    "expedite_surcharge_cents": 10000,
    "good_standing_freshness_days": 30,
    "requires_tax_clearance": False,
}

NY_RULE_FULL = {
    "state_code": "NY",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "ASSUMED_PAR_VALUE",
    "assumed_par_value_rate_bps": 35,
    "min_franchise_tax_cents": 17500,
    "max_franchise_tax_cents": 2000000,
    "grace_days": 15,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PERCENT_CAPPED",
    "late_fee_percent_bps": 1000,
    "late_fee_cap_cents": 30000,
    "delinquency_to_dissolution_days": 60,
    "reinstatement_window_days": 180,
    "annual_report_fee_cents": 900,
    "franchise_tax_filing_fee_cents": 900,
    "foreign_qualification_fee_cents": 7000,
    "withdrawal_fee_cents": 3000,
    "dissolution_fee_cents": 3000,
    "reinstatement_fee_cents": 25000,
    "expedite_surcharge_cents": 35000,
    "good_standing_freshness_days": 30,
    "requires_tax_clearance": False,
}

TX_RULE_FULL = {
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FISCAL_YEAR_END_OFFSET",
    "fiscal_offset_days": 135,
    "franchise_tax_basis": "GROSS_RECEIPTS_BRACKETS",
    "gross_receipts_brackets": TX_RECEIPTS_BRACKETS,
    "grace_days": 45,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PERCENT_CAPPED",
    "late_fee_percent_bps": 500,
    "late_fee_cap_cents": 5000,
    "delinquency_to_dissolution_days": 120,
    "reinstatement_window_days": 730,
    "annual_report_fee_cents": 0,
    "franchise_tax_filing_fee_cents": 0,
    "foreign_qualification_fee_cents": 75000,
    "withdrawal_fee_cents": 1500,
    "dissolution_fee_cents": 4000,
    "reinstatement_fee_cents": 12500,
    "expedite_surcharge_cents": 2500,
    "good_standing_freshness_days": 30,
    "requires_tax_clearance": False,
}

#: Minimal Delaware rule: everything not named takes its stated server-side default.
DE_RULE_MIN = {
    "state_code": "DE",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 3,
    "fixed_due_day": 1,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "annual_report_fee_cents": 5000,
}

#: Minimal Delaware rule plus a 30 calendar-day grace and a flat 20000 late fee.
DE_RULE_MIN_LATE = _copy(
    DE_RULE_MIN,
    grace_days=30,
    grace_basis="CALENDAR_DAYS",
    late_fee_style="FLAT",
    late_fee_flat_cents=20000,
)

DE_RULE_MIN_DISSOLUTION = _copy(DE_RULE_MIN, dissolution_fee_cents=4900)

DE_RULE_EXPEDITE = _copy(
    DE_RULE_MIN, dissolution_fee_cents=4900, expedite_surcharge_cents=10000
)

DE_RULE_FINAL_REPORT = _copy(
    DE_RULE_MIN, dissolution_fee_cents=0, requires_tax_clearance=False
)

DE_RULE_OPS = _copy(
    DE_RULE_MIN,
    franchise_tax_filing_fee_cents=5000,
    grace_days=30,
    grace_basis="CALENDAR_DAYS",
    late_fee_style="FLAT",
    late_fee_flat_cents=20000,
)

DE_RULE_WINDOW_LAPSE = _copy(
    DE_RULE_MIN,
    grace_days=30,
    grace_basis="CALENDAR_DAYS",
    late_fee_style="FLAT",
    late_fee_flat_cents=20000,
    delinquency_to_dissolution_days=60,
    reinstatement_window_days=365,
)

DE_RULE_REINSTATEMENT_V1 = _copy(DE_RULE_WINDOW_LAPSE, reinstatement_fee_cents=16900)

DE_RULE_REINSTATEMENT_V2 = {
    "state_code": "DE",
    "effective_from": "2027-07-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 3,
    "fixed_due_day": 1,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "annual_report_fee_cents": 12000,
    "grace_days": 30,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 50000,
    "delinquency_to_dissolution_days": 60,
    "reinstatement_window_days": 365,
    "reinstatement_fee_cents": 40000,
}

#: Delaware share-tier rule used by the tier-boundary scenario.
DE_RULE_TIERS = {
    "state_code": "DE",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 3,
    "fixed_due_day": 1,
    "franchise_tax_basis": "AUTHORIZED_SHARES_TIERS",
    "authorized_shares_tiers": DE_SHARE_TIERS,
    "grace_days": 30,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 20000,
    "annual_report_fee_cents": 5000,
    "franchise_tax_filing_fee_cents": 5000,
}

#: A second Delaware version whose effective_from is strictly later.
DE_RULE_V2_JULY = {
    "state_code": "DE",
    "effective_from": "2026-07-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 4,
    "fixed_due_day": 15,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 60000,
    "grace_days": 5,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 50000,
    "delinquency_to_dissolution_days": 90,
    "reinstatement_window_days": 365,
    "annual_report_fee_cents": 12000,
    "franchise_tax_filing_fee_cents": 12000,
    "foreign_qualification_fee_cents": 25000,
    "withdrawal_fee_cents": 4900,
    "dissolution_fee_cents": 4900,
    "reinstatement_fee_cents": 16900,
    "expedite_surcharge_cents": 10000,
    "good_standing_freshness_days": 30,
    "requires_tax_clearance": False,
}

#: A colliding republication carrying the incumbent's own effective_from.
DE_RULE_SAME_DAY_COLLISION = {
    "state_code": "DE",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 4,
    "fixed_due_day": 15,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 60000,
    "grace_days": 5,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 50000,
    "annual_report_fee_cents": 12000,
    "franchise_tax_filing_fee_cents": 12000,
}

TX_RULE_MIN = {
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FISCAL_YEAR_END_OFFSET",
    "fiscal_offset_days": 135,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "good_standing_freshness_days": 30,
}

TX_RULE_MIN_QUALIFICATION = _copy(TX_RULE_MIN, foreign_qualification_fee_cents=75000)

TX_RULE_FISCAL_REBUILD = {
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FISCAL_YEAR_END_OFFSET",
    "fiscal_offset_days": 135,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "grace_days": 45,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 0,
    "annual_report_fee_cents": 0,
}

TX_RULE_RECEIPTS = {
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FISCAL_YEAR_END_OFFSET",
    "fiscal_offset_days": 135,
    "franchise_tax_basis": "GROSS_RECEIPTS_BRACKETS",
    "gross_receipts_brackets": TX_RECEIPTS_BRACKETS,
    "grace_days": 45,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PERCENT_CAPPED",
    "late_fee_percent_bps": 500,
    "late_fee_cap_cents": 5000,
    "annual_report_fee_cents": 0,
    "franchise_tax_filing_fee_cents": 0,
}

TX_RULE_LISTING = {
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FISCAL_YEAR_END_OFFSET",
    "fiscal_offset_days": 135,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
}

DE_RULE_LISTING = {
    "state_code": "DE",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 3,
    "fixed_due_day": 1,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "annual_report_fee_cents": 5000,
}

NY_RULE_LISTING = {
    "state_code": "NY",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
}

MA_RULE_FEB31 = {
    "state_code": "MA",
    "effective_from": "2026-01-01",
    "annual_report_basis": "FIXED_CALENDAR_DATE",
    "fixed_due_month": 2,
    "fixed_due_day": 31,
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "annual_report_fee_cents": 5000,
    "grace_days": 0,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 0,
}

CA_RULE_CALENDAR_GRACE = {
    "state_code": "CA",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "grace_days": 10,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "FLAT",
    "late_fee_flat_cents": 0,
    "annual_report_fee_cents": 2000,
}

OR_RULE_BUSINESS_GRACE = _copy(
    CA_RULE_CALENDAR_GRACE, state_code="OR", grace_basis="BUSINESS_DAYS"
)

CA_RULE_PER_MONTH = {
    "state_code": "CA",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "FLAT",
    "flat_franchise_tax_cents": 0,
    "grace_days": 58,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PER_MONTH",
    "late_fee_per_month_cents": 5000,
    "annual_report_fee_cents": 2000,
}

NY_RULE_ASSUMED_PAR = {
    "state_code": "NY",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "ASSUMED_PAR_VALUE",
    "assumed_par_value_rate_bps": 35,
    "min_franchise_tax_cents": 17500,
    "max_franchise_tax_cents": 2000000,
    "grace_days": 15,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PERCENT_CAPPED",
    "late_fee_percent_bps": 1000,
    "late_fee_cap_cents": 30000,
    "annual_report_fee_cents": 900,
    "franchise_tax_filing_fee_cents": 900,
}


def state_rule_payload(base: dict, **overrides) -> dict:
    return _copy(base, **overrides)


# --- Other payloads ----------------------------------------------------------

def create_client_payload(**overrides) -> dict:
    return _copy(
        {"legal_name": "Harbor Holdings", "billing_email": "ap@harbor.example"},
        **overrides,
    )


def create_legal_entity_payload(**overrides) -> dict:
    return _copy(
        {
            "legal_name": "Northwind Widgets LLC",
            "entity_type": "LLC",
            "home_state_code": "DE",
            "formation_date": "2026-01-31",
        },
        **overrides,
    )


def create_beneficial_owner_payload(**overrides) -> dict:
    return _copy(
        {
            "full_name": "Ada Mercer",
            "date_of_birth": "1980-04-02",
            "residential_address": "12 Pier Rd",
            "id_document_number": "P4471190",
            "ownership_pct": 60,
        },
        **overrides,
    )


def create_name_clearance_payload(**overrides) -> dict:
    return _copy(
        {"state_code": "TX", "requested_name": "Northwind Widgets LLC"}, **overrides
    )


def create_certificate_payload(**overrides) -> dict:
    return _copy(
        {"issued_on": "2026-04-20", "certificate_number": "DE-GS-77120"}, **overrides
    )


def create_appointment_payload(expected_registration_version, **overrides) -> dict:
    return _copy(
        {
            "provider_name": "Bay State Agents",
            "appointed_on": "2026-05-01",
            "expected_registration_version": expected_registration_version,
        },
        **overrides,
    )


def create_obligation_payload(obligation_type, period_year) -> dict:
    return {"obligation_type": obligation_type, "period_year": period_year}


def create_obligation_filing_payload(filing_kind, expected_version, **overrides) -> dict:
    return _copy(
        {
            "filing_kind": filing_kind,
            "expected_compliance_obligation_version": expected_version,
        },
        **overrides,
    )


def create_standalone_filing_payload(filing_kind, **overrides) -> dict:
    return _copy({"filing_kind": filing_kind}, **overrides)


def create_payment_payload(authorized_amount_cents) -> dict:
    return {"authorized_amount_cents": authorized_amount_cents}


def capture_payload(capture_amount_cents, target_filing_id=None) -> dict:
    payload = {"capture_amount_cents": capture_amount_cents}
    if target_filing_id is not None:
        payload["target_filing_id"] = target_filing_id
    return payload


def create_boi_report_payload(report_kind, expected_legal_entity_version, **overrides) -> dict:
    return _copy(
        {
            "report_kind": report_kind,
            "expected_legal_entity_version": expected_legal_entity_version,
        },
        **overrides,
    )


def create_sop_payload(sop_class, **overrides) -> dict:
    return _copy({"sop_class": sop_class}, **overrides)
