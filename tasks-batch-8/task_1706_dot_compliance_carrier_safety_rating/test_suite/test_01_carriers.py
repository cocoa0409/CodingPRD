"""Carrier onboarding, profile OCC, and the fixed response envelope."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_carrier,
    assert_timestamp_at,
    create_carrier_payload,
    create_period_payload,
    is_valid_uuid,
    make_carrier,
    make_period,
    make_premium_model,
    validate_error,
    validate_success,
)


class TestCarrierOnboarding:
    def test_carrier_create_defaults_applied(self, api, admin_headers):
        """PRD §3.1: "A new carrier starts with `safety_rating` `NONE`, `posture`
        `NORMAL`, `rating_cooling_off_until` null, `last_cycle_date` null, and
        `version` 1; its `new_entrant_status` is `PENDING_AUDIT` when registered
        as a new entrant and `NOT_NEW_ENTRANT` otherwise."
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its
        own."

        Design: Corner/entities/carrier_create_defaults_applied
        """
        resp = api.create_carrier(
            create_carrier_payload(
                dot_number="DOT-2001", legal_name="Corner Carrier One", fleet_size=2
            ),
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_carrier(data)
        assert data["safety_rating"] == "NONE"
        assert data["new_entrant_status"] == "NOT_NEW_ENTRANT"
        assert data["posture"] == "NORMAL"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert_timestamp_at(data["created_at"], "2026-08-01T00:00:00")
        assert data["created_at"] == data["updated_at"], (
            "created_at and updated_at coincide at creation (PRD §2.4)"
        )

    def test_carrier_new_entrant_missing_due_date_returns_400(self, api, admin_headers):
        """PRD §3.1: "`safety_audit_due_date` — the deadline for the new-entrant
        safety audit — is required if and only if `is_new_entrant` is true; a
        registration that violates this conditional requirement is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/carrier_new_entrant_missing_due_date_returns_400
        """
        resp = api.create_carrier(
            create_carrier_payload(
                dot_number="DOT-2002",
                legal_name="Corner Carrier Two",
                fleet_size=2,
                is_new_entrant=True,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_fleet_size_zero_rejected(self, api, admin_headers):
        """PRD §3.1: "the number of power units, which must be at least 1,
        failing with `ERR_INVALID_FLEET_SIZE` otherwise."

        Design: Corner/validations/fleet_size_zero_rejected
        """
        resp = api.create_carrier(
            create_carrier_payload(
                dot_number="DOT-2318", legal_name="Zero Fleet", fleet_size=0
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FLEET_SIZE)

    def test_duplicate_dot_number_and_testing_period_rejected(
        self, api, admin_headers, manager_headers
    ):
        """PRD §3.1: "The `dot_number` is unique across all carriers, and a
        duplicate is rejected with `ERR_DUPLICATE_DOT_NUMBER`."
        PRD §3.6: "Only one period may exist per carrier per calendar year; a
        duplicate is rejected with `ERR_DUPLICATE_TESTING_PERIOD`."

        Design: Corner/validations/duplicate_dot_number_and_testing_period_rejected
        """
        carrier = make_carrier(dot_number="DOT-2335", legal_name="Dup Dot")
        make_period(carrier["id"], program_year=2026, avg_driver_count=4)

        dup_carrier = api.create_carrier(
            create_carrier_payload(
                dot_number="DOT-2335", legal_name="Dup Dot 2", fleet_size=5
            ),
            admin_headers,
        )
        validate_error(dup_carrier, ApiErrorId.ERR_DUPLICATE_DOT_NUMBER)

        dup_period = api.create_period(
            create_period_payload(carrier["id"], program_year=2026, avg_driver_count=10),
            manager_headers,
        )
        validate_error(dup_period, ApiErrorId.ERR_DUPLICATE_TESTING_PERIOD)

        other_year = api.create_period(
            create_period_payload(carrier["id"], program_year=2027, avg_driver_count=10),
            manager_headers,
        )
        validate_success(other_year, 201)


class TestCarrierProfileOcc:
    def test_occ_carrier_patch_stale_version(self, api, admin_headers):
        """PRD §2.7: "Updating a carrier's profile (`PATCH
        /safety/carriers/{id}`) requires `expected_carrier_version`, carrying the
        client's last observed `version` of the carrier. When the supplied value
        does not equal the parent entity's current `version` — because the
        driver or carrier has advanced through changes the client has not
        observed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_carrier_patch_stale_version
        """
        carrier = make_carrier(dot_number="DOT-2602", legal_name="OCC Carrier Two")
        assert carrier["version"] == 1

        first = api.patch_carrier(
            carrier["id"], {"fleet_size": 5, "expected_carrier_version": 1}, admin_headers
        )
        patched = validate_success(first, 200)
        assert patched["fleet_size"] == 5
        assert patched["version"] == 2

        stale = api.patch_carrier(
            carrier["id"],
            {"legal_name": "Stale Edit", "expected_carrier_version": 1},
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = api.patch_carrier(
            carrier["id"],
            {"legal_name": "Fresh Edit", "expected_carrier_version": 2},
            admin_headers,
        )
        assert validate_success(fresh, 200)["legal_name"] == "Fresh Edit"

    def test_premium_quote_after_carrier_patch_stale_input(
        self, api, admin_headers, insurance_headers
    ):
        """PRD §2.8: "Models in `DRAFT` are not eagerly swept; instead, both
        quoting and binding require the model's `carrier_version_at_compute` to
        equal the carrier's current `version`, and a model whose inputs have
        moved underneath it is rejected with `ERR_PREMIUM_INPUT_STALE` (HTTP
        409). The recovery path for a stale draft is recomputation, which
        re-reads current carrier data and refreshes `carrier_version_at_compute`
        (see §3.9)."

        Design: Corner/validations/premium_quote_after_carrier_patch_stale_input
        """
        carrier = make_carrier(dot_number="DOT-2331", legal_name="Stale Carrier")
        model = make_premium_model(carrier["id"], base_rate_cents_per_unit=80000)
        assert model["carrier_version_at_compute"] == 1

        api.patch_carrier(
            carrier["id"],
            {"legal_name": "Stale Carrier Renamed", "expected_carrier_version": 1},
            admin_headers,
        )

        quote = api.quote_premium_model(model["id"], insurance_headers)
        validate_error(quote, ApiErrorId.ERR_PREMIUM_INPUT_STALE)

        recomputed = api.recompute_premium_model(model["id"], insurance_headers)
        recomputed_data = validate_success(recomputed, 200)
        assert recomputed_data["status"] == "DRAFT"
        assert recomputed_data["carrier_version_at_compute"] == 2

        quote2 = api.quote_premium_model(model["id"], insurance_headers)
        assert validate_success(quote2, 200)["status"] == "QUOTED"


class TestResponseEnvelope:
    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "response_type": "error" and a `data`
        object carrying `error_id` and `message`; "The `meta` object for error
        responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.6: each missing resource yields "ERR_CARRIER_NOT_FOUND".

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_carrier(NON_EXISTENT_UUID, admin_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"]
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)

    @pytest.mark.parametrize(
        "kind,expected_error",
        [
            ("carriers", "ERR_CARRIER_NOT_FOUND"),
            ("drivers", "ERR_DRIVER_NOT_FOUND"),
            ("violation-categories", "ERR_CATEGORY_NOT_FOUND"),
            ("roadside-inspections", "ERR_INSPECTION_NOT_FOUND"),
            ("inspection-violations", "ERR_VIOLATION_NOT_FOUND"),
            ("dataqs-challenges", "ERR_CHALLENGE_NOT_FOUND"),
            ("coaching-assignments", "ERR_COACHING_NOT_FOUND"),
            ("drug-alcohol-tests", "ERR_TEST_NOT_FOUND"),
            ("accident-records", "ERR_ACCIDENT_NOT_FOUND"),
            ("compliance-audit-cases", "ERR_AUDIT_CASE_NOT_FOUND"),
            ("rating-upgrade-requests", "ERR_UPGRADE_REQUEST_NOT_FOUND"),
            ("insurance-premium-models", "ERR_PREMIUM_MODEL_NOT_FOUND"),
            ("document-records", "ERR_DOCUMENT_NOT_FOUND"),
            ("random-testing-periods", "ERR_TESTING_PERIOD_NOT_FOUND"),
            ("measurement-snapshots", "ERR_SNAPSHOT_NOT_FOUND"),
        ],
    )
    def test_not_found_sweep_returns_404(self, api, admin_headers, kind, expected_error):
        """PRD §2.6: "Path identifiers are resolved first, from left to right;
        then body foreign-key identifiers are resolved in their declared input
        order. Each missing resource yields its own 404:
        `ERR_CARRIER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
        `ERR_CATEGORY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
        `ERR_VIOLATION_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`,
        `ERR_COACHING_NOT_FOUND`, `ERR_TEST_NOT_FOUND`,
        `ERR_ACCIDENT_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`,
        `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_PREMIUM_MODEL_NOT_FOUND`,
        `ERR_DOCUMENT_NOT_FOUND`, `ERR_TESTING_PERIOD_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_returns_404
        """
        resp = api.get(f"/safety/{kind}/{NON_EXISTENT_UUID}", headers=admin_headers)
        validate_error(resp, expected_error, 404)
