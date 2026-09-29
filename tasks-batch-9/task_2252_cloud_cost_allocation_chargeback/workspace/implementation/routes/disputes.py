"""Dispute filing and credit adjudication (PRD 3.7)."""
from flask import Blueprint

from db import base_fields, db, now, touch
from errors import fail
from middleware import authorize, user_id
from routes.common import lookup, optional_ref, require_bu_owner, serve, serve_list
from services import derived, flows
from services.calc import MAX_DISPUTE_ROUNDS
from validation import body, present, req_enum, req_int, req_str

bp = Blueprint("disputes", __name__)

READERS = ("FinOpsController", "FinOpsAnalyst", "PlatformAdmin", "BusinessUnitOwner")
REASONS = ("WRONG_OWNER", "SHARED_METHODOLOGY", "UNTAGGED_ABSORPTION", "DOUBLE_CHARGE")
OUTCOMES = ("ADJUSTED", "UPHELD")
OPEN_STATES = ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED")


def _outstanding(invoice):
    return (
        invoice["gross_amount_cents"]
        - invoice["credited_amount_cents"]
        - invoice["paid_amount_cents"]
    )


@bp.route("/finops/disputes", methods=["POST"])
@authorize("BusinessUnitOwner")
def file_dispute():
    data = body()
    invoice = optional_ref("chargeback_invoices", req_str(data, "chargeback_invoice_id"))
    require_bu_owner(invoice["business_unit_id"])
    reason_code = req_enum(data, "reason_code", REASONS)
    claimed = req_int(data, "claimed_credit_cents", exclusive_minimum=0)
    narrative = req_str(data, "narrative")

    derived.invoice_sync(invoice, bump=False)
    if (
        invoice["settlement_status"] not in ("ISSUED", "PARTIALLY_CREDITED")
        or invoice["dispute_status"] != "NONE"
    ):
        fail("ERR_INVOICE_NOT_DISPUTABLE", "The invoice is not open to a new dispute.")

    window_end = invoice.get("_dispute_window_ends_at_dt")
    if window_end is None or now() > window_end:
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The invoice's dispute window has closed.")

    if claimed > _outstanding(invoice):
        fail(
            "ERR_CREDIT_EXCEEDS_INVOICE",
            "claimed_credit_cents exceeds the invoice's outstanding amount.",
        )

    dispute = base_fields()
    dispute.update(
        {
            "chargeback_invoice_id": invoice["id"],
            "filed_by_business_unit_id": invoice["business_unit_id"],
            "reason_code": reason_code,
            "claimed_credit_cents": claimed,
            "narrative": narrative,
            "status": "OPEN",
            "review_round": 0,
            "filed_by_user_id": user_id(),
            "resolved_by_user_id": None,
            "outcome": None,
            "granted_credit_cents": 0,
            "_last_question": None,
        }
    )
    db.disputes[dispute["id"]] = dispute

    invoice["dispute_status"] = "DISPUTED"
    touch(invoice)
    flows.hold_invoice_records(invoice)
    return serve(dispute, 201)


@bp.route("/finops/disputes", methods=["GET"])
@authorize(*READERS)
def list_disputes():
    return serve_list(
        db.disputes.values(),
        {
            "chargeback_invoice_id": "chargeback_invoice_id",
            "filed_by_business_unit_id": "filed_by_business_unit_id",
            "status": "status",
        },
    )


@bp.route("/finops/disputes/<dispute_id>", methods=["GET"])
@authorize(*READERS)
def get_dispute(dispute_id):
    return serve(lookup("disputes", dispute_id))


@bp.route("/finops/disputes/<dispute_id>/start-review", methods=["POST"])
@authorize("FinOpsController")
def start_review(dispute_id):
    dispute = lookup("disputes", dispute_id)
    if dispute["status"] != "OPEN":
        fail("ERR_DISPUTE_STATE_INVALID", "Only an OPEN dispute may enter review.")
    if dispute["review_round"] >= MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUND_LIMIT", "The dispute has exhausted its review rounds.")
    dispute["status"] = "UNDER_REVIEW"
    dispute["review_round"] = dispute["review_round"] + 1
    touch(dispute)
    return serve(dispute)


@bp.route("/finops/disputes/<dispute_id>/request-info", methods=["POST"])
@authorize("FinOpsController")
def request_info(dispute_id):
    dispute = lookup("disputes", dispute_id)
    data = body()
    question = req_str(data, "question")
    if dispute["status"] != "UNDER_REVIEW":
        fail(
            "ERR_DISPUTE_STATE_INVALID",
            "Only a dispute UNDER_REVIEW may have information requested.",
        )
    if dispute["review_round"] > MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUND_LIMIT", "The dispute has exhausted its review rounds.")
    dispute["status"] = "INFO_REQUESTED"
    dispute["_last_question"] = question
    touch(dispute)
    return serve(dispute)


@bp.route("/finops/disputes/<dispute_id>/respond", methods=["POST"])
@authorize("BusinessUnitOwner")
def respond(dispute_id):
    dispute = lookup("disputes", dispute_id)
    require_bu_owner(dispute["filed_by_business_unit_id"])
    data = body()
    response_text = req_str(data, "response_text")

    if dispute["status"] != "INFO_REQUESTED":
        fail(
            "ERR_DISPUTE_STATE_INVALID",
            "Only a dispute in INFO_REQUESTED may accept a response.",
        )
    if dispute["review_round"] >= MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUND_LIMIT", "The dispute has exhausted its review rounds.")

    dispute["narrative"] = "%s\n%s" % (dispute["narrative"], response_text)
    dispute["status"] = "UNDER_REVIEW"
    dispute["review_round"] = dispute["review_round"] + 1
    touch(dispute)
    return serve(dispute)


@bp.route("/finops/disputes/<dispute_id>/resolve", methods=["POST"])
@authorize("FinOpsController")
def resolve(dispute_id):
    dispute = lookup("disputes", dispute_id)
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    granted = 0
    if outcome == "ADJUSTED":
        granted = req_int(data, "granted_credit_cents", minimum=0)
    elif present(data, "granted_credit_cents"):
        req_int(data, "granted_credit_cents", minimum=0)

    if dispute["status"] != "UNDER_REVIEW":
        fail("ERR_DISPUTE_STATE_INVALID", "Only a dispute UNDER_REVIEW may be resolved.")

    invoice = db.chargeback_invoices.get(dispute["chargeback_invoice_id"])
    if invoice is None or invoice["settlement_status"] not in ("ISSUED", "PARTIALLY_CREDITED"):
        fail(
            "ERR_INVOICE_STATE_INVALID",
            "Resolution requires an ISSUED or PARTIALLY_CREDITED invoice.",
        )
    if user_id() == dispute["filed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The resolving user must differ from the filing user.",
        )

    derived.invoice_sync(invoice, bump=False)
    if outcome == "ADJUSTED" and granted > _outstanding(invoice):
        fail(
            "ERR_CREDIT_EXCEEDS_INVOICE",
            "granted_credit_cents exceeds the invoice's outstanding amount.",
        )

    credited_before = invoice["credited_amount_cents"]
    paid_before = invoice["paid_amount_cents"]

    dispute["outcome"] = outcome
    dispute["granted_credit_cents"] = granted if outcome == "ADJUSTED" else 0
    dispute["resolved_by_user_id"] = user_id()
    dispute["status"] = "RESOLVED_ADJUSTED" if outcome == "ADJUSTED" else "RESOLVED_UPHELD"
    touch(dispute)

    if outcome == "ADJUSTED" and granted > 0:
        if (
            invoice["settlement_status"] == "ISSUED"
            and granted + credited_before + paid_before < invoice["gross_amount_cents"]
        ):
            invoice["settlement_status"] = "PARTIALLY_CREDITED"

    invoice["dispute_status"] = "DISPUTE_RESOLVED"
    derived.invoice_sync(invoice, bump=False)
    touch(invoice)
    flows.release_invoice_records(invoice)
    derived.bu_sync_id(invoice["business_unit_id"])
    derived.budget_cascade(invoice["business_unit_id"])
    return serve(dispute)


@bp.route("/finops/disputes/<dispute_id>/withdraw", methods=["POST"])
@authorize("BusinessUnitOwner")
def withdraw(dispute_id):
    dispute = lookup("disputes", dispute_id)
    require_bu_owner(dispute["filed_by_business_unit_id"])

    if dispute["status"] not in ("OPEN", "INFO_REQUESTED"):
        fail(
            "ERR_DISPUTE_STATE_INVALID",
            "Only an OPEN or INFO_REQUESTED dispute may be withdrawn.",
        )

    dispute["status"] = "WITHDRAWN"
    touch(dispute)

    invoice = db.chargeback_invoices.get(dispute["chargeback_invoice_id"])
    if invoice is not None:
        others = [
            d
            for d in derived.invoice_disputes(invoice["id"])
            if d["id"] != dispute["id"] and d["status"] in OPEN_STATES
        ]
        if not others:
            invoice["dispute_status"] = "NONE"
            flows.release_invoice_records(invoice)
        derived.invoice_sync(invoice, bump=False)
        touch(invoice)
        derived.bu_sync_id(invoice["business_unit_id"])
    return serve(dispute)
