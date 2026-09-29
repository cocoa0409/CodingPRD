"""Request submission against the cycle stage, and the screening fork with its revision loop."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_service_event,
    assert_cents,
    assert_decimal,
    make_asset,
    make_clinical_requester_headers,
    make_cycle,
    make_department,
    make_facility,
    make_request,
    open_intake,
    pin_clock,
    refresh_cycle,
    refresh_request,
    score_rows,
    submit,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]

CT_JUSTIFICATION = (
    "CT-16 scanner at end of service life; replacement restores stroke protocol throughput."
)


def _ct_estate():
    """NRH with one CT department and one scanner sitting at 30.00 adjusted RULS."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    for event_date in ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"):
        add_service_event(asset["id"], event_date, "CORRECTIVE", downtime_hours=4.00)
    return facility, department, asset


def _request_payload_overrides():
    return dict(
        clinical_justification=CT_JUSTIFICATION,
        current_annual_volume=1200, projected_annual_volume=1801,
        estimated_capital_cents=250000001, annual_service_contract_cents=12345678,
        disposable_unit_cents=1230, facility_modification_cents=60000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )


def _draft_cycle_with_draft_request():
    """A 2027 cycle left in `DRAFT` with a request already raised against it."""
    _facility, department, asset = _ct_estate()
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    request = make_request(cycle["id"], department["id"], asset["id"],
                           **_request_payload_overrides())
    return department, cycle, request


def _submitted_request():
    """The same request, submitted into an open 2027 intake."""
    _facility, department, asset = _ct_estate()
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    open_intake(cycle["id"])
    request = make_request(cycle["id"], department["id"], asset["id"],
                           **_request_payload_overrides())
    request = submit(request["id"], department["id"])
    return department, cycle, request


# ─── The screening fork and the revision loop ─────────────────────────


def test_screening_return_branch_counts_the_return_without_touching_revisions(api):
    """PRD §3.4: "A `decision` of `RETURN` performs `SUBMITTED → RETURNED`, increments
    `return_count` by one and increments the request's `version`."
    PRD §3.4: "The two branches have disjoint effects and the same guards."

    Design: Difficulty/non_linear_state_machine/replacement_request_screen_branch_and_revision_loop
    """
    _department, _cycle, request = _submitted_request()

    returned = validate_success(
        api.screen_request(
            request["id"],
            {"decision": "RETURN",
             "screening_note": "Re-price the capital line against the current GPO schedule."},
            _PLANNER,
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1
    assert returned["revision_count"] == 0
    assert returned["version"] > request["version"]


def test_revision_loop_reprices_the_projection_before_the_accept_branch_lands(api):
    """PRD §3.4: "An edit applied to a request in `RETURNED` performs the transition
    `RETURNED → DRAFT` and increments `revision_count` by one."
    PRD §3.4: "On success the request's `version` is incremented and the budgetary
    total-cost-of-ownership projection is run and stored."
    PRD §3.4: "A `decision` of `ACCEPT` performs `SUBMITTED → SCREENED` and increments the
    request's `version`, and nothing else changes."
    PRD §3.5: "Each scoring produces an immutable score row rather than overwriting
    history."

    Design: Difficulty/non_linear_state_machine/replacement_request_screen_branch_and_revision_loop
    """
    department, _cycle, request = _submitted_request()
    requester = make_clinical_requester_headers(department["id"])
    validate_success(
        api.screen_request(
            request["id"],
            {"decision": "RETURN",
             "screening_note": "Re-price the capital line against the current GPO schedule."},
            _PLANNER,
        )
    )

    revised = validate_success(
        api.patch_request(request["id"], {"estimated_capital_cents": 240000000}, requester)
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["return_count"] == 1
    assert_cents(revised["estimated_capital_cents"], 240000000, "estimated_capital_cents")

    resubmitted = validate_success(api.submit_request(request["id"], requester, {}))
    assert resubmitted["status"] == "SUBMITTED"
    assert_cents(resubmitted["budgetary_operating_5y_cents"], 78961530,
                 "budgetary_operating_5y_cents")
    assert_cents(resubmitted["budgetary_tco_cents"], 378961530, "budgetary_tco_cents")
    assert_cents(resubmitted["baseline_year1_opex_cents"], 14228624,
                 "baseline_year1_opex_cents")

    accepted = validate_success(
        api.screen_request(request["id"], {"decision": "ACCEPT"}, _PLANNER)
    )
    assert accepted["status"] == "SCREENED"
    assert accepted["return_count"] == 1
    assert accepted["revision_count"] == 1
    assert_decimal(accepted["composite_score"], 0.00, "composite_score")
    assert accepted["expedited"] is False
    assert score_rows(request["id"]) == []


# ─── Submission is gated on a sibling entity's stage ──────────────────


def test_submit_is_refused_while_the_owning_cycle_still_sits_in_draft(api):
    """PRD §3.4: "The request must stand in `DRAFT` or `RETURNED`, the acting requester
    must own the department, the owning cycle must be in `INTAKE_OPEN`, the revision bound
    must hold, the asset must not be `DECOMMISSIONED` and must clear the eligibility gate
    of §3.2, no other request naming the same `asset_id` in the same `cycle_id` may hold a
    status other than `WITHDRAWN`, `REJECTED` or `DEFERRED` — a live sibling is rejected
    with `ERR_DUPLICATE_ASSET_REQUEST` — and both the modification cap and the
    mandate-deadline rule must hold."
    PRD §3.3: "Any operation attempted against a cycle in the wrong stage is rejected with
    `ERR_CYCLE_INVALID_STATE`; the pinned mapping is `DRAFT` to open intake, `INTAKE_OPEN`
    to submit a request or to close intake, `SCORING` to score or to run the first
    allocation, and `ALLOCATED` to vote, to close voting, to fund, to re-run the
    allocation or to commit."

    Design: Difficulty/cross_entity_state_dependency/request_submit_depends_on_cycle_intake_stage
    """
    department, cycle, request = _draft_cycle_with_draft_request()
    requester = make_clinical_requester_headers(department["id"])

    assert refresh_cycle(cycle["id"])["status"] == "DRAFT"
    response = api.submit_request(request["id"], requester, {})
    validate_error(response, ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409)

    after = refresh_request(request["id"])
    assert after["status"] == "DRAFT"
    assert_cents(after["budgetary_tco_cents"], 0, "budgetary_tco_cents")
    assert_cents(after["baseline_year1_opex_cents"], 0, "baseline_year1_opex_cents")


def test_the_identical_submit_succeeds_once_intake_is_opened_on_the_cycle(api):
    """PRD §3.3: "Opening intake requires the cycle to be in `DRAFT` and moves it to
    `INTAKE_OPEN`."
    PRD §3.3: "The cycle carries the running arithmetic of the plan year, all of it
    written by the allocation machinery rather than by a caller:
    `system_contingency_cents` and `distributable_cents` and `unallocated_cents` and
    `contingency_drawn_cents`, the count `allocation_count` of allocation rows for the
    cycle whose posture is not `SUPERSEDED`, the count `exhausted_allocation_count` of
    allocation rows whose posture is `EXHAUSTED`, `scored_count` as the number of the
    cycle's requests that stand in `SCORED` after the most recent scoring run, and
    `expedited_count` as the number of the cycle's requests whose `expedited` flag is
    currently true."
    PRD §3.4: "The capital term of the budgetary variant is `estimated_capital_cents` plus
    `facility_modification_cents`, and `budgetary_tco_cents` is that capital term plus the
    five-year operating total."

    Design: Difficulty/cross_entity_state_dependency/request_submit_depends_on_cycle_intake_stage
    """
    department, cycle, request = _draft_cycle_with_draft_request()
    requester = make_clinical_requester_headers(department["id"])
    validate_error(api.submit_request(request["id"], requester, {}),
                   ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409)

    opened = validate_success(api.open_intake(cycle["id"], _PLANNER, {}))
    assert opened["status"] == "INTAKE_OPEN"
    assert_cents(opened["system_contingency_cents"], 0, "system_contingency_cents")
    assert_cents(opened["distributable_cents"], 0, "distributable_cents")

    submitted = validate_success(api.submit_request(request["id"], requester, {}))
    assert submitted["status"] == "SUBMITTED"
    assert_cents(submitted["budgetary_operating_5y_cents"], 78961530,
                 "budgetary_operating_5y_cents")
    assert_cents(submitted["budgetary_tco_cents"], 388961531, "budgetary_tco_cents")
    assert_cents(submitted["baseline_year1_opex_cents"], 14228624,
                 "baseline_year1_opex_cents")

    cycle_after = refresh_cycle(cycle["id"])
    assert cycle_after["scored_count"] == 0
    assert cycle_after["expedited_count"] == 0


# ─── Which fault wins when a screen call breaks two rules ────────────


def test_a_requester_screening_with_a_bad_enum_is_told_about_the_role(api):
    """PRD §2.11: "When one call violates several rules, exactly one error is returned:
    the one earliest in the following order."
    PRD §2.11: "2. Acting role not authorized for the endpoint, on every endpoint —
    `ERR_UNAUTHORIZED`, 403."

    Design: Difficulty/priority_pair_validation_conflict/auth_beats_shape_on_screen
    """
    department, _cycle, request = _submitted_request()
    requester = make_clinical_requester_headers(department["id"])

    response = api.screen_request(request["id"], {"decision": "MAYBE"}, requester)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert refresh_request(request["id"])["status"] == "SUBMITTED"


def test_the_same_bad_enum_from_the_planner_is_told_about_the_body(api):
    """PRD §2.11: "7. A required input absent, a field of the wrong JSON type, an enum
    value outside its declared set, a string outside its length bounds or a number outside
    its declared range, on every write endpoint — `ERR_VALIDATION`, 422."
    PRD §3.4: "A screening call carries a `decision` of either `ACCEPT` or `RETURN` and an
    optional `screening_note`, and it requires the request to stand in `SUBMITTED` with
    its cycle in either `INTAKE_OPEN` or `SCORING`."

    Design: Difficulty/priority_pair_validation_conflict/auth_beats_shape_on_screen
    """
    _department, _cycle, request = _submitted_request()

    response = api.screen_request(request["id"], {"decision": "MAYBE"}, _PLANNER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    after = refresh_request(request["id"])
    assert after["status"] == "SUBMITTED"
    assert after["return_count"] == 0
    assert after["revision_count"] == 0
