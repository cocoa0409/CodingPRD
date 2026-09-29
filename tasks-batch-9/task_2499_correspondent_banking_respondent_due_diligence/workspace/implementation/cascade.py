"""Rollups and cross-entity cascades (PRD 2.10, 3.2, 3.5, 3.6, 3.8)."""

import calc
import clock
import store
from errors import fail
from validate import dec, q2

APPROVED_FAMILY = ("APPROVED", "REFRESH_DUE", "UNDER_REFRESH", "REFRESH_OVERDUE")


# ----------------------------------------------------------- nested graph ----

def compute_nested_depth(row):
    """Returns (depth, cycle_detected) per PRD 3.5."""
    visited = {row["respondent_bank_id"]}
    depth = 1
    cur = row
    guard = 0
    while cur.get("downstream_respondent_bank_id"):
        guard += 1
        if guard > 32:
            return depth, True
        nxt = cur["downstream_respondent_bank_id"]
        if nxt in visited:
            return depth, True
        visited.add(nxt)
        live = [r for r in store.nested_of(nxt)
                if r["state"] in calc.NESTED_LIVE and r["id"] != row["id"]]
        if not live:
            break
        live.sort(key=lambda r: (-int(r["depth"] or 0), r["_seq"]))
        cur = live[0]
        depth += 1
    return depth, False


def prohibition_ladder(row, respondent, depth=None, cycle=None):
    """First-match ladder; returns (prohibition_reason, error_id) or (None, None)."""
    if depth is None or cycle is None:
        depth, cycle = compute_nested_depth(row)
    if cycle:
        return "CYCLE", "ERR_NESTED_CYCLE_DETECTED"
    jp = store.jurisdiction_by_code(row["downstream_jurisdiction_code"])
    if jp is not None and jp["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED":
        return "SANCTIONED_JURISDICTION", "ERR_NESTED_SANCTIONED_JURISDICTION"
    if jp is not None and jp["nested_correspondent_prohibited"]:
        return "JURISDICTION_PROHIBITS_NESTING", "ERR_NESTED_JURISDICTION_PROHIBITS_NESTING"
    if depth >= 3:
        return "DEPTH_EXCEEDED", "ERR_NESTED_DEPTH_EXCEEDED"
    if row["relationship_type"] == "PAYABLE_THROUGH" and not respondent["nested_activity_permitted"]:
        return "PAYABLE_THROUGH_NOT_PERMITTED", "ERR_PAYABLE_THROUGH_NOT_PERMITTED"
    return None, None


def nested_rollup(respondent):
    rows = store.nested_of(respondent["id"])
    units = 0
    disclosed = 0
    undisclosed = 0
    max_depth = 0
    for row in rows:
        weight = calc.NESTED_STATE_WEIGHT.get(row["state"], 0)
        units += weight * int(row["depth"] or 0)
        if row["state"] in ("DISCLOSED", "CONFIRMED"):
            disclosed += 1
        if row["state"] == "UNDISCLOSED_DETECTED":
            undisclosed += 1
        if row["state"] in calc.NESTED_LIVE:
            max_depth = max(max_depth, int(row["depth"] or 0))
    changed = (respondent["nested_exposure_units"] != units
               or respondent["disclosed_nested_count"] != disclosed
               or respondent["undisclosed_nested_count"] != undisclosed
               or respondent["max_nested_depth"] != max_depth)
    respondent["nested_exposure_units"] = units
    respondent["disclosed_nested_count"] = disclosed
    respondent["undisclosed_nested_count"] = undisclosed
    respondent["max_nested_depth"] = max_depth
    if changed:
        store.touch(respondent)


# -------------------------------------------------------------- payments -----

def hold_cleared_payments(respondent):
    """SCREENED_CLEAR -> HELD_FOR_REVIEW when the posture leaves OPEN."""
    held = 0
    for pay in store.payments_of(respondent["id"]):
        if pay["screening_state"] == "SCREENED_CLEAR":
            pay["screening_state"] = "HELD_FOR_REVIEW"
            pay["hold_reason"] = "POSTURE_SCREEN_ONLY"
            store.touch(pay)
            held += 1
    return held


def block_payments_for_sanctions(rows):
    for pay in store.by_seq(rows):
        if pay["screening_state"] in ("RECEIVED", "SCREENED_CLEAR", "HELD_FOR_REVIEW"):
            pay["screening_state"] = "BLOCKED_SANCTIONS"
            pay["hold_reason"] = None
            store.touch(pay)


def require_recalibration(respondent, reason):
    for prof in store.profiles_of(respondent["id"]):
        if prof["calibration_state"] == "CALIBRATED":
            prof["calibration_state"] = "RECALIBRATION_REQUIRED"
            prof["recalibration_reason"] = reason
            store.touch(prof)
            return True
    return False


def suspend_confirmed_nested(respondent):
    count = 0
    for row in store.nested_of(respondent["id"]):
        if row["state"] == "CONFIRMED":
            row["state"] = "SUSPENDED"
            store.touch(row)
            count += 1
    if count:
        nested_rollup(respondent)
    return count


# ------------------------------------------------------------- restriction ---

def restrict(respondent, reason, posture="BLOCKED"):
    """Move dd_state to RESTRICTED and run the documented restriction cascade."""
    respondent["dd_state"] = "RESTRICTED"
    respondent["restriction_reason"] = reason
    if posture is not None:
        respondent["payment_posture"] = posture
    store.touch(respondent)
    suspended = suspend_confirmed_nested(respondent)
    if suspended:
        require_recalibration(respondent, "OFFICER_ACTION")


def narrow_to_screen_only(respondent):
    """OPEN -> SCREEN_ONLY plus the held-payment hop (PRD 3.6)."""
    if respondent["payment_posture"] != "OPEN":
        return False
    if respondent["dd_state"] not in APPROVED_FAMILY:
        return False
    respondent["payment_posture"] = "SCREEN_ONLY"
    store.touch(respondent)
    hold_cleared_payments(respondent)
    return True


# ------------------------------------------------------------ strike ledger --

def recompute_escalation_units(respondent):
    total = 0
    for rfi in store.rfis_of(respondent["id"]):
        total += int(rfi["escalation_level"])
    if respondent["escalation_units"] != total:
        respondent["escalation_units"] = total
        store.touch(respondent)


def add_strike(respondent, amount=1):
    respondent["unresponsive_strikes"] = int(respondent["unresponsive_strikes"]) + amount
    store.touch(respondent)
    enforce_strike_threshold(respondent)


def credit_strikes(respondent, reminder_count):
    current = int(respondent["unresponsive_strikes"])
    respondent["unresponsive_strikes"] = max(0, current - int(reminder_count))
    store.touch(respondent)


def enforce_strike_threshold(respondent):
    if int(respondent["unresponsive_strikes"]) < 3:
        return
    if respondent["dd_state"] in ("EXITING", "TERMINATED"):
        return
    posture = respondent["payment_posture"]
    new_posture = "SCREEN_ONLY" if posture == "OPEN" else posture
    restrict(respondent, "UNRESPONSIVE_STRIKES", new_posture)


# --------------------------------------------------------- alert closures ----

def close_alert_from_rfi(rfi, reason):
    alert_id = rfi.get("monitoring_alert_id")
    if not alert_id:
        return
    alert = store.get("alerts", alert_id)
    if alert is None or alert["state"] != "ESCALATED":
        return
    alert["state"] = "CLOSED_CONFIRMED"
    alert["disposition_reason"] = reason
    store.touch(alert)


# ------------------------------------------------------------ scoring ---------

def run_risk_assessment(respondent, variant, user_id):
    """The six pinned steps of PRD 3.6."""
    calc.ownership_rollup(respondent)
    respondent["inherent_risk_score"] = calc.inherent_risk_score(respondent)
    questionnaire = latest_assessed_questionnaire(respondent)
    if questionnaire is not None:
        respondent["control_score"] = calc.control_score(questionnaire, variant)
    start, end = calc.media_window(respondent, variant)
    respondent["adverse_media_uplift"] = calc.adverse_media_uplift(respondent, start, end)
    respondent["control_credit"] = calc.control_credit_of(respondent["control_score"])
    respondent["residual_risk_score"] = calc.residual_from(
        respondent["inherent_risk_score"],
        respondent["control_credit"],
        respondent["adverse_media_uplift"])
    respondent["risk_rating"] = calc.rating_from(
        respondent, respondent["residual_risk_score"])
    respondent["risk_assessment_variant"] = variant
    respondent["assessed_by_user_id"] = user_id
    store.set_dt(respondent, "last_risk_assessed_at", clock.now())
    store.touch(respondent)


def latest_assessed_questionnaire(respondent):
    rows = [q for q in store.questionnaires_of(respondent["id"])
            if q["state"] == "ASSESSED"]
    if not rows:
        return None
    return store.by_seq_desc(rows)[0]


def recompute_media_scores(respondent):
    """Hop two of the adverse-media confirmation cascade."""
    variant = respondent["risk_assessment_variant"]
    window_variant = variant if variant in ("ONBOARDING_PROVISIONAL", "REFRESH_FINAL") else "ONBOARDING_PROVISIONAL"
    start, end = calc.media_window(respondent, window_variant)
    respondent["adverse_media_uplift"] = calc.adverse_media_uplift(respondent, start, end)
    respondent["residual_risk_score"] = calc.residual_from(
        respondent["inherent_risk_score"],
        respondent["control_credit"],
        respondent["adverse_media_uplift"])
    respondent["risk_rating"] = calc.rating_from(
        respondent, respondent["residual_risk_score"])
    store.touch(respondent)


def write_refresh_due_date(respondent):
    value = calc.refresh_due_date(respondent)
    store.set_dt(respondent, "refresh_due_date", value)
    store.touch(respondent)
    return value


# ---------------------------------------------------------- refresh cycles ---

def cancel_cycles(respondent, states, reason):
    for cycle in store.refreshes_of(respondent["id"]):
        if cycle["state"] in states:
            cycle["state"] = "CANCELLED"
            cycle["cancelled_reason"] = reason
            store.touch(cycle)


def schedule_cycle(respondent, trigger_reason, window_start, scheduled_due_date,
                   rating_at_schedule=None, cadence_rating=None):
    rating = rating_at_schedule or respondent["approved_risk_rating"]
    cadence_source = cadence_rating or rating
    row = store.insert("refreshes", {
        "respondent_bank_id": respondent["id"],
        "trigger_reason": trigger_reason,
        "window_start": clock.iso(window_start),
        "scheduled_due_date": clock.iso(scheduled_due_date),
        "state": "SCHEDULED",
        "cadence_months_applied": calc.CADENCE_MONTHS.get(cadence_source, 0),
        "rating_at_schedule": rating,
        "started_at": None,
        "completed_at": None,
        "lapsed_at": None,
        "completed_control_score": None,
        "completion_risk_rating": None,
        "cancelled_reason": None,
    })
    return row


def terminate_all_nested(respondent):
    for row in store.nested_of(respondent["id"]):
        if row["state"] in calc.NESTED_LIVE:
            row["state"] = "TERMINATED"
            store.touch(row)
    nested_rollup(respondent)


def abandon_open_rfis(respondent, add_strikes=False):
    for rfi in store.rfis_of(respondent["id"]):
        if rfi["state"] in ("DRAFT", "SENT", "RESPONDED", "OVERDUE", "ESCALATED"):
            rfi["state"] = "ABANDONED"
            rfi["escalation_level"] = 0
            store.touch(rfi)
    recompute_escalation_units(respondent)


# --------------------------------------------------------------- guards ------

def guard_not_closed(respondent, allow_exiting=False):
    """Priority 20."""
    if respondent["dd_state"] == "TERMINATED":
        fail("ERR_RESPONDENT_RELATIONSHIP_CLOSED",
             "A terminated relationship accepts reads only.")
    if respondent["dd_state"] == "EXITING" and not allow_exiting:
        fail("ERR_RESPONDENT_RELATIONSHIP_CLOSED",
             "An exiting relationship accepts only closure, payment screening and "
             "information-request handling.")


def live_plan(respondent):
    for plan in store.by_seq_desc(store.plans_of(respondent["id"])):
        if plan["state"] in ("APPROVED", "NOTICE_SERVED", "WIND_DOWN"):
            return plan
    return None


def open_plan(respondent):
    for plan in store.by_seq_desc(store.plans_of(respondent["id"])):
        if plan["state"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED",
                             "NOTICE_SERVED", "WIND_DOWN"):
            return plan
    return None


def covering_profile(respondent, instant):
    """The CALIBRATED profile whose closed interval contains the instant."""
    for prof in store.profiles_of(respondent["id"]):
        if prof["calibration_state"] != "CALIBRATED":
            continue
        start = store.dt(prof, "effective_from")
        end = store.dt(prof, "effective_to")
        if start is not None and end is not None and start <= instant <= end:
            return prof
    return None


# ------------------------------------------------- information requests ------

def new_request(respondent, topic, severity, alert_id=None, state="DRAFT"):
    row = store.insert("rfis", {
        "respondent_bank_id": respondent["id"],
        "monitoring_alert_id": alert_id,
        "request_topic": topic,
        "severity": severity,
        "state": state,
        "dispatched_at": None,
        "sla_hours": None,
        "due_at": None,
        "escalation_level": 0,
        "reminder_count": 0,
        "insufficiency_rounds": 0,
        "responded_at": None,
        "response_note": "",
        "adjudicated_by_user_id": None,
        "retro_credited": False,
    })
    return row


def dispatch_request(rfi, respondent):
    """Stamp the service level and move an information request to SENT."""
    now = clock.now()
    hours = calc.rfi_sla_hours(respondent, rfi["severity"])
    store.set_dt(rfi, "dispatched_at", now)
    rfi["sla_hours"] = hours
    store.set_dt(rfi, "due_at", clock.add_hours(now, hours))
    rfi["state"] = "SENT"
    if int(rfi["escalation_level"]) < 1:
        rfi["escalation_level"] = 1
    store.touch(rfi)
    recompute_escalation_units(respondent)
    return rfi


def escalate_alert(alert, respondent):
    """The five-hop escalation cascade of PRD 3.7."""
    alert["state"] = "ESCALATED"
    store.set_dt(alert, "escalated_at", clock.now())
    store.touch(alert)
    topic = "ACTIVITY_EXPLANATION" if alert["alert_type"] in (
        "VOLUME_BREACH", "COUNT_BREACH", "CORRIDOR_UNEXPECTED") else "NESTED_DISCLOSURE"
    rfi = new_request(respondent, topic, alert["severity"], alert["id"])
    dispatch_request(rfi, respondent)
    if rfi["severity"] == "CRITICAL" and respondent["payment_posture"] == "OPEN" \
            and respondent["dd_state"] in APPROVED_FAMILY:
        respondent["payment_posture"] = "SCREEN_ONLY"
        store.touch(respondent)
        held = hold_cleared_payments(respondent)
        if held:
            require_recalibration(respondent, "ALERT_ESCALATION")
    return rfi
