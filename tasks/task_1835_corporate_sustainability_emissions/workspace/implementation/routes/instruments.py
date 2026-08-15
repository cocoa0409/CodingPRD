"""Renewable instruments: registration, retirement, void-retirement (PRD 3.6)."""
from flask import Blueprint, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_state, not_found
from http_util import (
    MANAGER,
    READ_ROLES,
    get_body,
    parse_pagination,
    require_roles,
    v_enum,
    v_int,
    v_num,
    v_str,
)
from store import db, new_entity, touch

bp = Blueprint("instruments", __name__, url_prefix="/sustainability")

TECHNOLOGIES = {"SOLAR", "WIND", "HYDRO"}
COLLECTING = ("DATA_COLLECTION", "UNDER_REVIEW")


def load_instrument(instrument_id):
    inst = db.instruments.get(instrument_id)
    if inst is None:
        raise not_found(f"RenewableInstrument {instrument_id} not found")
    return inst


@bp.route("/instruments", methods=["POST"])
@require_roles(MANAGER)
def create_instrument():
    body = get_body()
    registry = v_str(body, "registry")
    serial_number = v_str(body, "serial_number")
    technology = v_enum(body, "technology", TECHNOLOGIES)
    vintage_year = v_int(body, "vintage_year")
    quantity_mwh = v_num(body, "quantity_mwh", gt=0)
    # Priority 13: (registry, serial_number) unique among non-EXPIRED instruments.
    for other in db.instruments.values():
        if (
            other["status"] != "EXPIRED"
            and other["registry"] == registry
            and other["serial_number"] == serial_number
        ):
            raise err(
                "ERR_DUPLICATE_INSTRUMENT_SERIAL",
                409,
                "Another non-EXPIRED instrument has the same registry and serial_number",
            )
    inst = new_entity(
        {
            "registry": registry,
            "serial_number": serial_number,
            "technology": technology,
            "vintage_year": vintage_year,
            "quantity_mwh": quantity_mwh,
            "status": "PROCURED",
            "retired_for_cycle_id": None,
            "retired_for_site_id": None,
        }
    )
    db.instruments[inst["id"]] = inst
    return ok(domain.ser_instrument(inst), status=201)


@bp.route("/instruments/<instrument_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_instrument(instrument_id):
    return ok(domain.ser_instrument(load_instrument(instrument_id)))


@bp.route("/instruments", methods=["GET"])
@require_roles(*READ_ROLES)
def list_instruments():
    limit, offset = parse_pagination()
    items = sorted(db.instruments.values(), key=lambda x: x["_seq"])
    status = request.args.get("status")
    rcid = request.args.get("retired_for_cycle_id")
    rsid = request.args.get("retired_for_site_id")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if rcid is not None:
        items = [i for i in items if i["retired_for_cycle_id"] == rcid]
    if rsid is not None:
        items = [i for i in items if i["retired_for_site_id"] == rsid]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_instrument(i) for i in page], limit, offset, total)


@bp.route("/instruments/<instrument_id>/retire", methods=["POST"])
@require_roles(MANAGER)
def retire_instrument(instrument_id):
    body = get_body()
    # Priority 3: path id, then body FKs in input order.
    inst = load_instrument(instrument_id)
    for key, table in (("cycle_id", db.cycles), ("site_id", db.sites)):
        v = body.get(key)
        if v is not None and (not isinstance(v, str) or v not in table):
            raise not_found(f"Field {key} does not resolve to an existing resource")
    # Priority 4: request shape.
    cycle = db.cycles[v_str(body, "cycle_id")]
    site = db.sites[v_str(body, "site_id")]
    # Priority 6, in PRD 3.6 gauntlet order: instrument state, then cycle gate.
    if inst["status"] != "PROCURED":
        raise invalid_state(
            f"RenewableInstrument in status {inst['status']} cannot be retired"
        )
    if cycle["status"] not in COLLECTING:
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not permit instrument retirement",
        )
    # Priority 9: vintage window [cycle.reporting_year - 3, cycle.reporting_year],
    # inclusive on both ends.
    year = cycle["reporting_year"]
    if not (year - 3 <= inst["vintage_year"] <= year):
        raise err(
            "ERR_VINTAGE_INELIGIBLE",
            422,
            "Instrument vintage_year is outside the eligible window",
        )
    # Priority 16: the target site must be ACTIVE.
    if site["status"] != "ACTIVE":
        raise err("ERR_SITE_INACTIVE", 422, "Target site is not ACTIVE")
    inst["retired_for_cycle_id"] = cycle["id"]
    inst["retired_for_site_id"] = site["id"]
    inst["status"] = "RETIRED"
    # Full three-link retirement cascade; both versions advance.
    calc.cascade_staleness(cycle)
    touch(inst)
    touch(cycle)
    return ok(domain.ser_instrument(inst))


@bp.route("/instruments/<instrument_id>/void-retirement", methods=["POST"])
@require_roles(MANAGER)
def void_retirement(instrument_id):
    inst = load_instrument(instrument_id)
    get_body()  # body, if any, carries no fields
    if inst["status"] != "RETIRED":
        raise invalid_state(
            f"RenewableInstrument in status {inst['status']} has no retirement to void"
        )
    cycle = db.cycles.get(inst["retired_for_cycle_id"])
    if cycle is None or cycle["status"] not in COLLECTING:
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            "The formerly linked cycle is no longer collecting",
        )
    # Compensating reversal of the retirement cascade.
    inst["retired_for_cycle_id"] = None
    inst["retired_for_site_id"] = None
    inst["status"] = "PROCURED"
    calc.cascade_staleness(cycle)
    touch(inst)
    touch(cycle)
    return ok(domain.ser_instrument(inst))
