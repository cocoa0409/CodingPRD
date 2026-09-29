"""Gates that read the state of another entity: legal clearance withdrawn by a
market-data refresh, say-on-pay certification blocked by a reopened CD&A section,
and award vesting blocked until every metric of the award's vehicle is certified.
"""

from test_helpers import (
    CHAIR,
    CONSULTANT,
    COUNSEL_ONE,
    COUNSEL_TWO,
    COUNSEL_TWO_HEADERS,
    ApiErrorId,
    api_client,
    assert_money,
    assert_program_pay_totals,
    assert_screen_stale_keeps_last_scores,
    assert_version_incremented,
    certify_metric,
    create_cda_draft,
    create_screen,
    file_cda_draft,
    legal_clear_cda_draft,
    read_award,
    read_cda_draft,
    read_metric,
    read_pay_program,
    read_screen,
    refresh_market_data,
    request_revision_payload,
    rerun_screen,
    setup_award,
    setup_disclosed_program,
    setup_pay_program,
    settlement_payload,
    submit_cda_review,
    submit_metric_result,
    validate_error,
    validate_success,
    vote_certification_payload,
)


# ---------------------------------------------------------------------------
# Fixtures built from scratch inside each test
# ---------------------------------------------------------------------------
def _cleared_section_over_a_granted_psu():
    """A LEGAL_CLEARED CD&A one call from filing, over a GRANTED PSU award.

    With no LONG_TERM_PSU metric defined the award has no certified factor, so
    its realizable value marks 100,000 units to the issuer's current 50.00 share
    price. The ISS screen is opened after the grant so it is SCREENED and current.
    """
    env = setup_pay_program()
    env = setup_award(env, label="psu", vehicle="LONG_TERM_PSU")
    env["screens"]["ISS"] = create_screen(env["program"]["id"], "ISS")
    draft = create_cda_draft(env["program"]["id"], "CD_AND_A", 2000, True, COUNSEL_ONE)
    submit_cda_review(draft["id"], COUNSEL_ONE)
    env["cda_draft"] = legal_clear_cda_draft(draft["id"], COUNSEL_TWO)
    return env


def _program_with_one_of_two_annual_metrics_certified():
    """Two ANNUAL_INCENTIVE metrics, one CERTIFIED and one only RESULT_SUBMITTED.

    ADJ_EPS (weight 60.00) achieves 5.50 and is certified at 150.00; COST_RATIO
    (weight 40.00) has 0.63 submitted but is never certified, so the award of
    that vehicle stays unfactored.
    """
    env = setup_pay_program(metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"))
    env = setup_award(env)
    submit_metric_result(env["metrics"][0]["id"], 5.50)
    certify_metric(env["metrics"][0]["id"])
    submit_metric_result(env["metrics"][1]["id"], 0.63)
    return env


# ===========================================================================
# A share-price refresh four hops away withdraws a legal clearance
# ===========================================================================
def test_share_price_refresh_stales_the_screen_and_reverts_legal_clearance():
    """A price tick on the issuer sends a cleared section back to drafting.

    "And because a legally cleared disclosure cannot rest on a withdrawn screen,
    a screen's move to `STALE` in turn sends every `LEGAL_CLEARED` section of
    that program back to `DRAFTING`, incrementing its `revision_round` and
    clearing its `cleared_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/market_data_refresh_invalidates_legal_clearance_through_screen_staleness
    """
    env = _cleared_section_over_a_granted_psu()
    program_id = env["program"]["id"]
    draft_id = env["cda_draft"]["id"]
    screen_id = env["screens"]["ISS"]["id"]

    assert env["cda_draft"]["status"] == "LEGAL_CLEARED"
    assert env["cda_draft"]["revision_round"] == 0
    assert env["cda_draft"]["cleared_by_user_id"] == COUNSEL_TWO
    screen_before = read_screen(program_id, screen_id)
    assert screen_before["status"] == "SCREENED"

    refresh_market_data(env["issuer"]["id"], share_price_usd=60.00)

    screen_after = read_screen(program_id, screen_id)
    assert_screen_stale_keeps_last_scores(screen_before, screen_after)

    draft_after = read_cda_draft(program_id, draft_id)
    assert draft_after["status"] == "DRAFTING"
    assert draft_after["revision_round"] == 1
    assert draft_after["cleared_by_user_id"] is None
    assert draft_after["filed_at"] is None

    program = read_pay_program(program_id)
    assert program["design_status"] == "COMMITTEE_APPROVED"


def test_share_price_refresh_remarks_the_granted_psu_and_the_program_total():
    """The price move rewrites the award's realizable value and the program total.

    "Fourth, independently of the peer-group chain, a changed share price
    re-marks every award of the issuer's programs that is still `GRANTED`,
    rewriting each award's `realizable_value_usd` and then each affected
    program's `realizable_pay_total_usd`."

    Design: Difficulty/cross_entity_state_dependency/market_data_refresh_invalidates_legal_clearance_through_screen_staleness
    """
    env = _cleared_section_over_a_granted_psu()
    award_id = env["awards"]["psu"]["id"]

    award_before = read_award(award_id)
    assert award_before["status"] == "GRANTED"
    assert award_before["certified_factor_pct"] is None
    assert_money(award_before["realizable_value_usd"], 5000000.00, "realizable_value_usd")
    assert_money(award_before["realized_value_usd"], 0.00, "realized_value_usd")

    company = refresh_market_data(env["issuer"]["id"], share_price_usd=60.00)
    assert_money(company["share_price_usd"], 60.00, "share_price_usd")
    assert company["market_data_updated_at"].startswith("2026-08-01T00:00:00")

    award_after = read_award(award_id)
    assert_money(award_after["realizable_value_usd"], 6000000.00, "realizable_value_usd")
    assert_money(award_after["realized_value_usd"], 0.00, "realized_value_usd")
    assert_version_incremented(award_after["version"], award_before["version"])

    program = read_pay_program(env["program"]["id"])
    assert_program_pay_totals(program, 0.00, 6000000.00)


def test_filing_is_refused_until_the_reverted_section_is_cleared_again():
    """Filing needs LEGAL_CLEARED, and re-running the screen alone does not restore it.

    "Filing, also a `SecuritiesCounsel` operation, moves a section
    `LEGAL_CLEARED → FILED` — any other state is `ERR_CDA_STATE_INVALID` —
    stamps `filed_at` with the current logical time and increments the section's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/market_data_refresh_invalidates_legal_clearance_through_screen_staleness
    """
    env = _cleared_section_over_a_granted_psu()
    program_id = env["program"]["id"]
    draft_id = env["cda_draft"]["id"]
    screen_id = env["screens"]["ISS"]["id"]

    refresh_market_data(env["issuer"]["id"], share_price_usd=60.00)

    validate_error(
        api_client.file_cda_draft(draft_id, COUNSEL_TWO_HEADERS),
        ApiErrorId.ERR_CDA_STATE_INVALID,
        409,
    )

    refreshed_screen = rerun_screen(screen_id)
    assert refreshed_screen["status"] == "SCREENED"
    assert read_cda_draft(program_id, draft_id)["status"] == "DRAFTING"
    validate_error(
        api_client.file_cda_draft(draft_id, COUNSEL_TWO_HEADERS),
        ApiErrorId.ERR_CDA_STATE_INVALID,
        409,
    )

    submit_cda_review(draft_id, COUNSEL_ONE)
    legal_clear_cda_draft(draft_id, COUNSEL_TWO)
    filed = file_cda_draft(draft_id, COUNSEL_TWO)
    assert filed["status"] == "FILED"
    assert filed["filed_at"] is not None
    assert read_pay_program(program_id)["design_status"] == "DISCLOSED"


# ===========================================================================
# A reopened CD&A blocks the vote even though the program stays DISCLOSED
# ===========================================================================
def test_vote_certification_refused_while_the_reopened_cda_is_unfiled():
    """The program is still DISCLOSED, yet the CD&A section is no longer filed.

    "And the program's `CD_AND_A` section must exist and be in `FILED`, or the
    answer is `ERR_CDA_NOT_FILED`."

    Design: Difficulty/cross_entity_state_dependency/vote_certification_blocked_while_reopened_cda_awaits_refiling
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    draft_id = env["cda_draft"]["id"]
    assert env["program"]["design_status"] == "DISCLOSED"

    reopened = validate_success(
        api_client.request_cda_revision(
            draft_id,
            CHAIR,
            request_revision_payload("Amended proxy: the pay-ratio table must be restated."),
        ),
        200,
    )
    assert reopened["status"] == "DRAFTING"
    assert reopened["revision_round"] == 1
    assert reopened["filed_at"] is None
    assert reopened["cleared_by_user_id"] is None

    response = api_client.certify_vote(
        program_id,
        vote_certification_payload(800000, 200000, 0),
        CHAIR,
    )
    validate_error(response, ApiErrorId.ERR_CDA_NOT_FILED, 409)

    program = read_pay_program(program_id)
    assert program["design_status"] == "DISCLOSED"
    assert program["vote_status"] == "NOT_VOTED"
    assert program.get("support_pct") is None


def test_reopening_the_cda_leaves_the_program_disclosed():
    """The amended-proxy reopening does not un-disclose the program.

    "Reopening the `CD_AND_A` section leaves the program at `design_status`
    `DISCLOSED` — the program does not un-disclose — but it does make
    `ERR_CDA_NOT_FILED` reachable on vote certification until that section has
    been cleared and filed again."

    Design: Difficulty/cross_entity_state_dependency/vote_certification_blocked_while_reopened_cda_awaits_refiling
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    draft_id = env["cda_draft"]["id"]

    validate_success(
        api_client.request_cda_revision(
            draft_id,
            CHAIR,
            request_revision_payload("Amended proxy: the pay-ratio table must be restated."),
        ),
        200,
    )
    assert read_pay_program(program_id)["design_status"] == "DISCLOSED"

    submit_cda_review(draft_id, COUNSEL_ONE)
    legal_clear_cda_draft(draft_id, COUNSEL_TWO)
    refiled = file_cda_draft(draft_id, COUNSEL_TWO)
    assert refiled["status"] == "FILED"

    certified = validate_success(
        api_client.certify_vote(
            program_id,
            vote_certification_payload(800000, 200000, 0),
            CHAIR,
        ),
        200,
    )
    assert_money(certified["support_pct"], 80.00, "support_pct")
    assert certified["vote_status"] == "PASSED"
    assert certified["enhanced_engagement_required"] is False
    assert certified["design_status"] == "CLOSED"


def test_reopening_is_refused_once_the_vote_has_been_certified():
    """After certification the amended-proxy path is closed off.

    "Reopening is only permitted while the program's `vote_status` is still
    `NOT_VOTED`; after certification the answer is `ERR_VOTE_ALREADY_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/vote_certification_blocked_while_reopened_cda_awaits_refiling
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    draft_id = env["cda_draft"]["id"]

    certified = validate_success(
        api_client.certify_vote(
            program_id,
            vote_certification_payload(800000, 200000, 0),
            CHAIR,
        ),
        200,
    )
    assert certified["vote_status"] == "PASSED"

    response = api_client.request_cda_revision(
        draft_id,
        CHAIR,
        request_revision_payload("Amended proxy: the pay-ratio table must be restated."),
    )
    validate_error(response, ApiErrorId.ERR_VOTE_ALREADY_CERTIFIED, 409)

    draft = read_cda_draft(program_id, draft_id)
    assert draft["status"] == "FILED"
    assert draft["revision_round"] == 0


# ===========================================================================
# Vesting waits on a universal quantifier over the vehicle's metrics
# ===========================================================================
def test_vesting_refused_while_one_metric_of_the_vehicle_is_uncertified():
    """One certified metric out of two leaves the award unfactored and unvestable.

    "The `VEST` branch carries a cross-entity precondition the `FORFEIT` branch
    does not: for the `ANNUAL_INCENTIVE` and `LONG_TERM_PSU` vehicles the award's
    `certified_factor_pct` must already be non-null, meaning every metric of that
    vehicle has been certified, and vesting without it is refused with
    `ERR_METRIC_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/psu_vesting_blocked_until_every_metric_of_the_vehicle_is_certified
    """
    env = _program_with_one_of_two_annual_metrics_certified()
    program_id = env["program"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]

    response = api_client.settle_payout_award(
        award_id, settlement_payload("VEST", "2026-09-30T00:00:00Z"), CONSULTANT
    )
    validate_error(response, ApiErrorId.ERR_METRIC_NOT_CERTIFIED, 409)

    award = read_award(award_id)
    assert award["status"] == "GRANTED"
    assert award["settlement_date"] is None
    assert award["vest_price_usd"] is None
    assert award["certified_factor_pct"] is None
    assert award["earned_amount_usd"] is None
    assert_money(award["realized_value_usd"], 0.00, "realized_value_usd")
    assert_money(award["realizable_value_usd"], 1800000.00, "realizable_value_usd")

    assert read_metric(program_id, env["metrics"][0]["id"])["status"] == "CERTIFIED"
    assert read_metric(program_id, env["metrics"][1]["id"])["status"] == "RESULT_SUBMITTED"


def test_vesting_succeeds_once_the_second_metric_is_certified():
    """Completing the vehicle's certifications populates the factor and lets it vest.

    "If the set is non-empty but not every member of it is in `CERTIFIED` or
    `RESTATED`, the factor is likewise null and the computation stops."

    Design: Difficulty/cross_entity_state_dependency/psu_vesting_blocked_until_every_metric_of_the_vehicle_is_certified
    """
    env = _program_with_one_of_two_annual_metrics_certified()
    award_id = env["awards"]["annual_incentive"]["id"]
    assert read_award(award_id)["certified_factor_pct"] is None

    certify_metric(env["metrics"][1]["id"])

    factored = read_award(award_id)
    assert_money(factored["certified_factor_pct"], 130.00, "certified_factor_pct")
    assert_money(factored["earned_amount_usd"], 2340000.00, "earned_amount_usd")

    settled = validate_success(
        api_client.settle_payout_award(
            award_id, settlement_payload("VEST", "2026-09-30T00:00:00Z"), CONSULTANT
        ),
        200,
    )
    assert settled["status"] == "VESTED"
    assert settled["settlement_date"].startswith("2026-09-30T00:00:00")
    assert_money(settled["vest_price_usd"], 50.00, "vest_price_usd")
    assert_money(settled["certified_factor_pct"], 130.00, "certified_factor_pct")
    assert_money(settled["earned_amount_usd"], 2340000.00, "earned_amount_usd")
    assert_money(settled["realized_value_usd"], 2340000.00, "realized_value_usd")


def test_forfeiting_the_unfactored_award_is_not_blocked_by_the_certification_gate():
    """The FORFEIT branch carries no certification precondition at all.

    "Forfeiting moves the award `GRANTED → FORFEITED` with no certification
    requirement whatsoever — the divergent precondition set is precisely what
    distinguishes the two branches — stamps `settlement_date` with the current
    logical time, zeroes both `realized_value_usd` and `realizable_value_usd`,
    and increments the award's `version`."

    Design: Difficulty/cross_entity_state_dependency/psu_vesting_blocked_until_every_metric_of_the_vehicle_is_certified
    """
    env = _program_with_one_of_two_annual_metrics_certified()
    award_id = env["awards"]["annual_incentive"]["id"]
    granted = read_award(award_id)
    assert granted["certified_factor_pct"] is None

    forfeited = validate_success(
        api_client.settle_payout_award(
            award_id, settlement_payload("FORFEIT", "2026-09-30T00:00:00Z"), CONSULTANT
        ),
        200,
    )
    assert forfeited["status"] == "FORFEITED"
    assert_money(forfeited["realized_value_usd"], 0.00, "realized_value_usd")
    assert_money(forfeited["realizable_value_usd"], 0.00, "realizable_value_usd")
    assert forfeited["settlement_date"] is not None
    assert_version_incremented(forfeited["version"], granted["version"])

    program = read_pay_program(env["program"]["id"])
    assert_program_pay_totals(program, 0.00, 0.00)
