"""Settlement lines and the installment payment schedule."""
from flask import Blueprint

import cascades
import derive
import validation as v
from authz import (ACCOUNTS_PAYABLE_CLERK, GROWER, GROWER_RELATIONS_MANAGER,
                   QUALITY_LAB_TECH, auth, own)
from common import (CLOCK, by_created_asc, fail, read_body, respond,
                    respond_list, rows, touch)
from lookup import contract_writable, find, not_suspended

bp = Blueprint("money", __name__)

PAYABLE = ("SCHEDULED", "PARTIALLY_PAID", "DELINQUENT")
LIEN_OPEN = ("SCHEDULED", "PARTIALLY_PAID", "DELINQUENT")


# --------------------------------------------------------------------------
# Settlement lines
# --------------------------------------------------------------------------
@bp.get("/grower-relations/settlement-lines/<line_id>")
def get_line(line_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, ACCOUNTS_PAYABLE_CLERK,
                         QUALITY_LAB_TECH, GROWER)
    line = find("lines", line_id)
    contract = find("contracts", line["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.line_json(line))


@bp.get("/grower-relations/settlement-lines")
def list_lines():
    auth(GROWER_RELATIONS_MANAGER, ACCOUNTS_PAYABLE_CLERK, QUALITY_LAB_TECH)
    limit, offset = v.pagination()
    contract_id = v.filt("contract_id")
    weigh_tag_id = v.filt("weigh_tag_id")
    bucket = v.filt("bucket")
    status = v.filt("status")
    items = rows("lines")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if weigh_tag_id is not None:
        items = [r for r in items if r["weigh_tag_id"] == weigh_tag_id]
    if bucket is not None:
        items = [r for r in items if r["bucket"] == bucket]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.line_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Recording a payment
# --------------------------------------------------------------------------
@bp.post("/grower-relations/payment-installments/<installment_id>/payments")
def record_payment(installment_id):
    auth(ACCOUNTS_PAYABLE_CLERK)
    installment = find("installments", installment_id)
    body = read_body()
    amount = v.req_int(body, "amount_cents", minimum=1)

    contract = find("contracts", installment["contract_id"])

    # rank 20
    contract_writable(contract)
    # rank 26
    if installment["status"] not in PAYABLE:
        fail("ERR_INSTALLMENT_NOT_PAYABLE",
             "An installment in status '%s' is not payable."
             % installment["status"])
    # rank 31
    not_suspended(find("growers", contract["grower_id"]))
    # rank 47
    balance = (int(installment["planned_amount_cents"])
               - int(installment["paid_amount_cents"]))
    if amount > balance:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE",
             "amount_cents may not exceed the outstanding balance of %d cents."
             % balance)

    installment["paid_amount_cents"] = int(installment["paid_amount_cents"]) + amount
    if amount < balance:
        installment["status"] = "PARTIALLY_PAID"
    else:
        installment["status"] = "PAID"
    touch(installment)

    siblings = derive.installments_of_contract(contract["id"])
    contract_changed = False

    if installment["lien_protected"]:
        cascades.touch_grower(contract["grower_id"])
        outstanding = [row for row in siblings
                       if row["lien_protected"] and row["status"] in LIEN_OPEN]
        if not outstanding and contract["lien_released_at"] is None:
            contract["lien_released_at"] = CLOCK.now
            contract_changed = True

    if (contract["lifecycle_status"] == "SETTLED"
            and all(row["status"] == "PAID" for row in siblings)):
        contract["lifecycle_status"] = "CLOSED"
        if contract["lien_released_at"] is None:
            contract["lien_released_at"] = CLOCK.now
        contract_changed = True

    if contract_changed:
        touch(contract)

    return respond(derive.installment_json(installment))


@bp.get("/grower-relations/payment-installments/<installment_id>")
def get_installment(installment_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, ACCOUNTS_PAYABLE_CLERK, GROWER)
    installment = find("installments", installment_id)
    contract = find("contracts", installment["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.installment_json(installment))


@bp.get("/grower-relations/payment-installments")
def list_installments():
    auth(GROWER_RELATIONS_MANAGER, ACCOUNTS_PAYABLE_CLERK)
    limit, offset = v.pagination()
    contract_id = v.filt("contract_id")
    status = v.filt("status")
    lien_protected = v.filt_bool("lien_protected")
    items = rows("installments")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if lien_protected is not None:
        items = [r for r in items if bool(r["lien_protected"]) == lien_protected]
    items = sorted(by_created_asc(items), key=lambda r: int(r["installment_no"]))
    total = len(items)
    return respond_list(
        [derive.installment_json(r) for r in v.page(items, limit, offset)],
        total, limit, offset)
