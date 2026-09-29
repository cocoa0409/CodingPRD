"""Payload factories — one per entity, input fields only."""
from .constants import (
    NORTHBAY_CAPITAL, HARBOR_CAPITAL, LAKESIDE_CAPITAL,
    STANDARD_EXAMINER_SCORES, WELL_CAPITALIZED_ADJUSTMENTS,
)


def institution_payload(**overrides) -> dict:
    """A NATIONAL/OCC acquirer-grade bank with the Northbay balance sheet."""
    payload = {
        "legal_name": "Northbay National Bank",
        "charter_type": "NATIONAL",
        "primary_regulator": "OCC",
        "latest_cra_rating": "SATISFACTORY",
    }
    payload.update(NORTHBAY_CAPITAL)
    payload.update(overrides)
    return payload


def acquirer_payload(**overrides) -> dict:
    """Northbay National Bank — the canonical acquirer."""
    return institution_payload(**overrides)


def target_payload(**overrides) -> dict:
    """Harbor Community Bank — the canonical target (STATE_NONMEMBER/FDIC)."""
    payload = {
        "legal_name": "Harbor Community Bank",
        "charter_type": "STATE_NONMEMBER",
        "primary_regulator": "FDIC",
        "latest_cra_rating": "SATISFACTORY",
    }
    payload.update(HARBOR_CAPITAL)
    payload.update(overrides)
    return payload


def third_party_payload(**overrides) -> dict:
    """Lakeside Trust Company — an unrelated in-market competitor."""
    payload = {
        "legal_name": "Lakeside Trust Company",
        "charter_type": "STATE_MEMBER",
        "primary_regulator": "FRB",
        "latest_cra_rating": "SATISFACTORY",
    }
    payload.update(LAKESIDE_CAPITAL)
    payload.update(overrides)
    return payload


def deposit_market_payload(**overrides) -> dict:
    payload = {
        "market_code": "KESTREL-MSA",
        "market_name": "Kestrel MSA",
        "market_type": "MSA",
    }
    payload.update(overrides)
    return payload


def branch_payload(institution_id, market_id, **overrides) -> dict:
    payload = {
        "institution_id": institution_id,
        "market_id": market_id,
        "branch_name": "Kestrel Main Office",
        "deposits_usd": 200_000_000,
        "service_type": "FULL_SERVICE",
    }
    payload.update(overrides)
    return payload


def merger_application_payload(acquirer_id, target_id, **overrides) -> dict:
    payload = {
        "acquirer_id": acquirer_id,
        "target_id": target_id,
        "structure": "STATUTORY_MERGER",
        "consideration_type": "MIXED",
        "total_consideration_usd": 250_000_000,
    }
    payload.update(STANDARD_EXAMINER_SCORES)
    payload.update(overrides)
    return payload


def pro_forma_schedule_payload(application_id, expected_application_version, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
        "basis": "REGULATORY_ADJUSTED",
    }
    payload.update(WELL_CAPITALIZED_ADJUSTMENTS)
    payload.update(overrides)
    return payload


def competitive_analysis_payload(application_id, market_id, **overrides) -> dict:
    payload = {"application_id": application_id, "market_id": market_id}
    payload.update(overrides)
    return payload


def comment_period_payload(application_id, opens_at, **overrides) -> dict:
    payload = {"application_id": application_id, "opens_at": opens_at}
    payload.update(overrides)
    return payload


def public_comment_payload(period_id, **overrides) -> dict:
    payload = {
        "period_id": period_id,
        "commenter_name": "Kestrel Neighborhood Alliance",
        "commenter_type": "COMMUNITY_ORGANIZATION",
        "stance": "PROTEST",
        "body": "The combined branch network abandons the east side.",
        "substantive": True,
    }
    payload.update(overrides)
    return payload


def hearing_request_payload(application_id, comment_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "comment_id": comment_id,
        "basis": "Branch closure record warrants oral testimony.",
    }
    payload.update(overrides)
    return payload


def benefits_plan_payload(application_id, expected_application_version, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
        "term_years": 3,
        "measurement_basis": "CUMULATIVE_TO_DATE",
    }
    payload.update(overrides)
    return payload


def line_item_payload(plan_id, category, committed_usd, **overrides) -> dict:
    payload = {"plan_id": plan_id, "category": category, "committed_usd": committed_usd}
    payload.update(overrides)
    return payload


def approval_decision_payload(application_id, decision="CONDITIONALLY_APPROVED", **overrides) -> dict:
    payload = {"application_id": application_id, "decision": decision}
    payload.update(overrides)
    return payload


def approval_condition_payload(decision_id, condition_type="DIVESTITURE",
                               timing="PRE_CONSUMMATION", **overrides) -> dict:
    payload = {
        "decision_id": decision_id,
        "condition_type": condition_type,
        "timing": timing,
        "description": "Divest Kestrel MSA deposits sufficient to clear the concentration screen.",
    }
    payload.update(overrides)
    return payload


def conversion_plan_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "conversion_start_date": "2027-06-15",
        "conversion_end_date": "2027-06-20",
        "affected_customer_count": 42_000,
    }
    payload.update(overrides)
    return payload


def performance_report_payload(plan_id, period_label, period_index, achieved_by_category,
                               **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "period_label": period_label,
        "period_index": period_index,
        "achieved_by_category": achieved_by_category,
    }
    payload.update(overrides)
    return payload
