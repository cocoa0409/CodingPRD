"""Dispensers: installation, interoperability amendment, terminal certification
and retirement (PRD §3.2)."""
from flask import Blueprint

import cascades
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint
from response import array_response, object_response, paginate

bp = Blueprint("charging_ports", __name__)

CONNECTOR_TYPES = ("CCS1", "NACS", "CHADEMO", "J1772")
OCPI_VERSIONS = ("NONE", "V2_1_1", "V2_2_1", "V2_3_0")
CERTIFICATION_OUTCOMES = ("CERTIFIED", "REVOKED")


@bp.post("/charging-ports")
@endpoint("NetworkOperator")
def install_port():
    body = validation.json_body()
    station_id = validation.as_string(body, "station_id")
    station = lookup.station(station_id)

    connector_type = validation.as_enum(body, "connector_type", CONNECTOR_TYPES)
    rated_power_kw = validation.as_number(body, "rated_power_kw",
                                          exclusive_minimum=0, places=2)
    dispenser_serial = validation.as_string(body, "dispenser_serial")
    terminal_model = validation.as_string(body, "terminal_model")
    contactless = validation.as_bool(body, "contactless_enabled", required=False, default=False)
    plug_and_charge = validation.as_bool(body, "plug_and_charge_enabled",
                                         required=False, default=False)
    price_display = validation.as_bool(body, "price_display_verified",
                                       required=False, default=False)
    roaming = validation.as_enum(body, "roaming_ocpi_version", OCPI_VERSIONS,
                                 required=False, default="NONE")

    for existing in db.ports.values():
        if existing["dispenser_serial"] == dispenser_serial:
            raise err("ERR_DISPENSER_SERIAL_DUPLICATE", "dispenser_serial is already in use.")

    row = db.base_record()
    row.update({
        "station_id": station["id"],
        "connector_type": connector_type,
        "rated_power_kw": rated_power_kw,
        "dispenser_serial": dispenser_serial,
        "terminal_model": terminal_model,
        "contactless_enabled": contactless,
        "plug_and_charge_enabled": plug_and_charge,
        "price_display_verified": price_display,
        "roaming_ocpi_version": roaming,
        "terminal_certification_status": "PENDING",
        "service_state": "IN_SERVICE",
        "maintenance_state": "NONE",
        "retired_at": None,
    })
    db.ports[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.charging_port(row), 201)


@bp.get("/charging-ports/<port_id>")
@endpoint()
def get_port(port_id):
    return object_response(serialize.charging_port(lookup.port(port_id)))


@bp.get("/charging-ports/<port_id>/outage-events")
@endpoint()
def list_outages_of_port(port_id):
    port = lookup.port(port_id)
    limit, offset = validation.pagination()
    rows = db.outages_of_port(port["id"])
    rows = validation.apply_filters(rows, validation.filters("state", "fault_class"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.outage_event(r) for r in page], limit, offset, total)


@bp.patch("/charging-ports/<port_id>")
@endpoint("NetworkOperator")
def amend_port(port_id):
    port = lookup.port(port_id)
    body = validation.json_body()
    contactless = validation.as_bool(body, "contactless_enabled", required=False)
    plug_and_charge = validation.as_bool(body, "plug_and_charge_enabled", required=False)
    price_display = validation.as_bool(body, "price_display_verified", required=False)
    roaming = validation.as_enum(body, "roaming_ocpi_version", OCPI_VERSIONS, required=False)

    updates = {
        "contactless_enabled": contactless,
        "plug_and_charge_enabled": plug_and_charge,
        "price_display_verified": price_display,
        "roaming_ocpi_version": roaming,
    }
    for field, value in updates.items():
        if value is not None:
            port[field] = value
    db.touch(port)
    return object_response(serialize.charging_port(port))


@bp.post("/charging-ports/<port_id>/terminal-certification")
@endpoint("ComplianceAuditor")
def certify_terminal(port_id):
    port = lookup.port(port_id)
    body = validation.json_body()
    outcome = validation.as_enum(body, "certification_status", CERTIFICATION_OUTCOMES)

    port["terminal_certification_status"] = outcome
    db.touch(port)

    if outcome == "REVOKED" and port["service_state"] == "IN_SERVICE":
        cascades.create_system_outage(port, "TERMINAL_CERT_REVOKED", "MAJOR")
        cascades.port_out_of_service(port)

    return object_response(serialize.charging_port(port))


@bp.post("/charging-ports/<port_id>/retire")
@endpoint("NetworkOperator")
def retire_port(port_id):
    port = lookup.port(port_id)
    if port["service_state"] == "RETIRED":
        raise err("ERR_ALREADY_TERMINAL", "The dispenser is already RETIRED.")
    if port["maintenance_state"] != "NONE":
        raise err("ERR_INVALID_STATE",
                  "A dispenser with an in-flight repair may not be retired.")

    port["service_state"] = "RETIRED"
    port["retired_at"] = clock.now()
    db.touch(port)
    return object_response(serialize.charging_port(port))
