"""The declared status machines: entry points, legal edges and terminal states.

Every machine is exercised through the endpoints that drive it — the plan's
procedures cycle, the draft order's review gates, the payee account's closure,
the two opposite idempotency contracts, and the approach-conditional shape of
the qualification cascade.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
    assert_settlement,
    assert_sweep_found_nothing,
    assert_sweep_report,
    assert_tax_line,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    make_admin_headers,
)
from test_helpers.types import (
    AP_ACCOUNT_CLOSED,
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    APPROACH_SHARED_PAYMENT,
    AUTHORIZATION_ACTIVE,
    AUTHORIZATION_REVOKED,
    DENIAL_MAX_REVISIONS_EXCEEDED,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DISTRIBUTION_CODE_2,
    DISTRIBUTION_CODE_7,
    DISTRIBUTION_ISSUED,
    DRAFT_DEFICIENT,
    DRAFT_QUALIFIED,
    DRAFT_UNDER_REVIEW,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    HOLD_RELEASED,
    NOTICE_ISSUED,
    PAYMENT_MODE_SHARED_PAYMENT,
    PROCEDURES_AMENDMENT_PENDING,
    PROCEDURES_DRAFT,
    PROCEDURES_PUBLISHED,
    PROVISION_LUMP_SUM_ELECTION,
    REVIEW_DEFICIENT,
    REVIEW_DENIED,
    REVIEW_QUALIFIED,
    REVIEW_INTAKE,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SEGREGATION_LAPSED,
    SEGREGATION_NONE,
    SEGREGATION_RELEASED_TO_PARTICIPANT,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_SEGREGATION_LAPSE_NOTICE,
)

ONE_FORMULA = [FORMULA_PERCENTAGE_OF_ACCOUNT]


def test_new_rows_start_at_their_entry_points_on_the_startup_clock(client):
    """Seven dimensions enter at their declared values and windows run from the default clock.

    PRD: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    # No clock is set anywhere in this test: every window below is measured
    # from the startup default instant.
    plan = fixtures.create_plan(
        client,
        plan_name="Initial Plan",
        acceptable_formula_codes=ONE_FORMULA,
        requires_model_language=True,
    )
    assert plan["procedures_status"] == PROCEDURES_DRAFT, "a plan is never born published"
    assert plan["version"] == 1
    fixtures.set_procedures(client, plan["id"], PROCEDURES_PUBLISHED)
    participant = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="Nadia Farouk",
        ssn_last4="6767",
        date_of_birth="1973-06-06",
        participation_start_date="2004-01-01",
    )
    account = fixtures.open_plan_account(client, participant["id"])
    fixtures.add_money_source(
        client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
    )

    case = fixtures.open_case(
        client,
        participant["id"],
        alternate_payee_name="Samir Farouk",
        alternate_payee_dob="1975-05-05",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    assert_case_dimensions(
        case,
        review_status=REVIEW_INTAKE,
        segregation_status=SEGREGATION_NONE,
        version=1,
    )

    authorization = fixtures.authorize_attorney(
        client,
        case["id"],
        attorney_name="Counsel Initial",
        attorney_bar_number="BAR-9",
        attorney_email="ci@bar.example",
        effective_from="2026-07-01",
        expires_at="2027-07-01T00:00:00Z",
    )
    assert authorization["status"] == AUTHORIZATION_ACTIVE
    assert authorization["revoked_at"] is None

    draft = fixtures.receive_draft(
        client,
        case["id"],
        fixtures.read_case(client, case["id"])["version"],
        document_reference="DRO-2663-INIT",
        uses_model_language=False,
    )
    assert draft["status"] == DRAFT_UNDER_REVIEW
    assert draft["revision_number"] == 1
    assert draft["review_deadline_at"] == "2026-09-15T00:00:00Z"

    hold = fixtures.hold_for_case(client, case["id"])
    assert_hold(
        hold,
        status=HOLD_HELD,
        expires_at="2028-01-31T00:00:00Z",
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )

    notice = fixtures.issue_notice(client, draft["id"], reviewer_notes="no model language")
    assert notice["status"] == NOTICE_ISSUED
    assert notice["notice_sequence"] == 1
    assert notice["resubmission_deadline_at"] == "2026-09-30T00:00:00Z"

    # The notice moved only the review dimension; custody is untouched by it.
    assert_case_dimensions(
        fixtures.read_case(client, case["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
    )


def test_the_procedures_cycle_is_re_traversable_and_versions_every_hop(client):
    """Publication and amendment form a genuine cycle with no terminal state.

    PRD: "A published plan may pull its procedures back for amendment, moving
    `PUBLISHED` to `AMENDMENT_PENDING`, and may re-publish them, moving
    `AMENDMENT_PENDING` back to `PUBLISHED`."

    PRD: "Each of the three transitions increments the plan's `version` by one."

    Design: Corner/state_machines/plan_procedure_status_traverses_its_declared_cycle
    """
    plan = fixtures.create_plan(
        client,
        plan_name="Cycle Plan",
        acceptable_formula_codes=[
            FORMULA_PERCENTAGE_OF_ACCOUNT,
            "FLAT_DOLLAR",
        ],
    )
    assert plan["version"] == 1

    walk = [
        PROCEDURES_PUBLISHED,
        PROCEDURES_AMENDMENT_PENDING,
        PROCEDURES_PUBLISHED,
        PROCEDURES_AMENDMENT_PENDING,
    ]
    observed = []
    for index, to_status in enumerate(walk, start=2):
        row = fixtures.set_procedures(client, plan["id"], to_status)
        observed.append((row["procedures_status"], row["version"]))
        assert row["version"] == index, "a declared hop moves the version exactly once"
    assert observed == [
        (PROCEDURES_PUBLISHED, 2),
        (PROCEDURES_AMENDMENT_PENDING, 3),
        (PROCEDURES_PUBLISHED, 4),
        (PROCEDURES_AMENDMENT_PENDING, 5),
    ]

    final = validate_success(client.get_plan(plan["id"], ADMIN_HEADERS))
    assert final["procedures_status"] == PROCEDURES_AMENDMENT_PENDING
    assert final["version"] == 5
    assert final["plan_name"] == "Cycle Plan"
    assert final["acceptable_formula_codes"] == plan["acceptable_formula_codes"]
    assert final["allowed_approaches"] == plan["allowed_approaches"]

    # No terminal state: the cycle accepts yet another publication.
    again = fixtures.set_procedures(client, plan["id"], PROCEDURES_PUBLISHED)
    assert (again["procedures_status"], again["version"]) == (PROCEDURES_PUBLISHED, 6)


def test_undeclared_procedure_edges_move_neither_status_nor_version(client):
    """Only three edges exist, and a refusal is never a silent success.

    PRD: "No other movement exists: `DRAFT` to `AMENDMENT_PENDING` is not a
    declared transition, and neither is any movement *into* `DRAFT`; both are
    rejected with `ERR_PROCEDURE_STATUS_TRANSITION_INVALID`."

    Design: Corner/state_machines/undeclared_procedure_status_edges_are_rejected
    """
    draft_plan = fixtures.create_plan(
        client, plan_name="Draft Only", acceptable_formula_codes=ONE_FORMULA
    )
    amending = fixtures.create_plan(
        client, plan_name="Amending", acceptable_formula_codes=ONE_FORMULA
    )
    fixtures.set_procedures(client, amending["id"], PROCEDURES_PUBLISHED)
    pending = fixtures.set_procedures(
        client, amending["id"], PROCEDURES_AMENDMENT_PENDING
    )
    assert pending["version"] == 3

    refusals = [
        # A legal-looking destination that no transition out of DRAFT permits.
        (draft_plan["id"], PROCEDURES_AMENDMENT_PENDING),
        # Self-edges are undeclared on both statuses.
        (draft_plan["id"], PROCEDURES_DRAFT),
        (amending["id"], PROCEDURES_AMENDMENT_PENDING),
        # And nothing may move back into DRAFT.
        (amending["id"], PROCEDURES_DRAFT),
    ]
    for plan_id, to_status in refusals:
        assert_error_envelope(
            client.set_procedure_status(
                plan_id, factories.procedure_status_payload(to_status), ADMIN_HEADERS
            ),
            api_errors.ERR_PROCEDURE_STATUS_TRANSITION_INVALID,
            409,
        )

    # An undeclared literal is refused one rung earlier than the state check.
    assert_error_envelope(
        client.set_procedure_status(
            draft_plan["id"],
            factories.procedure_status_payload("RETIRED"),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )

    still_draft = validate_success(client.get_plan(draft_plan["id"], ADMIN_HEADERS))
    assert (still_draft["procedures_status"], still_draft["version"]) == (
        PROCEDURES_DRAFT,
        1,
    )
    still_pending = validate_success(client.get_plan(amending["id"], ADMIN_HEADERS))
    assert (still_pending["procedures_status"], still_pending["version"]) == (
        PROCEDURES_AMENDMENT_PENDING,
        3,
    )


def test_a_faultless_draft_can_be_neither_noticed_nor_denied(client):
    """Both refusal paths read the recomputed deficiency set, not a stored flag.

    PRD: "Any other combination — a faultless `UNDER_REVIEW` draft offered as
    `ORDER_NOT_QUALIFIABLE`, a revision count below the cap offered as
    `MAX_REVISIONS_EXCEEDED`, an open window offered as
    `RESUBMISSION_WINDOW_CLOSED` — is refused with `ERR_DENIAL_NOT_PERMITTED`."

    Design: Corner/state_machines/a_clean_draft_order_blocks_both_notice_issuance_and_denial
    """
    plan = fixtures.create_published_plan(
        client,
        plan_name="Precondition Plan",
        acceptable_formula_codes=ONE_FORMULA,
        requires_model_language=True,
        max_revisions=3,
    )
    accounts = []
    for full_name, ssn, dob in (
        ("Clean Claimant", "1010", "1972-10-10"),
        ("Deficient Claimant", "1111", "1972-11-11"),
    ):
        participant = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=full_name,
            ssn_last4=ssn,
            date_of_birth=dob,
            participation_start_date="2004-01-01",
        )
        account = fixtures.open_plan_account(client, participant["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
        )
        accounts.append(participant)
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    clean_case = fixtures.open_case(
        client,
        accounts[0]["id"],
        alternate_payee_name="Clean AP",
        alternate_payee_dob="1974-04-04",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    clean_draft = fixtures.receive_draft(
        client,
        clean_case["id"],
        clean_case["version"],
        document_reference="DRO-2663-CLEAN",
        provisions=[PROVISION_LUMP_SUM_ELECTION],
    )
    assert clean_draft["deficiency_codes"] == [], (
        "a lump-sum election is not a prohibited provision"
    )

    faulty_case = fixtures.open_case(
        client,
        accounts[1]["id"],
        alternate_payee_name="Deficient AP",
        alternate_payee_dob="1974-04-04",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    faulty_draft = fixtures.receive_draft(
        client,
        faulty_case["id"],
        faulty_case["version"],
        document_reference="DRO-2663-DEFCT",
        uses_model_language=False,
    )
    first_notice = fixtures.issue_notice(
        client, faulty_draft["id"], reviewer_notes="missing model language"
    )
    assert first_notice["notice_sequence"] == 1

    # The notice path recomputes the set and refuses to manufacture a fault.
    assert_error_envelope(
        client.create_deficiency_notice(
            clean_draft["id"],
            factories.deficiency_notice_payload(
                reviewer_notes="nothing wrong, but try anyway"
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_NO_DEFICIENCIES_TO_REPORT,
        409,
    )
    # A compliant order can only be qualified, never denied as unqualifiable.
    assert_error_envelope(
        client.deny_draft_order(
            clean_draft["id"],
            factories.denial_payload(DENIAL_ORDER_NOT_QUALIFIABLE),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_DENIAL_NOT_PERMITTED,
        409,
    )
    # The named reason must be true: revision 1 is below the cap of 3.
    assert_error_envelope(
        client.deny_draft_order(
            faulty_draft["id"],
            factories.denial_payload(DENIAL_MAX_REVISIONS_EXCEEDED),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_DENIAL_NOT_PERMITTED,
        409,
    )
    # And ORDER_NOT_QUALIFIABLE is admissible only from UNDER_REVIEW.
    assert_error_envelope(
        client.deny_draft_order(
            faulty_draft["id"],
            factories.denial_payload(DENIAL_ORDER_NOT_QUALIFIABLE),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_DENIAL_NOT_PERMITTED,
        409,
    )

    still_clean = fixtures.read_draft(client, clean_draft["id"])
    assert still_clean["status"] == DRAFT_UNDER_REVIEW
    assert still_clean["denial_reason"] is None
    still_faulty = fixtures.read_draft(client, faulty_draft["id"])
    assert still_faulty["status"] == DRAFT_DEFICIENT
    assert still_faulty["denial_reason"] is None
    assert_case_dimensions(
        fixtures.read_case(client, clean_case["id"]),
        review_status=REVIEW_UNDER_REVIEW,
    )
    assert_case_dimensions(
        fixtures.read_case(client, faulty_case["id"]), review_status=REVIEW_DEFICIENT
    )
    assert fixtures.read_notices(client, clean_draft["id"]) == [], (
        "the refused notice was not persisted"
    )


def test_an_exhausting_payment_freezes_three_machines_at_once(client):
    """Closure is terminal, and the terminal-state check outranks the balance check.

    PRD: "Capacity is checked against the pool the payee can actually draw on:
    for a separate-interest account the requested gross may not exceed the payee
    account's `balance_cents`, and for a shared-payment account it may not exceed
    the participant's `available_balance_cents`."

    Design: Corner/state_machines/exhausted_payee_account_is_terminal_in_three_machines_at_once
    """
    setup = fixtures.setup_qualified_separate_interest(
        client,
        "Lockdown Plan",
        plan_overrides={"acceptable_formula_codes": ONE_FORMULA},
        participant_overrides={
            "full_name": "Terminal Participant",
            "ssn_last4": "2020",
            "date_of_birth": "1971-02-02",
            "participation_start_date": "2004-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Terminal Payee",
            "alternate_payee_dob": "1975-05-05",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-LOCK"},
    )
    payee = setup["ap_account"]
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED
    assert payee["balance_cents"] == 400000, (
        "no snapshot exists on or after 2026-09-15, so earnings are zero"
    )
    assert payee["version"] == 1

    distribution = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        400000,
        headers=fixtures.payee_headers(payee),
    )
    assert distribution["status"] == DISTRIBUTION_ISSUED
    assert_settlement(
        distribution,
        gross_amount_cents=400000,
        basis_recovery_cents=0,
        taxable_amount_cents=400000,
        federal_withheld_cents=80000,
        net_before_fee_cents=320000,
        admin_fee_cents=5000,
        net_amount_cents=315000,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    closed = fixtures.read_ap_account(client, payee["id"])
    assert closed["status"] == AP_ACCOUNT_CLOSED
    assert closed["balance_cents"] == 0
    assert closed["version"] == 2, (
        "the exhausting payment closed the account in the same request"
    )

    # A one-cent request reports the terminal state, not an overdraft.
    assert_error_envelope(
        client.create_distribution(
            payee["id"],
            factories.distribution_payload(closed["version"], 1),
            fixtures.payee_headers(payee),
        ),
        api_errors.ERR_AP_ACCOUNT_CLOSED,
        409,
    )
    # The payment is still ISSUED and still inside its tax year, so the only
    # ground for refusing the reversal is the account's terminal state.
    assert_error_envelope(
        client.void_distribution(distribution["id"], ADMIN_HEADERS),
        api_errors.ERR_AP_ACCOUNT_CLOSED,
        409,
    )
    assert_error_envelope(
        client.qualify_draft_order(setup["draft"]["id"], make_admin_headers("admin-6")),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )
    assert_error_envelope(
        client.release_segregation_hold(setup["hold"]["id"], ADMIN_HEADERS),
        api_errors.ERR_HOLD_NOT_HELD,
        409,
    )

    assert setup["draft"]["status"] == DRAFT_QUALIFIED
    assert setup["hold"]["status"] == HOLD_CONVERTED
    frozen = validate_success(
        client.get_distribution(distribution["id"], ADMIN_HEADERS)
    )
    assert frozen["status"] == DISTRIBUTION_ISSUED
    ledger = fixtures.read_tax_reports(
        client, alternate_payee_account_id=payee["id"]
    )
    assert len(ledger) == 1, "the refused void appended no corrective line"
    assert_tax_line(ledger[0], correction_of_tax_report_id=None)
    assert fixtures.read_ap_account(client, payee["id"])["version"] == 2


def test_a_second_revoke_is_an_error_while_a_second_sweep_is_a_no_op(client):
    """Two opposite idempotency contracts coexist in the same system.

    PRD: "A revocation attempted on an authorization that is already `REVOKED`
    is refused with `ERR_AUTHORIZATION_NOT_ACTIVE`."

    PRD: "Sweeps are idempotent with respect to a fixed clock: a second run at
    the same instant finds nothing left to do."

    Design: Corner/state_machines/repeated_triggers_are_refused_or_are_true_no_ops
    """
    setup = fixtures.setup_case_with_held_hold(
        client,
        "Idempotent Plan",
        snapshots=(),
        plan_overrides={"acceptable_formula_codes": ONE_FORMULA},
        participant_overrides={
            "full_name": "Repeat Participant",
            "ssn_last4": "3030",
            "date_of_birth": "1970-03-03",
            "participation_start_date": "2004-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Repeat Payee",
            "alternate_payee_dob": "1974-04-04",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-IDEM"},
    )
    authorization = fixtures.authorize_attorney(
        client,
        setup["case"]["id"],
        represents="ALTERNATE_PAYEE",
        attorney_name="Twice Revoked",
        attorney_bar_number="BAR-4",
        attorney_email="tr@bar.example",
        disclosure_scope="LIMITED",
    )
    assert setup["hold"]["expires_at"] == constants.CLOCK_2028_03_02
    fixtures.set_clock(client, constants.CLOCK_2028_03_02_PLUS_1S)

    revoked = fixtures.revoke_authorization(client, authorization["id"])
    assert revoked["status"] == AUTHORIZATION_REVOKED
    assert revoked["revoked_at"] == constants.CLOCK_2028_03_02_PLUS_1S

    assert_error_envelope(
        client.revoke_attorney_authorization(authorization["id"], ADMIN_HEADERS),
        api_errors.ERR_AUTHORIZATION_NOT_ACTIVE,
        409,
    )
    dead = validate_success(
        client.list_attorney_authorizations(
            setup["case"]["id"], ADMIN_HEADERS, {"status": AUTHORIZATION_REVOKED}
        )
    )
    assert len(dead) == 1
    assert dead[0]["revoked_at"] == constants.CLOCK_2028_03_02_PLUS_1S, (
        "the refused second revoke did not restamp the instant"
    )

    first_sweep = fixtures.run_sweep(client)
    assert_sweep_report(
        first_sweep,
        expired_hold_ids=[setup["hold"]["id"]],
        lapsed_case_ids=[setup["case"]["id"]],
        denied_draft_order_ids=[setup["draft"]["id"]],
        expired_notice_ids=[],
        closed_ap_account_ids=[],
    )
    after_first = fixtures.read_case(client, setup["case"]["id"])
    assert_case_dimensions(
        after_first,
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
    )

    second_sweep = fixtures.run_sweep(client)
    assert_sweep_found_nothing(second_sweep)
    after_second = fixtures.read_case(client, setup["case"]["id"])
    assert_case_dimensions(
        after_second,
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=after_first["version"],
    )

    lapse_notices = fixtures.read_communications(
        client, setup["case"]["id"], template_code=TEMPLATE_SEGREGATION_LAPSE_NOTICE
    )
    assert len(lapse_notices) == 2, "the lapse correspondence was appended once"
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        held_amount_cents=0,
        available_balance_cents=1000000,
    )


def test_a_shared_payment_qualification_releases_instead_of_converting(client):
    """The cascade's lower levels branch entirely on the case's approach.

    PRD: "For a `SHARED_PAYMENT` case the hold moves `HELD → RELEASED` instead:
    `segregation_date` stays null and both `earnings_growth_bps` and
    `earnings_adjustment_cents` stay at 0, because nothing was ever carved out
    to earn anything."

    Design: Corner/state_machines/shared_payment_qualification_releases_instead_of_converting
    """
    setup = fixtures.setup_case_with_held_hold(
        client,
        "Shared Plan",
        snapshots=(("2026-06-30", 1000000),),
        plan_overrides={
            "acceptable_formula_codes": ONE_FORMULA,
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST, APPROACH_SHARED_PAYMENT],
            "requires_model_language": True,
        },
        participant_overrides={
            "full_name": "Retired Participant",
            "ssn_last4": "4040",
            "date_of_birth": "1958-04-04",
            "participation_start_date": "1990-01-01",
            "benefit_commenced": True,
        },
        account_overrides={"monthly_payment_cents": 320000},
        case_overrides={
            "alternate_payee_name": "Shared Payee",
            "alternate_payee_dob": "1960-01-15",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": "DRO-2663-SHARE",
            "proposed_approach": APPROACH_SHARED_PAYMENT,
            "proposed_shared_payment_end_date": "2027-12-31",
        },
    )
    assert setup["hold"]["hold_amount_cents"] == 400000
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    determined = fixtures.qualify(client, setup["draft"]["id"])
    assert determined["status"] == DRAFT_QUALIFIED

    assert_hold(
        fixtures.read_hold(client, setup["hold"]["id"]),
        status=HOLD_RELEASED,
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_RELEASED_TO_PARTICIPANT,
    )

    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["payment_mode"] == PAYMENT_MODE_SHARED_PAYMENT
    assert payee["balance_cents"] == 0
    assert payee["per_period_amount_cents"] == 128000
    assert payee["shared_payment_end_date"] == "2027-12-31"

    # No money source was debited: this is the divergence from separate interest.
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        assignable_base_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )

    assert_error_envelope(
        client.create_distribution(
            payee["id"],
            factories.distribution_payload(payee["version"], 128001),
            fixtures.payee_headers(payee),
        ),
        api_errors.ERR_SHARED_PAYMENT_AMOUNT_MISMATCH,
        422,
    )
    slice_paid = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        128000,
        headers=fixtures.payee_headers(payee),
    )
    assert_settlement(
        slice_paid,
        basis_recovery_cents=0,
        taxable_amount_cents=128000,
        federal_withheld_cents=25600,
        net_before_fee_cents=102400,
        admin_fee_cents=5000,
        net_amount_cents=97400,
        distribution_code=DISTRIBUTION_CODE_7,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=872000,
        assignable_base_cents=872000,
    )
    drawn = fixtures.read_ap_account(client, payee["id"])
    assert drawn["balance_cents"] == 0
    assert drawn["total_distributed_gross_cents"] == 128000

    fixtures.set_clock(client, "2027-12-31T23:59:59Z")
    assert_sweep_report(fixtures.run_sweep(client), closed_ap_account_ids=[])
    fixtures.set_clock(client, "2028-01-01T00:00:00Z")
    assert_sweep_report(
        fixtures.run_sweep(client), closed_ap_account_ids=[payee["id"]]
    )
    swept = fixtures.read_ap_account(client, payee["id"])
    assert swept["status"] == AP_ACCOUNT_CLOSED
    assert swept["version"] > drawn["version"], (
        "a shared-payment account is closed by the sweep, never by exhaustion"
    )
