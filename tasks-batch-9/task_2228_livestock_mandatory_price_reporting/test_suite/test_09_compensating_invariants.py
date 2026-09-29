"""Ledgers taken away and given back, checked for drift on the way home.

Both ledgers here are recomputed over the current rows rather than nudged by
deltas, so a full round trip has to land on the original figure exactly. The
money ledger additionally shows which consequences a settlement compensates and
which it leaves standing.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import assert_penalty_ledger, assert_window_ledger
from test_helpers.types import (
    DelinquencyTier,
    PenaltyStatus,
    RegistrationStatus,
    SubmissionStatus,
    SuspendedReason,
)


def _window_carrying_twelve_fifty_head(api):
    """Three accepted filings on one window: 500, 500 and 250 head."""
    scene = fx.three_reporter_cattle_window(api)
    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=1250,
        accepted_submission_count=3,
    )
    return scene


def test_01_reopening_a_filing_drops_its_head_from_the_window_ledger(api):
    """The removal leg takes exactly the coop's 250 head out, and nothing else.

    The ledger falls from 1,250 head over three filings to 1,000 over two, while
    the reopened filing keeps its own 250 head on its own record -- the ledger
    dropped it, it did not lose its figures.

    PRD §3.5: "Reopening stores the `correction_reason`, recomputes the window
    ledger so this filing's head leaves it, and forces every `COMPUTED` market
    report of the window to `STALE`."

    Design: Difficulty/compensating_invariant/window_head_ledger_restored_by_correction_cycle
    """
    scene = _window_carrying_twelve_fifty_head(api)
    coop_filing = scene["submissions"]["coop"]

    reopened = fx.reopen_filing(
        api, coop_filing["id"], "clerical review of the coop filing"
    )
    assert reopened["status"] == SubmissionStatus.UNDER_CORRECTION.value, reopened
    assert reopened["reported_head"] == 250, reopened

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=1000,
        accepted_submission_count=2,
    )


def test_02_refiling_restores_nothing_because_only_acceptance_books_head(api):
    """Between the two legs the ledger sits still at 1,000 head.

    The refiling carries the coop's filing out of correction and back into the
    review queue, and the window ledger is unmoved by it: the head only comes
    back when a reviewer accepts.

    PRD §3.5: "Refiling increments `resubmission_count` by 1, resets
    `submitted_at` to the logical clock, and re-measures lateness against the
    window's original `submission_deadline_utc`".

    Design: Difficulty/compensating_invariant/window_head_ledger_restored_by_correction_cycle
    """
    scene = _window_carrying_twelve_fifty_head(api)
    coop = scene["coop"]
    coop_filing = scene["submissions"]["coop"]

    fx.reopen_filing(api, coop_filing["id"], "clerical review of the coop filing")
    refiled = fx.resubmit_filing(api, coop["entity"]["id"], coop_filing["id"])

    assert refiled["status"] == SubmissionStatus.RESUBMITTED.value, refiled
    assert refiled["resubmission_count"] == 1, refiled

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=1000,
        accepted_submission_count=2,
    )


def test_03_the_closed_cycle_restores_the_ledger_exactly_but_not_the_version(api):
    """1,250 goes to 1,000 and back to 1,250, with no drift either way.

    Re-accepting the refiling brings the head back to the pre-cycle figure to the
    head, while the filing's resubmission counter records that the cycle happened
    and the window's version has advanced past where it started -- compensation
    restores values, never versions.

    PRD §2.11: "Two running ledgers in this program are always recomputed from
    scratch over the current rows rather than adjusted by deltas, so that no
    drift can accumulate across correction and settlement cycles."

    Design: Difficulty/compensating_invariant/window_head_ledger_restored_by_correction_cycle
    """
    scene = _window_carrying_twelve_fifty_head(api)
    window_id = scene["window"]["id"]
    coop_filing = scene["submissions"]["coop"]
    version_before = fx.window_version(api, window_id)

    fx.reopen_filing(api, coop_filing["id"], "clerical review of the coop filing")
    fx.resubmit_filing(api, scene["coop"]["entity"]["id"], coop_filing["id"])
    reaccepted = fx.accept_filing(api, coop_filing["id"])

    assert reaccepted["status"] == SubmissionStatus.ACCEPTED.value, reaccepted
    assert reaccepted["resubmission_count"] == 1, reaccepted
    assert reaccepted["reported_head"] == 250, reaccepted

    restored = fx.read_window(api, window_id)
    assert_window_ledger(
        restored, total_head_reported=1250, accepted_submission_count=3
    )
    assert restored["version"] > version_before, restored


def _firm_suspended_by_three_unregistered_seasons(api):
    """A suspended firm holding 4,815,000 cents of penalties and a voided draft."""
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)

    filing = fx.draft_filing(api, entity_id, firm["plant"]["id"], window["id"])
    fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )

    assessments = fx.assess_non_registration_penalties(api, entity_id, 3)

    return {
        "entity_id": entity_id,
        "registration_id": firm["registration"]["id"],
        "filing": filing,
        "assessments": assessments,
    }


def test_04_three_escalating_assessments_leave_the_whole_sum_outstanding(api):
    """Before any settlement the partition is entirely on the outstanding side.

    The three escalating assessments total 4,815,000 cents with nothing paid and
    nothing waived, their 24 points put the firm in the top tier, and the tier
    breach has suspended the registration and voided the untouched draft.

    PRD §2.11: "The conservation invariant holds at every observable instant:
    `assessed_penalty_cents` equals `paid_penalty_cents` plus
    `waived_penalty_cents` plus `outstanding_penalty_cents`".

    Design: Difficulty/compensating_invariant/entity_penalty_ledger_restored_by_waiver
    """
    scene = _firm_suspended_by_three_unregistered_seasons(api)

    amounts = [row["assessed_amount_cents"] for row in scene["assessments"]]
    assert amounts == [1126000, 1689000, 2000000], amounts

    assert_penalty_ledger(
        fx.read_entity(api, scene["entity_id"]),
        assessed_penalty_cents=4815000,
        paid_penalty_cents=0,
        waived_penalty_cents=0,
        outstanding_penalty_cents=4815000,
        delinquency_points=24,
    )

    registration = fx.read_registration(api, scene["registration_id"])
    assert registration["status"] == RegistrationStatus.SUSPENDED.value, registration
    assert (
        registration["suspended_reason"]
        == SuspendedReason.DELINQUENCY_TIER_BREACH.value
    ), registration

    assert (
        fx.read_submission(api, scene["filing"]["id"])["status"]
        == SubmissionStatus.VOIDED.value
    )


def test_05_a_waiver_moves_cents_sideways_returns_points_and_lifts_the_suspension(api):
    """The gross total is invariant; the points and the suspension are reversed.

    Waiving the top row shifts its 2,000,000 cents from outstanding into waived
    without touching the 4,815,000 assessed, hands back exactly that row's eight
    points to leave the firm one tier down, and reinstates the registration it
    had suspended while leaving the registration number alone -- but the voided
    draft stays voided, because a terminal filing is never resurrected.

    PRD §3.8: "When the firm's governing registration is `SUSPENDED` with
    `suspended_reason` equal to `DELINQUENCY_TIER_BREACH`, and the post-waiver
    point total no longer classifies as `TIER_2`, that registration is reinstated
    `SUSPENDED → ACTIVE` with `suspended_reason` cleared to null".

    Design: Difficulty/compensating_invariant/entity_penalty_ledger_restored_by_waiver
    """
    scene = _firm_suspended_by_three_unregistered_seasons(api)
    before = fx.read_registration(api, scene["registration_id"])

    waived = fx.waive_penalty(
        api,
        scene["assessments"][2]["id"],
        "assessment issued in error during registration transfer",
    )
    assert waived["status"] == PenaltyStatus.WAIVED.value, waived
    assert waived["settled_at"] is not None, waived

    assert_penalty_ledger(
        fx.read_entity(api, scene["entity_id"]),
        assessed_penalty_cents=4815000,
        paid_penalty_cents=0,
        waived_penalty_cents=2000000,
        outstanding_penalty_cents=2815000,
        delinquency_points=16,
    )
    assert (
        waived["delinquency_tier_at_assessment"] == DelinquencyTier.TIER_1.value
    ), waived

    reinstated = fx.read_registration(api, scene["registration_id"])
    assert reinstated["status"] == RegistrationStatus.ACTIVE.value, reinstated
    assert reinstated["suspended_reason"] is None, reinstated
    assert reinstated["registration_number"] == before["registration_number"]

    assert (
        fx.read_submission(api, scene["filing"]["id"])["status"]
        == SubmissionStatus.VOIDED.value
    )


def test_06_paying_in_full_moves_cents_but_deliberately_returns_no_points(api):
    """The money ledger and the point ledger compensate independently.

    Paying the first assessment in full shifts its 1,126,000 cents from
    outstanding into paid, leaving the partition at 1,126,000 plus 2,000,000 plus
    1,689,000 against the same 4,815,000 gross -- and the point total stays at the
    16 the waiver left, because paying a fine does not erase the violation.

    PRD §3.8: "A successful payment moves the row `ASSESSED → PAID`, stamps
    `settled_at` with the logical clock, and shifts the amount from
    `outstanding_penalty_cents` into `paid_penalty_cents` on the firm while
    `delinquency_points` stay exactly where they were".

    Design: Difficulty/compensating_invariant/entity_penalty_ledger_restored_by_waiver
    """
    scene = _firm_suspended_by_three_unregistered_seasons(api)
    fx.waive_penalty(
        api,
        scene["assessments"][2]["id"],
        "assessment issued in error during registration transfer",
    )

    paid = validate_success(
        api.pay_penalty_assessment(
            scene["assessments"][0]["id"],
            f.payment_payload(1126000),
            u.PENALTY_OFFICER,
        )
    )
    assert paid["status"] == PenaltyStatus.PAID.value, paid
    assert paid["settled_at"] is not None, paid

    assert_penalty_ledger(
        fx.read_entity(api, scene["entity_id"]),
        assessed_penalty_cents=4815000,
        paid_penalty_cents=1126000,
        waived_penalty_cents=2000000,
        outstanding_penalty_cents=1689000,
        delinquency_points=16,
    )

    still_reinstated = fx.read_registration(api, scene["registration_id"])
    assert (
        still_reinstated["status"] == RegistrationStatus.ACTIVE.value
    ), still_reinstated
