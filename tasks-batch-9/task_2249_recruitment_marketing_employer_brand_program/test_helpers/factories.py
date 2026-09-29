"""Request-body builders with valid defaults; pass keywords to override any field."""
from typing import Any, Dict, Optional


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Overrides win; a value of ``None`` removes the field from the body entirely."""
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<omit>"


#: Sentinel that removes a defaulted field from a generated body.
OMIT = _Omit()
_OMIT = OMIT


# --------------------------------------------------------------------- programs

def program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Talent Brand FY26",
            "fiscal_year": 2026,
            "attribution_model": "LINEAR",
        },
        overrides,
    )


# ----------------------------------------------------------------- job families

def job_family_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "name": "Software Engineering",
            "code": "SWE",
            "cpqa_target_cents": 15000,
            "priority_rank": 1,
            "dedicated_budget_cents": 0,
        },
        overrides,
    )


# --------------------------------------------------------------------- channels

def channel_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "name": "Board A",
            "channel_type": "JOB_BOARD",
            "daily_capacity_cents": 100000,
            "min_flight_days": 1,
        },
        overrides,
    )


# ------------------------------------------------------------ candidate personas

def persona_payload(job_family_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "job_family_id": job_family_id,
            "name": "Backend IC",
            "mix_method": "SURVEY_WEIGHTED",
            "research_window_days": 180,
        },
        overrides,
    )


def persona_review_payload(decision: str, review_note: str = "reviewed") -> Dict[str, Any]:
    return {"decision": decision, "review_note": review_note}


def signal_payload(persona_id: str, channel_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "persona_id": persona_id,
            "channel_id": channel_id,
            "preference_score": 70,
            "sample_size": 400,
            "engagement_events": 100,
            "collected_at": "2026-07-20T00:00:00Z",
        },
        overrides,
    )


# ----------------------------------------------------------------- job postings

def posting_payload(job_family_id: str, **overrides: Any) -> Dict[str, Any]:
    """Defaults describe a posting that optimizes to a publishable score."""
    return _merge(
        {
            "job_family_id": job_family_id,
            "title": "Senior Backend Engineer",
            "responsibility_count": 6,
            "benefit_count": 5,
            "pay_range_min_cents": 12000000,
            "pay_range_max_cents": 18000000,
            "eeo_statement_included": True,
            "superlative_claim_included": False,
        },
        overrides,
    )


def optimize_payload(expected_posting_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_posting_version": expected_posting_version}, overrides)


def compliance_review_payload(decision: str, note: str = "reviewed") -> Dict[str, Any]:
    return {"decision": decision, "note": note}


# ---------------------------------------------------------------- media flights

def flight_payload(
    channel_id: str,
    job_family_id: str,
    job_posting_id: str,
    expected_program_version: int,
    start_date: str = "2026-08-05",
    end_date: str = "2026-08-10",
    daily_cap_cents: int = 50000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "channel_id": channel_id,
            "job_family_id": job_family_id,
            "job_posting_id": job_posting_id,
            "start_date": start_date,
            "end_date": end_date,
            "daily_cap_cents": daily_cap_cents,
            "expected_program_version": expected_program_version,
        },
        overrides,
    )


def spend_payload(amount_cents: int, spent_on: str = "2026-08-01") -> Dict[str, Any]:
    return {"amount_cents": amount_cents, "spent_on": spent_on}


def cancel_reason_payload(reason: str = "cancelled by the buyer") -> Dict[str, Any]:
    return {"reason": reason}


# ------------------------------------------------- applications and touchpoints

def application_payload(job_posting_id: str, candidate_email: str) -> Dict[str, Any]:
    return {"job_posting_id": job_posting_id, "candidate_email": candidate_email}


def decide_payload(outcome: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if reason is not None:
        payload["reason"] = reason
    return payload


def touchpoint_payload(
    application_id: str,
    channel_id: str,
    occurred_at: str,
    touch_type: str = "CLICK",
    media_cost_cents: int = 0,
    media_flight_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "channel_id": channel_id,
        "touch_type": touch_type,
        "occurred_at": occurred_at,
        "media_cost_cents": media_cost_cents,
    }
    if media_flight_id is not None:
        payload["media_flight_id"] = media_flight_id
    return payload


# ------------------------------------------------------ talent community members

def member_payload(program_id: str, email: str = "m1@example.com", **overrides: Any) -> Dict[str, Any]:
    return _merge({"program_id": program_id, "email": email}, overrides)


def confirm_consent_payload(consent_token: str) -> Dict[str, Any]:
    return {"consent_token": consent_token}


def consent_change_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


# ------------------------------------------------------------ nurture campaigns

def campaign_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"program_id": program_id, "name": "August talent digest", "max_sends": 5},
        overrides,
    )


def schedule_payload(scheduled_for: str) -> Dict[str, Any]:
    return {"scheduled_for": scheduled_for}


# ------------------------------------------------------------- employer reviews

def review_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "platform": "GLASSDOOR",
            "external_ref": "gd-01",
            "rating": 3,
            "posted_at": "2026-07-31T00:00:00Z",
        },
        overrides,
    )


def triage_payload(note: str = "first pass") -> Dict[str, Any]:
    return {"note": note}


def draft_response_payload(response_body: str = "Thank you for the feedback.") -> Dict[str, Any]:
    return {"response_body": response_body}


def legal_review_payload(decision: str, note: str = "reviewed") -> Dict[str, Any]:
    return {"decision": decision, "note": note}


# -------------------------------------------------------------- event presences

def presence_payload(
    program_id: str,
    job_family_id: str,
    venue_code: str = "CAMPUS-A",
    start_at: str = "2026-08-19T09:00:00Z",
    end_at: str = "2026-08-20T18:00:00Z",
    booth_cost_cents: int = 200000,
) -> Dict[str, Any]:
    return {
        "program_id": program_id,
        "job_family_id": job_family_id,
        "venue_code": venue_code,
        "start_at": start_at,
        "end_at": end_at,
        "booth_cost_cents": booth_cost_cents,
    }
