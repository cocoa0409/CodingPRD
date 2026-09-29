"""Shipment endpoints — two independent axes (transport status, route survey)."""

from flask import Blueprint

import auth
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("shipments", __name__)

STATUSES = (
    "DRAFT",
    "SURVEY_REQUIRED",
    "PERMITTED",
    "DISPATCHED",
    "DELIVERED",
    "CANCELLED",
)
SURVEY_STATES = ("NOT_REQUIRED", "REQUIRED", "COMPLETED")
ENVELOPE_CLASSES = ("STANDARD", "OVERWIDTH", "SUPERLOAD")


@bp.post("/modular/shipments")
@auth.endpoint("TransportCoordinator")
def create_shipment():
    data = validate.body(optional=False)
    project_id = validate.field_id(data, "project_id")
    carrier_code = validate.field_str(data, "carrier_code")
    route_state_codes = validate.field_state_codes(data, "route_state_codes")
    planned_departure_at = validate.field_dt(data, "planned_departure_at")
    planned_arrival_at = validate.field_dt(data, "planned_arrival_at")

    if planned_arrival_at <= planned_departure_at:
        raise validate.bad("planned_arrival_at must be strictly after planned_departure_at")

    # rank 5
    services.get_project(project_id)

    row = base_row()
    row.update(
        {
            "project_id": project_id,
            "carrier_code": carrier_code,
            "route_state_codes": route_state_codes,
            "planned_departure_at": planned_departure_at,
            "planned_arrival_at": planned_arrival_at,
            "status": "DRAFT",
            "route_survey_state": "NOT_REQUIRED",
            "survey_completed_at": None,
            "escort_required": False,
            "escort_confirmed": False,
            "permit_expires_at": None,
            "permit_fee_cents": 0,
            "loaded_module_count": 0,
            "max_envelope_class": "STANDARD",
            "dispatched_at": None,
            "delivered_at": None,
            "cancel_reason": None,
        }
    )
    db.shipments[row["id"]] = row
    return created(serialize.shipment(row))


@bp.get("/modular/shipments/<shipment_id>")
@auth.endpoint(
    "ProgramAdmin", "TransportCoordinator", "SiteSuperintendent", "FactoryProductionManager"
)
def read_shipment(shipment_id):
    return ok(serialize.shipment(services.get_shipment(shipment_id)))


@bp.get("/modular/shipments")
@auth.endpoint(
    "ProgramAdmin", "TransportCoordinator", "SiteSuperintendent", "FactoryProductionManager"
)
def list_shipments():
    project_id = validate.field_str_query("project_id")
    status = validate.enum_query("status", STATUSES)
    route_survey_state = validate.enum_query("route_survey_state", SURVEY_STATES)
    carrier_code = validate.field_str_query("carrier_code")
    max_envelope_class = validate.enum_query("max_envelope_class", ENVELOPE_CLASSES)
    rows = sorted_rows(list(db.shipments.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if route_survey_state is not None:
        rows = [r for r in rows if r["route_survey_state"] == route_survey_state]
    if carrier_code is not None:
        rows = [r for r in rows if r["carrier_code"] == carrier_code]
    if max_envelope_class is not None:
        rows = [r for r in rows if r["max_envelope_class"] == max_envelope_class]
    page, meta = paginate(rows)
    return ok_list([serialize.shipment(r) for r in page], meta)


@bp.post("/modular/shipments/<shipment_id>/load-module")
@auth.endpoint("TransportCoordinator")
def load_module(shipment_id):
    data = validate.body(optional=False)
    module_id = validate.field_id(data, "module_id")
    expected_shipment_version = validate.field_int(
        data, "expected_shipment_version", minimum=0
    )

    shipment = services.get_shipment(shipment_id)  # rank 4
    module = services.get_module(module_id)  # rank 5

    # rank 10 — optimistic concurrency on the parent Shipment
    if expected_shipment_version != shipment["version"]:
        raise ApiError(
            "ERR_STALE_SHIPMENT_VERSION",
            "expected shipment version %s but current is %s"
            % (expected_shipment_version, shipment["version"]),
        )

    # rank 38 — link uniqueness wins over the generic loadability error
    if module["shipment_id"] is not None:
        raise ApiError(
            "ERR_MODULE_ALREADY_LOADED", "the module is already assigned to a shipment"
        )

    # rank 49
    if (
        shipment["status"] not in ("DRAFT", "SURVEY_REQUIRED")
        or module["site_status"] != "AT_FACTORY"
        or module["production_status"] != "LINE_COMPLETE"
    ):
        raise ApiError(
            "ERR_SHIPMENT_NOT_LOADABLE",
            "the shipment or the module is not in a loadable state",
        )

    # rank 65
    if module["qc_status"] == "HOLD":
        raise ApiError(
            "ERR_QC_HOLD_BLOCKS_OPERATION", "an agency hold blocks transport"
        )

    # rank 66
    if module["qc_status"] not in ("RELEASED", "CONDITIONAL_RELEASE"):
        raise ApiError(
            "ERR_QC_NOT_RELEASED",
            "qc_status %s has not been released for transport" % module["qc_status"],
        )

    # rank 71 — a superload route is capped at two states
    prospective = services.calc.widest_envelope(
        [m["envelope_class"] for m in services.modules_of_shipment(shipment["id"])]
        + [module["envelope_class"]]
    )
    if prospective == "SUPERLOAD" and len(shipment["route_state_codes"]) > 2:
        raise ApiError(
            "ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT",
            "a SUPERLOAD load may not traverse more than 2 states",
        )

    # rank 89
    if module["project_id"] != shipment["project_id"]:
        raise ApiError(
            "ERR_SHIPMENT_PROJECT_MISMATCH",
            "the module belongs to a different project than the shipment",
        )

    module["shipment_id"] = shipment["id"]
    module["site_status"] = "LOADED"
    touch(module)
    services.recompute_shipment_aggregates(shipment)
    touch(shipment)
    return ok(serialize.shipment(shipment))


@bp.post("/modular/shipments/<shipment_id>/route-survey")
@auth.endpoint("TransportCoordinator")
def route_survey(shipment_id):
    data = validate.body(optional=False)
    survey_completed_at = validate.field_dt(data, "survey_completed_at")
    permit_expires_at = validate.field_dt(data, "permit_expires_at")
    escort_confirmed = validate.field_bool(
        data, "escort_confirmed", required=False, default=False
    )

    shipment = services.get_shipment(shipment_id)

    # rank 50
    if (
        shipment["status"] not in ("DRAFT", "SURVEY_REQUIRED")
        or shipment["route_survey_state"] == "COMPLETED"
        or shipment["loaded_module_count"] < 1
    ):
        raise ApiError(
            "ERR_SURVEY_NOT_PENDING", "no route survey is pending on this shipment"
        )

    # rank 75
    if shipment["escort_required"] and escort_confirmed is not True:
        raise ApiError(
            "ERR_ESCORT_NOT_CONFIRMED",
            "escort vehicles must be confirmed for this envelope class",
        )

    # rank 79
    if permit_expires_at <= now():
        raise ApiError(
            "ERR_TRANSPORT_PERMIT_EXPIRED",
            "permit_expires_at is not after the current clock instant",
        )

    shipment["route_survey_state"] = "COMPLETED"
    shipment["status"] = "PERMITTED"
    shipment["survey_completed_at"] = survey_completed_at
    shipment["permit_expires_at"] = permit_expires_at
    shipment["escort_confirmed"] = escort_confirmed
    touch(shipment)
    return ok(serialize.shipment(shipment))


@bp.post("/modular/shipments/<shipment_id>/dispatch")
@auth.endpoint("TransportCoordinator")
def dispatch(shipment_id):
    data = validate.body()
    validate.field_dt(data, "departed_at", required=False)

    shipment = services.get_shipment(shipment_id)

    # rank 51
    if shipment["status"] != "PERMITTED" or shipment["loaded_module_count"] < 1:
        raise ApiError(
            "ERR_SHIPMENT_NOT_PERMITTED",
            "the shipment is not a permitted, loaded transport",
        )

    # rank 79
    expires = shipment["permit_expires_at"]
    if expires is None or not (now() < expires):
        raise ApiError(
            "ERR_TRANSPORT_PERMIT_EXPIRED", "the transport permit is no longer live"
        )

    shipment["status"] = "DISPATCHED"
    shipment["dispatched_at"] = now()
    touch(shipment)
    for module in services.modules_of_shipment(shipment["id"]):
        if module["site_status"] == "LOADED":
            module["site_status"] = "IN_TRANSIT"
            touch(module)
    project = db.projects.get(shipment["project_id"])
    if project is not None:
        services.refresh_project(project)
        touch(project)
    return ok(serialize.shipment(shipment))


@bp.post("/modular/shipments/<shipment_id>/deliver")
@auth.endpoint("TransportCoordinator", "SiteSuperintendent")
def deliver(shipment_id):
    data = validate.body()
    validate.field_dt(data, "arrived_at", required=False)

    shipment = services.get_shipment(shipment_id)

    # rank 52
    if shipment["status"] != "DISPATCHED":
        raise ApiError(
            "ERR_SHIPMENT_NOT_DISPATCHED",
            "status %s cannot be delivered" % shipment["status"],
        )

    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = now()
    touch(shipment)
    for module in services.modules_of_shipment(shipment["id"]):
        if module["site_status"] == "IN_TRANSIT":
            module["site_status"] = "DELIVERED"
            touch(module)
    project = db.projects.get(shipment["project_id"])
    if project is not None:
        services.recompute_draft_draws(project)
        services.refresh_project(project)
    return ok(serialize.shipment(shipment))


@bp.post("/modular/shipments/<shipment_id>/cancel")
@auth.endpoint("TransportCoordinator")
def cancel(shipment_id):
    data = validate.body(optional=False)
    reason = validate.field_str(data, "reason", allow_blank=True)

    shipment = services.get_shipment(shipment_id)

    # rank 53
    if shipment["status"] not in ("DRAFT", "SURVEY_REQUIRED", "PERMITTED"):
        raise ApiError(
            "ERR_SHIPMENT_TERMINAL",
            "status %s can no longer be cancelled" % shipment["status"],
        )

    for module in services.modules_of_shipment(shipment["id"]):
        module["shipment_id"] = None
        if module["site_status"] == "LOADED":
            module["site_status"] = "AT_FACTORY"
        touch(module)

    shipment["status"] = "CANCELLED"
    shipment["cancel_reason"] = reason
    services.reset_shipment_transport(shipment)
    touch(shipment)

    project = db.projects.get(shipment["project_id"])
    if project is not None:
        services.refresh_project(project)
        touch(project)
    return ok(serialize.shipment(shipment))
