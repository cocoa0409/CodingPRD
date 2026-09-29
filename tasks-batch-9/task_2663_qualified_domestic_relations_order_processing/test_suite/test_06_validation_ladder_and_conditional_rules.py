"""What each guard actually guards, and in what order it speaks.

The ladder is peeled one rung at a time; the uniqueness scopes are per-parent;
the segregation window is a read-side guard that outranks the substance of the
order; and two conditional rules bite only on the configurations they name.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_ap_account_totals,
    assert_case_dimensions,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
    assert_settlement,
    assert_single_resource,
    assert_tax_ledger_totals,
    assert_tax_line,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID_6,
    ADMIN_USER_ID_7,
    ANALYST_HEADERS,
    ANALYST_USER_ID_4,
    NO_CREDENTIALS,
    UNDECLARED_ROLE_HEADERS,
    make_admin_headers,
    make_alternate_payee_headers,
    make_analyst_headers,
)
from test_helpers.types import (
    AP_ACCOUNT_CLOSED,
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    APPROACH_SHARED_PAYMENT,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DISTRIBUTION_CODE_2,
    DISTRIBUTION_CODE_G,
    DISTRIBUTION_ISSUED,
    DISTRIBUTION_VOIDED,
    DRAFT_DEFICIENT,
    DRAFT_QUALIFIED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    ELECTION_DIRECT_ROLLOVER,
    EMPLOYMENT_RETIRED,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_HELD,
    NOTICE_ISSUED,
    REVIEW_DEFICIENT,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SNAPSHOT_MANUAL_ADJUSTMENT,
    SOURCE_PRE_TAX_DEFERRAL,
    SOURCE_ROTH,
)

ONE_FORMULA_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
}

BOTH_APPROACHES_PLAN = dict(
    ONE_FORMULA_PLAN,
    allowed_approaches=[APPROACH_SEPARATE_INTEREST, APPROACH_SHARED_PAYMENT],
)


def test_each_uniqueness_scope_refuses_only_its_own_second_row(client):
    """One account per participant, one code per account, one date per account.

    PRD: "a participant may hold at most one plan account
    (`ERR_PLAN_ACCOUNT_ALREADY_EXISTS`, 409); a money source's `source_code` is
    unique within its account (`ERR_MONEY_SOURCE_DUPLICATE`, 409); a valuation
    snapshot's `as_of_date` is unique within its account
    (`ERR_SNAPSHOT_DUPLICATE`, 409)"

    Design: Corner/validations/uniqueness_rules_refuse_the_second_row_in_each_scope
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Unique Plan", **ONE_FORMULA_PLAN
    )
    first = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="Unique A",
        ssn_last4="1717",
        date_of_birth="1970-01-07",
        participation_start_date="2004-01-01",
    )
    second = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="Unique B",
        ssn_last4="1818",
        date_of_birth="1970-01-08",
        participation_start_date="2004-01-01",
    )
    account_a = fixtures.open_plan_account(client, first["id"])
    fixtures.add_money_source(
        client, account_a["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
    )
    fixtures.add_snapshot(client, account_a["id"], "2026-06-30", 1000000)
    account_b = fixtures.open_plan_account(client, second["id"])

    # Each scope refuses its second row under its own error identifier.
    assert_error_envelope(
        client.open_plan_account(
            first["id"], factories.plan_account_payload(), ADMIN_HEADERS
        ),
        api_errors.ERR_PLAN_ACCOUNT_ALREADY_EXISTS,
        409,
    )
    assert_error_envelope(
        client.create_money_source(
            account_a["id"],
            factories.money_source_payload(SOURCE_PRE_TAX_DEFERRAL, 5),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_MONEY_SOURCE_DUPLICATE,
        409,
    )
    assert_error_envelope(
        client.create_valuation_snapshot(
            account_a["id"],
            factories.valuation_snapshot_payload(
                "2026-06-30", 7, source=SNAPSHOT_MANUAL_ADJUSTMENT
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_SNAPSHOT_DUPLICATE,
        409,
    )

    # The very code and the very date just refused are free on the neighbouring
    # account, and an unused code is free on the same one.
    fixtures.add_money_source(
        client, account_b["id"], SOURCE_PRE_TAX_DEFERRAL, 400000
    )
    fixtures.add_snapshot(client, account_b["id"], "2026-06-30", 400000)
    fixtures.add_money_source(
        client, account_a["id"], SOURCE_ROTH, 200000, basis_cents=200000
    )

    sources = fixtures.read_money_sources(client, account_a["id"])
    assert [row["source_code"] for row in sources] == [
        SOURCE_PRE_TAX_DEFERRAL,
        SOURCE_ROTH,
    ]
    assert [row["balance_cents"] for row in sources] == [1000000, 200000], (
        "the refused duplicate never overwrote the balance it collided with"
    )
    snapshots = validate_success(
        client.list_valuation_snapshots(account_a["id"], ADMIN_HEADERS)
    )
    assert [(row["as_of_date"], row["balance_cents"]) for row in snapshots] == [
        ("2026-06-30", 1000000)
    ]
    accounts_of_first = validate_success(
        client.list_participant_plan_accounts(first["id"], ADMIN_HEADERS)
    )
    assert [row["id"] for row in accounts_of_first] == [account_a["id"]]

    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_a["id"]),
        vested_balance_cents=1200000,
        assignable_base_cents=1200000,
        after_tax_basis_cents=200000,
        held_amount_cents=0,
        available_balance_cents=1200000,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_b["id"]),
        vested_balance_cents=400000,
        assignable_base_cents=400000,
    )


def test_the_first_five_rungs_are_peeled_one_at_a_time(client):
    """Credentials, then role, then shape, then path, then body foreign key.

    PRD: "If either header is absent, or if `X-User-Role` is not exactly one of
    the five declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the
    presented role is not among the roles authorised for the endpoint being
    called (see the Authorized Role(s) column in §4), the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/the_first_five_priority_rungs_are_peeled_one_at_a_time
    """
    setup = fixtures.setup_plan_account(
        client,
        "Ladder Plan",
        fixtures.SINGLE_SOURCE,
        snapshots=(("2026-06-30", 1000000),),
        plan_overrides=ONE_FORMULA_PLAN,
        participant_overrides={
            "full_name": "Ladder Member",
            "ssn_last4": "1919",
            "date_of_birth": "1970-01-09",
            "participation_start_date": "2004-01-01",
        },
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Ladder Payee",
        alternate_payee_dob="1972-02-02",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    good_shape = factories.draft_order_payload(
        NON_EXISTENT_UUID, case["version"], document_reference="DRO-2663-L1"
    )

    # Rung 1: no identity headers at all, and a well formed pair naming a
    # capacity outside the five declared roles, are the same refusal.
    assert_error_envelope(
        client.create_draft_order(good_shape, NO_CREDENTIALS),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )
    assert_error_envelope(
        client.create_draft_order(good_shape, UNDECLARED_ROLE_HEADERS),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # Rung 2: a declared role that this endpoint does not authorise. The
    # identifier it carries is never even resolved.
    assert_error_envelope(
        client.create_draft_order(
            good_shape, make_alternate_payee_headers(NON_EXISTENT_UUID)
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )

    # Rung 3: an authorised role, but a required field is missing — reported
    # ahead of the dead identifier the same request carries.
    assert_error_envelope(
        client.create_draft_order(
            factories.omit(good_shape, "document_reference"), ANALYST_HEADERS
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )

    # Rung 4: a well formed body aimed at a path identifier that resolves to
    # nothing names the entity type of the path segment.
    assert_error_envelope(
        client.deny_draft_order(
            NON_EXISTENT_UUID,
            factories.denial_payload(DENIAL_ORDER_NOT_QUALIFIABLE),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_DRAFT_ORDER_NOT_FOUND,
        404,
    )

    # Rung 5: shape and path are now clean, so the unresolvable body foreign key
    # is finally the earliest fault left.
    assert_error_envelope(
        client.create_draft_order(good_shape, ANALYST_HEADERS),
        api_errors.ERR_QDRO_CASE_NOT_FOUND,
        404,
    )

    # With every rung satisfied the very same submission is accepted.
    accepted = assert_single_resource(
        client.create_draft_order(
            factories.draft_order_payload(
                case["id"], case["version"], document_reference="DRO-2663-L1"
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == DRAFT_UNDER_REVIEW
    assert accepted["revision_number"] == 1
    assert accepted["deficiency_codes"] == []

    on_the_case = validate_success(
        client.list_draft_orders(ADMIN_HEADERS, {"qdro_case_id": case["id"]})
    )
    assert [row["id"] for row in on_the_case] == [accepted["id"]], (
        "five refusals wrote nothing, so the accepted receipt is the only draft"
    )
    assert_case_dimensions(
        fixtures.read_case(client, case["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=case["version"] + 1,
    )
    assert_hold(
        fixtures.hold_for_case(client, case["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
    )


def _window_case(client, plan, member_name, ssn_last4, payee_name, document_reference):
    """One funded participant carrying a deficient draft and a live hold."""
    participant = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name=member_name,
        ssn_last4=ssn_last4,
        date_of_birth="1970-02-01",
        participation_start_date="2004-01-01",
    )
    account = fixtures.open_plan_account(client, participant["id"])
    fixtures.add_money_source(client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000)
    fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
    case = fixtures.open_case(
        client,
        participant["id"],
        alternate_payee_name=payee_name,
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference=document_reference,
        uses_model_language=False,
    )
    assert draft["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    return {
        "participant": participant,
        "account": account,
        "case": case,
        "draft": draft,
        "hold": fixtures.hold_for_case(client, case["id"]),
    }


def test_the_segregation_window_closes_qualification_and_resubmission_alike(client):
    """An expired hold shuts both doors before the order's substance is read.

    PRD: "resubmission and qualification both require the case's segregation
    hold to be `HELD` with the logical clock at or before its `expires_at`
    (`ERR_SEGREGATION_WINDOW_EXPIRED`)"

    Design: Corner/validations/the_segregation_window_closes_qualification_and_resubmission_alike
    """
    plan = fixtures.create_published_plan(
        client,
        plan_name="Window Plan",
        segregation_period_days=548,
        resubmission_window_days=60,
        max_revisions=3,
        **ONE_FORMULA_PLAN,
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    noticed = _window_case(
        client, plan, "Stale Member", "2121", "Stale Payee", "DRO-2663-STALE"
    )
    quiet = _window_case(
        client, plan, "Quiet Member", "2122", "Quiet Payee", "DRO-2663-QUIET"
    )
    for built in (noticed, quiet):
        assert_hold(
            built["hold"],
            status=HOLD_HELD,
            hold_amount_cents=400000,
            placed_at=constants.CLOCK_2026_09_01,
            expires_at=constants.CLOCK_2028_03_02,
        )

    # One day before expiry a notice is still issuable, and its own window runs
    # well past the hold's — which is exactly the conflict under test.
    fixtures.set_clock(client, "2028-03-01T00:00:00Z")
    notice = fixtures.issue_notice(
        client,
        noticed["draft"]["id"],
        headers=make_analyst_headers(ANALYST_USER_ID_4),
        reviewer_notes="late notice, window still open",
    )
    assert notice["issued_at"] == "2028-03-01T00:00:00Z"
    assert notice["resubmission_deadline_at"] == "2028-04-30T00:00:00Z"
    assert notice["resubmission_deadline_at"] > noticed["hold"]["expires_at"]
    assert fixtures.read_draft(client, noticed["draft"]["id"])["status"] == (
        DRAFT_DEFICIENT
    )

    # The clock passes the hold's expiry with no sweep run, so the holds are
    # still HELD rows while the window they define is closed.
    fixtures.set_clock(client, "2028-03-05T00:00:00Z")

    late_resubmission = client.resubmit_draft_order(
        noticed["draft"]["id"],
        factories.resubmission_payload(
            document_reference="DRO-2663-STALE-r2", uses_model_language=True
        ),
        fixtures.participant_headers(noticed["participant"]),
    )
    assert_error_envelope(
        late_resubmission, api_errors.ERR_SEGREGATION_WINDOW_EXPIRED, 409
    )

    # The same draft offered for qualification reports its own state first: the
    # target-state rung sits above the window rung.
    assert_error_envelope(
        client.qualify_draft_order(
            noticed["draft"]["id"], make_admin_headers(ADMIN_USER_ID_6)
        ),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )

    # The never-noticed draft is still UNDER_REVIEW and still carries its code,
    # so the window rung is reached and it outranks the readiness rung.
    assert_error_envelope(
        client.qualify_draft_order(
            quiet["draft"]["id"], make_admin_headers(ADMIN_USER_ID_6)
        ),
        api_errors.ERR_SEGREGATION_WINDOW_EXPIRED,
        409,
    )

    # Nothing lapsed: only the sweep moves a hold out of HELD.
    for built, review_status, draft_status in (
        (noticed, REVIEW_DEFICIENT, DRAFT_DEFICIENT),
        (quiet, REVIEW_UNDER_REVIEW, DRAFT_UNDER_REVIEW),
    ):
        assert_hold(
            fixtures.read_hold(client, built["hold"]["id"]),
            status=HOLD_HELD,
            hold_amount_cents=400000,
            earnings_growth_bps=0,
            earnings_adjustment_cents=0,
            segregation_date=None,
        )
        assert_plan_account_figures(
            fixtures.read_plan_account(client, built["account"]["id"]),
            held_amount_cents=400000,
            available_balance_cents=600000,
        )
        reread = fixtures.read_draft(client, built["draft"]["id"])
        assert reread["status"] == draft_status
        assert reread["revision_number"] == 1, "the refused resubmission never landed"
        assert reread["denial_reason"] is None
        assert reread["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
        assert_case_dimensions(
            fixtures.read_case(client, built["case"]["id"]),
            review_status=review_status,
            segregation_status=SEGREGATION_HELD,
        )

    still_open = fixtures.read_notices(client, noticed["draft"]["id"])
    assert [row["status"] for row in still_open] == [NOTICE_ISSUED], (
        "neither refusal cured or expired the notice"
    )
    assert fixtures.read_notices(client, quiet["draft"]["id"]) == []


def _funded_member(
    client, plan, member_name, ssn_last4, monthly, commenced, employment=None
):
    """A participant, an account and one assignable bucket with a baseline."""
    posture = {"employment_status": employment} if employment is not None else {}
    participant = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name=member_name,
        ssn_last4=ssn_last4,
        date_of_birth="1966-05-05",
        participation_start_date="2004-01-01",
        benefit_commenced=commenced,
        **posture,
    )
    account = fixtures.open_plan_account(
        client, participant["id"], monthly_payment_cents=monthly
    )
    fixtures.add_money_source(client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000)
    fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
    return participant, account


def test_election_and_approach_rules_bite_only_on_what_they_name(client):
    """Approach compatibility points both ways; the institution follows election.

    PRD: "the case's operative `approach` must be one the plan lists in
    `allowed_approaches` *and* must match the participant's payment posture — a
    `SHARED_PAYMENT` case requires `benefit_commenced` true with
    `monthly_payment_cents` greater than 0, and a `SEPARATE_INTEREST` case
    requires `benefit_commenced` false (otherwise `ERR_APPROACH_NOT_PERMITTED`)"

    Design: Corner/validations/election_and_approach_rules_only_bite_on_the_configurations_they_name
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Conditional Plan", **BOTH_APPROACHES_PLAN
    )
    in_pay_status, _ = _funded_member(
        client, plan, "Pay Status Member", "3131", 320000, True, EMPLOYMENT_RETIRED
    )
    accruing, _ = _funded_member(
        client, plan, "Accruing Member", "3132", 0, False
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    commenced_case = fixtures.open_case(
        client, in_pay_status["id"], alternate_payee_name="Pay Status Payee"
    )
    commenced_draft = fixtures.receive_draft(
        client,
        commenced_case["id"],
        commenced_case["version"],
        document_reference="DRO-2663-COND-A",
    )
    accruing_case = fixtures.open_case(
        client, accruing["id"], alternate_payee_name="Accruing Payee"
    )
    accruing_draft = fixtures.receive_draft(
        client,
        accruing_case["id"],
        accruing_case["version"],
        document_reference="DRO-2663-COND-B",
        proposed_approach=APPROACH_SHARED_PAYMENT,
        proposed_shared_payment_end_date="2031-12-31",
    )
    signer = make_admin_headers(ADMIN_USER_ID_7)

    # The plan lists both approaches, so both refusals are about the posture of
    # the participant and not about the plan's allow-list.
    assert_error_envelope(
        client.qualify_draft_order(commenced_draft["id"], signer),
        api_errors.ERR_APPROACH_NOT_PERMITTED,
        422,
    )
    assert_error_envelope(
        client.qualify_draft_order(accruing_draft["id"], signer),
        api_errors.ERR_APPROACH_NOT_PERMITTED,
        422,
    )

    # Swapping only the approach on the same case, participant and balances
    # qualifies, which isolates the condition to the payment posture.
    current = fixtures.read_case(client, accruing_case["id"])
    swapped = fixtures.receive_draft(
        client,
        accruing_case["id"],
        current["version"],
        document_reference="DRO-2663-COND-r2",
    )
    determined = fixtures.qualify(client, swapped["id"], headers=signer)
    assert determined["status"] == DRAFT_QUALIFIED

    payee = fixtures.ap_account_for_case(client, accruing_case["id"])
    assert payee["payment_mode"] == APPROACH_SEPARATE_INTEREST
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED
    assert payee["balance_cents"] == 400000
    assert payee["after_tax_basis_cents"] == 0
    payee_acts = fixtures.payee_headers(payee)

    # A rollover without a receiving institution is refused, and the identical
    # body shape without that field is perfectly valid for cash.
    assert_error_envelope(
        client.create_distribution(
            payee["id"],
            factories.distribution_payload(
                payee["version"], 400000, election=ELECTION_DIRECT_ROLLOVER
            ),
            payee_acts,
        ),
        api_errors.ERR_ROLLOVER_INSTITUTION_REQUIRED,
        422,
    )
    untouched = fixtures.read_ap_account(client, payee["id"])
    assert untouched["balance_cents"] == 400000
    assert untouched["version"] == payee["version"]

    cash = fixtures.issue_distribution(
        client, payee["id"], untouched["version"], 100000, headers=payee_acts
    )
    assert_settlement(
        cash,
        gross_amount_cents=100000,
        basis_recovery_cents=0,
        taxable_amount_cents=100000,
        federal_withheld_cents=20000,
        net_before_fee_cents=80000,
        admin_fee_cents=2500,
        net_amount_cents=77500,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    after_cash = fixtures.read_ap_account(client, payee["id"])
    rollover = fixtures.issue_distribution(
        client,
        payee["id"],
        after_cash["version"],
        300000,
        headers=payee_acts,
        election=ELECTION_DIRECT_ROLLOVER,
        rollover_institution="Vanguard Fiduciary Trust",
    )
    # Zero withholding lifts the same gross into the middle fee tier, so the
    # tier is keyed on the post-withholding figure.
    assert_settlement(
        rollover,
        gross_amount_cents=300000,
        basis_recovery_cents=0,
        taxable_amount_cents=300000,
        federal_withheld_cents=0,
        net_before_fee_cents=300000,
        admin_fee_cents=5000,
        net_amount_cents=295000,
        distribution_code=DISTRIBUTION_CODE_G,
        tax_year=2026,
    )

    closed = fixtures.read_ap_account(client, payee["id"])
    assert closed["status"] == AP_ACCOUNT_CLOSED
    assert_ap_account_totals(
        closed,
        fixtures.read_distributions(client, payee["id"]),
        established_balance_cents=400000,
        established_basis_cents=0,
    )
    assert closed["balance_cents"] == 0
    assert closed["total_distributed_gross_cents"] == 400000, (
        "only the two accepted elections moved money"
    )


def test_a_void_is_legal_on_the_last_second_of_the_tax_year_and_not_after(client):
    """The void window compares calendar years, never elapsed time.

    PRD: "a void requires the logical clock's calendar year to equal the
    distribution's `tax_year` (`ERR_VOID_ACROSS_TAX_YEARS`)"

    Design: Corner/validations/a_void_is_legal_on_the_last_second_of_the_tax_year_and_illegal_one_second_later
    """
    setup = fixtures.setup_qualified_separate_interest(
        client,
        "Tax Year Plan",
        plan_overrides=ONE_FORMULA_PLAN,
        qualify_clock=constants.CLOCK_2026_09_15,
    )
    payee = setup["ap_account"]
    assert payee["balance_cents"] == 400000
    assert payee["after_tax_basis_cents"] == 0

    first = fixtures.issue_distribution(client, payee["id"], payee["version"], 100000)
    assert_settlement(
        first,
        gross_amount_cents=100000,
        basis_recovery_cents=0,
        taxable_amount_cents=100000,
        federal_withheld_cents=20000,
        net_before_fee_cents=80000,
        admin_fee_cents=2500,
        net_amount_cents=77500,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    original_lines = fixtures.read_tax_reports(client, distribution_id=first["id"])
    assert len(original_lines) == 1
    assert_tax_line(
        original_lines[0],
        reportable_gross_cents=100000,
        reportable_taxable_cents=100000,
        federal_withheld_cents=20000,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
        correction_of_tax_report_id=None,
    )

    # Three and a half months later, on the last second of the same tax year.
    moved = fixtures.set_clock(client, "2026-12-31T23:59:59Z")
    assert moved["previous_utc"] == constants.CLOCK_2026_09_15, (
        "the two voids differ only in the instant they are observed from"
    )
    before_void = fixtures.read_ap_account(client, payee["id"])
    assert before_void["balance_cents"] == 300000

    voided = fixtures.void_distribution(client, first["id"])
    assert voided["status"] == DISTRIBUTION_VOIDED
    assert voided["voided_at"] == "2026-12-31T23:59:59Z"
    assert voided["tax_year"] == 2026, "the year is the one it was issued in"

    restored = fixtures.read_ap_account(client, payee["id"])
    assert restored["version"] == before_void["version"] + 1
    assert restored["balance_cents"] == 400000
    assert restored["total_distributed_gross_cents"] == 0, (
        "the totals are re-derived from the ISSUED set alone"
    )

    # A second distribution priced identically, issued at that same last second.
    second = fixtures.issue_distribution(
        client, payee["id"], restored["version"], 100000
    )
    assert_settlement(
        second, tax_year=2026, net_amount_cents=77500, federal_withheld_cents=20000
    )
    assert second["issued_at"] == "2026-12-31T23:59:59Z"

    # One second of clock movement, and the operation that just succeeded is
    # refused on the byte-identical request.
    fixtures.set_clock(client, "2027-01-01T00:00:00Z")
    assert_error_envelope(
        client.void_distribution(second["id"], ADMIN_HEADERS),
        api_errors.ERR_VOID_ACROSS_TAX_YEARS,
        409,
    )
    unchanged = validate_success(client.get_distribution(second["id"], ADMIN_HEADERS))
    assert unchanged["status"] == DISTRIBUTION_ISSUED
    assert unchanged["voided_at"] is None

    ledger = fixtures.read_tax_reports(
        client, alternate_payee_account_id=payee["id"]
    )
    assert len(ledger) == 3, "the refused void appended nothing at all"
    assert_tax_line(
        ledger[1],
        reportable_gross_cents=-100000,
        reportable_taxable_cents=-100000,
        federal_withheld_cents=-20000,
        tax_year=2026,
        correction_of_tax_report_id=ledger[0]["id"],
    )
    assert_tax_line(
        ledger[2],
        reportable_gross_cents=100000,
        reportable_taxable_cents=100000,
        federal_withheld_cents=20000,
        tax_year=2026,
        correction_of_tax_report_id=None,
    )
    assert_tax_ledger_totals(ledger, 100000, 100000, 20000)
