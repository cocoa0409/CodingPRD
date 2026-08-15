"""Core returns (receipt, grading, respond) and core deposits (PRD 3.3, 3.4)."""

from flask import Blueprint, request

import calcs
import clock as clockmod
import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import (
    ERR_DEPOSIT_NOT_LINKABLE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_STATE,
    raise_error,
)
from services import close_deposit, get_or_404
from store import db, stamp_new, sorted_rows, touch
from validate import (
    check_allowed_fields,
    filter_enum,
    get_body,
    opt_nullable_str,
    pagination,
    req_enum,
    req_enum_list,
    req_str,
)

bp = Blueprint("core", __name__)

PART_TYPES = {"CRANKSHAFT", "CYLINDER_HEAD", "ENGINE_BLOCK", "CAMSHAFT"}
GRADES = {"GRADE_A", "GRADE_B", "GRADE_C", "REJECT"}
RETURN_STATUSES = {"RECEIVED", "GRADED", "DISPUTED", "CLOSED"}
DEPOSIT_STATUSES = {"HELD", "CLOSED_REFUNDED", "FORFEITED"}


# ---------------------------------------------------------------------------
# Core returns
# ---------------------------------------------------------------------------


@bp.route("/core-returns", methods=["POST"])
def create_core_return():
    caller = authorized(["Distributor"])
    body = get_body()
    check_allowed_fields(body, ["distributor_id", "build_spec_id", "core_deposit_id"])
    distributor_id = req_str(body, "distributor_id")
    build_spec_id = req_str(body, "build_spec_id")
    core_deposit_id = opt_nullable_str(body, "core_deposit_id")

    # Existence of body-referenced ids (priority 4), canonical order.
    spec = get_or_404("build_specs", build_spec_id)
    deposit = None
    if core_deposit_id is not None:
        deposit = get_or_404("core_deposits", core_deposit_id)
    get_or_404("distributors", distributor_id)

    # Ownership (priority 5): a distributor registers returns only for itself.
    if distributor_id != caller.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "a distributor may register core returns only for itself",
        )

    # Deposit linkability (priority 10): HELD and owned by the returning
    # distributor.
    if deposit is not None:
        if deposit["status"] != "HELD" or deposit["distributor_id"] != distributor_id:
            raise_error(
                ERR_DEPOSIT_NOT_LINKABLE,
                "core_deposit_id must name a HELD deposit owned by the returning distributor",
            )

    record = {
        "distributor_id": distributor_id,
        "build_spec_id": build_spec_id,
        "core_deposit_id": core_deposit_id,
        "status": "RECEIVED",
        "grade": None,
        "missing_components": [],
        "provisional_credit_cents": calcs.provisional_credit_cents(spec),
        "final_credit_cents": None,
        "graded_at": None,
        "dispute_count": 0,
    }
    stamp_new(record)
    db.core_returns[record["id"]] = record
    return envelope.created(serializers.core_return(record))


@bp.route("/core-returns", methods=["GET"])
def list_core_returns():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_distributor = request.args.get("distributor_id")
    f_spec = request.args.get("build_spec_id")
    f_deposit = request.args.get("core_deposit_id")
    f_status = filter_enum("status", RETURN_STATUSES)
    rows = list(db.core_returns.values())
    if f_distributor is not None:
        rows = [r for r in rows if r["distributor_id"] == f_distributor]
    if f_spec is not None:
        rows = [r for r in rows if r["build_spec_id"] == f_spec]
    if f_deposit is not None:
        rows = [r for r in rows if r["core_deposit_id"] == f_deposit]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.core_return(r) for r in page], limit, offset, total)


@bp.route("/core-returns/<rid>", methods=["GET"])
def get_core_return(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("core_returns", rid)
    return envelope.ok(serializers.core_return(record))


@bp.route("/core-returns/<rid>/grade", methods=["POST"])
def grade_core_return(rid):
    authorized(["CoreInspector"])
    body = get_body()
    check_allowed_fields(body, ["grade", "missing_components"])
    grade = req_enum(body, "grade", GRADES)
    missing_components = req_enum_list(body, "missing_components", PART_TYPES)

    record = get_or_404("core_returns", rid)
    if record["status"] not in ("RECEIVED", "DISPUTED"):
        raise_error(
            ERR_INVALID_STATE,
            "only a RECEIVED or DISPUTED core return can be graded",
        )

    now = clockmod.now()
    spec = db.build_specs[record["build_spec_id"]]
    final_credit = calcs.final_credit_cents(spec, grade, missing_components)

    record["grade"] = grade
    record["missing_components"] = list(missing_components)
    record["graded_at"] = now
    record["final_credit_cents"] = final_credit
    record["status"] = "GRADED"
    touch(record)

    distributor = db.distributors[record["distributor_id"]]

    # CREDIT CHAIN link 1: post the final credit.  On a re-grade after dispute
    # the prior credit was already suspended by the DISPUTE, so adding the new
    # final credit nets to the delta between old and new.
    distributor["credit_balance_cents"] += final_credit

    # DEPOSIT CHAIN (only when the return names a deposit that is still HELD;
    # on a re-grade the deposit is already closed and there are no further
    # deposit side effects).
    if record["core_deposit_id"] is not None:
        deposit = db.core_deposits.get(record["core_deposit_id"])
        if deposit is not None and deposit["status"] == "HELD":
            refunded = close_deposit(deposit, now)
            # DEPOSIT CHAIN link 2: the refund posts to the credit balance;
            # deposits_held_cents is derived, so removing HELD status lowers it.
            distributor["credit_balance_cents"] += refunded

    touch(distributor)  # one version bump per mutated resource per request
    return envelope.ok(serializers.core_return(record))


@bp.route("/core-returns/<rid>/respond", methods=["POST"])
def respond_core_return(rid):
    caller = authorized(["Distributor"])
    body = get_body()
    check_allowed_fields(body, ["action"])
    action = req_enum(body, "action", {"ACCEPT", "DISPUTE"})

    record = get_or_404("core_returns", rid)

    # Ownership: only the owning distributor may respond to the grading.
    if record["distributor_id"] != caller.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "a distributor may respond only to gradings of its own returns",
        )

    if record["status"] != "GRADED":
        raise_error(ERR_INVALID_STATE, "only a GRADED core return can be responded to")

    if action == "ACCEPT":
        record["status"] = "CLOSED"
        touch(record)
    else:
        # DISPUTE: credit placed back in suspense while the dispute is open.
        record["status"] = "DISPUTED"
        record["dispute_count"] += 1
        touch(record)
        distributor = db.distributors[record["distributor_id"]]
        distributor["credit_balance_cents"] -= record["final_credit_cents"]
        touch(distributor)

    return envelope.ok(serializers.core_return(record))


# ---------------------------------------------------------------------------
# Core deposits
# ---------------------------------------------------------------------------


@bp.route("/core-deposits", methods=["GET"])
def list_core_deposits():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_distributor = request.args.get("distributor_id")
    f_engine = request.args.get("reman_engine_id")
    f_status = filter_enum("status", DEPOSIT_STATUSES)
    rows = list(db.core_deposits.values())
    if f_distributor is not None:
        rows = [r for r in rows if r["distributor_id"] == f_distributor]
    if f_engine is not None:
        rows = [r for r in rows if r["reman_engine_id"] == f_engine]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.core_deposit(r) for r in page], limit, offset, total)


@bp.route("/core-deposits/<rid>", methods=["GET"])
def get_core_deposit(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("core_deposits", rid)
    return envelope.ok(serializers.core_deposit(record))
