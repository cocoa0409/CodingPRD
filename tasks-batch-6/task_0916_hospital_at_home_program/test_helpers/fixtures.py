"""Composite setup helpers.

Every helper here builds its state exclusively through the PRD's declared
endpoints, starting from an empty database.  Nothing is carried across tests.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_instant
from .factories import (
    create_bed_reservation_payload,
    create_billing_claim_payload,
    create_delivery_order_payload,
    create_device_component_payload,
    create_device_kit_payload,
    create_eligibility_assessment_payload,
    create_episode_payload,
    create_escalation_event_payload,
    create_inpatient_unit_payload,
    create_meal_plan_payload,
    create_monitoring_lapse_payload,
    create_patient_payload,
    create_referral_payload,
    create_visit_payload,
    deploy_kit_payload,
)
from .test_users import (
    ADMITTING_PHYSICIAN,
    BILLING_ANALYST,
    FIELD_NURSE,
    LOGISTICS_COORDINATOR,
    PROGRAM_ADMIN,
    make_admitting_physician_headers,
    make_community_paramedic_headers,
    make_field_nurse_headers,
    make_pharmacy_authorizer_headers,
)

DEFAULT_CLOCK = "2026-06-01T08:00:00Z"
DEFAULT_SERVICE_DATE = "2026-06-01"
DEFAULT_EVAL_AT = "2026-06-01T06:00:00Z"


# ─── Time helpers ──────────────────────────────────────────────────────────

def iso_utc(dt: datetime) -> str:
    """Render an aware datetime as an ISO 8601 UTC instant."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_minutes(instant: str, minutes: int) -> str:
    return iso_utc(parse_instant(instant) + timedelta(minutes=minutes))


def date_part(instant: str) -> str:
    return parse_instant(instant).strftime("%Y-%m-%d")


# ─── Tier 0: single-call primitives ────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Drive the program's logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, PROGRAM_ADMIN))


def register_patient(**overrides: Any) -> dict:
    payload = create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(payload, ADMITTING_PHYSICIAN))


def file_referral(patient_id: str, **overrides: Any) -> dict:
    payload = create_referral_payload(patient_id, **overrides)
    return get_success_data(api_client.create_referral(payload, ADMITTING_PHYSICIAN))


def record_assessment(
    referral_id: str, in_person_eval_at: str = DEFAULT_EVAL_AT, **overrides: Any
) -> dict:
    payload = create_eligibility_assessment_payload(
        referral_id, in_person_eval_at, **overrides
    )
    return get_success_data(
        api_client.create_eligibility_assessment(payload, ADMITTING_PHYSICIAN)
    )


def mark_eligible(referral_id: str) -> dict:
    return get_success_data(
        api_client.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN)
    )


def admit(patient_id: str, referral_id: str, program_track: str = "CMS_WAIVER") -> dict:
    payload = create_episode_payload(
        patient_id, referral_id, program_track=program_track
    )
    return get_success_data(api_client.create_episode(payload, ADMITTING_PHYSICIAN))


def read_episode(episode_id: str) -> dict:
    return get_success_data(api_client.get_episode(episode_id, PROGRAM_ADMIN))


def read_visit_list(episode_id: str, params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_episode_visits(episode_id, PROGRAM_ADMIN, params=params)
    )


def register_kit(**overrides: Any) -> dict:
    payload = create_device_kit_payload(**overrides)
    return get_success_data(api_client.create_device_kit(payload, PROGRAM_ADMIN))


def add_component(kit_id: str, **overrides: Any) -> dict:
    payload = create_device_component_payload(**overrides)
    return get_success_data(
        api_client.create_device_component(kit_id, payload, PROGRAM_ADMIN)
    )


def deploy_kit(kit_id: str, episode_id: str, expected_kit_version: int) -> dict:
    payload = deploy_kit_payload(episode_id, expected_kit_version)
    return get_success_data(api_client.deploy_device_kit(kit_id, payload, FIELD_NURSE))


def read_kit(kit_id: str) -> dict:
    return get_success_data(api_client.get_device_kit(kit_id, PROGRAM_ADMIN))


def read_kit_census() -> dict:
    return get_success_data(api_client.get_device_kit_census(PROGRAM_ADMIN))


def reconcile_component(component_id: str, outcome: str, user_id: str = "rn-1") -> dict:
    return get_success_data(
        api_client.reconcile_device_component(
            component_id, {"outcome": outcome}, make_field_nurse_headers(user_id)
        )
    )


def read_components(kit_id: str, params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_device_kit_components(kit_id, PROGRAM_ADMIN, params=params)
    )


def read_component(kit_id: str, component_id: str) -> dict:
    for component in read_components(kit_id):
        if component["id"] == component_id:
            return component
    raise AssertionError(f"Setup failed: component {component_id} not found on kit {kit_id}")


def record_lapse(
    episode_id: str, gap_start_at: str, gap_end_at: str, **overrides: Any
) -> dict:
    payload = create_monitoring_lapse_payload(
        episode_id, gap_start_at, gap_end_at, **overrides
    )
    return get_success_data(api_client.create_monitoring_lapse(payload, FIELD_NURSE))


def open_meal_plan(episode_id: str, **overrides: Any) -> dict:
    payload = create_meal_plan_payload(episode_id, **overrides)
    return get_success_data(api_client.create_meal_plan(payload, LOGISTICS_COORDINATOR))


def read_meal_plan(episode_id: str, meal_plan_id: str) -> dict:
    for plan in get_success_data(
        api_client.list_episode_meal_plans(episode_id, PROGRAM_ADMIN)
    ):
        if plan["id"] == meal_plan_id:
            return plan
    raise AssertionError(f"Setup failed: meal plan {meal_plan_id} not found")


def raise_delivery_order(episode_id: str, **overrides: Any) -> dict:
    payload = create_delivery_order_payload(episode_id, **overrides)
    return get_success_data(
        api_client.create_delivery_order(payload, LOGISTICS_COORDINATOR)
    )


def authorize_order(order_id: str, authorizer_user_id: str = "pharm-7") -> dict:
    return get_success_data(
        api_client.authorize_delivery_order(
            order_id, make_pharmacy_authorizer_headers(authorizer_user_id)
        )
    )


def dispatch_order(order_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_delivery_order(order_id, LOGISTICS_COORDINATOR)
    )


def refuse_order(order_id: str) -> dict:
    return get_success_data(
        api_client.refuse_delivery_order(order_id, LOGISTICS_COORDINATOR)
    )


def deliver_order(order_id: str, payload: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.deliver_delivery_order(
            order_id, payload or {}, LOGISTICS_COORDINATOR
        )
    )


def read_delivery_order(episode_id: str, order_id: str) -> dict:
    for order in get_success_data(
        api_client.list_episode_delivery_orders(episode_id, PROGRAM_ADMIN)
    ):
        if order["id"] == order_id:
            return order
    raise AssertionError(f"Setup failed: delivery order {order_id} not found")


def open_escalation(episode_id: str, **overrides: Any) -> dict:
    payload = create_escalation_event_payload(episode_id, **overrides)
    return get_success_data(api_client.create_escalation_event(payload, FIELD_NURSE))


def read_escalation(episode_id: str, escalation_id: str) -> dict:
    for event in get_success_data(
        api_client.list_episode_escalation_events(episode_id, PROGRAM_ADMIN)
    ):
        if event["id"] == escalation_id:
            return event
    raise AssertionError(f"Setup failed: escalation {escalation_id} not found")


def register_unit(**overrides: Any) -> dict:
    payload = create_inpatient_unit_payload(**overrides)
    return get_success_data(api_client.create_inpatient_unit(payload, PROGRAM_ADMIN))


def read_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_inpatient_unit(unit_id, PROGRAM_ADMIN))


def hold_bed(unit_id: str, episode_id: str, expected_unit_version: int) -> dict:
    payload = create_bed_reservation_payload(
        unit_id, episode_id, expected_unit_version
    )
    return get_success_data(
        api_client.create_bed_reservation(payload, ADMITTING_PHYSICIAN)
    )


def read_reservation(reservation_id: str) -> dict:
    return get_success_data(
        api_client.get_bed_reservation(reservation_id, ADMITTING_PHYSICIAN)
    )


def build_claim(episode_id: str, expected_episode_version: int) -> dict:
    payload = create_billing_claim_payload(episode_id, expected_episode_version)
    return get_success_data(api_client.create_billing_claim(payload, BILLING_ANALYST))


def read_claim(episode_id: str, claim_id: str) -> dict:
    for claim in get_success_data(
        api_client.list_episode_billing_claims(episode_id, BILLING_ANALYST)
    ):
        if claim["id"] == claim_id:
            return claim
    raise AssertionError(f"Setup failed: billing claim {claim_id} not found")


# ─── Tier 1: admission funnel ──────────────────────────────────────────────

def setup_eligible_referral(
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    home_distance_km: float = 5.0,
    diet_restriction: str = "NONE",
    caregiver_present: bool = True,
    broadband_verified: bool = True,
    primary_diagnosis_code: str = "CHF_EXAC",
    origin: str = "ED",
    qualifying_condition_code: str = "CHF_EXAC",
    acuity: str = "STANDARD",
    full_name: str = "Test Patient",
    mrn: Optional[str] = None,
    set_the_clock: bool = True,
    assessment_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """Register a patient, file a referral, record one all-PASS assessment and
    walk the referral SCREENING -> ELIGIBLE."""
    if set_the_clock:
        set_clock(clock)
    patient_kwargs: Dict[str, Any] = {
        "full_name": full_name,
        "home_distance_km": home_distance_km,
        "primary_diagnosis_code": primary_diagnosis_code,
        "diet_restriction": diet_restriction,
        "broadband_verified": broadband_verified,
        "caregiver_present": caregiver_present,
    }
    if mrn is not None:
        patient_kwargs["mrn"] = mrn
    patient = register_patient(**patient_kwargs)
    referral = file_referral(
        patient["id"],
        origin=origin,
        qualifying_condition_code=qualifying_condition_code,
        acuity=acuity,
    )
    assessment = record_assessment(
        referral["id"], eval_at, **(assessment_overrides or {})
    )
    referral = mark_eligible(referral["id"])
    return {"patient": patient, "referral": referral, "assessment": assessment}


def setup_screening_referral(
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    set_the_clock: bool = True,
    patient_overrides: Optional[dict] = None,
    referral_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """Register a patient, file a referral and record one assessment, leaving the
    referral in SCREENING so the gauntlet can be exercised."""
    if set_the_clock:
        set_clock(clock)
    patient = register_patient(**(patient_overrides or {}))
    referral = file_referral(patient["id"], **(referral_overrides or {}))
    assessment = record_assessment(
        referral["id"], eval_at, **(assessment_overrides or {})
    )
    return {"patient": patient, "referral": referral, "assessment": assessment}


def setup_active_episode(
    program_track: str = "CMS_WAIVER",
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    home_distance_km: float = 5.0,
    diet_restriction: str = "NONE",
    caregiver_present: bool = True,
    primary_diagnosis_code: str = "CHF_EXAC",
    origin: str = "ED",
    qualifying_condition_code: str = "CHF_EXAC",
    acuity: str = "STANDARD",
    full_name: str = "Test Patient",
    mrn: Optional[str] = None,
    set_the_clock: bool = True,
) -> Dict[str, Any]:
    """Full admission funnel through to an ACTIVE episode.

    Returns ``{"patient", "referral", "assessment", "episode"}``.
    """
    parts = setup_eligible_referral(
        clock=clock,
        eval_at=eval_at,
        home_distance_km=home_distance_km,
        diet_restriction=diet_restriction,
        caregiver_present=caregiver_present,
        primary_diagnosis_code=primary_diagnosis_code,
        origin=origin,
        qualifying_condition_code=qualifying_condition_code,
        acuity=acuity,
        full_name=full_name,
        mrn=mrn,
        set_the_clock=set_the_clock,
    )
    parts["episode"] = admit(
        parts["patient"]["id"], parts["referral"]["id"], program_track
    )
    return parts


# ─── Tier 2: visits and the daily verdict ──────────────────────────────────

def headers_for_staff(visit_type: str, staff_user_id: str) -> Dict[str, str]:
    """Pick the acting role whose discipline matches the visit modality and
    stamp it with the clinician's own operator identifier, so that
    ``attested_by_user_id`` records the clinician who owns the slot."""
    if visit_type == "PARAMEDIC_IN_PERSON":
        return make_community_paramedic_headers(staff_user_id)
    if visit_type in ("PHYSICIAN_IN_PERSON", "PHYSICIAN_TELEHEALTH"):
        return make_admitting_physician_headers(staff_user_id)
    return make_field_nurse_headers(staff_user_id)


def schedule_visit(
    episode_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    visit_type: str = "RN_IN_PERSON",
    staff_user_id: str = "rn-1",
    distance_km: float = 5.0,
    service_date: Optional[str] = None,
) -> dict:
    payload = create_visit_payload(
        episode_id,
        service_date or date_part(scheduled_start_at),
        scheduled_start_at,
        scheduled_end_at,
        visit_type=visit_type,
        staff_user_id=staff_user_id,
        distance_km=distance_km,
    )
    return get_success_data(
        api_client.create_visit(payload, headers_for_staff(visit_type, staff_user_id))
    )


def depart_visit(visit_id: str, visit_type: str, staff_user_id: str) -> dict:
    return get_success_data(
        api_client.depart_visit(visit_id, headers_for_staff(visit_type, staff_user_id))
    )


def complete_visit(visit_id: str, visit_type: str, staff_user_id: str) -> dict:
    return get_success_data(
        api_client.complete_visit(
            visit_id, headers_for_staff(visit_type, staff_user_id)
        )
    )


def attest_visit(visit_id: str, visit_type: str, staff_user_id: str) -> dict:
    return get_success_data(
        api_client.attest_visit(visit_id, headers_for_staff(visit_type, staff_user_id))
    )


def perform_and_attest_visit(
    episode_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    visit_type: str = "RN_IN_PERSON",
    staff_user_id: str = "rn-1",
    distance_km: float = 5.0,
    service_date: Optional[str] = None,
) -> dict:
    """Schedule -> depart -> complete -> attest.  Returns the attested visit."""
    visit = schedule_visit(
        episode_id,
        scheduled_start_at,
        scheduled_end_at,
        visit_type=visit_type,
        staff_user_id=staff_user_id,
        distance_km=distance_km,
        service_date=service_date,
    )
    depart_visit(visit["id"], visit_type, staff_user_id)
    complete_visit(visit["id"], visit_type, staff_user_id)
    return attest_visit(visit["id"], visit_type, staff_user_id)


def compliance_day_for(episode_id: str, service_date: str) -> dict:
    rows = get_success_data(
        api_client.list_compliance_days(
            episode_id, PROGRAM_ADMIN, params={"service_date": service_date}
        )
    )
    assert rows, (
        f"Setup failed: episode {episode_id} owns no compliance record for "
        f"{service_date}"
    )
    return rows[0]


def finalize_day(compliance_day_id: str) -> dict:
    return get_success_data(
        api_client.finalize_compliance_day(compliance_day_id, PROGRAM_ADMIN)
    )


def read_ledger(episode_id: str) -> dict:
    return get_success_data(
        api_client.get_episode_ledger(episode_id, ADMITTING_PHYSICIAN)
    )


def make_waiver_day_compliant(
    episode_id: str,
    service_date: str,
    day_start_hour: int = 9,
    distance_km: float = 5.0,
) -> Dict[str, Any]:
    """Give one calendar date the two qualified in-person visits and the
    physician evaluation a waiver day requires, then leave it PENDING.

    Staff identities are distinct per discipline and the slots are spread far
    enough apart that the turnaround buffer never bites.
    """
    base = f"{service_date}T{day_start_hour:02d}:00:00Z"
    rn = perform_and_attest_visit(
        episode_id,
        base,
        shift_minutes(base, 45),
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=distance_km,
        service_date=service_date,
    )
    medic_start = shift_minutes(base, 300)
    medic = perform_and_attest_visit(
        episode_id,
        medic_start,
        shift_minutes(medic_start, 45),
        visit_type="PARAMEDIC_IN_PERSON",
        staff_user_id="medic-1",
        distance_km=distance_km,
        service_date=service_date,
    )
    phys_start = shift_minutes(base, 420)
    physician = perform_and_attest_visit(
        episode_id,
        phys_start,
        shift_minutes(phys_start, 30),
        visit_type="PHYSICIAN_TELEHEALTH",
        staff_user_id="phys-1",
        distance_km=0,
        service_date=service_date,
    )
    return {"rn_visit": rn, "paramedic_visit": medic, "physician_visit": physician}


# ─── Tier 3: escalation ladder ─────────────────────────────────────────────

STANDARD_TIER_MINUTES = {1: 10, 2: 20, 3: 30, 4: 15}
HIGH_TIER_MINUTES = {1: 5, 2: 10, 3: 15, 4: 8}


def escalate_to_tier(
    episode_id: str,
    target_tier: int,
    opened_at: str,
    acuity: str = "STANDARD",
    reason: str = "VITALS_OUT_OF_RANGE",
    opened_by_user_id: str = "rn-1",
) -> Tuple[dict, str]:
    """Open a tier-1 escalation at ``opened_at`` and drive it up to
    ``target_tier`` by breaching each open tier's acknowledgement deadline.

    Returns ``(escalation, clock_now)`` where ``clock_now`` is the logical clock
    value in force after the last promotion.
    """
    set_clock(opened_at)
    escalation = open_escalation(
        episode_id, reason=reason, opened_by_user_id=opened_by_user_id
    )
    allowances = HIGH_TIER_MINUTES if acuity == "HIGH" else STANDARD_TIER_MINUTES
    now = opened_at
    for tier in range(1, target_tier):
        now = shift_minutes(now, allowances[tier] + 1)
        set_clock(now)
        escalation = get_success_data(
            api_client.promote_escalation(escalation["id"], PROGRAM_ADMIN)
        )
    return escalation, now


def acknowledge_escalation(escalation_id: str, user_id: str = "medic-1") -> dict:
    return get_success_data(
        api_client.acknowledge_escalation(
            escalation_id, make_community_paramedic_headers(user_id)
        )
    )


def resolve_escalation(escalation_id: str, user_id: str = "medic-1") -> dict:
    return get_success_data(
        api_client.resolve_escalation(
            escalation_id, make_community_paramedic_headers(user_id)
        )
    )


def convert_to_bed_return(escalation_id: str) -> dict:
    return get_success_data(
        api_client.convert_escalation_to_bed_return(escalation_id, ADMITTING_PHYSICIAN)
    )


def setup_escalated_episode_with_held_bed(
    program_track: str = "CMS_WAIVER",
    clock: str = "2026-06-02T09:00:00Z",
    eval_at: str = "2026-06-02T07:00:00Z",
    target_tier: int = 4,
    total_beds: int = 2,
    acuity: str = "STANDARD",
    reason: str = "FALL",
    hold_bed_after_tier: int = 3,
) -> Dict[str, Any]:
    """An episode promoted up the ladder past tier 3 (so it is ESCALATED) with a
    registered inpatient unit and one HELD reservation, ready for conversion."""
    parts = setup_active_episode(
        program_track=program_track, clock=clock, eval_at=eval_at, acuity=acuity
    )
    episode = parts["episode"]

    set_clock(clock)
    escalation = open_escalation(
        episode["id"], reason=reason, opened_by_user_id="rn-1"
    )
    allowances = HIGH_TIER_MINUTES if acuity == "HIGH" else STANDARD_TIER_MINUTES
    now = clock
    unit = None
    reservation = None
    for tier in range(1, target_tier):
        now = shift_minutes(now, allowances[tier] + 1)
        set_clock(now)
        escalation = get_success_data(
            api_client.promote_escalation(escalation["id"], PROGRAM_ADMIN)
        )
        if unit is None and (tier + 1) >= hold_bed_after_tier:
            unit = register_unit(total_beds=total_beds)
            reservation = hold_bed(unit["id"], episode["id"], unit["version"])

    if unit is None:
        unit = register_unit(total_beds=total_beds)
        reservation = hold_bed(unit["id"], episode["id"], unit["version"])

    parts.update(
        {
            "escalation": escalation,
            "unit": unit,
            "reservation": reservation,
            "clock_now": now,
        }
    )
    return parts


# ─── Tier 4: threshold-targeted day ledgers ────────────────────────────────

def setup_episode_with_compliant_day(
    program_track: str = "FEE_FOR_SERVICE",
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    service_date: str = DEFAULT_SERVICE_DATE,
    distance_km: float = 5.0,
    finalize: bool = True,
    home_distance_km: float = 5.0,
    diet_restriction: str = "NONE",
) -> Dict[str, Any]:
    """An episode whose single service date carries the visit set its track
    requires, optionally finalized so ``billable_day_count`` is 1.

    A fee-for-service day needs one qualified in-person visit; a waiver day
    needs two plus a physician evaluation.
    """
    parts = setup_active_episode(
        program_track=program_track,
        clock=clock,
        eval_at=eval_at,
        home_distance_km=home_distance_km,
        diet_restriction=diet_restriction,
    )
    episode_id = parts["episode"]["id"]
    if program_track == "CMS_WAIVER":
        parts["visits"] = make_waiver_day_compliant(episode_id, service_date)
        parts["visit"] = parts["visits"]["rn_visit"]
    else:
        parts["visit"] = perform_and_attest_visit(
            episode_id,
            f"{service_date}T09:00:00Z",
            f"{service_date}T09:45:00Z",
            visit_type="RN_IN_PERSON",
            staff_user_id="rn-1",
            distance_km=distance_km,
            service_date=service_date,
        )
    day = compliance_day_for(episode_id, service_date)
    if finalize:
        day = finalize_day(day["id"])
    parts["compliance_day"] = day
    parts["episode"] = read_episode(episode_id)
    return parts


def sign_med_rec(episode_id: str) -> dict:
    return get_success_data(
        api_client.sign_med_rec(episode_id, ADMITTING_PHYSICIAN)
    )


def begin_discharge(episode_id: str) -> dict:
    return get_success_data(
        api_client.begin_discharge(episode_id, ADMITTING_PHYSICIAN)
    )


def complete_discharge(episode_id: str) -> dict:
    return get_success_data(
        api_client.discharge_episode(episode_id, ADMITTING_PHYSICIAN)
    )


def readmit(episode_id: str) -> dict:
    return get_success_data(
        api_client.readmit_episode(episode_id, ADMITTING_PHYSICIAN)
    )


# ─── Tier 5: terminal states and the revenue cycle ─────────────────────────

def setup_discharged_ffs_episode_with_one_compliant_day(
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    service_date: str = DEFAULT_SERVICE_DATE,
) -> Dict[str, Any]:
    """A fee-for-service episode with exactly one compliant service day, no meal
    plan and no delivery orders, taken all the way to DISCHARGED.

    ``reimbursement_amount_usd`` is therefore the flat 9600.00 base with no
    outlier days and no meal credit.
    """
    parts = setup_episode_with_compliant_day(
        program_track="FEE_FOR_SERVICE",
        clock=clock,
        eval_at=eval_at,
        service_date=service_date,
        finalize=False,
    )
    episode_id = parts["episode"]["id"]
    sign_med_rec(episode_id)
    begin_discharge(episode_id)
    parts["episode"] = complete_discharge(episode_id)
    parts["compliance_day"] = compliance_day_for(episode_id, service_date)
    return parts


def setup_built_claim_on_discharged_ffs_episode(
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    service_date: str = DEFAULT_SERVICE_DATE,
) -> Dict[str, Any]:
    """Discharged fee-for-service episode plus a freshly built claim anchored to
    the episode version the analyst just read."""
    parts = setup_discharged_ffs_episode_with_one_compliant_day(
        clock=clock, eval_at=eval_at, service_date=service_date
    )
    episode = read_episode(parts["episode"]["id"])
    parts["episode"] = episode
    parts["claim"] = build_claim(episode["id"], episode["version"])
    return parts


def submit_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.submit_billing_claim(claim_id, BILLING_ANALYST)
    )


def record_outcome(claim_id: str, outcome: str, denial_reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"outcome": outcome}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.record_claim_outcome(claim_id, payload, BILLING_ANALYST)
    )


def appeal_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.appeal_billing_claim(claim_id, BILLING_ANALYST)
    )


def setup_discharge_pending_with_deployed_kit(
    program_track: str = "CMS_WAIVER",
    clock: str = DEFAULT_CLOCK,
    eval_at: str = DEFAULT_EVAL_AT,
    component_type: str = "BP_CUFF",
    replacement_cost_usd: float = 90.00,
    sign_the_med_rec: bool = False,
    with_open_delivery_order: bool = False,
) -> Dict[str, Any]:
    """An episode in DISCHARGE_PENDING whose begin-discharge kit release left one
    component in PENDING_RECONCILIATION, optionally with the medication
    reconciliation already signed and an in-flight delivery order."""
    parts = setup_active_episode(
        program_track=program_track, clock=clock, eval_at=eval_at
    )
    episode_id = parts["episode"]["id"]
    kit = register_kit()
    component = add_component(
        kit["id"],
        component_type=component_type,
        replacement_cost_usd=replacement_cost_usd,
    )
    deploy_kit(kit["id"], episode_id, kit["version"])

    if with_open_delivery_order:
        order = raise_delivery_order(
            episode_id,
            order_kind="DME",
            is_controlled=False,
            cold_chain_required=False,
            weight_kg=1.5,
            requested_by_user_id="log-1",
        )
        parts["delivery_order"] = authorize_order(order["id"], "pharm-9")

    if sign_the_med_rec:
        sign_med_rec(episode_id)

    parts["kit"] = kit
    parts["component"] = component
    parts["episode"] = begin_discharge(episode_id)
    return parts


def setup_bed_return_cascade() -> Dict[str, Any]:
    """The program's deepest single operation, staged but not yet triggered.

    A waiver episode with a deployed one-component kit, an active meal plan and
    an authorized delivery order; 2026-06-01 finalized COMPLIANT with a claim
    built against it; 2026-06-02 carrying two attested in-person visits plus an
    attested telehealth physician evaluation so its still-PENDING record can only
    fail on the kit clause; and an escalation promoted to tier 4 over a HELD bed.
    """
    parts = setup_active_episode(
        program_track="CMS_WAIVER",
        clock="2026-06-01T08:00:00Z",
        eval_at="2026-06-01T06:00:00Z",
        home_distance_km=11.0,
        origin="INPATIENT_WARD",
        full_name="Bea Bedreturn",
    )
    episode_id = parts["episode"]["id"]

    kit = register_kit()
    component = add_component(
        kit["id"], component_type="TABLET", replacement_cost_usd=450.00
    )
    deploy_kit(kit["id"], episode_id, kit["version"])

    meal_plan = open_meal_plan(episode_id, diet_code="NONE", daily_delivery_count=3)

    order = raise_delivery_order(
        episode_id,
        order_kind="DME",
        is_controlled=False,
        cold_chain_required=False,
        weight_kg=1.0,
        requested_by_user_id="log-1",
    )
    order = authorize_order(order["id"], "pharm-9")

    day_one_visits = make_waiver_day_compliant(episode_id, "2026-06-01", day_start_hour=9)
    day_one = compliance_day_for(episode_id, "2026-06-01")
    day_one = finalize_day(day_one["id"])

    episode = read_episode(episode_id)
    claim = build_claim(episode_id, episode["version"])

    set_clock("2026-06-02T08:00:00Z")
    day_two_visits = make_waiver_day_compliant(
        episode_id, "2026-06-02", day_start_hour=8
    )

    set_clock("2026-06-02T12:00:00Z")
    escalation = open_escalation(
        episode_id, reason="VITALS_OUT_OF_RANGE", opened_by_user_id="rn-1"
    )
    set_clock("2026-06-02T12:11:00Z")
    escalation = get_success_data(
        api_client.promote_escalation(escalation["id"], PROGRAM_ADMIN)
    )
    set_clock("2026-06-02T12:32:00Z")
    escalation = get_success_data(
        api_client.promote_escalation(escalation["id"], PROGRAM_ADMIN)
    )

    unit = register_unit(total_beds=2)
    reservation = hold_bed(unit["id"], episode_id, unit["version"])

    set_clock("2026-06-02T13:03:00Z")
    escalation = get_success_data(
        api_client.promote_escalation(escalation["id"], PROGRAM_ADMIN)
    )

    parts.update(
        {
            "kit": kit,
            "component": component,
            "meal_plan": meal_plan,
            "delivery_order": order,
            "day_one_visits": day_one_visits,
            "day_two_visits": day_two_visits,
            "day_one": day_one,
            "claim": claim,
            "escalation": escalation,
            "unit": unit,
            "reservation": reservation,
            "conversion_clock": "2026-06-02T13:03:00Z",
        }
    )
    return parts
