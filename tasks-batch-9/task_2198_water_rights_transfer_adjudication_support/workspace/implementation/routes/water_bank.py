"""Water bank accounts and credit deposits."""
from flask import Blueprint

import calc
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("water_bank", __name__)

POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
DEPOSITABLE_RIGHT_STATUSES = ("ACTIVE", "ENCUMBERED", "PARTIALLY_TRANSFERRED")
ZERO2 = calc.D("0.00")


@bp.route("/water-bank-accounts", methods=["POST"])
def create_account():
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))

    body = validate.get_body()
    claimant_id = validate.req_str(body, "claimant_id")
    basin_code = validate.req_str(body, "basin_code", 1, 24)

    claimant = common.get_claimant(claimant_id)

    row = db.base_row()
    row.update({
        "claimant_id": claimant["id"],
        "basin_code": basin_code,
        "deposited_credit_af": ZERO2,
        "committed_credit_af": ZERO2,
        "leased_out_af": ZERO2,
        "available_credit_af": ZERO2,
        "suspended_lease_count": 0,
        "posture": "OPEN",
    })
    db.water_bank_accounts[row["id"]] = row
    derive.recompute_account(row)
    return response.object_response(serialize.water_bank_account(row), 201)


@bp.route("/water-bank-accounts", methods=["GET"])
def list_accounts():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    claimant_id = validate.query_str("claimant_id")
    basin_code = validate.query_str("basin_code")
    posture = validate.query_enum("posture", POSTURES)

    rows = []
    for row in db.water_bank_accounts.values():
        derive.recompute_account(row)
        if claimant_id is not None and row["claimant_id"] != claimant_id:
            continue
        if basin_code is not None and row["basin_code"] != basin_code:
            continue
        if posture is not None and row["posture"] != posture:
            continue
        rows.append(row)
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.water_bank_account, limit, offset)


@bp.route("/water-bank-accounts/<acid>", methods=["GET"])
def get_account(acid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    account = common.get_account(acid)
    middleware.require_owner(caller, common.account_owner(account))
    return response.object_response(serialize.water_bank_account(account))


@bp.route("/water-bank-accounts/<acid>/deposits", methods=["POST"])
def create_deposit(acid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )
    account = common.get_account(acid)
    middleware.require_owner(caller, common.account_owner(account))

    body = validate.get_body()
    right_id = validate.req_str(body, "water_right_id")
    deposit_af = validate.req_decimal(body, "deposit_af", gt=0)
    expected = validate.req_int(
        body, "expected_water_bank_account_version", minimum=0
    )

    right = common.get_right(right_id)

    derive.recompute_account(account)
    if expected != account["version"]:
        raise ApiError(
            "ERR_STALE_ACCOUNT_VERSION",
            "expected_water_bank_account_version %d does not match version %d."
            % (expected, account["version"]),
        )

    derive.recompute_right(right)
    if right["status"] not in DEPOSITABLE_RIGHT_STATUSES:
        raise ApiError(
            "ERR_RIGHT_NOT_TRANSFERABLE",
            "A right in status %s cannot be banked." % right["status"],
        )
    if not right["bank_enrolled"]:
        raise ApiError(
            "ERR_RIGHT_NOT_BANK_ENROLLED",
            "The water right is not enrolled in the water bank.",
        )

    deposit_af = calc.q2(deposit_af)
    if deposit_af > right["transferable_af"]:
        raise ApiError(
            "ERR_TRANSFERABLE_VOLUME_EXCEEDED",
            "deposit_af %s exceeds transferable_af %s."
            % (deposit_af, right["transferable_af"]),
        )

    db.bank_deposits.append({
        "water_bank_account_id": account["id"],
        "water_right_id": right["id"],
        "deposit_af": deposit_af,
    })

    derive.recompute_account(account)
    db.touch(account)
    derive.recompute_right(right)
    db.touch(right)
    return response.object_response(serialize.water_bank_account(account))
