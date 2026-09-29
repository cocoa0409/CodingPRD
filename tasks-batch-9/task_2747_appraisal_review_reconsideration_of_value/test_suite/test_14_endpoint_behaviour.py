"""
Endpoint behaviour: what each shape of endpoint owes its caller.

An action endpoint is exercised twice over on the same appraiser to show that the
read-and-recompute action always spends a version even when it changes nothing, and then
refused when the action does not match the appraiser's standing. A computed read is driven
through each of its filter values and one page window. A cross-reference creation is given
two dangling references in turn to show which one is reported and that the guard token
survives the refusals. And a conditional action is asked for once too early and once at
exactly the moment it becomes available.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    DESK_REVIEWER_HEADERS,
    ApiErrorId,
    assert_instant,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_APPRAISER_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_AMC_ID = "00000000-0000-4000-8000-0000000000ff"


def _grid_row(street_number, street, price, distance, sale_date, **extra):
    row = {
        "street_address": "%d %s" % (street_number, street),
        "sale_price_cents": price,
        "gross_adjustment_cents": 390000 if street_number == 1 else 400000,
        "net_adjustment_cents": 390000 if street_number == 1 else 0,
        "distance_miles": distance,
        "sale_date": sale_date,
    }
    row.update(extra)
    return row


def test_monitoring_an_active_appraiser_recomputes_both_scores_and_moves_nothing(api):
    """The read-and-recompute action reports a clean panel record.

    The appraiser has authored two live reports and has had no value moved against either,
    so the rolling revision rate is zero and both score variants sit at the perfect opening
    figure. That score is nowhere near the probation band, so the standing cascade has
    nothing to do and the probation stamp stays empty.

    PRD: "`revision_rate_bps` is zero when the appraisal count is zero — a brand-new
    appraiser is not penalised for having no history — and otherwise is 10000 multiplied by
    the revision count, divided by the appraisal count, rounded half up. The score then
    starts at 10000 and subtracts three penalties: 0.60 multiplied by `revision_rate_bps`
    and rounded half up, plus 1200 for each entry in `substantiated_bias_count`, plus 400
    for each entry in `sla_miss_count`. The result is clamped into the range 0 through 10000
    inclusive."

    PRD: "The panel dimension opens at `ACTIVE` and reacts automatically to each recompute.
    A rolling score below 7000 but at or above 5500 moves the appraiser `ACTIVE →
    PROBATION`, stamping `probation_started_at` from the logical clock."

    Design: Corner/endpoints/action_endpoint_panel_review_monitor_recomputes_without_moving_status
    """
    env = _appraiser_with_two_reports(api)

    reviewed = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR", note="Quarterly monitoring."
    )

    assert reviewed["total_appraisal_count"] == 2
    assert reviewed["revision_rate_bps"] == 0
    assert reviewed["performance_score_bps"] == 10000
    assert reviewed["lifetime_performance_score_bps"] == 10000
    assert reviewed["panel_status"] == "ACTIVE"
    assert reviewed["probation_started_at"] is None


def test_a_second_monitor_over_the_same_data_still_burns_a_version(api):
    """Every panel review costs a version, whether or not anything changed.

    The action is repeated with nothing at all having happened in between. The tallies and
    both scores come back identical, and the appraiser's version has nonetheless advanced by
    exactly one.

    PRD: "Every panel review increments the appraiser's `version` by 1, and a mismatched
    version is rejected before anything else happens. A `MONITOR` action is the
    read-and-recompute action, available in `ACTIVE`, `PROBATION`, and `SUSPENDED` as the
    self-transitions `ACTIVE → ACTIVE`, `PROBATION → PROBATION`, and `SUSPENDED →
    SUSPENDED`; it recomputes both score variants from the current logical clock and is the
    only way to observe them side by side."

    Design: Corner/endpoints/action_endpoint_panel_review_monitor_recomputes_without_moving_status
    """
    env = _appraiser_with_two_reports(api)
    first = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR", note="Quarterly monitoring."
    )
    second = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR", note="Second look, same data."
    )

    assert second["version"] == first["version"] + 1
    assert second["total_appraisal_count"] == first["total_appraisal_count"]
    assert second["revision_rate_bps"] == first["revision_rate_bps"]
    assert second["performance_score_bps"] == first["performance_score_bps"]
    assert (
        second["lifetime_performance_score_bps"]
        == first["lifetime_performance_score_bps"]
    )
    assert second["panel_status"] == "ACTIVE"


def test_removal_is_refused_while_the_appraiser_is_still_active(api):
    """Removal is reachable only from suspension, never from a clean standing.

    The appraiser is active with a perfect score, which is neither of the two things removal
    requires. The action is refused, and nothing about the standing or the panel enrolment
    is disturbed.

    PRD: "A `REMOVE` action is available only from suspension, requires a rolling score
    below 4000 and a `removal_reason`, and moves the appraiser `SUSPENDED → REMOVED`; it
    records the reason, supersedes every `ACTIVE` panel membership held by that appraiser,
    and moves every `ASSIGNED` or `REASSIGNMENT_REQUIRED` order for that appraiser to
    `REASSIGNMENT_REQUIRED`. `REMOVED` is terminal. Any action that does not match one of
    those edges from the appraiser's present standing is refused with
    `ERR_PANEL_ACTION_NOT_PERMITTED` (HTTP 422) — including a reinstatement of an
    already-active appraiser, a removal from probation, and any action at all on a removed
    appraiser."

    Design: Corner/endpoints/action_endpoint_panel_review_monitor_recomputes_without_moving_status
    """
    env = _appraiser_with_two_reports(api)
    monitored = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR", note="Quarterly monitoring."
    )

    response = api.panel_review(
        env["appraiser"]["id"],
        f.panel_review_payload(
            "REMOVE",
            monitored["version"],
            removal_reason="Desk lost confidence.",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PANEL_ACTION_NOT_PERMITTED, 422)

    after = fx.read_appraiser(api, env["appraiser"]["id"])
    assert after["panel_status"] == "ACTIVE"
    assert after["removal_reason"] is None
    assert after["panel_membership_count"] == 1

    memberships, _ = validate_paginated(
        api.list_panel_memberships(
            CHIEF_APPRAISER_HEADERS, {"appraiser_id": env["appraiser"]["id"]}
        )
    )
    assert [row["status"] for row in memberships] == ["ACTIVE"]


def _appraiser_with_two_reports(api):
    amc = fx.create_amc(api, name="Monitor AMC")
    appraiser = fx.create_appraiser(
        api, full_name="Alice Author", license_number="CA-AL-C401", license_state="CA",
    )
    fx.enroll_on_panel(api, appraiser["id"], amc["id"])
    first_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C401A", borrower_display_name="Kim Borrower",
    )
    second_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C401B", borrower_display_name="Lee Borrower",
    )
    return {
        "amc": amc,
        "appraiser": appraiser,
        "appraisals": [
            fx.deliver_appraisal(api, first_loan["id"], appraiser["id"], amc["id"]),
            fx.deliver_appraisal(api, second_loan["id"], appraiser["id"], amc["id"]),
        ],
    }


TWO_ROW_GRID = [
    _grid_row(1, "Alder Street", 39000000, 1.0, "2026-05-01T00:00:00Z"),
    _grid_row(2, "Alder Street", 40000000, 1.5, "2026-06-01T00:00:00Z"),
]


def _graded_two_row_report(api):
    return fx.graded_report(
        api,
        amc={"name": "Filter Read AMC"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-C402",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-C402", "borrower_display_name": "Moe Borrower"},
        comparables=[dict(row) for row in TWO_ROW_GRID],
    )


def test_the_check_listing_filtered_by_outcome_reports_only_that_outcome(api):
    """Each outcome filter returns exactly the rows carrying that outcome.

    The grid is one comparable short of the closed-sale target, so the battery comes back
    with a single failure and no warnings. Filtering by failure returns that one row, the
    count check at its fixed second position, with the closed count as its observed metric.
    Filtering by pass returns the other seven, including the completeness row that scored
    above the passing floor. Filtering by warning returns nothing at all, and each of the
    three counts matches the tally persisted on the appraisal.

    PRD: "The fixed sequence is `CHK_COMPLETENESS` at position 1, `CHK_COMP_COUNT` at 2,
    `CHK_COMP_DISTANCE` at 3, `CHK_COMP_AGE` at 4, `CHK_GROSS_ADJUSTMENT` at 5,
    `CHK_NET_ADJUSTMENT` at 6, `CHK_VALUE_RECONCILIATION` at 7, and `CHK_FORM_TYPE` at 8.
    The listing endpoint returns them in that order and can be filtered by `outcome`."

    PRD: "**Position 2, closed-comparable count.** The observed value is
    `closed_comp_count`. The outcome is `FAIL` when fewer than three in-grid comparables are
    in `CLOSED` sale status, and `PASS` otherwise. This check never yields `WARN`."

    Design: Corner/endpoints/computed_read_rule_check_listing_filters_by_outcome
    """
    env = _graded_two_row_report(api)
    appraisal_id = env["appraisal"]["id"]
    appraisal = fx.read_appraisal(api, appraisal_id)
    assert appraisal["rule_check_fail_count"] == 1
    assert appraisal["rule_check_warn_count"] == 0

    failing, fail_meta = validate_paginated(
        api.list_rule_checks(appraisal_id, DESK_REVIEWER_HEADERS, {"outcome": "FAIL"})
    )
    assert fail_meta["total_count"] == 1
    assert fail_meta["has_more"] is False
    assert failing[0]["check_code"] == "CHK_COMP_COUNT"
    assert failing[0]["sequence_no"] == 2
    assert failing[0]["observed_value"] == "2"

    passing, pass_meta = validate_paginated(
        api.list_rule_checks(appraisal_id, DESK_REVIEWER_HEADERS, {"outcome": "PASS"})
    )
    assert pass_meta["total_count"] == 7
    completeness = [
        row for row in passing if row["check_code"] == "CHK_COMPLETENESS"
    ]
    assert len(completeness) == 1
    assert completeness[0]["observed_value"] == "9000"

    warning, warn_meta = validate_paginated(
        api.list_rule_checks(appraisal_id, DESK_REVIEWER_HEADERS, {"outcome": "WARN"})
    )
    assert warning == []
    assert warn_meta["total_count"] == 0
    assert warn_meta["has_more"] is False


def test_a_page_window_past_the_sixth_check_returns_the_last_two_in_order(api):
    """The page window narrows the rows returned without narrowing the count.

    A window of three rows starting after the sixth leaves only two rows to return, and they
    come back in the battery's fixed order. The total is the whole battery rather than the
    page, and nothing remains beyond the window.

    PRD: "For list responses the `meta` object carries `limit` (the effective page size
    actually applied), `offset` (the effective offset actually applied), `total_count` (the
    number of rows matching the filters before the page window is applied), and `has_more`
    (true when rows remain beyond the current window)."

    PRD: "The fixed sequence is `CHK_COMPLETENESS` at position 1, `CHK_COMP_COUNT` at 2,
    `CHK_COMP_DISTANCE` at 3, `CHK_COMP_AGE` at 4, `CHK_GROSS_ADJUSTMENT` at 5,
    `CHK_NET_ADJUSTMENT` at 6, `CHK_VALUE_RECONCILIATION` at 7, and `CHK_FORM_TYPE` at 8.
    The listing endpoint returns them in that order and can be filtered by `outcome`."

    Design: Corner/endpoints/computed_read_rule_check_listing_filters_by_outcome
    """
    env = _graded_two_row_report(api)

    rows, meta = validate_paginated(
        api.list_rule_checks(
            env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 3, "offset": 6}
        )
    )

    assert meta["total_count"] == 8
    assert meta["limit"] == 3
    assert meta["offset"] == 6
    assert meta["has_more"] is False
    assert [row["sequence_no"] for row in rows] == [7, 8]
    assert [row["check_code"] for row in rows] == [
        "CHK_VALUE_RECONCILIATION",
        "CHK_FORM_TYPE",
    ]


def _link_parties(api):
    amc = fx.create_amc(api, name="Link AMC")
    appraiser = fx.create_appraiser(
        api, full_name="Alice Author", license_number="CA-AL-C403", license_state="CA",
    )
    return amc, appraiser


def test_enrolment_reports_the_first_declared_dangling_reference_and_spends_nothing(api):
    """The earlier-declared reference is the one reported, and the token survives.

    Enrolment is offered two references that resolve to nothing at once, and the appraiser
    position — declared first — is the one named in the refusal. Correcting only that
    position moves the complaint to the company. Neither refusal spends the appraiser's
    guard token, so the very same version is still current afterwards.

    PRD: "Panel enrolment resolves `appraiser_id` then `amc_id`."

    PRD: "Every foreign key in the body references an existing row, checked in declaration
    order — otherwise that type's own not-found code (404)."

    Design: Corner/endpoints/cross_reference_link_panel_membership_requires_both_parties
    """
    _, appraiser = _link_parties(api)

    both_unknown = api.create_panel_membership(
        f.panel_membership_payload(
            UNKNOWN_APPRAISER_ID, UNKNOWN_AMC_ID, appraiser["version"]
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(both_unknown, ApiErrorId.ERR_APPRAISER_NOT_FOUND, 404)

    amc_unknown = api.create_panel_membership(
        f.panel_membership_payload(
            appraiser["id"], UNKNOWN_AMC_ID, appraiser["version"]
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(amc_unknown, ApiErrorId.ERR_AMC_NOT_FOUND, 404)

    after = fx.read_appraiser(api, appraiser["id"])
    assert after["version"] == appraiser["version"]
    assert after["panel_membership_count"] == 0


def test_enrolment_with_both_parties_present_links_them_and_spends_the_token(api):
    """With both references resolving, the membership is born active on the tier asked for.

    The same guard token that survived the two refusals is spent here. The membership records
    both parties and its coverage state, the appraiser's enrolment tally moves to one, and the
    appraiser's version advances by exactly one.

    PRD: "Enrolling one names the `appraiser_id`, the `amc_id`, a `coverage_state` given as
    exactly two uppercase letters, and a `tier` of `GENERAL`, `COMPLEX`, or
    `REVIEW_SPECIALIST` describing the assignment tier the appraiser is approved for on that
    panel. A membership is born with `status` `ACTIVE`."

    PRD: "Enrolment is one of the three operations guarded by the stale-read token of §2.6,
    so `expected_appraiser_version` must carry the appraiser's current `version`; a
    successful enrolment increments that appraiser's `version` by 1 and increments the
    appraiser's `panel_membership_count`."

    Design: Corner/endpoints/cross_reference_link_panel_membership_requires_both_parties
    """
    amc, appraiser = _link_parties(api)

    membership = validate_success(
        api.create_panel_membership(
            f.panel_membership_payload(
                appraiser["id"], amc["id"], appraiser["version"]
            ),
            CHIEF_APPRAISER_HEADERS,
        ),
        201,
    )

    assert membership["appraiser_id"] == appraiser["id"]
    assert membership["amc_id"] == amc["id"]
    assert membership["coverage_state"] == "CA"
    assert membership["tier"] == "GENERAL"
    assert membership["status"] == "ACTIVE"

    after = fx.read_appraiser(api, appraiser["id"])
    assert after["panel_membership_count"] == 1
    assert after["version"] == appraiser["version"] + 1


def _open_dispute(api):
    env = fx.graded_report(
        api,
        amc={"name": "Deadline AMC"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-C404",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-C404", "borrower_display_name": "Ned Borrower"},
        comparables=[dict(TWO_ROW_GRID[1])],
    )
    env["dispute"] = fx.file_dispute(
        api,
        env["appraisal"]["id"],
        env["amc"]["id"],
        env["appraiser"]["id"],
        dispute_basis="ADJUSTMENT_SUPPORT",
        slot_start="2026-08-02T09:00:00Z",
        slot_end="2026-08-02T12:00:00Z",
    )
    return env


def test_resolving_by_default_before_the_deadline_is_refused(api):
    """The SLA remedy is not available while the company still has time to answer.

    The dispute's deadline is seventy-two hours after it was filed, and the clock has not
    moved since. Asking for the default resolution now is refused, and the dispute is left
    open with no resolution, still counted against the company and with no breach recorded.

    PRD: "Resolving by default is the SLA remedy and is available only from `OPEN`, and only
    once the logical clock has reached or passed the dispute's `response_deadline_at`; an
    attempt before the deadline is refused with `ERR_DISPUTE_DEADLINE_NOT_REACHED` (HTTP
    422)."

    Design: Corner/endpoints/conditional_action_dispute_by_default_resolution_requires_the_deadline
    """
    env = _open_dispute(api)
    assert_instant(
        env["dispute"]["response_deadline_at"],
        "2026-08-04T00:00:00Z",
        "response_deadline_at",
    )

    response = api.resolve_dispute_case(
        env["dispute"]["id"],
        f.resolve_dispute_payload(
            "BY_DEFAULT", resolution_note="No response received."
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_DEADLINE_NOT_REACHED, 422)

    case = fx.read_dispute_case(api, env["dispute"]["id"])
    assert case["status"] == "OPEN"
    assert case["resolution"] is None
    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["open_dispute_count"] == 1
    assert amc["sla_breach_count"] == 0


def test_resolving_by_default_at_exactly_the_deadline_records_one_breach(api):
    """Reaching the deadline is enough; the remedy does not wait for it to pass.

    The clock is moved to precisely the deadline instant and the same call is repeated. It
    lands in the terminal default state, charges the company one SLA breach and releases the
    open dispute count. One breach is short of the probation trigger, so the company's
    standing is unchanged.

    PRD: "Resolving by default is the SLA remedy and is available only from `OPEN`, and only
    once the logical clock has reached or passed the dispute's `response_deadline_at`; an
    attempt before the deadline is refused with `ERR_DISPUTE_DEADLINE_NOT_REACHED` (HTTP
    422). It is the edge `OPEN → RESOLVED_BY_DEFAULT`, and it increments the company's
    `sla_breach_count`, re-evaluates the company panel cascade, and decrements the company's
    `open_dispute_count`."

    PRD: "When the count reaches 2 while still below 4, the company moves `ACTIVE →
    PROBATION`; probation changes nothing operationally — existing orders are untouched and
    new report intake is still permitted, it is purely a recorded warning."

    Design: Corner/endpoints/conditional_action_dispute_by_default_resolution_requires_the_deadline
    """
    env = _open_dispute(api)
    fx.set_clock(api, "2026-08-04T00:00:00Z")

    case = validate_success(
        api.resolve_dispute_case(
            env["dispute"]["id"],
            f.resolve_dispute_payload(
                "BY_DEFAULT",
                resolution_note="Deadline passed with no AMC response.",
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )

    assert case["status"] == "RESOLVED_BY_DEFAULT"
    assert case["resolution"] == "BY_DEFAULT"
    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["sla_breach_count"] == 1
    assert amc["open_dispute_count"] == 0
    assert amc["panel_status"] == "ACTIVE"


def test_a_default_resolution_moves_no_value_and_writes_no_ledger_row(api):
    """The default resolution is a remedy against the company, not a value movement.

    Nothing about the report's value opinion is disturbed by resolving a dispute this way:
    the value of record is still the figure the receipt battery seeded, and the append-only
    ledger — which is written on every movement of a value of record — has no row at all.

    PRD: "Every movement of a value of record, whichever channel produced it, writes one row
    to an append-only revision ledger hanging off the appraisal."

    PRD: "Each accepted run increments the appraisal's `version` by 1, and the very first run
    on an appraisal also seeds `current_value_cents` from `reported_value_cents`,
    establishing the baseline that every later value revision moves off."

    Design: Corner/endpoints/conditional_action_dispute_by_default_resolution_requires_the_deadline
    """
    env = _open_dispute(api)
    fx.set_clock(api, "2026-08-04T00:00:00Z")
    fx.resolve_dispute(
        api,
        env["dispute"]["id"],
        "BY_DEFAULT",
        resolution_note="Deadline passed with no AMC response.",
    )

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 40000000

    revisions, meta = validate_paginated(
        api.list_value_revisions(env["appraisal"]["id"], CHIEF_APPRAISER_HEADERS)
    )
    assert revisions == []
    assert meta["total_count"] == 0
