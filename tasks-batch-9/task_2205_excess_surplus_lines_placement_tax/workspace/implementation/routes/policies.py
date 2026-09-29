"""Policy issuance, reads, allocations and notice affixing (PRD 3.5-3.6)."""

from flask import Blueprint

import auth
import eligibility
import licensing
import serialize
import store
import validation
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("policies", __name__)

SECURITY_OK = ("APPROVED", "CONDITIONAL")


def _term_overlaps(placement_id, effective_at, expiration_at):
    """Policy terms on one placement are half-open, so touching terms are fine."""
    for other in store.policies_of_placement(placement_id):
        if other.get("status") == "CANCELLED":
            continue
        ex_eff = other.get("_effective_at")
        ex_exp = other.get("_expiration_at")
        if ex_eff is None or ex_exp is None:
            continue
        if effective_at < ex_exp and ex_eff < expiration_at:
            return True
    return False


@bp.post("/policies")
def issue_policy():
    auth.require("PlacementBroker")
    data = validation.body()
    # Rung 5: placement_id is declared before carrier_id.
    placement = auth.body_fk(data, "placement_id", "placements", "placement")
    carrier = auth.body_fk(data, "carrier_id", "carriers", "carrier")

    validation.req_str(data, "placement_id")
    validation.req_str(data, "carrier_id")
    policy_number = validation.req_str(data, "policy_number")
    effective_at, effective_raw = validation.req_datetime(data, "effective_date")
    expiration_at, expiration_raw = validation.req_datetime(data, "expiration_date")
    if expiration_at <= effective_at:
        validation.bad("expiration_date must be strictly after effective_date.")
    gross = validation.req_int(data, "original_gross_premium_cents", minimum=1)
    policy_fee = validation.opt_int(data, "policy_fee_cents", default=0, minimum=0)
    broker_fee = validation.opt_int(data, "broker_fee_cents", default=0, minimum=0)
    min_earned_pct = validation.opt_number(data, "min_earned_premium_pct", default=0,
                                          minimum=0, maximum=1, max_decimals=4)
    expected = validation.req_int(data, "expected_placement_version")
    if store.policy_by_number(policy_number) is not None:
        validation.bad("policy_number must be globally unique.")

    auth.check_owner(placement.get("broker_id"))
    auth.check_version(expected, placement, "ERR_STALE_PLACEMENT_VERSION")

    if placement.get("status") not in ("SEARCH_COMPLETE", "BOUND"):
        raise ApiError("ERR_PLACEMENT_NOT_BINDABLE",
                       "A policy may only be issued against a SEARCH_COMPLETE or "
                       "BOUND placement.")

    home = placement.get("home_state")
    program = store.state_program_by_code(home)
    if program is None:
        raise ApiError("ERR_STATE_PROGRAM_NOT_FOUND",
                       "No state program is configured for the home state %s." % home)

    if not licensing.has_active_surplus_lines(placement.get("broker_id"), home):
        raise ApiError("ERR_BROKER_LICENSE_NOT_ACTIVE",
                       "The brokerage holds no ACTIVE surplus lines licence in %s."
                       % home)
    if carrier.get("security_status") not in SECURITY_OK:
        raise ApiError("ERR_CARRIER_NOT_SECURITY_APPROVED",
                       "The carrier's market security standing is %s."
                       % carrier.get("security_status"))
    if not eligibility.white_listed_for(carrier["id"], program["id"], effective_at):
        raise ApiError("ERR_CARRIER_NOT_WHITE_LISTED",
                       "The carrier is not white-listed in %s for the policy's "
                       "effective date." % home)
    if _term_overlaps(placement["id"], effective_at, expiration_at):
        raise ApiError("ERR_POLICY_TERM_OVERLAP",
                       "The policy term overlaps an existing term on this placement.")

    stamping = "PENDING" if program.get("stamping_office_required") else "NOT_REQUIRED"
    rec = db.insert("policies", {
        "placement_id": placement["id"],
        "carrier_id": carrier["id"],
        "broker_id": placement.get("broker_id"),
        "policy_number": policy_number,
        "effective_date": effective_raw,
        "expiration_date": expiration_raw,
        "original_gross_premium_cents": gross,
        "gross_premium_cents": gross,
        "policy_fee_cents": policy_fee,
        "broker_fee_cents": broker_fee,
        "min_earned_premium_pct": min_earned_pct,
        "home_state": home,
        "allocation_method_applied": program.get("allocation_method"),
        "taxable_premium_cents": 0,
        "total_tax_cents": 0,
        "total_stamping_fee_cents": 0,
        "notice_codes_affixed": [],
        "status": "ISSUED",
        "compliance_status": "PENDING_NOTICES",
        "tax_status": "UNCALCULATED",
        "stamping_status": stamping,
        "stamping_submitted_at": None,
        "_effective_at": effective_at,
        "_expiration_at": expiration_at,
    })

    # The placement's version advances on every issuance, even one that leaves
    # the status at BOUND.
    placement["status"] = "BOUND"
    touch(placement)

    return created(serialize.public(rec))


@bp.get("/policies/<rec_id>")
def get_policy(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("policies", "policy", rec_id)
    return ok(serialize.public(rec))


@bp.get("/policies")
def list_policies():
    auth.require(auth.ANY)
    rows = filtered(db.all("policies"), placement_id=arg("placement_id"),
                    carrier_id=arg("carrier_id"), broker_id=arg("broker_id"),
                    tax_status=arg("tax_status"))
    return list_response(rows)


@bp.get("/policies/<rec_id>/allocations")
def list_allocations(rec_id):
    auth.require(auth.ANY)
    policy = auth.path_entity("policies", "policy", rec_id)
    rows = filtered(store.allocations_of(policy["id"]), state_code=arg("state_code"))
    return list_response(rows)


@bp.post("/policies/<rec_id>/affix-notices")
def affix_notices(rec_id):
    auth.require("PlacementBroker")
    policy = auth.path_entity("policies", "policy", rec_id)
    data = validation.body()
    codes = validation.req_code_array(data, "notice_codes")
    auth.check_owner(policy.get("broker_id"))

    if policy.get("compliance_status") != "PENDING_NOTICES":
        raise ApiError("ERR_INVALID_STATE",
                       "Notices may only be affixed while PENDING_NOTICES.")

    program = store.state_program_by_code(policy.get("home_state"))
    required = list((program or {}).get("required_notice_codes") or [])
    missing = [code for code in required if code not in codes]
    if missing:
        raise ApiError("ERR_NOTICES_INCOMPLETE",
                       "Missing required notice codes: %s." % ", ".join(missing))

    policy["notice_codes_affixed"] = sorted(set(codes))
    policy["compliance_status"] = "NOTICES_AFFIXED"
    touch(policy)
    return ok(serialize.public(policy))
