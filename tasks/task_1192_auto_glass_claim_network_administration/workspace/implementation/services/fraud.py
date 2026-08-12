"""Fraud signal accumulation, threshold gate, and score reversal."""

from datetime import timedelta

from db import store, base_fields, touch, now_dt

REPEAT_WINDOW_POINTS = 40
REPEAT_WINDOW_DAYS = 90
SOLICITATION_POINTS = 35
RAPID_COMPLETION_POINTS = 25
FRAUD_THRESHOLD = 100

ALERT_TYPES = {"REPEAT_WINDOW", "SOLICITATION", "RAPID_COMPLETION", "SCORE_THRESHOLD"}


def create_alert(policyholder_id, claim_id, alert_type, score_contribution):
    alert = base_fields()
    alert.update(
        {
            "policyholder_id": policyholder_id,
            "claim_id": claim_id,
            "alert_type": alert_type,
            "score_contribution": score_contribution,
            "resolution_notes": None,
            "status": "OPEN",
        }
    )
    store.fraud_alerts[alert["id"]] = alert
    return alert


def apply_signal(policyholder, claim_id, alert_type, points):
    """Create the signal alert, add points, and fire the threshold gate."""
    before = policyholder["fraud_score"]
    create_alert(policyholder["id"], claim_id, alert_type, points)
    policyholder["fraud_score"] = before + points
    touch(policyholder)
    if before < FRAUD_THRESHOLD <= policyholder["fraud_score"]:
        create_alert(policyholder["id"], claim_id, "SCORE_THRESHOLD", 0)


def evaluate_repeat_window(policyholder, new_claim):
    """REPEAT_WINDOW: another claim of the same policyholder created within
    (now - 90 days, now] — strictly after the 90-day-ago instant, inclusive now."""
    now = now_dt()
    window_start = now - timedelta(days=REPEAT_WINDOW_DAYS)
    for other in store.claims.values():
        if other["id"] == new_claim["id"]:
            continue
        if other["policyholder_id"] != policyholder["id"]:
            continue
        created = other["_created_dt"]
        if window_start < created <= now:
            apply_signal(policyholder, new_claim["id"], "REPEAT_WINDOW", REPEAT_WINDOW_POINTS)
            return


def dismiss_alert(alert):
    policyholder = store.policyholders.get(alert["policyholder_id"])
    if policyholder is not None:
        policyholder["fraud_score"] = max(0, policyholder["fraud_score"] - alert["score_contribution"])
        touch(policyholder)
    if alert["alert_type"] == "SCORE_THRESHOLD":
        claim = store.claims.get(alert["claim_id"])
        if claim is not None and claim["status"] == "FRAUD_HOLD":
            claim["status"] = "SUBMITTED"
            touch(claim)


def confirm_alert(alert):
    if alert["alert_type"] == "SCORE_THRESHOLD":
        claim = store.claims.get(alert["claim_id"])
        if claim is not None and claim["status"] == "FRAUD_HOLD":
            claim["status"] = "DENIED"
            touch(claim)
            policyholder = store.policyholders.get(alert["policyholder_id"])
            if policyholder is not None:
                policyholder["status"] = "SUSPENDED"
                touch(policyholder)
