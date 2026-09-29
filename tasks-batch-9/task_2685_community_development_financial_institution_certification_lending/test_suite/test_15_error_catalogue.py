"""Error surfaces: unknown identifiers, entity-specific state guards, gates.

The not-found sweep addresses each entity family by an identifier nothing owns.
The state sweep proves each family reports its own guard rather than the generic
transition error.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMINISTRATOR, ANALYST, COMMITTEE, REVIEWER

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_every_addressed_family_reports_its_own_not_found_error():
    """Eleven identifier families, eleven distinct 404s, on an empty platform.

    PRD: "**Existence**, each yielding HTTP 404, in exactly this order:
    `institution_id` resolving to an institution (`ERR_INSTITUTION_NOT_FOUND`, on
    every endpoint carrying an institution identifier in path or body);
    `application_id` resolving to a certification application
    (`ERR_APPLICATION_NOT_FOUND`, on every certification-application endpoint
    addressed by identifier); `target_market_id` resolving to a target market of
    the same institution (`ERR_TARGET_MARKET_NOT_FOUND`, on the target-market
    read and approve actions and on board-seat creation); `board_seat_id`
    resolving to a board seat (`ERR_BOARD_SEAT_NOT_FOUND`, on the board-seat read
    and the resignation action)."
    PRD: "`borrower_id` resolving to a borrower of the same institution
    (`ERR_BORROWER_NOT_FOUND`, on every borrower endpoint addressed by
    identifier, on loan filing and on engagement booking)."
    PRD: "`engagement_id` resolving to an engagement
    (`ERR_TA_ENGAGEMENT_NOT_FOUND`, on the engagement read and close actions);
    `impact_report_id` resolving to a report (`ERR_IMPACT_REPORT_NOT_FOUND`, on
    every impact-report endpoint addressed by identifier); `measurement_id`
    resolving to a measurement (`ERR_MEASUREMENT_NOT_FOUND`, on every
    compliance-measurement endpoint addressed by identifier); `award_id`
    resolving to an award application (`ERR_AWARD_NOT_FOUND`, on every award
    endpoint addressed by identifier); and `commitment_id` resolving to a
    matching-fund commitment (`ERR_COMMITMENT_NOT_FOUND`, on every commitment
    endpoint addressed by identifier)."

    Design: Corner/errors/not_found_sweep_across_every_path_identifier
    """
    validate_error(
        api_client.get_institution(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND,
    )
    validate_error(
        api_client.get_certification_application(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_APPLICATION_NOT_FOUND,
    )
    validate_error(
        api_client.approve_target_market(UNKNOWN_ID, REVIEWER),
        ApiErrorId.ERR_TARGET_MARKET_NOT_FOUND,
    )
    validate_error(
        api_client.get_board_seat(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_BOARD_SEAT_NOT_FOUND,
    )
    validate_error(
        api_client.geocode_borrower(
            UNKNOWN_ID,
            {"outcome": "MATCHED", "census_tract_code": "36005010100"},
            ANALYST,
        ),
        ApiErrorId.ERR_BORROWER_NOT_FOUND,
    )
    validate_error(
        api_client.get_loan(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_LOAN_NOT_FOUND,
    )
    validate_error(
        api_client.get_ta_engagement(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_TA_ENGAGEMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_impact_report(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_IMPACT_REPORT_NOT_FOUND,
    )
    validate_error(
        api_client.finalize_compliance_measurement(UNKNOWN_ID, ANALYST),
        ApiErrorId.ERR_MEASUREMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_award_application(UNKNOWN_ID, ADMINISTRATOR),
        ApiErrorId.ERR_AWARD_NOT_FOUND,
    )
    validate_error(
        api_client.verify_matching_fund_commitment(UNKNOWN_ID, ADMINISTRATOR),
        ApiErrorId.ERR_COMMITMENT_NOT_FOUND,
    )


def test_each_family_answers_with_its_own_state_guard_not_the_generic_one():
    """Four resources in four wrong states, each naming its own guard.

    PRD: "Then the specific state guards, all HTTP 409, in this order: the
    application is `UNDER_REVIEW` (`ERR_APPLICATION_NOT_UNDER_REVIEW`, guarding
    test evaluation, information requests and the certification decision); the
    loan's `underwriting_state` is `UNDERWRITING` (`ERR_LOAN_NOT_IN_UNDERWRITING`,
    guarding the credit decision); the loan's `servicing_state` is
    `DELINQUENT_90` (`ERR_LOAN_NOT_DELINQUENT_90`, guarding charge-off); the
    measurement is `DRAFT` (`ERR_MEASUREMENT_NOT_DRAFT`, guarding both
    finalization and voiding); the award is `AWARDED` (`ERR_AWARD_NOT_AWARDED`,
    guarding draw activation); the commitment is `PLEDGED`
    (`ERR_COMMITMENT_NOT_PLEDGED`, guarding verification); the engagement is
    `SCHEDULED` (`ERR_ENGAGEMENT_NOT_SCHEDULED`, guarding close); and the report
    is `DISPUTED` (`ERR_REPORT_NOT_DISPUTED`, guarding correction)."
    PRD: "Correcting a report that is not `DISPUTED` is refused with
    `ERR_REPORT_NOT_DISPUTED`."
    PRD: "Either path moves the commitment to `WITHDRAWN` and advances both the
    commitment's `version` and the award's `version` by 1; verification does the
    same."

    Design: Corner/errors/entity_specific_state_errors_sweep_instead_of_the_generic_rung
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    borrower = fixtures.create_borrower(institution_id)
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 1_000_000
    )
    assert loan["underwriting_state"] == "SCREENING"

    award = fixtures.open_award_application(
        institution_id,
        program="NEW_MARKETS",
        requested_amount_cents=1_000_000,
        match_ratio_pct=100.00,
        performance_goal_jobs=5,
        performance_goal_housing_units=0,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    commitment = fixtures.pledge_commitment(
        award["id"], source_name="Meridian Foundation",
        source_type="CASH_PRIVATE", amount_cents=1_000_000,
        committed_on="2026-07-15T00:00:00Z",
    )
    withdrawn = validate_success(
        api_client.withdraw_matching_fund_commitment(
            commitment["id"], {"withdraw_reason": "FUNDER_RESCINDED"}, ADMINISTRATOR
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    report = fixtures.file_impact_report(
        loan["id"], borrower["id"], reporting_period_end="2026-07-31T00:00:00Z",
        jobs_created=3, jobs_retained=1, housing_units=0, businesses_financed=1,
    )
    assert report["state"] == "SUBMITTED"

    validate_error(
        api_client.decide_loan(
            loan["id"],
            {"decision": "APPROVE", "approved_principal_cents": 1_000_000},
            COMMITTEE,
        ),
        ApiErrorId.ERR_LOAN_NOT_IN_UNDERWRITING,
    )
    validate_error(
        api_client.activate_award_disbursing(award["id"], ADMINISTRATOR),
        ApiErrorId.ERR_AWARD_NOT_AWARDED,
    )
    validate_error(
        api_client.verify_matching_fund_commitment(commitment["id"], ADMINISTRATOR),
        ApiErrorId.ERR_COMMITMENT_NOT_PLEDGED,
    )
    validate_error(
        api_client.resubmit_impact_report(
            report["id"],
            {"jobs_created": 4, "jobs_retained": 1, "housing_units": 0,
             "businesses_financed": 1},
            fixtures.make_borrower_headers(borrower["id"]),
        ),
        ApiErrorId.ERR_REPORT_NOT_DISPUTED,
    )

    unchanged_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged_loan["underwriting_state"] == "SCREENING"
    assert unchanged_loan["approved_principal_cents"] is None

    unchanged_award = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert unchanged_award["state"] == "DRAFT"

    unchanged_commitment = validate_success(
        api_client.get_matching_fund_commitment(commitment["id"], ADMINISTRATOR)
    )
    assert unchanged_commitment["status"] == "WITHDRAWN"
    assert unchanged_commitment["verified_by_user_id"] is None

    unchanged_report = validate_success(
        api_client.get_impact_report(report["id"], ANALYST)
    )
    assert unchanged_report["state"] == "SUBMITTED"
    assert unchanged_report["revision_count"] == 0
    assert unchanged_report["jobs_created"] == 3


def test_a_verified_but_insufficient_pledge_still_blocks_the_draw_window():
    """Settling every pledge is not the same as covering the requirement.

    PRD: "Verification also requires the commitment to be `PLEDGED`, failing with
    `ERR_COMMITMENT_NOT_PLEDGED`, and requires the verifying `AwardAdministrator`
    to present an `X-User-ID` different from the `decided_by_user_id` recorded on
    the award, failing with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "Cash from private sources and cash from public non-federal sources
    count in full, at a factor of 1.00."
    PRD: "`match_shortfall_cents` is then the greater of zero and
    `required_match_cents` less `match_eligible_cents`."
    PRD: "The application must be in `state` `AWARDED`, failing with
    `ERR_AWARD_NOT_AWARDED`. The institution's `compliance_posture` must be
    `COMPLIANT` or `WATCH`, failing with `ERR_POSTURE_NOT_COMPLIANT`. Every
    matching-fund commitment of the award must be settled, meaning none is left
    in `PLEDGED` or `HELD`, failing with `ERR_MATCH_COMMITMENTS_UNVERIFIED`. And
    `match_shortfall_cents` must be exactly 0, failing with
    `ERR_MATCH_SHORTFALL`."

    Design: Corner/errors/match_shortfall_blocks_activation_after_every_pledge_is_verified
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.create_certified_institution()
    institution_id = scenario["institution"]["id"]
    assert scenario["institution"]["certification_state"] == "CERTIFIED"
    assert scenario["institution"]["compliance_posture"] == "COMPLIANT"

    award = fixtures.open_award_application(
        institution_id,
        program="CDFI_PROGRAM_FA",
        requested_amount_cents=4_000_000,
        match_ratio_pct=25.00,
    )
    assert award["required_match_cents"] == 1_000_000

    commitment = fixtures.pledge_commitment(
        award["id"], source_name="Kellerman Family Foundation",
        source_type="CASH_PRIVATE", amount_cents=600_000,
    )
    fixtures.submit_award_application(award["id"])
    decided = validate_success(
        api_client.decide_award_application(
            award["id"],
            {"decision": "AWARD", "awarded_amount_cents": 4_000_000},
            ADMINISTRATOR,
        )
    )
    assert decided["state"] == "AWARDED"

    validate_error(
        api_client.verify_matching_fund_commitment(commitment["id"], ADMINISTRATOR),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    verified = fixtures.verify_commitment(commitment["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["eligible_cents"] == 600_000

    response = api_client.activate_award_disbursing(award["id"], ADMINISTRATOR)
    validate_error(response, ApiErrorId.ERR_MATCH_SHORTFALL)

    lender = fixtures.read_institution(institution_id)
    assert lender["certification_state"] == "CERTIFIED"
    assert lender["compliance_posture"] == "COMPLIANT"

    ledger = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert ledger["state"] == "AWARDED"
    assert ledger["required_match_cents"] == 1_000_000
    assert ledger["match_eligible_cents"] == 600_000
    assert ledger["match_shortfall_cents"] == 400_000
