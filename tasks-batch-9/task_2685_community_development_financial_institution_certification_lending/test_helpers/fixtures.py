"""Composite setup helpers.

The database is empty at the start of every test, so each helper builds the
state it needs from scratch using only endpoints the PRD publishes. Setup
calls go through the lenient validator so that a broken precondition reports
itself as a setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    ADMINISTRATOR_ONE,
    ADMINISTRATOR_TWO,
    ANALYST_ONE,
    COMMITTEE_ONE,
    REVIEWER_ONE,
    REVIEWER_TWO,
    TEST_USERS,
    UNDERWRITER_ONE,
    make_award_administrator_headers,
    make_borrower_headers,
    make_certification_reviewer_headers,
    make_compliance_analyst_headers,
    make_credit_committee_headers,
    make_credit_underwriter_headers,
    make_institution_officer_headers,
)

ANALYST = make_compliance_analyst_headers(ANALYST_ONE)
REVIEWER = make_certification_reviewer_headers(REVIEWER_ONE)
SECOND_REVIEWER = make_certification_reviewer_headers(REVIEWER_TWO)
UNDERWRITER = make_credit_underwriter_headers(UNDERWRITER_ONE)
COMMITTEE = make_credit_committee_headers(COMMITTEE_ONE)
ADMINISTRATOR = make_award_administrator_headers(ADMINISTRATOR_ONE)
SECOND_ADMINISTRATOR = make_award_administrator_headers(ADMINISTRATOR_TWO)


# ======================================================================
# Tier 1 — logical clock and single-entity progression
# ======================================================================
def set_clock(instant: str) -> None:
    """Move the logical clock to an explicit instant."""
    get_success_data(api_client.set_clock(instant, ANALYST))


def create_institution(**overrides) -> dict:
    """Register one lender. Returns the institution record."""
    return get_success_data(
        api_client.create_institution(
            f.institution_payload(**overrides),
            TEST_USERS["institution_officer_headers"],
        )
    )


def read_institution(institution_id: str) -> dict:
    return get_success_data(api_client.get_institution(institution_id, ANALYST))


def create_target_market(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_target_market(
            institution_id,
            f.target_market_payload(**overrides),
            make_institution_officer_headers(institution_id),
        )
    )


def create_approved_target_market(institution_id: str, **overrides) -> dict:
    """Define a market and have the certifying reviewer approve it."""
    market = create_target_market(institution_id, **overrides)
    return get_success_data(
        api_client.approve_target_market(market["id"], REVIEWER)
    )


def create_board_seat(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_board_seat(
            institution_id,
            f.board_seat_payload(**overrides),
            make_institution_officer_headers(institution_id),
        )
    )


def seat_representing_governing_board(institution_id: str, target_market_id: str,
                                     holders=("R. Alvarez", "L. Nakamura")) -> list:
    """Seat governing-board members who all represent the named market."""
    seats = []
    for holder in holders:
        seats.append(
            create_board_seat(
                institution_id,
                structure="GOVERNING_BOARD",
                holder_name=holder,
                represents_target_market=True,
                target_market_id=target_market_id,
            )
        )
    return seats


def create_accountable_institution(**overrides) -> dict:
    """A lender with an approved market and a fully representing board.

    The two representing governing seats put the accountability score at
    1.0000, which is what the certification docket needs to open.
    Returns ``{"institution", "target_market", "seats"}``.
    """
    institution = create_institution(**overrides)
    market = create_approved_target_market(institution["id"])
    seats = seat_representing_governing_board(institution["id"], market["id"])
    return {
        "institution": read_institution(institution["id"]),
        "target_market": market,
        "seats": seats,
    }


def create_borrower(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_borrower(
            institution_id,
            f.borrower_payload(**overrides),
            make_institution_officer_headers(institution_id),
        )
    )


def geocode_borrower(borrower_id: str, outcome="MATCHED", **overrides) -> dict:
    return get_success_data(
        api_client.geocode_borrower(
            borrower_id, f.geocode_payload(outcome, **overrides), ANALYST
        )
    )


def create_geocoded_borrower(institution_id: str, census_tract_code=None,
                             **overrides) -> dict:
    """Intake a borrower and resolve its address to a tract."""
    borrower = create_borrower(institution_id, **overrides)
    geocode_borrower(
        borrower["id"],
        "MATCHED",
        census_tract_code=census_tract_code or TEST_DEFAULTS["CENSUS_TRACT"],
    )
    return get_success_data(
        api_client.get_borrower(borrower["id"], ANALYST)
    )


def create_loan_product(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_loan_product(
            institution_id,
            f.loan_product_payload(**overrides),
            make_institution_officer_headers(institution_id),
        )
    )


# ======================================================================
# Tier 2 — lender hierarchy ready for lending
# ======================================================================
def setup_lending_ready_institution(institution_overrides=None,
                                    product_overrides=None,
                                    borrower_overrides=None,
                                    with_approved_market=True,
                                    census_tract_code=None) -> dict:
    """A lender with one product and one geocoded borrower.

    This is the preamble almost every lending claim needs. Returns
    ``{"institution", "target_market", "product", "borrower", "officer"}``
    where ``officer`` is the identity header set for that lender's officer.
    """
    institution = create_institution(**(institution_overrides or {}))
    officer = make_institution_officer_headers(institution["id"])
    market = None
    if with_approved_market:
        market = create_approved_target_market(institution["id"])
    product = create_loan_product(institution["id"], **(product_overrides or {}))
    borrower = create_geocoded_borrower(
        institution["id"],
        census_tract_code=census_tract_code,
        **(borrower_overrides or {}),
    )
    return {
        "institution": read_institution(institution["id"]),
        "target_market": market,
        "product": product,
        "borrower": borrower,
        "officer": officer,
    }


def setup_ungeocoded_lending_scenario(product_overrides=None,
                                      borrower_overrides=None) -> dict:
    """Same hierarchy, but the borrower's address was never resolved."""
    institution = create_institution()
    officer = make_institution_officer_headers(institution["id"])
    product = create_loan_product(institution["id"], **(product_overrides or {}))
    borrower = create_borrower(institution["id"], **(borrower_overrides or {}))
    return {
        "institution": institution,
        "product": product,
        "borrower": borrower,
        "officer": officer,
    }


# ======================================================================
# Tier 3 — loan lifecycle shortcuts
# ======================================================================
def file_loan(institution_id: str, borrower_id: str, product_id: str,
              requested_principal_cents=1_000_000, **overrides) -> dict:
    return get_success_data(
        api_client.create_loan(
            f.loan_payload(
                institution_id, borrower_id, product_id,
                requested_principal_cents, **overrides,
            ),
            make_institution_officer_headers(institution_id),
        )
    )


def underwrite_loan(loan_id: str, underwriter_id=UNDERWRITER_ONE, **overrides) -> dict:
    return get_success_data(
        api_client.underwrite_loan(
            loan_id,
            f.underwrite_payload(**overrides),
            make_credit_underwriter_headers(underwriter_id),
        )
    )


def decide_loan(loan_id: str, committee_id=COMMITTEE_ONE, decision="APPROVE",
                **overrides) -> dict:
    return get_success_data(
        api_client.decide_loan(
            loan_id,
            f.loan_decision_payload(decision, **overrides),
            make_credit_committee_headers(committee_id),
        )
    )


def disburse_loan(institution_id: str, loan_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.disburse_loan(
            loan_id,
            {"amount_cents": amount_cents},
            make_institution_officer_headers(institution_id),
        )
    )


def create_underwritten_loan(scenario: dict, requested_principal_cents=1_000_000,
                             underwrite_overrides=None, **loan_overrides) -> dict:
    """File a loan and run the pricing and grading chain on it."""
    loan = file_loan(
        scenario["institution"]["id"],
        scenario["borrower"]["id"],
        scenario["product"]["id"],
        requested_principal_cents,
        **loan_overrides,
    )
    underwrite_loan(loan["id"], **(underwrite_overrides or {}))
    return get_success_data(api_client.get_loan(loan["id"], ANALYST))


def create_approved_loan(scenario: dict, requested_principal_cents=1_000_000,
                         approved_principal_cents=None,
                         underwrite_overrides=None, **loan_overrides) -> dict:
    """Walk a loan from filing through committee approval."""
    loan = create_underwritten_loan(
        scenario, requested_principal_cents, underwrite_overrides, **loan_overrides
    )
    decide_loan(
        loan["id"],
        decision="APPROVE",
        approved_principal_cents=(
            approved_principal_cents
            if approved_principal_cents is not None
            else requested_principal_cents
        ),
    )
    return get_success_data(api_client.get_loan(loan["id"], ANALYST))


def create_disbursed_loan(scenario: dict, requested_principal_cents=1_000_000,
                          approved_principal_cents=None, disbursed_cents=None,
                          underwrite_overrides=None, **loan_overrides) -> dict:
    """Walk a loan all the way to a funded, currently-paying position."""
    loan = create_approved_loan(
        scenario, requested_principal_cents, approved_principal_cents,
        underwrite_overrides, **loan_overrides,
    )
    disburse_loan(
        scenario["institution"]["id"],
        loan["id"],
        disbursed_cents if disbursed_cents is not None else loan["approved_principal_cents"],
    )
    return get_success_data(api_client.get_loan(loan["id"], ANALYST))


def setup_disbursed_loan(**kwargs) -> dict:
    """One lender, one product, one geocoded borrower and one funded loan.

    Returns the lending scenario with a ``"loan"`` key added.
    """
    scenario = setup_lending_ready_institution(
        institution_overrides=kwargs.pop("institution_overrides", None),
        product_overrides=kwargs.pop("product_overrides", None),
        borrower_overrides=kwargs.pop("borrower_overrides", None),
    )
    scenario["loan"] = create_disbursed_loan(scenario, **kwargs)
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    return scenario


# ======================================================================
# Tier 3b — technical assistance
# ======================================================================
def book_ta_engagement(institution_id: str, borrower_id: str, start_at: str,
                       end_at: str, planned_hours: float,
                       topic="CREDIT_BUILDING", **overrides) -> dict:
    return get_success_data(
        api_client.create_ta_engagement(
            institution_id,
            f.ta_engagement_payload(
                borrower_id, start_at, end_at, planned_hours, topic, **overrides
            ),
            make_institution_officer_headers(institution_id),
        )
    )


def close_ta_engagement(institution_id: str, engagement_id: str,
                        outcome="COMPLETED", actual_hours=None,
                        competency_verified=None) -> dict:
    return get_success_data(
        api_client.close_ta_engagement(
            engagement_id,
            f.ta_close_payload(outcome, actual_hours, competency_verified),
            make_institution_officer_headers(institution_id),
        )
    )


def accumulate_ta_hours(institution_id: str, borrower_id: str, hours: float,
                        competency_verified=True, day="2026-09-02",
                        first_hour=6) -> list:
    """Deliver completed coaching until the borrower holds ``hours`` in total.

    Sessions are booked back to back with more than the required gap between
    them so that no booking collides with its predecessor, and each is closed
    as delivered so the hours land on the borrower's running total.
    """
    engagements = []
    remaining = float(hours)
    hour = first_hour
    while remaining > 0:
        block = min(4.0, remaining)
        start = "{}T{:02d}:00:00Z".format(day, hour)
        end = "{}T{:02d}:00:00Z".format(day, hour + int(block))
        engagement = book_ta_engagement(
            institution_id, borrower_id, start, end, round(block, 2)
        )
        close_ta_engagement(
            institution_id, engagement["id"],
            outcome="COMPLETED", actual_hours=round(block, 2),
            competency_verified=competency_verified,
        )
        engagements.append(engagement)
        remaining = round(remaining - block, 2)
        hour += int(block) + 1
    return engagements


# ======================================================================
# Tier 3c — certification docket
# ======================================================================
def open_certification_application(institution_id: str, **overrides) -> dict:
    """Open a docket, reading the institution's live version for the token."""
    institution = read_institution(institution_id)
    return get_success_data(
        api_client.create_certification_application(
            institution_id,
            f.certification_application_payload(institution["version"], **overrides),
            make_institution_officer_headers(institution_id),
        )
    )


def submit_certification_application(institution_id: str, application_id: str) -> dict:
    return get_success_data(
        api_client.submit_certification_application(
            application_id, make_institution_officer_headers(institution_id)
        )
    )


def begin_certification_review(application_id: str,
                               reviewer_id=REVIEWER_ONE) -> dict:
    return get_success_data(
        api_client.begin_certification_review(
            application_id, make_certification_reviewer_headers(reviewer_id)
        )
    )


def record_certification_verdict(application_id: str, test_code: str,
                                 verdict="PASSED", reviewer_id=REVIEWER_ONE,
                                 **overrides) -> dict:
    return get_success_data(
        api_client.evaluate_certification_test(
            application_id,
            f.evaluate_test_payload(test_code, verdict, **overrides),
            make_certification_reviewer_headers(reviewer_id),
        )
    )


def record_all_certification_verdicts(application_id: str, verdict="PASSED",
                                      reviewer_id=REVIEWER_ONE) -> None:
    """Record the six test verdicts one call at a time."""
    for test_code in (
        "PRIMARY_MISSION",
        "TARGET_MARKET",
        "FINANCING_ENTITY",
        "DEVELOPMENT_SERVICES",
        "ACCOUNTABILITY",
        "NON_GOVERNMENT",
    ):
        record_certification_verdict(
            application_id, test_code, verdict, reviewer_id
        )


def setup_application_under_review(institution_overrides=None,
                                   application_overrides=None,
                                   reviewer_id=REVIEWER_ONE) -> dict:
    """A lender whose docket has been submitted and opened for review.

    Returns ``{"institution", "target_market", "seats", "application"}``.
    """
    accountable = create_accountable_institution(**(institution_overrides or {}))
    institution_id = accountable["institution"]["id"]
    application = open_certification_application(
        institution_id, **(application_overrides or {})
    )
    submit_certification_application(institution_id, application["id"])
    begin_certification_review(application["id"], reviewer_id)
    accountable["application"] = get_success_data(
        api_client.get_certification_application(application["id"], ANALYST)
    )
    return accountable


def create_certified_institution(institution_overrides=None,
                                 application_overrides=None) -> dict:
    """Walk a lender all the way to a signed certification.

    The reviewer who opened review is not the reviewer who signs, because the
    signature is barred to the identity that opened the review.
    Returns ``{"institution", "target_market", "seats", "application"}``.
    """
    scenario = setup_application_under_review(
        institution_overrides, application_overrides
    )
    record_all_certification_verdicts(scenario["application"]["id"])
    get_success_data(
        api_client.decide_certification_application(
            scenario["application"]["id"], SECOND_REVIEWER
        )
    )
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    scenario["application"] = get_success_data(
        api_client.get_certification_application(
            scenario["application"]["id"], ANALYST
        )
    )
    return scenario


# ======================================================================
# Tier 3d — impact reporting
# ======================================================================
def file_impact_report(loan_id: str, borrower_id: str,
                       reporting_period_end="2026-08-31T00:00:00Z",
                       **figures) -> dict:
    """File impact data as the borrower of record, pinning the loan version."""
    loan = get_success_data(api_client.get_loan(loan_id, ANALYST))
    return get_success_data(
        api_client.create_impact_report(
            loan_id,
            f.impact_report_payload(
                loan["version"], reporting_period_end, **figures
            ),
            make_borrower_headers(borrower_id),
        )
    )


def verify_impact_report(impact_report_id: str) -> dict:
    return get_success_data(
        api_client.verify_impact_report(impact_report_id, ANALYST)
    )


def create_verified_impact_report(loan_id: str, borrower_id: str,
                                  reporting_period_end="2026-08-31T00:00:00Z",
                                  **figures) -> dict:
    """File impact data and have the analyst verify it."""
    report = file_impact_report(
        loan_id, borrower_id, reporting_period_end, **figures
    )
    verify_impact_report(report["id"])
    return get_success_data(
        api_client.get_impact_report(report["id"], ANALYST)
    )


# ======================================================================
# Tier 4 — accumulation and threshold targeting
# ======================================================================
def setup_loan_book(loans, institution_overrides=None, product_overrides=None,
                    clock=None) -> dict:
    """Build a book of funded loans with controlled target-market membership.

    ``loans`` is a sequence of ``(principal_cents, in_target_market)`` pairs.
    Borrowers destined for the market are geocoded into the approved tract;
    the others are geocoded to a tract the market does not cover, so their
    origination snapshot reads false. Returns the scenario plus ``"loans"``.
    """
    if clock:
        set_clock(clock)
    institution = create_institution(**(institution_overrides or {}))
    market = create_approved_target_market(institution["id"])
    product = create_loan_product(institution["id"], **(product_overrides or {}))
    scenario = {
        "institution": institution,
        "target_market": market,
        "product": product,
        "officer": make_institution_officer_headers(institution["id"]),
        "loans": [],
        "borrowers": [],
    }
    for index, (principal_cents, in_market) in enumerate(loans):
        borrower = create_geocoded_borrower(
            institution["id"],
            census_tract_code=(
                TEST_DEFAULTS["CENSUS_TRACT"] if in_market else "36005990100"
            ),
            full_name="Borrower {}".format(index + 1),
        )
        scenario["borrowers"].append(borrower)
        loan_scenario = {
            "institution": institution,
            "product": product,
            "borrower": borrower,
        }
        scenario["loans"].append(
            create_disbursed_loan(loan_scenario, principal_cents)
        )
    scenario["institution"] = read_institution(institution["id"])
    return scenario


# ======================================================================
# Tier 4b — compliance measurement
# ======================================================================
def open_measurement(institution_id: str, period_start: str, period_end: str,
                     weighting_basis="DOLLAR_WEIGHTED", **overrides) -> dict:
    return get_success_data(
        api_client.create_compliance_measurement(
            institution_id,
            f.compliance_measurement_payload(
                period_start, period_end, weighting_basis, **overrides
            ),
            ANALYST,
        )
    )


def finalize_measurement(measurement_id: str) -> dict:
    return get_success_data(
        api_client.finalize_compliance_measurement(measurement_id, ANALYST)
    )


def create_finalized_measurement(institution_id: str, period_start: str,
                                 period_end: str,
                                 weighting_basis="DOLLAR_WEIGHTED",
                                 **overrides) -> dict:
    """Open a measurement window and finalize it in one step."""
    measurement = open_measurement(
        institution_id, period_start, period_end, weighting_basis, **overrides
    )
    return finalize_measurement(measurement["id"])


def void_measurement(measurement_id: str, void_reason="Window opened in error") -> dict:
    return get_success_data(
        api_client.void_compliance_measurement(
            measurement_id, {"void_reason": void_reason}, ANALYST
        )
    )


# ======================================================================
# Tier 4c — awards and matching funds
# ======================================================================
def open_award_application(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_award_application(
            institution_id, f.award_application_payload(**overrides), ADMINISTRATOR
        )
    )


def pledge_commitment(award_application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_matching_fund_commitment(
            award_application_id,
            f.matching_fund_commitment_payload(**overrides),
            ADMINISTRATOR,
        )
    )


def verify_commitment(commitment_id: str, verifier=SECOND_ADMINISTRATOR) -> dict:
    """Verify a pledge under an administrator other than the one who filed it."""
    return get_success_data(
        api_client.verify_matching_fund_commitment(commitment_id, verifier)
    )


def pledge_verified_commitment(award_application_id: str, **overrides) -> dict:
    commitment = pledge_commitment(award_application_id, **overrides)
    return verify_commitment(commitment["id"])


def submit_award_application(award_application_id: str) -> dict:
    return get_success_data(
        api_client.submit_award_application(award_application_id, ADMINISTRATOR)
    )


def decide_award_application(award_application_id: str, decision="AWARD",
                             awarded_amount_cents=None) -> dict:
    payload = {"decision": decision}
    if awarded_amount_cents is not None:
        payload["awarded_amount_cents"] = awarded_amount_cents
    return get_success_data(
        api_client.decide_award_application(
            award_application_id, payload, SECOND_ADMINISTRATOR
        )
    )


def setup_award_ready_institution(institution_overrides=None,
                                  application_overrides=None) -> dict:
    """A certified lender holding a draft award application.

    Returns the certification scenario with an ``"award"`` key added.
    """
    scenario = create_certified_institution(institution_overrides)
    scenario["award"] = open_award_application(
        scenario["institution"]["id"], **(application_overrides or {})
    )
    return scenario


def setup_submitted_award(institution_overrides=None,
                          application_overrides=None,
                          pledges=((("CASH_PRIVATE"), 1_000_000),)) -> dict:
    """A certified lender whose award application is under consideration.

    ``pledges`` is a sequence of ``(source_type, amount_cents)`` pairs, each
    pledged and then verified so the eligible total counts toward the match.
    """
    scenario = setup_award_ready_institution(
        institution_overrides, application_overrides
    )
    scenario["commitments"] = []
    for index, (source_type, amount_cents) in enumerate(pledges):
        scenario["commitments"].append(
            pledge_verified_commitment(
                scenario["award"]["id"],
                source_type=source_type,
                amount_cents=amount_cents,
                source_name="Pledge {}".format(index + 1),
            )
        )
    submit_award_application(scenario["award"]["id"])
    scenario["award"] = get_success_data(
        api_client.get_award_application(scenario["award"]["id"], ADMINISTRATOR)
    )
    return scenario


def setup_awarded_application(institution_overrides=None,
                              application_overrides=None,
                              pledges=((("CASH_PRIVATE"), 1_000_000),),
                              awarded_amount_cents=None) -> dict:
    """Carry an award application through to the funder's award decision."""
    scenario = setup_submitted_award(
        institution_overrides, application_overrides, pledges
    )
    decide_award_application(
        scenario["award"]["id"], "AWARD", awarded_amount_cents
    )
    scenario["award"] = get_success_data(
        api_client.get_award_application(scenario["award"]["id"], ADMINISTRATOR)
    )
    return scenario


def setup_disbursing_award(institution_overrides=None,
                           application_overrides=None,
                           pledges=((("CASH_PRIVATE"), 1_000_000),),
                           awarded_amount_cents=None) -> dict:
    """Carry an award all the way to an open draw posture."""
    scenario = setup_awarded_application(
        institution_overrides, application_overrides, pledges,
        awarded_amount_cents,
    )
    get_success_data(
        api_client.activate_award_disbursing(
            scenario["award"]["id"], ADMINISTRATOR
        )
    )
    scenario["award"] = get_success_data(
        api_client.get_award_application(scenario["award"]["id"], ADMINISTRATOR)
    )
    return scenario


# ======================================================================
# Tier 4d — the bounded certification review cycle
# ======================================================================
def request_certification_info(application_id: str, reason="MISSION_UNCLEAR",
                               reviewer_id=REVIEWER_ONE) -> dict:
    return get_success_data(
        api_client.request_certification_info(
            application_id, {"info_requested_reason": reason},
            make_certification_reviewer_headers(reviewer_id),
        )
    )


def answer_certification_info(institution_id: str, application_id: str,
                              **corrections) -> dict:
    return get_success_data(
        api_client.resubmit_certification_application(
            application_id, dict(corrections),
            make_institution_officer_headers(institution_id),
        )
    )


def setup_application_at_revision_round(rounds: int,
                                        institution_overrides=None) -> dict:
    """Walk a docket through ``rounds`` completed information-request cycles.

    Each cycle is a reviewer request followed by the officer's answer, so the
    docket comes back to review with its revision counter advanced.
    """
    scenario = setup_application_under_review(institution_overrides)
    institution_id = scenario["institution"]["id"]
    application_id = scenario["application"]["id"]
    for _ in range(rounds):
        request_certification_info(application_id)
        answer_certification_info(institution_id, application_id)
    scenario["application"] = get_success_data(
        api_client.get_certification_application(application_id, ANALYST)
    )
    return scenario


# ======================================================================
# Tier 5 — servicing, delinquency and terminal positions
# ======================================================================
def run_servicing(institution_id: str) -> dict:
    """Run the servicing checkpoint for one lender."""
    return get_success_data(
        api_client.run_servicing(institution_id, ANALYST)
    )


def pay_loan(institution_id: str, loan_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_loan(
            loan_id, {"amount_cents": amount_cents},
            make_institution_officer_headers(institution_id),
        )
    )


def charge_off_loan(loan_id: str, charge_off_reason="Obligor unreachable") -> dict:
    return get_success_data(
        api_client.charge_off_loan(
            loan_id, {"charge_off_reason": charge_off_reason}, ANALYST
        )
    )


def age_book(institution_id: str, to_instant: str) -> dict:
    """Move the clock forward and run the checkpoint that ages the book."""
    set_clock(to_instant)
    return run_servicing(institution_id)


def setup_delinquent_loan(days_past_due=90, disbursed_cents=1_000_000,
                          first_disbursement_instant="2026-08-01T00:00:00Z",
                          **kwargs) -> dict:
    """A funded loan aged into a delinquency bucket by the checkpoint.

    The loan is advanced on ``first_disbursement_instant``, so its installment
    falls due thirty days later; the clock is then moved ``days_past_due`` days
    beyond that due date and the checkpoint is run.
    """
    from datetime import datetime, timedelta, timezone

    set_clock(first_disbursement_instant)
    scenario = setup_disbursed_loan(disbursed_cents=disbursed_cents, **kwargs)
    origin = datetime.strptime(
        first_disbursement_instant, "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    due = origin + timedelta(days=30)
    checkpoint = due + timedelta(days=days_past_due)
    age_book(
        scenario["institution"]["id"],
        checkpoint.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    scenario["loan"] = get_success_data(
        api_client.get_loan(scenario["loan"]["id"], ANALYST)
    )
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    return scenario


def setup_charged_off_loan(disbursed_cents=1_000_000,
                           charge_off_reason="Obligor unreachable",
                           **kwargs) -> dict:
    """A funded loan aged to ninety days past due and then written off."""
    scenario = setup_delinquent_loan(90, disbursed_cents, **kwargs)
    charge_off_loan(scenario["loan"]["id"], charge_off_reason)
    scenario["loan"] = get_success_data(
        api_client.get_loan(scenario["loan"]["id"], ANALYST)
    )
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    return scenario


def setup_paid_off_loan(disbursed_cents=1_000_000, **kwargs) -> dict:
    """A funded loan repaid to the cent, leaving the lender with an empty book."""
    scenario = setup_disbursed_loan(disbursed_cents=disbursed_cents, **kwargs)
    pay_loan(
        scenario["institution"]["id"], scenario["loan"]["id"], disbursed_cents
    )
    scenario["loan"] = get_success_data(
        api_client.get_loan(scenario["loan"]["id"], ANALYST)
    )
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    return scenario
