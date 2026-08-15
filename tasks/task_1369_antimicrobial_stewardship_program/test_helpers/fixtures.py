"""Composite setup helpers for multi-step test prerequisites.

All helpers build state exclusively through PRD-declared endpoints and use
get_success_data() (lenient) so a setup failure surfaces as a clear setup
error rather than a confusing assertion failure.

Identity threading: entity-backed role headers are built with the actual
Practitioner.id via the make_*_headers builders from test_users.py.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_hospital_payload,
    create_practitioner_payload,
    create_patient_case_payload,
    create_antimicrobial_payload,
    create_allergy_assessment_payload,
    create_culture_report_payload,
    create_susceptibility_result_payload,
    create_antibiotic_order_payload,
    create_approval_request_payload,
    create_audit_intervention_payload,
    create_antibiogram_payload,
    create_empiric_guideline_payload,
    create_dot_snapshot_payload,
    create_regulatory_report_payload,
)
from .test_users import (
    make_admin_headers,
    make_director_headers,
    make_pharmacist_headers,
    make_physician_headers,
    make_microbiologist_headers,
    make_preventionist_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation primitives
# ---------------------------------------------------------------------------

def create_hospital(**overrides):
    """Create a hospital; returns the Hospital resource."""
    res = api_client.create_hospital(create_hospital_payload(**overrides), make_admin_headers())
    return get_success_data(res)


def create_practitioner(hospital_id, role="PHYSICIAN", member=False, **overrides):
    """Register a practitioner; returns the Practitioner resource."""
    payload = create_practitioner_payload(
        hospital_id, discipline=role, is_stewardship_member=member, **overrides
    )
    res = api_client.create_practitioner(payload, make_admin_headers())
    return get_success_data(res)


def create_patient(hospital_id, admitting_physician_id, **overrides):
    """Admit a patient case as the given physician; returns the PatientCase."""
    res = api_client.create_patient_case(
        create_patient_case_payload(hospital_id, **overrides),
        make_physician_headers(admitting_physician_id),
    )
    return get_success_data(res)


def create_drug(hospital_id, **overrides):
    """Add a formulary drug; returns the Antimicrobial."""
    res = api_client.create_antimicrobial(
        create_antimicrobial_payload(hospital_id, **overrides), make_admin_headers()
    )
    return get_success_data(res)


def set_clock(hospital_id, to_iso8601):
    """Advance the hospital logical clock."""
    res = api_client.set_clock(
        {"hospital_id": hospital_id, "to_iso8601": to_iso8601}, make_admin_headers()
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: common committee scaffolding
# ---------------------------------------------------------------------------

def setup_committee(**hospital_overrides):
    """Hospital + the five entity-backed practitioners.

    Returns dict with keys: hospital, md, ph, dir, mb, ip.
    """
    hospital = create_hospital(**hospital_overrides)
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    return {"hospital": hospital, "md": md, "ph": ph, "dir": director, "mb": mb, "ip": ip}


def setup_hospital_md(**hospital_overrides):
    """Minimal hospital + one physician. Returns (hospital, md)."""
    hospital = create_hospital(**hospital_overrides)
    md = create_practitioner(hospital["id"], "PHYSICIAN", False)
    return hospital, md


def setup_hospital_md_ph(**hospital_overrides):
    """Hospital + physician + pharmacist. Returns (hospital, md, ph)."""
    hospital = create_hospital(**hospital_overrides)
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    return hospital, md, ph


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_order(patient, drug, prescriber, **overrides):
    """Place an order as the prescriber. Returns the AntibioticOrder."""
    res = api_client.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], drug["id"], prescriber["id"], **overrides
        ),
        make_physician_headers(prescriber["id"]),
    )
    return get_success_data(res)


def create_restricted_order_with_request(patient, drug, prescriber, **order_overrides):
    """Restricted order (PENDING / AWAITING_APPROVAL) + SUBMITTED approval request.

    Returns (order, approval_request).
    """
    order = create_order(patient, drug, prescriber, **order_overrides)
    res = api_client.create_approval_request(
        create_approval_request_payload(order["id"], prescriber["id"]),
        make_physician_headers(prescriber["id"]),
    )
    request = get_success_data(res)
    return order, request


def record_doses(order_id, prescriber_id, timestamps):
    """Record administrations at each timestamp (ISO strings). Returns last response data."""
    last = None
    for ts in timestamps:
        res = api_client.record_administration(
            order_id, {"administered_at": ts}, make_physician_headers(prescriber_id)
        )
        last = get_success_data(res)
    return last


def record_iv_doses_over_days(order_id, prescriber_id, hospital_id, days, per_day_times):
    """Record IV doses over consecutive days, advancing the clock between days.

    days: list of date prefixes like ["2026-08-01", "2026-08-02"]
    per_day_times: list of "HH:MM:SS" suffixes applied to each day.
    Returns last administration response data.
    """
    last = None
    for day in days:
        # Advance only when strictly later — holding the clock is rejected
        # with ERR_CLOCK_REGRESSION (PRD 2.4).
        current = get_success_data(api_client.get_hospital(hospital_id, make_admin_headers()))
        if current["current_utc"] < f"{day}T00:00:00Z":
            set_clock(hospital_id, f"{day}T00:00:00Z")
        for t in per_day_times:
            res = api_client.record_administration(
                order_id, {"administered_at": f"{day}T{t}"}, make_physician_headers(prescriber_id)
            )
            last = get_success_data(res)
    return last


# ---------------------------------------------------------------------------
# Tier 3b: intervention negotiation shortcuts
# ---------------------------------------------------------------------------

def create_issued_intervention(order, auditor, **overrides):
    """Document + issue an intervention. Returns the RECOMMENDED intervention."""
    res = api_client.create_audit_intervention(
        create_audit_intervention_payload(order["id"], auditor["id"], **overrides),
        make_pharmacist_headers(auditor["id"]),
    )
    intervention = get_success_data(res)
    res = api_client.issue_audit_intervention(intervention["id"], make_pharmacist_headers(auditor["id"]))
    return get_success_data(res)


def drive_intervention_to_appealed(intervention_id, auditor, responder):
    """RECOMMENDED -> REJECTED -> APPEALED. Returns the APPEALED intervention."""
    res = api_client.respond_audit_intervention(
        intervention_id,
        {"response": "REJECTED", "responder_id": responder["id"]},
        make_physician_headers(responder["id"]),
    )
    get_success_data(res)
    res = api_client.appeal_audit_intervention(
        intervention_id, {"appealer_id": auditor["id"]}, make_pharmacist_headers(auditor["id"])
    )
    return get_success_data(res)


def create_overturned_intervention(order, auditor, responder, adjudicator, **overrides):
    """Full negotiation cycle ending in OVERTURN (REJECTED_FINAL).

    DOCUMENTED -> RECOMMENDED -> REJECTED -> APPEALED -> REJECTED_FINAL.
    Returns the REJECTED_FINAL intervention.
    """
    intervention = create_issued_intervention(order, auditor, **overrides)
    appealed = drive_intervention_to_appealed(intervention["id"], auditor, responder)
    res = api_client.adjudicate_audit_intervention(
        appealed["id"],
        {"verdict": "OVERTURN", "adjudicator_id": adjudicator["id"]},
        make_director_headers(adjudicator["id"]),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4: culture / antibiogram / guideline scaffolding
# ---------------------------------------------------------------------------

def create_final_culture_with_result(patient, microbiologist, drug,
                                      organism="E_COLI", specimen_source="URINE",
                                      collected_at="2026-08-01T00:00:00Z",
                                      interpretation="S", mic_value=2.0):
    """Culture + one susceptibility row + finalize. Returns (culture, result)."""
    res = api_client.create_culture_report(
        create_culture_report_payload(
            patient["id"], organism=organism, specimen_source=specimen_source,
            collected_at=collected_at,
        ),
        make_microbiologist_headers(microbiologist["id"]),
    )
    culture = get_success_data(res)
    res = api_client.create_susceptibility_result(
        culture["id"],
        create_susceptibility_result_payload(
            drug["id"], interpretation=interpretation, mic_value=mic_value
        ),
        make_microbiologist_headers(microbiologist["id"]),
    )
    result = get_success_data(res)
    res = api_client.finalize_culture_report(
        culture["id"], make_microbiologist_headers(microbiologist["id"])
    )
    culture = get_success_data(res)
    return culture, result


def create_antibiogram_with_row(hospital, microbiologist, patient, drug,
                                 period_start="2026-08-01T00:00:00Z",
                                 period_end="2026-09-01T00:00:00Z",
                                 organism="E_COLI", interpretation="S"):
    """One first-isolate FINAL culture + antibiogram over the window.

    Returns (antibiogram, culture).
    """
    culture, _ = create_final_culture_with_result(
        patient, microbiologist, drug, organism=organism,
        collected_at=period_start, interpretation=interpretation,
    )
    res = api_client.create_antibiogram(
        create_antibiogram_payload(
            hospital["id"], period_start=period_start, period_end=period_end
        ),
        make_microbiologist_headers(microbiologist["id"]),
    )
    antibiogram = get_success_data(res)
    return antibiogram, culture


def publish_antibiogram(antibiogram_id, hospital_id, actor):
    """Publish with a fresh hospital version read. Returns PUBLISHED antibiogram."""
    role_headers = (
        make_microbiologist_headers(actor["id"])
        if actor.get("discipline") == "MICROBIOLOGIST"
        else make_director_headers(actor["id"])
    )
    hospital = get_success_data(api_client.get_hospital(hospital_id, role_headers))
    res = api_client.publish_antibiogram(
        antibiogram_id, {"expected_hospital_version": hospital["version"]}, role_headers
    )
    return get_success_data(res)


def create_published_antibiogram(hospital, microbiologist, patient, drug, **kwargs):
    """Antibiogram with one reportable row, published. Returns (antibiogram, culture)."""
    antibiogram, culture = create_antibiogram_with_row(
        hospital, microbiologist, patient, drug, **kwargs
    )
    published = publish_antibiogram(antibiogram["id"], hospital["id"], microbiologist)
    return published, culture


def create_and_adopt_guideline(hospital, director, drug, antibiogram, syndrome="UTI"):
    """Draft + adopt a guideline. Returns the ADOPTED guideline."""
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(
            hospital["id"], syndrome, drug["id"], antibiogram["id"]
        ),
        make_director_headers(director["id"]),
    )
    guideline = get_success_data(res)
    fresh = get_success_data(
        api_client.get_hospital(hospital["id"], make_director_headers(director["id"]))
    )
    res = api_client.adopt_empiric_guideline(
        guideline["id"],
        {"expected_hospital_version": fresh["version"]},
        make_director_headers(director["id"]),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4b: IV-to-PO accumulation targeting
# ---------------------------------------------------------------------------

def setup_iv_order_with_hours(num_doses, frequency_per_day=4, crcl=90, **hospital_overrides):
    """IV order with cumulative_iv_hours == num_doses * (24 / frequency_per_day).

    Doses are spread 3 per day across consecutive days starting 2026-08-01 so
    the DOT review sweep never interferes with detection tests.
    Returns dict: hospital, md, ph, patient, drug, order.
    """
    hospital, md, ph = setup_hospital_md_ph(**hospital_overrides)
    hid = hospital["id"]
    patient = create_patient(hid, md["id"], renal_function_crcl=crcl)
    drug = create_drug(hid)
    # NOTE: no set_clock here — the hospital clock already starts at
    # 2026-08-01T00:00:00Z (PRD 2.4) and holding the clock is rejected with
    # ERR_CLOCK_REGRESSION ("the destination must be strictly later").
    order = create_order(
        patient, drug, md, route="IV", dose_mg=500, frequency_per_day=frequency_per_day
    )
    per_day_times = ["00:00:00", "06:00:00", "12:00:00"]
    days = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"]
    remaining = num_doses
    day_idx = 0
    while remaining > 0:
        take = min(3, remaining)
        day = days[day_idx]
        # ensure clock is at start of the day (monotonic; first call is a no-op-safe set)
        current = get_success_data(api_client.get_hospital(hid, make_admin_headers()))
        if current["current_utc"] < f"{day}T00:00:00Z":
            set_clock(hid, f"{day}T00:00:00Z")
        for t in per_day_times[:take]:
            res = api_client.record_administration(
                order["id"], {"administered_at": f"{day}T{t}"}, make_physician_headers(md["id"])
            )
            get_success_data(res)
        remaining -= take
        day_idx += 1
    order = get_success_data(api_client.get_antibiotic_order(order["id"], make_physician_headers(md["id"])))
    return {"hospital": hospital, "md": md, "ph": ph, "patient": patient,
            "drug": drug, "order": order}


# ---------------------------------------------------------------------------
# Tier 5: snapshot / report terminal-state scaffolding
# ---------------------------------------------------------------------------

def create_finalized_snapshot(hospital, preventionist, period_label="2026-07",
                               patient_days=100, clock="2026-08-01T00:00:00Z"):
    """OPEN snapshot for a closed month, then FINALIZED. Returns the snapshot."""
    # Advance only when strictly later — the hospital clock already starts at
    # 2026-08-01T00:00:00Z and a hold is rejected with ERR_CLOCK_REGRESSION
    # (PRD 2.4). With the default period 2026-07 the initial clock already
    # satisfies the period-closure rule, so the default is a no-op.
    current = get_success_data(api_client.get_hospital(hospital["id"], make_admin_headers()))
    if current["current_utc"] < clock:
        set_clock(hospital["id"], clock)
    res = api_client.create_dot_snapshot(
        create_dot_snapshot_payload(
            hospital["id"], period_label=period_label, patient_days=patient_days
        ),
        make_preventionist_headers(preventionist["id"]),
    )
    snapshot = get_success_data(res)
    res = api_client.finalize_dot_snapshot(
        snapshot["id"], make_preventionist_headers(preventionist["id"])
    )
    return get_success_data(res)


def create_submitted_report(hospital, preventionist, snapshot, period_label="2026-07",
                             report_type="NHSN_AUR"):
    """Draft + submit a regulatory report pinning a FINALIZED snapshot."""
    res = api_client.create_regulatory_report(
        create_regulatory_report_payload(
            hospital["id"], snapshot["id"], period_label=period_label, report_type=report_type
        ),
        make_preventionist_headers(preventionist["id"]),
    )
    report = get_success_data(res)
    res = api_client.submit_regulatory_report(
        report["id"], make_preventionist_headers(preventionist["id"])
    )
    return get_success_data(res)
