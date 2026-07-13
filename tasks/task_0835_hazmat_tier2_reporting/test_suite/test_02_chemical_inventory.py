"""Chemical catalog, inventory declaration, threshold determination, and hazard index."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_chemical_payload,
    create_ehs_chemical_payload,
    create_chemical_inventory_payload,
    make_regulator_headers,
    make_facility_operator_headers,
    register_facility,
    create_chemical,
    create_ehs_chemical,
    declare_inventory,
    get_facility,
)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / inventory_max_vs_average_amount
# ---------------------------------------------------------------------------
def test_inventory_reportable_uses_max_not_average(api):
    """PRD §3.3: "`reportable_amount_lbs` is set equal to `max_daily_amount_lbs`
    and is the sole basis for every threshold and Tier II decision. The
    `average_onsite_lbs` field is set equal to `average_daily_amount_lbs` and is
    reported for information only — it is never substituted into any threshold,
    reportability, or fee decision, even though it can differ from the maximum for
    the same row."

    Design: Difficulty/dual_variant_calc/inventory_max_vs_average_amount
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.2)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=12000, average_daily_amount_lbs=4000,
        days_on_site=200, storage_type="TANK",
    )
    assert inv["reportable_amount_lbs"] == 12000
    assert inv["average_onsite_lbs"] == 4000
    assert inv["reportable_amount_lbs"] != inv["average_onsite_lbs"]


def test_inventory_max_variant_drives_reportability(api):
    """PRD §3.3: "`reportable_amount_lbs` is set equal to `max_daily_amount_lbs`
    and is the sole basis for every threshold and Tier II decision."
    PRD §3.3: "For a non-EHS chemical, `applicable_threshold_lbs` is a flat 10,000
    pounds and `exceeds_tpq` is always `false`."

    Design: Difficulty/dual_variant_calc/inventory_max_vs_average_amount
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.2)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=12000, average_daily_amount_lbs=4000,
        days_on_site=200, storage_type="TANK",
    )
    # 12000 (max) >= 10000 threshold -> reportable, even though average 4000 < 10000.
    assert inv["is_reportable"] is True


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / threshold_ehs_branch_nested_min
# ---------------------------------------------------------------------------
def test_ehs_threshold_is_nested_min_of_tpq_and_cap(api):
    """PRD §3.3: "For an EHS chemical, `applicable_threshold_lbs` is the smaller of
    the chemical's `tpq_lbs` and a cap of 500 pounds; additionally `exceeds_tpq` is
    set to `true` exactly when `reportable_amount_lbs` reaches or exceeds the
    chemical's `tpq_lbs` (an inclusive comparison — equal amounts qualify)."

    Design: Difficulty/combinatorial_formula/threshold_ehs_branch_nested_min
    """
    facility = register_facility()
    chemical = create_ehs_chemical(tpq_lbs=800, rq_lbs=100, hazard_weight=0.3)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=600, average_daily_amount_lbs=400,
        days_on_site=250, storage_type="TANK",
    )
    assert inv["applicable_threshold_lbs"] == 500


def test_ehs_reportable_true_but_exceeds_tpq_false(api):
    """PRD §3.3: "`is_reportable` is set to `true` exactly when
    `reportable_amount_lbs` reaches or exceeds `applicable_threshold_lbs` — again an
    inclusive lower bound, so an amount exactly equal to the threshold is reportable."
    PRD §3.3: "`exceeds_tpq` is set to `true` exactly when `reportable_amount_lbs`
    reaches or exceeds the chemical's `tpq_lbs` (an inclusive comparison — equal
    amounts qualify)."

    Design: Difficulty/combinatorial_formula/threshold_ehs_branch_nested_min
    """
    facility = register_facility()
    chemical = create_ehs_chemical(tpq_lbs=800, rq_lbs=100, hazard_weight=0.3)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=600, average_daily_amount_lbs=400,
        days_on_site=250, storage_type="TANK",
    )
    assert inv["is_reportable"] is True     # 600 >= 500 (applicable threshold)
    assert inv["exceeds_tpq"] is False      # 600 < 800 (tpq)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / inventory_threshold_inclusive_boundary
# ---------------------------------------------------------------------------
def test_non_ehs_threshold_inclusive_at_boundary(api):
    """PRD §3.3: "`is_reportable` is set to `true` exactly when
    `reportable_amount_lbs` reaches or exceeds `applicable_threshold_lbs` — again an
    inclusive lower bound, so an amount exactly equal to the threshold is reportable."

    Design: Difficulty/boundary_precision_check/inventory_threshold_inclusive_boundary
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.15)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=10000, average_daily_amount_lbs=6000,
        days_on_site=150, storage_type="TANK",
    )
    assert inv["applicable_threshold_lbs"] == 10000
    assert inv["reportable_amount_lbs"] == 10000
    assert inv["is_reportable"] is True


def test_non_ehs_threshold_below_boundary_not_reportable(api):
    """PRD §3.3: "`is_reportable` is set to `true` exactly when
    `reportable_amount_lbs` reaches or exceeds `applicable_threshold_lbs` — again an
    inclusive lower bound, so an amount exactly equal to the threshold is reportable."

    Design: Difficulty/boundary_precision_check/inventory_threshold_inclusive_boundary
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.15)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=9999, average_daily_amount_lbs=6000,
        days_on_site=150, storage_type="TANK",
    )
    # 9999 < 10000 -> not reportable (strict below the inclusive lower bound).
    assert inv["is_reportable"] is False


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / hazard_index_round_then_sum
# ---------------------------------------------------------------------------
def test_weighted_hazard_contribution_rounded_two_decimals(api):
    """PRD §3.3: "The row's `weighted_hazard_contribution` is computed by dividing
    `max_daily_amount_lbs` by 1,000 pounds, multiplying by the chemical's
    `hazard_weight`, and rounding that product half up to two decimal places."

    Design: Difficulty/combinatorial_formula/hazard_index_round_then_sum
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=5000, hazard_weight=0.125)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=1000, average_daily_amount_lbs=800,
        days_on_site=100, storage_type="DRUM",
    )
    # round((1000/1000) * 0.125, 2) = round(0.125, 2) = 0.13 (half up).
    assert inv["weighted_hazard_contribution"] == pytest.approx(0.13, abs=0.005)


def test_hazard_index_rounds_each_term_then_sums(api):
    """PRD §3.3: "each per-row contribution is rounded to two decimals **first**,
    and only those already-rounded contributions are summed. The system must not sum
    the raw products and round once at the end."

    Design: Difficulty/combinatorial_formula/hazard_index_round_then_sum
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=5000, hazard_weight=0.125)
    for _ in range(3):
        declare_inventory(
            fac_id, chemical["id"], reporting_year=2025,
            max_daily_amount_lbs=1000, average_daily_amount_lbs=800,
            days_on_site=100, storage_type="DRUM",
        )
    facility_read = get_facility(fac_id)
    # 0.13 + 0.13 + 0.13 = 0.39 (round-then-sum); sum-then-round of 0.375 would be 0.38.
    assert facility_read["hazard_index"] == pytest.approx(0.39, abs=0.005)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / hazard_index_add_retire_conserves
# ---------------------------------------------------------------------------
def test_retire_inventory_restores_hazard_index(api):
    """PRD §3.3: "Retiring a row moves its `status` from `ACTIVE` to `RETIRED`,
    which removes it from the active set: the facility's `hazard_index` therefore
    decreases by exactly that row's `weighted_hazard_contribution`, and
    `is_rmp_required` is recomputed to reflect the smaller active set."

    Design: Difficulty/compensating_invariant/hazard_index_add_retire_conserves
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.2)
    inv = declare_inventory(
        fac_id, chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=5000, average_daily_amount_lbs=3000,
        days_on_site=120, storage_type="TANK",
    )
    validate_success(api.retire_chemical_inventory(inv["id"], make_facility_operator_headers(fac_id)))
    facility_read = get_facility(fac_id)
    assert facility_read["hazard_index"] == pytest.approx(0.00, abs=0.005)


def test_hazard_contribution_of_added_row(api):
    """PRD §3.3: "The row's `weighted_hazard_contribution` is computed by dividing
    `max_daily_amount_lbs` by 1,000 pounds, multiplying by the chemical's
    `hazard_weight`, and rounding that product half up to two decimal places."

    Design: Difficulty/compensating_invariant/hazard_index_add_retire_conserves
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.2)
    inv = declare_inventory(
        facility["id"], chemical["id"], reporting_year=2025,
        max_daily_amount_lbs=5000, average_daily_amount_lbs=3000,
        days_on_site=120, storage_type="TANK",
    )
    # round((5000/1000) * 0.2, 2) = round(1.0, 2) = 1.00.
    assert inv["weighted_hazard_contribution"] == pytest.approx(1.00, abs=0.005)


# ---------------------------------------------------------------------------
# Corner instances
# ---------------------------------------------------------------------------
def test_ehs_chemical_without_tpq_rejected(api):
    """PRD §3.2: "A `tpq_lbs` Threshold Planning Quantity in pounds is required when
    the chemical is an EHS and is ignored otherwise; submitting an EHS chemical
    without a `tpq_lbs` is malformed and rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/chemical_ehs_missing_tpq_returns_invalid_request
    """
    payload = create_ehs_chemical_payload()
    del payload["tpq_lbs"]
    resp = api.create_chemical(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_inventory_invalid_storage_type_rejected(api):
    """PRD §2.9: "the request body is checked for well-formedness — required fields
    present, enum values valid, numeric amounts non-negative, and an EHS chemical
    carrying its `tpq_lbs` — which fails with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/inventory_invalid_enum_storage_type_returns_invalid_request
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    payload = create_chemical_inventory_payload(
        facility["id"], chemical["id"], max_daily_amount_lbs=100,
        average_daily_amount_lbs=50, days_on_site=10, storage_type="BOX",
    )
    resp = api.create_chemical_inventory(payload, make_facility_operator_headers(facility["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_inventory_unknown_chemical_not_found(api):
    """PRD §2.9: "any facility, chemical, inventory, filing, SDS, release, permit,
    inspection, case, risk-management plan, or path id that does not exist yields
    the corresponding not-found error (`ERR_FACILITY_NOT_FOUND`,
    `ERR_CHEMICAL_NOT_FOUND`, ..."

    Design: Corner/entities/inventory_unknown_chemical_returns_not_found
    """
    facility = register_facility()
    payload = create_chemical_inventory_payload(
        facility["id"], "00000000-0000-4000-8000-000000000001",
        max_daily_amount_lbs=100, average_daily_amount_lbs=50,
        days_on_site=10, storage_type="DRUM",
    )
    resp = api.create_chemical_inventory(payload, make_facility_operator_headers(facility["id"]))
    validate_error(resp, ApiErrorId.ERR_CHEMICAL_NOT_FOUND.value)


def test_retire_already_retired_inventory_rejected(api):
    """PRD §3.3: "retirement is permitted only when the row is `ACTIVE`, and an
    attempt to retire a row that is already `RETIRED` is rejected with
    `ERR_INVENTORY_NOT_ACTIVE`."

    Design: Corner/errors/retire_inventory_twice_returns_inventory_not_active
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    inv = declare_inventory(
        fac_id, chemical["id"], max_daily_amount_lbs=100,
        average_daily_amount_lbs=50, days_on_site=10, storage_type="DRUM",
    )
    validate_success(api.retire_chemical_inventory(inv["id"], make_facility_operator_headers(fac_id)))
    resp = api.retire_chemical_inventory(inv["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_INVENTORY_NOT_ACTIVE.value)
