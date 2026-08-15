"""CCTV inspection lifecycle: scheduling guards, coding, QA loop, auto-void, cycle close."""
from test_helpers import (
    ApiErrorId,
    add_defects,
    certify_inspection,
    create_district,
    create_open_cycle,
    create_segment,
    create_technician,
    drive_inspection_to_coding,
    get_segment,
    make_coder_headers,
    make_qa_reviewer_headers,
    reject_inspection,
    schedule_inspection,
    set_clock,
    setup_certified_segment,
    submit_for_qa,
    validate_error,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def _open_cycle_segment(district_name="D-X", cert_expires_at="2027-01-01T00:00:00Z"):
    """District + coder + QA + OPEN cycle + segment. Minimal shared preamble."""
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name=district_name, ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"], cert_expires_at=cert_expires_at)
    qa = create_technician(["QA_REVIEWER"], cert_expires_at=cert_expires_at)
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    return district, coder, qa, cycle, segment


def test_inspection_initial_state_scheduled(api):
    """PRD §3.3: "A fresh inspection sits in `SCHEDULED` with `reject_count` at 0
    and both `qa_reviewer_id` and `certified_at` null."

    Design: Corner/state_machines/inspection_initial_state_scheduled
    """
    _, coder, _, cycle, segment = _open_cycle_segment("D-S1")
    resp = api.create_cctv_inspection(
        segment["id"],
        {"cycle_id": cycle["id"], "scheduled_at": "2026-08-10T06:00:00Z",
         "coder_id": coder["id"], "purpose": "BASELINE"},
        ENGINEER,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["reject_count"] == 0
    assert data["qa_reviewer_id"] is None
    assert data["certified_at"] is None


def test_certified_inspection_terminal_lockdown(api):
    """PRD §2.10: "4. **State eligibility** — the target resource sits in a
    from-state that lists the requested transition, otherwise `ERR_INVALID_STATE`."
    CERTIFIED lists no outgoing reject transition (the QA reject route applies to
    `QA_REVIEW` only), so a reject on a CERTIFIED inspection is rejected.

    Design: Corner/state_machines/certified_inspection_terminal_lockdown
    """
    ctx = setup_certified_segment(
        defects=[{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}]
    )
    assert ctx["inspection"]["status"] == "CERTIFIED"
    resp = api.reject_inspection(
        ctx["inspection"]["id"], make_qa_reviewer_headers(ctx["qa"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_third_qa_reject_auto_voids_inspection(api):
    """PRD §3.3: "When an inspection already carrying a `reject_count` of 2 is
    rejected again, the reject call itself still succeeds — but instead of returning
    to `CODING`, the inspection is voided by an automatic system transition: its
    status becomes `VOIDED` and its `reject_count` is set to 3."

    Design: Corner/state_machines/third_qa_reject_auto_voids_inspection
    """
    _, coder, qa, cycle, segment = _open_cycle_segment("D-S3")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])
    reject_inspection(inspection["id"], qa["id"], "r1")
    submit_for_qa(inspection["id"], coder["id"])
    reject_inspection(inspection["id"], qa["id"], "r2")
    submit_for_qa(inspection["id"], coder["id"])

    resp = api.reject_inspection(inspection["id"], make_qa_reviewer_headers(qa["id"]), {"reason": "r3"})
    data = validate_success(resp, 200)
    assert data["status"] == "VOIDED", "third rejection routes through the system auto-void"
    assert data["reject_count"] == 3


def test_cycle_close_blocked_by_open_inspections(api):
    """PRD §3.2: "Closing a cycle, `OPEN` → `CLOSED`, is only possible once every
    inspection scheduled against that cycle has reached a terminal-or-stable state,
    meaning `CERTIFIED` or `VOIDED`; stragglers block the close with
    `ERR_INSPECTIONS_OPEN`."

    Design: Corner/state_machines/cycle_close_blocked_by_open_inspections
    """
    _, coder, _, cycle, segment = _open_cycle_segment("D-S4")
    schedule_inspection(segment["id"], cycle["id"], coder["id"])  # stays SCHEDULED
    resp = api.close_inspection_cycle(cycle["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INSPECTIONS_OPEN)


def test_qa_reject_loops_back_to_coding(api):
    """PRD §3.3: "The first and second rejections route the inspection
    `QA_REVIEW` → `CODING` and increment `reject_count`."

    Design: Difficulty/non_linear_state_machine/cctv_inspection_qa_reject_cycle_then_certify
    """
    _, coder, qa, cycle, segment = _open_cycle_segment("D-SM1")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 15, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])

    resp = api.reject_inspection(inspection["id"], make_qa_reviewer_headers(qa["id"]),
                                 {"reason": "recheck distance"})
    data = validate_success(resp, 200)
    assert data["status"] == "CODING", "first rejection loops the inspection back to CODING"
    assert data["reject_count"] == 1


def test_qa_reject_loop_then_certify_persists_reject_count(api):
    """PRD §3.3: "The first and second rejections route the inspection
    `QA_REVIEW` → `CODING` and increment `reject_count`."
    PRD §3.3: "the parent segment's condition scores are recomputed from this
    inspection's observations alone, across both families"

    Design: Difficulty/non_linear_state_machine/cctv_inspection_qa_reject_cycle_then_certify
    """
    _, coder, qa, cycle, segment = _open_cycle_segment("D-SM1B")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 15, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])
    reject_inspection(inspection["id"], qa["id"], "recheck distance")
    # Coder adds an O&M observation during the loop-back round, then resubmits.
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "RTL", "family": "OM", "grade": 1,
                  "distance_m": 80, "clock_position": 0}])
    submit_for_qa(inspection["id"], coder["id"])
    certified = certify_inspection(inspection["id"], qa["id"])

    assert certified["status"] == "CERTIFIED", "inspection reaches CERTIFIED after the loop"
    assert certified["reject_count"] == 1, "reject counter persists across the loop"
    segment_after = get_segment(segment["id"])
    assert segment_after["structural_grade"] == 2
    assert segment_after["om_grade"] == 1, "OM defect added during the loop is scored"


def test_error_no_defects_coded_on_submit_qa(api):
    """PRD §3.3: "When the footage is fully coded, the assigned coder submits the
    inspection for quality assurance, `CODING` → `QA_REVIEW`; an inspection with zero
    observations cannot be submitted and draws `ERR_NO_DEFECTS_CODED`."

    Design: Corner/errors/error_no_defects_coded_on_submit_qa
    """
    _, coder, _, cycle, segment = _open_cycle_segment("D-R3")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    resp = api.submit_qa(inspection["id"], make_coder_headers(coder["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_DEFECTS_CODED)


def test_cert_expired_boundary_at_expiry_instant(api):
    """PRD §3.1: "Certification validity is a hard gate on every coding and QA
    action: any attempt to code or QA-review at or after the `nassco_cert_expires_at`
    instant is rejected with `ERR_CERT_EXPIRED`."
    The coder's certification expires exactly at the current logical time, and
    "at or after" makes that instant already invalid.

    Design: Corner/validations/cert_expired_boundary_at_expiry_instant
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-V1", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"], cert_expires_at="2026-08-10T00:00:00Z")
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])

    resp = api.start_inspection(inspection["id"], make_coder_headers(coder["id"]))
    validate_error(resp, ApiErrorId.ERR_CERT_EXPIRED)


def test_sod_violation_certify_by_coding_technician(api):
    """PRD §3.3: "A `QaReviewer` certifies `QA_REVIEW` → `CERTIFIED`, and
    segregation of duties is absolute: the reviewing technician must differ from the
    inspection's `coder_id` (`ERR_SOD_VIOLATION`), must hold the `QA_REVIEWER`
    capability, and must hold a certification valid at the current logical time
    (`ERR_CERT_EXPIRED`)."

    Design: Corner/validations/sod_violation_certify_by_coding_technician
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-V2", ii_reduction_target_pct=20, budget_cents=1000000)
    tech = create_technician(["CODER", "QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], tech["id"])
    drive_inspection_to_coding(inspection["id"], tech["id"])
    add_defects(inspection["id"], tech["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}])
    submit_for_qa(inspection["id"], tech["id"])

    resp = api.certify_inspection(inspection["id"], make_qa_reviewer_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


def test_defect_distance_beyond_segment_length_rejected(api):
    """PRD §3.3: "A grade outside 1–5, a distance outside the segment's length, or
    a clock position outside 0–12 is rejected with `ERR_DEFECT_OUT_OF_RANGE`."
    The bound is inclusive, so a distance of exactly `length_m` is accepted while
    `length_m + 0.1` is rejected.

    Design: Corner/validations/defect_distance_beyond_segment_length_rejected
    """
    _, coder, _, cycle, segment = _open_cycle_segment("D-V3")  # 100 m segment
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])

    too_far = api.create_defect(
        inspection["id"],
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
         "distance_m": 100.1, "clock_position": 6},
        make_coder_headers(coder["id"]),
    )
    validate_error(too_far, ApiErrorId.ERR_DEFECT_OUT_OF_RANGE)

    at_boundary = api.create_defect(
        inspection["id"],
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
         "distance_m": 100, "clock_position": 6},
        make_coder_headers(coder["id"]),
    )
    validate_success(at_boundary, 201)


def test_inspection_scheduled_outside_cycle_window_rejected(api):
    """PRD §3.3: "The scheduled instant must fall inside the referenced cycle's
    window, or the request fails with `ERR_OUTSIDE_CYCLE_WINDOW`."

    Design: Corner/validations/inspection_scheduled_outside_cycle_window_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-V6", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    cycle = create_open_cycle(district["id"])  # window 2026-08-01 .. 2026-09-01
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    resp = api.create_cctv_inspection(
        segment["id"],
        {"cycle_id": cycle["id"], "scheduled_at": "2026-07-15T06:00:00Z",
         "coder_id": coder["id"], "purpose": "BASELINE"},
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_CYCLE_WINDOW)


def test_certify_on_coding_inspection_reports_state_before_sod(api):
    """PRD §2.10: "4. **State eligibility** — the target resource sits in a
    from-state that lists the requested transition, otherwise `ERR_INVALID_STATE`."
    PRD §2.10: "5. **Personnel certification and segregation** — NASSCO certification
    validity and segregation-of-duties on coding and QA actions: `ERR_CERT_EXPIRED`,
    `ERR_SOD_VIOLATION`, `ERR_NOT_ASSIGNED_CODER`."
    A certify call on an inspection still in CODING by the coder themself violates
    both rules; the fixed priority order makes the state check fire first.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_certify_on_coding_inspection_by_coder
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-PV1", ii_reduction_target_pct=25, budget_cents=100000000)
    tech = create_technician(["CODER", "QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-21->MH-22")
    inspection = schedule_inspection(segment["id"], cycle["id"], tech["id"])
    drive_inspection_to_coding(inspection["id"], tech["id"])
    add_defects(inspection["id"], tech["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}])

    resp = api.certify_inspection(inspection["id"], make_qa_reviewer_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_certify_by_coder_reports_sod_once_state_is_valid(api):
    """PRD §2.10: "4. **State eligibility** — the target resource sits in a
    from-state that lists the requested transition, otherwise `ERR_INVALID_STATE`."
    PRD §2.10: "5. **Personnel certification and segregation** — NASSCO certification
    validity and segregation-of-duties on coding and QA actions: `ERR_CERT_EXPIRED`,
    `ERR_SOD_VIOLATION`, `ERR_NOT_ASSIGNED_CODER`."
    The same actor on the same inspection, once it legitimately sits in QA_REVIEW,
    now clears priority 4 and is stopped by the priority-5 segregation rule —
    confirming which check was masking the other.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_certify_on_coding_inspection_by_coder
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-PV1B", ii_reduction_target_pct=25, budget_cents=100000000)
    tech = create_technician(["CODER", "QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-21->MH-22")
    inspection = schedule_inspection(segment["id"], cycle["id"], tech["id"])
    drive_inspection_to_coding(inspection["id"], tech["id"])
    add_defects(inspection["id"], tech["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}])
    submit_for_qa(inspection["id"], tech["id"])

    resp = api.certify_inspection(inspection["id"], make_qa_reviewer_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
