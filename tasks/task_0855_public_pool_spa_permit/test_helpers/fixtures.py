"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, because each test runs against a freshly started server with an empty store.
Setup calls use the lenient get_success_data() so a broken precondition surfaces as
a clear setup failure rather than a confusing assertion further down.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_closure_order_payload,
    create_complaint_payload,
    create_drain_certification_payload,
    create_facility_payload,
    create_inspection_payload,
    create_operator_payload,
    create_payment_payload,
    create_permit_payload,
    create_plan_review_payload,
    create_rwi_complaint_payload,
    create_signage_payload,
    create_spa_facility_payload,
    create_staff_assignment_payload,
    create_violation_payload,
    create_water_reading_payload,
)
from .test_users import (
    ADMIN,
    ANON,
    INSPECTOR,
    INSPECTOR_TWO,
    PLAN_REVIEWER,
    make_operator_headers,
)


# ==========================================================================
# Tier 0: primitives
# ==========================================================================


def set_clock(to_iso8601, headers=ADMIN):
    """Move the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def register_operator(**overrides):
    """Register an operator. Returns (operator, operator_headers)."""
    operator = get_success_data(
        api_client.create_operator(create_operator_payload(**overrides), ANON)
    )
    return operator, make_operator_headers(operator["id"])


def create_pool_facility(operator_id, op_headers, **overrides):
    """Register a CLASS_B_PUBLIC pool for the given operator."""
    return get_success_data(
        api_client.create_facility(
            create_facility_payload(operator_id, **overrides), op_headers
        )
    )


def create_spa_facility(operator_id, op_headers, **overrides):
    """Register a SPA venue for the given operator."""
    return get_success_data(
        api_client.create_facility(
            create_spa_facility_payload(operator_id, **overrides), op_headers
        )
    )


def read_facility(facility_id, headers=ADMIN):
    return get_success_data(api_client.get_facility(facility_id, headers))


def read_operator(operator_id, headers=ADMIN):
    return get_success_data(api_client.get_operator(operator_id, headers))


def read_permit(permit_id, headers=ADMIN):
    return get_success_data(api_client.get_permit(permit_id, headers))


def read_inspection(inspection_id, headers=ADMIN):
    return get_success_data(api_client.get_inspection(inspection_id, headers))


def read_plan_review(plan_review_id, headers=ADMIN):
    return get_success_data(api_client.get_plan_review(plan_review_id, headers))


def read_closure_order(closure_order_id, headers=ADMIN):
    return get_success_data(api_client.get_closure_order(closure_order_id, headers))


def read_complaint(complaint_id, headers=ADMIN):
    return get_success_data(api_client.get_complaint(complaint_id, headers))


def read_violation(inspection_id, violation_id, headers=ADMIN):
    """Violations are read back through their inspection's finding list."""
    rows = list_all_violations(inspection_id, headers)
    for row in rows:
        if row["id"] == violation_id:
            return row
    raise AssertionError(
        f"Setup failed: violation {violation_id} not present on inspection "
        f"{inspection_id}"
    )


def list_all_violations(inspection_id, headers=ADMIN, params=None):
    body = api_client.list_violations(inspection_id, headers, params=params)
    return get_success_data(body)


def list_all_closure_orders(headers=ADMIN, params=None):
    return get_success_data(api_client.list_closure_orders(headers, params=params))


def list_all_ledger_entries(headers=ADMIN, params=None):
    return get_success_data(
        api_client.list_fee_ledger_entries(headers, params=params)
    )


def fee_balance(operator_id, headers=ADMIN):
    return read_operator(operator_id, headers)["fee_balance_cents"]


def facility_version(facility_id, headers=ADMIN):
    return read_facility(facility_id, headers)["version"]


# ==========================================================================
# Tier 1: operator + venue scenarios
# ==========================================================================


def setup_operator_and_pool(operator_overrides=None, **facility_overrides):
    """One operator plus one CLASS_B_PUBLIC pool.

    Returns a dict with keys: operator, op_headers, operator_id, facility,
    facility_id.
    """
    operator, op_headers = register_operator(**(operator_overrides or {}))
    facility = create_pool_facility(operator["id"], op_headers, **facility_overrides)
    return {
        "operator": operator,
        "op_headers": op_headers,
        "operator_id": operator["id"],
        "facility": facility,
        "facility_id": facility["id"],
    }


def setup_operator_and_spa(operator_overrides=None, **facility_overrides):
    """One operator plus one SPA venue."""
    operator, op_headers = register_operator(**(operator_overrides or {}))
    facility = create_spa_facility(operator["id"], op_headers, **facility_overrides)
    return {
        "operator": operator,
        "op_headers": op_headers,
        "operator_id": operator["id"],
        "facility": facility,
        "facility_id": facility["id"],
    }


def setup_operator_with_two_pools(operator_overrides=None):
    """One operator owning two independent pools (no cross-facility clustering)."""
    operator, op_headers = register_operator(**(operator_overrides or {}))
    facility_a = create_pool_facility(operator["id"], op_headers, name="North Pool")
    facility_b = create_pool_facility(operator["id"], op_headers, name="South Pool")
    return {
        "operator": operator,
        "op_headers": op_headers,
        "operator_id": operator["id"],
        "facility_a": facility_a,
        "facility_a_id": facility_a["id"],
        "facility_b": facility_b,
        "facility_b_id": facility_b["id"],
    }


# ==========================================================================
# Tier 2: permit lifecycle shortcuts
# ==========================================================================


def apply_for_permit(facility_id, op_headers, **overrides):
    """File a permit application; the row lands in DRAFT."""
    return get_success_data(
        api_client.create_permit(
            create_permit_payload(facility_id, **overrides), op_headers
        )
    )


def advance_permit_to_under_review(permit_id, op_headers, admin_headers=ADMIN):
    """DRAFT -> SUBMITTED -> UNDER_REVIEW."""
    get_success_data(
        api_client.transition_permit(permit_id, {"action": "SUBMIT"}, op_headers)
    )
    return get_success_data(
        api_client.transition_permit(
            permit_id, {"action": "START_REVIEW"}, admin_headers
        )
    )


def issue_permit(permit_id, op_headers, admin_headers=ADMIN):
    """Walk a DRAFT permit all the way to ISSUED."""
    advance_permit_to_under_review(permit_id, op_headers, admin_headers)
    return get_success_data(
        api_client.transition_permit(permit_id, {"action": "ISSUE"}, admin_headers)
    )


def setup_facility_with_issued_permit(permit_overrides=None,
                                      operator_overrides=None,
                                      admin_headers=ADMIN,
                                      **facility_overrides):
    """Operator + pool + an ISSUED permit.

    The venue then reads RESTRICTED rather than CLOSED, which is the precondition
    for scheduling staff and for exercising the suspension cascade.
    """
    ctx = setup_operator_and_pool(operator_overrides, **facility_overrides)
    permit = apply_for_permit(
        ctx["facility_id"], ctx["op_headers"], **(permit_overrides or {})
    )
    permit = issue_permit(permit["id"], ctx["op_headers"], admin_headers)
    ctx["permit"] = permit
    ctx["permit_id"] = permit["id"]
    return ctx


def setup_facility_with_permit_under_review(permit_overrides=None,
                                            operator_overrides=None,
                                            admin_headers=ADMIN,
                                            **facility_overrides):
    """Operator + pool + a permit application parked in UNDER_REVIEW."""
    ctx = setup_operator_and_pool(operator_overrides, **facility_overrides)
    permit = apply_for_permit(
        ctx["facility_id"], ctx["op_headers"], **(permit_overrides or {})
    )
    permit = advance_permit_to_under_review(
        permit["id"], ctx["op_headers"], admin_headers
    )
    ctx["permit"] = permit
    ctx["permit_id"] = permit["id"]
    return ctx


def pay_operator_balance(operator_id, op_headers, amount_cents,
                         reference_note="Fee settlement"):
    """Record a payment against outstanding health-authority fees."""
    return get_success_data(
        api_client.create_payment(
            operator_id,
            create_payment_payload(amount_cents, reference_note=reference_note),
            op_headers,
        )
    )


# ==========================================================================
# Tier 3: plan-review pipeline shortcuts
# ==========================================================================


def submit_plan_review(facility_id, op_headers, **overrides):
    """File a plan review; the row lands in SUBMITTED at revision_round 0."""
    return get_success_data(
        api_client.create_plan_review(
            create_plan_review_payload(facility_id, **overrides), op_headers
        )
    )


def start_plan_review(plan_review_id, reviewer_headers=PLAN_REVIEWER):
    return get_success_data(
        api_client.transition_plan_review(
            plan_review_id, {"action": "START_REVIEW"}, reviewer_headers
        )
    )


def approve_plan_review(plan_review_id, reviewer_headers=PLAN_REVIEWER):
    """SUBMITTED -> UNDER_REVIEW -> APPROVED."""
    start_plan_review(plan_review_id, reviewer_headers)
    return get_success_data(
        api_client.transition_plan_review(
            plan_review_id, {"action": "APPROVE"}, reviewer_headers
        )
    )


def request_plan_review_corrections(plan_review_id, correction_notes,
                                    reviewer_headers=PLAN_REVIEWER):
    """UNDER_REVIEW -> CORRECTIONS_REQUIRED. Returns the updated review."""
    return get_success_data(
        api_client.transition_plan_review(
            plan_review_id,
            {"action": "REQUEST_CORRECTIONS", "correction_notes": correction_notes},
            reviewer_headers,
        )
    )


def drive_plan_review_to_corrections_required(plan_review_id, correction_notes,
                                              reviewer_headers=PLAN_REVIEWER):
    """SUBMITTED -> UNDER_REVIEW -> CORRECTIONS_REQUIRED."""
    start_plan_review(plan_review_id, reviewer_headers)
    return request_plan_review_corrections(
        plan_review_id, correction_notes, reviewer_headers
    )


def file_plan_revision(plan_review_id, expected_plan_review_version, op_headers,
                       drawing_reference=None):
    payload = {"expected_plan_review_version": expected_plan_review_version}
    if drawing_reference is not None:
        payload["drawing_reference"] = drawing_reference
    return get_success_data(
        api_client.create_plan_review_revision(plan_review_id, payload, op_headers)
    )


def setup_plan_review_chain(rounds, facility_id, op_headers,
                            reviewer_headers=PLAN_REVIEWER):
    """Walk a review through `rounds` correction/revision cycles.

    Returns the ordered list of review rows created, oldest first. The last row
    is left in SUBMITTED, carrying revision_round == rounds.
    """
    reviews = [submit_plan_review(facility_id, op_headers, drawing_reference="DR-A")]
    for index in range(rounds):
        current = reviews[-1]
        updated = drive_plan_review_to_corrections_required(
            current["id"], f"Round {index + 1} comments", reviewer_headers
        )
        successor = file_plan_revision(
            current["id"], updated["version"], op_headers,
            drawing_reference=f"DR-A-rev{index + 1}",
        )
        reviews.append(successor)
    return reviews


# ==========================================================================
# Tier 4: inspection lifecycle shortcuts
# ==========================================================================


def schedule_inspection(facility_id, inspector_headers=INSPECTOR, **overrides):
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(facility_id, **overrides), inspector_headers
        )
    )


def start_inspection(inspection_id, inspector_headers=INSPECTOR):
    return get_success_data(
        api_client.transition_inspection(
            inspection_id, {"action": "START"}, inspector_headers
        )
    )


def submit_inspection(inspection_id, inspector_headers=INSPECTOR):
    return get_success_data(
        api_client.transition_inspection(
            inspection_id, {"action": "SUBMIT"}, inspector_headers
        )
    )


def finalize_inspection(inspection_id, admin_headers=ADMIN):
    return get_success_data(
        api_client.transition_inspection(
            inspection_id, {"action": "FINALIZE"}, admin_headers
        )
    )


def void_inspection(inspection_id, admin_headers=ADMIN):
    return get_success_data(
        api_client.transition_inspection(
            inspection_id, {"action": "VOID"}, admin_headers
        )
    )


def add_violation(inspection_id, inspector_headers=INSPECTOR, **overrides):
    return get_success_data(
        api_client.create_violation(
            inspection_id, create_violation_payload(**overrides), inspector_headers
        )
    )


def setup_inspection_in_progress(facility_id, inspector_headers=INSPECTOR,
                                 **overrides):
    """Schedule a visit and start it, so findings may be appended."""
    inspection = schedule_inspection(facility_id, inspector_headers, **overrides)
    start_inspection(inspection["id"], inspector_headers)
    return inspection


def setup_finalized_inspection(facility_id, findings=(),
                               inspector_headers=INSPECTOR, admin_headers=ADMIN,
                               **inspection_overrides):
    """Schedule -> start -> record findings -> submit -> finalize.

    `findings` is a sequence of keyword dicts for create_violation_payload.
    Returns (inspection, violations) where the inspection is the FINALIZED row.
    """
    inspection = setup_inspection_in_progress(
        facility_id, inspector_headers, **inspection_overrides
    )
    violations = [
        add_violation(inspection["id"], inspector_headers, **finding)
        for finding in findings
    ]
    submit_inspection(inspection["id"], inspector_headers)
    finalized = finalize_inspection(inspection["id"], admin_headers)
    return finalized, violations


def issue_enforcement_notice(inspection_id, admin_headers=ADMIN, note=None):
    payload = {"action": "ISSUE_NOTICE"}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.enforce_inspection(inspection_id, payload, admin_headers)
    )


def escalate_enforcement(inspection_id, admin_headers=ADMIN):
    return get_success_data(
        api_client.enforce_inspection(
            inspection_id, {"action": "ESCALATE"}, admin_headers
        )
    )


def correct_violation(violation_id, op_headers, correction_note="Condition corrected"):
    return get_success_data(
        api_client.correct_violation(
            violation_id, {"correction_note": correction_note}, op_headers
        )
    )


def verify_violation(violation_id, outcome, inspector_headers=INSPECTOR):
    return get_success_data(
        api_client.verify_violation(
            violation_id, {"outcome": outcome}, inspector_headers
        )
    )


def clear_open_finding(violation_id, op_headers, inspector_headers=INSPECTOR):
    """Correct a finding and have it verified, so it leaves every open sum."""
    correct_violation(violation_id, op_headers)
    return verify_violation(violation_id, "VERIFIED", inspector_headers)


# ==========================================================================
# Tier 5: water chemistry, closure orders and the reopen protocol
# ==========================================================================


def log_water_reading(facility_id, headers, **overrides):
    return get_success_data(
        api_client.create_water_reading(
            facility_id, create_water_reading_payload(**overrides), headers
        )
    )


def log_in_range_reading(facility_id, headers, sampled_at, source="REOPEN_VERIFICATION",
                         **overrides):
    """A reading whose every parameter sits comfortably inside the pool limits."""
    return log_water_reading(
        facility_id, headers, sampled_at=sampled_at, source=source,
        free_chlorine_ppm=2.5, combined_chloramine_ppm=0.1, ph=7.4,
        water_temp_f=82.0, **overrides
    )


def open_closure_order(facility_id, headers, closure_reason, note=None,
                       expected_facility_version=None, version_reader=ADMIN):
    """Raise a manual closure order, reading the facility's current version first."""
    if expected_facility_version is None:
        expected_facility_version = facility_version(facility_id, version_reader)
    payload = create_closure_order_payload(
        facility_id, expected_facility_version, closure_reason=closure_reason
    )
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_closure_order(payload, headers))


def request_reopen(closure_order_id, verification_reading_id, op_headers,
                   treatment_free_chlorine_ppm=None, treatment_ph=None):
    payload = {"verification_reading_id": verification_reading_id}
    if treatment_free_chlorine_ppm is not None:
        payload["treatment_free_chlorine_ppm"] = treatment_free_chlorine_ppm
    if treatment_ph is not None:
        payload["treatment_ph"] = treatment_ph
    return get_success_data(
        api_client.request_reopen(closure_order_id, payload, op_headers)
    )


def decide_reopen(closure_order_id, decision, headers=INSPECTOR_TWO,
                  denial_reason=None):
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.decide_reopen(closure_order_id, payload, headers)
    )


def setup_closure_with_pending_reopen(closure_reason="CHEMICAL",
                                      clock_at_request="2026-05-01T02:00:00Z",
                                      reading_sampled_at="2026-05-01T01:30:00Z",
                                      reading_overrides=None,
                                      treatment_free_chlorine_ppm=None,
                                      treatment_ph=None,
                                      order_headers=INSPECTOR,
                                      **facility_overrides):
    """Operator + pool + an OPEN closure order carried into REOPEN_REQUESTED.

    The order is raised at the clock's 2026-05-01T00:00:00Z default, the clock is
    then advanced to `clock_at_request`, a verification reading is logged at
    `reading_sampled_at`, and the reopen request is filed. Returns the context dict
    with closure_order, closure_order_id, reading and reading_id added.
    """
    ctx = setup_operator_and_pool(**facility_overrides)
    order = open_closure_order(ctx["facility_id"], order_headers, closure_reason)
    if clock_at_request is not None:
        set_clock(clock_at_request)
    reading = log_water_reading(
        ctx["facility_id"],
        ctx["op_headers"],
        **{
            "sampled_at": reading_sampled_at,
            "source": "REOPEN_VERIFICATION",
            "free_chlorine_ppm": 2.5,
            "combined_chloramine_ppm": 0.1,
            "ph": 7.4,
            "water_temp_f": 82.0,
            **(reading_overrides or {}),
        },
    )
    order = request_reopen(
        order["id"], reading["id"], ctx["op_headers"],
        treatment_free_chlorine_ppm=treatment_free_chlorine_ppm,
        treatment_ph=treatment_ph,
    )
    ctx["closure_order"] = order
    ctx["closure_order_id"] = order["id"]
    ctx["reading"] = reading
    ctx["reading_id"] = reading["id"]
    return ctx


# ==========================================================================
# Tier 6: staffing, signage and drain certification
# ==========================================================================


def schedule_staff_shift(facility_id, op_headers, **overrides):
    return get_success_data(
        api_client.create_staff_assignment(
            create_staff_assignment_payload(facility_id, **overrides), op_headers
        )
    )


def cancel_staff_shift(assignment_id, op_headers):
    return get_success_data(
        api_client.cancel_staff_assignment(assignment_id, op_headers)
    )


def read_staff_assignment(facility_id, assignment_id, headers=ADMIN):
    """Staff assignments are read back through the venue's shift list."""
    rows = get_success_data(api_client.list_staff_assignments(facility_id, headers))
    for row in rows:
        if row["id"] == assignment_id:
            return row
    raise AssertionError(
        f"Setup failed: staff assignment {assignment_id} not present at facility "
        f"{facility_id}"
    )


def post_signage(facility_id, op_headers, signage_type, effective_on="2026-05-01"):
    return get_success_data(
        api_client.create_compliance_artifact(
            facility_id,
            create_signage_payload(signage_type, effective_on=effective_on),
            op_headers,
        )
    )


def post_drain_certification(facility_id, op_headers,
                             sva_system_type="MULTIPLE_MAIN_DRAINS",
                             effective_on="2026-05-01",
                             drain_cover_model="AquaSafe VGB-12"):
    return get_success_data(
        api_client.create_compliance_artifact(
            facility_id,
            create_drain_certification_payload(
                sva_system_type, effective_on=effective_on,
                drain_cover_model=drain_cover_model,
            ),
            op_headers,
        )
    )


def post_all_required_signage(facility_id, op_headers, signage_types,
                              effective_on="2026-05-01"):
    return [
        post_signage(facility_id, op_headers, signage_type, effective_on)
        for signage_type in signage_types
    ]


def read_artifacts(facility_id, headers=ADMIN, params=None):
    return get_success_data(
        api_client.list_compliance_artifacts(facility_id, headers, params=params)
    )


# ==========================================================================
# Tier 7: complaints and recreational-water-illness surveillance
# ==========================================================================


def file_complaint(facility_id, headers=ANON, **overrides):
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(facility_id, **overrides), headers
        )
    )


def file_rwi_complaint(facility_id, illness_case_count,
                       symptom_onset_date="2026-04-21", headers=ANON, **overrides):
    return get_success_data(
        api_client.create_complaint(
            create_rwi_complaint_payload(
                facility_id, illness_case_count,
                symptom_onset_date=symptom_onset_date, **overrides
            ),
            headers,
        )
    )


def transition_complaint(complaint_id, action, headers=INSPECTOR, **payload_extras):
    payload = {"action": action}
    payload.update(payload_extras)
    return get_success_data(
        api_client.transition_complaint(complaint_id, payload, headers)
    )


def setup_complaint_investigation(facility_id, complaint_id, op_headers=None,
                                  inspector_headers=INSPECTOR, admin_headers=ADMIN,
                                  scheduled_start_at="2026-05-02T09:00:00Z",
                                  scheduled_end_at="2026-05-02T10:00:00Z"):
    """Attach a COMPLAINT inspection, start the investigation and finalize the visit.

    Returns the finalized inspection so the caller can substantiate or
    unsubstantiate the complaint.
    """
    inspection = schedule_inspection(
        facility_id, inspector_headers, inspection_type="COMPLAINT",
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at,
    )
    transition_complaint(
        complaint_id, "TRIAGE", inspector_headers,
        linked_inspection_id=inspection["id"],
    )
    transition_complaint(complaint_id, "START_INVESTIGATION", inspector_headers)
    start_inspection(inspection["id"], inspector_headers)
    submit_inspection(inspection["id"], inspector_headers)
    return finalize_inspection(inspection["id"], admin_headers)
