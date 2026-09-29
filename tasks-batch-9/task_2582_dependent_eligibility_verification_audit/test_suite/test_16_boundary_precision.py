"""Thresholds tested at the exact value, one unit below, and one unit above.

Two different kinds of boundary appear here: a money floor on demand issuance
and an integer distinct-count floor on documentation completeness.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_pct
from test_helpers.fixtures import REVIEW_INSTANT, recovery_wave, response_window_wave
from test_helpers.test_users import RECOVERY_AGENT

# One pharmacy line of 25000 cents against which the employee contributed a
# single cent of premium: gross exactly at the floor, netted one cent below it.
DE_MINIMIS_CLAIM = {
    "service_date": "2026-09-20",
    "paid_cents": 25000,
    "employee_premium_offset_cents": 1,
    "provider_type": "PHARMACY",
}
ONSET_DATE = "2026-09-01"
FLOOR_CENTS = 25000


def _strict_recovery_at_the_floor(b):
    """A terminated dependent whose STRICT subtotal is exactly the de minimis floor."""
    ctx = recovery_wave(
        b,
        claims=(DE_MINIMIS_CLAIM,),
        recovery_variant="STRICT",
        ineligibility_onset_date=ONSET_DATE,
    )
    assert ctx.recovery["recoverable_subtotal_cents"] == FLOOR_CENTS
    return ctx


def test_a_subtotal_of_exactly_the_de_minimis_floor_is_demandable(b):
    """Twenty-five thousand cents passes; the fee tier below 100000 is zero.

    PRD: "the subtotal must clear a de minimis floor of 25,000 cents: a subtotal
    of exactly 25,000 cents passes, and anything below it is refused with
    `ERR_RECOVERY_BELOW_DE_MINIMIS`"

    Design: Difficulty/boundary_precision_check/de_minimis_recovery_threshold_exact_25000_passes_24999_fails
    """
    ctx = _strict_recovery_at_the_floor(b)

    issued = b.issue_demand(ctx.recovery["id"])

    assert issued["recoverable_subtotal_cents"] == FLOOR_CENTS
    assert_pct(issued["admin_fee_pct"], 0.0)
    assert issued["admin_fee_cents"] == 0
    assert issued["net_demand_cents"] == FLOOR_CENTS
    assert issued["status"] == "DEMAND_ISSUED"
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == FLOOR_CENTS


def test_the_equitable_recomputation_of_the_same_line_falls_one_cent_short(b, client):
    """Netting the one-cent premium offset drops the subtotal to 24999 and it is refused.

    PRD: "each qualifying line contributes its `paid_cents` reduced by its
    `employee_premium_offset_cents`, with any line whose offset exceeds its paid
    amount contributing zero rather than a negative number."

    Design: Difficulty/boundary_precision_check/de_minimis_recovery_threshold_exact_25000_passes_24999_fails
    """
    ctx = _strict_recovery_at_the_floor(b)
    b.issue_demand(ctx.recovery["id"])

    equitable = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        "EQUITABLE",
        ONSET_DATE,
    )
    assert equitable["recoverable_subtotal_cents"] == FLOOR_CENTS - 1

    response = client.issue_demand(
        equitable["id"], f.issue_demand_payload(0), RECOVERY_AGENT
    )
    validate_error(response, E.ERR_RECOVERY_BELOW_DE_MINIMIS, 422)

    refused = b.read_recovery(equitable["id"])
    assert refused["status"] == "OPEN"
    assert refused["net_demand_cents"] == 0


def test_opening_the_equitable_row_supersedes_the_uncollected_demand_and_empties_the_ledger(b):
    """A demand that collected nothing is superseded and stops counting.

    PRD: "any prior recovery of the same dependent whose `status` is `OPEN`, or
    whose `status` is `DEMAND_ISSUED` with `recovered_cents` still exactly zero,
    moves to `SUPERSEDED`, and the program's `recovery_ledger_cents` is
    recomputed so the superseded row no longer counts."

    Design: Difficulty/boundary_precision_check/de_minimis_recovery_threshold_exact_25000_passes_24999_fails
    """
    ctx = _strict_recovery_at_the_floor(b)
    b.issue_demand(ctx.recovery["id"])

    b.open_recovery(ctx.dep["id"], ctx.notice["id"], "EQUITABLE", ONSET_DATE)

    assert b.read_recovery(ctx.recovery["id"])["status"] == "SUPERSEDED"
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == 0


# The spouse rule below asks for two distinct classes, so the count boundary sits
# at two and a duplicate class cannot reach it.
TWO_CLASS_SPOUSE_RULE = {
    "SPOUSE": {
        "acceptable_proof_types": ["MARRIAGE_CERTIFICATE", "JOINT_TAX_RETURN"],
        "min_accepted_documents": 2,
    }
}


def _three_submissions_awaiting_review(b):
    """Two marriage certificates and one redacted joint tax return, all SUBMITTED."""
    ctx = response_window_wave(
        b, relationships=("SPOUSE",), rule_overrides=TWO_CLASS_SPOUSE_RULE
    )
    b.set_clock(REVIEW_INSTANT)
    employee_id = ctx.employee["id"]
    ctx.sub1 = b.submit_proof(
        ctx.case["id"], ctx.dep["id"], employee_id, "MARRIAGE_CERTIFICATE"
    )
    ctx.sub2 = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        employee_id,
        "MARRIAGE_CERTIFICATE",
        document_reference="s3://raw/marriage-cert-certified-copy.pdf",
    )
    ctx.sub3 = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        employee_id,
        "JOINT_TAX_RETURN",
        redaction_applied=True,
    )
    return ctx


def test_one_accepted_class_leaves_the_dependent_one_short_of_the_minimum(b):
    """A single distinct class is below a minimum of two.

    PRD: "The dependent's `documentation_complete` becomes true when
    `accepted_proof_type_count` is greater than or equal to the governing rule's
    `min_accepted_documents` — exactly the minimum is sufficient."

    Design: Difficulty/boundary_precision_check/distinct_accepted_proof_type_count_boundary_at_min_accepted_documents
    """
    ctx = _three_submissions_awaiting_review(b)

    b.accept_proof(ctx.sub1["id"])

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["accepted_proof_type_count"] == 1
    assert dependent["documentation_complete"] is False
    assert dependent["coverage_status"] == "PENDING_VERIFICATION"


def test_a_second_document_of_the_same_class_does_not_move_the_distinct_count(b):
    """Two accepted certificates of one class still count once.

    PRD: "The dependent's `accepted_proof_type_count` is the number of
    **distinct** `proof_type` values in that gathered set, so two accepted joint
    account statements count once and never twice."

    Design: Difficulty/boundary_precision_check/distinct_accepted_proof_type_count_boundary_at_min_accepted_documents
    """
    ctx = _three_submissions_awaiting_review(b)
    b.accept_proof(ctx.sub1["id"])

    second = b.accept_proof(ctx.sub2["id"])

    assert second["review_status"] == "ACCEPTED"
    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["accepted_proof_type_count"] == 1
    assert dependent["documentation_complete"] is False
    assert dependent["coverage_status"] == "PENDING_VERIFICATION"


def test_the_second_distinct_class_reaches_the_minimum_and_verifies_the_dependent(b):
    """Exactly the minimum is sufficient, and verification bubbles up the tree.

    PRD: "The dependent's `documentation_complete` becomes true when
    `accepted_proof_type_count` is greater than or equal to the governing rule's
    `min_accepted_documents` — exactly the minimum is sufficient."

    Design: Difficulty/boundary_precision_check/distinct_accepted_proof_type_count_boundary_at_min_accepted_documents
    """
    ctx = _three_submissions_awaiting_review(b)
    b.accept_proof(ctx.sub1["id"])
    b.accept_proof(ctx.sub2["id"])

    b.accept_proof(ctx.sub3["id"])

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["accepted_proof_type_count"] == 2
    assert dependent["documentation_complete"] is True
    assert dependent["coverage_status"] == "VERIFIED"

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "COMPLETE"
    assert case["unverified_dependent_count"] == 0

    program = b.read_program(ctx.program["id"])
    assert program["verified_dependent_count"] == 1
    assert program["pending_dependent_count"] == 0
