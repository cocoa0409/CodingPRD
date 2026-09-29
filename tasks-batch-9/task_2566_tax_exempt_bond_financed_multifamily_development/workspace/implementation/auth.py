"""Header-driven authentication, the endpoint role registry and ownership.

Ladder positions implemented here (PRD section 2.7):
  rule 1  ERR_UNAUTHENTICATED
  rule 2  ERR_FORBIDDEN_ROLE
  rule 3  ERR_NOT_RESOURCE_OWNER
"""

from flask import request

from errors import fail

DEVELOPER = "Developer"
INVESTOR = "Investor"
HFA_ALLOC = "HfaAllocationOfficer"
HFA_COMPL = "HfaComplianceOfficer"
TRUSTEE = "BondTrustee"
SYSOP = "SystemOperator"

ALL_ROLES = (DEVELOPER, INVESTOR, HFA_ALLOC, HFA_COMPL, TRUSTEE, SYSOP)

# Roles that are backed by a stored entity, so X-User-ID is always required.
ENTITY_BACKED_ROLES = (DEVELOPER, INVESTOR)

# endpoint key -> authorized roles
ENDPOINT_ROLES = {
    # ---- single reads ----
    "GET /developers/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL, TRUSTEE),
    "GET /investors/{id}": (INVESTOR, HFA_ALLOC, HFA_COMPL),
    "GET /cap-pools/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /projects/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL, TRUSTEE),
    "GET /volume-cap-allocations/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /bond-issues/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL, TRUSTEE),
    "GET /draw-requests/{id}": (DEVELOPER, HFA_ALLOC, TRUSTEE),
    "GET /unit-restrictions/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /regulatory-agreements/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /cost-certifications/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /credit-allocations/{id}": (DEVELOPER, INVESTOR, HFA_ALLOC, HFA_COMPL),
    "GET /investor-deliveries/{id}": (DEVELOPER, INVESTOR, HFA_ALLOC),
    "GET /compliance-reports/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /physical-inspections/{id}": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    # ---- list reads ----
    "GET /projects": (DEVELOPER, HFA_ALLOC, HFA_COMPL, TRUSTEE),
    "GET /volume-cap-allocations": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /bond-issues": (DEVELOPER, HFA_ALLOC, HFA_COMPL, TRUSTEE),
    "GET /draw-requests": (DEVELOPER, HFA_ALLOC, TRUSTEE),
    "GET /unit-restrictions": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /regulatory-agreements": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /cost-certifications": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /credit-allocations": (DEVELOPER, INVESTOR, HFA_ALLOC, HFA_COMPL),
    "GET /investor-deliveries": (DEVELOPER, INVESTOR, HFA_ALLOC),
    "GET /compliance-reports": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    "GET /physical-inspections": (DEVELOPER, HFA_ALLOC, HFA_COMPL),
    # ---- onboarding writes ----
    "POST /developers": (HFA_ALLOC,),
    "POST /developers/{id}/sanctions": (HFA_COMPL,),
    "POST /investors": (HFA_ALLOC,),
    "POST /cap-pools": (HFA_ALLOC,),
    "POST /projects": (DEVELOPER,),
    # ---- units ----
    "POST /unit-restrictions": (DEVELOPER,),
    "PATCH /unit-restrictions/{id}": (DEVELOPER,),
    # ---- volume cap ----
    "POST /volume-cap-allocations": (DEVELOPER,),
    "POST /volume-cap-allocations/{id}/decision": (HFA_ALLOC,),
    "POST /volume-cap-allocations/{id}/return": (DEVELOPER,),
    "POST /volume-cap-allocations/{id}/revise": (DEVELOPER,),
    # ---- regulatory agreement ----
    "POST /regulatory-agreements": (DEVELOPER,),
    "POST /regulatory-agreements/{id}/record": (HFA_COMPL,),
    "POST /regulatory-agreements/{id}/amend": (HFA_COMPL,),
    # ---- bonds ----
    "POST /bond-issues": (DEVELOPER,),
    "POST /bond-issues/{id}/issue": (TRUSTEE,),
    "POST /bond-issues/{id}/operating-months": (DEVELOPER,),
    "POST /bond-issues/{id}/convert": (TRUSTEE,),
    "POST /bond-issues/{id}/mandatory-redeem": (TRUSTEE,),
    # ---- draws ----
    "POST /draw-requests": (DEVELOPER,),
    "POST /draw-requests/{id}/decision": (TRUSTEE,),
    "POST /draw-requests/{id}/fund": (TRUSTEE,),
    "POST /draw-requests/{id}/void": (TRUSTEE,),
    # ---- cost certification, credit, delivery ----
    "POST /cost-certifications": (DEVELOPER,),
    "POST /cost-certifications/{id}/submit": (DEVELOPER,),
    "POST /cost-certifications/{id}/review": (HFA_ALLOC,),
    "POST /credit-allocations": (HFA_ALLOC,),
    "POST /credit-allocations/{id}/issue": (HFA_ALLOC,),
    "POST /investor-deliveries": (DEVELOPER,),
    "POST /investor-deliveries/{id}/accept": (INVESTOR,),
    "POST /investor-deliveries/{id}/rescind": (DEVELOPER,),
    # ---- compliance ----
    "POST /compliance-reports": (DEVELOPER,),
    "POST /compliance-reports/{id}/review": (HFA_COMPL,),
    "POST /physical-inspections": (HFA_COMPL,),
    "POST /physical-inspections/{id}/complete": (HFA_COMPL,),
    # ---- clock ----
    "POST /_clock/set_current_utc": (SYSOP,),
}

# Endpoints that record the acting operator on a row; these need X-User-ID even
# for the opaque operator roles.
ACTOR_RECORDING = frozenset((
    "POST /volume-cap-allocations/{id}/decision",
    "POST /cost-certifications/{id}/review",
    "POST /credit-allocations",
    "POST /credit-allocations/{id}/issue",
    "POST /compliance-reports/{id}/review",
))


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_developer(self):
        return self.role == DEVELOPER

    @property
    def is_investor(self):
        return self.role == INVESTOR


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def guard(endpoint_key):
    """Rules 1 and 2 of the ladder.  Returns the Caller."""
    role = _header("X-User-Role")
    if role is None:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    user_id = _header("X-User-ID")
    if user_id is None and (role in ENTITY_BACKED_ROLES or endpoint_key in ACTOR_RECORDING):
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")

    allowed = ENDPOINT_ROLES.get(endpoint_key, ())
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role '%s' may not call this endpoint." % role)
    return Caller(role, user_id)


def own_project(caller, project):
    """Rule 3 for a developer-scoped target.  A missing target defers to the 404."""
    if project is None:
        return
    if caller.is_developer and project.get("developer_id") != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this development.")


def own_developer(caller, developer):
    if developer is None:
        return
    if caller.is_developer and developer.get("id") != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this sponsor record.")


def own_investor(caller, investor):
    if investor is None:
        return
    if caller.is_investor and investor.get("id") != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this investor record.")


def own_delivery(caller, delivery, project=None):
    """Investor callers own by investor_id; developer callers by the project."""
    if delivery is None:
        return
    if caller.is_investor and delivery.get("investor_id") != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this delivery.")
    own_project(caller, project)
