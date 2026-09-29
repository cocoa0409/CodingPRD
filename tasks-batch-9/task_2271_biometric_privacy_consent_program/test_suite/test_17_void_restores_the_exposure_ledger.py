"""The program's exposure ledger is conserved across finalize and void.

Committing an estimate that lands exactly on the freeze boundary freezes the
program; voiding it subtracts the same figure back out with no residue.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    PRIVACY_OFFICER,
    assert_cents,
    assert_program_state,
    current_jurisdiction_version,
    draft_exposure_assessment,
    exposure_units_scenario,
    read_assessment,
    read_program,
    validate_success,
)

VOID = {
    "to_status": "VOID",
    "void_reason": "Plaintiff theory abandoned after counsel review.",
}


def _draft_estimate_at_the_freeze_boundary(api):
    ctx = exposure_units_scenario(api)
    assessment = draft_exposure_assessment(api, ctx, variant="PER_VIOLATION_STACKED")
    assert_cents(assessment["exposure_cents"], 875000, "exposure_cents")
    ctx["assessment_id"] = assessment["id"]
    return ctx


def test_finalizing_commits_the_figure_and_freezes_at_exactly_eighty_percent(api):
    """The ledger takes on 875000 and the master gate closes.

    PRD §2.6: "Otherwise, if `exposure_ceiling_cents` is greater than zero and
    carried exposure has reached at least eighty percent of it, `posture` becomes
    `FROZEN`. The comparison is evaluated entirely in integers — one hundred times
    `pra_exposure_cents` against eighty times `exposure_ceiling_cents` — so no
    floating-point drift is possible and exactly eighty percent does freeze the
    program."

    Two unanswered solicitations at 100,000 cents each and one uncompensated
    revocation at 500,000 cents, multiplied by Illinois's full private right of
    action and the 1.25 notice-gap multiplier, come to 875,000 — exactly eighty
    percent of the board's 1,093,750-cent ceiling.

    Design: Difficulty/compensating_invariant/voiding_a_final_assessment_restores_program_exposure_to_zero_and_unfreezes_posture
    """
    ctx = _draft_estimate_at_the_freeze_boundary(api)
    assert_program_state(
        read_program(api, ctx["program_id"]), pra_exposure_cents=0, posture="RESTRICTED"
    )

    finalized = validate_success(
        api.transition_exposure_assessment(
            ctx["assessment_id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )

    assert finalized["status"] == "FINAL"
    assert_cents(finalized["exposure_cents"], 875000, "exposure_cents")
    assert_program_state(
        read_program(api, ctx["program_id"]), pra_exposure_cents=875000, posture="FROZEN"
    )


def test_voiding_subtracts_the_same_figure_back_out_without_residue(api):
    """The ledger returns to its pre-finalization value exactly.

    PRD §3.9: "A `ComplianceApprover` may void a `FINAL` assessment, `FINAL` →
    `VOID`, and that move is compensating: `exposure_cents` is subtracted back out
    of the program's `pra_exposure_cents`, restoring the pre-finalization value
    exactly, then `posture` is recomputed and the program's `version` is
    incremented by 1."

    The void reverses the ledger, not the recorded figure: the assessment still
    reads 875,000. With the exposure gone the program falls back to `RESTRICTED`,
    because the consent gaps that produced the estimate are still open, and the
    state pairing is free for a fresh draft.

    Design: Difficulty/compensating_invariant/voiding_a_final_assessment_restores_program_exposure_to_zero_and_unfreezes_posture
    """
    ctx = _draft_estimate_at_the_freeze_boundary(api)
    validate_success(
        api.transition_exposure_assessment(
            ctx["assessment_id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )

    voided = validate_success(
        api.transition_exposure_assessment(ctx["assessment_id"], VOID, COMPLIANCE_APPROVER)
    )

    assert voided["status"] == "VOID"
    assert_cents(read_assessment(api, ctx["assessment_id"])["exposure_cents"], 875000, "exposure_cents")
    assert_program_state(
        read_program(api, ctx["program_id"]), pra_exposure_cents=0, posture="RESTRICTED"
    )

    replacement = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": ctx["program_id"],
                "jurisdiction_id": ctx["jurisdiction_id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, ctx["jurisdiction_id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert replacement["status"] == "DRAFT"
    assert_cents(replacement["exposure_cents"], 875000, "exposure_cents")
