"""Validation & install-scheduling tests: priority-conflict ordering, cross-entity
state preconditions, crew window overlap and day-capacity, and the standalone
validation/error corner instances.

Queue A: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap.
Queue B: validations + errors corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
)

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]
_CREW = TEST_USERS["install_crew_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================

def test_declined_financing_approve_reports_invalid_state_over_dti(api):
    """PRD §3.13: "Authentication of the headers comes first (`ERR_UNAUTHENTICATED`),
    then the role-permission check (`ERR_FORBIDDEN_ROLE`), then existence of every
    referenced resource id resolved left-to-right in the path (`ERR_NOT_FOUND`),
    then — for customer-scoped operations — project ownership
    (`ERR_NOT_PROJECT_OWNER`). Domain-specific referential and state checks follow:
    ... for any transition, that the target entity is in a state from which the
    transition is defined (`ERR_INVALID_STATE`)".
    PRD §3.12: "an approval attempt where the `dti_ratio` exceeds 0.20 is rejected
    with `ERR_DTI_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_quote_not_approved_beats_dti
    """
    # income 3700000, amount 2000000, term 36 -> dti 0.2032 (> 0.20), and the
    # application has been DECLINED so the transition is no longer defined.
    cust, proj, fa = fx.setup_submitted_financing(
        annual_income_cents=3_700_000, amount_cents=2_000_000, term_months=36)
    assert fa["dti_ratio"] == 0.2032, f"setup expected dti 0.2032, got {fa['dti_ratio']}"
    validate_success(api.decline_financing_application(fa["id"], _ADMIN))
    resp = api.approve_financing_application(fa["id"], _ADMIN)
    # State check precedes the fiscal DTI check -> ERR_INVALID_STATE (409).
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submitted_financing_over_dti_reports_dti_exceeded(api):
    """PRD §3.12: "an approval attempt where the `dti_ratio` exceeds 0.20 is rejected
    with `ERR_DTI_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_quote_not_approved_beats_dti
    """
    # With the state precondition satisfied (application still SUBMITTED), the fiscal
    # DTI check is what fires — isolating the lower-priority error.
    cust, proj, fa = fx.setup_submitted_financing(
        annual_income_cents=3_700_000, amount_cents=2_000_000, term_months=36)
    assert fa["dti_ratio"] == 0.2032, f"setup expected dti 0.2032, got {fa['dti_ratio']}"
    resp = api.approve_financing_application(fa["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value)


def test_unknown_crew_reports_not_found_over_window_conflict(api):
    """PRD §3.13: "then existence of every referenced resource id resolved
    left-to-right in the path (`ERR_NOT_FOUND`) ... Domain-specific referential and
    state checks follow ... Install scheduling layers its own checks — crew
    certification (`ERR_CREW_NOT_CERTIFIED`), window-before-ready
    (`ERR_WINDOW_BEFORE_READY`), crew window conflict (`ERR_CREW_WINDOW_CONFLICT`)".
    PRD §2.6: "the server validates them from left to right and rejects the request
    with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to
    an existing entity ... This existence check applies to every path identifier and
    to every resource id referenced in a request body."

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_unknown_crew_beats_window_conflict
    """
    # A real crew has a booked window; the trigger references a non-existent crew_id
    # AND a window overlapping the real crew's booked window.
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z")
    resp = api.create_install_job(proj["id"], {
        "material_order_id": mo["id"],
        "crew_id": NON_EXISTENT_UUID,
        "window_start": "2026-05-06T10:00:00Z",
        "window_end": "2026-05-06T15:00:00Z",
    }, _SCHED)
    # Existence (404) is checked before the temporal window-conflict (409).
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_window_conflict_reported_when_crew_exists(api):
    """PRD §3.9: "The proposed window, treated as the half-open interval from
    `window_start` up to but not including `window_end`, must not overlap any
    non-`CANCELLED` install job already booked for the same crew; an overlap yields
    `ERR_CREW_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_unknown_crew_beats_window_conflict
    """
    # With the existence check satisfied (real, certified crew on a ready project),
    # the temporal window-conflict is the error that fires — isolating the
    # lower-priority check that the unknown-crew test pre-empts.
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z")
    # A second ready project shares the same real crew; overlapping window.
    cust2, proj2, meas2, quote2, mo2 = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    resp = api.create_install_job(proj2["id"], {
        "material_order_id": mo2["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T10:00:00Z",
        "window_end": "2026-05-06T15:00:00Z",
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================

def test_material_order_requires_approved_quote(api):
    """PRD §3.8: "The referenced quote must be `APPROVED` and `is_active` on the
    same project; otherwise the request is rejected with `ERR_QUOTE_NOT_APPROVED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/material_order_requires_quote_approved
    """
    # The project must be SOLD so the higher-priority state check (§3.13: "for any
    # transition, that the target entity is in a state from which the transition is
    # defined (ERR_INVALID_STATE)") passes, isolating the quote-approved check.
    # An approved quote drives the project to SOLD; a second DRAFT quote on the same
    # project is not APPROVED, so placing against it yields ERR_QUOTE_NOT_APPROVED.
    cust, proj, meas, quote = fx.setup_approved_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    draft = fx.create_draft_quote(proj["id"], meas["id"], scope="REFACE")
    resp = api.create_material_order(proj["id"], {"quote_id": draft["id"]}, _SCHED)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_APPROVED.value)


def test_material_order_against_approved_quote_succeeds(api):
    """PRD §3.8: "The referenced quote must be `APPROVED` and `is_active` on the
    same project ... Placing the order requires the project's `status` to be `SOLD`
    and creates the material order in the `PLACED` state".

    Design: Difficulty/cross_entity_state_dependency/material_order_requires_quote_approved
    """
    fx.reset_clock()
    cust, proj, meas, quote = fx.setup_approved_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    mo = validate_success(
        api.create_material_order(proj["id"], {"quote_id": quote["id"]}, _SCHED),
        expected_status=201)
    assert mo["status"] == "PLACED", f"expected PLACED on approved quote, got {mo['status']}"
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    assert proj_read["status"] == "IN_PRODUCTION", \
        f"placement must bubble project to IN_PRODUCTION, got {proj_read['status']}"


def test_install_start_requires_material_order_ready(api):
    """PRD §3.10: "An `InstallCrew` starts a scheduled job, moving it
    `SCHEDULED → IN_PROGRESS`, which is permitted only when the job is in
    `SCHEDULED`, the linked material order is in `READY` or `RECEIVED`, and the
    current time is at or after the job's `window_start`."

    Design: Difficulty/cross_entity_state_dependency/install_start_requires_material_order_ready
    """
    fx.reset_clock()
    # Build IN_PRODUCTION with MaterialOrder still PLACED (never marked ready), an
    # InstallJob SCHEDULED, and clock at window_start.
    cust, proj, meas, quote, mo = fx.setup_in_production(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    crew = fx.create_crew(skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)
    ij = fx.schedule_install_job(proj["id"], mo["id"], crew["id"],
                                 window_start="2026-06-01T08:00:00Z",
                                 window_end="2026-06-01T17:00:00Z")
    fx.set_clock("2026-06-01T08:00:00Z")
    resp = api.start_install_job(ij["id"], _CREW)
    # Order still PLACED (not READY/RECEIVED) -> the transition is undefined.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_install_start_succeeds_when_material_order_ready(api):
    """PRD §3.10: "An `InstallCrew` starts a scheduled job, moving it
    `SCHEDULED → IN_PROGRESS`, which is permitted only when the job is in
    `SCHEDULED`, the linked material order is in `READY` or `RECEIVED`, and the
    current time is at or after the job's `window_start`."

    Design: Difficulty/cross_entity_state_dependency/install_start_requires_material_order_ready
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z")
    fx.set_clock("2026-05-06T08:00:00Z")  # at window_start, material order READY.
    started = validate_success(api.start_install_job(ij["id"], _CREW))
    assert started["status"] == "IN_PROGRESS", \
        f"expected IN_PROGRESS when material order READY, got {started['status']}"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================

def test_crew_window_half_open_overlap_rejected(api):
    """PRD §3.9: "The proposed window, treated as the half-open interval from
    `window_start` up to but not including `window_end`, must not overlap any
    non-`CANCELLED` install job already booked for the same crew; an overlap yields
    `ERR_CREW_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap_rejected
    """
    fx.reset_clock()
    # Crew E booked 08:00-17:00 on a first ready project.
    cust_a, proj_a, meas_a, quote_a, mo_a = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    crew = fx.create_crew(name="Crew E", skill_finishes=("WOOD_VENEER",), daily_job_capacity=5)
    fx.schedule_install_job(proj_a["id"], mo_a["id"], crew["id"],
                            window_start="2026-05-06T08:00:00Z",
                            window_end="2026-05-06T17:00:00Z")
    # A second ready project shares Crew E; trigger books overlapping 10:00-15:00.
    cust_b, proj_b, meas_b, quote_b, mo_b = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    resp = api.create_install_job(proj_b["id"], {
        "material_order_id": mo_b["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T10:00:00Z",
        "window_end": "2026-05-06T15:00:00Z",
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value)


def test_crew_window_adjacent_at_end_does_not_conflict(api):
    """PRD §3.9: "The proposed window, treated as the half-open interval from
    `window_start` up to but not including `window_end`, must not overlap any
    non-`CANCELLED` install job already booked for the same crew".

    Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap_rejected
    """
    fx.reset_clock()
    # Crew booked 08:00-17:00; a second window starting exactly at 17:00 (the prior
    # window_end, exclusive) does not overlap under half-open semantics.
    cust_a, proj_a, meas_a, quote_a, mo_a = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    crew = fx.create_crew(name="Crew Adj", skill_finishes=("WOOD_VENEER",), daily_job_capacity=5)
    fx.schedule_install_job(proj_a["id"], mo_a["id"], crew["id"],
                            window_start="2026-05-06T08:00:00Z",
                            window_end="2026-05-06T17:00:00Z")
    cust_b, proj_b, meas_b, quote_b, mo_b = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    job = validate_success(api.create_install_job(proj_b["id"], {
        "material_order_id": mo_b["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T17:00:00Z",
        "window_end": "2026-05-06T19:00:00Z",
    }, _SCHED), expected_status=201)
    assert job["status"] == "SCHEDULED", \
        f"adjacent (gap=0) window must be accepted, got {job['status']}"


def test_crew_daily_capacity_blocks_third_nonoverlapping_job(api):
    """PRD §3.9: "The number of non-`CANCELLED` install jobs already booked for that
    crew on the same `install_day` must remain below the crew's `daily_job_capacity`
    — once the count reaches capacity, the next booking is blocked with
    `ERR_CREW_DAY_FULL` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate_blocks_third_nonoverlapping_job
    """
    fx.reset_clock()
    crew = fx.create_crew(name="Crew F", skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)

    def ready_project():
        c, p, m, q, mo = fx.setup_material_order_ready(
            scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
            ready_clock="2026-05-05T00:00:00Z")
        return p, mo

    p1, mo1 = ready_project()
    fx.schedule_install_job(p1["id"], mo1["id"], crew["id"],
                            window_start="2026-05-06T08:00:00Z",
                            window_end="2026-05-06T10:00:00Z")
    p2, mo2 = ready_project()
    fx.schedule_install_job(p2["id"], mo2["id"], crew["id"],
                            window_start="2026-05-06T11:00:00Z",
                            window_end="2026-05-06T13:00:00Z")
    # Two non-overlapping same-day jobs already booked (capacity = 2). The third,
    # non-overlapping, same-day window is blocked on the per-day count.
    p3, mo3 = ready_project()
    resp = api.create_install_job(p3["id"], {
        "material_order_id": mo3["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T14:00:00Z",
        "window_end": "2026-05-06T16:00:00Z",
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_DAY_FULL.value)


def test_crew_second_same_day_job_allowed_below_capacity(api):
    """PRD §3.9: "The number of non-`CANCELLED` install jobs already booked for that
    crew on the same `install_day` must remain below the crew's `daily_job_capacity`
    — once the count reaches capacity, the next booking is blocked".

    Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate_blocks_third_nonoverlapping_job
    """
    fx.reset_clock()
    crew = fx.create_crew(name="Crew Cap", skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)

    def ready_project():
        c, p, m, q, mo = fx.setup_material_order_ready(
            scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
            ready_clock="2026-05-05T00:00:00Z")
        return p, mo

    p1, mo1 = ready_project()
    fx.schedule_install_job(p1["id"], mo1["id"], crew["id"],
                            window_start="2026-05-06T08:00:00Z",
                            window_end="2026-05-06T10:00:00Z")
    # One same-day job booked (count=1 < capacity=2); a second is still allowed.
    p2, mo2 = ready_project()
    job = validate_success(api.create_install_job(p2["id"], {
        "material_order_id": mo2["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T11:00:00Z",
        "window_end": "2026-05-06T13:00:00Z",
    }, _SCHED), expected_status=201)
    assert job["status"] == "SCHEDULED", \
        f"second same-day job below capacity must be accepted, got {job['status']}"


# ===========================================================================
# Queue B — validations corner instances
# ===========================================================================

def test_quote_create_measure_from_other_project_mismatch(api):
    """PRD §3.3: "The referenced `measure_id` must belong to a measure whose
    `project_id` equals the project being quoted; a mismatch is rejected with
    `ERR_MEASURE_PROJECT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/quote_create_measure_belongs_to_other_project_mismatch
    """
    cust = fx.create_customer()
    proj_a = fx.create_project(cust["id"], address_line="A Way")
    proj_b = fx.create_project(cust["id"], address_line="B Way")
    meas_b = fx.schedule_measure(proj_b["id"])
    meas_b = fx.complete_measure(proj_b["id"], meas_b["id"])
    resp = api.create_quote(proj_a["id"], {"measure_id": meas_b["id"], "scope": "REFACE"}, _SALES)
    validate_error(resp, ApiErrorId.ERR_MEASURE_PROJECT_MISMATCH.value)


def test_install_window_before_ready_rejected(api):
    """PRD §3.9: "The `window_start` must be at or after the linked material order's
    `ready_at` — installation cannot begin before materials arrive — and an earlier
    start yields `ERR_WINDOW_BEFORE_READY` (HTTP 409)."

    Design: Corner/validations/install_window_before_ready_rejected
    """
    fx.reset_clock()
    # MaterialOrder PLACED with ready_at 2026-05-04 (REFACE/WOOD_VENEER 25ft -> 33d).
    cust, proj, meas, quote, mo = fx.setup_in_production(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    assert mo["ready_at"].startswith("2026-05-04"), \
        f"setup expected ready_at 2026-05-04, got {mo['ready_at']}"
    crew = fx.create_crew(skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)
    resp = api.create_install_job(proj["id"], {
        "material_order_id": mo["id"],
        "crew_id": crew["id"],
        "window_start": "2026-04-20T08:00:00Z",  # before ready_at.
        "window_end": "2026-04-20T17:00:00Z",
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_WINDOW_BEFORE_READY.value)


def test_install_crew_not_certified_rejected(api):
    """PRD §3.9: "The assigned crew must be active and certified for the project's
    `finish_code` (that is, the measure's `finish_code` must appear in the crew's
    `skill_finishes`); a crew that is inactive or uncertified yields
    `ERR_CREW_NOT_CERTIFIED` (HTTP 422)."

    Design: Corner/validations/install_crew_not_certified_for_finish_rejected
    """
    # Project finish SOLID_WOOD; crew certified only for LAMINATE.
    cust, proj, meas, quote, mo = fx.setup_material_order_ready(
        scope="REDOOR", linear_feet=32, door_count=24, finish_code="SOLID_WOOD",
        ready_clock="2026-06-15T00:00:00Z")
    crew = fx.create_crew(name="Laminate Only", skill_finishes=("LAMINATE",), daily_job_capacity=2)
    resp = api.create_install_job(proj["id"], {
        "material_order_id": mo["id"],
        "crew_id": crew["id"],
        "window_start": "2026-06-16T08:00:00Z",
        "window_end": "2026-06-16T17:00:00Z",
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED.value)


def test_install_window_end_not_after_start_rejected(api):
    """PRD §3.9: "Finally, `window_end` must be strictly greater than `window_start`,
    or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/install_window_end_not_after_start_invalid
    """
    cust, proj, meas, quote, mo = fx.setup_material_order_ready(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z")
    crew = fx.create_crew(skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)
    resp = api.create_install_job(proj["id"], {
        "material_order_id": mo["id"],
        "crew_id": crew["id"],
        "window_start": "2026-05-06T08:00:00Z",
        "window_end": "2026-05-06T08:00:00Z",  # equal -> not strictly greater.
    }, _SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_warranty_claim_on_non_installed_project_rejected(api):
    """PRD §3.11: "A claim may be submitted only for a project that is `INSTALLED` or
    `CLOSED`; an attempt against any other project state — or any warranty action
    invalid for the claim's current state — is rejected with `ERR_OUT_OF_WARRANTY`
    (HTTP 409)."

    Design: Corner/validations/warranty_claim_on_non_installed_project_out_of_warranty
    """
    cust, proj = fx.create_customer_and_project()  # LEAD, never installed.
    resp = api.create_warranty_claim(
        proj["id"], {"description": "nothing installed yet"}, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_OUT_OF_WARRANTY.value)


# ===========================================================================
# Queue B — errors corner instance
# ===========================================================================

def test_warranty_adjudicate_approve_uncovered_claim_rejected(api):
    """PRD §3.11: "approving a claim whose `covered` flag is false (it falls outside
    the warranty window) is rejected with `ERR_WARRANTY_NOT_COVERED` (HTTP 409)."
    PRD §3.11: "a claim is covered when the current time is at or before the
    install-completion instant plus the warranty window of 90 days, and uncovered
    otherwise."

    Design: Corner/errors/warranty_adjudicate_approve_uncovered_claim_not_covered
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_installed_project(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z",
        start_clock="2026-05-06T08:00:00Z")
    # Advance the clock far past install completion + 90 days, then file a claim.
    fx.set_clock("2028-01-01T00:00:00Z")
    # PRD §4: "Operations that create a brand-new resource return 201 Created."
    claim = validate_success(api.create_warranty_claim(
        proj["id"], {"description": "late claim, out of window"},
        make_customer_headers(cust["id"])),
        expected_status=201)
    assert claim["covered"] is False, "claim filed beyond warranty window must be uncovered"
    resp = api.adjudicate_warranty_claim(claim["id"], {"decision": "APPROVE"}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_COVERED.value)
