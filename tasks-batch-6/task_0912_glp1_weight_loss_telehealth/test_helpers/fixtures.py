"""Composite setup helpers.

Almost every interesting claim in this programme needs a member who has been
screened, seen a clinician and been prescribed — a five-to-nine call preamble.
These helpers encapsulate those chains so tests can concentrate on assertions.

Identity threading matters here: `Patient`, `Provider`, `Coach` and
`PharmacyOperator` are entity-backed roles, so every ownership-gated call below
uses the per-instance header builder with the real row's id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_check_in_payload,
    create_clinician_payload,
    create_coach_payload,
    create_coaching_session_payload,
    create_consult_payload,
    create_patient_payload,
    create_pharmacy_order_payload,
    create_pharmacy_payload,
    create_prescription_payload,
    create_prior_authorization_payload,
    create_screening_payload,
    create_subscription_payload,
    create_supply_lot_payload,
)
from .test_users import (
    billing_admin_headers,
    make_coach_headers,
    make_patient_headers,
    make_pharmacy_operator_headers,
    make_provider_headers,
    platform_admin_headers,
)

BASE_CLOCK = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, platform_admin_headers())
    )


def enroll_patient(**overrides) -> dict:
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), platform_admin_headers())
    )


def register_clinician(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(
            create_clinician_payload(**overrides), platform_admin_headers()
        )
    )


def register_coach(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_coach_payload(**overrides), platform_admin_headers())
    )


def register_pharmacy(**overrides) -> dict:
    return get_success_data(
        api_client.create_pharmacy(
            create_pharmacy_payload(**overrides), platform_admin_headers()
        )
    )


def record_supply_lot(pharmacy_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_supply_lot(
            create_supply_lot_payload(pharmacy_id, **overrides), platform_admin_headers()
        )
    )


def open_screening(patient_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_screening(
            create_screening_payload(patient_id, **overrides),
            make_provider_headers(provider_id),
        )
    )


def submit_screening(screening_id: str, provider_id: str, **body) -> dict:
    return get_success_data(
        api_client.submit_screening(screening_id, body, make_provider_headers(provider_id))
    )


def book_consult(patient_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_consult(
            create_consult_payload(patient_id, provider_id, **overrides),
            make_patient_headers(patient_id),
        )
    )


def close_consult(consult_id: str, provider_id: str, outcome: str, outcome_note=None) -> dict:
    payload = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    return get_success_data(
        api_client.complete_consult(consult_id, payload, make_provider_headers(provider_id))
    )


def read_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, platform_admin_headers()))


def patient_version(patient_id: str) -> int:
    return read_patient(patient_id)["version"]


def read_prescription(prescription_id: str, provider_id: str) -> dict:
    return get_success_data(
        api_client.get_prescription(prescription_id, make_provider_headers(provider_id))
    )


def prescription_version(prescription_id: str, provider_id: str) -> int:
    return read_prescription(prescription_id, provider_id)["version"]


def issue_prescription(
    patient_id: str, consult_id: str, provider_id: str, screening_id: str, **overrides
) -> dict:
    expected = overrides.pop("expected_patient_version", None)
    if expected is None:
        expected = patient_version(patient_id)
    payload = create_prescription_payload(
        patient_id, consult_id, provider_id, screening_id, expected, **overrides
    )
    return get_success_data(
        api_client.create_prescription(payload, make_provider_headers(provider_id))
    )


def due_titration_step(prescription_id: str, provider_id: str) -> dict:
    data = get_success_data(
        api_client.list_titration_steps(
            make_provider_headers(provider_id),
            params={"prescription_id": prescription_id, "status": "DUE"},
        )
    )
    assert data, f"expected a DUE titration rung for prescription {prescription_id}"
    return data[0]


def titration_steps_for(prescription_id: str, provider_id: str) -> list:
    return get_success_data(
        api_client.list_titration_steps(
            make_provider_headers(provider_id), params={"prescription_id": prescription_id}
        )
    )


def place_pharmacy_order(
    prescription_id: str, titration_step_id: str, provider_id: str, **overrides
) -> dict:
    expected = overrides.pop("expected_prescription_version", None)
    if expected is None:
        expected = prescription_version(prescription_id, provider_id)
    payload = create_pharmacy_order_payload(
        prescription_id, titration_step_id, expected, **overrides
    )
    return get_success_data(
        api_client.create_pharmacy_order(payload, make_provider_headers(provider_id))
    )


def reserve_order(order: dict) -> dict:
    return get_success_data(
        api_client.reserve_pharmacy_order(
            order["id"], {}, make_pharmacy_operator_headers(order["pharmacy_id"])
        )
    )


def ship_order(order: dict) -> dict:
    return get_success_data(
        api_client.ship_pharmacy_order(
            order["id"], {}, make_pharmacy_operator_headers(order["pharmacy_id"])
        )
    )


def read_supply_lot(supply_lot_id: str) -> dict:
    return get_success_data(
        api_client.get_supply_lot(supply_lot_id, platform_admin_headers())
    )


def file_prior_authorization(prescription_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prior_authorization(
            create_prior_authorization_payload(prescription_id, **overrides),
            make_provider_headers(provider_id),
        )
    )


def decide_prior_authorization(prior_authorization_id: str, decision: str, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_prior_authorization(
            prior_authorization_id, payload, billing_admin_headers()
        )
    )


def start_subscription(patient_id: str, prescription_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(patient_id, prescription_id, **overrides),
            billing_admin_headers(),
        )
    )


def open_billing_cycle(subscription_id: str) -> dict:
    data = get_success_data(
        api_client.list_billing_cycles(
            billing_admin_headers(),
            params={"subscription_id": subscription_id, "status": "OPEN"},
        )
    )
    assert data, f"expected an OPEN billing cycle for subscription {subscription_id}"
    return data[0]


def read_billing_cycle(billing_cycle_id: str) -> dict:
    return get_success_data(
        api_client.get_billing_cycle(billing_cycle_id, billing_admin_headers())
    )


def read_subscription(subscription_id: str) -> dict:
    return get_success_data(
        api_client.get_subscription(subscription_id, billing_admin_headers())
    )


def invoice_cycle(billing_cycle_id: str) -> dict:
    return get_success_data(
        api_client.invoice_billing_cycle(billing_cycle_id, {}, billing_admin_headers())
    )


def settle_cycle(billing_cycle_id: str, payment_reference=None) -> dict:
    payload = {}
    if payment_reference is not None:
        payload["payment_reference"] = payment_reference
    return get_success_data(
        api_client.settle_billing_cycle(billing_cycle_id, payload, billing_admin_headers())
    )


def file_check_in(patient_id: str, prescription_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_check_in(
            create_check_in_payload(patient_id, prescription_id, **overrides),
            make_patient_headers(patient_id),
        )
    )


def triage_check_in(check_in_id: str, provider_id: str) -> dict:
    return get_success_data(
        api_client.triage_check_in(check_in_id, {}, make_provider_headers(provider_id))
    )


def resolve_check_in(check_in_id: str, provider_id: str) -> dict:
    return get_success_data(
        api_client.resolve_check_in(check_in_id, {}, make_provider_headers(provider_id))
    )


def book_coaching_session(
    patient_id: str, subscription_id: str, coach_provider_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_coaching_session(
            create_coaching_session_payload(subscription_id, coach_provider_id, **overrides),
            make_patient_headers(patient_id),
        )
    )


def complete_coaching_session(session: dict) -> dict:
    return get_success_data(
        api_client.complete_coaching_session(
            session["id"], {}, make_coach_headers(session["coach_provider_id"])
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: an adjudicated member
# ---------------------------------------------------------------------------


def setup_eligible_member(clock: str = BASE_CLOCK, patient=None, screening=None) -> dict:
    """Clock set, member enrolled, clinician registered, screening adjudicated.

    Returns a scenario dict with keys: patient, clinician, screening.
    """
    set_clock(clock)
    clinician = register_clinician()
    member = enroll_patient(**(patient or {}))
    scr = open_screening(member["id"], clinician["id"], **(screening or {}))
    scr = submit_screening(scr["id"], clinician["id"])
    return {"patient": member, "clinician": clinician, "screening": scr}


def setup_prescribing_consult(clock: str = BASE_CLOCK, patient=None, screening=None) -> dict:
    """An eligible member plus a consult closed with outcome PRESCRIBE."""
    scenario = setup_eligible_member(clock=clock, patient=patient, screening=screening)
    consult = book_consult(scenario["patient"]["id"], scenario["clinician"]["id"])
    consult = close_consult(consult["id"], scenario["clinician"]["id"], "PRESCRIBE")
    scenario["consult"] = consult
    return scenario


# ---------------------------------------------------------------------------
# Tier 2: an active prescription with its first titration rung
# ---------------------------------------------------------------------------


def setup_active_prescription(
    clock: str = BASE_CLOCK, patient=None, screening=None, prescription=None
) -> dict:
    """Full chain through to a clinically ACTIVE prescription at dose_level 1.

    Returns keys: patient, clinician, screening, consult, prescription, step.
    """
    scenario = setup_prescribing_consult(clock=clock, patient=patient, screening=screening)
    rx = issue_prescription(
        scenario["patient"]["id"],
        scenario["consult"]["id"],
        scenario["clinician"]["id"],
        scenario["screening"]["id"],
        **(prescription or {}),
    )
    scenario["prescription"] = rx
    scenario["step"] = due_titration_step(rx["id"], scenario["clinician"]["id"])
    return scenario


def setup_prescription_with_stock(
    clock: str = BASE_CLOCK,
    patient=None,
    screening=None,
    prescription=None,
    pharmacy=None,
    lot=None,
) -> dict:
    """An active prescription plus a dispensing pharmacy holding one lot.

    Adds keys: pharmacy, lot.
    """
    set_clock(clock)
    ph = register_pharmacy(**(pharmacy or {}))
    supply = record_supply_lot(ph["id"], **(lot or {}))
    scenario = setup_active_prescription(
        clock=clock, patient=patient, screening=screening, prescription=prescription
    )
    scenario["pharmacy"] = ph
    scenario["lot"] = supply
    return scenario


def setup_routed_order(
    clock: str = BASE_CLOCK,
    patient=None,
    screening=None,
    prescription=None,
    pharmacy=None,
    lot=None,
    order=None,
) -> dict:
    """An active prescription with one pharmacy order sitting in CREATED."""
    scenario = setup_prescription_with_stock(
        clock=clock,
        patient=patient,
        screening=screening,
        prescription=prescription,
        pharmacy=pharmacy,
        lot=lot,
    )
    scenario["order"] = place_pharmacy_order(
        scenario["prescription"]["id"],
        scenario["step"]["id"],
        scenario["clinician"]["id"],
        **(order or {}),
    )
    return scenario


def setup_reserved_order(**kwargs) -> dict:
    """An active prescription with one pharmacy order held on its lot."""
    scenario = setup_routed_order(**kwargs)
    scenario["order"] = reserve_order(scenario["order"])
    return scenario


def setup_shipped_order(**kwargs) -> dict:
    """An active prescription whose fulfilment axis has reached DISPENSED."""
    scenario = setup_reserved_order(**kwargs)
    scenario["order"] = ship_order(scenario["order"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: subscription and billing preambles
# ---------------------------------------------------------------------------


def setup_subscription(
    clock: str = BASE_CLOCK,
    patient=None,
    screening=None,
    prescription=None,
    subscription=None,
) -> dict:
    """An active prescription plus its subscription and first billing cycle.

    Adds keys: subscription, cycle.
    """
    scenario = setup_active_prescription(
        clock=clock, patient=patient, screening=screening, prescription=prescription
    )
    sub = start_subscription(
        scenario["patient"]["id"], scenario["prescription"]["id"], **(subscription or {})
    )
    scenario["subscription"] = sub
    scenario["cycle"] = open_billing_cycle(sub["id"])
    return scenario


def setup_coaching_subscription(
    clock: str = BASE_CLOCK,
    patient=None,
    screening=None,
    prescription=None,
    subscription=None,
) -> dict:
    """A subscription with the coaching add-on enabled plus a registered coach.

    Adds keys: subscription, cycle, coach.
    """
    options = {"coaching_addon_enabled": True}
    options.update(subscription or {})
    set_clock(clock)
    coach = register_coach()
    scenario = setup_subscription(
        clock=clock,
        patient=patient,
        screening=screening,
        prescription=prescription,
        subscription=options,
    )
    scenario["coach"] = coach
    return scenario


def setup_invoiced_cycle(**kwargs) -> dict:
    """A subscription whose first billing cycle has been priced."""
    scenario = setup_subscription(**kwargs)
    scenario["cycle"] = invoice_cycle(scenario["cycle"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: threshold targeting
# ---------------------------------------------------------------------------


def raise_since_dose_change_index(scenario: dict, at_clock: str, nausea: int, vomiting: int,
                                  dehydration: bool = False) -> dict:
    """File one check-in at `at_clock` and triage it, lifting both indices."""
    set_clock(at_clock)
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=nausea,
        vomiting_score=vomiting,
        dehydration_flag=dehydration,
    )
    return triage_check_in(check_in["id"], scenario["clinician"]["id"])


def escalate_to_level(scenario: dict, target_level: int, clocks: list,
                      second_signer_provider_id=None) -> dict:
    """Walk the ladder up to `target_level`, one rung per entry in `clocks`.

    `clocks` supplies the instant at which each escalation is attempted, in
    order. Returns the DUE rung sitting at the target level.
    """
    provider_id = scenario["clinician"]["id"]
    step = scenario["step"]
    for index, moment in enumerate(clocks):
        set_clock(moment)
        payload = {}
        if second_signer_provider_id and (index + 2) >= 4:
            payload["second_signer_provider_id"] = second_signer_provider_id
        get_success_data(
            api_client.escalate_titration_step(
                step["id"], payload, make_provider_headers(provider_id)
            )
        )
        step = due_titration_step(scenario["prescription"]["id"], provider_id)
    assert step["dose_level"] == target_level, (
        f"expected the ladder to reach rung {target_level}, got {step['dose_level']}"
    )
    return step
