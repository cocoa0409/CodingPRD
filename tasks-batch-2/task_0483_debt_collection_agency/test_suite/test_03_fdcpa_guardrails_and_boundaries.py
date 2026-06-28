"""FDCPA guardrail precedence, numeric/temporal boundaries, and recurring/forward
time-interval semantics.

All tests translate difficulty-design (queue A) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    setup_working_account,
    setup_validation_sent_account,
    setup_working_account_with_n_phone_attempts,
    propose_arrangement,
    raise_dispute,
    log_phone_attempt,
    refresh_account,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# priority_pair_validation_conflict / cease_safety_beats_call_window_temporal
# ===========================================================================
class TestCeaseBeatsCallWindow:
    """A PHONE attempt that is both outside the call window AND on a CEASED account
    surfaces ERR_CEASE_COMMUNICATION (the cease check is evaluated first)."""

    def _setup_ceased_outside_window(self):
        # WORKING account, then cease-communication; clock advanced to 2026-01-02T05:00:00Z
        # which is local 05:00 (offset 0) -> outside the [08:00, 21:00) call window.
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        get_success_data(api_client.cease_communication(ctx["account"]["id"], COMPLIANCE))
        set_clock("2026-01-02T05:00:00Z")
        return ctx

    def test_cease_error_returned_not_call_window(self):
        """PRD §3.5: "First, if the account's `contact_status` is `CEASED`, the
        attempt is refused with `ERR_CEASE_COMMUNICATION` — once a consumer has
        invoked cease-communication, no further cadence-counting contact is
        permitted."

        Design: Difficulty/priority_pair_validation_conflict/cease_safety_beats_call_window_temporal
        """
        ctx = self._setup_ceased_outside_window()
        res = log_phone_attempt(ctx["account"]["id"], "2026-01-02T05:00:00Z", "LOGGED")
        err = validate_error(res, ApiErrorId.ERR_CEASE_COMMUNICATION.value)
        assert err["error_id"] == "ERR_CEASE_COMMUNICATION"

    def test_call_window_error_not_returned(self):
        """PRD §3.5: "Logging a cadence-counting attempt runs a gauntlet of FDCPA
        guardrails. First, if the account's `contact_status` is `CEASED`, the attempt
        is refused with `ERR_CEASE_COMMUNICATION` — once a consumer has invoked
        cease-communication, no further cadence-counting contact is permitted."

        Design: Difficulty/priority_pair_validation_conflict/cease_safety_beats_call_window_temporal
        """
        ctx = self._setup_ceased_outside_window()
        res = log_phone_attempt(ctx["account"]["id"], "2026-01-02T05:00:00Z", "LOGGED")
        err = validate_error(res, ApiErrorId.ERR_CEASE_COMMUNICATION.value)
        assert err["error_id"] != "ERR_OUTSIDE_CALL_WINDOW"


# ===========================================================================
# priority_pair_validation_conflict / time_barred_temporal_beats_settlement_floor_fiscal
# ===========================================================================
class TestTimeBarredBeatsFloor:
    """A SETTLEMENT accept that is both time-barred AND below floor surfaces
    ERR_TIME_BARRED (time-barred check is evaluated before the floor check)."""

    def _setup_time_barred_below_floor(self):
        # charge_off 2020-01-01, sol_years 4, CHARGE_OFF basis -> time_barred at 2026-01-01.
        # balance 100000 -> balance_floor 6000; age > 730 -> age_floor 3000; floor max = 6000.
        # offer 3000 is below floor AND account is time-barred.
        ctx = setup_working_account(
            clock="2026-01-01T00:00:00Z",
            account_overrides={
                "original_principal_cents": 100000,
                "charge_off_date": "2020-01-01T00:00:00Z",
                "sol_years": 4,
                "sol_anchor_basis": "CHARGE_OFF",
            },
        )
        arr = propose_arrangement(ctx["account"]["id"], "SETTLEMENT", offer_pct_bps=3000)
        ctx["arrangement"] = arr
        return ctx

    def test_account_is_time_barred(self):
        """PRD §3.2: "The account is time-barred — that is, `time_barred` is true —
        exactly when the clock is at or after that expiry instant; an instant
        precisely equal to expiry counts as barred."

        Design: Difficulty/priority_pair_validation_conflict/time_barred_temporal_beats_settlement_floor_fiscal
        """
        ctx = self._setup_time_barred_below_floor()
        acct = refresh_account(ctx)
        assert acct["time_barred"] is True

    def test_time_barred_error_returned_not_below_floor(self):
        """PRD §3.6: "For a `SETTLEMENT`, the account must not be time-barred — that
        is, accepting a settlement on an account whose `time_barred` is true is
        rejected with `ERR_TIME_BARRED`; a `PLAN` is not subject to this restriction."

        Design: Difficulty/priority_pair_validation_conflict/time_barred_temporal_beats_settlement_floor_fiscal
        """
        ctx = self._setup_time_barred_below_floor()
        res = api_client.accept_arrangement(ctx["arrangement"]["id"], COLLECTOR)
        err = validate_error(res, ApiErrorId.ERR_TIME_BARRED.value)
        assert err["error_id"] != "ERR_SETTLEMENT_BELOW_FLOOR"


# ===========================================================================
# boundary_precision_check / cadence_seventh_allowed_eighth_rejected
# ===========================================================================
class TestCadenceBoundary:
    """The 7th cadence-counting attempt in the trailing window is allowed; the 8th
    is rejected with ERR_CADENCE_EXCEEDED."""

    SEVEN_ATTEMPTS = [
        "2026-03-01T08:00:00Z",
        "2026-03-01T09:00:00Z",
        "2026-03-01T10:00:00Z",
        "2026-03-01T11:00:00Z",
        "2026-03-01T12:00:00Z",
        "2026-03-01T13:00:00Z",
        "2026-03-01T14:00:00Z",
    ]

    def test_seventh_attempt_allowed_count_seven(self):
        """PRD §3.5: "Logging a new cadence-counting attempt that would push
        `attempts_in_window_count` above seven within that trailing window is
        rejected with `ERR_CADENCE_EXCEEDED`: the seventh counting attempt in the
        window is allowed, and the eighth is refused."

        Design: Difficulty/boundary_precision_check/cadence_seventh_allowed_eighth_rejected
        """
        ctx = setup_working_account_with_n_phone_attempts(
            attempts_at=self.SEVEN_ATTEMPTS, clock="2026-03-01T15:00:00Z"
        )
        assert ctx["account"]["attempts_in_window_count"] == 7

    def test_eighth_attempt_rejected_cadence_exceeded(self):
        """PRD §3.5: "Logging a new cadence-counting attempt that would push
        `attempts_in_window_count` above seven within that trailing window is
        rejected with `ERR_CADENCE_EXCEEDED`: the seventh counting attempt in the
        window is allowed, and the eighth is refused."

        Design: Difficulty/boundary_precision_check/cadence_seventh_allowed_eighth_rejected
        """
        ctx = setup_working_account_with_n_phone_attempts(
            attempts_at=self.SEVEN_ATTEMPTS, clock="2026-03-01T15:00:00Z"
        )
        res = log_phone_attempt(ctx["account"]["id"], "2026-03-01T14:30:00Z", "LOGGED")
        validate_error(res, ApiErrorId.ERR_CADENCE_EXCEEDED.value)
        acct = refresh_account(ctx)
        assert acct["attempts_in_window_count"] == 7, "8th attempt must not be recorded"


# ===========================================================================
# boundary_precision_check / validation_dispute_window_day30_inclusive_day31_excluded
# ===========================================================================
class TestValidationWindowBoundary:
    """A VALIDATION dispute raised at exactly the deadline instant is out of the
    window (deadline is exclusive) and does not hold contact."""

    def test_dispute_at_deadline_instant_not_in_window(self):
        """PRD §3.4: "The dispute is stamped with `raised_at` at the current clock and
        its `within_validation_window` is computed as true when `raised_at` falls
        strictly before the account's `validation_deadline`."

        Design: Difficulty/boundary_precision_check/validation_dispute_window_day30_inclusive_day31_excluded
        """
        # notice sent at 2026-01-01 -> deadline 2026-01-31; raise at exactly 2026-01-31.
        ctx = setup_validation_sent_account(clock="2026-01-01T00:00:00Z")
        set_clock("2026-01-31T00:00:00Z")
        disp = raise_dispute(ctx["account"]["id"], "VALIDATION")
        assert disp["within_validation_window"] is False

    def test_dispute_at_deadline_does_not_hold_contact(self):
        """PRD §3.4: "When a `VALIDATION` dispute is raised inside the validation
        window — that is, when `within_validation_window` is true — it pushes the
        account's `contact_status` to `VALIDATION_HELD`, pausing collection
        communication on the account until the dispute resolves in the agency's
        favor."

        Design: Difficulty/boundary_precision_check/validation_dispute_window_day30_inclusive_day31_excluded
        """
        ctx = setup_validation_sent_account(clock="2026-01-01T00:00:00Z")
        set_clock("2026-01-31T00:00:00Z")
        raise_dispute(ctx["account"]["id"], "VALIDATION")
        acct = refresh_account(ctx)
        assert acct["contact_status"] == "CONTACTABLE"


# ===========================================================================
# cross_entity_state_dependency / attempt_blocked_by_account_cease_status
# ===========================================================================
class TestAttemptBlockedByCease:
    """Whether an attempt may be logged depends on the parent account's contact_status."""

    def test_attempt_on_ceased_account_rejected(self):
        """PRD §3.5: "Once `CEASED`, every subsequent cadence-counting attempt is
        refused with `ERR_CEASE_COMMUNICATION`, and beginning work on the account is
        likewise blocked with the same error."

        Design: Difficulty/cross_entity_state_dependency/attempt_blocked_by_account_cease_status
        """
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        get_success_data(api_client.cease_communication(ctx["account"]["id"], COMPLIANCE))
        set_clock("2026-01-02T15:00:00Z")
        res = log_phone_attempt(ctx["account"]["id"], "2026-01-02T15:00:00Z", "LOGGED")
        validate_error(res, ApiErrorId.ERR_CEASE_COMMUNICATION.value)

    def test_attempt_allowed_when_contactable(self):
        """PRD §3.5: "First, if the account's `contact_status` is `CEASED`, the
        attempt is refused with `ERR_CEASE_COMMUNICATION` — once a consumer has
        invoked cease-communication, no further cadence-counting contact is
        permitted."

        Design: Difficulty/cross_entity_state_dependency/attempt_blocked_by_account_cease_status
        """
        # Same shape but account NOT ceased -> attempt succeeds (proves the dependency).
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        set_clock("2026-01-02T15:00:00Z")
        res = log_phone_attempt(ctx["account"]["id"], "2026-01-02T15:00:00Z", "LOGGED")
        validate_success(res, 201)


# ===========================================================================
# cross_entity_state_dependency / furnish_blocked_by_open_dispute_on_account
# ===========================================================================
class TestFurnishBlockedByOpenDispute:
    """Whether a furnishing may be created depends on the account having no
    unresolved dispute."""

    def test_furnish_blocked_when_open_accuracy_dispute(self):
        """PRD §3.11: "Furnishing is guarded: a tradeline may not be furnished for an
        account whose `work_status` is `RECALLED` or `CLOSED_UNCOLLECTIBLE`, nor for
        an account that has an unresolved `ACCURACY` or `VALIDATION` dispute, and
        such an attempt is rejected with `ERR_FURNISH_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/furnish_blocked_by_open_dispute_on_account
        """
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        disp = raise_dispute(ctx["account"]["id"], "ACCURACY")
        assert disp["status"] == "OPEN"
        res = api_client.create_bureau_furnishing(
            {"account_id": ctx["account"]["id"], "bureau": "EQUIFAX"}, COMPLIANCE
        )
        validate_error(res, ApiErrorId.ERR_FURNISH_BLOCKED.value)

    def test_furnish_allowed_without_open_dispute(self):
        """PRD §3.11: "Furnishing captures the account's `balance_cents` at that
        moment into the furnishing's `furnished_balance_cents` and sets the
        furnishing's `status` to `REPORTED`."

        Design: Difficulty/cross_entity_state_dependency/furnish_blocked_by_open_dispute_on_account
        """
        # Same shape but no open dispute -> furnishing succeeds (proves the dependency).
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        res = api_client.create_bureau_furnishing(
            {"account_id": ctx["account"]["id"], "bureau": "EQUIFAX"}, COMPLIANCE
        )
        furn = validate_success(res, 201)
        assert furn["status"] == "REPORTED"


# ===========================================================================
# resource_temporal_overlap / call_window_closed_open_daily_interval
# ===========================================================================
class TestCallWindowInterval:
    """The call window is [08:00, 21:00) in consumer local time: local 21:00 (open
    end) is rejected."""

    def test_local_2100_open_end_rejected(self):
        """PRD §3.5: "For a `PHONE` attempt, the system converts `attempted_at` into
        the consumer's local time by applying the consumer's
        `timezone_offset_minutes`, and requires that local time to fall at or after
        08:00:00 and strictly before 21:00:00; an attempt whose local time is earlier
        than 8 a.m. or at or after 9 p.m. is rejected with `ERR_OUTSIDE_CALL_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/call_window_closed_open_daily_interval
        """
        # consumer offset -300 (UTC-5); clock 2026-03-01T02:00:00Z = local 21:00:00.
        ctx = setup_working_account(
            clock="2026-03-01T02:00:00Z",
            consumer_overrides={"timezone_offset_minutes": -300},
        )
        res = log_phone_attempt(ctx["account"]["id"], "2026-03-01T02:00:00Z", "LOGGED")
        validate_error(res, ApiErrorId.ERR_OUTSIDE_CALL_WINDOW.value)

    def test_local_0800_closed_start_allowed(self):
        """PRD §3.5: "For a `PHONE` attempt, the system converts `attempted_at` into
        the consumer's local time by applying the consumer's
        `timezone_offset_minutes`, and requires that local time to fall at or after
        08:00:00 and strictly before 21:00:00; an attempt whose local time is earlier
        than 8 a.m. or at or after 9 p.m. is rejected with `ERR_OUTSIDE_CALL_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/call_window_closed_open_daily_interval
        """
        # consumer offset -300 (UTC-5); clock 2026-03-01T13:00:00Z = local 08:00:00
        # (closed start of the window -> allowed).
        ctx = setup_working_account(
            clock="2026-03-01T13:00:00Z",
            consumer_overrides={"timezone_offset_minutes": -300},
        )
        res = log_phone_attempt(ctx["account"]["id"], "2026-03-01T13:00:00Z", "LOGGED")
        validate_success(res, 201)


# ===========================================================================
# resource_temporal_overlap / post_conversation_cooldown_forward_7day_buffer
# ===========================================================================
class TestPostConversationCooldown:
    """A forward [last_conversation_at, +7d) buffer: an attempt at +7d-minus-1s is
    rejected."""

    def _setup_after_conversation(self):
        # CONVERSATION logged at 2026-02-01T12:00:00Z -> last_conversation_at set;
        # cooldown to 2026-02-08T12:00:00Z. Clock at 2026-02-08T11:59:59Z (in cooldown).
        ctx = setup_working_account(clock="2026-02-01T12:00:00Z")
        get_success_data(
            log_phone_attempt(ctx["account"]["id"], "2026-02-01T12:00:00Z", "CONVERSATION")
        )
        set_clock("2026-02-08T11:59:59Z")
        refresh_account(ctx)
        return ctx

    def test_last_conversation_at_recorded(self):
        """PRD §3.5: "When an attempt is successfully logged, the account's
        `attempts_in_window_count` is recomputed, and if the new attempt's outcome is
        `CONVERSATION`, the account's `last_conversation_at` is set to that attempt's
        `attempted_at`."

        Design: Difficulty/resource_temporal_overlap/post_conversation_cooldown_forward_7day_buffer
        """
        ctx = self._setup_after_conversation()
        assert ctx["account"]["last_conversation_at"] is not None
        assert ctx["account"]["last_conversation_at"].startswith("2026-02-01T12:00:00")

    def test_attempt_inside_cooldown_rejected(self):
        """PRD §3.5: "There is also a post-conversation cooldown: once the account has
        a `last_conversation_at` — the `attempted_at` of its most recent
        `CONVERSATION`-outcome attempt — any cadence-counting attempt whose
        `attempted_at` falls at or after `last_conversation_at` and strictly before
        `last_conversation_at` plus 7 days is rejected with
        `ERR_POST_CONVERSATION_COOLDOWN`."

        Design: Difficulty/resource_temporal_overlap/post_conversation_cooldown_forward_7day_buffer
        """
        ctx = self._setup_after_conversation()
        res = log_phone_attempt(ctx["account"]["id"], "2026-02-08T11:59:59Z", "LOGGED")
        validate_error(res, ApiErrorId.ERR_POST_CONVERSATION_COOLDOWN.value)
