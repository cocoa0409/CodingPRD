"""Entity-record contract tests: creation echo, retrieval, listing envelope,
required fields, defaults, computed and system fields, immutability, and the
relationship graph between screenings, findings, referrals, campaigns and devices.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    CLOCK_START_UTC,
    FIRMWARE_ENGINEER,
    ApiErrorId,
    assert_event_common,
    assert_pagination_meta,
    assert_patient,
    make_licensed_audiologist_headers,
    make_patient_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical California policy: OTC and telehealth permitted, 18-year floor,
# a 45-day statutory trial, a 10 percent flat restocking share with no cap,
# non-refundable shipping, 180-day clearance validity and no waiver requirement.
POLICY_CA_PAYLOAD = {
    "state_code": "CA",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 18,
    "trial_period_days": 45,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.1,
    "restocking_fee_cap_cents": 0,
    "shipping_refundable": False,
    "referral_validity_days": 180,
    "waiver_required": False,
    "max_loss_damage_claims": 2,
}

CLEAN_MEASUREMENTS = {
    "pure_tone_avg_db": 40.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
    "symptom_codes": [],
}

# An asymmetry of exactly 15.0 dB is the inclusive boundary that emits a single
# mandatory SUDDEN_UNILATERAL_LOSS finding without relying on any symptom code.
ASYMMETRY_RED_FLAG_MEASUREMENTS = dict(CLEAN_MEASUREMENTS, asymmetry_db=15.0)


def _create_policy_ca(api):
    return validate_success(api.create_state_policy(dict(POLICY_CA_PAYLOAD), ADMIN), 201)


def _register_patient(api, policy_id, email, full_name="Test Patient", age_years=70):
    payload = {
        "state_policy_id": policy_id,
        "email": email,
        "full_name": full_name,
        "age_years": age_years,
    }
    return validate_success(api.create_patient(payload, CARE_OPS), 201)


def _screen(api, patient_id, measurements):
    """Start, measure and submit one screening as the owning patient."""
    headers = make_patient_headers(patient_id)
    session = validate_success(api.start_screening_session(patient_id, {}, headers), 201)
    validate_success(api.update_screening_session(session["id"], dict(measurements), headers))
    return validate_success(api.submit_screening_session(session["id"], headers))


def _assert_logical_clock_instant(actual, expected_instant_prefix, field):
    """Logical-clock instants are ISO 8601 UTC; compare on the second."""
    assert isinstance(actual, str) and actual.startswith(expected_instant_prefix), (
        f"{field} should be stamped from the logical clock at "
        f"{expected_instant_prefix}, got {actual!r}"
    )


class TestEntityCreationAndRetrieval:
    def test_state_policy_creation_echoes_every_declared_field(self, api):
        """PRD §2.11: "Creation endpoints return 201 with the newly created resource."
        PRD §3.1: "It sets the `min_age_years` floor for candidacy, which defaults to 18, and the statutory `trial_period_days` minimum, which must be at least 30 and at most 90."
        PRD §3.1: "`restocking_fee_mode` is one of `FLAT_PCT`, `PRORATED_DAILY` or `PROHIBITED`."
        PRD §3.1: "It declares whether the patient must acknowledge a medical-evaluation waiver before ordering (`waiver_required`, default false), how many days a licensed-provider clearance stays valid (`referral_validity_days`, default 180 — a little under six months), and the lifetime `max_loss_damage_claims` ceiling per device, which defaults to 2."
        PRD §3.1: "A policy is never hard-deleted; retiring one sets `is_retired` (a system-managed flag defaulting to false), leaving it queryable and leaving it in force on any order that already pinned it."
        PRD §2.4: "Almost every resource additionally exposes `updated_at`, refreshed on every mutation and formatted identically, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

        Design: Corner/entities/entity_state_policy_create_returns_201_with_all_declared_fields
        """
        set_clock(CLOCK_START_UTC)

        data = validate_success(api.create_state_policy(dict(POLICY_CA_PAYLOAD), ADMIN), 201)

        assert data["state_code"] == "CA", "state_code must be echoed verbatim"
        assert data["trial_period_days"] == 45, "trial_period_days must be echoed verbatim"
        assert data["restocking_fee_mode"] == "FLAT_PCT", "restocking_fee_mode must be echoed verbatim"
        assert data["restocking_fee_pct"] == 0.1, "restocking_fee_pct must be echoed verbatim"
        assert data["shipping_refundable"] is False, "shipping_refundable must be echoed verbatim"
        assert data["referral_validity_days"] == 180, "referral_validity_days must be echoed verbatim"
        assert data["max_loss_damage_claims"] == 2, "max_loss_damage_claims must be echoed verbatim"
        assert data["is_retired"] is False, "a newly created policy is not retired"
        assert data["version"] == 1, "a newly created row starts at version 1"
        assert isinstance(data["id"], str) and data["id"], "the server must mint a non-empty id"

    def test_registered_patient_read_returns_stored_row_with_denormalized_state_code(self, api):
        """PRD §3.1: "Registering a patient supplies the governing `state_policy_id` along with `email`, `full_name` and `age_years`."
        PRD §3.1: "The server denormalizes `state_code` onto the patient from the chosen policy and refreshes that copy whenever `state_policy_id` changes on an amendment."
        PRD §3.1: "A freshly registered patient's `status` is `REGISTERED`, `candidacy_risk_score` is 0, `candidacy_risk_band` is `LOW`, `candidacy_risk_variant` is `PROVISIONAL_SELF_REPORTED`, `advisory_weight_total` is 0, `open_mandatory_flag_count` is 0, `lifetime_return_count` is 0, `screening_attempt_count` is 0, and both `waiver_acknowledged_at` and `deactivated_at` are null."

        Design: Corner/entities/entity_patient_retrieval_returns_stored_row_by_id
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)
        patient = _register_patient(api, policy["id"], "ret1@x.test", full_name="Ret One", age_years=70)

        data = validate_success(api.get_patient(patient["id"], CARE_OPS))

        assert_patient(data)
        assert data["id"] == patient["id"], "the read must return the row written by registration"
        assert data["email"] == "ret1@x.test", "email must round-trip"
        assert data["full_name"] == "Ret One", "full_name must round-trip"
        assert data["age_years"] == 70, "age_years must round-trip"
        assert data["state_policy_id"] == policy["id"], "the governing policy must round-trip"
        assert data["state_code"] == "CA", "state_code must be denormalized from the chosen policy"
        assert data["status"] == "REGISTERED", "a freshly registered patient's status is REGISTERED"


class TestEntityListing:
    def test_device_listing_reports_total_count_and_has_more_beyond_the_page(self, api):
        """PRD §2.3: "Every list endpoint accepts two optional query parameters, `limit` and `offset`."
        PRD §2.3: "The `meta` block of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when `offset` plus the number of returned rows is below `total_count`)."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/entities/entity_devices_listing_pagination_envelope_and_has_more
        """
        set_clock(CLOCK_START_UTC)
        for serial in ("SN-L001", "SN-L002", "SN-L003"):
            validate_success(
                api.create_device({"serial_number": serial, "model": "NEO", "firmware_version": "4.0.0"}, ADMIN),
                201,
            )

        resp = api.list_devices(ADMIN, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)

        assert resp.json()["response_type"] == "array", "a list endpoint responds with response_type array"
        assert len(data) == 2, f"limit=2 must return exactly 2 rows, got {len(data)}"
        assert_pagination_meta(meta, 2, 0, 3, True)

    def test_device_listing_applies_default_limit_ten_and_offset_zero(self, api):
        """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0."
        PRD §2.3: "The `meta` block of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when `offset` plus the number of returned rows is below `total_count`)."

        Design: Corner/entities/entity_devices_listing_default_limit_is_ten_and_offset_zero
        """
        set_clock(CLOCK_START_UTC)
        for serial in ("SN-D001", "SN-D002", "SN-D003"):
            validate_success(
                api.create_device({"serial_number": serial, "model": "NEO", "firmware_version": "4.0.0"}, ADMIN),
                201,
            )

        data, meta = validate_paginated(api.list_devices(ADMIN))

        assert_pagination_meta(meta, 10, 0, 3, False)
        assert len(data) == 3, f"all 3 rows fit inside the default page, got {len(data)}"


class TestEntityValidationAndDefaults:
    def test_unknown_patient_path_id_is_resource_not_found(self, api):
        """PRD §2.9: "Every path-segment resource exists, validated left to right, on every endpoint with path parameters — otherwise `ERR_RESOURCE_NOT_FOUND` (404)."

        Design: Corner/entities/entity_patient_not_found_on_unknown_uuid
        """
        set_clock(CLOCK_START_UTC)

        resp = api.get_patient("00000000-0000-4000-8000-000000000009", CARE_OPS)

        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_patient_registration_without_age_years_is_rejected(self, api):
        """PRD §2.9: "Every required body field is present with its declared type and inside its declared numeric bounds, on every POST and PATCH endpoint — otherwise `ERR_VALIDATION` (422)."
        PRD §3.1: "Registering a patient supplies the governing `state_policy_id` along with `email`, `full_name` and `age_years`."

        Design: Corner/entities/entity_patient_missing_required_age_years_is_err_validation
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)

        resp = api.create_patient(
            {"state_policy_id": policy["id"], "email": "noage@x.test", "full_name": "No Age"},
            CARE_OPS,
        )

        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_minted_device_starts_with_zero_loss_damage_claims(self, api):
        """PRD §3.5: "Devices are minted independently of orders, with a globally unique `serial_number`, a `model` and an optional `firmware_version` that defaults to `4.0.0`."
        PRD §3.5: "Its `shipped_at`, `warranty_expires_at` and `replaced_by_device_id` are null until the relevant event occurs, and `age_months_at_last_claim` and `loss_damage_claims_approved` start at 0."
        PRD §2.4: "Almost every resource additionally exposes `updated_at`, refreshed on every mutation and formatted identically, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

        Design: Corner/entities/entity_device_defaults_firmware_and_claim_counter_applied
        """
        set_clock(CLOCK_START_UTC)

        data = validate_success(
            api.create_device({"serial_number": "SN-DEF01", "model": "NEO", "firmware_version": "4.0.0"}, ADMIN),
            201,
        )

        assert data["loss_damage_claims_approved"] == 0, "the lifetime claim counter starts at 0"
        assert data["firmware_version"] == "4.0.0", "the supplied firmware_version must round-trip"
        assert data["version"] == 1, "a newly minted device starts at version 1"

    def test_state_policy_rejects_restocking_fee_mode_outside_its_value_set(self, api):
        """PRD §3.1: "`restocking_fee_mode` is one of `FLAT_PCT`, `PRORATED_DAILY` or `PROHIBITED`."
        PRD §2.9: "Every supplied enum value is a member of its field's declared value set, on every POST and PATCH endpoint with enum inputs — otherwise `ERR_INVALID_ENUM_VALUE` (422)."

        Design: Corner/entities/entity_state_policy_invalid_restocking_fee_mode_enum_rejected
        """
        set_clock(CLOCK_START_UTC)
        payload = dict(POLICY_CA_PAYLOAD, state_code="OR", restocking_fee_mode="SLIDING_SCALE")

        resp = api.create_state_policy(payload, ADMIN)

        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)

    def test_state_policy_rejects_negative_restocking_fee_cap(self, api):
        """PRD §3.1: "Either way, `restocking_fee_cap_cents` (non-negative, defaulting to 0) is an absolute ceiling on what a single return may retain, where a stored 0 means "no cap at all" rather than "retain nothing"."
        PRD §2.9: "This also covers a `scheduled_end_utc` that is not strictly after `scheduled_start_utc`, and any negative money or day count."

        Design: Corner/entities/entity_state_policy_negative_money_field_rejected
        """
        set_clock(CLOCK_START_UTC)
        payload = dict(POLICY_CA_PAYLOAD, state_code="WA", restocking_fee_cap_cents=-1)

        resp = api.create_state_policy(payload, ADMIN)

        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestComputedAndSystemFields:
    def test_submitted_screening_computes_ordinal_outcome_and_candidacy_score(self, api):
        """PRD §3.2: "Starting one from `REGISTERED` requires that the patient's governing policy is not retired, moves the patient from `REGISTERED` to `SCREENING_IN_PROGRESS`, and creates a `ScreeningSession` in `DRAFT` with `attempt_ordinal` 1."
        PRD §3.2: "Submitting the session requires all five measurement fields to be non-null and the patient to be in `SCREENING_IN_PROGRESS`; it stamps `submitted_at`, advances the session `IN_PROGRESS → SUBMITTED`, and then — inside the very same request — scores it and advances `SUBMITTED → SCORED`, stamping `scored_at`."
        PRD §3.2: "Otherwise, with an empty finding set, the outcome is `PASS`."
        PRD §3.2: "That transition recomputes `candidacy_risk_score` under the `PROVISIONAL_SELF_REPORTED` variant, sets `candidacy_risk_variant` to `PROVISIONAL_SELF_REPORTED`, derives `candidacy_risk_band` from the new score, refreshes `advisory_weight_total`, sets `open_mandatory_flag_count` to 0, and increments `screening_attempt_count`."
        PRD §3.2: "The `candidacy_risk_band` is `LOW` when the score is strictly below 35.0, `MODERATE` when it is at least 35.0 and strictly below 65.0, and `HIGH` when it is at least 65.0."

        Design: Corner/entities/entity_screening_computed_candidacy_score_ignores_client_supplied_value
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)
        patient = _register_patient(api, policy["id"], "comp@x.test", full_name="Comp One", age_years=70)
        patient_headers = make_patient_headers(patient["id"])
        session = validate_success(api.start_screening_session(patient["id"], {}, patient_headers), 201)
        # attempt_ordinal and screening_outcome are computed, so the client values must be discarded.
        validate_success(
            api.update_screening_session(
                session["id"],
                dict(CLEAN_MEASUREMENTS, attempt_ordinal=99, screening_outcome="RED_FLAG"),
                patient_headers,
            )
        )

        scored = validate_success(api.submit_screening_session(session["id"], patient_headers))

        assert scored["status"] == "SCORED", "submit scores the session inside the same request"
        assert scored["attempt_ordinal"] == 1, "a first attempt keeps attempt_ordinal 1"
        assert scored["screening_outcome"] == "PASS", "an empty finding set scores PASS"
        _assert_logical_clock_instant(scored["scored_at"], "2026-08-01T00:00:00", "ScreeningSession.scored_at")

        after = validate_success(api.get_patient(patient["id"], CARE_OPS))
        assert after["status"] == "CANDIDATE_APPROVED", "a PASS moves the patient to CANDIDATE_APPROVED"
        assert after["candidacy_risk_score"] == 39.3, (
            f"candidacy_risk_score must be 39.3 for the provisional variant, got {after['candidacy_risk_score']}"
        )
        assert after["candidacy_risk_band"] == "MODERATE", "39.3 lands in the MODERATE band"
        assert after["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
            "a screening submit writes the provisional variant"
        )

    def test_state_policy_ignores_client_supplied_id_and_version(self, api):
        """PRD §2.4: "Every persisted resource exposes an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits."
        PRD §2.4: "Almost every resource additionally exposes `updated_at`, refreshed on every mutation and formatted identically, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

        Design: Corner/entities/entity_state_policy_system_fields_ignore_client_supplied_id_and_version
        """
        set_clock(CLOCK_START_UTC)
        payload = {
            "id": "11111111-1111-4111-8111-111111111111",
            "version": 77,
            "state_code": "NV",
            "otc_sales_permitted": True,
            "telehealth_fitting_permitted": True,
            "min_age_years": 18,
            "trial_period_days": 30,
            "restocking_fee_mode": "FLAT_PCT",
            "restocking_fee_pct": 0.05,
            "restocking_fee_cap_cents": 0,
            "shipping_refundable": True,
            "referral_validity_days": 90,
            "waiver_required": False,
            "max_loss_damage_claims": 1,
        }

        data = validate_success(api.create_state_policy(payload, ADMIN), 201)

        assert data["version"] == 1, "version is server-managed and starts at 1"
        assert data["id"] != "11111111-1111-4111-8111-111111111111", "the id must be server-minted"
        assert data["state_code"] == "NV", "the input fields are still honoured"


class TestImmutableFindingEvents:
    def test_red_flag_finding_exposes_no_version_or_updated_at(self, api):
        """PRD §2.4: "The single exception is `RedFlagFinding`: a finding is an immutable audit event, so it carries only `id` and `created_at` — neither `updated_at` nor `version` exists on a finding, and no endpoint mutates one after emission."
        PRD §3.2: "Finally, if `asymmetry_db` is at least 15.0 — again inclusive — it emits `SUDDEN_UNILATERAL_LOSS`, mandatory, weight 0.0; when both the sudden-loss symptom and the asymmetry threshold are present, exactly one finding with that code is emitted, not two, because findings are deduplicated on `code`."
        PRD §3.2: "Every `RedFlagFinding` records the `screening_session_id` that produced it and leaves `cleared_by_referral_id` null while the finding is open."
        PRD §3.2: "Scoring runs a **finding detection table in exactly this order**, appending a `RedFlagFinding` for each condition that holds, each finding carrying a `code`, a `severity` and a `weight`, and each stamped with `detected_at` from the logical clock."

        Design: Corner/entities/entity_red_flag_finding_is_immutable_event_with_no_version_field
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)
        patient = _register_patient(api, policy["id"], "imm@x.test", full_name="Imm One", age_years=70)
        session = _screen(api, patient["id"], ASYMMETRY_RED_FLAG_MEASUREMENTS)

        data, meta = validate_paginated(api.list_screening_red_flag_findings(session["id"], CARE_OPS))

        assert meta["total_count"] == 1, f"exactly one finding must be emitted, got {meta['total_count']}"
        finding = data[0]
        assert_event_common(finding, "RedFlagFinding")
        assert finding["screening_session_id"] == session["id"], "the finding records its producing session"
        assert finding["code"] == "SUDDEN_UNILATERAL_LOSS", (
            f"an asymmetry of 15.0 dB emits SUDDEN_UNILATERAL_LOSS, got {finding['code']!r}"
        )
        assert finding["severity"] == "MANDATORY_REFERRAL", "the asymmetry finding is a mandatory referral"
        assert finding["weight"] == 0.0, "a mandatory finding carries weight 0.0"
        assert finding["cleared_by_referral_id"] is None, "an open finding has no clearing referral"
        _assert_logical_clock_instant(finding["detected_at"], "2026-08-01T00:00:00", "RedFlagFinding.detected_at")
        assert "version" not in finding, "a finding is immutable and exposes no version"
        assert "updated_at" not in finding, "a finding is immutable and exposes no updated_at"


class TestEntityRelationships:
    def test_screening_under_unknown_patient_path_is_resource_not_found(self, api):
        """PRD §2.5: "Nested paths are resolved strictly left to right."
        PRD §2.9: "An acting `Patient`'s `X-User-ID` equals the `patient_id` of the targeted resource, directly or transitively through `device_order_id`, `trial_period_id` or `device_id`. This applies to every `Patient`-callable endpoint that targets an existing resource — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."
        PRD §2.9: "Every path-segment resource exists, validated left to right, on every endpoint with path parameters — otherwise `ERR_RESOURCE_NOT_FOUND` (404)."

        Design: Corner/entities/entity_screening_parent_patient_must_exist_else_resource_not_found
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)
        patient = _register_patient(api, policy["id"], "par@x.test", full_name="Par One", age_years=70)

        resp = api.start_screening_session(
            "00000000-0000-4000-8000-0000000000aa", {}, make_patient_headers(patient["id"])
        )

        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_patient_registration_with_unknown_state_policy_is_reference_not_found(self, api):
        """PRD §2.5: "A foreign key supplied in a request body rather than a path — `state_policy_id`, `patient_id`, `provider_id`, `device_order_id`, `device_id`, `provider_referral_id`, `repair_order_id`, `care_plan_subscription_id`, `originating_repair_order_id`, `appeal_of_claim_id`, `firmware_rollout_id`, `supersedes_session_id` — that resolves to no row produces `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_patient_body_fk_state_policy_unknown_is_reference_not_found
        """
        set_clock(CLOCK_START_UTC)

        resp = api.create_patient(
            {
                "state_policy_id": "00000000-0000-4000-8000-0000000000bb",
                "email": "fk@x.test",
                "full_name": "Fk One",
                "age_years": 70,
            },
            CARE_OPS,
        )

        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_one_device_enrolled_in_two_campaigns_yields_two_distinct_rollouts(self, api):
        """PRD §3.9: "An engineer may enrol a single device by hand, naming a `device_id` and carrying `expected_device_version` per §2.7. The enrolment creates a rollout in `PENDING` whose `selection_rank` is one more than the campaign's current `rollout_count` and whose `from_version_observed` is the device's current `firmware_version`, increments the device's `version` by one, and recomputes `rollout_count`."
        PRD §3.9: "Every rollout row names its owning campaign through `firmware_campaign_id` and its target unit through `device_id`, and rollouts may be listed filtered by either."
        PRD §2.9: "A firmware install is only offered when the subscriber's `firmware_auto_update_enabled` is true or the campaign's `is_mandatory_safety` is true, on `POST /firmware-rollouts/{id}/offer` and `POST /firmware-campaigns/{campaign_id}/manual-enrollments` — otherwise `ERR_AUTO_UPDATE_NOT_CONSENTED` (422)."

        Design: Corner/entities/entity_topology_graph_firmware_rollout_junction_links_campaign_and_device
        """
        set_clock(CLOCK_START_UTC)
        device = validate_success(
            api.create_device({"serial_number": "SN-J001", "model": "NEO", "firmware_version": "4.0.0"}, ADMIN),
            201,
        )
        campaign_one = validate_success(
            api.create_firmware_campaign(
                {
                    "campaign_code": "FWJ-1",
                    "model": "NEO",
                    "from_version": "4.0.0",
                    "to_version": "4.1.0",
                    "window_start_utc": "2026-08-05T00:00:00Z",
                    "window_end_utc": "2026-08-06T00:00:00Z",
                    "batch_size": 5,
                    "max_concurrent_installs": 5,
                    "failure_rate_abort_pct": 50.0,
                    "is_mandatory_safety": True,
                },
                FIRMWARE_ENGINEER,
            ),
            201,
        )
        campaign_two = validate_success(
            api.create_firmware_campaign(
                {
                    "campaign_code": "FWJ-2",
                    "model": "NEO",
                    "from_version": "4.0.0",
                    "to_version": "4.1.1",
                    "window_start_utc": "2026-08-20T00:00:00Z",
                    "window_end_utc": "2026-08-21T00:00:00Z",
                    "batch_size": 5,
                    "max_concurrent_installs": 5,
                    "failure_rate_abort_pct": 50.0,
                    "is_mandatory_safety": True,
                },
                FIRMWARE_ENGINEER,
            ),
            201,
        )
        before_first = validate_success(api.get_device(device["id"], FIRMWARE_ENGINEER))
        first_rollout = validate_success(
            api.create_manual_enrollment(
                campaign_one["id"],
                {"device_id": device["id"], "expected_device_version": before_first["version"]},
                FIRMWARE_ENGINEER,
            ),
            201,
        )
        before_second = validate_success(api.get_device(device["id"], FIRMWARE_ENGINEER))

        second_rollout = validate_success(
            api.create_manual_enrollment(
                campaign_two["id"],
                {"device_id": device["id"], "expected_device_version": before_second["version"]},
                FIRMWARE_ENGINEER,
            ),
            201,
        )

        assert second_rollout["device_id"] == device["id"], "the rollout names its target unit"
        assert second_rollout["firmware_campaign_id"] == campaign_two["id"], (
            "the rollout names its owning campaign"
        )
        assert second_rollout["id"] != first_rollout["id"], (
            "enrolling the same device in a second campaign creates a distinct rollout row"
        )
        assert second_rollout["status"] == "PENDING", "a manual enrolment creates the rollout in PENDING"

    def test_clearance_closes_the_screening_finding_referral_cycle(self, api):
        """PRD §3.3: "Hop 1 of that cascade opens a `ProviderReferral` in `OPEN`, populating `reason_codes` with the `code` values of the triggering findings ordered by their `detected_at` ascending, naming the `triggering_screening_session_id`, stamping `issued_at` from the logical clock, and computing `expires_at` as `issued_at` plus the patient's policy `referral_validity_days` days."
        PRD §3.3: "A `CLEARED` determination moves the referral `EVALUATED → CLEARED` and requires the clock to be strictly before `expires_at`; it stamps `cleared_by_referral_id` on every still-open finding whose `code` appears in the referral's `reason_codes`, increments the referral's `cleared_finding_count` accordingly, recomputes the patient's `open_mandatory_flag_count` (which should now be zero) and `advisory_weight_total`, recomputes `candidacy_risk_score` under the `PROVIDER_ADJUSTED` variant and sets `candidacy_risk_variant` to `PROVIDER_ADJUSTED`, moves the patient `REFERRAL_REQUIRED → PROVIDER_CLEARED`, and releases every one of that patient's held orders from `MEDICAL_HOLD` back to `PENDING_FIT_CONFIRM` with `medical_hold_reason` cleared — no inventory moves on release, because the reservation was already given back when the hold was applied."
        PRD §3.4: "For a `REFERRAL_EVALUATION`, completion drives the referral `SCHEDULED → EVALUATED`."

        Design: Corner/entities/entity_topology_graph_screening_finding_referral_cycle_closes
        """
        set_clock(CLOCK_START_UTC)
        policy = _create_policy_ca(api)
        provider = validate_success(
            api.create_provider(
                {
                    "provider_type": "LICENSED_AUDIOLOGIST",
                    "npi": "1000000001",
                    "full_name": "Aud One",
                    "licensed_state_codes": ["CA"],
                    "daily_capacity_minutes": 240,
                    "buffer_minutes": 10,
                },
                ADMIN,
            ),
            201,
        )
        patient = _register_patient(api, policy["id"], "cyc@x.test", full_name="Cyc One", age_years=70)
        patient_headers = make_patient_headers(patient["id"])
        screening = _screen(api, patient["id"], ASYMMETRY_RED_FLAG_MEASUREMENTS)
        referrals, _ = validate_paginated(
            api.list_provider_referrals(CARE_OPS, params={"patient_id": patient["id"]})
        )
        assert referrals, "a red-flag screening must open a provider referral"
        referral_id = referrals[0]["id"]
        session = validate_success(
            api.create_remote_fitting_session(
                {
                    "patient_id": patient["id"],
                    "session_type": "REFERRAL_EVALUATION",
                    "scheduled_start_utc": "2026-08-03T10:00:00Z",
                    "scheduled_end_utc": "2026-08-03T10:30:00Z",
                    "provider_id": provider["id"],
                    "provider_referral_id": referral_id,
                },
                patient_headers,
            ),
            201,
        )
        set_clock("2026-08-03T10:05:00Z")
        provider_headers = make_licensed_audiologist_headers(provider["id"])
        validate_success(api.start_fitting_session(session["id"], provider_headers))
        validate_success(api.complete_fitting_session(session["id"], {}, provider_headers))

        cleared = validate_success(
            api.record_referral_determination(
                referral_id,
                {"clearance_outcome": "CLEARED", "clearance_note": "no pathology"},
                provider_headers,
            )
        )

        assert cleared["status"] == "CLEARED", "a CLEARED determination moves the referral to CLEARED"
        assert cleared["triggering_screening_session_id"] == screening["id"], (
            "the referral points back at the screening that triggered it"
        )
        assert cleared["cleared_finding_count"] == 1, "the single mandatory finding was retired"

        retired, retired_meta = validate_paginated(api.list_referral_cleared_findings(referral_id, CARE_OPS))
        assert retired_meta["total_count"] == 1, "exactly one finding was retired by this referral"
        assert retired[0]["screening_session_id"] == screening["id"], (
            "the retired finding still names its producing screening"
        )

        _, by_referral_meta = validate_paginated(
            api.list_red_flag_findings(CARE_OPS, params={"cleared_by_referral_id": referral_id})
        )
        assert by_referral_meta["total_count"] == 1, (
            "the finding is reachable from the clearing referral through cleared_by_referral_id"
        )

        after = validate_success(api.get_patient(patient["id"], CARE_OPS))
        assert after["status"] == "PROVIDER_CLEARED", "clearance moves the patient to PROVIDER_CLEARED"
        assert after["open_mandatory_flag_count"] == 0, "no mandatory flag remains open after clearance"
