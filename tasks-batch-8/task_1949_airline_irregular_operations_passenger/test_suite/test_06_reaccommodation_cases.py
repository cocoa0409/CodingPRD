"""Reaccommodation case machine: branching with the escalate/regenerate loop,
empty selector fallback, commit guards, and case OCC."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    setup_disrupted_booking, setup_offered_case, setup_committed_case,
    get_case, get_option, get_booking, get_flight,
    offer_case, commit_option,
    cancel_flight_under_event,
    generate_options_payload, commit_payload,
)

AGENT = TEST_USERS["agent_headers"]


def _offered_ctx():
    """Event RECOVERY path: booking disrupted, case OFFERED with one option on
    the 14:00 recovery flight."""
    return setup_offered_case(
        event_code="MECH-CX", event_state="ASSESSING",
        flight_overrides={"flight_number": "OC8",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[{"flight_number": "OC9",
                        "sched_dep_utc": "2026-08-10T14:00:00Z",
                        "sched_arr_utc": "2026-08-10T15:00:00Z"}])


class TestCaseBranchingWithLoop:
    def test_escalate_from_queued_creates_no_options(self, api):
        """PRD §3.5: "A `ReaccommodationAgent` may escalate a case that is
        stuck, moving it from `QUEUED` or `OFFERED` to `ESCALATED` and
        incrementing its `version`; escalation from any other state is
        `ERR_CASE_NOT_COMMITTABLE`." Option creation happens only at
        generation: "Generation supersedes any prior `PROPOSED` options by
        moving them to `EXPIRED`, increments the case's `version`, moves the
        case to `OFFERED`, and queues a `REBOOK_OFFER` communication."

        Design: Difficulty/non_linear_state_machine/reaccommodation_case_branching_with_loop
        """
        ctx = setup_disrupted_booking(
            event_code="MECH-7",
            flight_overrides={"flight_number": "OC1000",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T11:00:00Z"},
            extra_flights=[{"flight_number": "OC1100",
                            "sched_dep_utc": "2026-08-10T15:00:00Z",
                            "sched_arr_utc": "2026-08-10T16:00:00Z"}])
        escalated = validate_success(api_client.escalate_case(ctx["case"]["id"], AGENT))
        assert escalated["case_status"] == "ESCALATED"
        options = validate_success(api_client.list_case_options(ctx["case"]["id"], AGENT))
        assert options == [], "escalation alone materializes no options"

    def test_escalated_case_regenerates_to_offered_then_commits(self, api):
        """PRD §3.5: "Escalated cases may regenerate options, returning to
        `OFFERED`." and "A successful commit moves the option to `ACCEPTED` and
        every sibling `PROPOSED` option to `REJECTED`, records the accepted
        option in `committed_option_id`, and increments the case's `version`."

        Design: Difficulty/non_linear_state_machine/reaccommodation_case_branching_with_loop
        """
        ctx = setup_disrupted_booking(
            event_code="MECH-7b",
            flight_overrides={"flight_number": "OC1000",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T11:00:00Z"},
            extra_flights=[{"flight_number": "OC1100",
                            "sched_dep_utc": "2026-08-10T15:00:00Z",
                            "sched_arr_utc": "2026-08-10T16:00:00Z"}])
        validate_success(api_client.escalate_case(ctx["case"]["id"], AGENT))
        offered = validate_success(api_client.generate_options(
            ctx["case"]["id"], generate_options_payload(False), AGENT))
        assert offered["case_status"] == "OFFERED", (
            "generate-options from ESCALATED loops back to OFFERED")
        options = validate_success(api_client.list_case_options(ctx["case"]["id"], AGENT))
        assert len(options) >= 1
        assert all(o["option_status"] == "PROPOSED" for o in options)

        committed = commit_option(ctx["case"]["id"], options[0]["id"], offered["version"])
        assert committed["case_status"] == "COMMITTED"
        assert committed["committed_option_id"] == options[0]["id"]


class TestEmptyOptionSetRejection:
    def _setup_no_candidates(self):
        # No recovery flights exist anywhere; the only flight is CANCELLED.
        return setup_disrupted_booking(event_code="MECH-14")

    def test_generate_options_with_empty_candidate_set_returns_422(self, api):
        """PRD §3.5: "If the selector finds no eligible candidate at all, the
        request fails with `ERR_NO_REACCOM_OPTIONS` (HTTP 422) and the case is
        left in the status it had — `QUEUED` or `ESCALATED`."

        Design: Difficulty/boundary_precision_check/empty_option_set_rejection
        """
        ctx = self._setup_no_candidates()
        res = api_client.generate_options(
            ctx["case"]["id"], generate_options_payload(False), AGENT)
        validate_error(res, ApiErrorId.ERR_NO_REACCOM_OPTIONS)

    def test_case_state_unchanged_after_empty_fallback(self, api):
        """PRD §3.5: "If the selector finds no eligible candidate at all, the
        request fails with `ERR_NO_REACCOM_OPTIONS` (HTTP 422) and the case is
        left in the status it had — `QUEUED` or `ESCALATED`."

        Design: Difficulty/boundary_precision_check/empty_option_set_rejection
        """
        ctx = self._setup_no_candidates()
        res = api_client.generate_options(
            ctx["case"]["id"], generate_options_payload(False), AGENT)
        validate_error(res, ApiErrorId.ERR_NO_REACCOM_OPTIONS)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["case_status"] == "QUEUED", (
            f"empty fallback must not transition the case, got {case_after['case_status']}")


class TestCommitRequiresCommittableTargetFlight:
    def _setup_target_cancelled(self):
        ctx = _offered_ctx()
        target = ctx["extra_flights"][0]
        option = ctx["options"][0]
        assert option["legs"][0]["flight_id"] == target["id"]
        # The target flight is itself cancelled under the same event.
        cancel_flight_under_event(target["id"], ctx["event"]["id"],
                                  expected_version=target["version"])
        return ctx, target, option

    def test_commit_against_cancelled_target_fails_and_expires_option(self, api):
        """PRD §3.5: "The named `option_id` must exist and be `PROPOSED`, and
        every leg's flight must still be in `SCHEDULED` or `DELAYED`; if a leg's
        flight has since left those states, the option is marked `EXPIRED` and
        the commit fails with `ERR_OPTION_NOT_PROPOSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/commit_requires_target_flight_committable
        """
        ctx, target, option = self._setup_target_cancelled()
        res = api_client.commit_case(
            ctx["case"]["id"], commit_payload(option["id"], ctx["case"]["version"]), AGENT)
        validate_error(res, ApiErrorId.ERR_OPTION_NOT_PROPOSED)
        option_after = get_option(option["id"])
        assert option_after["option_status"] == "EXPIRED", (
            "a leg flight leaving {SCHEDULED, DELAYED} marks the option EXPIRED")

    def test_failed_commit_leaves_case_offered_and_booking_disrupted(self, api):
        """PRD §3.5: "The case must be `OFFERED`, otherwise
        `ERR_CASE_NOT_COMMITTABLE`." — a rejected commit performs none of the
        success effects.
        PRD §3.5: "A successful commit moves the option to `ACCEPTED` and every
        sibling `PROPOSED` option to `REJECTED`, records the accepted option in
        `committed_option_id`, and increments the case's `version`. The booking
        moves from `DISRUPTED` to `REBOOKED`: its old `DISRUPTED` segments
        become `REBOOKED`, and new `CONFIRMED` segments are created from the
        option's legs with their `reaccommodation_case_id` pointing back at the
        case."

        Design: Difficulty/cross_entity_state_dependency/commit_requires_target_flight_committable
        """
        ctx, target, option = self._setup_target_cancelled()
        res = api_client.commit_case(
            ctx["case"]["id"], commit_payload(option["id"], ctx["case"]["version"]), AGENT)
        validate_error(res, ApiErrorId.ERR_OPTION_NOT_PROPOSED)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["case_status"] == "OFFERED"
        booking_after = get_booking(ctx["booking"]["id"])
        assert booking_after["booking_status"] == "DISRUPTED"


def test_escalate_of_committed_case_rejected(api):
    """PRD §3.5: "A `ReaccommodationAgent` may escalate a case that is stuck,
    moving it from `QUEUED` or `OFFERED` to `ESCALATED` and incrementing its
    `version`; escalation from any other state is `ERR_CASE_NOT_COMMITTABLE`."

    Design: Corner/state_machines/escalate_committed_case_rejected
    """
    ctx = setup_committed_case(
        event_code="MECH-C6",
        flight_overrides={"flight_number": "OC8",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[{"flight_number": "OC9",
                        "sched_dep_utc": "2026-08-10T14:00:00Z",
                        "sched_arr_utc": "2026-08-10T15:00:00Z"}])
    assert ctx["case"]["case_status"] == "COMMITTED"
    res = api_client.escalate_case(ctx["case"]["id"], AGENT)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_COMMITTABLE)
    assert get_case(ctx["case"]["id"])["case_status"] == "COMMITTED"


def test_booking_cancel_voids_open_case_and_expires_options(api):
    """PRD §3.4: "Cancellation moves every non-`FLOWN` segment to `CANCELLED`
    and releases those seats, decreasing each affected cabin's `seats_sold` by
    `party_size`; any open case becomes `VOIDED` and its `PROPOSED` options
    become `EXPIRED`."

    Design: Corner/state_machines/case_voided_on_booking_cancel_conditional_cascade
    """
    ctx = _offered_ctx()
    option = ctx["options"][0]
    validate_success(api_client.cancel_booking(ctx["booking"]["id"], AGENT))

    case_after = get_case(ctx["case"]["id"])
    assert case_after["case_status"] == "VOIDED"
    option_after = get_option(option["id"])
    assert option_after["option_status"] == "EXPIRED"
    booking_after = get_booking(ctx["booking"]["id"])
    assert booking_after["booking_status"] == "CANCELLED"


def test_commit_with_stale_case_version_rejected_412(api):
    """PRD §2.7: "Committing a reaccommodation option requires a non-optional
    `expected_case_version` carrying the `version` of the reaccommodation case
    the client last observed. In each case, if the supplied value does not equal
    the resource's current `version` — for example because options were
    regenerated on the case, or because a crew assignment changed the flight's
    coverage and bumped its version — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the resource and
    resubmit with the current version."
    PRD §3.5: "Generation supersedes any prior `PROPOSED` options by moving them
    to `EXPIRED`, increments the case's `version`, moves the case to `OFFERED`,
    and queues a `REBOOK_OFFER` communication."

    Design: Corner/cross_cutting_layers/occ_commit_stale_version_returns_412
    """
    ctx = _offered_ctx()
    stale_version = ctx["case"]["version"]
    stale_option = ctx["options"][0]

    # Regeneration is admitted only from QUEUED or ESCALATED (PRD §3.5), so the
    # client-visible version bump a stale holder misses is produced through the
    # pinned escalate -> regenerate loop: ESCALATED, then back to OFFERED with
    # the first option set superseded.
    validate_success(api_client.escalate_case(ctx["case"]["id"], AGENT))
    validate_success(api_client.generate_options(
        ctx["case"]["id"], generate_options_payload(False), AGENT))

    res = api_client.commit_case(
        ctx["case"]["id"], commit_payload(stale_option["id"], stale_version), AGENT)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    case_after = get_case(ctx["case"]["id"])
    assert case_after["case_status"] == "OFFERED", (
        "the 412 rejection must not transition the case")
    booking_after = get_booking(ctx["booking"]["id"])
    assert booking_after["booking_status"] == "DISRUPTED", (
        "no seat movement or rebooking occurred")
