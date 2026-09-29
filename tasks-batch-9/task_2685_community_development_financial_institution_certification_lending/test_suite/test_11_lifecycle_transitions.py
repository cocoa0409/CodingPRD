"""Declared transitions, their side effects, and the positions that refuse them."""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_certification_application,
    assert_loan_ledger_invariant,
    assert_posture_matches_ratio,
)
from test_helpers.fixtures import ANALYST, REVIEWER, UNDERWRITER


def test_approving_a_market_stamps_the_instant_and_rescores_accountability():
    """Seats pointing at a draft definition only start counting on approval.

    PRD: "A seat counts as *representing* only when its
    `represents_target_market` flag is true **and** the target market it names is
    in state `APPROVED` — a seat pointing at a definition still in `DRAFT` is
    counted in the seat totals but not among the representing seats."
    PRD: "Approval stamps `approved_at` with the logical clock, and because
    seats pointing at that definition now begin to count, it also recomputes the
    institution's accountability figures and advances the institution's
    `version` by 1."

    Design: Corner/state_machines/target_market_approval_stamps_approved_at_and_rescores_accountability
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(ein="210000013")
    institution_id = institution["id"]
    market = fixtures.create_target_market(institution_id)
    seats = fixtures.seat_representing_governing_board(institution_id, market["id"])

    before = fixtures.read_institution(institution_id)
    assert float(before["accountability_score"]) == 0.0000
    assert before["accountability_satisfied"] is False
    assert before["governing_seats_active"] == 2

    approved = validate_success(
        api_client.approve_target_market(market["id"], REVIEWER)
    )
    assert approved["state"] == "APPROVED"
    assert approved["approved_at"] == "2026-09-01T00:00:00.000Z"

    after = fixtures.read_institution(institution_id)
    assert float(after["accountability_score"]) == 1.0000
    assert after["accountability_satisfied"] is True
    assert after["governing_seats_active"] == 2
    assert after["advisory_seats_active"] == 0
    for seat in seats:
        reread = validate_success(api_client.get_board_seat(seat["id"], ANALYST))
        assert reread["status"] == "ACTIVE"


def test_underwriting_a_borrower_who_was_never_geocoded_is_refused():
    """No pricing figure is written when the geocoding precondition fails.

    PRD: "Underwriting requires the borrower to be `GEOCODED`, failing with
    `ERR_BORROWER_NOT_GEOCODED`; it requires either a score to be present or the
    product's `allow_no_credit_score` to be true; and it requires the pricing
    chain below to resolve a grade."

    Design: Corner/state_machines/underwrite_on_an_ungeocoded_borrower_rejected
    """
    institution = fixtures.create_institution(ein="210000014")
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    borrower = fixtures.create_borrower(institution_id)
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 1_000_000
    )

    response = api_client.underwrite_loan(
        loan["id"], factories.underwrite_payload(), UNDERWRITER
    )
    validate_error(response, ApiErrorId.ERR_BORROWER_NOT_GEOCODED)

    unchanged = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged["underwriting_state"] == "SCREENING"
    assert unchanged["dti_pct"] is None
    assert unchanged["risk_grade"] is None
    assert unchanged["monthly_payment_cents"] is None
    assert unchanged["underwritten_by_user_id"] is None

    reread_borrower = validate_success(
        api_client.get_borrower(borrower["id"], ANALYST)
    )
    assert reread_borrower["geocode_state"] == "UNGEOCODED"


def test_the_first_advance_moves_both_dimensions_and_dates_the_loan():
    """One request performs two transitions and freezes the origination snapshot.

    PRD: "Exactly one request advances both dimensions at once: the first
    disbursement, which performs `APPROVED → CLOSED` and `NOT_DISBURSED →
    CURRENT` together."
    PRD: "On the **first** advance only, `first_disbursed_on` is stamped with the
    logical clock's date, `vintage_year` is set to the calendar year of that
    date, `next_payment_due_on` is set to that date advanced by 30 days, and
    `borrower_in_target_market_at_origination` is frozen from the borrower's
    `in_target_market` value as observed at that instant."
    PRD: "Consider a book of one 1,000,000-cent `CURRENT` loan and one
    2,000,000-cent `DELINQUENT_90` loan, both first disbursed in the clock's
    calendar year: the migration basis requires 1,520,000 cents and the
    static-pool basis requires 135,000 cents on identical data."

    Design: Corner/state_machines/first_disbursement_advances_both_dimensions_and_dates_the_loan
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution(
        institution_overrides={"ein": "210000015"}
    )
    institution_id = scenario["institution"]["id"]
    borrower = validate_success(
        api_client.get_borrower(scenario["borrower"]["id"], ANALYST)
    )
    assert borrower["in_target_market"] is True
    assert borrower["matched_target_market_type"] == "INVESTMENT_AREA"

    loan = fixtures.create_approved_loan(scenario, 1_000_000)
    funded = validate_success(
        api_client.disburse_loan(
            loan["id"], {"amount_cents": 1_000_000},
            fixtures.make_institution_officer_headers(institution_id),
        )
    )
    assert funded["underwriting_state"] == "CLOSED"
    assert funded["servicing_state"] == "CURRENT"
    assert funded["principal_disbursed_cents"] == 1_000_000
    assert funded["principal_outstanding_cents"] == 1_000_000
    assert funded["first_disbursed_on"] == "2026-09-01"
    assert funded["vintage_year"] == 2026
    assert funded["next_payment_due_on"] == "2026-10-01"
    assert funded["days_past_due"] == 0
    assert funded["borrower_in_target_market_at_origination"] is True
    assert_loan_ledger_invariant(funded)

    lender = fixtures.read_institution(institution_id)
    assert lender["portfolio_principal_outstanding_cents"] == 1_000_000
    assert lender["portfolio_principal_disbursed_cents"] == 1_000_000
    assert lender["loss_reserve_required_migration_cents"] == 20_000
    assert lender["loss_reserve_required_static_cents"] == 45_000
    assert lender["loss_reserve_required_cents"] == 20_000
    assert float(lender["reserve_coverage_ratio"]) == 0.0000
    assert lender["compliance_posture"] == "PROBATION"
    assert_posture_matches_ratio(lender)


def test_charging_off_a_current_loan_is_refused():
    """Charge-off is reserved for the deepest delinquency bucket.

    PRD: "Only a `ComplianceAnalyst` may do it, only against a loan whose
    `servicing_state` is `DELINQUENT_90` — any other position is refused with
    `ERR_LOAN_NOT_DELINQUENT_90` — and the request carries a
    `charge_off_reason`."

    Design: Corner/state_machines/charge_off_of_a_current_loan_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_disbursed_loan(
        institution_overrides={"ein": "210000016"},
        requested_principal_cents=1_000_000,
    )
    institution_id = scenario["institution"]["id"]
    loan = scenario["loan"]
    assert loan["servicing_state"] == "CURRENT"

    response = api_client.charge_off_loan(
        loan["id"], {"charge_off_reason": "PREMATURE_WRITE_OFF"}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_LOAN_NOT_DELINQUENT_90)

    unchanged = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged["servicing_state"] == "CURRENT"
    assert unchanged["charged_off_principal_cents"] == 0
    assert unchanged["principal_outstanding_cents"] == 1_000_000

    lender = fixtures.read_institution(institution_id)
    assert lender["loss_reserve_required_cents"] == 20_000
    assert lender["reserve_deficit_cents"] == 0
    assert lender["compliance_posture"] == "PROBATION"


def test_a_new_certification_docket_opens_in_draft_with_six_pending_verdicts():
    """The docket snapshots the score it was opened against.

    PRD: "On success the application is created in `state` `DRAFT` with
    `revision_round` 0, all six per-test verdict fields at `PENDING`,
    `accountability_score_snapshot` copied from the institution's current
    `accountability_score` and carried to four decimal places,
    `submitted_by_user_id`, `reviewed_by_user_id`, `info_requested_reason` and
    `decided_at` all null; the institution's `version` advances by 1."

    Design: Corner/state_machines/certification_application_starts_in_draft_with_six_pending_verdicts
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    accountable = fixtures.create_accountable_institution(ein="210000017")
    institution = accountable["institution"]
    assert float(institution["accountability_score"]) == 1.0000

    created = validate_success(
        api_client.create_certification_application(
            institution["id"],
            factories.certification_application_payload(institution["version"]),
            fixtures.make_institution_officer_headers(institution["id"]),
        ),
        201,
    )
    assert_certification_application(created)
    assert created["state"] == "DRAFT"
    assert created["revision_round"] == 0
    for field in (
        "test_primary_mission_state",
        "test_financing_entity_state",
        "test_target_market_state",
        "test_development_services_state",
        "test_accountability_state",
        "test_non_government_state",
    ):
        assert created[field] == "PENDING", f"{field} must open at PENDING"
    assert float(created["accountability_score_snapshot"]) == 1.0000
    assert created["submitted_by_user_id"] is None
    assert created["reviewed_by_user_id"] is None
    assert created["info_requested_reason"] is None
    assert created["decided_at"] is None
    assert created["version"] == 1


def test_voiding_a_finalized_measurement_is_refused():
    """Finalization is terminal for the void path.

    PRD: "the measurement is `DRAFT` (`ERR_MEASUREMENT_NOT_DRAFT`, guarding both
    finalization and voiding)."
    PRD: "Finalization moves the measurement `DRAFT → FINALIZED`, stamps
    `finalized_at` from the logical clock, copies `selected_pct` into the
    institution's `target_market_lending_pct`, and advances both the
    measurement's `version` and the institution's `version` by 1."

    Design: Corner/state_machines/void_of_a_finalized_measurement_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_disbursed_loan(
        institution_overrides={"ein": "210000018"},
        requested_principal_cents=1_000_000,
    )
    institution_id = scenario["institution"]["id"]
    fixtures.set_clock("2026-10-01T00:00:00Z")
    measurement = fixtures.create_finalized_measurement(
        institution_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )

    response = api_client.void_compliance_measurement(
        measurement["id"], {"void_reason": "TOO_LATE"}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_NOT_DRAFT)

    unchanged = validate_success(
        api_client.get_compliance_measurement(measurement["id"], ANALYST)
    )
    assert unchanged["state"] == "FINALIZED"
    assert unchanged["void_reason"] is None
    assert unchanged["measured_loan_count"] == 1
    assert float(unchanged["dollar_weighted_pct"]) == 100.00
    assert float(unchanged["count_weighted_pct"]) == 100.00
    assert float(unchanged["selected_pct"]) == 100.00
    assert unchanged["verdict"] == "PASS"
    assert unchanged["finalized_at"] == "2026-10-01T00:00:00.000Z"

    lender = fixtures.read_institution(institution_id)
    assert float(lender["target_market_lending_pct"]) == 100.00
    assert lender["certification_state"] == "UNCERTIFIED"


def test_closing_the_same_engagement_a_second_time_is_refused():
    """A closed session is terminal, and the first close is not replayed.

    PRD: "Closing a session that is not `SCHEDULED` is refused with
    `ERR_ENGAGEMENT_NOT_SCHEDULED`."
    PRD: "An `outcome` of `COMPLETED` requires `actual_hours` to be supplied and
    strictly greater than 0.00, and accepts `competency_verified` as the coach's
    attestation; it moves the session `SCHEDULED → COMPLETED`, stores both
    values, stamps `closed_at` from the logical clock, and recomputes the
    borrower's `ta_hours_total` as the sum of `actual_hours` over that borrower's
    `COMPLETED` sessions, carried to two decimal places."

    Design: Corner/state_machines/second_close_of_the_same_engagement_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(ein="210000019")
    institution_id = institution["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)
    borrower = fixtures.create_borrower(institution_id)
    engagement = fixtures.book_ta_engagement(
        institution_id, borrower["id"],
        "2026-09-02T09:00:00Z", "2026-09-02T13:00:00Z", 4.00,
    )
    fixtures.close_ta_engagement(
        institution_id, engagement["id"], outcome="COMPLETED",
        actual_hours=4.00, competency_verified=True,
    )

    response = api_client.close_ta_engagement(
        engagement["id"],
        {"outcome": "COMPLETED", "actual_hours": 4.00, "competency_verified": True},
        officer,
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_SCHEDULED)

    unchanged = validate_success(
        api_client.get_ta_engagement(engagement["id"], ANALYST)
    )
    assert unchanged["state"] == "COMPLETED"
    assert float(unchanged["actual_hours"]) == 4.00
    assert unchanged["competency_verified"] is True
    assert unchanged["closed_at"] == "2026-09-01T00:00:00.000Z"
    assert unchanged["version"] == 2, (
        "the rejected replay must not advance the engagement again"
    )

    reread_borrower = validate_success(
        api_client.get_borrower(borrower["id"], ANALYST)
    )
    assert float(reread_borrower["ta_hours_total"]) == 4.00


def test_resigning_an_already_resigned_seat_is_refused():
    """The generic transition guard catches the replayed resignation.

    PRD: "First, the generic check that the requested transition is declared for
    the resource's current state, reported as `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409) — this applies to every state-changing endpoint for which no more
    specific state error exists."
    PRD: "Resignation sets the seat's `status` to `RESIGNED`, stamps
    `resigned_at` from the logical clock, decrements the matching active-seat
    counter on the institution, recomputes `accountability_score` and
    `accountability_satisfied`, and advances the institution's `version` by 1."

    Design: Corner/state_machines/resignation_of_an_already_resigned_seat_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(ein="210000020")
    institution_id = institution["id"]
    market = fixtures.create_approved_target_market(institution_id)
    representing = fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD", holder_name="R. Alvarez",
        represents_target_market=True, target_market_id=market["id"],
    )
    plain = fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD",
        holder_name="T. Whitfield", represents_target_market=False,
    )
    officer = fixtures.make_institution_officer_headers(institution_id)
    validate_success(api_client.resign_board_seat(representing["id"], officer))

    response = api_client.resign_board_seat(representing["id"], officer)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    reread = validate_success(
        api_client.get_board_seat(representing["id"], ANALYST)
    )
    assert reread["status"] == "RESIGNED"
    assert reread["resigned_at"] == "2026-09-01T00:00:00.000Z"
    survivor = validate_success(api_client.get_board_seat(plain["id"], ANALYST))
    assert survivor["status"] == "ACTIVE"

    lender = fixtures.read_institution(institution_id)
    assert lender["governing_seats_active"] == 1
    assert float(lender["accountability_score"]) == 0.0000
    assert lender["accountability_satisfied"] is False

    _rows, meta = validate_paginated(
        api_client.list_board_seats(
            ANALYST, {"institution_id": institution_id, "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
