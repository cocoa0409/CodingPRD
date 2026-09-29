"""State machine edges: initial states, guards, terminal lockdown and the loops."""

import pytest

from test_helpers import (
    ADMIN,
    BILLER,
    OFFICER,
    PROJECT_OFFICER,
    REP,
    VERIFIER,
    ApiErrorId,
    adjudicate_uds_report_payload,
    advance_clock,
    api_client,
    bill_encounter_payload,
    compute_uds_report,
    refresh_encounter,
    refresh_finding,
    refresh_health_center,
    refresh_patient,
    refresh_scope_change_request,
    refresh_service_site,
    refresh_uds_report,
    resign_board_member_payload,
    same_instant,
    setup_boot_core,
    setup_boot_pt,
    setup_draft_scope_change_request,
    setup_draft_uds_report,
    setup_encounter,
    setup_income_verification,
    setup_open_finding,
    setup_patient,
    setup_proposed_site,
    setup_quality_measure,
    submit_uds_report,
    validate_error,
    validate_success,
    verify_income_verification_payload,
    void_encounter_payload,
)


def _annex(ctx):
    return setup_proposed_site(
        ctx,
        site_name="Corner Annex Clinic",
        address_line="2 Corner Ave",
        weekly_service_hours=20,
    )


def test_a_freshly_drafted_scope_change_request_lands_in_draft_with_nothing_stamped():
    """Drafting is a paperwork act: no board involvement and no counter movement.

    PRD 3.8: "A new request has `status` `DRAFT`, `revision_round` 0,
    `held_from_status` null, `reviewed_by_user_id` null, `decision_note` null, and
    records the drafting officer in `prepared_by_user_id`."

    Design: Corner/state_machines/scope_change_request_is_created_in_the_draft_initial_state
    """
    ctx = setup_boot_core()
    annex = _annex(ctx)

    response = api_client.create_scope_change_request(
        ctx["health_center_id"],
        {
            "request_type": "ADD_SITE",
            "target_site_id": annex["id"],
            "justification": "Annex clinic opens to absorb overflow primary-care demand",
        },
        OFFICER,
    )
    request = validate_success(response, 201)

    assert request["status"] == "DRAFT"
    assert request["revision_round"] == 0
    assert request["held_from_status"] is None
    assert request["reviewed_by_user_id"] is None
    assert request["prepared_by_user_id"] == "co-1", (
        f"the drafting officer is recorded, got {request['prepared_by_user_id']}"
    )
    assert request["target_service_definition_id"] is None, (
        "an add-site request leaves the service target null"
    )
    assert refresh_service_site(annex["id"])["status"] == "PROPOSED"
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1, (
        "drafting a request moves no site into scope"
    )


def test_reinstating_a_suspended_site_re_stamps_the_moment_it_re_entered_scope():
    """The stamp is the clock at reinstatement, not the original baseline instant.

    PRD 3.1: "The same officer may reverse it, moving the site `SUSPENDED →
    IN_SCOPE`, which re-stamps `in_scope_since` with the logical clock and again
    recomputes `in_scope_site_count` and `governance_posture` with a `version`
    increment."

    Design: Corner/state_machines/service_site_reinstate_returns_a_suspended_site_to_in_scope
    """
    ctx = setup_boot_core()
    validate_success(api_client.suspend_service_site(ctx["site_id"], PROJECT_OFFICER))
    assert refresh_service_site(ctx["site_id"])["status"] == "SUSPENDED"
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 0
    advance_clock("2026-09-15T00:00:00Z")

    reinstated = validate_success(
        api_client.reinstate_service_site(ctx["site_id"], PROJECT_OFFICER)
    )

    assert reinstated["status"] == "IN_SCOPE"
    assert same_instant(reinstated["in_scope_since"]) == "2026-09-15T00:00:00Z", (
        "in_scope_since carries the clock at reinstatement, got "
        f"{reinstated['in_scope_since']}"
    )
    assert reinstated["hold_reason"] is None

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["in_scope_site_count"] == 1
    assert health_center["version"] == 7, (
        "registration, baseline site, baseline service, the seating and the adoption "
        "take the grantee to 5; the suspension and the reinstatement make 7, got "
        f"{health_center['version']}"
    )


def test_a_voided_claim_can_never_be_billed_because_void_is_terminal():
    """The bill trigger departs from two states and VOID is not one of them.

    PRD 3.7: "It sets `wraparound_status` to `NOT_APPLICABLE`, removing the encounter
    from the receivable base, then recomputes the grantee's
    `wraparound_receivable_cents` and its `governance_posture` (a voided encounter no
    longer qualifies a patient board seat) and increments the grantee's `version` by
    one. `VOID` is terminal."

    Design: Corner/state_machines/encounter_bill_after_void_rejected
    """
    ctx = setup_boot_pt()
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )
    assert encounter["patient_charge_cents"] == 2500, (
        "the nominal band charges the schedule's flat nominal fee, got "
        f"{encounter['patient_charge_cents']}"
    )
    validate_success(
        api_client.void_encounter(
            encounter["id"], void_encounter_payload("CODING_ERROR"), BILLER
        )
    )

    validate_error(
        api_client.bill_encounter(
            encounter["id"], bill_encounter_payload("CLM-VOID-1"), BILLER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    unchanged = refresh_encounter(encounter["id"])
    assert unchanged["pps_claim_status"] == "VOID"
    assert unchanged["claim_reference"] is None, (
        "the refused billing stored no claim identifier"
    )
    assert unchanged["charge_adjustment_cents"] == -2500
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0


def _accepted_annual_report():
    """A 2026 report with one measure, computed, submitted and accepted."""
    ctx = setup_boot_core()
    report = setup_draft_uds_report(ctx, reporting_year=2026)
    measure = setup_quality_measure(
        report,
        measure_code="CMS165_BP_CONTROL",
        numerator=5,
        denominator=16,
        benchmark_pct=31.3,
    )
    compute_uds_report(report)
    submit_uds_report(report)
    accepted = validate_success(
        api_client.adjudicate_uds_report(
            report["id"], adjudicate_uds_report_payload("ACCEPT"), PROJECT_OFFICER
        )
    )
    ctx.update({"report": report, "measure": measure, "accepted": accepted})
    return ctx


def test_an_accepted_annual_report_refuses_a_second_adjudication():
    """ACCEPTED is terminal, so even the other decision cannot reopen the report.

    PRD 3.9: "`ACCEPT` moves the report `SUBMITTED → ACCEPTED`, which is terminal, and
    records the officer in `adjudicated_by_user_id`. `RETURN` moves it `SUBMITTED →
    RETURNED` and stores the `return_reason`, from where recomputation reopens it as a
    draft."

    Design: Corner/state_machines/uds_report_accepted_terminal_state_rejects_further_adjudication
    """
    ctx = _accepted_annual_report()
    assert ctx["accepted"]["status"] == "ACCEPTED"

    validate_error(
        api_client.adjudicate_uds_report(
            ctx["report"]["id"],
            adjudicate_uds_report_payload(
                "RETURN", return_reason="Denominators look implausible"
            ),
            PROJECT_OFFICER,
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    final = refresh_uds_report(ctx["report"]["id"])
    assert final["status"] == "ACCEPTED"
    assert final["return_reason"] is None, (
        "the refused return stored no reason"
    )
    assert final["return_round"] == 0, (
        "the return loop can never be entered after acceptance"
    )
    assert final["adjudicated_by_user_id"] == "po-1"


def test_resigning_a_seat_twice_is_refused_and_the_first_truncation_stands():
    """Resignation is once-only, so the second call cannot move the term again.

    PRD 3.2: "The transition is `SEATED → RESIGNED`; it truncates `term_end` down to
    the `resignation_date`, thereby freeing the `seat_number` for a new term, and it
    recomputes the grantee's `seated_board_count`, `patient_seat_pct` and
    `governance_posture` with a `version` increment. `RESIGNED` is terminal."

    Design: Corner/state_machines/board_member_second_resign_rejected
    """
    ctx = setup_boot_core()
    validate_success(
        api_client.resign_board_member(
            ctx["chair_id"],
            resign_board_member_payload(resignation_date="2026-08-01T00:00:00Z"),
            OFFICER,
        )
    )
    after_first = refresh_health_center(ctx["health_center_id"])
    assert after_first["version"] == 6, (
        "one resignation takes the grantee from 5 to 6, got "
        f"{after_first['version']}"
    )

    validate_error(
        api_client.resign_board_member(
            ctx["chair_id"],
            resign_board_member_payload(resignation_date="2026-08-02T00:00:00Z"),
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    member = validate_success(api_client.get_board_member(ctx["chair_id"], OFFICER))
    assert member["status"] == "RESIGNED"
    assert same_instant(member["resignation_date"]) == "2026-08-01T00:00:00Z"
    assert same_instant(member["term_end"]) == "2026-08-01T00:00:00Z", (
        "the term stays truncated to the first resignation date, got "
        f"{member['term_end']}"
    )

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["seated_board_count"] == 0
    assert health_center["version"] == 6, (
        "the refused repeat mutated nothing, so no second increment landed"
    )


def test_a_refusal_to_document_income_can_never_be_adjudicated_as_verified():
    """The precondition is enforced before any percentage is computed.

    PRD 3.4: "Choosing `VERIFY` moves the row `SUBMITTED → VERIFIED` and does a great
    deal. It is refused outright when the verification's `documentation_type` is
    `REFUSED`: a refusal to document income can never be adjudicated as verified — it
    may only be marked insufficient — and the attempt is rejected with
    `ERR_DOCUMENTATION_REFUSED`."

    Design: Corner/state_machines/verify_on_refused_documentation_rejected
    """
    setup_boot_core()
    patient = setup_patient(mrn="MRN-C02", full_name="Ida Renn", household_size=1)
    refused = setup_income_verification(
        patient,
        declared_annual_income_cents=900000,
        household_size=1,
        documentation_type="REFUSED",
        effective_date="2026-03-01T00:00:00Z",
    )

    validate_error(
        api_client.verify_income_verification(
            refused["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        ),
        ApiErrorId.ERR_DOCUMENTATION_REFUSED.value,
        422,
    )

    unchanged = validate_success(
        api_client.get_income_verification(refused["id"], REP)
    )
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["fpg_percent"] is None, (
        "no percentage was computed on the refused branch"
    )
    assert unchanged["assigned_discount_tier_id"] is None
    assert unchanged["verified_by_user_id"] is None
    assert refresh_patient(patient["id"])["sliding_fee_status"] == "UNVERIFIED"


def test_suspending_a_site_fires_every_declared_side_effect_in_one_request():
    """The counter, the governance verdict and the version all move together.

    PRD 3.1: "A `ProjectOfficer` may take an in-scope site out of service after an
    operational visit, moving it `IN_SCOPE → SUSPENDED`; this recomputes the grantee's
    `in_scope_site_count`, recomputes `governance_posture` (because, as section 3.2
    explains, a patient board seat is only qualified by an encounter at an in-scope
    site) and increments the grantee's `version` by one."

    Design: Corner/state_machines/suspend_site_side_effects_update_counter_governance_and_version
    """
    ctx = setup_boot_core()
    before = validate_success(
        api_client.get_health_center(ctx["health_center_id"], PROJECT_OFFICER)
    )
    assert before["version"] == 5, (
        "registration, the baseline site, the baseline service, the seating and the "
        f"adoption are five mutations, got {before['version']}"
    )
    assert before["in_scope_site_count"] == 1

    suspended = validate_success(
        api_client.suspend_service_site(ctx["site_id"], PROJECT_OFFICER)
    )
    assert suspended["status"] == "SUSPENDED"

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["in_scope_site_count"] == 0
    assert health_center["in_scope_service_count"] == 1, (
        "suspending a site leaves the service listing alone"
    )
    assert health_center["version"] == 6
    assert health_center["governance_posture"] == "GOVERNANCE_DEFICIENT"
    assert health_center["operational_status"] == "ACTIVE", (
        "a suspension is not a condition on the award"
    )
    assert health_center["scope_posture"] == "OPEN"


def test_recomputing_a_returned_report_reopens_it_as_a_draft_and_counts_the_lap():
    """The return cycle is traversable: compute is also the RETURNED to DRAFT edge.

    PRD 3.9: "Computing the report runs two aggregations. It also serves as the loop
    edge `RETURNED → DRAFT`, which increments `return_round` by one; that loop is
    capped at three, and a fourth pass is rejected with `ERR_LOOP_LIMIT_EXCEEDED`. In
    every case computing stamps `computed_at` with the logical clock."

    Design: Corner/state_machines/uds_report_returned_to_draft_loop_increments_return_round
    """
    ctx = setup_boot_core()
    report = setup_draft_uds_report(ctx, reporting_year=2026)
    setup_quality_measure(
        report,
        measure_code="CMS165_BP_CONTROL",
        numerator=5,
        denominator=16,
        benchmark_pct=31.3,
    )
    compute_uds_report(report)
    submit_uds_report(report)
    validate_success(
        api_client.adjudicate_uds_report(
            report["id"],
            adjudicate_uds_report_payload(
                "RETURN", return_reason="Recheck the hypertension denominator"
            ),
            PROJECT_OFFICER,
        )
    )
    assert refresh_uds_report(report["id"])["status"] == "RETURNED"

    reopened = validate_success(api_client.compute_uds_report(report["id"], OFFICER))

    assert reopened["status"] == "DRAFT", (
        f"recomputation reopens the report as a draft, got {reopened['status']}"
    )
    assert reopened["return_round"] == 1
    assert same_instant(reopened["computed_at"]) == "2026-08-01T00:00:00Z"
    assert reopened["included_measure_count"] == 1
    assert reopened["composite_quality_rate_pct"] == pytest.approx(31.3, abs=0.01), (
        "5 of 16 is 31.25, which rounds half up to 31.3, got "
        f"{reopened['composite_quality_rate_pct']}"
    )

    resubmitted = validate_success(api_client.submit_uds_report(report["id"], OFFICER))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["return_round"] == 1, (
        "the lap counter is not advanced by a submission"
    )


def test_submitting_a_draft_request_is_refused_once_the_award_is_frozen():
    """The guard reads the parent grantee's posture, not the request's own status.

    PRD 3.8: "Submission moves the request `DRAFT → SUBMITTED`. It is permitted only
    while the grantee's `scope_posture` is `OPEN`; a frozen grantee reports
    `ERR_SCOPE_CHANGE_FROZEN`."

    Design: Corner/state_machines/scope_change_submit_while_scope_frozen_rejected
    """
    ctx = setup_boot_core()
    annex = _annex(ctx)
    request = setup_draft_scope_change_request(
        ctx,
        request_type="ADD_SITE",
        target_site_id=annex["id"],
        justification="Annex clinic opens to absorb overflow primary-care demand",
    )
    finding = setup_open_finding(
        ctx,
        requirement_code="REQ_SLIDING_FEE_16",
        severity="CONDITION",
        cap_due_days=1,
        service_site_id=ctx["site_id"],
        finding_summary="Sliding fee schedule not posted at the point of service",
    )
    advance_clock("2026-08-03T00:00:00Z")
    sweep = validate_success(api_client.run_compliance_sweep(ADMIN))
    assert sweep["escalated_finding_count"] == 1

    escalated = refresh_finding(finding["id"])
    assert escalated["status"] == "ESCALATED"
    assert same_instant(escalated["cap_due_at"]) == "2026-08-02T00:00:00Z"
    frozen = refresh_health_center(ctx["health_center_id"])
    assert frozen["open_condition_count"] == 1
    assert frozen["operational_status"] == "CONDITIONS_IMPOSED"
    assert frozen["scope_posture"] == "CHANGE_FROZEN"

    validate_error(
        api_client.submit_scope_change_request(request["id"], OFFICER),
        ApiErrorId.ERR_SCOPE_CHANGE_FROZEN.value,
        409,
    )

    still_draft = refresh_scope_change_request(request["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["held_from_status"] is None, (
        "a draft request is never parked, so no departed status was recorded"
    )
    assert refresh_service_site(annex["id"])["status"] == "PROPOSED", (
        "a draft request's target is never put on hold"
    )
