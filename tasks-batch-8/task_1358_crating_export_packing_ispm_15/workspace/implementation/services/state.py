"""Lookups, derived fields, derived-status refreshers, cascades, serializers.

Derived fields (PRD §2.11) are computed at read time where the PRD defines
them as pure functions of other records: Customer.open_exposure_cents,
WoodBatch.available_board_feet / stamps_available, Container.payload_used_kg,
PackingJob.total_board_feet / total_chargeable_weight_kg /
estimated_labor_hours / readiness_posture. Stored statuses move via the
state machines (incl. automatic transitions applied at event time).
"""
from decimal import Decimal

from db import STORE, iso_ms, logical_now, touch
from services import calc

SEALED_SET = {"SEALED", "LOADED", "SHIPPED", "DELIVERED"}
LOADED_SET = {"LOADED", "SHIPPED", "DELIVERED"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get(table, rid):
    rec = STORE[table].get(rid)
    return rec


def job_items(job_id):
    return [r for r in STORE["items"].values() if r["packing_job_id"] == job_id]


def item_designs(item_id):
    return [r for r in STORE["designs"].values() if r["item_id"] == item_id]


def current_design(item_id):
    """The item's current design: latest-created non-SUPERSEDED design."""
    ds = [d for d in item_designs(item_id) if d["status"] != "SUPERSEDED"]
    return ds[-1] if ds else None  # dicts preserve insertion (= creation) order


def item_crates(item_id):
    return [r for r in STORE["crates"].values() if r["item_id"] == item_id]


def live_crate_for_item(item_id):
    for c in item_crates(item_id):
        if c["status"] != "VOIDED":
            return c
    return None


def job_crates(job_id, include_voided=False):
    return [r for r in STORE["crates"].values()
            if r["packing_job_id"] == job_id and (include_voided or r["status"] != "VOIDED")]


def job_bookings(job_id):
    return [r for r in STORE["bookings"].values() if r["packing_job_id"] == job_id]


def job_permits(job_id):
    return [r for r in STORE["permits"].values() if r["packing_job_id"] == job_id]


def job_claims(job_id):
    return [r for r in STORE["claims"].values() if r["packing_job_id"] == job_id]


def item_declarations(item_id):
    return [r for r in STORE["declarations"].values() if r["item_id"] == item_id]


def item_dg_classes(item_id):
    """dg_class set over the item's APPROVED declarations."""
    return {d["dg_class"] for d in item_declarations(item_id) if d["status"] == "APPROVED"}


def has_approved_declaration(item_id):
    return any(d["status"] == "APPROVED" for d in item_declarations(item_id))


# ---------------------------------------------------------------------------
# Customer derived
# ---------------------------------------------------------------------------

def customer_open_exposure(customer_id):
    total = 0
    for j in STORE["jobs"].values():
        if j["customer_id"] == customer_id and j["status"] in (
                "DESIGN", "PACKING", "READY_TO_LOAD", "LOADED", "SHIPPED", "DELIVERED"):
            total += j["quoted_price_cents"]
    return total


# ---------------------------------------------------------------------------
# WoodBatch derived + lazy lifecycle
# ---------------------------------------------------------------------------

def batch_available(b):
    return (b["received_board_feet"] - b["reserved_board_feet"]
            - b["consumed_board_feet"] - b["scrapped_board_feet"])


def batch_stamps_available(b):
    return b["stamps_acquired"] - b["stamps_applied"] - b["stamps_voided"]


def batch_eval_expiry(b):
    """Lazy EXPIRED flip (PRD §2.5): only from ACTIVE/SUSPENDED, terminal."""
    if b["status"] in ("ACTIVE", "SUSPENDED") and b["expires_at"] < logical_now():
        b["status"] = "EXPIRED"
        touch(b)


def refresh_batch(b):
    """Auto DEPLETED <-> ACTIVE derivation (state machine §1.2 WoodBatch)."""
    batch_eval_expiry(b)
    if b["status"] == "EXPIRED":
        return
    avail = batch_available(b)
    if b["status"] == "ACTIVE" and avail == 0 and (b["reserved_board_feet"] + b["consumed_board_feet"]) > 0:
        b["status"] = "DEPLETED"
        touch(b)
    elif b["status"] == "DEPLETED" and avail > 0:
        b["status"] = "ACTIVE"
        touch(b)


# ---------------------------------------------------------------------------
# Container derived
# ---------------------------------------------------------------------------

def container_payload_used(container_id):
    total = Decimal(0)
    for c in STORE["crates"].values():
        if c["container_id"] == container_id and c["status"] == "LOADED":
            total += Decimal(str(c["gross_weight_kg"]))
    return float(total)


def container_loaded_crates(container_id):
    return [c for c in STORE["crates"].values()
            if c["container_id"] == container_id and c["status"] == "LOADED"]


# ---------------------------------------------------------------------------
# PackingJob derived + automatic status transitions
# ---------------------------------------------------------------------------

def job_total_board_feet(job_id):
    total = 0
    for it in job_items(job_id):
        d = current_design(it["id"])
        if d:
            total += d["board_feet_required"]
    return total


def job_total_chargeable_weight(job_id):
    return float(sum(Decimal(str(it["chargeable_weight_kg"])) for it in job_items(job_id)))


def job_total_volume(job_id):
    return float(sum(Decimal(str(it["volume_m3"])) for it in job_items(job_id)))


def job_estimated_labor_hours(job):
    return calc.estimated_labor_hours(job["mode"], job_total_volume(job["id"]))


def job_readiness_posture(job_id):
    crates = job_crates(job_id)
    if not crates:
        return "BLOCKED"
    if any(c["compliance_hold"] for c in crates):
        return "BLOCKED"
    if all(c["status"] in SEALED_SET for c in crates):
        return "READY"
    return "BLOCKED"


def refresh_job_status(job):
    """Automatic compound transitions (PRD §3.4): PACKING <-> READY_TO_LOAD
    and READY_TO_LOAD <-> LOADED, driven by child crate states."""
    crates = job_crates(job["id"])
    if not crates:
        return
    sealed_all = all(c["status"] in SEALED_SET for c in crates)
    loaded_all = all(c["status"] in LOADED_SET for c in crates)
    if job["status"] == "PACKING" and sealed_all:
        job["status"] = "READY_TO_LOAD"
        touch(job)
    elif job["status"] == "READY_TO_LOAD" and not sealed_all:
        job["status"] = "PACKING"
        touch(job)
    elif job["status"] == "READY_TO_LOAD" and loaded_all:
        job["status"] = "LOADED"
        touch(job)
    elif job["status"] == "LOADED" and not loaded_all:
        job["status"] = "READY_TO_LOAD"
        touch(job)


# ---------------------------------------------------------------------------
# Quote computation (job_quote calc; PROVISIONAL live / FINAL at close)
# ---------------------------------------------------------------------------

def compute_quote(job, variant="PROVISIONAL"):
    items = job_items(job["id"])
    bf = job_total_board_feet(job["id"])
    protection = 0
    for it in items:
        d = current_design(it["id"])
        if d:
            protection += (calc.INDICATOR_COST[d["shock_indicator_g"]]
                           + calc.BARRIER_COST[d["moisture_barrier_required"]])
    hazmat_count = sum(1 for it in items
                       if it["hazmat"] or it["battery_in_equipment"] != "NONE")
    est_hours = job_estimated_labor_hours(job)
    actual_labor = sum(b["total_cost_cents"] for b in job_bookings(job["id"])
                       if b["status"] == "COMPLETED")
    breakdown = calc.quote(bf, job["mode"], est_hours, actual_labor,
                           protection, hazmat_count, variant)
    breakdown["estimated_labor_hours"] = est_hours
    breakdown["total_chargeable_weight_kg"] = job_total_chargeable_weight(job["id"])
    breakdown["total_board_feet"] = bf
    return breakdown


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def batch_suspend_cascade(batch):
    affected_jobs = set()
    for c in STORE["crates"].values():
        d = get("designs", c["design_id"])
        if d and d["wood_batch_id"] == batch["id"] and c["status"] in (
                "PLANNED", "BUILT", "PACKED", "SEALED"):
            if not c["compliance_hold"]:
                c["compliance_hold"] = True
                touch(c)
            affected_jobs.add(c["packing_job_id"])
    return affected_jobs


def batch_reinstate_cascade(batch):
    affected_jobs = set()
    for c in STORE["crates"].values():
        d = get("designs", c["design_id"])
        if d and d["wood_batch_id"] == batch["id"] and c["compliance_hold"]:
            c["compliance_hold"] = False
            touch(c)
            affected_jobs.add(c["packing_job_id"])
    return affected_jobs


def job_cancel_cascade(job):
    """PRD §3.9: supersede designs (APPROVED/LOCKED release wood), void crates,
    cancel bookings and permits, re-derive batch statuses."""
    touched_batches = set()
    for it in job_items(job["id"]):
        for d in item_designs(it["id"]):
            if d["status"] in ("DRAFT", "IN_REVIEW", "REJECTED", "APPROVED", "LOCKED"):
                if d["status"] in ("APPROVED", "LOCKED") and d["wood_batch_id"]:
                    b = get("batches", d["wood_batch_id"])
                    if b:
                        b["reserved_board_feet"] -= d["board_feet_required"]
                        touch(b)
                        touched_batches.add(b["id"])
                d["status"] = "SUPERSEDED"
                touch(d)
    for c in job_crates(job["id"], include_voided=True):
        if c["status"] in ("PLANNED", "BUILT", "PACKED"):
            c["status"] = "VOIDED"
            touch(c)
    for bk in job_bookings(job["id"]):
        if bk["status"] in ("RESERVED", "CONFIRMED"):
            bk["status"] = "CANCELLED"
            touch(bk)
    for p in job_permits(job["id"]):
        if p["status"] in ("REQUESTED", "CONFIRMED"):
            p["status"] = "CANCELLED"
            touch(p)
    for bid in touched_batches:
        refresh_batch(get("batches", bid))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_customer(c):
    return {
        "id": c["id"], "name": c["name"], "site_code": c["site_code"],
        "credit_limit_cents": c["credit_limit_cents"],
        "open_exposure_cents": customer_open_exposure(c["id"]),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_job(j):
    return {
        "id": j["id"], "customer_id": j["customer_id"], "mode": j["mode"],
        "incoterm": j["incoterm"], "status": j["status"],
        "total_board_feet": job_total_board_feet(j["id"]),
        "total_chargeable_weight_kg": job_total_chargeable_weight(j["id"]),
        "estimated_labor_hours": job_estimated_labor_hours(j),
        "quoted_price_cents": j["quoted_price_cents"],
        "invoiced_total_cents": j["invoiced_total_cents"],
        "readiness_posture": job_readiness_posture(j["id"]),
        "delivered_at": iso_ms(j["delivered_at"]) if j["delivered_at"] else None,
        "created_at": j["created_at"], "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_item(it):
    return {
        "id": it["id"], "packing_job_id": it["packing_job_id"],
        "description": it["description"],
        "length_cm": it["length_cm"], "width_cm": it["width_cm"], "height_cm": it["height_cm"],
        "weight_kg": it["weight_kg"], "fragile_class": it["fragile_class"],
        "hazmat": it["hazmat"], "battery_in_equipment": it["battery_in_equipment"],
        "declared_value_cents": it["declared_value_cents"],
        "volume_m3": it["volume_m3"],
        "dimensional_weight_kg": it["dimensional_weight_kg"],
        "chargeable_weight_kg": it["chargeable_weight_kg"],
        "status": it["status"],
        "created_at": it["created_at"], "updated_at": it["updated_at"],
        "version": it["version"],
    }


def ser_design(d):
    return {
        "id": d["id"], "item_id": d["item_id"], "revision": d["revision"],
        "clearance_cm": d["clearance_cm"],
        "internal_l_cm": d["internal_l_cm"], "internal_w_cm": d["internal_w_cm"],
        "internal_h_cm": d["internal_h_cm"], "thickness_cm": d["thickness_cm"],
        "external_l_cm": d["external_l_cm"], "external_w_cm": d["external_w_cm"],
        "external_h_cm": d["external_h_cm"],
        "board_feet_required": d["board_feet_required"],
        "tare_weight_kg": d["tare_weight_kg"],
        "shock_indicator_g": d["shock_indicator_g"],
        "moisture_barrier_required": d["moisture_barrier_required"],
        "wood_batch_id": d["wood_batch_id"], "reject_reason": d["reject_reason"],
        "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_batch(b, eval_expiry=True):
    if eval_expiry:
        batch_eval_expiry(b)
    return {
        "id": b["id"], "ht_certificate_no": b["ht_certificate_no"],
        "treatment_type": b["treatment_type"],
        "expires_at": iso_ms(b["expires_at"]),
        "received_board_feet": b["received_board_feet"],
        "stamps_acquired": b["stamps_acquired"],
        "reserved_board_feet": b["reserved_board_feet"],
        "consumed_board_feet": b["consumed_board_feet"],
        "scrapped_board_feet": b["scrapped_board_feet"],
        "available_board_feet": batch_available(b),
        "stamps_applied": b["stamps_applied"], "stamps_voided": b["stamps_voided"],
        "stamps_available": batch_stamps_available(b),
        "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_crate(c):
    return {
        "id": c["id"], "item_id": c["item_id"], "packing_job_id": c["packing_job_id"],
        "design_id": c["design_id"], "container_id": c["container_id"],
        "stamp_serial": c["stamp_serial"], "stamp_status": c["stamp_status"],
        "tare_weight_kg": c["tare_weight_kg"], "gross_weight_kg": c["gross_weight_kg"],
        "external_volume_m3": c["external_volume_m3"],
        "freight_density_kg_m3": c["freight_density_kg_m3"],
        "freight_class": c["freight_class"],
        "compliance_hold": c["compliance_hold"], "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_declaration(d):
    return {
        "id": d["id"], "item_id": d["item_id"], "un_number": d["un_number"],
        "dg_class": d["dg_class"], "packing_group": d["packing_group"],
        "battery_type": d["battery_type"],
        "prepared_by_user_id": d["prepared_by_user_id"],
        "approved_by_user_id": d["approved_by_user_id"],
        "revision": d["revision"], "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_packing_list(p):
    return {
        "id": p["id"], "packing_job_id": p["packing_job_id"], "lines": p["lines"],
        "total_gross_weight_kg": p["total_gross_weight_kg"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_invoice(v):
    return {
        "id": v["id"], "packing_job_id": v["packing_job_id"], "lines": v["lines"],
        "invoice_total_cents": v["invoice_total_cents"],
        "duty_total_cents": v["duty_total_cents"], "status": v["status"],
        "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_crew(c):
    return {
        "id": c["id"], "name": c["name"], "capabilities": c["capabilities"],
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_booking(b):
    return {
        "id": b["id"], "packing_job_id": b["packing_job_id"], "crew_id": b["crew_id"],
        "mode": b["mode"],
        "start_at": iso_ms(b["start_at"]), "end_at": iso_ms(b["end_at"]),
        "hours": b["hours"], "rate_cents_per_hour": b["rate_cents_per_hour"],
        "travel_surcharge_cents": b["travel_surcharge_cents"],
        "total_cost_cents": b["total_cost_cents"], "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"], "packing_job_id": p["packing_job_id"], "site_code": p["site_code"],
        "window_start": iso_ms(p["window_start"]), "window_end": iso_ms(p["window_end"]),
        "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_container(c):
    return {
        "id": c["id"], "container_no": c["container_no"], "size": c["size"],
        "max_payload_kg": c["max_payload_kg"],
        "dunnage_weight_kg": c["dunnage_weight_kg"],
        "payload_used_kg": container_payload_used(c["id"]),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"], "packing_job_id": c["packing_job_id"], "crate_id": c["crate_id"],
        "claim_type": c["claim_type"], "description": c["description"],
        "amount_claimed_cents": c["amount_claimed_cents"],
        "amount_approved_cents": c["amount_approved_cents"],
        "amount_settled_cents": c["amount_settled_cents"],
        "amount_waived_cents": c["amount_waived_cents"],
        "appeal_used": c["appeal_used"],
        "filed_at": iso_ms(c["filed_at"]),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }
