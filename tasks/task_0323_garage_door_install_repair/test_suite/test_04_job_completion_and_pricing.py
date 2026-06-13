"""Job completion, the final invoice total, and the emergency surcharge.

Covers the dual-variant cost divergence (estimate vs final), the combinatorial
emergency-surcharge formula and its boundary, the parallel dispatch/billing
dimensions, and the safety-before-referential completion gate.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    make_technician_headers,
    make_service_manager_headers,
    # fixtures
    create_customer,
    create_technician,
    create_door_model,
    create_part,
    create_sent_quote,
    accept_quote_get_job,
    schedule_job,
    setup_accepted_job,
    setup_on_site_job,
    consume_all_reservations,
    first_reservation,
)


# ===========================================================================
# Difficulty / dual_variant_calc / dvc_quote_estimate_vs_job_final_diverge
# ===========================================================================
class TestEstimateVsFinalDivergence:
    def _setup_diverging_job(self):
        """SERVICE_CALL quote: fee 8900, one PART line (spring qty 2 @10000,
        markup 0.35) and one LABOR line (60 min). Accept -> consume -> complete.
        Estimate 50900; final 35900 (consumed parts 27000 + fee 8900 +
        BUSINESS-band surcharge 0)."""
        customer = create_customer(time_zone="America/Phoenix")
        technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
        spring = create_part(category="SPRING", unit_price_cents=10000, markup_pct=0.35, on_hand_qty=10)
        quote = create_sent_quote(
            customer["id"],
            [
                {"item_kind": "PART", "item_ref_id": spring["id"], "qty": 2, "unit_price_cents": 10000},
                {"item_kind": "LABOR", "qty": 60},
            ],
            quote_type="SERVICE_CALL",
            service_call_fee_cents=8900,
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        # 17:00Z in America/Phoenix is 10:00 local -> BUSINESS band (rate 0).
        job = schedule_job(
            job["id"], technician["id"],
            start="2026-07-01T17:00:00Z", end="2026-07-01T19:00:00Z",
        )
        tech_h = make_technician_headers(technician["id"])
        get_success_data(api_client.depart_job(job["id"], tech_h))
        get_success_data(api_client.arrive_job(job["id"], tech_h))
        consume_all_reservations(job["id"], technician["id"])
        get_success_data(api_client.safety_check_job(job["id"], tech_h))
        return customer, technician, quote, job, tech_h

    def test_estimate_total_is_50900(self, api):
        """PRD §3.3: "Fourth, the `estimate_total_cents` is that parts-and-goods
        subtotal plus the `service_call_fee_cents` when the quote type is
        `SERVICE_CALL`, or plus nothing when the quote type is `INSTALL`."

        Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_job_final_diverge
        """
        _, _, quote, _, _ = self._setup_diverging_job()
        fetched = get_success_data(api.get_quote(quote["id"], make_service_manager_headers()))
        assert fetched["estimate_total_cents"] == 50900, (
            f"Expected estimate_total_cents 50900, got {fetched['estimate_total_cents']}"
        )

    def test_final_total_diverges_from_estimate(self, api):
        """PRD §3.6: "The `final_total_cents` is the consumed-parts cost plus the
        labor cost plus the emergency surcharge."
        PRD §3.6: "for a `SERVICE_CALL` job the labor cost is the quote's
        `service_call_fee_cents`"

        Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_job_final_diverge
        """
        _, _, quote, job, tech_h = self._setup_diverging_job()
        completed = validate_success(api.complete_job(job["id"], tech_h))
        assert completed["final_total_cents"] == 35900, (
            f"Expected final_total_cents 35900, got {completed['final_total_cents']}"
        )
        fetched_quote = get_success_data(api.get_quote(quote["id"], make_service_manager_headers()))
        assert fetched_quote["estimate_total_cents"] != completed["final_total_cents"], (
            "estimate_total_cents and final_total_cents must diverge"
        )


# ===========================================================================
# Difficulty / combinatorial_formula / cf_emergency_surcharge_tier_and_cap
# ===========================================================================
class TestEmergencySurchargeCombinatorial:
    def _setup_after_hours_install(self):
        """INSTALL quote (door 180 install minutes, one PANEL part qty 1 @20000),
        emergency job scheduled 19:00 Phoenix (=02:00Z), panel consumed, completed.
        Base = consumed parts 27000 + labor 180*250=45000 = 72000;
        AFTER_HOURS rate 0.25 -> surcharge 18000; final 90000."""
        customer = create_customer(time_zone="America/Phoenix")
        technician = create_technician(skill_level="MASTER", certified_for_install=True)
        door = create_door_model(install_labor_minutes=180, requires_lift=False, list_price_cents=120000)
        panel = create_part(category="PANEL", unit_price_cents=20000, markup_pct=0.35, on_hand_qty=5)
        quote = create_sent_quote(
            customer["id"],
            [{"item_kind": "PART", "item_ref_id": panel["id"], "qty": 1, "unit_price_cents": 20000}],
            quote_type="INSTALL",
            door_model_id=door["id"],
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        job = schedule_job(
            job["id"], technician["id"],
            start="2026-07-01T02:00:00Z", end="2026-07-01T04:00:00Z", is_emergency=True,
        )
        tech_h = make_technician_headers(technician["id"])
        get_success_data(api_client.depart_job(job["id"], tech_h))
        get_success_data(api_client.arrive_job(job["id"], tech_h))
        consume_all_reservations(job["id"], technician["id"])
        get_success_data(api_client.safety_check_job(job["id"], tech_h))
        return job, tech_h

    def test_after_hours_surcharge_is_18000(self, api):
        """PRD §3.7: "The `AFTER_HOURS` band covers local times from 18:00:00
        inclusive up to but not including 22:00:00 and carries a rate of 0.25"

        Design: Difficulty/combinatorial_formula/cf_emergency_surcharge_tier_and_cap
        """
        job, tech_h = self._setup_after_hours_install()
        completed = validate_success(api.complete_job(job["id"], tech_h))
        assert completed["emergency_surcharge_cents"] == 18000, (
            f"Expected emergency_surcharge_cents 18000, got {completed['emergency_surcharge_cents']}"
        )

    def test_final_total_includes_surcharge_is_90000(self, api):
        """PRD §3.6: "The third component is the `emergency_surcharge_cents`
        described in §3.7. The `final_total_cents` is the consumed-parts cost
        plus the labor cost plus the emergency surcharge."

        Design: Difficulty/combinatorial_formula/cf_emergency_surcharge_tier_and_cap
        """
        job, tech_h = self._setup_after_hours_install()
        completed = validate_success(api.complete_job(job["id"], tech_h))
        assert completed["final_total_cents"] == 90000, (
            f"Expected final_total_cents 90000, got {completed['final_total_cents']}"
        )


# ===========================================================================
# Difficulty / boundary_precision_check / bpc_after_hours_band_at_exactly_1800_local
# ===========================================================================
def test_surcharge_at_exactly_1800_local_is_after_hours_clamped_to_floor(api):
    """PRD §3.7: "note that a local time of exactly 18:00:00 falls in
    `AFTER_HOURS`, not `BUSINESS`."
    PRD §3.7: "a positive surcharge below the floor is lifted to 5,000 cents"

    Design: Difficulty/boundary_precision_check/bpc_after_hours_band_at_exactly_1800_local
    """
    # scheduled_start 2026-07-01T01:00:00Z == 18:00:00 America/Phoenix local.
    # base = consumed cable 4000*1.35 = 5400; raw surcharge 5400*0.25 = 1350;
    # positive and below floor -> clamped up to 5000.
    customer = create_customer(time_zone="America/Phoenix")
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    cable = create_part(category="CABLE", unit_price_cents=4000, markup_pct=0.35, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"],
        [{"item_kind": "PART", "item_ref_id": cable["id"], "qty": 1, "unit_price_cents": 4000}],
        quote_type="SERVICE_CALL",
        service_call_fee_cents=0,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(
        job["id"], technician["id"],
        start="2026-07-01T01:00:00Z", end="2026-07-01T03:00:00Z", is_emergency=True,
    )
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    consume_all_reservations(job["id"], technician["id"])
    get_success_data(api.safety_check_job(job["id"], tech_h))
    completed = validate_success(api.complete_job(job["id"], tech_h))
    assert completed["emergency_surcharge_cents"] == 5000, (
        f"Expected surcharge clamped to floor 5000, got {completed['emergency_surcharge_cents']}"
    )


def test_final_total_at_1800_boundary_includes_clamped_surcharge(api):
    """PRD §3.6: "The `final_total_cents` is the consumed-parts cost plus the
    labor cost plus the emergency surcharge."
    PRD §3.7: "a positive surcharge below the floor is lifted to 5,000 cents"

    Design: Difficulty/boundary_precision_check/bpc_after_hours_band_at_exactly_1800_local
    """
    # Same 18:00-local boundary flow: base = consumed cable 5400 + labor 0 (fee 0);
    # surcharge clamped to 5000; final = 5400 + 0 + 5000 = 10400.
    customer = create_customer(time_zone="America/Phoenix")
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    cable = create_part(category="CABLE", unit_price_cents=4000, markup_pct=0.35, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"],
        [{"item_kind": "PART", "item_ref_id": cable["id"], "qty": 1, "unit_price_cents": 4000}],
        quote_type="SERVICE_CALL",
        service_call_fee_cents=0,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(
        job["id"], technician["id"],
        start="2026-07-01T01:00:00Z", end="2026-07-01T03:00:00Z", is_emergency=True,
    )
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    consume_all_reservations(job["id"], technician["id"])
    get_success_data(api.safety_check_job(job["id"], tech_h))
    completed = validate_success(api.complete_job(job["id"], tech_h))
    assert completed["final_total_cents"] == 10400, (
        f"Expected final_total_cents 10400 (5400 parts + 5000 surcharge), got {completed['final_total_cents']}"
    )


# ===========================================================================
# Difficulty / non_linear_state_machine / nlsm_job_parallel_dispatch_billing_dimensions
# ===========================================================================
class TestParallelDispatchBillingDimensions:
    def _setup_completed_unbilled(self):
        """SERVICE_CALL job completed (dispatch COMPLETED) but not invoiced
        (billing still PENDING)."""
        customer = create_customer(time_zone="America/Phoenix")
        technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
        quote = create_sent_quote(
            customer["id"], [{"item_kind": "LABOR", "qty": 30}],
            quote_type="SERVICE_CALL", service_call_fee_cents=6000,
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        job = schedule_job(job["id"], technician["id"])
        tech_h = make_technician_headers(technician["id"])
        get_success_data(api_client.depart_job(job["id"], tech_h))
        get_success_data(api_client.arrive_job(job["id"], tech_h))
        get_success_data(api_client.safety_check_job(job["id"], tech_h))
        return job, tech_h

    def test_complete_advances_dispatch_to_completed(self, api):
        """PRD §3.6: "Completing the job moves it from `ON_SITE` to `COMPLETED`
        and is gated by two business checks."

        Design: Difficulty/non_linear_state_machine/nlsm_job_parallel_dispatch_billing_dimensions
        """
        job, tech_h = self._setup_completed_unbilled()
        completed = validate_success(api.complete_job(job["id"], tech_h))
        assert completed["dispatch_status"] == "COMPLETED", (
            f"Expected dispatch_status COMPLETED, got {completed['dispatch_status']}"
        )

    def test_billing_stays_pending_until_invoiced(self, api):
        """PRD §3.8: "The billing dimension of a job runs in parallel with the
        dispatch dimension and begins at `PENDING`."

        Design: Difficulty/non_linear_state_machine/nlsm_job_parallel_dispatch_billing_dimensions
        """
        job, tech_h = self._setup_completed_unbilled()
        completed = validate_success(api.complete_job(job["id"], tech_h))
        assert completed["billing_status"] == "PENDING", (
            f"Expected billing_status PENDING after complete, got {completed['billing_status']}"
        )


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / ppvc_safety_beats_referential_on_complete
# ===========================================================================
def test_complete_with_no_safety_and_held_reservation_returns_safety_first(api):
    """PRD §3.6: "First, the job cannot be completed unless
    `safety_inspection_passed` is true; if it is still false, the completion is
    rejected with `ERR_SAFETY_NOT_PASSED`."
    PRD §3.6: "Second, every part reservation on the job must be in `CONSUMED`
    status; if any reservation is still `HELD`, the completion is rejected with
    `ERR_PARTS_NOT_CONSUMED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_referential_on_complete
    """
    # ON_SITE job: safety NOT passed AND one HELD reservation. Safety check is
    # stated "First", parts-consumption "Second", so ERR_SAFETY_NOT_PASSED fires.
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    cable = create_part(category="CABLE", unit_price_cents=4000, markup_pct=0.35, on_hand_qty=10)
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
    # Neither safety-check nor consume performed.
    resp = api.complete_job(job["id"], tech_h)
    validate_error(resp, ApiErrorId.ERR_SAFETY_NOT_PASSED.value, 409)


def test_complete_rejection_leaves_job_on_site(api):
    """PRD §3.6: "Completing the job moves it from `ON_SITE` to `COMPLETED` and
    is gated by two business checks. First, the job cannot be completed unless
    `safety_inspection_passed` is true; if it is still false, the completion is
    rejected with `ERR_SAFETY_NOT_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_referential_on_complete
    """
    # The rejected completion must not advance the dispatch status: it stays ON_SITE.
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    cable = create_part(category="CABLE", unit_price_cents=4000, markup_pct=0.35, on_hand_qty=10)
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
    api.complete_job(job["id"], tech_h)  # rejected (no safety, HELD reservation)
    fetched = get_success_data(api.get_job(job["id"], make_service_manager_headers()))
    assert fetched["dispatch_status"] == "ON_SITE", (
        f"Expected job to remain ON_SITE after rejected complete, got {fetched['dispatch_status']}"
    )
