"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

Identity threading: Optometrist and Optician are entity_backed:Provider. After a
provider is created, ownership-gated calls use make_optometrist_headers(od_id) /
make_optician_headers(opt_id) with the real Provider.id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_provider_payload,
    create_patient_payload,
    create_encounter_payload,
    create_prescription_payload,
    create_eligibility_payload,
    create_lab_order_payload,
    create_claim_payload,
    create_recall_reminder_payload,
)
from .test_users import (
    TEST_USERS,
    make_optometrist_headers,
    make_optician_headers,
)
from .assertions import find_pool

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Tier 0: clock + primitive registrations
# --------------------------------------------------------------------------- #
def set_clock(iso: str = DEFAULT_CLOCK):
    """Set the simulated server clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, FRONT_DESK))


def create_optometrist(npi: str = "1234567890", full_name: str = "Dr OD") -> dict:
    return get_success_data(api_client.create_provider(
        create_provider_payload(full_name=full_name, role="OPTOMETRIST", npi=npi), FRONT_DESK))


def create_optician(npi: str = "2222222222", full_name: str = "Op Tician") -> dict:
    return get_success_data(api_client.create_provider(
        create_provider_payload(full_name=full_name, role="OPTICIAN", npi=npi), FRONT_DESK))


def create_patient(**overrides) -> dict:
    return get_success_data(api_client.create_patient(
        create_patient_payload(**overrides), FRONT_DESK))


def create_eligibility(patient_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_eligibility(
        create_eligibility_payload(patient_id, **overrides), FRONT_DESK))


def create_open_encounter(patient_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_encounter(
        create_encounter_payload(patient_id, provider_id, **overrides), FRONT_DESK))


# --------------------------------------------------------------------------- #
# Tier 1: clinical building blocks (provider + patient + refracted encounter)
# --------------------------------------------------------------------------- #
def setup_clinic(clock=DEFAULT_CLOCK, with_optician=True,
                 patient_overrides=None, elig=False, elig_overrides=None):
    """Base clinic: clock set, an optometrist (+ optionally optician), a patient,
    and optionally an eligibility. Returns a dict of building blocks.

    Keys: od, opt (or None), pat, od_h, opt_h, elig (or None), elig_v0 (or None).
    """
    set_clock(clock)
    od = create_optometrist()
    opt = create_optician() if with_optician else None
    pat = create_patient(**(patient_overrides or {}))
    elig_obj = None
    elig_v0 = None
    if elig:
        elig_obj = create_eligibility(pat["id"], **(elig_overrides or {}))
        elig_v0 = elig_obj["version"]
    return {
        "od": od,
        "opt": opt,
        "pat": pat,
        "od_h": make_optometrist_headers(od["id"]),
        "opt_h": make_optician_headers(opt["id"]) if opt else None,
        "elig": elig_obj,
        "elig_v0": elig_v0,
    }


def issue_prescription(pat_id: str, encounter_id: str, od_headers: dict, **overrides) -> dict:
    """Optometrist issues an Rx from an OPEN/REFRACTED encounter (PRD §3.3)."""
    return get_success_data(api_client.create_prescription(
        pat_id, create_prescription_payload(encounter_id, **overrides), od_headers))


def setup_active_rx(clock=DEFAULT_CLOCK, with_optician=True, patient_overrides=None,
                    elig=False, elig_overrides=None, rx_overrides=None,
                    encounter_overrides=None):
    """Clinic + an OPEN encounter + one ACTIVE prescription issued from it.

    Returns the clinic dict augmented with: enc, rx.
    """
    ctx = setup_clinic(clock=clock, with_optician=with_optician,
                       patient_overrides=patient_overrides, elig=elig,
                       elig_overrides=elig_overrides)
    enc = create_open_encounter(ctx["pat"]["id"], ctx["od"]["id"], **(encounter_overrides or {}))
    rx = issue_prescription(ctx["pat"]["id"], enc["id"], ctx["od_h"], **(rx_overrides or {}))
    ctx["enc"] = enc
    ctx["rx"] = rx
    return ctx


# --------------------------------------------------------------------------- #
# Tier 2: finalized routine encounters and claims
# --------------------------------------------------------------------------- #
def setup_finalized_routine_encounter(clock=DEFAULT_CLOCK, elig=True,
                                      patient_overrides=None, encounter_overrides=None,
                                      elig_overrides=None, rx_overrides=None):
    """Clinic + finalized ROUTINE_VISION encounter (Rx issued then finalized).

    Returns clinic dict augmented with: enc (FINALIZED), rx.
    """
    ctx = setup_active_rx(clock=clock, with_optician=False, patient_overrides=patient_overrides,
                          elig=elig, elig_overrides=elig_overrides, rx_overrides=rx_overrides,
                          encounter_overrides=encounter_overrides)
    get_success_data(api_client.finalize_encounter(ctx["enc"]["id"], ctx["od_h"]))
    ctx["enc"] = get_success_data(api_client.get_encounter(ctx["enc"]["id"], FRONT_DESK))
    return ctx


def draft_claim(encounter_id: str, eligibility_id=None) -> dict:
    payload = create_claim_payload(encounter_id)
    if eligibility_id is not None:
        payload["eligibility_id"] = eligibility_id
    return get_success_data(api_client.create_claim(payload, BILLER))


def setup_adjudicated_routine_claim(exam_fee=12000, refraction_fee=3000,
                                    exam_copay=2500, materials_allowance=40000):
    """Full chain to an ADJUDICATED ROUTINE claim drawing a VSP eligibility.

    Returns dict: pat, elig, enc, rx, claim (ADJUDICATED), od_h.
    """
    ctx = setup_finalized_routine_encounter(
        elig=True,
        patient_overrides={"plan_carrier": "VSP"},
        elig_overrides={"exam_copay_cents": exam_copay,
                        "materials_allowance_cents": materials_allowance},
        encounter_overrides={"exam_fee_cents": exam_fee, "refraction_fee_cents": refraction_fee},
    )
    claim = draft_claim(ctx["enc"]["id"], eligibility_id=ctx["elig"]["id"])
    claim = get_success_data(api_client.adjudicate_claim(claim["id"], BILLER))
    ctx["claim"] = claim
    return ctx


def setup_adjudicated_medical_claim(exam_fee=18000, refraction_fee=0,
                                    complaint="H40"):
    """Full chain to an ADJUDICATED MEDICAL claim (no eligibility).

    Patient has medical_insurance_on_file true, encounter is MEDICAL_EYE with an
    H-code complaint. Returns dict: pat, enc, rx, claim (ADJUDICATED), od_h.
    """
    ctx = setup_finalized_routine_encounter(
        elig=False,
        patient_overrides={"plan_carrier": "NONE", "medical_insurance_on_file": True},
        encounter_overrides={"encounter_type": "MEDICAL_EYE", "chief_complaint_code": complaint,
                             "exam_fee_cents": exam_fee, "refraction_fee_cents": refraction_fee},
    )
    claim = draft_claim(ctx["enc"]["id"])
    claim = get_success_data(api_client.adjudicate_claim(claim["id"], BILLER))
    ctx["claim"] = claim
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3: lab-order lifecycle shortcuts
# --------------------------------------------------------------------------- #
def place_lab_order(rx_id: str, opt_headers: dict, eligibility_id=None,
                    expected_eligibility_version=None, **overrides) -> dict:
    """Place a lab order (PRD §3.5). Benefit draw when eligibility_id is set."""
    payload = create_lab_order_payload(rx_id, **overrides)
    if eligibility_id is not None:
        payload["eligibility_id"] = eligibility_id
        payload["expected_eligibility_version"] = expected_eligibility_version
    return get_success_data(api_client.create_lab_order(payload, opt_headers))


def setup_placed_benefit_order(materials_allowance=40000, frame=15000, lens=8000,
                               tier="STANDARD"):
    """VSP patient + eligibility + ACTIVE Rx + one PLACED benefit lab order.

    Returns dict: pat, elig, rx, order (PLACED), opt_h, od_h, opt.
    """
    ctx = setup_active_rx(
        with_optician=True,
        patient_overrides={"plan_carrier": "VSP"},
        elig=True,
        elig_overrides={"materials_allowance_cents": materials_allowance},
    )
    order = place_lab_order(
        ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
        expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=frame,
        lens_charge_cents=lens, frame_brand_tier=tier)
    ctx["order"] = order
    return ctx


def setup_selfpay_dispensed_order(clock=DEFAULT_CLOCK, frame=15000, lens=8000):
    """Self-pay (NONE-carrier) EYEGLASS order taken to DISPENSED at the given clock.

    Returns dict: pat, rx, order (DISPENSED), opt_h, od_h, opt.
    """
    ctx = setup_active_rx(clock=clock, with_optician=True,
                          patient_overrides={"plan_carrier": "NONE"})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], frame_charge_cents=frame,
                            lens_charge_cents=lens)
    get_success_data(api_client.send_lab_order_to_lab(order["id"], ctx["opt_h"]))
    order = get_success_data(api_client.dispense_lab_order(
        order["id"], {"dispensing_optician_id": ctx["opt"]["id"]}, ctx["opt_h"]))
    ctx["order"] = order
    return ctx


def run_remake_cycle(order_id: str, opt_headers: dict, opt_id: str, reason: str = "remake"):
    """One full remake cycle: request-remake -> send-to-lab -> dispense.

    Returns the order after dispense.
    """
    get_success_data(api_client.request_lab_order_remake(order_id, {"reason": reason}, opt_headers))
    get_success_data(api_client.send_lab_order_to_lab(order_id, opt_headers))
    return get_success_data(api_client.dispense_lab_order(
        order_id, {"dispensing_optician_id": opt_id}, opt_headers))


def setup_order_after_n_remakes(n: int, clock=DEFAULT_CLOCK):
    """Self-pay DISPENSED order that has completed `n` remake cycles (remake_count == n).

    Returns dict: order (DISPENSED, remake_count==n), opt_h, opt, rx, pat.
    """
    ctx = setup_selfpay_dispensed_order(clock=clock)
    for i in range(n):
        ctx["order"] = run_remake_cycle(ctx["order"]["id"], ctx["opt_h"], ctx["opt"]["id"],
                                        reason=f"r{i + 1}")
    return ctx


def get_materials_pool(eligibility_id: str) -> dict:
    pools = get_success_data(
        api_client.list_eligibility_benefit_pools(eligibility_id, FRONT_DESK))
    return find_pool(pools, "MATERIALS")


def get_exam_pool(eligibility_id: str) -> dict:
    pools = get_success_data(
        api_client.list_eligibility_benefit_pools(eligibility_id, FRONT_DESK))
    return find_pool(pools, "EXAM")
