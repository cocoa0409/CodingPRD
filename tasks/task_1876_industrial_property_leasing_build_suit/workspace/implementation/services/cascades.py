"""Cross-entity cascades per PRD §2.9 and the state machines of §1.2.

The consistency model is immediate: every side effect lands inside the same
request, and each cascaded resource gets its own version bump + updated_at
refresh (PRD §2.4).
"""
from db import store, new_entity, touch
from services import calc
from timeutil import parse_iso


def recompute_site_available(site):
    site["available_sf"] = site["total_sf"] - site["reserved_sf"]


# ---------------------------------------------------------------------------
# TenantRequirement ACTIVE -> WITHDRAWN (PRD §3.1)
# ---------------------------------------------------------------------------
def withdraw_requirement_cascade(req):
    req["status"] = "WITHDRAWN"
    touch(req)
    for t in store.tours.values():
        if t["requirement_id"] == req["id"] and t["status"] in ("REQUESTED", "CONFIRMED"):
            t["status"] = "CANCELLED"
            touch(t)
    for l in store.lois.values():
        if l["requirement_id"] == req["id"] and l["status"] in ("DRAFT", "SUBMITTED", "COUNTERED"):
            l["status"] = "WITHDRAWN"
            touch(l)


# ---------------------------------------------------------------------------
# LOI accept (PRD §3.3): LOI -> ACCEPTED; Site LISTED -> RESERVED (link 1);
# the site transition rejects competing SUBMITTED/COUNTERED LOIs (link 2).
# ---------------------------------------------------------------------------
def accept_loi_cascade(loi):
    site = store.sites[loi["site_id"]]
    loi["status"] = "ACCEPTED"
    touch(loi)
    site_reserve(site, loi["leased_sf"])
    for other in store.lois.values():
        if (other["id"] != loi["id"] and other["site_id"] == site["id"]
                and other["status"] in ("SUBMITTED", "COUNTERED")):
            other["status"] = "REJECTED"
            touch(other)


def site_reserve(site, sf):
    site["status"] = "RESERVED"
    site["reserved_sf"] = site["reserved_sf"] + sf
    recompute_site_available(site)
    touch(site)


# ---------------------------------------------------------------------------
# LOI ACCEPTED -> WITHDRAWN (PRD §3.3): compensating release of the site and
# of every GRANTED expansion option riding on the LOI.
# ---------------------------------------------------------------------------
def withdraw_accepted_loi_cascade(loi):
    site = store.sites[loi["site_id"]]
    site["status"] = "LISTED"
    site["reserved_sf"] = site["reserved_sf"] - loi["leased_sf"]
    recompute_site_available(site)
    touch(site)
    for o in store.options.values():
        if o["loi_id"] == loi["id"] and o["status"] == "GRANTED":
            o["status"] = "RELEASED"
            touch(o)


# ---------------------------------------------------------------------------
# LOI ACCEPTED -> EXECUTED (PRD §3.5): site commit (+ its tour-cancellation
# link), requirement satisfaction, BTS plan auto-create, two commission
# invoices auto-created in fixed order (TENANT_REP first, LANDLORD_REP second).
# ---------------------------------------------------------------------------
def execute_loi_cascade(loi):
    site = store.sites[loi["site_id"]]
    req = store.requirements[loi["requirement_id"]]
    loi["status"] = "EXECUTED"
    touch(loi)
    # Site RESERVED -> COMMITTED; that commitment cancels other requirements'
    # open tours at the site (Site machine link 2).
    site["status"] = "COMMITTED"
    touch(site)
    for t in store.tours.values():
        if (t["site_id"] == site["id"]
                and t["requirement_id"] != loi["requirement_id"]
                and t["status"] in ("REQUESTED", "CONFIRMED")):
            t["status"] = "CANCELLED"
            touch(t)
    # TenantRequirement ACTIVE -> SATISFIED (system transition).
    if req["status"] == "ACTIVE":
        req["status"] = "SATISFIED"
        touch(req)
    # BuildToSuitPlan auto-created 1:1, SCHEMATIC.
    plan = new_entity({
        "loi_id": loi["id"],
        "hard_cost_total": None,
        "soft_cost_total": None,
        "contingency_pct": None,
        "pricing_method": None,
        "provisional_base_rate_psf": None,
        "commission_cost_estimate": None,
        "total_project_cost": None,
        "converted_base_rate_psf": None,
        "yield_on_cost": None,
        "status": "SCHEMATIC",
    })
    store.plans[plan["id"]] = plan
    # Two CommissionInvoices, fixed order TENANT_REP then LANDLORD_REP,
    # computed once at the LOI's final terms per broker_commission.
    basis = calc.commission_basis_amount(loi)
    tenant_total, landlord_total = calc.split_commission(basis)
    for side, total in (("TENANT_REP", tenant_total), ("LANDLORD_REP", landlord_total)):
        i1, i2 = calc.split_installments(total)
        inv = new_entity({
            "loi_id": loi["id"],
            "broker_side": side,
            "commission_basis": loi["commission_basis"],
            "commission_basis_amount": basis,
            "total_commission": total,
            "installment_1_amount": i1,
            "installment_2_amount": i2,
            "installment_1_paid": False,
            "installment_2_paid": False,
            "installment_2_due": False,
            "dispute_reason": None,
            "status": "ACCRUED",
        })
        store.invoices[inv["id"]] = inv
    return plan


# ---------------------------------------------------------------------------
# BuildToSuitPlan APPROVED -> DELIVERED (PRD §3.5): writes rent commencement
# and delay abatement onto the LOI (link 2), moves Site COMMITTED -> LEASED,
# and that site transition flips installment_2_due on the LOI's invoices
# (link 3).
# ---------------------------------------------------------------------------
def deliver_plan_cascade(plan):
    plan["status"] = "DELIVERED"
    touch(plan)
    loi = store.lois[plan["loi_id"]]
    sc = None
    for m in store.milestones.values():
        if m["plan_id"] == plan["id"] and m["milestone_type"] == "SUBSTANTIAL_COMPLETION":
            sc = m
            break
    if sc is not None:
        loi["rent_commencement_date"] = sc["actual_date"]
        planned_dt = parse_iso(sc["planned_date"])
        actual_dt = parse_iso(sc["actual_date"])
        loi["abatement_days"] = calc.delivery_delay_abatement(planned_dt, actual_dt)
    touch(loi)
    site = store.sites[loi["site_id"]]
    site["status"] = "LEASED"
    touch(site)
    for inv in store.invoices.values():
        if inv["loi_id"] == loi["id"] and not inv["installment_2_due"]:
            inv["installment_2_due"] = True
            touch(inv)


def plan_milestones(plan_id):
    return [m for m in store.milestones.values() if m["plan_id"] == plan_id]


def all_milestones_complete(plan_id):
    """Delivery requires at least one milestone and all COMPLETE."""
    ms = plan_milestones(plan_id)
    return len(ms) >= 1 and all(m["status"] == "COMPLETE" for m in ms)
