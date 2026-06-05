"""Trial-scoped resources: trials, eligibility criteria, randomization arms,
consent documents, IRB reviews (open / decide / consent activation).

Implements PRD §3.1 (setup), §3.2 (consent + ethics review), and the OCC-guarded
consent activation cascade (PRD §2.6 / §3.2).
"""
from flask import Blueprint

import clock
import db
import domain
from errors import err
from middleware import require
from response import object_response, array_plain
from serialize import serialize
from validate import (
    get_json, require_fields, check_int, check_number, check_string,
    check_enum, check_action, pagination,
)

bp = Blueprint("trials", __name__)

CRITERION_ATTRS = {"age_years", "weight_kg", "hba1c", "prior_trials_count", "biomarker_positive"}
COMPARATORS = {"GE", "GT", "LE", "LT", "EQ"}


def _get_trial_or_404(trial_id):
    t = db.trials.get(trial_id)
    if t is None:
        err("ERR_NOT_FOUND", "Trial not found")
    return t


# --- Trial -----------------------------------------------------------------

@bp.route("/trials", methods=["POST"])
@require("Sponsor")
def create_trial(caller_id=None, caller_role=None):
    body = get_json()
    require_fields(body, "title", "target_enrollment", "randomization_method")
    title = check_string(body, "title")
    target = check_int(body, "target_enrollment", minimum=1)
    method = check_enum(body, "randomization_method", {"SIMPLE", "PERMUTED_BLOCK"})

    block_size = None
    if method == "PERMUTED_BLOCK":
        if "block_size" not in body or body["block_size"] is None:
            err("ERR_INVALID_REQUEST", "PERMUTED_BLOCK requires block_size")
        block_size = check_int(body, "block_size", minimum=1)
    else:
        # SIMPLE leaves block_size null even if a value is supplied.
        if body.get("block_size") is not None:
            block_size = check_int(body, "block_size", minimum=1)
            # SIMPLE keeps block_size null per PRD §3.1.
            block_size = None

    rec = domain.make_base()
    rec.update({
        "title": title,
        "sponsor_user_id": caller_id,
        "target_enrollment": target,
        "randomization_method": method,
        "block_size": block_size,
        "irb_status": "NONE",
        "posture": "SETUP",
        "enrolled_count": 0,
        "active_safety_holds": 0,
    })
    db.trials[rec["id"]] = rec
    return object_response(serialize("Trial", rec), 201)


@bp.route("/trials/<trial_id>", methods=["GET"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer")
def get_trial(trial_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    return object_response(serialize("Trial", t), 200)


# --- EligibilityCriterion --------------------------------------------------

@bp.route("/trials/<trial_id>/criteria", methods=["POST"])
@require("Sponsor")
def add_criterion(trial_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    body = get_json()
    require_fields(body, "kind", "attribute", "comparator", "threshold")
    kind = check_enum(body, "kind", {"INCLUSION", "EXCLUSION"})
    attribute = check_enum(body, "attribute", CRITERION_ATTRS)
    comparator = check_enum(body, "comparator", COMPARATORS)
    threshold = check_number(body, "threshold")

    if t["posture"] != "SETUP":
        err("ERR_TRIAL_NOT_IN_SETUP", "Criteria may only be added while the trial is in SETUP")

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "kind": kind,
        "attribute": attribute,
        "comparator": comparator,
        "threshold": threshold,
    })
    db.criteria[rec["id"]] = rec
    return object_response(serialize("EligibilityCriterion", rec), 201)


@bp.route("/trials/<trial_id>/criteria", methods=["GET"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer")
def list_criteria(trial_id, caller_id=None, caller_role=None):
    _get_trial_or_404(trial_id)
    items = domain.sorted_by_created(domain.trial_criteria(trial_id))
    return array_plain([serialize("EligibilityCriterion", c) for c in items])


# --- RandomizationArm ------------------------------------------------------

@bp.route("/trials/<trial_id>/arms", methods=["POST"])
@require("Sponsor")
def add_arm(trial_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    body = get_json()
    require_fields(body, "name", "allocation_weight")
    name = check_string(body, "name")
    weight = check_int(body, "allocation_weight", minimum=1)

    if t["posture"] != "SETUP":
        err("ERR_TRIAL_NOT_IN_SETUP", "Arms may only be added while the trial is in SETUP")

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "name": name,
        "allocation_weight": weight,
        "assigned_count": 0,
    })
    db.arms[rec["id"]] = rec
    return object_response(serialize("RandomizationArm", rec), 201)


@bp.route("/trials/<trial_id>/arms", methods=["GET"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer")
def list_arms(trial_id, caller_id=None, caller_role=None):
    _get_trial_or_404(trial_id)
    items = domain.sorted_by_created(domain.trial_arms(trial_id))
    return array_plain([serialize("RandomizationArm", a) for a in items])


# --- ConsentDocument -------------------------------------------------------

@bp.route("/trials/<trial_id>/consent-documents", methods=["POST"])
@require("Sponsor")
def create_consent(trial_id, caller_id=None, caller_role=None):
    _get_trial_or_404(trial_id)
    body = get_json()
    require_fields(body, "body_hash")
    body_hash = check_string(body, "body_hash")

    existing = domain.trial_consents(trial_id)
    version_number = max((d["version_number"] for d in existing), default=0) + 1

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "version_number": version_number,
        "body_hash": body_hash,
        "status": "DRAFT",
        "irb_review_id": None,
    })
    db.consent_documents[rec["id"]] = rec
    return object_response(serialize("ConsentDocument", rec), 201)


@bp.route("/trials/<trial_id>/consent-documents", methods=["GET"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer")
def list_consents(trial_id, caller_id=None, caller_role=None):
    from flask import request

    _get_trial_or_404(trial_id)
    items = domain.trial_consents(trial_id)
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = domain.sorted_by_created(items)
    return array_plain([serialize("ConsentDocument", d) for d in items])


@bp.route("/trials/<trial_id>/consent-documents/<doc_id>/activate", methods=["POST"])
@require("Sponsor")
def activate_consent(trial_id, doc_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    doc = db.consent_documents.get(doc_id)
    if doc is None or doc["trial_id"] != trial_id:
        err("ERR_NOT_FOUND", "Consent document not found")

    body = get_json()
    # OCC field is required for this write (PRD §2.6).
    if "expected_trial_version" not in body or body["expected_trial_version"] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: expected_trial_version")
    expected = check_int(body, "expected_trial_version")

    # OCC precedes the configuration check (PRD §2.6 prose authority): a stale
    # version is rejected 412 even when the document is already ACTIVE — the
    # test suite re-activates an ACTIVE v2 with a stale version and expects
    # ERR_STALE_TRIAL_VERSION, not a document-state error.
    if expected != t["version"]:
        err("ERR_STALE_TRIAL_VERSION", "expected_trial_version does not match the trial version")

    # Configuration preconditions (PRD §3.2): the three requirements — document
    # in IRB_APPROVED, trial irb_status APPROVED, and >=1 arm — all collapse to
    # ERR_TRIAL_NOT_CONFIGURED ("if any of these preconditions is unmet"). The
    # not-yet-IRB_APPROVED (e.g. DRAFT) document case is therefore reported as
    # ERR_TRIAL_NOT_CONFIGURED, never ERR_INVALID_STATE.
    if (doc["status"] != "IRB_APPROVED"
            or t["irb_status"] != "APPROVED"
            or len(domain.trial_arms(trial_id)) < 1):
        err("ERR_TRIAL_NOT_CONFIGURED",
            "Activation requires an IRB_APPROVED consent, APPROVED protocol, and >=1 arm")

    # --- cascade hop 1: supersede the prior ACTIVE document ----------------
    prior = domain.active_consent(trial_id)
    if prior is not None and prior["id"] != doc["id"]:
        prior["status"] = "SUPERSEDED"
        domain.touch(prior)
        # --- cascade hop 2: reconsent CONSENTED enrollments on that doc ----
        for e in domain.trial_enrollments(trial_id):
            if (e["signed_consent_document_id"] == prior["id"]
                    and e["enrollment_status"] == "CONSENTED"):
                e["signed_consent_document_id"] = None
                e["signed_consent_version"] = None
                e["enrollment_status"] = "SCREENED"
                domain.touch(e)

    # Activate this document.
    doc["status"] = "ACTIVE"
    domain.touch(doc)

    # Recompute posture and bump the trial version once for the operation.
    domain.recompute_trial_posture(t)
    domain.touch(t)

    return object_response(serialize("ConsentDocument", doc), 200)


# --- IRBReview -------------------------------------------------------------

@bp.route("/trials/<trial_id>/irb-reviews", methods=["POST"])
@require("Sponsor")
def open_review(trial_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    body = get_json()
    require_fields(body, "scope")
    scope = check_enum(body, "scope", {"PROTOCOL", "CONSENT"})

    consent_document_id = body.get("consent_document_id")

    # Body-reference existence (priority 4) before per-action field shape.
    if consent_document_id is not None:
        ref = db.consent_documents.get(consent_document_id)
        if ref is None or ref["trial_id"] != trial_id:
            err("ERR_REFERENCE_NOT_FOUND", "consent_document_id does not resolve")

    # Per-action required fields (priority 7): CONSENT requires consent_document_id;
    # PROTOCOL must omit it.
    if scope == "CONSENT" and consent_document_id is None:
        err("ERR_MISSING_ACTION_FIELD", "CONSENT-scope review requires consent_document_id")
    if scope == "PROTOCOL" and consent_document_id is not None:
        err("ERR_MISSING_ACTION_FIELD", "PROTOCOL-scope review must not carry consent_document_id")

    # At most one PENDING PROTOCOL review per trial (priority 19).
    if scope == "PROTOCOL":
        for r in db.irb_reviews.values():
            if (r["trial_id"] == trial_id and r["scope"] == "PROTOCOL"
                    and r["decision"] == "PENDING"):
                err("ERR_REVIEW_ALREADY_OPEN", "A PENDING PROTOCOL review already exists")

    rec = domain.make_base()
    rec.update({
        "trial_id": trial_id,
        "scope": scope,
        "consent_document_id": consent_document_id,
        "reviewer_user_id": None,
        "decision": "PENDING",
        "decided_at": None,
    })
    db.irb_reviews[rec["id"]] = rec

    if scope == "PROTOCOL":
        t["irb_status"] = "PENDING"
        domain.recompute_trial_posture(t)
        domain.touch(t)

    return object_response(serialize("IRBReview", rec), 201)


@bp.route("/trials/<trial_id>/irb-reviews", methods=["GET"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer")
def list_reviews(trial_id, caller_id=None, caller_role=None):
    from flask import request

    _get_trial_or_404(trial_id)
    items = [r for r in db.irb_reviews.values() if r["trial_id"] == trial_id]
    scope = request.args.get("scope")
    decision = request.args.get("decision")
    if scope is not None:
        items = [r for r in items if r["scope"] == scope]
    if decision is not None:
        items = [r for r in items if r["decision"] == decision]
    items = domain.sorted_by_created(items)
    return array_plain([serialize("IRBReview", r) for r in items])


@bp.route("/trials/<trial_id>/irb-reviews/<review_id>/decide", methods=["POST"])
@require("IRBReviewer")
def decide_review(trial_id, review_id, caller_id=None, caller_role=None):
    t = _get_trial_or_404(trial_id)
    review = db.irb_reviews.get(review_id)
    if review is None or review["trial_id"] != trial_id:
        err("ERR_NOT_FOUND", "IRB review not found")

    body = get_json()
    require_fields(body, "action")
    action = check_action(body, "action", {"APPROVE", "REJECT", "REVISE"})

    # State (priority 8) / already-decided (priority 9).
    if review["decision"] != "PENDING":
        err("ERR_REVISE_NOT_DECIDABLE", "Review is no longer PENDING")

    # Segregation of duties (priority 10): reviewer must not be the sponsor.
    if caller_id == t["sponsor_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "An IRBReviewer may not decide their own trial's review")

    if action == "APPROVE" and review["scope"] == "CONSENT":
        # The referenced consent document must currently be DRAFT.
        doc = db.consent_documents.get(review["consent_document_id"])
        if doc is None or doc["status"] != "DRAFT":
            err("ERR_INVALID_STATE", "Referenced consent document is not in DRAFT status")

    now = clock.now()
    review["reviewer_user_id"] = caller_id
    review["decided_at"] = now

    if action == "APPROVE":
        review["decision"] = "APPROVED"
        if review["scope"] == "PROTOCOL":
            t["irb_status"] = "APPROVED"
        else:
            doc = db.consent_documents[review["consent_document_id"]]
            doc["status"] = "IRB_APPROVED"
            doc["irb_review_id"] = review["id"]
            domain.touch(doc)
    elif action == "REJECT":
        review["decision"] = "REJECTED"
        if review["scope"] == "PROTOCOL":
            t["irb_status"] = "REJECTED"
    else:  # REVISE
        review["decision"] = "REVISE_REQUESTED"
        # PROTOCOL: irb_status stays PENDING (no change).

    domain.touch(review)

    # Every decision branch increments the trial version by one (PRD §3.2).
    domain.recompute_trial_posture(t)
    domain.touch(t)

    return object_response(serialize("IRBReview", review), 200)


