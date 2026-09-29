"""Boundary conditions on the rules that admit or refuse a write.

Three of these guard the telemetry stream: no sample after the clock, none more
than a day behind it, and none repeating an instant already recorded.  The other
three guard cross-entity shape: an irrigation flag on the property, a contiguous
attestation chain on the policy, and one live claim per event and type.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_credit_attestation,
    assert_irrigation_window,
    assert_reimbursement_claim,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    attestation_payload,
    claim_payload,
    irrigation_window_payload,
    telemetry_payload,
)
from test_helpers.fixtures import (
    create_irrigation_window,
    create_second_property,
    file_claim,
    ingest_reading,
    open_attestation,
    read_attestation_list,
    read_claim,
    read_device,
    read_irrigation_windows,
    read_policy,
    read_telemetry,
    set_clock,
    setup_armed_device,
    setup_armed_device_with_policy,
    setup_burst_event_with_policy,
    setup_household,
)
from test_helpers.test_users import (
    GATEWAY_USER_ID,
    INSURER_ANALYST_USER_ID,
    make_gateway_headers,
    make_homeowner_headers,
    make_insurer_analyst_headers,
)

LAST_LEARNING_AT = "2026-08-01T00:40:00Z"
QUIET_SAMPLE = {
    "static_pressure_psi": 57.0,
    "flow_gpm": 0.0,
    "duration_minutes": 0.0,
    "total_gallons": 0.0,
}


def _attempt_ingest(api: ApiClient, device_id: str, reading_at: str):
    """Post a quiet sample without asserting success."""
    return api.create_telemetry_reading(
        device_id,
        telemetry_payload(reading_at, **QUIET_SAMPLE),
        make_gateway_headers(GATEWAY_USER_ID),
    )


class TestTelemetryStreamIsStrictlyIncreasing:
    def test_a_repeat_of_the_last_recorded_instant_is_refused(self, api: ApiClient):
        """The third learning sample stamped 00:40Z closes that instant forever.

        "And the stream must be strictly increasing: `reading_at` must be strictly later
        than the device's `last_reading_at`, so a repeat of the previous instant is refused
        with `ERR_READING_OUT_OF_ORDER`."
        "A refused sample is never persisted at all — it leaves no trace, contributes
        nothing to learning, and, importantly, contributes nothing to the uptime coverage
        the insurer scores."

        Design: Corner/validations/reading_with_duplicate_timestamp_returns_reading_out_of_order
        """
        state = setup_armed_device(api)
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:00"
        )

        validate_error(
            _attempt_ingest(api, state["device_id"], LAST_LEARNING_AT),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
            409,
        )
        # An earlier instant is refused by the same rule, not by the backdate floor.
        validate_error(
            _attempt_ingest(api, state["device_id"], "2026-08-01T00:30:00Z"),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
            409,
        )

        assert len(read_telemetry(api, state["device_id"])) == 3
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:00"
        )

    def test_one_second_later_than_the_last_instant_is_accepted(self, api: ApiClient):
        """Strictly later is the whole requirement, so a second suffices.

        "And the stream must be strictly increasing: `reading_at` must be strictly later
        than the device's `last_reading_at`, so a repeat of the previous instant is refused
        with `ERR_READING_OUT_OF_ORDER`."
        "**Step one**, the reading is persisted, with `device_id` set to the emitting
        device and `last_reading_at` on the device advanced to the new `reading_at`."

        Design: Corner/validations/reading_with_duplicate_timestamp_returns_reading_out_of_order
        """
        state = setup_armed_device(api)
        validate_error(
            _attempt_ingest(api, state["device_id"], LAST_LEARNING_AT),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
            409,
        )

        accepted = ingest_reading(
            api, state["device_id"], "2026-08-01T00:40:01Z", **QUIET_SAMPLE
        )
        assert accepted["reading_at"].startswith("2026-08-01T00:40:01")
        assert len(read_telemetry(api, state["device_id"])) == 4
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:01"
        )


BACKDATE_CLOCK = "2026-08-02T00:45:00Z"
AT_BACKDATE_FLOOR = "2026-08-01T00:45:00Z"
ONE_MINUTE_TOO_OLD = "2026-08-01T00:44:00Z"


class TestBackdateFloorIsInclusive:
    def test_one_minute_beyond_the_floor_is_refused_as_too_old(self, api: ApiClient):
        """With the clock at 00:45Z on the second, 00:44Z on the first is stale.

        "The sample may not be backdated by more than a full day: a `reading_at` exactly 24
        hours before the clock is accepted, one minute earlier is refused with
        `ERR_READING_TOO_OLD`."
        "A refused sample is never persisted at all — it leaves no trace, contributes
        nothing to learning, and, importantly, contributes nothing to the uptime coverage
        the insurer scores."

        Design: Corner/validations/reading_at_exactly_backdate_boundary_is_accepted
        """
        state = setup_armed_device(api)
        set_clock(api, BACKDATE_CLOCK)

        validate_error(
            _attempt_ingest(api, state["device_id"], ONE_MINUTE_TOO_OLD),
            ApiErrorId.ERR_READING_TOO_OLD,
            422,
        )

        assert len(read_telemetry(api, state["device_id"])) == 3
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:00"
        )

    def test_exactly_twenty_four_hours_before_the_clock_is_accepted(
        self, api: ApiClient
    ):
        """The boundary instant itself passes and vouches for its two hours.

        "The sample may not be backdated by more than a full day: a `reading_at` exactly 24
        hours before the clock is accepted, one minute earlier is refused with
        `ERR_READING_TOO_OLD`."
        "Every persisted reading also carries `coverage_minutes`, fixed at 120,
        representing the two hours of monitoring uptime that one sample vouches for;
        §3.7 explains how those spans are merged into an insurer-facing uptime figure."

        Design: Corner/validations/reading_at_exactly_backdate_boundary_is_accepted
        """
        state = setup_armed_device(api)
        set_clock(api, BACKDATE_CLOCK)
        validate_error(
            _attempt_ingest(api, state["device_id"], ONE_MINUTE_TOO_OLD),
            ApiErrorId.ERR_READING_TOO_OLD,
            422,
        )

        accepted = get_success_data(
            _attempt_ingest(api, state["device_id"], AT_BACKDATE_FLOOR), 201
        )
        assert accepted["reading_at"].startswith("2026-08-01T00:45:00")
        assert accepted["classification_at_ingest"] == "NONE"
        assert accepted["coverage_minutes"] == 120

        assert len(read_telemetry(api, state["device_id"])) == 4
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:45:00"
        )


AT_THE_CLOCK = "2026-08-01T06:05:00Z"
ONE_MINUTE_AHEAD = "2026-08-01T06:06:00Z"


class TestReadingMayNotOutrunTheClock:
    def test_a_sample_stamped_after_the_clock_is_refused(self, api: ApiClient):
        """One minute of the future is still the future.

        "The sample may not be stamped after the logical clock: a `reading_at` exactly
        equal to the clock is accepted, one minute later is refused with
        `ERR_READING_IN_FUTURE`."
        "A refused sample is never persisted at all — it leaves no trace, contributes
        nothing to learning, and, importantly, contributes nothing to the uptime coverage
        the insurer scores."

        Design: Corner/validations/reading_stamped_after_clock_returns_reading_in_future
        """
        state = setup_armed_device(api)

        validate_error(
            _attempt_ingest(api, state["device_id"], ONE_MINUTE_AHEAD),
            ApiErrorId.ERR_READING_IN_FUTURE,
            422,
        )

        assert len(read_telemetry(api, state["device_id"])) == 3
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:00"
        )

    def test_a_sample_stamped_exactly_at_the_clock_is_accepted(self, api: ApiClient):
        """The comparison is at-or-before, so the present instant qualifies.

        "The sample may not be stamped after the logical clock: a `reading_at` exactly
        equal to the clock is accepted, one minute later is refused with
        `ERR_READING_IN_FUTURE`."
        "Three temporal integrity rules then apply, in this order."

        Design: Corner/validations/reading_stamped_after_clock_returns_reading_in_future
        """
        state = setup_armed_device(api)
        validate_error(
            _attempt_ingest(api, state["device_id"], ONE_MINUTE_AHEAD),
            ApiErrorId.ERR_READING_IN_FUTURE,
            422,
        )

        accepted = get_success_data(
            _attempt_ingest(api, state["device_id"], AT_THE_CLOCK), 201
        )
        assert accepted["reading_at"].startswith("2026-08-01T06:05:00")
        assert accepted["classification_at_ingest"] == "NONE"

        assert len(read_telemetry(api, state["device_id"])) == 4
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T06:05:00"
        )


IRRIGATION_SPAN = ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z")
SPAN_LABEL = "Front zone Saturday"


def _one_irrigated_and_one_dry_property(api: ApiClient) -> dict:
    """The same account holds both, so the refusal cannot be an ownership one."""
    state = setup_household(api)
    dry = create_second_property(api, state["homeowner_id"])
    state["dry_property_id"] = dry["id"]
    assert dry["irrigation_present"] is False
    return state


def _attempt_window(api: ApiClient, state: dict, property_id: str):
    return api.create_irrigation_window(
        property_id,
        irrigation_window_payload(*IRRIGATION_SPAN, 9.0, label=SPAN_LABEL),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestIrrigationWindowRequiresThePropertyFlag:
    def test_a_window_on_a_property_without_irrigation_is_refused(
        self, api: ApiClient
    ):
        """No window exists on either property, so nothing else can be blocking.

        "The property must have `irrigation_present` true or the declaration is refused
        with `ERR_IRRIGATION_NOT_ENABLED`, and the submitted half-open span must not overlap
        any window on the property whose `status` is `ACTIVE`, or the declaration is refused
        with `ERR_IRRIGATION_WINDOW_OVERLAP`."
        "One further flag matters far more than it looks: `irrigation_present` declares
        whether the property has a sprinkler system, defaults to false, and gates whether
        irrigation exclusion windows may be declared at all."

        Design: Corner/validations/irrigation_window_on_property_without_irrigation_returns_not_enabled
        """
        state = _one_irrigated_and_one_dry_property(api)

        validate_error(
            _attempt_window(api, state, state["dry_property_id"]),
            ApiErrorId.ERR_IRRIGATION_NOT_ENABLED,
            409,
        )

        assert (
            read_irrigation_windows(
                api, state["dry_property_id"], state["homeowner_headers"]
            )
            == []
        )

    def test_the_identical_body_on_the_irrigated_property_is_accepted(
        self, api: ApiClient
    ):
        """Only the flag differs between the two calls, and it decides them.

        "The property must have `irrigation_present` true or the declaration is refused
        with `ERR_IRRIGATION_NOT_ENABLED`, and the submitted half-open span must not overlap
        any window on the property whose `status` is `ACTIVE`, or the declaration is refused
        with `ERR_IRRIGATION_WINDOW_OVERLAP`."
        "New windows are created `ACTIVE` with `suspended_at` null and reference the owning
        `property_id`; a window may later be `SUSPENDED_BY_SHUTOFF` while the valve is
        closed, or `CANCELLED` when the owning account closes."

        Design: Corner/validations/irrigation_window_on_property_without_irrigation_returns_not_enabled
        """
        state = _one_irrigated_and_one_dry_property(api)
        validate_error(
            _attempt_window(api, state, state["dry_property_id"]),
            ApiErrorId.ERR_IRRIGATION_NOT_ENABLED,
            409,
        )

        window = get_success_data(
            _attempt_window(api, state, state["property_id"]), 201
        )
        assert_irrigation_window(window)
        assert window["property_id"] == state["property_id"]
        assert window["status"] == "ACTIVE"
        assert window["suspended_at"] is None
        assert window["label"] == SPAN_LABEL

        assert (
            len(
                read_irrigation_windows(
                    api, state["property_id"], state["homeowner_headers"]
                )
            )
            == 1
        )


POLICY_YEAR_START = "2026-08-01T00:00:00Z"
GAPPED_PERIOD = ("2026-08-01T01:00:00Z", "2026-08-01T05:00:00Z")
ANCHORED_PERIOD = ("2026-08-01T00:00:00Z", "2026-08-01T04:00:00Z")


def _attempt_attestation(api: ApiClient, policy_id: str, span):
    return api.create_credit_attestation(
        policy_id,
        attestation_payload(*span),
        make_insurer_analyst_headers(INSURER_ANALYST_USER_ID),
    )


class TestAttestationChainMustBeContiguous:
    def test_a_gap_at_the_head_of_the_policy_year_is_refused(self, api: ApiClient):
        """An hour of daylight before the first period is not allowed.

        "The period must be contiguous: `period_start_at` must equal the policy's
        `last_attestation_end_at` when the policy already has a finalized period, and must
        equal the policy's `policy_year_start_at` for the very first period; a gap in the
        chain is refused with `ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS`."
        "The period must not overlap any existing period on the policy — refused with
        `ERR_ATTESTATION_PERIOD_OVERLAP`, with half-open semantics meaning a period
        beginning exactly where a prior one ended is not an overlap."

        Design: Corner/validations/attestation_period_not_starting_at_policy_year_start_returns_not_contiguous
        """
        state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
        assert read_policy(api, state["policy_id"])["last_attestation_end_at"] is None

        validate_error(
            _attempt_attestation(api, state["policy_id"], GAPPED_PERIOD),
            ApiErrorId.ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS,
            409,
        )

        assert read_attestation_list(api, state["policy_id"]) == []

    def test_the_same_span_anchored_at_the_policy_year_start_is_accepted(
        self, api: ApiClient
    ):
        """Starting exactly at the policy year start closes the gap.

        "The period must be contiguous: `period_start_at` must equal the policy's
        `last_attestation_end_at` when the policy already has a finalized period, and must
        equal the policy's `policy_year_start_at` for the very first period; a gap in the
        chain is refused with `ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS`."
        "A newly opened attestation records its `policy_id`, begins in `status` `OPEN`, has
        `period_minutes` computed immediately as the whole number of minutes in its
        half-open span, and leaves `covered_minutes`, `uptime_pct`, `offline_gap_count`, and
        `tier_pct` null, `credit_cents_awarded` and `true_up_cents` at 0,
        `is_policy_year_close` false, and `device_snapshot_lifecycle_state`,
        `denial_reason`, and `finalized_at` all null."

        Design: Corner/validations/attestation_period_not_starting_at_policy_year_start_returns_not_contiguous
        """
        state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
        validate_error(
            _attempt_attestation(api, state["policy_id"], GAPPED_PERIOD),
            ApiErrorId.ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS,
            409,
        )

        opened = open_attestation(api, state["policy_id"], *ANCHORED_PERIOD)
        assert_credit_attestation(opened)
        assert opened["policy_id"] == state["policy_id"]
        assert opened["period_start_at"].startswith("2026-08-01T00:00:00")
        assert opened["period_end_at"].startswith("2026-08-01T04:00:00")
        assert opened["status"] == "OPEN"
        assert opened["period_minutes"] == 240
        assert opened["uptime_pct"] is None
        assert opened["covered_minutes"] is None
        assert opened["tier_pct"] is None
        assert opened["finalized_at"] is None

        rows = read_attestation_list(api, state["policy_id"])
        assert len(rows) == 1
        assert rows[0]["id"] == opened["id"]


WATER_DAMAGE_LOSS_CENTS = 400000
SECOND_WATER_DAMAGE_LOSS_CENTS = 250000
WARRANTY_LOSS_CENTS = 120000


def _one_water_damage_claim_on_the_burst(api: ApiClient) -> dict:
    """A single SUBMITTED claim occupying the WATER_DAMAGE slot on the event."""
    state = setup_burst_event_with_policy(api)
    state["claim"] = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WATER_DAMAGE",
        WATER_DAMAGE_LOSS_CENTS,
        state["homeowner_id"],
        anomaly_event_id=state["event_id"],
    )
    state["claim_id"] = state["claim"]["id"]
    return state


def _attempt_claim(api: ApiClient, state: dict, claim_type: str, loss_cents: int):
    return api.create_claim(
        claim_payload(
            state["policy_id"],
            state["device_id"],
            claim_type,
            loss_cents,
            anomaly_event_id=state["event_id"],
        ),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestOneLiveClaimPerEventAndType:
    def test_a_second_water_damage_filing_on_the_same_event_is_refused(
        self, api: ApiClient
    ):
        """The slot is occupied by a SUBMITTED row, which is not DENIED.

        "And a given event may support only one live claim per type: if another claim
        already exists for the same `anomaly_event_id` and the same `claim_type` in any
        status other than `DENIED`, the filing is refused with `ERR_DUPLICATE_CLAIM` — a
        denied claim leaves the slot free to try again."
        "A new claim is created in `status` `SUBMITTED` with `approved_payout_cents` and
        `deductible_applied_cents` at 0, `info_request_count` at 0, `payout_variant`,
        `decided_by_user_id`, `decided_at`, `denial_reason`, and `paid_at` all null,
        `submitted_by_user_id` set to the resolved homeowner's identifier, and `version` at
        1."

        Design: Corner/validations/second_claim_on_same_event_and_type_returns_duplicate_claim
        """
        state = _one_water_damage_claim_on_the_burst(api)

        validate_error(
            _attempt_claim(
                api, state, "WATER_DAMAGE", SECOND_WATER_DAMAGE_LOSS_CENTS
            ),
            ApiErrorId.ERR_DUPLICATE_CLAIM,
            409,
        )

        # The refused filing left the incumbent exactly as it was.
        incumbent = read_claim(
            api, state["claim_id"], make_homeowner_headers(state["homeowner_id"])
        )
        assert incumbent["documented_loss_cents"] == WATER_DAMAGE_LOSS_CENTS
        assert incumbent["status"] == "SUBMITTED"
        assert incumbent["version"] == 1

    def test_a_warranty_filing_on_the_same_event_occupies_its_own_slot(
        self, api: ApiClient
    ):
        """The key is the pair, so a different claim_type is a different slot.

        "And a given event may support only one live claim per type: if another claim
        already exists for the same `anomaly_event_id` and the same `claim_type` in any
        status other than `DENIED`, the filing is refused with `ERR_DUPLICATE_CLAIM` — a
        denied claim leaves the slot free to try again."
        "The submission names the `policy_id` the claim is filed against, the `device_id`
        whose warranty or mitigation performance is at issue, a `claim_type` of either
        `WARRANTY_DEVICE` for a hardware failure or `WATER_DAMAGE` for loss reimbursement, a
        `documented_loss_cents` figure of at least 1 cent representing the documented loss
        or repair cost, and optionally an `anomaly_event_id` naming the qualifying event."

        Design: Corner/validations/second_claim_on_same_event_and_type_returns_duplicate_claim
        """
        state = _one_water_damage_claim_on_the_burst(api)
        validate_error(
            _attempt_claim(
                api, state, "WATER_DAMAGE", SECOND_WATER_DAMAGE_LOSS_CENTS
            ),
            ApiErrorId.ERR_DUPLICATE_CLAIM,
            409,
        )

        warranty = get_success_data(
            _attempt_claim(api, state, "WARRANTY_DEVICE", WARRANTY_LOSS_CENTS), 201
        )
        assert_reimbursement_claim(warranty)
        assert warranty["claim_type"] == "WARRANTY_DEVICE"
        assert warranty["status"] == "SUBMITTED"
        assert warranty["anomaly_event_id"] == state["event_id"]
        assert warranty["submitted_by_user_id"] == state["homeowner_id"]
        assert warranty["approved_payout_cents"] == 0
        assert warranty["deductible_applied_cents"] == 0
        assert warranty["info_request_count"] == 0
        assert warranty["payout_variant"] is None
        assert warranty["version"] == 1

        rows, meta = validate_paginated(
            api.list_claims(
                make_homeowner_headers(state["homeowner_id"]),
                {"anomaly_event_id": state["event_id"]},
            )
        )
        assert meta["total_count"] == 2
        assert {row["claim_type"] for row in rows} == {
            "WATER_DAMAGE",
            "WARRANTY_DEVICE",
        }
