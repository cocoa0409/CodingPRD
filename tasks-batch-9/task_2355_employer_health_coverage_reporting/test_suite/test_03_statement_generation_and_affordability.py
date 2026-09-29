"""Statement generation, the affordability safe harbors and coverage-offer intervals.

The harness empties the database and relaunches the server before every single
test, so each test below rebuilds its entire world from scratch through the
documented endpoints.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TAX_YEAR,
    TEST_USERS,
    ApiErrorId,
    assert_form_1095c,
    assert_monthly_coverage_line,
    assert_twelve_coverage_lines,
    factories,
    fixtures,
    get_success_data,
    lines_by_month,
    validate_error,
    validate_success,
)

BENEFITS_ADMIN = TEST_USERS["benefits_admin"]
PREPARER = TEST_USERS["preparer"]


# ---------------------------------------------------------------------------
# Local composition helpers (built on test_helpers.fixtures)
# ---------------------------------------------------------------------------
def _hire_salaried_employee(api, member_id, full_name, ssn_last4, **overrides):
    """Hire a salaried employee. A salaried employee supplies
    ``monthly_salary_cents``, so the hourly wage figure is left out of the body.
    """
    payload = factories.employee_payload(
        member_id, full_name, ssn_last4=ssn_last4, is_hourly=False, **overrides
    )
    payload.pop("hourly_rate_cents", None)
    return get_success_data(api.create_employee(payload, BENEFITS_ADMIN))


def _midyear_offer_world(api):
    """A determined-ALE member with one salaried employee whose only offer of
    coverage runs from 2026-07-01 up to 2027-01-01, plus the generated statement.
    """
    ctx = fixtures.determined_ale_group(api, member_overrides={"ein": "555555555"})
    employee = _hire_salaried_employee(
        api,
        ctx["member"]["id"],
        "Nia Franklin",
        "2002",
        monthly_salary_cents=0,
        w2_box1_wages_cents=1200000,
    )
    fixtures.record_hours(api, employee["id"], TAX_YEAR, hours_of_service=160)
    fixtures.create_coverage_offer(
        api,
        employee["id"],
        offer_kind="MEC_MV_FAMILY",
        minimum_value=True,
        lowest_cost_self_only_cents=18000,
        effective_start_date="2026-07-01",
        effective_end_date="2027-01-01",
    )
    ctx["employee"] = employee
    ctx["form"] = fixtures.generate_form(
        api, employee["id"], plan_start_month=7, safe_harbor_preference="W2"
    )
    return ctx


def _undetermined_group_with_employee(api):
    """A season and a group whose member already carries twelve complete
    prior-year headcount months, but whose determination has not been run.
    """
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"])
    member = fixtures.create_group_member(api, group["id"], ein="191919191")
    fixtures.record_headcounts(api, member["id"])
    employee = _hire_salaried_employee(
        api, member["id"], "Cleo Marsh", "1515", monthly_salary_cents=400000
    )
    return {"season": season, "group": group, "member": member, "employee": employee}


def _employee_with_first_half_offer(api):
    """A determined-ALE member with one employee holding a single offer over the
    half-open interval running from 2026-01-01 up to 2026-07-01.
    """
    ctx = fixtures.determined_ale_group(api, member_overrides={"ein": "232323232"})
    employee = _hire_salaried_employee(
        api, ctx["member"]["id"], "Faye Odom", "1818", monthly_salary_cents=400000
    )
    ctx["employee"] = employee
    ctx["offer"] = fixtures.create_coverage_offer(
        api,
        employee["id"],
        offer_kind="MEC_MV_FAMILY",
        minimum_value=True,
        lowest_cost_self_only_cents=17800,
        effective_start_date="2026-01-01",
        effective_end_date="2026-07-01",
    )
    return ctx


def _offers_of(api, employee_id):
    return get_success_data(
        api.list_coverage_offers(BENEFITS_ADMIN, params={"employee_id": employee_id, "limit": 100})
    )


# ---------------------------------------------------------------------------
# The W-2 safe harbor and its offered-month denominator
# ---------------------------------------------------------------------------
def test_w2_threshold_divides_by_offered_month_count(api):
    """PRD §3.6: "Third `offered_month_count` is computed as the number of months whose
    `line14_code` is not `1H`. Fourth that count becomes the divisor of the W-2
    affordability threshold — which is what makes the W-2 harbor look circular: its
    threshold cannot be computed until every line 14 code exists."
    PRD §3.6: "The W-2 threshold is the employee's `w2_box1_wages_cents` multiplied by the
    season's `affordability_pct` and divided by `offered_month_count`."
    PRD §3.6: "The chosen harbor is recorded per month as `safe_harbor_applied` and the
    figure it produced as `affordability_threshold_cents`, which is null when no harbor
    applied."

    Design: Difficulty/combinatorial_formula/w2_threshold_divides_by_offered_month_count_not_twelve
    """
    ctx = _midyear_offer_world(api)

    form = fixtures.read_form(api, ctx["form"]["id"])
    assert form["offered_month_count"] == 6, (
        f"only months 7-12 carry an offer, so offered_month_count should be 6, "
        f"got {form['offered_month_count']}"
    )

    lines = lines_by_month(fixtures.coverage_lines_for(api, form["id"]))
    assert_monthly_coverage_line(
        lines[7], safe_harbor_applied="W2", affordability_threshold_cents=18040
    )
    assert lines[7]["affordability_threshold_cents"] == 18040, (
        "the W-2 threshold divides by offered_month_count (6), not by twelve: "
        f"expected 18040, got {lines[7]['affordability_threshold_cents']}"
    )


def test_midyear_offer_month_is_affordable_under_the_w2_harbor(api):
    """PRD §3.6: "A month is affordable exactly when the governing offer's
    `lowest_cost_self_only_cents` is at most that threshold; a month with no covering offer
    is never affordable, and when the applied harbor is `NONE` no month is affordable."
    PRD §3.6: "Otherwise an affordable month is `2F` when the applied harbor is `W2`, `2G`
    when it is `FPL`, and `2H` when it is `RATE_OF_PAY`."
    PRD §3.6: "`line15_amount_cents` is the offer's `lowest_cost_self_only_cents` when the
    month's `line14_code` is `1B`, `1C`, `1D`, `1E` or `1K`, and null for every other code."
    PRD §3.6: "A month's `assessable` flag is true exactly when `full_time_flag` is true and
    `line16_code` is null."

    Design: Difficulty/combinatorial_formula/w2_threshold_divides_by_offered_month_count_not_twelve
    """
    ctx = _midyear_offer_world(api)

    lines = lines_by_month(fixtures.coverage_lines_for(api, ctx["form"]["id"]))
    assert_monthly_coverage_line(
        lines[7],
        month=7,
        line14_code="1E",
        line15_amount_cents=18000,
        line16_code="2F",
        full_time_flag=True,
        assessable=False,
    )
    assert lines[7]["line16_code"] == "2F", (
        "an 18000 contribution against an 18040 W-2 threshold is affordable, so July's "
        f"line 16 code should be 2F, got {lines[7]['line16_code']!r}"
    )


def test_statement_roll_ups_over_a_midyear_offer(api):
    """PRD §3.6: "`all_12_months_code` is the shared line 14 code when all twelve months
    agree and null otherwise; `ft_month_count` counts months with `full_time_flag` true;
    `offered_month_count` counts months whose `line14_code` is not `1H`;
    `assessable_month_count` counts months with `assessable` true; and `line15_total_cents`
    sums `line15_amount_cents` over the months where it is not null."
    PRD §3.5: "The input set is the employee's hours rows whose `measurement_year` equals the
    season's `tax_year`; the month is full time exactly when that month's `counted_hours` is
    at least 130, and `ft_source` for the month is `MONTHLY_ACTUAL`."

    Design: Difficulty/combinatorial_formula/w2_threshold_divides_by_offered_month_count_not_twelve
    """
    ctx = _midyear_offer_world(api)

    form = fixtures.read_form(api, ctx["form"]["id"])
    assert_form_1095c(
        form,
        offered_month_count=6,
        ft_month_count=12,
        assessable_month_count=6,
        line15_total_cents=108000,
        all_12_months_code=None,
    )
    assert form["line15_total_cents"] == 108000, (
        "six covered months at 18000 cents each sum to 108000, got "
        f"{form['line15_total_cents']}"
    )


def test_month_without_an_offer_is_full_time_and_exposed(api):
    """PRD §3.6: "A month with no offer, or an offer whose kind is `NO_OFFER`, is `1H`."
    PRD §3.6: "Anything left over gets a null `line16_code`, which means the month is
    exposed."
    PRD §3.6: "A month's `assessable` flag is true exactly when `full_time_flag` is true and
    `line16_code` is null."

    Design: Difficulty/combinatorial_formula/w2_threshold_divides_by_offered_month_count_not_twelve
    """
    ctx = _midyear_offer_world(api)

    lines = lines_by_month(fixtures.coverage_lines_for(api, ctx["form"]["id"]))
    assert_monthly_coverage_line(
        lines[1],
        month=1,
        line14_code="1H",
        line15_amount_cents=None,
        line16_code=None,
        full_time_flag=True,
        assessable=True,
    )
    assert lines[1]["assessable"] is True, (
        "January is full time with no offer and therefore exposed, so assessable should "
        f"be true, got {lines[1]['assessable']!r}"
    )


# ---------------------------------------------------------------------------
# Generation is gated on the controlled group's determination state
# ---------------------------------------------------------------------------
def test_form_generation_refused_while_group_not_determined(api):
    """PRD §2.6: "The relevant controlled group is in `DETERMINED_ALE` or `CORRECTION_OPEN`
    — `ERR_GROUP_NOT_DETERMINED_ALE` (409), on form generation, regenerate and build."
    PRD §3.6: "Generation also requires the employee's controlled group to be in
    `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
    `generated_form_count` and `unattached_form_count`."

    Design: Difficulty/cross_entity_state_dependency/form_generation_requires_group_determined_ale
    """
    ctx = _undetermined_group_with_employee(api)

    response = api.create_form_1095c(
        factories.form_1095c_payload(ctx["employee"]["id"], plan_start_month=1), PREPARER
    )
    validate_error(response, ApiErrorId.ERR_GROUP_NOT_DETERMINED_ALE, 409)

    member = fixtures.read_member(api, ctx["member"]["id"])
    assert member["generated_form_count"] == 0, (
        "the refused generation must not increment generated_form_count, got "
        f"{member['generated_form_count']}"
    )
    assert member["unattached_form_count"] == 0, (
        "the refused generation must not increment unattached_form_count, got "
        f"{member['unattached_form_count']}"
    )

    forms = get_success_data(
        api.list_forms_1095c(PREPARER, params={"employee_id": ctx["employee"]["id"]})
    )
    assert forms == [], f"no statement should exist after the refusal, got {forms!r}"


def test_form_generation_succeeds_once_group_reaches_determined_ale(api):
    """PRD §3.6: "Generation also requires the employee's controlled group to be in
    `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
    `generated_form_count` and `unattached_form_count`."
    PRD §3.6: "It creates a **Form1095C** with `form_type` of `ORIGINAL`, a
    `furnishing_status` of `NOT_FURNISHED` and a `filing_status` of `NOT_FILED` — the two
    status dimensions move independently of one another for the rest of the statement's life
    — and twelve **MonthlyCoverageLine** rows created together, one per month, each stamped
    with the parent statement's identity through `form_1095c_id` and its own `month`."
    PRD §3.2: "When `annual_average_fte` is at least 50 but that exception does not apply,
    the group becomes `DETERMINED_ALE` with `ale_reason` of `THRESHOLD_MET` and
    `seasonal_exception_applied` false."

    Design: Difficulty/cross_entity_state_dependency/form_generation_requires_group_determined_ale
    """
    ctx = _undetermined_group_with_employee(api)
    fixtures.run_ale_determination(api, ctx["group"]["id"])

    group = fixtures.read_group(api, ctx["group"]["id"])
    assert group["determination_state"] == "DETERMINED_ALE", (
        f"expected DETERMINED_ALE before generation, got {group['determination_state']!r}"
    )

    created = validate_success(
        api.create_form_1095c(
            factories.form_1095c_payload(ctx["employee"]["id"], plan_start_month=1), PREPARER
        ),
        201,
    )
    assert_form_1095c(
        created,
        form_type="ORIGINAL",
        furnishing_status="NOT_FURNISHED",
        filing_status="NOT_FILED",
        generated_by_user_id="preparer-1",
    )

    member = fixtures.read_member(api, ctx["member"]["id"])
    assert member["generated_form_count"] == 1, (
        f"generation increments generated_form_count, got {member['generated_form_count']}"
    )
    assert member["unattached_form_count"] == 1, (
        f"generation increments unattached_form_count, got {member['unattached_form_count']}"
    )

    assert_twelve_coverage_lines(fixtures.coverage_lines_for(api, created["id"]))


# ---------------------------------------------------------------------------
# Coverage offers are half-open intervals
# ---------------------------------------------------------------------------
def test_coverage_offer_starting_on_an_existing_end_date_is_accepted(api):
    """PRD §3.6: "A `BenefitsAdmin` records each offer of coverage as a **CoverageOffer**
    over a half-open interval: `effective_start_date` is the first date the offer is in force
    and `effective_end_date` is the first date it is no longer in force, so the end date
    itself is outside the offer."
    PRD §3.6: "Because the interval is half-open, a new offer beginning exactly on an
    existing offer's `effective_end_date` is legal; an offer is refused with
    `ERR_COVERAGE_OFFER_OVERLAP` only when its start falls strictly before an existing
    offer's end **and** its end falls strictly after that offer's start."
    PRD §3.6: "`covered_months` is computed as the ascending months of the reporting year
    every single day of which lies inside that interval."

    Design: Difficulty/resource_temporal_overlap/coverage_offer_half_open_adjacent_start_accepted_then_overlap_rejected
    """
    ctx = _employee_with_first_half_offer(api)

    adjacent = validate_success(
        api.create_coverage_offer(
            factories.coverage_offer_payload(
                ctx["employee"]["id"],
                offer_kind="MEC_MV_SELF_ONLY",
                effective_start_date="2026-07-01",
                effective_end_date="2027-01-01",
                lowest_cost_self_only_cents=12000,
            ),
            BENEFITS_ADMIN,
        ),
        201,
    )
    assert adjacent["effective_start_date"] == "2026-07-01", (
        "an offer beginning exactly on the previous offer's end date is legal, got "
        f"{adjacent['effective_start_date']!r}"
    )
    assert adjacent["covered_months"] == [7, 8, 9, 10, 11, 12], (
        f"expected the second half of the reporting year, got {adjacent['covered_months']!r}"
    )

    first = get_success_data(api.get_coverage_offer(ctx["offer"]["id"], BENEFITS_ADMIN))
    assert first["covered_months"] == [1, 2, 3, 4, 5, 6], (
        "the end date 2026-07-01 lies outside the offer, so July is not covered; got "
        f"{first['covered_months']!r}"
    )

    assert len(_offers_of(api, ctx["employee"]["id"])) == 2, "both offers should persist"


def test_coverage_offer_starting_one_day_before_an_existing_end_is_rejected(api):
    """PRD §3.6: "Because the interval is half-open, a new offer beginning exactly on an
    existing offer's `effective_end_date` is legal; an offer is refused with
    `ERR_COVERAGE_OFFER_OVERLAP` only when its start falls strictly before an existing
    offer's end **and** its end falls strictly after that offer's start."
    PRD §2.6: "A new coverage offer's interval does not overlap an existing one for that
    employee — `ERR_COVERAGE_OFFER_OVERLAP` (409), on coverage-offer creation."

    Design: Difficulty/resource_temporal_overlap/coverage_offer_half_open_adjacent_start_accepted_then_overlap_rejected
    """
    ctx = _employee_with_first_half_offer(api)

    response = api.create_coverage_offer(
        factories.coverage_offer_payload(
            ctx["employee"]["id"],
            offer_kind="MEC_MV_SELF_ONLY",
            effective_start_date="2026-06-30",
            effective_end_date="2027-01-01",
            lowest_cost_self_only_cents=12000,
        ),
        BENEFITS_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_OFFER_OVERLAP, 409)

    offers = _offers_of(api, ctx["employee"]["id"])
    assert len(offers) == 1, (
        f"the overlapping offer must not be created, found {len(offers)} offers"
    )


# ---------------------------------------------------------------------------
# Request shape is checked before body foreign keys
# ---------------------------------------------------------------------------
def test_coverage_offer_bad_enum_with_unknown_employee_answers_invalid_request(api):
    """PRD §2.6: "Three consequences are worth naming up front: the request-shape rung sits
    **above** existence, so a body carrying both an out-of-range enum and a non-existent id
    answers `ERR_INVALID_REQUEST` and never a 404; the transmittal-state rung at 20 sits
    **above** the electronic-channel rung at 43, so a paper transmission attempt on a
    submission that is not built answers `ERR_TRANSMITTAL_NOT_BUILT`; and segregation of
    duties at 23 sits **above** every temporal window at 33 through 36, because it is a
    compliance control rather than a scheduling rule."
    PRD §2.6: "Request shape: required fields present, correct types, enum values in range,
    declared integers not negative, `ownership_pct` above 0 and at most 100, `ssn_last4`
    exactly four digits, `ein` exactly nine digits, month values within 1 through 12,
    `months` arrays non-empty, `plan_start_month` within 0 through 12, dates well-formed
    `YYYY-MM-DD`, agency-response `errors` entries well-formed, and the intra-body date
    orderings (a coverage offer's `effective_end_date` strictly after its
    `effective_start_date`; a measurement cycle's `measurement_end_date` on or after
    `measurement_start_date`, `admin_period_end_date` on or after `measurement_end_date`,
    `stability_start_date` strictly after `admin_period_end_date`, `stability_end_date` on or
    after `stability_start_date`; a notice's `response_due_date` strictly after its
    `notice_date`) — `ERR_INVALID_REQUEST` (400), all POST and PATCH endpoints."

    Design: Difficulty/priority_pair_validation_conflict/coverage_offer_invalid_enum_beats_unknown_employee_existence
    """
    ctx = fixtures.determined_ale_group(api, member_overrides={"ein": "141414141"})
    _hire_salaried_employee(
        api, ctx["member"]["id"], "Xena Boyd", "1010", monthly_salary_cents=400000
    )

    response = api.create_coverage_offer(
        factories.coverage_offer_payload(
            NON_EXISTENT_UUID,
            offer_kind="MEC_MV_PLATINUM",
            lowest_cost_self_only_cents=15000,
        ),
        BENEFITS_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    offers = get_success_data(api.list_coverage_offers(BENEFITS_ADMIN, params={"limit": 100}))
    assert offers == [], f"the rejected body must create nothing, got {offers!r}"


def test_coverage_offer_for_unknown_employee_answers_employee_not_found(api):
    """PRD §2.6: "Every foreign key in the body exists — the matching not-found code (404),
    every POST carrying a foreign key."
    PRD §2.5: "Foreign keys carried in a request body are resolved the same way and answer
    with the not-found code of the referenced family: `filing_season_id`,
    `controlled_group_id`, `group_member_id`, `single_member_id`, `employee_id`,
    `to_group_member_id`, `form_1095c_id`, `penalty_notice_id` and each entry of `form_ids`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_offer_invalid_enum_beats_unknown_employee_existence
    """
    ctx = fixtures.determined_ale_group(api, member_overrides={"ein": "141414141"})
    _hire_salaried_employee(
        api, ctx["member"]["id"], "Xena Boyd", "1010", monthly_salary_cents=400000
    )

    response = api.create_coverage_offer(
        factories.coverage_offer_payload(
            NON_EXISTENT_UUID,
            offer_kind="MEC_MV_SELF_ONLY",
            lowest_cost_self_only_cents=15000,
        ),
        BENEFITS_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND, 404)
