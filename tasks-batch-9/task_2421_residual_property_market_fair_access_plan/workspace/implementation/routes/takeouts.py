"""Depopulation: take-out offer reads, policyholder election and withdrawal
(PRD 3.8)."""

from flask import Blueprint

import lookup
from db import db, touch
from errors import fail
from middleware import own, require
from response import ok
from routes.common import matches, page
from services import policy as policy_svc
from services.constants import ELECTIONS, OFFER_STATUSES
from util import parse_instant
from validate import (
    body,
    filter_enum,
    filter_string,
    pagination,
    req_enum,
    req_string,
    store_instant,
)

bp = Blueprint("takeouts", __name__)


@bp.get("/takeout-offers/<offer_id>")
def read_offer(offer_id):
    require("MemberInsurerUser", "Policyholder", "PlanAdmin", "Underwriter")
    return ok(lookup.takeout_offer(offer_id))


@bp.get("/takeout-offers")
def list_offers():
    require("PlanAdmin", "Underwriter", "MemberInsurerUser")
    limit, offset = pagination()
    filters = {
        "policy_id": filter_string("policy_id"),
        "member_insurer_id": filter_string("member_insurer_id"),
        "status": filter_enum("status", OFFER_STATUSES),
    }
    rows = [o for o in db.takeout_offers.values() if matches(o, filters)]
    return page(rows, limit, offset)


@bp.post("/takeout-offers/<offer_id>/election")
def elect_offer(offer_id):
    caller = require("Policyholder")
    data = body()
    election = req_enum(data, "election", ELECTIONS)

    offer = lookup.takeout_offer(offer_id)
    policy = db.policies.get(offer["policy_id"])
    own(policy is not None and policy["applicant_id"] == caller.user_id,
        "Only the policy's named insured may elect on this offer")

    if offer["status"] != "OUTSTANDING":
        fail("ERR_OFFER_NOT_OUTSTANDING",
             "Offer status %s is not electable" % offer["status"])

    deadline = parse_instant(offer["election_deadline_at"])
    if deadline is not None and db.now() > deadline:
        fail("ERR_ELECTION_WINDOW_CLOSED", "The election window has closed")

    now = db.now()
    offer["elected_at"] = store_instant(now)

    if election == "ACCEPT":
        offer["status"] = "ACCEPTED"
        offer["credit_units_granted"] = 1
        touch(offer)

        member = db.member_insurers.get(offer["member_insurer_id"])
        if member is not None:
            member["takeout_credit_count"] += offer["credit_units_granted"]
            touch(member)

        # The coverage dimension terminates pro-rata with a zero fee, while the
        # depopulation dimension records the election.
        policy["depopulation_status"] = "ELECTED_TAKEOUT"
        policy_svc.terminate(policy, "TAKEN_OUT", "TAKEOUT_ELECTION", db.today())
    else:
        offer["status"] = "DECLINED"
        offer["credit_units_granted"] = 0
        touch(offer)
        # Only the depopulation dimension moves; nothing else at all.
        policy["depopulation_status"] = "ELECTED_RETAIN"
        touch(policy)

    return ok(offer)


@bp.post("/takeout-offers/<offer_id>/withdrawal")
def withdraw_offer(offer_id):
    caller = require("MemberInsurerUser")
    data = body()
    reason = req_string(data, "reason")

    offer = lookup.takeout_offer(offer_id)
    own(offer["member_insurer_id"] == caller.user_id,
        "Only the offering carrier may withdraw this offer")

    if offer["status"] != "OUTSTANDING":
        fail("ERR_OFFER_NOT_OUTSTANDING",
             "Offer status %s cannot be withdrawn" % offer["status"])

    offer["status"] = "WITHDRAWN"
    offer["withdrawal_reason"] = reason
    touch(offer)

    policy = db.policies.get(offer["policy_id"])
    if policy is not None:
        policy["depopulation_status"] = "NOT_OFFERED"
        touch(policy)

    return ok(offer)
