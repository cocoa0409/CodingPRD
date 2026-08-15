from flask import Blueprint, request

from db import store, new_entity, touch
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response
from serializers import department_view
from services.aggregates import active_fiscal_period_id, rederive_all_budget_postures
from validation import Payload, require_exists, list_page

bp = Blueprint("departments", __name__, url_prefix="/legal-ops/departments")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


def _check_thresholds(warn, crit, defl):
    if not (0 < warn <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "budget_warning_pct must be > 0 and <= 1.0")
    if not (0 < crit <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "budget_critical_pct must be > 0 and <= 1.0")
    if not (crit > warn):
        raise ApiError(ERR_INVALID_REQUEST, 400, "budget_critical_pct must be > budget_warning_pct")
    if not (0 <= defl <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "deflection_target_pct must be >= 0 and <= 1.0")


@bp.post("")
@require_roles("LegalOpsManager")
def create_department(user_id, role):
    p = Payload()
    name = p.req_str("name", min_len=1, max_len=200)
    warn = p.opt_num("budget_warning_pct")
    crit = p.opt_num("budget_critical_pct")
    defl = p.opt_num("deflection_target_pct")
    # Uniqueness (priority 10) runs before payload-shape 400s (priority 20).
    if name is not None:
        for d in store.departments.values():
            if d["name"] == name:
                raise ApiError(ERR_DUPLICATE, 409, "Department name already exists")
    p.finish()
    new_warn = 0.8 if warn is None else warn
    new_crit = 0.95 if crit is None else crit
    new_defl = 0.30 if defl is None else defl
    _check_thresholds(new_warn, new_crit, new_defl)
    dept = new_entity({
        "name": name,
        "budget_warning_pct": new_warn,
        "budget_critical_pct": new_crit,
        "deflection_target_pct": new_defl,
    })
    store.departments[dept["id"]] = dept
    return object_response(department_view(dept), 201)


@bp.get("")
@require_roles(*ALL)
def list_departments(user_id, role):
    items = list(store.departments.values())
    afp = request.args.get("active_fiscal_period_id")
    if afp is not None:
        items = [d for d in items if active_fiscal_period_id() == afp]
    return list_page(items, department_view)


@bp.get("/<dept_id>")
@require_roles(*ALL)
def get_department(user_id, role, dept_id):
    return object_response(department_view(require_exists(store.departments, dept_id, "department")))


@bp.patch("/<dept_id>")
@require_roles("LegalOpsManager")
def update_department(user_id, role, dept_id):
    dept = require_exists(store.departments, dept_id, "department")
    p = Payload()
    warn = p.opt_num("budget_warning_pct")
    crit = p.opt_num("budget_critical_pct")
    defl = p.opt_num("deflection_target_pct")
    p.finish()
    new_warn = dept["budget_warning_pct"] if warn is None else warn
    new_crit = dept["budget_critical_pct"] if crit is None else crit
    new_defl = dept["deflection_target_pct"] if defl is None else defl
    _check_thresholds(new_warn, new_crit, new_defl)
    changed = False
    if warn is not None and warn != dept["budget_warning_pct"]:
        dept["budget_warning_pct"] = warn
        changed = True
    if crit is not None and crit != dept["budget_critical_pct"]:
        dept["budget_critical_pct"] = crit
        changed = True
    if defl is not None and defl != dept["deflection_target_pct"]:
        dept["deflection_target_pct"] = defl
        changed = True
    if p.provided("budget_warning_pct") or p.provided("budget_critical_pct") or p.provided("deflection_target_pct"):
        dept["budget_warning_pct"] = new_warn
        dept["budget_critical_pct"] = new_crit
        dept["deflection_target_pct"] = new_defl
        touch(dept)
        # Threshold changes re-derive posture for every budget (PRD section 3.1).
        rederive_all_budget_postures()
    return object_response(department_view(dept))
