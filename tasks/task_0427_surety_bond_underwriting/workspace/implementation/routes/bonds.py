"""Bond endpoints (PRD §3.4, §3.5): bind, issue, cancel, renew (OCC), expire,
with the program-exposure and cession-recapture cascades."""

import uuid

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_bond
from services.calculations import (
    elapsed_months, earned_premium_pro_rata, earned_premium_short_rate,
)
from services.domain import (
    touch, bond_net_retained, recompute_bond_ceded,
)
from helpers import (
    get_body, require_str, require_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("bonds", __name__)

ROLES = ("Underwriter", "SeniorUnderwriter")
READ_ROLES = ("Underwriter", "SeniorUnderwriter", "ClaimsExaminer")
CANCEL_MODES = {"PRO_RATA", "SHORT_RATE"}


def _has_open_claim(bond_id):
    for c in db.claims.values():
        if c["bond_id"] == bond_id and c["status"] in ("FILED", "INVESTIGATING"):
            return True
    return False


def _new_bond_record(application_id, principal_id, program_id, bond_type,
                     penal_sum_cents, term_months, premium_rate_bps,
                     written_premium_cents):
    ts = now_ts()
    bid = new_id()
    return {
        "id": bid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "application_id": application_id,
        "principal_id": principal_id,
        "program_id": program_id,
        "superseded_by_bond_id": None,
        "bond_type": bond_type,
        "penal_sum_cents": penal_sum_cents,
        "term_months": term_months,
        "power_of_attorney_number": None,
        "premium_rate_bps": premium_rate_bps,
        "written_premium_cents": written_premium_cents,
        "earned_premium_cents": 0,
        "ceded_penal_sum_cents": 0,
        "incurred_loss_cents": 0,
        "status": "ISSUED",
    }


@bp.route("/surety/bonds", methods=["POST"])
@require_roles(*ROLES)
def bind_bond():
    body = get_body()
    application_id = require_str(body, "application_id")
    app_rec = db.applications.get(application_id)
    if app_rec is None:
        raise errors.not_found("Application not found")
    # State: application must be APPROVED.
    if app_rec["status"] != "APPROVED":
        raise errors.invalid_state("Application is not APPROVED")
    program = db.programs.get(app_rec["program_id"])
    # Program must be OPEN (else ERR_PROGRAM_SUSPENDED).
    if program is None or program["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_PROGRAM_SUSPENDED, 409, "Program is SUSPENDED")
    # Aggregate room: requested penal sum must not exceed available.
    available = program["aggregate_limit_cents"] - program["aggregate_committed_cents"]
    if app_rec["requested_penal_sum_cents"] > available:
        raise errors.ApiError(errors.ERR_AGGREGATE_LIMIT_EXCEEDED, 409,
                              "Program aggregate available cannot cover this bond")

    bond = _new_bond_record(
        application_id=app_rec["id"],
        principal_id=app_rec["principal_id"],
        program_id=app_rec["program_id"],
        bond_type=app_rec["bond_type"],
        penal_sum_cents=app_rec["requested_penal_sum_cents"],
        term_months=app_rec["term_months"],
        premium_rate_bps=app_rec["quoted_premium_rate_bps"],
        written_premium_cents=app_rec["quoted_premium_cents"],
    )
    db.bonds[bond["id"]] = bond

    # application -> BOUND
    app_rec["status"] = "BOUND"
    touch(app_rec)
    # program aggregate_committed_cents += new bond net_retained (= full penal sum)
    program["aggregate_committed_cents"] += bond_net_retained(bond)
    touch(program)
    return success(serialize_bond(bond), status=201)


@bp.route("/surety/bonds/<bid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_bond(bid):
    record = db.bonds.get(bid)
    if record is None:
        raise errors.not_found("Bond not found")
    return success(serialize_bond(record), status=200)


@bp.route("/surety/bonds", methods=["GET"])
@require_roles(*READ_ROLES)
def list_bonds():
    limit, offset = parse_pagination()
    items = list(db.bonds.values())
    for key in ("application_id", "principal_id", "program_id", "superseded_by_bond_id"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_bond(b) for b in page], limit, offset, total)


@bp.route("/surety/bonds/<bid>/issue", methods=["POST"])
@require_roles(*ROLES)
def issue_bond(bid):
    record = db.bonds.get(bid)
    if record is None:
        raise errors.not_found("Bond not found")
    if record["status"] != "ISSUED":
        raise errors.invalid_state("Bond is not ISSUED")
    record["power_of_attorney_number"] = "POA-" + uuid.uuid4().hex[:12].upper()
    record["status"] = "ACTIVE"
    touch(record)
    return success(serialize_bond(record), status=200)


def _recapture_all_cessions(bond):
    """Drive every ACTIVE cession on the bond to RECAPTURED, decrementing each
    affected treaty's ceded_committed_cents (PRD §3.5 cancel/expiry cascade)."""
    for c in db.cessions.values():
        if c["bond_id"] == bond["id"] and c["status"] == "ACTIVE":
            treaty = db.treaties.get(c["treaty_id"])
            if treaty is not None:
                treaty["ceded_committed_cents"] -= c["ceded_penal_sum_cents"]
                touch(treaty)
            c["status"] = "RECAPTURED"
            touch(c)
    # Bond ceded recomputed to 0 after recapture.
    recompute_bond_ceded(bond)


@bp.route("/surety/bonds/<bid>/cancel", methods=["POST"])
@require_roles(*ROLES)
def cancel_bond(bid):
    body = get_body()
    record = db.bonds.get(bid)
    if record is None:
        raise errors.not_found("Bond not found")
    cancel_mode = require_enum(body, "cancel_mode", CANCEL_MODES)
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")
    if _has_open_claim(record["id"]):
        raise errors.ApiError(errors.ERR_OPEN_CLAIM_EXISTS, 409,
                              "Bond has an open claim blocking cancellation")

    elapsed = elapsed_months(record["created_at"], record["term_months"])
    remaining = record["term_months"] - elapsed
    if cancel_mode == "PRO_RATA":
        earned = earned_premium_pro_rata(
            record["written_premium_cents"], record["term_months"], elapsed)
    else:  # SHORT_RATE
        earned = earned_premium_short_rate(
            record["written_premium_cents"], record["term_months"], elapsed, remaining)
    record["earned_premium_cents"] = earned

    # Program exposure released by this bond's net_retained measured BEFORE recapture.
    program = db.programs.get(record["program_id"])
    pre_recapture_net = bond_net_retained(record)
    if program is not None:
        program["aggregate_committed_cents"] -= pre_recapture_net
        touch(program)
    # Then recapture all active cessions.
    _recapture_all_cessions(record)

    record["status"] = "CANCELLED"
    touch(record)
    return success(serialize_bond(record), status=200)


@bp.route("/surety/bonds/<bid>/expire", methods=["POST"])
@require_roles(*ROLES)
def expire_bond(bid):
    record = db.bonds.get(bid)
    if record is None:
        raise errors.not_found("Bond not found")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")
    if _has_open_claim(record["id"]):
        raise errors.ApiError(errors.ERR_OPEN_CLAIM_EXISTS, 409,
                              "Bond has an open claim blocking expiry")

    # Fully earned at natural expiry.
    record["earned_premium_cents"] = record["written_premium_cents"]
    program = db.programs.get(record["program_id"])
    pre_recapture_net = bond_net_retained(record)
    if program is not None:
        program["aggregate_committed_cents"] -= pre_recapture_net
        touch(program)
    _recapture_all_cessions(record)

    record["status"] = "EXPIRED"
    touch(record)
    return success(serialize_bond(record), status=200)


@bp.route("/surety/bonds/<bid>/renew", methods=["POST"])
@require_roles(*ROLES)
def renew_bond(bid):
    body = get_body()
    record = db.bonds.get(bid)
    if record is None:
        raise errors.not_found("Bond not found")
    # Body well-formedness (priority 4): expected_bond_version required & integer.
    expected_version = require_int(body, "expected_bond_version")
    # State (priority 5).
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")
    # OCC (priority 6).
    if expected_version != record["version"]:
        raise errors.stale_version()
    # Aggregate room afresh for the bond's full penal sum.
    program = db.programs.get(record["program_id"])
    available = program["aggregate_limit_cents"] - program["aggregate_committed_cents"]
    if available < record["penal_sum_cents"]:
        raise errors.ApiError(errors.ERR_AGGREGATE_LIMIT_EXCEEDED, 409,
                              "Program aggregate available cannot cover the renewal")

    successor = _new_bond_record(
        application_id=record["application_id"],
        principal_id=record["principal_id"],
        program_id=record["program_id"],
        bond_type=record["bond_type"],
        penal_sum_cents=record["penal_sum_cents"],
        term_months=record["term_months"],
        premium_rate_bps=record["premium_rate_bps"],
        written_premium_cents=record["written_premium_cents"],
    )
    db.bonds[successor["id"]] = successor

    # Shift program exposure: release predecessor net_retained, commit successor penal sum.
    predecessor_net = bond_net_retained(record)
    program["aggregate_committed_cents"] -= predecessor_net
    program["aggregate_committed_cents"] += successor["penal_sum_cents"]
    touch(program)

    record["superseded_by_bond_id"] = successor["id"]
    record["status"] = "RENEWED"
    touch(record)
    # Endpoint returns the (predecessor) bond per the renew contract (output: Bond,
    # 200). The successor is discoverable via superseded_by_bond_id filter.
    return success(serialize_bond(record), status=200)
