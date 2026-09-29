"""Composite setup helpers.

Most interesting claims in this API need the system walked several calls deep
before the operation under test can even be attempted: a survivor record, a
crisis call, a scored assessment, a screening decision, a bed reservation and a
clock advance are all preconditions for a single check-in. These helpers
encapsulate those preambles so that a test body contains the trigger and the
assertions and nothing else.

Every helper uses the lenient `get_success_data` validator so that a broken
precondition surfaces as an obvious setup failure rather than as a confusing
assertion deep inside a test.

Identity threading: the five operational roles bind `X-User-ID` to the acting
StaffMember's id, so every helper that performs an ownership-gated call builds
its headers from the real staff row it just created.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_UTC, TEST_DEFAULTS
from .factories import (
    cancel_payload,
    change_consent_payload,
    check_in_payload,
    complete_relocation_payload,
    create_client_payload,
    create_disclosure_event_payload,
    create_hotline_call_payload,
    create_housing_referral_payload,
    create_landlord_partner_payload,
    create_plan_component_payload,
    create_protective_order_case_payload,
    create_risk_assessment_payload,
    create_screening_request_payload,
    create_shelter_admission_payload,
    create_shelter_payload,
    create_shelter_unit_payload,
    create_staff_member_payload,
    create_wellness_check_payload,
    decide_disclosure_payload,
    decide_screening_payload,
    dispose_payload,
    exit_payload,
    file_protective_order_payload,
    match_referral_payload,
    next_client_code,
    record_outcome_payload,
    report_compromise_payload,
    set_clock_payload,
    withdraw_match_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    make_hotline_advocate_headers,
    make_housing_specialist_headers,
    make_legal_advocate_headers,
    make_privacy_officer_headers,
    make_shelter_manager_headers,
)


@dataclass
class Actor:
    """A StaffMember row paired with the headers that act as that staff member."""

    staff: Dict[str, Any]
    headers: Dict[str, str]

    @property
    def id(self) -> str:
        return self.staff["id"]

    @property
    def version(self) -> int:
        return self.staff["version"]


# --- Tier 1: single-entity seeds ---------------------------------------------


def seed_staff(role_header_builder, full_name: str, role_type: str, **overrides) -> Actor:
    """Register one staff member and return it with headers bound to its own id."""
    payload = create_staff_member_payload(
        full_name=full_name, role_type=role_type, **overrides
    )
    staff = get_success_data(api_client.create_staff_member(payload, ADMIN_HEADERS))
    return Actor(staff=staff, headers=role_header_builder(staff["id"]))


def seed_hotline_advocate(full_name: str = "Rosa Marin", **overrides) -> Actor:
    return seed_staff(
        make_hotline_advocate_headers, full_name, "HOTLINE_ADVOCATE", **overrides
    )


def seed_shelter_manager(full_name: str = "Dana Whit", **overrides) -> Actor:
    overrides.setdefault("max_caseload", 20)
    return seed_staff(make_shelter_manager_headers, full_name, "SHELTER_MANAGER", **overrides)


def seed_legal_advocate(full_name: str = "Nils Berg", **overrides) -> Actor:
    overrides.setdefault("max_caseload", 12)
    return seed_staff(make_legal_advocate_headers, full_name, "LEGAL_ADVOCATE", **overrides)


def seed_housing_specialist(full_name: str = "Omar Diaz", **overrides) -> Actor:
    overrides.setdefault("max_caseload", 15)
    return seed_staff(
        make_housing_specialist_headers, full_name, "HOUSING_SPECIALIST", **overrides
    )


def seed_privacy_officer(full_name: str = "Opal Reed", **overrides) -> Actor:
    overrides.setdefault("max_caseload", 12)
    return seed_staff(make_privacy_officer_headers, full_name, "PRIVACY_OFFICER", **overrides)


def seed_client(advocate: Actor, **overrides) -> Dict[str, Any]:
    """Open one survivor record as the given HotlineAdvocate."""
    overrides.setdefault("client_code", next_client_code())
    payload = create_client_payload(**overrides)
    return get_success_data(api_client.create_client(payload, advocate.headers))


def seed_shelter(manager: Actor, **overrides) -> Dict[str, Any]:
    payload = create_shelter_payload(**overrides)
    return get_success_data(api_client.create_shelter(payload, manager.headers))


def seed_unit(manager: Actor, shelter_id: str, **overrides) -> Dict[str, Any]:
    payload = create_shelter_unit_payload(**overrides)
    return get_success_data(
        api_client.create_shelter_unit(shelter_id, payload, manager.headers)
    )


def seed_landlord_partner(specialist: Actor, **overrides) -> Dict[str, Any]:
    payload = create_landlord_partner_payload(**overrides)
    return get_success_data(api_client.create_landlord_partner(payload, specialist.headers))


def seed_hotline_call(advocate: Actor, client_id: str, **overrides) -> Dict[str, Any]:
    payload = create_hotline_call_payload(client_id, **overrides)
    return get_success_data(api_client.create_hotline_call(payload, advocate.headers))


def seed_risk_assessment(advocate: Actor, call_id: str, **overrides) -> Dict[str, Any]:
    payload = create_risk_assessment_payload(**overrides)
    return get_success_data(
        api_client.create_risk_assessment(call_id, payload, advocate.headers)
    )


def advance_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock forward and return the clock response payload."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), headers or ADMIN_HEADERS)
    )


def read_unit(manager: Actor, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_shelter_unit(unit_id, manager.headers))


def unit_version(manager: Actor, unit_id: str) -> int:
    """Read the destination unit's current version for the concurrency guard."""
    return read_unit(manager, unit_id)["version"]


def read_client(client_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_client(client_id, headers or ADMIN_HEADERS))


def client_version(client_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return read_client(client_id, headers)["version"]


def read_staff(staff_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_staff_member(staff_id, headers or ADMIN_HEADERS))


def read_partner(specialist: Actor, partner_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_landlord_partner(partner_id, specialist.headers))


def partner_version(specialist: Actor, partner_id: str) -> int:
    return read_partner(specialist, partner_id)["version"]


def read_plan(plan_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.get_safety_plan(plan_id, headers))


def read_admission(manager: Actor, admission_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_shelter_admission(admission_id, manager.headers))


def read_shelter(manager: Actor, shelter_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_shelter(shelter_id, manager.headers))


def record_wellness_check(staff_id: str, **overrides) -> Dict[str, Any]:
    """File one wellness check as the AgencyAdmin, who may record for any member."""
    payload = create_wellness_check_payload(**overrides)
    return get_success_data(
        api_client.create_wellness_check(staff_id, payload, ADMIN_HEADERS)
    )


# --- Tier 2: intake through a scored call ------------------------------------


def seed_assessed_call(
    advocate: Actor,
    client_id: str,
    call_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Log a crisis call and score it, leaving the call in RISK_ASSESSED."""
    call = seed_hotline_call(advocate, client_id, **(call_overrides or {}))
    assessment = seed_risk_assessment(advocate, call["id"], **(assessment_overrides or {}))
    return call, assessment


def seed_client_with_assessed_call(
    advocate: Actor,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    call_overrides: Optional[dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Survivor record plus one RISK_ASSESSED call. Returns (client, call, assessment)."""
    client = seed_client(advocate, **(client_overrides or {}))
    call, assessment = seed_assessed_call(
        advocate, client["id"], call_overrides, assessment_overrides
    )
    return client, call, assessment


#: Factor inputs that reach the 100.0 ceiling and therefore the IMMINENT band.
IMMINENT_FACTORS = {
    "weapon_access": True,
    "strangulation_history": True,
    "separation_recent": True,
    "threats_to_kill": True,
    "stalking_frequency_per_week": 8,
}

#: Factor inputs that score 48.4 and therefore the MODERATE band.
MODERATE_FACTORS = {
    "weapon_access": True,
    "strangulation_history": False,
    "separation_recent": True,
    "threats_to_kill": False,
    "stalking_frequency_per_week": 2,
}


def seed_imminent_client(
    advocate: Actor, **client_overrides
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A survivor whose latest assessment bands IMMINENT. Returns (client, call, assessment)."""
    return seed_client_with_assessed_call(
        advocate,
        client_overrides=client_overrides,
        assessment_overrides=dict(IMMINENT_FACTORS),
    )


def dispose_call(advocate: Actor, call_id: str, disposition: str, **overrides):
    """Dispose a RISK_ASSESSED call down one of its three branches."""
    return api_client.dispose_hotline_call(
        call_id, dispose_payload(disposition, **overrides), advocate.headers
    )


def latest_plan_of_client(advocate: Actor, client_id: str) -> Dict[str, Any]:
    """Read the survivor's plans and return the most recently created one."""
    body = get_success_data(
        api_client.list_safety_plans(
            advocate.headers, params={"client_id": client_id, "limit": 100, "offset": 0}
        )
    )
    assert body, f"expected at least one safety plan for client {client_id}"
    return body[-1]


def seed_draft_plan_by_disposition(
    advocate: Actor, client_id: str, call_id: str
) -> Dict[str, Any]:
    """Dispose SAFETY_PLAN_ONLY, which is the branch that authors a DRAFT plan."""
    get_success_data(dispose_call(advocate, call_id, "SAFETY_PLAN_ONLY"))
    return latest_plan_of_client(advocate, client_id)


def seed_plan_with_components(
    advocate: Actor,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    component_types: Tuple[str, ...] = ("COMMUNICATION",),
    component_overrides: Optional[Dict[str, dict]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Survivor with a DRAFT plan carrying one component per requested domain.

    Returns (client, plan, components).
    """
    client, call, _assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
    )
    plan = seed_draft_plan_by_disposition(advocate, client["id"], call["id"])
    components = []
    for component_type in component_types:
        extra = (component_overrides or {}).get(component_type, {})
        components.append(
            get_success_data(
                api_client.create_plan_component(
                    plan["id"],
                    create_plan_component_payload(component_type, **extra),
                    advocate.headers,
                )
            )
        )
    return client, plan, components


def seed_active_plan(
    advocate: Actor,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    component_types: Tuple[str, ...] = ("RELOCATION",),
    component_overrides: Optional[Dict[str, dict]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """As seed_plan_with_components, then activate the plan. Returns (client, plan, components)."""
    client, plan, components = seed_plan_with_components(
        advocate,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
        component_types=component_types,
        component_overrides=component_overrides,
    )
    plan = get_success_data(api_client.activate_safety_plan(plan["id"], advocate.headers))
    return client, plan, components


# --- Tier 3: shelter placement lifecycle -------------------------------------


@dataclass
class ShelterScene:
    """A shelter with one unit, plus the two actors who work it."""

    advocate: Actor
    manager: Actor
    shelter: Dict[str, Any]
    unit: Dict[str, Any]


def seed_shelter_scene(
    shelter_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
    advocate_overrides: Optional[dict] = None,
) -> ShelterScene:
    """One HotlineAdvocate, one ShelterManager, one shelter and one unit."""
    advocate = seed_hotline_advocate(**(advocate_overrides or {}))
    manager = seed_shelter_manager()
    shelter = seed_shelter(manager, **(shelter_overrides or {}))
    unit = seed_unit(manager, shelter["id"], **(unit_overrides or {}))
    return ShelterScene(advocate=advocate, manager=manager, shelter=shelter, unit=unit)


def seed_screening_request(
    advocate: Actor, client_id: str, call_id: str, shelter_id: str, **overrides
) -> Dict[str, Any]:
    payload = create_screening_request_payload(client_id, call_id, shelter_id, **overrides)
    return get_success_data(api_client.create_screening_request(payload, advocate.headers))


def decide_screening(manager: Actor, request_id: str, decision: str, **overrides):
    return api_client.decide_screening_request(
        request_id, decide_screening_payload(decision, **overrides), manager.headers
    )


def approve_screening(manager: Actor, request_id: str, advocate_id: str) -> Dict[str, Any]:
    return get_success_data(
        decide_screening(manager, request_id, "APPROVE", assigned_advocate_id=advocate_id)
    )


def waitlist_screening(manager: Actor, request_id: str, advocate_id: str) -> Dict[str, Any]:
    return get_success_data(
        decide_screening(manager, request_id, "WAITLIST", assigned_advocate_id=advocate_id)
    )


def seed_approved_screening(
    scene: ShelterScene,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Survivor, scored call and an APPROVED screening request against the scene's shelter.

    Returns (client, call, screening_request).
    """
    client, call, _assessment = seed_client_with_assessed_call(
        scene.advocate,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
    )
    request = seed_screening_request(
        scene.advocate,
        client["id"],
        call["id"],
        scene.shelter["id"],
        **(request_overrides or {}),
    )
    request = approve_screening(scene.manager, request["id"], scene.advocate.id)
    return client, call, request


def reserve_bed(
    scene: ShelterScene,
    screening_request_id: str,
    unit_id: Optional[str] = None,
    **overrides,
):
    """Create the admission, reading the destination unit's version first."""
    target_unit = unit_id or scene.unit["id"]
    expected = overrides.pop(
        "expected_shelter_unit_version", unit_version(scene.manager, target_unit)
    )
    payload = create_shelter_admission_payload(
        screening_request_id, target_unit, expected, **overrides
    )
    return api_client.create_shelter_admission(payload, scene.manager.headers)


def seed_reserved_admission(
    scene: Optional[ShelterScene] = None,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    admission_overrides: Optional[dict] = None,
) -> Tuple[ShelterScene, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk intake through to a RESERVED admission.

    Returns (scene, client, screening_request, admission).
    """
    scene = scene or seed_shelter_scene()
    client, _call, request = seed_approved_screening(
        scene,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
    )
    admission = get_success_data(
        reserve_bed(scene, request["id"], **(admission_overrides or {}))
    )
    return scene, client, request, admission


def seed_checked_in_admission(
    scene: Optional[ShelterScene] = None,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    admission_overrides: Optional[dict] = None,
    check_in_overrides: Optional[dict] = None,
    entry_clock: Optional[str] = None,
) -> Tuple[ShelterScene, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """As seed_reserved_admission, then advance the clock to the entry date and check in.

    Returns (scene, client, screening_request, admission).
    """
    scene, client, request, admission = seed_reserved_admission(
        scene=scene,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
        admission_overrides=admission_overrides,
    )
    advance_clock(entry_clock or f"{admission['entry_date']}T08:00:00Z")
    admission = get_success_data(
        api_client.check_in_admission(
            admission["id"],
            scene.manager.headers,
            check_in_payload(**(check_in_overrides or {})),
        )
    )
    return scene, client, request, admission


def exit_household(
    scene: ShelterScene, admission_id: str, actual_exit_date: str, **overrides
):
    return api_client.exit_admission(
        admission_id, exit_payload(actual_exit_date, **overrides), scene.manager.headers
    )


def cancel_reservation(scene: ShelterScene, admission_id: str, **overrides):
    return api_client.cancel_admission(
        admission_id, cancel_payload(**overrides), scene.manager.headers
    )


def report_compromise(scene: ShelterScene, admission_id: str, **overrides):
    return api_client.report_location_compromise(
        admission_id, report_compromise_payload(**overrides), scene.manager.headers
    )


def relocate(scene: ShelterScene, admission_id: str, new_unit_id: str, **overrides):
    """Complete a relocation, reading the destination unit's version first."""
    expected = overrides.pop(
        "expected_shelter_unit_version", unit_version(scene.manager, new_unit_id)
    )
    return api_client.complete_relocation(
        admission_id,
        complete_relocation_payload(new_unit_id, expected, **overrides),
        scene.manager.headers,
    )


# --- Tier 4: threshold targeting ---------------------------------------------

#: A same-day check that contributes exactly 70.0 points and freezes the member.
FROZEN_CHECK = {
    "checked_on_utc": CLOCK_STARTUP_UTC,
    "exposure_hours": 20.0,
    "distress_scale": 10,
    "debrief_completed": False,
}

#: The same check one tenth of an hour lighter, contributing 69.9 points.
RESTRICTED_CHECK = {
    "checked_on_utc": CLOCK_STARTUP_UTC,
    "exposure_hours": 19.8,
    "distress_scale": 10,
    "debrief_completed": False,
}


def freeze_advocate(actor: Actor, **overrides) -> Dict[str, Any]:
    """Push a staff member's secondary-trauma index to the FROZEN band."""
    payload = dict(FROZEN_CHECK)
    payload.update(overrides)
    record_wellness_check(actor.id, **payload)
    return read_staff(actor.id)


def seed_frozen_advocate(full_name: str = "Rosa Marin", **overrides) -> Actor:
    """A HotlineAdvocate whose wellness posture is FROZEN before any assignment."""
    actor = seed_hotline_advocate(full_name, **overrides)
    freeze_advocate(actor)
    return actor


def seed_trauma_index_points(actor: Actor, distress_scale: int, exposure_hours: float,
                             checked_on_utc: str = CLOCK_STARTUP_UTC,
                             debrief_completed: bool = False) -> Dict[str, Any]:
    """File one check with chosen inputs, for tests that need an exact index value."""
    return record_wellness_check(
        actor.id,
        checked_on_utc=checked_on_utc,
        exposure_hours=exposure_hours,
        distress_scale=distress_scale,
        debrief_completed=debrief_completed,
    )


def seed_referral_on_active_plan(
    specialist: Actor,
    advocate: Actor,
    partner_overrides: Optional[dict] = None,
    referral_overrides: Optional[dict] = None,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    component_types: Tuple[str, ...] = ("RELOCATION",),
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Survivor with an ACTIVE plan, a landlord partner and one SUBMITTED referral.

    Returns (client, plan, partner, referral).
    """
    client, plan, _components = seed_active_plan(
        advocate,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
        component_types=component_types,
    )
    partner = seed_landlord_partner(specialist, **(partner_overrides or {}))
    referral = get_success_data(
        api_client.create_housing_referral(
            create_housing_referral_payload(
                client["id"], partner["id"], **(referral_overrides or {})
            ),
            specialist.headers,
        )
    )
    return client, plan, partner, referral


def submit_referral(
    specialist: Actor, client_id: str, partner_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_housing_referral(
            create_housing_referral_payload(client_id, partner_id, **overrides),
            specialist.headers,
        )
    )


def match_referral(
    specialist: Actor, referral_id: str, partner_id: str, monthly_rent_cents: int = 140000,
    **overrides
):
    """Match a referral, reading the partner's current version for the guard."""
    expected = overrides.pop(
        "expected_landlord_partner_version", partner_version(specialist, partner_id)
    )
    return api_client.match_housing_referral(
        referral_id,
        match_referral_payload(expected, monthly_rent_cents, **overrides),
        specialist.headers,
    )


def withdraw_match(specialist: Actor, referral_id: str, **overrides):
    return api_client.withdraw_housing_match(
        referral_id, withdraw_match_payload(**overrides), specialist.headers
    )


# --- Tier 5: sealed records, disclosure and court work -----------------------


def seed_sealed_client_via_compromise(
    scene: Optional[ShelterScene] = None,
    client_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    compromise_source: str = "ABUSER_CONTACT",
) -> Tuple[ShelterScene, Dict[str, Any], Dict[str, Any]]:
    """Reserve a bed and then report the location compromised, sealing the survivor.

    Returns (scene, client, admission).
    """
    scene, client, _request, admission = seed_reserved_admission(
        scene=scene,
        client_overrides=client_overrides,
        assessment_overrides=assessment_overrides,
    )
    admission = get_success_data(
        report_compromise(scene, admission["id"], compromise_source=compromise_source)
    )
    return scene, client, admission


def seed_disclosure_event(
    officer: Actor,
    client_id: str,
    requested_by_staff_id: str,
    kind: str,
    requested_field_keys: List[str],
    **overrides,
) -> Dict[str, Any]:
    payload = create_disclosure_event_payload(
        client_id, requested_by_staff_id, kind, requested_field_keys, **overrides
    )
    return get_success_data(api_client.create_disclosure_event(payload, officer.headers))


def decide_disclosure(officer: Actor, event_id: str, decision: str, **overrides):
    return api_client.decide_disclosure_event(
        event_id, decide_disclosure_payload(decision, **overrides), officer.headers
    )


def set_consent(client_id: str, value: str, headers: Optional[Dict[str, str]] = None):
    return api_client.change_consent(
        client_id, change_consent_payload(value), headers or ADMIN_HEADERS
    )


def seed_protective_order_case(
    legal: Actor, client_id: str, **overrides
) -> Dict[str, Any]:
    payload = create_protective_order_case_payload(client_id, **overrides)
    return get_success_data(
        api_client.create_protective_order_case(payload, legal.headers)
    )


def file_case(
    legal: Actor,
    case_id: str,
    accompanying_advocate_id: str,
    hearing_start_utc: str = "2026-08-05T09:00:00Z",
    hearing_end_utc: str = "2026-08-05T10:00:00Z",
    **overrides,
):
    return api_client.file_protective_order_case(
        case_id,
        file_protective_order_payload(
            accompanying_advocate_id, hearing_start_utc, hearing_end_utc, **overrides
        ),
        legal.headers,
    )


def seed_filed_case(
    legal: Actor,
    client_id: str,
    accompanying_advocate_id: Optional[str] = None,
    hearing_start_utc: str = "2026-08-05T09:00:00Z",
    hearing_end_utc: str = "2026-08-05T10:00:00Z",
    **case_overrides,
) -> Dict[str, Any]:
    """Draft a petition and file it with a hearing window. Returns the FILED case."""
    case = seed_protective_order_case(legal, client_id, **case_overrides)
    return get_success_data(
        file_case(
            legal,
            case["id"],
            accompanying_advocate_id or legal.id,
            hearing_start_utc,
            hearing_end_utc,
        )
    )


def record_outcome(legal: Actor, case_id: str, outcome: str, **overrides):
    return api_client.record_protective_order_outcome(
        case_id, record_outcome_payload(outcome, **overrides), legal.headers
    )


def seed_denied_hmis_export_seal(
    advocate: Actor, officer: Actor, client_overrides: Optional[dict] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Deny an HMIS export, which is the other sealing condition. Returns (client, event)."""
    overrides = dict(client_overrides or {})
    overrides.setdefault("hmis_disclosure_consent", "DENIED")
    client = seed_client(advocate, **overrides)
    event = seed_disclosure_event(
        officer,
        client["id"],
        advocate.id,
        "HMIS_EXPORT",
        ["client_code", "household_size"],
    )
    event = get_success_data(
        decide_disclosure(
            officer,
            event["id"],
            "DENY",
            denial_reason="No signed consent for homeless-data-system participation.",
        )
    )
    return client, event
