"""Outcomes that hinge on the state of a second, related entity.

Whether a burst reading mints an event at all depends on the device's lifecycle,
not on the reading; the identical sample that alerts on an armed device is filed
silently while a transfer is pending.  Whether a claim is admissible depends on the
policy it names, so a superseded policy refuses the body its successor accepts.
"""

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_insurance_policy,
    assert_reimbursement_claim,
    get_success_data,
    validate_error,
)
from test_helpers.constants import CANONICAL_BURST_READING
from test_helpers.factories import claim_payload, valve_command_payload
from test_helpers.fixtures import (
    create_policy,
    ingest_burst_reading,
    read_device,
    read_device_version,
    read_events,
    read_live_baseline,
    read_policy,
    read_telemetry,
    read_tickets,
    read_transfer,
    set_clock,
    setup_armed_device,
    setup_pending_transfer,
)
from test_helpers.test_users import make_homeowner_headers

BURST_AT = "2026-08-01T07:00:00Z"


def _burst_against_a_transfer_pending_device(api: ApiClient) -> dict:
    """Ingest the canonical burst sample while the buyer has yet to accept."""
    state = setup_pending_transfer(api)
    set_clock(api, BURST_AT)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], BURST_AT)
    return state


class TestTransferPendingDeviceSuppressesAlert:
    def test_a_burst_sample_on_a_transfer_pending_device_is_never_classified(
        self, api: ApiClient
    ):
        """The reading is accepted, yet the whole detection cascade is skipped.

        "A device accepts telemetry only while its `lifecycle_state` is `LEARNING`,
        `ARMED`, or `TRANSFER_PENDING`."
        "Classification itself runs only when the device's profile is `COMPLETE` and
        its `lifecycle_state` is `ARMED`."
        "**Step one**, the reading is persisted, with `device_id` set to the
        emitting device and `last_reading_at` on the device advanced to the new
        `reading_at`."

        Design: Difficulty/cross_entity_state_dependency/transfer_pending_device_suppresses_alert
        """
        state = _burst_against_a_transfer_pending_device(api)

        rows = read_telemetry(api, state["device_id"])
        burst = [r for r in rows if r["reading_at"].startswith("2026-08-01T07:00:00")]
        assert len(burst) == 1
        assert burst[0]["classification_at_ingest"] == "NONE"
        assert burst[0]["anomaly_event_created"] is False
        assert burst[0]["flow_gpm"] == CANONICAL_BURST_READING["flow_gpm"]

        # The gate on the other entity suppressed event, ticket and shutoff alike.
        assert read_events(api, state["device_id"]) == []
        assert read_tickets(api) == []

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0
        assert device["last_shutoff_at"] is None
        assert device["last_reading_at"].startswith("2026-08-01T07:00:00")

    def test_the_pending_transfer_also_freezes_the_homeowners_valve_command(
        self, api: ApiClient
    ):
        """A version read after the ingest clears concurrency, so the lock answers.

        "While the device is `TRANSFER_PENDING` it still ingests telemetry, but
        every anomaly minted is created `SUPPRESSED` with `suppression_reason`
        `DEVICE_NOT_ARMED`, and valve commands, mode changes, and firmware pushes
        are all refused with `ERR_DEVICE_TRANSFER_LOCKED`."
        "The row is created in `status` `INITIATED` with `from_homeowner_id`
        recording the property's current owner, `initiated_at` stamped at the clock,
        and `expires_at` set to 168 hours — a full week — after initiation;
        `accepted_at`, `accepted_by_user_id`, and `cancel_reason` all begin null."

        Design: Difficulty/cross_entity_state_dependency/transfer_pending_device_suppresses_alert
        """
        state = _burst_against_a_transfer_pending_device(api)
        current_version = read_device_version(
            api, state["device_id"], state["homeowner_headers"]
        )

        response = api.send_valve_command(
            state["device_id"],
            valve_command_payload("CLOSE", current_version),
            make_homeowner_headers(state["homeowner_id"]),
        )
        validate_error(response, ApiErrorId.ERR_DEVICE_TRANSFER_LOCKED, 409)

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "TRANSFER_PENDING"
        assert device["valve_state"] == "OPEN"

        transfer = read_transfer(api, state["transfer_id"])
        assert transfer["status"] == "INITIATED"
        assert transfer["expires_at"].startswith("2026-08-08T06:05:00")

    def test_the_complete_profile_does_not_absorb_the_unclassified_reading(
        self, api: ApiClient
    ):
        """Recomputation is scoped to a COLLECTING cycle, so the learned values hold.

        "On each accepted reading while the profile is still `COLLECTING`, three
        values are recomputed over exactly that eligible set"
        "The transition `COLLECTING → COMPLETE` publishes the three learned values,
        increments `baseline_version` by 1, and stamps `completed_at` with the clock
        — and that publication bubbles up to promote the device from `LEARNING` to
        `ARMED`, setting `baseline_ready` to true."
        "Those three conditions together define eligibility: a reading is
        baseline-eligible exactly when its frozen classification is `NONE`, its
        `reading_source` is `DEVICE`, and its `suppressed_by_irrigation` flag is
        false."

        Design: Difficulty/cross_entity_state_dependency/transfer_pending_device_suppresses_alert
        """
        state = _burst_against_a_transfer_pending_device(api)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "COMPLETE"
        # Neither learned value nor version moves: recomputation belongs to a
        # COLLECTING cycle and this profile is already COMPLETE.
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(6.00, abs=0.01)
        assert profile["baseline_version"] == 3
        # The unclassified sample is still a DEVICE reading whose frozen
        # classification is `NONE`, so it is baseline-eligible and the count of
        # eligible readings since `learning_started_at` is now four — the count is
        # a definition over the eligible set, not a tally the completion froze.
        assert profile["sample_count"] == 4


POLICY_YEAR_START = "2026-08-01T00:00:00Z"
DOCUMENTED_LOSS_CENTS = 620_000


def _superseded_and_superseding_policies(api: ApiClient) -> dict:
    """One property, one qualifying burst, and two policies written in order."""
    state = setup_armed_device(api)
    set_clock(api, BURST_AT)
    ingest_burst_reading(api, state["device_id"], BURST_AT)
    events = read_events(api, state["device_id"], event_state="ALERTED")
    assert len(events) == 1
    state["event_id"] = events[0]["id"]

    first = create_policy(api, state["property_id"], POLICY_YEAR_START)
    second = create_policy(
        api,
        state["property_id"],
        POLICY_YEAR_START,
        policy_number="POL-2225-B",
    )
    state["superseded_policy_id"] = first["id"]
    state["superseding_policy_id"] = second["id"]
    return state


def _water_damage_body(state: dict, policy_id: str) -> dict:
    return claim_payload(
        policy_id,
        state["device_id"],
        "WATER_DAMAGE",
        DOCUMENTED_LOSS_CENTS,
        anomaly_event_id=state["event_id"],
    )


class TestTerminatedPolicyBlocksClaimSubmission:
    def test_filing_against_the_superseded_policy_is_refused(self, api: ApiClient):
        """Admissibility follows the policy's state, not the claim's contents.

        "Termination is one-way: a `TERMINATED` policy freezes its
        `credited_cents_total` as it stands, with no clawback applied on
        termination, and any write that depends on it — opening an attestation,
        finalizing one, submitting a claim, or advancing a claim decision — is
        refused with `ERR_POLICY_TERMINATED`."
        "Every prior policy on the same property that is not already `TERMINATED` is
        driven to `TERMINATED` with its own `version` incremented by 1, and the
        property's `version` is incremented by 1 as well — which is exactly what
        makes a second analyst's stale `expected_property_version` detectable."

        Design: Difficulty/cross_entity_state_dependency/terminated_policy_blocks_claim_submission
        """
        state = _superseded_and_superseding_policies(api)

        response = api.create_claim(
            _water_damage_body(state, state["superseded_policy_id"]),
            make_homeowner_headers(state["homeowner_id"]),
        )
        validate_error(response, ApiErrorId.ERR_POLICY_TERMINATED, 409)

        rows = get_success_data(
            api.list_claims(
                make_homeowner_headers(state["homeowner_id"]),
                {"policy_id": state["superseded_policy_id"]},
            )
        )
        assert rows == []

    def test_the_identical_body_is_accepted_against_the_superseding_policy(
        self, api: ApiClient
    ):
        """Same device, same event, same loss, same claim type — different policy.

        "A `WATER_DAMAGE` claim **must** carry `anomaly_event_id`, and the
        referenced event must belong to the referenced device, which must in turn
        belong to the policy's property; any of those three failures is refused with
        `ERR_NO_QUALIFYING_EVENT`."
        "A new claim is created in `status` `SUBMITTED` with `approved_payout_cents`
        and `deductible_applied_cents` at 0, `info_request_count` at 0,
        `payout_variant`, `decided_by_user_id`, `decided_at`, `denial_reason`, and
        `paid_at` all null, `submitted_by_user_id` set to the resolved homeowner's
        identifier, and `version` at 1."

        Design: Difficulty/cross_entity_state_dependency/terminated_policy_blocks_claim_submission
        """
        state = _superseded_and_superseding_policies(api)
        api.create_claim(
            _water_damage_body(state, state["superseded_policy_id"]),
            make_homeowner_headers(state["homeowner_id"]),
        )

        created = get_success_data(
            api.create_claim(
                _water_damage_body(state, state["superseding_policy_id"]),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            201,
        )
        assert_reimbursement_claim(created)
        assert created["status"] == "SUBMITTED"
        assert created["policy_id"] == state["superseding_policy_id"]
        assert created["submitted_by_user_id"] == state["homeowner_id"]
        assert created["payout_variant"] is None
        assert created["approved_payout_cents"] == 0
        assert created["deductible_applied_cents"] == 0
        assert created["info_request_count"] == 0

    def test_the_superseded_policy_stays_terminated_and_books_nothing(
        self, api: ApiClient
    ):
        """The two policies sit in the two states the refusal turns on.

        "Every prior policy on the same property that is not already `TERMINATED` is
        driven to `TERMINATED` with its own `version` incremented by 1, and the
        property's `version` is incremented by 1 as well — which is exactly what
        makes a second analyst's stale `expected_property_version` detectable."
        "The new row is created with `credit_state` `PENDING_ENROLLMENT`,
        `current_credit_tier_pct` at 0, `credited_cents_total`,
        `clawback_cents_total`, `true_up_cents`, and `paid_payout_cents_total` all
        at 0, `finalized_period_count` at 0, `avg_uptime_pct` and
        `last_attestation_end_at` and `suspended_reason` all null, and `version` at
        1."

        Design: Difficulty/cross_entity_state_dependency/terminated_policy_blocks_claim_submission
        """
        state = _superseded_and_superseding_policies(api)

        superseded = read_policy(api, state["superseded_policy_id"])
        assert_insurance_policy(superseded)
        assert superseded["credit_state"] == "TERMINATED"
        assert superseded["paid_payout_cents_total"] == 0
        assert superseded["credited_cents_total"] == 0

        superseding = read_policy(api, state["superseding_policy_id"])
        assert superseding["credit_state"] == "PENDING_ENROLLMENT"
        assert superseding["finalized_period_count"] == 0
