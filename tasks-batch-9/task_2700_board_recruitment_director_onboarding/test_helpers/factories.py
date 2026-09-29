"""Payload builders.

Each builder returns a plain dict that satisfies the PRD's required fields for
one create/transition call, with every optional field also stated explicitly so
no expected value in the suite leans on an unpublished fallback.  Monetary
amounts are always emitted as Python integers of cents, never as strings.
"""
import itertools

from . import constants as C

_seq = itertools.count(1)


def _n():
    return next(_seq)


# ---------------------------------------------------------------------------
# Governance policy
# ---------------------------------------------------------------------------
def policy_payload(cycle_year=C.CYCLE_YEAR, effective_from=C.POLICY_EFFECTIVE_FROM, **overrides):
    payload = {"cycle_year": cycle_year, "effective_from": effective_from}
    payload.update(C.POLICY_KNOBS)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Skill category
# ---------------------------------------------------------------------------
def skill_category_payload(
    code=None,
    name=None,
    strategic_weight=0.5,
    risk_oversight=False,
    required_min_directors=1,
    criticality="STRATEGIC",
    **overrides,
):
    i = _n()
    payload = {
        "code": code if code is not None else f"SKILL_{i}",
        "name": name if name is not None else f"Skill Category {i}",
        "strategic_weight": strategic_weight,
        "risk_oversight": risk_oversight,
        "required_min_directors": required_min_directors,
        "criticality": criticality,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Search firm
# ---------------------------------------------------------------------------
def search_firm_payload(
    name=None,
    contact_email=None,
    fee_model="RETAINER",
    retainer_fee_cents=5000000,
    placement_fee_pct=25.0,
    placement_fee_tier2_pct=20.0,
    **overrides,
):
    i = _n()
    payload = {
        "name": name if name is not None else f"Search Partners {i}",
        "contact_email": contact_email if contact_email is not None else f"partner{i}@search.example",
        "fee_model": fee_model,
        "retainer_fee_cents": retainer_fee_cents,
        "placement_fee_pct": placement_fee_pct,
        "placement_fee_tier2_pct": placement_fee_tier2_pct,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External company
# ---------------------------------------------------------------------------
def external_company_payload(
    name=None,
    ticker=None,
    is_public=True,
    is_competitor=False,
    gross_revenue_cents=100000000000,
    **overrides,
):
    i = _n()
    payload = {
        "name": name if name is not None else f"External Corp {i}",
        "ticker": ticker if ticker is not None else f"EXC{i}",
        "is_public": is_public,
        "is_competitor": is_competitor,
        "gross_revenue_cents": gross_revenue_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Director
# ---------------------------------------------------------------------------
def director_payload(
    full_name=None,
    email=None,
    birth_date="1966-04-10",
    appointed_on="2020-05-01",
    is_management=False,
    is_sitting_ceo_elsewhere=False,
    is_independent=True,
    shares_held=0,
    initial_service_status="SEATED",
    **overrides,
):
    i = _n()
    payload = {
        "full_name": full_name if full_name is not None else f"Director {i}",
        "email": email if email is not None else f"director{i}@board.example",
        "birth_date": birth_date,
        "appointed_on": appointed_on,
        "is_management": is_management,
        "is_sitting_ceo_elsewhere": is_sitting_ceo_elsewhere,
        "is_independent": is_independent,
        "shares_held": shares_held,
        "initial_service_status": initial_service_status,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Director skill rating
# ---------------------------------------------------------------------------
def skill_rating_payload(skill_category_id, self_rating=4, **overrides):
    payload = {"skill_category_id": skill_category_id, "self_rating": self_rating}
    payload.update(overrides)
    return payload


def rating_validation_payload(validated_rating, **overrides):
    payload = {"validated_rating": validated_rating}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
def candidate_payload(
    full_name=None,
    email=None,
    birth_date="1970-09-15",
    source_channel="SEARCH_FIRM",
    search_firm_id=None,
    referring_director_id=None,
    shareholder_proponent_name=None,
    is_sitting_ceo=False,
    target_annual_comp_cents=35000000,
    **overrides,
):
    i = _n()
    payload = {
        "full_name": full_name if full_name is not None else f"Candidate {i}",
        "email": email if email is not None else f"candidate{i}@people.example",
        "birth_date": birth_date,
        "source_channel": source_channel,
        "is_sitting_ceo": is_sitting_ceo,
        "target_annual_comp_cents": target_annual_comp_cents,
    }
    if search_firm_id is not None:
        payload["search_firm_id"] = search_firm_id
    if referring_director_id is not None:
        payload["referring_director_id"] = referring_director_id
    if shareholder_proponent_name is not None:
        payload["shareholder_proponent_name"] = shareholder_proponent_name
    payload.update(overrides)
    return payload


def reference_check_payload(reference_count=3, adverse_findings=False, **overrides):
    payload = {"reference_count": reference_count, "adverse_findings": adverse_findings}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External directorship
# ---------------------------------------------------------------------------
def external_directorship_payload(
    external_company_id,
    director_id=None,
    candidate_id=None,
    seat_role="DIRECTOR",
    is_audit_chair=False,
    start_on="2021-01-01",
    **overrides,
):
    payload = {
        "external_company_id": external_company_id,
        "seat_role": seat_role,
        "is_audit_chair": is_audit_chair,
        "start_on": start_on,
    }
    if director_id is not None:
        payload["director_id"] = director_id
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    payload.update(overrides)
    return payload


def end_directorship_payload(end_on="2026-07-01", **overrides):
    payload = {"end_on": end_on}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Independence screen
# ---------------------------------------------------------------------------
def screen_payload(
    payments_to_company_cents=0,
    recipient_gross_revenue_cents=0,
    prior_employment_end_on=None,
    family_member_employed=False,
    auditor_affiliation=False,
    charitable_contributions_cents=0,
    company_gross_revenue_cents=0,
    **overrides,
):
    payload = {
        "payments_to_company_cents": payments_to_company_cents,
        "recipient_gross_revenue_cents": recipient_gross_revenue_cents,
        "family_member_employed": family_member_employed,
        "auditor_affiliation": auditor_affiliation,
        "charitable_contributions_cents": charitable_contributions_cents,
        "company_gross_revenue_cents": company_gross_revenue_cents,
    }
    if prior_employment_end_on is not None:
        payload["prior_employment_end_on"] = prior_employment_end_on
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interview session
# ---------------------------------------------------------------------------
def interview_payload(
    candidate_id,
    interviewer_director_id,
    start_at="2026-08-10T09:00:00Z",
    end_at="2026-08-10T10:00:00Z",
    modality="VIDEO",
    **overrides,
):
    payload = {
        "candidate_id": candidate_id,
        "interviewer_director_id": interviewer_director_id,
        "start_at": start_at,
        "end_at": end_at,
        "modality": modality,
    }
    payload.update(overrides)
    return payload


def interview_completion_payload(score=4, recommendation="ADVANCE", **overrides):
    payload = {"score": score, "recommendation": recommendation}
    payload.update(overrides)
    return payload


def interview_cancellation_payload(resolution="CANCELLED", **overrides):
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Committee and assignment
# ---------------------------------------------------------------------------
def committee_payload(
    code="AUDIT",
    name=None,
    authorized_seats=4,
    min_seats=C.COMMITTEE_MIN_SEATS_DEFAULT,
    requires_all_independent=False,
    requires_financial_expert=False,
    **overrides,
):
    payload = {
        "code": code,
        "name": name if name is not None else f"{code.title()} Committee",
        "authorized_seats": authorized_seats,
        "min_seats": min_seats,
        "requires_all_independent": requires_all_independent,
        "requires_financial_expert": requires_financial_expert,
    }
    payload.update(overrides)
    return payload


def assignment_payload(
    director_id,
    expected_committee_version,
    seat_role="MEMBER",
    term_start_on="2026-01-01",
    term_end_on="2026-12-31",
    **overrides,
):
    payload = {
        "director_id": director_id,
        "seat_role": seat_role,
        "term_start_on": term_start_on,
        "term_end_on": term_end_on,
        "expected_committee_version": expected_committee_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Slate, nominee, ballot
# ---------------------------------------------------------------------------
def slate_payload(
    cycle_year=C.CYCLE_YEAR,
    seat_count=3,
    search_fee_budget_cents=C.SEARCH_FEE_BUDGET_DEFAULT_CENTS,
    **overrides,
):
    payload = {
        "cycle_year": cycle_year,
        "seat_count": seat_count,
        "search_fee_budget_cents": search_fee_budget_cents,
    }
    payload.update(overrides)
    return payload


def nominee_payload(
    expected_slate_version,
    ballot_order,
    candidate_id=None,
    incumbent_director_id=None,
    **overrides,
):
    payload = {
        "ballot_order": ballot_order,
        "expected_slate_version": expected_slate_version,
    }
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    if incumbent_director_id is not None:
        payload["incumbent_director_id"] = incumbent_director_id
    payload.update(overrides)
    return payload


def vote_payload(voting_director_id, ballot="FOR", rationale="Reviewed the file.", **overrides):
    payload = {
        "voting_director_id": voting_director_id,
        "ballot": ballot,
        "rationale": rationale,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision="APPROVE", rationale="Committee decision recorded.", **overrides):
    payload = {"decision": decision, "rationale": rationale}
    payload.update(overrides)
    return payload


def election_payload(elected_nominee_ids, **overrides):
    payload = {"elected_nominee_ids": list(elected_nominee_ids)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Onboarding item
# ---------------------------------------------------------------------------
def onboarding_item_payload(
    module_code=None,
    category="BUSINESS_ORIENTATION",
    is_required=True,
    credit_hours=0.0,
    due_on=None,
    **overrides,
):
    i = _n()
    payload = {
        "module_code": module_code if module_code is not None else f"MODULE_{i}",
        "category": category,
        "is_required": is_required,
        "credit_hours": credit_hours,
    }
    if due_on is not None:
        payload["due_on"] = due_on
    payload.update(overrides)
    return payload


def waiver_payload(waiver_reason="Equivalent prior training on file.", **overrides):
    payload = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compensation award
# ---------------------------------------------------------------------------
def comp_award_payload(
    cycle_year=C.CYCLE_YEAR,
    service_start_on="2026-01-01",
    service_end_on="2026-12-31",
    share_price_cents=90000,
    shares_held=900,
    **overrides,
):
    payload = {
        "cycle_year": cycle_year,
        "service_start_on": service_start_on,
        "service_end_on": service_end_on,
        "share_price_cents": share_price_cents,
        "shares_held": shares_held,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Departure notice and logical clock
# ---------------------------------------------------------------------------
def departure_notice_payload(notice_type="RESIGNATION", effective_on=None, **overrides):
    payload = {"notice_type": notice_type}
    if effective_on is not None:
        payload["effective_on"] = effective_on
    payload.update(overrides)
    return payload


def clock_payload(current_utc):
    return {"current_utc": current_utc}
