"""Documentary credits: capture, listing and amendment rounds."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, dq, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_orders import guard_restricted

from flask import Blueprint, request

bp = Blueprint("lc", __name__)

D = Decimal
DOC_TYPES = ("COMMERCIAL_INVOICE", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN",
             "BILL_OF_LADING", "INSURANCE_CERTIFICATE", "INSPECTION_CERTIFICATE")
LC_READ = ("ExportOpsCoordinator", "DocumentaryCreditReviewer",
           "FinanceCollectionsOfficer", "PlatformAdmin")
AMENDABLE = ("amount_usd", "tolerance_pct", "expiry_date", "latest_shipment_date",
             "presentation_period_days", "partial_shipment_allowed",
             "transshipment_allowed", "required_document_types")


def lc_state_invalid(message="the credit state does not permit this"):
    raise ApiError("ERR_LC_STATE_INVALID", 409, message)


def guard_lc_live(lc):
    if store.clock >= lc["_expiry_dt"]:
        raise ApiError("ERR_LC_EXPIRED", 409, "the credit has expired")


def refresh_bounds(lc):
    upper, lower = calc.drawing_bounds(lc["amount_usd"], lc["tolerance_pct"])
    lc["max_drawable_usd"] = upper
    lc["min_drawable_usd"] = lower


def presentations_of_order(order_id):
    return [p for p in store.presentations.values() if p["export_order_id"] == order_id]


@bp.post("/letters-of-credit")
def capture_lc():
    caller = authenticate(("ExportOpsCoordinator",))
    body = valid.body()
    order = valid.fk(body, "export_order_id", store.orders, "ERR_ORDER_NOT_FOUND")
    superseded = valid.fk(body, "supersedes_lc_id", store.lcs, "ERR_LC_NOT_FOUND",
                          required=False)
    number = valid.string(body, "lc_number", max_len=100)
    swift = valid.string(body, "issuing_bank_swift", pattern=r"^([A-Z0-9]{8}|[A-Z0-9]{11})$",
                         min_len=8, max_len=11)
    amount = valid.decimal(body, "amount_usd", 2, minimum=0, exclusive_min=True)
    tolerance = valid.decimal(body, "tolerance_pct", 2, required=False, minimum=0,
                              maximum=10, default=D("0.00"))
    availability = valid.enum(body, "availability", ("SIGHT", "USANCE"))
    usance_days = valid.integer(body, "usance_days", required=False, minimum=0, default=0)
    expiry_raw, expiry_dt = valid.instant(body, "expiry_date")
    latest_raw, latest_dt = valid.instant(body, "latest_shipment_date")
    period = valid.integer(body, "presentation_period_days", required=False,
                           minimum=1, maximum=60, default=21)
    partial = valid.boolean(body, "partial_shipment_allowed", default=False)
    transshipment = valid.boolean(body, "transshipment_allowed", default=False)
    required_docs = valid.enum_list(body, "required_document_types", DOC_TYPES)

    if availability == "SIGHT" and usance_days != 0:
        valid.inconsistent("usance_days must be 0 for a SIGHT credit")
    if availability == "USANCE" and usance_days < calc.MIN_USANCE_DAYS:
        valid.inconsistent("usance_days must be at least 30 for a USANCE credit")
    if "COMMERCIAL_INVOICE" not in required_docs:
        valid.inconsistent("required_document_types must include COMMERCIAL_INVOICE")

    if superseded is not None and superseded["status"] not in ("REJECTED", "EXPIRED"):
        lc_state_invalid("the superseded credit must be REJECTED or EXPIRED")
    guard_restricted(store.buyers[order["buyer_id"]])
    for other in store.lcs.values():
        if other["lc_number"] == number and other["status"] not in ("REJECTED", "EXPIRED"):
            raise ApiError("ERR_DUPLICATE_LC_NUMBER", 409, "lc_number already exists")

    row = {
        "export_order_id": order["id"],
        "supersedes_lc_id": superseded["id"] if superseded else None,
        "captured_by_user_id": caller.user_id,
        "lc_number": number,
        "issuing_bank_swift": swift,
        "amount_usd": dq(amount, 2),
        "tolerance_pct": dq(tolerance, 2),
        "availability": availability,
        "usance_days": usance_days,
        "expiry_date": expiry_raw,
        "latest_shipment_date": latest_raw,
        "presentation_period_days": period,
        "partial_shipment_allowed": partial,
        "transshipment_allowed": transshipment,
        "required_document_types": list(required_docs),
        "status": "RECEIVED",
        "amendment_round": 0,
        "max_drawable_usd": D("0.00"),
        "min_drawable_usd": D("0.00"),
        "drawn_amount_usd": D("0.00"),
        "_expiry_dt": expiry_dt,
        "_latest_shipment_dt": latest_dt,
    }
    refresh_bounds(row)
    insert(store.lcs, row)
    return ok(serialize(row), 201)


@bp.get("/letters-of-credit")
def list_lcs():
    authenticate(LC_READ)
    limit, offset = pagination()
    rows = ordered(store.lcs)
    order_id = request.args.get("export_order_id")
    if order_id:
        rows = [r for r in rows if r["export_order_id"] == order_id]
    supersedes = request.args.get("supersedes_lc_id")
    if supersedes:
        rows = [r for r in rows if r["supersedes_lc_id"] == supersedes]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/letters-of-credit/<lc_id>")
def read_lc(lc_id):
    authenticate(LC_READ)
    row = require(store.lcs, lc_id, "ERR_LC_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/letters-of-credit/<lc_id>/amendments")
def amend_lc(lc_id):
    authenticate(("ExportOpsCoordinator",))
    lc = require(store.lcs, lc_id, "ERR_LC_NOT_FOUND")
    body = valid.body()
    expected = valid.integer(body, "expected_letter_of_credit_version", required=True,
                             minimum=0)
    amount = valid.decimal(body, "amount_usd", 2, required=False, minimum=0,
                           exclusive_min=True, default=None)
    tolerance = valid.decimal(body, "tolerance_pct", 2, required=False, minimum=0,
                              maximum=10, default=None)
    expiry = valid.instant(body, "expiry_date", required=False, default=(None, None))
    latest = valid.instant(body, "latest_shipment_date", required=False, default=(None, None))
    period = valid.integer(body, "presentation_period_days", required=False,
                           minimum=1, maximum=60, default=None)
    partial = valid.boolean(body, "partial_shipment_allowed", default=None)
    transshipment = valid.boolean(body, "transshipment_allowed", default=None)
    required_docs = valid.enum_list(body, "required_document_types", DOC_TYPES,
                                    required=False, default=None)

    if not any(valid.present(body, name) for name in AMENDABLE):
        valid.bad("an amendment must carry at least one amendable field")
    if required_docs is not None and "COMMERCIAL_INVOICE" not in required_docs:
        valid.inconsistent("required_document_types must include COMMERCIAL_INVOICE")

    if lc["status"] not in ("AMENDMENT_REQUESTED", "ACCEPTED"):
        lc_state_invalid("an amendment may only be applied from AMENDMENT_REQUESTED or ACCEPTED")
    order = store.orders[lc["export_order_id"]]
    presentations = presentations_of_order(order["id"])
    if lc["status"] == "ACCEPTED":
        if any(p["status"] in ("PRESENTED", "CURING", "COMPLIED", "HONOURED")
               for p in presentations):
            lc_state_invalid("documents are already presented under this credit")
    if expected != lc["version"]:
        raise ApiError("ERR_STALE_LC_VERSION", 412, "expected_letter_of_credit_version is stale")
    guard_lc_live(lc)

    was_accepted = lc["status"] == "ACCEPTED"
    if amount is not None:
        lc["amount_usd"] = dq(amount, 2)
    if tolerance is not None:
        lc["tolerance_pct"] = dq(tolerance, 2)
    if expiry[0] is not None:
        lc["expiry_date"] = expiry[0]
        lc["_expiry_dt"] = expiry[1]
    if latest[0] is not None:
        lc["latest_shipment_date"] = latest[0]
        lc["_latest_shipment_dt"] = latest[1]
    if period is not None:
        lc["presentation_period_days"] = period
    if partial is not None:
        lc["partial_shipment_allowed"] = partial
    if transshipment is not None:
        lc["transshipment_allowed"] = transshipment
    if required_docs is not None:
        lc["required_document_types"] = list(required_docs)
    lc["amendment_round"] = lc["amendment_round"] + 1
    refresh_bounds(lc)
    lc["status"] = "RECEIVED"
    touch(lc)

    for review in ordered(store.reviews):
        if review["letter_of_credit_id"] == lc["id"] and review["status"] == "SUBMITTED":
            review["status"] = "SUPERSEDED"
            touch(review)
    for finding in ordered(store.findings):
        if finding["letter_of_credit_id"] == lc["id"] and finding["source"] == "TERMS" \
                and finding["cure_status"] == "OPEN":
            finding["cure_status"] = "CURED"
            touch(finding)

    if was_accepted and order["settlement_status"] == "LC_ACCEPTED":
        if not any(p["status"] in ("PRESENTED", "CURING", "COMPLIED") for p in presentations):
            order["settlement_status"] = "UNSECURED"
            ledgers.release_exposure(order)
            touch(order)
    return ok(serialize(lc))
