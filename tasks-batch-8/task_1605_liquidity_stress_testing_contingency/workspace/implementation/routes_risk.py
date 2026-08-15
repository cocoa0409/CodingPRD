"""Routes: EWI metrics/readings, dashboard, posture evaluations/snapshots,
board limits, breaches, intraday snapshots."""
from flask import Blueprint, g, request

from db import mint_id, store
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LIMIT_STILL_BREACHED,
    ERR_NOT_FOUND,
    ERR_READING_TOO_FREQUENT,
    ERR_SNAPSHOT_OUT_OF_ORDER,
    ERR_SOD_VIOLATION,
    ERR_THRESHOLD_CONFIG_INVALID,
)
from helpers import (
    MISSING,
    fmt_dt,
    get_json_body,
    new_entity,
    new_event,
    opt_int,
    paginate,
    pub,
    req_date,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    sorted_by_created,
    touch,
)
from middleware import BIZ4, require_roles
from responses import ok, ok_list
from services import (
    append_posture_evaluation,
    band_counts,
    current_posture_level,
    current_subject_value,
    detect_breaches,
    within_limit,
)

bp = Blueprint("risk", __name__)

UNITS = ("PCT_BPS", "DAYS", "CENTS")
DIRECTIONS = ("ABOVE_BREACHES", "BELOW_BREACHES")
SUBJECTS = (
    "EWI_METRIC",
    "WHOLESALE_RELIANCE_PCT",
    "TOP_COUNTERPARTY_PCT",
    "SURVIVAL_DAYS",
    "INTRADAY_NET_POSITION",
)
SEVERITIES = ("BOARD", "REGULATORY")


def _get_or_404(table, entity_id, label):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found: {entity_id}")
    return ent


def _reading_band(metric, value):
    if metric["direction"] == "ABOVE_BREACHES":
        if value > metric["red_threshold"]:
            return "RED"
        if value > metric["amber_threshold"]:
            return "AMBER"
        return "GREEN"
    else:
        if value < metric["red_threshold"]:
            return "RED"
        if value < metric["amber_threshold"]:
            return "AMBER"
        return "GREEN"


# ---------------------------------------------------------------------------
# EWI metrics
# ---------------------------------------------------------------------------
@bp.post("/liquidity/ewi-metrics")
@require_roles("RiskOfficer")
def create_metric():
    body = get_json_body(required=True)
    code = req_str(body, "code")
    name = req_str(body, "name")
    unit = req_enum(body, "unit", UNITS)
    direction = req_enum(body, "direction", DIRECTIONS)
    amber = req_int(body, "amber_threshold")
    red = req_int(body, "red_threshold")
    interval = opt_int(body, "min_reading_interval_hours", default=0, min_v=0)
    if direction == "ABOVE_BREACHES":
        coherent = red > amber
    else:
        coherent = red < amber
    if not coherent:
        raise ApiError(
            ERR_THRESHOLD_CONFIG_INVALID, 422,
            "EWI metric thresholds inconsistent with direction "
            "(ABOVE needs red > amber; BELOW needs red < amber).")
    if any(m["code"] == code for m in store.metrics.values()):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"EWI metric code already exists: {code}")
    ent = new_entity({
        "id": mint_id(),
        "code": code,
        "name": name,
        "unit": unit,
        "direction": direction,
        "amber_threshold": amber,
        "red_threshold": red,
        "min_reading_interval_hours": interval,
        "current_band": "GREEN",
        "last_reading_at": None,
    })
    ent["_last_reading_dt"] = None
    store.metrics[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/ewi-metrics")
@require_roles(*BIZ4)
def list_metrics():
    page, pagination = paginate(sorted_by_created(list(store.metrics.values())))
    return ok_list([pub(m) for m in page], pagination)


@bp.get("/liquidity/ewi-metrics/<metric_id>")
@require_roles(*BIZ4)
def get_metric(metric_id):
    return ok(pub(_get_or_404(store.metrics, metric_id, "EwiMetric")))


@bp.post("/liquidity/ewi-metrics/<metric_id>/readings")
@require_roles("TreasuryAnalyst")
def post_reading(metric_id):
    metric = _get_or_404(store.metrics, metric_id, "EwiMetric")
    body = get_json_body(required=True)
    observed_dt = req_datetime(body, "observed_at")
    value = req_int(body, "value")
    # Cadence (temporal rule): observed_at >= last_reading_at + interval.
    if metric["_last_reading_dt"] is not None:
        from datetime import timedelta
        earliest = metric["_last_reading_dt"] + timedelta(
            hours=metric["min_reading_interval_hours"])
        if observed_dt < earliest:
            raise ApiError(
                ERR_READING_TOO_FREQUENT, 409,
                "observed_at earlier than last_reading_at + min_reading_interval_hours.")
    band = _reading_band(metric, value)
    reading = new_event({
        "id": mint_id(),
        "metric_id": metric["id"],
        # Caller-supplied observation instant is echoed verbatim.
        "observed_at": body["observed_at"],
        "value": value,
        "band": band,
    })
    reading["_observed_dt"] = observed_dt
    store.readings[reading["id"]] = reading

    # Recompute metric current band from the latest reading by observed_at
    # (tie-break: created later wins).
    prev_band = metric["current_band"]
    all_readings = [r for r in store.readings.values() if r["metric_id"] == metric["id"]]
    latest = max(all_readings, key=lambda r: (r["_observed_dt"], r["_seq"]))
    metric["current_band"] = latest["band"]
    metric["last_reading_at"] = latest["observed_at"]
    metric["_last_reading_dt"] = latest["_observed_dt"]
    touch(metric)

    # EWI_METRIC breach detection against this reading's value.
    detect_breaches(
        {"EWI_METRIC"},
        {"EWI_METRIC": value},
        "METRIC_READING",
        reading["id"],
        ewi_metric_id=metric["id"],
    )

    # RED transition triggers an automatic posture evaluation.
    if prev_band != "RED" and metric["current_band"] == "RED":
        append_posture_evaluation("READING_AUTO", "system")

    return ok(pub(reading), status=201)


@bp.get("/liquidity/ewi-metrics/<metric_id>/readings")
@require_roles(*BIZ4)
def list_readings(metric_id):
    _get_or_404(store.metrics, metric_id, "EwiMetric")
    items = [r for r in store.readings.values() if r["metric_id"] == metric_id]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(r) for r in page], pagination)


# ---------------------------------------------------------------------------
# Dashboard and posture
# ---------------------------------------------------------------------------
@bp.get("/liquidity/ewi-dashboard")
@require_roles(*BIZ4)
def ewi_dashboard():
    red, amber, _ = band_counts()
    return ok({
        "posture_level": current_posture_level(),
        "red_count": red,
        "amber_count": amber,
        "metric_count": len(store.metrics),
    })


@bp.post("/liquidity/posture-evaluations")
@require_roles("RiskOfficer", "LiquidityCommittee")
def manual_posture_evaluation():
    snap = append_posture_evaluation("MANUAL_EVALUATION", g.user_id, role=g.role)
    return ok(pub(snap), status=201)


@bp.get("/liquidity/posture-snapshots")
@require_roles(*BIZ4)
def list_posture_snapshots():
    items = sorted(store.posture_snapshots.values(), key=lambda s: s["snapshot_seq"])
    page, pagination = paginate(items)
    return ok_list([pub(s) for s in page], pagination)


# ---------------------------------------------------------------------------
# Board limits and breaches
# ---------------------------------------------------------------------------
@bp.post("/liquidity/board-limits")
@require_roles("RiskOfficer")
def create_limit():
    body = get_json_body(required=True)
    # Existence (priority 3) precedes cross-field shape rules (priority 4).
    raw_metric = body.get("ewi_metric_id")
    if isinstance(raw_metric, str) and raw_metric not in store.metrics:
        raise ApiError(ERR_NOT_FOUND, 404, f"EwiMetric not found: {raw_metric}")
    subject = req_enum(body, "subject", SUBJECTS)
    direction = req_enum(body, "direction", DIRECTIONS)
    limit_value = req_int(body, "limit_value")
    severity = req_enum(body, "severity", SEVERITIES)
    if subject == "EWI_METRIC":
        if raw_metric is None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "ewi_metric_id is required when subject == EWI_METRIC.")
        if not isinstance(raw_metric, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field ewi_metric_id must be a string.")
        ewi_metric_id = raw_metric
    else:
        if raw_metric is not None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "ewi_metric_id is forbidden unless subject == EWI_METRIC.")
        ewi_metric_id = None
    ent = new_entity({
        "id": mint_id(),
        "subject": subject,
        "direction": direction,
        "limit_value": limit_value,
        "severity": severity,
        "ewi_metric_id": ewi_metric_id,
    })
    store.limits[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/board-limits")
@require_roles(*BIZ4)
def list_limits():
    items = list(store.limits.values())
    subject = request.args.get("subject")
    metric_id = request.args.get("ewi_metric_id")
    if subject is not None:
        items = [l for l in items if l["subject"] == subject]
    if metric_id is not None:
        items = [l for l in items if l["ewi_metric_id"] == metric_id]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(l) for l in page], pagination)


@bp.get("/liquidity/board-limits/<limit_id>")
@require_roles(*BIZ4)
def get_limit(limit_id):
    return ok(pub(_get_or_404(store.limits, limit_id, "BoardLimit")))


@bp.get("/liquidity/board-limits/<limit_id>/breaches")
@require_roles(*BIZ4)
def list_limit_breaches(limit_id):
    _get_or_404(store.limits, limit_id, "BoardLimit")
    items = [b for b in store.breaches.values() if b["limit_id"] == limit_id]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(b) for b in page], pagination)


@bp.get("/liquidity/breaches/<breach_id>")
@require_roles(*BIZ4)
def get_breach(breach_id):
    return ok(pub(_get_or_404(store.breaches, breach_id, "LimitBreach")))


@bp.post("/liquidity/breaches/<breach_id>/acknowledge")
@require_roles("RiskOfficer")
def acknowledge_breach(breach_id):
    br = _get_or_404(store.breaches, breach_id, "LimitBreach")
    if br["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Breach is not OPEN.")
    br["status"] = "ACKNOWLEDGED"
    br["acknowledged_by_user_id"] = g.user_id
    touch(br)
    return ok(pub(br))


@bp.post("/liquidity/breaches/<breach_id>/escalate")
@require_roles("LiquidityCommittee")
def escalate_breach(breach_id):
    br = _get_or_404(store.breaches, breach_id, "LimitBreach")
    if br["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Breach is not ACKNOWLEDGED.")
    br["status"] = "ESCALATED"
    touch(br)
    return ok(pub(br))


@bp.post("/liquidity/breaches/<breach_id>/remediate")
@require_roles("RiskOfficer", "LiquidityCommittee")
def remediate_breach(breach_id):
    br = _get_or_404(store.breaches, breach_id, "LimitBreach")
    # State-specific role rule (priority 2 RBAC): ESCALATED remediation is
    # committee-only.
    if br["status"] == "ESCALATED" and g.role != "LiquidityCommittee":
        raise ApiError(
            ERR_FORBIDDEN, 403,
            "Remediation of an ESCALATED breach requires the LiquidityCommittee role.")
    body = get_json_body(required=True)
    note = req_str(body, "remediation_note")
    if br["status"] not in ("ACKNOWLEDGED", "ESCALATED"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Breach must be ACKNOWLEDGED or ESCALATED to remediate.")
    # SoD: remediator must differ from the acknowledger (when one is recorded).
    if br["acknowledged_by_user_id"] is not None and g.user_id == br["acknowledged_by_user_id"]:
        raise ApiError(
            ERR_SOD_VIOLATION, 403,
            "Remediator must differ from the breach acknowledger.")
    # Re-prove the numbers at remediate time.
    lim = store.limits.get(br["limit_id"])
    direction = lim["direction"] if lim is not None else "ABOVE_BREACHES"
    current = current_subject_value(br)
    if not within_limit(direction, current, br["limit_value"]):
        raise ApiError(
            ERR_LIMIT_STILL_BREACHED, 409,
            "Current subject value still violates the limit.")
    br["status"] = "REMEDIATED"
    br["remediated_by_user_id"] = g.user_id
    br["remediation_note"] = note
    touch(br)
    return ok(pub(br))


# ---------------------------------------------------------------------------
# Intraday snapshots
# ---------------------------------------------------------------------------
@bp.post("/liquidity/intraday-snapshots")
@require_roles("TreasuryOps")
def post_intraday_snapshot():
    body = get_json_body(required=True)
    business_date = req_date(body, "business_date")
    snapshot_dt = req_datetime(body, "snapshot_at")
    opening = req_int(body, "opening_balance_cents")
    received = req_int(body, "payments_received_cents", min_v=0)
    sent = req_int(body, "payments_sent_cents", min_v=0)
    # Chronological guard within the business_date bucket.
    for s in store.intraday_snapshots.values():
        if s["business_date"] == business_date and snapshot_dt <= s["_snapshot_dt"]:
            raise ApiError(
                ERR_SNAPSHOT_OUT_OF_ORDER, 409,
                "snapshot_at must be strictly greater than existing snapshots "
                "for the same business_date.")
    net = opening + received - sent
    ent = new_event({
        "id": mint_id(),
        "business_date": business_date,
        # Caller-supplied observation instant is echoed verbatim.
        "snapshot_at": body["snapshot_at"],
        "opening_balance_cents": opening,
        "payments_received_cents": received,
        "payments_sent_cents": sent,
        "net_position_cents": net,
    })
    ent["_snapshot_dt"] = snapshot_dt
    store.intraday_snapshots[ent["id"]] = ent
    detect_breaches(
        {"INTRADAY_NET_POSITION"},
        {"INTRADAY_NET_POSITION": net},
        "INTRADAY_SNAPSHOT",
        ent["id"],
    )
    return ok(pub(ent), status=201)


@bp.get("/liquidity/intraday-snapshots")
@require_roles(*BIZ4)
def list_intraday_snapshots():
    items = list(store.intraday_snapshots.values())
    business_date = request.args.get("business_date")
    if business_date is not None:
        items = [s for s in items if s["business_date"] == business_date]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(s) for s in page], pagination)
