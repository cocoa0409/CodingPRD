"""When two rungs are violated at once, exactly one of them answers.

Own state before substance, lateness before over-revision, and a marital window
that is half-open, per-participant, and freed only by a denial.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    REVIEWER_USER_ID,
    make_reviewer_headers,
)
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DRAFT_DEFICIENT,
    DRAFT_DENIED,
    DRAFT_QUALIFIED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    NOTICE_CURED,
    NOTICE_ISSUED,
    REVIEW_DEFICIENT,
    REVIEW_DENIED,
    REVIEW_INTAKE,
    REVIEW_QUALIFIED,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_CONVERTED,
    SEGREGATION_HELD,
    SEGREGATION_NONE,
    SOURCE_PRE_TAX_DEFERRAL,
)

ORDERING_PLAN = {
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


def _deficient_under_notice(client, plan_name):
    """A draft driven to DEFICIENT while its one deficiency is still real."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        snapshots=(("2026-06-30", 1000000),),
        plan_overrides=ORDERING_PLAN,
        participant_overrides={
            "full_name": "Rurik Almqvist",
            "ssn_last4": "5150",
            "date_of_birth": "1976-03-30",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Vega Almqvist",
            "alternate_payee_dob": "1978-09-09",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": "DRO-2663-O1",
            "uses_model_language": False,
        },
    )
    assert setup["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert setup["draft"]["status"] == DRAFT_UNDER_REVIEW
    # The reviewer's identifier is recorded, so a different administrator can
    # still sign without tripping the segregation-of-duties rung.
    notice = fixtures.issue_notice(
        client,
        setup["draft"]["id"],
        headers=make_reviewer_headers(),
        reviewer_notes="model language missing",
    )
    assert notice["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    setup["draft"] = fixtures.read_draft(client, setup["draft"]["id"])
    assert setup["draft"]["status"] == DRAFT_DEFICIENT
    assert setup["draft"]["reviewed_by_user_id"] == REVIEWER_USER_ID
    return setup


def test_the_state_rung_answers_before_the_substance_rung_is_reached(client):
    """A deficient draft with live codes reports its state, not its content.

    PRD: "Seven conditions must hold, and §2.8 fixes the order in which their
    failures are reported: the draft order must be `UNDER_REVIEW` (otherwise
    `ERR_DRAFT_ORDER_NOT_UNDER_REVIEW`); the acting `X-User-ID` must differ from
    the draft's `reviewed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`);
    the plan's `procedures_status` must be `PUBLISHED` (otherwise
    `ERR_PLAN_PROCEDURES_NOT_PUBLISHED`); the case's segregation hold must still
    be `HELD` with the logical clock at or before its `expires_at` (otherwise
    `ERR_SEGREGATION_WINDOW_EXPIRED`); the recomputed `deficiency_codes` set
    must be empty (otherwise `ERR_QUALIFICATION_DEFICIENCIES_PRESENT`)"

    Design: Difficulty/priority_pair_validation_conflict/qualify_state_check_precedes_deficiency_readiness_check
    """
    setup = _deficient_under_notice(client, "Ordering Plan A")
    draft_id = setup["draft"]["id"]

    # Both rules are violated at once, and the earlier rung answers.
    assert_error_envelope(
        client.qualify_draft_order(draft_id, ADMIN_HEADERS),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )

    # A resubmission that changes nothing substantive repairs only the state, so
    # the identical request now reaches the readiness rung.
    resubmitted = fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-O1-rev2",
        uses_model_language=False,
    )
    assert resubmitted["status"] == DRAFT_UNDER_REVIEW
    assert resubmitted["revision_number"] == 2
    assert resubmitted["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert_error_envelope(
        client.qualify_draft_order(draft_id, ADMIN_HEADERS),
        api_errors.ERR_QUALIFICATION_DEFICIENCIES_PRESENT,
        409,
    )

    # Neither refused determination mutated anything.
    reread = fixtures.read_draft(client, draft_id)
    assert reread["status"] == DRAFT_UNDER_REVIEW
    assert reread["revision_number"] == 2
    assert reread["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert reread["denial_reason"] is None
    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
    )
    assert fixtures.read_ap_accounts(client, setup["case"]["id"]) == [], (
        "a refused qualification never establishes a payee account"
    )
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
        earnings_adjustment_cents=0,
    )
    assert [row["status"] for row in fixtures.read_notices(client, draft_id)] == [
        NOTICE_CURED
    ]


def test_the_substance_rung_lets_go_the_moment_the_codes_are_cured(client):
    """The readiness refusal really was about the code set, nothing else.

    PRD: "Reviewing a draft order against the plan's procedures produces a set
    of **deficiency codes**, recomputed fresh at four moments: when a draft is
    received, when it is resubmitted, when a rejection notice is issued on it,
    and again when a qualification is attempted."

    Design: Difficulty/priority_pair_validation_conflict/qualify_state_check_precedes_deficiency_readiness_check
    """
    setup = _deficient_under_notice(client, "Ordering Plan A2")
    draft_id = setup["draft"]["id"]

    # While the draft sits DEFICIENT the state rung answers even for a caller
    # who is about to satisfy the readiness rung.
    assert_error_envelope(
        client.qualify_draft_order(draft_id, ADMIN_HEADERS),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )

    cured = fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-O1-rev2",
        uses_model_language=True,
    )
    assert cured["status"] == DRAFT_UNDER_REVIEW
    assert cured["revision_number"] == 2
    assert cured["deficiency_codes"] == [], "the recomputation cleared the set"
    assert [row["status"] for row in fixtures.read_notices(client, draft_id)] == [
        NOTICE_CURED
    ]

    determined = fixtures.qualify(client, draft_id)
    assert determined["status"] == DRAFT_QUALIFIED
    assert determined["revision_number"] == 2
    assert determined["deficiency_codes"] == []

    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
    )
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=400000,
        segregation_date="2026-09-01",
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["payment_mode"] == APPROACH_SEPARATE_INTEREST
    assert payee["balance_cents"] == 400000
    assert payee["after_tax_basis_cents"] == 0
    assert payee["per_period_amount_cents"] == 0
    assert payee["shared_payment_end_date"] is None
    assert payee["total_distributed_gross_cents"] == 0

    assert fixtures.money_source_balances(client, setup["account"]["id"]) == {
        SOURCE_PRE_TAX_DEFERRAL: 600000
    }
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=600000,
        assignable_base_cents=600000,
        after_tax_basis_cents=0,
        held_amount_cents=0,
        available_balance_cents=600000,
    )


def _noticed_draft(client, plan, member_name, ssn_last4, payee_name, reference):
    """A funded member whose deficient draft carries exactly one live notice."""
    participant = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name=member_name,
        ssn_last4=ssn_last4,
        date_of_birth="1980-11-11",
        participation_start_date="2010-01-01",
    )
    account = fixtures.open_plan_account(client, participant["id"])
    fixtures.add_money_source(client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000)
    fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
    case = fixtures.open_case(
        client,
        participant["id"],
        alternate_payee_name=payee_name,
        alternate_payee_dob="1982-04-04",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference=reference,
        uses_model_language=False,
    )
    notice = fixtures.issue_notice(
        client, draft["id"], headers=make_reviewer_headers(), reviewer_notes="notice 1"
    )
    return {
        "participant": participant,
        "account": account,
        "case": case,
        "draft": draft,
        "notice": notice,
        "hold": fixtures.hold_for_case(client, case["id"]),
    }


def _driven_to_the_cap(client, plan):
    """Three notices and two resubmissions, leaving `revision_number` at 3."""
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    built = _noticed_draft(
        client, plan, "Juno Baptiste", "8123", "Colette Baptiste", "DRO-2663-W1"
    )
    assert built["notice"]["resubmission_deadline_at"] == "2026-10-31T00:00:00Z"
    for clock, reference, expected_deadline in (
        (constants.CLOCK_2026_09_10, "DRO-2663-W1-rev2", "2026-11-09T00:00:00Z"),
        (constants.CLOCK_2026_09_20, "DRO-2663-W1-rev3", "2026-11-19T00:00:00Z"),
    ):
        fixtures.set_clock(client, clock)
        fixtures.resubmit(
            client,
            built["draft"]["id"],
            document_reference=reference,
            uses_model_language=False,
        )
        notice = fixtures.issue_notice(
            client,
            built["draft"]["id"],
            headers=make_reviewer_headers(),
            reviewer_notes="another notice",
        )
        assert notice["resubmission_deadline_at"] == expected_deadline
    built["draft"] = fixtures.read_draft(client, built["draft"]["id"])
    assert built["draft"]["revision_number"] == 3
    assert built["draft"]["status"] == DRAFT_DEFICIENT
    return built


def test_lateness_is_reported_before_over_revision_on_the_same_request(client):
    """Two rungs, one request, and the clock alone decides which one answers.

    PRD: "On resubmission, the draft order's `revision_number` is strictly less
    than the plan's `max_revisions` — otherwise `ERR_MAX_REVISIONS_EXCEEDED`
    (409). This rung sits deliberately *after* the window rung, so a
    resubmission that is both late and over the cap reports the closed window,
    not the cap."

    Design: Difficulty/priority_pair_validation_conflict/resubmission_window_check_precedes_revision_cap_check
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Ordering Plan B", **ORDERING_PLAN
    )
    built = _driven_to_the_cap(client, plan)
    fourth = factories.resubmission_payload(
        document_reference="DRO-2663-W1-rev4", uses_model_language=True
    )

    # At 2026-09-20 the window is open, so only the cap is violated.
    assert_error_envelope(
        client.resubmit_draft_order(built["draft"]["id"], fourth, ADMIN_HEADERS),
        api_errors.ERR_MAX_REVISIONS_EXCEEDED,
        409,
    )

    # Two months later both rules are violated and the byte-identical request
    # reports the other error. Both are 409, so the status cannot carry it.
    fixtures.set_clock(client, constants.CLOCK_2026_11_20)
    assert_error_envelope(
        client.resubmit_draft_order(built["draft"]["id"], fourth, ADMIN_HEADERS),
        api_errors.ERR_RESUBMISSION_WINDOW_CLOSED,
        409,
    )

    reread = fixtures.read_draft(client, built["draft"]["id"])
    assert reread["revision_number"] == 3
    assert reread["status"] == DRAFT_DEFICIENT
    assert reread["uses_model_language"] is False
    assert reread["document_reference"] == "DRO-2663-W1-rev3", (
        "neither refusal applied the submitted terms"
    )
    notices = fixtures.read_notices(client, built["draft"]["id"])
    assert [row["notice_sequence"] for row in notices] == [1, 2, 3]
    assert [row["resubmission_deadline_at"] for row in notices] == [
        "2026-10-31T00:00:00Z",
        "2026-11-09T00:00:00Z",
        "2026-11-19T00:00:00Z",
    ]
    assert [row["status"] for row in notices] == [
        NOTICE_CURED,
        NOTICE_CURED,
        NOTICE_ISSUED,
    ]
    assert_hold(
        fixtures.hold_for_case(client, built["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
    )
    assert_case_dimensions(
        fixtures.read_case(client, built["case"]["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
    )


def test_the_resubmission_deadline_instant_still_belongs_to_the_payee(client):
    """At the deadline the window rung passes, so the cap rung gets to speak.

    PRD: "the notice with the highest `notice_sequence` on that draft must still
    be `ISSUED` and the logical clock must be at or before its
    `resubmission_deadline_at` (otherwise `ERR_RESUBMISSION_WINDOW_CLOSED`)"

    Design: Difficulty/priority_pair_validation_conflict/resubmission_window_check_precedes_revision_cap_check
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Ordering Plan C", **ORDERING_PLAN
    )
    capped = _driven_to_the_cap(client, plan)
    on_time = _noticed_draft(
        client, plan, "Rune Baptiste", "8124", "Sanna Baptiste", "DRO-2663-B1"
    )
    one_second_late = _noticed_draft(
        client, plan, "Tova Baptiste", "8125", "Ulla Baptiste", "DRO-2663-B2"
    )
    for built in (on_time, one_second_late):
        assert built["notice"]["issued_at"] == constants.CLOCK_2026_09_20
        assert built["notice"]["resubmission_deadline_at"] == "2026-11-19T00:00:00Z"

    # The deadline instant itself is inside the window.
    fixtures.set_clock(client, "2026-11-19T00:00:00Z")
    accepted = fixtures.resubmit(
        client,
        on_time["draft"]["id"],
        document_reference="DRO-2663-B1-rev2",
        uses_model_language=True,
    )
    assert accepted["status"] == DRAFT_UNDER_REVIEW
    assert accepted["revision_number"] == 2
    assert accepted["deficiency_codes"] == []
    assert [row["status"] for row in fixtures.read_notices(client, on_time["draft"]["id"])] == [
        NOTICE_CURED
    ]
    assert_case_dimensions(
        fixtures.read_case(client, on_time["case"]["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
    )
    assert_hold(
        fixtures.read_hold(client, on_time["hold"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_20,
    )

    # At that same instant the capped draft is refused by the later rung, which
    # is only reachable because the window rung was satisfied.
    fourth = factories.resubmission_payload(
        document_reference="DRO-2663-W1-rev4", uses_model_language=True
    )
    assert_error_envelope(
        client.resubmit_draft_order(capped["draft"]["id"], fourth, ADMIN_HEADERS),
        api_errors.ERR_MAX_REVISIONS_EXCEEDED,
        409,
    )

    # One second past the deadline the window rung closes the door instead.
    fixtures.set_clock(client, "2026-11-19T00:00:01Z")
    assert_error_envelope(
        client.resubmit_draft_order(
            one_second_late["draft"]["id"],
            factories.resubmission_payload(
                document_reference="DRO-2663-B2-rev2", uses_model_language=True
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_RESUBMISSION_WINDOW_CLOSED,
        409,
    )
    stalled = fixtures.read_draft(client, one_second_late["draft"]["id"])
    assert stalled["revision_number"] == 1
    assert stalled["status"] == DRAFT_DEFICIENT
    assert stalled["document_reference"] == "DRO-2663-B2"
    assert stalled["uses_model_language"] is False
    assert [
        row["status"] for row in fixtures.read_notices(client, stalled["id"])
    ] == [NOTICE_ISSUED]
    assert_case_dimensions(
        fixtures.read_case(client, one_second_late["case"]["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
    )


def test_adjacent_windows_coexist_while_an_unbounded_one_swallows_the_future(client):
    """Marital windows are half-open intervals scoped to one participant.

    PRD: "Sharing only an endpoint is not an overlap, so a case whose window ends
    2027-01-01 and a case whose window starts 2027-01-01 coexist happily. A null
    `marital_period_end` is treated as unbounded forward and therefore overlaps
    every window that starts later."

    Design: Difficulty/resource_temporal_overlap/marital_period_half_open_adjacency_allowed_overlap_refused
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Interval Plan", **ORDERING_PLAN
    )
    lucian = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="Lucian Ferraro",
        ssn_last4="6060",
        date_of_birth="1970-01-01",
        participation_start_date="1999-01-01",
    )
    noor = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="Noor Ferraro",
        ssn_last4="6061",
        date_of_birth="1970-01-01",
        participation_start_date="1999-01-01",
    )
    account = fixtures.open_plan_account(client, lucian["id"])
    fixtures.add_money_source(
        client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
    )
    fixtures.open_plan_account(client, noor["id"])
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    first = fixtures.open_case(
        client,
        lucian["id"],
        alternate_payee_name="First Spouse",
        marital_period_start="2012-03-01",
        marital_period_end="2020-01-01",
        alternate_payee_dob="1972-02-02",
    )
    assert_case_dimensions(
        first, review_status=REVIEW_INTAKE, segregation_status=SEGREGATION_NONE
    )

    # The end day is outside the window, so the day it names is free to start
    # the next one.
    adjacent = validate_success(
        client.create_qdro_case(
            factories.qdro_case_payload(
                lucian["id"],
                alternate_payee_name="Second Spouse",
                marital_period_start="2020-01-01",
                marital_period_end="2024-01-01",
                alternate_payee_dob="1974-04-04",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert adjacent["marital_period_start"] == "2020-01-01"
    assert_case_dimensions(
        adjacent, review_status=REVIEW_INTAKE, segregation_status=SEGREGATION_NONE
    )

    # A window that genuinely intersects both of them is refused.
    assert_error_envelope(
        client.create_qdro_case(
            factories.qdro_case_payload(
                lucian["id"],
                alternate_payee_name="Straddling Spouse",
                marital_period_start="2019-06-01",
                marital_period_end="2021-06-01",
                alternate_payee_dob="1974-04-04",
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_MARITAL_PERIOD_OVERLAP,
        409,
    )

    # An omitted end is stored as null rather than defaulted to any date.
    open_ended = validate_success(
        client.create_qdro_case(
            factories.omit(
                factories.qdro_case_payload(
                    lucian["id"],
                    alternate_payee_name="Open Ended Spouse",
                    marital_period_start="2024-01-01",
                    alternate_payee_dob="1976-06-06",
                ),
                "marital_period_end",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert open_ended["marital_period_end"] is None
    assert open_ended["marital_period_start"] == "2024-01-01"

    # Being unbounded forward, it now covers every later window entirely.
    assert_error_envelope(
        client.create_qdro_case(
            factories.qdro_case_payload(
                lucian["id"],
                alternate_payee_name="Late Spouse",
                marital_period_start="2026-01-01",
                marital_period_end="2026-06-01",
                alternate_payee_dob="1976-06-06",
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_MARITAL_PERIOD_OVERLAP,
        409,
    )

    # The exclusivity set is scoped by participant, so the very interval that
    # was refused above is admissible on the other member.
    elsewhere = validate_success(
        client.create_qdro_case(
            factories.qdro_case_payload(
                noor["id"],
                alternate_payee_name="Other Participant Spouse",
                marital_period_start="2019-06-01",
                marital_period_end="2021-06-01",
                alternate_payee_dob="1974-04-04",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert elsewhere["participant_id"] == noor["id"]

    mine = validate_success(
        client.list_participant_qdro_cases(lucian["id"], ADMIN_HEADERS)
    )
    assert {row["id"] for row in mine} == {
        first["id"],
        adjacent["id"],
        open_ended["id"],
    }, "each refusal wrote nothing at all"
    assert [row["id"] for row in validate_success(
        client.list_participant_qdro_cases(noor["id"], ADMIN_HEADERS)
    )] == [elsewhere["id"]]

    # Opening cases moves no money: only a received draft order places a hold.
    assert fixtures.read_holds(client, plan_account_id=account["id"]) == []
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account["id"]),
        held_amount_cents=0,
        available_balance_cents=1000000,
    )


def test_a_denial_frees_the_interval_while_a_qualification_reserves_it(client):
    """Only a denied case leaves its window, and it leaves the money behind.

    PRD: "Two cases on the same participant may not carry overlapping windows
    unless the earlier one has been denied — formally, a new case's window must
    not overlap the half-open window of any other case on the same participant
    whose `review_status` is anything other than `DENIED`."

    Design: Difficulty/resource_temporal_overlap/marital_period_half_open_adjacency_allowed_overlap_refused
    """
    plan = fixtures.create_published_plan(
        client, plan_name="Interval Plan B", **ORDERING_PLAN
    )
    members = {}
    for full_name, ssn_last4 in (("Lucian Ferraro", "6060"), ("Noor Ferraro", "6061")):
        member = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=full_name,
            ssn_last4=ssn_last4,
            date_of_birth="1970-01-01",
            participation_start_date="1999-01-01",
        )
        account = fixtures.open_plan_account(client, member["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
        )
        fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
        members[ssn_last4] = {"participant": member, "account": account}
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    doomed = fixtures.open_case(
        client,
        members["6060"]["participant"]["id"],
        alternate_payee_name="First Spouse",
        marital_period_start="2012-03-01",
        marital_period_end="2020-01-01",
        alternate_payee_dob="1972-02-02",
    )
    faulty = fixtures.receive_draft(
        client,
        doomed["id"],
        doomed["version"],
        document_reference="DRO-2663-I1",
        uses_model_language=False,
    )
    assert faulty["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert faulty["status"] == DRAFT_UNDER_REVIEW

    refused = fixtures.deny(client, faulty["id"], DENIAL_ORDER_NOT_QUALIFIABLE)
    assert refused["status"] == DRAFT_DENIED
    assert refused["denial_reason"] == DENIAL_ORDER_NOT_QUALIFIABLE
    assert_case_dimensions(
        fixtures.read_case(client, doomed["id"]),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_HELD,
    )

    # The interval is released the moment the review status reads DENIED.
    refiled = validate_success(
        client.create_qdro_case(
            factories.qdro_case_payload(
                members["6060"]["participant"]["id"],
                alternate_payee_name="Refiled First Spouse",
                marital_period_start="2012-03-01",
                marital_period_end="2020-01-01",
                alternate_payee_dob="1972-02-02",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert refiled["marital_period_start"] == "2012-03-01"
    assert refiled["marital_period_end"] == "2020-01-01"
    assert_case_dimensions(
        refiled, review_status=REVIEW_INTAKE, segregation_status=SEGREGATION_NONE
    )

    # The refiled case is not denied, so it holds the interval against a third.
    assert_error_envelope(
        client.create_qdro_case(
            factories.qdro_case_payload(
                members["6060"]["participant"]["id"],
                alternate_payee_name="Third Spouse",
                marital_period_start="2012-03-01",
                marital_period_end="2020-01-01",
                alternate_payee_dob="1972-02-02",
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_MARITAL_PERIOD_OVERLAP,
        409,
    )
    assert len(
        validate_success(
            client.list_participant_qdro_cases(
                members["6060"]["participant"]["id"], ADMIN_HEADERS
            )
        )
    ) == 2

    # Freeing the interval is not releasing the funds: those are two acts.
    assert_hold(
        fixtures.hold_for_case(client, doomed["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, members["6060"]["account"]["id"]),
        held_amount_cents=400000,
        available_balance_cents=600000,
    )

    # A qualified case, by contrast, keeps its window reserved for good.
    honoured = fixtures.open_case(
        client,
        members["6061"]["participant"]["id"],
        alternate_payee_name="Kept Spouse",
        marital_period_start="2012-03-01",
        marital_period_end="2020-01-01",
        alternate_payee_dob="1972-02-02",
    )
    clean = fixtures.receive_draft(
        client, honoured["id"], honoured["version"], document_reference="DRO-2663-I2"
    )
    assert clean["deficiency_codes"] == []
    assert fixtures.qualify(client, clean["id"])["status"] == DRAFT_QUALIFIED
    assert_case_dimensions(
        fixtures.read_case(client, honoured["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
    )
    assert_error_envelope(
        client.create_qdro_case(
            factories.qdro_case_payload(
                members["6061"]["participant"]["id"],
                alternate_payee_name="Straddling Spouse",
                marital_period_start="2019-06-01",
                marital_period_end="2021-06-01",
                alternate_payee_dob="1974-04-04",
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_MARITAL_PERIOD_OVERLAP,
        409,
    )
    assert [
        row["id"]
        for row in validate_success(
            client.list_participant_qdro_cases(
                members["6061"]["participant"]["id"], ADMIN_HEADERS
            )
        )
    ] == [honoured["id"]]
