"""Validation, cross-entity dependency, temporal overlap, OCC, and precedence
tests. Pinned to PRD §2.7, §2.8, §2.9, §3.6, §3.7, §3.8.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    fixtures, factories, ApiErrorId,
    make_wound_clinician_headers, make_hyperbaric_tech_headers,
)


# =============================================================================
# priority_pair_validation_conflict (queue A) — PRD §2.9 ordering
# =============================================================================

def test_stale_version_beats_budget_on_supply_order(api):
    """PRD §2.9: "When several checks could apply to one request, they are
    evaluated in a fixed priority order, and the first failure is the one
    reported. The order is: ... (4) the optimistic-concurrency version check of
    §2.7, failing with ERR_STALE_PLAN_VERSION; ... (12) the supply budget check,
    failing with ERR_SUPPLY_BUDGET_EXCEEDED".
    A second supply submission carrying a stale expected_plan_version AND over
    budget is rejected on the higher-priority OCC check with
    ERR_STALE_PLAN_VERSION (412).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_supply_order
    """
    base = fixtures.setup_active_plan(budget_cents=200, mrn="M9")
    wc_id = base["wc_id"]
    wc_headers = make_wound_clinician_headers(wc_id)
    stale_version = fixtures.get_plan_version(base["plan_id"], wc_headers)
    # first submit (153c) bumps plan version
    validate_success(api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], stale_version, line_items=factories.THREE_LINES_153),
        wc_headers), 201)
    # second submit reuses stale version AND would exceed budget (153+153>200)
    resp = api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], stale_version, line_items=factories.THREE_LINES_153),
        wc_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)


def test_role_mismatch_beats_slot_conflict_on_debridement(api):
    """PRD §2.9: "(7) the debridement clinician-role check, failing with
    ERR_CLINICIAN_ROLE_MISMATCH; ... (10) the clinician temporal-overlap check,
    failing with ERR_CLINICIAN_SLOT_CONFLICT".
    A debridement referencing a HYPERBARIC clinician whose window also overlaps
    an existing booking returns the higher-priority ERR_CLINICIAN_ROLE_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_debridement
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M10", with_hyperbaric=True)
    wc_id = base["wc_id"]
    ht_id = base["ht_id"]
    # existing WOUND-clinician booking 09:00-10:00 to create the overlap window
    fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    # trigger: HYPERBARIC clinician (wrong role) AND overlapping 09:30-10:30
    resp = api.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            base["plan_id"], ht_id,
            window_start="2026-05-02T09:30:00Z", window_end="2026-05-02T10:30:00Z"),
        make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_ROLE_MISMATCH.value)


def test_stale_version_beats_budget_persists_nothing(api):
    """PRD §2.9: "the first failure is the one reported" with OCC at priority (4)
    ahead of the budget check at (12). PRD §3.6: "The plan's
    provisional_covered_cents therefore always equals the sum of covered_cents
    across that plan's supply orders whose status is SUBMITTED or APPROVED."
    When the stale-version check wins, only the first (successful) 153c order is
    reflected in provisional_covered_cents; the rejected second order persists
    nothing.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_supply_order
    """
    base = fixtures.setup_active_plan(budget_cents=200, mrn="M9b")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    stale_version = fixtures.get_plan_version(base["plan_id"], wc_headers)
    validate_success(api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], stale_version, line_items=factories.THREE_LINES_153),
        wc_headers), 201)
    resp = api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], stale_version, line_items=factories.THREE_LINES_153),
        wc_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 153, \
        f"only the first order should count, got {plan['provisional_covered_cents']}"


def test_role_mismatch_beats_slot_conflict_no_procedure_created(api):
    """PRD §2.9: "(7) the debridement clinician-role check ... (10) the clinician
    temporal-overlap check" — the lower-numbered role check wins. PRD §3.7:
    debridement requires the referenced clinician's role_kind to be WOUND.
    A wrong-role + overlapping debridement is rejected on
    ERR_CLINICIAN_ROLE_MISMATCH and no new procedure is scheduled on that
    clinician.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_debridement
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M10b", with_hyperbaric=True)
    wc_id = base["wc_id"]
    ht_id = base["ht_id"]
    fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    resp = api.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            base["plan_id"], ht_id,
            window_start="2026-05-02T09:30:00Z", window_end="2026-05-02T10:30:00Z"),
        make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_ROLE_MISMATCH.value)
    data, meta = validate_paginated(
        api.list_debridement_procedures(fixtures.INTAKE, params={"clinician_id": ht_id}))
    assert len(data) == 0, "no procedure should be created on the mismatched clinician"


# =============================================================================
# cross_entity_state_dependency (queue A)
# =============================================================================

def test_hbo_schedule_requires_plan_covered(api):
    """PRD §3.8: "The plan's coverage_status must be COVERED, or the request is
    rejected with ERR_COVERAGE_NOT_ACTIVE."
    Scheduling on a plan whose coverage_status is still PENDING returns
    ERR_COVERAGE_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/hbo_schedule_requires_plan_covered
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M13", with_hyperbaric=True)
    chamber = fixtures.create_chamber(base["center_id"])
    ht_headers = make_hyperbaric_tech_headers(base["ht_id"])
    version = fixtures.get_plan_version(base["plan_id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(base["plan_id"], chamber["id"], version),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_ACTIVE.value)


def test_debridement_complete_requires_patient_in_care(api):
    """PRD §3.7: "Completing a debridement is permitted only when the procedure
    is in SCHEDULED (otherwise ERR_PROC_NOT_SCHEDULED), the governing plan is
    ACTIVE (otherwise ERR_PLAN_NOT_ACTIVE), and the patient is IN_CARE (otherwise
    ERR_PATIENT_NOT_IN_CARE)."
    After a transfer cascade auto-suspends the plan (patient TRANSFERRED),
    completing the scheduled debridement returns ERR_PLAN_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/debridement_complete_requires_patient_in_care
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M14")
    wc_id = base["wc_id"]
    proc = fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id)
    fixtures.initiate_transfer(base["patient_id"])
    resp = api.complete_debridement_procedure(proc["id"], make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)
    patient = validate_success(api.get_patient(base["patient_id"], fixtures.INTAKE))
    assert patient["status"] == "TRANSFERRED"


def test_hbo_schedule_on_denied_coverage_plan_rejected(api):
    """PRD §3.8: "The plan's coverage_status must be COVERED, or the request is
    rejected with ERR_COVERAGE_NOT_ACTIVE." PRD §3.5: "Denying moves the
    authorization to DENIED and cascades: the plan's coverage_status flips to
    NOT_COVERED".
    Scheduling on a plan whose coverage was denied (NOT_COVERED) returns
    ERR_COVERAGE_NOT_ACTIVE — a coverage_status other than COVERED blocks
    scheduling regardless of which non-COVERED value it holds.

    Design: Difficulty/cross_entity_state_dependency/hbo_schedule_requires_plan_covered
    """
    base = fixtures.setup_center_staff_patient(mrn="M13b", with_hyperbaric=True)
    baseline_id = fixtures.accept_patient_into_care(base["patient_id"], base["wc_id"])
    plan = fixtures.create_draft_plan(base["patient_id"], base["wc_id"], baseline_id,
                                      budget_cents=100000)
    auth = validate_success(api.create_prior_authorization(
        factories.create_prior_authorization_payload(plan["id"], requested_hbo_sessions=2),
        fixtures.PAYER), 201)
    validate_success(api.deny_prior_authorization(auth["id"], fixtures.PAYER))
    chamber = fixtures.create_chamber(base["center_id"])
    ht_headers = make_hyperbaric_tech_headers(base["ht_id"])
    version = fixtures.get_plan_version(plan["id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(plan["id"], chamber["id"], version),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_ACTIVE.value)


def test_debridement_complete_after_transfer_leaves_procedure_scheduled(api):
    """PRD §3.7: "Completing a debridement is permitted only when the procedure is
    in SCHEDULED (otherwise ERR_PROC_NOT_SCHEDULED), the governing plan is ACTIVE
    (otherwise ERR_PLAN_NOT_ACTIVE), and the patient is IN_CARE".
    A blocked completion (plan auto-suspended by the transfer) leaves the
    procedure in SCHEDULED — no partial transition occurs.

    Design: Difficulty/cross_entity_state_dependency/debridement_complete_requires_patient_in_care
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M14b")
    wc_id = base["wc_id"]
    proc = fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id)
    fixtures.initiate_transfer(base["patient_id"])
    resp = api.complete_debridement_procedure(proc["id"], make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)
    fetched = validate_success(api.get_debridement_procedure(
        proc["id"], make_wound_clinician_headers(wc_id)))
    assert fetched["status"] == "SCHEDULED"


# =============================================================================
# resource_temporal_overlap (queue A)
# =============================================================================

def test_chamber_overlap_halfopen_plus_buffer_rejected(api):
    """PRD §3.8: "A new session on a chamber is rejected when there exists any
    SCHEDULED session on that same chamber such that, with each interval extended
    on the right by the buffer, they intersect ... Because the mandatory turnover
    buffer pads the right edge, two dives that merely touch (the new start equal
    to the existing end) still collide unless the buffer is zero. A conflict is
    rejected with ERR_CHAMBER_SLOT_CONFLICT."
    A 10:00-11:00 session collides with an existing 09:00-10:00 session on a
    chamber with a 30-min buffer.

    Design: Difficulty/resource_temporal_overlap/chamber_overlap_halfopen_plus_buffer
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M15", turnover_buffer_minutes=30)
    ht_id = base["ht_id"]
    ht_headers = make_hyperbaric_tech_headers(ht_id)
    fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    version = fixtures.get_plan_version(base["plan_id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(
            base["plan_id"], base["chamber_id"], version,
            window_start="2026-05-02T10:00:00Z", window_end="2026-05-02T11:00:00Z"),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_CHAMBER_SLOT_CONFLICT.value)


def test_clinician_overlap_closed_no_buffer_touch_allowed(api):
    """PRD §3.7: "Two procedures that merely touch at an endpoint (the new start
    equal to the existing end) do not overlap and adjacent booking is permitted.
    A true overlap is rejected with ERR_CLINICIAN_SLOT_CONFLICT."
    A 10:00-11:00 procedure is accepted adjacent to an existing 09:00-10:00
    booking, while a subsequent 09:30-10:30 procedure that truly overlaps is
    rejected.

    Design: Difficulty/resource_temporal_overlap/clinician_overlap_closed_no_buffer_touch_allowed
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M16")
    wc_id = base["wc_id"]
    fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    adjacent = fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id,
                                             window_start="2026-05-02T10:00:00Z",
                                             window_end="2026-05-02T11:00:00Z")
    assert adjacent["status"] == "SCHEDULED", "touching endpoint must be allowed"
    resp = api.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            base["plan_id"], wc_id,
            window_start="2026-05-02T09:30:00Z", window_end="2026-05-02T10:30:00Z"),
        make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT.value)


def test_chamber_zero_buffer_touching_dives_allowed(api):
    """PRD §3.8: "Because the mandatory turnover buffer pads the right edge, two
    dives that merely touch (the new start equal to the existing end) still
    collide unless the buffer is zero."
    With a zero turnover buffer, a 10:00-11:00 session is accepted adjacent to an
    existing 09:00-10:00 session on the same chamber (half-open, no padding).

    Design: Difficulty/resource_temporal_overlap/chamber_overlap_halfopen_plus_buffer
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M15b", turnover_buffer_minutes=0)
    ht_id = base["ht_id"]
    ht_headers = make_hyperbaric_tech_headers(ht_id)
    fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    version = fixtures.get_plan_version(base["plan_id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(
            base["plan_id"], base["chamber_id"], version,
            window_start="2026-05-02T10:00:00Z", window_end="2026-05-02T11:00:00Z"),
        ht_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED", "touching dives with zero buffer must be allowed"


def test_clinician_overlapping_debridement_rejected(api):
    """PRD §3.7: "A new procedure for a given clinician is rejected when there
    exists another SCHEDULED procedure for the same clinician_id whose closed
    interval strictly overlaps — that is, the new start falls before the existing
    end and the existing start falls before the new end ... A true overlap is
    rejected with ERR_CLINICIAN_SLOT_CONFLICT."
    A 09:30-10:30 procedure strictly overlapping an existing 09:00-10:00 booking
    on the same clinician is rejected.

    Design: Difficulty/resource_temporal_overlap/clinician_overlap_closed_no_buffer_touch_allowed
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M16b")
    wc_id = base["wc_id"]
    fixtures.schedule_debridement(base["plan_id"], wc_id, wc_id,
                                  window_start="2026-05-02T09:00:00Z",
                                  window_end="2026-05-02T10:00:00Z")
    resp = api.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            base["plan_id"], wc_id,
            window_start="2026-05-02T09:30:00Z", window_end="2026-05-02T10:30:00Z"),
        make_wound_clinician_headers(wc_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT.value)


# =============================================================================
# Corner: validations section
# =============================================================================

def test_supply_budget_exceeded_returns_402(api):
    """PRD §3.6: "Before the order is accepted, the budget is checked: the new
    order's covered_cents added to the plan's existing provisional_covered_cents
    must not exceed the plan's debridement_supply_budget_cents; if it would, the
    order is rejected with ERR_SUPPLY_BUDGET_EXCEEDED."
    A single 153c order on a plan with a 100c budget returns
    ERR_SUPPLY_BUDGET_EXCEEDED (402); provisional_covered_cents stays 0.

    Design: Corner/validations/supply_budget_exceeded_returns_402
    """
    base = fixtures.setup_draft_plan(budget_cents=100, mrn="Mbud", accept_into_care=False)
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    version = fixtures.get_plan_version(base["plan_id"], wc_headers)
    resp = api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], version, line_items=factories.THREE_LINES_153),
        wc_headers)
    validate_error(resp, ApiErrorId.ERR_SUPPLY_BUDGET_EXCEEDED.value)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 0


def test_cross_center_chamber_reference_returns_error(api):
    """PRD §2.8: "when scheduling an HBO session, the referenced chamber's
    center_id must equal the center_id of the patient on the plan. Either
    mismatch is rejected with ERR_CROSS_CENTER_REFERENCE."
    Scheduling with a chamber from a different center returns
    ERR_CROSS_CENTER_REFERENCE (409).

    Design: Corner/validations/cross_center_chamber_reference_returns_error
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mcc")
    center_b = fixtures.create_center(name="B")
    chamber_b = fixtures.create_chamber(center_b["id"], label="CH-B")
    ht_headers = make_hyperbaric_tech_headers(base["ht_id"])
    version = fixtures.get_plan_version(base["plan_id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(base["plan_id"], chamber_b["id"], version),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_CENTER_REFERENCE.value)


def test_segregation_of_duties_transfer_blocked(api):
    """PRD §3.9: "If the initiating user's identifier matches the
    performed_by_user_id recorded on any completed debridement for the patient's
    plan, the initiation is rejected with ERR_SEGREGATION_OF_DUTIES."
    An AttendingPhysician whose X-User-ID equals the completing clinician's id
    cannot initiate the patient's transfer.

    Design: Corner/validations/segregation_of_duties_transfer_blocked
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Msod")
    u_id = base["wc_id"]  # the clinician id doubles as the attending X-User-ID
    proc = fixtures.schedule_debridement(base["plan_id"], u_id, u_id)
    validate_success(api.complete_debridement_procedure(
        proc["id"], make_wound_clinician_headers(u_id)))
    resp = api.create_acute_transfer(
        factories.create_acute_transfer_payload(base["patient_id"]),
        fixtures.make_attending_physician_headers(u_id))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_debridement_wrong_role_kind_returns_error(api):
    """PRD §3.7: "The referenced clinician's role_kind must be WOUND, or the
    request is rejected with ERR_CLINICIAN_ROLE_MISMATCH."
    Scheduling a debridement referencing a HYPERBARIC clinician (non-overlapping
    window) returns ERR_CLINICIAN_ROLE_MISMATCH (409).

    Design: Corner/validations/debridement_wrong_role_kind_returns_error
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Mrole", with_hyperbaric=True)
    resp = api.create_debridement_procedure(
        factories.create_debridement_procedure_payload(
            base["plan_id"], base["ht_id"],
            window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z"),
        make_wound_clinician_headers(base["wc_id"]))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_ROLE_MISMATCH.value)


# =============================================================================
# Corner: cross_cutting_complexity_layers — OCC + versioning
# =============================================================================

def test_occ_stale_plan_version_on_hbo_schedule(api):
    """PRD §2.7: "Scheduling a new HBO session requires the request to include
    expected_plan_version carrying the client's last observed version of the
    target TreatmentPlan. If that value does not match the plan's current
    version, the schedule is rejected with ERR_STALE_PLAN_VERSION (HTTP 412)."
    A first schedule bumps the version; a second schedule reusing the same
    observed version is rejected with ERR_STALE_PLAN_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_hbo_schedule
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mocc")
    ht_headers = make_hyperbaric_tech_headers(base["ht_id"])
    observed = fixtures.get_plan_version(base["plan_id"], ht_headers)
    validate_success(api.create_hbo_session(
        factories.create_hbo_session_payload(
            base["plan_id"], base["chamber_id"], observed,
            window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z"),
        ht_headers), 201)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(
            base["plan_id"], base["chamber_id"], observed,
            window_start="2026-05-02T13:00:00Z", window_end="2026-05-02T14:00:00Z"),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)


def test_version_increments_on_plan_mutation(api):
    """PRD §2.4: "an integer version that starts at its initial value and
    increments by one on each mutation." PRD §3.4: "Activation increments the
    plan's version by one."
    After create then activate, the plan's version is strictly greater than 1
    and its status is ACTIVE.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_plan_mutation
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Mver")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["version"] > 1, f"expected version > 1 after activate, got {plan['version']}"
    assert plan["status"] == "ACTIVE"
