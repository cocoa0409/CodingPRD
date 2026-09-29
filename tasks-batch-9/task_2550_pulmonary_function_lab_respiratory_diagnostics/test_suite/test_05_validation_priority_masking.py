"""When several rules are broken at once, only the earliest one speaks.

Scheduling a study onto a device that is soiled, uncalibrated and uncontrolled
breaks three rules in one request, and the laboratory reports the device's state
and nothing else.  Arming a challenge run against a lot that is both expired and
short reports the safety failure, never the shortage.  Both scenarios then
remediate one rule at a time and watch the next complaint emerge from the same
unchanged payload.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BIOLOGIC_CONTROL_MISSING,
    ERR_CALIBRATION_STALE,
    ERR_DEVICE_NOT_AVAILABLE,
    ERR_INFECTION_CONTROL_INCOMPLETE,
    ERR_RESCUE_DOSES_INSUFFICIENT,
    ERR_RESCUE_NOT_READY,
)
from test_helpers.assertions import (
    assert_3dp,
    assert_dose_ledger_balanced,
    assert_page,
    assert_reservation_matches_live_runs,
)
from test_helpers.test_users import LAB_MANAGER

NEXT_DAY_START = "2026-08-04T09:00:00Z"
NEXT_DAY_END = "2026-08-04T09:30:00Z"


def _lab_the_morning_after_a_completed_study(api):
    """A device left soiled by yesterday's study, and a fresh order for today.

    Yesterday's calibration, biologic control, filter change and disinfection
    are all a day old once the clock moves on, and the hygiene pair predates the
    study that soiled the instrument.
    """
    lab = fx.build_lab(api)
    yesterday = fx.build_session_with_maneuvers(api, lab)
    fx.finalize_quality(api, yesterday["id"], lab.tech1)
    order = fx.build_ready_order(api, lab)
    fx.set_clock(api, "2026-08-04T08:00:00Z")
    return lab, order


def _attempt_to_schedule(api, lab, order):
    """The one identical booking request every stage of this scenario sends."""
    return api.create_test_session(
        f.test_session_payload(order["id"], lab.device_id, NEXT_DAY_START, NEXT_DAY_END),
        lab.tech1,
    )


class TestSchedulingGateMasking:
    """The device-state rung hides every safety rung sitting below it."""

    def test_a_soiled_device_reports_its_state_and_nothing_further(self, api):
        """Three broken rules, one answer, and no half-built study left behind.

        PRD 2.9: "**The ladder is evaluated in ascending order and the first
        rule that is violated determines the entire response; no later rule is
        evaluated.**"

        Design: Difficulty/priority_pair_validation_conflict/device_status_state_error_masks_calibration_and_biologic_safety_errors
        """
        lab, order = _lab_the_morning_after_a_completed_study(api)

        refused = _attempt_to_schedule(api, lab, order)

        body = validate_error(refused, ERR_DEVICE_NOT_AVAILABLE)
        assert body["error_id"] not in (
            ERR_CALIBRATION_STALE,
            ERR_BIOLOGIC_CONTROL_MISSING,
            ERR_INFECTION_CONTROL_INCOMPLETE,
        )
        still_ready = validate_success(api.get_test_order(order["id"], lab.doc1))
        assert still_ready["status"] == "READY"
        rows, meta = validate_paginated(
            api.list_test_sessions(lab.tech1, order_id=order["id"])
        )
        assert rows == []
        assert_page(meta, total_count=0, has_more=False)

    def test_each_remediation_uncovers_the_rule_the_last_one_masked(self, api):
        """Hygiene, then calibration, then a control blow: three refusals, then a booking.

        PRD 2.9: "This ordering is part of the contract, because many requests
        can fail several rules at once and only one code may be returned."

        Design: Difficulty/priority_pair_validation_conflict/device_status_state_error_masks_calibration_and_biologic_safety_errors
        """
        lab, order = _lab_the_morning_after_a_completed_study(api)
        validate_error(_attempt_to_schedule(api, lab, order), ERR_DEVICE_NOT_AVAILABLE)

        fx.append_quality_event(
            api, lab.device_id, f.filter_replacement_event_payload("F-1002"), lab.tech1
        )
        fx.append_quality_event(
            api, lab.device_id, f.disinfection_event_payload(25), lab.tech1
        )
        cleaned = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert cleaned["status"] == "AVAILABLE"
        assert cleaned["sessions_since_filter_change"] == 0

        validate_error(_attempt_to_schedule(api, lab, order), ERR_CALIBRATION_STALE)
        fx.append_quality_event(
            api, lab.device_id, f.calibration_event_payload(2.764), lab.tech1
        )

        validate_error(
            _attempt_to_schedule(api, lab, order), ERR_BIOLOGIC_CONTROL_MISSING
        )
        fx.append_quality_event(
            api,
            lab.device_id,
            f.biologic_control_event_payload(lab.bcs_id, 3.850, 5.100),
            lab.tech1,
        )

        booked = validate_success(
            _attempt_to_schedule(api, lab, order), expected_status=201
        )
        assert booked["session_status"] == "SCHEDULED"
        in_testing = validate_success(api.get_test_order(order["id"], lab.doc1))
        assert in_testing["status"] == "IN_TESTING"


def _in_progress_challenge_study_with_three_lots(api):
    """A provocation study standing ready, and three lots of differing quality.

    L-EXPIRED went out of date yesterday and holds only three doses, so it
    breaks the readiness rule and the four-dose reserve at once; L-SHORT is in
    date but equally short; L-2026-08 is in date and full.
    """
    lab = fx.build_lab(api)
    expired = fx.receive_rescue_lot(
        api, lot_number="L-EXPIRED", doses_at_receipt=3, expires_on="2026-08-02"
    )
    short = fx.receive_rescue_lot(
        api, lot_number="L-SHORT", doses_at_receipt=3, expires_on="2026-12-31"
    )
    full = fx.receive_rescue_lot(api, lot_number="L-2026-08", doses_at_receipt=10)
    session = fx.build_session_with_maneuvers(
        api,
        lab,
        indication_code="ASTHMA_DIAGNOSIS",
        challenge_type="METHACHOLINE",
    )
    return lab, session, expired["id"], short["id"], full["id"]


def _attempt_to_arm(api, lab, session, lot_id):
    return api.create_challenge_run(
        session["id"], f.challenge_run_payload(lot_id), lab.tech1
    )


class TestRescueLotGateMasking:
    """Readiness is asked before stock, so an unusable lot never gets counted."""

    def test_an_expired_and_short_lot_reports_only_the_safety_failure(self, api):
        """Two rules broken by one lot, and the clinician hears about the drug.

        PRD 3.7: "Because readiness is checked first, a lot that is both expired
        and short-stocked reports the safety failure rather than the fiscal one;
        the clinician is told the drug is unusable, not merely that there is not
        much of it."

        Design: Difficulty/priority_pair_validation_conflict/rescue_lot_safety_error_masks_dose_shortage_fiscal_error
        """
        lab, session, expired_id, _, _ = _in_progress_challenge_study_with_three_lots(api)

        refused = _attempt_to_arm(api, lab, session, expired_id)

        body = validate_error(refused, ERR_RESCUE_NOT_READY)
        assert body["error_id"] != ERR_RESCUE_DOSES_INSUFFICIENT
        lot = validate_success(api.get_rescue_lot(expired_id, LAB_MANAGER))
        assert lot["status"] == "STOCKED", (
            "the clock never crossed this lot's expiry, so only the readiness "
            "date comparison can have refused it"
        )
        assert lot["doses_reserved"] == 0
        assert lot["doses_remaining"] == 3
        assert_dose_ledger_balanced(lot, [])
        assert_reservation_matches_live_runs(lot, 0)
        _, meta = validate_paginated(
            api.list_challenge_runs(lab.tech1, session_id=session["id"])
        )
        assert_page(meta, total_count=0, has_more=False)

    def test_a_lot_that_clears_readiness_then_fails_on_the_four_dose_reserve(self, api):
        """The shortage only surfaces for a lot the safety rule has already passed.

        PRD 3.7: "The nominated lot must then pass a **readiness** check —
        `status` exactly `STOCKED` and `expires_on` on or after the current
        logical date, otherwise `ERR_RESCUE_NOT_READY` — and only after that
        passes is the **stock** check made, requiring `doses_remaining` minus
        `doses_reserved` to be at least 4, otherwise
        `ERR_RESCUE_DOSES_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/rescue_lot_safety_error_masks_dose_shortage_fiscal_error
        """
        lab, session, expired_id, short_id, full_id = (
            _in_progress_challenge_study_with_three_lots(api)
        )
        validate_error(_attempt_to_arm(api, lab, session, expired_id), ERR_RESCUE_NOT_READY)

        validate_error(
            _attempt_to_arm(api, lab, session, short_id), ERR_RESCUE_DOSES_INSUFFICIENT
        )
        short_lot = validate_success(api.get_rescue_lot(short_id, LAB_MANAGER))
        assert short_lot["doses_reserved"] == 0
        assert short_lot["doses_remaining"] == 3

        armed = validate_success(
            _attempt_to_arm(api, lab, session, full_id), expected_status=201
        )
        assert armed["status"] == "ARMED"
        assert_3dp(armed["baseline_fev1_l"], 2.400)
        full_lot = validate_success(api.get_rescue_lot(full_id, LAB_MANAGER))
        assert full_lot["doses_reserved"] == 4
        assert full_lot["doses_remaining"] == 10
        assert_reservation_matches_live_runs(full_lot, 1)

        rows, meta = validate_paginated(
            api.list_challenge_runs(lab.tech1, session_id=session["id"])
        )
        assert [row["id"] for row in rows] == [armed["id"]]
        assert_page(meta, total_count=1, has_more=False)
        live = validate_success(api.get_test_session(session["id"], lab.tech1))
        assert live["session_status"] == "IN_PROGRESS"
