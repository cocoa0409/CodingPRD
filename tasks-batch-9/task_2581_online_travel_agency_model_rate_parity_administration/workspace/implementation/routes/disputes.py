"""Dispute mediation and the two liability-split variants (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import clock
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("disputes", __name__)

TYPES = ("REFUND_PASSTHROUGH", "CHARGEBACK", "FRAUD")
STATUSES = ("FILED", "RESPONSE_REQUESTED", "MEDIATION", "RESOLVED")
OUTCOMES = ("SUPPLIER_LIABLE", "MARKETPLACE_LIABLE", "SPLIT", "REVERSE_REFUND")


def _booked_travel_date(booking):
    if booking["package_id"]:
        package = db["packages"].get(booking["package_id"])
        if package is not None:
            return package["travel_date"]
    offer = common.booking_governing_offer(booking)
    return offer["travel_date"] if offer else clock.today().isoformat()


@bp.post("/bookings/<booking_id>/dispute-cases")
def file_dispute(booking_id):
    actor = auth.authenticate(("ComplianceOfficer", "SupplierUser", "BookingAgent"))
    booking = common.find("bookings", booking_id)
    auth.require_supplier_scope_any(actor, common.booking_supplier_ids(booking))
    data = validate.body()
    dispute_type = validate.enum_req(data, "dispute_type", TYPES)
    claim_cents = validate.int_req(data, "claim_cents", 1)
    narrative = validate.str_req(data, "narrative")
    if dispute_type == "CHARGEBACK" and booking["payment_status"] != "CHARGEBACK":
        raise ApiError("ERR_PAYMENT_NOT_CHARGED_BACK")
    if int(booking["charged_total_cents"]) - int(booking["refunded_cents"]) < 1:
        raise ApiError("ERR_NOTHING_TO_DISPUTE")

    supplier = common.booking_supplier(booking)
    supplier_id = supplier["id"] if supplier else None
    filing = None
    if supplier_id:
        filing = calc.active_agreement_for_date(supplier_id, clock.today().isoformat()) \
            or calc.latest_activated_active_agreement(supplier_id)
    travel_date = _booked_travel_date(booking)
    binding = None
    if supplier_id:
        binding = calc.binding_agreement_for_travel_date(supplier_id, travel_date) or filing
    settlement = calc.settlement_for(claim_cents, booking["charged_total_cents"],
                                    booking["refunded_cents"])
    marketplace, supplier_share = calc.preliminary_split(
        settlement["settlement_total_cents"], filing)
    fields = {
        "booking_id": booking["id"],
        "supplier_id": supplier_id,
        "dispute_type": dispute_type,
        "claim_cents": claim_cents,
        "narrative": narrative,
        "filing_agreement_id": filing["id"] if filing else None,
        "binding_agreement_id": binding["id"] if binding else None,
        "preliminary_marketplace_cents": marketplace,
        "preliminary_supplier_cents": supplier_share,
        "binding_marketplace_cents": None,
        "binding_supplier_cents": None,
        "uncapped_marketplace_cents": None,
        "status": "FILED",
        "mediation_rounds": 0,
        "outcome": None,
        "supplier_position": None,
        "filed_by_user_id": actor.user_id,
        "resolved_by_user_id": None,
    }
    fields.update(settlement)
    dispute = store.new_row("disputes", fields)
    return response.obj(dispute, 201)


@bp.get("/dispute-cases/<dispute_id>")
def read_dispute(dispute_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("disputes", dispute_id), 200)


@bp.get("/dispute-cases")
def list_disputes():
    auth.authenticate(auth.ALL_ROLES)
    booking_id = validate.filter_str("booking_id")
    supplier_id = validate.filter_str("supplier_id")
    filing_id = validate.filter_str("filing_agreement_id")
    binding_id = validate.filter_str("binding_agreement_id")
    status = validate.filter_enum("status", STATUSES)
    rows = []
    for row in db["disputes"].values():
        if booking_id is not None and row["booking_id"] != booking_id:
            continue
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if filing_id is not None and row["filing_agreement_id"] != filing_id:
            continue
        if binding_id is not None and row["binding_agreement_id"] != binding_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/dispute-cases/<dispute_id>/request-response")
def request_response(dispute_id):
    auth.authenticate(("ComplianceOfficer",))
    dispute = common.find("disputes", dispute_id)
    data = validate.body()
    validate.str_opt(data, "note")
    if dispute["status"] == "RESOLVED":
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED")
    if dispute["status"] not in ("FILED", "MEDIATION"):
        raise ApiError("ERR_DISPUTE_NOT_AWAITING_RESPONSE")
    if int(dispute["mediation_rounds"]) >= calc.DISPUTE_MAX_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUND_LIMIT")
    dispute["status"] = "RESPONSE_REQUESTED"
    dispute["mediation_rounds"] = int(dispute["mediation_rounds"]) + 1
    touch(dispute)
    return response.obj(dispute, 200)


@bp.post("/dispute-cases/<dispute_id>/respond")
def respond(dispute_id):
    actor = auth.authenticate(("SupplierUser",))
    dispute = common.find("disputes", dispute_id)
    auth.require_supplier_scope(actor, dispute["supplier_id"])
    data = validate.body()
    position = validate.str_req(data, "supplier_position")
    if dispute["status"] == "RESOLVED":
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED")
    if dispute["status"] != "RESPONSE_REQUESTED":
        raise ApiError("ERR_DISPUTE_NOT_AWAITING_RESPONSE")
    dispute["status"] = "MEDIATION"
    dispute["supplier_position"] = position
    touch(dispute)
    return response.obj(dispute, 200)


@bp.post("/dispute-cases/<dispute_id>/resolve")
def resolve(dispute_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    dispute = common.find("disputes", dispute_id)
    data = validate.body()
    outcome = validate.enum_req(data, "outcome", OUTCOMES)
    validate.str_opt(data, "note")
    if dispute["status"] == "RESOLVED":
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED")
    if dispute["status"] not in ("FILED", "RESPONSE_REQUESTED", "MEDIATION"):
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED")
    auth.require_distinct(actor, dispute["filed_by_user_id"])
    booking = db["bookings"].get(dispute["booking_id"])
    if outcome == "REVERSE_REFUND":
        if booking is None or booking["payment_status"] not in ("REFUNDED_PARTIAL", "REFUNDED_FULL") \
                or int(booking["refunded_cents"]) <= 0:
            raise ApiError("ERR_PAYMENT_NOT_CAPTURED",
                           "There is no refund on this booking to reverse.")
    binding = db["model_agreements"].get(dispute["binding_agreement_id"])
    uncapped, marketplace, supplier_share = calc.binding_split(
        dispute["settlement_total_cents"], binding, outcome, dispute["dispute_type"])
    dispute["status"] = "RESOLVED"
    dispute["outcome"] = outcome
    dispute["resolved_by_user_id"] = actor.user_id
    dispute["uncapped_marketplace_cents"] = uncapped
    dispute["binding_marketplace_cents"] = marketplace
    dispute["binding_supplier_cents"] = supplier_share
    touch(dispute)
    if outcome == "REVERSE_REFUND":
        booking["payment_status"] = "CAPTURED"
        booking["refunded_cents"] = 0
        booking["marketplace_margin_cents"] += int(booking["last_refund_clawback_cents"])
        booking["supplier_payable_cents"] += int(booking["last_refund_supplier_debit_cents"])
        booking["taxes_fees_cents"] += int(booking["last_refund_tax_cents"])
        booking["last_refund_clawback_cents"] = 0
        booking["last_refund_supplier_debit_cents"] = 0
        booking["last_refund_tax_cents"] = 0
        touch(booking)
    return response.obj(dispute, 200)
