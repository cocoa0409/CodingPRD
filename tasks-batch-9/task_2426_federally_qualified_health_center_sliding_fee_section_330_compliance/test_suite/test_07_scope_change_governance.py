"""Change-in-scope governance: the revision cycle, seating, staleness, and removal."""

import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    OFFICER,
    api_client,
    begin_review_scope_change_request,
    create_poverty_guideline_payload,
    decide_scope_change_request_payload,
    lock_scope_baseline,
    make_board_chair_headers,
    refresh_encounter,
    refresh_fee_schedule,
    refresh_health_center,
    refresh_patient,
    refresh_scope_change_request,
    refresh_service_site,
    setup_board_seat,
    setup_boot_fs,
    setup_boot_gov,
    setup_draft_scope_change_request,
    setup_grantee,
    setup_proposed_site,
    setup_wraparound_claimed_encounter,
    submit_scope_change_request,
    validate_error,
    validate_success,
)


def _decide(request_id, decision, chair_id, decision_note=None):
    payload = decide_scope_change_request_payload(decision)
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return api_client.decide_scope_change_request(
        request_id, payload, make_board_chair_headers(chair_id)
    )


def _governance_summary(health_center_id):
    return validate_success(api_client.get_governance_summary(health_center_id, OFFICER))


def _add_site_request_submitted(ctx):
    """A locked baseline, a PROPOSED annex, and an ADD_SITE request awaiting review."""
    lock_scope_baseline(ctx)
    annex = setup_proposed_site(
        ctx, site_name="Eastside Annex", address_line="88 East Ave", weekly_service_hours=20
    )
    request = setup_draft_scope_change_request(
        ctx, request_type="ADD_SITE", target_site_id=annex["id"]
    )
    submit_scope_change_request(request, OFFICER)
    ctx.update({"annex": annex, "annex_id": annex["id"], "request": request})
    return ctx


def _request_walked_around_the_revision_cycle(ctx, laps):
    """Walk the review cycle, returning the revision_round seen after each resubmission."""
    rounds = []
    for lap in range(laps):
        begin_review_scope_change_request(ctx["request"], ctx["chair_id"])
        validate_success(
            _decide(
                ctx["request"]["id"],
                "REQUEST_REVISION",
                ctx["chair_id"],
                f"round {lap + 1}: attach the site lease",
            )
        )
        if lap + 1 < laps:
            resubmitted = validate_success(
                api_client.submit_scope_change_request(ctx["request"]["id"], OFFICER)
            )
            rounds.append(resubmitted["revision_round"])
    return rounds


def test_the_revision_round_counts_only_the_loop_edge_and_a_fourth_pass_is_refused():
    """Three laps take the counter to three; the fourth resubmission hits the cap.

    PRD 3.8: "The same operation is also the loop edge `REVISION_REQUESTED →
    SUBMITTED`, which increments `revision_round` by one, clears
    `reviewed_by_user_id`, and likewise requires an open scope posture. The loop is
    capped: resubmission is permitted only while `revision_round` is below 3, and a
    fourth pass is rejected with `ERR_LOOP_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/scope_change_request_revision_cycle_capped_at_three_rounds
    """
    ctx = _add_site_request_submitted(setup_boot_fs())
    assert ctx["request"]["revision_round"] == 0, (
        "the DRAFT to SUBMITTED edge does not increment the revision counter"
    )

    rounds = _request_walked_around_the_revision_cycle(ctx, 4)
    assert rounds == [1, 2, 3], (
        f"the loop edge increments once per pass, got {rounds}"
    )

    validate_error(
        api_client.submit_scope_change_request(ctx["request"]["id"], OFFICER),
        ApiErrorId.ERR_LOOP_LIMIT_EXCEEDED.value,
    )

    parked = refresh_scope_change_request(ctx["request"]["id"])
    assert parked["status"] == "REVISION_REQUESTED"
    assert parked["revision_round"] == 3


def test_from_revision_requested_the_begin_review_edge_does_not_exist_at_all():
    """The same state answers two different errors depending on the edge attempted.

    PRD 3.8: "A `BoardChair` holding a seated seat on that grantee's board then
    takes the request under review, moving it `SUBMITTED → UNDER_REVIEW` and
    recording the chair's identifier in `reviewed_by_user_id`." PRD 2.12 fixes the
    precedence: "because the state check at rung 11 sits above every safety and
    fiscal rule, an action aimed at a row in the wrong state always reports
    `ERR_INVALID_STATE_TRANSITION`, even when a later rule would also have rejected
    it."

    Design: Difficulty/non_linear_state_machine/scope_change_request_revision_cycle_capped_at_three_rounds
    """
    ctx = _add_site_request_submitted(setup_boot_fs())
    _request_walked_around_the_revision_cycle(ctx, 4)

    validate_error(
        api_client.begin_review_scope_change_request(
            ctx["request"]["id"], make_board_chair_headers(ctx["chair_id"])
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    parked = refresh_scope_change_request(ctx["request"]["id"])
    assert parked["status"] == "REVISION_REQUESTED"
    assert parked["revision_round"] == 3
    assert parked["reviewed_by_user_id"] == ctx["chair_id"], (
        "the last review recorded the chair and the revision decision mutated "
        "nothing else"
    )
    assert refresh_service_site(ctx["annex_id"])["status"] == "PROPOSED", (
        "the target site never left the proposal state"
    )
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1


def _northgate_with_its_own_seated_chair():
    """A second grantee whose board seat is legitimately SEATED."""
    health_center = setup_grantee(
        legal_name="Northgate Health",
        grant_number="H80CS00430",
        pps_base_rate_cents=17000,
        medicare_upper_limit_cents=15000,
    )
    chair = setup_board_seat(
        health_center["id"], expertise_category="HEALTH_PROFESSION"
    )
    return health_center, chair


def test_a_seated_chair_of_another_grantee_cannot_take_the_request_under_review():
    """Seating is looked up per grantee, so a legitimate foreign chair is refused.

    PRD 2.2: "Any board-business operation on a grantee therefore compares the
    acting `X-User-ID` against the `BoardMember` rows of that grantee: the acting
    chair must be a `BoardMember` whose `health_center_id` is the grantee in question
    and whose `status` is `SEATED`. A chair that holds no seated seat on that
    grantee's board is rejected with `ERR_NOT_SEATED_BOARD_MEMBER` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/scope_review_depends_on_board_member_seating_at_the_same_grantee
    """
    ctx = _add_site_request_submitted(setup_boot_fs())
    _northgate, foreign_chair = _northgate_with_its_own_seated_chair()
    assert foreign_chair["status"] == "SEATED", (
        "the foreign chair is a legitimate seated board member of its own grantee"
    )

    validate_error(
        api_client.begin_review_scope_change_request(
            ctx["request"]["id"], make_board_chair_headers(foreign_chair["id"])
        ),
        ApiErrorId.ERR_NOT_SEATED_BOARD_MEMBER.value,
    )

    untouched = refresh_scope_change_request(ctx["request"]["id"])
    assert untouched["status"] == "SUBMITTED", (
        f"the refused review left the request where it was, got {untouched['status']}"
    )
    assert untouched["reviewed_by_user_id"] is None


def test_the_grantees_own_chair_takes_the_identical_request_under_review():
    """The identical call succeeds for a chair seated at the request's own grantee.

    PRD 3.8: "A `BoardChair` holding a seated seat on that grantee's board then
    takes the request under review, moving it `SUBMITTED → UNDER_REVIEW` and
    recording the chair's identifier in `reviewed_by_user_id`. This too requires an
    open scope posture."

    Design: Difficulty/cross_entity_state_dependency/scope_review_depends_on_board_member_seating_at_the_same_grantee
    """
    ctx = _add_site_request_submitted(setup_boot_fs())
    _northgate_with_its_own_seated_chair()

    reviewed = validate_success(
        api_client.begin_review_scope_change_request(
            ctx["request"]["id"], make_board_chair_headers(ctx["chair_id"])
        )
    )

    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == ctx["chair_id"], (
        "the reviewer recorded is the identifier of the acting board member"
    )
    assert refresh_service_site(ctx["annex_id"])["status"] == "PROPOSED", (
        "taking a request under review does not move its target"
    )


def _add_site_under_review_then_a_newer_guideline_year(publish=True):
    """A compliant board, a request under review, and a freshly published 2027 table."""
    ctx = _add_site_request_submitted(setup_boot_gov())
    begin_review_scope_change_request(ctx["request"], ctx["chair_id"])
    ctx["review_status_before"] = refresh_fee_schedule(ctx["fee_schedule_id"])[
        "review_status"
    ]
    if publish:
        validate_success(
            api_client.create_poverty_guideline(
                create_poverty_guideline_payload(
                    guideline_year=2027,
                    base_amount_cents=1680000,
                    increment_cents=590000,
                ),
                ADMIN,
            ),
            201,
        )
    return ctx


def test_publishing_a_newer_guideline_year_makes_the_schedule_stale_and_blocks_approval():
    """A write to a third entity turns the approval gate against the request.

    PRD 3.3: "If the schedule's `fpg_year` is less than the latest published
    guideline year, `review_status` is `OUT_OF_DATE`." PRD 3.8 states the gate: "And
    the grantee's adopted fee schedule covering the logical clock must have a
    `review_status` other than `OUT_OF_DATE` — scope may not expand while the
    sliding fee schedule lags the current federal poverty guidelines — or the
    decision reports `ERR_FEE_SCHEDULE_OUT_OF_DATE`."

    Design: Difficulty/cross_entity_state_dependency/scope_approval_depends_on_fee_schedule_review_status
    """
    ctx = _add_site_under_review_then_a_newer_guideline_year()
    assert ctx["review_status_before"] == "CURRENT"
    assert refresh_fee_schedule(ctx["fee_schedule_id"])["review_status"] == "OUT_OF_DATE", (
        "guideline staleness dominates elapsed time, and nothing was written to the "
        "schedule itself"
    )

    validate_error(
        _decide(ctx["request"]["id"], "APPROVE", ctx["chair_id"], "annex approved"),
        ApiErrorId.ERR_FEE_SCHEDULE_OUT_OF_DATE.value,
    )


def test_the_stale_schedule_rule_answers_ahead_of_a_governance_check_that_would_pass():
    """The board is compliant, so the schedule rule is unambiguously the one that fires.

    PRD 3.8: "The grantee's `governance_posture` must be `GOVERNANCE_COMPLIANT` when
    evaluated on the pre-transition snapshot described in section 3.2, or the
    decision reports `ERR_GOVERNANCE_DEFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/scope_approval_depends_on_fee_schedule_review_status
    """
    ctx = _add_site_under_review_then_a_newer_guideline_year()
    summary = _governance_summary(ctx["health_center_id"])
    assert summary["patient_seat_pct"] == pytest.approx(66.67, abs=0.01)
    assert summary["governance_posture"] == "GOVERNANCE_COMPLIANT", (
        "the governance gate would have passed, so it cannot be the reported rule"
    )

    response = _decide(
        ctx["request"]["id"], "APPROVE", ctx["chair_id"], "annex approved"
    )
    validate_error(response, ApiErrorId.ERR_FEE_SCHEDULE_OUT_OF_DATE.value)

    unchanged = refresh_scope_change_request(ctx["request"]["id"])
    assert unchanged["status"] == "UNDER_REVIEW", (
        f"the refused approval leaves the request under review, got {unchanged['status']}"
    )
    assert refresh_service_site(ctx["annex_id"])["status"] == "PROPOSED"
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1


def _remove_site_request_under_review():
    """Three encounters at the only in-scope site, one of them paid, and a removal request."""
    ctx = setup_boot_gov()
    managed_care = setup_wraparound_claimed_encounter(
        ctx,
        ctx["patient_one"]["id"],
        payer_type="MEDICAID_MCO",
        gross_charge_cents=30000,
        claim_reference="CLM-5001",
        mco_paid_cents=14000,
        encounter_date="2026-03-05T00:00:00Z",
    )
    summary_before = _governance_summary(ctx["health_center_id"])
    request = setup_draft_scope_change_request(
        ctx,
        request_type="REMOVE_SITE",
        target_site_id=ctx["site_id"],
        justification="lease terminated",
    )
    submit_scope_change_request(request, OFFICER)
    begin_review_scope_change_request(request, ctx["chair_id"])
    ctx.update(
        {
            "managed_care_encounter": managed_care,
            "summary_before": summary_before,
            "request": request,
        }
    )
    return ctx


def test_removing_a_site_voids_only_its_unbilled_encounters():
    """Hops one through three: the site leaves scope and unbilled visits are compensated.

    PRD 3.8: "The third hop applies to `REMOVE_SITE` only: because a site left
    scope, every encounter at that site whose `pps_claim_status` is `UNBILLED` is
    voided — `pps_claim_status` becomes `VOID`, `void_reason` becomes
    `SITE_OUT_OF_SCOPE`, and `charge_adjustment_cents` becomes the negative of that
    encounter's `patient_charge_cents`."

    Design: Difficulty/transitive_cascade/remove_site_approval_cascades_into_void_and_patient_ledger_depth_five
    """
    ctx = _remove_site_request_under_review()
    assert ctx["verification_two"]["fpg_percent"] == pytest.approx(99.91, abs=0.01)
    assert ctx["verification_two"]["assigned_tier_label"] == "NOMINAL_FULL"
    assert ctx["encounter_two"]["patient_charge_cents"] == 2500, (
        "the nominal band charges the schedule's nominal fee, not a percentage of "
        f"20000, got {ctx['encounter_two']['patient_charge_cents']}"
    )
    assert ctx["managed_care_encounter"]["patient_charge_cents"] == 2500
    assert ctx["managed_care_encounter"]["wraparound_due_cents"] == 1500

    approved = validate_success(
        _decide(
            ctx["request"]["id"], "APPROVE", ctx["chair_id"], "site closure approved"
        )
    )
    assert approved["status"] == "APPROVED"

    assert refresh_service_site(ctx["site_id"])["status"] == "REMOVED"
    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["in_scope_site_count"] == 0
    assert health_center["in_scope_service_count"] == 1, (
        "removing a site does not touch the service listing"
    )

    for key in ("encounter_one", "encounter_two"):
        voided = refresh_encounter(ctx[key]["id"])
        assert voided["pps_claim_status"] == "VOID"
        assert voided["void_reason"] == "SITE_OUT_OF_SCOPE"
        assert voided["charge_adjustment_cents"] == -2500, (
            "the adjustment is the negative of the encounter's patient charge, got "
            f"{voided['charge_adjustment_cents']}"
        )

    survivor = refresh_encounter(ctx["managed_care_encounter"]["id"])
    assert survivor["pps_claim_status"] == "PAID", (
        "only unbilled encounters are voided by the removal cascade"
    )


def test_the_removal_restores_both_ledgers_and_then_recomputes_governance():
    """Hops four and five, then the post-transition governance recompute.

    PRD 3.8: "The fourth hop follows from the third: because those encounters were
    voided, each affected patient's `patient_balance_cents` is reduced by the voided
    encounter's `patient_charge_cents` less its `waived_amount_cents`, restoring the
    ledger invariant of section 2.8." PRD 3.8 continues: "As the last side effect of
    the whole transition, the grantee's `governance_posture` is recomputed on the
    *post*-transition site statuses."

    Design: Difficulty/transitive_cascade/remove_site_approval_cascades_into_void_and_patient_ledger_depth_five
    """
    ctx = _remove_site_request_under_review()
    assert ctx["summary_before"]["patient_seat_pct"] == pytest.approx(66.67, abs=0.01)
    assert ctx["summary_before"]["governance_posture"] == "GOVERNANCE_COMPLIANT"
    assert refresh_patient(ctx["patient_one"]["id"])["patient_balance_cents"] == 5000
    assert (
        refresh_health_center(ctx["health_center_id"])["wraparound_receivable_cents"]
        == 1500
    )

    validate_success(
        _decide(
            ctx["request"]["id"], "APPROVE", ctx["chair_id"], "site closure approved"
        )
    )

    assert refresh_patient(ctx["patient_one"]["id"])["patient_balance_cents"] == 2500, (
        "the voided self-pay visit comes off the ledger while the paid managed-care "
        "visit survives"
    )
    assert refresh_patient(ctx["patient_two"]["id"])["patient_balance_cents"] == 0

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["wraparound_receivable_cents"] == 1500, (
        "the receivable is recomputed from the surviving encounters, not decremented"
    )
    assert health_center["governance_posture"] == "GOVERNANCE_DEFICIENT", (
        "no site is in scope any more, so no patient seat is qualified"
    )
    assert health_center["patient_seat_pct"] == pytest.approx(0.00, abs=0.01)

    for seat in ctx["patient_seats"]:
        reloaded = validate_success(api_client.get_board_member(seat["id"], OFFICER))
        assert reloaded["patient_seat_qualified"] is False, (
            "an encounter at a removed site stops qualifying a patient seat"
        )
