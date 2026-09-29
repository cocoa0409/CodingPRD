"""Derived-field recomputes, the governing-test rule and the cascades."""
from decimal import Decimal

import calc
import store
from constants import MIN_CHARGE_MT, PATHWAY_SUSPENSION_STRIKES
from store import bump, q, sort_rows

ZERO = Decimal("0")
COUNTED_ALLOC = ("RESERVED", "CONSUMED")


# ---------------------------------------------------------------------------
# Simple selectors
# ---------------------------------------------------------------------------
def lot_allocations(lot_id):
    return sort_rows([a for a in store.allocations.values() if a["lot_id"] == lot_id])


def run_allocations(run_id):
    return sort_rows([a for a in store.allocations.values() if a["run_id"] == run_id])


def run_nominations(run_id):
    return sort_rows([n for n in store.nominations.values() if n["run_id"] == run_id])


def contract_nominations(contract_id):
    return sort_rows([n for n in store.nominations.values()
                      if n["contract_id"] == contract_id])


def supplier_lots(supplier_id):
    return sort_rows([l for l in store.lots.values() if l["supplier_id"] == supplier_id])


def lot_tests(lot_id):
    return sort_rows([t for t in store.tests.values() if t["lot_id"] == lot_id])


def supplier_documents(supplier_id):
    return sort_rows([d for d in store.documents.values()
                      if d["supplier_id"] == supplier_id])


def unit_windows(unit_id):
    return sort_rows([w for w in store.windows.values() if w["unit_id"] == unit_id])


def unit_runs(unit_id):
    return sort_rows([r for r in store.runs.values() if r["unit_id"] == unit_id])


def unit_charges(unit_id):
    return sort_rows([c for c in store.charges.values() if c["unit_id"] == unit_id])


def charge_runs(charge_id):
    return sort_rows([r for r in store.runs.values()
                      if r["catalyst_charge_id"] == charge_id])


def pathway_blocks(pathway_id):
    return sort_rows([b for b in store.blocks.values() if b["pathway_id"] == pathway_id])


def counted_lines(run_id, statuses=COUNTED_ALLOC):
    out = []
    for alloc in run_allocations(run_id):
        if alloc["status"] in statuses:
            lot = store.lots.get(alloc["lot_id"])
            if lot is not None:
                out.append((alloc["mass_mt"], lot))
    return out


# ---------------------------------------------------------------------------
# Supplier due diligence
# ---------------------------------------------------------------------------
def recompute_dd_document_type_count(supplier):
    clock = store.now()
    kinds = set()
    for doc in supplier_documents(supplier["id"]):
        if doc["valid_until"] > clock:
            kinds.add(doc["doc_type"])
    supplier["dd_document_type_count"] = len(kinds)
    return supplier["dd_document_type_count"]


def valid_doc_types(supplier):
    clock = store.now()
    return {d["doc_type"] for d in supplier_documents(supplier["id"])
            if d["valid_until"] > clock}


# ---------------------------------------------------------------------------
# Feedstock lots
# ---------------------------------------------------------------------------
def recompute_lot_masses(lot):
    allocated = ZERO
    for alloc in lot_allocations(lot["id"]):
        if alloc["status"] in COUNTED_ALLOC:
            allocated += alloc["mass_mt"]
    lot["allocated_mass_mt"] = q(allocated, 3)
    if lot["status"] == "REJECTED":
        lot["remaining_mass_mt"] = q(ZERO, 3)
        return
    remaining = lot["mass_mt"] - lot["allocated_mass_mt"] - lot["pretreatment_consumed_mt"]
    lot["remaining_mass_mt"] = q(remaining, 3)


def governing_test(lot_id):
    candidates = lot_tests(lot_id)
    if not candidates:
        return None
    best = None
    for test in candidates:
        if best is None:
            best = test
            continue
        if test["sampled_at"] > best["sampled_at"]:
            best = test
        elif test["sampled_at"] == best["sampled_at"]:
            if (test["_created"], test["_seq"]) >= (best["_created"], best["_seq"]):
                best = test
    return best


def apply_governing_test(lot):
    """Set lot status / tier / fee from the governing test."""
    test = governing_test(lot["id"])
    if test is None:
        lot["pretreatment_tier"] = "NONE"
        lot["pretreatment_fee_usd"] = q(ZERO, 2)
        return
    disposition = test["disposition"]
    if disposition == "PASS":
        lot["status"] = "TESTED"
        lot["pretreatment_tier"] = "NONE"
        lot["pretreatment_fee_usd"] = q(ZERO, 2)
    elif disposition == "PRETREAT":
        lot["status"] = "PRETREAT_REQUIRED"
        lot["pretreatment_tier"] = test["tier"]
        lot["pretreatment_fee_usd"] = test["_fee"]
    else:
        lot["status"] = "REJECTED"
        lot["pretreatment_tier"] = "HEAVY"
        lot["pretreatment_fee_usd"] = q(ZERO, 2)
    recompute_lot_masses(lot)


# ---------------------------------------------------------------------------
# Processing runs
# ---------------------------------------------------------------------------
def recompute_run_masses(run):
    reserved = ZERO
    consumed = ZERO
    for alloc in run_allocations(run["id"]):
        if alloc["status"] == "RESERVED":
            reserved += alloc["mass_mt"]
        elif alloc["status"] == "CONSUMED":
            consumed += alloc["mass_mt"]
    run["reserved_mass_mt"] = q(reserved, 3)
    run["consumed_mass_mt"] = q(consumed, 3)


def recompute_run_blend(run):
    lines = counted_lines(run["id"])
    run["blend_ci_gco2e_per_mj"] = calc.blend_carbon_intensity(lines)
    run["required_h2_kg_per_day"] = calc.hydrogen_requirement(
        lines, run["run_days"], run["target_saf_share_pct"])


def run_window_dates(run):
    """The campaign window is half-open, so window_end's own date is excluded."""
    dates = []
    cur = run["window_start"].date()
    while store.start_of_day(cur) < run["window_end"]:
        dates.append(cur)
        cur = cur + store.timedelta(days=1)
    return dates


def nomination_covers(nom, day):
    return (nom["start_at"] <= store.end_of_day(day)
            and nom["end_at"] >= store.start_of_day(day))


def hydrogen_coverage_ok(run):
    required = run["required_h2_kg_per_day"]
    if required is None:
        return False
    noms = [n for n in run_nominations(run["id"]) if n["status"] == "CONFIRMED"]
    for day in run_window_dates(run):
        total = ZERO
        for nom in noms:
            if nomination_covers(nom, day):
                total += nom["kg_per_day"]
        if total < required:
            return False
    return True


def reset_planned_figures(run):
    run["provisional_yield_pct"] = q(ZERO, 3)
    run["planned_total_product_mt"] = q(ZERO, 3)
    run["planned_rd_mt"] = q(ZERO, 3)
    run["planned_saf_mt"] = q(ZERO, 3)


def downgrade_run(run, cancel_nominations):
    run["status"] = "PLANNED"
    reset_planned_figures(run)
    bump(run)
    if cancel_nominations:
        cancel_run_nominations(run)


def cancel_run_nominations(run):
    touched_contracts = []
    for nom in run_nominations(run["id"]):
        if nom["status"] != "CONFIRMED":
            continue
        nom["status"] = "CANCELLED"
        bump(nom)
        contract = store.contracts.get(nom["contract_id"])
        if contract is not None and contract not in touched_contracts:
            touched_contracts.append(contract)
    for contract in touched_contracts:
        recompute_contract_peak(contract)
        bump(contract)


def dominant_feedstock(run):
    totals = {}
    order = {}
    index = 0
    for alloc in run_allocations(run["id"]):
        if alloc["status"] != "CONSUMED":
            continue
        lot = store.lots.get(alloc["lot_id"])
        if lot is None:
            continue
        kind = lot["feedstock_type"]
        totals[kind] = totals.get(kind, ZERO) + alloc["mass_mt"]
        if kind not in order:
            order[kind] = index
            index += 1
    if not totals:
        return None
    best = None
    for kind, mass in totals.items():
        if best is None:
            best = kind
            continue
        if mass > totals[best] or (mass == totals[best] and order[kind] < order[best]):
            best = kind
    return best


# ---------------------------------------------------------------------------
# Hydrogen contracts
# ---------------------------------------------------------------------------
def committed_on_day(contract_id, day, exclude_id=None):
    total = ZERO
    for nom in contract_nominations(contract_id):
        if nom["status"] != "CONFIRMED":
            continue
        if exclude_id is not None and nom["id"] == exclude_id:
            continue
        if nomination_covers(nom, day):
            total += nom["kg_per_day"]
    return total


def recompute_contract_peak(contract):
    days = store.date_range(contract["window_start"].date(),
                            contract["window_end"].date())
    peak = ZERO
    for day in days:
        total = committed_on_day(contract["id"], day)
        if total > peak:
            peak = total
    contract["peak_committed_kg_per_day"] = q(peak, 1)


# ---------------------------------------------------------------------------
# Catalyst charges
# ---------------------------------------------------------------------------
def recompute_charge(charge):
    total = ZERO
    for run in charge_runs(charge["id"]):
        if run["status"] in ("COMPLETED", "RECONCILED"):
            total += run["consumed_mass_mt"]
    charge["cumulative_throughput_mt"] = q(total, 3)
    charge["activity_index"] = calc.catalyst_activity_index(
        charge["cumulative_throughput_mt"])


# ---------------------------------------------------------------------------
# Pathways / credit blocks
# ---------------------------------------------------------------------------
def recompute_pathway_credits(pathway):
    total = ZERO
    for block in pathway_blocks(pathway["id"]):
        if block["status"] in ("VERIFIED", "ADJUSTED", "RETIRED"):
            total += block["verified_credits_mtco2e"] - block["retired_credits_mtco2e"]
    pathway["credits_outstanding_mtco2e"] = q(total, 3)


def adjusted_cascade(block, pathway):
    """Levels 2-4 of the ADJUSTED verification cascade."""
    pathway["variance_strikes"] = pathway["variance_strikes"] + 1
    bump(pathway)
    if pathway["variance_strikes"] >= PATHWAY_SUSPENSION_STRIKES \
            and pathway["status"] == "REGISTERED":
        pathway["status"] = "SUSPENDED"
        pathway["_updated"] = store.now()
        pathway["version"] = pathway["version"] + 1
        for sibling in pathway_blocks(pathway["id"]):
            if sibling["id"] == block["id"]:
                continue
            if sibling["status"] in ("DRAFT", "INTERNAL_SIGNED_OFF"):
                sibling["status"] = "BLOCKED"
                bump(sibling)


# ---------------------------------------------------------------------------
# Allocation release (shared by manual release, suspension and abort)
# ---------------------------------------------------------------------------
def release_allocation(alloc, reason):
    alloc["status"] = "RELEASED"
    alloc["release_reason"] = reason
    bump(alloc)
    lot = store.lots.get(alloc["lot_id"])
    if lot is not None:
        recompute_lot_masses(lot)
        bump(lot)


# ---------------------------------------------------------------------------
# Cascade A — supplier suspension (five levels)
# ---------------------------------------------------------------------------
QUARANTINABLE = ("RECEIVED", "TESTED", "PRETREAT_REQUIRED", "PRETREATED", "ACCEPTED")


def suspend_supplier_cascade(supplier, reason):
    # Level 1
    supplier["dd_status"] = "SUSPENDED"
    supplier["suspension_reason"] = reason
    bump(supplier)

    # Level 2
    quarantined = []
    for lot in supplier_lots(supplier["id"]):
        if lot["status"] in QUARANTINABLE:
            lot["status"] = "QUARANTINED"
            bump(lot)
            quarantined.append(lot)

    # Level 3
    affected_runs = []
    for lot in quarantined:
        for alloc in lot_allocations(lot["id"]):
            if alloc["status"] != "RESERVED":
                continue
            release_allocation(alloc, "SUPPLIER_SUSPENDED")
            run = store.runs.get(alloc["run_id"])
            if run is not None and run not in affected_runs:
                affected_runs.append(run)

    # Level 4
    for run in sort_rows(affected_runs):
        was_secured = run["status"] == "HYDROGEN_SECURED"
        recompute_run_masses(run)
        recompute_run_blend(run)
        bump(run)
        if was_secured and run["reserved_mass_mt"] < MIN_CHARGE_MT:
            run["status"] = "PLANNED"
            reset_planned_figures(run)
            # Level 5
            cancel_run_nominations(run)
