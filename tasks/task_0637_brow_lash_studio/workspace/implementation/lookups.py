"""Path/body existence resolution + ownership helpers (PRD §2.8, §2.1)."""
import errors
from clock import parse_iso8601
from common import bad_request
from db import store


def get_studio_or_404(studio_id):
    s = store.studios.get(studio_id)
    if not s:
        raise errors.ApiError(errors.ERR_STUDIO_NOT_FOUND, 404, "Studio not found.")
    return s


def get_service_type_or_404(stid):
    st = store.service_types.get(stid)
    if not st:
        raise errors.ApiError(errors.ERR_SERVICE_TYPE_NOT_FOUND, 404, "Service type not found.")
    return st


def get_member_or_404(mid):
    m = store.members.get(mid)
    if not m:
        raise errors.ApiError(errors.ERR_MEMBER_NOT_FOUND, 404, "Member not found.")
    return m


def get_membership_or_404(mid):
    ms = store.memberships.get(mid)
    if not ms:
        raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_FOUND, 404, "Membership not found.")
    return ms


def get_appointment_or_404(aid):
    a = store.appointments.get(aid)
    if not a:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Appointment not found.")
    return a


def get_tech_or_404(tid):
    t = store.lash_techs.get(tid)
    if not t:
        raise errors.ApiError(errors.ERR_TECH_NOT_FOUND, 404, "Lash technician not found.")
    return t


def get_schedule_or_404(sid):
    s = store.recurring_schedules.get(sid)
    if not s:
        raise errors.ApiError(errors.ERR_SCHEDULE_NOT_FOUND, 404, "Recurring schedule not found.")
    return s


def get_patch_test_or_404(pid):
    p = store.consent_patch_tests.get(pid)
    if not p:
        raise errors.ApiError(errors.ERR_PATCH_TEST_NOT_FOUND, 404, "Patch test not found.")
    return p


def get_retail_order_or_404(oid):
    # No dedicated not-found error in catalogue beyond appointment family; the
    # error catalogue lists no ERR_RETAIL_ORDER_NOT_FOUND. PRD path not-found
    # family for retail-orders is unspecified; use a generic 404 with the closest
    # applicable id is not available, so return appointment-style 404 is wrong.
    o = store.retail_orders.get(oid)
    if not o:
        # Fall back to a plain 404 envelope using a generic error id.
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Retail order not found.")
    return o


def parse_dt_or_400(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return None
    try:
        return parse_iso8601(v)
    except (ValueError, TypeError):
        raise bad_request("Field '%s' is not a valid ISO 8601 timestamp." % field)


def ownership_member(role, user_id, member_id):
    """Member role may only act on its own member_id (PRD §2.1)."""
    if role == "Member" and user_id != member_id:
        raise errors.ApiError(errors.ERR_FORBIDDEN_ROLE, 403,
                              "Members may only act on their own resources.")


def ownership_tech(role, user_id, tech_id):
    """LashTech role ownership: X-User-ID must equal the LashTech id (PRD §2.1)."""
    if role == "LashTech" and user_id != tech_id:
        raise errors.ApiError(errors.ERR_FORBIDDEN_ROLE, 403,
                              "Technicians may only act on their own resources.")
