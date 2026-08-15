"""Domain constants, derived-field computation, serializers, system sweeps."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import STORE, now
from helpers import bump, fmt_dt

# ---------------------------------------------------------------------------
# Enum domains
# ---------------------------------------------------------------------------

TOOL_TYPES = {"PROGRESSIVE_DIE", "TRANSFER_DIE", "INJECTION_MOLD", "BLOW_MOLD", "COMPRESSION_MOLD"}
DIE_CLASSES = {"CLASS_101", "CLASS_102", "CLASS_103", "CLASS_104", "CLASS_105"}
QUOTE_KINDS = {"BUDGETARY", "FIRM"}
WARRANTY_TERMS = {"LINEAR_PRORATION", "DECLINING_BALANCE"}
PRESSES = {"PRESS_200T", "PRESS_500T", "PRESS_800T"}
MACHINES = {"CNC_1", "CNC_2", "EDM_1", "GRIND_1"}
JOB_STATES = {"BOOKED", "IN_BUILD", "TRYOUT_PHASE", "BUYOFF_PASSED",
              "READY_TO_SHIP", "SHIPPED", "CLOSED", "ON_HOLD"}
REQUESTED_BY = {"SHOP", "CUSTOMER"}

# ---------------------------------------------------------------------------
# Pricing / calculation constants (PRD §3.3, §3.5, §3.7, §3.9)
# ---------------------------------------------------------------------------

CLASS_BASE_CENTS = {"CLASS_101": 12000000, "CLASS_102": 9000000, "CLASS_103": 6500000,
                    "CLASS_104": 4000000, "CLASS_105": 1800000}
CAVITY_RATE_CENTS = {"CLASS_101": 800000, "CLASS_102": 650000, "CLASS_103": 500000,
                     "CLASS_104": 350000, "CLASS_105": 200000}
COMPLEXITY_RATE_CENTS = 150000
STANDARD_LEAD_WEEKS = {"CLASS_101": 20, "CLASS_102": 16, "CLASS_103": 12,
                       "CLASS_104": 10, "CLASS_105": 6}
MIN_LEAD_WEEKS = {"CLASS_101": 12, "CLASS_102": 10, "CLASS_103": 8,
                  "CLASS_104": 6, "CLASS_105": 3}
# PRD §3.3 step 2: four hundredths per compression week, capped at 0.40.
SURCHARGE_PER_WEEK = Decimal("0.04")
SURCHARGE_CAP = Decimal("0.40")
EXPEDITED_MULTIPLIER = Decimal("1.10")
CONTINGENCY = {"BUDGETARY": Decimal("0.15"), "FIRM": Decimal("0.05")}
VALIDITY_DAYS = {"BUDGETARY": 14, "FIRM": 30}

BILLING_PCT = [20, 25, 25, 15, 10, 5]
MILESTONE_CODES = ["DESIGN_COMPLETE", "MATERIAL_STAGED", "MACHINING_COMPLETE",
                   "T1_TRYOUT_DONE", "BUYOFF_SIGNED", "DELIVERY_ACCEPTED"]

CLASS_LABOR_RATE_CENTS = {"CLASS_101": 14500, "CLASS_102": 13500, "CLASS_103": 12500,
                          "CLASS_104": 11500, "CLASS_105": 10500}
MATERIAL_MARKUP = Decimal("1.15")
PENALTY_FREE_EXTENSION_WEEKS = 2
PENALTY_PCT_PER_WEEK = Decimal("0.01")

WARRANTY_SHOT_LIMIT = {"CLASS_101": 1000000, "CLASS_102": 500000, "CLASS_103": 250000,
                       "CLASS_104": 100000, "CLASS_105": 10000}
WARRANTY_DAYS = 730

NET_TERMS_DAYS = 30
GRACE_DAYS = 10

COOLDOWN_BUFFER_HOURS = 4
WEEKLY_CAPACITY_HOURS = Decimal("45.0")


def rhu(value):
    """Round-half-up a Decimal-compatible value to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups and derived aggregates
# ---------------------------------------------------------------------------

def milestones_of_job(job_id):
    return sorted((m for m in STORE.milestones.values() if m["build_job_id"] == job_id),
                  key=lambda m: m["seq"])


def invoices_of_job(job_id):
    return [i for i in STORE.invoices.values() if i["build_job_id"] == job_id]


def invoices_of_milestone(milestone_id):
    return [i for i in STORE.invoices.values() if i["build_milestone_id"] == milestone_id]


def payments_of_job(job_id):
    return [p for p in STORE.payments.values() if p["build_job_id"] == job_id]


def tool_by_job(job_id):
    for t in STORE.tools.values():
        if t["build_job_id"] == job_id:
            return t
    return None


def ra_by_eco(eco_id):
    for r in STORE.ras.values():
        if r["engineering_change_id"] == eco_id:
            return r
    return None


def job_billed_cents(job_id):
    return sum(i["amount_cents"] for i in invoices_of_job(job_id) if i["status"] != "VOID")


def job_paid_cents(job_id):
    return sum(a["applied_cents"] for p in payments_of_job(job_id) for a in p["allocations"])


def job_credit_balance_cents(job_id):
    return sum(max(0, m["paid_cents"] - m["planned_amount_cents"])
               for m in milestones_of_job(job_id))


def job_net_paid_cents(job_id):
    return job_paid_cents(job_id) - job_credit_balance_cents(job_id)


def job_outstanding_cents(job):
    return job["contract_value_cents"] - job_net_paid_cents(job["id"])


def job_open_eco_count(job_id):
    return sum(1 for e in STORE.ecos.values()
               if e["build_job_id"] == job_id
               and e["status"] in ("SUBMITTED", "IMPACT_ASSESSED", "APPROVED"))


def ship_threshold_cents(job):
    return (job["contract_value_cents"] * 15) // 100


def customer_open_invoices(customer_id):
    job_ids = {j["id"] for j in STORE.jobs.values() if j["customer_id"] == customer_id}
    return [i for i in STORE.invoices.values()
            if i["build_job_id"] in job_ids and i["status"] in ("ISSUED", "PARTIALLY_PAID")]


def customer_outstanding_cents(customer_id):
    return sum(i["amount_cents"] - i["paid_cents"] for i in customer_open_invoices(customer_id))


# ---------------------------------------------------------------------------
# System actions
# ---------------------------------------------------------------------------

def sweep_customer(cust):
    """Credit-aging sweep for one customer (PRD §2.8). Suspension bumps the
    customer's version; restoration does not."""
    now_dt = now()
    overdue = any(now_dt > i["due_date"] + timedelta(days=GRACE_DAYS)
                  for i in customer_open_invoices(cust["id"]))
    if cust["status"] == "ACTIVE" and overdue:
        cust["status"] = "SUSPENDED"
        bump(cust)
    elif cust["status"] == "SUSPENDED" and not overdue:
        cust["status"] = "ACTIVE"
        cust["updated_at"] = now_dt


def sweep_all_customers():
    for cust in STORE.customers.values():
        sweep_customer(cust)


def eval_ownership(job):
    """Retention-lien release: net_paid >= contract AND tool IN_PRODUCTION.
    Transfers ownership one-way and closes a SHIPPED job (PRD §3.8)."""
    tool = tool_by_job(job["id"])
    if tool is None:
        return
    if tool["ownership_status"] != "SHOP_RETAINED":
        return
    if tool["physical_status"] != "IN_PRODUCTION":
        return
    if job_net_paid_cents(job["id"]) >= job["contract_value_cents"]:
        tool["ownership_status"] = "TRANSFERRED"
        bump(tool)
        if job["status"] == "SHIPPED":
            job["status"] = "CLOSED"
            bump(job)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def price_quote(design, quote_kind, requested_lead_weeks, expedited):
    """PRD §3.3 — exact-decimal arithmetic; round-half-up at steps 3 and 5 only."""
    die_class = design["die_class"]
    base = (CLASS_BASE_CENTS[die_class]
            + design["cavity_count"] * CAVITY_RATE_CENTS[die_class]
            + design["design_complexity_score"] * COMPLEXITY_RATE_CENTS)
    compression = max(0, STANDARD_LEAD_WEEKS[die_class] - requested_lead_weeks)
    surcharge = min(SURCHARGE_PER_WEEK * compression, SURCHARGE_CAP)
    subtotal = Decimal(base) * (Decimal("1") + surcharge)
    if expedited:
        subtotal = subtotal * EXPEDITED_MULTIPLIER
    subtotal_cents = rhu(subtotal)
    contingency = CONTINGENCY[quote_kind]
    total_cents = rhu(Decimal(subtotal_cents) * (Decimal("1") + contingency))
    return {
        "base_price_cents": base,
        "surcharge_pct": surcharge,
        "subtotal_cents": subtotal_cents,
        "contingency_pct": contingency,
        "total_price_cents": total_cents,
    }


def milestone_plan_amounts(contract_value_cents):
    """PRD §3.5 pinned rounding order at job creation: seq 1..5 rounded per line,
    seq 6 absorbs the remainder so the six sum exactly to the contract value."""
    planned = [rhu(Decimal(contract_value_cents) * pct / 100) for pct in BILLING_PCT[:5]]
    planned.append(contract_value_cents - sum(planned))
    return planned


def eco_impact_reprice(job, rework_hours, scrapped_material_cost_cents, lead_extension_weeks):
    """PRD §3.7 pinned evaluation order."""
    labor = rhu(Decimal(str(rework_hours)) * CLASS_LABOR_RATE_CENTS[job["die_class"]])
    material = rhu(Decimal(scrapped_material_cost_cents) * MATERIAL_MARKUP)
    impact = labor + material
    interim = job["contract_value_cents"] + impact
    if lead_extension_weeks <= PENALTY_FREE_EXTENSION_WEEKS:
        penalty = 0
    else:
        penalty = rhu(Decimal(lead_extension_weeks - PENALTY_FREE_EXTENSION_WEEKS)
                      * PENALTY_PCT_PER_WEEK * interim)
    return {
        "labor_cost_cents": labor,
        "material_cost_cents": material,
        "impact_cost_cents": impact,
        "schedule_penalty_cents": penalty,
        "total_charge_cents": impact + penalty,
    }


def warranty_credit(tool, claim):
    """PRD §3.9 — proration credit per warranty_terms variant."""
    base = min(claim["estimated_repair_cost_cents"], tool["contract_snapshot_cents"])
    shots = claim["claimed_at_shot_count"]
    limit = tool["warranty_shot_limit"]
    remaining = max(0, limit - shots)
    if tool["warranty_terms"] == "LINEAR_PRORATION":
        credit = Decimal(base) * Decimal(remaining) / Decimal(limit)
    else:  # DECLINING_BALANCE: square of the remaining-life fraction
        frac = Decimal(remaining) / Decimal(limit)
        credit = Decimal(base) * frac * frac
    return rhu(credit)


def iso_week_start(dt):
    d = dt.astimezone(timezone.utc).date()
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def machine_duration_hours(start, end):
    seconds = Decimal(str((end - start).total_seconds()))
    hours = seconds / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Serializers (explicit field lists; internal keys are never exposed)
# ---------------------------------------------------------------------------

def ser_customer(c):
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "contact_email": c["contact_email"],
        "credit_limit_cents": c["credit_limit_cents"],
        "outstanding_balance_cents": customer_outstanding_cents(c["id"]),
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_design(d):
    return {
        "id": d["id"],
        "customer_id": d["customer_id"],
        "part_number": d["part_number"],
        "tool_type": d["tool_type"],
        "die_class": d["die_class"],
        "cavity_count": d["cavity_count"],
        "design_complexity_score": d["design_complexity_score"],
        "revision_number": d["revision_number"],
        "supersedes_design_id": d["supersedes_design_id"],
        "quoted_count": d["quoted_count"],
        "status": d["status"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def ser_quote(q):
    return {
        "id": q["id"],
        "customer_id": q["customer_id"],
        "tool_design_id": q["tool_design_id"],
        "quote_kind": q["quote_kind"],
        "requested_lead_weeks": q["requested_lead_weeks"],
        "expedited": q["expedited"],
        "warranty_terms": q["warranty_terms"],
        "base_price_cents": q["base_price_cents"],
        "surcharge_pct": float(q["surcharge_pct"]),
        "subtotal_cents": q["subtotal_cents"],
        "contingency_pct": float(q["contingency_pct"]),
        "total_price_cents": q["total_price_cents"],
        "issued_at": fmt_dt(q["issued_at"]),
        "valid_until": fmt_dt(q["valid_until"]),
        "status": q["status"],
        "created_at": fmt_dt(q["created_at"]),
        "updated_at": fmt_dt(q["updated_at"]),
        "version": q["version"],
    }


def ser_job(j):
    job_id = j["id"]
    paid = job_paid_cents(job_id)
    credit = job_credit_balance_cents(job_id)
    net_paid = paid - credit
    return {
        "id": job_id,
        "quote_id": j["quote_id"],
        "customer_id": j["customer_id"],
        "tool_design_id": j["tool_design_id"],
        "die_class": j["die_class"],
        "contract_value_cents": j["contract_value_cents"],
        "billed_cents": job_billed_cents(job_id),
        "paid_cents": paid,
        "credit_balance_cents": credit,
        "net_paid_cents": net_paid,
        "outstanding_cents": j["contract_value_cents"] - net_paid,
        "open_eco_count": job_open_eco_count(job_id),
        "status": j["status"],
        "hold_return_state": j["hold_return_state"],
        "created_at": fmt_dt(j["created_at"]),
        "updated_at": fmt_dt(j["updated_at"]),
        "version": j["version"],
    }


def ser_milestone(m):
    return {
        "id": m["id"],
        "build_job_id": m["build_job_id"],
        "seq": m["seq"],
        "code": m["code"],
        "billing_pct": m["billing_pct"],
        "planned_amount_cents": m["planned_amount_cents"],
        "paid_cents": m["paid_cents"],
        "completed_at": fmt_dt(m["completed_at"]),
        "status": m["status"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "build_job_id": inv["build_job_id"],
        "build_milestone_id": inv["build_milestone_id"],
        "invoice_number": inv["invoice_number"],
        "amount_cents": inv["amount_cents"],
        "paid_cents": inv["paid_cents"],
        "balance_due_cents": inv["amount_cents"] - inv["paid_cents"],
        "issued_by_user_id": inv["issued_by_user_id"],
        "due_date": fmt_dt(inv["due_date"]),
        "void_reason": inv["void_reason"],
        "status": inv["status"],
        "created_at": fmt_dt(inv["created_at"]),
        "updated_at": fmt_dt(inv["updated_at"]),
        "version": inv["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "build_job_id": p["build_job_id"],
        "amount_cents": p["amount_cents"],
        "allocations": p["allocations"],
        "recorded_by_user_id": p["recorded_by_user_id"],
        "created_at": fmt_dt(p["created_at"]),
    }


def ser_sample(s):
    return {
        "id": s["id"],
        "build_job_id": s["build_job_id"],
        "press_reservation_id": s["press_reservation_id"],
        "round_number": s["round_number"],
        "sample_qty": s["sample_qty"],
        "shots_used": s["shots_used"],
        "measured_report_ref": s["measured_report_ref"],
        "defect_codes": s["defect_codes"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_eco(e):
    return {
        "id": e["id"],
        "build_job_id": e["build_job_id"],
        "requested_by": e["requested_by"],
        "description": e["description"],
        "affects_from_milestone_seq": e["affects_from_milestone_seq"],
        "rework_hours": e["rework_hours"],
        "scrapped_material_cost_cents": e["scrapped_material_cost_cents"],
        "lead_extension_weeks": e["lead_extension_weeks"],
        "labor_cost_cents": e["labor_cost_cents"],
        "material_cost_cents": e["material_cost_cents"],
        "impact_cost_cents": e["impact_cost_cents"],
        "schedule_penalty_cents": e["schedule_penalty_cents"],
        "total_charge_cents": e["total_charge_cents"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_ra(r):
    return {
        "id": r["id"],
        "engineering_change_id": r["engineering_change_id"],
        "build_job_id": r["build_job_id"],
        "authorized_cost_cents": r["authorized_cost_cents"],
        "consumed_cost_cents": r["consumed_cost_cents"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_tool(t):
    return {
        "id": t["id"],
        "build_job_id": t["build_job_id"],
        "customer_id": t["customer_id"],
        "serial_number": t["serial_number"],
        "die_class": t["die_class"],
        "warranty_terms": t["warranty_terms"],
        "warranty_shot_limit": t["warranty_shot_limit"],
        "warranty_expires_at": fmt_dt(t["warranty_expires_at"]),
        "tryout_shots": t["tryout_shots"],
        "reported_shots": t["reported_shots"],
        "lifetime_shots": t["tryout_shots"] + t["reported_shots"],
        "contract_snapshot_cents": t["contract_snapshot_cents"],
        "carrier": t["carrier"],
        "tracking_number": t["tracking_number"],
        "shipped_at": fmt_dt(t["shipped_at"]),
        "delivered_at": fmt_dt(t["delivered_at"]),
        "physical_status": t["physical_status"],
        "ownership_status": t["ownership_status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_shot_report(r):
    return {
        "id": r["id"],
        "tool_asset_id": r["tool_asset_id"],
        "report_period_end": fmt_dt(r["report_period_end"]),
        "shots_in_period": r["shots_in_period"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "tool_asset_id": c["tool_asset_id"],
        "defect_description": c["defect_description"],
        "estimated_repair_cost_cents": c["estimated_repair_cost_cents"],
        "claimed_at_shot_count": c["claimed_at_shot_count"],
        "approved_credit_cents": c["approved_credit_cents"],
        "denial_reason": c["denial_reason"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_insert(s):
    return {
        "id": s["id"],
        "tool_asset_id": s["tool_asset_id"],
        "insert_code": s["insert_code"],
        "unit_cost_cents": s["unit_cost_cents"],
        "on_hand": s["on_hand"],
        "reorder_point": s["reorder_point"],
        "reorder_needed": s["on_hand"] <= s["reorder_point"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_press_res(r):
    return {
        "id": r["id"],
        "build_job_id": r["build_job_id"],
        "press_id": r["press_id"],
        "start_time": fmt_dt(r["start_time"]),
        "end_time": fmt_dt(r["end_time"]),
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_machine_res(r):
    return {
        "id": r["id"],
        "build_job_id": r["build_job_id"],
        "machine_id": r["machine_id"],
        "start_time": fmt_dt(r["start_time"]),
        "end_time": fmt_dt(r["end_time"]),
        "duration_hours": float(r["duration_hours"]),
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }
