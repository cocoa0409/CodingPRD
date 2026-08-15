"""TurnoverPackage routes (PRD §3.5)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_VENDOR_CAPACITY_EXCEEDED,
)
from helpers import (
    new_entity,
    touch,
    now_iso,
    get_json_body,
    require_fields,
    check_string,
    check_enum,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from routes.vendors import vendor_in_flight_count
from services.transitions import guard_transition
from services.derived import recompute_turnover_change_list_revision

bp = Blueprint("turnovers", __name__)

TURNOVER_KINDS = ("CONFORM", "COLOR", "SOUND")
TURNOVER_TERMINAL = ("CLOSED", "VOID")
LIST_ROLES = ("PostSupervisor", "ConformEditor", "VendorRep", "ReviewerLead")


def serialize(turnover):
    return dict(turnover)


def get_turnover_or_404(project, turnover_id):
    turnover = db.turnovers.get(turnover_id)
    if turnover is None or turnover["project_id"] != project["id"]:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    return turnover


@bp.route("/post-production/projects/<project_id>/turnovers", methods=["POST"])
def create_turnover(project_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("turnover_kind", "sequence_label"))
    turnover_kind = check_enum(body, "turnover_kind", TURNOVER_KINDS)
    sequence_label = check_string(body, "sequence_label")
    # sequence_label unique per (project, turnover_kind)
    for existing in db.turnovers.values():
        if (
            existing["project_id"] == project_id
            and existing["turnover_kind"] == turnover_kind
            and existing["sequence_label"] == sequence_label
        ):
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"sequence_label '{sequence_label}' already exists in this "
                "project for this turnover_kind",
                400,
            )
    turnover = new_entity(
        {
            "project_id": project_id,
            "turnover_kind": turnover_kind,
            "sequence_label": sequence_label,
            "vendor_id": None,
            "status": "DRAFT",
            "issued_at": None,
            "change_list_revision": 0,
        }
    )
    db.turnovers[turnover["id"]] = turnover
    return success_object(serialize(turnover), 201)


@bp.route("/post-production/projects/<project_id>/turnovers", methods=["GET"])
def list_turnovers(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [t for t in db.turnovers.values() if t["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    kind = get_filter("turnover_kind")
    if kind is not None:
        items = [t for t in items if t["turnover_kind"] == kind]
    vendor_id = get_filter("vendor_id")
    if vendor_id is not None:
        items = [t for t in items if t.get("vendor_id") == vendor_id]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(t) for t in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>", methods=["GET"]
)
def get_turnover(project_id, turnover_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/stage",
    methods=["POST"],
)
def stage_turnover(project_id, turnover_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "DRAFT", TURNOVER_TERMINAL, "turnover package")
    if project["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Project is in state {project['status']}, not ACTIVE",
            409,
        )
    if turnover["turnover_kind"] == "CONFORM":
        # Requires at least one MediaAsset in {VERIFIED, CONFORMED}.
        has_asset = any(
            a["project_id"] == project_id and a["status"] in ("VERIFIED", "CONFORMED")
            for a in db.assets.values()
        )
        if not has_asset:
            raise ApiError(
                ERR_INVALID_STATE,
                "A CONFORM turnover requires at least one MediaAsset in "
                "VERIFIED or CONFORMED",
                409,
            )
    turnover["status"] = "STAGED"
    touch(turnover)
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/issue",
    methods=["POST"],
)
def issue_turnover(project_id, turnover_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "STAGED", TURNOVER_TERMINAL, "turnover package")
    # A VendorBid for this turnover must exist in status AWARDED.
    awarded = None
    for bid in db.vendor_bids.values():
        if bid.get("turnover_id") == turnover_id and bid["status"] == "AWARDED":
            awarded = bid
            break
    if awarded is None:
        raise ApiError(
            ERR_INVALID_STATE,
            "No VendorBid for this turnover exists in status AWARDED",
            409,
        )
    if turnover.get("vendor_id") != awarded["vendor_id"]:
        raise ApiError(
            ERR_INVALID_STATE,
            "TurnoverPackage.vendor_id does not equal the awarded bid's "
            "vendor_id",
            409,
        )
    # Vendor capacity (priority 13): concurrent ISSUED+ACKED turnovers must
    # stay below capacity_slots.
    vendor = db.vendors.get(awarded["vendor_id"])
    if vendor is None:
        raise ApiError(
            ERR_NOT_FOUND, f"Vendor {awarded['vendor_id']} does not exist", 404
        )
    load = vendor_in_flight_count(vendor["id"])
    if load >= vendor["capacity_slots"]:
        raise ApiError(
            ERR_VENDOR_CAPACITY_EXCEEDED,
            "Vendor already at capacity_slots of ISSUED+ACKED turnovers",
            422,
        )
    turnover["status"] = "ISSUED"
    turnover["issued_at"] = now_iso()
    touch(turnover)
    # conform_ready is recomputed when a turnover is issued (PRD §3.1).
    from services.derived import recompute_conform_ready

    recompute_conform_ready(project)
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/ack",
    methods=["POST"],
)
def ack_turnover(project_id, turnover_id):
    user_id, role = require_roles(("VendorRep",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "ISSUED", TURNOVER_TERMINAL, "turnover package")
    # VendorRep's vendor identity (X-User-ID) must match the turnover's
    # vendor_id (PRD §2.1, §3.5).
    if turnover.get("vendor_id") != user_id:
        raise ApiError(
            ERR_INVALID_STATE,
            "VendorRep may acknowledge only turnovers awarded to their own "
            "vendor",
            409,
        )
    turnover["status"] = "ACKED"
    touch(turnover)
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/return",
    methods=["POST"],
)
def return_turnover(project_id, turnover_id):
    user_id, role = require_roles(("VendorRep",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "ACKED", TURNOVER_TERMINAL, "turnover package")
    if turnover.get("vendor_id") != user_id:
        raise ApiError(
            ERR_INVALID_STATE,
            "VendorRep may return only turnovers awarded to their own vendor",
            409,
        )
    # No ChangeList on this turnover may be in OPEN.
    for cl in db.change_lists.values():
        if cl.get("turnover_id") == turnover_id and cl["status"] == "OPEN":
            raise ApiError(
                ERR_INVALID_STATE,
                "A ChangeList on this turnover is still OPEN",
                409,
            )
    turnover["status"] = "RETURNED"
    touch(turnover)
    # Side effect: auto-create a ReviewRound with target_kind VENDOR_RETURN.
    from services.derived import recompute_round_counters

    round_entity = new_entity(
        {
            "project_id": project_id,
            "round_label": f"VENDOR_RETURN-{turnover['sequence_label']}",
            "target_kind": "VENDOR_RETURN",
            "target_ref_id": turnover_id,
            "status": "OPEN",
            "unresolved_critical": False,
            "open_note_count": 0,
        }
    )
    db.review_rounds[round_entity["id"]] = round_entity
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/close",
    methods=["POST"],
)
def close_turnover(project_id, turnover_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "RETURNED", TURNOVER_TERMINAL, "turnover package")
    # The auto-created ReviewRound for this turnover must be in
    # {APPROVED, VOID}.
    auto_round = None
    for rr in db.review_rounds.values():
        if (
            rr.get("target_kind") == "VENDOR_RETURN"
            and rr.get("target_ref_id") == turnover_id
        ):
            auto_round = rr
            break
    if auto_round is None or auto_round["status"] not in ("APPROVED", "VOID"):
        raise ApiError(
            ERR_INVALID_STATE,
            "The auto-created ReviewRound for this turnover must be in "
            "APPROVED or VOID before close",
            409,
        )
    turnover["status"] = "CLOSED"
    touch(turnover)
    # Vendor capacity slot released implicitly by the status change (load
    # counts only ISSUED+ACKED).
    return success_object(serialize(turnover))


@bp.route(
    "/post-production/projects/<project_id>/turnovers/<turnover_id>/void",
    methods=["POST"],
)
def void_turnover(project_id, turnover_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    turnover = get_turnover_or_404(project, turnover_id)
    guard_transition(turnover, "DRAFT", TURNOVER_TERMINAL, "turnover package")
    turnover["status"] = "VOID"
    touch(turnover)
    # Side effects: SUBMITTED bids -> EXPIRED; AWARDED bid -> REJECTED.
    for bid in db.vendor_bids.values():
        if bid.get("turnover_id") != turnover_id:
            continue
        if bid["status"] == "SUBMITTED":
            bid["status"] = "EXPIRED"
            touch(bid)
        elif bid["status"] == "AWARDED":
            bid["status"] = "REJECTED"
            touch(bid)
    # A round still OPEN whose target is this turnover is voided (PRD §3.6).
    from services.derived import void_review_round

    for rr in db.review_rounds.values():
        if rr.get("target_ref_id") == turnover_id and rr["status"] == "OPEN":
            void_review_round(rr)
    return success_object(serialize(turnover))


# ---------------------------------------------------------------------------
# Flat alias + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/turnovers/<turnover_id>", methods=["GET"])
def get_turnover_flat(turnover_id):
    require_roles(LIST_ROLES)
    turnover = db.turnovers.get(turnover_id)
    if turnover is None:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    return success_object(serialize(turnover))


@bp.route("/post-production/turnovers/<turnover_id>/change-lists", methods=["GET"])
def list_turnover_change_lists(turnover_id):
    require_roles(("PostSupervisor", "ConformEditor", "VendorRep"))
    turnover = db.turnovers.get(turnover_id)
    if turnover is None:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    from routes.change_lists import serialize as serialize_change_list

    limit, offset = get_pagination()
    items = [c for c in db.change_lists.values() if c.get("turnover_id") == turnover_id]
    status = get_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list(
        [serialize_change_list(c) for c in window], limit, offset, total
    )


@bp.route("/post-production/turnovers/<turnover_id>/vendor-bids", methods=["GET"])
def list_turnover_bids(turnover_id):
    require_roles(("PostSupervisor", "VendorRep", "FacilityAdmin"))
    turnover = db.turnovers.get(turnover_id)
    if turnover is None:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    from routes.vendor_bids import serialize as serialize_bid

    limit, offset = get_pagination()
    items = [b for b in db.vendor_bids.values() if b.get("turnover_id") == turnover_id]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_bid(b) for b in window], limit, offset, total)
