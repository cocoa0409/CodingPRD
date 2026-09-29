"""Composite setup helpers.

The harness restarts the server before every test, so each test starts against
an empty database and must build all of its state through the API. These
helpers are the shared vocabulary for doing that: each one drives real
endpoints, validates every step with ``get_success_data`` so a broken setup
fails loudly, and returns the resulting rows.

They are ordinary functions rather than pytest fixtures so that a test can call
them more than once, with different arguments, in the same body.

Five tiers are provided:

1. Single-step primitives (``create_raw_material``, ``create_press_line``, ...).
2. Entity-hierarchy builders (``build_approved_formulation``, ``build_sku``).
3. Lifecycle shortcuts (``build_certified_sku``, ``build_stock_batch``).
4. Accumulation / threshold targeting (``build_filled_allocation``,
   ``run_to_completion``).
5. Terminal-state shortcuts (``build_adjudication_ready_claim``).

The canonical figures produced by the tier-3 helpers are documented on each
function so a test can assert against them without re-deriving them.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    FORMULATOR,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    distributor_headers,
)

# ---------------------------------------------------------------------------
# Tier 1 -- single-step primitives.
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock (PRD 2.4; PlantAdmin only)."""
    return get_success_data(
        api.set_clock(f.clock_payload(current_utc), PLANT_ADMIN)
    )


def create_distributor(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_distributor(f.distributor_payload(**overrides), PLANT_ADMIN)
    )


def create_raw_material(
    api: ApiClient, code: str = "RM-RESIN", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_raw_material(f.raw_material_payload(code, **overrides), PLANT_ADMIN)
    )


def seed_materials(api: ApiClient, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Register several reference materials, keyed by ``material_code``."""
    return {code: create_raw_material(api, code) for code in codes}


def set_material_status(
    api: ApiClient, material_id: str, to_status: str
) -> Dict[str, Any]:
    return get_success_data(
        api.set_raw_material_status(
            material_id, f.raw_material_status_payload(to_status), PLANT_ADMIN
        )
    )


def revalue_material(
    api: ApiClient, material_id: str, cost_per_kg_cents: int
) -> Dict[str, Any]:
    return get_success_data(
        api.set_raw_material_cost(
            material_id, f.raw_material_cost_payload(cost_per_kg_cents), PLANT_ADMIN
        )
    )


def create_formulation(
    api: ApiClient, code: str = "F-MIN", headers: Dict[str, str] = FORMULATOR, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_formulation(f.formulation_payload(code, **overrides), headers)
    )


def add_component(
    api: ApiClient,
    formulation_id: str,
    raw_material_id: str,
    phr: float,
    headers: Dict[str, str] = FORMULATOR,
) -> Dict[str, Any]:
    return get_success_data(
        api.add_formulation_component(
            formulation_id, f.component_payload(raw_material_id, phr), headers
        )
    )


def submit_formulation(
    api: ApiClient, formulation_id: str, headers: Dict[str, str] = FORMULATOR
) -> Dict[str, Any]:
    return get_success_data(api.submit_formulation(formulation_id, headers))


def review_formulation(
    api: ApiClient,
    formulation_id: str,
    decision: str,
    headers: Dict[str, str] = TECHNICAL_DIRECTOR,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_formulation(
            formulation_id, f.review_decision_payload(decision, **overrides), headers
        )
    )


def create_license(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_design_license(f.design_license_payload(**overrides), PLANT_ADMIN)
    )


def create_print_film(api: ApiClient, license_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_print_film(f.print_film_payload(license_id, **overrides), PLANT_ADMIN)
    )


def set_film_status(api: ApiClient, film_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_print_film_status(
            film_id, f.print_film_status_payload(to_status), PLANT_ADMIN
        )
    )


def set_license_status(
    api: ApiClient,
    license_id: str,
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive a grant's status.

    PRD 2.1 splits the authority on this endpoint by requested value:
    ``TERMINATED`` is reserved to TechnicalDirector while ``ACTIVE`` and
    ``SUSPENDED`` are reserved to PlantAdmin, so the caller defaults to
    whichever role the requested value belongs to.
    """
    if headers is None:
        headers = TECHNICAL_DIRECTOR if to_status == "TERMINATED" else PLANT_ADMIN
    return get_success_data(
        api.set_license_status(license_id, f.license_status_payload(to_status), headers)
    )


def create_press_line(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_press_line(f.press_line_payload(**overrides), PLANT_ADMIN)
    )


def set_press_line_status(
    api: ApiClient, line_id: str, to_status: str
) -> Dict[str, Any]:
    return get_success_data(
        api.set_press_line_status(
            line_id, f.press_line_status_payload(to_status), PLANT_ADMIN
        )
    )


def create_sku(
    api: ApiClient, formulation_id: str, print_film_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_product_sku(
            f.product_sku_payload(formulation_id, print_film_id, **overrides),
            PLANT_ADMIN,
        )
    )


def create_click_lock_sku(
    api: ApiClient, formulation_id: str, print_film_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_product_sku(
            f.click_lock_sku_payload(formulation_id, print_film_id, **overrides),
            PLANT_ADMIN,
        )
    )


def begin_testing(api: ApiClient, sku_id: str) -> Dict[str, Any]:
    return get_success_data(api.begin_sku_testing(sku_id, QA_TECHNICIAN))


def certify_sku(
    api: ApiClient, sku_id: str, headers: Dict[str, str] = TECHNICAL_DIRECTOR
) -> Dict[str, Any]:
    return get_success_data(api.certify_sku(sku_id, headers))


def set_commercial_status(api: ApiClient, sku_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_sku_commercial_status(
            sku_id, f.commercial_status_payload(to_status), PLANT_ADMIN
        )
    )


def create_panel(
    api: ApiClient,
    sku_id: str,
    panel_code: str = "TP-A1",
    headers: Dict[str, str] = QA_TECHNICIAN,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_test_panel(f.test_panel_payload(sku_id, panel_code), headers)
    )


def start_panel(
    api: ApiClient, panel_id: str, headers: Dict[str, str] = QA_TECHNICIAN
) -> Dict[str, Any]:
    return get_success_data(api.start_test_panel(panel_id, headers))


def record_result(
    api: ApiClient,
    panel_id: str,
    test_type: str,
    measured_value: float,
    headers: Dict[str, str] = QA_TECHNICIAN,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_test_result(
            panel_id, f.test_result_payload(test_type, measured_value), headers
        )
    )


def create_run(
    api: ApiClient, sku_id: str, press_line_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_production_run(
            f.production_run_payload(sku_id, press_line_id, **overrides),
            PRODUCTION_PLANNER,
        )
    )


def setup_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.setup_production_run(run_id, PRODUCTION_PLANNER))


def start_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_production_run(run_id, PRODUCTION_PLANNER))


def complete_run(
    api: ApiClient, run_id: str, actual_quantity_sqm: float = 1200.00, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_production_run(
            run_id,
            f.run_completion_payload(actual_quantity_sqm, **overrides),
            PRODUCTION_PLANNER,
        )
    )


def abort_run(api: ApiClient, run_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.abort_production_run(
            run_id, f.run_abort_payload(**overrides), PRODUCTION_PLANNER
        )
    )


def set_qc_disposition(
    api: ApiClient,
    run_id: str,
    to_disposition: str,
    headers: Dict[str, str] = QA_TECHNICIAN,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.set_run_qc_disposition(
            run_id, f.qc_disposition_payload(to_disposition, **overrides), headers
        )
    )


def set_batch_hold(
    api: ApiClient,
    batch_id: str,
    action: str,
    headers: Dict[str, str] = QA_TECHNICIAN,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.set_batch_hold_status(
            batch_id, f.hold_status_payload(action, **overrides), headers
        )
    )


def batch_of_run(api: ApiClient, run_id: str, headers=QA_TECHNICIAN) -> Dict[str, Any]:
    """Read back the single batch minted by a completed run (PRD 3.7)."""
    payload = api.list_batches(headers, params={"production_run_id": run_id}).json()
    rows = payload.get("data") or []
    matching = [row for row in rows if row.get("production_run_id") == run_id]
    if not matching:
        # The filter may not be supported for this field; fall back to a scan.
        payload = api.list_batches(headers, params={"limit": 100}).json()
        matching = [
            row
            for row in (payload.get("data") or [])
            if row.get("production_run_id") == run_id
        ]
    assert matching, f"no batch was minted for run {run_id}"
    assert len(matching) == 1, f"expected exactly one batch for run {run_id}"
    return matching[0]


def create_allocation(
    api: ApiClient,
    distributor_id: str,
    sku_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_allocation(
            f.allocation_payload(distributor_id, sku_id, **overrides),
            headers if headers is not None else distributor_headers(distributor_id),
        )
    )


def fill_allocation(
    api: ApiClient,
    allocation_id: str,
    distributor_id: str,
    expected_allocation_version: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.fill_allocation(
            allocation_id,
            f.fill_payload(expected_allocation_version),
            distributor_headers(distributor_id),
        )
    )


def release_allocation(
    api: ApiClient, allocation_id: str, distributor_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.release_allocation(allocation_id, distributor_headers(distributor_id))
    )


def create_claim(
    api: ApiClient,
    batch_id: str,
    distributor_id: str,
    headers: Dict[str, str] = WARRANTY_ADJUSTER,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_warranty_claim(
            f.warranty_claim_payload(batch_id, distributor_id, **overrides), headers
        )
    )


def triage_claim(
    api: ApiClient, claim_id: str, headers: Dict[str, str] = WARRANTY_ADJUSTER
) -> Dict[str, Any]:
    return get_success_data(api.triage_warranty_claim(claim_id, headers))


def record_review(
    api: ApiClient,
    claim_id: str,
    review_kind: str,
    outcome: str,
    headers: Dict[str, str] = WARRANTY_ADJUSTER,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_claim_review(
            claim_id, f.claim_review_payload(review_kind, outcome, **overrides), headers
        )
    )


def adjudicate_claim(
    api: ApiClient,
    claim_id: str,
    decision: str,
    headers: Dict[str, str] = WARRANTY_ADJUSTER_B,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_warranty_claim(
            claim_id, f.adjudication_payload(decision, **overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 -- entity-hierarchy builders.
# ---------------------------------------------------------------------------

# Component recipes as (material_code, phr) pairs.
F_MIN_COMPONENTS: Sequence[Tuple[str, float]] = (("RM-RESIN", 100), ("RM-STAB", 3))
F_STD_COMPONENTS: Sequence[Tuple[str, float]] = (
    ("RM-RESIN", 100),
    ("RM-SOFT", 25),
    ("RM-FILLER", 40),
)
F_CHALK_COMPONENTS: Sequence[Tuple[str, float]] = (
    ("RM-RESIN", 100),
    ("RM-CACO3", 200),
)


def build_draft_formulation(
    api: ApiClient,
    code: str = "F-MIN",
    components: Sequence[Tuple[str, float]] = F_MIN_COMPONENTS,
    materials: Optional[Dict[str, Dict[str, Any]]] = None,
    headers: Dict[str, str] = FORMULATOR,
) -> Dict[str, Any]:
    """Register any missing materials and dose them into a DRAFT recipe.

    Returns ``{"materials": {code: row}, "formulation": row,
    "components": [row]}`` with ``formulation`` re-read after the last dosage so
    its derived blend figures are current.
    """
    materials = dict(materials or {})
    for material_code, _ in components:
        if material_code not in materials:
            materials[material_code] = create_raw_material(api, material_code)
    formulation = create_formulation(api, code, headers)
    component_rows: List[Dict[str, Any]] = []
    for material_code, phr in components:
        component_rows.append(
            add_component(
                api, formulation["id"], materials[material_code]["id"], phr, headers
            )
        )
    formulation = get_success_data(api.get_formulation(formulation["id"], headers))
    return {
        "materials": materials,
        "formulation": formulation,
        "components": component_rows,
    }


def build_approved_formulation(
    api: ApiClient,
    code: str = "F-MIN",
    components: Sequence[Tuple[str, float]] = F_MIN_COMPONENTS,
    materials: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Author, submit and approve a recipe.

    With the default ``F_MIN_COMPONENTS`` the approved recipe carries
    ``total_phr`` 103.00, ``blended_cost_per_kg_cents`` 201,
    ``performance_score`` 89.28 and ``indentation_resistance_class``
    ``CLASS_34_43``.
    """
    built = build_draft_formulation(api, code, components, materials)
    submit_formulation(api, built["formulation"]["id"])
    built["formulation"] = review_formulation(
        api, built["formulation"]["id"], "APPROVE"
    )
    return built


def build_licensed_film(api: ApiClient, **film_overrides) -> Dict[str, Any]:
    """An ACTIVE grant plus one AVAILABLE film on it."""
    license_row = create_license(api)
    film = create_print_film(api, license_row["id"], **film_overrides)
    return {"license": license_row, "film": film}


def build_sku(
    api: ApiClient,
    formulation_components: Sequence[Tuple[str, float]] = F_MIN_COMPONENTS,
    formulation_code: str = "F-MIN",
    **sku_overrides,
) -> Dict[str, Any]:
    """An APPROVED recipe, an ACTIVE grant, an AVAILABLE film and an UNCERTIFIED SKU.

    Returns ``{"materials", "formulation", "components", "license", "film",
    "sku"}``. With every default in place the SKU is the glue-down SKU-A.
    """
    built = build_approved_formulation(
        api, formulation_code, formulation_components
    )
    licensed = build_licensed_film(api)
    sku = create_sku(
        api, built["formulation"]["id"], licensed["film"]["id"], **sku_overrides
    )
    return {**built, **licensed, "sku": sku}


# ---------------------------------------------------------------------------
# Tier 3 -- lifecycle shortcuts.
# ---------------------------------------------------------------------------

# Measurements that PASS for the glue-down SKU-A: the residual-indentation
# limit is 0.10 for a CLASS_34_43 recipe and the dimensional-stability limit is
# 0.25 for a non-click-lock construction (PRD 3.4).
GLUE_DOWN_PASSING_RESULTS: Sequence[Tuple[str, float]] = (
    ("RESIDUAL_INDENTATION", 0.0800),
    ("DIMENSIONAL_STABILITY_HEAT", 0.2000),
)

# Measurements that PASS for the waterproof click-lock SKU-W across all five
# required test types.
CLICK_LOCK_PASSING_RESULTS: Sequence[Tuple[str, float]] = (
    ("RESIDUAL_INDENTATION", 0.0800),
    ("DIMENSIONAL_STABILITY_HEAT", 0.1000),
    ("SLIP_RESISTANCE", 0.5000),
    ("PEEL_ADHESION_DELAMINATION", 40.0000),
    ("LOCK_SHEAR", 9.0000),
)


def build_passed_panel(
    api: ApiClient,
    sku_id: str,
    results: Sequence[Tuple[str, float]] = GLUE_DOWN_PASSING_RESULTS,
    panel_code: str = "TP-A1",
    headers: Dict[str, str] = QA_TECHNICIAN,
) -> Dict[str, Any]:
    """Create, start and fully cover a panel so it reaches PASSED.

    A PASSED panel covering both mandatory test types also moves the SKU's
    certification ``TESTING -> PROVISIONAL`` (PRD 3.4).
    """
    panel = create_panel(api, sku_id, panel_code, headers)
    start_panel(api, panel["id"], headers)
    result_rows = [
        record_result(api, panel["id"], test_type, value, headers)
        for test_type, value in results
    ]
    panel = get_success_data(api.get_test_panel(panel["id"], headers))
    return {"panel": panel, "results": result_rows}


def build_provisional_sku(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A SKU driven to certification ``PROVISIONAL`` through a PASSED panel."""
    built = build_sku(api, **kwargs)
    begin_testing(api, built["sku"]["id"])
    panel = build_passed_panel(api, built["sku"]["id"])
    built.update(panel)
    built["sku"] = get_success_data(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    return built


def build_certified_sku(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A SKU driven to certification ``CERTIFIED`` with its cost stamped.

    With every default in place the certified SKU-A carries
    ``standard_cost_cents_per_sqm`` 1157 and ``list_price_cents_per_sqm`` 1562,
    with ``pinned_formulation_version`` 2 and ``pinned_print_film_version`` 1.
    """
    built = build_provisional_sku(api, **kwargs)
    built["sku"] = certify_sku(api, built["sku"]["id"])
    return built


def build_released_sku(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A CERTIFIED SKU additionally RELEASED on its commercial dimension."""
    built = build_certified_sku(api, **kwargs)
    built["sku"] = set_commercial_status(api, built["sku"]["id"], "RELEASED")
    return built


def run_to_completion(
    api: ApiClient,
    sku_id: str,
    press_line_id: str,
    actual_quantity_sqm: float = 1200.00,
    completion_overrides: Optional[Dict[str, Any]] = None,
    **run_overrides,
) -> Dict[str, Any]:
    """Schedule, set up, start and complete one run."""
    run = create_run(api, sku_id, press_line_id, **run_overrides)
    setup_run(api, run["id"])
    start_run(api, run["id"])
    run = complete_run(
        api, run["id"], actual_quantity_sqm, **(completion_overrides or {})
    )
    return run


def build_stock_batch(
    api: ApiClient,
    actual_quantity_sqm: float = 1200.00,
    line_overrides: Optional[Dict[str, Any]] = None,
    **sku_kwargs,
) -> Dict[str, Any]:
    """Drive the whole plant chain to one ``IN_STOCK`` batch.

    Released SKU-A on line PL-1, run RUN-A1 planned and completed at 1200.00
    square metres, QC released. The resulting batch carries ``quantity_sqm``
    and ``available_quantity_sqm`` of 1200.00, and the grant's ledger shows
    ``reserved_volume_sqm`` 0, ``consumed_volume_sqm`` 1200.00 and
    ``accrued_royalty_cents`` 126000.

    Returns the tier-2 keys plus ``{"press_line", "run", "batch"}``.
    """
    built = build_released_sku(api, **sku_kwargs)
    press_line = create_press_line(api, **(line_overrides or {}))
    run = run_to_completion(
        api, built["sku"]["id"], press_line["id"], actual_quantity_sqm
    )
    set_qc_disposition(api, run["id"], "RELEASED")
    batch = batch_of_run(api, run["id"])
    built.update(
        {
            "press_line": press_line,
            "run": get_success_data(api.get_production_run(run["id"], PLANT_ADMIN)),
            "batch": batch,
        }
    )
    return built


# ---------------------------------------------------------------------------
# Tier 4 -- accumulation and threshold targeting.
# ---------------------------------------------------------------------------


def build_open_allocation(
    api: ApiClient,
    requested_quantity_sqm: float = 100.00,
    allocation_code: str = "ALLOC-1",
    **stock_kwargs,
) -> Dict[str, Any]:
    """An ``IN_STOCK`` batch plus a distributor and an ``OPEN`` allocation."""
    built = build_stock_batch(api, **stock_kwargs)
    distributor = create_distributor(api)
    allocation = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code=allocation_code,
        requested_quantity_sqm=requested_quantity_sqm,
    )
    built.update({"distributor": distributor, "allocation": allocation})
    return built


def build_filled_allocation(
    api: ApiClient, requested_quantity_sqm: float = 100.00, **kwargs
) -> Dict[str, Any]:
    """An allocation filled from stock in one draw, reaching ``FILLED``."""
    built = build_open_allocation(
        api, requested_quantity_sqm=requested_quantity_sqm, **kwargs
    )
    built["allocation"] = fill_allocation(
        api,
        built["allocation"]["id"],
        built["distributor"]["id"],
        built["allocation"]["version"],
    )
    built["batch"] = get_success_data(
        api.get_batch(built["batch"]["id"], QA_TECHNICIAN)
    )
    return built


def build_quarantined_batch(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A completed run quarantined at QC, leaving its batch ``HELD``."""
    built = build_released_sku(api, **kwargs)
    press_line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], press_line["id"])
    set_qc_disposition(api, run["id"], "QUARANTINED")
    built.update(
        {
            "press_line": press_line,
            "run": get_success_data(api.get_production_run(run["id"], PLANT_ADMIN)),
            "batch": batch_of_run(api, run["id"]),
        }
    )
    return built


def release_batch_hold(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    """Release a held batch as a different technician than the one who held it.

    PRD 2.8 forbids the acting user from being the batch's ``held_by_user_id``,
    so this uses the second QA technician.
    """
    return set_batch_hold(api, batch_id, "RELEASE_HOLD", QA_TECHNICIAN_B)


# ---------------------------------------------------------------------------
# Tier 5 -- terminal-state shortcuts.
# ---------------------------------------------------------------------------


def build_adjudication_ready_claim(
    api: ApiClient,
    claim_type: str = "LOCK_FAILURE",
    claim_overrides: Optional[Dict[str, Any]] = None,
    **stock_kwargs,
) -> Dict[str, Any]:
    """A traceable batch with a claim triaged and every required arm answered.

    ``LOCK_FAILURE`` and ``DELAMINATION`` fork both a materials and a field
    review; the other two claim types fork the field review only (PRD 3.9).
    Every fork is answered ``DEFECT_CONFIRMED``, so the claim lands in
    ``ADJUDICATION_READY`` ready to be approved.
    """
    built = build_stock_batch(api, **stock_kwargs)
    distributor = create_distributor(api)
    claim = create_claim(
        api,
        built["batch"]["id"],
        distributor["id"],
        claim_type=claim_type,
        **(claim_overrides or {}),
    )
    claim = triage_claim(api, claim["id"])
    for review_kind in claim.get("required_reviews") or []:
        claim = record_review(api, claim["id"], review_kind, "DEFECT_CONFIRMED")
    built.update({"distributor": distributor, "claim": claim})
    return built
