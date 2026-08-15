from flask import Blueprint, request

import response
from db import store, new_rec, touch, serialize
from errors import (
    ApiError,
    ERR_NOT_ASSIGNED_APPRAISER,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_APPROACH,
    ERR_INCOME_DATA_MISSING,
    ERR_COMPARABLES_INSUFFICIENT,
    ERR_DCF_INCOMPLETE,
    ERR_CAP_RATE_UNSUPPORTED,
    ERR_COST_INPUTS_INCOMPLETE,
)
from middleware import (
    auth,
    require_role,
    get_body,
    req_enum,
    req_int,
    opt_int,
    req_num,
    opt_num,
)
from response import sort_by_creation
from services import calc, domain

bp = Blueprint("approaches", __name__)

APPROACH_TYPES = ("INCOME", "SALES_COMPARISON", "COST")
DCF_FIELDS = (
    "dcf_holding_period_years",
    "dcf_discount_rate_bps",
    "dcf_exit_cap_bps",
    "revenue_growth_bps_annual",
)


@bp.post("/engagements/<engagementId>/approaches")
def create_approach(engagementId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    eng = domain.get_engagement(engagementId)
    body = get_body()
    approach_type = req_enum(body, "approach_type", APPROACH_TYPES)
    weight_pct = req_num(body, "weight_pct", minimum=0, maximum=100)
    cap_rate_bps = opt_int(body, "cap_rate_bps")
    dcf_holding_period_years = opt_int(body, "dcf_holding_period_years", minimum=1)
    dcf_discount_rate_bps = opt_int(body, "dcf_discount_rate_bps", minimum=1)
    dcf_exit_cap_bps = opt_int(body, "dcf_exit_cap_bps", minimum=1)
    revenue_growth_bps_annual = opt_int(body, "revenue_growth_bps_annual")
    land_value_cents = opt_int(body, "land_value_cents", minimum=0)
    replacement_cost_cents = opt_int(body, "replacement_cost_cents", minimum=0)
    depreciation_pct = opt_num(body, "depreciation_pct", minimum=0, maximum=100)
    if approach_type == "INCOME" and cap_rate_bps is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "cap_rate_bps is required for INCOME"
        )
    if cap_rate_bps is not None and cap_rate_bps <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cap_rate_bps must be positive")
    # Priority 6: author ownership.
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    # Priority 8: engagement state.
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    # Priority 11: approach_type unique per engagement.
    for other in store.approaches.values():
        if (
            other["engagement_id"] == eng["id"]
            and other["approach_type"] == approach_type
        ):
            raise ApiError(
                ERR_DUPLICATE_APPROACH,
                409,
                "An approach with this approach_type already exists on the engagement",
            )
    rec = new_rec(
        {
            "engagement_id": eng["id"],
            "approach_type": approach_type,
            "cap_rate_bps": cap_rate_bps,
            "dcf_holding_period_years": dcf_holding_period_years,
            "dcf_discount_rate_bps": dcf_discount_rate_bps,
            "dcf_exit_cap_bps": dcf_exit_cap_bps,
            "revenue_growth_bps_annual": revenue_growth_bps_annual,
            "land_value_cents": land_value_cents,
            "replacement_cost_cents": replacement_cost_cents,
            "depreciation_pct": depreciation_pct,
            "indicated_value_cents": None,
            "weight_pct": weight_pct,
            "status": "SELECTED",
        }
    )
    store.approaches[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/approaches/<approachId>")
def get_approach(approachId):
    auth()
    rec = domain.get_approach(approachId)
    return response.success(serialize(rec))


@bp.get("/approaches")
def list_approaches():
    auth()
    items = list(store.approaches.values())
    for field in ("engagement_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


def _author_context(rec, uid):
    eng = domain.engagement_of(rec)
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    return eng


@bp.post("/approaches/<approachId>/complete")
def complete_approach(approachId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    ap = domain.get_approach(approachId)
    eng = _author_context(ap, uid)
    if ap["status"] != "SELECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Approach is not in SELECTED")
    subs = [s for s in store.submissions.values() if s["engagement_id"] == eng["id"]]
    comps = [c for c in store.comparables.values() if c["engagement_id"] == eng["id"]]
    atype = ap["approach_type"]
    if atype == "INCOME":
        stmt = calc.evidence_statement(subs)
        if stmt is None:
            raise ApiError(
                ERR_INCOME_DATA_MISSING,
                409,
                "INCOME completion requires an ACCEPTED OPERATING_STATEMENT",
            )
        supported = calc.supported_cap_rate_bps(comps)
        if supported is None:
            raise ApiError(
                ERR_COMPARABLES_INSUFFICIENT,
                409,
                "INCOME completion requires a selected_for_support comparable",
            )
        dcf_present = [f for f in DCF_FIELDS if ap[f] is not None]
        if dcf_present and len(dcf_present) != 4:
            raise ApiError(
                ERR_DCF_INCOMPLETE,
                409,
                "DCF assumptions are all-or-none",
            )
        if abs(ap["cap_rate_bps"] - supported) > calc.SUPPORT_TOLERANCE_BPS:
            raise ApiError(
                ERR_CAP_RATE_UNSUPPORTED,
                409,
                "cap_rate_bps is outside the 25 bps support tolerance",
            )
        if len(dcf_present) == 4:
            ap["indicated_value_cents"] = calc.dcf_value(stmt, ap)
        else:
            ap["indicated_value_cents"] = calc.direct_cap_value(
                stmt, ap["cap_rate_bps"]
            )
    elif atype == "SALES_COMPARISON":
        if not any(c["selected_for_support"] for c in comps):
            raise ApiError(
                ERR_COMPARABLES_INSUFFICIENT,
                409,
                "SALES_COMPARISON completion requires a selected_for_support comparable",
            )
        ap["indicated_value_cents"] = calc.sales_comparison_value(
            comps, eng["building_sf"]
        )
    else:  # COST
        if (
            ap["land_value_cents"] is None
            or ap["replacement_cost_cents"] is None
            or ap["depreciation_pct"] is None
        ):
            raise ApiError(
                ERR_COST_INPUTS_INCOMPLETE,
                409,
                "COST completion requires land_value_cents, replacement_cost_cents and depreciation_pct",
            )
        ap["indicated_value_cents"] = calc.cost_approach_value(ap)
    ap["status"] = "COMPLETE"
    touch(ap)
    return response.success(serialize(ap))


@bp.post("/approaches/<approachId>/exclude")
def exclude_approach(approachId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    ap = domain.get_approach(approachId)
    _author_context(ap, uid)
    if ap["status"] != "COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409, "Approach is not in COMPLETE")
    ap["status"] = "EXCLUDED"
    touch(ap)
    return response.success(serialize(ap))


@bp.post("/approaches/<approachId>/include")
def include_approach(approachId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    ap = domain.get_approach(approachId)
    _author_context(ap, uid)
    if ap["status"] != "EXCLUDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Approach is not in EXCLUDED")
    ap["status"] = "COMPLETE"
    touch(ap)
    return response.success(serialize(ap))
