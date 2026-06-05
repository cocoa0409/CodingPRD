"""Payload factories — one per entity, input fields only (PRD Section 3 + 4).

Computed/system fields (status, version, monthly_amount_cents, net_monthly_income_cents,
petitioner_time_pct, mediator_user_id, judge_user_id, ledger fields) are never in
these payloads — they are server-owned.
"""
from .constants import (
    CA_WIDE_TIER,
    SCHEDULE_DEFAULTS,
    DEFAULT_FILING_FEE_CENTS,
)


def guideline_schedule_payload(**overrides) -> dict:
    """POST /api/guideline-schedules. state_code + basic_obligation_tiers required;
    the four tuning pcts/months are optional (server defaults applied if omitted)."""
    defaults = {
        "state_code": "CA",
        "basic_obligation_tiers": [dict(t) for t in CA_WIDE_TIER],
        "spousal_payor_pct": SCHEDULE_DEFAULTS["spousal_payor_pct"],
        "spousal_payee_offset_pct": SCHEDULE_DEFAULTS["spousal_payee_offset_pct"],
        "shared_custody_threshold_pct": SCHEDULE_DEFAULTS["shared_custody_threshold_pct"],
        "long_marriage_months": SCHEDULE_DEFAULTS["long_marriage_months"],
    }
    defaults.update(overrides)
    return defaults


def case_payload(**overrides) -> dict:
    """POST /api/cases."""
    defaults = {
        "state_code": "CA",
        "caption": "In re Marriage of Test",
        "marriage_months": 84,
        "filing_fee_cents": DEFAULT_FILING_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def party_payload(case_id, role, user_id, **overrides) -> dict:
    """POST /api/parties."""
    defaults = {
        "case_id": case_id,
        "role": role,
        "user_id": user_id,
        "full_name": "Party Name",
        "gross_monthly_income_cents": 800000,
    }
    defaults.update(overrides)
    return defaults


def child_payload(case_id, **overrides) -> dict:
    """POST /api/children."""
    defaults = {
        "case_id": case_id,
        "full_name": "Child Name",
        "birth_year": 2016,
    }
    defaults.update(overrides)
    return defaults


def pleading_payload(case_id, pleading_type, filed_by_party_id, **overrides) -> dict:
    """POST /api/pleadings."""
    defaults = {
        "case_id": case_id,
        "pleading_type": pleading_type,
        "filed_by_party_id": filed_by_party_id,
    }
    defaults.update(overrides)
    return defaults


def financial_disclosure_payload(party_id, case_id, **overrides) -> dict:
    """POST /api/financial-disclosures."""
    defaults = {
        "party_id": party_id,
        "case_id": case_id,
        "gross_monthly_income_cents": 720000,
        "tax_withholding_cents": 90000,
        "mandatory_retirement_cents": 20000,
        "health_insurance_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def parenting_plan_payload(case_id, proposed_by_party_id,
                           petitioner_overnights=110, respondent_overnights=255,
                           **overrides) -> dict:
    """POST /api/parenting-plans (overnights default to a 365-sum split)."""
    defaults = {
        "case_id": case_id,
        "proposed_by_party_id": proposed_by_party_id,
        "petitioner_overnights": petitioner_overnights,
        "respondent_overnights": respondent_overnights,
    }
    defaults.update(overrides)
    return defaults


def revise_plan_payload(petitioner_overnights, respondent_overnights, **overrides) -> dict:
    """POST /api/parenting-plans/{id}/revise."""
    defaults = {
        "petitioner_overnights": petitioner_overnights,
        "respondent_overnights": respondent_overnights,
    }
    defaults.update(overrides)
    return defaults


def mediation_session_payload(case_id, mediator_user_id,
                              scheduled_start, scheduled_end, **overrides) -> dict:
    """POST /api/mediation-sessions."""
    defaults = {
        "case_id": case_id,
        "mediator_user_id": mediator_user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def support_order_payload(case_id, support_type, payor_party_id, payee_party_id,
                          variant, **overrides) -> dict:
    """POST /api/support-orders. monthly_amount_cents/support_term_months are
    server-computed and never client-supplied."""
    defaults = {
        "case_id": case_id,
        "support_type": support_type,
        "payor_party_id": payor_party_id,
        "payee_party_id": payee_party_id,
        "variant": variant,
    }
    defaults.update(overrides)
    return defaults


def court_order_payload(case_id, order_kind, support_order_ids, **overrides) -> dict:
    """POST /api/court-orders. parenting_plan_id / supersedes_order_id are optional
    (parenting_plan_id required for FINAL_JUDGMENT)."""
    defaults = {
        "case_id": case_id,
        "order_kind": order_kind,
        "support_order_ids": list(support_order_ids),
    }
    defaults.update(overrides)
    return defaults


def hearing_payload(case_id, courtroom_code, scheduled_start, scheduled_end, **overrides) -> dict:
    """POST /api/hearings."""
    defaults = {
        "case_id": case_id,
        "courtroom_code": courtroom_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults
