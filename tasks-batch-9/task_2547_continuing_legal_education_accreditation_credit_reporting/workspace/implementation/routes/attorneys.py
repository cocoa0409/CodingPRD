"""The attorney register, compliance periods and reinstatement
(PRD 3.4, 3.8, 3.9)."""
from flask import Blueprint

import calc
import constants as C
import db
import listing
import middleware
import response
import util
from errors import fail
from services import cascades

bp = Blueprint("attorneys", __name__)

COMPLIANCE_GROUPS = ["GROUP_1", "GROUP_2", "GROUP_3"]
STANDING_TARGETS = ["ACTIVE", "EXEMPT", "INACTIVE"]
CARRYOVER_ELECTIONS = ["CARRY_FORWARD", "WAIVE_CARRYOVER"]
CURE_BASES = ["FEES_AND_CREDITS_CURED", "BOARD_ORDER"]


def load_attorney(attorney_id):
    attorney = db.get("attorneys", attorney_id)
    if attorney is None:
        fail("ERR_ATTORNEY_NOT_FOUND", "No attorney matches that identifier.")
    return attorney


def load_cycle(cycle_id):
    cycle = db.get("compliance_cycles", cycle_id)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "No compliance cycle matches that identifier.")
    return cycle


@bp.route("/cle/attorneys", methods=["POST"])
def register_attorney():
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    body = middleware.body_json()
    bar_number = middleware.req_str(body, "bar_number", 1, 20)
    full_name = middleware.req_str(body, "full_name", 1, 200)
    admission_date = middleware.req_instant(body, "admission_date")
    compliance_group = middleware.req_enum(body, "compliance_group", COMPLIANCE_GROUPS)
    jurisdiction = middleware.req_jurisdiction(body, "principal_office_jurisdiction")

    for existing in db.all_rows("attorneys"):
        if existing.get("bar_number") == bar_number:
            fail("ERR_DUPLICATE_BAR_NUMBER", "That bar number is already on the register.")

    attorney = db.insert(
        "attorneys",
        {
            "bar_number": bar_number,
            "full_name": full_name,
            "admission_date": util.iso(admission_date),
            "compliance_group": compliance_group,
            "principal_office_jurisdiction": jurisdiction,
            "status": "ACTIVE",
            "outstanding_fee_cents": 0,
            "open_deficiency_count": 0,
            "pending_recertification_count": 0,
        },
    )
    return response.success(db.serialize(attorney), 201)


@bp.route("/cle/attorneys/<attorney_id>", methods=["GET"])
def read_attorney(attorney_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    return response.success(db.serialize(load_attorney(attorney_id)), 200)


@bp.route("/cle/attorneys/<attorney_id>/status-changes", methods=["POST"])
def status_change(attorney_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    attorney = load_attorney(attorney_id)
    body = middleware.body_json()
    target = middleware.req_enum(
        body, "status", STANDING_TARGETS + ["ADMIN_SUSPENDED"]
    )
    middleware.opt_str(body, "reason", 1, None, None)
    if target == "ADMIN_SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION", "ADMIN_SUSPENDED is not reachable by a standing change.")
    if attorney.get("status") == "ADMIN_SUSPENDED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "An administratively suspended attorney is only cleared by reinstatement.",
        )
    cascades.set_fields(attorney, {"status": target})
    db.touch(attorney)
    return response.success(db.serialize(attorney), 200)


@bp.route("/cle/attorneys/<attorney_id>/compliance-cycles", methods=["POST"])
def open_cycle(attorney_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    attorney = load_attorney(attorney_id)
    body = middleware.body_json()

    previous = None
    if middleware.present(body, "previous_cycle_id"):
        previous = load_cycle(body.get("previous_cycle_id"))

    period_start = middleware.req_instant(body, "period_start")
    period_end = middleware.req_instant(body, "period_end")
    if not period_start < period_end:
        fail("ERR_INVALID_REQUEST", "period_start must be strictly earlier than period_end.")
    election = middleware.opt_enum(body, "carryover_election", CARRYOVER_ELECTIONS, "CARRY_FORWARD")

    for existing in db.all_rows("compliance_cycles"):
        if existing.get("attorney_id") != attorney["id"]:
            continue
        other_start = util.parse_dt(existing.get("period_start"))
        other_end = util.parse_dt(existing.get("period_end"))
        if period_start < other_end and other_start < period_end:
            fail("ERR_CYCLE_PERIOD_OVERLAP", "That period intersects an existing period.")

    derived = calc.requirement_derivation(attorney, period_start, period_end)
    cycle = db.insert(
        "compliance_cycles",
        {
            "attorney_id": attorney["id"],
            "period_start": util.iso(period_start),
            "period_end": util.iso(period_end),
            "previous_cycle_id": previous["id"] if previous is not None else None,
            "comity_claim_id": None,
            "credit_status": "OPEN",
            "administrative_status": "GOOD_STANDING",
            "prorated": derived["prorated"],
            "required_total_minutes": derived["required_total_minutes"],
            "required_ethics_minutes": derived["required_ethics_minutes"],
            "required_technology_minutes": derived["required_technology_minutes"],
            "required_bias_minutes": derived["required_bias_minutes"],
            "filing_deadline": derived["filing_deadline"],
            "carryover_election": election,
            "carryover_in_general_minutes": (previous.get("carryover_out_general_minutes") or 0)
            if previous is not None
            else 0,
            "carryover_in_ethics_minutes": (previous.get("carryover_out_ethics_minutes") or 0)
            if previous is not None
            else 0,
            "carryover_out_general_minutes": 0,
            "carryover_out_ethics_minutes": 0,
            "earned_countable_minutes": 0,
            "earned_ethics_minutes": 0,
            "earned_technology_minutes": 0,
            "earned_bias_minutes": 0,
            "earned_live_minutes": 0,
            "certified_at": None,
            "delinquent_since": None,
        },
    )
    return response.success(db.serialize(cycle), 201)


@bp.route("/cle/attorneys/<attorney_id>/reciprocity-claims", methods=["GET"])
def list_attorney_claims(attorney_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    attorney = load_attorney(attorney_id)
    rows = [r for r in db.all_rows("reciprocity_claims") if r.get("attorney_id") == attorney["id"]]
    return listing.page(listing.sort_created_asc(rows))


@bp.route("/cle/attorneys/<attorney_id>/reinstatement", methods=["POST"])
def reinstatement(attorney_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    attorney = load_attorney(attorney_id)
    body = middleware.body_json()
    cycle = load_cycle(body.get("cycle_id")) if middleware.present(body, "cycle_id") else None
    if cycle is None:
        fail("ERR_INVALID_REQUEST", "cycle_id is required.")
    cure_basis = middleware.req_enum(body, "cure_basis", CURE_BASES)
    middleware.opt_str(body, "reason", 1, None, None)

    # Step 8: state preconditions.
    if attorney.get("status") != "ADMIN_SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION", "The attorney is not administratively suspended.")
    if cycle.get("administrative_status") != "ADMIN_SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION", "That cycle is not administratively suspended.")
    if cure_basis == "FEES_AND_CREDITS_CURED":
        preview = calc.credit_application(cycle, "FINAL")
        if calc.has_any_deficiency(preview):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "The final-variant run still shows a deficiency.",
            )

    # Step 17: fiscal gate, evaluated last of all.
    if int(attorney.get("outstanding_fee_cents") or 0) != 0:
        fail("ERR_OUTSTANDING_FEE_BALANCE", "The attorney still owes an outstanding balance.")

    cascades.set_fields(cycle, {"administrative_status": "REINSTATED", "delinquent_since": None})
    cascades.set_fields(attorney, {"status": "ACTIVE"})
    if cure_basis == "FEES_AND_CREDITS_CURED":
        cascades.persist_application(cycle, "FINAL")
        if cycle.get("credit_status") == "DEFICIENT":
            cascades.bump_deficiency_count(attorney, -1)
        cascades.set_fields(cycle, {"credit_status": "SATISFIED"})
    db.touch(cycle)
    db.touch(attorney)
    return response.success(db.serialize(attorney), 200)
