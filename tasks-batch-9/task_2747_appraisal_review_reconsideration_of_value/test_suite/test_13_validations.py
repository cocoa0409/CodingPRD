"""
Validations: the ladder's ordering, its scoping, and the pass side of each guard.

Every rung exercised here is exercised from both sides. The comparable dedup guard is
shown rejecting a case-and-whitespace variant on one report while accepting the very same
address on a different report, because its scope is one appraisal. The sale-date guard is
driven one day past the effective date and then exactly onto it. The in-grid ceiling is
driven to its seventh row and then satisfied by the identical row kept out of the grid.
Two ordering pairs are driven in sequence, so that the earlier rung is seen to mask the
later one before the later one is allowed to surface on its own, and the eligibility pair
shows one candidate's standing refused where another's is admitted for the same order.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    DESK_REVIEWER_HEADERS,
    ApiErrorId,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_amc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _author(license_number):
    return {
        "full_name": "Alice Author",
        "license_number": license_number,
        "license_state": "CA",
    }


def _reviewer(license_number, **extra):
    body = {
        "full_name": "Bruno Backup",
        "license_number": license_number,
        "license_state": "CA",
    }
    body.update(extra)
    return body


def _grid(street):
    return [
        {
            "street_address": "1 %s" % street,
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": "2 %s" % street,
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": "3 %s" % street,
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def test_a_case_and_spacing_variant_of_a_filed_address_is_refused(api):
    """Normalisation makes two differently typed addresses the same address.

    One comparable is already on the grid at a plainly written address. A second filing
    of the same street, differing only in capitalisation and in runs of spaces, is
    rejected on the dedup rung. Nothing lands: the grid still holds one row, the parent's
    eligible count is unmoved and the rejected call did not bump the appraisal's version.

    PRD: "Next, addresses are deduplicated on a normalised form: the `street_address` is
    compared case-folded with runs of whitespace collapsed, and a normalised address
    already present on this appraisal is rejected with `ERR_DUPLICATE_COMPARABLE` (HTTP
    422)."

    Design: Corner/validations/violation_duplicate_comparable_address_rejected
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Dup Comp AMC"},
        appraiser=_author("CA-AL-C301"),
        loan={"loan_number": "LN-2747-C301", "borrower_display_name": "Bo Borrower"},
        comparables=_grid("Alder Street")[:1],
    )
    appraisal_id = env["appraisal"]["id"]
    before = fx.read_appraisal(api, appraisal_id)

    response = api.create_comparable(
        appraisal_id,
        f.comparable_payload(
            "  1   ALDER   street ",
            sale_price_cents=39500000,
            gross_adjustment_cents=395000,
            net_adjustment_cents=0,
            distance_miles=1.1,
            sale_date="2026-05-10T00:00:00Z",
        ),
        make_amc_headers(env["amc"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_COMPARABLE, 422)

    rows, meta = validate_paginated(
        api.list_comparables(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    after = fx.read_appraisal(api, appraisal_id)
    assert after["eligible_comp_count"] == 1
    assert after["version"] == before["version"]


def test_the_same_address_is_accepted_on_a_different_report(api):
    """The dedup guard is scoped to one appraisal, not to the whole system.

    Two loan files carry two separate reports from the same appraiser, and the identical
    address is filed on each. The second filing succeeds because the guard asks only
    whether the address is already on *this* appraisal, and each grid ends up holding its
    own single row.

    PRD: "Next, addresses are deduplicated on a normalised form: the `street_address` is
    compared case-folded with runs of whitespace collapsed, and a normalised address
    already present on this appraisal is rejected with `ERR_DUPLICATE_COMPARABLE` (HTTP
    422)."

    Design: Corner/validations/satisfaction_same_address_on_a_second_appraisal_accepted
    """
    amc = fx.create_amc(api, name="Scope AMC")
    appraiser = fx.create_appraiser(api, **_author("CA-AL-C302"))
    fx.enroll_on_panel(api, appraiser["id"], amc["id"])

    first_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C302A", borrower_display_name="Cai Borrower",
    )
    second_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C302B", borrower_display_name="Dee Borrower",
    )
    first = fx.deliver_appraisal(api, first_loan["id"], appraiser["id"], amc["id"])
    second = fx.deliver_appraisal(api, second_loan["id"], appraiser["id"], amc["id"])

    row = _grid("Alder Street")[0]
    first_comp = fx.add_comparables(api, first["id"], amc["id"], [dict(row)])[0]
    second_comp = validate_success(
        api.create_comparable(
            second["id"],
            f.comparable_payload(
                row["street_address"],
                sale_price_cents=row["sale_price_cents"],
                gross_adjustment_cents=row["gross_adjustment_cents"],
                net_adjustment_cents=row["net_adjustment_cents"],
                distance_miles=row["distance_miles"],
                sale_date=row["sale_date"],
            ),
            make_amc_headers(amc["id"]),
        ),
        201,
    )

    assert second_comp["id"] != first_comp["id"]
    assert second_comp["appraisal_id"] == second["id"]
    assert second_comp["gross_adjustment_bps"] == 100
    assert fx.read_appraisal(api, first["id"])["eligible_comp_count"] == 1
    assert fx.read_appraisal(api, second["id"])["eligible_comp_count"] == 1


def _field_review_order(api, suffix, borrower, **extra):
    return fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Order Priority AMC"},
        appraiser=_author("CA-AL-%s" % suffix),
        reviewer=_reviewer("CA-BR-%s" % suffix, **extra),
        loan={
            "loan_number": "LN-2747-%s" % suffix,
            "borrower_display_name": borrower,
            "risk_tier": "HIGH",
        },
        appraisal={"exhibit_count": 1},
        comparables=_grid("Alder Street"),
    )


def test_an_unknown_assignee_is_reported_before_a_backwards_window(api):
    """A body reference that resolves to nothing outranks a malformed window.

    The assignment call is deliberately wrong twice over: it names an appraiser that does
    not exist and it puts the window's end before its start. The reference failure is the
    earlier rung, so that is what comes back, and the window complaint never surfaces.

    PRD: "Every foreign key in the body references an existing row, checked in declaration
    order — otherwise that type's own not-found code (404)."

    PRD: "Escalation assignment resolves `assigned_appraiser_id`. A dangling reference in
    any of these positions yields that referenced type's own not-found code with HTTP
    404."

    Design: Corner/validations/priority_ordering_body_fk_not_found_precedes_invalid_window_on_assign
    """
    env = _field_review_order(api, "C303", "Eli Borrower")
    order = env["order"]
    assert order["escalation_type"] == "FIELD_REVIEW"
    assert order["status"] == "PENDING_ASSIGNMENT"

    response = api.assign_escalation_order(
        order["id"],
        f.assign_payload(
            UNKNOWN_ID,
            "2026-08-03T12:00:00Z",
            "2026-08-03T09:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_FOUND, 404)


def test_a_backwards_window_surfaces_once_the_assignee_resolves(api):
    """With a real appraiser named, the window guard is the one that fires.

    Only the reference is corrected; the window is left inverted. Now the later rung is
    reachable and refuses the call, and the order is untouched by the failed attempt: it
    is still waiting for an assignment, carries no assignee and no cost, has not billed
    the company and has not loaded the reviewer.

    PRD: "The submitted window must be well formed: `inspection_window_start` strictly
    before `inspection_window_end`, and both endpoints present whenever either is,
    otherwise `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/priority_ordering_body_fk_not_found_precedes_invalid_window_on_assign
    """
    env = _field_review_order(api, "C303", "Eli Borrower")
    order = env["order"]

    response = api.assign_escalation_order(
        order["id"],
        f.assign_payload(
            env["reviewer"]["id"],
            "2026-08-03T12:00:00Z",
            "2026-08-03T09:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW, 422)

    after = fx.read_escalation_order(api, order["id"])
    assert after["status"] == "PENDING_ASSIGNMENT"
    assert after["assigned_appraiser_id"] is None
    assert after["total_cost_cents"] is None
    assert fx.read_amc(api, env["amc"]["id"])["ytd_escalation_spend_cents"] == 0
    assert fx.read_appraiser(api, env["reviewer"]["id"])["open_assignment_count"] == 0


def _report_with_a_stranger(api):
    env = fx.graded_report(
        api,
        amc={"name": "Party Match AMC"},
        appraiser=_author("CA-AL-C304"),
        loan={"loan_number": "LN-2747-C304", "borrower_display_name": "Fay Borrower"},
        comparables=_grid("Alder Street"),
    )
    stranger = fx.create_appraiser(api, **_reviewer("CA-BR-C304"))
    fx.enroll_on_panel(api, stranger["id"], env["amc"]["id"])
    env["stranger"] = stranger
    return env


def test_a_dispute_naming_someone_elses_appraiser_is_refused(api):
    """The dispute must name the report's own author, not merely a panel member.

    The named appraiser is enrolled with the same management company and is perfectly real,
    but did not write the report under dispute. That mismatch is refused, and the company's
    open dispute counter never moves.

    PRD: "The parties must match the report: the dispute's `appraiser_id` must equal the
    appraisal's own `appraiser_id` and its `amc_id` must equal the appraisal's own
    `amc_id`, and any mismatch is refused with `ERR_DISPUTE_PARTY_MISMATCH` (HTTP 422)."

    Design: Corner/validations/cross_entity_dispute_parties_must_match_the_appraisal
    """
    env = _report_with_a_stranger(api)

    response = api.create_dispute_case(
        f.dispute_payload(
            env["appraisal"]["id"],
            env["amc"]["id"],
            env["stranger"]["id"],
            "COMP_SELECTION",
            "2026-08-02T09:00:00Z",
            "2026-08-02T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_PARTY_MISMATCH, 422)

    assert fx.read_amc(api, env["amc"]["id"])["open_dispute_count"] == 0
    _, meta = validate_paginated(api.list_dispute_cases(CHIEF_APPRAISER_HEADERS))
    assert meta["total_count"] == 0


def test_a_dispute_naming_the_author_opens_and_snapshots_its_deadline(api):
    """With the authoring appraiser named, the same filing is accepted.

    Only the party is corrected. The case opens, keeps the basis it was filed under, and
    takes a deadline snapshotted from its own creation instant plus the company's default
    response window of seventy-two hours. Filing also loads the company's open dispute
    counter.

    PRD: "Its `response_deadline_at` is snapshotted at creation as the dispute's
    `created_at` plus the company's `sla_response_hours` — a snapshot, so a later change to
    the company's SLA parameter does not move an existing dispute's deadline. Filing
    increments the company's `open_dispute_count`."

    Design: Corner/validations/cross_entity_dispute_parties_must_match_the_appraisal
    """
    env = _report_with_a_stranger(api)

    case = validate_success(
        api.create_dispute_case(
            f.dispute_payload(
                env["appraisal"]["id"],
                env["amc"]["id"],
                env["appraiser"]["id"],
                "COMP_SELECTION",
                "2026-08-02T09:00:00Z",
                "2026-08-02T12:00:00Z",
            ),
            CHIEF_APPRAISER_HEADERS,
        ),
        201,
    )

    assert case["status"] == "OPEN"
    assert case["dispute_basis"] == "COMP_SELECTION"
    assert case["appraiser_id"] == env["appraiser"]["id"]
    assert_instant(
        case["response_deadline_at"], "2026-08-04T00:00:00Z", "response_deadline_at"
    )
    assert case["responded_late"] is False
    assert fx.read_amc(api, env["amc"]["id"])["open_dispute_count"] == 1


def _report_awaiting_comparables(api, suffix, name, borrower):
    return fx.delivered_report(
        api,
        amc={"name": name},
        appraiser=_author("CA-AL-%s" % suffix),
        loan={
            "loan_number": "LN-2747-%s" % suffix,
            "borrower_display_name": borrower,
        },
        comparables=[],
    )


def test_a_sale_that_closed_after_the_effective_date_is_rejected(api):
    """A comparable cannot close after the date as of which value was opined.

    The report's effective date is the middle of July; the offered comparable closed the
    day after. The filing is refused and the grid stays empty.

    PRD: "Next, a `sale_date` later than the parent's `effective_date` is rejected with
    `ERR_COMP_DATE_AFTER_EFFECTIVE` (HTTP 422) — a comparable cannot have closed after the
    date as of which value was opined."

    Design: Corner/validations/temporal_comparable_sale_date_after_effective_date_rejected
    """
    env = _report_awaiting_comparables(api, "C305", "Sale Date AMC", "Gus Borrower")
    appraisal_id = env["appraisal"]["id"]
    assert env["appraisal"]["effective_date"].startswith("2026-07-15")

    response = api.create_comparable(
        appraisal_id,
        f.comparable_payload("20 Cedar Street", sale_date="2026-07-16T00:00:00Z"),
        make_amc_headers(env["amc"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_COMP_DATE_AFTER_EFFECTIVE, 422)

    _, meta = validate_paginated(
        api.list_comparables(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert fx.read_appraisal(api, appraisal_id)["eligible_comp_count"] == 0


def test_a_sale_that_closed_exactly_on_the_effective_date_is_accepted(api):
    """The comparison is strict, so the effective date itself is still admissible.

    The same report is offered a comparable that closed on precisely the effective date.
    Because only a *later* date is rejected, this one lands and is counted.

    PRD: "Next, a `sale_date` later than the parent's `effective_date` is rejected with
    `ERR_COMP_DATE_AFTER_EFFECTIVE` (HTTP 422) — a comparable cannot have closed after the
    date as of which value was opined."

    Design: Corner/validations/temporal_comparable_sale_date_after_effective_date_rejected
    """
    env = _report_awaiting_comparables(api, "C305", "Sale Date AMC", "Gus Borrower")
    appraisal_id = env["appraisal"]["id"]

    row = validate_success(
        api.create_comparable(
            appraisal_id,
            f.comparable_payload("21 Cedar Street", sale_date="2026-07-15T00:00:00Z"),
            make_amc_headers(env["amc"]["id"]),
        ),
        201,
    )
    assert row["appraisal_id"] == appraisal_id

    _, meta = validate_paginated(
        api.list_comparables(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert fx.read_appraisal(api, appraisal_id)["eligible_comp_count"] == 1


SIX_IN_GRID = [
    {
        "street_address": "3%d Cedar Street" % index,
        "sale_price_cents": 39000000 + index * 200000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.0 + index * 0.1,
        "sale_date": "2026-05-0%dT00:00:00Z" % (index + 1),
    }
    for index in range(1, 7)
]


def _full_grid(api):
    env = fx.delivered_report(
        api,
        amc={"name": "Grid Cap AMC"},
        appraiser=_author("CA-AL-C306"),
        loan={"loan_number": "LN-2747-C306", "borrower_display_name": "Hal Borrower"},
        comparables=[dict(row) for row in SIX_IN_GRID],
    )
    assert fx.read_appraisal(api, env["appraisal"]["id"])["eligible_comp_count"] == 6
    return env


def test_a_seventh_in_grid_comparable_is_refused(api):
    """Six in-grid rows fill the grid, and the seventh has nowhere to go.

    The report already carries six comparables that all sit in the grid. A seventh in-grid
    row is refused on the ceiling rung, and the grid is left exactly as it was.

    PRD: "Finally, the grid holds at most six comparables with `included_in_grid` true; an
    addition that would make the seventh in-grid comparable is rejected with
    `ERR_COMP_LIMIT_EXCEEDED` (HTTP 422), while rows explicitly excluded from the grid do
    not count toward that ceiling."

    Design: Corner/validations/aggregate_seventh_in_grid_comparable_exceeds_the_cap
    """
    env = _full_grid(api)
    appraisal_id = env["appraisal"]["id"]

    response = api.create_comparable(
        appraisal_id,
        f.comparable_payload(
            "37 Cedar Street",
            sale_price_cents=40200000,
            gross_adjustment_cents=390000,
            net_adjustment_cents=0,
            distance_miles=1.7,
            sale_date="2026-05-08T00:00:00Z",
        ),
        make_amc_headers(env["amc"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_COMP_LIMIT_EXCEEDED, 422)

    _, meta = validate_paginated(
        api.list_comparables(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 6
    assert fx.read_appraisal(api, appraisal_id)["eligible_comp_count"] == 6


def test_the_same_seventh_row_kept_out_of_the_grid_is_accepted(api):
    """Rows excluded from the grid do not count toward the ceiling.

    The identical seventh row is offered again, differing only in being marked as outside
    the grid. It is accepted, so the appraisal ends up holding seven comparables while the
    in-grid population is still the six the ceiling allows.

    PRD: "Finally, the grid holds at most six comparables with `included_in_grid` true; an
    addition that would make the seventh in-grid comparable is rejected with
    `ERR_COMP_LIMIT_EXCEEDED` (HTTP 422), while rows explicitly excluded from the grid do
    not count toward that ceiling."

    Design: Corner/validations/aggregate_seventh_in_grid_comparable_exceeds_the_cap
    """
    env = _full_grid(api)
    appraisal_id = env["appraisal"]["id"]

    row = validate_success(
        api.create_comparable(
            appraisal_id,
            f.comparable_payload(
                "37 Cedar Street",
                sale_price_cents=40200000,
                gross_adjustment_cents=390000,
                net_adjustment_cents=0,
                distance_miles=1.7,
                sale_date="2026-05-08T00:00:00Z",
                included_in_grid=False,
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        201,
    )
    assert row["included_in_grid"] is False

    _, meta = validate_paginated(
        api.list_comparables(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 7
    assert fx.read_appraisal(api, appraisal_id)["eligible_comp_count"] == 6


def _field_review_with_two_candidates(api):
    env = fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Eligibility AMC"},
        appraiser=_author("CA-AL-C307"),
        reviewer=_reviewer("CA-BR-C307", panel_status="PROBATION"),
        loan={
            "loan_number": "LN-2747-C307",
            "borrower_display_name": "Ivy Borrower",
            "risk_tier": "HIGH",
        },
        appraisal={"exhibit_count": 1},
        comparables=_grid("Alder Street"),
    )
    assert env["order"]["escalation_type"] == "FIELD_REVIEW"
    suspended = fx.create_appraiser(
        api,
        full_name="Cleo Cutoff",
        license_number="CA-CL-C307",
        license_state="CA",
        panel_status="SUSPENDED",
    )
    fx.enroll_on_panel(
        api, suspended["id"], env["amc"]["id"], tier="REVIEW_SPECIALIST"
    )
    env["suspended"] = suspended
    return env


def test_a_suspended_appraiser_is_ineligible_for_a_field_review(api):
    """Suspension disqualifies a candidate from either kind of escalation.

    The suspended candidate holds a live membership with the escalated report's company, so
    the panel-membership condition is satisfied and the standing condition is the one that
    decides. It refuses the assignment, and the order is still waiting for staff.

    PRD: "The candidate's panel standing must permit the order's type, and the two types
    differ: a `SECOND_APPRAISAL` may be assigned only to an appraiser whose `panel_status`
    is `ACTIVE`, while a `FIELD_REVIEW` may be assigned to an appraiser in `ACTIVE` or in
    `PROBATION`; an appraiser in `SUSPENDED` or `REMOVED` is eligible for neither."

    Design: Corner/validations/conditional_appraiser_eligibility_depends_on_escalation_type
    """
    env = _field_review_with_two_candidates(api)

    response = api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["suspended"]["id"],
            "2026-08-02T09:00:00Z",
            "2026-08-02T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_INELIGIBLE, 422)

    after = fx.read_escalation_order(api, env["order"]["id"])
    assert after["status"] == "PENDING_ASSIGNMENT"
    assert after["assigned_appraiser_id"] is None
    assert fx.read_appraiser(api, env["suspended"]["id"])["open_assignment_count"] == 0


def test_an_appraiser_on_probation_may_still_take_a_field_review(api):
    """Probation is disqualifying for a second appraisal but not for a field review.

    The same order is offered a candidate whose standing is probationary rather than active.
    Because this order is a field review, that standing is permitted: the assignment lands
    and the candidate picks up the open assignment, while the suspended candidate remains
    unloaded.

    PRD: "The candidate's panel standing must permit the order's type, and the two types
    differ: a `SECOND_APPRAISAL` may be assigned only to an appraiser whose `panel_status`
    is `ACTIVE`, while a `FIELD_REVIEW` may be assigned to an appraiser in `ACTIVE` or in
    `PROBATION`; an appraiser in `SUSPENDED` or `REMOVED` is eligible for neither."

    Design: Corner/validations/conditional_appraiser_eligibility_depends_on_escalation_type
    """
    env = _field_review_with_two_candidates(api)
    assert fx.read_appraiser(api, env["reviewer"]["id"])["panel_status"] == "PROBATION"

    order = validate_success(
        api.assign_escalation_order(
            env["order"]["id"],
            f.assign_payload(
                env["reviewer"]["id"],
                "2026-08-02T09:00:00Z",
                "2026-08-02T12:00:00Z",
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )
    assert order["status"] == "ASSIGNED"
    assert order["assigned_appraiser_id"] == env["reviewer"]["id"]
    assert fx.read_appraiser(api, env["reviewer"]["id"])["open_assignment_count"] == 1
    assert fx.read_appraiser(api, env["suspended"]["id"])["open_assignment_count"] == 0


def _graded_but_unscreened(api):
    return fx.graded_report(
        api,
        amc={"name": "Gate Order AMC"},
        appraiser=_author("CA-AL-C308"),
        loan={"loan_number": "LN-2747-C308", "borrower_display_name": "Jon Borrower"},
        comparables=_grid("Alder Street"),
    )


def test_the_screen_gate_is_what_stops_a_graded_but_unscreened_report(api):
    """With the receipt battery already run, the missing screen is the live gate.

    The report has been graded, so the first precondition is satisfied and its
    completeness figure is on record. The bias screen has not been run, and that is the
    precondition that refuses the open — with the screen code rather than the rule-check
    code. No review is created.

    PRD: "The receipt checks must already have run, which is to say the appraisal's
    `review_status` must be `RULES_CLEARED` or `RULES_FLAGGED` and its
    `completeness_score_bps` therefore non-null; an appraisal still in `RECEIVED` is
    refused with `ERR_RULE_CHECKS_NOT_RUN` (HTTP 409). The bias screen must already have
    run, which is to say `bias_screen_status` must be anything other than `NOT_SCREENED`;
    an unscreened appraisal is refused with `ERR_BIAS_SCREEN_REQUIRED` (HTTP 422)."

    Design: Corner/validations/cascading_bias_screen_gate_applies_after_the_rule_check_gate
    """
    env = _graded_but_unscreened(api)
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "RULES_CLEARED"
    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["bias_screen_status"] == "NOT_SCREENED"

    response = api.create_desk_review(
        f.desk_review_payload(appraisal["id"], appraisal["version"]),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_BIAS_SCREEN_REQUIRED, 422)

    _, meta = validate_paginated(api.list_desk_reviews(DESK_REVIEWER_HEADERS))
    assert meta["total_count"] == 0
    assert fx.read_appraisal(api, appraisal["id"])["review_status"] == "RULES_CLEARED"


def test_once_the_screen_has_run_the_open_succeeds_at_the_graded_score(api):
    """Running the screen satisfies the last gate and the review opens in draft.

    Only the screen is added; the grid and the battery are untouched. The open now
    succeeds, and because this grid produced neither a failing nor a warning rule row the
    preliminary score is the completeness figure itself, undiminished.

    PRD: "Both start from the appraisal's persisted `completeness_score_bps`. Both subtract
    a rule penalty of 600 basis points for every rule-check row with outcome `FAIL` plus
    200 basis points for every row with outcome `WARN`. The **preliminary** variant stops
    there: it is the base minus the rule penalty, floored at zero, and it is computed
    exactly once at open time, persisted to `preliminary_quality_score_bps`, and never
    recomputed no matter what happens afterwards."

    Design: Corner/validations/cascading_bias_screen_gate_applies_after_the_rule_check_gate
    """
    env = _graded_but_unscreened(api)
    appraisal_id = env["appraisal"]["id"]
    screened = fx.run_bias_screen(api, appraisal_id)
    assert screened["bias_screen_status"] == "CLEAR"

    review = validate_success(
        api.create_desk_review(
            f.desk_review_payload(appraisal_id, screened["version"]),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )
    assert review["status"] == "DRAFT"
    assert review["appraisal_id"] == appraisal_id
    assert review["preliminary_quality_score_bps"] == 10000
    assert review["final_quality_score_bps"] is None
    assert fx.read_appraisal(api, appraisal_id)["review_status"] == "IN_DESK_REVIEW"
