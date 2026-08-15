"""Routes: logical clock, subledger seed, close periods, entities, FX rates."""
from core import (
    CLOCK, STORE, ApiError, ALL_ROLES, base_record, body, bp, bump, dec,
    fmt_ts, logical_now, new_id, next_seq, ok, paged_response, parse_ts,
    req_enum, req_int, req_num, req_str, req_ts, require_roles, wall_now,
)
from domain import (
    CURRENCIES, add_event, compute_close_metrics, eps_of_period, get_entity,
    get_period, json_detail, reevaluate_clock, recompute_period_counts,
    run_consolidation, ser_entity, ser_ep, ser_event, ser_fx, ser_period,
    touch_ep,
)

READERS = ALL_ROLES


def _check_period_version(period, b):
    expected = b.get("expected_close_period_version")
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        expected = None
    if expected is None or expected != period["version"]:
        raise ApiError(
            "ERR_STALE_PERIOD_VERSION", 412,
            "expected_close_period_version does not match the period's "
            "current version")


# ---------------------------------------------------------------------------
# Test-driving endpoints
# ---------------------------------------------------------------------------
@bp.post("/close/_clock/set_current_utc")
def set_clock():
    require_roles("Controller")
    b = body()
    ts = req_ts(b, "to_iso8601")
    CLOCK["now"] = ts
    reevaluate_clock(ts)
    return ok({"now_iso8601": fmt_ts(CLOCK["now"])})


@bp.post("/close/_subledger/seed")
def seed_subledger():
    require_roles("Controller")
    b = body()
    entity = get_entity(req_str(b, "entity_id"))
    subledger = req_enum(b, "subledger",
                         ("AR", "AP", "INVENTORY", "FIXED_ASSETS", "PAYROLL"))
    ts = req_ts(b, "ts")
    amount = req_int(b, "amount_minor")
    account_code = req_str(b, "account_code")
    txn = {
        "id": new_id(),
        "_seq": next_seq(),
        "entity_id": entity["id"],
        "subledger": subledger,
        "ts": ts,
        "amount_minor": amount,
        "account_code": account_code,
        "created_at": wall_now(),
    }
    STORE["subledger_txns"][txn["id"]] = txn
    return ok({"subledger_txn_id": txn["id"]}, 201)


# ---------------------------------------------------------------------------
# ClosePeriod
# ---------------------------------------------------------------------------
@bp.post("/close/periods")
def create_period():
    require_roles("Controller")
    b = body()
    fiscal_year = req_int(b, "fiscal_year")
    fiscal_period = req_int(b, "fiscal_period")
    if not (1 <= fiscal_period <= 13):
        raise ApiError("ERR_VALIDATION", 400,
                       "fiscal_period must be between 1 and 13")
    period_start = req_ts(b, "period_start")
    period_end = req_ts(b, "period_end")
    if not period_end > period_start:
        raise ApiError("ERR_VALIDATION", 400,
                       "period_end must be strictly after period_start")
    reporting_currency = req_enum(b, "reporting_currency", CURRENCIES)
    materiality = req_int(b, "materiality_threshold_minor")
    rec = base_record()
    rec.update({
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "period_start": period_start,
        "period_end": period_end,
        "close_posture": "OPEN",
        "reporting_currency": reporting_currency,
        "materiality_threshold_minor": materiality,
        "status": "SCHEDULED",
        "locked_entity_count": 0,
        "total_entity_count": 0,
        "reopened_reason": None,
    })
    STORE["periods"][rec["id"]] = rec
    return ok(ser_period(rec), 201)


@bp.get("/close/periods/<pid>")
def get_one_period(pid):
    require_roles(*READERS)
    return ok(ser_period(get_period(pid)))


@bp.get("/close/periods")
def list_periods():
    require_roles(*READERS)
    return paged_response(list(STORE["periods"].values()), ser_period)


@bp.post("/close/periods/<pid>/open")
def open_period(pid):
    require_roles("Controller")
    period = get_period(pid)
    if period["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED period can be opened")
    if logical_now() < period["period_start"]:
        raise ApiError("ERR_PERIOD_NOT_YET_OPEN", 409,
                       "Logical clock has not reached period_start")
    for other in STORE["periods"].values():
        if other["id"] != period["id"] and other["status"] in (
                "IN_PROGRESS", "UNDER_REVIEW"):
            raise ApiError("ERR_PERIOD_ALREADY_OPEN", 409,
                           "Another close period is already open")
    period["status"] = "IN_PROGRESS"
    period["close_posture"] = "OPEN"
    # Fan out one EntityPeriod per registered entity (elimination
    # counterparty or not).
    entities = sorted(STORE["entities"].values(),
                      key=lambda e: (e["created_at"], e["_seq"]))
    for ent in entities:
        ep = base_record()
        ep.update({
            "close_period_id": period["id"],
            "entity_id": ent["id"],
            "status": "PREPARING",
            "trial_balance_minor": 0,
            "translated_balance_minor": None,
            "cta_minor": None,
            "nci_share_minor": 0,
            "unreconciled_count": 0,
            "aged_over_30_count": 0,
            "open_task_count": 0,
            "remeasurement_minor": None,
            "_translation_run": False,
            "_translation_stale": False,
        })
        STORE["entity_periods"][ep["id"]] = ep
    recompute_period_counts(period)
    bump(period)
    add_event(period["id"], None, "PERIOD_OPENED", "system",
              json_detail({"status_before": "SCHEDULED",
                           "status_after": "IN_PROGRESS"}))
    return ok(ser_period(period))


@bp.post("/close/periods/<pid>/soft-lock")
def soft_lock_period(pid):
    uid = require_roles("Controller")
    period = get_period(pid)
    _check_period_version(period, body())
    if period["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_PROGRESS period can be soft-locked")
    if period["close_posture"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Soft-lock requires close_posture OPEN or REOPENED")
    eps = eps_of_period(period["id"])
    if any(e["status"] not in ("READY_FOR_CONSOL", "SOFT_LOCKED",
                               "HARD_LOCKED") for e in eps):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Every entity-period must be READY_FOR_CONSOL or beyond to "
            "soft-lock")
    posture_before = period["close_posture"]
    for e in eps:
        if e["status"] == "READY_FOR_CONSOL":
            e["status"] = "SOFT_LOCKED"
            bump(e)
    period["close_posture"] = "SOFT_CLOSED"
    recompute_period_counts(period)
    bump(period)
    add_event(period["id"], None, "SOFT_LOCK", uid,
              json_detail({"close_posture_before": posture_before,
                           "close_posture_after": "SOFT_CLOSED"}))
    return ok(ser_period(period))


@bp.post("/close/periods/<pid>/hard-lock")
def hard_lock_period(pid):
    uid = require_roles("Controller")
    period = get_period(pid)
    _check_period_version(period, body())
    if period["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_PROGRESS period can be hard-locked")
    eps = eps_of_period(period["id"])
    if any(e["status"] != "SOFT_LOCKED" for e in eps):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Every entity-period must be SOFT_LOCKED to hard-lock")
    for pair in STORE["elim_pairs"].values():
        if pair["close_period_id"] != period["id"]:
            continue
        ok_state = pair["status"] == "ELIMINATED" or (
            pair["status"] == "DISPUTED"
            and abs(pair["residual_minor"]) <= 500)
        if not ok_state:
            raise ApiError(
                "ERR_ELIM_RESIDUAL_EXCEEDED", 409,
                "All elimination pairs must be ELIMINATED, or DISPUTED with "
                "residual within tolerance, before hard-lock")
    for fx in STORE["fluxes"].values():
        ep = STORE["entity_periods"].get(fx["entity_period_id"])
        if ep is None or ep["close_period_id"] != period["id"]:
            continue
        if fx["requires_explanation"] and fx["status"] != "ACCEPTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Every flux explanation requiring one must be ACCEPTED "
                "before hard-lock")
    for e in eps:
        e["status"] = "HARD_LOCKED"
        bump(e)
    period["status"] = "UNDER_REVIEW"
    period["close_posture"] = "HARD_CLOSED"
    recompute_period_counts(period)
    period["locked_entity_count"] = period["total_entity_count"]
    bump(period)
    add_event(period["id"], None, "HARD_LOCK", uid,
              json_detail({"close_posture_after": "HARD_CLOSED",
                           "status_after": "UNDER_REVIEW"}))
    return ok(ser_period(period))


@bp.post("/close/periods/<pid>/reopen")
def reopen_period(pid):
    uid = require_roles("Controller")
    period = get_period(pid)
    b = body()
    _check_period_version(period, b)
    if period["close_posture"] == "HARD_CLOSED" or period["status"] in (
            "UNDER_REVIEW", "FINALIZED"):
        raise ApiError("ERR_PERIOD_HARD_LOCKED", 409,
                       "A HARD_CLOSED/UNDER_REVIEW/FINALIZED period cannot "
                       "be reopened")
    if period["status"] != "IN_PROGRESS" \
            or period["close_posture"] != "SOFT_CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SOFT_CLOSED in-progress period can be "
                       "reopened")
    reason = b.get("reopened_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError("ERR_REOPEN_REASON_REQUIRED", 409,
                       "reopened_reason must be non-empty")
    for e in eps_of_period(period["id"]):
        if e["status"] == "SOFT_LOCKED":
            e["status"] = "REOPENED"
            e["_translation_stale"] = True
            bump(e)
    period["close_posture"] = "REOPENED"
    period["reopened_reason"] = reason
    recompute_period_counts(period)
    bump(period)
    add_event(period["id"], None, "REOPENED", uid, reason)
    return ok(ser_period(period))


@bp.post("/close/periods/<pid>/finalize")
def finalize_period(pid):
    uid = require_roles("Controller")
    period = get_period(pid)
    _check_period_version(period, body())
    if period["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an UNDER_REVIEW period can be finalized")
    for ev in STORE["events"].values():
        if ev["close_period_id"] == period["id"] \
                and ev["event_kind"] == "REVIEW_FINALIZED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Period already has a REVIEW_FINALIZED event")
    if any(e["status"] == "REOPENED" for e in eps_of_period(period["id"])):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot finalize while an entity-period is REOPENED")
    metrics = compute_close_metrics(period, logical_now())
    period["status"] = "FINALIZED"
    bump(period)
    add_event(period["id"], None, "REVIEW_FINALIZED", uid,
              json_detail(metrics))
    return ok(ser_period(period))


@bp.post("/close/periods/<pid>/consolidate")
def consolidate_period(pid):
    require_roles("Controller")
    period = get_period(pid)
    result = run_consolidation(period)
    return ok(result)


@bp.get("/close/periods/<pid>/events")
def list_period_events(pid):
    require_roles("Controller", "Approver", "Auditor")
    period = get_period(pid)
    events = [e for e in STORE["events"].values()
              if e["close_period_id"] == period["id"]]
    return paged_response(events, ser_event)


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------
@bp.post("/close/entities")
def create_entity():
    require_roles("Controller")
    b = body()
    entity_code = req_str(b, "entity_code")
    name = req_str(b, "name")
    functional_currency = req_enum(b, "functional_currency", CURRENCIES)
    translation_method = req_enum(b, "translation_method",
                                  ("CURRENT_RATE", "TEMPORAL"))
    ownership = req_num(b, "ownership_pct")
    if not (dec(ownership) > 0 and dec(ownership) <= 100):
        raise ApiError("ERR_VALIDATION", 400,
                       "ownership_pct must be > 0 and <= 100")
    parent_id = b.get("parent_entity_id")
    parent = None
    if parent_id is not None:
        parent = get_entity(parent_id)
    for existing in STORE["entities"].values():
        if existing["entity_code"] == entity_code:
            raise ApiError("ERR_VALIDATION", 409,
                           "entity_code %s is already registered"
                           % entity_code)
    # Walk the parent chain: compute tier and guard against cycles.
    tier = 0
    seen = set()
    node = parent
    while node is not None:
        if node["id"] in seen:
            raise ApiError("ERR_ENTITY_HIERARCHY_CYCLE", 409,
                           "parent_entity_id chain contains a cycle")
        seen.add(node["id"])
        tier += 1
        node = (STORE["entities"].get(node["parent_entity_id"])
                if node["parent_entity_id"] else None)
    is_elim = b.get("is_elimination_counterparty", True)
    if not isinstance(is_elim, bool):
        raise ApiError("ERR_VALIDATION", 400,
                       "is_elimination_counterparty must be a boolean")
    rec = base_record()
    rec.update({
        "entity_code": entity_code,
        "name": name,
        "functional_currency": functional_currency,
        "parent_entity_id": parent_id,
        "ownership_pct": ownership,
        "translation_method": translation_method,
        "consolidation_tier": tier,
        "is_elimination_counterparty": is_elim,
    })
    STORE["entities"][rec["id"]] = rec
    return ok(ser_entity(rec), 201)


@bp.get("/close/entities/<eid>")
def get_one_entity(eid):
    require_roles(*READERS)
    return ok(ser_entity(get_entity(eid)))


@bp.get("/close/entities")
def list_entities():
    require_roles(*READERS)
    from flask import request
    records = list(STORE["entities"].values())
    parent_filter = request.args.get("parent_entity_id")
    if parent_filter is not None:
        records = [e for e in records
                   if e["parent_entity_id"] == parent_filter]
    return paged_response(records, ser_entity)


@bp.get("/close/entities/<eid>/journal-entry-lines")
def list_entity_counterparty_lines(eid):
    require_roles(*READERS)
    entity = get_entity(eid)
    lines = [l for l in STORE["je_lines"].values()
             if l.get("counterparty_entity_id") == entity["id"]]
    return paged_response(lines, ser_line)


# ---------------------------------------------------------------------------
# FxRate
# ---------------------------------------------------------------------------
@bp.post("/close/periods/<pid>/fx-rates")
def create_fx_rate(pid):
    require_roles("Controller")
    period = get_period(pid)
    b = body()
    from_currency = req_enum(b, "from_currency", CURRENCIES)
    to_currency = req_enum(b, "to_currency", CURRENCIES)
    rate_kind = req_enum(b, "rate_kind", ("PERIOD_END", "AVERAGE",
                                          "HISTORICAL"))
    rate = req_num(b, "rate")
    if not (dec(rate) > 0):
        raise ApiError("ERR_VALIDATION", 400, "rate must be > 0")
    effective_at = req_ts(b, "effective_at")
    rec = base_record()
    rec.update({
        "close_period_id": period["id"],
        "from_currency": from_currency,
        "to_currency": to_currency,
        "rate_kind": rate_kind,
        "rate": rate,
        "effective_at": effective_at,
    })
    STORE["fx_rates"][rec["id"]] = rec
    return ok(ser_fx(rec), 201)


@bp.get("/close/periods/<pid>/fx-rates")
def list_fx_rates(pid):
    require_roles(*READERS)
    from flask import request
    period = get_period(pid)
    records = [r for r in STORE["fx_rates"].values()
               if r["close_period_id"] == period["id"]]
    for param, field in (("from_currency", "from_currency"),
                         ("to_currency", "to_currency"),
                         ("rate_kind", "rate_kind")):
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return paged_response(records, ser_fx)
