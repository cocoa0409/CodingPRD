"""Ladder rungs 1-5: authentication, role recognition, endpoint authorisation,
entity-backed identity resolution and ownership (PRD 2.1)."""

from flask import request

from errors import ApiError
from store import DB
from validation import ROLES

OPAQUE_ROLES = (
    "PlatformAdmin", "IntakeOfficer", "FosterCoordinator", "AdoptionCounselor",
    "TransportDispatcher", "Veterinarian", "FinanceOfficer",
)

# PRD 2.1: "when `X-User-Role` is `Driver`, `FosterParent` or `Adopter`,
# `X-User-ID` is the `id` of the acting `Person`; when it is `PartnerRescue`,
# `X-User-ID` is the `id` of the acting `Organization`."
ENTITY_BACKED = {
    "Driver": "Person",
    "FosterParent": "Person",
    "Adopter": "Person",
    "PartnerRescue": "Organization",
}


class Ctx(object):
    __slots__ = ("user_id", "role", "actor")

    def __init__(self, user_id, role, actor):
        self.user_id = user_id
        self.role = role
        self.actor = actor

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED


def authenticate(allowed_roles):
    """Rungs 1-4."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # Rung 1: both headers present and non-empty.
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both X-User-ID and X-User-Role are required and must be non-empty.")

    # Rung 2: the role names one of the eleven roles.  PRD 2.1: "an unrecognised
    # role is treated as a failure to authenticate, not as a permission problem".
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role names an unrecognised role.")

    # Rung 3: the acting role appears on the endpoint's authorised list.
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not authorised for this endpoint." % role)

    # Rung 4: an entity-backed actor's X-User-ID resolves to a row of its
    # backing entity.
    #
    # Adjudication of friction 2: Reading A -- rung 4 emits ERR_PERSON_NOT_FOUND
    # for EVERY entity-backed role, including PartnerRescue whose backing entity
    # is Organization.  Both readings leave every declared behaviour reachable
    # (ERR_ORGANIZATION_NOT_FOUND is still produced by every /organizations/{id}
    # path lookup, ERR_PERSON_NOT_FOUND by every person FK), so the tie is
    # broken by the literal text, which states this code twice: PRD 2.1 "If that
    # lookup fails, the request is rejected with ERR_PERSON_NOT_FOUND (HTTP 404)"
    # -- a sentence that governs all four entity-backed roles -- and PRD 2.5
    # rung 4 "otherwise ERR_PERSON_NOT_FOUND".
    actor = None
    if role in ENTITY_BACKED:
        actor = DB.get(ENTITY_BACKED[role], user_id)
        if actor is None:
            raise ApiError("ERR_PERSON_NOT_FOUND",
                           "X-User-ID does not resolve to an acting %s." % ENTITY_BACKED[role])

    return Ctx(user_id, role, actor)


def own(ctx, owner_id):
    """Rung 5: an entity-backed actor may only act on resources it owns.

    Called only once the resource has been fetched; a resource that does not
    exist cannot fail an ownership comparison, so the request falls through to
    rung 10/11 and reports the not-found code from the PRD 2.11 map instead.
    """
    if not ctx.entity_backed:
        return
    if owner_id != ctx.user_id:
        raise ApiError("ERR_UNAUTHORIZED", "This resource belongs to another actor.")


def own_if(ctx, role, owner_id):
    """Ownership comparison that applies only to one specific entity-backed role."""
    if ctx.role == role and owner_id != ctx.user_id:
        raise ApiError("ERR_UNAUTHORIZED", "This resource belongs to another actor.")
