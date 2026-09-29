"""
Cross-entity state dependencies: a write refused because of a third entity's state.

A report delivery is legal or illegal according to the ordering management company's own
standing, which appears nowhere in the request body. An escalation assignment is legal or
illegal according to the candidate's panel standing read against the order's escalation
type, so the same candidate that a field review would accept is refused by a second
appraisal. Both instances also pin the absence of side effects on the entities that were
never meant to move.
"""

from test_helpers import (
    ApiErrorId,
    CHIEF_APPRAISER_HEADERS,
    DESK_REVIEWER_HEADERS,
    factories as f,
    fixtures as fx,
    make_amc_headers,
    validate_error,
    validate_paginated,
)


def _suspended_company_and_panelled_author(api):
    """A suspended management company that nonetheless carries an active membership for
    an active appraiser, plus a fresh loan file awaiting its first report."""
    amc = fx.create_amc(
        api, name="Lapsed Appraisal Management", panel_status="SUSPENDED",
    )
    author = fx.create_appraiser(
        api, full_name="Alice Author", license_number="CA-AL-7001",
        license_state="CA",
    )
    membership = fx.enroll_on_panel(api, author["id"], amc["id"])
    loan = fx.create_loan_file(
        api, loan_number="LN-2747-7A1", borrower_display_name="Kai Borrower",
    )
    return {
        "amc": amc,
        "appraiser": author,
        "membership": membership,
        "loan": loan,
    }


def test_a_suspended_company_cannot_deliver_an_otherwise_valid_report(api):
    """Delivery is refused on the company's standing, not on anything in the body.

    Every field of the delivery is well formed, the authoring appraiser holds an active
    membership with the very company named in the body, and the loan file's guard token
    is current. The only defect is the company's suspended standing, which is read from
    a third entity.

    PRD: "The named management company must not be in `SUSPENDED` standing, or the
    delivery is refused with `ERR_AMC_NOT_ELIGIBLE`; and the named appraiser must hold
    an `ACTIVE` panel membership with that same management company, or the delivery is
    refused with `ERR_APPRAISER_NOT_ON_PANEL`."

    Design: Difficulty/cross_entity_state_dependency/appraisal_intake_blocked_by_suspended_amc
    """
    env = _suspended_company_and_panelled_author(api)
    assert env["membership"]["status"] == "ACTIVE"

    response = api.create_appraisal(
        f.appraisal_payload(
            env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
            env["loan"]["version"],
        ),
        make_amc_headers(env["amc"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_AMC_NOT_ELIGIBLE, 422)


def test_the_refused_delivery_leaves_the_loan_and_the_author_untouched(api):
    """No appraisal is persisted and none of the delivery's side effects fire.

    The loan file keeps its pending collateral status, its null value-of-record pointer
    and its guard token, and the authoring appraiser's report tally stays at zero even
    though a successful delivery would have moved it.

    PRD: "The delivery increments the loan file's `version` by 1, increments the
    authoring appraiser's `total_appraisal_count`, and recomputes both of that
    appraiser's performance-score variants — because a new report changes the
    denominator of the revision rate, a delivery can move an appraiser's standing all on
    its own."

    Design: Difficulty/cross_entity_state_dependency/appraisal_intake_blocked_by_suspended_amc
    """
    env = _suspended_company_and_panelled_author(api)
    api.create_appraisal(
        f.appraisal_payload(
            env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
            env["loan"]["version"],
        ),
        make_amc_headers(env["amc"]["id"]),
    )

    rows, meta = validate_paginated(
        api.list_appraisals(
            DESK_REVIEWER_HEADERS, {"loan_file_id": env["loan"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "PENDING_APPRAISAL"
    assert loan["value_of_record_appraisal_id"] is None
    assert loan["version"] == env["loan"]["version"]

    appraiser = fx.read_appraiser(api, env["appraiser"]["id"])
    assert appraiser["total_appraisal_count"] == 0
    assert appraiser["panel_membership_count"] == 1


# A narrative carrying three of the declared prohibited terms, which drives the bias
# index to 36 and the screen to INDICATED.
BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)

CEDAR_GRID = [
    {
        "street_address": "91 Cedar Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "92 Cedar Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "93 Cedar Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _second_appraisal_order_and_probation_candidate(api):
    """A second-appraisal order awaiting staffing, with the only available review
    specialist sitting in probation rather than active standing."""
    return fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Beacon Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-7002",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Probation",
            "license_number": "CA-BP-7002",
            "license_state": "CA",
            "panel_status": "PROBATION",
        },
        loan={
            "loan_number": "LN-2747-7B1",
            "borrower_display_name": "Lena Borrower",
        },
        appraisal={"exhibit_count": 1, "narrative_text": BIASED_NARRATIVE},
        comparables=CEDAR_GRID,
    )


def test_a_probation_candidate_cannot_take_a_second_appraisal(api):
    """The candidate's standing is measured against the order's type and fails.

    Probation is a perfectly assignable standing for a field review, and the candidate
    holds an active membership with the escalated report's company, holds no competing
    inspection window and did not author the report. The refusal turns purely on the
    order being a second appraisal, which admits only active standing.

    PRD: "The candidate's panel standing must permit the order's type, and the two types
    differ: a `SECOND_APPRAISAL` may be assigned only to an appraiser whose
    `panel_status` is `ACTIVE`, while a `FIELD_REVIEW` may be assigned to an appraiser in
    `ACTIVE` or in `PROBATION`; an appraiser in `SUSPENDED` or `REMOVED` is eligible for
    neither."

    Design: Difficulty/cross_entity_state_dependency/second_appraisal_assignment_blocked_by_probation_appraiser
    """
    env = _second_appraisal_order_and_probation_candidate(api)
    assert env["order"]["escalation_type"] == "SECOND_APPRAISAL"

    response = api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["reviewer"]["id"], "2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_INELIGIBLE, 422)


def test_the_bias_override_and_not_the_tier_matrix_set_the_order_type(api):
    """The order is a second appraisal because the screen indicated, not because of tier.

    On a standard-tier loan the matrix would only ever ask for a field review, and only
    below 6000 basis points at that, yet the final score is 6586. The indicated bias
    screen short-circuits the matrix and forces the heavier requirement, which is what
    makes probation standing insufficient.

    PRD: "**Clause one is a bias override and it short-circuits everything else**: if the
    appraisal's `bias_screen_status` is `INDICATED` or `SUBSTANTIATED`,
    `required_escalation` is `SECOND_APPRAISAL` and no further clause is consulted."

    Design: Difficulty/cross_entity_state_dependency/second_appraisal_assignment_blocked_by_probation_appraiser
    """
    env = _second_appraisal_order_and_probation_candidate(api)

    assert env["appraisal"]["bias_screen_status"] == "INDICATED"
    assert env["desk_review"]["risk_tier_at_review"] == "STANDARD"
    assert env["desk_review"]["preliminary_quality_score_bps"] == 8086
    assert env["desk_review"]["final_quality_score_bps"] == 6586
    assert env["desk_review"]["required_escalation"] == "SECOND_APPRAISAL"
    assert env["order"]["escalation_type"] == "SECOND_APPRAISAL"


def test_the_refused_assignment_prices_nothing_and_reserves_nothing(api):
    """None of the four assignment side effects land after the ineligible candidate.

    The order keeps its pending status with no assignee, no priced cost fields and no
    reserved window; the company's year-to-date escalation spend is still zero; and the
    rejected candidate carries no open assignment and keeps the probation standing it
    started with.

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents` to
    the management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Difficulty/cross_entity_state_dependency/second_appraisal_assignment_blocked_by_probation_appraiser
    """
    env = _second_appraisal_order_and_probation_candidate(api)
    api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["reviewer"]["id"], "2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )

    order = fx.read_escalation_order(api, env["order"]["id"])
    assert order["status"] == "PENDING_ASSIGNMENT"
    assert order["assigned_appraiser_id"] is None
    assert order["total_cost_cents"] is None
    assert order["inspection_window_start"] is None

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 0

    candidate = fx.read_appraiser(api, env["reviewer"]["id"])
    assert candidate["panel_status"] == "PROBATION"
    assert candidate["open_assignment_count"] == 0
