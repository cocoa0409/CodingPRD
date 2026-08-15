"""IntegratorOrg and IntegratorUser endpoints (PRD §3.1)."""
from flask import Blueprint

from db import children, store
from errors import not_found
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SAFETY_LEAD as SL
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from middleware import ROLE_TRAINER as TR
from response import success, success_list
from services.domain import common_fields, pub, pubs
from validation import as_bool, as_enum, as_int, as_str, body, paginate, pagination, req

bp = Blueprint("orgs", __name__)

BRANDS = ("FANUC", "ABB", "DUAL")
PL_LEVELS = ("PLc", "PLd", "PLe")
USER_ROLES = (
    "PROJECT_ENGINEER", "SAFETY_LEAD", "CONTROLS_PROGRAMMER",
    "SITE_SUPERVISOR", "TRAINER", "SERVICE_MANAGER", "FINANCE_ADMIN",
)


def get_org(org_id):
    org = store.orgs.get(org_id)
    if org is None:
        raise not_found("Integrator org not found")
    return org


def get_user(user_id):
    user = store.users.get(user_id)
    if user is None:
        raise not_found("Integrator user not found")
    return user


@bp.post("/robotics/integrator-orgs")
def create_org():
    authenticate({FA})
    b = body()
    org = {
        **common_fields(),
        "legal_name": as_str(req(b, "legal_name"), "legal_name"),
        "brand_specialization": as_enum(req(b, "brand_specialization"), "brand_specialization", BRANDS),
        "retention_rate_bps": as_int(req(b, "retention_rate_bps"), "retention_rate_bps", 0, 2000),
        "default_pl_category_target": as_enum(req(b, "default_pl_category_target"), "default_pl_category_target", PL_LEVELS),
    }
    store.orgs[org["id"]] = org
    return success(pub(org), 201)


@bp.get("/robotics/integrator-orgs")
def list_orgs():
    authenticate({FA})
    limit, offset = pagination()
    items = sorted(store.orgs.values(), key=lambda e: e["_seq"])
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/integrator-orgs/<org_id>")
def get_one_org(org_id):
    authenticate()
    return success(pub(get_org(org_id)))


# ---------------------------------------------------------------- users
@bp.post("/robotics/integrator-orgs/<org_id>/users")
def create_user(org_id):
    authenticate({FA})
    get_org(org_id)
    b = body()
    user = {
        **common_fields(),
        "integrator_org_id": org_id,
        "display_name": as_str(req(b, "display_name"), "display_name"),
        "user_role": as_enum(req(b, "user_role"), "user_role", USER_ROLES),
        "active": as_bool(b["active"], "active") if "active" in b and b["active"] is not None else True,
    }
    store.users[user["id"]] = user
    return success(pub(user), 201)


@bp.get("/robotics/integrator-orgs/<org_id>/users")
def list_users(org_id):
    authenticate({FA, PE, SL, SS, SM})
    get_org(org_id)
    limit, offset = pagination()
    page, total = paginate(children("users", "integrator_org_id", org_id), limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/users/<user_id>")
def get_one_user(user_id):
    authenticate()
    return success(pub(get_user(user_id)))


@bp.get("/robotics/users/<user_id>/approved-safety-assessments")
def list_approved_assessments(user_id):
    authenticate({FA, PE, SL, SS, SM})
    get_user(user_id)
    limit, offset = pagination()
    items = children("assessments", "approved_by_safety_lead_id", user_id)
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/users/<user_id>/recorded-acceptance-tests")
def list_recorded_tests(user_id):
    authenticate({FA, PE, SS, SM})
    get_user(user_id)
    limit, offset = pagination()
    items = children("tests", "recorded_by_user_id", user_id)
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/users/<user_id>/training-sessions")
def list_trainer_sessions(user_id):
    authenticate({FA, PE, SS, TR})
    get_user(user_id)
    limit, offset = pagination()
    items = children("sessions", "trainer_user_id", user_id)
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)
