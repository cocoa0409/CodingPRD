"""Medication reconciliation: conservation counters, deferral rules and the
attestation gate the reconciliation controls."""
from test_helpers import (
    ADMIN,
    CLINICIAN,
    HIGH_REQUIRED_ELEMENTS,
    MODERATE_REQUIRED_ELEMENTS,
    ApiErrorId,
    append_discrepancy,
    assert_discrepancy,
    assert_med_reconciliation,
    assert_medrec_counters,
    complete_medrec,
    complete_visit,
    connect_contact,
    open_medrec,
    read_episode,
    read_medrec,
    read_visit,
    setup_completed_medrec,
    setup_confirmed_visit,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_error,
    validate_success,
)


def _three_item_reconciliation(ctx, ep):
    medrec = open_medrec(ctx, ep)
    low = append_discrepancy(ctx, medrec["id"], severity="LOW", medication_name="metformin")
    moderate = append_discrepancy(
        ctx,
        medrec["id"],
        severity="MODERATE",
        medication_name="lisinopril",
        discrepancy_type="OMISSION",
    )
    high = append_discrepancy(
        ctx,
        medrec["id"],
        severity="HIGH",
        medication_name="apixaban",
        discrepancy_type="DUPLICATION",
    )
    return medrec, low, moderate, high


def test_disposition_moves_one_unit_out_of_the_unresolved_bucket(api):
    """PRD §2.9: "First, on a medication reconciliation, `discrepancy_count`
    always equals `resolved_count` plus `unresolved_count` plus
    `deferred_count`. A disposition moves one unit out of the unresolved bucket
    into either the resolved or the deferred bucket; a reopen moves one unit
    back. Discrepancies are never deleted, so the total only grows when a
    genuinely new line item is appended."

    Design: Difficulty/compensating_invariant/discrepancy_disposition_then_reopen_conserves_bucket_total
    """
    ctx, ep = setup_program_with_episode()
    medrec, low, moderate, _high = _three_item_reconciliation(ctx, ep)

    validate_success(
        api.disposition_discrepancy(
            low["id"], {"disposition": "RESOLVED", "resolution_note": "dose verified"}, CLINICIAN
        )
    )
    after_resolve = read_medrec(ctx, medrec["id"])
    assert_medrec_counters(
        after_resolve,
        discrepancy_count=3,
        resolved_count=1,
        unresolved_count=2,
        deferred_count=0,
        blocking_unresolved_count=1,
    )

    validate_success(
        api.disposition_discrepancy(
            moderate["id"],
            {"disposition": "DEFERRED", "resolution_note": "deferred to PCP visit"},
            CLINICIAN,
        )
    )
    after_defer = read_medrec(ctx, medrec["id"])
    assert_medrec_counters(
        after_defer,
        discrepancy_count=3,
        resolved_count=1,
        unresolved_count=1,
        deferred_count=1,
        blocking_unresolved_count=1,
    )
    assert after_defer["status"] == "IN_REVIEW"


def test_reopen_returns_the_unit_and_conserves_the_bucket_total(api):
    """PRD §3.5: "A dispositioned line item can be pulled back. Reopening moves
    it `RESOLVED → UNRESOLVED` or `DEFERRED → UNRESOLVED`, taking one unit back
    out of `resolved_count` or `deferred_count` respectively and returning it to
    `unresolved_count`, and then recomputing `blocking_unresolved_count`."
    PRD §3.5: "Throughout all of this, the parent's `discrepancy_count` always
    equals `resolved_count` plus `unresolved_count` plus `deferred_count` — a
    disposition and a reopen each move exactly one unit between buckets and
    never create or destroy one."

    Design: Difficulty/compensating_invariant/discrepancy_disposition_then_reopen_conserves_bucket_total
    """
    ctx, ep = setup_program_with_episode()
    medrec, low, moderate, _high = _three_item_reconciliation(ctx, ep)
    validate_success(
        api.disposition_discrepancy(
            low["id"], {"disposition": "RESOLVED", "resolution_note": "dose verified"}, CLINICIAN
        )
    )
    validate_success(
        api.disposition_discrepancy(
            moderate["id"],
            {"disposition": "DEFERRED", "resolution_note": "deferred to PCP visit"},
            CLINICIAN,
        )
    )

    reopened = validate_success(api.reopen_discrepancy(low["id"], CLINICIAN))
    assert_discrepancy(reopened)
    assert reopened["status"] == "UNRESOLVED"

    after = read_medrec(ctx, medrec["id"])
    assert_medrec_counters(
        after,
        discrepancy_count=3,
        resolved_count=0,
        unresolved_count=2,
        deferred_count=1,
        blocking_unresolved_count=1,
    )
    assert after["status"] == "IN_REVIEW"
    assert validate_success(api.get_discrepancy(moderate["id"], ADMIN))["status"] == "DEFERRED"


def test_zero_item_reconciliation_completes_straight_out_of_open(api):
    """PRD §3.5: "From `OPEN` it is allowed only when `discrepancy_count` is
    exactly 0 — the empty-set boundary, where a reconciliation that found
    nothing completes directly without ever passing through `IN_REVIEW`."
    PRD §3.5: "Completion stamps `completed_at` with the current instant, sets
    the episode's `medrec_complete` to true, and unblocks visit attestation."

    Design: Difficulty/boundary_precision_check/empty_reconciliation_completes_but_one_critical_item_blocks
    """
    ctx, ep = setup_program_with_episode()
    medrec = open_medrec(ctx, ep)
    completed = validate_success(
        api.complete_med_reconciliation(medrec["id"], CLINICIAN)
    )
    assert_med_reconciliation(completed)
    assert completed["status"] == "COMPLETED"
    assert_medrec_counters(
        completed,
        discrepancy_count=0,
        resolved_count=0,
        unresolved_count=0,
        deferred_count=0,
        blocking_unresolved_count=0,
    )
    assert read_episode(ctx, ep["episode_id"])["medrec_complete"] is True


def test_one_unresolved_critical_item_blocks_reconciliation_completion(api):
    """PRD §3.5: "From `IN_REVIEW` it is allowed only when
    `blocking_unresolved_count` is 0, meaning no `HIGH` or `CRITICAL` line item
    remains unresolved; deferred low and moderate items do not block completion.
    A blocking item present at this moment is reported as
    `ERR_BLOCKING_DISCREPANCY_UNRESOLVED`."

    Design: Difficulty/boundary_precision_check/empty_reconciliation_completes_but_one_critical_item_blocks
    """
    ctx, ep = setup_program_with_episode()
    medrec = open_medrec(ctx, ep)
    append_discrepancy(
        ctx,
        medrec["id"],
        severity="CRITICAL",
        medication_name="warfarin",
        discrepancy_type="INTERACTION",
    )

    validate_error(
        api.complete_med_reconciliation(medrec["id"], CLINICIAN),
        ApiErrorId.ERR_BLOCKING_DISCREPANCY_UNRESOLVED.value,
    )
    after = read_medrec(ctx, medrec["id"])
    assert after["status"] == "IN_REVIEW"
    assert_medrec_counters(
        after,
        discrepancy_count=1,
        unresolved_count=1,
        blocking_unresolved_count=1,
    )
    assert read_episode(ctx, ep["episode_id"])["medrec_complete"] is False


def test_attestation_is_refused_while_the_reconciliation_is_in_review(api):
    """PRD §3.4: "the episode's medication reconciliation must exist and be
    `COMPLETED`, and must have been completed no later than the visit's
    `completed_at` instant, or the request is refused with
    `ERR_MEDREC_NOT_COMPLETE`"

    Design: Difficulty/cross_entity_state_dependency/visit_attest_requires_completed_medreconciliation
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    medrec = open_medrec(ctx, ep)
    line = append_discrepancy(ctx, medrec["id"], severity="LOW")
    validate_success(
        api.disposition_discrepancy(
            line["id"],
            {"disposition": "RESOLVED", "resolution_note": "dose confirmed with pharmacy"},
            CLINICIAN,
        )
    )
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )

    validate_error(
        api.attest_visit(visit["id"], CLINICIAN),
        ApiErrorId.ERR_MEDREC_NOT_COMPLETE.value,
    )
    assert read_visit(ctx, visit["id"])["documentation_status"] == "DRAFT"
    assert read_medrec(ctx, medrec["id"])["status"] == "IN_REVIEW"


def test_attestation_succeeds_once_the_reconciliation_completes(api):
    """PRD §3.5: "Completion stamps `completed_at` with the current instant,
    sets the episode's `medrec_complete` to true, and unblocks visit
    attestation."
    PRD §3.4: "A successful attestation moves the documentation `DRAFT →
    ATTESTED`, records `attested_by_user_id` from the acting `X-User-ID` and
    `attested_at` from the logical clock, and derives `achieved_complexity`:
    `HIGH_COMPLEXITY` when the documented elements cover the full
    high-complexity set — `MED_REC_REVIEWED`, `DISCHARGE_SUMMARY_REVIEWED`,
    `PATIENT_EDUCATION`, `HIGH_COMPLEXITY_MDM` and `COMMUNITY_SERVICE_REFERRAL`
    — and `MODERATE_COMPLEXITY` otherwise."

    Design: Difficulty/cross_entity_state_dependency/visit_attest_requires_completed_medreconciliation
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    medrec = open_medrec(ctx, ep)
    line = append_discrepancy(ctx, medrec["id"], severity="LOW")
    validate_success(
        api.disposition_discrepancy(
            line["id"],
            {"disposition": "RESOLVED", "resolution_note": "dose confirmed with pharmacy"},
            CLINICIAN,
        )
    )
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )
    validate_error(
        api.attest_visit(visit["id"], CLINICIAN),
        ApiErrorId.ERR_MEDREC_NOT_COMPLETE.value,
    )

    completed = complete_medrec(ctx, medrec["id"])
    assert completed["status"] == "COMPLETED"
    assert_medrec_counters(
        completed,
        discrepancy_count=1,
        resolved_count=1,
        unresolved_count=0,
        deferred_count=0,
    )

    attested = validate_success(api.attest_visit(visit["id"], CLINICIAN))
    assert attested["documentation_status"] == "ATTESTED"
    assert attested["achieved_complexity"] == "MODERATE_COMPLEXITY"
    assert read_episode(ctx, ep["episode_id"])["medrec_complete"] is True


def test_critical_discrepancy_cannot_be_deferred_but_a_low_one_can(api):
    """PRD §3.5: "`UNRESOLVED → DEFERRED` moves one unit out of
    `unresolved_count` and into `deferred_count` — but deferral is available
    only to line items whose `severity` is `LOW` or `MODERATE`. A `HIGH` or
    `CRITICAL` discrepancy is clinically non-deferrable and must actually be
    resolved; attempting to defer one is rejected with
    `ERR_DEFERRAL_NOT_PERMITTED`."

    Design: Corner/validations/critical_discrepancy_cannot_be_deferred
    """
    ctx, ep = setup_program_with_episode()
    medrec = open_medrec(ctx, ep)
    critical = append_discrepancy(
        ctx,
        medrec["id"],
        severity="CRITICAL",
        medication_name="warfarin",
        discrepancy_type="ALLERGY_CONFLICT",
    )
    low = append_discrepancy(
        ctx,
        medrec["id"],
        severity="LOW",
        medication_name="vitamin d",
        discrepancy_type="OMISSION",
    )

    validate_error(
        api.disposition_discrepancy(
            critical["id"],
            {"disposition": "DEFERRED", "resolution_note": "defer to outpatient"},
            CLINICIAN,
        ),
        ApiErrorId.ERR_DEFERRAL_NOT_PERMITTED.value,
    )
    assert validate_success(api.get_discrepancy(critical["id"], ADMIN))["status"] == "UNRESOLVED"

    deferred = validate_success(
        api.disposition_discrepancy(
            low["id"],
            {"disposition": "DEFERRED", "resolution_note": "defer to outpatient"},
            CLINICIAN,
        )
    )
    assert deferred["status"] == "DEFERRED"

    assert_medrec_counters(
        read_medrec(ctx, medrec["id"]),
        discrepancy_count=2,
        unresolved_count=1,
        deferred_count=1,
        resolved_count=0,
        blocking_unresolved_count=1,
    )


def test_reopening_the_reconciliation_reblocks_attestation(api):
    """PRD §3.5: "A completed reconciliation may be reopened by a `Clinician`,
    moving it `COMPLETED → IN_REVIEW`, incrementing `reopen_count` by 1,
    clearing `completed_at` and setting the episode's `medrec_complete` back to
    false — which re-blocks attestation until the reconciliation is completed
    again."

    Design: Corner/state_machines/medrec_reopen_cycle_reblocks_attestation
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    medrec = setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )
    validate_success(api.attest_visit(visit["id"], CLINICIAN))
    current = read_visit(ctx, visit["id"])
    validate_success(
        api.amend_visit(
            visit["id"],
            {
                "documented_elements": list(HIGH_REQUIRED_ELEMENTS),
                "expected_visit_version": current["version"],
            },
            CLINICIAN,
        )
    )

    reopened = validate_success(api.reopen_med_reconciliation(medrec["id"], CLINICIAN))
    assert reopened["status"] == "IN_REVIEW"
    assert reopened["reopen_count"] == 1
    assert reopened["completed_at"] is None
    assert read_episode(ctx, ep["episode_id"])["medrec_complete"] is False

    validate_error(
        api.attest_visit(visit["id"], CLINICIAN),
        ApiErrorId.ERR_MEDREC_NOT_COMPLETE.value,
    )
    assert read_visit(ctx, visit["id"])["documentation_status"] == "AMENDED"

    recompleted = complete_medrec(ctx, medrec["id"])
    assert recompleted["status"] == "COMPLETED"
    assert read_episode(ctx, ep["episode_id"])["medrec_complete"] is True

    final = validate_success(api.attest_visit(visit["id"], CLINICIAN))
    assert final["documentation_status"] == "ATTESTED"
    assert final["achieved_complexity"] == "HIGH_COMPLEXITY"


def test_stale_reconciliation_version_rejects_a_new_line_item(api):
    """PRD §2.6: "Appending a discrepancy line item to a medication
    reconciliation requires `expected_med_reconciliation_version` carrying the
    client's last observed `version` of that `MedReconciliation`. Every
    disposition and every reopen shifts the reconciliation's counters, so a
    caller with a stale view would be appending a line item against a
    conservation state it has not seen; a mismatch is refused."
    PRD §2.6: "In each case the version field is a **required** part of the
    request body — omitting it is a plain request-validation failure — and in
    each case a value that does not equal the parent's current `version` is
    rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_medrec_version_rejects_discrepancy_creation
    """
    ctx = setup_program()
    ep = setup_episode(ctx)
    medrec = open_medrec(ctx, ep)
    stale_version = medrec["version"]
    validate_success(
        api.append_discrepancy(
            medrec["id"],
            {
                "medication_name": "metformin",
                "discrepancy_type": "DOSE_MISMATCH",
                "severity": "LOW",
                "expected_med_reconciliation_version": stale_version,
            },
            CLINICIAN,
        ),
        201,
    )

    validate_error(
        api.append_discrepancy(
            medrec["id"],
            {
                "medication_name": "lisinopril",
                "discrepancy_type": "OMISSION",
                "severity": "MODERATE",
                "expected_med_reconciliation_version": stale_version,
            },
            CLINICIAN,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    after = read_medrec(ctx, medrec["id"])
    assert_medrec_counters(
        after,
        discrepancy_count=1,
        unresolved_count=1,
        resolved_count=0,
        deferred_count=0,
    )
    assert after["version"] == stale_version + 1
    assert after["status"] == "IN_REVIEW"
