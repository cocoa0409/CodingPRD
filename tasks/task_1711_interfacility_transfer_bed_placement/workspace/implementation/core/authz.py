"""Rungs 1 and 2 of the validation ladder (PRD 2.8).

Rung 1 -- user context: X-User-ID and X-User-Role headers must be present and
X-User-Role must name a declared role (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400).
Rung 2 -- role authorization: the role must be listed for the endpoint
(ERR_INSUFFICIENT_PERMISSIONS, 403).

Both rungs execute in a before_request hook, before any view runs its body
schema validation (rung 3).
"""

from flask import g, request

from .errors import fail

ROLES = (
    "TransferCoordinator",
    "SendingPhysician",
    "ReceivingPhysician",
    "BedManager",
    "QualityReviewer",
    "Any",
)

# Every declared role may read; all GET endpoints admit Any (PRD 2.1).
READ = list(ROLES)

# (METHOD, flask rule) -> the endpoint's authorized roles (PRD section 4).
ENDPOINT_ROLES = {
    ("POST", "/_clock/set_current_utc"): ["TransferCoordinator"],

    ("POST", "/facilities"): ["TransferCoordinator"],
    ("GET", "/facilities/<id>"): READ,
    ("GET", "/facilities/<id>/beds"): READ,
    ("GET", "/facilities/<id>/physicians"): READ,
    ("GET", "/facilities/<id>/diversion-events"): READ,
    ("POST", "/facilities/<id>/beds"): ["BedManager"],
    ("POST", "/facilities/<id>/diversion-events"): ["BedManager"],
    ("PUT", "/beds/<id>"): ["BedManager"],
    ("POST", "/diversion-events/<id>/lift"): ["BedManager"],

    ("POST", "/physicians"): ["TransferCoordinator"],

    ("POST", "/transfer-cases"): ["TransferCoordinator"],
    ("GET", "/transfer-cases"): READ,
    ("GET", "/transfer-cases/<id>"): READ,
    ("POST", "/transfer-cases/<id>/emtala-screening"): ["SendingPhysician"],
    ("GET", "/transfer-cases/<id>/emtala-screening"): READ,
    ("POST", "/transfer-cases/<id>/emtala-screening/certify"): ["SendingPhysician"],
    ("POST", "/transfer-cases/<id>/emtala-screening/amend"): ["SendingPhysician"],
    ("POST", "/transfer-cases/<id>/request-acceptance"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/re-request"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/accept"): ["ReceivingPhysician"],
    ("POST", "/transfer-cases/<id>/refuse"): ["ReceivingPhysician"],
    ("POST", "/transfer-cases/<id>/bed-holds"): ["BedManager"],
    ("POST", "/transfer-cases/<id>/dispatch"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/depart"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/arrive"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/complete"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/cancel"): ["TransferCoordinator"],
    ("GET", "/transfer-cases/<id>/outcome"): READ,
    ("POST", "/transfer-cases/<id>/insurance-notifications"): ["TransferCoordinator"],
    ("POST", "/transfer-cases/<id>/clinical-packet"): ["SendingPhysician"],

    ("GET", "/communications"): READ,
    ("GET", "/communications/<id>"): READ,

    ("GET", "/bed-holds"): READ,
    ("GET", "/bed-holds/<id>"): READ,
    ("POST", "/bed-holds/<id>/release"): ["BedManager"],

    ("GET", "/transport-dispatches"): READ,
    ("GET", "/transport-dispatches/<id>"): READ,
    ("POST", "/transport-dispatches/<id>/cancel"): ["TransferCoordinator"],

    ("GET", "/insurance-notifications"): READ,
    ("GET", "/insurance-notifications/<id>"): READ,
    ("POST", "/insurance-notifications/<id>/notify"): ["TransferCoordinator"],
    ("POST", "/insurance-notifications/<id>/claim-exception"): ["TransferCoordinator"],

    ("GET", "/clinical-packets"): READ,
    ("GET", "/clinical-packets/<id>"): READ,
    ("POST", "/clinical-packets/<id>/documents"): ["SendingPhysician"],
    ("POST", "/clinical-packets/<id>/imaging-exchange"): ["SendingPhysician"],

    ("GET", "/refusal-records"): READ,
    ("GET", "/refusal-records/<id>"): READ,

    ("GET", "/quality-reviews"): READ,
    ("GET", "/quality-reviews/<id>"): READ,
    ("POST", "/quality-reviews/<id>/begin"): ["QualityReviewer"],
    ("POST", "/quality-reviews/<id>/close"): ["QualityReviewer"],
}


def check_user_context():
    """Rung 1 of PRD 2.8, applies to every endpoint."""
    if request.method == "OPTIONS":
        return
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-ID header is required.", 400)
    if role is None or str(role).strip() == "":
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-Role header is required.", 400)
    if role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-Role must name a declared role.", 400)
    g.user_id = user_id
    g.role = role


def authorize():
    """Rung 2 of PRD 2.8: role membership for the target endpoint."""
    rule = request.url_rule
    if rule is None:
        return
    allowed = ENDPOINT_ROLES.get((request.method, rule.rule))
    if allowed is None:
        return
    if g.role not in allowed:
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "Role %s is not permitted on this endpoint." % g.role, 403)
