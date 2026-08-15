"""Composite setup helpers for the workout pipeline (PRD §3).

Every helper builds its preconditions from scratch through the public API, using
the lenient setup validator so failures surface as clear "Setup step failed"
errors. The standard pipeline landmarks are:

  boarding (clock 2026-05-01) -> INTAKE -> ELIGIBILITY_REVIEW -> MARKETING_PERIOD
  -> [listing 2026-05-01; clock 2026-08-01 -> 92 creditable days]
  -> certify-marketing -> TITLE_REVIEW -> commitment ORDERED -> receive
  (zero liens auto-CLEARS) -> certify-title -> TERMS_NEGOTIATION
  -> draft agreement (vacate 2026-09-01) -> offer -> accept -> AGREEMENT_ACTIVE
  -> schedule HANDOVER (2026-09-01T10:00Z) -> VACATE_PENDING
  -> clock to handover -> report -> submit -> DISBURSEMENT_PENDING
  -> disburse full remaining -> approve (do_1) -> release (do_2)
  -> DIL: RECORDING_PENDING / CFK: COMPLETED
  -> DIL: document waiver -> create+submit+confirm recording -> COMPLETED
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BOARDING_CLOCK_ISO,
    MARKETING_READY_CLOCK_ISO,
    STANDARD_LIST_DATE,
    STANDARD_LIST_PRICE_CENTS,
    STANDARD_VACATE_DATE,
)
from .factories import (
    create_agreement_payload,
    create_appointment_payload,
    create_borrower_payload,
    create_case_payload,
    create_deed_recording_payload,
    create_disbursement_payload,
    create_lien_payload,
    create_lien_release_payload,
    create_listing_payload,
    create_loan_payload,
    create_property_payload,
    create_report_payload,
    create_title_commitment_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_disbursement_officer_headers,
    make_inspector_headers,
    make_legal_counsel_headers,
    make_specialist_headers,
    make_title_officer_headers,
    make_workout_manager_headers,
)

ADMIN = TEST_USERS["servicing_admin_headers"]
SPEC = TEST_USERS["specialist_headers"]
MANAGER = TEST_USERS["workout_manager_headers"]
TITLE = TEST_USERS["title_officer_headers"]
INSP = TEST_USERS["inspector_headers"]
OFFICER_1 = TEST_USERS["disbursement_officer_1_headers"]
OFFICER_2 = TEST_USERS["disbursement_officer_2_headers"]
LEGAL = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def board_loan(loan_number=None, **overrides) -> dict:
    payload = create_loan_payload(**overrides)
    if loan_number is not None:
        payload["loan_number"] = loan_number
    return get_success_data(api_client.create_loan(payload, ADMIN), 201)


def register_borrower(**overrides) -> dict:
    return get_success_data(api_client.create_borrower(create_borrower_payload(**overrides), ADMIN), 201)


def register_property(loan_id, **overrides) -> dict:
    return get_success_data(api_client.create_property(create_property_payload(loan_id, **overrides), ADMIN), 201)


def open_workout_case(loan_id, borrower_id, program_type="DEED_IN_LIEU", specialist_id="spec_1") -> dict:
    payload = create_case_payload(loan_id, borrower_id, program_type=program_type)
    return get_success_data(api_client.create_case(payload, make_specialist_headers(specialist_id)), 201)


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, SPEC))


def get_loan(loan_id) -> dict:
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_agreement(agreement_id) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, SPEC))


def get_title_commitment(commitment_id) -> dict:
    return get_success_data(api_client.get_title_commitment(commitment_id, TITLE))


def get_listing(listing_id) -> dict:
    return get_success_data(api_client.get_listing(listing_id, SPEC))


def get_disbursement(disbursement_id) -> dict:
    return get_success_data(api_client.get_disbursement(disbursement_id, SPEC))


def get_deficiency_waiver(waiver_id) -> dict:
    return get_success_data(api_client.get_deficiency_waiver(waiver_id, LEGAL))


def get_eviction_case(eviction_case_id) -> dict:
    return get_success_data(api_client.get_eviction_case(eviction_case_id, LEGAL))


def list_case_deficiency_waivers(case_id) -> list:
    return get_success_data(api_client.list_case_deficiency_waivers(case_id, LEGAL))


# ---------------------------------------------------------------------------
# Tier 1: case state progression
# ---------------------------------------------------------------------------

def setup_case_at_marketing_period(
    loan_number=None,
    program_type="DEED_IN_LIEU",
    loan_overrides=None,
    borrower_overrides=None,
    property_overrides=None,
    with_listing=True,
    list_date=STANDARD_LIST_DATE,
    list_price_cents=STANDARD_LIST_PRICE_CENTS,
    boarding_clock=BOARDING_CLOCK_ISO,
    specialist_id="spec_1",
) -> dict:
    """Board reference data, open a case, submit it, and PASS eligibility."""
    set_clock(boarding_clock)
    loan = board_loan(loan_number, **(loan_overrides or {}))
    borrower = register_borrower(**(borrower_overrides or {}))
    prop = register_property(loan["id"], **(property_overrides or {}))
    case = open_workout_case(loan["id"], borrower["id"], program_type, specialist_id)
    spec = make_specialist_headers(specialist_id)
    get_success_data(api_client.submit_case(case["id"], spec))
    get_success_data(api_client.evaluate_eligibility(case["id"], {"decision": "PASS"}, spec))
    listing = None
    if with_listing:
        listing = get_success_data(
            api_client.create_listing(
                create_listing_payload(case["id"], list_date=list_date, list_price_cents=list_price_cents),
                spec,
            ),
            201,
        )
    case = get_case(case["id"])
    return {"loan": loan, "borrower": borrower, "property": prop, "case": case, "listing": listing}


def setup_case_at_title_review(marketing_ready_clock=MARKETING_READY_CLOCK_ISO, **kwargs) -> dict:
    """MARKETING_PERIOD + listing -> clock to the ready date -> certify-marketing."""
    bundle = setup_case_at_marketing_period(**kwargs)
    set_clock(marketing_ready_clock)
    get_success_data(api_client.certify_marketing(bundle["case"]["id"], SPEC))
    bundle["case"] = get_case(bundle["case"]["id"])
    return bundle


def setup_case_at_terms_negotiation(vested_owner_name=None, **kwargs) -> dict:
    """TITLE_REVIEW + zero-lien commitment received (auto-CLEARED) -> certify-title."""
    bundle = setup_case_at_title_review(**kwargs)
    case_id = bundle["case"]["id"]
    commitment = get_success_data(
        api_client.create_title_commitment(create_title_commitment_payload(case_id), TITLE), 201
    )
    commitment = get_success_data(
        api_client.receive_title_commitment(
            commitment["id"],
            {"vested_owner_name": vested_owner_name or bundle["borrower"]["full_name"]},
            TITLE,
        )
    )
    get_success_data(api_client.certify_title(case_id, SPEC))
    bundle["title_commitment"] = get_title_commitment(commitment["id"])
    bundle["case"] = get_case(case_id)
    return bundle


# ---------------------------------------------------------------------------
# Tier 2: agreement lifecycle
# ---------------------------------------------------------------------------

def create_draft_agreement(case_id, vacate_date=STANDARD_VACATE_DATE, specialist_id="spec_1") -> dict:
    """Refetch the case version, then draft an agreement under OCC (PRD §2.7)."""
    spec = make_specialist_headers(specialist_id)
    case = get_success_data(api_client.get_case(case_id, spec))
    return get_success_data(
        api_client.create_agreement(
            case_id, create_agreement_payload(case["version"], vacate_date=vacate_date), spec
        ),
        201,
    )


def setup_accepted_agreement(
    bundle, vacate_date=STANDARD_VACATE_DATE, offer_valid_days=10, specialist_id="spec_1"
) -> dict:
    """DRAFT -> OFFERED -> ACCEPTED (borrower acts with its own entity id)."""
    case_id = bundle["case"]["id"]
    spec = make_specialist_headers(specialist_id)
    agreement = create_draft_agreement(case_id, vacate_date, specialist_id)
    get_success_data(api_client.offer_agreement(agreement["id"], {"offer_valid_days": offer_valid_days}, spec))
    agreement = get_success_data(
        api_client.accept_agreement(agreement["id"], make_borrower_headers(bundle["borrower"]["id"]))
    )
    bundle["agreement"] = get_agreement(agreement["id"])
    bundle["case"] = get_case(case_id)
    waivers = list_case_deficiency_waivers(case_id)
    bundle["waiver"] = waivers[0] if waivers else None
    return bundle


def setup_case_at_agreement_active(vacate_date=STANDARD_VACATE_DATE, offer_valid_days=10, **kwargs) -> dict:
    bundle = setup_case_at_terms_negotiation(**kwargs)
    return setup_accepted_agreement(bundle, vacate_date=vacate_date, offer_valid_days=offer_valid_days)


# ---------------------------------------------------------------------------
# Tier 3: handover inspection lifecycle
# ---------------------------------------------------------------------------

def schedule_appointment(
    case_id,
    inspector_id="insp_1",
    appointment_type="HANDOVER",
    scheduled_start="2026-09-01T10:00:00Z",
    scheduled_end="2026-09-01T11:00:00Z",
    specialist_id="spec_1",
) -> dict:
    payload = create_appointment_payload(
        case_id,
        inspector_id=inspector_id,
        appointment_type=appointment_type,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    return get_success_data(
        api_client.create_inspection_appointment(payload, make_specialist_headers(specialist_id)), 201
    )


def submit_inspection_report(
    appointment_id,
    report_overrides=None,
    submit_clock="2026-09-01T10:30:00Z",
    inspector_id="insp_1",
) -> dict:
    """Move the clock to the handover moment, create the draft, submit it."""
    set_clock(submit_clock)
    inspector = make_inspector_headers(inspector_id)
    report = get_success_data(
        api_client.create_inspection_report(appointment_id, create_report_payload(**(report_overrides or {})), inspector),
        201,
    )
    return get_success_data(api_client.submit_inspection_report(report["id"], inspector))


def setup_case_at_disbursement_pending(
    handover_start="2026-09-01T10:00:00Z",
    handover_end="2026-09-01T11:00:00Z",
    submit_clock="2026-09-01T10:30:00Z",
    report_overrides=None,
    inspector_id="insp_1",
    **kwargs,
) -> dict:
    """AGREEMENT_ACTIVE -> schedule HANDOVER -> submit report (passing by default)."""
    bundle = setup_case_at_agreement_active(**kwargs)
    appointment = schedule_appointment(
        bundle["case"]["id"],
        inspector_id=inspector_id,
        appointment_type="HANDOVER",
        scheduled_start=handover_start,
        scheduled_end=handover_end,
    )
    report = submit_inspection_report(appointment["id"], report_overrides, submit_clock, inspector_id)
    bundle["appointment"] = appointment
    bundle["report"] = get_success_data(api_client.get_inspection_report(report["id"], INSP))
    bundle["case"] = get_case(bundle["case"]["id"])
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: disbursement lifecycle
# ---------------------------------------------------------------------------

def create_disbursement(case_id, agreement_id, amount_cents, specialist_id="spec_1") -> dict:
    return get_success_data(
        api_client.create_disbursement(
            case_id,
            create_disbursement_payload(agreement_id, amount_cents),
            make_specialist_headers(specialist_id),
        ),
        201,
    )


def approve_disbursement(disbursement_id, officer_id="do_1") -> dict:
    return get_success_data(
        api_client.approve_disbursement(disbursement_id, make_disbursement_officer_headers(officer_id))
    )


def release_disbursement(disbursement_id, officer_id="do_2") -> dict:
    return get_success_data(
        api_client.release_disbursement(disbursement_id, make_disbursement_officer_headers(officer_id))
    )


def create_approved_disbursement(case_id, agreement_id, amount_cents, specialist_id="spec_1", approver_id="do_1") -> dict:
    disb = create_disbursement(case_id, agreement_id, amount_cents, specialist_id)
    return approve_disbursement(disb["id"], approver_id)


def setup_case_at_recording_pending(releaser_id="do_2", **kwargs) -> dict:
    """DIL case driven through a full-assistance release into RECORDING_PENDING."""
    bundle = setup_case_at_disbursement_pending(**kwargs)
    case = bundle["case"]
    amount = case["remaining_assistance_cents"]
    disb = create_approved_disbursement(case["id"], bundle["agreement"]["id"], amount)
    disb = release_disbursement(disb["id"], releaser_id)
    bundle["disbursement"] = get_disbursement(disb["id"])
    bundle["case"] = get_case(case["id"])
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 5: deed recording / completion / rescission
# ---------------------------------------------------------------------------

def document_case_waiver(bundle, document_reference="DOC-1") -> dict:
    waiver = get_success_data(
        api_client.document_deficiency_waiver(
            bundle["waiver"]["id"], {"document_reference": document_reference}, LEGAL
        )
    )
    bundle["waiver"] = waiver
    return waiver


def setup_case_at_recording_submitted(document_reference="DOC-1", **kwargs) -> dict:
    """RECORDING_PENDING with the waiver DOCUMENTED and a recording SUBMITTED."""
    bundle = setup_case_at_recording_pending(**kwargs)
    document_case_waiver(bundle, document_reference)
    recording = get_success_data(
        api_client.create_deed_recording(
            bundle["case"]["id"], create_deed_recording_payload(county=bundle["property"]["county"]), LEGAL
        ),
        201,
    )
    recording = get_success_data(api_client.submit_deed_recording(recording["id"], LEGAL))
    bundle["recording"] = recording
    return bundle


def setup_completed_dil_case(instrument_number="INST-1", **kwargs) -> dict:
    """Full DIL lifecycle through the deed-recording confirmation cascade."""
    bundle = setup_case_at_recording_submitted(**kwargs)
    recording = get_success_data(
        api_client.confirm_deed_recording(bundle["recording"]["id"], {"instrument_number": instrument_number}, LEGAL)
    )
    bundle["recording"] = recording
    bundle["case"] = get_case(bundle["case"]["id"])
    bundle["loan"] = get_loan(bundle["loan"]["id"])
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    bundle["waiver"] = get_deficiency_waiver(bundle["waiver"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 6: holdover / eviction
# ---------------------------------------------------------------------------

def setup_escalated_holdover(escalation_clock="2026-09-05T00:00:00Z", vacate_date=STANDARD_VACATE_DATE, **kwargs) -> dict:
    """AGREEMENT_ACTIVE case escalated after the grace window -> EvictionCase ESCALATED."""
    bundle = setup_case_at_agreement_active(vacate_date=vacate_date, **kwargs)
    set_clock(escalation_clock)
    eviction = get_success_data(api_client.escalate_holdover(bundle["case"]["id"], MANAGER), 201)
    bundle["eviction_case"] = eviction
    bundle["case"] = get_case(bundle["case"]["id"])
    return bundle


def setup_filed_eviction(court_reference="CV-2026-100", **kwargs) -> dict:
    """Escalated holdover filed in court -> case EVICTION_IN_PROGRESS."""
    bundle = setup_escalated_holdover(**kwargs)
    eviction = get_success_data(
        api_client.file_eviction(bundle["eviction_case"]["id"], {"court_reference": court_reference}, LEGAL)
    )
    bundle["eviction_case"] = eviction
    bundle["case"] = get_case(bundle["case"]["id"])
    bundle["loan"] = get_loan(bundle["loan"]["id"])
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    return bundle
