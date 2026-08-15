"""Nightly sleep logs: submission rules, review transitions, the regression
cascade (depth 3), conditional no-op links, and log listing pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_case,
    get_consultant,
    make_consultant_headers,
    make_parent_headers,
    review_log_entry,
    review_log_payload,
    set_logical_clock,
    setup_case_in_active_support,
    submit_log_for_case,
    submit_log_payload,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["practice_admin_headers"]


def test_regression_review_cascade_depth3(api):
    """PRD §3.5: "A `REGRESSION` outcome moves it to `REVIEWED_REGRESSION` and fires
    the three-link regression cascade, with each link conditional on current state —
    a link already sitting in its target state is a no-op. Link one: the case's
    current plan, if `ACTIVE`, becomes `NEEDS_ADJUSTMENT`. Link two: the case, if
    `ACTIVE_SUPPORT`, becomes `NEEDS_ATTENTION`, incrementing the case `version`.
    Link three: the consultant's `active_case_count` is recomputed and drops by one,
    because a case in `NEEDS_ATTENTION` no longer counts against the cap."

    Design: Difficulty/transitive_cascade/regression_review_cascade_depth3
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, plan = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["plan"],
    )
    count_before = get_consultant(consultant["id"])["active_case_count"]
    assert count_before == 1

    log = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=6)
    reviewed = review_log_entry(log["id"], consultant, outcome="REGRESSION")
    assert reviewed["review_status"] == "REVIEWED_REGRESSION"  # trigger row

    plans, _ = validate_paginated(
        api.list_plans(case["id"], make_consultant_headers(consultant["id"]))
    )
    link1 = [p for p in plans if p["id"] == plan["id"]][0]
    assert link1["status"] == "NEEDS_ADJUSTMENT", "link 1: plan ACTIVE -> NEEDS_ADJUSTMENT"
    assert get_case(case["id"])["status"] == "NEEDS_ATTENTION", "link 2: case transition"
    count_after = get_consultant(consultant["id"])["active_case_count"]
    assert count_after == 0, (
        f"link 3: active_case_count 1 -> 0, got {count_after}"
    )


def test_on_track_review_fires_no_cascade(api):
    """PRD §3.5: "An `ON_TRACK` outcome simply moves the log to `REVIEWED_ON_TRACK`."

    Design: Difficulty/transitive_cascade/regression_review_cascade_depth3
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, plan = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["plan"],
    )
    log = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=1)
    reviewed = review_log_entry(log["id"], consultant, outcome="ON_TRACK")
    assert reviewed["review_status"] == "REVIEWED_ON_TRACK"

    plans, _ = validate_paginated(
        api.list_plans(case["id"], make_consultant_headers(consultant["id"]))
    )
    assert plans[0]["status"] == "ACTIVE", "ON_TRACK leaves the plan untouched"
    assert get_case(case["id"])["status"] == "ACTIVE_SUPPORT"
    assert get_consultant(consultant["id"])["active_case_count"] == 1


def test_regression_cascade_conditional_noop(api):
    """PRD §3.5: "A `REGRESSION` outcome moves it to `REVIEWED_REGRESSION` and fires
    the three-link regression cascade, with each link conditional on current state —
    a link already sitting in its target state is a no-op."
    PRD §3.5: "The entry names its `log_date`, which must not be later than the
    logical clock date (a future date is rejected with `ERR_INVALID_REQUEST`) and
    must be unique within the case (a second log for the same date is rejected with
    `ERR_DUPLICATE_LOG`)."

    A second REGRESSION while the plan is already NEEDS_ADJUSTMENT and the case
    already NEEDS_ATTENTION succeeds without re-firing any link.

    Design: Corner/state_machines/regression_cascade_conditional_noop
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, plan = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["plan"],
    )
    cons_headers = make_consultant_headers(consultant["id"])

    log1 = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=6)
    review_log_entry(log1["id"], consultant, outcome="REGRESSION")
    assert get_consultant(consultant["id"])["active_case_count"] == 0

    # Uniqueness still binds while the case is NEEDS_ATTENTION.
    res = api.submit_log(
        case["id"],
        submit_log_payload("2026-08-01", night_wake_count=6),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_LOG.value, expected_status=409)

    set_logical_clock("2026-08-02T00:00:00Z")
    log2 = submit_log_for_case(case["id"], family, "2026-08-02", night_wake_count=6)
    reviewed = review_log_entry(log2["id"], consultant, outcome="REGRESSION")
    assert reviewed["review_status"] == "REVIEWED_REGRESSION"

    plans, _ = validate_paginated(api.list_plans(case["id"], cons_headers))
    assert plans[0]["status"] == "NEEDS_ADJUSTMENT", "link already in target: no-op"
    assert get_case(case["id"])["status"] == "NEEDS_ATTENTION", "link already in target: no-op"
    assert get_consultant(consultant["id"])["active_case_count"] == 0, "no double decrement"


def test_double_review_rejected(api):
    """PRD §3.2: "The review requires the questionnaire to still be `SUBMITTED` (a
    second review is rejected with `ERR_QUESTIONNAIRE_ALREADY_REVIEWED`) and the case
    to be in `ASSESSMENT`."
    PRD §3.5: "The assigned `Consultant` reviews each pending log with an `outcome`
    of `ON_TRACK` or `REGRESSION` and an optional `review_note`; reviewing anything
    other than a `PENDING_REVIEW` log is rejected with `ERR_LOG_ALREADY_REVIEWED`."

    Design: Corner/state_machines/double_review_rejected
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, questionnaire = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["questionnaire"],
    )
    cons_headers = make_consultant_headers(consultant["id"])

    log = submit_log_for_case(case["id"], family, "2026-08-01")
    review_log_entry(log["id"], consultant, outcome="ON_TRACK")

    res = api.review_questionnaire(
        questionnaire["id"],
        {"adjustment_points": 5},
        cons_headers,
    )
    validate_error(res, ApiErrorId.ERR_QUESTIONNAIRE_ALREADY_REVIEWED.value, expected_status=409)

    res = api.review_log(log["id"], review_log_payload("REGRESSION"), cons_headers)
    validate_error(res, ApiErrorId.ERR_LOG_ALREADY_REVIEWED.value, expected_status=409)

    # The rejected second review fires no regression cascade.
    logs, _ = validate_paginated(api.list_logs(case["id"], cons_headers))
    assert logs[0]["review_status"] == "REVIEWED_ON_TRACK"
    assert get_case(case["id"])["status"] == "ACTIVE_SUPPORT"


def test_log_future_date_rejected(api):
    """PRD §3.5: "The entry names its `log_date`, which must not be later than the
    logical clock date (a future date is rejected with `ERR_INVALID_REQUEST`) and
    must be unique within the case (a second log for the same date is rejected with
    `ERR_DUPLICATE_LOG`)."

    At the default clock 2026-08-01, log_date 2026-08-02 is in the future; tonight's
    own date 2026-08-01 is accepted.

    Design: Corner/validations/log_future_date_rejected
    """
    bundle = setup_case_in_active_support()
    case, family = bundle["case"], bundle["family"]
    res = api.submit_log(
        case["id"],
        submit_log_payload("2026-08-02"),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    log = submit_log_for_case(case["id"], family, "2026-08-01")
    assert log["review_status"] == "PENDING_REVIEW"


def test_logs_listing_pagination_defaults(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`, which defaults
    to 10 and must lie between 1 and 100 inclusive, and `offset`, which defaults to
    0. Responses for list endpoints carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside `meta`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Three logs paginate 2 + 1 under limit=2.

    Design: Corner/endpoints/logs_listing_pagination_defaults
    """
    bundle = setup_case_in_active_support()
    case, family = bundle["case"], bundle["family"]
    headers = make_parent_headers(family["id"])
    for log_date in ("2026-07-30", "2026-07-31", "2026-08-01"):
        submit_log_for_case(case["id"], family, log_date)

    res1 = api.list_logs(case["id"], headers, params={"limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(res1)
    assert res1.json()["response_type"] == "array"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    res2 = api.list_logs(case["id"], headers, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(res2)
    assert len(page2) == 1
    assert meta2["has_more"] is False
