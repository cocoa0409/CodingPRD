"""Claims recovery: opening, pricing the demand and collecting (section 3.9)."""

from flask import Blueprint

import calc
import clock
import constants as K
import db
import derive
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("recoveries", __name__)

READ_ROLES = ("ProgramAdmin", "RecoveryAgent", "AppealReviewer")


def _recovery_or_404(recovery_id):
    recovery = db.get("recoveries", recovery_id)
    if recovery is None:
        raise ApiError("ERR_RECOVERY_NOT_FOUND")
    return recovery


def _program_of(notice, dependent):
    """The program whose announcement anchors an EQUITABLE window."""
    case_id = notice.get("case_id")
    if case_id is not None:
        case = db.get("cases", case_id)
        if case is not None:
            return db.get("programs", case["program_id"])
    poe_program_id = dependent.get("poe_program_id")
    if poe_program_id is not None:
        return db.get("programs", poe_program_id)
    return None


@bp.route("/claim-recoveries", methods=["POST"])
@endpoint("RecoveryAgent")
def open_recovery():
    payload = validate.body()
    dependent_id = validate.req_id(payload, "dependent_id")
    notice_id = validate.req_id(payload, "termination_notice_id")
    variant = validate.req_enum(payload, "recovery_variant", K.RECOVERY_VARIANTS)
    onset_date = validate.req_date(payload, "ineligibility_onset_date")
    expected_version = validate.req_int(payload, "expected_dependent_version")

    dependent = db.get("dependents", dependent_id)
    if dependent is None:
        raise ApiError("ERR_DEPENDENT_NOT_FOUND")
    notice = db.get("notices", notice_id)
    if notice is None:
        raise ApiError("ERR_NOTICE_NOT_FOUND")

    has_amnesty = any(
        r["dependent_id"] == dependent["id"]
        for r in db.collection("amnesty_removals").values()
    )
    if dependent["coverage_status"] != "TERMINATED" or has_amnesty:
        raise ApiError("ERR_DEPENDENT_STATE_INVALID")
    if notice["status"] != "FINAL":
        raise ApiError("ERR_NOTICE_STATE_INVALID")
    if expected_version != dependent["version"]:
        raise ApiError("ERR_STALE_DEPENDENT_VERSION")

    program = _program_of(notice, dependent)
    subtotal = calc.claims_recovery_amount(
        dependent, notice, program, variant, onset_date
    )

    # Supersede the dependent's prior row unless it has already collected money.
    for prior in db.ordered(
        "recoveries", lambda r: r["dependent_id"] == dependent["id"]
    ):
        if prior["status"] == "OPEN" or (
            prior["status"] == "DEMAND_ISSUED" and prior["recovered_cents"] == 0
        ):
            db.set_fields(prior, status="SUPERSEDED")

    recovery = db.insert(
        "recoveries",
        {
            "dependent_id": dependent["id"],
            "termination_notice_id": notice["id"],
            "recovery_variant": variant,
            "ineligibility_onset_date": onset_date,
            "recoverable_subtotal_cents": subtotal,
            "admin_fee_pct": 0,
            "admin_fee_cents": 0,
            "waiver_credit_cents": 0,
            "net_demand_cents": 0,
            "recovered_cents": 0,
            "refund_due_cents": 0,
            "status": "OPEN",
            "demand_issued_at": None,
        },
    )

    db.set_fields(
        dependent, recovery_revision=(dependent.get("recovery_revision") or 0) + 1
    )
    derive.refresh_all()
    return response.obj_out(serialize.recovery, recovery, 201)


@bp.route("/claim-recoveries/<recovery_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_recovery(recovery_id):
    recovery = _recovery_or_404(recovery_id)
    return response.obj_out(serialize.recovery, recovery)


@bp.route("/claim-recoveries", methods=["GET"])
@endpoint(*READ_ROLES)
def list_recoveries():
    dependent_id = validate.query_filter("dependent_id")
    notice_id = validate.query_filter("termination_notice_id")
    status = validate.query_filter("status")
    variant = validate.query_filter("recovery_variant")
    rows = db.ordered(
        "recoveries",
        lambda r: (dependent_id is None or r["dependent_id"] == dependent_id)
        and (notice_id is None or r["termination_notice_id"] == notice_id)
        and (status is None or r["status"] == status)
        and (variant is None or r["recovery_variant"] == variant),
    )
    return response.arr_out(serialize.recovery, rows, validate.paginate(rows))


@bp.route("/claim-recoveries/<recovery_id>/issue-demand", methods=["POST"])
@endpoint("RecoveryAgent")
def issue_demand(recovery_id):
    recovery = _recovery_or_404(recovery_id)
    payload = validate.body()
    waiver_credit_cents = validate.opt_int(payload, "waiver_credit_cents", 0, 0)

    if recovery["status"] != "OPEN":
        raise ApiError("ERR_RECOVERY_STATE_INVALID")
    subtotal = recovery["recoverable_subtotal_cents"]
    if waiver_credit_cents > subtotal:
        raise ApiError("ERR_WAIVER_EXCEEDS_SUBTOTAL")
    if subtotal < K.DE_MINIMIS_RECOVERY_CENTS:
        raise ApiError("ERR_RECOVERY_BELOW_DE_MINIMIS")

    pct, admin_fee_cents, net = calc.net_recovery_demand(subtotal, waiver_credit_cents)
    db.set_fields(
        recovery,
        admin_fee_pct=pct,
        admin_fee_cents=admin_fee_cents,
        waiver_credit_cents=waiver_credit_cents,
        net_demand_cents=net,
        status="DEMAND_ISSUED",
        demand_issued_at=clock.now(),
    )
    derive.refresh_all()
    return response.obj_out(serialize.recovery, recovery)


@bp.route("/claim-recoveries/<recovery_id>/payments", methods=["POST"])
@endpoint("RecoveryAgent")
def record_payment(recovery_id):
    recovery = _recovery_or_404(recovery_id)
    payload = validate.body()
    amount_cents = validate.req_int(payload, "amount_cents", 0)
    validate.req_date(payload, "received_date")

    if recovery["status"] not in ("DEMAND_ISSUED", "PARTIALLY_RECOVERED"):
        raise ApiError("ERR_RECOVERY_STATE_INVALID")
    total = recovery["recovered_cents"] + amount_cents
    if total > recovery["net_demand_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_DEMAND")

    db.set_fields(
        recovery,
        recovered_cents=total,
        status="RECOVERED" if total == recovery["net_demand_cents"] else "PARTIALLY_RECOVERED",
    )
    derive.refresh_all()
    return response.obj_out(serialize.recovery, recovery)
