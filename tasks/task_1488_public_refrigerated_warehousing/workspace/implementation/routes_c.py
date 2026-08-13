"""Routes: blast-freeze cells/bookings, temperature excursions, recalls,
claims, invoices, and the monthly billing run."""

from datetime import timedelta

from flask import Blueprint, request

from core import (
    ALL_ROLES, ApiError, DB, as_enum, as_int, as_number, as_str, authenticate,
    authorize, check_ownership, clock_now, get_body, get_or_404, list_response,
    new_record, ok_object, parse_datetime, req_present, touch,
)
from views import (
    PRESENT_STATUSES, active_rate_card, booking_view, cell_view, claim_view,
    compute_dwell_cents, compute_storage_cents, create_invoice, excursion_view,
    find_lot, invoice_view, month_bounds, open_invoice, recall_view,
)

bp = Blueprint("routes_c", __name__)


# ----------------------------------------------------------------------------
# Blast-freeze cells
# ----------------------------------------------------------------------------

@bp.route("/api/blast-freeze-cells", methods=["POST"])
def create_cell():
    uid, role = authenticate()
    data = get_body()
    cell_code = as_str(req_present(data, "cell_code"), "cell_code")
    capacity = as_int(req_present(data, "capacity_pallets"), "capacity_pallets", minimum=1)
    turnaround = as_int(req_present(data, "turnaround_minutes"), "turnaround_minutes", minimum=0)
    authorize(role, {"WarehouseOperator"})
    if any(c["cell_code"] == cell_code for c in DB["cells"].values()):
        raise ApiError("ERR_VALIDATION", 400, "cell_code must be unique across all cells")
    cell = new_record({
        "cell_code": cell_code,
        "capacity_pallets": capacity,
        "turnaround_minutes": turnaround,
    })
    DB["cells"][cell["id"]] = cell
    return ok_object(cell_view(cell), 201)


@bp.route("/api/blast-freeze-cells/<cid>", methods=["GET"])
def get_cell(cid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok_object(cell_view(get_or_404("cells", cid, "cell")))


@bp.route("/api/blast-freeze-cells", methods=["GET"])
def list_cells():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(DB["cells"].values()), cell_view)


# ----------------------------------------------------------------------------
# Blast-freeze bookings
# ----------------------------------------------------------------------------

@bp.route("/api/blast-freeze-bookings", methods=["POST"])
def create_booking():
    uid, role = authenticate()
    data = get_body()
    cell_id = as_str(req_present(data, "cell_id"), "cell_id")
    lot_id = as_str(req_present(data, "lot_id"), "lot_id")
    pallet_count = as_int(req_present(data, "pallet_count"), "pallet_count", minimum=1)
    window_start = parse_datetime(req_present(data, "window_start"), "window_start")
    window_end = parse_datetime(req_present(data, "window_end"), "window_end")
    if not window_end > window_start:
        raise ApiError("ERR_VALIDATION", 400, "window_end must be later than window_start")
    authorize(role, {"WarehouseOperator"})
    cell = get_or_404("cells", cell_id, "cell")
    lot = get_or_404("lots", lot_id, "lot")
    # Tier 8 — cell-window conflict, turnaround buffer included
    buffer = timedelta(minutes=cell["turnaround_minutes"])
    for b in DB["bookings"].values():
        if b["cell_id"] != cell_id or b["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if window_start < b["window_end"] + buffer and b["window_start"] < window_end + buffer:
            raise ApiError("ERR_BOOKING_WINDOW_CONFLICT", 409,
                           "booking window collides with an existing booking on this cell")
    # Tier 9 — cell capacity
    if pallet_count > cell["capacity_pallets"]:
        raise ApiError("ERR_CELL_CAPACITY_EXCEEDED", 409,
                       "pallet_count exceeds the cell's capacity")
    booking = new_record({
        "cell_id": cell_id,
        "lot_id": lot_id,
        "customer_id": lot["customer_id"],
        "pallet_count": pallet_count,
        "window_start": window_start,
        "window_end": window_end,
        "fee_cents": None,
        "status": "SCHEDULED",
        "_selected": [],
    })
    DB["bookings"][booking["id"]] = booking
    return ok_object(booking_view(booking), 201)


@bp.route("/api/blast-freeze-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    booking = get_or_404("bookings", bid, "booking")
    check_ownership(role, uid, booking["customer_id"])
    return ok_object(booking_view(booking))


@bp.route("/api/blast-freeze-bookings", methods=["GET"])
def list_bookings():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_cell = request.args.get("cell_id")
    f_lot = request.args.get("lot_id")
    f_customer = request.args.get("customer_id")
    f_status = request.args.get("status")
    records = list(DB["bookings"].values())
    if role == "CustomerAdmin":
        records = [b for b in records if b["customer_id"] == uid]
    if f_cell is not None:
        records = [b for b in records if b["cell_id"] == f_cell]
    if f_lot is not None:
        records = [b for b in records if b["lot_id"] == f_lot]
    if f_customer is not None:
        records = [b for b in records if b["customer_id"] == f_customer]
    if f_status is not None:
        records = [b for b in records if b["status"] == f_status]
    return list_response(records, booking_view)


@bp.route("/api/blast-freeze-bookings/<bid>/start", methods=["POST"])
def start_booking(bid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    booking = get_or_404("bookings", bid, "booking")
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "booking is not SCHEDULED")
    now = clock_now()
    if not (booking["window_start"] <= now <= booking["window_end"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", 409, "the logical clock is outside the booking window")
    candidates = sorted(
        (p for p in DB["pallets"].values()
         if p["lot_id"] == booking["lot_id"] and p["status"] == "STORED" and p["quality"] == "OK"),
        key=lambda p: (p["received_at"], p["created_at"], p["_seq"]),
    )
    if len(candidates) < booking["pallet_count"]:
        raise ApiError("ERR_INSUFFICIENT_FREEZABLE_STOCK", 409,
                       "fewer STORED+OK pallets on the lot than pallet_count")
    selected = candidates[:booking["pallet_count"]]
    for p in selected:
        p["status"] = "IN_BLAST_FREEZE"
        touch(p)
    booking["_selected"] = [p["id"] for p in selected]
    booking["status"] = "IN_PROGRESS"
    touch(booking)
    return ok_object(booking_view(booking))


@bp.route("/api/blast-freeze-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    booking = get_or_404("bookings", bid, "booking")
    if booking["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "booking is not IN_PROGRESS")
    card = active_rate_card(booking["customer_id"])
    if card is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_CARD", 409, "customer has no ACTIVE rate card")
    now = clock_now()
    for pid in booking["_selected"]:
        p = DB["pallets"][pid]
        if p["status"] == "IN_BLAST_FREEZE":
            p["status"] = "STORED"
            p["last_blast_frozen_at"] = now
            touch(p)
    fee = card["blast_base_cents"] + booking["pallet_count"] * card["blast_per_pallet_cents"]
    booking["fee_cents"] = fee
    booking["status"] = "COMPLETED"
    touch(booking)
    inv = open_invoice(booking["customer_id"])
    inv["blast_freeze_cents"] += fee
    touch(inv)
    return ok_object(booking_view(booking))


@bp.route("/api/blast-freeze-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    booking = get_or_404("bookings", bid, "booking")
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a SCHEDULED booking can be cancelled")
    booking["status"] = "CANCELLED"
    touch(booking)
    return ok_object(booking_view(booking))


# ----------------------------------------------------------------------------
# Temperature excursions
# ----------------------------------------------------------------------------

@bp.route("/api/temperature-excursions", methods=["POST"])
def create_excursion():
    uid, role = authenticate()
    data = get_body()
    zone_id = as_str(req_present(data, "zone_id"), "zone_id")
    observed = as_number(req_present(data, "observed_temp_c"), "observed_temp_c")
    window_start = parse_datetime(req_present(data, "window_start"), "window_start")
    window_end = parse_datetime(req_present(data, "window_end"), "window_end")
    if not window_end > window_start:
        raise ApiError("ERR_VALIDATION", 400, "window_end must be later than window_start")
    authorize(role, {"WarehouseOperator"})
    get_or_404("zones", zone_id, "zone")
    exc = new_record({
        "zone_id": zone_id,
        "observed_temp_c": observed,
        "window_start": window_start,
        "window_end": window_end,
        "reported_by_user_id": uid,
        "quarantined_pallet_count": 0,
        "status": "REPORTED",
    })
    DB["excursions"][exc["id"]] = exc
    return ok_object(excursion_view(exc), 201)


@bp.route("/api/temperature-excursions/<eid>", methods=["GET"])
def get_excursion(eid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok_object(excursion_view(get_or_404("excursions", eid, "excursion")))


@bp.route("/api/temperature-excursions", methods=["GET"])
def list_excursions():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_zone = request.args.get("zone_id")
    f_status = request.args.get("status")
    records = list(DB["excursions"].values())
    if f_zone is not None:
        records = [e for e in records if e["zone_id"] == f_zone]
    if f_status is not None:
        records = [e for e in records if e["status"] == f_status]
    return list_response(records, excursion_view)


def _sod_check(exc, uid):
    if exc["reported_by_user_id"] == uid:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "the reporting user may not adjudicate this excursion")


@bp.route("/api/temperature-excursions/<eid>/confirm", methods=["POST"])
def confirm_excursion(eid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    exc = get_or_404("excursions", eid, "excursion")
    if exc["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "excursion is not REPORTED")
    _sod_check(exc, uid)
    # Hop 1 — quarantine overlapping present pallets with quality OK
    affected = sorted(
        (p for p in DB["pallets"].values()
         if p["zone_id"] == exc["zone_id"]
         and p["status"] in PRESENT_STATUSES
         and p["quality"] == "OK"
         and p["received_at"] < exc["window_end"]
         and (p["out_at"] is None or p["out_at"] > exc["window_start"])),
        key=lambda p: p["_seq"],
    )
    demoted = set()
    for p in affected:
        # Hop 3 — an ALLOCATED pallet releases its allocation and returns to STORED
        if p["status"] == "ALLOCATED":
            for alloc in DB["allocations"].values():
                if alloc["pallet_id"] == p["id"] and alloc["status"] == "ACTIVE":
                    alloc["status"] = "RELEASED"
                    touch(alloc)
                    order = DB["orders"][alloc["order_id"]]
                    if order["status"] == "ALLOCATED" and order["id"] not in demoted:
                        order["status"] = "SUBMITTED"  # Hop 4
                        touch(order)
                        demoted.add(order["id"])
            p["status"] = "STORED"
        p["quality"] = "QUARANTINED"
        touch(p)
    exc["quarantined_pallet_count"] = len(affected)
    exc["status"] = "CONFIRMED_BREACH"
    touch(exc)
    return ok_object(excursion_view(exc))


@bp.route("/api/temperature-excursions/<eid>/clear", methods=["POST"])
def clear_excursion(eid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    exc = get_or_404("excursions", eid, "excursion")
    if exc["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "excursion is not REPORTED")
    _sod_check(exc, uid)
    exc["status"] = "CLEARED"
    touch(exc)
    return ok_object(excursion_view(exc))


# ----------------------------------------------------------------------------
# Recalls
# ----------------------------------------------------------------------------

@bp.route("/api/recalls", methods=["POST"])
def create_recall():
    uid, role = authenticate()
    data = get_body()
    customer_id = as_str(req_present(data, "customer_id"), "customer_id")
    product_code = as_str(req_present(data, "product_code"), "product_code")
    lot_code = as_str(req_present(data, "lot_code"), "lot_code")
    reason = as_str(req_present(data, "reason"), "reason")
    authorize(role, {"QualityManager"})
    get_or_404("customers", customer_id, "customer")
    lot = find_lot(customer_id, product_code, lot_code)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "no lot matches (customer_id, product_code, lot_code)")
    recall = new_record({
        "customer_id": customer_id,
        "product_code": product_code,
        "lot_code": lot_code,
        "lot_id": lot["id"],
        "reason": reason,
        "status": "DECLARED",
    })
    DB["recalls"][recall["id"]] = recall
    return ok_object(recall_view(recall), 201)


@bp.route("/api/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    recall = get_or_404("recalls", rid, "recall")
    check_ownership(role, uid, recall["customer_id"])
    return ok_object(recall_view(recall))


@bp.route("/api/recalls", methods=["GET"])
def list_recalls():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_lot = request.args.get("lot_id")
    f_status = request.args.get("status")
    records = list(DB["recalls"].values())
    if role == "CustomerAdmin":
        records = [r for r in records if r["customer_id"] == uid]
    if f_customer is not None:
        records = [r for r in records if r["customer_id"] == f_customer]
    if f_lot is not None:
        records = [r for r in records if r["lot_id"] == f_lot]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    return list_response(records, recall_view)


@bp.route("/api/recalls/<rid>/activate", methods=["POST"])
def activate_recall(rid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    recall = get_or_404("recalls", rid, "recall")
    if recall["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409, "recall is not DECLARED")
    pallets = sorted(
        (p for p in DB["pallets"].values()
         if p["lot_id"] == recall["lot_id"] and p["status"] in PRESENT_STATUSES),
        key=lambda p: p["_seq"],
    )
    demoted = set()
    for p in pallets:
        if p["quality"] == "RECALLED":
            continue
        if p["status"] == "ALLOCATED":
            for alloc in DB["allocations"].values():
                if alloc["pallet_id"] == p["id"] and alloc["status"] == "ACTIVE":
                    alloc["status"] = "RELEASED"
                    touch(alloc)
                    order = DB["orders"][alloc["order_id"]]
                    if order["status"] == "ALLOCATED" and order["id"] not in demoted:
                        order["status"] = "SUBMITTED"
                        touch(order)
                        demoted.add(order["id"])
            p["status"] = "STORED"
        p["quality"] = "RECALLED"
        touch(p)
    recall["status"] = "ACTIVE"
    touch(recall)
    return ok_object(recall_view(recall))


@bp.route("/api/recalls/<rid>/complete", methods=["POST"])
def complete_recall(rid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    recall = get_or_404("recalls", rid, "recall")
    if recall["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "recall is not ACTIVE")
    remaining = any(
        p["lot_id"] == recall["lot_id"] and p["status"] in PRESENT_STATUSES
        and p["quality"] == "RECALLED"
        for p in DB["pallets"].values()
    )
    if remaining:
        raise ApiError("ERR_RECALL_HAS_UNDISPOSITIONED_STOCK", 409,
                       "present pallets of the lot still have quality RECALLED")
    recall["status"] = "COMPLETED"
    touch(recall)
    return ok_object(recall_view(recall))


@bp.route("/api/recalls/<rid>/cancel", methods=["POST"])
def cancel_recall(rid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    recall = get_or_404("recalls", rid, "recall")
    if recall["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a DECLARED recall can be cancelled")
    recall["status"] = "CANCELLED"
    touch(recall)
    return ok_object(recall_view(recall))


# ----------------------------------------------------------------------------
# Claims
# ----------------------------------------------------------------------------

@bp.route("/api/claims", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    data = get_body()
    customer_id = as_str(req_present(data, "customer_id"), "customer_id")
    excursion_id = as_str(req_present(data, "excursion_id"), "excursion_id")
    affected = as_int(req_present(data, "affected_pallet_count"), "affected_pallet_count", minimum=1)
    declared = as_int(req_present(data, "declared_value_cents"), "declared_value_cents", minimum=1)
    authorize(role, {"CustomerAdmin"})
    check_ownership(role, uid, customer_id)
    get_or_404("customers", customer_id, "customer")
    exc = get_or_404("excursions", excursion_id, "excursion")
    # Tier 10 — claim cross-references
    if exc["status"] != "CONFIRMED_BREACH":
        raise ApiError("ERR_EXCURSION_NOT_CONFIRMED", 409,
                       "the referenced excursion is not CONFIRMED_BREACH")
    if affected > exc["quarantined_pallet_count"]:
        raise ApiError("ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT", 422,
                       "affected_pallet_count exceeds the excursion's quarantined count")
    claim = new_record({
        "customer_id": customer_id,
        "excursion_id": excursion_id,
        "affected_pallet_count": affected,
        "declared_value_cents": declared,
        "settlement_cents": None,
        "status": "FILED",
    })
    DB["claims"][claim["id"]] = claim
    return ok_object(claim_view(claim), 201)


@bp.route("/api/claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    claim = get_or_404("claims", cid, "claim")
    check_ownership(role, uid, claim["customer_id"])
    return ok_object(claim_view(claim))


@bp.route("/api/claims", methods=["GET"])
def list_claims():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_exc = request.args.get("excursion_id")
    f_status = request.args.get("status")
    records = list(DB["claims"].values())
    if role == "CustomerAdmin":
        records = [c for c in records if c["customer_id"] == uid]
    if f_customer is not None:
        records = [c for c in records if c["customer_id"] == f_customer]
    if f_exc is not None:
        records = [c for c in records if c["excursion_id"] == f_exc]
    if f_status is not None:
        records = [c for c in records if c["status"] == f_status]
    return list_response(records, claim_view)


@bp.route("/api/claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    uid, role = authenticate()
    authorize(role, {"ClaimsAdjuster"})
    claim = get_or_404("claims", cid, "claim")
    if claim["status"] not in ("FILED", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not FILED or REOPENED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok_object(claim_view(claim))


@bp.route("/api/claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    uid, role = authenticate()
    data = get_body()
    decision = as_enum(req_present(data, "decision"), "decision", ("APPROVED", "DENIED"))
    authorize(role, {"ClaimsAdjuster"})
    claim = get_or_404("claims", cid, "claim")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not UNDER_REVIEW")
    if decision == "APPROVED":
        card = active_rate_card(claim["customer_id"])
        if card is None:
            raise ApiError("ERR_NO_ACTIVE_RATE_CARD", 409, "customer has no ACTIVE rate card")
        if card["liability_model"] == "DECLARED_VALUE":
            settlement = claim["declared_value_cents"]
        else:
            settlement = min(claim["declared_value_cents"],
                             claim["affected_pallet_count"] * card["liability_per_pallet_cents"])
        claim["settlement_cents"] = settlement
        claim["status"] = "APPROVED"
    else:
        claim["status"] = "DENIED"
    touch(claim)
    return ok_object(claim_view(claim))


@bp.route("/api/claims/<cid>/settle", methods=["POST"])
def settle_claim(cid):
    uid, role = authenticate()
    authorize(role, {"BillingAdmin"})
    claim = get_or_404("claims", cid, "claim")
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not APPROVED")
    inv = open_invoice(claim["customer_id"])
    inv["claim_credit_cents"] += claim["settlement_cents"]
    touch(inv)
    claim["status"] = "SETTLED"
    touch(claim)
    return ok_object(claim_view(claim))


@bp.route("/api/claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin"})
    claim = get_or_404("claims", cid, "claim")
    check_ownership(role, uid, claim["customer_id"])
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not DENIED")
    claim["status"] = "REOPENED"
    touch(claim)
    return ok_object(claim_view(claim))


@bp.route("/api/claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin"})
    claim = get_or_404("claims", cid, "claim")
    check_ownership(role, uid, claim["customer_id"])
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not FILED")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return ok_object(claim_view(claim))


# ----------------------------------------------------------------------------
# Invoices and the billing run
# ----------------------------------------------------------------------------

@bp.route("/api/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    inv = get_or_404("invoices", iid, "invoice")
    check_ownership(role, uid, inv["customer_id"])
    return ok_object(invoice_view(inv))


@bp.route("/api/invoices", methods=["GET"])
def list_invoices():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_status = request.args.get("status")
    f_card = request.args.get("rate_card_id")
    records = list(DB["invoices"].values())
    if role == "CustomerAdmin":
        records = [i for i in records if i["customer_id"] == uid]
    if f_customer is not None:
        records = [i for i in records if i["customer_id"] == f_customer]
    if f_status is not None:
        records = [i for i in records if i["status"] == f_status]
    if f_card is not None:
        records = [i for i in records if i["rate_card_id"] == f_card]
    return list_response(records, invoice_view)


@bp.route("/api/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin"})
    inv = get_or_404("invoices", iid, "invoice")
    check_ownership(role, uid, inv["customer_id"])
    if inv["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not FINALIZED")
    inv["status"] = "DISPUTED"
    touch(inv)
    return ok_object(invoice_view(inv))


@bp.route("/api/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_dispute(iid):
    uid, role = authenticate()
    authorize(role, {"BillingAdmin"})
    inv = get_or_404("invoices", iid, "invoice")
    if inv["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not DISPUTED")
    inv["status"] = "FINALIZED"
    touch(inv)
    return ok_object(invoice_view(inv))


@bp.route("/api/invoices/<iid>/settle", methods=["POST"])
def settle_invoice(iid):
    uid, role = authenticate()
    data = get_body()
    amount = as_int(req_present(data, "amount_cents"), "amount_cents")
    authorize(role, {"BillingAdmin"})
    inv = get_or_404("invoices", iid, "invoice")
    if inv["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not FINALIZED")
    from views import invoice_total
    if amount != invoice_total(inv):
        raise ApiError("ERR_INVOICE_AMOUNT_MISMATCH", 409,
                       "amount_cents must equal the invoice total exactly")
    inv["status"] = "SETTLED"
    touch(inv)
    return ok_object(invoice_view(inv))


@bp.route("/api/billing/run", methods=["POST"])
def billing_run():
    uid, role = authenticate()
    authorize(role, {"BillingAdmin"})
    now = clock_now()
    eligible = sorted(
        (inv for inv in DB["invoices"].values()
         if inv["status"] == "OPEN" and inv["period_end"] <= now),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    finalized_ids = []
    for inv in eligible:
        card = active_rate_card(inv["customer_id"])
        inv["storage_cents"] = compute_storage_cents(
            inv["customer_id"], inv["period_start"], inv["period_end"], card)
        inv["dwell_surcharge_cents"] = compute_dwell_cents(
            inv["customer_id"], inv["period_start"], inv["period_end"], card)
        inv["rate_card_id"] = card["id"] if card is not None else None
        inv["status"] = "FINALIZED"
        touch(inv)
        start = inv["period_end"]
        _, end = month_bounds(start)
        create_invoice(inv["customer_id"], start, end)
        finalized_ids.append(inv["id"])
    return ok_object({"finalized_count": len(finalized_ids),
                      "finalized_invoice_ids": finalized_ids})
