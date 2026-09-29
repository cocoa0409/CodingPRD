"""Geofencing zones and location campaigns: activation gates, windows and cooldowns."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from test_helpers import (
    ApiErrorId,
    activate_campaign,
    activate_mapping,
    assert_geofence_campaign,
    assert_geofence_zone,
    create_approved_assessment,
    create_campaign,
    create_element,
    create_executed_vendor,
    create_mapping,
    create_product,
    create_published_policy,
    create_purpose,
    create_zone,
    make_data_steward_headers,
    make_privacy_officer_headers,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SHARE_PURPOSE = {
    "purpose_kind": "ADVERTISING",
    "activity_kind": "SHARE",
    "description_text": "Share with advertising partners",
}


def _instant(value: str) -> datetime:
    """Parse a rendered UTC instant so comparisons ignore fractional-digit padding."""
    assert value is not None, "expected an instant, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read_campaign(campaign_id: str, api: Any) -> dict[str, Any]:
    return validate_success(
        api.get_geofence_campaign(campaign_id, make_data_steward_headers())
    )


def _read_zone(zone_id: str, api: Any) -> dict[str, Any]:
    return validate_success(api.get_geofence_zone(zone_id, make_data_steward_headers()))


# ---------------------------------------------------------------------------
# Precedence between the geofence prohibition and the campaign window conflict
# ---------------------------------------------------------------------------


def test_prohibited_zone_masks_the_overlapping_window_on_campaign_activation(api):
    """The outright geofencing prohibition is reported ahead of the window conflict.

    PRD §2.7: "Checks are evaluated in the order below and the first failure
    short-circuits the request."
    PRD §2.7: "Lower-numbered checks therefore mask higher-numbered ones: a caller
    with the wrong role never learns that its payload was also malformed, and a
    caller acting on a policy that is not under review never learns that the
    policy's completeness score was also too low."
    PRD §3.8: "The zone's `prohibition_rule` must not be `PROHIBITED_ALL`, and an
    attempt against such a zone is refused with `ERR_GEOFENCE_PROHIBITED`."
    PRD §3.8: "First, exclusivity on the zone: the campaign's own closed interval
    from `window_start_at` to `window_end_at` inclusive must share no instant with
    the closed interval of any other campaign on the same zone whose `state` is
    `PLANNED`, `ACTIVE`, or `PAUSED`."

    The geofence prohibition sits at position 11 of the §2.7 list and the campaign
    window exclusivity at position 38, so the prohibition wins.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_geofence_prohibition_beats_business_temporal_window_conflict
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="WA")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Reproductive Care Center",
        state_code="WA",
        facility_kind="SENSITIVE_HEALTH",
        radius_meters=300,
    )
    assert zone["prohibition_rule"] == "PROHIBITED_ALL"

    incumbent = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Incumbent",
        target_radius_meters=200,
        distance_to_zone_center_meters=4000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    overlapper = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Overlapper",
        target_radius_meters=200,
        distance_to_zone_center_meters=4000,
        window_start_at="2026-09-03T00:00:00Z",
        window_end_at="2026-09-07T00:00:00Z",
    )

    response = api.activate_geofence_campaign(
        overlapper["id"], make_data_steward_headers()
    )
    validate_error(response, ApiErrorId.GEOFENCE_PROHIBITED.value)

    assert _read_campaign(overlapper["id"], api)["state"] == "PLANNED"
    assert _read_campaign(incumbent["id"], api)["state"] == "PLANNED"
    refreshed_zone = _read_zone(zone["id"], api)
    assert refreshed_zone["prohibition_rule"] == "PROHIBITED_ALL"
    assert refreshed_zone["last_campaign_activated_at"] is None


def test_overlapping_window_surfaces_once_the_zone_is_a_permitting_jurisdiction(api):
    """With no prohibition in the way, the masked window conflict is the reported failure.

    PRD §3.8: "In a permitting jurisdiction, every facility class yields `PERMITTED`."
    PRD §3.8: "First, exclusivity on the zone: the campaign's own closed interval
    from `window_start_at` to `window_end_at` inclusive must share no instant with
    the closed interval of any other campaign on the same zone whose `state` is
    `PLANNED`, `ACTIVE`, or `PAUSED`."
    PRD §3.8: "Because both intervals are closed, merely touching endpoints
    collide, and the conflict is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_geofence_prohibition_beats_business_temporal_window_conflict
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="SENSITIVE_HEALTH",
        radius_meters=300,
    )
    assert zone["prohibition_rule"] == "PERMITTED"

    incumbent = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Incumbent",
        target_radius_meters=200,
        distance_to_zone_center_meters=4000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    overlapper = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Overlapper",
        target_radius_meters=200,
        distance_to_zone_center_meters=4000,
        window_start_at="2026-09-03T00:00:00Z",
        window_end_at="2026-09-07T00:00:00Z",
    )

    response = api.activate_geofence_campaign(
        overlapper["id"], make_data_steward_headers()
    )
    validate_error(response, ApiErrorId.CAMPAIGN_WINDOW_CONFLICT.value)

    assert _read_campaign(overlapper["id"], api)["state"] == "PLANNED"
    assert _read_campaign(incumbent["id"], api)["state"] == "PLANNED"
    assert _read_zone(zone["id"], api)["last_campaign_activated_at"] is None


# ---------------------------------------------------------------------------
# Closed campaign windows on one zone
# ---------------------------------------------------------------------------


def test_campaign_windows_touching_at_one_endpoint_collide_on_the_same_zone(api):
    """A window starting exactly when the running campaign's window ends collides.

    PRD §3.8: "First, exclusivity on the zone: the campaign's own closed interval
    from `window_start_at` to `window_end_at` inclusive must share no instant with
    the closed interval of any other campaign on the same zone whose `state` is
    `PLANNED`, `ACTIVE`, or `PAUSED`."
    PRD §3.8: "Because both intervals are closed, merely touching endpoints
    collide, and the conflict is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`."
    PRD §3.8: "Creation also computes the campaign's `standoff_meters`: the
    surveyed centre-to-centre distance, less the campaign's own
    `target_radius_meters`, less the zone's `radius_meters`."

    Design: Difficulty/resource_temporal_overlap/campaign_closed_windows_touching_at_an_endpoint_collide_on_the_same_zone
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    assert zone["prohibition_rule"] == "PERMITTED"
    assert zone["min_standoff_meters"] == 0

    wave_a = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave A",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    assert wave_a["standoff_meters"] == 1500
    activate_campaign(wave_a["id"], api)

    set_clock("2026-08-07T00:00:00Z", api)
    wave_b = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave B",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-05T00:00:00Z",
        window_end_at="2026-09-08T00:00:00Z",
    )

    response = api.activate_geofence_campaign(wave_b["id"], make_data_steward_headers())
    validate_error(response, ApiErrorId.CAMPAIGN_WINDOW_CONFLICT.value)

    assert _read_campaign(wave_b["id"], api)["state"] == "PLANNED"
    running = _read_campaign(wave_a["id"], api)
    assert running["state"] == "ACTIVE"
    assert running["standoff_meters"] == 1500
    refreshed_zone = _read_zone(zone["id"], api)
    assert _instant(refreshed_zone["last_campaign_activated_at"]) == _instant(
        "2026-08-05T00:00:00Z"
    )


def test_campaign_window_starting_after_the_incumbent_ends_activates_on_the_zone(api):
    """A window sharing no instant with the running campaign's window is admitted.

    PRD §3.8: "First, exclusivity on the zone: the campaign's own closed interval
    from `window_start_at` to `window_end_at` inclusive must share no instant with
    the closed interval of any other campaign on the same zone whose `state` is
    `PLANNED`, `ACTIVE`, or `PAUSED`."
    PRD §3.8: "Every successful activation, from `PLANNED` or from `PAUSED`, sets
    the zone's `last_campaign_activated_at` to the logical clock; a resume
    additionally clears `pause_reason` back to null."

    Design: Difficulty/resource_temporal_overlap/campaign_closed_windows_touching_at_an_endpoint_collide_on_the_same_zone
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    wave_a = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave A",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    activate_campaign(wave_a["id"], api)

    set_clock("2026-08-07T00:00:00Z", api)
    wave_b = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave B",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-06T00:00:00Z",
        window_end_at="2026-09-08T00:00:00Z",
    )

    response = api.activate_geofence_campaign(wave_b["id"], make_data_steward_headers())
    activated = validate_success(response)
    assert_geofence_campaign(activated)
    assert activated["state"] == "ACTIVE"
    assert activated["standoff_meters"] == 1500
    assert _read_campaign(wave_a["id"], api)["state"] == "ACTIVE"
    refreshed_zone = _read_zone(zone["id"], api)
    assert _instant(refreshed_zone["last_campaign_activated_at"]) == _instant(
        "2026-08-07T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# Campaign lifecycle corners
# ---------------------------------------------------------------------------


def test_ended_campaign_cannot_be_activated_again(api):
    """ENDED is the campaign's only terminal state, so activation is a terminal-state refusal.

    PRD §3.8: "Ending a campaign is admitted from all three non-terminal states
    and takes it to the terminal `ENDED`: `PLANNED → ENDED` for one never
    activated, `ACTIVE → ENDED` for one running, and `PAUSED → ENDED` for one
    suspended."
    PRD §2.7: "A data element action that requires an `ACTIVE` element fails with
    `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in
    `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or
    reissue whose vendor agreement is not `EXECUTED` fails with
    `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`; a target already sitting in one of its
    terminal states fails with `ERR_ALREADY_TERMINAL`; every other from-state
    mismatch fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_state_lockdown_ended_campaign_cannot_be_activated
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    campaign = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave A",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    ended = validate_success(
        api.end_geofence_campaign(campaign["id"], make_data_steward_headers())
    )
    assert ended["state"] == "ENDED"

    response = api.activate_geofence_campaign(campaign["id"], make_data_steward_headers())
    validate_error(response, ApiErrorId.ALREADY_TERMINAL.value)

    assert _read_campaign(campaign["id"], api)["state"] == "ENDED"
    assert _read_zone(zone["id"], api)["last_campaign_activated_at"] is None


def test_resuming_a_paused_campaign_clears_the_pause_reason_and_restamps_the_zone(api):
    """A resume clears the operator's pause reason and re-stamps the zone inside the cooldown.

    PRD §3.8: "Pausing an `ACTIVE` campaign moves it `ACTIVE → PAUSED` and records
    the operator's `pause_reason` from the body — or sets it to `POLICY_LAPSED`
    when the pause was driven by the fifth hop of the vendor-termination cascade
    rather than by an operator."
    PRD §3.8: "Every successful activation, from `PLANNED` or from `PAUSED`, sets
    the zone's `last_campaign_activated_at` to the logical clock; a resume
    additionally clears `pause_reason` back to null."
    PRD §3.8: "Neither the window-exclusivity test nor the cooldown is
    re-evaluated when a paused campaign resumes."

    Design: Corner/endpoints/action_endpoint_pause_then_resume_clears_the_pause_reason
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    campaign = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave A",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    activate_campaign(campaign["id"], api)
    paused = validate_success(
        api.pause_geofence_campaign(
            campaign["id"],
            {"pause_reason": "Creative under legal review"},
            make_data_steward_headers(),
        )
    )
    assert paused["state"] == "PAUSED"
    assert paused["pause_reason"] == "Creative under legal review"

    set_clock("2026-08-05T06:00:00Z", api)
    resumed = validate_success(
        api.activate_geofence_campaign(campaign["id"], make_data_steward_headers())
    )
    assert_geofence_campaign(resumed)
    assert resumed["state"] == "ACTIVE"
    assert resumed["pause_reason"] is None
    assert resumed["standoff_meters"] == 1500

    refreshed_zone = _read_zone(zone["id"], api)
    assert_geofence_zone(refreshed_zone)
    assert refreshed_zone["prohibition_rule"] == "PERMITTED"
    assert refreshed_zone["min_standoff_meters"] == 0
    assert _instant(refreshed_zone["last_campaign_activated_at"]) == _instant(
        "2026-08-05T06:00:00Z"
    )


# ---------------------------------------------------------------------------
# Activation and creation refusals
# ---------------------------------------------------------------------------


def test_campaign_one_meter_short_of_the_sensitive_standoff_is_refused(api):
    """A standoff of 499 metres against a 500-metre minimum is refused one metre short.

    PRD §3.8: "In a jurisdiction that prohibits only around sensitive facilities,
    a `SENSITIVE_HEALTH` facility yields `PROHIBITED_ALL`, a `GENERAL_HEALTH`
    facility yields `PROHIBITED_SENSITIVE_ONLY`, and a `NON_HEALTH` facility
    yields `PERMITTED`."
    PRD §3.8: "From the rule follows `min_standoff_meters`: a zone whose
    `prohibition_rule` is `PROHIBITED_SENSITIVE_ONLY` demands a clearance of five
    hundred metres; a `PERMITTED` zone demands none, so the value is zero; and for
    a `PROHIBITED_ALL` zone the field is not applicable because no campaign may
    ever run against it."
    PRD §3.8: "The campaign's `standoff_meters` must be at least the zone's
    `min_standoff_meters` — a standoff exactly equal to the minimum is admitted,
    and anything strictly below it is refused with
    `ERR_GEOFENCE_STANDOFF_VIOLATION`."

    Design: Corner/errors/error_geofence_standoff_violation_one_meter_short
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="CT")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Elm Street Medical Center",
        state_code="CT",
        facility_kind="GENERAL_HEALTH",
        radius_meters=301,
    )
    assert zone["prohibition_rule"] == "PROHIBITED_SENSITIVE_ONLY"
    assert zone["min_standoff_meters"] == 500

    campaign = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Neighbourhood push",
        target_radius_meters=200,
        distance_to_zone_center_meters=1000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    assert campaign["standoff_meters"] == 499

    response = api.activate_geofence_campaign(campaign["id"], make_data_steward_headers())
    validate_error(response, ApiErrorId.GEOFENCE_STANDOFF_VIOLATION.value)

    refreshed_campaign = _read_campaign(campaign["id"], api)
    assert refreshed_campaign["state"] == "PLANNED"
    assert refreshed_campaign["standoff_meters"] == 499
    refreshed_zone = _read_zone(zone["id"], api)
    assert refreshed_zone["prohibition_rule"] == "PROHIBITED_SENSITIVE_ONLY"
    assert refreshed_zone["min_standoff_meters"] == 500
    assert refreshed_zone["last_campaign_activated_at"] is None


def test_zero_length_campaign_window_is_refused_at_creation(api):
    """A window whose end equals its start is refused and no campaign row is written.

    PRD §3.8: "The end must be strictly later than the start; an inverted or
    zero-length window is refused with `ERR_WINDOW_END_BEFORE_START`."

    Design: Corner/errors/error_window_end_before_start_on_campaign_create
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )

    response = api.create_geofence_campaign(
        {
            "geofence_zone_id": zone["id"],
            "processing_purpose_id": purpose["id"],
            "campaign_name": "Zero length",
            "target_radius_meters": 200,
            "distance_to_zone_center_meters": 2000,
            "window_start_at": "2026-09-01T00:00:00Z",
            "window_end_at": "2026-09-01T00:00:00Z",
        },
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.WINDOW_END_BEFORE_START.value)

    rows, meta = validate_paginated(
        api.list_geofence_campaigns(
            make_data_steward_headers(), {"geofence_zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_zone_cooldown_still_bites_twelve_hours_after_the_last_activation(api):
    """A second activation twelve hours into the day-long zone cooldown is refused.

    PRD §3.8: "Second, a cooldown: the zone's `last_campaign_activated_at` must be
    null, or the elapsed logical-clock time since it must be at least twenty-four
    hours; an activation strictly inside that day-long cooldown is refused with
    `ERR_ZONE_COOLDOWN_ACTIVE`."
    PRD §3.8: "Ending releases the campaign's window on the zone, so that another
    campaign may thereafter occupy an interval that previously collided with it."

    Design: Corner/errors/error_zone_cooldown_active_twelve_hours_after_the_last_activation
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    wave_a = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave A",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-09-05T00:00:00Z",
    )
    activate_campaign(wave_a["id"], api)
    validate_success(api.end_geofence_campaign(wave_a["id"], make_data_steward_headers()))

    wave_b = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Wave B",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-15T00:00:00Z",
    )

    set_clock("2026-08-05T12:00:00Z", api)
    response = api.activate_geofence_campaign(wave_b["id"], make_data_steward_headers())
    validate_error(response, ApiErrorId.ZONE_COOLDOWN_ACTIVE.value)

    assert _read_campaign(wave_b["id"], api)["state"] == "PLANNED"
    assert _read_campaign(wave_a["id"], api)["state"] == "ENDED"
    refreshed_zone = _read_zone(zone["id"], api)
    assert _instant(refreshed_zone["last_campaign_activated_at"]) == _instant(
        "2026-08-05T00:00:00Z"
    )


def test_campaign_activation_is_refused_while_the_policy_is_lapsed(api):
    """Terminating the named vendor lapses the policy and blocks campaign activation.

    PRD §3.4: "Hop two, because this vendor's agreement has ended, moves every
    element-purpose mapping whose `vendor_id` names this vendor and whose `status`
    is `ACTIVE` from `ACTIVE → SUSPENDED`, with `suspension_reason` set to
    `VENDOR_AGREEMENT_TERMINATED`."
    PRD §3.4: "Hop three, because at least one `ACTIVE` mapping was suspended by
    hop two, moves the privacy policy version on the same product whose `state` is
    `PUBLISHED` from `PUBLISHED → SUPERSEDED_PENDING_UPDATE` — the published text
    now describes a disclosure that no longer exists, so it is no longer an
    accurate policy."
    PRD §3.4: "Hop four, because that policy left `PUBLISHED` in hop three, sets
    the product's `policy_compliance_state` to `LAPSED`."
    PRD §3.8: "The product's `policy_compliance_state` must also not be `LAPSED`
    on either path, on pain of `ERR_POLICY_LAPSED`."

    Design: Corner/errors/error_policy_lapsed_on_campaign_activate_after_vendor_termination
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, primary_state_code="TX")
    element = create_element(product["id"], api)
    purpose = create_purpose(product["id"], api, **SHARE_PURPOSE)
    vendor = create_executed_vendor(product["id"], api)
    assessment = create_approved_assessment(product["id"], api)

    mapping = create_mapping(element["id"], purpose["id"], api, vendor_id=vendor["id"])
    mapping = activate_mapping(mapping["id"], api)
    assert mapping["status"] == "ACTIVE"

    policy = create_published_policy(
        product["id"],
        assessment["id"],
        api,
        disclosed_third_party_count=1,
        named_third_party_count=1,
    )
    assert policy["state"] == "PUBLISHED"
    assert read_product(product["id"], api)["policy_compliance_state"] == "CURRENT"

    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        radius_meters=300,
    )
    campaign = create_campaign(
        zone["id"],
        purpose["id"],
        api,
        campaign_name="Autumn wave",
        target_radius_meters=200,
        distance_to_zone_center_meters=2000,
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-20T00:00:00Z",
    )

    set_clock("2026-09-05T00:00:00Z", api)
    validate_success(
        api.terminate_vendor_agreement(vendor["id"], make_privacy_officer_headers())
    )

    response = api.activate_geofence_campaign(campaign["id"], make_data_steward_headers())
    validate_error(response, ApiErrorId.POLICY_LAPSED.value)

    assert read_product(product["id"], api)["policy_compliance_state"] == "LAPSED"
    lapsed_policy = validate_success(
        api.get_privacy_policy_version(policy["id"], make_privacy_officer_headers())
    )
    assert lapsed_policy["state"] == "SUPERSEDED_PENDING_UPDATE"
    suspended_mapping = validate_success(
        api.get_element_purpose_mapping(mapping["id"], make_data_steward_headers())
    )
    assert suspended_mapping["status"] == "SUSPENDED"
    assert _read_campaign(campaign["id"], api)["state"] == "PLANNED"
    assert _read_zone(zone["id"], api)["last_campaign_activated_at"] is None
