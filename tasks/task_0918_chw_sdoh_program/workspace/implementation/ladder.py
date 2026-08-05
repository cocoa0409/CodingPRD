"""The single global 17-rung validation ladder (PRD §2.5).

Every request walks the rungs in numeric order and stops at the first failure.
Rungs 1-4 (authentication, role authorization, path existence and the
records-hold write gate) are built in and identical for every endpoint; rungs
5-17 are supplied by the handler as callables keyed by rung number and are
executed by this engine in rung order, never in handler order.
"""

from flask import request

import store
from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_PATIENT_NOT_FOUND,
    ERR_PATIENT_RECORDS_HOLD,
    ERR_REFERRAL_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)

CHW = "CHW"
SUPERVISOR = "Supervisor"
PROGRAM_ADMIN = "ProgramAdmin"
BILLING = "BillingSpecialist"
PARTNER = "ResourcePartner"

VALID_ROLES = (CHW, SUPERVISOR, PROGRAM_ADMIN, BILLING, PARTNER)
ALL_ROLES = list(VALID_ROLES)

# Entities that carry a patient reference, for gate-subject resolution step 3.
PATIENT_CARRYING = ("referral", "visit", "goal", "encounter", "claim", "escalation", "screening")

NOT_FOUND_FOR_KIND = {
    "patient": ERR_PATIENT_NOT_FOUND,
    "referral": ERR_REFERRAL_NOT_FOUND,
}


class Endpoint(object):
    """Declarative descriptor: roles, path ids and whether the gate applies."""

    def __init__(self, key, roles, path=(), gated=False):
        self.key = key
        self.roles = list(roles)
        self.path = list(path)          # ordered [(url_param_name, entity_kind)]
        self.gated = gated


class Ctx(object):
    def __init__(self, endpoint, user_id, role, body, args):
        self.endpoint = endpoint
        self.user_id = user_id
        self.role = role
        self.body = body
        self.args = args
        self.rows = {}                  # url_param_name -> resolved row
        self.gate_subject = None
        self.state = {}                 # handler scratch space

    def row(self, name):
        return self.rows.get(name)


def _read_body():
    """Parse the JSON body defensively; a malformed body behaves as empty."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:            # pragma: no cover - defensive
        data = None
    if isinstance(data, dict):
        return data
    return {}


def _rung1_authentication():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID header is required")
    if not role or not role.strip():
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role header is required")
    if role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role is not a recognized role")
    return user_id, role


def _rung2_authorization(ctx):
    if ctx.role not in ctx.endpoint.roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Role %s may not call this endpoint" % ctx.role)


def _rung3_path_existence(ctx, path_params):
    for name, kind in ctx.endpoint.path:
        row_id = path_params.get(name)
        row = store.get(kind, row_id)
        if row is None:
            raise ApiError(NOT_FOUND_FOR_KIND.get(kind, ERR_RESOURCE_NOT_FOUND),
                           "%s not found" % kind)
        ctx.rows[name] = row


def _resolve_gate_subject(ctx):
    """PRD §2.6 subject resolution, in its fixed order.  An unresolvable
    subject means the rung is skipped, never failed."""
    # 1. a patients-collection {id} segment
    for name, kind in ctx.endpoint.path:
        if kind == "patient":
            return ctx.rows.get(name)
    # 2. a patient_id in the request body
    if isinstance(ctx.body, dict) and "patient_id" in ctx.body:
        return store.get("patient", ctx.body.get("patient_id"))
    # 3. a path row that itself carries a patient reference
    for name, kind in ctx.endpoint.path:
        if kind in PATIENT_CARRYING:
            row = ctx.rows.get(name)
            if row is None:
                return None
            return store.get("patient", row.get("patient_id"))
    # 4. a grant charge line in the path, or an encounter_id in the body
    for name, kind in ctx.endpoint.path:
        if kind == "chargeline":
            line = ctx.rows.get(name)
            if line is None:
                return None
            encounter = store.get("encounter", line.get("encounter_id"))
            if encounter is None:
                return None
            return store.get("patient", encounter.get("patient_id"))
    if isinstance(ctx.body, dict) and "encounter_id" in ctx.body:
        encounter = store.get("encounter", ctx.body.get("encounter_id"))
        if encounter is None:
            return None
        return store.get("patient", encounter.get("patient_id"))
    # 5. no subject
    return None


def _rung4_write_gate(ctx):
    if not ctx.endpoint.gated:
        return
    subject = _resolve_gate_subject(ctx)
    ctx.gate_subject = subject
    if subject is not None and subject.get("gate_status") == "RECORDS_HOLD":
        raise ApiError(ERR_PATIENT_RECORDS_HOLD,
                       "Patient is on a records hold; writes are blocked")


def run(endpoint, path_params=None, steps=None):
    """Walk the whole ladder and return the request context."""
    path_params = path_params or {}
    steps = steps or {}

    user_id, role = _rung1_authentication()
    ctx = Ctx(endpoint, user_id, role, _read_body(), request.args)
    _rung2_authorization(ctx)
    _rung3_path_existence(ctx, path_params)
    _rung4_write_gate(ctx)

    for rung in range(5, 18):
        for check in steps.get(rung, ()):
            check(ctx)
    return ctx
