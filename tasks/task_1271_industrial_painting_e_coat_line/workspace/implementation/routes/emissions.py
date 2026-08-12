"""ColorChanges, VocPermits, EmissionEntries, logical clock (PRD SS3.8-SS3.9, SS2.11)."""
from datetime import timedelta

from flask import request

from db import STORE, clock_now, set_clock
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_color_change, ser_voc_permit, ser_emission_entry
from services import (
    D, new_common, new_event, touch, lot_outstanding, spec_of,
    purge_cost_cents, purge_voc_kg, theoretical_voc_kg, round_half_up,
    covering_permit, post_emission, cap_would_exceed, PURGE_BUFFER_MIN,
)
from validators import get_body, req, as_str, as_num, as_dt

from . import bp


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


def _fmt_instant(dt):
    if dt.microsecond:
        frac = ("%06d" % dt.microsecond).rstrip("0")
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "." + frac + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


# --- ColorChange -------------------------------------------------------------

@bp.post("/ecoat/color-changes")
@require_roles("LineScheduler")
def create_color_change():
    body = get_body()
    paint_line_id = as_str(req(body, "paint_line_id"), "paint_line_id")
    to_color = as_str(req(body, "to_color_code"), "to_color_code")
    liters = as_num(req(body, "purge_solvent_liters"), "purge_solvent_liters")
    if liters <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "purge_solvent_liters must be greater than zero")
    ws_raw = req(body, "window_start_utc")
    we_raw = req(body, "window_end_utc")
    ws = as_dt(ws_raw, "window_start_utc")
    we = as_dt(we_raw, "window_end_utc")
    if we <= ws:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "window_end_utc must be after window_start_utc")

    line = STORE["paint_lines"].get(paint_line_id)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "paint_line_id does not exist")
    if to_color == line["current_color_code"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_color_code must differ from the line's current_color_code")

    # Buffered-window conflict (rung 8): a slot starting within the 30-minute
    # post-purge buffer still collides.
    buffered_end = we + timedelta(minutes=PURGE_BUFFER_MIN)
    for s in STORE["run_slots"].values():
        if (s["paint_line_id"] == paint_line_id
                and s["status"] in ("SCHEDULED", "RUNNING")
                and s["_start"] < buffered_end and s["_end"] > ws):
            raise ApiError("ERR_COLOR_CHANGE_CONFLICT", 409,
                           "Changeover window (+30 min post-buffer) collides with a "
                           "SCHEDULED/RUNNING slot on the line")

    # VOC fiscal gate (rung 10).
    permit = covering_permit()
    if permit is None:
        raise ApiError("ERR_NO_ACTIVE_PERMIT", 409,
                       "No non-CLOSED VOC permit covers the current logical clock")
    voc = purge_voc_kg(liters)
    if cap_would_exceed(permit, voc):
        raise ApiError("ERR_VOC_CAP_EXCEEDED", 409,
                       "used_kg + reserved_kg + purge_voc_kg would exceed cap_kg")

    cost = purge_cost_cents(liters)
    change = new_event()
    change.update({
        "paint_line_id": paint_line_id,
        "from_color_code": line["current_color_code"],
        "to_color_code": to_color,
        "window_start_utc": ws_raw, "window_end_utc": we_raw,
        "purge_solvent_liters": liters,
        "purge_cost_cents": cost,
        "purge_voc_kg": voc,
        "allocation_method": line["allocation_policy"],
    })
    STORE["color_changes"][change["id"]] = change

    post_emission(permit, "PURGE_SOLVENT", voc, "METERED",
                  color_change_id=change["id"])
    line["current_color_code"] = to_color
    touch(line)

    # Allocate the purge cost to QUEUED lots whose spec color matches.
    targets = [l for l in STORE["lots"].values()
               if l["status"] == "QUEUED"
               and spec_of(l) is not None
               and spec_of(l)["color_code"] == to_color]
    targets.sort(key=lambda l: (l["created_at"], -l["part_quantity"], l["_seq"]))
    if targets:
        if line["allocation_policy"] == "FULL_TO_NEXT_LOT":
            targets[0]["purge_alloc_cents"] += cost
            touch(targets[0])
        else:  # PRO_RATA_BY_PARTS
            total_parts = sum(l["part_quantity"] for l in targets)
            assigned = 0
            for i, lot in enumerate(targets):
                if i < len(targets) - 1:
                    share = int(round_half_up(
                        D(cost) * lot["part_quantity"] / D(total_parts), 0))
                    assigned += share
                else:
                    share = cost - assigned
                lot["purge_alloc_cents"] += share
                touch(lot)
    return success_object(ser_color_change(change), 201)


@bp.get("/ecoat/color-changes/<cid>")
@require_roles(*ROLES)
def get_color_change(cid):
    return success_object(ser_color_change(_get_or_404("color_changes", cid)))


@bp.get("/ecoat/color-changes")
@require_roles(*ROLES)
def list_color_changes():
    items = list(STORE["color_changes"].values())
    paint_line_id = request.args.get("paint_line_id")
    if paint_line_id is not None:
        items = [c for c in items if c["paint_line_id"] == paint_line_id]
    page, meta = paginate(items, ser_color_change)
    return success_list(page, meta)


# --- VocPermit ---------------------------------------------------------------

@bp.post("/ecoat/voc-permits")
@require_roles("PlantAdmin")
def create_voc_permit():
    body = get_body()
    ps_raw = req(body, "period_start")
    pe_raw = req(body, "period_end")
    ps = as_dt(ps_raw, "period_start")
    pe = as_dt(pe_raw, "period_end")
    if pe <= ps:
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_end must be after period_start")
    cap = as_num(req(body, "cap_kg"), "cap_kg")
    permit = new_common()
    permit.update({
        "period_start": ps_raw, "period_end": pe_raw,
        "_period_start": ps, "_period_end": pe,
        "cap_kg": cap,
        "_used_kg": D(0), "_reserved_kg": D(0),
        "status": "ACTIVE",
    })
    STORE["voc_permits"][permit["id"]] = permit
    return success_object(ser_voc_permit(permit), 201)


@bp.get("/ecoat/voc-permits/<pid>")
@require_roles(*ROLES)
def get_voc_permit(pid):
    return success_object(ser_voc_permit(_get_or_404("voc_permits", pid)))


@bp.post("/ecoat/voc-permits/<pid>/close")
@require_roles("PlantAdmin")
def close_voc_permit(pid):
    permit = _get_or_404("voc_permits", pid)
    if permit["status"] == "CLOSED":
        raise ApiError("ERR_PERMIT_PERIOD_CLOSED", 409,
                       "Operation targets a CLOSED permit")
    if clock_now() <= permit["_period_end"]:
        raise ApiError("ERR_PERMIT_NOT_EXPIRED", 409,
                       "Permit close requires the current logical clock past period_end")

    # Reconciliation: theoretical total over lots with a COMPLETED run slot
    # whose completion timestamp falls in the half-open period, minus the
    # metered total posted to this permit.
    ps, pe = permit["_period_start"], permit["_period_end"]
    theoretical_total = D(0)
    for lot in STORE["lots"].values():
        completed_in_period = any(
            s["lot_id"] == lot["id"] and s["status"] == "COMPLETED"
            and s["_completed_at"] is not None
            and ps <= s["_completed_at"] < pe
            for s in STORE["run_slots"].values()
        )
        if completed_in_period:
            spec = spec_of(lot)
            if spec is not None:
                theoretical_total += theoretical_voc_kg(spec, lot_outstanding(lot))
    metered_total = D(0)
    for e in STORE["emission_entries"].values():
        if e["permit_id"] == permit["id"] and e["source_type"] == "PAINT_USAGE_METERED":
            metered_total += e["voc_kg"]
    adjustment = round_half_up(theoretical_total - metered_total, 3)

    post_emission(permit, "CLOSEOUT_ADJUSTMENT", adjustment, "ADJUSTMENT")

    # Settle: CLOSED only at or under the cap; otherwise EXCEEDED.
    permit["status"] = "EXCEEDED" if permit["_used_kg"] > D(permit["cap_kg"]) else "CLOSED"
    touch(permit)
    return success_object(ser_voc_permit(permit))


@bp.get("/ecoat/voc-permits/<pid>/emission-entries")
@require_roles(*ROLES)
def list_permit_entries(pid):
    _get_or_404("voc_permits", pid)
    items = [e for e in STORE["emission_entries"].values() if e["permit_id"] == pid]
    page, meta = paginate(items, ser_emission_entry)
    return success_list(page, meta)


# --- EmissionEntry -----------------------------------------------------------

@bp.get("/ecoat/emission-entries")
@require_roles(*ROLES)
def list_emission_entries():
    items = list(STORE["emission_entries"].values())
    permit_id = request.args.get("permit_id")
    source_lot_id = request.args.get("source_lot_id")
    source_color_change_id = request.args.get("source_color_change_id")
    if permit_id is not None:
        items = [e for e in items if e["permit_id"] == permit_id]
    if source_lot_id is not None:
        items = [e for e in items if e["source_lot_id"] == source_lot_id]
    if source_color_change_id is not None:
        items = [e for e in items if e["source_color_change_id"] == source_color_change_id]
    page, meta = paginate(items, ser_emission_entry)
    return success_list(page, meta)


@bp.get("/ecoat/emission-entries/<eid>")
@require_roles(*ROLES)
def get_emission_entry(eid):
    return success_object(ser_emission_entry(_get_or_404("emission_entries", eid)))


# --- Logical clock -----------------------------------------------------------

@bp.post("/ecoat/_clock/set_current_utc")
@require_roles("PlantAdmin")
def set_current_utc():
    body = get_body()
    dt = as_dt(req(body, "to_iso8601"), "to_iso8601")
    set_clock(dt)
    return success_object({"current_utc": _fmt_instant(clock_now())})
