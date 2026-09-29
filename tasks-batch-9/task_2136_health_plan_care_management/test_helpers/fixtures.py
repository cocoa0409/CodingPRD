"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only; nothing is carried over between tests. Setup calls use the
lenient validator so a broken precondition reports as a setup failure rather
than as a confusing assertion failure inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CADENCE_MULTIPLIER, TIER_POINTS
from .factories import (
    create_care_manager_payload, create_care_plan_payload,
    create_community_resource_payload, create_enrollment_payload,
    create_goal_payload, create_intervention_payload, create_member_payload,
    create_program_payload, create_referral_payload, create_social_need_payload,
    create_touch_payload, create_transition_event_payload,
)
from .test_users import (
    PROGRAM_ADMIN, UTILIZATION_ANALYST, make_care_manager_headers,
    make_clinical_reviewer_headers, make_community_partner_headers,
)


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(instant: str) -> str:
    """Move the logical clock; returns the reported current_utc."""
    data = get_success_data(api.set_clock(instant, PROGRAM_ADMIN))
    return data["current_utc"]


# ─── Reads ────────────────────────────────────────────────────────────────

def read_member(member_id: str) -> dict:
    return get_success_data(api.get_member(member_id, PROGRAM_ADMIN))


def read_program(program_id: str) -> dict:
    return get_success_data(api.get_program(program_id, PROGRAM_ADMIN))


def read_care_manager(care_manager_id: str) -> dict:
    return get_success_data(api.get_care_manager(care_manager_id, PROGRAM_ADMIN))


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api.get_enrollment(enrollment_id, PROGRAM_ADMIN))


def enrollment_version(enrollment_id: str) -> int:
    return read_enrollment(enrollment_id)["version"]


def read_care_plan(care_plan_id: str) -> dict:
    return get_success_data(api.get_care_plan(care_plan_id, PROGRAM_ADMIN))


def read_goal(goal_id: str) -> dict:
    return get_success_data(api.get_goal(goal_id, PROGRAM_ADMIN))


def read_touch(touch_id: str) -> dict:
    return get_success_data(api.get_touch(touch_id, PROGRAM_ADMIN))


def read_social_need(social_need_id: str) -> dict:
    return get_success_data(api.get_social_need(social_need_id, PROGRAM_ADMIN))


def read_community_resource(resource_id: str) -> dict:
    return get_success_data(api.get_community_resource(resource_id, PROGRAM_ADMIN))


def read_referral(referral_id: str) -> dict:
    return get_success_data(api.get_referral(referral_id, PROGRAM_ADMIN))


# ─── Tier 1: single-resource creation ─────────────────────────────────────

def create_member(**overrides) -> dict:
    return get_success_data(
        api.create_member(create_member_payload(**overrides), PROGRAM_ADMIN)
    )


def create_program(**overrides) -> dict:
    return get_success_data(
        api.create_program(create_program_payload(**overrides), PROGRAM_ADMIN)
    )


def create_care_manager(**overrides) -> dict:
    return get_success_data(
        api.create_care_manager(create_care_manager_payload(**overrides), PROGRAM_ADMIN)
    )


def record_event(member_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_transition_event(
            create_transition_event_payload(member_id, **overrides), PROGRAM_ADMIN
        )
    )


def stratify(member_id: str, variant: str = "CONCURRENT") -> dict:
    return get_success_data(
        api.create_stratification(member_id, {"variant": variant}, UTILIZATION_ANALYST)
    )


def set_consent(member_id: str, status: str, headers=None) -> dict:
    return get_success_data(
        api.set_member_consent(
            member_id, {"social_data_consent_status": status},
            headers or PROGRAM_ADMIN,
        )
    )


def register_resource(**overrides) -> dict:
    return get_success_data(
        api.create_community_resource(
            create_community_resource_payload(**overrides), PROGRAM_ADMIN
        )
    )


# ─── Tier 2: enrollment lifecycle ─────────────────────────────────────────

def enroll(member_id, program_id, care_manager_id=None, headers=None, **overrides):
    return get_success_data(
        api.create_enrollment(
            create_enrollment_payload(
                member_id, program_id, care_manager_id, **overrides
            ),
            headers or PROGRAM_ADMIN,
        )
    )


def activate(enrollment_id: str, headers=None) -> dict:
    return get_success_data(
        api.activate_enrollment(enrollment_id, headers or PROGRAM_ADMIN)
    )


def transfer(enrollment_id, to_care_manager_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = enrollment_version(enrollment_id)
    return get_success_data(
        api.transfer_enrollment(
            enrollment_id,
            {"to_care_manager_id": to_care_manager_id,
             "expected_enrollment_version": expected_version},
            PROGRAM_ADMIN,
        )
    )


def disenroll(enrollment_id, reason, headers=None) -> dict:
    return get_success_data(
        api.disenroll_enrollment(
            enrollment_id, {"reason": reason}, headers or PROGRAM_ADMIN
        )
    )


# ─── Tier 3: care plan lifecycle ──────────────────────────────────────────

def author_plan(enrollment_id, care_manager_id, title="Test care plan") -> dict:
    return get_success_data(
        api.create_care_plan(
            create_care_plan_payload(enrollment_id, title=title),
            make_care_manager_headers(care_manager_id),
        )
    )


def add_goal(care_plan_id, care_manager_id, **overrides) -> dict:
    return get_success_data(
        api.create_goal(
            care_plan_id, create_goal_payload(**overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def submit_plan(care_plan_id, care_manager_id) -> dict:
    return get_success_data(
        api.submit_care_plan(care_plan_id, make_care_manager_headers(care_manager_id))
    )


def review_plan(care_plan_id, reviewer_care_manager_id, decision="APPROVE",
                revision_note=None) -> dict:
    payload = {"decision": decision}
    if revision_note is not None:
        payload["revision_note"] = revision_note
    return get_success_data(
        api.review_care_plan(
            care_plan_id, payload,
            make_clinical_reviewer_headers(reviewer_care_manager_id),
        )
    )


def plan_intervention(goal_id, care_manager_id, **overrides) -> dict:
    return get_success_data(
        api.create_intervention(
            goal_id, create_intervention_payload(**overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def complete_intervention(intervention_id, care_manager_id) -> dict:
    return get_success_data(
        api.complete_intervention(
            intervention_id, make_care_manager_headers(care_manager_id)
        )
    )


def void_intervention(intervention_id, care_manager_id, void_reason) -> dict:
    return get_success_data(
        api.void_intervention(
            intervention_id, {"void_reason": void_reason},
            make_care_manager_headers(care_manager_id),
        )
    )


# ─── Tier 3: outreach ─────────────────────────────────────────────────────

def schedule_touch(enrollment_id, care_manager_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_touch(
            create_touch_payload(enrollment_id, care_manager_id, **overrides),
            headers if headers is not None else make_care_manager_headers(care_manager_id),
        )
    )


_UNSET = object()


def complete_touch(touch_id, care_manager_id, outcome="REACHED",
                   documentation_note=_UNSET) -> dict:
    """Complete a touch. A REACHED completion carries a contact note by
    default; a NOT_REACHED completion carries none unless one is passed."""
    payload = {"outcome": outcome}
    if documentation_note is _UNSET:
        if outcome == "REACHED":
            payload["documentation_note"] = "Contact documented."
    elif documentation_note is not None:
        payload["documentation_note"] = documentation_note
    return get_success_data(
        api.complete_touch(touch_id, payload, make_care_manager_headers(care_manager_id))
    )


def cancel_touch(touch_id, care_manager_id, cancel_reason="Member rescheduled.") -> dict:
    return get_success_data(
        api.cancel_touch(
            touch_id, {"cancel_reason": cancel_reason},
            make_care_manager_headers(care_manager_id),
        )
    )


# ─── Tier 3: social needs and referrals ───────────────────────────────────

def identify_social_need(enrollment_id, care_manager_id, **overrides) -> dict:
    return get_success_data(
        api.create_social_need(
            create_social_need_payload(enrollment_id, **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def send_referral(social_need_id, community_resource_id, care_manager_id,
                  **overrides) -> dict:
    return get_success_data(
        api.create_referral(
            create_referral_payload(
                social_need_id, community_resource_id, **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def decide_referral(referral_id, community_resource_id, decision="ACCEPT",
                    decline_reason=None) -> dict:
    payload = {"decision": decision}
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        api.decide_referral(
            referral_id, payload,
            make_community_partner_headers(community_resource_id),
        )
    )


def close_loop(referral_id, resolution, outcome_note, headers) -> dict:
    return get_success_data(
        api.close_referral_loop(
            referral_id,
            {"resolution": resolution, "outcome_note": outcome_note},
            headers,
        )
    )


def close_loop_as_partner(referral_id, community_resource_id, resolution,
                          outcome_note="Loop closed.") -> dict:
    return close_loop(referral_id, resolution, outcome_note,
                      make_community_partner_headers(community_resource_id))


def close_loop_as_care_manager(referral_id, care_manager_id, resolution,
                               outcome_note="Loop closed.") -> dict:
    return close_loop(referral_id, resolution, outcome_note,
                      make_care_manager_headers(care_manager_id))


def expected_acuity_weight(tier: str, cadence_tier: str) -> float:
    """PRD §3.3: tier points multiplied by the cadence multiplier, to one decimal."""
    return round(TIER_POINTS[tier] * CADENCE_MULTIPLIER[cadence_tier] + 1e-9, 1)


# ─── Tier 4: composite scenarios ──────────────────────────────────────────

def setup_program_and_managers(program_overrides=None, manager_overrides=None,
                               reviewer_overrides=None, with_reviewer=True) -> dict:
    """Create a program plus the care manager who will carry the caseload and,
    by default, a second care manager to act as the clinical reviewer.

    The reviewer must be a different person from the author, because a plan
    review by the plan's own author is refused for segregation of duties.
    """
    program = create_program(**(program_overrides or {}))
    credential = program["required_credential_levels"][0]

    manager_kwargs = {"full_name": "Rita Nolan", "credential_level": credential}
    manager_kwargs.update(manager_overrides or {})
    care_manager = create_care_manager(**manager_kwargs)

    reviewer = None
    if with_reviewer:
        reviewer_kwargs = {"full_name": "Dana Ruiz", "credential_level": credential}
        reviewer_kwargs.update(reviewer_overrides or {})
        reviewer = create_care_manager(**reviewer_kwargs)

    return {"program": program, "care_manager": care_manager, "reviewer": reviewer}


def setup_enrollment(program_overrides=None, manager_overrides=None,
                     reviewer_overrides=None, member_overrides=None,
                     events=None, with_reviewer=True, activate_it=True,
                     auto_assign=False, base=None) -> dict:
    """Program + care managers + member + stratification + enrollment.

    `events` is a list of transition-event override dicts recorded before the
    stratification runs, so their utilization points are inside the score.
    The stratification uses the program's own stratification_variant, which is
    the variant enrollment creation demands.
    """
    setting = base or setup_program_and_managers(
        program_overrides, manager_overrides, reviewer_overrides, with_reviewer
    )
    program = setting["program"]
    care_manager = setting["care_manager"]

    member = create_member(**(member_overrides or {}))
    for event in (events or []):
        record_event(member["id"], **event)

    stratification = stratify(member["id"], program["stratification_variant"])

    enrollment = enroll(
        member["id"], program["id"],
        None if auto_assign else care_manager["id"],
    )
    if activate_it:
        enrollment = activate(enrollment["id"])

    return {
        "program": program,
        "care_manager": care_manager,
        "reviewer": setting["reviewer"],
        "member": member,
        "stratification": stratification,
        "enrollment": enrollment,
    }


def setup_active_care_plan(goal_specs=None, plan_title="Test care plan",
                           **enrollment_kwargs) -> dict:
    """Everything setup_enrollment builds, carried on to an ACTIVE care plan.

    A plan reaches ACTIVE only through DRAFT → PENDING_REVIEW → ACTIVE, and a
    submission requires at least one goal and an ACTIVE enrollment, so the
    enrollment is always activated on this path.
    """
    enrollment_kwargs.setdefault("activate_it", True)
    scenario = setup_enrollment(**enrollment_kwargs)
    author_id = scenario["care_manager"]["id"]
    reviewer_id = scenario["reviewer"]["id"]

    plan = author_plan(scenario["enrollment"]["id"], author_id, title=plan_title)
    goals = []
    for spec in (goal_specs or [{"domain": "CLINICAL"}]):
        goals.append(add_goal(plan["id"], author_id, **spec))

    submit_plan(plan["id"], author_id)
    plan = review_plan(plan["id"], reviewer_id, "APPROVE")

    scenario["plan"] = plan
    scenario["goals"] = goals
    scenario["goal"] = goals[0] if goals else None
    scenario["enrollment"] = read_enrollment(scenario["enrollment"]["id"])
    return scenario


def setup_draft_care_plan(goal_specs=None, plan_title="Test care plan",
                          **enrollment_kwargs) -> dict:
    """A DRAFT care plan carrying its goals, left unsubmitted."""
    scenario = setup_enrollment(**enrollment_kwargs)
    author_id = scenario["care_manager"]["id"]
    plan = author_plan(scenario["enrollment"]["id"], author_id, title=plan_title)
    goals = [add_goal(plan["id"], author_id, **spec)
             for spec in (goal_specs or [{"domain": "CLINICAL"}])]
    scenario["plan"] = plan
    scenario["goals"] = goals
    scenario["goal"] = goals[0] if goals else None
    return scenario


def setup_discharge_escalated_enrollment(admission_occurred_at="2026-07-29T00:00:00Z",
                                         discharge_occurred_at="2026-08-01T00:00:00Z",
                                         **plan_kwargs) -> dict:
    """An ACTIVE enrollment with an ACTIVE plan whose member has just been
    discharged, so the transitions-of-care obligation is open.

    Returns the scenario dict extended with `admission_event`, `discharge_event`
    and the re-read `enrollment`.
    """
    scenario = setup_active_care_plan(**plan_kwargs)
    member_id = scenario["member"]["id"]

    admission = record_event(
        member_id, event_type="INPATIENT_ADMISSION",
        occurred_at=admission_occurred_at, episode_cost_cents=500000,
        adjudication_status="CLOSED",
    )
    discharge = record_event(
        member_id, event_type="DISCHARGE", occurred_at=discharge_occurred_at,
        episode_cost_cents=0, adjudication_status="CLOSED",
        discharge_disposition="HOME", index_admission_event_id=admission["id"],
    )

    scenario["admission_event"] = admission
    scenario["discharge_event"] = discharge
    scenario["enrollment"] = read_enrollment(scenario["enrollment"]["id"])
    return scenario


def setup_referral_scenario(resource_overrides=None, need_overrides=None,
                            goal_specs=None, **plan_kwargs) -> dict:
    """An ACTIVE enrollment with an ACTIVE plan, one registered community
    organization and one identified social need, ready for a referral."""
    plan_kwargs.setdefault(
        "program_overrides", {"required_credential_levels": ["CHW"]}
    )
    scenario = setup_active_care_plan(goal_specs=goal_specs, **plan_kwargs)
    scenario["resource"] = register_resource(**(resource_overrides or {}))
    scenario["social_need"] = identify_social_need(
        scenario["enrollment"]["id"], scenario["care_manager"]["id"],
        **(need_overrides or {}),
    )
    return scenario


def setup_completed_touch_history(touch_windows, outcomes, notes=None,
                                  **plan_kwargs) -> dict:
    """Book a run of touches on consecutive days and complete them in order,
    stepping the logical clock to each touch's start instant first.

    `touch_windows` is a list of (start, end) instant pairs and `outcomes` the
    matching list of REACHED / NOT_REACHED values. Returns the scenario dict
    extended with `touches` (all booked touches, in booking order).
    """
    scenario = setup_active_care_plan(**plan_kwargs)
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]

    touches = [
        schedule_touch(
            enrollment_id, care_manager_id,
            scheduled_start_at=start, scheduled_end_at=end,
        )
        for start, end in touch_windows
    ]

    for index, outcome in enumerate(outcomes):
        set_clock(touch_windows[index][0])
        note = None
        if notes and index < len(notes):
            note = notes[index]
        elif outcome == "REACHED":
            note = f"Outreach contact {index + 1} documented."
        complete_touch(touches[index]["id"], care_manager_id,
                       outcome=outcome, documentation_note=note)

    scenario["touches"] = touches
    scenario["enrollment"] = read_enrollment(enrollment_id)
    return scenario
