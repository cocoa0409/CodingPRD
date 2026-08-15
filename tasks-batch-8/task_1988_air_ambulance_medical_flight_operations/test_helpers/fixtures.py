"""Composite setup helpers for the air-ambulance test suite.

Every fixture builds its preconditions from scratch against an empty database
(the server is restarted before each test) using only PRD-declared endpoints.
Setup calls use the lenient get_success_data validator so failures surface as
clear "Setup failed" assertion errors.

Identity threading: FlightCrew is entity-backed, so weather filing, PCR
create/submit/amend, and crew-member-scoped advance/abort/divert calls use
make_flight_crew_headers(member["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_accept_payload,
    create_aircraft_payload,
    create_base_payload,
    create_bed_reservation_payload,
    create_crew_member_payload,
    create_crew_shift_payload,
    create_document_payload,
    create_ground_leg_payload,
    create_insurance_authorization_payload,
    create_membership_payload,
    create_mission_request_payload,
    create_patient_payload,
    create_pcr_payload,
    create_repatriation_case_payload,
    create_triage_payload,
    create_weather_assessment_payload,
)
from .test_users import TEST_USERS, make_flight_crew_headers, make_qa_reviewer_headers
from .constants import CLOCK_START_ISO

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]
QA = TEST_USERS["qa_reviewer_headers"]

# Standard subscale bundles producing known tiers/scores (PRD §3.2):
#   ALS_SUBSCALES 8/6/5/3: triage 5.8; acceptance 5.8 + 2.0 bonus (fresh onset) = 7.8.
#   BLS_SUBSCALES 2/1/1/0: triage 1.1; acceptance 1.1 + 2.0 bonus = 3.1 (fresh onset)
#   or 1.1 with a stale onset — both below the 4.0 ALS break.
ALS_SUBSCALES = {"cardio": 8, "resp": 6, "neuro": 5, "interv": 3}
BLS_SUBSCALES = {"cardio": 2, "resp": 1, "neuro": 1, "interv": 0}
CCT_SUBSCALES = ALS_SUBSCALES  # with a fresh (<120 min) onset these reach 7.8 -> CCT


def fc(member):
    """FlightCrew headers threaded to the acting member's id."""
    return make_flight_crew_headers(member["id"])


def set_clock(to_iso8601=CLOCK_START_ISO):
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def create_base(**overrides) -> dict:
    return get_success_data(api_client.create_base(create_base_payload(**overrides), OPS), 201)


def create_aircraft(base_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_aircraft(create_aircraft_payload(base_id=base_id, **overrides), OPS), 201
    )


def create_crew_member(base_id, full_name, crew_role) -> dict:
    return get_success_data(
        api_client.create_crew_member(
            create_crew_member_payload(base_id=base_id, full_name=full_name, crew_role=crew_role),
            OPS,
        ),
        201,
    )


def create_patient(**overrides) -> dict:
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), DISP), 201)


def create_membership(patient_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership(create_membership_payload(patient_id=patient_id, **overrides), BILL),
        201,
    )


def create_crew_shift(crew_member_id, start_iso, end_iso, headers=None) -> dict:
    return get_success_data(
        api_client.create_crew_shift(
            create_crew_shift_payload(
                crew_member_id=crew_member_id,
                planned_start_iso=start_iso,
                planned_end_iso=end_iso,
            ),
            headers or OPS,
        ),
        201,
    )


def close_shift(shift_id, headers=None) -> dict:
    return get_success_data(api_client.update_crew_shift(shift_id, {"status": "CLOSED"}, headers or OPS))


def create_mission_request(patient_id, subscales=ALS_SUBSCALES, **overrides) -> dict:
    payload = create_mission_request_payload(
        patient_id=patient_id,
        reported_cardio=subscales["cardio"],
        reported_resp=subscales["resp"],
        reported_neuro=subscales["neuro"],
        reported_interventions=subscales["interv"],
        **overrides,
    )
    return get_success_data(api_client.create_mission_request(payload, DISP), 201)


def triage_request(request_id, subscales=ALS_SUBSCALES, **overrides) -> dict:
    payload = create_triage_payload(
        verified_cardio=subscales["cardio"],
        verified_resp=subscales["resp"],
        verified_neuro=subscales["neuro"],
        verified_interventions=subscales["interv"],
        **overrides,
    )
    return get_success_data(api_client.triage_mission_request(request_id, payload, MED))


def accept_request(request_id, aircraft_id, crew_ids, **overrides) -> dict:
    """crew_ids: list of (crew_member_id, role_in_mission) pairs."""
    crew = [{"crew_member_id": cid, "role_in_mission": role} for cid, role in crew_ids]
    payload = create_accept_payload(aircraft_id=aircraft_id, crew=crew, **overrides)
    return get_success_data(api_client.accept_mission_request(request_id, payload, DISP), 201)


def post_weather(mission_id, mission_version, pilot, **overrides) -> dict:
    payload = create_weather_assessment_payload(
        mission_id=mission_id, expected_mission_version=mission_version, **overrides
    )
    return get_success_data(api_client.create_weather_assessment(payload, fc(pilot)), 201)


def post_go_weather(mission_id, pilot) -> dict:
    """Read the mission's current version, then file a clean GO assessment
    (ROTOR_WING DAY FLAT: ceiling 1000, vis 5.0, wind 10 passes every gate)."""
    mission = get_success_data(api_client.get_mission(mission_id, DISP))
    return post_weather(mission_id, mission["version"], pilot)


def advance_mission(mission_id, to_state, headers=None) -> dict:
    return get_success_data(
        api_client.advance_mission(mission_id, {"to_state": to_state}, headers or DISP)
    )


def abort_mission(mission_id, reason_code="REQUESTER", headers=None) -> dict:
    """Abort (post-launch) or cancel (PLANNING) a mission by reason_code."""
    return get_success_data(
        api_client.abort_mission(mission_id, {"reason_code": reason_code}, headers or DISP)
    )


def create_ground_leg(mission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_ground_leg(create_ground_leg_payload(mission_id=mission_id, **overrides), DISP),
        201,
    )


def advance_ground_leg(leg_id, to_status) -> dict:
    return get_success_data(api_client.update_ground_leg(leg_id, {"status": to_status}, DISP))


def create_bed_reservation(mission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bed_reservation(
            create_bed_reservation_payload(mission_id=mission_id, **overrides), DISP
        ),
        201,
    )


def create_invoice(mission_id) -> dict:
    return get_success_data(api_client.create_invoice({"mission_id": mission_id}, BILL), 201)


def create_insurance_authorization(mission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_authorization(
            create_insurance_authorization_payload(mission_id=mission_id, **overrides), BILL
        ),
        201,
    )


def update_membership_safe(membership_id, status) -> dict:
    return get_success_data(api_client.update_membership(membership_id, {"status": status}, BILL))


def create_pcr(mission_id, author) -> dict:
    return get_success_data(
        api_client.create_patient_care_report(
            create_pcr_payload(mission_id=mission_id, author_crew_id=author["id"]), fc(author)
        ),
        201,
    )


def submit_pcr(pcr_id, author) -> dict:
    return get_success_data(api_client.submit_patient_care_report(pcr_id, fc(author)))


def qa_review(pcr_id, outcome, deficiency_points, reviewer_id="qa-officer-1") -> dict:
    return get_success_data(
        api_client.qa_review_patient_care_report(
            pcr_id,
            {"outcome": outcome, "deficiency_points": deficiency_points},
            make_qa_reviewer_headers(reviewer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2: environment builders
# ---------------------------------------------------------------------------

def setup_base_with_crew(aircraft_class="ROTOR_WING", medical_config="CCT_CAPABLE",
                         extra_roles=()):
    """Base + one tail + PILOT and NURSE crew (+ any extra roles). Returns
    (base, aircraft, roster) where roster maps role -> CrewMember dict."""
    base = create_base()
    aircraft = create_aircraft(
        base["id"], aircraft_class=aircraft_class, medical_config=medical_config
    )
    roster = {
        "PILOT": create_crew_member(base["id"], "Pat Pilot", "PILOT"),
        "NURSE": create_crew_member(base["id"], "Nina Nurse", "NURSE"),
    }
    for i, role in enumerate(extra_roles):
        roster[role] = create_crew_member(base["id"], f"Pam {role} {i}", role)
    return base, aircraft, roster


def crew_pairs(roster, tier="ALS"):
    pairs = [(roster["PILOT"]["id"], "PILOT"), (roster["NURSE"]["id"], "NURSE")]
    if tier == "CCT":
        pairs.append((roster["PARAMEDIC"]["id"], "PARAMEDIC"))
    return pairs


def setup_triaged_request(subscales=ALS_SUBSCALES, onset_iso="2026-07-31T14:00:00Z",
                          transport_class="EMERGENCY_INTERFACILITY",
                          emergency_override=None, patient=None, **request_overrides):
    """Patient + RECEIVED request -> TRIAGED. Returns (patient, request)."""
    set_clock()
    patient = patient or create_patient()
    request = create_mission_request(
        patient["id"], subscales=subscales, onset_iso=onset_iso,
        transport_class=transport_class, **request_overrides,
    )
    triage_kwargs = {}
    if emergency_override is not None:
        triage_kwargs["emergency_override"] = emergency_override
    request = triage_request(request["id"], subscales=subscales, **triage_kwargs)
    return patient, request


def setup_planning_mission(
    subscales=ALS_SUBSCALES,
    tier="ALS",
    medical_config="CCT_CAPABLE",
    aircraft_class="ROTOR_WING",
    onset_iso="2026-07-31T14:00:00Z",
    transport_class="EMERGENCY_INTERFACILITY",
    emergency_override=None,
    patient=None,
    **accept_overrides,
):
    """Full chain to a PLANNING mission: base + tail + crew + patient + TRIAGED
    request -> accept. The logical clock is pinned to its startup default first.
    Returns dict with base, aircraft, roster, patient, request, mission."""
    set_clock()
    base, aircraft, roster = setup_base_with_crew(
        aircraft_class=aircraft_class,
        medical_config=medical_config,
        extra_roles=("PARAMEDIC",) if tier == "CCT" else (),
    )
    patient = patient or create_patient()
    request = create_mission_request(
        patient["id"], subscales=subscales, onset_iso=onset_iso,
        transport_class=transport_class,
        **({"destination_country": "MX"} if transport_class == "INTERNATIONAL_REPATRIATION" else {}),
    )
    triage_kwargs = {}
    if emergency_override is not None:
        triage_kwargs["emergency_override"] = emergency_override
    request = triage_request(request["id"], subscales=subscales, **triage_kwargs)
    mission = accept_request(
        request["id"], aircraft["id"], crew_pairs(roster, tier), **accept_overrides
    )
    return {
        "base": base, "aircraft": aircraft, "roster": roster, "patient": patient,
        "request": request, "mission": mission,
    }


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def advance_mission_through(mission_id, pilot, states, headers=None):
    """Advance the mission through each state in order; returns the last body."""
    body = None
    for to_state in states:
        body = advance_mission(mission_id, to_state, headers=headers or fc(pilot))
    return body


def setup_completed_mission(**kwargs):
    """PLANNING mission flown to COMPLETED (fresh GO assessment, no ground legs).
    Returns the setup dict from setup_planning_mission with the mission body
    refreshed to its COMPLETED state."""
    ctx = setup_planning_mission(**kwargs)
    pilot = ctx["roster"]["PILOT"]
    mission = ctx["mission"]
    post_go_weather(mission["id"], pilot)
    ctx["mission"] = advance_mission_through(
        mission["id"], pilot,
        ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION", "COMPLETED"],
    )
    return ctx


def setup_completed_mission_with_completed_destination_leg(**kwargs):
    """COMPLETED mission whose one DESTINATION leg was walked to COMPLETED
    mid-flight (so the completion gate passes). Returns (ctx, leg)."""
    ctx = setup_planning_mission(**kwargs)
    pilot = ctx["roster"]["PILOT"]
    mission = ctx["mission"]
    leg = create_ground_leg(mission["id"], leg_type="DESTINATION")
    post_go_weather(mission["id"], pilot)
    advance_mission_through(mission["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT"])
    advance_ground_leg(leg["id"], "ENROUTE")
    advance_ground_leg(leg["id"], "AT_BEDSIDE")
    advance_ground_leg(leg["id"], "COMPLETED")
    ctx["mission"] = advance_mission_through(
        mission["id"], pilot, ["AT_DESTINATION", "COMPLETED"]
    )
    return ctx, leg


def setup_finalized_invoice(actual_loaded_miles=0.5, membership=None, **kwargs):
    """COMPLETED mission + invoice + finalize. Returns (ctx, invoice)."""
    ctx = setup_completed_mission(**kwargs)
    invoice = create_invoice(ctx["mission"]["id"])
    invoice = get_success_data(
        api_client.finalize_invoice(
            invoice["id"], {"actual_loaded_miles": actual_loaded_miles}, BILL
        )
    )
    return ctx, invoice


def setup_submitted_invoice(actual_loaded_miles=0.5, qa_reviewer_id="qa-officer-1",
                            **kwargs):
    """COMPLETED mission + FINALIZED invoice + PCR QA_APPROVED + claim SUBMITTED.
    Returns (ctx, invoice, pcr)."""
    ctx, invoice = setup_finalized_invoice(actual_loaded_miles, **kwargs)
    pilot = ctx["roster"]["PILOT"]
    pcr = create_pcr(ctx["mission"]["id"], pilot)
    submit_pcr(pcr["id"], pilot)
    qa_review(pcr["id"], "APPROVED", 0, reviewer_id=qa_reviewer_id)
    invoice = get_success_data(api_client.submit_invoice(invoice["id"], BILL))
    return ctx, invoice, pcr


def setup_member_protected_submitted_invoice(membership_effective_from="2026-08-01",
                                             membership_tier="STANDARD",
                                             completion_clock=None, **kwargs):
    """Full member path: ACTIVE membership for the patient, invoice finalized to
    MEMBER_PROTECTED, PCR approved, claim SUBMITTED. Returns (ctx, invoice, pcr,
    membership).

    completion_clock: when given, the logical clock is advanced to this instant
    before the COMPLETED advance so completed_at lands on a specific date (used
    by membership effective-date boundary tests)."""
    set_clock()
    patient = create_patient(full_name="Megan Member")
    membership = create_membership(
        patient["id"], tier=membership_tier, effective_from=membership_effective_from
    )
    kwargs.setdefault("subscales", BLS_SUBSCALES)
    kwargs.setdefault("tier", "BLS")
    kwargs.setdefault("medical_config", "BLS_CAPABLE")
    ctx = setup_planning_mission(patient=patient, **kwargs)
    pilot = ctx["roster"]["PILOT"]
    if completion_clock is not None:
        set_clock(completion_clock)
    post_go_weather(ctx["mission"]["id"], pilot)
    advance_mission_through(
        ctx["mission"]["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION"]
    )
    ctx["mission"] = advance_mission(ctx["mission"]["id"], "COMPLETED", headers=fc(pilot))
    invoice = create_invoice(ctx["mission"]["id"])
    invoice = get_success_data(
        api_client.finalize_invoice(invoice["id"], {"actual_loaded_miles": 0.5}, BILL)
    )
    pcr = create_pcr(ctx["mission"]["id"], pilot)
    submit_pcr(pcr["id"], pilot)
    qa_review(pcr["id"], "APPROVED", 0, reviewer_id="qa-officer-1")
    invoice = get_success_data(api_client.submit_invoice(invoice["id"], BILL))
    return ctx, invoice, pcr, membership


# ---------------------------------------------------------------------------
# Tier: international repatriation
# ---------------------------------------------------------------------------

def setup_repatriation_mission(with_documents=(), **kwargs):
    """PLANNING INTERNATIONAL_REPATRIATION mission (emergency_override True) with
    a COLLECTING case and the given documents appended. Returns (ctx, case)."""
    patient_kwargs = {"full_name": "Rita Repat", "date_of_birth": "1955-02-20", "weight_kg": 68}
    set_clock()
    patient = create_patient(**patient_kwargs)
    ctx = setup_planning_mission(
        subscales=BLS_SUBSCALES,
        tier="BLS",
        medical_config="CCT_CAPABLE",
        patient=patient,
        transport_class="INTERNATIONAL_REPATRIATION",
        emergency_override=True,
        estimated_loaded_miles=kwargs.pop("estimated_loaded_miles", 300),
        planned_duration_min=kwargs.pop("planned_duration_min", 240),
        **kwargs,
    )
    case = get_success_data(
        api_client.create_repatriation_case(
            create_repatriation_case_payload(mission_id=ctx["mission"]["id"]), DISP
        ),
        201,
    )
    for doc in with_documents:
        get_success_data(api_client.add_repatriation_document(case["id"], doc, DISP), 201)
        case = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
    return ctx, case


def full_document_set(fit_to_fly_issued="2026-07-29T12:00:00Z",
                      passport_expires="2027-01-01T00:00:00Z",
                      visa_expires="2026-12-01T00:00:00Z"):
    """The four PRD-required document entries with configurable validity."""
    return [
        create_document_payload(
            doc_type="PASSPORT", document_number="P123",
            issued_iso="2020-01-01T00:00:00Z", expires_iso=passport_expires,
        ),
        create_document_payload(
            doc_type="VISA", document_number="V456",
            issued_iso="2026-01-01T00:00:00Z", expires_iso=visa_expires,
        ),
        create_document_payload(
            doc_type="FIT_TO_FLY", document_number="F789",
            issued_iso=fit_to_fly_issued, expires_iso=None,
        ),
        create_document_payload(
            doc_type="CUSTOMS_PRECLEARANCE", document_number="C012",
            issued_iso="2026-07-30T00:00:00Z", expires_iso=None,
        ),
    ]
