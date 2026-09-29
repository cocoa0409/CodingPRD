"""Changeover events: purge windows, provisional and reconciled scrap, cullet recovery."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import q2, q4
from db import clock_now, new_row, store, touch
from errors import fail
from middleware import authenticate, require_plant_owned
from refs import apply_filters, get_changeover, get_plant, get_run
from response import created_response, list_response, object_response
from validate import body, dec_field, instant_field, int_field, present

bp = Blueprint("changeovers", __name__)

READ_ROLES = ("CorporateOps", "PlantOperator", "QualityEngineer")
BUFFER = timedelta(minutes=calc.CHANGEOVER_PURGE_BUFFER_MIN)
LIVE_CHANGEOVER_STATUSES = ("OPEN", "CLOSED")


def _closed_intervals_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/changeover-events")
def open_changeover():
    authenticate(("PlantOperator",))
    payload = body()
    if present(payload, "plant_id"):
        require_plant_owned(payload["plant_id"])

    line_index = int_field(payload, "line_index")
    start_raw, start_dt = instant_field(payload, "window_start")
    end_raw, end_dt = instant_field(payload, "window_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")

    if not present(payload, "plant_id"):
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    plant = get_plant(payload["plant_id"])
    if not present(payload, "outgoing_run_id"):
        fail("ERR_INVALID_REQUEST", "outgoing_run_id is required")
    outgoing = get_run(payload["outgoing_run_id"])
    if not present(payload, "incoming_run_id"):
        fail("ERR_INVALID_REQUEST", "incoming_run_id is required")
    incoming = get_run(payload["incoming_run_id"])

    # rung 8 — state and cross-row coherence
    if outgoing["run_status"] not in ("PACKAGED", "CLOSED"):
        fail("ERR_INVALID_STATE", "the outgoing run must be PACKAGED or CLOSED")
    if incoming["run_status"] not in ("SCHEDULED", "HELD"):
        fail("ERR_INVALID_STATE", "the incoming run must be SCHEDULED or HELD")
    if outgoing["plant_id"] != plant["id"] or incoming["plant_id"] != plant["id"]:
        fail("ERR_INVALID_STATE", "both runs must belong to the named plant")
    if outgoing["line_index"] != line_index or incoming["line_index"] != line_index:
        fail("ERR_INVALID_STATE", "both runs must sit on the named line_index")

    # rung 11 — inflated closed-window conflict, then the line index range
    new_start = start_dt - BUFFER
    new_end = end_dt + BUFFER
    for other in store.changeovers.values():
        if other["plant_id"] != plant["id"] or other["line_index"] != line_index:
            continue
        if other["status"] not in LIVE_CHANGEOVER_STATUSES:
            continue
        if _closed_intervals_intersect(new_start, new_end,
                                       other["_window_start_dt"] - BUFFER,
                                       other["_window_end_dt"] + BUFFER):
            fail("ERR_CHANGEOVER_WINDOW_CONFLICT",
                 "the buffered purge window intersects changeover %s" % other["id"])
    if line_index < 1 or line_index > plant["production_line_count"]:
        fail("ERR_LINE_INDEX_OUT_OF_RANGE", "line_index is outside the plant's line count")

    from_line = store.product_lines[outgoing["product_line_id"]]
    to_line = store.product_lines[incoming["product_line_id"]]
    from_width = Decimal(from_line["width_in"])
    to_width = Decimal(to_line["width_in"])
    # rung 12
    if abs(to_width - from_width) > Decimal(plant["max_width_change_in"]):
        fail("ERR_WIDTH_CHANGE_OUT_OF_RANGE",
             "the batt-width step exceeds the plant's max_width_change_in")

    delta_4, delta_2 = calc.density_delta(from_line["density_pcf"], to_line["density_pcf"])
    facing_changed = from_line["facing_type"] != to_line["facing_type"]
    purge_min = calc.purge_minutes(delta_2, from_width != to_width, facing_changed)
    provisional = calc.provisional_scrap_kg(purge_min, from_line["mass_rate_kg_per_min"])

    row = new_row()
    row.update({
        "plant_id": plant["id"],
        "outgoing_run_id": outgoing["id"],
        "incoming_run_id": incoming["id"],
        "line_index": line_index,
        "window_start": start_raw,
        "window_end": end_raw,
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
        "from_density_pcf": from_line["density_pcf"],
        "to_density_pcf": to_line["density_pcf"],
        "from_width_in": from_line["width_in"],
        "to_width_in": to_line["width_in"],
        "facing_changed": facing_changed,
        "density_delta_pct": delta_4,
        "purge_minutes": purge_min,
        "provisional_scrap_kg": provisional,
        "weighed_trim_kg": None,
        "recovered_cullet_kg": None,
        "reconciled_scrap_kg": None,
        "scrap_variance_kg": None,
        "status": "OPEN",
    })
    store.changeovers[row["id"]] = row

    outgoing["changeover_scrap_kg"] = provisional
    touch(outgoing)
    return created_response(row)


@bp.get("/changeover-events/<changeover_id>")
def read_changeover(changeover_id):
    authenticate(READ_ROLES)
    return object_response(get_changeover(changeover_id))


@bp.get("/changeover-events")
def list_changeovers():
    authenticate(READ_ROLES)
    rows = apply_filters(store.changeovers.values(), {
        "plant_id": ("plant_id", "str"),
        "outgoing_run_id": ("outgoing_run_id", "str"),
        "incoming_run_id": ("incoming_run_id", "str"),
        "line_index": ("line_index", "int"),
        "status": ("status", "str"),
    })
    return list_response(rows)


@bp.post("/changeover-events/<changeover_id>/close")
def close_changeover(changeover_id):
    authenticate(("PlantOperator",))
    event = get_changeover(changeover_id)
    require_plant_owned(event["plant_id"])
    payload = body()
    weighed = dec_field(payload, "weighed_trim_kg")
    recovered = dec_field(payload, "recovered_cullet_kg")

    if event["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN changeover may be closed")
    if clock_now() < event["_window_end_dt"]:
        fail("ERR_INVALID_STATE", "the purge window has not closed yet")
    if weighed < 0 or recovered < 0 or recovered > weighed:
        fail("ERR_TRIM_MASS_INCONSISTENT",
             "recovered_cullet_kg must be between 0 and weighed_trim_kg")

    reconciled = q2(Decimal(weighed) - Decimal(recovered))
    variance = q2(Decimal(weighed) - Decimal(event["provisional_scrap_kg"]))
    event["weighed_trim_kg"] = q2(weighed)
    event["recovered_cullet_kg"] = q2(recovered)
    event["reconciled_scrap_kg"] = reconciled
    event["scrap_variance_kg"] = variance
    event["status"] = "CLOSED"
    touch(event)

    outgoing = store.runs[event["outgoing_run_id"]]
    outgoing["changeover_scrap_kg"] = reconciled
    touch(outgoing)

    plant = store.plants[event["plant_id"]]
    if recovered > 0:
        batch = new_row()
        batch.update({
            "plant_id": plant["id"],
            "source_run_id": outgoing["id"],
            "charged_run_id": None,
            "source_type": "CHANGEOVER_SCRAP",
            "mass_kg": q2(recovered),
            "status": "STAGED",
            "reject_reason": None,
        })
        store.cullet[batch["id"]] = batch
        ledger.recompute_plant_ledger(plant)
    return object_response(event)
