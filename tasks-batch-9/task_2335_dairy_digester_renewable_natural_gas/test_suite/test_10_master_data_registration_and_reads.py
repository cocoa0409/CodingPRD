"""Registering dairies and digesters: birth defaults, the regime-derived design ceiling,
the read and filter paths, and the screens that refuse a malformed registration."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    OPERATOR,
    create_dairy,
    create_facility,
    create_ops_day,
    setup_plant,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_UNKNOWN_UUID = "9f000000-0000-4000-8000-000000000099"


def test_01_a_new_dairy_is_born_a_prospect_with_no_history(api):
    """Registration assumes no agreements and no nutrient applications.

    PRD: "A newly registered dairy begins as `PROSPECT` with `active_agreement_count` at 0, `contracted_agreement_count` at 0 and `pan_applied_ytd_kg` at 0.000."

    Design: Corner/entities/entity_dairy_creation_returns_201_with_prospect_status_and_zero_counters
    """
    dairy = validate_success(
        api.create_dairy(
            {
                "name": "Vista Verde Dairy",
                "county": "Tulare",
                "herd_size": 3200,
                "manure_management_baseline": "LAGOON",
                "haul_distance_km": 12.0,
                "annual_nitrogen_budget_kg": 24000.000,
            },
            ADMIN,
        ),
        201,
    )
    assert dairy["status"] == "PROSPECT"
    assert dairy["active_agreement_count"] == 0
    assert dairy["contracted_agreement_count"] == 0
    assert dairy["pan_applied_ytd_kg"] == 0.000
    assert dairy["haul_distance_km"] == 12.0
    assert dairy["version"] == 1


def test_02_the_thermal_regime_alone_fixes_the_design_loading_ceiling(api):
    """Two identically sized digesters get different ceilings from their regimes.

    PRD: "The regime is either `MESOPHILIC` or `THERMOPHILIC`, and it alone fixes the derived design ceiling `design_max_olr`: a mesophilic digester is assigned a design ceiling of 3.500 kilograms of volatile solids per cubic metre per day, a thermophilic digester 4.500, in both cases stored to 3 decimal places."

    Design: Corner/entities/entity_facility_design_max_olr_is_computed_from_thermal_regime
    """
    mesophilic = create_facility()
    assert mesophilic["thermal_regime"] == "MESOPHILIC"

    thermophilic = validate_success(
        api.create_facility(
            {
                "name": "Tulare Digester 2",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "THERMOPHILIC",
                "target_temperature_c": 54.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
                "dscr_minimum": 1.250,
            },
            ADMIN,
        ),
        201,
    )
    assert thermophilic["thermal_regime"] == "THERMOPHILIC"
    assert thermophilic["design_max_olr"] == 4.500

    reread = validate_success(api.get_facility(mesophilic["id"], ADMIN))
    assert reread["design_max_olr"] == 3.500


def test_03_a_new_facility_starts_stable_open_and_arithmetically_empty(api):
    """Every posture, ledger and mass-control accumulator starts at its zero.

    PRD: "Creation also sets `ops_posture` to `STABLE`, `distribution_posture` to `OPEN`, `posture_override_active` to false, `reserve_balance_cents` to 0, `dscr_current` to 0.000, and all of the mass-control and revenue-ledger accumulators — `total_manure_received_tonnes`, `unseparated_manure_tonnes`, `digestate_solids_produced_tonnes`, `digestate_liquid_produced_tonnes`, `digestate_solids_applied_tonnes`, `digestate_liquid_applied_tonnes`, `digestate_solids_on_hand_tonnes`, `digestate_liquid_on_hand_tonnes`, `mass_control_residual_tonnes`, `gross_revenue_to_date_cents`, `dairy_share_paid_cents` and `retained_to_date_cents` — to zero."

    Design: Corner/entities/entity_facility_creation_defaults_every_ledger_and_posture_field
    """
    facility = validate_success(
        api.create_facility(
            {
                "name": "Tulare Digester 1",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "MESOPHILIC",
                "target_temperature_c": 38.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
                "dscr_minimum": 1.250,
            },
            ADMIN,
        ),
        201,
    )
    assert facility["ops_posture"] == "STABLE"
    assert facility["distribution_posture"] == "OPEN"
    assert facility["posture_override_active"] is False
    assert facility["reserve_balance_cents"] == 0
    assert facility["dscr_current"] == 0
    assert facility["total_manure_received_tonnes"] == 0.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_04_a_dairy_detail_read_returns_the_stored_baseline_unchanged(api):
    """The read path never recomputes master data.

    PRD: "A `PlatformAdmin` registers each manure supplier as a `Dairy`, supplying its legal `name`, the `county` it operates in, its milking `herd_size` (which must be greater than zero), the `manure_management_baseline` describing how manure was handled before the project existed, the one-way `haul_distance_km` from the dairy to the digester (which may be zero for an on-site dairy but never negative), and the `annual_nitrogen_budget_kg` that caps plant-available nitrogen across all of that dairy's land units in a calendar year (which must be greater than zero)."

    Design: Corner/entities/entity_dairy_detail_read_returns_the_stored_master_data
    """
    dairy = create_dairy(
        name="Kings River Dairy",
        county="Kings",
        herd_size=2200,
        manure_management_baseline="SOLID_STORAGE",
        haul_distance_km=30.0,
        annual_nitrogen_budget_kg=12000.000,
    )

    stored = validate_success(api.get_dairy(dairy["id"], ADMIN))
    assert stored["name"] == "Kings River Dairy"
    assert stored["county"] == "Kings"
    assert stored["herd_size"] == 2200
    assert stored["manure_management_baseline"] == "SOLID_STORAGE"
    assert stored["haul_distance_km"] == 30.0
    assert stored["annual_nitrogen_budget_kg"] == 12000.000


def test_05_the_county_filter_removes_rows_rather_than_paging_them(api):
    """Two Tulare dairies come back and the Kings dairy is filtered out entirely.

    PRD: "Dairies may be filtered by `status` and `county`."

    Design: Corner/entities/entity_dairy_list_applies_county_filter_with_pagination_envelope
    """
    tulare_one = create_dairy()
    tulare_two = create_dairy(
        name="Sierra Bend Dairy",
        county="Tulare",
        herd_size=1800,
        manure_management_baseline="DAILY_SPREAD",
        haul_distance_km=8.0,
        annual_nitrogen_budget_kg=9000.000,
    )
    kings = create_dairy(
        name="Kings River Dairy",
        county="Kings",
        herd_size=2200,
        manure_management_baseline="SOLID_STORAGE",
        haul_distance_km=30.0,
        annual_nitrogen_budget_kg=12000.000,
    )

    rows, meta = validate_paginated(
        api.list_dairies(
            ADMIN, {"status": "PROSPECT", "county": "Tulare", "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    returned = {row["id"] for row in rows}
    assert returned == {tulare_one["id"], tulare_two["id"]}
    assert kings["id"] not in returned


def test_06_a_facility_without_a_covenant_floor_is_never_created(api):
    """Omitting the required covenant minimum is a schema failure, not a default.

    PRD: "**Schema conformance** — required fields present, types correct, numeric ranges honoured, enum members valid, decimal scale not exceeded: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/entity_facility_creation_missing_dscr_minimum_returns_invalid_request
    """
    validate_error(
        api.create_facility(
            {
                "name": "Tulare Digester 1",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "MESOPHILIC",
                "target_temperature_c": 38.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
            },
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _, meta = validate_paginated(api.list_facilities(ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_07_a_load_whose_tare_equals_its_gross_weight_is_refused(api):
    """A zero-net load never reaches the mass or loading-rate arithmetic.

    PRD: "The `ProjectOperator` supplies `agreement_id` and `ops_day_id`, resolved in that order, the `gross_tonnes` loaded weight (greater than zero), an optional `tare_tonnes` deduction that defaults to 0.000 when omitted and must be zero or more and strictly less than `gross_tonnes`, the measured `total_solids_pct` of the load (greater than zero and less than 100), and `volatile_solids_pct_of_ts`, the volatile fraction of those solids (greater than zero and at most 100)."

    Design: Corner/entities/entity_delivery_tare_not_below_gross_returns_invalid_request
    """
    plant = setup_plant()
    ops_day = create_ops_day(plant["facility"]["id"], "2026-08-03")

    validate_error(
        api.create_delivery(
            {
                "agreement_id": plant["agreement"]["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 150.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    untouched = validate_success(api.get_ops_day(ops_day["id"], OPERATOR))
    assert untouched["organic_loading_rate"] == 0.000


def test_08_the_first_unresolvable_body_reference_names_the_error(api):
    """Both foreign keys are unknown and the agreement is the one reported.

    PRD: "**Body reference resolution** — on creation operations, every foreign key supplied in the request body is resolved in the exact order the fields are listed for that operation, yielding `ERR_DAIRY_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OPS_DAY_NOT_FOUND`, `ERR_INTERCONNECT_NOT_FOUND` or `ERR_PATHWAY_NOT_FOUND` (404)."

    Design: Corner/entities/entity_delivery_creation_with_unknown_agreement_returns_agreement_not_found
    """
    create_facility()

    body = validate_error(
        api.create_delivery(
            {
                "agreement_id": NON_EXISTENT_UUID,
                "ops_day_id": SECOND_UNKNOWN_UUID,
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_AGREEMENT_NOT_FOUND",
        404,
    )
    assert body["error_id"] != "ERR_OPS_DAY_NOT_FOUND"


def test_09_an_unknown_dairy_path_id_answers_with_its_own_not_found_code(api):
    """A detail read of a missing row is an error envelope, not an empty object.

    PRD: "**Path resolution** — every identifier embedded in the URL is resolved strictly left to right, and the first one that does not exist produces its own not-found error: `ERR_DAIRY_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_OPS_DAY_NOT_FOUND`, `ERR_INTERCONNECT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`, `ERR_PATHWAY_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND` or `ERR_STATEMENT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/entity_unknown_dairy_id_on_detail_read_returns_dairy_not_found
    """
    validate_error(
        api.get_dairy(NON_EXISTENT_UUID, ADMIN), "ERR_DAIRY_NOT_FOUND", 404
    )
