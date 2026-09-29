"""Publisher accounts, signing credentials and the logical clock."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import flows
from common import (CLOCK, d2, endpoint, fail, fmt_iso, get_row, jsonable,
                    new_row, now_dt, now_iso, ok, paginate, parse_iso, public,
                    resolve, rows, scope_rows, body_json, touch, arg_filter)
from valid import (check_unknown, opt_array, opt_int, opt_str, req_id, req_int,
                   req_iso, req_str)

bp = Blueprint("accounts", __name__)

PROGRAM_STATUSES = {"ACTIVE", "EXPIRED", "SUSPENDED", "TERMINATED"}
TIERS = {"SMALL_BUSINESS", "STANDARD"}
CREDENTIAL_TYPES = {"DISTRIBUTION_CERT", "PROVISIONING_PROFILE"}
PLATFORMS = {"IOS", "ANDROID"}
CUSTODY = {"HSM", "CLOUD_MANAGED", "LOCAL_KEYCHAIN"}
ENTITLEMENTS = {"IN_APP_PURCHASE", "EXTERNAL_PAYMENT_LINK", "PUSH_NOTIFICATIONS",
                "BACKGROUND_LOCATION"}
REVOCATION_REASONS = {"SUPERSEDED", "MANUAL", "COMPROMISE_CASCADE"}
ALL_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
             "PlatformReviewer", "PlatformAppealBoard", "PlatformPolicyAdmin",
             "Auditor"]


# --------------------------------------------------------------------------
# PublisherAccount
# --------------------------------------------------------------------------
@bp.route("/publisher-accounts", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def create_publisher_account():
    body = body_json()
    check_unknown(body, {"legal_name", "contact_email",
                         "membership_paid_through_at", "commerce_program_tier"})
    legal_name = req_str(body, "legal_name", 1, 120)
    contact_email = req_str(body, "contact_email", 1)
    if "@" not in contact_email:
        fail("ERR_VALIDATION", "contact_email must contain '@'")
    paid_through = req_iso(body, "membership_paid_through_at")
    tier = opt_str(body, "commerce_program_tier", enum=TIERS, default="STANDARD",
                   nullable=False)
    for existing in rows("publisher_account"):
        if existing["legal_name"] == legal_name:
            fail("ERR_VALIDATION", "legal_name is already registered")
    status = "ACTIVE" if paid_through > now_dt() else "EXPIRED"
    row = new_row("publisher_account", {
        "legal_name": legal_name,
        "contact_email": contact_email,
        "program_status": status,
        "commerce_program_tier": tier,
        "membership_paid_through_at": fmt_iso(paid_through),
        "enforcement_reason_code": None,
        "standing_score_rolling_365": d2("100"),
        "standing_score_lifetime": d2("100"),
        "expedite_credits_remaining": 2,
        "rejection_strike_count": 0,
        "settlement_finalized_periods": [],
    })
    return ok(public(row), 201)


@bp.route("/publisher-accounts", methods=["GET"])
@endpoint(["PlatformPolicyAdmin", "PlatformReviewer", "PlatformAppealBoard",
           "Auditor", "PublisherAdmin"])
def list_publisher_accounts():
    items = rows("publisher_account")
    status = arg_filter("program_status")
    tier = arg_filter("commerce_program_tier")
    if status is not None:
        items = [r for r in items if r["program_status"] == status]
    if tier is not None:
        items = [r for r in items if r["commerce_program_tier"] == tier]
    return paginate(scope_rows(items))


@bp.route("/publisher-accounts/<account_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformPolicyAdmin", "PlatformReviewer", "PlatformAppealBoard",
           "Auditor"])
def read_publisher_account(account_id):
    (account,) = resolve([("publisher_account", account_id)])
    return ok(public(account))


@bp.route("/publisher-accounts/<account_id>/membership-renewal", methods=["POST"])
@endpoint(["PublisherAdmin"])
def renew_membership(account_id):
    (account,) = resolve([("publisher_account", account_id)])
    body = body_json()
    check_unknown(body, {"expected_publisher_account_version", "paid_through_at"})
    expected = req_int(body, "expected_publisher_account_version")
    paid_through = req_iso(body, "paid_through_at")
    if paid_through <= now_dt():
        fail("ERR_VALIDATION", "paid_through_at must be later than the current instant")
    if expected != account["version"]:
        fail("ERR_STALE_PUBLISHER_ACCOUNT_VERSION",
             "expected_publisher_account_version does not match")
    account["membership_paid_through_at"] = fmt_iso(paid_through)
    if account["program_status"] == "EXPIRED":
        account["program_status"] = "ACTIVE"
    touch(account)
    flows.recompute_account_apps(account)
    return ok(public(account))


@bp.route("/publisher-accounts/<account_id>/enforcement", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def enforce_account(account_id):
    (account,) = resolve([("publisher_account", account_id)])
    body = body_json()
    check_unknown(body, {"action", "reason_code"})
    action = req_str(body, "action", enum={"SUSPEND", "TERMINATE", "REINSTATE"})
    reason_code = req_str(body, "reason_code", 1)
    if action == "SUSPEND":
        account["program_status"] = "SUSPENDED"
        account["enforcement_reason_code"] = reason_code
    elif action == "TERMINATE":
        account["program_status"] = "TERMINATED"
        account["enforcement_reason_code"] = reason_code
    else:
        paid_through = parse_iso(account["membership_paid_through_at"])
        account["program_status"] = ("ACTIVE" if paid_through is not None
                                     and paid_through > now_dt() else "EXPIRED")
        account["enforcement_reason_code"] = None
    touch(account)
    flows.recompute_account_apps(account)
    return ok(public(account))


@bp.route("/publisher-accounts/<account_id>/standing", methods=["GET"])
@endpoint(["PublisherAdmin", "ComplianceOfficer", "PlatformAppealBoard",
           "PlatformPolicyAdmin", "Auditor"])
def read_standing(account_id):
    (account,) = resolve([("publisher_account", account_id)])
    return ok(jsonable(calc.standing_details(account)))


# --------------------------------------------------------------------------
# SigningCredential
# --------------------------------------------------------------------------
@bp.route("/signing-credentials", methods=["POST"])
@endpoint(["PublisherAdmin"])
def create_credential():
    body = body_json()
    check_unknown(body, {"expected_publisher_account_version", "publisher_account_id",
                         "credential_type", "platform", "key_custody", "not_before",
                         "not_after", "linked_cert_id", "entitlements"})
    account, linked = resolve([
        ("publisher_account", body.get("publisher_account_id")),
        ("signing_credential", body.get("linked_cert_id")),
    ])
    expected = req_int(body, "expected_publisher_account_version")
    req_id(body, "publisher_account_id")
    credential_type = req_str(body, "credential_type", enum=CREDENTIAL_TYPES)
    platform = req_str(body, "platform", enum=PLATFORMS)
    key_custody = req_str(body, "key_custody", enum=CUSTODY)
    not_before = req_iso(body, "not_before")
    not_after = req_iso(body, "not_after")
    if not_after <= not_before:
        fail("ERR_VALIDATION", "not_after must be strictly later than not_before")
    if credential_type == "PROVISIONING_PROFILE":
        if linked is None:
            fail("ERR_VALIDATION",
                 "linked_cert_id is required for a PROVISIONING_PROFILE")
        if linked["credential_type"] != "DISTRIBUTION_CERT":
            fail("ERR_VALIDATION",
                 "linked_cert_id must reference a DISTRIBUTION_CERT")
    elif linked is not None:
        fail("ERR_VALIDATION",
             "linked_cert_id must be null for a DISTRIBUTION_CERT")
    entitlements = opt_array(body, "entitlements", member_enum=ENTITLEMENTS,
                             default=[])
    if expected != account["version"]:
        fail("ERR_STALE_PUBLISHER_ACCOUNT_VERSION",
             "expected_publisher_account_version does not match")
    if credential_type == "DISTRIBUTION_CERT" and key_custody == "LOCAL_KEYCHAIN":
        fail("ERR_KEY_CUSTODY_NOT_PERMITTED",
             "a distribution certificate may not be held in a local keychain")
    if linked is not None and linked["platform"] != platform:
        fail("ERR_CREDENTIAL_PLATFORM_MISMATCH",
             "profile platform differs from that of its linked certificate")
    row = new_row("signing_credential", {
        "publisher_account_id": account["id"],
        "credential_type": credential_type,
        "linked_cert_id": linked["id"] if linked is not None else None,
        "platform": platform,
        "key_custody": key_custody,
        "entitlements": entitlements,
        "not_before": fmt_iso(not_before),
        "not_after": fmt_iso(not_after),
        "status": "PENDING_ACTIVATION",
        "revocation_reason": None,
        "compromised_at": None,
        "blocked_submission_count": 0,
    })
    touch(account)
    return ok(public(row), 201)


@bp.route("/signing-credentials", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"])
def list_credentials():
    items = rows("signing_credential")
    for field in ("publisher_account_id", "linked_cert_id", "credential_type",
                  "platform", "status", "key_custody"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/signing-credentials/<credential_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"])
def read_credential(credential_id):
    (credential,) = resolve([("signing_credential", credential_id)])
    return ok(public(credential))


@bp.route("/signing-credentials/<credential_id>/activate", methods=["POST"])
@endpoint(["PublisherAdmin"])
def activate_credential(credential_id):
    (credential,) = resolve([("signing_credential", credential_id)])
    if credential["status"] != "PENDING_ACTIVATION":
        fail("ERR_INVALID_CREDENTIAL_STATE",
             "a %s credential cannot be activated" % credential["status"])
    account = get_row("publisher_account", credential["publisher_account_id"])
    flows.program_gate(account)
    now = now_dt()
    if not (parse_iso(credential["not_before"]) <= now
            < parse_iso(credential["not_after"])):
        fail("ERR_CREDENTIAL_NOT_YET_VALID",
             "the logical clock is outside the credential validity interval")
    if (credential["credential_type"] == "DISTRIBUTION_CERT"
            and credential["key_custody"] == "LOCAL_KEYCHAIN"):
        fail("ERR_KEY_CUSTODY_NOT_PERMITTED",
             "a distribution certificate may not be held in a local keychain")
    if credential["credential_type"] == "PROVISIONING_PROFILE":
        linked = get_row("signing_credential", credential.get("linked_cert_id"))
        if linked is None or linked["status"] != "ACTIVE":
            fail("ERR_LINKED_CERT_NOT_ACTIVE",
                 "the linked distribution certificate is not ACTIVE")
    credential["status"] = "ACTIVE"
    touch(credential)
    for other in rows("signing_credential"):
        if other["id"] == credential["id"]:
            continue
        if (other["publisher_account_id"] == credential["publisher_account_id"]
                and other["credential_type"] == credential["credential_type"]
                and other["platform"] == credential["platform"]
                and other["status"] in ("ACTIVE", "EXPIRING_SOON")):
            other["status"] = "REVOKED"
            other["revocation_reason"] = "SUPERSEDED"
            touch(other)
    flows.recompute_account_apps(account)
    return ok(public(credential))


@bp.route("/signing-credentials/<credential_id>/report-compromise", methods=["POST"])
@endpoint(["PublisherAdmin", "PlatformPolicyAdmin"])
def report_compromise(credential_id):
    (credential,) = resolve([("signing_credential", credential_id)])
    body = body_json()
    check_unknown(body, {"reason_code"})
    req_str(body, "reason_code", 1)
    if credential["status"] not in ("ACTIVE", "EXPIRING_SOON"):
        fail("ERR_INVALID_CREDENTIAL_STATE",
             "a %s credential cannot be reported compromised" % credential["status"])
    credential["status"] = "COMPROMISED"
    credential["compromised_at"] = now_iso()
    touch(credential)
    flows.compromise_cascade(credential)
    return ok(public(credential))


@bp.route("/signing-credentials/<credential_id>/revoke", methods=["POST"])
@endpoint(["PublisherAdmin"])
def revoke_credential(credential_id):
    (credential,) = resolve([("signing_credential", credential_id)])
    body = body_json()
    check_unknown(body, {"revocation_reason"})
    reason = opt_str(body, "revocation_reason", enum=REVOCATION_REASONS,
                     default="MANUAL")
    if credential["status"] not in ("ACTIVE", "COMPROMISED"):
        fail("ERR_INVALID_CREDENTIAL_STATE",
             "a %s credential cannot be revoked" % credential["status"])
    if credential["status"] == "ACTIVE":
        for submission in rows("submission"):
            if (submission.get("signing_credential_id") == credential["id"]
                    and submission["state"] in ("WAITING_FOR_REVIEW", "IN_REVIEW")):
                fail("ERR_CREDENTIAL_IN_USE",
                     "a submission signed with this credential is still in review")
    was_active = credential["status"] == "ACTIVE"
    credential["status"] = "REVOKED"
    credential["revocation_reason"] = reason or "MANUAL"
    touch(credential)
    if was_active:
        account = get_row("publisher_account", credential["publisher_account_id"])
        if account is not None:
            flows.recompute_account_apps(account)
    return ok(public(credential))


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def set_clock():
    body = body_json()
    check_unknown(body, {"current_utc"})
    target = req_iso(body, "current_utc")
    if target < parse_iso(CLOCK["current_utc"]):
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "the logical clock may never move backwards")
    counters = flows.clock_sweep(target)
    return ok({
        "current_utc": counters["current_utc"],
        "credentials_warned_count": counters["credentials_warned_count"],
        "credentials_expired_count": counters["credentials_expired_count"],
        "accounts_expired_count": counters["accounts_expired_count"],
        "assessments_overdue_count": counters["assessments_overdue_count"],
        "postures_frozen_count": counters["postures_frozen_count"],
        "rollouts_paused_count": counters["rollouts_paused_count"],
    })
