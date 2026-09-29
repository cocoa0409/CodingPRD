"""Cascading recomputation: multi-hop derived-state chains and the compensating
halves of the two conserved ledgers.

Every scenario is built from scratch through PRD-declared endpoints, because the
harness restarts the server and empties the database before each test.
"""

from typing import Any, Dict

from test_helpers import (
    VALIDATOR_USER_ID,
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    evidence_action,
    file_evidence,
    file_ppr,
    make_evidence_validator_headers,
    make_standard_owner_headers,
    open_rounding_session,
    raise_deficiency,
    read_unit,
    record_observation,
    schedule_tracer,
    set_clock,
    tracer_action,
    validate_paginated,
    validate_success,
)

OWNER_ONE = "owner-1"
OWNER_TWO = "owner-2"


# ===========================================================================
# Private setup chains
# ===========================================================================

def _setup_life_safety_escalation_chain() -> Dict[str, Any]:
    """Unit ICU-7 with one SCHEDULED tracer on chapter EC for window
    2026-08-20T08:00Z-10:00Z, plus one OPEN LIFE_SAFETY rounding session holding a
    single MODERATE ticket, with the clock parked at 2026-08-10T00:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], OWNER_ONE, "PRIMARY")
    unit = create_unit("ICU-7", "ICU", 12)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T10:00:00Z",
        tracer_type="PATIENT",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-10T00:00:00Z")
    session = open_rounding_session(
        unit["id"], "LIFE_SAFETY", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    ticket = raise_deficiency(
        session["id"], standard["id"], "MODERATE", "Fire door wedged open"
    )
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit,
        "tracer": tracer,
        "session": session,
        "ticket": ticket,
    }


def _setup_two_standard_chapter_with_submitted_ppr() -> Dict[str, Any]:
    """Chapter PC with exactly two MAPPED standards, one SUBMITTED self-assessment
    for 2026-H2 rating both COMPLIANT, and unit PED-1 carrying an IN_PROGRESS
    tracer on PC with two NON_COMPLIANT observations already recorded."""
    chapter = create_chapter("PC", "Provision of Care", 100, 1)
    first = create_standard(chapter["id"], "PC.01.02.03", "Care planning", "DIRECT_IMPACT")
    second = create_standard(
        chapter["id"], "PC.03.01.01", "Restraint monitoring", "DIRECT_IMPACT"
    )
    assign_owner(first["id"], OWNER_ONE, "PRIMARY")
    assign_owner(second["id"], OWNER_TWO, "PRIMARY")
    ppr = file_ppr(
        chapter["id"],
        "2026-H2",
        [
            {"standard_id": first["id"], "rating": "COMPLIANT"},
            {"standard_id": second["id"], "rating": "COMPLIANT"},
        ],
    )
    unit = create_unit("PED-1", "MED_SURG", 18)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type="PATIENT",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-06T00:00:00Z")
    tracer = tracer_action(tracer["id"], "START")
    record_observation(tracer["id"], first["id"], "NON_COMPLIANT", 1)
    record_observation(tracer["id"], second["id"], "NON_COMPLIANT", 1)
    return {
        "chapter": chapter,
        "first": first,
        "second": second,
        "ppr": ppr,
        "unit": unit,
        "tracer": tracer,
    }


def _setup_evidence_complete_standard_expiring_on_boundary() -> Dict[str, Any]:
    """Chapter IC with evidence_min_count 1 and one MAPPED standard holding a
    single VALIDATED evidence item whose expires_at is 2026-09-01T00:00:00Z, so
    the standard is EVIDENCE_COMPLETE while the clock stays at its default."""
    chapter = create_chapter("IC", "Infection Control", 50, 1)
    standard = create_standard(
        chapter["id"], "IC.01.01.01", "Hand hygiene program", "DIRECT_IMPACT"
    )
    assign_owner(standard["id"], OWNER_ONE, "PRIMARY")
    evidence = file_evidence(
        standard["id"],
        "Hand hygiene audit log",
        "LOG",
        "2026-07-01T00:00:00Z",
        expires_at="2026-09-01T00:00:00Z",
        owner_user_id=OWNER_ONE,
    )
    evidence_action(evidence["id"], "SUBMIT", make_standard_owner_headers(OWNER_ONE))
    evidence = evidence_action(
        evidence["id"],
        "VALIDATE",
        make_evidence_validator_headers(VALIDATOR_USER_ID),
        review_note="Log complete for Q3",
    )
    return {"chapter": chapter, "standard": standard, "evidence": evidence}


def _setup_evidence_complete_standard_with_single_owner() -> Dict[str, Any]:
    """Chapter IC with evidence_min_count 1 and one standard owned by owner-1
    holding one VALIDATED, never-expiring evidence item, so the standard sits in
    EVIDENCE_COMPLETE with both chapter owner-derived counters at one."""
    chapter = create_chapter("IC", "Infection Control", 50, 1)
    standard = create_standard(
        chapter["id"], "IC.01.01.01", "Hand hygiene program", "DIRECT_IMPACT"
    )
    assignment = assign_owner(standard["id"], OWNER_ONE, "PRIMARY")
    evidence = file_evidence(
        standard["id"],
        "Hand hygiene policy",
        "POLICY",
        "2026-07-01T00:00:00Z",
        owner_user_id=OWNER_ONE,
    )
    evidence_action(evidence["id"], "SUBMIT", make_standard_owner_headers(OWNER_ONE))
    evidence = evidence_action(
        evidence["id"],
        "VALIDATE",
        make_evidence_validator_headers(VALIDATOR_USER_ID),
        review_note="Policy current",
    )
    return {
        "chapter": chapter,
        "standard": standard,
        "assignment": assignment,
        "evidence": evidence,
    }


def _setup_unit_with_one_scheduled_tracer() -> Dict[str, Any]:
    """Unit MED-9 in posture OPEN with one SCHEDULED SYSTEM tracer occupying
    2026-08-05T08:00Z-12:00Z on mapped chapter EC."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], OWNER_ONE, "PRIMARY")
    unit = create_unit("MED-9", "MED_SURG", 26)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    return {"chapter": chapter, "standard": standard, "unit": unit, "tracer": tracer}


# ===========================================================================
# transitive_cascade / life_safety_escalation_cascades_to_tracer_abort
# ===========================================================================

def test_life_safety_escalation_raises_severity_and_restricts_the_unit(
    api, safety_officer_headers, director_headers
):
    """PRD §3.5: "`ESCALATE` is reserved to the `SafetyOfficer` and has two declared entry points with no preconditions, `OPEN → ESCALATED` and `IN_PROGRESS → ESCALATED`, whose consequences are identical."
    PRD §3.5: "When the ticket's rounding session has `round_type` `LIFE_SAFETY`, escalation raises the ticket's `severity` to `IMMEDIATE_THREAT` and recomputes its `penalty_points` to the fifteen points that severity carries; an `ENVIRONMENT_OF_CARE` escalation leaves severity and points as they were."
    PRD §3.5: "The unit's `open_deficiency_penalty_points` is then recomputed against the ticket's current points."
    PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."

    Design: Difficulty/transitive_cascade/life_safety_escalation_cascades_to_tracer_abort
    """
    built = _setup_life_safety_escalation_chain()

    escalated = validate_success(
        api.transition_deficiency_ticket(
            built["ticket"]["id"],
            {"action": "ESCALATE", "note": "Life safety deficiency unresolved at shift change"},
            safety_officer_headers,
        )
    )

    assert escalated["state"] == "ESCALATED"
    assert escalated["severity"] == "IMMEDIATE_THREAT"
    assert escalated["penalty_points"] == 15

    unit = validate_success(api.get_unit(built["unit"]["id"], director_headers))
    assert unit["open_deficiency_penalty_points"] == 15
    assert unit["posture"] == "RESTRICTED"


def test_life_safety_escalation_aborts_the_scheduled_tracer_and_clears_readiness(
    api, safety_officer_headers, tracer_surveyor_headers, director_headers
):
    """PRD §3.5: "That recomputation can carry the unit `OPEN → RESTRICTED` once the total reaches fifteen, which aborts every `SCHEDULED` tracer of the unit with `abort_reason` `UNIT_POSTURE_RESTRICTED`, zeroes `scheduled_tracer_count`, and recomputes `readiness_score` and `readiness_band`."
    PRD §3.3: "That transition drags a cascade behind it: every mock tracer of the unit still in `SCHEDULED` moves to `ABORTED` with `abort_reason` set to `UNIT_POSTURE_RESTRICTED`, which zeroes `scheduled_tracer_count` and forces a recomputation of `readiness_score` and `readiness_band`."
    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."

    Design: Difficulty/transitive_cascade/life_safety_escalation_cascades_to_tracer_abort
    """
    built = _setup_life_safety_escalation_chain()
    before = validate_success(api.get_unit(built["unit"]["id"], director_headers))
    assert before["scheduled_tracer_count"] == 1

    validate_success(
        api.transition_deficiency_ticket(
            built["ticket"]["id"],
            {"action": "ESCALATE", "note": "Life safety deficiency unresolved at shift change"},
            safety_officer_headers,
        )
    )

    tracer = validate_success(
        api.get_mock_tracer(built["tracer"]["id"], tracer_surveyor_headers)
    )
    assert tracer["state"] == "ABORTED"
    assert tracer["abort_reason"] == "UNIT_POSTURE_RESTRICTED"

    unit = validate_success(api.get_unit(built["unit"]["id"], director_headers))
    assert unit["scheduled_tracer_count"] == 0
    assert float(unit["readiness_score"]) == 0.00
    assert unit["readiness_band"] == "NOT_ASSESSED"


# ===========================================================================
# transitive_cascade / tracer_completion_cascades_to_ppr_reassessment
# ===========================================================================

def test_tracer_completion_freezes_its_score_and_drives_both_standards_deficient(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §3.4: "`scored_weight` becomes the sum of `weight` across those observations and is kept exact."
    PRD §3.4: "Otherwise `tracer_score` is `earned_weight` divided by `scored_weight`, multiplied by one hundred, rounded half up to two decimal places, and `contributes_to_readiness` becomes true."
    PRD §3.4: "Every standard that carries at least one `NON_COMPLIANT` observation on this tracer moves to `DEFICIENT` and has its `last_noncompliant_observed_at` stamped with the current logical clock."

    Design: Difficulty/transitive_cascade/tracer_completion_cascades_to_ppr_reassessment
    """
    built = _setup_two_standard_chapter_with_submitted_ppr()

    completed = validate_success(
        api.transition_mock_tracer(
            built["tracer"]["id"], {"action": "COMPLETE"}, tracer_surveyor_headers
        )
    )

    assert float(completed["tracer_score"]) == 0.00
    assert completed["contributes_to_readiness"] is True

    for standard_id in (built["first"]["id"], built["second"]["id"]):
        standard = validate_success(api.get_standard(standard_id, director_headers))
        assert standard["compliance_state"] == "DEFICIENT"
        assert standard["last_noncompliant_observed_at"] == "2026-08-06T00:00:00.000Z"


def test_tracer_completion_flips_the_chapter_at_risk_and_returns_the_submitted_ppr(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §3.9: "A new assessment begins at `state` `SUBMITTED` with `requires_reassessment` false and `attested_by_user_id` null."
    PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."
    PRD §3.4: "From `MAPPED` the move is `MAPPED → DEFICIENT` and the chapter's `deficient_standard_count` increases by one; from `EVIDENCE_COMPLETE` the move is `EVIDENCE_COMPLETE → DEFICIENT`, the chapter's `evidence_complete_standard_count` decreases by one **and** its `deficient_standard_count` increases by one."
    PRD §3.4: "Once a chapter's `deficient_standard_count` reaches two, that chapter's `readiness_flag` flips `ON_TRACK → AT_RISK`, and that flip in turn returns every periodic performance review self-assessment of that chapter still in `SUBMITTED` to `RETURNED_FOR_REASSESSMENT` with `requires_reassessment` set to true."

    Design: Difficulty/transitive_cascade/tracer_completion_cascades_to_ppr_reassessment
    """
    built = _setup_two_standard_chapter_with_submitted_ppr()
    assert built["ppr"]["state"] == "SUBMITTED"
    assert float(built["ppr"]["gap"]) == 50.00

    validate_success(
        api.transition_mock_tracer(
            built["tracer"]["id"], {"action": "COMPLETE"}, tracer_surveyor_headers
        )
    )

    chapter = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert chapter["deficient_standard_count"] == 2
    assert chapter["readiness_flag"] == "AT_RISK"

    assessments, _meta = validate_paginated(
        api.list_ppr_self_assessments(built["chapter"]["id"], director_headers)
    )
    returned = next(item for item in assessments if item["id"] == built["ppr"]["id"])
    assert returned["state"] == "RETURNED_FOR_REASSESSMENT"
    assert returned["requires_reassessment"] is True


def test_tracer_completion_recomputes_the_traced_unit_to_not_ready(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §3.4: "Finally, the traced unit's `readiness_score` and `readiness_band` are recomputed under the attested variant — which they must be, since the chapter has just become a participating chapter with a freshly frozen rate."
    PRD §3.3: "The chapter's rate is the sum over those observations of `weight` multiplied by credit, divided by the sum of `weight` over the same observations, rounded half up to four decimal places."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Difficulty/transitive_cascade/tracer_completion_cascades_to_ppr_reassessment
    """
    built = _setup_two_standard_chapter_with_submitted_ppr()

    validate_success(
        api.transition_mock_tracer(
            built["tracer"]["id"], {"action": "COMPLETE"}, tracer_surveyor_headers
        )
    )

    unit = validate_success(api.get_unit(built["unit"]["id"], director_headers))
    assert float(unit["readiness_score"]) == 0.00
    assert unit["readiness_band"] == "NOT_READY"


# ===========================================================================
# transitive_cascade / clock_expiry_cascades_to_chapter_evidence_counter
# ===========================================================================

def test_clock_sweep_expires_the_evidence_item_on_the_inclusive_boundary(
    api, director_headers
):
    """PRD §2.4: "First, the **evidence expiry sweep**: every evidence item in `VALIDATED` whose `expires_at` is not null and is at or before the new clock value moves to `EXPIRED`."
    PRD §2.4: "The boundary is inclusive — an `expires_at` exactly equal to the new clock expires."
    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."
    PRD §3.2: "If that increase brings the count to at least the owning chapter's `evidence_min_count`, the standard transitions `MAPPED → EVIDENCE_COMPLETE` and the chapter's `evidence_complete_standard_count` increases by one."

    Design: Difficulty/transitive_cascade/clock_expiry_cascades_to_chapter_evidence_counter
    """
    built = _setup_evidence_complete_standard_expiring_on_boundary()
    assert built["evidence"]["validation_state"] == "VALIDATED"

    before = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert before["evidence_complete_standard_count"] == 1

    swept = validate_success(api.set_clock("2026-09-01T00:00:00Z", director_headers))
    assert swept["expired_evidence_count"] == 1

    evidence = validate_success(
        api.get_evidence_item(built["evidence"]["id"], director_headers)
    )
    assert evidence["validation_state"] == "EXPIRED"


def test_clock_sweep_pulls_the_standard_back_to_mapped_and_decrements_the_chapter(
    api, director_headers
):
    """PRD §2.4: "Each such expiry decrements the owning standard's `validated_evidence_count`, which may in turn pull the standard from `EVIDENCE_COMPLETE` back to `MAPPED` and decrement its chapter's `evidence_complete_standard_count`."
    PRD §3.2: "Each expiry decreases the standard's `validated_evidence_count` by one, and that decrease can carry the standard `EVIDENCE_COMPLETE → MAPPED` and decrement the chapter's `evidence_complete_standard_count` in the same sweep."
    PRD §3.1: "The four population counters mean exactly what their names say: `standard_count` is the number of standards in the chapter regardless of their compliance state, `mapped_standard_count` is the number whose `active_owner_count` is at least 1, `evidence_complete_standard_count` is the number whose `compliance_state` is `EVIDENCE_COMPLETE`, and `deficient_standard_count` is the number whose `compliance_state` is `DEFICIENT`."

    Design: Difficulty/transitive_cascade/clock_expiry_cascades_to_chapter_evidence_counter
    """
    built = _setup_evidence_complete_standard_expiring_on_boundary()

    validate_success(api.set_clock("2026-09-01T00:00:00Z", director_headers))

    standard = validate_success(api.get_standard(built["standard"]["id"], director_headers))
    assert standard["validated_evidence_count"] == 0
    assert standard["compliance_state"] == "MAPPED"

    chapter = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert chapter["evidence_complete_standard_count"] == 0
    assert chapter["mapped_standard_count"] == 1


# ===========================================================================
# compensating_invariant / chapter_mapped_standard_ledger_reverses_on_owner_revocation
# ===========================================================================

def test_owner_revocation_stamps_revoked_at_and_unmaps_the_standard(api, director_headers):
    """PRD §3.1: "Revocation sets `status` to `REVOKED` and stamps `revoked_at` with the current logical clock, then decreases the standard's `active_owner_count` by one."
    PRD §2.4: "The server maintains a **logical clock** that begins at the fixed instant `2026-08-01T00:00:00Z` and never falls back to real time; every deadline, window boundary, expiry and "current instant" in this specification means the value of that logical clock at the moment the request is processed."
    PRD §2.6: "Instants — `due_at`, `predicted_open_date`, `predicted_close_date`, `command_center_activation_allowed_from`, `follow_up_due_at`, `initial_response_due_at`, `response_due_at`, `revoked_at`, `started_at`, `completed_at`, `closed_at`, `survey_opened_at`, `survey_closed_at`, `accepted_at` and `last_noncompliant_observed_at` — are ISO 8601 UTC with three fractional digits."
    PRD §3.1: "From `EVIDENCE_COMPLETE`, the standard also returns to `UNMAPPED`, the chapter's `mapped_standard_count` decreases by one **and** its `evidence_complete_standard_count` decreases by one — losing the last owner drops the standard out of the evidence-complete population without touching the standard's own `validated_evidence_count`, so the documents are still there and still validated should an owner be reinstated."

    Design: Difficulty/compensating_invariant/chapter_mapped_standard_ledger_reverses_on_owner_revocation
    """
    built = _setup_evidence_complete_standard_with_single_owner()

    revoked = validate_success(
        api.revoke_owner_assignment(
            built["assignment"]["id"],
            {"reason": "Owner left the organisation"},
            director_headers,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == "2026-08-01T00:00:00.000Z"

    standard = validate_success(api.get_standard(built["standard"]["id"], director_headers))
    assert standard["active_owner_count"] == 0
    assert standard["compliance_state"] == "UNMAPPED"


def test_owner_revocation_reverses_both_chapter_counters_and_spares_the_evidence_ledger(
    api, director_headers
):
    """PRD §2.9: "The **chapter mapped-standard ledger** pins `Chapter.mapped_standard_count` to the number of standards in that chapter whose `active_owner_count` is at least 1."
    PRD §3.1: "From `EVIDENCE_COMPLETE`, the standard also returns to `UNMAPPED`, the chapter's `mapped_standard_count` decreases by one **and** its `evidence_complete_standard_count` decreases by one — losing the last owner drops the standard out of the evidence-complete population without touching the standard's own `validated_evidence_count`, so the documents are still there and still validated should an owner be reinstated."
    PRD §3.1: "The four population counters mean exactly what their names say: `standard_count` is the number of standards in the chapter regardless of their compliance state, `mapped_standard_count` is the number whose `active_owner_count` is at least 1, `evidence_complete_standard_count` is the number whose `compliance_state` is `EVIDENCE_COMPLETE`, and `deficient_standard_count` is the number whose `compliance_state` is `DEFICIENT`."

    Design: Difficulty/compensating_invariant/chapter_mapped_standard_ledger_reverses_on_owner_revocation
    """
    built = _setup_evidence_complete_standard_with_single_owner()

    before = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert before["mapped_standard_count"] == 1
    assert before["evidence_complete_standard_count"] == 1

    validate_success(
        api.revoke_owner_assignment(
            built["assignment"]["id"],
            {"reason": "Owner left the organisation"},
            director_headers,
        )
    )

    after = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert after["mapped_standard_count"] == 0
    assert after["evidence_complete_standard_count"] == 0
    assert after["standard_count"] == 1

    standard = validate_success(api.get_standard(built["standard"]["id"], director_headers))
    assert standard["validated_evidence_count"] == 1

    evidence = validate_success(
        api.get_evidence_item(built["evidence"]["id"], director_headers)
    )
    assert evidence["validation_state"] == "VALIDATED"


# ===========================================================================
# compensating_invariant / scheduled_tracer_count_ledger_releases_on_abort
# ===========================================================================

def test_tracer_abort_decrements_the_scheduled_tracer_ledger_back_to_zero(
    api, tracer_surveyor_headers
):
    """PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."
    PRD §3.4: "`SCHEDULED → ABORTED` and `IN_PROGRESS → ABORTED` both set `abort_reason` from the payload and both recompute the unit's `readiness_score` and `readiness_band`."
    PRD §3.4: "They differ only in bookkeeping: aborting from `SCHEDULED` decrements the unit's `scheduled_tracer_count` by one because the tracer was still counted there, while aborting from `IN_PROGRESS` does not, that decrement having already happened at `START`."

    Design: Difficulty/compensating_invariant/scheduled_tracer_count_ledger_releases_on_abort
    """
    built = _setup_unit_with_one_scheduled_tracer()

    before = validate_success(api.get_unit(built["unit"]["id"], tracer_surveyor_headers))
    assert before["scheduled_tracer_count"] == 1

    aborted = validate_success(
        api.transition_mock_tracer(
            built["tracer"]["id"],
            {"action": "ABORT", "abort_reason": "SURVEYOR_UNAVAILABLE"},
            tracer_surveyor_headers,
        )
    )
    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "SURVEYOR_UNAVAILABLE"

    after = validate_success(api.get_unit(built["unit"]["id"], tracer_surveyor_headers))
    assert after["scheduled_tracer_count"] == 0


def test_aborted_tracer_releases_the_window_so_the_identical_interval_reschedules(
    api, tracer_surveyor_headers
):
    """PRD §3.4: "Only tracers of the same unit whose `state` is `SCHEDULED` or `IN_PROGRESS` occupy anything; a tracer that has reached `COMPLETED` or `ABORTED` releases the unit immediately."
    PRD §3.4: "Concretely, a proposed tracer conflicts with an existing one when the proposed `window_start` falls strictly before the existing `window_end` extended by sixty minutes, **and** the proposed `window_end` falls strictly after the existing `window_start`."
    PRD §3.3: "The new unit starts with `posture` `OPEN`, `open_deficiency_penalty_points` at zero, `scheduled_tracer_count` at zero, `readiness_score` at 0.00 and `readiness_band` `NOT_ASSESSED`."
    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."

    Design: Difficulty/compensating_invariant/scheduled_tracer_count_ledger_releases_on_abort
    """
    built = _setup_unit_with_one_scheduled_tracer()
    assert read_unit(built["unit"]["id"])["readiness_band"] == "NOT_ASSESSED"

    validate_success(
        api.transition_mock_tracer(
            built["tracer"]["id"],
            {"action": "ABORT", "abort_reason": "SURVEYOR_UNAVAILABLE"},
            tracer_surveyor_headers,
        )
    )

    released = validate_success(api.get_unit(built["unit"]["id"], tracer_surveyor_headers))
    assert released["scheduled_tracer_count"] == 0
    assert released["readiness_band"] == "NOT_ASSESSED"

    rescheduled = validate_success(
        api.create_mock_tracer(
            {
                "unit_id": built["unit"]["id"],
                "chapter_id": built["chapter"]["id"],
                "tracer_type": "PATIENT",
                "window_start": "2026-08-05T08:00:00Z",
                "window_end": "2026-08-05T12:00:00Z",
                "expected_unit_version": released["version"],
            },
            tracer_surveyor_headers,
        ),
        201,
    )
    assert rescheduled["state"] == "SCHEDULED"

    final = validate_success(api.get_unit(built["unit"]["id"], tracer_surveyor_headers))
    assert final["scheduled_tracer_count"] == 1
    assert final["readiness_band"] == "NOT_ASSESSED"
