"""Operator identities for the five roles of PRD §2.1.

PRD §2.1: "Every request carries two headers: `X-User-Id` identifying the
operator and `X-User-Role` naming one of five roles."  No role is backed by a
stored entity, so an identity is simply an opaque operator id paired with a role
name.  Several workflows compare the acting operator against a recorded
identity — counter acceptance against `Reservation.booked_by_agent_id`,
investigation against `AnimalIncident.reported_by_user_id`, closure against
`AnimalIncident.investigated_by_user_id` — so the helpers below make it easy to
mint as many distinct operators per role as a scenario needs.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

PROGRAM_ADMIN = "ProgramAdmin"
RESERVATIONS_AGENT = "ReservationsAgent"
ACCEPTANCE_AGENT = "AcceptanceAgent"
VETERINARY_REVIEWER = "VeterinaryReviewer"
COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = [
    PROGRAM_ADMIN,
    RESERVATIONS_AGENT,
    ACCEPTANCE_AGENT,
    VETERINARY_REVIEWER,
    COMPLIANCE_OFFICER,
]

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": {"user_id": "admin-01", "role": PROGRAM_ADMIN},
    "reservations_agent": {"user_id": "agent-01", "role": RESERVATIONS_AGENT},
    "acceptance_agent": {"user_id": "accept-01", "role": ACCEPTANCE_AGENT},
    "veterinary_reviewer": {"user_id": "vet-01", "role": VETERINARY_REVIEWER},
    "compliance_officer": {"user_id": "officer-01", "role": COMPLIANCE_OFFICER},
}


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Build the two identity headers for an arbitrary operator id and role."""
    return build_user_headers(user_id, role)


def make_program_admin_headers(user_id: str = "admin-01") -> Dict[str, str]:
    return build_user_headers(user_id, PROGRAM_ADMIN)


def make_reservations_agent_headers(user_id: str = "agent-01") -> Dict[str, str]:
    return build_user_headers(user_id, RESERVATIONS_AGENT)


def make_acceptance_agent_headers(user_id: str = "accept-01") -> Dict[str, str]:
    return build_user_headers(user_id, ACCEPTANCE_AGENT)


def make_veterinary_reviewer_headers(user_id: str = "vet-01") -> Dict[str, str]:
    return build_user_headers(user_id, VETERINARY_REVIEWER)


def make_compliance_officer_headers(user_id: str = "officer-01") -> Dict[str, str]:
    return build_user_headers(user_id, COMPLIANCE_OFFICER)


# Canonical operator ids reused by the acceptance workflow scenarios.  The
# reservation booker and the accepting agent must differ because PRD §2.11 bars
# the booking agent from accepting its own reservation.
PROGRAM_ADMIN_ID = "admin-01"
BOOKING_AGENT_ID = "agent-01"
SECOND_BOOKING_AGENT_ID = "agent-02"
ACCEPTANCE_AGENT_ID = "accept-01"
SECOND_ACCEPTANCE_AGENT_ID = "accept-02"
THIRD_ACCEPTANCE_AGENT_ID = "accept-03"
VETERINARY_REVIEWER_ID = "vet-01"
SECOND_VETERINARY_REVIEWER_ID = "vet-02"
COMPLIANCE_OFFICER_ID = "officer-01"
SECOND_COMPLIANCE_OFFICER_ID = "officer-02"

__all__ = [
    "PROGRAM_ADMIN",
    "RESERVATIONS_AGENT",
    "ACCEPTANCE_AGENT",
    "VETERINARY_REVIEWER",
    "COMPLIANCE_OFFICER",
    "ALL_ROLES",
    "TEST_USERS",
    "headers_for",
    "make_program_admin_headers",
    "make_reservations_agent_headers",
    "make_acceptance_agent_headers",
    "make_veterinary_reviewer_headers",
    "make_compliance_officer_headers",
    "PROGRAM_ADMIN_ID",
    "BOOKING_AGENT_ID",
    "SECOND_BOOKING_AGENT_ID",
    "ACCEPTANCE_AGENT_ID",
    "SECOND_ACCEPTANCE_AGENT_ID",
    "THIRD_ACCEPTANCE_AGENT_ID",
    "VETERINARY_REVIEWER_ID",
    "SECOND_VETERINARY_REVIEWER_ID",
    "COMPLIANCE_OFFICER_ID",
    "SECOND_COMPLIANCE_OFFICER_ID",
]
