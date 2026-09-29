"""Subscriber accounts and label disclosures (PRD §3.7)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (ALL_ROLES, COMPLAINT_ANALYST, COMPLIANCE_OFFICER,
                        REGULATORY_LIAISON, RETAIL_AGENT, SUBSCRIBER,
                        authorize, require_own_account)
from services import calculations as calc

bp = Blueprint("accounts", __name__)

ACCESSIBILITY_NEEDS = ("NONE", "SCREEN_READER", "LARGE_PRINT")
CHANNELS = ("POINT_OF_SALE", "ACCOUNT_PORTAL")
ACCESSIBLE_FORMATS = ("STANDARD_WEB", "SCREEN_READER", "LARGE_PRINT")

NEED_TO_FORMAT = {
    "SCREEN_READER": "SCREEN_READER",
    "LARGE_PRINT": "LARGE_PRINT",
}


@bp.route("/subscriber-accounts", methods=["POST"])
def create_subscriber_account():
    authorize(RETAIL_AGENT)
    body = validators.json_body()

    account_code = validators.get_str(body, "account_code", 1, 32)
    plan_ref = validators.get_id_ref(body, "plan_id")
    locale = validators.get_str(body, "preferred_locale", 2, 16)
    service_start = validators.get_datetime(body, "service_start_date")
    need = validators.get_enum(body, "accessibility_need", ACCESSIBILITY_NEEDS,
                               required=False, default="NONE")
    enrolled = validators.get_bool(body, "discount_program_enrolled",
                                   required=False, default=False)

    plan = lookup.service_plan(plan_ref)

    for existing in db.store.subscriber_accounts.values():
        if existing["account_code"] == account_code:
            validators.bad("Field 'account_code' is already in use.")

    account = db.new_record()
    account.update({
        "account_code": account_code,
        "plan_id": plan["id"],
        "preferred_locale": locale,
        "accessibility_need": need,
        "discount_program_enrolled": enrolled,
        "service_start_date": service_start,
        "subscription_state": "ACTIVE",
        "credit_balance_cents": 0,
        "remediation_count": 0,
        "audit_flag": False,
        "last_disclosed_label_version_id": None,
    })
    db.store.subscriber_accounts[account["id"]] = account
    return response.success(serializers.subscriber_account(account), 201)


@bp.route("/subscriber-accounts/<account_id>", methods=["GET"])
def read_subscriber_account(account_id):
    principal = authorize(*ALL_ROLES)
    account = lookup.subscriber_account(account_id)
    require_own_account(principal, account["id"])
    return response.success(serializers.subscriber_account(account), 200)


@bp.route("/subscriber-accounts", methods=["GET"])
def list_subscriber_accounts():
    authorize(COMPLIANCE_OFFICER, COMPLAINT_ANALYST, REGULATORY_LIAISON,
              RETAIL_AGENT)
    validators.pagination_params()
    plan_id = request.args.get("plan_id")
    state = request.args.get("subscription_state")
    rows = [a for a in db.store.subscriber_accounts.values()
            if (plan_id is None or a["plan_id"] == plan_id)
            and (state is None or a["subscription_state"] == state)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.subscriber_account)
    return response.success_list(items, meta, 200)


@bp.route("/subscriber-accounts/<account_id>/label-disclosures",
          methods=["POST"])
def create_label_disclosure(account_id):
    principal = authorize(RETAIL_AGENT, SUBSCRIBER)
    body = validators.json_body()
    channel = validators.get_enum(body, "channel", CHANNELS)
    locale = validators.get_str(body, "locale", 2, 16)
    accessible_format = validators.get_enum(body, "accessible_format",
                                            ACCESSIBLE_FORMATS)

    account = lookup.subscriber_account(account_id)
    require_own_account(principal, account["id"])

    plan = lookup.service_plan(account["plan_id"])

    # Step 9 — disclosure posture.
    posture = plan["label_posture"]
    if posture == "FROZEN":
        fail(errors.ERR_PLAN_POSTURE_FROZEN)
    if posture == "RESTRICTED" and channel == "POINT_OF_SALE":
        fail(errors.ERR_PLAN_POSTURE_RESTRICTED)

    # Step 10 — accessibility accommodation.
    required_format = NEED_TO_FORMAT.get(account["accessibility_need"])
    if required_format is not None and accessible_format != required_format:
        fail(errors.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED)

    # Step 15 — label selection, then the format/conformance rule that needs it.
    label = calc.select_effective_label(plan["id"])
    if label is None:
        fail(errors.ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE)
    if (accessible_format != "STANDARD_WEB"
            and label["accessibility_conformance"] != "WCAG_AA"):
        fail(errors.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED)

    verified = False
    for translation in db.store.label_translations.values():
        if (translation["label_version_id"] == label["id"]
                and translation["locale"] == locale
                and translation["status"] == "VERIFIED"):
            verified = True
            break
    if not verified:
        fail(errors.ERR_TRANSLATION_NOT_AVAILABLE)

    phase = calc.account_pricing_phase(account)
    if phase == "INTRO":
        disclosed_net = label["net_monthly_intro_cents"]
    else:
        disclosed_net = label["net_monthly_post_promo_cents"]

    disclosure = db.new_record(common_fields=False)
    disclosure.update({
        "account_id": account["id"],
        "label_version_id": label["id"],
        "channel": channel,
        "locale": locale,
        "accessible_format": accessible_format,
        "disclosed_label_version_seq": label["version_seq"],
        "disclosed_net_monthly_cents": disclosed_net,
        "disclosed_by_user_id": principal.user_id,
    })
    db.store.label_disclosures[disclosure["id"]] = disclosure

    account["last_disclosed_label_version_id"] = label["id"]
    db.touch(account)

    return response.success(serializers.label_disclosure(disclosure), 201)


@bp.route("/subscriber-accounts/<account_id>/label-disclosures",
          methods=["GET"])
def list_account_disclosures(account_id):
    principal = authorize(COMPLIANCE_OFFICER, COMPLAINT_ANALYST,
                          REGULATORY_LIAISON, RETAIL_AGENT, SUBSCRIBER)
    validators.pagination_params()
    account = lookup.subscriber_account(account_id)
    require_own_account(principal, account["id"])

    channel = request.args.get("channel")
    rows = [d for d in db.store.label_disclosures.values()
            if d["account_id"] == account["id"]
            and (channel is None or d["channel"] == channel)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.label_disclosure)
    return response.success_list(items, meta, 200)
