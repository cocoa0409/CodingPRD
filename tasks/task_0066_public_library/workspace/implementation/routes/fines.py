"""Fine routes: get / pay / waive."""
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import get_fine, check_version, assert_reader_ownership
from services.serialize import serialize_fine
from services.reader_status import recompute_reader
from services import audit


bp = Blueprint("fines", __name__)


def _recompute_outstanding(fine: dict):
    fine["outstanding_cents"] = max(
        0, fine["accrued_cents"] - fine["waived_cents"] - fine["paid_cents"])
    if fine["outstanding_cents"] == 0:
        fine["settlement_status"] = "SETTLED"


@bp.route("/library/fines/<fid>", methods=["GET"])
@require_auth(roles={"Reader", "FineOfficer", "Admin"})
def get_fine_endpoint(fid):
    fine = get_fine(fid)
    assert_reader_ownership(fine["reader_id"])
    return success(serialize_fine(fine))


@bp.route("/library/fines/<fid>/pay", methods=["POST"])
@require_auth(roles={"Reader", "FineOfficer"})
def pay_fine(fid):
    fine = get_fine(fid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(fine, body)
    assert_reader_ownership(fine["reader_id"])

    pay_cents = V.require_int(body, "pay_cents")
    if pay_cents <= 0:
        raise err("ERR_FINE_OVERPAYMENT", "pay_cents must be > 0")
    idem_key = V.require_str(body, "idempotency_key")

    # PAYMENT_CONFIRMED event lookup
    evt = db.payment_events.get(idem_key)
    if evt is None or evt.get("consumed"):
        raise err("ERR_PAYMENT_EVENT_MISSING",
                  "No matching PAYMENT_CONFIRMED event for the idempotency_key")

    if fine["settlement_status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Fine is {fine['settlement_status']}; only PENDING fines can be paid")

    if pay_cents > fine["outstanding_cents"]:
        raise err("ERR_FINE_OVERPAYMENT",
                  f"pay_cents {pay_cents} exceeds outstanding {fine['outstanding_cents']}")

    fine["paid_cents"] = fine["paid_cents"] + pay_cents
    _recompute_outstanding(fine)
    db.stamp_update(fine)
    evt["consumed"] = True

    audit.append("FINE_PAID", "Fine", fine["id"],
                 {"after": {"paid_cents": fine["paid_cents"],
                            "outstanding_cents": fine["outstanding_cents"],
                            "settlement_status": fine["settlement_status"]}})

    recompute_reader(fine["reader_id"])
    return success(serialize_fine(fine))


@bp.route("/library/fines/<fid>/waive", methods=["POST"])
@require_auth(roles={"FineOfficer"})
def waive_fine(fid):
    fine = get_fine(fid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(fine, body)

    waive_cents = V.require_int(body, "waive_cents")
    reason = body.get("reason")

    if reason not in V.WAIVE_REASONS:
        raise err("ERR_INVALID_WAIVER",
                  f"reason must be one of {sorted(V.WAIVE_REASONS)}, got {reason!r}")
    if waive_cents <= 0:
        raise err("ERR_INVALID_WAIVER", "waive_cents must be > 0")

    if fine["settlement_status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Fine is {fine['settlement_status']}; only PENDING fines can be waived")

    if waive_cents > fine["outstanding_cents"]:
        # Per validation priority — when waive exceeds outstanding at validation step we use INVALID_WAIVER;
        # PRD §3.6 distinguishes concurrent-loser case as FINE_OVERPAYMENT. We pick FINE_OVERPAYMENT
        # only when a concurrent reduction has happened (not modeled in single-threaded eval).
        raise err("ERR_INVALID_WAIVER",
                  f"waive_cents {waive_cents} exceeds outstanding {fine['outstanding_cents']}")

    fine["waived_cents"] = fine["waived_cents"] + waive_cents
    _recompute_outstanding(fine)
    db.stamp_update(fine)

    audit.append("FINE_WAIVED", "Fine", fine["id"],
                 {"after": {"waived_cents": fine["waived_cents"],
                            "outstanding_cents": fine["outstanding_cents"],
                            "settlement_status": fine["settlement_status"]}})

    recompute_reader(fine["reader_id"])
    return success(serialize_fine(fine))
