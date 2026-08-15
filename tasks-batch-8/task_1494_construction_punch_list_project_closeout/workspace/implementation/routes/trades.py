"""Trade packages and the lien-waiver mini state machine (PRD 3.1, 3.5)."""
from flask import Blueprint

from authz import (
    GCPM, SUBREP, ALL_ROLES, require_roles, check_responsible_party,
)
from db import store
from derived import maybe_advance_project, recompute_trade
from errors import (
    duplicate_trade, invalid_request, invalid_state, not_responsible_party,
    waiver_already_accepted, waiver_not_acceptable_state,
)
from respond import success
from serialize import ser_trade
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_enum, req_int, req_str, sorted_by_creation,
)

bp = Blueprint("trades", __name__, url_prefix="/closeout")

TRADE_NAMES = (
    "ELECTRICAL", "PLUMBING", "HVAC", "DRYWALL", "FLOORING",
    "ROOFING", "PAINTING", "CONCRETE",
)

# Waiver submissions are accepted in the five working phases (PRD 3.5).
WORKING_PHASES = (
    "PUNCH_ACTIVE", "SC_REVIEW", "SUBSTANTIALLY_COMPLETE",
    "CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING",
)


@bp.route("/trade-packages", methods=["POST"])
def create_trade_package():
    require_roles([GCPM])
    data = json_body()
    project_id = req_str(data, "project_id")
    trade_name = req_enum(data, "trade_name", TRADE_NAMES)
    responsible_type = req_enum(
        data, "responsible_type", ("SUBCONTRACTOR", "SELF_PERFORMED"))
    sub_org = data.get("subcontractor_org")
    # subcontractor_org is required exactly when responsible_type=SUBCONTRACTOR.
    if responsible_type == "SUBCONTRACTOR" and sub_org is None:
        raise invalid_request(
            "subcontractor_org is required for SUBCONTRACTOR trade packages")
    if sub_org is not None and (isinstance(sub_org, bool) or not isinstance(sub_org, str)):
        raise invalid_request("subcontractor_org must be a string")
    p = get_or_404(store.projects, project_id)
    if p["status"] != "MOBILIZED":
        raise invalid_state("Trade packages may only be registered while MOBILIZED")
    if any(t["project_id"] == project_id and t["trade_name"] == trade_name
           for t in store.trade_packages.values()):
        raise duplicate_trade()
    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "trade_name": trade_name,
        "responsible_type": responsible_type,
        "subcontractor_org": sub_org,
        "has_completed_walk": False,
        "open_item_count": 0,
        "om_doc_approved": False,
        "warranty_doc_approved": False,
        "asbuilt_doc_approved": False,
        "has_conducted_training": False,
        "lien_waiver_status": "NONE",
        "lien_waiver_type": None,
        "lien_waiver_amount_cents": None,
        "lien_waiver_file_ref": None,
        "closeout_ready": False,
    }
    t.update(new_common_fields())
    store.trade_packages[t["id"]] = t
    return success(ser_trade(t), status=201)


@bp.route("/trade-packages/<tid>", methods=["GET"])
def get_trade_package(tid):
    require_roles(ALL_ROLES)
    return success(ser_trade(get_or_404(store.trade_packages, tid)))


@bp.route("/trade-packages", methods=["GET"])
def list_trade_packages():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id")
    items = [t for t in store.trade_packages.values()
             if all(t[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_trade(t) for t in page], response_type="array",
                   pagination=pagination)


@bp.route("/trade-packages/<tid>/lien-waiver-submission", methods=["POST"])
def lien_waiver_submission(tid):
    uid, role = require_roles([SUBREP, GCPM])
    # Priority 3 (responsible party): for a SubcontractorRep the identity check
    # is evaluable from the path alone — X-User-ID must equal the trade id.
    if role == SUBREP and uid != tid:
        raise not_responsible_party()
    data = json_body()
    waiver_type = req_enum(data, "waiver_type", ("CONDITIONAL", "UNCONDITIONAL"))
    amount_cents = req_int(data, "amount_cents")
    if amount_cents <= 0:
        raise invalid_request("amount_cents must be > 0")
    file_ref = req_str(data, "file_ref")
    t = get_or_404(store.trade_packages, tid)
    check_responsible_party(uid, role, t)
    p = store.projects[t["project_id"]]
    if p["status"] not in WORKING_PHASES:
        raise invalid_state("Lien waivers may only be submitted in a working phase")
    if t["lien_waiver_status"] == "ACCEPTED":
        raise waiver_already_accepted()
    if t["lien_waiver_status"] not in ("NONE", "REJECTED"):
        raise invalid_state("A submitted waiver is already awaiting a decision")
    recompute_trade(t, {
        "lien_waiver_status": "SUBMITTED",
        "lien_waiver_type": waiver_type,
        "lien_waiver_amount_cents": amount_cents,
        "lien_waiver_file_ref": file_ref,
    })
    return success(ser_trade(t))


@bp.route("/trade-packages/<tid>/lien-waiver-decision", methods=["POST"])
def lien_waiver_decision(tid):
    require_roles([GCPM])
    data = json_body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    if decision == "REJECT":
        req_str(data, "rejection_reason")  # required on REJECT
    t = get_or_404(store.trade_packages, tid)
    if t["lien_waiver_status"] != "SUBMITTED":
        raise invalid_state("Lien waiver decision requires status SUBMITTED")
    p = store.projects[t["project_id"]]
    if decision == "ACCEPT":
        # Acceptance is phase-gated by waiver type (PRD 3.5).
        if t["lien_waiver_type"] == "CONDITIONAL":
            allowed = ("SUBSTANTIALLY_COMPLETE", "CLOSEOUT_IN_PROGRESS",
                       "FINAL_RELEASE_PENDING")
        else:
            allowed = ("CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING")
        if p["status"] not in allowed:
            raise waiver_not_acceptable_state()
        recompute_trade(t, {"lien_waiver_status": "ACCEPTED"})
        maybe_advance_project(p)
    else:
        recompute_trade(t, {"lien_waiver_status": "REJECTED"})
    return success(ser_trade(t))
