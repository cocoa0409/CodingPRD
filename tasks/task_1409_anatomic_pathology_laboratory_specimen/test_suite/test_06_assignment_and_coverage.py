"""Assignment eligibility and the deterministic selector, workload ledger,
reassign OCC, and coverage-window temporal rules."""
from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    accession_specimen,
    assign_case,
    create_case,
    create_coverage_window,
    create_patient,
    create_pathologist,
    get_case,
    get_pathologist,
    set_clock,
    setup_pending_signout_case,
    setup_qc_passed_case,
    setup_workup_case,
    sign_out_case,
    submit_for_signout,
    validate_error,
    validate_success,
)


def test_assign_ineligible_explicit_and_empty_pool(api):
    """PRD §3.5: "Either way the target must be eligible: `active` must be
    true, the pathologist's `subspecialties` must contain the case's
    `subspecialty`, and no `ACTIVE` coverage window of type `UNAVAILABLE` may
    contain the current logical clock under closed containment"
    PRD §3.5: "An explicitly named pathologist who fails eligibility is
    rejected with `ERR_PATHOLOGIST_INELIGIBLE` (HTTP 422)."
    PRD §3.5: "an empty pool is rejected with `ERR_NO_ELIGIBLE_PATHOLOGIST`
    (HTTP 422)."

    Design: Corner/validations/assign_ineligible_explicit_and_empty_pool
    """
    patient = create_patient(mrn="MRN-VE", full_name="Val Fourteen")
    inactive = create_pathologist(full_name="Dr Inactive", active=False)
    case = create_case(patient["id"], subspecialty="GI")

    resp = api.assign_case(case["id"], {"pathologist_id": inactive["id"]}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_PATHOLOGIST_INELIGIBLE)

    resp = api.assign_case(case["id"], {}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PATHOLOGIST)

    assert get_case(case["id"])["assigned_pathologist_id"] is None, (
        "both failures leave the case unassigned"
    )


def test_selector_lowest_workload_then_earliest_created(api):
    """PRD §3.5: "The selector ranks the same eligibility pool by
    `workload_score` ascending, breaks ties by `last_assigned_at` ascending
    with never-assigned pathologists (null) first, and breaks remaining ties
    by the pathologist's `created_at` ascending"
    PRD §3.5: "A successful assignment sets `assigned_pathologist_id`, stamps
    the assignee's `last_assigned_at`, and recomputes the workload of both the
    former and the new assignee."

    Design: Corner/endpoints/selector_lowest_workload_then_earliest_created
    """
    patient = create_patient(mrn="MRN-E1", full_name="Ep One")
    p1 = create_pathologist(full_name="Dr Early")
    set_clock("2026-08-01T00:01:00Z")
    p2 = create_pathologist(full_name="Dr Late")
    c1 = create_case(patient["id"], subspecialty="GI")
    c2 = create_case(patient["id"], subspecialty="GI")

    resp = api.assign_case(c1["id"], {}, ADMIN_HEADERS)
    assigned1 = validate_success(resp, expected_status=200)
    assert assigned1["assigned_pathologist_id"] == p1["id"], (
        "tie on workload 0.0 and null last_assigned_at breaks by created_at ascending"
    )

    resp = api.assign_case(c2["id"], {}, ADMIN_HEADERS)
    assigned2 = validate_success(resp, expected_status=200)
    assert assigned2["assigned_pathologist_id"] == p2["id"], (
        "p1 now carries workload 1.0, so the selector picks p2 at 0.0"
    )

    p1_after = get_pathologist(p1["id"])
    assert p1_after["workload_score"] == 1.0, "one open SIMPLE case weighs 1"
    assert p1_after["last_assigned_at"] is not None


def test_workload_drops_to_zero_on_signout(api):
    """PRD §3.5: "A pathologist's `workload_score` sums a per-class weight over
    their assigned cases in `OPEN`, `WORKUP`, `PENDING_SIGNOUT`, or `AMENDING`
    — 1 for a `SIMPLE` case, 2 for `MODERATE`, 3 for `COMPLEX`, 5 for
    `HIGH_COMPLEXITY`"
    PRD §3.6: "the assignee's workload is recomputed as the case leaves the
    open set."

    Design: Corner/endpoints/workload_drops_to_zero_on_signout
    """
    ctx = setup_pending_signout_case(mrn="MRN-E2")
    p1 = ctx["pathologist"]
    before = get_pathologist(p1["id"])
    assert before["workload_score"] == 1.0, "one open SIMPLE case before sign-out"

    sign_out_case(ctx["case"]["id"], p1["id"])

    after = get_pathologist(p1["id"])
    assert after["workload_score"] == 0.0, "the FINAL case left the open set"


def test_workload_conservation_assign_raises_score(api):
    """PRD §3.5: "A pathologist's `workload_score` sums a per-class weight over
    their assigned cases in `OPEN`, `WORKUP`, `PENDING_SIGNOUT`, or `AMENDING`
    — 1 for a `SIMPLE` case, 2 for `MODERATE`, 3 for `COMPLEX`, 5 for
    `HIGH_COMPLEXITY`"
    PRD §3.5: "A successful assignment sets `assigned_pathologist_id`, stamps
    the assignee's `last_assigned_at`, and recomputes the workload of both the
    former and the new assignee."

    Design: Difficulty/compensating_invariant/workload_conservation_on_reassign
    """
    p1 = create_pathologist(full_name="Dr First")
    create_pathologist(full_name="Dr Second")
    ctx = setup_workup_case(
        mrn="MRN-951",
        specimen_type="RESECTION",
        container_count=2,
        num_blocks=1,
        slides_per_block=1,
    )
    case_id = ctx["case"]["id"]
    # RESECTION base 3 + 1 block + 1 slide x 0.5 = 4.5 -> MODERATE (weight 2).
    assert get_case(case_id)["complexity_class"] == "MODERATE"
    assert get_pathologist(p1["id"])["workload_score"] == 0.0

    assign_case(case_id, p1["id"])

    after = get_pathologist(p1["id"])
    assert after["workload_score"] == 2.0, "COMPLEXITY_WEIGHT[MODERATE] added"
    assert after["last_assigned_at"] is not None


def test_workload_conservation_reassign_restores_score(api):
    """PRD §3.5: "Reassignment legitimately supersedes the current assignment:
    `assigned_pathologist_id` is swapped, the new assignee's `last_assigned_at`
    is stamped, and both pathologists' workloads are recomputed."
    PRD §2.8: "The case-reassignment endpoint (`POST
    /pathology/cases/{id}/reassign`) requires the request to carry
    `expected_case_version`, holding the `version` of the case as the client
    last read it."

    Design: Difficulty/compensating_invariant/workload_conservation_on_reassign
    """
    p1 = create_pathologist(full_name="Dr First")
    p2 = create_pathologist(full_name="Dr Second")
    ctx = setup_workup_case(
        mrn="MRN-951",
        specimen_type="RESECTION",
        container_count=2,
        num_blocks=1,
        slides_per_block=1,
    )
    case_id = ctx["case"]["id"]
    assign_case(case_id, p1["id"])
    assert get_pathologist(p1["id"])["workload_score"] == 2.0
    case_version = get_case(case_id)["version"]

    resp = api.reassign_case(
        case_id,
        {"pathologist_id": p2["id"], "expected_case_version": case_version},
        ADMIN_HEADERS,
    )
    reassigned = validate_success(resp, expected_status=200)
    assert reassigned["assigned_pathologist_id"] == p2["id"]

    assert get_pathologist(p1["id"])["workload_score"] == 0.0, (
        "the compensating reassign restored p1's ledger"
    )
    assert get_pathologist(p2["id"])["workload_score"] == 2.0, (
        "p2 absorbed the MODERATE case"
    )


def test_occ_stale_reassign_returns_412(api):
    """PRD §2.8: "If the case's current `version` differs — because another
    writer has advanced it since — the reassignment is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the client from silently
    overwriting an assignment it never observed."

    Design: Corner/complexity_layers/occ_stale_reassign_returns_412
    """
    p1 = create_pathologist(full_name="Dr O1")
    p2 = create_pathologist(full_name="Dr O2")
    p3 = create_pathologist(full_name="Dr O3")
    ctx = setup_workup_case(mrn="MRN-CL1", num_blocks=0)
    case_id = ctx["case"]["id"]
    assign_case(case_id, p1["id"])
    observed_version = get_case(case_id)["version"]

    # First reassign with the current version succeeds and advances it.
    resp = api.reassign_case(
        case_id,
        {"pathologist_id": p2["id"], "expected_case_version": observed_version},
        ADMIN_HEADERS,
    )
    validate_success(resp, expected_status=200)

    # Replaying the previously observed version is rejected.
    resp = api.reassign_case(
        case_id,
        {"pathologist_id": p3["id"], "expected_case_version": observed_version},
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)
    assert get_case(case_id)["assigned_pathologist_id"] == p2["id"], (
        "the stale request changed nothing"
    )


def test_assign_reassign_cancel_state_gates(api):
    """PRD §3.5: "Cases reach a signing pathologist through assignment, a
    `LabAdmin` action valid while the case is `OPEN` or `WORKUP` (otherwise
    `ERR_CASE_NOT_ASSIGNABLE`, HTTP 409)."
    PRD §3.5: "Reassignment — valid while the case is `WORKUP` or
    `PENDING_SIGNOUT`, otherwise `ERR_CASE_NOT_REASSIGNABLE` (HTTP 409)"
    PRD §3.6: "A `LabAdmin` cancels a case, supplying a `reason`, while the
    case is `OPEN` or `WORKUP`; cancelling from any other status is rejected
    with `ERR_CASE_NOT_CANCELLABLE` (HTTP 409)."

    Design: Corner/errors/assign_reassign_cancel_state_gates
    """
    patient = create_patient(mrn="MRN-R9", full_name="Err Nine")
    p1 = create_pathologist(full_name="Dr One")
    p2 = create_pathologist(full_name="Dr Two")
    # Case X stays OPEN (never worked up).
    case_x = create_case(patient["id"], subspecialty="GI")
    # Case Y is worked up to PENDING_SIGNOUT.
    ctx_y = setup_qc_passed_case(mrn="MRN-R9B")
    case_y = ctx_y["case"]
    assign_case(case_y["id"], ctx_y["pathologist"]["id"])
    submit_for_signout(case_y["id"], ctx_y["pathologist"]["id"])
    assert get_case(case_y["id"])["status"] == "PENDING_SIGNOUT"

    resp = api.assign_case(case_y["id"], {"pathologist_id": p2["id"]}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ASSIGNABLE)

    x_version = get_case(case_x["id"])["version"]
    resp = api.reassign_case(
        case_x["id"],
        {"pathologist_id": p1["id"], "expected_case_version": x_version},
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_REASSIGNABLE)

    resp = api.cancel_case(case_y["id"], {"reason": "too late"}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_CANCELLABLE)


def test_consult_service_window_half_open_adjacency(api):
    """PRD §3.5: "a new `CONSULT_SERVICE` window must not overlap any other
    `ACTIVE` `CONSULT_SERVICE` window under half-open containment — the
    interval runs from `start_at` inclusive to `end_at` exclusive, so touching
    endpoints where one window ends exactly when another begins are allowed"

    Design: Difficulty/resource_temporal_overlap/consult_service_window_half_open_adjacency
    """
    p1 = create_pathologist(full_name="Dr Window")
    create_coverage_window(
        p1["id"], "CONSULT_SERVICE", "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z"
    )
    # Touching the existing window's end is not an overlap under [start, end).
    resp = api.create_coverage_window(
        p1["id"],
        {
            "window_type": "CONSULT_SERVICE",
            "start_at": "2026-08-03T12:00:00Z",
            "end_at": "2026-08-03T14:00:00Z",
        },
        ADMIN_HEADERS,
    )
    adjacent = validate_success(resp, expected_status=201)
    assert adjacent["status"] == "ACTIVE"


def test_consult_service_window_interior_overlap_rejected(api):
    """PRD §3.5: "a new `CONSULT_SERVICE` window must not overlap any other
    `ACTIVE` `CONSULT_SERVICE` window under half-open containment — the
    interval runs from `start_at` inclusive to `end_at` exclusive, so touching
    endpoints where one window ends exactly when another begins are allowed —
    with overlaps rejected as `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/consult_service_window_half_open_adjacency
    """
    p1 = create_pathologist(full_name="Dr Window")
    create_coverage_window(
        p1["id"], "CONSULT_SERVICE", "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z"
    )
    # [11:00, 13:00) intersects [10:00, 12:00) in its interior.
    resp = api.create_coverage_window(
        p1["id"],
        {
            "window_type": "CONSULT_SERVICE",
            "start_at": "2026-08-03T11:00:00Z",
            "end_at": "2026-08-03T13:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP)


def test_unavailability_buffer_60_minute_boundary(api):
    """PRD §3.5: "a new `UNAVAILABLE` window must keep a buffer of at least 60
    minutes from every `ACTIVE` `CONSULT_SERVICE` window, with smaller gaps
    rejected as `ERR_UNAVAILABILITY_BUFFER_VIOLATION` (HTTP 409)."

    Design: Corner/validations/unavailability_buffer_60_minute_boundary
    """
    p1 = create_pathologist(full_name="Dr Buffer")
    create_coverage_window(
        p1["id"], "CONSULT_SERVICE", "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z"
    )
    # 30-minute gap violates the 60-minute buffer.
    resp = api.create_coverage_window(
        p1["id"],
        {
            "window_type": "UNAVAILABLE",
            "start_at": "2026-08-03T12:30:00Z",
            "end_at": "2026-08-03T14:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAVAILABILITY_BUFFER_VIOLATION)
    # Exactly 60 minutes satisfies "at least 60 minutes".
    resp = api.create_coverage_window(
        p1["id"],
        {
            "window_type": "UNAVAILABLE",
            "start_at": "2026-08-03T13:00:00Z",
            "end_at": "2026-08-03T14:00:00Z",
        },
        ADMIN_HEADERS,
    )
    ok = validate_success(resp, expected_status=201)
    assert ok["status"] == "ACTIVE"


def test_window_end_not_after_start_returns_400(api):
    """PRD §2.9: "The priority-3 shape validation rejects with
    `ERR_INVALID_REQUEST` (HTTP 400) on any of: a missing required field, an
    invalid enum member, an out-of-range number such as a `container_count`
    below 1 or a `consumption_pct` of 0 or less, a window `end_at` not strictly
    after its `start_at`, a loan `due_back_at` not strictly after its
    `requested_out_at`, a reflex rule whose `followup_stain_type` equals its
    `trigger_stain_type`, or a release request whose identifier field does not
    match its declared `material_type`."
    PRD §3.5: "A `LabAdmin` creates a window for a pathologist with a
    `window_type` of `CONSULT_SERVICE` (bookable consult duty) or `UNAVAILABLE`
    (no consults or assignments), a `start_at`, and an `end_at` that must be
    strictly after the start."

    Design: Corner/validations/window_end_not_after_start_returns_400
    """
    p1 = create_pathologist(full_name="Dr Shape")
    resp = api.create_coverage_window(
        p1["id"],
        {
            "window_type": "CONSULT_SERVICE",
            "start_at": "2026-08-03T10:00:00Z",
            "end_at": "2026-08-03T10:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_coverage_window_cancel_twice_rejected(api):
    """PRD §3.5: "Windows are born `ACTIVE` and can be cancelled, moving to
    `CANCELLED`; cancelling a window that is not `ACTIVE` is rejected with
    `ERR_COVERAGE_WINDOW_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/coverage_window_cancel_twice_rejected
    """
    p1 = create_pathologist(full_name="Dr W")
    window = create_coverage_window(
        p1["id"], "CONSULT_SERVICE", "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z"
    )
    resp = api.cancel_coverage_window(window["id"], ADMIN_HEADERS)
    validate_success(resp, expected_status=200)

    resp = api.cancel_coverage_window(window["id"], ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_NOT_ACTIVE)
