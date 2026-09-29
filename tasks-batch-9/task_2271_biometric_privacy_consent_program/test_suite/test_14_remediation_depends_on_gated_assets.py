"""Remediation waits on the exposed collection points, not on the case file.

Both of the incident's own dimensions are satisfied, yet the terminal containment
move is refused while an exposed surface is still collecting.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_instant_equals,
    assert_program_state,
    baseline_with_active_asset,
    create_incident,
    read_asset,
    read_incident,
    read_program,
    set_clock,
    validate_error,
    validate_success,
)

REMEDIATION = {"to_status": "REMEDIATED", "containment_note": "Pipeline rebuilt and reviewed."}


def _contained_and_notified_incident_over_a_live_point(api):
    ctx = baseline_with_active_asset(api, activation_clock=None)
    set_clock(api, "2026-09-01T00:00:00Z")
    incident = create_incident(
        api,
        ctx["program_id"],
        [ctx["asset_id"]],
        exposure_vector="INSIDER_MISUSE",
        description="Contractor exported fingerprint templates to personal storage.",
        exposed_subject_count=12,
        translation_locale_count=0,
    )
    validate_success(
        api.transition_incident_containment(
            incident["id"],
            {"to_status": "CONTAINED", "containment_note": "Export path revoked."},
            PRIVACY_OFFICER,
        )
    )
    validate_success(
        api.transition_incident_notification(
            incident["id"], {"to_status": "ASSESSED"}, PRIVACY_OFFICER
        )
    )
    notified = validate_success(
        api.transition_incident_notification(
            incident["id"], {"to_status": "NOTIFIED", "notified_subject_count": 12}, PRIVACY_OFFICER
        )
    )
    ctx["incident_id"] = incident["id"]
    ctx["notified"] = notified
    return ctx


def test_remediation_is_refused_while_an_exposed_point_is_still_active(api):
    """A satisfied case file cannot remediate a live surface.

    PRD §3.8: "and it requires that every collection point listed in
    `affected_asset_ids` has a status of `GATED` or `DECOMMISSIONED`, since an
    exposed surface that is still collecting has not been remediated at all; a
    still-`ACTIVE` point yields `ERR_ASSET_STILL_ACTIVE`."

    The notification dimension has already reached `NOTIFIED` on the day of
    discovery, well inside the forty-five-day deadline, so the notification half of
    the join is not what is blocking.

    Design: Difficulty/cross_entity_state_dependency/incident_remediation_requires_every_affected_asset_out_of_active
    """
    ctx = _contained_and_notified_incident_over_a_live_point(api)

    notified = ctx["notified"]
    assert notified["notified_subject_count"] == 12
    assert_instant_equals(notified["notified_at"], "2026-09-01T00:00:00.000Z", "notified_at")
    assert_instant_equals(
        notified["notification_due_at"], "2026-10-16T00:00:00.000Z", "notification_due_at"
    )
    assert notified["late_notification"] is False
    assert read_asset(api, ctx["asset_id"])["status"] == "ACTIVE"

    refused = api.transition_incident_containment(ctx["incident_id"], REMEDIATION, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.ASSET_STILL_ACTIVE)

    unchanged = read_incident(api, ctx["incident_id"])
    assert unchanged["containment_status"] == "CONTAINED"
    assert unchanged["notification_status"] == "NOTIFIED"


def test_gating_the_exposed_point_lets_the_identical_remediation_succeed(api):
    """Touching only the collection point unblocks the case.

    PRD §3.5: "In all cases gating recomputes the program's `gated_asset_count` and
    `posture`."

    Nothing about the incident changes between the refusal and the success: the
    exposed surface stops collecting, and the same terminal containment move then
    lands, leaving the program restricted by its one gated point.

    Design: Difficulty/cross_entity_state_dependency/incident_remediation_requires_every_affected_asset_out_of_active
    """
    ctx = _contained_and_notified_incident_over_a_live_point(api)
    validate_error(
        api.transition_incident_containment(ctx["incident_id"], REMEDIATION, PRIVACY_OFFICER),
        ApiErrorId.ASSET_STILL_ACTIVE,
    )

    gated = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "GATED"}, PRIVACY_OFFICER)
    )
    assert gated["status"] == "GATED"

    remediated = validate_success(
        api.transition_incident_containment(ctx["incident_id"], REMEDIATION, PRIVACY_OFFICER)
    )

    assert remediated["containment_status"] == "REMEDIATED"
    assert remediated["notification_status"] == "NOTIFIED"
    assert_program_state(
        read_program(api, ctx["program_id"]), posture="RESTRICTED", gated_asset_count=1
    )
