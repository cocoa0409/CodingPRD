"""Monitoring profiles, calibration and activity observations (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import (ALL, OPS, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import (body, dec, fbool, fdate, fenum, fint, fnum, farr, fstr,
                      is_int, is_num, q2, q4, validate)

bp = Blueprint("monitoring", __name__)

CAL_STATES = ("PROVISIONAL", "CALIBRATED", "RECALIBRATION_REQUIRED", "SUPERSEDED")
RECAL_REASONS = ("NESTED_DISCOVERY", "ALERT_ESCALATION", "REFRESH_COMPLETION",
                 "OFFICER_ACTION")

CREATE_SPEC = [
    fdate("effective_from", True),
    fdate("effective_to", True),
    farr("expected_corridors", True, 1, 8),
    fint("expected_respondent_version", True, 0),
    fnum("tolerance_pct", False, "0.00", "0.50"),
    fbool("supersede", False),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/monitoring-profiles")
def create_profile(respondent_id):
    start(("ComplianceAnalyst",))
    resp = need_respondent(respondent_id)
    data = body()
    parsed = validate(data, CREATE_SPEC)
    corridors = _corridors(data["expected_corridors"])
    if int(data["expected_respondent_version"]) != int(resp["version"]):
        fail("ERR_STALE_RESPONDENT_VERSION",
             "expected_respondent_version does not match the respondent version.")
    cascade.guard_not_closed(resp)
    seen = []
    for entry in corridors:
        code = entry["jurisdiction_code"]
        if store.jurisdiction_by_code(code) is None:
            fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
                 "Corridor jurisdiction %s does not resolve." % code)
        if code in seen:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Corridor %s appears more than once." % code)
        seen.append(code)
    start_at = parsed["effective_from"]
    end_at = parsed["effective_to"]
    overlapped = []
    for prof in store.profiles_of(resp["id"]):
        if prof["calibration_state"] == "SUPERSEDED":
            continue
        other_start = store.dt(prof, "effective_from")
        other_end = store.dt(prof, "effective_to")
        if other_start is None or other_end is None:
            continue
        if start_at <= other_end and other_start <= end_at:
            overlapped.append(prof)
    if overlapped and not data.get("supersede"):
        fail("ERR_MONITORING_INTERVAL_OVERLAP",
             "The closed effective interval overlaps an existing profile.")
    if end_at <= start_at:
        fail("ERR_EFFECTIVE_INTERVAL_INVALID",
             "effective_to must be strictly after effective_from.")
    for prof in store.by_seq(overlapped):
        prof["calibration_state"] = "SUPERSEDED"
        store.touch(prof)
    row = store.insert("profiles", {
        "respondent_bank_id": resp["id"],
        "effective_from": data["effective_from"],
        "effective_to": data["effective_to"],
        "tolerance_pct": q2(data.get("tolerance_pct")
                           if data.get("tolerance_pct") is not None else "0.15"),
        "expected_corridors": corridors,
        "calibration_state": "PROVISIONAL",
        "corridor_thresholds": [],
        "aggregate_usd_threshold": None,
        "hold_threshold_usd": None,
        "calibrated_at": None,
        "calibrated_by_user_id": None,
        "recalibration_reason": None,
    })
    store.touch(resp)
    return ok(row, 201)


def _corridors(raw):
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST_BODY",
                 "Each expected_corridors entry must be an object.")
        code = entry.get("jurisdiction_code")
        usd = entry.get("expected_monthly_usd")
        count = entry.get("expected_monthly_count")
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST_BODY",
                 "Each corridor requires a jurisdiction_code string.")
        if not is_num(usd) or not is_int(count):
            fail("ERR_INVALID_REQUEST_BODY",
                 "Each corridor requires expected_monthly_usd and "
                 "expected_monthly_count.")
        if dec(usd) < 0 or count < 0:
            fail("ERR_FIELD_OUT_OF_RANGE", "Corridor expectations must not be negative.")
        out.append({"jurisdiction_code": code,
                    "expected_monthly_usd": q2(usd),
                    "expected_monthly_count": int(count)})
    return out


@bp.get(PREFIX + "/monitoring-profiles")
def list_profiles():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.all_rows("profiles")
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "calibration_state", arg("calibration_state"))
    rows.sort(key=lambda r: (store.dt(r, "effective_from") or clock.DEFAULT_CLOCK,
                            r["_seq"]))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/monitoring-profiles/<profile_id>")
def read_profile(profile_id):
    ctx = start(ALL)
    return ok(scoped_child("profiles", profile_id, ctx))


@bp.post(PREFIX + "/monitoring-profiles/<profile_id>/calibration")
def calibration(profile_id):
    ctx = start(("ComplianceAnalyst",))
    prof = need("profiles", profile_id)
    data = body()
    validate(data, [
        fenum("action", ("CALIBRATE", "REQUIRE_RECALIBRATION", "SUPERSEDE"), True),
        fenum("recalibration_reason", RECAL_REASONS, False),
    ])
    resp = store.get("respondents", prof["respondent_bank_id"])
    action = data["action"]
    if action == "CALIBRATE":
        forbidden = ("DECLINED", "TERMINATED")
        if prof["calibration_state"] != "RECALIBRATION_REQUIRED":
            forbidden = ("PROSPECT", "DECLINED", "TERMINATED")
        if resp["dd_state"] in forbidden:
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "This respondent state permits no calibration.")
        cascade.guard_not_closed(resp)
        if prof["calibration_state"] not in ("PROVISIONAL", "RECALIBRATION_REQUIRED"):
            fail("ERR_INVALID_MONITORING_PROFILE_STATE",
                 "Only a provisional or recalibration-required profile may be calibrated.")
        if resp["risk_rating"] == "UNRATED":
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "An unrated respondent cannot have its monitoring calibrated.")
        start_at = store.dt(prof, "effective_from")
        end_at = store.dt(prof, "effective_to")
        for other in store.profiles_of(resp["id"]):
            if other["id"] == prof["id"] or other["calibration_state"] != "CALIBRATED":
                continue
            o_start = store.dt(other, "effective_from")
            o_end = store.dt(other, "effective_to")
            if o_start is None or o_end is None:
                continue
            if start_at <= o_end and o_start <= end_at:
                fail("ERR_MONITORING_INTERVAL_OVERLAP",
                     "Another calibrated profile already covers this interval.")
        lines, aggregate, hold = calc.calibrate_thresholds(prof, resp)
        prof["corridor_thresholds"] = lines
        prof["aggregate_usd_threshold"] = aggregate
        prof["hold_threshold_usd"] = hold
        prof["recalibration_reason"] = None
        prof["calibrated_by_user_id"] = ctx.user_id
        store.set_dt(prof, "calibrated_at", clock.now())
        prof["calibration_state"] = "CALIBRATED"
    elif action == "REQUIRE_RECALIBRATION":
        if data.get("recalibration_reason") is None:
            fail("ERR_INVALID_REQUEST_BODY",
                 "recalibration_reason is required to require a recalibration.")
        cascade.guard_not_closed(resp)
        if prof["calibration_state"] != "CALIBRATED":
            fail("ERR_INVALID_MONITORING_PROFILE_STATE",
                 "Only a calibrated profile may be marked for recalibration.")
        prof["calibration_state"] = "RECALIBRATION_REQUIRED"
        prof["recalibration_reason"] = data["recalibration_reason"]
    else:
        cascade.guard_not_closed(resp)
        if prof["calibration_state"] == "SUPERSEDED":
            fail("ERR_INVALID_MONITORING_PROFILE_STATE",
                 "This profile is already superseded.")
        prof["calibration_state"] = "SUPERSEDED"
    store.touch(prof)
    return ok(prof)


# ------------------------------------------------------------ observations ----

OBS_SPEC = [
    fdate("period_month", True, "month"),
    fstr("corridor_jurisdiction_code", True, 1, None),
    fnum("aggregate_usd", True, 0),
    fint("txn_count", True, 0),
    fint("distinct_downstream_count", False, 0),
]

SEV_BY_SANCTIONS = {"COMPREHENSIVELY_SANCTIONED": "CRITICAL",
                    "RESTRICTED": "HIGH", "PERMITTED": "MEDIUM"}


@bp.post(PREFIX + "/monitoring-profiles/<profile_id>/observations")
def post_observation(profile_id):
    start(("PlatformAdmin", "ComplianceAnalyst"))
    prof = need("profiles", profile_id)
    data = body()
    parsed = validate(data, OBS_SPEC)
    resp = store.get("respondents", prof["respondent_bank_id"])
    cascade.guard_not_closed(resp)
    code = data["corridor_jurisdiction_code"]
    corridor_jp = store.jurisdiction_by_code(code)
    if corridor_jp is None:
        fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
             "corridor_jurisdiction_code %s does not resolve." % code)
    if prof["calibration_state"] == "SUPERSEDED":
        fail("ERR_MONITORING_PROFILE_SUPERSEDED",
             "A superseded monitoring profile accepts no observation.")
    for other in store.observations_of_profile(prof["id"]):
        if (other["period_month"] == data["period_month"]
                and other["corridor_jurisdiction_code"] == code):
            fail("ERR_DUPLICATE_RESOURCE",
                 "This corridor already has an observation for %s."
                 % data["period_month"])
    year, month = parsed["period_month"]
    now = clock.now()
    if (year, month) > (now.year, now.month):
        fail("ERR_OBSERVATION_PERIOD_IN_FUTURE",
             "period_month lies beyond the logical clock's calendar month.")
    downstream = int(data.get("distinct_downstream_count") or 0)
    row = store.insert("observations", {
        "monitoring_profile_id": prof["id"],
        "period_month": data["period_month"],
        "corridor_jurisdiction_code": code,
        "aggregate_usd": q2(data["aggregate_usd"]),
        "txn_count": int(data["txn_count"]),
        "distinct_downstream_count": downstream,
        "usd_threshold_applied": q2("0.00"),
        "count_threshold_applied": 0,
        "breach_ratio": q4("0.0000"),
        "alerts_created_count": 0,
    })
    created = _generate_alerts(row, prof, resp, corridor_jp)
    row["alerts_created_count"] = created
    return ok(row, 201)


def _raise_alert(resp, observation, alert_type, severity, breach_ratio=None):
    return store.insert("alerts", {
        "respondent_bank_id": resp["id"],
        "activity_observation_id": observation["id"],
        "alert_type": alert_type,
        "severity": severity,
        "state": "OPEN",
        "breach_ratio": breach_ratio,
        "investigated_by_user_id": None,
        "disposition_reason": None,
        "escalated_at": None,
    })


def _generate_alerts(row, prof, resp, corridor_jp):
    count = 0
    code = row["corridor_jurisdiction_code"]
    expected = None
    index = None
    for position, entry in enumerate(prof["expected_corridors"]):
        if entry["jurisdiction_code"] == code:
            expected = entry
            index = position
            break
    if expected is None:
        severity = SEV_BY_SANCTIONS.get(corridor_jp["sanctions_status"], "MEDIUM")
        _raise_alert(resp, row, "CORRIDOR_UNEXPECTED", severity, None)
        count += 1
    else:
        thresholds = prof["corridor_thresholds"]
        line = thresholds[index] if index is not None and index < len(thresholds) else None
        if line is not None:
            usd_threshold = dec(line["usd_threshold"])
            count_threshold = int(line["count_threshold"])
            row["usd_threshold_applied"] = q2(usd_threshold)
            row["count_threshold_applied"] = count_threshold
            ratio = q4(dec(row["aggregate_usd"]) / usd_threshold) if usd_threshold > 0 \
                else q4("0.0000")
            row["breach_ratio"] = ratio
            if prof["calibration_state"] == "CALIBRATED":
                if dec(row["aggregate_usd"]) >= usd_threshold:
                    if ratio >= Decimal("3.0000"):
                        severity = "CRITICAL"
                    elif ratio >= Decimal("2.0000"):
                        severity = "HIGH"
                    elif ratio >= Decimal("1.5000"):
                        severity = "MEDIUM"
                    else:
                        severity = "LOW"
                    _raise_alert(resp, row, "VOLUME_BREACH", severity, ratio)
                    count += 1
                if int(row["txn_count"]) >= count_threshold:
                    severity = "HIGH" if int(row["txn_count"]) >= 2 * count_threshold \
                        else "MEDIUM"
                    _raise_alert(resp, row, "COUNT_BREACH", severity, None)
                    count += 1
    known = len([r for r in store.nested_of(resp["id"])
                 if r["state"] in ("DISCLOSED", "CONFIRMED")])
    if int(row["distinct_downstream_count"]) > known:
        severity = "HIGH" if resp["nested_activity_permitted"] else "CRITICAL"
        _raise_alert(resp, row, "NESTED_ACTIVITY_UNDISCLOSED", severity, None)
        count += 1
    return count


@bp.get(PREFIX + "/activity-observations")
def list_observations():
    start(OPS)
    rows = store.all_rows("observations")
    rows = eq(rows, "monitoring_profile_id", arg("monitoring_profile_id"))
    rows = eq(rows, "period_month", arg("period_month"))
    rows = eq(rows, "corridor_jurisdiction_code", arg("corridor_jurisdiction_code"))
    rows.sort(key=lambda r: (r["period_month"], r["_seq"]))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/activity-observations/<observation_id>")
def read_observation(observation_id):
    start(OPS)
    return ok(need("observations", observation_id))
