"""Shared lookups, projections and cascades."""

import calc
import store
from errors import ApiError
from store import db, bump, set_fields


# ---------------------------------------------------------------- existence

def _lookup(bucket, entity_id, error_id):
    if not isinstance(entity_id, str):
        raise ApiError(error_id, "Referenced record does not exist.")
    rec = bucket.get(entity_id)
    if rec is None:
        raise ApiError(error_id, "Referenced record does not exist.")
    return rec


def get_family(entity_id):
    return _lookup(db.families, entity_id, "ERR_CERTIFICATION_FAMILY_NOT_FOUND")


def get_platform(entity_id):
    return _lookup(db.platforms, entity_id, "ERR_ENGINE_PLATFORM_NOT_FOUND")


def get_durability_test(entity_id):
    return _lookup(db.durability_tests, entity_id, "ERR_DURABILITY_TEST_NOT_FOUND")


def get_model(entity_id):
    return _lookup(db.product_models, entity_id, "ERR_PRODUCT_MODEL_NOT_FOUND")


def get_supplier(entity_id):
    return _lookup(db.suppliers, entity_id, "ERR_SUPPLIER_NOT_FOUND")


def get_lot(entity_id):
    return _lookup(db.component_lots, entity_id, "ERR_COMPONENT_LOT_NOT_FOUND")


def get_machining_run(entity_id):
    return _lookup(db.machining_runs, entity_id, "ERR_MACHINING_RUN_NOT_FOUND")


def get_assembly_line(entity_id):
    return _lookup(db.assembly_lines, entity_id, "ERR_ASSEMBLY_LINE_NOT_FOUND")


def get_build_order(entity_id):
    return _lookup(db.build_orders, entity_id, "ERR_BUILD_ORDER_NOT_FOUND")


def get_engine_unit(entity_id):
    return _lookup(db.engine_units, entity_id, "ERR_ENGINE_UNIT_NOT_FOUND")


def get_line_audit(entity_id):
    return _lookup(db.line_audits, entity_id, "ERR_LINE_AUDIT_NOT_FOUND")


def get_service_part(entity_id):
    return _lookup(db.service_parts, entity_id, "ERR_SERVICE_PART_NOT_FOUND")


# ---------------------------------------------------------------- uniqueness

def require_unique(bucket, field, value, scope_field=None, scope_value=None):
    for rec in bucket.values():
        if rec.get(field) != value:
            continue
        if scope_field is not None and rec.get(scope_field) != scope_value:
            continue
        raise ApiError("ERR_DUPLICATE_CODE", "%s '%s' is already in use." % (field, value))


# ---------------------------------------------------------------- projections

def family_platforms(family_id):
    return store.sort_created_asc(
        [p for p in db.platforms.values() if p["certification_family_id"] == family_id]
    )


def recompute_postures(family):
    """PRD 2.7 — posture is a pure projection of the owning family's status."""
    posture = calc.POSTURE_BY_FAMILY_STATUS[family["status"]]
    for platform in family_platforms(family["id"]):
        set_fields(platform, certification_posture=posture)


def platform_family(platform):
    return db.families.get(platform["certification_family_id"])


def model_platform(model):
    return db.platforms.get(model["engine_platform_id"])


def model_family(model):
    platform = model_platform(model)
    if platform is None:
        return None
    return platform_family(platform)


def order_model(order):
    return db.product_models.get(order["product_model_id"])


def order_family(order):
    model = order_model(order)
    if model is None:
        return None
    return model_family(model)


def models_of_platform(platform_id):
    return store.sort_created_asc(
        [m for m in db.product_models.values() if m["engine_platform_id"] == platform_id]
    )


def orders_of_model(model_id):
    return store.sort_created_asc(
        [o for o in db.build_orders.values() if o["product_model_id"] == model_id]
    )


def units_of_order(order_id):
    return store.sort_created_asc(
        [u for u in db.engine_units.values() if u["build_order_id"] == order_id]
    )


def audits_of_order(order_id):
    return store.sort_created_asc(
        [a for a in db.line_audits.values() if a["build_order_id"] == order_id]
    )


def family_orders(family_id):
    orders = []
    for platform in family_platforms(family_id):
        for model in models_of_platform(platform["id"]):
            orders.extend(orders_of_model(model["id"]))
    return store.sort_created_asc(orders)


# ------------------------------------------------------- safety certification

def latest_passing_certification(model_id):
    rows = [
        c for c in db.safety_certifications.values()
        if c["product_model_id"] == model_id and c["result"] == "PASSED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda c: (c["tested_on"], c["created_at"], c["_seq"]), reverse=True)
    return rows[0]


def check_safety_certification(model):
    """PRD 3.3 / 3.6 — ladder steps 34 then 35."""
    cert = latest_passing_certification(model["id"])
    if cert is None:
        raise ApiError(
            "ERR_SAFETY_CERTIFICATION_MISSING",
            "The model has no passing safety certification.",
        )
    if cert["expires_on"] < store.clock_date().isoformat():
        raise ApiError(
            "ERR_SAFETY_CERTIFICATION_EXPIRED",
            "The model's latest passing safety certification has expired.",
        )
    return cert


# ----------------------------------------------------------- build order maths

def recompute_order_progress(order):
    units = units_of_order(order["id"])
    staged = len([u for u in units if u["build_state"] in ("STAGED", "ASSEMBLED", "HOT_TESTED")])
    built = len([u for u in units if u["build_state"] == "RELEASED"])
    set_fields(order, staged_quantity=staged, built_quantity=built)
    return staged, built


# --------------------------------------------------------------- lot / supplier

def inspected_lots(supplier_id):
    rows = [
        lot for lot in db.component_lots.values()
        if lot["supplier_id"] == supplier_id
        and lot["status"] in ("ACCEPTED", "REJECTED", "DEVIATION_ACCEPTED")
        and (lot["sample_size"] or 0) > 0
        and lot["defects_found"] is not None
    ]
    return store.sort_created_asc(rows)


def counted_lots(supplier_id):
    """Lots that count toward inspected_lot_count."""
    rows = [
        lot for lot in db.component_lots.values()
        if lot["supplier_id"] == supplier_id
        and lot["status"] in ("ACCEPTED", "REJECTED", "DEVIATION_ACCEPTED")
    ]
    return store.sort_created_asc(rows)


def quarantine_cascade(supplier, inspected_lot_id):
    """PRD 3.4 — sibling lots quarantined, then their STAGED units."""
    quarantined_ids = []
    for lot in store.sort_created_asc(list(db.component_lots.values())):
        if lot["supplier_id"] != supplier["id"]:
            continue
        if lot["id"] == inspected_lot_id:
            continue
        if lot["status"] not in ("RECEIVED", "ACCEPTED"):
            continue
        if (lot["remaining_qty"] or 0) <= 0:
            continue
        set_fields(lot, status="QUARANTINED")
        quarantined_ids.append(lot["id"])
    if not quarantined_ids:
        return
    for unit in store.sort_created_asc(list(db.engine_units.values())):
        if unit["build_state"] != "STAGED":
            continue
        if unit["carburetor_lot_id"] in quarantined_ids or unit["ignition_lot_id"] in quarantined_ids:
            set_fields(unit, conformance_state="QUARANTINED")


# --------------------------------------------------------------- audit cascade

def audit_failure_cascade(family):
    """PRD 3.8 levels 2 through 4b.  Level 1 is written by the caller."""
    failures = (family["cumulative_audit_failures"] or 0) + 1
    if failures >= calc.AUDIT_FAILURE_SUSPEND_COUNT:
        suspended = True
        set_fields(family, cumulative_audit_failures=failures, status="SUSPENDED")
    else:
        suspended = False
        set_fields(
            family,
            cumulative_audit_failures=failures,
            status="AUDIT_HOLD",
            audit_hold_at=store.now_clock(),
        )

    # Level 2b — platforms and models.
    recompute_postures(family)
    affected_models = []
    for platform in family_platforms(family["id"]):
        for model in models_of_platform(platform["id"]):
            affected_models.append(model)
            if model["status"] == "RELEASED":
                set_fields(model, status="SUSPENDED")

    # Levels 3 and 4b — build orders held, their standing channel position torn up.
    reason = "FAMILY_SUSPENDED" if suspended else "FAMILY_AUDIT_HOLD"
    newly_held = []
    for model in affected_models:
        for order in orders_of_model(model["id"]):
            if order["status"] in ("PLANNED", "RELEASED", "IN_PRODUCTION"):
                set_fields(
                    order,
                    status_before_hold=order["status"],
                    status="HELD",
                    held_reason=reason,
                    allocated_dealer_units=0,
                    allocated_mass_retail_units=0,
                    unallocated_units=order["built_quantity"],
                    allocation_status="UNALLOCATED",
                    allocation_run_at=None,
                )
                newly_held.append(order)
            elif suspended and order["status"] == "HELD":
                set_fields(order, held_reason=reason)

    # Level 4 — engines of the newly held orders.
    for order in newly_held:
        for unit in units_of_order(order["id"]):
            if unit["build_state"] in ("STAGED", "ASSEMBLED", "HOT_TESTED"):
                set_fields(unit, conformance_state="QUARANTINED")


def certification_compensation(family):
    """PRD 3.8 — the deliberately partial compensating half."""
    for order in family_orders(family["id"]):
        if order["status"] != "HELD":
            continue
        restored = order.get("status_before_hold")
        if restored is None:
            continue
        set_fields(
            order,
            status=restored,
            held_reason=None,
            status_before_hold=None,
        )
        for unit in units_of_order(order["id"]):
            if unit["conformance_state"] == "QUARANTINED":
                set_fields(unit, conformance_state="PENDING")


# ------------------------------------------------------------- service parts

def requests_of_part(part_id):
    rows = [
        r for r in db.parts_requests.values()
        if r["service_part_id"] == part_id or r.get("shipped_from_part_id") == part_id
    ]
    return store.sort_created_asc(rows)


def part_metrics(part):
    """The four availability counters, attributed as PRD 3.9 describes."""
    filled = 0
    substituted = 0
    backordered = 0
    for req in db.parts_requests.values():
        if req["status"] == "FILLED" and req.get("shipped_from_part_id") == part["id"]:
            filled += 1
        elif req["status"] == "SUBSTITUTED" and req.get("shipped_from_part_id") == part["id"]:
            substituted += 1
        elif req["status"] == "BACKORDERED" and req["service_part_id"] == part["id"]:
            backordered += 1
    return {
        "filled_request_count": filled,
        "substituted_request_count": substituted,
        "backordered_request_count": backordered,
        "fill_rate_pct": calc.fill_rate(filled, substituted, backordered),
    }


def recompute_part_metrics(part, **extra):
    """Write the counters and any co-occurring change in a single row mutation."""
    changes = part_metrics(part)
    changes.update(extra)
    set_fields(part, **changes)


def lead_time_for(part, channel):
    if channel == "DEALER":
        return part["dealer_lead_time_days"]
    return part["mass_retail_lead_time_days"]


def promised_date(days):
    from datetime import timedelta
    return (store.clock_date() + timedelta(days=days)).isoformat()
