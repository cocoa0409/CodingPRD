"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: SendingPhysician / ReceivingPhysician / QualityReviewer
calls are entity-backed by Physician, and BedManager calls are entity-backed by
Facility. Every ownership-gated call uses headers built from the real entity id
via the make_* builders; the shared TEST_USERS constants are only used for
opaque roles (TransferCoordinator, Any).

A "workspace" is a plain dict of created entities that the drive_* helpers
advance through the transfer-case lifecycle:

    ws = setup_certified_case(...)          # case EMTALA_DETERMINED
    drive_to_awaiting(ws)                   # -> AWAITING_ACCEPTANCE
    drive_to_accepted(ws)                   # -> ACCEPTED (auto bed hold)
    drive_to_dispatch_ready(ws)             # packet READY + insurance NOTIFIED
    drive_to_en_route(ws)                   # dispatch + depart
    drive_to_arrived(ws)                    # arrive (TransferOutcome created)
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .constants import (
    DEFAULT_CERTIFICATION,
    DEFAULT_REFUSAL_NARRATIVE,
    DEFAULT_REVIEW_FINDINGS,
)
from .test_users import (
    TEST_USERS,
    make_bed_manager_headers,
    make_quality_reviewer_headers,
    make_receiving_physician_headers,
    make_sending_physician_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Move the logical clock. Returns the echoed position payload."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


# ---------------------------------------------------------------------------
# Tier 1: reference data
# ---------------------------------------------------------------------------

def create_facility(name="Sending General", facility_code="SND",
                    trauma_level="LEVEL_3", capabilities=("TRAUMA",)):
    payload = {
        "name": name,
        "facility_code": facility_code,
        "trauma_level": trauma_level,
        "capabilities": list(capabilities),
    }
    return get_success_data(api_client.create_facility(payload, COORD))


def get_facility(facility_id):
    return get_success_data(api_client.get_facility(facility_id, ANY))


def create_bed(facility_id, bed_code="ICU-01", unit_type="ICU",
               isolation_capable=None):
    payload = {"bed_code": bed_code, "unit_type": unit_type}
    if isolation_capable is not None:
        payload["isolation_capable"] = isolation_capable
    return get_success_data(api_client.create_bed(
        facility_id, payload, make_bed_manager_headers(facility_id)))


def set_bed_status(bed_id, facility_id, status):
    return get_success_data(api_client.update_bed(
        bed_id, {"status": status}, make_bed_manager_headers(facility_id)))


def list_facility_beds(facility_id, **params):
    data, _meta = validate_paginated(api_client.list_facility_beds(
        facility_id, ANY, params=params or None))
    return data


def create_physician(full_name, facility_id, specialty="EMERGENCY",
                     is_on_call=None):
    payload = {
        "full_name": full_name,
        "facility_id": facility_id,
        "specialty": specialty,
    }
    if is_on_call is not None:
        payload["is_on_call"] = is_on_call
    return get_success_data(api_client.create_physician(payload, COORD))


def create_diversion_event(facility_id, scope, starts_at, ends_at, reason,
                           unit_type=None):
    payload = {
        "scope": scope,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": reason,
    }
    if unit_type is not None:
        payload["unit_type"] = unit_type
    return get_success_data(api_client.create_diversion_event(
        facility_id, payload, make_bed_manager_headers(facility_id)))


def lift_diversion_event(event_id, facility_id):
    return get_success_data(api_client.lift_diversion_event(
        event_id, make_bed_manager_headers(facility_id)))


def list_diversion_events(facility_id, **params):
    data, _meta = validate_paginated(api_client.list_facility_diversion_events(
        facility_id, ANY, params=params or None))
    return data


# ---------------------------------------------------------------------------
# Tier 1: transfer case and EMTALA screening
# ---------------------------------------------------------------------------

def create_case(sending_facility_id, sending_physician_id, acuity_level="EMERGENT",
                required_unit_type="ICU", required_capability="CARDIAC_CATH",
                requires_isolation=None, patient_ref="PT-1"):
    payload = {
        "patient_ref": patient_ref,
        "sending_facility_id": sending_facility_id,
        "sending_physician_id": sending_physician_id,
        "acuity_level": acuity_level,
        "required_unit_type": required_unit_type,
        "required_capability": required_capability,
    }
    if requires_isolation is not None:
        payload["requires_isolation"] = requires_isolation
    return get_success_data(api_client.create_transfer_case(payload, COORD))


def get_case(case_id):
    return get_success_data(api_client.get_transfer_case(case_id, ANY))


def list_cases(**params):
    data, meta = validate_paginated(api_client.list_transfer_cases(
        ANY, params=params or None))
    return data, meta


def create_screening(case_id, sending_physician_id,
                     has_emergency_medical_condition=True, is_stabilized=True,
                     benefits_outweigh_risks=None, physician_certification=None):
    payload = {
        "has_emergency_medical_condition": has_emergency_medical_condition,
        "is_stabilized": is_stabilized,
    }
    if benefits_outweigh_risks is not None:
        payload["benefits_outweigh_risks"] = benefits_outweigh_risks
    if physician_certification is not None:
        payload["physician_certification"] = physician_certification
    return get_success_data(api_client.create_emtala_screening(
        case_id, payload, make_sending_physician_headers(sending_physician_id)))


def _array_data(response):
    """Lenient array extractor for fixed-size sub-resource reads (screening,
    outcome) that carry no pagination inputs in the PRD."""
    data = validate_success(response, response.status_code)
    assert isinstance(data, list), f"expected array payload, got {type(data)}"
    return data


def get_screening(case_id):
    """The case's screening collection (length 0 or 1)."""
    return _array_data(api_client.get_emtala_screening(case_id, ANY))


def certify_screening(case_id, sending_physician_id):
    return get_success_data(api_client.certify_emtala_screening(
        case_id, make_sending_physician_headers(sending_physician_id)))


def amend_screening(case_id, sending_physician_id, **fields):
    return get_success_data(api_client.amend_emtala_screening(
        case_id, fields, make_sending_physician_headers(sending_physician_id)))


# ---------------------------------------------------------------------------
# Tier 1: negotiation
# ---------------------------------------------------------------------------

def request_acceptance(case_id, receiving_facility_id, receiving_physician_id,
                       contact_method="PHONE", notes=None):
    payload = {
        "receiving_facility_id": receiving_facility_id,
        "receiving_physician_id": receiving_physician_id,
        "contact_method": contact_method,
    }
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.request_acceptance(case_id, payload, COORD))


def re_request(case_id, receiving_facility_id, receiving_physician_id,
               contact_method="PHONE", notes=None):
    payload = {
        "receiving_facility_id": receiving_facility_id,
        "receiving_physician_id": receiving_physician_id,
        "contact_method": contact_method,
    }
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.re_request(case_id, payload, COORD))


def accept_case(case_id, receiving_physician_id, notes=None):
    payload = {}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.accept_case(
        case_id, payload, make_receiving_physician_headers(receiving_physician_id)))


def refuse_case(case_id, receiving_physician_id, refusal_category="NO_BED_AVAILABLE",
                narrative=DEFAULT_REFUSAL_NARRATIVE):
    payload = {"refusal_category": refusal_category, "narrative": narrative}
    return get_success_data(api_client.refuse_case(
        case_id, payload, make_receiving_physician_headers(receiving_physician_id)))


def list_communications(**params):
    data, _meta = validate_paginated(api_client.list_communications(
        ANY, params=params or None))
    return data


def list_refusal_records(**params):
    data, _meta = validate_paginated(api_client.list_refusal_records(
        ANY, params=params or None))
    return data


# ---------------------------------------------------------------------------
# Tier 1: bed holds
# ---------------------------------------------------------------------------

def current_case_version(case_id):
    return get_case(case_id)["version"]


def create_manual_hold(case_id, facility_id, bed_id,
                       expected_transfer_case_version=None):
    if expected_transfer_case_version is None:
        expected_transfer_case_version = current_case_version(case_id)
    payload = {
        "bed_id": bed_id,
        "expected_transfer_case_version": expected_transfer_case_version,
    }
    return get_success_data(api_client.create_bed_hold(
        case_id, payload, make_bed_manager_headers(facility_id)))


def get_hold(hold_id):
    return get_success_data(api_client.get_bed_hold(hold_id, ANY))


def release_hold(hold_id, facility_id):
    return get_success_data(api_client.release_bed_hold(
        hold_id, make_bed_manager_headers(facility_id)))


def list_holds(**params):
    data, _meta = validate_paginated(api_client.list_bed_holds(
        ANY, params=params or None))
    return data


# ---------------------------------------------------------------------------
# Tier 1: clinical packet
# ---------------------------------------------------------------------------

def create_packet(case_id, sending_physician_id, required_documents=("H_AND_P",),
                  imaging_studies=None):
    payload = {"required_documents": list(required_documents)}
    if imaging_studies is not None:
        payload["imaging_studies"] = imaging_studies
    return get_success_data(api_client.create_clinical_packet(
        case_id, payload, make_sending_physician_headers(sending_physician_id)))


def upload_documents(packet_id, sending_physician_id, documents,
                     expected_clinical_packet_version):
    payload = {
        "documents": list(documents),
        "expected_clinical_packet_version": expected_clinical_packet_version,
    }
    return get_success_data(api_client.upload_packet_documents(
        packet_id, payload, make_sending_physician_headers(sending_physician_id)))


def exchange_imaging(packet_id, sending_physician_id, exchanged_study_refs):
    payload = {"exchanged_study_refs": list(exchanged_study_refs)}
    return get_success_data(api_client.imaging_exchange(
        packet_id, payload, make_sending_physician_headers(sending_physician_id)))


def get_packet(packet_id):
    return get_success_data(api_client.get_clinical_packet(packet_id, ANY))


# ---------------------------------------------------------------------------
# Tier 1: insurance notifications
# ---------------------------------------------------------------------------

def create_notification(case_id, payer_id="PAYER-9", channel="PORTAL"):
    payload = {"payer_id": payer_id, "channel": channel}
    return get_success_data(api_client.create_insurance_notification(
        case_id, payload, COORD))


def get_notification(notification_id):
    return get_success_data(api_client.get_insurance_notification(
        notification_id, ANY))


def mark_notified(notification_id):
    return get_success_data(api_client.notify_insurance(notification_id, COORD))


def claim_exception(notification_id, exception_reason="CLINICAL_URGENCY"):
    return get_success_data(api_client.claim_exception(
        notification_id, {"exception_reason": exception_reason}, COORD))


# ---------------------------------------------------------------------------
# Tier 1: transport and lifecycle
# ---------------------------------------------------------------------------

def dispatch_case(case_id, mode="GROUND_ALS", crew_capability="ALS",
                  distance_miles=20.0):
    payload = {
        "mode": mode,
        "crew_capability": crew_capability,
        "distance_miles": distance_miles,
    }
    return get_success_data(api_client.create_dispatch(case_id, payload, COORD))


def get_dispatch(dispatch_id):
    return get_success_data(api_client.get_transport_dispatch(dispatch_id, ANY))


def list_dispatches(**params):
    data, _meta = validate_paginated(api_client.list_transport_dispatches(
        ANY, params=params or None))
    return data


def depart_case(case_id):
    return get_success_data(api_client.depart_case(case_id, COORD))


def arrive_case(case_id, arrival_condition="STABLE", deterioration_en_route=False,
                receiving_physician_confirmed=True):
    payload = {
        "arrival_condition": arrival_condition,
        "deterioration_en_route": deterioration_en_route,
        "receiving_physician_confirmed": receiving_physician_confirmed,
    }
    return get_success_data(api_client.arrive_case(case_id, payload, COORD))


def complete_case(case_id):
    return get_success_data(api_client.complete_case(case_id, COORD))


def cancel_case(case_id, cancel_reason="Transfer no longer indicated."):
    return get_success_data(api_client.cancel_case(
        case_id, {"cancel_reason": cancel_reason}, COORD))


def get_case_outcome(case_id):
    """The case's outcome collection (length 0 or 1)."""
    return _array_data(api_client.get_case_outcome(case_id, ANY))


# ---------------------------------------------------------------------------
# Tier 1: quality reviews
# ---------------------------------------------------------------------------

def list_reviews(**params):
    data, _meta = validate_paginated(api_client.list_quality_reviews(
        ANY, params=params or None))
    return data


def get_review(review_id):
    return get_success_data(api_client.get_quality_review(review_id, ANY))


def begin_review(review_id, reviewer_physician_id):
    return get_success_data(api_client.begin_quality_review(
        review_id, make_quality_reviewer_headers(reviewer_physician_id)))


def close_review(review_id, reviewer_physician_id, outcome="CONCURRENCE",
                 findings=DEFAULT_REVIEW_FINDINGS):
    payload = {"outcome": outcome, "findings": findings}
    return get_success_data(api_client.close_quality_review(
        review_id, payload, make_quality_reviewer_headers(reviewer_physician_id)))


# ---------------------------------------------------------------------------
# Tier 2: certified-case workspace
# ---------------------------------------------------------------------------

def setup_certified_case(acuity="EMERGENT", unit="ICU",
                         required_capability="CARDIAC_CATH",
                         requires_isolation=False, emc=True, stabilized=True,
                         benefits_outweigh_risks=None,
                         physician_certification=None,
                         rcv_beds=(("ICU-01", "ICU", None),),
                         rcv_capabilities=None, patient_ref="PT-WS-1",
                         snd_code="SND", rcv_code="RCV"):
    """Facilities SND/RCV, physicians phys_s/phys_r, beds at RCV, and a case
    with a certified screening (status EMTALA_DETERMINED)."""
    fac_s = create_facility("Sending General", snd_code, "LEVEL_3", ["TRAUMA"])
    caps = list(rcv_capabilities) if rcv_capabilities is not None else [
        required_capability]
    fac_r = create_facility("Receiving Trauma Center", rcv_code, "LEVEL_1", caps)
    beds = [create_bed(fac_r["id"], code, ut, iso)
            for (code, ut, iso) in rcv_beds]
    phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
    phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")
    case = create_case(fac_s["id"], phys_s["id"], acuity, unit,
                       required_capability, requires_isolation, patient_ref)
    screening = create_screening(
        case["id"], phys_s["id"], emc, stabilized,
        benefits_outweigh_risks, physician_certification)
    screening = certify_screening(case["id"], phys_s["id"])
    ws = {
        "fac_s": fac_s, "fac_r": fac_r, "beds": beds,
        "phys_s": phys_s, "phys_r": phys_r,
        "case": get_case(case["id"]), "screening": screening,
    }
    return ws


# ---------------------------------------------------------------------------
# Tier 3: lifecycle drivers (mutate the workspace in place)
# ---------------------------------------------------------------------------

def drive_to_awaiting(ws, contact_method="PHONE", notes=None):
    """EMTALA_DETERMINED -> AWAITING_ACCEPTANCE (negotiation round opens)."""
    ws["case"] = request_acceptance(
        ws["case"]["id"], ws["fac_r"]["id"], ws["phys_r"]["id"],
        contact_method, notes)
    return ws


def drive_to_accepted(ws, notes=None):
    """AWAITING_ACCEPTANCE -> ACCEPTED (selector places the auto hold)."""
    ws["case"] = accept_case(ws["case"]["id"], ws["phys_r"]["id"], notes)
    ws["hold_id"] = ws["case"]["active_bed_hold_id"]
    return ws


def drive_to_dispatch_ready(ws, required_documents=("H_AND_P",),
                            upload=None, imaging_studies=None, exchange=None,
                            payer_id="PAYER-9", channel="PORTAL", notify=True):
    """Add a clinical packet (documents uploaded, imaging optionally exchanged)
    and an insurance notification to an ACCEPTED case."""
    pkt = create_packet(ws["case"]["id"], ws["phys_s"]["id"],
                        required_documents, imaging_studies)
    docs = list(upload) if upload is not None else list(required_documents)
    if docs:
        pkt = upload_documents(pkt["id"], ws["phys_s"]["id"], docs,
                               pkt["version"])
    if exchange:
        pkt = exchange_imaging(pkt["id"], ws["phys_s"]["id"], list(exchange))
    ws["packet"] = pkt
    notif = create_notification(ws["case"]["id"], payer_id, channel)
    if notify:
        notif = mark_notified(notif["id"])
    ws["notification"] = notif
    return ws


def drive_to_en_route(ws, mode="GROUND_ALS", crew_capability="ALS",
                      distance_miles=20.0):
    ws["dispatch"] = dispatch_case(ws["case"]["id"], mode, crew_capability,
                                   distance_miles)
    ws["case"] = depart_case(ws["case"]["id"])
    ws["dispatch"] = get_dispatch(ws["dispatch"]["id"])
    return ws


def drive_to_arrived(ws, arrival_condition="STABLE", deterioration_en_route=False,
                     receiving_physician_confirmed=True):
    ws["case"] = arrive_case(ws["case"]["id"], arrival_condition,
                             deterioration_en_route,
                             receiving_physician_confirmed)
    ws["dispatch"] = get_dispatch(ws["dispatch"]["id"])
    ws["outcome"] = get_case_outcome(ws["case"]["id"])[0]
    return ws


def refuse_current_round(ws, refusal_category="NO_BED_AVAILABLE",
                         narrative=DEFAULT_REFUSAL_NARRATIVE):
    """Refuse the case from its current receiving physician."""
    ws["case"] = refuse_case(ws["case"]["id"], ws["phys_r"]["id"],
                             refusal_category, narrative)
    return ws


def find_review_for_case(case_id):
    reviews = list_reviews(transfer_case_id=case_id)
    return reviews[0] if reviews else None
