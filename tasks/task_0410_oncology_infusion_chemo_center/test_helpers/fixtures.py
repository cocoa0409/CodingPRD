"""Composite setup helpers.

These encapsulate the multi-step sequences most test claims require so the test
functions can focus on the trigger + assertion. Each test starts against an
empty database (the runner restarts the server before every test), so every
fixture builds its preconditions from scratch using only PRD-declared endpoints.

All setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: any Nurse chairside action uses make_nurse_headers(nurse_id)
with the real Nurse.id so the server records the correct acting nurse.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_nurse_headers,
    make_prior_auth_coordinator_headers,
)
from . import factories as f

PHARM = TEST_USERS["pharmacist_headers"]
PAC = TEST_USERS["prior_auth_coordinator_headers"]


# -- atomic creators ----------------------------------------------------------

_mrn_seq = [0]
_code_seq = [0]
_label_seq = [0]


def _next_mrn():
    _mrn_seq[0] += 1
    return f"MRN-{_mrn_seq[0]:04d}"


def _next_code():
    _code_seq[0] += 1
    return f"PROTO-{_code_seq[0]:04d}"


def _next_label():
    _label_seq[0] += 1
    return f"CHAIR-{_label_seq[0]:04d}"


def create_patient(**overrides):
    payload = f.create_patient_payload(**overrides)
    payload.setdefault("mrn", _next_mrn())
    return get_success_data(api_client.create_patient(payload, PHARM))


def create_protocol(**overrides):
    payload = f.create_regimen_protocol_payload(**overrides)
    payload.setdefault("code", _next_code())
    return get_success_data(api_client.create_regimen_protocol(payload, PHARM))


def add_order_set_item(protocol_id, **overrides):
    payload = f.create_order_set_item_payload(protocol_id, **overrides)
    return get_success_data(api_client.create_order_set_item(payload, PHARM))


def publish_protocol(protocol_id):
    return get_success_data(api_client.publish_regimen_protocol(protocol_id, PHARM))


def create_chair(**overrides):
    payload = f.create_chair_payload(**overrides)
    payload.setdefault("label", _next_label())
    return get_success_data(api_client.create_chair(payload, PHARM))


def create_nurse(**overrides):
    payload = f.create_nurse_payload(**overrides)
    return get_success_data(api_client.create_nurse(payload, PHARM))


def create_cycle(patient_id, protocol_id, **overrides):
    payload = f.create_treatment_cycle_payload(patient_id, protocol_id, **overrides)
    return get_success_data(api_client.create_treatment_cycle(payload, PHARM))


def activate_cycle(cycle_id):
    return get_success_data(api_client.activate_treatment_cycle(cycle_id, PHARM))


def create_approved_pa(patient_id, drug_name, authorized_units_mg, payer="Acme"):
    """Open a PA and approve it. Returns the APPROVED PriorAuthorization."""
    pa = get_success_data(api_client.create_prior_authorization(
        f.create_prior_authorization_payload(patient_id, drug_name=drug_name, payer=payer), PAC))
    return get_success_data(api_client.decide_prior_authorization(
        pa["id"],
        f.decide_prior_authorization_payload("APPROVE", authorized_units_mg=authorized_units_mg),
        PAC))


# -- Tier 2/3: published protocol + active cycle ------------------------------

def setup_published_protocol_with_item(item_overrides=None, protocol_overrides=None):
    """Create a DRAFT protocol, attach one CHEMO item, publish it.
    Returns (protocol, item)."""
    protocol = create_protocol(**(protocol_overrides or {}))
    item = add_order_set_item(protocol["id"], **(item_overrides or {}))
    protocol = publish_protocol(protocol["id"])
    return protocol, item


def setup_active_cycle(patient_overrides=None, protocol_overrides=None,
                       item_overrides=None):
    """Full preamble to an ACTIVE cycle with one published CHEMO item.

    Returns dict with patient, protocol, item, cycle (post-activation, so
    cycle['version'] is the snapshot-frozen version) and convenience fields.
    """
    patient = create_patient(**(patient_overrides or {}))
    protocol, item = setup_published_protocol_with_item(
        item_overrides=item_overrides, protocol_overrides=protocol_overrides)
    cycle = create_cycle(patient["id"], protocol["id"])
    cycle = activate_cycle(cycle["id"])
    return {
        "patient": patient,
        "protocol": protocol,
        "item": item,
        "cycle": cycle,
    }


def setup_active_cycle_two_items(bsa_item, auc_item,
                                 patient_overrides=None, protocol_overrides=None):
    """ACTIVE cycle with two published CHEMO items (e.g. one BSA + one AUC).
    Returns dict with patient, protocol, item_a, item_b, cycle."""
    patient = create_patient(**(patient_overrides or {}))
    protocol = create_protocol(**(protocol_overrides or {}))
    item_a = add_order_set_item(protocol["id"], **bsa_item)
    item_b = add_order_set_item(protocol["id"], **auc_item)
    protocol = publish_protocol(protocol["id"])
    cycle = create_cycle(patient["id"], protocol["id"])
    cycle = activate_cycle(cycle["id"])
    return {
        "patient": patient,
        "protocol": protocol,
        "item_a": item_a,
        "item_b": item_b,
        "cycle": cycle,
    }


# -- Tier 1: cycle state progression ------------------------------------------

def setup_held_cycle(item_overrides=None):
    """ACTIVE cycle then placed ON_HOLD. Returns dict from setup_active_cycle
    with cycle refreshed to the ON_HOLD version."""
    env = setup_active_cycle(item_overrides=item_overrides)
    env["cycle"] = get_success_data(api_client.hold_treatment_cycle(env["cycle"]["id"], PHARM))
    return env


# -- Tier 3/4: drug-order lifecycle shortcuts ---------------------------------

def create_drug_order(cycle_id, item_id, **overrides):
    payload = f.create_drug_order_payload(cycle_id, item_id, **overrides)
    return get_success_data(api_client.create_drug_order(payload, PHARM))


def prepare_order(order_id, nurse_id):
    return get_success_data(api_client.prepare_drug_order(order_id, make_nurse_headers(nurse_id)))


def verify_order(order_id, nurse_id, recomputed_dose_mg):
    return get_success_data(api_client.verify_drug_order(
        order_id, f.verify_drug_order_payload(recomputed_dose_mg), make_nurse_headers(nurse_id)))


def setup_prepared_order(item_overrides=None, certified_preparer=True):
    """ACTIVE cycle with one drug order PREPARED by nurse n1.

    Returns dict: cycle, item, order (post-prepare), n1 (preparer nurse id),
    plus the full setup_active_cycle env keys.
    """
    env = setup_active_cycle(item_overrides=item_overrides)
    n1 = create_nurse(full_name="N1", is_chemo_certified=certified_preparer)
    order = create_drug_order(env["cycle"]["id"], env["item"]["id"])
    order = prepare_order(order["id"], n1["id"])
    env["order"] = order
    env["n1"] = n1
    return env


def setup_verified_order_with_pa(authorized_units_mg, dose_drug="SpecialtyX",
                                 target_auc=5, vial_size_mg=150):
    """ACTIVE cycle with one AUC CHEMO order (525 mg at gfr 80) linked to an
    APPROVED PA, walked through PREPARE + VERIFY to VERIFIED.

    Returns dict: patient, protocol, item, cycle, pa, order (VERIFIED),
    na (preparer), nb (verifier). The order is verified by nb so administer
    can also be called by nb.
    """
    patient = create_patient()
    na = create_nurse(full_name="Na", is_chemo_certified=True)
    nb = create_nurse(full_name="Nb", is_chemo_certified=True)
    pa = create_approved_pa(patient["id"], dose_drug, authorized_units_mg)
    protocol = create_protocol()
    item = add_order_set_item(protocol["id"], drug_name=dose_drug, role="CHEMO",
                              dosing_method="AUC", target_auc=target_auc,
                              vial_size_mg=vial_size_mg, flat_dose_mg=None)
    # remove FLAT default's flat_dose_mg, AUC item only needs target_auc
    protocol = publish_protocol(protocol["id"])
    cycle = create_cycle(patient["id"], protocol["id"])
    cycle = activate_cycle(cycle["id"])
    order = create_drug_order(cycle["id"], item["id"], prior_authorization_id=pa["id"])
    order = prepare_order(order["id"], na["id"])
    order = verify_order(order["id"], nb["id"], order["ordered_dose_mg"])
    return {
        "patient": patient,
        "protocol": protocol,
        "item": item,
        "cycle": cycle,
        "pa": pa,
        "order": order,
        "na": na,
        "nb": nb,
    }


# -- Tier 2: scheduling setup helpers -----------------------------------------

def book_appointment(cycle_id, chair_id, nurse_id, start_at, end_at, acuity,
                     expected_version, headers=None):
    payload = f.create_infusion_appointment_payload(
        cycle_id, chair_id, nurse_id, start_at, end_at, acuity, expected_version)
    return get_success_data(api_client.create_infusion_appointment(payload, headers or PHARM))


def setup_active_cycle_with_chair_and_nurse(nurse_overrides=None, chair_overrides=None,
                                            item_overrides=None):
    """ACTIVE cycle plus a chair and a nurse ready for appointment booking.
    Returns dict: patient, protocol, item, cycle, chair, nurse."""
    env = setup_active_cycle(item_overrides=item_overrides)
    env["chair"] = create_chair(**(chair_overrides or {}))
    env["nurse"] = create_nurse(**(nurse_overrides or {"full_name": "Booking Nurse",
                                                       "is_chemo_certified": True,
                                                       "max_acuity_load": 6}))
    return env
