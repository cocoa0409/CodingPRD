"""Requests that break two rules at once, where only one answer is correct.

An approval on a SUBMITTED claim that would also breach the annual payout cap must
report the state error.  A SNOOZE request from VACATION during a snooze cooldown
must report the forbidden transition.  In both, clearing the higher-priority rule
lets the lower-priority one finally surface.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    validate_error,
)
from test_helpers.fixtures import (
    approve_claim,
    begin_claim_review,
    file_claim,
    ingest_burst_reading,
    pay_claim,
    read_claim,
    read_device,
    read_events,
    read_policy,
    set_clock,
    set_monitor_mode,
    setup_armed_device,
    setup_armed_device_with_policy,
    snooze_device,
)
from test_helpers.test_users import (
    SECOND_ADJUSTER_USER_ID,
    make_claims_adjuster_headers,
    make_homeowner_headers,
)

CLAIM_POLICY_YEAR_START = "2026-08-01T00:00:00Z"
BURST_AT = "2026-08-01T07:00:00Z"


def _paid_water_damage_then_a_submitted_warranty_claim(api: ApiClient) -> dict:
    """500000 cents already paid, leaving only 100000 under the annual cap."""
    state = setup_armed_device_with_policy(api, CLAIM_POLICY_YEAR_START)
    set_clock(api, BURST_AT)
    ingest_burst_reading(api, state["device_id"], BURST_AT)
    events = read_events(api, state["device_id"], event_state="ALERTED")
    assert len(events) == 1

    first = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WATER_DAMAGE",
        620_000,
        state["homeowner_id"],
        anomaly_event_id=events[0]["id"],
    )
    begin_claim_review(api, first["id"])
    approve_claim(api, first["id"])
    state["paid_claim"] = pay_claim(api, first["id"])
    state["paid_claim_id"] = first["id"]

    second = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WARRANTY_DEVICE",
        150_000,
        state["homeowner_id"],
    )
    state["warranty_claim_id"] = second["id"]
    return state


class TestClaimStateBeatsPayoutCap:
    def test_approving_a_submitted_claim_reports_the_state_error_not_the_cap(
        self, api: ApiClient
    ):
        """Both rules are broken; the claim-state rule is the one that answers.

        "A verb submitted against a status it is not legal from is refused with
        `ERR_CLAIM_NOT_REVIEWABLE`, and every accepted decision increments the
        claim's `version` by 1."
        "When a single request violates several rules at once, the response must
        name the violation the server encountered first, and the ordering below is
        normative rather than advisory."
        "Approval requires that the policy's `paid_payout_cents_total` plus the
        newly computed payout not exceed an annual policy payout cap of 600000
        cents; exceeding it is refused with `ERR_ANNUAL_PAYOUT_CAP_EXCEEDED` rather
        than silently truncated."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_payout_cap
        """
        state = _paid_water_damage_then_a_submitted_warranty_claim(api)

        response = api.decide_claim(
            state["warranty_claim_id"],
            {"decision": "APPROVE"},
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE, 409)

        claim = read_claim(api, state["warranty_claim_id"])
        assert claim["status"] == "SUBMITTED"
        assert claim["payout_variant"] is None
        assert claim["approved_payout_cents"] == 0
        assert claim["decided_by_user_id"] is None

    def test_the_cap_error_only_surfaces_once_the_claim_is_under_review(
        self, api: ApiClient
    ):
        """Clearing the state rule lets the lower-priority cap rule answer.

        "Approval requires that the policy's `paid_payout_cents_total` plus the
        newly computed payout not exceed an annual policy payout cap of 600000
        cents; exceeding it is refused with `ERR_ANNUAL_PAYOUT_CAP_EXCEEDED` rather
        than silently truncated."
        "It re-checks the annual cap against `approved_payout_cents`, refuses when
        the paying `X-User-ID` equals the recorded `decided_by_user_id`, and on
        success stamps `paid_at` at the clock, moves the claim `APPROVED → PAID`,
        and increases the policy's `paid_payout_cents_total` by
        `approved_payout_cents` along with the policy's `version`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_payout_cap
        """
        state = _paid_water_damage_then_a_submitted_warranty_claim(api)

        reviewing = begin_claim_review(api, state["warranty_claim_id"], "adj-02")
        assert reviewing["status"] == "UNDER_REVIEW"

        response = api.decide_claim(
            state["warranty_claim_id"],
            {"decision": "APPROVE"},
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_ANNUAL_PAYOUT_CAP_EXCEEDED, 422)

        # The ceiling refuses the claim outright; it never truncates the payout to
        # the 100000 cents of headroom that remain.
        claim = read_claim(api, state["warranty_claim_id"])
        assert claim["status"] == "UNDER_REVIEW"
        assert claim["approved_payout_cents"] == 0

        policy = read_policy(api, state["policy_id"])
        assert policy["paid_payout_cents_total"] == 500_000
        paid = read_claim(api, state["paid_claim_id"])
        assert paid["status"] == "PAID"
        assert paid["approved_payout_cents"] == 500_000
        assert paid["paid_at"].startswith("2026-08-01T07:00:00")


SNOOZE_AT = "2026-08-01T07:00:00Z"
REVERT_AT = "2026-08-01T07:10:00Z"
VACATION_AT = "2026-08-01T07:20:00Z"
TRIGGER_AT = "2026-08-01T07:30:00Z"
VACATION_ENDS_AT = "2026-08-05T00:00:00Z"


def _snoozed_then_reverted_then_on_vacation(api: ApiClient) -> dict:
    """A cooldown running to 09:00Z on a device that is now in VACATION."""
    state = setup_armed_device(api)
    set_clock(api, SNOOZE_AT)
    snooze_device(api, state["device_id"], state["homeowner_id"], 60)
    set_clock(api, REVERT_AT)
    set_monitor_mode(api, state["device_id"], state["homeowner_id"], "NORMAL")
    set_clock(api, VACATION_AT)
    set_monitor_mode(
        api,
        state["device_id"],
        state["homeowner_id"],
        "VACATION",
        vacation_ends_at=VACATION_ENDS_AT,
    )
    set_clock(api, TRIGGER_AT)
    return state


class TestModeTransitionBeatsSnoozeCooldown:
    def test_snoozing_out_of_vacation_reports_the_forbidden_transition(
        self, api: ApiClient
    ):
        """The illegal edge answers first, even though the cooldown is also live.

        "Going directly from `VACATION` to `SNOOZE`, or directly from `SNOOZE` to
        `VACATION`, is not a transition; the device must pass through `NORMAL`
        first, and an attempt to shortcut is refused with
        `ERR_MODE_TRANSITION_FORBIDDEN`."
        "When a single request violates several rules at once, the response must
        name the violation the server encountered first, and the ordering below is
        normative rather than advisory."

        Design: Difficulty/priority_pair_validation_conflict/mode_transition_beats_snooze_cooldown
        """
        state = _snoozed_then_reverted_then_on_vacation(api)

        response = api.set_monitor_mode(
            state["device_id"],
            {"mode": "SNOOZE", "snooze_minutes": 60},
            make_homeowner_headers(state["homeowner_id"]),
        )
        validate_error(response, ApiErrorId.ERR_MODE_TRANSITION_FORBIDDEN, 409)

        device = read_device(api, state["device_id"])
        assert device["monitor_mode"] == "VACATION"
        assert device["vacation_ends_at"].startswith("2026-08-05T00:00:00")

    def test_the_cooldown_error_only_surfaces_from_a_legal_starting_mode(
        self, api: ApiClient
    ):
        """Reverting to NORMAL first exposes the buffered snooze cooldown.

        "Once a snooze window has ever existed on a device, a new snooze is admitted
        only when the clock has reached `snooze_window_end_at` plus a further hour;
        strictly before that instant the request is refused with
        `ERR_SNOOZE_COOLDOWN_ACTIVE`."
        "Crucially, reverting to `NORMAL` early does **not** clear the window
        bounds: `snooze_window_start_at` and `snooze_window_end_at` are retained
        after the mode reverts, whether the revert was manual or done by the sweep,
        precisely so that the cooldown still applies to somebody who tries to escape
        it by toggling back to `NORMAL`."

        Design: Difficulty/priority_pair_validation_conflict/mode_transition_beats_snooze_cooldown
        """
        state = _snoozed_then_reverted_then_on_vacation(api)

        reverted = set_monitor_mode(
            api, state["device_id"], state["homeowner_id"], "NORMAL"
        )
        assert reverted["monitor_mode"] == "NORMAL"
        assert reverted["vacation_started_at"] is None
        assert reverted["vacation_ends_at"] is None
        assert reverted["snooze_window_start_at"].startswith("2026-08-01T07:00:00")
        assert reverted["snooze_window_end_at"].startswith("2026-08-01T08:00:00")

        # 07:30Z is earlier than the 08:00Z window end plus the 60-minute buffer.
        response = api.set_monitor_mode(
            state["device_id"],
            {"mode": "SNOOZE", "snooze_minutes": 60},
            make_homeowner_headers(state["homeowner_id"]),
        )
        validate_error(response, ApiErrorId.ERR_SNOOZE_COOLDOWN_ACTIVE, 409)

        device = read_device(api, state["device_id"])
        assert device["monitor_mode"] == "NORMAL"
        # Stamped by the accepted revert, not by either rejected call.
        assert device["monitor_mode_updated_at"].startswith("2026-08-01T07:30:00")
