"""Gates (rungs 40/45/50) and the multi-hop cascades, including the clock sweep."""
from decimal import Decimal

from flask import g

import calc
from common import (CLOCK, CREDENTIAL_EXPIRY_WARNING_HOURS, days, fail, fmt_iso,
                    get_row, hours, new_row, now_dt, now_iso, parse_iso, rows,
                    touch)

# --------------------------------------------------------------------------
# Rung 40 — compliance posture, rung 45 — program status, rung 50 — duties
# --------------------------------------------------------------------------


def posture_gate(app, release_advancing=False):
    posture = app["compliance_posture"]
    if posture == "FROZEN":
        fail("ERR_APP_COMPLIANCE_FROZEN",
             "app %s is frozen: %s" % (app["id"], app["posture_reason_codes"]))
    if release_advancing and posture == "RESTRICTED":
        fail("ERR_APP_COMPLIANCE_RESTRICTED",
             "app %s is restricted: %s" % (app["id"], app["posture_reason_codes"]))


def program_gate(account):
    status = account["program_status"]
    if status == "EXPIRED":
        fail("ERR_PROGRAM_MEMBERSHIP_EXPIRED", "program membership has expired")
    if status in ("SUSPENDED", "TERMINATED"):
        fail("ERR_ACCOUNT_SUSPENDED", "account is %s" % status.lower())


def sod_must_differ(other_user_id):
    if other_user_id is not None and g.user_id == other_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
             "acting operator may not judge an artifact they produced")


def sod_must_equal(other_user_id):
    if other_user_id is None or g.user_id != other_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
             "only the claiming reviewer may perform this operation")


# --------------------------------------------------------------------------
# Shared cascade fragments
# --------------------------------------------------------------------------
def release_slot(submission):
    """Clear a submission's window assignment and re-derive that window."""
    window_id = submission.get("review_window_id")
    submission["review_window_id"] = None
    if window_id:
        window = get_row("review_capacity_window", window_id)
        if window is not None:
            calc.sync_window(window, bump=True)


def pause_active_plans(app, reason_code="POSTURE_DEGRADED"):
    """Pause every PHASE_ACTIVE plan of an app and mirror onto the app row."""
    paused = 0
    for plan in calc.plans_of_app(app["id"]):
        if plan["state"] != "PHASE_ACTIVE":
            continue
        plan["state"] = "PAUSED"
        plan["pause_reason_code"] = reason_code
        touch(plan)
        paused += 1
        if app["distribution_state"] == "PHASED_ROLLOUT":
            app["distribution_state"] = "PAUSED"
            touch(app)
    return paused


def recompute_app_and_dependents(app):
    calc.recompute_app_posture(app)


def recompute_account_apps(account):
    for app in calc.apps_of_account(account["id"]):
        calc.recompute_app_posture(app)


# --------------------------------------------------------------------------
# §3.2 — the four-hop key-compromise cascade
# --------------------------------------------------------------------------
def compromise_cascade(credential):
    affected_apps = {}
    for child in rows("signing_credential"):
        if child.get("linked_cert_id") != credential["id"]:
            continue
        if child["status"] not in ("PENDING_ACTIVATION", "ACTIVE", "EXPIRING_SOON"):
            continue
        child["status"] = "REVOKED"
        child["revocation_reason"] = "COMPROMISE_CASCADE"
        touch(child)
        for submission in rows("submission"):
            if submission.get("signing_credential_id") != child["id"]:
                continue
            if submission["state"] not in ("WAITING_FOR_REVIEW", "IN_REVIEW"):
                continue
            submission["state"] = "BLOCKED_INVALID_SIGNING"
            release_slot(submission)
            touch(submission)
            child["blocked_submission_count"] = child.get("blocked_submission_count", 0) + 1
            touch(child)
            app = get_row("app_record", submission["app_record_id"])
            if app is not None:
                affected_apps[app["id"]] = app
    account = get_row("publisher_account", credential["publisher_account_id"])
    if account is not None:
        for app in calc.apps_of_account(account["id"]):
            affected_apps.setdefault(app["id"], app)
    for app in affected_apps.values():
        calc.recompute_app_posture(app)
        if app["compliance_posture"] != "OPEN":
            pause_active_plans(app)


# --------------------------------------------------------------------------
# §3.4 — the four-hop guideline-publication cascade
# --------------------------------------------------------------------------
def publish_cascade(rule, superseded):
    staled_by_app = {}
    if superseded is not None:
        for mapping in rows("feature_mapping"):
            if mapping["guideline_rule_id"] != superseded["id"]:
                continue
            mapping["guideline_rule_id"] = rule["id"]
            if mapping["self_review_status"] in ("PASSED", "WAIVED_BY_PLATFORM"):
                mapping["self_review_status"] = "STALE"
                mapping["staled_by_rule_id"] = rule["id"]
                staled_by_app.setdefault(mapping["app_record_id"], []).append(mapping)
            touch(mapping)
            staled_by_app.setdefault(mapping["app_record_id"], [])
    impacted = 0
    for app_id, mappings in staled_by_app.items():
        app = get_row("app_record", app_id)
        if app is None:
            continue
        impacted += 1
        codes = [m["feature_code"] for m in
                 sorted(mappings, key=lambda m: (m["created_at"], m["_seq"]))]
        severity, factor = calc.impact_severity(rule, codes, app)
        new_row("impact_assessment", {
            "app_record_id": app_id,
            "guideline_rule_id": rule["id"],
            "status": "OPEN",
            "affected_feature_codes": codes,
            "exposure_factor": factor,
            "impact_severity": severity,
            "remediation_deadline_at": calc.remediation_deadline(rule),
            "opened_at": now_iso(),
            "assessed_by_user_id": None,
            "assessed_at": None,
            "note": None,
            "remediated_at": None,
        })
    rule["impacted_app_count"] = impacted
    for app_id in staled_by_app:
        app = get_row("app_record", app_id)
        if app is None:
            continue
        calc.recompute_app_posture(app)
        if app["compliance_posture"] != "OPEN":
            pause_active_plans(app)
    return impacted


# --------------------------------------------------------------------------
# §3.9 — the four-hop rejection cascade
# --------------------------------------------------------------------------
def rejection_cascade(app, cited_rule_ids):
    for mapping in calc.mappings_of_app(app["id"]):
        if mapping["guideline_rule_id"] not in cited_rule_ids:
            continue
        if mapping["self_review_status"] != "PASSED":
            continue
        mapping["self_review_status"] = "FAILED"
        touch(mapping)
    calc.recompute_app_posture(app)
    if app["compliance_posture"] != "OPEN":
        pause_active_plans(app)


# --------------------------------------------------------------------------
# §2.5 — the pinned six-step clock sweep
# --------------------------------------------------------------------------
def clock_sweep(new_utc):
    counters = {
        "credentials_warned_count": 0,
        "credentials_expired_count": 0,
        "accounts_expired_count": 0,
        "assessments_overdue_count": 0,
        "postures_frozen_count": 0,
        "rollouts_paused_count": 0,
    }
    CLOCK["current_utc"] = fmt_iso(new_utc)
    now = new_utc

    # (1) signing credentials: ACTIVE -> EXPIRING_SOON -> EXPIRED
    for cred in rows("signing_credential"):
        not_after = parse_iso(cred["not_after"])
        if cred["status"] in ("ACTIVE", "EXPIRING_SOON") and now >= not_after:
            cred["status"] = "EXPIRED"
            touch(cred)
            counters["credentials_expired_count"] += 1
        elif (cred["status"] == "ACTIVE"
              and now >= not_after - hours(CREDENTIAL_EXPIRY_WARNING_HOURS)):
            cred["status"] = "EXPIRING_SOON"
            touch(cred)
            counters["credentials_warned_count"] += 1

    # (2) publisher accounts: ACTIVE -> EXPIRED
    for account in rows("publisher_account"):
        if account["program_status"] != "ACTIVE":
            continue
        paid_through = parse_iso(account["membership_paid_through_at"])
        if paid_through is not None and now > paid_through:
            account["program_status"] = "EXPIRED"
            touch(account)
            counters["accounts_expired_count"] += 1

    # (3) impact assessments: REMEDIATION_REQUIRED -> OVERDUE (strictly past)
    for assessment in rows("impact_assessment"):
        if assessment["status"] != "REMEDIATION_REQUIRED":
            continue
        deadline = parse_iso(assessment["remediation_deadline_at"])
        if deadline is not None and now > deadline:
            assessment["status"] = "OVERDUE"
            touch(assessment)
            counters["assessments_overdue_count"] += 1

    # (4) posture recompute for every app record
    newly_frozen = []
    for app in rows("app_record"):
        before = app["compliance_posture"]
        calc.recompute_app_posture(app)
        if app["compliance_posture"] == "FROZEN" and before != "FROZEN":
            newly_frozen.append(app)
            counters["postures_frozen_count"] += 1

    # (5) PHASE_ACTIVE rollouts of newly frozen apps are paused
    for app in newly_frozen:
        counters["rollouts_paused_count"] += pause_active_plans(app)

    # (6) standing / expedite rolling windows, then the priority forward pass
    for account in rows("publisher_account"):
        calc.recompute_account_standing(account)
    for submission in rows("submission"):
        if submission["state"] != "WAITING_FOR_REVIEW":
            continue
        app = get_row("app_record", submission["app_record_id"])
        if app is None:
            continue
        account = calc.account_of_app(app)
        if account is None:
            continue
        before = (submission.get("priority_score"), submission.get("priority_band"),
                  submission.get("effective_review_deadline_at"))
        calc.priority_pass(submission, account, first_time=False)
        after = (submission.get("priority_score"), submission.get("priority_band"),
                 submission.get("effective_review_deadline_at"))
        if before != after:
            touch(submission)
    counters["current_utc"] = CLOCK["current_utc"]
    return counters
