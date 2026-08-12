"""Monitoring scenarios, threshold versions (model tuning), and evaluation."""
from datetime import datetime, timedelta, timezone
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import (ALL_ROLES, authn, authz, get_body, pagination_params)
from services.core import alert_score, high_risk_count
from util import (DIRECTION_FILTERS, TXN_TYPES, base_entity, opt_int, opt_num,
                  opt_dt, req_enum, req_int, req_num, req_num_range, req_str,
                  req_dt, serialize, sort_created, touch)

bp = Blueprint("scenarios", __name__)
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@bp.route("/monitoring-scenarios", methods=["POST"])
def create_scenario():
    body = get_body()
    scenario_code = req_str(body, "scenario_code")
    name = req_str(body, "name")
    applies = body.get("applies_to_txn_types")
    if not isinstance(applies, list):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'applies_to_txn_types' must be an array", 400)
    for item in applies:
        if not isinstance(item, str) or item not in TXN_TYPES:
            raise ApiError("ERR_INVALID_REQUEST",
                           f"Unknown txn_type '{item}' in applies_to_txn_types", 400)
    direction_filter = req_enum(body, "direction_filter", DIRECTION_FILTERS)
    bw_amount = opt_num(body, "baseline_weight_amount", default=0.5)
    bw_velocity = opt_num(body, "baseline_weight_velocity", default=0.3)
    bw_geo = opt_num(body, "baseline_weight_geo", default=0.2)
    stale_days = opt_int(body, "stale_alert_days", default=30, minimum=0)
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    for existing in db.scenarios.values():
        if existing["scenario_code"] == scenario_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           f"scenario_code '{scenario_code}' is already in use", 400)
    scenario = base_entity()
    scenario.update({
        "scenario_code": scenario_code,
        "name": name,
        "applies_to_txn_types": list(applies),
        "direction_filter": direction_filter,
        "status": "DRAFT",
        "baseline_weight_amount": bw_amount,
        "baseline_weight_velocity": bw_velocity,
        "baseline_weight_geo": bw_geo,
        "stale_alert_days": stale_days,
        "current_active_threshold_id": None,
    })
    db.scenarios[scenario["id"]] = scenario
    return response.success(serialize(scenario), status=201)


@bp.route("/monitoring-scenarios/<rid>", methods=["GET"])
def get_scenario(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    return response.success(serialize(scenario), status=200)


@bp.route("/monitoring-scenarios/<rid>/activate", methods=["POST"])
def activate_scenario(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    if scenario["status"] not in {"DRAFT", "SUSPENDED"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Scenario in status {scenario['status']} cannot be activated", 409)
    allowed = {"APPROVED"} if scenario["status"] == "DRAFT" else {"APPROVED", "ACTIVE"}
    has_threshold = any(
        t["scenario_id"] == scenario["id"] and t["status"] in allowed
        for t in db.thresholds.values())
    if not has_threshold:
        raise ApiError("ERR_NO_ACTIVE_THRESHOLD",
                       "Scenario activation requires an APPROVED threshold version", 409)
    scenario["status"] = "ACTIVE"
    touch(scenario)
    return response.success(serialize(scenario), status=200)


@bp.route("/monitoring-scenarios/<rid>/suspend", methods=["POST"])
def suspend_scenario(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    if scenario["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Scenario in status {scenario['status']} cannot be suspended", 409)
    scenario["status"] = "SUSPENDED"
    touch(scenario)
    return response.success(serialize(scenario), status=200)


@bp.route("/monitoring-scenarios/<rid>/retire", methods=["POST"])
def retire_scenario(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    if scenario["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Scenario in status {scenario['status']} cannot be retired", 409)
    open_alerts = any(
        a["scenario_id"] == scenario["id"] and a["status"] in {"NEW", "UNDER_TRIAGE"}
        for a in db.alerts.values())
    if open_alerts:
        raise ApiError("ERR_SCENARIO_HAS_OPEN_ALERTS",
                       "Scenario has alerts in NEW or UNDER_TRIAGE", 409)
    scenario["status"] = "RETIRED"
    touch(scenario)
    return response.success(serialize(scenario), status=200)


# ---------------------------------------------------------------------------
# Threshold versions
# ---------------------------------------------------------------------------

def _window_overlaps(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; None end means open-ended."""
    a_end = a_to if a_to is not None else _FAR_FUTURE
    b_end = b_to if b_to is not None else _FAR_FUTURE
    return a_from < b_end and b_from < a_end


@bp.route("/monitoring-scenarios/<rid>/threshold-versions", methods=["POST"])
def propose_threshold(rid):
    body = get_body()
    expected_version = req_int(body, "expected_scenario_version")
    threshold_amount = req_int(body, "threshold_amount_cents", minimum=1)
    lookback_days = req_int(body, "lookback_days", minimum=1)
    min_txn_count = req_int(body, "min_transaction_count", minimum=1)
    weight_amount = req_num(body, "weight_amount")
    weight_velocity = req_num(body, "weight_velocity")
    weight_geo = req_num(body, "weight_geo")
    effective_from = req_dt(body, "effective_from")
    effective_to = opt_dt(body, "effective_to")
    if effective_to is not None and effective_to <= effective_from:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must be after effective_from", 400)
    tuning_rationale = req_str(body, "tuning_rationale")
    backtest_precision = req_num_range(body, "backtest_precision", 0, 1)
    backtest_recall = req_num_range(body, "backtest_recall", 0, 1)

    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    if expected_version != scenario["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_scenario_version does not match the scenario's "
                       "current version", 412)
    for other in db.thresholds.values():
        if (other["scenario_id"] == scenario["id"]
                and other["status"] in {"PROPOSED", "APPROVED"}
                and _window_overlaps(effective_from, effective_to,
                                     other["effective_from"], other["effective_to"])):
            raise ApiError("ERR_THRESHOLD_WINDOW_OVERLAP",
                           "Effective window overlaps another PROPOSED/APPROVED "
                           "version of this scenario", 409)
    version_number = 1 + sum(1 for t in db.thresholds.values()
                             if t["scenario_id"] == scenario["id"])
    threshold = base_entity()
    threshold.update({
        "scenario_id": scenario["id"],
        "version_number": version_number,
        "threshold_amount_cents": threshold_amount,
        "lookback_days": lookback_days,
        "min_transaction_count": min_txn_count,
        "weight_amount": weight_amount,
        "weight_velocity": weight_velocity,
        "weight_geo": weight_geo,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "tuning_rationale": tuning_rationale,
        "backtest_precision": backtest_precision,
        "backtest_recall": backtest_recall,
        "status": "PROPOSED",
        "proposed_by_analyst_id": user_id,
        "approved_by_analyst_id": None,
    })
    db.thresholds[threshold["id"]] = threshold
    touch(scenario)  # each successful proposal increments the scenario version
    return response.success(serialize(threshold), status=201)


@bp.route("/monitoring-scenarios/<rid>/threshold-versions", methods=["GET"])
def list_thresholds(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    limit, offset = pagination_params()
    items = sorted([t for t in db.thresholds.values()
                    if t["scenario_id"] == scenario["id"]],
                   key=lambda t: (t["version_number"], t["_seq"]))
    return response.paginated([serialize(t) for t in items], limit, offset)


@bp.route("/threshold-versions/<rid>/approve", methods=["POST"])
def approve_threshold(rid):
    user_id, role = authn()
    authz(role, ["BSAManager"])
    threshold = _get(db.thresholds, rid, "ScenarioThreshold")
    if user_id == threshold["proposed_by_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from the proposing analyst", 403)
    if threshold["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Threshold in status {threshold['status']} cannot be approved", 409)
    threshold["status"] = "APPROVED"
    threshold["approved_by_analyst_id"] = user_id
    touch(threshold)
    return response.success(serialize(threshold), status=200)


@bp.route("/threshold-versions/<rid>/return", methods=["POST"])
def return_threshold(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    threshold = _get(db.thresholds, rid, "ScenarioThreshold")
    if threshold["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Threshold in status {threshold['status']} cannot be returned", 409)
    threshold["status"] = "PROPOSED"
    threshold["approved_by_analyst_id"] = None
    touch(threshold)
    return response.success(serialize(threshold), status=200)


@bp.route("/threshold-versions/<rid>/activate", methods=["POST"])
def activate_threshold(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    threshold = _get(db.thresholds, rid, "ScenarioThreshold")
    if threshold["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Threshold in status {threshold['status']} cannot be activated", 409)
    scenario = _get(db.scenarios, threshold["scenario_id"], "MonitoringScenario")
    current = None
    if scenario["current_active_threshold_id"]:
        current = db.thresholds.get(scenario["current_active_threshold_id"])
        if current is not None and current["status"] != "ACTIVE":
            current = None
    if current is not None and threshold["effective_from"] < current["effective_from"]:
        raise ApiError("ERR_THRESHOLD_WINDOW_OVERLAP",
                       "New version's effective_from precedes the current ACTIVE "
                       "version's effective_from", 409)
    if scenario["status"] != "ACTIVE":
        raise ApiError("ERR_SCENARIO_NOT_ACTIVE",
                       "Threshold activation requires the scenario to be ACTIVE", 409)
    if current is not None:
        current["status"] = "SUPERSEDED"
        current["effective_to"] = threshold["effective_from"]
        touch(current)
    threshold["status"] = "ACTIVE"
    touch(threshold)
    scenario["current_active_threshold_id"] = threshold["id"]
    touch(scenario)
    return response.success(serialize(threshold), status=200)


# ---------------------------------------------------------------------------
# Evaluation (scenario_trigger_evaluation + alert_risk_score)
# ---------------------------------------------------------------------------

@bp.route("/monitoring-scenarios/<rid>/evaluate", methods=["POST"])
def evaluate_scenario(rid):
    body = get_body()
    account_id = req_str(body, "account_id")
    evaluated_at = opt_dt(body, "evaluated_at")
    _, role = authn()
    authz(role, ["ComplianceAdmin", "BSAAnalyst"])
    scenario = _get(db.scenarios, rid, "MonitoringScenario")
    account = _get(db.accounts, account_id, "Account")

    threshold = None
    if scenario["current_active_threshold_id"]:
        candidate = db.thresholds.get(scenario["current_active_threshold_id"])
        if candidate is not None and candidate["status"] == "ACTIVE":
            threshold = candidate
    if threshold is None:
        raise ApiError("ERR_NO_ACTIVE_THRESHOLD",
                       "Evaluation requires a currently ACTIVE threshold version", 409)
    if scenario["status"] != "ACTIVE":
        raise ApiError("ERR_SCENARIO_NOT_ACTIVE",
                       "Evaluation requires the scenario to be ACTIVE", 409)

    window_end = evaluated_at if evaluated_at is not None else db.now()
    window_start = window_end - timedelta(days=threshold["lookback_days"])

    matching = [
        t for t in db.transactions.values()
        if t["account_id"] == account["id"]
        and t["txn_type"] in scenario["applies_to_txn_types"]
        and (scenario["direction_filter"] == "BOTH"
             or t["direction"] == scenario["direction_filter"])
        and window_start < t["posted_at"] <= window_end
    ]
    aggregate = sum(t["amount_cents"] for t in matching)
    txn_count = len(matching)

    # Idempotency: at most one Alert per (scenario_id, account_id, window_end).
    existing = next(
        (a for a in db.alerts.values()
         if a["scenario_id"] == scenario["id"]
         and a["account_id"] == account["id"]
         and a["window_end"] == window_end),
        None)
    if existing is not None:
        return response.success({
            "alert_created": False,
            "alert_id": existing["id"],
            "aggregate_amount_cents": aggregate,
            "txn_count": txn_count,
        }, status=200)

    fires = (aggregate >= threshold["threshold_amount_cents"]
             and txn_count >= threshold["min_transaction_count"])
    if not fires:
        return response.success({
            "alert_created": False,
            "alert_id": None,
            "aggregate_amount_cents": aggregate,
            "txn_count": txn_count,
        }, status=200)

    risky = high_risk_count(matching)
    tuned = alert_score(threshold["weight_amount"], threshold["weight_velocity"],
                        threshold["weight_geo"], aggregate, txn_count, risky,
                        threshold["threshold_amount_cents"],
                        threshold["min_transaction_count"])
    baseline = alert_score(scenario["baseline_weight_amount"],
                           scenario["baseline_weight_velocity"],
                           scenario["baseline_weight_geo"], aggregate, txn_count,
                           risky, threshold["threshold_amount_cents"],
                           threshold["min_transaction_count"])
    alert = base_entity()
    alert.update({
        "scenario_id": scenario["id"],
        "scenario_threshold_id": threshold["id"],
        "account_id": account["id"],
        "customer_id": account["customer_id"],
        "case_id": None,
        "window_start": window_start,
        "window_end": window_end,
        "aggregate_amount_cents": aggregate,
        "txn_count": txn_count,
        "risk_score": tuned,
        "baseline_score": baseline,
        "status": "NEW",
        "triaged_by_analyst_id": None,
        "dismissal_rationale": None,
        "dismissed_at": None,
        "closure_reason": None,
    })
    db.alerts[alert["id"]] = alert
    return response.success({
        "alert_created": True,
        "alert_id": alert["id"],
        "aggregate_amount_cents": aggregate,
        "txn_count": txn_count,
    }, status=200)
