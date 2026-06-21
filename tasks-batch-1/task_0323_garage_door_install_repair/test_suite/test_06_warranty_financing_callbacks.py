"""Warranty plans & tune-ups, consumer financing, callbacks and the technician
quality score, the customer-blocked accept guard, and the completion/invoice
business errors that depend on these workflows.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    make_service_manager_headers,
    # fixtures
    create_customer,
    create_technician,
    create_part,
    create_sent_quote,
    accept_quote_get_job,
    schedule_job,
    setup_completed_job,
    setup_closed_job,
    setup_on_site_callback,
    setup_blocked_customer,
    submit_financing_application,
    open_callback,
    create_warranty_plan,
    consume_all_reservations,
    get_technician,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc / dvc_technician_callback_rate_provisional_vs_settled
# ===========================================================================
class TestCallbackRateProvisionalVsSettled:
    def _two_completed_jobs_one_open_callback(self):
        """One technician with 2 COMPLETED jobs and exactly 1 OPEN callback on one."""
        customer = create_customer(time_zone="America/Phoenix")
        technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
        tech_h = make_technician_headers(technician["id"])

        def complete_one(start, end):
            quote = create_sent_quote(
                customer["id"], [{"item_kind": "LABOR", "qty": 30}],
                quote_type="SERVICE_CALL", service_call_fee_cents=5000,
            )
            job = accept_quote_get_job(quote["id"], customer["id"])
            job = schedule_job(job["id"], technician["id"], start=start, end=end)
            get_success_data(api_client.depart_job(job["id"], tech_h))
            get_success_data(api_client.arrive_job(job["id"], tech_h))
            get_success_data(api_client.safety_check_job(job["id"], tech_h))
            get_success_data(api_client.complete_job(job["id"], tech_h))
            return job

        job1 = complete_one("2026-07-01T17:00:00Z", "2026-07-01T18:00:00Z")
        complete_one("2026-07-02T17:00:00Z", "2026-07-02T18:00:00Z")
        # Open one callback on job1; leave it OPEN (unresolved).
        open_callback(job1["id"], customer["id"], reason="door reverses")
        return technician

    def test_provisional_rate_counts_open_callback(self, api):
        """PRD §3.10: "The **provisional** rate is pessimistic: its numerator
        counts every callback on the technician's jobs that is either not yet
        `RESOLVED`, or is `RESOLVED` with `fault_confirmed` true — open, scheduled,
        and on-site callbacks are all counted as faults."

        Design: Difficulty/dual_variant_calc/dvc_technician_callback_rate_provisional_vs_settled
        """
        technician = self._two_completed_jobs_one_open_callback()
        tech = get_technician(technician["id"])
        assert tech["jobs_completed_count"] == 2, (
            f"Expected jobs_completed_count 2, got {tech['jobs_completed_count']}"
        )
        assert tech["callback_rate_provisional"] == pytest.approx(0.5, abs=0.0001), (
            f"Expected callback_rate_provisional 0.5, got {tech['callback_rate_provisional']}"
        )

    def test_settled_rate_excludes_open_callback(self, api):
        """PRD §3.10: "The **settled** rate is confirmed: its numerator counts
        only callbacks that are `RESOLVED` with `fault_confirmed` true."

        Design: Difficulty/dual_variant_calc/dvc_technician_callback_rate_provisional_vs_settled
        """
        technician = self._two_completed_jobs_one_open_callback()
        tech = get_technician(technician["id"])
        assert tech["callback_rate_settled"] == pytest.approx(0.0, abs=0.0001), (
            f"Expected callback_rate_settled 0.0 while callback is OPEN, got {tech['callback_rate_settled']}"
        )


# ===========================================================================
# Difficulty / cross_entity_state_dependency / cesd_quote_accept_requires_customer_good_standing
# ===========================================================================
class TestBlockedCustomerCannotAccept:
    def test_blocked_customer_accept_rejected(self, api):
        """PRD §3.4: "the customer's `financing_standing` must be `GOOD` — a
        customer whose standing is `BLOCKED` cannot accept, and the attempt is
        rejected with `ERR_CUSTOMER_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/cesd_quote_accept_requires_customer_good_standing
        """
        ctx = setup_blocked_customer()
        resp = api.accept_quote(ctx["blocked_quote"]["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_BLOCKED.value, 409)

    def test_default_sets_financing_standing_blocked(self, api):
        """PRD §3.12: "defaulting recomputes the owning customer's
        `financing_standing` to `BLOCKED`, which is the condition that prevents
        that customer from accepting further quotes."

        Design: Difficulty/cross_entity_state_dependency/cesd_quote_accept_requires_customer_good_standing
        """
        ctx = setup_blocked_customer()
        fetched = get_success_data(api.get_customer(ctx["customer"]["id"], SM))
        assert fetched["financing_standing"] == "BLOCKED", (
            f"Expected financing_standing BLOCKED after default, got {fetched['financing_standing']}"
        )


# ===========================================================================
# Difficulty / boundary_precision_check / bpc_tuneups_exhausted_at_equal_count
# ===========================================================================
class TestTuneUpsExhaustedBoundary:
    def _active_plan_one_tuneup(self):
        """ACTIVE warranty plan, tune_ups_included 1, tune_ups_used 0 (job closed)."""
        ctx = setup_completed_job(time_zone="America/Phoenix", service_call_fee_cents=6000)
        plan = create_warranty_plan(ctx["job"]["id"], ctx["customer"]["id"], tune_ups_included=1)
        mgr_h = make_service_manager_headers("manager-1")
        get_success_data(api_client.invoice_job(ctx["job"]["id"], mgr_h))
        get_success_data(api_client.pay_job(ctx["job"]["id"], mgr_h))
        get_success_data(api_client.close_job(ctx["job"]["id"], mgr_h))
        return plan

    def test_first_tuneup_succeeds_second_exhausted(self, api):
        """PRD §3.11: "each redemption increments `tune_ups_used` by one, but only
        while it is below the limit — a redemption attempted when `tune_ups_used`
        is greater than or equal to `tune_ups_included` is rejected with
        `ERR_TUNEUPS_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/bpc_tuneups_exhausted_at_equal_count
        """
        plan = self._active_plan_one_tuneup()
        # used 0 < 1 -> first redemption succeeds.
        first = validate_success(api.redeem_tune_up(plan["id"], SM))
        assert first["tune_ups_used"] == 1, f"Expected tune_ups_used 1, got {first['tune_ups_used']}"
        # used 1 >= 1 -> second rejected.
        resp = api.redeem_tune_up(plan["id"], SM)
        validate_error(resp, ApiErrorId.ERR_TUNEUPS_EXHAUSTED.value, 409)

    def test_tuneup_used_does_not_advance_past_limit(self, api):
        """PRD §3.11: "each redemption increments `tune_ups_used` by one, but only
        while it is below the limit"

        Design: Difficulty/boundary_precision_check/bpc_tuneups_exhausted_at_equal_count
        """
        plan = self._active_plan_one_tuneup()
        get_success_data(api.redeem_tune_up(plan["id"], SM))
        api.redeem_tune_up(plan["id"], SM)  # rejected
        fetched = get_success_data(api.get_warranty_plan(plan["id"], SM))
        assert fetched["tune_ups_used"] == 1, (
            f"Expected tune_ups_used to stay at 1 after exhausted redemption, got {fetched['tune_ups_used']}"
        )


# ===========================================================================
# Corner / calculations / financing_monthly_payment_correct_24mo_tier
# ===========================================================================
def test_financing_monthly_payment_24mo_tier(api):
    """PRD §3.12: "a term of 13 through 24 months carries an APR of 0.149 ...
    the monthly payment is the `principal_cents` multiplied by the monthly rate,
    multiplied by that growth factor, divided by the growth factor minus one,
    with the result rounded half-up to whole cents."

    Design: Corner/calculations/financing_monthly_payment_correct_24mo_tier
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    app = submit_financing_application(customer["id"], quote["id"], 50900, 24)
    approved = validate_success(api.approve_financing_application(app["id"], SM))
    assert approved["monthly_payment_cents"] == 2466, (
        f"Expected monthly_payment_cents 2466, got {approved['monthly_payment_cents']}"
    )


# ===========================================================================
# Corner / calculations / financing_zero_apr_tier_6mo
# ===========================================================================
def test_financing_monthly_payment_zero_apr_6mo_tier(api):
    """PRD §3.12: "a `term_months` of 6 or fewer carries an APR of 0.00 ... When
    the monthly rate is zero (the 0% tier), the monthly payment is the
    `principal_cents` divided by `term_months`, rounded up to the next whole cent
    (ceiling)."

    Design: Corner/calculations/financing_zero_apr_tier_6mo
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    app = submit_financing_application(customer["id"], quote["id"], 60000, 6)
    approved = validate_success(api.approve_financing_application(app["id"], SM))
    assert approved["monthly_payment_cents"] == 10000, (
        f"Expected monthly_payment_cents 10000 (ceil(60000/6)), got {approved['monthly_payment_cents']}"
    )


# ===========================================================================
# Corner / validations / financing_ceiling_blocks_approval
# ===========================================================================
def test_financing_above_ceiling_cannot_be_approved(api):
    """PRD §3.12: "**Approving** it moves it from `SUBMITTED` to `APPROVED`,
    permitted only when the `principal_cents` is at or below the approval ceiling
    of 1,500,000 cents (fifteen thousand dollars); a principal above that ceiling
    is rejected with `ERR_FINANCING_CEILING`."

    Design: Corner/validations/financing_ceiling_blocks_approval
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    app = submit_financing_application(customer["id"], quote["id"], 1600000, 24)
    resp = api.approve_financing_application(app["id"], SM)
    validate_error(resp, ApiErrorId.ERR_FINANCING_CEILING.value, 409)


# ===========================================================================
# Corner / state_machines / financing_decline_branch
# ===========================================================================
def test_financing_decline_lands_in_declined(api):
    """PRD §3.12: "**Declining** it moves it from `SUBMITTED` to `DECLINED` with
    no further effect."

    Design: Corner/state_machines/financing_decline_branch
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    app = submit_financing_application(customer["id"], quote["id"], 12500, 12)
    declined = validate_success(api.decline_financing_application(app["id"], SM))
    assert declined["status"] == "DECLINED", (
        f"Expected status DECLINED, got {declined['status']}"
    )


# ===========================================================================
# Corner / state_machines / callback_reopen_cycle_then_resolve
# ===========================================================================
def test_callback_reopen_returns_to_open(api):
    """PRD §3.10: "Alternatively, a `Dispatcher` may **reopen** an on-site
    callback that could not be resolved, moving it from `ON_SITE` back to `OPEN`
    for re-triage; this is the cyclic branch of the callback lifecycle."

    Design: Corner/state_machines/callback_reopen_cycle_then_resolve
    """
    ctx = setup_on_site_callback()
    reopened = validate_success(api.reopen_callback(ctx["callback"]["id"], DISPATCHER))
    assert reopened["status"] == "OPEN", (
        f"Expected callback status OPEN after reopen, got {reopened['status']}"
    )


# ===========================================================================
# Corner / state_machines / warranty_expire_before_exhausted_returns_invalid_state
# ===========================================================================
def test_expire_warranty_before_exhausted_rejected(api):
    """PRD §3.11: "A `ServiceManager` may also **expire** a plan, moving it from
    `ACTIVE` to `EXPIRED`, permitted only once the plan is exhausted — that is,
    once `tune_ups_used` is greater than or equal to `tune_ups_included`"

    Design: Corner/state_machines/warranty_expire_before_exhausted_returns_invalid_state
    """
    ctx = setup_completed_job(time_zone="America/Phoenix", service_call_fee_cents=6000)
    plan = create_warranty_plan(ctx["job"]["id"], ctx["customer"]["id"], tune_ups_included=2)
    mgr_h = make_service_manager_headers("manager-1")
    get_success_data(api_client.invoice_job(ctx["job"]["id"], mgr_h))
    get_success_data(api_client.pay_job(ctx["job"]["id"], mgr_h))
    get_success_data(api_client.close_job(ctx["job"]["id"], mgr_h))
    # tune_ups_used 0 < tune_ups_included 2 -> not exhausted.
    resp = api.expire_warranty_plan(plan["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner / validations / parts_not_consumed_blocks_complete
# ===========================================================================
def test_complete_with_held_reservation_after_safety_rejected(api):
    """PRD §3.6: "Second, every part reservation on the job must be in `CONSUMED`
    status; if any reservation is still `HELD`, the completion is rejected with
    `ERR_PARTS_NOT_CONSUMED`."

    Design: Corner/validations/parts_not_consumed_blocks_complete
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED")
    cable = create_part(category="CABLE", unit_price_cents=4000, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"],
        [{"item_kind": "PART", "item_ref_id": cable["id"], "qty": 1, "unit_price_cents": 4000}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(job["id"], technician["id"])
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    # Safety passes but the reservation is left HELD -> referential check fires.
    get_success_data(api.safety_check_job(job["id"], tech_h))
    resp = api.complete_job(job["id"], tech_h)
    validate_error(resp, ApiErrorId.ERR_PARTS_NOT_CONSUMED.value, 409)


# ===========================================================================
# Corner / validations / insufficient_stock_on_manual_reservation
# ===========================================================================
def test_manual_reservation_exceeding_available_rejected(api):
    """PRD §3.9: "A manual reservation create is rejected with
    `ERR_INSUFFICIENT_STOCK` if its `qty` exceeds the part's `available_qty`."

    Design: Corner/validations/insufficient_stock_on_manual_reservation
    """
    customer = create_customer()
    part = create_part(category="ROLLER", unit_price_cents=2000, on_hand_qty=5)
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job_v = get_success_data(api.get_job(job["id"], SM))["version"]
    resp = api.create_part_reservation(
        {"job_id": job["id"], "part_id": part["id"], "qty": 6, "expected_job_version": job_v},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, 409)


# ===========================================================================
# Corner / errors / segregation_violation_on_self_invoice
# ===========================================================================
def test_self_invoice_segregation_violation(api):
    """PRD §3.8: "enforcing separation of duties — the acting manager's
    `X-User-ID` must not equal the job's `completed_by_user_id`. A manager
    attempting to invoice a job they personally completed is rejected with
    `ERR_SEGREGATION_VIOLATION`."

    Design: Corner/errors/segregation_violation_on_self_invoice
    """
    customer = create_customer(time_zone="America/Phoenix")
    technician = create_technician(skill_level="CERTIFIED")
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=6000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(job["id"], technician["id"])
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    get_success_data(api.safety_check_job(job["id"], tech_h))
    get_success_data(api.complete_job(job["id"], tech_h))
    # completed_by_user_id is the technician id; invoice as a ServiceManager
    # whose X-User-ID equals that same id.
    resp = api.invoice_job(job["id"], make_service_manager_headers(technician["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, 409)
