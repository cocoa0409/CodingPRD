"""Cross-entity state dependencies, resource temporal overlap, and compensating
invariants.

Difficulty queue: cross_entity_state_dependency, resource_temporal_overlap,
compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_finance_coordinator_headers,
    make_clinician_dvm_headers,
    make_owner_headers,
    register_and_triage,
    create_and_issue_estimate,
    setup_visit_with_active_auth,
    setup_visit_in_treatment,
    setup_visit_with_active_hospitalization,
    schedule_procedure,
    admit_hospitalization,
    get_invoice,
    get_visit_state,
    api_client,
)


# ---- cross_entity_state_dependency ----

def test_begin_treatment_without_active_auth_rejected(api):
    """PRD §3.6: "A `ClinicianDVM` begins treatment on a Visit that is in
    `TRIAGED` status (`ERR_INVALID_STATE`) and that has at least one `ACTIVE`
    Authorization; a Visit with no active authorization is rejected with
    `ERR_NO_ACTIVE_AUTH`."

    Design: Difficulty/cross_entity_state_dependency/cesd_begin_treatment_requires_active_auth
    """
    finance = make_finance_coordinator_headers()
    dvm = make_clinician_dvm_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-12",
                                   chief_complaint="cough")
    est = create_and_issue_estimate(visit["id"], unit_price_cents=50000)
    # PENDING authorization only (never approved) -> no ACTIVE auth exists.
    validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 100000}, finance),
        expected_status=201)
    resp = api.begin_treatment(visit["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AUTH, expected_status=409)


def test_begin_treatment_pending_auth_only_blocks(api):
    """PRD §3.6: "Clinical treatment begins only after money is authorized."
    PRD §3.6: "a Visit with no active authorization is rejected with
    `ERR_NO_ACTIVE_AUTH`."

    Design: Difficulty/cross_entity_state_dependency/cesd_begin_treatment_requires_active_auth
    """
    finance = make_finance_coordinator_headers()
    dvm = make_clinician_dvm_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-12b")
    est = create_and_issue_estimate(visit["id"], unit_price_cents=50000)
    validate_success(api.create_authorization(visit["id"], {
        "estimate_id": est["id"], "approved_ceiling_cents": 100000}, finance),
        expected_status=201)
    resp = api.begin_treatment(visit["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AUTH, expected_status=409)


def test_ready_for_discharge_blocked_by_active_hospitalization(api):
    """PRD §3.6: "This requires the Visit to be `IN_TREATMENT`
    (`ERR_INVALID_STATE`) and that all in-flight work has settled: there must be
    no `ACTIVE` Hospitalization on the Visit, otherwise `ERR_PATIENT_STILL_BOARDED`"

    Design: Difficulty/cross_entity_state_dependency/cesd_ready_for_discharge_requires_no_active_hosp
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-02T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-13")
    resp = api.ready_for_discharge(visit["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_PATIENT_STILL_BOARDED, expected_status=409)


def test_ready_for_discharge_active_board_returns_still_boarded(api):
    """PRD §3.6: "there must be no `ACTIVE` Hospitalization on the Visit,
    otherwise `ERR_PATIENT_STILL_BOARDED`"

    Design: Difficulty/cross_entity_state_dependency/cesd_ready_for_discharge_requires_no_active_hosp
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="WARD", cage_number=2,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-02T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-13b")
    resp = api.ready_for_discharge(visit["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_PATIENT_STILL_BOARDED, expected_status=409)


# ---- resource_temporal_overlap ----

def test_surgery_suite_halfopen_overlap_rejected(api):
    """PRD §3.8: "a new booking may not overlap any existing `SCHEDULED` or
    `PERFORMED` booking on the same `resource_room`, where overlap is judged on
    the half-open interval from `start_at` up to but not including `end_at` — two
    bookings that merely touch at an endpoint do not conflict, but any true
    overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/rto_surgery_suite_halfopen_overlap
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=300000, owner_user_id="owner-14",
        chief_complaint="fracture")
    schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                       start_at="2026-05-01T10:30:00Z",
                       end_at="2026-05-01T11:30:00Z", price_cents=80000)
    # [10:00,11:00) truly overlaps [10:30,11:30) on OR_1.
    resp = api.create_procedure(visit["id"], {
        "modality": "SURGERY", "resource_room": "OR_1",
        "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T11:00:00Z",
        "price_cents": 80000}, dvm)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_DOUBLE_BOOKED, expected_status=409)


def test_surgery_suite_adjacent_booking_allowed(api):
    """PRD §3.8: "overlap is judged on the half-open interval from `start_at` up
    to but not including `end_at` — two bookings that merely touch at an endpoint
    do not conflict"

    Design: Difficulty/resource_temporal_overlap/rto_surgery_suite_halfopen_overlap
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=300000, owner_user_id="owner-14b")
    schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                       start_at="2026-05-01T10:30:00Z",
                       end_at="2026-05-01T11:30:00Z", price_cents=80000)
    # Booking starting exactly at the prior end (11:30) touches but does not overlap.
    resp = api.create_procedure(visit["id"], {
        "modality": "SURGERY", "resource_room": "OR_1",
        "start_at": "2026-05-01T11:30:00Z", "end_at": "2026-05-01T12:30:00Z",
        "price_cents": 80000}, dvm)
    validate_success(resp, expected_status=201)


def test_icu_cage_point_occupancy_conflict(api):
    """PRD §3.7: "A cage is occupied by point-occupancy: a new hospitalization
    may not reuse a `cage_number` that an `ACTIVE` hospitalization of the same
    ward already holds, and a collision is rejected with `ERR_CAGE_OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/rto_icu_cage_point_occupancy
    """
    dvm = make_clinician_dvm_headers()
    # Visit A holds ICU cage 1 (ACTIVE).
    _, vA, _, _, _ = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-03T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-15")
    # Visit B tries ICU cage 1 at a disjoint time -> still occupied (point-occupancy).
    _, vB, _, _ = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=300000, owner_user_id="owner-16",
        chief_complaint="sepsis")
    resp = api.create_hospitalization(vB["id"], {
        "ward": "ICU", "cage_number": 1, "admit_at": "2026-05-04T08:00:00Z",
        "planned_discharge_at": "2026-05-05T08:00:00Z"}, dvm)
    validate_error(resp, ApiErrorId.ERR_CAGE_OCCUPIED, expected_status=409)


def test_icu_cage_occupancy_ignores_admit_times(api):
    """PRD §3.7: "a new hospitalization may not reuse a `cage_number` that an
    `ACTIVE` hospitalization of the same ward already holds, and a collision is
    rejected with `ERR_CAGE_OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/rto_icu_cage_point_occupancy
    """
    dvm = make_clinician_dvm_headers()
    _, vA, _, _, _ = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-03T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-15b")
    _, vB, _, _ = setup_visit_in_treatment(
        triage_level="YELLOW", approved_ceiling_cents=300000,
        owner_user_id="owner-16b")
    resp = api.create_hospitalization(vB["id"], {
        "ward": "ICU", "cage_number": 1, "admit_at": "2026-05-10T08:00:00Z",
        "planned_discharge_at": "2026-05-11T08:00:00Z"}, dvm)
    validate_error(resp, ApiErrorId.ERR_CAGE_OCCUPIED, expected_status=409)


# ---- compensating_invariant ----

def test_void_authorization_restores_ceiling(api):
    """PRD §3.5: "On a successful void, the authorization moves from `ACTIVE` to
    `VOIDED`, the Visit's `authorized_ceiling_cents` is recomputed excluding this
    authorization"
    PRD §2.8: "The authorized ceiling is defined as the sum of
    `approved_ceiling_cents` over every Authorization on the Visit whose status
    is `ACTIVE`; authorizations in any other status contribute nothing."

    Design: Difficulty/compensating_invariant/ci_authorization_void_ceiling_conserved
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=200000, owner_user_id="owner-17")
    # No procedures performed -> committed 0.
    resp = api.void_authorization(visit["id"], auth["id"], finance)
    voided = validate_success(resp)
    assert voided["status"] == "VOIDED"
    v = get_visit_state(visit["id"])
    assert v["authorized_ceiling_cents"] == 0, (
        f"ceiling must return to 0 after void, got {v['authorized_ceiling_cents']}")


def test_void_authorization_status_voided_and_ceiling_zero(api):
    """PRD §3.5: "On a successful void, the authorization moves from `ACTIVE` to
    `VOIDED`, the Visit's `authorized_ceiling_cents` is recomputed excluding this
    authorization"

    Design: Difficulty/compensating_invariant/ci_authorization_void_ceiling_conserved
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=100000,
        approved_ceiling_cents=200000, owner_user_id="owner-17b")
    validate_success(api.void_authorization(visit["id"], auth["id"], finance))
    assert get_visit_state(visit["id"])["authorized_ceiling_cents"] == 0


def test_void_authorization_restores_deposit_and_balance(api):
    """PRD §3.5: "this authorization's deposit is removed from the invoice's
    `deposit_applied_cents`, and the invoice balance is recomputed"
    PRD §3.9: "The `deposit_applied_cents` is the sum of `deposit_paid_cents` over
    the Visit's `ACTIVE` authorizations."
    PRD §3.9: "The `balance_due_cents` is the subtotal plus the tax minus the
    applied deposit, floored at zero so it never goes negative."

    Design: Difficulty/compensating_invariant/ci_authorization_void_deposit_conserved
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=300000,
        approved_ceiling_cents=386100, owner_user_id="owner-18")
    resp = api.void_authorization(visit["id"], auth["id"], finance)
    assert validate_success(resp)["status"] == "VOIDED"
    invoice = get_invoice(visit["id"])
    assert invoice["deposit_applied_cents"] == 0, (
        f"deposit must return to 0 after void, got {invoice['deposit_applied_cents']}")
    assert invoice["balance_due_cents"] == 0, (
        f"balance floored at 0 with no charges, got {invoice['balance_due_cents']}")


def test_void_authorization_removes_deposit_credit(api):
    """PRD §3.5: "this authorization's deposit is removed from the invoice's
    `deposit_applied_cents`, and the invoice balance is recomputed"

    Design: Difficulty/compensating_invariant/ci_authorization_void_deposit_conserved
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=300000,
        approved_ceiling_cents=386100, owner_user_id="owner-18b")
    # Deposit was credited on approve; confirm, then void and confirm removal.
    before = get_invoice(visit["id"])
    assert before["deposit_applied_cents"] == 193050
    validate_success(api.void_authorization(visit["id"], auth["id"], finance))
    after = get_invoice(visit["id"])
    assert after["deposit_applied_cents"] == 0
