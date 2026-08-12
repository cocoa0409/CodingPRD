"""Payee registration and the compliance block sweep."""

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import cancel_payment_row
from core.audit import set_client, set_subject
from core.envelope import object_response
from core.errors import fail
from core.pipeline import audited, authorize, resolve, resolve_body_client
from core.store import bump, db, new_row

bp = Blueprint("payees", __name__)


@bp.post("/dmm/payees")
@audited("Payee")
def register_payee():
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("payee_name", str, True),
        ("payee_type", str, True),
        ("remittance_reference", str, True),
    ])
    ctx.check_enum("payee_type", K.PAYEE_TYPE)                 # rung 5

    row = new_row("payees", {
        "client_id": client_row["id"],
        "payee_name": ctx.body["payee_name"],
        "payee_type": ctx.body["payee_type"],
        "remittance_reference": ctx.body["remittance_reference"],
        "status": "ACTIVE",
        "blocked_reason": None,
        "settled_payment_count": 0,
    })
    set_subject(row["id"])
    return object_response(serialize.payee(row), 201)


@bp.post("/dmm/payees/<pid>/block")
@audited("Payee", path_param="pid")
def block_payee(pid):
    ctx = authorize("ComplianceOfficer")                       # rungs 1-2
    payee = resolve("payees", pid)                             # rung 3
    set_client(payee["client_id"])
    ctx.check_shape([("blocked_reason", str, True)])           # rung 4

    if payee["status"] != "ACTIVE":                            # rung 12
        fail("ERR_INVALID_STATE", "Only an ACTIVE payee may be blocked.")

    payee["status"] = "BLOCKED"
    payee["blocked_reason"] = ctx.body["blocked_reason"]
    for payment in db.ordered("payments"):
        if payment["payee_id"] != payee["id"]:
            continue
        if payment["settlement_status"] != "SCHEDULED":
            continue
        cancel_payment_row(payment)
    bump(payee)
    return object_response(serialize.payee(payee), 200)


@bp.get("/dmm/payees/<pid>")
def read_payee(pid):
    authorize("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer",
              "PlatformAdmin")
    return object_response(serialize.payee(resolve("payees", pid)), 200)
