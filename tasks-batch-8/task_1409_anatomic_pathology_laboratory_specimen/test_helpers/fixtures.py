"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and validates setup calls with the lenient
get_success_data so failures surface as clear "Setup failed" errors.
"""
from datetime import timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .assertions import parse_instant
from .constants import (
    DEFAULT_COLLECTION,
    DEFAULT_CONSULT_DUE,
    DEFAULT_DOB,
    DEFAULT_LOAN_DUE_BACK,
    DEFAULT_LOAN_OUT,
    DEFAULT_RECEIVED,
)
from .factories import next_mrn
from .test_users import (
    TEST_USERS,
    make_pathologist_headers,
)

ADMIN_HEADERS = TEST_USERS["lab_admin_headers"]
HISTOTECH_HEADERS = TEST_USERS["histotech_headers"]
PA_HEADERS = TEST_USERS["pathology_assistant_headers"]


def _setup_ok(response, what: str):
    data = get_success_data(response)
    assert isinstance(data, dict), (
        f"Setup failed for {what}: {response.status_code} {response.text}"
    )
    return data


def iso_after(iso_ts: str, **delta_kwargs) -> str:
    """Return an ISO 8601 Z timestamp `delta` after (or before) the given one."""
    dt = parse_instant(iso_ts) + timedelta(**delta_kwargs)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Patients / pathologists / coverage windows
# ---------------------------------------------------------------------------

def create_patient(mrn=None, full_name="Test Patient", date_of_birth=DEFAULT_DOB):
    payload = {
        "mrn": mrn or next_mrn(),
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    }
    return _setup_ok(api_client.create_patient(payload, ADMIN_HEADERS), "patient")


def create_pathologist(full_name="Dr Test", subspecialties=("GI",), active=None):
    payload = {"full_name": full_name, "subspecialties": list(subspecialties)}
    if active is not None:
        payload["active"] = active
    return _setup_ok(api_client.create_pathologist(payload, ADMIN_HEADERS), "pathologist")


def get_pathologist(pathologist_id):
    return _setup_ok(api_client.get_pathologist(pathologist_id, ADMIN_HEADERS), "get pathologist")


def create_coverage_window(pathologist_id, window_type, start_at, end_at):
    payload = {"window_type": window_type, "start_at": start_at, "end_at": end_at}
    return _setup_ok(
        api_client.create_coverage_window(pathologist_id, payload, ADMIN_HEADERS),
        "coverage window",
    )


def cancel_coverage_window(window_id):
    return _setup_ok(api_client.cancel_coverage_window(window_id, ADMIN_HEADERS), "cancel window")


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def create_case(patient_id, subspecialty="GI", tat_mode=None):
    payload = {"patient_id": patient_id, "subspecialty": subspecialty}
    if tat_mode is not None:
        payload["tat_mode"] = tat_mode
    return _setup_ok(api_client.create_case(payload, ADMIN_HEADERS), "case")


def get_case(case_id):
    return _setup_ok(api_client.get_case(case_id, ADMIN_HEADERS), "get case")


def assign_case(case_id, pathologist_id=None):
    payload = {}
    if pathologist_id is not None:
        payload["pathologist_id"] = pathologist_id
    return _setup_ok(api_client.assign_case(case_id, payload, ADMIN_HEADERS), "assign case")


def reassign_case(case_id, pathologist_id, expected_case_version):
    payload = {
        "pathologist_id": pathologist_id,
        "expected_case_version": expected_case_version,
    }
    return _setup_ok(api_client.reassign_case(case_id, payload, ADMIN_HEADERS), "reassign case")


def submit_for_signout(case_id, pathologist_id):
    return _setup_ok(
        api_client.submit_for_signout(case_id, make_pathologist_headers(pathologist_id)),
        "submit for signout",
    )


def sign_out_case(case_id, pathologist_id, diagnosis_text="Benign"):
    return _setup_ok(
        api_client.sign_out_case(
            case_id, {"diagnosis_text": diagnosis_text}, make_pathologist_headers(pathologist_id)
        ),
        "sign out",
    )


def amend_case(case_id, pathologist_id, diagnosis_text="Amended diagnosis", amendment_reason="clarification"):
    return _setup_ok(
        api_client.amend_case(
            case_id,
            {"diagnosis_text": diagnosis_text, "amendment_reason": amendment_reason},
            make_pathologist_headers(pathologist_id),
        ),
        "amend case",
    )


def amend_sign(case_id, pathologist_id):
    return _setup_ok(
        api_client.amend_sign(case_id, make_pathologist_headers(pathologist_id)),
        "amend sign",
    )


def amend_cancel(case_id, pathologist_id):
    return _setup_ok(
        api_client.amend_cancel(case_id, make_pathologist_headers(pathologist_id)),
        "amend cancel",
    )


def cancel_case(case_id, reason="order withdrawn"):
    return _setup_ok(
        api_client.cancel_case(case_id, {"reason": reason}, ADMIN_HEADERS),
        "cancel case",
    )


# ---------------------------------------------------------------------------
# Specimens / blocks / slides
# ---------------------------------------------------------------------------

def accession_specimen(
    case_id,
    patient_mrn,
    patient_dob=DEFAULT_DOB,
    specimen_type="BIOPSY",
    anatomical_site="Colon",
    collection_datetime=DEFAULT_COLLECTION,
    received_datetime=DEFAULT_RECEIVED,
    container_count=1,
    fixative_type=None,
):
    payload = {
        "patient_mrn": patient_mrn,
        "patient_dob": patient_dob,
        "specimen_type": specimen_type,
        "anatomical_site": anatomical_site,
        "collection_datetime": collection_datetime,
        "received_datetime": received_datetime,
        "container_count": container_count,
    }
    if fixative_type is not None:
        payload["fixative_type"] = fixative_type
    return _setup_ok(
        api_client.accession_specimen(case_id, payload, HISTOTECH_HEADERS),
        "specimen accession",
    )


def get_specimen(specimen_id):
    return _setup_ok(api_client.get_specimen(specimen_id, ADMIN_HEADERS), "get specimen")


def gross_specimen(specimen_id, gross_description="biopsy fragments"):
    return _setup_ok(
        api_client.gross_specimen(specimen_id, {"gross_description": gross_description}, PA_HEADERS),
        "gross specimen",
    )


def reject_specimen(specimen_id, reason="no tissue in container"):
    return _setup_ok(
        api_client.reject_specimen(specimen_id, {"reason": reason}, HISTOTECH_HEADERS),
        "reject specimen",
    )


def create_block(specimen_id, block_label="A1"):
    return _setup_ok(
        api_client.create_block(specimen_id, {"block_label": block_label}, HISTOTECH_HEADERS),
        "create block",
    )


def get_block(block_id):
    return _setup_ok(api_client.get_block(block_id, ADMIN_HEADERS), "get block")


def embed_block(block_id):
    return _setup_ok(api_client.embed_block(block_id, HISTOTECH_HEADERS), "embed block")


def create_slide(block_id, slide_label="A1-1"):
    return _setup_ok(
        api_client.create_slide(block_id, {"slide_label": slide_label}, HISTOTECH_HEADERS),
        "create slide",
    )


def get_slide(slide_id):
    return _setup_ok(api_client.get_slide(slide_id, ADMIN_HEADERS), "get slide")


def section_slide(slide_id, consumption_pct=10.0):
    return _setup_ok(
        api_client.section_slide(slide_id, {"consumption_pct": consumption_pct}, HISTOTECH_HEADERS),
        "section slide",
    )


def stain_complete_slide(slide_id):
    return _setup_ok(api_client.stain_complete_slide(slide_id, HISTOTECH_HEADERS), "stain complete")


def qc_review_slide(slide_id, result="PASS", reason=None):
    payload = {"result": result}
    if reason is not None:
        payload["reason"] = reason
    return _setup_ok(api_client.qc_review_slide(slide_id, payload, HISTOTECH_HEADERS), "qc review")


def recut_slide(slide_id, consumption_pct=5.0):
    return _setup_ok(
        api_client.recut_slide(slide_id, {"consumption_pct": consumption_pct}, HISTOTECH_HEADERS),
        "recut slide",
    )


# ---------------------------------------------------------------------------
# Stain orders / reflex rules
# ---------------------------------------------------------------------------

def create_stain_order(case_id, block_id, stain_type, pathologist_id):
    payload = {"block_id": block_id, "stain_type": stain_type}
    return _setup_ok(
        api_client.create_stain_order(case_id, payload, make_pathologist_headers(pathologist_id)),
        "stain order",
    )


def get_stain_order(order_id):
    return _setup_ok(api_client.get_stain_order(order_id, ADMIN_HEADERS), "get stain order")


def start_stain_order(order_id):
    return _setup_ok(api_client.start_stain_order(order_id, HISTOTECH_HEADERS), "start stain order")


def result_stain_order(order_id, result_value="POSITIVE"):
    return _setup_ok(
        api_client.result_stain_order(order_id, {"result_value": result_value}, HISTOTECH_HEADERS),
        "result stain order",
    )


def create_reflex_rule(
    name="Reflex rule",
    trigger_stain_type="HER2_IHC",
    trigger_result="POSITIVE",
    followup_stain_type="KI67",
    priority=1,
):
    payload = {
        "name": name,
        "trigger_stain_type": trigger_stain_type,
        "trigger_result": trigger_result,
        "followup_stain_type": followup_stain_type,
        "priority": priority,
    }
    return _setup_ok(api_client.create_reflex_rule(payload, ADMIN_HEADERS), "reflex rule")


def get_reflex_rule(rule_id):
    return _setup_ok(api_client.get_reflex_rule(rule_id, ADMIN_HEADERS), "get reflex rule")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def get_report(report_id):
    return _setup_ok(api_client.get_report(report_id, ADMIN_HEADERS), "get report")


def list_reports(case_id=None, status=None):
    params = {}
    if case_id is not None:
        params["case_id"] = case_id
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(api_client.list_reports(ADMIN_HEADERS, params=params))
    return data


def get_signed_report_id(case_id):
    """The case's unique SIGNED report id."""
    reports = list_reports(case_id=case_id, status="SIGNED")
    assert len(reports) == 1, f"expected exactly one SIGNED report for case {case_id}"
    return reports[0]["id"]


# ---------------------------------------------------------------------------
# Consultations
# ---------------------------------------------------------------------------

def create_consultation(
    case_id,
    requester_id,
    consultant_id,
    subspecialty="GI",
    question_text="grade?",
    due_at=DEFAULT_CONSULT_DUE,
):
    payload = {
        "consultant_pathologist_id": consultant_id,
        "subspecialty": subspecialty,
        "question_text": question_text,
        "due_at": due_at,
    }
    return _setup_ok(
        api_client.create_consultation(case_id, payload, make_pathologist_headers(requester_id)),
        "consultation",
    )


def get_consultation(consultation_id):
    return _setup_ok(
        api_client.get_consultation(consultation_id, ADMIN_HEADERS), "get consultation"
    )


def accept_consultation(consultation_id, consultant_id):
    return _setup_ok(
        api_client.accept_consultation(consultation_id, make_pathologist_headers(consultant_id)),
        "accept consultation",
    )


def decline_consultation(consultation_id, consultant_id, reason="overloaded"):
    return _setup_ok(
        api_client.decline_consultation(
            consultation_id, {"reason": reason}, make_pathologist_headers(consultant_id)
        ),
        "decline consultation",
    )


def answer_consultation(consultation_id, consultant_id, opinion_text="agree", concordance="CONCORDANT"):
    return _setup_ok(
        api_client.answer_consultation(
            consultation_id,
            {"opinion_text": opinion_text, "concordance": concordance},
            make_pathologist_headers(consultant_id),
        ),
        "answer consultation",
    )


def incorporate_consultation(consultation_id, requester_id):
    return _setup_ok(
        api_client.incorporate_consultation(
            consultation_id, make_pathologist_headers(requester_id)
        ),
        "incorporate consultation",
    )


def reroute_consultation(consultation_id, requester_id, new_consultant_id, new_due_at):
    return _setup_ok(
        api_client.reroute_consultation(
            consultation_id,
            {"consultant_pathologist_id": new_consultant_id, "due_at": new_due_at},
            make_pathologist_headers(requester_id),
        ),
        "reroute consultation",
    )


# ---------------------------------------------------------------------------
# Discrepancies
# ---------------------------------------------------------------------------

def create_discrepancy(case_id, severity, description, report_id=None):
    payload = {"severity": severity, "description": description}
    if report_id is not None:
        payload["report_id"] = report_id
    return _setup_ok(
        api_client.create_discrepancy(case_id, payload, ADMIN_HEADERS),
        "discrepancy",
    )


def get_discrepancy(discrepancy_id):
    return _setup_ok(
        api_client.get_discrepancy(discrepancy_id, ADMIN_HEADERS), "get discrepancy"
    )


def acknowledge_discrepancy(discrepancy_id, pathologist_id):
    return _setup_ok(
        api_client.acknowledge_discrepancy(
            discrepancy_id, make_pathologist_headers(pathologist_id)
        ),
        "acknowledge discrepancy",
    )


def resolve_discrepancy(discrepancy_id, resolved_with_amendment=None):
    payload = {}
    if resolved_with_amendment is not None:
        payload["resolved_with_amendment"] = resolved_with_amendment
    return _setup_ok(
        api_client.resolve_discrepancy(discrepancy_id, payload, ADMIN_HEADERS),
        "resolve discrepancy",
    )


# ---------------------------------------------------------------------------
# Release requests
# ---------------------------------------------------------------------------

def create_release_request(
    material_type="SLIDE",
    block_id=None,
    slide_id=None,
    requesting_institution="County Hospital",
    reason="external review",
    requested_out_at=DEFAULT_LOAN_OUT,
    due_back_at=DEFAULT_LOAN_DUE_BACK,
):
    payload = {
        "material_type": material_type,
        "requesting_institution": requesting_institution,
        "reason": reason,
        "requested_out_at": requested_out_at,
        "due_back_at": due_back_at,
    }
    if block_id is not None:
        payload["block_id"] = block_id
    if slide_id is not None:
        payload["slide_id"] = slide_id
    return _setup_ok(
        api_client.create_release_request(payload, ADMIN_HEADERS),
        "release request",
    )


def get_release_request(request_id):
    return _setup_ok(
        api_client.get_release_request(request_id, ADMIN_HEADERS), "get release request"
    )


def approve_release_request(request_id):
    return _setup_ok(
        api_client.approve_release_request(request_id, ADMIN_HEADERS), "approve release"
    )


def deny_release_request(request_id, reason="overlap"):
    return _setup_ok(
        api_client.deny_release_request(request_id, {"reason": reason}, ADMIN_HEADERS),
        "deny release",
    )


def ship_release_request(request_id):
    return _setup_ok(api_client.ship_release_request(request_id, HISTOTECH_HEADERS), "ship release")


def return_release_request(request_id):
    return _setup_ok(
        api_client.return_release_request(request_id, HISTOTECH_HEADERS), "return release"
    )


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return _setup_ok(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS),
        "set clock",
    )


# ---------------------------------------------------------------------------
# Composite: case with a worked-up inventory
# ---------------------------------------------------------------------------

def setup_workup_case(
    mrn=None,
    patient_dob=DEFAULT_DOB,
    subspecialty="GI",
    tat_mode=None,
    specimen_type="BIOPSY",
    anatomical_site="Colon",
    collection_datetime=DEFAULT_COLLECTION,
    received_datetime=DEFAULT_RECEIVED,
    container_count=1,
    num_blocks=1,
    embed_blocks=True,
    slides_per_block=0,
):
    """Patient + case + one accessioned, grossed specimen + blocks/slides.
    Returns dict(patient, case, specimen, blocks, slides). Case is in WORKUP."""
    mrn = mrn or next_mrn()
    patient = create_patient(mrn=mrn, date_of_birth=patient_dob)
    case = create_case(patient["id"], subspecialty=subspecialty, tat_mode=tat_mode)
    specimen = accession_specimen(
        case["id"],
        patient_mrn=mrn,
        patient_dob=patient_dob,
        specimen_type=specimen_type,
        anatomical_site=anatomical_site,
        collection_datetime=collection_datetime,
        received_datetime=received_datetime,
        container_count=container_count,
    )
    gross_specimen(specimen["id"])
    blocks = []
    slides = []
    for i in range(num_blocks):
        block = create_block(specimen["id"], block_label=f"A{i + 1}")
        if embed_blocks:
            block = embed_block(block["id"])
        blocks.append(block)
        for j in range(slides_per_block):
            slides.append(create_slide(block["id"], slide_label=f"A{i + 1}-{j + 1}"))
    return {
        "patient": patient,
        "case": case,
        "specimen": specimen,
        "blocks": blocks,
        "slides": slides,
        "mrn": mrn,
    }


def setup_qc_passed_case(
    mrn=None,
    subspecialty="GI",
    tat_mode=None,
    specimen_type="BIOPSY",
    collection_datetime=DEFAULT_COLLECTION,
    received_datetime=DEFAULT_RECEIVED,
    num_qc_slides=1,
    consumption_pct=10.0,
    pathologist_name="Dr Signer",
):
    """WORKUP case with one EMBEDDED block and `num_qc_slides` QC_PASSED slides,
    plus a pathologist created (not yet assigned). Returns dict with
    patient, case, specimen, block, slides, pathologist."""
    mrn = mrn or next_mrn()
    patient = create_patient(mrn=mrn)
    pathologist = create_pathologist(full_name=pathologist_name, subspecialties=(subspecialty,))
    case = create_case(patient["id"], subspecialty=subspecialty, tat_mode=tat_mode)
    specimen = accession_specimen(
        case["id"],
        patient_mrn=mrn,
        specimen_type=specimen_type,
        collection_datetime=collection_datetime,
        received_datetime=received_datetime,
    )
    gross_specimen(specimen["id"])
    block = embed_block(create_block(specimen["id"], block_label="A1")["id"])
    slides = []
    for i in range(num_qc_slides):
        slide = create_slide(block["id"], slide_label=f"A1-{i + 1}")
        section_slide(slide["id"], consumption_pct=consumption_pct)
        stain_complete_slide(slide["id"])
        slides.append(qc_review_slide(slide["id"], result="PASS"))
    return {
        "patient": patient,
        "pathologist": pathologist,
        "case": case,
        "specimen": specimen,
        "block": block,
        "slides": slides,
        "mrn": mrn,
    }


def setup_pending_signout_case(**kwargs):
    """QC-passed case, assigned and submitted: case is PENDING_SIGNOUT."""
    ctx = setup_qc_passed_case(**kwargs)
    assign_case(ctx["case"]["id"], ctx["pathologist"]["id"])
    submit_for_signout(ctx["case"]["id"], ctx["pathologist"]["id"])
    return ctx


def setup_final_case(**kwargs):
    """Full lifecycle through FINAL. Returns ctx plus report_id."""
    ctx = setup_pending_signout_case(**kwargs)
    sign_out_case(ctx["case"]["id"], ctx["pathologist"]["id"])
    ctx["report_id"] = get_signed_report_id(ctx["case"]["id"])
    return ctx


def setup_consulted_case(
    mrn=None,
    subspecialty="GI",
    due_at=DEFAULT_CONSULT_DUE,
    consultant_name="Dr Consult",
):
    """WORKUP case assigned to p1 with a REQUESTED consultation from p1 to p2."""
    mrn = mrn or next_mrn()
    patient = create_patient(mrn=mrn)
    requester = create_pathologist(full_name="Dr Req", subspecialties=(subspecialty,))
    consultant = create_pathologist(full_name=consultant_name, subspecialties=(subspecialty,))
    case = create_case(patient["id"], subspecialty=subspecialty)
    specimen = accession_specimen(case["id"], patient_mrn=mrn)
    gross_specimen(specimen["id"])
    assign_case(case["id"], requester["id"])
    consultation = create_consultation(
        case["id"], requester["id"], consultant["id"], subspecialty=subspecialty, due_at=due_at
    )
    return {
        "patient": patient,
        "case": case,
        "specimen": specimen,
        "requester": requester,
        "consultant": consultant,
        "consultation": consultation,
        "mrn": mrn,
    }
