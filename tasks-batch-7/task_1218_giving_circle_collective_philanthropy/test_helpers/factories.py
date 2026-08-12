"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from . import constants

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def unique_email(prefix: str = "member") -> str:
    """Distinct, case-insensitively-unique email per call (PRD §3.2)."""
    return f"{prefix}.{_seq()}@example.org"


def unique_ein() -> str:
    """Distinct EIN per call (PRD §3.4 uniqueness rule)."""
    return f"99-{_seq():07d}"


def create_circle_payload(name: str = "Giving Circle", **overrides) -> dict:
    payload = {
        "name": name,
        "admin_fee_percent": constants.DEFAULT_ADMIN_FEE_PERCENT,
        "quorum_percent": constants.DEFAULT_QUORUM_PERCENT,
        "standard_minimum_cents": constants.DEFAULT_STANDARD_MINIMUM_CENTS,
        "leader_minimum_cents": constants.DEFAULT_LEADER_MINIMUM_CENTS,
        "operating_reserve_cents": constants.DEFAULT_OPERATING_RESERVE_CENTS,
        "vetting_profile": "BALANCED",
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(circle_id: str, year_label: str = "2026", **overrides) -> dict:
    payload = {"circle_id": circle_id, "year_label": year_label}
    payload.update(overrides)
    return payload


def create_member_payload(full_name: str = "Test Member", email: str = None) -> dict:
    return {"full_name": full_name, "email": email or unique_email("member")}


def create_membership_payload(member_id: str, circle_id: str, tier: str = "STANDARD") -> dict:
    return {"member_id": member_id, "circle_id": circle_id, "tier": tier}


def create_contribution_payload(cycle_id: str, membership_id: str, amount_cents: int) -> dict:
    return {
        "cycle_id": cycle_id,
        "membership_id": membership_id,
        "amount_cents": amount_cents,
    }


def create_nonprofit_payload(
    ein: str = None, legal_name: str = "Test Nonprofit", mission_category: str = "arts"
) -> dict:
    return {
        "ein": ein or unique_ein(),
        "legal_name": legal_name,
        "mission_category": mission_category,
    }


def create_nomination_payload(cycle_id: str, nonprofit_id: str, statement: str = "s") -> dict:
    return {"cycle_id": cycle_id, "nonprofit_id": nonprofit_id, "statement": statement}


def vetting_scores_payload(
    financial_health: int = 80, mission_alignment: int = 80, org_capacity: int = 80
) -> dict:
    return {
        "financial_health": financial_health,
        "mission_alignment": mission_alignment,
        "org_capacity": org_capacity,
    }


def create_site_visit_payload(
    nomination_id: str,
    starts_at: str = constants.VISIT_START_ISO,
    ends_at: str = constants.VISIT_END_ISO,
) -> dict:
    return {"nomination_id": nomination_id, "starts_at": starts_at, "ends_at": ends_at}


def create_learning_session_payload(
    cycle_id: str,
    title: str = "Session",
    starts_at: str = constants.VISIT_START_ISO,
    ends_at: str = constants.VISIT_END_ISO,
    capacity: int = 10,
) -> dict:
    return {
        "cycle_id": cycle_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }


def allocation(nomination_id: str, points: int) -> dict:
    return {"nomination_id": nomination_id, "points": points}


def create_ballot_payload(cycle_id: str, membership_id: str, allocations: list) -> dict:
    return {
        "cycle_id": cycle_id,
        "membership_id": membership_id,
        "allocations": allocations,
    }


def recast_ballot_payload(allocations: list, expected_ballot_version: int) -> dict:
    return {
        "allocations": allocations,
        "expected_ballot_version": expected_ballot_version,
    }


def submit_report_payload(narrative: str = "report", expenditure_cents: int = 10000) -> dict:
    return {"narrative": narrative, "expenditure_cents": expenditure_cents}


def reject_report_payload(reject_reason: str = "incomplete") -> dict:
    return {"reject_reason": reject_reason}


def create_rollover_decision_payload(
    source_cycle_id: str, mode: str, target_cycle_id: str = None
) -> dict:
    payload = {"source_cycle_id": source_cycle_id, "mode": mode}
    if target_cycle_id is not None:
        payload["target_cycle_id"] = target_cycle_id
    return payload
