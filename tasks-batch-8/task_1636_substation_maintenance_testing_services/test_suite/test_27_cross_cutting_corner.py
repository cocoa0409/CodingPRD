"""Corner coverage — cross-cutting layers: optimistic concurrency control on
the two OCC-carrying write endpoints (PRD §2.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_outage_window,
    create_certified_technician,
    create_defect,
    create_outage_window,
    create_verified_relay_setting,
    create_work_order,
    setup_asset,
    setup_relay_domain,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestOccStaleSchedule:
    def test_stale_window_version_rejected_then_fresh_retry_succeeds(self):
        """PRD §2.6: "Scheduling a work order requires the request to carry
        `expected_outage_window_version` equal to the current `version` of the
        target `OutageWindow`. In both cases, a mismatch with the parent's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_schedule_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(base["asset"]["id"], tech_headers, "C3", title="Heater")
        work_order = create_work_order(defect["id"], tech["id"], 2, title="Fix heater")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-11-20T08:00:00Z", "2026-11-20T16:00:00Z", purpose="OCC probe",
        )
        pre_approve_version = window["version"]
        approve_outage_window(window["id"], "ops-mgr-1")  # advances the version
        # The pre-approval version is stale by the time of scheduling.
        resp = api_client.schedule_work_order(
            work_order["id"],
            {
                "outage_window_id": window["id"],
                "expected_outage_window_version": pre_approve_version,
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        fresh = validate_success(api_client.get_outage_window(window["id"], COORD))
        scheduled = validate_success(
            api_client.schedule_work_order(
                work_order["id"],
                {
                    "outage_window_id": window["id"],
                    "expected_outage_window_version": fresh["version"],
                },
                COORD,
            )
        )
        assert scheduled["status"] == "SCHEDULED"


class TestOccStaleRelayActivate:
    def test_stale_asset_version_rejected_after_prior_activation(self):
        """PRD §2.6: "Activating a relay setting requires the request to carry
        `expected_asset_version` equal to the current `version` of the target
        `Asset`."
        PRD §2.6: "an activation carrying an older `expected_asset_version` is
        acting on a coordination basis the server has already advanced past,
        and a schedule carrying an older `expected_outage_window_version`
        would commit hours against a stale remaining-capacity figure."
        PRD §3.8: "Success transitions the setting `VERIFIED → ACTIVE`,
        transitions any previously `ACTIVE` setting of the same `(asset_id,
        setting_group)` to `SUPERSEDED`, stamps this setting's
        `supersedes_setting_id` to the superseded setting's `id` (null when
        none existed), and increments both the setting's and the asset's
        `version`."

        Design: Corner/cross_cutting_layers/occ_stale_relay_activate_rejected
        """
        domain = setup_relay_domain()
        asset_id = domain["asset"]["id"]
        setting1 = create_verified_relay_setting(
            asset_id, domain["author_headers"], domain["verifier_headers"], pickup_a=80,
        )
        setting2 = create_verified_relay_setting(
            asset_id, domain["author_headers"], domain["verifier_headers"],
            pickup_a=85, time_dial=2.2, curve="IEC_VI",
        )
        asset = validate_success(api_client.get_asset(asset_id, OPS))
        stale_version = asset["version"]
        activated1 = validate_success(
            api_client.activate_relay_setting(
                setting1["id"], {"expected_asset_version": stale_version},
                domain["verifier_headers"],
            )
        )
        assert activated1["status"] == "ACTIVE"
        # The first activation bumped the asset version; the second activation
        # carrying the same expected version is acting on a stale basis.
        resp = api_client.activate_relay_setting(
            setting2["id"], {"expected_asset_version": stale_version},
            domain["verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        setting2_now = validate_success(api_client.get_relay_setting(setting2["id"], OPS))
        assert setting2_now["status"] == "VERIFIED"
