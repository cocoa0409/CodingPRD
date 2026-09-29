"""
Payload factories.

Every literal here is the canonical setup literal pinned by the two design
indices (§1.8 / §1.9). Money is always an integer count of cents and shares are
always integer basis points — PRD.md §2.6 forbids fractional or string money,
so no factory may emit a numeric field as a string.
"""

from .constants import (
    CANONICAL_LEASE,
    CANONICAL_LESSEE_EMAIL,
    CANONICAL_LESSEE_NAME,
    CANONICAL_LESSEE_RATING,
    MEZZ_MORTGAGE,
    SENIOR_MORTGAGE,
)


def lessee_payload(**overrides):
    payload = {
        "legal_name": CANONICAL_LESSEE_NAME,
        "notice_email": CANONICAL_LESSEE_EMAIL,
        "credit_rating_code": CANONICAL_LESSEE_RATING,
    }
    payload.update(overrides)
    return payload


def lease_payload(lessee_id, premises_code, **overrides):
    payload = dict(CANONICAL_LEASE)
    payload["lessee_id"] = lessee_id
    payload["premises_code"] = premises_code
    payload.update(overrides)
    return payload


def insurance_payload(**overrides):
    payload = {
        "property_all_risk_limit_cents": 90000000,
        "builders_risk_limit_cents": 20000000,
        "lessor_additional_insured": True,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def rent_charge_payload(amount_cents=1000000, memo="2026 Q2 ground rent"):
    return {"amount_cents": amount_cents, "memo": memo}


def senior_mortgage_payload(**overrides):
    payload = dict(SENIOR_MORTGAGE)
    payload.update(overrides)
    return payload


def mezz_mortgage_payload(**overrides):
    payload = dict(MEZZ_MORTGAGE)
    payload.update(overrides)
    return payload


def revaluation_payload(valuation_date="2027-06-01T00:00:00Z", **overrides):
    payload = {"valuation_date": valuation_date}
    payload.update(overrides)
    return payload


def appraisal_payload(appointed_by, appraised_annual_rent_cents,
                      valuation_method_code=None, **overrides):
    if valuation_method_code is None:
        valuation_method_code = (
            "COMPARABLE_LAND" if appointed_by == "LESSOR" else "INCOME_CAP"
        )
    payload = {
        "appointed_by": appointed_by,
        "appraised_annual_rent_cents": appraised_annual_rent_cents,
        "valuation_method_code": valuation_method_code,
    }
    payload.update(overrides)
    return payload


def referral_payload(arbitrator_user_id="arb-neutral-1",
                     hearing_date="2027-07-01T00:00:00Z", **overrides):
    payload = {
        "arbitrator_user_id": arbitrator_user_id,
        "hearing_date": hearing_date,
    }
    payload.update(overrides)
    return payload


def award_payload(independent_annual_rent_cents, **overrides):
    payload = {"independent_annual_rent_cents": independent_annual_rent_cents}
    payload.update(overrides)
    return payload


def statement_payload(lease_id, expected_lease_version,
                      period_start="2025-01-01T00:00:00Z",
                      period_end="2026-01-01T00:00:00Z",
                      reported_gross_sales_cents=120000000, **overrides):
    payload = {
        "lease_id": lease_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_gross_sales_cents": reported_gross_sales_cents,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def alteration_payload(scope_code="COSMETIC", proposed_use_code="RETAIL_MIXED",
                       requested_gfa_sqft=10000,
                       construction_window_start="2027-01-01T00:00:00Z",
                       construction_window_end="2027-06-01T00:00:00Z",
                       estimated_cost_cents=1000000, **overrides):
    payload = {
        "scope_code": scope_code,
        "proposed_use_code": proposed_use_code,
        "requested_gfa_sqft": requested_gfa_sqft,
        "construction_window_start": construction_window_start,
        "construction_window_end": construction_window_end,
        "estimated_cost_cents": estimated_cost_cents,
    }
    payload.update(overrides)
    return payload


def sublease_payload(lease_id, premises_unit_code, annual_sublease_rent_cents,
                     sublet_area_sqft=1000,
                     term_start="2026-09-01T00:00:00Z",
                     term_end="2031-09-01T00:00:00Z",
                     transferee_legal_name="Tidewater Grocers Inc",
                     transferee_credit_rating_code="BBB",
                     consent_deposit_cents=0, **overrides):
    payload = {
        "lease_id": lease_id,
        "transfer_type": "SUBLEASE",
        "term_start": term_start,
        "term_end": term_end,
        "transferee_legal_name": transferee_legal_name,
        "transferee_credit_rating_code": transferee_credit_rating_code,
        "premises_unit_code": premises_unit_code,
        "annual_sublease_rent_cents": annual_sublease_rent_cents,
        "sublet_area_sqft": sublet_area_sqft,
        "consent_deposit_cents": consent_deposit_cents,
    }
    payload.update(overrides)
    return payload


def assignment_payload(lease_id, transferee_lessee_id, net_consideration_cents,
                       transferee_legal_name="Seawall Fund II LLC",
                       transferee_credit_rating_code="BBB",
                       term_start="2026-09-01T00:00:00Z",
                       term_end="2070-01-01T00:00:00Z",
                       consent_deposit_cents=0, **overrides):
    payload = {
        "lease_id": lease_id,
        "transfer_type": "ASSIGNMENT",
        "term_start": term_start,
        "term_end": term_end,
        "transferee_legal_name": transferee_legal_name,
        "transferee_lessee_id": transferee_lessee_id,
        "transferee_credit_rating_code": transferee_credit_rating_code,
        "net_consideration_cents": net_consideration_cents,
        "consent_deposit_cents": consent_deposit_cents,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision="APPROVE", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def fee_payment_payload(amount_cents):
    return {"amount_cents": amount_cents}


def default_notice_payload(default_type="MONETARY_RENT_ARREARS",
                           claimed_amount_cents=None, **overrides):
    payload = {"default_type": default_type}
    if claimed_amount_cents is not None:
        payload["claimed_amount_cents"] = claimed_amount_cents
    payload.update(overrides)
    return payload


def lessee_cure_payload(payment_at, cure_amount_cents=1000000, **overrides):
    payload = {"payment_at": payment_at, "cure_amount_cents": cure_amount_cents}
    payload.update(overrides)
    return payload


def mortgagee_cure_payload(action, mortgage_id, cure_amount_cents=None, **overrides):
    payload = {"action": action, "mortgage_id": mortgage_id}
    if cure_amount_cents is not None:
        payload["cure_amount_cents"] = cure_amount_cents
    payload.update(overrides)
    return payload


def loss_event_payload(event_type="CASUALTY", scope_code="PARTIAL",
                       occurred_at="2026-07-01T00:00:00Z",
                       damage_estimate_cents=1000000,
                       damaged_area_sqft=500, **overrides):
    payload = {
        "event_type": event_type,
        "scope_code": scope_code,
        "occurred_at": occurred_at,
        "damage_estimate_cents": damage_estimate_cents,
        "damaged_area_sqft": damaged_area_sqft,
    }
    payload.update(overrides)
    return payload


def adjust_payload(distributable_pool_cents, allocation_method="BONUS_VALUE",
                   rent_abatement_bps=0, **overrides):
    payload = {
        "distributable_pool_cents": distributable_pool_cents,
        "allocation_method": allocation_method,
        "rent_abatement_bps": rent_abatement_bps,
    }
    payload.update(overrides)
    return payload


def election_payload(election, **overrides):
    payload = {"election": election}
    payload.update(overrides)
    return payload


def inspection_payload(structural_condition_score, envelope_condition_score,
                       systems_condition_score, **overrides):
    payload = {
        "structural_condition_score": structural_condition_score,
        "envelope_condition_score": envelope_condition_score,
        "systems_condition_score": systems_condition_score,
    }
    payload.update(overrides)
    return payload


def holdback_payload(acknowledged_holdback_cents):
    return {"acknowledged_holdback_cents": acknowledged_holdback_cents}


def estoppel_payload(lease_id, requested_by_mortgage_id, expected_lease_version,
                     **overrides):
    payload = {
        "lease_id": lease_id,
        "requested_by_mortgage_id": requested_by_mortgage_id,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def new_lease_election_payload(new_lessee_id, **overrides):
    payload = {"new_lessee_id": new_lessee_id}
    payload.update(overrides)
    return payload
