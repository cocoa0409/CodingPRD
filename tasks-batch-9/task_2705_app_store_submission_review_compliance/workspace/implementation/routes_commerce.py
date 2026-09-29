"""The commerce catalogue: shape policing, review and revenue reporting."""
from flask import Blueprint, g

import calc
import flows
from common import (arg_filter, body_json, endpoint, fail, get_row, new_row, ok,
                    paginate, public, resolve, rows, scope_rows, touch)
from valid import check_unknown, opt_int, opt_str, req_id, req_int, req_str

bp = Blueprint("commerce", __name__)

ITEM_TYPES = {"CONSUMABLE", "NON_CONSUMABLE", "SUBSCRIPTION",
              "EXTERNAL_PAYMENT_LINK"}
ENTITLEMENT_CLASSES = {"DIGITAL_CONTENT", "PHYSICAL_GOOD", "SERVICE"}
READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
              "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"]
DISTRIBUTED_STATES = ("PHASED_ROLLOUT", "FULLY_RELEASED", "PAUSED")


def _external_entitlement_present(app):
    """True when the account owns an ACTIVE cert bearing the link entitlement."""
    account_id = app["publisher_account_id"]
    for credential in calc.credentials_of_account(account_id):
        if (credential["credential_type"] == "DISTRIBUTION_CERT"
                and credential["status"] == "ACTIVE"
                and "EXTERNAL_PAYMENT_LINK" in (credential.get("entitlements") or [])):
            return True
    return False


@bp.route("/commerce-items", methods=["POST"])
@endpoint(["PublisherAdmin"])
def create_item():
    body = body_json()
    check_unknown(body, {"app_record_id", "item_type", "reference_name",
                         "price_tier_cents", "entitlement_class",
                         "external_link_url", "subscriber_retention_months"})
    (app,) = resolve([("app_record", body.get("app_record_id"))])
    req_id(body, "app_record_id")
    item_type = req_str(body, "item_type", enum=ITEM_TYPES)
    reference_name = req_str(body, "reference_name", 1, 120)
    price_tier_cents = req_int(body, "price_tier_cents", 0)
    entitlement_class = req_str(body, "entitlement_class",
                                enum=ENTITLEMENT_CLASSES)
    external_link_url = opt_str(body, "external_link_url", 1, 500)
    retention = opt_int(body, "subscriber_retention_months", 0, default=0,
                        nullable=False)
    if item_type == "EXTERNAL_PAYMENT_LINK":
        if external_link_url is None:
            fail("ERR_VALIDATION",
                 "external_link_url is required for an EXTERNAL_PAYMENT_LINK")
        if price_tier_cents != 0:
            fail("ERR_VALIDATION",
                 "price_tier_cents must be 0 for an EXTERNAL_PAYMENT_LINK")
    elif external_link_url is not None:
        fail("ERR_VALIDATION",
             "external_link_url must be null unless item_type is "
             "EXTERNAL_PAYMENT_LINK")
    for existing in rows("commerce_item"):
        if (existing["app_record_id"] == app["id"]
                and existing["reference_name"] == reference_name):
            fail("ERR_VALIDATION",
                 "reference_name is already used by this app record")
    flows.posture_gate(app)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    if (item_type == "EXTERNAL_PAYMENT_LINK"
            and entitlement_class == "DIGITAL_CONTENT"):
        fail("ERR_EXTERNAL_LINK_NOT_PERMITTED",
             "digital content may never be sold through an external link")
    row = new_row("commerce_item", {
        "app_record_id": app["id"],
        "item_type": item_type,
        "reference_name": reference_name,
        "price_tier_cents": price_tier_cents,
        "entitlement_class": entitlement_class,
        "external_link_url": external_link_url,
        "subscriber_retention_months": retention,
        "status": "DRAFT",
        "rejection_note": None,
        "reported_gross_cents": 0,
        "reported_period_label": None,
        "commission_rate_applied": None,
        "commission_cents": 0,
    })
    return ok(public(row), 201)


@bp.route("/commerce-items", methods=["GET"])
@endpoint(READ_ROLES)
def list_items():
    items = rows("commerce_item")
    for field in ("app_record_id", "item_type", "status", "entitlement_class",
                  "reported_period_label"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/commerce-items/<item_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_item(item_id):
    (item,) = resolve([("commerce_item", item_id)])
    return ok(public(item))


@bp.route("/commerce-items/<item_id>/submit", methods=["POST"])
@endpoint(["PublisherAdmin"])
def submit_item(item_id):
    (item,) = resolve([("commerce_item", item_id)])
    if item["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_COMMERCE_ITEM_STATE",
             "a %s commerce item cannot be submitted" % item["status"])
    app = get_row("app_record", item["app_record_id"])
    flows.posture_gate(app, release_advancing=True)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    if item["item_type"] == "EXTERNAL_PAYMENT_LINK":
        if item["entitlement_class"] == "DIGITAL_CONTENT":
            fail("ERR_EXTERNAL_LINK_NOT_PERMITTED",
                 "digital content may never be sold through an external link")
        if not item.get("external_link_url"):
            fail("ERR_VALIDATION",
                 "external_link_url is required for an EXTERNAL_PAYMENT_LINK")
        if item.get("price_tier_cents"):
            fail("ERR_VALIDATION",
                 "price_tier_cents must be 0 for an EXTERNAL_PAYMENT_LINK")
        if not _external_entitlement_present(app):
            fail("ERR_EXTERNAL_LINK_NOT_PERMITTED",
                 "no ACTIVE distribution certificate carries the "
                 "EXTERNAL_PAYMENT_LINK entitlement")
    elif item.get("external_link_url") is not None:
        fail("ERR_VALIDATION",
             "external_link_url must be null unless item_type is "
             "EXTERNAL_PAYMENT_LINK")
    item["status"] = "SUBMITTED"
    item["rejection_note"] = None
    touch(item)
    return ok(public(item))


@bp.route("/commerce-items/<item_id>/review", methods=["POST"])
@endpoint(["PlatformReviewer"])
def review_item(item_id):
    (item,) = resolve([("commerce_item", item_id)])
    body = body_json()
    check_unknown(body, {"outcome", "rejection_note"})
    outcome = req_str(body, "outcome", enum={"APPROVE", "REJECT"})
    rejection_note = opt_str(body, "rejection_note", 1, 1000)
    if item["status"] != "SUBMITTED":
        fail("ERR_INVALID_COMMERCE_ITEM_STATE",
             "a %s commerce item cannot be reviewed" % item["status"])
    app = get_row("app_record", item["app_record_id"])
    for mapping in calc.mappings_of_app(app["id"]):
        rule = get_row("guideline_rule", mapping["guideline_rule_id"])
        if rule is not None and rule["category"] == "COMMERCE":
            flows.sod_must_differ(mapping.get("attested_by_user_id"))
    account = calc.account_of_app(app)
    if outcome == "APPROVE":
        item["status"] = "APPROVED"
        calc.recompute_commission(item, account)
    else:
        if not rejection_note:
            fail("ERR_VALIDATION",
                 "a rejection_note is required when rejecting an item")
        item["status"] = "REJECTED"
        item["rejection_note"] = rejection_note
    touch(item)
    return ok(public(item))


@bp.route("/commerce-items/<item_id>/report-revenue", methods=["POST"])
@endpoint(["PublisherAdmin"])
def report_revenue(item_id):
    (item,) = resolve([("commerce_item", item_id)])
    body = body_json()
    check_unknown(body, {"reported_gross_cents", "period_label"})
    gross = req_int(body, "reported_gross_cents", 0)
    period_label = req_str(body, "period_label", 1, 40)
    if item["status"] != "APPROVED":
        fail("ERR_INVALID_COMMERCE_ITEM_STATE",
             "only an APPROVED commerce item may report revenue")
    app = get_row("app_record", item["app_record_id"])
    if app["distribution_state"] not in DISTRIBUTED_STATES:
        fail("ERR_APP_NOT_DISTRIBUTED",
             "an undistributed app cannot earn reportable revenue")
    account = calc.account_of_app(app)
    finalized = list(account.get("settlement_finalized_periods") or [])
    if item.get("reported_period_label") is not None or period_label in finalized:
        fail("ERR_REVENUE_ALREADY_REPORTED",
             "gross proceeds are stated exactly once per item and period")
    item["reported_gross_cents"] = gross
    item["reported_period_label"] = period_label
    calc.recompute_commission(item, account)
    touch(item)
    if period_label not in finalized:
        finalized.append(period_label)
        account["settlement_finalized_periods"] = finalized
        touch(account)
    return ok(public(item))
