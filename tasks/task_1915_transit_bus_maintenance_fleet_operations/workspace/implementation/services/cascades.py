"""Cross-entity cascades: WO close/cancel, bus retire, epoch sweep."""
from datetime import timedelta

from store import db, meta, mark_dirty, clock_date, fmt_date, init_common
from services import domain as dom


# ---------------------------------------------------------------------------
# Work order close cascade (QA_CERTIFY -> CLOSED)
# ---------------------------------------------------------------------------
def close_work_order(wo):
    bus = db["buses"][wo["bus_id"]]
    today = fmt_date(clock_date())
    wo["status"] = "CLOSED"
    wo["closed_date"] = today
    dom.recompute_wo_costs(wo)
    mark_dirty("work_orders", wo["id"])

    # Bus lifecycle / PM nesting / cost accumulation
    if wo["wo_type"] == "OVERHAUL" and bus["service_status"] == "OVERHAUL_HOLD":
        bus["service_status"] = "ACTIVE"
        bus["last_overhaul_miles"] = bus["odometer_miles"]
        mark_dirty("buses", bus["id"])
    if wo["wo_type"] in ("PM_A", "PM_B", "PM_C"):
        levels = {"PM_A": ("a",), "PM_B": ("a", "b"), "PM_C": ("a", "b", "c")}
        for lv in levels[wo["wo_type"]]:
            bus[f"last_pm_{lv}_miles"] = bus["odometer_miles"]
            bus[f"last_pm_{lv}_date"] = today
        dom.recompute_pm_due(bus)
        mark_dirty("buses", bus["id"])
    bus["total_maintenance_cost_cents"] = (
        bus.get("total_maintenance_cost_cents", 0) + wo.get("total_cost_cents", 0))
    mark_dirty("buses", bus["id"])

    # Linked defect auto-resolves
    if wo.get("defect_report_id"):
        d = db["defects"].get(wo["defect_report_id"])
        if d is not None and d.get("linked_work_order_id") == wo["id"] \
                and d["status"] == "WO_LINKED":
            d["status"] = "RESOLVED"
            d["resolution"] = "SHOP_REPAIRED"
            mark_dirty("defects", d["id"])

    dom.recompute_bus_availability(bus)

    # Campaign progress / auto-complete
    if wo.get("campaign_id"):
        camp = db["campaigns"].get(wo["campaign_id"])
        if camp is not None and camp["status"] == "ACTIVE":
            count, pct = dom.campaign_progress(camp)
            if pct >= 100.0:
                camp["status"] = "COMPLETED"
                mark_dirty("campaigns", camp["id"])

    # Warranty auto-draft cascade
    if wo["wo_type"] in ("CORRECTIVE", "EMISSIONS", "CAMPAIGN"):
        if dom.base_warranty_ok(bus, wo):
            claim = init_common({
                "work_order_id": wo["id"],
                "bus_id": bus["id"],
                "claim_type": "BASE_OEM",
                "proration_basis": None,
                "manual_claimed_cents": None,
                "status": "DRAFT",
                "eligible_cents": None,
                "claimed_cents": None,
                "approved_cents": None,
                "received_cents": None,
                "appeal_count": 0,
                "oem_reference": None,
                "auto_created": True,
                "submitted_by_user_id": None,
                "recovered_by_user_id": None,
            })
            db["claims"][claim["id"]] = claim

    dom.recompute_posture()


# ---------------------------------------------------------------------------
# Work order cancel cascade
# ---------------------------------------------------------------------------
def cancel_work_order(wo, reason=None):
    wo["status"] = "CANCELLED"
    if reason is not None:
        wo["cancel_reason"] = reason
    mark_dirty("work_orders", wo["id"])

    # Auto-release still-RESERVED lines
    for line in dom.wo_lines(wo["id"]):
        if line["issue_status"] == "RESERVED":
            line["issue_status"] = "RELEASED"
            mark_dirty("part_lines", line["id"])
            part = db["parts"].get(line["part_id"])
            if part is not None:
                part["quantity_reserved"] -= line["qty"]
                dom.recompute_stock_status(part)
                mark_dirty("parts", part["id"])

    # Linked defect reverts to SHOP_QUEUED
    if wo.get("defect_report_id"):
        d = db["defects"].get(wo["defect_report_id"])
        if d is not None and d.get("linked_work_order_id") == wo["id"] \
                and d["status"] == "WO_LINKED":
            d["status"] = "SHOP_QUEUED"
            d["linked_work_order_id"] = None
            mark_dirty("defects", d["id"])

    bus = db["buses"].get(wo["bus_id"])
    if bus is not None:
        if wo["wo_type"] == "OVERHAUL" and bus["service_status"] == "OVERHAUL_HOLD":
            bus["service_status"] = "ACTIVE"
            mark_dirty("buses", bus["id"])
        dom.recompute_bus_availability(bus)
    dom.recompute_posture()


# ---------------------------------------------------------------------------
# Bus retire cascade
# ---------------------------------------------------------------------------
def retire_bus(bus, reason=None):
    from errors import err
    for wo in db["work_orders"].values():
        if wo["bus_id"] == bus["id"] and wo["status"] not in dom.WO_TERMINAL:
            raise err("ERR_OPEN_WORK_ORDERS_EXIST",
                      "Bus has non-terminal work orders")
    bus["service_status"] = "RETIRED"
    if reason is not None:
        bus["retirement_reason"] = reason
    # Auto-cancel DRAFT/BLOCKED work orders
    for wo in list(db["work_orders"].values()):
        if wo["bus_id"] == bus["id"] and wo["status"] in ("DRAFT", "BLOCKED"):
            cancel_work_order(wo, reason="BUS_RETIRED")
    bus["availability_status"] = "OUT_OF_SERVICE"
    bus["hold_reasons"] = []
    bus["emissions_hold"] = False
    mark_dirty("buses", bus["id"])
    dom.recompute_posture()


# ---------------------------------------------------------------------------
# Epoch sweep
# ---------------------------------------------------------------------------
def run_epoch():
    today = clock_date()
    today_s = fmt_date(today)
    counters = {
        "defects_reopened": 0,
        "cores_aged": 0,
        "certifications_expired": 0,
        "buses_grounded": 0,
    }

    # 1. Deferral expiry: DEFERRED -> OPEN once defer_until_date has passed
    for d in db["defects"].values():
        if d["status"] == "DEFERRED" and d.get("defer_until_date") \
                and d["defer_until_date"] < today_s:
            d["status"] = "OPEN"
            d["disposition"] = None
            mark_dirty("defects", d["id"])
            counters["defects_reopened"] += 1

    # 2. Core aging
    for line in db["part_lines"].values():
        due = line.get("core_due_date")
        if line["core_status"] in ("CORE_PENDING", "CORE_LATE") and due:
            from datetime import datetime as _dt
            due_d = _dt.strptime(due, "%Y-%m-%d").date()
            if (due_d + timedelta(days=dom.CORE_LATE_GRACE_DAYS)) < today:
                line["core_status"] = "CORE_REJECTED"
                line["core_due_date"] = None
                mark_dirty("part_lines", line["id"])
                counters["cores_aged"] += 1
            elif due_d < today:
                if line["core_status"] != "CORE_LATE":
                    line["core_status"] = "CORE_LATE"
                    mark_dirty("part_lines", line["id"])
                    counters["cores_aged"] += 1

    # 3. Certification expiry recompute
    for cert in db["certifications"].values():
        from datetime import datetime as _dt
        exp = _dt.strptime(cert["expiry_date"], "%Y-%m-%d").date()
        old = cert["status"]
        if exp < today:
            new = "EXPIRED"
        elif (exp - today).days <= 30:
            new = "EXPIRING_SOON"
        else:
            new = "VALID"
        # Sweep only moves forward in the expiry lifecycle; EXPIRED stays EXPIRED.
        if old == "EXPIRED":
            new = "EXPIRED"
        elif old == "EXPIRING_SOON" and new == "VALID":
            new = "EXPIRING_SOON"
        if new != old:
            cert["status"] = new
            mark_dirty("certifications", cert["id"])
            if new == "EXPIRED":
                counters["certifications_expired"] += 1

    # 4. Emissions certificate expiry grounding
    for bus in db["buses"].values():
        if bus["service_status"] == "RETIRED":
            continue
        expiry = bus.get("emissions_cert_expiry_date")
        if expiry and expiry < today_s and not bus.get("emissions_hold"):
            bus["emissions_hold"] = True
            mark_dirty("buses", bus["id"])
            counters["buses_grounded"] += 1

    # 5. Shift locking: PUBLISHED shifts whose date has passed -> LOCKED
    for shift in db["shifts"].values():
        if shift["status"] == "PUBLISHED" and shift["shift_date"] < today_s:
            shift["status"] = "LOCKED"
            mark_dirty("shifts", shift["id"])

    # 6. PM due-status recompute (epoch is a trigger)
    policy = dom.active_policy()
    for bus in db["buses"].values():
        if bus["service_status"] != "RETIRED":
            dom.recompute_pm_due(bus, policy)

    # 7. Availability + posture recompute
    for bus in db["buses"].values():
        dom.recompute_bus_availability(bus)
    posture = dom.recompute_posture()

    meta["epoch_index"] += 1
    return {
        "epoch_index": meta["epoch_index"],
        "posture": posture["posture"],
        "defects_reopened": counters["defects_reopened"],
        "cores_aged": counters["cores_aged"],
        "certifications_expired": counters["certifications_expired"],
        "buses_grounded": counters["buses_grounded"],
    }
