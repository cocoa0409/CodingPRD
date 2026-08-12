"""Applications and appeals: screening gates, claim/review cycle, reviewer
ownership, appeal windows, segregation of duties, the overturn cascade, and
validation-priority resolution (PRD §2.7, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_application,
    assert_appeal,
    fixtures as fx,
    make_appeals_officer_headers,
    make_case_worker_headers,
    make_patient_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _rejected_screening_ctx():
    """Program + patient whose screening went SUBMITTED -> REJECTED."""
    ctx = fx.setup_program_with_period()
    patient = fx.create_patient_record()
    screening = fx.setup_submitted_screening(patient["id"], ctx["program"]["id"])
    rejected = validate_success(api_client.decide_screening(
        screening["id"], {"decision": "REJECTED",
                          "rejection_reason": "documents not reviewed favorably"}, fx.CW))
    ctx.update({"patient": patient, "screening": rejected})
    return ctx


def test_application_with_rejected_screening_rejected():
    """PRD §3.3: "The screening must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`
    otherwise) and still within its validity window (`ERR_SCREENING_STALE`
    otherwise)."

    Design: Difficulty/cross_entity_state_dependency/application_requires_verified_screening
    """
    ctx = _rejected_screening_ctx()
    resp = api_client.create_application(
        {"patient_id": ctx["patient"]["id"], "program_id": ctx["program"]["id"],
         "screening_id": ctx["screening"]["id"]},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_VERIFIED, expected_status=409)


def test_rejected_screening_application_persists_nothing():
    """PRD §3.3: "The screening must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`
    otherwise) and still within its validity window (`ERR_SCREENING_STALE`
    otherwise)." A rejected creation persists no record to list.

    Design: Difficulty/cross_entity_state_dependency/application_requires_verified_screening
    """
    ctx = _rejected_screening_ctx()
    resp = api_client.create_application(
        {"patient_id": ctx["patient"]["id"], "program_id": ctx["program"]["id"],
         "screening_id": ctx["screening"]["id"]},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_VERIFIED)
    apps, meta = validate_paginated(api_client.list_applications(
        fx.CW, params={"patient_id": ctx["patient"]["id"]}))
    assert apps == [] and meta["total_count"] == 0, "no Application row is persisted"


def _stale_foreign_screening_ctx():
    """Patient B's screening VERIFIED on 2026-05-01; clock advanced past its
    validity with no sweep; patient A exists and references B's screening."""
    ctx = fx.setup_program_with_period()
    patient_a = fx.create_patient_record(full_name="Mia Moth")
    patient_b = fx.create_patient_record(full_name="Noa Noll")
    screening_b = fx.setup_verified_screening(patient_b["id"], ctx["program"]["id"])
    fx.set_clock("2026-08-05T00:00:00Z")  # past 2026-07-30 = verified + 90d; no sweep
    ctx.update({"patient_a": patient_a, "patient_b": patient_b, "screening_b": screening_b})
    return ctx


def test_stale_screening_reported_before_mismatch():
    """PRD §2.7: "When a single request would fail several rules, the failure the
    client observes is determined by a fixed priority cascade; lower tiers are
    evaluated first, and HTTP status does not disambiguate within a tier." — with
    "9. **Temporal windows.** Screening freshness, renewal and appeal windows,
    period geometry (`ERR_SCREENING_STALE`, `ERR_OUTSIDE_RENEWAL_WINDOW`,
    `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_BUDGET_PERIOD_OVERLAP`)." evaluated before
    "11. **Cross-reference agreement.** Screening-to-application (or
    screening-to-enrollment) patient and program agreement, and prescriber
    resolvability for provider-destination shipments (`ERR_SCREENING_MISMATCH`,
    `ERR_PRESCRIBER_REQUIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_stale_screening
    """
    ctx = _stale_foreign_screening_ctx()
    resp = api_client.create_application(
        {"patient_id": ctx["patient_a"]["id"], "program_id": ctx["program"]["id"],
         "screening_id": ctx["screening_b"]["id"]},
        make_patient_headers(ctx["patient_a"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_STALE, expected_status=409)


def test_stale_screening_rejection_persists_no_application():
    """PRD §3.3: "The screening must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`
    otherwise) and still within its validity window (`ERR_SCREENING_STALE`
    otherwise)." A rejected creation persists no record to list.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_stale_screening
    """
    ctx = _stale_foreign_screening_ctx()
    api_client.create_application(
        {"patient_id": ctx["patient_a"]["id"], "program_id": ctx["program"]["id"],
         "screening_id": ctx["screening_b"]["id"]},
        make_patient_headers(ctx["patient_a"]["id"]))
    apps, meta = validate_paginated(api_client.list_applications(
        fx.CW, params={"patient_id": ctx["patient_a"]["id"]}))
    assert apps == [] and meta["total_count"] == 0


def test_second_claim_rejected_reviewer_unchanged():
    """PRD §3.3: "A `CaseWorker` claims a `SUBMITTED` application — any other
    state draws `ERR_APPLICATION_NOT_SUBMITTED` — moving it to `UNDER_REVIEW`
    and recording their own `X-User-ID` as `reviewer_id`."

    Design: Corner/state_machines/application_claim_twice_rejected
    """
    ctx = fx.setup_under_review_application()
    resp = api_client.claim_application(
        ctx["application"]["id"], make_case_worker_headers("cw_2"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED, expected_status=409)
    current = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert current["reviewer_id"] == ctx["reviewer"], "the first claim's reviewer is unchanged"


def test_resubmit_without_info_request_rejected():
    """PRD §3.3: "The owning patient answers by resubmitting — anyone else draws
    `ERR_OWNERSHIP_VIOLATION`, and a non-`MORE_INFO_REQUESTED` state draws
    `ERR_APPLICATION_NOT_AWAITING_INFO`"

    Design: Corner/state_machines/application_resubmit_wrong_state_rejected
    """
    ctx = fx.setup_under_review_application()
    resp = api_client.resubmit_application(
        ctx["application"]["id"], {"resubmission_note": "premature"},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_AWAITING_INFO, expected_status=409)
    current = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert current["status"] == "UNDER_REVIEW"


def test_decision_by_non_reviewer_rejected():
    """PRD §3.3: "From that moment the review belongs to that caseworker: only
    the recorded reviewer may request more information or render a decision, and
    anyone else is rejected with `ERR_REVIEWER_MISMATCH` (HTTP 403)."

    Design: Corner/state_machines/application_decision_by_other_caseworker_returns_403
    """
    ctx = fx.setup_under_review_application()
    resp = api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers("cw_2"))
    validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH, expected_status=403)
    current = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert current["status"] == "UNDER_REVIEW"
    assert current["reviewer_id"] == ctx["reviewer"]


def test_info_request_cycle_returns_to_under_review():
    """PRD §3.3: "Requesting information requires the application be
    `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`), stores the supplied
    `info_request_note`, and moves the application to `MORE_INFO_REQUESTED`." and
    "This request-and-resubmit cycle may repeat indefinitely."

    Design: Difficulty/non_linear_state_machine/application_info_request_cycle
    """
    ctx = fx.setup_under_review_application()
    info = validate_success(api_client.request_info(
        ctx["application"]["id"], {"info_request_note": "need clearer income proof"},
        make_case_worker_headers(ctx["reviewer"])))
    assert info["status"] == "MORE_INFO_REQUESTED"

    back = validate_success(api_client.resubmit_application(
        ctx["application"]["id"], {"resubmission_note": "re-uploaded W2"},
        make_patient_headers(ctx["patient"]["id"])))
    assert back["status"] == "UNDER_REVIEW", "the cycle returns to UNDER_REVIEW"

    decided = validate_success(api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"])))
    assert decided["status"] == "APPROVED", "the cycle traversed before branching to APPROVED"


def test_info_request_cycle_retains_reviewer():
    """PRD §3.3: "The owning patient answers by resubmitting — anyone else draws
    `ERR_OWNERSHIP_VIOLATION`, and a non-`MORE_INFO_REQUESTED` state draws
    `ERR_APPLICATION_NOT_AWAITING_INFO`; an optional `resubmission_note` may
    accompany the answer — which returns the application to `UNDER_REVIEW` with
    the same `reviewer_id` retained."

    Design: Difficulty/non_linear_state_machine/application_info_request_cycle
    """
    ctx = fx.setup_under_review_application()
    validate_success(api_client.request_info(
        ctx["application"]["id"], {"info_request_note": "need clearer income proof"},
        make_case_worker_headers(ctx["reviewer"])))
    back = validate_success(api_client.resubmit_application(
        ctx["application"]["id"], {"resubmission_note": "re-uploaded W2"},
        make_patient_headers(ctx["patient"]["id"])))
    assert back["reviewer_id"] == ctx["reviewer"], "reviewer retained across the loop"

    decided = validate_success(api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"])))
    assert decided["enrollment_id"], "enrollment_id is filled in on APPROVED"


def test_appeal_on_under_review_application_rejected():
    """PRD §3.4: "The application must be `DENIED` — appealing anything else is
    rejected with `ERR_APPLICATION_NOT_DENIED` — only one `FILED` appeal may
    exist per application (`ERR_APPEAL_ALREADY_EXISTS`), and the filing must fall
    inside the appeal window of §2.5, else `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/state_machines/appeal_on_non_denied_application_rejected
    """
    ctx = fx.setup_under_review_application()
    resp = api_client.create_appeal(
        ctx["application"]["id"], {"grounds": "premature appeal"},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DENIED, expected_status=409)
    appeals, meta = validate_paginated(api_client.list_appeals(
        fx.CW, params={"application_id": ctx["application"]["id"]}))
    assert appeals == [] and meta["total_count"] == 0, "no Appeal persisted"


def test_decided_appeal_rejects_second_decision():
    """PRD §3.4: "Deciding a non-`FILED` appeal is rejected with
    `ERR_APPEAL_NOT_FILED`."

    Design: Corner/state_machines/appeal_decision_after_upheld_rejected
    """
    ctx = fx.setup_filed_appeal()
    upheld = validate_success(api_client.decide_appeal(
        ctx["appeal"]["id"], {"decision": "UPHELD", "decision_reason": "denial stands"},
        make_appeals_officer_headers("ao_1")))
    assert upheld["status"] == "UPHELD"

    resp = api_client.decide_appeal(
        ctx["appeal"]["id"], {"decision": "OVERTURNED", "decision_reason": "second thoughts"},
        make_appeals_officer_headers("ao_1"))
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FILED, expected_status=409)
    current = validate_success(api_client.get_appeal(ctx["appeal"]["id"], fx.CW))
    assert current["status"] == "UPHELD"
    application = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert application["status"] == "DENIED", "the upheld denial stands"


def _two_denied_applications():
    """One patient, two applications, both DENIED on 2026-05-10."""
    ctx = fx.setup_denied_application(clock="2026-05-10T00:00:00Z",
                                      decision_reason="incomplete")
    second = validate_success(api_client.create_application(
        {"patient_id": ctx["patient"]["id"], "program_id": ctx["program"]["id"],
         "screening_id": ctx["screening"]["id"]},
        make_patient_headers(ctx["patient"]["id"])), expected_status=201)
    claimed = validate_success(api_client.claim_application(
        second["id"], make_case_worker_headers(ctx["reviewer"])))
    denied2 = validate_success(api_client.decide_application(
        second["id"], {"decision": "DENIED", "decision_reason": "incomplete again"},
        make_case_worker_headers(ctx["reviewer"])))
    ctx["application_b"] = denied2
    return ctx


def test_appeal_on_last_window_day_succeeds():
    """PRD §2.5: "An appeal may be filed while today is on or before the
    application's `decided_at` date plus the program's `appeal_window_days`."

    Design: Difficulty/boundary_precision_check/appeal_window_day30_inclusive
    """
    ctx = _two_denied_applications()
    fx.set_clock("2026-06-09T00:00:00Z")  # decided 2026-05-10 + 30 days, inclusive
    appeal = validate_success(api_client.create_appeal(
        ctx["application"]["id"], {"grounds": "filed on last allowed day"},
        make_patient_headers(ctx["patient"]["id"])), expected_status=201)
    assert_appeal(appeal)
    assert appeal["status"] == "FILED"


def test_appeal_one_day_past_window_rejected():
    """PRD §2.5: "An appeal may be filed while today is on or before the
    application's `decided_at` date plus the program's `appeal_window_days`."
    PRD §3.4: "the filing must fall inside the appeal window of §2.5, else
    `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/appeal_window_day30_inclusive
    """
    ctx = _two_denied_applications()
    fx.set_clock("2026-06-10T00:00:00Z")  # one day past the inclusive boundary
    resp = api_client.create_appeal(
        ctx["application_b"]["id"], {"grounds": "filed one day late"},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, expected_status=409)


def test_appeal_decision_by_original_reviewer_segregated():
    """PRD §3.4: "An `AppealsOfficer` decides the appeal, and the system enforces
    segregation of duties at the identity level: the deciding officer's
    `X-User-ID` must differ from the application's `reviewer_id`, or the decision
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/appeal_decision_by_original_reviewer_returns_403
    """
    ctx = fx.setup_filed_appeal()
    resp = api_client.decide_appeal(
        ctx["appeal"]["id"],
        {"decision": "UPHELD", "decision_reason": "reviewing own denial"},
        make_appeals_officer_headers(ctx["reviewer"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    current = validate_success(api_client.get_appeal(ctx["appeal"]["id"], fx.CW))
    assert current["status"] == "FILED", "the segregated decision leaves the appeal FILED"

    decided = validate_success(api_client.decide_appeal(
        ctx["appeal"]["id"],
        {"decision": "UPHELD", "decision_reason": "independent review confirms"},
        make_appeals_officer_headers("ao_1")))
    assert decided["status"] == "UPHELD"
    assert decided["decided_by"] == "ao_1"


def test_appeal_overturn_approves_application():
    """PRD §3.4: "Only when every gate passes does the application move `DENIED →
    APPROVED` with `approved_via_appeal` set to true, an enrollment created and
    budget committed exactly as in a first-pass approval, and posture
    recomputed."

    Design: Difficulty/transitive_cascade/appeal_overturn_depth4_cascade
    """
    ctx = fx.setup_filed_appeal()
    decided = validate_success(api_client.decide_appeal(
        ctx["appeal"]["id"],
        {"decision": "OVERTURNED", "decision_reason": "documentation sufficient"},
        make_appeals_officer_headers("ao_1")))
    assert decided["status"] == "OVERTURNED"

    application = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert application["status"] == "APPROVED", "hop 1: the appeal moves the application"
    assert application["approved_via_appeal"] is True
    assert application["enrollment_id"], "hop 2: enrollment_id is filled in"


def test_appeal_overturn_creates_enrollment_and_commits_budget():
    """PRD §3.4: "An `OVERTURNED` decision triggers the deepest cascade in the
    system — appeal to application to enrollment to budget — and it is gated by
    exactly the approval precondition set of §3.3, re-evaluated fresh at
    appeal-decision time rather than inherited from the original review"

    Design: Difficulty/transitive_cascade/appeal_overturn_depth4_cascade
    """
    ctx = fx.setup_filed_appeal()
    validate_success(api_client.decide_appeal(
        ctx["appeal"]["id"],
        {"decision": "OVERTURNED", "decision_reason": "documentation sufficient"},
        make_appeals_officer_headers("ao_1")))
    application = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))

    enrollment = validate_success(api_client.get_enrollment(application["enrollment_id"], fx.CW))
    assert enrollment["status"] == "ACTIVE", "hop 2: the new enrollment starts ACTIVE"
    assert enrollment["benefit_cap_cents"] == 900000
    assert enrollment["start_date"] == "2026-05-01"
    assert enrollment["end_date"] == "2026-07-29", "start + 90 days - 1"

    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 900000, "hop 3: budget committed as in a first-pass approval"
    assert utilization["posture"] == "RESTRICTED", "hop 4: 900000/1000000 = 90.00 flips posture"


def test_approval_immediately_consistent():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.3: "the application's `decided_at` is set from the logical
    clock, its `enrollment_id` is filled in" and "The new enrollment starts
    `ACTIVE` with `disbursed_cents` zero and `remaining_units` equal to
    `cap_units`"

    Design: Corner/consistency_model/immediate_consistency_on_approval
    """
    ctx = fx.setup_under_review_application()
    decided = validate_success(api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"])))
    assert_application(decided)
    assert decided["status"] == "APPROVED"
    assert decided["enrollment_id"], "enrollment_id present in the same response"

    enrollment = validate_success(api_client.get_enrollment(decided["enrollment_id"], fx.CW))
    assert enrollment["status"] == "ACTIVE"
    assert enrollment["benefit_cap_cents"] == 900000
    assert enrollment["remaining_units"] == 100
    assert enrollment["start_date"] == "2026-05-01"
    assert enrollment["end_date"] == "2026-07-29"


def test_unclaimed_decision_reports_state_error_over_exhaustion():
    """PRD §2.7: "When a single request would fail several rules, the failure the
    client observes is determined by a fixed priority cascade; lower tiers are
    evaluated first" — "7. **Source-state legality.** The entity is in the state
    the transition requires (the family of `ERR_*_NOT_*` state errors)." precedes
    "12. **Fiscal gates.** Posture and budget-sufficiency gates, in their own
    fixed internal order described in §3.3."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_unclaimed_decision
    """
    ctx = fx.setup_second_patient_application(first_allocated_cents=900000,
                                              claim_second=False)
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["posture"] == "EXHAUSTED", "committed 900000 of 900000 = 100.00"
    resp = api_client.decide_application(
        ctx["application_b"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW, expected_status=409)


def test_unclaimed_decision_leaves_application_submitted():
    """PRD §3.3: "Both approval and denial require the `UNDER_REVIEW` state with
    the matching reviewer" — a rejected decision mutates nothing.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_unclaimed_decision
    """
    ctx = fx.setup_second_patient_application(first_allocated_cents=900000,
                                              claim_second=False)
    api_client.decide_application(
        ctx["application_b"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    current = validate_success(api_client.get_application(ctx["application_b"]["id"], fx.CW))
    assert current["status"] == "SUBMITTED", "the failed decision leaves the state untouched"


def test_duplicate_benefit_reported_over_fiscal_failures():
    """PRD §2.7: "8. **Duplication and duty segregation.** Benefit-duplication
    and appeal-decider checks (`ERR_DUPLICATE_BENEFIT_ACTIVE`,
    `ERR_SEGREGATION_OF_DUTIES`)." precedes "12. **Fiscal gates.**"
    PRD §3.6: "The symmetric guard fires at PAP approval and appeal-overturn
    time: no copay card in `ACTIVE` status whose coverage interval intersects the
    new enrollment's `[start_date, end_date]` may exist for the patient and
    program, and no enrollment in `ACTIVE` or `SUSPENDED` status may exist for
    the pair other than the one named by `renewal_of_enrollment_id` — either
    violation is `ERR_DUPLICATE_BENEFIT_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_duplicate_benefit
    """
    ctx = fx.setup_second_patient_application(
        first_allocated_cents=1000000,
        second_screening_overrides={
            "income_basis": "PRIOR_YEAR", "prior_year_income_cents": 2000000,
            "insurance_status": "UNDERINSURED", "insurance_coverage_pct": "0.50"},
        claim_second=True,
        copay_card={"coverage_start": "2026-01-01", "coverage_end": "2026-12-31"})
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["posture"] == "RESTRICTED", (
        "900000 committed of 1000000 — the fiscal gate would also fail for a 450000 cap")
    resp = api_client.decide_application(
        ctx["application_b"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BENEFIT_ACTIVE, expected_status=409)


def test_duplicate_benefit_creates_no_enrollment():
    """PRD §3.6: "either violation is `ERR_DUPLICATE_BENEFIT_ACTIVE` (HTTP 409)"
    — a rejected approval persists no enrollment.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_duplicate_benefit
    """
    ctx = fx.setup_second_patient_application(
        first_allocated_cents=1000000,
        second_screening_overrides={
            "income_basis": "PRIOR_YEAR", "prior_year_income_cents": 2000000,
            "insurance_status": "UNDERINSURED", "insurance_coverage_pct": "0.50"},
        claim_second=True,
        copay_card={"coverage_start": "2026-01-01", "coverage_end": "2026-12-31"})
    api_client.decide_application(
        ctx["application_b"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    enrollments, meta = validate_paginated(api_client.list_enrollments(
        fx.CW, params={"patient_id": ctx["patient_b"]["id"]}))
    assert enrollments == [] and meta["total_count"] == 0, (
        "no Enrollment was created for the blocked patient")


def test_approval_blocked_by_overlapping_active_copay_card():
    """PRD §3.6: "The symmetric guard fires at PAP approval and appeal-overturn
    time: no copay card in `ACTIVE` status whose coverage interval intersects the
    new enrollment's `[start_date, end_date]` may exist for the patient and
    program, and no enrollment in `ACTIVE` or `SUSPENDED` status may exist for
    the pair other than the one named by `renewal_of_enrollment_id` — either
    violation is `ERR_DUPLICATE_BENEFIT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/approval_blocked_by_active_copay_card
    """
    ctx = fx.setup_under_review_application(allocated_cents=5000000)
    card = fx.create_copay_card_record(
        ctx["patient"]["id"], ctx["program"]["id"],
        coverage_start="2026-06-01", coverage_end="2026-06-30")
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["posture"] == "OPEN", "budget fully sufficient — the card is the only gate"

    resp = api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BENEFIT_ACTIVE, expected_status=409)
    current_card = validate_success(api_client.get_copay_card(card["id"], fx.CW))
    assert current_card["status"] == "ACTIVE"


def test_blocked_approval_leaves_card_active_and_no_enrollment():
    """PRD §3.6: "A `SUSPENDED` copay card, notably, does not block approval;
    only `ACTIVE` cards do." — the blocking ACTIVE card is untouched by the
    failed approval and no enrollment appears.

    Design: Difficulty/cross_entity_state_dependency/approval_blocked_by_active_copay_card
    """
    ctx = fx.setup_under_review_application(allocated_cents=5000000)
    fx.create_copay_card_record(
        ctx["patient"]["id"], ctx["program"]["id"],
        coverage_start="2026-06-01", coverage_end="2026-06-30")
    api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    enrollments, meta = validate_paginated(api_client.list_enrollments(
        fx.CW, params={"patient_id": ctx["patient"]["id"]}))
    assert enrollments == [] and meta["total_count"] == 0
    application = validate_success(api_client.get_application(ctx["application"]["id"], fx.CW))
    assert application["status"] == "UNDER_REVIEW", "the failed approval leaves the state untouched"
