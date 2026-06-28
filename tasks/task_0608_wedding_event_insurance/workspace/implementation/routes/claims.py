"""Claim filing, documentation, and adjudication routes (PRD §3.7; scaffold §1.5)."""
from flask import Blueprint

from db import db, new_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.calculations import MAX_REVISIONS, claim_indemnity
from services.lookups import (
    children_by_policy,
    get_claim,
    get_policy,
)
from services.policy_ops import append_ledger
from validators import (
    get_body,
    get_pagination,
    opt_str,
    query_str,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"CANCELLATION", "VENDOR_FAILURE", "FORCE_MAJEURE", "PROPERTY"}
DOC_TYPES = {"INVOICE", "RECEIPT", "POLICE_REPORT", "VENDOR_CONTRACT", "PHOTO"}
SUBJECT_KINDS = {"VENDOR", "COVERAGE", "NONE"}


def _paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


def _docs_for_claim(claim_id):
    docs = [d for d in db.claim_documents.values() if d["claim_id"] == claim_id]
    docs.sort(key=lambda d: d["_seq"])
    return docs


# ---- File a claim (PRD §3.7) -----------------------------------------------
@bp.route("/policies/<policy_id>/claims", methods=["POST"])
def file_claim(policy_id):
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    get_policy(policy_id)
    body = get_body()

    coverage_id = req_str(body, "coverage_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    claimed_amount_cents = req_int(body, "claimed_amount_cents", minimum=1)
    vendor_id = opt_str(body, "vendor_id")
    force_majeure_event_id = opt_str(body, "force_majeure_event_id")

    # Body FK resolution (priority 5): coverage, vendor, peril.
    coverage = db.coverages.get(coverage_id)
    if coverage is None or coverage["policy_id"] != policy_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "coverage_id does not resolve")
    if vendor_id is not None and vendor_id not in db.vendors:
        raise err("ERR_REFERENCE_NOT_FOUND", "vendor_id does not resolve")
    if force_majeure_event_id is not None and force_majeure_event_id not in db.force_majeure_events:
        raise err("ERR_REFERENCE_NOT_FOUND", "force_majeure_event_id does not resolve")

    claim = new_common()
    claim.update({
        "policy_id": policy_id,
        "coverage_id": coverage_id,
        "claim_type": claim_type,
        "vendor_id": vendor_id,
        "force_majeure_event_id": force_majeure_event_id,
        "claimed_amount_cents": claimed_amount_cents,
        "approved_amount_cents": 0,
        "revision_count": 0,
        "status": "SUBMITTED",
        "_docs_at_info_requested": 0,
    })
    db.claims[claim["id"]] = claim
    return success(public(claim), status=201)


@bp.route("/policies/<policy_id>/claims", methods=["GET"])
def list_claims(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_status = query_str("status")
    f_type = query_str("claim_type")
    items = children_by_policy(db.claims, policy_id)
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    if f_type is not None:
        items = [c for c in items if c["claim_type"] == f_type]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


@bp.route("/policies/<policy_id>/claims/<claim_id>", methods=["GET"])
def get_claim_route(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    claim = get_claim(policy_id, claim_id)
    return success(public(claim), status=200)


# ---- Documents (append-only; PRD §3.7) -------------------------------------
@bp.route("/policies/<policy_id>/claims/<claim_id>/documents", methods=["POST"])
def add_document(policy_id, claim_id):
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    policy = get_policy(policy_id)
    # Ownership check (priority 3).
    if policy["policyholder_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER", "acting policyholder does not own this policy")
    claim = get_claim(policy_id, claim_id)
    body = get_body()

    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    file_uri = req_str(body, "file_uri")
    subject_kind = body.get("subject_kind")
    if subject_kind is not None and subject_kind not in SUBJECT_KINDS:
        raise err("ERR_INVALID_REQUEST", "subject_kind must be one of VENDOR, COVERAGE, NONE")
    subject_ref = opt_str(body, "subject_ref")

    doc = new_common(versioned=False)
    doc.update({
        "claim_id": claim_id,
        "doc_type": doc_type,
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "file_uri": file_uri,
        "_seq": db.next_seq(),
    })
    db.claim_documents[doc["id"]] = doc
    return success(public(doc), status=201)


@bp.route("/policies/<policy_id>/claims/<claim_id>/documents", methods=["GET"])
def list_documents(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    get_claim(policy_id, claim_id)
    f_type = query_str("doc_type")
    items = _docs_for_claim(claim_id)
    if f_type is not None:
        items = [d for d in items if d["doc_type"] == f_type]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


# ---- Adjudication revision loop (PRD §3.7) ---------------------------------
@bp.route("/policies/<policy_id>/claims/<claim_id>/request-info", methods=["POST"])
def request_info(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"ClaimsAdjuster"})
    get_policy(policy_id)
    claim = get_claim(policy_id, claim_id)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_CLAIM_NOT_SUBMITTED", "claim is not SUBMITTED")
    claim["status"] = "INFO_REQUESTED"
    # Snapshot doc count at entry into INFO_REQUESTED for the new-docs check.
    claim["_docs_at_info_requested"] = len(_docs_for_claim(claim_id))
    touch(claim)
    return success(public(claim), status=200)


@bp.route("/policies/<policy_id>/claims/<claim_id>/resubmit", methods=["POST"])
def resubmit_claim(policy_id, claim_id):
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    policy = get_policy(policy_id)
    if policy["policyholder_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER", "acting policyholder does not own this policy")
    claim = get_claim(policy_id, claim_id)

    if claim["status"] != "INFO_REQUESTED":
        raise err("ERR_CLAIM_NOT_INFO_REQUESTED", "claim is not INFO_REQUESTED")

    # At least one new ClaimDocument since entering INFO_REQUESTED.
    if len(_docs_for_claim(claim_id)) <= claim["_docs_at_info_requested"]:
        raise err("ERR_NO_NEW_DOCUMENTATION", "no new documentation since INFO_REQUESTED")

    # revision_count may legally reach MAX_REVISIONS; the attempt past the cap is barred.
    if claim["revision_count"] >= MAX_REVISIONS:
        raise err("ERR_REVISION_CAP_EXCEEDED", "revision cap exceeded")

    claim["revision_count"] += 1
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success(public(claim), status=200)


@bp.route("/policies/<policy_id>/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"ClaimsAdjuster"})
    policy = get_policy(policy_id)
    claim = get_claim(policy_id, claim_id)

    # Ordered approval battery (PRD §3.7).
    if claim["status"] != "SUBMITTED":
        raise err("ERR_CLAIM_NOT_SUBMITTED", "claim is not SUBMITTED")
    if policy["lifecycle_status"] != "IN_FORCE":
        raise err("ERR_POLICY_NOT_IN_FORCE", "policy is not IN_FORCE")

    coverage = db.coverages[claim["coverage_id"]]
    if coverage["status"] == "EXHAUSTED":
        raise err("ERR_COVERAGE_LIMIT_EXCEEDED", "coverage line is EXHAUSTED")
    if coverage["status"] != "ACTIVE":
        raise err("ERR_COVERAGE_NOT_ACTIVE", "coverage line is not ACTIVE")

    claim_type = claim["claim_type"]
    if claim_type == "VENDOR_FAILURE":
        vendor = db.vendors.get(claim["vendor_id"]) if claim["vendor_id"] else None
        if vendor is None or vendor["status"] != "DEFAULTED":
            raise err("ERR_VENDOR_NOT_DEFAULTED", "referenced vendor is not DEFAULTED")

    if claim_type == "FORCE_MAJEURE":
        peril = db.force_majeure_events.get(claim["force_majeure_event_id"]) if claim["force_majeure_event_id"] else None
        if peril is None or peril["status"] != "ACTIVE":
            raise err("ERR_FORCE_MAJEURE_NOT_COVERED", "force-majeure peril is not ACTIVE")
        # Named-storm cutoff: bind_at must be strictly before cutoff_at.
        if not (policy["_bind_at_dt"] < peril["_cutoff_at"]):
            raise err("ERR_BOUND_AFTER_CUTOFF", "policy bound at or after the peril cutoff")
        # landfall_at must fall within some EventProfile [start, end] window.
        landfall = peril["_landfall_at"]
        covered = any(
            ep["_event_start_dt"] <= landfall <= ep["_event_end_dt"]
            for ep in children_by_policy(db.event_profiles, policy_id)
        )
        if not covered:
            raise err("ERR_LANDFALL_OUTSIDE_WINDOW", "landfall outside every event window")

    if not _docs_for_claim(claim_id):
        raise err("ERR_INSUFFICIENT_DOCUMENTATION", "claim has no documentation")

    # Indemnity (PRD §3.7).
    product = db.coverage_products[coverage["coverage_product_id"]]
    approved = claim_indemnity(product, coverage, claim_type, claim["claimed_amount_cents"])
    claim["approved_amount_cents"] = approved
    claim["status"] = "APPROVED"

    coverage["consumed_limit_cents"] += approved
    if coverage["consumed_limit_cents"] >= product["coverage_limit_cents"]:
        coverage["status"] = "EXHAUSTED"
    touch(coverage)
    touch(claim)

    # Bubble-up: IN_FORCE -> CLAIMED_OUT if every coverage EXHAUSTED/VOIDED and >=1 EXHAUSTED.
    all_coverages = children_by_policy(db.coverages, policy_id)
    if all_coverages and all(c["status"] in ("EXHAUSTED", "VOIDED") for c in all_coverages) \
            and any(c["status"] == "EXHAUSTED" for c in all_coverages):
        if policy["lifecycle_status"] == "IN_FORCE":
            policy["lifecycle_status"] = "CLAIMED_OUT"
            touch(policy)

    return success(public(claim), status=200)


@bp.route("/policies/<policy_id>/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"ClaimsAdjuster"})
    get_policy(policy_id)
    claim = get_claim(policy_id, claim_id)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_CLAIM_NOT_SUBMITTED", "claim is not SUBMITTED")
    claim["status"] = "DENIED"
    touch(claim)
    return success(public(claim), status=200)


@bp.route("/policies/<policy_id>/claims/<claim_id>/pay", methods=["POST"])
def pay_claim(policy_id, claim_id):
    _, role = get_user_context()
    require_role(role, {"ClaimsAdjuster"})
    get_policy(policy_id)
    claim = get_claim(policy_id, claim_id)
    if claim["status"] != "APPROVED":
        raise err("ERR_CLAIM_NOT_APPROVED", "claim is not APPROVED")
    append_ledger(policy_id, "INDEMNITY_PAYOUT", -claim["approved_amount_cents"])
    claim["status"] = "PAID"
    touch(claim)
    return success(public(claim), status=200)
