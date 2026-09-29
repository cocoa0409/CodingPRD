"""The confidentiality dimension, the disclosure log, the integrity score and
the recurring renewal review."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_round,
    advance_case,
    assert_absence_record,
    assert_calendar_date,
    assert_journal_fields,
    assert_ledger_matches_options,
    assert_medical_disclosure,
    create_absence,
    create_absence_record_payload,
    file_appeal,
    issue_doc_round,
    log_disclosure,
    move_absence,
    open_case,
    propose_option,
    read_absence,
    read_appeal,
    read_case,
    read_employee,
    read_option,
    read_profile,
    record_all_analyses,
    renewal_review,
    respond_to_round,
    set_clock,
    setup_case_at_decision_pending,
    setup_case_at_renewal_due,
    setup_denied_case,
    setup_workforce,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import decide_case

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
APPEAL = TEST_USERS["appeal_officer_headers"]


def _sealed_case_with_filed_appeal(department_code):
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_denied_case(
        denial_basis="NOT_QUALIFIED",
        rationale_text="No ground-level pick face exists on this site.",
        department_code=department_code,
    )
    file_appeal(ctx, "A ground-level face was opened last quarter.")
    return ctx


def test_an_impermissible_disclosure_is_recorded_and_seals_the_case(api):
    """PRD §3.9: "The log **always accepts the row**, and always with HTTP 201.
    An impermissible disclosure is not rejected; it is recorded, because a breach
    that the system refuses to write down is a breach nobody can audit."
    PRD §3.9: "Disclosure to a `Manager` is authorized when every member of
    `fields_disclosed` is drawn from the narrower set of `work_restrictions`,
    `restriction_duration` and `accommodation_needed`."
    PRD §3.9: "Hop two, caused by hop one, drives the case's
    `confidentiality_posture` to `SEALED` — from `STANDARD` or from `RESTRICTED`
    alike — and recomputes the case's `interactive_process_integrity_score`."
    PRD §3.9: "**Unauthorized disclosure.** Count the disclosure rows on the case
    whose `authorized` is false. Each one costs **30 points**."

    Design: Difficulty/cross_entity_state_dependency/appeal_review_blocked_by_sealed_case_posture
    """
    ctx = _sealed_case_with_filed_appeal("LOG")

    response = api.create_medical_disclosure(
        ctx["case"]["id"],
        {
            "disclosed_to_role": "Manager",
            "disclosed_to_user_id": ctx["manager"]["id"],
            "disclosure_purpose": "FUNCTION_ANALYSIS",
            "fields_disclosed": ["diagnosis"],
        },
        COORD,
    )
    row = validate_success(response, 201)

    assert_medical_disclosure(row)
    assert row["authorized"] is False, "a diagnosis is outside the manager's set"

    case = read_case(ctx["case"]["id"])
    assert case["confidentiality_posture"] == "SEALED"
    assert case["interactive_process_integrity_score"] == 70


def test_a_sealed_case_refuses_to_open_the_appeal_review(api):
    """PRD §2.10: "Once a case is `SEALED`, mutating operations scoped to that
    case are refused with `ERR_CASE_SEALED` (HTTP 409)."
    PRD §3.8: "An `AppealOfficer` takes an appeal in `FILED` under review with
    `START_REVIEW`, which requires that the case's `confidentiality_posture` is
    not `SEALED` and that the officer is not the coordinator who issued the
    denial; the appeal moves `FILED → UNDER_REVIEW` and `appeal_officer_user_id`
    is stamped from the acting `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/appeal_review_blocked_by_sealed_case_posture
    """
    ctx = _sealed_case_with_filed_appeal("LO2")
    log_disclosure(
        ctx,
        disclosed_to_role="Manager",
        disclosed_to_user_id=ctx["manager"]["id"],
        disclosure_purpose="FUNCTION_ANALYSIS",
        fields_disclosed=["diagnosis"],
    )
    assert read_case(ctx["case"]["id"])["confidentiality_posture"] == "SEALED"

    response = api.transition_appeal(
        ctx["appeal"]["id"], {"action": "START_REVIEW"}, APPEAL
    )
    validate_error(response, ApiErrorId.ERR_CASE_SEALED)

    appeal = read_appeal(ctx["appeal"]["id"])
    assert appeal["status"] == "FILED"
    assert appeal["appeal_officer_user_id"] is None
    assert appeal["stay_count"] == 0, (
        "the appeal was not yet UNDER_REVIEW when the seal fired"
    )


def test_an_authorized_disclosure_is_an_append_only_row_that_never_seals(api):
    """PRD §2.4: "`EffectivenessReview` rows and `MedicalDisclosure` rows are
    append-only journal entries: they carry `id` and `created_at` only, and both
    `updated_at` and `version` are absent from their representations entirely."
    PRD §3.9: "Disclosure to a `MedicalReviewOfficer` or to a
    `ComplianceAuditor` is always authorized; these two roles see everything."
    PRD §3.9: "The log is readable by the same three roles and filterable on
    `authorized`."

    Design: Corner/entities/corner_medical_disclosure_is_append_only_immutable_row
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CN9")
    open_case(ctx, disability_obvious=True)

    response = api.create_medical_disclosure(
        ctx["case"]["id"],
        {
            "disclosed_to_role": "MedicalReviewOfficer",
            "disclosed_to_user_id": "MRO-1",
            "disclosure_purpose": "AUDIT",
            "fields_disclosed": ["diagnosis", "treatment_plan"],
        },
        AUDITOR,
    )
    row = validate_success(response, 201)

    assert_journal_fields(row, "MedicalDisclosure")
    assert row["authorized"] is True

    case = read_case(ctx["case"]["id"])
    assert case["confidentiality_posture"] == "STANDARD", (
        "an authorized disclosure does not seal"
    )
    assert case["interactive_process_integrity_score"] == 100

    rows, meta = validate_paginated(
        api.list_medical_disclosures(ctx["case"]["id"], AUDITOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == row["id"]


def test_the_integrity_score_clamps_at_zero_after_four_breaches(api):
    """PRD §3.9: "It starts from a base of **100** and subtracts four penalties,
    then floors the result at **0** so it can never go negative."
    PRD §3.9: "**Unauthorized disclosure.** Count the disclosure rows on the case
    whose `authorized` is false. Each one costs **30 points**."
    PRD §3.9: "Disclosure to `EXTERNAL` is never authorized."
    PRD §3.9: "Disclosure to a `FinanceOfficer` is authorized only when
    `fields_disclosed` contains nothing beyond `accommodation_needed`."
    PRD §3.9: "Disclosure to an `AppealOfficer` is authorized under the same
    five-category set permitted to an `AccommodationCoordinator`."

    Design: Corner/calculations/corner_integrity_score_floors_at_zero_after_repeated_breaches
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CNA")
    open_case(ctx, disability_obvious=True)

    breaches = [
        ("EXTERNAL", "VENDOR-1", "OTHER", ["work_restrictions"]),
        ("FinanceOfficer", "FIN-1", "HARDSHIP_ASSESSMENT", ["diagnosis"]),
        ("Manager", "MGR-X", "FUNCTION_ANALYSIS", ["prognosis"]),
        ("AppealOfficer", "APPEAL-1", "APPEAL_REVIEW", ["treatment_plan"]),
    ]
    for role, user_id, purpose, fields in breaches:
        response = api.create_medical_disclosure(
            ctx["case"]["id"],
            {
                "disclosed_to_role": role,
                "disclosed_to_user_id": user_id,
                "disclosure_purpose": purpose,
                "fields_disclosed": fields,
            },
            AUDITOR,
        )
        row = validate_success(response, 201)
        assert row["authorized"] is False, f"disclosure to {role} of {fields} is a breach"

    case = read_case(ctx["case"]["id"])
    assert case["interactive_process_integrity_score"] == 0, (
        "100 minus four 30-point penalties floors at zero"
    )
    assert case["confidentiality_posture"] == "SEALED"

    _rows, meta = validate_paginated(
        api.list_medical_disclosures(ctx["case"]["id"], AUDITOR, {"authorized": False})
    )
    assert meta["total_count"] == 4


def test_linking_an_open_absence_record_shortens_the_renewal_cadence(api):
    """PRD §3.3: "An `AccommodationCoordinator` may later amend
    `requested_accommodation_text`, `disability_obvious` and `absence_record_id`
    on an open case; linking an absence record after the fact is the ordinary way
    a leave or workers'-compensation matter gets cross-referenced, and it later
    shortens the renewal cadence."
    PRD §3.7: "If the case's `absence_record_id` is non-null and that absence
    record's `status` is anything other than `CLOSED`, a **90-day** interval also
    applies."
    PRD §3.7: "`review_cadence_days` is the smallest of whichever intervals
    apply, and `review_due_date` is the current logical-clock date plus that many
    days."
    PRD §3.7: "If the recorded `decision` is `GRANT_WITH_TRIAL`, a **120-day**
    interval also applies."

    Design: Corner/endpoints/corner_patch_case_links_absence_record_and_shortens_cadence
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_decision_pending(department_code="CN5")
    absence = create_absence(
        ctx,
        record_type="WC_RESTRICTION",
        start_date="2026-08-01",
        end_date="2026-12-31",
        restriction_severity=2,
        modified_duty_available=True,
    )
    move_absence(absence, "ACTIVE")

    linked = validate_success(
        api.update_accommodation_request(
            ctx["case"]["id"], {"absence_record_id": absence["id"]}, COORD
        ),
        200,
    )
    assert linked["absence_record_id"] == absence["id"]
    ctx["case"] = linked

    case = decide_case(
        ctx, decision="GRANT_WITH_TRIAL", selected_option_id=ctx["options"][0]["id"]
    )
    assert case["review_cadence_days"] == 90, (
        "the smallest of the 365, 120 and 90 day intervals"
    )
    assert_calendar_date(case["review_due_date"], "2026-11-01", "review_due_date")
    assert case["stage"] == "TRIAL_SETUP"
    assert case["selected_option_id"] == ctx["options"][0]["id"]

    _rows, meta = validate_paginated(
        api.list_accommodation_requests(COORD, {"absence_record_id": absence["id"]})
    )
    assert meta["total_count"] == 1


def test_the_committed_ledger_returns_to_exactly_its_pre_grant_value(api):
    """PRD §2.11: "The forward action fires when an option enters `SELECTED` or
    `IMPLEMENTED`: the option's `committed_cost_cents` is set to its
    `option_net_cost_cents`, and that same amount is added to the profile's
    ledger."
    PRD §2.11: "The pair must leave the ledger at exactly the value it held
    before the forward action."
    PRD §3.9: "**`CLOSE`** retires the matter, with no precondition of its own.
    The case moves `RENEWAL_DUE → CLOSED`; the selected option is set to
    `IMPLEMENTED` with its `committed_cost_cents` released to zero and that
    released amount subtracted from the pinned profile's
    `committed_accommodation_cost_cents`; and the employee's `open_case_count` is
    decremented by one."

    Design: Difficulty/compensating_invariant/committed_cost_ledger_returns_to_zero_after_renewal_close
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_renewal_due(department_code="ARC")

    granted_profile = read_profile(ctx["profile"]["id"])
    assert granted_profile["committed_accommodation_cost_cents"] == 29_600
    option = read_option(ctx["case"]["selected_option_id"])
    assert option["committed_cost_cents"] == 29_600

    renewal_review(ctx, "CLOSE")

    profile = read_profile(ctx["profile"]["id"])
    assert profile["committed_accommodation_cost_cents"] == 0, (
        "the release leaves the ledger at exactly its pre-grant value"
    )
    released = read_option(option["id"])
    assert released["committed_cost_cents"] == 0
    assert released["status"] == "IMPLEMENTED"
    assert_ledger_matches_options(profile, [released])


def test_the_renewal_close_retires_the_case_and_its_open_count(api):
    """PRD §2.5: "Every `AccommodationRequest` in stage `GRANTED_PERMANENT` whose
    `review_due_date` is non-null and is at or before the current logical date
    moves to stage `RENEWAL_DUE`."
    PRD §3.9: "All four outcomes increment `review_cycle_index` by one and
    increment the case's `version` by one; they differ in everything else."
    PRD §3.9: "**`CLOSE`** retires the matter, with no precondition of its own.
    The case moves `RENEWAL_DUE → CLOSED`; the selected option is set to
    `IMPLEMENTED` with its `committed_cost_cents` released to zero and that
    released amount subtracted from the pinned profile's
    `committed_accommodation_cost_cents`; and the employee's `open_case_count` is
    decremented by one."
    PRD §3.7: "Begin with a baseline of **365 days** — one review a year."

    Design: Difficulty/compensating_invariant/committed_cost_ledger_returns_to_zero_after_renewal_close
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_renewal_due(department_code="AR2")

    assert ctx["case"]["review_cadence_days"] == 365
    assert_calendar_date(ctx["case"]["review_due_date"], "2027-08-03", "review_due_date")
    assert ctx["case"]["stage"] == "RENEWAL_DUE", "the sweep promoted the case"

    closed = renewal_review(ctx, "CLOSE")

    assert closed["stage"] == "CLOSED"
    assert closed["review_cycle_index"] == 1
    assert read_employee(ctx["employee"]["id"])["open_case_count"] == 0


def test_the_employee_withdrawal_sweeps_the_open_children_and_locks_the_case(api):
    """PRD §3.3: "Withdrawal sets the case's stage to `WITHDRAWN`; sets every
    accommodation option on the case that is in `PROPOSED`, `CLEARED` or
    `HARDSHIP_BLOCKED` to `WITHDRAWN`, adjusting `cleared_option_count` and
    `blocked_option_count` to match; sets every documentation round on the case
    in `ISSUED` or `RESPONDED` to `WITHDRAWN` and recomputes
    `medical_doc_request_count`; sets every trial period on the case in
    `SCHEDULED`, `ACTIVE` or `UNDER_REVIEW` to `ABORTED`; and decrements the
    employee's `open_case_count`."
    PRD §3.3: "Any advance or decision that is not declared out of the case's
    current stage is refused with `ERR_INVALID_STAGE_TRANSITION`."

    Design: Corner/state_machines/corner_withdraw_cascades_options_and_doc_rounds_then_locks_case
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CN4")
    open_case(ctx, disability_obvious=False)
    doc_round = issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    respond_to_round(ctx, doc_round)
    adjudicate_round(doc_round, "SUFFICIENT", "Provider letter is sufficient")
    advance_case(ctx, "FUNCTION_ANALYSIS")
    record_all_analyses(ctx)
    advance_case(ctx, "OPTION_EXPLORATION")
    option = propose_option(ctx, option_code="C-OPT-14")

    withdrawn = validate_success(
        api.advance_accommodation_request(
            ctx["case"]["id"], {"target_stage": "WITHDRAWN"}, ctx["employee_headers"]
        ),
        200,
    )
    assert withdrawn["stage"] == "WITHDRAWN"
    assert read_option(option["id"])["status"] == "WITHDRAWN"

    rows, _meta = validate_paginated(
        api.list_medical_doc_requests(ctx["case"]["id"], COORD)
    )
    stored_round = [r for r in rows if r["id"] == doc_round["id"]][0]
    assert stored_round["status"] == "ACCEPTED_SUFFICIENT", (
        "a terminal round is not swept into WITHDRAWN by the cascade"
    )
    assert read_case(ctx["case"]["id"])["medical_doc_request_count"] == 1
    assert read_employee(ctx["employee"]["id"])["open_case_count"] == 0

    locked = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "HARDSHIP_REVIEW"}, COORD
    )
    validate_error(locked, ApiErrorId.ERR_INVALID_STAGE_TRANSITION)


def test_activating_and_closing_a_restriction_drives_the_employment_status(api):
    """PRD §3.2: "Activation drives the employee's `employment_status`: to
    `RESTRICTED_DUTY` when the record is a `WC_RESTRICTION`, and to `ON_LEAVE`
    for every other type."
    PRD §3.2: "Whenever a record reaches `EXHAUSTED`, or is closed from `ACTIVE`
    or `MODIFIED_DUTY`, the employee's `employment_status` returns to `ACTIVE`
    provided the employee has no other absence record still sitting in `ACTIVE`
    or `MODIFIED_DUTY`; closing an already-`EXHAUSTED` record is a bookkeeping
    move that leaves `employment_status` alone."
    PRD §3.2: "Absence records are readable individually and listable with
    filters on `employee_id`, `record_type` and `status`."

    Design: Corner/state_machines/corner_absence_activation_and_closure_drive_employment_status
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CNH", with_manager=False)
    absence = validate_success(
        api.create_absence_record(
            create_absence_record_payload(
                ctx["employee"]["id"],
                record_type="WC_RESTRICTION",
                start_date="2026-09-01",
                end_date="2026-12-01",
                restriction_severity=3,
                modified_duty_available=False,
            ),
            COORD,
        ),
        201,
    )
    assert_absence_record(absence)
    assert absence["status"] == "SCHEDULED"

    activated = validate_success(
        api.transition_absence_record(absence["id"], {"to_status": "ACTIVE"}, COORD), 200
    )
    assert activated["status"] == "ACTIVE"
    assert read_employee(ctx["employee"]["id"])["employment_status"] == "RESTRICTED_DUTY"

    closed = validate_success(
        api.transition_absence_record(absence["id"], {"to_status": "CLOSED"}, COORD), 200
    )
    assert closed["status"] == "CLOSED"
    assert read_employee(ctx["employee"]["id"])["employment_status"] == "ACTIVE"

    _rows, meta = validate_paginated(
        api.list_absence_records(COORD, {"employee_id": ctx["employee"]["id"]})
    )
    assert meta["total_count"] == 1


def test_the_intermittent_cap_and_the_undeclared_transition_are_both_refused(api):
    """PRD §3.2: "It then adds the candidate's `weekly_intermittent_days` to the
    sum of `weekly_intermittent_days` across those overlapping records. If that
    total exceeds **five days per week**, the create is refused with
    `ERR_INTERMITTENT_CAP_EXCEEDED`."
    PRD §3.2: "From `ACTIVE`, a workers'-compensation restriction whose
    `modified_duty_available` is true may move to `MODIFIED_DUTY`, which again
    sets the employee's `employment_status` to `RESTRICTED_DUTY`; requesting that
    move on a record that is not a workers'-compensation restriction, or on one
    where modified duty is not available, is refused with
    `ERR_ABSENCE_TRANSITION_INVALID`, as is any `to_status` that is not reachable
    from the record's current status."

    Design: Corner/errors/corner_absence_record_cap_and_invalid_transition_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_workforce(department_code="CNG", with_manager=False)
    first = validate_success(
        api.create_absence_record(
            create_absence_record_payload(
                ctx["employee"]["id"],
                record_type="FMLA_INTERMITTENT",
                start_date="2026-09-01",
                end_date="2026-10-01",
                weekly_intermittent_days=3,
            ),
            COORD,
        ),
        201,
    )

    overlapping = api.create_absence_record(
        create_absence_record_payload(
            ctx["employee"]["id"],
            record_type="FMLA_INTERMITTENT",
            start_date="2026-09-15",
            end_date="2026-10-15",
            weekly_intermittent_days=3,
        ),
        COORD,
    )
    validate_error(overlapping, ApiErrorId.ERR_INTERMITTENT_CAP_EXCEEDED)

    _rows, meta = validate_paginated(
        api.list_absence_records(COORD, {"employee_id": ctx["employee"]["id"]})
    )
    assert meta["total_count"] == 1, "the over-cap candidate was never persisted"

    validate_success(
        api.transition_absence_record(first["id"], {"to_status": "ACTIVE"}, COORD), 200
    )

    invalid = api.transition_absence_record(
        first["id"], {"to_status": "MODIFIED_DUTY"}, COORD
    )
    validate_error(invalid, ApiErrorId.ERR_ABSENCE_TRANSITION_INVALID)

    assert read_absence(first["id"])["status"] == "ACTIVE"
    assert read_employee(ctx["employee"]["id"])["employment_status"] == "ON_LEAVE"
