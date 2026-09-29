"""Payload factories — one per write operation, input fields only."""

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Code cycles and committees (PRD §3.1)
# ---------------------------------------------------------------------------
def create_code_cycle_payload(**overrides) -> dict:
    payload = {
        "cycle_year": TEST_DEFAULTS["CYCLE_YEAR"],
        "model_code_edition": TEST_DEFAULTS["MODEL_CODE_EDITION"],
        "intake_opens_at": TEST_DEFAULTS["INTAKE_OPENS_AT"],
        "intake_closes_at": TEST_DEFAULTS["INTAKE_CLOSES_AT"],
    }
    payload.update(overrides)
    return payload


def code_cycle_status_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def create_discipline_committee_payload(
    discipline: str = "ENERGY", voting_seat_count: int = 6, **overrides
) -> dict:
    payload = {"discipline": discipline, "voting_seat_count": voting_seat_count}
    payload.update(overrides)
    return payload


def create_committee_member_payload(
    full_name: str = "Dana Reyes", sector: str = "INDUSTRY", **overrides
) -> dict:
    payload = {"full_name": full_name, "sector": sector}
    payload.update(overrides)
    return payload


def recusal_payload(action: str = "RECUSE", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Amendment proposals (PRD §3.2)
# ---------------------------------------------------------------------------
def create_amendment_proposal_payload(code_cycle_id: str, **overrides) -> dict:
    payload = {
        "code_cycle_id": code_cycle_id,
        "code_section": "C402.1.4",
        "discipline": "ENERGY",
        "title": "Envelope U-factor tightening",
        "proposed_text": "Reduce maximum assembly U-factor for climate zone 5 walls.",
        "stringency_direction": "MORE_STRINGENT",
        "proposer_sector": "INDUSTRY",
    }
    payload.update(overrides)
    return payload


def screening_payload(decision: str = "ACCEPT_FOR_ANALYSIS", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def reopen_payload(reason: str = "Council asked for a redraft.", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Impact analyses (PRD §3.3)
# ---------------------------------------------------------------------------
def create_cost_benefit_analysis_payload(
    expected_proposal_version: int, **overrides
) -> dict:
    payload = {
        "expected_proposal_version": expected_proposal_version,
        "analysis_type": "COST_BENEFIT",
        "incremental_cost_by_occupancy": {
            "R3": 42375,
            "R2": 61250,
            "B": 118900,
            "A2": 97150,
        },
        "affected_permit_count": 2410,
        "annual_cost_savings_cents": 14500000,
        "measure_life_years": 12,
    }
    payload.update(overrides)
    return payload


def create_energy_impact_analysis_payload(
    expected_proposal_version: int, **overrides
) -> dict:
    payload = {
        "expected_proposal_version": expected_proposal_version,
        "analysis_type": "ENERGY_IMPACT",
        "annual_energy_savings_kwh": 4250000,
        "energy_delta_pct": -6.5,
    }
    payload.update(overrides)
    return payload


def analysis_review_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Comment windows and comments (PRD §3.4)
# ---------------------------------------------------------------------------
def open_comment_window_payload(
    opens_at: str = "2026-08-10T00:00:00Z",
    closes_at: str = "2026-09-09T00:00:00Z",
    **overrides,
) -> dict:
    payload = {"action": "OPEN", "opens_at": opens_at, "closes_at": closes_at}
    payload.update(overrides)
    return payload


def comment_window_action_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_public_comment_payload(
    commenter_sector: str = "INDUSTRY",
    position: str = "SUPPORT",
    body: str = "Aligns with our product roadmap.",
    **overrides,
) -> dict:
    payload = {
        "commenter_sector": commenter_sector,
        "position": position,
        "body": body,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hearings and votes (PRD §3.5)
# ---------------------------------------------------------------------------
def create_hearing_payload(
    committee_id: str,
    scheduled_start: str = "2026-10-05T14:00:00Z",
    scheduled_end: str = "2026-10-05T17:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "committee_id": committee_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def agenda_payload(mode: str = "AUTO_FILL", **overrides) -> dict:
    payload = {"mode": mode}
    payload.update(overrides)
    return payload


def convene_payload(present_member_ids: list, **overrides) -> dict:
    payload = {"present_member_ids": list(present_member_ids)}
    payload.update(overrides)
    return payload


def ballot(member_id: str, choice: str) -> dict:
    """One entry of the `ballots` array: a `member_id` and that member's `ballot`."""
    return {"member_id": member_id, "ballot": choice}


def vote_payload(proposal_id: str, ballots: list, **overrides) -> dict:
    payload = {"proposal_id": proposal_id, "ballots": list(ballots)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Adoption rules (PRD §3.7)
# ---------------------------------------------------------------------------
def create_adoption_rule_payload(
    code_cycle_id: str, title: str = "2027 State Code Adoption Order", **overrides
) -> dict:
    payload = {"code_cycle_id": code_cycle_id, "title": title}
    payload.update(overrides)
    return payload


def adoption_rule_status_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Jurisdictions and local amendments (PRD §3.8)
# ---------------------------------------------------------------------------
def create_jurisdiction_payload(
    name: str = "Riverbend",
    population: int = 1200000,
    local_authority_level: str = "FULL",
    host_seat_capacity: int = 60,
    official_headcount: int = 5,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "population": population,
        "local_authority_level": local_authority_level,
        "host_seat_capacity": host_seat_capacity,
        "official_headcount": official_headcount,
    }
    payload.update(overrides)
    return payload


def create_local_amendment_payload(
    expected_jurisdiction_version: int,
    jurisdiction_id: str,
    adoption_rule_id: str,
    code_section: str = "C402.1.4",
    local_text: str = "Riverbend requires an additional 5 percent envelope improvement.",
    stringency_direction: str = "MORE_STRINGENT",
    justification: str = "Local climate study.",
    **overrides,
) -> dict:
    payload = {
        "expected_jurisdiction_version": expected_jurisdiction_version,
        "jurisdiction_id": jurisdiction_id,
        "adoption_rule_id": adoption_rule_id,
        "code_section": code_section,
        "local_text": local_text,
        "stringency_direction": stringency_direction,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


def local_amendment_review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_local_amendment_payload(
    local_text: str = "Riverbend restates the envelope requirement.",
    stringency_direction: str = "MORE_STRINGENT",
    justification: str = "Revised local climate study.",
    **overrides,
) -> dict:
    payload = {
        "local_text": local_text,
        "stringency_direction": stringency_direction,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interpretation requests (PRD §3.8)
# ---------------------------------------------------------------------------
def create_interpretation_request_payload(
    adoption_rule_id: str,
    code_section: str = "C402.1.4",
    question: str = (
        "Does the tightened U-factor apply to an addition under 500 square feet?"
    ),
    **overrides,
) -> dict:
    payload = {
        "adoption_rule_id": adoption_rule_id,
        "code_section": code_section,
        "question": question,
    }
    payload.update(overrides)
    return payload


def interpretation_action_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Training (PRD §3.9)
# ---------------------------------------------------------------------------
def create_training_session_payload(
    adoption_rule_id: str,
    host_jurisdiction_id: str,
    discipline: str = "ENERGY",
    audience: str = "BUILDING_OFFICIAL",
    seat_capacity: int = TEST_DEFAULTS["SEAT_CAPACITY"],
    starts_at: str = "2027-01-10T09:00:00Z",
    ends_at: str = "2027-01-10T17:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "adoption_rule_id": adoption_rule_id,
        "host_jurisdiction_id": host_jurisdiction_id,
        "discipline": discipline,
        "audience": audience,
        "seat_capacity": seat_capacity,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def training_session_status_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def create_training_enrollment_payload(
    jurisdiction_id: str,
    attendee_name: str,
    attendee_role: str = "BUILDING_OFFICIAL",
    **overrides,
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "attendee_name": attendee_name,
        "attendee_role": attendee_role,
    }
    payload.update(overrides)
    return payload


def attendance_record(enrollment_id: str, outcome: str) -> dict:
    """One entry of the `records` array: an `enrollment_id` and that attendee's
    `outcome` of either ATTENDED or NO_SHOW."""
    return {"enrollment_id": enrollment_id, "outcome": outcome}


def attendance_payload(records: list, **overrides) -> dict:
    payload = {"records": list(records)}
    payload.update(overrides)
    return payload
