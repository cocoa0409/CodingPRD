"""Laboratory workflow: per-line fee rounding, aggregate in-test capacity,
the capped rerun loop, custody gating, USCS classification, append-only
results, and sample interval validation."""
import pytest

from test_helpers import (
    FG,
    LM,
    LT,
    ApiErrorId,
    api_client,
    accept_lab_order,
    authorize_lab_order,
    create_lab_order,
    create_sample,
    get_success_data,
    reject_lab_order,
    run_order_to_accepted,
    setup_accepted_uc_order,
    setup_drilled_boring,
    setup_lab_received_sample,
    start_lab_order,
    submit_lab_result,
    transition_lab_order,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Per-line fee rounding (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestLabInvoicePerLineRoundingPinned:
    """Each order line rounds half-up to whole cents FIRST; only then are
    lines summed into the project's testing invoice."""

    def _two_rush_moisture_orders(self, api):
        ctx = setup_lab_received_sample()
        o1 = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                              test_type="MOISTURE_CONTENT", priority="RUSH")
        o2 = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                              test_type="MOISTURE_CONTENT", priority="RUSH")
        return ctx, o1, o2

    def test_rush_moisture_line_fee_rounded_per_line(self, api):
        """PRD section 3.4: "Every order carries a `fee_cents` computed at
        creation: the base fee for its `test_type` — 4,533 cents for
        `MOISTURE_CONTENT`, 24,500 for `ATTERBERG`, 18,500 for
        `SIEVE_ANALYSIS`, 32,000 for `UNCONFINED_COMPRESSION`, 55,000 for
        `DIRECT_SHEAR`, 88,000 for `CONSOLIDATION`, 21,000 for `PROCTOR` —
        multiplied by 1.5 when `priority` is `RUSH` and by 1.0 otherwise,
        rounded half-up to whole cents per order line with a half-cent
        rounding away from zero. The rounding order is pinned: each line is
        rounded first and only then summed."

        Design: Difficulty/combinatorial_formula/lab_invoice_per_line_rounding_pinned
        """
        _ctx, o1, o2 = self._two_rush_moisture_orders(api)
        # round_half_up(4533 * 1.5) = round_half_up(6799.5) = 6800 per line.
        assert o1["fee_cents"] == 6800
        assert o2["fee_cents"] == 6800

    def test_invoice_total_sums_per_line_rounded_fees(self, api):
        """PRD section 3.4: "Summing unrounded products and rounding once is
        forbidden and yields a different total — two rush moisture-content
        orders must total 13,600 cents (two lines of 6,800), not 13,599. The
        project's `testing_invoice_cents` is the sum of `fee_cents` over all
        of the project's orders in any status: fees accrue at order time and
        rejected reruns are never refunded."

        Design: Difficulty/combinatorial_formula/lab_invoice_per_line_rounding_pinned
        """
        ctx, _o1, _o2 = self._two_rush_moisture_orders(api)
        project = get_success_data(api.get_project(ctx["project"]["id"], LM))
        assert project["testing_invoice_cents"] == 13600, (
            f"Per-line rounding pins 2 * 6800 = 13600; sum-then-round would "
            f"yield 13599 — got {project['testing_invoice_cents']}"
        )


# ---------------------------------------------------------------------------
# Aggregate in-test capacity (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestLabInTestAggregateCapacity:
    """At most six orders may stand in IN_TEST at once, in aggregate."""

    def _seven_authorized_orders(self, api):
        ctx = setup_lab_received_sample()
        orders = [
            create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                             test_type="MOISTURE_CONTENT")
            for _ in range(7)
        ]
        for order in orders:
            authorize_lab_order(order["id"])
        for order in orders[:6]:
            start_lab_order(order["id"])
        return ctx, orders

    def test_seventh_in_test_start_rejected(self, api):
        """PRD section 3.4: "A `LabTechnician` starts the test (`AUTHORIZED`
        → `IN_TEST`) only while fewer than six orders across the laboratory
        stand in `IN_TEST` — an aggregate capacity cap, not an interval check
        — otherwise `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/lab_in_test_aggregate_capacity
        """
        _ctx, orders = self._seven_authorized_orders(api)
        resp = api.transition_lab_test_order(orders[6]["id"], {"to": "IN_TEST"}, LT)
        validate_error(resp, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED)

    def test_capacity_frees_when_result_submitted(self, api):
        """PRD section 3.4: "A `LabTechnician` starts the test (`AUTHORIZED`
        → `IN_TEST`) only while fewer than six orders across the laboratory
        stand in `IN_TEST` — an aggregate capacity cap, not an interval check
        — otherwise `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409). Result submission
        by a `LabTechnician` creates a LabTestResult against the order,
        records the caller's `X-User-ID` as `submitted_by_user_id`, and moves
        the order from `IN_TEST` to `RESULT_SUBMITTED`".

        Design: Difficulty/resource_temporal_overlap/lab_in_test_aggregate_capacity
        """
        _ctx, orders = self._seven_authorized_orders(api)
        submit_lab_result(orders[0]["id"], moisture_content_pct=22.5)

        started = transition_lab_order(orders[6]["id"], "IN_TEST", LT)
        assert started["status"] == "IN_TEST", (
            "With one order out of IN_TEST the seventh start must succeed"
        )


# ---------------------------------------------------------------------------
# Rerun loop with hard cap (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestLabOrderRerunCycleCapped:
    """RESULT_SUBMITTED -> REJECTED -> IN_TEST loops with rerun_count
    increments, capped at 2."""

    def _submitted_order(self, api):
        ctx = setup_lab_received_sample()
        order = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                                 test_type="MOISTURE_CONTENT")
        authorize_lab_order(order["id"])
        start_lab_order(order["id"])
        submit_lab_result(order["id"], moisture_content_pct=22.5)
        return ctx, order

    def test_rerun_count_increments_on_each_reentry(self, api):
        """PRD section 3.4: "a `LabTechnician` may return a rejected order to
        `IN_TEST` while `rerun_count` remains below its cap of 2 and the
        laboratory capacity check passes (`ERR_RERUN_LIMIT`, HTTP 409, at the
        cap; `ERR_LAB_CAPACITY_EXCEEDED` when full), and each rerun increments
        `rerun_count` by 1 from its initial 0."

        Design: Difficulty/non_linear_state_machine/lab_order_rerun_cycle_capped
        """
        _ctx, order = self._submitted_order(api)
        reject_lab_order(order["id"])
        first = transition_lab_order(order["id"], "IN_TEST", LT)
        assert first["rerun_count"] == 1

        submit_lab_result(order["id"], moisture_content_pct=22.7)
        reject_lab_order(order["id"])
        second = transition_lab_order(order["id"], "IN_TEST", LT)
        assert second["rerun_count"] == 2

    def test_third_rerun_rejected_at_cap(self, api):
        """PRD section 3.4: "a `LabTechnician` may return a rejected order to
        `IN_TEST` while `rerun_count` remains below its cap of 2 and the
        laboratory capacity check passes (`ERR_RERUN_LIMIT`, HTTP 409, at the
        cap; `ERR_LAB_CAPACITY_EXCEEDED` when full), and each rerun increments
        `rerun_count` by 1 from its initial 0."

        Design: Difficulty/non_linear_state_machine/lab_order_rerun_cycle_capped
        """
        _ctx, order = self._submitted_order(api)
        for moisture in (22.6, 22.7):
            reject_lab_order(order["id"])
            transition_lab_order(order["id"], "IN_TEST", LT)
            submit_lab_result(order["id"], moisture_content_pct=moisture)
        final = reject_lab_order(order["id"])
        assert final["status"] == "REJECTED"
        assert final["rerun_count"] == 2

        resp = api.transition_lab_test_order(order["id"], {"to": "IN_TEST"}, LT)
        validate_error(resp, ApiErrorId.ERR_RERUN_LIMIT)

        reread = get_success_data(api.get_lab_test_order(order["id"], LM))
        assert reread["status"] == "REJECTED"
        assert reread["rerun_count"] == 2


# ---------------------------------------------------------------------------
# Custody gating on authorization (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestOrderAuthorizeRequiresSampleInLab:
    """REQUESTED -> AUTHORIZED requires the sample's custody LAB_RECEIVED."""

    def test_authorize_with_sample_collected_rejected(self, api):
        """PRD section 3.4: "A `LabManager` authorizes an order (`REQUESTED`
        → `AUTHORIZED`) only while its sample's custody is `LAB_RECEIVED`
        (`ERR_SAMPLE_NOT_IN_LAB`, HTTP 409, otherwise)."

        Design: Difficulty/cross_entity_state_dependency/order_authorize_requires_sample_in_lab
        """
        ctx = setup_drilled_boring()
        sample = create_sample(ctx["boring"]["id"])  # stays COLLECTED
        order = create_lab_order(ctx["project"]["id"], sample["id"],
                                 test_type="MOISTURE_CONTENT")

        resp = api.transition_lab_test_order(order["id"], {"to": "AUTHORIZED"}, LM)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_IN_LAB)

    def test_authorize_with_sample_in_transit_rejected(self, api):
        """PRD section 3.4: "A `LabManager` authorizes an order (`REQUESTED`
        → `AUTHORIZED`) only while its sample's custody is `LAB_RECEIVED`
        (`ERR_SAMPLE_NOT_IN_LAB`, HTTP 409, otherwise)." and "The
        `FieldGeologist` ships the sample (`COLLECTED` → `IN_TRANSIT`); a
        `LabTechnician` receives it (`IN_TRANSIT` → `LAB_RECEIVED`)".

        Design: Difficulty/cross_entity_state_dependency/order_authorize_requires_sample_in_lab
        """
        from test_helpers import transition_sample
        ctx = setup_drilled_boring()
        sample = create_sample(ctx["boring"]["id"])
        transition_sample(sample["id"], "IN_TRANSIT", FG)  # shipped, not received
        order = create_lab_order(ctx["project"]["id"], sample["id"],
                                 test_type="MOISTURE_CONTENT")

        resp = api.transition_lab_test_order(order["id"], {"to": "AUTHORIZED"}, LM)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_IN_LAB)


# ---------------------------------------------------------------------------
# USCS classification (corner instances)
# ---------------------------------------------------------------------------

def _accept_sieve_and_atterberg(api, ctx, percent_passing_200, liquid_limit,
                                plasticity_index):
    """Run both classification inputs to ACCEPTED, returning the sample's
    uscs_class after only the sieve acceptance and after both."""
    sieve = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                             test_type="SIEVE_ANALYSIS")
    authorize_lab_order(sieve["id"])
    start_lab_order(sieve["id"])
    submit_lab_result(sieve["id"], percent_passing_200=percent_passing_200)
    accept_lab_order(sieve["id"])
    mid = get_success_data(api.get_sample(ctx["sample"]["id"], LM))

    att = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                           test_type="ATTERBERG")
    authorize_lab_order(att["id"])
    start_lab_order(att["id"])
    submit_lab_result(att["id"], liquid_limit=liquid_limit,
                      plasticity_index=plasticity_index)
    accept_lab_order(att["id"])
    final = get_success_data(api.get_sample(ctx["sample"]["id"], LM))
    return mid, final


def test_uscs_class_sc_from_coarse_with_fines(api):
    """PRD section 3.4: "When F is greater than 12 and at most 50 —
    coarse-grained with fines — the class is `SC` if PI is greater than 7 and
    `SM` otherwise." and "until both result types are accepted, or after
    either is rejected, `uscs_class` is null."

    Design: Corner/calculations/uscs_class_sc_from_coarse_with_fines
    """
    ctx = setup_lab_received_sample()
    mid, final = _accept_sieve_and_atterberg(
        api, ctx, percent_passing_200=42, liquid_limit=38, plasticity_index=12)
    assert mid["uscs_class"] is None, (
        "Classification waits for both sieve and Atterberg acceptances"
    )
    # 12 < 42 <= 50 with PI 12 > 7 -> SC.
    assert final["uscs_class"] == "SC"


def test_uscs_class_mh_fine_grained_below_a_line(api):
    """PRD section 3.4: "When F is strictly greater than 50 the soil is
    fine-grained: if LL is below 50, the class is `CL` when PI is at least 7
    and also at least the A-line value, and `ML` otherwise; if LL is 50 or
    more, the class is `CH` when PI is at least the A-line value and `MH`
    otherwise." and "compares PI against the A-line value computed as 0.73
    times LL-minus-20, evaluated without rounding."

    Design: Corner/calculations/uscs_class_mh_fine_grained_a_line
    """
    ctx = setup_lab_received_sample()
    _mid, final = _accept_sieve_and_atterberg(
        api, ctx, percent_passing_200=67, liquid_limit=55, plasticity_index=20)
    # F 67 > 50, LL 55 >= 50, A-line = 0.73 * 35 = 25.55, PI 20 < 25.55 -> MH.
    assert final["uscs_class"] == "MH"


def test_uscs_boundary_fifty_stays_coarse_bucket(api):
    """PRD section 3.4: "The boundary is exact: F equal to precisely 50.0
    falls in the 12-to-50 coarse-with-fines bucket, because the fine-grained
    branch requires strictly more than 50." and "When F is greater than 12
    and at most 50 — coarse-grained with fines — the class is `SC` if PI is
    greater than 7 and `SM` otherwise."

    Design: Corner/calculations/uscs_boundary_fifty_stays_coarse_bucket
    """
    ctx = setup_lab_received_sample()
    _mid, final = _accept_sieve_and_atterberg(
        api, ctx, percent_passing_200=50.0, liquid_limit=30, plasticity_index=10)
    # F == 50.0 stays in the coarse bucket; PI 10 > 7 -> SC.
    assert final["uscs_class"] == "SC"


# ---------------------------------------------------------------------------
# Append-only results (corner) and sample interval validation (corner)
# ---------------------------------------------------------------------------

def test_lab_test_result_append_only(api):
    """PRD section 3.4: "Result submission by a `LabTechnician` creates a
    LabTestResult against the order, records the caller's `X-User-ID` as
    `submitted_by_user_id`, and moves the order from `IN_TEST` to
    `RESULT_SUBMITTED`" and "Results are listed by `lab_test_order_id`."
    PRD section 2.3: "Every list response sorts by `created_at` in ascending
    order".

    Design: Corner/entities/lab_test_result_append_only
    """
    ctx = setup_lab_received_sample()
    order = create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                             test_type="MOISTURE_CONTENT")
    authorize_lab_order(order["id"])
    start_lab_order(order["id"])
    submit_lab_result(order["id"], moisture_content_pct=22.5)
    reject_lab_order(order["id"])
    transition_lab_order(order["id"], "IN_TEST", LT)
    submit_lab_result(order["id"], moisture_content_pct=22.7)

    resp = api.list_lab_test_results(LM, params={"lab_test_order_id": order["id"]})
    results, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert len(results) == 2, (
        "Each submission creates its own LabTestResult; none is overwritten"
    )
    assert all(r["lab_test_order_id"] == order["id"] for r in results)
    assert results[0]["moisture_content_pct"] == pytest.approx(22.5)
    assert results[1]["moisture_content_pct"] == pytest.approx(22.7)


def test_lab_technician_cannot_approve_plan(api):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list, or that fails an entity-backed ownership check, is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: "| POST | `/geo/boring-plans/{id}/transition` | Drive the
    BoringPlan machine (submit, return to draft, approve) | StaffEngineer,
    ProjectManager |".

    Design: Corner/validations/lab_technician_cannot_approve_plan
    """
    from test_helpers import SE, create_boring_plan_payload, \
        create_client_and_project
    _client, project = create_client_and_project()
    plan = get_success_data(api.create_boring_plan(
        project["id"], create_boring_plan_payload(project["version"]), SE))
    plan = get_success_data(api.transition_boring_plan(
        plan["id"], {"to": "SUBMITTED"}, SE))

    resp = api.transition_boring_plan(plan["id"], {"to": "APPROVED"}, LT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403


def test_sample_interval_outside_drilled_depth_rejected(api):
    """PRD section 3.4: "A `FieldGeologist` records each Sample with
    `depth_top_ft` and `depth_bottom_ft` delimiting the sampled interval —
    the top must lie strictly above the bottom and neither may exceed the
    boring's `actual_depth_ft` — a `sampler_type` of `SPT`, `SHELBY`,
    `BULK`, or `ROCK_CORE`, and a `recovery_pct` between 0 and 100 inclusive;
    malformed intervals or out-of-range recovery fail with `ERR_VALIDATION`."

    Design: Corner/validations/sample_interval_outside_drilled_depth_rejected
    """
    ctx = setup_drilled_boring(actual_depth_ft=30)
    resp = api.create_sample(
        ctx["boring"]["id"],
        {"depth_top_ft": 29, "depth_bottom_ft": 31, "sampler_type": "SPT",
         "recovery_pct": 80}, FG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400
