"""Responsibility determinations, segregation of duties, and work-order
costing variants (PRD §3.7, §2.8, §2.10)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_territory_technician_crew, setup_monitoring_incident,
    draft_determination, finalize_determination, get_incident,
    list_work_orders, get_work_order, set_clock,
    TEST_USERS, make_supervisor_headers,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


def _setup_leak_confirmed_incident(priority="P2", address="3 Ash Ct",
                                   caller="Jack", phone="555-0109",
                                   reading_context="OUTSIDE", pct_lel=4.0,
                                   location_context="OUTSIDE_STRUCTURE",
                                   **kwargs):
    """Territory + on-shift technician + crew + leak-confirmed MONITORING
    incident. Returns (terr, tech, crew, call, incident, disp)."""
    terr, tech, crew = setup_territory_technician_crew(**kwargs)
    call, incident, disp = setup_monitoring_incident(
        terr["id"], tech["id"], priority=priority, leak_confirmed=True,
        pct_lel=pct_lel, reading_context=reading_context,
        address_line=address, caller_name=caller, caller_phone=phone,
        location_context=location_context)
    return terr, tech, crew, call, incident, disp


class TestResponsibilityFinalizationCascade:
    def test_outside_company_finalize_auto_creates_work_order(self, api):
        """PRD §3.7: "when it is `OUTSIDE_COMPANY` or `SHARED`, the server
        auto-creates a repair work order with `origin` `AUTO_DETERMINATION` in
        status `OPEN`, priced from the provisional matrix below, and — because
        `OPEN` work orders hold no reservation — no budget moves yet." The
        matrix: "For `OUTSIDE_COMPANY` the figures are 150,000 cents at `P1`,
        90,000 at `P2`, 45,000 at `P3`, and 20,000 at `P4`."

        Design: Difficulty/transitive_cascade/responsibility_finalization_work_order_budget_cascade
        """
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident()
        det = draft_determination(call["incident_id"], "OUTSIDE_COMPANY",
                                  "METER_LOCATION", drafter="sup-1")
        finalize_determination(det["id"], finalizer="sup-2")

        orders = list_work_orders(call["incident_id"])
        assert len(orders) == 1
        wo = orders[0]
        assert wo["origin"] == "AUTO_DETERMINATION"
        assert wo["status"] == "OPEN"
        assert wo["provisional_estimate_cents"] == 90000  # OUTSIDE_COMPANY x P2

        # Hop 3: scheduling the auto-created order reserves its estimate.
        validate_success(api_client.schedule_work_order(
            wo["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T10:00:00Z"},
            SUPERVISOR))
        scheduled = get_work_order(wo["id"])
        assert scheduled["status"] == "SCHEDULED"
        from test_helpers import get_territory
        terr_after = get_territory(terr["id"])
        assert terr_after["repair_reserved_cents"] == 90000

    def test_inside_customer_finalize_creates_no_work_order(self, api):
        """PRD §3.7: "when the determination is `INSIDE_CUSTOMER`, the
        incident's `customer_referral_required` flag sets to true and no
        company work order results" and "the incident's `responsibility`
        recomputes to the newly final value".

        Design: Difficulty/transitive_cascade/responsibility_finalization_work_order_budget_cascade
        """
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            address="8 Ash Ct", caller="Kim", phone="555-0110", pct_lel=1.5,
            reading_context="INSIDE", location_context="INSIDE_STRUCTURE")
        det = draft_determination(call["incident_id"], "INSIDE_CUSTOMER",
                                  "CUSTOMER_APPLIANCE_TRACE", drafter="sup-1")
        finalize_determination(det["id"], finalizer="sup-2")

        orders = list_work_orders(call["incident_id"])
        assert len(orders) == 0, "INSIDE_CUSTOMER creates no company work order"

        incident = get_incident(call["incident_id"])
        assert incident["customer_referral_required"] is True
        assert incident["responsibility"] == "INSIDE_CUSTOMER"


class TestSegregationOfDuties:
    def test_supervisor_cannot_finalize_own_draft_returns_403(self, api):
        """PRD §3.7: "the finalizer's `X-User-ID` must differ from
        `drafted_by_user_id`, or the request fails with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." and "Finalization stamps
        `finalized_at` and `finalized_by_user_id`".

        Design: Corner/rbac/supervisor_cannot_finalize_own_draft_returns_403
        """
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            address="11 Sod St", caller="Z11", phone="555-0235")
        det = draft_determination(call["incident_id"], "OUTSIDE_COMPANY",
                                  "METER_LOCATION", drafter="sup-1")

        resp = api_client.finalize_determination(det["id"],
                                                 make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        current = validate_success(api_client.get_determination(det["id"],
                                                                SUPERVISOR))
        assert current["status"] == "DRAFT"

        finalized = finalize_determination(det["id"], finalizer="sup-2")
        assert finalized["status"] == "FINAL"
        assert finalized["finalized_by_user_id"] == "sup-2"


class TestWorkOrderScheduleRequiresFinalDetermination:
    def test_schedule_rejected_while_determination_draft(self, api):
        """PRD §3.7 schedule gates: "a `FINAL` responsibility determination
        must exist for the incident (`ERR_DETERMINATION_REQUIRED`, HTTP 422)".
        Manual creation is legal before finalization: "manual creation is
        permitted only on an incident whose `leak_confirmed` flag is true" and
        "the undetermined row applying when no final determination exists" —
        "a flat 60,000 cents regardless of priority".

        Design: Difficulty/cross_entity_state_dependency/work_order_schedule_requires_final_determination
        """
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            address="60 Chestnut St", caller="Sam", phone="555-0118", pct_lel=6.0)
        inc_id = call["incident_id"]
        wo = validate_success(api_client.create_work_order(inc_id, SUPERVISOR),
                              expected_status=201)
        assert wo["origin"] == "MANUAL"
        assert wo["status"] == "OPEN"
        assert wo["provisional_estimate_cents"] == 60000

        # Determination still DRAFT at this point.
        det = draft_determination(inc_id, "OUTSIDE_COMPANY", "EXCAVATION",
                                  drafter="sup-1")

        resp = api_client.schedule_work_order(
            wo["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T09:00:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_REQUIRED)

    def test_schedule_succeeds_after_finalization(self, api):
        """PRD §3.7: "A successful schedule moves the order `OPEN →
        SCHEDULED`, stores the crew and window, increments the order
        `version`, and adds the current estimate to the territory
        reservation."

        Design: Difficulty/cross_entity_state_dependency/work_order_schedule_requires_final_determination
        """
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            address="60 Chestnut St", caller="Sam", phone="555-0118", pct_lel=6.0)
        inc_id = call["incident_id"]
        wo = validate_success(api_client.create_work_order(inc_id, SUPERVISOR),
                              expected_status=201)
        det = draft_determination(inc_id, "OUTSIDE_COMPANY", "EXCAVATION",
                                  drafter="sup-1")
        finalize_determination(det["id"], finalizer="sup-2")

        scheduled = validate_success(api_client.schedule_work_order(
            wo["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T09:00:00Z"},
            SUPERVISOR))
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["crew_id"] == crew["id"]

        from test_helpers import get_territory
        terr_after = get_territory(terr["id"])
        assert terr_after["repair_reserved_cents"] == 60000


class TestRepairCostProvisionalVsFinalVariants:
    def _setup_in_progress_auto_order(self):
        """P3 leak-confirmed incident with FINAL OUTSIDE_COMPANY
        determination; the auto-created work order scheduled and started."""
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            priority="P3", address="20 Oak Ave", caller="Bob", phone="555-0101",
            pct_lel=3.0)
        det = draft_determination(call["incident_id"], "OUTSIDE_COMPANY",
                                  "BARHOLE_SURVEY", drafter="sup-1")
        finalize_determination(det["id"], finalizer="sup-2")
        wo = list_work_orders(call["incident_id"])[0]
        validate_success(api_client.schedule_work_order(
            wo["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T10:00:00Z"},
            SUPERVISOR))
        validate_success(api_client.start_work_order(wo["id"], SUPERVISOR))
        return terr, tech, crew, call, wo

    def test_provisional_estimate_from_matrix_at_creation(self, api):
        """PRD §3.7: "The `provisional_estimate_cents` is fixed at creation
        from a matrix keyed by the responsibility in force at creation time
        and the incident's current priority. For `OUTSIDE_COMPANY` the figures
        are 150,000 cents at `P1`, 90,000 at `P2`, 45,000 at `P3`, and 20,000
        at `P4`."

        Design: Difficulty/dual_variant_calc/repair_cost_provisional_vs_final_variants
        """
        terr, tech, crew, call, wo = self._setup_in_progress_auto_order()
        current = get_work_order(wo["id"])
        assert current["provisional_estimate_cents"] == 45000  # OUTSIDE_COMPANY x P3
        assert current["current_estimate_cents"] == 45000, (
            "current_estimate mirrors the provisional estimate while non-terminal")

    def test_final_cost_computed_at_completion(self, api):
        """PRD §3.7: "First, each parts line is priced on its own: the line's
        `quantity` times its `unit_price_cents` times one minus its
        `discount_pct`, rounded half up to a whole cent... Second, labor is
        quantized to the quarter hour: `labor_billed_minutes` is
        `labor_minutes` rounded up to the next multiple of fifteen... Third,
        the labor charge is `labor_billed_minutes` divided by sixty and
        multiplied by the assigned crew's `hourly_rate_cents`, rounded half up
        to a whole cent." and "Completion then sets `current_estimate_cents`
        to the final cost".

        Design: Difficulty/dual_variant_calc/repair_cost_provisional_vs_final_variants
        """
        terr, tech, crew, call, wo = self._setup_in_progress_auto_order()
        completed = validate_success(api_client.complete_work_order(
            wo["id"],
            {"lines": [
                {"description": "pipe section", "quantity": 7,
                 "unit_price_cents": 333, "discount_pct": 0.05},
                {"description": "clamp", "quantity": 1,
                 "unit_price_cents": 999, "discount_pct": 0.05},
             ], "labor_minutes": 45},
            SUPERVISOR))
        # Per-line: round_half_up(7*333*0.95)=2214; round_half_up(1*999*0.95)=949.
        # Labor: 45 is an exact multiple of 15 -> billed as itself (45)
        # -> 45/60 h * 6000c = 4500c.
        assert completed["labor_billed_minutes"] == 45
        assert completed["final_cost_cents"] == 7663  # 2214 + 949 + 4500
        assert completed["current_estimate_cents"] == 7663
        assert completed["provisional_estimate_cents"] == 45000
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None


class TestRepairFinalCostPerLineRoundingOrder:
    def _setup_in_progress_manual_order(self):
        """MANUAL work order (UNDETERMINED estimate) progressed to
        IN_PROGRESS; a SHARED determination is then finalized, auto-creating a
        second order."""
        terr, tech, crew, call, incident, disp = _setup_leak_confirmed_incident(
            priority="P2", address="9 Pine Rd", caller="Dan", phone="555-0103",
            pct_lel=2.0, reading_context="INSIDE",
            location_context="INSIDE_STRUCTURE")
        inc_id = call["incident_id"]
        wo = validate_success(api_client.create_work_order(inc_id, SUPERVISOR),
                              expected_status=201)
        det = draft_determination(inc_id, "SHARED", "EXCAVATION", drafter="sup-1")
        finalize_determination(det["id"], finalizer="sup-2")
        validate_success(api_client.schedule_work_order(
            wo["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T09:00:00Z"},
            SUPERVISOR))
        validate_success(api_client.start_work_order(wo["id"], SUPERVISOR))
        return terr, tech, crew, call, wo

    def test_per_line_rounding_precedes_parts_sum(self, api):
        """PRD §3.7: "The final cost is computed in a pinned order that never
        sums unrounded values. First, each parts line is priced on its own:
        the line's `quantity` times its `unit_price_cents` times one minus its
        `discount_pct`, rounded half up to a whole cent; the parts total is
        the sum of those per-line rounded amounts." Two 1x101c lines at 50%
        each round half up to 51c -> parts 102c (sum-then-round would give
        101c); labor 30min at 6000c/h -> 3000c; final 3102c.

        Design: Difficulty/combinatorial_formula/repair_final_cost_per_line_rounding_order
        """
        terr, tech, crew, call, wo = self._setup_in_progress_manual_order()
        completed = validate_success(api_client.complete_work_order(
            wo["id"],
            {"lines": [
                {"description": "gasket", "quantity": 1,
                 "unit_price_cents": 101, "discount_pct": 0.5},
                {"description": "sealant", "quantity": 1,
                 "unit_price_cents": 101, "discount_pct": 0.5},
             ], "labor_minutes": 30},
            SUPERVISOR))
        assert completed["labor_billed_minutes"] == 30
        assert completed["final_cost_cents"] == 3102  # 51 + 51 + 3000, not 3101
        assert completed["current_estimate_cents"] == 3102

    def test_manual_order_uses_undetermined_row_and_finalize_adds_second(self, api):
        """PRD §3.7: "When no `FINAL` determination exists at creation, the
        undetermined row applies: a flat 60,000 cents regardless of priority"
        and "when it is `OUTSIDE_COMPANY` or `SHARED`, the server auto-creates
        a repair work order with `origin` `AUTO_DETERMINATION` in status
        `OPEN`" — "For `SHARED` the figures are 75,000, 45,000, 22,500, and
        10,000 cents across `P1` to `P4`."

        Design: Difficulty/combinatorial_formula/repair_final_cost_per_line_rounding_order
        """
        terr, tech, crew, call, wo = self._setup_in_progress_manual_order()
        manual = get_work_order(wo["id"])
        assert manual["origin"] == "MANUAL"
        assert manual["provisional_estimate_cents"] == 60000

        orders = list_work_orders(call["incident_id"])
        assert len(orders) == 2
        auto = [o for o in orders if o["origin"] == "AUTO_DETERMINATION"][0]
        assert auto["provisional_estimate_cents"] == 45000  # SHARED x P2
