"""The audit-failure cascade and the appropriation identity across a clawback."""

from test_helpers import (
    add_milestone,
    api_client,
    issue_clawback_notice,
    read_award,
    read_location,
    read_program,
    read_subgrantee,
    resolve_clawback,
    setup_construction_authorized_award,
    setup_disbursed_milestone,
    setup_failed_audit,
    submit_milestone_evidence,
    validate_paginated,
    verify_milestone,
)
from test_helpers.fixtures import ADMIN


def _award_with_one_disbursed_and_one_approved_milestone():
    """An IN_CONSTRUCTION award whose first milestone over L2 is DISBURSED and
    whose second milestone over L3 is APPROVED but still unpaid."""
    ctx = setup_construction_authorized_award()
    ctx["disbursed_milestone"] = setup_disbursed_milestone(
        ctx, milestone_location_keys=("L2",), sequence_no=1
    )

    pending = add_milestone(ctx["award_id"], 2, [ctx["location_ids"]["L3"]])
    submit_milestone_evidence(
        ctx["award_id"], pending["id"], [ctx["location_ids"]["L3"]], ctx["subgrantee_id"]
    )
    ctx["approved_milestone"] = verify_milestone(
        ctx["award_id"], pending["id"], "APPROVED"
    )
    return ctx


def test_failed_audit_flips_the_award_and_marks_only_the_failed_locations():
    """Hop one of the failure cascade: the listed location drops to AUDIT_FAILED
    and loses its certification stamp, the award turns NONCOMPLIANT, and a tested
    but passing location is left alone.

    PRD 3.9: "`failed_location_ids` is stamped; each listed location moves on the
    service axis to `AUDIT_FAILED` — as `SERVICE_AVAILABLE → AUDIT_FAILED` for
    one not yet certified and as `CERTIFIED → AUDIT_FAILED` for one already
    certified — and a location that was `CERTIFIED` also has its `certified_at`
    cleared to null. The award's `compliance_state` moves `COMPLIANT →
    NONCOMPLIANT`, and the award's `failed_location_count` and
    `certified_location_count` are re-derived."
    PRD 3.9: "The multiplier is then selected by tier, with every tier boundary
    inclusive on its upper edge: 1.00 when the share is at most 0.10, 1.10 when
    it is at most 0.25, 1.25 when it is at most 0.50, and 1.50 above that — so a
    share of exactly 0.5000 selects 1.25, not 1.50."

    Design: Difficulty/transitive_cascade/audit_failure_three_hop_suspension_cascade
    """
    ctx = _award_with_one_disbursed_and_one_approved_milestone()
    assert read_location(ctx["location_ids"]["L2"])["service_state"] == "CERTIFIED"
    assert read_location(ctx["location_ids"]["L3"])["service_state"] == "SERVICE_AVAILABLE"

    audit = setup_failed_audit(ctx, ("L2", "L3"), ("L2",))

    assert audit["audit_state"] == "FAILED"
    assert audit["tested_location_count"] == 2
    assert audit["failed_location_count"] == 1
    assert audit["noncompliant_share"] == 0.3333, (
        "One failed location over three confirmed locations is 0.333333, rounded "
        "half up to four decimals"
    )
    assert audit["penalty_multiplier"] == 1.25, "A share of 0.3333 sits in the 0.50 tier"

    failed = read_location(ctx["location_ids"]["L2"])
    assert failed["service_state"] == "AUDIT_FAILED"
    assert failed["certified_at"] is None

    untouched = read_location(ctx["location_ids"]["L3"])
    assert untouched["service_state"] == "SERVICE_AVAILABLE"

    award = read_award(ctx["award_id"])
    assert award["compliance_state"] == "NONCOMPLIANT"
    assert award["failed_location_count"] == 1
    assert award["certified_location_count"] == 0
    assert award["disbursed_to_date_cents"] == 675001


def test_failed_audit_holds_the_unpaid_milestone_and_suspends_the_applicant():
    """Hops two and three: the compliance change freezes the still-unpaid
    APPROVED milestone with its payable amount zeroed and suspends the applicant,
    while the milestone already DISBURSED keeps both its state and its figure.

    PRD 3.9: "**Hop 2**, caused by hop 1's compliance change. Every milestone of
    that award moves to `HELD` — as `EVIDENCE_SUBMITTED → HELD` for one awaiting
    verification and as `APPROVED → HELD` for one already verified — and has its
    `payable_amount_cents` zeroed — for an already-approved milestone this
    releases a reserved disbursement."
    PRD 3.9: "**Hop 3**, caused by hop 2's non-empty held set. The award's
    applicant moves `QUALIFIED → SUSPENDED` and its `open_noncompliance_count`
    rises by one."

    Design: Difficulty/transitive_cascade/audit_failure_three_hop_suspension_cascade
    """
    ctx = _award_with_one_disbursed_and_one_approved_milestone()
    disbursed_id = ctx["disbursed_milestone"]["id"]
    approved_id = ctx["approved_milestone"]["id"]
    assert ctx["approved_milestone"]["payable_amount_cents"] == 675001
    assert read_subgrantee(ctx["subgrantee_id"])["capability_state"] == "QUALIFIED"

    setup_failed_audit(ctx, ("L2", "L3"), ("L2",))

    rows, _ = validate_paginated(api_client.list_milestones(ctx["award_id"], ADMIN))
    by_id = {m["id"]: m for m in rows}
    assert by_id[approved_id]["milestone_state"] == "HELD"
    assert by_id[approved_id]["payable_amount_cents"] == 0
    assert by_id[disbursed_id]["milestone_state"] == "DISBURSED", (
        "A milestone already paid out is outside the held set"
    )
    assert by_id[disbursed_id]["payable_amount_cents"] == 675001

    applicant = read_subgrantee(ctx["subgrantee_id"])
    assert applicant["capability_state"] == "SUSPENDED"
    assert applicant["open_noncompliance_count"] == 1


def _award_with_a_clawback_notice():
    """An IN_CONSTRUCTION award that has paid out 675001 cents and then failed an
    audit on its single certified location, with the clawback notice issued."""
    ctx = setup_construction_authorized_award()
    setup_disbursed_milestone(ctx, milestone_location_keys=("L2",), sequence_no=1)

    audit = setup_failed_audit(ctx, ("L2",), ("L2",))
    ctx["audit"] = issue_clawback_notice(ctx["award_id"], audit["id"])
    ctx["audit_id"] = audit["id"]
    return ctx


def test_clawback_settlement_moves_money_from_disbursed_back_to_uncommitted():
    """The recovery is computed in two rounded steps, and settling it lowers the
    disbursed balance and raises the uncommitted balance by exactly that amount
    while the obligated bucket is untouched.

    PRD 3.9: "The recovery is computed in two rounded steps: a base recovery is
    the award's `disbursed_to_date_cents` multiplied by `failed_location_count`
    and divided by the award's `confirmed_location_count` — using the exact
    unrounded fraction — rounded half up to a whole cent; that base is then
    multiplied by `penalty_multiplier`, rounded half up to a whole cent again,
    and the result is capped at the award's `disbursed_to_date_cents`, because
    the office can never recover more than it paid."
    PRD 3.9: "A `CLAWBACK_RECOVERY` ledger entry for that amount is appended, the
    award's `disbursed_to_date_cents` is reduced, the program's
    `disbursed_balance_cents` falls and its `uncommitted_balance_cents` rises by
    the settled amount, the award's `compliance_state` becomes `CURED`, and every
    location in `failed_location_ids` still sitting at `AUDIT_FAILED` has its
    `certified_at` cleared to null so that the award's re-derived
    `certified_location_count` returns to its pre-certification value for those
    locations."

    Design: Difficulty/compensating_invariant/program_funds_identity_across_disbursement_and_clawback
    """
    ctx = _award_with_a_clawback_notice()
    assert ctx["audit"]["recovery_amount_cents"] == 281250, (
        "675001 times one third is 225000.33 rounded to 225000, and 225000 times "
        "1.25 is 281250"
    )

    before = read_program(ctx["program_id"])
    assert before["uncommitted_balance_cents"] == 97974997
    assert before["obligated_balance_cents"] == 1350002
    assert before["disbursed_balance_cents"] == 675001

    settled = resolve_clawback(
        ctx["award_id"], ctx["audit_id"], "SETTLED", settled_amount_cents=281250
    )
    assert settled["audit_state"] == "CLAWBACK_SETTLED"
    assert settled["settled_amount_cents"] == 281250

    award = read_award(ctx["award_id"])
    assert award["disbursed_to_date_cents"] == 393751, "675001 less the 281250 recovered"
    assert award["compliance_state"] == "CURED"
    assert award["certified_location_count"] == 0
    assert read_location(ctx["location_ids"]["L2"])["certified_at"] is None

    after = read_program(ctx["program_id"])
    assert after["uncommitted_balance_cents"] == 98256247
    assert after["obligated_balance_cents"] == 1350002, (
        "The recovery never touches the obligated bucket"
    )
    assert after["disbursed_balance_cents"] == 393751
    assert (
        after["uncommitted_balance_cents"]
        + after["obligated_balance_cents"]
        + after["disbursed_balance_cents"]
        == 100000000
    )


def test_the_ledger_re_derives_the_balances_without_rewriting_earlier_entries():
    """Each fiscal movement appends one row and the three balances are replayed
    from the whole set, so the identity holds after obligation, after
    disbursement and again after the recovery, with the earlier rows unchanged.

    PRD 2.11: "Entries are never updated or deleted, so replaying them in full is
    the definition of the program's balances rather than a cache of them."
    PRD 2.11: "Then `uncommitted_balance_cents` is `total_appropriation_cents`
    minus the obligation total, plus the deobligation total, plus the recovery
    total; `obligated_balance_cents` is the obligation total minus the
    deobligation total minus the disbursement total; and
    `disbursed_balance_cents` is the disbursement total minus the recovery
    total."
    PRD 2.11: "The invariant that must hold after every mutation is that
    `total_appropriation_cents` equals the sum of `uncommitted_balance_cents`,
    `obligated_balance_cents` and `disbursed_balance_cents`."

    Design: Difficulty/compensating_invariant/program_funds_identity_across_disbursement_and_clawback
    """
    ctx = _award_with_a_clawback_notice()

    def balances():
        program = read_program(ctx["program_id"])
        assert (
            program["uncommitted_balance_cents"]
            + program["obligated_balance_cents"]
            + program["disbursed_balance_cents"]
            == program["total_appropriation_cents"]
        )
        return program

    balances()
    before_rows, before_meta = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    assert before_meta["total_count"] == 2
    assert [(r["entry_type"], r["amount_cents"]) for r in before_rows] == [
        ("OBLIGATION", 2025003),
        ("DISBURSEMENT", 675001),
    ]

    resolve_clawback(
        ctx["award_id"], ctx["audit_id"], "SETTLED", settled_amount_cents=281250
    )

    balances()
    after_rows, after_meta = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    assert after_meta["total_count"] == 3
    assert [(r["entry_type"], r["amount_cents"]) for r in after_rows] == [
        ("OBLIGATION", 2025003),
        ("DISBURSEMENT", 675001),
        ("CLAWBACK_RECOVERY", 281250),
    ]
    assert [r["id"] for r in after_rows[:2]] == [r["id"] for r in before_rows], (
        "The recovery is a new row rather than an edit of the earlier two"
    )
    assert after_rows[2]["program_uncommitted_after_cents"] == 98256247
