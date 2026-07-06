"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a fitting Physician entity, every ownership/segregation-
gated call (start-fabrication, complete-milestone, deliver, adjustments, repairs) uses
make_practitioner_headers(fit_id); every sign/void uses make_physician_headers(rx_phys_id).
The DB is empty before every test, so each helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patient_payload, create_medicare_patient_payload, create_physician_payload,
    create_supplier_payload, create_prescription_payload, create_device_order_payload,
    create_claim_line_payload, create_milestone_payload, create_assess_payload,
    create_repair_request_payload, deliver_payload, clock_payload,
)
from .test_users import TEST_USERS, make_physician_headers, make_practitioner_headers
from .constants import TEST_CLOCK


# ─── Low-level building blocks ───────────────────────────────────────

def set_clock(iso: str):
    """Set the logical clock (ComplianceOfficer)."""
    return get_success_data(api_client.set_clock(clock_payload(iso), TEST_USERS["compliance_headers"]))


def create_physician(pecos: bool = True, npi: str = "1111111111", name: str = "Dr Rx"):
    return get_success_data(api_client.create_physician(
        create_physician_payload(full_name=name, npi=npi, pecos_enrolled=pecos),
        TEST_USERS["compliance_headers"]))


def create_supplier(**overrides):
    return get_success_data(api_client.create_supplier(
        create_supplier_payload(**overrides), TEST_USERS["compliance_headers"]))


def create_patient(medicare: bool = False, **overrides):
    payload = (create_medicare_patient_payload(**overrides) if medicare
               else create_patient_payload(**overrides))
    return get_success_data(api_client.create_patient(payload, TEST_USERS["billing_headers"]))


def create_signed_prescription(patient_id, physician_id, device_category, diagnosis,
                               face_to_face_date="2026-05-20", sign=True):
    rx = get_success_data(api_client.create_prescription(
        create_prescription_payload(
            patient_id, physician_id, device_category=device_category,
            primary_diagnosis_code=diagnosis, face_to_face_date=face_to_face_date),
        make_physician_headers(physician_id)))
    if sign:
        rx = get_success_data(api_client.sign_prescription(
            rx["id"], make_physician_headers(physician_id)))
    return rx


# ─── Tier 1/2: Common cast + order at INTAKE ─────────────────────────

def setup_cast(clock=TEST_CLOCK, rx_pecos=True, supplier_overrides=None, medicare=False,
               patient_overrides=None):
    """Set clock + create prescribing physician, fitting practitioner, supplier, patient.

    Returns a dict: {rx_phys_id, fit_id, sup_id, pat_id, supplier, patient}.
    """
    set_clock(clock)
    rx_phys = create_physician(pecos=rx_pecos, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier(**(supplier_overrides or {}))
    patient = create_patient(medicare=medicare, **(patient_overrides or {}))
    return {
        "rx_phys_id": rx_phys["id"],
        "fit_id": fit["id"],
        "sup_id": supplier["id"],
        "pat_id": patient["id"],
        "supplier": supplier,
        "patient": patient,
    }


def setup_order_at_intake(clock=TEST_CLOCK, device_category="LOWER_EXTREMITY_ORTHOSIS",
                          diagnosis="M21.6X1", medicare=False, rx_pecos=True,
                          supplier_overrides=None, face_to_face_date="2026-05-20",
                          patient_overrides=None):
    """Full chain to a DeviceOrder at INTAKE.

    Returns dict adding {rx_id, ord_id, order} to the setup_cast keys.
    """
    cast = setup_cast(clock=clock, rx_pecos=rx_pecos, supplier_overrides=supplier_overrides,
                      medicare=medicare, patient_overrides=patient_overrides)
    rx = create_signed_prescription(
        cast["pat_id"], cast["rx_phys_id"], device_category, diagnosis,
        face_to_face_date=face_to_face_date)
    order = get_success_data(api_client.create_device_order(
        create_device_order_payload(rx["id"], cast["sup_id"], cast["fit_id"]),
        TEST_USERS["billing_headers"]))
    cast["rx_id"] = rx["id"]
    cast["ord_id"] = order["id"]
    cast["order"] = order
    return cast


def add_milestone(order_id, fit_id, step="ASSEMBLY", weight=1):
    return get_success_data(api_client.create_milestone(
        order_id, create_milestone_payload(step=step, weight=weight),
        make_practitioner_headers(fit_id)))


# ─── Tier 3: Order driven to READY_FOR_FITTING (no-auth path) ────────

def setup_order_ready_no_auth(clock=TEST_CLOCK, device_category="LOWER_EXTREMITY_ORTHOSIS",
                              diagnosis="M21.6X1", supplier_overrides=None,
                              same_practitioner_as_physician=False):
    """No-auth (COMMERCIAL) order driven INTAKE -> FABRICATION -> READY_FOR_FITTING
    with one ASSEMBLY milestone. Returns setup dict with current order version under
    'ord_v' (the live version after the last milestone completion bumped it).

    If same_practitioner_as_physician, the prescribing physician also serves as the
    fitting practitioner (for segregation-of-duties tests).
    """
    if same_practitioner_as_physician:
        set_clock(clock)
        solo = create_physician(pecos=True, npi="1111111111", name="Dr Solo")
        supplier = create_supplier(**(supplier_overrides or {}))
        patient = create_patient(medicare=False)
        rx = create_signed_prescription(patient["id"], solo["id"], device_category, diagnosis)
        order = get_success_data(api_client.create_device_order(
            create_device_order_payload(rx["id"], supplier["id"], solo["id"]),
            TEST_USERS["billing_headers"]))
        cast = {"rx_phys_id": solo["id"], "fit_id": solo["id"], "sup_id": supplier["id"],
                "pat_id": patient["id"], "supplier": supplier, "patient": patient,
                "rx_id": rx["id"], "ord_id": order["id"], "order": order}
    else:
        cast = setup_order_at_intake(clock=clock, device_category=device_category,
                                     diagnosis=diagnosis, supplier_overrides=supplier_overrides)

    ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
    api_client.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    api_client.complete_milestone(ms["id"], make_practitioner_headers(cast["fit_id"]))
    live = get_success_data(api_client.get_device_order(
        cast["ord_id"], make_practitioner_headers(cast["fit_id"])))
    cast["ms_id"] = ms["id"]
    cast["ord_v"] = live["version"]
    cast["order"] = live
    return cast


def setup_order_ready_medicare_approved(clock=TEST_CLOCK, supplier_overrides=None):
    """Medicare LOWER_LIMB_PROSTHETIC order with APPROVED auth, driven to READY_FOR_FITTING.

    Sequence: order INTAKE -> add milestone -> submit-auth -> approve auth
    (cascades AUTH_PENDING -> FABRICATION) -> complete milestone
    (cascades FABRICATION -> READY_FOR_FITTING). Returns setup dict with live 'ord_v',
    'pa_id', 'ms_id'.
    """
    cast = setup_order_at_intake(clock=clock, device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True,
                                 supplier_overrides=supplier_overrides)
    ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
    pa = get_success_data(api_client.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]))
    api_client.approve_prior_auth(pa["id"], TEST_USERS["compliance_headers"])
    api_client.complete_milestone(ms["id"], make_practitioner_headers(cast["fit_id"]))
    live = get_success_data(api_client.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]))
    cast["ms_id"] = ms["id"]
    cast["pa_id"] = pa["id"]
    cast["ord_v"] = live["version"]
    cast["order"] = live
    return cast


def deliver(order_id, fit_id, expected_version):
    """Deliver an order at the current version (OCC-guarded)."""
    return get_success_data(api_client.deliver_order(
        order_id, deliver_payload(expected_version), make_practitioner_headers(fit_id)))


# ─── Tier 3/4: Delivered orders + claim lines ────────────────────────

def setup_delivered_no_auth(clock=TEST_CLOCK, device_category="LOWER_EXTREMITY_ORTHOSIS",
                            diagnosis="M21.6X1", supplier_overrides=None):
    """A COMMERCIAL no-auth order driven all the way to DELIVERED. Returns setup dict
    with the delivered order under 'order' and live version under 'ord_v'."""
    cast = setup_order_ready_no_auth(clock=clock, device_category=device_category,
                                     diagnosis=diagnosis, supplier_overrides=supplier_overrides)
    delivered = deliver(cast["ord_id"], cast["fit_id"], cast["ord_v"])
    cast["order"] = delivered
    cast["ord_v"] = delivered["version"]
    return cast


def setup_delivered_medicare(clock=TEST_CLOCK, supplier_overrides=None):
    """A Medicare LOWER_LIMB_PROSTHETIC order with APPROVED auth, driven to DELIVERED."""
    cast = setup_order_ready_medicare_approved(clock=clock, supplier_overrides=supplier_overrides)
    delivered = deliver(cast["ord_id"], cast["fit_id"], cast["ord_v"])
    cast["order"] = delivered
    cast["ord_v"] = delivered["version"]
    return cast


def create_claim_line(order_id, l_code="L1960", modifier="NONE", billed_units=1,
                      fee_schedule_cents=30000):
    return get_success_data(api_client.create_claim_line(
        create_claim_line_payload(order_id, l_code=l_code, modifier=modifier,
                                  billed_units=billed_units,
                                  fee_schedule_cents=fee_schedule_cents),
        TEST_USERS["billing_headers"]))


def setup_delivered_no_auth_with_lines(line_specs, clock=TEST_CLOCK):
    """Create a no-auth COMMERCIAL order, attach claim lines (created DRAFT before
    delivery), then deliver (which submits all DRAFT lines).

    line_specs: list of dicts, each with keys among {l_code, modifier, billed_units,
    fee_schedule_cents}. Returns (cast_dict, [submitted_claim_line, ...]).
    """
    cast = setup_order_at_intake(clock=clock, device_category="LOWER_EXTREMITY_ORTHOSIS",
                                 diagnosis="M21.6X1")
    lines = []
    for spec in line_specs:
        lines.append(create_claim_line(cast["ord_id"], **spec))
    ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
    api_client.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    api_client.complete_milestone(ms["id"], make_practitioner_headers(cast["fit_id"]))
    live = get_success_data(api_client.get_device_order(
        cast["ord_id"], make_practitioner_headers(cast["fit_id"])))
    deliver(cast["ord_id"], cast["fit_id"], live["version"])
    # Re-fetch the now-SUBMITTED claim lines.
    refreshed = [get_success_data(api_client.get_claim_line(cl["id"], TEST_USERS["billing_headers"]))
                 for cl in lines]
    cast["ms_id"] = ms["id"]
    return cast, refreshed


def setup_denied_appealed_line(clock=TEST_CLOCK, fee_schedule_cents=30000):
    """Delivered COMMERCIAL orthosis order with one claim line (NONE, fee x1) that has
    been DENIED then APPEALED. Returns (cast_dict, claim_line)."""
    cast, lines = setup_delivered_no_auth_with_lines(
        [{"l_code": "L1960", "modifier": "NONE", "billed_units": 1,
          "fee_schedule_cents": fee_schedule_cents}], clock=clock)
    cl = lines[0]
    api_client.deny_claim_line(cl["id"], TEST_USERS["billing_headers"])
    api_client.appeal_claim_line(cl["id"], TEST_USERS["compliance_headers"])
    refreshed = get_success_data(api_client.get_claim_line(cl["id"], TEST_USERS["billing_headers"]))
    return cast, refreshed


# ─── Prior-auth lifecycle helpers ────────────────────────────────────

def setup_order_auth_pending(clock=TEST_CLOCK, supplier_overrides=None, add_milestone_first=False):
    """Medicare LOWER_LIMB_PROSTHETIC order at AUTH_PENDING with a SUBMITTED PriorAuth.
    Returns setup dict with 'pa_id'. If add_milestone_first, one ASSEMBLY milestone is
    added before submit-auth (so approval can cascade to FABRICATION)."""
    cast = setup_order_at_intake(clock=clock, device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True,
                                 supplier_overrides=supplier_overrides)
    if add_milestone_first:
        ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
        cast["ms_id"] = ms["id"]
    pa = get_success_data(api_client.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]))
    cast["pa_id"] = pa["id"]
    cast["prior_auth"] = pa
    return cast


def setup_pended_prior_auth(clock=TEST_CLOCK):
    """Medicare order with a PriorAuth PENDED once. Returns (cast_dict, pended_pa)."""
    cast = setup_order_auth_pending(clock=clock)
    pa = get_success_data(api_client.pend_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]))
    return cast, pa


# ─── Delivered order + reported repair ───────────────────────────────

def setup_repair_reported(delivered_clock=TEST_CLOCK, report_clock="2027-09-01T00:00:00Z",
                          supplier_overrides=None):
    """A delivered COMMERCIAL orthosis order, clock advanced, then a RepairRequest reported.
    Returns (cast_dict, repair_request). delivered_clock is when delivery happens;
    report_clock is advanced before reporting the repair."""
    cast = setup_delivered_no_auth(clock=delivered_clock, supplier_overrides=supplier_overrides)
    set_clock(report_clock)
    rr = get_success_data(api_client.create_repair_request(
        create_repair_request_payload(cast["ord_id"]),
        make_practitioner_headers(cast["fit_id"])))
    cast["rr_id"] = rr["id"]
    return cast, rr


def assess_repair(rr_id, fit_id, parts_cents=0):
    return get_success_data(api_client.assess_repair(
        rr_id, create_assess_payload(parts_cents=parts_cents),
        make_practitioner_headers(fit_id)))
