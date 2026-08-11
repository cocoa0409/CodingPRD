"""Foreign travel extension endpoints."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from util import (
    add_days,
    body,
    get_child,
    get_production,
    make_entity,
    now,
    paginate,
    req_dt,
    req_int,
    req_string,
    serialize,
    touch,
)

TRAVEL_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}
FOREIGN_TRAVEL_BUFFER_DAYS = 14


def get_extension(prod_id, ext_id):
    return get_child(db.travel_extensions, ext_id, "production_id", prod_id,
                     "ForeignTravelExtension")


@bp.route("/productions/<id>/foreign-travel-extensions", methods=["POST"])
def create_travel_extension(id):
    require_roles({"ProductionManager"})
    with db.lock:
        get_production(id)
        data = body()
        territory_code = req_string(data, "territory_code")
        start = req_dt(data, "travel_window_start")
        end = req_dt(data, "travel_window_end")
        travelers_count = req_int(data, "travelers_count")
        repatriation_limit_cents = req_int(data, "repatriation_limit_cents")
        if end <= start:
            raise err("ERR_TEMPORAL_RANGE_INVALID",
                      "travel_window_end must be after travel_window_start")
        if travelers_count <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "travelers_count must be greater than zero")
        if repatriation_limit_cents <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "repatriation_limit_cents must be greater than zero")

        rec = make_entity({
            "production_id": id,
            "territory_code": territory_code,
            "travel_window_start": start,
            "travel_window_end": end,
            "travelers_count": travelers_count,
            "repatriation_limit_cents": repatriation_limit_cents,
            "status": "REQUESTED",
        })
        db.travel_extensions[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/foreign-travel-extensions", methods=["GET"])
def list_travel_extensions(id):
    require_roles(TRAVEL_ROLES)
    get_production(id)
    territory = request.args.get("territory_code")
    status = request.args.get("status")
    records = [e for e in db.travel_extensions.values() if e["production_id"] == id]
    if territory is not None:
        records = [r for r in records if r["territory_code"] == territory]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/foreign-travel-extensions/<childId>", methods=["GET"])
def get_travel_extension(id, childId):
    require_roles(TRAVEL_ROLES)
    get_production(id)
    rec = get_extension(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/foreign-travel-extensions/<childId>/approve", methods=["POST"])
def approve_travel_extension(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        prod = get_production(id)
        ext = get_extension(id, childId)
        if ext["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE",
                      "Extension must be REQUESTED to approve (current: %s)" % ext["status"])

        if prod["coverage_posture"] not in ("BOUND_PARTIAL", "BOUND_FULL"):
            raise err("ERR_POSTURE_BLOCKS_FOREIGN",
                      "coverage_posture %s blocks foreign travel approval"
                      % prod["coverage_posture"])

        ft_policies = [
            p for p in db.policies.values()
            if p["production_id"] == id and p["coverage_line"] == "FOREIGN_TRAVEL"
            and p["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")
        ]
        if not ft_policies:
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "No bound FOREIGN_TRAVEL policy on this production")
        overlaps_policy = any(
            ext["travel_window_start"] < p["expiry_date"]
            and ext["travel_window_end"] > p["effective_date"]
            for p in ft_policies
        )
        if not overlaps_policy:
            raise err("ERR_FOREIGN_TRAVEL_OVERLAP",
                      "Travel window does not overlap the FOREIGN_TRAVEL policy window")

        # Half-open overlap against other approved/active same-territory extensions
        for other in db.travel_extensions.values():
            if (other["id"] == ext["id"] or other["production_id"] != id
                    or other["territory_code"] != ext["territory_code"]
                    or other["status"] not in ("APPROVED", "ACTIVE")):
                continue
            if (ext["travel_window_start"] < other["travel_window_end"]
                    and ext["travel_window_end"] > other["travel_window_start"]):
                raise err("ERR_FOREIGN_TRAVEL_OVERLAP",
                          "Window overlaps extension '%s' for territory %s"
                          % (other["id"], other["territory_code"]))

        buffer_start = add_days(prod["principal_photography_start"], -FOREIGN_TRAVEL_BUFFER_DAYS)
        buffer_end = add_days(prod["principal_photography_end"], FOREIGN_TRAVEL_BUFFER_DAYS)
        if ext["travel_window_start"] < buffer_start or ext["travel_window_end"] > buffer_end:
            raise err("ERR_FOREIGN_TRAVEL_OVERLAP",
                      "Travel window is outside the production travel envelope")

        ext["status"] = "APPROVED"
        touch(ext)
        from services.lifecycle import sweep
        sweep()
        return success_object(serialize(ext))


@bp.route("/productions/<id>/foreign-travel-extensions/<childId>/deny", methods=["POST"])
def deny_travel_extension(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        get_production(id)
        ext = get_extension(id, childId)
        if ext["status"] == "REQUESTED":
            pass
        elif ext["status"] == "APPROVED":
            if not now() < ext["travel_window_start"]:
                raise err("ERR_INVALID_STATE",
                          "Approved extension cannot be denied once its window has started")
        else:
            raise err("ERR_INVALID_STATE",
                      "Extension in %s cannot be denied" % ext["status"])
        ext["status"] = "DENIED"
        touch(ext)
        return success_object(serialize(ext))
