"""Drill after-action corrective-action lifecycle preconditions."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_activated_hazard_plan,
    create_drill,
)


def test_drill_close_corrective_action_before_complete_rejected(api, admin_headers):
    """PRD §3.7: "Closing the corrective action — moving
    `corrective_action_status` from `OPEN` to `CLOSED` — is available only once
    `status` is `COMPLETED` and `corrective_action_status` is `OPEN`..."

    Design: Corner/state_machines/drill_close_corrective_action_before_complete_rejected
    """
    hp = create_activated_hazard_plan()
    drill = create_drill(hp["id"], drill_type="TABLETOP", scheduled_at="2026-04-01T09:00:00Z")
    assert drill["status"] == "SCHEDULED"
    assert drill["corrective_action_status"] == "NONE"

    res = api.close_drill_corrective_action(drill["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
