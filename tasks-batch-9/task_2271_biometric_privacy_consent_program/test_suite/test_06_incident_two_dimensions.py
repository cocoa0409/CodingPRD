"""The two parallel dimensions of an incident case.

Containment and notification advance independently on one row, and they meet only
at the terminal containment step.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_cents,
    assert_instant_equals,
    baseline_with_active_asset,
    create_incident,
    set_clock,
    validate_error,
    validate_success,
)


def _detected_incident(api):
    ctx = baseline_with_active_asset(api, activation_clock=None)
    set_clock(api, "2026-09-01T00:00:00Z")
    incident = create_incident(
        api,
        ctx["program_id"],
        [ctx["asset_id"]],
        exposure_vector="INSIDER_MISUSE",
        description="Contractor exported hand-geometry templates to personal storage.",
        exposed_subject_count=12,
        translation_locale_count=0,
    )
    return ctx, incident


def test_containment_and_notification_each_advance_without_moving_the_other(api):
    """Containing an incident leaves notification pending, and vice versa.

    PRD §3.8: "An incident advances along **two parallel dimensions that move
    independently**, and only one join point couples them."

    The containment move to `CONTAINED` leaves `notification_status` at
    `PENDING`, and the later notification move to `ASSESSED` — which prices the
    case at 12 x 425 = 5,100 cents with no locale cost, no surcharge and no
    vendor pool — leaves `containment_status` at `CONTAINED`.

    Design: Difficulty/non_linear_state_machine/incident_containment_and_notification_dimensions_advance_independently
    """
    _ctx, incident = _detected_incident(api)

    assert incident["containment_status"] == "DETECTED"
    assert incident["notification_status"] == "PENDING"

    contained = validate_success(
        api.transition_incident_containment(
            incident["id"],
            {"to_status": "CONTAINED", "containment_note": "Export path revoked and credentials rotated."},
            PRIVACY_OFFICER,
        )
    )
    assert contained["containment_status"] == "CONTAINED"
    assert contained["notification_status"] == "PENDING", "containment must not advance notification"

    assessed = validate_success(
        api.transition_incident_notification(incident["id"], {"to_status": "ASSESSED"}, PRIVACY_OFFICER)
    )

    assert assessed["notification_status"] == "ASSESSED"
    assert assessed["containment_status"] == "CONTAINED", "notification must not advance containment"
    assert assessed["heightened_tier"] == "TIER_2"
    assert_instant_equals(assessed["notification_due_at"], "2026-10-16T00:00:00.000Z", "notification_due_at")
    assert_cents(assessed["gross_notice_cents"], 5100, "gross_notice_cents")
    assert_cents(assessed["regulator_surcharge_cents"], 0, "regulator_surcharge_cents")
    assert_cents(assessed["net_incident_cost_cents"], 5100, "net_incident_cost_cents")


def test_remediation_is_refused_while_the_notification_dimension_is_unresolved(api):
    """The join edge waits for the notification dimension to finish.

    PRD §3.8: "It requires that `notification_status` is already `NOTIFIED` or
    `EXEMPT` — an outstanding `PENDING` or `ASSESSED` notification blocks
    remediation with `ERR_NOTIFICATION_OUTSTANDING`"

    The exposed point is gated first so the affected-point requirement is
    satisfied and the notification dimension is the only thing left outstanding.

    Design: Difficulty/non_linear_state_machine/incident_containment_and_notification_dimensions_advance_independently
    """
    ctx, incident = _detected_incident(api)

    validate_success(
        api.transition_incident_containment(
            incident["id"],
            {"to_status": "CONTAINED", "containment_note": "Export path revoked and credentials rotated."},
            PRIVACY_OFFICER,
        )
    )
    validate_success(api.transition_asset(ctx["asset_id"], {"to_status": "GATED"}, PRIVACY_OFFICER))
    validate_success(
        api.transition_incident_notification(incident["id"], {"to_status": "ASSESSED"}, PRIVACY_OFFICER)
    )

    refused = api.transition_incident_containment(
        incident["id"],
        {"to_status": "REMEDIATED", "containment_note": "Rebuilt the export pipeline."},
        PRIVACY_OFFICER,
    )

    validate_error(refused, ApiErrorId.NOTIFICATION_OUTSTANDING)

    still_contained = validate_success(api.get_incident(incident["id"], PRIVACY_OFFICER))
    assert still_contained["containment_status"] == "CONTAINED"
    assert still_contained["notification_status"] == "ASSESSED"
