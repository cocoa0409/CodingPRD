"""Galley load calculation variants, pinned per-service ceil rounding, manifest OCC
locking, frozen-after-lock behavior, and the provision threshold (PRD §2.8, §3.7)."""
import pytest

from test_helpers import (
    CATER,
    create_confirmed_booking,
    create_held_booking,
    get_manifest,
    lock_manifest,
    setup_published_excursion,
    setup_published_pair,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import DINING_CAR_SPECS


class TestGalleyLoadVariants:
    """Same booking mix, two variants: REGULAR manifests are net (HELD excluded);
    HOLIDAY manifests prep conservatively (unexpired HELD included)."""

    def _book_dining_mix(self, excursion_id):
        create_confirmed_booking(excursion_id, "alice@x.com", "DINING", 1, "EARLY")
        create_confirmed_booking(excursion_id, "bob@x.com", "DINING", 1, "LATE")
        create_held_booking(excursion_id, "carol@x.com", "DINING", 2, "EARLY")  # unexpired

    def test_regular_manifest_net_variant_excludes_held(self, api, catering_manager_headers):
        """PRD §3.7: "Which bookings count depends on the excursion's `event_type`. On
        `REGULAR` excursions the counts are net: only `CONFIRMED` and `CHECKED_IN` diners
        are included. On `HOLIDAY` excursions the kitchen preps conservatively: unexpired
        `HELD` dining bookings are included as well, so identical booking data yields a
        larger load on a holiday train."

        Design: Difficulty/dual_variant_calc/galley_load_net_vs_conservative_holiday
        """
        pair = setup_published_pair(car_specs=DINING_CAR_SPECS,
                                    event_types=("REGULAR", "HOLIDAY"), surges=(10000, 12000))
        self._book_dining_mix(pair["a"]["excursion"]["id"])  # REGULAR leg

        manifest = get_manifest(pair["a"]["excursion"]["id"])
        assert manifest["early_diner_count"] == 1, "net variant excludes the HELD party of 2"
        assert manifest["late_diner_count"] == 1
        assert manifest["galley_load_units"] == 8, "ceil(1*3*1.1) + ceil(1*3*1.1) = 4 + 4"

    def test_holiday_manifest_conservative_prep_includes_held(self, api, catering_manager_headers):
        """PRD §3.7: "On `HOLIDAY` excursions the kitchen preps conservatively: unexpired
        `HELD` dining bookings are included as well, so identical booking data yields a
        larger load on a holiday train."
        PRD §3.5: "On `HOLIDAY` excursions, creating the hold also recomputes the
        still-`DRAFT` manifest — holiday provisioning pre-counts unexpired `HELD` diners —
        and bumps the manifest's `version`."

        Design: Difficulty/dual_variant_calc/galley_load_net_vs_conservative_holiday
        """
        pair = setup_published_pair(car_specs=DINING_CAR_SPECS,
                                    event_types=("REGULAR", "HOLIDAY"), surges=(10000, 12000))
        self._book_dining_mix(pair["b"]["excursion"]["id"])  # HOLIDAY leg

        manifest = get_manifest(pair["b"]["excursion"]["id"])
        assert manifest["early_diner_count"] == 3, "1 confirmed + 2 unexpired HELD"
        assert manifest["late_diner_count"] == 1
        assert manifest["galley_load_units"] == 14, "ceil(3*3*1.1) + ceil(1*3*1.1) = 10 + 4"


class TestGalleyLoadPinnedRounding:
    """Rounding order pinned: ceiling per dining service first, then sum."""

    def _setup_dining_excursion(self):
        scenario = setup_published_excursion(car_specs=DINING_CAR_SPECS)
        return scenario["excursion"]["id"]

    def test_ceil_per_service_then_sum_two_services(self, api, catering_manager_headers):
        """PRD §3.7: "The rounding order is pinned — ceiling first, then sum — because
        summing first and taking one ceiling can yield a different integer."

        Design: Difficulty/combinatorial_formula/galley_load_per_service_ceil_then_sum (mode b)
        """
        excursion_id = self._setup_dining_excursion()
        create_confirmed_booking(excursion_id, "alice@x.com", "DINING", 1, "EARLY")
        create_confirmed_booking(excursion_id, "bob@x.com", "DINING", 1, "LATE")

        manifest = get_manifest(excursion_id)
        assert manifest["early_diner_count"] == 1
        assert manifest["late_diner_count"] == 1
        # ceil(1*3*1.1) + ceil(1*3*1.1) = 4 + 4 = 8; the sum-then-ceil order would give
        # ceil(6.6) = 7 — the pinned order is what separates the two.
        assert manifest["galley_load_units"] == 8

    def test_ceil_applied_to_single_service_independently(self, api, catering_manager_headers):
        """PRD §3.7: "The rounding order is pinned — ceiling first, then sum — because
        summing first and taking one ceiling can yield a different integer."
        PRD §3.7: "Two diner counts sit on the manifest: `early_diner_count`, the summed
        `party_size` of `DINING` bookings in the `EARLY` service, and `late_diner_count`,
        the same for `LATE`."

        Design: Difficulty/combinatorial_formula/galley_load_per_service_ceil_then_sum (mode b)
        """
        excursion_id = self._setup_dining_excursion()
        create_confirmed_booking(excursion_id, "solo@x.com", "DINING", 1, "EARLY")

        manifest = get_manifest(excursion_id)
        assert manifest["early_diner_count"] == 1
        assert manifest["late_diner_count"] == 0
        assert manifest["galley_load_units"] == 4, "ceil(1*3*1.1) + ceil(0) = 4 + 0"


class TestProvisionThreshold:
    """MARK_PROVISIONED requires actual_loaded_units >= galley_load_units (inclusive)."""

    def _setup_locked_manifest_at_8(self):
        scenario = setup_published_excursion(car_specs=DINING_CAR_SPECS)
        excursion_id = scenario["excursion"]["id"]
        create_confirmed_booking(excursion_id, "a1@x.com", "DINING", 1, "EARLY")
        create_confirmed_booking(excursion_id, "b2@x.com", "DINING", 1, "LATE")
        manifest = get_manifest(excursion_id)
        assert manifest["galley_load_units"] == 8, "precondition: load is exactly 8"
        locked = lock_manifest(manifest["id"])
        assert locked["status"] == "LOCKED"
        return locked

    def test_mark_provisioned_exact_units_accepted(self, api, catering_manager_headers):
        """PRD §3.7: "Finally, marking the manifest provisioned requires the
        `actual_loaded_units` delivered to the platform to be at least `galley_load_units`
        — a shortfall is `ERR_PROVISION_SHORTFALL` — stores the figure, which remains
        unset until this moment, and moves the manifest to its terminal `PROVISIONED`
        state."

        Design: Difficulty/boundary_precision_check/provision_exact_units_accepted
        """
        locked = self._setup_locked_manifest_at_8()
        res = api.manifest_event(locked["id"],
                                 {"event_type": "MARK_PROVISIONED", "actual_loaded_units": 8},
                                 catering_manager_headers)
        provisioned = validate_success(res, 200)
        assert provisioned["status"] == "PROVISIONED", "equality satisfies the >= threshold"
        assert provisioned["actual_loaded_units"] == 8

    def test_mark_provisioned_over_delivery_accepted(self, api, catering_manager_headers):
        """PRD §3.7: "Finally, marking the manifest provisioned requires the
        `actual_loaded_units` delivered to the platform to be at least `galley_load_units`
        — a shortfall is `ERR_PROVISION_SHORTFALL` — stores the figure, which remains
        unset until this moment, and moves the manifest to its terminal `PROVISIONED`
        state."

        Design: Difficulty/boundary_precision_check/provision_exact_units_accepted
        """
        locked = self._setup_locked_manifest_at_8()
        res = api.manifest_event(locked["id"],
                                 {"event_type": "MARK_PROVISIONED", "actual_loaded_units": 9},
                                 catering_manager_headers)
        provisioned = validate_success(res, 200)
        assert provisioned["status"] == "PROVISIONED", "more than the load is also fine"
        assert provisioned["actual_loaded_units"] == 9


def test_locked_manifest_frozen_after_late_cancellation(api, station_agent_headers,
                                                        catering_manager_headers):
    """PRD §3.7: "Locking freezes the numbers: the lock event requires
    `expected_manifest_version` per §2.8, rejects a stale value with `ERR_STALE_VERSION`,
    stamps `locked_at` with the logical clock's timestamp — `locked_at` stays null while
    the manifest is `DRAFT` — and moves the manifest `DRAFT → LOCKED`; later booking
    changes no longer recompute a `LOCKED` manifest."

    Design: Corner/calculations/locked_manifest_frozen_after_late_cancellation
    """
    scenario = setup_published_excursion(car_specs=DINING_CAR_SPECS)
    excursion_id = scenario["excursion"]["id"]
    create_confirmed_booking(excursion_id, "d1@x.com", "DINING", 1, "EARLY")
    b2 = create_confirmed_booking(excursion_id, "d2@x.com", "DINING", 1, "EARLY")

    manifest = get_manifest(excursion_id)
    assert manifest["galley_load_units"] == 7, "ceil(2 * 3 * 1.1) = ceil(6.6)"
    locked = lock_manifest(manifest["id"])
    assert locked["locked_at"] is not None, "lock stamps the logical clock's timestamp"

    validate_success(api.booking_event(b2["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)

    after = validate_success(api.get_manifest(manifest["id"], catering_manager_headers), 200)
    assert after["status"] == "LOCKED"
    assert after["early_diner_count"] == 2, "frozen at the locked count"
    assert after["galley_load_units"] == 7, "a LOCKED manifest does not track booking changes"


def test_provision_shortfall_rejected(api, catering_manager_headers):
    """PRD §3.7: "Finally, marking the manifest provisioned requires the
    `actual_loaded_units` delivered to the platform to be at least `galley_load_units` —
    a shortfall is `ERR_PROVISION_SHORTFALL` — stores the figure, which remains unset
    until this moment, and moves the manifest to its terminal `PROVISIONED` state."

    Design: Corner/validations/provision_shortfall_rejected
    """
    scenario = setup_published_excursion(car_specs=DINING_CAR_SPECS)
    excursion_id = scenario["excursion"]["id"]
    create_confirmed_booking(excursion_id, "d1@x.com", "DINING", 1, "EARLY")
    create_confirmed_booking(excursion_id, "d2@x.com", "DINING", 1, "EARLY")

    manifest = get_manifest(excursion_id)
    assert manifest["galley_load_units"] == 7
    locked = lock_manifest(manifest["id"])

    res = api.manifest_event(locked["id"],
                             {"event_type": "MARK_PROVISIONED", "actual_loaded_units": 6},
                             catering_manager_headers)
    validate_error(res, ApiErrorId.ERR_PROVISION_SHORTFALL.value, expected_status=409)
    after = validate_success(api.get_manifest(manifest["id"], catering_manager_headers), 200)
    assert after["status"] == "LOCKED", "shortfall leaves the manifest LOCKED"


def test_occ_manifest_lock_stale_version(api, station_agent_headers, catering_manager_headers):
    """PRD §2.8: "The second guards manifest locking. A lock request must carry
    `expected_manifest_version`, the `version` of the provisioning manifest the client
    last observed. Every booking create, confirm, cancel, or rain-check cascade that
    recomputes a DRAFT manifest increments that version, so a lock submitted against an
    older number is rejected with `ERR_STALE_VERSION`, ensuring catering always locks the
    numbers it actually reviewed."

    Design: Corner/cross_cutting_layers/occ_manifest_lock_stale_version
    """
    scenario = setup_published_excursion(car_specs=DINING_CAR_SPECS)
    excursion_id = scenario["excursion"]["id"]
    create_confirmed_booking(excursion_id, "o1@x.com", "DINING", 1, "EARLY")

    observed = get_manifest(excursion_id)
    stale_version = observed["version"]

    # A second CONFIRM recomputes the DRAFT manifest and bumps its version.
    create_confirmed_booking(excursion_id, "o2@x.com", "DINING", 1, "LATE")

    res = api.manifest_event(observed["id"],
                             {"event_type": "LOCK", "expected_manifest_version": stale_version},
                             catering_manager_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    fresh = validate_success(api.get_manifest(observed["id"], catering_manager_headers), 200)
    res = api.manifest_event(observed["id"],
                             {"event_type": "LOCK", "expected_manifest_version": fresh["version"]},
                             catering_manager_headers)
    locked = validate_success(res, 200)
    assert locked["status"] == "LOCKED", "locking with the fresh version succeeds"
