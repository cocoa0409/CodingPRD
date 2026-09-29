"""When nobody acts, time acts instead — and only for the rows whose time is up.

The sweep is the mirror image of the determination: one call with an empty body
unwinds the custody track and the review track together. It is also skip-based
rather than transactional, so the interesting claims are as much about the rows
it must leave alone as about the ones it destroys.
"""

from test_helpers import api_errors, constants, fixtures
from test_helpers.assertions import (
    assert_attorney_email_absent,
    assert_case_dimensions,
    assert_communication_sequence,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
    assert_statuses_in_order,
    assert_sweep_found_nothing,
    assert_sweep_report,
)
from test_helpers.test_users import ADMIN_HEADERS, make_reviewer_headers
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_SEGREGATION_LAPSED,
    DISCLOSURE_FULL,
    DISCLOSURE_LIMITED,
    DRAFT_DEFICIENT,
    DRAFT_DENIED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_EXPIRED,
    HOLD_HELD,
    NOTICE_CURED,
    NOTICE_EXPIRED,
    NOTICE_ISSUED,
    ORIGIN_SYSTEM,
    RECIPIENT_ALTERNATE_PAYEE,
    RECIPIENT_PARTICIPANT,
    REVIEW_DEFICIENT,
    REVIEW_DENIED,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SEGREGATION_LAPSED,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DEFICIENCY_NOTICE,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
    TEMPLATE_SEGREGATION_LAPSE_NOTICE,
)

# The eighteen-month plan every scenario in this file shares: a 548-day
# segregation window and a 60-day resubmission window, so the two deadlines the
# sweep's first two phases read fall far apart in time.
SWEEP_PLAN = {
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

# 2026-10-01 advanced by the same 548 whole days: one month later than the
# window that opens on 2026-09-01, hence one month later than 2028-03-02.
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"
HOLD_Y_EXPIRES_AT = "2028-04-01T00:00:00Z"
CLOCK_2028_04_01_PLUS_1S = "2028-04-01T00:00:01Z"

def _noticed_and_never_cured(client, plan_name, reference="DRO-2663-X1"):
    """A held case whose only draft is DEFICIENT under a still-ISSUED notice."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        plan_overrides=SWEEP_PLAN,
        participant_overrides={
            "full_name": "Oona Brightwater",
            "ssn_last4": "9004",
            "date_of_birth": "1974-12-01",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Ilse Brightwater",
            "alternate_payee_dob": "1977-05-05",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": reference,
            "uses_model_language": False,
        },
    )
    assert setup["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert_hold(
        setup["hold"],
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    setup["notice"] = fixtures.issue_notice(
        client,
        setup["draft"]["id"],
        headers=make_reviewer_headers(),
        reviewer_notes="model language missing; resubmit with plan model language",
    )
    assert setup["notice"]["status"] == NOTICE_ISSUED
    assert setup["notice"]["resubmission_deadline_at"] == constants.CLOCK_2026_10_31
    setup["draft"] = fixtures.read_draft(client, setup["draft"]["id"])
    assert setup["draft"]["status"] == DRAFT_DEFICIENT
    return setup


def test_the_sweep_drives_the_whole_chain_backwards_without_a_human_act(client):
    """One empty-bodied system call unwinds hold, account, case and draft alike.

    PRD: "The hold moves `HELD → EXPIRED`. Because it left `HELD`, the plan
    account's derived balances are recomputed so `held_amount_cents` drops and
    `available_balance_cents` is restored. Because the segregation lapsed, the
    case's `segregation_status` moves `HELD → LAPSED`."

    Design: Difficulty/transitive_cascade/segregation_lapse_sweep_five_level_denial_cascade
    """
    setup = _noticed_and_never_cured(client, "Lapse Plan")
    case_id = setup["case"]["id"]
    draft_id = setup["draft"]["id"]
    hold_id = setup["hold"]["id"]
    notice_id = setup["notice"]["id"]

    # Strictly past 2028-03-02T00:00:00Z, so the phase-1 predicate selects it.
    fixtures.set_clock(client, constants.CLOCK_2028_03_03)
    report = fixtures.run_sweep(client)
    assert_sweep_report(
        report,
        expired_hold_ids=[hold_id],
        lapsed_case_ids=[case_id],
        denied_draft_order_ids=[draft_id],
        expired_notice_ids=[notice_id],
        closed_ap_account_ids=[],
    )

    # Level 1: the hold leaves HELD without ever having been converted, so the
    # three conversion-only fields stay exactly where receipt left them.
    assert_hold(
        fixtures.read_hold(client, hold_id),
        status=HOLD_EXPIRED,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )

    # Level 2: the participant's money comes back whole. A lapse is not a
    # payment, so no money source was ever debited.
    account = fixtures.read_plan_account(client, setup["account"]["id"])
    assert_plan_account_figures(
        account,
        vested_balance_cents=1000000,
        assignable_base_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    assert fixtures.money_source_balances(client, account["id"]) == {
        SOURCE_PRE_TAX_DEFERRAL: 1000000
    }

    # Levels 3 and 5: both dimensions of the one case row terminate together.
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=4,
    )

    # Level 4: the draft carries the system-only reason, and its nested notice
    # cascade expired the notice rather than curing it.
    denied = fixtures.read_draft(client, draft_id)
    assert denied["status"] == DRAFT_DENIED
    assert denied["denial_reason"] == DENIAL_SEGREGATION_LAPSED
    assert denied["revision_number"] == 1
    assert_statuses_in_order(fixtures.read_notices(client, draft_id), [NOTICE_EXPIRED])

    letters = fixtures.read_communications(client, case_id)
    assert_communication_sequence(
        letters,
        [
            (RECIPIENT_PARTICIPANT, TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
            (RECIPIENT_PARTICIPANT, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_FULL, ORIGIN_SYSTEM),
            (RECIPIENT_ALTERNATE_PAYEE, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
            (RECIPIENT_PARTICIPANT, TEMPLATE_SEGREGATION_LAPSE_NOTICE,
             DISCLOSURE_FULL, ORIGIN_SYSTEM),
            (RECIPIENT_ALTERNATE_PAYEE, TEMPLATE_SEGREGATION_LAPSE_NOTICE,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
        ],
    )
    assert [row["sent_at"] for row in letters[3:]] == [
        constants.CLOCK_2028_03_03,
        constants.CLOCK_2028_03_03,
    ]
    assert_attorney_email_absent(letters)


def test_the_lapse_consumes_the_hold_and_closes_the_manual_release_path(client):
    """After time has taken the hold there is nothing left for a human to release.

    PRD: "it is permitted only while the hold is still `HELD` (otherwise
    `ERR_HOLD_NOT_HELD`) and only once the hold's case has actually reached
    `review_status` `DENIED` (otherwise `ERR_CASE_NOT_DENIED`)"

    Design: Difficulty/transitive_cascade/segregation_lapse_sweep_five_level_denial_cascade
    """
    setup = _noticed_and_never_cured(client, "Lapse Guard Plan", "DRO-2663-X2")
    case_id = setup["case"]["id"]
    hold_id = setup["hold"]["id"]

    fixtures.set_clock(client, constants.CLOCK_2028_03_03)
    first = fixtures.run_sweep(client)
    assert_sweep_report(first, expired_hold_ids=[hold_id], lapsed_case_ids=[case_id])

    # A second run at the same instant selects nothing: every row it would have
    # acted on has already left the status its phase looks for.
    second = fixtures.run_sweep(client)
    assert_sweep_found_nothing(second)
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=4,
    )
    assert len(fixtures.read_communications(client, case_id)) == 5

    # The case did reach review_status DENIED, so the second gate is satisfied
    # and only the hold's own status can be what refuses the release.
    assert_error_envelope(
        client.release_segregation_hold(hold_id, ADMIN_HEADERS),
        api_errors.ERR_HOLD_NOT_HELD,
        409,
    )
    assert_hold(
        fixtures.read_hold(client, hold_id),
        status=HOLD_EXPIRED,
        hold_amount_cents=400000,
        segregation_date=None,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        segregation_status=SEGREGATION_LAPSED,
        version=4,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    assert len(fixtures.read_communications(client, case_id)) == 5, (
        "a refused release appends no correspondence"
    )
    assert fixtures.read_ap_accounts(client, case_id) == []


def test_the_expiry_instant_itself_still_belongs_to_the_segregation(client):
    """At exactly expires_at the hold survives, and a revision never moved it.

    PRD: "A hold placed at 2026-09-01T00:00:00Z under the default 548-day window
    expires at 2028-03-02T00:00:00Z; the sweep leaves it `HELD` at exactly
    2028-03-02T00:00:00Z and only expires it at 2028-03-02T00:00:01Z or later."

    Design: Difficulty/boundary_precision_check/segregation_hold_expires_only_strictly_after_expires_at
    """
    setup = _noticed_and_never_cured(client, "Boundary Plan", "DRO-2663-B1")
    case_id = setup["case"]["id"]
    draft_id = setup["draft"]["id"]
    hold_id = setup["hold"]["id"]

    # The resubmission arrives at exactly its own deadline and is accepted, but
    # it is the eighteen-month window that this test follows afterwards.
    fixtures.set_clock(client, constants.CLOCK_2026_10_31)
    revised = fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-B1-rev2",
        uses_model_language=False,
    )
    assert revised["status"] == DRAFT_UNDER_REVIEW
    assert revised["revision_number"] == 2
    assert revised["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert_statuses_in_order(fixtures.read_notices(client, draft_id), [NOTICE_CURED])

    fixtures.set_clock(client, constants.CLOCK_2028_03_02)
    assert_sweep_found_nothing(fixtures.run_sweep(client))

    surviving = fixtures.read_hold(client, hold_id)
    assert_hold(
        surviving,
        status=HOLD_HELD,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
        segregation_date=None,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
    )
    assert fixtures.read_draft(client, draft_id)["status"] == DRAFT_UNDER_REVIEW


def test_one_second_past_the_expiry_instant_the_whole_chain_fires(client):
    """The same comparison that spared the hold at 00:00:00 destroys it at 00:00:01.

    PRD: "Whole-day arithmetic on UTC instants carries the time-of-day component
    unchanged, and every expiry predicate in this system is **strictly greater
    than**, never greater-than-or-equal."

    Design: Difficulty/boundary_precision_check/segregation_hold_expires_only_strictly_after_expires_at
    """
    setup = _noticed_and_never_cured(client, "Boundary Plan B", "DRO-2663-B2")
    case_id = setup["case"]["id"]
    draft_id = setup["draft"]["id"]
    hold_id = setup["hold"]["id"]

    fixtures.set_clock(client, constants.CLOCK_2026_10_31)
    fixtures.resubmit(
        client,
        draft_id,
        document_reference="DRO-2663-B2-rev2",
        uses_model_language=False,
    )
    fixtures.set_clock(client, constants.CLOCK_2028_03_02)
    assert_sweep_found_nothing(fixtures.run_sweep(client))

    # One second later the same row satisfies the strict comparison.
    fixtures.set_clock(client, constants.CLOCK_2028_03_02_PLUS_1S)
    report = fixtures.run_sweep(client)
    assert_sweep_report(
        report,
        expired_hold_ids=[hold_id],
        lapsed_case_ids=[case_id],
        denied_draft_order_ids=[draft_id],
        expired_notice_ids=[],
        closed_ap_account_ids=[],
    )

    assert_hold(
        fixtures.read_hold(client, hold_id),
        status=HOLD_EXPIRED,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
        segregation_date=None,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=5,
    )
    lapsed_draft = fixtures.read_draft(client, draft_id)
    assert lapsed_draft["status"] == DRAFT_DENIED
    assert lapsed_draft["denial_reason"] == DENIAL_SEGREGATION_LAPSED
    assert lapsed_draft["revision_number"] == 2

    # The notice was cured long before the lapse, so the nested notice cascade
    # had nothing of its own to expire.
    assert_statuses_in_order(fixtures.read_notices(client, draft_id), [NOTICE_CURED])
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )


def _two_cases_with_staggered_windows(client):
    """One plan, two members, two receipts a month apart — so two expiry dates."""
    plan = fixtures.create_published_plan(client, plan_name="Skip Plan", **SWEEP_PLAN)
    built = {}
    for label, name, ssn, dob in (
        ("x", "Ivar Solheim", "1201", "1972-02-02"),
        ("y", "Runa Solheim", "1202", "1974-04-04"),
    ):
        member = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=name,
            ssn_last4=ssn,
            date_of_birth=dob,
            participation_start_date="2010-01-01",
        )
        account = fixtures.open_plan_account(client, member["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000, basis_cents=0
        )
        fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
        built[label] = {"member": member, "account": account}

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case_x = fixtures.open_case(
        client,
        built["x"]["member"]["id"],
        alternate_payee_name="Petra Solheim",
        alternate_payee_dob="1975-05-05",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    draft_x = fixtures.receive_draft(
        client,
        case_x["id"],
        case_x["version"],
        document_reference="DRO-2663-S1",
        uses_model_language=False,
    )
    built["x"].update({"case": case_x, "draft": draft_x})
    built["x"]["hold"] = fixtures.hold_for_case(client, case_x["id"])
    built["x"]["notice"] = fixtures.issue_notice(
        client,
        draft_x["id"],
        headers=make_reviewer_headers(),
        reviewer_notes="model language missing on the first filing",
    )

    fixtures.set_clock(client, CLOCK_2026_10_01)
    case_y = fixtures.open_case(
        client,
        built["y"]["member"]["id"],
        alternate_payee_name="Tobias Solheim",
        alternate_payee_dob="1976-06-06",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    draft_y = fixtures.receive_draft(
        client,
        case_y["id"],
        case_y["version"],
        document_reference="DRO-2663-S2",
    )
    assert draft_y["deficiency_codes"] == []
    built["y"].update({"case": case_y, "draft": draft_y})
    built["y"]["hold"] = fixtures.hold_for_case(client, case_y["id"])
    return built


def test_the_sweep_touches_only_the_rows_whose_own_deadline_has_passed(client):
    """Three independent phases, per-row eligibility, and a no-op on re-run.

    PRD: "Every rejection notice in `ISSUED` status whose
    `resubmission_deadline_at` is strictly earlier than the logical clock moves
    `ISSUED → EXPIRED`, processed in `issued_at` ascending order. This phase
    touches nothing else: the draft order stays `DEFICIENT`."

    Design: Corner/endpoints/the_sweep_acts_on_the_eligible_rows_and_silently_skips_the_rest
    """
    built = _two_cases_with_staggered_windows(client)
    hold_x = built["x"]["hold"]
    hold_y = built["y"]["hold"]
    assert hold_x["placed_at"] == constants.CLOCK_2026_09_01
    assert hold_x["expires_at"] == constants.CLOCK_2028_03_02
    assert hold_y["placed_at"] == CLOCK_2026_10_01
    assert hold_y["expires_at"] == HOLD_Y_EXPIRES_AT

    # Holds come back in placed_at ascending order, so the earlier window first.
    assert [row["id"] for row in fixtures.read_holds(client, status=HOLD_HELD)] == [
        hold_x["id"],
        hold_y["id"],
    ]

    # Phase 2 only: the notice's 60-day window has closed, while neither
    # eighteen-month window is anywhere near its end.
    fixtures.set_clock(client, constants.CLOCK_2026_11_01)
    first = fixtures.run_sweep(client)
    assert_sweep_report(
        first,
        expired_hold_ids=[],
        lapsed_case_ids=[],
        denied_draft_order_ids=[],
        expired_notice_ids=[built["x"]["notice"]["id"]],
        closed_ap_account_ids=[],
    )
    assert_statuses_in_order(
        fixtures.read_notices(client, built["x"]["draft"]["id"]), [NOTICE_EXPIRED]
    )
    assert fixtures.read_draft(client, built["x"]["draft"]["id"])["status"] == (
        DRAFT_DEFICIENT
    ), "an expired window is not a denial"
    assert_case_dimensions(
        fixtures.read_case(client, built["x"]["case"]["id"]),
        review_status=REVIEW_DEFICIENT,
        segregation_status=SEGREGATION_HELD,
        version=3,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, built["x"]["account"]["id"]),
        held_amount_cents=400000,
        available_balance_cents=600000,
    )

    # Re-running at the same instant finds nothing: the notice is no longer ISSUED.
    assert_sweep_found_nothing(fixtures.run_sweep(client))

    # One second past case X's own expiry: its phase-1 cascade fires, and case
    # Y — a month from its own expiry — is skipped in the very same sweep.
    fixtures.set_clock(client, constants.CLOCK_2028_03_02_PLUS_1S)
    third = fixtures.run_sweep(client)
    assert_sweep_report(
        third,
        expired_hold_ids=[hold_x["id"]],
        lapsed_case_ids=[built["x"]["case"]["id"]],
        denied_draft_order_ids=[built["x"]["draft"]["id"]],
        expired_notice_ids=[],
        closed_ap_account_ids=[],
    )
    case_x_after_lapse = fixtures.read_case(client, built["x"]["case"]["id"])
    assert_case_dimensions(
        case_x_after_lapse,
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=4,
    )
    assert fixtures.read_hold(client, hold_y["id"])["status"] == HOLD_HELD
    assert fixtures.read_draft(client, built["y"]["draft"]["id"])["status"] == (
        DRAFT_UNDER_REVIEW
    )
    assert_case_dimensions(
        fixtures.read_case(client, built["y"]["case"]["id"]),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=2,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, built["y"]["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )

    # Case Y's turn comes a month later, and the terminal rows of case X are
    # never revisited by it.
    fixtures.set_clock(client, CLOCK_2028_04_01_PLUS_1S)
    fourth = fixtures.run_sweep(client)
    assert_sweep_report(
        fourth,
        expired_hold_ids=[hold_y["id"]],
        lapsed_case_ids=[built["y"]["case"]["id"]],
        denied_draft_order_ids=[built["y"]["draft"]["id"]],
        expired_notice_ids=[],
        closed_ap_account_ids=[],
    )
    denied_y = fixtures.read_draft(client, built["y"]["draft"]["id"])
    assert denied_y["status"] == DRAFT_DENIED
    assert denied_y["denial_reason"] == DENIAL_SEGREGATION_LAPSED
    assert_case_dimensions(
        fixtures.read_case(client, built["y"]["case"]["id"]),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_LAPSED,
        version=3,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, built["y"]["account"]["id"]),
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    assert fixtures.read_case(client, built["x"]["case"]["id"])["version"] == (
        case_x_after_lapse["version"]
    ), "a row that already lapsed is not swept a second time"
