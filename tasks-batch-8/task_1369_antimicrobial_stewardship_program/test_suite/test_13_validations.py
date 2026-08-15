"""Validation claims: violation -> pinned error for rules not covered by the
difficulty queue."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_physician_headers, make_pharmacist_headers,
    make_director_headers, make_microbiologist_headers, make_preventionist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    create_restricted_order_with_request, create_overturned_intervention,
    create_antibiotic_order_payload, create_allergy_assessment_payload,
    create_culture_report_payload, create_approval_request_payload,
    create_dot_snapshot_payload, create_finalized_snapshot,
    create_regulatory_report_payload,
    api_client, ApiErrorId,
)


def test_duplicate_active_order_rejected(api):
    """PRD Section 3.2: "a duplicate-active-order check rejects with
    `ERR_DUPLICATE_ACTIVE_ORDER` when the same patient already has an order for
    the same antimicrobial whose `therapy_status` is neither `COMPLETED` nor
    `DISCONTINUED`".

    Design: Corner/validations/duplicate_active_order_rejected
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1)
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], drug["id"], md["id"],
            route="IV", dose_mg=2000, frequency_per_day=2,
        ),
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_ORDER)


def test_restricted_order_cap_enforced(api):
    """PRD Section 3.2: "a per-patient cap rejects with
    `ERR_RESTRICTED_ORDER_CAP` when the patient already carries two concurrent
    restricted orders, where "concurrent" counts orders whose `approval_status`
    is `PENDING` or `APPROVED` and whose therapy has not reached a terminal
    state."

    Design: Corner/validations/restricted_order_cap_enforced
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    r1 = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                     is_restricted=True, has_po_form=False)
    r2 = create_drug(hid, drug_name="VANCOMYCIN", drug_class="GLYCOPEPTIDE",
                     is_restricted=True, has_po_form=False)
    r3 = create_drug(hid, drug_name="MICAFUNGIN", drug_class="ECHINOCANDIN",
                     is_restricted=True, has_po_form=False)
    create_order(patient, r1, md, route="IV", dose_mg=1000, frequency_per_day=3)
    create_order(patient, r2, md, route="IV", dose_mg=1000, frequency_per_day=2)
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], r3["id"], md["id"],
            route="IV", dose_mg=100, frequency_per_day=1,
        ),
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_RESTRICTED_ORDER_CAP)


def test_renal_dose_guardrail(api):
    """PRD Section 3.2: "The renal guardrail rejects with
    `ERR_RENAL_DOSE_EXCEEDED` whenever the patient's `renal_function_crcl` is
    below 30 and the product of `dose_mg` and `frequency_per_day` exceeds 4000
    mg per day."

    Design: Corner/validations/renal_dose_guardrail
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"], renal_function_crcl=20)
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    # 1500 * 3 = 4500 > 4000 with CrCl 20 < 30.
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], drug["id"], md["id"],
            route="IV", dose_mg=1500, frequency_per_day=3,
        ),
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_RENAL_DOSE_EXCEEDED)


def test_future_specimen_rejected(api):
    """PRD Section 3.4: "Collection may not lie in the future: `collected_at`
    after the hospital clock is rejected with `ERR_FUTURE_SPECIMEN`."

    Design: Corner/validations/future_specimen_rejected
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    # Clock is the default 2026-08-01T00:00:00Z; collected_at is one day later.
    res = api.create_culture_report(
        create_culture_report_payload(
            patient["id"], specimen_source="BLOOD",
            collected_at="2026-08-02T00:00:00Z", organism="MRSA",
        ),
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FUTURE_SPECIMEN)


def test_clock_regression_rejected(api):
    """PRD Section 2.4: "That capability takes the target `hospital_id` and a
    destination instant `to_iso8601`; the destination must be strictly later
    than the hospital's present `current_utc`, and any attempt to hold or move
    the clock backwards is rejected with `ERR_CLOCK_REGRESSION`."

    Design: Corner/validations/clock_regression_rejected
    """
    hospital = create_hospital()
    set_clock(hospital["id"], "2026-08-10T00:00:00Z")
    res = api.set_clock(
        {"hospital_id": hospital["id"], "to_iso8601": "2026-08-05T00:00:00Z"},
        make_admin_headers(),
    )
    validate_error(res, ApiErrorId.ERR_CLOCK_REGRESSION)


def test_administration_before_approval_rejected(api):
    """PRD Section 3.2: "Recording a dose against a restricted drug whose
    `approval_status` is not `APPROVED` is rejected with
    `ERR_RESTRICTED_REQUIRES_APPROVAL`."

    Design: Corner/validations/administration_before_approval_rejected
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3)
    res = api.record_administration(
        order["id"], {"administered_at": "2026-08-01T00:00:00Z"},
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_RESTRICTED_REQUIRES_APPROVAL)


def test_severe_allergy_never_schedulable(api):
    """PRD Section 3.6: "A `SEVERE` assessment may never schedule a test, from
    any origin, and is rejected with `ERR_SEVERE_ALLERGY_BLOCKED`." and "The
    reaction term adds 20 points when the `reported_reaction` text contains any
    of the anaphylaxis keywords — "anaphylaxis", "angioedema", "hives", or
    "wheeze" — matched case-insensitively as substrings, and adds nothing
    otherwise." and "The sum is capped at 100 and rounded half-up to two
    decimals."

    Design: Corner/validations/severe_allergy_never_schedulable
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(
            patient["id"],
            reported_reaction="anaphylaxis requiring ICU",
            reaction_severity="SEVERE",
            years_since_reaction=15,
        ),
        make_pharmacist_headers(ph["id"]),
    )
    assessment = get_success_data(res)
    # SEVERE base 80 + anaphylaxis keyword 20 = 100 (cap).
    assert assessment["risk_score"] == pytest.approx(100.00, abs=0.001)
    res = api.schedule_allergy_test(assessment["id"], make_pharmacist_headers(ph["id"]))
    validate_error(res, ApiErrorId.ERR_SEVERE_ALLERGY_BLOCKED)


def test_high_risk_allergy_not_schedulable(api):
    """PRD Section 3.6: "From `SUSPECTED`, scheduling additionally requires
    `delabel_eligible` to be true — a `risk_score` of 30 or higher is rejected
    with `ERR_ALLERGY_HIGH_RISK`." and "The recency term starts at 30 points
    and decays by 3 points per elapsed year of `years_since_reaction`, never
    dropping below zero".

    Design: Corner/validations/high_risk_allergy_not_schedulable
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(
            patient["id"],
            reported_reaction="hives all over",
            reaction_severity="MILD",
            years_since_reaction=2,
        ),
        make_pharmacist_headers(ph["id"]),
    )
    assessment = get_success_data(res)
    # 10 (MILD) + 20 (hives keyword) + max(0, 30-6)=24 -> 54.00 >= 30.
    assert assessment["risk_score"] == pytest.approx(54.00, abs=0.001)
    res = api.schedule_allergy_test(assessment["id"], make_pharmacist_headers(ph["id"]))
    validate_error(res, ApiErrorId.ERR_ALLERGY_HIGH_RISK)


def test_self_approval_forbidden(api):
    """PRD Section 2.9: "A practitioner who submitted a restricted-drug
    approval request may not decide it: any decision where the decider equals
    the `requester_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/validations/self_approval_forbidden
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3)
    # Pharmacist submits the request, then attempts to decide their own request.
    res = api_client.create_approval_request(
        create_approval_request_payload(
            order["id"], ph["id"],
            justification="Pharmacist-initiated request for carbapenem coverage",
        ),
        make_pharmacist_headers(ph["id"]),
    )
    request = get_success_data(res)
    res = api.decide_approval_request(
        request["id"],
        {"decision": "APPROVED", "decider_id": ph["id"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)


def test_adjudicator_conflict_rejected(api):
    """PRD Section 2.9: "A committee member adjudicating an appealed audit
    intervention must be neither the auditor who wrote it nor the prescriber
    who responded to it: a violation is rejected with
    `ERR_ADJUDICATOR_CONFLICT`."

    Design: Corner/validations/adjudicator_conflict_rejected
    """
    from test_helpers import drive_intervention_to_appealed
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1)
    intervention = create_issued_intervention(order, ph)
    appealed = drive_intervention_to_appealed(intervention["id"], ph, md)
    # Adjudicator is the original responder (md) — conflict.
    res = api.adjudicate_audit_intervention(
        appealed["id"],
        {"verdict": "UPHOLD", "adjudicator_id": md["id"]},
        make_director_headers(director["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ADJUDICATOR_CONFLICT)


def test_approval_justification_min_length(api):
    """PRD Section 3.2: "That workflow begins when the prescriber (or an
    `IDPharmacist` acting on the case) submits an approval request carrying the
    `antibiotic_order_id`, the `requester_id`, and a `justification` of at
    least 20 characters; anything shorter fails with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/approval_justification_min_length
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3)
    res = api.create_approval_request(
        create_approval_request_payload(order["id"], md["id"], justification="too short"),
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_prescriber_suspended_blocks_restricted(api):
    """PRD Section 3.2: "Last among the ordering guards, a prescriber whose
    `stewardship_standing` has fallen to `SUSPENDED` may not place
    restricted-drug orders at all (`ERR_PRESCRIBER_SUSPENDED`)." and PRD
    Section 3.3: "Standing follows a simple ladder over the count of a
    prescriber's interventions resolved `REJECTED_FINAL`: three or more makes
    the prescriber `SUSPENDED`, exactly two puts them on `WATCH`, and anything
    less is `GOOD`."

    Design: Corner/validations/prescriber_suspended_blocks_restricted
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    d1 = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                     is_restricted=False, has_po_form=False)
    d2 = create_drug(hid, drug_name="AZITHROMYCIN", drug_class="MACROLIDE",
                     is_restricted=False, has_po_form=True)
    d3 = create_drug(hid, drug_name="LEVOFLOXACIN", drug_class="FLUOROQUINOLONE",
                     is_restricted=False, has_po_form=True)
    d4 = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                     is_restricted=True, has_po_form=False)
    # Drive the prescriber to SUSPENDED via three OVERTURN-adjudicated STOP
    # interventions on three distinct unrestricted orders.
    for drug in (d1, d2, d3):
        order = create_order(patient, drug, md, route="PO", dose_mg=500, frequency_per_day=1)
        create_overturned_intervention(
            order, ph, md, director, intervention_type="STOP",
            recommendation_text="Stop therapy; cultures negative and patient stable",
        )
    prescriber = validate_success(
        api.get_practitioner(md["id"], make_physician_headers(md["id"])), 200
    )
    assert prescriber["stewardship_standing"] == "SUSPENDED"
    assert prescriber["unresolved_noncompliance_count"] == 3
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], d4["id"], md["id"],
            route="IV", dose_mg=1000, frequency_per_day=3,
        ),
        make_physician_headers(md["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PRESCRIBER_SUSPENDED)
