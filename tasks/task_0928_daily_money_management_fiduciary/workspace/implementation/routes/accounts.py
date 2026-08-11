"""Accounts under management, balance adjustments and the fraud posture axis."""

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import append_ledger_entry, freeze_sweep, recompute_account
from core.audit import set_client, set_subject
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.gates import (
    gate_account_frozen,
    gate_bond,
    gate_period_frozen_for_date,
)
from core.pipeline import audited, authorize, resolve, resolve_body_client
from core.store import all_of, bump, db, new_row

bp = Blueprint("accounts", __name__)

READ_ROLES = ("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/dmm/accounts")
@audited("ClientAccount")
def create_account():
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("institution_name", str, True),
        ("account_label", str, True),
        ("account_type", str, True),
        ("opening_balance_cents", int, True),
    ])
    ctx.check_enum("account_type", K.ACCOUNT_TYPE)             # rung 5

    opening = ctx.body["opening_balance_cents"]
    if opening < 0:                                            # rung 15
        fail("ERR_VALIDATION", "opening_balance_cents must be zero or greater.")

    row = new_row("accounts", {
        "client_id": client_row["id"],
        "institution_name": ctx.body["institution_name"],
        "account_label": ctx.body["account_label"],
        "account_type": ctx.body["account_type"],
        "opening_balance_cents": opening,
        "cleared_balance_cents": opening,
        "pending_holds_cents": 0,
        "committed_disbursements_cents": 0,
        "available_balance_cents": opening,
        "fraud_posture": "NORMAL",
        "fraud_posture_reason": None,
    })
    set_subject(row["id"])
    return object_response(serialize.account(row), 201)


@bp.post("/dmm/accounts/<aid>/adjustments")
@audited("ClientAccount", path_param="aid")
def post_adjustment(aid):
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    account = resolve("accounts", aid)                         # rung 3
    set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("adjustment_type", str, True),
        ("amount_cents", int, True),
        ("value_date", str, True),
        ("memo", str, False),
    ])
    ctx.check_enum("adjustment_type", K.ADJUSTMENT_TYPE)       # rung 5

    gate_bond()                                                # rung 6
    gate_account_frozen(account)                               # rung 9
    gate_period_frozen_for_date(account, ctx.body["value_date"])  # rung 10

    amount = ctx.body["amount_cents"]
    adjustment_type = ctx.body["adjustment_type"]
    if amount <= 0:                                            # rung 15
        fail("ERR_VALIDATION", "amount_cents must be greater than zero.")
    if adjustment_type == "HOLD_RELEASE" and account["pending_holds_cents"] - amount < 0:
        fail("ERR_VALIDATION", "A hold release may not drive pending holds below zero.")

    if adjustment_type == "DEPOSIT":
        append_ledger_entry(
            account, "DEPOSIT", amount, ctx.body["value_date"],
            memo=ctx.body.get("memo"),
        )
    elif adjustment_type == "WITHDRAWAL_HOLD":
        account["pending_holds_cents"] += amount
    else:
        account["pending_holds_cents"] -= amount

    recompute_account(account)
    bump(account)
    return object_response(serialize.account(account), 200)


@bp.post("/dmm/accounts/<aid>/fraud-posture")
@audited("ClientAccount", path_param="aid")
def move_fraud_posture(aid):
    ctx = authorize("ComplianceOfficer")                       # rungs 1-2
    account = resolve("accounts", aid)                         # rung 3
    set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("to_posture", str, True),
        ("reason", str, True),
    ])
    ctx.check_enum("to_posture", K.FRAUD_POSTURE)              # rung 5

    to_posture = ctx.body["to_posture"]
    current = account["fraud_posture"]

    # rung 12 - the state gate on the posture axis.
    allowed = {
        ("NORMAL", "WATCH"),
        ("WATCH", "FROZEN"),
        ("NORMAL", "FROZEN"),
        ("WATCH", "NORMAL"),
        ("FROZEN", "NORMAL"),
    }
    if (current, to_posture) not in allowed:
        fail("ERR_INVALID_STATE", "The posture axis has no such transition.")
    if current == "FROZEN" and to_posture == "NORMAL":
        for alert in all_of("fraud_alerts"):
            if alert["account_id"] != account["id"]:
                continue
            if alert["status"] in ("NEW", "ESCALATED", "ACKNOWLEDGED"):
                fail("ERR_INVALID_STATE", "An open fraud alert still stands.")

    reason = ctx.body["reason"]
    if to_posture == "NORMAL" and len(reason) < K.FRAUD_UNFREEZE_REASON_MIN_CHARS:
        fail("ERR_VALIDATION", "The reason is too short.")     # rung 15

    apply_posture(account, to_posture, reason)
    return object_response(serialize.account(account), 200)


def apply_posture(account, to_posture, reason):
    """Shared by the posture endpoint and the confirmed-fraud cascade."""
    account["fraud_posture"] = to_posture
    account["fraud_posture_reason"] = reason
    if to_posture == "FROZEN":
        freeze_sweep(account)
    recompute_account(account)
    bump(account)


@bp.get("/dmm/accounts/<aid>")
def read_account(aid):
    authorize(*READ_ROLES)
    return object_response(serialize.account(resolve("accounts", aid)), 200)


@bp.get("/dmm/accounts/<aid>/reconciliation-periods")
def list_account_periods(aid):
    authorize(*READ_ROLES)
    resolve("accounts", aid)
    rows = [p for p in db.ordered("reconciliation_periods") if p["account_id"] == aid]
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize.reconciliation_period)
