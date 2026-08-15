"""Tariff administration: window geometry (half-open), OCC amendment,
version increments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_tariff,
    create_tariff_rate_payload,
    get_success_data,
    validate_error,
    validate_success,
)

LEASE_ADMIN = TEST_USERS["lease_admin_headers"]


class TestTariffWindowGeometry:
    def test_tariff_invalid_date_range_rejected(self, api):
        """PRD §3.13: "The window must be ordered — `effective_to` strictly
        after `effective_from` (`ERR_INVALID_DATE_RANGE`, 422) — and must not
        overlap any existing window for the same `(car_type, rate_kind)`
        pair; because windows are half-open, adjacency (one window's
        `effective_from` equal to another's `effective_to`) is allowed, while
        true overlap fails with `ERR_TARIFF_WINDOW_OVERLAP` (422)."

        Design: Corner/validations/tariff_invalid_date_range_rejected
        """
        resp = api.create_tariff_rate(
            create_tariff_rate_payload(
                car_type="BOX", rate_kind="CAR_HIRE_BASE",
                effective_from="2026-06-01", effective_to="2026-06-01",
                unit_rate_cents=9000,
            ),
            LEASE_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, 422)

    def test_adjacent_half_open_window_is_allowed(self, api):
        """PRD §3.13: "because windows are half-open, adjacency (one window's
        `effective_from` equal to another's `effective_to`) is allowed, while
        true overlap fails with `ERR_TARIFF_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/tariff_half_open_adjacency_vs_overlap
        """
        create_tariff("COVERED_HOPPER", "CAR_HIRE_BASE", 9000,
                      "2026-01-01", "2026-06-01")
        # effective_from == the predecessor's effective_to: legal adjacency.
        adjacent = validate_success(
            api.create_tariff_rate(
                create_tariff_rate_payload(
                    car_type="COVERED_HOPPER", rate_kind="CAR_HIRE_BASE",
                    effective_from="2026-06-01", effective_to="2027-01-01",
                    unit_rate_cents=9500,
                ),
                LEASE_ADMIN,
            ),
            201,
        )
        assert adjacent["effective_from"] == "2026-06-01"
        assert adjacent["unit_rate_cents"] == 9500

    def test_one_day_early_window_overlaps(self, api):
        """PRD §3.13: "because windows are half-open, adjacency (one window's
        `effective_from` equal to another's `effective_to`) is allowed, while
        true overlap fails with `ERR_TARIFF_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/tariff_half_open_adjacency_vs_overlap
        """
        create_tariff("COVERED_HOPPER", "CAR_HIRE_BASE", 9000,
                      "2026-01-01", "2026-06-01")
        # One day before the predecessor's exclusive end: a true intersection.
        resp = api.create_tariff_rate(
            create_tariff_rate_payload(
                car_type="COVERED_HOPPER", rate_kind="CAR_HIRE_BASE",
                effective_from="2026-05-31", effective_to="2026-12-01",
                unit_rate_cents=9100,
            ),
            LEASE_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP, 422)


class TestTariffAmendment:
    def test_tariff_amend_increments_version(self, api):
        """PRD §3.13: "A successful amendment increments the tariff's
        `version` by 1, and the amended window is re-validated for overlap
        against the same `(car_type, rate_kind)` pair
        (`ERR_TARIFF_WINDOW_OVERLAP`, 422)."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/endpoints/tariff_amend_increments_version_and_refreshes_updated_at
        """
        tariff = create_tariff("GONDOLA", "MILEAGE_CREDIT", 55,
                               "2026-01-01", "2027-01-01")
        amended = validate_success(
            api.amend_tariff_rate(
                tariff["id"],
                {"unit_rate_cents": 60,
                 "expected_tariff_version": tariff["version"]},
                LEASE_ADMIN,
            )
        )
        assert amended["version"] == tariff["version"] + 1, (
            "Version increments by exactly 1 on a successful amendment"
        )
        assert amended["unit_rate_cents"] == 60, (
            "The amendment is visible in the same response"
        )

    def test_tariff_amend_stale_version_rejected(self, api):
        """PRD §2.11: "Amending a tariff rate's window or unit rate requires
        `expected_tariff_version` carrying the client's last observed
        `version` of the tariff; the client's view of the rate grid is stale
        even though the tariff remains editable, and a mismatch is rejected
        with `ERR_STALE_VERSION` (412)."

        Design: Corner/cross_cutting_layers/tariff_amend_stale_version_rejected
        """
        tariff = create_tariff("FLAT", "CAR_HIRE_BASE", 8000,
                               "2026-01-01", "2027-01-01")
        observed = tariff["version"]
        first = validate_success(
            api.amend_tariff_rate(
                tariff["id"],
                {"unit_rate_cents": 8500, "expected_tariff_version": observed},
                LEASE_ADMIN,
            )
        )
        assert first["unit_rate_cents"] == 8500

        replayed = api.amend_tariff_rate(
            tariff["id"],
            {"unit_rate_cents": 8700, "expected_tariff_version": observed},
            LEASE_ADMIN,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION, 412)
        after = get_success_data(api.get_tariff_rate(tariff["id"], LEASE_ADMIN))
        assert after["unit_rate_cents"] == 8500, (
            "The stale amendment must not apply"
        )
