"""Horse intake, ration computation, defaults, and response envelope contracts."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    is_iso8601_timestamp,
    assert_horse, assert_daily_health_log,
    create_horse_payload, create_intake_evaluation_payload,
    daily_health_log_payload, adopter_payload,
    make_adopter_headers,
    intake_horse, protocols_for, register_adopter,
)

INTAKE = TEST_USERS["intake_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestHorseIntakeAndRation:
    def test_horse_creation_initial_state(self):
        """PRD §3.1: "A newly intaken horse lands in `QUARANTINE` status with
        `current_location` set to `QUARANTINE_STALL`, and the same act auto-creates
        an `ACTIVE` quarantine protocol for it: `min_days` of 14, `reason` of
        `INTAKE`, `start_date` stamped at the logical now, and `extension_days`
        starting at 0."
        PRD §3.1: "The ration starts from two percent of the horse's
        `estimated_weight_lbs`." (1000 lbs, BCS 3: 1000*0.02*1.30 = 26.0 capped at
        1000*0.025 = 25.0)

        Design: Corner/entities/horse_creation_initial_state
        """
        resp = api_client.create_horse(
            create_horse_payload(
                name="H", sex="MARE", breed_class="LIGHT",
                estimated_weight_lbs=1000, age_years=6, body_condition_score=3,
                training_level="GREEN"),
            INTAKE)
        data = validate_success(resp, 201)
        assert_horse(data)
        assert data["status"] == "QUARANTINE"
        assert data["current_location"] == "QUARANTINE_STALL"
        assert data["daily_feed_ration_lbs"] == pytest.approx(25.0, abs=1e-9)

        protocols = protocols_for(data["id"])
        assert len(protocols) == 1, "intake must auto-create exactly one protocol"
        proto = protocols[0]
        assert proto["status"] == "ACTIVE"
        assert proto["min_days"] == 14
        assert proto["reason"] == "INTAKE"
        assert proto["extension_days"] == 0

    def test_horse_defaults_applied(self):
        """PRD §3.1: "Three further inputs are optional: `temperament_score` (an
        integer from 1 to 10, defaulting to 5 when omitted), free-text
        `intake_reason`, and `bonded_companion_id`, which links the horse to
        another horse as a bonded-pair companion and stays null for unbonded
        animals."

        Design: Corner/entities/horse_defaults_applied
        """
        resp = api_client.create_horse(
            create_horse_payload(
                name="H", sex="GELDING", breed_class="DRAFT",
                estimated_weight_lbs=1400, age_years=9, body_condition_score=5,
                training_level="UNHANDLED"),
            INTAKE)
        data = validate_success(resp, 201)
        assert_horse(data)
        assert data["temperament_score"] == 5, "omitted temperament must default to 5"
        assert data["bonded_companion_id"] is None
        # 1400 * 0.02 = 28.0, no BCS factor, cap 35.0, floor 4.0
        assert data["daily_feed_ration_lbs"] == pytest.approx(28.0, abs=1e-9)

    def test_horse_ration_recompute_on_patch(self):
        """PRD §3.1: "An `IntakeCoordinator` or `Veterinarian` may also correct the
        horse's assessment fields after intake — `estimated_weight_lbs`,
        `body_condition_score`, `temperament_score`, `training_level`, and
        `bonded_companion_id` — and each such update reruns the ration computation
        when weight or condition changed and increments the horse's `version`."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by
        one with every modification, including mutations performed by automatic
        cascades."

        Design: Corner/entities/horse_ration_recompute_on_patch
        """
        horse = intake_horse(
            name="H", sex="MARE", breed_class="LIGHT", estimated_weight_lbs=1000,
            age_years=6, body_condition_score=3, training_level="GREEN")
        assert horse["daily_feed_ration_lbs"] == pytest.approx(25.0, abs=1e-9)
        v0 = horse["version"]

        # Temperament-only patch: ration unchanged, version still increments.
        r1 = validate_success(api_client.patch_horse(
            horse["id"], {"temperament_score": 7}, INTAKE))
        assert r1["daily_feed_ration_lbs"] == pytest.approx(25.0, abs=1e-9)
        assert r1["version"] == v0 + 1, "every modification increments version by one"

        # BCS change: ration recomputes (1000*0.02*0.80 = 16.0), version +1 again.
        r2 = validate_success(api_client.patch_horse(
            horse["id"], {"body_condition_score": 8}, INTAKE))
        assert r2["daily_feed_ration_lbs"] == pytest.approx(16.0, abs=1e-9)
        assert r2["version"] == v0 + 2

    def test_horse_get_not_found_returns_404(self):
        """PRD §2.7: "Identifiers embedded in the URL path are resolved left to
        right; the first missing one fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/horse_get_not_found_returns_404
        """
        resp = api_client.get_horse(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_invalid_enum_values_rejected(self):
        """PRD §2.7: "Required fields are present, enum values belong to their
        declared sets, and numeric ranges hold — weight above zero, body condition
        scores within 1 through 9, quarantine minimum days within 1 through 60,
        suffering scores within 1 through 10, a pledge that is a positive integer,
        end times and dates strictly after their starts, non-empty skill lists.
        Violations fail with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enum_values_rejected
        """
        bad_horse = create_horse_payload(sex="GELDINGX")
        resp1 = api_client.create_horse(bad_horse, INTAKE)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST, 400)

        horse = intake_horse()
        resp2 = api_client.create_intake_evaluation(
            create_intake_evaluation_payload(
                horse["id"], evaluation_type="DENTAL",
                scheduled_date="2026-08-02T00:00:00Z"),
            INTAKE)
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_health_log_immutable_no_version(self):
        """PRD §2.5: "Two resources are append-only ledgers and depart from this
        convention: a `DailyHealthLog` record and a `FeedDayClose` record carry
        only `id` and `created_at`. Both `updated_at` and `version` are absent on
        them — a health log, once recorded, is never updated, and a day-close
        record is never revisited."

        Design: Corner/entities/health_log_immutable_no_version
        """
        horse = intake_horse()
        l1 = validate_success(api_client.create_daily_health_log(
            daily_health_log_payload(horse["id"], temp_f=101.0, appetite="NORMAL"),
            INTAKE), 201)
        assert_daily_health_log(l1)
        l2 = validate_success(api_client.create_daily_health_log(
            daily_health_log_payload(horse["id"], temp_f=101.2, appetite="REDUCED"),
            INTAKE), 201)
        assert_daily_health_log(l2)
        assert l1["id"] != l2["id"], "append-only: both entries persist"

        listed, meta = validate_paginated(api_client.list_daily_health_logs(INTAKE))
        ids = {row["id"] for row in listed}
        assert {l1["id"], l2["id"]} <= ids
        for row in listed:
            assert "version" not in row and "updated_at" not in row

    def test_adopter_registration_identity_establishing(self):
        """PRD §2.1: "The three registration endpoints — `POST /rescue-ops/adopters`,
        `POST /rescue-ops/sponsors`, and `POST /rescue-ops/volunteers` — are
        identity-establishing: on these calls `X-User-ID` is not resolved against
        any existing entity, the server mints the new entity's `id`, and the caller
        adopts that minted id thereafter."
        PRD §3.3: "A new adopter is `ACTIVE`."

        Design: Corner/entities/adopter_registration_identity_establishing
        """
        resp = api_client.create_adopter(
            adopter_payload(full_name="Ad N", contact_email="an@x.com",
                            experience_level="NOVICE", has_stall_facility=False),
            TEST_USERS["adopter_registration_headers"])
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"

        got = validate_success(api_client.get_adopter(
            data["id"], make_adopter_headers(data["id"])))
        assert got["id"] == data["id"], "minted id must work as identity thereafter"


    def test_ration_bcs_factor_boundaries(self):
        """PRD §3.1: "The ration starts from two percent of the horse's
        `estimated_weight_lbs`. When the horse's `body_condition_score` is 3 or
        lower, that base is increased by thirty percent; when the score is 7 or
        higher, the base is instead reduced by twenty percent. The adjusted figure
        is then capped at two and a half percent of `estimated_weight_lbs` and
        floored at 4.0 pounds, and the stored ration is that result rounded half
        up to one decimal place."

        Design: Corner/calculations/ration_bcs_factor_boundaries
        """
        gain = intake_horse(name="G", body_condition_score=3)
        assert gain["daily_feed_ration_lbs"] == pytest.approx(25.0, abs=1e-9), (
            "BCS 3: min(1000*0.02*1.30 = 26.0, 1000*0.025 = 25.0) -> cap binds")
        neutral = intake_horse(name="N", body_condition_score=4)
        assert neutral["daily_feed_ration_lbs"] == pytest.approx(20.0, abs=1e-9), (
            "BCS 4: no branch")
        reduce = intake_horse(name="F", body_condition_score=7)
        assert reduce["daily_feed_ration_lbs"] == pytest.approx(16.0, abs=1e-9), (
            "BCS 7: 1000*0.02*0.80")


class TestImmediateConsistencyAndEnvelope:
    def test_same_request_mutation_visibility(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.1: "each such update reruns the ration computation when weight or
        condition changed and increments the horse's `version`."

        Design: Corner/consistency_model/same_request_mutation_visibility
        """
        created = validate_success(api_client.create_horse(
            create_horse_payload(
                name="H", sex="MARE", breed_class="LIGHT",
                estimated_weight_lbs=1000, age_years=6, body_condition_score=3,
                training_level="GREEN"),
            INTAKE), 201)
        assert created["status"] == "QUARANTINE"
        assert created["daily_feed_ration_lbs"] == pytest.approx(25.0, abs=1e-9)

        patched = validate_success(api_client.patch_horse(
            created["id"], {"body_condition_score": 8}, INTAKE))
        assert patched["daily_feed_ration_lbs"] == pytest.approx(16.0, abs=1e-9)
        assert patched["version"] == created["version"] + 1

    def test_response_envelope_shape(self):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape
        """
        horse = intake_horse()
        ok_resp = api_client.get_horse(horse["id"], INTAKE)
        ok_body = ok_resp.json()
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(ok_body["meta"]["api_request_timestamp"])
        assert ok_body["response_type"] == "object"
        assert ok_body["data"]["id"] == horse["id"]

        err_resp = api_client.get_horse(NON_EXISTENT_UUID, INTAKE)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()

    def test_horses_list_pagination(self):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items before returning the page and defaults
        to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/horses_list_pagination
        """
        for name in ("A", "B", "C"):
            intake_horse(name=name)
        page1, meta1 = validate_paginated(
            api_client.list_horses(INTAKE, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_horses(INTAKE, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
