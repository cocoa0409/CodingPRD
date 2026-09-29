"""Triggers offered from the wrong state, replays of completed ones, and the
reinstatement ladder.

Covers the four state dialects a permit, an application, a plan and an
enforcement action each speak, the absence of duplicate side effects behind a
refused replay, the untouched cascade behind a refused suspension, and the
one-rung-at-a-time climb back from SUSPENDED to ACTIVE.
"""
from test_helpers import (
    ApiErrorId,
    accept_use_report,
    appeal_action,
    authorize_guide,
    create_operating_plan,
    create_qualified_guide,
    decide_appeal,
    file_use_report,
    finalize_fee_assessment,
    issue_noncompliance_action,
    list_noncompliance_actions,
    list_permit_authorizations,
    pay_fee_assessment,
    read_allocation_summary,
    read_application,
    read_fee_assessment,
    read_needs_assessment_list,
    read_operating_plan,
    read_outfitter,
    read_permit,
    read_use_area,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    sole_fee_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]
LONG_TERM = {"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"}


def test_every_machine_answers_an_undeclared_trigger_in_its_own_state_dialect():
    """PRD §2.5: "**State preconditions** — the target record is in a status from which the
    requested transition is declared."
    PRD §3.8: "Suspension is also an officer's direct act, from `ACTIVE` only, supplying the
    `suspension_reason_code` — `OFFICER_ORDER` on this path — and the `suspended_until_date`."
    PRD §3.8: "A permit that is not `SUSPENDED` is refused with `ERR_PERMIT_NOT_OPERATIONAL`."
    PRD §3.2: "Both `DENIED` and `WITHDRAWN` are terminal, as is `PERMIT_ISSUED`."
    PRD §3.5: "Submission is available from `DRAFT` and from `REVISION_REQUESTED`, and any other
    status yields `ERR_INVALID_PLAN_STATE` (HTTP 409)."
    PRD §3.5: "A `PermitSpecialist` or an `AuthorizedOfficer` takes a `SUBMITTED` plan under review,
    moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` with the acting
    `X-User-ID`."
    PRD §3.8: "A pending appeal is then decided by an `AuthorizedOfficer` or `ProgramAdministrator`
    supplying a `decision` of `UPHELD` or `RESCINDED`; the action must be `APPEALED`, else
    `ERR_ACTION_NOT_APPEALABLE`"
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Corner/state_machines/an_undeclared_trigger_for_the_current_state_is_rejected
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]
    application_id = context["application"]["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = make_outfitter_representative_headers(outfitter_id)

    plan = create_operating_plan(permit_id, outfitter_id)
    assert plan["status"] == "DRAFT"
    action = issue_noncompliance_action(
        permit_id, severity="MINOR", action_type="WARNING",
        cited_provision="Clause 12(b) sanitation", cure_deadline_date="2027-08-01",
    )
    assert action["status"] == "ISSUED"

    permit_version = read_permit(permit_id)["version"]
    application_version = read_application(application_id)["version"]
    plan_version = read_operating_plan(plan["id"])["version"]

    validate_error(
        api_client.suspend_permit(
            permit_id,
            {"suspension_reason_code": "OFFICER_ORDER", "suspended_until_date": "2027-04-01"},
            OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
        409,
    )
    validate_error(
        api_client.reinstate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
        409,
    )
    validate_error(
        api_client.deny_permit_application(
            application_id, {"denial_reason_code": "TOO_LATE"}, OFFICER
        ),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
        409,
    )
    validate_error(
        api_client.withdraw_permit_application(application_id, holder),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
        409,
    )
    validate_error(
        api_client.start_operating_plan_review(plan["id"], SPECIALIST),
        ApiErrorId.ERR_INVALID_PLAN_STATE,
        409,
    )
    validate_error(
        api_client.approve_operating_plan(plan["id"], OFFICER),
        ApiErrorId.ERR_INVALID_PLAN_STATE,
        409,
    )
    validate_error(
        api_client.request_operating_plan_revision(
            plan["id"], {"deficiency_sections": ["stock_section"]}, SPECIALIST
        ),
        ApiErrorId.ERR_INVALID_PLAN_STATE,
        409,
    )
    validate_error(
        api_client.decide_noncompliance_appeal(
            action["id"], {"decision": "UPHELD"}, OFFICER
        ),
        ApiErrorId.ERR_ACTION_NOT_APPEALABLE,
        409,
    )

    permit = read_permit(permit_id)
    assert permit["administrative_status"] == "ISSUED"
    assert permit["suspension_count"] == 0
    assert permit["suspended_until_date"] is None
    assert permit["suspension_reason_code"] is None
    assert permit["version"] == permit_version

    assert read_application(application_id)["status"] == "PERMIT_ISSUED"
    assert read_application(application_id)["version"] == application_version

    closing_plan = read_operating_plan(plan["id"])
    assert closing_plan["status"] == "DRAFT"
    assert closing_plan["revision_round"] == 0
    assert closing_plan["reviewed_by_user_id"] is None
    assert closing_plan["approved_by_user_id"] is None
    assert closing_plan["deficiency_sections"] == []
    assert closing_plan["version"] == plan_version

    rows, meta = list_noncompliance_actions(permit_id)
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ISSUED"


def test_replaying_a_completed_trigger_is_refused_and_mints_no_second_permit():
    """PRD §3.1: "An `AuthorizedOfficer` or `ProgramAdministrator` publishes an assessment that is
    still `DRAFT`, moving it `DRAFT → PUBLISHED`; attempting to publish one that is already
    `PUBLISHED`, or one that has been `SUPERSEDED`, returns `ERR_INVALID_ASSESSMENT_STATE`."
    PRD §3.2: "The application must be `SUBMITTED`, else `ERR_INVALID_APPLICATION_STATE`."
    PRD §3.2: "Both `DENIED` and `WITHDRAWN` are terminal, as is `PERMIT_ISSUED`."
    PRD §2.7: "The governing invariant is that the allocatable total always equals the committed
    sum plus the pending sum plus the available remainder, for every area at every observable
    instant."
    PRD §2.7: "`demand_ratio` is the committed sum plus the pending sum, divided by the allocatable
    total, rounded half up to four decimal places."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Corner/state_machines/replaying_a_completed_trigger_is_refused_and_leaves_no_duplicate_side_effect
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    area_id = context["use_area"]["id"]
    application_id = context["application"]["id"]
    permit_id = context["permit"]["id"]
    assessment_id = context["needs_assessment"]["id"]
    holder = make_outfitter_representative_headers(context["outfitter"]["id"])

    rows, _meta = read_needs_assessment_list(area_id, params={"assessment_year": 2027})
    published = next(row for row in rows if row["id"] == assessment_id)
    assert published["status"] == "PUBLISHED"
    published_at_before = published["published_at"]
    assessment_version = published["version"]
    area_version = read_use_area(area_id)["version"]

    validate_error(
        api_client.publish_needs_assessment(assessment_id, OFFICER),
        ApiErrorId.ERR_INVALID_ASSESSMENT_STATE,
        409,
    )
    validate_error(
        api_client.submit_permit_application(application_id, holder),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
        409,
    )
    validate_error(
        api_client.screen_permit_application(application_id, SPECIALIST),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
        409,
    )
    validate_error(
        api_client.issue_permit(
            application_id,
            {
                "term_start_date": "2027-01-01",
                "term_end_date": "2029-12-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
        409,
    )

    permits, meta = validate_paginated(
        api_client.list_permits(SPECIALIST, params={"application_id": application_id})
    )
    assert meta["total_count"] == 1, "the replayed issuance minted no second permit"
    assert permits[0]["id"] == permit_id

    summary = read_allocation_summary(area_id)
    assert summary["allocatable_service_days"] == 900
    assert summary["committed_service_days"] == 200, "the replayed issuance committed nothing more"
    assert summary["pending_service_days"] == 0, "the replayed screen added no second hold"
    assert summary["available_service_days"] == 700
    assert summary["demand_ratio"] == 0.2222
    assert summary["allocation_posture"] == "OPEN"

    rows, _meta = read_needs_assessment_list(area_id, params={"assessment_year": 2027})
    still_published = next(row for row in rows if row["id"] == assessment_id)
    assert still_published["status"] == "PUBLISHED"
    assert still_published["published_at"] == published_at_before
    assert still_published["version"] == assessment_version
    assert read_use_area(area_id)["version"] == area_version
    assert read_application(application_id)["status"] == "PERMIT_ISSUED"


def test_a_refused_suspension_leaves_none_of_its_cascade_hops_behind():
    """PRD §3.8: "Suspension is also an officer's direct act, from `ACTIVE` only, supplying the
    `suspension_reason_code` — `OFFICER_ORDER` on this path — and the `suspended_until_date`."
    PRD §3.8: "Whatever the trigger, suspension increments `suspension_count`, stamps the date and
    reason, revokes every `AUTHORIZED` authorization on the permit with reason `PERMIT_SUSPENDED` so
    that `authorized_client_capacity_total` recomputes to 0, and then recomputes the holder's
    `active_permit_count` and re-derives its `status`, which falls from `PERMITTED` to `SUSPENDED`
    once the holder has no active permits left and at least one suspended one."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"
    PRD §3.6: "Its `authorized_client_capacity` is computed once, at this instant, as the lesser of
    the area's `max_clients_per_guide` and the guide's `base_client_capacity`, and is then
    **frozen**"

    Design: Corner/complexity_layers/a_rejected_cascade_trigger_writes_none_of_its_side_effects
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    guide = create_qualified_guide(outfitter_id, full_name="Rita Long")
    authorization = authorize_guide(permit_id, guide["id"], outfitter_id)
    assert authorization["authorized_client_capacity"] == 8

    before = read_permit(permit_id)
    assert before["administrative_status"] == "ISSUED"
    assert before["authorized_client_capacity_total"] == 8
    holder_before = read_outfitter(outfitter_id)
    assert holder_before["status"] == "PERMITTED"
    assert holder_before["active_permit_count"] == 0

    validate_error(
        api_client.suspend_permit(
            permit_id,
            {"suspension_reason_code": "OFFICER_ORDER", "suspended_until_date": "2027-03-01"},
            OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
        409,
    )

    after = read_permit(permit_id)
    assert after["administrative_status"] == "ISSUED"
    assert after["suspension_count"] == 0
    assert after["suspended_until_date"] is None
    assert after["suspension_reason_code"] is None
    assert after["authorized_client_capacity_total"] == 8, "hop 1 of the cascade did not run"
    assert after["version"] == before["version"]

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "AUTHORIZED", "hop 2 of the cascade did not run"
    assert rows[0]["revoked_at"] is None
    assert rows[0]["revocation_reason_code"] is None
    assert rows[0]["authorized_client_capacity"] == 8
    assert rows[0]["version"] == authorization["version"]

    holder_after = read_outfitter(outfitter_id)
    assert holder_after["status"] == "PERMITTED", "hop 3 of the cascade did not run"
    assert holder_after["active_permit_count"] == 0
    assert holder_after["prior_permit_count"] == 1
    assert holder_after["version"] == holder_before["version"]


def test_reinstatement_reveals_the_point_gate_then_the_fee_gate_one_rung_at_a_time():
    """PRD §3.8: "Reinstatement returns a `SUSPENDED` permit to `ACTIVE` and re-tests the operating
    conditions in order: an `APPROVED` operating plan must exist for the covering plan year, else
    `ERR_OPERATING_PLAN_NOT_APPROVED`; the `ACTIVE` certificate set must still cover the term without
    a hole, else `ERR_INSURANCE_COVERAGE_GAP`; `open_noncompliance_points` must be back below 12,
    else `ERR_POINTS_THRESHOLD_UNRESOLVED`; general-liability coverage must still be sufficient and
    endorsed, else `ERR_INSURANCE_COVERAGE_INSUFFICIENT`; an `ACTIVE` bond must still meet the
    requirement, else `ERR_BOND_INSUFFICIENT`; and no assessment may carry a balance, else
    `ERR_FEE_BALANCE_OUTSTANDING`."
    PRD §3.8: "The holder may cure it, supplying a `corrective_summary`, but only on or before the
    `cure_deadline_date` — the current logical date must be on or before that date inclusive, else
    `ERR_CURE_DEADLINE_PASSED`."
    PRD §3.8: "an appealed action **keeps contributing its points** while the appeal is pending,
    because appealing is not a stay."
    PRD §3.8: "`RESCINDED` drops the action's points, so the point total is recomputed downward and
    compliance re-derived."
    PRD §3.8: "Leaving `NONCOMPLIANT` never auto-reinstates, and entering or leaving `PROBATION`
    never changes `administrative_status` at all."
    PRD §3.8: "Reinstatement clears `suspended_until_date` and `suspension_reason_code` to null,
    leaves `suspension_count` at its accumulated value, re-derives the compliance signals and
    `compliance_status`, and recomputes the holder's `active_permit_count` and `status`. It does
    **not** restore the guide roster the suspension revoked; the holder must authorize guides again
    from scratch."
    PRD §3.7: "The payment adds to `paid_to_date_cents`, which only ever increases, and recomputes
    `balance_due_cents` and `credit_balance_cents`; the assessment moves to `PAID` only when
    `balance_due_cents` reaches zero, and a partial payment leaves the status untouched."
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or `insurance_current`
    is false, or `fee_delinquent` is true, the permit is on `PROBATION`."

    Design: Corner/errors/reinstatement_reveals_the_point_gate_then_the_fee_gate_and_a_late_cure_is_refused
    """
    context = setup_active_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = make_outfitter_representative_headers(outfitter_id)

    set_clock("2027-06-15T00:00:00Z")
    report = file_use_report(
        permit_id, outfitter_id,
        period_start_date="2027-05-15", period_end_date="2027-06-01",
        service_days_used=20, client_count=8,
        gross_revenue_cents=2_000_000, allowable_deductions_cents=0,
    )
    accept_use_report(report["id"])
    assessment = sole_fee_assessment(permit_id)
    assert assessment["status"] == "PROVISIONAL"
    assert assessment["balance_due_cents"] == 60_000

    issue_noncompliance_action(
        permit_id, severity="MAJOR", action_type="SUSPENSION",
        cited_provision="36 CFR 251.56(a)", cure_deadline_date="2027-07-31",
    )
    on_probation = read_permit(permit_id)
    assert on_probation["administrative_status"] == "ACTIVE"
    assert on_probation["compliance_status"] == "PROBATION"
    minor = issue_noncompliance_action(
        permit_id, severity="MINOR", action_type="WARNING",
        cited_provision="36 CFR 251.56(c)", cure_deadline_date="2027-07-31",
    )

    suspended = read_permit(permit_id)
    assert suspended["administrative_status"] == "SUSPENDED"
    assert suspended["compliance_status"] == "NONCOMPLIANT"
    assert suspended["open_noncompliance_points"] == 12
    assert suspended["suspension_count"] == 1
    assert suspended["suspension_reason_code"] == "POINTS_THRESHOLD"
    assert suspended["suspended_until_date"].startswith("2027-07-15")
    assert suspended["authorized_client_capacity_total"] == 0

    validate_error(
        api_client.reinstate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_POINTS_THRESHOLD_UNRESOLVED,
        409,
    )

    set_clock("2027-08-01T00:00:00Z")
    validate_error(
        api_client.cure_noncompliance_action(
            minor["id"], {"corrective_summary": "Signage replaced at the trailhead."}, holder
        ),
        ApiErrorId.ERR_CURE_DEADLINE_PASSED,
        422,
    )
    rows, _meta = list_noncompliance_actions(permit_id)
    assert [row["status"] for row in rows] == ["ISSUED", "ISSUED"], "the late cure changed nothing"
    assert read_permit(permit_id)["open_noncompliance_points"] == 12

    appealed = appeal_action(minor["id"], outfitter_id)
    assert appealed["status"] == "APPEALED"
    assert read_permit(permit_id)["open_noncompliance_points"] == 12

    validate_error(
        api_client.reinstate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_POINTS_THRESHOLD_UNRESOLVED,
        409,
    )

    assert decide_appeal(minor["id"], "RESCINDED")["status"] == "RESCINDED"
    rescinded = read_permit(permit_id)
    assert rescinded["open_noncompliance_points"] == 10
    assert rescinded["compliance_status"] == "PROBATION"
    assert rescinded["administrative_status"] == "SUSPENDED", "nothing auto-reinstates"

    validate_error(
        api_client.reinstate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_FEE_BALANCE_OUTSTANDING,
        409,
    )

    finalized = finalize_fee_assessment(assessment["id"])
    assert finalized["status"] == "FINAL"
    assert finalized["variant_applied"] == "FINAL_AGGREGATE"
    assert finalized["assessed_fee_cents"] == 60_000
    assert finalized["minimum_fee_applied"] is False
    assert finalized["balance_due_cents"] == 60_000

    paid = pay_fee_assessment(assessment["id"], outfitter_id, 60_000)
    assert paid["status"] == "PAID"
    assert paid["paid_to_date_cents"] == 60_000
    assert paid["balance_due_cents"] == 0
    settled = read_permit(permit_id)
    assert settled["fee_delinquent"] is False
    assert settled["compliance_status"] == "PROBATION", "ten points still exceed the probation bar"

    reinstated = validate_success(api_client.reinstate_permit(permit_id, OFFICER))
    assert reinstated["administrative_status"] == "ACTIVE"
    assert reinstated["suspended_until_date"] is None
    assert reinstated["suspension_reason_code"] is None
    assert reinstated["suspension_count"] == 1
    assert reinstated["compliance_status"] == "PROBATION"
    assert reinstated["authorized_client_capacity_total"] == 0
    assert read_fee_assessment(assessment["id"])["status"] == "PAID"
