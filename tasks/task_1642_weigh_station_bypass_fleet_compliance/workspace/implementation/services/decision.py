"""The roadside bypass decision engine (PRD 3.5; calculations
bypass_decision_evaluation, deterministic_random_screen, bypass_rate_cap_check).

Fourteen checks in pinned order; the first failing check fixes PULL_IN with
that single reason code. Supporting facts (selected credential, ruleset
version, weight/credential flags, screen ordinal, pre-decision counters) are
frozen onto the event record.
"""
from db import store

WIM_TOLERANCE_BPS = 500


def _select_credential(vehicle_id, station, config):
    """Channel-compatible ACTIVE credentials; PILOT prefers MOBILE_APP, other
    configs prefer TRANSPONDER; ties break toward earliest created_at (never
    id). Returns (selected_or_None, active_count, candidate_count)."""
    active = [
        c
        for c in store.credentials.values()
        if c["vehicle_id"] == vehicle_id and c["status"] == "ACTIVE"
    ]
    if station["supported_channel"] == "BOTH":
        candidates = list(active)
    else:
        candidates = [
            c for c in active if c["device_type"] == station["supported_channel"]
        ]
    prefer = (
        "MOBILE_APP" if config["participation_status"] == "PILOT" else "TRANSPONDER"
    )
    candidates.sort(key=lambda c: (0 if c["device_type"] == prefer else 1, c["_seq"]))
    return (candidates[0] if candidates else None), len(active), len(candidates)


def evaluate_event(vehicle, station, config, carrier, approach_dt,
                   measured_weight, credentials_presented, hazmat_load):
    selected, n_active, _n_candidates = _select_credential(
        vehicle["id"], station, config
    )

    gvwr = vehicle["gvwr_lbs"]
    weight_limit = gvwr + (gvwr * WIM_TOLERANCE_BPS) // 10000
    weight_verified = measured_weight is not None and measured_weight <= weight_limit
    credentials_complete = set(config["credential_sets_required"]).issubset(
        set(credentials_presented)
    )

    # Pre-decision counters for the (carrier, state, month) bucket and the
    # (station, day) screen ordinal. "Prior" = recorded before this event.
    month_key = (approach_dt.year, approach_dt.month)
    day_key = approach_dt.date()
    cap_total_before = 0
    cap_granted_before = 0
    for e in store.events.values():
        if e["carrier_id"] != carrier["id"]:
            continue
        est = store.stations.get(e["station_id"])
        if est is None or est["state_program_config_id"] != config["id"]:
            continue
        if (e["_approach_dt"].year, e["_approach_dt"].month) != month_key:
            continue
        cap_total_before += 1
        if e["decision"] == "BYPASS_GRANTED":
            cap_granted_before += 1
    ordinal = 1 + sum(
        1
        for e in store.events.values()
        if e["station_id"] == station["id"] and e["_approach_dt"].date() == day_key
    )

    reason = None
    screen_index = None

    # 1-14 in pinned order
    if station["operational_status"] != "OPERATIONAL":
        reason = "STATION_NOT_OPERATIONAL"
    elif station["station_type"] == "MOBILE_PATROL":
        reason = "STATION_TYPE_NO_BYPASS"
    elif config["participation_status"] == "SUSPENDED":
        reason = "STATE_NOT_PARTICIPATING"
    elif carrier["status"] != "ACTIVE":
        reason = "CARRIER_NOT_ACTIVE"
    elif carrier["eligibility_status"] in ("INELIGIBLE", "NOT_EVALUATED"):
        reason = "CARRIER_INELIGIBLE"
    elif (
        carrier["latest_iss_score"] is not None
        and carrier["latest_iss_score"] >= config["iss_refusal_threshold"]
    ):
        reason = "ISS_ABOVE_STATE_THRESHOLD"
    elif vehicle["service_status"] != "IN_SERVICE":
        reason = "VEHICLE_OUT_OF_SERVICE"
    elif n_active == 0:
        reason = "NO_ACTIVE_CREDENTIAL"
    elif selected is None:
        reason = "CHANNEL_UNSUPPORTED"
    elif (
        config["participation_status"] == "PILOT"
        and selected["device_type"] != "MOBILE_APP"
    ):
        reason = "PILOT_APP_ONLY"
    elif hazmat_load and not config["hazmat_bypass_allowed"]:
        reason = "HAZMAT_NOT_PERMITTED"
    elif measured_weight is not None and measured_weight > weight_limit:
        reason = "OVERWEIGHT"
    elif config["requires_weight_clearance"] and measured_weight is None:
        reason = "WEIGHT_NOT_CLEARED"
    elif not credentials_complete:
        reason = "CREDENTIALS_INCOMPLETE"
    else:
        bps = config["random_pull_in_rate_bps"]
        if bps:
            n = 10000 // bps
            if ordinal % n == 0:
                reason = "RANDOM_SCREEN"
                screen_index = ordinal
        if reason is None:
            cap = config["bypass_rate_cap_bps"]
            if carrier["eligibility_status"] == "CONDITIONAL":
                cap //= 2
            if (cap_granted_before + 1) * 10000 > cap * (cap_total_before + 1):
                reason = "RATE_CAP_EXCEEDED"

    return {
        "decision": "PULL_IN" if reason else "BYPASS_GRANTED",
        "decision_reasons": [reason] if reason else [],
        "selected_credential_id": selected["id"] if selected else None,
        "ruleset_version": config["version"],
        "weight_verified": weight_verified,
        "credentials_complete": credentials_complete,
        "screen_index": screen_index,
        "cap_granted_before": cap_granted_before,
        "cap_total_before": cap_total_before,
    }
