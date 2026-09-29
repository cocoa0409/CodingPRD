"""Authentication, RBAC and ownership scope (ladder rungs 1-6) plus path lookups."""

from functools import wraps

from flask import g, request

from constants import ROLES
from errors import ApiError
from store import store


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None:
        role = request.headers.get("X-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header must name a known role.")
    return user_id, role


def require(*roles):
    """Ladder rung 1 (authentication) then rung 2 (role authorisation)."""
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = _authenticate()
            g.user_id = user_id
            g.role = role
            g.endpoint_roles = allowed
            if role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s is not permitted on this endpoint." % role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# rung 4 / rung 5 ownership scope
# ---------------------------------------------------------------------------
def check_facility_scope(facility_id):
    if g.role != "FacilityManager":
        return
    if "FacilityManager" not in g.endpoint_roles:
        return
    if facility_id is None:
        return
    if g.user_id != facility_id:
        raise ApiError(
            "ERR_FACILITY_SCOPE_VIOLATION",
            "This facility is outside the caller's scope.",
        )


def check_partner_scope(partner_ids):
    if g.role != "ServicePartnerTech":
        return
    if "ServicePartnerTech" not in g.endpoint_roles:
        return
    if not partner_ids:
        return
    if isinstance(partner_ids, str):
        partner_ids = {partner_ids}
    if g.user_id not in partner_ids:
        raise ApiError(
            "ERR_PARTNER_SCOPE_VIOLATION",
            "This service partner is outside the caller's scope.",
        )


def check_facility_filter(param="facility_id"):
    """List endpoints: a FacilityManager may not name another facility."""
    if g.role != "FacilityManager" or "FacilityManager" not in g.endpoint_roles:
        return
    value = request.args.get(param)
    if value is not None and value != g.user_id:
        raise ApiError(
            "ERR_FACILITY_SCOPE_VIOLATION",
            "This facility is outside the caller's scope.",
        )


def check_partner_filter(param="service_partner_id"):
    """List endpoints: a ServicePartnerTech may not name another partner."""
    if g.role != "ServicePartnerTech" or "ServicePartnerTech" not in g.endpoint_roles:
        return
    value = request.args.get(param)
    if value is not None and value != g.user_id:
        raise ApiError(
            "ERR_PARTNER_SCOPE_VIOLATION",
            "This service partner is outside the caller's scope.",
        )


def asset_servicing_partners(asset):
    """Partners delivering preventive maintenance at the asset's facility."""
    return {
        program["service_partner_id"]
        for program in store.pm_programs.values()
        if program["facility_id"] == asset["facility_id"]
        and program["status"] in ("ACTIVE", "NEEDS_REVISION")
    }


# ---------------------------------------------------------------------------
# rung 3 / rung 9 existence lookups
# ---------------------------------------------------------------------------
def _lookup(collection, entity_id, error_id):
    row = collection.get(entity_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_model(model_id):
    return _lookup(store.equipment_models, model_id, "ERR_MODEL_NOT_FOUND")


def get_revision(revision_id):
    return _lookup(store.model_revisions, revision_id, "ERR_REVISION_NOT_FOUND")


def get_rig(rig_id):
    return _lookup(store.test_rigs, rig_id, "ERR_TEST_RESOURCE_NOT_FOUND")


def get_run(run_id):
    return _lookup(store.test_runs, run_id, "ERR_TEST_RESOURCE_NOT_FOUND")


def get_release(release_id):
    return _lookup(store.firmware_releases, release_id, "ERR_FIRMWARE_NOT_FOUND")


def get_certification(cert_id):
    return _lookup(store.firmware_certifications, cert_id, "ERR_FIRMWARE_NOT_FOUND")


def get_facility(facility_id):
    return _lookup(store.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")


def get_order(order_id):
    return _lookup(store.orders, order_id, "ERR_ORDER_NOT_FOUND")


def get_order_line(line_id):
    return _lookup(store.order_lines, line_id, "ERR_ORDER_NOT_FOUND")


def get_partner(partner_id):
    return _lookup(store.service_partners, partner_id, "ERR_PARTNER_NOT_FOUND")


def get_install_job(job_id):
    return _lookup(store.install_jobs, job_id, "ERR_INSTALL_JOB_NOT_FOUND")


def get_asset(asset_id):
    return _lookup(store.serialized_assets, asset_id, "ERR_ASSET_NOT_FOUND")


def get_program(program_id):
    return _lookup(store.pm_programs, program_id, "ERR_SERVICE_PLAN_NOT_FOUND")


def get_visit(visit_id):
    return _lookup(store.maintenance_visits, visit_id, "ERR_SERVICE_PLAN_NOT_FOUND")
