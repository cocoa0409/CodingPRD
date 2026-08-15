"""Agreement termination cascades and the abandonment / removal workflow with
its depth-3 cascade and late-removal penalty (PRD §2.8, §3.1, §3.8).
"""
from test_helpers import (
    ENGINEER,
    RCM,
    assert_track_agreement,
    get_amendment,
    get_segment,
    get_service_order,
    get_storage_placement,
    make_active_agreement,
    make_amendment,
    make_segment,
    make_service_order,
    make_shipper_headers,
    setup_abandonment_in_progress,
    setup_terminated_with_stored_car,
    validate_success,
)
from test_helpers import constants as C


class TestTerminationCascade:
    def test_terminate_cascades_to_orders_and_amendments(self, api):
        """PRD §3.1: "Termination cascades directly — every service order of
        the agreement still `REQUESTED` becomes `CANCELLED`, and every
        amendment still `PENDING` becomes `SUPERSEDED` — and bumps the
        agreement's `version`."

        Design: Corner/state_machines/terminate_cascades_to_orders_and_amendments
        """
        agreement = make_active_agreement()
        agr_id = agreement["id"]
        amendment = make_amendment(agr_id, expected_agreement_version=3)
        segment = make_segment(agr_id)
        order = make_service_order(agr_id, segment["id"])
        res = api.terminate_agreement(
            agr_id, RCM, payload={"reason": "Repeated safety violations"}
        )
        terminated = validate_success(res)
        assert terminated["status"] == "TERMINATED"
        assert get_service_order(order["id"])["status"] == "CANCELLED"
        assert get_amendment(amendment["id"])["status"] == "SUPERSEDED"


class TestAbandonmentCascade:
    def test_notice_sets_dates_and_grounds_segments(self, api):
        """PRD §3.8: "Filing records `abandonment_notice_date` as the supplied
        notice date, computes `removal_deadline_date` as that date plus the
        agreement's `removal_period_days` days, and moves the agreement to
        `ABANDONMENT_IN_PROGRESS` — and then the cascade fires, link by link."
        PRD §3.8: "At the first link, every segment of the agreement still
        `IN_SERVICE` moves to `OUT_OF_SERVICE`."

        Design: Difficulty/transitive_cascade/abandonment_cascade_depth3
        """
        ctx = setup_terminated_with_stored_car()
        res = api.file_abandonment_notice(
            ctx["agreement"]["id"], {"notice_date": "2026-09-01"},
            make_shipper_headers(C.SHIPPER_USER_ID),
        )
        agreement = validate_success(res)
        assert_track_agreement(agreement)
        assert agreement["status"] == "ABANDONMENT_IN_PROGRESS"
        assert agreement["abandonment_notice_date"] == "2026-09-01"
        # 2026-09-01 + 90 days = 2026-11-30.
        assert agreement["removal_deadline_date"] == "2026-11-30"
        segment = get_segment(ctx["segment"]["id"])
        assert segment["status"] == "OUT_OF_SERVICE"

    def test_cascade_force_releases_and_recomputes_ledger(self, api):
        """PRD §3.8: "Each segment's transition causes the second link: every
        storage placement on that segment still `STORED` becomes
        `FORCE_RELEASED` with its `released_date` set to the notice date and
        its `days_charged` and `final_storage_charge_cents` computed per the
        storage charge rules, and every service order on that segment still
        `REQUESTED` becomes `CANCELLED`."
        PRD §3.8: "Each force-release causes the third link: the placement's
        segment recomputes `accrued_storage_cents` as the sum of final charges
        over `RELEASED` and `FORCE_RELEASED` placements, and `stored_car_count`
        as the count of placements still `STORED`."

        Design: Difficulty/transitive_cascade/abandonment_cascade_depth3
        """
        ctx = setup_terminated_with_stored_car(car_mark="STGX901")
        validate_success(
            api.file_abandonment_notice(
                ctx["agreement"]["id"], {"notice_date": "2026-09-01"},
                make_shipper_headers(C.SHIPPER_USER_ID),
            )
        )
        placement = get_storage_placement(ctx["placement"]["id"])
        assert placement["status"] == "FORCE_RELEASED"
        assert placement["released_date"] == "2026-09-01"
        # 2026-08-01 -> 2026-09-01 is 31 days; 333.73 * 31 = 10345.63 -> 10346.
        assert placement["days_charged"] == 31
        assert placement["final_storage_charge_cents"] == 10346
        segment = get_segment(ctx["segment"]["id"])
        assert segment["accrued_storage_cents"] == 10346
        assert segment["stored_car_count"] == 0


class TestRemovalVerification:
    def test_late_verification_accrues_penalty(self, api):
        """PRD §3.8: "Verification computes the late-removal penalty: the
        number of whole days by which the verified date falls after
        `removal_deadline_date`, floored at zero — verification exactly on the
        deadline accrues nothing — multiplied by
        `removal_penalty_per_day_cents`, and records the result in
        `removal_penalty_cents`."
        PRD §3.8: "Every segment then `OUT_OF_SERVICE` moves to `REMOVED`, the
        segment's terminal state, and the agreement reaches `CLOSED`, its
        terminal state."

        Design: Corner/calculations/removal_penalty_late_accrual
        """
        ctx = setup_abandonment_in_progress(notice_date="2026-09-01")
        assert ctx["agreement"]["removal_deadline_date"] == "2026-11-30"
        # 2026-12-10 is 10 days after the 2026-11-30 deadline.
        res = api.verify_removal(
            ctx["agreement"]["id"],
            {"removal_verified_date": "2026-12-10"},
            ENGINEER,
        )
        closed = validate_success(res)
        assert closed["removal_penalty_cents"] == 50000  # 10 * 5000
        assert closed["status"] == "CLOSED"
        assert get_segment(ctx["segment"]["id"])["status"] == "REMOVED"

    def test_verification_on_deadline_accrues_nothing(self, api):
        """PRD §3.8: "Verification computes the late-removal penalty: the
        number of whole days by which the verified date falls after
        `removal_deadline_date`, floored at zero — verification exactly on the
        deadline accrues nothing — multiplied by
        `removal_penalty_per_day_cents`, and records the result in
        `removal_penalty_cents`."

        Design: Corner/calculations/removal_penalty_on_deadline_is_zero
        """
        ctx = setup_abandonment_in_progress(
            notice_date="2026-09-01", with_segment=False
        )
        res = api.verify_removal(
            ctx["agreement"]["id"],
            {"removal_verified_date": "2026-11-30"},
            ENGINEER,
        )
        closed = validate_success(res)
        assert closed["removal_penalty_cents"] == 0
        assert closed["status"] == "CLOSED"
