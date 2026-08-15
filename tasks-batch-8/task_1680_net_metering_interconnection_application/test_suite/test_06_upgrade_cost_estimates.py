"""Upgrade cost estimates: totals, issuance, customer decision, OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    api_client,
    assert_instant_equal,
    create_cost_estimate_payload,
    drive_to_awaiting_cost_estimate,
    drive_to_customer_decision_pending,
    get_application,
    get_success_data,
    issue_estimate,
    set_clock,
    setup_program_with_grid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
ENGINEER = TEST_USERS["engineer_headers"]

# Grid geometry that fails the strict feeder screen for a 20 kW design
# (140,000 + 20,000 = 160,000 >= 150,000) while leaving the class cap and the
# production ratio green.
FAILING_FEEDER = {"peak_load_watts": 1_000_000, "pre_existing_der_watts":
                  140_000}


def _decision_pending_scenario(name, items=None, contingency_pct=10):
    sc = setup_program_with_grid(name, feeder_overrides=FAILING_FEEDER)
    ctx = add_customer_account(sc, "1", prior_annual_usage_wh=100_000_000)
    app, review, estimate = drive_to_customer_decision_pending(
        sc, ctx, size=20_000, production=30_000_000, items=items,
        contingency_pct=contingency_pct)
    return sc, ctx, app, review, estimate


class TestEstimateTotal:
    def test_total_rounds_once_after_contingency(self, api):
        """PRD §3.5: "The estimate's `total_cents` is the sum of the line
        amounts, scaled by one plus the contingency percentage — that is, the
        subtotal multiplied by (100 + `contingency_pct`) and divided by 100 —
        with a single round-half-up to whole cents applied only at the end.
        Issuance stamps `valid_until` thirty days out, marks the estimate
        `ISSUED`, supersedes any currently `ISSUED` estimate for the same
        application (moving it to `SUPERSEDED`), moves the application from
        `AWAITING_COST_ESTIMATE` to `CUSTOMER_DECISION_PENDING`, and increments
        the application's `version` by one."

        Design: Corner/calculations/c_estimate_total_single_rounding
        """
        sc = setup_program_with_grid("EST", feeder_overrides=FAILING_FEEDER)
        ctx = add_customer_account(sc, "1",
                                   prior_annual_usage_wh=100_000_000)
        app, _report, review = drive_to_awaiting_cost_estimate(
            sc, ctx, size=20_000, production=30_000_000)
        # 99,999 * 115 / 100 = 114,998.85 -> a single round-half-up at the end
        # yields 114,999 (rounding each item first would not produce this).
        estimate, app = issue_estimate(
            sc, app, review,
            items=[{"description": "transformer", "amount_cents": 50_000},
                   {"description": "pole work", "amount_cents": 49_999}],
            contingency_pct=15)

        assert estimate["total_cents"] == 114_999
        assert_instant_equal(estimate["valid_until"], "2026-08-31T00:00:00Z",
                             "issued at the 2026-08-01 default clock + 30 days")
        assert estimate["estimate_status"] == "ISSUED"
        assert app["application_status"] == "CUSTOMER_DECISION_PENDING"


class TestEstimateDecision:
    def test_decline_is_terminal_for_the_estimate(self, api):
        """PRD §3.5: "Accepting is allowed only while the estimate is still
        `ISSUED` — attempting to accept or decline an estimate in any other
        status is rejected with `ERR_ESTIMATE_NOT_ISSUED`"
        PRD §3.5: "Declining records `decided_at`, moves the estimate to
        `DECLINED`, and withdraws the application with `withdrawal_reason`
        `CUSTOMER_DECLINED`, triggering the full release cascade of §3.6."

        Design: Corner/state_machines/sm_estimate_decline_is_terminal_for_estimate
        """
        sc, ctx, app, _review, estimate = _decision_pending_scenario("ED")

        estimate = validate_success(
            api.decline_cost_estimate(estimate["id"], ctx["applicant"]))
        assert estimate["estimate_status"] == "DECLINED"
        assert estimate["decided_at"] is not None
        app = get_application(app["id"])
        assert app["application_status"] == "WITHDRAWN"
        assert app["withdrawal_reason"] == "CUSTOMER_DECLINED"

        resp = api.accept_cost_estimate(estimate["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_ISSUED, 409)

    def test_accept_after_valid_until_rejected_lazily(self, api):
        """PRD §3.5: "an accept attempted after that instant, while the
        estimate still shows `ISSUED` because the sweep has not run, is
        rejected with `ERR_ESTIMATE_EXPIRED`."

        Design: Corner/validations/v_estimate_accept_after_valid_until_expires
        """
        sc, ctx, app, _review, estimate = _decision_pending_scenario("EX")
        # Issued at the default clock 2026-08-01T00:00:00Z; valid_until
        # 2026-08-31T00:00:00Z. One second past it, with no sweep run.
        set_clock("2026-08-31T00:00:01Z")
        resp = api.accept_cost_estimate(estimate["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_EXPIRED, 422)
        estimate_after = validate_success(
            api.get_cost_estimate(estimate["id"], ADMIN))
        assert estimate_after["estimate_status"] == "ISSUED", (
            "expiry is lazy until the sweep runs")

    def test_accept_at_valid_until_succeeds(self, api):
        """PRD §3.5: "Accepting is allowed only while the estimate is still
        `ISSUED` — attempting to accept or decline an estimate in any other
        status is rejected with `ERR_ESTIMATE_NOT_ISSUED` — and only on or
        before `valid_until`"
        PRD §3.5: "Acceptance records `decided_at`, moves the estimate to
        `ACCEPTED`, and moves the application to `UPGRADE_IN_PROGRESS`."

        Design: Corner/validations/v_estimate_accept_at_valid_until_succeeds
        """
        sc, ctx, app, _review, estimate = _decision_pending_scenario("EA")
        set_clock("2026-08-31T00:00:00Z")  # exactly valid_until: inclusive
        estimate = validate_success(
            api.accept_cost_estimate(estimate["id"], ctx["applicant"]))
        assert estimate["estimate_status"] == "ACCEPTED"
        assert_instant_equal(estimate["decided_at"], "2026-08-31T00:00:00Z",
                             "decided_at stamped with the logical clock")
        assert (get_application(app["id"])["application_status"]
                == "UPGRADE_IN_PROGRESS")


class TestMarkWorkComplete:
    def test_work_complete_returns_application_to_screen_passed(self, api):
        """PRD §3.5: "Once upgrade construction finishes, the engineer marks
        the work complete: the `ACCEPTED` estimate moves to `WORK_COMPLETE` and
        the application returns to `SCREEN_PASSED`, ready for final inspection
        and energization."

        Design: Corner/endpoints/ep_mark_work_complete_returns_screen_passed
        """
        sc, ctx, app, _review, estimate = _decision_pending_scenario("MW")
        estimate = validate_success(
            api.accept_cost_estimate(estimate["id"], ctx["applicant"]))
        assert estimate["estimate_status"] == "ACCEPTED"

        estimate = validate_success(
            api.mark_work_complete(estimate["id"], ENGINEER))
        assert estimate["estimate_status"] == "WORK_COMPLETE"
        assert (get_application(app["id"])["application_status"]
                == "SCREEN_PASSED")


class TestEstimateOptimisticConcurrency:
    def test_stale_application_version_rejected(self, api):
        """PRD §2.9: "Issuing an upgrade cost estimate requires the request to
        carry `expected_application_version`, holding the `version` of the
        target application as the client last observed it. If the application's
        current `version` has advanced beyond that value, the create is
        rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."
        PRD §3.5: "a further issuance while the customer is deciding keeps the
        application in `CUSTOMER_DECISION_PENDING` with the same supersession
        cascade."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_estimate_stale_version_rejected
        """
        sc = setup_program_with_grid("OC1", feeder_overrides=FAILING_FEEDER)
        ctx = add_customer_account(sc, "1",
                                   prior_annual_usage_wh=100_000_000)
        app, _report, review = drive_to_awaiting_cost_estimate(
            sc, ctx, size=20_000, production=30_000_000)
        stale_version = get_application(app["id"])["version"]

        est1 = validate_success(api.create_cost_estimate(
            create_cost_estimate_payload(
                app["id"], review["id"], stale_version,
                items=[{"description": "first", "amount_cents": 50_000}],
                contingency_pct=10), ENGINEER), 201)

        # The first issuance bumped the application version; replaying the
        # captured version is stale.
        resp = api.create_cost_estimate(
            create_cost_estimate_payload(
                app["id"], review["id"], stale_version,
                items=[{"description": "stale", "amount_cents": 60_000}],
                contingency_pct=10), ENGINEER)
        validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION, 412)

        fresh_version = get_application(app["id"])["version"]
        est3 = validate_success(api.create_cost_estimate(
            create_cost_estimate_payload(
                app["id"], review["id"], fresh_version,
                items=[{"description": "fresh", "amount_cents": 70_000}],
                contingency_pct=10), ENGINEER), 201)

        est1_after = validate_success(api.get_cost_estimate(est1["id"], ADMIN))
        assert est1_after["estimate_status"] == "SUPERSEDED"
        assert est3["estimate_status"] == "ISSUED"
        assert est3["total_cents"] == 77_000  # 70,000 * 110 / 100

        data, meta = validate_paginated(api.list_cost_estimates(
            ADMIN, params={"application_id": app["id"]}))
        assert meta["total_count"] == 2, "the rejected 412 created nothing"
