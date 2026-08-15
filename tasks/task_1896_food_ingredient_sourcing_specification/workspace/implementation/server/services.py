"""Business logic: calculations, cascades, sweeps (PRD §3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from .store import STORE, new_record, set_dt_system, touch

D4 = Decimal("0.0001")
D2 = Decimal("0.01")

ALLERGEN_TAGS = {
    "MILK", "EGG", "FISH", "SHELLFISH", "TREE_NUT", "PEANUT",
    "WHEAT", "SOY", "SESAME", "NONE",
}
CRITICALITIES = {"CRITICAL", "MAJOR", "MINOR"}
RISK_TIERS = {"TIER_A", "TIER_B", "TIER_C"}
REASON_CODES = {
    "SUPPLY_SHORTAGE", "COST_REDUCTION", "QUALITY_ESCAPE", "DUAL_SOURCE_BREACH",
}
DECLARATION_TYPES = {"ALLERGEN", "COUNTRY_OF_ORIGIN"}
DISPOSITIONS = {"ACCEPT_AS_IS", "DOWNGRADED_TO_MINOR", "REJECT_LOT"}

WEIGHTS = {"CRITICAL": 3, "MAJOR": 2, "MINOR": 1}

TIER1_BASE = Decimal("4.50")
TIER2_BASE = Decimal("4.20")
TIER3_BASE = Decimal("3.95")
TIER1_CAP = 10000
TIER2_CAP = 50000

REBATE_HIGH_RATE = Decimal("0.02")
REBATE_LOW_RATE = Decimal("0.015")
REBATE_HIGH_THRESHOLD = Decimal("250000")

RISK_W_COA = Decimal("0.35")
RISK_W_AUDIT = Decimal("0.30")
RISK_W_OVERDUE = Decimal("0.20")
RISK_W_DECLARATION = Decimal("0.15")
RISK_SUSPEND_THRESHOLD = Decimal("70")

AUTO_APPROVE_MAX_ABS_DELTA = Decimal("0.5000")

CADENCE_MONTHS = {"TIER_A": 12, "TIER_B": 6, "TIER_C": 3}
ESCALATION_DAYS = 7
AUDIT_WINDOW_DAYS = 14


def dec(value):
    """Exact Decimal from a JSON number."""
    return Decimal(str(value))


def q4(value):
    return value.quantize(D4, rounding=ROUND_HALF_UP)


def q2(value):
    return value.quantize(D2, rounding=ROUND_HALF_UP)


def to_json_number(d):
    return float(d)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def sources_of_ingredient(ingredient_id):
    return [s for s in STORE.sources.values() if s["ingredient_id"] == ingredient_id]


def sources_of_supplier(supplier_id):
    return [s for s in STORE.sources.values() if s["supplier_id"] == supplier_id]


def specs_of_ingredient(ingredient_id):
    return [s for s in STORE.specs.values() if s["ingredient_id"] == ingredient_id]


def params_of_spec(spec_id):
    rows = [p for p in STORE.parameters.values() if p["spec_id"] == spec_id]
    return sorted(rows, key=lambda r: (r["_created_dt"], r["_seq"]))


def findings_of_coa(coa_id):
    rows = [f for f in STORE.findings.values() if f["coa_id"] == coa_id]
    return sorted(rows, key=lambda r: (r["_created_dt"], r["_seq"]))


def contracts_of_source(source_id):
    return [c for c in STORE.contracts.values() if c["approved_source_id"] == source_id]


def coas_of_source(source_id):
    return [c for c in STORE.coas.values() if c["approved_source_id"] == source_id]


def declarations_of_source(source_id):
    return [d for d in STORE.declarations.values() if d["approved_source_id"] == source_id]


def capas_of_supplier(supplier_id):
    audit_ids = [a["id"] for a in STORE.audits.values() if a["supplier_id"] == supplier_id]
    return [c for c in STORE.capas.values() if c["audit_id"] in audit_ids]


def current_declaration(source_id, declaration_type):
    for d in declarations_of_source(source_id):
        if d["declaration_type"] == declaration_type and d["status"] == "CURRENT":
            return d
    return None


def declaration_in_window(decl):
    return decl["valid_from__dt"] <= STORE.clock < decl["valid_until__dt"]


# ---------------------------------------------------------------------------
# Dual-source breach (calculation dual_source_breach)
# ---------------------------------------------------------------------------

def recompute_dual_source(ingredient):
    active = [
        s
        for s in sources_of_ingredient(ingredient["id"])
        if s["status"] == "ACTIVE" and s["pinned_spec_id"] == ingredient["active_spec_id"]
    ]
    breach = bool(ingredient["requires_dual_source"]) and len(active) < 2
    if ingredient["current_dual_source_breach"] != breach:
        ingredient["current_dual_source_breach"] = breach
        touch(ingredient)


# ---------------------------------------------------------------------------
# Supplier suspension cascade / composite risk
# ---------------------------------------------------------------------------

def suspend_supplier(supplier):
    """QUALIFIED -> SUSPENDED with the full cascade (manual or automatic)."""
    supplier["status"] = "SUSPENDED"
    touch(supplier)
    for src in sources_of_supplier(supplier["id"]):
        if src["status"] == "ACTIVE":
            src["status"] = "SUSPENDED"
            src["suspension_reason"] = "SUPPLIER_SUSPENDED"
            touch(src)
            ing = STORE.ingredients.get(src["ingredient_id"])
            if ing is not None:
                recompute_dual_source(ing)


def overdue_capa_count(supplier_id):
    clock = STORE.clock
    count = 0
    for capa in capas_of_supplier(supplier_id):
        if capa["status"] in ("OPEN", "SUBMITTED", "REJECTED") and capa["due_date__dt"] < clock:
            count += 1
    return count


def recompute_overdue_count(supplier):
    count = overdue_capa_count(supplier["id"])
    if supplier["open_overdue_capa_count"] != count:
        supplier["open_overdue_capa_count"] = count
        touch(supplier)
    return count


def recompute_risk(supplier):
    """supplier_composite_risk_score; auto-suspends QUALIFIED suppliers at >= 70."""
    clock = STORE.clock
    count = overdue_capa_count(supplier["id"])
    if supplier["open_overdue_capa_count"] != count:
        supplier["open_overdue_capa_count"] = count
        touch(supplier)

    # CoA component: trailing 365-day window over the supplier's sources.
    window_start = clock - timedelta(days=365)
    rejected = 0
    decided = 0
    for src in sources_of_supplier(supplier["id"]):
        for coa in coas_of_source(src["id"]):
            received = coa["received_at__dt"]
            if window_start <= received <= clock:
                if coa["status"] == "REJECTED":
                    rejected += 1
                    decided += 1
                elif coa["status"] in ("ACCEPTED", "CONDITIONALLY_ACCEPTED"):
                    decided += 1
    coa_component = dec(rejected) / dec(max(1, decided)) * Decimal(100)

    # Audit component: 100 - latest CLOSED audit score (0 when none).
    closed = [a for a in STORE.audits.values()
              if a["supplier_id"] == supplier["id"] and a["status"] == "CLOSED"]
    if closed:
        latest = max(closed, key=lambda a: (a.get("_closed_dt") or a["_created_dt"], a["_seq"]))
        audit_component = dec(100 - latest["audit_score"])
    else:
        audit_component = Decimal(0)

    overdue_component = min(Decimal(100), dec(count) * Decimal(25))

    declaration_component = Decimal(0)
    for src in sources_of_supplier(supplier["id"]):
        if src["status"] != "ACTIVE":
            continue
        allergen = current_declaration(src["id"], "ALLERGEN")
        coo = current_declaration(src["id"], "COUNTRY_OF_ORIGIN")
        if (
            allergen is None
            or coo is None
            or not declaration_in_window(allergen)
            or not declaration_in_window(coo)
        ):
            declaration_component = Decimal(100)
            break

    score = q2(
        RISK_W_COA * coa_component
        + RISK_W_AUDIT * audit_component
        + RISK_W_OVERDUE * overdue_component
        + RISK_W_DECLARATION * declaration_component
    )
    score = max(Decimal(0), min(Decimal(100), score))
    if supplier["composite_risk_score"] != to_json_number(score):
        supplier["composite_risk_score"] = to_json_number(score)
        touch(supplier)
    if score >= RISK_SUSPEND_THRESHOLD and supplier["status"] == "QUALIFIED":
        suspend_supplier(supplier)


# ---------------------------------------------------------------------------
# CoA deviation score (calculation coa_deviation_score)
# ---------------------------------------------------------------------------

def compute_excess_ratio(observed, bound, min_value, max_value):
    spread = dec(max_value) - dec(min_value)
    if spread == 0:
        return Decimal(0)
    return q4(abs(dec(observed) - dec(bound)) / spread)


def deviation_score(findings, variant):
    total = Decimal(0)
    for f in findings:
        weight = WEIGHTS[f["criticality_at_finding"]]
        if variant == "final" and f["disposition"] == "DOWNGRADED_TO_MINOR":
            weight = WEIGHTS["MINOR"]
        total += dec(f["excess_ratio"]) * weight
    return q2(total * Decimal(100))


# ---------------------------------------------------------------------------
# Contract tier price (calculation contract_tier_price)
# ---------------------------------------------------------------------------

def select_index_current():
    """Latest INGREDIENT-SPOT observation with observed_at <= clock.

    Ordered by observed_at DESC; tie-break earliest created_at ASC.
    """
    best = None
    for obs in STORE.observations.values():
        if obs["index_name"] != "INGREDIENT-SPOT":
            continue
        if obs["observed_at__dt"] > STORE.clock:
            continue
        if best is None:
            best = obs
            continue
        if obs["observed_at__dt"] > best["observed_at__dt"]:
            best = obs
        elif obs["observed_at__dt"] == best["observed_at__dt"]:
            if (obs["_created_dt"], obs["_seq"]) < (best["_created_dt"], best["_seq"]):
                best = obs
    return best


def tier_unit_price(contract, lot_kg):
    obs = select_index_current()
    index_current = dec(obs["index_value"]) if obs is not None else dec(contract["index_base_value"])
    index_base = dec(contract["index_base_value"])
    pass_through = dec(contract["index_pass_through_pct"])
    factor = Decimal(1) + pass_through * (index_current - index_base) / index_base

    prior_kg = contract["cumulative_shipped_kg"]
    remaining = lot_kg
    cursor = prior_kg
    line_value = Decimal(0)
    tiers = (
        (0, TIER1_CAP, TIER1_BASE),
        (TIER1_CAP, TIER2_CAP, TIER2_BASE),
        (TIER2_CAP, None, TIER3_BASE),
    )
    while remaining > 0:
        for lower, upper, base in tiers:
            if cursor >= lower and (upper is None or cursor < upper):
                capacity = remaining if upper is None else min(remaining, upper - cursor)
                adjusted_base = q4(base * factor)
                line_value += dec(capacity) * adjusted_base
                cursor += capacity
                remaining -= capacity
                break
    return q4(line_value / dec(lot_kg))


# ---------------------------------------------------------------------------
# Annual rebate (calculation annual_rebate)
# ---------------------------------------------------------------------------

def compute_rebate(contract):
    qualifying = []
    for coa in STORE.coas.values():
        if coa["contract_id"] != contract["id"]:
            continue
        if coa["status"] not in ("ACCEPTED", "CONDITIONALLY_ACCEPTED"):
            continue
        received = coa["received_at__dt"]
        if contract["window_start__dt"] <= received < contract["window_end__dt"]:
            qualifying.append(coa)
    qualifying.sort(key=lambda r: (r["_created_dt"], r["_seq"]))

    accepted_value_total = Decimal(0)
    for coa in qualifying:
        accepted_value_total += dec(coa["shipped_qty_kg"]) * dec(coa["unit_price_applied"])
    rate = REBATE_HIGH_RATE if accepted_value_total >= REBATE_HIGH_THRESHOLD else REBATE_LOW_RATE

    total_rebate = Decimal(0)
    for coa in qualifying:
        line = q2(dec(coa["shipped_qty_kg"]) * dec(coa["unit_price_applied"]) * rate)
        total_rebate += line

    return {
        "contract_id": contract["id"],
        "rebate_rate": float(rate),
        "accepted_value_total": float(accepted_value_total),
        "total_rebate": float(total_rebate),
        "line_count": len(qualifying),
    }


# ---------------------------------------------------------------------------
# Formula impact assessment (calculation formula_impact_delta)
# ---------------------------------------------------------------------------

def run_assessment(request_rec):
    from_source = STORE.sources[request_rec["from_approved_source_id"]]
    to_source = STORE.sources[request_rec["to_approved_source_id"]]
    ingredient = STORE.ingredients[request_rec["ingredient_id"]]
    from_params = params_of_spec(from_source["pinned_spec_id"])
    to_params = params_of_spec(to_source["pinned_spec_id"])
    from_by_name = {p["parameter_name"]: p for p in from_params}
    to_by_name = {p["parameter_name"]: p for p in to_params}

    # Union of parameter names: from-spec creation order, then to-spec extras.
    ordered_names = [p["parameter_name"] for p in from_params]
    ordered_names += [p["parameter_name"] for p in to_params if p["parameter_name"] not in from_by_name]

    sensitivities = {}
    for item in request_rec["formula_unit_cost_sensitivities"]:
        if isinstance(item, dict) and "parameter_name" in item:
            sensitivities[item["parameter_name"]] = item.get("cost_per_unit_delta")

    parameter_deltas = []
    total = Decimal(0)
    for name in ordered_names:
        from_target = from_by_name[name]["target_value"] if name in from_by_name else 0
        to_target = to_by_name[name]["target_value"] if name in to_by_name else 0
        delta = q4(dec(to_target) - dec(from_target))
        if name in sensitivities and sensitivities[name] is not None:
            cost_delta = q4(delta * dec(sensitivities[name]))
        else:
            cost_delta = Decimal(0)
        total += cost_delta
        parameter_deltas.append(
            {
                "parameter_name": name,
                "from_target": from_target,
                "to_target": to_target,
                "delta": float(delta),
                "cost_delta": float(cost_delta),
            }
        )
    total_delta = q4(total)

    to_allergen = current_declaration(to_source["id"], "ALLERGEN")
    to_tags = []
    if to_allergen is not None and isinstance(to_allergen["payload"], dict):
        tags = to_allergen["payload"].get("allergen_tags")
        if isinstance(tags, list):
            to_tags = tags
    profile = set(ingredient["allergen_profile"] or [])
    allergen_delta_tags = sorted({t for t in to_tags if t not in profile})

    to_coo = current_declaration(to_source["id"], "COUNTRY_OF_ORIGIN")
    from_coo = current_declaration(from_source["id"], "COUNTRY_OF_ORIGIN")
    to_primary = to_coo["payload"].get("primary_country") if to_coo and isinstance(to_coo["payload"], dict) else None
    from_primary = from_coo["payload"].get("primary_country") if from_coo and isinstance(from_coo["payload"], dict) else None
    coo_changed = to_primary != from_primary

    requires_signoff = bool(allergen_delta_tags) or coo_changed

    assessment = new_record()
    assessment.update(
        {
            "substitution_request_id": request_rec["id"],
            "parameter_deltas": parameter_deltas,
            "total_delta_per_unit": float(total_delta),
            "allergen_delta_tags": allergen_delta_tags,
            "coo_changed": coo_changed,
        }
    )
    STORE.assessments[assessment["id"]] = assessment

    request_rec["impact_delta_per_unit"] = float(total_delta)
    request_rec["requires_regulatory_signoff"] = requires_signoff
    request_rec["status"] = "IMPACT_ASSESSED"
    touch(request_rec)
    return assessment


# ---------------------------------------------------------------------------
# Audit cadence (calculation audit_cadence_schedule)
# ---------------------------------------------------------------------------

def add_months(dt, months):
    """Whole-month arithmetic: same day-of-month, clamped to month end."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        next_month = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_month = dt.replace(year=year, month=month + 1, day=1)
    last_day = (next_month - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def supplier_has_overdue_capas(supplier_id):
    return overdue_capa_count(supplier_id) > 0


def schedule_next_audit(supplier):
    if supplier["status"] == "SUSPENDED" or supplier_has_overdue_capas(supplier["id"]):
        window_start = STORE.clock + timedelta(days=ESCALATION_DAYS)
        cadence_source = "ESCALATED"
    else:
        base = CADENCE_MONTHS[supplier["risk_tier"]]
        window_start = add_months(supplier["last_audit_closed_at__dt"], base)
        cadence_source = "TIER_CADENCE"
    window_end = window_start + timedelta(days=AUDIT_WINDOW_DAYS)
    audit = new_record()
    audit.update(
        {
            "supplier_id": supplier["id"],
            "audit_score": None,
            "findings_summary": None,
            "cadence_source": cadence_source,
            "status": "SCHEDULED",
            "_report_issued_dt": None,
            "_closed_dt": None,
        }
    )
    set_dt_system(audit, "scheduled_window_start", window_start)
    set_dt_system(audit, "scheduled_window_end", window_end)
    STORE.audits[audit["id"]] = audit
    return audit


# ---------------------------------------------------------------------------
# Clock sweeps (PRD §2.6)
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    clock = STORE.clock
    # 1. Contract expiry sweep.
    for contract in sorted(
        STORE.contracts.values(), key=lambda r: (r["_created_dt"], r["_seq"])
    ):
        if contract["status"] == "ACTIVE" and contract["window_end__dt"] <= clock:
            contract["status"] = "EXPIRED"
            touch(contract)

    # 2. Declaration expiry sweep.
    for decl in sorted(
        STORE.declarations.values(), key=lambda r: (r["_created_dt"], r["_seq"])
    ):
        if decl["status"] == "CURRENT" and decl["valid_until__dt"] <= clock:
            decl["status"] = "EXPIRED"
            touch(decl)
            src = STORE.sources.get(decl["approved_source_id"])
            if src is None:
                continue
            ingredient = STORE.ingredients.get(src["ingredient_id"])
            if src["status"] == "ACTIVE":
                src["status"] = "SUSPENDED"
                src["suspension_reason"] = "MANUAL"
                touch(src)
                if ingredient is not None:
                    recompute_dual_source(ingredient)
            supplier = STORE.suppliers.get(src["supplier_id"])
            if supplier is not None:
                recompute_risk(supplier)

    # 3. Overdue CAPA sweep.
    for supplier in sorted(
        STORE.suppliers.values(), key=lambda r: (r["_created_dt"], r["_seq"])
    ):
        recompute_risk(supplier)
