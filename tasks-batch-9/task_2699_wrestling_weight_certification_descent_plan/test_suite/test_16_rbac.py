"""
Role-based access control: the endpoint role table, the two entity-backed
identities, and the ownership boundary they draw.

Three separate gates live in this family, and the requirements document pins the
order they run in (§2.8): header authentication first, then endpoint role
authorization (`ERR_UNAUTHORIZED`), then path-identifier existence, then body
foreign-key existence, then resource ownership (`ERR_NOT_RESOURCE_OWNER`), and
only afterwards any shape, state or domain rule.

The role check is a pure table lookup against the authorized-role list §4
declares for each path, and §2.1 states it is evaluated "before any resource in
the URL is looked up".  Ownership is a different question entirely and only
arises for the two entity-backed roles: "When `X-User-Role` is `Assessor`,
`X-User-ID` is the `id` of the acting `Assessor` row" and "When `X-User-Role` is
`TeamCoach`, `X-User-ID` is the `id` of the acting `Team`" (§2.1), while
`StateOffice`, `WeighInOfficial` and `MedicalReviewer` are opaque principals the
server "never compares ... to any entity's `id`".  Holding the right role is
therefore necessary but not sufficient: a peer coach and a peer assessor are
refused as non-owners on calls their role otherwise owns.

The mirror image is exercised too — the three endpoints §4 lists for more than
one role, plus the all-role wrestler read, behave identically whichever
permitted role issues them.
"""

from typing import Any, Callable, Dict

import pytest
import requests

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    assert_row_count,
    assert_severity_ledger,
    assert_weight_equals,
)
from test_helpers.constants import (
    ALL_ROLES,
    APPEAL_DENIED,
    APPEAL_RETEST_ORDERED,
    APPEAL_UNDER_REVIEW,
    ASSESSMENT_DAY_INSTANT,
    ASSESSMENT_DRAFT,
    ASSESSMENT_VALIDATED,
    CANON_MEASURED_WEIGHT_LBS,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_FAIL,
    DEFAULT_WRESTLER_NAME,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_ENTERED,
    ENTRY_WEIGHED_IN,
    EVENT_TYPE_TOURNAMENT,
    FLAG_ESCALATED,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    METHOD_BIA,
    METHOD_SKINFOLD,
    OUTCOME_CLEARED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    PLAN_START_DATE,
    ROLE_ASSESSOR,
    ROLE_MEDICAL_REVIEWER,
    ROLE_STATE_OFFICE,
    ROLE_TEAM_COACH,
    ROLE_WEIGH_IN_OFFICIAL,
    SECOND_TEAM_NAME,
    SEX_MALE,
    VARIANT_WEEKLY_STEP,
    WEEKLY_STEP_SCHEDULE,
    WEIGH_IN_PASS,
    WRESTLER_CERTIFIED,
    WRESTLER_DISQUALIFIED,
    WRESTLER_PROVISIONAL,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import (
    MEDICAL_REVIEWER,
    STATE_OFFICE,
    STATE_OFFICE_USER_ID,
    WEIGH_IN_OFFICIAL,
    WEIGH_IN_OFFICIAL_USER_ID,
    assessor_headers,
    coach_headers,
)

# ── Shared literals ──────────────────────────────────────────────────
EVENT_NAME = "State Qualifier"
EVENT_DATE = "2026-12-12"

# A second, dry reading on the same UTC calendar day as the canonical one: the
# assessor's daily capacity defaults to three, so two readings sit inside it, and
# a specific gravity strictly above the season's 1.025 ceiling takes the
# hydration-failure arm, which raises a severity-1 `OPEN` flag (§3.3).
DRY_ASSESSED_AT = "2026-11-01T09:30:00Z"
DRY_MEASURED_WEIGHT_LBS = 158.0
HYDRATION_LEDGER_TOTAL = 1

# The third reading, never accepted: the probe that attempts to open an
# assessment as the state office.
REFUSED_ASSESSED_AT = "2026-11-01T10:00:00Z"
REFUSED_MEASURED_WEIGHT_LBS = 157.0
REFUSED_BODY_FAT_PCT = 13.9

# A syntactically valid identifier that matches no stored appeal.
UNKNOWN_APPEAL_ID = "00000000-0000-4000-8000-0000000000c1"

PEER_SEASON_NAME = "Coach's own season"
PEER_WRESTLER_NAME = "Rowan Diaz"
PEER_WRESTLER_GRADE = 10

ESCALATION_NOTE = "Rapid descent pattern; referred for disqualification review."
DISQUALIFICATION_REASON = "Unhealthy weight management on an escalated flag."


# ── The fixture the exclusive-operation probes all share ─────────────

def _season_with_a_draft_plan_and_an_open_flag(api: ApiClient) -> fixtures.Scenario:
    """The chain of §3.1 through §3.5, stopped at a `DRAFT` plan and an `OPEN` flag.

    A season is opened, a team registered, an assessor trained to the credential
    threshold, a wrestler rostered and measured, and a plan opened on the
    resulting validated assessment.  A second, dry reading then finalizes on the
    hydration-failure arm, which per §3.3 leaves the wrestler's
    `certification_status` untouched and raises a `HYDRATION_FAIL` flag of
    severity 1 in `OPEN` — the only way a flag ever comes into being, since §3.9
    states health flags "are never created by a client".  One event is scheduled
    so the seeding and entry paths have a target.
    """
    scenario = fixtures.assessed_wrestler(api)
    plan = fixtures.create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=VARIANT_WEEKLY_STEP,
    )
    dry = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=DRY_ASSESSED_AT,
        measured_weight_lbs=DRY_MEASURED_WEIGHT_LBS,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, dry["id"], scenario.assessor_id)

    flags = fixtures.flags_of_wrestler(api, scenario.wrestler_id, FLAG_OPEN)
    assert len(flags) == 1, "the dry reading raises exactly one flag"
    assert flags[0]["source"] == FLAG_HYDRATION_FAIL

    event = fixtures.create_event(
        api, scenario.season_id, EVENT_NAME, EVENT_DATE, EVENT_TYPE_TOURNAMENT
    )
    scenario.update(
        plan=plan,
        plan_id=plan["id"],
        dry_assessment_id=dry["id"],
        flag=flags[0],
        flag_id=flags[0]["id"],
        event=event,
        event_id=event["id"],
    )
    return scenario


# ── One probe per exclusive operation, issued by a role that lacks it ──

def _season_create_as_coach(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """`POST /seasons` is listed for `StateOffice` alone (§4)."""
    return api.create_season(factories.season_payload(name=PEER_SEASON_NAME), ctx.coach)


def _plan_certify_as_coach(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """Plan certification "belongs to the state office" (§3.5)."""
    return api.certify_descent_plan(ctx.plan_id, ctx.coach)


def _event_seed_as_official(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """"Seeding is a state-office act" (§3.8)."""
    return api.seed_event(ctx.event_id, WEIGH_IN_OFFICIAL)


def _flag_review_as_state_office(
    api: ApiClient, ctx: fixtures.Scenario
) -> requests.Response:
    """"Medical review belongs exclusively to `MedicalReviewer`" (§3.9)."""
    return api.review_health_flag(
        ctx.flag_id,
        factories.flag_review_payload(FLAG_ESCALATED, ESCALATION_NOTE),
        STATE_OFFICE,
    )


def _disqualification_as_medical_reviewer(
    api: ApiClient, ctx: fixtures.Scenario
) -> requests.Response:
    """"Disqualification ... is reserved to `StateOffice`"; the physician may not (§3.9)."""
    return api.disqualify_wrestler(
        ctx.wrestler_id,
        factories.disqualification_payload(ctx.flag_id, DISQUALIFICATION_REASON),
        MEDICAL_REVIEWER,
    )


def _finalize_as_coach(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """`POST /assessments/{id}/finalize` is listed for `Assessor` alone (§4)."""
    return api.finalize_assessment(ctx.assessment_id, ctx.coach)


def _entry_create_as_official(
    api: ApiClient, ctx: fixtures.Scenario
) -> requests.Response:
    """"Entering a wrestler is exclusive to `TeamCoach`" (§3.7)."""
    return api.create_entry(
        ctx.event_id,
        factories.entry_payload(ctx.wrestler_id, CANON_TARGET_CLASS_LBS, 1),
        WEIGH_IN_OFFICIAL,
    )


def _assessment_open_as_state_office(
    api: ApiClient, ctx: fixtures.Scenario
) -> requests.Response:
    """"Opening an assessment is exclusive to the `Assessor` role" (§3.3)."""
    return api.create_assessment(
        ctx.wrestler_id,
        factories.assessment_payload(
            assessor_id=ctx.assessor_id,
            method=METHOD_SKINFOLD,
            assessed_at=REFUSED_ASSESSED_AT,
            measured_weight_lbs=REFUSED_MEASURED_WEIGHT_LBS,
            body_fat_pct=REFUSED_BODY_FAT_PCT,
        ),
        STATE_OFFICE,
    )


def _compliance_run_as_medical_reviewer(
    api: ApiClient, ctx: fixtures.Scenario
) -> requests.Response:
    """The season compliance run is triggered by "a state-office operator" (§3.6)."""
    return api.run_compliance(ctx.season_id, MEDICAL_REVIEWER)


_EXCLUSIVE_PROBES: Dict[str, Callable[[ApiClient, fixtures.Scenario], requests.Response]] = {
    "season_create_attempted_by_a_coach": _season_create_as_coach,
    "plan_certification_attempted_by_a_coach": _plan_certify_as_coach,
    "bracket_seeding_attempted_by_a_weigh_in_official": _event_seed_as_official,
    "flag_review_attempted_by_the_state_office": _flag_review_as_state_office,
    "disqualification_attempted_by_the_physician": _disqualification_as_medical_reviewer,
    "assessment_finalize_attempted_by_a_coach": _finalize_as_coach,
    "competition_entry_attempted_by_a_weigh_in_official": _entry_create_as_official,
    "assessment_open_attempted_by_the_state_office": _assessment_open_as_state_office,
    "compliance_run_attempted_by_the_physician": _compliance_run_as_medical_reviewer,
}


@pytest.mark.parametrize("probe_name", list(_EXCLUSIVE_PROBES))
def test_exclusive_operation_refused_for_a_role_that_does_not_own_it(api, probe_name):
    """Every exclusive operation is 403 `ERR_UNAUTHORIZED` for an outsider role.

    §2.1: "When both headers are well formed but the named role is not among the
    roles authorized for the endpoint being called, the refusal is
    `ERR_UNAUTHORIZED` (HTTP 403)."  Each probe here names an operation §3 or the
    §4 routing table assigns to exactly one role and issues it as a different,
    well-formed role, so nothing but the role table can explain the refusal — the
    identity headers are valid, the paths resolve, and the resources are all in
    the from-state their operation wants.

    Design: Corner/rbac/exclusive_operations_rejected_for_every_other_role
    """
    ctx = _season_with_a_draft_plan_and_an_open_flag(api)

    response = _EXCLUSIVE_PROBES[probe_name](api, ctx)
    validate_error(response, api_errors.ERR_UNAUTHORIZED, 403)


def test_role_refusal_outranks_the_unresolvable_appeal_in_the_path(api):
    """A retest order from a coach is 403, not 404, even for an appeal that does not exist.

    §2.1 states that authentication and authorization "are evaluated before any
    resource in the URL is looked up", and §2.8 puts endpoint role authorization
    at the second position and path-identifier existence only at the third.
    `POST /appeals/{id}/order-retest` is listed for `Assessor` alone, so a
    `TeamCoach` caller is refused with `ERR_UNAUTHORIZED` and never reaches the
    `ERR_APPEAL_NOT_FOUND` the missing identifier would otherwise produce.

    Design: Corner/rbac/exclusive_operations_rejected_for_every_other_role
    """
    ctx = _season_with_a_draft_plan_and_an_open_flag(api)

    response = api.order_appeal_retest(UNKNOWN_APPEAL_ID, ctx.coach)
    validate_error(response, api_errors.ERR_UNAUTHORIZED, 403)
    assert response.json()["data"]["error_id"] != api_errors.ERR_APPEAL_NOT_FOUND


def test_health_and_safety_pipeline_needs_both_the_physician_and_the_state_office(api):
    """Neither role can drive escalation and disqualification by itself.

    §3.9 splits the safety workflow in two: "Escalation of a health flag belongs
    to this role alone; disqualification does not" for `MedicalReviewer`, and
    "Disqualification for unhealthy weight management is reserved to
    `StateOffice`, and this is the segregation of duties at the heart of the
    safety workflow: the physician who escalates cannot disqualify, and the state
    office cannot disqualify without a physician's escalation."  Each half of the
    pipeline is therefore refused with `ERR_UNAUTHORIZED` for the other role, and
    accepted for its own.

    Design: Corner/rbac/exclusive_operations_rejected_for_every_other_role
    """
    ctx = _season_with_a_draft_plan_and_an_open_flag(api)

    # The state office may not escalate, and the refusal records nothing.
    validate_error(
        api.review_health_flag(
            ctx.flag_id,
            factories.flag_review_payload(FLAG_ESCALATED, ESCALATION_NOTE),
            STATE_OFFICE,
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    flag = fixtures.read_flag(api, ctx.flag_id)
    assert flag["status"] == FLAG_OPEN
    assert flag["reviewer_user_id"] is None
    assert flag["review_note"] is None

    # The physician escalates: §3.9 keeps the severity inside the ledger.
    escalated = validate_success(
        api.review_health_flag(
            ctx.flag_id,
            factories.flag_review_payload(FLAG_ESCALATED, ESCALATION_NOTE),
            MEDICAL_REVIEWER,
        ),
        200,
    )
    assert escalated["status"] == FLAG_ESCALATED
    assert_severity_ledger(
        fixtures.read_team(api, ctx.team_id),
        HYDRATION_LEDGER_TOTAL,
        "team after the escalation",
    )

    # The physician may not then disqualify on the flag they escalated.
    validate_error(
        api.disqualify_wrestler(
            ctx.wrestler_id,
            factories.disqualification_payload(ctx.flag_id, DISQUALIFICATION_REASON),
            MEDICAL_REVIEWER,
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    wrestler = fixtures.read_wrestler(api, ctx.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["disqualified_at"] is None
    assert wrestler["certification_hold_reason"] is None

    # The state office may, on the strength of that escalation.
    disqualified = validate_success(
        api.disqualify_wrestler(
            ctx.wrestler_id,
            factories.disqualification_payload(ctx.flag_id, DISQUALIFICATION_REASON),
            STATE_OFFICE,
        ),
        200,
    )
    assert disqualified["certification_status"] == WRESTLER_DISQUALIFIED
    assert disqualified["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert disqualified["certification_hold_reason"] == DISQUALIFICATION_REASON
    assert_instant_equals(
        disqualified["disqualified_at"], ASSESSMENT_DAY_INSTANT, "disqualified_at"
    )


def test_refused_exclusive_operations_leave_every_row_exactly_as_it_was(api):
    """Nine role refusals in a row mutate nothing at all.

    A refusal at the second position of the §2.8 precedence order happens before
    any state machine is consulted, so none of the transitions attempted here
    lands: the plan stays `DRAFT` (§3.5 makes certification the only `DRAFT →
    CERTIFIED` route), the flag stays `OPEN` with its severity still in the
    team's ledger (§2.9), the wrestler stays `PROVISIONAL` — the hydration-failure
    arm "left unchanged" state of §3.3 — the event keeps the `entry_count` of 0 it
    was scheduled with (§3.7), the season's `certified_wrestler_count` is still 0
    because only plan certification increments it (§3.5), and the refused
    assessment open created no row, leaving the two readings the fixture recorded.

    Design: Corner/rbac/exclusive_operations_rejected_for_every_other_role
    """
    ctx = _season_with_a_draft_plan_and_an_open_flag(api)

    for probe in _EXCLUSIVE_PROBES.values():
        validate_error(probe(api, ctx), api_errors.ERR_UNAUTHORIZED, 403)

    plan = fixtures.read_plan(api, ctx.plan_id)
    assert plan["status"] == PLAN_DRAFT
    assert plan["milestone_count"] == 0
    assert plan["total_weeks"] is None
    assert_row_count(
        api.list_plan_milestones(ctx.plan_id, STATE_OFFICE, {"limit": 100}),
        0,
        "milestones of the still-draft plan",
    )

    flag = fixtures.read_flag(api, ctx.flag_id)
    assert flag["status"] == FLAG_OPEN
    assert_severity_ledger(
        fixtures.read_team(api, ctx.team_id),
        HYDRATION_LEDGER_TOTAL,
        "team after the refusals",
    )

    wrestler = fixtures.read_wrestler(api, ctx.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert wrestler["disqualified_at"] is None

    event = fixtures.read_event(api, ctx.event_id)
    assert event["entry_count"] == 0
    assert event["seeded_entry_count"] == 0
    assert event["bracket_locked"] is False
    assert_row_count(
        api.list_entries(STATE_OFFICE, {"event_id": ctx.event_id}),
        0,
        "entries of the event",
    )

    season = get_success_data(api.get_season(ctx.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0

    assert_row_count(
        api.list_assessments(STATE_OFFICE, {"wrestler_id": ctx.wrestler_id}),
        2,
        "assessments of the wrestler",
    )


# ── The peer coach: right role, wrong team ───────────────────────────

def _two_teams_one_assessed_wrestler(api: ApiClient) -> fixtures.Scenario:
    """One season, two rival teams, and a measured wrestler on the first of them.

    Both coaches hold the same `TeamCoach` role, so every difference in outcome
    below comes from the ownership comparison of §2.1 alone: "`X-User-ID` is the
    `id` of the acting `Team`".  The wrestler is left `PROVISIONAL` on a validated
    assessment, which is a legal starting point for a plan, an appeal and an
    entry alike.
    """
    scenario = fixtures.open_season_with_team(api)
    peer_team = fixtures.create_team(api, scenario.season_id, SECOND_TEAM_NAME)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    assessment = fixtures.create_validated_assessment(
        api, wrestler["id"], assessor["id"]
    )
    event = fixtures.create_event(
        api, scenario.season_id, EVENT_NAME, EVENT_DATE, EVENT_TYPE_TOURNAMENT
    )
    scenario.update(
        peer_team=peer_team,
        peer_team_id=peer_team["id"],
        peer_coach=coach_headers(peer_team["id"]),
        assessor=assessor,
        assessor_id=assessor["id"],
        wrestler=fixtures.read_wrestler(api, wrestler["id"]),
        wrestler_id=wrestler["id"],
        assessment=assessment,
        assessment_id=assessment["id"],
        event=event,
        event_id=event["id"],
    )
    return scenario


def _peer_plan_open(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """A coach may "only open or revise descent plans for their own wrestlers" (§2.1)."""
    return api.create_descent_plan(
        ctx.wrestler_id,
        factories.descent_plan_payload(
            source_assessment_id=ctx.assessment_id,
            target_class_lbs=CANON_TARGET_CLASS_LBS,
            plan_start_date=PLAN_START_DATE,
            expected_wrestler_version=fixtures.wrestler_version(api, ctx.wrestler_id),
            plan_variant=VARIANT_WEEKLY_STEP,
        ),
        ctx.peer_coach,
    )


def _peer_appeal_filing(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """The body carries the rival's own team, which §3.4 still refuses.

    "The supplied `team_id` must equal the caller's `X-User-ID` and must also be
    the team that owns the contested assessment's wrestler; either mismatch is
    `ERR_NOT_RESOURCE_OWNER`."  Here the first half holds and the second fails.
    """
    return api.create_appeal(
        ctx.assessment_id,
        factories.appeal_payload(ctx.peer_team_id, "Rival coach disputes the reading."),
        ctx.peer_coach,
    )


def _peer_entry_create(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """A coach may "only enter their own wrestlers in competitions" (§2.1)."""
    return api.create_entry(
        ctx.event_id,
        factories.entry_payload(ctx.wrestler_id, CANON_TARGET_CLASS_LBS, 1),
        ctx.peer_coach,
    )


def _peer_roster_write(api: ApiClient, ctx: fixtures.Scenario) -> requests.Response:
    """"A coach whose `X-User-ID` is not that team is refused" on a roster add (§3.1)."""
    return api.create_wrestler(
        ctx.team_id,
        factories.wrestler_payload(PEER_WRESTLER_NAME, SEX_MALE, PEER_WRESTLER_GRADE),
        ctx.peer_coach,
    )


_PEER_COACH_PROBES: Dict[str, Callable[[ApiClient, fixtures.Scenario], requests.Response]] = {
    "plan_opened_on_another_teams_wrestler": _peer_plan_open,
    "appeal_filed_against_another_teams_assessment": _peer_appeal_filing,
    "entry_created_for_another_teams_wrestler": _peer_entry_create,
    "wrestler_added_to_another_teams_roster": _peer_roster_write,
}


@pytest.mark.parametrize("probe_name", list(_PEER_COACH_PROBES))
def test_coach_write_across_the_team_boundary_is_refused_as_non_ownership(api, probe_name):
    """A rival coach is 403 `ERR_NOT_RESOURCE_OWNER`, never `ERR_UNAUTHORIZED`.

    §2.1 draws the line precisely: a `TeamCoach` "may only manage wrestlers whose
    `team_id` equals `X-User-ID`, only file appeals carrying their own `team_id`,
    only open or revise descent plans for their own wrestlers, and only enter
    their own wrestlers in competitions.  A violation is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."  The role is authorized for each of these endpoints, so the role
    gate passes and the ownership gate — position five of the §2.8 order — is what
    refuses; the two refusals share an HTTP status and are told apart only by
    `error_id`.

    Design: Corner/rbac/coach_cannot_reach_another_teams_wrestler
    """
    ctx = _two_teams_one_assessed_wrestler(api)

    response = _PEER_COACH_PROBES[probe_name](api, ctx)
    error = validate_error(response, api_errors.ERR_NOT_RESOURCE_OWNER, 403)
    assert error["error_id"] != api_errors.ERR_UNAUTHORIZED


def test_the_owning_coach_succeeds_where_the_rival_coach_was_refused(api):
    """The identical calls land for the team that owns the wrestler.

    Refusing the rival is an ownership decision, not a rejection of the request
    itself: with only the `X-User-ID` header changed to the owning team, the plan
    opens in `DRAFT` (§3.5) and the entry is accepted in `ENTERED` (§3.7).  The
    rival's four refusals left no trace either — the rival's own roster is still
    empty, and the event's `entry_count` counts exactly the one accepted entry.

    Design: Corner/rbac/coach_cannot_reach_another_teams_wrestler
    """
    ctx = _two_teams_one_assessed_wrestler(api)

    for probe in _PEER_COACH_PROBES.values():
        validate_error(probe(api, ctx), api_errors.ERR_NOT_RESOURCE_OWNER, 403)

    plan = validate_success(
        api.create_descent_plan(
            ctx.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=ctx.assessment_id,
                target_class_lbs=CANON_TARGET_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=fixtures.wrestler_version(
                    api, ctx.wrestler_id
                ),
                plan_variant=VARIANT_WEEKLY_STEP,
            ),
            ctx.coach,
        ),
        201,
    )
    assert plan["status"] == PLAN_DRAFT
    assert plan["wrestler_id"] == ctx.wrestler_id

    certified = fixtures.certify_plan(api, plan["id"])
    assert certified["status"] == PLAN_CERTIFIED
    assert fixtures.read_wrestler(api, ctx.wrestler_id)["certification_status"] == (
        WRESTLER_CERTIFIED
    )

    entry = validate_success(
        api.create_entry(
            ctx.event_id,
            factories.entry_payload(ctx.wrestler_id, CANON_TARGET_CLASS_LBS, 1),
            ctx.coach,
        ),
        201,
    )
    assert entry["status"] == ENTRY_ENTERED
    assert entry["wrestler_id"] == ctx.wrestler_id
    assert entry["weight_class_lbs"] == CANON_TARGET_CLASS_LBS

    assert fixtures.read_event(api, ctx.event_id)["entry_count"] == 1
    assert fixtures.read_team(api, ctx.team_id)["roster_count"] == 1
    assert fixtures.read_team(api, ctx.peer_team_id)["roster_count"] == 0
    assert_row_count(
        api.list_wrestlers(STATE_OFFICE, {"team_id": ctx.peer_team_id}),
        0,
        "the rival team's roster",
    )


# ── Assessor peers: the same role, three different dossiers ──────────

SECOND_ASSESSOR_NAME = "Priya Nair"
SECOND_CREDENTIAL_NUMBER = "AS-1002"
THIRD_ASSESSOR_NAME = "Owen Blake"
THIRD_CREDENTIAL_NUMBER = "AS-1003"
DECISION_NOTE = "Caliper reading confirmed against the dossier."


def _three_assessors_and_a_draft_assessment(api: ApiClient) -> fixtures.Scenario:
    """Three interchangeably credentialed assessors; the first has one draft open.

    All three clear the same credential bar of §3.2 — `CERTIFIED` status on
    `assessor_min_training_hours` of logged training — so nothing about
    qualification distinguishes them.  What distinguishes them is that §2.1 makes
    the `Assessor` role's `X-User-ID` "the `id` of the acting `Assessor` row", and
    the draft names the first of them as its `assessor_id`.
    """
    scenario = fixtures.open_season_with_team(api)
    first = fixtures.create_certified_assessor(api)
    second = fixtures.create_certified_assessor(
        api,
        full_name=SECOND_ASSESSOR_NAME,
        credential_number=SECOND_CREDENTIAL_NUMBER,
        certified_methods=[METHOD_SKINFOLD, METHOD_BIA],
    )
    third = fixtures.create_certified_assessor(
        api,
        full_name=THIRD_ASSESSOR_NAME,
        credential_number=THIRD_CREDENTIAL_NUMBER,
        certified_methods=[METHOD_SKINFOLD],
    )
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    draft = fixtures.create_assessment(api, wrestler["id"], first["id"])
    scenario.update(
        first_assessor_id=first["id"],
        second_assessor_id=second["id"],
        third_assessor_id=third["id"],
        wrestler_id=wrestler["id"],
        assessment=draft,
        assessment_id=draft["id"],
    )
    return scenario


def _appeal_under_review_by_the_second_assessor(api: ApiClient) -> fixtures.Scenario:
    """The draft is validated by its own assessor, appealed, and handed to a peer.

    Reviewer assignment is the state office's act (§3.4) and must not name the
    producing assessor, so the second assessor takes the file: the appeal sits in
    `UNDER_REVIEW` with `reviewing_assessor_id` pointing at them and
    `retest_round_count` still 0.
    """
    ctx = _three_assessors_and_a_draft_assessment(api)
    fixtures.finalize_assessment(api, ctx.assessment_id, ctx.first_assessor_id)
    appeal = fixtures.file_appeal(api, ctx.assessment_id, ctx.team_id)
    assert appeal["retest_round_count"] == 0
    appeal = fixtures.assign_reviewer(api, appeal["id"], ctx.second_assessor_id)
    assert appeal["status"] == APPEAL_UNDER_REVIEW
    assert appeal["reviewing_assessor_id"] == ctx.second_assessor_id
    ctx.update(appeal=appeal, appeal_id=appeal["id"])
    return ctx


def test_only_the_assessor_who_recorded_a_draft_may_finalize_it(api):
    """Two equally credentialed peers are refused; the recording assessor is not.

    §2.1 says of the `Assessor` role that "an assessment may only be opened with
    an `assessor_id` equal to the caller's `X-User-ID`, only that same assessor may
    finalize it".  The peers hold the authorized role, so their refusal is the
    ownership one, and it lands before the hydration fork of §3.3 runs: the draft
    is still `DRAFT` afterwards and the wrestler still carries the all-null
    certified figures §3.1 gives a fresh roster member.  The recording assessor's
    identical call then produces the worked figures of §3.3 and credits the
    validated reading to that assessor's dossier alone.

    Design: Corner/rbac/assessor_peers_cannot_finalize_or_review_each_others_work
    """
    ctx = _three_assessors_and_a_draft_assessment(api)

    for peer_id in (ctx.second_assessor_id, ctx.third_assessor_id):
        validate_error(
            api.finalize_assessment(ctx.assessment_id, assessor_headers(peer_id)),
            api_errors.ERR_NOT_RESOURCE_OWNER,
            403,
        )

    assert fixtures.read_assessment(api, ctx.assessment_id)["status"] == (
        ASSESSMENT_DRAFT
    )
    before = fixtures.read_wrestler(api, ctx.wrestler_id)
    assert before["certification_status"] == WRESTLER_UNCERTIFIED
    assert before["source_assessment_id"] is None
    assert before["minimum_certified_weight_lbs"] is None
    assert before["min_weight_class_lbs"] is None

    validated = validate_success(
        api.finalize_assessment(
            ctx.assessment_id, assessor_headers(ctx.first_assessor_id)
        ),
        200,
    )
    assert validated["status"] == ASSESSMENT_VALIDATED
    assert validated["assessor_id"] == ctx.first_assessor_id

    wrestler = fixtures.read_wrestler(api, ctx.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["source_assessment_id"] == ctx.assessment_id
    assert_weight_equals(
        wrestler["minimum_certified_weight_lbs"],
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "minimum certified weight",
    )
    assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS

    assert fixtures.read_assessor(api, ctx.first_assessor_id)[
        "validated_assessment_count"
    ] == 1
    for peer_id in (ctx.second_assessor_id, ctx.third_assessor_id):
        assert fixtures.read_assessor(api, peer_id)["validated_assessment_count"] == 0


def test_only_the_assigned_reviewer_may_order_a_retest(api):
    """An unassigned peer and the producing assessor are both refused as non-owners.

    §3.4: "the reviewer, and only the assessor whose `X-User-ID` matches
    `reviewing_assessor_id`, drives the retest cycle."  The refusal is the
    ownership one for both probes — the unassigned third assessor and the
    assessor who produced the contested reading — because the specification
    reserves `ERR_SAME_ASSESSOR_CONFLICT` for the reviewer-assignment step, whose
    `reviewing_assessor_id` is checked against the producing assessor there and
    nowhere else.  Neither refusal advances the cycle, and the assigned reviewer's
    identical call does: `retest_round_count` increments by one and the appeal
    lands in `RETEST_ORDERED`.

    Design: Corner/rbac/assessor_peers_cannot_finalize_or_review_each_others_work
    """
    ctx = _appeal_under_review_by_the_second_assessor(api)
    version_before = ctx.appeal["version"]

    for outsider_id in (ctx.third_assessor_id, ctx.first_assessor_id):
        validate_error(
            api.order_appeal_retest(ctx.appeal_id, assessor_headers(outsider_id)),
            api_errors.ERR_NOT_RESOURCE_OWNER,
            403,
        )

    unchanged = fixtures.read_appeal(api, ctx.appeal_id)
    assert unchanged["status"] == APPEAL_UNDER_REVIEW
    assert unchanged["retest_round_count"] == 0
    assert unchanged["retest_assessment_id"] is None
    assert unchanged["version"] == version_before

    ordered = validate_success(
        api.order_appeal_retest(
            ctx.appeal_id, assessor_headers(ctx.second_assessor_id)
        ),
        200,
    )
    assert ordered["status"] == APPEAL_RETEST_ORDERED
    assert ordered["retest_round_count"] == 1
    assert ordered["reviewing_assessor_id"] == ctx.second_assessor_id
    assert ordered["version"] == version_before + 1

    assert_row_count(
        api.list_appeals(STATE_OFFICE, {"assessment_id": ctx.assessment_id}),
        1,
        "appeals against the contested assessment",
    )


def test_only_the_assigned_reviewer_may_decide_the_appeal(api):
    """A peer cannot record the decision even when the outcome is a legal one.

    `DENIED` "is accepted out of `UNDER_REVIEW`" (§3.4), so the from-state gate
    would pass for either caller and only the reviewer comparison can refuse: both
    the unassigned peer and the producing assessor get `ERR_NOT_RESOURCE_OWNER`
    and the appeal keeps its null `decision_note`.  The assigned reviewer's
    decision is then recorded, and because it is a denial the contested
    assessment stays `VALIDATED` "with the wrestler's certified figures completely
    untouched".

    Design: Corner/rbac/assessor_peers_cannot_finalize_or_review_each_others_work
    """
    ctx = _appeal_under_review_by_the_second_assessor(api)

    for outsider_id in (ctx.third_assessor_id, ctx.first_assessor_id):
        validate_error(
            api.decide_appeal(
                ctx.appeal_id,
                factories.appeal_decision_payload(APPEAL_DENIED, DECISION_NOTE),
                assessor_headers(outsider_id),
            ),
            api_errors.ERR_NOT_RESOURCE_OWNER,
            403,
        )

    pending = fixtures.read_appeal(api, ctx.appeal_id)
    assert pending["status"] == APPEAL_UNDER_REVIEW
    assert pending["decision_note"] is None

    decided = validate_success(
        api.decide_appeal(
            ctx.appeal_id,
            factories.appeal_decision_payload(APPEAL_DENIED, DECISION_NOTE),
            assessor_headers(ctx.second_assessor_id),
        ),
        200,
    )
    assert decided["status"] == APPEAL_DENIED
    assert decided["decision_note"] == DECISION_NOTE

    assert fixtures.read_assessment(api, ctx.assessment_id)["status"] == (
        ASSESSMENT_VALIDATED
    )
    wrestler = fixtures.read_wrestler(api, ctx.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert_weight_equals(
        wrestler["minimum_certified_weight_lbs"],
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "minimum certified weight after the denial",
    )
    assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS


# ── Shared operations: several roles, one identical outcome ───────────

SECOND_WRESTLER_NAME = "Bailey Novak"
SECOND_WRESTLER_GRADE = 12
SECOND_ASSESSED_AT = "2026-11-01T10:00:00Z"

# Weigh-in day is the event date itself, which is day index zero.
WEIGH_IN_INSTANT = "2026-12-12T07:00:00Z"

# A reading at or under the entered class limit, and above the certified minimum
# of 147.6, so §3.8's first comparison settles it as `PASS` and `below_minimum`
# stays false.  Day index zero "earns nothing", so the allowance is 0.0 and the
# effective limit is the bare class limit.
SCALE_READING_LBS = 149.5
EXPECTED_ALLOWANCE_LBS = 0.0
EXPECTED_EFFECTIVE_LIMIT_LBS = 150.0

# The governing plan's last milestone due on or before the event date is week
# five of the weekly-step progression, which is the greatest of the two floor
# candidates and still selects the 150 class.
SCHEDULE_ALLOWABLE_LBS = WEEKLY_STEP_SCHEDULE[5]
EXPECTED_LOWEST_ELIGIBLE_CLASS_LBS = 150
EXPECTED_GROWTH_ALLOWANCE_LBS = 0.0


def _second_certified_wrestler(
    api: ApiClient, ctx: fixtures.Scenario
) -> Dict[str, Any]:
    """Put a second wrestler of the same team through the same certification chain."""
    wrestler = get_success_data(
        api.create_wrestler(
            ctx.team_id,
            factories.wrestler_payload(
                SECOND_WRESTLER_NAME, SEX_MALE, SECOND_WRESTLER_GRADE
            ),
            STATE_OFFICE,
        )
    )
    assessment = fixtures.create_validated_assessment(
        api, wrestler["id"], ctx.assessor_id, assessed_at=SECOND_ASSESSED_AT
    )
    fixtures.create_certified_plan(
        api, wrestler["id"], ctx.team_id, assessment["id"]
    )
    return fixtures.read_wrestler(api, wrestler["id"])


def test_roster_write_accepted_from_both_the_owning_coach_and_the_state_office(api):
    """§3.1's two listed roles both add wrestlers, and the rows are indistinguishable.

    "Adding a wrestler to a roster may be done by that team's own `TeamCoach` or by
    `StateOffice`", and "the new wrestler's `team_id` is taken from the roster
    being written to" — the writer's identity is not stored on the row and does not
    change it.  Both adds increment the same `roster_count`, and both wrestlers
    then run the assessment arithmetic of §3.3 to the same certified figures, so
    the certification pipeline is indifferent to which permitted role created the
    row.

    Design: Corner/rbac/shared_operations_accepted_for_every_listed_role
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)

    by_coach = validate_success(
        api.create_wrestler(
            scenario.team_id,
            factories.wrestler_payload(DEFAULT_WRESTLER_NAME, SEX_MALE, 11),
            scenario.coach,
        ),
        201,
    )
    assert by_coach["team_id"] == scenario.team_id
    assert by_coach["certification_status"] == WRESTLER_UNCERTIFIED
    assert fixtures.read_team(api, scenario.team_id)["roster_count"] == 1

    by_state_office = validate_success(
        api.create_wrestler(
            scenario.team_id,
            factories.wrestler_payload(
                SECOND_WRESTLER_NAME, SEX_MALE, SECOND_WRESTLER_GRADE
            ),
            STATE_OFFICE,
        ),
        201,
    )
    assert by_state_office["team_id"] == scenario.team_id
    assert by_state_office["certification_status"] == WRESTLER_UNCERTIFIED

    # The coach's own read of the team sees both rows on the one roster.
    team = get_success_data(api.get_team(scenario.team_id, scenario.coach))
    assert team["roster_count"] == 2
    assert_row_count(
        api.list_wrestlers(scenario.coach, {"team_id": scenario.team_id}),
        2,
        "the team's roster",
    )

    fixtures.create_validated_assessment(api, by_coach["id"], assessor["id"])
    fixtures.create_validated_assessment(
        api, by_state_office["id"], assessor["id"], assessed_at=SECOND_ASSESSED_AT
    )

    for wrestler_id in (by_coach["id"], by_state_office["id"]):
        wrestler = fixtures.read_wrestler(api, wrestler_id)
        assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
        assert_weight_equals(
            wrestler["alpha_weight_lbs"], CANON_MEASURED_WEIGHT_LBS, "alpha weight"
        )
        assert_weight_equals(
            wrestler["minimum_certified_weight_lbs"],
            CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
            "minimum certified weight",
        )
        assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS


def test_eligibility_check_accepted_from_every_listed_role_with_one_verdict(api):
    """The informational class-floor check gives all three listed roles the same answer.

    §3.7 makes the arithmetic "a standalone, purely informational operation
    available to `StateOffice`, `TeamCoach` and `WeighInOfficial`" that "always
    succeeds with HTTP 201, logging a check row rather than rejecting on any
    business rule".  Each caller's four pinned steps run identically: no
    allowances were published, the governing certified plan's latest milestone due
    on or before the event date supplies the week-five allowable weight, that
    value exceeds the certified minimum and so becomes the floor, and the class it
    selects ties the unadjusted hard-floor class.  With the requested class not
    below that and nothing blocking the wrestler, the verdict is `CLEARED` with a
    null `blocking_error_id` for all three.  Every call logs its own row.

    Design: Corner/rbac/shared_operations_accepted_for_every_listed_role
    """
    scenario = fixtures.certified_wrestler(api)
    event = fixtures.create_event(
        api, scenario.season_id, EVENT_NAME, EVENT_DATE, EVENT_TYPE_TOURNAMENT
    )

    callers = {
        ROLE_STATE_OFFICE: STATE_OFFICE,
        ROLE_TEAM_COACH: scenario.coach,
        ROLE_WEIGH_IN_OFFICIAL: WEIGH_IN_OFFICIAL,
    }
    logged_ids = []
    for role, headers in callers.items():
        check = validate_success(
            api.create_eligibility_check(
                scenario.wrestler_id,
                factories.eligibility_check_payload(
                    event["id"], EXPECTED_LOWEST_ELIGIBLE_CLASS_LBS
                ),
                headers,
            ),
            201,
        )
        assert check["outcome"] == OUTCOME_CLEARED, role
        assert check["blocking_error_id"] is None, role
        assert check["wrestler_id"] == scenario.wrestler_id, role
        assert check["event_id"] == event["id"], role
        assert check["as_of_date"] == EVENT_DATE, role
        assert check["requested_class_lbs"] == EXPECTED_LOWEST_ELIGIBLE_CLASS_LBS, role
        assert check["lowest_eligible_class_lbs"] == (
            EXPECTED_LOWEST_ELIGIBLE_CLASS_LBS
        ), role
        assert_weight_equals(
            check["growth_allowance_lbs"], EXPECTED_GROWTH_ALLOWANCE_LBS, role
        )
        assert_weight_equals(
            check["schedule_allowable_weight_lbs"], SCHEDULE_ALLOWABLE_LBS, role
        )
        logged_ids.append(check["id"])

    assert len(set(logged_ids)) == 3, "each call logs its own check row"
    assert_row_count(
        api.list_eligibility_checks(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_id}
        ),
        3,
        "logged eligibility checks",
    )

    # The check refreshes the wrestler's own copy of the figure.
    assert fixtures.read_wrestler(api, scenario.wrestler_id)[
        "lowest_eligible_class_lbs"
    ] == EXPECTED_LOWEST_ELIGIBLE_CLASS_LBS


def test_weigh_in_accepted_from_both_listed_roles_with_identical_arithmetic(api):
    """"Recording a weigh-in may be done by the `WeighInOfficial` ... or by `StateOffice`".

    Two entries of the same event and class are weighed on the same day with the
    same scale reading, one by each listed role.  §3.8's allowance arithmetic and
    its three ordered comparisons never consult the caller, so both readings come
    back with an identical `allowance_lbs`, `effective_limit_lbs` and `result`, and
    both advance their entry `ENTERED → WEIGHED_IN`.  The single trace the caller
    leaves is `official_user_id`, which "records the acting operator's opaque
    `X-User-ID`" and therefore differs between the two rows.

    Design: Corner/rbac/shared_operations_accepted_for_every_listed_role
    """
    scenario = fixtures.certified_wrestler(api)
    second_wrestler = _second_certified_wrestler(api, scenario)
    event = fixtures.create_event(
        api, scenario.season_id, EVENT_NAME, EVENT_DATE, EVENT_TYPE_TOURNAMENT
    )
    first_entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=5,
    )
    second_entry = fixtures.create_entry(
        api,
        event["id"],
        second_wrestler["id"],
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=3,
    )
    fixtures.move_clock(api, WEIGH_IN_INSTANT)
    fixtures.open_weigh_ins(api, event["id"])

    by_official = validate_success(
        api.create_weigh_in(
            event["id"],
            factories.weigh_in_payload(first_entry["id"], 0, SCALE_READING_LBS),
            WEIGH_IN_OFFICIAL,
        ),
        201,
    )
    by_state_office = validate_success(
        api.create_weigh_in(
            event["id"],
            factories.weigh_in_payload(second_entry["id"], 0, SCALE_READING_LBS),
            STATE_OFFICE,
        ),
        201,
    )

    for reading in (by_official, by_state_office):
        assert reading["result"] == WEIGH_IN_PASS
        assert reading["below_minimum"] is False
        assert reading["day_index"] == 0
        assert_weight_equals(
            reading["allowance_lbs"], EXPECTED_ALLOWANCE_LBS, "allowance"
        )
        assert_weight_equals(
            reading["effective_limit_lbs"],
            EXPECTED_EFFECTIVE_LIMIT_LBS,
            "effective limit",
        )
        assert_weight_equals(
            reading["recorded_weight_lbs"], SCALE_READING_LBS, "scale reading"
        )
        assert_instant_equals(reading["recorded_at"], WEIGH_IN_INSTANT, "recorded_at")

    assert by_official["official_user_id"] == WEIGH_IN_OFFICIAL_USER_ID
    assert by_state_office["official_user_id"] == STATE_OFFICE_USER_ID
    assert by_official["wrestler_id"] == scenario.wrestler_id
    assert by_state_office["wrestler_id"] == second_wrestler["id"]

    for entry_id in (first_entry["id"], second_entry["id"]):
        entry = fixtures.read_entry(api, entry_id)
        assert entry["status"] == ENTRY_WEIGHED_IN
        assert_weight_equals(
            entry["latest_effective_weight_lbs"],
            SCALE_READING_LBS,
            "latest effective weight",
        )

    assert fixtures.read_event(api, event["id"])["weighed_in_count"] == 2
    assert_row_count(
        api.list_health_flags(STATE_OFFICE, {"wrestler_id": scenario.wrestler_id}),
        0,
        "flags of the first wrestler",
    )


def test_wrestler_read_agrees_across_all_five_roles(api):
    """The wrestler read is listed for every role, and every role sees the same row.

    §4 opens `GET /wrestlers/{id}` to all five role names, and the certification
    record it returns is a single stored row rather than a per-caller projection:
    the reads are compared field by field and must be identical, showing the
    `CERTIFIED`/`ELIGIBLE` pair a certified plan produces (§3.5) together with the
    worked figures of §3.3.

    Design: Corner/rbac/shared_operations_accepted_for_every_listed_role
    """
    scenario = fixtures.certified_wrestler(api)
    headers_by_role = {
        ROLE_STATE_OFFICE: STATE_OFFICE,
        ROLE_ASSESSOR: assessor_headers(scenario.assessor_id),
        ROLE_TEAM_COACH: scenario.coach,
        ROLE_WEIGH_IN_OFFICIAL: WEIGH_IN_OFFICIAL,
        ROLE_MEDICAL_REVIEWER: MEDICAL_REVIEWER,
    }
    assert sorted(headers_by_role) == sorted(ALL_ROLES)

    reads = {}
    for role in ALL_ROLES:
        row = validate_success(
            api.get_wrestler(scenario.wrestler_id, headers_by_role[role]), 200
        )
        assert row["id"] == scenario.wrestler_id, role
        assert row["certification_status"] == WRESTLER_CERTIFIED, role
        assert row["eligibility_status"] == ELIGIBILITY_ELIGIBLE, role
        assert row["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS, role
        assert_weight_equals(
            row["minimum_certified_weight_lbs"],
            CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
            role,
        )
        reads[role] = row

    reference = reads[ROLE_STATE_OFFICE]
    for role, row in reads.items():
        assert row == reference, f"{role} saw a different row"
