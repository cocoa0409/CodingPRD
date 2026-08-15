"""Release compound status, the release-risk projection, delay notices
(append-only log), and OCC-guarded date revisions."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_delay_notice,
    confirm_order,
    create_completed_order,
    create_order,
    create_queued_order,
    decide_qc_report,
    drive_tooling_to_stamper_ready,
    file_qc_report,
    get_order,
    press_run,
    produce_test_pressing,
    quote_order,
    review_test_pressing,
    schedule_order,
    setup_world,
    ship_test_pressing,
    start_tooling,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CSR


class TestReleaseCompoundStatus:
    def test_release_compound_status_progression(self, api):
        """PRD §2.10: "a release's `status` is a compound of its orders'
        states, moving from `SETUP` to `IN_PRODUCTION` on the first order
        confirmation and from `IN_PRODUCTION` to `FULFILLED` once every order
        of the release is terminal."
        PRD §3.2: "A new release starts in `SETUP` with `risk_level`
        `ON_TRACK`."

        Design: Corner/state_machines/release_compound_status_progression
        """
        world = setup_world()
        rel = world["release"]
        assert rel["status"] == "SETUP"
        assert rel["risk_level"] == "ON_TRACK"

        order = create_order(rel["id"], quantity_ordered=1000)
        order = quote_order(order)
        order = confirm_order(order, world["customer"]["id"])
        mid = validate_success(api.get_release(rel["id"], CSR), 200)
        assert mid["status"] == "IN_PRODUCTION", (
            "the first order confirmation must flip the release to IN_PRODUCTION"
        )

        job = start_tooling(order["id"])
        drive_tooling_to_stamper_ready(job["id"], world["bath"]["id"])
        tp = produce_test_pressing(order["id"])
        tp = ship_test_pressing(tp["id"])
        review_test_pressing(tp["id"], world["customer"]["id"], "APPROVE")
        order = get_order(order["id"])
        order = schedule_order(order, world["line"]["id"], planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc = file_qc_report(order["id"], 1000, 30)
        decide_qc_report(qc["id"], "ACCEPT", "NONE")

        done = validate_success(api.get_release(rel["id"], CSR), 200)
        assert done["status"] == "FULFILLED", (
            "with every order terminal, the release must move to FULFILLED"
        )


class TestRiskRead:
    def test_release_risk_read_on_setup_release(self, api):
        """PRD §3.2: "The release's `projected_completion_date` is the latest
        projection across its non-terminal orders — null when none remain
        open"
        PRD §3.2: "A new release starts in `SETUP` with `risk_level`
        `ON_TRACK`."

        Design: Corner/endpoints/release_risk_read_on_setup_release
        """
        world = setup_world(with_line=False, with_bath=False)
        risk = validate_success(api.get_release_risk(world["release"]["id"], CSR), 200)
        assert risk["risk_level"] == "ON_TRACK"
        assert risk["projected_completion_date"] is None
        assert risk["slack_days"] is None


def _order_awaiting_tp_approval(world, quantity_ordered=1000):
    """Drive an order up to AWAITING_TP_APPROVAL (TP shipped, not reviewed)."""
    order = create_order(world["release"]["id"], quantity_ordered=quantity_ordered)
    order = quote_order(order)
    order = confirm_order(order, world["customer"]["id"])
    job = start_tooling(order["id"])
    drive_tooling_to_stamper_ready(job["id"], world["bath"]["id"])
    tp = produce_test_pressing(order["id"])
    tp = ship_test_pressing(tp["id"])
    return order, tp


class TestTpApprovalCascade:
    def test_tp_approval_cascade_state_and_risk(self, api):
        """PRD §3.4: "Supplying `decision` `APPROVE` moves the pressing
        `UNDER_REVIEW` → `APPROVED` and cascades the order
        `AWAITING_TP_APPROVAL` → `QUEUED`, followed by a risk recompute with
        cause `SCHEDULE` and a DelayNotice if the outlook worsened."
        PRD §3.2: "a `QUEUED` order that has never been repressed projects to
        today plus 21 days"
        PRD §3.2: "The `risk_level` is `ON_TRACK` when slack is at least 14
        days, `AT_RISK` when slack is zero or more but under 14, and `LATE`
        when slack is negative."

        Design: Difficulty/transitive_cascade/tp_approval_cascade_to_delay_notice
        """
        world = setup_world(release_over={"release_date": "2026-08-20"},
                            with_line=False)
        order, tp = _order_awaiting_tp_approval(world)
        reviewed = review_test_pressing(tp["id"], world["customer"]["id"], "APPROVE")
        assert reviewed["status"] == "APPROVED"

        order_after = get_order(order["id"])
        assert order_after["production_status"] == "QUEUED"

        rel = validate_success(api.get_release(world["release"]["id"], CSR), 200)
        # QUEUED projection: 2026-08-01 + 21 days = 2026-08-22 vs the
        # 2026-08-20 street date -> slack -2 -> LATE.
        assert rel["projected_completion_date"] == "2026-08-22"
        assert rel["slack_days"] == -2
        assert rel["risk_level"] == "LATE"

    def test_tp_approval_cascade_delay_notice(self, api):
        """PRD §3.2: "Whenever a recompute worsens the level, the system
        appends a DelayNotice recording the `release_id`, the `press_order_id`
        of the order whose recompute worsened the outlook, the `cause` (one of
        `TP_REVISION`, `REPRESS`, `SCHEDULE`, or `DATE_REVISION`), the
        `prior_level`, the strictly worse `new_level`, and a human-readable
        `message`; improvement never generates a notice."

        Design: Difficulty/transitive_cascade/tp_approval_cascade_to_delay_notice
        """
        world = setup_world(release_over={"release_date": "2026-08-20"},
                            with_line=False)
        order, tp = _order_awaiting_tp_approval(world)
        review_test_pressing(tp["id"], world["customer"]["id"], "APPROVE")

        notices, _m = validate_paginated(
            api.list_release_delay_notices(world["release"]["id"], CSR)
        )
        assert len(notices) == 1, (
            f"exactly one notice expected, got {len(notices)}"
        )
        notice = notices[0]
        assert_delay_notice(notice)
        assert notice["prior_level"] == "ON_TRACK"
        assert notice["new_level"] == "LATE"
        assert notice["cause"] == "SCHEDULE"
        assert notice["press_order_id"] == order["id"]


class TestRepressCascade:
    def _setup_repress(self, world):
        """Order scheduled 2026-08-10, pressed with a HOLD run, then a
        PLANT-fault REPRESS decision. Returns the order id."""
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], world["line"]["id"],
                               date="2026-08-10", start_hour=0, end_hour=8,
                               planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc = file_qc_report(order["id"], 1000, 100)
        assert qc["outcome"] == "HOLD"
        return order["id"], qc["id"]

    def test_repress_cascade_notices_and_risk(self, api):
        """PRD §3.7: "The risk recompute applies the ten-day repress delay with
        cause `REPRESS` and appends a DelayNotice on worsening."
        PRD §3.2: "one that has been repressed at least once projects to today
        plus 21 days plus a further 10 days of repress delay"
        PRD §3.7: "the run's good units are banked into `accepted_units` — the
        repress re-covers only the rejected shortfall, never the good units."

        Design: Difficulty/transitive_cascade/repress_decision_cascade_to_notice_and_backlog
        """
        world = setup_world(release_over={"release_date": "2026-08-20"})
        order_id, qc_id = self._setup_repress(world)

        # The TP-approval recompute inside _setup_repress (clock 2026-08-01)
        # already fired ON_TRACK -> LATE: QUEUED projection 2026-08-22 vs the
        # 2026-08-20 street date -> slack -2 (PRD §3.4 names cause SCHEDULE for
        # the approval recompute). The later schedule-commit improves the level
        # to AT_RISK (projection 2026-08-11 -> slack 9), emitting no notice.
        decide_qc_report(qc_id, "REPRESS", "PLANT", decider="pm-1")

        order = get_order(order_id)
        assert order["production_status"] == "QUEUED"
        assert order["repress_round"] == 1
        assert order["accepted_units"] == 900

        rel = validate_success(api.get_release(world["release"]["id"], CSR), 200)
        # Repressed QUEUED projection: 2026-08-10 + 21 + 10 = 2026-09-10 ->
        # slack -21 -> LATE.
        assert rel["projected_completion_date"] == "2026-09-10"
        assert rel["slack_days"] == -21
        assert rel["risk_level"] == "LATE"

        notices, _m = validate_paginated(
            api.list_release_delay_notices(world["release"]["id"], CSR)
        )
        assert len(notices) == 2
        assert notices[0]["prior_level"] == "ON_TRACK"
        assert notices[0]["new_level"] == "LATE"
        assert notices[0]["cause"] == "SCHEDULE"
        assert notices[1]["prior_level"] == "AT_RISK"
        assert notices[1]["new_level"] == "LATE"
        assert notices[1]["cause"] == "REPRESS"

    def test_repress_cascade_conservative_backlog(self, api):
        """PRD §3.6: "The conservative figure inflates booked hours by
        twenty-five percent, adds a repress-queue term — the sum, over each
        order of this line currently `QUEUED` after at least one repress, of
        that order's `quantity_ordered` divided by the line's hourly rate and
        rounded up to whole hours — divides the total by `hours_per_day`, and
        rounds half-up to two decimals"

        Design: Difficulty/transitive_cascade/repress_decision_cascade_to_notice_and_backlog
        """
        world = setup_world(release_over={"release_date": "2026-08-20"})
        order_id, qc_id = self._setup_repress(world)
        decide_qc_report(qc_id, "REPRESS", "PLANT", decider="pm-1")

        backlog = validate_success(
            api.get_line_backlog(world["line"]["id"], CSR), 200
        )
        # booked 8h slot (dated 2026-08-10, today) -> optimistic 8/16 = 0.50;
        # conservative (8*1.25 + ceil(1000/313))/16 = 14/16 -> 0.88.
        assert backlog["booked_hours"] == 8
        assert backlog["optimistic_backlog_days"] == pytest.approx(0.50, abs=1e-6)
        assert backlog["conservative_backlog_days"] == pytest.approx(0.88, abs=1e-6)


class TestDateRevisionOcc:
    def test_occ_release_date_revision_stale(self, api):
        """PRD §2.7: "Revising a release's street date requires
        `expected_release_version` matching the release's current `version`.
        Date revisions supersede the prior date and are always permitted while
        the release is not `FULFILLED`; a revision whose
        `expected_release_version` lags the release's current `version` —
        advanced by prior revisions or by the first-confirm cascade that moves
        a release from `SETUP` to `IN_PRODUCTION` — is rejected with
        `ERR_STALE_VERSION`."
        PRD §3.2: "A street-date change is itself a superseding revision: the
        representative supplies `new_release_date`, a `reason`, and the OCC
        guard, the release's `version` increments, and the risk recompute runs
        with cause `DATE_REVISION`."

        Design: Corner/cross_cutting_layers/occ_release_date_revision_stale
        """
        world = setup_world(with_line=False)
        staged = create_queued_order(world, quantity_ordered=100)
        rel = validate_success(api.get_release(world["release"]["id"], CSR), 200)

        r1 = api.revise_release_date(
            rel["id"],
            {"new_release_date": "2026-08-20", "reason": "moved up",
             "expected_release_version": rel["version"]},
            CSR,
        )
        revised = validate_success(r1, 200)
        assert revised["release_date"] == "2026-08-20"
        # QUEUED projection 2026-08-22 vs 2026-08-20 -> slack -2 -> LATE.
        assert revised["risk_level"] == "LATE"

        notices, _m = validate_paginated(
            api.list_release_delay_notices(rel["id"], CSR)
        )
        assert len(notices) == 1
        assert notices[0]["cause"] == "DATE_REVISION"

        # Replaying the pre-revision version is stale.
        r2 = api.revise_release_date(
            rel["id"],
            {"new_release_date": "2026-09-01", "reason": "stale replay",
             "expected_release_version": rel["version"]},
            CSR,
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)


class TestDelayNoticeShape:
    def test_delay_notice_append_only_shape(self, api):
        """PRD §2.4: "The DelayNotice resource is the single exception. Because
        it is an append-only event log entry, it carries `id` and `created_at`
        only — it has no `updated_at` and no `version`, and no operation ever
        mutates a DelayNotice after creation."

        Design: Corner/entities/delay_notice_append_only_shape
        """
        world = setup_world(release_over={"release_date": "2026-08-20"},
                            with_line=False)
        order, tp = _order_awaiting_tp_approval(world, quantity_ordered=100)
        review_test_pressing(tp["id"], world["customer"]["id"], "APPROVE")

        notices, _m = validate_paginated(
            api.list_release_delay_notices(world["release"]["id"], CSR)
        )
        assert len(notices) == 1
        notice = notices[0]
        assert_delay_notice(notice)
        assert notice["cause"] == "SCHEDULE"
        assert notice["release_id"] == world["release"]["id"]
        assert notice["press_order_id"] == order["id"]
