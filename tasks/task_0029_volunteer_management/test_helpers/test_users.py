"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes role identities as follows:

- Volunteer: entity_backed on Volunteer. PRD §2.1 says "When X-User-Role
  is `Volunteer`, X-User-ID is the `id` of the acting `Volunteer`;
  ownership checks on any resource that references a `Volunteer` (for
  example `Application.volunteer_id`, `RedemptionOrder.volunteer_id`, or
  `VolunteerSkill.volunteer_id`) compare the resource's foreign-key field
  to `X-User-ID` and reject mismatches with `ERR_FORBIDDEN`."

- Organizer: also entity_backed on Volunteer (an Organizer is itself a
  verified Volunteer row). PRD §2.1 says "When X-User-Role is
  `Organizer`, X-User-ID is likewise the `id` of an acting `Volunteer`
  row (an organizer is itself a verified volunteer); ownership checks on
  activities compare `Activity.organizer_id` to `X-User-ID`."

- SkillAdmin: opaque. PRD §2.1 says "When X-User-Role is `SkillAdmin`,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity."

For Volunteer and Organizer, ownership-gated calls MUST use
make_volunteer_headers(volunteer["id"]) or
make_organizer_headers(volunteer["id"]) where the id is the actual
Volunteer.id (because Activity.organizer_id and Application.volunteer_id
are compared byte-equal to X-User-ID). The shared TEST_USERS constants
exist only as a fallback for tests whose success does NOT depend on
ownership comparison (e.g., ERR_INVALID_INPUT on bad payload,
ERR_NOT_FOUND on missing resource, ERR_FORBIDDEN where the role itself
is rejected before identity check).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque SkillAdmin role; for Volunteer
# and Organizer these are FALLBACK headers usable only when the test does
# NOT exercise an ownership comparison.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — shared constant is canonical (PRD §2.1).
    "skilladmin_headers": build_user_headers("skilladmin-001", "SkillAdmin"),
    "skilladmin_headers_alt": build_user_headers("skilladmin-002", "SkillAdmin"),

    # Entity-backed roles — fallback only for non-ownership tests.
    "volunteer_headers": build_user_headers("volunteer-fallback-001", "Volunteer"),
    "organizer_headers": build_user_headers("organizer-fallback-001", "Organizer"),
}


# --- Per-instance builders for entity-backed roles ---------------------------
# Each builder threads the actual Volunteer.id through X-User-ID so that
# ownership comparisons (PRD §2.1) succeed for real-world flows.

def make_volunteer_headers(volunteer_id: str) -> Dict[str, str]:
    """Volunteer headers. PRD §2.1: 'When X-User-Role is Volunteer,
    X-User-ID is the id of the acting Volunteer; ownership checks on any
    resource that references a Volunteer (for example
    Application.volunteer_id, RedemptionOrder.volunteer_id, or
    VolunteerSkill.volunteer_id) compare the resource's foreign-key field
    to X-User-ID and reject mismatches with ERR_FORBIDDEN.'

    Pass the actual Volunteer.id whenever the request is ownership-gated.
    """
    return build_user_headers(volunteer_id, "Volunteer")


def make_organizer_headers(volunteer_id: str) -> Dict[str, str]:
    """Organizer headers. PRD §2.1: 'When X-User-Role is Organizer,
    X-User-ID is likewise the id of an acting Volunteer row (an organizer
    is itself a verified volunteer); ownership checks on activities
    compare Activity.organizer_id to X-User-ID.'

    Pass the Volunteer.id of the organizer whenever the request is
    ownership-gated (e.g., /activities/{id}/submit, .../approve,
    .../reject of an Application, /hour-adjustments).
    """
    return build_user_headers(volunteer_id, "Organizer")


def make_skilladmin_headers(operator_id: str = "skilladmin-001") -> Dict[str, str]:
    """SkillAdmin headers. PRD §2.1: identity is opaque — server may
    record the value (e.g., as reviewer_id, approver_id) but does not
    compare it to any entity id for ownership purposes. Optional
    operator_id allows two distinct SkillAdmin operators (e.g., for
    HourAdjustment race tests where two SkillAdmins approve/reject
    simultaneously).
    """
    return build_user_headers(operator_id, "SkillAdmin")


__all__ = [
    "TEST_USERS",
    "make_volunteer_headers",
    "make_organizer_headers",
    "make_skilladmin_headers",
]
