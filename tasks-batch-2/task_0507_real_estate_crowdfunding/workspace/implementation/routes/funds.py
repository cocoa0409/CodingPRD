"""Fund, Valuation, ShareClass, Project, Distribution-under-fund, and fund-scoped
list endpoints (PRD §3.1, §3.2, §3.6, §3.7)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_role, require_auth
from response import success, list_success
from services import calc, domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("funds", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


# ============================ FUNDS ============================
@bp.post("/funds")
def create_fund():
    require_role({"FundManager"})
    body = V.get_body()
    name = V.req_str(body, "name")
    vehicle_type = V.req_enum(body, "vehicle_type", {"REIT", "PARTNERSHIP"})
    gav = V.req_int(body, "gross_asset_value_cents", minimum=0)
    tl = V.req_int(body, "total_liabilities_cents", minimum=0)

    e = db.base_fields()
    e.update({
        "name": name,
        "vehicle_type": vehicle_type,
        "status": "OPEN",
        "gross_asset_value_cents": gav,
        "total_liabilities_cents": tl,
        "shares_outstanding": calc.round_shares(0),
        "nav_per_share_cents": calc.PAR_NAV_CENTS,
        "total_capital_cents": 0,
        "current_valuation_seq": 0,
    })
    db.funds[e["id"]] = e
    return success(serialize.fund(e), status=201)


@bp.get("/funds/<fund_id>")
def get_fund(fund_id):
    require_role(READ_ROLES)
    e = domain.get_fund(fund_id)
    return success(serialize.fund(e))


@bp.get("/funds")
def list_funds():
    require_role(READ_ROLES)
    limit, offset = get_pagination()
    page, total = order_and_page(list(db.funds.values()), limit, offset)
    return list_success([serialize.fund(e) for e in page], limit, offset, total)


@bp.post("/funds/<fund_id>/close-to-new")
def close_to_new(fund_id):
    require_role({"FundManager"})
    f = domain.get_fund(fund_id)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Fund is not OPEN")
    f["status"] = "CLOSED_TO_NEW"
    db.touch(f)
    return success(serialize.fund(f))


@bp.post("/funds/<fund_id>/wind-down")
def wind_down(fund_id):
    require_role({"FundManager"})
    f = domain.get_fund(fund_id)
    if f["status"] not in ("OPEN", "CLOSED_TO_NEW"):
        raise err("ERR_INVALID_STATE", "Fund cannot wind down from current state")

    f["status"] = "WINDING_DOWN"
    # Cascade: ShareClasses {OFFERING,SUSPENDED} -> CLOSED
    for sc in db.share_classes.values():
        if sc["fund_id"] == fund_id and sc["status"] in ("OFFERING", "SUSPENDED"):
            sc["status"] = "CLOSED"
            db.touch(sc)
    # Cascade: RedemptionRequests {QUEUED,DEFERRED} -> REJECTED
    sc_ids = domain.share_class_ids_of_fund(fund_id)
    holding_ids = {h["id"] for h in db.holdings.values() if h["share_class_id"] in sc_ids}
    for r in db.redemption_requests.values():
        if r["holding_id"] in holding_ids and r["status"] in ("QUEUED", "DEFERRED"):
            r["status"] = "REJECTED"
            db.touch(r)
    db.touch(f)
    return success(serialize.fund(f))


@bp.get("/funds/<fund_id>/report")
def fund_report(fund_id):
    require_role(READ_ROLES)
    f = domain.get_fund(fund_id)
    out = serialize.fund(f)
    projs = [p for p in db.projects.values() if p["fund_id"] == fund_id]
    projs.sort(key=lambda e: e["_seq"])
    out["projects"] = [serialize.project(p) for p in projs]
    return success(out)


# ============================ VALUATIONS ============================
@bp.post("/funds/<fund_id>/valuations")
def post_valuation(fund_id):
    require_role({"FundManager"})
    f = domain.get_fund(fund_id)
    body = V.get_body()
    period_label = V.req_str(body, "period_label")
    gav = V.req_int(body, "gross_asset_value_cents", minimum=0)
    tl = V.req_int(body, "total_liabilities_cents", minimum=0)

    # Uniqueness per (fund_id, period_label)
    for v in db.valuations.values():
        if v["fund_id"] == fund_id and v["period_label"] == period_label:
            raise err("ERR_DUPLICATE", "Valuation period_label already exists for fund")

    seq = f["current_valuation_seq"] + 1
    f["gross_asset_value_cents"] = gav
    f["total_liabilities_cents"] = tl
    f["current_valuation_seq"] = seq
    # recompute NAV from newly-written net assets (shares_outstanding unchanged)
    f["nav_per_share_cents"] = calc.nav_per_share(
        f["gross_asset_value_cents"], f["total_liabilities_cents"], f["shares_outstanding"])

    val = db.base_fields(full=False)
    val.update({
        "fund_id": fund_id,
        "seq": seq,
        "period_label": period_label,
        "gross_asset_value_cents": gav,
        "total_liabilities_cents": tl,
        "resulting_nav_per_share_cents": f["nav_per_share_cents"],
    })
    db.valuations[val["id"]] = val
    db.touch(f)
    return success(serialize.valuation(val), status=201)


@bp.get("/funds/<fund_id>/valuations")
def list_valuations(fund_id):
    require_role(READ_ROLES)
    domain.get_fund(fund_id)
    limit, offset = get_pagination()
    items = [v for v in db.valuations.values() if v["fund_id"] == fund_id]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.valuation(v) for v in page], limit, offset, total)


# ============================ SHARE CLASSES ============================
@bp.post("/funds/<fund_id>/share-classes")
def create_share_class(fund_id):
    require_role({"FundManager"})
    domain.get_fund(fund_id)
    body = V.get_body()
    class_code = V.req_str(body, "class_code")
    min_inv = V.req_int(body, "min_investment_cents", minimum=0)
    fee = V.req_int(body, "mgmt_fee_bps", minimum=0)
    if fee > 1000:
        raise err("ERR_INVALID_REQUEST", "mgmt_fee_bps must be 0..1000")
    accredited_only = V.opt_bool(body, "accredited_only", False)
    drip_eligible = V.opt_bool(body, "drip_eligible", True)

    for sc in db.share_classes.values():
        if sc["fund_id"] == fund_id and sc["class_code"] == class_code:
            raise err("ERR_DUPLICATE", "class_code already exists for fund")

    e = db.base_fields()
    e.update({
        "fund_id": fund_id,
        "class_code": class_code,
        "min_investment_cents": min_inv,
        "mgmt_fee_bps": fee,
        "accredited_only": accredited_only,
        "drip_eligible": drip_eligible,
        "status": "OFFERING",
    })
    db.share_classes[e["id"]] = e
    return success(serialize.share_class(e), status=201)


@bp.get("/funds/<fund_id>/share-classes")
def list_share_classes(fund_id):
    require_role(READ_ROLES)
    domain.get_fund(fund_id)
    limit, offset = get_pagination()
    items = [s for s in db.share_classes.values() if s["fund_id"] == fund_id]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.share_class(s) for s in page], limit, offset, total)


@bp.get("/share-classes/<sc_id>")
def get_share_class(sc_id):
    require_role(READ_ROLES)
    e = domain.get_share_class(sc_id)
    return success(serialize.share_class(e))


@bp.post("/share-classes/<sc_id>/suspend")
def suspend_share_class(sc_id):
    require_role({"FundManager"})
    sc = domain.get_share_class(sc_id)
    fund = domain.get_fund(sc["fund_id"])
    if sc["status"] != "OFFERING" or fund["status"] == "WINDING_DOWN":
        raise err("ERR_INVALID_STATE", "ShareClass cannot be suspended")
    sc["status"] = "SUSPENDED"
    db.touch(sc)
    return success(serialize.share_class(sc))


@bp.post("/share-classes/<sc_id>/resume")
def resume_share_class(sc_id):
    require_role({"FundManager"})
    sc = domain.get_share_class(sc_id)
    fund = domain.get_fund(sc["fund_id"])
    if sc["status"] != "SUSPENDED" or fund["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "ShareClass cannot be resumed")
    sc["status"] = "OFFERING"
    db.touch(sc)
    return success(serialize.share_class(sc))


# ============================ PROJECTS ============================
@bp.post("/funds/<fund_id>/projects")
def create_project(fund_id):
    require_role({"FundManager"})
    domain.get_fund(fund_id)
    body = V.get_body()
    name = V.req_str(body, "name")
    acq = V.req_int(body, "acquisition_cost_cents", minimum=0)
    appr = V.req_int(body, "appraised_value_cents", minimum=0)

    e = db.base_fields()
    e.update({
        "fund_id": fund_id,
        "name": name,
        "acquisition_cost_cents": acq,
        "appraised_value_cents": appr,
        "status": "ACQUIRED",
    })
    db.projects[e["id"]] = e
    return success(serialize.project(e), status=201)


@bp.get("/funds/<fund_id>/projects")
def list_projects(fund_id):
    require_role(READ_ROLES)
    domain.get_fund(fund_id)
    limit, offset = get_pagination()
    items = [p for p in db.projects.values() if p["fund_id"] == fund_id]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.project(p) for p in page], limit, offset, total)


@bp.post("/projects/<pid>/stabilize")
def stabilize_project(pid):
    require_role({"FundManager"})
    p = domain.get_project(pid)
    if p["status"] != "ACQUIRED":
        raise err("ERR_INVALID_STATE", "Project not ACQUIRED")
    p["status"] = "STABILIZED"
    db.touch(p)
    return success(serialize.project(p))


@bp.post("/projects/<pid>/dispose")
def dispose_project(pid):
    require_role({"FundManager"})
    p = domain.get_project(pid)
    if p["status"] not in ("ACQUIRED", "STABILIZED"):
        raise err("ERR_INVALID_STATE", "Project cannot be disposed")
    p["status"] = "DISPOSED"
    db.touch(p)
    return success(serialize.project(p))
