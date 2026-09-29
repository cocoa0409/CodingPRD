"""The conserved fee ledger: reads and settlement (PRD 2.11, 3.9)."""
from flask import Blueprint

import constants as C
import db
import listing
import middleware
import response
from errors import fail
from services import cascades

bp = Blueprint("fees", __name__)

SETTLEMENT_ACTIONS = ["PAY", "WAIVE"]


def load_fee(fee_id):
    fee = db.get("fee_assessments", fee_id)
    if fee is None:
        fail("ERR_FEE_ASSESSMENT_NOT_FOUND", "No fee assessment matches that identifier.")
    return fee


@bp.route("/cle/fee-assessments/<fee_id>", methods=["GET"])
def read_fee(fee_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_ATTORNEY, C.ROLE_PROVIDER_ADMIN])
    return response.success(db.serialize(load_fee(fee_id)), 200)


@bp.route("/cle/fee-assessments", methods=["GET"])
def list_fees():
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY, C.ROLE_PROVIDER_ADMIN]
    )
    rows = listing.apply_filters(
        db.all_rows("fee_assessments"),
        ["attorney_id", "cycle_id", "provider_id", "assessed_by_sweep_id", "fee_type", "status"],
    )
    return listing.page(listing.sort_created_asc(rows))


@bp.route("/cle/fee-assessments/<fee_id>/settlement", methods=["POST"])
def settle(fee_id):
    user_id, role = middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_ATTORNEY, C.ROLE_PROVIDER_ADMIN]
    )
    body = middleware.body_json()

    # Step 2: WAIVE is reserved to the board, and the reservation is an
    # authorization check — it precedes path existence (PRD 2.1, 2.8).
    if body.get("action") == "WAIVE" and role != C.ROLE_BOARD_ADMIN:
        fail("ERR_ROLE_NOT_PERMITTED", "Only a BoardAdmin may waive an assessment.")

    fee = load_fee(fee_id)

    # Step 5: ownership — an attorney may only settle its own assessments.
    if role == C.ROLE_ATTORNEY and fee.get("attorney_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "That assessment names another attorney.")

    # Step 6: request shape.
    action = middleware.req_enum(body, "action", SETTLEMENT_ACTIONS)
    waiver_reason = middleware.opt_str(body, "waiver_reason", 1, None, None)
    if action == "WAIVE" and waiver_reason is None:
        fail("ERR_INVALID_REQUEST", "waiver_reason is required to waive an assessment.")

    # Step 17: fiscal gate, evaluated last of all.
    if fee.get("status") != "ASSESSED":
        fail("ERR_FEE_ALREADY_SETTLED", "That assessment has already left ASSESSED.")

    if action == "PAY":
        cascades.release_fee(fee, "PAID")
    else:
        cascades.release_fee(fee, "WAIVED", waiver_reason)
    return response.success(db.serialize(fee), 200)
