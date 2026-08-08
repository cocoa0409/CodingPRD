"""Service-period closure, TCM code selection, the money waterfall and the
bounded denial-and-appeal loop."""
from test_helpers import (
    ADMIN,
    BILLER_PREPARER,
    BILLER_SUBMITTER,
    MODERATE_REQUIRED_ELEMENTS,
    ApiErrorId,
    assert_claim,
    assert_claim_money,
    assert_same_instant,
    book_visit,
    close_service_period,
    complete_visit,
    connect_contact,
    make_care_navigator_headers,
    prepare_claim,
    read_claim,
    read_episode,
    read_navigator,
    read_patient,
    read_visit,
    set_clock,
    setup_billable_episode,
    setup_completed_medrec,
    setup_confirmed_visit,
    setup_episode,
    setup_prepared_claim,
    setup_program,
    setup_program_with_episode,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_full_variant_bills_99496_when_the_visit_lands_on_day_four(api):
    """PRD §3.8: "When the episode's `required_visit_complexity` is
    `HIGH_COMPLEXITY`, the visit's `achieved_complexity` is also
    `HIGH_COMPLEXITY`, and `completed_at` is on or before the high-complexity
    deadline, the `payable_code` is `99496`."
    PRD §3.8: "A `99496` claim yields an allowed amount of 27680 cents,
    coinsurance of 5536 cents, a net before withhold of 22144 cents, a withhold
    rate of 0.03, a withhold of 664 cents and a net payable of 21480 cents."

    Design: Difficulty/dual_variant_calc/claim_code_full_99496_vs_downgraded_99495
    """
    ctx, ep, visit = setup_billable_episode()
    claim = prepare_claim(ctx, ep, visit["id"])
    assert_claim(claim)
    assert str(claim["payable_code"]) == "99496"
    assert claim["payable_variant"] == "FULL"
    assert_claim_money(
        claim,
        base_rate_cents=27680,
        allowed_cents=27680,
        coinsurance_cents=5536,
        net_before_withhold_cents=22144,
        withhold_pct=0.03,
        withhold_cents=664,
        net_payable_cents=21480,
    )
    assert visit["achieved_complexity"] == "HIGH_COMPLEXITY"
    assert read_episode(ctx, ep["episode_id"])["visit_timely"] is True


def test_downgraded_variant_bills_99495_when_the_visit_lands_on_day_ten(api):
    """PRD §3.8: "Otherwise, provided `completed_at` is on or before the
    moderate deadline, the `payable_code` is `99495`."
    PRD §3.8: "The `payable_variant` records which side of that fork the claim
    landed on — `DOWNGRADED` when the episode required high complexity but the
    claim fell back to `99495`, and `FULL` in every other case. `base_rate_cents`
    follows the code: 27680 cents for `99496` and 20450 cents for `99495`."
    PRD §3.8: "A `99495` claim yields 20450, 4090, 16360, a withhold rate of
    0.01, 164 and a net payable of 16196 cents."

    Design: Difficulty/dual_variant_calc/claim_code_full_99496_vs_downgraded_99495
    """
    ctx, ep, visit = setup_billable_episode(
        visit_start="2026-05-11T15:00:00Z",
        visit_end="2026-05-11T16:00:00Z",
        visit_completed_at="2026-05-11T16:00:00Z",
    )
    claim = prepare_claim(ctx, ep, visit["id"])
    assert str(claim["payable_code"]) == "99495"
    assert claim["payable_variant"] == "DOWNGRADED"
    assert_claim_money(
        claim,
        base_rate_cents=20450,
        allowed_cents=20450,
        coinsurance_cents=4090,
        net_before_withhold_cents=16360,
        withhold_pct=0.01,
        withhold_cents=164,
        net_payable_cents=16196,
    )
    assert visit["achieved_complexity"] == "HIGH_COMPLEXITY"
    assert read_episode(ctx, ep["episode_id"])["visit_timely"] is False


def test_withhold_percentage_is_selected_from_the_post_coinsurance_net(api):
    """PRD §3.8: "Fourth, the quality withhold rate is selected from that third
    figure: `withhold_pct` is 0.03 when `net_before_withhold_cents` is at least
    20000 cents, and 0.01 when it is below 20000 cents."
    PRD §3.8: "Second, `coinsurance_cents` is that **already-rounded**
    `allowed_cents` multiplied by the payer's `coinsurance_rate`, rounded half
    up to whole cents — never the raw product from the first step."

    Design: Difficulty/combinatorial_formula/claim_withhold_tier_keyed_on_post_coinsurance_net
    """
    ctx, ep, visit = setup_billable_episode()
    claim = prepare_claim(ctx, ep, visit["id"])
    assert claim["allowed_cents"] == 27680
    assert claim["coinsurance_cents"] == 5536
    assert claim["net_before_withhold_cents"] == 22144
    assert abs(float(claim["withhold_pct"]) - 0.03) < 1e-9, (
        "the withhold tier is selected from 22144, not from the allowed amount"
    )


def test_withhold_cents_are_computed_from_the_net_not_the_allowed_amount(api):
    """PRD §3.8: "Fifth, `withhold_cents` is `net_before_withhold_cents`
    multiplied by `withhold_pct`, rounded half up to whole cents. Sixth and
    last, `net_payable_cents` is `net_before_withhold_cents` minus
    `withhold_cents`."
    PRD §2.8: "Rounding half up to whole cents is applied at each of the three
    points in the claim waterfall where a multiplication occurs — the allowed
    amount, the coinsurance amount and the withhold amount — and never
    retroactively to a figure that has already been rounded."

    Design: Difficulty/combinatorial_formula/claim_withhold_tier_keyed_on_post_coinsurance_net
    """
    ctx, ep, visit = setup_billable_episode()
    claim = prepare_claim(ctx, ep, visit["id"])
    assert claim["withhold_cents"] == 664, (
        "0.03 of 22144 rounds to 664; 0.03 of the allowed 27680 would give 830"
    )
    assert claim["net_payable_cents"] == 21480


def test_claim_appeal_loop_runs_exactly_twice(api):
    """PRD §3.8: "Filing an appeal on a `DENIED` claim whose `appeal_count` is
    below 2 moves it `DENIED → APPEALED` and increments `appeal_count` by 1; the
    money fields are deliberately **not** recomputed, so an appeal can never
    double-count the withhold."
    PRD §3.8: "`DENIED` stores the supplied `denial_reason_code` and leaves
    `appeal_count` untouched; denial never advances the appeal counter."

    Design: Difficulty/non_linear_state_machine/claim_denied_appealed_denied_bounded_loop
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    validate_success(
        api.adjudicate_claim(
            claim["id"],
            {"outcome": "DENIED", "denial_reason_code": "MISSING_DOCUMENTATION"},
            ADMIN,
        )
    )

    first = validate_success(api.appeal_claim(claim["id"], BILLER_SUBMITTER))
    assert first["status"] == "APPEALED"
    assert first["appeal_count"] == 1
    assert first["net_payable_cents"] == 21480

    denied_again = validate_success(
        api.adjudicate_claim(
            claim["id"], {"outcome": "DENIED", "denial_reason_code": "NOT_COVERED"}, ADMIN
        )
    )
    assert denied_again["status"] == "DENIED"
    assert denied_again["appeal_count"] == 1

    second = validate_success(api.appeal_claim(claim["id"], BILLER_SUBMITTER))
    assert second["status"] == "APPEALED"
    assert second["appeal_count"] == 2
    assert second["net_payable_cents"] == 21480

    denied_final_time = validate_success(
        api.adjudicate_claim(
            claim["id"], {"outcome": "DENIED", "denial_reason_code": "NOT_COVERED"}, ADMIN
        )
    )
    assert denied_final_time["status"] == "DENIED"
    assert denied_final_time["appeal_count"] == 2
    assert denied_final_time["net_payable_cents"] == 21480


def test_third_appeal_finalises_the_claim_and_zeroes_net_payable(api):
    """PRD §3.8: "When the bound is already exhausted — `appeal_count` already
    equal to 2 — a third attempt does something unusual: the claim is first
    flipped `DENIED → DENIED_FINAL` with `net_payable_cents` set to 0 and the
    freeze evaluation triggered, that change is persisted, and only then is the
    caller told `ERR_APPEAL_LIMIT_REACHED`."
    PRD §2.10: "Two of these rungs deliberately mutate state before returning
    their rejection, and the persisted change survives the error: rung 32 flips
    the claim from `DENIED` to `DENIED_FINAL` with `net_payable_cents` zeroed
    before returning `ERR_APPEAL_LIMIT_REACHED`, and rung 33 flips the handoff
    to `EXPIRED` before returning `ERR_HANDOFF_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/claim_denied_appealed_denied_bounded_loop
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    for reason in ("MISSING_DOCUMENTATION", "NOT_COVERED", "NOT_COVERED"):
        validate_success(
            api.adjudicate_claim(
                claim["id"], {"outcome": "DENIED", "denial_reason_code": reason}, ADMIN
            )
        )
        current = read_claim(ctx, claim["id"])
        if current["appeal_count"] < 2:
            validate_success(api.appeal_claim(claim["id"], BILLER_SUBMITTER))

    before = read_claim(ctx, claim["id"])
    assert before["status"] == "DENIED"
    assert before["appeal_count"] == 2
    assert before["net_payable_cents"] == 21480

    validate_error(
        api.appeal_claim(claim["id"], BILLER_SUBMITTER),
        ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value,
    )
    after = read_claim(ctx, claim["id"])
    assert after["status"] == "DENIED_FINAL"
    assert after["net_payable_cents"] == 0


def test_claim_preparation_is_refused_while_the_episode_is_still_active(api):
    """PRD §3.8: "The episode's `status` must read `SERVICE_PERIOD_CLOSED`; if
    it does not, the failure is reported as `ERR_SERVICE_PERIOD_OPEN` rather
    than as a generic invalid-state error — this is the one place where an
    episode-status requirement is deliberately taken out of the ordinary state
    check and evaluated later in the ladder."

    Design: Difficulty/cross_entity_state_dependency/claim_preparation_requires_episode_service_period_closed
    """
    ctx, ep, visit = setup_billable_episode(close_at=None)
    set_clock("2026-05-31T01:00:00Z")
    assert read_episode(ctx, ep["episode_id"])["status"] == "ACTIVE"

    validate_error(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        ApiErrorId.ERR_SERVICE_PERIOD_OPEN.value,
    )
    assert read_episode(ctx, ep["episode_id"])["claim_id"] is None


def test_claim_preparation_succeeds_once_the_service_period_closes(api):
    """PRD §3.8: "Closing the service period is a `ProgramAdmin` action
    available only from `ACTIVE`, and only once the current instant is strictly
    after the end of `service_period_end_date`."
    PRD §3.8: "A prepared claim records `service_period_start_date` and
    `service_period_end_date` copied from the episode, `patient_id` and
    `payer_id` copied from the episode, the `visit_id` it bills,
    `prepared_by_user_id` from the acting `X-User-ID`, `status` `PREPARED`,
    `appeal_count` 0, `readmission_flagged` false, `denial_reason_code` null,
    `submitted_by_user_id` null and `paid_at` null. The episode's `claim_id` is
    set to point at it."

    Design: Difficulty/cross_entity_state_dependency/claim_preparation_requires_episode_service_period_closed
    """
    ctx, ep, visit = setup_billable_episode(close_at=None)
    set_clock("2026-05-31T01:00:00Z")
    validate_error(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        ApiErrorId.ERR_SERVICE_PERIOD_OPEN.value,
    )

    closed = close_service_period(ctx, ep, at=None)
    assert closed["status"] == "SERVICE_PERIOD_CLOSED"

    claim = validate_success(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        201,
    )
    assert claim["status"] == "PREPARED"
    assert str(claim["payable_code"]) == "99496"
    assert claim["net_payable_cents"] == 21480
    assert claim["appeal_count"] == 0
    assert claim["readmission_flagged"] is False
    assert claim["denial_reason_code"] is None
    assert claim["submitted_by_user_id"] is None
    assert claim["paid_at"] is None
    assert claim["prepared_by_user_id"] == "bill-prep-1"
    assert read_episode(ctx, ep["episode_id"])["claim_id"] == claim["id"]


def test_payer_multiplier_and_zero_coinsurance_money_path(api):
    """PRD §3.8: "First, `allowed_cents` is `base_rate_cents` multiplied by the
    payer's `tcm_rate_multiplier`, rounded half up to whole cents."
    PRD §3.8: "Third, `net_before_withhold_cents` is `allowed_cents` minus
    `coinsurance_cents`. Fourth, the quality withhold rate is selected from that
    third figure: `withhold_pct` is 0.03 when `net_before_withhold_cents` is at
    least 20000 cents, and 0.01 when it is below 20000 cents."

    Design: Corner/calculations/payer_multiplier_and_zero_coinsurance_money_path
    """
    ctx, ep, visit = setup_billable_episode(
        payer_overrides={
            "name": "Value Plan",
            "tcm_covered": True,
            "tcm_rate_multiplier": 0.9,
            "coinsurance_rate": 0.0,
        }
    )
    claim = prepare_claim(ctx, ep, visit["id"])
    assert str(claim["payable_code"]) == "99496"
    assert claim["payable_variant"] == "FULL"
    assert_claim_money(
        claim,
        base_rate_cents=27680,
        allowed_cents=24912,
        coinsurance_cents=0,
        net_before_withhold_cents=24912,
        withhold_pct=0.03,
        withhold_cents=747,
        net_payable_cents=24165,
    )


def test_moderate_required_episode_never_upgrades_to_the_high_code(api):
    """PRD §3.8: "There is no upgrade above the tier the episode required: an
    episode whose required complexity was only `MODERATE_COMPLEXITY` still bills
    `99495` even if the visit happened on day 3 with the entire high-complexity
    element set documented."
    PRD §3.8: "A `99495` claim yields 20450, 4090, 16360, a withhold rate of
    0.01, 164 and a net payable of 16196 cents."

    Design: Corner/calculations/moderate_required_episode_never_upgrades_to_99496
    """
    ctx, ep, visit = setup_billable_episode(tier="MODERATE")
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["required_visit_complexity"] == "MODERATE_COMPLEXITY"
    assert episode["visit_due_date"] == "2026-05-15"
    assert visit["achieved_complexity"] == "HIGH_COMPLEXITY"
    assert visit["deadline_status"] == "MET"

    claim = prepare_claim(ctx, ep, visit["id"])
    assert str(claim["payable_code"]) == "99495"
    assert claim["payable_variant"] == "FULL"
    assert_claim_money(
        claim,
        allowed_cents=20450,
        coinsurance_cents=4090,
        net_before_withhold_cents=16360,
        withhold_pct=0.01,
        withhold_cents=164,
        net_payable_cents=16196,
    )


def test_claim_without_attested_documentation_is_not_billable(api):
    """PRD §3.8: "The episode must have a visit whose `encounter_status` is
    `COMPLETED` and whose `documentation_status` is `ATTESTED` or `AMENDED`,
    since without attested documentation there is no billable service; the
    absence of one is `ERR_CLAIM_NOT_BILLABLE`."

    Design: Corner/validations/claim_preparation_without_attested_visit_is_not_billable
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )
    close_service_period(ctx, ep, at="2026-05-31T01:00:00Z")

    validate_error(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        ApiErrorId.ERR_CLAIM_NOT_BILLABLE.value,
    )
    assert read_episode(ctx, ep["episode_id"])["claim_id"] is None
    _, meta = validate_paginated(
        api.list_claims(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 0


def test_claim_rejected_when_the_visit_landed_after_day_fourteen(api):
    """PRD §3.8: "The visit's `completed_at` must be on or before the end of
    `discharge_date` plus 14 days, because no TCM code covers a later encounter;
    a later visit is `ERR_VISIT_WINDOW_MISSED`."

    Design: Corner/validations/claim_rejected_when_visit_landed_after_day_14
    """
    ctx, ep, visit = setup_billable_episode(
        visit_start="2026-05-21T15:00:00Z",
        visit_end="2026-05-21T16:00:00Z",
        visit_completed_at="2026-05-21T16:00:00Z",
    )
    validate_error(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        ApiErrorId.ERR_VISIT_WINDOW_MISSED.value,
    )
    assert read_visit(ctx, visit["id"])["deadline_status"] == "MISSED"
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["visit_timely"] is False
    assert episode["claim_id"] is None


def test_claim_submission_is_rejected_when_contact_was_untimely(api):
    """PRD §3.8: "and `contact_timely` must be true, or it is refused with
    `ERR_CONTACT_NOT_TIMELY` — an episode where the programme never reached the
    patient inside the window cannot be billed no matter how good the visit
    was."

    Design: Corner/validations/claim_submit_rejected_when_contact_was_untimely
    """
    ctx, ep, visit, claim = setup_prepared_claim(
        contact_at="2026-05-06T10:00:00Z",
        visit_start="2026-05-06T15:00:00Z",
        visit_end="2026-05-06T16:00:00Z",
        visit_completed_at="2026-05-06T16:00:00Z",
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )
    assert_same_instant(
        episode["successful_contact_at"], "2026-05-06T10:00:00.000Z", "successful_contact_at"
    )
    assert episode["contact_timely"] is False
    assert claim["status"] == "PREPARED"
    assert str(claim["payable_code"]) == "99496"
    assert claim["net_payable_cents"] == 21480

    validate_error(
        api.submit_claim(claim["id"], BILLER_SUBMITTER),
        ApiErrorId.ERR_CONTACT_NOT_TIMELY.value,
    )
    after = read_claim(ctx, claim["id"])
    assert after["status"] == "PREPARED"
    assert after["submitted_by_user_id"] is None


def test_second_claim_for_the_same_service_period_is_a_duplicate(api):
    """PRD §3.8: "And exactly one billable TCM claim may exist per patient per
    service period: if another claim for the same `patient_id` covers an
    overlapping service period and is not `VOIDED`, preparation is refused with
    `ERR_DUPLICATE_TCM_CLAIM`."

    Design: Corner/validations/second_claim_for_same_service_period_is_duplicate
    """
    ctx, ep, visit, claim = setup_prepared_claim()
    validate_error(
        api.prepare_claim(ep["episode_id"], {"visit_id": visit["id"]}, BILLER_PREPARER),
        ApiErrorId.ERR_DUPLICATE_TCM_CLAIM.value,
    )
    _, meta = validate_paginated(
        api.list_claims(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 1
    assert claim["service_period_start_date"] == "2026-05-01"
    assert claim["service_period_end_date"] == "2026-05-30"


def test_visit_from_another_episode_is_a_link_mismatch(api):
    """PRD §3.8: "A `BillingSpecialist` prepares the episode's single claim by
    naming the `visit_id` of the attested face-to-face visit being billed. That
    visit must belong to this episode, or the request fails with
    `ERR_ENTITY_LINK_MISMATCH`."
    PRD §2.10: "A body-supplied reference belongs to the parent named in the
    path — otherwise `ERR_ENTITY_LINK_MISMATCH` (409). The two loci are claim
    preparation (`visit_id` from another episode) and handoff proposal
    (`to_navigator_id` equal to the episode's current navigator)."

    Design: Corner/validations/claim_visit_id_from_another_episode_is_link_mismatch
    """
    ctx = setup_program()
    ep_a = setup_episode(ctx)
    ep_b = setup_episode(ctx)
    visit_b = book_visit(ctx, ep_b)

    validate_error(
        api.prepare_claim(
            ep_a["episode_id"], {"visit_id": visit_b["id"]}, BILLER_PREPARER
        ),
        ApiErrorId.ERR_ENTITY_LINK_MISMATCH.value,
    )
    assert read_episode(ctx, ep_a["episode_id"])["claim_id"] is None


def test_paid_claim_drives_the_episode_to_billed_and_freezes_the_records(api):
    """PRD §3.8: "`PAID` stamps `paid_at` with the current instant and drives
    the episode `SERVICE_PERIOD_CLOSED → BILLED`, which then triggers the freeze
    evaluation — and that evaluation now succeeds, because no non-terminal claim
    remains."
    PRD §2.7: "Once an episode is frozen, every subsequent mutation aimed at
    that episode or at any `RiskAssessment`, `ContactAttempt`, `TcmVisit`,
    `MedReconciliation`, `MedDiscrepancy`, `Barrier`, `RedFlag`,
    `HandoffRequest` or `TcmClaim` beneath it is rejected with
    `ERR_EPISODE_RECORDS_FROZEN` and HTTP 409."

    Design: Corner/state_machines/claim_paid_drives_episode_to_billed_and_freezes_the_record_set
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, ADMIN)
    )
    assert paid["status"] == "PAID"
    assert_same_instant(paid["paid_at"], "2026-05-31T01:00:00.000Z", "paid_at")
    assert paid["net_payable_cents"] == 21480

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "BILLED"
    assert episode["record_posture"] == "FROZEN"

    validate_error(
        api.raise_barrier(
            ep["episode_id"],
            {"barrier_type": "TRANSPORTATION", "description": "late request"},
            ep["nav_headers"],
        ),
        ApiErrorId.ERR_EPISODE_RECORDS_FROZEN.value,
    )
    _, meta = validate_paginated(
        api.list_barriers(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 0
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 0
    assert read_patient(ctx, ep["patient_id"])["open_episode_count"] == 0


def test_claim_submitter_must_differ_from_the_preparer(api):
    """PRD §3.8: "And the submitter must not be the preparer."
    PRD §2.1: "A claim may not be submitted by the same `X-User-ID` that
    prepared it, and a red flag may not be resolved by the same `X-User-ID` that
    raised it. Either violation yields `ERR_SEGREGATION_OF_DUTIES` with HTTP
    403."

    Design: Corner/rbac/claim_submitter_cannot_be_the_preparer
    """
    ctx, ep, _visit, claim = setup_prepared_claim()
    validate_error(
        api.submit_claim(claim["id"], BILLER_PREPARER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert read_claim(ctx, claim["id"])["status"] == "PREPARED"

    submitted = validate_success(api.submit_claim(claim["id"], BILLER_SUBMITTER))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "bill-sub-1"
    assert submitted["prepared_by_user_id"] == "bill-prep-1"


def test_care_navigator_cannot_adjudicate_a_claim(api):
    """PRD §2.1: "If both headers are present but the supplied role is not one
    of the roles authorised for the endpoint being called, the request is
    rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §2.1: "`ProgramAdmin` is programme operations. It owns configuration
    (facilities, payers, navigators, the holiday calendar), the logical clock,
    the operational sweep, service-period closure, administrative episode
    closure, readmission recording and retraction, claim adjudication and claim
    voiding, and it is the only role that may close a barrier as waived."

    Design: Corner/rbac/care_navigator_cannot_adjudicate_a_claim
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    validate_error(
        api.adjudicate_claim(
            claim["id"],
            {"outcome": "PAID"},
            make_care_navigator_headers(ctx["navigator_id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    after = read_claim(ctx, claim["id"])
    assert after["status"] == "SUBMITTED"
    assert after["paid_at"] is None
    assert read_episode(ctx, ep["episode_id"])["status"] == "SERVICE_PERIOD_CLOSED"
