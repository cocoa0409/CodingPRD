"""Invoices: issuance and the compensating void (PRD 3.8)."""

from flask import Blueprint

import derive
import enums
import lookup
from auth import ROLE_CPA_ADMINISTRATOR, any_role, require
from core import clock
from db import public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("invoices", __name__)

LIST_FILTERS = (
    ("cycle_id", "cycle_id", None),
    ("status", "status", enums.INVOICE_STATUS),
    ("variant", "variant", enums.INVOICE_VARIANT),
)

PASSTHROUGH_TERMINAL = ("RECONCILED", "REJECTED")


def _cycle_of(invoice):
    return store.schedule_cycles[invoice["cycle_id"]]


@bp.route("/invoices", methods=["GET"])
@any_role()
def list_invoices():
    return collection_listing("invoices", LIST_FILTERS)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
@any_role()
def read_invoice(invoice_id):
    return object_response(public(lookup.invoice(invoice_id)))


@bp.route("/invoices/<invoice_id>/issue-final", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def issue_final(invoice_id):
    invoice = lookup.invoice(invoice_id)

    guard_terminal(invoice, enums.INVOICE_TERMINAL)
    guard_state(invoice["status"] == "DRAFT")

    cycle = _cycle_of(invoice)
    if invoice["variant"] != "FINAL":
        fail("ERR_INVOICE_VARIANT_NOT_FINAL")
    guard_state(cycle["status"] == "CLOSED",
                "The settlement month is not CLOSED")

    unreconciled = any(claim["cycle_id"] == cycle["id"]
                       and claim["status"] not in PASSTHROUGH_TERMINAL
                       for claim in store.passthrough_claims.values())
    if unreconciled:
        fail("ERR_PASSTHROUGH_UNRECONCILED")

    if derive.stale_scorecards_of_cycle_exist(cycle["id"]):
        fail("ERR_SCORECARD_STALE")

    invoice["status"] = "ISSUED"
    invoice["issued_final_at"] = clock.iso()
    touch(invoice)

    cycle["status"] = "SETTLED"
    touch(cycle)

    derive.refresh_agreement(derive.agreement_of_cycle(cycle))

    return object_response(public(invoice))


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def void(invoice_id):
    invoice = lookup.invoice(invoice_id)

    guard_terminal(invoice, enums.INVOICE_TERMINAL)
    guard_state(invoice["status"] in ("DRAFT", "ISSUED"))

    derive.void_invoice(invoice, "MANUAL")

    return object_response(public(invoice))
