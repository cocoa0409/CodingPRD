"""Each declared derivation driven once on the edge that makes its rule visible."""
from test_helpers import (
    accept_offer,
    add_operating_room,
    advance_clock,
    book_theatre,
    complete_transplant,
    create_active_recipient,
    create_donor,
    create_medical_evaluation_payload,
    create_medical_findings_payload,
    create_outcome_review_payload,
    create_psychosocial_evaluation_payload,
    create_psychosocial_findings_payload,
    create_recipient,
    create_recipient_candidate_payload,
    create_donor_cost_claim_payload,
    determine_evaluation,
    file_and_approve_claim,
    file_claim,
    follow_up_by_interval,
    follow_up_fields,
    get_chain,
    get_donor,
    refresh_program,
    run_compliance_sweep,
    send_offer,
    setup_committed_paired_loop,
    setup_donated_donor,
    setup_program_with_staff,
    update_recipient_status,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def test_every_medical_soft_band_upper_edge_awards_its_points_without_excluding():
    """PRD §3.4: "Soft findings do not exclude anyone; they accumulate `risk_points`."
    PRD §3.4: "On a medical evaluation, 2 points are added when `bmi` is strictly
    greater than 30.0 and at most 35.0; 3 points when `egfr_ml_min` is at least 80.0 and
    strictly below 90.0; 2 points when `systolic_bp` is at least 140 and strictly below
    160; 2 points when `hba1c` is at least 5.7 and strictly below 6.5; and 1 point when
    the donor's `age_years` is at least 60."
    PRD §3.4: "The bands are constructed so that the hard region lies strictly outside
    the soft region: a `bmi` of exactly 35.0 is a soft two-point finding rather than a
    hard exclusion, an `egfr_ml_min` of exactly 80.0 is a soft three-point finding, a
    `systolic_bp` of exactly 160 is hard, and an `hba1c` of exactly 6.5 is hard."
    PRD §3.4: "A new evaluation row starts at `SUBMITTED` with `submission_count` 1 and
    `determined_at` null, and the first evaluation row ever created for a donor moves
    that donor's `overall_status` from `REFERRED` to `EVAL_IN_PROGRESS`."
    PRD §3.3: "A new donor starts with `overall_status` `REFERRED`, `advocacy_status`
    `UNASSIGNED`, both `medical_status` and `psychosocial_status` at `PENDING`,
    `disclosure_sequence` 0, `deferral_count` 0, `medical_risk_points` and
    `psychosocial_risk_points` 0, and `screening_risk_index` 0; `advocate_staff_id`,
    `disclosure_at`, `cooling_off_ends_at`, `attestation_at`, `objection_reason_code`,
    `final_risk_index` and `donated_at` are all null."

    Design: Corner/calculations/exclusion_screen_soft_band_upper_edges_award_every_soft_point
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-501", age_years=60
    )

    evaluation = validate_success(
        api_client.create_donor_evaluation(
            create_medical_evaluation_payload(
                donor["id"], bmi=35.0, egfr_ml_min=80.0, systolic_bp=159, hba1c=6.4
            ),
            env["reviewer_med_headers"],
        ),
        expected_status=201,
    )

    assert evaluation["status"] == "SUBMITTED"
    assert evaluation["domain"] == "MEDICAL"
    assert evaluation["exclusion_codes"] == []
    assert evaluation["hard_exclusion_count"] == 0
    assert evaluation["risk_points"] == 10, "2 + 3 + 2 + 2 + 1, every band on its edge"
    assert evaluation["reviewer_staff_id"] == env["reviewer_med"]["id"]
    assert evaluation["submission_count"] == 1
    assert evaluation["determined_at"] is None

    after = get_donor(env, donor["id"])
    assert after["overall_status"] == "EVAL_IN_PROGRESS", "the first evaluation row exists"
    assert after["medical_status"] == "PENDING"
    assert after["medical_risk_points"] == 0, "nothing mirrors before a determination"
    assert after["screening_risk_index"] == 0


def test_a_resubmission_over_the_hard_edge_zeroes_the_soft_points():
    """PRD §3.4: "`EX_BMI_TOO_HIGH` fires when `bmi` is strictly greater than 35.0."
    PRD §3.4: "A measurement that fires a hard code contributes no soft points for that
    same measurement."
    PRD §3.4: "The evaluation returns to `SUBMITTED`, `submission_count` increases by 1,
    `determined_at` is cleared to null, and `exclusion_codes`, `hard_exclusion_count` and
    `risk_points` are re-screened from the new findings."
    PRD §3.4: "Critically, `deferral_count` is **not** reset — the resubmission repairs
    the findings but not the history."

    Design: Corner/calculations/exclusion_screen_resubmission_over_the_hard_edge_zeroes_risk_points
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-502", age_years=41
    )
    evaluation = validate_success(
        api_client.create_donor_evaluation(
            create_medical_evaluation_payload(
                donor["id"], bmi=31.0, egfr_ml_min=84.0, systolic_bp=145, hba1c=6.0
            ),
            env["reviewer_med_headers"],
        ),
        expected_status=201,
    )
    assert evaluation["risk_points"] == 9, "2 + 3 + 2 + 2 with no hard code"
    assert evaluation["hard_exclusion_count"] == 0
    determine_evaluation(env, evaluation["id"], "DEFERRED", env["reviewer_med_headers"])
    assert get_donor(env, donor["id"])["deferral_count"] == 1

    resubmitted = validate_success(
        api_client.resubmit_evaluation(
            evaluation["id"],
            {
                **create_medical_findings_payload(
                    bmi=35.1, egfr_ml_min=95.0, systolic_bp=130, hba1c=5.2
                ),
                **create_psychosocial_findings_payload(),
            },
            env["reviewer_med_headers"],
        )
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["determined_at"] is None
    assert resubmitted["submission_count"] == 2
    assert resubmitted["exclusion_codes"] == ["EX_BMI_TOO_HIGH"]
    assert resubmitted["hard_exclusion_count"] == 1
    assert resubmitted["risk_points"] == 0, (
        "one hundredth of a BMI point turns a two-point finding into a hard exclusion, "
        "so the figure falls from 9 to 0 rather than rising"
    )

    donor_after = get_donor(env, donor["id"])
    assert donor_after["deferral_count"] == 1
    assert donor_after["medical_status"] == "DEFERRED", (
        "the dimension waits for a fresh determination"
    )


def test_a_psychosocial_row_scores_only_its_own_domain_findings():
    """PRD §3.4: "Only codes belonging to the evaluation's own domain are considered."
    PRD §3.4: "On a psychosocial evaluation, 3 points are added when
    `financial_hardship_score` is at least 7, and 2 points when `social_support_score` is
    at most 3."
    PRD §3.4: "For a psychosocial evaluation, three hard codes may fire:
    `EX_COERCION_SUSPECTED` when `coercion_flag` is true, `EX_SUBSTANCE_USE` when
    `unmanaged_substance_use` is true, and `EX_CAPACITY_ABSENT` when
    `decisional_capacity_ok` is false."
    PRD §3.4: "Evaluations are listed with optional `donor_candidate_id`,
    `reviewer_staff_id`, `domain` and `status` filters plus `limit` and `offset`, and read
    individually to expose `exclusion_codes`, `hard_exclusion_count`, `risk_points` and
    `submission_count`."

    Design: Corner/calculations/psychosocial_screen_ignores_medical_findings_in_the_same_payload
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-503", age_years=41
    )

    evaluation = validate_success(
        api_client.create_donor_evaluation(
            create_psychosocial_evaluation_payload(
                donor["id"],
                financial_hardship_score=7,
                social_support_score=3,
                bmi=31.0,
                egfr_ml_min=84.0,
                systolic_bp=145,
                hba1c=6.0,
            ),
            env["reviewer_psy_headers"],
        ),
        expected_status=201,
    )

    assert evaluation["domain"] == "PSYCHOSOCIAL"
    assert evaluation["risk_points"] == 5, (
        "3 for the hardship edge plus 2 for the support edge; the medical findings in "
        "the same payload are worth 9 in their own domain and 0 here"
    )
    assert evaluation["exclusion_codes"] == []
    assert evaluation["hard_exclusion_count"] == 0

    _rows, meta = validate_paginated(
        api_client.list_donor_evaluations(
            env["reviewer_psy_headers"], params={"donor_candidate_id": donor["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_realized_interval_over_the_ceiling_breaches_yet_keeps_the_posture_open():
    """PRD §3.6: "`actual_cit_minutes`, by contrast, is computed at completion as simply
    the whole minutes between `actual_cross_clamp_at` and `actual_reperfusion_at`,
    truncated toward zero, with no allowance added, because the realized interval already
    contains whatever hold actually occurred."
    PRD §3.7: "On success the segment moves to `TRANSPLANTED` — a terminal segment
    state — records both actual timestamps, computes `actual_cit_minutes`, and sets
    `cit_breach` to true when `actual_cit_minutes` exceeds the eighteen-hour ceiling of
    1,080 minutes and false otherwise."
    PRD §3.7: "When `cit_breach` came out true, the program's `cit_breach_count`
    increases by 1 and `compliance_posture` is re-derived again — two breaches are enough
    to restrict the program."
    PRD §2.8: "A `cit_breach_count` of 1 keeps the program `OPEN`; 2 degrades it to
    `RESTRICTED`."

    Design: Corner/calculations/actual_cit_over_the_cap_flags_breach_but_one_breach_keeps_posture_open
    """
    env = setup_committed_paired_loop()
    room_one = add_operating_room(env, "OR-1")
    room_two = add_operating_room(env, "OR-2")
    segment_id = env["segment_one"]["id"]
    book_theatre(
        env,
        room_one["id"],
        segment_id,
        "DONOR_RECOVERY",
        "2026-08-09T05:00:00Z",
        "2026-08-09T07:00:00Z",
    )
    book_theatre(
        env,
        room_two["id"],
        segment_id,
        "RECIPIENT_IMPLANT",
        "2026-08-09T22:00:00Z",
        "2026-08-10T02:00:00Z",
    )
    advance_clock(env, "2026-08-09T04:00:00Z")
    offered = send_offer(
        env, segment_id, "2026-08-09T06:00:00Z", "2026-08-09T23:15:00Z"
    )
    assert offered["planned_cit_minutes"] == 1080, "1035 minutes plus the 45-minute hold"
    accept_offer(env, segment_id)
    advance_clock(env, "2026-08-10T02:00:00Z")

    completed = complete_transplant(
        env, segment_id, "2026-08-09T06:00:00Z", "2026-08-10T00:05:30Z"
    )

    assert completed["status"] == "TRANSPLANTED"
    assert completed["actual_cit_minutes"] == 1085, (
        "the thirty-second remainder truncates and no hold is added"
    )
    assert completed["cit_breach"] is True
    assert completed["planned_cit_minutes"] == 1080, "the planned figure is not restated"

    program = refresh_program(env)
    assert program["cit_breach_count"] == 1
    assert program["compliance_posture"] == "OPEN", "one breach does not restrict"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "EXECUTING"
    assert chain["total_planned_cit_minutes"] == 1080

    donor = get_donor(env, env["donor_one"]["id"])
    assert donor["overall_status"] == "DONATED"
    assert donor["donated_at"].startswith("2026-08-10T02:00:00")


def test_two_listed_intervals_are_merged_and_floored_once():
    """PRD §3.2: "An active interval opens at every event whose `to_status` is `ACTIVE`
    and closes at the next event whose `from_status` is `ACTIVE`; an interval still open
    when the figure is evaluated closes at the current logical clock."
    PRD §3.2: "Applying the floor once rather than per interval matters: two separate
    twelve-hour intervals sum to a full day and count as 1, where per-interval flooring
    would have counted 0."
    PRD §3.2: "From `APPROVED_NOT_LISTED` the candidate may be registered on the
    waitlist by moving to `ACTIVE`; the first time this happens the candidate's
    `registered_at` is set to the supplied `effective_at`, and later re-entries into
    `ACTIVE` leave `registered_at` alone."
    PRD §3.2: "The pediatric component is 3 when `age_years` is below 18 and 0
    otherwise, so a candidate who is exactly 18 earns no bonus."
    PRD §3.2: "`waitlist_priority_score` is the sum of five components, each of which is
    rounded half up to two decimal places *before* the addition, with the sum itself left
    unrounded."
    PRD §3.2: "The waiting component is `active_days_total` multiplied by 0.007, so a
    full year of listed time contributes 2.56 points, and the small weight is deliberate
    so that waiting never overwhelms urgency."

    Design: Corner/calculations/waitlist_active_days_floors_the_merged_total_once
    """
    env = setup_program_with_staff()
    recipient = create_recipient(
        env,
        mrn="R-201",
        abo_blood_type="A",
        age_years=17,
        cpra=0.20,
        dialysis_years=0,
        medical_urgency_points=1,
    )
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", "2026-05-01T00:00:00Z"
    )
    update_recipient_status(
        env, recipient["id"], "ACTIVE", "LISTED", "2026-06-01T00:00:00Z"
    )
    update_recipient_status(
        env, recipient["id"], "INACTIVE_HOLD", "MEDICALLY_UNFIT", "2026-06-11T12:00:00Z"
    )
    update_recipient_status(
        env, recipient["id"], "ACTIVE", "RELISTED", "2026-07-01T00:00:00Z"
    )

    removed = validate_success(
        api_client.create_recipient_status_update(
            recipient["id"],
            {
                "to_status": "REMOVED",
                "reason_code": "PATIENT_WITHDREW",
                "effective_at": "2026-07-11T18:00:00Z",
            },
            env["coordinator_headers"],
        )
    )

    assert removed["listing_status"] == "REMOVED"
    assert removed["active_days_total"] == 21, (
        "10.5 days plus 10.75 days is 21.25, floored once to 21 rather than 10 plus 10"
    )
    assert removed["waitlist_priority_score"] == 6.15, (
        "2.0 urgency + 0.15 waiting + 0.0 dialysis + 1.0 sensitization + 3.0 pediatric"
    )
    assert removed["registered_at"].startswith("2026-06-01T00:00:00"), (
        "the first ACTIVE instant survives the relisting"
    )

    _events, meta = validate_paginated(
        api_client.list_waitlist_events(recipient["id"], env["coordinator_headers"])
    )
    assert meta["total_count"] == 5


def test_the_sensitization_tier_is_inclusive_at_its_lower_bound():
    """PRD §3.2: "The sensitization component is a tier lookup on `cpra`, inclusive at
    each lower bound: 10 when `cpra` is at least 0.98, otherwise 4 when it is at least
    0.80, otherwise 1 when it is at least 0.20, otherwise 0."
    PRD §3.2: "`waitlist_priority_score` is the sum of five components, each of which is
    rounded half up to two decimal places *before* the addition, with the sum itself left
    unrounded."
    PRD §3.2: "The urgency component is `medical_urgency_points` multiplied by 2."
    PRD §3.2: "The dialysis component is `dialysis_years` multiplied by 1.005."
    PRD §3.2: "The new candidate's `listing_status` starts at `WORKUP`,
    `active_days_total` at 0, `offer_decline_count` at 0, and `waitlist_priority_score`
    is computed immediately — with zero accumulated waiting time, since the candidate has
    never been active."

    Design: Corner/calculations/cpra_tier_boundary_is_inclusive_at_the_lower_bound
    """
    env = setup_program_with_staff()
    just_below = validate_success(
        api_client.create_recipient_candidate(
            create_recipient_candidate_payload(
                env["program_id"],
                mrn="R-301",
                abo_blood_type="A",
                age_years=30,
                cpra=0.9799,
                dialysis_years=1.0,
                medical_urgency_points=3,
            ),
            env["coordinator_headers"],
        ),
        expected_status=201,
    )
    assert just_below["waitlist_priority_score"] == 11.01, (
        "6.0 urgency + 0.0 waiting + 1.01 dialysis + 4.0 for the 0.80 tier"
    )

    on_the_bound = validate_success(
        api_client.create_recipient_candidate(
            create_recipient_candidate_payload(
                env["program_id"],
                mrn="R-302",
                abo_blood_type="A",
                age_years=30,
                cpra=0.98,
                dialysis_years=1.0,
                medical_urgency_points=3,
            ),
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert on_the_bound["waitlist_priority_score"] == 17.01, (
        "6.0 + 0.0 + 1.01 + 10.0 for the inclusive 0.98 tier"
    )
    assert on_the_bound["listing_status"] == "WORKUP"
    assert on_the_bound["active_days_total"] == 0
    assert just_below["listing_status"] == "WORKUP"
    assert just_below["active_days_total"] == 0
    assert round(
        on_the_bound["waitlist_priority_score"] - just_below["waitlist_priority_score"], 2
    ) == 6.0, "four decimal places of cpra are worth six whole priority points"


def test_the_lost_wage_cap_flips_from_daily_to_weekly_at_five_days():
    """PRD §3.9: "For a `LOST_WAGES` claim the cap is the smaller of two figures:
    `lost_wage_days` multiplied by the program's `lost_wage_daily_cap_cents`, and the
    number of weeks — `lost_wage_days` divided by 7 and rounded **up** to a whole week —
    multiplied by the program's `lost_wage_weekly_cap_cents`."
    PRD §3.9: "With the default daily and weekly caps the nested comparison flips at the
    five-day mark: at four days the daily figure of 120,000 binds below the one-week
    figure of 150,000, at exactly five days the two are equal at 150,000, and at six days
    the weekly figure of 150,000 binds below the daily figure of 180,000."
    PRD §3.9: "`estimated_reimbursement_cents` is then the smaller of
    `submitted_amount_cents` and that cap."
    PRD §3.9: "A new claim starts in `SUBMITTED` with `insurance_part_cents`,
    `grant_part_cents` and `fund_part_cents` all 0 and with
    `adjudicated_reimbursement_cents`, `unfunded_cents`, `adjudicated_at`,
    `adjudicated_by_user_id` and `reversal_reason_code` all null."

    Design: Corner/calculations/lost_wage_nested_cap_min_flips_at_the_five_day_crossover
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    four_days = file_claim(
        env,
        donor_id,
        claim_type="LOST_WAGES",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=200000,
        lost_wage_days=4,
        service_from_on="2026-08-10",
        service_to_on="2026-08-13",
    )
    six_days = file_claim(
        env,
        donor_id,
        claim_type="LOST_WAGES",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=200000,
        lost_wage_days=6,
        service_from_on="2026-08-14",
        service_to_on="2026-08-19",
    )

    five_days = validate_success(
        api_client.create_donor_cost_claim(
            create_donor_cost_claim_payload(
                donor_id,
                claim_type="LOST_WAGES",
                coverage_source="PROGRAM_FUND",
                submitted_amount_cents=200000,
                lost_wage_days=5,
                service_from_on="2026-08-20",
                service_to_on="2026-08-24",
            ),
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert five_days["status"] == "SUBMITTED"
    assert five_days["estimated_reimbursement_cents"] == 150000, (
        "at five days the daily and weekly figures are equal"
    )
    assert four_days["estimated_reimbursement_cents"] == 120000, "the daily cap binds"
    assert six_days["estimated_reimbursement_cents"] == 150000, "the weekly cap binds"

    for part in ("insurance_part_cents", "grant_part_cents", "fund_part_cents"):
        assert five_days[part] == 0
    assert five_days["adjudicated_reimbursement_cents"] is None
    assert five_days["unfunded_cents"] is None
    assert five_days["adjudicated_at"] is None

    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 0, "filing commits no money"
    assert program["donor_fund_remaining_cents"] == 5000000

    _rows, meta = validate_paginated(
        api_client.list_donor_cost_claims(donor_id, env["coordinator_headers"])
    )
    assert meta["total_count"] == 3


def test_the_waterfall_skips_structurally_closed_buckets_and_records_the_shortfall():
    """PRD §3.9: "The insurance bucket has a per-claim ceiling of 600,000 cents (six
    thousand dollars), but only when the claim's `coverage_source` is
    `RECIPIENT_INSURANCE`; for any other coverage source the insurance headroom is zero,
    so a claim filed against the program fund never touches insurance even where a
    ceiling would have existed."
    PRD §3.9: "The grant bucket is only open to claims whose `claim_type` is `TRAVEL` or
    `LOST_WAGES`; for a `MEDICAL` claim the grant headroom is zero."
    PRD §3.9: "The funded need is then the smaller of `estimated_reimbursement_cents`
    and that headroom."
    PRD §3.9: "`adjudicated_reimbursement_cents` is the sum of the three parts, and
    `unfunded_cents` is `estimated_reimbursement_cents` less
    `adjudicated_reimbursement_cents` — the shortfall between what the caps allowed and
    what the pockets could actually pay, recorded and never silently dropped, and the
    figure an improvement-plan narrative reports."

    Design: Corner/calculations/adjudication_waterfall_skips_zero_headroom_buckets_and_records_the_shortfall
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    first = file_and_approve_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=1000000,
    )
    assert first["fund_part_cents"] == 1000000
    opening = refresh_program(env)
    assert opening["donor_fund_committed_cents"] == 1000000
    assert opening["donor_fund_remaining_cents"] == 4000000

    second = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=800000,
    )
    assert second["estimated_reimbursement_cents"] == 800000

    adjudicated = validate_success(
        api_client.adjudicate_claim(
            second["id"], {"decision": "APPROVE"}, env["finance_headers"]
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["adjudicated_at"].startswith("2026-08-09T06:00:00")
    assert adjudicated["insurance_part_cents"] == 0, (
        "a PROGRAM_FUND claim opens no insurance headroom at all"
    )
    assert adjudicated["grant_part_cents"] == 0, "a MEDICAL claim is not grant-eligible"
    assert adjudicated["fund_part_cents"] == 500000, (
        "the need is clipped to the 500000 of lifetime headroom that is left"
    )
    assert adjudicated["adjudicated_reimbursement_cents"] == 500000
    assert adjudicated["estimated_reimbursement_cents"] == 800000, "the estimate is never revised"
    assert adjudicated["unfunded_cents"] == 300000

    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 1500000
    assert program["donor_fund_remaining_cents"] == 3500000
    assert (
        program["donor_fund_committed_cents"] + program["donor_fund_remaining_cents"]
        == program["donor_fund_pool_cents"]
    )


def test_one_complete_submission_lifts_compliance_from_zero_to_a_hundred():
    """PRD §3.7: "The denominator is the count of follow-up rows whose donor belongs to
    this program, whose `status` is one of `DUE`, `SUBMITTED_COMPLETE`, `INCOMPLETE` or
    `DELINQUENT`, and whose `due_on` is at or before the current logical clock."
    PRD §3.7: "The numerator is the count of those same rows whose `status` is
    `SUBMITTED_COMPLETE`."
    PRD §3.7: "The threshold comparison is inclusive: when `completeness_pct` is at or
    above the program's `follow_up_completeness_threshold_pct` the row becomes
    `SUBMITTED_COMPLETE`, and otherwise it becomes `INCOMPLETE`."
    PRD §3.7: "Either outcome stamps `submitted_at` with the current logical clock,
    recomputes the program's `follow_up_compliance_pct`, re-derives `compliance_posture`,
    and increments the row's `version`."

    Design: Corner/calculations/program_compliance_recovers_from_zero_to_hundred_on_one_submission
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    advance_clock(env, "2027-02-06T00:00:00Z")
    swept = run_compliance_sweep(env)
    assert swept["follow_up_compliance_pct"] == 0.0
    assert swept["compliance_posture"] == "RESTRICTED"

    six_month = follow_up_by_interval(env, donor_id, "SIX_MONTH")
    assert six_month["status"] == "DUE", "only one day of the thirty-day grace has passed"
    assert six_month["required_fields_count"] == 12

    submitted = validate_success(
        api_client.submit_follow_up(
            six_month["id"],
            {"submitted_fields": follow_up_fields(12)},
            env["coordinator_headers"],
        )
    )

    assert submitted["status"] == "SUBMITTED_COMPLETE"
    assert submitted["submitted_at"].startswith("2027-02-06T00:00:00")
    assert submitted["submitted_field_count"] == 12
    assert submitted["completeness_pct"] == 100.0

    program = refresh_program(env)
    assert program["follow_up_compliance_pct"] == 100.0, "denominator 1, numerator 1"
    assert program["compliance_posture"] == "OPEN"
    assert program["last_sweep_at"].startswith("2027-02-06T00:00:00"), (
        "a submission is not a sweep and does not restamp last_sweep_at"
    )


def test_a_cohort_below_the_minimum_suppresses_the_ratio_and_the_flag():
    """PRD §3.8: "When `cohort_size` is below 10, the cohort is too small to rate at
    all: `oe_ratio` is null, `flag_level` is `NONE` and `requires_improvement_plan` is
    false, no matter how catastrophic the raw ratio would have looked."
    PRD §3.8: "`expected_survivor_count` is `cohort_size` multiplied by
    `expected_survival_rate_used`, rounded half up to two decimal places."
    PRD §3.8: "Creation snapshots the program's `expected_one_year_survival_rate` into
    the review's own `expected_survival_rate_used`."
    PRD §3.8: "A new review's `status` is `DRAFT` and `finalized_at` is null; a draft
    review does not yet affect the program's posture at all."

    Design: Corner/calculations/cohort_below_minimum_suppresses_the_ratio_and_the_flag
    """
    env = setup_program_with_staff()

    review = validate_success(
        api_client.create_outcome_review(
            create_outcome_review_payload(
                env["program_id"],
                period_start_on="2025-01-01",
                period_end_on="2025-12-31",
                cohort_size=9,
                observed_survivor_count=3,
            ),
            env["quality_headers"],
        ),
        expected_status=201,
    )

    assert review["status"] == "DRAFT"
    assert review["expected_survival_rate_used"] == 0.8
    assert review["expected_survivor_count"] == 7.2
    assert review["oe_ratio"] is None, (
        "the raw ratio of 3 over 7.2 would have flagged, but the cohort cannot be rated"
    )
    assert review["flag_level"] == "NONE"
    assert review["requires_improvement_plan"] is False
    assert review["finalized_at"] is None
    assert review["version"] == 1

    assert refresh_program(env)["compliance_posture"] == "OPEN"
