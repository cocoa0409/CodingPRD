"""Product Recall & Field Action API — Flask entry point.

In-memory only. No seeding: the store starts empty on every process boot.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

from db import store, new_id
import db
from errors import ApiError, err, ERRORS
from response import success, error_response
from middleware import authenticate, authorize
from pagination import paginate
import services as svc
import serialize as ser
import validate as V

app = Flask(__name__)

ALL_ROLES = [
    "RecallCoordinator",
    "QualityOfficer",
    "FieldServiceAgent",
    "FinanceClerk",
    "PlatformAdmin",
]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_response(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = error_response("ERR_NOT_FOUND", "Resource not found")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = error_response("ERR_NOT_FOUND", "Method not allowed")
    return body, 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
    return body, 422


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3)
# ---------------------------------------------------------------------------
def find(collection, _id):
    e = collection.get(_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return e


def fk(collection, _id, label="reference"):
    e = collection.get(_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "Referenced %s does not exist" % label)
    return e


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "PlatformAdmin"])
    body = V.get_body()
    sku = V.req_str(body, "sku")
    name = V.req_str(body, "name")
    regulator = V.req_enum(body, "regulator", {"FDA", "CPSC"})
    price = V.req_int(body, "unit_list_price_cents", minimum=1)

    with store.lock:
        for p in store.products.values():
            if p["sku"] == sku:
                raise err("ERR_DUPLICATE_KEY", "sku already exists")
        e = {"id": new_id(), "sku": sku, "name": name, "regulator": regulator,
             "unit_list_price_cents": price, "active_recall_id": None}
        e.update(svc.common_create_fields())
        store.products[e["id"]] = e
    return success(ser.product_out(e), 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.products, pid)
    return success(ser.product_out(e), 200)


@app.route("/products", methods=["GET"])
def list_products():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.products.values())
    sku = request.args.get("sku")
    regulator = request.args.get("regulator")
    if sku is not None:
        items = [p for p in items if p["sku"] == sku]
    if regulator is not None:
        items = [p for p in items if p["regulator"] == regulator]
    page, meta = paginate(items)
    return success([ser.product_out(p) for p in page], 200, pagination=meta)


# ===========================================================================
# LOTS
# ===========================================================================
@app.route("/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "PlatformAdmin"])
    body = V.get_body()
    product_id = V.req_str(body, "product_id")
    with store.lock:
        # existence (priority 3) before non-FK body well-formedness (priority 4)
        fk(store.products, product_id, "product_id")
        lot_code = V.req_str(body, "lot_code")
        serial_start = V.req_int(body, "serial_start", minimum=1)
        serial_end = V.req_int(body, "serial_end", minimum=1)
        if serial_end < serial_start:
            raise err("ERR_INVALID_REQUEST", "serial_end must be >= serial_start")
        # Duplicate lot_code within product
        for lot in store.lots.values():
            if lot["product_id"] == product_id and lot["lot_code"] == lot_code:
                raise err("ERR_DUPLICATE_KEY", "lot_code already exists for product")
        # Range overlap (closed-interval) within product
        for lot in store.lots.values():
            if lot["product_id"] != product_id:
                continue
            if serial_start <= lot["serial_end"] and serial_end >= lot["serial_start"]:
                raise err("ERR_LOT_RANGE_OVERLAP", "serial range overlaps an existing lot")
        e = {"id": new_id(), "product_id": product_id, "lot_code": lot_code,
             "serial_start": serial_start, "serial_end": serial_end,
             "manufactured_units": serial_end - serial_start + 1,
             "quarantine_status": "RELEASED"}
        e.update(svc.common_create_fields())
        store.lots[e["id"]] = e
    return success(ser.lot_out(e), 201)


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.lots, lid)
    return success(ser.lot_out(e), 200)


@app.route("/lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.lots.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    page, meta = paginate(items)
    return success([ser.lot_out(l) for l in page], 200, pagination=meta)


# ===========================================================================
# UNITS
# ===========================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "FieldServiceAgent", "PlatformAdmin"])
    body = V.get_body()
    lot_id = V.req_str(body, "lot_id")
    customer_id = V.req_str(body, "customer_id")

    with store.lock:
        # existence (priority 3): resolve FKs left-to-right before non-FK body checks
        lot = fk(store.lots, lot_id, "lot_id")
        fk(store.customers, customer_id, "customer_id")
        serial_number = V.req_int(body, "serial_number")
        sale_price_cents = V.req_int(body, "sale_price_cents", minimum=0)
        # serial range (422) before uniqueness (409): validation order priorities
        # 18 (ERR_SERIAL_OUT_OF_RANGE) precedes 25 (ERR_DUPLICATE_KEY).
        if serial_number < lot["serial_start"] or serial_number > lot["serial_end"]:
            raise err("ERR_SERIAL_OUT_OF_RANGE", "serial_number outside lot range")
        for u in store.units.values():
            if u["lot_id"] == lot_id and u["serial_number"] == serial_number:
                raise err("ERR_DUPLICATE_KEY", "serial_number already exists in lot")
        e = {"id": new_id(), "lot_id": lot_id, "serial_number": serial_number,
             "customer_id": customer_id, "sale_price_cents": sale_price_cents,
             "affected": False}
        e.update(svc.common_create_fields())
        store.units[e["id"]] = e
        svc.recompute_single_unit_affected(e)
        # If this unit became affected, refresh counters on any covering recalls.
        for recall in store.recalls.values():
            if lot_id in svc.affected_lot_ids_for_recall(recall["id"]):
                svc.recompute_recall_counters(recall)
    return success(ser.unit_out(e), 201)


@app.route("/units/<uid>", methods=["GET"])
def get_unit(uid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.units, uid)
    return success(ser.unit_out(e), 200)


@app.route("/units", methods=["GET"])
def list_units():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.units.values())
    lot_id = request.args.get("lot_id")
    customer_id = request.args.get("customer_id")
    affected = request.args.get("affected")
    if lot_id is not None:
        items = [u for u in items if u["lot_id"] == lot_id]
    if customer_id is not None:
        items = [u for u in items if u["customer_id"] == customer_id]
    if affected is not None:
        want = affected.lower() in ("true", "1", "yes")
        items = [u for u in items if u["affected"] == want]
    page, meta = paginate(items)
    return success([ser.unit_out(u) for u in page], 200, pagination=meta)


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "FieldServiceAgent", "PlatformAdmin"])
    body = V.get_body()
    name = V.req_str(body, "name")
    contact_channel = V.req_enum(body, "contact_channel", {"EMAIL", "SMS", "MAIL"})
    contact_address = V.req_str(body, "contact_address")
    reachable = V.opt_bool(body, "reachable", default=True)

    with store.lock:
        e = {"id": new_id(), "name": name, "contact_channel": contact_channel,
             "contact_address": contact_address, "reachable": reachable}
        e.update(svc.common_create_fields())
        store.customers[e["id"]] = e
    return success(ser.customer_out(e), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.customers, cid)
    return success(ser.customer_out(e), 200)


@app.route("/customers/<cid>", methods=["PATCH"])
def update_customer(cid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "FieldServiceAgent", "PlatformAdmin"])
    with store.lock:
        e = find(store.customers, cid)
        body = V.get_body()
        channel = V.opt_enum(body, "contact_channel", {"EMAIL", "SMS", "MAIL"})
        address = body.get("contact_address")
        reachable = V.opt_bool(body, "reachable")
        if "contact_address" in body and body["contact_address"] is not None:
            if not isinstance(address, str) or address == "":
                raise err("ERR_INVALID_REQUEST", "contact_address must be a non-empty string")
        if channel is not None:
            e["contact_channel"] = channel
        if "contact_address" in body and body["contact_address"] is not None:
            e["contact_address"] = address
        if reachable is not None:
            e["reachable"] = reachable
        svc.touch(e)
    return success(ser.customer_out(e), 200)


# ===========================================================================
# RECALLS
# ===========================================================================
def _recall_window_overlap(product_id, new_start, new_end, exclude_id=None):
    """Unbounded/half-open overlap vs non-terminal recalls on the same product."""
    ns = new_start if new_start is not None else float("-inf")
    ne = new_end if new_end is not None else float("inf")
    for r in store.recalls.values():
        if r["id"] == exclude_id:
            continue
        if r["product_id"] != product_id:
            continue
        if r["status"] in ("TERMINATED", "EFFECTIVE"):
            continue
        es = r["serial_filter_start"] if r["serial_filter_start"] is not None else float("-inf")
        ee = r["serial_filter_end"] if r["serial_filter_end"] is not None else float("inf")
        if max(ns, es) <= min(ne, ee):
            return True
    return False


@app.route("/recalls", methods=["POST"])
def create_recall():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "PlatformAdmin"])
    body = V.get_body()
    product_id = V.req_str(body, "product_id")

    with store.lock:
        # existence (priority 3) before non-FK body well-formedness (priority 4)
        fk(store.products, product_id, "product_id")
        reason = V.req_str(body, "reason")
        hazard_severity = V.req_enum(body, "hazard_severity", {"SERIOUS", "TEMPORARY", "MINOR"})
        injury_reported = V.opt_bool(body, "injury_reported", default=False)
        serial_filter_start = V.opt_int(body, "serial_filter_start")
        serial_filter_end = V.opt_int(body, "serial_filter_end")
        if _recall_window_overlap(product_id, serial_filter_start, serial_filter_end):
            raise err("ERR_RECALL_WINDOW_OVERLAP", "serial window overlaps a non-terminal recall")
        e = {"id": new_id(), "product_id": product_id, "reason": reason,
             "hazard_severity": hazard_severity, "injury_reported": injury_reported,
             "serial_filter_start": serial_filter_start,
             "serial_filter_end": serial_filter_end,
             "classification": None, "classified_by_user_id": None,
             "approved_by_user_id": None, "status": "DRAFT",
             "notification_deadline_hours": None, "affected_unit_count": 0,
             "recovered_unit_count": 0, "effectiveness_pct": 0.0,
             "total_refund_cents": 0}
        e.update(svc.common_create_fields())
        store.recalls[e["id"]] = e
    return success(ser.recall_out(e), 201)


@app.route("/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.recalls, rid)
    return success(ser.recall_out(e), 200)


@app.route("/recalls", methods=["GET"])
def list_recalls():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.recalls.values())
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success([ser.recall_out(r) for r in page], 200, pagination=meta)


@app.route("/recalls/<rid>/effectiveness", methods=["GET"])
def recall_effectiveness(rid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "FinanceClerk", "PlatformAdmin"])
    e = find(store.recalls, rid)
    return success(ser.recall_out(e), 200)


# ---- affected lots (OCC-guarded) ----
@app.route("/recalls/<rid>/affected-lots", methods=["POST"])
def add_affected_lot(rid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "PlatformAdmin"])
    with store.lock:
        recall = find(store.recalls, rid)
        body = V.get_body()
        lot_id = V.req_str(body, "lot_id")
        # existence (priority 3): resolve body FK before OCC/state checks
        lot = fk(store.lots, lot_id, "lot_id")
        expected_version = V.req_int(body, "expected_recall_version")
        # OCC (priority 5) precedes generic state.
        if expected_version != recall["version"]:
            raise err("ERR_STALE_VERSION", "expected_recall_version does not match")
        al = {"id": new_id(), "recall_id": rid, "lot_id": lot_id,
              "unit_count_snapshot": lot["manufactured_units"],
              "created_at": db.iso_now(), "_seq": store.next_seq()}
        store.affected_lots[al["id"]] = al
        svc.recompute_affected_flags(recall)
        svc.recompute_recall_counters(recall)
        svc.touch(recall)
    return success(ser.affected_lot_out(al), 201)


@app.route("/affected-lots/<aid>", methods=["GET"])
def get_affected_lot(aid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.affected_lots, aid)
    return success(ser.affected_lot_out(e), 200)


@app.route("/affected-lots", methods=["GET"])
def list_affected_lots():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.affected_lots.values())
    recall_id = request.args.get("recall_id")
    lot_id = request.args.get("lot_id")
    if recall_id is not None:
        items = [a for a in items if a["recall_id"] == recall_id]
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    page, meta = paginate(items)
    return success([ser.affected_lot_out(a) for a in page], 200, pagination=meta)


# ---- recall lifecycle transitions ----
@app.route("/recalls/<rid>/classify", methods=["POST"])
def classify_recall(rid):
    _, user_id, role = _auth_with_user(["RecallCoordinator"])
    with store.lock:
        recall = find(store.recalls, rid)
        if recall["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "recall is not in DRAFT")
        # business rule ordering: no-affected-lots (conflict, 11) then inverted
        # filter (malformed, 12).
        lot_ids = svc.affected_lot_ids_for_recall(rid)
        if not lot_ids:
            raise err("ERR_NO_AFFECTED_LOTS", "recall has no affected lots")
        s = recall["serial_filter_start"]
        e_ = recall["serial_filter_end"]
        if s is not None and e_ is not None and s > e_:
            raise err("ERR_INVALID_SERIAL_FILTER", "serial_filter_start > serial_filter_end")
        recall["classification"] = svc.classification_rule(
            recall["hazard_severity"], recall["injury_reported"])
        product = store.products[recall["product_id"]]
        recall["notification_deadline_hours"] = svc.notification_window_rule(
            recall["classification"], product["regulator"], recall["injury_reported"])
        recall["classified_by_user_id"] = user_id
        recall["status"] = "CLASSIFIED"
        svc.recompute_affected_flags(recall)
        svc.recompute_recall_counters(recall)
        product["active_recall_id"] = rid
        svc.touch(product)
        svc.touch(recall)
    return success(ser.recall_out(recall), 200)


@app.route("/recalls/<rid>/reclassify", methods=["POST"])
def reclassify_recall(rid):
    _, user_id, role = _auth_with_user(["RecallCoordinator"])
    with store.lock:
        recall = find(store.recalls, rid)
        body = V.get_body()
        hazard_severity = V.opt_enum(body, "hazard_severity", {"SERIOUS", "TEMPORARY", "MINOR"})
        injury_reported = V.opt_bool(body, "injury_reported")
        sfs_present = "serial_filter_start" in body
        sfe_present = "serial_filter_end" in body
        serial_filter_start = V.opt_int(body, "serial_filter_start")
        serial_filter_end = V.opt_int(body, "serial_filter_end")
        if recall["status"] != "CLASSIFIED":
            raise err("ERR_INVALID_STATE", "recall is not in CLASSIFIED")
        # business rule: no report SUBMITTED/ACKNOWLEDGED (22)
        for rep in store.regulatory_reports.values():
            if rep["recall_id"] == rid and rep["status"] in ("SUBMITTED", "ACKNOWLEDGED"):
                raise err("ERR_REPORT_ALREADY_FILED", "a report has already been filed")
        # apply field edits
        if hazard_severity is not None:
            recall["hazard_severity"] = hazard_severity
        if injury_reported is not None:
            recall["injury_reported"] = injury_reported
        if sfs_present:
            recall["serial_filter_start"] = serial_filter_start
        if sfe_present:
            recall["serial_filter_end"] = serial_filter_end
        # clear derived classification fields
        recall["classification"] = None
        recall["notification_deadline_hours"] = None
        recall["classified_by_user_id"] = None
        recall["status"] = "DRAFT"
        svc.recompute_affected_flags(recall)
        svc.recompute_recall_counters(recall)
        svc.touch(recall)
    return success(ser.recall_out(recall), 200)


@app.route("/recalls/<rid>/announce", methods=["POST"])
def announce_recall(rid):
    _, user_id, role = _auth_with_user(["QualityOfficer"])
    with store.lock:
        recall = find(store.recalls, rid)
        if recall["status"] != "CLASSIFIED":
            raise err("ERR_INVALID_STATE", "recall is not in CLASSIFIED")
        # segregation of duties (7) before initial-report-required (8)
        if user_id == recall["classified_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", "announcer must differ from classifier")
        has_initial = any(
            rep["recall_id"] == rid and rep["report_kind"] == "INITIAL"
            and rep["status"] in ("SUBMITTED", "ACKNOWLEDGED")
            for rep in store.regulatory_reports.values())
        if not has_initial:
            raise err("ERR_INITIAL_REPORT_REQUIRED", "an INITIAL report must be filed first")
        recall["approved_by_user_id"] = user_id
        recall["status"] = "ANNOUNCED"
        # affected flags now reflect non-DRAFT status (already set at classify,
        # but recompute to be safe across the transition).
        svc.recompute_affected_flags(recall)
        svc.recompute_recall_counters(recall)
        # CASCADE hop 1+2: quarantine holds per affected lot lacking one.
        lot_ids = svc.affected_lot_ids_for_recall(rid)
        for lot_id in lot_ids:
            existing = any(
                h["recall_id"] == rid and h["lot_id"] == lot_id and h["status"] == "ACTIVE"
                for h in store.quarantine_holds.values())
            if not existing:
                hold = {"id": new_id(), "recall_id": rid, "lot_id": lot_id,
                        "reason": "Recall announced", "status": "ACTIVE",
                        "lifted_count": 0}
                hold.update(svc.common_create_fields())
                store.quarantine_holds[hold["id"]] = hold
                lot = store.lots[lot_id]
                svc.recompute_lot_quarantine_status(lot)
        # notification fan-out: one QUEUED per distinct customer owning an affected unit
        seen_customers = set()
        affected_units = [u for u in store.units.values()
                          if u["affected"] and svc._unit_in_recall(u, rid)]
        # deterministic order by unit creation sequence
        for u in sorted(affected_units, key=lambda x: x["_seq"]):
            cust = u["customer_id"]
            if cust in seen_customers:
                continue
            seen_customers.add(cust)
            n = {"id": new_id(), "recall_id": rid, "customer_id": cust,
                 "channel": None, "status": "QUEUED", "attempt_count": 0}
            n.update(svc.common_create_fields())
            store.notifications[n["id"]] = n
        svc.touch(recall)
    return success(ser.recall_out(recall), 200)


@app.route("/recalls/<rid>/begin-monitoring", methods=["POST"])
def begin_monitoring(rid):
    _, user_id, role = _auth_with_user(["RecallCoordinator"])
    with store.lock:
        recall = find(store.recalls, rid)
        if recall["status"] != "ANNOUNCED":
            raise err("ERR_INVALID_STATE", "recall is not in ANNOUNCED")
        pending = any(
            n["recall_id"] == rid and n["status"] == "QUEUED"
            for n in store.notifications.values())
        if pending:
            raise err("ERR_NOTIFICATIONS_PENDING", "notifications still QUEUED")
        recall["status"] = "MONITORING"
        svc.touch(recall)
    return success(ser.recall_out(recall), 200)


@app.route("/recalls/<rid>/terminate", methods=["POST"])
def terminate_recall(rid):
    _, user_id, role = _auth_with_user(["QualityOfficer"])
    with store.lock:
        recall = find(store.recalls, rid)
        body = V.get_body()
        force_terminate = V.opt_bool(body, "force_terminate", default=False)
        if recall["status"] != "MONITORING":
            raise err("ERR_INVALID_STATE", "recall is not in MONITORING")
        # FINAL report required (9) — applies to both branches.
        has_final = any(
            rep["recall_id"] == rid and rep["report_kind"] == "FINAL"
            and rep["status"] in ("SUBMITTED", "ACKNOWLEDGED")
            for rep in store.regulatory_reports.values())
        if not has_final:
            raise err("ERR_FINAL_REPORT_REQUIRED", "a FINAL report must be filed first")
        # latest effectiveness check
        checks = [c for c in store.effectiveness_checks.values() if c["recall_id"] == rid]
        latest = max(checks, key=lambda c: c["_seq"]) if checks else None
        if force_terminate:
            new_status = "TERMINATED"
        else:
            # to EFFECTIVE requires latest check PASS (21)
            if latest is None or latest["outcome"] != "PASS":
                raise err("ERR_EFFECTIVENESS_NOT_MET", "latest effectiveness check is not PASS")
            new_status = "EFFECTIVE"
        recall["status"] = new_status
        # quarantine release cascade
        lot_ids = svc.affected_lot_ids_for_recall(rid)
        for hold in store.quarantine_holds.values():
            if hold["recall_id"] == rid and hold["status"] == "ACTIVE":
                hold["status"] = "LIFTED"
                hold["lifted_count"] = hold["lifted_count"] + 1
                svc.touch(hold)
        for lot_id in lot_ids:
            lot = store.lots.get(lot_id)
            if lot:
                svc.recompute_lot_quarantine_status(lot)
        product = store.products.get(recall["product_id"])
        if product and product["active_recall_id"] == rid:
            product["active_recall_id"] = None
            svc.touch(product)
        svc.touch(recall)
    return success(ser.recall_out(recall), 200)


# ===========================================================================
# QUARANTINE HOLDS
# ===========================================================================
@app.route("/quarantine-holds/<hid>", methods=["GET"])
def get_quarantine_hold(hid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.quarantine_holds, hid)
    return success(ser.quarantine_hold_out(e), 200)


@app.route("/quarantine-holds", methods=["GET"])
def list_quarantine_holds():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.quarantine_holds.values())
    recall_id = request.args.get("recall_id")
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    if recall_id is not None:
        items = [h for h in items if h["recall_id"] == recall_id]
    if lot_id is not None:
        items = [h for h in items if h["lot_id"] == lot_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, meta = paginate(items)
    return success([ser.quarantine_hold_out(h) for h in page], 200, pagination=meta)


@app.route("/quarantine-holds/<hid>/lift", methods=["POST"])
def lift_hold(hid):
    _, user_id, role = _auth_with_user(["RecallCoordinator"])
    with store.lock:
        hold = find(store.quarantine_holds, hid)
        if hold["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "hold is not ACTIVE")
        recall = store.recalls[hold["recall_id"]]
        if recall["status"] not in ("MONITORING", "EFFECTIVE", "TERMINATED"):
            raise err("ERR_HOLD_LOCKED_BY_RECALL", "owning recall locks the hold")
        hold["status"] = "LIFTED"
        hold["lifted_count"] = hold["lifted_count"] + 1
        svc.touch(hold)
        lot = store.lots.get(hold["lot_id"])
        if lot:
            svc.recompute_lot_quarantine_status(lot)
    return success(ser.quarantine_hold_out(hold), 200)


@app.route("/quarantine-holds/<hid>/reimpose", methods=["POST"])
def reimpose_hold(hid):
    _, user_id, role = _auth_with_user(["RecallCoordinator"])
    with store.lock:
        hold = find(store.quarantine_holds, hid)
        if hold["status"] != "LIFTED":
            raise err("ERR_INVALID_STATE", "hold is not LIFTED")
        recall = store.recalls[hold["recall_id"]]
        if recall["status"] in ("TERMINATED", "EFFECTIVE"):
            raise err("ERR_HOLD_LOCKED_BY_RECALL", "owning recall locks the hold")
        hold["status"] = "ACTIVE"
        svc.touch(hold)
        lot = store.lots.get(hold["lot_id"])
        if lot:
            svc.recompute_lot_quarantine_status(lot)
    return success(ser.quarantine_hold_out(hold), 200)


# ===========================================================================
# NOTIFICATIONS
# ===========================================================================
@app.route("/notifications/<nid>", methods=["GET"])
def get_notification(nid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "PlatformAdmin"])
    e = find(store.notifications, nid)
    return success(ser.notification_out(e), 200)


@app.route("/notifications", methods=["GET"])
def list_notifications():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "PlatformAdmin"])
    items = list(store.notifications.values())
    recall_id = request.args.get("recall_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if recall_id is not None:
        items = [n for n in items if n["recall_id"] == recall_id]
    if customer_id is not None:
        items = [n for n in items if n["customer_id"] == customer_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    page, meta = paginate(items)
    return success([ser.notification_out(n) for n in page], 200, pagination=meta)


@app.route("/notifications/<nid>/send", methods=["POST"])
def send_notification(nid):
    _, user_id, role = _auth_with_user(["PlatformAdmin"])
    with store.lock:
        n = find(store.notifications, nid)
        if n["status"] not in ("QUEUED", "FAILED"):
            raise err("ERR_INVALID_STATE", "notification is not QUEUED or FAILED")
        customer = store.customers[n["customer_id"]]
        if n["status"] == "QUEUED":
            # QUEUED forks to SENT or FAILED on reachability (no guard error).
            n["attempt_count"] = n["attempt_count"] + 1
            if customer["reachable"]:
                n["status"] = "SENT"
                n["channel"] = customer["contact_channel"]
            else:
                n["status"] = "FAILED"
            svc.touch(n)
        else:  # FAILED -> SENT requires reachable, else guard error
            if not customer["reachable"]:
                raise err("ERR_CUSTOMER_UNREACHABLE", "customer is not reachable")
            n["attempt_count"] = n["attempt_count"] + 1
            n["status"] = "SENT"
            n["channel"] = customer["contact_channel"]
            svc.touch(n)
    return success(ser.notification_out(n), 200)


@app.route("/notifications/<nid>/acknowledge", methods=["POST"])
def acknowledge_notification(nid):
    _, user_id, role = _auth_with_user(["PlatformAdmin"])
    with store.lock:
        n = find(store.notifications, nid)
        if n["status"] != "SENT":
            raise err("ERR_INVALID_STATE", "notification is not SENT")
        n["status"] = "ACKNOWLEDGED"
        svc.touch(n)
    return success(ser.notification_out(n), 200)


# ===========================================================================
# DISPOSITIONS
# ===========================================================================
@app.route("/dispositions", methods=["POST"])
def create_disposition():
    _, user_id, role = _auth_with_user(["FieldServiceAgent"])
    with store.lock:
        body = V.get_body()
        recall_id = V.req_str(body, "recall_id")
        unit_id = V.req_str(body, "unit_id")
        # existence (priority 3): resolve FKs left-to-right before non-FK body checks
        recall = fk(store.recalls, recall_id, "recall_id")
        unit = fk(store.units, unit_id, "unit_id")
        disposition_type = V.req_enum(body, "disposition_type", {"RETURN", "REPLACE", "REFUND"})
        refund_basis = V.opt_enum(body, "refund_basis", {"SALE_PRICE", "LIST_PRICE"}, default="SALE_PRICE")
        expected_version = V.req_int(body, "expected_recall_version")
        # OCC (priority 5) before generic state (6) and business rules.
        if expected_version != recall["version"]:
            raise err("ERR_STALE_VERSION", "expected_recall_version does not match")
        # recall must be open for disposition (17)
        if recall["status"] not in ("ANNOUNCED", "MONITORING"):
            raise err("ERR_RECALL_NOT_OPEN_FOR_DISPOSITION", "recall not open for disposition")
        # unit affected (13)
        if not (unit["affected"] and svc._unit_in_recall(unit, recall_id)):
            raise err("ERR_UNIT_NOT_AFFECTED", "unit is not affected by this recall")
        # at most one PENDING per (recall_id, unit_id) (14)
        for d in store.dispositions.values():
            if d["recall_id"] == recall_id and d["unit_id"] == unit_id \
                    and d["logistics_status"] == "PENDING":
                raise err("ERR_DUPLICATE_DISPOSITION", "an open disposition already exists")
        d = {"id": new_id(), "recall_id": recall_id, "unit_id": unit_id,
             "disposition_type": disposition_type, "logistics_status": "PENDING",
             "financial_status": "NOT_OWED", "refund_basis": refund_basis,
             "refund_amount_cents": 0}
        d.update(svc.common_create_fields())
        store.dispositions[d["id"]] = d
        # opening bumps Recall.version
        svc.touch(recall)
    return success(ser.disposition_out(d), 201)


@app.route("/dispositions/<did>", methods=["GET"])
def get_disposition(did):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    e = find(store.dispositions, did)
    return success(ser.disposition_out(e), 200)


@app.route("/dispositions", methods=["GET"])
def list_dispositions():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.dispositions.values())
    recall_id = request.args.get("recall_id")
    unit_id = request.args.get("unit_id")
    logistics_status = request.args.get("logistics_status")
    financial_status = request.args.get("financial_status")
    if recall_id is not None:
        items = [d for d in items if d["recall_id"] == recall_id]
    if unit_id is not None:
        items = [d for d in items if d["unit_id"] == unit_id]
    if logistics_status is not None:
        items = [d for d in items if d["logistics_status"] == logistics_status]
    if financial_status is not None:
        items = [d for d in items if d["financial_status"] == financial_status]
    page, meta = paginate(items)
    return success([ser.disposition_out(d) for d in page], 200, pagination=meta)


@app.route("/dispositions/<did>/receive-return", methods=["POST"])
def receive_return(did):
    _, user_id, role = _auth_with_user(["FieldServiceAgent"])
    with store.lock:
        d = find(store.dispositions, did)
        if d["logistics_status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "disposition logistics is not PENDING")
        if d["disposition_type"] not in ("RETURN", "REFUND"):
            raise err("ERR_DISPOSITION_TYPE_MISMATCH", "type does not allow return receipt")
        recall = store.recalls[d["recall_id"]]
        if recall["status"] not in ("ANNOUNCED", "MONITORING"):
            raise err("ERR_RECALL_NOT_OPEN_FOR_DISPOSITION", "recall not open for disposition")
        d["logistics_status"] = "RETURNED"
        svc.touch(d)
        svc.recompute_recall_counters(recall)
        svc.touch(recall)
    return success(ser.disposition_out(d), 200)


@app.route("/dispositions/<did>/ship-replacement", methods=["POST"])
def ship_replacement(did):
    _, user_id, role = _auth_with_user(["FieldServiceAgent"])
    with store.lock:
        d = find(store.dispositions, did)
        if d["logistics_status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "disposition logistics is not PENDING")
        if d["disposition_type"] != "REPLACE":
            raise err("ERR_DISPOSITION_TYPE_MISMATCH", "type does not allow replacement")
        recall = store.recalls[d["recall_id"]]
        if recall["status"] not in ("ANNOUNCED", "MONITORING"):
            raise err("ERR_RECALL_NOT_OPEN_FOR_DISPOSITION", "recall not open for disposition")
        d["logistics_status"] = "REPLACED"
        svc.touch(d)
        svc.recompute_recall_counters(recall)
        svc.touch(recall)
    return success(ser.disposition_out(d), 200)


@app.route("/dispositions/<did>/cancel", methods=["POST"])
def cancel_disposition(did):
    _, user_id, role = _auth_with_user(["FieldServiceAgent"])
    with store.lock:
        d = find(store.dispositions, did)
        # PRD §3.9: cancellation is refused if the disposition has already been
        # refunded (financial REFUNDED). This guard is evaluated before the
        # generic logistics-state check because a REFUNDED disposition has
        # logistics RETURNED, and the PRD names ERR_DISPOSITION_ALREADY_REFUNDED
        # for it. The PRD's OWED->VOID and already-refunded branches both only
        # arise once a return has been received, so cancel is permitted from a
        # RETURNED logistics state as well as PENDING.
        if d["financial_status"] == "REFUNDED":
            raise err("ERR_DISPOSITION_ALREADY_REFUNDED", "disposition already refunded")
        if d["logistics_status"] not in ("PENDING", "RETURNED"):
            raise err("ERR_INVALID_STATE", "disposition cannot be cancelled from its current logistics state")
        d["logistics_status"] = "CANCELLED"
        if d["financial_status"] == "OWED":
            d["financial_status"] = "VOID"
        svc.touch(d)
        recall = store.recalls[d["recall_id"]]
        svc.recompute_recall_counters(recall)
        svc.touch(recall)
    return success(ser.disposition_out(d), 200)


@app.route("/dispositions/<did>/accrue-refund", methods=["POST"])
def accrue_refund(did):
    _, user_id, role = _auth_with_user(["FinanceClerk"])
    with store.lock:
        d = find(store.dispositions, did)
        if d["financial_status"] != "NOT_OWED":
            raise err("ERR_INVALID_STATE", "financial status is not NOT_OWED")
        if d["disposition_type"] != "REFUND":
            raise err("ERR_DISPOSITION_TYPE_MISMATCH", "type is not REFUND")
        if d["logistics_status"] != "RETURNED":
            raise err("ERR_RETURN_NOT_RECEIVED", "return not received")
        d["financial_status"] = "OWED"
        svc.touch(d)
    return success(ser.disposition_out(d), 200)


@app.route("/dispositions/<did>/settle-refund", methods=["POST"])
def settle_refund(did):
    _, user_id, role = _auth_with_user(["FinanceClerk"])
    with store.lock:
        d = find(store.dispositions, did)
        if d["financial_status"] != "OWED":
            raise err("ERR_INVALID_STATE", "financial status is not OWED")
        if d["logistics_status"] != "RETURNED":
            raise err("ERR_RETURN_NOT_RECEIVED", "return not received")
        recall = store.recalls[d["recall_id"]]
        d["refund_amount_cents"] = svc.refund_amount_rule(d, recall)
        d["financial_status"] = "REFUNDED"
        svc.touch(d)
        svc.recompute_refund_ledger(recall)
        svc.touch(recall)
    return success(ser.disposition_out(d), 200)


# ===========================================================================
# REGULATORY REPORTS
# ===========================================================================
@app.route("/regulatory-reports", methods=["POST"])
def create_report():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer"])
    body = V.get_body()
    recall_id = V.req_str(body, "recall_id")
    with store.lock:
        # existence (priority 3) before non-FK body well-formedness (priority 4)
        fk(store.recalls, recall_id, "recall_id")
        report_kind = V.req_enum(body, "report_kind", {"INITIAL", "FOLLOWUP", "FINAL"})
        e = {"id": new_id(), "recall_id": recall_id, "agency": None,
             "report_kind": report_kind, "filed_within_deadline": None,
             "status": "DRAFTED", "signed_by_user_id": None}
        e.update(svc.common_create_fields())
        store.regulatory_reports[e["id"]] = e
    return success(ser.regulatory_report_out(e), 201)


@app.route("/regulatory-reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "PlatformAdmin"])
    e = find(store.regulatory_reports, rid)
    return success(ser.regulatory_report_out(e), 200)


@app.route("/regulatory-reports", methods=["GET"])
def list_reports():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "PlatformAdmin"])
    items = list(store.regulatory_reports.values())
    recall_id = request.args.get("recall_id")
    report_kind = request.args.get("report_kind")
    status = request.args.get("status")
    if recall_id is not None:
        items = [r for r in items if r["recall_id"] == recall_id]
    if report_kind is not None:
        items = [r for r in items if r["report_kind"] == report_kind]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success([ser.regulatory_report_out(r) for r in page], 200, pagination=meta)


@app.route("/regulatory-reports/<repid>/submit", methods=["POST"])
def submit_report(repid):
    _, user_id, role = _auth_with_user(["QualityOfficer"])
    with store.lock:
        rep = find(store.regulatory_reports, repid)
        if rep["status"] != "DRAFTED":
            raise err("ERR_INVALID_STATE", "report is not DRAFTED")
        recall = store.recalls[rep["recall_id"]]
        if recall["status"] == "DRAFT":
            raise err("ERR_RECALL_NOT_CLASSIFIED", "recall is still DRAFT")
        rep["signed_by_user_id"] = user_id
        product = store.products[recall["product_id"]]
        rep["agency"] = product["regulator"]
        if rep["report_kind"] == "INITIAL":
            rep["filed_within_deadline"] = _within_deadline(recall)
        rep["status"] = "SUBMITTED"
        svc.touch(rep)
    return success(ser.regulatory_report_out(rep), 200)


@app.route("/regulatory-reports/<repid>/acknowledge", methods=["POST"])
def acknowledge_report(repid):
    _, user_id, role = _auth_with_user(["PlatformAdmin"])
    with store.lock:
        rep = find(store.regulatory_reports, repid)
        if rep["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "report is not SUBMITTED")
        rep["status"] = "ACKNOWLEDGED"
        svc.touch(rep)
    return success(ser.regulatory_report_out(rep), 200)


def _within_deadline(recall):
    """filed_within_deadline: INITIAL submitted within notification window of created_at."""
    hours = recall["notification_deadline_hours"]
    if hours is None:
        return False
    created = _parse_iso(recall["created_at"])
    now = store.now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta_hours = (now - created).total_seconds() / 3600.0
    return delta_hours <= hours


def _parse_iso(s):
    # Accept trailing Z and optional fractional seconds.
    s2 = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ===========================================================================
# EFFECTIVENESS CHECKS
# ===========================================================================
@app.route("/effectiveness-checks", methods=["POST"])
def create_effectiveness_check():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer"])
    body = V.get_body()
    recall_id = V.req_str(body, "recall_id")
    with store.lock:
        recall = fk(store.recalls, recall_id, "recall_id")
        target = svc.effectiveness_target(recall["classification"])
        measured = recall["effectiveness_pct"]
        outcome = "PASS" if measured >= target else "FAIL"
        e = {"id": new_id(), "recall_id": recall_id, "target_pct": target,
             "measured_pct": measured, "outcome": outcome}
        e.update(svc.common_create_fields())
        store.effectiveness_checks[e["id"]] = e
    return success(ser.effectiveness_check_out(e), 201)


@app.route("/effectiveness-checks/<eid>", methods=["GET"])
def get_effectiveness_check(eid):
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "FinanceClerk", "PlatformAdmin"])
    e = find(store.effectiveness_checks, eid)
    return success(ser.effectiveness_check_out(e), 200)


@app.route("/effectiveness-checks", methods=["GET"])
def list_effectiveness_checks():
    _, role = authenticate()
    authorize(role, ["RecallCoordinator", "QualityOfficer", "FinanceClerk", "PlatformAdmin"])
    items = list(store.effectiveness_checks.values())
    recall_id = request.args.get("recall_id")
    outcome = request.args.get("outcome")
    if recall_id is not None:
        items = [c for c in items if c["recall_id"] == recall_id]
    if outcome is not None:
        items = [c for c in items if c["outcome"] == outcome]
    page, meta = paginate(items)
    return success([ser.effectiveness_check_out(c) for c in page], 200, pagination=meta)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, user_id, role = _auth_with_user(["PlatformAdmin"])
    body = V.get_body()
    to_iso8601 = V.req_str(body, "to_iso8601")
    try:
        dt = _parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    with store.lock:
        store.set_clock(dt)
    return success({}, 200)


# ---------------------------------------------------------------------------
# Auth convenience wrapper that also returns the user id
# ---------------------------------------------------------------------------
def _auth_with_user(allowed_roles):
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return None, user_id, role


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
