"""Program, posture, budget adjustments, ledger, snapshots listing, ops-runs, clock."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_posture_gate, err_invalid_state,
    err_stale_version,
)
from middleware import require_roles, get_actor
from response import success
from services.util import (
    req_str, req_int, req_number, opt_str, opt_int, opt_number, req_enum, body,
    paginate, serialize, hours_val, quarter_bounds, add_months,
)
from services import core

bp = Blueprint("programs", __name__)

POSTURES = {"ENROLLMENT_OPEN", "ENROLLMENT_PAUSED", "PROGRAM_SUSPENDED", "CLOSED"}
ALLOWED_POSTURE_MOVES = {
    ("ENROLLMENT_OPEN", "ENROLLMENT_PAUSED"),
    ("ENROLLMENT_PAUSED", "ENROLLMENT_OPEN"),
    ("ENROLLMENT_OPEN", "PROGRAM_SUSPENDED"),
    ("ENROLLMENT_PAUSED", "PROGRAM_SUSPENDED"),
    ("PROGRAM_SUSPENDED", "ENROLLMENT_OPEN"),
    ("ENROLLMENT_OPEN", "CLOSED"),
}


def _program_or_404(pid):
    p = db.programs.get(pid)
    if p is None:
        raise err_not_found("program")
    return p


def _serialize_program(p):
    out = serialize(p, "program")
    out.pop("_fiscal_year_start", None)
    out["unencumbered_cents"] = core.program_unencumbered(p)
    return out


@bp.route("/respite/programs", methods=["POST"])
def create_program():
    require_roles("FunderAdmin")
    data = body()
    name = req_str(data, "name")
    fys = req_str(data, "fiscal_year_start")
    try:
        fy_date = datetime.strptime(fys, "%Y-%m-%d").date()
    except ValueError:
        raise err_invalid_request("fiscal_year_start must be YYYY-MM-DD")
    total_budget = req_int(data, "total_budget_cents")
    qcap = req_number(data, "quarterly_cap_hours")
    acap = req_number(data, "annual_cap_hours")
    rate = req_int(data, "standard_rate_cents_per_hour")
    reserve = req_int(data, "emergency_reserve_hours")
    weekend = opt_number(data, "weekend_multiplier", 1.5)
    evening = opt_number(data, "evening_multiplier", 1.25)
    evening_start = opt_int(data, "evening_start_hour", 18)
    emerg = opt_number(data, "emergency_multiplier", 2.0)
    cred = opt_number(data, "credential_premium_multiplier", 1.10)
    overage = opt_number(data, "max_overage_pct", 1.10)
    expiry_days = opt_int(data, "voucher_expiry_days", 90)
    carryover = opt_number(data, "carryover_cap_pct", 0.25)
    noshow = opt_int(data, "no_show_grace_minutes", 30)
    autoclose = opt_int(data, "auto_close_grace_hours", 2)
    appeal_days = opt_int(data, "appeal_window_days", 30)

    base = db.new_common()
    prog = {
        **base,
        "name": name,
        "fiscal_year_start": fys,
        "_fiscal_year_start": fy_date,
        "posture": "ENROLLMENT_OPEN",
        "total_budget_cents": total_budget,
        "encumbered_cents": 0,
        "settled_cents": 0,
        "emergency_reserve_hours": reserve,
        "emergency_hours_used": 0.0,
        "quarterly_cap_hours": float(qcap),
        "annual_cap_hours": float(acap),
        "standard_rate_cents_per_hour": rate,
        "weekend_multiplier": float(weekend),
        "evening_multiplier": float(evening),
        "evening_start_hour": evening_start,
        "emergency_multiplier": float(emerg),
        "credential_premium_multiplier": float(cred),
        "max_overage_pct": float(overage),
        "voucher_expiry_days": expiry_days,
        "carryover_cap_pct": float(carryover),
        "no_show_grace_minutes": noshow,
        "auto_close_grace_hours": autoclose,
        "appeal_window_days": appeal_days,
        "ops_run_index": 0,
    }
    db.programs[prog["id"]] = prog
    return success(_serialize_program(prog), status=201)


@bp.route("/respite/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles("FunderAdmin", "Coordinator")
    p = _program_or_404(pid)
    return success(_serialize_program(p))


@bp.route("/respite/programs/<pid>/posture", methods=["POST"])
def program_posture(pid):
    require_roles("FunderAdmin")
    data = body()
    target = req_enum(data, "target_posture", POSTURES)
    p = _program_or_404(pid)
    cur = p["posture"]
    if (cur, target) not in ALLOWED_POSTURE_MOVES:
        raise err_invalid_state(f"Posture transition {cur} -> {target} not permitted")
    if target == "CLOSED":
        # guard: no live vouchers / claims / bookings in program
        for v in db.vouchers.values():
            if v["program_id"] == pid and v["status"] in ("ISSUED", "COMMITTED", "REDEEMED"):
                raise err_posture_gate("Live vouchers exist for this program")
        for c in db.claims.values():
            if c["program_id"] == pid and c["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "APPEALED"):
                raise err_posture_gate("Live claims exist for this program")
        for b in db.bookings.values():
            if b["program_id"] == pid and b["status"] in (
                "PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE",
            ):
                raise err_posture_gate("Live bookings exist for this program")
    p["posture"] = target
    db.touch(p)
    return success(_serialize_program(p))


@bp.route("/respite/programs/<pid>/budget-adjustments", methods=["POST"])
def budget_adjustment(pid):
    require_roles("FunderAdmin")
    data = body()
    delta = req_int(data, "delta_cents")
    reason = req_str(data, "reason")
    expected = data.get("expected_program_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_program_version is required and must be an integer")
    p = _program_or_404(pid)
    if p["version"] != expected:
        raise err_stale_version()
    new_total = p["total_budget_cents"] + delta
    if new_total < p["encumbered_cents"] + p["settled_cents"]:
        raise err_invalid_request(
            "total_budget_cents would fall below encumbered + settled"
        )
    p["total_budget_cents"] = new_total
    core.ledger_entry(p, "ADJUSTMENT", abs(delta), "program", p["id"], reason)
    db.touch(p)
    return success(_serialize_program(p), status=201)


@bp.route("/respite/programs/<pid>/budget-ledger", methods=["GET"])
def budget_ledger(pid):
    require_roles("FunderAdmin", "Coordinator")
    _program_or_404(pid)
    entry_type = request.args.get("entry_type")
    items = [e for e in db.ledger.values() if e["program_id"] == pid]
    if entry_type:
        items = [e for e in items if e["entry_type"] == entry_type]
    # newest first (per PRD). created_at ties are broken by insertion sequence
    # (the logical clock does not advance between ledger appends within a
    # single request, so id alone is not a deterministic tiebreak).
    items.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)), reverse=True)
    # manual pagination (paginate() sorts by created_at ASC, so we do our own here)
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize(e, "ledger") for e in page]
    return success(
        data,
        response_type="array",
        pagination={
            "limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total,
        },
    )


@bp.route("/respite/programs/<pid>/report-snapshots", methods=["GET"])
def list_snapshots(pid):
    require_roles("FunderAdmin")
    _program_or_404(pid)
    status = request.args.get("status")
    items = [s for s in db.snapshots.values() if s["program_id"] == pid]
    if status:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(s, "snapshot") for s in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/respite/programs/<pid>/allocations", methods=["GET"])
def list_program_allocations(pid):
    require_roles("Coordinator", "FunderAdmin")
    _program_or_404(pid)
    status = request.args.get("status")
    items = [a for a in db.allocations.values() if a["program_id"] == pid]
    if status:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(a, "allocation") for a in page],
        response_type="array",
        pagination=meta,
    )


# ---------------- ops-run ----------------
def _run_ops(program, run_type):
    now = db.now()
    pid = program["id"]

    # 1. voucher expiry sweep (ISSUED vouchers with expires_at <= now)
    for v in list(db.vouchers.values()):
        if v["program_id"] != pid:
            continue
        if v["status"] == "ISSUED" and v["expires_at"] <= now:
            core.expire_voucher(v)

    # 2. no-show sweep: CONFIRMED bookings with start_at + grace < now, no visit
    for b in list(db.bookings.values()):
        if b["program_id"] != pid or b["status"] != "CONFIRMED":
            continue
        has_visit = any(
            vr["booking_id"] == b["id"] for vr in db.visits.values()
        )
        if has_visit:
            continue
        if b["start_at"] + timedelta(minutes=program["no_show_grace_minutes"]) < now:
            b["status"] = "NO_SHOW"
            db.touch(b)
            core.release_booking(b)

    # 3. visit auto-close: OPEN visits with booking.end_at + grace < now
    for v in list(db.visits.values()):
        if v["status"] != "OPEN":
            continue
        b = db.bookings.get(v["booking_id"])
        if b is None or b["program_id"] != pid:
            continue
        if b["end_at"] + timedelta(hours=program["auto_close_grace_hours"]) < now:
            v["check_out_at"] = b["end_at"]
            v["auto_closed"] = True
            v["verified_minutes"] = core.compute_verified_minutes(
                v["check_in_at"], v["check_out_at"]
            )
            v["payable_minutes"] = core.compute_payable_minutes(
                v["verified_minutes"], b["committed_minutes"], program["max_overage_pct"]
            )
            v["status"] = "SUBMITTED"
            db.touch(v)

    # 4. provider credential lapse
    for p in list(db.providers.values()):
        if p["credential_status"] == "ACTIVE" and p.get("credential_expires_at") is not None:
            if p["credential_expires_at"] <= now:
                p["credential_status"] = "LAPSED"
                db.touch(p)

    # 5. caregiver redetermination flag
    for cg in list(db.caregivers.values()):
        if cg["status"] == "ACTIVE" and cg.get("redetermination_due_at") is not None:
            if cg["redetermination_due_at"] <= now:
                cg["status"] = "REDETERMINATION_PENDING"
                db.touch(cg)

    # 6. close past availability windows
    for w in list(db.windows.values()):
        if w["status"] in ("OPEN", "FULLY_BOOKED") and w["end_at"] <= now:
            w["status"] = "CLOSED"
            db.touch(w)

    # 7. QUARTER_ROLLOVER: close ended allocations and create next-quarter grants
    if run_type == "QUARTER_ROLLOVER":
        ended = [
            a for a in db.allocations.values()
            if a["program_id"] == pid
            and a["status"] in ("OPEN", "FROZEN")
            and a["period_end"] <= now
        ]

        def rollover_key(a):
            cg = db.caregivers.get(a["caregiver_id"])
            # latest APPROVED application's need_score
            apps = [
                ap for ap in db.applications.values()
                if ap["caregiver_id"] == a["caregiver_id"] and ap["status"] == "APPROVED"
            ]
            if apps:
                apps.sort(key=lambda ap: (ap["created_at"], ap["id"]))
                need = apps[-1]["need_score"]
            else:
                need = 0
            cg_created = cg["created_at"] if cg else datetime.min.replace(tzinfo=timezone.utc)
            return (-need, cg_created, a["id"])

        ended.sort(key=rollover_key)
        for a in ended:
            cg = db.caregivers.get(a["caregiver_id"])
            carry_cap = Decimal(str(program["quarterly_cap_hours"])) * Decimal(
                str(program["carryover_cap_pct"])
            )
            carry_cap = carry_cap.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            carry = min(float(carry_cap), a["available_hours"])
            old_status = a["status"]
            a["status"] = "CLOSED"
            db.touch(a)
            if cg is not None and cg["status"] != "DISENROLLED":
                # create next-quarter allocation
                new_start = a["period_end"]
                new_end_date = add_months(new_start.date(), 3)
                new_end = datetime(
                    new_end_date.year, new_end_date.month, new_end_date.day,
                    tzinfo=timezone.utc,
                )
                granted = float(
                    Decimal(str(program["quarterly_cap_hours"])) + Decimal(str(carry))
                )
                core.create_allocation(program, cg["id"], granted, new_start, new_end)

    # 8. ReportSnapshot
    program_allocs = [a for a in db.allocations.values() if a["program_id"] == pid]
    total_granted = sum(
        (Decimal(str(a["granted_hours"])) for a in program_allocs),
        start=Decimal("0"),
    )
    consumed_sum = sum(
        (Decimal(str(a["consumed_hours"])) for a in program_allocs),
        start=Decimal("0"),
    )
    reserved_sum = sum(
        (Decimal(str(a["reserved_hours"])) for a in program_allocs),
        start=Decimal("0"),
    )
    if total_granted == 0:
        projected = Decimal("0.00")
    else:
        projected = (
            (Decimal("100") * (consumed_sum + reserved_sum) / total_granted)
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    if program["total_budget_cents"] == 0:
        settled_pct = Decimal("0.00")
    else:
        settled_pct = (
            (Decimal("100") * Decimal(program["settled_cents"]) / Decimal(program["total_budget_cents"]))
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    paid_claims = [
        c for c in db.claims.values()
        if c["program_id"] == pid and c["status"] == "PAID"
    ]
    claims_paid_count = len(paid_claims)
    total_paid = sum(c["amount_cents"] for c in paid_claims)

    # period = calendar month of ops-run clock time
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    next_month_date = add_months(month_start.date(), 1)
    month_end = datetime(next_month_date.year, next_month_date.month, next_month_date.day, tzinfo=timezone.utc)

    base = db.new_common()
    snapshot = {
        **base,
        "program_id": pid,
        "period_start": month_start,
        "period_end": month_end,
        "status": "GENERATED",
        "utilization_projected_pct": float(projected),
        "utilization_settled_pct": float(settled_pct),
        "total_granted_hours": float(total_granted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "consumed_hours": float(consumed_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "reserved_hours": float(reserved_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "claims_paid_count": claims_paid_count,
        "total_paid_amount_cents": total_paid,
        "emergency_hours_used": hours_val(program["emergency_hours_used"]),
        # ops_run_index records the program's value at generation — i.e. the
        # value the program will hold *after* this run bumps it.
        "ops_run_index": program["ops_run_index"] + 1,
    }
    db.snapshots[snapshot["id"]] = snapshot

    # bump ops_run_index and program version
    program["ops_run_index"] += 1
    db.touch(program)
    return snapshot


@bp.route("/respite/programs/<pid>/ops-runs", methods=["POST"])
def ops_run(pid):
    require_roles("Coordinator")
    data = body()
    run_type = req_enum(data, "run_type", {"STANDARD", "QUARTER_ROLLOVER"})
    p = _program_or_404(pid)
    snapshot = _run_ops(p, run_type)
    return success(serialize(snapshot, "snapshot"), status=201)


# ---------------- clock ----------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("FunderAdmin")
    data = body()
    to = data.get("to_iso8601")
    if not isinstance(to, str):
        raise err_invalid_request("to_iso8601 is required")
    try:
        dt = db.parse_ts(to)
    except Exception:
        raise err_invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    db.set_clock(dt)
    return success({"current_utc": db.fmt_ts(db.now())})
