"""Disbursement preparation, dual control, release, settlement and unwinds."""

from datetime import timedelta

from flask import Blueprint

from core import calc
from core import constants as K
from core import serialize
from core.aggregates import (
    append_ledger_entry,
    cancel_payment_row,
    in_force_bond,
    recompute_payment_aggregates,
    stop_payment_row,
)
from core.audit import set_client, set_subject
from core.clock import parse_date
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.gates import (
    gate_account_frozen,
    gate_authorization,
    gate_bond,
    gate_client_active,
    gate_period_frozen_now,
    gate_scope_payment,
)
from core.pipeline import audited, authorize, resolve, resolve_body_ref
from core.store import all_of, bump, db, new_row

bp = Blueprint("payments", __name__)

READ_ROLES = ("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer", "PlatformAdmin")


def _client_of_account(account):
    return db.clients.get(account["client_id"]) if account else None


@bp.post("/dmm/payments")
@audited("Payment")
def schedule_payment():
    ctx = authorize("BillPaySpecialist")                       # rungs 1-2

    # rung 3 - path first (none here), then body identifiers in input order.
    account = resolve_body_ref(ctx, "account_id", "accounts")
    payee = resolve_body_ref(ctx, "payee_id", "payees")
    auth = resolve_body_ref(ctx, "authorization_id", "authorizations")
    line = resolve_body_ref(ctx, "budget_category_id", "budget_categories")
    if account is not None:
        set_client(account["client_id"])

    ctx.check_shape([                                          # rung 4
        ("account_id", str, True),
        ("payee_id", str, True),
        ("authorization_id", str, True),
        ("budget_category_id", str, True),
        ("amount_cents", int, True),
        ("channel", str, True),
        ("expected_account_version", int, True),
        ("requested_send_date", str, False),
        ("memo", str, False),
        ("duplicate_override", bool, False),
    ])
    ctx.check_enum("channel", K.PAYMENT_CHANNEL)               # rung 5

    gate_bond()                                                # rung 6
    gate_authorization(auth)                                   # rung 7
    gate_scope_payment(auth, payee)                            # rung 8
    gate_account_frozen(account)                               # rung 9
    gate_period_frozen_now(account)                            # rung 10
    gate_client_active(_client_of_account(account))            # rung 11

    amount = ctx.body["amount_cents"]
    channel = ctx.body["channel"]
    requested_send_date = ctx.body.get("requested_send_date")
    service_fee = calc.service_fee_cents(amount)
    total_charge = amount + service_fee
    projected = calc.settlement_date(db.now, requested_send_date, channel)

    # rung 13 - payment referential integrity.
    if (payee["client_id"] != account["client_id"]
            or line["client_id"] != account["client_id"]
            or line["budget_month"] != projected[:7]):
        fail("ERR_REFERENCE_MISMATCH", "Payee, budget line and account must agree.")

    if amount <= 0:                                            # rung 15
        fail("ERR_VALIDATION", "amount_cents must be greater than zero.")

    if ctx.body.get("duplicate_override") is not True:         # rung 19
        if _has_duplicate(account["id"], payee["id"], amount, projected):
            fail("ERR_DUPLICATE_PAYMENT_WINDOW", "A near-duplicate payment is outstanding.")

    if requested_send_date is not None:                        # rung 20
        supplied = parse_date(requested_send_date)
        if supplied is not None and supplied < db.now.date():
            fail("ERR_SEND_DATE_IN_PAST", "requested_send_date is in the past.")

    if payee["status"] != "ACTIVE":                            # rung 28
        fail("ERR_PAYEE_BLOCKED", "The payee is blocked.")

    ceiling = calc.scope_amount_ceiling(auth["scope_tier"])    # rung 33
    if ceiling is not None and amount > ceiling:
        fail("ERR_SCOPE_AMOUNT_EXCEEDED", "The instrument's per-payment ceiling is exceeded.")

    if ctx.body["expected_account_version"] != account["version"]:   # rung 34
        fail("ERR_STALE_VERSION", "The account version has moved on.")

    bond = in_force_bond()                                     # rung 35
    if bond["exposure_committed_cents"] + amount > bond["coverage_cents"]:
        fail("ERR_BOND_COVERAGE_EXCEEDED", "The bond's committed coverage is exhausted.")

    capacity = line["allocation_cents"] + line["override_granted_cents"]   # rung 36
    if line["committed_cents"] + amount > capacity:
        fail("ERR_BUDGET_EXCEEDED", "The budget line has insufficient capacity.")

    if account["available_balance_cents"] < total_charge:      # rung 37
        fail("ERR_INSUFFICIENT_AVAILABLE", "The account has insufficient available funds.")

    approval_status = (
        "PENDING_SECOND_APPROVAL"
        if amount >= K.SECOND_APPROVAL_THRESHOLD_CENTS
        else "APPROVED"
    )
    payment = new_row("payments", {
        "account_id": account["id"],
        "payee_id": payee["id"],
        "authorization_id": auth["id"],
        "budget_category_id": line["id"],
        "amount_cents": amount,
        "channel": channel,
        "memo": ctx.body.get("memo"),
        "requested_send_date": requested_send_date,
        "duplicate_override": bool(ctx.body.get("duplicate_override", False)),
        "service_fee_cents": service_fee,
        "total_charge_cents": total_charge,
        "prepared_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "approval_status": approval_status,
        "settlement_status": "SCHEDULED",
        "projected_settlement_date": projected,
        "effective_settlement_date": None,
        "released_at": None,
        "settled_on": None,
        "revision_count": 0,
        "return_reason": None,
        "stop_reason": None,
    })
    set_subject(payment["id"])
    recompute_payment_aggregates(payment)
    bump(account)
    return object_response(serialize.payment(payment), 201)


def _has_duplicate(account_id, payee_id, amount_cents, projected):
    for other in all_of("payments"):
        if other["account_id"] != account_id or other["payee_id"] != payee_id:
            continue
        if other["amount_cents"] != amount_cents:
            continue
        if other["settlement_status"] not in ("SCHEDULED", "IN_FLIGHT"):
            continue
        gap = calc.days_between(other["projected_settlement_date"], projected)
        if gap is not None and abs(gap) <= K.DUPLICATE_PAYMENT_BUFFER_DAYS:
            return True
    return False


@bp.post("/dmm/payments/<pid>/approval-decision")
@audited("Payment", path_param="pid")
def approval_decision(pid):
    ctx = authorize("FiduciaryManager", "ComplianceOfficer")   # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("decision", str, True),
        ("note", str, False),
    ])
    ctx.check_enum("decision", K.APPROVAL_DECISION)            # rung 5

    # rung 12 - the approval axis only, plus the same-axis-row condition that
    # settlement_status must still be SCHEDULED.
    if payment["approval_status"] != "PENDING_SECOND_APPROVAL":
        fail("ERR_INVALID_STATE", "The payment is not awaiting second approval.")
    if payment["settlement_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "The payment is no longer SCHEDULED.")

    if ctx.user_id == payment["prepared_by_user_id"]:          # rung 29
        fail("ERR_SEGREGATION_OF_DUTIES", "A preparer may not approve their own disbursement.")

    if ctx.body["decision"] == "APPROVE":
        payment["approval_status"] = "APPROVED"
        payment["approved_by_user_id"] = ctx.user_id
    else:
        payment["approval_status"] = "REJECTED"
        payment["approved_by_user_id"] = None
    bump(payment)
    return object_response(serialize.payment(payment), 200)


@bp.post("/dmm/payments/<pid>/revise")
@audited("Payment", path_param="pid")
def revise_payment(pid):
    ctx = authorize("BillPaySpecialist")                       # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    payee = db.payees.get(payment["payee_id"])
    auth = db.authorizations.get(payment["authorization_id"])
    line = db.budget_categories.get(payment["budget_category_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("amount_cents", int, True),
        ("memo", str, False),
    ])

    gate_bond()                                                # rung 6
    gate_authorization(auth)                                   # rung 7
    gate_scope_payment(auth, payee)                            # rung 8
    gate_account_frozen(account)                               # rung 9
    gate_period_frozen_now(account)                            # rung 10
    gate_client_active(_client_of_account(account))            # rung 11

    if payment["approval_status"] != "REJECTED":               # rung 12
        fail("ERR_INVALID_STATE", "Only a REJECTED payment may be reworked.")
    if payment["settlement_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "The payment is no longer SCHEDULED.")

    amount = ctx.body["amount_cents"]
    if amount <= 0:                                            # rung 15
        fail("ERR_VALIDATION", "amount_cents must be greater than zero.")

    if payee["status"] != "ACTIVE":                            # rung 28
        fail("ERR_PAYEE_BLOCKED", "The payee is blocked.")

    ceiling = calc.scope_amount_ceiling(auth["scope_tier"])    # rung 33
    if ceiling is not None and amount > ceiling:
        fail("ERR_SCOPE_AMOUNT_EXCEEDED", "The instrument's per-payment ceiling is exceeded.")

    service_fee = calc.service_fee_cents(amount)
    total_charge = amount + service_fee
    old_amount = payment["amount_cents"]
    old_total = payment["total_charge_cents"]

    bond = in_force_bond()                                     # rung 35
    if bond["exposure_committed_cents"] - old_amount + amount > bond["coverage_cents"]:
        fail("ERR_BOND_COVERAGE_EXCEEDED", "The bond's committed coverage is exhausted.")

    capacity = line["allocation_cents"] + line["override_granted_cents"]   # rung 36
    if line["committed_cents"] - old_amount + amount > capacity:
        fail("ERR_BUDGET_EXCEEDED", "The budget line has insufficient capacity.")

    if account["available_balance_cents"] + old_total < total_charge:      # rung 37
        fail("ERR_INSUFFICIENT_AVAILABLE", "The account has insufficient available funds.")

    payment["amount_cents"] = amount
    if "memo" in ctx.body and ctx.body.get("memo") is not None:
        payment["memo"] = ctx.body["memo"]
    payment["service_fee_cents"] = service_fee
    payment["total_charge_cents"] = total_charge
    payment["revision_count"] += 1
    payment["approval_status"] = (
        "PENDING_SECOND_APPROVAL"
        if amount >= K.SECOND_APPROVAL_THRESHOLD_CENTS
        else "APPROVED"
    )
    bump(payment)
    recompute_payment_aggregates(payment)
    return object_response(serialize.payment(payment), 200)


@bp.post("/dmm/payments/<pid>/release")
@audited("Payment", path_param="pid")
def release_payment(pid):
    ctx = authorize("BillPaySpecialist")                       # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    auth = db.authorizations.get(payment["authorization_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([])                                        # rung 4 - no input

    gate_bond()                                                # rung 6
    gate_authorization(auth)                                   # rung 7
    gate_account_frozen(account)                               # rung 9
    gate_client_active(_client_of_account(account))            # rung 11

    if payment["settlement_status"] != "SCHEDULED":            # rung 12
        fail("ERR_INVALID_STATE", "Only a SCHEDULED payment may be released.")

    if payment["approval_status"] != "APPROVED":               # rung 30
        fail("ERR_SECOND_APPROVAL_REQUIRED", "The payment still needs second approval.")

    payment["settlement_status"] = "IN_FLIGHT"
    payment["released_at"] = db.now
    # The effective variant runs at the release instant with the
    # requested_send_date treated as absent.
    payment["effective_settlement_date"] = calc.settlement_date(
        db.now, None, payment["channel"]
    )
    bump(payment)
    return object_response(serialize.payment(payment), 200)


@bp.post("/dmm/payments/<pid>/settlement-event")
@audited("Payment", path_param="pid")
def settlement_event(pid):
    ctx = authorize("BillPaySpecialist")                       # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("event", str, True),
        ("return_reason", str, False),
    ])
    if ctx.body.get("event") == "RETURN":
        ctx.require_conditional("return_reason")
    ctx.check_enum("event", K.SETTLEMENT_EVENT)                # rung 5

    gate_account_frozen(account)                               # rung 9
    gate_period_frozen_now(account)                            # rung 10

    event = ctx.body["event"]
    if event == "SETTLE":                                      # rung 12
        if payment["settlement_status"] != "IN_FLIGHT":
            fail("ERR_INVALID_STATE", "Only an IN_FLIGHT payment may settle.")
    else:
        if payment["settlement_status"] != "SETTLED":
            fail("ERR_INVALID_STATE", "Only a SETTLED payment may be returned.")
        if ctx.body["return_reason"].strip() == "":            # rung 15
            fail("ERR_VALIDATION", "return_reason must not be empty.")

    payee = db.payees.get(payment["payee_id"])
    if event == "SETTLE":
        payment["settlement_status"] = "SETTLED"
        payment["settled_on"] = db.today_str()
        if payee is not None:
            payee["settled_payment_count"] += 1
        append_ledger_entry(
            account, "DISBURSEMENT", -payment["amount_cents"], db.today_str(),
            memo="Disbursement", source_payment_id=payment["id"],
        )
        append_ledger_entry(
            account, "SERVICE_FEE", -payment["service_fee_cents"], db.today_str(),
            memo="Fiduciary service fee", source_payment_id=payment["id"],
        )
    else:
        payment["settlement_status"] = "RETURNED"
        payment["return_reason"] = ctx.body["return_reason"]
        if payee is not None:
            payee["settled_payment_count"] -= 1
        append_ledger_entry(
            account, "RETURN_REVERSAL", payment["total_charge_cents"], db.today_str(),
            memo="Return reversal", source_payment_id=payment["id"],
        )
        append_ledger_entry(
            account, "NSF_FEE", -K.NSF_FEE_CENTS, db.today_str(),
            memo="Insufficient funds fee", source_payment_id=payment["id"],
        )

    bump(payment)
    recompute_payment_aggregates(payment)
    return object_response(serialize.payment(payment), 200)


@bp.post("/dmm/payments/<pid>/cancel")
@audited("Payment", path_param="pid")
def cancel_payment(pid):
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([("reason", str, False)])                  # rung 4

    if payment["settlement_status"] != "SCHEDULED":            # rung 12
        fail("ERR_INVALID_STATE", "Only a SCHEDULED payment may be cancelled.")

    cancel_payment_row(payment)
    return object_response(serialize.payment(payment), 200)


@bp.post("/dmm/payments/<pid>/stop-payment")
@audited("Payment", path_param="pid")
def stop_payment(pid):
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    payment = resolve("payments", pid)                         # rung 3
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([("stop_reason", str, True)])              # rung 4

    gate_period_frozen_now(account)                            # rung 10

    if payment["settlement_status"] not in ("SCHEDULED", "IN_FLIGHT"):   # rung 12
        fail("ERR_INVALID_STATE", "The payment can no longer be stopped.")

    deadline = payment["created_at"] + timedelta(hours=K.STOP_PAYMENT_WINDOW_HOURS)
    if db.now > deadline:                                      # rung 21
        fail("ERR_STOP_WINDOW_EXPIRED", "The stop-payment window has closed.")

    payment["stop_reason"] = ctx.body["stop_reason"]
    stop_payment_row(payment)
    return object_response(serialize.payment(payment), 200)


@bp.get("/dmm/payments")
def list_payments():
    authorize(*READ_ROLES)
    rows = db.ordered("payments")
    for field in ("account_id", "payee_id", "authorization_id",
                  "budget_category_id", "approval_status", "settlement_status"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.payment)


@bp.get("/dmm/payments/<pid>")
def read_payment(pid):
    authorize(*READ_ROLES)
    return object_response(serialize.payment(resolve("payments", pid)), 200)


@bp.get("/dmm/payments/<pid>/disputes")
def list_payment_disputes(pid):
    authorize(*READ_ROLES)
    resolve("payments", pid)
    rows = [d for d in db.ordered("disputes") if d["payment_id"] == pid]
    return paginate(rows, serialize.dispute)
