"""Clock, pricing nodes, offtakers and projects."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import services as svc
from core import (ApiError, D0, add_days, bad_request, body, db, endpoint,
                  opt_enum,
                  filter_enum, filter_int, filter_str, get_offtaker,
                  get_pricing_node, get_project, iso_ms, now, opt_bool, opt_dt,
                  opt_int, opt_list, opt_num, opt_str, page, parse_dt, present,
                  q, req_dt, req_enum, req_int, req_num, req_str, sort_created,
                  touch)

bp = Blueprint("routes_a", __name__)

ALL_ROLES = ["Originator", "CreditOfficer", "DealCommittee",
             "SettlementAnalyst", "RegistryAgent", "OfftakerRep"]


# --------------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def set_clock():
    data = body()
    moment = req_dt(data, "current_utc")
    db.clock = moment
    return {"current_utc": moment}


# -------------------------------------------------------------- pricing nodes
@bp.route("/ppa/pricing-nodes", methods=["POST"])
@endpoint(["Originator", "SettlementAnalyst"])
def create_pricing_node():
    data = body()
    name = req_str(data, "name", 1, 64)
    iso = req_enum(data, "iso", calc.ISO)
    point_type = req_enum(data, "settlement_point_type",
                          calc.SETTLEMENT_POINT_TYPE)
    for existing in db.pricing_nodes.values():
        if existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_PRICING_NODE",
                           "pricing node name already registered")
    row = svc.base_row()
    row.pop("version", None)
    row.pop("updated_at", None)
    row.update({"name": name, "iso": iso,
                "settlement_point_type": point_type})
    db.pricing_nodes[row["id"]] = row
    return row, 201


@bp.route("/ppa/pricing-nodes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_pricing_nodes():
    iso = filter_enum("iso", calc.ISO)
    point_type = filter_enum("settlement_point_type",
                             calc.SETTLEMENT_POINT_TYPE)
    rows = sort_created(list(db.pricing_nodes.values()))
    if iso is not None:
        rows = [r for r in rows if r["iso"] == iso]
    if point_type is not None:
        rows = [r for r in rows if r["settlement_point_type"] == point_type]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/pricing-nodes/<node_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_pricing_node(node_id):
    return get_pricing_node(node_id)


# ------------------------------------------------------------------ offtakers
@bp.route("/ppa/offtakers", methods=["POST"])
@endpoint(["Originator"])
def create_offtaker():
    data = body()
    legal_name = req_str(data, "legal_name", 1, 128)
    credit_rating = req_enum(data, "credit_rating", calc.CREDIT_RATING)
    rating_agency = req_enum(data, "rating_agency", calc.RATING_AGENCY)
    ebitda = req_num(data, "reported_ebitda_usd", minimum=0,
                     exclusive_min=True)
    leverage = req_num(data, "net_debt_to_ebitda", minimum=0)
    framework = req_enum(data, "disclosure_framework",
                         calc.DISCLOSURE_FRAMEWORK)
    sbt = opt_bool(data, "has_science_based_target", False)
    re100 = opt_bool(data, "re100_member", False)
    target_year = opt_int(data, "scope2_target_year", 2026, 2060, None)
    registry_account_id = opt_str(data, "registry_account_id", 1, None, None)
    parent_id = opt_str(data, "parent_guarantor_offtaker_id", 1, None, None)

    if parent_id is not None:
        get_offtaker(parent_id)

    row = svc.base_row()
    if parent_id is not None:
        svc.check_guarantor_cycle(row["id"], parent_id)
    row.update({
        "legal_name": legal_name,
        "credit_rating": credit_rating,
        "rating_agency": rating_agency,
        "reported_ebitda_usd": q(ebitda, 2),
        "net_debt_to_ebitda": leverage,
        "disclosure_framework": framework,
        "has_science_based_target": bool(sbt),
        "re100_member": bool(re100),
        "scope2_target_year": target_year,
        "registry_account_id": registry_account_id,
        "parent_guarantor_offtaker_id": parent_id,
        "qualification_status": "DRAFT",
        "credit_score": None,
        "credit_score_variant": None,
        "credit_tier": None,
        "sustainability_score": None,
        "unsecured_credit_limit_usd": None,
        "conditions": [],
        "claimed_attributes_mwh": 0,
        "watchlist_since": None,
        "created_by_user_id": g.user_id,
        "decision_by_user_id": None,
    })
    db.offtakers[row["id"]] = row
    return row, 201


@bp.route("/ppa/offtakers", methods=["GET"])
@endpoint(["Originator", "CreditOfficer", "DealCommittee", "RegistryAgent"])
def list_offtakers():
    status = filter_enum("qualification_status", calc.QUALIFICATION_STATUS)
    tier = filter_enum("credit_tier", calc.CREDIT_TIER)
    parent_id = filter_str("parent_guarantor_offtaker_id")
    rows = sort_created(list(db.offtakers.values()))
    if status is not None:
        rows = [r for r in rows if r["qualification_status"] == status]
    if tier is not None:
        rows = [r for r in rows if r.get("credit_tier") == tier]
    if parent_id is not None:
        rows = [r for r in rows
                if r.get("parent_guarantor_offtaker_id") == parent_id]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/offtakers/<off_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_offtaker(off_id):
    return get_offtaker(off_id)


@bp.route("/ppa/offtakers/<off_id>/submit-qualification", methods=["POST"])
@endpoint(["Originator"])
def submit_qualification(off_id):
    body()
    off = get_offtaker(off_id)
    status = off["qualification_status"]
    if status == "DRAFT":
        if not (off["rating_agency"] != "NONE" or off["credit_rating"] == "NR"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "a rated buyer must name a rating agency")
    elif status == "CONDITIONAL":
        off["conditions"] = []
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "cannot submit a buyer in %s" % status)
    off["qualification_status"] = "UNDER_REVIEW"
    svc.score_offtaker(off)
    touch(off)
    return off


@bp.route("/ppa/offtakers/<off_id>/qualification-decision", methods=["POST"])
@endpoint(["CreditOfficer"])
def qualification_decision(off_id):
    data = body()
    decision = req_enum(data, "decision", ["QUALIFY", "CONDITIONAL", "REJECT"])
    conditions = opt_list(data, "conditions", None)
    if decision == "CONDITIONAL" and not conditions:
        bad_request("conditions must be a non-empty array on a "
                    "CONDITIONAL decision")
    off = get_offtaker(off_id)
    if off["qualification_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "buyer is not under review")
    if g.user_id == off.get("created_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the preparer may not decide the qualification")

    if decision == "QUALIFY":
        if off.get("credit_tier") not in ("PRIME", "STANDARD"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "credit tier does not support qualification")
        if (off.get("sustainability_score") or D0) < Decimal("70.00"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "sustainability score below 70.00")
        off["qualification_status"] = "QUALIFIED"
        off["conditions"] = []
    elif decision == "CONDITIONAL":
        if off.get("credit_tier") == "DECLINED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "a declined tier cannot be conditionally qualified")
        if (off.get("sustainability_score") or D0) < Decimal("40.00"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "sustainability score below 40.00")
        off["qualification_status"] = "CONDITIONAL"
        off["conditions"] = list(conditions)
    else:
        off["qualification_status"] = "REJECTED"
        svc.decline_anchored_deals(off["id"])
    off["decision_by_user_id"] = g.user_id
    touch(off)
    return off


@bp.route("/ppa/offtakers/<off_id>/rating-change", methods=["POST"])
@endpoint(["CreditOfficer"])
def rating_change(off_id):
    data = body()
    credit_rating = req_enum(data, "credit_rating", calc.CREDIT_RATING)
    rating_agency = opt_enum(data, "rating_agency", calc.RATING_AGENCY)
    leverage = opt_num(data, "net_debt_to_ebitda", minimum=0)
    ebitda = opt_num(data, "reported_ebitda_usd", minimum=0,
                     exclusive_min=True)
    framework = opt_enum(data, "disclosure_framework",
                                 calc.DISCLOSURE_FRAMEWORK)
    parent_id = opt_str(data, "parent_guarantor_offtaker_id", 1, None, None)

    off = get_offtaker(off_id)
    if parent_id is not None:
        get_offtaker(parent_id)
        svc.check_guarantor_cycle(off["id"], parent_id)
    if off["qualification_status"] not in ("QUALIFIED", "WATCHLIST"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a QUALIFIED or WATCHLIST buyer may be re-rated")

    off["credit_rating"] = credit_rating
    if rating_agency is not None:
        off["rating_agency"] = rating_agency
    if leverage is not None:
        off["net_debt_to_ebitda"] = leverage
    if ebitda is not None:
        off["reported_ebitda_usd"] = q(ebitda, 2)
    if framework is not None:
        off["disclosure_framework"] = framework
    if parent_id is not None:
        off["parent_guarantor_offtaker_id"] = parent_id

    was = off["qualification_status"]
    svc.score_offtaker(off)
    tier = off["credit_tier"]
    if was == "QUALIFIED" and tier in ("SUBPRIME", "DECLINED"):
        off["qualification_status"] = "WATCHLIST"
        off["watchlist_since"] = now()
        svc.cascade_downgrade(off)
    elif was == "WATCHLIST" and tier in ("PRIME", "STANDARD"):
        off["qualification_status"] = "QUALIFIED"
        off["watchlist_since"] = None
        svc.cascade_recovery(off)
    elif (was == "WATCHLIST" and tier == "DECLINED"
            and off.get("watchlist_since") is not None):
        off["qualification_status"] = "REJECTED"
        svc.decline_anchored_deals(off["id"])
    else:
        svc.cascade_same_band(off)
    touch(off)
    return off


@bp.route("/ppa/offtakers/<off_id>/allocations", methods=["GET"])
@endpoint(["Originator", "CreditOfficer", "DealCommittee", "OfftakerRep"])
def offtaker_allocations(off_id):
    status = filter_enum("status", calc.ALLOCATION_STATUS)
    off = get_offtaker(off_id)
    rows = sort_created([a for a in db.allocations.values()
                         if a["offtaker_id"] == off["id"]])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/offtakers/<off_id>/attribute-batches", methods=["GET"])
@endpoint(["RegistryAgent", "Originator", "OfftakerRep"])
def offtaker_batches(off_id):
    status = filter_enum("status", calc.BATCH_STATUS)
    vintage_month = filter_str("vintage_month")
    claim_year = filter_int("claim_year")
    off = get_offtaker(off_id)
    rows = sort_created([b for b in db.batches.values()
                         if b.get("transferred_to_offtaker_id") == off["id"]])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if vintage_month is not None:
        rows = [r for r in rows if r["vintage_month"] == vintage_month]
    if claim_year is not None:
        rows = [r for r in rows if r.get("claim_year") == claim_year]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/offtakers/<off_id>/issued-guarantees", methods=["GET"])
@endpoint(["CreditOfficer", "Originator", "DealCommittee"])
def offtaker_guarantees(off_id):
    status = filter_enum("status", calc.INSTRUMENT_STATUS)
    off = get_offtaker(off_id)
    rows = sort_created([i for i in db.instruments.values()
                         if i.get("guarantor_offtaker_id") == off["id"]])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return window, 200, meta


# ------------------------------------------------------------------- projects
@bp.route("/ppa/projects", methods=["POST"])
@endpoint(["Originator"])
def create_project():
    data = body()
    name = req_str(data, "name", 1, 128)
    technology = req_enum(data, "technology", calc.TECHNOLOGY)
    capacity = req_num(data, "capacity_mw", minimum=0, exclusive_min=True)
    node_id = req_str(data, "node_id", 1, None)
    cod_target = req_dt(data, "cod_target_date")
    p50 = req_num(data, "p50_annual_mwh", minimum=0, exclusive_min=True)
    queue = opt_int(data, "interconnection_queue_position", 1, None, None)

    get_pricing_node(node_id)

    row = svc.base_row()
    row.update({
        "name": name,
        "technology": technology,
        "capacity_mw": q(capacity, 3),
        "node_id": node_id,
        "cod_target_date": cod_target,
        "p50_annual_mwh": q(p50, 2),
        "interconnection_queue_position": queue,
        "status": "PRE_DEVELOPMENT",
        "contracted_mw": q(D0, 3),
        "available_mw": q(capacity, 3),
        "last_milestone_at": None,
        "created_by_user_id": g.user_id,
    })
    db.projects[row["id"]] = row
    return row, 201


@bp.route("/ppa/projects", methods=["GET"])
@endpoint(["Originator", "CreditOfficer", "DealCommittee", "SettlementAnalyst"])
def list_projects():
    node_id = filter_str("node_id")
    status = filter_enum("status", calc.PROJECT_STATUS)
    technology = filter_enum("technology", calc.TECHNOLOGY)
    rows = sort_created(list(db.projects.values()))
    if node_id is not None:
        rows = [r for r in rows if r["node_id"] == node_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if technology is not None:
        rows = [r for r in rows if r["technology"] == technology]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/projects/<project_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_project(project_id):
    return get_project(project_id)


MILESTONE_STEPS = {
    "PERMITTED": ("PRE_DEVELOPMENT", "PERMITTED", "PERMITTING"),
    "INTERCONNECTION_APPROVED": ("PERMITTED", "INTERCONNECTION_APPROVED",
                                 "INTERCONNECTION"),
    "NOTICE_TO_PROCEED": ("INTERCONNECTION_APPROVED", "NTP_ISSUED",
                          "NOTICE_TO_PROCEED"),
    "OPERATIONAL": ("NTP_ISSUED", "OPERATIONAL", None),
}


@bp.route("/ppa/projects/<project_id>/advance-milestone", methods=["POST"])
@endpoint(["Originator"])
def advance_milestone(project_id):
    data = body()
    milestone = req_enum(data, "milestone", calc.MILESTONE)
    evidence_ref = req_str(data, "evidence_ref", 1, None)
    project = get_project(project_id)
    required_from, target, cp_type = MILESTONE_STEPS[milestone]
    if project["status"] != required_from:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "milestone %s is not the successor of %s"
                       % (milestone, project["status"]))
    project["status"] = target
    project["last_milestone_at"] = now()
    if cp_type is not None:
        svc.project_cp_cascade(project, cp_type, evidence_ref)
        svc.recompute_project_capacity(project, always_touch=True)
    else:
        svc.recompute_project_capacity(project, always_touch=True)
    return project
