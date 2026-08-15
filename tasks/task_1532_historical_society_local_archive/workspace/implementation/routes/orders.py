"""ReproductionOrder routes (PRD §3.7) — quote/invoice fee variants, donor-term
gates, annual page quota, exact payment, citation-at-delivery, refunds."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_REQUEST_NOT_APPROVED, ERR_RESEARCHER_SUSPENDED, ERR_EMBARGO_ACTIVE,
    ERR_DEED_REPRODUCTION_RESTRICTED, ERR_PUBLICATION_LICENSE_REQUIRED,
    ERR_REQUEST_OWNERSHIP_MISMATCH, ERR_OWNERSHIP_MISMATCH,
    ERR_ITEM_NOT_IN_REQUEST, ERR_REPRO_QUOTA_EXCEEDED,
    ERR_PAYMENT_AMOUNT_MISMATCH, ERR_REQUOTE_REQUIRED, ERR_CITATION_MISMATCH,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.calc import (
    reproduction_order_total, requote_cap, ANNUAL_PAGE_QUOTA, FORMAT_MULT,
    LICENSE_FLAT_CENTS,
)
from util import (
    get_json_body, as_str, as_int, as_bool, as_enum, as_str_list,
    check_no_duplicates, paginate, public_view,
)

bp = Blueprint("orders", __name__)

# statuses that retain the annual page-quota debit (REFUNDED keeps it — pinned)
QUOTA_CONSUMING_STATES = ("INVOICED", "PAID", "DELIVERED", "REFUNDED")


def serialize_order(o: dict) -> dict:
    return public_view(o)


def _get_order(oid: str) -> dict:
    o = db.orders.get(oid)
    if o is None:
        raise_err(ERR_NOT_FOUND, f"ReproductionOrder not found: {oid}")
    return o


def _current_deed_for_item(item: dict):
    accession = db.accessions.get(item["accession_id"])
    if accession is None:
        return None
    deed_id = accession.get("current_deed_id")
    if deed_id is None:
        return None
    deed = db.deeds.get(deed_id)
    if deed is None or deed["status"] != "EXECUTED":
        return None
    return deed


@bp.route("/reproduction-orders", methods=["POST"])
@require_roles("Researcher")
def create_order(_user_id: str, _role: str):
    body = get_json_body()
    # priority 3: shape
    research_request_id = as_str(body, "research_request_id", required=True)
    item_ids = as_str_list(body, "item_ids", required=True)
    if len(item_ids) == 0:
        raise_err(ERR_ITEM_NOT_IN_REQUEST, "item_ids must be non-empty")
    check_no_duplicates(item_ids)
    fmt = as_enum(body, "format", set(FORMAT_MULT), required=True)
    page_estimate = as_int(body, "page_estimate", required=True, minimum=1)
    license_class = as_enum(body, "license_class", set(LICENSE_FLAT_CENTS), required=False, default="PERSONAL")
    rush = as_bool(body, "rush", required=False, default=False)

    # priority 4: existence — researcher, request, then each item in order
    researcher = db.researchers.get(_user_id)
    if researcher is None:
        raise_err(ERR_NOT_FOUND, f"Researcher not found: {_user_id}")
    req = db.requests.get(research_request_id)
    if req is None:
        raise_err(ERR_NOT_FOUND, f"ResearchRequest not found: {research_request_id}")
    for iid in item_ids:
        if iid not in db.items:
            raise_err(ERR_NOT_FOUND, f"Item not found: {iid}")

    # priority 7: request APPROVED, then researcher ACTIVE
    if req["status"] != "APPROVED":
        raise_err(ERR_REQUEST_NOT_APPROVED, "The research request is not APPROVED")
    if researcher["status"] != "ACTIVE":
        raise_err(ERR_RESEARCHER_SUSPENDED, "The researcher is SUSPENDED")

    # priority 8: donor-term gates on the CURRENT EXECUTED deed, per item in order
    now = db.get_now()
    for iid in item_ids:
        deed = _current_deed_for_item(db.items[iid])
        if deed is None:
            continue
        if deed.get("_embargo_dt") is not None and deed["_embargo_dt"] > now:
            raise_err(ERR_EMBARGO_ACTIVE, f"A current deed embargo covers item {iid}")
        if deed["reproduction_restricted"]:
            raise_err(ERR_DEED_REPRODUCTION_RESTRICTED, f"Reproduction is restricted by deed for item {iid}")
        if deed["publication_license_required"] and license_class == "PERSONAL":
            raise_err(ERR_PUBLICATION_LICENSE_REQUIRED, f"A publication license is required for item {iid}")

    # priority 11: ownership, then item subset membership
    if req["researcher_id"] != _user_id:
        raise_err(ERR_REQUEST_OWNERSHIP_MISMATCH, "The research request belongs to a different researcher")
    for iid in item_ids:
        if iid not in req["item_ids"]:
            raise_err(ERR_ITEM_NOT_IN_REQUEST, f"Item {iid} is not part of the research request")

    quoted = reproduction_order_total(page_estimate, fmt, rush, license_class, req["purpose"])

    order = {
        **db.make_common_fields(),
        "researcher_id": _user_id,
        "research_request_id": research_request_id,
        "item_ids": list(item_ids),
        "format": fmt,
        "page_estimate": page_estimate,
        "actual_pages": None,
        "license_class": license_class,
        "rush": rush,
        "quoted_fee_cents": quoted,
        "invoiced_fee_cents": None,
        "status": "QUOTED",
        "_invoiced_year": None,
    }
    db.orders[order["id"]] = order
    return success_object(serialize_order(order), 201)


@bp.route("/reproduction-orders", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_orders(_user_id: str, _role: str):
    researcher_id = request.args.get("researcher_id")
    request_id = request.args.get("research_request_id")
    status = request.args.get("status")
    rows = list(db.orders.values())
    if researcher_id is not None:
        rows = [o for o in rows if o["researcher_id"] == researcher_id]
    if request_id is not None:
        rows = [o for o in rows if o["research_request_id"] == request_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_order(o) for o in page], limit, offset, total)


@bp.route("/reproduction-orders/<oid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_order(oid: str, _user_id: str, _role: str):
    return success_object(serialize_order(_get_order(oid)))


@bp.route("/reproduction-orders/<oid>/approve-quote", methods=["POST"])
@require_roles("Researcher")
def approve_quote(oid: str, _user_id: str, _role: str):
    o = _get_order(oid)
    if o["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "Only a QUOTED order may be quote-approved")
    if o["researcher_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the owning researcher may approve the quote")
    o["status"] = "APPROVED"
    db.touch(o)
    return success_object(serialize_order(o))


@bp.route("/reproduction-orders/<oid>/invoice", methods=["POST"])
@require_roles("ReadingRoomStaff")
def invoice(oid: str, _user_id: str, _role: str):
    body = get_json_body()
    actual_pages = as_int(body, "actual_pages", required=True, minimum=1)

    o = _get_order(oid)
    if o["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED order may be invoiced")

    req = db.requests.get(o["research_request_id"])
    purpose = req["purpose"] if req is not None else None
    invoiced = reproduction_order_total(actual_pages, o["format"], o["rush"], o["license_class"], purpose)

    # fiscal gates (priority 12): requote threshold, then annual page quota
    if invoiced > requote_cap(o["quoted_fee_cents"]):
        raise_err(ERR_REQUOTE_REQUIRED, "Invoiced fee exceeds 110% of the quoted fee")

    year = db.get_now().year
    consumed = sum(
        od["actual_pages"] or 0
        for od in db.orders.values()
        if od["researcher_id"] == o["researcher_id"]
        and od["status"] in QUOTA_CONSUMING_STATES
        and od.get("_invoiced_year") == year
    )
    if actual_pages > ANNUAL_PAGE_QUOTA - consumed:
        raise_err(ERR_REPRO_QUOTA_EXCEEDED, "Actual pages exceed the remaining annual page quota")

    o["actual_pages"] = actual_pages
    o["invoiced_fee_cents"] = invoiced
    o["_invoiced_year"] = year
    o["status"] = "INVOICED"
    db.touch(o)
    return success_object(serialize_order(o))


@bp.route("/reproduction-orders/<oid>/pay", methods=["POST"])
@require_roles("Researcher")
def pay(oid: str, _user_id: str, _role: str):
    body = get_json_body()
    amount_cents = as_int(body, "amount_cents", required=True)

    o = _get_order(oid)
    if o["status"] != "INVOICED":
        raise_err(ERR_INVALID_STATE, "Only an INVOICED order may be paid")
    if o["researcher_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the owning researcher may pay the order")
    if amount_cents != o["invoiced_fee_cents"]:
        raise_err(ERR_PAYMENT_AMOUNT_MISMATCH, "Payment must equal the invoiced fee exactly")

    o["status"] = "PAID"
    db.touch(o)
    researcher = db.researchers.get(o["researcher_id"])
    if researcher is not None:
        researcher["total_charged_cents"] = researcher.get("total_charged_cents", 0) + o["invoiced_fee_cents"]
        db.touch(researcher)
    return success_object(serialize_order(o))


@bp.route("/reproduction-orders/<oid>/deliver", methods=["POST"])
@require_roles("ReadingRoomStaff")
def deliver(oid: str, _user_id: str, _role: str):
    body = get_json_body()
    citation = as_str(body, "citation_acknowledgment_text", required=True)

    o = _get_order(oid)
    if o["status"] != "PAID":
        raise_err(ERR_INVALID_STATE, "Only a PAID order may be delivered")

    # citation acknowledgment is evaluated against the deeds current AT
    # DELIVERY TIME; containment is verbatim and case-sensitive
    if citation == "":
        raise_err(ERR_CITATION_MISMATCH, "citation_acknowledgment_text must be non-empty")
    for iid in o["item_ids"]:
        item = db.items.get(iid)
        if item is None:
            continue
        deed = _current_deed_for_item(item)
        if deed is None:
            continue
        required = deed.get("required_citation_text")
        if required is not None and required not in citation:
            raise_err(ERR_CITATION_MISMATCH, "Acknowledgment does not contain the required citation text")

    o["status"] = "DELIVERED"
    db.touch(o)
    return success_object(serialize_order(o))


@bp.route("/reproduction-orders/<oid>/refund", methods=["POST"])
@require_roles("ReadingRoomStaff")
def refund(oid: str, _user_id: str, _role: str):
    o = _get_order(oid)
    if o["status"] != "PAID":
        raise_err(ERR_INVALID_STATE, "Only a PAID order may be refunded")
    o["status"] = "REFUNDED"
    db.touch(o)
    # compensate the charge ledger; the annual quota debit is NOT released (pinned)
    researcher = db.researchers.get(o["researcher_id"])
    if researcher is not None:
        researcher["total_charged_cents"] = researcher.get("total_charged_cents", 0) - (o["invoiced_fee_cents"] or 0)
        db.touch(researcher)
    return success_object(serialize_order(o))
