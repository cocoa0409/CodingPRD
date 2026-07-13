"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted server with an empty database and the
logical clock reset to its startup default (2026-03-01T00:00:00Z). These helpers
build all preconditions from scratch using only PRD-declared endpoints, and use
get_success_data() (lenient) so setup failures surface as clear "setup failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_contact_payload,
    create_risk_screening_payload,
    create_safety_plan_payload,
    create_team_payload,
    create_dispatch_payload,
    create_center_payload,
    create_bed_referral_payload,
)
from .test_users import TEST_USERS

SUP = TEST_USERS["supervisor_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

# Screening input recipes that reach a target band under COMPREHENSIVE scoring
# (protective_factors 0). See PRD §3.2.
#   LOW:      ideation 0, plan 0                       -> score 0
#   MODERATE: ideation 1, plan 2                       -> score 11
#   HIGH:     ideation 0, plan 3                       -> score 12
#   IMMINENT: ideation 3, plan 3, means true           -> score 26
_BAND_INPUTS = {
    "LOW": dict(suicidal_ideation=0, plan_specificity=0, means_access=False, prior_attempts=0),
    "MODERATE": dict(suicidal_ideation=1, plan_specificity=2, means_access=False, prior_attempts=0),
    "HIGH": dict(suicidal_ideation=0, plan_specificity=3, means_access=False, prior_attempts=0),
    "IMMINENT": dict(suicidal_ideation=3, plan_specificity=3, means_access=True, prior_attempts=0),
}


# ─── Primitives ───────────────────────────────────────────────────────────────

def set_clock(iso, headers=SUP):
    return get_success_data(api_client.set_clock(iso, headers))


def create_contact(caller_key, channel="PHONE", headers=SUP, **overrides):
    """Create a Contact (status INTAKE). Returns the contact dict."""
    res = api_client.create_contact(
        create_contact_payload(channel=channel, caller_key=caller_key, **overrides), headers
    )
    return get_success_data(res)


def submit_screening(contact_id, screening_type="COMPREHENSIVE", headers=COUNSELOR, **inputs):
    """Submit a RiskScreening for a contact. Returns the screening dict."""
    res = api_client.create_risk_screening(
        create_risk_screening_payload(contact_id, screening_type=screening_type, **inputs), headers
    )
    return get_success_data(res)


def create_screened_contact(caller_key, band="HIGH", channel="PHONE"):
    """Create a contact and screen it to a target band (COMPREHENSIVE). Returns the
    re-fetched contact (status SCREENED, risk_band == band)."""
    contact = create_contact(caller_key, channel=channel)
    submit_screening(contact["id"], screening_type="COMPREHENSIVE", **_BAND_INPUTS[band])
    return get_success_data(api_client.get_contact(contact["id"], SUP))


def create_dispatch_pending_contact(caller_key, channel="PHONE"):
    """HIGH-band contact driven SCREENED -> DISPATCH_PENDING. Returns the contact dict."""
    contact = create_screened_contact(caller_key, band="HIGH", channel=channel)
    res = api_client.contact_state(contact["id"], {"to_status": "DISPATCH_PENDING"}, DISPATCHER)
    return get_success_data(res)


def create_de_escalation_contact(caller_key, channel="PHONE"):
    """MODERATE-band contact driven SCREENED -> DE_ESCALATION. Returns the contact dict."""
    contact = create_screened_contact(caller_key, band="MODERATE", channel=channel)
    res = api_client.contact_state(contact["id"], {"to_status": "DE_ESCALATION"}, COUNSELOR)
    return get_success_data(res)


def create_team(name="Test Team", capacity=1, status=None, **overrides):
    """Create a MobileCrisisTeam. Returns the team dict."""
    payload = create_team_payload(name=name, capacity=capacity, **overrides)
    if status is not None:
        payload["status"] = status
    return get_success_data(api_client.create_team(payload, SUP))


def create_center(name="Test Center", bed_capacity=1, accepted_acuities=None, status=None):
    """Create a CrisisCenter (ONLINE). Returns the center dict."""
    payload = create_center_payload(
        name=name, bed_capacity=bed_capacity, accepted_acuities=accepted_acuities
    )
    if status is not None:
        payload["status"] = status
    return get_success_data(api_client.create_center(payload, SUP))


def current_team_version(team_id):
    return get_success_data(api_client.get_team(team_id, DISPATCHER))["version"]


def current_center_version(center_id):
    return get_success_data(api_client.get_center(center_id, DISPATCHER))["version"]


# ─── Tier 2/3: composite scenarios ────────────────────────────────────────────

def create_active_safety_plan(contact_id):
    """Author a DRAFT safety plan for a contact and activate it. Returns the plan dict."""
    plan = get_success_data(
        api_client.create_safety_plan(create_safety_plan_payload(contact_id), COUNSELOR)
    )
    return get_success_data(
        api_client.safety_plan_state(plan["id"], {"to_status": "ACTIVE"}, COUNSELOR)
    )


def create_resolved_de_escalation_with_followup(caller_key, channel="PHONE"):
    """DE_ESCALATION contact with an ACTIVE safety plan, resolved to RESOLVED which
    schedules a FollowUpTask. Returns (contact, follow_up_task) with the task SCHEDULED."""
    contact = create_de_escalation_contact(caller_key, channel=channel)
    create_active_safety_plan(contact["id"])
    get_success_data(api_client.contact_state(contact["id"], {"to_status": "RESOLVED"}, COUNSELOR))
    tasks, _ = _list_data(api_client.list_follow_up_tasks(COUNSELOR, params={"contact_id": contact["id"]}))
    return contact, tasks[0]


def setup_dispatch(caller_key, team_kwargs=None, dispatch_kwargs=None):
    """DISPATCH_PENDING contact + on-shift team + one REQUESTED dispatch.
    Returns (contact, team, dispatch)."""
    team_kwargs = team_kwargs or {}
    dispatch_kwargs = dispatch_kwargs or {}
    contact = create_dispatch_pending_contact(caller_key)
    team = create_team(**team_kwargs)
    dispatch = get_success_data(api_client.create_dispatch(
        create_dispatch_payload(contact["id"], team["id"], team["version"], **dispatch_kwargs),
        DISPATCHER,
    ))
    return contact, team, dispatch


def setup_held_referral(caller_key, center_kwargs=None, referral_kwargs=None, dispatch_link=False):
    """DISPATCH_PENDING contact + ONLINE center + one HELD bed referral (which drives the
    contact to REFERRAL_PENDING). If dispatch_link, also create a REQUESTED dispatch and link
    it to the referral. Returns (contact, center, referral, dispatch_or_None)."""
    center_kwargs = center_kwargs or {}
    referral_kwargs = referral_kwargs or {}
    contact = create_dispatch_pending_contact(caller_key)
    dispatch = None
    if dispatch_link:
        team = create_team(name="Link Team")
        dispatch = get_success_data(api_client.create_dispatch(
            create_dispatch_payload(contact["id"], team["id"], team["version"]), DISPATCHER,
        ))
    center = create_center(**center_kwargs)
    payload_extra = dict(referral_kwargs)
    if dispatch is not None:
        payload_extra["mobile_dispatch_id"] = dispatch["id"]
    referral = get_success_data(api_client.create_bed_referral(
        create_bed_referral_payload(
            contact["id"], center["id"], current_center_version(center["id"]), **payload_extra
        ),
        DISPATCHER,
    ))
    return contact, center, referral, dispatch


def drive_dispatch_to_completed(dispatch_id):
    """Walk a REQUESTED dispatch through EN_ROUTE -> ON_SCENE -> COMPLETED. Returns the
    completed dispatch dict."""
    get_success_data(api_client.dispatch_state(dispatch_id, {"to_status": "EN_ROUTE"}, DISPATCHER))
    get_success_data(api_client.dispatch_state(
        dispatch_id, {"to_status": "ON_SCENE", "on_scene_acuity": "HIGH"}, DISPATCHER))
    return get_success_data(api_client.dispatch_state(dispatch_id, {"to_status": "COMPLETED"}, DISPATCHER))


def _list_data(response):
    """Return (data_list, meta) from a list response using the lenient validator."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
