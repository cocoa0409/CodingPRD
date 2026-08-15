"""Material release: case-FINAL gate, releasable-material gate, approval
safety-vs-temporal precedence, closed-interval loan conflicts, and the
overdue sweep with late return."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    ApiErrorId,
    approve_release_request,
    assign_case,
    create_block,
    create_release_request,
    deny_release_request,
    get_block,
    get_release_request,
    get_slide,
    set_clock,
    setup_final_case,
    setup_qc_passed_case,
    ship_release_request,
    sign_out_case,
    submit_for_signout,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_release_create_gated_on_case_final(api):
    """PRD §3.8: "Blocks and slides may leave the laboratory on loan to
    outside institutions, but only after the diagnostic story is closed:
    creating a release request — open to `LabAdmin` and `Pathologist` —
    requires the material's case to be `FINAL`, otherwise
    `ERR_CASE_NOT_FINAL` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/release_create_gated_on_case_final
    """
    # WORKUP case with a QC_PASSED slide: material releasable, case state wrong.
    ctx = setup_qc_passed_case(mrn="MRN-801")
    assert get_slide(ctx["slides"][0]["id"])["status"] == "QC_PASSED"

    resp = api.create_release_request(
        {
            "material_type": "SLIDE",
            "slide_id": ctx["slides"][0]["id"],
            "requesting_institution": "County Hospital",
            "reason": "external review",
            "requested_out_at": "2026-08-10T00:00:00Z",
            "due_back_at": "2026-08-20T00:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FINAL)


def test_release_create_gated_on_case_final_creates_nothing(api):
    """PRD §3.8: "creating a release request — open to `LabAdmin` and
    `Pathologist` — requires the material's case to be `FINAL`, otherwise
    `ERR_CASE_NOT_FINAL` (HTTP 409)."
    PRD §2.3: "the release-request list accepts `block_id`, `slide_id`, and
    `status`"

    Design: Difficulty/cross_entity_state_dependency/release_create_gated_on_case_final
    """
    ctx = setup_qc_passed_case(mrn="MRN-801")
    slide_id = ctx["slides"][0]["id"]
    resp = api.create_release_request(
        {
            "material_type": "SLIDE",
            "slide_id": slide_id,
            "requesting_institution": "County Hospital",
            "reason": "external review",
            "requested_out_at": "2026-08-10T00:00:00Z",
            "due_back_at": "2026-08-20T00:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FINAL)
    _data, meta = validate_paginated(
        api.list_release_requests(ADMIN_HEADERS, params={"slide_id": slide_id})
    )
    assert meta["total_count"] == 0, "no ReleaseRequest row may be created"


def test_release_last_material_safety_beats_loan_interval(api):
    """PRD §2.9: "on release approval, the last-diagnostic-material safety
    check is evaluated before the loan-interval temporal check, so a
    doubly-forbidden approval surfaces `ERR_LAST_DIAGNOSTIC_MATERIAL` rather
    than `ERR_LOAN_INTERVAL_CONFLICT`"
    PRD §3.8: "The safety gate refuses to strip a case of its last diagnostic
    material: approving a slide that is the only `QC_PASSED` slide of its
    case, or a block that is the only `EMBEDDED` non-`DEPLETED` block of its
    case, is rejected with `ERR_LAST_DIAGNOSTIC_MATERIAL` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/release_last_material_safety_beats_loan_interval_temporal
    """
    # FINAL case with exactly one QC_PASSED slide.
    ctx = setup_final_case(mrn="MRN-601")
    slide_id = ctx["slides"][0]["id"]
    create_release_request(
        slide_id=slide_id,
        requesting_institution="County Hospital",
        reason="tumor board",
        requested_out_at="2026-08-10T00:00:00Z",
        due_back_at="2026-08-20T00:00:00Z",
    )
    r2 = create_release_request(
        slide_id=slide_id,
        requesting_institution="University Hospital",
        reason="second opinion",
        requested_out_at="2026-08-15T00:00:00Z",
        due_back_at="2026-08-25T00:00:00Z",
    )

    resp = api.approve_release_request(r2["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_LAST_DIAGNOSTIC_MATERIAL)
    assert get_release_request(r2["id"])["status"] == "REQUESTED", (
        "the doubly-forbidden approval changed nothing"
    )


def test_release_last_material_safety_also_guards_first_request(api):
    """PRD §2.9: "on release approval, the last-diagnostic-material safety
    check is evaluated before the loan-interval temporal check, so a
    doubly-forbidden approval surfaces `ERR_LAST_DIAGNOSTIC_MATERIAL` rather
    than `ERR_LOAN_INTERVAL_CONFLICT`"
    PRD §3.8: "The temporal gate then checks for scheduling conflicts: if any
    other release request for the same material is in `REQUESTED`,
    `APPROVED`, `SHIPPED`, or `OVERDUE` with a closed interval from
    `requested_out_at` to `due_back_at` that intersects this request's
    interval — and touching endpoints count as a conflict — approval is
    rejected with `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/release_last_material_safety_beats_loan_interval_temporal
    """
    ctx = setup_final_case(mrn="MRN-601")
    slide_id = ctx["slides"][0]["id"]
    r1 = create_release_request(
        slide_id=slide_id,
        requesting_institution="County Hospital",
        reason="tumor board",
        requested_out_at="2026-08-10T00:00:00Z",
        due_back_at="2026-08-20T00:00:00Z",
    )
    r2 = create_release_request(
        slide_id=slide_id,
        requesting_institution="University Hospital",
        reason="second opinion",
        requested_out_at="2026-08-15T00:00:00Z",
        due_back_at="2026-08-25T00:00:00Z",
    )

    # Both requests are doubly forbidden (last material AND overlapping
    # intervals); either approval surfaces the safety error first.
    resp = api.approve_release_request(r1["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_LAST_DIAGNOSTIC_MATERIAL)
    resp = api.approve_release_request(r2["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_LAST_DIAGNOSTIC_MATERIAL)
    assert get_release_request(r1["id"])["status"] == "REQUESTED"
    assert get_release_request(r2["id"])["status"] == "REQUESTED"


def test_release_loan_closed_interval_touching_conflicts(api):
    """PRD §3.8: "if any other release request for the same material is in
    `REQUESTED`, `APPROVED`, `SHIPPED`, or `OVERDUE` with a closed interval
    from `requested_out_at` to `due_back_at` that intersects this request's
    interval — and touching endpoints count as a conflict — approval is
    rejected with `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/release_loan_closed_interval_touching_conflicts
    """
    # Two QC_PASSED slides so the safety gate does not fire for s1.
    ctx = setup_final_case(mrn="MRN-900", num_qc_slides=2)
    slide_id = ctx["slides"][0]["id"]
    create_release_request(
        slide_id=slide_id,
        requesting_institution="County Hospital",
        reason="board review",
        requested_out_at="2026-08-10T00:00:00Z",
        due_back_at="2026-08-20T00:00:00Z",
    )
    touching = create_release_request(
        slide_id=slide_id,
        requesting_institution="University Hospital",
        reason="touching loan",
        requested_out_at="2026-08-20T00:00:00Z",
        due_back_at="2026-08-25T00:00:00Z",
    )

    # Closed-interval semantics: starting exactly when the pending loan ends
    # still conflicts.
    resp = api.approve_release_request(touching["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_LOAN_INTERVAL_CONFLICT)


def test_release_loan_one_second_gap_approved(api):
    """PRD §3.8: "if any other release request for the same material is in
    `REQUESTED`, `APPROVED`, `SHIPPED`, or `OVERDUE` with a closed interval
    from `requested_out_at` to `due_back_at` that intersects this request's
    interval — and touching endpoints count as a conflict — approval is
    rejected with `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409); a `DENIED` or
    `RETURNED` request frees its interval."

    Design: Difficulty/resource_temporal_overlap/release_loan_closed_interval_touching_conflicts
    """
    ctx = setup_final_case(mrn="MRN-900", num_qc_slides=2)
    slide_id = ctx["slides"][0]["id"]
    r1 = create_release_request(
        slide_id=slide_id,
        requesting_institution="County Hospital",
        reason="board review",
        requested_out_at="2026-08-10T00:00:00Z",
        due_back_at="2026-08-20T00:00:00Z",
    )
    touching = create_release_request(
        slide_id=slide_id,
        requesting_institution="University Hospital",
        reason="touching loan",
        requested_out_at="2026-08-20T00:00:00Z",
        due_back_at="2026-08-25T00:00:00Z",
    )
    deny_release_request(touching["id"], reason="overlap")

    # A one-second gap after the pending loan's end does not intersect the
    # closed interval [08-10, 08-20T00:00:00Z].
    gapped = create_release_request(
        slide_id=slide_id,
        requesting_institution="University Hospital",
        reason="gapped loan",
        requested_out_at="2026-08-20T00:00:01Z",
        due_back_at="2026-08-25T00:00:00Z",
    )
    approved = approve_release_request(gapped["id"])
    assert approved["status"] == "APPROVED"
    assert get_release_request(r1["id"])["status"] == "REQUESTED", (
        "approving the gapped loan does not mutate the pending one"
    )


def test_release_ship_before_approve_rejected(api):
    """PRD §3.8: "Approving or denying a request not in `REQUESTED`, shipping
    one not `APPROVED`, or returning one not `SHIPPED` or `OVERDUE` is
    rejected with `ERR_RELEASE_WRONG_STATE` (HTTP 409)."

    Design: Corner/errors/release_ship_before_approve_rejected
    """
    ctx = setup_final_case(mrn="MRN-R6", num_qc_slides=2)
    r1 = create_release_request(slide_id=ctx["slides"][0]["id"], reason="review")

    resp = api.ship_release_request(r1["id"], HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_RELEASE_WRONG_STATE)
    after = get_release_request(r1["id"])
    assert after["status"] == "REQUESTED"
    assert after["shipped_at"] is None


def test_release_of_unembedded_block_rejected(api):
    """PRD §3.8: "The material itself must be releasable: a block must be
    `EMBEDDED` and a slide must be `QC_PASSED`, otherwise
    `ERR_MATERIAL_NOT_RELEASABLE` (HTTP 409)."

    Design: Corner/errors/release_of_unembedded_block_rejected
    """
    # FINAL case; block b2 was created but never embedded.
    ctx = setup_qc_passed_case(mrn="MRN-R7")
    case_id = ctx["case"]["id"]
    b2 = create_block(ctx["specimen"]["id"], block_label="A2")
    assign_case(case_id, ctx["pathologist"]["id"])
    submit_for_signout(case_id, ctx["pathologist"]["id"])
    sign_out_case(case_id, ctx["pathologist"]["id"])
    assert get_block(b2["id"])["status"] == "CREATED"

    resp = api.create_release_request(
        {
            "material_type": "BLOCK",
            "block_id": b2["id"],
            "requesting_institution": "County",
            "reason": "research",
            "requested_out_at": "2026-08-10T00:00:00Z",
            "due_back_at": "2026-08-20T00:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_RELEASABLE)


def test_release_overdue_sweep_and_late_return(api):
    """PRD §2.5: "Every release request in `SHIPPED` whose `due_back_at` is
    strictly before the new clock value transitions to `OVERDUE`, with
    equality likewise not overdue."
    PRD §3.8: "Return accepts a request in `SHIPPED` or `OVERDUE`, moves it to
    `RETURNED`, stamps `returned_at`, computes `returned_late` as true exactly
    when the return happens strictly after `due_back_at`, and flips `on_loan`
    back to false, restoring the material's availability."

    Design: Corner/state_machines/release_overdue_sweep_and_late_return
    """
    ctx = setup_final_case(mrn="MRN-S7", num_qc_slides=2)
    slide_id = ctx["slides"][0]["id"]
    r1 = create_release_request(
        slide_id=slide_id,
        requesting_institution="County Hospital",
        reason="review",
        requested_out_at="2026-08-10T00:00:00Z",
        due_back_at="2026-08-15T00:00:00Z",
    )
    approve_release_request(r1["id"])
    shipped = ship_release_request(r1["id"])
    assert shipped["status"] == "SHIPPED"
    assert get_slide(slide_id)["on_loan"] is True

    # Equality with due_back_at is not overdue.
    set_clock("2026-08-15T00:00:00Z")
    assert get_release_request(r1["id"])["status"] == "SHIPPED"

    # One second past, the sweep moves it to OVERDUE.
    set_clock("2026-08-15T00:00:01Z")
    assert get_release_request(r1["id"])["status"] == "OVERDUE"

    resp = api.return_release_request(r1["id"], HISTOTECH_HEADERS)
    returned = validate_success(resp, expected_status=200)
    assert returned["status"] == "RETURNED"
    assert returned["returned_late"] is True
    assert returned["returned_at"] is not None
    assert get_slide(slide_id)["on_loan"] is False, "availability restored"
