"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid


def _unique_email(prefix: str = "test") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:10]}@example.com"


def _unique_code(prefix: str = "DEPT") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ---------- Department (PRD §3.1) ----------
def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": "Engineering",
        "cost_center_code": _unique_code("CC"),
        "hiring_budget_cents": 200_000_000,  # $2,000,000
    }
    defaults.update(overrides)
    return defaults


# ---------- JobRequisition (PRD §3.2) ----------
def create_requisition_payload(department_id: str, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "title": "Software Engineer",
        "target_level": "MID",
        "base_salary_min_cents": 10_000_000,  # $100k
        "base_salary_max_cents": 15_000_000,  # $150k
        "openings": 1,
    }
    defaults.update(overrides)
    return defaults


# ---------- Candidate (PRD §3.3) ----------
def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Candidate",
        "email": _unique_email("cand"),
        "source_channel": "DIRECT",
    }
    defaults.update(overrides)
    return defaults


def create_referral_candidate_payload(referrer_user_id: str, **overrides) -> dict:
    """Candidate with source_channel=REFERRAL — referrer_user_id is required (PRD §3.3)."""
    defaults = {
        "full_name": "Referral Candidate",
        "email": _unique_email("ref"),
        "source_channel": "REFERRAL",
        "referrer_user_id": referrer_user_id,
    }
    defaults.update(overrides)
    return defaults


# ---------- Application (PRD §3.4) ----------
def create_application_payload(candidate_id: str, requisition_id: str, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "requisition_id": requisition_id,
    }
    defaults.update(overrides)
    return defaults


# ---------- Interview (PRD §3.5) ----------
def create_interview_payload(application_id: str, panel_user_ids,
                             round_number: int = 1,
                             scheduled_at: str = "2027-01-01T10:00:00Z",
                             duration_minutes: int = 60,
                             **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "round_number": round_number,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "panel_user_ids": list(panel_user_ids),
    }
    defaults.update(overrides)
    return defaults


# ---------- InterviewFeedback (PRD §3.5) ----------
def create_interview_feedback_payload(interview_id: str, panelist_user_id: str,
                                      score: int = 4, comments: str = "ok",
                                      **overrides) -> dict:
    defaults = {
        "interview_id": interview_id,
        "panelist_user_id": panelist_user_id,
        "score": score,
        "comments": comments,
    }
    defaults.update(overrides)
    return defaults


# ---------- Offer (PRD §3.6) ----------
def create_offer_payload(application_id: str, base_salary_cents: int = 12_000_000,
                         signing_bonus_cents: int = 0, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "base_salary_cents": base_salary_cents,
        "signing_bonus_cents": signing_bonus_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_offer_payload(expected_offer_version: int, **overrides) -> dict:
    """OCC-guarded approve (PRD §2.7)."""
    defaults = {"expected_offer_version": expected_offer_version}
    defaults.update(overrides)
    return defaults


def cancel_requisition_payload(expected_requisition_version: int, **overrides) -> dict:
    """OCC-guarded cancel (PRD §2.7)."""
    defaults = {"expected_requisition_version": expected_requisition_version}
    defaults.update(overrides)
    return defaults


# ---------- BackgroundCheck (PRD §3.7) ----------
def resolve_background_check_payload(outcome: str = "PASSED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


# ---------- DiversityGoal (PRD §3.1) ----------
def create_diversity_goal_payload(department_id: str, target_level: str = "MID",
                                  period_year: int = 2027,
                                  target_underrepresented_pct: float = 0.50,
                                  **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "target_level": target_level,
        "period_year": period_year,
        "target_underrepresented_pct": target_underrepresented_pct,
    }
    defaults.update(overrides)
    return defaults


# ---------- Clock (PRD §3.8) ----------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
