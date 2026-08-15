"""Clock, CardProgram, BinRange, and program economics endpoints."""
from datetime import datetime, timezone

from flask import Blueprint

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_int, opt_int, req_enum,
    new_entity, touch, pub, sort_created, get_or_404, require_roles,
    parse_dt, fmt_dt, now, apply_lazy, ser_program, ser_bin_range,
    NETWORKS, PRODUCT_CLASSES, TERMINATION_REASONS, BIN_PREFIX_RE, MONTH_RE,
)

bp = Blueprint("programs", __name__)

ALL_READ = ("ProgramManager", "ComplianceOfficer", "OperationsAnalyst",
            "FinanceController", "PlatformAdmin")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/issuing/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    raw = req_field(data, "to_iso8601")
    try:
        target = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO8601 timestamp")
    STORE["clock"] = target
    apply_lazy()
    return ok({"current_utc": fmt_dt(STORE["clock"])})


# ---------------------------------------------------------------------------
# CardProgram
# ---------------------------------------------------------------------------

@bp.post("/issuing/programs")
@require_roles("ProgramManager")
def create_program():
    data = body()
    program_code = req_field(data, "program_code")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_VALIDATION", 400, "program_code must be a non-empty string")
    product_class = req_enum(data, "product_class", PRODUCT_CLASSES)
    network = req_enum(data, "network", NETWORKS)
    currency_code = req_field(data, "currency_code")
    if not isinstance(currency_code, str) or len(currency_code) != 3:
        raise ApiError("ERR_VALIDATION", 400, "currency_code must be an ISO 4217 code")
    cap = req_int(data, "daily_spend_cap_cents", min_value=1)
    termination_reason = data.get("termination_reason")
    if termination_reason is not None and termination_reason not in TERMINATION_REASONS:
        raise ApiError("ERR_VALIDATION", 400, "invalid termination_reason")
    for p in STORE["programs"].values():
        if p["program_code"] == program_code:
            raise ApiError("ERR_VALIDATION", 409,
                           "program_code %s already exists" % program_code)
    p = new_entity()
    p.update({
        "program_code": program_code,
        "product_class": product_class,
        "network": network,
        "currency_code": currency_code,
        "daily_spend_cap_cents": cap,
        "authorization_rules_locked": False,
        "posture": "DRAFT",
        "terminated_at": None,
        "termination_reason": termination_reason,
        "_lock_ack_id": None,
        "_sunset_frozen": [],
    })
    STORE["programs"][p["id"]] = p
    return ok(ser_program(p), 201)


@bp.get("/issuing/programs")
@require_roles(*ALL_READ)
def list_programs():
    items = list(STORE["programs"].values())
    for param in ("posture", "network", "product_class"):
        val = __import__("flask").request.args.get(param)
        if val is not None:
            items = [p for p in items if p.get(param) == val]
    return ok_list([ser_program(p) for p in sort_created(items)])


def _get_program(pid):
    return get_or_404("programs", pid, "program")


@bp.get("/issuing/programs/<pid>")
@require_roles(*ALL_READ)
def get_program(pid):
    return ok(ser_program(_get_program(pid)))


@bp.put("/issuing/programs/<pid>")
@require_roles("ProgramManager")
def update_program(pid):
    p = _get_program(pid)
    data = body()
    if "expected_program_version" not in data or data["expected_program_version"] is None:
        raise ApiError("ERR_MISSING_OCC_FIELD", 400,
                       "expected_program_version is required")
    if data["expected_program_version"] != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_program_version does not match current version")
    if "daily_spend_cap_cents" in data and data["daily_spend_cap_cents"] is not None:
        v = data["daily_spend_cap_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ApiError("ERR_VALIDATION", 400,
                           "daily_spend_cap_cents must be a positive integer")
        p["daily_spend_cap_cents"] = v
    touch(p)
    return ok(ser_program(p))


@bp.post("/issuing/programs/<pid>/publish")
@require_roles("ProgramManager")
def publish_program(pid):
    p = _get_program(pid)
    if p["posture"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409, "publish requires posture DRAFT")
    has_active_bin = any(
        br["program_id"] == pid and br["status"] == "ACTIVE"
        for br in STORE["bin_ranges"].values())
    if not has_active_bin:
        raise ApiError("ERR_PROGRAM_NO_ACTIVE_BIN", 409,
                       "publish requires at least one ACTIVE BinRange")
    if p["daily_spend_cap_cents"] <= 0:
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409,
                       "daily_spend_cap_cents must be > 0")
    for ack in STORE["acks"].values():
        if ack["program_id"] != pid or ack["status"] != "SUBMITTED":
            continue
        m = STORE["mandates"].get(ack["mandate_id"])
        if m and m["status"] == "EFFECTIVE":
            raise ApiError("ERR_MANDATE_ACK_IN_FLIGHT", 409,
                           "a MandateAck is SUBMITTED against an EFFECTIVE mandate")
    p["posture"] = "LIVE"
    touch(p)
    return ok(ser_program(p))


@bp.post("/issuing/programs/<pid>/sunset")
@require_roles("ProgramManager")
def sunset_program(pid):
    p = _get_program(pid)
    if p["posture"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "sunset requires posture LIVE")
    for b in STORE["batches"].values():
        if b["program_id"] == pid and b["status"] in ("SUBMITTED", "IN_PRODUCTION"):
            raise ApiError("ERR_PROGRAM_BATCH_IN_FLIGHT", 409,
                           "a production batch is in flight for this program")
    p["posture"] = "SUNSETTING"
    frozen = []
    for br in STORE["bin_ranges"].values():
        if br["program_id"] == pid and br["status"] == "ACTIVE":
            br["status"] = "FROZEN"
            touch(br)
            frozen.append(br["id"])
    p["_sunset_frozen"] = frozen
    touch(p)
    return ok(ser_program(p))


@bp.post("/issuing/programs/<pid>/cancel_sunset")
@require_roles("ProgramManager")
def cancel_sunset_program(pid):
    p = _get_program(pid)
    if p["posture"] != "SUNSETTING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel_sunset requires posture SUNSETTING")
    for j in STORE["jobs"].values():
        if j["source_program_id"] == pid and j["status"] in ("SCHEDULED", "EXECUTING"):
            raise ApiError("ERR_CONVERSION_IN_FLIGHT", 409,
                           "a conversion job is in flight for this program")
    p["posture"] = "LIVE"
    for brid in p.get("_sunset_frozen", []):
        br = STORE["bin_ranges"].get(brid)
        if br is not None and br["status"] == "FROZEN":
            br["status"] = "ACTIVE"
            touch(br)
    p["_sunset_frozen"] = []
    touch(p)
    return ok(ser_program(p))


@bp.post("/issuing/programs/<pid>/terminate")
@require_roles("ProgramManager")
def terminate_program(pid):
    p = _get_program(pid)
    if p["posture"] != "SUNSETTING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "terminate requires posture SUNSETTING")
    data = body()
    reason = data.get("termination_reason")
    if reason not in TERMINATION_REASONS:
        raise ApiError("ERR_VALIDATION", 400,
                       "termination_reason must be one of %s" % list(TERMINATION_REASONS))
    if reason == "PORTFOLIO_CONVERSION":
        done = any(j["source_program_id"] == pid and j["status"] == "COMPLETED"
                   for j in STORE["jobs"].values())
        if not done:
            raise ApiError("ERR_CONVERSION_NOT_COMPLETED", 409,
                           "no COMPLETED conversion job for this program")
    else:
        for a in STORE["accounts"].values():
            if a["program_id"] == pid and \
                    a["lifecycle_status"] not in ("CLOSED", "CONVERTED_OUT"):
                raise ApiError("ERR_PROGRAM_HAS_OPEN_ACCOUNTS", 409,
                               "all accounts must be CLOSED or CONVERTED_OUT")
    p["posture"] = "TERMINATED"
    p["terminated_at"] = fmt_dt(now())
    p["termination_reason"] = reason
    for br in STORE["bin_ranges"].values():
        if br["program_id"] == pid and br["status"] != "RETIRED":
            br["status"] = "RETIRED"
            touch(br)
    for card in STORE["cards"].values():
        acct = STORE["accounts"].get(card["account_id"])
        if acct and acct["program_id"] == pid and \
                card["lifecycle_status"] not in ("CANCELLED", "EXPIRED", "COMPROMISED"):
            card["lifecycle_status"] = "CANCELLED"
            touch(card)
    for r in STORE["rules"].values():
        if r["subject_kind"] == "PROGRAM" and r["subject_ref"] == pid and \
                r["status"] in ("DRAFT", "ACTIVE"):
            r["status"] = "RETIRED"
            touch(r)
    touch(p)
    return ok(ser_program(p))


# ---------------------------------------------------------------------------
# Program economics
# ---------------------------------------------------------------------------

@bp.get("/issuing/programs/<pid>/economics")
@require_roles("FinanceController", "PlatformAdmin")
def program_economics(pid):
    p = _get_program(pid)
    from flask import request
    month = request.args.get("month")
    if not month or not MONTH_RE.match(month):
        raise ApiError("ERR_VALIDATION", 400, "month must be YYYY-MM")
    variant = request.args.get("variant")
    if variant is not None and variant not in ("PROVISIONAL", "FINAL"):
        raise ApiError("ERR_VALIDATION", 400, "variant must be PROVISIONAL or FINAL")
    year, mon = int(month[:4]), int(month[5:7])
    if variant is None:
        clock = now()
        variant = "PROVISIONAL" if (clock.year, clock.month) == (year, mon) else "FINAL"
    month_start = datetime(year, mon, 1, tzinfo=timezone.utc)
    ny, nm = (year + 1, 1) if mon == 12 else (year, mon + 1)
    month_end = datetime(ny, nm, 1, tzinfo=timezone.utc)
    clock = now()

    interchange = 0
    for s in STORE["settlements"].values():
        if s["_program_id"] != pid:
            continue
        sat = s["_settled_at"]
        if not (month_start <= sat < month_end):
            continue
        if variant == "PROVISIONAL" and sat > clock:
            continue
        interchange += s["interchange_cents"]

    production = 0
    for b in STORE["batches"].values():
        if b["program_id"] != pid or b["scheduled_for_utc_date"][:7] != month:
            continue
        if b["status"] in ("SHIPPED", "DELIVERED"):
            production += b["fulfilled_card_count"] * b["unit_cost_cents"]
        elif variant == "PROVISIONAL" and b["status"] in ("SUBMITTED", "IN_PRODUCTION"):
            production += b["requested_card_count"] * b["unit_cost_cents"]

    reissue = 0
    for c in STORE["campaigns"].values():
        if c["program_id"] != pid or c["status"] != "COMPLETED":
            continue
        comp = c.get("_completed_at")
        if comp is not None and month_start <= comp < month_end:
            reissue += c.get("_booked_fee_cents", 0)

    return ok({
        "month": month,
        "variant": variant,
        "interchange_revenue_cents": interchange,
        "production_cost_cents": production,
        "reissue_fee_cents": reissue,
        "net_economics_cents": interchange - production - reissue,
    })


# ---------------------------------------------------------------------------
# BinRange
# ---------------------------------------------------------------------------

def _valid_range_size(n):
    if isinstance(n, bool) or not isinstance(n, int):
        return False
    if n < 1000 or n > 10_000_000:
        return False
    v = 1000
    while v <= 10_000_000:
        if v == n:
            return True
        v *= 10
    return False


@bp.post("/issuing/programs/<pid>/bin-ranges")
@require_roles("ProgramManager")
def create_bin_range(pid):
    p = _get_program(pid)
    data = body()
    bin_prefix = req_field(data, "bin_prefix")
    if not isinstance(bin_prefix, str) or not BIN_PREFIX_RE.match(bin_prefix):
        raise ApiError("ERR_VALIDATION", 400,
                       "bin_prefix must be a 6- or 8-digit numeric string")
    range_size = data.get("range_size")
    if not _valid_range_size(range_size):
        raise ApiError("ERR_VALIDATION", 400,
                       "range_size must be a power of 10 between 10^3 and 10^7")
    try:
        effective_from = parse_dt(req_field(data, "effective_from"))
        effective_until = parse_dt(req_field(data, "effective_until"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "effective_from/effective_until must be ISO8601 timestamps")
    if not effective_from < effective_until:
        raise ApiError("ERR_BIN_NOT_IN_WINDOW", 409,
                       "effective_from must be strictly before effective_until")
    br = new_entity()
    br.update({
        "program_id": pid,
        "bin_prefix": bin_prefix,
        "range_size": range_size,
        "pans_allocated": 0,
        "effective_from": fmt_dt(effective_from),
        "effective_until": fmt_dt(effective_until),
        "status": "PENDING_ACTIVATION",
        "_effective_from": effective_from,
        "_effective_until": effective_until,
    })
    STORE["bin_ranges"][br["id"]] = br
    apply_lazy()
    return ok(ser_bin_range(br), 201)


@bp.get("/issuing/programs/<pid>/bin-ranges")
@require_roles("ProgramManager", "ComplianceOfficer", "OperationsAnalyst", "PlatformAdmin")
def list_bin_ranges(pid):
    _get_program(pid)
    from flask import request
    items = [br for br in STORE["bin_ranges"].values() if br["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [br for br in items if br["status"] == status]
    return ok_list([ser_bin_range(br) for br in sort_created(items)])


def _get_bin_range(rid):
    return get_or_404("bin_ranges", rid, "bin range")


@bp.get("/issuing/bin-ranges/<rid>")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def get_bin_range(rid):
    return ok(ser_bin_range(_get_bin_range(rid)))


@bp.post("/issuing/bin-ranges/<rid>/freeze")
@require_roles("ProgramManager")
def freeze_bin_range(rid):
    br = _get_bin_range(rid)
    if br["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "freeze requires status ACTIVE")
    br["status"] = "FROZEN"
    touch(br)
    return ok(ser_bin_range(br))


@bp.post("/issuing/bin-ranges/<rid>/unfreeze")
@require_roles("ProgramManager")
def unfreeze_bin_range(rid):
    br = _get_bin_range(rid)
    if br["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE", 409, "unfreeze requires status FROZEN")
    prog = STORE["programs"].get(br["program_id"])
    if prog is None or prog["posture"] not in ("DRAFT", "LIVE"):
        raise ApiError("ERR_PROGRAM_NOT_EDITABLE", 409,
                       "unfreeze requires program posture DRAFT or LIVE")
    br["status"] = "ACTIVE"
    touch(br)
    return ok(ser_bin_range(br))


@bp.post("/issuing/bin-ranges/<rid>/retire")
@require_roles("ProgramManager")
def retire_bin_range(rid):
    br = _get_bin_range(rid)
    if br["status"] in ("ACTIVE", "FROZEN"):
        if br["pans_allocated"] > 0:
            raise ApiError("ERR_BIN_HAS_ALLOCATED_PANS", 409,
                           "retire requires pans_allocated = 0")
    elif br["status"] == "DEPLETED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "retire requires status ACTIVE, FROZEN, or DEPLETED")
    br["status"] = "RETIRED"
    touch(br)
    return ok(ser_bin_range(br))
