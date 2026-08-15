"""Corner coverage — errors: invalid state transitions surface
ERR_STATE_TRANSITION from the state-machine permission check (PRD §2.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_certified_technician,
    create_defect,
    create_relay_setting_payload,
    create_spare_reservation,
    create_spare_unit,
    create_work_order,
    get_success_data,
    setup_asset,
    setup_relay_domain,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestInvalidTransitions:
    def test_workorder_complete_from_draft_rejected(self):
        """PRD §3.6: "Completion is again the assignee's action, now carrying
        the `labor_lines` and `parts_lines` arrays."
        PRD §3.6: "Success transitions `SCHEDULED → IN_PROGRESS`."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/errors/workorder_complete_from_draft_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(base["asset"]["id"], tech_headers, "C3", title="Valve")
        work_order = create_work_order(defect["id"], tech["id"], 1, title="Fix valve")
        # The work order is DRAFT; completion is defined only from IN_PROGRESS.
        resp = api_client.complete_work_order(
            work_order["id"], {"labor_lines": [], "parts_lines": []}, tech_headers
        )
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)

    def test_reservation_cancel_twice_rejected(self):
        """PRD §3.7: "An `OutageCoordinator` may cancel an `ACTIVE` reservation
        provided the unit is not currently deployed under it — a deployed
        reservation must be returned, not cancelled; cancelling it is rejected
        with `ERR_STATE_TRANSITION` (HTTP 409). Cancellation transitions the
        reservation `ACTIVE → CANCELLED` and recomputes the unit's status:
        `AVAILABLE` when no `ACTIVE` reservation remains on the unit, else
        `RESERVED`."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/errors/reservation_cancel_twice_rejected
        """
        unit = create_spare_unit(home_location="Yard-V")
        reservation = create_spare_reservation(
            "2026-12-10T08:00:00Z", "2026-12-10T16:00:00Z", spare_unit_id=unit["id"]
        )
        cancelled = validate_success(
            api_client.cancel_spare_reservation(reservation["id"], COORD)
        )
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.cancel_spare_reservation(reservation["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)

    def test_activate_draft_relay_setting_rejected(self):
        """PRD §3.8: "Success transitions the setting `VERIFIED → ACTIVE`,
        transitions any previously `ACTIVE` setting of the same `(asset_id,
        setting_group)` to `SUPERSEDED`, stamps this setting's
        `supersedes_setting_id` to the superseded setting's `id` (null when
        none existed), and increments both the setting's and the asset's
        `version`."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/errors/activate_draft_relay_setting_rejected
        """
        domain = setup_relay_domain()
        # The author holds NETA_LEVEL_4 so only the state check can fail.
        get_success_data(
            api_client.create_certification(
                domain["author"]["id"],
                {
                    "cert_type": "NETA_LEVEL_4",
                    "issued_at": "2025-01-01T00:00:00Z",
                    "expires_at": "2027-01-01T00:00:00Z",
                },
                OPS,
            )
        )
        setting = get_success_data(
            api_client.create_relay_setting(
                create_relay_setting_payload(
                    domain["asset"]["id"], setting_group="G2", pickup_a=50, time_dial=1.0
                ),
                domain["author_headers"],
            )
        )
        asset = validate_success(api_client.get_asset(domain["asset"]["id"], OPS))
        resp = api_client.activate_relay_setting(
            setting["id"], {"expected_asset_version": asset["version"]},
            domain["author_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)
