"""Surrogacy & Egg-Donation Agency API — Flask entry point.

In-memory store, empty on every boot. No seeding.
"""
import os

from flask import Flask, request

from errors import (
    ApiError,
    err,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_REQUEST,
    ERR_CARRIER_INELIGIBLE,
    ERR_PSYCH_CLEARANCE_MISSING,
    ERR_INSURANCE_REVIEW_REQUIRED,
    ERR_COOLING_OFF_ACTIVE,
    ERR_MILESTONE_ORDER_VIOLATION,
    ERR_DUPLICATE_MILESTONE,
    ERR_BUDGET_EXCEEDED,
    ERR_INSUFFICIENT_ESCROW,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_PARENTAGE_JURISDICTION_BLOCKED,
    ERR_MILESTONE_GATE_NOT_MET,
    ERR_JOURNEY_PRECONDITION,
    ERR_FORBIDDEN,
)
from response import success, success_list, error_response
from db import db, stamp_create, touch
from middleware import get_identity, require_roles
from clock import clock, parse_iso8601, format_iso8601
from calculations import (
    insurance_gap_premium,
    carrier_comp_breakdown,
    PHASE_ORDER,
)
import validate as V
import serialize as S
from datetime import timedelta

app = Flask(__name__)

PARENTAGE_HOSTILE = {"LA", "NE"}
READ_ROLES = ["CaseManager", "Screener", "FinanceOfficer"]
FINANCE_READ = ["CaseManager", "FinanceOfficer"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Bad request: %s" % str(e), 400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    """Standard auth+RBAC for operator/opaque-role endpoints. Returns (uid, role)."""
    uid, role = get_identity()
    require_roles(role, allowed_roles)
    return uid, role


def has_qualifying_insurance_review(carrier_id):
    for r in db.insurance_reviews.values():
        if r["carrier_id"] == carrier_id and r["status"] in ("APPROVED", "GAP_IDENTIFIED"):
            return True
    return False


def contract_for_journey(journey_id):
    journey = db.journeys.get(journey_id)
    if not journey:
        return None
    match_id = journey["match_id"]
    for c in db.contracts.values():
        if c["match_id"] == match_id:
            return c
    return None


def journey_has_void_contract(journey_id):
    """True if any contract linked to the journey's match is VOID (PRD §3.9)."""
    journey = db.journeys.get(journey_id)
    if not journey:
        return False
    match_id = journey["match_id"]
    return any(
        c["match_id"] == match_id and c["status"] == "VOID"
        for c in db.contracts.values()
    )


def escrow_for_journey(journey_id):
    for e in db.escrow_accounts.values():
        if e["journey_id"] == journey_id:
            return e
    return None


def freeze_escrow_if_open(escrow):
    if escrow and escrow["status"] == "OPEN":
        escrow["status"] = "FROZEN"
        touch(escrow)


def achieved_milestone_types(journey_id):
    return {
        m["milestone_type"]
        for m in db.milestones.values()
        if m["journey_id"] == journey_id and m["status"] == "ACHIEVED"
    }


# ===========================================================================
# Intended Parents
# ===========================================================================
@app.route("/intended-parents", methods=["POST"])
def create_intended_parent():
    auth(["CaseManager"])
    body = V.get_json_body()
    legal_name = V.require_string(body, "legal_name")
    state_code = V.require_state_code(body, "state_code")
    budget_cents = V.require_int_cents(body, "budget_cents")
    obj = {
        "legal_name": legal_name,
        "state_code": state_code,
        "intake_status": "DRAFT",
        "psych_clearance": "PENDING",
        "budget_cents": budget_cents,
    }
    stamp_create(obj)
    db.intended_parents[obj["id"]] = obj
    return success(S.ser_intended_parent(obj), status=201)


@app.route("/intended-parents/<pid>", methods=["GET"])
def get_intended_parent(pid):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.intended_parents, pid)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents", methods=["GET"])
def list_intended_parents():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.intended_parents.values())
    status_filter = request.args.get("intake_status")
    if status_filter is not None:
        items = [o for o in items if o["intake_status"] == status_filter]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_intended_parent(o) for o in page], limit, offset, total)


@app.route("/intended-parents/<pid>/submit", methods=["POST"])
def ip_submit(pid):
    auth(["CaseManager"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    if obj["intake_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "IntendedParent not in DRAFT")
    if not obj.get("legal_name") or obj["budget_cents"] < 0:
        raise err(ERR_INVALID_REQUEST, "budget_cents must be >= 0 and legal_name present")
    obj["intake_status"] = "SUBMITTED"
    touch(obj)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents/<pid>/return-to-draft", methods=["POST"])
def ip_return_to_draft(pid):
    auth(["CaseManager"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    if obj["intake_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "IntendedParent not in SUBMITTED")
    obj["intake_status"] = "DRAFT"
    touch(obj)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents/<pid>/start-screening", methods=["POST"])
def ip_start_screening(pid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    if obj["intake_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "IntendedParent not in SUBMITTED")
    obj["intake_status"] = "SCREENING"
    touch(obj)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents/<pid>/set-psych", methods=["POST"])
def ip_set_psych(pid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    body = V.get_json_body()
    value = V.require_enum(body, "psych_clearance", {"PASSED", "FAILED"})
    obj["psych_clearance"] = value
    touch(obj)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents/<pid>/clear", methods=["POST"])
def ip_clear(pid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "IntendedParent not in SCREENING")
    if obj["psych_clearance"] != "PASSED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "psych_clearance must be PASSED")
    obj["intake_status"] = "CLEARED"
    touch(obj)
    return success(S.ser_intended_parent(obj))


@app.route("/intended-parents/<pid>/reject", methods=["POST"])
def ip_reject(pid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.intended_parents, pid)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "IntendedParent not in SCREENING")
    obj["intake_status"] = "REJECTED"
    touch(obj)
    return success(S.ser_intended_parent(obj))


# ===========================================================================
# Gestational Carriers
# ===========================================================================
@app.route("/carriers", methods=["POST"])
def create_carrier():
    auth(["CaseManager"])
    body = V.get_json_body()
    legal_name = V.require_string(body, "legal_name")
    state_code = V.require_state_code(body, "state_code")
    prior_deliveries = V.require_int(body, "prior_deliveries")
    if prior_deliveries < 0:
        raise err(ERR_INVALID_REQUEST, "prior_deliveries must be >= 0")
    base_comp = V.require_int_cents(body, "base_compensation_cents")
    obj = {
        "legal_name": legal_name,
        "state_code": state_code,
        "intake_status": "DRAFT",
        "psych_clearance": "PENDING",
        "prior_deliveries": prior_deliveries,
        "base_compensation_cents": base_comp,
    }
    stamp_create(obj)
    db.carriers[obj["id"]] = obj
    return success(S.ser_carrier(obj), status=201)


@app.route("/carriers/<cid>", methods=["GET"])
def get_carrier(cid):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.carriers, cid)
    return success(S.ser_carrier(obj))


@app.route("/carriers", methods=["GET"])
def list_carriers():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.carriers.values())
    status_filter = request.args.get("intake_status")
    if status_filter is not None:
        items = [o for o in items if o["intake_status"] == status_filter]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_carrier(o) for o in page], limit, offset, total)


@app.route("/carriers/<cid>/submit", methods=["POST"])
def carrier_submit(cid):
    auth(["CaseManager"])
    obj = V.lookup_or_404(db.carriers, cid)
    if obj["intake_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Carrier not in DRAFT")
    if obj["prior_deliveries"] < 1:
        raise err(ERR_CARRIER_INELIGIBLE, "prior_deliveries must be >= 1")
    obj["intake_status"] = "SUBMITTED"
    touch(obj)
    return success(S.ser_carrier(obj))


@app.route("/carriers/<cid>/start-screening", methods=["POST"])
def carrier_start_screening(cid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.carriers, cid)
    if obj["intake_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Carrier not in SUBMITTED")
    obj["intake_status"] = "SCREENING"
    touch(obj)
    return success(S.ser_carrier(obj))


@app.route("/carriers/<cid>/set-psych", methods=["POST"])
def carrier_set_psych(cid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.carriers, cid)
    body = V.get_json_body()
    value = V.require_enum(body, "psych_clearance", {"PASSED", "FAILED"})
    obj["psych_clearance"] = value
    touch(obj)
    return success(S.ser_carrier(obj))


@app.route("/carriers/<cid>/clear", methods=["POST"])
def carrier_clear(cid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.carriers, cid)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "Carrier not in SCREENING")
    if obj["psych_clearance"] != "PASSED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "psych_clearance must be PASSED")
    if not has_qualifying_insurance_review(cid):
        raise err(ERR_INSURANCE_REVIEW_REQUIRED, "No qualifying InsuranceReview")
    obj["intake_status"] = "CLEARED"
    touch(obj)
    return success(S.ser_carrier(obj))


@app.route("/carriers/<cid>/reject", methods=["POST"])
def carrier_reject(cid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.carriers, cid)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "Carrier not in SCREENING")
    obj["intake_status"] = "REJECTED"
    touch(obj)
    return success(S.ser_carrier(obj))


@app.route("/carriers/<cid>/insurance-reviews", methods=["GET"])
def carrier_insurance_reviews(cid):
    auth(READ_ROLES)
    V.lookup_or_404(db.carriers, cid)
    limit, offset = V.parse_pagination()
    items = [r for r in db.insurance_reviews.values() if r["carrier_id"] == cid]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_insurance_review(o) for o in page], limit, offset, total)


# ===========================================================================
# Egg Donors
# ===========================================================================
@app.route("/egg-donors", methods=["POST"])
def create_donor():
    auth(["CaseManager"])
    body = V.get_json_body()
    donor_code = V.require_string(body, "donor_code")
    state_code = V.require_state_code(body, "state_code")
    donor_comp = V.require_int_cents(body, "donor_compensation_cents")
    obj = {
        "donor_code": donor_code,
        "state_code": state_code,
        "intake_status": "DRAFT",
        "donor_compensation_cents": donor_comp,
    }
    stamp_create(obj)
    db.egg_donors[obj["id"]] = obj
    return success(S.ser_donor(obj), status=201)


@app.route("/egg-donors/<did>", methods=["GET"])
def get_donor(did):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.egg_donors, did)
    return success(S.ser_donor(obj))


@app.route("/egg-donors", methods=["GET"])
def list_donors():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.egg_donors.values())
    status_filter = request.args.get("intake_status")
    if status_filter is not None:
        items = [o for o in items if o["intake_status"] == status_filter]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_donor(o) for o in page], limit, offset, total)


@app.route("/egg-donors/<did>/submit", methods=["POST"])
def donor_submit(did):
    auth(["CaseManager"])
    obj = V.lookup_or_404(db.egg_donors, did)
    if obj["intake_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Donor not in DRAFT")
    for other in db.egg_donors.values():
        if other["id"] == obj["id"]:
            continue
        if other["donor_code"] == obj["donor_code"] and other["intake_status"] in (
            "SUBMITTED",
            "SCREENING",
            "CLEARED",
        ):
            raise err(ERR_CARRIER_INELIGIBLE, "donor_code collides with a non-terminal donor")
    obj["intake_status"] = "SUBMITTED"
    touch(obj)
    return success(S.ser_donor(obj))


@app.route("/egg-donors/<did>/start-screening", methods=["POST"])
def donor_start_screening(did):
    auth(["Screener"])
    obj = V.lookup_or_404(db.egg_donors, did)
    if obj["intake_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Donor not in SUBMITTED")
    obj["intake_status"] = "SCREENING"
    touch(obj)
    return success(S.ser_donor(obj))


@app.route("/egg-donors/<did>/clear", methods=["POST"])
def donor_clear(did):
    auth(["Screener"])
    obj = V.lookup_or_404(db.egg_donors, did)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "Donor not in SCREENING")
    obj["intake_status"] = "CLEARED"
    touch(obj)
    return success(S.ser_donor(obj))


@app.route("/egg-donors/<did>/reject", methods=["POST"])
def donor_reject(did):
    auth(["Screener"])
    obj = V.lookup_or_404(db.egg_donors, did)
    if obj["intake_status"] != "SCREENING":
        raise err(ERR_INVALID_STATE, "Donor not in SCREENING")
    obj["intake_status"] = "REJECTED"
    touch(obj)
    return success(S.ser_donor(obj))


# ===========================================================================
# Insurance Reviews
# ===========================================================================
@app.route("/insurance-reviews", methods=["POST"])
def create_insurance_review():
    auth(["Screener"])
    body = V.get_json_body()
    carrier_id = V.require_string(body, "carrier_id")
    policy_kind = V.require_enum(body, "policy_kind", {"SURROGACY_FRIENDLY", "EXCLUSION", "NONE"})
    V.lookup_or_404(db.carriers, carrier_id)
    obj = {
        "carrier_id": carrier_id,
        "policy_kind": policy_kind,
        "status": "PENDING",
        "gap_premium_cents": 0,
    }
    stamp_create(obj)
    db.insurance_reviews[obj["id"]] = obj
    return success(S.ser_insurance_review(obj), status=201)


@app.route("/insurance-reviews/<rid>", methods=["GET"])
def get_insurance_review(rid):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.insurance_reviews, rid)
    return success(S.ser_insurance_review(obj))


@app.route("/insurance-reviews/<rid>/approve", methods=["POST"])
def insurance_approve(rid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.insurance_reviews, rid)
    if obj["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "InsuranceReview not PENDING")
    if obj["policy_kind"] != "SURROGACY_FRIENDLY":
        raise err(ERR_INVALID_STATE, "policy_kind must be SURROGACY_FRIENDLY to approve")
    obj["status"] = "APPROVED"
    touch(obj)
    return success(S.ser_insurance_review(obj))


@app.route("/insurance-reviews/<rid>/identify-gap", methods=["POST"])
def insurance_identify_gap(rid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.insurance_reviews, rid)
    if obj["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "InsuranceReview not PENDING")
    if obj["policy_kind"] != "EXCLUSION":
        raise err(ERR_INVALID_STATE, "policy_kind must be EXCLUSION to identify gap")
    carrier = db.carriers.get(obj["carrier_id"])
    base = carrier["base_compensation_cents"] if carrier else 0
    obj["gap_premium_cents"] = insurance_gap_premium(base)
    obj["status"] = "GAP_IDENTIFIED"
    touch(obj)
    return success(S.ser_insurance_review(obj))


@app.route("/insurance-reviews/<rid>/reject", methods=["POST"])
def insurance_reject(rid):
    auth(["Screener"])
    obj = V.lookup_or_404(db.insurance_reviews, rid)
    if obj["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "InsuranceReview not PENDING")
    if obj["policy_kind"] != "NONE":
        raise err(ERR_INVALID_STATE, "policy_kind must be NONE to reject")
    obj["status"] = "REJECTED"
    touch(obj)
    return success(S.ser_insurance_review(obj))


# ===========================================================================
# Matches
# ===========================================================================
@app.route("/matches", methods=["POST"])
def create_match():
    auth(["CaseManager"])
    body = V.get_json_body()
    ip_id = V.require_string(body, "intended_parent_id")
    carrier_id = V.require_string(body, "carrier_id")
    proposed = V.require_int_cents(body, "proposed_carrier_comp_cents")
    donor_id = body.get("donor_id")
    if donor_id is not None and not isinstance(donor_id, str):
        raise err(ERR_INVALID_REQUEST, "donor_id must be a string or null")
    V.lookup_or_404(db.intended_parents, ip_id)
    V.lookup_or_404(db.carriers, carrier_id)
    if donor_id is not None:
        V.lookup_or_404(db.egg_donors, donor_id)
    obj = {
        "intended_parent_id": ip_id,
        "carrier_id": carrier_id,
        "donor_id": donor_id,
        "status": "PROPOSED",
        "offer_round": 0,
        "proposed_carrier_comp_cents": proposed,
    }
    stamp_create(obj)
    db.matches[obj["id"]] = obj
    return success(S.ser_match(obj), status=201)


@app.route("/matches/<mid>", methods=["GET"])
def get_match(mid):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.matches, mid)
    return success(S.ser_match(obj))


@app.route("/matches", methods=["GET"])
def list_matches():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.matches.values())
    for key in ("intended_parent_id", "carrier_id", "donor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_match(o) for o in page], limit, offset, total)


def _match_multiples_addon(match):
    """Add-on applies when a journey for this match has HEARTBEAT achieved and
    current_phase >= HEARTBEAT_CONFIRMED."""
    for j in db.journeys.values():
        if j["match_id"] != match["id"]:
            continue
        phase = S.journey_current_phase(j)
        types = achieved_milestone_types(j["id"])
        if "HEARTBEAT" in types and PHASE_ORDER[phase] >= PHASE_ORDER["HEARTBEAT_CONFIRMED"]:
            return True
    return False


@app.route("/matches/<mid>/comp-breakdown", methods=["GET"])
def match_comp_breakdown(mid):
    auth(FINANCE_READ)
    match = V.lookup_or_404(db.matches, mid)
    carrier = db.carriers.get(match["carrier_id"])
    prior = carrier["prior_deliveries"] if carrier else 0
    addon = _match_multiples_addon(match)
    breakdown = carrier_comp_breakdown(match["proposed_carrier_comp_cents"], prior, addon)
    return success(breakdown)


@app.route("/matches/<mid>/counter", methods=["POST"])
def match_counter(mid):
    auth(["CaseManager"])
    match = V.lookup_or_404(db.matches, mid)
    body = V.get_json_body()
    proposed = V.require_int_cents(body, "proposed_carrier_comp_cents")
    expected = V.require_int(body, "expected_match_version")
    if match["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Match not PROPOSED")
    if expected != match["version"]:
        raise err(ERR_STALE_VERSION, "expected_match_version stale")
    match["status"] = "COUNTERED"
    match["proposed_carrier_comp_cents"] = proposed
    touch(match)
    return success(S.ser_match(match))


@app.route("/matches/<mid>/re-propose", methods=["POST"])
def match_re_propose(mid):
    auth(["CaseManager"])
    match = V.lookup_or_404(db.matches, mid)
    body = V.get_json_body()
    proposed = V.require_int_cents(body, "proposed_carrier_comp_cents")
    expected = V.require_int(body, "expected_match_version")
    if match["status"] != "COUNTERED":
        raise err(ERR_INVALID_STATE, "Match not COUNTERED")
    if expected != match["version"]:
        raise err(ERR_STALE_VERSION, "expected_match_version stale")
    match["status"] = "PROPOSED"
    match["offer_round"] += 1
    match["proposed_carrier_comp_cents"] = proposed
    touch(match)
    return success(S.ser_match(match))


@app.route("/matches/<mid>/accept", methods=["POST"])
def match_accept(mid):
    auth(["CaseManager"])
    match = V.lookup_or_404(db.matches, mid)
    body = V.get_json_body()
    expected = V.require_int(body, "expected_match_version")
    if match["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Match not PROPOSED")
    # clearance gate (business) before OCC per PRD §3.10: OCC in state category
    # after existence and basic state validity; clearance is a business rule.
    # PRD §2.7 lists version equality among accept requirements; §3.10 pins OCC
    # in the state category, evaluated before business rules. So check OCC first.
    if expected != match["version"]:
        raise err(ERR_STALE_VERSION, "expected_match_version stale")
    ip = db.intended_parents.get(match["intended_parent_id"])
    carrier = db.carriers.get(match["carrier_id"])
    if not ip or ip["intake_status"] != "CLEARED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "IntendedParent not CLEARED")
    if not carrier or carrier["intake_status"] != "CLEARED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "Carrier not CLEARED")
    if match["donor_id"] is not None:
        donor = db.egg_donors.get(match["donor_id"])
        if not donor or donor["intake_status"] != "CLEARED":
            raise err(ERR_PSYCH_CLEARANCE_MISSING, "Donor not CLEARED")
    carrier["base_compensation_cents"] = match["proposed_carrier_comp_cents"]
    touch(carrier)
    match["status"] = "ACCEPTED"
    touch(match)
    return success(S.ser_match(match))


@app.route("/matches/<mid>/psych-clear", methods=["POST"])
def match_psych_clear(mid):
    auth(["Screener"])
    match = V.lookup_or_404(db.matches, mid)
    if match["status"] != "ACCEPTED":
        raise err(ERR_INVALID_STATE, "Match not ACCEPTED")
    ip = db.intended_parents.get(match["intended_parent_id"])
    carrier = db.carriers.get(match["carrier_id"])
    if not ip or ip["psych_clearance"] != "PASSED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "IntendedParent psych not PASSED")
    if not carrier or carrier["psych_clearance"] != "PASSED":
        raise err(ERR_PSYCH_CLEARANCE_MISSING, "Carrier psych not PASSED")
    match["status"] = "PSYCH_CLEARED"
    touch(match)
    return success(S.ser_match(match))


@app.route("/matches/<mid>/void", methods=["POST"])
def match_void(mid):
    auth(["CaseManager"])
    match = V.lookup_or_404(db.matches, mid)
    if match["status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED", "PSYCH_CLEARED"):
        raise err(ERR_INVALID_STATE, "Match not voidable")
    # cascade hop 1: void linked non-VOID contract (any non-VOID status; PRD §3.4)
    for c in db.contracts.values():
        if c["match_id"] == match["id"] and c["status"] != "VOID":
            c["status"] = "VOID"
            touch(c)
            # cascade hop 2: freeze linked journey's open escrow
            _freeze_escrow_for_contract(c)
    match["status"] = "VOID"
    touch(match)
    return success(S.ser_match(match))


def _freeze_escrow_for_contract(contract):
    for j in db.journeys.values():
        if j["match_id"] == contract["match_id"]:
            escrow = escrow_for_journey(j["id"])
            freeze_escrow_if_open(escrow)


# ===========================================================================
# Contracts
# ===========================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    auth(["CaseManager"])
    body = V.get_json_body()
    match_id = V.require_string(body, "match_id")
    match = V.lookup_or_404(db.matches, match_id)
    obj = {
        "match_id": match_id,
        "status": "DRAFTED",
        "ip_signed_at": None,
        "cooling_off_days": 3,
    }
    stamp_create(obj)
    db.contracts[obj["id"]] = obj
    return success(S.ser_contract(obj), status=201)


def _load_contract_with_ownership(cid, role, uid, require_owner):
    contract = V.lookup_or_404(db.contracts, cid)
    if require_owner:
        match = db.matches.get(contract["match_id"])
        if role == "IntendedParentActor":
            if not match or match["intended_parent_id"] != uid:
                raise err(ERR_FORBIDDEN, "Not the owning intended parent")
        elif role == "CarrierActor":
            if not match or match["carrier_id"] != uid:
                raise err(ERR_FORBIDDEN, "Not the owning carrier")
    return contract


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    uid, role = get_identity()
    require_roles(role, ["CaseManager", "Screener", "FinanceOfficer", "IntendedParentActor", "CarrierActor"])
    contract = V.lookup_or_404(db.contracts, cid)
    if role in ("IntendedParentActor", "CarrierActor"):
        match = db.matches.get(contract["match_id"])
        if role == "IntendedParentActor" and (not match or match["intended_parent_id"] != uid):
            raise err(ERR_FORBIDDEN, "Not the owning intended parent")
        if role == "CarrierActor" and (not match or match["carrier_id"] != uid):
            raise err(ERR_FORBIDDEN, "Not the owning carrier")
    return success(S.ser_contract(contract))


@app.route("/contracts", methods=["GET"])
def list_contracts():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.contracts.values())
    for key in ("match_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_contract(o) for o in page], limit, offset, total)


@app.route("/contracts/<cid>/ip-sign", methods=["POST"])
def contract_ip_sign(cid):
    uid, role = get_identity()
    require_roles(role, ["IntendedParentActor"])
    contract = V.lookup_or_404(db.contracts, cid)
    match = db.matches.get(contract["match_id"])
    if not match or match["intended_parent_id"] != uid:
        raise err(ERR_FORBIDDEN, "Not the owning intended parent")
    if contract["status"] != "DRAFTED":
        raise err(ERR_INVALID_STATE, "Contract not DRAFTED")
    if not match or match["status"] != "PSYCH_CLEARED":
        raise err(ERR_INVALID_STATE, "Match not PSYCH_CLEARED")
    contract["status"] = "IP_SIGNED"
    contract["ip_signed_at"] = format_iso8601(clock.now())
    touch(contract)
    return success(S.ser_contract(contract))


@app.route("/contracts/<cid>/carrier-sign", methods=["POST"])
def contract_carrier_sign(cid):
    uid, role = get_identity()
    require_roles(role, ["CarrierActor"])
    contract = V.lookup_or_404(db.contracts, cid)
    match = db.matches.get(contract["match_id"])
    if not match or match["carrier_id"] != uid:
        raise err(ERR_FORBIDDEN, "Not the owning carrier")
    if contract["status"] != "IP_SIGNED":
        raise err(ERR_INVALID_STATE, "Contract not IP_SIGNED")
    signed_at = parse_iso8601(contract["ip_signed_at"])
    window_end = signed_at + timedelta(days=contract["cooling_off_days"])
    if clock.now() < window_end:
        raise err(ERR_COOLING_OFF_ACTIVE, "Cooling-off window has not elapsed")
    contract["status"] = "EXECUTED"
    touch(contract)
    return success(S.ser_contract(contract))


@app.route("/contracts/<cid>/void", methods=["POST"])
def contract_void(cid):
    auth(["CaseManager"])
    contract = V.lookup_or_404(db.contracts, cid)
    if contract["status"] not in ("DRAFTED", "IP_SIGNED"):
        raise err(ERR_INVALID_STATE, "Contract not voidable")
    contract["status"] = "VOID"
    touch(contract)
    _freeze_escrow_for_contract(contract)
    return success(S.ser_contract(contract))


# ===========================================================================
# Journeys
# ===========================================================================
@app.route("/journeys", methods=["POST"])
def create_journey():
    auth(["CaseManager"])
    body = V.get_json_body()
    match_id = V.require_string(body, "match_id")
    match = V.lookup_or_404(db.matches, match_id)
    # precondition: match PSYCH_CLEARED and its contract EXECUTED
    contract = None
    for c in db.contracts.values():
        if c["match_id"] == match_id and c["status"] == "EXECUTED":
            contract = c
            break
    if match["status"] != "PSYCH_CLEARED" or contract is None:
        raise err(ERR_JOURNEY_PRECONDITION, "Match must be PSYCH_CLEARED with an EXECUTED contract")
    journey = {
        "match_id": match_id,
        "status": "ACTIVE",
        "parentage_order_status": "NOT_FILED",
    }
    stamp_create(journey)
    db.journeys[journey["id"]] = journey
    # auto-open escrow account (cascade)
    escrow = {
        "journey_id": journey["id"],
        "deposited_cents": 0,
        "disbursed_cents": 0,
        "reserved_cents": 0,
        "status": "OPEN",
    }
    stamp_create(escrow)
    db.escrow_accounts[escrow["id"]] = escrow
    return success(S.ser_journey(journey), status=201)


@app.route("/journeys/<jid>", methods=["GET"])
def get_journey(jid):
    auth(READ_ROLES)
    obj = V.lookup_or_404(db.journeys, jid)
    return success(S.ser_journey(obj))


@app.route("/journeys", methods=["GET"])
def list_journeys():
    auth(READ_ROLES)
    limit, offset = V.parse_pagination()
    items = list(db.journeys.values())
    for key in ("match_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_journey(o) for o in page], limit, offset, total)


@app.route("/journeys/<jid>/hold", methods=["POST"])
def journey_hold(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    if j["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Journey not ACTIVE")
    j["status"] = "ON_HOLD"
    touch(j)
    return success(S.ser_journey(j))


@app.route("/journeys/<jid>/resume", methods=["POST"])
def journey_resume(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    if j["status"] != "ON_HOLD":
        raise err(ERR_INVALID_STATE, "Journey not ON_HOLD")
    j["status"] = "ACTIVE"
    touch(j)
    return success(S.ser_journey(j))


@app.route("/journeys/<jid>/complete", methods=["POST"])
def journey_complete(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    if j["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Journey not ACTIVE")
    birth_achieved = any(
        m["journey_id"] == jid and m["milestone_type"] == "BIRTH" and m["status"] == "ACHIEVED"
        for m in db.milestones.values()
    )
    if not birth_achieved:
        raise err(ERR_INVALID_STATE, "BIRTH milestone not ACHIEVED")
    if j["parentage_order_status"] != "GRANTED":
        raise err(ERR_INVALID_STATE, "parentage_order_status not GRANTED")
    j["status"] = "COMPLETED"
    touch(j)
    return success(S.ser_journey(j))


@app.route("/journeys/<jid>/terminate", methods=["POST"])
def journey_terminate(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    if j["status"] not in ("ACTIVE", "ON_HOLD"):
        raise err(ERR_INVALID_STATE, "Journey not terminable")
    j["status"] = "TERMINATED"
    touch(j)
    freeze_escrow_if_open(escrow_for_journey(jid))
    return success(S.ser_journey(j))


@app.route("/journeys/<jid>/parentage/file", methods=["POST"])
def journey_parentage_file(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    if j["parentage_order_status"] != "NOT_FILED":
        raise err(ERR_INVALID_STATE, "parentage_order_status not NOT_FILED")
    match = db.matches.get(j["match_id"])
    ip = db.intended_parents.get(match["intended_parent_id"]) if match else None
    if ip and ip["state_code"] in PARENTAGE_HOSTILE:
        raise err(ERR_PARENTAGE_JURISDICTION_BLOCKED, "State forbids pre-birth parentage orders")
    j["parentage_order_status"] = "FILED"
    touch(j)
    return success(S.ser_journey(j))


@app.route("/journeys/<jid>/parentage/decide", methods=["POST"])
def journey_parentage_decide(jid):
    auth(["CaseManager"])
    j = V.lookup_or_404(db.journeys, jid)
    body = V.get_json_body()
    decision = V.require_enum(body, "decision", {"GRANTED", "DENIED"})
    if j["parentage_order_status"] != "FILED":
        raise err(ERR_INVALID_STATE, "parentage_order_status not FILED")
    j["parentage_order_status"] = decision
    touch(j)
    return success(S.ser_journey(j))


# ===========================================================================
# Milestones (under Journey)
# ===========================================================================
@app.route("/journeys/<jid>/milestones", methods=["POST"])
def create_milestone(jid):
    auth(["CaseManager"])
    journey = V.lookup_or_404(db.journeys, jid)
    body = V.get_json_body()
    mtype = V.require_enum(body, "milestone_type", {"EMBRYO_TRANSFER", "HEARTBEAT", "BIRTH"})
    scheduled_utc_raw = V.require_string(body, "scheduled_utc")
    try:
        parse_iso8601(scheduled_utc_raw)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "scheduled_utc must be ISO 8601 UTC")
    for m in db.milestones.values():
        if m["journey_id"] == jid and m["milestone_type"] == mtype:
            raise err(ERR_DUPLICATE_MILESTONE, "Milestone of this type already exists")
    obj = {
        "journey_id": jid,
        "milestone_type": mtype,
        "status": "SCHEDULED",
        "scheduled_utc": scheduled_utc_raw,
        "achieved_utc": None,
    }
    stamp_create(obj)
    db.milestones[obj["id"]] = obj
    return success(S.ser_milestone(obj), status=201)


@app.route("/journeys/<jid>/milestones", methods=["GET"])
def list_milestones(jid):
    auth(READ_ROLES)
    V.lookup_or_404(db.journeys, jid)
    limit, offset = V.parse_pagination()
    items = [m for m in db.milestones.values() if m["journey_id"] == jid]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_milestone(o) for o in page], limit, offset, total)


@app.route("/journeys/<jid>/milestones/<mid>/achieve", methods=["POST"])
def milestone_achieve(jid, mid):
    auth(["CaseManager"])
    journey = V.lookup_or_404(db.journeys, jid)
    milestone = V.lookup_or_404(db.milestones, mid)
    if milestone["journey_id"] != jid:
        raise err(ERR_NOT_FOUND, "Milestone not under this journey")
    if milestone["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Milestone not SCHEDULED")
    if journey["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Journey not ACTIVE")
    achieved = achieved_milestone_types(jid)
    if milestone["milestone_type"] == "HEARTBEAT" and "EMBRYO_TRANSFER" not in achieved:
        raise err(ERR_MILESTONE_ORDER_VIOLATION, "EMBRYO_TRANSFER must be ACHIEVED first")
    if milestone["milestone_type"] == "BIRTH" and "HEARTBEAT" not in achieved:
        raise err(ERR_MILESTONE_ORDER_VIOLATION, "HEARTBEAT must be ACHIEVED first")
    milestone["status"] = "ACHIEVED"
    milestone["achieved_utc"] = format_iso8601(clock.now())
    touch(milestone)
    # recompute journey current_phase -> phase is derived on read, but the
    # mutation must bump the journey's version/updated_at (PRD §2.4).
    touch(journey)
    return success(S.ser_milestone(milestone))


@app.route("/journeys/<jid>/milestones/<mid>/fail", methods=["POST"])
def milestone_fail(jid, mid):
    auth(["CaseManager"])
    V.lookup_or_404(db.journeys, jid)
    milestone = V.lookup_or_404(db.milestones, mid)
    if milestone["journey_id"] != jid:
        raise err(ERR_NOT_FOUND, "Milestone not under this journey")
    if milestone["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Milestone not SCHEDULED")
    milestone["status"] = "FAILED"
    touch(milestone)
    return success(S.ser_milestone(milestone))


# ===========================================================================
# Compensation Schedule (under Journey)
# ===========================================================================
@app.route("/journeys/<jid>/comp-schedule", methods=["POST"])
def create_comp_schedule(jid):
    auth(["CaseManager", "FinanceOfficer"])
    V.lookup_or_404(db.journeys, jid)
    body = V.get_json_body()
    trigger = V.require_enum(body, "trigger_milestone_type", {"EMBRYO_TRANSFER", "HEARTBEAT", "BIRTH"})
    recipient = V.require_enum(body, "recipient", {"CARRIER", "DONOR"})
    amount = V.require_int_cents(body, "amount_cents")
    obj = {
        "journey_id": jid,
        "trigger_milestone_type": trigger,
        "recipient": recipient,
        "amount_cents": amount,
    }
    stamp_create(obj)
    db.comp_schedules[obj["id"]] = obj
    return success(S.ser_comp_schedule(obj), status=201)


@app.route("/journeys/<jid>/comp-schedule", methods=["GET"])
def list_comp_schedule(jid):
    auth(FINANCE_READ)
    V.lookup_or_404(db.journeys, jid)
    limit, offset = V.parse_pagination()
    items = [c for c in db.comp_schedules.values() if c["journey_id"] == jid]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_comp_schedule(o) for o in page], limit, offset, total)


@app.route("/comp-schedule/<sid>", methods=["GET"])
def get_comp_schedule(sid):
    auth(FINANCE_READ)
    obj = V.lookup_or_404(db.comp_schedules, sid)
    return success(S.ser_comp_schedule(obj))


# ===========================================================================
# Escrow Accounts
# ===========================================================================
@app.route("/escrow-accounts/<eid>", methods=["GET"])
def get_escrow(eid):
    auth(FINANCE_READ)
    obj = V.lookup_or_404(db.escrow_accounts, eid)
    return success(S.ser_escrow(obj))


@app.route("/escrow-accounts", methods=["GET"])
def list_escrow():
    auth(FINANCE_READ)
    limit, offset = V.parse_pagination()
    items = list(db.escrow_accounts.values())
    val = request.args.get("journey_id")
    if val is not None:
        items = [o for o in items if o["journey_id"] == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_escrow(o) for o in page], limit, offset, total)


@app.route("/escrow-accounts/<eid>/summary", methods=["GET"])
def escrow_summary(eid):
    auth(FINANCE_READ)
    escrow = V.lookup_or_404(db.escrow_accounts, eid)
    available = S.compute_available(escrow)
    journey_id = escrow["journey_id"]
    # milestones on the journey, indexed by type
    milestones_by_type = {}
    for m in db.milestones.values():
        if m["journey_id"] == journey_id:
            milestones_by_type[m["milestone_type"]] = m
    schedule_lines = [c for c in db.comp_schedules.values() if c["journey_id"] == journey_id]

    # disbursable_now: gated chronological
    achieved = [m for m in milestones_by_type.values() if m["status"] == "ACHIEVED"]
    achieved.sort(key=lambda m: (m["achieved_utc"], m["created_at"], m["_seq"]))
    disbursable_now = 0
    for m in achieved:
        lines = [
            c for c in schedule_lines if c["trigger_milestone_type"] == m["milestone_type"]
        ]
        lines.sort(key=lambda c: (c["created_at"], c["_seq"]))
        for line in lines:
            if disbursable_now + line["amount_cents"] <= available:
                disbursable_now += line["amount_cents"]

    # projected_liability: sum of all lines whose trigger milestone is not FAILED
    projected = 0
    for line in schedule_lines:
        m = milestones_by_type.get(line["trigger_milestone_type"])
        if m is None or m["status"] != "FAILED":
            projected += line["amount_cents"]
    funding_shortfall = max(0, projected - available)

    return success(
        {
            "available_cents": available,
            "disbursable_now_cents": disbursable_now,
            "projected_liability_cents": projected,
            "funding_shortfall_cents": funding_shortfall,
        }
    )


@app.route("/escrow-accounts/<eid>/deposit", methods=["POST"])
def escrow_deposit(eid):
    uid, role = get_identity()
    require_roles(role, ["IntendedParentActor"])
    escrow = V.lookup_or_404(db.escrow_accounts, eid)
    body = V.get_json_body()
    amount = V.require_int_cents(body, "amount_cents")
    expected = V.require_int(body, "expected_escrow_version")
    journey = db.journeys.get(escrow["journey_id"])
    match = db.matches.get(journey["match_id"]) if journey else None
    ip = db.intended_parents.get(match["intended_parent_id"]) if match else None
    # ownership: IntendedParentActor acting on their own escrow
    if not ip or match["intended_parent_id"] != uid:
        raise err(ERR_FORBIDDEN, "Not the owning intended parent")
    if escrow["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escrow not OPEN")
    if expected != escrow["version"]:
        raise err(ERR_STALE_VERSION, "expected_escrow_version stale")
    if escrow["deposited_cents"] + amount > ip["budget_cents"]:
        raise err(ERR_BUDGET_EXCEEDED, "Deposit exceeds IntendedParent budget")
    escrow["deposited_cents"] += amount
    touch(escrow)
    return success(S.ser_escrow(escrow))


@app.route("/escrow-accounts/<eid>/freeze", methods=["POST"])
def escrow_freeze(eid):
    auth(["FinanceOfficer"])
    escrow = V.lookup_or_404(db.escrow_accounts, eid)
    if escrow["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escrow not OPEN")
    escrow["status"] = "FROZEN"
    touch(escrow)
    return success(S.ser_escrow(escrow))


@app.route("/escrow-accounts/<eid>/unfreeze", methods=["POST"])
def escrow_unfreeze(eid):
    auth(["FinanceOfficer"])
    escrow = V.lookup_or_404(db.escrow_accounts, eid)
    if escrow["status"] != "FROZEN":
        raise err(ERR_INVALID_STATE, "Escrow not FROZEN")
    if journey_has_void_contract(escrow["journey_id"]):
        raise err(ERR_INVALID_STATE, "Linked contract is VOID; cannot unfreeze")
    escrow["status"] = "OPEN"
    touch(escrow)
    return success(S.ser_escrow(escrow))


@app.route("/escrow-accounts/<eid>/close", methods=["POST"])
def escrow_close(eid):
    auth(["FinanceOfficer"])
    escrow = V.lookup_or_404(db.escrow_accounts, eid)
    if escrow["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escrow not OPEN")
    if escrow["reserved_cents"] != 0:
        raise err(ERR_INVALID_STATE, "reserved_cents must be 0 to close")
    journey = db.journeys.get(escrow["journey_id"])
    if not journey or journey["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Linked journey must be COMPLETED")
    escrow["status"] = "CLOSED"
    touch(escrow)
    return success(S.ser_escrow(escrow))


# ===========================================================================
# Disbursements (under Journey)
# ===========================================================================
@app.route("/journeys/<jid>/disbursements", methods=["POST"])
def create_disbursement(jid):
    auth(["CaseManager", "FinanceOfficer"])
    V.lookup_or_404(db.journeys, jid)
    body = V.get_json_body()
    schedule_id = V.require_string(body, "schedule_id")
    escrow_account_id = V.require_string(body, "escrow_account_id")
    schedule = V.lookup_or_404(db.comp_schedules, schedule_id)
    escrow = V.lookup_or_404(db.escrow_accounts, escrow_account_id)
    obj = {
        "journey_id": jid,
        "schedule_id": schedule_id,
        "escrow_account_id": escrow_account_id,
        "amount_cents": schedule["amount_cents"],
        "status": "REQUESTED",
        "approved_by_user_id": None,
    }
    stamp_create(obj)
    db.disbursements[obj["id"]] = obj
    return success(S.ser_disbursement(obj), status=201)


@app.route("/journeys/<jid>/disbursements", methods=["GET"])
def list_disbursements_for_journey(jid):
    auth(FINANCE_READ)
    V.lookup_or_404(db.journeys, jid)
    limit, offset = V.parse_pagination()
    items = [d for d in db.disbursements.values() if d["journey_id"] == jid]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_disbursement(o) for o in page], limit, offset, total)


def _load_disbursement(jid, did):
    V.lookup_or_404(db.journeys, jid)
    disb = V.lookup_or_404(db.disbursements, did)
    if disb["journey_id"] != jid:
        raise err(ERR_NOT_FOUND, "Disbursement not under this journey")
    return disb


@app.route("/journeys/<jid>/disbursements/<did>/approve", methods=["POST"])
def disbursement_approve(jid, did):
    uid, role = get_identity()
    require_roles(role, ["CaseManager"])
    disb = _load_disbursement(jid, did)
    if disb["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Disbursement not REQUESTED")
    schedule = db.comp_schedules.get(disb["schedule_id"])
    escrow = db.escrow_accounts.get(disb["escrow_account_id"])
    achieved = achieved_milestone_types(jid)
    if not schedule or schedule["trigger_milestone_type"] not in achieved:
        raise err(ERR_MILESTONE_GATE_NOT_MET, "Trigger milestone not ACHIEVED")
    if not escrow or escrow["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escrow not OPEN")
    amount = disb["amount_cents"]
    if amount > S.compute_available(escrow):
        raise err(ERR_INSUFFICIENT_ESCROW, "Amount exceeds available escrow")
    disb["status"] = "APPROVED"
    disb["approved_by_user_id"] = uid
    escrow["reserved_cents"] += amount
    touch(escrow)
    touch(disb)
    return success(S.ser_disbursement(disb))


@app.route("/journeys/<jid>/disbursements/<did>/release", methods=["POST"])
def disbursement_release(jid, did):
    uid, role = get_identity()
    require_roles(role, ["FinanceOfficer"])
    disb = _load_disbursement(jid, did)
    if disb["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Disbursement not APPROVED")
    escrow = db.escrow_accounts.get(disb["escrow_account_id"])
    if not escrow or escrow["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escrow not OPEN")
    if uid == disb["approved_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Releaser must differ from approver")
    amount = disb["amount_cents"]
    escrow["reserved_cents"] -= amount
    escrow["disbursed_cents"] += amount
    touch(escrow)
    disb["status"] = "RELEASED"
    touch(disb)
    return success(S.ser_disbursement(disb))


@app.route("/journeys/<jid>/disbursements/<did>/reject", methods=["POST"])
def disbursement_reject(jid, did):
    auth(["CaseManager"])
    disb = _load_disbursement(jid, did)
    if disb["status"] not in ("REQUESTED", "APPROVED"):
        raise err(ERR_INVALID_STATE, "Disbursement not REQUESTED or APPROVED")
    if disb["status"] == "APPROVED":
        escrow = db.escrow_accounts.get(disb["escrow_account_id"])
        if escrow:
            escrow["reserved_cents"] -= disb["amount_cents"]
            touch(escrow)
    disb["status"] = "REJECTED"
    touch(disb)
    return success(S.ser_disbursement(disb))


@app.route("/disbursements/<did>", methods=["GET"])
def get_disbursement(did):
    auth(FINANCE_READ)
    obj = V.lookup_or_404(db.disbursements, did)
    return success(S.ser_disbursement(obj))


@app.route("/disbursements", methods=["GET"])
def list_disbursements():
    auth(FINANCE_READ)
    limit, offset = V.parse_pagination()
    items = list(db.disbursements.values())
    for key in ("journey_id", "schedule_id", "escrow_account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return success_list([S.ser_disbursement(o) for o in page], limit, offset, total)


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth(["CaseManager", "FinanceOfficer", "Screener"])
    body = V.get_json_body()
    to_iso = V.require_string(body, "to_iso8601")
    try:
        dt = parse_iso8601(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601 UTC")
    clock.set(dt)
    return success({"current_utc": format_iso8601(clock.now())})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Use a threaded WSGI server with a large listen backlog. Under the
    # benchmark's 8x-concurrent per-test-server sweep the default socket
    # backlog saturates and Werkzeug drops connections mid-request (surfacing
    # to clients as BadStatusLine / ConnectionError). A larger request queue
    # plus daemon threads keeps every incoming connection served.
    from werkzeug.serving import make_server, ThreadedWSGIServer

    ThreadedWSGIServer.request_queue_size = 256
    ThreadedWSGIServer.daemon_threads = True
    server = make_server("0.0.0.0", port, app, threaded=True)
    server.request_queue_size = 256
    server.daemon_threads = True
    server.serve_forever()
