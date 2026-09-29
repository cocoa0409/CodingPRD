"""Actions on one row gated on the state of sibling rows.

A credit approval waits on a coaching session's state *and* its attestation
flag; a draw window waits on the status set of the award's own pledges.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMINISTRATOR, ANALYST, COMMITTEE, SECOND_ADMINISTRATOR


def _loan_awaiting_attested_coaching():
    """An underwritten loan whose borrower has hours but no attested session.

    The delivered session was completed with the attestation withheld; a second
    session covering the attestation is still scheduled.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    product = fixtures.create_loan_product(
        institution_id, name="TA-Gated Microloan", requires_ta_completion=True,
    )
    borrower = fixtures.create_geocoded_borrower(institution_id)
    delivered = fixtures.book_ta_engagement(
        institution_id, borrower["id"],
        "2026-09-02T09:00:00Z", "2026-09-02T13:00:00Z", 4.00,
    )
    scheduled = fixtures.book_ta_engagement(
        institution_id, borrower["id"],
        "2026-09-02T14:00:00Z", "2026-09-02T19:00:00Z", 5.00,
        topic="BUSINESS_PLANNING",
    )
    fixtures.close_ta_engagement(
        institution_id, delivered["id"], outcome="COMPLETED",
        actual_hours=4.00, competency_verified=False,
    )
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 2_000_000
    )
    fixtures.underwrite_loan(loan["id"])
    return {
        "institution": institution,
        "product": product,
        "borrower": borrower,
        "delivered": delivered,
        "scheduled": scheduled,
        "loan": loan,
    }


def test_a_completed_session_without_the_attestation_does_not_open_the_approval():
    """Hours on the borrower are not the gate; the attested session is.

    PRD: "Only a session that is `COMPLETED` **and** carries
    `competency_verified` true satisfies a product's technical-assistance
    prerequisite; hours delivered under a session still `SCHEDULED`, or one
    closed as `NO_SHOW`, contribute nothing to `ta_hours_total` and nothing to
    the prerequisite."
    PRD: "when the product's `requires_ta_completion` is true, a session must
    exist for the loan's borrower in `state` `COMPLETED` with
    `competency_verified` true, or the approval is refused with
    `ERR_TA_PREREQUISITE_UNMET`"

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_on_a_sibling_engagement_state_plus_flag
    """
    scenario = _loan_awaiting_attested_coaching()

    response = api_client.decide_loan(
        scenario["loan"]["id"],
        {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
        COMMITTEE,
    )
    validate_error(response, ApiErrorId.ERR_TA_PREREQUISITE_UNMET)

    blocked = validate_success(
        api_client.get_loan(scenario["loan"]["id"], ANALYST)
    )
    assert blocked["underwriting_state"] == "UNDERWRITING"

    borrower = validate_success(
        api_client.get_borrower(scenario["borrower"]["id"], ANALYST)
    )
    assert float(borrower["ta_hours_total"]) == 4.00


def test_attesting_the_second_session_releases_the_same_approval():
    """Closing the sibling session with the attestation opens the gate.

    PRD: "An `outcome` of `COMPLETED` requires `actual_hours` to be supplied and
    strictly greater than 0.00, and accepts `competency_verified` as the coach's
    attestation; it moves the session `SCHEDULED → COMPLETED`, stores both
    values, stamps `closed_at` from the logical clock, and recomputes the
    borrower's `ta_hours_total` as the sum of `actual_hours` over that
    borrower's `COMPLETED` sessions, carried to two decimal places."
    PRD: "A successful approval moves the loan `UNDERWRITING → APPROVED`,
    records `approved_principal_cents` and `decided_by_user_id`, and adds the
    approved amount to the product's `committed_principal_cents`."

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_on_a_sibling_engagement_state_plus_flag
    """
    scenario = _loan_awaiting_attested_coaching()
    institution_id = scenario["institution"]["id"]

    attested = fixtures.close_ta_engagement(
        institution_id, scenario["scheduled"]["id"], outcome="COMPLETED",
        actual_hours=5.00, competency_verified=True,
    )
    assert attested["state"] == "COMPLETED"
    assert attested["competency_verified"] is True

    approved = validate_success(
        api_client.decide_loan(
            scenario["loan"]["id"],
            {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
            COMMITTEE,
        )
    )
    assert approved["underwriting_state"] == "APPROVED"
    assert approved["approved_principal_cents"] == 2_000_000
    assert float(approved["dti_pct"]) == 14.83
    assert approved["risk_grade"] == "A"
    assert approved["ta_discount_bps"] == 0
    assert approved["final_rate_bps"] == 900
    assert approved["monthly_payment_cents"] == 48_333

    borrower = validate_success(
        api_client.get_borrower(scenario["borrower"]["id"], ANALYST)
    )
    assert float(borrower["ta_hours_total"]) == 9.00

    product = validate_success(
        api_client.get_loan_product(scenario["product"]["id"], ANALYST)
    )
    assert product["committed_principal_cents"] == 2_000_000


def _award_with_one_unsettled_pledge():
    """An awarded application whose match is met but whose pledge set is not."""
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.create_certified_institution()
    institution_id = scenario["institution"]["id"]
    award = fixtures.open_award_application(
        institution_id,
        requested_amount_cents=4_000_000,
        match_ratio_pct=25.00,
        period_start="2026-10-01T00:00:00Z",
        period_end="2027-10-01T00:00:00Z",
    )
    settled = fixtures.pledge_commitment(
        award["id"], source_name="Kellerman Family Foundation",
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
            settled["id"], SECOND_ADMINISTRATOR
        )
    )
    unsettled = fixtures.pledge_commitment(
        award["id"], source_name="Bronx Legal Aid In-Kind Services",
        source_type="IN_KIND", amount_cents=500_000,
        committed_on="2026-08-20T00:00:00Z",
    )
    scenario["award"] = award
    scenario["settled"] = settled
    scenario["unsettled"] = unsettled
    return scenario


def test_a_single_unsettled_pledge_holds_the_draw_window_shut():
    """A met match is not enough while any pledge of the award is unsettled.

    PRD: "Every matching-fund commitment of the award must be settled, meaning
    none is left in `PLEDGED` or `HELD`, failing with
    `ERR_MATCH_COMMITMENTS_UNVERIFIED`."
    PRD: "Pledges may be recorded while the award is in `DRAFT`, `SUBMITTED`,
    `AWARDED` or `DISBURSING`, which means a source pledged after the draw
    window has opened starts out unsettled and matters for the activation gate
    below."

    Design: Difficulty/cross_entity_state_dependency/award_activation_gated_on_the_status_set_of_its_own_commitments
    """
    scenario = _award_with_one_unsettled_pledge()

    before = validate_success(
        api_client.get_award_application(scenario["award"]["id"], ADMINISTRATOR)
    )
    assert before["required_match_cents"] == 1_000_000
    assert before["match_eligible_cents"] == 1_000_000
    assert before["match_shortfall_cents"] == 0

    response = api_client.activate_award_disbursing(
        scenario["award"]["id"], ADMINISTRATOR
    )
    validate_error(response, ApiErrorId.ERR_MATCH_COMMITMENTS_UNVERIFIED)

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["certification_state"] == "CERTIFIED"
    assert institution["compliance_posture"] == "COMPLIANT"


def test_withdrawing_the_unsettled_pledge_settles_the_set_and_opens_the_window():
    """Retracting the loose source empties the unsettled set without moving the ledger.

    PRD: "Withdrawing a merely `PLEDGED` source leaves `match_eligible_cents`
    untouched, because an unverified pledge never entered the ledger. Either
    path moves the commitment to `WITHDRAWN` and advances both the commitment's
    `version` and the award's `version` by 1; verification does the same."
    PRD: "Activation moves the application `AWARDED → DISBURSING`, clears
    `suspension_reason` to null and advances its `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/award_activation_gated_on_the_status_set_of_its_own_commitments
    """
    scenario = _award_with_one_unsettled_pledge()

    withdrawn = validate_success(
        api_client.withdraw_matching_fund_commitment(
            scenario["unsettled"]["id"],
            {"withdraw_reason": "SOURCE_RETRACTED"},
            ADMINISTRATOR,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["eligible_cents"] == 0

    activated = validate_success(
        api_client.activate_award_disbursing(
            scenario["award"]["id"], ADMINISTRATOR
        )
    )
    assert activated["state"] == "DISBURSING"
    assert activated["suspension_reason"] is None
    assert activated["match_eligible_cents"] == 1_000_000
    assert activated["match_shortfall_cents"] == 0

    kept = validate_success(
        api_client.get_matching_fund_commitment(
            scenario["settled"]["id"], ADMINISTRATOR
        )
    )
    assert kept["status"] == "VERIFIED"
    assert kept["eligible_cents"] == 1_000_000
