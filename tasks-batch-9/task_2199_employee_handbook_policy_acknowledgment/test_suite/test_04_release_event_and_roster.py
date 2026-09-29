"""The release event: roster minting, coverage variants and the supersede cascade."""
from test_helpers import (
    acknowledge,
    api_client,
    assert_same_instant,
    assignments_of,
    make_admin_headers,
    patch_employee,
    refresh_assignment,
    refresh_package,
    setup_released_scenario,
    validate_success,
)


def _coverage(package_id):
    return validate_success(api_client.get_coverage(package_id, make_admin_headers()))


def test_snapshot_and_live_coverage_denominators_diverge_after_a_termination():
    """PRD §3.6: "The `snapshot_roster` variant divides that numerator by
    `roster_snapshot_size`, the mint count frozen at release time, which still
    includes rows later voided and rows whose assignee has since become
    `TERMINATED`; the result is written to `coverage_snapshot_pct`. The
    `live_roster` variant divides the same numerator by the count of the package's
    assignments whose `ack_state` is anything other than `VOIDED` and whose
    assignee's `employment_status` is `ACTIVE` or `ON_LEAVE`; the result is written
    to `coverage_live_pct`."

    Design: Difficulty/dual_variant_calc/coverage_snapshot_vs_live_roster_denominator
    """
    ctx = setup_released_scenario(extra_employees=2)
    package, subject, extras = ctx["package"], ctx["employee"], ctx["extras"]
    assert package["roster_snapshot_size"] == 3, (
        "three in-scope ACTIVE employees must mint three assignments, got "
        f"{package['roster_snapshot_size']}"
    )

    acknowledge(ctx["assignment"], subject["id"])
    patch_employee(extras[1]["id"], employment_status="TERMINATED")

    coverage = _coverage(package["id"])
    assert coverage["roster_snapshot_size"] == 3, (
        "roster_snapshot_size is frozen at the mint count, got "
        f"{coverage['roster_snapshot_size']}"
    )
    assert float(coverage["coverage_snapshot_pct"]) == 33.33, (
        "one acknowledged over the frozen denominator of 3 is 33.333... which "
        f"rounds half up to 33.33, got {coverage['coverage_snapshot_pct']}"
    )
    assert float(coverage["coverage_live_pct"]) == 50.00, (
        "the live denominator drops the terminated assignee, leaving 1/2 = 50.00, "
        f"got {coverage['coverage_live_pct']}"
    )
    assert coverage["status"] == "RELEASED", (
        "two assignments are still UNDELIVERED so the package stays RELEASED, got "
        f"{coverage['status']}"
    )


def test_coverage_read_recomputes_both_variants_without_bumping_version():
    """PRD §3.6: "Both variants are computed when the package is released, and
    again when it closes, and again on every coverage read; the coverage read
    recomputes and returns both numbers **without** incrementing the package's
    `version`." ... "in both variants a denominator of zero yields exactly 100.00
    rather than an error or a null."

    Design: Difficulty/dual_variant_calc/coverage_snapshot_vs_live_roster_denominator
    """
    ctx = setup_released_scenario(extra_employees=1)
    package, subject = ctx["package"], ctx["employee"]
    assert package["roster_snapshot_size"] == 2

    at_release = _coverage(package["id"])
    baseline_version = at_release["version"]
    assert float(at_release["coverage_snapshot_pct"]) == 0.00, (
        "nothing is acknowledged yet so the snapshot variant is 0/2 = 0.00, got "
        f"{at_release['coverage_snapshot_pct']}"
    )
    assert float(at_release["coverage_live_pct"]) == 0.00

    again = _coverage(package["id"])
    assert again["version"] == baseline_version, (
        "a coverage read must not increment the package version, saw "
        f"{baseline_version} then {again['version']}"
    )

    acknowledge(ctx["assignment"], subject["id"])
    after_ack = _coverage(package["id"])
    assert float(after_ack["coverage_snapshot_pct"]) == 50.00, (
        f"1/2 = 50.00 expected, got {after_ack['coverage_snapshot_pct']}"
    )
    assert float(after_ack["coverage_live_pct"]) == 50.00
    assert after_ack["version"] == baseline_version, (
        "the package did not close, so no coverage read in this test may move its "
        f"version off {baseline_version}, got {after_ack['version']}"
    )


def test_release_with_only_a_terminated_employee_closes_at_full_coverage():
    """PRD §3.6: "in both variants a denominator of zero yields exactly 100.00
    rather than an error or a null." ... "That condition can be satisfied the
    instant the package is released if zero assignments were minted, in which case
    the package transitions straight through to `CLOSED` with both coverage figures
    at 100.00." ... "Terminated employees are never assigned."

    Design: Difficulty/boundary_precision_check/empty_roster_denominator_yields_full_coverage_and_immediate_close
    """
    from test_helpers import new_employee, refresh_version, released_package_for, setup_approved_version

    ctx = setup_approved_version()
    employee = new_employee(ctx["jurisdiction"]["id"])
    patch_employee(employee["id"], employment_status="TERMINATED")

    package = released_package_for(
        [ctx["version"]["id"]], [ctx["jurisdiction"]["id"]], "2026-08-15T00:00:00Z"
    )

    assert package["roster_snapshot_size"] == 0, (
        "the only in-scope employee is TERMINATED so nothing is minted, got "
        f"{package['roster_snapshot_size']}"
    )
    assert assignments_of(package["id"]) == [], (
        "a terminated employee must receive no assignment"
    )
    assert package["status"] == "CLOSED", (
        "with zero open assignments the package must pass straight to CLOSED, got "
        f"{package['status']}"
    )
    assert float(package["coverage_snapshot_pct"]) == 100.00, (
        f"a zero denominator yields exactly 100.00, got {package['coverage_snapshot_pct']}"
    )
    assert float(package["coverage_live_pct"]) == 100.00, (
        f"a zero denominator yields exactly 100.00, got {package['coverage_live_pct']}"
    )
    assert_same_instant(package["released_at"], "2026-08-15T00:00:00Z", "released_at")
    assert refresh_version(ctx["version"]["id"])["status"] == "PUBLISHED", (
        "the item's version must still reach PUBLISHED on an empty roster"
    )


def test_release_into_an_empty_jurisdiction_closes_at_full_coverage():
    """PRD §3.6: "The package's `roster_snapshot_size` is set to the number of
    assignments minted" ... "in both variants a denominator of zero yields exactly
    100.00 rather than an error or a null" ... "That condition can be satisfied the
    instant the package is released if zero assignments were minted, in which case
    the package transitions straight through to `CLOSED` with both coverage figures
    at 100.00."

    Design: Difficulty/boundary_precision_check/empty_roster_denominator_yields_full_coverage_and_immediate_close
    """
    from test_helpers import refresh_version, released_package_for, setup_approved_version

    ctx = setup_approved_version()

    package = released_package_for(
        [ctx["version"]["id"]], [ctx["jurisdiction"]["id"]], "2026-08-15T00:00:00Z"
    )

    assert package["roster_snapshot_size"] == 0, (
        f"no employees exist, so nothing is minted, got {package['roster_snapshot_size']}"
    )
    assert assignments_of(package["id"]) == []
    assert package["status"] == "CLOSED", (
        f"an empty roster closes the package immediately, got {package['status']}"
    )
    assert float(package["coverage_snapshot_pct"]) == 100.00
    assert float(package["coverage_live_pct"]) == 100.00
    assert_same_instant(package["released_at"], "2026-08-15T00:00:00Z", "released_at")

    reread = refresh_package(package["id"])
    assert float(reread["coverage_snapshot_pct"]) == 100.00
    assert float(reread["coverage_live_pct"]) == 100.00
    assert refresh_version(ctx["version"]["id"])["status"] == "PUBLISHED"


def test_successor_release_supersedes_prior_version_and_voids_its_open_assignment():
    """PRD §3.4: "Hop 1: that prior version moves `PUBLISHED → SUPERSEDED` and its
    `window_end_date` is set to the successor's `effective_date`, closing its window
    exactly where the successor's opens. Hop 2: because the version became
    `SUPERSEDED`, every assignment on it whose `ack_state` is `UNDELIVERED` or
    `PENDING` is set to `VOIDED`. Hop 3: because those assignments became `VOIDED`,
    each owning employee's `open_ack_count` is decremented by 1."

    Design: Difficulty/transitive_cascade/successor_release_supersedes_voids_and_moots_the_prior_generation
    """
    from test_helpers import (
        add_approved_version_to_document,
        refresh_document,
        refresh_employee,
        refresh_version,
        released_package_for,
    )

    ctx = setup_released_scenario(document={"max_ack_deadline_days": 5})
    v1, employee = ctx["version"], ctx["employee"]
    assert refresh_employee(employee["id"])["open_ack_count"] == 1

    v2 = add_approved_version_to_document(
        ctx["document"], ctx["jurisdiction"]["id"], ctx["reviewer"]["id"]
    )
    second = released_package_for(
        [v2["id"]], [ctx["jurisdiction"]["id"]], "2026-09-20T00:00:00Z"
    )

    retired = refresh_version(v1["id"])
    assert retired["status"] == "SUPERSEDED", (
        f"hop 1 must retire the prior published version, got {retired['status']}"
    )
    assert_same_instant(
        retired["window_end_date"], "2026-09-20T00:00:00Z", "window_end_date"
    )

    voided = refresh_assignment(ctx["assignment"]["id"])
    assert voided["ack_state"] == "VOIDED", (
        f"hop 2 must void the open assignment on the retired version, got "
        f"{voided['ack_state']}"
    )

    assert refresh_employee(employee["id"])["open_ack_count"] == 1, (
        "hop 3 decrements the counter for the voided row and the fresh mint adds one "
        "back, leaving exactly 1 open acknowledgment"
    )

    items = validate_success(
        api_client.list_release_items(
            make_admin_headers(), params={"release_package_id": second["id"], "limit": 100}
        )
    )
    assert len(items) == 1
    assert items[0]["supersedes_version_id"] == v1["id"], (
        "the successor item must record the version it retired, got "
        f"{items[0]['supersedes_version_id']}"
    )

    document = refresh_document(ctx["document"]["id"])
    assert document["current_published_version_id"] == v2["id"], (
        "the document must now point at the successor, got "
        f"{document['current_published_version_id']}"
    )
    assert document["latest_version_no"] == 2, (
        f"two minted versions means latest_version_no 2, got {document['latest_version_no']}"
    )


def test_supersede_cascade_moots_the_open_escalation_case_of_the_voided_assignment():
    """PRD §3.4: "Hop 4: because those assignments became `VOIDED`, every
    escalation case on them whose `status` is `OPEN`, `NOTIFIED` or `ESCALATED_HR`
    is closed as `CLOSED_MOOT` with `closed_at` stamped from the logical clock, the
    assignment's `escalation_state` becomes `MOOT`, and each such employee's
    `open_escalation_count` is decremented by 1."

    Design: Difficulty/transitive_cascade/successor_release_supersedes_voids_and_moots_the_prior_generation
    """
    from test_helpers import (
        add_approved_version_to_document,
        refresh_case,
        refresh_employee,
        refresh_version,
        released_package_for,
        setup_open_escalation_case,
    )

    ctx = setup_open_escalation_case(document={"max_ack_deadline_days": 5})
    v1, employee, case = ctx["version"], ctx["employee"], ctx["case"]
    assert case["status"] == "OPEN"
    assert refresh_assignment(ctx["assignment"]["id"])["days_overdue"] == 14, (
        "a due_date of 2026-08-20 read at 2026-09-03 is 14 whole days overdue"
    )
    assert refresh_employee(employee["id"])["open_escalation_count"] == 1

    v2 = add_approved_version_to_document(
        ctx["document"], ctx["jurisdiction"]["id"], ctx["reviewer"]["id"]
    )
    second = released_package_for(
        [v2["id"]], [ctx["jurisdiction"]["id"]], "2026-09-20T00:00:00Z"
    )

    assert refresh_version(v1["id"])["status"] == "SUPERSEDED"
    voided = refresh_assignment(ctx["assignment"]["id"])
    assert voided["ack_state"] == "VOIDED", (
        f"hop 2 must void the PENDING assignment, got {voided['ack_state']}"
    )
    assert voided["escalation_state"] == "MOOT", (
        "hop 4 moves the escalation dimension to MOOT rather than RESOLVED, got "
        f"{voided['escalation_state']}"
    )

    closed = refresh_case(case["id"])
    assert closed["status"] == "CLOSED_MOOT", (
        f"hop 4 must close the open case as moot, got {closed['status']}"
    )
    assert_same_instant(closed["closed_at"], "2026-09-20T00:00:00Z", "closed_at")

    subject = refresh_employee(employee["id"])
    assert subject["open_escalation_count"] == 0, (
        "hop 4 must decrement the subject's open_escalation_count, got "
        f"{subject['open_escalation_count']}"
    )
    assert subject["open_ack_count"] == 1, (
        "the voided row releases one open acknowledgment and the fresh mint adds one, "
        f"got {subject['open_ack_count']}"
    )
    assert second["roster_snapshot_size"] == 2, (
        "both in-scope employees are minted a fresh assignment, got "
        f"{second['roster_snapshot_size']}"
    )


def _pending_window_then_scheduled_successor(second_effective_date):
    """One employee holding a PENDING CODE_OF_CONDUCT assignment over the closed
    window 2026-08-15 .. 2026-08-20, plus a second same-category package already
    SCHEDULED for `second_effective_date`.  The clock sits at 2026-08-15."""
    from test_helpers import (
        add_approved_version_to_document,
        add_item,
        new_document,
        new_package,
        schedule_package,
    )

    ctx = setup_released_scenario(
        jurisdiction={"ack_window_buffer_days": 3},
        document={"max_ack_deadline_days": 5},
    )
    assert ctx["jurisdiction"]["ack_window_buffer_days"] == 3
    first = refresh_assignment(ctx["assignment"]["id"])
    assert first["ack_state"] == "PENDING"
    assert_same_instant(first["window_start_date"], "2026-08-15T00:00:00Z", "window_start_date")
    assert_same_instant(first["due_date"], "2026-08-20T00:00:00Z", "due_date")

    other_document = new_document(max_ack_deadline_days=5)
    successor = add_approved_version_to_document(
        other_document, ctx["jurisdiction"]["id"], ctx["reviewer"]["id"]
    )
    package = new_package([ctx["jurisdiction"]["id"]], second_effective_date)
    add_item(package["id"], successor["id"])
    ctx["second_package"] = schedule_package(package["id"])
    return ctx


def test_release_is_refused_when_the_ack_window_gap_is_below_the_buffer():
    """PRD §3.6: "Each such assignment occupies the closed window from its
    `window_start_date` through its `due_date`, and the candidate occupies its own
    closed window in the same way. The gap between two windows is measured from the
    earlier window's `due_date` to the later window's `window_start_date`, and it
    must be at least the employee's jurisdiction's `ack_window_buffer_days` whole
    days. A gap strictly smaller than that — including adjacency, meaning a gap of
    zero — is a conflict, and the release is refused with
    `ERR_ACK_WINDOW_BUFFER_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/employee_ack_window_closed_interval_with_mandatory_buffer_gap
    """
    from test_helpers import ApiErrorId, refresh_employee, set_clock, validate_error

    ctx = _pending_window_then_scheduled_successor("2026-08-22T00:00:00Z")
    package = ctx["second_package"]
    set_clock("2026-08-22T00:00:00Z")

    validate_error(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": package["version"]},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_ACK_WINDOW_BUFFER_CONFLICT,
    )

    blocked = refresh_package(package["id"])
    assert blocked["status"] == "SCHEDULED", (
        "a gap of 2 whole days is short of the 3-day buffer, so the package must stay "
        f"SCHEDULED, got {blocked['status']}"
    )
    assert blocked["released_at"] is None
    assert blocked["roster_snapshot_size"] == 0
    assert refresh_assignment(ctx["assignment"]["id"])["ack_state"] == "PENDING"
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 1, (
        "a refused release must leave the employee's open_ack_count at 1, got "
        f"{refresh_employee(ctx['employee']['id'])['open_ack_count']}"
    )


def test_release_succeeds_when_the_ack_window_gap_exactly_meets_the_buffer():
    """PRD §3.6: "The gap between two windows is measured from the earlier window's
    `due_date` to the later window's `window_start_date`, and it must be at least the
    employee's jurisdiction's `ack_window_buffer_days` whole days."  PRD §3.7: "Its
    `window_start_date` is the package's `effective_date`".

    Design: Difficulty/resource_temporal_overlap/employee_ack_window_closed_interval_with_mandatory_buffer_gap
    """
    from test_helpers import refresh_employee, set_clock, sole_assignment

    ctx = _pending_window_then_scheduled_successor("2026-08-23T00:00:00Z")
    package = ctx["second_package"]
    set_clock("2026-08-23T00:00:00Z")

    released = validate_success(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": package["version"]},
            make_admin_headers(),
        )
    )
    assert released["status"] == "RELEASED", (
        "a gap of exactly 3 whole days meets the buffer, got "
        f"{released['status']}"
    )
    assert released["roster_snapshot_size"] == 1, (
        f"the single in-scope employee is minted one row, got {released['roster_snapshot_size']}"
    )

    minted = sole_assignment(package["id"], ctx["employee"]["id"])
    assert_same_instant(minted["window_start_date"], "2026-08-23T00:00:00Z", "window_start_date")
    assert_same_instant(minted["due_date"], "2026-08-28T00:00:00Z", "due_date")
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 2, (
        "the employee now carries two open obligations, got "
        f"{refresh_employee(ctx['employee']['id'])['open_ack_count']}"
    )
