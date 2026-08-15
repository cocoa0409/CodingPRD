"""Purchase windows: scheduling, overlap, blackout, orders, fees, settlement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_shares_equal,
    close_window_at,
    create_active_enrollment,
    create_active_plan,
    create_window,
    declare_dividend,
    deposit_shares,
    get_order,
    get_success_data,
    get_window,
    list_fees,
    make_participant_headers,
    open_window_at,
    register_participant,
    setup_open_window_scenario,
    submit_order,
    submit_order_ok,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestWindowCumulativeLimit:
    def test_cumulative_limit_exact_ceiling_allowed_then_exceed_rejected(self, api):
        """PRD §3.5: "the cumulative ceiling — the sum of `amount_cents` over
        that enrollment's still-`SUBMITTED` orders in the same window, plus the
        new amount — must not strictly exceed the plan's `ocp_max_cents`, else
        `ERR_PURCHASE_LIMIT_EXCEEDED` (HTTP 422). Landing exactly on the ceiling
        is allowed, and orders that leave `SUBMITTED` release their
        reservation."

        Design: Difficulty/boundary_precision_check/window_cumulative_limit_equal_allowed_exceed_rejected
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Bnd Corp", "ticker": "BND",
                            "name": "BND DRIP"},
            participant_email="pb2@x.com")
        o1 = submit_order_ok(window["id"], enrollment["id"], participant["id"],
                             12000)
        o2 = submit_order_ok(window["id"], enrollment["id"], participant["id"],
                             13000)
        assert get_order(o1["id"])["status"] == "SUBMITTED"
        assert get_order(o2["id"])["status"] == "SUBMITTED", (
            "12000 + 13000 lands exactly on the 25000 ceiling and is allowed")

        resp = submit_order(window["id"], enrollment["id"], participant["id"],
                            1000)
        # A further 1000 strictly exceeds the ceiling (26000 > 25000).
        validate_error(resp, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED)

    def test_cumulative_limit_cancelled_order_releases_reservation(self, api):
        """PRD §3.5: "Landing exactly on the ceiling is allowed, and orders
        that leave `SUBMITTED` release their reservation."
        PRD §3.5: "The owner may cancel an order while it is `SUBMITTED` and
        its window is still `OPEN`; cancellation moves it to `CANCELLED`,
        removes its amount from the window's `submitted_total_cents`, and
        increments the order's `version`."

        Design: Difficulty/boundary_precision_check/window_cumulative_limit_equal_allowed_exceed_rejected
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Bnd Corp", "ticker": "BND",
                            "name": "BND DRIP"},
            participant_email="pb2@x.com")
        submit_order_ok(window["id"], enrollment["id"], participant["id"],
                        12000)
        o2 = submit_order_ok(window["id"], enrollment["id"], participant["id"],
                             13000)
        cancelled = validate_success(api.cancel_purchase_order(
            o2["id"], make_participant_headers(participant["id"])))
        assert cancelled["status"] == "CANCELLED"

        o3 = submit_order_ok(window["id"], enrollment["id"], participant["id"],
                             13000)
        assert o3["status"] == "SUBMITTED", (
            "after the cancellation releases 13000, a fresh 13000 lands exactly "
            "on the ceiling again and is allowed")


def _setup_three_order_scenario():
    """One ACTIVE plan, one OPEN window @2500, and three SUBMITTED orders:
    12000 (normal participant), 9000 (normal), 12000 (fee-waiver-eligible).
    The window is then CLOSED at 2026-09-16. Returns (orders, enrollments)."""
    plan = create_active_plan(issuer_name="Fee Corp", ticker="FEE",
                              name="FEE DRIP")
    p_normal = register_participant("Pat N", "pn@x.com")
    e_normal = create_active_enrollment(plan["id"], p_normal["id"])
    p_waived = register_participant("Pat W", "pw@x.com", fee_waiver_eligible=True)
    e_waived = create_active_enrollment(plan["id"], p_waived["id"])
    window = create_window(plan["id"])
    open_window_at(window["id"])
    o_prop = submit_order_ok(window["id"], e_normal["id"], p_normal["id"], 12000)
    o_floor = submit_order_ok(window["id"], e_normal["id"], p_normal["id"], 9000)
    o_waived = submit_order_ok(window["id"], e_waived["id"], p_waived["id"], 12000)
    close_window_at(window["id"])
    return (plan, window, e_normal, e_waived, o_prop, o_floor, o_waived)


class TestOcpFeeAssessment:
    def test_ocp_fee_proportional_and_floor_arms(self, api):
        """PRD §3.5: "For every still-`SUBMITTED` order of the window the system
        first assesses the OCP fee — the greater of the plan's
        `ocp_fee_min_cents` floor and the proportional fee, the latter being the
        order's `amount_cents` times the plan's `ocp_fee_pct` rounded half-up to
        whole cents — as a fee assessment of type `OCP` with `WINDOW`
        provenance."
        PRD §3.5: "The order then moves to `SETTLED` with `settled_shares` set
        to the fee-net amount — `amount_cents` minus `charged_cents` — divided
        by the window's `price_cents`, rounded half-up to four decimal places"

        Design: Difficulty/combinatorial_formula/ocp_fee_max_min_with_conditional_inputs
        """
        (plan, window, e_normal, _e_waived, o_prop, o_floor,
         _o_waived) = _setup_three_order_scenario()
        get_success_data(api.settle_purchase_window(window["id"], ADMIN))

        prop = get_order(o_prop["id"])
        floor = get_order(o_floor["id"])
        assert prop["status"] == "SETTLED"
        assert floor["status"] == "SETTLED"
        assert_shares_equal(prop["settled_shares"], "4.5600",
                            "(12000 - max(500, 600)) / 2500")
        assert_shares_equal(floor["settled_shares"], "3.4000",
                            "(9000 - max(500, 450)) / 2500: the floor binds")

        fees = [f for f in list_fees(e_normal["id"]) if f["fee_type"] == "OCP"]
        assert len(fees) == 2
        fee_by_source = {f["source_id"]: f for f in fees}
        fee_prop = fee_by_source[o_prop["id"]]
        fee_floor = fee_by_source[o_floor["id"]]
        assert fee_prop["computed_cents"] == 600, "12000 * 0.05 = 600 exceeds the floor"
        assert fee_prop["charged_cents"] == 600
        assert fee_prop["waived"] is False
        assert fee_floor["computed_cents"] == 500, "the 500-cent floor binds on 9000 * 0.05 = 450"
        assert fee_floor["charged_cents"] == 500
        assert fee_floor["waived"] is False

    def test_ocp_fee_waiver_eligible_branch(self, api):
        """PRD §3.5: "When the participant behind the enrollment is
        fee-waiver-eligible the assessment is created waived with
        `waived_reason` `AUTO_ELIGIBLE` and `charged_cents` 0; otherwise
        `charged_cents` equals the computed fee."
        PRD §3.5: "The order then moves to `SETTLED` with `settled_shares` set
        to the fee-net amount — `amount_cents` minus `charged_cents` — divided
        by the window's `price_cents`, rounded half-up to four decimal places"

        Design: Difficulty/combinatorial_formula/ocp_fee_max_min_with_conditional_inputs
        """
        (plan, window, _e_normal, e_waived, _o_prop, _o_floor,
         o_waived) = _setup_three_order_scenario()
        get_success_data(api.settle_purchase_window(window["id"], ADMIN))

        settled = get_order(o_waived["id"])
        assert settled["status"] == "SETTLED"
        assert_shares_equal(settled["settled_shares"], "4.8000",
                            "(12000 - 0) / 2500: the waived fee nets nothing")

        fees = [f for f in list_fees(e_waived["id"]) if f["fee_type"] == "OCP"]
        assert len(fees) == 1
        fee = fees[0]
        assert fee["computed_cents"] == 600
        assert fee["charged_cents"] == 0
        assert fee["waived"] is True
        assert fee["waived_reason"] == "AUTO_ELIGIBLE"


class TestOrderSubmitValidationPriority:
    def test_order_submit_state_gate_masks_fiscal_check(self, api):
        """PRD §2.11: "Next come the state gates of §2.8 (`ERR_INVALID_STATE`,
        `ERR_PLAN_NOT_ACTIVE`, `ERR_WINDOW_NOT_OPEN`,
        `ERR_ENROLLMENT_NOT_ACTIVE`), then temporal business rules (window
        schedule sanity, dividend blackout, notice lead time, window opening
        time), then business constraints (window overlap, duplicate enrollment,
        election payload shape, minimum purchase amount), then fiscal checks
        (the cumulative purchase ceiling and sufficient shares for a transfer),
        and finally referential recipient checks (`ERR_RECIPIENT_NOT_ENROLLED`)."
        PRD §2.11: "Incoming requests are checked against a fixed priority
        order, and a failure at an earlier tier masks every later tier."

        Design: Difficulty/priority_pair_validation_conflict/order_submit_state_beats_fiscal
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Prio Corp", "ticker": "PRI",
                            "name": "PRI DRIP"},
            participant_email="pp@x.com")
        submit_order_ok(window["id"], enrollment["id"], participant["id"], 12000)
        submit_order_ok(window["id"], enrollment["id"], participant["id"], 12500)
        close_window_at(window["id"])

        resp = submit_order(window["id"], enrollment["id"], participant["id"],
                            1000)
        # The window is CLOSED and 24500 + 1000 would exceed the 25000
        # ceiling; the state gate must surface first.
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)

    def test_order_submit_fiscal_check_fires_when_window_open(self, api):
        """PRD §3.5: "the cumulative ceiling — the sum of `amount_cents` over
        that enrollment's still-`SUBMITTED` orders in the same window, plus the
        new amount — must not strictly exceed the plan's `ocp_max_cents`, else
        `ERR_PURCHASE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/order_submit_state_beats_fiscal
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Prio Corp", "ticker": "PRI",
                            "name": "PRI DRIP"},
            participant_email="pp@x.com")
        submit_order_ok(window["id"], enrollment["id"], participant["id"], 12000)
        submit_order_ok(window["id"], enrollment["id"], participant["id"], 12500)
        # Window stays OPEN: only the fiscal check can fail now.
        resp = submit_order(window["id"], enrollment["id"], participant["id"],
                            1000)
        validate_error(resp, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED)


class TestWindowCreateValidationPriority:
    def test_window_create_temporal_beats_constraint(self, api):
        """PRD §2.11: "A schedule-sanity failure therefore surfaces before an
        overlap failure on the same request, and a state-gate failure surfaces
        before either."

        Design: Difficulty/priority_pair_validation_conflict/window_create_temporal_beats_constraint
        """
        plan = create_active_plan(issuer_name="Time Corp", ticker="TIM",
                                  name="TIM DRIP")
        create_window(plan["id"])  # [2026-09-01, 2026-09-15), clock 2026-08-01
        resp = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-07-01T00:00:00Z",
            "closes_at": "2026-09-10T00:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        # The new window both opens in the past and overlaps the existing
        # one; the schedule-sanity failure must surface first.
        validate_error(resp, ApiErrorId.ERR_WINDOW_SCHEDULE_INVALID)

    def test_window_create_past_opening_rejected_alone(self, api):
        """PRD §3.5: "Schedule sanity: the opening instant must be strictly
        earlier than the closing instant, and the opening instant must be at or
        after the logical clock — no window may open in the past — else
        `ERR_WINDOW_SCHEDULE_INVALID` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/window_create_temporal_beats_constraint
        """
        plan = create_active_plan(issuer_name="Time Corp", ticker="TIM",
                                  name="TIM DRIP")
        # No existing windows: only the schedule-sanity check can fail.
        resp = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-07-01T00:00:00Z",
            "closes_at": "2026-08-15T00:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_WINDOW_SCHEDULE_INVALID)


class TestWindowOverlapGeometry:
    def test_window_adjacency_allowed(self, api):
        """PRD §3.5: "Window overlap: the new window's half-open interval,
        inclusive of `opens_at` and exclusive of `closes_at`, must not intersect
        any existing non-`SETTLED` window of the same plan, though back-to-back
        adjacency — one window closing exactly when the other opens — is
        allowed; violations fail with `ERR_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/window_window_half_open_adjacency
        """
        plan = create_active_plan(issuer_name="Ovl Corp", ticker="OVL",
                                  name="OVL DRIP")
        create_window(plan["id"])  # [2026-09-01, 2026-09-15)
        resp = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-09-15T00:00:00Z",
            "closes_at": "2026-09-30T00:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "SCHEDULED", (
            "opening exactly when the first window closes is allowed adjacency")

    def test_window_overlap_rejected(self, api):
        """PRD §3.5: "Window overlap: the new window's half-open interval,
        inclusive of `opens_at` and exclusive of `closes_at`, must not intersect
        any existing non-`SETTLED` window of the same plan, though back-to-back
        adjacency — one window closing exactly when the other opens — is
        allowed; violations fail with `ERR_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/window_window_half_open_adjacency
        """
        plan = create_active_plan(issuer_name="Ovl Corp", ticker="OVL",
                                  name="OVL DRIP")
        create_window(plan["id"])  # [2026-09-01, 2026-09-15)
        resp = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-09-14T00:00:00Z",
            "closes_at": "2026-09-20T00:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestWindowDividendBlackout:
    def test_window_blackout_clear_accepted_boundary_touch_rejected(self, api):
        """PRD §3.5: "Dividend blackout: the window must not intersect the
        blackout cast by any non-`SETTLED` dividend event of the same plan,
        where a blackout is the closed interval from 00:00:00 UTC two days
        before the dividend's `record_date` through 23:59:59 UTC on its
        `payable_date`, and touching either blackout boundary already counts as
        intersection — violations fail with `ERR_WINDOW_DIVIDEND_BLACKOUT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/window_dividend_blackout_closed_buffer
        """
        plan = create_active_plan(issuer_name="Blk Corp", ticker="BLK",
                                  name="BLK DRIP")
        declare_dividend(plan["id"], record_date="2026-10-10T00:00:00Z",
                         payable_date="2026-10-20T00:00:00Z")
        # Blackout is [2026-10-08T00:00:00Z, 2026-10-20T23:59:59Z].
        clear = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-09-20T00:00:00Z",
            "closes_at": "2026-10-07T23:59:59Z",
            "price_cents": 2500,
        }, ADMIN)
        window_d = validate_success(clear, expected_status=201)
        assert window_d["status"] == "SCHEDULED", \
            "ending one second before the blackout starts does not intersect it"

        touching = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-10-08T00:00:00Z",
            "closes_at": "2026-10-08T12:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        # Opening exactly at the blackout's inclusive lower bound touches it.
        validate_error(touching, ApiErrorId.ERR_WINDOW_DIVIDEND_BLACKOUT)

    def test_window_inside_blackout_rejected(self, api):
        """PRD §3.5: "Dividend blackout: the window must not intersect the
        blackout cast by any non-`SETTLED` dividend event of the same plan,
        where a blackout is the closed interval from 00:00:00 UTC two days
        before the dividend's `record_date` through 23:59:59 UTC on its
        `payable_date`, and touching either blackout boundary already counts as
        intersection — violations fail with `ERR_WINDOW_DIVIDEND_BLACKOUT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/window_dividend_blackout_closed_buffer
        """
        plan = create_active_plan(issuer_name="Blk Corp", ticker="BLK",
                                  name="BLK DRIP")
        declare_dividend(plan["id"], record_date="2026-10-10T00:00:00Z",
                         payable_date="2026-10-20T00:00:00Z")
        resp = api.create_purchase_window(plan["id"], {
            "opens_at": "2026-10-15T00:00:00Z",
            "closes_at": "2026-10-16T00:00:00Z",
            "price_cents": 2500,
        }, ADMIN)
        # A window sitting strictly inside the blackout intersects it.
        validate_error(resp, ApiErrorId.ERR_WINDOW_DIVIDEND_BLACKOUT)


class TestOrderWindowOpenGate:
    def test_order_submission_requires_window_open(self, api):
        """PRD §2.8: "Submitting or cancelling a purchase order additionally
        requires the window to be `OPEN`, failing with `ERR_WINDOW_NOT_OPEN`
        (HTTP 409) otherwise."

        Design: Difficulty/cross_entity_state_dependency/order_submission_requires_window_open
        """
        plan = create_active_plan(issuer_name="Gate Corp", ticker="GTE",
                                  name="GTE DRIP")
        participant = register_participant("Pat K", "pk@x.com")
        enrollment = create_active_enrollment(plan["id"], participant["id"])
        deposit_shares(enrollment["id"], 5.0, 1000)
        window = create_window(plan["id"])  # SCHEDULED; clock still 2026-08-01
        resp = submit_order(window["id"], enrollment["id"], participant["id"],
                            5000)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)
        assert get_window(window["id"])["submitted_total_cents"] == 0, \
            "the rejected submission reserves nothing on the window"

    def test_order_submission_succeeds_once_window_open(self, api):
        """PRD §2.8: "Submitting or cancelling a purchase order additionally
        requires the window to be `OPEN`, failing with `ERR_WINDOW_NOT_OPEN`
        (HTTP 409) otherwise."
        PRD §3.5: "A new order starts `SUBMITTED`, and its amount is added to
        the window's `submitted_total_cents`, a derived figure reconciled on
        every order mutation."

        Design: Difficulty/cross_entity_state_dependency/order_submission_requires_window_open
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Gate Corp", "ticker": "GTE",
                            "name": "GTE DRIP"},
            participant_email="pk@x.com")
        order = submit_order_ok(window["id"], enrollment["id"],
                                participant["id"], 5000)
        assert order["status"] == "SUBMITTED"
        assert get_window(window["id"])["submitted_total_cents"] == 5000


class TestOrderAmountFloor:
    def test_purchase_below_min_rejected(self, api):
        """PRD §3.5: "the amount must be at least the plan's `ocp_min_cents`,
        else `ERR_PURCHASE_BELOW_MIN` (HTTP 422)"

        Design: Corner/validations/purchase_below_min_rejected
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Min Corp", "ticker": "MIN",
                            "name": "MIN DRIP"},
            participant_email="pmn@x.com")
        resp = submit_order(window["id"], enrollment["id"], participant["id"],
                            500)
        validate_error(resp, ApiErrorId.ERR_PURCHASE_BELOW_MIN)


class TestWindowTotalReconciliation:
    def test_window_total_reconciles_on_order_cancel(self, api):
        """PRD §3.5: "A new order starts `SUBMITTED`, and its amount is added to
        the window's `submitted_total_cents`, a derived figure reconciled on
        every order mutation."
        PRD §3.5: "The owner may cancel an order while it is `SUBMITTED` and
        its window is still `OPEN`; cancellation moves it to `CANCELLED`,
        removes its amount from the window's `submitted_total_cents`, and
        increments the order's `version`."

        Design: Corner/calculations/window_total_reconciles_on_order_cancel
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Rec Corp", "ticker": "REC",
                            "name": "REC DRIP"},
            participant_email="prc@x.com")
        order = submit_order_ok(window["id"], enrollment["id"],
                                participant["id"], 12000)
        assert get_window(window["id"])["submitted_total_cents"] == 12000

        cancelled = validate_success(api.cancel_purchase_order(
            order["id"], make_participant_headers(participant["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert get_window(window["id"])["submitted_total_cents"] == 0


class TestWindowAndOrderStateGates:
    def test_window_settle_from_open_rejected(self, api):
        """PRD §3.5: "Settlement is the final step: an administrator settles a
        `CLOSED` window, moving it to `SETTLED`."
        PRD §2.8: "Any state-machine trigger attempted from a state where it is
        not defined — including any action against an entity already in a
        terminal state, or repeating a transition already taken — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/window_settle_from_open_rejected
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Win Corp", "ticker": "WIN",
                            "name": "WIN DRIP"},
            participant_email="pwin@x.com")
        resp = api.settle_purchase_window(window["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_window(window["id"])["status"] == "OPEN"

    def test_order_cancel_after_window_closed_rejected(self, api):
        """PRD §3.5: "The owner may cancel an order while it is `SUBMITTED` and
        its window is still `OPEN`"
        PRD §2.8: "Submitting or cancelling a purchase order additionally
        requires the window to be `OPEN`, failing with `ERR_WINDOW_NOT_OPEN`
        (HTTP 409) otherwise."

        Design: Corner/state_machines/order_cancel_after_window_closed_rejected
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Can Corp", "ticker": "CAN",
                            "name": "CAN DRIP"},
            participant_email="pcn@x.com")
        order = submit_order_ok(window["id"], enrollment["id"],
                                participant["id"], 12000)
        close_window_at(window["id"])
        resp = api.cancel_purchase_order(
            order["id"], make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)
        assert get_order(order["id"])["status"] == "SUBMITTED", \
            "the order stays SUBMITTED awaiting settlement"


class TestWindowOpenTiming:
    def test_window_open_before_opens_at_rejected(self, api):
        """PRD §3.5: "A `SCHEDULED` window is opened by an administrator once
        the plan is `ACTIVE` and the logical clock sits at or after `opens_at`
        but strictly before `closes_at`; an opening attempt outside that
        half-open interval fails with `ERR_WINDOW_OPEN_TOO_EARLY` (HTTP 422)."
        PRD §2.4: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."

        Design: Corner/cross_cutting_layers/window_open_before_opens_at_rejected
        """
        plan = create_active_plan(issuer_name="Clk Corp", ticker="CLK",
                                  name="CLK DRIP")
        window = create_window(plan["id"])  # opens 2026-09-01; clock 2026-08-01
        resp = api.open_purchase_window(window["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OPEN_TOO_EARLY)
        assert get_window(window["id"])["status"] == "SCHEDULED"


class TestOrderSubmissionRbac:
    def test_admin_cannot_submit_purchase_order(self, api):
        """PRD §3.5: "While a window is `OPEN`, a `Participant` submits optional
        cash purchase orders into it with a payload naming their `enrollment_id`
        and the `amount_cents` to invest."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or a `Participant`-role request that touches a resource owned by a
        different participant — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/admin_cannot_submit_purchase_order
        """
        plan, participant, enrollment, window = setup_open_window_scenario(
            plan_overrides={"issuer_name": "Adm Corp", "ticker": "ADM",
                            "name": "ADM DRIP"},
            participant_email="pad@x.com")
        resp = api.create_purchase_order(
            window["id"],
            {"enrollment_id": enrollment["id"], "amount_cents": 5000},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
