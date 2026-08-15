"""Routes: blend batches and work orders."""
from state import (
    D, ApiError, err_bad, rhu_int,
    customers, profiles, dies, lines, lots, formulations, batches,
    work_orders, runs, assignments, index_by_month, index_points,
    endpoint, list_result, get_body, Fields, require_exists,
    pagination, paginate, sort_created, mark, stamp_new,
    ser_batch, ser_work_order, clock_month,
    ALL_ROLES,
)
from services import (
    blend_composition, draw_lots, credit_back_lots,
    compute_pass_through, recompute_exposure, compute_invoice,
)


def _not_found(what):
    return ApiError("ERR_NOT_FOUND", 404, "%s not found" % what)


# ============================ Blend batches ================================
@endpoint("/blend-batches", ["POST"], ["LineOperator"])
def create_batch(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("formulation_id")
    f.str_("virgin_lot_id")
    f.str_("regrind_lot_id", required=False)
    f.str_("colorant_lot_id")
    f.num("target_batch_kg", positive=True)
    # existence (priority 3), body declaration order
    form = virgin = regrind = colorant = None
    vid = f.values.get("formulation_id")
    if isinstance(vid, str):
        form = require_exists(formulations, vid, "Formulation")
    vid = f.values.get("virgin_lot_id")
    if isinstance(vid, str):
        virgin = require_exists(lots, vid, "ResinLot")
    vid = f.values.get("regrind_lot_id")
    if isinstance(vid, str):
        regrind = require_exists(lots, vid, "ResinLot")
    vid = f.values.get("colorant_lot_id")
    if isinstance(vid, str):
        colorant = require_exists(lots, vid, "ResinLot")
    # priority 10: every referenced lot must be QC_PASSED
    if virgin is not None and colorant is not None and \
            (f.values.get("regrind_lot_id") is None or regrind is not None):
        refs = [virgin, colorant] + ([regrind] if regrind else [])
        for lot in refs:
            if lot["status"] != "QC_PASSED":
                raise ApiError("ERR_MATERIAL_NOT_RELEASED", 409,
                               "Referenced lot %s is not QC_PASSED"
                               % lot["id"])
        # priority 12: regrind purity
        if regrind is not None and form is not None:
            if regrind["lot_kind"] != "REGRIND" or \
                    regrind["resin_type"] != form["base_resin_type"] or \
                    regrind["color_family"] != form["color_family"]:
                raise ApiError("ERR_REGRIND_PURITY_VIOLATION", 422,
                               "Regrind lot violates lot purity rule")
        # priority 21: virgin / colorant compatibility
        if form is not None:
            if virgin["lot_kind"] != "VIRGIN" or \
                    virgin["resin_type"] != form["base_resin_type"]:
                raise ApiError("ERR_LOT_INCOMPATIBLE", 422,
                               "Virgin lot incompatible with formulation")
            if colorant["lot_kind"] != "COLORANT" or \
                    colorant["resin_type"] != form["base_resin_type"] or \
                    colorant["color_family"] != form["color_family"]:
                raise ApiError("ERR_LOT_INCOMPATIBLE", 422,
                               "Colorant lot incompatible with formulation")
        # composition + availability gate (priority 28)
        if form is not None and f.ok("target_batch_kg"):
            colorant_kg, regrind_kg, virgin_kg, actual_pct = \
                blend_composition(form, f.values["target_batch_kg"], regrind)
            if D(virgin["available_kg"]) < virgin_kg or \
                    D(colorant["available_kg"]) < colorant_kg:
                raise ApiError("ERR_INSUFFICIENT_LOT_QUANTITY", 422,
                               "Lot available_kg below computed draw")
    f.fail_if_problems()
    if form is None or virgin is None or colorant is None or \
            (f.values.get("regrind_lot_id") is not None and regrind is None):
        raise _not_found("Referenced resource")
    batch = stamp_new({
        "formulation_id": form["id"],
        "virgin_lot_id": virgin["id"],
        "regrind_lot_id": regrind["id"] if regrind else None,
        "colorant_lot_id": colorant["id"],
        "target_batch_kg": f.values["target_batch_kg"],
        "colorant_kg": colorant_kg,
        "regrind_kg": regrind_kg,
        "virgin_kg": virgin_kg,
        "actual_regrind_pct": actual_pct,
        "pre_quarantine_status": None,
        "last_qc_user_id": None,
        "status": "BLENDED",
    })
    batches[batch["id"]] = batch
    draw_lots(batch)
    return ser_batch(batch), 201


@endpoint("/blend-batches/<batch_id>", ["GET"], ALL_ROLES)
def get_batch(user_id, batch_id):
    return ser_batch(require_exists(batches, batch_id, "BlendBatch")), 200


@endpoint("/blend-batches", ["GET"], ALL_ROLES)
def list_batches(user_id):
    from flask import request
    limit, offset = pagination()
    items = sort_created(list(batches.values()))
    for key in ("formulation_id", "virgin_lot_id", "regrind_lot_id",
                "colorant_lot_id"):
        v = request.args.get(key)
        if v:
            items = [b for b in items if b.get(key) == v]
    page, total = paginate(items, limit, offset)
    return list_result([ser_batch(b) for b in page], limit, offset, total)


@endpoint("/blend-batches/<batch_id>/qc", ["POST"], ["QualityInspector"])
def batch_qc(user_id, batch_id):
    batch = require_exists(batches, batch_id, "BlendBatch")
    body = get_body()
    action = body.get("action")
    if not isinstance(action, str) or action not in ("RELEASE", "QUARANTINE",
                                                     "RE_RELEASE"):
        raise err_bad("action must be RELEASE, QUARANTINE or RE_RELEASE")
    # priority 5: SoD on RE_RELEASE (evaluated before from-state validity)
    if action == "RE_RELEASE" and batch.get("last_qc_user_id") is not None \
            and user_id == batch["last_qc_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Releasing inspector must differ from last_qc_user_id")
    if action == "RELEASE":
        if batch["status"] != "BLENDED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "RELEASE requires a BLENDED batch")
        batch["status"] = "QC_RELEASED"
        batch["last_qc_user_id"] = user_id
        mark(batch)
        return ser_batch(batch), 200
    if action == "QUARANTINE":
        if batch["status"] in ("BLENDED", "QC_RELEASED"):
            batch["pre_quarantine_status"] = batch["status"]
            batch["status"] = "QUARANTINED"
            credit_back_lots(batch)
            batch["last_qc_user_id"] = user_id
            mark(batch)
            return ser_batch(batch), 200
        if batch["status"] == "CONSUMED":
            consuming = [r for r in runs.values()
                         if r["batch_id"] == batch["id"]]
            run = consuming[0] if consuming else None
            if run is None or run["status"] not in ("RUNNING", "HOLD"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Consumed batch quarantine requires its run "
                               "RUNNING or HOLD")
            batch["pre_quarantine_status"] = "CONSUMED"
            batch["status"] = "QUARANTINED"
            batch["last_qc_user_id"] = user_id
            mark(batch)
            if run["status"] == "RUNNING":
                from services import hold_run_system
                hold_run_system(run)
            return ser_batch(batch), 200
        raise ApiError("ERR_INVALID_STATE", 409,
                       "QUARANTINE not allowed from %s" % batch["status"])
    # RE_RELEASE
    if batch["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "RE_RELEASE requires a QUARANTINED batch")
    pre = batch["pre_quarantine_status"]
    batch["status"] = pre
    batch["pre_quarantine_status"] = None
    if pre in ("BLENDED", "QC_RELEASED"):
        draw_lots(batch)
    batch["last_qc_user_id"] = user_id
    mark(batch)
    return ser_batch(batch), 200


# ============================ Work orders ==================================
@endpoint("/work-orders", ["POST"], ["SalesEngineer"])
def create_work_order(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("customer_id")
    f.str_("profile_id")
    f.str_("formulation_id")
    f.str_("die_id")
    f.num("ordered_length_m", positive=True)
    f.int_("cut_length_mm", min_v=1)
    f.int_("pieces_per_bundle", min_v=1)
    f.num("base_unit_price_cents_per_m", nonnegative=True)
    # existence (priority 3), body declaration order
    cust = prof = form = die = None
    v = f.values.get("customer_id")
    if isinstance(v, str):
        cust = require_exists(customers, v, "Customer")
    v = f.values.get("profile_id")
    if isinstance(v, str):
        prof = require_exists(profiles, v, "Profile")
    v = f.values.get("formulation_id")
    if isinstance(v, str):
        form = require_exists(formulations, v, "Formulation")
    v = f.values.get("die_id")
    if isinstance(v, str):
        die = require_exists(dies, v, "Die")
    # priority 25: referential integrity
    if cust is not None and prof is not None and form is not None \
            and die is not None:
        if prof["customer_id"] != cust["id"] or \
                form["profile_id"] != prof["id"] or \
                die["profile_id"] != prof["id"]:
            raise err_bad("Work-order references must belong together "
                          "(customer/profile/formulation/die)")
    # priority 26: quote-month index coverage
    qm = clock_month()
    pid = index_by_month.get(qm)
    if pid is None:
        raise ApiError("ERR_RESIN_INDEX_MISSING", 422,
                       "No resin index point for quote month %s" % qm)
    f.fail_if_problems()
    quote_index = D(index_points[pid]["index_cents_per_kg"])
    wo = stamp_new({
        "customer_id": cust["id"],
        "profile_id": prof["id"],
        "formulation_id": form["id"],
        "die_id": die["id"],
        "ordered_length_m": f.values["ordered_length_m"],
        "cut_length_mm": f.values["cut_length_mm"],
        "pieces_per_bundle": f.values["pieces_per_bundle"],
        "base_unit_price_cents_per_m": f.values["base_unit_price_cents_per_m"],
        "quote_month": qm,
        "quote_index_cents_per_kg": quote_index,
        "pass_through_adj_cents_per_m": D(0),
        "current_unit_price_cents_per_m":
            f.values["base_unit_price_cents_per_m"],
        "produced_good_length_m": D(0),
        "status": "QUOTED",
        "billing_status": "UNBILLED",
        "billed_length_m": None,
        "invoice_total_cents": None,
    })
    work_orders[wo["id"]] = wo
    return ser_work_order(wo), 201


@endpoint("/work-orders/<work_order_id>", ["GET"], ALL_ROLES)
def get_work_order(user_id, work_order_id):
    return ser_work_order(
        require_exists(work_orders, work_order_id, "WorkOrder")), 200


@endpoint("/work-orders", ["GET"], ALL_ROLES)
def list_work_orders(user_id):
    from flask import request
    limit, offset = pagination()
    items = sort_created(list(work_orders.values()))
    for key in ("customer_id", "profile_id", "formulation_id", "die_id"):
        v = request.args.get(key)
        if v:
            items = [w for w in items if w.get(key) == v]
    page, total = paginate(items, limit, offset)
    return list_result([ser_work_order(w) for w in page], limit, offset,
                       total)


@endpoint("/work-orders/<work_order_id>/confirm", ["POST"], ["SalesEngineer"])
def confirm_work_order(user_id, work_order_id):
    wo = require_exists(work_orders, work_order_id, "WorkOrder")
    get_body()
    if wo["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Confirm requires a QUOTED order")
    cust = customers[wo["customer_id"]]
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", 409,
                       "Customer is on CREDIT_HOLD")
    adj = compute_pass_through(wo)  # ERR_RESIN_INDEX_MISSING on gaps
    new_unit = D(wo["base_unit_price_cents_per_m"]) + adj
    # credit gate (priority 27): candidate strictly above limit is rejected
    term = rhu_int(D(wo["ordered_length_m"]) * new_unit)
    candidate = cust["open_exposure_cents"] + term
    if candidate > cust["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Candidate exposure exceeds credit limit")
    wo["pass_through_adj_cents_per_m"] = adj
    wo["current_unit_price_cents_per_m"] = new_unit
    wo["status"] = "CONFIRMED"
    mark(wo)
    recompute_exposure(cust["id"])
    return ser_work_order(wo), 200


@endpoint("/work-orders/<work_order_id>/reprice", ["POST"], ["SalesEngineer"])
def reprice_work_order(user_id, work_order_id):
    wo = require_exists(work_orders, work_order_id, "WorkOrder")
    body = get_body()
    occ_missing = False
    ev = body.get("expected_work_order_version")
    if ev is None or not (isinstance(ev, int) and not isinstance(ev, bool)):
        occ_missing = True
    elif ev != wo["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_work_order_version does not match current "
                       "version")
    if wo["status"] not in ("QUOTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Reprice requires QUOTED or CONFIRMED status")
    adj = compute_pass_through(wo)  # ERR_RESIN_INDEX_MISSING on gaps
    if occ_missing:
        raise err_bad("expected_work_order_version is required")
    wo["pass_through_adj_cents_per_m"] = adj
    wo["current_unit_price_cents_per_m"] = \
        D(wo["base_unit_price_cents_per_m"]) + adj
    if wo["status"] == "CONFIRMED":
        wo["status"] = "QUOTED"
    mark(wo)
    recompute_exposure(wo["customer_id"])
    return ser_work_order(wo), 200


@endpoint("/work-orders/<work_order_id>/cancel", ["POST"], ["SalesEngineer"])
def cancel_work_order(user_id, work_order_id):
    wo = require_exists(work_orders, work_order_id, "WorkOrder")
    get_body()
    if wo["status"] not in ("QUOTED", "CONFIRMED", "SCHEDULED",
                            "IN_PRODUCTION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order cannot be cancelled from %s" % wo["status"])
    own_asg = [a for a in assignments.values()
               if a["work_order_id"] == wo["id"]]
    own_ids = {a["id"] for a in own_asg}
    if any(r["assignment_id"] in own_ids and
           r["status"] in ("RUNNING", "HOLD") for r in runs.values()):
        raise ApiError("ERR_RUN_IN_PROGRESS", 409,
                       "A run under this order is RUNNING or HOLD")
    wo["status"] = "CANCELLED"
    mark(wo)
    for a in own_asg:
        if a["status"] in ("SCHEDULED", "ACTIVE"):
            was_active = a["status"] == "ACTIVE"
            a["status"] = "CANCELLED"
            mark(a)
            if was_active:
                line = lines[a["line_id"]]
                if line["status"] == "SETUP":
                    line["status"] = "IDLE"
                    mark(line)
    recompute_exposure(wo["customer_id"])
    return ser_work_order(wo), 200


@endpoint("/work-orders/<work_order_id>/invoice", ["POST"], ["PlantManager"])
def invoice_work_order(user_id, work_order_id):
    wo = require_exists(work_orders, work_order_id, "WorkOrder")
    get_body()
    if wo["status"] != "CLOSED" or wo["billing_status"] != "UNBILLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Invoice requires a CLOSED, UNBILLED order")
    billed, adj, final_unit, product, surcharge, total, die = \
        compute_invoice(wo)  # ERR_RESIN_INDEX_MISSING on gaps
    wo["pass_through_adj_cents_per_m"] = adj
    wo["current_unit_price_cents_per_m"] = final_unit
    wo["billed_length_m"] = billed
    wo["invoice_total_cents"] = total
    wo["billing_status"] = "INVOICED"
    mark(wo)
    if surcharge:
        die["amortized_cents"] += surcharge
        die["remaining_balance_cents"] -= surcharge
        mark(die)
    return ser_work_order(wo), 200
