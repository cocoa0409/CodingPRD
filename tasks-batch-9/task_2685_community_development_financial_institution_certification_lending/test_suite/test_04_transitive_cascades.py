"""Cascades that cross several aggregates from one request.

A write-off travels loan to lender to award to pledge on a reserve threshold;
a resignation travels seat to lender to certification verdict to docket state
on a derived boolean.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMINISTRATOR, ANALYST, SECOND_ADMINISTRATOR


def _certified_lender_with_an_open_draw_window():
    """A certified lender drawing on an award, holding a delinquent 2,000,000 loan.

    Its funded reserve of 1,520,000 cents exactly meets the migration
    requirement of the two-loan book, so the posture is still compliant when
    the write-off arrives.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.create_certified_institution(
        institution_overrides={"loss_reserve_balance_cents": 1_520_000}
    )
    institution_id = scenario["institution"]["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)

    scenario["product"] = fixtures.create_loan_product(institution_id)
    scenario["borrower"] = fixtures.create_geocoded_borrower(institution_id)
    lending = {
        "institution": scenario["institution"],
        "product": scenario["product"],
        "borrower": scenario["borrower"],
    }
    scenario["delinquent_loan"] = fixtures.create_disbursed_loan(lending, 2_000_000)

    award = fixtures.open_award_application(
        institution_id,
        requested_amount_cents=4_000_000,
        match_ratio_pct=25.00,
        period_start="2026-10-01T00:00:00Z",
        period_end="2027-09-30T00:00:00Z",
    )
    verified_pledge = fixtures.pledge_commitment(
        award["id"], source_name="Private Foundation A",
        source_type="CASH_PRIVATE", amount_cents=1_000_000,
    )
    fixtures.submit_award_application(award["id"])
    validate_success(
        api_client.decide_award_application(
            award["id"],
            {"decision": "AWARD", "awarded_amount_cents": 4_000_000},
            ADMINISTRATOR,
        )
    )
    validate_success(
        api_client.verify_matching_fund_commitment(
            verified_pledge["id"], SECOND_ADMINISTRATOR
        )
    )
    validate_success(
        api_client.activate_award_disbursing(award["id"], ADMINISTRATOR)
    )
    pledged_only = fixtures.pledge_commitment(
        award["id"], source_name="Donated Office Space", source_type="IN_KIND",
        amount_cents=500_000, committed_on="2026-12-01T00:00:00Z",
    )

    fixtures.set_clock("2026-12-31T00:00:00Z")
    fixtures.run_servicing(institution_id)
    scenario["current_loan"] = fixtures.create_disbursed_loan(lending, 1_000_000)

    scenario["award"] = award
    scenario["verified_pledge"] = verified_pledge
    scenario["pledged_only"] = pledged_only
    scenario["officer"] = officer
    return scenario


def test_a_write_off_travels_from_the_loan_to_the_pledges_on_one_request():
    """The reserve absorbs what it can, and the shortfall suspends the draw window.

    PRD: "The first link writes the loan: the entire
    `principal_outstanding_cents` moves into `charged_off_principal_cents`,
    `principal_outstanding_cents` becomes 0, `servicing_state` becomes
    `CHARGED_OFF` and `underwriting_state` becomes `CLOSED`."
    PRD: "The second link, caused by the outstanding balance changing, writes
    the institution: the reserve absorbs the write-off first, so
    `loss_reserve_balance_cents` becomes the greater of zero and the prior
    balance less the charged-off principal, and `reserve_deficit_cents` records
    the portion that could not be absorbed — the greater of zero and the
    charged-off principal less the balance as it stood before absorption."
    PRD: "The third link, caused by the posture change, suspends federal money:
    every award application of that institution whose `state` is `DISBURSING`
    moves `DISBURSING → DRAW_SUSPENDED` with `suspension_reason` recorded as
    `POSTURE_PROBATION`. The fourth link, caused by each suspension, freezes
    the match: every matching-fund commitment of each newly suspended award
    whose `status` is `PLEDGED` moves `PLEDGED → HELD`."

    Design: Difficulty/transitive_cascade/charge_off_cascade_reaches_matching_fund_commitment_hold
    """
    scenario = _certified_lender_with_an_open_draw_window()

    written_off = validate_success(
        api_client.charge_off_loan(
            scenario["delinquent_loan"]["id"],
            {"charge_off_reason": "BORROWER_INSOLVENT"},
            ANALYST,
        )
    )
    assert written_off["servicing_state"] == "CHARGED_OFF"
    assert written_off["underwriting_state"] == "CLOSED"
    assert written_off["charged_off_principal_cents"] == 2_000_000
    assert written_off["principal_outstanding_cents"] == 0

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["loss_reserve_balance_cents"] == 0
    assert institution["reserve_deficit_cents"] == 480_000
    assert institution["loss_reserve_required_migration_cents"] == 20_000
    assert institution["loss_reserve_required_cents"] == 20_000
    assert float(institution["reserve_coverage_ratio"]) == 0.0000
    assert institution["compliance_posture"] == "PROBATION"
    assert institution["portfolio_principal_outstanding_cents"] == 1_000_000
    assert institution["certification_state"] == "CERTIFIED"

    award = validate_success(
        api_client.get_award_application(scenario["award"]["id"], ADMINISTRATOR)
    )
    assert award["state"] == "DRAW_SUSPENDED"
    assert award["suspension_reason"] == "POSTURE_PROBATION"
    assert award["match_eligible_cents"] == 1_000_000
    assert award["match_shortfall_cents"] == 0

    held = validate_success(
        api_client.get_matching_fund_commitment(
            scenario["pledged_only"]["id"], ADMINISTRATOR
        )
    )
    assert held["status"] == "HELD"

    untouched = validate_success(
        api_client.get_matching_fund_commitment(
            scenario["verified_pledge"]["id"], ADMINISTRATOR
        )
    )
    assert untouched["status"] == "VERIFIED"
    assert untouched["eligible_cents"] == 1_000_000


def test_draws_cannot_be_resumed_while_the_write_off_leaves_the_lender_on_probation():
    """The suspension the cascade wrote cannot be lifted until the reserve is repaired.

    PRD: "An `AwardAdministrator` must lift the suspension explicitly, and the
    gate to do so is strictly tighter than the activation gate: the application
    must be in `DRAW_SUSPENDED` and the institution's `compliance_posture` must
    be exactly `COMPLIANT` — `WATCH` is not sufficient here, and an attempt
    under `WATCH` or `PROBATION` is refused with `ERR_POSTURE_NOT_COMPLIANT`."

    Design: Difficulty/transitive_cascade/charge_off_cascade_reaches_matching_fund_commitment_hold
    """
    scenario = _certified_lender_with_an_open_draw_window()
    fixtures.charge_off_loan(
        scenario["delinquent_loan"]["id"], "BORROWER_INSOLVENT"
    )

    response = api_client.resume_award_draws(
        scenario["award"]["id"], ADMINISTRATOR
    )

    validate_error(response, ApiErrorId.ERR_POSTURE_NOT_COMPLIANT)


def _docket_with_a_split_governing_board():
    """A docket under review behind two seats, only one of which represents.

    The half-representing board puts the accountability score at exactly
    0.5000, which is the satisfaction threshold.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    market = fixtures.create_approved_target_market(institution_id)
    representing = fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD", holder_name="R. Alvarez",
        represents_target_market=True, target_market_id=market["id"],
    )
    plain = fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD", holder_name="T. Boyd",
        represents_target_market=False,
    )
    application = fixtures.open_certification_application(institution_id)
    fixtures.submit_certification_application(institution_id, application["id"])
    fixtures.begin_certification_review(application["id"])
    fixtures.record_certification_verdict(
        application["id"], "ACCOUNTABILITY", "PASSED"
    )
    return {
        "institution": fixtures.read_institution(institution_id),
        "target_market": market,
        "representing_seat": representing,
        "plain_seat": plain,
        "application": application,
    }


def test_losing_the_representing_seat_fails_the_verdict_and_reopens_the_docket():
    """The score falls below the threshold, so the docket leaves review.

    PRD: "Resignation sets the seat's `status` to `RESIGNED`, stamps
    `resigned_at` from the logical clock, decrements the matching active-seat
    counter on the institution, recomputes `accountability_score` and
    `accountability_satisfied`, and advances the institution's `version` by 1.
    If — and only if — that recomputation flips `accountability_satisfied` from
    true to false, the cascade continues into the certification docket: every
    certification application of that institution whose `state` is
    `UNDER_REVIEW` has its `test_accountability_state` set to `FAILED`, and each
    such application whose `revision_round` is still below 2 is additionally
    pushed backwards from `UNDER_REVIEW` to `INFO_REQUESTED` with
    `revision_round` incremented by 1 and `info_requested_reason` recorded as
    `ACCOUNTABILITY_TEST_FAILED`."

    Design: Difficulty/transitive_cascade/board_seat_resignation_cascade_reopens_certification_review
    """
    scenario = _docket_with_a_split_governing_board()

    resigned = validate_success(
        api_client.resign_board_seat(
            scenario["representing_seat"]["id"],
            fixtures.make_institution_officer_headers(
                scenario["institution"]["id"]
            ),
        )
    )
    assert resigned["status"] == "RESIGNED"
    assert resigned["resigned_at"] == "2026-09-01T00:00:00.000Z"

    still_seated = validate_success(
        api_client.get_board_seat(scenario["plain_seat"]["id"], ANALYST)
    )
    assert still_seated["status"] == "ACTIVE"

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["governing_seats_active"] == 1
    assert float(institution["accountability_score"]) == 0.0000
    assert institution["accountability_satisfied"] is False

    docket = validate_success(
        api_client.get_certification_application(
            scenario["application"]["id"], ANALYST
        )
    )
    assert docket["test_accountability_state"] == "FAILED"
    assert docket["test_primary_mission_state"] == "PENDING"
    assert docket["state"] == "INFO_REQUESTED"
    assert docket["revision_round"] == 1
    assert docket["info_requested_reason"] == "ACCOUNTABILITY_TEST_FAILED"


def test_losing_the_non_representing_seat_leaves_the_docket_under_review():
    """The flag never flips, so nothing downstream of the lender is written.

    PRD: "If — and only if — that recomputation flips
    `accountability_satisfied` from true to false, the cascade continues into
    the certification docket: every certification application of that
    institution whose `state` is `UNDER_REVIEW` has its
    `test_accountability_state` set to `FAILED`."
    PRD: "The governing share is the representing governing count divided by the
    total governing count, taken as an exact ratio and not rounded; when there
    are no active governing seats at all, the governing share is treated as zero
    rather than as undefined."

    Design: Difficulty/transitive_cascade/board_seat_resignation_cascade_reopens_certification_review
    """
    scenario = _docket_with_a_split_governing_board()

    validate_success(
        api_client.resign_board_seat(
            scenario["plain_seat"]["id"],
            fixtures.make_institution_officer_headers(
                scenario["institution"]["id"]
            ),
        )
    )

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["governing_seats_active"] == 1
    assert float(institution["accountability_score"]) == 1.0000
    assert institution["accountability_satisfied"] is True

    docket = validate_success(
        api_client.get_certification_application(
            scenario["application"]["id"], ANALYST
        )
    )
    assert docket["state"] == "UNDER_REVIEW"
    assert docket["revision_round"] == 0
    assert docket["test_accountability_state"] == "PASSED"
    assert docket["info_requested_reason"] is None
