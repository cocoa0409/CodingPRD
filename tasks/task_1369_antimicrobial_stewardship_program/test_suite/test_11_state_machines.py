"""State-machine claims: valid transitions, invalid transitions, terminal
lockdown, initial states, and side-effect execution."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    create_restricted_order_with_request, create_finalized_snapshot,
    create_submitted_report, create_dot_snapshot_payload,
    create_regulatory_report_payload, create_allergy_assessment_payload,
    api_client, ApiErrorId,
)


def _setup_submitted_request():
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
        is_restricted=True, has_po_form=False,
    )
    order, request = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    return hospital, md, ph, order, request


def test_approval_decide_approved_happy_path(api):
    """PRD Section 3.2: "Approval sets the order's `approval_status` to
    `APPROVED` and, when the order was waiting in `AWAITING_APPROVAL`, promotes
    `therapy_status` to `ACTIVE` with `started_at` stamped; the request records
    `decided_at` and `decided_by_id`."

    Design: Corner/state_machines/approval_decide_approved_happy_path
    """
    _, _, ph, order, request = _setup_submitted_request()
    decided = validate_success(
        api.decide_approval_request(
            request["id"],
            {"decision": "APPROVED", "decider_id": ph["id"]},
            make_pharmacist_headers(ph["id"]),
        ), 200,
    )
    assert decided["status"] == "APPROVED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched_order["approval_status"] == "APPROVED"
    assert fetched_order["therapy_status"] == "ACTIVE"
    assert fetched_order["started_at"] == "2026-08-01T00:00:00Z"


def test_approval_decide_denied_cascades_discontinue(api):
    """PRD Section 3.2: "Denial sets the order's `approval_status` to `DENIED`
    and, when the order was waiting, moves `therapy_status` to `DISCONTINUED`
    with `stopped_at` stamped."

    Design: Corner/state_machines/approval_decide_denied_cascades_discontinue
    """
    _, _, ph, order, request = _setup_submitted_request()
    decided = validate_success(
        api.decide_approval_request(
            request["id"],
            {"decision": "DENIED", "decider_id": ph["id"]},
            make_pharmacist_headers(ph["id"]),
        ), 200,
    )
    assert decided["status"] == "DENIED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched_order["approval_status"] == "DENIED"
    assert fetched_order["therapy_status"] == "DISCONTINUED"
    assert fetched_order["stopped_at"] == "2026-08-01T00:00:00Z"


def test_escalated_request_id_pharmacist_cannot_decide(api):
    """PRD Section 2.9: "A fifth separation governs escalation: once an
    approval request has been escalated, only the `StewardshipDirector` may
    decide it, and any other decider is rejected with
    `ERR_ESCALATED_REQUIRES_DIRECTOR`."

    Design: Corner/state_machines/escalated_request_id_pharmacist_cannot_decide
    """
    _, _, ph, _, request = _setup_submitted_request()
    validate_success(
        api.escalate_approval_request(
            request["id"],
            {"escalation_reason": "Restricted carbapenem use in septic shock"},
            make_pharmacist_headers(ph["id"]),
        ), 200,
    )
    res = api.decide_approval_request(
        request["id"],
        {"decision": "APPROVED", "decider_id": ph["id"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ESCALATED_REQUIRES_DIRECTOR)
    fetched = validate_success(
        api.get_approval_request(request["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched["status"] == "ESCALATED"


def test_escalated_request_does_not_auto_expire(api):
    """PRD Section 3.2: "Escalated requests are exempt from auto-expiry." and
    PRD Section 2.4: "First, any approval request still in `SUBMITTED` whose
    age has reached the hospital's `restricted_auto_expire_hours` transitions
    to `EXPIRED`, with the order-level cascade described in §3.2."

    Design: Corner/state_machines/escalated_request_does_not_auto_expire
    """
    hospital, _, ph, _, request = _setup_submitted_request()
    validate_success(
        api.escalate_approval_request(
            request["id"],
            {"escalation_reason": "Needs director review for policy exception"},
            make_pharmacist_headers(ph["id"]),
        ), 200,
    )
    set_clock(hospital["id"], "2026-08-06T00:00:00Z")
    fetched = validate_success(
        api.get_approval_request(request["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched["status"] == "ESCALATED"


def test_approval_terminal_lockdown_decide_after_approved(api):
    """PRD Section 3.2: "The request must still be in `SUBMITTED` or
    `ESCALATED` (`ERR_APPROVAL_NOT_PENDING`)".

    Design: Corner/state_machines/approval_terminal_lockdown_decide_after_approved
    """
    _, _, ph, _, request = _setup_submitted_request()
    validate_success(
        api.decide_approval_request(
            request["id"],
            {"decision": "APPROVED", "decider_id": ph["id"]},
            make_pharmacist_headers(ph["id"]),
        ), 200,
    )
    res = api.decide_approval_request(
        request["id"],
        {"decision": "DENIED", "decider_id": ph["id"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPROVAL_NOT_PENDING)
    fetched = validate_success(
        api.get_approval_request(request["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched["status"] == "APPROVED"


def _setup_issued_intervention(intervention_type="DURATION_REDUCTION",
                                recommendation_text="Reduce total course from 14 to 7 days per guideline"):
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
        is_restricted=False, has_po_form=False,
    )
    order = create_order(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1,
        indication="EMPIRIC",
    )
    intervention = create_issued_intervention(
        order, ph, intervention_type=intervention_type,
        recommendation_text=recommendation_text,
    )
    return hospital, md, ph, order, intervention


def test_intervention_issue_from_non_documented_rejected(api):
    """PRD Section 3.3: "Issuing the recommendation requires the intervention
    to still be `DOCUMENTED` (`ERR_INTERVENTION_NOT_DRAFT`) and the target
    order's `therapy_status` to be `ACTIVE` or `REVIEW_REQUIRED`
    (`ERR_ORDER_NOT_AUDITABLE`)."

    Design: Corner/state_machines/intervention_issue_from_non_documented_rejected
    """
    _, _, ph, _, intervention = _setup_issued_intervention()
    res = api.issue_audit_intervention(
        intervention["id"], make_pharmacist_headers(ph["id"])
    )
    validate_error(res, ApiErrorId.ERR_INTERVENTION_NOT_DRAFT)
    fetched = validate_success(
        api.get_audit_intervention(intervention["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched["recommendation_status"] == "RECOMMENDED"


def test_intervention_accept_stop_discontinues_order(api):
    """PRD Section 3.3: "accepting a `STOP` recommendation closes therapy
    outright — the order moves from `REVIEW_REQUIRED` to `DISCONTINUED` with
    `stopped_at` stamped — while accepting any other type returns the order
    from `REVIEW_REQUIRED` toward resumed therapy".

    Design: Corner/state_machines/intervention_accept_stop_discontinues_order
    """
    _, md, _, order, intervention = _setup_issued_intervention(
        intervention_type="STOP",
        recommendation_text="Blood cultures negative x48h; stop all antibiotics",
    )
    accepted = validate_success(
        api.respond_audit_intervention(
            intervention["id"],
            {"response": "ACCEPTED", "responder_id": md["id"]},
            make_physician_headers(md["id"]),
        ), 200,
    )
    assert accepted["recommendation_status"] == "ACCEPTED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_order["therapy_status"] == "DISCONTINUED"
    assert fetched_order["stopped_at"] == "2026-08-01T00:00:00Z"


def test_intervention_accept_iv_to_po_converts_order(api):
    """PRD Section 3.3: "accepting an `IV_TO_PO` recommendation moves the order
    to `CONVERTED` and rewrites `route` to `PO`".

    Design: Corner/state_machines/intervention_accept_iv_to_po_converts_order
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid)
    order = create_order(
        patient, drug, md, route="IV", dose_mg=500, frequency_per_day=1,
        indication="EMPIRIC",
    )
    intervention = create_issued_intervention(
        order, ph, intervention_type="IV_TO_PO",
        recommendation_text="Patient tolerating oral intake; switch to levofloxacin PO",
    )
    accepted = validate_success(
        api.respond_audit_intervention(
            intervention["id"],
            {"response": "ACCEPTED", "responder_id": md["id"]},
            make_physician_headers(md["id"]),
        ), 200,
    )
    assert accepted["recommendation_status"] == "ACCEPTED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_order["therapy_status"] == "CONVERTED"
    assert fetched_order["route"] == "PO"


def _drive_assessment_to_delabled():
    """SUSPECTED -> TESTING_SCHEDULED -> TESTED -> DELABELED via NEGATIVE."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(patient["id"], years_since_reaction=12),
        make_pharmacist_headers(ph["id"]),
    )
    assessment = get_success_data(res)
    validate_success(
        api_client.schedule_allergy_test(assessment["id"], make_pharmacist_headers(ph["id"])), 200
    )
    res = api_client.record_allergy_result(
        assessment["id"], {"test_result": "NEGATIVE"}, make_pharmacist_headers(ph["id"])
    )
    return hospital, md, ph, get_success_data(res)


def test_allergy_terminal_delabeled_cannot_withdraw(api):
    """PRD Section 3.6: "An assessment may also be withdrawn by an
    `IDPharmacist` or the `StewardshipDirector` from `SUSPECTED`,
    `TESTING_SCHEDULED`, or `CONFIRMED`, moving it to `WITHDRAWN`; assessments
    already in the terminal states `DELABELED` or `WITHDRAWN` reject further
    transitions with `ERR_ALLERGY_TERMINAL`."

    Design: Corner/state_machines/allergy_terminal_delabeled_cannot_withdraw
    """
    _, _, ph, assessment = _drive_assessment_to_delabled()
    assert assessment["status"] == "DELABELED"
    res = api.withdraw_allergy_assessment(
        assessment["id"], make_pharmacist_headers(ph["id"])
    )
    validate_error(res, ApiErrorId.ERR_ALLERGY_TERMINAL)
    fetched = validate_success(
        api.get_allergy_assessment(assessment["id"], make_pharmacist_headers(ph["id"])), 200
    )
    assert fetched["status"] == "DELABELED"


def test_allergy_indeterminate_loops_to_scheduled(api):
    """PRD Section 3.6: "`INDETERMINATE` loops it back to `TESTING_SCHEDULED`
    for another attempt."

    Design: Corner/state_machines/allergy_indeterminate_loops_to_scheduled
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(patient["id"], years_since_reaction=12),
        make_pharmacist_headers(ph["id"]),
    )
    assessment = get_success_data(res)
    validate_success(
        api_client.schedule_allergy_test(assessment["id"], make_pharmacist_headers(ph["id"])), 200
    )
    res = api.record_allergy_result(
        assessment["id"], {"test_result": "INDETERMINATE"}, make_pharmacist_headers(ph["id"])
    )
    recorded = validate_success(res, 200)
    assert recorded["status"] == "TESTING_SCHEDULED"
    assert recorded["test_result"] == "INDETERMINATE"


def test_order_initial_state_restricted_vs_unrestricted(api):
    """PRD Section 3.2: "Ordering an unrestricted antimicrobial sets
    `approval_status` to `NOT_REQUIRED` and `therapy_status` to `ACTIVE`, and
    stamps `started_at` from the hospital clock." and "Ordering a restricted
    drug instead sets `approval_status` to `PENDING` and `therapy_status` to
    `AWAITING_APPROVAL`; the order sits inert — no doses may be recorded
    against it — until the approval workflow resolves."

    Design: Corner/state_machines/order_initial_state_restricted_vs_unrestricted
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    unrestricted = create_drug(
        hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
        is_restricted=False, has_po_form=False,
    )
    restricted = create_drug(
        hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
        is_restricted=True, has_po_form=False,
    )
    order_u = create_order(patient, unrestricted, md, route="IV", dose_mg=1000, frequency_per_day=1)
    order_r = create_order(patient, restricted, md, route="IV", dose_mg=1000, frequency_per_day=3)
    assert order_u["approval_status"] == "NOT_REQUIRED"
    assert order_u["therapy_status"] == "ACTIVE"
    assert order_r["approval_status"] == "PENDING"
    assert order_r["therapy_status"] == "AWAITING_APPROVAL"


def test_dot_snapshot_reopen_blocked_when_pinned(api):
    """PRD Section 3.8: "A finalized snapshot may be reopened only by the
    `StewardshipDirector` and only while no regulatory report in `SUBMITTED` or
    `ACCEPTED` pins it: reopening a snapshot that is not `FINALIZED` fails with
    `ERR_SNAPSHOT_NOT_FINALIZED`, and reopening one pinned by such a report
    fails with `ERR_SNAPSHOT_PINNED_BY_REPORT`."

    Design: Corner/state_machines/dot_snapshot_reopen_blocked_when_pinned
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    snapshot = create_finalized_snapshot(hospital, ip)
    create_submitted_report(hospital, ip, snapshot)
    res = api.reopen_dot_snapshot(snapshot["id"], make_director_headers(director["id"]))
    validate_error(res, ApiErrorId.ERR_SNAPSHOT_PINNED_BY_REPORT)
    fetched = validate_success(
        api.get_dot_snapshot(snapshot["id"], make_director_headers(director["id"])), 200
    )
    assert fetched["status"] == "FINALIZED"
