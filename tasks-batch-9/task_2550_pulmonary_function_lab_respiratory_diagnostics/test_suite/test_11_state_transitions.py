"""Where each workflow starts, what moves it and what it refuses once it lands.

An order is born a draft, a study wakes on its first blow, a report may only be
reopened after it has been signed, and the two terminal order states admit
nothing at all.  The same requests that are refused before the trigger succeed
after it, and the cascades that follow a transition are conditional on the state
each affected row happens to be in.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ORDER_STATE_INVALID,
    ERR_REPORT_STATE_INVALID,
    ERR_SESSION_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_device_quarantined,
    assert_instant,
    assert_listing_ids,
    assert_page,
    assert_signed_interpretation,
    assert_version_advanced_by,
    assert_version_is,
)
from test_helpers.constants import MORNING_CLOCK
from test_helpers.test_users import LAB_MANAGER


class TestOrderInitialState:
    """An order starts as a draft and is discoverable as one."""

    def test_a_new_order_is_a_draft_with_no_derived_workflow_state(self, api):
        """Nothing downstream of submission has been decided yet.

        PRD 3.4: "The server records `ordering_staff_id` from the acting
        physician's `X-User-ID` header, sets `status` to `DRAFT`, `abort_count`
        to 0, and leaves `rejection_reason`, `hold_release_at` and
        `cancellation_reason` null."

        Design: Corner/state_machines/test_order_is_born_in_draft_with_no_derived_workflow_state
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        patient = fx.register_patient(api)

        order = fx.draft_order(api, patient["id"], roster.doc1)

        assert order["status"] == "DRAFT"
        assert_version_is(order, 1)
        assert order["rejection_reason"] is None
        assert order["hold_release_at"] is None

        drafts, draft_meta = validate_paginated(
            api.list_test_orders(LAB_MANAGER, status="DRAFT")
        )
        assert_page(draft_meta, total_count=1, has_more=False)
        assert_listing_ids(drafts, [order["id"]])

        _, ready_meta = validate_paginated(
            api.list_test_orders(LAB_MANAGER, status="READY")
        )
        assert_page(ready_meta, total_count=0, has_more=False)

    def test_submitting_an_already_ready_order_a_second_time_is_refused(self, api):
        """Submission is not idempotent and the refusal moves no version.

        PRD 3.4: "An order sitting in `INDICATION_REJECTED` is revised through
        the same update operation the draft used, and applying a revision
        returns it to `DRAFT` and clears `rejection_reason` to null. That closes
        the revision cycle `DRAFT` → `INDICATION_REJECTED` → `DRAFT` →
        `SUBMITTED`, which may be traversed as many times as the physician
        needs."

        Design: Corner/state_machines/submitting_an_already_ready_order_a_second_time_is_rejected
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        patient = fx.register_patient(api)
        ready = fx.draft_and_submit_order(api, patient["id"], roster.doc1)
        assert ready["status"] == "READY"
        assert_version_is(ready, 2)

        validate_error(
            api.submit_test_order(ready["id"], roster.doc1, {}),
            ERR_ORDER_STATE_INVALID,
        )

        unchanged = validate_success(api.get_test_order(ready["id"], LAB_MANAGER))
        assert unchanged["status"] == "READY"
        assert_version_is(unchanged, 2)

    def test_cancelling_a_completed_order_is_refused_from_its_terminal_state(self, api):
        """The signature's consequences are not reversible by a late cancellation.

        PRD 3.4: "Cancellation is available from any non-terminal order state —
        `DRAFT`, `SUBMITTED`, `INDICATION_REJECTED`, `MED_HOLD_ISSUED`, `READY`
        or `IN_TESTING` — and records the supplied `cancellation_reason`. From
        `COMPLETED` or `CANCELLED` the call is refused with
        `ERR_ORDER_STATE_INVALID`."

        Design: Corner/state_machines/cancelling_a_completed_order_is_rejected_from_the_terminal_state
        """
        lab = fx.build_lab(api, clock="2026-08-03T10:00:00Z", interpreters=1)
        report = fx.build_assigned_report(
            api,
            lab,
            scheduled_start_at="2026-08-03T11:00:00Z",
            scheduled_end_at="2026-08-03T11:30:00Z",
        )
        signed = fx.sign_report(api, report["id"], lab.roster.rad1)
        session = validate_success(
            api.get_test_session(signed["session_id"], LAB_MANAGER)
        )
        order = validate_success(api.get_test_order(session["order_id"], LAB_MANAGER))
        assert order["status"] == "COMPLETED"

        validate_error(
            api.cancel_test_order(order["id"], f.cancel_order_payload(), lab.doc1),
            ERR_ORDER_STATE_INVALID,
        )

        after = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert after["status"] == "COMPLETED"
        assert after["cancellation_reason"] is None
        assert after["abort_count"] == 0
        assert session["session_status"] == "REPORTED"
        assert signed["status"] == "SIGNED"
        patient = validate_success(api.get_patient(lab.patient_id, LAB_MANAGER))
        assert patient["completed_order_count"] == 1


class TestStudyExecutionState:
    """The first blow wakes the study and finalization closes it."""

    def test_the_first_blow_moves_the_study_into_progress_and_rolls_it_up(self, api):
        """One append carries the state, the best values and every percentage.

        PRD 3.6: "The first maneuver moves the study from `SCHEDULED` to
        `IN_PROGRESS`; later maneuvers leave it there." and "`fev1_pct_predicted`
        is `best_fev1_l` divided by `predicted_fev1_l` times 100 to one decimal
        place, `fvc_pct_predicted` is `best_fvc_l` divided by `predicted_fvc_l`
        times 100 to one decimal place, and `fev1_fvc_ratio` is `best_fev1_l`
        divided by `best_fvc_l` to three decimal places."

        Design: Corner/state_machines/first_maneuver_advances_the_session_from_scheduled_to_in_progress
        """
        lab = fx.build_lab(api)
        scheduled = fx.build_scheduled_session(api, lab)
        assert scheduled["session_status"] == "SCHEDULED"

        fx.append_maneuver(api, scheduled["id"], f.maneuver_payload(3.200, 2.400), lab.tech1)
        after_first = validate_success(
            api.get_test_session(scheduled["id"], LAB_MANAGER)
        )

        assert after_first["session_status"] == "IN_PROGRESS"
        assert_3dp(after_first["best_fev1_l"], 2.400)
        assert_3dp(after_first["best_fvc_l"], 3.200)
        assert after_first["acceptable_maneuver_count"] == 1
        assert_1dp(after_first["fev1_pct_predicted"], 60.0)
        assert_1dp(after_first["fvc_pct_predicted"], 66.7)
        assert_3dp(after_first["fev1_fvc_ratio"], 0.750)
        assert_version_advanced_by(scheduled, after_first, 1)

        fx.append_maneuver(
            api,
            scheduled["id"],
            f.maneuver_payload(3.150, 2.250, pef_l_s=5.80,
                               back_extrapolated_volume_ml=120,
                               expiratory_time_s=16.0),
            lab.tech1,
        )
        after_second = validate_success(
            api.get_test_session(scheduled["id"], LAB_MANAGER)
        )
        assert after_second["session_status"] == "IN_PROGRESS"
        assert after_second["acceptable_maneuver_count"] == 2
        assert after_second["repeatability_delta_ml"] == 150

        order = validate_success(
            api.get_test_order(after_second["order_id"], LAB_MANAGER)
        )
        assert order["status"] == "IN_TESTING"

    def test_finalizing_before_any_blow_is_refused_and_then_succeeds(self, api):
        """The identical call is a state conflict, then an acceptance.

        PRD 3.6: "Finalization requires `session_status` to be `IN_PROGRESS`, and
        it additionally requires that no challenge run on the study is still
        `ARMED` or `IN_PROGRESS`; attempting to close a study over a live
        provocation is a session-state conflict reported as
        `ERR_SESSION_STATE_INVALID`."

        Design: Corner/state_machines/finalize_quality_before_any_maneuver_is_rejected_then_succeeds_from_in_progress
        """
        lab = fx.build_lab(api)
        scheduled = fx.build_scheduled_session(api, lab)

        validate_error(
            api.finalize_session_quality(
                scheduled["id"], f.finalize_quality_payload(), lab.tech1
            ),
            ERR_SESSION_STATE_INVALID,
        )

        still_scheduled = validate_success(
            api.get_test_session(scheduled["id"], LAB_MANAGER)
        )
        assert still_scheduled["session_status"] == "SCHEDULED"
        assert still_scheduled["quality_grade"] == "F"
        assert still_scheduled["acceptable_maneuver_count"] == 0

        fx.append_maneuver_series(api, scheduled["id"], lab.tech1)
        accepted = fx.finalize_quality(api, scheduled["id"], lab.tech1)

        assert accepted["session_status"] == "ACCEPTED"
        assert accepted["quality_grade"] == "A"
        assert accepted["rejection_round"] == 0

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert device["status"] == "SOILED"
        assert_instant(device["last_session_end_at"], "2026-08-03T09:30:00Z")


class TestReportAmendmentState:
    """Amendment reopens a signature and refuses to precede one."""

    def test_amending_an_assigned_report_is_refused_until_it_is_signed(self, api):
        """The premature amendment leaves the amendment counter at zero.

        PRD 3.9: "A signed report may be amended by the same physician, supplying
        an `amendment_reason`. Amendment raises `amendment_count` by one, moves
        `status` to `AMENDED`, and raises that interpreter's `open_report_count`
        by one again because `AMENDED` is an open status — which means an
        amendment also raises the laboratory-wide queue load that future
        assignments will measure."

        Design: Corner/state_machines/amending_an_assigned_report_is_rejected_until_it_has_been_signed
        """
        lab = fx.build_lab(api, clock="2026-08-03T10:00:00Z", interpreters=1)
        report = fx.build_assigned_report(
            api,
            lab,
            scheduled_start_at="2026-08-03T11:00:00Z",
            scheduled_end_at="2026-08-03T11:30:00Z",
        )

        validate_error(
            api.amend_interpretation_report(
                report["id"],
                f.amend_report_payload("Corrected the clinical comment."),
                lab.roster.rad1,
            ),
            ERR_REPORT_STATE_INVALID,
        )

        unchanged = validate_success(
            api.get_interpretation_report(report["id"], LAB_MANAGER)
        )
        assert unchanged["status"] == "ASSIGNED"
        assert unchanged["amendment_count"] == 0
        assert unchanged["amendment_reason"] is None

        signed = fx.sign_report(api, report["id"], lab.roster.rad1)
        assert_signed_interpretation(signed, "RESTRICTION", "MODERATE")
        after_signature = validate_success(
            api.get_test_session(signed["session_id"], LAB_MANAGER)
        )
        assert after_signature["session_status"] == "REPORTED"

        amended = validate_success(
            api.amend_interpretation_report(
                report["id"],
                f.amend_report_payload("Corrected the clinical comment."),
                lab.roster.rad1,
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

        interpreter = validate_success(
            api.get_staff(lab.roster.rad1_id, LAB_MANAGER)
        )
        assert interpreter["open_report_count"] == 1
        after_amendment = validate_success(
            api.get_test_session(signed["session_id"], LAB_MANAGER)
        )
        assert after_amendment["session_status"] == "REPORTED"


class TestDeviceHygieneState:
    """A soiled instrument needs both halves of the cycle, in either order."""

    def test_the_second_of_the_two_hygiene_events_is_the_one_that_clears_it(self, api):
        """A fresh filter alone resets the counter but not the status.

        PRD 3.3: "Whichever of the two events is appended second is the one that
        clears the device, and it clears it only when both qualifying events
        postdate the study that soiled it."

        Design: Corner/state_machines/soiled_device_needs_both_infection_control_halves_after_the_session_end
        """
        lab = fx.build_lab(api)
        fx.build_accepted_session(api, lab)

        soiled = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert soiled["status"] == "SOILED"
        assert_instant(soiled["last_session_end_at"], "2026-08-03T09:30:00Z")
        assert soiled["sessions_since_filter_change"] == 1
        assert soiled["current_filter_serial"] == "F-1001"

        fx.set_clock(api, "2026-08-03T09:35:00Z")
        refit = fx.append_quality_event(
            api,
            lab.device_id,
            f.filter_replacement_event_payload("F-1002"),
            lab.tech1,
        )
        assert refit["outcome"] == "COMPLETE"

        half_way = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert half_way["status"] == "SOILED"
        assert half_way["current_filter_serial"] == "F-1002"
        assert half_way["sessions_since_filter_change"] == 0

        disinfection = fx.append_quality_event(
            api, lab.device_id, f.disinfection_event_payload(25), lab.tech1
        )
        assert disinfection["outcome"] == "COMPLETE"

        cleared = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert cleared["status"] == "AVAILABLE"
        assert_instant(cleared["last_session_end_at"], "2026-08-03T09:30:00Z")


class TestCascadeConditionalOnState:
    """A cascade touches a row only when that row's own state admits it."""

    def test_cancelling_the_order_aborts_the_study_that_never_started(self, api):
        """The abort is recorded but the order counter and the device stay put.

        PRD 3.4: "A cancellation moves every `PENDING` hold on the order to
        `SUPERSEDED`, sets the order's `hold_release_at` to null, and aborts
        every study for that order whose `session_status` is `SCHEDULED` or
        `IN_PROGRESS` with `abort_reason` `ORDER_CANCELLED`, oldest first by
        `created_at`. Those aborts do not bounce the order back to `READY`, since
        it is already cancelled."

        Design: Corner/state_machines/order_cancellation_cascades_down_to_abort_its_scheduled_session
        """
        lab = fx.build_lab(api)
        scheduled = fx.build_scheduled_session(api, lab)
        order_id = scheduled["order_id"]

        cancelled = validate_success(
            api.cancel_test_order(order_id, f.cancel_order_payload(), lab.doc1)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "Patient withdrew from the referral."
        assert cancelled["abort_count"] == 0

        aborted = validate_success(api.get_test_session(scheduled["id"], LAB_MANAGER))
        assert aborted["session_status"] == "ABORTED"
        assert aborted["abort_reason"] == "ORDER_CANCELLED"

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert device["status"] == "AVAILABLE"
        assert device["last_session_end_at"] is None

        rows, meta = validate_paginated(
            api.list_test_sessions(LAB_MANAGER, session_status="ABORTED")
        )
        assert_page(meta, total_count=1, has_more=False)
        assert_listing_ids(rows, [scheduled["id"]])

    def test_a_quarantine_aborts_the_scheduled_study_and_spares_the_accepted_one(self, api):
        """Only the study still standing in a live state is dragged down.

        PRD 3.3: "The moment a device becomes `QUARANTINED`, every study on that
        device whose `session_status` is `SCHEDULED` or `IN_PROGRESS` is aborted
        with `abort_reason` `DEVICE_QUARANTINED`, oldest study first by
        `created_at`, and each of those aborts then drives its own downstream
        consequences — the parent order back from `IN_TESTING` to `READY` with
        `abort_count` incremented, every live challenge run on the study to
        `ABORTED_SAFETY` with `stop_reason` `SESSION_ABORTED`, the corresponding
        rescue-lot ledger movements, and any report still `ASSIGNED` on that
        study to `REASSIGNED` with its interpreter's `open_report_count`
        decremented."

        Design: Corner/state_machines/device_quarantine_cascade_aborts_the_scheduled_session_and_spares_the_accepted_one
        """
        lab = fx.build_lab(api)
        morning = fx.build_scheduled_session(api, lab)
        late_morning = fx.build_scheduled_session(
            api,
            lab,
            scheduled_start_at="2026-08-03T11:00:00Z",
            scheduled_end_at="2026-08-03T11:30:00Z",
        )
        fx.append_maneuver_series(api, morning["id"], lab.tech1)
        fx.finalize_quality(api, morning["id"], lab.tech1)

        fx.set_clock(api, "2026-08-03T09:35:00Z")
        fx.append_quality_event(
            api, lab.device_id, f.filter_replacement_event_payload("F-1002"), lab.tech1
        )
        fx.append_quality_event(
            api, lab.device_id, f.disinfection_event_payload(25), lab.tech1
        )

        failure = fx.append_quality_event(
            api, lab.device_id, f.calibration_event_payload(2.848), lab.tech1
        )
        assert_2dp(failure["error_pct"], 3.03)
        assert failure["outcome"] == "FAIL"

        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert_device_quarantined(
            device, "CALIBRATION_FAILED", trigger_staff_id=lab.tech1_id
        )
        assert device["consecutive_biologic_failures"] == 0

        cascaded = validate_success(
            api.get_test_session(late_morning["id"], LAB_MANAGER)
        )
        assert cascaded["session_status"] == "ABORTED"
        assert cascaded["abort_reason"] == "DEVICE_QUARANTINED"

        spared = validate_success(api.get_test_session(morning["id"], LAB_MANAGER))
        assert spared["session_status"] == "ACCEPTED"
        assert spared["quality_grade"] == "A"

        cascaded_order = validate_success(
            api.get_test_order(late_morning["order_id"], LAB_MANAGER)
        )
        assert cascaded_order["status"] == "READY"
        assert cascaded_order["abort_count"] == 1

        spared_order = validate_success(
            api.get_test_order(morning["order_id"], LAB_MANAGER)
        )
        assert spared_order["status"] == "IN_TESTING"
        assert spared_order["abort_count"] == 0
