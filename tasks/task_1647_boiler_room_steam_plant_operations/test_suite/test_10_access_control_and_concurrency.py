"""Access control (authentication, RBAC), referential integrity, validation
ordering, and optimistic concurrency control."""
import pytest

from test_helpers import (
    ANON_HEADERS,
    NON_EXISTENT_UUID,
    ROLE_ONLY_HEADERS,
    ApiErrorId,
    create_boiler,
    create_draft_log_entry,
    create_plant,
    create_plant_payload,
    deliver_fuel,
    get_boiler,
    make_operator_headers,
    setup_plant_with_operators,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_x_user_role_header_returns_401(self, api):
        """PRD §2.1: "A request with a missing or malformed header — a role
        that is absent or not one of the three declared values, or an absent
        user id — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_x_user_role_header_returns_401
        """
        resp = api.get_plant(NON_EXISTENT_UUID, ANON_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

        resp = api.get_plant(NON_EXISTENT_UUID, ROLE_ONLY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRbac:
    def test_operator_cannot_create_plant_returns_403(self, api, operator_headers):
        """PRD §4: `POST /plants` is listed under Authorized Role(s)
        `PlantManager` only. PRD §2.7: "Authorization — the role is permitted
        for the endpoint per the RBAC matrix; otherwise `ERR_UNAUTHORIZED`
        (403)."

        Design: Corner/validations/operator_cannot_create_plant_returns_403
        """
        resp = api.create_plant(
            create_plant_payload(name="Forbidden", state_code="TX"),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_inspector_cannot_warm_boiler(self, api, inspector_headers):
        """PRD §4: `POST /plants/{plantId}/boilers/{boilerId}/warm` is listed
        under Authorized Role(s) `Operator` only. PRD §2.7: "Authorization —
        the role is permitted for the endpoint per the RBAC matrix; otherwise
        `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/inspector_cannot_warm_boiler
        """
        plant = create_plant(name="RBAC Plant")
        boiler = create_boiler(plant["id"], tag="B-RB")
        resp = api.warm_boiler(plant["id"], boiler["id"], inspector_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_plant_manager_cannot_verify_log_entry(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "Duty segregation on log voids — only a `PlantManager`
        may void a `VERIFIED` log entry, and only an `Operator` may verify;
        violations are rejected with `ERR_UNAUTHORIZED` (403)." PRD §3.2:
        "Verification of a boiler log entry is reserved for the `Operator`
        role".

        Design: Corner/rbac/plant_manager_cannot_verify_log_entry
        """
        plant, ops = setup_plant_with_operators(name="RBAC3 Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-RB3")
        entry = create_draft_log_entry(plant["id"], boiler["id"], ops[0]["id"])

        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], current["version"],
            plant_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestReferentialIntegrity:
    def test_err_referenced_not_found_on_bad_operator_id(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "An `Operator` records an entry with
        `recorded_by_operator_id` (which must exist, else
        `ERR_REFERENCED_NOT_FOUND`)".

        Design: Corner/errors/err_referenced_not_found_on_bad_operator_id
        """
        plant, ops = setup_plant_with_operators(name="Ref Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-REF")
        resp = api.create_log_entry(
            plant["id"], boiler["id"],
            {
                "recorded_by_operator_id": "11111111-1111-1111-1111-111111111111",
                "recorded_at": "2026-08-05T10:00:00Z",
                "header_pressure_reading_psi": 150,
                "steam_generated_lb": 1000,
                "fuel_burned_gal": 8,
                "feedwater_intake_gal": 130,
                "blowdown_gal": 10,
            },
            make_operator_headers(ops[0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND,
                       expected_status=422)


class TestValidationPriorityLicenseVsReferential:
    def test_license_wrong_state_precedes_referential_check(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "Every request is validated in a fixed, global order, and
        a request that fails several checks surfaces the error from the
        earliest stage." Stage 9 is "License jurisdiction gate — the calling
        operator's `license_state` must equal the plant's `state_code`; this
        applies to warming, bringing online, recording boiler log entries, and
        recording chemistry logs, and violations are rejected with
        `ERR_LICENSE_WRONG_STATE` (422)", and stage 11 is "Referential
        integrity ... otherwise `ERR_REFERENCED_NOT_FOUND` (422)." A request
        failing both reports ERR_LICENSE_WRONG_STATE.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_log_create
        """
        plant, ops = setup_plant_with_operators(name="PC2 Plant", count=1)
        # Re-enroll the caller as licensed in NY while the plant is TX.
        wrong_state_op = validate_success(
            api.create_operator(
                plant["id"],
                {
                    "full_name": "Op Wrong State",
                    "license_class": "CLASS_1",
                    "license_state": "NY",
                    "license_expires_on": "2027-01-01T00:00:00Z",
                },
                plant_manager_headers,
            ),
            expected_status=201,
        )
        boiler = create_boiler(plant["id"], tag="B-PC2")
        resp = api.create_log_entry(
            plant["id"], boiler["id"],
            {
                "recorded_by_operator_id": NON_EXISTENT_UUID,
                "recorded_at": "2026-08-05T10:00:00Z",
                "header_pressure_reading_psi": 150,
                "steam_generated_lb": 1000,
                "fuel_burned_gal": 8,
                "feedwater_intake_gal": 130,
                "blowdown_gal": 10,
            },
            make_operator_headers(wrong_state_op["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_WRONG_STATE)

    def test_referential_error_fires_in_isolation(self, api, plant_manager_headers):
        """PRD §2.7: "Referential integrity — foreign keys supplied in request
        bodies (`recorded_by_operator_id`, `triggered_boiler_id`, each element
        of `assigned_boiler_ids`) must resolve to existing entities; otherwise
        `ERR_REFERENCED_NOT_FOUND` (422)." With the caller properly licensed
        in the plant's state, only the referential check fails.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_log_create
        """
        plant, ops = setup_plant_with_operators(name="PC3 Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-PC3")
        resp = api.create_log_entry(
            plant["id"], boiler["id"],
            {
                "recorded_by_operator_id": NON_EXISTENT_UUID,
                "recorded_at": "2026-08-05T10:00:00Z",
                "header_pressure_reading_psi": 150,
                "steam_generated_lb": 1000,
                "fuel_burned_gal": 8,
                "feedwater_intake_gal": 130,
                "blowdown_gal": 10,
            },
            make_operator_headers(ops[0]["id"]),  # caller licensed in TX
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND,
                       expected_status=422)


class TestOptimisticConcurrency:
    def test_occ_stale_boiler_version_on_verify_returns_412(
        self, api, plant_manager_headers
    ):
        """PRD §2.8: "Verifying a boiler log entry requires the request to
        carry `expected_boiler_version`, holding the `version` of the parent
        boiler as the verifier last observed it; if the boiler's current
        `version` differs — for example because another writer has since
        verified a different log entry on the same boiler, which legitimately
        advances the boiler's totals, header pressure, efficiency, and version
        — the verification is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_boiler_version_on_verify_returns_412
        """
        plant, ops = setup_plant_with_operators(name="OCC Plant", count=2)
        recorder, verifier = ops
        boiler = create_boiler(plant["id"], tag="B-OCC")
        deliver_fuel(plant["id"], 1000)
        e1 = create_draft_log_entry(
            plant["id"], boiler["id"], recorder["id"],
            recorded_at="2026-08-05T10:00:00Z",
        )
        e2 = create_draft_log_entry(
            plant["id"], boiler["id"], recorder["id"],
            recorded_at="2026-08-05T11:00:00Z",
            steam_generated_lb=1100, fuel_burned_gal=9,
            feedwater_intake_gal=140, blowdown_gal=11,
        )

        stale_version = get_boiler(plant["id"], boiler["id"])["version"]
        # First verify succeeds and advances the boiler version.
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], e1["id"], stale_version,
            make_operator_headers(verifier["id"]),
        )
        validate_success(resp, expected_status=200)

        # Second verify with the pre-first-verify version is stale.
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], e2["id"], stale_version,
            make_operator_headers(verifier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        reread = validate_success(
            api.get_log_entry(
                plant["id"], boiler["id"], e2["id"], plant_manager_headers
            )
        )
        assert reread["status"] == "DRAFT", "rejected verify leaves entry DRAFT"

    def test_occ_correct_version_on_verify_succeeds(
        self, api, plant_manager_headers
    ):
        """PRD §2.8: "Verifying a boiler log entry requires the request to
        carry `expected_boiler_version`, holding the `version` of the parent
        boiler as the verifier last observed it". PRD §3.5: "the boiler's
        `version` increments by one".

        Design: Corner/cross_cutting_layers/occ_correct_version_on_verify_succeeds
        """
        plant, ops = setup_plant_with_operators(name="OCC2 Plant", count=2)
        recorder, verifier = ops
        boiler = create_boiler(plant["id"], tag="B-OCC2")
        deliver_fuel(plant["id"], 1000)
        entry = create_draft_log_entry(plant["id"], boiler["id"], recorder["id"])

        pre = get_boiler(plant["id"], boiler["id"])["version"]
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], pre,
            make_operator_headers(verifier["id"]),
        )
        verified = validate_success(resp, expected_status=200)
        assert verified["status"] == "VERIFIED"

        post = get_boiler(plant["id"], boiler["id"])["version"]
        assert post == pre + 1, (
            f"verify must increment boiler version by exactly one ({pre} -> {post})"
        )
