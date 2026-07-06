"""Boundary precision (reach cap, list-exhaustion) and cross-entity state dependencies."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_campaign_with_media_list,
    create_coverage,
    create_pitch,
    create_pitch_in_state,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]


# =========================================================================== #
# boundary_precision_check / reach_cap_min_boundary_on_coverage_verify
# =========================================================================== #

def test_reach_factor_exactly_at_cap_verified_value(api):
    """PRD §3.9: "Multiply by a reach factor equal to one plus the outlet's
    `monthly_unique_visitors` divided by one million, but cap that reach factor at 3.0 —
    that is, use the smaller of the computed reach factor and 3.0."

    ENTERPRISE / NATIONAL / MUV 2_000_000 (reach exactly 3.0) / DA 80 (auth 1.8) /
    POSITIVE / FEATURE: verified = 500000*3.0*1.8*1.0*1.0*1.5 = 4050000.

    Design: Difficulty/boundary_precision_check/reach_cap_min_boundary_on_coverage_verify
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(
        scn["campaign"]["id"], scn["journalist"]["id"],
        sentiment="POSITIVE", prominence="FEATURE",
    )
    verified = validate_success(api.verify_coverage(cov["id"], MS))
    assert verified["media_value_cents"] == 4050000, \
        f"reach exactly at cap should give 4050000, got {verified['media_value_cents']}"


def test_reach_at_cap_matches_value_above_cap(api):
    """PRD §3.9: "Multiply by a reach factor equal to one plus the outlet's
    `monthly_unique_visitors` divided by one million, but cap that reach factor at 3.0 —
    that is, use the smaller of the computed reach factor and 3.0."

    An outlet exactly at the cap (MUV 2_000_000, reach 3.0) and one above (MUV 2_500_000,
    reach uncapped 3.5) both clamp to 3.0, so both verify to the same 4050000 for an
    otherwise identical ENTERPRISE / NATIONAL / DA80 / POSITIVE / FEATURE clip.

    Design: Difficulty/boundary_precision_check/reach_cap_min_boundary_on_coverage_verify
    """
    at_cap = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov_at = create_coverage(at_cap["campaign"]["id"], at_cap["journalist"]["id"],
                             sentiment="POSITIVE", prominence="FEATURE")
    v_at = validate_success(api.verify_coverage(cov_at["id"], MS))

    above_cap = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2500000, "domain_authority": 80},
    )
    cov_above = create_coverage(above_cap["campaign"]["id"], above_cap["journalist"]["id"],
                                sentiment="POSITIVE", prominence="FEATURE")
    v_above = validate_success(api.verify_coverage(cov_above["id"], MS))

    assert v_at["media_value_cents"] == 4050000
    assert v_above["media_value_cents"] == 4050000, \
        "MUV above the cap must clamp to the same value as MUV exactly at the cap"


# =========================================================================== #
# boundary_precision_check / media_list_exhausted_at_zero_open_count_boundary
# =========================================================================== #

def test_media_list_exhausts_when_open_count_hits_zero_on_reject(api):
    """PRD §3.4: "For a given media list, count the pitches on it whose `status` is `DRAFT`,
    `SENT`, `RESPONDED`, or `ACCEPTED` — this is the list's open count. When a reject or a
    decline drops that open count to exactly zero, the media list auto-transitions from
    `ACTIVE` to `EXHAUSTED`."

    One RESPONDED pitch (open count 1); rejecting it drops the count to 0 -> EXHAUSTED.

    Design: Difficulty/boundary_precision_check/media_list_exhausted_at_zero_open_count_boundary
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED")
    rejected = validate_success(api.reject_pitch(pitch["id"], MS))
    assert rejected["status"] == "REJECTED"

    media_list = validate_success(api.get_media_list(scn["media_list"]["id"], MS))
    assert media_list["status"] == "EXHAUSTED", \
        f"list should be EXHAUSTED when open count hits 0, got {media_list['status']}"


def test_media_list_stays_active_when_open_count_is_one(api):
    """PRD §3.4: "The boundary is exact: an open count reaching zero triggers exhaustion, while
    an open count of one does not."

    Two RESPONDED pitches (open count 2); rejecting one leaves open count 1, so the list
    must remain ACTIVE (boundary X+1, not X).

    Design: Difficulty/boundary_precision_check/media_list_exhausted_at_zero_open_count_boundary
    """
    scn = setup_campaign_with_media_list()
    p1 = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED")
    p2 = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED")
    validate_success(api.reject_pitch(p1["id"], MS))

    media_list = validate_success(api.get_media_list(scn["media_list"]["id"], MS))
    assert media_list["status"] == "ACTIVE", \
        f"list should stay ACTIVE while open count is 1, got {media_list['status']}"
    # second reject drives it to zero -> EXHAUSTED
    validate_success(api.reject_pitch(p2["id"], MS))
    media_list = validate_success(api.get_media_list(scn["media_list"]["id"], MS))
    assert media_list["status"] == "EXHAUSTED"


# =========================================================================== #
# cross_entity_state_dependency / pitch_send_requires_campaign_active
# =========================================================================== #

def test_pitch_send_on_paused_campaign_rejected(api):
    """PRD §3.4: "Sending has three preconditions: the campaign must be `ACTIVE`, else
    `ERR_CAMPAIGN_NOT_ACTIVE`; the recipient journalist must be `ACTIVE`, else
    `ERR_JOURNALIST_BLOCKLISTED`; and the source media list must be `ACTIVE`, else
    `ERR_MEDIA_LIST_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/pitch_send_requires_campaign_active
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch(scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"])
    validate_success(api.pause_campaign(scn["campaign"]["id"], AM))

    resp = api.send_pitch(pitch["id"], MS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE.value)

    fetched = validate_success(api.get_pitch(pitch["id"], MS))
    assert fetched["status"] == "DRAFT", "pitch should remain DRAFT after rejected send"


def test_pitch_send_succeeds_when_campaign_active(api):
    """PRD §3.4: "Sending a pitch advances it from `DRAFT` to `SENT`. Sending has three
    preconditions: the campaign must be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`; the
    recipient journalist must be `ACTIVE`, else `ERR_JOURNALIST_BLOCKLISTED`; and the source
    media list must be `ACTIVE`, else `ERR_MEDIA_LIST_NOT_ACTIVE`."

    With campaign ACTIVE (and journalist + list ACTIVE) the same send succeeds, confirming
    the campaign-state guard is the discriminating factor.

    Design: Difficulty/cross_entity_state_dependency/pitch_send_requires_campaign_active
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch(scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"])
    sent = validate_success(api.send_pitch(pitch["id"], MS))
    assert sent["status"] == "SENT"


# =========================================================================== #
# cross_entity_state_dependency / interview_confirm_requires_pitch_accepted
# =========================================================================== #

def test_confirm_interview_anchored_on_responded_pitch_rejected(api):
    """PRD §3.6: "Confirming advances `REQUESTED` to `CONFIRMED` and has two preconditions: the
    spokesperson must be `ACTIVE`, else `ERR_SPOKESPERSON_INACTIVE`; and if the interview
    carries a `pitch_id`, that pitch's `status` must be `ACCEPTED`, else
    `ERR_PITCH_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/interview_confirm_requires_pitch_accepted
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "RESPONDED")
    from test_helpers import create_spokesperson, create_interview
    spokesperson = create_spokesperson(scn["client"]["id"], full_name="Conf Spoke", title="VP")
    interview = create_interview(
        scn["campaign"]["id"], spokesperson["id"], scn["journalist"]["id"],
        "2026-04-15T10:00:00Z", "2026-04-15T11:00:00Z", pitch_id=pitch["id"],
    )

    resp = api.confirm_interview(interview["id"], SC)
    validate_error(resp, ApiErrorId.ERR_PITCH_NOT_ACCEPTED.value)

    fetched = validate_success(api.get_interview(interview["id"], SC))
    assert fetched["status"] == "REQUESTED", "interview should remain REQUESTED"


def test_confirm_interview_anchored_on_accepted_pitch_succeeds(api):
    """PRD §3.6: "Confirming advances `REQUESTED` to `CONFIRMED` and has two preconditions: the
    spokesperson must be `ACTIVE`, else `ERR_SPOKESPERSON_INACTIVE`; and if the interview
    carries a `pitch_id`, that pitch's `status` must be `ACCEPTED`, else
    `ERR_PITCH_NOT_ACCEPTED`."

    Once the anchoring pitch is ACCEPTED, the same confirm succeeds, isolating pitch state
    as the discriminating precondition.

    Design: Difficulty/cross_entity_state_dependency/interview_confirm_requires_pitch_accepted
    """
    from test_helpers import create_spokesperson, create_interview
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "ACCEPTED")
    spokesperson = create_spokesperson(scn["client"]["id"], full_name="Ok Spoke", title="VP")
    interview = create_interview(
        scn["campaign"]["id"], spokesperson["id"], scn["journalist"]["id"],
        "2026-04-16T10:00:00Z", "2026-04-16T11:00:00Z", pitch_id=pitch["id"],
    )
    confirmed = validate_success(api.confirm_interview(interview["id"], SC))
    assert confirmed["status"] == "CONFIRMED"
