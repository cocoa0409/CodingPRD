"""Claim intake, investigation, engineering assessment, routing and
adjudication (PRD 3.6, 3.7)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err
from middleware import (ROLE_ADJUSTER, ROLE_BUILDER, ROLE_COMPLIANCE,
                        ROLE_HOMEOWNER, ROLE_UNDERWRITER, endpoint)

bp = Blueprint("claims", __name__)

ALL_READERS = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_BUILDER,
               ROLE_HOMEOWNER)
INTAKE_CANDIDATE_STATES = ("OPEN", "LIMIT_EXHAUSTED")


def _bad_claim_state(claim):
    return err("ERR_INVALID_CLAIM_STATE", "claim is in status '%s'" % claim["status"])


def _require_builder_principal(claim, user_id):
    policy = db.policies[claim["policy_id"]]
    if policy["builder_id"] != user_id:
        raise err("ERR_NOT_BUILDER_PRINCIPAL",
                  "X-User-ID is not the builder behind this claim")
    return policy


@bp.post("/claims")
@endpoint(ROLE_HOMEOWNER)
def file_claim(user_id, role):
    body = v.body()
    raw_policy_id = body.get("policy_id")
    policy = None
    if isinstance(raw_policy_id, str):
        policy = store.get_policy(raw_policy_id)
        if policy["current_owner_id"] != user_id:
            raise err("ERR_NOT_POLICY_OWNER",
                      "X-User-ID is not the current owner of this policy")
    policy_id = v.req_str(body, "policy_id")
    coverage_type = v.req_enum(body, "coverage_type", calc.COVERAGE_TYPES)
    defect_category = v.req_enum(body, "defect_category", calc.DEFECT_CATEGORIES)
    damage_description = v.req_str(body, "damage_description", 1, 1000)
    claimed_amount_cents = v.req_int(body, "claimed_amount_cents", 1)
    if policy is None:
        policy = store.get_policy(policy_id)
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE",
                  "claims may only be filed against an ACTIVE policy")

    reported = v.fmt_date(db.clock_date())
    candidates = [t for t in store.terms_of_policy(policy["id"])
                  if t["status"] in INTAKE_CANDIDATE_STATES
                  and t["coverage_type"] == coverage_type
                  and t["start_date"] <= reported <= t["end_date"]]
    if not candidates:
        raise err("ERR_NO_COVERAGE_IN_FORCE",
                  "no %s coverage term is in force on %s" % (coverage_type, reported))
    candidates.sort(key=store.term_sort_key)
    term = candidates[0]

    claim = {
        "policy_id": policy["id"],
        "coverage_term_id": term["id"],
        "filed_by_owner_id": user_id,
        "coverage_type": coverage_type,
        "defect_category": defect_category,
        "damage_description": damage_description,
        "claimed_amount_cents": claimed_amount_cents,
        "reported_date": reported,
        "obligor": ("BUILDER" if reported <= policy["builder_obligation_end_date"]
                    else "INSURER"),
        "substantiation_ratio": None,
        "designated_structural": False,
        "gross_adjusted_cents": 0,
        "deductible_applied_cents": 0,
        "betterment_cents": 0,
        "net_payable_cents": 0,
        "reserve_cents": 0,
        "paid_cents": 0,
        "released_cents": 0,
        "incurred_authorized_cents": 0,
        "adjudicated_by_user_id": None,
        "denial_date": None,
        "escalation_deadline_date": None,
        "status": "SUBMITTED",
    }
    db.stamp_create(claim)
    db.claims[claim["id"]] = claim
    return response.object_response(db.public(claim), 201)


@bp.post("/claims/<claim_id>/investigation")
@endpoint(ROLE_ADJUSTER)
def investigate_claim(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    ratio = v.req_rate(v.body(), "substantiation_ratio", 0, 1, 2)
    if claim["status"] != "SUBMITTED":
        raise _bad_claim_state(claim)
    claim["substantiation_ratio"] = ratio
    claim["gross_adjusted_cents"] = calc.gross_adjusted(
        claim["claimed_amount_cents"], ratio)
    claim["status"] = "UNDER_INVESTIGATION"
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.post("/claims/<claim_id>/structural-assessments")
@endpoint(ROLE_ADJUSTER)
def file_assessment(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    body = v.body()
    elements = v.req_string_array(body, "affected_elements", calc.ALL_ELEMENTS, 8)
    deflection = v.req_rate(body, "deflection_ratio", 0, "0.5000", 4)
    load_bearing = v.req_bool(body, "load_bearing_affected")
    verdict = calc.structural_designation(elements, deflection, load_bearing)
    row = {
        "claim_id": claim["id"],
        "affected_elements": elements,
        "deflection_ratio": deflection,
        "load_bearing_affected": load_bearing,
        "assessed_by_user_id": user_id,
        "assessment_date": v.fmt_date(db.clock_date()),
        "designated_structural": verdict,
    }
    db.stamp_create(row, versioned=False)
    db.assessments[row["id"]] = row
    if verdict:
        claim["designated_structural"] = True
    db.mark(claim)
    return response.object_response(db.public(row), 201)


@bp.post("/claims/<claim_id>/obligation-routing")
@endpoint(ROLE_ADJUSTER)
def route_obligation(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    v.opt_str(v.body(), "routing_note", non_blank=False)
    if claim["status"] != "UNDER_INVESTIGATION" or claim["substantiation_ratio"] is None:
        raise _bad_claim_state(claim)
    builder = store.builder_of_claim(claim)
    if claim["obligor"] == "BUILDER":
        if builder is not None and builder["underwriting_status"] == "DEFAULTED":
            raise err("ERR_BUILDER_DEFAULTED",
                      "a defaulted builder cannot be sent an obligation notice")
        claim["status"] = "BUILDER_OBLIGATION_NOTICE"
        store.apply_waterfall(claim, "builder")
    else:
        claim["status"] = "INSURER_ADJUDICATION"
        store.apply_waterfall(claim, "insurer")
        store.establish_reserve(claim)
        store.recompute_builder(builder)
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.post("/claims/<claim_id>/builder-response")
@endpoint(ROLE_BUILDER)
def builder_response(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    _require_builder_principal(claim, user_id)
    body = v.body()
    answer = v.req_enum(body, "response", ("ACCEPT_OBLIGATION", "REFUSE_OBLIGATION"))
    v.opt_str(body, "response_note", non_blank=False)
    if claim["status"] != "BUILDER_OBLIGATION_NOTICE":
        raise _bad_claim_state(claim)
    if answer == "ACCEPT_OBLIGATION":
        claim["status"] = "BUILDER_REPAIR_ACCEPTED"
    else:
        store.join_insurer_arm(claim)
        store.recompute_builder(store.builder_of_claim(claim))
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.post("/claims/<claim_id>/repair-completion")
@endpoint(ROLE_BUILDER)
def repair_completion(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    _require_builder_principal(claim, user_id)
    v.req_date(v.body(), "completion_date")
    if claim["status"] != "BUILDER_REPAIR_ACCEPTED":
        raise _bad_claim_state(claim)
    claim["status"] = "CLOSED_REPAIRED"
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.post("/claims/<claim_id>/adjudication")
@endpoint(ROLE_ADJUSTER)
def adjudicate_claim(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", ("APPROVE", "DENY"))
    v.opt_str(body, "adjudication_note", non_blank=False)
    if claim["status"] != "INSURER_ADJUDICATION":
        raise _bad_claim_state(claim)
    term = store.term_of_claim(claim)
    if outcome == "APPROVE" and (term is None or term["status"] != "OPEN"):
        raise err("ERR_COVERAGE_LIMIT_EXHAUSTED",
                  "the claim's coverage term is not OPEN")
    if (claim["defect_category"] in ("STRUCTURAL_CRACKING", "LOAD_BEARING_FAILURE")
            and not store.assessments_of_claim(claim["id"])):
        raise err("ERR_STRUCTURAL_ASSESSMENT_REQUIRED",
                  "a structural allegation requires an engineering assessment")
    claim["adjudicated_by_user_id"] = user_id
    if outcome == "APPROVE":
        claim["status"] = "APPROVED"
    else:
        claim["status"] = "DENIED"
        denial = db.clock_date()
        claim["denial_date"] = v.fmt_date(denial)
        claim["escalation_deadline_date"] = v.fmt_date(
            store.deadline_from(denial, calc.MEDIATION_WINDOW_DAYS))
        store.release_reserve(claim, user_id)
        store.recompute_builder(store.builder_of_claim(claim))
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.get("/claims/<claim_id>")
@endpoint(*ALL_READERS)
def read_claim(claim_id, user_id, role):
    return response.object_response(db.public(store.get_claim(claim_id)))


@bp.get("/claims")
@endpoint(*ALL_READERS)
def list_claims(user_id, role):
    rows = store.all_rows(db.claims)
    rows = listing.eq_filter(rows, "policy_id")
    rows = listing.eq_filter(rows, "coverage_term_id")
    rows = listing.eq_filter(rows, "filed_by_owner_id")
    rows = listing.eq_filter(rows, "status")
    rows = listing.eq_filter(rows, "obligor")
    return response.paginate(rows)


@bp.get("/claims/<claim_id>/structural-assessments")
@endpoint(*ALL_READERS)
def list_assessments(claim_id, user_id, role):
    store.get_claim(claim_id)
    rows = store.assessments_of_claim(claim_id)
    rows = listing.bool_filter(rows, "designated_structural")
    return response.paginate(rows)
