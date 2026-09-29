"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success validator so that a broken
precondition surfaces as a setup failure rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CONTROL_DOMAIN_ORDER, DEFAULT_CLOCK
from .factories import (
    adverse_media_payload,
    beneficial_owner_payload,
    closure_plan_payload,
    control_assessment_payload,
    corridor,
    information_request_payload,
    jurisdiction_profile_payload,
    monitoring_profile_payload,
    next_jurisdiction_code,
    nested_relationship_payload,
    observation_payload,
    payment_instruction_payload,
    periodic_refresh_payload,
    questionnaire_payload,
    respondent_payload,
)
from .test_users import (
    ADMIN_ID,
    ANALYST_ID,
    COMMITTEE_ID,
    OFFICER_ID,
    RM_ID,
    TEST_USERS,
    make_admin_headers,
    make_analyst_headers,
    make_committee_headers,
    make_officer_headers,
    make_respondent_headers,
    make_rm_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["officer_headers"]
RM = TEST_USERS["rm_headers"]
COMMITTEE = TEST_USERS["committee_headers"]


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def set_clock(current_utc: str, headers=None) -> dict:
    """Replace the server's logical clock value."""
    return get_success_data(api.set_clock({"current_utc": current_utc}, headers or ADMIN))


def reset_clock() -> dict:
    return set_clock(DEFAULT_CLOCK)


# --------------------------------------------------------------------------
# reference data
# --------------------------------------------------------------------------

def new_jurisdiction(**overrides) -> dict:
    """Register one jurisdiction reference profile."""
    payload = jurisdiction_profile_payload(**overrides)
    return get_success_data(api.create_jurisdiction_profile(payload, ADMIN))


def sanctioned_jurisdiction(**overrides) -> dict:
    overrides.setdefault("sanctions_status", "COMPREHENSIVELY_SANCTIONED")
    return new_jurisdiction(**overrides)


def restricted_jurisdiction(**overrides) -> dict:
    overrides.setdefault("sanctions_status", "RESTRICTED")
    return new_jurisdiction(**overrides)


# --------------------------------------------------------------------------
# respondents
# --------------------------------------------------------------------------

def new_respondent(jurisdiction_code=None, **overrides) -> dict:
    """Onboard one respondent bank.  Creates a home jurisdiction when none given."""
    if jurisdiction_code is None:
        jurisdiction_code = new_jurisdiction()["jurisdiction_code"]
    payload = respondent_payload(jurisdiction_code, **overrides)
    return get_success_data(api.create_respondent(payload, RM))


def read_respondent(respondent_id, headers=None) -> dict:
    return get_success_data(api.get_respondent(respondent_id, headers or ANALYST))


def respondent_version(respondent_id) -> int:
    return read_respondent(respondent_id)["version"]


def verify_licensing(
    respondent_id, license_status="ACTIVE", regulator_standing="GOOD_STANDING", **overrides
) -> dict:
    payload = {"license_status": license_status, "regulator_standing": regulator_standing}
    payload.update(overrides)
    return get_success_data(api.verify_licensing(respondent_id, payload, ANALYST))


def licensed_respondent(jurisdiction_code=None, **overrides) -> dict:
    """Respondent moved from PROSPECT to DD_IN_PROGRESS by a clean verification."""
    respondent = new_respondent(jurisdiction_code, **overrides)
    verify_licensing(respondent["id"])
    return read_respondent(respondent["id"])


# --------------------------------------------------------------------------
# beneficial owners
# --------------------------------------------------------------------------

def add_owner(respondent_id, country_of_residence, headers=None, **overrides) -> dict:
    payload = beneficial_owner_payload(country_of_residence, **overrides)
    return get_success_data(
        api.create_beneficial_owner(respondent_id, payload, headers or ANALYST)
    )


def verify_owner(owner_id, action="VERIFY", headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.verify_owner(owner_id, payload, headers or ANALYST))


def add_verified_owner(respondent_id, country_of_residence, **overrides) -> dict:
    owner = add_owner(respondent_id, country_of_residence, **overrides)
    verify_owner(owner["id"])
    return get_success_data(api.get_beneficial_owner(owner["id"], ANALYST))


# --------------------------------------------------------------------------
# questionnaires and control assessments
# --------------------------------------------------------------------------

def open_questionnaire(respondent_id, version="WOLFSBERG_V1_4", headers=None, **overrides) -> dict:
    """Create a questionnaire, echoing the respondent's current version."""
    payload = questionnaire_payload(respondent_version(respondent_id), **overrides)
    payload["questionnaire_version"] = version
    return get_success_data(
        api.create_questionnaire(
            respondent_id, payload, headers or make_respondent_headers(respondent_id)
        )
    )


def add_control_rows(questionnaire_id, respondent_id, self_ratings=None) -> dict:
    """Add one control-assessment row per control domain.  Returns domain -> row."""
    ratings = {d: 3 for d in CONTROL_DOMAIN_ORDER}
    if self_ratings:
        ratings.update(self_ratings)
    headers = make_respondent_headers(respondent_id)
    rows = {}
    for domain in CONTROL_DOMAIN_ORDER:
        rows[domain] = get_success_data(
            api.create_control_assessment(
                questionnaire_id, control_assessment_payload(domain, ratings[domain]), headers
            )
        )
    return rows


def overlay_row(control_assessment_id, **fields) -> dict:
    return get_success_data(
        api.overlay_control_assessment(control_assessment_id, dict(fields), ANALYST)
    )


def submit_questionnaire(questionnaire_id, respondent_id) -> dict:
    return get_success_data(
        api.submit_questionnaire(questionnaire_id, {}, make_respondent_headers(respondent_id))
    )


def assess_questionnaire(questionnaire_id, variant, headers=None, **overrides) -> dict:
    payload = {"action": "ASSESS", "variant": variant}
    payload.update(overrides)
    return get_success_data(api.decide_assessment(questionnaire_id, payload, headers or ANALYST))


def return_questionnaire(questionnaire_id, headers=None, **overrides) -> dict:
    payload = {"action": "RETURN"}
    payload.update(overrides)
    return get_success_data(api.decide_assessment(questionnaire_id, payload, headers or ANALYST))


def assessed_questionnaire(
    respondent_id, variant="ONBOARDING_PROVISIONAL", version="WOLFSBERG_V1_4",
    self_ratings=None, overlays=None,
):
    """Full questionnaire lifecycle: create -> eight rows -> submit -> overlay -> assess.

    Returns (questionnaire, rows) where rows maps control domain to its row.
    """
    questionnaire = open_questionnaire(respondent_id, version=version)
    rows = add_control_rows(questionnaire["id"], respondent_id, self_ratings)
    submit_questionnaire(questionnaire["id"], respondent_id)
    for domain, fields in (overlays or {}).items():
        overlay_row(rows[domain]["id"], **fields)
    assessed = assess_questionnaire(questionnaire["id"], variant)
    for domain in list(rows):
        rows[domain] = get_success_data(api.get_control_assessment(rows[domain]["id"], ANALYST))
    return assessed, rows


def all_assessed_overlays(rating=3):
    """Overlay map giving every one of the eight control domains an assessed_rating."""
    return {d: {"assessed_rating": rating} for d in CONTROL_DOMAIN_ORDER}


# --------------------------------------------------------------------------
# scoring, committee decision, restriction
# --------------------------------------------------------------------------

def score_respondent(respondent_id, variant="ONBOARDING_PROVISIONAL", headers=None) -> dict:
    return get_success_data(
        api.assess_risk(respondent_id, {"variant": variant}, headers or ANALYST)
    )


def committee_decision(respondent_id, action="APPROVE", headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.decide_committee(respondent_id, payload, headers or COMMITTEE))


def restrict(respondent_id, reason="OFFICER_ACTION", headers=None, **overrides) -> dict:
    payload = {"action": "RESTRICT", "restriction_reason": reason}
    payload.update(overrides)
    return get_success_data(api.restrict_respondent(respondent_id, payload, headers or OFFICER))


def lift(respondent_id, headers=None, **overrides) -> dict:
    payload = {"action": "LIFT"}
    payload.update(overrides)
    return get_success_data(api.restrict_respondent(respondent_id, payload, headers or OFFICER))


def clear_screening(respondent_id, headers=None, **overrides) -> dict:
    payload = {"action": "CLEAR_SCREENING"}
    payload.update(overrides)
    return get_success_data(api.restrict_respondent(respondent_id, payload, headers or OFFICER))


# --------------------------------------------------------------------------
# Tier 2 / Tier 3: respondent lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_pending_committee(jurisdiction_code=None, self_ratings=None, **respondent_overrides):
    """Respondent walked all the way to dd_state PENDING_COMMITTEE.

    Returns a dict with the jurisdiction code, the respondent row, the verified
    owner, the ASSESSED questionnaire and its eight control rows.
    """
    if jurisdiction_code is None:
        jurisdiction_code = new_jurisdiction()["jurisdiction_code"]
    respondent = licensed_respondent(jurisdiction_code, **respondent_overrides)
    rid = respondent["id"]
    owner = add_verified_owner(rid, jurisdiction_code, owner_name="Sole Holder")
    questionnaire, rows = assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL", self_ratings=self_ratings
    )
    score_respondent(rid, "ONBOARDING_PROVISIONAL")
    return {
        "jurisdiction_code": jurisdiction_code,
        "respondent": read_respondent(rid),
        "owner": owner,
        "questionnaire": questionnaire,
        "rows": rows,
    }


def setup_approved_respondent(jurisdiction_code=None, self_ratings=None, **respondent_overrides):
    """Respondent driven through the committee to dd_state APPROVED.

    With the default eight self_ratings of 3 the control score is 60.00 and the
    respondent lands on risk_rating LOW, so payment_posture becomes OPEN.
    """
    bundle = setup_pending_committee(jurisdiction_code, self_ratings, **respondent_overrides)
    committee_decision(bundle["respondent"]["id"], "APPROVE")
    bundle["respondent"] = read_respondent(bundle["respondent"]["id"])
    return bundle


def setup_restricted_respondent(reason="OFFICER_ACTION", **kwargs):
    """Approved respondent then restricted by the officer lever."""
    bundle = setup_approved_respondent(**kwargs)
    restrict(bundle["respondent"]["id"], reason)
    bundle["respondent"] = read_respondent(bundle["respondent"]["id"])
    return bundle


# --------------------------------------------------------------------------
# nested relationships
# --------------------------------------------------------------------------

def add_nested(respondent_id, downstream_jurisdiction_code, headers=None, **overrides) -> dict:
    payload = nested_relationship_payload(downstream_jurisdiction_code, **overrides)
    return get_success_data(
        api.create_nested_relationship(respondent_id, payload, headers or ANALYST)
    )


def adjudicate_nested(nested_relationship_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(
        api.adjudicate_nested(nested_relationship_id, payload, headers or ANALYST)
    )


def read_nested(nested_relationship_id) -> dict:
    return get_success_data(api.get_nested_relationship(nested_relationship_id, ANALYST))


def setup_confirmed_nested(depth_jurisdiction=None, **kwargs):
    """Approved respondent with nested_activity_permitted and one CONFIRMED edge."""
    kwargs.setdefault("nested_activity_permitted", True)
    bundle = setup_approved_respondent(**kwargs)
    rid = bundle["respondent"]["id"]
    code = depth_jurisdiction or new_jurisdiction()["jurisdiction_code"]
    row = add_nested(rid, code, discovery_source="QUESTIONNAIRE")
    adjudicate_nested(row["id"], "CONFIRM")
    bundle["nested"] = read_nested(row["id"])
    bundle["downstream_jurisdiction_code"] = code
    bundle["respondent"] = read_respondent(rid)
    return bundle


# --------------------------------------------------------------------------
# monitoring profiles, calibration and observations
# --------------------------------------------------------------------------

def open_profile(respondent_id, corridors, headers=None, **overrides) -> dict:
    payload = monitoring_profile_payload(
        respondent_version(respondent_id), corridors, **overrides
    )
    return get_success_data(
        api.create_monitoring_profile(respondent_id, payload, headers or ANALYST)
    )


def calibrate(monitoring_profile_id, headers=None, **overrides) -> dict:
    payload = {"action": "CALIBRATE"}
    payload.update(overrides)
    return get_success_data(
        api.calibrate_profile(monitoring_profile_id, payload, headers or ANALYST)
    )


def read_profile(monitoring_profile_id) -> dict:
    return get_success_data(api.get_monitoring_profile(monitoring_profile_id, ANALYST))


def setup_calibrated_profile(
    corridors=None, corridor_usd=2000000.00, corridor_count=400, profile_overrides=None, **kwargs
):
    """Approved respondent plus one CALIBRATED monitoring profile covering the
    default logical clock instant.

    Returns the approved-respondent bundle extended with `profile` and
    `corridor_code`.
    """
    bundle = setup_approved_respondent(**kwargs)
    rid = bundle["respondent"]["id"]
    if corridors is None:
        corridor_code = new_jurisdiction(corridor_risk_weight=1.25)["jurisdiction_code"]
        corridors = [corridor(corridor_code, corridor_usd, corridor_count)]
    else:
        corridor_code = corridors[0]["jurisdiction_code"]
    profile = open_profile(rid, corridors, **(profile_overrides or {}))
    calibrate(profile["id"])
    bundle["profile"] = read_profile(profile["id"])
    bundle["corridor_code"] = corridor_code
    bundle["respondent"] = read_respondent(rid)
    return bundle


def post_observation(monitoring_profile_id, period_month, corridor_code, headers=None, **overrides):
    payload = observation_payload(period_month, corridor_code, **overrides)
    return get_success_data(
        api.create_observation(monitoring_profile_id, payload, headers or ANALYST)
    )


def raise_alert(respondent_id, alert_type, severity, headers=None, **overrides) -> dict:
    payload = {"alert_type": alert_type, "severity": severity}
    payload.update(overrides)
    return get_success_data(
        api.create_monitoring_alert(respondent_id, payload, headers or OFFICER)
    )


def dispose_alert(alert_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.dispose_alert(alert_id, payload, headers or ANALYST))


def read_alert(alert_id) -> dict:
    return get_success_data(api.get_monitoring_alert(alert_id, ANALYST))


def alerts_for(respondent_id, **filters) -> list:
    params = {"respondent_bank_id": respondent_id, "limit": 100}
    params.update(filters)
    return get_success_data(api.list_monitoring_alerts(ANALYST, params=params))


# --------------------------------------------------------------------------
# information requests
# --------------------------------------------------------------------------

def raise_request(respondent_id, headers=None, **overrides) -> dict:
    payload = information_request_payload(**overrides)
    return get_success_data(
        api.create_information_request(respondent_id, payload, headers or ANALYST)
    )


def dispatch_request(request_id, headers=None) -> dict:
    return get_success_data(api.dispatch_request(request_id, {}, headers or ANALYST))


def respond_request(request_id, respondent_id, note="Here is our answer.") -> dict:
    return get_success_data(
        api.respond_request(
            request_id, {"response_note": note}, make_respondent_headers(respondent_id)
        )
    )


def maintain_request(request_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.mark_overdue(request_id, payload, headers or ANALYST))


def adjudicate_request(request_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.adjudicate_request(request_id, payload, headers or ANALYST))


def read_request(request_id) -> dict:
    return get_success_data(api.get_information_request(request_id, ANALYST))


def setup_sent_request(severity="HIGH", topic="OWNERSHIP_EVIDENCE", bundle=None, **kwargs):
    """Approved respondent with one information request dispatched into SENT."""
    bundle = bundle or setup_approved_respondent(**kwargs)
    request = raise_request(
        bundle["respondent"]["id"], request_topic=topic, severity=severity
    )
    dispatch_request(request["id"])
    bundle["request"] = read_request(request["id"])
    bundle["respondent"] = read_respondent(bundle["respondent"]["id"])
    return bundle


# --------------------------------------------------------------------------
# adverse media
# --------------------------------------------------------------------------

def log_media(respondent_id, headers=None, **overrides) -> dict:
    payload = adverse_media_payload(**overrides)
    return get_success_data(
        api.create_adverse_media_event(respondent_id, payload, headers or ANALYST)
    )


def triage_media(event_id, action, headers=None) -> dict:
    return get_success_data(api.triage_media(event_id, {"action": action}, headers or ANALYST))


def read_media(event_id) -> dict:
    return get_success_data(api.get_adverse_media_event(event_id, ANALYST))


def confirmed_media(respondent_id, **overrides) -> dict:
    event = log_media(respondent_id, **overrides)
    triage_media(event["id"], "CONFIRM")
    return read_media(event["id"])


# --------------------------------------------------------------------------
# periodic refreshes and the sweep
# --------------------------------------------------------------------------

def schedule_refresh(respondent_id, window_start, scheduled_due_date, headers=None, **overrides):
    payload = periodic_refresh_payload(window_start, scheduled_due_date, **overrides)
    return get_success_data(
        api.create_periodic_refresh(respondent_id, payload, headers or ANALYST)
    )


def progress_refresh(refresh_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.progress_refresh(refresh_id, payload, headers or ANALYST))


def read_refresh(refresh_id) -> dict:
    return get_success_data(api.get_periodic_refresh(refresh_id, ANALYST))


def run_sweep(dry_run=False, headers=None):
    return get_success_data(api.run_sweep({"dry_run": dry_run}, headers or ADMIN))


def setup_in_progress_refresh(
    window_start="2026-08-01T00:00:00Z", scheduled_due_date="2026-10-30T00:00:00Z",
    bundle=None, **kwargs
):
    """Approved respondent with one refresh cycle walked into IN_PROGRESS."""
    bundle = bundle or setup_approved_respondent(**kwargs)
    rid = bundle["respondent"]["id"]
    cycle = schedule_refresh(rid, window_start, scheduled_due_date)
    progress_refresh(cycle["id"], "START")
    bundle["cycle"] = read_refresh(cycle["id"])
    bundle["respondent"] = read_respondent(rid)
    return bundle


# --------------------------------------------------------------------------
# payment instructions
# --------------------------------------------------------------------------

def submit_payment(respondent_id, ordering_code, beneficiary_code, headers=None, **overrides):
    payload = payment_instruction_payload(ordering_code, beneficiary_code, **overrides)
    return get_success_data(
        api.create_payment_instruction(respondent_id, payload, headers or RM)
    )


def decide_payment(payment_id, action, decision_reason, headers=None, **overrides) -> dict:
    payload = {"action": action, "decision_reason": decision_reason}
    payload.update(overrides)
    return get_success_data(api.decide_screening(payment_id, payload, headers or OFFICER))


def read_payment(payment_id) -> dict:
    return get_success_data(api.get_payment_instruction(payment_id, OFFICER))


def payments_for(respondent_id, **filters) -> list:
    params = {"respondent_bank_id": respondent_id, "limit": 100}
    params.update(filters)
    return get_success_data(api.list_payment_instructions(OFFICER, params=params))


# --------------------------------------------------------------------------
# closure plans
# --------------------------------------------------------------------------

def draft_plan(respondent_id, headers=None, **overrides) -> dict:
    payload = closure_plan_payload(**overrides)
    return get_success_data(api.create_closure_plan(respondent_id, payload, headers or RM))


def submit_plan(plan_id, headers=None) -> dict:
    return get_success_data(api.submit_closure_plan(plan_id, {}, headers or RM))


def approve_plan(plan_id, action="APPROVE", headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.approve_closure_plan(plan_id, payload, headers or COMMITTEE))


def progress_plan(plan_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(api.progress_closure_plan(plan_id, payload, headers or RM))


def allocate(plan_id, amount_cents, action="ALLOCATE", headers=None) -> dict:
    return get_success_data(
        api.allocate_settlement(
            plan_id, {"action": action, "amount_cents": amount_cents}, headers or RM
        )
    )


def read_plan(plan_id) -> dict:
    return get_success_data(api.get_closure_plan(plan_id, RM))


def setup_approved_plan(bundle=None, plan_overrides=None, **kwargs):
    """Approved respondent carrying a closure plan walked to state APPROVED.

    The plan is drafted by the relationship manager and approved by the
    committee, so the drafter and the approver are different identities.
    """
    bundle = bundle or setup_approved_respondent(**kwargs)
    rid = bundle["respondent"]["id"]
    plan = draft_plan(rid, **(plan_overrides or {}))
    submit_plan(plan["id"])
    approve_plan(plan["id"])
    bundle["plan"] = read_plan(plan["id"])
    bundle["respondent"] = read_respondent(rid)
    return bundle
