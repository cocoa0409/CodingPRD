"""Time capture: line-level billable computation and submission guards."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_client,
    add_matter,
    add_time_entry,
    add_timekeeper,
    advance_periods,
    api_client,
    assert_time_entry,
    close_books,
    create_time_entry_payload,
    make_billing_partner_headers,
    make_timekeeper_headers,
    setup_active_matter,
    setup_firm,
    validate_error,
    validate_success,
)


class TestBillableAmountComputation:

    def test_billable_amount_floor_rounds_down(self):
        """PRD section 3.4: "At creation the system computes
        `billable_amount_cents` as `hours_worked_milli` multiplied by
        `hourly_rate_cents` and divided by one thousand, rounded down to a
        whole cent — this line-level floor rounding is pinned at creation and
        never recomputed later — and derives the entry's `period_index` as the
        fiscal period containing `entry_date` (see §2.6)."

        Design: Corner/entities/time_entry_billable_amount_floor_rounding
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"],
                            litigation_stage="INTAKE")

        # 1.5 hours at 33333 cents/hour: 1500 * 33333 / 1000 = 49999.5,
        # floored to a whole cent at line level.
        resp = api_client.create_time_entry(
            firm["id"], matter["id"],
            create_time_entry_payload(timekeeper_id=tk["id"],
                                      task_code="L110",
                                      litigation_stage="INTAKE",
                                      hours_worked_milli=1500,
                                      hourly_rate_cents=33333),
            make_timekeeper_headers(tk["id"]))
        entry = validate_success(resp, 201)
        assert_time_entry(entry)
        assert entry["billable_amount_cents"] == 49999, (
            f"floor(1500*33333/1000) must be 49999, got "
            f"{entry['billable_amount_cents']}")


class TestSubmissionGuards:

    def test_submit_blocked_when_client_suspended(self):
        """PRD section 3.4: "Second, the client must be `ACTIVE`; a
        `SUSPENDED` or `CLOSED` client rejects it with
        `ERR_CLIENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/time_entry_submit_depends_on_client_state
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], 50000)

        resp = api_client.suspend_client(
            ctx["firm"]["id"], ctx["client"]["id"], ADMIN)
        validate_success(resp, 200)

        resp = api_client.submit_time_entry(
            ctx["firm"]["id"], entry["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)

    def test_submit_blocked_when_task_code_not_budgeted(self):
        """PRD section 3.4: "Fourth, the entry's `task_code` must match an
        `ACTIVE` phase budget on the matter, or the submission is rejected
        with `ERR_TASK_CODE_NOT_BUDGETED`."

        Design: Corner/errors/error_task_code_not_budgeted
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], 50000,
                               task_code="L999")

        resp = api_client.submit_time_entry(
            ctx["firm"]["id"], entry["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TASK_CODE_NOT_BUDGETED)

    def test_matter_gate_fires_before_closed_period_guard(self):
        """PRD section 3.4: "Submission by the timekeeper or a billing
        partner moves the entry `DRAFT` → `SUBMITTED` and passes through four
        guards in a fixed order. First, the matter must be `ACTIVE` or
        `REOPENED`; an `OPEN`, `SUSPENDED`, or `CLOSED` matter rejects the
        submission with `ERR_MATTER_NOT_OPEN`."
        PRD section 2.9: "Where two listed guards both apply to the same
        endpoint, the earlier-numbered guard fires first; the per-workflow
        orderings in §3 refine this sequence wherever several business gates
        stack on a single action."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_priority_on_time_entry_submit
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        # Entry dated in the firm's current period (period 0).
        entry = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], 50000)

        # Suspend the matter (matter-open gate will fail on submit), then
        # close the books through period 0 so the entry's period is also
        # closed (closed-period guard would fail too).
        resp = api_client.suspend_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_success(resp, 200)
        advance_periods(ctx["firm"]["id"], 1)
        close_books(ctx["firm"]["id"])

        resp = api_client.submit_time_entry(
            ctx["firm"]["id"], entry["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MATTER_NOT_OPEN)
