"""Online Will & Estate Planning API — Flask entrypoint with all 37 routes."""
import os

from flask import Flask, request

import core
from core import (
    db, clock, ApiError,
    authenticate, require_ownership,
    get_body, require, as_str, as_enum, as_int, as_bool, as_state_code, as_pct,
    parse_iso, add_common, touch,
    respond, respond_entity, respond_list, error_response, paginate,
    signup_price, renewal_final_charge, witness_requirement, cancel_refund,
    gross_estate_value, recompute_estate_distribution, period_overlap,
    PLAN_TIERS, DOC_TYPES, BUNDLE_TYPES, RELATIONSHIPS, ASSET_TYPES,
    FUNDING_STATUSES, SCOPES, PAYMENT_OUTCOMES, REVIEW_ACTIONS, EXECUTOR_DECISIONS,
    REQUIRED_FIELDS, ATTORNEY_ADDON_CENTS, BUNDLE_MULTIPLIER,
    TERM_DAYS, RENEWAL_WINDOW_DAYS, GRACE_DAYS,
    NON_TERMINAL_SUB, TERMINAL_SUB, NON_TERMINAL_DOC, TERMINAL_DOC, NON_TERMINAL_REVIEW,
)
from datetime import timedelta
from decimal import Decimal

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_VALIDATION", "route not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_VALIDATION", "method not allowed"))


# =====================================================================
# Fetch helpers (raise proper not-found)
# =====================================================================
def fetch(store, ident, err_id):
    ent = store.get(ident)
    if ent is None:
        raise ApiError(err_id, "resource not found")
    return ent


def get_member(i):
    return fetch(db.members, i, "ERR_MEMBER_NOT_FOUND")


def get_subscription(i):
    return fetch(db.subscriptions, i, "ERR_SUBSCRIPTION_NOT_FOUND")


def get_questionnaire(i):
    return fetch(db.questionnaires, i, "ERR_QUESTIONNAIRE_NOT_FOUND")


def get_document(i):
    return fetch(db.documents, i, "ERR_DOCUMENT_NOT_FOUND")


def get_beneficiary(i):
    return fetch(db.beneficiaries, i, "ERR_BENEFICIARY_NOT_FOUND")


def get_asset(i):
    return fetch(db.assets, i, "ERR_ASSET_NOT_FOUND")


def get_executor(i):
    return fetch(db.executors, i, "ERR_EXECUTOR_NOT_FOUND")


def get_review(i):
    return fetch(db.attorney_reviews, i, "ERR_REVIEW_NOT_FOUND")


def get_share_grant(i):
    return fetch(db.share_grants, i, "ERR_SHARE_GRANT_NOT_FOUND")


def sub_owner(sub):
    return sub["member_id"]


def doc_owner(doc):
    return db.subscriptions[doc["subscription_id"]]["member_id"]


# =====================================================================
# Cascade helpers
# =====================================================================
def close_reviews_for_document(document_id):
    for r in db.attorney_reviews.values():
        if r["document_id"] == document_id and r["status"] in NON_TERMINAL_REVIEW:
            r["status"] = "CLOSED"
            touch(r)


def revoke_grants_for_document(document_id):
    for g in db.share_grants.values():
        if g["document_id"] == document_id and g["status"] == "ACTIVE":
            g["status"] = "REVOKED"
            touch(g)


# =====================================================================
# PlatformAdmin utilities
# =====================================================================
@app.route("/v1/plan-catalog", methods=["POST"])
def create_plan_catalog():
    authenticate({"PlatformAdmin"})
    body = get_body()
    plan_tier = as_enum(require(body, "plan_tier"), "plan_tier", PLAN_TIERS)
    base_price_cents = as_int(require(body, "base_price_cents"), "base_price_cents", minimum=0)
    included = require(body, "included_document_types")
    if not isinstance(included, list) or not included or any(x not in DOC_TYPES for x in included):
        raise ApiError("ERR_VALIDATION", "included_document_types must be a non-empty subset of document types")
    max_documents = as_int(require(body, "max_documents"), "max_documents", minimum=1)
    allows_trust = as_bool(require(body, "allows_trust"), "allows_trust")
    if any(p["plan_tier"] == plan_tier for p in db.plan_catalog.values()):
        raise ApiError("ERR_VALIDATION", "plan_tier already exists in catalog")
    ent = {
        "plan_tier": plan_tier,
        "base_price_cents": base_price_cents,
        "included_document_types": list(included),
        "max_documents": max_documents,
        "allows_trust": allows_trust,
    }
    add_common(ent, versioned=False)
    db.plan_catalog[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_body()
    to_iso = require(body, "to_iso8601")
    clock.set(parse_iso(to_iso))
    return respond({}, status=200, response_type="object")


@app.route("/v1/_payments/simulate", methods=["POST"])
def simulate_payment():
    authenticate({"PlatformAdmin"})
    body = get_body()
    subscription_id = as_str(require(body, "subscription_id"), "subscription_id")
    outcome = as_enum(require(body, "outcome"), "outcome", PAYMENT_OUTCOMES)
    sub = get_subscription(subscription_id)
    status = sub["status"]
    now = clock.now()

    def settle_renewal():
        new_count = sub["renewal_count"] + 1
        final = renewal_final_charge(sub["pending_charge_cents"], new_count)
        new_start = sub["current_period_end"]
        new_end = new_start + timedelta(days=TERM_DAYS)
        if period_overlap(sub["member_id"], sub["id"], new_start, new_end):
            raise ApiError("ERR_SUBSCRIPTION_PERIOD_OVERLAP", "renewal window overlaps another subscription")
        sub["renewal_count"] = new_count
        sub["paid_to_date_cents"] += final
        sub["current_period_start"] = new_start
        sub["current_period_end"] = new_end
        sub["renewal_pending"] = False
        sub["pending_charge_cents"] = 0
        sub["status"] = "ACTIVE"

    if status == "PENDING_PAYMENT":
        if outcome == "SUCCEEDED":
            new_start = now
            new_end = now + timedelta(days=TERM_DAYS)
            if period_overlap(sub["member_id"], sub["id"], new_start, new_end):
                raise ApiError("ERR_SUBSCRIPTION_PERIOD_OVERLAP", "coverage window overlaps another subscription")
            sub["current_period_start"] = new_start
            sub["current_period_end"] = new_end
            sub["paid_to_date_cents"] += sub["pending_charge_cents"]
            sub["pending_charge_cents"] = 0
            sub["status"] = "ACTIVE"
        else:  # FAILED
            sub["pending_charge_cents"] = 0
            sub["status"] = "EXPIRED"
        touch(sub)
        return respond_entity(sub, status=200)

    if status == "ACTIVE" and sub["renewal_pending"]:
        if outcome == "SUCCEEDED":
            settle_renewal()
        else:  # FAILED renewal settlement
            sub["status"] = "SUSPENDED"
        touch(sub)
        return respond_entity(sub, status=200)

    if status == "SUSPENDED" and sub["renewal_pending"]:
        within_grace = now <= sub["current_period_end"] + timedelta(days=GRACE_DAYS)
        if outcome == "SUCCEEDED" and within_grace:
            settle_renewal()
            touch(sub)
            return respond_entity(sub, status=200)
        if outcome == "FAILED" and not within_grace:
            sub["pending_charge_cents"] = 0
            sub["status"] = "EXPIRED"
            touch(sub)
            return respond_entity(sub, status=200)
        raise ApiError("ERR_PAYMENT_ALREADY_SETTLED", "no compatible outstanding charge to settle")

    # ACTIVE without renewal_pending, terminal states, etc.
    raise ApiError("ERR_PAYMENT_ALREADY_SETTLED", "subscription has no outstanding charge")


# =====================================================================
# Members
# =====================================================================
@app.route("/v1/members", methods=["POST"])
def create_member():
    body = get_body()
    email = as_str(require(body, "email"), "email")
    full_name = as_str(require(body, "full_name"), "full_name")
    state_code = as_state_code(require(body, "state_code"), "state_code")
    if any(m["email"] == email for m in db.members.values()):
        raise ApiError("ERR_VALIDATION", "email already registered")
    ent = {"email": email, "full_name": full_name, "state_code": state_code}
    add_common(ent)
    db.members[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/members/<mid>", methods=["GET"])
def get_member_route(mid):
    _uid, role = authenticate({"Member", "PlatformAdmin"})
    member = get_member(mid)
    require_ownership(role, _uid, member["id"])
    return respond_entity(member, status=200)


@app.route("/v1/members/<mid>/subscriptions", methods=["GET"])
def list_member_subscriptions(mid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    member = get_member(mid)
    require_ownership(role, uid, member["id"])
    items = [s for s in db.subscriptions.values() if s["member_id"] == mid]
    page, meta = paginate(items)
    return respond_list(page, meta)


# =====================================================================
# Subscriptions
# =====================================================================
@app.route("/v1/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = authenticate({"Member"})
    body = get_body()
    member_id = as_str(require(body, "member_id"), "member_id")
    plan_tier = as_enum(require(body, "plan_tier"), "plan_tier", PLAN_TIERS)
    bundle_type = body.get("bundle_type", "INDIVIDUAL")
    if bundle_type is None:
        bundle_type = "INDIVIDUAL"
    bundle_type = as_enum(bundle_type, "bundle_type", BUNDLE_TYPES)
    attorney_support = body.get("attorney_support", False)
    if attorney_support is None:
        attorney_support = False
    attorney_support = as_bool(attorney_support, "attorney_support")
    spouse_name = body.get("spouse_name")
    spouse_email = body.get("spouse_email")

    require_ownership(role, uid, member_id)

    if bundle_type == "COUPLE" and (spouse_name is None or spouse_name == ""):
        raise ApiError("ERR_VALIDATION", "spouse_name is required for a COUPLE bundle")

    plan = next((p for p in db.plan_catalog.values() if p["plan_tier"] == plan_tier), None)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "plan_tier is not in the catalog")

    price = signup_price(plan, attorney_support, bundle_type)
    ent = {
        "member_id": member_id,
        "plan_tier": plan_tier,
        "bundle_type": bundle_type,
        "spouse_name": spouse_name,
        "spouse_email": spouse_email,
        "attorney_support": attorney_support,
        "status": "PENDING_PAYMENT",
        "price_cents": price,
        "pending_charge_cents": price,
        "paid_to_date_cents": 0,
        "refunded_cents": 0,
        "current_period_start": None,
        "current_period_end": None,
        "renewal_count": 0,
        "renewal_pending": False,
    }
    add_common(ent)
    db.subscriptions[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/subscriptions/<sid>", methods=["GET"])
def get_subscription_route(sid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    sub = get_subscription(sid)
    require_ownership(role, uid, sub_owner(sub))
    return respond_entity(sub, status=200)


@app.route("/v1/subscriptions/<sid>/change-plan", methods=["POST"])
def change_plan(sid):
    uid, role = authenticate({"Member"})
    sub = get_subscription(sid)
    require_ownership(role, uid, sub_owner(sub))
    body = get_body()
    new_plan_tier = as_enum(require(body, "new_plan_tier"), "new_plan_tier", PLAN_TIERS)
    expected_version = as_int(require(body, "expected_subscription_version"), "expected_subscription_version")

    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "plan can only be changed on an ACTIVE subscription")
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_subscription_version does not match current version")
    plan = next((p for p in db.plan_catalog.values() if p["plan_tier"] == new_plan_tier), None)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "new_plan_tier is not in the catalog")

    sub["plan_tier"] = new_plan_tier
    sub["price_cents"] = signup_price(plan, sub["attorney_support"], sub["bundle_type"])
    touch(sub)
    return respond_entity(sub, status=200)


@app.route("/v1/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authenticate({"Member"})
    sub = get_subscription(sid)
    require_ownership(role, uid, sub_owner(sub))

    if sub["status"] in TERMINAL_SUB:
        raise ApiError("ERR_ALREADY_TERMINAL", "subscription is already terminal")

    prior_status = sub["status"]
    if prior_status == "PENDING_PAYMENT":
        sub["pending_charge_cents"] = 0
        sub["status"] = "CANCELLED"
        touch(sub)
        return respond_entity(sub, status=200)

    # ACTIVE or SUSPENDED
    refund = cancel_refund(sub)
    sub["refunded_cents"] += refund
    sub["paid_to_date_cents"] -= refund
    sub["status"] = "CANCELLED"
    touch(sub)

    # Cascade chain-1: revoke non-terminal documents -> their grants + reviews
    for doc in db.documents.values():
        if doc["subscription_id"] == sid and doc["status"] in NON_TERMINAL_DOC:
            doc["status"] = "REVOKED"
            touch(doc)
            revoke_grants_for_document(doc["id"])
            close_reviews_for_document(doc["id"])
    # Cascade: revoke NOMINATED / ACCEPTED executors
    for ex in db.executors.values():
        if ex["subscription_id"] == sid and ex["status"] in ("NOMINATED", "ACCEPTED"):
            ex["status"] = "REVOKED"
            touch(ex)

    return respond_entity(sub, status=200)


@app.route("/v1/subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    uid, role = authenticate({"Member"})
    sub = get_subscription(sid)
    require_ownership(role, uid, sub_owner(sub))

    if sub["status"] != "ACTIVE" or sub["renewal_pending"]:
        raise ApiError("ERR_INVALID_STATE", "renewal requires an ACTIVE subscription with no pending renewal")

    now = clock.now()
    end = sub["current_period_end"]
    if now < end - timedelta(days=RENEWAL_WINDOW_DAYS):
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", "renewal window has not opened yet")
    if now > end + timedelta(days=GRACE_DAYS):
        raise ApiError("ERR_RENEWAL_TOO_LATE", "renewal grace period has elapsed")

    plan = next((p for p in db.plan_catalog.values() if p["plan_tier"] == sub["plan_tier"]), None)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "current plan tier missing from catalog")
    quote = signup_price(plan, sub["attorney_support"], sub["bundle_type"])
    sub["renewal_pending"] = True
    sub["pending_charge_cents"] = quote
    touch(sub)
    return respond_entity(sub, status=200)


def _sub_read(sid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    sub = get_subscription(sid)
    require_ownership(role, uid, sub_owner(sub))
    return sub


@app.route("/v1/subscriptions/<sid>/questionnaires", methods=["GET"])
def list_sub_questionnaires(sid):
    _sub_read(sid)
    items = [q for q in db.questionnaires.values() if q["subscription_id"] == sid]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/subscriptions/<sid>/documents", methods=["GET"])
def list_sub_documents(sid):
    _sub_read(sid)
    items = [d for d in db.documents.values() if d["subscription_id"] == sid]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/subscriptions/<sid>/beneficiaries", methods=["GET"])
def list_sub_beneficiaries(sid):
    _sub_read(sid)
    items = [b for b in db.beneficiaries.values() if b["subscription_id"] == sid]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/subscriptions/<sid>/assets", methods=["GET"])
def list_sub_assets(sid):
    _sub_read(sid)
    items = [a for a in db.assets.values() if a["subscription_id"] == sid]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/subscriptions/<sid>/executors", methods=["GET"])
def list_sub_executors(sid):
    _sub_read(sid)
    items = [e for e in db.executors.values() if e["subscription_id"] == sid]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/subscriptions/<sid>/estate-summary", methods=["GET"])
def estate_summary(sid):
    _sub_read(sid)
    assets = [a for a in db.assets.values() if a["subscription_id"] == sid]
    gross = sum(a["estimated_value_cents"] for a in assets)
    net = sum(
        a["estimated_value_cents"]
        for a in assets
        if a["funding_status"] != "FUNDED" and a["assigned_beneficiary_id"] is None
    )
    assigned = sum(
        a["estimated_value_cents"] for a in assets if a["assigned_beneficiary_id"] is not None
    )
    bens = [b for b in db.beneficiaries.values() if b["subscription_id"] == sid]
    total_allocated = sum(b["allocated_cents"] for b in bens)
    primary_count = sum(1 for b in bens if not b["is_contingent"])
    data = {
        "gross_estate_value_cents": gross,
        "net_probate_estate_cents": net,
        "total_assigned_value_cents": assigned,
        "total_allocated_cents": total_allocated,
        "primary_beneficiary_count": primary_count,
    }
    return respond(data, status=200, response_type="object")


# =====================================================================
# Questionnaires
# =====================================================================
def _completeness(document_type, answers):
    required = REQUIRED_FIELDS[document_type]
    answered = min(required, len(answers))
    pct = (Decimal(answered) / Decimal(required) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=core.ROUND_HALF_UP
    )
    return answered, float(pct)


@app.route("/v1/questionnaires", methods=["POST"])
def create_questionnaire():
    uid, role = authenticate({"Member"})
    body = get_body()
    subscription_id = as_str(require(body, "subscription_id"), "subscription_id")
    document_type = as_enum(require(body, "document_type"), "document_type", DOC_TYPES)
    state_code = as_state_code(require(body, "state_code"), "state_code")
    sub = get_subscription(subscription_id)
    require_ownership(role, uid, sub_owner(sub))

    required = REQUIRED_FIELDS[document_type]
    ent = {
        "subscription_id": subscription_id,
        "document_type": document_type,
        "state_code": state_code,
        "answers": {},
        "required_field_count": required,
        "answered_field_count": 0,
        "completeness_pct": 0.0,
        "status": "IN_PROGRESS",
    }
    add_common(ent)
    db.questionnaires[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/questionnaires/<qid>", methods=["GET"])
def get_questionnaire_route(qid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    q = get_questionnaire(qid)
    require_ownership(role, uid, db.subscriptions[q["subscription_id"]]["member_id"])
    return respond_entity(q, status=200)


@app.route("/v1/questionnaires/<qid>/answers", methods=["POST"])
def submit_answers(qid):
    uid, role = authenticate({"Member"})
    q = get_questionnaire(qid)
    require_ownership(role, uid, db.subscriptions[q["subscription_id"]]["member_id"])
    body = get_body()
    answers = require(body, "answers")
    if not isinstance(answers, dict):
        raise ApiError("ERR_VALIDATION", "answers must be an object")

    if q["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "answers can only be submitted while IN_PROGRESS")

    merged = dict(q["answers"])
    merged.update(answers)
    q["answers"] = merged
    answered, pct = _completeness(q["document_type"], merged)
    q["answered_field_count"] = answered
    q["completeness_pct"] = pct
    if pct == 100:
        q["status"] = "COMPLETED"
    touch(q)
    return respond_entity(q, status=200)


@app.route("/v1/questionnaires/<qid>/documents", methods=["GET"])
def list_questionnaire_documents(qid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    q = get_questionnaire(qid)
    require_ownership(role, uid, db.subscriptions[q["subscription_id"]]["member_id"])
    items = [d for d in db.documents.values() if d["questionnaire_id"] == qid]
    page, meta = paginate(items)
    return respond_list(page, meta)


# =====================================================================
# Documents
# =====================================================================
@app.route("/v1/documents", methods=["POST"])
def create_document():
    uid, role = authenticate({"Member"})
    body = get_body()
    questionnaire_id = as_str(require(body, "questionnaire_id"), "questionnaire_id")
    q = get_questionnaire(questionnaire_id)
    sub = db.subscriptions[q["subscription_id"]]
    require_ownership(role, uid, sub["member_id"])

    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", "subscription must be ACTIVE to generate a document")
    if q["status"] != "COMPLETED" or q["completeness_pct"] != 100:
        raise ApiError("ERR_QUESTIONNAIRE_INCOMPLETE", "questionnaire must be COMPLETED")

    plan = next((p for p in db.plan_catalog.values() if p["plan_tier"] == sub["plan_tier"]), None)
    document_type = q["document_type"]
    if plan is None or document_type not in plan["included_document_types"] or (
        document_type == "TRUST" and not plan["allows_trust"]
    ):
        raise ApiError("ERR_DOCUMENT_TYPE_NOT_IN_PLAN", "document_type not permitted by the plan")

    non_revoked = sum(
        1 for d in db.documents.values()
        if d["subscription_id"] == sub["id"] and d["status"] != "REVOKED"
    )
    if non_revoked >= plan["max_documents"]:
        raise ApiError("ERR_DOCUMENT_QUOTA_EXCEEDED", "document quota reached for this plan")

    prior_same_type = sum(
        1 for d in db.documents.values()
        if d["subscription_id"] == sub["id"] and d["document_type"] == document_type
    )
    doc_version = prior_same_type + 1
    witness_req, requires_notary = witness_requirement(document_type, q["state_code"])
    ent = {
        "subscription_id": sub["id"],
        "questionnaire_id": questionnaire_id,
        "document_type": document_type,
        "state_code": q["state_code"],
        "status": "GENERATED",
        "doc_version": doc_version,
        "requires_notary": requires_notary,
        "witness_count_required": witness_req,
        "witnesses_count": 0,
        "execution_date": None,
        "superseded_by_id": None,
    }
    add_common(ent)
    db.documents[ent["id"]] = ent

    # Lock the source questionnaire.
    q["status"] = "LOCKED"
    touch(q)
    return respond_entity(ent, status=201)


@app.route("/v1/documents/<did>", methods=["GET"])
def get_document_route(did):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    doc = get_document(did)
    require_ownership(role, uid, doc_owner(doc))
    return respond_entity(doc, status=200)


@app.route("/v1/documents/<did>/submit-review", methods=["POST"])
def submit_review(did):
    uid, role = authenticate({"Member"})
    doc = get_document(did)
    require_ownership(role, uid, doc_owner(doc))

    if doc["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE", "only a GENERATED document can be submitted for review")
    sub = db.subscriptions[doc["subscription_id"]]
    if not sub["attorney_support"]:
        raise ApiError("ERR_ATTORNEY_SUPPORT_NOT_ENABLED", "attorney_support add-on is not enabled")

    # Reuse a CHANGES_REQUESTED review; otherwise create a new one if no non-terminal review exists.
    changes = None
    non_terminal = None
    for r in db.attorney_reviews.values():
        if r["document_id"] == did:
            if r["status"] == "CHANGES_REQUESTED":
                changes = r
            if r["status"] in NON_TERMINAL_REVIEW:
                non_terminal = r
    if changes is None and non_terminal is None:
        review = {
            "document_id": did,
            "attorney_user_id": None,
            "status": "REQUESTED",
            "notes": None,
        }
        add_common(review)
        db.attorney_reviews[review["id"]] = review

    doc["status"] = "IN_REVIEW"
    touch(doc)
    return respond_entity(doc, status=200)


@app.route("/v1/documents/<did>/execute", methods=["POST"])
def execute_document(did):
    authenticate({"Notary"})
    doc = get_document(did)
    body = get_body()
    witnesses_count = as_int(require(body, "witnesses_count"), "witnesses_count", minimum=0)

    if doc["status"] in TERMINAL_DOC:
        raise ApiError("ERR_ALREADY_TERMINAL", "document is already terminal")
    if doc["status"] not in ("GENERATED", "PENDING_EXECUTION"):
        raise ApiError("ERR_INVALID_STATE", "document is not in an executable state")

    sub = db.subscriptions[doc["subscription_id"]]
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", "owning subscription must be ACTIVE")

    if witnesses_count < doc["witness_count_required"]:
        raise ApiError("ERR_WITNESS_REQUIREMENT_NOT_MET", "not enough witnesses for execution")

    if doc["document_type"] == "WILL":
        has_primary = any(
            b["subscription_id"] == sub["id"] and not b["is_contingent"]
            for b in db.beneficiaries.values()
        )
        if not has_primary:
            raise ApiError("ERR_NO_BENEFICIARIES", "executing a WILL requires a non-contingent beneficiary")

    doc["status"] = "EXECUTED"
    doc["witnesses_count"] = witnesses_count
    doc["execution_date"] = clock.now()
    touch(doc)

    # Cascade chain-2: supersede prior EXECUTED docs of same subscription + type.
    for prior in list(db.documents.values()):
        if (
            prior["id"] != doc["id"]
            and prior["subscription_id"] == sub["id"]
            and prior["document_type"] == doc["document_type"]
            and prior["status"] == "EXECUTED"
        ):
            prior["status"] = "SUPERSEDED"
            prior["superseded_by_id"] = doc["id"]
            touch(prior)
            revoke_grants_for_document(prior["id"])
            close_reviews_for_document(prior["id"])

    return respond_entity(doc, status=200)


@app.route("/v1/documents/<did>/share-grants", methods=["GET"])
def list_document_share_grants(did):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    doc = get_document(did)
    require_ownership(role, uid, doc_owner(doc))
    items = [g for g in db.share_grants.values() if g["document_id"] == did]
    page, meta = paginate(items)
    return respond_list(page, meta)


@app.route("/v1/documents/<did>/attorney-reviews", methods=["GET"])
def list_document_reviews(did):
    uid, role = authenticate({"Member", "Attorney", "PlatformAdmin"})
    doc = get_document(did)
    require_ownership(role, uid, doc_owner(doc))
    items = [r for r in db.attorney_reviews.values() if r["document_id"] == did]
    page, meta = paginate(items)
    return respond_list(page, meta)


# =====================================================================
# Attorney reviews
# =====================================================================
@app.route("/v1/attorney-reviews/<rid>/decision", methods=["POST"])
def review_decision(rid):
    uid, _role = authenticate({"Attorney"})
    review = get_review(rid)
    body = get_body()
    action = as_enum(require(body, "action"), "action", REVIEW_ACTIONS)
    notes = body.get("notes")
    doc = db.documents.get(review["document_id"])

    if review["status"] in ("APPROVED", "CLOSED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "review is already terminal")

    if action == "START_REVIEW":
        if review["status"] == "REQUESTED":
            review["status"] = "IN_REVIEW"
            review["attorney_user_id"] = uid
            touch(review)
        elif review["status"] == "CHANGES_REQUESTED":
            if doc is None or doc["status"] != "IN_REVIEW":
                raise ApiError("ERR_INVALID_STATE", "document must be re-submitted before re-review")
            review["status"] = "IN_REVIEW"
            touch(review)
        else:
            raise ApiError("ERR_INVALID_STATE", "cannot start review from current state")
    elif action == "REQUEST_CHANGES":
        if review["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "changes can only be requested from IN_REVIEW")
        review["status"] = "CHANGES_REQUESTED"
        review["notes"] = notes
        touch(review)
        if doc is not None and doc["status"] == "IN_REVIEW":
            doc["status"] = "GENERATED"
            touch(doc)
    else:  # APPROVE
        if review["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "approval requires an IN_REVIEW review")
        review["status"] = "APPROVED"
        touch(review)
        if doc is not None and doc["status"] == "IN_REVIEW":
            doc["status"] = "PENDING_EXECUTION"
            touch(doc)

    return respond_entity(review, status=200)


# =====================================================================
# Beneficiaries
# =====================================================================
@app.route("/v1/beneficiaries", methods=["POST"])
def create_beneficiary():
    uid, role = authenticate({"Member"})
    body = get_body()
    subscription_id = as_str(require(body, "subscription_id"), "subscription_id")
    full_name = as_str(require(body, "full_name"), "full_name")
    relationship = as_enum(require(body, "relationship"), "relationship", RELATIONSHIPS)
    allocation_pct = as_pct(require(body, "allocation_pct"), "allocation_pct")
    is_contingent = body.get("is_contingent", False)
    if is_contingent is None:
        is_contingent = False
    is_contingent = as_bool(is_contingent, "is_contingent")

    sub = get_subscription(subscription_id)
    require_ownership(role, uid, sub_owner(sub))

    if not is_contingent:
        existing = sum(
            b["allocation_pct"]
            for b in db.beneficiaries.values()
            if b["subscription_id"] == subscription_id and not b["is_contingent"]
        )
        if existing + allocation_pct > Decimal("100"):
            raise ApiError("ERR_ALLOCATION_EXCEEDED", "non-contingent allocation would exceed 100.00%")

    ent = {
        "subscription_id": subscription_id,
        "full_name": full_name,
        "relationship": relationship,
        "allocation_pct": allocation_pct,
        "is_contingent": is_contingent,
        "allocated_cents": 0,
    }
    add_common(ent)
    db.beneficiaries[ent["id"]] = ent
    recompute_estate_distribution(subscription_id)
    return respond_entity(ent, status=201)


@app.route("/v1/beneficiaries/<bid>", methods=["GET"])
def get_beneficiary_route(bid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    ben = get_beneficiary(bid)
    require_ownership(role, uid, db.subscriptions[ben["subscription_id"]]["member_id"])
    return respond_entity(ben, status=200)


@app.route("/v1/beneficiaries/<bid>/assets", methods=["GET"])
def list_beneficiary_assets(bid):
    uid, role = authenticate({"Member", "PlatformAdmin"})
    ben = get_beneficiary(bid)
    require_ownership(role, uid, db.subscriptions[ben["subscription_id"]]["member_id"])
    items = [a for a in db.assets.values() if a["assigned_beneficiary_id"] == bid]
    page, meta = paginate(items)
    return respond_list(page, meta)


# =====================================================================
# Assets
# =====================================================================
@app.route("/v1/assets", methods=["POST"])
def create_asset():
    uid, role = authenticate({"Member"})
    body = get_body()
    subscription_id = as_str(require(body, "subscription_id"), "subscription_id")
    asset_type = as_enum(require(body, "asset_type"), "asset_type", ASSET_TYPES)
    description = as_str(require(body, "description"), "description")
    estimated_value_cents = as_int(require(body, "estimated_value_cents"), "estimated_value_cents", minimum=0)
    funding_status = body.get("funding_status", "UNFUNDED")
    if funding_status is None:
        funding_status = "UNFUNDED"
    funding_status = as_enum(funding_status, "funding_status", FUNDING_STATUSES)
    assigned_beneficiary_id = body.get("assigned_beneficiary_id")

    sub = get_subscription(subscription_id)
    require_ownership(role, uid, sub_owner(sub))

    if assigned_beneficiary_id is not None:
        ben = db.beneficiaries.get(assigned_beneficiary_id)
        if ben is None or ben["subscription_id"] != subscription_id:
            raise ApiError("ERR_BENEFICIARY_NOT_FOUND", "assigned_beneficiary_id does not reference a beneficiary of this subscription")

    ent = {
        "subscription_id": subscription_id,
        "asset_type": asset_type,
        "description": description,
        "estimated_value_cents": estimated_value_cents,
        "funding_status": funding_status,
        "assigned_beneficiary_id": assigned_beneficiary_id,
    }
    add_common(ent)
    db.assets[ent["id"]] = ent
    recompute_estate_distribution(subscription_id)
    return respond_entity(ent, status=201)


@app.route("/v1/assets/<aid>/assign-beneficiary", methods=["POST"])
def assign_beneficiary(aid):
    uid, role = authenticate({"Member"})
    asset = get_asset(aid)
    require_ownership(role, uid, db.subscriptions[asset["subscription_id"]]["member_id"])
    body = get_body()
    beneficiary_id = as_str(require(body, "beneficiary_id"), "beneficiary_id")

    ben = db.beneficiaries.get(beneficiary_id)
    if ben is None or ben["subscription_id"] != asset["subscription_id"]:
        raise ApiError("ERR_BENEFICIARY_NOT_FOUND", "beneficiary does not belong to this subscription")
    if asset["funding_status"] == "FUNDED":
        raise ApiError("ERR_ASSET_ALREADY_FUNDED", "a funded asset cannot carry a probate earmark")

    asset["assigned_beneficiary_id"] = beneficiary_id
    touch(asset)
    recompute_estate_distribution(asset["subscription_id"])
    return respond_entity(asset, status=200)


# =====================================================================
# Executors
# =====================================================================
@app.route("/v1/executors", methods=["POST"])
def create_executor():
    uid, role = authenticate({"Member"})
    body = get_body()
    subscription_id = as_str(require(body, "subscription_id"), "subscription_id")
    full_name = as_str(require(body, "full_name"), "full_name")
    email = as_str(require(body, "email"), "email")
    priority_order = as_int(require(body, "priority_order"), "priority_order", minimum=1)

    sub = get_subscription(subscription_id)
    require_ownership(role, uid, sub_owner(sub))

    if any(
        e["subscription_id"] == subscription_id and e["priority_order"] == priority_order
        for e in db.executors.values()
    ):
        raise ApiError("ERR_VALIDATION", "priority_order must be unique per subscription")

    ent = {
        "subscription_id": subscription_id,
        "full_name": full_name,
        "email": email,
        "priority_order": priority_order,
        "status": "NOMINATED",
    }
    add_common(ent)
    db.executors[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/executors/<eid>/respond", methods=["POST"])
def respond_executor(eid):
    uid, role = authenticate({"Member"})
    ex = get_executor(eid)
    require_ownership(role, uid, db.subscriptions[ex["subscription_id"]]["member_id"])
    body = get_body()
    decision = as_enum(require(body, "decision"), "decision", EXECUTOR_DECISIONS)

    if ex["status"] in ("DECLINED", "REVOKED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "executor is already terminal")
    if ex["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_STATE", "executor has already responded")

    ex["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(ex)
    return respond_entity(ex, status=200)


# =====================================================================
# Share grants
# =====================================================================
@app.route("/v1/share-grants", methods=["POST"])
def create_share_grant():
    uid, role = authenticate({"Member"})
    body = get_body()
    document_id = as_str(require(body, "document_id"), "document_id")
    grantee_email = as_str(require(body, "grantee_email"), "grantee_email")
    scope = as_enum(require(body, "scope"), "scope", SCOPES)
    expires_at = parse_iso(require(body, "expires_at"))

    doc = get_document(document_id)
    require_ownership(role, uid, doc_owner(doc))

    if doc["status"] != "EXECUTED":
        raise ApiError("ERR_DOCUMENT_NOT_EXECUTED", "share grants require an EXECUTED document")

    created_at = clock.now()
    # Closed-window overlap (touching counts) against active grants for same grantee+document.
    for g in db.share_grants.values():
        if (
            g["document_id"] == document_id
            and g["grantee_email"] == grantee_email
            and g["status"] == "ACTIVE"
        ):
            if created_at <= g["expires_at"] and g["created_at"] <= expires_at:
                raise ApiError("ERR_SHARE_WINDOW_OVERLAP", "share window overlaps an existing active grant")

    ent = {
        "document_id": document_id,
        "grantee_email": grantee_email,
        "scope": scope,
        "status": "ACTIVE",
        "expires_at": expires_at,
    }
    add_common(ent)
    db.share_grants[ent["id"]] = ent
    return respond_entity(ent, status=201)


@app.route("/v1/share-grants/<gid>/revoke", methods=["POST"])
def revoke_share_grant(gid):
    uid, role = authenticate({"Member"})
    grant = get_share_grant(gid)
    doc = db.documents[grant["document_id"]]
    require_ownership(role, uid, doc_owner(doc))

    if grant["status"] == "REVOKED":
        raise ApiError("ERR_ALREADY_TERMINAL", "share grant is already revoked")
    grant["status"] = "REVOKED"
    touch(grant)
    return respond_entity(grant, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
