"""Discharge cascade, stay pricing, quality penalties and consolidation."""

from test_helpers import (
    OFFICER_HEADERS,
    admit,
    api_client,
    assert_admission_dimensions,
    assert_facility_cohort,
    assert_payment,
    assert_week_counters,
    create_concurred_screening,
    create_draft_screening,
    deliver_session,
    discharge,
    finalize_qrp_assessment,
    open_admission,
    open_and_compute_review,
    open_qrp_assessment,
    open_therapy_week,
    read_admission,
    read_compliance_review,
    read_facility,
    read_qrp_assessment,
    read_screening,
    read_therapy_week,
    register_patient,
    rescind_interruption_payload,
    schedule_session,
    set_clock,
    setup_admitted_cohort,
    setup_facility_with_staff,
    setup_interruption_chain,
    setup_stay,
    sign_plan_of_care,
    submit_screening,
    validate_success,
)

PATIENT_A = {"comorbidity_tier": "TIER_2"}
PATIENT_B = {
    "full_name": "Bo Whitaker",
    "impairment_group_code": "0950",
    "etiologic_diagnosis_code": "M17.11",
}


def test_discharge_moves_the_stay_and_payment_dimensions_only():
    """Discharge closes the stay and prices it, leaving documentation as it was.

    PRD §3.8: "The stay's `stay_status` moves from `ADMITTED` to the terminal
    `DISCHARGED`; `documentation_status` is deliberately untouched, since a
    discharged stay may still be documentarily incomplete."

    Design: Difficulty/non_linear_state_machine/admission_parallel_dimensions_advance_independently
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(
        env, patient_overrides=PATIENT_A,
        plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                        "disciplines": ["PT", "OT"]},
    )

    discharged = discharge(env, stay["admission"]["id"], "2026-08-18T12:00:00Z")

    assert_admission_dimensions(discharged, stay_status="DISCHARGED",
                                payment_status="PRICED",
                                documentation_status="POC_SIGNED")
    plan = validate_success(
        api_client.get_plan_of_care(stay["plan"]["id"], OFFICER_HEADERS)
    )
    assert plan["status"] == "ACTIVE"


def test_priced_stay_with_no_therapy_weeks_is_non_qualifying():
    """A fifteen-day TIER_B stay with a 6 percent uplift prices at 2597000 cents.

    PRD §3.8: "The uplifted base is the tier base multiplied by one plus that
    uplift fraction, rounded half up to whole cents *at this step*."

    Design: Difficulty/non_linear_state_machine/admission_parallel_dimensions_advance_independently
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(
        env, patient_overrides=PATIENT_A,
        plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                        "disciplines": ["PT", "OT"]},
    )

    discharged = discharge(env, stay["admission"]["id"], "2026-08-18T12:00:00Z")

    assert_payment(discharged, effective_los_days=15,
                   total_payment_cents=2597000, payment_status="PRICED")
    assert discharged["screening_compliant"] is True
    assert discharged["poc_signed_within_deadline"] is True
    assert discharged["therapy_weeks_satisfied"] is False
    assert_admission_dimensions(discharged, compliance_class="NON_QUALIFYING")


def test_discharge_evaluates_the_open_week_and_settles_the_stay_verdict():
    """The first cascade hop closes the open week, which fails the daily rule.

    PRD §3.8: "The first hop closes out therapy measurement: every therapy week
    of this admission still in `OPEN` is evaluated exactly as §3.6 describes,
    under its own pinned `evaluation_mode`, and becomes either `MET` or
    `NOT_MET`."

    Design: Difficulty/transitive_cascade/discharge_cascade_freezes_facility_and_holds_screenings
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stays = setup_admitted_cohort(env, [
        {"mrn": "MRN-A", "patient_overrides": PATIENT_A},
        {"mrn": "MRN-B", "patient_overrides": PATIENT_B},
    ])
    admission_a = stays[0]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    week_a = open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    session = schedule_session(env, admission_a,
                               "2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z")
    deliver_session(env, session["id"])
    discharge(env, stays[1]["admission"]["id"], "2026-08-10T12:00:00Z")
    set_clock("2026-08-17T09:00:00Z")

    discharged_a = discharge(env, admission_a, "2026-08-18T12:00:00Z")

    assert_week_counters(read_therapy_week(week_a["id"]),
                         delivered_credited_minutes=180,
                         qualifying_days_count=1, status="NOT_MET")
    assert discharged_a["therapy_weeks_satisfied"] is False
    assert_admission_dimensions(discharged_a, compliance_class="NON_QUALIFYING")


def test_discharge_freezes_the_facility_and_holds_submitted_screenings():
    """The cascade reaches the posture and puts pending screenings ON_HOLD.

    PRD §3.8: "The fourth hop, caused by the third, propagates posture to
    screenings: if the posture became `ADMISSION_FREEZE`, every screening of
    that facility in `SUBMITTED` becomes `ON_HOLD`; if the posture left
    `ADMISSION_FREEZE`, every screening in `ON_HOLD` returns to `SUBMITTED`."

    Design: Difficulty/transitive_cascade/discharge_cascade_freezes_facility_and_holds_screenings
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stays = setup_admitted_cohort(env, [
        {"mrn": "MRN-A", "patient_overrides": PATIENT_A},
        {"mrn": "MRN-B", "patient_overrides": PATIENT_B},
    ])
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    session = schedule_session(env, admission_a,
                               "2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z")
    deliver_session(env, session["id"])
    discharge(env, admission_b, "2026-08-10T12:00:00Z")

    set_clock("2026-08-17T09:00:00Z")
    patient_c = register_patient(env, mrn="MRN-C", full_name="Cleo Barnes",
                                 impairment_group_code="0110",
                                 comorbidity_tier="TIER_3")
    screening_c = create_draft_screening(
        env, patient_c["id"], expected_admission_at="2026-08-18T09:00:00Z"
    )
    submit_screening(env, screening_c["id"])
    patient_d = register_patient(env, mrn="MRN-D", full_name="Dov Halvorsen",
                                 impairment_group_code="0704",
                                 etiologic_diagnosis_code="S72.001A",
                                 comorbidity_tier="TIER_1")
    screening_d = create_concurred_screening(
        env, patient_d["id"], expected_admission_at="2026-08-18T12:00:00Z"
    )

    discharge(env, admission_a, "2026-08-18T12:00:00Z")

    assert_facility_cohort(read_facility(env["facility_id"]),
                           cohort_total_count=2, cohort_qualifying_count=0,
                           provisional_compliance_pct=0.00,
                           posture="ADMISSION_FREEZE")
    assert_admission_dimensions(read_admission(admission_b),
                                compliance_class="NON_QUALIFYING")
    assert read_screening(screening_c["id"])["status"] == "ON_HOLD"
    assert read_screening(screening_d["id"])["status"] == "PHYSICIAN_CONCURRED"


def test_finalising_a_quality_penalty_never_reprices_an_earlier_stay():
    """The penalty takes force at once but the already-priced stay is untouched.

    PRD §3.3: "`qrp_penalty_pct_snapshot` is pinned from the facility's
    `active_qrp_penalty_pct` at that instant, defaulting to 0.00 when no penalty
    is in force, and is never repinned — a quality-reporting penalty finalised
    tomorrow does not reach a patient admitted today."

    Design: Difficulty/combinatorial_formula/qrp_penalty_snapshot_ordering_versus_stay_payment
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"),
                                    review_period_end="2026-09-30")
    stay_a = setup_stay(env, patient_overrides=PATIENT_A, with_plan=False)
    discharge(env, stay_a["admission"]["id"], "2026-08-18T12:00:00Z")
    qrp = open_qrp_assessment(env, fiscal_year=2027,
                              reporting_period_start="2026-08-01",
                              reporting_period_end="2026-08-31")

    finalize_qrp_assessment(qrp["id"])

    finalized = read_qrp_assessment(qrp["id"])
    assert finalized["cohort_count"] == 1
    assert finalized["timely_count"] == 0
    assert float(finalized["data_completeness_pct"]) == 0.00
    assert float(finalized["penalty_pct"]) == 2.00
    assert finalized["status"] == "FINALIZED"
    facility = read_facility(env["facility_id"])
    assert float(facility["active_qrp_penalty_pct"]) == 2.00
    assert facility["qrp_penalty_effective_at"].startswith("2026-08-18T12:00:00")
    priced = read_admission(stay_a["admission"]["id"])
    assert priced["cmg_tier"] == "TIER_B"
    assert float(priced["qrp_penalty_pct_snapshot"]) == 0.00
    assert_payment(priced, effective_los_days=15, total_payment_cents=2597000)


def test_stay_admitted_after_finalisation_pays_the_reduced_amount():
    """The later stay pins 2.00 percent and pays 2545060 cents.

    PRD §3.8: "*Step five — the quality-reporting reduction, applied last.*
    `total_payment_cents` is the gross amount multiplied by one minus the head's
    `qrp_penalty_pct_snapshot` divided by 100, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/qrp_penalty_snapshot_ordering_versus_stay_payment
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"),
                                    review_period_end="2026-09-30")
    stay_a = setup_stay(env, patient_overrides=PATIENT_A, with_plan=False)
    discharge(env, stay_a["admission"]["id"], "2026-08-18T12:00:00Z")
    qrp = open_qrp_assessment(env, fiscal_year=2027,
                              reporting_period_start="2026-08-01",
                              reporting_period_end="2026-08-31")
    finalize_qrp_assessment(qrp["id"])

    set_clock("2026-08-18T20:00:00Z")
    patient_b = register_patient(env, mrn="MRN-B", full_name="Bo Whitaker",
                                 comorbidity_tier="TIER_2")
    screening_b = create_concurred_screening(
        env, patient_b["id"], expected_admission_at="2026-08-19T12:00:00Z"
    )
    admission_b = open_admission(env, patient_b["id"], screening_b["id"])
    admitted_b = admit(env, admission_b["id"], "2026-08-19T12:00:00Z")
    assert float(admitted_b["qrp_penalty_pct_snapshot"]) == 2.00

    discharged_b = discharge(env, admission_b["id"], "2026-09-02T12:00:00Z")

    assert_payment(discharged_b, effective_los_days=15,
                   total_payment_cents=2545060, payment_status="PRICED")
    facility = read_facility(env["facility_id"])
    assert facility["settled_payment_cents"] == 5142060


def test_attaching_a_continuation_consolidates_payment_into_the_chain_head():
    """The continuation carries no money and reopens the head that does.

    PRD §3.4: "Attaching a continuation sets `interrupted_stay_flag` to true (it
    is false by default), records the computed gap in `interruption_gap_days`
    (null on any stay that is not a continuation), and points
    `payment_consolidated_into_admission_id` at the head of the chain — the
    admission whose own `predecessor_admission_id` is null — which is where the
    single consolidated payment will live."

    Design: Difficulty/transitive_cascade/interrupted_stay_attach_reopens_head_and_stales_review
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env, patient_overrides=PATIENT_A,
                                     attach=False)
    open_and_compute_review(env)

    continuation = admit(env, chain["continuation"]["id"],
                         chain["continuation_admitted_at"])

    assert continuation["interrupted_stay_flag"] is True
    assert continuation["interruption_gap_days"] == 2
    assert continuation["payment_status"] == "CONSOLIDATED"
    assert continuation["total_payment_cents"] == 0
    assert (continuation["payment_consolidated_into_admission_id"]
            == chain["head"]["id"])
    head = read_admission(chain["head"]["id"])
    assert head["payment_status"] == "REOPENED"
    assert head["total_payment_cents"] == 0
    assert head["effective_los_days"] is None


def test_attaching_a_continuation_clears_the_ledger_and_stales_the_review():
    """The facility unsettles the head's money and its computed review goes STALE.

    PRD §3.4: "And because a reopened stay's numbers are provisional, every
    compliance review of that facility currently in `COMPUTED` whose cohort
    contains the head is invalidated to `STALE`, with `stale_reason` set to
    `INTERRUPTED_STAY_RECONSOLIDATION`."

    Design: Difficulty/transitive_cascade/interrupted_stay_attach_reopens_head_and_stales_review
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env, patient_overrides=PATIENT_A,
                                     attach=False)
    review = open_and_compute_review(env)

    admit(env, chain["continuation"]["id"], chain["continuation_admitted_at"])

    assert read_facility(env["facility_id"])["settled_payment_cents"] == 0
    staled = read_compliance_review(review["id"])
    assert staled["status"] == "STALE"
    assert staled["stale_reason"] == "INTERRUPTED_STAY_RECONSOLIDATION"
    assert float(staled["compliance_pct"]) == 0.00
    assert staled["total_cases"] == 1


def test_rescinding_an_interruption_unlinks_the_continuation():
    """Rescission clears every consolidation field on the continuation.

    PRD §3.4: "Rescission sets `interrupted_stay_flag` back to false, clears
    `interruption_gap_days`, `payment_consolidated_into_admission_id` and
    `predecessor_admission_id` to null, and moves the continuation's
    `payment_status` from `CONSOLIDATED` back to `NOT_PRICED`."

    Design: Difficulty/compensating_invariant/rescind_interruption_restores_head_pricing_and_facility_ledger
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env, patient_overrides=PATIENT_A,
                                     attach=False)
    open_and_compute_review(env)
    admit(env, chain["continuation"]["id"], chain["continuation_admitted_at"])

    response = api_client.rescind_interruption(
        chain["continuation"]["id"], rescind_interruption_payload(),
        OFFICER_HEADERS,
    )

    rescinded = validate_success(response, expected_status=200)
    assert rescinded["interrupted_stay_flag"] is False
    assert rescinded["interruption_gap_days"] is None
    assert rescinded["predecessor_admission_id"] is None
    assert rescinded["payment_consolidated_into_admission_id"] is None
    assert_admission_dimensions(rescinded, stay_status="ADMITTED",
                                payment_status="NOT_PRICED")


def test_rescinding_an_interruption_restores_the_head_and_the_facility_ledger():
    """The head returns to PRICED at exactly the amount it held before.

    PRD §3.4: "The chain head is made whole in the same breath: its
    `payment_status` moves from `REOPENED` back to `PRICED` with its standalone
    `effective_los_days` and `total_payment_cents` restored, and the facility's
    `settled_payment_cents` is recomputed to exactly the value it held before
    the erroneous attach."

    Design: Difficulty/compensating_invariant/rescind_interruption_restores_head_pricing_and_facility_ledger
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env, patient_overrides=PATIENT_A,
                                     attach=False)
    review = open_and_compute_review(env)
    admit(env, chain["continuation"]["id"], chain["continuation_admitted_at"])

    validate_success(api_client.rescind_interruption(
        chain["continuation"]["id"], rescind_interruption_payload(),
        OFFICER_HEADERS,
    ))

    head = read_admission(chain["head"]["id"])
    assert_payment(head, effective_los_days=7, total_payment_cents=1623128,
                   payment_status="PRICED")
    assert read_facility(env["facility_id"])["settled_payment_cents"] == 1623128
    assert read_compliance_review(review["id"])["status"] == "STALE"
