"""Shared business logic: aggregates, reconciliation, and validation helpers."""
from decimal import Decimal

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_INVALID_TIER_SET,
)
from util import dec, round1, round2, num_out, is_int, is_num, req_str, req_num, invalid, not_found


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def formula_lines(formula_id):
    return [l for l in store["formula_lines"].values() if l["formula_id"] == formula_id]


def batch_of_mo(mo_id):
    for b in store["batches"].values():
        if b["mo_id"] == mo_id:
            return b
    return None


def mo_formula(mo):
    return store["formulas"].get(mo["formula_id"])


def batch_mo(batch):
    return store["manufacturing_orders"].get(batch["mo_id"])


# ---------------------------------------------------------------------------
# Customer commercial aggregates (PRD section 2.12): recomputed in full after
# every order-book mutation so the pinned invariant always holds.
# ---------------------------------------------------------------------------
OPEN_ORDER_STATUSES = ("PLACED", "SCHEDULED", "IN_PRODUCTION")


def refresh_customer_aggregates(customer_id):
    customer = store["customers"].get(customer_id)
    if customer is None:
        return
    orders = [o for o in store["manufacturing_orders"].values() if o["customer_id"] == customer_id]
    open_orders = [o for o in orders if o["status"] in OPEN_ORDER_STATUSES]
    values = {
        "committed_order_value_cents": sum(o["total_price_cents"] for o in open_orders),
        "open_order_count": len(open_orders),
        "lifetime_receipts_cents": sum(
            o["total_price_cents"] for o in orders if o["status"] == "COMPLETED"
        ),
        "open_recall_count": sum(1 for o in orders if o.get("recall_flag")),
    }
    changed = any(customer[k] != v for k, v in values.items())
    customer.update(values)
    if changed:
        touch(customer)


# ---------------------------------------------------------------------------
# Lot quantity reconciliation (calculation lot_qty_reconciliation):
# qty_remaining = qty_received - sum(qty_consumed over ACTIVE rows), 2dp
# round-half-up.
# ---------------------------------------------------------------------------
def recompute_lot_remaining(lot):
    used = Decimal("0")
    for row in store["batch_consumptions"].values():
        if row["material_lot_id"] == lot["id"] and row["status"] == "ACTIVE":
            used += dec(row["qty_consumed"])
    lot["qty_remaining"] = num_out(round2(dec(lot["qty_received"]) - used))


# ---------------------------------------------------------------------------
# Price tier set validation (PRD section 3.1). A non-empty set must have its
# first min_qty equal to min_order_qty, strictly increasing min_qty, and
# strictly decreasing unit_price_cents. An empty set is tolerated on a DRAFT.
# ---------------------------------------------------------------------------
def check_tier_entries_shape(tiers):
    for t in tiers:
        if not isinstance(t, dict):
            invalid("price_tiers entries must be objects with min_qty and unit_price_cents")
        if not is_int(t.get("min_qty")) or not is_int(t.get("unit_price_cents")):
            invalid("price_tiers entries must carry integer min_qty and unit_price_cents")


def check_tier_ordering(tiers, min_order_qty):
    if not tiers:
        return
    if tiers[0]["min_qty"] != min_order_qty:
        raise_error(
            ERR_INVALID_TIER_SET,
            "The first tier's min_qty must equal the formula's min_order_qty",
        )
    for prev, nxt in zip(tiers, tiers[1:]):
        if not nxt["min_qty"] > prev["min_qty"]:
            raise_error(ERR_INVALID_TIER_SET, "Tier min_qty values must be strictly increasing")
        if not nxt["unit_price_cents"] < prev["unit_price_cents"]:
            raise_error(
                ERR_INVALID_TIER_SET,
                "Tier unit_price_cents values must be strictly decreasing",
            )


def normalize_tiers(tiers):
    return [
        {"min_qty": t["min_qty"], "unit_price_cents": t["unit_price_cents"]} for t in tiers
    ]


# ---------------------------------------------------------------------------
# Formula line payload validation (PRD section 3.1).
# ---------------------------------------------------------------------------
def validate_line_payload(line):
    if not isinstance(line, dict):
        invalid("Each formula line must be an object")
    raw_material_id = req_str(line, "raw_material_id")
    if raw_material_id not in store["raw_materials"]:
        not_found("raw_material_id does not identify an existing raw material")
    theoretical = req_num(line, "theoretical_qty_mg_per_unit")
    if not dec(theoretical) > 0:
        invalid("'theoretical_qty_mg_per_unit' must be greater than zero")
    if "overage_pct" not in line or not is_num(line["overage_pct"]):
        invalid("'overage_pct' must be a number")
    overage = dec(line["overage_pct"])
    if overage < 0 or overage > 25:
        invalid("'overage_pct' must be within [0, 25]")
    flag = line.get("is_label_claim_line")
    if not isinstance(flag, bool):
        invalid("'is_label_claim_line' must be a boolean")
    label_claim = line.get("label_claim_mg_per_unit")
    if flag:
        if not is_num(label_claim) or not dec(label_claim) > 0:
            invalid("'label_claim_mg_per_unit' is required on the label claim line and must be greater than zero")
    else:
        if label_claim is not None:
            invalid("'label_claim_mg_per_unit' is allowed only on the label claim line")


def create_lines(formula_id, lines_payload):
    """Discard prior FormulaLine rows and re-create from payload."""
    doomed = [lid for lid, l in store["formula_lines"].items() if l["formula_id"] == formula_id]
    for lid in doomed:
        del store["formula_lines"][lid]
    created = []
    for lp in lines_payload:
        entity = new_entity({
            "formula_id": formula_id,
            "raw_material_id": lp["raw_material_id"],
            "theoretical_qty_mg_per_unit": lp["theoretical_qty_mg_per_unit"],
            "overage_pct": lp["overage_pct"],
            "is_label_claim_line": lp["is_label_claim_line"],
            "label_claim_mg_per_unit": lp.get("label_claim_mg_per_unit"),
            "planned_weigh_qty_mg": None,
        })
        store["formula_lines"][entity["id"]] = entity
        created.append(entity)
    return created


# ---------------------------------------------------------------------------
# planned_overage_qty calculation (PRD section 3.1): rounding order pinned —
# round per-unit first (2dp half-up), then multiply by batch size, then round
# the product (2dp half-up).
# ---------------------------------------------------------------------------
def compute_planned_weigh_qty(formula, line):
    # Overage base is chosen by the formula's overage_basis. Under LABEL_CLAIM
    # the base is the line's label_claim_mg_per_unit; only the label-claim line
    # carries that value, so other lines use their theoretical quantity.
    if formula["overage_basis"] == "LABEL_CLAIM" and line.get("label_claim_mg_per_unit") is not None:
        base = dec(line["label_claim_mg_per_unit"])
    else:
        base = dec(line["theoretical_qty_mg_per_unit"])
    per_unit = round2(base * (Decimal("1") + dec(line["overage_pct"]) / Decimal("100")))
    planned = round2(per_unit * dec(formula["batch_size_units"]))
    return num_out(planned)


# ---------------------------------------------------------------------------
# yield_variance_pct calculation (PRD section 3.4): UNITS basis pinned,
# 2dp round-half-up.
# ---------------------------------------------------------------------------
def compute_yield_variance_pct(actual_yield_units, theoretical_units):
    variance = (dec(actual_yield_units) - dec(theoretical_units)) / dec(theoretical_units) * Decimal("100")
    return round2(variance)


# ---------------------------------------------------------------------------
# pct_of_claim calculation (PRD section 3.5): 1dp round-half-up.
# ---------------------------------------------------------------------------
CLAIM_MIN = Decimal("90.0")
CLAIM_MAX = Decimal("110.0")


def compute_pct_of_claim(assayed_mg_per_unit, label_claim_mg_per_unit):
    return round1(dec(assayed_mg_per_unit) / dec(label_claim_mg_per_unit) * Decimal("100"))


def pct_in_range(pct):
    return CLAIM_MIN <= dec(pct) <= CLAIM_MAX


# ---------------------------------------------------------------------------
# Recall cascade per PRD section 3.8.
# ---------------------------------------------------------------------------
def recall_batch(batch):
    """Transition one RELEASED batch to RECALLED with its side effects."""
    batch["quality_status"] = "RECALLED"
    touch(batch)
    mo = batch_mo(batch)
    if mo is not None and not mo.get("recall_flag"):
        mo["recall_flag"] = True
        touch(mo)
        refresh_customer_aggregates(mo["customer_id"])
