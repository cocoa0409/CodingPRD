"""Entity-surface claims: creation defaults, required fields, enums, computed
initialization, round-trip retrieval, listing, pagination, FK reachability,
server-stamped fields."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_admin_headers, make_physician_headers, make_microbiologist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_hospital_payload, create_practitioner_payload,
    create_patient_case_payload, create_antimicrobial_payload,
    create_culture_report_payload, create_susceptibility_result_payload,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    CLOCK_START_ISO,
)


def test_hospital_create_applies_defaults(api):
    """PRD Section 3.1: "`dot_review_threshold` is the days-of-therapy length,
    in whole days, at or above which an active order is flagged for mandatory
    prospective audit — it defaults to 7 and must be at least 1;
    `iv_to_po_min_iv_hours` is the minimum cumulative IV exposure before a
    conversion opportunity may be raised — it defaults to 48 and must be at
    least 24; `antibiogram_min_isolates` is the minimum first-isolate count for
    a susceptibility row to be reportable — it defaults to 30 and must be at
    least 1; and `restricted_auto_expire_hours` is the number of hours a
    submitted approval request may sit undecided before the clock sweep expires
    it — it defaults to 72 and must be at least 1."

    Design: Corner/entities/hospital_create_applies_defaults
    """
    res = api.create_hospital(
        create_hospital_payload(name="Default Hospital", nhsn_facility_id="NHSN-D"),
        make_admin_headers(),
    )
    created = validate_success(res, 201)
    fetched = validate_success(
        api.get_hospital(created["id"], make_admin_headers()), 200
    )
    assert fetched["dot_review_threshold"] == 7
    assert fetched["iv_to_po_min_iv_hours"] == 48
    assert fetched["antibiogram_min_isolates"] == 30
    assert fetched["restricted_auto_expire_hours"] == 72
    assert fetched["current_utc"] == CLOCK_START_ISO


def test_hospital_get_not_found_returns_404(api):
    """PRD Section 2.8: "3. **Existence** — path-referenced resources exist,
    validated left to right, else `ERR_NOT_FOUND` (see §2.11)."

    Design: Corner/entities/hospital_get_not_found_returns_404
    """
    res = api.get_hospital(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_practitioner_create_missing_required_field(api):
    """PRD Section 3.1: "Practitioners join the program through admin
    registration, which records the `hospital_id` they practice at, a
    `full_name`, a `license_no` unique within the hospital, and a `discipline`
    drawn from `PHYSICIAN`, `PHARMACIST`, `MICROBIOLOGIST`, or
    `INFECTION_PREVENTIONIST`."

    Design: Corner/entities/practitioner_create_missing_required_field
    """
    hospital = create_hospital()
    payload = {
        "hospital_id": hospital["id"],
        "full_name": "No License",
        "discipline": "PHYSICIAN",
    }
    res = api.create_practitioner(payload, make_admin_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_practitioner_invalid_enum_discipline_rejected(api):
    """PRD Section 3.1: "a `discipline` drawn from `PHYSICIAN`, `PHARMACIST`,
    `MICROBIOLOGIST`, or `INFECTION_PREVENTIONIST`."

    Design: Corner/entities/practitioner_invalid_enum_discipline_rejected
    """
    hospital = create_hospital()
    res = api.create_practitioner(
        {
            "hospital_id": hospital["id"],
            "full_name": "Bad Enum",
            "license_no": "L-X",
            "discipline": "NURSE",
        },
        make_admin_headers(),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_practitioner_computed_standing_fields_initialized(api):
    """PRD Section 3.1: "Every practitioner starts with `is_active` true, a
    `stewardship_standing` of `GOOD`, and an `unresolved_noncompliance_count`
    of zero; the standing later derives from resolved interventions, as §3.3
    describes."

    Design: Corner/entities/practitioner_computed_standing_fields_initialized
    """
    hospital = create_hospital()
    res = api.create_practitioner(
        create_practitioner_payload(hospital["id"]),
        make_admin_headers(),
    )
    practitioner = validate_success(res, 201)
    assert practitioner["stewardship_standing"] == "GOOD"
    assert practitioner["unresolved_noncompliance_count"] == 0
    assert practitioner["is_active"] is True


def test_patient_case_create_and_retrieve_roundtrip(api):
    """PRD Section 3.1: "Admitting a case records the admitting `hospital_id`,
    an `mrn` unique within that hospital, the `admitted_at` timestamp (the
    logical-clock time at registration), the `ward` code, the measured
    `weight_kg` (strictly greater than zero), the `renal_function_crcl` in
    mL/min (zero or greater), and two flags that modulate downstream
    thresholds: `is_immunocompromised` (default false) and `has_enteral_access`
    (default true). A case opens with `status` `ADMITTED`."

    Design: Corner/entities/patient_case_create_and_retrieve_roundtrip
    """
    hospital = create_hospital()
    md = create_practitioner(hospital["id"], "PHYSICIAN", False)
    res = api.create_patient_case(
        create_patient_case_payload(
            hospital["id"], mrn="MRN-RT", ward="ICU", weight_kg=82.5,
            renal_function_crcl=45, is_immunocompromised=True,
            has_enteral_access=False,
        ),
        make_physician_headers(md["id"]),
    )
    created = validate_success(res, 201)
    fetched = validate_success(
        api.get_patient_case(created["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched["mrn"] == "MRN-RT"
    assert fetched["ward"] == "ICU"
    assert fetched["is_immunocompromised"] is True
    assert fetched["has_enteral_access"] is False
    assert fetched["status"] == "ADMITTED"


def test_antimicrobial_list_filter_by_hospital(api):
    """PRD Section 4: "List the formulary, filterable by `hospital_id`,
    `is_restricted`, and `drug_class`".

    Design: Corner/entities/antimicrobial_list_filter_by_hospital
    """
    h1 = create_hospital(name="H1", nhsn_facility_id="NHSN-1")
    h2 = create_hospital(name="H2", nhsn_facility_id="NHSN-2")
    create_drug(h1["id"], drug_name="DRUG-A", drug_class="CEPHALOSPORIN",
                is_restricted=False, has_po_form=False)
    create_drug(h2["id"], drug_name="DRUG-B", drug_class="MACROLIDE",
                is_restricted=False, has_po_form=True)
    data, meta = validate_paginated(
        api.list_antimicrobials(make_admin_headers(), params={"hospital_id": h1["id"]})
    )
    names = [row["drug_name"] for row in data]
    assert names == ["DRUG-A"]
    assert "DRUG-B" not in names


def test_pagination_envelope_fields_present(api):
    """PRD Section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10 when omitted, and values below 1 or above 100
    are out of range — the minimum is 1 and the maximum is 100. The `offset`
    parameter states how many items to skip and defaults to 0." and "Paginated
    list responses carry `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/entities/pagination_envelope_fields_present
    """
    hospital = create_hospital()
    md = create_practitioner(hospital["id"], "PHYSICIAN", False)
    create_patient(hospital["id"], md["id"], mrn="M1")
    create_patient(hospital["id"], md["id"], mrn="M2")
    data, meta = validate_paginated(
        api.list_patient_cases(
            make_physician_headers(md["id"]), params={"hospital_id": hospital["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 2


def test_susceptibility_result_fk_reverse_reachable(api):
    """PRD Section 3.4: "Susceptibility rows are added to a culture by a
    `Microbiologist`, each naming the tested `antimicrobial_id`, an
    `interpretation` of `S` (susceptible), `I` (intermediate), or `R`
    (resistant) per the breakpoint standard, and a `mic_value` strictly greater
    than zero."

    Design: Corner/entities/susceptibility_result_fk_reverse_reachable
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
        is_restricted=False, has_po_form=True,
    )
    res = api.create_culture_report(
        create_culture_report_payload(patient["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    culture = validate_success(res, 201)
    res = api.create_susceptibility_result(
        culture["id"],
        create_susceptibility_result_payload(drug["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    row = validate_success(res, 201)
    children = validate_success(
        api.list_culture_susceptibility_results(
            culture["id"], make_microbiologist_headers(mb["id"])
        ), 200,
    )
    assert len(children) == 1
    assert children[0]["id"] == row["id"]


def test_order_system_fields_server_stamped(api):
    """PRD Section 3.2: "Ordering an unrestricted antimicrobial sets
    `approval_status` to `NOT_REQUIRED` and `therapy_status` to `ACTIVE`, and
    stamps `started_at` from the hospital clock." and PRD Section 2.5:
    "**`version`** (integer): a system-managed integer that increments by one
    on every mutation, including mutations applied by automatic cascades rather
    than direct client writes."

    Design: Corner/entities/order_system_fields_server_stamped
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid)
    set_clock(hid, "2026-08-05T10:00:00Z")
    order = create_order(
        patient, drug, md, route="PO", dose_mg=500, frequency_per_day=2,
        indication="EMPIRIC",
    )
    assert order["started_at"] == "2026-08-05T10:00:00Z"
    assert order["version"] == 1
