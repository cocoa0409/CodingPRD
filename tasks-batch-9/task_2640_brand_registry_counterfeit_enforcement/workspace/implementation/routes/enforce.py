"""Evidence packages, takedown submissions and counter notices."""

from flask import Blueprint

import calc
import constants as C
import db
import entities
import ledger
import reps
import validation as V
from errors import fail
from middleware import (ALL_ROLES, AUTHORIZED_REPRESENTATIVE,
                        ENFORCEMENT_ANALYST, MARKETPLACE_LIAISON, authenticate)
from response import created, ok, public
from timeutil import add_business_days
from versioning import touch

bp = Blueprint("enforce", __name__)


def _package_referenced_by_live_takedown(package_id):
    for takedown in db.values("takedowns"):
        if (takedown["evidence_package_id"] == package_id
                and takedown["status"] in ("SUBMITTED", "APPROVED_REMOVED",
                                           "COUNTER_NOTICED")):
            return True
    return False


def _rederive_package(package):
    claim = db.get("claims", package["claim_id"])
    coverage, required_total, score = calc.evidence_completeness(
        package["items"], claim["claimed_violation_type"])
    package["required_type_coverage"] = coverage
    package["completeness_score"] = score
    return coverage, required_total, score


# --------------------------------------------------------- evidence packages --

@bp.route("/brand-protection/evidence-packages", methods=["POST"])
def create_package():
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    claim_id = V.id_field(payload, "claim_id")
    package_ref = V.string_field(payload, "package_ref", 1, 40)
    expected = V.int_field(payload, "expected_claim_version", minimum=None)
    claim = V.must_exist("claims", claim_id)
    if expected != claim["version"]:
        fail("ERR_STALE_CLAIM_VERSION")
    row = entities.new_package(claim["id"], package_ref)
    touch(claim)
    return created(public(row))


@bp.route("/brand-protection/evidence-packages/<package_id>", methods=["GET"])
def read_package(package_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("packages", package_id)))


@bp.route("/brand-protection/evidence-packages", methods=["GET"])
def list_packages():
    authenticate(ALL_ROLES)
    return V.collection("packages", {"claim_id": None,
                                     "status": C.PACKAGE_STATUSES})


@bp.route("/brand-protection/evidence-packages/<package_id>/items",
          methods=["POST"])
def append_package_item(package_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    item_type = V.enum_field(payload, "item_type", calc.ALL_ITEM_TYPES)
    item_ref = V.string_field(payload, "item_ref", 1, 80)
    package = V.must_exist("packages", package_id)
    if package["status"] != "ASSEMBLING":
        fail("ERR_EVIDENCE_PACKAGE_SEALED")
    package["items"].append({"item_type": item_type, "item_ref": item_ref,
                             "added_at": db.now()})
    package["item_count"] = len(package["items"])
    _rederive_package(package)
    touch(package)
    return ok(public(package))


@bp.route("/brand-protection/evidence-packages/<package_id>/seal",
          methods=["POST"])
def seal_package(package_id):
    authenticate(ENFORCEMENT_ANALYST)
    V.body()
    package = V.must_exist("packages", package_id)
    if package["status"] != "ASSEMBLING":
        fail("ERR_INVALID_STATE")
    coverage, required_total, score = _rederive_package(package)
    if not calc.evidence_sealable(coverage, required_total, score):
        fail("ERR_EVIDENCE_INCOMPLETE")
    package["status"] = "SEALED"
    package["sealed_at"] = db.now()
    touch(package)
    return ok(public(package))


@bp.route("/brand-protection/evidence-packages/<package_id>/withdraw",
          methods=["POST"])
def withdraw_package(package_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    V.string_field(payload, "reason_code", 1, 80)
    package = V.must_exist("packages", package_id)
    if package["status"] not in ("ASSEMBLING", "SEALED"):
        fail("ERR_INVALID_STATE")
    if _package_referenced_by_live_takedown(package["id"]):
        fail("ERR_INVALID_STATE")
    package["status"] = "WITHDRAWN"
    touch(package)
    return ok(public(package))


# ---------------------------------------------------- takedown submissions ----

@bp.route("/brand-protection/takedowns", methods=["POST"])
def create_takedown():
    authenticate(ENFORCEMENT_ANALYST, AUTHORIZED_REPRESENTATIVE)
    payload = V.body()
    enrollment_id = V.id_field(payload, "enrollment_id")
    claim_id = V.id_field(payload, "claim_id")
    package_id = V.id_field(payload, "evidence_package_id")
    enrollment = V.must_exist("enrollments", enrollment_id)
    claim = V.must_exist("claims", claim_id)
    package = V.must_exist("packages", package_id)
    registration = db.get("registrations", claim["asserted_registration_id"])
    if registration is None or registration["status"] != "REGISTERED":
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    if package["claim_id"] != claim["id"]:
        fail("ERR_EVIDENCE_PACKAGE_MISMATCH")
    row = entities.new_takedown(enrollment["id"], claim["id"], package["id"])
    return created(public(row))


@bp.route("/brand-protection/takedowns/<takedown_id>", methods=["GET"])
def read_takedown(takedown_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("takedowns", takedown_id)))


@bp.route("/brand-protection/takedowns", methods=["GET"])
def list_takedowns():
    authenticate(ALL_ROLES)
    return V.collection("takedowns", {
        "claim_id": None,
        "enrollment_id": None,
        "evidence_package_id": None,
        "submitted_by_rep_id": None,
        "status": C.TAKEDOWN_STATUSES,
    })


def _decision_due(enrollment, moment):
    allowance = C.TAKEDOWN_SLA_DAYS[enrollment["marketplace_code"]]
    return add_business_days(moment, allowance)


@bp.route("/brand-protection/takedowns/<takedown_id>/submit", methods=["POST"])
def submit_takedown(takedown_id):
    identity = authenticate(AUTHORIZED_REPRESENTATIVE)
    V.body()
    takedown = V.must_exist("takedowns", takedown_id)
    claim = db.get("claims", takedown["claim_id"])
    package = db.get("packages", takedown["evidence_package_id"])
    enrollment = db.get("enrollments", takedown["enrollment_id"])
    # priority 20 - state of the notice and of the rows it binds
    if takedown["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if claim is None or claim["status"] not in ("SUBSTANTIATED", "ENFORCED"):
        fail("ERR_INVALID_STATE")
    if package is None or package["status"] != "SEALED":
        fail("ERR_INVALID_STATE")
    # priority 22
    if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    # priority 30 then 35
    reps.require_effective(identity.representative)
    reps.require_scope(identity.representative, "SUBMIT_TAKEDOWN")
    # priority 45
    registration = db.get("registrations", claim["asserted_registration_id"])
    if registration is None or registration["status"] != "REGISTERED":
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    moment = db.now()
    takedown["status"] = "SUBMITTED"
    takedown["submitted_by_rep_id"] = identity.user_id
    takedown["submitted_at"] = moment
    takedown["round_number"] = 1
    takedown["decision_due_at"] = _decision_due(enrollment, moment)
    touch(takedown)
    listing = db.get("listings", claim["listing_id"])
    if listing is not None and listing["enforcement_status"] == "CLAIM_OPEN":
        listing["enforcement_status"] = "TAKEDOWN_PENDING"
        touch(listing)
    return ok(public(takedown))


@bp.route("/brand-protection/takedowns/<takedown_id>/marketplace-decision",
          methods=["POST"])
def marketplace_decision(takedown_id):
    authenticate(MARKETPLACE_LIAISON)
    payload = V.body()
    decision = V.enum_field(payload, "decision", C.MARKETPLACE_DECISIONS)
    case_ref = V.string_field(payload, "marketplace_case_ref", 1, 60)
    takedown = V.must_exist("takedowns", takedown_id)
    if takedown["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    moment = db.now()
    takedown["decided_at"] = moment
    takedown["marketplace_case_ref"] = case_ref
    claim = db.get("claims", takedown["claim_id"])
    listing = db.get("listings", claim["listing_id"]) if claim else None
    if decision == "REJECTED":
        takedown["status"] = "REJECTED"
        touch(takedown)
        if listing is not None and listing["enforcement_status"] == "TAKEDOWN_PENDING":
            listing["enforcement_status"] = "CLAIM_OPEN"
            touch(listing)
        return ok(public(takedown))

    takedown["status"] = "APPROVED_REMOVED"
    takedown["counter_notice_deadline_at"] = add_business_days(
        moment, C.COUNTER_NOTICE_FILING_DAYS)
    touch(takedown)
    if listing is not None and listing["enforcement_status"] == "TAKEDOWN_PENDING":
        listing["enforcement_status"] = "REMOVED"
        touch(listing)
    if claim is not None and claim["status"] == "SUBSTANTIATED":
        claim["status"] = "ENFORCED"
        touch(claim)
    if listing is not None:
        ledger.attribute_strike(listing["seller_id"], claim["brand_id"],
                                takedown["id"])
    return ok(public(takedown))


@bp.route("/brand-protection/takedowns/<takedown_id>/resubmit", methods=["POST"])
def resubmit_takedown(takedown_id):
    identity = authenticate(AUTHORIZED_REPRESENTATIVE)
    payload = V.body()
    package_id = V.id_field(payload, "evidence_package_id")
    takedown = V.must_exist("takedowns", takedown_id)
    package = V.must_exist("packages", package_id)
    claim = db.get("claims", takedown["claim_id"])
    enrollment = db.get("enrollments", takedown["enrollment_id"])
    # priority 20
    if takedown["status"] not in ("REJECTED", "REINSTATED"):
        fail("ERR_INVALID_STATE")
    if package["status"] != "SEALED":
        fail("ERR_INVALID_STATE")
    # priority 22
    if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    # priority 30 then 35
    reps.require_effective(identity.representative)
    reps.require_scope(identity.representative, "SUBMIT_TAKEDOWN")
    # priority 60
    if (package["id"] == takedown["evidence_package_id"]
            or package["claim_id"] != takedown["claim_id"]):
        fail("ERR_EVIDENCE_PACKAGE_MISMATCH")
    # priority 68
    if takedown["round_number"] >= C.MAX_TAKEDOWN_ROUNDS:
        fail("ERR_MAX_TAKEDOWN_ROUNDS")
    moment = db.now()
    takedown["status"] = "SUBMITTED"
    takedown["evidence_package_id"] = package["id"]
    takedown["round_number"] = takedown["round_number"] + 1
    takedown["submitted_by_rep_id"] = identity.user_id
    takedown["submitted_at"] = moment
    takedown["decision_due_at"] = _decision_due(enrollment, moment)
    takedown["decided_at"] = None
    takedown["marketplace_case_ref"] = None
    takedown["counter_notice_deadline_at"] = None
    touch(takedown)
    listing = db.get("listings", claim["listing_id"]) if claim else None
    if listing is not None and listing["enforcement_status"] != "TAKEDOWN_PENDING":
        listing["enforcement_status"] = "TAKEDOWN_PENDING"
        touch(listing)
    return ok(public(takedown))


# ----------------------------------------------------------- counter notices --

@bp.route("/brand-protection/counter-notices", methods=["POST"])
def create_counter_notice():
    authenticate(MARKETPLACE_LIAISON)
    payload = V.body()
    takedown_id = V.id_field(payload, "takedown_id")
    seller_id = V.id_field(payload, "seller_id")
    sworn_statement_ref = V.string_field(payload, "sworn_statement_ref", 1, 80)
    takedown = V.must_exist("takedowns", takedown_id)
    seller = V.must_exist("sellers", seller_id)
    if takedown["status"] != "APPROVED_REMOVED":
        fail("ERR_INVALID_STATE")
    moment = db.now()
    deadline = takedown["counter_notice_deadline_at"]
    if deadline is None or moment > deadline:
        fail("ERR_COUNTER_NOTICE_WINDOW_EXPIRED")
    for existing in db.values("counter_notices"):
        if existing["takedown_id"] == takedown["id"]:
            fail("ERR_DUPLICATE_COUNTER_NOTICE")
    row = entities.new_counter_notice(
        takedown["id"], seller["id"], sworn_statement_ref, moment,
        add_business_days(moment, C.REBUTTAL_WINDOW_DAYS))
    takedown["status"] = "COUNTER_NOTICED"
    touch(takedown)
    return created(public(row))


@bp.route("/brand-protection/counter-notices/<counter_notice_id>",
          methods=["GET"])
def read_counter_notice(counter_notice_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("counter_notices", counter_notice_id)))


@bp.route("/brand-protection/counter-notices", methods=["GET"])
def list_counter_notices():
    authenticate(ALL_ROLES)
    return V.collection("counter_notices", {
        "takedown_id": None,
        "seller_id": None,
        "status": C.COUNTER_NOTICE_STATUSES,
    })


@bp.route("/brand-protection/counter-notices/<counter_notice_id>/resolve",
          methods=["POST"])
def resolve_counter_notice(counter_notice_id):
    authenticate(MARKETPLACE_LIAISON)
    payload = V.body()
    resolution = V.enum_field(payload, "resolution",
                              C.COUNTER_NOTICE_RESOLUTIONS)
    rebuttal_ref = V.string_field(payload, "rebuttal_ref", 1, 80,
                                 required=False)
    if resolution == "REBUTTED" and rebuttal_ref is None:
        fail("ERR_INVALID_REQUEST",
             "rebuttal_ref is required when the resolution is REBUTTED.")
    notice = V.must_exist("counter_notices", counter_notice_id)
    if notice["status"] != "FILED":
        fail("ERR_INVALID_STATE")
    moment = db.now()
    if notice["response_due_at"] is not None and moment > notice["response_due_at"]:
        fail("ERR_INVALID_STATE")
    takedown = db.get("takedowns", notice["takedown_id"])
    claim = db.get("claims", takedown["claim_id"]) if takedown else None
    listing = db.get("listings", claim["listing_id"]) if claim else None
    notice["resolved_at"] = moment
    if resolution == "REBUTTED":
        notice["rebuttal_ref"] = rebuttal_ref
        notice["status"] = "REBUTTED"
        touch(notice)
        if takedown is not None and takedown["status"] == "COUNTER_NOTICED":
            takedown["status"] = "APPROVED_REMOVED"
            touch(takedown)
        return ok(public(notice))

    notice["status"] = "ACCEPTED"
    touch(notice)
    if takedown is not None and takedown["status"] == "COUNTER_NOTICED":
        takedown["status"] = "REINSTATED"
        touch(takedown)
    if listing is not None and listing["enforcement_status"] == "REMOVED":
        listing["enforcement_status"] = "REINSTATED"
        touch(listing)
    ledger.demote_claim_after_reversal(claim)
    if listing is not None:
        ledger.attribute_strike(listing["seller_id"], claim["brand_id"],
                                auto_case=False)
    return ok(public(notice))
