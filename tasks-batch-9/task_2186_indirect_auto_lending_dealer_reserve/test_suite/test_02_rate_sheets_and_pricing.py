"""Rate sheets, tier rows, and the tier-assignment / buy-rate engine."""
from test_helpers import (
    ADMIN, ANALYST, COMPLIANCE, ApiErrorId, CLOCK_START, TIER_T1, api_client,
    append_tiers, assert_rate_sheet, assert_rate_sheet_tier, create_draft_rate_sheet,
    create_published_rate_sheet, dealer_status_action, make_credit_analyst_headers,
    publish_sheet, read_application, read_dealer, set_clock, setup_program,
    submit_application, validate_error, validate_paginated, validate_success,
)


def test_tier_row_is_a_historical_fact_without_version_or_updated_at(api):
    """PRD 2.4: "Three entity types are exceptions and are deliberately immutable
    once written: `RateSheetTier`, `ReserveEntry`, and `ChargebackEvent` carry only
    `id` and `created_at` — they have no `updated_at` and no `version` field at all,
    and neither field appears in their response payloads."
    PRD 3.2: "Appending a row advances the owning sheet's `tier_count`."

    Design: Corner/entities/rate_sheet_tier_is_immutable_and_carries_no_version
    """
    set_clock(CLOCK_START)
    sheet = create_draft_rate_sheet()

    response = api.create_tier(sheet["id"], dict(TIER_T1), ADMIN)
    tier = validate_success(response, 201)
    assert_rate_sheet_tier(tier)
    assert "version" not in tier
    assert "updated_at" not in tier

    rows, meta = validate_paginated(api.list_tiers(sheet["id"], ADMIN))
    assert len(rows) == 1
    assert rows[0]["id"] == tier["id"]
    for row in rows:
        assert "version" not in row and "updated_at" not in row

    refreshed = validate_success(api.get_rate_sheet(sheet["id"], ADMIN), 200)
    assert refreshed["tier_count"] == 1


def test_publishing_a_sheet_with_no_tiers_is_rejected(api):
    """PRD 3.2: "It must carry at least one tier row, or the attempt is
    `ERR_RATE_SHEET_NO_TIERS` (HTTP 422)."
    PRD 3.2: "The sheet is born in `DRAFT` with `tier_count` at zero and
    `published_at` null"

    Design: Corner/endpoints/publish_rate_sheet_with_no_tiers_returns_rate_sheet_no_tiers
    """
    set_clock(CLOCK_START)
    sheet = create_draft_rate_sheet()

    response = api.publish_rate_sheet(sheet["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_RATE_SHEET_NO_TIERS.value, 422)

    refreshed = validate_success(api.get_rate_sheet(sheet["id"], ADMIN), 200)
    assert refreshed["status"] == "DRAFT"
    assert refreshed["published_at"] is None
    assert refreshed["tier_count"] == 0


def test_publishing_an_intersecting_rate_sheet_window_is_rejected(api):
    """PRD 3.2: "Intersection is tested under half-open semantics: two windows
    intersect when the existing sheet's `effective_from` is strictly before the new
    sheet's `effective_to` **and** the new sheet's `effective_from` is strictly
    before the existing sheet's `effective_to`."
    PRD 3.2: "An intersection is refused with `ERR_RATE_SHEET_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rate_sheet_halfopen_overlap_adjacency_allowed
    """
    set_clock(CLOCK_START)
    incumbent = create_published_rate_sheet()["rate_sheet"]

    overlapping = create_draft_rate_sheet(
        effective_from="2026-06-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z"
    )
    append_tiers(overlapping["id"], [dict(TIER_T1, buy_rate_apr_bps=499)])

    response = api.publish_rate_sheet(overlapping["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_RATE_SHEET_WINDOW_OVERLAP.value, 409)

    refreshed = validate_success(api.get_rate_sheet(overlapping["id"], ADMIN), 200)
    assert refreshed["status"] == "DRAFT"
    assert validate_success(
        api.get_rate_sheet(incumbent["id"], ADMIN), 200
    )["status"] == "PUBLISHED"


def test_publishing_a_sheet_that_merely_touches_the_incumbent_is_accepted(api):
    """PRD 3.2: "Windows that merely touch — the new sheet beginning at the exact
    instant the existing one ends — do **not** intersect and are accepted."
    PRD 3.2: "every other sheet of the same `program_code` that is currently
    `PUBLISHED` and whose `effective_to` is at or before the current instant moves
    `PUBLISHED → RETIRED`"

    Design: Difficulty/resource_temporal_overlap/rate_sheet_halfopen_overlap_adjacency_allowed
    """
    set_clock(CLOCK_START)
    incumbent = create_published_rate_sheet()["rate_sheet"]

    adjacent = create_draft_rate_sheet(
        effective_from="2027-01-01T00:00:00Z", effective_to="2028-01-01T00:00:00Z"
    )
    append_tiers(adjacent["id"], [dict(TIER_T1, buy_rate_apr_bps=499)])

    published = validate_success(api.publish_rate_sheet(adjacent["id"], ADMIN), 200)
    assert_rate_sheet(published)
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None

    still_published = validate_success(api.get_rate_sheet(incumbent["id"], ADMIN), 200)
    assert still_published["status"] == "PUBLISHED", (
        "its effective_to 2027-01-01 is after the clock, so it is not retired"
    )


def test_publication_retires_an_expired_same_program_sheet(api):
    """PRD 3.2: "Publication also performs the housekeeping that keeps the
    program's history tidy: every other sheet of the same `program_code` that is
    currently `PUBLISHED` and whose `effective_to` is at or before the current
    instant moves `PUBLISHED → RETIRED`, processed in ascending `effective_from`
    order and tie-broken by ascending `created_at`."

    Design: Corner/state_machines/rate_sheet_auto_retires_when_later_sheet_publishes
    """
    set_clock(CLOCK_START)
    expired = create_published_rate_sheet(
        tiers=[dict(TIER_T1)],
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
    )["rate_sheet"]

    successor = create_draft_rate_sheet(
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z"
    )
    append_tiers(successor["id"], [dict(TIER_T1, buy_rate_apr_bps=599)])

    published = validate_success(api.publish_rate_sheet(successor["id"], ADMIN), 200)
    assert published["status"] == "PUBLISHED"

    retired = validate_success(api.get_rate_sheet(expired["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"


def test_credit_score_at_the_inclusive_band_floor_prices_in_the_richest_tier(api):
    """PRD 3.3: "Walking that ordered list, the base tier is the first row whose
    band contains the applicant's `credit_score`: the score is at or above
    `min_credit_score` and at or below `max_credit_score`."
    PRD 3.3: "Finally, `max_contract_apr_bps` is pinned as the assigned
    `buy_rate_apr_bps` plus whichever is smaller of the agreement's
    `max_participation_bps` and the program-wide markup ceiling of 250 basis points."

    Design: Difficulty/boundary_precision_check/tier_band_lower_bound_inclusive_at_720
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-b720", credit_score=720,
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )

    approved = validate_success(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST), 200
    )
    assert approved["base_tier_code"] == "T1"
    assert approved["assigned_tier_code"] == "T1"
    assert approved["buy_rate_apr_bps"] == 549
    assert approved["max_contract_apr_bps"] == 749
    assert approved["demotion_count"] == 0


def test_credit_score_one_point_below_the_band_floor_falls_to_the_next_tier(api):
    """PRD 3.3: "The selected sheet's tier rows are ordered by `min_credit_score`
    descending and tie-broken by `tier_code` ascending — richest band first."
    PRD 3.3: "On success the row at the final index becomes the assigned tier. The
    application moves to `APPROVED` and pins `rate_sheet_id` to the selected sheet,
    `agreement_id` to the selected agreement, `assigned_tier_id` to the assigned tier
    row, `assigned_tier_code` to that row's `tier_code`, and `buy_rate_apr_bps` to
    that row's `buy_rate_apr_bps`."

    Design: Difficulty/boundary_precision_check/tier_band_lower_bound_inclusive_at_720
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-b719", credit_score=719,
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )

    approved = validate_success(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["base_tier_code"] == "T2"
    assert approved["assigned_tier_code"] == "T2"
    assert approved["buy_rate_apr_bps"] == 749
    assert approved["max_contract_apr_bps"] == 949
    assert approved["demotion_count"] == 0
    assert approved["rate_sheet_id"] == program["rate_sheet"]["id"]
    assert approved["agreement_id"] == program["agreement"]["id"]
    assert approved["assigned_tier_id"] is not None


def test_ltv_and_term_breaches_demote_the_base_tier_twice(api):
    """PRD 3.3: "It increases by one when `ltv_pct` is strictly greater than the
    **base** tier's `max_ltv_pct`, and by one again when `term_months` is strictly
    greater than the **base** tier's `max_term_months`, so its value is 0, 1, or 2."
    PRD 3.3: "The final index is the base index plus `demotion_count`."

    Design: Difficulty/combinatorial_formula/tier_demotion_two_steps_without_recheck
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-DEMOTE", credit_score=725,
        monthly_income_cents=700000, monthly_debt_cents=210000,
        amount_financed_cents=2800000, collateral_value_cents=2200000,
        term_months=84, vehicle_model_year=2022, requested_apr_bps=1299,
    )
    assert application["ltv_pct"] == 127.27
    assert application["dti_pct"] == 30.00

    approved = validate_success(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST), 200
    )
    assert approved["base_tier_code"] == "T1"
    assert approved["demotion_count"] == 2
    assert approved["assigned_tier_code"] == "T3"


def test_the_demoted_tier_own_caps_are_not_re_evaluated(api):
    """PRD 3.3: "Both tests are evaluated **once, against the base tier's own caps**
    — the caps of the tier a deal has been demoted into are deliberately not
    re-checked, so a deal never cascades further than two steps."
    PRD 3.3: "Finally, `max_contract_apr_bps` is pinned as the assigned
    `buy_rate_apr_bps` plus whichever is smaller of the agreement's
    `max_participation_bps` and the program-wide markup ceiling of 250 basis points."

    Design: Difficulty/combinatorial_formula/tier_demotion_two_steps_without_recheck
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-DEMOTE2", credit_score=725,
        monthly_income_cents=700000, monthly_debt_cents=210000,
        amount_financed_cents=2800000, collateral_value_cents=2200000,
        term_months=84, vehicle_model_year=2022, requested_apr_bps=1299,
    )

    approved = validate_success(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST), 200
    )
    assert approved["status"] == "APPROVED", (
        "T3's own max_ltv_pct 110 and max_term_months 60 must not be re-tested"
    )
    assert approved["assigned_tier_code"] == "T3"
    assert approved["buy_rate_apr_bps"] == 1099
    assert approved["max_contract_apr_bps"] == 1299


def test_debt_to_income_above_the_ceiling_is_reported_after_the_tier_resolves(api):
    """PRD 3.3: "If `dti_pct` is strictly greater than 45.00 percent, the decision
    fails with `ERR_DTI_EXCEEDED` (HTTP 422)."
    PRD 3.3: "`dti_pct` is `monthly_debt_cents` multiplied by 100, divided by
    `monthly_income_cents`, rounded half up to two decimal places."

    Design: Corner/validations/approve_with_dti_above_cap_returns_dti_exceeded
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-dt",
        monthly_income_cents=500000, monthly_debt_cents=250000,
        amount_financed_cents=1000000, collateral_value_cents=1000000,
    )
    assert application["dti_pct"] == 50.00

    response = api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_DTI_EXCEEDED.value, 422)

    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["assigned_tier_id"] is None


def test_credit_score_below_every_band_yields_no_eligible_tier(api):
    """PRD 3.3: "If no row's band contains the score, the decision fails with
    `ERR_NO_ELIGIBLE_TIER` (HTTP 422)."
    PRD 3.3: "Because this gate runs last, a file that both bands into no tier and
    exceeds the debt-to-income ceiling reports the tier failure, not the
    affordability failure."

    Design: Corner/validations/approve_with_score_below_lowest_band_returns_no_eligible_tier
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-nt", credit_score=580,
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )

    response = api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TIER.value, 422)

    unchanged = read_application(application["id"])
    assert unchanged["base_tier_code"] is None
    assert unchanged["demotion_count"] == 0
    assert unchanged["status"] == "SUBMITTED"


def test_approval_is_refused_when_the_agreement_window_has_closed(api):
    """PRD 3.3: "Among the dealership's agreements, the eligible ones are those
    whose `status` is `ACTIVE` and whose closed window contains the current instant:
    `effective_from` at or before it and `effective_to` at or after it."
    PRD 3.3: "When no candidate exists, the decision fails with
    `ERR_NO_INFORCE_AGREEMENT` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/decision_requires_inforce_agreement_window
    """
    program = setup_program(
        agreement_overrides={"effective_to": "2026-09-01T00:00:00Z"}
    )
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-agw",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    set_clock("2026-10-01T00:00:00Z")

    response = api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_NO_INFORCE_AGREEMENT.value, 422)

    assert read_dealer(program["dealer_id"])["status"] == "ACTIVE", (
        "the dealership itself is in a permitting state"
    )
    agreement = validate_success(
        api.get_agreement(program["agreement"]["id"], ADMIN), 200
    )
    assert agreement["status"] == "ACTIVE"
    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["agreement_id"] is None
    assert unchanged["assigned_tier_id"] is None


def test_agreement_is_still_in_force_on_the_instant_it_expires(api):
    """PRD 2.9: "**Dealer agreements use a closed window.** An agreement is in
    force when its `effective_from` is at or before the clock **and** the clock is at
    or before its `effective_to`; an agreement whose `effective_to` is exactly the
    current instant is still in force on that instant."
    PRD 3.3: "Candidates are ranked by `effective_from` descending, tie-broken by
    `created_at` descending, and the first is selected."

    Design: Difficulty/cross_entity_state_dependency/decision_requires_inforce_agreement_window
    """
    program = setup_program(
        agreement_overrides={"effective_to": "2026-09-01T00:00:00Z"}
    )
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-agw-edge",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    set_clock("2026-09-01T00:00:00Z")

    approved = validate_success(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["agreement_id"] == program["agreement"]["id"]


def test_compliance_hold_is_reported_before_the_rate_sheet_lookup(api):
    """PRD 2.10: "While `compliance_hold` is true, three operations are refused with
    `ERR_DEALER_COMPLIANCE_HOLD` (HTTP 409): decisioning any application of that
    dealership, booking a contract for that dealership, and funding one of its
    contracts."
    PRD 2.7: "then the compliance hold (`ERR_DEALER_COMPLIANCE_HOLD`), then
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then dealer activity status
    (`ERR_DEALER_NOT_ACTIVE`), and only then the domain-specific referential,
    temporal, computational and fiscal rules described throughout §3, in the order in
    which they are introduced there."

    Design: Difficulty/priority_pair_validation_conflict/decision_compliance_safety_beats_rate_sheet_referential
    """
    program = setup_program(
        agreement_overrides={"effective_to": "2028-02-01T00:00:00Z"}
    )
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-ch",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    dealer_status_action(
        program["dealer_id"], "COMPLIANCE_HOLD", "MARKUP_REVIEW_OPEN", headers=COMPLIANCE
    )
    set_clock("2027-06-01T00:00:00Z")

    response = api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST)
    error = validate_error(
        response, ApiErrorId.ERR_DEALER_COMPLIANCE_HOLD.value, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_NO_EFFECTIVE_RATE_SHEET.value


def test_rate_sheet_lookup_failure_surfaces_once_the_hold_is_released(api):
    """PRD 3.3: "Among all rate sheets, the eligible ones are those whose `status`
    is `PUBLISHED`, whose `program_code` equals the dealership's `program_code`, and
    whose half-open window contains the current logical instant: `effective_from` at
    or before the instant and `effective_to` strictly after it."
    PRD 3.3: "When no candidate exists, the decision fails with
    `ERR_NO_EFFECTIVE_RATE_SHEET` (HTTP 422)."
    PRD 3.9: "`RELEASE_HOLD` clears it to false"

    Design: Difficulty/priority_pair_validation_conflict/decision_compliance_safety_beats_rate_sheet_referential
    """
    program = setup_program(
        agreement_overrides={"effective_to": "2028-02-01T00:00:00Z"}
    )
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-ch2",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    dealer_status_action(
        program["dealer_id"], "COMPLIANCE_HOLD", "MARKUP_REVIEW_OPEN", headers=COMPLIANCE
    )
    set_clock("2027-06-01T00:00:00Z")
    validate_error(
        api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST),
        ApiErrorId.ERR_DEALER_COMPLIANCE_HOLD.value, 409,
    )

    dealer_status_action(
        program["dealer_id"], "RELEASE_HOLD", "REVIEW_CLOSED", headers=COMPLIANCE
    )
    assert read_dealer(program["dealer_id"])["compliance_hold"] is False

    response = api.decision_application(application["id"], {"outcome": "APPROVE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_NO_EFFECTIVE_RATE_SHEET.value, 422)

    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["assigned_tier_id"] is None
