"""The bounded medical-documentation budget: scope, permission, budget and the
half-open response window."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_round,
    assert_documentation_budget_invariant,
    assert_medical_doc_request,
    case_version,
    issue_doc_round,
    open_case,
    read_case,
    respond_to_round,
    set_clock,
    setup_workforce,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
MEDICAL = TEST_USERS["medical_officer_headers"]


def _case_in_intake(department_code, disability_obvious=False, clock="2026-08-03T09:00:00Z"):
    set_clock(clock)
    ctx = setup_workforce(department_code=department_code)
    open_case(ctx, disability_obvious=disability_obvious)
    return ctx


def test_a_functional_only_scope_opens_the_documentation_stage(api):
    """PRD §3.3: "The **scope** guard comes first: the employer is entitled to
    functional information only, so `scope_fields_requested` may not include
    `diagnosis` and may not include `treatment_plan`, and a round that asks for
    either is refused with `ERR_MEDICAL_SCOPE_OVERBROAD`."
    PRD §3.3: "A successful issue creates the round in `status` `ISSUED` with
    `issued_at` read from the logical clock and `round_index` set to the case's
    `medical_doc_request_count` plus one — a 1-based ordinal assigned in
    issuance order."
    PRD §3.3: "The first such round moves the case from `INTAKE` to
    `DOC_PENDING`; every subsequent round is a self-loop that leaves the case in
    `DOC_PENDING`, because the interactive process may legitimately need more
    than one round."

    Design: Corner/validations/corner_functional_only_scope_passes_documentation_request
    """
    ctx = _case_in_intake("CNE")

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": [
                "functional_limitations",
                "work_restrictions",
                "restriction_duration",
                "prognosis",
                "accommodation_needed",
            ],
            "due_date": "2026-08-17T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": case_version(ctx["case"]["id"]),
        },
        COORD,
    )
    data = validate_success(response, 201)

    assert_medical_doc_request(data)
    assert data["status"] == "ISSUED"
    assert data["round_index"] == 1
    assert data["issued_at"] == "2026-08-03T09:00:00.000Z"

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "DOC_PENDING"
    assert case["medical_doc_request_count"] == 1
    assert case["documentation_budget_remaining"] == 1
    assert case["interactive_process_integrity_score"] == 100
    assert_documentation_budget_invariant(case)


def test_an_obvious_disability_forbids_documentation_altogether(api):
    """PRD §3.3: "The **permission** guard comes next: when the case's
    `disability_obvious` is true, the limitation is obvious or already known and
    no medical documentation may be requested at all, so any round on such a
    case is refused with `ERR_DOCUMENTATION_NOT_PERMITTED`."

    Design: Corner/validations/corner_documentation_not_permitted_when_disability_is_obvious
    """
    ctx = _case_in_intake("CNF", disability_obvious=True)

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["functional_limitations"],
            "due_date": "2026-08-17T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": case_version(ctx["case"]["id"]),
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_DOCUMENTATION_NOT_PERMITTED)

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "INTAKE"
    assert case["medical_doc_request_count"] == 0

    _rows, meta = validate_paginated(
        api.list_medical_doc_requests(ctx["case"]["id"], COORD)
    )
    assert meta["total_count"] == 0


def test_the_employee_response_hardens_the_posture_without_moving_the_stage(api):
    """PRD §3.3: "Responding moves the round `ISSUED → RESPONDED`, stamps
    `responded_at` from the clock, and — this is the parallel-dimension side
    effect — moves the case's `confidentiality_posture` from `STANDARD` to
    `RESTRICTED`."
    PRD §2.10: "`stage` tracks where the case sits in the interactive process.
    `confidentiality_posture` tracks how tightly the case's medical information
    is held, and it moves on its own axis: nothing about the `stage` value
    constrains the posture value, and a posture change never by itself advances
    or rewinds `stage`."

    Design: Corner/state_machines/corner_respond_hardens_confidentiality_posture_to_restricted
    """
    ctx = _case_in_intake("CNG")
    doc_round = issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")

    response = api.respond_medical_doc_request(
        doc_round["id"],
        {"response_summary": "Occupational health letter uploaded"},
        ctx["employee_headers"],
    )
    data = validate_success(response, 200)

    assert data["status"] == "RESPONDED"
    assert data["responded_at"] == "2026-08-03T09:00:00.000Z"

    case = read_case(ctx["case"]["id"])
    assert case["confidentiality_posture"] == "RESTRICTED"
    assert case["stage"] == "DOC_PENDING", "the stage dimension is untouched"
    assert case["interactive_process_integrity_score"] == 100


def test_a_terminal_round_cannot_be_adjudicated_a_second_time(api):
    """PRD §3.3: "A `MedicalReviewOfficer`, and no other role, then adjudicates a
    `RESPONDED` round by supplying a `verdict` of `SUFFICIENT` or `INSUFFICIENT`,
    together with an optional `adjudication_note`; the round moves to
    `ACCEPTED_SUFFICIENT` or to `REJECTED_INSUFFICIENT` accordingly and the note
    is recorded."
    PRD §3.3: "Any of these three moves attempted from a status that does not
    permit it is refused with `ERR_DOC_REQUEST_NOT_OPEN`."

    Design: Corner/state_machines/corner_second_adjudication_on_terminal_round_rejected
    """
    ctx = _case_in_intake("CNH")
    doc_round = issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    respond_to_round(ctx, doc_round)
    ruled = adjudicate_round(doc_round, "SUFFICIENT", "First ruling")
    assert ruled["status"] == "ACCEPTED_SUFFICIENT"
    assert ruled["adjudication_note"] == "First ruling"

    response = api.adjudicate_medical_doc_request(
        doc_round["id"],
        {"verdict": "INSUFFICIENT", "adjudication_note": "Second ruling"},
        MEDICAL,
    )
    validate_error(response, ApiErrorId.ERR_DOC_REQUEST_NOT_OPEN)

    rows, _meta = validate_paginated(
        api.list_medical_doc_requests(ctx["case"]["id"], COORD)
    )
    stored = [r for r in rows if r["id"] == doc_round["id"]][0]
    assert stored["status"] == "ACCEPTED_SUFFICIENT"
    assert stored["adjudication_note"] == "First ruling"


# --------------------------------------------------------------------------
# The discrete budget boundary
# --------------------------------------------------------------------------
def test_the_round_that_reaches_the_base_allowance_is_still_accepted(api):
    """PRD §3.3: "Start from a base allowance of **two** rounds."
    PRD §3.3: "A successful issue creates the round in `status` `ISSUED` with
    `issued_at` read from the logical clock and `round_index` set to the case's
    `medical_doc_request_count` plus one — a 1-based ordinal assigned in
    issuance order."
    PRD §3.3: "`documentation_budget_remaining` is the ceiling minus the count,
    floored at zero so it is never negative."

    Design: Difficulty/boundary_precision_check/doc_round_at_limit_allowed_next_round_rejected
    """
    ctx = _case_in_intake("AD2")
    issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")

    second = issue_doc_round(ctx, ["work_restrictions"], "2026-08-31T00:00:00Z")
    assert second["round_index"] == 2
    assert second["status"] == "ISSUED"

    case = read_case(ctx["case"]["id"])
    assert case["medical_doc_request_count"] == 2
    assert case["medical_doc_request_limit"] == 2
    assert case["documentation_budget_remaining"] == 0
    assert_documentation_budget_invariant(case)


def test_the_round_past_the_base_allowance_is_refused(api):
    """PRD §3.3: "The **budget** guard comes after both:
    `documentation_budget_remaining` must be at least 1, and a round issued
    against an exhausted budget is refused with
    `ERR_DOC_REQUEST_LIMIT_EXCEEDED`."
    PRD §3.9: "Count the case's `medical_doc_request_count` and subtract the
    base allowance of two, taking zero if the difference is negative."

    Design: Difficulty/boundary_precision_check/doc_round_at_limit_allowed_next_round_rejected
    """
    ctx = _case_in_intake("AD3")
    issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")
    issue_doc_round(ctx, ["work_restrictions"], "2026-08-31T00:00:00Z")

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["prognosis"],
            "due_date": "2026-09-14T00:00:00Z",
            "is_second_opinion": True,
            "expected_request_version": case_version(ctx["case"]["id"]),
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_DOC_REQUEST_LIMIT_EXCEEDED)

    case = read_case(ctx["case"]["id"])
    assert case["medical_doc_request_count"] == 2
    assert case["medical_doc_request_limit"] == 2
    assert case["interactive_process_integrity_score"] == 100, (
        "two rounds is exactly the base allowance, so no overreach penalty applies"
    )


# --------------------------------------------------------------------------
# The compensating withdrawal
# --------------------------------------------------------------------------
def test_withdrawing_an_issued_round_returns_its_budget_unit(api):
    """PRD §3.3: "An `AccommodationCoordinator` may withdraw a round from either
    `ISSUED` or `RESPONDED`, which moves it to `WITHDRAWN`, decrements the
    case's `medical_doc_request_count`, recomputes
    `documentation_budget_remaining` — returning that budget unit to the case —
    and recomputes the integrity score."
    PRD §3.3: "`documentation_budget_remaining` is the ceiling minus the count,
    floored at zero so it is never negative."

    Design: Difficulty/compensating_invariant/doc_budget_restored_by_withdrawing_issued_round
    """
    ctx = _case_in_intake("ITS")
    before = read_case(ctx["case"]["id"])
    assert before["medical_doc_request_count"] == 0
    assert before["documentation_budget_remaining"] == 2
    assert_documentation_budget_invariant(before)

    doc_round = issue_doc_round(
        ctx, ["functional_limitations", "work_restrictions"], "2026-08-17T00:00:00Z"
    )

    midway = read_case(ctx["case"]["id"])
    assert midway["medical_doc_request_count"] == 1
    assert midway["documentation_budget_remaining"] == 1
    assert midway["medical_doc_request_limit"] == 2
    assert_documentation_budget_invariant(midway)

    validate_success(api.withdraw_medical_doc_request(doc_round["id"], COORD), 200)

    after = read_case(ctx["case"]["id"])
    assert after["medical_doc_request_count"] == 0, "the pre-issue count is restored"
    assert after["documentation_budget_remaining"] == 2, "the budget unit comes back"
    assert_documentation_budget_invariant(after)


def test_the_withdrawal_restores_the_quota_but_not_the_stage(api):
    """PRD §3.3: "An `AccommodationCoordinator` may withdraw a round from either
    `ISSUED` or `RESPONDED`, which moves it to `WITHDRAWN`, decrements the
    case's `medical_doc_request_count`, recomputes
    `documentation_budget_remaining` — returning that budget unit to the case —
    and recomputes the integrity score."
    PRD §3.3: "The first such round moves the case from `INTAKE` to
    `DOC_PENDING`; every subsequent round is a self-loop that leaves the case in
    `DOC_PENDING`, because the interactive process may legitimately need more
    than one round."
    PRD §3.9: "Count the case's `medical_doc_request_count` and subtract the
    base allowance of two, taking zero if the difference is negative."

    Design: Difficulty/compensating_invariant/doc_budget_restored_by_withdrawing_issued_round
    """
    ctx = _case_in_intake("IT2")
    assert read_case(ctx["case"]["id"])["interactive_process_integrity_score"] == 100

    doc_round = issue_doc_round(
        ctx, ["functional_limitations", "work_restrictions"], "2026-08-17T00:00:00Z"
    )
    assert read_case(ctx["case"]["id"])["stage"] == "DOC_PENDING"

    withdrawn = validate_success(
        api.withdraw_medical_doc_request(doc_round["id"], COORD), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "DOC_PENDING", (
        "the compensating action restores the quota but not the stage"
    )
    assert case["interactive_process_integrity_score"] == 100


# --------------------------------------------------------------------------
# The half-open documentation window
# --------------------------------------------------------------------------
def test_a_round_issued_inside_an_open_window_collides(api):
    """PRD §3.3: "Documentation windows are **half-open** on the case: a round
    occupies the interval from its `issued_at` up to but excluding its
    `due_date`, and only rounds still in `ISSUED` occupy anything."
    PRD §3.3: "A new round's `issued_at` is always the current logical instant,
    so it can never begin before an existing window; the collision test is
    therefore simply whether the new `issued_at` falls strictly before the
    `due_date` of some round still in `ISSUED`."

    Design: Difficulty/resource_temporal_overlap/doc_round_half_open_window_allows_exact_touch
    """
    ctx = _case_in_intake("FIN")
    issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")

    set_clock("2026-08-10T00:00:00Z")
    version_before = case_version(ctx["case"]["id"])

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["work_restrictions"],
            "due_date": "2026-08-24T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": version_before,
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_DOC_WINDOW_OVERLAP)

    case = read_case(ctx["case"]["id"])
    assert case["version"] == version_before, "a rejected call does not bump the version"
    assert case["medical_doc_request_count"] == 1


def test_a_round_issued_at_the_prior_due_date_does_not_collide(api):
    """PRD §3.3: "Because the endpoint is exclusive, a round issued at exactly
    the prior round's `due_date` does **not** collide."
    PRD §3.3: "A successful issue creates the round in `status` `ISSUED` with
    `issued_at` read from the logical clock and `round_index` set to the case's
    `medical_doc_request_count` plus one — a 1-based ordinal assigned in
    issuance order."

    Design: Difficulty/resource_temporal_overlap/doc_round_half_open_window_allows_exact_touch
    """
    ctx = _case_in_intake("FI2")
    first = issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")

    set_clock("2026-08-17T00:00:00Z")
    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["work_restrictions"],
            "due_date": "2026-08-31T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": case_version(ctx["case"]["id"]),
        },
        COORD,
    )
    data = validate_success(response, 201)

    assert data["round_index"] == 2
    assert data["issued_at"] == "2026-08-17T00:00:00.000Z"

    rows, _meta = validate_paginated(
        api.list_medical_doc_requests(ctx["case"]["id"], COORD)
    )
    stored_first = [r for r in rows if r["id"] == first["id"]][0]
    assert stored_first["status"] == "ISSUED", "no sweep has run, so round one is still open"

    case = read_case(ctx["case"]["id"])
    assert case["medical_doc_request_count"] == 2
    assert case["documentation_budget_remaining"] == 0


# --------------------------------------------------------------------------
# Scope overbreadth outranks budget exhaustion
# --------------------------------------------------------------------------
def _case_with_exhausted_budget(department_code):
    ctx = _case_in_intake(department_code)
    issue_doc_round(ctx, ["functional_limitations", "work_restrictions"], "2026-08-17T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")
    issue_doc_round(ctx, ["restriction_duration"], "2026-08-31T00:00:00Z")
    set_clock("2026-08-31T00:00:00Z")
    return ctx


def test_an_overbroad_scope_is_reported_ahead_of_an_exhausted_budget(api):
    """PRD §3.3: "Three substantive guards apply, and their relative order
    matters when a single request trips more than one."
    PRD §3.3: "The **scope** guard comes first: the employer is entitled to
    functional information only, so `scope_fields_requested` may not include
    `diagnosis` and may not include `treatment_plan`, and a round that asks for
    either is refused with `ERR_MEDICAL_SCOPE_OVERBROAD`."
    PRD §3.3: "The **budget** guard comes after both:
    `documentation_budget_remaining` must be at least 1, and a round issued
    against an exhausted budget is refused with
    `ERR_DOC_REQUEST_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/scope_overbreadth_outranks_doc_limit_exhaustion
    """
    ctx = _case_with_exhausted_budget("ADM")
    before = read_case(ctx["case"]["id"])
    assert before["documentation_budget_remaining"] == 0, (
        "the budget guard would also fail on this request"
    )

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["diagnosis", "functional_limitations"],
            "due_date": "2026-09-14T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": before["version"],
        },
        COORD,
    )
    error = validate_error(response, ApiErrorId.ERR_MEDICAL_SCOPE_OVERBROAD)
    assert error["error_id"] != "ERR_DOC_REQUEST_LIMIT_EXCEEDED"
    assert response.status_code == 422


def test_the_rejected_overbroad_round_leaves_every_counter_alone(api):
    """PRD §2.6: "When a request violates more than one rule, exactly one error
    is returned, and which one is fully determined."
    PRD §3.3: "The **scope** guard comes first: the employer is entitled to
    functional information only, so `scope_fields_requested` may not include
    `diagnosis` and may not include `treatment_plan`, and a round that asks for
    either is refused with `ERR_MEDICAL_SCOPE_OVERBROAD`."

    Design: Difficulty/priority_pair_validation_conflict/scope_overbreadth_outranks_doc_limit_exhaustion
    """
    ctx = _case_with_exhausted_budget("AD4")
    before = read_case(ctx["case"]["id"])

    response = api.create_medical_doc_request(
        ctx["case"]["id"],
        {
            "scope_fields_requested": ["treatment_plan"],
            "due_date": "2026-09-14T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": before["version"],
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_MEDICAL_SCOPE_OVERBROAD)

    after = read_case(ctx["case"]["id"])
    assert after["medical_doc_request_count"] == 2
    assert after["documentation_budget_remaining"] == 0
    assert after["version"] == before["version"]
    assert_documentation_budget_invariant(after)

    _rows, meta = validate_paginated(
        api.list_medical_doc_requests(ctx["case"]["id"], COORD)
    )
    assert meta["total_count"] == 2
