"""Entity shape: server-assigned fields, declared defaults and reference checks.

The contract fixes which fields a client may supply and which the server mints.
Accounts, properties, devices and contacts each declare defaults that must be
applied rather than hard-coded, a telemetry reading is deliberately excluded from
the version/updated_at pair, and every reference in a body has to resolve — and,
where two aggregates meet, cohere.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_device,
    assert_emergency_contact,
    assert_homeowner,
    assert_property,
    assert_telemetry_reading,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import (
    COVERAGE_MINUTES_PER_READING,
    DEFAULT_CLOCK_UTC,
    FIXTURE_CLOCK_UTC,
    TEST_DEFAULTS,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
)
from test_helpers.factories import (
    claim_payload,
    device_payload,
    emergency_contact_payload,
    homeowner_payload,
    irrigation_window_payload,
    property_payload,
)
from test_helpers.fixtures import (
    create_buyer,
    create_device,
    create_homeowner,
    create_policy,
    create_property,
    create_second_property,
    ingest_burst_reading,
    ingest_learning_samples,
    read_device,
    read_events,
    read_homeowner,
    read_irrigation_windows,
    read_telemetry,
    set_clock,
    setup_armed_device,
    setup_registered_device,
    verify_install,
)
from test_helpers.test_users import (
    make_gateway_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()
TECH = make_installer_tech_headers()


class TestHomeownerCreation:
    def test_registering_an_account_mints_every_system_field(self, api: ApiClient):
        """The client supplies three fields; the server owns the rest.

        "The new account is created with `account_state` equal to `ACTIVE`,
        `deactivated_at` null, and `owned_property_count` at 0."
        "Every persisted resource is identified by `id`, a server-minted UUID carrying
        no type prefix — clients never supply an `id` and never derive one from a
        serial number, a policy number, or an email address."
        "Most resources additionally carry `updated_at`, in the same format, and
        `version`, an integer that starts at 1 when the resource is created and
        increases by exactly 1 on every accepted mutation of that row."

        Design: Corner/entities/create_homeowner_returns_active_account_with_system_fields
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        created = get_success_data(api.create_homeowner(homeowner_payload(), ADMIN), 201)
        assert_homeowner(created)

        assert is_valid_uuid(created["id"])
        assert created["full_name"] == TEST_DEFAULTS["HOMEOWNER_NAME"]
        assert created["email"] == TEST_DEFAULTS["HOMEOWNER_EMAIL"]
        assert created["phone_e164"] == TEST_DEFAULTS["HOMEOWNER_PHONE"]

        assert created["account_state"] == "ACTIVE"
        assert created["deactivated_at"] is None
        assert created["owned_property_count"] == 0
        assert created["version"] == 1

        # Both stamps come from the logical clock, never from wall time.
        assert created["created_at"].startswith("2026-08-01T06:05:00")
        assert created["updated_at"].startswith("2026-08-01T06:05:00")

    def test_the_notification_channel_default_is_applied_not_hard_coded(
        self, api: ApiClient
    ):
        """Omitting the channel yields SMS; supplying EMAIL yields EMAIL.

        "and optionally a `notification_channel`, which selects how those first-stage
        alerts reach the homeowner and takes one of `SMS`, `EMAIL`, or `PUSH`,
        defaulting to `SMS` when omitted."

        Design: Corner/entities/create_homeowner_omitting_notification_channel_applies_sms_default
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        defaulted = create_homeowner(api)
        supplied = get_success_data(
            api.create_homeowner(
                homeowner_payload(
                    full_name=TEST_DEFAULTS["BUYER_NAME"],
                    email=TEST_DEFAULTS["BUYER_EMAIL"],
                    phone_e164=TEST_DEFAULTS["BUYER_PHONE"],
                    notification_channel="EMAIL",
                ),
                ADMIN,
            ),
            201,
        )

        assert defaulted["notification_channel"] == "SMS"
        assert supplied["notification_channel"] == "EMAIL"

        # The stored rows agree with the creation responses.
        assert read_homeowner(api, defaulted["id"])["notification_channel"] == "SMS"
        assert read_homeowner(api, supplied["id"])["notification_channel"] == "EMAIL"


class TestPropertyCreation:
    def test_omitting_irrigation_present_defaults_it_to_false(self, api: ApiClient):
        """The flag that gates window declarations is off unless asked for.

        "One further flag matters far more than it looks: `irrigation_present`
        declares whether the property has a sprinkler system, defaults to false, and
        gates whether irrigation exclusion windows may be declared at all."
        "A new property begins with `property_state` equal to `ACTIVE` and
        `archived_at` null."

        Design: Corner/entities/create_property_omitting_irrigation_present_defaults_false
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        owner = create_homeowner(api)
        body = property_payload(owner["id"])
        del body["irrigation_present"]

        created = get_success_data(
            api.create_property(body, make_homeowner_headers(owner["id"])), 201
        )
        assert_property(created)
        assert created["irrigation_present"] is False
        assert created["property_state"] == "ACTIVE"
        assert created["archived_at"] is None
        assert created["version"] == 1

        # The owner's count is derived on read, so it moves immediately.
        assert read_homeowner(api, owner["id"])["owned_property_count"] == 1

    def test_a_property_missing_state_code_is_refused_and_persists_nothing(
        self, api: ApiClient
    ):
        """A required field has no default, and the rejection leaves no row.

        "The payload names the owning `homeowner_id` and describes the building:
        `address_line1` (1 to 160 characters), `city`, a two-uppercase-letter
        `state_code`, a five-digit `postal_code`, and `year_built`, which must fall
        between 1850 and 2026 and which the carrier's underwriting notes read."
        "**Request shape** — every required body field present, every enum value
        inside its declared set, every numeric field non-negative and inside its
        declared bound, every timestamp parseable as ISO 8601 UTC, and every interval
        body satisfying a start strictly before its end (equal bounds and inverted
        bounds are both refused): `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_property_missing_state_code_returns_invalid_request
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        owner = create_homeowner(api)
        body = property_payload(owner["id"])
        del body["state_code"]

        response = api.create_property(body, make_homeowner_headers(owner["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        assert read_homeowner(api, owner["id"])["owned_property_count"] == 0
        rows, meta = validate_paginated(
            api.list_homeowner_properties(owner["id"], make_homeowner_headers(owner["id"]))
        )
        assert rows == []
        assert meta["total_count"] == 0


def _two_devices_on_one_property(api: ApiClient) -> dict:
    """One install-verified device and one still awaiting its hold test."""
    state = setup_registered_device(api)
    verify_install(api, state["device_id"])
    second = create_device(
        api,
        state["property_id"],
        serial_number=TEST_DEFAULTS["SECOND_SERIAL_NUMBER"],
        model_code=TEST_DEFAULTS["SECOND_MODEL_CODE"],
    )
    state["second_device_id"] = second["id"]
    return state


class TestDeviceRetrieval:
    def test_reading_a_device_back_echoes_the_stored_row_and_its_defaults(
        self, api: ApiClient
    ):
        """Registration lands in three postures at once, with counters at zero.

        "Registration names the `property_id` whose main line the shutoff valve sits
        on, a `serial_number` between 6 and 32 characters that must be unique across
        every device the platform has ever seen — a collision is refused with
        `ERR_DEVICE_SERIAL_TAKEN` — a `model_code` of either `FLO_SMART_3_4` or
        `FLO_SMART_1_0`, and optionally `firmware_version` as a semantic-version
        string, which defaults to `1.0.0`."
        "Because a device carries three independent posture dimensions rather than one
        status, a newly registered row lands in `lifecycle_state` `REGISTERED`,
        `valve_state` `OPEN`, and `monitor_mode` `NORMAL` simultaneously, with
        `close_count` and `reopen_count` both at 0 and `monitor_mode_updated_at` equal
        to `created_at`."

        Design: Corner/entities/get_device_returns_stored_entity_with_defaults
        """
        state = setup_registered_device(api)

        device = get_success_data(api.get_device(state["device_id"], TECH))
        assert_device(device)
        assert device["id"] == state["device_id"]
        assert device["property_id"] == state["property_id"]
        assert device["serial_number"] == TEST_DEFAULTS["SERIAL_NUMBER"]
        assert device["model_code"] == TEST_DEFAULTS["MODEL_CODE"]

        assert device["firmware_version"] == "1.0.0"
        assert device["lifecycle_state"] == "REGISTERED"
        assert device["valve_state"] == "OPEN"
        assert device["monitor_mode"] == "NORMAL"

        assert device["close_count"] == 0
        assert device["reopen_count"] == 0
        assert device["install_verified_at"] is None
        assert device["installed_static_pressure_psi"] is None
        assert device["baseline_ready"] is False
        assert device["version"] == 1

    def test_the_device_list_reports_the_page_it_actually_returned(
        self, api: ApiClient
    ):
        """A limit of 1 over two rows leaves more behind; an offset of 1 does not.

        "List responses populate `limit`, `offset`, `total_count`, and `has_more`
        inside `meta`. `total_count` is the number of rows matching the filter before
        pagination is applied, and `has_more` is true exactly when rows remain beyond
        the returned page."

        Design: Corner/entities/list_property_devices_returns_paginated_envelope
        """
        state = _two_devices_on_one_property(api)
        owner_headers = state["homeowner_headers"]

        first_page, first_meta = validate_paginated(
            api.list_property_devices(
                state["property_id"], owner_headers, {"limit": 1, "offset": 0}
            )
        )
        assert len(first_page) == 1
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_property_devices(
                state["property_id"], owner_headers, {"limit": 1, "offset": 1}
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False
        assert second_page[0]["id"] != first_page[0]["id"]

    def test_the_lifecycle_filter_narrows_before_the_default_page_is_cut(
        self, api: ApiClient
    ):
        """Filtering to REGISTERED leaves only the device that skipped its hold test.

        "Filters on list endpoints narrow the result set before pagination. The roster
        of emergency contacts and the irrigation-window and attestation lists accept
        `status`; the property list accepts `property_state`; the device list accepts
        `lifecycle_state`; the policy list accepts `credit_state`; the baseline-profile
        list accepts `learning_state`; the telemetry list accepts
        `classification_at_ingest` and `baseline_eligible`; the anomaly-event list
        accepts `device_id`, `telemetry_reading_id`, `classification`, and
        `event_state`; the escalation-ticket list accepts `anomaly_event_id`,
        `notified_contact_id`, and `stage`; the claim list accepts `policy_id`,
        `device_id`, `anomaly_event_id`, and `status`; the transfer list accepts
        `device_id`, `from_homeowner_id`, `to_homeowner_id`, and `status`."
        "`limit` defaults to 10 when omitted, may be no smaller than 1, and may be no
        larger than 100. `offset` defaults to 0 and is a zero-based row skip."

        Design: Corner/entities/list_property_devices_returns_paginated_envelope
        """
        state = _two_devices_on_one_property(api)
        owner_headers = state["homeowner_headers"]

        filtered, filtered_meta = validate_paginated(
            api.list_property_devices(
                state["property_id"], owner_headers, {"lifecycle_state": "REGISTERED"}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["id"] == state["second_device_id"]

        everything, default_meta = validate_paginated(
            api.list_property_devices(state["property_id"], owner_headers)
        )
        assert default_meta["total_count"] == 2
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0
        assert default_meta["has_more"] is False
        assert len(everything) == 2

    def test_an_unknown_device_id_answers_with_the_devices_not_found_code(
        self, api: ApiClient
    ):
        """A well-formed identifier that resolves to nothing is a 404, not a 400.

        "The equivalent codes for the remaining single-resource paths are
        `ERR_ANOMALY_EVENT_NOT_FOUND`, `ERR_ESCALATION_TICKET_NOT_FOUND`,
        `ERR_ATTESTATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and
        `ERR_TRANSFER_NOT_FOUND`."
        "a request against a device's baseline profiles, telemetry, or health summary
        resolves the device first and answers `ERR_DEVICE_NOT_FOUND`"

        Design: Corner/entities/get_device_unknown_id_returns_device_not_found
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        owner = create_homeowner(api)
        create_property(api, owner["id"])

        error = validate_error(
            api.get_device(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_DEVICE_NOT_FOUND, 404
        )
        assert error["message"].strip() != ""
        assert "id" not in error

    def test_a_device_naming_an_unknown_property_is_refused_before_any_write(
        self, api: ApiClient
    ):
        """A body foreign key resolves at priority 5 and stores nothing.

        "Identifiers carried in a request *body* rather than the path resolve the same
        way and reuse the same codes: an unresolvable `homeowner_id` or
        `to_homeowner_id` yields `ERR_HOMEOWNER_NOT_FOUND`, an unresolvable
        `property_id` yields `ERR_PROPERTY_NOT_FOUND`, an unresolvable `device_id`
        yields `ERR_DEVICE_NOT_FOUND`, an unresolvable `anomaly_event_id` yields
        `ERR_ANOMALY_EVENT_NOT_FOUND`, and an unresolvable `policy_id` yields
        `ERR_POLICY_NOT_FOUND`."
        "a `serial_number` between 6 and 32 characters that must be unique across every
        device the platform has ever seen — a collision is refused with
        `ERR_DEVICE_SERIAL_TAKEN`"

        Design: Corner/entities/create_device_with_unknown_property_id_returns_property_not_found
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        owner = create_homeowner(api)

        response = api.create_device(
            device_payload(UNKNOWN_UUID_ALT, serial_number="FLO-000009"), TECH
        )
        validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)

        # Nothing was reserved: the same serial is still free.
        home = create_property(api, owner["id"])
        accepted = create_device(api, home["id"], serial_number="FLO-000009")
        assert accepted["serial_number"] == "FLO-000009"
        assert read_device(api, accepted["id"])["lifecycle_state"] == "REGISTERED"


class TestIrrigationWindowBounds:
    def test_equal_and_inverted_bounds_are_both_refused_before_the_overlap_check(
        self, api: ApiClient
    ):
        """A zero-length span and a reversed span are shape errors, not conflicts.

        "**Request shape** — every required body field present, every enum value inside
        its declared set, every numeric field non-negative and inside its declared
        bound, every timestamp parseable as ISO 8601 UTC, and every interval body
        satisfying a start strictly before its end (equal bounds and inverted bounds
        are both refused): `ERR_INVALID_REQUEST` (400)."
        "an `end_at` instant strictly after it"

        Design: Corner/entities/create_irrigation_window_with_inverted_bounds_returns_invalid_request
        """
        state = setup_armed_device(api)
        owner_headers = state["homeowner_headers"]

        equal_bounds = api.create_irrigation_window(
            state["property_id"],
            irrigation_window_payload(
                "2026-08-05T09:00:00Z",
                "2026-08-05T09:00:00Z",
                expected_max_flow_gpm=9.0,
                label="Zero-length zone",
            ),
            owner_headers,
        )
        validate_error(equal_bounds, ApiErrorId.ERR_INVALID_REQUEST, 400)

        inverted = api.create_irrigation_window(
            state["property_id"],
            irrigation_window_payload(
                "2026-08-05T11:00:00Z",
                "2026-08-05T09:00:00Z",
                expected_max_flow_gpm=9.0,
                label="Inverted zone",
            ),
            owner_headers,
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST, 400)

        assert read_irrigation_windows(api, state["property_id"], owner_headers) == []


class TestEmergencyContactSystemFields:
    def test_verification_state_is_system_assigned_from_the_verify_flag(
        self, api: ApiClient
    ):
        """VERIFIED only on request; PENDING by default; ACTIVE either way.

        "Contact creation also accepts the optional flag `verify_immediately`: when it
        is true the contact is created with `verification_state` equal to `VERIFIED`,
        standing in for a confirmed SMS opt-in; when it is false or omitted the contact
        is created `PENDING`."
        "Every new contact starts `ACTIVE` with `last_notified_at` null; the field is
        stamped only when an escalation sweep actually dials that contact."

        Design: Corner/entities/create_emergency_contact_verification_state_is_system_assigned
        """
        set_clock(api, FIXTURE_CLOCK_UTC)
        owner = create_homeowner(api)
        owner_headers = make_homeowner_headers(owner["id"])

        verified = get_success_data(
            api.create_emergency_contact(
                owner["id"],
                emergency_contact_payload(1, verify_immediately=True),
                owner_headers,
            ),
            201,
        )
        pending = get_success_data(
            api.create_emergency_contact(
                owner["id"],
                emergency_contact_payload(
                    2, full_name="Dee Nunez", phone_e164="+14155550404"
                ),
                owner_headers,
            ),
            201,
        )

        assert_emergency_contact(verified)
        assert verified["verification_state"] == "VERIFIED"
        assert verified["status"] == "ACTIVE"
        assert verified["last_notified_at"] is None
        assert verified["priority_rank"] == 1

        assert_emergency_contact(pending)
        assert pending["verification_state"] == "PENDING"
        assert pending["status"] == "ACTIVE"
        assert pending["last_notified_at"] is None

        roster, meta = validate_paginated(
            api.list_emergency_contacts(owner["id"], owner_headers, {"status": "ACTIVE"})
        )
        assert meta["total_count"] == 2
        assert [row["priority_rank"] for row in roster] == [1, 2]


class TestTelemetryImmutability:
    def test_a_stored_reading_carries_no_version_and_no_updated_at(
        self, api: ApiClient
    ):
        """The one entity excluded from the audit pair, and never rewritten.

        "One entity is deliberately excluded from both: a telemetry reading is
        immutable once accepted, so a `TelemetryReading` row carries only `id` and
        `created_at` — it has no `updated_at` and no `version` field at all, and nothing
        in the system ever rewrites a stored reading."
        "a device's telemetry is ordered by `reading_at` ascending"

        Design: Corner/entities/telemetry_reading_is_immutable_with_no_version_field
        """
        state = setup_armed_device(api)

        rows, meta = validate_paginated(
            api.list_telemetry_readings(
                state["device_id"], make_gateway_headers(), {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

        for row in rows:
            assert_telemetry_reading(row)
            assert row["device_id"] == state["device_id"]
            assert "reading_at" in row
            assert "classification_at_ingest" in row
            assert "baseline_eligible" in row
            assert "coverage_minutes" in row
            assert "created_at" in row
            assert "version" not in row
            assert "updated_at" not in row

        assert rows[0]["coverage_minutes"] == COVERAGE_MINUTES_PER_READING
        assert rows[0]["baseline_eligible"] is True
        assert rows[0]["classification_at_ingest"] == "NONE"

    def test_a_later_ingest_never_rewrites_an_earlier_rows_verdict(
        self, api: ApiClient
    ):
        """The frozen classification of the learning samples survives a burst.

        "One entity is deliberately excluded from both: a telemetry reading is
        immutable once accepted, so a `TelemetryReading` row carries only `id` and
        `created_at` — it has no `updated_at` and no `version` field at all, and nothing
        in the system ever rewrites a stored reading."
        "Those three conditions together define eligibility: a reading is
        baseline-eligible exactly when its frozen classification is `NONE`, its
        `reading_source` is `DEVICE`, and its `suppressed_by_irrigation` flag is false."

        Design: Corner/entities/telemetry_reading_is_immutable_with_no_version_field
        """
        state = setup_armed_device(api)
        before = read_telemetry(api, state["device_id"])

        set_clock(api, "2026-08-01T07:00:00Z")
        ingest_burst_reading(api, state["device_id"], "2026-08-01T07:00:00Z")

        after = read_telemetry(api, state["device_id"])
        assert len(after) == 4
        for earlier, later in zip(before, after):
            assert earlier["id"] == later["id"]
            assert earlier["classification_at_ingest"] == later["classification_at_ingest"]
            assert earlier["baseline_eligible"] == later["baseline_eligible"]
            assert earlier["created_at"] == later["created_at"]
        assert after[3]["classification_at_ingest"] == "CATASTROPHIC_BURST"


POLICY_YEAR_START = "2026-08-01T00:00:00Z"
OTHER_LEARNING_READINGS = [
    {
        "reading_at": "2026-08-01T01:00:00Z",
        "static_pressure_psi": 60.0,
        "flow_gpm": 0.0,
        "duration_minutes": 0,
        "total_gallons": 0.0,
    },
    {
        "reading_at": "2026-08-01T01:20:00Z",
        "static_pressure_psi": 62.0,
        "flow_gpm": 6.0,
        "duration_minutes": 4,
        "total_gallons": 24.0,
    },
    {
        "reading_at": "2026-08-01T01:40:00Z",
        "static_pressure_psi": 58.0,
        "flow_gpm": 0.0,
        "duration_minutes": 0,
        "total_gallons": 0.0,
    },
]
BURST_AT = "2026-08-01T07:00:00Z"


def _a_policy_on_one_property_and_a_burst_on_another(api: ApiClient) -> dict:
    """Two insured households; the qualifying event belongs to the wrong one."""
    state = setup_armed_device(api)
    policy = create_policy(api, state["property_id"], POLICY_YEAR_START)
    state["policy_id"] = policy["id"]

    other_owner = create_buyer(api)
    other_property = create_second_property(api, other_owner["id"])
    other_device = create_device(
        api,
        other_property["id"],
        serial_number=TEST_DEFAULTS["SECOND_SERIAL_NUMBER"],
    )
    # The hold test pins the profile's `learning_started_at`, and `sample_count`
    # only counts readings stamped at or after it, so the sign-off has to precede
    # the 01:00 samples that are meant to close the second household's cycle.
    set_clock(api, DEFAULT_CLOCK_UTC)
    verify_install(
        api,
        other_device["id"],
        installed_static_pressure_psi=61.0,
        pressure_drop_psi=0.5,
    )
    set_clock(api, OTHER_LEARNING_READINGS[-1]["reading_at"])
    ingest_learning_samples(api, other_device["id"], OTHER_LEARNING_READINGS)

    set_clock(api, BURST_AT)
    ingest_burst_reading(api, other_device["id"], BURST_AT)
    foreign_events = read_events(api, other_device["id"], event_state="ALERTED")
    assert len(foreign_events) == 1
    state["foreign_device_id"] = other_device["id"]
    state["foreign_event_id"] = foreign_events[0]["id"]
    return state


class TestCrossAggregateClaimCoherence:
    def test_an_event_from_another_property_cannot_support_a_water_damage_claim(
        self, api: ApiClient
    ):
        """Every row referenced exists; only their coherence is wrong.

        "A `WATER_DAMAGE` claim **must** carry `anomaly_event_id`, and the referenced
        event must belong to the referenced device, which must in turn belong to the
        policy's property; any of those three failures is refused with
        `ERR_NO_QUALIFYING_EVENT`."
        "The submission names the `policy_id` the claim is filed against, the
        `device_id` whose warranty or mitigation performance is at issue, a `claim_type`
        of either `WARRANTY_DEVICE` for a hardware failure or `WATER_DAMAGE` for loss
        reimbursement, a `documented_loss_cents` figure of at least 1 cent representing
        the documented loss or repair cost, and optionally an `anomaly_event_id` naming
        the qualifying event."

        Design: Corner/entities/claim_referencing_event_from_another_property_returns_no_qualifying_event
        """
        state = _a_policy_on_one_property_and_a_burst_on_another(api)

        # Filed by the administrator, so the ownership gate cannot mask the
        # coherence check that this case is about.
        mismatched = api.create_claim(
            claim_payload(
                state["policy_id"],
                state["device_id"],
                "WATER_DAMAGE",
                400_000,
                anomaly_event_id=state["foreign_event_id"],
            ),
            ADMIN,
        )
        validate_error(mismatched, ApiErrorId.ERR_NO_QUALIFYING_EVENT, 409)

        rows, meta = validate_paginated(
            api.list_claims(ADMIN, {"policy_id": state["policy_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        # Dropping the reference entirely is the same refusal: the field is
        # mandatory for this claim type.
        omitted = api.create_claim(
            claim_payload(state["policy_id"], state["device_id"], "WATER_DAMAGE", 400_000),
            ADMIN,
        )
        validate_error(omitted, ApiErrorId.ERR_NO_QUALIFYING_EVENT, 409)
