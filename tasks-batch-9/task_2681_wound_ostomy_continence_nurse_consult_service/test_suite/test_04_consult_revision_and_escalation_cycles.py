"""The two cycles in the consult machine: the revision loop that terminates on a
counter and the escalation loop that hands work from one nurse to another."""
from test_helpers import (
    as_instant,
    assign_consult,
    create_certified_nurse,
    create_consult,
    create_patient,
    create_trainee_nurse,
    create_unit,
    get_success_data,
    set_clock,
    triage_consult,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_director_headers,
    make_nurse_headers,
    make_unit_charge_headers,
)


DIRECTOR = make_director_headers()


def _returnable_consult(api, mrn, note):
    """Unit 7W, a certified nurse and a `WOUND` consult claiming `STAGE_1`."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn=mrn,
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=1,
        device_related_risk=False,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note=note,
    )
    return unit, nurse, patient, consult


def test_the_return_leaves_the_score_but_stops_the_clock_and_the_resubmit_wipes_it(api):
    """One full turn of the revision cycle, field by field.

    PRD §3.4: "The return deliberately leaves `clinical_note`, `acuity_score` and
    `priority_band` intact so the history is legible, but it clears `sla_due_at` to
    null, because the service is no longer on the clock while the ward is gathering
    information."
    PRD §3.4: "The requesting `UnitCharge` then resubmits, moving the consult
    `RETURNED_FOR_INFO → REQUESTED` with a revised `clinical_note` and a revised
    `reported_stage`; resubmission adds 1 to `revision_count` and wipes the whole
    triage output — `acuity_score`, `acuity_variant`, `priority_band`, `triaged_at`
    and `sla_due_at` all return to null — so that triage runs again from scratch
    against the revised claim."

    Design: Difficulty/non_linear_state_machine/consult_return_resubmit_cycle_increments_revision
    """
    unit, nurse, _patient, consult = _returnable_consult(
        api, "MRN-C1", "Sacral redness, no measurement supplied."
    )
    nurse_headers = make_nurse_headers(nurse["id"])
    charge = make_unit_charge_headers(unit["id"])

    triaged = validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    assert triaged["acuity_score"] == 25.0, "(STAGE_1 20 + min(25, 5 * 1)) * 1.00 = 25.0"
    assert triaged["priority_band"] == "P3"
    assert triaged["status"] == "TRIAGED"

    returned = validate_success(
        api.return_consult_request(
            consult["id"],
            {"reason": "No wound measurement and no photograph attached."},
            nurse_headers,
        )
    )
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["sla_due_at"] is None, "the service is no longer on the clock"
    assert returned["acuity_score"] == 25.0, "the score is left intact so history stays legible"
    assert returned["priority_band"] == "P3"
    assert returned["revision_count"] == 0, "the return itself consumes no revision"

    resubmitted = validate_success(
        api.resubmit_consult_request(
            consult["id"],
            {
                "clinical_note": "Sacral full-thickness loss with visible subcutaneous fat.",
                "reported_stage": "STAGE_3",
            },
            charge,
        )
    )
    assert resubmitted["status"] == "REQUESTED"
    assert resubmitted["revision_count"] == 1
    assert resubmitted["acuity_score"] is None
    assert resubmitted["acuity_variant"] is None
    assert resubmitted["priority_band"] is None
    assert resubmitted["triaged_at"] is None
    assert resubmitted["sla_due_at"] is None
    assert resubmitted["reported_stage"] == "STAGE_3"

    retriaged = validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    assert retriaged["acuity_score"] == 65.0, "(STAGE_3 60 + 5) * 1.00 = 65.0"
    assert retriaged["priority_band"] == "P2", "one full loop moved the band from P3 to P2"


def test_the_third_return_is_refused_once_two_revisions_are_consumed(api):
    """The loop closes on the revision counter, not on a terminal state.

    PRD §3.4: "This is a genuine cycle: `TRIAGED → RETURNED_FOR_INFO → REQUESTED →
    TRIAGED` may be walked twice."
    PRD §3.4: "Both legs are gated on `revision_count` being strictly below 2, and
    once two revisions have been consumed both the return and the resubmit are
    refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/consult_return_resubmit_cycle_increments_revision
    """
    unit, nurse, _patient, consult = _returnable_consult(
        api, "MRN-C1", "Sacral redness, no measurement supplied."
    )
    nurse_headers = make_nurse_headers(nurse["id"])
    charge = make_unit_charge_headers(unit["id"])

    validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    validate_success(
        api.return_consult_request(
            consult["id"],
            {"reason": "No wound measurement and no photograph attached."},
            nurse_headers,
        )
    )
    first_resubmit = validate_success(
        api.resubmit_consult_request(
            consult["id"],
            {
                "clinical_note": "Sacral full-thickness loss with visible subcutaneous fat.",
                "reported_stage": "STAGE_3",
            },
            charge,
        )
    )
    assert first_resubmit["revision_count"] == 1
    validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    validate_success(
        api.return_consult_request(
            consult["id"],
            {"reason": "Stage upgraded without documenting undermining depth."},
            nurse_headers,
        )
    )
    second_resubmit = validate_success(
        api.resubmit_consult_request(
            consult["id"],
            {
                "clinical_note": "Sacral wound with exposed bone and undermining 3cm at 6 o'clock.",
                "reported_stage": "STAGE_4",
            },
            charge,
        )
    )
    assert second_resubmit["revision_count"] == 2
    assert second_resubmit["reported_stage"] == "STAGE_4"

    third_triage = validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    assert third_triage["acuity_score"] == 85.0, "(STAGE_4 80 + 5) * 1.00 = 85.0"
    assert third_triage["priority_band"] == "P1"
    assert as_instant(third_triage["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z")

    validate_error(
        api.return_consult_request(
            consult["id"], {"reason": "Third bounce attempt."}, nurse_headers
        ),
        "ERR_REVISION_LIMIT_REACHED",
        expected_status=409,
    )
    after = get_success_data(api.get_consult_request(consult["id"], charge))
    assert after["status"] == "TRIAGED", "the refused return left the consult where it was"
    assert after["revision_count"] == 2
    assert after["acuity_score"] == 85.0


def test_triage_is_not_a_legal_move_out_of_returned_for_info(api):
    """`RETURNED_FOR_INFO` accepts resubmit and cancel, never a second triage.

    PRD §2.10 rung 10: "The consult request's `status` is a legal starting state for
    the requested transition — `ERR_CONSULT_INVALID_STATE` (409), on
    `POST /consult-requests/{consult_id}/triage`, `/return`, `/resubmit`, `/assign`,
    `/escalate`, `/close` and `/cancel`, and also on `POST /skin-assessments`,
    `POST /dressing-protocols` and `POST /ostomy-education-plans`, each of which
    requires its referenced consult to be in a permitted state."
    PRD §3.4: "A `WocNurse` triages a `REQUESTED` consult whose patient is still
    `ADMITTED`, moving it `REQUESTED → TRIAGED`."

    Design: Corner/state_machines/triage_from_returned_for_info_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    nurse_headers = make_nurse_headers(nurse["id"])
    patient = create_patient(unit, api=api, mrn="MRN-G3", admitted_at="2026-07-31T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note="Redness, no measurement supplied.",
    )
    validate_success(api.triage_consult_request(consult["id"], nurse_headers))
    validate_success(
        api.return_consult_request(
            consult["id"], {"reason": "Measurement and photo missing."}, nurse_headers
        )
    )

    validate_error(
        api.triage_consult_request(consult["id"], nurse_headers),
        "ERR_CONSULT_INVALID_STATE",
        expected_status=409,
    )
    after = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert after["status"] == "RETURNED_FOR_INFO"
    assert after["revision_count"] == 0, "the rejection consumed no revision"
    assert after["acuity_score"] == 20.0, "the return left the score in place"
    assert after["priority_band"] == "P3"
    assert after["sla_due_at"] is None, "the refused triage did not restore the SLA clock"


def test_a_cancelled_consult_refuses_both_a_second_cancel_and_a_close(api):
    """`CANCELLED` is terminal for every remaining verb, under one shared code.

    PRD §3.4: "A consult already `CLOSED` or `CANCELLED` cannot be cancelled again,
    and the attempt is an `ERR_CONSULT_INVALID_STATE`."
    PRD §3.4: "Only a `PLAN_ACTIVE` consult may be closed, and only by a `WocNurse`,
    supplying a `closing_summary` narrative that is stored on the record."

    Design: Corner/state_machines/cancelled_consult_cannot_be_cancelled_or_closed_again
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = create_patient(unit, api=api, mrn="MRN-G5", admitted_at="2026-07-31T00:00:00Z")
    nurse = create_trainee_nurse(unit, api=api, full_name="Nina Stage")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note="Filed in error.",
    )
    cancelled = validate_success(
        api.cancel_consult_request(
            consult["id"], {"reason": "Duplicate of an existing consult."}, DIRECTOR
        )
    )
    assert cancelled["status"] == "CANCELLED"
    version_after_cancel = cancelled["version"]

    validate_error(
        api.cancel_consult_request(consult["id"], {"reason": "Second attempt."}, DIRECTOR),
        "ERR_CONSULT_INVALID_STATE",
        expected_status=409,
    )
    validate_error(
        api.close_consult_request(
            consult["id"],
            {"closing_summary": "Attempting to close a cancelled consult."},
            make_nurse_headers(nurse["id"]),
        ),
        "ERR_CONSULT_INVALID_STATE",
        expected_status=409,
    )
    after = get_success_data(api.get_consult_request(consult["id"], charge))
    assert after["status"] == "CANCELLED"
    assert after["closing_summary"] is None
    assert after["version"] == version_after_cancel, "neither refused call wrote anything"


def test_escalation_holds_the_load_and_reassignment_moves_it(api):
    """`ESCALATED` is not terminal; re-routing returns the consult to `ASSIGNED`.

    PRD §3.4: "When the clock runs out on an assigned consult, a `WocNurse` or a
    `WocProgramDirector` escalates it with a `reason`, moving it
    `ASSIGNED → ESCALATED` and adding 1 to `escalation_count`."
    PRD §3.4: "The assigned nurse's `active_consult_load` is deliberately *not*
    reduced — the consult is late, not abandoned, and it continues to occupy the
    nurse's capacity."
    PRD §3.4: "When the payload names a different nurse from the one currently
    holding the consult, the displaced nurse's `active_consult_load` falls by 1, the
    incoming nurse's rises by 1, and both nurse rows are versioned; the incoming
    nurse must satisfy the load headroom check."

    Design: Corner/state_machines/escalate_then_reassign_returns_consult_to_assigned
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    omar = create_certified_nurse(unit, api=api, full_name="Omar Verify")
    patient = create_patient(unit, api=api, mrn="MRN-G6", admitted_at="2026-07-31T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note="Stage 1 sacral redness.",
    )
    triaged = triage_consult(consult, nina, api=api)
    assert triaged["acuity_score"] == 20.0
    assert triaged["priority_band"] == "P3"
    assert as_instant(triaged["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    assign_consult(consult, nina, api=api)
    set_clock("2026-08-05T00:00:00Z", api=api)

    escalated = validate_success(
        api.escalate_consult_request(
            consult["id"],
            {"reason": "SLA breached; no bedside assessment filed."},
            DIRECTOR,
        )
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalation_count"] == 1
    assert get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))["active_consult_load"] == 1, (
        "an escalated consult keeps occupying the nurse's capacity"
    )

    reassigned = validate_success(
        api.assign_consult_request(
            consult["id"], {"assigned_nurse_id": omar["id"]}, DIRECTOR
        )
    )
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_nurse_id"] == omar["id"]
    assert get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))["active_consult_load"] == 0
    assert get_success_data(api.get_woc_nurse(omar["id"], DIRECTOR))["active_consult_load"] == 1
    assert reassigned["escalation_count"] == 1, "returning to ASSIGNED does not reset the counter"
    assert reassigned["acuity_score"] == 20.0, "nor does it re-score the consult"
