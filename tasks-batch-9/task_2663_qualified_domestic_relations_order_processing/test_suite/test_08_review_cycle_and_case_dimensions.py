"""Returning to a state the row already occupied, and two tracks on one row.

The review cycle is a loop rather than a ladder, so closing it must not amnesty
the reviewer; and a case's review track and custody track advance on different
triggers, so the pair they form is not derivable from either half.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_communication_sequence,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    REVIEWER_USER_ID,
    make_admin_headers,
    make_determiner_headers,
    make_reviewer_headers,
)
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_RESUBMISSION_WINDOW_CLOSED,
    DISCLOSURE_LIMITED,
    DRAFT_DEFICIENT,
    DRAFT_DENIED,
    DRAFT_QUALIFIED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    HOLD_RELEASED,
    NOTICE_CURED,
    NOTICE_EXPIRED,
    NOTICE_ISSUED,
    ORIGIN_SYSTEM,
    PROCEDURES_AMENDMENT_PENDING,
    PROCEDURES_PUBLISHED,
    RECIPIENT_PARTICIPANT,
    REVIEW_DEFICIENT,
    REVIEW_DENIED,
    REVIEW_QUALIFIED,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_CONVERTED,
    SEGREGATION_HELD,
    SEGREGATION_RELEASED_TO_PARTICIPANT,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
)

CYCLE_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "review_period_days": 45,
    "segregation_period_days": 548,
    "resubmission_window_days": 60,
    "max_revisions": 3,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}


def _noticed_by_the_reviewer(client, plan_name, member_name, payee_name, reference):
    """A draft carried to DEFICIENT by a notice from one identified analyst."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        plan_overrides=CYCLE_PLAN,
        participant_overrides={
            "full_name": member_name,
            "ssn_last4": "6602",
            "date_of_birth": "1977-10-10",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": payee_name,
            "alternate_payee_dob": "1979-06-06",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": reference,
            "uses_model_language": False,
        },
    )
    assert setup["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert setup["draft"]["status"] == DRAFT_UNDER_REVIEW
    assert setup["draft"]["reviewed_by_user_id"] is None
    setup["notice"] = fixtures.issue_notice(
        client,
        setup["draft"]["id"],
        headers=make_reviewer_headers(),
        reviewer_notes="order omits the plan's model language",
    )
    setup["draft"] = fixtures.read_draft(client, setup["draft"]["id"])
    return setup


def test_closing_the_review_loop_does_not_forget_who_rejected_the_order(client):
    """Back at UNDER_REVIEW the row is advanced, not reset: the reviewer is kept.

    PRD: "when an analyst issues a rejection notice, that analyst's `X-User-ID`
    is written to the draft order's `reviewed_by_user_id`. That recorded value is
    compared only against a later qualifier's `X-User-ID`, never against any
    entity's `id`."

    Design: Difficulty/non_linear_state_machine/draft_order_deficiency_revision_cycle_preserves_review_memory
    """
    setup = _noticed_by_the_reviewer(
        client, "Cycle Memory Plan", "Teodor Ilves", "Kaja Ilves", "DRO-2663-C1"
    )
    draft_id = setup["draft"]["id"]
    assert setup["draft"]["status"] == DRAFT_DEFICIENT
    assert setup["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert setup["draft"]["revision_number"] == 1
    assert setup["draft"]["reviewed_by_user_id"] == REVIEWER_USER_ID
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
    )

    # The loop closes: DEFICIENT returns to UNDER_REVIEW on a resubmission.
    revised = fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-C1-rev2",
        uses_model_language=True,
    )
    assert revised["status"] == DRAFT_UNDER_REVIEW
    assert revised["revision_number"] == 2
    assert revised["deficiency_codes"] == []
    assert revised["reviewed_by_user_id"] == REVIEWER_USER_ID, (
        "the reviewer marker is memory, not a property of the current state"
    )

    notices = fixtures.read_notices(client, draft_id)
    assert len(notices) == 1
    assert notices[0]["id"] == setup["notice"]["id"]
    assert notices[0]["notice_sequence"] == 1
    assert notices[0]["status"] == NOTICE_CURED
    assert notices[0]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert notices[0]["resubmission_deadline_at"] == constants.CLOCK_2026_10_31

    # The row is once again in the state it started in, yet the analyst who
    # rejected it still cannot sign the determination.
    assert_error_envelope(
        client.qualify_draft_order(draft_id, make_admin_headers(REVIEWER_USER_ID)),
        api_errors.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unchanged = fixtures.read_draft(client, draft_id)
    assert unchanged["status"] == DRAFT_UNDER_REVIEW
    assert unchanged["revision_number"] == 2
    assert unchanged["deficiency_codes"] == []
    assert fixtures.read_ap_accounts(client, setup["case"]["id"]) == []
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
    )


def test_the_terminal_state_refuses_the_two_loop_entries_differently(client):
    """Once qualified the order cannot be re-noticed and cannot be resubmitted.

    PRD: "issuing a rejection notice and qualifying both require the draft order
    to be `UNDER_REVIEW` (`ERR_DRAFT_ORDER_NOT_UNDER_REVIEW`); resubmitting
    requires it to be `DEFICIENT` (`ERR_DRAFT_ORDER_NOT_DEFICIENT`)"

    Design: Difficulty/non_linear_state_machine/draft_order_deficiency_revision_cycle_preserves_review_memory
    """
    setup = _noticed_by_the_reviewer(
        client, "Cycle Exit Plan", "Teodor Ilves", "Kaja Ilves", "DRO-2663-C2"
    )
    draft_id = setup["draft"]["id"]
    cured = fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-C2-rev2",
        uses_model_language=True,
    )
    assert cured["deficiency_codes"] == []

    # A different human signs, and the reviewer marker survives the signing.
    determined = fixtures.qualify(client, draft_id, headers=make_determiner_headers())
    assert determined["status"] == DRAFT_QUALIFIED
    assert determined["revision_number"] == 2
    assert determined["reviewed_by_user_id"] == REVIEWER_USER_ID, (
        "the memory is never cleared, not even by the determination"
    )

    # The two triggers that would re-enter the loop fail for two different
    # reasons, because each names the state it needs rather than the state it
    # forbids.
    assert_error_envelope(
        client.create_deficiency_notice(
            draft_id, factories.deficiency_notice_payload(), ANALYST_HEADERS
        ),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )
    assert_error_envelope(
        client.resubmit_draft_order(
            draft_id,
            factories.resubmission_payload(
                document_reference="DRO-2663-C2-rev3", uses_model_language=True
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_DRAFT_ORDER_NOT_DEFICIENT,
        409,
    )

    final = fixtures.read_draft(client, draft_id)
    assert final["status"] == DRAFT_QUALIFIED
    assert final["revision_number"] == 2
    assert final["document_reference"] == "DRO-2663-C2-rev2"
    assert [row["status"] for row in fixtures.read_notices(client, draft_id)] == [
        NOTICE_CURED
    ], "a refused notice attempt appended nothing"

    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
    )
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        segregation_date="2026-09-01",
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["balance_cents"] == 400000
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=600000,
        held_amount_cents=0,
        available_balance_cents=600000,
    )


def _two_dimension_setup(client, plan_name):
    """One receipt, which is the single call that moves both of a case's tracks."""
    return fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        plan_overrides=CYCLE_PLAN,
        participant_overrides={
            "full_name": "Halvard Sund",
            "ssn_last4": "7719",
            "date_of_birth": "1975-01-20",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Ingrid Sund",
            "alternate_payee_dob": "1978-02-02",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": "DRO-2663-D1",
            "uses_model_language": False,
        },
    )


def test_the_review_track_reaches_its_end_with_the_money_still_segregated(client):
    """A denied case is finished and holding the participant's cash at once.

    PRD: "Neither dimension gates the other's progress except where this document
    says so: a case may sit at `review_status` `DEFICIENT` with
    `segregation_status` `HELD`, or at `review_status` `UNDER_REVIEW` with
    `segregation_status` `LAPSED`."

    Design: Difficulty/non_linear_state_machine/qdro_case_parallel_review_and_segregation_dimensions
    """
    setup = _two_dimension_setup(client, "Two Dimensions Plan")
    draft_id = setup["draft"]["id"]

    # One call advanced both tracks together.
    assert_case_dimensions(
        setup["case"],
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=2,
    )
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )

    # A notice moves the review track alone; the custody track is frozen.
    notice = fixtures.issue_notice(
        client,
        draft_id,
        headers=make_reviewer_headers(),
        reviewer_notes="model language missing",
    )
    assert notice["status"] == NOTICE_ISSUED
    assert notice["resubmission_deadline_at"] == constants.CLOCK_2026_10_31
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
        version=3,
    )
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
    )

    # One day past the deadline the closed window is an observable fact, so the
    # denial reason matches and the review track terminates.
    fixtures.set_clock(client, constants.CLOCK_2026_11_01)
    denied = fixtures.deny(client, draft_id, DENIAL_RESUBMISSION_WINDOW_CLOSED)
    assert denied["status"] == DRAFT_DENIED
    assert denied["denial_reason"] == DENIAL_RESUBMISSION_WINDOW_CLOSED
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_HELD,
        version=4,
    )
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    assert [row["status"] for row in fixtures.read_notices(client, draft_id)] == [
        NOTICE_EXPIRED
    ], "the denial expired a notice that was never cured"


def test_the_custody_track_advances_only_on_its_own_explicit_second_act(client):
    """Release is guarded by the other track, and then by the hold's own state.

    PRD: "it is permitted only while the hold is still `HELD` (otherwise
    `ERR_HOLD_NOT_HELD`) and only once the hold's case has actually reached
    `review_status` `DENIED` (otherwise `ERR_CASE_NOT_DENIED`) — funds cannot go
    back to the participant while an order is still live."

    Design: Difficulty/non_linear_state_machine/qdro_case_parallel_review_and_segregation_dimensions
    """
    setup = _two_dimension_setup(client, "Release Guard Plan")
    draft_id = setup["draft"]["id"]
    hold_id = setup["hold"]["id"]

    # The hold itself is validly HELD, so the refusal can only come from the
    # other dimension.
    assert setup["hold"]["status"] == HOLD_HELD
    assert_error_envelope(
        client.release_segregation_hold(hold_id, ADMIN_HEADERS),
        api_errors.ERR_CASE_NOT_DENIED,
        409,
    )
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=2,
    )

    fixtures.issue_notice(
        client,
        draft_id,
        headers=make_reviewer_headers(),
        reviewer_notes="model language missing",
    )
    fixtures.set_clock(client, constants.CLOCK_2026_11_01)
    fixtures.deny(client, draft_id, DENIAL_RESUBMISSION_WINDOW_CLOSED)

    released = fixtures.release_hold(client, hold_id)
    assert released["status"] == HOLD_RELEASED
    assert released["hold_amount_cents"] == 400000
    assert released["segregation_date"] is None, (
        "nothing was carved out, so no segregation date is stamped"
    )
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_RELEASED_TO_PARTICIPANT,
        version=5,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )

    # The hold's own terminal state now locks it down independently of the case.
    assert_error_envelope(
        client.release_segregation_hold(hold_id, ADMIN_HEADERS),
        api_errors.ERR_HOLD_NOT_HELD,
        409,
    )
    assert fixtures.read_hold(client, hold_id)["status"] == HOLD_RELEASED
    assert fixtures.read_ap_accounts(client, setup["case"]["id"]) == [], (
        "a denied case never establishes a payee account, terminal custody or not"
    )


def _two_faultless_cases(client, plan_name):
    """Two members of one plan, one already carrying a faultless received draft."""
    plan = fixtures.create_published_plan(client, plan_name=plan_name, **CYCLE_PLAN)
    built = {"plan": plan, "members": {}}
    for full_name, ssn_last4 in (("Ingrid Halvorsen", "2201"), ("Odd Halvorsen", "2202")):
        member = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=full_name,
            ssn_last4=ssn_last4,
            date_of_birth="1976-02-02",
            participation_start_date="2010-01-01",
        )
        account = fixtures.open_plan_account(client, member["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
        )
        fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
        built["members"][ssn_last4] = {"participant": member, "account": account}
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    for ssn_last4, payee in (("2201", "Marit Halvorsen"), ("2202", "Sigrid Halvorsen")):
        built["members"][ssn_last4]["case"] = fixtures.open_case(
            client,
            built["members"][ssn_last4]["participant"]["id"],
            alternate_payee_name=payee,
            alternate_payee_dob="1978-06-06",
            marital_period_start="2012-03-01",
            marital_period_end="2026-02-01",
        )
    first = built["members"]["2201"]
    first["draft"] = fixtures.receive_draft(
        client,
        first["case"]["id"],
        first["case"]["version"],
        document_reference="DRO-2663-P-A",
    )
    assert first["draft"]["deficiency_codes"] == [], (
        "the draft must be faultless so a later refusal cannot be blamed on it"
    )
    return built


def test_pulling_procedures_back_blocks_the_signature_but_not_a_receipt(client):
    """A faultless draft becomes unqualifiable three levels up the hierarchy.

    PRD: "While procedures sit in `AMENDMENT_PENDING`, in-flight orders are
    untouched — drafts continue to be received, reviewed, rejected and denied
    exactly as before — but no qualification determination may be signed, because
    determinations require procedures actually in force."

    Design: Difficulty/cross_entity_state_dependency/qualification_blocked_by_plan_procedures_amendment_pending
    """
    built = _two_faultless_cases(client, "Amendment Plan")
    first = built["members"]["2201"]
    second = built["members"]["2202"]

    pulled = fixtures.set_procedures(
        client, built["plan"]["id"], PROCEDURES_AMENDMENT_PENDING
    )
    assert pulled["procedures_status"] == PROCEDURES_AMENDMENT_PENDING

    assert_error_envelope(
        client.qualify_draft_order(first["draft"]["id"], ADMIN_HEADERS),
        api_errors.ERR_PLAN_PROCEDURES_NOT_PUBLISHED,
        409,
    )

    # The refusal is inert on every row the determination would have touched.
    assert fixtures.read_draft(client, first["draft"]["id"])["status"] == (
        DRAFT_UNDER_REVIEW
    )
    assert_case_dimensions(
        fixtures.read_case(client, first["case"]["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=2,
    )
    assert fixtures.read_ap_accounts(client, first["case"]["id"]) == []
    assert_communication_sequence(
        fixtures.read_communications(client, first["case"]["id"]),
        [
            (
                RECIPIENT_PARTICIPANT,
                TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
                DISCLOSURE_LIMITED,
                ORIGIN_SYSTEM,
            )
        ],
    )

    # Custody can still be taken while the procedures are being amended.
    sibling = fixtures.receive_draft(
        client,
        second["case"]["id"],
        second["case"]["version"],
        document_reference="DRO-2663-P-B",
    )
    assert sibling["status"] == DRAFT_UNDER_REVIEW
    assert sibling["deficiency_codes"] == []
    assert_hold(
        fixtures.hold_for_case(client, second["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, second["account"]["id"]),
        held_amount_cents=400000,
        available_balance_cents=600000,
    )


def test_republishing_makes_the_identical_request_succeed_untouched(client):
    """The amendment cycle is traversable, and it costs the order nothing.

    PRD: "A published plan may pull its procedures back for amendment, moving
    `PUBLISHED` to `AMENDMENT_PENDING`, and may re-publish them, moving
    `AMENDMENT_PENDING` back to `PUBLISHED`. That pair is a genuine cycle a plan
    may traverse repeatedly. Each of the three transitions increments the plan's
    `version` by one."

    Design: Difficulty/cross_entity_state_dependency/qualification_blocked_by_plan_procedures_amendment_pending
    """
    built = _two_faultless_cases(client, "Republish Plan")
    first = built["members"]["2201"]
    draft_id = first["draft"]["id"]

    fixtures.set_procedures(client, built["plan"]["id"], PROCEDURES_AMENDMENT_PENDING)
    assert_error_envelope(
        client.qualify_draft_order(draft_id, ADMIN_HEADERS),
        api_errors.ERR_PLAN_PROCEDURES_NOT_PUBLISHED,
        409,
    )

    republished = fixtures.set_procedures(
        client, built["plan"]["id"], PROCEDURES_PUBLISHED
    )
    assert republished["procedures_status"] == PROCEDURES_PUBLISHED

    # The byte-identical request now succeeds, with no resubmission in between.
    determined = validate_success(client.qualify_draft_order(draft_id, ADMIN_HEADERS))
    assert determined["status"] == DRAFT_QUALIFIED
    assert determined["revision_number"] == 1
    assert determined["document_reference"] == "DRO-2663-P-A"
    assert_case_dimensions(
        fixtures.read_case(client, first["case"]["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
    )
    payee = fixtures.ap_account_for_case(client, first["case"]["id"])
    assert payee["balance_cents"] == 400000
    assert_hold(
        fixtures.hold_for_case(client, first["case"]["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        segregation_date="2026-09-01",
    )
    assert len(fixtures.read_holds(client, qdro_case_id=first["case"]["id"])) == 1, (
        "no second hold was placed by the successful retry"
    )

    plan = validate_success(client.get_plan(built["plan"]["id"], ADMIN_HEADERS))
    assert plan["version"] == 6, (
        "version 1 on registration, one for each of the two enrolments — "
        "\"Enrolling a participant recomputes the plan's participant_count and "
        "increments the plan's version by one\" — and one for each of the three "
        "procedures moves"
    )
    assert fixtures.read_case(client, built["members"]["2202"]["case"]["id"])[
        "version"
    ] == 1, "plan-level writes never touch a case's version"
