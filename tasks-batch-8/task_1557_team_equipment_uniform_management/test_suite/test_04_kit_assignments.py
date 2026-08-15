"""Kit assignments: reservation schema, numbering uniqueness, state machine
transitions, and version cadence."""
from test_helpers import (
    EM,
    ApiErrorId,
    create_jersey_and_pants_pools,
    create_player,
    create_reserved_kit,
    get_kit,
    get_pool,
    setup_issued_kit,
    setup_reserved_kit,
    validate_error,
    validate_success,
)


class TestKitSchema:
    def test_kit_create_missing_required_field_returns_400(self, api):
        """PRD §2.9: "Request schema — required fields are present and types,
        enums, and ranges are valid: `jersey_number` an integer from 0 to 99
        inclusive, quantities strictly positive, percentage fields within 0 to 1
        inclusive, dates parseable."
        PRD §2.9: "all other schema failures answer `ERR_INVALID_REQUEST`."
        PRD §3.4: "An `EquipmentManager` reserves a kit by supplying the
        `player_id`, the `season_label`, a `jersey_number` between 0 and 99
        inclusive, and the two pools the garments come from: `jersey_pool_id`
        and `pants_pool_id`."

        Design: Corner/entities/kit_create_missing_required_field_returns_400
        """
        ws = setup_reserved_kit(jersey_number=40, player_name="Req Base")
        resp = api.create_kit_assignment(
            {
                "player_id": ws["player"]["id"],
                "season_label": "2026-FALL",
                "jersey_pool_id": ws["jersey_pool"]["id"],
                "pants_pool_id": ws["pants_pool"]["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestKitStateMachine:
    def test_kit_issue_from_issued_rejected(self, api):
        """PRD §3.4: "Issuing moves a kit `RESERVED → ISSUED`. The kit must
        currently be `RESERVED` (`ERR_KIT_NOT_RESERVED`), the player must be
        `ACTIVE` (`ERR_PLAYER_NOT_ACTIVE`), and both pools must still be
        `ACTIVE` (`ERR_POOL_CLOSED`)."

        Design: Corner/state_machines/kit_issue_from_issued_rejected
        """
        ws = setup_issued_kit(jersey_number=41, player_name="Tr One")
        resp = api.issue_kit_assignment(ws["kit"]["id"], EM)
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_RESERVED)
        assert get_kit(ws["kit"]["id"])["status"] == "ISSUED", (
            "The rejected second issue leaves the kit ISSUED")

    def test_kit_terminal_lockdown_after_return(self, api):
        """PRD §3.4: "Returning moves an issued kit `ISSUED → RETURNED`
        (`ERR_KIT_NOT_ISSUED` from any other state), adding one unit of
        `stock_on_hand` back to each pool, stamping `closed_at`, and freeing the
        number."

        Design: Corner/state_machines/kit_terminal_lockdown_after_return
        """
        ws = setup_issued_kit(jersey_number=42, jersey_stock=5, pants_stock=5,
                              player_name="Term One")
        validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        assert get_kit(ws["kit"]["id"])["status"] == "RETURNED"
        assert get_pool(ws["jersey_pool"]["id"])["stock_on_hand"] == 5

        resp = api.return_kit_assignment(ws["kit"]["id"], EM)
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_ISSUED)
        assert get_pool(ws["jersey_pool"]["id"])["stock_on_hand"] == 5, (
            "A terminal kit cannot restock the pool a second time")


class TestJerseyNumberUniqueness:
    def test_jersey_number_taken_then_freed(self, api):
        """PRD §3.4: "Within a season, a jersey number may be held by at most
        one kit assignment in `RESERVED` or `ISSUED` status; a clash is rejected
        with `ERR_JERSEY_NUMBER_TAKEN`."
        PRD §3.4: "an explicit release by an `EquipmentManager`, valid only from
        `RESERVED` (`ERR_KIT_NOT_RESERVED`), which decrements each pool's
        `reserved_quantity` by one, stamps `closed_at`, frees the jersey number
        for the season, and lands the kit in `RELEASED`"

        Design: Corner/validations/jersey_number_taken_then_freed
        """
        ws = setup_reserved_kit(jersey_number=7, player_name="N One")
        p2 = create_player(full_name="N Two", position_group="DEFENSE")
        p3 = create_player(full_name="N Three")

        resp = api.create_kit_assignment(
            {
                "player_id": p2["id"],
                "season_label": "2026-FALL",
                "jersey_number": 7,
                "jersey_pool_id": ws["jersey_pool"]["id"],
                "pants_pool_id": ws["pants_pool"]["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_JERSEY_NUMBER_TAKEN)

        released = validate_success(api.release_kit_assignment(ws["kit"]["id"], EM))
        assert released["status"] == "RELEASED"

        kit3 = create_reserved_kit(p3["id"], ws["jersey_pool"]["id"],
                                   ws["pants_pool"]["id"], jersey_number=7)
        assert kit3["status"] == "RESERVED" and kit3["jersey_number"] == 7, (
            "Releasing the holder frees the number for reuse")


class TestKitPoolSeasonAlignment:
    def test_kit_pool_season_mismatch_rejected(self, api):
        """PRD §3.4: "Both pools must exist (`ERR_POOL_NOT_FOUND`), must belong
        to the kit's season (`ERR_POOL_SEASON_MISMATCH`), and must be `ACTIVE`
        (`ERR_POOL_CLOSED`)."

        Design: Corner/validations/kit_pool_season_mismatch_rejected
        """
        jersey, pants = create_jersey_and_pants_pools(season_label="2025-FALL")
        player = create_player(full_name="Szn One")
        resp = api.create_kit_assignment(
            {
                "player_id": player["id"],
                "season_label": "2026-FALL",
                "jersey_number": 74,
                "jersey_pool_id": jersey["id"],
                "pants_pool_id": pants["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_SEASON_MISMATCH)


class TestKitVersionCadence:
    def test_kit_version_increments_on_each_mutation(self, api):
        """PRD §3.4: "Every issue, release, and return increments the
        assignment's `version` by 1."
        PRD §2.5: "`version` (integer): starts at its initial value on creation
        and increments by exactly 1 on every mutation of the resource, including
        system-driven cascades that touch the resource."

        Design: Corner/complexity_layers/kit_version_increments_on_each_mutation
        """
        ws = setup_reserved_kit(jersey_number=77, player_name="Ver One")
        v_create = ws["kit"]["version"]

        issued = validate_success(api.issue_kit_assignment(ws["kit"]["id"], EM))
        assert issued["version"] == v_create + 1, "Issue increments the version by 1"

        returned = validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        assert returned["version"] == v_create + 2, "Return increments it by 1 again"

        fetched = get_kit(ws["kit"]["id"])
        assert fetched["version"] == v_create + 2
