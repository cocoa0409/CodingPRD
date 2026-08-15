"""Line item lifecycle: launch guards, completion boundaries, fraud hold,
and OCC-guarded mid-flight edits."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_io, create_line_item, create_creative, transition_io,
    transition_line_item, walk_creative_to_tagged, add_tagged_creative,
    setup_trafficked_line_item, setup_live_line_item,
    post_snapshot, set_clock, get_line_item, get_creative,
    setup_breach_report,
)


class TestLaunchGuards:
    def test_launch_from_draft_rejected(self, api, trafficker_headers):
        """PRD §3.2: "Launching (`TRAFFICKED` → `LIVE`) enforces four guards,
        evaluated after the general state check"
        PRD §2.8: "Sixth, state validity: the target resource must be in a
        valid from-state for the requested action, with terminal states
        locked against any further transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/launch_from_draft_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        io = create_io()
        li = create_line_item(io["id"], goal_impressions=1000)
        transition_io(io["id"], "APPROVE")
        res = api.transition_line_item(li["id"], {"action": "LAUNCH"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert get_line_item(li["id"])["status"] == "DRAFT"

    def test_traffic_without_tagged_creative_rejected(
            self, api, trafficker_headers):
        """PRD §3.2: "Trafficking moves the line item from `DRAFT` to
        `TRAFFICKED` and requires at least one of its creatives to be in
        `TAGGED` status, failing with `ERR_NO_TAGGED_CREATIVE` otherwise."

        Design: Corner/state_machines/traffic_without_tagged_creative_rejected
        """
        io = create_io()
        li = create_line_item(io["id"], goal_impressions=1000)
        transition_io(io["id"], "APPROVE")
        create_creative(li["id"])  # stays UPLOADED — never tagged
        res = api.transition_line_item(li["id"], {"action": "TRAFFIC"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_NO_TAGGED_CREATIVE.value, 409)
        assert get_line_item(li["id"])["status"] == "DRAFT"

    def test_launch_before_start_date_rejected(self, api, trafficker_headers):
        """PRD §3.2: "the logical current date must fall on or after
        `start_date` and on or before `end_date`, with a launch before the
        start or after the end rejected as `ERR_FLIGHT_NOT_STARTED`"

        Design: Corner/validations/launch_before_start_date_rejected
        """
        ctx = setup_trafficked_line_item(
            clock="2026-08-01T00:00:00Z",
            li_overrides={"start_date": "2026-08-05",
                          "end_date": "2026-08-31"})
        res = api.transition_line_item(ctx["line_item"]["id"],
                                       {"action": "LAUNCH"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_STARTED.value, 422)
        assert get_line_item(ctx["line_item"]["id"])["status"] == "TRAFFICKED"

    def test_launch_requires_io_approved_rejected_while_draft(
            self, api, trafficker_headers):
        """PRD §3.2: "the parent order must be `APPROVED` or `ACTIVE`
        (`ERR_IO_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/line_item_launch_requires_io_approved
        """
        set_clock("2026-08-01T00:00:00Z")
        io = create_io()
        li = create_line_item(io["id"])
        cr = create_creative(li["id"])
        walk_creative_to_tagged(cr["id"])
        transition_line_item(li["id"], "TRAFFIC")

        res = api.transition_line_item(li["id"], {"action": "LAUNCH"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_IO_NOT_APPROVED.value, 409)
        assert get_line_item(li["id"])["status"] == "TRAFFICKED"
        assert get_creative(cr["id"])["status"] == "TAGGED", (
            "A rejected launch must not flip TAGGED creatives to LIVE")

    def test_launch_succeeds_once_io_approved(self, api, trafficker_headers):
        """PRD §3.2: "the parent order must be `APPROVED` or `ACTIVE`
        (`ERR_IO_NOT_APPROVED`)"
        PRD §3.2: "A successful launch flips every `TAGGED` creative of the
        line item to `LIVE`."

        Design: Difficulty/cross_entity_state_dependency/line_item_launch_requires_io_approved
        """
        set_clock("2026-08-01T00:00:00Z")
        io = create_io()
        li = create_line_item(io["id"])
        cr = create_creative(li["id"])
        walk_creative_to_tagged(cr["id"])
        transition_line_item(li["id"], "TRAFFIC")
        transition_io(io["id"], "APPROVE")

        launched = validate_success(
            api.transition_line_item(li["id"], {"action": "LAUNCH"},
                                     trafficker_headers), 200)
        assert launched["status"] == "LIVE"
        assert get_creative(cr["id"])["status"] == "LIVE"


class TestCompletion:
    def test_complete_at_flight_end_boundary(self, api, trafficker_headers):
        """PRD §3.2: "A `Trafficker` completes manually — from `LIVE` or
        `PAUSED` — only when the logical current date is strictly after
        `end_date`"

        Design: Corner/state_machines/complete_at_flight_end_boundary
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10"},
            li_overrides={"start_date": "2026-08-01",
                          "end_date": "2026-08-10"},
            activate_io=True)
        set_clock("2026-08-10T12:00:00Z")
        res = api.transition_line_item(ctx["line_item"]["id"],
                                       {"action": "COMPLETE"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

        set_clock("2026-08-11T00:00:00Z")
        completed = validate_success(
            api.transition_line_item(ctx["line_item"]["id"],
                                     {"action": "COMPLETE"},
                                     trafficker_headers), 200)
        assert completed["status"] == "COMPLETED"

    def test_line_item_auto_completes_at_goal(self, api, trafficker_headers):
        """PRD §3.2: "the system completes a `LIVE` line item automatically
        the moment a posted delivery snapshot lifts `delivered_impressions`
        to meet or exceed `goal_impressions` (§3.4). In both cases every
        creative in `LIVE` or `PAUSED` transitions to `ARCHIVED`."

        Design: Corner/state_machines/line_item_auto_completes_at_goal
        """
        ctx = setup_live_line_item(li_overrides={"goal_impressions": 100000,
                                                 "cpm_rate_cents": 500})
        li_id = ctx["line_item"]["id"]
        post_snapshot(li_id, "2026-08-02", 60000, 300)
        assert get_line_item(li_id)["status"] == "LIVE"

        post_snapshot(li_id, "2026-08-03", 40000, 200)

        li_after = get_line_item(li_id)
        assert li_after["delivered_impressions"] == 100000
        assert li_after["status"] == "COMPLETED"
        assert get_creative(ctx["creative"]["id"])["status"] == "ARCHIVED"


class TestMidFlightEditStateGuard:
    def test_patch_on_cancelled_beats_budget_violation(
            self, api, trafficker_headers):
        """PRD §3.2: "in any other status the edit is refused with
        `ERR_INVALID_STATE`."
        PRD §2.8: "Every request is evaluated against a fixed pipeline, and a
        request that would trip several checks is rejected with the error
        belonging to the earliest one."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_patch
        """
        io = create_io(total_budget_cents=100000)
        li = create_line_item(io["id"], goal_impressions=100000,
                              cpm_rate_cents=500)
        transition_io(io["id"], "APPROVE")
        transition_line_item(li["id"], "CANCEL")
        current_version = get_line_item(li["id"])["version"]

        res = api.patch_line_item(
            li["id"],
            {"expected_line_item_version": current_version,
             "goal_impressions": 1000000},
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert get_line_item(li["id"])["goal_impressions"] == 100000, (
            "A rejected edit must leave goal_impressions unchanged")

    def test_patch_on_cancelled_rejected_even_without_fiscal_violation(
            self, api, trafficker_headers):
        """PRD §3.2: "While the line item is `LIVE` or `PAUSED`, a
        `Trafficker` may adjust `goal_impressions`, `cpm_rate_cents`,
        `pacing_mode`, `start_date`, `end_date`,
        `frequency_cap_max_impressions`, or `frequency_cap_window_hours`
        through the OCC-guarded mid-flight edit described in §2.7; in any
        other status the edit is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_patch
        """
        io = create_io(total_budget_cents=100000)
        li = create_line_item(io["id"], goal_impressions=100000,
                              cpm_rate_cents=500)
        transition_io(io["id"], "APPROVE")
        transition_line_item(li["id"], "CANCEL")
        current_version = get_line_item(li["id"])["version"]

        res = api.patch_line_item(
            li["id"],
            {"expected_line_item_version": current_version,
             "goal_impressions": 1000},
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestFraudHold:
    def test_resume_blocked_by_fraud_hold_until_cleared(
            self, api, trafficker_headers):
        """PRD §3.5: "While the breach stands, launch, resume, and creative
        activation are refused with `ERR_FRAUD_HOLD` until a `Trafficker`
        clears the hold through the self-transition of §3.2."
        PRD §3.2: "the fraud-clearing action is a self-transition available
        only from `LIVE` or `PAUSED` and only while `fraud_posture` is
        `BREACH`: it resets `fraud_posture` to `CLEAR`, leaves the status
        untouched, and still increments `version` by one."

        Design: Corner/state_machines/resume_blocked_by_fraud_hold_until_cleared
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        cr_id = ctx["creative"]["id"]
        setup_breach_report(li_id, vendor="MOAT", viewable=80000, ivt=5000)
        assert get_line_item(li_id)["status"] == "PAUSED"

        res = api.transition_line_item(li_id, {"action": "RESUME"},
                                       trafficker_headers)
        validate_error(res, ApiErrorId.ERR_FRAUD_HOLD.value, 409)

        cleared = validate_success(
            api.transition_line_item(li_id, {"action": "CLEAR_FRAUD"},
                                     trafficker_headers), 200)
        assert cleared["fraud_posture"] == "CLEAR"
        assert cleared["status"] == "PAUSED", (
            "CLEAR_FRAUD is a self-transition: status must be untouched")

        resumed = validate_success(
            api.transition_line_item(li_id, {"action": "RESUME"},
                                     trafficker_headers), 200)
        assert resumed["status"] == "LIVE"
        assert get_creative(cr_id)["status"] == "LIVE"
