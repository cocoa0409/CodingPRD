"""Work estimates: provisional pricing, the revision cycle, OCC, the
repair-start gate, and the fleet authorization / monthly-cap fiscal gates."""
from test_helpers import (
    TEST_USERS,
    adjust_fleet_spend,
    advance_clock,
    approve_estimate,
    create_estimate,
    create_estimate_payload,
    create_fleet,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_call,
    get_success_data,
    make_fleet_manager_headers,
    open_triaged_call,
    run_daily,
    start_repair,
    submit_estimate,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _diagnosed_call_with_tech(fleet=None, received_at="2026-08-05T10:00:00Z",
                              severity="DEFERRED", labor_rate_class="STANDARD",
                              window=("2026-08-05T10:00:00Z",
                                      "2026-08-05T14:00:00Z"),
                              arrive_at="2026-08-05T10:45:00Z",
                              actual_travel_miles=20):
    """Retail-or-fleet call diagnosed ON_SITE_REPAIR. Returns (call, tech,
    tech_headers, dispatch)."""
    create_standard_rate_card()
    veh = create_vehicle(fleet_account_id=fleet["id"] if fleet else None)
    tech, tech_headers = create_technician(labor_rate_class=labor_rate_class)
    call = open_triaged_call(veh["id"], severity=severity,
                             received_at=received_at)
    call, dispatch = drive_call_on_site(
        call, tech["id"], tech_headers, window[0], window[1],
        arrive_at=arrive_at, actual_travel_miles=actual_travel_miles)
    call = diagnose_call(call["id"], tech_headers,
                         diagnosis_summary="glow plug circuit")
    return call, tech, tech_headers, dispatch


class TestEstimateRevisionCycle:
    def test_rejected_estimate_revision_recomputes_total(self, api):
        """PRD: "revising a `REJECTED` estimate moves it back to `DRAFT` and
        increments `revision` (which starts at 1 and is monotone per call),
        again recomputing the total."

        Design: Difficulty/non_linear_state_machine/work_estimate_rejected_revision_cycle
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech()
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        assert estimate["revision"] == 1
        # 14500 labor + 0 travel (20 <= 25 free miles) + 30000 parts
        # + round_half_up(30000 * 0.0725) = 2175 tax.
        assert estimate["total_cents"] == 46675
        submit_estimate(estimate["id"], headers=tech_headers)
        rejected = validate_success(api.reject_estimate(
            estimate["id"], {"reason": "too expensive"}, OPS))
        assert rejected["status"] == "REJECTED"

        revised = validate_success(api.patch_estimate(
            estimate["id"], {"parts_estimate_cents": 25000}, tech_headers))
        assert revised["status"] == "DRAFT", (
            "revising a REJECTED estimate returns it to DRAFT")
        assert revised["revision"] == 2, "revision increments on revise"
        # 14500 + 25000 + round_half_up(25000 * 0.0725) = round(1812.5) = 1813.
        assert revised["total_cents"] == 41313

    def test_revised_estimate_completes_the_approval_cycle(self, api):
        """PRD: "An estimate moves `DRAFT` to `SUBMITTED` when submitted" and
        approval moves it to `APPROVED` — the revision loop
        REJECTED -> DRAFT -> SUBMITTED -> APPROVED closes cleanly on a retail
        call (no fleet authorization gate).

        Design: Difficulty/non_linear_state_machine/work_estimate_rejected_revision_cycle
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech()
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        submit_estimate(estimate["id"], headers=tech_headers)
        validate_success(api.reject_estimate(
            estimate["id"], {"reason": "too expensive"}, OPS))
        validate_success(api.patch_estimate(
            estimate["id"], {"parts_estimate_cents": 25000}, tech_headers))

        resubmitted = submit_estimate(estimate["id"], headers=tech_headers)
        assert resubmitted["status"] == "SUBMITTED"
        approved = approve_estimate(estimate["id"], DISPATCHER)
        assert approved["status"] == "APPROVED"
        assert approved["revision"] == 2


class TestStateBeatsFiscalOnApprove:
    def _draft_over_limit_estimate(self):
        """Fleet call (limit 100000) with a DRAFT estimate totalling 102425."""
        fleet = create_fleet(per_call_authorization_limit_cents=100000)
        call, tech, tech_headers, _d = _diagnosed_call_with_tech(
            fleet=fleet, received_at="2026-08-05T09:00:00Z",
            severity="DRIVABLE",
            window=("2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z"),
            arrive_at="2026-08-05T09:50:00Z", actual_travel_miles=30)
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=30,
                                   parts_estimate_cents=80000,
                                   headers=tech_headers)
        return estimate

    def test_state_beats_fiscal_on_estimate_approve(self, api):
        """PRD: "then state-machine legality with `ERR_INVALID_STATE` and the
        terminal-call guard `ERR_CALL_ALREADY_TERMINAL`, then
        optimistic-concurrency rejection with `ERR_STALE_VERSION`, then the
        business rules described throughout Section 3" — state legality is
        evaluated before the business rules, so approving a DRAFT estimate
        reports ERR_INVALID_STATE even though the total also exceeds the
        fleet's per-call authorization limit.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_estimate_approve
        """
        estimate = self._draft_over_limit_estimate()
        # 14500 + (30-25)*425 = 2125 travel + 80000 parts + 5800 tax = 102425.
        assert estimate["total_cents"] == 102425
        assert estimate["requires_fleet_approval"] is True, (
            "102425 > 100000 limit, so the fiscal gate would also fail")
        resp = api.approve_estimate(estimate["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_rejection_leaves_estimate_unchanged(self, api):
        """PRD: "Across a whole request, checks are evaluated in a fixed
        priority order so that earlier failures are never masked by later
        ones." — the state-illegal approve fires no fiscal side effects and
        the estimate stays DRAFT.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_estimate_approve
        """
        estimate = self._draft_over_limit_estimate()
        resp = api.approve_estimate(estimate["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_estimate(estimate["id"], DISPATCHER))
        assert current["status"] == "DRAFT"


class TestAuthorizationLimitBoundary:
    def _two_fleet_estimates_at_limit_boundary(self):
        """Fleet limit 100000; two diagnosed calls carry SUBMITTED estimates
        of exactly 100000 (79720 parts) and 100001 (79721 parts)."""
        fleet = create_fleet(per_call_authorization_limit_cents=100000)
        call_a, tech, tech_headers, _d = _diagnosed_call_with_tech(
            fleet=fleet, received_at="2026-08-05T09:00:00Z",
            severity="DRIVABLE",
            window=("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"),
            arrive_at="2026-08-05T09:40:00Z", actual_travel_miles=20)
        est_eq = create_estimate(call_a["id"], labor_hours_est=1.0,
                                 travel_miles_est=20,
                                 parts_estimate_cents=79720,
                                 headers=tech_headers)
        submit_estimate(est_eq["id"], headers=tech_headers)

        # A second STANDARD technician for the second call (the first is still
        # ON_DISPATCH with an incomplete dispatch).
        spare, spare_headers = create_technician(full_name="Sam Spare")
        veh_b = create_vehicle(fleet_account_id=fleet["id"])
        call_b = open_triaged_call(veh_b["id"], severity="DRIVABLE",
                                   breakdown_location_text="I-25 mm 88")
        call_b, _db = drive_call_on_site(
            call_b, spare["id"], spare_headers, "2026-08-05T12:00:00Z",
            "2026-08-05T14:00:00Z", arrive_at="2026-08-05T12:40:00Z",
            actual_travel_miles=20)
        diagnose_call(call_b["id"], spare_headers,
                      diagnosis_summary="harness")
        est_over = create_estimate(call_b["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=79721,
                                   headers=spare_headers)
        submit_estimate(est_over["id"], headers=spare_headers)
        return fleet, est_eq, est_over

    def test_authorization_limit_equality_is_dispatcher_approvable(self, api):
        """PRD: "When the estimate's `total_cents` exceeds the fleet's
        `per_call_authorization_limit_cents` — a computed
        `requires_fleet_approval` flag surfaces exactly this condition —
        approval requires a `FleetManager` of that fleet or an `OpsAdmin`" —
        a total exactly equal to the limit does not exceed it.

        Design: Difficulty/boundary_precision_check/authorization_limit_equality_vs_one_cent_over
        """
        fleet, est_eq, est_over = \
            self._two_fleet_estimates_at_limit_boundary()
        # 14500 + 0 travel + 79720 parts + 5780 tax == 100000 == the limit.
        assert est_eq["total_cents"] == 100000
        assert est_eq["requires_fleet_approval"] is False
        # 14500 + 0 + 79721 + 5780 == 100001: one cent over.
        assert est_over["total_cents"] == 100001
        assert est_over["requires_fleet_approval"] is True

        approved = approve_estimate(est_eq["id"], DISPATCHER)
        assert approved["status"] == "APPROVED", (
            "total == limit exactly is Dispatcher-approvable")

    def test_one_cent_over_limit_requires_fleet_manager(self, api):
        """PRD: "a `Dispatcher` attempting it is rejected with
        `ERR_AUTHORIZATION_REQUIRED`" for a total strictly above the fleet's
        per-call limit, while "approval requires a `FleetManager` of that
        fleet or an `OpsAdmin`" succeeds.

        Design: Difficulty/boundary_precision_check/authorization_limit_equality_vs_one_cent_over
        """
        fleet, _est_eq, est_over = \
            self._two_fleet_estimates_at_limit_boundary()
        assert est_over["total_cents"] == 100001
        resp = api.approve_estimate(est_over["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_REQUIRED)
        approved = approve_estimate(est_over["id"],
                                    make_fleet_manager_headers(fleet["id"]))
        assert approved["status"] == "APPROVED"


class TestEstimateApproveFleetGate:
    def _submitted_estimate_then_suspend_fleet(self, api):
        fleet = create_fleet(per_call_authorization_limit_cents=100000)
        call, tech, tech_headers, _d = _diagnosed_call_with_tech(
            fleet=fleet, received_at="2026-08-05T09:00:00Z",
            severity="DEFERRED",
            window=("2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z"),
            arrive_at="2026-08-05T09:45:00Z", actual_travel_miles=20)
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        submit_estimate(estimate["id"], headers=tech_headers)
        suspended = validate_success(api.suspend_fleet_account(fleet["id"], OPS))
        assert suspended["status"] == "SUSPENDED"
        return fleet, estimate

    def test_estimate_approve_requires_active_fleet(self, api):
        """PRD: "Four fleet-scoped writes — service-call intake, dispatch
        creation, estimate approval, and invoice issue — require the fleet to
        be `ACTIVE`; against a `SUSPENDED` fleet they are rejected with
        `ERR_FLEET_SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_active_fleet
        """
        fleet, estimate = self._submitted_estimate_then_suspend_fleet(api)
        resp = api.approve_estimate(
            estimate["id"], {}, make_fleet_manager_headers(fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_FLEET_SUSPENDED)

    def test_fleet_gate_rejection_leaves_estimate_submitted(self, api):
        """PRD: "against a `SUSPENDED` fleet they are rejected with
        `ERR_FLEET_SUSPENDED`" — the estimate's own state was valid for
        approval and is left untouched by the fleet-gate rejection.

        Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_active_fleet
        """
        fleet, estimate = self._submitted_estimate_then_suspend_fleet(api)
        resp = api.approve_estimate(
            estimate["id"], {}, make_fleet_manager_headers(fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_FLEET_SUSPENDED)
        current = get_success_data(api.get_estimate(estimate["id"], DISPATCHER))
        assert current["status"] == "SUBMITTED"


class TestEstimateCreateOcc:
    def test_occ_stale_estimate_create_rejected(self, api):
        """PRD: "Creating an estimate for a call and creating a dispatch for a
        call each require a non-optional request field
        `expected_service_call_version` carrying the client's last observed
        `version` of that call. If the value does not match the call's current
        `version` ... the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)." and "Creation supersedes any prior estimate of the call
        in `DRAFT`, `SUBMITTED`, or `APPROVED` to `SUPERSEDED`".

        Design: Corner/cross_cutting_layers/occ_stale_estimate_create_rejected
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech()
        observed = get_call(call["id"])["version"]
        first = create_estimate(call["id"], labor_hours_est=1.0,
                                travel_miles_est=20,
                                parts_estimate_cents=30000,
                                headers=tech_headers)
        fresh_version = get_call(call["id"])["version"]

        stale = api.create_estimate(
            call["id"],
            create_estimate_payload(observed, labor_hours_est=1.5,
                                    travel_miles_est=20,
                                    parts_estimate_cents=31000),
            tech_headers)
        assert stale.status_code == 412
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        second = validate_success(api.create_estimate(
            call["id"],
            create_estimate_payload(fresh_version, labor_hours_est=1.5,
                                    travel_miles_est=20,
                                    parts_estimate_cents=31000),
            tech_headers), 201)
        assert second["status"] == "DRAFT"
        superseded = get_success_data(api.get_estimate(first["id"], DISPATCHER))
        assert superseded["status"] == "SUPERSEDED"


class TestStartRepairEstimateGate:
    def test_estimate_approve_from_draft_rejected(self, api):
        """PRD: "An estimate moves `DRAFT` to `SUBMITTED` when submitted" and
        approval is declared from `SUBMITTED` — approving a DRAFT estimate
        fails `ERR_INVALID_STATE` (the retail total here is under any fleet
        limit, so no fiscal rule is in play).

        Design: Corner/state_machines/estimate_approve_from_draft_rejected
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech()
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        assert estimate["total_cents"] == 46675
        resp = api.approve_estimate(estimate["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_estimate_gate_blocks_start_repair(self, api):
        """PRD: "no estimate of the call may be sitting in `DRAFT` or
        `SUBMITTED` (an `APPROVED` estimate, or no estimate at all, passes;
        otherwise `ERR_ESTIMATE_NOT_APPROVED`)".

        Design: Corner/validations/estimate_gate_blocks_start_repair
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech()
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        submit_estimate(estimate["id"], headers=tech_headers)

        resp = api.start_repair(call["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_APPROVED)

        approve_estimate(estimate["id"], DISPATCHER)
        started = start_repair(call["id"], tech_headers)
        assert started["status"] == "REPAIR_IN_PROGRESS", (
            "the gate passes once the estimate is APPROVED")


class TestMonthlyCapGate:
    def _over_cap_scenario(self):
        """Fleet mtd 250000 against cap 300000; after-hours GOLD estimate
        totalling 161444 (projected 411444 > 300000)."""
        fleet = create_fleet(per_call_authorization_limit_cents=100000,
                             monthly_spend_cap_cents=300000)
        adjust_fleet_spend(fleet["id"], 250000)
        call, tech, tech_headers, _d = _diagnosed_call_with_tech(
            fleet=fleet, received_at="2026-08-03T18:30:00Z",
            severity="BLOCKING", labor_rate_class="MASTER",
            window=("2026-08-03T18:30:00Z", "2026-08-03T23:30:00Z"),
            arrive_at="2026-08-03T20:30:00Z", actual_travel_miles=30)
        estimate = create_estimate(call["id"], labor_hours_est=2.0,
                                   travel_miles_est=30,
                                   parts_estimate_cents=80000,
                                   headers=tech_headers)
        # 52500 labor (2.0h MASTER x 1.5 after-hours) + 2125 travel
        # + 25000 P1 callout = 79625 gross; GOLD 5% discount 3981;
        # + 80000 parts + 5800 tax = 161444.
        assert estimate["total_cents"] == 161444
        submit_estimate(estimate["id"], headers=tech_headers)
        return fleet, estimate

    def test_monthly_cap_override_requires_ops_admin(self, api):
        """PRD: "when the projected month spend — the fleet's current
        `month_to_date_spend_cents` plus the estimate's `total_cents` — would
        exceed `monthly_spend_cap_cents`, approval is rejected with
        `ERR_MONTHLY_CAP_EXCEEDED` unless an `OpsAdmin` passes `override_cap`
        as true".

        Design: Corner/validations/monthly_cap_override_requires_ops_admin
        """
        fleet, estimate = self._over_cap_scenario()
        # 250000 + 161444 = 411444 > 300000.
        resp = api.approve_estimate(
            estimate["id"], {}, make_fleet_manager_headers(fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_MONTHLY_CAP_EXCEEDED)
        approved = approve_estimate(estimate["id"], OPS,
                                    payload={"override_cap": True})
        assert approved["status"] == "APPROVED"

    def test_estimate_without_covering_rate_card_rejected(self, api):
        """PRD: "otherwise the system selects the single card whose closed
        window contains the call's `received_at`, and when no card covers that
        instant the pricing operation fails with `ERR_NO_ACTIVE_RATE_CARD`."

        Design: Corner/consistency_model/estimate_without_covering_rate_card_rejected
        """
        create_standard_rate_card()  # covers calendar 2026 only
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        call = open_triaged_call(veh["id"], severity="DEFERRED",
                                 received_at="2027-01-10T14:00:00Z")
        call, _d = drive_call_on_site(
            call, tech["id"], tech_headers, "2027-01-10T14:00:00Z",
            "2027-01-10T18:00:00Z", arrive_at="2027-01-10T14:45:00Z",
            actual_travel_miles=20)
        call = diagnose_call(call["id"], tech_headers,
                             diagnosis_summary="glow plugs")
        resp = api.create_estimate(
            call["id"],
            create_estimate_payload(get_call(call["id"])["version"],
                                    labor_hours_est=1.0, travel_miles_est=20,
                                    parts_estimate_cents=30000),
            tech_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_CARD)


class TestEstimateExpiry:
    def test_stale_estimate_expires_via_run_daily(self, api):
        """PRD: "a submitted estimate left undecided for more than seven
        calendar days is moved to `EXPIRED` by the daily run" — at exactly
        submitted_at + 7 days the estimate is still live; one second later
        the sweep expires it.

        Design: Corner/calculations/stale_estimate_expires_via_run_daily
        """
        call, tech, tech_headers, _d = _diagnosed_call_with_tech(
            received_at="2026-08-03T09:00:00Z",
            window=("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z"),
            arrive_at="2026-08-03T09:40:00Z")
        advance_clock("2026-08-03T10:00:00Z")
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        submit_estimate(estimate["id"], headers=tech_headers)

        advance_clock("2026-08-10T10:00:00Z")
        counts0 = run_daily()
        assert counts0["expired_estimate_count"] == 0, (
            "exactly submitted_at + 7 days is not yet 'more than' 7 days")

        advance_clock("2026-08-10T10:00:01Z")
        counts1 = run_daily()
        assert counts1["expired_estimate_count"] == 1
        current = get_success_data(api.get_estimate(estimate["id"], DISPATCHER))
        assert current["status"] == "EXPIRED"
