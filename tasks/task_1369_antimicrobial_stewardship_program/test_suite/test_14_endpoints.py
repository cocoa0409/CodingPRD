"""Endpoint action claims: discharge cascade, conversion accept/decline,
antibiogram publish supersession and empty-publish guard, guideline adoption
retiring the predecessor, snapshot period closure."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    make_microbiologist_headers, make_preventionist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    setup_iv_order_with_hours, create_antibiogram_with_row,
    create_published_antibiogram, publish_antibiogram,
    create_empiric_guideline_payload, create_and_adopt_guideline,
    create_dot_snapshot_payload,
    api_client, ApiErrorId,
)


def test_patient_discharge_completes_open_orders(api):
    """PRD Section 3.1: "Discharge — an `AttendingPhysician` action — moves the
    case to `DISCHARGED` and locks the chart in one pass: every order not yet
    in a terminal therapy state is moved to `COMPLETED` with `stopped_at`
    stamped from the clock, and every intervention still in `DOCUMENTED` or
    `RECOMMENDED` is moved to `SUPERSEDED`."

    Design: Corner/endpoints/patient_discharge_completes_open_orders
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
    discharged = validate_success(
        api.discharge_patient_case(patient["id"], make_physician_headers(md["id"])), 200
    )
    assert discharged["status"] == "DISCHARGED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_order["therapy_status"] == "COMPLETED"
    assert fetched_order["stopped_at"] == "2026-08-01T00:00:00Z"
    fetched_intervention = validate_success(
        api.get_audit_intervention(intervention["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_intervention["recommendation_status"] == "SUPERSEDED"


def test_conversion_opportunity_accept_applies_route_change(api):
    """PRD Section 3.5: "on success the order's `route` becomes `PO`, its
    `therapy_status` becomes `CONVERTED`, the opportunity becomes `ACCEPTED`,
    and both DOT counters keep accruing under the new route."

    Design: Corner/endpoints/conversion_opportunity_accept_applies_route_change
    """
    env = setup_iv_order_with_hours(8, frequency_per_day=4, crcl=90)
    order = env["order"]
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    opp = validate_success(res, 201)
    accepted = validate_success(
        api.accept_conversion_opportunity(
            opp["id"], {"accepter_id": env["md"]["id"]},
            make_physician_headers(env["md"]["id"]),
        ), 200,
    )
    assert accepted["status"] == "ACCEPTED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(env["md"]["id"])), 200
    )
    assert fetched_order["route"] == "PO"
    assert fetched_order["therapy_status"] == "CONVERTED"


def test_conversion_decline_leaves_order_untouched(api):
    """PRD Section 3.5: "Declining — carrying the `decliner_id` — is likewise
    guarded: an opportunity no longer in `DETECTED` is rejected with
    `ERR_OPPORTUNITY_NOT_DETECTED`, and a live one moves to `DECLINED`."

    Design: Corner/endpoints/conversion_decline_leaves_order_untouched
    """
    env = setup_iv_order_with_hours(8, frequency_per_day=4, crcl=90)
    order = env["order"]
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    opp = validate_success(res, 201)
    declined = validate_success(
        api.decline_conversion_opportunity(
            opp["id"], {"decliner_id": env["md"]["id"]},
            make_physician_headers(env["md"]["id"]),
        ), 200,
    )
    assert declined["status"] == "DECLINED"
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(env["md"]["id"])), 200
    )
    assert fetched_order["route"] == "IV"
    assert fetched_order["therapy_status"] == "ACTIVE"


def test_antibiogram_publish_supersedes_prior(api):
    """PRD Section 3.7: "Publication moves the antibiogram to `PUBLISHED`,
    moves any other `PUBLISHED` antibiogram of the same hospital to
    `SUPERSEDED` so that exactly one published posture exists at a time,
    increments the hospital's `version` by one, and sweeps every `ADOPTED`
    empiric guideline of the hospital for staleness".

    Design: Corner/endpoints/antibiogram_publish_supersedes_prior
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    ab1, _ = create_published_antibiogram(hospital, mb, patient, drug)
    # Second culture in the September window, then a second antibiogram.
    set_clock(hid, "2026-09-02T00:00:00Z")
    ab2, _ = create_antibiogram_with_row(
        hospital, mb, patient, drug,
        period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        organism="KLEBSIELLA", interpretation="R",
    )
    published2 = publish_antibiogram(ab2["id"], hid, mb)
    assert published2["status"] == "PUBLISHED"
    fetched_ab1 = validate_success(
        api.get_antibiogram(ab1["id"], make_microbiologist_headers(mb["id"])), 200
    )
    assert fetched_ab1["status"] == "SUPERSEDED"


def test_empty_antibiogram_cannot_publish(api):
    """PRD Section 3.7: "Publishing — available to `Microbiologist` and
    `StewardshipDirector` — requires the antibiogram to be `DRAFT`
    (`ERR_ANTIBIOGRAM_NOT_DRAFT`) and to carry at least one reportable row
    (`ERR_ANTIBIOGRAM_EMPTY`)."

    Design: Corner/endpoints/empty_antibiogram_cannot_publish
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    res = api.create_antibiogram(
        {
            "hospital_id": hid,
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-09-01T00:00:00Z",
        },
        make_microbiologist_headers(mb["id"]),
    )
    antibiogram = validate_success(res, 201)
    assert antibiogram["row_count"] == 0
    fresh = get_success_data(api.get_hospital(hid, make_microbiologist_headers(mb["id"])))
    res = api.publish_antibiogram(
        antibiogram["id"],
        {"expected_hospital_version": fresh["version"]},
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ANTIBIOGRAM_EMPTY)


def test_guideline_adoption_happy_path_retires_predecessor(api):
    """PRD Section 3.7: "Adoption moves the guideline to `ADOPTED`, records the
    `pct_susceptible_at_adoption` snapshot of the first-line drug, retires
    whichever guideline previously stood `ADOPTED` for the same hospital and
    syndrome, and increments the hospital's `version` by one."

    Design: Corner/endpoints/guideline_adoption_happy_path_retires_predecessor
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    antibiogram, _ = create_published_antibiogram(hospital, mb, patient, drug)
    g1 = create_and_adopt_guideline(hospital, director, drug, antibiogram, syndrome="UTI")
    assert g1["status"] == "ADOPTED"
    # Successor for the same syndrome superseding g1.
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(
            hid, "UTI", drug["id"], antibiogram["id"],
            supersedes_guideline_id=g1["id"],
        ),
        make_director_headers(director["id"]),
    )
    g2 = get_success_data(res)
    fresh = get_success_data(api.get_hospital(hid, make_director_headers(director["id"])))
    adopted2 = validate_success(
        api.adopt_empiric_guideline(
            g2["id"], {"expected_hospital_version": fresh["version"]},
            make_director_headers(director["id"]),
        ), 200,
    )
    assert adopted2["status"] == "ADOPTED"
    assert adopted2["pct_susceptible_at_adoption"] == pytest.approx(100.00, abs=0.001)
    fetched_g1 = validate_success(
        api.get_empiric_guideline(g1["id"], make_director_headers(director["id"])), 200
    )
    assert fetched_g1["status"] == "RETIRED"


def test_snapshot_finalize_requires_closed_period(api):
    """PRD Section 3.8: "Finalizing a snapshot — open to
    `InfectionPreventionist` and `StewardshipDirector` — requires the snapshot
    to be `OPEN` (`ERR_SNAPSHOT_NOT_OPEN`) and the `period_label` month to lie
    strictly before the month of the hospital clock (`ERR_PERIOD_NOT_CLOSED`)".

    Design: Corner/endpoints/snapshot_finalize_requires_closed_period
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    set_clock(hid, "2026-08-15T00:00:00Z")
    res = api.create_dot_snapshot(
        create_dot_snapshot_payload(hid, period_label="2026-08", patient_days=100),
        make_preventionist_headers(ip["id"]),
    )
    snapshot = validate_success(res, 201)
    res = api.finalize_dot_snapshot(snapshot["id"], make_preventionist_headers(ip["id"]))
    validate_error(res, ApiErrorId.ERR_PERIOD_NOT_CLOSED)
    fetched = validate_success(
        api.get_dot_snapshot(snapshot["id"], make_preventionist_headers(ip["id"])), 200
    )
    assert fetched["status"] == "OPEN"
