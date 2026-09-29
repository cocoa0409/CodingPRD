"""
Request payload factories.

Each builder produces only the *input* fields the PRD declares for its endpoint:
server-managed identity fields (§2.4), computed figures and state fields are
never sent. Every builder accepts keyword overrides, and passing ``None`` for an
optional field removes it from the payload so the endpoint's declared default can
be exercised.
"""

from typing import Any, Dict, List


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` deletes the key so the default applies."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Institution (PRD §3.1) ───────────────────────────────────────────────


def institution_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Grace Covenant Church",
            "institution_type": "CONGREGATION",
            "denomination_code": "PCA",
            "requires_denominational_approval": False,
            "bylaws_borrowing_cap_cents": 500000000,
            "bylaws_quorum_pct": 0.6667,
            "community_program_count": 3,
            "endowment_market_value_cents": 800000000,
        },
        overrides,
    )


# ─── Giving period (PRD §3.1) ─────────────────────────────────────────────


def giving_period_payload(institution_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "institution_id": institution_id,
            "period_label": "2025Q1",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-03-31T00:00:00Z",
            "source": "AUDITED",
            "total_contributions_cents": 60000000,
            "restricted_contributions_cents": 8000000,
            "donor_restricted_endowment_draw_cents": 2000000,
            "operating_expense_cents": 39999950,
            "member_household_count": 500,
        },
        overrides,
    )


# The four audited 2025 quarters that every multi-step chain in this suite
# builds on. Their per-period arithmetic is pinned by PRD §3.1 and §3.5:
#   unrestricted = total - restricted - endowment draw
#   per-period net dollars = round_half_up((unrestricted - opex) / 100)
REFERENCE_AUDITED_QUARTERS: List[Dict[str, Any]] = [
    {
        "period_label": "2025Q1",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-03-31T00:00:00Z",
        "source": "AUDITED",
        "total_contributions_cents": 60000000,
        "restricted_contributions_cents": 8000000,
        "donor_restricted_endowment_draw_cents": 2000000,
        "operating_expense_cents": 39999950,
        "member_household_count": 500,
    },
    {
        "period_label": "2025Q2",
        "period_start": "2025-04-01T00:00:00Z",
        "period_end": "2025-06-30T00:00:00Z",
        "source": "AUDITED",
        "total_contributions_cents": 62000000,
        "restricted_contributions_cents": 8000000,
        "donor_restricted_endowment_draw_cents": 2000000,
        "operating_expense_cents": 40999950,
        "member_household_count": 510,
    },
    {
        "period_label": "2025Q3",
        "period_start": "2025-07-01T00:00:00Z",
        "period_end": "2025-09-30T00:00:00Z",
        "source": "AUDITED",
        "total_contributions_cents": 60000000,
        "restricted_contributions_cents": 8000000,
        "donor_restricted_endowment_draw_cents": 2000000,
        "operating_expense_cents": 40999950,
        "member_household_count": 515,
    },
    {
        "period_label": "2025Q4",
        "period_start": "2025-10-01T00:00:00Z",
        "period_end": "2025-12-31T00:00:00Z",
        "source": "AUDITED",
        "total_contributions_cents": 65000000,
        "restricted_contributions_cents": 8000000,
        "donor_restricted_endowment_draw_cents": 2000000,
        "operating_expense_cents": 41800200,
        "member_household_count": 520,
    },
]

# One further internal quarter, used where a chain needs the BLENDED basis to
# diverge from AUDITED_ONLY (PRD §3.1: an INTERNAL period 'contributes only 85
# percent of it').
REFERENCE_INTERNAL_2026Q1: Dict[str, Any] = {
    "period_label": "2026Q1",
    "period_start": "2026-01-01T00:00:00Z",
    "period_end": "2026-03-31T00:00:00Z",
    "source": "INTERNAL",
    "total_contributions_cents": 64000000,
    "restricted_contributions_cents": 8000000,
    "donor_restricted_endowment_draw_cents": 2000000,
    "operating_expense_cents": 43000000,
    "member_household_count": 530,
}


# ─── Governance authorization (PRD §3.2) ──────────────────────────────────


def governance_authorization_payload(institution_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "institution_id": institution_id,
            "resolution_date": "2026-06-15T00:00:00Z",
            "bylaws_citation": "Article VII Section 3",
            "board_votes_for": 8,
            "board_votes_total": 12,
            "authorized_amount_cents": 400000000,
            "expires_on": "2027-06-30T00:00:00Z",
        },
        overrides,
    )


def board_verification_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"minutes_reference": "MIN-2026-06-15"}, overrides)


def denominational_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def return_to_draft_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rework_note": "Reworking the resolution after rejection"}, overrides)


# ─── Pledge campaign and pledges (PRD §3.3) ───────────────────────────────


def pledge_campaign_payload(institution_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "institution_id": institution_id,
            "campaign_name": "Sanctuary 2026",
            "goal_cents": 200000000,
            "pledge_period_months": 36,
            "sponsor_collection_rate_bps": 9000,
        },
        overrides,
    )


def pledge_payload(
    pledge_campaign_id: str, expected_pledge_campaign_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "pledge_campaign_id": pledge_campaign_id,
            "donor_tier": "GENERAL",
            "pledged_amount_cents": 10000000,
            "installment_count": 12,
            "expected_pledge_campaign_version": expected_pledge_campaign_version,
        },
        overrides,
    )


def installment_payload(installment_month: int, outcome: str, amount_cents: int) -> Dict[str, Any]:
    """
    PRD §3.3: 'PAID requires an `amount_cents` strictly greater than zero, and
    MISSED requires an `amount_cents` of exactly zero.'
    """
    return {
        "installment_month": installment_month,
        "outcome": outcome,
        "amount_cents": amount_cents,
    }


def missed_installment_payload(installment_month: int) -> Dict[str, Any]:
    return installment_payload(installment_month, "MISSED", 0)


def paid_installment_payload(installment_month: int, amount_cents: int) -> Dict[str, Any]:
    return installment_payload(installment_month, "PAID", amount_cents)


# ─── Collateral (PRD §3.4) ────────────────────────────────────────────────


def collateral_asset_payload(institution_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "institution_id": institution_id,
            "asset_type": "SANCTUARY",
            "description_label": "Main sanctuary building",
            "appraised_value_cents": 500000000,
            "appraisal_date": "2025-06-01T00:00:00Z",
            "alternative_use_score": 2,
        },
        overrides,
    )


def assignment_payload(loan_application_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_application_id": loan_application_id,
            "lien_position": 1,
            "lien_effective_from": "2026-08-01T00:00:00Z",
            "lien_effective_to": "2031-08-01T00:00:00Z",
        },
        overrides,
    )


def release_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"release_note": "Deal shelved"}, overrides)


# ─── Loan application and loan (PRD §3.5, §3.6) ───────────────────────────


def loan_application_payload(
    institution_id: str, governance_authorization_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "institution_id": institution_id,
            "governance_authorization_id": governance_authorization_id,
            "purpose": "SANCTUARY_CONSTRUCTION",
            "requested_amount_cents": 225000000,
            "term_months": 240,
            "interest_rate_bps": 625,
        },
        overrides,
    )


def submit_underwriting_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"analyst_note": "Sanctuary construction facility"}, overrides)


def committee_referral_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"referral_note": "First lien fully covers the request"}, overrides)


def committee_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def loan_payload(loan_application_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_application_id": loan_application_id,
            "annual_debt_service_cents": 36000000,
            "interest_reserve_shortfall_cents": 1500000,
        },
        overrides,
    )


def loan_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"amount_cents": amount_cents, "payment_date": "2026-08-01T00:00:00Z"}, overrides
    )


def construction_completion_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"final_inspection_passed": True, "completion_note": "Project closed out"}, overrides
    )


# ─── Draw requests (PRD §3.7) ─────────────────────────────────────────────


def draw_request_payload(loan_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "project_phase": "FOUNDATION",
            "requested_amount_cents": 60000000,
            "percent_complete": 0.3000,
        },
        overrides,
    )


def draw_approval_payload(approved_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "approved_amount_cents": approved_amount_cents,
            "inspector_note": "Foundation poured and inspected",
        },
        overrides,
    )


def draw_disbursement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"disbursement_date": "2026-08-01T00:00:00Z"}, overrides)


def draw_rejection_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"inspector_note": "Shell framing not inspected"}, overrides)


def draw_void_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason": "Wire recalled by the title company"}, overrides)


def draw_reinstatement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reinstatement_note": "Breach resolved, resuming the draw"}, overrides)


# ─── Covenants (PRD §3.8) ─────────────────────────────────────────────────


def covenant_payload(loan_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "covenant_type": "DSCR_UNRESTRICTED_GIVING",
            "threshold_ratio": 1.2000,
            "test_frequency": "QUARTERLY",
        },
        overrides,
    )


def covenant_test_payload(as_of_date: str = "2026-08-01T00:00:00Z") -> Dict[str, Any]:
    return {"as_of_date": as_of_date}


def cure_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cure_evidence_note": "Fresh audited quarter filed"}, overrides)


def waiver_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"waiver_note": "Committee waives the breach"}, overrides)


# ─── Workout plans (PRD §3.9) ─────────────────────────────────────────────


def workout_plan_payload(loan_id: str, expected_loan_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "option": "PAYMENT_DEFERRAL",
            "deferral_months": 3,
            "denominational_support_letter": False,
            "narrative": "Three months of deferral while giving recovers",
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


def term_extension_payload(
    loan_id: str, expected_loan_version: int, extension_months: int = 60, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "option": "TERM_EXTENSION",
            "extension_months": extension_months,
            "denominational_support_letter": False,
            "narrative": "Stretching the amortisation to restore coverage",
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


def forgiveness_payload(
    loan_id: str, expected_loan_version: int, forgiveness_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "option": "PARTIAL_FORGIVENESS",
            "forgiveness_amount_cents": forgiveness_amount_cents,
            "denominational_support_letter": True,
            "narrative": "Forgiveness with a presbytery support letter",
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


def forbearance_payload(loan_id: str, expected_loan_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "option": "MISSION_IMPACT_FORBEARANCE",
            "denominational_support_letter": True,
            "narrative": "Forbearance while the food pantry expansion completes",
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


def workout_approval_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"approval_note": "Committee approves the plan"}, overrides)
