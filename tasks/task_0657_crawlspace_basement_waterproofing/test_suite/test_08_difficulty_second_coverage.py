"""Second-coverage tests for Difficulty-queue instances (each difficulty instance
requires >= 2 tests). Each test here approaches its instance's rule from a complementary
angle — a passing-boundary complement, an alternate branch, or the positive side of a
cross-entity dependency — while still translating the SAME design instance.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_crew_payload, create_crew_booking_payload, create_install_order_payload,
    create_service_visit_payload, create_claim_payload, create_quote_payload,
    create_financing_application_payload, create_foundation_referral_payload,
    create_homeowner, create_job, create_finalized_inspection,
    setup_sold_job, setup_sold_cash_job, setup_planned_install_order,
    setup_passed_install_order, setup_warranted_job, setup_scheduled_job_seed,
    setup_open_claim, setup_resolved_claim, setup_scheduled_annual_visit,
    setup_submitted_financing,
    TEST_USERS, MISSING_UUID,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]
SCH = TEST_USERS["scheduler_headers"]
WAR = TEST_USERS["warranty_admin_headers"]
FIN = TEST_USERS["finance_partner_headers"]


# ─── dual_variant_calc / install_reconciliation_variance_vs_quoted_estimate ──

def test_reconciliation_negative_variance_when_actual_drain_below_quoted(api):
    """PRD §3.7: "the billable drain footage is the actual footage minus the 20 free feet
    but never below zero ... charged at 4,500 cents per foot; the subtotal re-sums the same
    base, vapor, sump, dehumidifier, and backup charges plus this reconciled drain charge;
    the discount re-applies the accepted quote's discount percentage to that subtotal,
    rounded half up; tax at 7 percent is applied to the discounted subtotal, rounded half
    up; and the result becomes `final_total_cents`. The `variance_cents` is
    `final_total_cents` minus the accepted quote's `total_cents`".

    Design: Difficulty/dual_variant_calc/install_reconciliation_variance_vs_quoted_estimate
    """
    # Accepted Quote 1000 sqft full scope SPRING10 drain50 -> total 890775.
    # Reconcile with actual drain 30: drain billable (30-20)*4500=45000; subtotal 835000;
    # SPRING10 disc 83500; discounted 751500; tax round(751500*.07)=52605; final 804105;
    # variance 804105-890775 = -86670 (an underage, negative variance).
    ctx = setup_passed_install_order(
        footprint_sqft=1000, day="2026-05-03",
        quote_overrides={"includes_vapor_barrier": True, "includes_sump": True,
                         "includes_drain": True, "includes_battery_backup": True,
                         "drain_linear_ft": 50, "discount_code": "SPRING10"})
    io_id = ctx["install_order"]["id"]
    completed = validate_success(
        api.complete_install_order(io_id, {"actual_drain_linear_ft": 30}, SCH), 200)
    assert completed["final_total_cents"] == 804105
    assert completed["variance_cents"] == -86670


# ─── combinatorial_formula / financing_amortization_2d_tier_nonlinear ────────

def test_prime_short_bucket_term24_selects_599_bps(api):
    """PRD §3.6: "the term bucket is "short" when `term_months` is 24 or fewer and "long"
    when `term_months` is greater than 24. For a `PRIME` band the APR is 599 basis points
    short and 799 long".
    PRD §3.6: "the payment is the principal times the monthly rate times the quantity
    one-plus-the-monthly-rate raised to the number of months, divided by the quantity
    one-plus-the-monthly-rate raised to the number of months minus one. The result is
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/financing_amortization_2d_tier_nonlinear
    """
    # PRIME term24 (short) -> 599 bps; principal 395900 over 24 months -> monthly 17545.
    ctx = setup_sold_job(credit_band="PRIME", footprint_sqft=600,
                        quote_overrides={"includes_sump": True})
    res = api.create_financing_application(
        create_financing_application_payload(ctx["job"]["id"], ctx["quote"]["id"], 24),
        ctx["ho_headers"])
    app = validate_success(res, 201)
    assert app["apr_bps"] == 599
    assert app["monthly_payment_cents"] == 17545


# ─── combinatorial_formula / quote_pricing_nested_rounding_order_discount_then_tax ─

def test_spring10_discount_then_tax_order(api):
    """PRD §3.4: "`SPRING10` is 10 percent ... The discount amount is the subtotal
    multiplied by that percentage, rounded half up to whole cents, and recorded as
    `discount_cents`. The discounted subtotal is the subtotal minus the discount. Tax is
    then computed on the discounted subtotal — not on the pre-discount subtotal — at a rate
    of 7 percent, rounded half up to whole cents, and recorded as `tax_cents`. The total is
    the discounted subtotal plus the tax."

    Design: Difficulty/combinatorial_formula/quote_pricing_nested_rounding_order_discount_then_tax
    """
    # 2000 sqft vapor+dehu -> subtotal 1125000; SPRING10 disc round(1125000*.10)=112500;
    # discounted 1012500; tax round(1012500*.07)=70875; total 1083375.
    ho = create_homeowner(credit_band="PRIME")
    job = create_job(ho["id"], footprint_sqft=2000, structure_type="COMBINED")
    quote = validate_success(api.create_quote(job["id"], create_quote_payload(
        includes_vapor_barrier=True, includes_dehumidifier=True, discount_code="SPRING10"), EST), 201)
    assert quote["subtotal_cents"] == 1125000
    assert quote["discount_cents"] == 112500
    assert quote["tax_cents"] == 70875
    assert quote["total_cents"] == 1083375


# ─── compensating_invariant / open_claim_count_conserved_file_then_deny ──────

def test_open_claim_count_rises_to_one_on_file(api):
    """PRD §3.11: "Filing creates the claim in status `OPEN`, recomputes the Job's
    `open_claim_count`, and increments the Job's `version`."
    PRD §3.11: "the Job's `open_claim_count` is kept equal to the number of this Job's
    claims whose status is `OPEN` or `IN_PROGRESS`."

    Design: Difficulty/compensating_invariant/open_claim_count_conserved_file_then_deny
    """
    ctx = setup_warranted_job()
    before = validate_success(api.get_job(ctx["job_id"], WAR), 200)
    assert before["open_claim_count"] == 0
    validate_success(api.create_claim(
        create_claim_payload(ctx["job_id"], ctx["warranty_id"], "WATER_INTRUSION"),
        ctx["ho_headers"]), 201)
    after = validate_success(api.get_job(ctx["job_id"], WAR), 200)
    assert after["open_claim_count"] == 1


# ─── compensating_invariant / schedule_link_conserved_install_create_then_cancel ─

def test_install_create_sets_link_and_schedules_job(api):
    """PRD §3.7: "On success an InstallOrder is created in status `PLANNED` with its
    `job_id` set, its `quote_id` pinned to the Job's `accepted_quote_id`, the Job's
    `install_order_id` pointed at the new order, and the Job advanced from `SOLD` to
    `SCHEDULED`; the Job's `version` is incremented."

    Design: Difficulty/compensating_invariant/schedule_link_conserved_install_create_then_cancel
    """
    ctx = setup_planned_install_order(footprint_sqft=600,
                                     quote_overrides={"includes_sump": True},
                                     scheduled_start="2026-05-09T08:00:00Z",
                                     scheduled_end="2026-05-09T17:00:00Z")
    io = ctx["install_order"]
    assert io["status"] == "PLANNED"
    job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
    assert job_after["lifecycle_status"] == "SCHEDULED"
    assert job_after["install_order_id"] == io["id"]


# ─── cross_entity_state_dependency / claim_triage_requires_warranty_active ───

def test_triage_accept_succeeds_on_active_warranty(api):
    """PRD §3.11: "Triaging with accept true moves a claim from `OPEN` (or from `REOPENED`)
    to `IN_PROGRESS`, but only when the warranty is `ACTIVE` and the claim's category is one
    the warranty covers".

    Design: Difficulty/cross_entity_state_dependency/claim_triage_requires_warranty_active
    """
    ctx = setup_open_claim(category="WATER_INTRUSION")  # warranty still ACTIVE
    triaged = validate_success(api.triage_claim(ctx["claim"]["id"], {"accept": True}, WAR), 200)
    assert triaged["status"] == "IN_PROGRESS"


# ─── cross_entity_state_dependency / install_order_requires_job_financing_resolved ─

def test_install_create_succeeds_when_financed_cash(api):
    """PRD §3.7: "This is permitted only when the Job is `SOLD` and its `financing_status`
    is either `CASH` or `APPROVED`".
    PRD §3.7: "On success an InstallOrder is created in status `PLANNED` ... and the Job
    advanced from `SOLD` to `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/install_order_requires_job_financing_resolved
    """
    ctx = setup_sold_cash_job(footprint_sqft=600, quote_overrides={"includes_sump": True})
    res = api.create_install_order(
        ctx["job"]["id"],
        create_install_order_payload("2026-05-06T08:00:00Z", "2026-05-06T17:00:00Z",
                                    ctx["job_version"]),
        SCH)
    io = validate_success(res, 201)
    assert io["status"] == "PLANNED"
    job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
    assert job_after["lifecycle_status"] == "SCHEDULED"


# ─── non_linear_state_machine / claim_cyclic_resolved_reopen_loop ────────────

def test_reopen_requires_warranty_active(api):
    """PRD §3.11: "a `Homeowner` may reopen it while the warranty is still `ACTIVE`,
    moving it from `RESOLVED` to `REOPENED`, incrementing its `reopen_count` by 1".

    Design: Difficulty/non_linear_state_machine/claim_cyclic_resolved_reopen_loop
    """
    # complement to the reopen->triage loop: the reopen step itself, asserting the resolved
    # claim transitions to REOPENED while the warranty is ACTIVE.
    ctx = setup_resolved_claim()
    reopened = validate_success(api.reopen_claim(ctx["claim"]["id"], ctx["ho_headers"]), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1


# ─── priority_pair_validation_conflict / existence_before_referral_eligibility_on_send ─

def test_send_missing_referral_existence_outranks_eligibility(api):
    """PRD §2.7: "Then path-resource existence is verified left to right, yielding
    `ERR_NOT_FOUND`. ... Only after all of those does the system evaluate whether the
    target resource is in a legal state for the requested transition ... and finally the
    domain-specific business rules described throughout §2 and §3."

    Design: Difficulty/priority_pair_validation_conflict/existence_before_referral_eligibility_on_send
    """
    # A distinct unknown referral id; even though the eligibility business rule (P10) could
    # never be satisfied for a missing referral, existence (P3) is what is reported.
    res = api.send_foundation_referral("00000000-0000-4000-8000-0000000000ef", INS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── priority_pair_validation_conflict / state_before_finance_limit_on_decide ─

def test_reapprove_already_approved_over_ceiling_returns_invalid_state(api):
    """PRD §2.7: "Only after all of those does the system evaluate whether the target
    resource is in a legal state for the requested transition, yielding `ERR_INVALID_STATE`
    (HTTP 409); the optimistic-concurrency version check ...; and finally the
    domain-specific business rules".
    PRD §3.6: "Approving requires the application to be `SUBMITTED` and the Job's
    `financing_status` to be `APPLIED`".

    Design: Difficulty/priority_pair_validation_conflict/state_before_finance_limit_on_decide
    """
    # NEAR_PRIME full-scope 2000 sqft total 1813650 (< 3M ceiling) so first APPROVE succeeds;
    # a second APPROVE is then an invalid-state transition (already APPROVED), which P6 reports
    # ahead of any later business-rule evaluation.
    ctx = setup_submitted_financing(
        credit_band="NEAR_PRIME", footprint_sqft=2000, term_months=12,
        quote_overrides={"includes_vapor_barrier": True, "includes_sump": True,
                         "includes_dehumidifier": True, "includes_drain": True,
                         "includes_battery_backup": True, "drain_linear_ft": 100,
                         "discount_code": "NONE"})
    validate_success(api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, FIN), 200)
    res = api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, FIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── boundary_precision_check / crew_daily_capacity_zero_remaining_boundary ──

def test_confirm_under_daily_capacity_succeeds(api):
    """PRD §3.8: "confirming must not push the crew over its `daily_capacity`: the count of
    the crew's `CONFIRMED` bookings on the booking's calendar day must remain below
    `daily_capacity`, and a confirm that would exceed it is rejected with
    `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/crew_daily_capacity_zero_remaining_boundary
    """
    # daily_capacity 1, zero CONFIRMED bookings yet -> one remaining slot, so the FIRST
    # same-day confirm stays below the ceiling and succeeds (the X-1 side of the boundary).
    crew = get_success_data(api.create_crew(
        create_crew_payload(name="India", daily_capacity=1), SCH))
    seed = setup_scheduled_job_seed()
    cb = get_success_data(api.create_crew_booking(
        create_crew_booking_payload(crew["id"], seed["install_order_id"],
                                   "2026-05-05T08:00:00Z", "2026-05-05T12:00:00Z"), SCH))
    confirmed = validate_success(api.confirm_crew_booking(cb["id"], SCH), 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── resource_temporal_overlap / crew_booking_half_open_interval_overlap ─────

def test_touching_window_does_not_collide(api):
    """PRD §3.8: "two windows collide when their half-open
    `window_start`-to-`window_end` intervals intersect, and a colliding confirm is rejected
    with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."
    PRD §3.8: "the booking window via `window_start` and `window_end`, again treated as
    half-open from start up to but not including end."

    Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_interval_overlap
    """
    # CONFIRMED [12:00,16:00); a touching [16:00,18:00) does NOT intersect under [start,end)
    # semantics, so confirming the second booking succeeds.
    crew = get_success_data(api.create_crew(
        create_crew_payload(name="Golf", daily_capacity=5), SCH))
    seed1 = setup_scheduled_job_seed()
    seed2 = setup_scheduled_job_seed()
    cb1 = get_success_data(api.create_crew_booking(
        create_crew_booking_payload(crew["id"], seed1["install_order_id"],
                                   "2026-05-07T12:00:00Z", "2026-05-07T16:00:00Z"), SCH))
    validate_success(api.confirm_crew_booking(cb1["id"], SCH), 200)
    cb2 = get_success_data(api.create_crew_booking(
        create_crew_booking_payload(crew["id"], seed2["install_order_id"],
                                   "2026-05-07T16:00:00Z", "2026-05-07T18:00:00Z"), SCH))
    confirmed = validate_success(api.confirm_crew_booking(cb2["id"], SCH), 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── resource_temporal_overlap / service_visit_min_gap_buffer_overlap ────────

def test_visit_exactly_seven_days_apart_succeeds(api):
    """PRD §3.10: "a new visit must sit at least 7 calendar days from every other
    `SCHEDULED` visit on the same warranty. ... two scheduled visits within the 7-day buffer
    — including ones at the very same instant — collide and the new one is rejected with
    `ERR_VISIT_TOO_CLOSE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/service_visit_min_gap_buffer_overlap
    """
    # First visit 2026-09-01; second exactly 7 days later satisfies "at least 7 days" -> OK.
    ctx = setup_scheduled_annual_visit(scheduled_for="2026-09-01T10:00:00Z")
    sv2 = validate_success(api.create_service_visit(
        ctx["warranty_id"],
        create_service_visit_payload("ANNUAL", "2026-09-08T10:00:00Z"), WAR), 201)
    assert sv2["status"] == "SCHEDULED"


# ─── transitive_cascade / install_complete_cascade_depth3 ────────────────────

def test_complete_releases_reserved_unconfirmed_booking(api):
    """PRD §3.7: "On completion the order moves from `PASSED` to `COMPLETED`, the Job
    advances from `SCHEDULED` to `INSTALLED`, every crew booking for that order still in
    `RESERVED` or `CONFIRMED` is released to `RELEASED`".

    Design: Difficulty/transitive_cascade/install_complete_cascade_depth3
    """
    # Build a PASSED install order (which has one CONFIRMED booking), then add a second
    # still-RESERVED booking on the same order; completion must release BOTH.
    ctx = setup_passed_install_order(footprint_sqft=600, day="2026-05-04",
                                    quote_overrides={"includes_sump": True})
    io_id = ctx["install_order"]["id"]
    crew2 = get_success_data(api.create_crew(
        create_crew_payload(name="Hotel", daily_capacity=3), SCH))
    reserved = get_success_data(api.create_crew_booking(
        create_crew_booking_payload(crew2["id"], io_id,
                                   "2026-05-04T08:00:00Z", "2026-05-04T17:00:00Z"), SCH))
    assert reserved["status"] == "RESERVED"

    validate_success(api.complete_install_order(io_id, {}, SCH), 200)
    reserved_after = validate_success(api.get_crew_booking(reserved["id"], SCH), 200)
    assert reserved_after["status"] == "RELEASED"


# ─── transitive_cascade / warranty_void_cascade_depth2 ───────────────────────

def test_void_cancels_claim_repair_scheduled_visit(api):
    """PRD §3.9: "A `WarrantyAdmin` may void an active warranty, moving it from `ACTIVE` to
    `VOID`; voiding also cancels every `SCHEDULED` service visit on that warranty, moving
    each to `CANCELLED`".

    Design: Difficulty/transitive_cascade/warranty_void_cascade_depth2
    """
    # Distinct from the ANNUAL-visit case: a SCHEDULED CLAIM_REPAIR visit is also cancelled.
    ctx = setup_open_claim(category="WATER_INTRUSION")
    validate_success(api.triage_claim(ctx["claim"]["id"], {"accept": True}, WAR), 200)
    sv = get_success_data(api.create_service_visit(
        ctx["warranty_id"],
        create_service_visit_payload("CLAIM_REPAIR", "2026-10-01T10:00:00Z",
                                    claim_id=ctx["claim"]["id"]), WAR))
    voided = validate_success(api.void_warranty(ctx["warranty_id"], WAR), 200)
    assert voided["status"] == "VOID"
    sv_after = validate_success(api.get_service_visit(sv["id"], WAR), 200)
    assert sv_after["status"] == "CANCELLED"
