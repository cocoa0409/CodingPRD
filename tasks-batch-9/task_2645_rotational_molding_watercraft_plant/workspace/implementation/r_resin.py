"""Resin lot and resin charge routes (CASCADE-F lives here)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, q2, q3, touch
from errors import fail
from schema import (add_schema, body_json, coerce, date_filter, enum_filter,
                    str_filter)

bp = Blueprint("resin", __name__)

LOT_READ = ("PlantAdmin", "ResinTechnician", "MoldingOperator", "QualityInspector")

LOT_CREATE = {
    "lot_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "resin_grade": {"type": "enum", "required": True, "values": rt.RESIN_GRADES},
    "melt_index_g10min": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "color_code": {"type": "string", "required": True, "min_len": 2, "max_len": 16},
    "color_delta_e": {"type": "dec", "places": 2, "required": True, "min": 0},
    "additive_package_code": {"type": "string", "required": True,
                              "min_len": 2, "max_len": 16},
    "regrind_pct_by_mass": {"type": "dec", "places": 2, "min": 0, "max": 100,
                            "default": "0.00"},
    "cost_cents_per_kg": {"type": "int", "required": True, "min": 0},
    "received_kg": {"type": "dec", "places": 3, "required": True, "gt": 0},
    "expires_on": {"type": "date", "required": True},
}

QUARANTINE_SPEC = {"quarantine_reason": {"type": "string", "required": True,
                                         "min_len": 1, "max_len": 500}}
RELEASE_QUARANTINE_SPEC = {"release_note": {"type": "string", "required": True,
                                            "min_len": 1, "max_len": 500}}


@bp.route("/resin-lots", methods=["POST"])
def create_lot():
    auth.authenticate(("PlantAdmin", "ResinTechnician"))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, LOT_CREATE)
    checks.add(26, lambda: rt.unique_code("resin_lots", "lot_code", body.get("lot_code")))
    checks.run()
    row = coerce(body, LOT_CREATE)
    row["available_kg"] = row["received_kg"]
    row["reserved_kg"] = q3(ZERO)
    row["consumed_kg"] = q3(ZERO)
    row["status"] = "AVAILABLE"
    core.insert("resin_lots", row)
    svc.sweep_unblock_resin()
    return rt.one("resin_lots", row, 201)


@bp.route("/resin-lots", methods=["GET"])
def list_lots():
    auth.authenticate(LOT_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("resin_lots")
        rows = rt.filter_eq(rows, "resin_grade",
                            enum_filter("resin_grade", rt.RESIN_GRADES))
        rows = rt.filter_eq(rows, "color_code", str_filter("color_code"))
        rows = rt.filter_eq(rows, "additive_package_code",
                            str_filter("additive_package_code"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.LOT_STATUSES))
        cutoff = date_filter("expires_on_or_before")
        if cutoff is not None:
            rows = [r for r in rows if r["expires_on"] <= cutoff]
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("resin_lots", items[0])


@bp.route("/resin-lots/<resin_lot_id>", methods=["GET"])
def read_lot(resin_lot_id):
    auth.authenticate(LOT_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("resin_lots", resin_lot_id)))
    checks.run()
    return rt.one("resin_lots", holder["row"])


@bp.route("/resin-lots/<resin_lot_id>/quarantine", methods=["POST"])
def quarantine_lot(resin_lot_id):
    auth.authenticate(("QualityInspector",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("resin_lots", resin_lot_id)))
    add_schema(checks, body, QUARANTINE_SPEC)

    def state():
        if holder["row"]["status"] not in ("AVAILABLE", "DEPLETED"):
            fail("ERR_RESIN_LOT_NOT_AVAILABLE",
                 "Lot status is %s." % holder["row"]["status"])

    checks.add(36, state)
    checks.run()
    lot = holder["row"]
    # PRD.md section 3.2 counts the whole of CASCADE-F as one revision of the
    # lot: "(1) the lot moves `AVAILABLE` or `DEPLETED` to `QUARANTINED`;
    # (2) every `RESERVED` charge drawn on that lot becomes `RELEASED` ... moving
    # `charge_kg` from `reserved_kg` back to `available_kg` ... The lot's
    # `version` advances by 1."  Link 1 and link 2 both write this one row inside
    # one request, so the mass that comes back must not advance it a second time.
    base_version = lot["version"]
    # CASCADE-F link 1: the lot is quarantined.
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = body["quarantine_reason"]
    touch(lot)
    # Link 2: every RESERVED charge on the lot is released, mass returning to
    # available_kg.  Link 3: SCHEDULED cycles that held one are aborted.
    touched_cycles = []
    for charge in core.sorted_rows(core.rows("resin_charges")):
        if charge["resin_lot_id"] != lot["id"] or charge["status"] != "RESERVED":
            continue
        cycle = S.molding_cycles.get(charge["molding_cycle_id"])
        svc.release_charge(charge, "LOT_QUARANTINED")
        if cycle is not None and cycle["id"] not in touched_cycles:
            touched_cycles.append(cycle["id"])
    for cycle_id in touched_cycles:
        cycle = S.molding_cycles.get(cycle_id)
        if cycle is None:
            continue
        if cycle["status"] == "SCHEDULED":
            svc.abort_cycle(cycle, "LOT_QUARANTINED", "LOT_QUARANTINED")
        else:
            svc.recompute_cycle_rollups(cycle)
            touch(cycle)
    # Link 4: orders left without a qualified lot are blocked.
    svc.sweep_block_resin()
    lot["version"] = base_version + 1
    return rt.one("resin_lots", lot)


@bp.route("/resin-lots/<resin_lot_id>/release-quarantine", methods=["POST"])
def release_quarantine(resin_lot_id):
    auth.authenticate(("QualityInspector",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("resin_lots", resin_lot_id)))
    add_schema(checks, body, RELEASE_QUARANTINE_SPEC)

    def state():
        if holder["row"]["status"] != "QUARANTINED":
            fail("ERR_RESIN_LOT_NOT_AVAILABLE",
                 "Lot status is %s." % holder["row"]["status"])

    checks.add(36, state)
    checks.run()
    lot = holder["row"]
    lot["release_note"] = body["release_note"]
    if lot["available_kg"] > q3(ZERO):
        lot["status"] = "AVAILABLE"
        touch(lot)
        svc.sweep_unblock_resin()
    else:
        lot["status"] = "DEPLETED"
        touch(lot)
    return rt.one("resin_lots", lot)


# --------------------------------------------------------------------------
# Resin charges.
# --------------------------------------------------------------------------
CHARGE_CREATE = {
    "molding_cycle_id": {"type": "string", "required": True},
    "resin_lot_id": {"type": "string", "required": True},
    "created_by_technician_id": {"type": "string", "required": False},
    "charge_kg": {"type": "dec", "places": 3, "required": True, "gt": 0,
                  "bound_error": "ERR_INVALID_QUANTITY"},
    "regrind_kg": {"type": "dec", "places": 3, "min": 0, "default": "0.000",
                   "bound_error": "ERR_INVALID_QUANTITY"},
    "expected_resin_lot_version": {"type": "int", "required": True, "min": 1},
}

CHARGE_RELEASE = {"release_reason": {"type": "enum", "required": False,
                                     "values": rt.RELEASED_REASONS}}


@bp.route("/resin-charges", methods=["POST"])
def create_charge():
    ctx = auth.authenticate(("ResinTechnician",))
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, CHARGE_CREATE)

    def resolve():
        holder["cycle"] = rt.find("molding_cycles", body.get("molding_cycle_id"))
        holder["lot"] = rt.find("resin_lots", body.get("resin_lot_id"))
        holder["model"] = calc.model_of_cycle(holder["cycle"])

    def acting_identity():
        supplied = body.get("created_by_technician_id")
        if supplied is None:
            return
        rt.find("technicians", supplied)
        if supplied != ctx.user_id:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "created_by_technician_id must equal the acting identifier.")

    def regrind_share():
        values = coerce(body, CHARGE_CREATE)
        if values["regrind_kg"] > values["charge_kg"]:
            fail("ERR_INVALID_QUANTITY", "regrind_kg must not exceed charge_kg.")

    def cycle_state():
        if holder["cycle"]["status"] != "SCHEDULED":
            fail("ERR_CYCLE_INVALID_STATE",
                 "Cycle status is %s." % holder["cycle"]["status"])

    def lot_state():
        if holder["lot"]["status"] != "AVAILABLE":
            fail("ERR_RESIN_LOT_NOT_AVAILABLE",
                 "Lot status is %s." % holder["lot"]["status"])

    def qualification():
        lot, model = holder["lot"], holder["model"]
        if lot["resin_grade"] != model["resin_grade"] \
                or lot["additive_package_code"] != model["required_additive_package_code"] \
                or not (lot["color_code"] == model["master_color_code"]
                        or lot["color_delta_e"] <= model["max_color_delta_e"]) \
                or lot["regrind_pct_by_mass"] > model["max_regrind_pct"] \
                or lot["expires_on"] < core.clock_date() \
                or lot["available_kg"] < calc.min_shot_mass_kg(model):
            fail("ERR_RESIN_LOT_NOT_QUALIFIED",
                 "The lot does not qualify for this hull model.")
        if not calc.melt_index_in_band(model, lot["melt_index_g10min"]):
            fail("ERR_MELT_INDEX_OUT_OF_RANGE",
                 "The lot's melt index lies outside the model's band.")

    def regrind_ceiling():
        values = coerce(body, CHARGE_CREATE)
        participating = [c for c in calc.charges_of_cycle(holder["cycle"])
                         if c["status"] in ("RESERVED", "CONSUMED")]
        candidate = {"charge_kg": values["charge_kg"],
                     "regrind_kg": values["regrind_kg"]}
        blended = calc.blended_regrind_pct(participating + [candidate])
        if blended > holder["model"]["max_regrind_pct"]:
            fail("ERR_REGRIND_LIMIT_EXCEEDED",
                 "Blended regrind share %s exceeds the model ceiling." % blended)

    def mass_available():
        values = coerce(body, CHARGE_CREATE)
        if holder["lot"]["available_kg"] < values["charge_kg"]:
            fail("ERR_RESIN_INSUFFICIENT", "The lot cannot cover charge_kg.")

    def occ():
        if body["expected_resin_lot_version"] != holder["lot"]["version"]:
            fail("ERR_STALE_RESIN_LOT_VERSION",
                 "expected_resin_lot_version does not match the stored version.")

    checks.add(13, resolve)
    checks.add(13.5, acting_identity)
    checks.add(22.5, regrind_share)
    checks.add(30, lambda: auth.require_active(ctx.technician))
    checks.add(31, lambda: auth.require_cert(ctx.technician, ("RESIN_BLENDING",)))
    checks.add(35, cycle_state)
    checks.add(36, lot_state)
    checks.add(51, qualification)
    checks.add(52, regrind_ceiling)
    checks.add(72, mass_available)
    checks.add(81, occ)
    checks.run()

    values = coerce(body, CHARGE_CREATE)
    lot, cycle = holder["lot"], holder["cycle"]
    row = {
        "molding_cycle_id": cycle["id"],
        "resin_lot_id": lot["id"],
        "created_by_technician_id": ctx.user_id,
        "charge_kg": values["charge_kg"],
        "regrind_kg": values["regrind_kg"],
        "virgin_kg": q3(values["charge_kg"] - values["regrind_kg"]),
        "charge_regrind_pct": q2(values["regrind_kg"] / values["charge_kg"]
                                 * Decimal(100)),
        "status": "RESERVED",
        "released_reason": None,
    }
    core.insert("resin_charges", row)
    svc.lot_reserve(lot, values["charge_kg"])
    svc.recompute_cycle_rollups(cycle)
    touch(cycle)
    return rt.one("resin_charges", row, 201)


@bp.route("/resin-charges", methods=["GET"])
def list_charges():
    auth.authenticate(LOT_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("resin_charges")
        rows = rt.filter_eq(rows, "molding_cycle_id", str_filter("molding_cycle_id"))
        rows = rt.filter_eq(rows, "resin_lot_id", str_filter("resin_lot_id"))
        rows = rt.filter_eq(rows, "created_by_technician_id",
                            str_filter("created_by_technician_id"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.CHARGE_STATUSES))
        rows = rt.filter_eq(rows, "released_reason",
                            enum_filter("released_reason", rt.RELEASED_REASONS))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("resin_charges", items[0])


@bp.route("/resin-charges/<resin_charge_id>", methods=["GET"])
def read_charge(resin_charge_id):
    auth.authenticate(LOT_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("resin_charges", resin_charge_id)))
    checks.run()
    return rt.one("resin_charges", holder["row"])


@bp.route("/resin-charges/<resin_charge_id>/release", methods=["POST"])
def release_charge_route(resin_charge_id):
    ctx = auth.authenticate(("ResinTechnician",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("resin_charges", resin_charge_id)))
    add_schema(checks, body, CHARGE_RELEASE)
    checks.add(30, lambda: auth.require_active(ctx.technician))

    def state():
        if holder["row"]["status"] != "RESERVED":
            fail("ERR_CHARGE_NOT_RELEASABLE",
                 "Charge status is %s." % holder["row"]["status"])

    checks.add(37, state)
    checks.run()
    charge = holder["row"]
    cycle = S.molding_cycles.get(charge["molding_cycle_id"])
    revived = svc.release_charge(charge, body.get("release_reason") or "CYCLE_ABORTED")
    if cycle is not None:
        svc.recompute_cycle_rollups(cycle)
        touch(cycle)
    if revived:
        svc.sweep_unblock_resin()
    return rt.one("resin_charges", charge)
