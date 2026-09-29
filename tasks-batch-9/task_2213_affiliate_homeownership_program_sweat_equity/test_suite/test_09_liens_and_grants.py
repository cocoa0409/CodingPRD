"""The life of the silent second after settlement, and reporting back to funders."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, APPROVER, OFFICER


def _closed_loan(api, closing_instant="2026-08-05T12:00:00.000Z"):
    """A partnership carried all the way to a recorded ACTIVE lien."""
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    application = X.setup_closed_loan(
        api,
        program["id"],
        household["id"],
        member["id"],
        site["id"],
        closing_date=closing_instant,
        clock_before_close=closing_instant,
    )
    return program, site, household, application


def _award_money(award):
    """The award amount under either of the two spellings the PRD accepts."""
    return award["award_amount_cents"] if "award_amount_cents" in award else award["amount_cents"]


def _award_funder(award):
    """The funder of record under either of the two spellings the PRD accepts."""
    return award["funder_name"] if "funder_name" in award else award["donor_name"]


def test_a_transfer_request_forgives_the_elapsed_slice_before_it_prices_the_sale(api):
    """Decay runs first and its result is what the appreciation ladder is added to.

    "Elapsed months are the whole number of 30-day months between
    `lien_recorded_on` and the clock's present instant, discarding the fraction.
    Nothing is forgiven before the 60th month; from the 60th month onward,
    `forgiven_amount_cents` is the silent second multiplied by the number of months
    beyond the 60th and divided by 180, rounded half-up to whole cents ...
    `lien_outstanding_cents` is the silent second less the forgiven amount, floored
    at zero."

    At 3,000 days the elapsed count is 100 months, so 40 months of the 180-month
    schedule have run: 1,950,000 × 40 / 180 forgives 433,333 and leaves 1,516,667
    outstanding. Straight-line from month zero would have reported 812,500.

    Design: Difficulty/combinatorial_formula/lien_decay_then_shared_appreciation_tier_composition
    """
    _, _, _, application = _closed_loan(api, closing_instant="2026-08-05T00:00:00.000Z")
    assert application["silent_second_amount_cents"] == 1_950_000

    X.advance_clock(api, "2034-10-22T00:00:00.000Z")
    moved = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_TRANSFER_REQUEST, "2034-10-22T00:00:00.000Z", sale_price_cents=20_000_000
            ),
            headers=OFFICER,
        )
    )

    assert moved["silent_second_amount_cents"] == 1_950_000
    assert moved["forgiven_amount_cents"] == 433_333
    assert moved["lien_outstanding_cents"] == 1_516_667
    assert moved["lien_status"] == C.LIEN_TRANSFER_PENDING
    # The origination dimension is untouched by anything the lien does.
    assert moved["status"] == C.APP_CLOSED
    assert moved["right_of_first_refusal_expires_on"] == "2034-11-21T00:00:00.000Z"


def test_the_appreciation_share_is_the_first_matching_tier_not_the_last(api):
    """The tier is picked by where the elapsed month falls, and 100 lands in the middle band.

    "The recapture total the affiliate collects is `lien_outstanding_cents` plus a
    share of the home's appreciation, where appreciation is the `sale_price_cents`
    less the pinned `appraised_value_cents`, floored at zero, and the shared
    percentage steps down over time: 75 percent before the 60th month, 50 percent
    from the 60th through the 119th month, 25 percent from the 120th month up to the
    end of the `resale_restriction_months` affordability period, and nothing at all
    after it."

    Month 100 sits inside the 60-through-119 band, so the affiliate's share of the
    5,000,000-cent appreciation is 2,500,000 and the recapture total riding on the
    outstanding balance is 4,016,667 — a scan that fell through to the last matching
    band would have shared only 1,250,000.

    Design: Difficulty/combinatorial_formula/lien_decay_then_shared_appreciation_tier_composition
    """
    _, site, _, application = _closed_loan(api, closing_instant="2026-08-05T00:00:00.000Z")
    assert application["resale_restriction_months"] == 240

    X.advance_clock(api, "2034-10-22T00:00:00.000Z")
    moved = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_TRANSFER_REQUEST, "2034-10-22T00:00:00.000Z", sale_price_cents=20_000_000
            ),
            headers=OFFICER,
        )
    )

    reread_site = validate_success(api.get_build_site(site["id"], headers=OFFICER))
    appreciation = 20_000_000 - reread_site["appraised_value_cents"]
    assert appreciation == 5_000_000
    shared = round(appreciation * 0.50)
    assert shared == 2_500_000
    assert moved["lien_outstanding_cents"] + shared == 4_016_667


def test_the_forbearance_cycle_runs_twice_and_the_counter_never_gives_hours_back(api):
    """The lien dimension is walked end to end while the origination dimension stays put.

    "A grant is available only on an `ACTIVE` lien of a `CLOSED` application,
    requires its `counseling_session_reference` as evidence that counseling actually
    happened, moves the lien `ACTIVE → FORBEARANCE`, raises
    `forbearance_counseling_sessions` by 1, and recomputes the forgiveness figures.
    ... Reinstatement moves the lien `FORBEARANCE → ACTIVE`, and the `ACTIVE ↔
    FORBEARANCE` cycle can therefore run at most twice."

    Design: Corner/state_machines/lien_forbearance_cure_cycle_then_transfer_and_recapture
    """
    program, _, _, application = _closed_loan(api)
    assert application["status"] == C.APP_CLOSED
    assert application["lien_status"] == C.LIEN_ACTIVE
    assert application["lien_recorded_on"] == "2026-08-05T12:00:00.000Z"
    assert application["lien_outstanding_cents"] == 1_950_000
    assert application["forgiven_amount_cents"] == 0

    first_grant = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_FORBEARANCE,
                "2026-08-05T12:00:00.000Z",
                counseling_session_reference="CNS-0001",
            ),
            headers=OFFICER,
        )
    )
    assert first_grant["lien_status"] == C.LIEN_FORBEARANCE
    assert first_grant["forbearance_counseling_sessions"] == 1
    assert first_grant["status"] == C.APP_CLOSED

    first_cure = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_CURE, "2026-08-05T12:00:00.000Z"),
            headers=OFFICER,
        )
    )
    assert first_cure["lien_status"] == C.LIEN_ACTIVE
    # Curing does not hand the counselling allowance back.
    assert first_cure["forbearance_counseling_sessions"] == 1

    second_grant = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_FORBEARANCE,
                "2026-08-05T12:00:00.000Z",
                counseling_session_reference="CNS-0002",
            ),
            headers=OFFICER,
        )
    )
    assert second_grant["lien_status"] == C.LIEN_FORBEARANCE
    assert second_grant["forbearance_counseling_sessions"] == 2

    second_cure = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_CURE, "2026-08-05T12:00:00.000Z"),
            headers=OFFICER,
        )
    )
    assert second_cure["lien_status"] == C.LIEN_ACTIVE
    assert second_cure["forbearance_counseling_sessions"] == 2

    notice = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_TRANSFER_REQUEST, "2026-08-05T12:00:00.000Z", sale_price_cents=16_000_000
            ),
            headers=OFFICER,
        )
    )
    assert notice["lien_status"] == C.LIEN_TRANSFER_PENDING
    assert notice["right_of_first_refusal_expires_on"] == "2026-09-04T12:00:00.000Z"

    X.advance_clock(api, "2026-09-05T12:00:00.000Z")
    recaptured = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_RECAPTURE, "2026-09-05T12:00:00.000Z"),
            headers=OFFICER,
        )
    )
    assert recaptured["lien_status"] == C.LIEN_RECAPTURED
    assert recaptured["status"] == C.APP_CLOSED

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    # The outstanding balance left the disbursed bucket and 750,000 cents of
    # shared appreciation on a 1,000,000-cent gain came back into the pool.
    assert reread_program["subsidy_disbursed_cents"] == 0
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_pool_cents"] == 5_750_000
    assert reread_program["subsidy_available_cents"] == 5_750_000
    assert reread_program["households_served_count"] == 1


def test_forgiveness_is_flat_through_month_sixty_and_pays_off_only_at_month_two_forty(api):
    """The decay curve is sampled either side of its own start and at its clamp.

    "Nothing is forgiven before the 60th month; from the 60th month onward,
    `forgiven_amount_cents` is the silent second multiplied by the number of months
    beyond the 60th and divided by 180, rounded half-up to whole cents; from the
    240th month onward the whole silent second is forgiven."

    Payoff waits on that curve: "Payoff is available on an `ACTIVE` lien and only
    once `lien_outstanding_cents` has been recomputed to exactly zero ... a payoff
    requested while a balance remains is refused with
    `ERR_LIEN_BALANCE_OUTSTANDING`."

    Design: Corner/calculations/forgiveness_stays_flat_through_month_sixty_then_accrues_and_pays_off
    """
    _, _, _, application = _closed_loan(api)
    assert application["lien_recorded_on"] == "2026-08-05T12:00:00.000Z"

    # 1,770 days past the recording: floor(1770 / 30) is the 59th month.
    X.advance_clock(api, "2031-06-10T12:00:00.000Z")
    at_59 = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert at_59["forgiven_amount_cents"] == 0
    assert at_59["lien_outstanding_cents"] == 1_950_000
    assert at_59["lien_status"] == C.LIEN_ACTIVE

    # 1,800 days: exactly the 60th month.
    X.advance_clock(api, "2031-07-10T12:00:00.000Z")
    at_60 = validate_success(api.get_application(application["id"], headers=OFFICER))
    # The curve starts AT month 60 with a zero numerator; it does not jump.
    assert at_60["forgiven_amount_cents"] == 0
    assert at_60["lien_outstanding_cents"] == 1_950_000

    # 1,830 days: the 61st month, so one month of the 180 has run.
    X.advance_clock(api, "2031-08-09T12:00:00.000Z")
    at_61 = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert at_61["forgiven_amount_cents"] == 10_833
    assert at_61["lien_outstanding_cents"] == 1_939_167

    validate_error(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_SATISFY, "2031-08-09T12:00:00.000Z"),
            headers=OFFICER,
        ),
        E.ERR_LIEN_BALANCE_OUTSTANDING,
        409,
    )
    still_active = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert still_active["lien_status"] == C.LIEN_ACTIVE

    # 7,200 days: the 240th month, where the curve is clamped rather than extrapolated.
    X.advance_clock(api, "2046-04-22T12:00:00.000Z")
    at_240 = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert at_240["forgiven_amount_cents"] == 1_950_000
    assert at_240["lien_outstanding_cents"] == 0

    satisfied = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_SATISFY, "2046-04-22T12:00:00.000Z"),
            headers=OFFICER,
        )
    )
    assert satisfied["lien_status"] == C.LIEN_SATISFIED
    assert satisfied["status"] == C.APP_CLOSED


def test_a_third_grant_a_live_balance_and_an_open_window_are_each_refused(api):
    """Three refusals on one endpoint, each staged from a legal lien state.

    "At most two grants are ever available: a grant requested when
    `forbearance_counseling_sessions` has already reached its limit is refused with
    `ERR_FORBEARANCE_LIMIT_REACHED`." A recording is gated the same way:
    "Recording the transfer moves the lien `TRANSFER_PENDING → RECAPTURED`, and it
    may only happen once the window has lapsed: a recording attempted while the
    logical clock is still before `right_of_first_refusal_expires_on` is refused
    with `ERR_ROFR_WINDOW_OPEN`."

    Design: Corner/validations/a_third_forbearance_and_a_premature_recapture_are_refused
    """
    program, _, _, application = _closed_loan(api)
    for reference in ("CNS-0001", "CNS-0002"):
        validate_success(
            api.lien_action(
                application["id"],
                F.lien_action_payload(
                    C.LIEN_ACTION_FORBEARANCE,
                    "2026-08-05T12:00:00.000Z",
                    counseling_session_reference=reference,
                ),
                headers=OFFICER,
            )
        )
        validate_success(
            api.lien_action(
                application["id"],
                F.lien_action_payload(C.LIEN_ACTION_CURE, "2026-08-05T12:00:00.000Z"),
                headers=OFFICER,
            )
        )

    validate_error(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_FORBEARANCE,
                "2026-08-05T12:00:00.000Z",
                counseling_session_reference="CNS-0003",
            ),
            headers=OFFICER,
        ),
        E.ERR_FORBEARANCE_LIMIT_REACHED,
        409,
    )
    validate_error(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_SATISFY, "2026-08-05T12:00:00.000Z"),
            headers=OFFICER,
        ),
        E.ERR_LIEN_BALANCE_OUTSTANDING,
        409,
    )

    notice = validate_success(
        api.lien_action(
            application["id"],
            F.lien_action_payload(
                C.LIEN_ACTION_TRANSFER_REQUEST, "2026-08-05T12:00:00.000Z", sale_price_cents=16_000_000
            ),
            headers=OFFICER,
        )
    )
    assert notice["lien_status"] == C.LIEN_TRANSFER_PENDING
    assert notice["right_of_first_refusal_expires_on"] == "2026-09-04T12:00:00.000Z"

    X.advance_clock(api, "2026-08-20T12:00:00.000Z")
    validate_error(
        api.lien_action(
            application["id"],
            F.lien_action_payload(C.LIEN_ACTION_RECAPTURE, "2026-08-20T12:00:00.000Z"),
            headers=OFFICER,
        ),
        E.ERR_ROFR_WINDOW_OPEN,
        409,
    )

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["lien_status"] == C.LIEN_TRANSFER_PENDING
    assert reread["status"] == C.APP_CLOSED
    assert reread["forbearance_counseling_sessions"] == 2
    assert reread["lien_outstanding_cents"] == 1_950_000

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    # The refused recapture returned nothing to the pool.
    assert reread_program["subsidy_disbursed_cents"] == 1_950_000
    assert reread_program["subsidy_pool_cents"] == 5_000_000


def test_the_award_read_surface_filters_and_pages_over_three_funders(api):
    """One create per funder, then the whole read surface of the funding aggregate.

    "A `ProgramAdmin` records an award under a program with its `award_code` (1 to 40
    characters, unique within the program), the `donor_name` of the funder — stored
    as the award's `funder_name` — the `amount_cents` of the award, stored as
    `award_amount_cents`, the inclusive reporting `period_start` at UTC midnight and
    the `period_end` which must be strictly after it, the contractual
    `households_served_target` of 1 through 500, and an optional
    `restricted_to_in_kind_reporting` flag defaulting to false. An award opens in
    `OPEN` status."

    Design: Corner/endpoints/grant_award_crud_round_trip_with_filtering_and_pagination
    """
    program = X.setup_program(api)

    first = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="FHLB-2026-Q3",
                amount_cents=2_500_000,
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-09-30T23:59:59.999Z",
                households_served_target=3,
            ),
            headers=ADMIN,
        ),
        201,
    )
    assert first["status"] == C.GRANT_OPEN
    assert _award_money(first) == 2_500_000
    assert _award_funder(first) == "Federal Home Loan Bank"
    assert first["period_end"] == "2026-09-30T23:59:59.999Z"
    assert first["restricted_to_in_kind_reporting"] is False

    second = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="CITY-2026-CDBG",
                amount_cents=1_800_000,
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-12-31T23:59:59.999Z",
                households_served_target=2,
                donor_name="City of Austin",
            ),
            headers=ADMIN,
        ),
        201,
    )
    assert _award_money(second) == 1_800_000
    assert _award_funder(second) == "City of Austin"
    assert second["restricted_to_in_kind_reporting"] is False

    third = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="INKIND-2026-A",
                amount_cents=400_000,
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-12-31T23:59:59.999Z",
                households_served_target=1,
                donor_name="Cedar Lumber Co",
                restricted_to_in_kind_reporting=True,
            ),
            headers=ADMIN,
        ),
        201,
    )
    assert _award_money(third) == 400_000
    assert third["restricted_to_in_kind_reporting"] is True

    # The by-id read is open to the officer as well as the administrator.
    by_id = validate_success(api.get_grant_award(first["id"], headers=OFFICER))
    assert by_id["id"] == first["id"]
    assert by_id["award_code"] == "FHLB-2026-Q3"
    assert by_id["households_served_target"] == 3

    all_rows, all_meta = validate_paginated(
        api.list_grant_awards({"program_id": program["id"]}, headers=ADMIN)
    )
    assert all_meta["total_count"] == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["has_more"] is False
    assert len(all_rows) == 3

    coded_rows, coded_meta = validate_paginated(
        api.list_grant_awards({"award_code": "CITY-2026-CDBG"}, headers=ADMIN)
    )
    assert coded_meta["total_count"] == 1
    assert coded_rows[0]["id"] == second["id"]

    reported_rows, reported_meta = validate_paginated(
        api.list_grant_awards({"program_id": program["id"], "status": C.GRANT_REPORTED}, headers=ADMIN)
    )
    assert reported_meta["total_count"] == 0
    assert reported_rows == []

    page_one, meta_one = validate_paginated(
        api.list_grant_awards({"program_id": program["id"], "limit": 2, "offset": 0}, headers=ADMIN)
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_grant_awards({"program_id": program["id"], "limit": 2, "offset": 2}, headers=ADMIN)
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False


def test_a_report_over_a_period_that_served_nobody_publishes_integer_zeros(api):
    """The empty set is reported, not divided by.

    "When no household qualifies, every numeric field of the report is the integer 0
    — never null, and never a division error — and the itemized list is empty.
    Accepting the report flips the award's `status` to `REPORTED` and increments its
    `version` by 1."

    Design: Corner/calculations/impact_report_over_an_empty_period_returns_integer_zeros
    """
    program = X.setup_program(api)
    award = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="FHLB-2026-Q1",
                amount_cents=2_500_000,
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-03-31T00:00:00.000Z",
                households_served_target=4,
            ),
            headers=ADMIN,
        ),
        201,
    )
    version_before = award["version"]

    report = validate_success(api.create_impact_report(award["id"], headers=ADMIN))
    assert report["households_served"] == 0
    assert report["persons_served"] == 0
    assert report["sweat_equity_hours"] == 0
    assert report["cost_total_cents"] == 0
    assert report["subsidy_total_cents"] == 0
    # The zero-served guard short-circuits both divisions.
    assert report["cost_per_household_cents"] == 0
    assert report["subsidy_per_household_cents"] == 0
    assert report["target_variance"] == -4
    assert report["households"] == []
    assert report["basis"] == C.BASIS_CASH

    reread = validate_success(api.get_grant_award(award["id"], headers=ADMIN))
    assert reread["status"] == C.GRANT_REPORTED
    assert reread["version"] == version_before + 1


def test_a_report_filed_before_the_period_closes_is_refused(api):
    """The identical request is a refusal inside the window and a report after it.

    "The impact report may only be produced once the reporting period has closed:
    the logical clock must have reached `period_end`, and an earlier attempt — or a
    second attempt on an award already in `REPORTED` status — is refused with
    `ERR_REPORTING_PERIOD_OPEN`."

    Design: Corner/validations/an_impact_report_before_the_period_closes_is_refused
    """
    program = X.setup_program(api)
    award = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="FHLB-2026-Q3",
                amount_cents=2_500_000,
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-09-30T23:59:59.999Z",
                households_served_target=3,
            ),
            headers=ADMIN,
        ),
        201,
    )

    validate_error(
        api.create_impact_report(award["id"], headers=ADMIN), E.ERR_REPORTING_PERIOD_OPEN, 409
    )
    during = validate_success(api.get_grant_award(award["id"], headers=ADMIN))
    assert during["status"] == C.GRANT_OPEN

    X.advance_clock(api, "2026-10-01T00:00:00.000Z")
    report = validate_success(api.create_impact_report(award["id"], headers=ADMIN))
    assert report["households_served"] == 0

    after = validate_success(api.get_grant_award(award["id"], headers=ADMIN))
    assert after["status"] == C.GRANT_REPORTED
    assert after["award_code"] == "FHLB-2026-Q3"
    assert after["households_served_target"] == 3
