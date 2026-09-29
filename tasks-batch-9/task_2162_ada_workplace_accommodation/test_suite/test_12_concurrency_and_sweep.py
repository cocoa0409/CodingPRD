"""Optimistic concurrency on the three guarded writes, and the sweep's
behaviour when nothing is due."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_calendar_date,
    case_version,
    issue_doc_round,
    open_case,
    option_version,
    read_case,
    read_employee,
    read_option,
    run_sweep,
    set_clock,
    setup_case_at_hardship_review,
    setup_case_at_renewal_due,
    setup_workforce,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_a_stale_case_version_is_refused_on_a_documentation_round(api):
    """PRD §2.7: "**Issuing a medical documentation round** on an accommodation
    case requires `expected_request_version` carrying the client's last observed
    `version` of that `AccommodationRequest`."
    PRD §2.7: "If the supplied value differs from the case's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "A successful issue creates the round in `status` `ISSUED` with
    `issued_at` read from the logical clock and `round_index` set to the case's
    `medical_doc_request_count` plus one — a 1-based ordinal assigned in
    issuance order."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_request_version_rejects_documentation_round
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CQ1", with_manager=False)
    case = open_case(ctx, disability_obvious=False)
    stale_version = case["version"]

    issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")

    stale = api.create_medical_doc_request(
        case["id"],
        {
            "scope_fields_requested": ["work_restrictions"],
            "due_date": "2026-08-31T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": stale_version,
        },
        COORD,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert read_case(case["id"])["medical_doc_request_count"] == 1

    fresh_version = case_version(case["id"])
    assert fresh_version > stale_version

    retry = api.create_medical_doc_request(
        case["id"],
        {
            "scope_fields_requested": ["work_restrictions"],
            "due_date": "2026-08-31T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": fresh_version,
        },
        COORD,
    )
    created = validate_success(retry, 201)
    assert created["round_index"] == 2

    refreshed = read_case(case["id"])
    assert refreshed["medical_doc_request_count"] == 2
    assert refreshed["documentation_budget_remaining"] == 0


def test_a_cost_revision_invalidates_the_officers_concurrency_token(api):
    """PRD §2.7: "**Recording an undue-hardship assessment** on an accommodation
    option requires `expected_option_version` carrying the client's last observed
    `version` of that `AccommodationOption`."
    PRD §2.7: "A mismatch against the option's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Note the interaction the option guard is designed to catch:
    revising an option's costs advances that option's `version` even when the
    revision leaves the option's `status` unchanged at `PROPOSED`."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_option_version_rejects_hardship_assessment
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_hardship_review(
        option_specs=[
            {
                "option_code": "C-OPT-49",
                "one_time_cost_cents": 40_000,
                "implementation_days": 10,
            }
        ],
        department_code="CQ2",
    )
    option = ctx["options"][0]
    stale_version = option_version(option["id"])

    revised = validate_success(
        api.update_accommodation_option(
            option["id"], {"one_time_cost_cents": 50_000}, COORD
        ),
        200,
    )
    assert revised["option_net_cost_cents"] == 37_000
    assert revised["status"] == "PROPOSED"

    stale = api.create_hardship_assessment(
        option["id"],
        {"assessment_basis": "SITE_LOCAL", "expected_option_version": stale_version},
        FINANCE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    _rows, meta = validate_paginated(api.list_hardship_assessments(option["id"], FINANCE))
    assert meta["total_count"] == 0

    retry = api.create_hardship_assessment(
        option["id"],
        {
            "assessment_basis": "SITE_LOCAL",
            "expected_option_version": option_version(option["id"]),
        },
        FINANCE,
    )
    assessment = validate_success(retry, 201)
    assert assessment["hardship_score"] == 34.57
    assert assessment["hardship_verdict"] == "NOT_UNDUE"
    assert read_option(option["id"])["status"] == "CLEARED"


def test_a_stale_case_version_is_refused_on_a_renewal_review(api):
    """PRD §2.7: "**Completing a recurring renewal review** on a case requires
    `expected_request_version` carrying the client's last observed `version` of
    that `AccommodationRequest`."
    PRD §2.7: "A mismatch against the case's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.9: "**`CONTINUE`** re-arms the cadence: the accommodation stands as it
    is, `review_due_date` is set to the current logical-clock date plus the
    standing `review_cadence_days`, and the case returns
    `RENEWAL_DUE → GRANTED_PERMANENT`."
    PRD §3.9: "All four outcomes increment `review_cycle_index` by one and
    increment the case's `version` by one; they differ in everything else."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_request_version_rejects_renewal_review
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_renewal_due(department_code="CQ3")
    current_version = case_version(ctx["case"]["id"])

    stale = api.renewal_review(
        ctx["case"]["id"],
        {"outcome": "CONTINUE", "expected_request_version": current_version - 1},
        COORD,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    midway = read_case(ctx["case"]["id"])
    assert midway["review_cycle_index"] == 0
    assert midway["stage"] == "RENEWAL_DUE"

    accepted = validate_success(
        api.renewal_review(
            ctx["case"]["id"],
            {"outcome": "CONTINUE", "expected_request_version": current_version},
            COORD,
        ),
        200,
    )
    assert accepted["review_cycle_index"] == 1
    assert accepted["stage"] == "GRANTED_PERMANENT"
    assert_calendar_date(accepted["review_due_date"], "2028-08-02", "review_due_date")


def test_the_sweep_reports_all_zeroes_when_nothing_is_due(api):
    """PRD §2.5: "The sweep response carries `swept_at` plus seven counters:
    `doc_requests_expired`, `absence_records_activated`,
    `absence_records_exhausted`, `trials_activated`, `trials_moved_to_review`,
    `requests_moved_to_renewal_due` and `denials_finalized`."
    PRD §2.5: "Moving the clock does not, by itself, advance any state machine."

    Design: Corner/cross_cutting_complexity_layers/corner_daily_sweep_is_a_noop_when_nothing_is_due
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CQ4", with_manager=False)

    counters = run_sweep()

    assert counters["swept_at"] == "2026-08-03T09:00:00.000Z"
    for name in (
        "doc_requests_expired",
        "absence_records_activated",
        "absence_records_exhausted",
        "trials_activated",
        "trials_moved_to_review",
        "requests_moved_to_renewal_due",
        "denials_finalized",
    ):
        assert counters[name] == 0, f"{name} must be 0 when nothing is due"

    employee = read_employee(ctx["employee"]["id"])
    assert employee["employment_status"] == "ACTIVE"
    assert employee["version"] == 1, "the sweep touched nothing"
