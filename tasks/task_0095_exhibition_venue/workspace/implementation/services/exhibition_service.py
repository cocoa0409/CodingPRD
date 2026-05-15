"""Exhibition lifecycle: create, open-intake, publish-allocation, start-setup, open-doors,
close-doors, close. Posture and cascades per PRD §3.1 / §2.6.
"""

from datetime import timedelta

import db
import clock
from errors import (
    AppError,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_SAFETY_INSPECTION_MISSING,
)
from services.common import (
    stamp_create,
    bump,
    check_occ,
    must_dict,
    write_audit,
)
from services import calculations


# -------- create --------
def create_exhibition(body: dict) -> dict:
    body = must_dict(body)
    required = ("name", "theme_code", "open_date", "close_date", "capacity_max")
    for f in required:
        if f not in body or body[f] is None or (isinstance(body[f], str) and body[f] == ""):
            raise AppError(ERR_INVALID_INPUT, f"Missing required field '{f}'.", 422)
    if not isinstance(body["capacity_max"], int) or body["capacity_max"] < 0:
        raise AppError(ERR_INVALID_INPUT, "capacity_max must be a non-negative integer.", 422)
    if clock.parse_iso(body["open_date"]) is None or clock.parse_iso(body["close_date"]) is None:
        raise AppError(ERR_INVALID_INPUT, "Invalid open_date/close_date.", 422)
    objection_hours = body.get("objection_window_hours", 72)
    if objection_hours is None:
        objection_hours = 72
    if not isinstance(objection_hours, int) or objection_hours < 0:
        raise AppError(ERR_INVALID_INPUT, "objection_window_hours must be a non-negative integer.", 422)

    row = {
        "name": body["name"],
        "theme_code": body["theme_code"],
        "open_date": body["open_date"],
        "close_date": body["close_date"],
        "capacity_max": int(body["capacity_max"]),
        "status": "DRAFT",
        "posture": "FROZEN",
        "live_occupancy": 0,
        "objection_window_hours": objection_hours,
        "allocation_published_at": None,
    }
    stamp_create(row)
    db.exhibitions[row["id"]] = row
    return row


# -------- open-intake: DRAFT → INTAKE_OPEN --------
def open_intake(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in DRAFT.", 409)
    if not (ex.get("theme_code") or "").strip():
        raise AppError(ERR_INVALID_STATE, "Exhibition theme_code is empty.", 409)
    # Require at least one Hall with an ACTIVE FloorPlanVersion.
    halls = [h for h in db.halls.values() if h["exhibition_id"] == exhibition_id]
    if not halls:
        raise AppError(ERR_INVALID_STATE, "Exhibition has no halls.", 409)
    has_active_plan = False
    for h in halls:
        for fp in db.floor_plans.values():
            if fp["hall_id"] == h["id"] and fp["status"] == "ACTIVE":
                has_active_plan = True
                break
        if has_active_plan:
            break
    if not has_active_plan:
        raise AppError(ERR_INVALID_STATE, "No active floor plan on any hall.", 409)
    check_occ(ex, body)
    ex["status"] = "INTAKE_OPEN"
    ex["posture"] = "FROZEN"
    bump(ex)
    return ex


# -------- publish-allocation: INTAKE_OPEN → ALLOCATION_PUBLISHED --------
def publish_allocation(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "INTAKE_OPEN":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in INTAKE_OPEN.", 409)
    # All applications must be in {QUALIFIED, REJECTED, WITHDRAWN}.
    terminal_app_statuses = {"QUALIFIED", "REJECTED", "WITHDRAWN", "ALLOCATED"}
    for a in db.applications.values():
        if a["exhibition_id"] == exhibition_id and a["status"] not in terminal_app_statuses:
            raise AppError(ERR_INVALID_STATE, "Not all applications are resolved.", 409)
    # At least one BoothAllocation in PROPOSED.
    proposed = [
        al for al in db.allocations.values()
        if al["exhibition_id"] == exhibition_id and al["status"] == "PROPOSED"
    ]
    if not proposed:
        raise AppError(ERR_INVALID_STATE, "No PROPOSED allocations to publish.", 409)
    check_occ(ex, body)

    now_iso = clock.iso()
    for al in proposed:
        booth = db.booths.get(al["booth_id"])
        if booth is None:
            # Should not happen — skip gracefully.
            continue
        quoted = calculations.booth_quoted_price(booth, ex)
        al["status"] = "PUBLISHED"
        al["quoted_price_cents"] = quoted
        al["published_at"] = now_iso
        booth["status"] = "ALLOCATED"
        bump(al)
        bump(booth)
        write_audit("ALLOCATION", al["id"], "PUBLISH", {
            "quoted_price_cents": quoted,
            "booth_id": booth["id"],
        })
    ex["status"] = "ALLOCATION_PUBLISHED"
    ex["allocation_published_at"] = now_iso
    bump(ex)
    return ex


# -------- start-setup: ALLOCATION_PUBLISHED → SETUP --------
def start_setup(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "ALLOCATION_PUBLISHED":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in ALLOCATION_PUBLISHED.", 409)
    # Each allocation must be CONFIRMED or REVOKED.
    for al in db.allocations.values():
        if al["exhibition_id"] == exhibition_id and al["status"] not in ("CONFIRMED", "REVOKED"):
            raise AppError(ERR_INVALID_STATE, "Not all allocations are CONFIRMED or REVOKED.", 409)
    # now() >= allocation_published_at + objection_window_hours
    pub_at = clock.parse_iso(ex.get("allocation_published_at"))
    if pub_at is None:
        raise AppError(ERR_INVALID_STATE, "No publication timestamp.", 409)
    deadline = pub_at + timedelta(hours=int(ex["objection_window_hours"]))
    if clock.now() < deadline:
        raise AppError(ERR_INVALID_STATE, "Objection window has not closed.", 409)
    check_occ(ex, body)
    ex["status"] = "SETUP"
    ex["posture"] = "RESTRICTED"
    bump(ex)
    return ex


# -------- open-doors: SETUP → OPEN --------
def open_doors(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "SETUP":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in SETUP.", 409)
    # PRE_OPEN PASS safety inspection on this exhibition.
    has_pre_open_pass = any(
        si["exhibition_id"] == exhibition_id
        and si["kind"] == "PRE_OPEN"
        and si["result"] == "PASS"
        for si in db.safety_inspections.values()
    )
    if not has_pre_open_pass:
        raise AppError(
            ERR_SAFETY_INSPECTION_MISSING,
            "PRE_OPEN PASS safety inspection required.",
            409,
        )
    open_dt = clock.parse_iso(ex.get("open_date"))
    if open_dt is None or clock.now() < open_dt:
        raise AppError(ERR_INVALID_STATE, "Current clock is before open_date.", 409)
    check_occ(ex, body)
    ex["status"] = "OPEN"
    ex["posture"] = "OPEN"
    bump(ex)
    return ex


# -------- close-doors: OPEN → TEARDOWN --------
def close_doors(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "OPEN":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in OPEN.", 409)
    close_dt = clock.parse_iso(ex.get("close_date"))
    if close_dt is None or clock.now() < close_dt:
        raise AppError(ERR_INVALID_STATE, "Current clock is before close_date.", 409)
    if int(ex.get("live_occupancy", 0)) != 0:
        raise AppError(ERR_INVALID_STATE, "Live occupancy is not zero.", 409)
    check_occ(ex, body)
    ex["status"] = "TEARDOWN"
    ex["posture"] = "RESTRICTED"
    # Void any Ticket still in ISSUED on this exhibition.
    for t in db.tickets.values():
        if t["exhibition_id"] == exhibition_id and t["status"] == "ISSUED":
            t["status"] = "VOID"
            bump(t)
    bump(ex)
    return ex


# -------- close: TEARDOWN → CLOSED --------
def close_exhibition(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if ex["status"] != "TEARDOWN":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in TEARDOWN.", 409)
    wo_terminal = {"BILLED", "RESOLVED", "CANCELLED"}
    for wo in db.work_orders.values():
        if wo["exhibition_id"] == exhibition_id and wo["status"] not in wo_terminal:
            raise AppError(ERR_INVALID_STATE, "Not all work orders are resolved.", 409)
    ent_terminal = {"FULFILLED", "MISSED", "MAKE_GOOD_ACCEPTED", "WAIVED"}
    # The scaffold's close-precondition: all entitlements in terminal states;
    # The side-effect: auto-MISS those still in {IN_PROGRESS, MAKE_GOOD_OFFERED}.
    # Read PRD §3.1: "every SponsorEntitlement to be in {FULFILLED, MISSED,
    # MAKE_GOOD_ACCEPTED, WAIVED}" — but then "auto-MISS any entitlement still
    # in IN_PROGRESS or MAKE_GOOD_OFFERED". The latter is the cascade that runs
    # AS PART OF the close transition: we allow IN_PROGRESS / MAKE_GOOD_OFFERED
    # and auto-MISS them here.
    for ent in db.entitlements.values():
        if ent["exhibition_id"] != exhibition_id:
            continue
        if ent["status"] in ent_terminal:
            continue
        if ent["status"] in ("IN_PROGRESS", "MAKE_GOOD_OFFERED"):
            continue   # will be auto-MISSED below
        if ent["status"] == "PLANNED":
            raise AppError(ERR_INVALID_STATE, "Entitlement still PLANNED.", 409)
    check_occ(ex, body)

    # Auto-MISS cascade.
    now_dt = clock.now()
    for ent in list(db.entitlements.values()):
        if ent["exhibition_id"] != exhibition_id:
            continue
        if ent["status"] in ("IN_PROGRESS", "MAKE_GOOD_OFFERED"):
            ent["status"] = "MISSED"
            ent["make_good_credit_cents"] = calculations.entitlement_make_good(
                ent["sponsor_tier"], ent["entitlement_code"]
            )
            ent["fulfillment_score"] = calculations.fulfillment_score_final(
                "MISSED",
                clock.parse_iso(ent.get("deadline")),
                now_dt,
            )
            bump(ent)
    ex["status"] = "CLOSED"
    ex["posture"] = "FROZEN"
    bump(ex)
    return ex


# -------- entitlement report (computed) --------
def entitlement_report(exhibition_id: str) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    closed = (ex["status"] == "CLOSED")
    entitlements = [e for e in db.entitlements.values() if e["exhibition_id"] == exhibition_id]
    status_counts: dict = {}
    total_make_good = 0
    score_rows = []
    for ent in entitlements:
        status_counts[ent["status"]] = status_counts.get(ent["status"], 0) + 1
        total_make_good += int(ent.get("make_good_credit_cents") or 0)
        if closed:
            score = float(ent.get("fulfillment_score") or 0.0)
        else:
            score = calculations.fulfillment_score_provisional(ent["status"])
        score_rows.append({
            "entitlement_id": ent["id"],
            "exhibitor_id": ent["exhibitor_id"],
            "entitlement_code": ent["entitlement_code"],
            "sponsor_tier": ent["sponsor_tier"],
            "status": ent["status"],
            "fulfillment_score": score,
            "make_good_credit_cents": int(ent.get("make_good_credit_cents") or 0),
            "deadline": ent.get("deadline"),
        })
    return {
        "exhibition_id": exhibition_id,
        "exhibition_status": ex["status"],
        "variant": "final" if closed else "provisional",
        "total_entitlements": len(entitlements),
        "status_counts": status_counts,
        "total_make_good_credit_cents": total_make_good,
        "entitlements": score_rows,
    }


# -------- occupancy snapshot --------
def occupancy(exhibition_id: str) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        from errors import ERR_NOT_FOUND
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    return {
        "exhibition_id": exhibition_id,
        "live_occupancy": int(ex.get("live_occupancy", 0)),
        "capacity_max": int(ex["capacity_max"]),
        "posture": ex["posture"],
        "status": ex["status"],
    }
