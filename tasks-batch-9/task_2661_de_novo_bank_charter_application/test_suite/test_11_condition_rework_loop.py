"""
The condition rework loop: reopen, re-evidence, re-satisfy, and the counts that must return.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_condition_counts_conserved,
    assert_fields_equal,
)
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    CATEGORY_CAPITAL,
    CATEGORY_POLICY,
    CONDITION_OPEN,
    CONDITION_SATISFIED,
    DISPOSITION_REOPENED,
    FILING_ADDITIONAL_INFO_REQUESTED,
    FILING_CONDITIONALLY_APPROVED,
)


def _two_settled_conditions(api):
    """
    The chartering application carrying exactly two settled conditions: POL-01, a
    pre-opening blocker, and CAP-01, which is not blocking. Both deadlines fall on
    2026-12-01, months after the logical clock.
    """
    world = fx.conditionally_approved_group(api)
    world["c_pol"] = fx.add_condition(
        api, world["f_ca"], "POL-01", CATEGORY_POLICY, True, authority=AUTHORITY_CHARTERING
    )
    world["c_cap"] = fx.add_condition(
        api, world["f_ca"], "CAP-01", CATEGORY_CAPITAL, False, authority=AUTHORITY_CHARTERING
    )
    fx.satisfy_condition(api, world["c_pol"], "BOARD-MIN-2026-09-14-POLICY-PACKET")
    fx.satisfy_condition(api, world["c_cap"], "ESCROW-AGENT-CERT-2026-09-14-CAPITAL")
    return world


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant
# ---------------------------------------------------------------------------
def test_reopening_a_settled_blocker_moves_one_unit_across_and_conserves_the_total(api):
    """
    Both conditions start settled, with the blocking set empty and the application cleared
    for pre-opening. Reopening the blocker returns it to open and moves exactly one unit
    from the settled side to the blocking side. The total does not move, because attaching
    is the only thing that can move it, and the non-blocking sibling never enters the
    blocking count at all.

    PRD: "`REOPENED` conserves the total and moves one unit from the settled side to the open blocking side; nothing in the service may ever change `condition_total_count` other than attaching a new condition."
    PRD: "`open_blocking_condition_count` is the number whose `is_pre_opening_blocking` is true **and** whose `status` is `OPEN`, `EVIDENCE_SUBMITTED` or `FAILED`; a non-blocking condition is counted in the total and, once settled, in the settled count, but it can never hold `open_blocking_condition_count` above zero no matter how long it stays open."

    Design: Difficulty/compensating_invariant/condition_reopen_round_trip_restores_filing_counts
    """
    world = _two_settled_conditions(api)
    before = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(
        before,
        status=FILING_CONDITIONALLY_APPROVED,
        condition_total_count=2,
        settled_condition_count=2,
        open_blocking_condition_count=0,
        pre_opening_clearance=True,
    )
    assert_fields_equal(
        fx.read_condition(api, world["c_pol"]),
        status=CONDITION_SATISFIED,
        adjudication_count=1,
    )

    reopened = fx.adjudicate(api, world["c_pol"], DISPOSITION_REOPENED)
    assert_fields_equal(reopened, status=CONDITION_OPEN, adjudication_count=2)

    filing = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(
        filing,
        condition_total_count=2,
        settled_condition_count=1,
        open_blocking_condition_count=1,
    )
    assert_condition_counts_conserved(filing, 2)


def test_the_reopen_pulls_the_application_onto_an_information_round(api):
    """
    The blocking set going from empty to occupied while the application stood conditionally
    approved is itself a cascade: the application falls to an information request and
    consumes the first of the three rounds an examiner would otherwise have had.

    PRD: "Both `FAILED` and `REOPENED` can therefore push a settled blocking condition back into the blocking set, and when that raises the filing's `open_blocking_condition_count` from 0 while the filing is `CONDITIONALLY_APPROVED`, the filing cascades to `ADDITIONAL_INFO_REQUESTED` with `info_request_round` incremented by one, which in turn pulls a `PRE_OPENING` group back to `CONDITIONALLY_APPROVED` with `opening_blocked_reason` `FILING_INFO_REQUESTED` and cancels the group's `SCHEDULED` examinations."

    Design: Difficulty/compensating_invariant/condition_reopen_round_trip_restores_filing_counts
    """
    world = _two_settled_conditions(api)
    assert_fields_equal(fx.read_filing(api, world["f_ca"]), info_request_round=0)

    fx.adjudicate(api, world["c_pol"], DISPOSITION_REOPENED)

    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        status=FILING_ADDITIONAL_INFO_REQUESTED,
        info_request_round=1,
    )


def test_re_satisfying_restores_both_counts_while_the_audit_trail_grows(api):
    """
    Re-evidencing and re-accepting the blocker closes the loop: the settled count is back at
    two, the blocking set is empty again and the total never moved. The audit trail is the
    one thing that does not come back — three adjudications now sit on the reworked
    condition against the single one on its untouched sibling — and clearance stays false,
    because the application itself is no longer conditionally approved.

    PRD: "A round trip in which a satisfied condition is reopened, has evidence resubmitted, and is satisfied again must restore both `settled_condition_count` and `open_blocking_condition_count` to their exact values before the reopen, while leaving `adjudication_count` strictly higher than before — the audit trail grows even though the counts return to where they started."
    PRD: "`pre_opening_clearance` is true exactly when the filing's own `status` is `CONDITIONALLY_APPROVED` or `FINAL_APPROVED` **and** `open_blocking_condition_count` is 0; a filing sitting in `FILED` with no conditions at all has zero open blockers and still has `pre_opening_clearance` false, because clearance is a statement about an approved filing, not about an empty condition list."

    Design: Difficulty/compensating_invariant/condition_reopen_round_trip_restores_filing_counts
    """
    world = _two_settled_conditions(api)
    fx.adjudicate(api, world["c_pol"], DISPOSITION_REOPENED)
    fx.satisfy_condition(api, world["c_pol"], "BOARD-MIN-2026-09-14-AMENDED-PACKET")

    filing = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(
        filing,
        condition_total_count=2,
        settled_condition_count=2,
        open_blocking_condition_count=0,
        status=FILING_ADDITIONAL_INFO_REQUESTED,
        pre_opening_clearance=False,
    )
    assert_condition_counts_conserved(filing, 2)

    assert_fields_equal(
        fx.read_condition(api, world["c_pol"]),
        status=CONDITION_SATISFIED,
        adjudication_count=3,
    )
    assert_fields_equal(
        fx.read_condition(api, world["c_cap"]),
        status=CONDITION_SATISFIED,
        adjudication_count=1,
    )
