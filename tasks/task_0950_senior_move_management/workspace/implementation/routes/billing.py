"""The invoice lifecycle and the immutable ledger."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered

bp = Blueprint("billing", __name__)

INVOICE_READ = ["BILLING_ADMIN", "MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY", "FAMILY_MEMBER"]
LINE_READ = ["BILLING_ADMIN", "MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"]
INVOICE_TERMINAL = ["FINALIZED"]

# `amount_cents` on a charge line must be positive (ladder rung 5). A
# CONSIGNMENT_CREDIT line is a credit and a MANUAL_ADJUSTMENT may be either, so
# those two admit a negative amount; zero is neither a charge nor a credit and
# is refused for every line type.
SIGNED_LINE_TYPES = {"CONSIGNMENT_CREDIT", "MANUAL_ADJUSTMENT"}


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    req = gates.preflight(INVOICE_READ, is_list=True)
    rows = filtered(store.all_of("invoices"), req.args, ["engagement_id", "status"])
    return listing("invoices", req, rows)


@bp.route("/invoices/<iid>", methods=["GET"])
def read_invoice(iid):
    req = gates.preflight(INVOICE_READ)
    record = gates.path_record("invoices", iid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("invoices", record)


def _invoice_context(iid):
    record = gates.path_record("invoices", iid)
    engagement = store.get("engagements", record["engagement_id"])
    return record, engagement


@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    req = gates.preflight(["BILLING_ADMIN"])
    record, engagement = _invoice_context(iid)
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["DRAFT"], INVOICE_TERMINAL)
    move_day = derive.milestone_by_key(engagement["id"], "MOVE_DAY")
    gates.require_state(move_day is not None and move_day["status"] == "COMPLETE")
    services.issue_invoice(record, engagement, req.role)
    return one("invoices", record)


@bp.route("/invoices/<iid>/recall", methods=["POST"])
def recall_invoice(iid):
    req = gates.preflight(["BILLING_ADMIN"], required=[("reason", "nes")])
    record, engagement = _invoice_context(iid)
    gates.gate3(engagement)
    if record["status"] == "FINALIZED":
        raise ApiError("ERR_INVOICE_FINALIZED")
    gates.gate10_state(record["status"], ["ISSUED"], INVOICE_TERMINAL)
    gates.require_state(record["payments_cents"] == 0)
    if record["recall_count"] >= K.MAX_INVOICE_RECALLS:
        raise ApiError("ERR_INVOICE_ACTION_LIMIT")

    record["recall_count"] = record["recall_count"] + 1
    record["status"] = "DRAFT"
    services.remove_lines(record, "COORDINATION_FEE")
    record["coordination_fee_cents"] = 0
    store.touch(record)
    return one("invoices", record)


@bp.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    req = gates.preflight(["CLIENT", "POWER_OF_ATTORNEY", "FAMILY_MEMBER"],
                          required=[("reason", "nes"), ("raised_by_party_id", "string")])
    record, engagement = _invoice_context(iid)
    gates.resolve_body_fks(req.body)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["raised_by_party_id"]])
    gates.gate4_authority(req, "BILLING")
    if record["status"] == "FINALIZED":
        raise ApiError("ERR_INVOICE_FINALIZED")
    gates.gate10_state(record["status"], ["ISSUED"], INVOICE_TERMINAL)
    if record["dispute_count"] >= K.MAX_INVOICE_DISPUTES:
        raise ApiError("ERR_INVOICE_ACTION_LIMIT")

    record["status"] = "DISPUTED"
    record["dispute_count"] = record["dispute_count"] + 1
    record["dispute_reason"] = req.body["reason"]
    store.touch(record)
    return one("invoices", record)


@bp.route("/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_dispute(iid):
    # `resolution` here is free text, not the family-hold enum
    gates.preflight(["BILLING_ADMIN"], required=[("resolution", "string")], enum_fields=[])
    record, engagement = _invoice_context(iid)
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["DISPUTED"], INVOICE_TERMINAL)
    record["status"] = "ISSUED"
    record["dispute_reason"] = None
    store.touch(record)
    return one("invoices", record)


@bp.route("/invoices/<iid>/finalize", methods=["POST"])
def finalize_invoice(iid):
    gates.preflight(["BILLING_ADMIN"])
    record, engagement = _invoice_context(iid)
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["ISSUED"], INVOICE_TERMINAL)
    for lot in store.where("consignment_lots", engagement_id=engagement["id"]):
        if lot["status"] in ("SOLD", "SETTLED") and lot["credited"] and not lot["reversed"]:
            raise ApiError("ERR_INVALID_STATE")
    if derive.invoice_balance_due(record) > 0:
        raise ApiError("ERR_BALANCE_OUTSTANDING")

    record["status"] = "FINALIZED"
    record["finalized_at_utc"] = store.now_iso()
    store.touch(record)
    return one("invoices", record)


@bp.route("/invoices/<iid>/record-payment", methods=["POST"])
def record_payment(iid):
    req = gates.preflight(["BILLING_ADMIN"],
                          required=[("amount_cents", "int"), ("paid_on", "date")])
    record, engagement = _invoice_context(iid)
    gates.gate3(engagement)
    if record["status"] == "FINALIZED":
        raise ApiError("ERR_INVOICE_FINALIZED")

    record["payments_cents"] = record["payments_cents"] + req.body["amount_cents"]
    store.touch(record)
    return one("invoices", record)


# ---------------------------------------------------------------------------
# ledger lines
# ---------------------------------------------------------------------------

@bp.route("/invoice-lines", methods=["POST"])
def create_invoice_line():
    req = gates.preflight(["BILLING_ADMIN"],
                          required=[("invoice_id", "string"), ("line_type", "string"),
                                    ("amount_cents", "int"), ("memo", "string"),
                                    ("expected_invoice_version", "int")],
                          optional=[("source_consignment_lot_id", "string")])
    amount = req.body["amount_cents"]
    if amount == 0 or (amount < 0 and req.body["line_type"] not in SIGNED_LINE_TYPES):
        raise ApiError("ERR_VALIDATION", "amount_cents must be positive on a charge line.")

    fks = gates.resolve_body_fks(req.body)
    invoice = fks["invoice_id"]
    engagement = store.get("engagements", invoice["engagement_id"])
    gates.gate3(engagement)
    if invoice["status"] == "FINALIZED":
        raise ApiError("ERR_INVOICE_FINALIZED")
    gates.require_state(invoice["status"] in ("DRAFT", "ISSUED"))
    gates.gate11_version(req.body["expected_invoice_version"], invoice,
                         "ERR_STALE_INVOICE_VERSION")

    record = services.append_line(invoice, req.body["line_type"], amount,
                                  req.body["memo"], req.role,
                                  source_consignment_lot_id=req.body.get(
                                      "source_consignment_lot_id"))
    return one("invoice_lines", record, 201)


@bp.route("/invoice-lines", methods=["GET"])
def list_invoice_lines():
    req = gates.preflight(LINE_READ, is_list=True)
    rows = filtered(store.all_of("invoice_lines"), req.args,
                    ["invoice_id", "source_consignment_lot_id", "line_type"])
    return listing("invoice_lines", req, rows)


@bp.route("/invoice-lines/<lid>", methods=["GET"])
def read_invoice_line(lid):
    req = gates.preflight(LINE_READ)
    record = gates.path_record("invoice_lines", lid)
    invoice = store.get("invoices", record["invoice_id"])
    gates.gate4_ownership(req, engagement=store.get("engagements", invoice["engagement_id"]))
    return one("invoice_lines", record)
