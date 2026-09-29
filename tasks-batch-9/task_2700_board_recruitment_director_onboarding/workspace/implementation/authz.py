"""Header presence, role authorisation and ownership (PRD 2.1, 2.10 steps 1-3)."""

from flask import request

from errors import fail

GOVERNANCE_STAFF = "GovernanceStaff"
CORPORATE_SECRETARY = "CorporateSecretary"
COMMITTEE_CHAIR = "CommitteeChair"
COMMITTEE_MEMBER = "CommitteeMember"
SEATED_DIRECTOR = "SeatedDirector"
SEARCH_FIRM_PARTNER = "SearchFirmPartner"

ALL_ROLES = (
    GOVERNANCE_STAFF,
    CORPORATE_SECRETARY,
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    SEATED_DIRECTOR,
    SEARCH_FIRM_PARTNER,
)

# roles whose X-User-ID is an entity id rather than an opaque operator id
DIRECTOR_BACKED = (COMMITTEE_CHAIR, COMMITTEE_MEMBER, SEATED_DIRECTOR)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_director_backed(self):
        return self.role in DIRECTOR_BACKED

    @property
    def is_firm_backed(self):
        return self.role == SEARCH_FIRM_PARTNER


def require(*allowed_roles):
    """Step 1 header presence, then step 2 role authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return Actor(user_id, role)


def require_director_owner(actor, director_id):
    """Ownership check for a director-owned resource (step 3)."""
    if actor.is_director_backed and director_id is not None:
        if actor.user_id != director_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "Acting director may only act on their own record.")


def require_firm_owner(actor, firm_id):
    if actor.is_firm_backed and firm_id is not None:
        if actor.user_id != firm_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "A search firm partner may only read their own firm.")
