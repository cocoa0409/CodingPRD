"""Cost capture: overhead loading and its pinned rounding, rate resolution,
the variance hold and its boundaries, validation-order pairs, and reversals
(PRD §2.5, §2.8, §2.9, §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_work_order_ledger_invariants,
    close_period,
    create_cost_charge_payload,
    create_in_progress_work_order,
    create_period,
    create_program,
    create_schedule,
    create_work_order_payload,
    get_success_data,
    get_work_order,
    post_charge,
    setup_charging_world,
    setup_variance_hold_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestOverheadRounding:
    def test_overhead_per_line_rounding_order(self, api):
        """PRD §2.5: "Whenever a computation produces a fractional cent, the result is rounded half up to a whole cent — zero decimal places — and this rounding is applied per individual row before any summation, never on the aggregate. The rounding order is pinned: overhead on a charge is rounded per charge row first and only then summed into work-order totals; computing overhead on the sum of the bases is forbidden because it yields different cents. By way of example, three charge rows of 100 cents each at a two-and-a-half-percent rate accrue 3 cents of overhead apiece — 9 cents in total — whereas rounding the aggregate 7.50 cents would yield 8."

        Design: Corner/calculations/overhead_per_line_rounding_order
        """
        world = setup_charging_world(estimate_cents=9_000_000,
                                     cost_type="LABOR", rate_pct=2.5)
        wo = world["work_order"]

        first = post_charge(wo["id"], cost_type="LABOR", base_amount_cents=100,
                            charge_date="2026-08-05")
        # round_half_up(100 * 2.5 / 100) == 3 per row.
        assert first["overhead_amount_cents"] == 3
        assert first["total_cents"] == 103
        assert first["overhead_rate_pct"] == 2.5

        post_charge(wo["id"], cost_type="LABOR", base_amount_cents=100,
                    charge_date="2026-08-06")
        post_charge(wo["id"], cost_type="LABOR", base_amount_cents=100,
                    charge_date="2026-08-07")

        wo_view = get_work_order(wo["id"])
        assert wo_view["actual_direct_cents"] == 309, (
            "per-row rounding gives 3 * 103 == 309; the forbidden "
            "sum-then-round order would give 308")


class TestOverheadRateResolution:
    def test_overhead_rate_temporal_resolution_boundary(self, api):
        """PRD §3.5: "The applicable rate is the unique schedule row whose `cost_type` matches the charge, whose `order_type` equals the work order's `order_type`, and whose half-open interval covers the charge date — on or after `effective_from` and strictly before `effective_to`, or open-ended when `effective_to` is null. Because schedule creation forbids overlaps, at most one row can match; when none covers the date, the posting fails with `ERR_OVERHEAD_RATE_NOT_FOUND`."

        Design: Corner/calculations/overhead_rate_temporal_resolution_boundary
        """
        program = create_program(code="CAP-RATE")
        create_schedule(cost_type="LABOR", order_type="CAPITAL", rate_pct=15.0,
                        effective_from="2026-01-01", effective_to="2026-07-01")
        create_schedule(cost_type="LABOR", order_type="CAPITAL", rate_pct=16.0,
                        effective_from="2026-07-01")
        period6 = create_period(fiscal_year=2026, period_no=6,
                                start_date="2026-06-01", end_date="2026-06-30")
        wo = create_in_progress_work_order(program["id"],
                                           initial_estimated_cost_cents=9_000_000)

        june = post_charge(wo["id"], cost_type="LABOR", base_amount_cents=10_000,
                           charge_date="2026-06-15")
        assert june["overhead_rate_pct"] == 15.0
        assert june["total_cents"] == 11_500
        assert june["accounting_period_id"] == period6["id"]

        close_period(period6["id"])
        period7 = create_period(fiscal_year=2026, period_no=7,
                                start_date="2026-07-01", end_date="2026-07-31")

        # The boundary date belongs to the second row: effective_to is exclusive.
        july = post_charge(wo["id"], cost_type="LABOR", base_amount_cents=10_000,
                           charge_date="2026-07-01")
        assert july["overhead_rate_pct"] == 16.0
        assert july["total_cents"] == 11_600
        assert july["accounting_period_id"] == period7["id"]

        # No EQUIPMENT schedule covers the date at all.
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "EQUIPMENT",
             "base_amount_cents": 10_000, "charge_date": "2026-07-02"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_OVERHEAD_RATE_NOT_FOUND, 422)


class TestImmediateConsistency:
    def test_immediate_visibility_of_computed_fields(self, api):
        """PRD §2.10: "Every derived balance named in this document — a program's committed, capitalized, written-off, and contra amounts, a work order's actuals, AFUDC total, and CWIP balance, a unit's accumulated depreciation, a regulatory asset's remaining balance — is recomputed immediately inside the request that triggered the change, and all cascaded side effects of a single request apply atomically: the request either lands with every cascade complete or is rejected with nothing persisted."
        PRD §3.5: "The resolved rate is pinned onto the charge as `overhead_rate_pct`; the `overhead_amount_cents` is the base multiplied by that rate and divided by one hundred, rounded half up to a whole cent per the pinned per-row rounding of §2.5; and the `total_cents` is the base plus the overhead."

        Design: Corner/consistency_model/immediate_visibility_of_computed_fields
        """
        world = setup_charging_world(estimate_cents=500_000, cost_type="LABOR",
                                     rate_pct=10.0)
        wo = world["work_order"]

        charge = post_charge(wo["id"], cost_type="LABOR", base_amount_cents=10_000,
                             charge_date="2026-08-10")
        assert charge["overhead_amount_cents"] == 1_000
        assert charge["total_cents"] == 11_000

        wo_view = get_work_order(wo["id"])
        assert wo_view["actual_direct_cents"] == 11_000
        assert wo_view["cwip_cents"] == 11_000
        assert_work_order_ledger_invariants(wo_view)


class TestVarianceThresholdBoundary:
    def test_variance_exactly_110_percent_stays_within_tolerance(self, api):
        """PRD §3.5: "The `variance_posture` is then re-derived from the new actuals: while no estimate is approved it stays `WITHIN_TOLERANCE`; once an `approved_estimate_cents` exists, actuals scaled by one hundred strictly greater than the approved estimate scaled by one hundred ten flips the posture to `RE_ESTIMATE_REQUIRED`, while exactly 110.00% remains within tolerance."

        Design: Difficulty/boundary_precision_check/variance_threshold_exact_110_percent
        """
        world = setup_charging_world(estimate_cents=10_000)
        wo = world["work_order"]

        # Exactly 110.00% of the 10,000c approved estimate.
        charge = post_charge(wo["id"], base_amount_cents=11_000,
                             charge_date="2026-08-05")
        assert charge["total_cents"] == 11_000

        wo_view = get_work_order(wo["id"])
        assert wo_view["actual_direct_cents"] == 11_000
        assert wo_view["variance_posture"] == "WITHIN_TOLERANCE", (
            "the rule is strictly-greater: exactly 110.00% stays within tolerance")

    def test_variance_one_cent_over_flips_posture_and_blocks_next(self, api):
        """PRD §3.5: "The `variance_posture` is then re-derived from the new actuals: while no estimate is approved it stays `WITHIN_TOLERANCE`; once an `approved_estimate_cents` exists, actuals scaled by one hundred strictly greater than the approved estimate scaled by one hundred ten flips the posture to `RE_ESTIMATE_REQUIRED`, while exactly 110.00% remains within tolerance. While the posture stands at `RE_ESTIMATE_REQUIRED`, any further charge posting is rejected with `ERR_VARIANCE_HOLD` (HTTP 409) — though the charge that itself crosses the threshold is allowed to post, flipping the posture only for the next charge — and the hold clears when an approved re-estimate or a reversal brings the comparison back within bound."

        Design: Difficulty/boundary_precision_check/variance_threshold_exact_110_percent
        """
        world = setup_charging_world(estimate_cents=10_000)
        wo = world["work_order"]

        post_charge(wo["id"], base_amount_cents=11_000, charge_date="2026-08-05")
        # The 1-cent crossing charge is itself allowed to post.
        crossing = post_charge(wo["id"], base_amount_cents=1,
                               charge_date="2026-08-06")
        assert crossing["total_cents"] == 1

        wo_view = get_work_order(wo["id"])
        assert wo_view["actual_direct_cents"] == 11_001
        assert wo_view["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        # The NEXT charge is blocked by the hold.
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 1, "charge_date": "2026-08-07"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_HOLD, 409)


class TestValidationOrderPairs:
    def test_charge_on_completed_order_reports_state_error(self, api):
        """PRD §3.5: "Following the §2.8 order, a posting that would fail several of these guards reports the state error first, then the temporal period errors, then the missing overhead rate, and the variance hold last."
        PRD §3.7: "Completion freezes the ledger going forward: any further charge posting against the order is rejected with `ERR_INVALID_STATE`, and AFUDC stops accruing for the order at the in-service date — subsequent period closes produce no further AFUDC entries for it."

        Design: Difficulty/priority_pair_validation_conflict/charge_state_error_beats_variance_hold
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        wo = world["work_order"]
        completed = get_success_data(
            api.complete_work_order(wo["id"], "2026-08-20", SUPERVISOR))
        assert completed["status"] == "COMPLETED"
        # Completion does not re-derive the variance posture: neither actuals
        # nor the approved estimate changed, so the hold persists.
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 100, "charge_date": "2026-08-21"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_variance_hold_fires_when_state_is_legal(self, api):
        """PRD §3.5: "Following the §2.8 order, a posting that would fail several of these guards reports the state error first, then the temporal period errors, then the missing overhead rate, and the variance hold last."
        PRD §3.5: "While the posture stands at `RE_ESTIMATE_REQUIRED`, any further charge posting is rejected with `ERR_VARIANCE_HOLD` (HTTP 409) — though the charge that itself crosses the threshold is allowed to post, flipping the posture only for the next charge — and the hold clears when an approved re-estimate or a reversal brings the comparison back within bound."

        Design: Difficulty/priority_pair_validation_conflict/charge_state_error_beats_variance_hold
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        wo = world["work_order"]
        # The order stays IN_PROGRESS (state-legal), the date is inside the
        # OPEN period, and a 0% MATERIAL rate resolves — so the variance hold
        # is the only failing guard and must surface.
        assert get_work_order(wo["id"])["status"] == "IN_PROGRESS"
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 100, "charge_date": "2026-08-21"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_HOLD, 409)

    def test_charge_in_closed_period_reports_temporal_error(self, api):
        """PRD §3.5: "Following the §2.8 order, a posting that would fail several of these guards reports the state error first, then the temporal period errors, then the missing overhead rate, and the variance hold last."
        PRD §3.5: "The `charge_date` must fall inside an existing accounting period, else `ERR_PERIOD_NOT_FOUND`, and that period must currently be `OPEN` or `REOPENED`, else `ERR_PERIOD_CLOSED`; the containing period's id is then recorded on the row as `accounting_period_id`."

        Design: Difficulty/priority_pair_validation_conflict/charge_period_error_beats_variance_hold
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        wo, period = world["work_order"], world["period"]
        close_period(period["id"])
        create_period(fiscal_year=2026, period_no=9, start_date="2026-09-01",
                      end_date="2026-09-30")
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        # The date falls in the now-CLOSED 2026-08 period; the temporal error
        # must win over the variance hold.
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 100, "charge_date": "2026-08-15"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 422)

    def test_variance_hold_fires_when_period_is_open(self, api):
        """PRD §3.5: "Following the §2.8 order, a posting that would fail several of these guards reports the state error first, then the temporal period errors, then the missing overhead rate, and the variance hold last."
        PRD §3.5: "While the posture stands at `RE_ESTIMATE_REQUIRED`, any further charge posting is rejected with `ERR_VARIANCE_HOLD` (HTTP 409) — though the charge that itself crosses the threshold is allowed to post, flipping the posture only for the next charge — and the hold clears when an approved re-estimate or a reversal brings the comparison back within bound."

        Design: Difficulty/priority_pair_validation_conflict/charge_period_error_beats_variance_hold
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        wo, period = world["work_order"], world["period"]
        close_period(period["id"])
        create_period(fiscal_year=2026, period_no=9,
                      start_date="2026-09-01", end_date="2026-09-30")
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        # Dated inside the OPEN 2026-09 period, temporal checks pass and the
        # fiscal hold fires.
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 100, "charge_date": "2026-09-02"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_HOLD, 409)


class TestChargePeriodGating:
    def test_charge_rejected_when_covering_period_closed(self, api):
        """PRD §3.5: "The `charge_date` must fall inside an existing accounting period, else `ERR_PERIOD_NOT_FOUND`, and that period must currently be `OPEN` or `REOPENED`, else `ERR_PERIOD_CLOSED`; the containing period's id is then recorded on the row as `accounting_period_id`."

        Design: Difficulty/cross_entity_state_dependency/charge_posting_gated_by_period_state
        """
        world = setup_charging_world(estimate_cents=9_000_000)
        wo, period = world["work_order"], world["period"]

        charge = post_charge(wo["id"], base_amount_cents=5_000,
                             charge_date="2026-08-10")
        assert charge["accounting_period_id"] == period["id"]

        close_period(period["id"])

        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 7_000, "charge_date": "2026-08-20"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 422)

    def test_charge_resolves_into_new_open_period(self, api):
        """PRD §3.5: "The `charge_date` must fall inside an existing accounting period, else `ERR_PERIOD_NOT_FOUND`, and that period must currently be `OPEN` or `REOPENED`, else `ERR_PERIOD_CLOSED`; the containing period's id is then recorded on the row as `accounting_period_id`."
        PRD §3.2: "The single currently open period is the only container that accepts new charge postings, in-service declarations, and retirements, and it is the period whose close advances the accounting epoch."

        Design: Difficulty/cross_entity_state_dependency/charge_posting_gated_by_period_state
        """
        world = setup_charging_world(estimate_cents=9_000_000)
        wo, period = world["work_order"], world["period"]
        close_period(period["id"])
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")

        charge = post_charge(wo["id"], base_amount_cents=7_000,
                             charge_date="2026-09-02")
        assert charge["accounting_period_id"] == period9["id"]


class TestChargeReferences:
    def test_body_fk_existence_and_charge_date_without_period(self, api):
        """PRD §2.9: "Existence is validated in a strict left-to-right order: every identifier appearing in the path is resolved first — `program_id`, `catalog_id`, `schedule_id`, `period_id`, `work_order_id`, `estimate_id`, `charge_id`, `ciac_id`, `unit_id`, `reg_asset_id`, `entry_id` — and only then are the body's foreign-key references checked, such as `program_id` on work-order creation, `work_order_id` on estimate, charge, and CIAC creation, each `unit_catalog_id` inside a closeout's `unitization_lines`, and `source_work_order_id` on a regulatory-asset proposal. The first identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and no later reference is examined."
        PRD §3.5: "The `charge_date` must fall inside an existing accounting period, else `ERR_PERIOD_NOT_FOUND`, and that period must currently be `OPEN` or `REOPENED`, else `ERR_PERIOD_CLOSED`; the containing period's id is then recorded on the row as `accounting_period_id`."

        Design: Corner/validations/body_fk_existence_and_charge_date_without_period
        """
        world = setup_charging_world(estimate_cents=9_000_000)
        wo = world["work_order"]

        resp = api.create_work_order(
            create_work_order_payload(program_id=NON_EXISTENT_UUID,
                                      title="Ghost program",
                                      initial_estimated_cost_cents=1_000),
            ENGINEER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

        resp2 = api.create_cost_charge(
            create_cost_charge_payload(work_order_id=NON_EXISTENT_UUID,
                                       base_amount_cents=1_000,
                                       charge_date="2026-08-10"), CLERK)
        validate_error(resp2, ApiErrorId.ERR_NOT_FOUND, 404)

        # 2027-05-05 falls inside no existing accounting period.
        resp3 = api.create_cost_charge(
            create_cost_charge_payload(work_order_id=wo["id"],
                                       base_amount_cents=1_000,
                                       charge_date="2027-05-05"), CLERK)
        validate_error(resp3, ApiErrorId.ERR_PERIOD_NOT_FOUND, 422)


class TestReversal:
    def test_charge_reversal_state_errors(self, api):
        """PRD §3.5: "A `FieldClerk` reverses a charge only while it is a `POSTED` row of `kind` `ORIGINAL`: attempting to reverse a `REVERSAL` row is rejected with `ERR_REVERSAL_NOT_ALLOWED`, and reversing an original already in `REVERSED` is `ERR_CHARGE_ALREADY_REVERSED`."

        Design: Corner/state_machines/charge_reversal_state_errors
        """
        world = setup_charging_world(estimate_cents=500_000)
        wo = world["work_order"]
        charge = post_charge(wo["id"], base_amount_cents=30_000,
                             charge_date="2026-08-10")
        reversal = get_success_data(api.reverse_cost_charge(charge["id"], CLERK))
        assert reversal["kind"] == "REVERSAL"

        # The original is already REVERSED.
        resp = api.reverse_cost_charge(charge["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CHARGE_ALREADY_REVERSED, 409)

        # A REVERSAL row can never itself be reversed.
        resp2 = api.reverse_cost_charge(reversal["id"], CLERK)
        validate_error(resp2, ApiErrorId.ERR_REVERSAL_NOT_ALLOWED, 409)

    def test_reversal_posts_to_current_open_period(self, api):
        """PRD §3.5: "An accounting period must currently stand `OPEN` or `REOPENED` to receive the reversal row, else `ERR_PERIOD_NOT_FOUND`."
        PRD §3.5: "The reversal itself is a brand-new charge row, created with `kind` `REVERSAL`, its `reverses_charge_id` pointing at the reversed original, its base, overhead, and total amounts exactly negated, and its `charge_date` stamped with the current logical-clock date as an informational marker; as a prior-period adjustment, its `accounting_period_id` is the single currently `OPEN` or `REOPENED` period regardless of that clock date, because the clock date never re-enters a `CLOSED` period."

        Design: Corner/endpoints/reversal_posts_to_current_open_period
        """
        world = setup_charging_world(estimate_cents=500_000)
        wo, period = world["work_order"], world["period"]
        charge = post_charge(wo["id"], base_amount_cents=30_000,
                             charge_date="2026-08-10")
        close_period(period["id"])

        # No OPEN or REOPENED period exists to receive the reversal row.
        resp = api.reverse_cost_charge(charge["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_FOUND, 422)

        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        reversal = validate_success(api.reverse_cost_charge(charge["id"], CLERK), 201)
        assert reversal["accounting_period_id"] == period9["id"], (
            "the reversal posts into the current OPEN period, never back into "
            "the CLOSED one")
        assert reversal["total_cents"] == -30_000

    def test_reversal_row_shape_and_linkage(self, api):
        """PRD §3.5: "The reversal itself is a brand-new charge row, created with `kind` `REVERSAL`, its `reverses_charge_id` pointing at the reversed original, its base, overhead, and total amounts exactly negated, and its `charge_date` stamped with the current logical-clock date as an informational marker; as a prior-period adjustment, its `accounting_period_id` is the single currently `OPEN` or `REOPENED` period regardless of that clock date, because the clock date never re-enters a `CLOSED` period. The original flips `POSTED` → `REVERSED`, while reversal rows stay `POSTED` forever and can never themselves be reversed."

        Design: Difficulty/compensating_invariant/charge_reversal_conserves_cwip
        """
        world = setup_charging_world(estimate_cents=500_000)
        wo, period = world["work_order"], world["period"]
        charge = post_charge(wo["id"], base_amount_cents=30_000,
                             charge_date="2026-08-10")

        reversal = validate_success(api.reverse_cost_charge(charge["id"], CLERK), 201)
        assert reversal["kind"] == "REVERSAL"
        assert reversal["reverses_charge_id"] == charge["id"]
        assert reversal["base_amount_cents"] == -30_000
        assert reversal["overhead_amount_cents"] == 0
        assert reversal["total_cents"] == -30_000
        assert reversal["accounting_period_id"] == period["id"]
        assert reversal["status"] == "POSTED"

        original = validate_success(api.get_cost_charge(charge["id"], AUDITOR))
        assert original["status"] == "REVERSED"

    def test_reversal_restores_cwip_invariant(self, api):
        """PRD §3.5: "The pair nets to zero, so the order's `actual_direct_cents` and `cwip_cents` return to their pre-charge values — posting a charge and then reversing it leaves the ledger identical to its state before the posting — and the `variance_posture` is recomputed, which may clear a `RE_ESTIMATE_REQUIRED` hold."
        PRD §3.5: "The `actual_direct_cents` is the sum of `total_cents` over all of the order's charge rows, in both kinds — an `ORIGINAL` row remains in the sum even after it flips to `REVERSED`, because its compensating `REVERSAL` row carries the exact negation — and it excludes AFUDC entirely, making it the variance base."

        Design: Difficulty/compensating_invariant/charge_reversal_conserves_cwip
        """
        world = setup_charging_world(estimate_cents=500_000)
        wo = world["work_order"]

        before = get_work_order(wo["id"])
        assert before["actual_direct_cents"] == 0
        assert before["cwip_cents"] == 0

        charge = post_charge(wo["id"], base_amount_cents=30_000,
                             charge_date="2026-08-10")
        mid = get_work_order(wo["id"])
        assert mid["actual_direct_cents"] == 30_000
        assert mid["cwip_cents"] == 30_000

        get_success_data(api.reverse_cost_charge(charge["id"], CLERK))
        after = get_work_order(wo["id"])
        assert after["actual_direct_cents"] == before["actual_direct_cents"] == 0
        assert after["cwip_cents"] == before["cwip_cents"] == 0
        assert_work_order_ledger_invariants(after)
