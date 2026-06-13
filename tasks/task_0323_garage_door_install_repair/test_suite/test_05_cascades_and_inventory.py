"""Cascades and conserved quantities: the accept->job->reservation->part depth-3
cascade, the close->warranty->customer depth-2 cascade, part-inventory
conservation on cancel, derived-field reconciliation on consume, and the
optimistic-concurrency guard on reservation create.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    validate_paginated,
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
    create_quote,
    create_sent_quote,
    add_line,
    accept_quote_get_job,
    schedule_job,
    setup_completed_job,
    setup_on_site_job,
    consume_all_reservations,
    create_warranty_plan,
    first_reservation,
    get_part,
    get_customer,
    get_job,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty / transitive_cascade / tc_quote_accept_job_reservation_part_depth3
# ===========================================================================
class TestAcceptCascadeDepth3:
    def _accept_with_part_line(self):
        """SERVICE_CALL quote with one PART line (spring qty 2), part on_hand 10.
        Accept spawns the job + a HELD reservation + bumps reserved_qty."""
        customer = create_customer()
        spring = create_part(category="SPRING", unit_price_cents=10000, markup_pct=0.35, on_hand_qty=10)
        quote = create_sent_quote(
            customer["id"],
            [{"item_kind": "PART", "item_ref_id": spring["id"], "qty": 2, "unit_price_cents": 10000}],
            quote_type="SERVICE_CALL", service_call_fee_cents=5000,
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        return spring, job

    def test_accept_reserves_part_and_updates_pools(self, api):
        """PRD §3.4: "Fourth, each reservation creation increases the corresponding
        part's `reserved_qty` and recomputes its `available_qty`"

        Design: Difficulty/transitive_cascade/tc_quote_accept_job_reservation_part_depth3
        """
        spring, _job = self._accept_with_part_line()
        part = get_part(spring["id"])
        assert part["reserved_qty"] == 2, f"Expected reserved_qty 2, got {part['reserved_qty']}"
        assert part["available_qty"] == 8, f"Expected available_qty 8, got {part['available_qty']}"

    def test_accept_creates_held_reservation(self, api):
        """PRD §3.4: "Third, for every `PART` quote line, a part reservation in
        `HELD` status is created on the new job."

        Design: Difficulty/transitive_cascade/tc_quote_accept_job_reservation_part_depth3
        """
        spring, job = self._accept_with_part_line()
        resp = api.list_part_reservations(SM, params={"part_id": spring["id"]})
        reservations, _ = validate_paginated(resp)
        assert len(reservations) == 1, f"Expected exactly one reservation, got {len(reservations)}"
        assert reservations[0]["status"] == "HELD", (
            f"Expected reservation status HELD, got {reservations[0]['status']}"
        )
        assert reservations[0]["job_id"] == job["id"]


# ===========================================================================
# Difficulty / transitive_cascade / tc_job_close_warranty_activate_customer_count_depth2
# ===========================================================================
class TestCloseWarrantyCascadeDepth2:
    def _close_job_with_pending_warranty(self):
        """Completed+paid SERVICE_CALL job with a PENDING warranty plan; close it."""
        ctx = setup_completed_job(time_zone="America/Phoenix",
                                  service_call_fee_cents=6000)
        plan = create_warranty_plan(ctx["job"]["id"], ctx["customer"]["id"], tune_ups_included=2)
        mgr_h = make_service_manager_headers("manager-1")
        get_success_data(api_client.invoice_job(ctx["job"]["id"], mgr_h))
        get_success_data(api_client.pay_job(ctx["job"]["id"], mgr_h))
        get_success_data(api_client.close_job(ctx["job"]["id"], mgr_h))
        return ctx["customer"], plan

    def test_close_activates_pending_warranty(self, api):
        """PRD §3.8: "Closing carries a cascade: if a warranty plan exists for
        this job in `PENDING` status, it is activated to `ACTIVE`, and that
        activation increments the owning customer's `active_warranty_count` by one."

        Design: Difficulty/transitive_cascade/tc_job_close_warranty_activate_customer_count_depth2
        """
        _customer, plan = self._close_job_with_pending_warranty()
        fetched = get_success_data(api.get_warranty_plan(plan["id"], SM))
        assert fetched["status"] == "ACTIVE", (
            f"Expected warranty plan ACTIVE after close, got {fetched['status']}"
        )

    def test_close_increments_customer_active_warranty_count(self, api):
        """PRD §3.8: "and that activation increments the owning customer's
        `active_warranty_count` by one."

        Design: Difficulty/transitive_cascade/tc_job_close_warranty_activate_customer_count_depth2
        """
        customer, _plan = self._close_job_with_pending_warranty()
        fetched = get_customer(customer["id"])
        assert fetched["active_warranty_count"] == 1, (
            f"Expected active_warranty_count 1 after close, got {fetched['active_warranty_count']}"
        )


# ===========================================================================
# Difficulty / compensating_invariant / ci_part_inventory_conservation_on_cancel
# ===========================================================================
class TestPartInventoryConservationOnCancel:
    def _scheduled_job_with_held_reservation(self):
        customer = create_customer()
        technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
        spring = create_part(category="SPRING", unit_price_cents=10000, markup_pct=0.35, on_hand_qty=10)
        quote = create_sent_quote(
            customer["id"],
            [{"item_kind": "PART", "item_ref_id": spring["id"], "qty": 2, "unit_price_cents": 10000}],
            quote_type="SERVICE_CALL", service_call_fee_cents=5000,
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        job = schedule_job(job["id"], technician["id"],
                           start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
        return spring, job

    def test_reserved_before_cancel(self, api):
        """PRD §3.4: "Fourth, each reservation creation increases the corresponding
        part's `reserved_qty` and recomputes its `available_qty`"

        Design: Difficulty/compensating_invariant/ci_part_inventory_conservation_on_cancel
        """
        spring, _job = self._scheduled_job_with_held_reservation()
        part = get_part(spring["id"])
        assert part["reserved_qty"] == 2 and part["available_qty"] == 8, (
            f"Expected reserved 2/available 8 pre-cancel, got "
            f"{part['reserved_qty']}/{part['available_qty']}"
        )

    def test_cancel_releases_reservation_and_conserves_inventory(self, api):
        """PRD §3.5: "every `HELD` part reservation on the job is moved to
        `RELEASED`, and each release decreases the corresponding part's
        `reserved_qty` and recomputes its `available_qty`"
        PRD §2.9: "`available_qty` is always `on_hand_qty` minus `reserved_qty`"

        Design: Difficulty/compensating_invariant/ci_part_inventory_conservation_on_cancel
        """
        spring, job = self._scheduled_job_with_held_reservation()
        get_success_data(api.cancel_job(job["id"], DISPATCHER))
        part = get_part(spring["id"])
        assert part["on_hand_qty"] == 10, f"Expected on_hand_qty 10, got {part['on_hand_qty']}"
        assert part["reserved_qty"] == 0, f"Expected reserved_qty 0 after cancel, got {part['reserved_qty']}"
        assert part["available_qty"] == 10, f"Expected available_qty 10 after cancel, got {part['available_qty']}"


# ===========================================================================
# Corner / cross_cutting_complexity_layers / derived_reservation_consume_decrements_on_hand
# ===========================================================================
def test_consume_reservation_decrements_on_hand_and_reserved(api):
    """PRD §3.9: "consuming requires that the parent job's dispatch status is
    `ON_SITE`, moves the reservation from `HELD` to `CONSUMED`, and decreases both
    the part's `on_hand_qty` and its `reserved_qty` by the reservation `qty`,
    recomputing `available_qty` — the consumed stock leaves both pools, keeping
    inventory conserved."

    Design: Corner/cross_cutting_complexity_layers/derived_reservation_consume_decrements_on_hand
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    spring = create_part(category="SPRING", unit_price_cents=10000, markup_pct=0.35, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"],
        [{"item_kind": "PART", "item_ref_id": spring["id"], "qty": 2, "unit_price_cents": 10000}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(job["id"], technician["id"])
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    resv = first_reservation(job["id"])
    get_success_data(api.consume_part_reservation(resv["id"], tech_h))
    part = get_part(spring["id"])
    assert part["on_hand_qty"] == 8, f"Expected on_hand_qty 8 after consume, got {part['on_hand_qty']}"
    assert part["reserved_qty"] == 0, f"Expected reserved_qty 0 after consume, got {part['reserved_qty']}"
    assert part["available_qty"] == 8, f"Expected available_qty 8 after consume, got {part['available_qty']}"


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_reservation_correct_version_succeeds
# ===========================================================================
def test_manual_reservation_with_correct_version_succeeds_and_bumps_job_version(api):
    """PRD §3.9: "A successful manual create records the reservation in `HELD`
    status, increases the part's `reserved_qty`, recomputes its `available_qty`,
    and advances the job's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_correct_version_succeeds
    """
    customer = create_customer()
    part = create_part(category="SENSOR", unit_price_cents=3000, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job_v = get_job(job["id"])["version"]
    created = validate_success(
        api.create_part_reservation(
            {"job_id": job["id"], "part_id": part["id"], "qty": 1, "expected_job_version": job_v},
            DISPATCHER,
        ),
        201,
    )
    assert created["status"] == "HELD", f"Expected reservation HELD, got {created['status']}"
    after = get_job(job["id"])
    assert after["version"] == job_v + 1, (
        f"Expected job version {job_v + 1} after reservation create, got {after['version']}"
    )


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_reservation_create_stale_job_version
# ===========================================================================
def test_manual_reservation_with_stale_job_version_rejected(api):
    """PRD §2.6: "If `expected_job_version` does not equal the job's current
    `version`, the reservation create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_create_stale_job_version
    """
    customer = create_customer()
    sensor = create_part(category="SENSOR", unit_price_cents=3000, on_hand_qty=10)
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    stale_v = get_job(job["id"])["version"]
    # First create at the current version succeeds and bumps job.version.
    validate_success(
        api.create_part_reservation(
            {"job_id": job["id"], "part_id": sensor["id"], "qty": 1, "expected_job_version": stale_v},
            DISPATCHER,
        ),
        201,
    )
    # Second create still carrying the pre-bump version is rejected.
    resp = api.create_part_reservation(
        {"job_id": job["id"], "part_id": sensor["id"], "qty": 1, "expected_job_version": stale_v},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
