"""Forfeiture's four-link cascade, and the rationed legacy reclamation fund."""
from test_helpers import (
    PERMIT_REVIEWER,
    PROGRAM_DIRECTOR,
    PUBLIC_PARTICIPANT,
    ApiErrorId,
    api_client as api,
    assert_forfeiture_proceeding,
    assert_mine_site,
    assert_money,
    chain_issued,
    create_permit_payload,
    file_permit_revision,
    finalize_forfeiture,
    initiate_forfeiture,
    nominate_legacy_site,
    refresh_instrument,
    refresh_mine_site,
    refresh_operator,
    refresh_permit,
    refresh_proceeding,
    register_legacy_site,
    register_mine_site,
    register_qualified_operator,
    set_clock,
    setup_nominated_legacy_site,
    validate_error,
    validate_paginated,
    validate_success,
)

HIGHLINE_OPERATOR = {
    "legal_name": "Highline Resources Group",
    "tangible_net_worth": 40000000.00,
    "fixed_assets_in_state": 25000000.00,
    "total_liabilities": 8000000.00,
    "net_income_prior_year": 5000000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}

CONTEST_WINDOW_OPERATOR = {
    "legal_name": "Contest Window Mining",
    "tangible_net_worth": 15850000.00,
    "fixed_assets_in_state": 7820000.00,
    "total_liabilities": 5105000.00,
    "net_income_prior_year": 625000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}

HIGH_SCORING_NOMINATION = {
    "hazard_class": "H1_EXTREME",
    "public_safety_score": 80,
    "water_quality_score": 60,
    "acres_affected": 90.00,
}
MIDDLE_SCORING_NOMINATION = {
    "hazard_class": "H2_HIGH",
    "public_safety_score": 50,
    "water_quality_score": 40,
    "acres_affected": 200.00,
}
LOW_SCORING_NOMINATION = {
    "hazard_class": "H3_MODERATE",
    "public_safety_score": 20,
    "water_quality_score": 10,
    "acres_affected": 50.00,
}


def _highline_portfolio_at_the_brink():
    """Two permits under one self-bonding operator, one of them in forfeiture.

    Permit A is cash-bonded and bond-deficient after an approved expansion, and
    carries an INITIATED proceeding whose contest window has already closed.
    Permit B is untouched and secured entirely by a self bond.
    """
    operator = register_qualified_operator(**HIGHLINE_OPERATOR)
    assert operator["self_bond_status"] == "QUALIFIED"
    assert_money(operator["self_bond_capacity_amount"], 10000000.00, "self_bond_capacity_amount")

    permit_a = chain_issued(
        operator=operator,
        site_overrides={
            "name": "Highline Alpha Pit", "county": "Sweetwater", "total_acres": 400.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        instrument_type="CASH",
        face_amount=900000.00,
    )
    permit_b = chain_issued(
        operator=operator,
        site_overrides={
            "name": "Highline Beta Pit", "county": "Sweetwater", "total_acres": 90.00,
        },
        mining_plan_acres=20.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
        instrument_type="SELF_BOND",
        face_amount=144700.00,
    )
    # 7110.00 loaded per acre x 20 = 142200.00 subtotal, whose 1.5 percent fee of
    # 2133.00 is raised to the 2500.00 floor.
    assert_money(permit_b["permit"]["bond_required_amount"], 144700.00, "bond_required_amount")
    assert_money(permit_b["permit"]["bond_held_amount"], 144700.00, "bond_held_amount")
    assert permit_b["permit"]["compliance_posture"] == "COMPLIANT"

    revision = file_permit_revision(permit_a, "EXPANSION", acreage_delta=60.00)
    validate_success(
        api.decide_permit_revision(
            revision["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )
    permit_a["permit"] = refresh_permit(permit_a["permit"]["id"])
    assert_money(permit_a["permit"]["bond_deficiency_amount"], 398997.00, "bond_deficiency_amount")
    assert permit_a["permit"]["compliance_posture"] == "BOND_DEFICIENT"

    initiate_forfeiture(permit_a, "BOND_DEFICIENCY_UNCURED")
    set_clock("2026-09-05T00:00:00Z")
    return operator, permit_a, permit_b


def test_finalisation_takes_the_bond_and_forfeits_the_permit():
    """At finalisation the proceeding stamps `finalized_at` with the logical
    clock's current value, stores the supplied `state_reclamation_cost_estimate`,
    and captures `forfeited_bond_amount` as the permit's `bond_held_amount` **as
    observed before** the permit is transitioned.

    Design: Difficulty/transitive_cascade/forfeiture_finalize_cascade_reaches_second_permit_bond_deficiency
    """
    _, permit_a, permit_b = _highline_portfolio_at_the_brink()

    proceeding = finalize_forfeiture(permit_a, state_reclamation_cost_estimate=1200000.00)
    assert_forfeiture_proceeding(proceeding)

    # Link 1: the proceeding's own transition and its settlement figures.
    assert proceeding["status"] == "FINAL"
    assert proceeding["finalized_at"] is not None
    assert_money(proceeding["forfeited_bond_amount"], 900000.00, "forfeited_bond_amount")
    assert_money(proceeding["state_reclamation_cost_estimate"], 1200000.00,
                 "state_reclamation_cost_estimate")
    assert_money(proceeding["deficiency_amount"], 300000.00, "deficiency_amount")
    assert_money(proceeding["surplus_amount"], 0.00, "surplus_amount")

    # Link 2: the permit follows, caused by link 1 rather than by the request.
    permit = refresh_permit(permit_a["permit"]["id"])
    assert permit["status"] == "FORFEITED"
    assert_money(permit["bond_held_amount"], 0.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert refresh_instrument(permit_a["instrument"]["id"])["status"] == "FORFEITED"

    assert refresh_permit(permit_b["permit"]["id"])["status"] == "ISSUED", (
        "only the permit under proceeding was forfeited"
    )


def test_the_forfeiture_reaches_the_self_bond_on_the_untouched_permit():
    """Every bond instrument with `instrument_type` of `SELF_BOND` and status
    `ACCEPTED` sitting on the operator's **other** permits moves `ACCEPTED →
    SUBSTITUTION_REQUIRED`; each such instrument's `credited_amount` thereby
    leaves its permit's held-bond sum; and each of those permits recomputes
    `bond_deficiency_amount` and `compliance_posture`, landing in
    `BOND_DEFICIENT` where the resulting deficiency is greater than zero.

    Design: Difficulty/transitive_cascade/forfeiture_finalize_cascade_reaches_second_permit_bond_deficiency
    """
    operator, permit_a, permit_b = _highline_portfolio_at_the_brink()

    finalize_forfeiture(permit_a, state_reclamation_cost_estimate=1200000.00)

    # Link 3: the operator is disqualified because the permit became FORFEITED.
    disqualified = refresh_operator(operator["id"])
    assert disqualified["registry_status"] == "DISQUALIFIED"
    assert disqualified["self_bond_status"] == "DISQUALIFIED"
    assert disqualified["forfeiture_count"] == 1
    assert_money(disqualified["self_bond_capacity_amount"], 0.00, "self_bond_capacity_amount")

    # Link 4: the self bond elsewhere in the portfolio becomes a demand for
    # real collateral, and its permit's ledger loses that credit.
    instrument = refresh_instrument(permit_b["instrument"]["id"])
    assert instrument["status"] == "SUBSTITUTION_REQUIRED", (
        "SUBSTITUTION_REQUIRED is not terminal — a replacement may still be accepted"
    )
    assert_money(instrument["credited_amount"], 144700.00, "credited_amount")

    permit = refresh_permit(permit_b["permit"]["id"])
    assert_money(permit["bond_held_amount"], 0.00, "bond_held_amount")
    assert_money(permit["bond_required_amount"], 144700.00, "bond_required_amount")
    assert_money(permit["bond_deficiency_amount"], 144700.00, "bond_deficiency_amount")
    assert permit["compliance_posture"] == "BOND_DEFICIENT"
    assert permit["status"] == "ISSUED", "the second permit was never forfeited"


def test_the_priority_score_is_a_weighted_sum_of_hazard_scores_and_acreage():
    """Second, the score itself: add the hazard-band weight for the site's
    `hazard_class` — 50 for `H1_EXTREME`, 30 for `H2_HIGH`, and 15 for
    `H3_MODERATE` — plus `public_safety_score` multiplied by 0.30, plus
    `water_quality_score` multiplied by 0.20, plus the acreage component; round
    the sum half up to two decimals; and cap it at 100.00.

    Design: Corner/calculations/legacy_priority_score_weighted_scoring_correct_result
    """
    site = register_legacy_site(
        name="Cinder Hollow Legacy Workings", county="Fremont", total_acres=400.00
    )
    assert site["site_class"] == "ABANDONED_LEGACY"
    assert site["funding_status"] == "NOT_APPLICABLE", "nomination is admitted from here"

    nominated = nominate_legacy_site(
        site["id"], unfunded_reclamation_need=1200000.00, **HIGH_SCORING_NOMINATION
    )
    assert_mine_site(nominated)

    # 50 hazard + 80 x 0.30 = 24.00 + 60 x 0.20 = 12.00 + 90 x 0.05 = 4.50
    assert_money(nominated["legacy_priority_score"], 90.50, "legacy_priority_score")
    assert nominated["funding_status"] == "NOMINATED"
    assert nominated["site_class"] == "ABANDONED_LEGACY"
    assert_money(nominated["unfunded_reclamation_need"], 1200000.00,
                 "unfunded_reclamation_need")
    assert_money(nominated["awarded_funding_amount"], 0.00, "awarded_funding_amount")
    assert nominated["version"] == site["version"] + 1, "nomination is one mutation"


def test_the_acreage_component_and_the_score_are_both_capped():
    """First, the acreage component: multiply `acres_affected` by 0.05 points per
    acre, round half up to two decimals, and cap the result at 15 points — so
    twenty acres earn one point and any site beyond three hundred unreclaimed
    acres earns the same 15.

    Design: Corner/calculations/legacy_priority_score_acre_points_and_score_cap_applied
    """
    site = register_legacy_site(
        name="Sulphur Gulch Legacy Workings", county="Fremont", total_acres=900.00
    )

    nominated = nominate_legacy_site(
        site["id"],
        hazard_class="H1_EXTREME",
        public_safety_score=100,
        water_quality_score=100,
        acres_affected=300.00,
        unfunded_reclamation_need=9000000.00,
    )

    # Uncapped the sum would read 50 + 30.00 + 20.00 + 15 == 115.00.
    assert_money(nominated["legacy_priority_score"], 100.00, "legacy_priority_score")
    assert abs(nominated["legacy_priority_score"] - 115.00) > 0.005, (
        "a site whose raw components would exceed the cap simply reads 100.00"
    )
    assert nominated["funding_status"] == "NOMINATED"
    assert_money(nominated["acres_affected"], 300.00, "acres_affected")


def _two_nominated_sites(head_need, tail_need, head_name, tail_name, county):
    head = setup_nominated_legacy_site(
        site_overrides={"name": head_name, "county": county, "total_acres": 420.00},
        unfunded_reclamation_need=head_need,
        **HIGH_SCORING_NOMINATION,
    )
    tail = setup_nominated_legacy_site(
        site_overrides={"name": tail_name, "county": county, "total_acres": 520.00},
        unfunded_reclamation_need=tail_need,
        **MIDDLE_SCORING_NOMINATION,
    )
    assert_money(head["legacy_priority_score"], 90.50, "legacy_priority_score")
    # 30 hazard + 50 x 0.30 = 15.00 + 40 x 0.20 = 8.00 + min(200 x 0.05, 15) = 10.00
    assert_money(tail["legacy_priority_score"], 63.00, "legacy_priority_score")
    return head, tail


def test_awarding_money_out_of_queue_order_rejected():
    """At priority 14, the addressed site must be the current head of the funding
    queue as ordered above, else `ERR_FUNDING_QUEUE_ORDER` — the program cannot
    skip a higher-scoring site.

    Design: Corner/validations/legacy_funding_out_of_queue_order_rejected
    """
    head, tail = _two_nominated_sites(
        1200000.00, 800000.00,
        "Queue Head Legacy Workings", "Queue Tail Legacy Workings", "Lincoln",
    )

    response = api.award_legacy_funding(
        tail["id"], {"award_amount": 800000.00}, PROGRAM_DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_FUNDING_QUEUE_ORDER, 409)

    skipped = refresh_mine_site(tail["id"])
    assert skipped["funding_status"] == "NOMINATED", "the lower-scoring site waits"
    assert_money(skipped["awarded_funding_amount"], 0.00, "awarded_funding_amount")
    assert_money(skipped["unfunded_reclamation_need"], 800000.00,
                 "unfunded_reclamation_need")

    funded = validate_success(
        api.award_legacy_funding(
            head["id"], {"award_amount": 1200000.00}, PROGRAM_DIRECTOR
        )
    )
    assert funded["funding_status"] == "FUNDED", "the head of the queue is fundable"
    assert_money(funded["awarded_funding_amount"], 1200000.00, "awarded_funding_amount")
    assert_money(funded["unfunded_reclamation_need"], 0.00, "unfunded_reclamation_need")


def test_an_award_that_would_breach_the_annual_cap_rejected():
    """And at priority 15, the sum of `awarded_funding_amount` across all sites
    plus the new `award_amount`, rounded half up to two decimals, must not exceed
    the annual legacy fund cap of five million dollars (5000000.00), else
    `ERR_LEGACY_FUND_CAP_EXCEEDED`.

    Design: Corner/validations/legacy_fund_annual_cap_exceeded_rejected
    """
    head, tail = _two_nominated_sites(
        4800000.00, 300000.00,
        "Cap Test Head Workings", "Cap Test Tail Workings", "Uinta",
    )
    first = validate_success(
        api.award_legacy_funding(
            head["id"], {"award_amount": 4800000.00}, PROGRAM_DIRECTOR
        )
    )
    assert first["funding_status"] == "FUNDED"
    assert_money(first["awarded_funding_amount"], 4800000.00, "awarded_funding_amount")

    # 4800000.00 already committed plus 300000.00 requested totals 5100000.00,
    # even though each award on its own sits well inside the cap.
    response = api.award_legacy_funding(
        tail["id"], {"award_amount": 300000.00}, PROGRAM_DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_LEGACY_FUND_CAP_EXCEEDED, 409)

    refused = refresh_mine_site(tail["id"])
    assert refused["funding_status"] == "NOMINATED", (
        "the exhausted appropriation leaves the site in the queue"
    )
    assert_money(refused["awarded_funding_amount"], 0.00, "awarded_funding_amount")
    assert_money(refused["unfunded_reclamation_need"], 300000.00,
                 "unfunded_reclamation_need")


def test_the_funding_queue_is_ordered_by_score_and_drops_funded_sites():
    """That queue is exposed as its own read, returned in queue order rather than
    the creation order that governs every other list endpoint, and it accepts the
    standard `limit` and `offset` parameters.

    Design: Corner/endpoints/legacy_funding_queue_orders_by_score_then_need
    """
    # Registered low, high, middle, so creation order cannot masquerade as rank.
    low = setup_nominated_legacy_site(
        site_overrides={
            "name": "Ranked Workings Low", "county": "Fremont", "total_acres": 200.00,
        },
        unfunded_reclamation_need=200000.00,
        **LOW_SCORING_NOMINATION,
    )
    high = setup_nominated_legacy_site(
        site_overrides={
            "name": "Ranked Workings High", "county": "Fremont", "total_acres": 400.00,
        },
        unfunded_reclamation_need=1200000.00,
        **HIGH_SCORING_NOMINATION,
    )
    middle = setup_nominated_legacy_site(
        site_overrides={
            "name": "Ranked Workings Middle", "county": "Fremont", "total_acres": 500.00,
        },
        unfunded_reclamation_need=800000.00,
        **MIDDLE_SCORING_NOMINATION,
    )
    # 15 hazard + 20 x 0.30 = 6.00 + 10 x 0.20 = 2.00 + 50 x 0.05 = 2.50
    assert_money(low["legacy_priority_score"], 25.50, "legacy_priority_score")

    rows, meta = validate_paginated(
        api.list_legacy_funding_queue(PUBLIC_PARTICIPANT, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 3, "every NOMINATED legacy site is in the queue"
    assert [row["id"] for row in rows] == [high["id"], middle["id"], low["id"]], (
        "the queue is ordered by legacy_priority_score descending, not by created_at"
    )
    assert_money(rows[0]["legacy_priority_score"], 90.50, "head legacy_priority_score")

    validate_success(
        api.award_legacy_funding(
            high["id"], {"award_amount": 1200000.00}, PROGRAM_DIRECTOR
        )
    )

    rows, meta = validate_paginated(
        api.list_legacy_funding_queue(PROGRAM_DIRECTOR, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, "the funded site leaves the queue"
    assert rows[0]["id"] == middle["id"], "the next-highest site comes to the head"
    assert high["id"] not in [row["id"] for row in rows]
    assert refresh_mine_site(high["id"])["funding_status"] == "FUNDED"


def test_renominating_an_already_nominated_site_rejected():
    """Nomination moves the site `NOT_APPLICABLE → NOMINATED`, and is admitted
    only when the site's `funding_status` is `NOT_APPLICABLE` and its
    `site_class` is already `ABANDONED_LEGACY` — set either at registration or by
    the forfeiture-completion cascade of §3.7. A site failing either condition is
    refused with `ERR_SITE_FUNDING_STATE_INVALID`.

    Design: Corner/errors/renomination_of_already_nominated_site_rejected
    """
    site = register_legacy_site(
        name="Renominated Workings", county="Lander", total_acres=210.00
    )
    nominated = nominate_legacy_site(
        site["id"], unfunded_reclamation_need=200000.00, **LOW_SCORING_NOMINATION
    )
    assert_money(nominated["legacy_priority_score"], 25.50, "legacy_priority_score")

    response = api.nominate_legacy_site(
        site["id"],
        {
            "hazard_class": "H1_EXTREME",
            "public_safety_score": 90,
            "water_quality_score": 90,
            "acres_affected": 150.00,
            "unfunded_reclamation_need": 900000.00,
        },
        PROGRAM_DIRECTOR,
    )
    validate_error(response, ApiErrorId.ERR_SITE_FUNDING_STATE_INVALID, 409)

    unchanged = refresh_mine_site(site["id"])
    assert unchanged["hazard_class"] == "H3_MODERATE", "the second payload was discarded"
    assert_money(unchanged["legacy_priority_score"], 25.50, "legacy_priority_score")
    assert unchanged["funding_status"] == "NOMINATED"
    assert_money(unchanged["unfunded_reclamation_need"], 200000.00,
                 "unfunded_reclamation_need")
    assert unchanged["version"] == nominated["version"], "no version was consumed"


def _contest_window_scenario(operator_overrides, site_name, second_site_name=None):
    """An INITIATED proceeding on a bond-deficient permit, window open until 08-31."""
    ctx = chain_issued(
        operator_overrides=operator_overrides,
        site_overrides={"name": site_name, "county": "Yavapai", "total_acres": 400.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    revision = file_permit_revision(ctx, "EXPANSION", acreage_delta=60.00)
    validate_success(
        api.decide_permit_revision(
            revision["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    assert ctx["permit"]["compliance_posture"] == "BOND_DEFICIENT"

    initiate_forfeiture(ctx, "BOND_DEFICIENCY_UNCURED")
    if second_site_name:
        ctx["spare_site"] = register_mine_site(
            name=second_site_name, county="Yavapai", total_acres=260.00
        )
    return ctx


def test_the_contest_window_bounds_both_the_operator_and_the_state():
    """Finalisation is admitted only while the logical clock's current instant is
    strictly after `contest_deadline`; finalising while the window is still open
    is `ERR_CONTEST_WINDOW_OPEN` at priority 12, and the mirror-image of the
    contest rule means the exact boundary instant belongs to the operator, not
    the state.

    Design: Corner/errors/forfeiture_contest_window_boundary_rejections
    """
    ctx = _contest_window_scenario(CONTEST_WINDOW_OPERATOR, "Contest Window Pit")
    proceeding = ctx["proceeding"]
    assert proceeding["status"] == "INITIATED"
    assert proceeding["contest_deadline"].startswith("2026-08-31T00:00:00"), (
        f"thirty days after the 2026-08-01 clock, got {proceeding['contest_deadline']!r}"
    )
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "FORFEITURE_PENDING"

    early = api.finalize_forfeiture(
        proceeding["id"], {"state_reclamation_cost_estimate": 1200000.00}, PROGRAM_DIRECTOR
    )
    validate_error(early, ApiErrorId.ERR_CONTEST_WINDOW_OPEN, 409)

    second = api.create_forfeiture_proceeding(
        {"permit_id": ctx["permit"]["id"], "initiation_reason": "UNABATED_CESSATION"},
        PROGRAM_DIRECTOR,
    )
    validate_error(second, ApiErrorId.ERR_PERMIT_HAS_OPEN_PROCEEDING, 409)

    set_clock("2026-09-05T00:00:00Z")
    late = api.contest_forfeiture(
        proceeding["id"],
        {"contest_note": "We dispute the deficiency calculation."},
        ctx["operator_headers"],
    )
    validate_error(late, ApiErrorId.ERR_CONTEST_WINDOW_CLOSED, 409)

    unchanged = refresh_proceeding(proceeding["id"])
    assert unchanged["status"] == "INITIATED", "all three refusals changed nothing"
    assert unchanged["contest_note"] is None
    assert unchanged["finalized_at"] is None
    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["status"] == "ISSUED"
    assert permit["compliance_posture"] == "FORFEITURE_PENDING"
    _, meta = validate_paginated(
        api.list_permit_forfeiture_proceedings(ctx["permit"]["id"], PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 1, "only one proceeding may ever exist per permit"


def test_a_disqualified_operator_cannot_apply_and_a_final_file_cannot_be_contested():
    """`DISQUALIFIED` is terminal on both operator dimensions: a disqualified
    operator can no longer apply for permits, cannot have its financials
    replaced, and cannot be re-tested.

    Design: Corner/errors/disqualified_operator_and_finalized_proceeding_rejections
    """
    ctx = _contest_window_scenario(
        {
            "legal_name": "Disqualified After Forfeit Mining",
            "tangible_net_worth": 15900000.00,
            "fixed_assets_in_state": 7850000.00,
            "total_liabilities": 5110000.00,
            "net_income_prior_year": 630000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        "Forfeit Pit One",
        second_site_name="Forfeit Pit Two",
    )
    set_clock("2026-09-05T00:00:00Z")
    proceeding = finalize_forfeiture(ctx, state_reclamation_cost_estimate=1200000.00)
    assert proceeding["status"] == "FINAL"
    assert_money(proceeding["forfeited_bond_amount"], 900000.00, "forfeited_bond_amount")
    assert_money(proceeding["deficiency_amount"], 300000.00, "deficiency_amount")
    operator = refresh_operator(ctx["operator"]["id"])
    assert operator["registry_status"] == "DISQUALIFIED"
    assert operator["forfeiture_count"] == 1
    assert refresh_permit(ctx["permit"]["id"])["status"] == "FORFEITED"
    assert refresh_instrument(ctx["instrument"]["id"])["status"] == "FORFEITED"

    fresh_application = api.create_permit(
        create_permit_payload(
            ctx["spare_site"]["id"], ctx["operator"]["id"],
            mining_plan_acres=50.00,
            post_mining_land_use="CROPLAND",
            proposed_start_date="2026-10-01",
        ),
        ctx["operator_headers"],
    )
    validate_error(fresh_application, ApiErrorId.ERR_OPERATOR_DISQUALIFIED, 409)
    _, meta = validate_paginated(
        api.list_mine_site_permits(ctx["spare_site"]["id"], PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 0, "no permit was filed against the spare site"

    late_contest = api.contest_forfeiture(
        proceeding["id"],
        {"contest_note": "Contesting after the fact."},
        ctx["operator_headers"],
    )
    validate_error(late_contest, ApiErrorId.ERR_PROCEEDING_STATE_INVALID, 409)
    assert refresh_proceeding(proceeding["id"])["contest_note"] is None, (
        "own-state admissibility at priority 9 outranks the priority-12 window check"
    )
