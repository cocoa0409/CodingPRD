"""Breadth over the money calculations: the closure cost basis and the royalty waterfall."""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_amount,
    assert_cell_fill,
    assert_density,
    assert_estimate_totals_consistent,
    assert_landfill_ledger,
)
from test_helpers.test_users import TEST_USERS

CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]

CERTIFIED_CELL = {
    "cell_code": "C-1",
    "design_airspace_cy": 1000000,
    "design_area_sf": 120001,
    "liner_type": "DOUBLE_COMPOSITE",
}
DESIGN_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "liner_type": "DOUBLE_COMPOSITE",
}


def _site_with_one_certified_and_one_design_cell():
    """C-1 is carried to QA_CERTIFIED; C-2 of 45,001 sf is left untouched in DESIGN."""
    landfill = fixtures.create_landfill()
    certified = fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides=CERTIFIED_CELL
    )
    design_cell = fixtures.create_cell(landfill["id"], **DESIGN_CELL)
    assert design_cell["status"] == "DESIGN"
    return landfill, certified["cell"], design_cell


def test_only_the_certified_cell_enters_the_closure_cost_basis():
    """Two cells differing only in state, and only one of them is priced.

    Including C-2 would give 306078.72, and summing the two areas before rounding would give
    the forbidden 306078.71.

    PRD: "Only cells of the landfill sitting in `QA_CERTIFIED`, `READY_FOR_WASTE`, `ACTIVE` or
    `FULL` contribute; cells in `DESIGN`, `UNDER_CONSTRUCTION`, `QA_REVIEW`, `REJECTED` and
    `CLOSED` contribute nothing, closed cells because their cover is already paid for and the
    rest because they carry no liner yet."

    Design: Corner/calculations/closure_cost_basis_includes_only_cells_in_the_declared_state_set
    """
    landfill, _certified, _design_cell = _site_with_one_certified_and_one_design_cell()

    estimate = fixtures.file_closure_estimate(landfill["id"])

    assert_amount(estimate["closure_cost_total"], 222601.86, "closure cost total")
    assert_amount(estimate["post_closure_cost_total"], 4519664.50, "post closure cost total")
    assert_amount(estimate["required_assurance_amount"], 4742266.36, "required assurance")
    assert_estimate_totals_consistent(estimate)


def test_the_excluded_cell_is_skipped_for_its_state_and_not_for_absence():
    """The 45,001 sf cell is on file and listable; the post-closure leg ignores cells entirely.

    PRD: "A site with no contributing cells still owes the entire post-closure care total,
    because step two does not depend on the cell set at all."

    Design: Corner/calculations/closure_cost_basis_includes_only_cells_in_the_declared_state_set
    """
    landfill, _certified, design_cell = _site_with_one_certified_and_one_design_cell()
    fixtures.file_closure_estimate(landfill["id"])

    rows, meta = validate_paginated(
        api_client.list_cells(
            FINANCE_FILER, {"landfill_id": landfill["id"], "status": "DESIGN"}
        )
    )

    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [design_cell["id"]]
    assert_amount(rows[0]["design_area_sf"], 45001, "excluded cell design area")

    bare_site = fixtures.create_landfill(name="Eastbank MSW", permit_number="MSW-8802")
    fixtures.create_cell(bare_site["id"], **DESIGN_CELL)
    bare_estimate = fixtures.file_closure_estimate(bare_site["id"])

    assert_amount(bare_estimate["closure_cost_total"], 0.00, "closure cost total")
    assert_amount(
        bare_estimate["post_closure_cost_total"], 4519664.50, "post closure cost total"
    )
    assert_amount(bare_estimate["required_assurance_amount"], 4519664.50, "required assurance")


FEE_SCHEDULE = {
    "posted_tipping_fee_per_ton": 42.50,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
}
DAY_SHAPE = {
    "operating_date": "2026-08-01T00:00:00Z",
    "working_face_area_sf": 5000,
    "cover_material_type": "ALTERNATIVE_TARP",
}


def _three_loads_processed_in_reverse_creation_order():
    """L-1, L-2, L-3 are created in that order and then cleared and weighed backwards."""
    site = fixtures.setup_open_day(
        cell_overrides=CERTIFIED_CELL,
        agreement_overrides=dict(FEE_SCHEDULE),
        day_overrides=dict(DAY_SHAPE),
    )
    landfill_id = site["landfill"]["id"]
    day_id = site["day"]["id"]
    site["l1"] = fixtures.receive_load(
        landfill_id, day_id, hauler_ref="H-1", waste_stream="MSW", manifest_tons=40.00
    )
    site["l2"] = fixtures.receive_load(
        landfill_id, day_id, hauler_ref="H-2", waste_stream="MSW", manifest_tons=90.00
    )
    site["l3"] = fixtures.receive_load(
        landfill_id, day_id, hauler_ref="H-3", waste_stream="CD", manifest_tons=30.00
    )
    for key, certified_tons in (("l3", 100.00), ("l2", 92.00), ("l1", 45.25)):
        site[key] = fixtures.clear_screening(landfill_id, site[key]["id"])
        site[key] = fixtures.certify_weight(landfill_id, site[key]["id"], certified_tons)
    return site


def _reread(site, key):
    return get_success_data(
        api_client.get_waste_load(site[key]["id"], site["scale_headers"])
    )


def test_the_three_gate_prices_are_struck_on_manifest_tonnage():
    """Clearance prices each truck off its manifest, in the order clearance happened.

    PRD: "It bills the *manifest* tonnage: the gross is `manifest_tons` multiplied by
    `posted_tipping_fee_per_ton`, rounded to 2 decimal places; the host fee is `manifest_tons`
    multiplied by `host_fee_per_ton`, also rounded to 2 decimal places; and
    `gate_charge_amount` is the sum of those two already-rounded components, rounded again to
    2 decimal places."

    Design: Corner/calculations/loads_finalize_in_pinned_chronological_order_not_clearing_order
    """
    site = _three_loads_processed_in_reverse_creation_order()

    assert_amount(site["l1"]["gate_charge_amount"], 1850.00, "L-1 gate charge")
    assert_amount(site["l2"]["gate_charge_amount"], 4162.50, "L-2 gate charge")
    assert_amount(site["l3"]["gate_charge_amount"], 1387.50, "L-3 gate charge")
    for key in ("l1", "l2", "l3"):
        assert site[key]["billing_status"] == "PROVISIONAL"
        assert site[key]["host_royalty_amount"] is None
        assert site[key]["final_charge_amount"] is None


def test_finalisation_follows_creation_order_and_not_clearing_order():
    """The tier-1 allowance runs out inside L-2, whichever truck was cleared first.

    A clearing-order implementation would have handed the allowance to L-3 and priced it at
    4795.00 instead of 4922.50.

    PRD: "Loads are finalized in one pinned chronological order across the whole site: by the
    operating day's `operating_date` ascending, and within a date by the load's `created_at`
    ascending."

    Design: Corner/calculations/loads_finalize_in_pinned_chronological_order_not_clearing_order
    """
    site = _three_loads_processed_in_reverse_creation_order()

    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    first = _reread(site, "l1")
    assert_amount(first["host_royalty_amount"], 76.93, "L-1 royalty")
    assert_amount(first["final_charge_amount"], 2169.75, "L-1 final charge")
    second = _reread(site, "l2")
    assert_amount(second["host_royalty_amount"], 203.90, "L-2 royalty")
    assert_amount(second["final_charge_amount"], 4458.90, "L-2 final charge")
    third = _reread(site, "l3")
    assert_amount(third["host_royalty_amount"], 297.50, "L-3 royalty")
    assert_amount(third["final_charge_amount"], 4922.50, "L-3 final charge")
    for row, gate in ((first, 1850.00), (second, 4162.50), (third, 1387.50)):
        assert row["billing_status"] == "FINALIZED"
        assert_amount(row["gate_charge_amount"], gate, "gate charge after finalisation")


def test_the_close_syncs_the_day_the_cell_and_the_site_ledgers():
    """237.25 certified tons at the capped density burn 279.12 cubic yards site-wide.

    PRD: "The **ledger sync** recomputes the site's `consumed_airspace_cy`,
    `remaining_airspace_cy` and `remaining_life_years`; if the recomputed
    `remaining_life_years` is below 2.0 years and the site is currently `OPEN`, its
    `operating_status` is set to `RESTRICTED_AIRSPACE` — the site keeps taking waste, but the
    shortening life is now visible in its posture."

    Design: Corner/calculations/loads_finalize_in_pinned_chronological_order_not_clearing_order
    """
    site = _three_loads_processed_in_reverse_creation_order()

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert_amount(closed["tons_placed"], 237.25, "tons placed")
    assert_density(closed["effective_density_tons_per_cy"], 0.8500, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 279.12, "airspace consumed")
    cell = get_success_data(api_client.get_cell(site["cell"]["id"], CQA_ENGINEER))
    assert_amount(cell["consumed_airspace_cy"], 279.12, "cell consumed airspace")
    assert_amount(cell["fill_pct"], 0.03, "cell fill pct")
    assert_cell_fill(cell)
    assert cell["status"] == "ACTIVE"
    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert_amount(landfill["consumed_airspace_cy"], 279.12, "site consumed airspace")
    assert_amount(landfill["remaining_life_years"], 3.00, "remaining life years")
    assert landfill["operating_status"] == "OPEN"
    assert_landfill_ledger(landfill)
