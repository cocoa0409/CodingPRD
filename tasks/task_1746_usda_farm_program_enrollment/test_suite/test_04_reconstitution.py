"""Reconstitution: DIVIDE cascade, base-acre conservation invariant, and the
OCC correct-version success path (PRD §3.6, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_tract,
    assert_tract,
    create_farm,
    create_reconstitution_payload,
    get_farm_version,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


def _farm_with_tract(specialist, farm_number, base=100.00, cropland=100.00):
    farm = create_farm(farm_number=farm_number, county_code="019", program_year=2026)
    tract = add_tract(
        farm["id"], tract_number="T1", base_acres=base, cropland_acres=cropland
    )
    return farm, tract


class TestDivideCascade:
    def test_divide_marks_source_and_creates_products(self, api, specialist):
        """PRD §3.6: "The farm moves from `ACTIVE` to `RECONSTITUTION_PENDING`,
        its `version` increments by one, the source tracts move to `DIVIDED` or
        `COMBINED` under `tract_status`, and the product tracts are created — for
        a `DIVIDE`, two or more product tracts each recording
        `reconstituted_from_tract_id` pointing at the source"

        Design: Difficulty/transitive_cascade/reconstitution_divide_tract_cascade
        """
        set_clock("2026-02-01T00:00:00Z")
        farm, tract = _farm_with_tract(specialist, "F800")
        version = get_farm_version(farm["id"])
        resp = api.open_reconstitution(
            farm["id"],
            create_reconstitution_payload(
                method="DIVIDE",
                source_tract_ids=[tract["id"]],
                product_specs=[
                    {"tract_number": "T1A", "base_acres": 60.00, "cropland_acres": 60.00},
                    {"tract_number": "T1B", "base_acres": 40.00, "cropland_acres": 40.00},
                ],
                expected_farm_version=version,
            ),
            specialist,
        )
        get_success_data(resp)
        source_after = validate_success(api.get_tract(tract["id"], specialist), 200)
        assert source_after["tract_status"] == "DIVIDED", (
            f"source tract must be DIVIDED, got {source_after['tract_status']}"
        )
        tracts, _meta = validate_paginated(
            api.list_farm_tracts(farm["id"], specialist)
        )
        products = [
            t for t in tracts if t.get("reconstituted_from_tract_id") == tract["id"]
        ]
        assert len(products) == 2, (
            f"DIVIDE must create two product tracts, got {len(products)}"
        )
        for product in products:
            assert_tract(product)
        by_number = {t["tract_number"]: t for t in products}
        assert by_number["T1A"]["base_acres"] == pytest.approx(60.00)
        assert by_number["T1B"]["base_acres"] == pytest.approx(40.00)

    def test_divide_moves_farm_into_reconstitution_and_bumps_version(
        self, api, specialist
    ):
        """PRD §3.6: "The farm moves from `ACTIVE` to `RECONSTITUTION_PENDING`,
        its `version` increments by one, the source tracts move to `DIVIDED` or
        `COMBINED` under `tract_status`, and the product tracts are created"
        PRD §3.6: "The reconstitution completes automatically once every product
        tract is `ACTIVE` and the base-acre conservation check passes: the
        absolute difference between the sum of product `base_acres` and the sum
        of source `base_acres` must be no greater than 0.01 acres."
        PRD §3.6: "On success the farm moves to `RECONSTITUTED` and
        `total_base_acres` is recomputed."

        Design: Difficulty/transitive_cascade/reconstitution_divide_tract_cascade
        """
        set_clock("2026-02-01T00:00:00Z")
        farm, tract = _farm_with_tract(specialist, "F801")
        v_before = get_farm_version(farm["id"])
        resp = api.open_reconstitution(
            farm["id"],
            create_reconstitution_payload(
                method="DIVIDE",
                source_tract_ids=[tract["id"]],
                product_specs=[
                    {"tract_number": "T1A", "base_acres": 60.00, "cropland_acres": 60.00},
                    {"tract_number": "T1B", "base_acres": 40.00, "cropland_acres": 40.00},
                ],
                expected_farm_version=v_before,
            ),
            specialist,
        )
        get_success_data(resp)
        farm_after = validate_success(api.get_farm(farm["id"], specialist), 200)
        assert farm_after["version"] == v_before + 1, (
            f"opening a reconstitution increments Farm.version by one: "
            f"{v_before} -> {farm_after['version']}"
        )
        # A balanced product set is created ACTIVE in the same call; PRD allows
        # the farm to be observed pending or already auto-completed.
        assert farm_after["farm_status"] in ("RECONSTITUTION_PENDING", "RECONSTITUTED"), (
            f"farm must be in the reconstitution flow, got {farm_after['farm_status']}"
        )


class TestBaseAcreConservation:
    def test_imbalanced_divide_rejected_and_total_conserved(self, api, specialist):
        """PRD §3.6: "the absolute difference between the sum of product
        `base_acres` and the sum of source `base_acres` must be no greater than
        0.01 acres. A reconstitution that fails this check is rejected with
        `ERR_BASE_ACRE_IMBALANCE`."

        Design: Difficulty/compensating_invariant/reconstitution_conserves_total_base_acres
        """
        set_clock("2026-02-01T00:00:00Z")
        farm, tract = _farm_with_tract(specialist, "F1700", base=100.00, cropland=100.00)
        version = get_farm_version(farm["id"])
        resp = api.open_reconstitution(
            farm["id"],
            create_reconstitution_payload(
                method="DIVIDE",
                source_tract_ids=[tract["id"]],
                product_specs=[
                    {"tract_number": "T1A", "base_acres": 60.00, "cropland_acres": 60.00},
                    {"tract_number": "T1B", "base_acres": 30.00, "cropland_acres": 30.00},
                ],
                expected_farm_version=version,
            ),
            specialist,
        )
        validate_error(resp, ApiErrorId.ERR_BASE_ACRE_IMBALANCE.value)
        farm_after = validate_success(api.get_farm(farm["id"], specialist), 200)
        assert farm_after["total_base_acres"] == pytest.approx(100.00), (
            f"failed divide must conserve total base acres at 100.00, got "
            f"{farm_after['total_base_acres']}"
        )

    def test_balanced_divide_conserves_total_base_acres(self, api, specialist):
        """PRD §3.6: "the absolute difference between the sum of product
        `base_acres` and the sum of source `base_acres` must be no greater than
        0.01 acres." and "On success the farm moves to `RECONSTITUTED` and
        `total_base_acres` is recomputed."

        Design: Difficulty/compensating_invariant/reconstitution_conserves_total_base_acres
        """
        set_clock("2026-02-01T00:00:00Z")
        farm, tract = _farm_with_tract(specialist, "F1701", base=100.00, cropland=100.00)
        version = get_farm_version(farm["id"])
        resp = api.open_reconstitution(
            farm["id"],
            create_reconstitution_payload(
                method="DIVIDE",
                source_tract_ids=[tract["id"]],
                product_specs=[
                    {"tract_number": "T1A", "base_acres": 60.00, "cropland_acres": 60.00},
                    {"tract_number": "T1B", "base_acres": 40.00, "cropland_acres": 40.00},
                ],
                expected_farm_version=version,
            ),
            specialist,
        )
        get_success_data(resp)
        farm_after = validate_success(api.get_farm(farm["id"], specialist), 200)
        assert farm_after["total_base_acres"] == pytest.approx(100.00), (
            f"balanced divide must conserve total base acres at 100.00, got "
            f"{farm_after['total_base_acres']}"
        )


class TestOccCorrectVersion:
    def test_reconstitution_with_current_version_succeeds_and_bumps(
        self, api, specialist
    ):
        """PRD §2.6: "Opening a reconstitution on a farm likewise requires
        `expected_farm_version`. A mismatch with the farm's current `version` is
        rejected with `ERR_STALE_FARM_VERSION` (HTTP 412)."
        PRD §3.6: "The farm moves from `ACTIVE` to `RECONSTITUTION_PENDING`, its
        `version` increments by one, the source tracts move to `DIVIDED` or
        `COMBINED` under `tract_status`, and the product tracts are created"

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
        """
        farm, tract = _farm_with_tract(specialist, "F25")
        v_before = get_farm_version(farm["id"])
        resp = api.open_reconstitution(
            farm["id"],
            create_reconstitution_payload(
                method="DIVIDE",
                source_tract_ids=[tract["id"]],
                product_specs=[
                    {"tract_number": "T1A", "base_acres": 60.00, "cropland_acres": 60.00},
                    {"tract_number": "T1B", "base_acres": 40.00, "cropland_acres": 40.00},
                ],
                expected_farm_version=v_before,
            ),
            specialist,
        )
        get_success_data(resp)  # OCC check passes when the version matches
        v_after = get_farm_version(farm["id"])
        assert v_after == v_before + 1, (
            f"successful OCC-guarded reconstitution bumps Farm.version by one: "
            f"{v_before} -> {v_after}"
        )
