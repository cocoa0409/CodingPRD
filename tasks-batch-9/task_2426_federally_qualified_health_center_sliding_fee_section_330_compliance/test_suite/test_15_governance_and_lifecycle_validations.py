"""Governance, baseline-lock, reporting and adjudication-order validations."""

from test_helpers import (
    ADMIN,
    OFFICER,
    REP,
    TWO_BAND_LADDER,
    VERIFIER,
    ApiErrorId,
    adopt_schedule,
    api_client,
    create_board_member_payload,
    create_corrective_action_plan_payload,
    create_scope_change_request_payload,
    create_service_site_payload,
    decide_scope_change_request_payload,
    lock_scope_baseline,
    make_board_chair_headers,
    refresh_finding,
    refresh_health_center,
    refresh_patient,
    refresh_scope_change_request,
    refresh_service_site,
    refresh_uds_report,
    resubmit_income_verification_payload,
    same_instant,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_board_seat,
    setup_boot_core,
    setup_draft_fee_schedule,
    setup_draft_uds_report,
    setup_grantee,
    setup_income_verification,
    setup_open_finding,
    setup_patient,
    setup_proposed_site,
    setup_scope_change_request_under_review,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification_payload,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def _annex(ctx):
    return setup_proposed_site(
        ctx,
        site_name="Corner Annex Clinic",
        address_line="2 Corner Ave",
        weekly_service_hours=20,
    )


def _get_verification(income_verification_id):
    return validate_success(
        api_client.get_income_verification(income_verification_id, REP)
    )


def test_an_add_service_request_carrying_a_site_target_is_refused():
    """The pairing is read off `request_type`, not off whichever target resolves.

    PRD 2.12: "9. The polymorphic target pairing agrees with `request_type`, on
    change-in-scope-request drafting and on change-in-scope-request submission —
    otherwise `ERR_SCOPE_TARGET_MISMATCH` (422)."

    PRD 3.8: "an `ADD_SITE` or `REMOVE_SITE` request must carry `target_site_id` and
    must leave `target_service_definition_id` null, while an `ADD_SERVICE` or
    `REMOVE_SERVICE` request must carry `target_service_definition_id` and must leave
    `target_site_id` null. A mismatch is rejected with `ERR_SCOPE_TARGET_MISMATCH`"

    Design: Corner/validations/scope_change_request_type_and_target_pairing_rejected
    """
    ctx = setup_boot_core()
    annex = _annex(ctx)

    validate_error(
        api_client.create_scope_change_request(
            ctx["health_center_id"],
            create_scope_change_request_payload(
                request_type="ADD_SERVICE",
                target_site_id=annex["id"],
                justification="Mispaired request under test",
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_SCOPE_TARGET_MISMATCH.value,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_scope_change_requests(
            OFFICER, {"health_center_id": ctx["health_center_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "the mispaired request was not stored even though the named site resolves"
    )


def test_a_plan_promising_completion_after_the_due_date_is_refused():
    """The deadline is derived, and the draft is measured against the derived value.

    PRD 3.8: "has `cap_due_at` computed as its `created_at` plus `cap_due_days` days,
    evaluated on the logical clock."

    PRD 3.8: "The committed date must not be after the parent finding's `cap_due_at`,
    or the draft is rejected with `ERR_CAP_TARGET_AFTER_DUE`."

    Design: Corner/validations/corrective_action_plan_target_after_cap_due_rejected
    """
    ctx = setup_boot_core()
    finding = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )
    assert same_instant(finding["cap_due_at"]) == "2026-08-31T00:00:00Z", (
        "30 days after the 2026-08-01 clock is 2026-08-31, got "
        f"{finding['cap_due_at']}"
    )

    validate_error(
        api_client.create_corrective_action_plan(
            finding["id"],
            create_corrective_action_plan_payload(
                narrative="Recruit three patient board members",
                milestone_count=3,
                target_completion_date="2026-09-15T00:00:00Z",
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_CAP_TARGET_AFTER_DUE.value,
        422,
    )

    assert refresh_finding(finding["id"])["status"] == "OPEN", (
        "the refused draft never drove the finding to CAP_SUBMITTED"
    )
    _, meta = validate_paginated(
        api_client.list_finding_corrective_action_plans(finding["id"], OFFICER)
    )
    assert meta["total_count"] == 0


def test_a_locked_baseline_closes_both_the_shortcut_and_a_second_lock():
    """One error identifier answers two different attempts to reopen the baseline.

    PRD 3.1: "Baseline admission is only available while `scope_baseline_locked` is
    false; once the baseline is locked, `in_initial_scope` set to true is rejected with
    `ERR_SCOPE_BASELINE_LOCKED`, and sites may only reach scope through an approved
    change-in-scope request."

    PRD 3.1: "It is a once-only action: a second attempt to lock an already-locked
    baseline is rejected with `ERR_SCOPE_BASELINE_LOCKED`."

    Design: Corner/validations/baseline_scope_addition_after_lock_rejected
    """
    ctx = setup_boot_core()
    locked = lock_scope_baseline(ctx)
    version_at_lock = locked["version"]

    validate_error(
        api_client.create_service_site(
            ctx["health_center_id"],
            create_service_site_payload(
                site_name="Late Baseline Clinic",
                site_type="SERVICE_DELIVERY",
                address_line="9 Corner Ave",
                weekly_service_hours=10,
                in_initial_scope=True,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_SCOPE_BASELINE_LOCKED.value,
        409,
    )
    validate_error(
        api_client.lock_scope_baseline(ctx["health_center_id"], ADMIN),
        ApiErrorId.ERR_SCOPE_BASELINE_LOCKED.value,
        409,
    )

    unchanged = refresh_health_center(ctx["health_center_id"])
    assert unchanged["scope_baseline_locked"] is True
    assert unchanged["version"] == version_at_lock, (
        "neither refusal took a version increment with it, got "
        f"{unchanged['version']} against {version_at_lock}"
    )
    _, meta = validate_paginated(
        api_client.list_health_center_service_sites(ctx["health_center_id"], ADMIN)
    )
    assert meta["total_count"] == 1, "the refused site was not stored at all"


def test_an_uncomputed_report_cannot_be_submitted():
    """The submission precondition has its own error rather than the generic one.

    PRD 3.9: "It is permitted only when `computed_at` is not null and
    `included_measure_count` is at least 1; an uncomputed report, or one whose every
    measure was excluded for a zero denominator, is rejected with
    `ERR_UDS_REPORT_NOT_COMPUTED`."

    Design: Corner/validations/uds_report_submit_before_compute_rejected
    """
    ctx = setup_boot_core()
    report = setup_draft_uds_report(ctx, reporting_year=2026)

    validate_error(
        api_client.submit_uds_report(report["id"], OFFICER),
        ApiErrorId.ERR_UDS_REPORT_NOT_COMPUTED.value,
        409,
    )

    unchanged = refresh_uds_report(report["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["computed_at"] is None
    assert unchanged["submitted_by_user_id"] is None, (
        "the refused submission recorded no submitting officer"
    )
    assert unchanged["composite_quality_rate_pct"] is None


def test_a_one_member_board_cannot_approve_a_scope_change():
    """Reviewability and approvability are separate: the review succeeded, the approval does not.

    PRD 3.8: "The grantee's `governance_posture` must be `GOVERNANCE_COMPLIANT` when
    evaluated on the pre-transition snapshot described in section 3.2, or the decision
    reports `ERR_GOVERNANCE_DEFICIENT`."

    PRD 3.2: "the seated board count is at least 3"

    Design: Corner/validations/governance_deficient_board_cannot_approve_a_scope_change
    """
    ctx = setup_boot_core()
    annex = _annex(ctx)
    under_review = setup_scope_change_request_under_review(
        ctx, request_type="ADD_SITE", target_site_id=annex["id"]
    )
    assert under_review["status"] == "UNDER_REVIEW", (
        "a deficient board may still take the request under review"
    )
    assert (
        refresh_health_center(ctx["health_center_id"])["governance_posture"]
        == "GOVERNANCE_DEFICIENT"
    )

    validate_error(
        api_client.decide_scope_change_request(
            under_review["id"],
            decide_scope_change_request_payload(
                "APPROVE", decision_note="Annex approved by a one-member board"
            ),
            make_board_chair_headers(ctx["chair_id"]),
        ),
        ApiErrorId.ERR_GOVERNANCE_DEFICIENT.value,
        409,
    )

    still_under_review = refresh_scope_change_request(under_review["id"])
    assert still_under_review["status"] == "UNDER_REVIEW"
    assert still_under_review["decision_note"] is None, (
        "the refused decision stored no note"
    )
    assert refresh_service_site(annex["id"])["status"] == "PROPOSED", (
        "the refused approval fired none of the cascade"
    )


def test_the_twenty_sixth_seat_is_refused_by_the_roster_ceiling():
    """Every seat is individually valid; only the collective count is out of bounds.

    PRD 3.2: "There is also a hard roster ceiling — a seating that would push
    `seated_board_count` above twenty-five seats is rejected with
    `ERR_BOARD_SEAT_LIMIT`."

    Design: Corner/validations/twenty_sixth_board_seat_rejected_by_the_aggregate_cap
    """
    ctx = setup_boot_core()
    for seat_number in range(2, 26):
        validate_success(
            api_client.create_board_member(
                ctx["health_center_id"],
                create_board_member_payload(
                    seat_number=seat_number,
                    seat_type="NON_PATIENT",
                    expertise_category="COMMUNITY",
                    term_start="2026-01-01T00:00:00Z",
                    term_end="2028-12-31T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
    summary = validate_success(
        api_client.get_governance_summary(ctx["health_center_id"], OFFICER)
    )
    assert summary["seated_board_count"] == 25, (
        f"the roster is full at the ceiling, got {summary['seated_board_count']}"
    )

    validate_error(
        api_client.create_board_member(
            ctx["health_center_id"],
            create_board_member_payload(
                seat_number=26,
                seat_type="NON_PATIENT",
                expertise_category="COMMUNITY",
                term_start="2026-01-01T00:00:00Z",
                term_end="2028-12-31T00:00:00Z",
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_BOARD_SEAT_LIMIT.value,
        409,
    )

    _, meta = validate_paginated(
        api_client.list_board_members(
            OFFICER, {"health_center_id": ctx["health_center_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 25
    assert refresh_health_center(ctx["health_center_id"])["seated_board_count"] == 25


def test_the_intake_year_guideline_is_required_even_when_the_schedule_year_is_published():
    """Two guideline years are needed, and the calendar year of the visit is one of them.

    PRD 3.4: "The **intake-year** variant is the one that drives reporting. Its year is
    simply the UTC calendar year of the verification's `effective_date`."

    PRD 3.4: "If the poverty guideline row for *either* required year has not been
    published, the verification cannot be verified and the request is rejected with
    `ERR_POVERTY_GUIDELINE_MISSING`."

    Design: Corner/validations/verify_without_the_intake_year_poverty_guideline_rejected
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )
    setup_baseline_site(grantee["id"], site_name="Corner Clinic")
    setup_baseline_service(grantee["id"])
    chair = setup_board_seat(grantee["id"])
    draft = setup_draft_fee_schedule(
        grantee["id"],
        fpg_year=2026,
        effective_start="2026-01-01T00:00:00Z",
        effective_end="2028-01-01T00:00:00Z",
        nominal_fee_cents=2500,
        ladder=TWO_BAND_LADDER,
    )
    adopt_schedule(grantee["id"], draft["fee_schedule"]["id"], chair["id"])
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=1000000,
        household_size=1,
        documentation_type="TAX_RETURN",
        effective_date="2027-02-01T00:00:00Z",
    )

    validate_error(
        api_client.verify_income_verification(
            verification["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        ),
        ApiErrorId.ERR_POVERTY_GUIDELINE_MISSING.value,
        422,
    )

    unchanged = _get_verification(verification["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["fpg_percent"] is None
    assert unchanged["uds_fpg_percent"] is None, (
        "the intake-year percentage is exactly the one that could not be computed"
    )
    assert unchanged["assigned_discount_tier_id"] is None


def test_the_missing_schedule_answers_before_the_missing_guideline():
    """Both rules are violated, and the lower rung is the one that speaks.

    PRD 2.12: "When more than one rule would reject a request, the rule with the
    **lowest priority number wins** and its error is the one returned."

    PRD 3.4: "If no adopted schedule covers `effective_date` on the half-open
    convention, the adjudication is rejected with `ERR_NO_EFFECTIVE_FEE_SCHEDULE`."

    Design: Corner/validations/fee_schedule_selector_runs_before_the_guideline_lookup
    """
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )
    setup_baseline_site(grantee["id"], site_name="Corner Clinic")
    setup_baseline_service(grantee["id"])
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=1000000,
        household_size=1,
        documentation_type="TAX_RETURN",
        effective_date="2026-03-01T00:00:00Z",
    )

    validate_error(
        api_client.verify_income_verification(
            verification["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        ),
        ApiErrorId.ERR_NO_EFFECTIVE_FEE_SCHEDULE.value,
        409,
    )

    unchanged = _get_verification(verification["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["assigned_discount_tier_id"] is None


def test_a_refused_packet_may_be_cycled_but_never_approved():
    """The refusal rule is conditional on the decision, so insufficiency is still open.

    PRD 3.4: "Choosing `MARK_INSUFFICIENT` moves the row `SUBMITTED →
    INSUFFICIENT_DOCUMENTATION`. It stores the supplied `insufficiency_reason` and
    records the adjudicating operator in `verified_by_user_id`"

    PRD 3.4: "The transition is `INSUFFICIENT_DOCUMENTATION → SUBMITTED`; it increments
    `resubmit_round` by one, clears both `insufficiency_reason` and
    `verified_by_user_id`, and re-records `submitted_by_user_id` as the acting operator."

    Design: Corner/validations/refused_documentation_blocks_verify_but_not_mark_insufficient
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

    insufficient = validate_success(
        api_client.verify_income_verification(
            refused["id"],
            verify_income_verification_payload(
                "MARK_INSUFFICIENT",
                insufficiency_reason="Patient declined to supply documentation",
            ),
            VERIFIER,
        )
    )
    assert insufficient["status"] == "INSUFFICIENT_DOCUMENTATION", (
        "a refusal to document may still be marked insufficient, got "
        f"{insufficient['status']}"
    )
    assert insufficient["resubmit_round"] == 0

    resubmitted = validate_success(
        api_client.resubmit_income_verification(
            refused["id"], resubmit_income_verification_payload("REFUSED"), REP
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmit_round"] == 1

    validate_error(
        api_client.verify_income_verification(
            refused["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        ),
        ApiErrorId.ERR_DOCUMENTATION_REFUSED.value,
        422,
    )

    final = _get_verification(refused["id"])
    assert final["status"] == "SUBMITTED", (
        "the cycle is traversable but the approval never lands"
    )
    assert final["resubmit_round"] == 1
    assert refresh_patient(patient["id"])["sliding_fee_status"] == "UNVERIFIED"
