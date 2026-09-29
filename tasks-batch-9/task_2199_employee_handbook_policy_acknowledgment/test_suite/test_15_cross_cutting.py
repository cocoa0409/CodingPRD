"""Optimistic concurrency on the three guarded writes, approval pinning and the sweep."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_policy_version_payload,
    make_admin_headers,
    make_author_headers,
    new_document,
    new_jurisdiction,
    refresh_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_document_token_read_before_the_first_mint_is_stale_for_the_second():
    """PRD §2.6: "Minting a new policy version under a policy document requires
    `expected_policy_document_version` carrying the client's last observed `version` of
    that `PolicyDocument`." ... "If the supplied value does not equal the document's
    current `version`, the request is rejected with
    `ERR_STALE_POLICY_DOCUMENT_VERSION` at HTTP 412."

    Design: Corner/cross-cutting complexity layers/corner_occ_on_version_mint_rejects_a_stale_document_view
    """
    jurisdiction = new_jurisdiction(min_legal_review_days=5)
    document = new_document()
    first_token = document["version"]

    validate_success(
        api_client.create_policy_version(
            document["id"],
            create_policy_version_payload(
                [jurisdiction["id"]], first_token, body_text="First draft"
            ),
            make_author_headers(),
        ),
        201,
    )

    validate_error(
        api_client.create_policy_version(
            document["id"],
            create_policy_version_payload(
                [jurisdiction["id"]], first_token, body_text="Second draft"
            ),
            make_author_headers(),
        ),
        ApiErrorId.ERR_STALE_POLICY_DOCUMENT_VERSION,
    )

    _rows, meta = validate_paginated(
        api_client.list_policy_versions(
            make_admin_headers(),
            params={"policy_document_id": document["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused mint must persist no version row, got {meta['total_count']}"
    )
    after_first = refresh_document(document["id"])
    assert after_first["latest_version_no"] == 1, (
        f"only one version was minted, got {after_first['latest_version_no']}"
    )
    assert after_first["version"] == first_token + 1, (
        "minting mutates the document row itself, so its version must advance to "
        f"{first_token + 1}, got {after_first['version']}"
    )

    second = validate_success(
        api_client.create_policy_version(
            document["id"],
            create_policy_version_payload(
                [jurisdiction["id"]], after_first["version"], body_text="Second draft"
            ),
            make_author_headers(),
        ),
        201,
    )
    assert second["version_no"] == 2, (
        f"the re-read token must admit version_no 2, got {second['version_no']}"
    )
    assert second["status"] == "DRAFT"

    after_second = refresh_document(document["id"])
    assert after_second["latest_version_no"] == 2, (
        f"the document must now report two versions, got {after_second['latest_version_no']}"
    )
    assert after_second["version"] == after_first["version"] + 1, (
        "the counter advances on every write, got "
        f"{after_second['version']} after {after_first['version']}"
    )
    assert after_second["current_published_version_id"] is None, (
        "nothing has been released, got "
        f"{after_second['current_published_version_id']}"
    )


def test_an_hr_edit_to_the_employee_row_invalidates_the_requester_token():
    """PRD §2.6: "Creating a policy exception requires `expected_employee_version`
    carrying the client's last observed `version` of the requesting `Employee`." ... "If
    the supplied value does not equal the employee's current `version`, the request is
    rejected with `ERR_STALE_EMPLOYEE_VERSION` at HTTP 412."  PRD §3.1: "An
    `HRComplianceAdmin` may later update an employee's `employment_status` ... and any
    such update increments the employee's `version` by 1."

    Design: Corner/cross-cutting complexity layers/corner_occ_on_exception_request_rejects_a_stale_employee_view
    """
    from test_helpers import (
        assert_same_instant,
        create_policy_exception_payload,
        make_employee_headers,
        patch_employee,
        refresh_assignment,
        refresh_employee,
        setup_released_scenario,
    )

    ctx = setup_released_scenario(
        jurisdiction={
            "min_legal_review_days": 5,
            "ack_deadline_days": 30,
            "esign_permitted": True,
            "ack_window_buffer_days": 3,
        },
        effective_date="2026-09-01T00:00:00Z",
    )
    subject, assignment = ctx["employee"], ctx["assignment"]
    stale_token = refresh_employee(subject["id"])["version"]

    patched = patch_employee(subject["id"], employment_status="ON_LEAVE")
    assert patched["employment_status"] == "ON_LEAVE"
    assert patched["version"] == stale_token + 1, (
        f"the HR edit must bump the employee version to {stale_token + 1}, got "
        f"{patched['version']}"
    )

    validate_error(
        api_client.create_policy_exception(
            create_policy_exception_payload(
                ctx["version"]["id"],
                stale_token,
                reason_code="MEDICAL",
                justification="Surgery recovery",
                requested_days=30,
            ),
            make_employee_headers(subject["id"]),
        ),
        ApiErrorId.ERR_STALE_EMPLOYEE_VERSION,
    )
    _rows, meta = validate_paginated(
        api_client.list_policy_exceptions(
            make_admin_headers(), params={"employee_id": subject["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused request must persist no exception row, got {meta['total_count']}"
    )

    fresh_token = refresh_employee(subject["id"])["version"]
    assert fresh_token == patched["version"], (
        "the refused request must not have moved the employee row again, got "
        f"{fresh_token} against {patched['version']}"
    )

    request = validate_success(
        api_client.create_policy_exception(
            create_policy_exception_payload(
                ctx["version"]["id"],
                fresh_token,
                reason_code="MEDICAL",
                justification="Surgery recovery",
                requested_days=30,
            ),
            make_employee_headers(subject["id"]),
        ),
        201,
    )
    assert request["status"] == "SUBMITTED", (
        f"the re-read token must be accepted, got {request['status']}"
    )
    assert float(request["risk_score_aggregate"]) == 23.50, (
        "0.20*25 + 0.15*16.6667 + 0.25*0 + 0.40*40 is 23.50, got "
        f"{request['risk_score_aggregate']}"
    )
    assert_same_instant(
        refresh_assignment(assignment["id"])["due_date"],
        "2026-10-01T00:00:00.000Z",
        "the due date was derived once at mint from the then-ACTIVE employee, so the "
        "ON_LEAVE edit must not re-derive the pinned window",
    )


def test_an_unschedule_reschedule_round_trip_invalidates_the_release_token():
    """PRD §2.6: "Releasing a release package requires
    `expected_release_package_version` carrying the client's last observed `version` of
    that `ReleasePackage`." ... "If the supplied value does not equal the package's
    current `version`, the request is rejected with
    `ERR_STALE_RELEASE_PACKAGE_VERSION` at HTTP 412."

    Design: Corner/cross-cutting complexity layers/corner_occ_on_release_rejects_a_token_read_before_reschedule
    """
    from test_helpers import (
        add_item,
        new_employee,
        new_package,
        refresh_package,
        schedule_package,
        set_clock,
        setup_approved_version,
    )

    ctx = setup_approved_version(
        jurisdiction={"min_legal_review_days": 5, "esign_permitted": True}
    )
    new_employee(ctx["jurisdiction"]["id"])
    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])

    stale_token = schedule_package(package["id"])["version"]
    validate_success(
        api_client.unschedule_release_package(package["id"], make_admin_headers())
    )
    rescheduled = schedule_package(package["id"])
    assert rescheduled["version"] == stale_token + 2, (
        "the round trip is two lifecycle hops, so the version must reach "
        f"{stale_token + 2}, got {rescheduled['version']}"
    )
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": stale_token},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_STALE_RELEASE_PACKAGE_VERSION,
    )
    blocked = refresh_package(package["id"])
    assert blocked["status"] == "SCHEDULED", (
        f"the refused release must leave the package SCHEDULED, got {blocked['status']}"
    )
    assert blocked["version"] == rescheduled["version"], (
        "a refused release must not move the package version off "
        f"{rescheduled['version']}, got {blocked['version']}"
    )
    _rows, meta = validate_paginated(
        api_client.list_assignments(
            make_admin_headers(),
            params={"release_package_id": package["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused release must mint zero assignments, got {meta['total_count']}"
    )

    released = validate_success(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": blocked["version"]},
            make_admin_headers(),
        )
    )
    assert released["status"] == "RELEASED", (
        f"the re-read token must be accepted, got {released['status']}"
    )
    assert released["roster_snapshot_size"] == 1, (
        f"the single in-scope employee is minted one row, got {released['roster_snapshot_size']}"
    )
    assert released["version"] == blocked["version"] + 1, (
        "the release hop increments the version once more, to "
        f"{blocked['version'] + 1}, got {released['version']}"
    )
    _rows, meta = validate_paginated(
        api_client.list_assignments(
            make_admin_headers(),
            params={"release_package_id": package["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one assignment must now exist, got {meta['total_count']}"
    )


def test_the_sweep_is_inert_at_the_due_instant_and_idempotent_afterwards():
    """PRD §3.8: "`days_overdue` is 0 whenever the logical clock is at or before the
    assignment's `due_date`; once the clock passes the due date it is the
    floor-truncated whole-day difference from `due_date` to the logical clock." ... "For
    each assignment whose `ack_state` is `PENDING`, whose `escalation_state` is `NONE`,
    whose `days_overdue` is at least 1, and against which no exception request is
    currently sitting in `SUBMITTED` or `MANAGER_APPROVED`, the escalation dimension
    moves `NONE → ESCALATING`".

    Design: Corner/cross-cutting complexity layers/corner_escalation_sweep_fires_only_after_the_deferred_threshold
    """
    from test_helpers import (
        assert_same_instant,
        refresh_assignment,
        refresh_case,
        refresh_employee,
        set_clock,
        setup_released_scenario,
        sweep,
    )

    ctx = setup_released_scenario(
        jurisdiction={
            "min_legal_review_days": 5,
            "ack_deadline_days": 30,
            "esign_permitted": True,
        },
        effective_date="2026-09-01T00:00:00Z",
    )
    subject, assignment = ctx["employee"], ctx["assignment"]
    assert assignment["ack_state"] == "PENDING"
    assert_same_instant(
        assignment["window_start_date"], "2026-09-01T00:00:00.000Z", "window_start_date"
    )
    assert_same_instant(assignment["due_date"], "2026-10-01T00:00:00.000Z", "due_date")

    def _case_rows():
        rows, meta = validate_paginated(
            api_client.list_escalations(
                make_admin_headers(),
                params={"assignment_id": assignment["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == len(rows)
        return rows

    def _cases():
        return len(_case_rows())

    set_clock("2026-10-01T00:00:00Z")
    sweep()
    at_due = refresh_assignment(assignment["id"])
    assert at_due["days_overdue"] == 0, (
        f"a clock at the due_date leaves days_overdue at 0, got {at_due['days_overdue']}"
    )
    assert at_due["escalation_state"] == "NONE", (
        f"the escalation dimension must stay NONE, got {at_due['escalation_state']}"
    )
    assert _cases() == 0, "no case may exist at the due instant"
    assert refresh_employee(subject["id"])["open_escalation_count"] == 0

    set_clock("2026-10-02T00:00:00Z")
    sweep()
    opened = _case_rows()
    assert len(opened) == 1, (
        f"one day past the due date opens exactly one case, got {len(opened)}"
    )
    case = opened[0]
    assert case["status"] == "OPEN", (
        f"a fresh case starts in OPEN, got {case['status']}"
    )
    assert case["tier"] == 1, (
        f"1 day overdue falls in the [1,7) band, which is tier 1, got {case['tier']}"
    )
    assert refresh_assignment(assignment["id"])["escalation_state"] == "ESCALATING"
    assert refresh_employee(subject["id"])["open_escalation_count"] == 1, (
        "the subject now carries one open case, got "
        f"{refresh_employee(subject['id'])['open_escalation_count']}"
    )

    sweep()
    assert _cases() == 1, (
        "the assignment has already left NONE, so a repeated sweep at the same clock "
        f"must open no further case; got {_cases()} cases"
    )
    assert refresh_case(case["id"])["tier"] == 1, (
        "days_overdue is still 1, so the re-tiering must leave the case at tier 1, got "
        f"{refresh_case(case['id'])['tier']}"
    )
    assert refresh_employee(subject["id"])["open_escalation_count"] == 1
    assert refresh_assignment(assignment["id"])["ack_state"] == "PENDING", (
        "the deferred action moves only the escalation dimension, got "
        f"{refresh_assignment(assignment['id'])['ack_state']}"
    )
