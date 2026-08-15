"""Fleet credit governance: the issue-time suspension cascade, month
rollover reinstatement, immediate consistency, and fleet close gating."""
from test_helpers import (
    TEST_USERS,
    adjust_fleet_spend,
    advance_clock,
    create_dispatch,
    create_fleet,
    create_invoice_for_call,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    get_call,
    get_success_data,
    intake_call,
    issue_invoice,
    open_triaged_call,
    run_daily,
    run_on_site_repair,
    setup_s1_completed_job,
    stock_van,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _suspension_cascade_scenario():
    """Fleet cap 300000 with month spend 200000; an after-hours MASTER job
    invoiced at 200995 (not yet issued); a second fleet call DISPATCHED with
    a PROPOSED dispatch; a third fleet call sitting in RECEIVED."""
    create_standard_rate_card()
    fleet = create_fleet(per_call_authorization_limit_cents=100000,
                         monthly_spend_cap_cents=300000)
    adjust_fleet_spend(fleet["id"], 200000)
    veh1 = create_vehicle(fleet_account_id=fleet["id"], odometer_miles=120000,
                          unit_number="U-101")
    veh2 = create_vehicle(fleet_account_id=fleet["id"], odometer_miles=60000,
                          unit_number="U-102")
    veh3 = create_vehicle(fleet_account_id=fleet["id"], odometer_miles=70000,
                          unit_number="U-103")
    master, master_headers = create_technician(labor_rate_class="MASTER",
                                               full_name="Rita Master")
    stock = stock_van(master["id"], part_number="STARTER-9",
                      description="Starter motor", qty_on_hand=10,
                      unit_cost_cents=41000, unit_retail_cents=82000)
    spare, spare_headers = create_technician(full_name="Tom Standard")

    job = run_on_site_repair(
        veh1["id"], master["id"], master_headers, severity="BLOCKING",
        received_at="2026-08-03T18:30:00Z",
        window=("2026-08-03T18:30:00Z", "2026-08-03T23:30:00Z"),
        planned_travel_miles=30, depart_at="2026-08-03T19:10:00Z",
        arrive_at="2026-08-03T20:30:00Z", actual_travel_miles=30,
        labor_hours_actual=2.0, completion_odometer_miles=120500,
        parts=[{"item_id": stock["id"], "qty": 1}],
        diagnosis_summary="starter failed")
    invoice = create_invoice_for_call(job["call"]["id"])
    assert invoice["total_cents"] == 200995

    call2 = open_triaged_call(veh2["id"], severity="DRIVABLE",
                              received_at=None,
                              breakdown_location_text="I-25 mm 88",
                              distance_miles_from_depot=15,
                              symptom_description="intermittent start")
    dispatch2 = create_dispatch(call2["id"], spare["id"],
                                "2026-08-04T08:00:00Z", "2026-08-04T12:00:00Z",
                                planned_travel_miles=15)
    call3 = intake_call(veh3["id"], symptom_category="LIGHTING",
                        breakdown_location_text="depot",
                        distance_miles_from_depot=5,
                        symptom_description="marker lamps out")
    return {"fleet": fleet, "invoice": invoice, "job": job,
            "call2": call2, "dispatch2": dispatch2, "call3": call3}


class TestIssueSuspensionCascade:
    def test_cascade_invoice_issue_suspends_fleet(self, api):
        """PRD: "the invoice's `total_cents` is added to the fleet's
        `month_to_date_spend_cents`, and if that pushes the month total
        strictly above `monthly_spend_cap_cents`, the fleet is suspended to
        `SUSPENDED` with `suspension_reason` `CREDIT_HOLD`".

        Design: Difficulty/transitive_cascade/cascade_invoice_issue_suspends_fleet_and_expires_dispatches
        """
        ctx = _suspension_cascade_scenario()
        issue_invoice(ctx["invoice"]["id"])
        fleet = get_success_data(api.get_fleet_account(ctx["fleet"]["id"], OPS))
        assert fleet["month_to_date_spend_cents"] == 400995, (
            "200000 adjustment + 200995 issued total")
        assert fleet["status"] == "SUSPENDED"
        assert fleet["suspension_reason"] == "CREDIT_HOLD", (
            "400995 > 300000 cap")
        invoice = get_success_data(
            api.get_invoice(ctx["invoice"]["id"], TEST_USERS[
                "billing_clerk_headers"]))
        assert invoice["issue_status"] == "ISSUED", (
            "the completed job's billing is not rolled back")

    def test_cascade_flags_open_calls_and_expires_proposed_dispatches(
            self, api):
        """PRD: "every one of that fleet's calls sitting in `RECEIVED`,
        `TRIAGED`, or `DISPATCHED` is then flagged with `hold_reason`
        `FLEET_CREDIT_HOLD` and a `HOLD_FLAGGED` event; every `PROPOSED`
        dispatch of those calls is expired, and any `DISPATCHED` call whose
        dispatch expired reverts to `TRIAGED`."

        Design: Difficulty/transitive_cascade/cascade_invoice_issue_suspends_fleet_and_expires_dispatches
        """
        ctx = _suspension_cascade_scenario()
        issue_invoice(ctx["invoice"]["id"])
        call2 = get_call(ctx["call2"]["id"])
        call3 = get_call(ctx["call3"]["id"])
        assert call2["hold_reason"] == "FLEET_CREDIT_HOLD"
        assert call3["hold_reason"] == "FLEET_CREDIT_HOLD"
        dispatch2 = get_success_data(
            api.get_dispatch(ctx["dispatch2"]["id"], DISPATCHER))
        assert dispatch2["status"] == "EXPIRED"
        assert call2["status"] == "TRIAGED", (
            "the expired PROPOSED dispatch reverts the DISPATCHED call")


class TestMonthRolloverReinstatement:
    def test_month_rollover_resets_mtd_and_reinstates_credit_hold(self, api):
        """PRD: the daily run "re-evaluates each fleet suspended for credit
        reasons, reinstating any whose month-to-date spend has fallen back
        within cap — including the natural month rollover, where the passing
        of the clock into a new calendar month empties the month-to-date
        window."

        Design: Corner/calculations/month_rollover_resets_mtd_and_reinstates_credit_hold
        """
        # setup_s1_completed_job publishes the STD-2026 card itself.
        fleet = create_fleet(per_call_authorization_limit_cents=100000,
                             monthly_spend_cap_cents=140000)
        adjust_fleet_spend(fleet["id"], 10000, reason="correction")
        ctx = setup_s1_completed_job(fleet=fleet)
        invoice = create_invoice_for_call(ctx["call"]["id"])
        issue_invoice(invoice["id"])
        august = get_success_data(api.get_fleet_account(fleet["id"], OPS))
        assert august["status"] == "SUSPENDED", (
            "credit hold at 146698 > 140000")

        advance_clock("2026-09-01T00:05:00Z")
        counts = run_daily()
        assert counts["reinstated_fleet_count"] == 1
        september = get_success_data(api.get_fleet_account(fleet["id"], OPS))
        assert september["status"] == "ACTIVE"
        assert september["month_to_date_spend_cents"] == 0, (
            "the September window contains no issued invoices")


class TestImmediateConsistency:
    def test_immediate_consistency_after_invoice_issue(self, api):
        """PRD: "the invoice's `total_cents` is added to the fleet's
        `month_to_date_spend_cents`" at issue — the very next read reflects
        the new month total with no reconciliation delay.

        Design: Corner/consistency_model/immediate_consistency_after_invoice_issue
        """
        # setup_s1_completed_job publishes the STD-2026 card itself.
        fleet = create_fleet()
        ctx = setup_s1_completed_job(fleet=fleet)
        invoice = create_invoice_for_call(ctx["call"]["id"])
        issue_invoice(invoice["id"])
        fleet_now = get_success_data(
            api.get_fleet_account(fleet["id"], TEST_USERS[
                "billing_clerk_headers"]))
        assert fleet_now["month_to_date_spend_cents"] == 136698
        call_now = get_call(ctx["call"]["id"])
        assert call_now["status"] == "INVOICED", (
            "issue side effects are atomic with the response")


class TestFleetCloseGating:
    def test_fleet_close_blocked_then_closed_gates_intake(self, api):
        """PRD: "Closing a fleet is permitted only when none of its service
        calls remains in a non-terminal status; otherwise the close is
        rejected with `ERR_FLEET_HAS_OPEN_CALLS`." and "against a `CLOSED`
        fleet with `ERR_FLEET_CLOSED`" — intake is one of the four
        fleet-gated writes.

        Design: Corner/consistency_model/fleet_close_blocked_then_closed_gates_intake
        """
        create_standard_rate_card()
        fleet = create_fleet()
        veh = create_vehicle(fleet_account_id=fleet["id"],
                             odometer_miles=120000)
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DRIVABLE")

        blocked = api.close_fleet_account(fleet["id"], OPS)
        validate_error(blocked, ApiErrorId.ERR_FLEET_HAS_OPEN_CALLS)

        validate_success(api.cancel_service_call(
            call["id"], {"reason": "customer cancelled"}, DISPATCHER))
        closed = validate_success(api.close_fleet_account(fleet["id"], OPS))
        assert closed["status"] == "CLOSED"

        resp = api.create_service_call(
            {"vehicle_id": veh["id"], "caller_name": "Sam",
             "caller_phone": "555-0100", "breakdown_location_text": "yard",
             "distance_miles_from_depot": 5, "symptom_category": "LIGHTING",
             "symptom_description": "lamps"},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_FLEET_CLOSED)
