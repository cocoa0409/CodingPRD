"""Disputes, provisional credit and resolution."""

from flask import Blueprint

from core import calc
from core import constants as K
from core import serialize
from core.aggregates import append_ledger_entry, recompute_account
from core.audit import set_client, set_subject
from core.envelope import object_response
from core.errors import fail
from core.gates import (
    gate_account_frozen,
    gate_client_active,
    gate_period_frozen_now,
)
from core.pipeline import audited, authorize, resolve, resolve_body_ref
from core.store import bump, db, new_row

bp = Blueprint("disputes", __name__)


def _account_of_payment(payment):
    return db.accounts.get(payment["account_id"]) if payment else None


def _client_of_payment(payment):
    account = _account_of_payment(payment)
    return db.clients.get(account["client_id"]) if account else None


@bp.post("/dmm/disputes")
@audited("Dispute")
def file_dispute():
    ctx = authorize("FiduciaryManager", "ComplianceOfficer")   # rungs 1-2
    payment = resolve_body_ref(ctx, "payment_id", "payments")  # rung 3
    if payment is not None:
        account = _account_of_payment(payment)
        if account is not None:
            set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("payment_id", str, True),
        ("reason_code", str, True),
        ("disputed_amount_cents", int, True),
    ])
    ctx.check_enum("reason_code", K.DISPUTE_REASON_CODE)       # rung 5

    gate_client_active(_client_of_payment(payment))            # rung 11

    disputed = ctx.body["disputed_amount_cents"]
    if disputed <= 0 or disputed > payment["amount_cents"]:    # rung 15
        fail("ERR_VALIDATION", "disputed_amount_cents is out of range.")

    filed_on = db.today_str()                                  # rung 22
    days = calc.days_between(payment.get("settled_on"), filed_on)
    if days is None or days > K.DISPUTE_FILING_WINDOW_DAYS:
        fail("ERR_DISPUTE_WINDOW_EXPIRED", "The dispute filing window has closed.")

    row = new_row("disputes", {
        "payment_id": payment["id"],
        "reason_code": ctx.body["reason_code"],
        "disputed_amount_cents": disputed,
        "filed_on": filed_on,
        "days_since_settlement": days,
        "provisional_credit_cents": 0,
        "status": "FILED",
        "resolution_note": None,
    })
    set_subject(row["id"])
    return object_response(serialize.dispute(row), 201)


@bp.post("/dmm/disputes/<did>/provisional-credit")
@audited("Dispute", path_param="did")
def apply_provisional_credit(did):
    ctx = authorize("ComplianceOfficer")                       # rungs 1-2
    dispute = resolve("disputes", did)                         # rung 3
    payment = db.payments.get(dispute["payment_id"])
    account = _account_of_payment(payment)
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([])                                        # rung 4

    gate_account_frozen(account)                               # rung 9
    gate_period_frozen_now(account)                            # rung 10

    if dispute["status"] != "FILED":                           # rung 12
        fail("ERR_INVALID_STATE", "Only a FILED dispute may be credited.")

    if dispute["disputed_amount_cents"] > K.DISPUTE_PROVISIONAL_CREDIT_MAX_CENTS:
        fail("ERR_CREDIT_CAP_EXCEEDED", "The provisional credit cap is exceeded.")  # rung 39

    dispute["status"] = "PROVISIONAL_CREDITED"
    dispute["provisional_credit_cents"] = dispute["disputed_amount_cents"]
    append_ledger_entry(
        account, "DISPUTE_PROVISIONAL_CREDIT", dispute["provisional_credit_cents"],
        db.today_str(), memo="Dispute provisional credit",
        source_payment_id=payment["id"],
    )
    recompute_account(account)
    bump(dispute)
    return object_response(serialize.dispute(dispute), 200)


@bp.post("/dmm/disputes/<did>/resolve")
@audited("Dispute", path_param="did")
def resolve_dispute(did):
    ctx = authorize("ComplianceOfficer")                       # rungs 1-2
    dispute = resolve("disputes", did)                         # rung 3
    payment = db.payments.get(dispute["payment_id"])
    account = _account_of_payment(payment)
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("outcome", str, True),
        ("resolution_note", str, False),
    ])
    ctx.check_enum("outcome", K.DISPUTE_OUTCOME)               # rung 5

    gate_period_frozen_now(account)                            # rung 10

    outcome = ctx.body["outcome"]
    source = dispute["status"]
    if source not in ("FILED", "PROVISIONAL_CREDITED"):        # rung 12
        fail("ERR_INVALID_STATE", "The dispute is already resolved.")

    if source == "FILED" and outcome == "UPHELD":              # rung 39
        if dispute["disputed_amount_cents"] > K.DISPUTE_PROVISIONAL_CREDIT_MAX_CENTS:
            fail("ERR_CREDIT_CAP_EXCEEDED", "The provisional credit cap is exceeded.")

    if source == "PROVISIONAL_CREDITED" and outcome == "DENIED":
        append_ledger_entry(
            account, "DISPUTE_CREDIT_REVERSAL", -dispute["provisional_credit_cents"],
            db.today_str(), memo="Dispute credit reversal",
            source_payment_id=payment["id"],
        )
        recompute_account(account)
    elif source == "FILED" and outcome == "UPHELD":
        dispute["provisional_credit_cents"] = dispute["disputed_amount_cents"]
        append_ledger_entry(
            account, "DISPUTE_PROVISIONAL_CREDIT", dispute["disputed_amount_cents"],
            db.today_str(), memo="Dispute credit on resolution",
            source_payment_id=payment["id"],
        )
        recompute_account(account)

    dispute["status"] = outcome
    if ctx.body.get("resolution_note") is not None:
        dispute["resolution_note"] = ctx.body["resolution_note"]
    bump(dispute)
    return object_response(serialize.dispute(dispute), 200)


@bp.get("/dmm/disputes/<did>")
def read_dispute(did):
    authorize("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer",
              "PlatformAdmin")
    return object_response(serialize.dispute(resolve("disputes", did)), 200)
