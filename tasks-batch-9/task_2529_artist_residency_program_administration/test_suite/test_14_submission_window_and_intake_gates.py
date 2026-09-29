"""The clock, the work samples and the fee, each refusing an intake in its own words."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_FEE_ALREADY_SETTLED,
    ERR_FEE_UNSETTLED,
    ERR_FEE_WAIVER_NOT_ELIGIBLE,
    ERR_PORTFOLIO_ITEM_COUNT,
    ERR_PORTFOLIO_MEDIA_MISSING,
    ERR_SUBMISSION_WINDOW_CLOSED,
    add_portfolio_item,
    advance_to_screening,
    create_applicant,
    create_application,
    decide_screening,
    get_success_data,
    make_fee_resolution_payload,
    make_portfolio_item_payload,
    read_application,
    read_cycle,
    refresh_application,
    set_clock,
    setup_open_cycle,
    submit_application,
    validate_error,
)

CLOCK = "2026-08-01T00:00:00Z"
CLOSE_BOUND = "2026-09-30T23:59:59Z"
JUST_INSIDE_CLOSE = CLOSE_BOUND
JUST_PAST_CLOSE = "2026-10-01T00:00:01Z"
JUST_BEFORE_OPEN = "2026-07-31T23:59:59Z"
DEEP_IN_SCREENING = "2026-10-15T00:00:00Z"


def _waived_draft(api, **discipline_overrides):
    """A draft application that wants nothing but a submission call.

    The window closes exactly on `CLOSE_BOUND`, so a clock reading that same
    instant lands on the bound itself — the inclusive case — while
    `JUST_PAST_CLOSE` is genuinely past it. Window bounds are compared as full
    instants, not as calendar dates.
    """
    cycle = setup_open_cycle(
        api,
        clock=CLOCK,
        close_at=CLOSE_BOUND,
        discipline_overrides=discipline_overrides,
    )
    applicant = create_applicant(api)
    app = create_application(api, cycle, applicant, fee_waiver_requested=True)
    waived = get_success_data(
        api.resolve_application_fee(
            app.application_id,
            make_fee_resolution_payload("WAIVE", reason="income below ceiling"),
            ADMIN_HEADERS,
        )
    )
    assert waived["fee_status"] == "WAIVED"
    add_portfolio_item(api, app)
    return cycle, app


def test_one_day_past_the_close_shuts_the_first_submission(api):
    """The window is a property of the clock, not of the cycle's stage.

    PRD: "The logical clock must fall inside the inclusive window running from
    `open_at` to `close_at`; an instant before the window opens or after it closes
    yields `ERR_SUBMISSION_WINDOW_CLOSED` (HTTP 422), and an instant landing
    exactly on either bound is inside the window."

    Design: Corner/validations/first_submission_window_is_inclusive_and_shuts_the_next_day
    """
    cycle, app = _waived_draft(api)
    before = refresh_application(api, app)
    set_clock(api, JUST_PAST_CLOSE)

    validate_error(
        api.submit_application(app.application_id, ADMIN_HEADERS),
        ERR_SUBMISSION_WINDOW_CLOSED,
    )

    held = read_application(api, app.application_id)
    assert held["status"] == "DRAFT"
    assert held["version"] == before["version"]
    assert read_cycle(api, cycle.cycle_id)["status"] == "OPEN"


def test_the_closing_bound_is_inclusive_to_the_whole_day(api):
    """A clock reading the closing instant exactly is still inside the window.

    PRD: "an instant landing exactly on either bound is inside the window. The
    application's `fee_status` must already be `PAID` or `WAIVED`; a
    still-`PENDING` fee is `ERR_FEE_UNSETTLED` (HTTP 422)."

    Design: Corner/validations/first_submission_window_is_inclusive_and_shuts_the_next_day
    """
    _cycle, app = _waived_draft(api)
    set_clock(api, JUST_INSIDE_CLOSE)

    submitted = submit_application(api, app)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 0


def test_the_opening_bound_is_inclusive_in_the_same_way(api):
    """A second early is refused; the opening instant itself is accepted.

    PRD: "an instant before the window opens or after it closes yields
    `ERR_SUBMISSION_WINDOW_CLOSED` (HTTP 422)"

    Design: Corner/validations/first_submission_window_is_inclusive_and_shuts_the_next_day
    """
    _cycle, app = _waived_draft(api)
    set_clock(api, JUST_BEFORE_OPEN)

    validate_error(
        api.submit_application(app.application_id, ADMIN_HEADERS),
        ERR_SUBMISSION_WINDOW_CLOSED,
    )

    set_clock(api, CLOCK)
    assert submit_application(api, app)["status"] == "SUBMITTED"


def test_a_resubmission_is_deliberately_not_window_checked(api):
    """Rework returns long after the deadline, because screening happens later.

    PRD: "The cycle must be in `SCREENING` rather than `OPEN`, and the submission
    window is deliberately **not** re-checked — screening happens after
    `close_at` by construction, so re-testing the window would make every
    resubmission impossible."

    Design: Corner/validations/first_submission_window_is_inclusive_and_shuts_the_next_day
    """
    cycle, app = _waived_draft(api)
    submit_application(api, app)
    advance_to_screening(api, cycle)
    sent_back = decide_screening(api, app, "REQUEST_REVISION")
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["revision_round"] == 1

    set_clock(api, DEEP_IN_SCREENING)
    returned = submit_application(api, app)

    assert returned["status"] == "SUBMITTED"
    assert returned["revision_round"] == 1


# Two work samples are enough to satisfy the count band while leaving the
# required VIDEO coverage missing.
NARROW_PORTFOLIO = {
    "portfolio_min_items": 2,
    "portfolio_max_items": 3,
    "required_media_types": ["IMAGE", "VIDEO"],
}


def _two_image_draft(api):
    """A draft whose count is inside the band and whose coverage is one type short."""
    cycle, app = _waived_draft(api, **NARROW_PORTFOLIO)
    add_portfolio_item(api, app, title="Plate II", file_size_mb=9.0)
    counted = refresh_application(api, app)
    assert counted["portfolio_item_count"] == 2
    assert counted["portfolio_media_types"] == ["IMAGE"]
    return cycle, app


def test_a_satisfied_count_with_a_missing_media_type_names_the_coverage_error(api):
    """Two of the two required samples are present, but both are the same kind.

    PRD: "And every media type listed in the discipline's `required_media_types`
    must appear among the application's `portfolio_media_types`; a missing one is
    `ERR_PORTFOLIO_MEDIA_MISSING` (HTTP 422)."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    _cycle, app = _two_image_draft(api)
    before = refresh_application(api, app)

    validate_error(
        api.submit_application(app.application_id, ADMIN_HEADERS),
        ERR_PORTFOLIO_MEDIA_MISSING,
    )

    held = read_application(api, app.application_id)
    assert held["status"] == "DRAFT"
    assert held["version"] == before["version"]
    assert held["portfolio_item_count"] == 2


def test_adding_the_missing_type_lets_the_identical_submission_through(api):
    """Nothing else about the application changes, and the coverage set widens.

    PRD: "`portfolio_media_types`, the distinct media types present sorted in
    ascending order; and `hazardous_materials_declared` on the application, which
    is true when at least one of its work samples declares hazardous materials."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    _cycle, app = _two_image_draft(api)

    add_portfolio_item(api, app, media_type="VIDEO", title="Reel I", file_size_mb=40.0)

    widened = refresh_application(api, app)
    assert widened["portfolio_media_types"] == ["IMAGE", "VIDEO"]
    assert widened["portfolio_item_count"] == 3
    assert submit_application(api, app)["status"] == "SUBMITTED"


def test_the_count_band_answers_before_the_coverage_rule_does(api):
    """One lone VIDEO fails on the count, not on the missing IMAGE.

    PRD: "The `portfolio_item_count` must lie at or above the discipline's
    `portfolio_min_items` and at or below its `portfolio_max_items`, with both
    bounds inclusive; outside that band the answer is `ERR_PORTFOLIO_ITEM_COUNT`
    (HTTP 422)."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    _cycle, app = _two_image_draft(api)
    add_portfolio_item(api, app, media_type="VIDEO", title="Reel I", file_size_mb=40.0)
    for item_id in list(app.portfolio_item_ids[:2]):
        removed = api.delete_portfolio_item(item_id, ADMIN_HEADERS)
        assert removed.status_code == 204
    thinned = refresh_application(api, app)
    assert thinned["portfolio_item_count"] == 1
    assert thinned["portfolio_media_types"] == ["VIDEO"]

    validate_error(
        api.submit_application(app.application_id, ADMIN_HEADERS),
        ERR_PORTFOLIO_ITEM_COUNT,
    )

    assert read_application(api, app.application_id)["status"] == "DRAFT"


def test_the_maximum_is_guarded_on_the_attach_call_as_well(api):
    """A fourth work sample is refused before it can be counted.

    PRD: "Attaching an item that would push the application past its discipline's
    `portfolio_max_items` is refused with `ERR_PORTFOLIO_ITEM_COUNT` (HTTP 422)."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    _cycle, app = _two_image_draft(api)
    add_portfolio_item(api, app, media_type="VIDEO", title="Reel I", file_size_mb=40.0)

    validate_error(
        api.create_portfolio_item(
            make_portfolio_item_payload(
                app.application_id, media_type="AUDIO", title="Track I"
            ),
            ADMIN_HEADERS,
        ),
        ERR_PORTFOLIO_ITEM_COUNT,
    )

    unchanged = refresh_application(api, app)
    assert unchanged["portfolio_item_count"] == 3
    assert unchanged["portfolio_media_types"] == ["IMAGE", "VIDEO"]


def test_coverage_is_read_as_a_set_so_duplicates_never_substitute(api):
    """Three samples of one type fill the band and still miss the second type.

    PRD: "`required_media_types` names every media type that must appear at least
    once among an application's work samples and is a possibly-empty subset of
    `IMAGE`, `VIDEO`, `AUDIO`, `TEXT` and `MODEL_3D`."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    _cycle, app = _two_image_draft(api)
    add_portfolio_item(api, app, title="Plate III", file_size_mb=7.5)
    stacked = refresh_application(api, app)
    assert stacked["portfolio_item_count"] == 3
    assert stacked["portfolio_media_types"] == ["IMAGE"]

    validate_error(
        api.submit_application(app.application_id, ADMIN_HEADERS),
        ERR_PORTFOLIO_MEDIA_MISSING,
    )

    assert read_application(api, app.application_id)["status"] == "DRAFT"


def test_the_unsettled_fee_answers_before_either_portfolio_rule(api):
    """An empty portfolio and an unpaid fee together are reported as the fee.

    PRD: "The application's `fee_status` must already be `PAID` or `WAIVED`; a
    still-`PENDING` fee is `ERR_FEE_UNSETTLED` (HTTP 422)."

    Design: Corner/validations/portfolio_media_coverage_and_item_count_map_to_distinct_errors
    """
    cycle = setup_open_cycle(api, clock=CLOCK, discipline_overrides=NARROW_PORTFOLIO)
    bare = create_application(api, cycle, create_applicant(api))
    assert bare.application["fee_status"] == "PENDING"
    assert bare.application["portfolio_item_count"] == 0

    validate_error(
        api.submit_application(bare.application_id, ADMIN_HEADERS), ERR_FEE_UNSETTLED
    )

    assert read_application(api, bare.application_id)["status"] == "DRAFT"


WAIVER_INCOME_CEILING = 3500000
WAIVER_REASON = "Freelance income below the published ceiling"


def _fee_case(api, income, requested):
    """A fresh draft whose applicant earns `income` and may or may not have asked."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    applicant = create_applicant(api, declared_annual_income_cents=income)
    app = create_application(api, cycle, applicant, fee_waiver_requested=requested)
    assert app.application["fee_status"] == "PENDING"
    assert app.application["fee_waiver_reason"] is None
    return applicant, app


def _waive(api, application_id, reason=WAIVER_REASON):
    """The waiver decision as a `ProgramAdmin` records it."""
    return api.resolve_application_fee(
        application_id, make_fee_resolution_payload("WAIVE", reason=reason), ADMIN_HEADERS
    )


def test_an_income_one_cent_over_the_ceiling_is_refused(api):
    """The ceiling is an upper bound, so 3,500,001 cents falls outside it.

    PRD: "`WAIVE` sets it to `WAIVED`, but only when the artist actually asked —
    `fee_waiver_requested` must be true — and only when their
    `declared_annual_income_cents` is at or below the waiver income ceiling of
    3,500,000 cents, which is thirty-five thousand dollars a year"

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, WAIVER_INCOME_CEILING + 1, True)

    validate_error(_waive(api, app.application_id), ERR_FEE_WAIVER_NOT_ELIGIBLE)

    held = read_application(api, app.application_id)
    assert held["fee_status"] == "PENDING"
    assert held["version"] == app.application["version"]


def test_an_income_exactly_on_the_ceiling_qualifies(api):
    """One cent lower than the refusal above, and the waiver lands.

    PRD: "a request that fails either condition is `ERR_FEE_WAIVER_NOT_ELIGIBLE`
    (HTTP 422), and note that an income sitting exactly on the ceiling qualifies."

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, WAIVER_INCOME_CEILING, True)

    waived = get_success_data(_waive(api, app.application_id))

    assert waived["fee_status"] == "WAIVED"
    assert waived["fee_waiver_reason"] == WAIVER_REASON
    assert waived["version"] == app.application["version"] + 1


def test_a_modest_income_without_the_request_flag_is_refused_too(api):
    """Both conditions must hold, and this artist never asked.

    PRD: "`WAIVE` sets it to `WAIVED`, but only when the artist actually asked —
    `fee_waiver_requested` must be true — and only when their
    `declared_annual_income_cents` is at or below the waiver income ceiling of
    3,500,000 cents"

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, 1000000, False)

    validate_error(_waive(api, app.application_id), ERR_FEE_WAIVER_NOT_ELIGIBLE)

    assert read_application(api, app.application_id)["fee_status"] == "PENDING"


def test_raising_the_request_flag_makes_the_identical_waiver_land(api):
    """Only the flag changes between the refusal above and this acceptance.

    PRD: "While it is in `DRAFT` or `REVISION_REQUESTED` the artist may revise its
    `discipline_id`, `requested_session_length_weeks`, `project_statement` or
    `fee_waiver_requested`, each advancing the application's `version` by 1"

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, 1000000, False)
    validate_error(_waive(api, app.application_id), ERR_FEE_WAIVER_NOT_ELIGIBLE)

    asked = get_success_data(
        api.update_application(
            app.application_id, {"fee_waiver_requested": True}, ADMIN_HEADERS
        )
    )
    assert asked["fee_waiver_requested"] is True

    granted = get_success_data(_waive(api, app.application_id))
    assert granted["fee_status"] == "WAIVED"


def test_the_income_is_read_live_from_the_applicant_profile(api):
    """Lowering the declared income turns the refusal into an acceptance.

    PRD: "Profile edits may change `full_name`, `affiliation_org`,
    `citizenship_country`, `treaty_country` or `declared_annual_income_cents`"

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    applicant, app = _fee_case(api, WAIVER_INCOME_CEILING + 1, True)
    validate_error(_waive(api, app.application_id), ERR_FEE_WAIVER_NOT_ELIGIBLE)

    trimmed = get_success_data(
        api.update_applicant(
            applicant.applicant_id,
            {"declared_annual_income_cents": WAIVER_INCOME_CEILING - 100000},
            ADMIN_HEADERS,
        )
    )
    assert trimmed["declared_annual_income_cents"] == WAIVER_INCOME_CEILING - 100000

    granted = get_success_data(_waive(api, app.application_id))
    assert granted["fee_status"] == "WAIVED"


def test_a_denied_waiver_records_a_reason_without_settling_the_fee(api):
    """The refusal is recorded, and the fee is still there to be paid afterwards.

    PRD: "`DENY_WAIVER` records the decision without settling anything, leaving
    `fee_status` at `PENDING`. In all three cases the supplied reason is stored on
    the application as `fee_waiver_reason`, which is null until the first fee
    decision is recorded, and the application's `version` advances by 1."

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, WAIVER_INCOME_CEILING + 1, True)

    denied = get_success_data(
        api.resolve_application_fee(
            app.application_id,
            make_fee_resolution_payload("DENY_WAIVER", reason="Income above ceiling"),
            ADMIN_HEADERS,
        )
    )

    assert denied["fee_status"] == "PENDING"
    assert denied["fee_waiver_reason"] == "Income above ceiling"
    assert denied["version"] == app.application["version"] + 1
    paid = get_success_data(
        api.resolve_application_fee(
            app.application_id, make_fee_resolution_payload("PAY"), ADMIN_HEADERS
        )
    )
    assert paid["fee_status"] == "PAID"


def test_a_settled_fee_refuses_every_later_decision(api):
    """Payment closes the question even for an otherwise eligible waiver.

    PRD: "A fee may only be settled once: if `fee_status` is already `PAID` or
    `WAIVED`, the request is `ERR_FEE_ALREADY_SETTLED` (HTTP 409)."

    Design: Corner/validations/fee_waiver_requires_both_the_request_flag_and_the_income_ceiling
    """
    _applicant, app = _fee_case(api, 1000000, True)
    paid = get_success_data(
        api.resolve_application_fee(
            app.application_id, make_fee_resolution_payload("PAY"), ADMIN_HEADERS
        )
    )
    assert paid["fee_status"] == "PAID"

    validate_error(_waive(api, app.application_id), ERR_FEE_ALREADY_SETTLED)

    unchanged = read_application(api, app.application_id)
    assert unchanged["fee_status"] == "PAID"
    assert unchanged["version"] == paid["version"]
