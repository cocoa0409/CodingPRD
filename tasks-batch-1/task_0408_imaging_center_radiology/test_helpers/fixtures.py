"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): Technologist and Radiologist actions are
ownership-gated against exam.technologist_id / exam.radiologist_id, so every
such call here uses make_technologist_headers(tech_id) /
make_radiologist_headers(rad_id) with the real Staff id — never a shared
constant.

The deterministic center clock (PRD §2.6) is advanced explicitly via set_clock
so acquired_at_utc / signed_off_at_utc / raised_at_utc land on known instants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_center_payload, create_modality_payload, create_room_payload,
    create_staff_payload, create_order_payload, create_prior_auth_payload,
    prior_auth_decision_payload, create_screening_payload, create_exam_payload,
    create_series_payload, finalize_series_payload, claim_read_payload,
    create_report_payload, create_critical_result_payload, set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_nurse_headers, make_technologist_headers,
    make_radiologist_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Tier 0: Primitive provisioning ──────────────────────────────────

def create_center(name="Test Center", **overrides):
    """Create an imaging center. Returns the center dict."""
    res = api_client.create_center(create_center_payload(name=name, **overrides), ADMIN)
    return get_success_data(res)


def set_clock(center_id, iso):
    """Advance the center's deterministic clock to `iso`. Returns the center."""
    res = api_client.set_clock(set_clock_payload(center_id, iso), ADMIN)
    return get_success_data(res)


def create_modality(center_id, modality_type="XRAY", name="MOD", base_rvu=1.0, **overrides):
    res = api_client.create_modality(
        center_id, create_modality_payload(modality_type=modality_type, name=name,
                                            base_rvu=base_rvu, **overrides), ADMIN)
    return get_success_data(res)


def create_room(center_id, modality_id, name="ROOM", **overrides):
    res = api_client.create_room(
        center_id, create_room_payload(modality_id=modality_id, name=name, **overrides), ADMIN)
    return get_success_data(res)


def create_staff(center_id, staff_role, full_name="STAFF", credentialed_modalities=None, **overrides):
    res = api_client.create_staff(
        center_id, create_staff_payload(staff_role=staff_role, full_name=full_name,
                                        credentialed_modalities=credentialed_modalities,
                                        **overrides), ADMIN)
    return get_success_data(res)


def create_order(center_id, modality_id, **overrides):
    res = api_client.create_order(
        center_id, create_order_payload(modality_id=modality_id, **overrides), CLERK)
    return get_success_data(res)


# ─── Tier 1: Topology bundles ─────────────────────────────────────────

def setup_center_topology(modality_type="XRAY", base_rvu=1.0, requires_prior_auth=False,
                          clock="2026-06-01T08:00:00Z", cleanup_buffer_minutes=0,
                          with_radiologist=True, rad_creds=None, tech_creds=None,
                          center_overrides=None):
    """Center + clock + one modality + one room + technologist + nurse
    (+ radiologist). Returns a dict of all provisioned ids/objects.

    Each Staff is credentialed on the modality type unless overridden.
    """
    center = create_center(**(center_overrides or {}))
    if clock is not None:
        set_clock(center["id"], clock)
    modality = create_modality(center["id"], modality_type=modality_type,
                               name=modality_type, base_rvu=base_rvu,
                               requires_prior_auth=requires_prior_auth)
    room = create_room(center["id"], modality["id"], name="R-1",
                       cleanup_buffer_minutes=cleanup_buffer_minutes)
    tech = create_staff(center["id"], "TECHNOLOGIST", full_name="T",
                        credentialed_modalities=tech_creds or [modality_type])
    nurse = create_staff(center["id"], "NURSE", full_name="N",
                         credentialed_modalities=[modality_type])
    rad = None
    if with_radiologist:
        rad = create_staff(center["id"], "RADIOLOGIST", full_name="R",
                          credentialed_modalities=rad_creds or [modality_type])
    return {
        "center": center, "center_id": center["id"],
        "modality": modality, "modality_id": modality["id"],
        "room": room, "room_id": room["id"],
        "tech": tech, "tech_id": tech["id"],
        "nurse": nurse, "nurse_id": nurse["id"],
        "rad": rad, "rad_id": rad["id"] if rad else None,
    }


# ─── Tier 2: Order pipeline to a target state ─────────────────────────

def advance_order_to_benefit_checked(order_id, benefit_copay_cents=None):
    """REQUESTED -> BENEFIT_CHECKED (PRD §3.2). Returns the order."""
    payload = {}
    if benefit_copay_cents is not None:
        payload["benefit_copay_cents"] = benefit_copay_cents
    return get_success_data(api_client.benefit_check(order_id, payload, CLERK))


def clear_order_screening(order_id, nurse_id):
    """BENEFIT_CHECKED -> SCREEN_CLEARED (PRD §3.3). Returns the order."""
    return get_success_data(api_client.clear_screening(order_id, make_nurse_headers(nurse_id)))


def add_cleared_screening(order_id, nurse_id, egfr_value=90, **flags):
    """Create + evaluate a ContrastScreening (default inputs clear). Returns screening."""
    scr = get_success_data(api_client.create_screening(
        order_id, create_screening_payload(egfr_value=egfr_value, **flags),
        make_nurse_headers(nurse_id)))
    return get_success_data(api_client.evaluate_screening(scr["id"], make_nurse_headers(nurse_id)))


def setup_order_screen_cleared(topo, requires_contrast=False, priority=None,
                               benefit_copay_cents=None, do_screening=None):
    """Drive a fresh order on the topology's modality to SCREEN_CLEARED.

    do_screening defaults to topo's modality requiring contrast screening
    (MRI/CT). Returns (order_id, order_version_at_screen_cleared).
    """
    overrides = {"requires_contrast": requires_contrast}
    if priority is not None:
        overrides["priority"] = priority
    order = create_order(topo["center_id"], topo["modality_id"], **overrides)
    advance_order_to_benefit_checked(order["id"], benefit_copay_cents)
    if do_screening is None:
        do_screening = bool(topo["modality"]["requires_contrast_screening"])
    if do_screening:
        add_cleared_screening(order["id"], topo["nurse_id"])
    cleared = clear_order_screening(order["id"], topo["nurse_id"])
    return order["id"], cleared["version"]


def schedule_exam(topo, order_id, order_version, start, end, room_id=None, technologist_id=None):
    """SCREEN_CLEARED -> SCHEDULED; creates the exam (PRD §3.4). Returns the exam."""
    res = api_client.create_exam(
        order_id,
        create_exam_payload(
            room_id=room_id or topo["room_id"],
            technologist_id=technologist_id or topo["tech_id"],
            scheduled_start_utc=start,
            scheduled_end_utc=end,
            expected_imaging_order_version=order_version),
        CLERK)
    return get_success_data(res)


# ─── Tier 3: Exam pipeline to a target state ──────────────────────────

def acquire_exam(exam_id, tech_id, series_labels=("S1",), acquired_clock=None, center_id=None):
    """BOOKED -> CHECKED_IN -> ACQUIRING; capture+ACCEPT each series;
    advance clock; ACQUIRING -> ACQUIRED (PRD §3.5). Returns the exam dict.

    Requires the center clock to already be >= scheduled_start_utc for check-in.
    """
    th = make_technologist_headers(tech_id)
    get_success_data(api_client.check_in(exam_id, th))
    get_success_data(api_client.start_acquisition(exam_id, th))
    for label in series_labels:
        ser = get_success_data(api_client.create_series(exam_id, create_series_payload(series_label=label), th))
        get_success_data(api_client.finalize_series(ser["id"], finalize_series_payload("ACCEPTED"), th))
    if acquired_clock is not None and center_id is not None:
        set_clock(center_id, acquired_clock)
    return get_success_data(api_client.finish_acquisition(exam_id, th))


def claim_and_report(exam_id, exam_version, rad_id, findings_text="ok", has_critical_finding=False):
    """ACQUIRED -> READING (claim) then create + finalize report -> READ_COMPLETE
    (PRD §3.6). Returns (exam_after_claim_version, report_dict)."""
    rh = make_radiologist_headers(rad_id)
    claimed = get_success_data(api_client.claim_read(exam_id, claim_read_payload(exam_version), rh))
    report_payload = create_report_payload(findings_text=findings_text)
    if has_critical_finding:
        report_payload["has_critical_finding"] = True
    report = get_success_data(api_client.create_report(exam_id, report_payload, rh))
    report = get_success_data(api_client.finalize_report(report["id"], rh))
    return claimed["version"], report


def setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority=None, requires_contrast=False,
                     start="2026-06-01T09:00:00Z", end="2026-06-01T09:30:00Z",
                     acquired_clock="2026-06-01T09:00:00Z", signoff_clock="2026-06-01T09:40:00Z",
                     init_clock="2026-06-01T08:00:00Z", has_critical_finding=False,
                     center_overrides=None):
    """Full pipeline to a SIGNED_OFF exam + SIGNED_OFF order, report FINAL.

    Returns a dict with keys: topo, order_id, exam_id, exam_v_at_claim,
    report_id, report, exam (post-signoff), order (post-signoff).

    The reading radiologist is distinct from the technologist (segregation of
    duties holds). If has_critical_finding is set, a CriticalResult is raised
    before sign-off so the sign-off succeeds.
    """
    topo = setup_center_topology(modality_type=modality_type, base_rvu=base_rvu,
                                 requires_prior_auth=False, clock=init_clock,
                                 center_overrides=center_overrides)
    order_id, ov = setup_order_screen_cleared(topo, requires_contrast=requires_contrast,
                                              priority=priority)
    exam = schedule_exam(topo, order_id, ov, start, end)
    # advance clock to >= start for check-in if needed
    if init_clock < start:
        set_clock(topo["center_id"], start)
    exam = acquire_exam(exam["id"], topo["tech_id"], series_labels=("S1",),
                        acquired_clock=acquired_clock, center_id=topo["center_id"])
    exam_v, report = claim_and_report(exam["id"], exam["version"], topo["rad_id"],
                                      has_critical_finding=has_critical_finding)
    rh = make_radiologist_headers(topo["rad_id"])
    if has_critical_finding:
        get_success_data(api_client.create_critical_result(
            report["id"], create_critical_result_payload(), rh))
    set_clock(topo["center_id"], signoff_clock)
    signed_exam = get_success_data(api_client.sign_off(exam["id"], rh))
    signed_order = get_success_data(api_client.get_order(order_id, CLERK))
    return {
        "topo": topo,
        "order_id": order_id,
        "exam_id": exam["id"],
        "exam_v_at_claim": exam_v,
        "report_id": report["id"],
        "report": report,
        "exam": signed_exam,
        "order": signed_order,
    }


def setup_read_complete(modality_type="XRAY", base_rvu=1.0, priority=None, requires_contrast=False,
                        start="2026-06-01T09:00:00Z", end="2026-06-01T09:30:00Z",
                        acquired_clock="2026-06-01T09:00:00Z",
                        init_clock="2026-06-01T08:00:00Z", has_critical_finding=False):
    """Pipeline to an exam at READ_COMPLETE (report FINAL), NOT signed off.

    Returns dict: topo, order_id, exam_id, report_id, report.
    """
    topo = setup_center_topology(modality_type=modality_type, base_rvu=base_rvu,
                                 requires_prior_auth=False, clock=init_clock)
    order_id, ov = setup_order_screen_cleared(topo, requires_contrast=requires_contrast,
                                              priority=priority)
    exam = schedule_exam(topo, order_id, ov, start, end)
    if init_clock < start:
        set_clock(topo["center_id"], start)
    exam = acquire_exam(exam["id"], topo["tech_id"], series_labels=("S1",),
                        acquired_clock=acquired_clock, center_id=topo["center_id"])
    exam_v, report = claim_and_report(exam["id"], exam["version"], topo["rad_id"],
                                      has_critical_finding=has_critical_finding)
    return {
        "topo": topo,
        "order_id": order_id,
        "exam_id": exam["id"],
        "report_id": report["id"],
        "report": report,
    }


def setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=200.0,
                         clock="2026-06-01T09:00:00Z",
                         start="2026-06-01T09:00:00Z", end="2026-06-01T09:30:00Z"):
    """Pipeline to an exam at ACQUIRING (checked in, acquisition started), no
    series finalized yet. A high default threshold avoids accidental
    QUALITY_HOLD side effects during series finalize.

    Returns dict: topo, order_id, exam_id, exam_version.
    """
    topo = setup_center_topology(modality_type=modality_type, requires_prior_auth=False,
                                 clock=clock,
                                 center_overrides={"repeat_rate_threshold_pct": repeat_rate_threshold_pct})
    order_id, ov = setup_order_screen_cleared(topo, requires_contrast=False)
    exam = schedule_exam(topo, order_id, ov, start, end)
    th = make_technologist_headers(topo["tech_id"])
    get_success_data(api_client.check_in(exam["id"], th))
    started = get_success_data(api_client.start_acquisition(exam["id"], th))
    return {
        "topo": topo,
        "order_id": order_id,
        "exam_id": exam["id"],
        "exam_version": started["version"],
    }


def finalize_n_series(exam_id, tech_id, n_accepted, n_repeated=0, n_rejected=0,
                      reject_reason="MOTION"):
    """On an ACQUIRING exam, capture and finalize series:
    n_accepted ACCEPTED, then n_repeated REPEATED, then n_rejected REJECTED.

    Returns the list of finalized series dicts (in finalize order).
    """
    th = make_technologist_headers(tech_id)
    out = []
    for i in range(n_accepted):
        ser = get_success_data(api_client.create_series(exam_id, create_series_payload(series_label=f"A{i}"), th))
        out.append(get_success_data(api_client.finalize_series(ser["id"], finalize_series_payload("ACCEPTED"), th)))
    for i in range(n_repeated):
        ser = get_success_data(api_client.create_series(exam_id, create_series_payload(series_label=f"REP{i}"), th))
        out.append(get_success_data(api_client.finalize_series(
            ser["id"], finalize_series_payload("REPEATED", reject_reason=reject_reason), th)))
    for i in range(n_rejected):
        ser = get_success_data(api_client.create_series(exam_id, create_series_payload(series_label=f"REJ{i}"), th))
        out.append(get_success_data(api_client.finalize_series(
            ser["id"], finalize_series_payload("REJECTED", reject_reason=reject_reason), th)))
    return out


# ─── Tier 4: Critical-result / SLA targeting ──────────────────────────

def setup_critical_result(modality_type="XRAY", critical_ack_sla_minutes=60,
                          init_clock="2026-06-01T08:00:00Z",
                          start="2026-06-01T08:30:00Z", end="2026-06-01T09:00:00Z",
                          checkin_clock="2026-06-01T08:30:00Z",
                          raised_clock="2026-06-01T09:00:00Z",
                          notified_party_role="ORDERING_PROVIDER"):
    """Pipeline to a CriticalResult raised at `raised_clock` on a report whose
    exam is READING (report DRAFT->FINAL not required to raise). The report
    carries has_critical_finding true. Returns dict:
    topo, order_id, exam_id, report_id, cr_id, cr (raised).
    """
    topo = setup_center_topology(modality_type=modality_type, requires_prior_auth=False,
                                 clock=init_clock,
                                 center_overrides={"critical_ack_sla_minutes": critical_ack_sla_minutes})
    order_id, ov = setup_order_screen_cleared(topo, requires_contrast=False)
    exam = schedule_exam(topo, order_id, ov, start, end)
    set_clock(topo["center_id"], checkin_clock)
    exam = acquire_exam(exam["id"], topo["tech_id"], series_labels=("S1",),
                        acquired_clock=None, center_id=topo["center_id"])
    rh = make_radiologist_headers(topo["rad_id"])
    get_success_data(api_client.claim_read(exam["id"], claim_read_payload(exam["version"]), rh))
    report = get_success_data(api_client.create_report(
        exam["id"], create_report_payload(findings_text="crit", has_critical_finding=True), rh))
    set_clock(topo["center_id"], raised_clock)
    cr = get_success_data(api_client.create_critical_result(
        report["id"], create_critical_result_payload(notified_party_role=notified_party_role), rh))
    return {
        "topo": topo,
        "order_id": order_id,
        "exam_id": exam["id"],
        "report_id": report["id"],
        "cr_id": cr["id"],
        "cr": cr,
    }
