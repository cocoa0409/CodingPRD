"""Document presentations: lodging, examination, the cure loop and settlement."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, buyer_scope, pagination
from core import ApiError, dq, fmt_dt, fmt_instant, ok, ok_list, parse_dt
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_lc import guard_lc_live
from routes_orders import guard_restricted
from routes_reviews import CLAUSES, FINDING_CODES, SEVERITIES, new_finding

from flask import Blueprint, request

bp = Blueprint("present", __name__)

D = Decimal
PRESENTATION_READ = ("DocumentaryCreditReviewer", "ExportOpsCoordinator",
                     "FinanceCollectionsOfficer", "PlatformAdmin")
FINDING_READ = ("DocumentaryCreditReviewer", "ExportOpsCoordinator",
                "FinanceCollectionsOfficer", "ForeignBuyer", "PlatformAdmin")
CLAUSE_FOR_DOC = {
    "COMMERCIAL_INVOICE": ("AMOUNT", "DOCUMENTS", "GOODS"),
    "PACKING_LIST": ("DOCUMENTS", "GOODS"),
    "CERTIFICATE_OF_ORIGIN": ("DOCUMENTS", "GOODS"),
    "BILL_OF_LADING": ("DOCUMENTS", "LATEST_SHIPMENT", "GOODS"),
    "INSURANCE_CERTIFICATE": ("DOCUMENTS",),
    "INSPECTION_CERTIFICATE": ("DOCUMENTS", "GOODS"),
}


def presentation_state_invalid(message="the presentation state does not permit this"):
    raise ApiError("ERR_PRESENTATION_STATE_INVALID", 409, message)


def revision_superseded(message="a tendered document revision is not the revision of record"):
    raise ApiError("ERR_DOCUMENT_REVISION_SUPERSEDED", 409, message)


def active_links(presentation_id):
    return [l for l in ordered(store.links)
            if l["document_presentation_id"] == presentation_id
            and l["link_status"] == "ACTIVE"]


def linked_document(presentation_id, doc_type):
    for link in active_links(presentation_id):
        if link["doc_type"] == doc_type:
            return store.documents.get(link["trade_document_id"])
    return None


def whole_days(start, end):
    delta = end - start
    return int(delta.total_seconds() // 86400)


def recompute_tender_figures(presentation):
    bol = linked_document(presentation["id"], "BILL_OF_LADING")
    presented_at = parse_dt(presentation["presented_at"])
    if bol is not None and bol["on_board_date"]:
        presentation["days_after_on_board"] = whole_days(
            parse_dt(bol["on_board_date"]), presented_at)
    else:
        presentation["days_after_on_board"] = None
    invoice = linked_document(presentation["id"], "COMMERCIAL_INVOICE")
    presentation["presented_amount_usd"] = invoice["declared_total_usd"] \
        if invoice is not None else D("0.00")


def guard_period(presentation, lc):
    days = presentation.get("days_after_on_board")
    if days is not None and days > lc["presentation_period_days"]:
        raise ApiError("ERR_PRESENTATION_PERIOD_ELAPSED", 409,
                       "the presentation period has elapsed")


def price_and_complete(presentation, lc):
    presentation["negotiable_amount_usd"] = calc.price_drawing(
        presentation["presented_amount_usd"], lc)


@bp.post("/document-presentations")
def lodge_presentation():
    caller = authenticate(("ExportOpsCoordinator",))
    body = valid.body()
    lc = valid.fk(body, "letter_of_credit_id", store.lcs, "ERR_LC_NOT_FOUND")
    order = valid.fk(body, "export_order_id", store.orders, "ERR_ORDER_NOT_FOUND")
    document_ids = valid.id_list(body, "trade_document_ids")
    expected = valid.integer(body, "expected_export_order_version", minimum=0)
    documents = [require(store.documents, value, "ERR_DOCUMENT_NOT_FOUND")
                 for value in document_ids]

    # PRD §3.7 lists the lodging preconditions in this order ("The credit must be in
    # ACCEPTED, the order's fulfillment_status must be SHIPPED or SHORT_SHIPPED"), and
    # PRD §2.11 places the credit gate at priority 12 and the concurrency check at 13.
    if lc["status"] != "ACCEPTED":
        raise ApiError("ERR_LC_NOT_ACCEPTED", 409, "the credit is not ACCEPTED")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", 412,
                       "expected_export_order_version is stale")
    ledgers.require_settlement(order, ("LC_ACCEPTED",))
    ledgers.require_fulfillment(order, ("SHIPPED", "SHORT_SHIPPED"))
    guard_restricted(store.buyers[order["buyer_id"]])
    guard_lc_live(lc)
    if not documents:
        raise ApiError("ERR_PRESENTATION_NO_DOCUMENTS", 422,
                       "trade_document_ids is empty")
    seen = set()
    for document in documents:
        if document["status"] != "ISSUED":
            revision_superseded("a tendered document is not ISSUED")
        if document["export_order_id"] != order["id"]:
            revision_superseded("a tendered document belongs to another order")
        if document["doc_type"] in seen:
            revision_superseded("two tendered documents share a doc_type")
        seen.add(document["doc_type"])
    for doc_type in lc["required_document_types"]:
        if doc_type not in seen:
            raise ApiError("ERR_REQUIRED_DOCUMENT_MISSING", 409,
                           "no %s was tendered" % doc_type)
    bol = None
    invoice = None
    for document in documents:
        if document["doc_type"] == "BILL_OF_LADING":
            bol = document
        elif document["doc_type"] == "COMMERCIAL_INVOICE":
            invoice = document
    days = None
    if bol is not None and bol["on_board_date"]:
        days = whole_days(parse_dt(bol["on_board_date"]), store.clock)
    if days is not None and days > lc["presentation_period_days"]:
        raise ApiError("ERR_PRESENTATION_PERIOD_ELAPSED", 409,
                       "the presentation period has elapsed")

    presentation = insert(store.presentations, {
        "letter_of_credit_id": lc["id"],
        "export_order_id": order["id"],
        "presented_by_user_id": caller.user_id,
        "examined_by_user_id": None,
        "presented_at": fmt_instant(store.clock),
        "presentation_round": 1,
        "days_after_on_board": None,
        "presented_amount_usd": D("0.00"),
        "examination_risk_score": D("0.00"),
        "negotiable_amount_usd": D("0.00"),
        "open_finding_count": 0,
        "received_amount_usd": None,
        "value_date": None,
        "refusal_reason": None,
        "status": "PRESENTED",
    })
    for document in documents:
        insert(store.links, {
            "document_presentation_id": presentation["id"],
            "trade_document_id": document["id"],
            "doc_type": document["doc_type"],
            "pinned_document_revision": document["revision"],
            "linked_in_round": 1,
            "link_status": "ACTIVE",
        }, with_version=False)
    recompute_tender_figures(presentation)
    order["settlement_status"] = "DOCS_PRESENTED"
    touch(order)
    return ok(serialize(presentation), 201)


@bp.get("/document-presentations")
def list_presentations():
    authenticate(PRESENTATION_READ)
    limit, offset = pagination()
    rows = ordered(store.presentations)
    for field in ("letter_of_credit_id", "export_order_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/document-presentations/<presentation_id>")
def read_presentation(presentation_id):
    authenticate(PRESENTATION_READ)
    row = require(store.presentations, presentation_id, "ERR_PRESENTATION_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/document-presentations/<presentation_id>/examine")
def examine_presentation(presentation_id):
    caller = authenticate(("DocumentaryCreditReviewer",))
    presentation = require(store.presentations, presentation_id,
                           "ERR_PRESENTATION_NOT_FOUND")
    body = valid.body()
    entries = body.get("findings")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        valid.bad("findings must be an array")
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict):
            valid.bad("findings entries must be objects")
        parsed.append({
            "code": valid.enum(entry, "code", FINDING_CODES),
            "severity": valid.enum(entry, "severity", SEVERITIES),
            "clause_ref": valid.enum(entry, "clause_ref", CLAUSES),
            "detail": valid.string(entry, "detail", max_len=2000),
        })

    lc = store.lcs[presentation["letter_of_credit_id"]]
    order = store.orders[presentation["export_order_id"]]
    if presentation["status"] != "PRESENTED":
        presentation_state_invalid("only a PRESENTED tender may be examined")
    links = active_links(presentation["id"])
    for link in links:
        document = store.documents.get(link["trade_document_id"])
        if document is not None and caller.user_id == document["generated_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                           "the examiner prepared a tendered document")
    guard_lc_live(lc)
    guard_period(presentation, lc)
    for link in links:
        document = store.documents.get(link["trade_document_id"])
        if document is None or document["status"] != "ISSUED":
            revision_superseded("a tendered document is no longer ISSUED")
        if link["pinned_document_revision"] != document["revision"]:
            revision_superseded("a tendered revision has been superseded")
    present_types = set(link["doc_type"] for link in links)
    for doc_type in lc["required_document_types"]:
        if doc_type not in present_types:
            raise ApiError("ERR_REQUIRED_DOCUMENT_MISSING", 409,
                           "no ACTIVE %s link is on the presentation" % doc_type)
    if presentation["presented_amount_usd"] > lc["max_drawable_usd"]:
        raise ApiError("ERR_LC_AMOUNT_EXCEEDED", 409,
                       "presented_amount_usd exceeds max_drawable_usd")

    round_no = presentation["presentation_round"]
    raised = []
    for entry in parsed:
        raised.append(new_finding(
            letter_of_credit_id=lc["id"],
            document_presentation_id=presentation["id"], source="DOCUMENT",
            code=entry["code"], severity=entry["severity"],
            clause_ref=entry["clause_ref"], detail=entry["detail"],
            cure_status="OPEN", raised_in_round=round_no))
    floor = calc.effective_underdraw_floor(lc)
    if presentation["presented_amount_usd"] < floor:
        raised.append(new_finding(
            letter_of_credit_id=lc["id"],
            document_presentation_id=presentation["id"], source="DOCUMENT",
            code="SHORT_DRAWING", severity="MAJOR", clause_ref="AMOUNT",
            detail="the drawing falls below the effective floor of %s" % floor,
            cure_status="OPEN", raised_in_round=round_no))

    presentation["examined_by_user_id"] = caller.user_id
    presentation["examination_risk_score"] = calc.examination_risk_score(presentation, lc)
    presentation["open_finding_count"] = calc.open_finding_count(presentation["id"])
    blocking = any(f["severity"] in ("CRITICAL", "MAJOR") for f in raised)
    if not blocking:
        presentation["status"] = "COMPLIED"
        price_and_complete(presentation, lc)
        touch(presentation)
    else:
        presentation["status"] = "DISCREPANT"
        touch(presentation)
        if order["settlement_status"] == "DOCS_PRESENTED" \
                and not ledgers.has_complying_presentation(order["id"]):
            order["settlement_status"] = "LC_ACCEPTED"
            touch(order)
    return ok(serialize(presentation))


@bp.post("/document-presentations/<presentation_id>/cure")
def cure_presentation(presentation_id):
    authenticate(("ExportOpsCoordinator",))
    presentation = require(store.presentations, presentation_id,
                           "ERR_PRESENTATION_NOT_FOUND")
    body = valid.body()
    document_ids = valid.id_list(body, "replacement_document_ids")
    documents = [require(store.documents, value, "ERR_DOCUMENT_NOT_FOUND")
                 for value in document_ids]
    lc = store.lcs[presentation["letter_of_credit_id"]]
    order = store.orders[presentation["export_order_id"]]

    if presentation["status"] != "DISCREPANT":
        presentation_state_invalid("only a DISCREPANT presentation may be cured")
    if lc["status"] != "ACCEPTED":
        raise ApiError("ERR_LC_NOT_ACCEPTED", 409, "the credit is not ACCEPTED")
    guard_lc_live(lc)
    guard_period(presentation, lc)
    if not documents:
        raise ApiError("ERR_NO_REPLACEMENT_DOCUMENTS", 422,
                       "replacement_document_ids is empty")
    seen = set()
    for document in documents:
        if document["status"] != "ISSUED":
            revision_superseded("a replacement document is not ISSUED")
        if document["export_order_id"] != order["id"]:
            revision_superseded("a replacement document belongs to another order")
        if document["doc_type"] in seen:
            revision_superseded("two replacements share a doc_type")
        seen.add(document["doc_type"])
    if presentation["presentation_round"] >= calc.MAX_CURE_ROUNDS:
        raise ApiError("ERR_CURE_ROUNDS_EXHAUSTED", 409,
                       "the cure-round ceiling has been reached")

    presentation["status"] = "CURING"
    for link in ordered(store.links):
        if link["document_presentation_id"] != presentation["id"]:
            continue
        if link["doc_type"] not in seen:
            continue
        if link["link_status"] not in ("ACTIVE", "INVALIDATED"):
            continue
        link["link_status"] = "REPLACED"
        touch(link)
    addressed = set()
    for doc_type in seen:
        addressed.update(CLAUSE_FOR_DOC.get(doc_type, ()))
    for finding in ordered(store.findings):
        if finding["document_presentation_id"] != presentation["id"]:
            continue
        if finding["cure_status"] != "OPEN":
            continue
        if finding["clause_ref"] in addressed:
            finding["cure_status"] = "CURED"
            touch(finding)

    new_round = presentation["presentation_round"] + 1
    presentation["presentation_round"] = new_round
    presentation["presented_at"] = fmt_instant(store.clock)
    written = 0
    for document in documents:
        insert(store.links, {
            "document_presentation_id": presentation["id"],
            "trade_document_id": document["id"],
            "doc_type": document["doc_type"],
            "pinned_document_revision": document["revision"],
            "linked_in_round": new_round,
            "link_status": "ACTIVE",
        }, with_version=False)
        written += 1
    recompute_tender_figures(presentation)
    presentation["open_finding_count"] = calc.open_finding_count(presentation["id"])
    if written:
        presentation["status"] = "PRESENTED"
    touch(presentation)
    if order["settlement_status"] == "LC_ACCEPTED":
        order["settlement_status"] = "DOCS_PRESENTED"
        touch(order)
    return ok(serialize(presentation))


@bp.post("/document-presentations/<presentation_id>/settlement")
def settle_presentation(presentation_id):
    authenticate(("FinanceCollectionsOfficer",))
    presentation = require(store.presentations, presentation_id,
                           "ERR_PRESENTATION_NOT_FOUND")
    body = valid.body()
    received = valid.decimal(body, "received_amount_usd", 2, minimum=0)
    value_raw, _value_dt = valid.instant(body, "value_date")
    lc = store.lcs[presentation["letter_of_credit_id"]]
    order = store.orders[presentation["export_order_id"]]

    if presentation["status"] != "COMPLIED":
        presentation_state_invalid("only a COMPLIED presentation may be settled")
    ledgers.require_settlement(order, ("DOCS_PRESENTED",))
    if received > lc["max_drawable_usd"] \
            or received > presentation["negotiable_amount_usd"]:
        raise ApiError("ERR_LC_AMOUNT_EXCEEDED", 409,
                       "received_amount_usd exceeds the permitted drawing")

    presentation["received_amount_usd"] = received
    presentation["value_date"] = value_raw
    presentation["status"] = "HONOURED"
    touch(presentation)
    lc["drawn_amount_usd"] = dq(lc["drawn_amount_usd"] + received, 2)
    if lc["status"] == "ACCEPTED" and lc["drawn_amount_usd"] >= lc["min_drawable_usd"]:
        lc["status"] = "UTILISED"
    touch(lc)
    order["settlement_status"] = "PAID"
    ledgers.recompute_outstanding_receivable(order)
    ledgers.release_exposure(order)
    ledgers.auto_close(order)
    touch(order)
    return ok(serialize(presentation))


@bp.post("/document-presentations/<presentation_id>/dishonour")
def dishonour_presentation(presentation_id):
    authenticate(("FinanceCollectionsOfficer",))
    presentation = require(store.presentations, presentation_id,
                           "ERR_PRESENTATION_NOT_FOUND")
    body = valid.body()
    reason = valid.string(body, "refusal_reason", max_len=1000)
    order = store.orders[presentation["export_order_id"]]

    if presentation["status"] not in ("COMPLIED", "DISCREPANT"):
        presentation_state_invalid("the presentation may not be refused")
    ledgers.require_settlement(order, ("DOCS_PRESENTED",))

    presentation["refusal_reason"] = reason
    presentation["status"] = "REFUSED"
    touch(presentation)
    order["settlement_status"] = "DISHONORED"
    touch(order)
    return ok(serialize(presentation))


@bp.post("/discrepancy-findings/<finding_id>/waiver")
def waive_finding(finding_id):
    caller = authenticate(("ForeignBuyer",))
    finding = require(store.findings, finding_id, "ERR_FINDING_NOT_FOUND")
    body = valid.body()
    reference = valid.string(body, "buyer_reference", max_len=200)

    presentation = store.presentations.get(finding["document_presentation_id"]) \
        if finding["document_presentation_id"] else None
    if presentation is not None:
        order = store.orders[presentation["export_order_id"]]
    else:
        # PRD §2.1: the scope check compares the buyer_id of the ExportOrder reached
        # through the target resource; a TERMS finding reaches it through its credit.
        lc_row = store.lcs.get(finding["letter_of_credit_id"])
        order = store.orders[lc_row["export_order_id"]] if lc_row else None
    buyer_scope(caller, order)
    if finding["cure_status"] != "OPEN":
        presentation_state_invalid("the finding is not OPEN")

    finding["cure_status"] = "WAIVED"
    finding["waived_by_buyer_id"] = caller.user_id
    finding["buyer_reference"] = reference
    touch(finding)

    if presentation is None:
        return ok(serialize(finding))

    remaining = calc.open_finding_count(presentation["id"])
    presentation["open_finding_count"] = remaining
    lc = store.lcs[presentation["letter_of_credit_id"]]
    if remaining == 0 and presentation["status"] == "DISCREPANT" \
            and store.clock < lc["_expiry_dt"]:
        presentation["status"] = "COMPLIED"
        price_and_complete(presentation, lc)
        touch(presentation)
        if order["settlement_status"] == "LC_ACCEPTED":
            order["settlement_status"] = "DOCS_PRESENTED"
            touch(order)
    return ok(serialize(finding))
