from flask import Blueprint, request

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("plots", __name__)


@bp.post("/plots")
@require("Admin", "CemeteryClerk")
def create_plot():
    body = validate.get_json()
    funeral_home_id = validate.require_string(body, "funeral_home_id")
    section = validate.require_string(body, "section")
    plot_code = validate.require_string(body, "plot_code")
    current_price_cents = validate.require_int(body, "current_price_cents", minimum=0)

    lookup.funeral_home(funeral_home_id)

    plot = {
        "id": db.new_id(),
        "funeral_home_id": funeral_home_id,
        "section": section,
        "plot_code": plot_code,
        "current_price_cents": current_price_cents,
        "status": "AVAILABLE",
        "reserved_case_id": None,
        "locked_price_cents": None,
    }
    db.stamp_create(plot)
    db.plots[plot["id"]] = plot
    return ok_object(serialize.plot(plot), 201)


@bp.get("/plots/<plot_id>")
@require("Admin", "Arranger", "CemeteryClerk")
def get_plot(plot_id):
    plot = lookup.plot(plot_id)
    return ok_object(serialize.plot(plot), 200)


@bp.get("/plots")
@require("Admin", "Arranger", "CemeteryClerk")
def list_plots():
    limit, offset = validate.pagination()
    fh = request.args.get("funeral_home_id")
    reserved_case_id = request.args.get("reserved_case_id")
    items = list(db.plots.values())
    if fh is not None:
        items = [p for p in items if p["funeral_home_id"] == fh]
    if reserved_case_id is not None:
        items = [p for p in items if p.get("reserved_case_id") == reserved_case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.plot(p) for p in window], limit, offset, total)


@bp.post("/plots/<plot_id>/reserve")
@require("CemeteryClerk")
def reserve_plot(plot_id):
    plot = lookup.plot(plot_id)
    body = validate.get_json()
    case_id = validate.require_string(body, "case_id")
    expected = validate.require_int(body, "expected_plot_version")

    # existence of the target case (priority 3, body resource id)
    case = lookup.case(case_id)

    # priority 5: OCC staleness
    if expected != plot["version"]:
        raise errors.stale_version("expected_plot_version does not match current version")

    # priority 6: state
    if plot["status"] != "AVAILABLE":
        raise errors.conflict(errors.ERR_PLOT_NOT_AVAILABLE,
                              "Plot is not AVAILABLE")

    # business rule: target case must not be CANCELLED/COMPLETED
    if case["arrangement_status"] in ("CANCELLED", "COMPLETED"):
        raise errors.invalid_state("Target case is not in an active state")

    plot["status"] = "RESERVED"
    plot["reserved_case_id"] = case_id
    plot["locked_price_cents"] = plot["current_price_cents"]
    db.touch(plot)
    return ok_object(serialize.plot(plot), 200)


@bp.post("/plots/<plot_id>/release")
@require("CemeteryClerk")
def release_plot(plot_id):
    plot = lookup.plot(plot_id)
    if plot["status"] != "RESERVED":
        raise errors.conflict(errors.ERR_PLOT_NOT_RESERVED,
                              "Plot is not RESERVED")
    # cannot release if the holding case has already reached INTERRED
    holder = db.cases.get(plot.get("reserved_case_id")) if plot.get("reserved_case_id") else None
    if holder is not None and holder.get("interment_status") == "INTERRED":
        raise errors.invalid_state("Cannot release a plot for an interred case")

    plot["status"] = "AVAILABLE"
    plot["reserved_case_id"] = None
    plot["locked_price_cents"] = None
    db.touch(plot)
    return ok_object(serialize.plot(plot), 200)


@bp.post("/plots/<plot_id>/inter")
@require("CemeteryClerk")
def inter_plot(plot_id):
    plot = lookup.plot(plot_id)
    if plot["status"] != "RESERVED":
        raise errors.conflict(errors.ERR_PLOT_NOT_RESERVED,
                              "Plot is not RESERVED")
    case = db.cases.get(plot.get("reserved_case_id")) if plot.get("reserved_case_id") else None
    if case is None or case.get("interment_status") != "READY":
        raise errors.conflict(errors.ERR_INTERMENT_NOT_READY,
                              "Reserved case interment status is not READY")

    # interment-close cascade (depth 2)
    plot["status"] = "INTERRED"
    db.touch(plot)
    case["interment_status"] = "INTERRED"
    db.touch(case)
    return ok_object(serialize.plot(plot), 200)
