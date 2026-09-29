"""
Request-body builders.

One builder per write endpoint. Each takes the required fields as arguments,
leaves every optional field out unless it is passed, and accepts `**overrides`
so a test can bend one value without restating the whole body. Omitting rather
than defaulting matters here, because several tests exist precisely to check
what the server fills in when a field is absent.
"""

from typing import Any, Dict, Optional

from . import constants as K


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the keys whose value was left as None so the field stays absent."""
    return {key: value for key, value in payload.items() if value is not None}


# ─── Theatres ─────────────────────────────────────────────────────────────


def theatre_payload(
    name: str = "Palace Theatre",
    seat_count: int = 1200,
    top_ticket_price_cents: int = 19900,
    changeover_buffer_days: Optional[int] = None,
    weekly_fixed_rent_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "name": name,
            "seat_count": seat_count,
            "top_ticket_price_cents": top_ticket_price_cents,
            "changeover_buffer_days": changeover_buffer_days,
            "weekly_fixed_rent_cents": weekly_fixed_rent_cents,
        }
    )
    payload.update(overrides)
    return payload


# ─── Productions ──────────────────────────────────────────────────────────


def production_payload(
    theatre_id: str,
    title: str = "The Understudy",
    offering_entity_type: str = "LP",
    capitalization_target_cents: int = 120_000_000,
    reserve_target_cents: int = 20_000_000,
    pre_recoupment_pool_pct: Optional[float] = None,
    post_recoupment_pool_pct: Optional[float] = None,
    subsidiary_rights_investor_share_pct: Optional[float] = None,
    closing_notice_min_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "title": title,
            "offering_entity_type": offering_entity_type,
            "capitalization_target_cents": capitalization_target_cents,
            "reserve_target_cents": reserve_target_cents,
            "theatre_id": theatre_id,
            "pre_recoupment_pool_pct": pre_recoupment_pool_pct,
            "post_recoupment_pool_pct": post_recoupment_pool_pct,
            "subsidiary_rights_investor_share_pct": subsidiary_rights_investor_share_pct,
            "closing_notice_min_days": closing_notice_min_days,
        }
    )
    payload.update(overrides)
    return payload


def spelled_out_production_payload(theatre_id: str, **overrides: Any) -> Dict[str, Any]:
    """A production body that states all four deal terms explicitly."""
    return production_payload(
        theatre_id,
        pre_recoupment_pool_pct=K.DEFAULT_PRE_RECOUPMENT_POOL_PCT,
        post_recoupment_pool_pct=K.DEFAULT_POST_RECOUPMENT_POOL_PCT,
        subsidiary_rights_investor_share_pct=K.DEFAULT_SUBSIDIARY_RIGHTS_INVESTOR_SHARE_PCT,
        closing_notice_min_days=K.DEFAULT_CLOSING_NOTICE_MIN_DAYS,
        **overrides,
    )


def operating_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


# ─── Theatre engagements ──────────────────────────────────────────────────


def engagement_payload(
    production_id: str,
    theatre_id: str,
    start_date: str,
    end_date: str,
    engagement_type: str = "PERFORMANCE_RUN",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "theatre_id": theatre_id,
        "engagement_type": engagement_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


# ─── Budget lines ─────────────────────────────────────────────────────────


def budget_line_payload(
    production_id: str,
    amount_cents: int,
    expected_production_version: int,
    component: str = "PRODUCTION",
    description: str = "Scenery build",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "component": component,
        "description": description,
        "amount_cents": amount_cents,
        "expected_production_version": expected_production_version,
    }
    payload.update(overrides)
    return payload


def reserve_line_payload(
    production_id: str,
    amount_cents: int,
    expected_production_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """The RESERVE line the closing cascade draws on."""
    return budget_line_payload(
        production_id,
        amount_cents,
        expected_production_version,
        component="RESERVE",
        description="Closing reserve",
        **overrides,
    )


# ─── Operating budgets ────────────────────────────────────────────────────


def operating_budget_payload(
    production_id: str,
    weekly_fixed_running_cost_cents: int = 32_000_000,
    variable_cost_pct: float = 0.05,
    performances_per_week: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "production_id": production_id,
            "weekly_fixed_running_cost_cents": weekly_fixed_running_cost_cents,
            "variable_cost_pct": variable_cost_pct,
            "performances_per_week": performances_per_week,
        }
    )
    payload.update(overrides)
    return payload


# ─── Offering documents ───────────────────────────────────────────────────


def offering_document_payload(
    production_id: str,
    offering_amount_cents: int = 120_000_000,
    unit_price_cents: int = 120_000_000,
    max_investors: int = 3,
    doc_type: str = "LP_AGREEMENT",
    effective_date: str = "2026-07-15",
    expiration_date: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "doc_type": doc_type,
        "offering_amount_cents": offering_amount_cents,
        "unit_price_cents": unit_price_cents,
        "max_investors": max_investors,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
    }
    payload.update(overrides)
    return payload


def withdrawal_payload(reason: str = "Terms repapered") -> Dict[str, Any]:
    return {"withdrawal_reason": reason}


# ─── Investors and subscriptions ──────────────────────────────────────────


def investor_payload(
    legal_name: str = "Amelia Hart",
    jurisdiction: str = "NY",
    contact_email: str = "amelia.hart@example.com",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name,
        "jurisdiction": jurisdiction,
        "contact_email": contact_email,
    }
    payload.update(overrides)
    return payload


def accreditation_payload(accreditation_status: str = "ACCREDITED") -> Dict[str, Any]:
    return {"accreditation_status": accreditation_status}


def subscription_payload(
    offering_document_id: str, investor_id: str, units: int = 1, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "offering_document_id": offering_document_id,
        "investor_id": investor_id,
        "units": units,
    }
    payload.update(overrides)
    return payload


def cure_payload(defect_note: str = "Signature page unsigned") -> Dict[str, Any]:
    return {"defect_note": defect_note}


def resubmit_payload(units: int = 1) -> Dict[str, Any]:
    return {"units": units}


def rescission_payload(
    reason: str = "Investor exercised statutory rescission right",
) -> Dict[str, Any]:
    return {"rescission_reason": reason}


# ─── Royalty participants ─────────────────────────────────────────────────


def participant_payload(
    production_id: str,
    participant_name: str = "Iris Blake",
    role: str = "AUTHOR",
    fixed_gross_pct: float = 0.04,
    pool_points: int = 4,
    min_guarantee_cents: int = 400_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "participant_name": participant_name,
        "role": role,
        "fixed_gross_pct": fixed_gross_pct,
        "pool_points": pool_points,
        "min_guarantee_cents": min_guarantee_cents,
    }
    payload.update(overrides)
    return payload


def participant_payload_from(production_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Build a participant body from one of the constant specs."""
    return participant_payload(production_id, **spec)


# ─── Weekly wraps ─────────────────────────────────────────────────────────


def wrap_payload(
    production_id: str,
    week_ending_date: str = "2026-09-06",
    performances: int = 8,
    gross_receipts_cents: int = 65_000_000,
    paid_attendance: int = 8_200,
    running_expenses_cents: int = 33_500_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "week_ending_date": week_ending_date,
        "performances": performances,
        "gross_receipts_cents": gross_receipts_cents,
        "paid_attendance": paid_attendance,
        "running_expenses_cents": running_expenses_cents,
    }
    payload.update(overrides)
    return payload


def standard_week_payload(production_id: str, **overrides: Any) -> Dict[str, Any]:
    """The profitable week whose royalty base is 28,250,000 cents."""
    return wrap_payload(production_id, **{**K.STANDARD_WEEK, **overrides})


def dispute_payload(
    dispute_note: str = "Box office statement understates single-ticket gross",
) -> Dict[str, Any]:
    return {"dispute_note": dispute_note}


def amend_payload(**fields: Any) -> Dict[str, Any]:
    """An amendment body carrying only the figures the test means to restate."""
    return dict(fields)


def void_payload(
    void_reason: str = "Duplicate settlement discovered in audit",
) -> Dict[str, Any]:
    return {"void_reason": void_reason}


# ─── Subsidiary rights income ─────────────────────────────────────────────


def income_payload(
    production_id: str,
    gross_income_cents: int = 10_000_000,
    source: str = "CAST_ALBUM",
    received_date: str = "2026-08-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "source": source,
        "gross_income_cents": gross_income_cents,
        "received_date": received_date,
    }
    payload.update(overrides)
    return payload


# ─── Investor distributions ───────────────────────────────────────────────


def distribution_payload(
    production_id: str,
    total_amount_cents: int,
    expected_production_version: int,
    distribution_type: str = "RECOUPMENT_RETURN",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "distribution_type": distribution_type,
        "total_amount_cents": total_amount_cents,
        "expected_production_version": expected_production_version,
    }
    payload.update(overrides)
    return payload


# ─── Closing notices ──────────────────────────────────────────────────────


def closing_notice_payload(
    production_id: str,
    notice_date: str,
    final_performance_date: str,
    reason: str = "ECONOMIC",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "production_id": production_id,
        "notice_date": notice_date,
        "final_performance_date": final_performance_date,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def settle_payload(closing_costs_cents: int = 5_000_000) -> Dict[str, Any]:
    return {"closing_costs_cents": closing_costs_cents}
