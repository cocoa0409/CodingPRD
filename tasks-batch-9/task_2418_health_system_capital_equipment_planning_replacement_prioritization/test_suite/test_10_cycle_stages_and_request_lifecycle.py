"""The plan-year pipeline and the intake loop: stage gates, counters and body rules."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_allocation,
    assert_cents,
    assert_cycle,
    assert_decimal,
    assert_request,
    create_facility_payload,
    create_request_payload,
    get_success_data,
    live_allocation,
    make_asset,
    make_clinical_requester_headers,
    make_cycle,
    make_department,
    make_facility,
    make_request,
    open_intake,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_request,
    screen,
    service_event_rows,
    setup_draft_request,
    setup_estate,
    setup_intake_open_cycle,
    submit,
    validate_error,
    validate_success,
    withdraw,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]

_CYCLE_AGGREGATE_CENTS = (
    "system_contingency_cents",
    "distributable_cents",
    "unallocated_cents",
    "contingency_drawn_cents",
)
_CYCLE_COUNTS = (
    "allocation_count",
    "exhausted_allocation_count",
    "scored_count",
    "expedited_count",
)


def _two_scored_requests_one_facility():
    """One CT department competing with two scanners of its own in the 2027 cycle."""
    ctx = setup_intake_open_cycle()
    second_asset = make_asset(
        ctx["facility"]["id"], ctx["department"]["id"],
        modality="CT", model_name="Aquilon CT-8B", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    first = make_request(ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"])
    second = make_request(ctx["cycle"]["id"], ctx["department"]["id"], second_asset["id"])
    for request in (first, second):
        submit(request["id"], ctx["department"]["id"])
        screen(request["id"], "ACCEPT")
    ctx["second_asset"] = second_asset
    ctx["first"] = first
    ctx["second"] = second
    return ctx


def _two_departments_one_scanner():
    """A CT department owning the scanner and an MRI department that does not."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    ct = make_department(facility["id"], name="Diagnostic Imaging CT", modality_scope="CT")
    mri = make_department(facility["id"], name="Diagnostic Imaging MRI", modality_scope="MRI")
    asset = make_asset(
        facility["id"], ct["id"],
        modality="CT", model_name="Aquilon CT-8", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = open_intake(make_cycle()["id"])
    return {"facility": facility, "ct": ct, "mri": mri, "asset": asset, "cycle": cycle}


# ─── The cycle's stage gate ───────────────────────────────────────────


def test_a_new_cycle_holds_its_budget_but_none_of_its_arithmetic(api):
    """PRD §3.3: "The cycle is born in `DRAFT` with `allocation_method` null, every aggregate at
    zero and `allocated_by_user_id` null."
    PRD §3.3: "The cycle carries the running arithmetic of the plan year, all of it written by
    the allocation machinery rather than by a caller: `system_contingency_cents` and
    `distributable_cents` and `unallocated_cents` and `contingency_drawn_cents`, the count
    `allocation_count` of allocation rows for the cycle whose posture is not `SUPERSEDED`, the
    count `exhausted_allocation_count` of allocation rows whose posture is `EXHAUSTED`,
    `scored_count` as the number of the cycle's requests that stand in `SCORED` after the most
    recent scoring run, and `expedited_count` as the number of the cycle's requests whose
    `expedited` flag is currently true."
    PRD §3.6: "Separately, `system_contingency_cents` is the cycle's `total_capital_cents`
    multiplied by `contingency_pct`, rounded half up to whole cents, and `distributable_cents`
    is `total_capital_cents` less `system_contingency_cents`."

    Design: Corner/state_machines/capital_cycle_is_created_in_draft_with_every_aggregate_zeroed
    """
    pin_clock(CLOCK)

    cycle = validate_success(
        api.create_cycle(
            {"plan_year": 2027, "plan_year_start": "2027-01-01T00:00:00Z",
             "total_capital_cents": 500000000, "contingency_pct": 0.10,
             "facility_contingency_pct": 0.05},
            _PLANNER,
        ),
        201,
    )
    assert_cycle(cycle)
    assert cycle["status"] == "DRAFT"
    assert cycle["version"] == 1
    assert cycle["allocation_method"] is None
    assert cycle["allocated_by_user_id"] is None
    assert_cents(cycle["total_capital_cents"], 500000000, "total_capital_cents")
    for field in _CYCLE_AGGREGATE_CENTS:
        assert_cents(cycle[field], 0, field)
    for field in _CYCLE_COUNTS:
        assert cycle[field] == 0, f"{field} starts at zero"


def test_opening_intake_a_second_time_is_a_stage_fault_that_leaves_the_version_alone(api):
    """PRD §3.3: "Opening intake requires the cycle to be in `DRAFT` and moves it to
    `INTAKE_OPEN`."
    PRD §3.3: "Any operation attempted against a cycle in the wrong stage is rejected with
    `ERR_CYCLE_INVALID_STATE`; the pinned mapping is `DRAFT` to open intake, `INTAKE_OPEN` to
    submit a request or to close intake, `SCORING` to score or to run the first allocation, and
    `ALLOCATED` to vote, to close voting, to fund, to re-run the allocation or to commit."
    PRD §2.11: "Nothing later in the order is evaluated, and no side effect is written."

    Design: Corner/state_machines/second_open_intake_on_an_already_open_cycle_is_rejected_not_idempotent
    """
    pin_clock(CLOCK)
    cycle = make_cycle()
    opened = validate_success(api.open_intake(cycle["id"], _PLANNER))
    assert opened["status"] == "INTAKE_OPEN"
    assert opened["version"] == 2

    validate_error(
        api.open_intake(cycle["id"], _PLANNER),
        ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409,
    )

    after = refresh_cycle(cycle["id"])
    assert after["status"] == "INTAKE_OPEN"
    assert after["version"] == 2


def test_the_budget_envelope_is_editable_until_intake_opens_and_frozen_afterwards(api):
    """PRD §3.3: "While the cycle is still in `DRAFT` a planner may edit `total_capital_cents`,
    `contingency_pct`, `facility_contingency_pct` and `plan_year_start`; once the cycle has left
    `DRAFT` the edit is rejected with `ERR_CYCLE_INVALID_STATE`."
    PRD §2.6: "`version` is an integer that starts at 1 when the row is created and increases by
    exactly one on every mutation of that row, including mutations performed as a side effect of
    an operation on another resource."

    Design: Corner/endpoints/patch_cycle_is_a_draft_only_operation
    """
    pin_clock(CLOCK)
    cycle = make_cycle()

    patched = validate_success(
        api.patch_cycle(
            cycle["id"],
            {"total_capital_cents": 900000000, "contingency_pct": 0.10,
             "facility_contingency_pct": 0.05},
            _PLANNER,
        )
    )
    assert_cents(patched["total_capital_cents"], 900000000, "total_capital_cents")
    assert_decimal(patched["contingency_pct"], 0.10, "contingency_pct")
    assert_decimal(patched["facility_contingency_pct"], 0.05, "facility_contingency_pct")
    assert patched["status"] == "DRAFT"
    assert patched["version"] == 2
    for field in _CYCLE_AGGREGATE_CENTS:
        assert_cents(patched[field], 0, field)
    assert patched["allocation_count"] == 0

    opened = validate_success(api.open_intake(cycle["id"], _PLANNER))
    assert opened["status"] == "INTAKE_OPEN"
    assert opened["version"] == 3

    validate_error(
        api.patch_cycle(cycle["id"], {"total_capital_cents": 100000000}, _PLANNER),
        ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409,
    )

    after = refresh_cycle(cycle["id"])
    assert after["status"] == "INTAKE_OPEN"
    assert after["version"] == 3
    assert_cents(after["total_capital_cents"], 900000000, "total_capital_cents")


def test_committing_sweeps_every_still_scored_request_without_touching_the_allocation(api):
    """PRD §3.3: "Committing the cycle is a settlement act with a cascade."
    PRD §3.3: "The cycle moves `ALLOCATED → COMMITTED` and its `version` is incremented, and
    then every request of that cycle whose status is `SCORED` or `IN_COMMITTEE`, processed in
    `created_at` ascending order, is moved to `DEFERRED` with that request's `version`
    incremented."
    PRD §3.6: "A new row starts with `contingency_status` `HELD`, `released_contingency_cents` 0
    and `committed_cents` 0, so `available_cents` equals `allocated_cents`, and `posture` is
    `ACTIVE` when `available_cents` is above zero and `EXHAUSTED` when it is zero."
    PRD §3.6: "Cycle-level aggregates are written from the same run: `unallocated_cents` is the
    distributable amount less the sum of every `allocated_cents`, `contingency_drawn_cents` is
    the sum of every `contingency_reserve_cents`, `allocation_count` is the number of rows
    created, and `exhausted_allocation_count` is set to 0."

    Design: Corner/state_machines/commit_defers_every_remaining_scored_request_in_created_at_order
    """
    ctx = _two_scored_requests_one_facility()
    validate_success(api.close_intake(ctx["cycle"]["id"], _PLANNER))
    scored = validate_success(api.score_cycle(ctx["cycle"]["id"], _PLANNER))
    allocated = validate_success(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "RANK_ORDERED", "expected_cycle_version": scored["version"]},
            TEST_USERS["planner_alloc_headers"],
        )
    )
    assert allocated["allocation_count"] == 1
    assert_cents(allocated["unallocated_cents"], 300000000, "unallocated_cents")
    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])

    committed = validate_success(api.commit_cycle(ctx["cycle"]["id"], _PLANNER))
    assert_cycle(committed)
    assert committed["status"] == "COMMITTED"
    assert committed["version"] == 6
    assert committed["allocation_count"] == 1
    assert committed["exhausted_allocation_count"] == 0

    for request in (ctx["first"], ctx["second"]):
        after = refresh_request(request["id"])
        assert_request(after)
        assert after["status"] == "DEFERRED"
        assert after["version"] == 5
        assert_decimal(after["composite_score"], 39.69, "composite_score")

    after_allocation = validate_success(api.get_allocation(allocation["id"], _PLANNER))
    assert_allocation(after_allocation)
    assert after_allocation["posture"] == "ACTIVE"
    assert_cents(after_allocation["allocated_cents"], 200000000, "allocated_cents")
    assert_cents(after_allocation["committed_cents"], 0, "committed_cents")
    assert_cents(after_allocation["available_cents"], 200000000, "available_cents")
    assert after_allocation["version"] == 1


# ─── The intake loop ──────────────────────────────────────────────────


def test_a_returned_request_counts_its_return_once_and_its_revision_once(api):
    """PRD §3.4: "A `decision` of `RETURN` performs `SUBMITTED → RETURNED`, increments
    `return_count` by one and increments the request's `version`."
    PRD §3.4: "An edit applied to a request in `RETURNED` performs the transition
    `RETURNED → DRAFT` and increments `revision_count` by one."
    PRD §3.4: "An edit applied to a request in `DRAFT` leaves it in `DRAFT` — the self-transition
    `DRAFT → DRAFT` — and leaves `revision_count` untouched."
    PRD §3.4: "On success the request's `version` is incremented and the budgetary
    total-cost-of-ownership projection is run and stored."

    Design: Corner/state_machines/screen_return_forks_the_request_and_the_next_patch_bumps_revision_count
    """
    ctx = setup_draft_request()
    submitted = submit(ctx["request"]["id"], ctx["department"]["id"])
    assert_cents(submitted["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")
    requester = make_clinical_requester_headers(ctx["department"]["id"])

    returned = validate_success(
        api.screen_request(
            ctx["request"]["id"],
            {"decision": "RETURN", "screening_note": "Add the volume evidence and the room survey."},
            _PLANNER,
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1
    assert returned["revision_count"] == 0
    assert returned["version"] == 3

    revised = validate_success(
        api.patch_request(
            ctx["request"]["id"],
            {"clinical_justification":
                "CT replacement with attached room survey and referral trend."},
            requester,
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["return_count"] == 1
    assert revised["version"] == 4

    again = validate_success(
        api.patch_request(ctx["request"]["id"], {"current_annual_volume": 1100}, requester)
    )
    assert again["status"] == "DRAFT"
    assert again["revision_count"] == 1
    assert again["version"] == 5
    assert_cents(again["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")


def test_a_withdrawn_request_can_neither_be_submitted_nor_edited_again(api):
    """PRD §3.4: "The full request lifecycle is `DRAFT`, `SUBMITTED`, `SCREENED`, `RETURNED`,
    `SCORED`, `IN_COMMITTEE`, `APPROVED`, `DEFERRED`, `REJECTED`, `FUNDED`, `IMPLEMENTED`,
    `AUDITED` and `WITHDRAWN`, with `REJECTED`, `WITHDRAWN` and `AUDITED` terminal."
    PRD §3.4: "The state set each operation requires is pinned: submitting demands `DRAFT` or
    `RETURNED`; editing demands `DRAFT` or `RETURNED`; screening demands `SUBMITTED`;
    withdrawing demands `DRAFT`, `RETURNED`, `SUBMITTED`, `SCREENED` or `SCORED`; balloting
    demands `SCORED` or `IN_COMMITTEE`; closing voting demands `IN_COMMITTEE`; funding demands
    `APPROVED`; withdrawing funding demands `FUNDED`; raising a vendor quote demands `SCORED`,
    `IN_COMMITTEE`, `APPROVED` or `FUNDED`; opening an installation project demands `FUNDED`;
    and scheduling a utilization audit demands `IMPLEMENTED`."
    PRD §2.11: "16. The replacement request not in the state set the operation requires, on
    every request transition endpoint and on quote creation, installation-project creation and
    audit creation — `ERR_REQUEST_INVALID_STATE`, 409."

    Design: Corner/state_machines/submit_after_withdraw_is_locked_out_of_the_terminal_state
    """
    ctx = setup_draft_request()
    gone = withdraw(ctx["request"]["id"], ctx["department"]["id"])
    assert gone["status"] == "WITHDRAWN"
    assert gone["version"] == 2
    requester = make_clinical_requester_headers(ctx["department"]["id"])

    validate_error(
        api.submit_request(ctx["request"]["id"], requester),
        ApiErrorId.ERR_REQUEST_INVALID_STATE.value, 409,
    )
    validate_error(
        api.patch_request(ctx["request"]["id"], {"current_annual_volume": 1200}, requester),
        ApiErrorId.ERR_REQUEST_INVALID_STATE.value, 409,
    )

    after = refresh_request(ctx["request"]["id"])
    assert after["status"] == "WITHDRAWN"
    assert after["version"] == 2
    assert after["current_annual_volume"] == 1000


def test_the_second_bid_on_one_scanner_waits_for_the_first_to_be_withdrawn(api):
    """PRD §3.4: "Submitting a request performs `DRAFT → SUBMITTED` and is the densest gate in
    the intake stage."
    PRD §3.4: "The request must stand in `DRAFT` or `RETURNED`, the acting requester must own
    the department, the owning cycle must be in `INTAKE_OPEN`, the revision bound must hold, the
    asset must not be `DECOMMISSIONED` and must clear the eligibility gate of §3.2, no other
    request naming the same `asset_id` in the same `cycle_id` may hold a status other than
    `WITHDRAWN`, `REJECTED` or `DEFERRED` — a live sibling is rejected with
    `ERR_DUPLICATE_ASSET_REQUEST` — and both the modification cap and the mandate-deadline rule
    must hold."
    PRD §3.4: "Each of the five years is rounded to whole cents **before** the summation, and
    `budgetary_operating_5y_cents` is the sum over the five years of that year's service cost
    plus that year's disposables cost."
    PRD §3.4: "Submission also writes `baseline_year1_opex_cents` as the year-one service cost
    plus the year-one disposables cost of the authoritative variant, which at submission time is
    the budgetary one; this figure is the business-case baseline the post-implementation audit
    measures actual operating cost against."

    Design: Corner/validations/second_submit_for_the_same_asset_in_one_cycle_is_blocked_until_the_first_is_withdrawn
    """
    ctx = setup_intake_open_cycle()
    option_a = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"],
        clinical_justification="Option A: single-source replacement.",
    )
    submit(option_a["id"], ctx["department"]["id"])
    option_b = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"],
        clinical_justification="Option B: refurbished replacement.",
    )
    requester = make_clinical_requester_headers(ctx["department"]["id"])

    validate_error(
        api.submit_request(option_b["id"], requester),
        ApiErrorId.ERR_DUPLICATE_ASSET_REQUEST.value, 409,
    )
    blocked = refresh_request(option_b["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["version"] == 1

    withdraw(option_a["id"], ctx["department"]["id"],
             withdrawal_reason="Consolidating on option B.")

    accepted = validate_success(api.submit_request(option_b["id"], requester))
    assert accepted["status"] == "SUBMITTED"
    assert_cents(accepted["budgetary_operating_5y_cents"], 60106313,
                 "budgetary_operating_5y_cents")
    assert_cents(accepted["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")
    assert_cents(accepted["baseline_year1_opex_cents"], 10850000, "baseline_year1_opex_cents")

    rows = get_success_data(api.list_requests(_PLANNER, params={"asset_id": ctx["asset"]["id"]}))
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"WITHDRAWN", "SUBMITTED"}


# ─── Body rules and duplicate keys ────────────────────────────────────


def test_a_repeated_facility_code_and_a_repeated_plan_year_both_report_a_duplicate_key(api):
    """PRD §3.1: "A facility is created with a display `name` of one to one hundred twenty
    characters that may not be blank, a short `code` of two to eight characters drawn only from
    uppercase letters A through Z and the digits 0 through 9 and unique across all facilities,
    and a `region` that is one of `NORTH`, `SOUTH`, `EAST` or `WEST`."
    PRD §3.3: "Creating one requires a `plan_year` between 2026 and 2035 inclusive and unique
    across cycles — a duplicate is rejected with `ERR_DUPLICATE_KEY` — a `plan_year_start`
    naming the first instant of that plan year, a `total_capital_cents` greater than zero, a
    `contingency_pct` between 0.00 and 0.50 inclusive with at most four decimal places, and a
    `facility_contingency_pct` under the same bounds."
    PRD §2.11: "9. A duplicate `code` on facility creation, a duplicate `plan_year` on cycle
    creation, or a duplicate `contract_code` on group-purchasing-contract creation —
    `ERR_DUPLICATE_KEY`, 409."

    Design: Corner/validations/duplicate_facility_code_and_duplicate_plan_year_return_duplicate_key
    """
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    cycle = make_cycle()

    validate_error(
        api.create_facility(
            create_facility_payload(
                name="North Regional Hospital Annex", code="NRH", region="SOUTH"
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value, 409,
    )
    validate_error(
        api.create_cycle(
            {"plan_year": 2027, "plan_year_start": "2027-04-01T00:00:00Z",
             "total_capital_cents": 900000000, "contingency_pct": 0.10,
             "facility_contingency_pct": 0.05},
            _PLANNER,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value, 409,
    )

    twin = validate_success(
        api.create_facility(
            create_facility_payload(
                name="North Regional Hospital", code="NRH2", region="NORTH"
            ),
            _PLANNER,
        ),
        201,
    )
    assert twin["code"] == "NRH2"

    facilities = get_success_data(api.list_facilities(_PLANNER))
    assert len(facilities) == 2
    assert {row["id"] for row in facilities} == {facility["id"], twin["id"]}

    cycles = get_success_data(api.list_cycles(_PLANNER, params={"plan_year": 2027}))
    assert len(cycles) == 1
    assert cycles[0]["id"] == cycle["id"]
    assert_cents(cycles[0]["total_capital_cents"], 500000000, "total_capital_cents")


def test_the_three_intake_body_rules_answer_in_their_pinned_order(api):
    """PRD §3.4: "The acting requester's `X-User-ID` must equal the `department_id` on the
    request, and the referenced asset's own `department_id` must equal it too — a foreign asset
    is rejected with `ERR_ASSET_DEPARTMENT_MISMATCH`."
    PRD §3.4: "The facility modification cost is capped at thirty percent of the estimated
    capital cost, and the comparison is made as an exact integer cross-multiplication: ten times
    `facility_modification_cents` may not exceed three times `estimated_capital_cents`."
    PRD §3.4: "Separately, a request that asserts `regulatory_mandate_flag` true must also carry
    a `mandate_deadline`; a true flag with a null deadline is rejected with
    `ERR_MANDATE_DEADLINE_REQUIRED`."
    PRD §2.11: "11. A request whose referenced asset's `department_id` is not the request's
    `department_id`, on request creation and request patch — `ERR_ASSET_DEPARTMENT_MISMATCH`,
    422."
    PRD §2.11: "12. Facility modification cost above the thirty-percent cap, on request
    creation, request patch and request submit — `ERR_MODIFICATION_COST_EXCEEDS_CAP`, 422."

    Design: Corner/validations/request_creation_body_rules_fire_in_priority_order_from_mismatch_to_cap_to_mandate
    """
    ctx = _two_departments_one_scanner()
    ct_requester = make_clinical_requester_headers(ctx["ct"]["id"])
    mri_requester = make_clinical_requester_headers(ctx["mri"]["id"])

    validate_error(
        api.create_request(
            create_request_payload(ctx["cycle"]["id"], ctx["mri"]["id"], ctx["asset"]["id"]),
            mri_requester,
        ),
        ApiErrorId.ERR_ASSET_DEPARTMENT_MISMATCH.value, 422,
    )
    validate_error(
        api.create_request(
            create_request_payload(
                ctx["cycle"]["id"], ctx["ct"]["id"], ctx["asset"]["id"],
                facility_modification_cents=30000001,
            ),
            ct_requester,
        ),
        ApiErrorId.ERR_MODIFICATION_COST_EXCEEDS_CAP.value, 422,
    )
    validate_error(
        api.create_request(
            create_request_payload(
                ctx["cycle"]["id"], ctx["ct"]["id"], ctx["asset"]["id"],
                regulatory_mandate_flag=True,
            ),
            ct_requester,
        ),
        ApiErrorId.ERR_MANDATE_DEADLINE_REQUIRED.value, 422,
    )

    created = validate_success(
        api.create_request(
            create_request_payload(
                ctx["cycle"]["id"], ctx["ct"]["id"], ctx["asset"]["id"],
                facility_modification_cents=30000000,
                regulatory_mandate_flag=True,
                mandate_deadline="2027-06-30T00:00:00Z",
            ),
            ct_requester,
        ),
        201,
    )
    assert_request(created)
    assert created["status"] == "DRAFT"
    assert_cents(created["facility_modification_cents"], 30000000, "facility_modification_cents")

    rows = get_success_data(api.list_requests(_PLANNER, params={"cycle_id": ctx["cycle"]["id"]}))
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


def test_an_event_one_second_past_the_clock_is_refused_while_the_clock_instant_lands(api):
    """PRD §3.2: "Each service event carries the `event_date` on which it occurred, which may
    not be later than the logical clock — a future-dated event is rejected with
    `ERR_EVENT_DATE_IN_FUTURE` — a `category` of `PM`, `CORRECTIVE`, `RECALL` or `UPGRADE`, a
    `downtime_hours` figure with two decimal places that defaults to 0.00 and must be at least 0
    and at most 8760, a `cost_cents` figure that defaults to 0 and may not be negative, a
    `recall_resolved` boolean that defaults to false and is meaningful only for a recall event
    (for every other category the value is ignored), and a free-text `notes` field of up to five
    hundred characters."
    PRD §2.11: "31. A service event dated after the logical clock, on service-event append —
    `ERR_EVENT_DATE_IN_FUTURE`, 422."
    PRD §3.2: "From those, `service_penalty_points` is three points for each corrective event
    plus half a point for each downtime hour, rounded half up to two decimals, and then capped
    at 40.00; the cap applies to this penalty term alone and never to the sum of all penalties."

    Design: Corner/validations/service_event_dated_after_the_clock_is_rejected_while_the_clock_instant_passes
    """
    ctx = setup_estate()

    validate_error(
        api.create_service_event(
            ctx["asset"]["id"],
            {"event_date": "2026-08-01T00:00:01Z", "category": "CORRECTIVE",
             "downtime_hours": 2.00},
            _PLANNER,
        ),
        ApiErrorId.ERR_EVENT_DATE_IN_FUTURE.value, 422,
    )
    untouched = refresh_asset(ctx["asset"]["id"])
    assert untouched["version"] == 1
    assert_decimal(untouched["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
    assert service_event_rows(ctx["asset"]["id"]) == []

    validate_success(
        api.create_service_event(
            ctx["asset"]["id"],
            {"event_date": CLOCK, "category": "CORRECTIVE", "downtime_hours": 2.00},
            _PLANNER,
        ),
        201,
    )
    after = refresh_asset(ctx["asset"]["id"])
    assert after["corrective_count_24m"] == 1
    assert_decimal(after["downtime_hours_24m"], 2.00, "downtime_hours_24m")
    assert_decimal(after["service_penalty_points"], 4.00, "service_penalty_points")
    assert_decimal(after["adjusted_ruls_score"], 21.00, "adjusted_ruls_score")
    assert after["version"] == 2
