"""
Queue B — §1.9 section ``validations``.

The validation ladder of PRD §2.10 exercised where it bites: paired inputs
checked together rather than singly, inclusive comparisons at their exact
boundary, checks enforced at one endpoint rather than another, the single
shape-violation error standing in for five different malformations, and four
priority conflicts where two rules both apply and only the earlier may answer.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_AUTHORIZED_AMOUNT_EXCEEDED,
    ERR_BOARD_QUORUM_NOT_MET,
    ERR_BYLAWS_CAP_EXCEEDED,
    ERR_COLLATERAL_ALREADY_ASSIGNED,
    ERR_COLLATERAL_APPRAISAL_STALE,
    ERR_COVENANT_INVALID_STATE,
    ERR_DRAW_NET_NONPOSITIVE,
    ERR_ENDOWMENT_COLLATERAL_INELIGIBLE,
    ERR_FORGIVENESS_EXCEEDS_OUTSTANDING,
    ERR_GOVERNANCE_AUTHORIZATION_EXPIRED,
    ERR_INVALID_REQUEST,
    ERR_LTV_COVERAGE_INSUFFICIENT,
    ERR_MISSION_IMPACT_SCORE_TOO_LOW,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_PLEDGE_CAMPAIGN_REQUIRED,
    ERR_PREDECESSOR_WORKOUT_INVALID,
    ERR_RESTRICTED_EXCEEDS_TOTAL,
)
from test_helpers.assertions import (
    assert_fields,
    assert_iso_equal,
    assert_loan_ledger,
    assert_nulls,
    assert_pagination_meta,
    assert_ratio,
    assert_score,
)
from test_helpers.factories import (
    REFERENCE_AUDITED_QUARTERS,
    assignment_payload,
    board_verification_payload,
    covenant_test_payload,
    cure_payload,
    draw_approval_payload,
    draw_disbursement_payload,
    draw_request_payload,
    forgiveness_payload,
    giving_period_payload,
    installment_payload,
    loan_payment_payload,
    pledge_payload,
    release_payload,
    submit_underwriting_payload,
    waiver_payload,
    workout_approval_payload,
    workout_plan_payload,
)
from test_helpers.fixtures import (
    assign_asset,
    build_authorized_authorization,
    build_collateral_asset,
    build_covenant,
    build_draft_application,
    build_draft_authorization,
    build_giving_periods,
    build_institution,
    build_pledge,
    build_pledge_campaign,
    build_submitted_authorization,
    chain_through_loan,
    refer_to_committee,
    render_committee_decision,
    reset_clock,
    set_clock,
    submit_to_underwriting,
)
from test_helpers.test_users import (
    ANALYST_1,
    COMMITTEE_MEMBER,
    CREDIT_ANALYST,
    GOVERNANCE_OFFICER,
    LOAN_SERVICER,
    make_institution_representative_headers,
)

# The reference borrower: a 500000000 bylaws cap, a two-thirds quorum threshold
# and no denominational overlay, so a board verification lands on AUTHORIZED.
BORROWER = {
    "requires_denominational_approval": False,
    "bylaws_borrowing_cap_cents": 500000000,
    "bylaws_quorum_pct": 0.6667,
    "community_program_count": 3,
    "endowment_market_value_cents": None,
}


def test_the_two_restricted_buckets_are_tested_against_the_total_together(api):
    """
    Neither 50000000 of restricted gifts nor a 15000000 endowment draw exceeds the
    60000000 total on its own, but their sum does, and the pair is what the rule
    tests; at a sum exactly equal to the total the period is accepted and nets zero.

    PRD §3.1: "A period whose restricted contributions and donor-restricted endowment draw sum to more than its total contributions is refused with `ERR_RESTRICTED_EXCEEDS_TOTAL`."
    PRD §2.10: "Restricted contributions and the donor-restricted endowment draw together do not exceed total contributions — `ERR_RESTRICTED_EXCEEDS_TOTAL` (HTTP 422), on giving-period creation."
    PRD §3.1: "`unrestricted_contributions_cents` is total contributions reduced by restricted contributions and reduced again by the donor-restricted endowment draw, with the result floored at zero if those two deductions together would exceed the total."
    PRD §3.1: "Filing a period also reconciles its institution."

    Design: Corner/validations/restricted_plus_endowment_draw_above_total_contributions_is_rejected
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    over_total = giving_period_payload(
        institution["id"],
        period_label="2025Q1",
        source="AUDITED",
        total_contributions_cents=60000000,
        restricted_contributions_cents=50000000,
        donor_restricted_endowment_draw_cents=15000000,
        operating_expense_cents=30000000,
        member_household_count=500,
    )

    validate_error(
        api.create_giving_period(over_total, CREDIT_ANALYST),
        ERR_RESTRICTED_EXCEEDS_TOTAL,
        422,
    )

    # Nothing was filed, so the institution's derived figures are untouched.
    assert_fields(
        get_success_data(api.get_institution(institution["id"], CREDIT_ANALYST)),
        period_count=0,
        audited_period_count=0,
        unrestricted_giving_base_cents=0,
        net_available_for_debt_service_dollars=0,
    )

    # 50000000 + 10000000 is exactly the total: the deductions may consume it all.
    at_the_total = dict(over_total, donor_restricted_endowment_draw_cents=10000000)
    period = get_success_data(api.create_giving_period(at_the_total, CREDIT_ANALYST), 201)
    assert_fields(
        period,
        total_contributions_cents=60000000,
        restricted_contributions_cents=50000000,
        donor_restricted_endowment_draw_cents=10000000,
        unrestricted_contributions_cents=0,
        # 0 unrestricted less 30000000 of operating expense, floored at zero.
        net_available_for_debt_service_cents=0,
    )
    assert_fields(
        get_success_data(api.get_institution(institution["id"], CREDIT_ANALYST)),
        period_count=1,
        audited_period_count=1,
    )


def test_board_quorum_passes_exactly_at_the_bylaws_fraction_and_fails_below_it(api):
    """
    Eight votes of twelve rounds to 0.6667, which equals the bylaws threshold and
    verifies; seven of twelve rounds to 0.5833 and is refused, and the refused
    packet keeps its null quorum.

    PRD §3.2: "The officer's job is arithmetic: the achieved quorum is `board_votes_for` divided by `board_votes_total`, rounded half up to four decimal places, and it must be greater than or equal to the institution's `bylaws_quorum_pct`."
    PRD §3.2: "A tally that falls short is refused with `ERR_BOARD_QUORUM_NOT_MET`; a tally exactly equal to the required fraction passes."
    PRD §3.2: "Where it is false, the very same act moves the packet `SUBMITTED → AUTHORIZED` outright, and the packet is immediately usable for a referral."
    PRD §3.2: "On success the computed quorum is stored as `board_quorum_pct`, `verified_by_user_id` is set to the acting `X-User-ID`, and `version` advances by 1."

    Design: Corner/validations/board_quorum_exactly_at_the_bylaws_threshold_passes_while_below_is_rejected
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    at_threshold = build_submitted_authorization(
        api, institution["id"], board_votes_for=8, board_votes_total=12
    )
    below_threshold = build_submitted_authorization(
        api,
        institution["id"],
        resolution_date="2026-06-20T00:00:00Z",
        board_votes_for=7,
        board_votes_total=12,
        authorized_amount_cents=100000000,
    )

    verified = get_success_data(
        api.board_verify_governance_authorization(
            at_threshold["id"], board_verification_payload(), GOVERNANCE_OFFICER
        )
    )
    assert_fields(verified, status="AUTHORIZED")
    assert_ratio(verified["board_quorum_pct"], 0.6667, "board_quorum_pct")

    validate_error(
        api.board_verify_governance_authorization(
            below_threshold["id"],
            board_verification_payload(minutes_reference="MIN-2026-06-20"),
            GOVERNANCE_OFFICER,
        ),
        ERR_BOARD_QUORUM_NOT_MET,
        422,
    )

    # The failed check writes nothing: no quorum, no verifier, no transition.
    stuck = get_success_data(
        api.get_governance_authorization(below_threshold["id"], GOVERNANCE_OFFICER)
    )
    assert_fields(stuck, status="SUBMITTED")
    assert_nulls(stuck, "board_quorum_pct", "verified_by_user_id")


def test_the_bylaws_cap_is_enforced_at_submission_rather_than_at_creation(api):
    """
    A resolution authorising 600000000 against a 500000000 cap is created happily and
    only the submission is refused, leaving the packet in DRAFT until the board
    re-votes a smaller amount.

    PRD §3.2: "A new packet opens in `DRAFT` with `revision_round` at 0, and with `denominational_decision_note`, `verified_by_user_id` and `board_quorum_pct` all null."
    PRD §3.2: "The one substantive check is fiscal: a resolution authorising more than the bylaws permit — an `authorized_amount_cents` exceeding the institution's `bylaws_borrowing_cap_cents` — is refused with `ERR_BYLAWS_CAP_EXCEEDED`."
    PRD §2.10: "The amount under review does not exceed the institution's bylaws borrowing cap — `ERR_BYLAWS_CAP_EXCEEDED` (HTTP 422), on packet submission, where the amount tested is `authorized_amount_cents`, and on submit-underwriting, where it is `requested_amount_cents`."

    Design: Corner/validations/resolution_authorizing_more_than_the_bylaws_cap_is_rejected_at_submit
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)

    packet = build_draft_authorization(
        api,
        institution["id"],
        board_votes_for=12,
        board_votes_total=12,
        authorized_amount_cents=600000000,
    )
    assert_fields(packet, authorized_amount_cents=600000000, status="DRAFT", revision_round=0)

    validate_error(
        api.submit_governance_authorization(
            packet["id"], {}, make_institution_representative_headers(institution["id"])
        ),
        ERR_BYLAWS_CAP_EXCEEDED,
        422,
    )

    unchanged = get_success_data(
        api.get_governance_authorization(packet["id"], GOVERNANCE_OFFICER)
    )
    assert_fields(unchanged, status="DRAFT", authorized_amount_cents=600000000)
    assert_nulls(unchanged, "board_quorum_pct", "verified_by_user_id")


def test_five_different_shape_violations_all_answer_with_the_one_schema_error(api):
    """
    A zero-length period interval, a non-advancing lien window, a MISSED installment
    carrying money, a PAID installment carrying none and a negative pledge amount are
    five structurally different malformations that all resolve to the single schema
    error rather than to any domain-specific one, and none of them writes anything.

    PRD §2.10: "The request body conforms to the endpoint's input schema — `ERR_INVALID_REQUEST` (HTTP 422), on every write endpoint. This covers a missing required field, an enum value outside its declared set, a negative cent amount (or a non-positive one where §3 requires strict positivity), a `percent_complete` outside the range above 0 and at or below 1, a `period_end` at or before `period_start`, a `lien_effective_to` at or before `lien_effective_from`, an installment whose `outcome` is `MISSED` with a non-zero `amount_cents` or whose `outcome` is `PAID` with an `amount_cents` of zero or less, a `decision` outside its allowed set, a workout option missing its option-specific field, and a construction completion whose `final_inspection_passed` is not true."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"

    Design: Corner/validations/malformed_bodies_across_write_endpoints_return_invalid_request
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    packet = build_draft_authorization(api, institution["id"])
    application = build_draft_application(
        api,
        institution["id"],
        packet["id"],
        purpose="SCHOOL_CONSTRUCTION",
        requested_amount_cents=100000000,
        term_months=180,
        interest_rate_bps=600,
    )
    asset = build_collateral_asset(
        api,
        institution["id"],
        asset_type="EDUCATION_WING",
        description_label="East education wing",
        appraised_value_cents=200000000,
        appraisal_date="2026-05-01T00:00:00Z",
        alternative_use_score=3,
    )
    campaign = build_pledge_campaign(
        api,
        institution["id"],
        campaign_name="Building For Generations",
        goal_cents=120000000,
        pledge_period_months=36,
        sponsor_collection_rate_bps=9500,
    )
    pledge = build_pledge(
        api,
        campaign["id"],
        donor_tier="MAJOR",
        pledged_amount_cents=20000000,
        installment_count=24,
    )
    campaign_version = get_success_data(
        api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST)
    )["version"]

    malformed = [
        # period_end at or before period_start
        api.create_giving_period(
            giving_period_payload(
                institution["id"],
                period_label="BAD",
                period_start="2025-03-31T00:00:00Z",
                period_end="2025-03-31T00:00:00Z",
                total_contributions_cents=1000000,
                restricted_contributions_cents=0,
                donor_restricted_endowment_draw_cents=0,
                operating_expense_cents=500000,
                member_household_count=100,
            ),
            CREDIT_ANALYST,
        ),
        # lien_effective_to at or before lien_effective_from
        api.assign_collateral_asset(
            asset["id"],
            assignment_payload(
                application["id"],
                lien_effective_from="2026-08-01T00:00:00Z",
                lien_effective_to="2026-08-01T00:00:00Z",
            ),
            CREDIT_ANALYST,
        ),
        # MISSED carrying a non-zero amount
        api.record_pledge_payment(
            pledge["id"], installment_payload(1, "MISSED", 500000), LOAN_SERVICER
        ),
        # PAID carrying nothing
        api.record_pledge_payment(
            pledge["id"], installment_payload(1, "PAID", 0), LOAN_SERVICER
        ),
        # a negative cent amount
        api.create_pledge(
            pledge_payload(
                campaign["id"],
                campaign_version,
                donor_tier="LEAD",
                pledged_amount_cents=-5000000,
                installment_count=12,
            ),
            CREDIT_ANALYST,
        ),
    ]
    for response in malformed:
        validate_error(response, ERR_INVALID_REQUEST, 422)
        assert response.json()["response_type"] == "error"

    assert_fields(
        get_success_data(api.get_institution(institution["id"], CREDIT_ANALYST)),
        period_count=0,
    )
    assert_nulls(
        get_success_data(api.get_collateral_asset(asset["id"], CREDIT_ANALYST)),
        "assigned_loan_application_id",
        "lien_position",
    )
    assert_fields(
        get_success_data(api.get_pledge(pledge["id"], CREDIT_ANALYST)),
        status="ACTIVE",
        collected_cents=0,
        payments_made_count=0,
        missed_payments_count=0,
    )


def test_a_pledge_advance_cannot_leave_underwriting_without_naming_its_campaign(api):
    """
    Two PLEDGE_ADVANCE applications differ only in whether they name a backing
    campaign: both were created happily, but only the one naming a campaign can be
    submitted for underwriting.

    PRD §3.5: "And an application whose `purpose` is `PLEDGE_ADVANCE` must name a `pledge_campaign_id`, or the request is refused with `ERR_PLEDGE_CAMPAIGN_REQUIRED`."
    PRD §2.10: "A `PLEDGE_ADVANCE` application names a backing campaign — `ERR_PLEDGE_CAMPAIGN_REQUIRED` (HTTP 422), on submit-underwriting."
    PRD §3.5: "On success the analyst's own figures are frozen onto the application."
    PRD §3.5: "The mandated basis is resolved exactly as in §3.1 — `AUDITED_ONLY` when the institution's `audited_period_count` is 4 or more, `BLENDED` otherwise — and stored as `giving_basis`."
    PRD §3.5: "`prepared_by_user_id` is set to the acting `X-User-ID`, `revision_reason` is cleared to null, and `version` advances by 1."

    Design: Corner/validations/pledge_advance_without_a_campaign_is_rejected_at_submit_underwriting
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    build_giving_periods(api, institution["id"], REFERENCE_AUDITED_QUARTERS)
    packet = build_draft_authorization(api, institution["id"])
    campaign = build_pledge_campaign(
        api,
        institution["id"],
        campaign_name="Building For Generations",
        goal_cents=120000000,
        pledge_period_months=36,
        sponsor_collection_rate_bps=9500,
    )
    bare = build_draft_application(
        api,
        institution["id"],
        packet["id"],
        purpose="PLEDGE_ADVANCE",
        requested_amount_cents=60000000,
        term_months=120,
        interest_rate_bps=700,
    )
    linked = build_draft_application(
        api,
        institution["id"],
        packet["id"],
        pledge_campaign_id=campaign["id"],
        purpose="PLEDGE_ADVANCE",
        requested_amount_cents=60000000,
        term_months=120,
        interest_rate_bps=700,
    )

    validate_error(
        api.submit_underwriting(
            bare["id"],
            submit_underwriting_payload(analyst_note="Campaign paperwork still pending"),
            CREDIT_ANALYST,
        ),
        ERR_PLEDGE_CAMPAIGN_REQUIRED,
        422,
    )
    refused = get_success_data(api.get_loan_application(bare["id"], CREDIT_ANALYST))
    assert_fields(refused, status="DRAFT")
    assert_nulls(refused, "giving_basis", "giving_base_cents", "prepared_by_user_id")

    accepted = get_success_data(
        api.submit_underwriting(
            linked["id"],
            submit_underwriting_payload(analyst_note="Campaign named"),
            CREDIT_ANALYST,
        )
    )
    assert_fields(
        accepted,
        status="UNDERWRITING",
        giving_basis="AUDITED_ONLY",
        giving_base_cents=207000000,
        net_available_dollars=432001,
        prepared_by_user_id=ANALYST_1,
    )


def test_an_endowment_asset_answers_its_own_error_even_when_it_is_also_stale(api):
    """
    An asset that is both a donor-restricted endowment and 731 days stale answers the
    endowment error, because that check stands earlier in the ladder; an identically
    stale sanctuary answers the staleness error, and one day younger — exactly at the
    limit — it assigns.

    PRD §2.10: "The asset's `asset_type` is not `DONOR_RESTRICTED_ENDOWMENT` — `ERR_ENDOWMENT_COLLATERAL_INELIGIBLE` (HTTP 422), on a collateral assignment."
    PRD §2.10: "The asset's `appraisal_age_days` is at most 730 — `ERR_COLLATERAL_APPRAISAL_STALE` (HTTP 422), on a collateral assignment."
    PRD §2.10: "Validations are evaluated in the ascending order set out below; the **first** rule that a request violates determines the single error the response carries, and no later rule can mask an earlier one."
    PRD §3.4: "An asset whose `appraisal_age_days` exceeds 730 — two years of staleness — is refused with `ERR_COLLATERAL_APPRAISAL_STALE`; at exactly 730 days it is still acceptable."
    PRD §3.4: "A successful assignment sets `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and `lien_effective_to`, re-runs the lending-value computation with the assigned lien factor now in force — so pledging an asset in second position immediately cuts its recorded `lending_value_cents` by 40 percent — rewrites `lending_value_cents`, and advances the asset's `version` by 1."

    Design: Corner/validations/endowment_ineligibility_outranks_the_stale_appraisal_check
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    packet = build_draft_authorization(api, institution["id"])
    application = build_draft_application(
        api,
        institution["id"],
        packet["id"],
        requested_amount_cents=200000000,
    )
    endowment = build_collateral_asset(
        api,
        institution["id"],
        asset_type="DONOR_RESTRICTED_ENDOWMENT",
        description_label="Hargrove memorial endowment fund",
        appraised_value_cents=900000000,
        appraisal_date="2024-07-31T00:00:00Z",
        alternative_use_score=5,
    )
    stale = build_collateral_asset(
        api,
        institution["id"],
        description_label="Old chapel",
        appraisal_date="2024-07-31T00:00:00Z",
    )
    at_the_limit = build_collateral_asset(
        api,
        institution["id"],
        appraisal_date="2024-08-01T00:00:00Z",
    )
    assert_fields(endowment, appraisal_age_days=731)
    assert_fields(stale, appraisal_age_days=731)

    # Both flaws are present on the endowment; only the earlier one may answer.
    validate_error(
        api.assign_collateral_asset(
            endowment["id"], assignment_payload(application["id"]), CREDIT_ANALYST
        ),
        ERR_ENDOWMENT_COLLATERAL_INELIGIBLE,
        422,
    )
    validate_error(
        api.assign_collateral_asset(
            stale["id"], assignment_payload(application["id"]), CREDIT_ANALYST
        ),
        ERR_COLLATERAL_APPRAISAL_STALE,
        422,
    )

    assigned = get_success_data(
        api.assign_collateral_asset(
            at_the_limit["id"], assignment_payload(application["id"]), CREDIT_ANALYST
        )
    )
    assert_fields(
        assigned,
        appraisal_age_days=730,
        lien_position=1,
        assigned_loan_application_id=application["id"],
        # floor(500000000 * min(0.50, 0.55)) == 250000000, first lien, then the
        # seasoning haircut at 730 days: floor(250000000 * 0.90).
        lending_value_cents=225000000,
    )

    rows, meta = validate_paginated(
        api.list_collateral_assets(
            CREDIT_ANALYST, {"assigned_loan_application_id": application["id"]}
        )
    )
    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [at_the_limit["id"]]


def test_one_rule_answers_both_a_double_assignment_and_a_double_release(api):
    """
    Assigning an asset that already holds a lien and releasing one that holds none are
    opposite mistakes answered by the same rule, with the successful release in
    between appending exactly one history record and re-valuing the freed asset.

    PRD §2.10: "The asset is unassigned for an assignment and assigned for a release — `ERR_COLLATERAL_ALREADY_ASSIGNED` (HTTP 409), on both collateral actions."
    PRD §3.4: "An asset whose `assigned_loan_application_id` is already populated is refused with `ERR_COLLATERAL_ALREADY_ASSIGNED`."
    PRD §3.4: "Releasing a lien, also a `CreditAnalyst` act, takes a `release_note` and requires that the asset currently hold one; releasing an unassigned asset is refused with `ERR_COLLATERAL_ALREADY_ASSIGNED`."
    PRD §3.4: "The release appends the occupation just ended to `lien_history` as a record carrying `loan_application_id`, `lien_position`, `effective_from`, `effective_to` and `released_at`, with the list held in ascending `released_at` order and never rewritten once appended."
    PRD §3.4: "The four current-occupation fields are cleared to null, the asset is re-valued at the first-lien factor, `lending_value_cents` is rewritten, and `version` advances by 1."

    Design: Corner/validations/collateral_already_assigned_guard_fires_in_both_directions
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    packet = build_draft_authorization(api, institution["id"])
    first = build_draft_application(
        api, institution["id"], packet["id"], requested_amount_cents=200000000
    )
    second = build_draft_application(
        api,
        institution["id"],
        packet["id"],
        purpose="REFINANCE",
        requested_amount_cents=100000000,
        term_months=180,
        interest_rate_bps=650,
    )
    asset = build_collateral_asset(api, institution["id"])
    assign_asset(api, asset["id"], first["id"])

    # Even a lower lien position cannot be layered onto an occupied asset. The
    # proposed window opens after the live occupation's end plus the 30-day
    # release buffer (2031-08-01 + 30d = 2031-08-31), so ladder position 37
    # is clear and position 40 is the first rule the request violates.
    validate_error(
        api.assign_collateral_asset(
            asset["id"],
            assignment_payload(
                second["id"],
                lien_position=2,
                lien_effective_from="2031-09-01T00:00:00Z",
                lien_effective_to="2035-09-01T00:00:00Z",
            ),
            CREDIT_ANALYST,
        ),
        ERR_COLLATERAL_ALREADY_ASSIGNED,
        409,
    )

    released = get_success_data(
        api.release_collateral_asset(
            asset["id"], release_payload(release_note="Deal restructured"), CREDIT_ANALYST
        )
    )
    assert_nulls(
        released,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert len(released["lien_history"]) == 1
    record = released["lien_history"][0]
    assert record["loan_application_id"] == first["id"]
    assert record["lien_position"] == 1
    assert_iso_equal(record["effective_from"], "2026-08-01T00:00:00Z", "effective_from")
    assert_iso_equal(record["effective_to"], "2031-08-01T00:00:00Z", "effective_to")
    assert record["released_at"] is not None
    # Re-valued at the first-lien factor now that it is free.
    assert_fields(released, lending_value_cents=225000000)

    validate_error(
        api.release_collateral_asset(
            asset["id"], release_payload(release_note="Releasing again"), CREDIT_ANALYST
        ),
        ERR_COLLATERAL_ALREADY_ASSIGNED,
        409,
    )
    reread = get_success_data(api.get_collateral_asset(asset["id"], CREDIT_ANALYST))
    assert len(reread["lien_history"]) == 1


def test_a_lapsed_resolution_answers_before_the_sizing_cap_is_ever_computed(api):
    """
    The same over-sized referral on the same application answers two different errors
    depending only on where the clock stands: past the packet's expiry the governance
    check answers, and back inside the window the coverage cap answers.

    PRD §3.5: "The packet's `expires_on` must fall at or after the current logical instant, or it is refused with `ERR_GOVERNANCE_AUTHORIZATION_EXPIRED`; a packet expiring exactly now is still good."
    PRD §3.5: "And the `requested_amount_cents` must not exceed the maximum supportable principal, or it is refused with `ERR_LTV_COVERAGE_INSUFFICIENT`; a request exactly equal to that maximum is supportable."
    PRD §2.10: "The packet's `expires_on` is at or after the current logical instant — `ERR_GOVERNANCE_AUTHORIZATION_EXPIRED` (HTTP 409), on committee referral and on the committee decision."
    PRD §2.10: "The requested amount is within the maximum supportable principal — `ERR_LTV_COVERAGE_INSUFFICIENT` (HTTP 422), on committee referral."
    PRD §3.5: "On success two figures are snapshotted and the application moves `UNDERWRITING → COMMITTEE_REVIEW` with its `version` advanced by 1."

    Design: Corner/validations/governance_expiry_outranks_the_collateral_cap_at_committee_referral
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    build_giving_periods(api, institution["id"], REFERENCE_AUDITED_QUARTERS)
    packet = build_authorized_authorization(api, institution["id"])
    asset = build_collateral_asset(api, institution["id"])
    application = build_draft_application(
        api, institution["id"], packet["id"], requested_amount_cents=240000000
    )
    submit_to_underwriting(
        api,
        application["id"],
        analyst_note="Requesting 240000000 against a 225000000 lien",
    )
    assign_asset(api, asset["id"], application["id"])

    # Past expires_on the fiscal cap is never reached.
    set_clock(api, "2027-07-01T00:00:00Z")
    validate_error(
        api.committee_referral(
            application["id"],
            {"referral_note": "Referring after the resolution lapsed"},
            CREDIT_ANALYST,
        ),
        ERR_GOVERNANCE_AUTHORIZATION_EXPIRED,
        409,
    )

    # Back inside the window the same request fails on coverage instead:
    # min(306000000, 225000000, 500000000, 400000000) == 225000000 < 240000000.
    set_clock(api, "2026-08-01T00:00:00Z")
    validate_error(
        api.committee_referral(
            application["id"],
            {"referral_note": "Referring inside the window"},
            CREDIT_ANALYST,
        ),
        ERR_LTV_COVERAGE_INSUFFICIENT,
        422,
    )

    stalled = get_success_data(api.get_loan_application(application["id"], CREDIT_ANALYST))
    assert_fields(stalled, status="UNDERWRITING")
    assert_nulls(
        stalled, "collateral_lending_value_cents", "max_supportable_principal_cents"
    )
    # Expiry is evaluated per call, never stored on the packet.
    assert_fields(
        get_success_data(api.get_governance_authorization(packet["id"], GOVERNANCE_OFFICER)),
        status="AUTHORIZED",
    )


def test_one_resolution_binds_its_applications_in_aggregate_on_the_approving_arm(api):
    """
    Two 225000000 applications each pass their own sizing caps against a 400000000
    resolution, but approving the second would total 450000000, so only the approving
    arm is refused — a decline on the identical application succeeds.

    PRD §3.6: "A single board resolution may back several applications, and the resolution's `authorized_amount_cents` binds them in aggregate: the `requested_amount_cents` of the application being approved, added to the `requested_amount_cents` of every **other** application carrying the same `governance_authorization_id` whose `status` is `APPROVED` or `FUNDED`, must not exceed `authorized_amount_cents`."
    PRD §3.6: "An aggregate that breaches it is refused with `ERR_AUTHORIZED_AMOUNT_EXCEEDED`."
    PRD §2.10: "The aggregate draw on one board resolution stays inside the amount that resolution authorised — `ERR_AUTHORIZED_AMOUNT_EXCEEDED` (HTTP 422), on an approving committee decision. Position 47 already caps any single request at the authorised amount, so only the aggregate across several applications can breach here."
    PRD §3.6: "A **declining** decision moves the application `COMMITTEE_REVIEW → DECLINED`, stores the submitted note as `revision_reason`, and releases the collateral: every asset assigned to this application has its `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and `lien_effective_to` cleared to null, with the occupation just ended appended to that asset's `lien_history` exactly as an explicit release would append it."

    Design: Corner/validations/aggregate_draw_on_one_resolution_cannot_exceed_the_authorized_amount
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    build_giving_periods(api, institution["id"], REFERENCE_AUDITED_QUARTERS)
    packet = build_authorized_authorization(api, institution["id"])
    asset_a = build_collateral_asset(api, institution["id"])
    asset_b = build_collateral_asset(
        api, institution["id"], description_label="West campus sanctuary"
    )

    first = build_draft_application(api, institution["id"], packet["id"])
    submit_to_underwriting(api, first["id"], analyst_note="First deal on the resolution")
    assign_asset(api, asset_a["id"], first["id"])
    refer_to_committee(api, first["id"], referral_note="First lien on the main sanctuary")
    first = render_committee_decision(api, first["id"], "APPROVE")
    assert_fields(first, status="APPROVED", max_supportable_principal_cents=225000000)

    second = build_draft_application(
        api, institution["id"], packet["id"], purpose="SCHOOL_CONSTRUCTION"
    )
    submit_to_underwriting(api, second["id"], analyst_note="Second deal on the same resolution")
    assign_asset(api, asset_b["id"], second["id"])
    second = refer_to_committee(
        api, second["id"], referral_note="First lien on the west campus sanctuary"
    )
    # Each request cleared position 47 on its own merits.
    assert_fields(
        second,
        status="COMMITTEE_REVIEW",
        requested_amount_cents=225000000,
        max_supportable_principal_cents=225000000,
    )

    # 225000000 + 225000000 == 450000000 against a 400000000 resolution.
    validate_error(
        api.committee_decision(second["id"], {"decision": "APPROVE"}, COMMITTEE_MEMBER),
        ERR_AUTHORIZED_AMOUNT_EXCEEDED,
        422,
    )
    held = get_success_data(api.get_loan_application(second["id"], CREDIT_ANALYST))
    assert_fields(held, status="COMMITTEE_REVIEW")
    assert_nulls(held, "decided_by_user_id")

    # The aggregate cap guards only the approving arm.
    declined = get_success_data(
        api.committee_decision(
            second["id"],
            {"decision": "DECLINE", "note": "Resolution headroom exhausted"},
            COMMITTEE_MEMBER,
        )
    )
    assert_fields(declined, status="DECLINED", revision_reason="Resolution headroom exhausted")

    rows, meta = validate_paginated(
        api.list_loan_applications(
            CREDIT_ANALYST,
            {"governance_authorization_id": packet["id"], "status": "APPROVED"},
        )
    )
    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [first["id"]]


def test_one_cent_decides_whether_the_waterfall_leaves_the_institution_anything(api):
    """
    A 50000-cent draw nets exactly nothing once retainage and the inspection fee are
    taken and is refused, while 50001 cents nets exactly one cent and disburses,
    because the floored retainage does not move between the two.

    PRD §3.7: "The third bucket must be strictly greater than zero; a draw whose retainage, interest-reserve sweep and inspection fee together consume the entire gross amount is refused with `ERR_DRAW_NET_NONPOSITIVE`."
    PRD §3.7: "Add the gross amount to the loan's `disbursed_principal_cents` as it stands immediately before this disbursement, multiply that post-draw total by 10000, divide by the loan's `principal_cents` discarding any remainder, then divide by 10000 again to express the result as a fraction floored to four decimal places."
    PRD §3.7: "Below a completion fraction of 0.5000 the rate is 10 percent; from 0.5000 up to but not including 0.9000 it is 5 percent; at 0.9000 and above it is 0 percent."
    PRD §3.7: "The second bucket takes the inspection fee: whichever is smaller of what remains in the pool and 45000 cents — a flat 450 dollars per disbursement — stored as `inspection_fee_cents` and removed from the pool."
    PRD §3.7: "On the loan, `reserved_draw_cents` falls by the approved amount because the reservation has been consumed; `disbursed_principal_cents` rises by the approved amount and `undrawn_commitment_cents` falls by the same amount; `outstanding_principal_cents` rises by the approved amount; `retainage_held_cents` rises by `retainage_cents`; and `interest_reserve_shortfall_cents` falls by `interest_reserve_applied_cents`."

    Design: Corner/validations/draw_whose_waterfall_leaves_the_institution_nothing_is_rejected
    """
    chain = chain_through_loan(
        api,
        institution_overrides=BORROWER,
        loan_overrides={"interest_reserve_shortfall_cents": 0},
    )
    nets_nothing = get_success_data(
        api.create_draw_request(
            draw_request_payload(
                chain.loan_id,
                project_phase="SITE_WORK",
                requested_amount_cents=50000,
                percent_complete=0.0100,
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    get_success_data(
        api.approve_draw_request(
            nets_nothing["id"],
            draw_approval_payload(50000, inspector_note="Approved at the requested amount"),
            LOAN_SERVICER,
        )
    )
    nets_one_cent = get_success_data(
        api.create_draw_request(
            draw_request_payload(
                chain.loan_id,
                project_phase="SITE_WORK",
                requested_amount_cents=50001,
                percent_complete=0.0100,
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    get_success_data(
        api.approve_draw_request(
            nets_one_cent["id"],
            draw_approval_payload(50001, inspector_note="One cent more"),
            LOAN_SERVICER,
        )
    )

    # retainage floor(50000 * 0.10) == 5000, pool 45000, reserve sweep 0,
    # inspection fee 45000, net 0.
    validate_error(
        api.disburse_draw_request(
            nets_nothing["id"], draw_disbursement_payload(), LOAN_SERVICER
        ),
        ERR_DRAW_NET_NONPOSITIVE,
        422,
    )
    refused = get_success_data(api.get_draw_request(nets_nothing["id"], LOAN_SERVICER))
    assert_fields(refused, status="APPROVED")
    assert_nulls(
        refused,
        "retainage_cents",
        "interest_reserve_applied_cents",
        "inspection_fee_cents",
        "net_disbursed_cents",
        "completion_pct_at_disbursement",
    )

    disbursed = get_success_data(
        api.disburse_draw_request(
            nets_one_cent["id"], draw_disbursement_payload(), LOAN_SERVICER
        )
    )
    assert_fields(
        disbursed,
        status="DISBURSED",
        retainage_cents=5000,
        interest_reserve_applied_cents=0,
        inspection_fee_cents=45000,
        net_disbursed_cents=1,
    )
    # floor(50001 * 10000 / 225000000) == 2, expressed as 0.0002.
    assert_ratio(
        disbursed["completion_pct_at_disbursement"], 0.0002, "completion_pct_at_disbursement"
    )

    assert_loan_ledger(
        chain.read_loan(),
        servicing_status="CONSTRUCTION_DRAW",
        disbursed_principal_cents=50001,
        outstanding_principal_cents=50001,
        undrawn_commitment_cents=224949999,
        retainage_held_cents=5000,
        # The refused draw is still reserved; nothing released its claim.
        reserved_draw_cents=50000,
    )


def test_a_cure_needs_a_passing_test_and_a_waiver_needs_a_hard_breach(api):
    """
    One covenant sitting in the soft-breach window after a single failure refuses both
    remedies for different reasons: the cure because the last test failed, and the
    waiver because it departs from the hard breach only.

    PRD §3.8: "In both cases the covenant's `last_test_result` must already be `PASS`; a cure filed while the most recent test failed, or filed against a covenant that is already `COMPLIANT`, is refused with `ERR_COVENANT_INVALID_STATE`."
    PRD §3.8: "A waiver is the committee's instrument and is reserved to a `CreditCommitteeMember`, who supplies a `waiver_note`."
    PRD §3.8: "It is available only from `BREACHED`, moving the covenant `BREACHED → WAIVED` and raising `waiver_count` by 1; attempted on a covenant in any other state it is refused with `ERR_COVENANT_INVALID_STATE`."
    PRD §2.10: "The covenant occupies the state the requested transition departs from, and an explicit cure additionally requires `last_test_result` to be `PASS` — `ERR_COVENANT_INVALID_STATE` (HTTP 409), on a cure and on a waiver."
    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT → BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1."

    Design: Corner/validations/cure_without_a_passing_test_and_waiver_before_hard_breach_are_rejected
    """
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    tested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    assert_fields(
        tested,
        status="BREACH_PENDING_CURE",
        last_test_result="FAIL",
        consecutive_fail_count=1,
        test_count=1,
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")

    # The from-state is right, but the evidence is a failing test.
    validate_error(
        api.cure_covenant(
            covenant["id"],
            cure_payload(cure_evidence_note="Cure filed with no fresh test"),
            LOAN_SERVICER,
        ),
        ERR_COVENANT_INVALID_STATE,
        409,
    )
    # The waiver departs from BREACHED, which this covenant has not reached.
    validate_error(
        api.waive_covenant(
            covenant["id"],
            waiver_payload(waiver_note="Committee waiver before the hard breach"),
            COMMITTEE_MEMBER,
        ),
        ERR_COVENANT_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_covenant(covenant["id"], LOAN_SERVICER))
    assert_fields(
        unchanged,
        status="BREACH_PENDING_CURE",
        waiver_count=0,
        consecutive_fail_count=1,
    )
    assert_nulls(unchanged, "cure_evidence_note")
    assert_fields(
        chain.read_loan(), risk_posture="WATCH", servicing_status="PENDING_FIRST_DRAW"
    )


def test_four_fiscal_guards_answer_four_nearly_identical_calls_in_ladder_order(api):
    """
    On one WATCH loan whose outstanding principal is zero, the mission floor answers
    before the forgiveness cap on the same approval, the predecessor rule answers a
    create naming a merely proposed plan, and the payment cap answers a 1000-cent
    payment — and nothing on the loan moves.

    PRD §3.9: "Two score floors then apply, and both are inclusive: a `PARTIAL_FORGIVENESS` plan requires a `mission_impact_score` of at least 92.00, and a `MISSION_IMPACT_FORBEARANCE` plan requires at least 50.00."
    PRD §3.9: "Finally, a `PARTIAL_FORGIVENESS` plan whose `forgiveness_amount_cents` exceeds the loan's `outstanding_principal_cents` is refused with `ERR_FORGIVENESS_EXCEEDS_OUTSTANDING`."
    PRD §3.9: "`predecessor_workout_plan_id` is optional and null for the first plan on a loan; when supplied it must reference a plan on the **same** loan whose `status` is `APPROVED`, and a reference to a plan on another loan or to a plan that is not approved is refused with `ERR_PREDECESSOR_WORKOUT_INVALID`."
    PRD §3.7: "The amount must not exceed the loan's `outstanding_principal_cents`, or the payment is refused with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`; a payment against a `PAID_OFF` loan is refused with `ERR_LOAN_TERMINAL`."
    PRD §2.10: "The workout plan named in the path is `PROPOSED`, and the loan's `risk_posture` is `WATCH`, `RESTRICTED` or `WORKOUT_GATED` — `ERR_WORKOUT_INVALID_STATE` (HTTP 409), on workout creation and workout approval. A creation has no target plan yet, so it is judged by the posture clause alone; any predecessor it names is left to position 41."
    PRD §3.9: "`denominational_points` is 100 when the plan's `denominational_support_letter` is true and 0 when it is false."

    Design: Corner/validations/workout_and_payment_fiscal_guards_fire_in_declared_priority_order
    """
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    version_before = chain.read_loan()["version"]

    without_letter = get_success_data(
        api.create_workout_plan(
            forgiveness_payload(
                chain.loan_id,
                version_before,
                1000000,
                denominational_support_letter=False,
                narrative="Forgiveness without denominational backing",
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    assert_fields(
        without_letter,
        membership_trend_points=100,
        giving_trend_points=100,
        community_points=60,
        denominational_points=0,
    )
    assert_score(without_letter["mission_impact_score"], 72.00)

    # 72.00 < 92.00, so the mission floor answers before the forgiveness cap is
    # ever consulted.
    validate_error(
        api.approve_workout_plan(
            without_letter["id"], workout_approval_payload(approval_note="Committee attempts approval"), COMMITTEE_MEMBER
        ),
        ERR_MISSION_IMPACT_SCORE_TOO_LOW,
        422,
    )

    with_letter = get_success_data(
        api.create_workout_plan(
            forgiveness_payload(
                chain.loan_id,
                chain.read_loan()["version"],
                1000000,
                denominational_support_letter=True,
                narrative="Forgiveness with a presbytery support letter",
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    assert_fields(with_letter, denominational_points=100)
    assert_score(with_letter["mission_impact_score"], 92.00)

    # The floor now passes at exactly 92.00, so the later cap gets its turn:
    # 1000000 against an outstanding principal of 0.
    validate_error(
        api.approve_workout_plan(
            with_letter["id"], workout_approval_payload(approval_note="Committee attempts approval"), COMMITTEE_MEMBER
        ),
        ERR_FORGIVENESS_EXCEEDS_OUTSTANDING,
        422,
    )

    version_after = chain.read_loan()["version"]
    # The predecessor is PROPOSED rather than APPROVED.
    validate_error(
        api.create_workout_plan(
            workout_plan_payload(
                chain.loan_id,
                version_after,
                predecessor_workout_plan_id=without_letter["id"],
                deferral_months=3,
                denominational_support_letter=True,
                narrative="Deferral succeeding a plan that was never approved",
            ),
            LOAN_SERVICER,
        ),
        ERR_PREDECESSOR_WORKOUT_INVALID,
        409,
    )
    validate_error(
        api.record_loan_payment(chain.loan_id, loan_payment_payload(1000), LOAN_SERVICER),
        ERR_PAYMENT_EXCEEDS_OUTSTANDING,
        422,
    )

    # No plan reached APPROVED, so the posture never became WORKOUT_GATED and the
    # loan's own version never moved through any of it.
    assert version_after == version_before
    assert_loan_ledger(
        chain.read_loan(),
        risk_posture="WATCH",
        forgiven_principal_cents=0,
        deferred_payments_count=0,
        principal_repaid_cents=0,
        outstanding_principal_cents=0,
    )
    rows, meta = validate_paginated(
        api.list_workout_plans(LOAN_SERVICER, {"loan_id": chain.loan_id})
    )
    assert_pagination_meta(meta, total_count=2)
    assert [row["status"] for row in rows] == ["PROPOSED", "PROPOSED"]
