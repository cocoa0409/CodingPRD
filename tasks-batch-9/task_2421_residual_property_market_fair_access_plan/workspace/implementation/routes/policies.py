"""Binding, renewal, cancellation and take-out offer creation
(PRD 3.6 / 3.7 / 3.8)."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail
from middleware import own, require
from response import created, ok
from routes.common import matches, page
from services import inspection as inspection_svc
from services import policy as policy_svc
from services import ratefiling as rate_svc
from services import zone as zone_svc
from services.constants import (
    CLIENT_CANCEL_REASONS,
    COVERAGE_STATUSES,
    DEPOPULATION_STATUSES,
    INSPECTION_VALIDITY_DAYS,
    MAX_DWELLING_LIMIT_CENTS,
    OFFER_PREMIUM_CAP_MULTIPLIER,
    POLICY_TERM_DAYS,
)
from util import D, add_days, date_of, parse_instant, rhu_cents
from validate import (
    body,
    filter_enum,
    filter_string,
    opt_int,
    pagination,
    req_bool,
    req_date,
    req_enum,
    req_instant,
    req_int,
    req_string,
    store_instant,
)

bp = Blueprint("policies", __name__)


def _zone_posture_gates(zone, construction_type, rating_score):
    """Ladder rungs 25 and 26, shared by binding and renewal."""
    if zone["status"] == "CLOSED":
        fail("ERR_ZONE_CLOSED",
             "Territory %s is CLOSED to new exposure" % zone["code"])
    if zone["status"] == "RESTRICTED":
        minimum = zone["restricted_min_condition_score"]
        if (construction_type != "MASONRY"
                or rating_score is None
                or rating_score < minimum):
            fail("ERR_ZONE_RESTRICTED_INELIGIBLE",
                 "A RESTRICTED territory writes only MASONRY risks scoring at "
                 "least %s" % minimum)


def _headroom_gate(zone, exposure_value_cents):
    if (zone["aggregate_insured_value_cents"] + exposure_value_cents
            > zone["exposure_cap_cents"]):
        fail("ERR_ZONE_EXPOSURE_CAP_EXCEEDED",
             "Territory %s has insufficient exposure headroom" % zone["code"])


def _appointed(producer):
    if producer is None or producer["agreement_status"] != "APPOINTED":
        fail("ERR_PRODUCER_NOT_APPOINTED", "Producer is not APPOINTED")
    return producer


def _selected_filing(zone, peril_package, reference_date):
    filing = rate_svc.select_rate_filing(zone["id"], peril_package, reference_date)
    if filing is None:
        fail("ERR_NO_APPROVED_RATE",
             "No APPROVED rate filing covers this territory and package on %s"
             % reference_date)
    return filing


def _limit_gate(limit_cents, prop):
    if (limit_cents > MAX_DWELLING_LIMIT_CENTS
            or limit_cents > prop["replacement_cost_cents"]):
        fail("ERR_COVERAGE_LIMIT_EXCEEDED",
             "Dwelling limit exceeds the statutory ceiling or the property's "
             "replacement cost")


# --- binding --------------------------------------------------------------

@bp.post("/policies")
def bind_policy():
    caller = require("Underwriter")
    data = body()
    application_id = req_string(data, "application_id")
    effective_date = req_date(data, "effective_date")

    application = lookup.application(application_id)

    if application["status"] != "APPROVED_TO_BIND":
        fail("ERR_APPLICATION_NOT_BINDABLE",
             "Application status %s is not bindable" % application["status"])

    if application["eligibility_reviewer_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The underwriter who reviewed eligibility may not bind the policy")

    prop = db.properties[application["property_id"]]
    zone = zone_svc.zone_of_property(prop)
    chosen = inspection_svc.chosen_inspection(application["id"])
    rating_score = chosen["observed_condition_score"] if chosen else None

    _zone_posture_gates(zone, prop["construction_type"], rating_score)

    producer = _appointed(db.producers.get(application["producer_id"]))
    filing = _selected_filing(zone, application["requested_peril_package"],
                              db.today())

    if prop["occupancy"] == "VACANT":
        cured = False
        if chosen is not None:
            for requirement in inspection_svc.requirements_of(chosen["id"]):
                if (requirement["code"] == "VACANCY_CURE"
                        and requirement["status"] == "CLEARED"):
                    cured = True
                    break
        if not cured:
            fail("ERR_VACANT_PROPERTY_INELIGIBLE",
                 "A VACANT property needs a CLEARED VACANCY_CURE requirement")

    completed_on = date_of(chosen["completed_at"]) if chosen else None
    if completed_on is None or (db.today() - completed_on).days > INSPECTION_VALIDITY_DAYS:
        fail("ERR_INSPECTION_STALE",
             "The chosen inspection is older than %d days"
             % INSPECTION_VALIDITY_DAYS)

    deadline = parse_instant(application["bind_deadline_at"])
    if deadline is None or db.now() > deadline:
        fail("ERR_BIND_DEADLINE_PASSED", "The bind window has closed")

    expiration_date = add_days(effective_date, POLICY_TERM_DAYS)
    if policy_svc.conflicting_policy(prop["id"], effective_date, expiration_date):
        fail("ERR_POLICY_TERM_OVERLAP",
             "The requested term intersects an existing term on this property")

    limit_cents = application["requested_dwelling_limit_cents"]
    _headroom_gate(zone, limit_cents)

    policy = policy_svc.build_policy(
        application, prop, application["applicant_id"], producer, filing, zone,
        limit_cents, effective_date, rating_score,
        chosen["cleared_major_count"] if chosen else 0, rating_score)

    application["status"] = "BOUND"
    touch(application)
    return created(policy)


@bp.get("/policies/<policy_id>")
def read_policy(policy_id):
    require("Underwriter", "PlanAdmin", "Policyholder", "Producer",
            "MemberInsurerUser")
    return ok(lookup.policy(policy_id))


@bp.get("/policies")
def list_policies():
    require("Underwriter", "PlanAdmin", "MemberInsurerUser")
    limit, offset = pagination()
    filters = {
        "application_id": filter_string("application_id"),
        "property_id": filter_string("property_id"),
        "applicant_id": filter_string("applicant_id"),
        "producer_id": filter_string("producer_id"),
        "rate_filing_id": filter_string("rate_filing_id"),
        "predecessor_policy_id": filter_string("predecessor_policy_id"),
        "coverage_status": filter_enum("coverage_status", COVERAGE_STATUSES),
        "depopulation_status": filter_enum("depopulation_status",
                                           DEPOPULATION_STATUSES),
    }
    rows = [p for p in db.policies.values() if matches(p, filters)]
    return page(rows, limit, offset)


# --- cancellation ---------------------------------------------------------

@bp.post("/policies/<policy_id>/cancellation")
def cancel_policy(policy_id):
    require("Underwriter", "PlanAdmin")
    data = body()
    # TAKEOUT_ELECTION is server-only, so a client that supplies it fails rung 3.
    cancel_reason = req_enum(data, "cancel_reason", CLIENT_CANCEL_REASONS)
    cancel_date = req_date(data, "cancel_date")

    policy = lookup.policy(policy_id)
    acceptable = (policy["coverage_status"] == "IN_FORCE"
                  or (policy["coverage_status"] == "BOUND"
                      and cancel_reason == "PLAN_INITIATED"))
    if not acceptable:
        fail("ERR_POLICY_NOT_IN_FORCE",
             "Coverage status %s cannot be cancelled with reason %s"
             % (policy["coverage_status"], cancel_reason))

    policy_svc.terminate(policy, "CANCELLED", cancel_reason, cancel_date)
    return ok(policy)


# --- renewal --------------------------------------------------------------

@bp.post("/policies/<policy_id>/renewal")
def renew_policy(policy_id):
    require("Underwriter")
    data = body()
    effective_date = req_date(data, "effective_date")
    revised_limit = opt_int(data, "requested_dwelling_limit_cents", positive=True)

    predecessor = lookup.policy(policy_id)
    if predecessor["coverage_status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE",
             "Coverage status %s cannot be renewed" % predecessor["coverage_status"])

    prop = db.properties[predecessor["property_id"]]
    zone = zone_svc.zone_of_property(prop)
    rating_score = predecessor["condition_score_at_bind"]

    _zone_posture_gates(zone, prop["construction_type"], rating_score)
    producer = _appointed(db.producers.get(predecessor["producer_id"]))
    filing = _selected_filing(zone, predecessor["peril_package"], effective_date)

    limit_cents = (revised_limit if revised_limit is not None
                   else predecessor["dwelling_limit_cents"])
    _limit_gate(limit_cents, prop)

    expiration_date = add_days(effective_date, POLICY_TERM_DAYS)
    if policy_svc.conflicting_policy(prop["id"], effective_date, expiration_date):
        fail("ERR_POLICY_TERM_OVERLAP",
             "The successor term intersects an existing term on this property")

    _headroom_gate(zone, limit_cents)

    carried = {
        "id": predecessor["application_id"],
        "requested_peril_package": predecessor["peril_package"],
        "producer_id": predecessor["producer_id"],
    }
    successor = policy_svc.build_policy(
        carried, prop, predecessor["applicant_id"], producer, filing, zone,
        limit_cents, effective_date, rating_score, 0,
        predecessor["condition_score_at_bind"],
        predecessor_policy_id=predecessor["id"])
    return created(successor)


# --- take-out offer creation ---------------------------------------------

@bp.post("/policies/<policy_id>/takeout-offers")
def create_offer(policy_id):
    caller = require("MemberInsurerUser")
    data = body()
    member_insurer_id = req_string(data, "member_insurer_id")
    offered_premium_cents = req_int(data, "offered_premium_cents", positive=True)
    comparable_coverage_flag = req_bool(data, "comparable_coverage_flag")
    election_deadline_at = req_instant(data, "election_deadline_at")

    policy = lookup.policy(policy_id)
    member = lookup.member(member_insurer_id)
    own(member["id"] == caller.user_id,
        "An operator may only offer on behalf of its own carrier")

    if policy["coverage_status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE",
             "Coverage status %s cannot be taken out" % policy["coverage_status"])
    if policy["depopulation_status"] != "NOT_OFFERED":
        fail("ERR_OFFER_ALREADY_OUTSTANDING",
             "The policy already carries depopulation status %s"
             % policy["depopulation_status"])
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE",
             "Member status %s may not make take-out offers" % member["status"])

    cap = rhu_cents(D(policy["annual_premium_cents"]) * OFFER_PREMIUM_CAP_MULTIPLIER)
    if not comparable_coverage_flag or offered_premium_cents > cap:
        fail("ERR_OFFER_NOT_COMPARABLE",
             "The offer must attest comparable coverage and may not exceed %d cents"
             % cap)

    offer = new_record({
        "policy_id": policy["id"],
        "member_insurer_id": member["id"],
        "offered_premium_cents": offered_premium_cents,
        "comparable_coverage_flag": comparable_coverage_flag,
        "election_deadline_at": store_instant(election_deadline_at),
        "status": "OUTSTANDING",
        "elected_at": None,
        "withdrawal_reason": None,
        "credit_units_granted": 0,
    })
    db.takeout_offers[offer["id"]] = offer

    policy["depopulation_status"] = "OFFER_OUTSTANDING"
    touch(policy)
    return created(offer)
