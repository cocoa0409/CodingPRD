"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

DEFAULTS = {
    "ORG_NAME": "Test Org",
    "ORG_STATE": "CA",
    "FYE_MONTH": 12,
    "RECEIPTS": 4_000_000_000,
    "QUORUM_PCT": 50,
    "QUORUM_BASIS": "SEATED",
    "AMENDMENT_THRESHOLD_PCT": 67,
    "TERM_LENGTH_YEARS": 2,
    "MAX_CONSECUTIVE_TERMS": 3,
    "TERM_COOLOFF_YEARS": 1,
    "BOARD_SIZE": 5,
    "TERM_START": "2026-01-01T00:00:00Z",
    "MEETING_START": "2026-08-01T00:00:00Z",
    "DURATION_MINUTES": 60,
    "EXECUTIVE_NAME": "ED Smith",
    "PREPARER": "staff-1",
}


def create_nonprofit_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "ein": "EIN-1",
        "state_of_incorporation": DEFAULTS["ORG_STATE"],
        "fiscal_year_end_month": DEFAULTS["FYE_MONTH"],
        "annual_gross_receipts_cents": DEFAULTS["RECEIPTS"],
    }
    defaults.update(overrides)
    return defaults


def create_bylaws_payload(nonprofit_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "quorum_pct": DEFAULTS["QUORUM_PCT"],
        "quorum_basis": DEFAULTS["QUORUM_BASIS"],
        "amendment_threshold_pct": DEFAULTS["AMENDMENT_THRESHOLD_PCT"],
        "term_length_years": DEFAULTS["TERM_LENGTH_YEARS"],
        "max_consecutive_terms": DEFAULTS["MAX_CONSECUTIVE_TERMS"],
        "term_cooloff_years": DEFAULTS["TERM_COOLOFF_YEARS"],
        "board_size": DEFAULTS["BOARD_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(nonprofit_id, base_bylaws_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "base_bylaws_id": base_bylaws_id,
        "title": "Amendment",
        "proposed_fields": {"quorum_pct": 60},
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(nonprofit_id, full_name, email, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "full_name": full_name,
        "email": email,
        "skill_tags": ["GOVERNANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(nonprofit_id, board_member_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "board_member_id": board_member_id,
        "start_date": DEFAULTS["TERM_START"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_payload(nonprofit_id, name, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "name": name,
        "type": "GOVERNANCE",
        "min_members": 1,
        "authorized_size": 3,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(nonprofit_id, committee_id, board_member_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "committee_id": committee_id,
        "board_member_id": board_member_id,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(nonprofit_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "scheduled_start": DEFAULTS["MEETING_START"],
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
        "notice_waived": True,
    }
    defaults.update(overrides)
    return defaults


def create_motion_payload(nonprofit_id, meeting_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "meeting_id": meeting_id,
        "title": "Motion",
        "category": "GOVERNANCE",
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(nonprofit_id, motion_id, board_member_id, choice) -> dict:
    return {
        "nonprofit_id": nonprofit_id,
        "motion_id": motion_id,
        "board_member_id": board_member_id,
        "choice": choice,
    }


def create_disclosure_payload(nonprofit_id, board_member_id, fiscal_year, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "board_member_id": board_member_id,
        "fiscal_year": fiscal_year,
        "answers": [{"question_key": "q1", "answer": False}],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(nonprofit_id, fiscal_year, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "fiscal_year": fiscal_year,
        "executive_name": DEFAULTS["EXECUTIVE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_succession_plan_payload(nonprofit_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "target_role": "EXECUTIVE_DIRECTOR",
        "readiness": "READY_NOW",
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(nonprofit_id, fiscal_year, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "fiscal_year": fiscal_year,
        "total_revenue_cents": 100_000_000,
        "total_expenses_cents": 60_000_000,
        "contributions_cents": 70_000_000,
        "program_service_revenue_cents": 20_000_000,
        "preparer_user_id": DEFAULTS["PREPARER"],
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(nonprofit_id, state_code, current_period_end, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "state_code": state_code,
        "current_period_end": current_period_end,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(nonprofit_id, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "policy_type": "DNO",
        "carrier": "Carrier1",
        "coverage_limit_cents": 1_000_000_000,
        "premium_cents": 100_000,
        "policy_start_date": "2026-01-01T00:00:00Z",
        "policy_end_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def make_scores(value) -> list:
    """A complete five-dimension score sheet with every dimension at `value`."""
    return [
        {"dimension": d, "score": value}
        for d in ("LEADERSHIP", "FUNDRAISING", "FINANCIAL", "PROGRAM", "GOVERNANCE")
    ]


def make_scores_list(leadership, fundraising, financial, program, governance) -> list:
    return [
        {"dimension": "LEADERSHIP", "score": leadership},
        {"dimension": "FUNDRAISING", "score": fundraising},
        {"dimension": "FINANCIAL", "score": financial},
        {"dimension": "PROGRAM", "score": program},
        {"dimension": "GOVERNANCE", "score": governance},
    ]
