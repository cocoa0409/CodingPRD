"""State-machine breadth: the unbounded legal-review loop, the referential
gates guarding each lifecycle edge, the terminal statuses that refuse a repeat
call, and the two independent dimensions of a separated employment row."""

import pytest

from test_helpers import (
    CLOCK_CLOSE_DAY,
    COUNSEL,
    FINANCE,
    LEAD,
    SETTLER,
    ApiErrorId,
    accept_offer,
    add_doctor_with_offer,
    advance_to_diligence,
    api_client,
    assert_affiliation,
    assert_doctor_employment,
    assert_earnout_pool_ledger,
    assert_earnout_tranche,
    assert_migration_batch,
    assert_practice,
    assert_service_agreement,
    add_service_line_item,
    build_clinical_director,
    build_closed_deal,
    build_closed_deal_two_doctors,
    build_closed_deal_with_contract,
    build_deal_in_draft,
    build_scheduled_batch,
    build_settled_tranche,
    claw_back_tranche,
    create_payer_contract,
    create_payer_enrollment,
    create_service_agreement,
    create_service_line_item_payload,
    approve_enrollment,
    get_success_data,
    make_dentist_headers,
    project_tranche,
    read_affiliation,
    read_conversion_vendor,
    read_employment,
    read_migration_batch,
    read_payer_contract,
    read_payer_enrollment,
    read_practice,
    read_service_agreement,
    schedule_cutover_payload,
    separate_employment,
    sign_deal,
    stage_batch,
    submit_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DATE = "2026-09-01T00:00:00Z"
NON_COMPETE_END = "2028-09-01T00:00:00Z"
BATCH_WINDOW = ("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"
MEASUREMENT_START = "2026-09-01T00:00:00Z"
MEASUREMENT_END = "2027-09-01T00:00:00Z"
RESERVE_CLOCK = "2027-03-01T00:00:00Z"
SETTLE_CLOCK = "2027-09-02T00:00:00Z"
AWARDED_CENTS = 41_921_250

SECOND_DOCTOR = {
    "full_name": "Beto Alvarez",
    "npi": "1710000002",
    "license_number": "IL-DDS-5521",
    "license_state": "IL",
    "is_seller_owner": False,
}
SECOND_EMPLOYMENT = {
    "base_salary_monthly_cents": 1_700_000,
    "collections_pct_bps": 2800,
    "comp_model": "ANNUAL_TRUE_UP",
    "legacy_annual_comp_cents": 23_000_000,
    "post_close_term_months": 36,
    "non_compete_months": 18,
    "non_compete_radius_miles": 8,
}


def test_rejected_scope_returns_to_draft_and_accumulates_findings():
    """PRD §3.2: "Review may reject the scope, which returns the agreement `LEGAL_REVIEW → DRAFT` and adds the request's `finding_count` to the cumulative `scope_findings_count`, optionally recording a `finding_note`."
    PRD §3.2: "This revision loop has no round limit: an agreement may be resubmitted and rejected any number of times, with `review_round` counting submissions and `scope_findings_count` accumulating findings across all of them."

    Design: Corner/state_machines/service_agreement_reject_scope_returns_to_draft_and_records_findings
    """
    ctx = build_deal_in_draft(clock_utc=CLOCK_CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    agreement = create_service_agreement(ctx["practice_id"])
    add_service_line_item(agreement["id"])
    in_review = get_success_data(
        api_client.submit_legal_review(agreement["id"], COUNSEL)
    )
    assert in_review["status"] == "LEGAL_REVIEW"
    assert in_review["review_round"] == 1

    rejected = get_success_data(
        api_client.reject_scope(
            agreement["id"],
            {
                "finding_count": 2,
                "finding_note": "clinical supervision language must be struck",
            },
            COUNSEL,
        )
    )
    assert_service_agreement(rejected)
    assert rejected["status"] == "DRAFT"
    assert rejected["scope_findings_count"] == 2
    assert rejected["review_round"] == 1

    resubmitted = get_success_data(
        api_client.submit_legal_review(agreement["id"], COUNSEL)
    )
    assert resubmitted["status"] == "LEGAL_REVIEW"
    assert resubmitted["review_round"] == 2
    assert resubmitted["scope_findings_count"] == 2
    assert resubmitted["line_item_count"] == 1
    assert resubmitted["effective_date"] is None


def test_diligence_cannot_open_on_a_file_with_no_target_practice():
    """PRD §3.1: "Opening diligence moves the affiliation `DRAFT → DILIGENCE` and stamps `diligence_opened_at` from the logical clock; it requires the file to be in `DRAFT` and requires `practice_count` to be at least one, since diligence cannot open on a deal with nothing to buy — an empty file is refused with `ERR_NO_TARGET_PRACTICE`."
    PRD §2.11: "The affiliation has at least one target practice — `ERR_NO_TARGET_PRACTICE` (422)."

    Design: Corner/state_machines/advance_diligence_without_practice_rejected
    """
    affiliation = get_success_data(
        api_client.create_affiliation(
            {
                "seller_group_name": "Elm Ridge Dental Group",
                "purchase_price_cents": 450_000_000,
                "earnout_pool_cents": 90_000_000,
                "baseline_ebitda_cents": 90_000_000,
                "baseline_net_collections_cents": 400_000_000,
                "post_close_doctor_term_months": 36,
            },
            COUNSEL,
        )
    )
    assert affiliation["practice_count"] == 0

    validate_error(
        api_client.advance_diligence(affiliation["id"], COUNSEL),
        ApiErrorId.ERR_NO_TARGET_PRACTICE.value,
        422,
    )

    unchanged = read_affiliation(affiliation["id"])
    assert_affiliation(unchanged)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["diligence_opened_at"] is None
    assert unchanged["version"] == 1


def test_signature_needs_post_close_terms_on_the_table_at_every_practice():
    """PRD §3.1: "It requires that every practice of the affiliation have at least one employment row in `OFFERED` status, because the support organization will not sign for a practice with no post-close clinical coverage on the table; a practice without one blocks signature with `ERR_NO_POST_CLOSE_EMPLOYMENT`."
    PRD §2.11: "Every practice of the affiliation has post-close employment terms on the table — `ERR_NO_POST_CLOSE_EMPLOYMENT` (422)."

    Design: Corner/state_machines/sign_without_offered_employment_rejected
    """
    affiliation = get_success_data(
        api_client.create_affiliation(
            {
                "seller_group_name": "Elm Ridge Dental Group",
                "purchase_price_cents": 450_000_000,
                "earnout_pool_cents": 90_000_000,
                "baseline_ebitda_cents": 90_000_000,
                "baseline_net_collections_cents": 400_000_000,
                "post_close_doctor_term_months": 36,
            },
            COUNSEL,
        )
    )
    vendor = get_success_data(
        api_client.create_conversion_vendor(
            {"name": "ChartBridge Conversions", "max_concurrent_windows": 3}, LEAD
        )
    )
    get_success_data(
        api_client.create_practice(
            {
                "affiliation_id": affiliation["id"],
                "conversion_vendor_id": vendor["id"],
                "name": "Elm Street Dental",
                "state_code": "IL",
                "charts_total_expected": 5000,
            },
            LEAD,
        )
    )
    advance_to_diligence(affiliation["id"])

    validate_error(
        api_client.sign_affiliation(
            affiliation["id"], COUNSEL, {"signature_note": "premature"}
        ),
        ApiErrorId.ERR_NO_POST_CLOSE_EMPLOYMENT.value,
        422,
    )

    unchanged = read_affiliation(affiliation["id"])
    assert unchanged["status"] == "DILIGENCE"
    assert unchanged["signed_date"] is None


def test_close_is_blocked_until_every_practice_holds_a_live_agreement():
    """PRD §3.3: "It requires the file to be in `SIGNED` status, and it requires that every practice of the affiliation already hold at least one management services agreement in `EFFECTIVE` status — no support services may be rendered and no conversion begun before the agreement is live — so a practice without one blocks the close with `ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE`."
    PRD §3.3: "The cascade then runs in five hops, and every hop after the first is caused by the state change the previous hop wrote rather than by the close call itself."

    Design: Corner/state_machines/close_without_effective_service_agreement_rejected
    """
    ctx = build_deal_in_draft(clock_utc=CLOCK_CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])

    validate_error(
        api_client.close_affiliation(ctx["affiliation_id"], LEAD),
        ApiErrorId.ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE.value,
        422,
    )

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["status"] == "SIGNED"
    assert affiliation["close_date"] is None
    assert affiliation["earnout_measurement_state"] == "NOT_OPEN"

    practice = read_practice(ctx["practice_id"])
    assert practice["affiliation_status"] == "PENDING"
    assert practice["integration_posture"] == "PRE_CLOSE"
    assert read_employment(ctx["employment_id"])["employment_status"] == "OFFERED"


def test_a_projected_tranche_allocates_nothing_from_the_pool():
    """PRD §3.9: "A new tranche opens in `PROJECTED` with no `variant_applied`, with `reserved_cents`, `awarded_cents` and `clawed_back_cents` all at zero, with every reported, annualized, final and derived figure still empty, and with neither `reserved_by_user_id` nor `settled_by_user_id` recorded; it increments the affiliation's `version` by one."

    Design: Corner/state_machines/earnout_tranche_starts_in_projected_state
    """
    ctx = build_closed_deal()
    tranche = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y1",
        measurement_start=MEASUREMENT_START,
        measurement_end=MEASUREMENT_END,
    )

    assert_earnout_tranche(tranche)
    assert tranche["status"] == "PROJECTED"
    assert tranche["version"] == 1
    assert tranche["reserved_cents"] == 0
    assert tranche["awarded_cents"] == 0
    assert tranche["clawed_back_cents"] == 0
    assert tranche["variant_applied"] is None
    assert tranche["lag_holdback_cents"] is None
    assert tranche["growth_bps"] is None
    assert tranche["multiple_bps"] is None
    assert tranche["reserved_by_user_id"] is None
    assert tranche["settled_by_user_id"] is None

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert_earnout_pool_ledger(affiliation)


def test_a_second_close_is_refused_and_the_counters_are_not_doubled():
    """PRD §2.11: "Affiliation status permits the operation — `ERR_INVALID_AFFILIATION_STATE` (409)."
    PRD §3.3: "Rows with `offer_accepted` true move `OFFERED → ACTIVE`, have `comp_effective_date` set to the affiliation's `close_date`, increase that practice's `active_doctor_count` by one, and have their own `version` incremented by one."

    Design: Corner/state_machines/closing_an_already_closed_affiliation_returns_invalid_state
    """
    ctx = build_closed_deal()

    validate_error(
        api_client.close_affiliation(ctx["affiliation_id"], LEAD),
        ApiErrorId.ERR_INVALID_AFFILIATION_STATE.value,
        409,
    )

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["status"] == "CLOSED"
    assert affiliation["close_date"] == CLOSE_DATE

    practice = read_practice(ctx["practice_id"])
    assert practice["active_doctor_count"] == 1

    employment = read_employment(ctx["employment_id"])
    assert employment["employment_status"] == "ACTIVE"
    assert employment["comp_effective_date"] == CLOSE_DATE


def test_an_approved_enrollment_cannot_be_submitted_again():
    """PRD §3.6: "`APPROVED` is terminal for an enrollment; a `SUSPENDED` enrollment is resumable only by a posture recompute and never by a client call, so acting on one is refused with `ERR_INVALID_ENROLLMENT_STATE`."
    PRD §3.6: "On `APPROVE` the enrollment moves `SUBMITTED → APPROVED`, `decided_at` is stamped from the logical clock, the practice's `pending_credentialing_count` decreases by one, the contract's `enrollment_open_count` decreases by one, the employment's credentialing dimension and the practice's posture are recomputed, and the enrollment's `version` increments by one."

    Design: Corner/state_machines/approved_enrollment_cannot_be_resubmitted
    """
    ctx = build_closed_deal()
    contract = create_payer_contract(ctx["practice_id"])
    enrollment = create_payer_enrollment(
        contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    submit_enrollment(enrollment["id"])
    approved = approve_enrollment(enrollment["id"])
    assert approved["status"] == "APPROVED"

    validate_error(
        api_client.submit_enrollment(enrollment["id"], LEAD),
        ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value,
        409,
    )

    unchanged = read_payer_enrollment(enrollment["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["submission_round"] == 1

    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 0
    assert read_payer_contract(contract["id"])["enrollment_open_count"] == 0
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "APPROVED"


def test_a_clawed_back_tranche_refuses_a_second_settlement():
    """PRD §3.9: "**Clawing back** a settled tranche is the compensating operation of the whole fiscal chain."
    PRD §3.9: "`clawed_back_cents` is set to the current `awarded_cents`, which is then reset to zero; the affiliation's `earnout_settled_cents` falls by `clawed_back_cents` and its `earnout_unallocated_cents` rises by exactly the same amount, restoring the pool identity with zero drift; the tranche moves `SETTLED → CLAWED_BACK`, which is terminal; and both the tranche's and the affiliation's `version` increment by one."

    Design: Corner/state_machines/clawed_back_tranche_cannot_be_settled_again
    """
    ctx = build_closed_deal()
    settled = build_settled_tranche(
        ctx,
        reserve_clock=RESERVE_CLOCK,
        settle_clock=SETTLE_CLOCK,
        reported_net_collections_cents=210_000_000,
        reported_expenses_cents=151_000_000,
        final_net_collections_cents=420_000_000,
        final_expenses_cents=285_000_000,
        measurement_start=MEASUREMENT_START,
        measurement_end=MEASUREMENT_END,
    )
    assert settled["status"] == "SETTLED"
    assert settled["awarded_cents"] == AWARDED_CENTS

    clawed_back = claw_back_tranche(settled["id"], "restatement")
    assert clawed_back["status"] == "CLAWED_BACK"

    validate_error(
        api_client.settle_tranche(
            settled["id"],
            {
                "final_net_collections_cents": 420_000_000,
                "final_expenses_cents": 285_000_000,
            },
            SETTLER,
        ),
        ApiErrorId.ERR_INVALID_TRANCHE_STATE.value,
        409,
    )

    tranche = get_success_data(
        api_client.get_earnout_tranche(settled["id"], FINANCE)
    )
    assert tranche["status"] == "CLAWED_BACK"
    assert tranche["awarded_cents"] == 0
    assert tranche["clawed_back_cents"] == AWARDED_CENTS

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert affiliation["earnout_settled_cents"] == 0
    assert_earnout_pool_ledger(affiliation)


def test_a_lapsed_offer_can_never_be_separated():
    """PRD §3.4: "`employment_status` is the contractual dimension and runs `OFFERED`, `ACTIVE`, `LAPSED`, `SEPARATED`, with `LAPSED` and `SEPARATED` terminal."
    PRD §3.4: "Either the integration lead or the departing dentist may perform it, it requires `employment_status` to be `ACTIVE`, and it supplies a `separation_reason` of `VOLUNTARY`, `TERMINATED_FOR_CAUSE` or `NON_RENEWAL`."

    Design: Corner/state_machines/lapsed_employment_cannot_be_separated
    """
    ctx = build_closed_deal_two_doctors(
        second_doctor=SECOND_DOCTOR,
        second_employment=SECOND_EMPLOYMENT,
        accept_second=False,
    )
    lapsed = read_employment(ctx["second_employment_id"])
    assert lapsed["employment_status"] == "LAPSED"

    validate_error(
        api_client.separate_employment(
            ctx["second_employment_id"], {"separation_reason": "VOLUNTARY"}, LEAD
        ),
        ApiErrorId.ERR_INVALID_EMPLOYMENT_STATE.value,
        409,
    )

    still_lapsed = read_employment(ctx["second_employment_id"])
    assert_doctor_employment(still_lapsed)
    assert still_lapsed["employment_status"] == "LAPSED"
    assert still_lapsed["separation_date"] is None
    assert still_lapsed["non_compete_end_date"] is None

    practice = read_practice(ctx["practice_id"])
    assert practice["active_doctor_count"] == 1
    assert practice["integration_posture"] == "STABILIZING"


def test_pre_close_acceptance_records_consent_without_activating():
    """PRD §3.4: "When the affiliation is `SIGNED`, acceptance only records consent: `offer_accepted` becomes true, `employment_status` deliberately stays at `OFFERED` — the self-transition `OFFERED` → `OFFERED` — and activation is deferred to the close cascade of §3.3, which will find `offer_accepted` true at hop three."
    PRD §3.4: "In both branches the row must be in `OFFERED` with `offer_accepted` still false; an already-accepted offer is refused."

    Design: Corner/state_machines/accept_offer_before_close_keeps_offered_status
    """
    ctx = build_deal_in_draft(clock_utc=CLOCK_CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])

    accepted = accept_offer(ctx["employment_id"], ctx["doctor_id"])
    assert accepted["offer_accepted"] is True
    assert accepted["employment_status"] == "OFFERED"
    assert accepted["comp_effective_date"] is None
    assert accepted["credentialing_status"] == "PENDING"
    assert read_practice(ctx["practice_id"])["active_doctor_count"] == 0

    validate_error(
        api_client.accept_offer(
            ctx["employment_id"], make_dentist_headers(ctx["doctor_id"])
        ),
        ApiErrorId.ERR_INVALID_EMPLOYMENT_STATE.value,
        409,
    )

    unchanged = read_employment(ctx["employment_id"])
    assert unchanged["employment_status"] == "OFFERED"
    assert unchanged["offer_accepted"] is True
    assert unchanged["credentialing_status"] == "PENDING"


def test_custody_and_covenant_advance_without_touching_the_contract_status():
    """PRD §3.4: "The clinical director, as custodian of patient records after a departure, **transfers records custody**, optionally recording a `custodian_note`; this requires `employment_status` to be `SEPARATED` and `records_custody_state` to be `TRANSFER_PENDING`, and it advances `records_custody_state` to `TRANSFERRED` while leaving `employment_status` at `SEPARATED` and `credentialing_status` untouched."
    PRD §3.4: "On success, `non_compete_enforcement_state` moves `PENDING → ENFORCED` and the row's `version` increments by one."

    Design: Corner/state_machines/custody_and_non_compete_dimensions_advance_independently
    """
    ctx = build_closed_deal()
    director, director_headers = build_clinical_director(
        full_name="Dana Whitfield", npi="1710000009", license_number="IL-DDS-9001"
    )
    separate_employment(ctx["employment_id"])

    transferred = get_success_data(
        api_client.transfer_records_custody(
            ctx["employment_id"],
            director_headers,
            {"custodian_note": "charts moved to the DSO custodian of record"},
        )
    )
    assert transferred["records_custody_state"] == "TRANSFERRED"
    assert transferred["employment_status"] == "SEPARATED"
    assert transferred["non_compete_enforcement_state"] == "PENDING"

    enforced = get_success_data(
        api_client.enforce_non_compete(
            ctx["employment_id"], COUNSEL, {"enforcement_note": "10-mile radius asserted"}
        )
    )
    assert enforced["non_compete_enforcement_state"] == "ENFORCED"
    assert enforced["records_custody_state"] == "TRANSFERRED"
    assert enforced["employment_status"] == "SEPARATED"
    assert enforced["non_compete_end_date"] == NON_COMPETE_END
    assert enforced["separation_date"] == CLOSE_DATE
    assert director["license_state"] == "IL"

    practice = read_practice(ctx["practice_id"])
    assert practice["integration_posture"] == "FROZEN"
    assert practice["clinical_coverage_gap"] is True


@pytest.fixture
def frozen_practice_with_a_replacement_offer():
    """A frozen practice holding a held batch, a suspended enrollment and an offer."""
    ctx = build_closed_deal_with_contract()
    ctx["enrollment_id"] = ctx["cascade_enrollment_id"]
    submit_enrollment(ctx["enrollment_id"])
    batch = build_scheduled_batch(
        ctx["practice_id"], *BATCH_WINDOW, batch_label="CHART-WAVE-1", records_total=5000
    )
    ctx["batch_id"] = batch["id"]
    add_doctor_with_offer(
        ctx,
        ctx["practice_id"],
        doctor=SECOND_DOCTOR,
        employment=SECOND_EMPLOYMENT,
        key="replacement",
    )
    separate_employment(ctx["employment_id"])
    return ctx


def test_the_replacement_hire_activates_immediately_and_thaws_the_practice(
    frozen_practice_with_a_replacement_offer
):
    """PRD §3.4: "When the affiliation is already `CLOSED` — the post-close replacement-hire branch of the same operation — acceptance activates the employment immediately: `offer_accepted` becomes true, `employment_status` moves `OFFERED → ACTIVE`, `comp_effective_date` is stamped from the logical clock rather than from the close date, the practice's `active_doctor_count` increases by one, the practice's posture is recomputed, and both the employment row's `version` and the practice's `version` increment by one."
    PRD §3.4: "That posture recomputation is what releases a frozen practice: bringing `active_doctor_count` back to one or more moves a practice `FROZEN → STABILIZING`, sets `clinical_coverage_gap` back to false, returns every batch of that practice from `HELD` to `SCHEDULED` and every enrollment from `SUSPENDED` back to `SUBMITTED`, and — when no other practice of the affiliation remains frozen — moves the affiliation's `earnout_measurement_state` from `SUSPENDED` back to `OPEN`."

    Design: Corner/state_machines/replacement_doctor_activation_releases_held_batch_and_suspended_enrollment
    """
    ctx = frozen_practice_with_a_replacement_offer
    assert read_practice(ctx["practice_id"])["integration_posture"] == "FROZEN"
    assert read_migration_batch(ctx["batch_id"])["status"] == "HELD"
    assert read_payer_enrollment(ctx["enrollment_id"])["status"] == "SUSPENDED"
    assert read_conversion_vendor(ctx["vendor_id"])["active_window_count"] == 0

    activated = accept_offer(
        ctx["replacement_employment_id"], ctx["replacement_doctor_id"]
    )
    assert activated["employment_status"] == "ACTIVE"
    assert activated["comp_effective_date"] == CLOSE_DATE

    practice = read_practice(ctx["practice_id"])
    assert_practice(practice)
    assert practice["active_doctor_count"] == 1
    assert practice["integration_posture"] == "STABILIZING"
    assert practice["clinical_coverage_gap"] is False
    assert practice["pending_credentialing_count"] == 1

    batch = read_migration_batch(ctx["batch_id"])
    assert batch["status"] == "SCHEDULED"
    assert batch["cutover_start_at"] == BATCH_WINDOW[0]
    assert read_conversion_vendor(ctx["vendor_id"])["active_window_count"] == 1

    assert read_payer_enrollment(ctx["enrollment_id"])["status"] == "SUBMITTED"
    assert read_payer_contract(ctx["contract_id"])["enrollment_open_count"] == 1
    assert read_affiliation(ctx["affiliation_id"])["earnout_measurement_state"] == "OPEN"
    assert read_employment(ctx["employment_id"])["employment_status"] == "SEPARATED"


def test_a_superseded_batch_can_no_longer_reserve_a_window():
    """PRD §3.5: "Staging is exclusive per practice: every earlier batch of the same practice still in `STAGED` status is moved `STAGED → SUPERSEDED`, processed in `created_at` ascending order, with each superseded batch's `version` incremented by one, and the practice's own `version` incremented by one."
    PRD §3.5: "`SUPERSEDED` is terminal, as is `RECONCILED`."

    Design: Corner/state_machines/superseded_batch_cannot_schedule_cutover
    """
    ctx = build_closed_deal()
    first = stage_batch(ctx["practice_id"], batch_label="WAVE-1", records_total=5000)
    second = stage_batch(ctx["practice_id"], batch_label="WAVE-2", records_total=5000)

    assert read_migration_batch(first["id"])["status"] == "SUPERSEDED"
    assert read_migration_batch(second["id"])["status"] == "STAGED"

    validate_error(
        api_client.schedule_cutover(
            first["id"], schedule_cutover_payload(*BATCH_WINDOW), LEAD
        ),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value,
        409,
    )

    unscheduled = read_migration_batch(first["id"])
    assert_migration_batch(unscheduled)
    assert unscheduled["cutover_start_at"] is None
    assert read_conversion_vendor(ctx["vendor_id"])["active_window_count"] == 0


def test_a_live_agreement_refuses_a_further_scope_line():
    """PRD §3.2: "Scope may only be edited in `DRAFT`, so line-item additions and submission both require `DRAFT`, while rejection and making the agreement effective both require `LEGAL_REVIEW`; a request against the wrong status is refused with `ERR_INVALID_AGREEMENT_STATE`, and because `EFFECTIVE` is terminal, no scope edit is possible once the agreement is live."

    Design: Corner/state_machines/effective_service_agreement_rejects_additional_line_item
    """
    ctx = build_closed_deal()

    validate_error(
        api_client.add_service_line_item(
            ctx["agreement_id"],
            create_service_line_item_payload(
                service_code="SVC-HR-01", service_domain="HR", monthly_fee_cents=90_000
            ),
            COUNSEL,
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )

    agreement = read_service_agreement(ctx["agreement_id"])
    assert agreement["status"] == "EFFECTIVE"
    assert agreement["line_item_count"] == 1

    lines, meta = validate_paginated(
        api_client.list_service_line_items(ctx["agreement_id"], COUNSEL)
    )
    assert meta["total_count"] == 1
    assert len(lines) == 1
    assert validate_success(
        api_client.get_service_agreement(ctx["agreement_id"], COUNSEL)
    )["effective_date"] == CLOSE_DATE
