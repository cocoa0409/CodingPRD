"""Composite setup helpers.

Every helper builds its preconditions from scratch through the endpoints the PRD
declares, because each test starts against an empty database. Setup calls go
through ``get_success_data`` so a broken precondition surfaces as a setup
failure rather than as a confusing assertion later on.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as payloads
from .api_client import api_client
from .test_users import (
    USER_FINANCE_A,
    USER_FINANCE_B,
    USER_PROGRAM,
    USER_VERIFIER,
    make_credit_verifier_headers,
    make_dairy_partner_headers,
    make_finance_controller_headers,
    make_platform_admin_headers,
    make_program_administrator_headers,
    make_pipeline_scheduler_headers,
    make_project_operator_headers,
)

Entity = Dict[str, Any]

ADMIN = make_platform_admin_headers()
OPERATOR = make_project_operator_headers()
SCHEDULER = make_pipeline_scheduler_headers()
PROGRAM = make_program_administrator_headers()
VERIFIER = make_credit_verifier_headers()
FINANCE_A = make_finance_controller_headers(USER_FINANCE_A)
FINANCE_B = make_finance_controller_headers(USER_FINANCE_B)


# ---------------------------------------------------------------------------
# Tier 1: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Entity:
    """Reposition the server logical clock."""
    return get_success_data(api_client.set_clock_to(to_iso8601, ADMIN))


def create_dairy(**overrides) -> Entity:
    return get_success_data(
        api_client.create_dairy(payloads.create_dairy_payload(**overrides), ADMIN)
    )


def create_second_dairy(**overrides) -> Entity:
    defaults = {
        "name": "Rio Seco Dairy",
        "county": "Kings",
        "herd_size": 1800,
        "manure_management_baseline": "SOLID_STORAGE",
        "haul_distance_km": 30.0,
        "annual_nitrogen_budget_kg": 15000.000,
    }
    defaults.update(overrides)
    return create_dairy(**defaults)


def create_facility(**overrides) -> Entity:
    return get_success_data(
        api_client.create_facility(payloads.create_facility_payload(**overrides), ADMIN)
    )


def create_draft_agreement(dairy_id: str, facility_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_agreement(
            payloads.create_agreement_payload(dairy_id, facility_id, **overrides), OPERATOR
        )
    )


def offer_agreement(agreement_id: str, cover_note: str = "August 2026 term sheet") -> Entity:
    return get_success_data(
        api_client.offer_agreement(agreement_id, {"cover_note": cover_note}, OPERATOR)
    )


def sign_agreement(
    agreement_id: str, dairy_id: str, signatory_name: str = "R. Alvarez"
) -> Entity:
    return get_success_data(
        api_client.sign_agreement(
            agreement_id, {"signatory_name": signatory_name}, make_dairy_partner_headers(dairy_id)
        )
    )


def create_active_agreement(dairy_id: str, facility_id: str, **overrides) -> Entity:
    """Draft, offer and sign, so the agreement lands in ACTIVE."""
    agreement = create_draft_agreement(dairy_id, facility_id, **overrides)
    offer_agreement(agreement["id"])
    return sign_agreement(agreement["id"], dairy_id)


def create_offered_agreement(dairy_id: str, facility_id: str, **overrides) -> Entity:
    """Draft and offer, leaving the agreement in PENDING_DAIRY_SIGNATURE."""
    agreement = create_draft_agreement(dairy_id, facility_id, **overrides)
    return offer_agreement(agreement["id"])


def create_interconnect(facility_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_interconnect(
            payloads.create_interconnect_payload(facility_id, **overrides), SCHEDULER
        )
    )


def create_ops_day(facility_id: str, ops_date: str = "2026-08-03") -> Entity:
    return get_success_data(
        api_client.create_ops_day(
            payloads.create_ops_day_payload(facility_id, ops_date=ops_date), OPERATOR
        )
    )


def book_delivery(agreement_id: str, ops_day_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_delivery(
            payloads.create_delivery_payload(agreement_id, ops_day_id, **overrides), OPERATOR
        )
    )


def close_day(ops_day_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.close_ops_day(ops_day_id, payloads.close_ops_day_payload(**overrides), OPERATOR)
    )


def condition_gas(ops_day_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.condition_gas(ops_day_id, payloads.condition_gas_payload(**overrides), OPERATOR)
    )


def record_separation(ops_day_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.record_separation(
            ops_day_id, payloads.record_separation_payload(**overrides), OPERATOR
        )
    )


def create_nomination(interconnect_id: str, ops_day_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_nomination(
            payloads.create_nomination_payload(interconnect_id, ops_day_id, **overrides), SCHEDULER
        )
    )


def confirm_nomination(nomination_id: str, reason: Optional[str] = None) -> Entity:
    payload: Dict[str, Any] = {"decision": "CONFIRM"}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.schedule_decision(nomination_id, payload, SCHEDULER))


def curtail_nomination(
    nomination_id: str, curtailed_mmbtu: float, reason: Optional[str] = None
) -> Entity:
    payload: Dict[str, Any] = {"decision": "CURTAIL", "curtailed_mmbtu": curtailed_mmbtu}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.schedule_decision(nomination_id, payload, SCHEDULER))


def deliver_nomination(nomination_id: str, delivered_mmbtu: float) -> Entity:
    return get_success_data(
        api_client.deliver_nomination(
            nomination_id, {"delivered_mmbtu": delivered_mmbtu}, SCHEDULER
        )
    )


def create_pathway(facility_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_pathway(payloads.create_pathway_payload(facility_id, **overrides), PROGRAM)
    )


def certify_pathway(
    pathway_id: str,
    reference_start_date: str = "2026-08-01",
    reference_end_date: str = "2026-08-31",
) -> Entity:
    return get_success_data(
        api_client.certification_decision(
            pathway_id,
            {
                "decision": "CERTIFY",
                "reference_start_date": reference_start_date,
                "reference_end_date": reference_end_date,
            },
            PROGRAM,
        )
    )


def create_batch(pathway_id: str, facility_id: str, expected_pathway_version: int, **overrides):
    return get_success_data(
        api_client.create_batch(
            payloads.create_batch_payload(
                pathway_id, facility_id, expected_pathway_version, **overrides
            ),
            PROGRAM,
        )
    )


def claim_batch(batch_id: str, claim_note: str = "August claim") -> Entity:
    return get_success_data(api_client.claim_batch(batch_id, {"claim_note": claim_note}, PROGRAM))


def verify_batch(batch_id: str, verifier_user_id: str = USER_VERIFIER) -> Entity:
    return get_success_data(
        api_client.verify_batch(
            batch_id,
            {"verifier_note": "Third-party verification complete"},
            make_credit_verifier_headers(verifier_user_id),
        )
    )


def issue_batch(batch_id: str, issuer_user_id: str = USER_PROGRAM) -> Entity:
    return get_success_data(
        api_client.issue_batch(
            batch_id,
            {"issuance_reference": "REG-2026-08-0001"},
            make_program_administrator_headers(issuer_user_id),
        )
    )


def create_audit(pathway_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.create_audit(payloads.create_audit_payload(pathway_id, **overrides), VERIFIER)
    )


def record_fieldwork(audit_id: str, **overrides) -> Entity:
    return get_success_data(
        api_client.record_fieldwork(audit_id, payloads.fieldwork_payload(**overrides), VERIFIER)
    )


def issue_findings(audit_id: str, narrative: str = "Annual verification findings") -> Entity:
    return get_success_data(
        api_client.issue_findings(audit_id, {"narrative": narrative}, VERIFIER)
    )


def open_remediation(audit_id: str, remediation_plan: str = "Recalibrate flow meters") -> Entity:
    return get_success_data(
        api_client.open_remediation(audit_id, {"remediation_plan": remediation_plan}, OPERATOR)
    )


def plan_nutrient_application(
    dairy_id: str, facility_id: str, ops_day_id: str, **overrides
) -> Entity:
    return get_success_data(
        api_client.create_nutrient_application(
            payloads.create_nutrient_application_payload(
                dairy_id, facility_id, ops_day_id, **overrides
            ),
            OPERATOR,
        )
    )


def apply_nutrient_application(
    application_id: str, applicator_name: str = "Valley Custom Spreading"
) -> Entity:
    return get_success_data(
        api_client.apply_nutrient_application(
            application_id, {"applicator_name": applicator_name}, OPERATOR
        )
    )


def fund_reserve(facility_id: str, amount_cents: int) -> Entity:
    return get_success_data(
        api_client.fund_reserve(facility_id, {"amount_cents": amount_cents}, FINANCE_A)
    )


def override_posture(facility_id: str, dimension: str, justification: str) -> Entity:
    return get_success_data(
        api_client.override_posture(
            facility_id, {"dimension": dimension, "justification": justification}, ADMIN
        )
    )


def read_facility(facility_id: str) -> Entity:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def read_facility_version(facility_id: str) -> int:
    return read_facility(facility_id)["version"]


def read_pathway(pathway_id: str) -> Entity:
    return get_success_data(api_client.get_pathway(pathway_id, PROGRAM))


def read_pathway_version(pathway_id: str) -> int:
    return read_pathway(pathway_id)["version"]


def create_statement(facility_id: str, **overrides) -> Entity:
    """Open a settlement statement, pinning the facility's live version."""
    expected_facility_version = overrides.pop(
        "expected_facility_version", read_facility_version(facility_id)
    )
    return get_success_data(
        api_client.create_statement(
            payloads.create_statement_payload(
                facility_id, expected_facility_version, **overrides
            ),
            FINANCE_A,
        )
    )


def approve_statement(
    statement_id: str,
    approver_user_id: str = USER_FINANCE_A,
    approval_note: str = "August settlement approved",
) -> Entity:
    return get_success_data(
        api_client.approve_statement(
            statement_id,
            {"approval_note": approval_note},
            make_finance_controller_headers(approver_user_id),
        )
    )


def pay_statement(
    statement_id: str,
    payer_user_id: str = USER_FINANCE_B,
    payment_reference: str = "ACH-2026-08-0007",
) -> Entity:
    return get_success_data(
        api_client.pay_statement(
            statement_id,
            {"payment_reference": payment_reference},
            make_finance_controller_headers(payer_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------


def setup_dairy_and_facility(
    dairy_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Entity, Entity]:
    dairy = create_dairy(**(dairy_overrides or {}))
    facility = create_facility(**(facility_overrides or {}))
    return dairy, facility


def setup_plant(
    dairy_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Entity]:
    """One dairy, one facility and one ACTIVE supply agreement between them."""
    dairy, facility = setup_dairy_and_facility(dairy_overrides, facility_overrides)
    agreement = create_active_agreement(
        dairy["id"], facility["id"], **(agreement_overrides or {})
    )
    return {"dairy": dairy, "facility": facility, "agreement": agreement}


def setup_plant_with_interconnect(
    dairy_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    interconnect_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Entity]:
    plant = setup_plant(dairy_overrides, facility_overrides, agreement_overrides)
    plant["interconnect"] = create_interconnect(
        plant["facility"]["id"], **(interconnect_overrides or {})
    )
    return plant


def setup_open_day_with_delivery(
    ops_date: str = "2026-08-03",
    delivery_overrides: Optional[Dict[str, Any]] = None,
    with_interconnect: bool = False,
    **plant_kwargs,
) -> Dict[str, Entity]:
    """Plant plus an OPEN operations day carrying one ACCEPTED load."""
    plant = (
        setup_plant_with_interconnect(**plant_kwargs)
        if with_interconnect
        else setup_plant(**plant_kwargs)
    )
    ops_day = create_ops_day(plant["facility"]["id"], ops_date)
    delivery = book_delivery(
        plant["agreement"]["id"], ops_day["id"], **(delivery_overrides or {})
    )
    plant["ops_day"] = ops_day
    plant["delivery"] = delivery
    return plant


def setup_closed_day(
    ops_date: str = "2026-08-03",
    delivery_overrides: Optional[Dict[str, Any]] = None,
    close_overrides: Optional[Dict[str, Any]] = None,
    with_interconnect: bool = False,
    **plant_kwargs,
) -> Dict[str, Entity]:
    """Plant plus a CLOSED day whose gas dimension sits at RAW."""
    plant = setup_open_day_with_delivery(
        ops_date=ops_date,
        delivery_overrides=delivery_overrides,
        with_interconnect=with_interconnect,
        **plant_kwargs,
    )
    plant["ops_day"] = close_day(plant["ops_day"]["id"], **(close_overrides or {}))
    return plant


def setup_pipeline_spec_day(
    ops_date: str = "2026-08-03",
    delivery_overrides: Optional[Dict[str, Any]] = None,
    close_overrides: Optional[Dict[str, Any]] = None,
    condition_overrides: Optional[Dict[str, Any]] = None,
    **plant_kwargs,
) -> Dict[str, Entity]:
    """Plant with an active interconnect and a day conditioned to PIPELINE_SPEC."""
    plant = setup_closed_day(
        ops_date=ops_date,
        delivery_overrides=delivery_overrides,
        close_overrides=close_overrides,
        with_interconnect=True,
        **plant_kwargs,
    )
    plant["ops_day"] = condition_gas(plant["ops_day"]["id"], **(condition_overrides or {}))
    return plant


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_injected_day(
    ops_date: str = "2026-08-03",
    nominated_mmbtu: float = 120.280,
    delivered_mmbtu: float = 120.280,
    window_start_utc: str = "2026-08-04T06:00:00Z",
    window_end_utc: str = "2026-08-04T18:00:00Z",
    clock_before_delivery: Optional[str] = "2026-08-04T19:00:00Z",
    **kwargs,
) -> Dict[str, Entity]:
    """Conditioned day, nomination confirmed, then energy actually injected."""
    plant = setup_pipeline_spec_day(ops_date=ops_date, **kwargs)
    nomination = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        nominated_mmbtu=nominated_mmbtu,
    )
    nomination = confirm_nomination(nomination["id"])
    if clock_before_delivery is not None:
        set_clock(clock_before_delivery)
    plant["nomination"] = deliver_nomination(nomination["id"], delivered_mmbtu)
    return plant


def setup_certified_pathway(
    reference_start_date: str = "2026-08-01",
    reference_end_date: str = "2026-08-31",
    pathway_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Entity]:
    """Injected day plus a CERTIFIED credit pathway over the same window."""
    plant = setup_injected_day(**kwargs)
    pathway = create_pathway(plant["facility"]["id"], **(pathway_overrides or {}))
    plant["pathway"] = certify_pathway(
        pathway["id"], reference_start_date, reference_end_date
    )
    return plant


def setup_claimed_batch(
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-08-31",
    **kwargs,
) -> Dict[str, Entity]:
    plant = setup_certified_pathway(**kwargs)
    batch = create_batch(
        plant["pathway"]["id"],
        plant["facility"]["id"],
        read_pathway_version(plant["pathway"]["id"]),
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    plant["batch"] = claim_batch(batch["id"])
    return plant


def setup_verified_batch(verifier_user_id: str = USER_VERIFIER, **kwargs) -> Dict[str, Entity]:
    plant = setup_claimed_batch(**kwargs)
    plant["batch"] = verify_batch(plant["batch"]["id"], verifier_user_id)
    return plant


def setup_issued_batch(
    verifier_user_id: str = USER_VERIFIER,
    issuer_user_id: str = USER_PROGRAM,
    **kwargs,
) -> Dict[str, Entity]:
    plant = setup_verified_batch(verifier_user_id=verifier_user_id, **kwargs)
    plant["batch"] = issue_batch(plant["batch"]["id"], issuer_user_id)
    plant["pathway"] = read_pathway(plant["pathway"]["id"])
    return plant


def setup_separated_day(
    separation_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Entity]:
    """Conditioned day whose screw-press run has been recorded."""
    plant = setup_pipeline_spec_day(**kwargs)
    plant["ops_day"] = record_separation(
        plant["ops_day"]["id"], **(separation_overrides or {})
    )
    return plant


def setup_planned_nutrient_application(
    application_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Entity]:
    plant = setup_separated_day(**kwargs)
    plant["application"] = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        **(application_overrides or {}),
    )
    return plant


# ---------------------------------------------------------------------------
# Tier 4: threshold targeting
# ---------------------------------------------------------------------------


def setup_facility_with_funded_reserve(
    amount_cents: int, facility_overrides: Optional[Dict[str, Any]] = None
) -> Entity:
    """Facility whose debt-service reserve already holds ``amount_cents``."""
    facility = create_facility(**(facility_overrides or {}))
    return fund_reserve(facility["id"], amount_cents)


def setup_interconnect_at_curtailment_charges(
    charges: int,
    ops_date: str = "2026-08-03",
    nominated_mmbtu: float = 30.000,
    curtailed_mmbtu: float = 10.000,
    windows: Optional[List[Tuple[str, str]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Conditioned day plus ``charges`` curtailed nominations on one interconnect."""
    plant = setup_pipeline_spec_day(ops_date=ops_date, **kwargs)
    windows = windows or [
        ("2026-08-04T06:00:00Z", "2026-08-04T10:00:00Z"),
        ("2026-08-04T11:00:00Z", "2026-08-04T15:00:00Z"),
        ("2026-08-04T16:00:00Z", "2026-08-04T20:00:00Z"),
        ("2026-08-04T21:00:00Z", "2026-08-05T01:00:00Z"),
    ]
    nominations: List[Entity] = []
    for index in range(charges):
        start, end = windows[index]
        nomination = create_nomination(
            plant["interconnect"]["id"],
            plant["ops_day"]["id"],
            window_start_utc=start,
            window_end_utc=end,
            nominated_mmbtu=nominated_mmbtu,
        )
        nominations.append(curtail_nomination(nomination["id"], curtailed_mmbtu))
    plant["nominations"] = nominations
    plant["windows"] = windows
    return plant


def setup_day_at_hydraulic_headroom(
    already_accepted_tonnes: float,
    committed_tonnes_per_day: float = 400.000,
    ops_date: str = "2026-08-03",
    **plant_kwargs,
) -> Dict[str, Entity]:
    """Open day already carrying ``already_accepted_tonnes`` of net feedstock."""
    agreement_overrides = plant_kwargs.pop("agreement_overrides", {}) or {}
    agreement_overrides.setdefault("committed_tonnes_per_day", committed_tonnes_per_day)
    plant = setup_plant(agreement_overrides=agreement_overrides, **plant_kwargs)
    ops_day = create_ops_day(plant["facility"]["id"], ops_date)
    plant["ops_day"] = ops_day
    plant["priming_delivery"] = book_delivery(
        plant["agreement"]["id"],
        ops_day["id"],
        gross_tonnes=already_accepted_tonnes,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    return plant


# ---------------------------------------------------------------------------
# Tier 5: settlement / terminal state
# ---------------------------------------------------------------------------


def setup_draft_statement(
    gas_revenue_cents: int = 2_010_000,
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-08-31",
    plant: Optional[Dict[str, Entity]] = None,
    **kwargs,
) -> Dict[str, Entity]:
    """Plant with one ACTIVE agreement and a DRAFT settlement statement."""
    plant = plant if plant is not None else setup_plant(**kwargs)
    plant["statement"] = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=gas_revenue_cents,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return plant


def setup_approved_statement(
    approver_user_id: str = USER_FINANCE_A, **kwargs
) -> Dict[str, Entity]:
    plant = setup_draft_statement(**kwargs)
    plant["statement"] = approve_statement(plant["statement"]["id"], approver_user_id)
    return plant


def setup_paid_statement(
    approver_user_id: str = USER_FINANCE_A,
    payer_user_id: str = USER_FINANCE_B,
    payment_reference: str = "ACH-2026-08-0007",
    **kwargs,
) -> Dict[str, Entity]:
    plant = setup_approved_statement(approver_user_id=approver_user_id, **kwargs)
    plant["statement"] = pay_statement(
        plant["statement"]["id"], payer_user_id, payment_reference
    )
    return plant


def setup_separated_plant_with_paid_statement(
    gas_revenue_cents: int = 2_010_000, **kwargs
) -> Dict[str, Entity]:
    """Full month: conditioned day, screw-press run recorded, statement paid."""
    plant = setup_separated_day(**kwargs)
    plant = setup_draft_statement(gas_revenue_cents=gas_revenue_cents, plant=plant)
    plant["statement"] = approve_statement(plant["statement"]["id"])
    plant["statement"] = pay_statement(plant["statement"]["id"])
    return plant


# ---------------------------------------------------------------------------
# Two-dairy plant used by the deeper cascade and allocation scenarios
# ---------------------------------------------------------------------------

DIFFICULTY_DAIRY_ONE = {
    "name": "Vista Verde Dairy",
    "county": "Tulare",
    "herd_size": 3000,
    "manure_management_baseline": "LAGOON",
    "haul_distance_km": 12.0,
    "annual_nitrogen_budget_kg": 18000.000,
}

DIFFICULTY_DAIRY_TWO = {
    "name": "Kings River Dairy",
    "county": "Kings",
    "herd_size": 2200,
    "manure_management_baseline": "SOLID_STORAGE",
    "haul_distance_km": 30.0,
    "annual_nitrogen_budget_kg": 12000.000,
}

DIFFICULTY_AGREEMENT_ONE = {
    "committed_tonnes_per_day": 180.000,
    "minimum_total_solids_pct": 8.0,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "revenue_share_pct": 0.2200,
    "revenue_share_basis": "NET",
    "curtailable": True,
}

DIFFICULTY_AGREEMENT_TWO = {
    "committed_tonnes_per_day": 120.000,
    "minimum_total_solids_pct": 6.5,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "revenue_share_pct": 0.1500,
    "revenue_share_basis": "GROSS",
    "curtailable": False,
}

DIFFICULTY_CLOSE = {
    "avg_digester_temp_c": 38.4,
    "temp_excursion_minutes": 15,
    "vfa_mg_per_l": 2400.0,
    "alkalinity_mg_per_l": 8000.0,
    "raw_biogas_scf": 196000.000,
    "raw_ch4_pct": 62.0,
    "raw_co2_pct": 36.5,
    "raw_h2s_ppm": 1800.0,
    "raw_moisture_lb_per_mmscf": 120.0,
}


def setup_two_dairy_plant(
    facility_overrides: Optional[Dict[str, Any]] = None,
    agreement_one_overrides: Optional[Dict[str, Any]] = None,
    agreement_two_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Entity]:
    """One facility fed by two dairies on two ACTIVE agreements.

    The first agreement commits the larger daily tonnage and is curtailable; the
    second commits less, is paid on gross revenue and is not curtailable.
    """
    facility = create_facility(**(facility_overrides or {}))
    dairy_one = create_dairy(**DIFFICULTY_DAIRY_ONE)
    dairy_two = create_dairy(**DIFFICULTY_DAIRY_TWO)
    terms_one = dict(DIFFICULTY_AGREEMENT_ONE)
    terms_one.update(agreement_one_overrides or {})
    terms_two = dict(DIFFICULTY_AGREEMENT_TWO)
    terms_two.update(agreement_two_overrides or {})
    agreement_one = create_active_agreement(dairy_one["id"], facility["id"], **terms_one)
    agreement_two = create_active_agreement(dairy_two["id"], facility["id"], **terms_two)
    return {
        "facility": facility,
        "dairy_one": dairy_one,
        "dairy_two": dairy_two,
        "agreement_one": agreement_one,
        "agreement_two": agreement_two,
    }


def setup_two_dairy_open_day(
    ops_date: str = "2026-08-03",
    delivery_one_overrides: Optional[Dict[str, Any]] = None,
    delivery_two_overrides: Optional[Dict[str, Any]] = None,
    with_interconnect: bool = True,
    **plant_kwargs,
) -> Dict[str, Entity]:
    """Two-dairy plant with one OPEN day carrying a load from each dairy."""
    plant = setup_two_dairy_plant(**plant_kwargs)
    if with_interconnect:
        plant["interconnect"] = create_interconnect(plant["facility"]["id"])
    ops_day = create_ops_day(plant["facility"]["id"], ops_date)
    load_one = {
        "gross_tonnes": 150.000,
        "tare_tonnes": 0.000,
        "total_solids_pct": 8.0,
        "volatile_solids_pct_of_ts": 82.0,
    }
    load_one.update(delivery_one_overrides or {})
    load_two = {
        "gross_tonnes": 100.000,
        "tare_tonnes": 0.000,
        "total_solids_pct": 7.2,
        "volatile_solids_pct_of_ts": 80.0,
    }
    load_two.update(delivery_two_overrides or {})
    plant["ops_day"] = ops_day
    plant["delivery_one"] = book_delivery(plant["agreement_one"]["id"], ops_day["id"], **load_one)
    plant["delivery_two"] = book_delivery(plant["agreement_two"]["id"], ops_day["id"], **load_two)
    return plant


def setup_two_dairy_pipeline_spec_day(
    close_overrides: Optional[Dict[str, Any]] = None,
    condition_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Entity]:
    plant = setup_two_dairy_open_day(**kwargs)
    close_payload = dict(DIFFICULTY_CLOSE)
    close_payload.update(close_overrides or {})
    plant["ops_day"] = close_day(plant["ops_day"]["id"], **close_payload)
    plant["ops_day"] = condition_gas(plant["ops_day"]["id"], **(condition_overrides or {}))
    return plant


def setup_two_dairy_injected_day(
    nominated_mmbtu: float = 120.280,
    delivered_mmbtu: float = 120.280,
    window_start_utc: str = "2026-08-04T06:00:00Z",
    window_end_utc: str = "2026-08-04T18:00:00Z",
    clock_before_delivery: Optional[str] = "2026-08-04T19:00:00Z",
    **kwargs,
) -> Dict[str, Entity]:
    plant = setup_two_dairy_pipeline_spec_day(**kwargs)
    nomination = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        nominated_mmbtu=nominated_mmbtu,
    )
    nomination = confirm_nomination(nomination["id"])
    if clock_before_delivery is not None:
        set_clock(clock_before_delivery)
    plant["nomination"] = deliver_nomination(nomination["id"], delivered_mmbtu)
    return plant


def setup_two_dairy_issued_batch(
    reference_start_date: str = "2026-08-01",
    reference_end_date: str = "2026-08-31",
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-08-31",
    pathway_overrides: Optional[Dict[str, Any]] = None,
    verifier_user_id: str = USER_VERIFIER,
    issuer_user_id: str = USER_PROGRAM,
    **kwargs,
) -> Dict[str, Entity]:
    """Two-dairy plant carried all the way through to ISSUED credits."""
    plant = setup_two_dairy_injected_day(**kwargs)
    pathway = create_pathway(plant["facility"]["id"], **(pathway_overrides or {}))
    plant["pathway"] = certify_pathway(pathway["id"], reference_start_date, reference_end_date)
    batch = create_batch(
        pathway["id"],
        plant["facility"]["id"],
        read_pathway_version(pathway["id"]),
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    batch = claim_batch(batch["id"])
    batch = verify_batch(batch["id"], verifier_user_id)
    plant["batch"] = issue_batch(batch["id"], issuer_user_id)
    plant["pathway"] = read_pathway(pathway["id"])
    return plant


def setup_two_dairy_statement(
    gas_revenue_cents: int = 1_736_376,
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-08-31",
    **kwargs,
) -> Dict[str, Entity]:
    """Two-dairy plant with issued credits and a DRAFT settlement statement."""
    plant = setup_two_dairy_issued_batch(**kwargs)
    plant["statement"] = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=gas_revenue_cents,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return plant
