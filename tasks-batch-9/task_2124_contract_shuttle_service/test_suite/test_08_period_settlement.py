"""Period settlement: provisional against final, the dispute loop, and approval."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_report,
    assert_settlement_block_zeroed,
    complete_trip,
    create_active_contract,
    create_report,
    make_client_liaison_headers,
    make_contract_admin_headers,
    set_clock,
    setup_empty_period_report,
    setup_fifty_minute_schedule_report,
    setup_four_trip_settlement_scenario,
    setup_on_time_grace_scenario,
    setup_completed_trip,
    start_trip,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


# ─── The two settlement variants over one dataset ─────────────────────────────

def test_provisional_submit_bills_the_schedule(api):
    """PRD §3.8: "The provisional set is every trip whose `contract_id` matches the
    report's, whose `service_date` lies inside the closed range from
    `period_start_date` to `period_end_date`, and whose `dispatch_status` is
    `SCHEDULED`, `ASSIGNED`, `IN_SERVICE` or `COMPLETED` — it bills the schedule, so
    trips that were never assigned and never ran still count at their planned
    duration."
    PRD §3.8: "`gross_amount_cents` is `billable_service_hours` multiplied by the
    report's frozen `effective_rate_cents_per_service_hour`, rounded half up to a
    whole number of cents."
    PRD §3.8: "`net_amount_cents` is `gross_amount_cents` minus
    `penalty_amount_cents` minus `credit_amount_cents`, clamped at a floor of
    exactly 0 so it is never negative."
    PRD §3.8: "`missed_trip_penalty_cents` is `missed_trip_count` multiplied by the
    contract's `penalty_rate_cents_per_missed_trip`, and `penalty_amount_cents` is
    `sla_penalty_cents` plus `missed_trip_penalty_cents`."
    PRD §3.8: "`credit_amount_cents` is the sum of `amount_cents` over every credit
    memo of this contract whose `status` is `ISSUED`, whose `trip_id` is not null,
    and whose trip's `service_date` falls inside the closed period range"
    PRD §3.8: "`total_boardings` is the sum of `counted_boardings` over the
    settlement input set, `total_ada_boardings` the sum of `counted_ada_boardings`
    over the same set, `scheduled_trip_count` the size of that set, and
    `completed_trip_count` the number of the period's trips whose `dispatch_status`
    is `COMPLETED`."
    PRD §3.8: "`on_time_pct` is 100.00 when `countable_trip_count` is 0, and
    otherwise is 100 multiplied by `on_time_trip_count`, divided by
    `countable_trip_count`, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/report_settlement_provisional_versus_final
    """
    scenario = setup_four_trip_settlement_scenario()

    submitted = validate_success(
        api.submit_report(scenario["report"]["id"], make_client_liaison_headers("liaison-1"))
    )
    assert_report(submitted)

    assert submitted["settlement_variant"] == "PROVISIONAL"
    assert submitted["scheduled_trip_count"] == 3, (
        "two completed trips and the untouched fourth trip bill the schedule"
    )
    assert submitted["total_billable_minutes"] == 144
    assert submitted["billable_service_hours"] == pytest.approx(2.40, abs=0.001)
    assert submitted["gross_amount_cents"] == 21_600
    assert submitted["countable_trip_count"] == 3
    assert submitted["on_time_trip_count"] == 1
    assert submitted["on_time_pct"] == pytest.approx(33.33, abs=0.001)
    assert submitted["penalty_tier_pct"] == pytest.approx(10, abs=0.001)
    assert submitted["sla_penalty_cents"] == 2_160
    assert submitted["missed_trip_penalty_cents"] == 4_500
    assert submitted["penalty_amount_cents"] == 6_660
    assert submitted["credit_amount_cents"] == 4_500
    assert submitted["net_amount_cents"] == 10_440
    assert submitted["total_boardings"] == 23


def test_final_approve_bills_the_operation_and_settles_the_period(api):
    """PRD §3.8: "The final set applies the same contract and date filter but admits
    only trips whose `dispatch_status` is `COMPLETED` — it bills the operation."
    PRD §3.8: "Each trip in the set contributes an integer count of billable
    minutes: under the provisional variant, its `scheduled_arrival_min` minus its
    `scheduled_departure_min`; under the final variant, its `actual_completion_min`
    minus its `actual_departure_min`."
    PRD §3.8: "Once `credit_amount_cents` has been computed and stored, every credit
    memo of this contract whose `status` is `ISSUED` and whose trip's `service_date`
    lies inside the period moves to `APPLIED` with `applied_report_id` set to this
    report; because those memos left `ISSUED`, the contract's `credit_balance_cents`
    is recomputed and the contract's `version` increments by one."
    PRD §3.8: "Separately, every trip in the final input set whose
    `settlement_status` is still `UNBILLED` moves `UNBILLED` → `BILLED`, each with
    its own `version` incremented by one"

    Design: Difficulty/dual_variant_calc/report_settlement_provisional_versus_final
    """
    scenario = setup_four_trip_settlement_scenario()
    provisional = submit_report(scenario["report"]["id"], "liaison-1")

    approved = validate_success(
        api.approve_report(scenario["report"]["id"], make_contract_admin_headers("admin-1"))
    )
    assert approved["settlement_variant"] == "FINAL"
    assert approved["status"] == "APPROVED"
    assert approved["scheduled_trip_count"] == 2
    assert approved["total_billable_minutes"] == 97, "47 plus 50 actual minutes"
    assert approved["billable_service_hours"] == pytest.approx(1.62, abs=0.001)
    assert approved["gross_amount_cents"] == 14_580
    assert approved["sla_penalty_cents"] == 1_458
    assert approved["penalty_amount_cents"] == 5_958
    assert approved["credit_amount_cents"] == 4_500
    assert approved["net_amount_cents"] == 4_122

    assert provisional["gross_amount_cents"] != approved["gross_amount_cents"]
    assert provisional["net_amount_cents"] != approved["net_amount_cents"]

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 0, "the applied memo leaves the balance"

    memos, memo_meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"trip_id": scenario["trips"][2]["id"]})
    )
    assert memo_meta["total_count"] == 1
    assert memos[0]["status"] == "APPLIED"
    assert memos[0]["applied_report_id"] == scenario["report"]["id"]

    billed = validate_success(api.get_trip(scenario["trips"][0]["id"], PLANNER))
    assert billed["settlement_status"] == "BILLED"
    assert billed["dispatch_status"] == "COMPLETED"

    untouched = validate_success(api.get_trip(scenario["trips"][3]["id"], PLANNER))
    assert untouched["settlement_status"] == "UNBILLED"
    assert untouched["dispatch_status"] == "SCHEDULED"


# ─── Sum first, then round ────────────────────────────────────────────────────

def test_billable_hours_are_rounded_once_on_the_period_total(api):
    """PRD §3.8: "Those per-trip minutes are never rounded. They are summed into
    `total_billable_minutes`, and only then, exactly once, is a rounding applied:
    `billable_service_hours` is the period total divided by 60 and rounded half up
    to two decimal places."

    Design: Difficulty/combinatorial_formula/period_gross_sum_then_round_ordering
    """
    scenario = setup_fifty_minute_schedule_report()
    assert len(scenario["trips"]) == 3, "the window 420..540 at headway 60 cuts three departures"

    submitted = submit_report(scenario["report"]["id"], "liaison-2")

    assert submitted["scheduled_trip_count"] == 3
    assert submitted["total_billable_minutes"] == 150, "three untouched 50-minute trips"
    assert submitted["billable_service_hours"] == pytest.approx(2.50, abs=0.001), (
        "150 minutes over 60 is exactly 2.50, not the 2.49 that per-trip rounding gives"
    )


def test_gross_amount_follows_the_pinned_sum_then_round_order(api):
    """PRD §3.8: "The order is pinned: sum first, then round. Rounding each trip's
    hours to two decimals and then summing is explicitly not this system's rule and
    produces different cents."
    PRD §3.8: "`on_time_pct` is 100.00 when `countable_trip_count` is 0, and
    otherwise is 100 multiplied by `on_time_trip_count`, divided by
    `countable_trip_count`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/period_gross_sum_then_round_ordering
    """
    scenario = setup_fifty_minute_schedule_report()

    submitted = submit_report(scenario["report"]["id"], "liaison-2")

    assert submitted["gross_amount_cents"] == 22_500, (
        "2.50 hours at 9000 cents, not the 22410 that round-then-sum produces"
    )
    assert submitted["gross_amount_cents"] != 22_410
    assert submitted["countable_trip_count"] == 0
    assert submitted["on_time_pct"] == pytest.approx(100.00, abs=0.001)
    assert submitted["penalty_amount_cents"] == 0
    assert submitted["net_amount_cents"] == 22_500


# ─── The dispute loop ─────────────────────────────────────────────────────────

def _dispute_scenario():
    """One 48-minute trip that departed on time, settled once by liaison-4."""
    scenario = setup_completed_trip(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        actual_departure_min=423,
        actual_completion_min=470,
        boarded=11, alighted=11, ada_boardings=0,
        contract_overrides={"client_name": "Dispute Loop Corp", "site_type": "CORPORATE"},
        vehicle_overrides={"odometer_km": 1_000},
        driver_overrides={"full_name": "Omar Haddad"},
    )
    report = create_report(
        scenario["contract"]["id"],
        period_start_date="2026-09-01", period_end_date="2026-09-30",
    )
    first = submit_report(report["id"], "liaison-4")
    return {**scenario, "report": report, "first_submission": first}


def test_dispute_zeroes_the_stored_settlement(api):
    """PRD §3.8: "The payload carries `dispute_reason` as free text, which is
    stored; the report moves `SUBMITTED` → `DISPUTED`, `settlement_variant` is reset
    to `NONE`, and every settlement figure is zeroed — `scheduled_trip_count`,
    `completed_trip_count`, `missed_trip_count`, `waived_trip_count`,
    `countable_trip_count`, `on_time_trip_count`, `on_time_pct`, `total_boardings`,
    `total_ada_boardings`, `total_billable_minutes`, `billable_service_hours`,
    `gross_amount_cents`, `penalty_tier_pct`, `sla_penalty_cents`,
    `missed_trip_penalty_cents`, `penalty_amount_cents`, `credit_amount_cents` and
    `net_amount_cents` all return to 0 — so that the next submission is forced to
    recompute rather than inheriting stale figures."

    Design: Difficulty/non_linear_state_machine/report_dispute_resubmit_cycle
    """
    scenario = _dispute_scenario()
    assert scenario["first_submission"]["gross_amount_cents"] == 7_200

    disputed = validate_success(
        api.dispute_report(
            scenario["report"]["id"], {"dispute_reason": "boarding counts under review"},
            LIAISON,
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["settlement_variant"] == "NONE"
    assert disputed["dispute_reason"] == "boarding counts under review"
    assert_settlement_block_zeroed(disputed)


def test_resubmission_recomputes_and_advances_the_revision_round(api):
    """PRD §3.8: "When the submission arrives from `DISPUTED` rather than from
    `DRAFT`, it additionally increments `revision_round` by one — a report
    submitted, disputed and resubmitted therefore reads `revision_round` 1."
    PRD §3.8: "Submitting is permitted from `DRAFT` or from `DISPUTED`; from
    `SUBMITTED` or `APPROVED` it is rejected with `ERR_REPORT_NOT_SUBMITTABLE`."

    Design: Difficulty/non_linear_state_machine/report_dispute_resubmit_cycle
    """
    scenario = _dispute_scenario()
    assert scenario["first_submission"]["revision_round"] == 0

    validate_success(
        api.dispute_report(
            scenario["report"]["id"], {"dispute_reason": "boarding counts under review"},
            LIAISON,
        )
    )

    resubmitted = validate_success(
        api.submit_report(scenario["report"]["id"], make_client_liaison_headers("liaison-4"))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["settlement_variant"] == "PROVISIONAL"
    assert resubmitted["gross_amount_cents"] == 7_200, "the figures are re-derived"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["billable_service_hours"] == pytest.approx(0.80, abs=0.001)
    assert resubmitted["on_time_pct"] == pytest.approx(100.00, abs=0.001)


# ─── The on-time grace boundary ───────────────────────────────────────────────

def _run_grace_scenario():
    scenario = setup_on_time_grace_scenario()
    trips, drivers = scenario["trips"], scenario["drivers"]
    start_trip(trips[0]["id"], drivers[0]["id"], 425)
    complete_trip(trips[0]["id"], drivers[0]["id"], 470, boarded=5, alighted=5, ada_boardings=0)
    start_trip(trips[1]["id"], drivers[1]["id"], 438)
    complete_trip(trips[1]["id"], drivers[1]["id"], 486, boarded=5, alighted=5, ada_boardings=0)
    return scenario


def test_departure_delay_of_exactly_five_minutes_counts_as_on_time(api):
    """PRD §3.8: "Within that population, `on_time_trip_count` counts the trips that
    are `COMPLETED` and whose lateness — `actual_departure_min` minus
    `scheduled_departure_min` — is at most five minutes; a departure delay of
    exactly five minutes is on time, and six minutes is late."

    Design: Difficulty/boundary_precision_check/on_time_grace_exactly_five_minutes
    """
    scenario = _run_grace_scenario()

    submitted = submit_report(scenario["report"]["id"], "liaison-5")

    assert submitted["countable_trip_count"] == 2
    assert submitted["on_time_trip_count"] == 1, (
        "the 425 departure against a 420 schedule is on time, the 438 against 432 is not"
    )
    assert submitted["on_time_pct"] == pytest.approx(50.00, abs=0.001)


def test_on_time_shortfall_selects_the_penalty_tier(api):
    """PRD §3.8: "The shortfall against the promise is the contract's
    `sla_on_time_threshold_pct` minus `on_time_pct`, and it selects
    `penalty_tier_pct` from four bands: 0 when the shortfall is zero or negative, 2
    when the shortfall is greater than zero and at most 5.00 percentage points, 5
    when the shortfall is greater than 5.00 and at most 15.00 percentage points, and
    10 when the shortfall exceeds 15.00 percentage points."
    PRD §3.8: "`sla_penalty_cents` is `gross_amount_cents` multiplied by
    `penalty_tier_pct`, divided by 100, rounded half up to a whole number of cents."
    PRD §3.8: "They are summed into `total_billable_minutes`, and only then, exactly
    once, is a rounding applied: `billable_service_hours` is the period total
    divided by 60 and rounded half up to two decimal places."
    PRD §3.8: "`net_amount_cents` is `gross_amount_cents` minus
    `penalty_amount_cents` minus `credit_amount_cents`, clamped at a floor of
    exactly 0 so it is never negative."

    Design: Difficulty/boundary_precision_check/on_time_grace_exactly_five_minutes
    """
    scenario = _run_grace_scenario()

    submitted = submit_report(scenario["report"]["id"], "liaison-5")

    assert submitted["penalty_tier_pct"] == pytest.approx(10, abs=0.001), (
        "a 92.00 promise against 50.00 delivered is a 42-point shortfall"
    )
    assert submitted["total_billable_minutes"] == 96
    assert submitted["billable_service_hours"] == pytest.approx(1.60, abs=0.001)
    assert submitted["gross_amount_cents"] == 14_400
    assert submitted["sla_penalty_cents"] == 1_440
    assert submitted["net_amount_cents"] == 12_960


# ─── The empty period ─────────────────────────────────────────────────────────

def test_empty_period_reports_one_hundred_percent_on_time(api):
    """PRD §3.8: "`on_time_pct` is 100.00 when `countable_trip_count` is 0, and
    otherwise is 100 multiplied by `on_time_trip_count`, divided by
    `countable_trip_count`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/empty_period_on_time_pct_is_one_hundred
    """
    scenario = setup_empty_period_report()

    submitted = submit_report(scenario["report"]["id"], "liaison-6")

    assert submitted["countable_trip_count"] == 0
    assert submitted["scheduled_trip_count"] == 0
    assert submitted["on_time_pct"] == pytest.approx(100.00, abs=0.001)
    assert submitted["penalty_tier_pct"] == pytest.approx(0, abs=0.001), (
        "a shortfall of exactly zero attracts no penalty at all"
    )
    assert submitted["settlement_variant"] == "PROVISIONAL"


def test_empty_period_settles_every_money_field_at_zero(api):
    """PRD §3.8: "`missed_trip_penalty_cents` is `missed_trip_count` multiplied by
    the contract's `penalty_rate_cents_per_missed_trip`, and `penalty_amount_cents`
    is `sla_penalty_cents` plus `missed_trip_penalty_cents`."
    PRD §3.8: "`net_amount_cents` is `gross_amount_cents` minus
    `penalty_amount_cents` minus `credit_amount_cents`, clamped at a floor of
    exactly 0 so it is never negative."

    Design: Difficulty/boundary_precision_check/empty_period_on_time_pct_is_one_hundred
    """
    scenario = setup_empty_period_report()

    submitted = submit_report(scenario["report"]["id"], "liaison-6")

    assert submitted["total_billable_minutes"] == 0
    assert submitted["billable_service_hours"] == pytest.approx(0.00, abs=0.001)
    assert submitted["gross_amount_cents"] == 0
    assert submitted["penalty_amount_cents"] == 0
    assert submitted["credit_amount_cents"] == 0
    assert submitted["net_amount_cents"] == 0


# ─── Approval gates ───────────────────────────────────────────────────────────

def _terminated_contract_scenario():
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Terminated Campus", site_type="CAMPUS")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )
    submit_report(report["id"], "liaison-7")
    return {"contract": contract, "report": report}


def test_approve_is_refused_on_a_terminated_contract(api):
    """PRD §3.8: "It is permitted only from `SUBMITTED`
    (`ERR_REPORT_NOT_SUBMITTED`); it requires the contract's `status` to be `ACTIVE`
    or `RENEWAL_PENDING` (`ERR_CONTRACT_NOT_ACTIVE`); and it enforces the
    segregation rule of §2.10, rejecting an approver whose `X-User-ID` equals the
    report's `submitted_by_user_id` with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_terminated_contract
    """
    scenario = _terminated_contract_scenario()
    validate_success(
        api.terminate_contract(
            scenario["contract"]["id"], {"termination_reason": "client moved sites"}, ADMIN
        )
    )

    response = api.approve_report(
        scenario["report"]["id"], make_contract_admin_headers("admin-7")
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["status"] == "TERMINATED"


def test_refused_approval_leaves_the_report_at_its_provisional_settlement(api):
    """PRD §2.6: "Approving a report requires the contract's `status` to be `ACTIVE`
    or `RENEWAL_PENDING`, and publishing or republishing a route requires the same,
    failing as `ERR_CONTRACT_NOT_ACTIVE` (409)."
    PRD §3.8: "Approval recomputes the entire settlement block using the **final**
    variant and sets `settlement_variant` to `FINAL`, stamps `approved_by_user_id`
    with the caller's `X-User-ID`, and moves the report `SUBMITTED` → `APPROVED`
    with its `version` incremented by one."

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_terminated_contract
    """
    scenario = _terminated_contract_scenario()
    validate_success(
        api.terminate_contract(
            scenario["contract"]["id"], {"termination_reason": "client moved sites"}, ADMIN
        )
    )

    response = api.approve_report(
        scenario["report"]["id"], make_contract_admin_headers("admin-7")
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

    report = validate_success(api.get_report(scenario["report"]["id"], ADMIN))
    assert report["status"] == "SUBMITTED"
    assert report["settlement_variant"] == "PROVISIONAL"
    assert report.get("approved_by_user_id") is None


# ─── Opening periods ──────────────────────────────────────────────────────────

def test_overlapping_reporting_period_is_rejected(api):
    """PRD §3.8: "The new period must also not overlap any existing report of the
    same contract — two closed date ranges overlap when the new start is on or
    before the existing end and the existing start is on or before the new end — and
    an overlap is rejected with `ERR_PERIOD_OVERLAP` and HTTP 409."

    Design: Corner/validations/overlapping_reporting_period_is_rejected
    """
    contract = create_active_contract(client_name="Overlap Hotel")
    create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )

    response = api.create_report(
        {
            "contract_id": contract["id"],
            "period_start_date": "2026-09-15",
            "period_end_date": "2026-10-15",
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value, 409)

    _, meta = validate_paginated(
        api.list_reports(ADMIN, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 1


def test_reporting_period_outside_the_contract_term_is_rejected(api):
    """PRD §3.8: "The start may not fall after the end, and both endpoints must lie
    inside the contract's closed term range; a violation of either condition is
    rejected with `ERR_PERIOD_OUT_OF_TERM` and HTTP 422."

    Design: Corner/validations/reporting_period_outside_contract_term_is_rejected
    """
    contract = create_active_contract(
        client_name="Term Hotel", term_start_date="2026-09-01", term_end_date="2027-08-31"
    )

    response = api.create_report(
        {
            "contract_id": contract["id"],
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-31",
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_PERIOD_OUT_OF_TERM.value, 422)

    _, meta = validate_paginated(
        api.list_reports(ADMIN, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0


def test_disputing_a_draft_report_is_rejected(api):
    """PRD §3.8: "Disputing is the client's lever and belongs to the `ClientLiaison`
    alone. It is permitted only from `SUBMITTED`, and from anywhere else is rejected
    with `ERR_REPORT_NOT_SUBMITTED`."

    Design: Corner/state_machines/dispute_a_draft_report_returns_report_not_submitted
    """
    contract = create_active_contract(client_name="Dispute Guard", site_type="CORPORATE")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )

    response = api.dispute_report(report["id"], {"dispute_reason": "too early"}, LIAISON)
    validate_error(response, ApiErrorId.ERR_REPORT_NOT_SUBMITTED.value, 409)

    reread = validate_success(api.get_report(report["id"], ADMIN))
    assert reread["status"] == "DRAFT"
    assert reread.get("dispute_reason") is None


def test_submitting_an_approved_report_is_rejected(api):
    """PRD §3.8: "Submitting is permitted from `DRAFT` or from `DISPUTED`; from
    `SUBMITTED` or `APPROVED` it is rejected with `ERR_REPORT_NOT_SUBMITTABLE`."
    PRD §3.8: "Approval is a `ContractAdmin` action and is the report's terminal
    transition."

    Design: Corner/state_machines/submit_an_approved_report_returns_report_not_submittable
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Approved Lock", site_type="CORPORATE")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )
    submit_report(report["id"], "liaison-a")
    validate_success(api.approve_report(report["id"], make_contract_admin_headers("admin-a")))

    response = api.submit_report(report["id"], make_client_liaison_headers("liaison-a"))
    validate_error(response, ApiErrorId.ERR_REPORT_NOT_SUBMITTABLE.value, 409)

    reread = validate_success(api.get_report(report["id"], ADMIN))
    assert reread["status"] == "APPROVED"
    assert reread["settlement_variant"] == "FINAL"
    assert reread["revision_round"] == 0
    assert reread["approved_by_user_id"] == "admin-a"


def test_self_approval_is_blocked_by_segregation_of_duties(api):
    """PRD §2.10: "Approval requires the two to differ: if the approving `X-User-ID`
    equals the report's current `submitted_by_user_id`, the approval is rejected
    with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD §2.10: "A `ContractAdmin` may open and submit a reporting period, and a
    `ContractAdmin` is the only role that may approve one — but a `ContractAdmin`
    who submitted a particular report may not approve that same report."

    Design: Corner/rbac/segregation_of_duties_blocks_self_approval
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="SoD Corp", site_type="CORPORATE")
    report = validate_success(
        api.create_report(
            {
                "contract_id": contract["id"],
                "period_start_date": "2026-09-01",
                "period_end_date": "2026-09-30",
            },
            make_contract_admin_headers("admin-s"),
        ),
        expected_status=201,
    )
    submitted = validate_success(
        api.submit_report(report["id"], make_contract_admin_headers("admin-s"))
    )
    assert submitted["submitted_by_user_id"] == "admin-s"

    refused = api.approve_report(report["id"], make_contract_admin_headers("admin-s"))
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    approved = validate_success(
        api.approve_report(report["id"], make_contract_admin_headers("admin-t"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "admin-t"
    assert approved["settlement_variant"] == "FINAL"
