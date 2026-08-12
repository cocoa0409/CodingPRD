"""Business logic: derived fields, calculation rules (PRD 2.7-2.10, scaffold 1.3),
cascading side effects, and entity serializers.

All money is integer cents, all tonnages are Decimal carried to three decimals,
and every rounding is round-half-up pinned to the stage the PRD pins it to.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, clock_now, bump, fmt_dt
from errors import ApiError

D = Decimal

CENT = D("1")
PCT2 = D("0.01")
TONS3 = D("0.001")

# Calculation constants (scaffold 1.3)
MAX_INCLUSION_PCT = D("70")
WEIGHMENT_TOLERANCE_PCT = D("2.00")
ORDER_QTY_TOLERANCE = D("0.02")
MIN_FLUSH_TONS = D("0.5")
CLEANUP_BUFFER = timedelta(minutes=45)
MARGIN_TIER1_CAP_CENTS = 500000
MARGIN_TIER2_CAP_CENTS = 2000000
MEDICATED_SURCHARGE_CENTS_PER_TON = 1500
DELIVERY_BASE_CENTS = 7500
DELIVERY_PER_TON_CENTS = 900


def rhu(value, quantum):
    """Round half up — the only rounding mode in the system (PRD 2.7)."""
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _num(v):
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    return v


def sorted_items(coll):
    """Every list endpoint sorts by created_at ascending (PRD 2.3); _seq breaks
    ties deterministically when several records share one logical instant."""
    return sorted(coll.values(), key=lambda r: (r["_created_dt"], r["_seq"]))


# ---------------------------------------------------------------------------
# Derived fields (recomputed inside the mutating request; PRD 2.4)
# ---------------------------------------------------------------------------

def bin_on_hand(b):
    drawn = sum((w["actual_tons"] for w in STORE["weighments"].values()
                 if w["bin_id"] == b["id"] and w["status"] == "RECORDED"), D("0"))
    return b["cumulative_replenished_tons"] - drawn


def bin_status(b):
    if b["blocked"]:
        return "BLOCKED"
    return "EMPTY" if bin_on_hand(b) == 0 else "READY"


def contract_consumed(c):
    return sum((w["actual_tons"] for w in STORE["weighments"].values()
                if w["contract_id"] == c["id"] and w["status"] == "RECORDED"), D("0"))


def contract_remaining(c):
    return c["total_tons"] - contract_consumed(c)


def credit_used(customer_id):
    """PRD 2.10: CONFIRMED/IN_PRODUCTION quoted totals + COMPLETED final totals."""
    total = 0
    for o in STORE["orders"].values():
        if o["customer_id"] != customer_id:
            continue
        if o["status"] in ("CONFIRMED", "IN_PRODUCTION"):
            total += o["quoted_total_cents"]
        elif o["status"] == "COMPLETED":
            total += o["final_total_cents"]
    return total


def order_blocked(order_id):
    return any(b["order_id"] == order_id and b["status"] == "HOLD"
               for b in STORE["batches"].values())


def batch_actual_tons(batch_id):
    return sum((w["actual_tons"] for w in STORE["weighments"].values()
                if w["batch_id"] == batch_id and w["status"] == "RECORDED"), D("0"))


def batch_ingredient_cost(batch_id):
    return sum((w["line_cost_cents"] for w in STORE["weighments"].values()
                if w["batch_id"] == batch_id and w["status"] == "RECORDED"), 0)


def last_medicated_batch(line_id):
    cands = [b for b in STORE["batches"].values()
             if b["line_id"] == line_id and b["is_medicated"] and b["mixed_at"] is not None]
    if not cands:
        return None
    return max(cands, key=lambda b: (b["mixed_at"], b["_seq"]))


def line_contamination(line_id):
    """MEDICATED iff a medicated batch mixed on this line and no VERIFIED flush
    has verified_at strictly after that batch's mixed_at (PRD 3.7)."""
    last = last_medicated_batch(line_id)
    if last is None:
        return "NONE"
    cleared = any(f["line_id"] == line_id and f["status"] == "VERIFIED"
                  and f["verified_at"] is not None and f["verified_at"] > last["mixed_at"]
                  for f in STORE["flushes"].values())
    return "NONE" if cleared else "MEDICATED"


def quote_stale(o):
    f = STORE["formulas"].get(o["formula_id"])
    if f is None:
        return True
    return (f["version"] != o["quoted_formula_version"]
            or f["provisional_cost_cents_per_ton"] != o["quoted_cost_basis_cents"])


def formula_in_use(formula_id):
    for o in STORE["orders"].values():
        if (o["formula_id"] == formula_id and o["pinned_formula_version"] is not None
                and o["status"] in ("CONFIRMED", "REVISING", "IN_PRODUCTION", "COMPLETED")):
            return True
    return False


# ---------------------------------------------------------------------------
# Pricing calculations
# ---------------------------------------------------------------------------

def effective_spot_price(ingredient_id, T):
    """Tick with the greatest effective_from <= T; ties toward latest created_at."""
    best = None
    best_key = None
    for t in STORE["price_ticks"].values():
        if t["ingredient_id"] != ingredient_id:
            continue
        if t["effective_from"] > T:
            continue
        key = (t["effective_from"], t["_created_dt"], t["_seq"])
        if best_key is None or key > best_key:
            best_key = key
            best = t
    return best["price_cents_per_ton"] if best else None


def contract_pool(ingredient_id, T, min_cover=None):
    """OPEN contracts of the ingredient whose closed window covers date(T),
    ranked earliest window end, then lowest fixed price, then earliest created."""
    d = T.date()
    pool = []
    for c in STORE["contracts"].values():
        if c["ingredient_id"] != ingredient_id or c["status"] != "OPEN":
            continue
        if not (c["window_start"] <= d <= c["window_end"]):
            continue
        if min_cover is not None and contract_remaining(c) < min_cover:
            continue
        pool.append(c)
    pool.sort(key=lambda c: (c["window_end"], c["fixed_price_cents_per_ton"],
                             c["_created_dt"], c["_seq"]))
    return pool


def blend_cost(ingredient_id, tons, T):
    """Contract-blend projection of `tons` of one ingredient at T (unrounded)."""
    remaining = tons
    cost = D("0")
    for c in contract_pool(ingredient_id, T):
        if remaining <= 0:
            break
        covered = min(contract_remaining(c), remaining)
        cost += covered * c["fixed_price_cents_per_ton"]
        remaining -= covered
    if remaining > 0:
        spot = effective_spot_price(ingredient_id, T)
        if spot is not None:
            cost += remaining * spot
    return cost


def provisional_cost(lines, T):
    """One reference ton projected per line independently; rounded once at end."""
    total = D("0")
    for line in lines:
        tons_i = line["inclusion_pct"] / D("100")
        total += blend_cost(line["ingredient_id"], tons_i, T)
    return int(rhu(total, CENT))


def solve_ration(T):
    """Least-cost greedy waterfall (scaffold calculation least_cost_ration_solve)."""
    candidates = []
    for ing in STORE["ingredients"].values():
        if ing["status"] != "ACTIVE":
            continue
        price = effective_spot_price(ing["id"], T)
        if price is None:
            continue
        candidates.append((ing, price))
    if not candidates or MAX_INCLUSION_PCT * len(candidates) < D("100"):
        raise ApiError("ERR_FORMULA_NOT_FEASIBLE", 422,
                       "Optimizer cannot fill 100%: too few priced ACTIVE candidates")
    # cheapest first; ties toward higher protein, then earlier created_at
    candidates.sort(key=lambda ip: (ip[1], -ip[0]["crude_protein_pct"],
                                    ip[0]["_created_dt"], ip[0]["_seq"]))
    lines = []
    remaining = D("100.00")
    for ing, _price in candidates:
        take = min(MAX_INCLUSION_PCT, remaining)
        if take > 0:
            lines.append({"ingredient_id": ing["id"], "inclusion_pct": rhu(take, PCT2)})
            remaining -= take
        if remaining == 0:
            break
    return lines


def nutrient_totals(lines):
    tp = tf = te = D("0")
    for line in lines:
        ing = STORE["ingredients"].get(line["ingredient_id"])
        if ing is None:
            continue
        tp += line["inclusion_pct"] * ing["crude_protein_pct"]
        tf += line["inclusion_pct"] * ing["crude_fiber_pct"]
        te += line["inclusion_pct"] * ing["metabolizable_energy_kcal_kg"]
    return rhu(tp / 100, PCT2), rhu(tf / 100, PCT2), rhu(te / 100, PCT2)


def _price_finish(subtotal, tons, is_medicated):
    """Pinned evaluation order (scaffold order_price): margin tier on the
    pre-margin subtotal, margin rounded, then surcharge, then delivery."""
    if subtotal <= MARGIN_TIER1_CAP_CENTS:
        margin_pct = D("0.12")
    elif subtotal <= MARGIN_TIER2_CAP_CENTS:
        margin_pct = D("0.10")
    else:
        margin_pct = D("0.08")
    margin = int(rhu(D(subtotal) * margin_pct, CENT))
    surcharge = int(rhu(tons * MEDICATED_SURCHARGE_CENTS_PER_TON, CENT)) if is_medicated else 0
    delivery = DELIVERY_BASE_CENTS + int(rhu(tons * DELIVERY_PER_TON_CENTS, CENT))
    return subtotal + margin + surcharge + delivery


def order_price_quoted(lines, tons, T, is_medicated):
    """Variant quoted: per-line contract-blend projection, rounded per line."""
    subtotal = 0
    for line in lines:
        line_tons = rhu(line["inclusion_pct"] / D("100") * tons, TONS3)
        line_cost = int(rhu(blend_cost(line["ingredient_id"], line_tons, T), CENT))
        subtotal += line_cost
    return _price_finish(subtotal, tons, is_medicated)


def order_price_final(order):
    """Variant final: per-ingredient sums of already-rounded weighment costs over
    the order's RELEASED batches (never re-rounded)."""
    released_ids = {b["id"] for b in STORE["batches"].values()
                    if b["order_id"] == order["id"] and b["status"] == "RELEASED"}
    subtotal = 0
    for line in order["pinned_lines"]:
        subtotal += sum((w["line_cost_cents"] for w in STORE["weighments"].values()
                         if w["batch_id"] in released_ids and w["status"] == "RECORDED"
                         and w["ingredient_id"] == line["ingredient_id"]), 0)
    return _price_finish(subtotal, order["tons"], order["is_medicated"])


def check_mix_tolerance(batch, order):
    """Per-line 2.00 pct gate; exactly 2.00 passes (strictly-greater comparison)."""
    for line in order["pinned_lines"]:
        target = rhu(line["inclusion_pct"] / D("100") * batch["target_tons"], TONS3)
        actual = sum((w["actual_tons"] for w in STORE["weighments"].values()
                      if w["batch_id"] == batch["id"] and w["status"] == "RECORDED"
                      and w["ingredient_id"] == line["ingredient_id"]), D("0"))
        if target == 0:
            if actual != 0:
                raise ApiError("ERR_WEIGHMENT_OUT_OF_TOLERANCE", 422,
                               "Weighment deviation exceeds 2.00 pct for a line")
            continue
        deviation = rhu(abs(actual - target) / target * D("100"), PCT2)
        if deviation > WEIGHMENT_TOLERANCE_PCT:
            raise ApiError("ERR_WEIGHMENT_OUT_OF_TOLERANCE", 422,
                           f"Line {line['ingredient_id']} deviates {deviation}% from target")


# ---------------------------------------------------------------------------
# Window / overlap rules (scaffold calculations, interval semantics)
# ---------------------------------------------------------------------------

def line_window_conflict(line_id, start, end):
    new_end = end + CLEANUP_BUFFER
    for b in STORE["batches"].values():
        if b["line_id"] != line_id:
            continue
        if b["status"] not in ("PLANNED", "BATCHING", "MIXED", "HOLD", "RELEASED", "REJECTED"):
            continue
        ex_end = b["planned_end_at"] + CLEANUP_BUFFER
        if start < ex_end and b["planned_start_at"] < new_end:
            return True
    return False


def truck_window_conflict(truck_id, departure, ret):
    for t in STORE["trips"].values():
        if t["truck_id"] != truck_id:
            continue
        if t["status"] not in ("PLANNED", "LOADING", "IN_TRANSIT"):
            continue
        if departure < t["planned_return_at"] and t["planned_departure_at"] < ret:
            return True
    return False


# ---------------------------------------------------------------------------
# Cascading side effects
# ---------------------------------------------------------------------------

def recompute_provisional_for_ingredient(ingredient_id):
    """Provisional cost recompute NEVER increments Formula.version (PRD 3.4)."""
    T = clock_now()
    for f in STORE["formulas"].values():
        if (f["status"] in ("DRAFT", "ACTIVE")
                and any(l["ingredient_id"] == ingredient_id for l in f["lines"])):
            f["provisional_cost_cents_per_ton"] = provisional_cost(f["lines"], T)


def contract_after_consumption(c):
    if c["status"] == "OPEN" and contract_remaining(c) == 0:
        c["status"] = "EXHAUSTED"
        bump(c)
        recompute_provisional_for_ingredient(c["ingredient_id"])


def contract_after_void(c):
    if c["status"] == "EXHAUSTED" and contract_remaining(c) > 0:
        c["status"] = "OPEN"
        bump(c)
        recompute_provisional_for_ingredient(c["ingredient_id"])


def maybe_expire_contract(c):
    """Lazy OPEN -> EXPIRED evaluation on contract reads and clock advance."""
    if (c["status"] == "OPEN" and clock_now().date() > c["window_end"]
            and contract_remaining(c) > 0):
        c["status"] = "EXPIRED"
        bump(c)
        recompute_provisional_for_ingredient(c["ingredient_id"])


def expiry_sweep():
    for c in list(STORE["contracts"].values()):
        maybe_expire_contract(c)


def discontinue_cascade(ingredient):
    for b in STORE["bins"].values():
        if (b["ingredient_id"] == ingredient["id"] and not b["blocked"]
                and bin_on_hand(b) > 0):
            b["blocked"] = True
            bump(b)
    for f in STORE["formulas"].values():
        if (f["status"] in ("DRAFT", "ACTIVE")
                and any(l["ingredient_id"] == ingredient["id"] for l in f["lines"])):
            f["status"] = "RETIRED"
            bump(f)


def sample_fail_cascade(batch):
    """FAIL result: batch MIXED -> HOLD, order blocked recomputes (derived),
    PLANNED/LOADING trips of the order are cancelled (not auto-revived)."""
    if batch["status"] == "MIXED":
        batch["status"] = "HOLD"
        bump(batch)
    order_id = batch["order_id"]
    for t in STORE["trips"].values():
        if t["order_id"] == order_id and t["status"] in ("PLANNED", "LOADING"):
            t["status"] = "CANCELLED"
            bump(t)


def maybe_bubble_order_delivered(order):
    """Order COMPLETED -> DELIVERED once every trip is terminal, at least one is
    DELIVERED, and delivered tons exactly equal the order's tons."""
    if order["status"] != "COMPLETED":
        return
    trips = [t for t in STORE["trips"].values() if t["order_id"] == order["id"]]
    if not trips:
        return
    if not all(t["status"] in ("DELIVERED", "CANCELLED") for t in trips):
        return
    delivered = [t for t in trips if t["status"] == "DELIVERED"]
    if not delivered:
        return
    if sum((t["total_tons"] for t in delivered), D("0")) != order["tons"]:
        return
    order["status"] = "DELIVERED"
    bump(order)
    customer = STORE["customers"].get(order["customer_id"])
    if customer is not None:
        bump(customer)


# ---------------------------------------------------------------------------
# Serializers (common fields: id, created_at, updated_at, version — PriceTick
# carries only id + created_at, PRD 2.4)
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_lines(lines):
    if lines is None:
        return None
    return [{"ingredient_id": l["ingredient_id"],
             "inclusion_pct": _num(l["inclusion_pct"])} for l in lines]


def ser_customer(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "medicated_permit_ref": c["medicated_permit_ref"],
        "credit_used_cents": credit_used(c["id"]),
        "status": c["status"],
    })
    return out


def ser_employee(e):
    out = _common(e)
    out.update({"full_name": e["full_name"], "capability": e["capability"]})
    return out


def ser_ingredient(i):
    out = _common(i)
    out.update({
        "code": i["code"],
        "name": i["name"],
        "hazard_class": i["hazard_class"],
        "is_flush_material": i["is_flush_material"],
        "crude_protein_pct": _num(i["crude_protein_pct"]),
        "crude_fiber_pct": _num(i["crude_fiber_pct"]),
        "metabolizable_energy_kcal_kg": _num(i["metabolizable_energy_kcal_kg"]),
        "status": i["status"],
    })
    return out


def ser_price_tick(t):
    return {
        "id": t["id"],
        "ingredient_id": t["ingredient_id"],
        "price_cents_per_ton": t["price_cents_per_ton"],
        "effective_from": fmt_dt(t["effective_from"]),
        "created_at": t["created_at"],
    }


def ser_contract(c):
    out = _common(c)
    out.update({
        "ingredient_id": c["ingredient_id"],
        "supplier_ref": c["supplier_ref"],
        "fixed_price_cents_per_ton": c["fixed_price_cents_per_ton"],
        "total_tons": _num(c["total_tons"]),
        "consumed_tons": _num(contract_consumed(c)),
        "remaining_tons": _num(contract_remaining(c)),
        "window_start_date": c["window_start"].isoformat(),
        "window_end_date": c["window_end"].isoformat(),
        "status": c["status"],
    })
    return out


def ser_bin(b):
    out = _common(b)
    out.update({
        "code": b["code"],
        "capacity_tons": _num(b["capacity_tons"]),
        "ingredient_id": b["ingredient_id"],
        "on_hand_tons": _num(bin_on_hand(b)),
        "cumulative_replenished_tons": _num(b["cumulative_replenished_tons"]),
        "status": bin_status(b),
    })
    return out


def ser_formula(f):
    out = _common(f)
    out.update({
        "code": f["code"],
        "min_protein_pct": _num(f["min_protein_pct"]),
        "max_fiber_pct": _num(f["max_fiber_pct"]),
        "min_energy_kcal_kg": _num(f["min_energy_kcal_kg"]),
        "lines": ser_lines(f["lines"]),
        "total_protein_pct": _num(f["total_protein_pct"]),
        "total_fiber_pct": _num(f["total_fiber_pct"]),
        "total_energy_kcal_kg": _num(f["total_energy_kcal_kg"]),
        "meets_constraints": f["meets_constraints"],
        "provisional_cost_cents_per_ton": f["provisional_cost_cents_per_ton"],
        "status": f["status"],
    })
    return out


def ser_order(o):
    out = _common(o)
    out.update({
        "customer_id": o["customer_id"],
        "formula_id": o["formula_id"],
        "tons": _num(o["tons"]),
        "is_medicated": o["is_medicated"],
        "quoted_formula_version": o["quoted_formula_version"],
        "quoted_cost_basis_cents": o["quoted_cost_basis_cents"],
        "quoted_total_cents": o["quoted_total_cents"],
        "pinned_formula_version": o["pinned_formula_version"],
        "pinned_lines": ser_lines(o["pinned_lines"]),
        "pinned_min_protein_pct": _num(o["pinned_min_protein_pct"]),
        "pinned_max_fiber_pct": _num(o["pinned_max_fiber_pct"]),
        "final_total_cents": o["final_total_cents"],
        "quote_stale": quote_stale(o),
        "blocked": order_blocked(o["id"]),
        "status": o["status"],
    })
    return out


def ser_line(l):
    out = _common(l)
    out.update({
        "code": l["code"],
        "status": l["status"],
        "contamination": line_contamination(l["id"]),
    })
    return out


def ser_batch(b):
    out = _common(b)
    out.update({
        "order_id": b["order_id"],
        "line_id": b["line_id"],
        "target_tons": _num(b["target_tons"]),
        "planned_start_at": fmt_dt(b["planned_start_at"]),
        "planned_end_at": fmt_dt(b["planned_end_at"]),
        "is_medicated": b["is_medicated"],
        "actual_tons": _num(batch_actual_tons(b["id"])),
        "ingredient_cost_cents": batch_ingredient_cost(b["id"]),
        "mixed_at": fmt_dt(b["mixed_at"]),
        "status": b["status"],
    })
    return out


def ser_weighment(w):
    out = _common(w)
    out.update({
        "batch_id": w["batch_id"],
        "ingredient_id": w["ingredient_id"],
        "bin_id": w["bin_id"],
        "actual_tons": _num(w["actual_tons"]),
        "source": w["source"],
        "contract_id": w["contract_id"],
        "unit_price_cents": w["unit_price_cents"],
        "line_cost_cents": w["line_cost_cents"],
        "status": w["status"],
    })
    return out


def ser_flush(f):
    out = _common(f)
    out.update({
        "line_id": f["line_id"],
        "flush_material_ingredient_id": f["flush_material_ingredient_id"],
        "quantity_tons": _num(f["quantity_tons"]),
        "recorded_by_employee_id": f["recorded_by_employee_id"],
        "verified_by_employee_id": f["verified_by_employee_id"],
        "verified_at": fmt_dt(f["verified_at"]),
        "status": f["status"],
    })
    return out


def ser_sample(s):
    out = _common(s)
    out.update({
        "batch_id": s["batch_id"],
        "sample_type": s["sample_type"],
        "retain_expiry_date": fmt_dt(s["retain_expiry_date"]),
        "protein_pct_actual": _num(s["protein_pct_actual"]),
        "crude_fiber_pct_actual": _num(s["crude_fiber_pct_actual"]),
        "moisture_pct": _num(s["moisture_pct"]),
        "protein_dry_matter": _num(s["protein_dry_matter"]),
        "fiber_dry_matter": _num(s["fiber_dry_matter"]),
        "result": s["result"],
        "result_by_employee_id": s["result_by_employee_id"],
    })
    return out


def ser_truck(t):
    out = _common(t)
    out.update({
        "plate_no": t["plate_no"],
        "cargo_class_capability": t["cargo_class_capability"],
        "compartments": [{"compartment_seq": c["compartment_seq"],
                          "capacity_tons": _num(c["capacity_tons"])}
                         for c in t["compartments"]],
        "status": t["status"],
    })
    return out


def ser_trip(t):
    out = _common(t)
    out.update({
        "truck_id": t["truck_id"],
        "order_id": t["order_id"],
        "planned_departure_at": fmt_dt(t["planned_departure_at"]),
        "planned_return_at": fmt_dt(t["planned_return_at"]),
        "compartment_allocations": [
            {"compartment_seq": a["compartment_seq"],
             "tons": _num(a["tons"]),
             "cargo_class": a["cargo_class"]}
            for a in t["compartment_allocations"]],
        "total_tons": _num(t["total_tons"]),
        "status": t["status"],
    })
    return out
