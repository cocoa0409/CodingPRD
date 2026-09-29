"""Cascade propagation (PRD §2.11) and the three logical-clock expiry sweeps (§2.5).

Cascades never run backwards and every touched row is a mutation: updated_at is
refreshed and version increments by exactly 1, however many hops away it is."""
import calc
import clock
from store import db, touch


def offers_of_supplier(supplier_id, statuses=None):
    plan_ids = {p["id"] for p in db["rate_plans"].values() if p["supplier_id"] == supplier_id}
    rows = [o for o in db["offers"].values() if o["rate_plan_id"] in plan_ids]
    if statuses is not None:
        rows = [o for o in rows if o["status"] in statuses]
    return sorted(rows, key=lambda r: r["_seq"])


def offers_of_plan(rate_plan_id, statuses=None):
    rows = [o for o in db["offers"].values() if o["rate_plan_id"] == rate_plan_id]
    if statuses is not None:
        rows = [o for o in rows if o["status"] in statuses]
    return sorted(rows, key=lambda r: r["_seq"])


def supplier_of_plan(rate_plan_id):
    plan = db["rate_plans"].get(rate_plan_id)
    if plan is None:
        return None
    return db["suppliers"].get(plan["supplier_id"])


def supplier_of_offer(offer):
    return supplier_of_plan(offer["rate_plan_id"])


def clear_package_pricing(package):
    package["components_subtotal_cents"] = None
    package["discount_pct"] = None
    package["discount_cents"] = None
    package["package_total_cents"] = None
    package["priced_at"] = None
    for component in db["components"].values():
        if component["package_id"] == package["id"]:
            component["display_total_snapshot_cents"] = None
            component["discount_alloc_cents"] = None
            component["allocated_cents"] = None


def components_of_package(package_id):
    rows = [c for c in db["components"].values() if c["package_id"] == package_id]
    return sorted(rows, key=lambda r: r["_seq"])


def packages_holding_offer(offer_id):
    package_ids = []
    for component in sorted(db["components"].values(), key=lambda r: r["_seq"]):
        if component["offer_id"] == offer_id and component["package_id"] not in package_ids:
            package_ids.append(component["package_id"])
    return [db["packages"][pid] for pid in package_ids if pid in db["packages"]]


def runs_holding_offer(offer_id):
    run_ids = []
    for entry in sorted(db["ranking_entries"].values(), key=lambda r: r["_seq"]):
        if entry["offer_id"] == offer_id and entry["ranking_run_id"] not in run_ids:
            run_ids.append(entry["ranking_run_id"])
    return [db["ranking_runs"][rid] for rid in run_ids if rid in db["ranking_runs"]]


def suppress_offer(offer, reason):
    """Offer LIVE -> SUPPRESSED plus cascade hops 3 and 4."""
    offer["status"] = "SUPPRESSED"
    offer["suppression_reason"] = reason
    touch(offer)
    # hop 3: published artifacts that quoted this offer are withdrawn
    for run in runs_holding_offer(offer["id"]):
        if run["status"] == "PUBLISHED":
            run["status"] = "WITHDRAWN"
            run["withdrawal_reason"] = "COMPONENT_SUPPRESSED"
            touch(run)
    for package in packages_holding_offer(offer["id"]):
        if package["status"] == "PUBLISHED":
            package["status"] = "WITHDRAWN"
            package["withdrawal_reason"] = "COMPONENT_SUPPRESSED"
            package["reveal_supplier_names"] = False
            touch(package)
        elif package["status"] == "PRICED":
            # hop 4: a priced package holding a suppressed offer goes back to DRAFT
            package["status"] = "DRAFT"
            clear_package_pricing(package)
            touch(package)


def suspend_supplier(supplier, reason):
    """Cascade hop 1 + hop 2. Only ACTIVE suppliers can be suspended."""
    if supplier["visibility_status"] != "ACTIVE":
        return
    supplier["visibility_status"] = "SUSPENDED"
    supplier["certification_level"] = "NONE"
    supplier["content_score"] = 0
    supplier["connectivity_score"] = 0
    supplier["suspension_reason"] = reason
    supplier["_backing_cert_id"] = None
    touch(supplier)
    for offer in offers_of_supplier(supplier["id"], ("LIVE",)):
        suppress_offer(offer, "SUPPLIER_SUSPENDED")


def hold_rate_plan(plan, case):
    """RatePlan ACTIVE -> PARITY_HOLD plus hops 3 and 4."""
    if plan["status"] != "ACTIVE":
        return
    plan["status"] = "PARITY_HOLD"
    plan["parity_hold_case_id"] = case["id"]
    touch(plan)
    for offer in offers_of_plan(plan["id"], ("LIVE",)):
        suppress_offer(offer, "PARITY_HOLD")


def offboard_supplier(supplier):
    """Archives every rate plan and closes out every PENDING/LIVE/SUPPRESSED offer."""
    supplier["visibility_status"] = "OFFBOARDED"
    touch(supplier)
    plans = sorted((p for p in db["rate_plans"].values() if p["supplier_id"] == supplier["id"]),
                   key=lambda r: r["_seq"])
    for plan in plans:
        for offer in offers_of_plan(plan["id"], ("PENDING", "LIVE", "SUPPRESSED")):
            offer["status"] = "CLOSED"
            touch(offer)
        if plan["status"] != "ARCHIVED":
            plan["status"] = "ARCHIVED"
            touch(plan)


def recompute_current_model(supplier):
    agreement = calc.active_agreement_for_date(supplier["id"], clock.today().isoformat())
    supplier["current_model"] = agreement["model"] if agreement else "NONE"


def run_sweeps(new_instant):
    """The three sweeps, in the pinned order. Only ever called when the clock moves forward."""
    new_day = new_instant.date().isoformat()
    # 1. certification expiry -> supplier suspension -> offer suppression
    for cert in sorted(db["certifications"].values(), key=lambda r: r["_seq"]):
        if cert["status"] not in ("CERTIFIED", "PROVISIONAL"):
            continue
        expires_at = cert.get("expires_at")
        if not expires_at:
            continue
        expiry = clock.parse_instant(expires_at)
        if expiry is None or expiry > new_instant:
            continue
        supplier = db["suppliers"].get(cert["supplier_id"])
        backing = supplier is not None and supplier.get("_backing_cert_id") == cert["id"]
        cert["status"] = "EXPIRED"
        touch(cert)
        if backing:
            suspend_supplier(supplier, "CERTIFICATION_EXPIRED")
    # 2. commission override expiry
    for override in sorted(db["overrides"].values(), key=lambda r: r["_seq"]):
        if override["status"] == "ACTIVE" and override["effective_to"] < new_day:
            override["status"] = "EXPIRED"
            touch(override)
    # 3. placement agreement expiry
    for placement in sorted(db["placements"].values(), key=lambda r: r["_seq"]):
        if placement["status"] == "ACTIVE" and placement["window_end"] <= new_day:
            placement["status"] = "EXPIRED"
            touch(placement)
