"""Claims lifecycle, documents, and reads."""
from flask import Blueprint, request

import store
import serializers as S
import calc
from store import touch
from common import (
    bad_request, get_body, new_common, ok, ok_list, optional_int, paginate,
    require_auth, require_enum, require_str, require_household_member, resolve_or_404,
)
from errors import ApiError
from util import new_id, now_iso

bp_claims = Blueprint("claims", __name__)

CLAIM_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "ManufacturerAgent", "PlatformAdmin"]
DOC_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "PlatformAdmin"]
DOC_TYPES = {"RECEIPT", "PHOTO", "SERIAL_PROOF", "OTHER"}
CLAIM_TYPES = {"WARRANTY", "RECALL"}
RESOLUTION_PREFS = {"REPLACEMENT", "REFUND"}


def _household_of_claim(claim):
    product = store.products.get(claim["product_id"])
    if product is None:
        return None
    return store.households.get(product["household_id"])


# ------------------------------------------------------------------ claims ----
@bp_claims.route("/claims", methods=["POST"])
def create_claim():
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    body = get_body()

    product_id = body.get("product_id")
    filed_by = body.get("filed_by_member_id")
    recall_match_id = body.get("recall_match_id")

    # existence left-to-right + membership on product's household
    if product_id is not None:
        product = store.products.get(product_id)
        if product is None:
            raise ApiError("ERR_NOT_FOUND")
        require_household_member(uid, product["household_id"])
    if filed_by is not None and filed_by not in store.members:
        raise ApiError("ERR_NOT_FOUND")
    if recall_match_id is not None and recall_match_id not in store.recall_matches:
        raise ApiError("ERR_NOT_FOUND")

    # well-formedness
    if not isinstance(product_id, str) or product_id == "":
        raise bad_request("product_id is required.")
    if not isinstance(filed_by, str) or filed_by == "":
        raise bad_request("filed_by_member_id is required.")
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    resolution_preference = require_enum(body, "resolution_preference", RESOLUTION_PREFS)
    issue_description = require_str(body, "issue_description")
    shipping_cost_cents = optional_int(body, "shipping_cost_cents", 0)

    rec = new_common()
    rec.update({
        "product_id": product_id,
        "filed_by_member_id": filed_by,
        "recall_match_id": recall_match_id if recall_match_id is not None else None,
        "claim_type": claim_type,
        "resolution_preference": resolution_preference,
        "issue_description": issue_description,
        "shipping_cost_cents": shipping_cost_cents,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
        "settlement_total_cents": None,
        "needs_docs_marker": None,
        "submit_subscription_id": None,
    })
    store.claims[rec["id"]] = rec
    household = _household_of_claim(rec)
    if household is not None:
        calc.recompute_active_claim_count(household)
    return ok(S.claim(rec), 201)


@bp_claims.route("/claims/<cid>/documents", methods=["POST"])
def add_document(cid):
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    claim = resolve_or_404(store.claims, cid)
    household = _household_of_claim(claim)
    if household is not None:
        require_household_member(uid, household["id"])
    body = get_body()
    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    file_uri = require_str(body, "file_uri")
    doc = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "claim_id": cid,
        "doc_type": doc_type,
        "file_uri": file_uri,
    }
    store.claim_documents[doc["id"]] = doc
    return ok(S.claim_document(doc), 201)


@bp_claims.route("/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    claim = resolve_or_404(store.claims, cid)
    household = _household_of_claim(claim)
    if household is not None:
        require_household_member(uid, household["id"])

    from_state = claim["status"]
    if from_state not in ("DRAFT", "NEEDS_DOCS"):
        raise ApiError("ERR_INVALID_STATE")

    product = store.products.get(claim["product_id"])
    # ERR_PRODUCT_ARCHIVED
    if product is not None and product["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PRODUCT_ARCHIVED")

    # ERR_MISSING_DOCUMENTATION
    docs = [d for d in store.claim_documents.values() if d["claim_id"] == cid]
    if from_state == "DRAFT":
        qualifies = len(docs) > 0
    else:  # NEEDS_DOCS re-submit: need a doc added after entering NEEDS_DOCS
        marker = claim.get("needs_docs_marker") or 0
        qualifies = any(d["_seq"] > marker for d in docs)
    if not qualifies:
        raise ApiError("ERR_MISSING_DOCUMENTATION")

    # ERR_SUBSCRIPTION_NOT_ACTIVE
    sub = calc.get_active_subscription(household["id"]) if household is not None else None
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE")

    # ERR_CLAIM_ALLOWANCE_EXCEEDED (only meaningful on first submit consuming allowance)
    ceiling = calc.TIER_CONFIG[sub["tier"]]["included_claims_per_year"]
    if from_state == "DRAFT" and sub["claims_used"] >= ceiling:
        raise ApiError("ERR_CLAIM_ALLOWANCE_EXCEEDED")

    claim["status"] = "SUBMITTED"
    if from_state == "DRAFT":
        sub["claims_used"] = sub["claims_used"] + 1
        claim["submit_subscription_id"] = sub["id"]
        touch(sub)
    touch(claim)
    if household is not None:
        calc.recompute_active_claim_count(household)
    return ok(S.claim(claim))


@bp_claims.route("/claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    role, uid = require_auth(["ConciergeAgent"])
    claim = resolve_or_404(store.claims, cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    claim["status"] = "UNDER_REVIEW"
    claim["reviewed_by_user_id"] = uid
    touch(claim)
    return ok(S.claim(claim))


@bp_claims.route("/claims/<cid>/request-docs", methods=["POST"])
def request_docs(cid):
    require_auth(["ConciergeAgent"])
    claim = resolve_or_404(store.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    claim["status"] = "NEEDS_DOCS"
    claim["needs_docs_marker"] = store.next_seq()
    touch(claim)
    return ok(S.claim(claim))


@bp_claims.route("/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    role, uid = require_auth(["ConciergeAgent"])
    claim = resolve_or_404(store.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if uid == claim["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["status"] = "APPROVED"
    _create_resolution(claim)
    touch(claim)
    household = _household_of_claim(claim)
    if household is not None:
        calc.recompute_active_claim_count(household)
    return ok(S.claim(claim))


def _create_resolution(claim):
    product = store.products.get(claim["product_id"])
    household = _household_of_claim(claim)
    mode = claim["resolution_preference"]
    res = new_common()
    res.update({
        "claim_id": claim["id"],
        "replacement_product_id": None,
        "mode": mode,
        "refund_variant": None,
        "refund_amount_cents": None,
        "shipping_cost_cents": claim.get("shipping_cost_cents", 0),
        "shipping_reimbursement_cents": 0,
        "concierge_fee_cents": 0,
        "settlement_total_cents": 0,
        "rma_status": "NONE",
        "rma_number": None,
        "status": "PENDING",
    })
    if mode == "REFUND" and product is not None:
        sub = calc.resolve_tier_subscription(household["id"]) if household is not None else None
        tier = sub["tier"] if sub is not None else "BASIC"
        variant, refund_amount = calc.compute_refund(product, tier)
        res["refund_variant"] = variant
        res["refund_amount_cents"] = refund_amount
        components = calc.compute_settlement(refund_amount, res["shipping_cost_cents"], tier)
        res["shipping_reimbursement_cents"] = components["shipping_reimbursement_cents"]
        res["concierge_fee_cents"] = components["concierge_fee_cents"]
        res["settlement_total_cents"] = components["settlement_total_cents"]
    store.resolutions[res["id"]] = res
    return res


@bp_claims.route("/claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    role, uid = require_auth(["ConciergeAgent"])
    claim = resolve_or_404(store.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if uid == claim["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    claim["status"] = "REJECTED"
    touch(claim)
    household = _household_of_claim(claim)
    if household is not None:
        calc.recompute_active_claim_count(household)
    return ok(S.claim(claim))


@bp_claims.route("/claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    claim = resolve_or_404(store.claims, cid)
    household = _household_of_claim(claim)
    if household is not None:
        require_household_member(uid, household["id"])
    if claim["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_DOCS"):
        raise ApiError("ERR_INVALID_STATE")
    claim["status"] = "WITHDRAWN"
    sub_id = claim.get("submit_subscription_id")
    if sub_id is not None:
        sub = store.subscriptions.get(sub_id)
        if sub is not None:
            sub["claims_used"] = max(0, sub["claims_used"] - 1)
            touch(sub)
    touch(claim)
    if household is not None:
        calc.recompute_active_claim_count(household)
    return ok(S.claim(claim))


@bp_claims.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_auth(CLAIM_READ_ROLES)
    rec = resolve_or_404(store.claims, cid)
    return ok(S.claim(rec))


@bp_claims.route("/claims", methods=["GET"])
def list_claims():
    require_auth(CLAIM_READ_ROLES)
    product_id = request.args.get("product_id")
    filed_by = request.args.get("filed_by_member_id")
    recall_match_id = request.args.get("recall_match_id")
    records = list(store.claims.values())
    if product_id is not None:
        records = [c for c in records if c["product_id"] == product_id]
    if filed_by is not None:
        records = [c for c in records if c["filed_by_member_id"] == filed_by]
    if recall_match_id is not None:
        records = [c for c in records if c["recall_match_id"] == recall_match_id]
    items, pagination = paginate(records, S.claim)
    return ok_list(items, pagination)


@bp_claims.route("/claim-documents/<did>", methods=["GET"])
def get_claim_document(did):
    require_auth(DOC_READ_ROLES)
    rec = resolve_or_404(store.claim_documents, did)
    return ok(S.claim_document(rec))


@bp_claims.route("/claim-documents", methods=["GET"])
def list_claim_documents():
    require_auth(DOC_READ_ROLES)
    claim_id = request.args.get("claim_id")
    records = list(store.claim_documents.values())
    if claim_id is not None:
        records = [d for d in records if d["claim_id"] == claim_id]
    items, pagination = paginate(records, S.claim_document)
    return ok_list(items, pagination)
