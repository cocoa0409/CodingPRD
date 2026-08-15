"""Business logic: calculations (PRD 3.x / scaffold 1.3) and cascades."""
from decimal import Decimal, ROUND_FLOOR

from state import (
    D, rhu, rhu_int, ApiError,
    customers, profiles, dies, lines, lots, formulations, batches,
    work_orders, assignments, runs, samples, bundles, purge_events,
    index_points, index_by_month,
    clock_month, months_inclusive, mark, stamp_new, stamp_new_lean,
    COLOR_RANK,
)

PASS_THROUGH_FACTOR = Decimal("0.85")
TOOLING_SURCHARGE_PCT = Decimal("0.10")

ERR_INDEX_MISSING = lambda msg="Resin index point missing for required month": \
    ApiError("ERR_RESIN_INDEX_MISSING", 422, msg)


# ---------------------------------------------------------------------------
# customer_open_exposure (scaffold 1.3)
# ---------------------------------------------------------------------------
def order_exposure_cents(wo):
    return rhu_int(D(wo["ordered_length_m"]) *
                   D(wo["current_unit_price_cents_per_m"]))


def compute_exposure(customer_id):
    total = 0
    for wo in work_orders.values():
        if wo["customer_id"] != customer_id:
            continue
        if wo["status"] in ("CONFIRMED", "SCHEDULED", "IN_PRODUCTION"):
            total += order_exposure_cents(wo)
    return total


def recompute_exposure(customer_id):
    """Rewrite open_exposure_cents; bump the customer only on real change."""
    cust = customers.get(customer_id)
    if cust is None:
        return
    new_val = compute_exposure(customer_id)
    if new_val != cust["open_exposure_cents"]:
        cust["open_exposure_cents"] = new_val
        mark(cust)


# ---------------------------------------------------------------------------
# resin_price_pass_through (scaffold 1.3)
# ---------------------------------------------------------------------------
def compute_pass_through(wo):
    """Return the freshly computed pass_through_adj_cents_per_m (Decimal, 2dp).
    Raises ERR_RESIN_INDEX_MISSING on any window gap."""
    cust = customers[wo["customer_id"]]
    profile = profiles[wo["profile_id"]]
    cur = clock_month()
    qm = wo["quote_month"]
    if cust["resin_index_basis"] == "MONTHLY_AVG":
        months = months_inclusive(qm, cur)
        if not months:
            months = [qm]
        vals = []
        for mth in months:
            pid = index_by_month.get(mth)
            if pid is None:
                raise ERR_INDEX_MISSING()
            vals.append(D(index_points[pid]["index_cents_per_kg"]))
        basis = rhu(sum(vals) / Decimal(len(vals)), 2)
    else:  # SHIPMENT_DATE
        pid = index_by_month.get(cur)
        if pid is None:
            raise ERR_INDEX_MISSING()
        basis = D(index_points[pid]["index_cents_per_kg"])
    adj = rhu((basis - D(wo["quote_index_cents_per_kg"]))
              * D(profile["resin_content_kg_per_m"]) * PASS_THROUGH_FACTOR, 2)
    return adj


def apply_pass_through(wo):
    """Recompute and store adj + current unit price on the order."""
    adj = compute_pass_through(wo)
    wo["pass_through_adj_cents_per_m"] = adj
    wo["current_unit_price_cents_per_m"] = D(wo["base_unit_price_cents_per_m"]) + adj
    mark(wo)
    return adj


def restate_cascade(restated_month):
    """Recompute pass-through on affected uninvoiced orders, then exposure."""
    cur = clock_month()
    affected_customers = set()
    for wo in sortable_orders():
        if wo["billing_status"] != "UNBILLED" or wo["status"] == "CANCELLED":
            continue
        cust = customers[wo["customer_id"]]
        if cust["resin_index_basis"] == "MONTHLY_AVG":
            qm = wo["quote_month"]
            referenced = months_inclusive(qm, cur) if cur >= qm else []
            if restated_month not in referenced:
                continue
        else:  # SHIPMENT_DATE
            if restated_month != cur:
                continue
        try:
            old_adj = D(wo["pass_through_adj_cents_per_m"])
            old_cur = D(wo["current_unit_price_cents_per_m"])
            adj = compute_pass_through(wo)
        except ApiError:
            # A window month without a point: restate itself never fails
            # with ERR_RESIN_INDEX_MISSING; leave the order untouched.
            continue
        new_cur = D(wo["base_unit_price_cents_per_m"]) + adj
        if adj != old_adj or new_cur != old_cur:
            wo["pass_through_adj_cents_per_m"] = adj
            wo["current_unit_price_cents_per_m"] = new_cur
            mark(wo)
        affected_customers.add(wo["customer_id"])
    for cid in affected_customers:
        recompute_exposure(cid)


def sortable_orders():
    return sorted(work_orders.values(),
                  key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Work-order close / revert checks (PRD 3.4, 3.5, 3.7)
# ---------------------------------------------------------------------------
def wo_close_check(wo):
    if wo["status"] == "IN_PRODUCTION" and \
            D(wo["produced_good_length_m"]) >= D(wo["ordered_length_m"]):
        wo["status"] = "CLOSED"
        mark(wo)
        recompute_exposure(wo["customer_id"])


def wo_revert_check(wo_id):
    """SCHEDULED -> CONFIRMED when no SCHEDULED/ACTIVE assignments remain
    and no COMPLETED runs exist."""
    wo = work_orders[wo_id]
    if wo["status"] != "SCHEDULED":
        return
    has_live = any(a["work_order_id"] == wo_id and
                   a["status"] in ("SCHEDULED", "ACTIVE")
                   for a in assignments.values())
    if has_live:
        return
    has_completed = any(
        r["status"] == "COMPLETED" and
        assignments[r["assignment_id"]]["work_order_id"] == wo_id
        for r in runs.values())
    if has_completed:
        return
    wo["status"] = "CONFIRMED"
    mark(wo)


# ---------------------------------------------------------------------------
# Hold cascade (PRD 3.6): run -> HOLD(SYSTEM), line -> DOWN,
# SCHEDULED assignments on the line -> CANCELLED, order revert checks.
# ---------------------------------------------------------------------------
def cancel_line_scheduled_assignments(line_id):
    for a in sorted(assignments.values(),
                    key=lambda e: (e["created_at"], e.get("_seq", 0))):
        if a["line_id"] == line_id and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            mark(a)
            wo_revert_check(a["work_order_id"])


def line_go_down(line):
    if line["status"] == "RUNNING":
        line["status"] = "DOWN"
        mark(line)
    cancel_line_scheduled_assignments(line["id"])


def hold_run_system(run):
    """System-origin hold: only fires from RUNNING."""
    if run["status"] != "RUNNING":
        return
    run["status"] = "HOLD"
    run["hold_origin"] = "SYSTEM"
    run["held_by_user_id"] = None
    mark(run)
    asg = assignments[run["assignment_id"]]
    line_go_down(lines[asg["line_id"]])


# ---------------------------------------------------------------------------
# Mass balance (PRD 2.9 INV-MASS): draws, credit-backs, re-applications
# ---------------------------------------------------------------------------
def _lot_after_change(lot):
    lot["available_kg"] = D(lot["received_kg"]) - D(lot["consumed_kg"])
    if lot["status"] == "QC_PASSED" and D(lot["available_kg"]) == 0:
        lot["status"] = "DEPLETED"
    elif lot["status"] == "DEPLETED" and D(lot["available_kg"]) > 0:
        lot["status"] = "QC_PASSED"


def draw_lots(batch):
    for key, field in (("virgin_lot_id", "virgin_kg"),
                       ("regrind_lot_id", "regrind_kg"),
                       ("colorant_lot_id", "colorant_kg")):
        lid = batch.get(key)
        if lid is None:
            continue
        lot = lots[lid]
        lot["consumed_kg"] = D(lot["consumed_kg"]) + D(batch[field])
        _lot_after_change(lot)
        mark(lot)


def credit_back_lots(batch):
    for key, field in (("virgin_lot_id", "virgin_kg"),
                       ("regrind_lot_id", "regrind_kg"),
                       ("colorant_lot_id", "colorant_kg")):
        lid = batch.get(key)
        if lid is None:
            continue
        lot = lots[lid]
        lot["consumed_kg"] = D(lot["consumed_kg"]) - D(batch[field])
        _lot_after_change(lot)
        mark(lot)


# ---------------------------------------------------------------------------
# blend_composition (scaffold 1.3) — pinned rounding order
# ---------------------------------------------------------------------------
def blend_composition(formulation, target_batch_kg, regrind_lot):
    T = D(target_batch_kg)
    LDR = D(formulation["let_down_ratio"])
    MAXP = D(formulation["max_regrind_pct"])
    colorant_kg = rhu(T / (1 + LDR), 1)
    base_total = T - colorant_kg
    regrind_request = rhu(base_total * MAXP / 100, 1)
    ravail = D(regrind_lot["available_kg"]) if regrind_lot else Decimal(0)
    regrind_kg = min(regrind_request, ravail)
    if regrind_kg < 0:
        regrind_kg = Decimal(0)
    virgin_kg = base_total - regrind_kg
    if base_total != 0:
        actual_pct = rhu(100 * regrind_kg / base_total, 2)
    else:
        actual_pct = Decimal("0.00")
    return colorant_kg, regrind_kg, virgin_kg, actual_pct


# ---------------------------------------------------------------------------
# purge_scrap_estimate (scaffold 1.3)
# ---------------------------------------------------------------------------
PURGE_BASE = {
    "SAME_RESIN_SAME_COLOR": Decimal("2.0"),
    "SAME_RESIN_LIGHT_TO_DARK": Decimal("4.0"),
    "SAME_RESIN_DARK_TO_LIGHT": Decimal("8.0"),
    "RESIN_CHANGE": Decimal("12.0"),
}


def purge_estimate(line, from_resin, to_resin, from_color, to_color, grade):
    if from_resin != to_resin:
        tclass = "RESIN_CHANGE"
    elif from_color == to_color:
        tclass = "SAME_RESIN_SAME_COLOR"
    elif COLOR_RANK[to_color] > COLOR_RANK[from_color]:
        tclass = "SAME_RESIN_LIGHT_TO_DARK"
    else:
        tclass = "SAME_RESIN_DARK_TO_LIGHT"
    screw = D(line["screw_diameter_mm"])
    if screw <= 45:
        factor = Decimal("1.0")
    elif screw <= 90:
        factor = Decimal("1.6")
    else:
        factor = Decimal("2.2")
    mult = Decimal("1.0") if grade == "STANDARD" else Decimal("0.7")
    scrap = rhu(PURGE_BASE[tclass] * factor * mult, 2)
    return tclass, scrap


# ---------------------------------------------------------------------------
# tooling_amortization_credit (scaffold 1.3)
# ---------------------------------------------------------------------------
def pin_amortization_rates(die):
    die["amort_rate_cents_per_m"] = rhu(
        D(die["tooling_cost_cents"]) / D(die["committed_length_m"]), 4)
    die["amort_rate_cents_per_kg"] = rhu(
        D(die["tooling_cost_cents"]) / D(die["committed_weight_kg"]), 4)


def credit_die_for_run(die, run):
    if die["amortization_mode"] == "PER_METER":
        raw = rhu(D(run["good_length_mm"]) / 1000 *
                  D(die["amort_rate_cents_per_m"]), 0)
    else:
        raw = rhu(D(run["good_weight_kg"]) *
                  D(die["amort_rate_cents_per_kg"]), 0)
    credit = int(min(D(die["remaining_balance_cents"]), raw))
    if credit < 0:
        credit = 0
    if credit:
        die["amortized_cents"] += credit
        die["remaining_balance_cents"] -= credit
        mark(die)
    return credit


# ---------------------------------------------------------------------------
# bundle_cut_plan (scaffold 1.3) — nested floor: pieces first, then bundles
# ---------------------------------------------------------------------------
def build_cut_plan(run, work_order):
    good_mm = int(run["good_length_mm"])
    cut = int(work_order["cut_length_mm"])
    ppb = int(work_order["pieces_per_bundle"])
    pieces = good_mm // cut
    full_bundles = pieces // ppb
    loose = pieces - full_bundles * ppb
    remnant = good_mm - pieces * cut
    created = []
    seq = 1
    for _ in range(full_bundles):
        created.append({"run_id": run["id"], "bundle_seq": seq,
                        "pieces": ppb, "partial": False,
                        "total_length_mm": ppb * cut})
        seq += 1
    if loose > 0:
        created.append({"run_id": run["id"], "bundle_seq": seq,
                        "pieces": loose, "partial": True,
                        "total_length_mm": loose * cut})
    return created, remnant


# ---------------------------------------------------------------------------
# spc_control_evaluation (scaffold 1.3)
# ---------------------------------------------------------------------------
def evaluate_spc(dim_spec, measurements):
    n = Decimal(len(measurements))
    xbar = rhu(sum(measurements) / n, 4)
    rng = rhu(max(measurements) - min(measurements), 4)
    ooc = (xbar > D(dim_spec["ucl_mm"])) or (xbar < D(dim_spec["lcl_mm"]))
    lo = D(dim_spec["nominal_mm"]) - D(dim_spec["tol_minus_mm"])
    hi = D(dim_spec["nominal_mm"]) + D(dim_spec["tol_plus_mm"])
    violations = sum(1 for m in measurements if m < lo or m > hi)
    return xbar, rng, ooc, violations


def spc_quota_met(run, profile):
    good_m = D(run["good_length_mm"]) / 1000
    need = int((good_m / D(profile["sample_every_m"])).to_integral_value(
        rounding=ROUND_FLOOR))
    return run["samples_posted"] >= need


# ---------------------------------------------------------------------------
# closeout_invoice_total (scaffold 1.3) — pinned evaluation order
# ---------------------------------------------------------------------------
def compute_invoice(work_order):
    billed = Decimal(0)
    for r in runs.values():
        if r["status"] != "COMPLETED":
            continue
        if assignments[r["assignment_id"]]["work_order_id"] != work_order["id"]:
            continue
        billed += D(r["good_length_mm"]) / 1000
    adj = compute_pass_through(work_order)  # may raise ERR_RESIN_INDEX_MISSING
    final_unit = D(work_order["base_unit_price_cents_per_m"]) + adj
    product_charges = rhu_int(billed * final_unit)
    die = dies[work_order["die_id"]]
    surcharge = int(min(D(die["remaining_balance_cents"]),
                        rhu(TOOLING_SURCHARGE_PCT * product_charges, 0)))
    if surcharge < 0:
        surcharge = 0
    total = product_charges + surcharge
    return billed, adj, final_unit, product_charges, surcharge, total, die
