"""CASCADE-A, CASCADE-B, referral retries and the clinical write gate."""

from test_helpers import (
    ApiErrorId,
    accepted_outbound_referral,
    assert_money,
    assert_same_instant,
    assert_visit_unit_identity,
    build_battery,
    coverage_version,
    create_claim_payload,
    checked_out_loan,
    deliver_session,
    discharge,
    get_success_data,
    make_front_desk_headers,
    new_kit_item,
    new_patient,
    new_referral,
    npc_measurement_payload,
    read_authorization,
    read_kit_item,
    read_kit_loan,
    read_patient,
    read_plan,
    read_referral,
    read_session,
    request_loan,
    respond_referral,
    schedule_session,
    set_clock,
    setup_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

RED_FLAG_ROW = npc_measurement_payload(14.0, 18.0, red_flag=True)


def _red_flagged_reassessment(scn):
    return build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[RED_FLAG_ROW],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )


def _urgent_outbound_referrals(scn):
    """List the urgent outbound referrals CASCADE-A raised against this plan."""
    from test_helpers import api_client

    return api_client.list_referrals(
        scn["hdr_front"],
        {
            "plan_id": scn["plan"],
            "direction": "OUTBOUND",
            "urgency": "URGENT",
            "limit": 10,
            "offset": 0,
        },
    )


# --------------------------------------------------------------------------
# CASCADE-A, the red-flag chain
# --------------------------------------------------------------------------


def test_a_red_flagged_finalize_raises_an_urgent_referral_and_suspends_the_plan(api):
    """PRD §3.11: "Hop 1: finalizing a battery whose `red_flag_present` is true
    creates an outbound urgent referral for the same patient, in `status` `SENT`, with
    `triggering_assessment_id` naming that battery and `plan_id` copied from it. Hop
    2: the creation of an outbound urgent referral that names a plan currently in
    `status` `ACTIVE` suspends that plan, moving it `ACTIVE → SUSPENDED` with
    `suspension_reason` `RED_FLAG_REFERRAL`."
    PRD §3.2: "A third boolean, `red_flag_present`, is true when any child reading on
    the battery carries `red_flag` true."
    PRD §3.11: "`sla_due_at` is the creation instant advanced by twenty-four hours for
    an `URGENT` referral and by one hundred and twenty hours for a `ROUTINE` one."

    Design: Difficulty/transitive_cascade/red_flag_finalize_depth_five_cascade
    """
    scn = setup_active_plan()
    checked_out_loan(
        scn,
        name="Vectogram set",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=300.00,
        useful_life_months=24,
        in_service_date="2025-06-01",
        initial_qty=3,
    )
    schedule_session(scn)
    reassessment = _red_flagged_reassessment(scn)

    finalized = validate_success(
        api.finalize_assessment(reassessment["id"], scn["hdr_od1"]), 200
    )

    assert finalized["red_flag_present"] is True

    rows, meta = validate_paginated(_urgent_outbound_referrals(scn))
    assert meta["total_count"] == 1, "CASCADE-A hop 1 must create exactly one referral"
    referral = rows[0]
    assert referral["direction"] == "OUTBOUND"
    assert referral["urgency"] == "URGENT"
    assert referral["status"] == "SENT"
    assert referral["triggering_assessment_id"] == reassessment["id"]
    assert referral["plan_id"] == scn["plan"]
    assert_same_instant(referral["sla_due_at"], "2026-06-02T00:00:00Z", "Referral.sla_due_at")

    plan = read_plan(scn["plan"])
    assert plan["status"] == "SUSPENDED"
    assert plan["suspension_reason"] == "RED_FLAG_REFERRAL"


def test_the_red_flag_chain_releases_the_visit_unit_and_recalls_the_kit(api):
    """PRD §3.11: "Hop 3: the suspension cancels every session on that plan whose
    `schedule_status` is `SCHEDULED` or `CHECKED_IN` and whose `scheduled_start_at` is
    at or after the current clock reading, with `cancel_reason` `PLAN_SUSPENDED` and
    `billing_status` forced to `NON_BILLABLE`. Hop 4: each cancelled in-office session
    releases its unit back to the pool, raising `visits_released` and
    `visits_remaining` by 1 and returning an `EXHAUSTED` pool to `ACTIVE`. Hop 5:
    because that release came from a session whose plan is `SUSPENDED` for
    `RED_FLAG_REFERRAL`, every loan on that plan in `status` `CHECKED_OUT` moves to
    `RECALLED` with `recalled_at` stamped and `recall_due_at` set seven days out."
    PRD §3.9: "Stock counters do not move on recall: the unit is still out of the
    building, so it stays counted in `on_loan_qty`."

    Design: Difficulty/transitive_cascade/red_flag_finalize_depth_five_cascade
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Vectogram set",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=300.00,
        useful_life_months=24,
        in_service_date="2025-06-01",
        initial_qty=3,
    )
    session = schedule_session(scn)
    reassessment = _red_flagged_reassessment(scn)

    validate_success(api.finalize_assessment(reassessment["id"], scn["hdr_od1"]), 200)

    cancelled = read_session(session["id"])
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "PLAN_SUSPENDED"

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 1
    assert pool["visits_remaining"] == 12
    assert_visit_unit_identity(pool)

    recalled = read_kit_loan(loan["id"])
    assert recalled["status"] == "RECALLED"
    assert_same_instant(
        recalled["recall_due_at"], "2026-06-08T00:00:00Z", "KitLoan.recall_due_at"
    )

    stock = read_kit_item(item["id"])
    assert stock["on_loan_qty"] == 1
    assert stock["on_hand_qty"] == 2


# --------------------------------------------------------------------------
# CASCADE-B, the discharge chain
# --------------------------------------------------------------------------


def test_discharge_moves_the_patient_and_plan_and_cancels_the_future_session(api):
    """PRD §3.11: "On success the patient moves `ACTIVE → DISCHARGED`,
    `discharge_reason` is recorded, `discharged_at` is stamped from the clock,
    `discharged_by_user_id` records the acting `X-User-ID`, and the patient's
    `version` is bumped."
    PRD §3.11: "Hop 1: every therapy plan of this patient whose `status` is `DRAFT`,
    `ACTIVE`, `SUSPENDED` or `UNDER_REVISION` moves to `DISCHARGED`. Hop 2: on each of
    those plans, every session whose `schedule_status` is `SCHEDULED` or `CHECKED_IN`
    is cancelled with `cancel_reason` `PLAN_DISCHARGED` and `billing_status` forced to
    `NON_BILLABLE` — note that this hop, unlike hop 3 of the red-flag chain, does not
    filter on whether the appointment lies in the future."
    PRD §3.11: "`TRANSFERRED` requires at least one referral for this patient with
    `direction` `OUTBOUND` and `status` `ACCEPTED`."

    Design: Difficulty/transitive_cascade/discharge_cascade_plan_session_units_authorization
    """
    scn = setup_active_plan()
    session = schedule_session(scn)
    accepted_outbound_referral(scn)

    discharged = validate_success(
        api.discharge_patient(scn["pt"], {"discharge_reason": "TRANSFERRED"}, scn["hdr_od1"]),
        200,
    )

    assert discharged["clinical_status"] == "DISCHARGED"
    assert discharged["discharge_reason"] == "TRANSFERRED"
    assert discharged["discharged_at"] is not None

    assert read_plan(scn["plan"])["status"] == "DISCHARGED"
    cancelled = read_session(session["id"])
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "PLAN_DISCHARGED"


def test_discharge_releases_the_visit_unit_and_closes_the_pool(api):
    """PRD §3.11: "Hop 3: each cancelled in-office session releases its unit back to
    its pool, raising `visits_released` and `visits_remaining` by 1 and returning an
    `EXHAUSTED` pool to `ACTIVE`."
    PRD §3.11: "Hop 5: the authorization each discharged plan was bound to, reached
    through that plan's `authorization_id`, moves to `CLOSED` with `close_reason`
    `PATIENT_DISCHARGED`, its four counters left untouched so the visit-unit identity
    still holds; a plan that never left `DRAFT` has a null `authorization_id` and so
    closes nothing, and an authorization no discharged plan references is not reached
    by this path."

    Design: Difficulty/transitive_cascade/discharge_cascade_plan_session_units_authorization
    """
    scn = setup_active_plan()
    schedule_session(scn)
    accepted_outbound_referral(scn)

    discharge(scn, "TRANSFERRED")

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 1
    assert pool["visits_remaining"] == 12
    assert pool["status"] == "CLOSED"
    assert pool["close_reason"] == "PATIENT_DISCHARGED"
    assert_visit_unit_identity(pool)


def test_a_second_discharge_is_an_illegal_transition_not_a_write_gate_refusal(api):
    """PRD §2.8: "Discharge itself being outside the gate is load-bearing. A second
    discharge attempt on an already-discharged patient is refused by rung 14 as an
    illegal transition, reporting `ERR_INVALID_STATE`, and not by rung 12."
    PRD §3.11: "Only an optometrist discharges a patient, and only a patient in
    `clinical_status` `ACTIVE` — attempting to discharge a patient still in `INTAKE`,
    or one already `DISCHARGED`, is refused with `ERR_INVALID_STATE`, because
    discharge sits outside the write gate and so never reports
    `ERR_PATIENT_DISCHARGED` against itself."

    Design: Corner/state_machines/second_discharge_returns_invalid_state_not_the_write_gate
    """
    scn = setup_active_plan()
    accepted_outbound_referral(scn)
    discharge(scn, "TRANSFERRED")

    response = api.discharge_patient(
        scn["pt"], {"discharge_reason": "GOALS_MET"}, scn["hdr_od1"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_patient(scn["pt"])["discharge_reason"] == "TRANSFERRED"


# --------------------------------------------------------------------------
# Referral traffic
# --------------------------------------------------------------------------


def test_the_re_referral_cap_writes_abandoned_and_then_refuses(api):
    """PRD §3.11: "While `attempt_count` is still below 3, the referral moves
    `DECLINED → SENT`, `attempt_count` increments by 1, `target_provider_name` is
    rewritten, `responded_at`, `response_outcome` and `decline_reason` are all cleared
    back to null, `sla_due_at` is re-stamped as the current clock instant advanced by
    the urgency's SLA hours, and the `version` is bumped — the capped retry loop
    `SENT → DECLINED → SENT`."
    PRD §3.11: "Once `attempt_count` has reached 3, the loop closes differently: the
    referral is written to `ABANDONED` and its `version` bumped, and *then* the call
    fails with `ERR_REFERRAL_ATTEMPT_LIMIT`."
    PRD §3.11: "Every referral opens in `status` `SENT` with `attempt_count` 1,
    `responded_at`, `response_outcome` and `decline_reason` null, and `sla_breached`
    false."

    Design: Corner/state_machines/referral_re_refer_cap_writes_abandoned_then_rejects
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient()
    headers = make_front_desk_headers()

    referral = validate_success(
        api.create_referral(
            {
                "patient_id": patient["id"],
                "direction": "INBOUND",
                "urgency": "ROUTINE",
                "referring_provider_name": "Dr Amara Family Eyecare",
                "target_provider_name": "Vision Therapy Clinic",
                "reason": "Convergence insufficiency workup",
            },
            headers,
        ),
        201,
    )
    assert referral["attempt_count"] == 1
    assert_same_instant(
        referral["sla_due_at"], "2026-06-06T00:00:00Z", "Referral.sla_due_at"
    )

    for attempt, (decline, target) in enumerate(
        [("No capacity", "Northside Vision Therapy"), ("Out of network", "Lakeside Optometry")],
        start=2,
    ):
        get_success_data(
            api.respond_referral(
                referral["id"],
                {"response_outcome": "DECLINED", "decline_reason": decline},
                headers,
            )
        )
        again = get_success_data(
            api.re_refer(referral["id"], {"target_provider_name": target}, headers)
        )
        assert again["attempt_count"] == attempt

    get_success_data(
        api.respond_referral(
            referral["id"],
            {"response_outcome": "DECLINED", "decline_reason": "Waitlist closed"},
            headers,
        )
    )

    response = api.re_refer(
        referral["id"], {"target_provider_name": "Harbour Eye Institute"}, headers
    )

    validate_error(response, ApiErrorId.ERR_REFERRAL_ATTEMPT_LIMIT.value, 409)
    stored = validate_success(api.get_referral(referral["id"], headers), 200)
    assert stored["status"] == "ABANDONED", "The ABANDONED write is committed before the refusal"
    assert stored["attempt_count"] == 3


def test_a_red_flag_suspension_cannot_be_resumed_while_the_referral_is_open(api):
    """PRD §3.4: "Resuming reverses it, moving `SUSPENDED → ACTIVE` and clearing
    `suspension_reason` to null, but a plan suspended for `RED_FLAG_REFERRAL` may not
    be resumed until every referral on that plan with `direction` `OUTBOUND` and
    `urgency` `URGENT` has reached `ACCEPTED` or `ABANDONED`; while any of them is
    still `SENT` or `DECLINED`, the resume is refused with `ERR_INVALID_STATE`."
    PRD §3.11: "Recording the answer is reception's or an optometrist's operation and
    sits outside the discharge write gate, so an outbound referral can still be
    answered after the patient has been discharged."

    Design: Corner/state_machines/plan_resume_blocked_while_the_urgent_referral_is_still_open
    """
    scn = setup_active_plan()
    reassessment = _red_flagged_reassessment(scn)
    validate_success(api.finalize_assessment(reassessment["id"], scn["hdr_od1"]), 200)
    rows, _meta = validate_paginated(_urgent_outbound_referrals(scn))
    referral_id = rows[0]["id"]

    blocked = api.resume_plan(scn["plan"], scn["hdr_od1"])
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value, 409)

    respond_referral(scn, referral_id, "ACCEPTED")

    resumed = validate_success(api.resume_plan(scn["plan"], scn["hdr_od1"]), 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["suspension_reason"] is None


# --------------------------------------------------------------------------
# The clinical write gate
# --------------------------------------------------------------------------


def test_the_write_gate_pre_empts_every_business_rung_below_it(api):
    """PRD §2.8: "Once a patient reaches `clinical_status` `DISCHARGED`, the clinical
    record freezes. Any request in the **clinical write family** that touches that
    patient — whether the patient is named in the path, named in the body, or reached
    indirectly through a plan, phase, session, assessment, loan, referral or
    prescription that belongs to them — is refused with `ERR_PATIENT_DISCHARGED`
    (HTTP 409) at rung 12, before any business rule below it is evaluated."
    PRD §2.7: "First, rung 12 sits above every business rung, so on a discharged
    patient a gated endpoint reports `ERR_PATIENT_DISCHARGED` and never the business
    failure underneath it — which is exactly why the exclusion list in §2.8 matters."

    Design: Corner/validations/clinical_write_gate_pre_empts_lower_rungs_after_discharge
    """
    scn = setup_active_plan()
    accepted_outbound_referral(scn)
    discharge(scn, "TRANSFERRED")

    booking = api.create_session(
        scn["plan"],
        {
            "therapist_id": scn["cvt1"],
            "room_id": scn["room_a"],
            "scheduled_start_at": "2026-06-20T09:00:00Z",
            "scheduled_end_at": "2026-06-20T10:00:00Z",
            "procedure_code": "TIMED_THERAPEUTIC_ACTIVITY",
            "expected_authorization_version": scn["auth_v1"],
        },
        scn["hdr_front"],
    )
    validate_error(booking, ApiErrorId.ERR_PATIENT_DISCHARGED.value, 409)

    battery = api.create_assessment(
        {
            "patient_id": scn["pt"],
            "assessment_type": "REASSESSMENT",
            "purpose": "PROGRESS",
            "encounter_date": "2026-06-20",
            "performed_by_therapist_id": scn["od1"],
            "plan_id": scn["plan"],
        },
        scn["hdr_od1"],
    )
    validate_error(battery, ApiErrorId.ERR_PATIENT_DISCHARGED.value, 409)

    home = api.create_home_session(
        scn["plan"],
        {"performed_at": "2026-06-20T18:00:00Z", "timed_minutes": 20},
        scn["hdr_patient"],
    )
    validate_error(home, ApiErrorId.ERR_PATIENT_DISCHARGED.value, 409)


def test_the_endpoints_outside_the_gate_still_work_after_discharge(api):
    """PRD §2.8: "These sixteen write endpoints sit **outside** the gate and operate
    normally on a discharged patient:"
    PRD §3.9: "The same operation applied to a loan still in `status` `REQUESTED` is a
    withdrawal rather than a return: the loan moves `REQUESTED → CANCELLED` with
    `returned_at` stamped, and no stock counter moves, because nothing ever left the
    shelf."
    PRD §3.11: "A referral in `status` `SENT` moves to `ACCEPTED` or to `DECLINED`
    accordingly, `responded_at` is stamped from the clock, `sla_breached` is
    recomputed, and the referral's `version` is bumped."
    PRD §3.10: "Claims are the billing specialist's exclusive territory, and every
    claim endpoint sits outside the discharge write gate so the revenue cycle can be
    worked to completion long after a patient has left."

    Design: Corner/validations/endpoints_outside_the_write_gate_still_work_after_discharge
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    item = new_kit_item(
        name="Anaglyph glasses",
        item_class="CONSUMABLE_STOCK",
        replacement_cost=4.00,
        useful_life_months=12,
        in_service_date="2026-01-01",
        initial_qty=5,
    )
    loan = request_loan(scn, item["id"], quantity=2)
    accepted_outbound_referral(scn)
    unanswered = new_referral(
        scn,
        plan_id=scn["plan"],
        target_provider_name="Lakeside Low Vision",
        reason="Low vision aids",
    )
    discharge(scn, "TRANSFERRED")

    withdrawn = validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "GOOD"}, scn["hdr_front"]), 200
    )
    assert withdrawn["status"] == "CANCELLED"

    answered = validate_success(
        api.respond_referral(
            unanswered["id"],
            {"response_outcome": "DECLINED", "decline_reason": "Patient transferred"},
            scn["hdr_front"],
        ),
        200,
    )
    assert answered["status"] == "DECLINED"

    claim = validate_success(
        api.create_claim(
            create_claim_payload(
                scn["pt"],
                scn["cov_med"],
                "THERAPY_SESSION",
                "2026-06-10",
                coverage_version(scn["cov_med"]),
                session_id=session["id"],
            ),
            scn["hdr_biller"],
        ),
        201,
    )
    assert claim["status"] == "DRAFT"
    assert_money(claim["billed_amount"], 126.00, "billed_amount")
    assert read_patient(scn["pt"])["clinical_status"] == "DISCHARGED"


def test_the_outstanding_loan_rung_pre_empts_the_discharge_criteria_rung(api):
    """PRD §3.11: "Before anything else, the patient's equipment must be back: if any
    loan for this patient is in `status` `CHECKED_OUT` or `RECALLED`, the discharge is
    refused with `ERR_LOAN_OUTSTANDING`."
    PRD §3.11: "`GOALS_MET` requires that plan's `discharge_ready` to be true."
    PRD §3.11: "A reason whose precondition does not hold is refused with
    `ERR_DISCHARGE_CRITERIA_NOT_MET`."
    PRD §3.9: "A `GOOD` return therefore always yields a fee of exactly `0.00`, and a
    fully depreciated item still bills a fifth of its replacement cost when it is
    lost."

    Design: Corner/validations/outstanding_loan_rung_pre_empts_the_discharge_criteria_rung
    """
    scn = setup_active_plan()
    _item, loan = checked_out_loan(
        scn,
        name="Vectogram set",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=275.00,
        useful_life_months=24,
        in_service_date="2025-11-01",
        initial_qty=2,
    )
    assert loan["status"] == "CHECKED_OUT"

    blocked = api.discharge_patient(
        scn["pt"], {"discharge_reason": "GOALS_MET"}, scn["hdr_od1"]
    )
    validate_error(blocked, ApiErrorId.ERR_LOAN_OUTSTANDING.value, 409)

    returned = validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "GOOD"}, scn["hdr_front"]), 200
    )
    assert_money(returned["damage_fee_amount"], 0.00, "damage_fee_amount")

    criteria = api.discharge_patient(
        scn["pt"], {"discharge_reason": "GOALS_MET"}, scn["hdr_od1"]
    )
    validate_error(criteria, ApiErrorId.ERR_DISCHARGE_CRITERIA_NOT_MET.value, 422)
    assert read_patient(scn["pt"])["clinical_status"] == "ACTIVE"


def test_cascade_effects_are_readable_the_instant_the_mutation_returns(api):
    """PRD §3.4: "Suspension is never a quiet flag: as CASCADE-A hop 3, every session
    on the plan whose `schedule_status` is `SCHEDULED` or `CHECKED_IN` and whose
    `scheduled_start_at` is at or after the current clock reading is cancelled with
    `cancel_reason` `PLAN_SUSPENDED`, and each cancelled in-office session releases
    its authorization unit as described in §3.5."
    PRD §2.11: "Every row a cascade writes has its `version` incremented and its
    `updated_at` refreshed exactly as if the change had been made by a direct call."
    PRD §2.10: "Four named identities must hold at every instant an API caller can
    observe, on every row in scope, and not merely at the end of some batch."

    Design: Corner/consistency_model/cascade_effects_are_visible_immediately_after_the_mutation
    """
    scn = setup_active_plan()
    session = schedule_session(scn)

    suspended = validate_success(
        api.suspend_plan(scn["plan"], {"suspension_reason": "CLINICIAN_HOLD"}, scn["hdr_od1"]),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "CLINICIAN_HOLD"

    cancelled = validate_success(api.get_session(session["id"], scn["hdr_front"]), 200)
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "PLAN_SUSPENDED"

    pool = validate_success(api.get_authorization(scn["auth"], scn["hdr_biller"]), 200)
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 1
    assert pool["visits_remaining"] == 12
    assert_visit_unit_identity(pool)
