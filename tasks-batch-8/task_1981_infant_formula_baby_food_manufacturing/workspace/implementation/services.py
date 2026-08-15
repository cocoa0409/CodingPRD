"""Shared domain logic: serializers, calculations, state cascades."""
from datetime import timedelta
from decimal import Decimal

from db import store, now
from util import fmt_dt, add_months, q2, q4, floor3, num, KG_Q
from errors import err, ERR_INVALID_STATE

# ------------------------------------------------------------------ vocabularies
PROFILE_CODES = ["INF-0-6M", "INF-6-12M", "TODDLER-12-36M", "CEREAL-6M", "PUREE-4M"]
INGREDIENT_CATEGORIES = ["DAIRY_BASE", "VEGETABLE_OIL", "VITAMIN_PREMIX", "MINERAL_PREMIX",
                         "PROBIOTIC", "CARBOHYDRATE", "NUCLEOTIDE", "OTHER"]
RISK_CLASSES = ["HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]
STORAGE_CONDITIONS = ["AMBIENT", "REFRIGERATED", "FROZEN", "CONTROLLED_HUMIDITY"]
AUDIT_TYPES = ["INITIAL", "SURVEILLANCE", "FOR_CAUSE", "RE_QUALIFICATION"]
PROCESS_TYPES = ["DRY_BLEND", "WET_PROCESS", "COMBINATION"]
VALIDATION_TYPES = ["DRY_BLEND_HOMOGENEITY", "WET_PROCESS_THERMAL", "PATHOGEN_ENVIRONMENTAL",
                    "COMBINATION_FULL"]
SUBMISSION_TYPES = ["NEW_PRODUCT_REGISTRATION", "LABEL_AMENDMENT", "NOTIFICATION", "RENEWAL"]
COMPLAINT_TYPES = ["QUALITY_DEFECT", "FOREIGN_MATTER", "PACKAGING", "ADVERSE_EVENT", "ILLNESS", "OTHER"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RECALL_REASONS = ["PATHOGEN_CONTAMINATION", "NUTRIENT_DEVIATION", "FOREIGN_MATTER", "MISLABELING",
                  "PACKAGING_DEFECT", "PRECAUTIONARY"]
RECALL_CLASSES = ["CLASS_I", "CLASS_II", "CLASS_III"]
WITHDRAWAL_LEVELS = ["CONSUMER", "RETAIL", "WHOLESALE", "DISTRIBUTION_CENTER"]
ALLOCATION_METHODS = ["PRO_RATA", "PRIORITY_TIER", "EQUAL_SPLIT", "WATERFALL"]
USER_ROLES = ["QA_MANAGER", "PRODUCTION_SUPERVISOR", "REGULATORY_AFFAIRS", "QUALITY_ANALYST",
              "SUPPLY_CHAIN_PLANNER", "COMPLAINT_HANDLER", "ADMIN"]


# ------------------------------------------------------------------ common helpers
def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now()


def stamp_new(rec):
    ts = now()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def refresh_validation(pv):
    """Lazy system auto-transition: PASSED -> EXPIRED once valid_until passes."""
    if pv["status"] == "PASSED" and pv.get("valid_until") is not None and now() > pv["valid_until"]:
        pv["status"] = "EXPIRED"
        touch(pv)


def get_or_404(collection, rid, label="Resource"):
    rec = collection.get(rid)
    if rec is None:
        from errors import err, ERR_NOT_FOUND
        raise err(ERR_NOT_FOUND, "%s '%s' does not exist" % (label, rid))
    return rec


# ------------------------------------------------------------------ serializers
def ser_user(u):
    return {
        "id": u["id"],
        "username": u["username"],
        "full_name": u["full_name"],
        "role": u["role"],
        "department": u["department"],
        "created_at": fmt_dt(u["created_at"]),
    }


def ser_profile(p):
    return {
        "id": p["id"],
        "profile_code": p["profile_code"],
        "nutrient_specs": p["nutrient_specs"],
        "regulation_ref": p["regulation_ref"],
        "effective_from": fmt_dt(p["effective_from"]),
        "effective_until": fmt_dt(p["effective_until"]),
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_supplier(s):
    next_due = None
    if s["qualification_status"] == "QUALIFIED" and s.get("last_audit_date") is not None:
        next_due = fmt_dt(s["last_audit_date"] + timedelta(days=s["audit_frequency_days"]))
    return {
        "id": s["id"],
        "supplier_code": s["supplier_code"],
        "legal_name": s["legal_name"],
        "ingredient_categories": s["ingredient_categories"],
        "qualification_status": s["qualification_status"],
        "last_audit_date": fmt_dt(s.get("last_audit_date")),
        "next_audit_due": next_due,
        "audit_frequency_days": s["audit_frequency_days"],
        "risk_rating": s["risk_rating"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "supplier_id": a["supplier_id"],
        "audit_type": a["audit_type"],
        "audit_date": fmt_dt(a["audit_date"]),
        "auditor_name": a["auditor_name"],
        "score": num(a["score"], 2),
        "findings": a.get("findings", []),
        "capa_deadline": fmt_dt(a.get("capa_deadline")),
        "result": a["result"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_ingredient(i):
    return {
        "id": i["id"],
        "ingredient_code": i["ingredient_code"],
        "ingredient_name": i["ingredient_name"],
        "category": i["category"],
        "pathogen_risk_class": i["pathogen_risk_class"],
        "storage_condition": i["storage_condition"],
        "allergen_flags": i.get("allergen_flags", []),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def ser_lot(l):
    return {
        "id": l["id"],
        "ingredient_id": l["ingredient_id"],
        "supplier_id": l["supplier_id"],
        "lot_number": l["lot_number"],
        "quantity_kg": num(l["quantity_kg"], 3),
        "remaining_kg": num(l["remaining_kg"], 3),
        "received_date": fmt_dt(l["received_date"]),
        "expiry_date": fmt_dt(l["expiry_date"]),
        "qc_status": l["qc_status"],
        "created_at": fmt_dt(l["created_at"]),
        "updated_at": fmt_dt(l["updated_at"]),
        "version": l["version"],
    }


def ser_formula(f):
    return {
        "id": f["id"],
        "formula_code": f["formula_code"],
        "product_name": f["product_name"],
        "nutrient_profile_id": f["nutrient_profile_id"],
        "ingredients": f["ingredients"],
        "process_type": f["process_type"],
        "status": f["status"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "formula_id": b["formula_id"],
        "batch_number": b["batch_number"],
        "batch_size_kg": num(b["batch_size_kg"], 3),
        "actual_yield_kg": num(b["actual_yield_kg"], 3) if b.get("actual_yield_kg") is not None else None,
        "status": b["status"],
        "production_date": fmt_dt(b["production_date"]),
        "expiry_date": fmt_dt(b.get("expiry_date")),
        "ingredient_consumptions": [
            {"ingredient_lot_id": c["ingredient_lot_id"],
             "consumed_kg": num(c["consumed_kg"], 3),
             "consumption_order": c["consumption_order"]}
            for c in b.get("ingredient_consumptions", [])
        ],
        "nutrient_results": b.get("nutrient_results"),
        "pathogen_results": b.get("pathogen_results"),
        "release_decision": b.get("release_decision"),
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def ser_validation(v):
    refresh_validation(v)
    return {
        "id": v["id"],
        "formula_id": v["formula_id"],
        "validation_type": v["validation_type"],
        "status": v["status"],
        "protocol_version": v["protocol_version"],
        "started_at": fmt_dt(v.get("started_at")),
        "completed_at": fmt_dt(v.get("completed_at")),
        "test_results": v.get("test_results"),
        "valid_until": fmt_dt(v.get("valid_until")),
        "validation_validity_days": v["validation_validity_days"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def ser_label(l):
    return {
        "id": l["id"],
        "formula_id": l["formula_id"],
        "submission_type": l["submission_type"],
        "label_text": l["label_text"],
        "claims": l.get("claims", []),
        "status": l["status"],
        "reviewer_id": l.get("reviewer_id"),
        "review_comments": l.get("review_comments", []),
        "submitted_at": fmt_dt(l.get("submitted_at")),
        "decided_at": fmt_dt(l.get("decided_at")),
        "created_at": fmt_dt(l["created_at"]),
        "updated_at": fmt_dt(l["updated_at"]),
        "version": l["version"],
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "complaint_ref": c["complaint_ref"],
        "complainant_name": c["complainant_name"],
        "complainant_contact": c["complainant_contact"],
        "product_formula_id": c["product_formula_id"],
        "batch_id": c.get("batch_id"),
        "complaint_type": c["complaint_type"],
        "severity": c["severity"],
        "description": c["description"],
        "status": c["status"],
        "is_adverse_event": c["is_adverse_event"],
        "escalated_at": fmt_dt(c.get("escalated_at")),
        "resolution": c.get("resolution"),
        "resolved_at": fmt_dt(c.get("resolved_at")),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_recall(r):
    return {
        "id": r["id"],
        "recall_ref": r["recall_ref"],
        "reason": r["reason"],
        "recall_class": r["recall_class"],
        "scope_description": r["scope_description"],
        "status": r["status"],
        "initiated_by": r["initiated_by"],
        "initiated_at": fmt_dt(r["initiated_at"]),
        "completed_at": fmt_dt(r.get("completed_at")),
        "effectiveness_checks": r.get("effectiveness_checks"),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def compute_recovery_pct(scope):
    shipped = scope["quantity_shipped_kg"]
    if shipped == 0:
        return Decimal("100.00")
    return q2((scope["quantity_recovered_kg"] / shipped) * Decimal(100))


def ser_scope(s):
    return {
        "id": s["id"],
        "recall_id": s["recall_id"],
        "batch_id": s["batch_id"],
        "withdrawal_level": s["withdrawal_level"],
        "status": s["status"],
        "quantity_shipped_kg": num(s["quantity_shipped_kg"], 3),
        "quantity_recovered_kg": num(s["quantity_recovered_kg"], 3),
        "recovery_pct": num(s["recovery_pct"], 2),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "plan_ref": p["plan_ref"],
        "formula_id": p["formula_id"],
        "total_available_kg": num(p["total_available_kg"], 3),
        "allocation_method": p["allocation_method"],
        "status": p["status"],
        "activated_at": fmt_dt(p.get("activated_at")),
        "fulfilled_at": fmt_dt(p.get("fulfilled_at")),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "plan_id": e["plan_id"],
        "customer_code": e["customer_code"],
        "customer_name": e["customer_name"],
        "requested_kg": num(e["requested_kg"], 3),
        "priority_tier": e.get("priority_tier"),
        "allocated_kg": num(e["allocated_kg"], 3),
        "fulfilled_kg": num(e["fulfilled_kg"], 3),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


# ------------------------------------------------------------------ calculations
def audit_result(score, findings):
    """audit_result_determination: CRITICAL finding -> FAIL; score < 50 -> FAIL;
    MAJOR finding or score < 75 -> CONDITIONAL_PASS; else PASS."""
    has_critical = any(f.get("severity") == "CRITICAL" for f in findings)
    has_major = any(f.get("severity") == "MAJOR" for f in findings)
    if has_critical:
        return "FAIL"
    if score < Decimal("50.00"):
        return "FAIL"
    if has_major or score < Decimal("75.00"):
        return "CONDITIONAL_PASS"
    return "PASS"


def compute_risk_rating(score, audit_date):
    """supplier_risk_rating: recency-decayed adjusted score -> LOW/MEDIUM/HIGH."""
    days_since = Decimal(str((now() - audit_date).total_seconds())) / Decimal(86400)
    recency = Decimal("1.0") - (days_since / Decimal(730))
    if recency < Decimal("0.5"):
        recency = Decimal("0.5")
    adjusted = q2(score * recency)
    if adjusted >= Decimal("80"):
        return "LOW"
    if adjusted >= Decimal("60"):
        return "MEDIUM"
    return "HIGH"


def evaluate_nutrient_results(profile, nutrient_results):
    """nutrient_compliance_check: sets pass flag on each result; INF-0-6M uses
    the borderline variant (min*1.02, max*0.98, bounds quantized to 4dp half-up)."""
    borderline = profile["profile_code"] == "INF-0-6M"
    specs = {s.get("nutrient_code"): s for s in profile["nutrient_specs"]}
    out = []
    for r in nutrient_results:
        code = r.get("nutrient_code")
        spec = specs.get(code)
        passed = False
        if spec is not None:
            measured = q4(Decimal(str(r.get("measured_per_100kcal"))))
            lo = Decimal(str(spec.get("min_per_100kcal")))
            hi = Decimal(str(spec.get("max_per_100kcal")))
            if borderline:
                lo = q4(lo * Decimal("1.02"))
                hi = q4(hi * Decimal("0.98"))
            passed = (measured >= lo) and (measured <= hi)
        entry = dict(r)
        entry["measured_per_100kcal"] = float(q4(Decimal(str(r.get("measured_per_100kcal")))))
        entry["pass"] = passed
        out.append(entry)
    return out


def batch_shelf_life_months(profile_code, process_type):
    base = {
        "INF-0-6M": 24,
        "INF-6-12M": 24,
        "TODDLER-12-36M": 18,
        "CEREAL-6M": 12,
        "PUREE-4M": 9,
    }.get(profile_code, 12)
    if process_type == "DRY_BLEND":
        base += 3
    return base


def run_allocation(plan, entries):
    """Populate allocated_kg on PENDING entries per the plan's method.
    All arithmetic in Decimal kg with 3dp floor (truncate) semantics."""
    available = plan["total_available_kg"]
    pending = [e for e in entries if e["status"] == "PENDING"]
    pending.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)))
    method = plan["allocation_method"]
    for e in entries:
        if e["status"] == "PENDING":
            e["allocated_kg"] = Decimal("0")
    if not pending:
        return
    if method == "PRO_RATA":
        _alloc_pro_rata(available, pending)
    elif method in ("PRIORITY_TIER", "WATERFALL"):
        _alloc_priority_tier(available, pending)
    elif method == "EQUAL_SPLIT":
        _alloc_equal_split(available, pending)


def _distribute_remainder(entries, remainder):
    """Walk entries in created_at ASC order adding 0.001 while remainder allows."""
    idx = 0
    guard = 0
    while remainder >= KG_Q and entries and guard < 1000000:
        entries[idx]["allocated_kg"] += KG_Q
        remainder -= KG_Q
        idx = (idx + 1) % len(entries)
        guard += 1
    return remainder


def _alloc_pro_rata(available, pending):
    total_requested = sum(e["requested_kg"] for e in pending)
    if total_requested <= available:
        for e in pending:
            e["allocated_kg"] = e["requested_kg"]
        return
    ratio = available / total_requested
    for e in pending:
        e["allocated_kg"] = floor3(e["requested_kg"] * ratio)
    remainder = available - sum(e["allocated_kg"] for e in pending)
    _distribute_remainder(pending, remainder)


def _alloc_priority_tier(available, pending):
    remaining = available
    for tier in range(1, 11):
        tier_entries = [e for e in pending if (e.get("priority_tier") or 10) == tier]
        if not tier_entries:
            continue
        tier_requested = sum(e["requested_kg"] for e in tier_entries)
        if remaining >= tier_requested:
            for e in tier_entries:
                e["allocated_kg"] = e["requested_kg"]
            remaining -= tier_requested
        else:
            if remaining > 0:
                ratio = remaining / tier_requested
                for e in tier_entries:
                    e["allocated_kg"] = floor3(e["requested_kg"] * ratio)
                tier_allocated = sum(e["allocated_kg"] for e in tier_entries)
                tier_remainder = remaining - tier_allocated
                _distribute_remainder(tier_entries, tier_remainder)
            remaining = Decimal("0")
            break


def _alloc_equal_split(available, pending):
    n = len(pending)
    base = floor3(available / Decimal(n))
    for e in pending:
        e["allocated_kg"] = min(base, e["requested_kg"])
    surplus = available - sum(e["allocated_kg"] for e in pending)
    uncapped = [e for e in pending if e["allocated_kg"] < e["requested_kg"]]
    guard = 0
    while surplus >= KG_Q and uncapped and guard < 1000000:
        per_entry = floor3(surplus / Decimal(len(uncapped)))
        if per_entry < KG_Q:
            uncapped[0]["allocated_kg"] += surplus
            surplus = Decimal("0")
        else:
            for e in uncapped:
                grant = min(per_entry, e["requested_kg"] - e["allocated_kg"])
                e["allocated_kg"] += grant
                surplus -= grant
            uncapped = [e for e in pending if e["allocated_kg"] < e["requested_kg"]]
        guard += 1


# ------------------------------------------------------------------ cascades
def cascade_supplier_suspended(supplier):
    for lot in store.lots.values():
        if lot["supplier_id"] == supplier["id"] and lot["qc_status"] == "QC_PASSED":
            lot["qc_status"] = "QUARANTINED"
            touch(lot)


def cascade_supplier_reinstated(supplier):
    for lot in store.lots.values():
        if lot["supplier_id"] == supplier["id"] and lot["qc_status"] == "QUARANTINED":
            lot["qc_status"] = "QC_PASSED"
            touch(lot)


def cascade_supplier_disqualified(supplier):
    for lot in store.lots.values():
        if lot["supplier_id"] == supplier["id"] and lot["qc_status"] != "QC_FAILED":
            lot["qc_status"] = "QC_FAILED"
            touch(lot)


def transition(rec, allowed_from, to, label="Resource"):
    if rec["status"] not in allowed_from:
        raise err(
            ERR_INVALID_STATE,
            "%s in status %s cannot perform this transition (requires: %s)"
            % (label, rec["status"], ", ".join(allowed_from)),
        )
    rec["status"] = to
    touch(rec)


def check_plan_fulfillment(plan):
    """System auto-transition: ACTIVE -> FULFILLED when every entry is
    FULFILLED or SHORTFALL."""
    if plan["status"] != "ACTIVE":
        return
    entries = [e for e in store.entries.values() if e["plan_id"] == plan["id"]]
    if entries and all(e["status"] in ("FULFILLED", "SHORTFALL") for e in entries):
        plan["status"] = "FULFILLED"
        plan["fulfilled_at"] = now()
        touch(plan)
