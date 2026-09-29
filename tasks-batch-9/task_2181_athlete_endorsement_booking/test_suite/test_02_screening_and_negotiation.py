"""Brand-fit screening and the term-sheet negotiation cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_opportunity,
    assert_same_instant,
    assert_term_sheet,
    build_deal,
    counter_term_sheet,
    draft_term_sheet,
    file_opportunity,
    make_brand_rep_headers,
    register_athlete,
    register_brand,
    revise_term_sheet,
    revise_term_sheet_payload,
    counter_term_sheet_payload,
    screen_opportunity,
    set_athlete_status,
    set_clock,
    submit_term_sheet,
    validate_error,
    validate_paginated,
    validate_success,
    FOUR_LINE_OPPORTUNITY,
)

AGENT = TEST_USERS["talent_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ── Brand-fit screening boundary ─────────────────────────────────────────────

def test_brand_fit_score_of_exactly_sixty_screens_the_opportunity_in(api):
    """PRD 3.2: "A score of 60 or higher screens the opportunity in and moves it
    `INTAKE → SCREENED`. Anything below 60 moves it `INTAKE → REJECTED_FIT`, and no
    term sheet may ever be drafted against an opportunity in that state."
    PRD 3.2: "The athlete's `base_appearance_rate_cents` is multiplied by that total
    and the product divided by four, and the result rounded half up to whole cents
    becomes `expected_fee_cents`."

    Design: Difficulty/boundary_precision_check/brand_fit_score_exactly_sixty_screens_in
    """
    athlete = register_athlete()
    brand = register_brand(compliance_rating=45)
    opportunity = file_opportunity(
        athlete["id"], brand["id"], **FOUR_LINE_OPPORTUNITY
    )

    screened = validate_success(api.screen_opportunity(opportunity["id"], OFFICER), 200)
    assert_opportunity(screened)

    assert screened["expected_fee_cents"] == 800_000
    assert screened["brand_fit_score"] == 60
    assert screened["status"] == "SCREENED"
    assert screened["screened_by_user_id"] == "co-screen-1"


def test_brand_fit_score_of_fifty_nine_rejects_the_opportunity(api):
    """PRD 3.2: "A score of 60 or higher screens the opportunity in and moves it
    `INTAKE → SCREENED`. Anything below 60 moves it `INTAKE → REJECTED_FIT`, and no
    term sheet may ever be drafted against an opportunity in that state."
    PRD 3.2: "Brand quality contributes 40 percent of the brand's `compliance_rating`.
    Reach contributes 30 percent of a tier figure obtained by multiplying 100 by a
    reach weight of 1.00 for a `GLOBAL` athlete, 0.85 for a `NATIONAL` athlete and
    0.70 for a `REGIONAL` athlete. Money contributes 30 percent of the fee-alignment
    figure. From that sum an exclusivity burden is subtracted: one and a half points
    for each requested exclusivity month, but never more than 20 points however long
    the requested lock. The resulting raw figure is rounded half up to a whole number
    exactly once — never at the intermediate weighted terms — and then clamped so it
    cannot fall below 0 or rise above 100. That whole number is written to
    `brand_fit_score`."

    Design: Difficulty/boundary_precision_check/brand_fit_score_exactly_sixty_screens_in
    """
    athlete = register_athlete()
    brand = register_brand(
        name="Gridiron Gaming",
        category="GAMING",
        legal_entity_name="Gridiron Gaming Ltd",
        compliance_rating=42,
    )
    opportunity = file_opportunity(
        athlete["id"], brand["id"], exclusivity_category="GAMING", **FOUR_LINE_OPPORTUNITY
    )

    screened = validate_success(api.screen_opportunity(opportunity["id"], OFFICER), 200)

    assert screened["expected_fee_cents"] == 800_000
    assert screened["brand_fit_score"] == 59
    assert screened["status"] == "REJECTED_FIT"
    assert screened["screened_by_user_id"] == "co-screen-1", (
        "the rejected branch records the officer just as the accepted one does"
    )


def test_talent_agent_may_not_screen_an_opportunity(api):
    """PRD 2.1: "If the headers are well formed but the named role is not listed among
    the roles authorised for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.2: "A `ComplianceOfficer` screens an opportunity that is still in `INTAKE`;
    the call carries no payload, and it always computes the same two figures before
    choosing a branch."

    Design: Corner/rbac/talent_agent_cannot_screen_opportunity_returns_forbidden_role
    """
    deal = build_deal(stage="filed")

    response = api.screen_opportunity(deal["opportunity_id"], AGENT)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert opportunity["status"] == "INTAKE"
    assert opportunity["brand_fit_score"] is None
    assert opportunity["screened_by_user_id"] is None


# ── The multiplier stack and its ceiling ─────────────────────────────────────

def test_provisional_fee_is_clamped_by_the_contract_value_ceiling(api):
    """PRD 3.3: "The `fee_cents` figure is multiplied by all three multipliers and the
    whole product is rounded half up to whole cents exactly once — never once per
    multiplier — giving the rights component."
    PRD 3.3: "Separately, an exclusivity uplift is taken as the athlete's
    `base_appearance_rate_cents` multiplied by five percent for each month of
    exclusivity on the table, with the month count capped at 24 before the
    multiplication, rounded half up to whole cents once."
    PRD 3.3: "Finally a ceiling applies: `fee_cents` multiplied by 2.5 and rounded
    half up to whole cents. The provisional figure is the lesser of the summed
    components and that ceiling."

    Design: Difficulty/combinatorial_formula/appearance_fee_multiplier_stack_with_cap
    """
    set_clock()
    athlete = register_athlete(full_name="Ivo Marchetti", sport="TENNIS")
    brand = register_brand(
        name="Northstar Motors",
        category="AUTOMOTIVE",
        legal_entity_name="Northstar Motors SA",
        compliance_rating=60,
    )
    opportunity = file_opportunity(
        athlete["id"], brand["id"],
        exclusivity_category="AUTOMOTIVE", exclusivity_months=24,
        territory="GLOBAL", usage_rights_tier="PERPETUAL",
    )
    screen_opportunity(opportunity["id"])
    term_sheet = draft_term_sheet(
        opportunity["id"], fee_cents=200_000, usage_rights_tier="PERPETUAL",
        usage_term_months=24, territory="GLOBAL", morals_clause_tier="TIER_A",
        exclusivity_months=24, appearance_days=0,
    )

    submitted = validate_success(api.submit_term_sheet(term_sheet["id"], AGENT), 200)
    assert_term_sheet(submitted)

    assert submitted["provisional_fee_cents"] == 500_000, (
        "the 600300 rights component plus the 480000 uplift is clamped to 200000 * 2.5"
    )
    assert submitted["provisional_fee_cents"] != 1_080_300


def test_multiplier_stack_screens_in_and_stamps_the_offer_expiry(api):
    """PRD 3.2: "A score of 60 or higher screens the opportunity in and moves it
    `INTAKE → SCREENED`. Anything below 60 moves it `INTAKE → REJECTED_FIT`, and no
    term sheet may ever be drafted against an opportunity in that state."
    PRD 3.3: "Submitting the paper moves it `DRAFT → SUBMITTED` and requires the
    opportunity's athlete to be `ACTIVE` on the roster — a cross-entity guard, since
    it is the *athlete* record and not the term sheet that is being checked.
    Submission recomputes `provisional_fee_cents` and stamps `offer_expires_at` at the
    logical clock plus fourteen days."

    Design: Difficulty/combinatorial_formula/appearance_fee_multiplier_stack_with_cap
    """
    set_clock("2026-08-01T00:00:00Z")
    athlete = register_athlete(full_name="Ivo Marchetti", sport="TENNIS")
    brand = register_brand(
        name="Northstar Motors",
        category="AUTOMOTIVE",
        legal_entity_name="Northstar Motors SA",
        compliance_rating=60,
    )
    opportunity = file_opportunity(
        athlete["id"], brand["id"],
        exclusivity_category="AUTOMOTIVE", exclusivity_months=24,
        territory="GLOBAL", usage_rights_tier="PERPETUAL",
    )
    screened = screen_opportunity(opportunity["id"])
    assert screened["brand_fit_score"] == 64
    assert screened["status"] == "SCREENED"

    term_sheet = draft_term_sheet(
        opportunity["id"], fee_cents=200_000, usage_rights_tier="PERPETUAL",
        usage_term_months=24, territory="GLOBAL", morals_clause_tier="TIER_A",
        exclusivity_months=24, appearance_days=0,
    )
    submitted = submit_term_sheet(term_sheet["id"])

    assert submitted["status"] == "SUBMITTED"
    assert_same_instant(
        submitted["offer_expires_at"], "2026-08-15T00:00:00Z", "offer_expires_at"
    )


# ── The counter / revise cycle ───────────────────────────────────────────────

def test_counter_overwrites_the_terms_and_records_the_countered_tier(api):
    """PRD 3.3: "The brand answers with a counter, moving the paper
    `SUBMITTED → COUNTERED`. The counter carries `counter_fee_cents`,
    `counter_usage_rights_tier`, `counter_morals_clause_tier` and
    `counter_exclusivity_months`, plus an optional `note`, and those four values
    overwrite `fee_cents`, `usage_rights_tier`, `morals_clause_tier` and
    `exclusivity_months` on the paper outright. Countering increments `counter_count`
    by 1 and records the countered tier in `last_counter_morals_tier`."

    Design: Difficulty/non_linear_state_machine/term_sheet_counter_revise_cycle_increments_round
    """
    deal = build_deal(
        stage="submitted",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
    )
    assert deal["term_sheet"]["provisional_fee_cents"] == 2_621_400

    response = api.counter_term_sheet(
        deal["term_sheet_id"],
        counter_term_sheet_payload(
            counter_fee_cents=1_200_000,
            counter_morals_clause_tier="TIER_A",
            note="tighten morals, trim fee",
        ),
        make_brand_rep_headers(deal["brand_id"]),
    )
    countered = validate_success(response, 200)
    assert_term_sheet(countered)

    assert countered["status"] == "COUNTERED"
    assert countered["counter_count"] == 1
    assert countered["last_counter_morals_tier"] == "TIER_A"
    assert countered["fee_cents"] == 1_200_000
    assert countered["morals_clause_tier"] == "TIER_A"


def test_revise_returns_the_paper_to_submitted_and_reprices_it(api):
    """PRD 3.3: "The agent answers a counter by revising, closing the cycle
    `COUNTERED → SUBMITTED`; a paper can therefore travel
    `SUBMITTED → COUNTERED → SUBMITTED` repeatedly, bounded only by the counter
    ceiling."
    PRD 3.3: "A successful revision increments `round_number` by 1, recomputes
    `provisional_fee_cents` by exactly the same rules as submission, and re-stamps
    `offer_expires_at` at the logical clock plus another fourteen days."

    Design: Difficulty/non_linear_state_machine/term_sheet_counter_revise_cycle_increments_round
    """
    deal = build_deal(
        stage="submitted",
        opportunity_overrides=dict(FOUR_LINE_OPPORTUNITY),
        term_sheet_overrides={"appearance_days": 2},
    )
    counter_term_sheet(
        deal["term_sheet_id"], deal["brand_id"],
        counter_fee_cents=1_200_000, counter_morals_clause_tier="TIER_A",
    )

    response = api.revise_term_sheet(
        deal["term_sheet_id"],
        revise_term_sheet_payload(
            fee_cents=1_300_000, usage_rights_tier="BROADCAST", usage_term_months=12,
            morals_clause_tier="TIER_A", exclusivity_months=12, appearance_days=2,
        ),
        AGENT,
    )
    revised = validate_success(response, 200)

    assert revised["status"] == "SUBMITTED"
    assert revised["round_number"] == 2
    assert revised["counter_count"] == 1
    assert revised["fee_cents"] == 1_300_000
    assert revised["morals_clause_tier"] == "TIER_A"
    # 1300000 * 1.35 * 1.15 * 1.20 = 2421900 rights, plus the 240000 uplift.
    assert revised["provisional_fee_cents"] == 2_661_900


def test_fourth_counter_on_one_paper_is_refused(api):
    """PRD 3.3: "A brand gets at most three counters on one paper: if `counter_count`
    has already reached 3, a fourth counter is refused with
    `ERR_COUNTER_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/counter_limit_exceeded_after_three_counters
    """
    deal = build_deal(stage="submitted")
    for round_index in range(3):
        counter_term_sheet(
            deal["term_sheet_id"], deal["brand_id"],
            counter_fee_cents=1_300_001 + round_index,
            counter_morals_clause_tier="TIER_A",
        )
        revise_term_sheet(
            deal["term_sheet_id"],
            fee_cents=1_350_001 + round_index, usage_rights_tier="BROADCAST",
            usage_term_months=12, morals_clause_tier="TIER_A",
            exclusivity_months=12, appearance_days=1,
        )

    response = api.counter_term_sheet(
        deal["term_sheet_id"],
        counter_term_sheet_payload(
            counter_fee_cents=1_310_000, counter_morals_clause_tier="TIER_A"
        ),
        make_brand_rep_headers(deal["brand_id"]),
    )
    validate_error(response, ApiErrorId.ERR_COUNTER_LIMIT_EXCEEDED.value, 422)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["counter_count"] == 3
    assert term_sheet["round_number"] == 4
    assert term_sheet["status"] == "SUBMITTED"


def test_revision_may_not_loosen_the_countered_morals_tier(api):
    """PRD 3.3: "It also enforces a one-way ratchet on reputation risk: the
    `morals_clause_tier` proposed in the revision must be at least as strict as the
    tier recorded in `last_counter_morals_tier`, where `TIER_A` is stricter than
    `TIER_B` and `TIER_B` is stricter than `TIER_C`. Proposing a looser tier than the
    brand's most recent counter demanded is refused with
    `ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`."

    Design: Corner/validations/morals_tier_downgrade_on_revise_is_refused
    """
    deal = build_deal(stage="submitted")
    counter_term_sheet(
        deal["term_sheet_id"], deal["brand_id"],
        counter_fee_cents=1_300_000, counter_morals_clause_tier="TIER_A",
    )

    response = api.revise_term_sheet(
        deal["term_sheet_id"],
        revise_term_sheet_payload(fee_cents=1_350_000, morals_clause_tier="TIER_B"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN.value, 422)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "COUNTERED"
    assert term_sheet["round_number"] == 1
    assert term_sheet["morals_clause_tier"] == "TIER_A"


def test_resubmitting_a_submitted_paper_is_refused(api):
    """PRD 3.3: "Any negotiation action attempted from the wrong state — submitting
    something that is not `DRAFT`, countering or accepting something that is not
    `SUBMITTED`, revising something that is not `COUNTERED`, or withdrawing something
    already `ACCEPTED`, `WITHDRAWN` or `EXPIRED` — is refused with
    `ERR_TERM_SHEET_INVALID_STATE`."
    PRD 3.3: "Submission recomputes `provisional_fee_cents` and stamps
    `offer_expires_at` at the logical clock plus fourteen days."

    Design: Corner/errors/submit_already_submitted_term_sheet_returns_term_sheet_invalid_state
    """
    deal = build_deal(stage="submitted")
    set_clock("2026-08-05T00:00:00Z")

    response = api.submit_term_sheet(deal["term_sheet_id"], AGENT)
    validate_error(response, ApiErrorId.ERR_TERM_SHEET_INVALID_STATE.value, 409)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "SUBMITTED"
    assert term_sheet["round_number"] == 1
    assert_same_instant(
        term_sheet["offer_expires_at"], "2026-08-15T00:00:00Z",
        "offer_expires_at is not re-stamped by a refused submit",
    )


def test_withdrawing_the_last_live_paper_closes_the_opportunity_lost(api):
    """PRD 3.3: "Withdrawal has a knock-on effect on the parent: if, after the
    withdrawal, no term sheet of that opportunity remains in `DRAFT`, `SUBMITTED` or
    `COUNTERED`, the opportunity itself moves `SCREENED → CLOSED_LOST` and accepts no
    further term sheets."

    Design: Corner/state_machines/withdraw_last_live_term_sheet_closes_opportunity_lost
    """
    deal = build_deal(stage="submitted")

    withdrawn = validate_success(
        api.withdraw_term_sheet(
            deal["term_sheet_id"], {"reason": "Athlete calendar conflict"}, AGENT
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"

    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert opportunity["status"] == "CLOSED_LOST"

    rows, _meta = validate_paginated(
        api.list_engagements(AGENT, params={"opportunity_id": deal["opportunity_id"]})
    )
    assert rows == []


# ── Cross-entity guard: the athlete's roster status ──────────────────────────

def test_submit_is_blocked_while_the_athlete_is_suspended(api):
    """PRD 2.10: "A `SUSPENDED` or `RETIRED` athlete may not be negotiated for or
    booked: submitting a term sheet, revising one, and creating an appearance booking
    are all refused with `ERR_ATHLETE_NOT_BOOKABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/term_sheet_submit_blocked_by_suspended_athlete
    """
    deal = build_deal(stage="drafted")
    set_athlete_status(deal["athlete_id"], "SUSPENDED", reason="Pending conduct review")

    response = api.submit_term_sheet(deal["term_sheet_id"], AGENT)
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_BOOKABLE.value, 409)


def test_blocked_submit_leaves_the_paper_unpriced_in_draft(api):
    """PRD 3.3: "Submitting the paper moves it `DRAFT → SUBMITTED` and requires the
    opportunity's athlete to be `ACTIVE` on the roster — a cross-entity guard, since
    it is the *athlete* record and not the term sheet that is being checked.
    Submission recomputes `provisional_fee_cents` and stamps `offer_expires_at` at the
    logical clock plus fourteen days."
    PRD 3.3: "A new paper opens in `DRAFT` with `round_number` 1 and `counter_count`
    0."

    Design: Difficulty/cross_entity_state_dependency/term_sheet_submit_blocked_by_suspended_athlete
    """
    deal = build_deal(stage="drafted")
    assert deal["term_sheet"]["provisional_fee_cents"] is None
    set_athlete_status(deal["athlete_id"], "SUSPENDED", reason="Pending conduct review")

    response = api.submit_term_sheet(deal["term_sheet_id"], AGENT)
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_BOOKABLE.value, 409)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "DRAFT"
    assert term_sheet["provisional_fee_cents"] is None
    assert term_sheet["offer_expires_at"] is None
    assert term_sheet["round_number"] == 1
    assert term_sheet["counter_count"] == 0


# ── The default logical clock ────────────────────────────────────────────────

def test_default_logical_clock_governs_the_offer_expiry(api):
    """PRD 2.4: "Before the first call to that endpoint the logical clock reads
    exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock
    time — not for `created_at`, not for `updated_at`, and not for any of the domain
    stamps (`screened_at`, `offer_expires_at`, `countersigned_at`, `released_at`,
    `disbursed_at`, `decided_at`)."
    PRD 3.3: "Submission recomputes `provisional_fee_cents` and stamps
    `offer_expires_at` at the logical clock plus fourteen days."

    Design: Corner/endpoints/clock_default_time_governs_offer_expiry_without_any_clock_call
    """
    deal = build_deal(stage="drafted", clock=None)

    submitted = validate_success(api.submit_term_sheet(deal["term_sheet_id"], AGENT), 200)
    assert submitted["status"] == "SUBMITTED"
    assert_same_instant(
        submitted["offer_expires_at"], "2026-08-15T00:00:00Z", "offer_expires_at"
    )

    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert_same_instant(opportunity["screened_at"], "2026-08-01T00:00:00Z", "screened_at")
