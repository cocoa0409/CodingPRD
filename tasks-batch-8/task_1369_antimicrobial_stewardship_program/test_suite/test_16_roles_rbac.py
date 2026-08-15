"""RBAC claims: exclusive-operation denials across roles, and missing auth
headers rejected before any other check."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    make_microbiologist_headers, make_preventionist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    create_order, create_restricted_order_with_request,
    create_published_antibiogram, create_empiric_guideline_payload,
    create_culture_report_payload,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
)


def test_attending_physician_cannot_decide_approval(api):
    """PRD Section 3.2: "Decisions belong to the committee: an `IDPharmacist`
    or the `StewardshipDirector` decides by supplying a `decision` of
    `APPROVED` or `DENIED` together with their `decider_id`." and PRD Section
    2.1: "Access to each operation is restricted by role per the endpoint
    catalogue in §4; an authenticated caller whose role is not on an endpoint's
    authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/roles/attending_physician_cannot_decide_approval
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    _, request = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    res = api.decide_approval_request(
        request["id"],
        {"decision": "APPROVED", "decider_id": md["id"]},
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_microbiologist_cannot_place_order(api):
    """PRD Section 3.2: "An `AttendingPhysician` places an antibiotic order
    with a payload naming the `patient_case_id`, the `antimicrobial_id`, the
    `prescriber_id`, the administration `route` (one of `IV`, `PO`, or `IM`),
    the per-dose `dose_mg` (strictly greater than zero), the
    `frequency_per_day` (between 1 and 4 doses per calendar day), and the
    `indication` — `EMPIRIC`, `CULTURE_DIRECTED`, or `PROPHYLAXIS`." and PRD
    Section 2.1: "Access to each operation is restricted by role per the
    endpoint catalogue in §4; an authenticated caller whose role is not on an
    endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/roles/microbiologist_cannot_place_order
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    res = api.create_antibiotic_order(
        {
            "patient_case_id": patient["id"],
            "antimicrobial_id": drug["id"],
            "prescriber_id": md["id"],
            "route": "IV",
            "dose_mg": 1000,
            "frequency_per_day": 1,
            "indication": "EMPIRIC",
        },
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_infection_preventionist_cannot_create_culture(api):
    """PRD Section 3.4: "The laboratory's side of the program begins when a
    `Microbiologist` registers a culture report with the `patient_case_id`, the
    `specimen_source` (an anatomic source such as `BLOOD`, `URINE`, `SPUTUM`,
    `WOUND`, or `CSF`), the `collected_at` timestamp, and the identified
    `organism` (for example `E_COLI`, `MRSA`, or `PSEUDOMONAS`)." and PRD
    Section 2.1: "Access to each operation is restricted by role per the
    endpoint catalogue in §4; an authenticated caller whose role is not on an
    endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/roles/infection_preventionist_cannot_create_culture
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    res = api.create_culture_report(
        create_culture_report_payload(
            patient["id"], specimen_source="BLOOD", organism="MRSA",
        ),
        make_preventionist_headers(ip["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_id_pharmacist_cannot_adopt_guideline(api):
    """PRD Section 3.7: "Adoption belongs to the `StewardshipDirector` alone
    and carries the same hospital-version guard as publication, since adopting
    mutates hospital-scoped posture and retires the incumbent". PRD Section
    2.1: "Access to each operation is restricted by role per the endpoint
    catalogue in §4; an authenticated caller whose role is not on an endpoint's
    authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/roles/id_pharmacist_cannot_adopt_guideline
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    antibiogram, _ = create_published_antibiogram(hospital, mb, patient, drug)
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(hid, "UTI", drug["id"], antibiogram["id"]),
        make_pharmacist_headers(ph["id"]),
    )
    guideline = get_success_data(res)
    fresh = get_success_data(api.get_hospital(hid, make_pharmacist_headers(ph["id"])))
    res = api.adopt_empiric_guideline(
        guideline["id"],
        {"expected_hospital_version": fresh["version"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_missing_auth_headers_rejected(api):
    """PRD Section 2.1: "All interactions with the API are authenticated
    through two mandatory HTTP headers: `X-User-ID` identifies the acting user
    and `X-User-Role` declares their operational capacity. A request in which
    either header is missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`." and PRD Section 2.8: "Every
    request passes through a fixed validation cascade, and the order is part of
    the contract: when several checks would fail, the caller sees the error
    from the earliest failing stage. The stages run as follows. 1.
    **Authentication context** — both headers present and non-empty, else
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/roles/missing_auth_headers_rejected
    """
    # No auth headers at all; the path also references a nonexistent hospital,
    # and the auth check (stage 1) must fire before existence (stage 3).
    res = api.get_hospital(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)
