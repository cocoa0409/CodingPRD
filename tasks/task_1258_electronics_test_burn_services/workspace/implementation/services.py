"""Shared business logic: projections, tallies, yields, suggestions, ledger, serializers."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import db
from errors import not_found
from util import fmt_ms, sec

AMBIENT_C = Decimal(25)
PURGE_GAP = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# common helpers
# ---------------------------------------------------------------------------

def now_str():
    """created_at / updated_at are stamped from the logical clock."""
    return fmt_ms(db.clock_dt)


def stamp_new(rec):
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now_str()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_str()


def get_or_404(coll, rid, what):
    rec = coll.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise not_found(what)
    return rec


def sorted_by_creation(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# lazy derivations
# ---------------------------------------------------------------------------

def equipment_effective_status(eq):
    if eq["status"] == "IN_SERVICE" and sec(db.clock_dt) >= sec(eq["_next_due_dt"]):
        return "CALIBRATION_DUE"
    return eq["status"]


def auth_effective_status(a):
    if a["status"] == "ACTIVE" and sec(a["_expires_dt"]) <= sec(db.clock_dt):
        return "EXPIRED"
    return a["status"]


# ---------------------------------------------------------------------------
# unit projection / lot tallies
# ---------------------------------------------------------------------------

def unit_effective_results(unit_id):
    rs = [
        r for r in db.results.values()
        if r["unit_id"] == unit_id and not r["voided"] and not r["excluded_from_tally"]
    ]
    rs.sort(key=lambda r: (r["_seq"], r["insertion_index"]))
    return rs


def unit_state(unit):
    """Derive (test_status, current_bin) by replaying tally-effective results."""
    if unit.get("force_failed"):
        return "FAILED", None
    rs = unit_effective_results(unit["id"])
    if not rs:
        return "UNTESTED", None
    last = rs[-1]
    return ("PASSED" if last["passed"] else "FAILED"), last["bin_code"]


def lot_units(lot_id):
    return sorted_by_creation([u for u in db.units.values() if u["lot_id"] == lot_id])


def lot_escape_count(lot_id):
    return sum(
        1 for r in db.rma_cases.values()
        if r["lot_id"] == lot_id and r["fa_status"] == "CLOSED"
        and r["fa_conclusion"] == "TEST_ESCAPE"
    )


def lot_tallies(lot):
    us = lot_units(lot["id"])
    counts = {"UNTESTED": 0, "PASSED": 0, "FAILED": 0}
    for u in us:
        s, _ = unit_state(u)
        counts[s] += 1
    return {
        "units_registered": len(us),
        "units_untested": counts["UNTESTED"],
        "units_passed": counts["PASSED"],
        "units_failed": counts["FAILED"],
        "retested_unit_count": sum(1 for u in us if u["retest_count"] >= 1),
        "escape_count": lot_escape_count(lot["id"]),
    }


def lot_yields(lot):
    """Return (first_pass_yield, final_yield) as exact Fractions."""
    first_pass = 0
    tested = 0
    passed = 0
    for u in lot_units(lot["id"]):
        rs = unit_effective_results(u["id"])
        if rs:
            tested += 1
            first = next((r for r in rs if r["insertion_index"] == 1), None)
            if first is not None and first["passed"]:
                first_pass += 1
        s, _ = unit_state(u)
        if s == "PASSED":
            passed += 1
    fpy = Fraction(first_pass, tested) if tested else Fraction(0, 1)
    final = Fraction(passed, lot["quantity"])
    return fpy, final


def compute_suggestion(lot):
    """disposition_suggestion: exact-fraction thresholds, first match wins."""
    t = lot_tallies(lot)
    fpy, _ = lot_yields(lot)
    esc = t["escape_count"]
    retest_rate = Fraction(t["retested_unit_count"], lot["quantity"])
    if esc >= 1:
        return "SCRAP_REVIEW"
    if fpy < Fraction(1, 2):
        return "SCRAP_REVIEW"
    if fpy >= Fraction(3, 4) and esc == 0 and retest_rate <= Fraction(1, 4):
        return "SHIP"
    return "MRB_REVIEW"


def bin_counts(lot_id):
    counts = {}
    for r in db.results.values():
        if r["lot_id"] == lot_id and not r["voided"] and not r["excluded_from_tally"]:
            k = str(r["bin_code"])
            counts[k] = counts.get(k, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# chamber slot ledger
# ---------------------------------------------------------------------------

def chamber_available_slots(chamber_id, exclude_reservation_id=None):
    ch = db.chambers[chamber_id]
    committed = sum(
        r["slot_count"] for r in db.reservations.values()
        if r["chamber_id"] == chamber_id
        and r["status"] in ("RESERVED", "IN_PROGRESS")
        and r["id"] != exclude_reservation_id
    )
    return ch["slot_count"] - committed


def cancel_reservation(r):
    r["status"] = "CANCELLED"
    touch(r)


# ---------------------------------------------------------------------------
# ESD containment
# ---------------------------------------------------------------------------

def esd_area_contained(area_code):
    for a in db.audits.values():
        if (
            a["area_code"] == area_code
            and a["status"] == "OPEN"
            and any(f.get("severity") == "MAJOR" for f in a["findings"])
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# burn-in profile duration
# ---------------------------------------------------------------------------

def burn_profile_duration(profile):
    """Per-segment ramp rounded half-up to whole minutes FIRST, then summed."""
    prev = AMBIENT_C
    total = 0
    for seg in profile:
        target = Decimal(str(seg["target_temp_c"]))
        rate = Decimal(str(seg["ramp_rate_c_per_min"]))
        soak = seg["soak_minutes"]
        ramp = (abs(target - prev) / rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(ramp) + int(soak)
        prev = target
    return total


# ---------------------------------------------------------------------------
# reservation window checks
# ---------------------------------------------------------------------------

def check_overlap(chamber_id, s_dt, e_dt, exclude_id=None):
    from errors import ApiError, ERR_SLOT_OVERLAP
    for ex in db.reservations.values():
        if ex["chamber_id"] != chamber_id or ex["status"] == "CANCELLED":
            continue
        if ex["id"] == exclude_id:
            continue
        if s_dt < ex["_end_dt"] and ex["_start_dt"] < e_dt:
            raise ApiError(ERR_SLOT_OVERLAP, 409, "Reservation window overlaps an existing reservation")


def check_purge_buffer(chamber_id, profile_class, s_dt, e_dt, exclude_id=None):
    from errors import ApiError, ERR_PROFILE_BUFFER_VIOLATION
    for ex in db.reservations.values():
        if ex["chamber_id"] != chamber_id or ex["status"] == "CANCELLED":
            continue
        if ex["id"] == exclude_id:
            continue
        if ex["profile_class"] == profile_class:
            continue  # same-class runs may abut
        if not (s_dt >= ex["_end_dt"] + PURGE_GAP or e_dt <= ex["_start_dt"] - PURGE_GAP):
            raise ApiError(
                ERR_PROFILE_BUFFER_VIOLATION, 409,
                "Different profile class runs require a 30-minute purge gap",
            )


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def ser_customer(c):
    return {
        "id": c["id"], "name": c["name"], "tier": c["tier"],
        "requires_esd_certification": c["requires_esd_certification"],
        "account_status": c["account_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_program(p):
    return {
        "id": p["id"], "customer_id": p["customer_id"], "part_number": p["part_number"],
        "revision": p["revision"], "supersedes_program_id": p["supersedes_program_id"],
        "bin_map": p["bin_map"], "max_retests_per_unit": p["max_retests_per_unit"],
        "burn_profile": p["burn_profile"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_fixture(f):
    return {
        "id": f["id"], "program_id": f["program_id"], "serial_number": f["serial_number"],
        "site_count": f["site_count"], "status": f["status"],
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }


def ser_chamber(ch):
    return {
        "id": ch["id"], "name": ch["name"], "area_code": ch["area_code"],
        "slot_count": ch["slot_count"],
        "supported_profile_classes": ch["supported_profile_classes"],
        "status": ch["status"],
        "available_slots": chamber_available_slots(ch["id"]),
        "created_at": ch["created_at"], "updated_at": ch["updated_at"], "version": ch["version"],
    }


def ser_reservation(r):
    return {
        "id": r["id"], "chamber_id": r["chamber_id"], "lot_id": r["lot_id"],
        "fixture_id": r["fixture_id"], "profile_class": r["profile_class"],
        "start_at": r["start_at"], "end_at": r["end_at"], "slot_count": r["slot_count"],
        "planned_duration_minutes": r["planned_duration_minutes"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_lot(lot):
    t = lot_tallies(lot)
    return {
        "id": lot["id"], "customer_id": lot["customer_id"], "program_id": lot["program_id"],
        "part_number": lot["part_number"], "quantity": lot["quantity"],
        "status": lot["status"],
        "units_registered": t["units_registered"],
        "units_untested": t["units_untested"],
        "units_passed": t["units_passed"],
        "units_failed": t["units_failed"],
        "retested_unit_count": t["retested_unit_count"],
        "escape_count": t["escape_count"],
        "suggested_disposition": lot["suggested_disposition"],
        "created_at": lot["created_at"], "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def ser_unit(u):
    status, current_bin = unit_state(u)
    return {
        "id": u["id"], "lot_id": u["lot_id"], "serial_number": u["serial_number"],
        "test_status": status, "current_bin": current_bin, "retest_count": u["retest_count"],
        "created_at": u["created_at"], "updated_at": u["updated_at"], "version": u["version"],
    }


def ser_result(r):
    # TestResult is an immutable event record: only id + created_at, no updated_at/version.
    return {
        "id": r["id"], "unit_id": r["unit_id"], "lot_id": r["lot_id"],
        "program_id": r["program_id"], "fixture_id": r["fixture_id"],
        "equipment_id": r["equipment_id"], "bin_code": r["bin_code"], "passed": r["passed"],
        "insertion_index": r["insertion_index"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "consumed_authorization_id": r["consumed_authorization_id"],
        "voided": r["voided"], "void_reason": r["void_reason"],
        "excluded_from_tally": r["excluded_from_tally"],
        "created_at": r["created_at"],
    }


def ser_authorization(a):
    return {
        "id": a["id"], "unit_id": a["unit_id"], "reason": a["reason"],
        "authorized_by_user_id": a["authorized_by_user_id"], "expires_at": a["expires_at"],
        "status": auth_effective_status(a),
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def ser_equipment(eq):
    return {
        "id": eq["id"], "customer_id": eq["customer_id"],
        "equipment_type": eq["equipment_type"], "serial_number": eq["serial_number"],
        "calibration_interval_days": eq["calibration_interval_days"],
        "last_calibrated_at": eq["last_calibrated_at"],
        "next_calibration_due": eq["next_calibration_due"],
        "status": equipment_effective_status(eq),
        "created_at": eq["created_at"], "updated_at": eq["updated_at"], "version": eq["version"],
    }


def ser_maintenance_order(o):
    return {
        "id": o["id"], "target_type": o["target_type"], "target_id": o["target_id"],
        "kind": o["kind"], "window_start": o["window_start"], "window_end": o["window_end"],
        "status": o["status"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"], "area_code": a["area_code"], "findings": a["findings"],
        "corrective_actions": a["corrective_actions"], "outcome": a["outcome"],
        "auditor_user_id": a["auditor_user_id"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def ser_rma(r):
    return {
        "id": r["id"], "lot_id": r["lot_id"], "unit_id": r["unit_id"],
        "failure_mode": r["failure_mode"], "fa_status": r["fa_status"],
        "fa_conclusion": r["fa_conclusion"],
        "created_by_customer_id": r["created_by_customer_id"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_review(rv):
    return {
        "id": rv["id"], "lot_id": rv["lot_id"],
        "suggested_disposition": rv["suggested_disposition"], "decision": rv["decision"],
        "rationale": rv["rationale"], "decided_by_user_id": rv["decided_by_user_id"],
        "status": rv["status"],
        "created_at": rv["created_at"], "updated_at": rv["updated_at"], "version": rv["version"],
    }
