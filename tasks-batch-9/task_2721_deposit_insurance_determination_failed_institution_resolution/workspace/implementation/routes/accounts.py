"""The deposit-account register, ownership interests and hold release
(PRD sections 3.2 and 3.6)."""

from flask import Blueprint, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, CLAIMS_AGENT, CLAIMS_CERTIFIER, require
from db import db, new_immutable_row, new_row, touch
from errors import ApiError
from routes.depositors import INTEREST_ROLES
from util import format_iso

bp = Blueprint("accounts", __name__)

OWNERSHIP_CATEGORIES = (
    "SINGLE",
    "JOINT",
    "REVOCABLE_TRUST",
    "IRREVOCABLE_TRUST",
    "RETIREMENT",
    "BROKERED_PASS_THROUGH",
)

RECORDKEEPING_STATUSES = ("COMPLETE", "DEFICIENT", "PENDING")


@bp.post("/deposit-accounts")
@require(CLAIMS_AGENT)
def create_account():
    # Stage 3 resolves every named resource before the body's shape is inspected,
    # in the entity order institution then depositor record (PRD 2.11).
    raw = shape.raw_body()
    institution = None
    if shape.present(raw, "institution_id"):
        institution = lookup.institution(raw["institution_id"])
    depositor = None
    if shape.present(raw, "primary_depositor_id"):
        depositor = lookup.depositor(raw["primary_depositor_id"])

    payload = shape.body()
    shape.req_id(payload, "institution_id")
    shape.req_id(payload, "primary_depositor_id")
    account_number = shape.req_str(payload, "account_number", min_len=1, max_len=32)
    ownership_category = shape.req_enum(
        payload, "ownership_category", OWNERSHIP_CATEGORIES
    )
    balance_cents = shape.req_int(payload, "balance_cents", minimum=0)
    opened_at = shape.req_datetime(payload, "opened_at")
    accrued_interest_cents = shape.opt_int(
        payload, "accrued_interest_cents", default=0, minimum=0
    )

    # The brokered pair is required exactly when the category is brokered.
    if ownership_category == "BROKERED_PASS_THROUGH":
        broker_name = shape.req_str(payload, "broker_name", min_len=1)
        recordkeeping_status = shape.req_enum(
            payload, "recordkeeping_status", RECORDKEEPING_STATUSES
        )
    else:
        shape.forbid(
            payload,
            "broker_name",
            "broker_name is only allowed for BROKERED_PASS_THROUGH accounts",
        )
        shape.forbid(
            payload,
            "recordkeeping_status",
            "recordkeeping_status is only allowed for BROKERED_PASS_THROUGH accounts",
        )
        broker_name = None
        recordkeeping_status = None

    # The mismatch is detected before the duplicate (PRD 3.2).
    if depositor["institution_id"] != institution["id"]:
        raise ApiError("ERR_DEPOSITOR_INSTITUTION_MISMATCH")
    for existing in lookup.accounts_of(institution["id"]):
        if existing["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = new_row(
        {
            "institution_id": institution["id"],
            "primary_depositor_id": depositor["id"],
            "account_number": account_number,
            "ownership_category": ownership_category,
            "balance_cents": balance_cents,
            "accrued_interest_cents": accrued_interest_cents,
            "opened_at": format_iso(opened_at),
            "broker_name": broker_name,
            "recordkeeping_status": recordkeeping_status,
            "insurance_status": "PENDING",
            "hold_status": "NONE",
            "held_amount_cents": 0,
            "transition_status": "PENDING",
            "attributed_amount_cents": 0,
        }
    )
    db.accounts[row["id"]] = row
    # total_deposit_balance_cents is recomputed from scratch on read; the
    # institution row still records the mutation.
    touch(institution)
    return response.created(serializers.account(row))


@bp.get("/deposit-accounts")
@require(ALL_ROLES)
def list_accounts():
    rows = list(db.accounts.values())
    for field in (
        "institution_id",
        "primary_depositor_id",
        "ownership_category",
        "insurance_status",
        "hold_status",
        "transition_status",
        "recordkeeping_status",
    ):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return response.paginated(dbmod.ordered(rows), serializers.account)


@bp.get("/deposit-accounts/<account_id>")
@require(ALL_ROLES)
def get_account(account_id):
    return response.ok(serializers.account(lookup.account(account_id)))


@bp.post("/deposit-accounts/<account_id>/ownership-interests")
@require(CLAIMS_AGENT)
def create_interest(account_id):
    # A path identifier is resolved before any body field is inspected (PRD 2.5).
    account = lookup.account(account_id)
    raw = shape.raw_body()
    depositor = None
    if shape.present(raw, "depositor_record_id"):
        depositor = lookup.depositor(raw["depositor_record_id"])

    payload = shape.body()
    shape.req_id(payload, "depositor_record_id")
    interest_role = shape.req_enum(payload, "interest_role", INTEREST_ROLES)
    designated_share_bps = shape.req_int(
        payload, "designated_share_bps", minimum=1, maximum=10000
    )

    if depositor["institution_id"] != account["institution_id"]:
        raise ApiError("ERR_DEPOSITOR_INSTITUTION_MISMATCH")

    row = new_immutable_row(
        {
            # Taken from the account addressed in the request, not from the body.
            "deposit_account_id": account["id"],
            "depositor_record_id": depositor["id"],
            "interest_role": interest_role,
            "designated_share_bps": designated_share_bps,
        }
    )
    db.interests[row["id"]] = row
    # An ownership interest is immutable and carries no version of its own, so
    # attaching one bumps the account it sits on.
    touch(account)
    return response.created(serializers.interest(row))


@bp.get("/deposit-accounts/<account_id>/ownership-interests")
@require(ALL_ROLES)
def list_account_interests(account_id):
    lookup.account(account_id)
    role = request.args.get("interest_role")
    rows = lookup.interests_on_account(account_id, role)
    return response.paginated(dbmod.ordered(rows), serializers.interest)


@bp.post("/deposit-accounts/<account_id>/release-hold")
@require(CLAIMS_CERTIFIER)
def release_hold(account_id):
    account = lookup.account(account_id)
    shape.body()

    if account["hold_status"] != "HELD":
        raise ApiError("ERR_HOLD_NOT_PLACED")
    depositor = db.depositors.get(account["primary_depositor_id"])
    if depositor is None or depositor["notice_status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_NOTICE_NOT_ACKNOWLEDGED")

    account["hold_status"] = "RELEASED"
    account["held_amount_cents"] = 0
    touch(account)
    # The receivership certificate is left completely untouched: releasing an
    # operational hold does not extinguish the uninsured claim.
    return response.ok(serializers.account(account))
