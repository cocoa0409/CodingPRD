"""Deep cascades (archive depth-3, deactivate depth-2) and branching state machines."""
from test_helpers import (
    validate_success,
    create_client,
    create_campaign,
    create_outlet,
    create_journalist,
    create_spokesperson,
    create_media_list_current,
    create_pitch,
    create_pitch_in_state,
    create_interview,
    create_crisis_event,
    setup_campaign_with_media_list,
    TEST_USERS,
)
from test_helpers import api_client

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]


# =========================================================================== #
# transitive_cascade / campaign_archive_depth3_medialist_pitch_interview
# =========================================================================== #

def _build_archive_cascade_scenario():
    """DRAFT campaign + ACTIVE media list + DRAFT pitch + REQUESTED interview anchored on it."""
    client = create_client()
    campaign = create_campaign(client["id"])  # stays DRAFT
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"])
    media_list = create_media_list_current(campaign["id"], [journalist["id"]], name="Cas List")
    pitch = create_pitch(campaign["id"], media_list["id"], journalist["id"], angle="casc angle")
    spokesperson = create_spokesperson(client["id"], full_name="Spoke Cas", title="CEO")
    interview = create_interview(
        campaign["id"], spokesperson["id"], journalist["id"],
        "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z", pitch_id=pitch["id"],
    )
    return campaign, media_list, pitch, interview


def test_archive_cascades_medialist_pitch_interview(api):
    """PRD §3.7: "At the first level, every media list belonging to the campaign whose `status`
    is `ACTIVE` or `EXHAUSTED` is moved to `ARCHIVED`. At the second level, each media list
    moving to `ARCHIVED` cascades to its pitches: every pitch on that list whose `status` is
    `DRAFT`, `SENT`, or `RESPONDED` is moved to `CANCELLED`. At the third level, each pitch
    moving to `CANCELLED` cascades to its interviews: every interview anchored to that pitch
    whose `status` is `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`, which frees the
    spokesperson's slot."

    Design: Difficulty/transitive_cascade/campaign_archive_depth3_medialist_pitch_interview
    """
    campaign, media_list, pitch, interview = _build_archive_cascade_scenario()

    archived = validate_success(api.archive_campaign(campaign["id"], AM))
    assert archived["status"] == "ARCHIVED"

    assert validate_success(api.get_media_list(media_list["id"], MS))["status"] == "ARCHIVED"
    assert validate_success(api.get_pitch(pitch["id"], MS))["status"] == "CANCELLED"
    assert validate_success(api.get_interview(interview["id"], SC))["status"] == "CANCELLED"


def test_archive_cascade_bumps_child_versions(api):
    """PRD §2.5: "This holds for cascade-induced transitions just as it does for the directly
    requested one — a child swept into a new state by a parent's transition has its own
    `updated_at` and `version` updated."

    Each cascaded child (media list, pitch, interview) has its version incremented beyond
    its create-time value of 1.

    Design: Difficulty/transitive_cascade/campaign_archive_depth3_medialist_pitch_interview
    """
    campaign, media_list, pitch, interview = _build_archive_cascade_scenario()
    assert media_list["version"] == 1 and pitch["version"] == 1 and interview["version"] == 1

    validate_success(api.archive_campaign(campaign["id"], AM))

    ml = validate_success(api.get_media_list(media_list["id"], MS))
    p = validate_success(api.get_pitch(pitch["id"], MS))
    iv = validate_success(api.get_interview(interview["id"], SC))
    assert ml["version"] > 1, "cascaded media list version must increment"
    assert p["version"] > 1, "cascaded pitch version must increment"
    assert iv["version"] > 1, "cascaded interview version must increment"


# =========================================================================== #
# transitive_cascade / spokesperson_deactivate_depth2_interview_pitch_revert
# =========================================================================== #

def _build_deactivate_cascade_scenario():
    """ACTIVE campaign + ACCEPTED pitch + ACTIVE spokesperson + REQUESTED interview anchored on it."""
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "ACCEPTED")
    spokesperson = create_spokesperson(scn["client"]["id"], full_name="Spoke Theta", title="CFO")
    interview = create_interview(
        scn["campaign"]["id"], spokesperson["id"], scn["journalist"]["id"],
        "2026-04-12T14:00:00Z", "2026-04-12T15:00:00Z", pitch_id=pitch["id"],
    )
    return spokesperson, interview, pitch


def test_deactivate_cancels_interview_and_reverts_accepted_pitch(api):
    """PRD §3.6: "First, every interview for that spokesperson in `REQUESTED` or `CONFIRMED` is
    cancelled (advancing to `CANCELLED`), freeing the spokesperson's calendar slot. Then,
    for each such cancelled interview that carried a `pitch_id` whose pitch is currently
    `ACCEPTED`, that pitch is reverted from `ACCEPTED` back to `RESPONDED` as compensation,
    so the pitch can be re-accepted and re-anchored to a fresh interview later."

    Design: Difficulty/transitive_cascade/spokesperson_deactivate_depth2_interview_pitch_revert
    """
    spokesperson, interview, pitch = _build_deactivate_cascade_scenario()

    deactivated = validate_success(api.deactivate_spokesperson(spokesperson["id"], AM))
    assert deactivated["status"] == "INACTIVE"

    assert validate_success(api.get_interview(interview["id"], SC))["status"] == "CANCELLED"
    assert validate_success(api.get_pitch(pitch["id"], MS))["status"] == "RESPONDED", \
        "accepted pitch must revert to RESPONDED as compensation"


def test_reverted_pitch_can_be_reaccepted(api):
    """PRD §3.6: "that pitch is reverted from `ACCEPTED` back to `RESPONDED` as compensation,
    so the pitch can be re-accepted and re-anchored to a fresh interview later."

    After deactivation reverts the pitch to RESPONDED, accepting it again advances it back
    to ACCEPTED — proving the revert restores a re-acceptable RESPONDED state.

    Design: Difficulty/transitive_cascade/spokesperson_deactivate_depth2_interview_pitch_revert
    """
    spokesperson, interview, pitch = _build_deactivate_cascade_scenario()
    validate_success(api.deactivate_spokesperson(spokesperson["id"], AM))
    assert validate_success(api.get_pitch(pitch["id"], MS))["status"] == "RESPONDED"

    reaccepted = validate_success(api.accept_pitch(pitch["id"], MS))
    assert reaccepted["status"] == "ACCEPTED"


# =========================================================================== #
# non_linear_state_machine / crisis_event_parallel_severity_and_response_dimensions
# =========================================================================== #

def test_escalate_advances_severity_leaving_response_untouched(api):
    """PRD §3.12: "Each dimension's transition affects only that dimension and leaves the other
    untouched."
    PRD §3.12: "Escalating advances `ASSESSING` to `ESCALATED`, but only when the event's
    `severity` is `HIGH` or `CRITICAL`; an escalate on a `LOW` or `MEDIUM` crisis is
    rejected with `ERR_SEVERITY_TOO_LOW`."

    Design: Difficulty/non_linear_state_machine/crisis_event_parallel_severity_and_response_dimensions
    """
    crisis = create_crisis_event(severity="HIGH", holding_statement="We are investigating.")
    assert crisis["severity_status"] == "ASSESSING"
    assert crisis["response_status"] == "DRAFTING"

    escalated = validate_success(api.escalate_crisis(crisis["id"], AM))
    assert escalated["severity_status"] == "ESCALATED"
    assert escalated["response_status"] == "DRAFTING", \
        "escalating the severity dimension must leave response_status unchanged"


def test_response_dimension_advances_independently_of_severity(api):
    """PRD §3.12: "Approving the response advances `DRAFTING` to `APPROVED`, but only when the
    event has a non-null `holding_statement`; if no holding statement is present the approve
    is rejected with `ERR_NO_HOLDING_STATEMENT`."
    PRD §3.12: "Each dimension's transition affects only that dimension and leaves the other
    untouched."

    Approving then publishing the response dimension advances response_status while
    severity_status stays at its initial ASSESSING value.

    Design: Difficulty/non_linear_state_machine/crisis_event_parallel_severity_and_response_dimensions
    """
    crisis = create_crisis_event(severity="HIGH", holding_statement="Holding text.")
    approved = validate_success(api.approve_response_crisis(crisis["id"], AM))
    assert approved["response_status"] == "APPROVED"
    assert approved["severity_status"] == "ASSESSING", \
        "approving the response dimension must leave severity_status unchanged"

    published = validate_success(api.publish_response_crisis(crisis["id"], AM))
    assert published["response_status"] == "PUBLISHED"
    assert published["severity_status"] == "ASSESSING"


# =========================================================================== #
# non_linear_state_machine / pitch_branch_responded_to_accepted_or_rejected
# =========================================================================== #

def test_pitch_fork_accept_vs_reject_divergent_outcomes(api):
    """PRD §3.4: "From `RESPONDED`, the pitch forks into two mutually exclusive branches.
    Accepting it advances `RESPONDED` to `ACCEPTED`; an accepted pitch becomes eligible to
    anchor an interview, meaning an interview create may reference it. Rejecting it advances
    `RESPONDED` to `REJECTED`, which is terminal."

    Two RESPONDED pitches on one list: accept one (ACCEPTED), reject the other (REJECTED);
    the list stays ACTIVE because the accepted pitch keeps open count above zero.

    Design: Difficulty/non_linear_state_machine/pitch_branch_responded_to_accepted_or_rejected
    """
    scn = setup_campaign_with_media_list()
    pitch_a = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED",
        angle="angle A")
    pitch_b = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED",
        angle="angle B")

    accepted = validate_success(api.accept_pitch(pitch_a["id"], MS))
    rejected = validate_success(api.reject_pitch(pitch_b["id"], MS))
    assert accepted["status"] == "ACCEPTED"
    assert rejected["status"] == "REJECTED"

    media_list = validate_success(api.get_media_list(scn["media_list"]["id"], MS))
    assert media_list["status"] == "ACTIVE", \
        "list stays ACTIVE while an ACCEPTED pitch keeps the open count > 0"


def test_rejected_pitch_is_terminal(api):
    """PRD §3.4: "Rejecting it advances `RESPONDED` to `REJECTED`, which is terminal."

    A REJECTED pitch cannot be accepted afterward (terminal); the accept attempt is an
    invalid transition.

    Design: Difficulty/non_linear_state_machine/pitch_branch_responded_to_accepted_or_rejected
    """
    from test_helpers import validate_error, ApiErrorId
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED")
    rejected = validate_success(api.reject_pitch(pitch["id"], MS))
    assert rejected["status"] == "REJECTED"

    resp = api.accept_pitch(pitch["id"], MS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
