"""State-gate, temporal-window, uniqueness and cross-entity validations.

Every test builds its own entities from scratch through PRD-declared endpoints
and trips exactly one rule, so the expected error identifier is unambiguous.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    append_record,
    append_reversal,
    assert_days_after,
    assert_ledger_aggregates,
    assert_sanction_state,
    create_property_payload,
    determine_case,
    draft_standard,
    extend_order,
    file_panel,
    make_property_owner_headers,
    open_cycle,
    parse_instant,
    read_community,
    read_cycle,
    read_inspection,
    read_property,
    read_standard,
    read_structure,
    register_community,
    run_sweep,
    set_clock,
    setup_parcel,
    setup_scheduled_inspection,
    setup_structure,
    setup_violation_with_order,
    submit_cycle,
    submit_standard,
    validate_error,
    validate_paginated,
    validate_success,
    verify_standard,
)

_ADMIN = TEST_USERS["administrator_headers"]
_COORD = TEST_USERS["coordinator_headers"]


def _read_order(api, order_id):
    return validate_success(api.get_remediation_order(order_id, _ADMIN), 200)


def _read_violation(api, violation_id):
    return validate_success(api.get_violation(violation_id, _ADMIN), 200)


def _read_record(api, record_id):
    return validate_success(api.get_improvement_record(record_id, _ADMIN), 200)


def _read_panel(api, panel_id):
    return validate_success(api.get_firm_panel(panel_id, _COORD), 200)


def _only_case_for_structure(api, structure_id):
    cases, _meta = validate_paginated(
        api.list_determination_cases(_ADMIN, params={"structure_id": structure_id})
    )
    assert len(cases) == 1, f"Expected exactly one determination case, got {len(cases)}"
    return cases[0]


# ==========================================================================
# Cross-entity state guards
# ==========================================================================

def test_property_creation_on_a_pending_panel_is_rejected(api):
    """PRD §3.3: "A `FloodplainAdministrator` records each parcel as a `Property` naming its
    `community_id`, the `firm_panel_id` of the governing panel — which must be `EFFECTIVE` at
    creation, else `ERR_PANEL_NOT_EFFECTIVE` — the assessor's `parcel_id`, the
    `mapped_area_code` printed on the panel for the parcel's flood-hazard sub-area, and the
    owner's `owner_name` and `owner_email`."

    PRD §3.2: "A filed panel begins with `status` at `PENDING_REVISION`,
    `supersedes_panel_id` null, and `version` at 1."

    Design: Corner/validations/property_creation_on_a_pending_panel_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    panel = file_panel(community["id"])
    assert panel["status"] == "PENDING_REVISION"

    resp = api.create_property(
        create_property_payload(community["id"], panel["id"], parcel_id="P-0001"), _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_EFFECTIVE)

    assert _read_panel(api, panel["id"])["status"] == "PENDING_REVISION"


def test_certification_with_a_still_submitted_standard_is_rejected(api):
    """PRD §3.9: "It additionally requires that `verification_visit_required` be false or
    `verification_visit_completed_at` be set, else `ERR_VERIFICATION_VISIT_REQUIRED`, and that
    no `HigherStandard` of the community still be `SUBMITTED`, else
    `ERR_UNRESOLVED_SUBMISSIONS`."

    PRD §3.9: "The class formula subtracts, from 10, the number of whole 500-point blocks the
    points total contains, truncating any partial block downward; the result is then raised to
    1 if it came out lower, since 1 is the best attainable class; and if the community's
    `compliance_posture` is anything other than `GOOD_STANDING`, the class is instead forced to
    10 outright — no credit accrues to a community on probation or under suspension."

    Design: Corner/validations/certification_with_a_still_submitted_standard_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    standard = draft_standard(
        community["id"],
        activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026,
        claimed_points=100,
    )
    submit_standard(standard["id"])

    cycle = open_cycle(
        community["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2027-03-01T00:00:00Z",
    )
    cycle = submit_cycle(cycle["id"])
    assert cycle["verification_visit_required"] is False

    resp = api.certify_crs_cycle(cycle["id"], _COORD)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SUBMISSIONS)

    after = read_cycle(cycle["id"])
    assert after["status"] == "SUBMITTED"
    assert after["total_claimed_points"] == 100
    assert after["provisional_class"] == 10
    assert after["resulting_class"] is None

    assert read_standard(standard["id"])["documentation_status"] == "SUBMITTED"
    assert read_community(community["id"])["crs_class"] == 10


def test_certification_without_the_required_verification_visit_is_rejected(api):
    """PRD §3.9: "It additionally requires that `verification_visit_required` be false or
    `verification_visit_completed_at` be set, else `ERR_VERIFICATION_VISIT_REQUIRED`, and that
    no `HigherStandard` of the community still be `SUBMITTED`, else
    `ERR_UNRESOLVED_SUBMISSIONS`."

    PRD §3.9: "That flag is true when `cycle_year` is an exact multiple of 5, and also true
    whenever a `provisional_class` has been computed and is numerically lower — that is,
    better — than `prior_class`."

    Design: Corner/validations/certification_without_the_required_verification_visit_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    standard = draft_standard(
        community["id"],
        activity_code="A430_FREEBOARD",
        documentation_cycle_year=2025,
        claimed_points=100,
    )
    submit_standard(standard["id"])
    verify_standard(standard["id"], "VERIFY")

    cycle = open_cycle(
        community["id"],
        cycle_year=2025,
        cycle_start_date="2025-01-01T00:00:00Z",
        cycle_end_date="2025-12-31T00:00:00Z",
        due_at="2026-09-01T00:00:00Z",
    )
    cycle = submit_cycle(cycle["id"])
    assert cycle["verification_visit_required"] is True

    resp = api.certify_crs_cycle(cycle["id"], _COORD)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_VISIT_REQUIRED)

    after = read_cycle(cycle["id"])
    assert after["status"] == "SUBMITTED"
    assert after["verification_visit_required"] is True
    assert after["verification_visit_completed_at"] is None

    assert read_standard(standard["id"])["documentation_status"] == "VERIFIED"
    assert read_community(community["id"])["crs_class"] == 10


# ==========================================================================
# Temporal windows and deadlines
# ==========================================================================

def test_appeal_one_day_past_the_window_is_rejected(api):
    """PRD §3.7: "A `PropertyOwner` whose identifier equals the `property_id` of the case's
    structure may appeal a `DETERMINED` case — any other status is rejected with
    `ERR_DETERMINATION_NOT_DETERMINED` — by supplying an `appeal_basis`, provided the current
    logical clock is at or before `appeal_deadline_at`; a late filing is rejected with
    `ERR_APPEAL_WINDOW_CLOSED`."

    PRD §2.5: "A determination's `appeal_deadline_at` is its `determined_at` plus 30 days."

    Design: Corner/validations/appeal_one_day_past_the_window_is_rejected
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    append_record(
        scenario["structure"]["id"],
        record_type="IMPROVEMENT",
        event_date="2026-03-01T00:00:00Z",
        cost_usd=105_000.00,
    )

    case = _only_case_for_structure(api, scenario["structure"]["id"])
    case = determine_case(case["id"])
    assert case["status"] == "DETERMINED"
    assert case["determined_at"] is not None
    assert_days_after(case["appeal_deadline_at"], case["determined_at"], 30,
                      "appeal_deadline_at")
    assert parse_instant(case["appeal_deadline_at"]) == parse_instant("2026-08-31T00:00:00Z")

    set_clock("2026-09-01T00:00:00Z")

    owner_headers = make_property_owner_headers(scenario["property"]["id"])
    resp = api.appeal_case(
        case["id"], {"appeal_basis": "Survey disputes the cost basis"}, owner_headers
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    after = validate_success(api.get_determination_case(case["id"], _ADMIN), 200)
    assert after["status"] == "DETERMINED"
    assert after["appealed_at"] is None


def test_inspection_assessment_on_the_deadline_day_is_accepted(api):
    """PRD §3.7: "Assessment is admitted only while an inspection is `SCHEDULED`
    (`ERR_INSPECTION_NOT_SCHEDULED`) and only while the current logical clock is at or before
    `deadline_at` (`ERR_INSPECTION_WINDOW_CLOSED`)."

    PRD §2.5: "An inspection's `deadline_at` is the sweep's `disaster_event_date` plus the
    sweep's `inspection_window_days`."

    PRD §2.5: "Unless a rule explicitly says "strictly after", every comparison of the logical
    clock against a stored deadline is inclusive — acting exactly at the deadline instant is
    acting on time."

    Design: Corner/validations/inspection_assessment_on_the_deadline_day_is_accepted
    """
    scenario = setup_scheduled_inspection(
        sweep_overrides={
            "declaration_code": "DR-4700",
            "event_date": "2026-07-15T00:00:00Z",
            "inspection_window_days": 30,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    inspection = scenario["inspection"]
    assert_days_after(inspection["deadline_at"], inspection["disaster_event_date"], 30,
                      "deadline_at")
    assert parse_instant(inspection["deadline_at"]) == parse_instant("2026-08-14T00:00:00Z")

    set_clock("2026-08-14T00:00:00Z")

    resp = api.assess_inspection(
        inspection["id"],
        {"damage_cost_usd": 30_000.00, "claim_paid_amount_usd": 25_000.00},
        _ADMIN,
    )
    assessed = validate_success(resp, 200)
    assert assessed["status"] == "ASSESSED"
    assert float(assessed["damage_cost_usd"]) == pytest.approx(30_000.00, abs=0.01)
    assert float(assessed["claim_paid_amount_usd"]) == pytest.approx(25_000.00, abs=0.01)

    structure = read_structure(scenario["structure"]["id"])
    assert float(structure["cumulative_counted_cost_usd"]) == 0


def test_cycle_lapse_exactly_at_due_at_is_rejected(api):
    """PRD §3.9: "A lapse, recorded by the coordinator on a cycle still `OPEN` while the
    logical clock is strictly past `due_at` — else `ERR_CYCLE_NOT_PAST_DUE` — moves the cycle
    to the terminal `LAPSED` and resets the community's `crs_class` to 10."

    PRD §3.9: "That flag is true when `cycle_year` is an exact multiple of 5, and also true
    whenever a `provisional_class` has been computed and is numerically lower — that is,
    better — than `prior_class`."

    PRD §3.1: "A freshly registered community starts with `sanction_risk_points` at 0,
    `compliance_posture` at `GOOD_STANDING`, `crs_credit_points_claimed` and
    `crs_credit_points_verified` at 0, `crs_class` at 10, `standards_adopted_at` set to the
    current logical clock, and `version` at 1."

    Design: Corner/validations/cycle_lapse_exactly_at_due_at_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    cycle = open_cycle(
        community["id"],
        cycle_year=2025,
        cycle_start_date="2025-01-01T00:00:00Z",
        cycle_end_date="2025-12-31T00:00:00Z",
        due_at="2026-08-01T00:00:00Z",
    )
    assert cycle["status"] == "OPEN"

    resp = api.lapse_crs_cycle(cycle["id"], _COORD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_PAST_DUE)

    after = read_cycle(cycle["id"])
    assert after["status"] == "OPEN"
    assert after["verification_visit_required"] is True
    assert read_community(community["id"])["crs_class"] == 10


def test_order_default_before_the_deadline_is_rejected(api):
    """PRD §3.8: "`DEFAULTED` requires that the current logical clock be strictly past the
    order's `deadline_at`, else `ERR_ORDER_DEADLINE_NOT_PASSED`, and it opens the enforcement
    cascade."

    PRD §3.8: "**Step one** produces the raw score: the severity weights of every violation
    belonging to any property of the community whose `status` is `OPEN`, `ORDER_ISSUED`, or
    `ESCALATED` — 2 points for `MINOR`, 6 for `MAJOR`, 12 for `CRITICAL` — plus 5 points for
    each `DEFAULTED` remediation order whose violation is still `ESCALATED` and whose violation
    belongs to a property of the community."

    Design: Corner/validations/order_default_before_the_deadline_is_rejected
    """
    scenario = setup_violation_with_order(
        violation_overrides={"violation_type": "NO_PERMIT", "severity": "MAJOR"},
        order_deadline_at="2026-09-01T00:00:00Z",
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    order = scenario["order"]

    resp = api.resolve_remediation_order(order["id"], {"resolution": "DEFAULTED"}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_DEADLINE_NOT_PASSED)

    after = _read_order(api, order["id"])
    assert after["status"] == "ISSUED"
    assert after["extension_count"] == 0

    assert _read_violation(api, scenario["violation"]["id"])["status"] == "ORDER_ISSUED"
    assert_sanction_state(read_community(scenario["community"]["id"]), 6, "GOOD_STANDING")


def test_improvement_record_dated_one_day_ahead_is_rejected(api):
    """PRD §3.6: "Whichever route created it, a record names its `structure_id`, a
    `record_type` of `IMPROVEMENT`, `DAMAGE`, or `REVERSAL`, and an `event_date` — the date the
    work or the damage actually occurred, which is what drives window membership and which may
    not be later than the current logical clock (`ERR_EVENT_DATE_IN_FUTURE`)."

    Design: Corner/validations/improvement_record_dated_one_day_ahead_is_rejected
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )

    resp = api.append_improvement_record(
        {
            "structure_id": scenario["structure"]["id"],
            "record_type": "IMPROVEMENT",
            "event_date": "2026-08-02T00:00:00Z",
            "cost_usd": 60_000.00,
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_DATE_IN_FUTURE)

    structure = read_structure(scenario["structure"]["id"])
    assert_ledger_aggregates(structure, None, 0, 0.0, 0.0)
    assert structure["version"] == 1


def test_clock_cannot_be_moved_backwards(api):
    """PRD §2.5: "The clock is monotonic: a target instant earlier than the current logical
    clock is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/validations/clock_cannot_be_moved_backwards
    """
    set_clock("2026-09-01T00:00:00Z")

    resp = api.set_clock("2026-08-31T00:00:00Z", _COORD)
    validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC)


def test_third_order_extension_is_rejected(api):
    """PRD §3.8: "An order may be extended while its `status` is `ISSUED` or `EXTENDED`, while
    `extension_count` is strictly less than 2, and only with a `deadline_at` strictly after the
    order's current `deadline_at`; a third extension or a non-advancing deadline is rejected
    with `ERR_EXTENSION_LIMIT_EXCEEDED`, and an attempt to extend an order that is already
    `SATISFIED` or `DEFAULTED` is rejected with `ERR_ORDER_NOT_ACTIONABLE`."

    Design: Corner/validations/third_order_extension_is_rejected
    """
    scenario = setup_violation_with_order(
        violation_overrides={"violation_type": "UNPERMITTED_FILL", "severity": "MAJOR"},
        order_deadline_at="2026-09-01T00:00:00Z",
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    order_id = scenario["order"]["id"]

    extend_order(order_id, "2026-10-01T00:00:00Z")
    second = extend_order(order_id, "2026-11-01T00:00:00Z")
    assert second["extension_count"] == 2

    resp = api.extend_remediation_order(
        order_id, {"deadline_at": "2026-12-01T00:00:00Z"}, _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)

    after = _read_order(api, order_id)
    assert after["status"] == "EXTENDED"
    assert after["extension_count"] == 2
    assert parse_instant(after["deadline_at"]) == parse_instant("2026-11-01T00:00:00Z")


def test_extension_to_an_unchanged_deadline_is_rejected(api):
    """PRD §3.8: "An order may be extended while its `status` is `ISSUED` or `EXTENDED`, while
    `extension_count` is strictly less than 2, and only with a `deadline_at` strictly after the
    order's current `deadline_at`; a third extension or a non-advancing deadline is rejected
    with `ERR_EXTENSION_LIMIT_EXCEEDED`, and an attempt to extend an order that is already
    `SATISFIED` or `DEFAULTED` is rejected with `ERR_ORDER_NOT_ACTIONABLE`."

    Design: Corner/validations/extension_to_an_unchanged_deadline_is_rejected
    """
    scenario = setup_violation_with_order(
        violation_overrides={"violation_type": "MISSING_CERTIFICATE", "severity": "MINOR"},
        order_deadline_at="2026-09-01T00:00:00Z",
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    order_id = scenario["order"]["id"]

    resp = api.extend_remediation_order(
        order_id, {"deadline_at": "2026-09-01T00:00:00Z"}, _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)

    after = _read_order(api, order_id)
    assert after["status"] == "ISSUED"
    assert after["extension_count"] == 0
    assert parse_instant(after["deadline_at"]) == parse_instant("2026-09-01T00:00:00Z")


# ==========================================================================
# Uniqueness and single-active guards
# ==========================================================================

def test_duplicate_parcel_id_inside_one_community_is_rejected(api):
    """PRD §3.3: "The `parcel_id` must be unique within its community; a repeat is rejected
    with `ERR_DUPLICATE_PARCEL_ID`."

    Design: Corner/validations/duplicate_parcel_id_inside_one_community_is_rejected
    """
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        property_overrides={
            "parcel_id": "P-0001",
            "mapped_area_code": "RLA-1",
            "owner_name": "A Owner",
            "owner_email": "a@example.com",
        },
    )

    resp = api.create_property(
        {
            "community_id": scenario["community"]["id"],
            "firm_panel_id": scenario["panel"]["id"],
            "parcel_id": "P-0001",
            "mapped_area_code": "RLA-2",
            "owner_name": "B Owner",
            "owner_email": "b@example.com",
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARCEL_ID)

    after = read_property(scenario["property"]["id"])
    assert after["parcel_id"] == "P-0001"
    assert after["mapped_area_code"] == "RLA-1"
    assert after["owner_name"] == "A Owner"


def test_duplicate_cycle_year_with_disjoint_windows_is_rejected(api):
    """PRD §3.9: "Recertification runs on `CrsCycle` records opened by the
    `StateNfipCoordinator` with the `community_id`, the `cycle_year` — unique per community,
    else `ERR_DUPLICATE_CYCLE_YEAR` — the closed coverage interval `cycle_start_date` through
    `cycle_end_date` with the end strictly after the start, and the submission deadline
    `due_at`."

    PRD §2.11: "A candidate interval running from `cycle_start_date` through `cycle_end_date`
    inclusive may not intersect the closed interval of any cycle of the same community whose
    `status` is `OPEN`, `SUBMITTED`, `UNDER_VERIFICATION`, `CERTIFIED`, or `RETROGRADED`; only
    `LAPSED` cycles are ignored."

    Design: Corner/validations/duplicate_cycle_year_with_disjoint_windows_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    first = open_cycle(
        community["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-06-30T00:00:00Z",
        due_at="2027-03-01T00:00:00Z",
    )

    resp = api.create_crs_cycle(
        {
            "community_id": community["id"],
            "cycle_year": 2026,
            "cycle_start_date": "2026-07-01T00:00:00Z",
            "cycle_end_date": "2026-12-31T00:00:00Z",
            "due_at": "2027-09-01T00:00:00Z",
        },
        _COORD,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE_YEAR)

    after = read_cycle(first["id"])
    assert after["cycle_year"] == 2026
    assert after["status"] == "OPEN"
    assert parse_instant(after["cycle_end_date"]) == parse_instant("2026-06-30T00:00:00Z")

    cycles, _meta = validate_paginated(
        api.list_crs_cycles(_COORD, params={"community_id": community["id"]})
    )
    assert len(cycles) == 1


def test_duplicate_declaration_code_with_disjoint_windows_is_rejected(api):
    """PRD §3.7: "The `declaration_code` must be unique per community
    (`ERR_DUPLICATE_DECLARATION_CODE`) and the sweep's buffer-expanded window must not conflict
    with an existing sweep of that community, per §2.11."

    PRD §2.11: "A candidate sweep's window is expanded to run from 7 days before its event date
    to 7 days after its event date plus its `inspection_window_days`, and that expanded window
    may not intersect the closed window running from any existing sweep's `disaster_event_date`
    through that sweep's `deadline_at`."

    Design: Corner/validations/duplicate_declaration_code_with_disjoint_windows_is_rejected
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    sweep = run_sweep(
        scenario["community"]["id"],
        declaration_code="DR-4700",
        event_date="2026-01-01T00:00:00Z",
        inspection_window_days=30,
    )
    first = read_inspection(sweep["inspection_ids"][0])
    assert parse_instant(first["deadline_at"]) == parse_instant("2026-01-31T00:00:00Z")

    resp = api.open_inspection_sweep(
        scenario["community"]["id"],
        {
            "declaration_code": "DR-4700",
            "event_date": "2026-06-01T00:00:00Z",
            "inspection_window_days": 30,
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DECLARATION_CODE)

    inspections, _meta = validate_paginated(
        api.list_inspections(_ADMIN, params={"structure_id": scenario["structure"]["id"]})
    )
    assert len(inspections) == 1
    assert inspections[0]["declaration_code"] == "DR-4700"
    assert parse_instant(inspections[0]["disaster_event_date"]) == parse_instant(
        "2026-01-01T00:00:00Z"
    )


def test_second_active_order_for_one_violation_is_rejected(api):
    """PRD §3.8: "At most one order per violation may be active at a time: if an order with
    `status` `ISSUED` or `EXTENDED` already exists for that violation, the second is rejected
    with `ERR_ORDER_ALREADY_ACTIVE`."

    PRD §2.8: "One deliberate asymmetry lives here: issuing a remediation order admits a
    violation that is already `ORDER_ISSUED` at this step, so that the duplicate-order rule at
    step 18 is the check that actually rejects a second active order."

    Design: Corner/validations/second_active_order_for_one_violation_is_rejected
    """
    scenario = setup_violation_with_order(
        violation_overrides={"violation_type": "NO_PERMIT", "severity": "MAJOR"},
        order_deadline_at="2026-09-01T00:00:00Z",
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )

    resp = api.create_remediation_order(
        {
            "violation_id": scenario["violation"]["id"],
            "required_action": "Elevate the lowest floor to the required elevation",
            "deadline_at": "2026-10-01T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_ACTIVE)

    after = _read_order(api, scenario["order"]["id"])
    assert after["status"] == "ISSUED"
    assert parse_instant(after["deadline_at"]) == parse_instant("2026-09-01T00:00:00Z")

    assert _read_violation(api, scenario["violation"]["id"])["status"] == "ORDER_ISSUED"


def test_second_reversal_of_the_same_record_is_rejected(api):
    """PRD §3.6: "A row that has already been reversed cannot be reversed again
    (`ERR_RECORD_ALREADY_REVERSED`)."

    PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the row itself as
    `counted_in_cumulative`, and the rule is a conjunction of three conditions: the
    `record_type` must be `IMPROVEMENT` or `DAMAGE`, `is_code_compliance_only` must be false,
    and `cost_usd` must be at least 500.00."

    PRD §3.6: "When that set is empty, `anchor_record_id` is set to null,
    `cumulative_counted_cost_usd` to 0, and both `cumulative_improvement_pct` and
    `single_event_improvement_pct` to 0.00, and nothing further happens."

    Design: Corner/validations/second_reversal_of_the_same_record_is_rejected
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]
    original = append_record(
        structure_id,
        record_type="IMPROVEMENT",
        event_date="2026-03-01T00:00:00Z",
        cost_usd=60_000.00,
    )
    reversal = append_reversal(structure_id, original["id"], event_date="2026-03-01T00:00:00Z")
    assert reversal["counted_in_cumulative"] is False

    resp = api.append_improvement_record(
        {
            "structure_id": structure_id,
            "record_type": "REVERSAL",
            "event_date": "2026-03-01T00:00:00Z",
            "reverses_record_id": original["id"],
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_REVERSED)

    assert _read_record(api, original["id"])["reversed"] is True
    assert_ledger_aggregates(read_structure(structure_id), None, 0, 0.0, 0.0)
