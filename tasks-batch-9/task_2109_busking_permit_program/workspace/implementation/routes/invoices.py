"""Fee invoices and their settlement (PRD section 3.5)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_state, raise_err
from gates import P_BODY, P_OWNER, P_PATH, P_PAYMENT_AMOUNT, P_STATE, resolve, run_gates
from middleware import PERFORMER, PERMIT_OFFICER, require_owner, require_roles
from response import ok_object
from services import domain
from services.serializers import serialize
from utils import touch

bp = Blueprint("invoices", __name__, url_prefix="/busking")


@bp.post("/fee-invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    user_id, role = require_roles([PERFORMER, PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def resolve_invoice():
        ctx["invoice"] = resolve("invoices", invoice_id)
        ctx["permit"] = db.get("permits", ctx["invoice"]["permit_id"])

    def check_body():
        ctx["amount"] = body.req_int("amount_cents")

    def check_state():
        if ctx["invoice"]["status"] not in ("PENDING", "PAST_DUE"):
            invalid_state("Only a PENDING or PAST_DUE invoice can be settled")

    def check_amount():
        if ctx["amount"] != ctx["invoice"]["amount_due_cents"]:
            raise_err("ERR_PAYMENT_AMOUNT_MISMATCH",
                      "The tendered amount must equal amount_due_cents exactly")

    run_gates([
        (P_PATH, resolve_invoice),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_PAYMENT_AMOUNT, check_amount),
    ])

    invoice = ctx["invoice"]
    permit = ctx["permit"]
    clock = db.now()

    invoice["status"] = "PAID"
    invoice["amount_paid_cents"] = ctx["amount"]
    invoice["paid_at"] = clock
    touch(invoice)

    permit["net_fees_paid_cents"] += invoice["amount_paid_cents"]
    if invoice["invoice_kind"] == "INITIAL" and permit["lifecycle_status"] == "PENDING_FEE":
        permit["lifecycle_status"] = "ACTIVE"
        permit["activated_at"] = clock
    elif invoice["invoice_kind"] == "RENEWAL" and permit["lifecycle_status"] == "RENEWAL_PENDING":
        permit["lifecycle_status"] = "ACTIVE"
        permit["season_year"] = permit["next_season_year"]
        permit["next_season_year"] = None
        permit["season_minutes_used"] = 0
        permit["closure_credit_minutes"] = 0
        permit["noise_violation_count"] = 0
        performer = domain.performer_of(permit)
        if performer is not None:
            performer["premium_wins_this_season"] = 0
            touch(performer)
    touch(permit)
    return ok_object(serialize(invoice))
