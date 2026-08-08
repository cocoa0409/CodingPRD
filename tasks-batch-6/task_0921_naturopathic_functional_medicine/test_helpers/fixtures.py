"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints:
the store is empty at the start of every test. Setup calls use the lenient
validator so a broken precondition surfaces as a clear setup failure.

Identity threading: any call whose outcome depends on who is acting uses the
per-instance header builder with the real entity id.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import LAB_PANELS, TEST_DEFAULTS
from .factories import (
    adverse_reaction_payload,
    complete_encounter_payload,
    create_dispensary_product_payload,
    create_dispense_payload,
    create_encounter_payload,
    create_intake_section_payload,
    create_lab_order_payload,
    create_lab_result_payload,
    create_membership_payload,
    create_message_thread_payload,
    create_patient_payload,
    create_practitioner_payload,
    create_product_lot_payload,
    create_protocol_item_payload,
    create_protocol_payload,
    create_referral_payload,
    create_superbill_payload,
    critical_potassium_payload,
    next_email,
    titration_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_nd_headers,
    make_patient_headers,
    make_tech_headers,
)

ADMIN = TEST_USERS["practice_admin_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]

# Attesting these three gives intake_booking_score 65 (25 + 25 + 15).
BOOKING_SECTIONS = ["CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "DIET_LIFESTYLE"]
# Attesting these four gives intake_protocol_score 90 (25 + 25 + 25 + 15).
PROTOCOL_SECTIONS = [
    "CHIEF_COMPLAINT_TIMELINE",
    "SYSTEMS_REVIEW",
    "MEDICATIONS_SUPPLEMENTS",
    "DIET_LIFESTYLE",
]


# --------------------------------------------------------------------------- #
# Tier 1 — primitives
# --------------------------------------------------------------------------- #
def set_clock(api, to_iso8601: str) -> dict:
    """Move the server's logical clock."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def register_practitioner(api, **overrides) -> dict:
    payload = create_practitioner_payload(**overrides)
    return get_success_data(api.create_practitioner(payload, ADMIN))


def register_nd(api, **overrides) -> dict:
    defaults = {
        "full_name": "Dr Nora Vance",
        "credential": "ND",
        "licensed_state_codes": ["OR"],
        "npi": "1234567893",
    }
    defaults.update(overrides)
    return register_practitioner(api, **defaults)


def register_coach(api, **overrides) -> dict:
    defaults = {
        "full_name": "Cam Diaz",
        "credential": "HEALTH_COACH",
        "licensed_state_codes": ["OR"],
        "npi": None,
    }
    defaults.update(overrides)
    return register_practitioner(api, **defaults)


def register_tech(api, **overrides) -> dict:
    defaults = {
        "full_name": "Tess Ortiz",
        "credential": "DISPENSARY_TECH",
        "licensed_state_codes": ["OR"],
        "npi": None,
    }
    defaults.update(overrides)
    return register_practitioner(api, **defaults)


def register_director(api, **overrides) -> dict:
    defaults = {
        "full_name": "Dr Ines Park",
        "credential": "CLINICAL_DIRECTOR",
        "licensed_state_codes": ["OR"],
        "npi": "1987654327",
    }
    defaults.update(overrides)
    return register_practitioner(api, **defaults)


def register_patient(api, primary_practitioner_id: str, **overrides) -> dict:
    payload = create_patient_payload(primary_practitioner_id, **overrides)
    payload.setdefault("email", next_email("pt"))
    return get_success_data(api.create_patient(payload, ADMIN))


def read_patient(api, patient_id: str) -> dict:
    return get_success_data(api.get_patient(patient_id, ADMIN))


def patient_version(api, patient_id: str) -> int:
    return read_patient(api, patient_id)["version"]


def read_protocol(api, protocol_id: str, nd_id: str) -> dict:
    return get_success_data(api.get_protocol(protocol_id, make_nd_headers(nd_id)))


def protocol_version(api, protocol_id: str, nd_id: str) -> int:
    return read_protocol(api, protocol_id, nd_id)["version"]


def read_membership(api, patient_id: str, index: int = 0) -> dict:
    rows = get_success_data(api.list_memberships(patient_id, ADMIN))
    assert len(rows) > index, "Setup failed: no membership on the patient"
    return rows[index]


def membership_version(api, patient_id: str, index: int = 0) -> int:
    return read_membership(api, patient_id, index)["version"]


# --------------------------------------------------------------------------- #
# Tier 2 — intake progression
# --------------------------------------------------------------------------- #
def submit_section(api, patient_id: str, section_type: str, **overrides) -> dict:
    payload = create_intake_section_payload(section_type, **overrides)
    return get_success_data(
        api.create_intake_section(patient_id, payload, make_patient_headers(patient_id))
    )


def attest_section(api, patient_id: str, section_id: str) -> dict:
    return get_success_data(
        api.attest_intake_section(section_id, make_patient_headers(patient_id))
    )


def submit_and_attest(api, patient_id: str, section_type: str) -> dict:
    section = submit_section(api, patient_id, section_type)
    return attest_section(api, patient_id, section["id"])


def attest_sections(api, patient_id: str, section_types) -> dict:
    """Submit and attest each named section. Returns {section_type: section}."""
    return {st: submit_and_attest(api, patient_id, st) for st in section_types}


def setup_booking_ready_patient(api, nd=None, **patient_overrides) -> dict:
    """ND plus a patient whose intake_booking_score is 65 (three attested sections)."""
    nd = nd or register_nd(api)
    patient = register_patient(api, nd["id"], **patient_overrides)
    sections = attest_sections(api, patient["id"], BOOKING_SECTIONS)
    return {"nd": nd, "patient": patient, "sections": sections}


def setup_protocol_ready_patient(api, nd=None, **patient_overrides) -> dict:
    """ND plus a patient whose intake_protocol_score is 90 (four attested sections)."""
    nd = nd or register_nd(api)
    patient = register_patient(api, nd["id"], **patient_overrides)
    sections = attest_sections(api, patient["id"], PROTOCOL_SECTIONS)
    return {"nd": nd, "patient": patient, "sections": sections}


# --------------------------------------------------------------------------- #
# Tier 2 — memberships and the dispensary catalogue
# --------------------------------------------------------------------------- #
def open_membership(api, patient_id: str, tier: str = "CORE", **overrides) -> dict:
    payload = create_membership_payload(patient_id, tier=tier, **overrides)
    return get_success_data(api.create_membership(payload, ADMIN))


def create_product(api, **overrides) -> dict:
    payload = create_dispensary_product_payload(**overrides)
    return get_success_data(api.create_dispensary_product(payload, ADMIN))


def receive_lot(api, product_id: str, **overrides) -> dict:
    payload = create_product_lot_payload(**overrides)
    return get_success_data(api.create_product_lot(product_id, payload, ADMIN))


# --------------------------------------------------------------------------- #
# Tier 3 — protocol lifecycle shortcuts
# --------------------------------------------------------------------------- #
def draft_protocol(api, nd_id: str, patient_id: str, **overrides) -> dict:
    version = overrides.pop("expected_patient_version", None)
    if version is None:
        version = patient_version(api, patient_id)
    payload = create_protocol_payload(patient_id, version, **overrides)
    return get_success_data(api.create_protocol(payload, make_nd_headers(nd_id)))


def add_protocol_item(api, nd_id: str, protocol_id: str, product_id: str, **overrides) -> dict:
    payload = create_protocol_item_payload(product_id, **overrides)
    return get_success_data(
        api.create_protocol_item(protocol_id, payload, make_nd_headers(nd_id))
    )


def issue_protocol(api, nd_id: str, protocol_id: str) -> dict:
    return get_success_data(api.issue_protocol(protocol_id, make_nd_headers(nd_id)))


def activate_protocol(api, nd_id: str, protocol_id: str) -> dict:
    return get_success_data(api.activate_protocol(protocol_id, make_nd_headers(nd_id)))


def setup_active_protocol(
    api,
    with_tech: bool = True,
    with_lot: bool = True,
    product_overrides=None,
    lot_overrides=None,
    item_overrides=None,
    protocol_overrides=None,
    patient_overrides=None,
    membership_tier=None,
    nd=None,
) -> dict:
    """Patient (protocol score 90) + product (+lot) + an ACTIVE protocol with one line.

    Returns nd, tech, patient, product, lot, protocol and item.
    """
    ready = setup_protocol_ready_patient(api, nd=nd, **(patient_overrides or {}))
    nd, patient = ready["nd"], ready["patient"]
    tech = register_tech(api) if with_tech else None
    if membership_tier:
        open_membership(api, patient["id"], tier=membership_tier)
    product = create_product(api, **(product_overrides or {}))
    lot = receive_lot(api, product["id"], **(lot_overrides or {})) if with_lot else None
    protocol = draft_protocol(api, nd["id"], patient["id"], **(protocol_overrides or {}))
    item = add_protocol_item(
        api, nd["id"], protocol["id"], product["id"], **(item_overrides or {})
    )
    issue_protocol(api, nd["id"], protocol["id"])
    protocol = activate_protocol(api, nd["id"], protocol["id"])
    return {
        "nd": nd,
        "tech": tech,
        "patient": patient,
        "sections": ready["sections"],
        "product": product,
        "lot": lot,
        "protocol": protocol,
        "item": item,
    }


def dispense_units(
    api, actor_id: str, protocol_id: str, item_id: str, quantity: int = 1,
    nd_id: str = None, as_role: str = "tech", **overrides
) -> dict:
    """Fill a line, reading the protocol's live version for the concurrency field."""
    version = overrides.pop("expected_protocol_version", None)
    if version is None:
        version = protocol_version(api, protocol_id, nd_id or actor_id)
    payload = create_dispense_payload(item_id, version, quantity=quantity, **overrides)
    headers = make_tech_headers(actor_id) if as_role == "tech" else make_nd_headers(actor_id)
    return get_success_data(api.create_dispense(payload, headers))


def setup_dispensed_line(api, quantity: int = 3, **kwargs) -> dict:
    """An ACTIVE protocol whose single line already has one DISPENSED fill."""
    ctx = setup_active_protocol(api, **kwargs)
    ctx["dispense"] = dispense_units(
        api,
        ctx["tech"]["id"],
        ctx["protocol"]["id"],
        ctx["item"]["id"],
        quantity=quantity,
        nd_id=ctx["nd"]["id"],
    )
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3 — encounters
# --------------------------------------------------------------------------- #
def book_encounter(api, nd_id: str, patient_id: str, practitioner_id: str = None, **overrides) -> dict:
    payload = create_encounter_payload(
        patient_id, practitioner_id or nd_id, **overrides
    )
    return get_success_data(api.create_encounter(payload, make_nd_headers(nd_id)))


def complete_encounter(api, nd_id: str, encounter_id: str, **overrides) -> dict:
    payload = complete_encounter_payload(**overrides)
    return get_success_data(
        api.complete_encounter(encounter_id, payload, make_nd_headers(nd_id))
    )


def setup_completed_encounter(
    api, membership_tier=None, modality: str = "IN_PERSON",
    duration_minutes: int = 60, patient_overrides=None, encounter_overrides=None,
    nd_overrides=None,
) -> dict:
    """A booked-and-completed encounter, ready for a superbill."""
    nd = register_nd(api, **(nd_overrides or {}))
    ready = setup_booking_ready_patient(api, nd=nd, **(patient_overrides or {}))
    patient = ready["patient"]
    membership = (
        open_membership(api, patient["id"], tier=membership_tier)
        if membership_tier
        else None
    )
    encounter = book_encounter(
        api, nd["id"], patient["id"], modality=modality, **(encounter_overrides or {})
    )
    encounter = complete_encounter(
        api, nd["id"], encounter["id"], duration_minutes=duration_minutes,
        service_code="99215", diagnosis_codes=["R53.83"],
    )
    return {
        "nd": nd,
        "patient": patient,
        "membership": membership,
        "encounter": encounter,
    }


def draft_superbill(api, patient_id: str, encounter_id: str) -> dict:
    payload = create_superbill_payload(patient_id, encounter_id)
    return get_success_data(api.create_superbill(payload, BILLING))


def superbill_transition(api, superbill_id: str, action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(
        api.create_superbill_transition(superbill_id, payload, BILLING)
    )


# --------------------------------------------------------------------------- #
# Tier 3 — lab orders and results
# --------------------------------------------------------------------------- #
def order_panel(api, nd_id: str, patient_id: str, **overrides) -> dict:
    payload = create_lab_order_payload(patient_id, **overrides)
    return get_success_data(api.create_lab_order(payload, make_nd_headers(nd_id)))


def collect_panel(api, nd_id: str, lab_order_id: str) -> dict:
    return get_success_data(
        api.collect_lab_order(lab_order_id, make_nd_headers(nd_id))
    )


def setup_collected_panel(api, panel_code: str = "SERUM_METABOLIC", nd=None,
                          patient=None, order_overrides=None) -> dict:
    """An ND, a patient and one collected cash panel."""
    nd = nd or register_nd(api)
    patient = patient or register_patient(api, nd["id"])
    overrides = dict(order_overrides or {})
    overrides.setdefault("panel_code", panel_code)
    order = order_panel(api, nd["id"], patient["id"], **overrides)
    order = collect_panel(api, nd["id"], order["id"])
    return {"nd": nd, "patient": patient, "order": order}


def post_result(api, nd_id: str, lab_order_id: str, **overrides) -> dict:
    payload = create_lab_result_payload(**overrides)
    return get_success_data(
        api.create_lab_result(lab_order_id, payload, make_nd_headers(nd_id))
    )


def post_critical_result(api, nd_id: str, lab_order_id: str, **overrides) -> dict:
    payload = critical_potassium_payload(**overrides)
    return get_success_data(
        api.create_lab_result(lab_order_id, payload, make_nd_headers(nd_id))
    )


def red_flag_referral(api, nd_id: str) -> dict:
    """The RED_FLAG_AUTO referral raised by the escalation cascade."""
    rows = get_success_data(
        api.list_referrals(
            make_nd_headers(nd_id), params={"referral_type": "RED_FLAG_AUTO"}
        )
    )
    assert rows, "Setup failed: no RED_FLAG_AUTO referral was raised"
    return rows[0]


def setup_frozen_by_critical_result(api, **kwargs) -> dict:
    """An ACTIVE protocol whose chart has been frozen by a critical analyte.

    The freeze is arranged LAST so that every gated write used to build the
    fixture ran while the gate was still OPEN.
    """
    ctx = setup_active_protocol(api, **kwargs)
    order = order_panel(api, ctx["nd"]["id"], ctx["patient"]["id"])
    order = collect_panel(api, ctx["nd"]["id"], order["id"])
    result = post_critical_result(api, ctx["nd"]["id"], order["id"])
    ctx["order"] = order
    ctx["result"] = result
    ctx["referral"] = red_flag_referral(api, ctx["nd"]["id"])
    return ctx


def setup_frozen_by_scope_review(api, reason: str = "supervision query", **kwargs) -> dict:
    """An ACTIVE protocol whose chart has been frozen by a scope-of-practice review.

    The director is registered separately from the patient's primary
    practitioner, and the review is opened LAST.
    """
    ctx = setup_active_protocol(api, **kwargs)
    director = register_director(api)
    get_success_data(
        api.open_scope_review(
            ctx["patient"]["id"], {"reason": reason}, make_director_headers(director["id"])
        )
    )
    ctx["director"] = director
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3 — message threads
# --------------------------------------------------------------------------- #
def open_thread(api, patient_id: str, practitioner_id: str, **overrides) -> dict:
    payload = create_message_thread_payload(patient_id, practitioner_id, **overrides)
    return get_success_data(
        api.create_message_thread(payload, make_patient_headers(patient_id))
    )


def post_patient_message(api, patient_id: str, thread_id: str, body: str) -> dict:
    return get_success_data(
        api.create_message(thread_id, {"body": body}, make_patient_headers(patient_id))
    )


def post_clinical_reply(api, nd_id: str, thread_id: str, body: str, clinical_minutes: int) -> dict:
    return get_success_data(
        api.create_message(
            thread_id,
            {"body": body, "clinical_minutes": clinical_minutes},
            make_nd_headers(nd_id),
        )
    )


def setup_thread_at_message_threshold(api, membership_tier=None, **patient_overrides) -> dict:
    """A thread carrying exactly four patient messages and no clinical reply."""
    nd = register_nd(api)
    overrides = {"telehealth_consent": True}
    overrides.update(patient_overrides)
    patient = register_patient(api, nd["id"], **overrides)
    membership = (
        open_membership(api, patient["id"], tier=membership_tier)
        if membership_tier
        else None
    )
    thread = open_thread(api, patient["id"], nd["id"])
    for body in ("photo attached", "now itching", "should I stop the supplement"):
        thread = post_patient_message(api, patient["id"], thread["id"], body)
    return {"nd": nd, "patient": patient, "membership": membership, "thread": thread}


# --------------------------------------------------------------------------- #
# Tier 3 — referrals
# --------------------------------------------------------------------------- #
def raise_routine_referral(api, nd_id: str, patient_id: str, **overrides) -> dict:
    payload = create_referral_payload(patient_id, **overrides)
    return get_success_data(api.create_referral(payload, make_nd_headers(nd_id)))


def referral_transition(api, nd_id: str, referral_id: str, action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(
        api.create_referral_transition(referral_id, payload, make_nd_headers(nd_id))
    )


# --------------------------------------------------------------------------- #
# Tier 4 — accumulation / boundary targeting
# --------------------------------------------------------------------------- #
def setup_patient_at_booking_score(api, nd, attested, submitted_only=()) -> dict:
    """Build a patient whose intake sections land on an exact score."""
    patient = register_patient(api, nd["id"])
    for section_type in attested:
        submit_and_attest(api, patient["id"], section_type)
    for section_type in submitted_only:
        submit_section(api, patient["id"], section_type)
    return read_patient(api, patient["id"])


def setup_titrating_line(api, baseline: int = 28, dose_amount_mg: int = 500,
                         titration_interval_days: int = 14, **kwargs) -> dict:
    """An ACTIVE protocol line ready to take titration decisions."""
    return setup_active_protocol(
        api,
        with_lot=False,
        protocol_overrides={"symptom_score_baseline": baseline, "title": "Adrenal"},
        item_overrides={
            "dose_amount_mg": dose_amount_mg,
            "titration_interval_days": titration_interval_days,
        },
        **kwargs,
    )


def take_titration_decision(api, nd_id: str, item_id: str, current_symptom_score: int) -> dict:
    payload = titration_decision_payload(current_symptom_score)
    return get_success_data(
        api.create_titration_decision(item_id, payload, make_nd_headers(nd_id))
    )


def report_adverse_reaction(api, actor_headers: dict, item_id: str, severity: str,
                            description: str = "palpitations and rash") -> dict:
    payload = adverse_reaction_payload(severity, description=description)
    return get_success_data(api.create_adverse_reaction(item_id, payload, actor_headers))


def panel_catalogue(panel_code: str) -> dict:
    """Fixed catalogue block for a panel code."""
    return LAB_PANELS[panel_code]


DEFAULTS = TEST_DEFAULTS
