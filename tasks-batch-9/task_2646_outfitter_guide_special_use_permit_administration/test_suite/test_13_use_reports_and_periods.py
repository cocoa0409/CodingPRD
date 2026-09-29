"""Filing actual use: five rules in priority order, half-open periods, the cap.

Covers the five substantive filing rules and the order they are revealed in, the
floored fifteen-percent deduction cap, half-open period adjacency against closed
permit terms, the cumulative season day cap at acceptance, and the two disjoint
state gates that share one error id.
"""
from test_helpers import (
    ApiErrorId,
    accept_use_report,
    authorize_guide,
    create_qualified_guide,
    current_permit_version,
    file_bond,
    file_insurance_certificate,
    list_noncompliance_actions,
    list_use_reports,
    read_permit,
    read_use_report,
    setup_issued_permit,
    sole_fee_assessment,
    trip_use_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]


def _reporting_permit(clock):
    """An ISSUED Alpine permit for 200 service days on BRW-01, with one
    QUALIFIED LEAD/WFR guide authorized so eight client slots stand open."""
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200}, clock=clock
    )
    guide = create_qualified_guide(context["outfitter"]["id"])
    authorization = authorize_guide(
        context["permit"]["id"], guide["id"], context["outfitter"]["id"]
    )
    assert authorization["authorized_client_capacity"] == 8
    permit = read_permit(context["permit"]["id"])
    assert permit["authorized_client_capacity_total"] == 8
    assert permit["authorized_service_days"] == 200
    assert permit["service_days_used_ytd"] == 0
    context["guide"] = guide
    return context


def _file(context, **overrides):
    return api_client.create_trip_use_report(
        context["permit"]["id"],
        trip_use_report_payload(**overrides),
        context["holder_headers"],
    )


def test_the_reporting_window_is_settled_before_any_money_on_the_report():
    """PRD §3.7: "The reported interval must lie inside the area's season for the report's season
    year, bounded inclusively by `season_open_date` and `season_close_date`, and also inside the
    permit's term bounded inclusively by `term_start_date` and `term_end_date`; outside either it
    is `ERR_OUTSIDE_SEASON_WINDOW`."
    PRD §3.7: "And deductions are capped: `allowable_deductions_cents` must not exceed 15 percent
    of `gross_revenue_cents`, computed as the floor of that product, else
    `ERR_DEDUCTIONS_EXCEED_CAP`."
    PRD §3.7: "Five substantive rules police a filing, in priority order."
    PRD §3.7: "`adjusted_gross_revenue_cents` is computed at filing as `gross_revenue_cents`
    minus `allowable_deductions_cents`, while `applied_rate_bp` and `fee_component_cents` stay
    null until acceptance."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/priority_pair_validation_conflict/outside_season_window_beats_deduction_cap
    """
    context = _reporting_permit("2027-09-01T00:00:00Z")

    validate_error(
        _file(
            context,
            period_start_date="2027-04-01",
            period_end_date="2027-05-01",
            service_days_used=20,
            gross_revenue_cents=1_000_000,
            allowable_deductions_cents=500_000,
        ),
        ApiErrorId.ERR_OUTSIDE_SEASON_WINDOW,
    )
    rows, meta = list_use_reports(params={"permit_id": context["permit"]["id"]})
    assert meta["total_count"] == 0 and rows == [], (
        "the refused filing left no row behind"
    )

    validate_error(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-15",
            service_days_used=20,
            gross_revenue_cents=1_000_000,
            allowable_deductions_cents=500_000,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )

    accepted = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-15",
            service_days_used=20,
            gross_revenue_cents=1_000_000,
            allowable_deductions_cents=150_000,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["adjusted_gross_revenue_cents"] == 850_000
    assert accepted["applied_rate_bp"] is None
    assert accepted["fee_component_cents"] is None
    assert accepted["season_year"] == 2027


def test_the_five_filing_rules_are_revealed_one_at_a_time_in_their_pinned_order():
    """PRD §3.7: "Five substantive rules police a filing, in priority order. `client_count` must
    not exceed the permit's `authorized_client_capacity_total` — the client-to-guide ratio must
    not merely have been satisfiable, it must have been satisfied by the trips actually run —
    else `ERR_CLIENT_GUIDE_RATIO_UNMET`."
    PRD §3.7: "The reported interval must lie inside the area's season for the report's season
    year, bounded inclusively by `season_open_date` and `season_close_date`, and also inside the
    permit's term bounded inclusively by `term_start_date` and `term_end_date`; outside either it
    is `ERR_OUTSIDE_SEASON_WINDOW`."
    PRD §3.7: "The period must be over: `period_end_date` must be on or before the current
    logical date, else `ERR_PERIOD_NOT_ELAPSED`."
    PRD §3.7: "The interval must not intersect the interval of any other report on the same
    permit whose `status` is `SUBMITTED` or `ACCEPTED` — `SUPERSEDED` rows are ignored, which is
    what lets an amendment chain reuse a period — else `ERR_REPORTING_PERIOD_OVERLAP`."
    PRD §3.7: "And deductions are capped: `allowable_deductions_cents` must not exceed 15 percent
    of `gross_revenue_cents`, computed as the floor of that product, else
    `ERR_DEDUCTIONS_EXCEED_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/outside_season_window_beats_deduction_cap
    """
    context = _reporting_permit("2027-09-01T00:00:00Z")
    incumbent = validate_success(
        _file(
            context,
            period_start_date="2027-06-01",
            period_end_date="2027-07-01",
            service_days_used=20,
            gross_revenue_cents=500_000,
        ),
        201,
    )
    assert incumbent["status"] == "SUBMITTED"

    money = {"gross_revenue_cents": 1_000_000, "allowable_deductions_cents": 500_000}

    validate_error(
        _file(
            context,
            period_start_date="2027-04-01",
            period_end_date="2027-05-01",
            client_count=9,
            **money,
        ),
        ApiErrorId.ERR_CLIENT_GUIDE_RATIO_UNMET,
    )
    validate_error(
        _file(
            context,
            period_start_date="2027-04-01",
            period_end_date="2027-05-01",
            client_count=8,
            **money,
        ),
        ApiErrorId.ERR_OUTSIDE_SEASON_WINDOW,
    )
    validate_error(
        _file(
            context,
            period_start_date="2027-09-15",
            period_end_date="2027-09-25",
            client_count=8,
            **money,
        ),
        ApiErrorId.ERR_PERIOD_NOT_ELAPSED,
    )
    validate_error(
        _file(
            context,
            period_start_date="2027-06-15",
            period_end_date="2027-06-20",
            client_count=8,
            **money,
        ),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP,
    )
    validate_error(
        _file(
            context,
            period_start_date="2027-07-01",
            period_end_date="2027-07-10",
            client_count=8,
            **money,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )

    clean = validate_success(
        _file(
            context,
            period_start_date="2027-07-01",
            period_end_date="2027-07-10",
            client_count=8,
            gross_revenue_cents=1_000_000,
            allowable_deductions_cents=150_000,
        ),
        201,
    )
    assert clean["adjusted_gross_revenue_cents"] == 850_000

    rows, meta = list_use_reports(params={"permit_id": context["permit"]["id"]})
    assert meta["total_count"] == 2, "five refusals wrote nothing"
    assert [row["id"] for row in rows] == [incumbent["id"], clean["id"]], (
        "reports list by period_start_date ascending"
    )


def test_the_deduction_cap_is_floored_and_the_comparison_admits_equality():
    """PRD §3.7: "And deductions are capped: `allowable_deductions_cents` must not exceed 15
    percent of `gross_revenue_cents`, computed as the floor of that product, else
    `ERR_DEDUCTIONS_EXCEED_CAP`."
    PRD §3.7: "`adjusted_gross_revenue_cents` is computed at filing as `gross_revenue_cents`
    minus `allowable_deductions_cents`, while `applied_rate_bp` and `fee_component_cents` stay
    null until acceptance."
    PRD §3.7: "supplying `period_start_date`, `period_end_date`, `service_days_used`,
    `client_count`, `gross_revenue_cents` and optionally `allowable_deductions_cents`, which
    defaults to 0."

    Design: Difficulty/boundary_precision_check/deduction_cap_floor_boundary
    """
    context = _reporting_permit("2027-09-20T00:00:00Z")
    permit_id = context["permit"]["id"]

    validate_error(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-14",
            gross_revenue_cents=1_000_001,
            allowable_deductions_cents=150_001,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )
    _rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 0

    at_the_cap = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-14",
            gross_revenue_cents=1_000_001,
            allowable_deductions_cents=150_000,
        ),
        201,
    )
    assert at_the_cap["adjusted_gross_revenue_cents"] == 850_001, (
        "floor(1000001 * 0.15) is 150000, and the comparison refuses only what exceeds it"
    )

    lower_gross = validate_success(
        _file(
            context,
            period_start_date="2027-06-14",
            period_end_date="2027-07-14",
            gross_revenue_cents=1_000_000,
            allowable_deductions_cents=150_000,
        ),
        201,
    )
    assert lower_gross["adjusted_gross_revenue_cents"] == 850_000, (
        "the cap tracks gross revenue rather than being a fixed amount"
    )

    bare = trip_use_report_payload(
        period_start_date="2027-07-14",
        period_end_date="2027-08-14",
        gross_revenue_cents=1_000_001,
    )
    del bare["allowable_deductions_cents"]
    defaulted = validate_success(
        api_client.create_trip_use_report(permit_id, bare, context["holder_headers"]), 201
    )
    assert defaulted["allowable_deductions_cents"] == 0
    assert defaulted["adjusted_gross_revenue_cents"] == 1_000_001


def test_the_cap_is_floored_at_every_scale_including_a_sub_cent_remainder():
    """PRD §3.7: "And deductions are capped: `allowable_deductions_cents` must not exceed 15
    percent of `gross_revenue_cents`, computed as the floor of that product, else
    `ERR_DEDUCTIONS_EXCEED_CAP`."
    PRD §3.7: "`adjusted_gross_revenue_cents` is computed at filing as `gross_revenue_cents`
    minus `allowable_deductions_cents`, while `applied_rate_bp` and `fee_component_cents` stay
    null until acceptance."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/boundary_precision_check/deduction_cap_floor_boundary
    """
    context = _reporting_permit("2027-09-20T00:00:00Z")
    permit_id = context["permit"]["id"]

    validate_error(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-05-20",
            service_days_used=5,
            gross_revenue_cents=6,
            allowable_deductions_cents=1,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )
    nothing_deductible = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-05-20",
            service_days_used=5,
            gross_revenue_cents=6,
            allowable_deductions_cents=0,
        ),
        201,
    )
    assert nothing_deductible["adjusted_gross_revenue_cents"] == 6, (
        "floor(6 * 0.15) is 0, so not a cent may be deducted"
    )

    validate_error(
        _file(
            context,
            period_start_date="2027-05-20",
            period_end_date="2027-05-25",
            service_days_used=5,
            gross_revenue_cents=7,
            allowable_deductions_cents=2,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )
    one_cent = validate_success(
        _file(
            context,
            period_start_date="2027-05-20",
            period_end_date="2027-05-25",
            service_days_used=5,
            gross_revenue_cents=7,
            allowable_deductions_cents=1,
        ),
        201,
    )
    assert one_cent["adjusted_gross_revenue_cents"] == 6, (
        "floor(7 * 0.15) is floor(1.05), so exactly one cent is deductible"
    )

    validate_error(
        _file(
            context,
            period_start_date="2027-05-25",
            period_end_date="2027-05-30",
            service_days_used=5,
            gross_revenue_cents=3_333_333,
            allowable_deductions_cents=500_000,
        ),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
    )
    at_scale = validate_success(
        _file(
            context,
            period_start_date="2027-05-25",
            period_end_date="2027-05-30",
            service_days_used=5,
            gross_revenue_cents=3_333_333,
            allowable_deductions_cents=499_999,
        ),
        201,
    )
    assert at_scale["adjusted_gross_revenue_cents"] == 2_833_334, (
        "floor(3333333 * 0.15) is floor(499999.95), so the last cent is not deductible"
    )

    rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 3, "three refusals wrote nothing"
    assert [row["adjusted_gross_revenue_cents"] for row in rows] == [6, 6, 2_833_334]


def test_periods_that_share_an_endpoint_stand_while_one_shared_day_falls():
    """PRD §3.7: "The reporting period is **half-open** — it includes `period_start_date` and
    excludes `period_end_date` — so two periods that share an endpoint, where one report's
    `period_end_date` equals the next report's `period_start_date`, do not overlap and are both
    accepted."
    PRD §3.7: "The interval must not intersect the interval of any other report on the same
    permit whose `status` is `SUBMITTED` or `ACCEPTED` — `SUPERSEDED` rows are ignored, which is
    what lets an amendment chain reuse a period — else `ERR_REPORTING_PERIOD_OVERLAP`."
    PRD §3.7: "Acceptance moves the report `SUBMITTED → ACCEPTED`, stamps `accepted_at`, stamps
    `applied_rate_bp` and `fee_component_cents`, adds `service_days_used` into the permit's
    `service_days_used_ytd`"

    Design: Difficulty/resource_temporal_overlap/use_report_half_open_period_adjacency
    """
    context = _reporting_permit("2027-09-20T00:00:00Z")
    permit_id = context["permit"]["id"]

    first = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-15",
            service_days_used=20,
            gross_revenue_cents=500_000,
        ),
        201,
    )
    second = validate_success(
        _file(
            context,
            period_start_date="2027-06-15",
            period_end_date="2027-07-15",
            service_days_used=20,
            gross_revenue_cents=500_000,
        ),
        201,
    )
    assert second["status"] == "SUBMITTED", (
        "a period starting exactly on the previous period's excluded end does not intersect it"
    )

    validate_error(
        _file(
            context,
            period_start_date="2027-06-14",
            period_end_date="2027-06-20",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP,
    )
    validate_error(
        _file(
            context,
            period_start_date="2027-07-14",
            period_end_date="2027-07-20",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP,
    )

    assert read_use_report(first["id"])["status"] == "SUBMITTED"
    assert read_use_report(second["id"])["status"] == "SUBMITTED", (
        "SUBMITTED rows contend for the timeline, not only accepted ones"
    )

    third = validate_success(
        _file(
            context,
            period_start_date="2027-07-15",
            period_end_date="2027-07-20",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        201,
    )
    assert third["status"] == "SUBMITTED"

    accepted = accept_use_report(first["id"])
    assert accepted["status"] == "ACCEPTED"
    assert read_permit(permit_id)["service_days_used_ytd"] == 20

    validate_error(
        _file(
            context,
            period_start_date="2027-06-14",
            period_end_date="2027-06-20",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP,
    )

    rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]


def test_an_amendment_reuses_the_period_so_the_slot_never_frees_up():
    """PRD §3.7: "The interval must not intersect the interval of any other report on the same
    permit whose `status` is `SUBMITTED` or `ACCEPTED` — `SUPERSEDED` rows are ignored, which is
    what lets an amendment chain reuse a period — else `ERR_REPORTING_PERIOD_OVERLAP`."
    PRD §3.7: "The original row is never edited: it moves `ACCEPTED → SUPERSEDED`, which is
    terminal, and a **new** report row is created directly in `ACCEPTED` carrying
    `supersedes_report_id` pointing at the original, the same `period_start_date` and
    `period_end_date`, and the amended figures — so both the original and the corrected numbers
    survive in the audit trail."
    PRD §3.7: "The permit's `service_days_used_ytd` is recomputed from the accepted set rather
    than adjusted"
    PRD §3.7: "The reporting period is **half-open** — it includes `period_start_date` and
    excludes `period_end_date` — so two periods that share an endpoint, where one report's
    `period_end_date` equals the next report's `period_start_date`, do not overlap and are both
    accepted."

    Design: Difficulty/resource_temporal_overlap/use_report_half_open_period_adjacency
    """
    context = _reporting_permit("2027-09-20T00:00:00Z")
    permit_id = context["permit"]["id"]

    original = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-15",
            service_days_used=20,
            gross_revenue_cents=2_000_000,
        ),
        201,
    )
    accept_use_report(original["id"])

    replacement = validate_success(
        api_client.amend_trip_use_report(
            original["id"],
            {
                "expected_permit_version": current_permit_version(permit_id),
                "service_days_used": 25,
                "client_count": 8,
                "gross_revenue_cents": 3_000_000,
                "allowable_deductions_cents": 0,
            },
            context["holder_headers"],
        ),
        201,
    )
    assert replacement["status"] == "ACCEPTED"
    assert replacement["supersedes_report_id"] == original["id"]
    assert replacement["period_start_date"].startswith("2027-05-15")
    assert replacement["period_end_date"].startswith("2027-06-15")
    assert read_use_report(original["id"])["status"] == "SUPERSEDED"

    validate_error(
        _file(
            context,
            period_start_date="2027-05-20",
            period_end_date="2027-05-25",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP,
    )

    abutting = validate_success(
        _file(
            context,
            period_start_date="2027-06-15",
            period_end_date="2027-06-20",
            service_days_used=5,
            gross_revenue_cents=100_000,
        ),
        201,
    )
    assert abutting["status"] == "SUBMITTED"

    superseded, superseded_meta = list_use_reports(
        params={"permit_id": permit_id, "status": "SUPERSEDED"}
    )
    assert superseded_meta["total_count"] == 1
    assert superseded[0]["id"] == original["id"]
    assert superseded[0]["service_days_used"] == 20, (
        "the superseded row keeps the original figures as the audit record"
    )

    assert read_permit(permit_id)["service_days_used_ytd"] == 25, (
        "the total is re-summed over the accepted set, so the superseded row drops out"
    )


def test_the_season_day_cap_sums_the_accepted_set_and_admits_equality():
    """PRD §3.7: "Acceptance is the `PermitSpecialist`'s exclusive act and the entry point for
    money. The report must be `SUBMITTED`, else `ERR_USE_REPORT_STATE_INVALID`; and the cumulative
    `service_days_used` over the permit's accepted reports for the season, *including this one*,
    must not exceed the permit's `authorized_service_days`, else
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."
    PRD §3.7: "Both variants read only reports whose `status` is `ACCEPTED` and whose
    `season_year` matches the assessment; `SUBMITTED` and `SUPERSEDED` rows are excluded."
    PRD §3.7: "Three graduated brackets apply when the permit's `fee_schedule_code` is
    `GRADUATED`: 300 basis points on the portion up to 2500000 cents, 400 basis points on the
    portion above that up to 10000000 cents, and 500 basis points above that."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Corner/validations/season_day_cap_rejects_the_cumulative_total_while_each_report_alone_fits
    """
    context = _reporting_permit("2027-09-20T00:00:00Z")
    permit_id = context["permit"]["id"]

    june = validate_success(
        _file(
            context,
            period_start_date="2027-06-01",
            period_end_date="2027-07-01",
            service_days_used=120,
            gross_revenue_cents=500_000,
        ),
        201,
    )
    accept_use_report(june["id"])
    july = validate_success(
        _file(
            context,
            period_start_date="2027-07-01",
            period_end_date="2027-08-01",
            service_days_used=70,
            gross_revenue_cents=500_000,
        ),
        201,
    )
    accept_use_report(july["id"])
    assert read_permit(permit_id)["service_days_used_ytd"] == 190

    over = validate_success(
        _file(
            context,
            period_start_date="2027-08-01",
            period_end_date="2027-08-16",
            service_days_used=15,
            gross_revenue_cents=300_000,
        ),
        201,
    )
    validate_error(
        api_client.accept_trip_use_report(over["id"], SPECIALIST),
        ApiErrorId.ERR_SERVICE_DAY_LIMIT_EXCEEDED,
    )
    assert read_use_report(over["id"])["status"] == "SUBMITTED", (
        "190 + 15 exceeds the 200-day authorization even though 15 alone is trivial"
    )
    assert read_permit(permit_id)["service_days_used_ytd"] == 190

    at_the_cap = validate_success(
        _file(
            context,
            period_start_date="2027-08-16",
            period_end_date="2027-08-31",
            service_days_used=10,
            gross_revenue_cents=300_000,
        ),
        201,
    )
    accepted = accept_use_report(at_the_cap["id"])
    assert accepted["status"] == "ACCEPTED"
    assert read_permit(permit_id)["service_days_used_ytd"] == 200, (
        "the cap is a must-not-exceed, so landing exactly on 200 is admissible"
    )

    one_more = validate_success(
        _file(
            context,
            period_start_date="2027-08-31",
            period_end_date="2027-09-05",
            service_days_used=1,
            gross_revenue_cents=100_000,
        ),
        201,
    )
    validate_error(
        api_client.accept_trip_use_report(one_more["id"], SPECIALIST),
        ApiErrorId.ERR_SERVICE_DAY_LIMIT_EXCEEDED,
    )
    assert read_permit(permit_id)["service_days_used_ytd"] == 200

    accepted_rows, accepted_meta = list_use_reports(
        params={"permit_id": permit_id, "status": "ACCEPTED"}
    )
    assert accepted_meta["total_count"] == 3
    assert [row["service_days_used"] for row in accepted_rows] == [120, 70, 10]

    assessment = sole_fee_assessment(permit_id)
    assert assessment["reported_agr_cents"] == 1_300_000, (
        "the two refused acceptances never entered the fee basis"
    )
    assert assessment["assessed_fee_cents"] == 39_000
    assert assessment["minimum_fee_applied"] is False


def test_accept_and_amend_guard_disjoint_states_behind_one_error_id():
    """PRD §3.7: "The report must be `SUBMITTED`, else `ERR_USE_REPORT_STATE_INVALID`"
    PRD §3.7: "The report must be `ACCEPTED`, else `ERR_USE_REPORT_STATE_INVALID`; the caller must
    own the permit; the deduction cap applies again; and `expected_permit_version` must equal the
    permit's current `version`, else `ERR_STALE_PERMIT_VERSION` at HTTP 412."
    PRD §3.7: "The original row is never edited: it moves `ACCEPTED → SUPERSEDED`, which is
    terminal, and a **new** report row is created directly in `ACCEPTED` carrying
    `supersedes_report_id` pointing at the original, the same `period_start_date` and
    `period_end_date`, and the amended figures"
    PRD §3.7: "It walks the ordered accepted set carrying a running cumulative adjusted gross
    revenue that starts at zero and, for each report, assigns `applied_rate_bp` from the bracket
    that the cumulative total of *strictly earlier* reports falls into"
    PRD §3.7: "The permit's `service_days_used_ytd` is recomputed from the accepted set rather
    than adjusted"

    Design: Corner/errors/report_state_gates_accept_and_amend_from_opposite_sides
    """
    context = _reporting_permit("2027-06-15T00:00:00Z")
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]

    first = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-01",
            service_days_used=20,
            gross_revenue_cents=2_000_000,
        ),
        201,
    )
    accept_use_report(first["id"])
    second = validate_success(
        _file(
            context,
            period_start_date="2027-06-01",
            period_end_date="2027-06-10",
            service_days_used=10,
            gross_revenue_cents=1_000_000,
        ),
        201,
    )

    provisional = sole_fee_assessment(permit_id)
    assert provisional["assessed_fee_cents"] == 60_000

    validate_error(
        api_client.accept_trip_use_report(first["id"], SPECIALIST),
        ApiErrorId.ERR_USE_REPORT_STATE_INVALID,
    )
    assert sole_fee_assessment(permit_id)["assessed_fee_cents"] == 60_000, (
        "acceptance is not idempotent, and the refused repeat left the money alone"
    )

    validate_error(
        api_client.amend_trip_use_report(
            second["id"],
            {
                "expected_permit_version": current_permit_version(permit_id),
                "service_days_used": 12,
                "client_count": 8,
                "gross_revenue_cents": 1_200_000,
                "allowable_deductions_cents": 0,
            },
            holder,
        ),
        ApiErrorId.ERR_USE_REPORT_STATE_INVALID,
    )

    replacement = validate_success(
        api_client.amend_trip_use_report(
            first["id"],
            {
                "expected_permit_version": current_permit_version(permit_id),
                "service_days_used": 20,
                "client_count": 8,
                "gross_revenue_cents": 3_000_000,
                "allowable_deductions_cents": 0,
            },
            holder,
        ),
        201,
    )
    assert replacement["status"] == "ACCEPTED"
    assert replacement["supersedes_report_id"] == first["id"]
    assert replacement["adjusted_gross_revenue_cents"] == 3_000_000
    assert read_use_report(first["id"])["status"] == "SUPERSEDED"

    validate_error(
        api_client.amend_trip_use_report(
            first["id"],
            {
                "expected_permit_version": current_permit_version(permit_id),
                "service_days_used": 20,
                "client_count": 8,
                "gross_revenue_cents": 4_000_000,
                "allowable_deductions_cents": 0,
            },
            holder,
        ),
        ApiErrorId.ERR_USE_REPORT_STATE_INVALID,
    )

    accept_use_report(second["id"])
    assessment = sole_fee_assessment(permit_id)
    assert assessment["reported_agr_cents"] == 4_000_000
    assert assessment["assessed_fee_cents"] == 130_000, (
        "the replacement takes 300 bp on 3000000 and the later report 400 bp on 1000000"
    )
    assert read_use_report(replacement["id"])["applied_rate_bp"] == 300
    assert read_use_report(replacement["id"])["fee_component_cents"] == 90_000
    assert read_use_report(second["id"])["applied_rate_bp"] == 400
    assert read_use_report(second["id"])["fee_component_cents"] == 40_000

    superseded, superseded_meta = list_use_reports(
        params={"permit_id": permit_id, "status": "SUPERSEDED"}
    )
    assert superseded_meta["total_count"] == 1
    assert superseded[0]["id"] == first["id"]

    assert read_permit(permit_id)["service_days_used_ytd"] == 30


def test_every_consequence_of_an_acceptance_is_visible_to_the_next_reader():
    """PRD §3.7: "A fee assessment is never created by a request of its own: it exists only as a
    consequence of an acceptance, its `season_year` is unique per permit, and it is discoverable
    only through the permit's assessment listing, ordered by `season_year` ascending then
    `created_at` ascending, with optional `season_year` and `status` filters."
    PRD §3.7: "Acceptance moves the report `SUBMITTED → ACCEPTED`, stamps `accepted_at`, stamps
    `applied_rate_bp` and `fee_component_cents`, adds `service_days_used` into the permit's
    `service_days_used_ytd`, and either creates the season's fee assessment in `PROVISIONAL` if
    none exists yet or recomputes the existing one. It then recomputes `fee_delinquent` and
    re-derives `compliance_status`, advancing the `version` of the report, the assessment and the
    permit."
    PRD §3.7: "`balance_due_cents` is `assessed_fee_cents` less `paid_to_date_cents` floored at
    zero"
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`."

    Design: Corner/consistency_model/acceptance_side_effects_are_visible_in_the_same_response_and_the_next_read
    """
    context = _reporting_permit("2027-06-15T00:00:00Z")
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    file_insurance_certificate(permit_id, outfitter_id)
    file_bond(permit_id, outfitter_id)

    report = validate_success(
        _file(
            context,
            period_start_date="2027-05-15",
            period_end_date="2027-06-01",
            service_days_used=30,
            gross_revenue_cents=2_000_000,
        ),
        201,
    )

    before = read_permit(permit_id)
    assert before["service_days_used_ytd"] == 0
    assert before["fee_delinquent"] is False
    assert before["insurance_current"] is True
    assert before["bond_current"] is True
    assert before["compliance_status"] == "COMPLIANT"
    _empty, empty_meta = validate_paginated(
        api_client.list_fee_assessments(permit_id, SPECIALIST)
    )
    assert empty_meta["total_count"] == 0

    accepted = validate_success(api_client.accept_trip_use_report(report["id"], SPECIALIST))
    assert accepted["status"] == "ACCEPTED", (
        "the transition is in the accept response itself, not queued behind a later read"
    )
    assert accepted["accepted_at"].startswith("2027-06-15")

    rows, meta = validate_paginated(api_client.list_fee_assessments(permit_id, SPECIALIST))
    assert meta["total_count"] == 1, "one call after the accept, the assessment is already there"
    assessment = rows[0]
    assert assessment["season_year"] == 2027
    assert assessment["status"] == "PROVISIONAL"
    assert assessment["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert assessment["assessed_fee_cents"] == 60_000
    assert assessment["paid_to_date_cents"] == 0
    assert assessment["balance_due_cents"] == 60_000
    assert assessment["credit_balance_cents"] == 0
    assert (
        assessment["assessed_fee_cents"] + assessment["credit_balance_cents"]
        == assessment["paid_to_date_cents"] + assessment["balance_due_cents"]
    )

    after = read_permit(permit_id)
    assert after["service_days_used_ytd"] == 30
    assert after["fee_delinquent"] is True
    assert after["open_noncompliance_points"] == 0
    assert after["compliance_status"] == "PROBATION", (
        "the re-derivation runs inside the accept, driven by the balance it just created"
    )

    _actions, action_meta = list_noncompliance_actions(permit_id)
    assert action_meta["total_count"] == 0, (
        "no citation exists, so the probation came from the fee balance alone"
    )

    holder_view = validate_success(
        api_client.get_trip_use_report(report["id"], context["holder_headers"])
    )
    assert holder_view["status"] == "ACCEPTED"
    assert holder_view["applied_rate_bp"] == 300
    assert holder_view["fee_component_cents"] == 60_000
