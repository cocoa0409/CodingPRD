"""App records: the listing dimension, the posture explanation and settlement."""
from flask import Blueprint, g, request

import calc
import flows
from common import (arg_filter, body_json, endpoint, fail, get_row, jsonable,
                    new_row, now_dt, ok, paginate, public, resolve, rows,
                    scope_rows, touch)
from valid import check_unknown, req_id, req_str

bp = Blueprint("apps", __name__)

PLATFORMS = {"IOS", "ANDROID"}
CATEGORIES = {"GAMES", "FINANCE", "HEALTH", "SOCIAL", "PRODUCTIVITY", "KIDS"}
LISTING_ACTIONS = {"COMPLETE_METADATA", "LIST", "DELIST", "RETURN_TO_DRAFT"}
BLOCKING_PLAN_STATES = ("SCHEDULED", "PHASE_ACTIVE", "PAUSED")


@bp.route("/app-records", methods=["POST"])
@endpoint(["PublisherAdmin"])
def create_app_record():
    body = body_json()
    check_unknown(body, {"publisher_account_id", "bundle_id", "platform",
                         "display_name", "primary_category"})
    (account,) = resolve([("publisher_account", body.get("publisher_account_id"))])
    req_id(body, "publisher_account_id")
    bundle_id = req_str(body, "bundle_id", 1, 200)
    platform = req_str(body, "platform", enum=PLATFORMS)
    req_str(body, "display_name", 1, 30)
    req_str(body, "primary_category", enum=CATEGORIES)
    for existing in rows("app_record"):
        if (existing["publisher_account_id"] == account["id"]
                and existing["platform"] == platform
                and existing["bundle_id"] == bundle_id):
            fail("ERR_VALIDATION",
                 "bundle_id is already used on this platform by this account")
    flows.program_gate(account)
    row = new_row("app_record", {
        "publisher_account_id": account["id"],
        "bundle_id": bundle_id,
        "platform": platform,
        "display_name": body["display_name"],
        "primary_category": body["primary_category"],
        "listing_state": "DRAFT",
        "distribution_state": "NOT_DISTRIBUTED",
        "compliance_posture": "RESTRICTED",
        "posture_reason_codes": [],
        "feature_compliance_index": calc.d2("0"),
        "live_submission_id": None,
        "released_share_pct": calc.d2("0"),
        "held_back_share_pct": calc.d2("100"),
        "rollback_count": 0,
    })
    calc.recompute_app_posture(row, bump=False)
    return ok(public(row), 201)


@bp.route("/app-records", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "PlatformAppealBoard",
           "Auditor"])
def list_app_records():
    items = rows("app_record")
    for field in ("publisher_account_id", "live_submission_id", "platform",
                  "primary_category", "listing_state", "distribution_state",
                  "compliance_posture"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/app-records/<app_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "PlatformAppealBoard",
           "Auditor"])
def read_app_record(app_id):
    (app,) = resolve([("app_record", app_id)])
    return ok(public(app))


def _metadata_ready(app):
    """True when some submission of the app owns a complete primary locale."""
    screenshot_shortfall = False
    for submission in calc.submissions_of_app(app["id"]):
        for locale in rows("metadata_locale"):
            if locale["submission_id"] != submission["id"]:
                continue
            if not locale.get("is_primary"):
                continue
            if locale.get("is_complete"):
                return True, False
            if locale.get("title"):
                screenshot_shortfall = True
    return False, screenshot_shortfall


@bp.route("/app-records/<app_id>/listing", methods=["PATCH"])
@endpoint(["PublisherAdmin", "PlatformPolicyAdmin"])
def drive_listing(app_id):
    (app,) = resolve([("app_record", app_id)])
    body = body_json()
    check_unknown(body, {"listing_action"})
    action = req_str(body, "listing_action", enum=LISTING_ACTIONS)
    if g.role == "PlatformPolicyAdmin" and action != "DELIST":
        fail("ERR_ROLE_NOT_PERMITTED",
             "a PlatformPolicyAdmin may only delist a listing")
    state = app["listing_state"]
    allowed = {
        "COMPLETE_METADATA": ("DRAFT",),
        "LIST": ("METADATA_COMPLETE", "DELISTED"),
        "DELIST": ("LISTED",),
        "RETURN_TO_DRAFT": ("DELISTED",),
    }[action]
    if state not in allowed:
        fail("ERR_INVALID_LISTING_STATE",
             "listing_action %s is not declared for listing_state %s"
             % (action, state))
    flows.posture_gate(app)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    if action == "COMPLETE_METADATA":
        ready, screenshot_shortfall = _metadata_ready(app)
        if not ready:
            if screenshot_shortfall:
                fail("ERR_SCREENSHOT_SET_INCOMPLETE",
                     "the primary locale is short of required screenshots")
            fail("ERR_METADATA_INCOMPLETE",
                 "no submission of this app owns a complete primary locale")
        app["listing_state"] = "METADATA_COMPLETE"
    elif action == "LIST":
        if app["distribution_state"] not in ("PHASED_ROLLOUT", "FULLY_RELEASED",
                                            "PAUSED"):
            fail("ERR_APP_NOT_DISTRIBUTED",
                 "a store page may only go live once a build is distributed")
        app["listing_state"] = "LISTED"
    elif action == "DELIST":
        app["listing_state"] = "DELISTED"
    else:
        for plan in calc.plans_of_app(app["id"]):
            if plan["state"] in BLOCKING_PLAN_STATES:
                fail("ERR_INVALID_ROLLOUT_STATE",
                     "a rollout plan of this app is still %s" % plan["state"])
        app["listing_state"] = "DRAFT"
    touch(app)
    return ok(public(app))


@bp.route("/app-records/<app_id>/compliance-summary", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformPolicyAdmin", "Auditor"])
def compliance_summary(app_id):
    (app,) = resolve([("app_record", app_id)])
    index = calc.feature_compliance_index(app)
    posture, codes = calc.compliance_posture(app, index)
    mappings = calc.mappings_of_app(app["id"])
    assessments = calc.assessments_of_app(app["id"])
    critical = [f for f in calc.findings_of_app(app["id"])
                if f["severity"] == "CRITICAL" and f["status"] in ("OPEN", "DISPUTED")]
    return ok(jsonable({
        "compliance_posture": posture,
        "posture_reason_codes": codes,
        "feature_compliance_index": index,
        "mapping_total": len(mappings),
        "mapping_passed": len([m for m in mappings
                               if m["self_review_status"] == "PASSED"]),
        "mapping_stale": len([m for m in mappings
                              if m["self_review_status"] == "STALE"]),
        "mapping_failed": len([m for m in mappings
                               if m["self_review_status"] == "FAILED"]),
        "open_impact_count": len([a for a in assessments
                                  if a["status"] in ("OPEN", "IN_ASSESSMENT",
                                                     "REMEDIATION_REQUIRED")]),
        "overdue_impact_count": len([a for a in assessments
                                     if a["status"] == "OVERDUE"]),
        "critical_finding_open_count": len(critical),
        "active_distribution_cert_present": calc.active_distribution_cert_present(app),
    }))


@bp.route("/app-records/<app_id>/commerce-settlement", methods=["GET"])
@endpoint(["PublisherAdmin", "PlatformPolicyAdmin", "Auditor"])
def commerce_settlement(app_id):
    (app,) = resolve([("app_record", app_id)])
    period_label = request.args.get("period_label")
    if period_label is None or period_label == "":
        fail("ERR_VALIDATION", "period_label is required")
    return ok(jsonable(calc.settlement(app, period_label)))
