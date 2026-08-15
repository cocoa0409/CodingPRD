"""Shared entity helpers, serialization, calculations, and cascades.

Every calculation follows PRD §2.7 and §3: integer lbs and integer cents
everywhere; moisture rounded half-up to 1 dp; alpha values rounded half-up
to 2 dp; rounding applied once at the end of a computation, never
incrementally (aggregate-then-round).
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store, fmt_ts, new_id
from errors import not_found

# ---------------------------------------------------------------------------
# domain constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

VARIETIES = {"CASCADE", "CENTENNIAL", "CTZ", "CITRA", "MOSAIC"}

VARIETY_BASE_YIELD_LBS_PER_ACRE = {
    "CASCADE": 1800,
    "CENTENNIAL": 2000,
    "CTZ": 2200,
    "CITRA": 1900,
    "MOSAIC": 1700,
}

BONE_DRY_FLOOR_FRACTION = Decimal("0.24")   # green hops are 76% water
MOISTURE_RELEASE_MAX_PCT = Decimal("10.0")
PROCESSING_LOSS_PCT = Decimal("0.08")
MIN_PRICE_CENTS_PER_LB = 100
KILN_BUFFER_MINUTES = 30
STORAGE_GRACE_MONTHS = 6
MONTHLY_DECAY_RATE = Decimal("0.01")

PLAN_STATUSES = {"DRAFT", "GROWING", "HARVESTING", "COMPLETE", "CANCELLED"}
LOT_STATUSES = {"HARVESTED", "IN_KILN", "MOISTURE_CHECK", "DRIED", "CONSUMED"}
TEST_TYPES = {"PROVISIONAL", "FINAL"}
INVENTORY_STATUSES = {"AVAILABLE", "RESERVED", "SOLD", "DELIVERED"}
AGE_CLASSES = {"CURRENT", "CARRYOVER"}
ALLOCATION_STATUSES = {"PROJECTED", "CONFIRMED", "DELIVERED", "SETTLED", "CANCELLED"}
SALE_STATUSES = {"DRAFT", "CONFIRMED", "CANCELLED"}
SAMPLE_STATUSES = {"SENT", "SELECTED", "REJECTED"}
CLAIM_STATUSES = {"FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID"}


# ---------------------------------------------------------------------------
# generic record factory / mutation
# ---------------------------------------------------------------------------

def base_record():
    """Common fields per PRD §2.4: id, created_at, updated_at, version (starts
    at 1, +1 on every mutation)."""
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def base_record_light():
    """LabTest is deliberately leaner: only id and created_at."""
    return {
        "id": new_id(),
        "created_at": store.now_str(),
        "_seq": store.next_seq(),
    }


def touch(rec):
    """One mutation event on a versioned resource: version +1, updated_at refresh."""
    rec["updated_at"] = store.now_str()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip private keys; render datetimes as ISO 8601 UTC with 3 fractional digits."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out


def sort_records(records):
    """Default list order: created_at ascending (§2.3); _seq breaks the ties
    that arise when several records share one logical timestamp."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# getters with 404
# ---------------------------------------------------------------------------

def _get(table, rec_id, label):
    rec = table.get(rec_id)
    if rec is None:
        raise not_found(f"{label} not found")
    return rec


def get_field(field_id):
    return _get(store.fields, field_id, "Field")


def get_kiln(kiln_id):
    return _get(store.kilns, kiln_id, "Kiln")


def get_plan(plan_id):
    return _get(store.planting_plans, plan_id, "PlantingPlan")


def get_contract(contract_id):
    return _get(store.contracts, contract_id, "Contract")


def get_harvest_lot(lot_id):
    return _get(store.harvest_lots, lot_id, "HarvestLot")


def get_lab_test(test_id):
    return _get(store.lab_tests, test_id, "LabTest")


def get_pellet_lot(lot_id):
    return _get(store.pellet_lots, lot_id, "PelletLot")


def get_allocation(allocation_id):
    return _get(store.allocations, allocation_id, "Allocation")


def get_spot_sale(sale_id):
    return _get(store.spot_sales, sale_id, "SpotSale")


def get_sample(sample_id):
    return _get(store.samples, sample_id, "BrewerySample")


def get_claim(claim_id):
    return _get(store.insurance_claims, claim_id, "InsuranceClaim")


# ---------------------------------------------------------------------------
# rounding helpers
# ---------------------------------------------------------------------------

def rhu(value, dp):
    """Round a Decimal half-up to dp decimal places; return a Decimal."""
    return value.quantize(Decimal("1").scaleb(-dp), rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round a Decimal half-up to an integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp_float(value):
    """Round a Decimal half-up to 2 dp; return a JSON-friendly float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# §3.1 projected yield
# ---------------------------------------------------------------------------

def projected_yield_lbs(planned_acreage, variety):
    """Exact integer product, no rounding."""
    return planned_acreage * VARIETY_BASE_YIELD_LBS_PER_ACRE[variety]


# ---------------------------------------------------------------------------
# §3.2 kiln pipeline: moisture + window buffer rule
# ---------------------------------------------------------------------------

def dried_lbs_floor(wet_lbs):
    """ceil(0.24 * wet_lbs), exact integer arithmetic."""
    return (24 * wet_lbs + 99) // 100


def compute_moisture_pct(dried_lbs, wet_lbs):
    """moisture_pct = (dried - 0.24*wet)/dried * 100, half-up to 1 dp.

    Exact form: (100*dried - 24*wet) / dried.
    """
    value = Decimal(100 * dried_lbs - 24 * wet_lbs) / Decimal(dried_lbs)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def kiln_window_conflict(kiln_id, start, end, exclude_lot_id=None):
    """Half-open [start, end) against every occupying window on the same kiln.

    Occupying set: other lots with same kiln_id and status IN_KILN or
    MOISTURE_CHECK. No conflict iff separated by >= KILN_BUFFER_MINUTES on
    either side; exactly 30 minutes of clearance is allowed.
    """
    buf = timedelta(minutes=KILN_BUFFER_MINUTES)
    for lot in store.harvest_lots.values():
        if lot["id"] == exclude_lot_id:
            continue
        if lot.get("kiln_id") != kiln_id:
            continue
        if lot["status"] not in ("IN_KILN", "MOISTURE_CHECK"):
            continue
        s2 = lot["kiln_window_start"]
        e2 = lot["kiln_window_end"]
        if start >= e2 + buf or end <= s2 - buf:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# §3.3 alpha values + regrade cascade
# ---------------------------------------------------------------------------

def posted_alpha(alpha_raw):
    """A posted alpha_pct is rounded half-up to 2 dp (PRD §2.7)."""
    return rhu_2dp_float(Decimal(str(alpha_raw)))


def alpha_eff(lot):
    """Effective alpha of a harvest lot: final if set else provisional."""
    a = lot.get("alpha_pct_final")
    if a is not None:
        return Decimal(str(a))
    a = lot.get("alpha_pct_provisional")
    if a is not None:
        return Decimal(str(a))
    return None


def recompute_pellet_blend(pellet):
    """Recompute blended_alpha_pct from current source-lot alpha data.

    Weight-weighted over the source lots that carry alpha data (a lot with
    neither provisional nor final contributes neither numerator nor
    denominator); None when no source lot has any alpha posted yet.
    """
    num = Decimal(0)
    den = 0
    for sid in pellet["source_lot_ids"]:
        src = store.harvest_lots.get(sid)
        if src is None:
            continue
        a = alpha_eff(src)
        if a is None:
            continue
        num += Decimal(src["dried_lbs"]) * a
        den += src["dried_lbs"]
    if den == 0:
        return None
    return rhu_2dp_float(num / Decimal(den))


def compute_delivered_alpha(pellet_lots):
    """qty-weighted blended_alpha_pct over delivered pellet lots, half-up 2 dp.
    None if any delivered lot lacks alpha data."""
    num = Decimal(0)
    den = 0
    for p in pellet_lots:
        b = p.get("blended_alpha_pct")
        if b is None:
            return None
        num += Decimal(p["qty_lbs"]) * Decimal(str(b))
        den += p["qty_lbs"]
    if den == 0:
        return None
    return rhu_2dp_float(num / Decimal(den))


def alpha_price_adjustment(alpha, contract):
    """§3.5 pricing rule. alpha: Decimal percentage (e.g. Decimal('12.75')).

    alpha >= floor: base + (alpha - floor) * premium
    alpha <  floor: max(100, base - (floor - alpha) * discount)
    Round half-up once, at the very end, to integer cents.
    """
    floor = Decimal(str(contract["alpha_floor_pct"]))
    base = Decimal(contract["base_price_cents_per_lb"])
    if alpha >= floor:
        price = base + (alpha - floor) * Decimal(contract["alpha_premium_cents_per_point"])
    else:
        price = base - (floor - alpha) * Decimal(contract["alpha_discount_cents_per_point"])
        if price < Decimal(MIN_PRICE_CENTS_PER_LB):
            price = Decimal(MIN_PRICE_CENTS_PER_LB)
    return rhu_int(price)


def regrade_cascade(harvest_lot):
    """Fired when a FINAL lab test posts on a harvest lot (§3.3).

    1. Every pellet lot whose blend includes the lot recomputes blended_alpha_pct.
    2. Every DELIVERED (not yet SETTLED) allocation whose delivered lots include
       such a pellet lot recomputes delivered_alpha_pct and the provisional
       estimated_unit_price_cents. SETTLED allocations are never reopened.
    """
    affected_pellet_ids = set()
    for pellet in store.pellet_lots.values():
        if harvest_lot["id"] in pellet["source_lot_ids"]:
            pellet["blended_alpha_pct"] = recompute_pellet_blend(pellet)
            touch(pellet)
            affected_pellet_ids.add(pellet["id"])
    if not affected_pellet_ids:
        return
    for alloc in store.allocations.values():
        if alloc["status"] != "DELIVERED":
            continue
        if not affected_pellet_ids.intersection(alloc["delivered_lot_ids"]):
            continue
        pellets = [store.pellet_lots[lid] for lid in alloc["delivered_lot_ids"]
                   if lid in store.pellet_lots]
        alloc["delivered_alpha_pct"] = compute_delivered_alpha(pellets)
        contract = store.contracts.get(alloc["contract_id"])
        if alloc["delivered_alpha_pct"] is not None and contract is not None:
            alloc["estimated_unit_price_cents"] = alpha_price_adjustment(
                Decimal(str(alloc["delivered_alpha_pct"])), contract)
        else:
            alloc["estimated_unit_price_cents"] = None
        touch(alloc)


# ---------------------------------------------------------------------------
# §3.4 pelletizing
# ---------------------------------------------------------------------------

def compute_pellet_qty(source_lots):
    """Aggregate-then-round: qty_lbs = round_half_up(sum(dried) * (1 - 0.08), 0).
    Per-lot rounding first is a forbidden order."""
    total_dried = sum(lot["dried_lbs"] for lot in source_lots)
    return rhu_int(Decimal(total_dried) * (Decimal(1) - PROCESSING_LOSS_PCT))


# ---------------------------------------------------------------------------
# §3.6 allocation run (pro-rata waterfall) and lifecycle helpers
# ---------------------------------------------------------------------------

def cancel_allocation(alloc):
    """PROJECTED|CONFIRMED|DELIVERED -> CANCELLED.

    A cancelled CONFIRMED allocation releases its reserved pellet lots back to
    AVAILABLE and clears reserved_lot_ids. A cancelled DELIVERED allocation
    keeps delivered_lbs/delivered_lot_ids as a historical record and does NOT
    release its lots (they were physically delivered).
    """
    if alloc["status"] == "CONFIRMED":
        for lid in alloc["reserved_lot_ids"]:
            pellet = store.pellet_lots.get(lid)
            if pellet is not None and pellet["inventory_status"] == "RESERVED":
                pellet["inventory_status"] = "AVAILABLE"
                touch(pellet)
        alloc["reserved_lot_ids"] = []
    alloc["status"] = "CANCELLED"
    touch(alloc)


def default_contract_cascade(contract):
    """ACTIVE -> DEFAULTED: cancel this contract's PROJECTED/CONFIRMED
    allocations; confirmed ones release their reserved lots."""
    for alloc in store.allocations.values():
        if alloc["contract_id"] != contract["id"]:
            continue
        if alloc["status"] in ("PROJECTED", "CONFIRMED"):
            cancel_allocation(alloc)


def eligible_lots_for_run(variety):
    """AVAILABLE pellet lots of the run's variety — any age_class, any crop_year."""
    return [p for p in store.pellet_lots.values()
            if p["variety"] == variety and p["inventory_status"] == "AVAILABLE"]


def contract_has_live_allocation(contract_id, crop_year):
    for a in store.allocations.values():
        if (a["contract_id"] == contract_id and a["crop_year"] == crop_year
                and a["status"] in ("PROJECTED", "CONFIRMED", "DELIVERED")):
            return True
    return False


def run_pro_rata(crop_year, variety):
    """POST /api/allocation-runs.

    Supersede: existing PROJECTED allocations for (crop_year, variety) are
    cancelled first. Eligible contracts: ACTIVE, variety match, term covers
    crop_year, and no non-terminal allocation for the crop year.
    """
    for alloc in list(store.allocations.values()):
        if (alloc["crop_year"] == crop_year and alloc["variety"] == variety
                and alloc["status"] == "PROJECTED"):
            cancel_allocation(alloc)

    elig = []
    for c in sort_records(list(store.contracts.values())):
        if c["status"] != "ACTIVE" or c["variety"] != variety:
            continue
        if not (c["term_start_year"] <= crop_year <= c["term_end_year"]):
            continue
        if contract_has_live_allocation(c["id"], crop_year):
            continue
        elig.append(c)

    available_lbs = sum(p["qty_lbs"] for p in eligible_lots_for_run(variety))
    contracted_total_lbs = sum(c["annual_volume_lbs"] for c in elig)

    shares = {}
    if elig:
        if available_lbs >= contracted_total_lbs:
            for c in elig:
                shares[c["id"]] = c["annual_volume_lbs"]
        else:
            exact = {c["id"]: Fraction(available_lbs * c["annual_volume_lbs"],
                                       contracted_total_lbs) for c in elig}
            base = {cid: ex.numerator // ex.denominator for cid, ex in exact.items()}
            remainder = available_lbs - sum(base.values())
            # largest remainder first; ties break toward the earlier-created contract
            order = sorted(elig, key=lambda c: (-(exact[c["id"]] - base[c["id"]]),
                                                c["created_at"], c["_seq"]))
            idx = 0
            while remainder > 0:
                base[order[idx]["id"]] += 1
                remainder -= 1
                idx += 1
            shares = base

    created_ids = []
    for c in elig:
        alloc = base_record()
        alloc.update({
            "contract_id": c["id"],
            "crop_year": crop_year,
            "variety": variety,
            "allocated_lbs": shares[c["id"]],
            "shortfall_lbs": c["annual_volume_lbs"] - shares[c["id"]],
            "reserved_lot_ids": [],
            "delivered_lbs": 0,
            "delivered_lot_ids": [],
            "delivered_alpha_pct": None,
            "estimated_unit_price_cents": None,
            "delivery_shortfall_lbs": None,
            "unit_price_cents": None,
            "settlement_total_cents": None,
            "status": "PROJECTED",
        })
        store.allocations[alloc["id"]] = alloc
        created_ids.append(alloc["id"])

    return available_lbs, contracted_total_lbs, created_ids


def fifo_reserve(alloc, contract):
    """Walk AVAILABLE lots of the contract's variety, oldest first by
    entered_storage_at (tie: created_at ascending); reserve a lot iff it does
    not push the cumulative reserved total above allocated_lbs; stop when the
    cumulative total reaches allocated_lbs or the pool is exhausted."""
    pool = [p for p in store.pellet_lots.values()
            if p["variety"] == contract["variety"] and p["inventory_status"] == "AVAILABLE"]
    pool.sort(key=lambda p: (p["entered_storage_at"], p["created_at"], p["_seq"]))
    cumulative = 0
    reserved = []
    for p in pool:
        if cumulative == alloc["allocated_lbs"]:
            break
        if cumulative + p["qty_lbs"] <= alloc["allocated_lbs"]:
            reserved.append(p)
            cumulative += p["qty_lbs"]
    for p in reserved:
        p["inventory_status"] = "RESERVED"
        touch(p)
    alloc["reserved_lot_ids"] = [p["id"] for p in reserved]


# ---------------------------------------------------------------------------
# §3.8 insurance indemnity variants
# ---------------------------------------------------------------------------

def compute_guarantee_lbs(plan, coverage_pct):
    """round_half_up(planned_acreage * base yield * coverage_pct, 0)."""
    raw = Decimal(plan["planned_acreage"] * VARIETY_BASE_YIELD_LBS_PER_ACRE[plan["variety"]])
    return rhu_int(raw * Decimal(str(coverage_pct)))


def indemnity_cents(guarantee_lbs, production_lbs, price_election_cents_per_lb):
    """max(0, guarantee - production) * price election — exact integer cents."""
    return max(0, guarantee_lbs - production_lbs) * price_election_cents_per_lb


# ---------------------------------------------------------------------------
# §3.9 rollover: carryover decay + contract completion
# ---------------------------------------------------------------------------

def full_calendar_months(start, end):
    """Full calendar months between two instants (anniversary-based)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def crop_year_rollover():
    """Two sweeps against the logical clock's year (§3.9)."""
    clock = store.now()
    clock_year = clock.year

    carried_over_lot_ids = []
    for pellet in sort_records(list(store.pellet_lots.values())):
        if pellet["age_class"] != "CURRENT":
            continue
        if pellet["crop_year"] >= clock_year:
            continue
        if pellet["inventory_status"] not in ("AVAILABLE", "RESERVED"):
            continue
        pellet["age_class"] = "CARRYOVER"
        # carryover decay fires exactly once, at the flip
        if pellet["blended_alpha_pct"] is not None:
            months_stored = full_calendar_months(pellet["entered_storage_at"], clock)
            decay_months = max(0, months_stored - STORAGE_GRACE_MONTHS)
            if decay_months > 0:
                decayed = (Decimal(str(pellet["blended_alpha_pct"]))
                           * ((Decimal(1) - MONTHLY_DECAY_RATE) ** decay_months))
                pellet["blended_alpha_pct"] = rhu_2dp_float(decayed)
        touch(pellet)
        carried_over_lot_ids.append(pellet["id"])

    completed_contract_ids = []
    for contract in sort_records(list(store.contracts.values())):
        if contract["status"] != "ACTIVE":
            continue
        if contract["term_end_year"] >= clock_year:
            continue
        contract["status"] = "COMPLETED"
        touch(contract)
        # asymmetry with termination: DELIVERED allocations are NOT cancelled
        for alloc in store.allocations.values():
            if alloc["contract_id"] != contract["id"]:
                continue
            if alloc["status"] in ("PROJECTED", "CONFIRMED"):
                cancel_allocation(alloc)
        completed_contract_ids.append(contract["id"])

    return carried_over_lot_ids, completed_contract_ids


# ---------------------------------------------------------------------------
# list filtering helper
# ---------------------------------------------------------------------------

def filtered_sorted(records, args, spec):
    """Apply query-param filters then the default sort.

    spec maps query param -> (kind, record_field[, enum_values]) with kind in
    {"str", "int", "enum", "member"}. Invalid enum/int filter values are a
    request-shape failure (ERR_INVALID_REQUEST).
    """
    from errors import invalid_request

    conditions = []
    for param, rule in spec.items():
        raw = args.get(param)
        if raw is None:
            continue
        kind = rule[0]
        field = rule[1]
        if kind == "str":
            conditions.append(lambda r, f=field, v=raw: r.get(f) == v)
        elif kind == "int":
            try:
                v = int(raw)
            except (TypeError, ValueError):
                raise invalid_request(f"{param} must be an integer")
            conditions.append(lambda r, f=field, v=v: r.get(f) == v)
        elif kind == "enum":
            values = rule[2]
            if raw not in values:
                raise invalid_request(f"{param} must be one of {', '.join(sorted(values))}")
            conditions.append(lambda r, f=field, v=raw: r.get(f) == v)
        elif kind == "member":
            conditions.append(lambda r, f=field, v=raw: v in (r.get(f) or []))
    out = [r for r in records if all(cond(r) for cond in conditions)]
    return sort_records(out)
