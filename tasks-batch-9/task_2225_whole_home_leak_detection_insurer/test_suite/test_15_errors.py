"""Catalog errors reached deliberately, each from the fixture that isolates it.

Every refusal here is a distinct identifier rather than a generic failure: three
uniqueness scopes, three attestation lifecycle guards, two transfer initiation
gates, two post-accept transfer refusals, seven path-scoped 404s, and the written
acknowledgement that turns a refused reopen into an accepted one.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    ApiClient,
    ApiErrorId,
    assert_device_transfer,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    attestation_payload,
    claim_payload,
    device_payload,
    device_transfer_payload,
    emergency_contact_payload,
    monitor_mode_payload,
    policy_payload,
    valve_command_payload,
)
from test_helpers.fixtures import (
    accept_transfer,
    acknowledge_ticket,
    create_buyer,
    create_emergency_contact,
    create_policy,
    file_claim,
    finalize_attestation,
    ingest_burst_reading,
    ingest_quiet_reading,
    initiate_transfer,
    open_attestation,
    read_attestation_list,
    read_device,
    read_device_version,
    read_events,
    read_live_baseline,
    read_policy,
    read_property,
    read_property_version,
    read_tickets,
    read_transfer,
    run_ops_sweep,
    set_clock,
    setup_armed_device_with_buyer,
    setup_armed_device_with_contact,
    setup_armed_device_with_policy,
    setup_burst_event,
    setup_burst_event_with_policy,
    setup_learning_device,
    setup_pending_transfer,
    setup_second_registered_device,
)
from test_helpers.test_users import (
    ADJUSTER_USER_ID,
    INSTALLER_TECH_USER_ID,
    INSURER_ANALYST_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    make_claims_adjuster_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_insurer_analyst_headers,
    make_program_admin_headers,
)

POLICY_YEAR_START = "2026-08-01T00:00:00Z"
ANALYST = make_insurer_analyst_headers(INSURER_ANALYST_USER_ID)
ADMIN = make_program_admin_headers(PROGRAM_ADMIN_USER_ID)
INSTALLER = make_installer_tech_headers(INSTALLER_TECH_USER_ID)
ANONYMOUS: dict = {}


def _one_device_one_policy_and_one_rank_one_contact(api: ApiClient) -> dict:
    """Three rows, each owning a different uniqueness scope."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    state["contact"] = create_emergency_contact(
        api, state["homeowner_id"], 1, verify_immediately=True
    )
    return state


class TestEachUniquenessScopeRaisesItsOwnConflict:
    def test_a_taken_serial_and_a_taken_policy_number_are_distinct_conflicts(
        self, api: ApiClient
    ):
        """Both scopes are global, and both refusals leave the original row alone.

        "Registration names the `property_id` whose main line the shutoff valve sits on, a
        `serial_number` between 6 and 32 characters that must be unique across every device
        the platform has ever seen — a collision is refused with `ERR_DEVICE_SERIAL_TAKEN` —
        a `model_code` of either `FLO_SMART_3_4` or `FLO_SMART_1_0`, and optionally
        `firmware_version` as a semantic-version string, which defaults to `1.0.0`."
        "The submission names the insured `property_id`, an `insurer_code` of 2 to 12
        uppercase characters identifying the carrier, a `policy_number` of 4 to 32 characters
        that must be unique across every policy the platform holds — a collision is refused
        with `ERR_POLICY_NUMBER_TAKEN` — an `annual_premium_cents` figure of at least 10000
        cents which is the base the IoT credit is computed from, a `policy_year_start_at`
        instant which the very first attestation period must begin at exactly, the mandatory
        `expected_property_version` described in §2.6, and optionally `deductible_cents`, the
        water-damage deductible, which must not be negative and defaults to 100000 cents when
        omitted."

        Design: Corner/errors/uniqueness_violations_return_serial_policy_and_rank_taken
        """
        state = _one_device_one_policy_and_one_rank_one_contact(api)

        # A different model on an already-registered serial is still the same serial.
        validate_error(
            api.create_device(
                device_payload(
                    state["property_id"],
                    serial_number=TEST_DEFAULTS["SERIAL_NUMBER"],
                    model_code=TEST_DEFAULTS["SECOND_MODEL_CODE"],
                ),
                INSTALLER,
            ),
            ApiErrorId.ERR_DEVICE_SERIAL_TAKEN,
            409,
        )
        devices, device_meta = validate_paginated(
            api.list_property_devices(state["property_id"], ADMIN)
        )
        assert device_meta["total_count"] == 1
        assert devices[0]["id"] == state["device_id"]

        # The version is re-read so the staleness check cannot mask the conflict.
        fresh_version = read_property_version(api, state["property_id"], ANALYST)
        validate_error(
            api.create_policy(
                policy_payload(
                    state["property_id"],
                    fresh_version,
                    POLICY_YEAR_START,
                    annual_premium_cents=200000,
                    deductible_cents=50000,
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_POLICY_NUMBER_TAKEN,
            409,
        )
        policies, policy_meta = validate_paginated(
            api.list_property_policies(state["property_id"], ANALYST)
        )
        assert policy_meta["total_count"] == 1
        assert policies[0]["id"] == state["policy_id"]
        assert policies[0]["annual_premium_cents"] == 149900

    def test_the_rank_conflict_is_scoped_to_the_household_not_the_platform(
        self, api: ApiClient
    ):
        """Rank 1 is taken, so rank 2 on the same account is accepted at once.

        "Ranks must be unique among the homeowner's contacts whose `status` is `ACTIVE`; a
        second `ACTIVE` contact at an already-taken rank is refused with
        `ERR_CONTACT_RANK_TAKEN`."
        "Each emergency contact is created against a homeowner with a `full_name` between 1
        and 120 characters, a `phone_e164` number that will be dialled at escalation stage 2,
        and a `priority_rank` between 1 and 5 where rank 1 is called first."
        "Every new contact starts `ACTIVE` with `last_notified_at` null; the field is stamped
        only when an escalation sweep actually dials that contact."

        Design: Corner/errors/uniqueness_violations_return_serial_policy_and_rank_taken
        """
        state = _one_device_one_policy_and_one_rank_one_contact(api)
        homeowner_headers = make_homeowner_headers(state["homeowner_id"])

        validate_error(
            api.create_emergency_contact(
                state["homeowner_id"],
                emergency_contact_payload(
                    1, full_name="Dee Nunez", phone_e164="+14155550404"
                ),
                homeowner_headers,
            ),
            ApiErrorId.ERR_CONTACT_RANK_TAKEN,
            409,
        )
        contacts, meta = validate_paginated(
            api.list_emergency_contacts(state["homeowner_id"], homeowner_headers)
        )
        assert meta["total_count"] == 1
        assert contacts[0]["priority_rank"] == 1

        # The same account accepts the same person at a free rank.
        second = create_emergency_contact(
            api,
            state["homeowner_id"],
            2,
            full_name="Dee Nunez",
            phone_e164="+14155550404",
        )
        assert second["priority_rank"] == 2
        assert second["status"] == "ACTIVE"
        _, after = validate_paginated(
            api.list_emergency_contacts(state["homeowner_id"], homeowner_headers)
        )
        assert after["total_count"] == 2


LAST_ACCEPTED_INSTANT = "2026-08-31T07:00:00Z"
ONE_MINUTE_LATER = "2026-08-31T07:01:00Z"


def _a_burst_thirty_days_old(api: ApiClient) -> dict:
    """The clock sits on the last instant the filing window admits."""
    state = setup_burst_event_with_policy(api)
    assert state["event"]["detected_at"].startswith("2026-08-01T07:00:00")
    set_clock(api, LAST_ACCEPTED_INSTANT)
    return state


class TestClaimWindowIncludesItsLastInstant:
    def test_a_filing_at_exactly_thirty_days_is_still_accepted(self, api: ApiClient):
        """detected_at plus 30 days is inside the window, not outside it.

        "Filing is also time-boxed: the clock must be no later than 30 days after the
        referenced event's `detected_at`, with the last instant of the window still accepted,
        or the claim is refused with `ERR_CLAIM_WINDOW_EXPIRED`."
        "A new claim is created in `status` `SUBMITTED` with `approved_payout_cents` and
        `deductible_applied_cents` at 0, `info_request_count` at 0, `payout_variant`,
        `decided_by_user_id`, `decided_at`, `denial_reason`, and `paid_at` all null,
        `submitted_by_user_id` set to the resolved homeowner's identifier, and `version` at 1."

        Design: Corner/errors/claim_one_minute_past_submission_window_returns_window_expired
        """
        state = _a_burst_thirty_days_old(api)

        claim = file_claim(
            api,
            state["policy_id"],
            state["device_id"],
            "WARRANTY_DEVICE",
            90000,
            state["homeowner_id"],
            anomaly_event_id=state["event_id"],
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["created_at"].startswith("2026-08-31T07:00:00")
        assert claim["submitted_by_user_id"] == state["homeowner_id"]
        assert claim["version"] == 1

    def test_one_minute_past_the_window_the_same_event_is_refused(
        self, api: ApiClient
    ):
        """The window closes strictly after detected_at plus 30 days.

        "Filing is also time-boxed: the clock must be no later than 30 days after the
        referenced event's `detected_at`, with the last instant of the window still accepted,
        or the claim is refused with `ERR_CLAIM_WINDOW_EXPIRED`."
        "That optionality is load-bearing."

        Design: Corner/errors/claim_one_minute_past_submission_window_returns_window_expired
        """
        state = _a_burst_thirty_days_old(api)
        accepted = file_claim(
            api,
            state["policy_id"],
            state["device_id"],
            "WARRANTY_DEVICE",
            90000,
            state["homeowner_id"],
            anomaly_event_id=state["event_id"],
        )

        set_clock(api, ONE_MINUTE_LATER)
        validate_error(
            api.create_claim(
                claim_payload(
                    state["policy_id"],
                    state["device_id"],
                    "WATER_DAMAGE",
                    300000,
                    anomaly_event_id=state["event_id"],
                ),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED,
            409,
        )

        claims, meta = validate_paginated(
            api.list_claims(ADMIN, {"anomaly_event_id": state["event_id"]})
        )
        assert meta["total_count"] == 1
        assert claims[0]["id"] == accepted["id"]


def _an_armed_device_a_buyer_and_a_never_installed_device(api: ApiClient) -> dict:
    """One transferable device, one that was never install-verified."""
    state = setup_armed_device_with_buyer(api)
    state["second_device"] = setup_second_registered_device(api, state)
    state["second_device_id"] = state["second_device"]["id"]
    return state


class TestTransferInitiationHasTwoIndependentGates:
    def test_selling_to_yourself_and_selling_a_never_installed_device_differ(
        self, api: ApiClient
    ):
        """Two gates, two identifiers, and neither attempt writes a row.

        "The buyer must be somebody else — a `to_homeowner_id` equal to the property's current
        `homeowner_id` is refused with `ERR_TRANSFER_TARGET_INVALID`."
        "The device must be transferable, meaning its `lifecycle_state` is `ARMED` or
        `LEARNING`; a device that was never installed (`REGISTERED` or `INSTALL_VERIFIED`) or
        that has been `DECOMMISSIONED` is refused with `ERR_DEVICE_NOT_TRANSFERABLE`."

        Design: Corner/errors/transfer_to_current_owner_and_of_unverified_device_are_refused
        """
        state = _an_armed_device_a_buyer_and_a_never_installed_device(api)
        seller = make_homeowner_headers(state["homeowner_id"])
        armed_version = read_device_version(api, state["device_id"], seller)
        registered_version = read_device_version(api, state["second_device_id"], seller)

        validate_error(
            api.create_device_transfer(
                device_transfer_payload(
                    state["device_id"], state["homeowner_id"], armed_version
                ),
                seller,
            ),
            ApiErrorId.ERR_TRANSFER_TARGET_INVALID,
            409,
        )
        # A legitimate buyer cannot rescue a device that never had its hold test.
        validate_error(
            api.create_device_transfer(
                device_transfer_payload(
                    state["second_device_id"], state["buyer_id"], registered_version
                ),
                seller,
            ),
            ApiErrorId.ERR_DEVICE_NOT_TRANSFERABLE,
            409,
        )

        _, meta = validate_paginated(
            api.list_device_transfers(ADMIN, {"device_id": state["device_id"]})
        )
        assert meta["total_count"] == 0

        assert read_device(api, state["device_id"])["lifecycle_state"] == "ARMED"
        assert (
            read_device(api, state["second_device_id"])["lifecycle_state"]
            == "REGISTERED"
        )
        assert read_property(api, state["property_id"])["property_state"] == "ACTIVE"
        assert read_device_version(api, state["device_id"], seller) == armed_version
        assert (
            read_device_version(api, state["second_device_id"], seller)
            == registered_version
        )


FIRST_PERIOD = ("2026-08-01T00:00:00Z", "2026-08-01T04:00:00Z")
ONE_MINUTE_BEFORE_END = "2026-08-01T03:59:00Z"
PERIOD_END = "2026-08-01T04:00:00Z"
OVERLAPPING_PERIOD = ("2026-08-01T03:00:00Z", "2026-08-01T08:00:00Z")
ABUTTING_PERIOD = ("2026-08-01T04:00:00Z", "2026-08-01T08:00:00Z")


def _an_open_period_one_minute_from_its_end(api: ApiClient) -> dict:
    """The only attestation on the policy, still OPEN, still unfinalizable."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    state["attestation"] = open_attestation(api, state["policy_id"], *FIRST_PERIOD)
    state["attestation_id"] = state["attestation"]["id"]
    set_clock(api, ONE_MINUTE_BEFORE_END)
    return state


def _only_attestation(api: ApiClient, state: dict, attestation_id: str) -> dict:
    rows = read_attestation_list(api, state["policy_id"])
    matching = [row for row in rows if row["id"] == attestation_id]
    assert len(matching) == 1
    return matching[0]


class TestAttestationLifecycleGuardsAreThreeSeparateRefusals:
    def test_the_period_end_instant_is_itself_a_legal_finalize_instant(
        self, api: ApiClient
    ):
        """One minute early is refused; the boundary instant scores the period.

        "It requires the attestation to still be `OPEN` — a second finalize is refused with
        `ERR_ATTESTATION_NOT_OPEN` — and requires the clock to have reached `period_end_at`,
        inclusively, so the boundary instant itself is finalizable while anything earlier is
        refused with `ERR_ATTESTATION_PERIOD_NOT_ENDED`."
        "Every accepted telemetry reading for the resolved device whose `reading_at` falls at
        or after `period_start_at` and strictly before `period_end_at` vouches for the two
        hours of monitoring that follow it: each contributes a coverage interval beginning at
        its `reading_at` and ending at the earlier of two hours later or `period_end_at`, so
        the tail of the last reading is clamped at the period boundary."

        Design: Corner/errors/attestation_lifecycle_errors_not_ended_not_open_and_overlap
        """
        state = _an_open_period_one_minute_from_its_end(api)

        validate_error(
            api.finalize_credit_attestation(state["attestation_id"], {}, ANALYST),
            ApiErrorId.ERR_ATTESTATION_PERIOD_NOT_ENDED,
            409,
        )
        still_open = _only_attestation(api, state, state["attestation_id"])
        assert still_open["status"] == "OPEN"
        assert still_open["finalized_at"] is None

        set_clock(api, PERIOD_END)
        scored = finalize_attestation(api, state["attestation_id"])
        assert scored["id"] == state["attestation_id"]
        assert scored["finalized_at"].startswith("2026-08-01T04:00:00")
        assert scored["period_minutes"] == 240
        # The three learning samples cover 00:00 to 02:40 once merged.
        assert scored["covered_minutes"] == 160
        assert scored["uptime_pct"] == 66.67

    def test_the_denial_that_lands_at_the_boundary_still_advances_the_chain(
        self, api: ApiClient
    ):
        """Below the floor the period awards nothing, yet the chain moves on.

        "A denial moves the attestation `OPEN → FINALIZED_DENIED` and writes
        `covered_minutes`, `uptime_pct`, `offline_gap_count`, `denial_reason`, and
        `finalized_at`, leaving `credit_cents_awarded` at 0 and `tier_pct` at 0."
        "A denial still advances the chain, setting the policy's `last_attestation_end_at` to
        the period end, and when the policy was `CREDIT_ACTIVE` and the reason was
        `UPTIME_BELOW_FLOOR` it drives the policy `CREDIT_ACTIVE → CREDIT_SUSPENDED` with
        `suspended_reason` `UPTIME_BELOW_FLOOR` and `current_credit_tier_pct` reset to 0."

        Design: Corner/errors/attestation_lifecycle_errors_not_ended_not_open_and_overlap
        """
        state = _an_open_period_one_minute_from_its_end(api)
        set_clock(api, PERIOD_END)
        scored = finalize_attestation(api, state["attestation_id"])

        assert scored["status"] == "FINALIZED_DENIED"
        assert scored["denial_reason"] == "UPTIME_BELOW_FLOOR"
        assert scored["credit_cents_awarded"] == 0
        assert scored["tier_pct"] == 0
        assert scored["offline_gap_count"] == 1

        policy = read_policy(api, state["policy_id"])
        assert policy["last_attestation_end_at"].startswith("2026-08-01T04:00:00")
        assert policy["credited_cents_total"] == 0
        assert policy["clawback_cents_total"] == 0
        assert policy["finalized_period_count"] == 1

    def test_a_second_finalize_is_refused_and_an_overlapping_period_cannot_open(
        self, api: ApiClient
    ):
        """Not-open and overlap are different guards on different verbs.

        "It requires the attestation to still be `OPEN` — a second finalize is refused with
        `ERR_ATTESTATION_NOT_OPEN` — and requires the clock to have reached `period_end_at`,
        inclusively, so the boundary instant itself is finalizable while anything earlier is
        refused with `ERR_ATTESTATION_PERIOD_NOT_ENDED`."
        "The period must not overlap any existing period on the policy — refused with
        `ERR_ATTESTATION_PERIOD_OVERLAP`, with half-open semantics meaning a period beginning
        exactly where a prior one ended is not an overlap."

        Design: Corner/errors/attestation_lifecycle_errors_not_ended_not_open_and_overlap
        """
        state = _an_open_period_one_minute_from_its_end(api)
        set_clock(api, PERIOD_END)
        finalize_attestation(api, state["attestation_id"])

        validate_error(
            api.finalize_credit_attestation(state["attestation_id"], {}, ANALYST),
            ApiErrorId.ERR_ATTESTATION_NOT_OPEN,
            409,
        )
        validate_error(
            api.create_credit_attestation(
                state["policy_id"], attestation_payload(*OVERLAPPING_PERIOD), ANALYST
            ),
            ApiErrorId.ERR_ATTESTATION_PERIOD_OVERLAP,
            409,
        )
        assert len(read_attestation_list(api, state["policy_id"])) == 1

        # Abutment at the shared instant is not overlap, so this one opens.
        abutting = open_attestation(api, state["policy_id"], *ABUTTING_PERIOD)
        assert abutting["status"] == "OPEN"
        assert abutting["period_minutes"] == 240
        assert abutting["period_start_at"].startswith("2026-08-01T04:00:00")
        assert len(read_attestation_list(api, state["policy_id"])) == 2


ONE_SAMPLE_AT = "2026-08-01T06:10:00Z"
VACATION_ENDS_AT = "2026-08-10T12:00:00Z"


def _a_learning_device_with_a_policy(api: ApiClient) -> dict:
    """One accepted sample, far short of the sample count that arms a device."""
    state = setup_learning_device(api)
    set_clock(api, ONE_SAMPLE_AT)
    ingest_quiet_reading(api, state["device_id"], ONE_SAMPLE_AT)
    policy = create_policy(api, state["property_id"], POLICY_YEAR_START)
    state["policy"] = policy
    state["policy_id"] = policy["id"]
    return state


class TestALearningDeviceFailsTwoDifferentGates:
    def test_the_attestation_gate_and_the_mode_gate_are_distinct_identifiers(
        self, api: ApiClient
    ):
        """The same posture, two operations, two error ids by design.

        "And the property's device must have a baseline profile currently in `learning_state`
        `COMPLETE`, or the opening is refused with `ERR_BASELINE_NOT_COMPLETE` — this is the
        only place the armed-device requirement is enforced at attestation-opening time, so a
        device that is `LEARNING` or whose profile is `INVALIDATED` fails here specifically."
        "Entering either non-default mode requires the device to be `ARMED` — a device still
        learning, awaiting install verification, mid-transfer, or decommissioned is refused
        with `ERR_DEVICE_NOT_ARMED` — while returning to `NORMAL` carries no such requirement."

        Design: Corner/errors/attestation_and_monitor_mode_on_learning_device_return_distinct_errors
        """
        state = _a_learning_device_with_a_policy(api)
        assert read_live_baseline(api, state["device_id"])["learning_state"] == "COLLECTING"

        validate_error(
            api.create_credit_attestation(
                state["policy_id"], attestation_payload(*FIRST_PERIOD), ANALYST
            ),
            ApiErrorId.ERR_BASELINE_NOT_COMPLETE,
            409,
        )
        validate_error(
            api.set_monitor_mode(
                state["device_id"],
                monitor_mode_payload("VACATION", vacation_ends_at=VACATION_ENDS_AT),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_DEVICE_NOT_ARMED,
            409,
        )

        assert read_attestation_list(api, state["policy_id"]) == []
        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "LEARNING"
        assert device["monitor_mode"] == "NORMAL"
        assert device["vacation_ends_at"] is None


BURST_AT = "2026-08-01T07:00:00Z"
SWEEP_AT = "2026-08-01T07:16:00Z"


def _an_escalated_burst_with_an_acknowledged_ticket(api: ApiClient) -> dict:
    """The ladder ran to stage 2 and the household answered the call."""
    state = setup_armed_device_with_contact(api)
    state["buyer"] = create_buyer(api)
    state["buyer_id"] = state["buyer"]["id"]
    set_clock(api, BURST_AT)
    ingest_burst_reading(api, state["device_id"], BURST_AT)
    events = read_events(api, state["device_id"])
    assert len(events) == 1
    state["event_id"] = events[0]["id"]

    set_clock(api, SWEEP_AT)
    run_ops_sweep(api)
    escalated = read_tickets(api, stage="PENDING_EMERGENCY_CONTACT")
    assert len(escalated) == 1
    state["ticket_id"] = escalated[0]["id"]
    state["ticket"] = acknowledge_ticket(api, state["ticket_id"])
    return state


class TestThreeCatalogErrorsFromOneEscalatedBurst:
    def test_a_call_with_no_identity_is_refused_before_anything_else(
        self, api: ApiClient
    ):
        """The row exists, so only the missing identity can explain the 401.

        "**Authentication** — both headers present, role recognised: `ERR_UNAUTHENTICATED`
        (401)."
        "When a single request violates several rules at once, the response must name the
        violation the server encountered first, and the ordering below is normative rather
        than advisory."

        Design: Corner/errors/unauthenticated_ticket_not_pending_and_unresolved_events_block_transfer
        """
        state = _an_escalated_burst_with_an_acknowledged_ticket(api)
        assert read_device(api, state["device_id"])["id"] == state["device_id"]

        validate_error(
            api.get_device(state["device_id"], ANONYMOUS),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

    def test_an_acknowledged_ticket_and_an_open_event_refuse_different_things(
        self, api: ApiClient
    ):
        """One fixture, two 409s: the ladder is finished and the house is not quiet.

        "Acknowledgement on a ticket that is already `ACKNOWLEDGED` or `EXPIRED` is refused
        with `ERR_TICKET_NOT_PENDING`, and a homeowner acknowledging a ticket belonging to
        another household's event is refused with `ERR_NOT_RESOURCE_OWNER`."
        "The house must be quiet: the device must have no anomaly event whose `event_state` is
        `DETECTED`, `ALERTED`, or `ESCALATED`, and its `valve_state` must be `OPEN`, or the
        attempt is refused with `ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER`."

        Design: Corner/errors/unauthenticated_ticket_not_pending_and_unresolved_events_block_transfer
        """
        state = _an_escalated_burst_with_an_acknowledged_ticket(api)
        assert state["ticket"]["stage"] == "ACKNOWLEDGED"
        seller = make_homeowner_headers(state["homeowner_id"])
        device_version = read_device_version(api, state["device_id"], seller)

        validate_error(
            api.acknowledge_escalation_ticket(state["ticket_id"], {}, ADMIN),
            ApiErrorId.ERR_TICKET_NOT_PENDING,
            409,
        )
        validate_error(
            api.create_device_transfer(
                device_transfer_payload(
                    state["device_id"], state["buyer_id"], device_version
                ),
                seller,
            ),
            ApiErrorId.ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER,
            409,
        )

        _, meta = validate_paginated(
            api.list_device_transfers(ADMIN, {"device_id": state["device_id"]})
        )
        assert meta["total_count"] == 0
        assert read_events(api, state["device_id"])[0]["event_state"] == "ESCALATED"
        assert read_device(api, state["device_id"])["valve_state"] == "CLOSED"


ADJUSTER = make_claims_adjuster_headers(ADJUSTER_USER_ID)


class TestEveryPathScopedIdHasItsOwnNotFoundCode:
    def test_seven_single_resource_paths_answer_seven_different_codes(
        self, api: ApiClient
    ):
        """The same unknown identifier means a different thing on each path.

        "Nested reads resolve their path segments strictly left to right, and the first segment
        that fails to resolve determines the error."
        "The equivalent codes for the remaining single-resource paths are
        `ERR_ANOMALY_EVENT_NOT_FOUND`, `ERR_ESCALATION_TICKET_NOT_FOUND`,
        `ERR_ATTESTATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and `ERR_TRANSFER_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_over_every_path_scoped_id
        """
        setup_armed_device_with_policy(api, POLICY_YEAR_START)

        validate_error(
            api.get_homeowner(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_HOMEOWNER_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_anomaly_event(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_ANOMALY_EVENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_escalation_ticket(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_ESCALATION_TICKET_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_policy(NON_EXISTENT_UUID, ANALYST),
            ApiErrorId.ERR_POLICY_NOT_FOUND,
            404,
        )
        validate_error(
            api.finalize_credit_attestation(NON_EXISTENT_UUID, {}, ANALYST),
            ApiErrorId.ERR_ATTESTATION_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_claim(NON_EXISTENT_UUID, ADJUSTER),
            ApiErrorId.ERR_CLAIM_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_device_transfer(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_TRANSFER_NOT_FOUND,
            404,
        )

    def test_a_body_borne_event_id_answers_the_event_code_and_writes_nothing(
        self, api: ApiClient
    ):
        """The body foreign key resolves before any claim-specific rule runs.

        "Identifiers carried in a request *body* rather than the path resolve the same way and
        reuse the same codes: an unresolvable `homeowner_id` or `to_homeowner_id` yields
        `ERR_HOMEOWNER_NOT_FOUND`, an unresolvable `property_id` yields
        `ERR_PROPERTY_NOT_FOUND`, an unresolvable `device_id` yields `ERR_DEVICE_NOT_FOUND`, an
        unresolvable `anomaly_event_id` yields `ERR_ANOMALY_EVENT_NOT_FOUND`, and an
        unresolvable `policy_id` yields `ERR_POLICY_NOT_FOUND`."
        "That optionality is load-bearing."

        Design: Corner/errors/not_found_sweep_over_every_path_scoped_id
        """
        state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
        version_before = read_device_version(api, state["device_id"])

        validate_error(
            api.create_claim(
                claim_payload(
                    state["policy_id"],
                    state["device_id"],
                    "WATER_DAMAGE",
                    200000,
                    anomaly_event_id=NON_EXISTENT_UUID,
                ),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_ANOMALY_EVENT_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(
            api.list_claims(ADMIN, {"policy_id": state["policy_id"]})
        )
        assert meta["total_count"] == 0
        assert read_device_version(api, state["device_id"]) == version_before


OVERRIDE_REASON = "plumber says the line is fine"


def _a_valve_the_system_closed_for_a_live_burst(api: ApiClient) -> dict:
    """The burst is still ALERTED, so the reopen has something to refuse."""
    state = setup_burst_event(api, BURST_AT)
    state["closed_version"] = read_device_version(api, state["device_id"])
    return state


def _attempt_reopen(api: ApiClient, state: dict, **extra):
    return api.send_valve_command(
        state["device_id"],
        valve_command_payload(
            "OPEN",
            state["closed_version"],
            override_reason=OVERRIDE_REASON,
            **extra,
        ),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestReopeningALiveBurstNeedsAWrittenAcknowledgement:
    def test_a_reason_without_the_acknowledgement_flag_is_refused(
        self, api: ApiClient
    ):
        """A written reason alone does not clear the gate, and nothing moves.

        "A reopen is refused outright — `ERR_UNRESOLVED_BURST_BLOCKS_REOPEN` — while the device
        still has an anomaly event whose `classification` is `CATASTROPHIC_BURST` and whose
        `event_state` is `ALERTED` or `ESCALATED`, *unless* the command carries
        `acknowledge_water_damage_risk` set to true together with a non-empty `override_reason`."
        "In other words, the burst must be resolved, relabelled a false positive, or explicitly
        overridden with a written acknowledgement before water is restored; the platform will
        not silently move water back into a house it believes is flooding."

        Design: Corner/errors/reopen_during_unresolved_burst_needs_written_acknowledgement
        """
        state = _a_valve_the_system_closed_for_a_live_burst(api)

        validate_error(
            _attempt_reopen(api, state),
            ApiErrorId.ERR_UNRESOLVED_BURST_BLOCKS_REOPEN,
            409,
        )

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "CLOSED"
        assert device["reopen_count"] == 0
        assert device["close_count"] == 1
        assert device["version"] == state["closed_version"]

        event = read_events(api, state["device_id"])[0]
        assert event["classification"] == "CATASTROPHIC_BURST"
        assert event["event_state"] == "ALERTED"
        assert event["override_reopen_at"] is None

    def test_the_byte_identical_command_plus_the_flag_is_accepted(
        self, api: ApiClient
    ):
        """The acknowledgement is the only difference, and it restores the water.

        "When the reopen is accepted, `reopen_count` increases by 1 — restoring the parity
        invariant that `close_count` minus `reopen_count` equals 1 while the valve is `CLOSED`
        and 0 while it is `OPEN` — every irrigation window on the property whose `status` is
        `SUSPENDED_BY_SHUTOFF` returns to `ACTIVE` with `suspended_at` cleared back to null, and
        the device's `version` increases by 1."
        "Every anomaly event on the device still sitting in `ALERTED` or `ESCALATED` has its
        `override_reopen_at` stamped at the clock, which both clears that event's
        `mitigation_credited` and starts the two-hour auto-shutoff immunity described above."

        Design: Corner/errors/reopen_during_unresolved_burst_needs_written_acknowledgement
        """
        state = _a_valve_the_system_closed_for_a_live_burst(api)
        validate_error(
            _attempt_reopen(api, state),
            ApiErrorId.ERR_UNRESOLVED_BURST_BLOCKS_REOPEN,
            409,
        )

        reopened = get_success_data(
            _attempt_reopen(api, state, acknowledge_water_damage_risk=True)
        )
        assert reopened["valve_state"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert reopened["version"] == state["closed_version"] + 1

        event = read_events(api, state["device_id"])[0]
        assert event["event_state"] == "ALERTED"
        assert event["override_reopen_at"].startswith("2026-08-01T07:00:00")
        assert event["mitigation_credited"] is False


EXPIRES_AT = "2026-08-08T06:05:00Z"
SECOND_EXPIRES_AT = "2026-08-15T06:05:00Z"
ONE_MINUTE_PAST_SECOND = "2026-08-15T06:06:00Z"


def _a_transfer_on_its_last_legal_instant(api: ApiClient) -> dict:
    """Initiated at the fixture clock, so the clock now equals expires_at."""
    state = setup_pending_transfer(api)
    assert state["transfer"]["expires_at"].startswith("2026-08-08T06:05:00")
    set_clock(api, EXPIRES_AT)
    return state


class TestTheAcceptWindowIncludesItsLastInstant:
    def test_accepting_exactly_at_expires_at_succeeds_then_cannot_repeat(
        self, api: ApiClient
    ):
        """No sweep has run, so the row is still pending at its own expiry instant.

        "The transfer must still be `INITIATED` — otherwise `ERR_TRANSFER_NOT_PENDING` — the
        clock must be no later than `expires_at`, with acceptance at exactly that instant still
        succeeding and anything later refused with `ERR_TRANSFER_WINDOW_EXPIRED`, the acting
        `X-User-ID` must equal `to_homeowner_id` (otherwise `ERR_TRANSFER_TARGET_INVALID`) and
        that buyer account must be `ACTIVE`, and the device must still have an `OPEN` valve and
        no anomaly event in `ALERTED` or `ESCALATED` (otherwise
        `ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER`)."
        "The transfer moves `INITIATED → ACCEPTED` with `accepted_at` stamped at the clock and
        `accepted_by_user_id` recording the buyer."

        Design: Corner/errors/transfer_accept_at_expiry_boundary_then_not_pending_then_expired
        """
        state = _a_transfer_on_its_last_legal_instant(api)

        accepted = accept_transfer(api, state["transfer_id"], state["buyer_id"])
        assert_device_transfer(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_at"].startswith("2026-08-08T06:05:00")
        assert accepted["accepted_by_user_id"] == state["buyer_id"]

        validate_error(
            api.accept_device_transfer(
                state["transfer_id"], {}, make_homeowner_headers(state["buyer_id"])
            ),
            ApiErrorId.ERR_TRANSFER_NOT_PENDING,
            409,
        )

        # The ownership cascade ran once, not twice.
        home = read_property(api, state["property_id"])
        assert home["homeowner_id"] == state["buyer_id"]
        assert home["property_state"] == "ACTIVE"
        assert read_transfer(api, state["transfer_id"])["status"] == "ACCEPTED"

    def test_a_later_transfer_one_minute_past_its_own_expiry_is_refused(
        self, api: ApiClient
    ):
        """Nothing but an accept attempt happens, so only the clock explains the 409.

        "The row is created in `status` `INITIATED` with `from_homeowner_id` recording the
        property's current owner, `initiated_at` stamped at the clock, and `expires_at` set to
        168 hours — a full week — after initiation; `accepted_at`, `accepted_by_user_id`, and
        `cancel_reason` all begin null."
        "The transfer must still be `INITIATED` — otherwise `ERR_TRANSFER_NOT_PENDING` — the
        clock must be no later than `expires_at`, with acceptance at exactly that instant still
        succeeding and anything later refused with `ERR_TRANSFER_WINDOW_EXPIRED`, the acting
        `X-User-ID` must equal `to_homeowner_id` (otherwise `ERR_TRANSFER_TARGET_INVALID`) and
        that buyer account must be `ACTIVE`, and the device must still have an `OPEN` valve and
        no anomaly event in `ALERTED` or `ESCALATED` (otherwise
        `ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER`)."

        Design: Corner/errors/transfer_accept_at_expiry_boundary_then_not_pending_then_expired
        """
        state = _a_transfer_on_its_last_legal_instant(api)
        accept_transfer(api, state["transfer_id"], state["buyer_id"])

        # The new owner starts a sale back to the original household.
        second = initiate_transfer(
            api, state["device_id"], state["homeowner_id"], state["buyer_id"]
        )
        assert second["status"] == "INITIATED"
        assert second["from_homeowner_id"] == state["buyer_id"]
        assert second["initiated_at"].startswith("2026-08-08T06:05:00")
        assert second["expires_at"].startswith("2026-08-15T06:05:00")
        assert second["accepted_at"] is None
        assert second["cancel_reason"] is None

        set_clock(api, ONE_MINUTE_PAST_SECOND)
        validate_error(
            api.accept_device_transfer(
                second["id"], {}, make_homeowner_headers(state["homeowner_id"])
            ),
            ApiErrorId.ERR_TRANSFER_WINDOW_EXPIRED,
            409,
        )

        # Only an operational sweep would move a lapsed row to EXPIRED.
        assert read_transfer(api, second["id"])["status"] == "INITIATED"
        assert (
            read_property(api, state["property_id"])["homeowner_id"]
            == state["buyer_id"]
        )
