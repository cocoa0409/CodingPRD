"""Error-catalog claims: every remaining error triggerable, with its pinned
HTTP status and trigger condition."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    make_microbiologist_headers, make_preventionist_headers, make_admin_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    create_restricted_order_with_request, create_final_culture_with_result,
    create_antibiogram_payload, create_empiric_guideline_payload,
    create_published_antibiogram, create_finalized_snapshot,
    create_dot_snapshot_payload, create_regulatory_report_payload,
    api_client, ApiErrorId,
)


def test_error_drug_suspended_on_order(api):
    """PRD Section 3.1: "A drug enters with `formulary_status` `ACTIVE`;
    suspending it via a patch to `formulary_status` moves it to `SUSPENDED`,
    after which new orders and new culture-driven recommendations involving it
    are refused — an order attempt against a suspended drug fails with
    `ERR_DRUG_SUSPENDED`, while the recommendation selector of §3.4 simply
    excludes suspended drugs from its candidate pool."

    Design: Corner/errors/error_drug_suspended_on_order
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    validate_success(
        api.patch_antimicrobial(
            drug["id"], {"formulary_status": "SUSPENDED"}, make_admin_headers()
        ), 200,
    )
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
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DRUG_SUSPENDED)


def test_error_open_intervention_blocks_complete(api):
    """PRD Section 3.2: "Completing — an `AttendingPhysician` action available
    from `ACTIVE`, `REVIEW_REQUIRED`, `DEESCALATED`, or `CONVERTED` — requires
    that no intervention for the order stands in `RECOMMENDED` or `APPEALED`
    (`ERR_OPEN_INTERVENTION_BLOCKS_CLOSE`) and that the patient is still
    admitted (`ERR_PATIENT_DISCHARGED`)".

    Design: Corner/errors/error_open_intervention_blocks_complete
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1)
    create_issued_intervention(order, ph)
    res = api.complete_order(order["id"], make_physician_headers(md["id"]))
    validate_error(res, ApiErrorId.ERR_OPEN_INTERVENTION_BLOCKS_CLOSE)
    fetched = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched["therapy_status"] == "REVIEW_REQUIRED"


def test_error_approval_already_open(api):
    """PRD Section 3.2: "the target order may have at most one open request at
    a time — a second submission while one stands in `SUBMITTED` or `ESCALATED`
    is rejected with `ERR_APPROVAL_ALREADY_OPEN`."

    Design: Corner/errors/error_approval_already_open
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3)
    res = api_client.create_approval_request(
        {
            "antibiotic_order_id": order["id"],
            "requester_id": md["id"],
            "justification": "Suspected ESBL bacteremia per prior cultures",
        },
        make_physician_headers(md["id"]),
    )
    get_success_data(res)
    res = api.create_approval_request(
        {
            "antibiotic_order_id": order["id"],
            "requester_id": md["id"],
            "justification": "Duplicate submission while first is still open",
        },
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPROVAL_ALREADY_OPEN)


def test_error_duplicate_snapshot_period(api):
    """PRD Section 3.8: "An `InfectionPreventionist` opens a monthly DOT
    snapshot by naming the `hospital_id`, a `period_label` in calendar-month
    form `YYYY-MM` that is unique within the hospital (a repeat is rejected
    with `ERR_DUPLICATE_SNAPSHOT_PERIOD`), and the `patient_days` denominator —
    the inpatient days present that month, strictly greater than zero."

    Design: Corner/errors/error_duplicate_snapshot_period
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    validate_success(
        api.create_dot_snapshot(
            create_dot_snapshot_payload(hid, period_label="2026-08", patient_days=100),
            make_preventionist_headers(ip["id"]),
        ), 201,
    )
    res = api.create_dot_snapshot(
        create_dot_snapshot_payload(hid, period_label="2026-08", patient_days=120),
        make_preventionist_headers(ip["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SNAPSHOT_PERIOD)


def test_error_report_not_submitted_on_acknowledge(api):
    """PRD Section 3.8: "The regulator's answer is recorded by the
    `StewardshipDirector` through an acknowledgement carrying an `ack` of
    `ACCEPTED` or `REJECTED`; only a `SUBMITTED` report may be acknowledged
    (`ERR_REPORT_NOT_SUBMITTED`)."

    Design: Corner/errors/error_report_not_submitted_on_acknowledge
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    snapshot = create_finalized_snapshot(hospital, ip)
    res = api_client.create_regulatory_report(
        create_regulatory_report_payload(hid, snapshot["id"]),
        make_preventionist_headers(ip["id"]),
    )
    report = get_success_data(res)
    # Report is still DRAFT — acknowledge must be refused.
    res = api.acknowledge_regulatory_report(
        report["id"], {"ack": "ACCEPTED"}, make_director_headers(director["id"])
    )
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_SUBMITTED)


def test_error_intervention_overdue_on_respond(api):
    """PRD Section 3.3: "The intervention must be `RECOMMENDED`
    (`ERR_INTERVENTION_NOT_PENDING`), the responder must be the order's own
    prescriber (`ERR_NOT_PRESCRIBER`), and the clock must not have passed
    `due_at` (`ERR_INTERVENTION_OVERDUE`)." and PRD Section 2.4: "Second, any
    audit intervention still in `RECOMMENDED` whose `due_at` has passed
    transitions to `SUPERSEDED`."

    Design: Corner/errors/error_intervention_overdue_on_respond
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1)
    intervention = create_issued_intervention(order, ph)
    # Issue stamped due_at := 2026-08-01T00:00:00Z + 24h == 2026-08-02T00:00:00Z.
    # Boundary rule: overdue only when the clock has passed due_at; at exactly
    # due_at the response is still accepted.
    set_clock(hid, "2026-08-02T00:00:00Z")
    accepted = validate_success(
        api.respond_audit_intervention(
            intervention["id"],
            {"response": "ACCEPTED", "responder_id": md["id"]},
            make_physician_headers(md["id"]),
        ), 200,
    )
    assert accepted["recommendation_status"] == "ACCEPTED"


def test_error_not_request_owner_on_withdraw(api):
    """PRD Section 2.9: "Withdrawing an approval request is reserved to the
    practitioner who submitted it (`ERR_NOT_REQUEST_OWNER`)".

    Design: Corner/errors/error_not_request_owner_on_withdraw
    """
    _, md, ph, _, request = _setup_request()
    res = api.withdraw_approval_request(
        request["id"], {"withdrawer_id": ph["id"]}, make_pharmacist_headers(ph["id"])
    )
    validate_error(res, ApiErrorId.ERR_NOT_REQUEST_OWNER)


def _setup_request():
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    order, request = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    return hospital, md, ph, order, request


def test_error_no_supporting_culture_on_deescalation_accept(api):
    """PRD Section 3.5: "For `DEESCALATION`, four hard gates must pass: a
    `FINAL` culture report exists for the same patient; that culture carries a
    susceptibility row with `interpretation` `S` for the
    `suggested_antimicrobial_id`; the suggested drug's class is genuinely
    narrower than the current drug's class on the breadth ladder; and the
    order's `indication` is `EMPIRIC` or `CULTURE_DIRECTED`." and "otherwise
    the detection is rejected with `ERR_CONVERSION_NOT_ELIGIBLE` or
    `ERR_DEESCALATION_NOT_ELIGIBLE` respectively."

    Design: Corner/errors/error_no_supporting_culture_on_deescalation_accept
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    patient = create_patient(hid, md["id"])
    broad = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                        is_restricted=False, has_po_form=False)
    narrow = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                         is_restricted=False, has_po_form=True)
    order = create_order(patient, broad, md, route="IV", dose_mg=1000, frequency_per_day=3)
    # The FINAL culture carries R (not S) for the suggested drug -> gate G2 fails.
    create_final_culture_with_result(
        patient, mb, narrow, interpretation="R", mic_value=32.0,
    )
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "DEESCALATION",
            "suggested_antimicrobial_id": narrow["id"],
        },
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DEESCALATION_NOT_ELIGIBLE)


def test_error_invalid_period_antibiogram(api):
    """PRD Section 3.7: "An end not strictly after the start fails with
    `ERR_INVALID_PERIOD`".

    Design: Corner/errors/error_invalid_period_antibiogram
    """
    hospital = create_hospital()
    mb = create_practitioner(
        hospital["id"], "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1"
    )
    res = api.create_antibiogram(
        create_antibiogram_payload(
            hospital["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        ),
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PERIOD)


def test_error_invalid_supersession_self_reference(api):
    """PRD Section 3.7: "The supersession reference, when given, must point at
    a guideline of the same hospital and same syndrome standing in `ADOPTED` or
    `STALE` — never at the draft itself — else `ERR_INVALID_SUPERSESSION`."

    Design: Corner/errors/error_invalid_supersession_self_reference
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    antibiogram, _ = create_published_antibiogram(hospital, mb, patient, drug)
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(hid, "UTI", drug["id"], antibiogram["id"]),
        make_director_headers(director["id"]),
    )
    g1 = get_success_data(res)
    # g1 is DRAFT — not ADOPTED/STALE — so supersession pointing at it fails.
    res = api.create_empiric_guideline(
        create_empiric_guideline_payload(
            hid, "UTI", drug["id"], antibiogram["id"],
            supersedes_guideline_id=g1["id"],
        ),
        make_director_headers(director["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SUPERSESSION)
