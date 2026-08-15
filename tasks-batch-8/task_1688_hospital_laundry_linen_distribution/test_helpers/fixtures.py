"""Composite setup helpers.

Every test runs against an empty database (the runner restarts the server
before each test), so each helper builds its preconditions from scratch using
only endpoints the PRD declares. Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing assertion failure later.

Most helpers return or extend a plain `ctx` dict so tests can pick out the
entities they need: facility, unit, stock, par, runs, manifests, invoices.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    PERIOD_ADJUSTED_PATIENT_DAYS,
    PERIOD_END,
    PERIOD_START,
    TEST_DEFAULTS,
    TIME_COLLECT_END,
    TIME_COLLECT_START,
    TIME_FILL_END,
    TIME_FILL_START,
)
from .factories import (
    complete_cart_run_payload,
    create_cart_run_payload,
    create_complaint_payload,
    create_facility_payload,
    create_invoice_payload,
    create_linen_stock_payload,
    create_par_level_payload,
    create_soiled_manifest_payload,
    create_surge_event_payload,
    create_unit_payload,
    recount_cart_run_payload,
    return_manifest_payload,
    set_clock_payload,
    stock_adjustment_payload,
)
from .test_users import (
    TEST_USERS,
    make_unit_clerk_headers,
)

LM = TEST_USERS["linen_manager_headers"]          # lm-1
LM2 = TEST_USERS["linen_manager_2_headers"]       # lm-2 (finalize / segregation)
EVS = TEST_USERS["evs_operator_headers"]          # evs-1
VENDOR = TEST_USERS["laundry_vendor_headers"]     # ven-1
ICO = TEST_USERS["infection_control_officer_headers"]  # ico-1


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (LinenManager only, PRD 2.5)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), LM))


def create_facility(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), LM)
    )


def create_unit(facility_id: str, name: str = "ICU", unit_tier: str = "CRITICAL") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(facility_id, name=name, unit_tier=unit_tier), LM
        )
    )


def create_stock(facility_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_linen_stock(
            create_linen_stock_payload(facility_id, **overrides), LM
        )
    )


def create_gown_stock(facility_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "sku": TEST_DEFAULTS["GOWN_SKU"],
        "display_name": TEST_DEFAULTS["GOWN_NAME"],
        "category": "ISOLATION",
        "piece_weight_lbs": TEST_DEFAULTS["GOWN_WEIGHT_LBS"],
        "unit_cost_cents": TEST_DEFAULTS["GOWN_UNIT_COST_CENTS"],
        "max_wash_cycles": TEST_DEFAULTS["GOWN_MAX_WASH_CYCLES"],
        "reorder_point_pieces": TEST_DEFAULTS["GOWN_REORDER_POINT"],
        "opening_pieces": TEST_DEFAULTS["GOWN_OPENING_PIECES"],
        "opening_reserve_pieces": TEST_DEFAULTS["GOWN_OPENING_RESERVE"],
    }
    defaults.update(overrides)
    return create_stock(facility_id, **defaults)


def create_towel_stock(facility_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "sku": TEST_DEFAULTS["TOWEL_SKU"],
        "display_name": TEST_DEFAULTS["TOWEL_NAME"],
        "category": "TERRY",
        "piece_weight_lbs": TEST_DEFAULTS["TOWEL_WEIGHT_LBS"],
        "unit_cost_cents": TEST_DEFAULTS["TOWEL_UNIT_COST_CENTS"],
        "max_wash_cycles": TEST_DEFAULTS["TOWEL_MAX_WASH_CYCLES"],
        "reorder_point_pieces": TEST_DEFAULTS["TOWEL_REORDER_POINT"],
        "opening_pieces": TEST_DEFAULTS["TOWEL_OPENING_PIECES"],
        "opening_reserve_pieces": TEST_DEFAULTS["TOWEL_OPENING_RESERVE"],
    }
    defaults.update(overrides)
    return create_stock(facility_id, **defaults)


def create_par(unit_id: str, stock_id: str, base_par_quantity: int = 20,
               cart_cycle: str = "DAILY") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_par_level(
            create_par_level_payload(
                unit_id, stock_id,
                base_par_quantity=base_par_quantity, cart_cycle=cart_cycle,
            ),
            LM,
        )
    )


def schedule_run(unit_id: str, start: str, end: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_cart_run(
            create_cart_run_payload(
                unit_id, scheduled_start=start, scheduled_end=end
            ),
            EVS,
        )
    )


def complete_run(run_id: str, soiled_lines: Optional[List[Dict[str, Any]]] = None,
                 storage_attested: bool = True) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_cart_run(
            run_id,
            complete_cart_run_payload(
                soiled_lines=soiled_lines, storage_attested=storage_attested
            ),
            EVS,
        )
    )


def dispute_run(run_id: str, unit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispute_cart_run(run_id, {}, make_unit_clerk_headers(unit_id))
    )


def recount_run(run_id: str, unit_id: str,
                corrected_soiled_lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    return get_success_data(
        api_client.recount_cart_run(
            run_id,
            recount_cart_run_payload(corrected_soiled_lines),
            make_unit_clerk_headers(unit_id),
        )
    )


def reconcile_run(run_id: str, unit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reconcile_cart_run(run_id, make_unit_clerk_headers(unit_id))
    )


def create_manifest(facility_id: str, cart_run_ids: List[str],
                    lines: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_soiled_manifest(
            create_soiled_manifest_payload(facility_id, cart_run_ids, lines, **overrides),
            EVS,
        )
    )


def return_manifest(manifest_id: str,
                    returned_lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    return get_success_data(
        api_client.return_soiled_manifest(
            manifest_id, return_manifest_payload(returned_lines), VENDOR
        )
    )


def reconcile_manifest(manifest_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reconcile_soiled_manifest(manifest_id, LM))


def create_invoice(facility_id: str, manifest_ids: List[str],
                   **overrides) -> Dict[str, Any]:
    """Created by lm-1; finalization must use a different manager (PRD 3.6)."""
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(facility_id, manifest_ids, **overrides), LM
        )
    )


def finalize_invoice(invoice_id: str) -> Dict[str, Any]:
    """Finalized by lm-2, a different manager than creator lm-1."""
    return get_success_data(api_client.finalize_invoice(invoice_id, LM2))


def create_complaint(unit_id: str, manifest_id: str, stock_id: str,
                     **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(unit_id, manifest_id, stock_id, **overrides),
            make_unit_clerk_headers(unit_id),
        )
    )


def create_surge(facility_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_surge_event(
            create_surge_event_payload(facility_id, **overrides), LM
        )
    )


def read_par(par_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_par_level(par_id, LM))


def read_stock(stock_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_linen_stock(stock_id, LM))


def read_facility(facility_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_facility(facility_id, LM))


def read_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_cart_run(run_id, LM))


def read_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(invoice_id, LM))


def read_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_complaint(complaint_id, LM))


def read_surge(surge_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_surge_event(surge_id, LM))


def read_unit(unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_unit(unit_id, LM))


def adjust_stock(stock_id: str, delta_pieces: int, expected_version: int,
                 reason: str = "FOUND") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_stock_adjustment(
            stock_id,
            stock_adjustment_payload(
                delta_pieces, expected_version, reason=reason
            ),
            LM,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2 — base scenario and cart-run lifecycle
# ---------------------------------------------------------------------------


def base_scenario(unit_name: str = "ICU", unit_tier: str = "CRITICAL",
                  par_quantity: int = 20, cart_cycle: str = "DAILY",
                  facility_overrides: Optional[Dict[str, Any]] = None,
                  stock_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Facility + one unit + one sheet stock + one par level.

    Returns ctx with keys: facility, unit, stock, par.
    """
    facility = create_facility(**(facility_overrides or {}))
    unit = create_unit(facility["id"], name=unit_name, unit_tier=unit_tier)
    stock = create_stock(facility["id"], **(stock_overrides or {}))
    par = create_par(unit["id"], stock["id"], par_quantity, cart_cycle)
    return {"facility": facility, "unit": unit, "stock": stock, "par": par}


def fill_unit_to_par(ctx: Dict[str, Any], start: str = TIME_FILL_START,
                     end: str = TIME_FILL_END, reconcile: bool = True) -> Dict[str, Any]:
    """Run an empty-soiled completion that restocks the unit to effective par.

    Sets the logical clock to the window start first so completed_at lands
    inside the window (no lateness). Returns the run.
    """
    set_clock(start)
    run = schedule_run(ctx["unit"]["id"], start, end)
    run = complete_run(run["id"], soiled_lines=[])
    if reconcile:
        run = reconcile_run(run["id"], ctx["unit"]["id"])
    return run


def collect_soiled(ctx: Dict[str, Any], soiled_lines: List[Dict[str, Any]],
                   start: str = TIME_COLLECT_START,
                   end: str = TIME_COLLECT_END,
                   reconcile: bool = True) -> Dict[str, Any]:
    """Schedule + complete (+ optionally reconcile) a collection run."""
    run = schedule_run(ctx["unit"]["id"], start, end)
    run = complete_run(run["id"], soiled_lines=soiled_lines)
    if reconcile:
        run = reconcile_run(run["id"], ctx["unit"]["id"])
    return run


def setup_unit_with_collection(soiled_pieces: int = 8, reconcile: bool = True,
                               **kwargs) -> Dict[str, Any]:
    """Base scenario + fill run (reconciled) + collection run.

    After this fixture the unit is back at par and `soiled_pieces` of the
    sheet stock sit in the stock's in_wash counter. Pass ``reconcile=False``
    to leave the collection run in COMPLETED so dispute/recount flows can
    act on it. Adds keys: fill_run, collect_run.
    """
    ctx = base_scenario(**kwargs)
    ctx["fill_run"] = fill_unit_to_par(ctx)
    ctx["collect_run"] = collect_soiled(
        ctx, [{"stock_id": ctx["stock"]["id"], "pieces": soiled_pieces}],
        reconcile=reconcile,
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — manifest lifecycle shortcuts
# ---------------------------------------------------------------------------


def make_manifest(ctx: Dict[str, Any], cart_run_ids: List[str],
                  weight_lbs: float = 16.00, isolation: bool = False,
                  stock: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a DISPATCHED manifest over the given runs with one line."""
    stock = stock or ctx["stock"]
    overrides: Dict[str, Any] = {}
    if isolation:
        overrides["isolation_protocol_ack"] = True
    return create_manifest(
        ctx["facility"]["id"],
        cart_run_ids,
        [{"stock_id": stock["id"], "weight_lbs": weight_lbs,
          "isolation_flag": isolation}],
        **overrides,
    )


def setup_returned_manifest(soiled_pieces: int = 8, weight_lbs: float = 16.00,
                            returned_pieces: int = 7, condemned: int = 0,
                            **kwargs) -> Dict[str, Any]:
    """Collection scenario + manifest + vendor return (status RETURNED).

    Default numbers: 16.00 lbs of 2.00 lb sheets -> 8 expected pieces,
    matching the 8 collected; 7 returned clean. Adds key: manifest.
    """
    ctx = setup_unit_with_collection(soiled_pieces=soiled_pieces, **kwargs)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], weight_lbs)
    ctx["manifest"] = return_manifest(
        manifest["id"],
        [{"stock_id": ctx["stock"]["id"], "pieces": returned_pieces,
          "condemned_pieces": condemned}],
    )
    return ctx


def setup_reconciled_manifest(soiled_pieces: int = 8, weight_lbs: float = 16.00,
                              returned_pieces: int = 7, condemned: int = 0,
                              **kwargs) -> Dict[str, Any]:
    """Like setup_returned_manifest, then reconciled by the LinenManager."""
    ctx = setup_returned_manifest(
        soiled_pieces=soiled_pieces, weight_lbs=weight_lbs,
        returned_pieces=returned_pieces, condemned=condemned, **kwargs,
    )
    ctx["manifest"] = reconcile_manifest(ctx["manifest"]["id"])
    return ctx


def setup_provisional_invoice(**kwargs) -> Dict[str, Any]:
    """Reconciled manifest + PROVISIONAL invoice over it (created by lm-1).

    Adds key: invoice.
    """
    ctx = setup_reconciled_manifest(**kwargs)
    ctx["invoice"] = create_invoice(
        ctx["facility"]["id"], [ctx["manifest"]["id"]],
        period_start=PERIOD_START, period_end=PERIOD_END,
        period_adjusted_patient_days=PERIOD_ADJUSTED_PATIENT_DAYS,
    )
    return ctx


def setup_finalized_invoice(**kwargs) -> Dict[str, Any]:
    """Provisional invoice finalized by lm-2 (segregation-safe)."""
    ctx = setup_provisional_invoice(**kwargs)
    ctx["invoice"] = finalize_invoice(ctx["invoice"]["id"])
    return ctx
