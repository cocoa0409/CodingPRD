"""RecoveryTransaction endpoints: post, get, list, list-by-account (PRD 3.8)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_RECOVERY_EXCEEDS_BALANCE,
    ERR_RECOVERY_FK_MISMATCH,
    not_found,
)
from middleware import (
    ROLE_AGENCY,
    ROLE_COLLECTOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    close_account_paid_if_zero,
    installments_paid_count,
    plan_paid_cents,
    post_writeoff_recoveries_cents,
    serialize_recovery,
)
from util import (
    base_record,
    fee_round_half_up,
    get_body,
    now_iso,
    paginate,
    req_enum,
    req_int,
    req_str,
    touch,
)

bp = Blueprint("recoveries", __name__)

_RW_ROLES = [ROLE_COLLECTOR, ROLE_OFFICER, ROLE_AGENCY]
_POST_ROLES = [ROLE_COLLECTOR, ROLE_AGENCY]

PAYMENT_KINDS = (
    "INSTALLMENT",
    "LUMP_SUM",
    "AGENCY_REMITTANCE",
    "EARLY_OUT_REMITTANCE",
    "POST_WRITEOFF_RECOVERY",
)


def get_recovery_or_404(transaction_id):
    r = db.recovery_transactions.get(transaction_id)
    if r is None:
        raise not_found("recovery transaction not found")
    return r


@bp.post("/self-pay/recovery-transactions")
def post_recovery():
    authenticate(_POST_ROLES)
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)

    payment_kind = req_enum(b, "payment_kind", PAYMENT_KINDS)
    amount_cents = req_int(b, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0", 400)

    # polymorphic companion references must resolve to the entity family the
    # payment kind requires (priority 13); a missing or wrong-family reference
    # is ERR_RECOVERY_FK_MISMATCH
    placement = None
    plan = None
    write_off = None
    attributed_placement_id = None
    payment_plan_id = None
    write_off_id = None
    if payment_kind == "EARLY_OUT_REMITTANCE":
        attributed_placement_id = b.get("attributed_placement_id")
        if (not isinstance(attributed_placement_id, str)
                or attributed_placement_id not in db.early_out_placements):
            raise ApiError(
                ERR_RECOVERY_FK_MISMATCH,
                "EARLY_OUT_REMITTANCE requires attributed_placement_id "
                "resolving to an early-out placement",
                400,
            )
        placement = db.early_out_placements[attributed_placement_id]
    elif payment_kind == "AGENCY_REMITTANCE":
        attributed_placement_id = b.get("attributed_placement_id")
        if (not isinstance(attributed_placement_id, str)
                or attributed_placement_id not in db.agency_placements):
            raise ApiError(
                ERR_RECOVERY_FK_MISMATCH,
                "AGENCY_REMITTANCE requires attributed_placement_id resolving "
                "to a collection agency placement",
                400,
            )
        placement = db.agency_placements[attributed_placement_id]
    elif payment_kind == "INSTALLMENT":
        payment_plan_id = b.get("payment_plan_id")
        if (not isinstance(payment_plan_id, str)
                or payment_plan_id not in db.payment_plans):
            raise ApiError(
                ERR_RECOVERY_FK_MISMATCH,
                "INSTALLMENT requires payment_plan_id resolving to a payment "
                "plan",
                400,
            )
        plan = db.payment_plans[payment_plan_id]
    elif payment_kind == "POST_WRITEOFF_RECOVERY":
        write_off_id = b.get("write_off_id")
        if (not isinstance(write_off_id, str)
                or write_off_id not in db.write_offs):
            raise ApiError(
                ERR_RECOVERY_FK_MISMATCH,
                "POST_WRITEOFF_RECOVERY requires write_off_id resolving to a "
                "write-off",
                400,
            )
        write_off = db.write_offs[write_off_id]

    # amount ceiling per target (priority 14)
    if payment_kind == "POST_WRITEOFF_RECOVERY":
        ceiling = write_off["amount_cents"] - post_writeoff_recoveries_cents(
            write_off_id)
        if amount_cents > ceiling:
            raise ApiError(
                ERR_RECOVERY_EXCEEDS_BALANCE,
                "post-write-off recovery exceeds the write-off remainder",
                422,
            )
    else:
        if payment_kind == "INSTALLMENT":
            remaining = (plan["installment_amount_cents"]
                         * plan["installment_count"]
                         - plan_paid_cents(payment_plan_id))
            if amount_cents > remaining:
                raise ApiError(
                    ERR_RECOVERY_EXCEEDS_BALANCE,
                    "installment amount exceeds the plan's remaining balance",
                    422,
                )
        if amount_cents > account["current_balance_cents"]:
            raise ApiError(
                ERR_RECOVERY_EXCEEDS_BALANCE,
                "amount exceeds the account's current_balance_cents",
                422,
            )

    # vendor/agency contingency fee: round half up; net = gross - fee
    fee_cents = 0
    if placement is not None:
        fee_cents = fee_round_half_up(amount_cents,
                                      placement["contingency_fee_bps"])
    net_to_hospital_cents = amount_cents - fee_cents

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "payment_kind": payment_kind,
        "amount_cents": amount_cents,
        "attributed_placement_id": attributed_placement_id,
        "payment_plan_id": payment_plan_id,
        "write_off_id": write_off_id,
        "net_to_hospital_cents": net_to_hospital_cents,
        "posted_at": now_iso(),
    })
    db.recovery_transactions[rec["id"]] = rec

    # the patient paid gross: balance falls by gross; recovery ledger +gross
    if payment_kind == "POST_WRITEOFF_RECOVERY":
        # balance was already written off; reserve methodology selects the
        # accounting treatment of the write-off total
        if account["_reserve_methodology"] == "ALLOWANCE":
            account["bad_debt_writeoff_total_cents"] = max(
                0, account["bad_debt_writeoff_total_cents"] - amount_cents)
        account["recovery_total_cents"] += amount_cents
        # closure check: cumulative post-write-off recoveries reaching the
        # write-off amount close a still-WRITTEN_OFF account as CLOSED_PAID
        cumulative = post_writeoff_recoveries_cents(write_off_id)
        if (cumulative >= write_off["amount_cents"]
                and account["status"] == "WRITTEN_OFF"):
            account["status"] = "CLOSED_PAID"
            account["status_reason"] = "post-write-off recovery completed"
            # credit_reporting_status unchanged
    else:
        account["current_balance_cents"] -= amount_cents
        account["recovery_total_cents"] += amount_cents
        if payment_kind == "INSTALLMENT":
            if (installments_paid_count(payment_plan_id)
                    == plan["installment_count"]
                    and plan["status"] == "ACTIVE"):
                plan["status"] = "COMPLETED"
                touch(plan)
        close_account_paid_if_zero(account)
    touch(account)
    return ok_object(serialize_recovery(rec), 201)


@bp.get("/self-pay/recovery-transactions/<transaction_id>")
def get_recovery(transaction_id):
    authenticate(_RW_ROLES)
    return ok_object(serialize_recovery(get_recovery_or_404(transaction_id)))


def _recovery_filters(items):
    acct_f = request.args.get("account_id")
    kind_f = request.args.get("payment_kind")
    placement_f = request.args.get("attributed_placement_id")
    plan_f = request.args.get("payment_plan_id")
    wo_f = request.args.get("write_off_id")
    if acct_f is not None:
        items = [r for r in items if r["account_id"] == acct_f]
    if kind_f is not None:
        items = [r for r in items if r["payment_kind"] == kind_f]
    if placement_f is not None:
        items = [r for r in items
                 if r.get("attributed_placement_id") == placement_f]
    if plan_f is not None:
        items = [r for r in items if r.get("payment_plan_id") == plan_f]
    if wo_f is not None:
        items = [r for r in items if r.get("write_off_id") == wo_f]
    return items


@bp.get("/self-pay/recovery-transactions")
def list_recoveries():
    authenticate(_RW_ROLES)
    items = _recovery_filters(list(db.recovery_transactions.values()))
    page, meta = paginate(items)
    return ok_list([serialize_recovery(r) for r in page], meta)


@bp.get("/self-pay/accounts/<account_id>/recovery-transactions")
def list_recoveries_for_account(account_id):
    authenticate(_RW_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = _recovery_filters([r for r in db.recovery_transactions.values()
                               if r["account_id"] == account_id])
    page, meta = paginate(items)
    return ok_list([serialize_recovery(r) for r in page], meta)
