"""Roster management, auth cascade, role-based access control, and error envelope."""
from test_helpers import (
    EM,
    LV,
    NON_EXISTENT_UUID,
    TA,
    ApiErrorId,
    assert_player,
    create_disposition,
    create_gear,
    create_player,
    create_player_payload,
    create_pool,
    get_case,
    get_claim,
    get_kit,
    get_player,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_assessed_gear_claim,
    setup_completed_event_with_load,
    setup_issued_kit,
    setup_reserved_kit,
    validate_error,
    validate_success,
)


class TestPlayerCreation:
    def test_player_create_defaults_status_active(self, api):
        """PRD §3.1: "Every player begins life in `ACTIVE` status."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
        uniquely identifying the resource."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."
        PRD §2.5: "`version` (integer): starts at its initial value on creation
        and increments by exactly 1 on every mutation of the resource, including
        system-driven cascades that touch the resource."

        Design: Corner/entities/player_create_defaults_status_active
        """
        resp = api.create_player(
            create_player_payload(full_name="Dee Fault", position_group="OFFENSE"), EM)
        player = validate_success(resp, 201)
        assert_player(player)
        assert player["status"] == "ACTIVE", "A new player is born ACTIVE"
        assert is_valid_uuid(player["id"]), "id is a server-minted bare UUID"
        assert is_iso8601_timestamp(player["created_at"])
        assert isinstance(player["version"], int) and player["version"] >= 1

        fetched = validate_success(api.get_player(player["id"], EM))
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == player["version"]


class TestAuthCascade:
    def test_auth_missing_headers_returns_400(self, api):
        """PRD §2.1: "A request with a missing header or an unrecognized role is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/auth_missing_headers_returns_400
        """
        resp = api.get_player(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failure(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.9: "Existence — referenced resources exist, checked left-to-right
        across the path identifiers first and then the identifiers referenced in
        the body (`player_id`, pool ids, `supplier_contract_id`, `item_id`, and
        so on), each surfacing its specific not-found error such as
        `ERR_PLAYER_NOT_FOUND`"

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api.get_player(NON_EXISTENT_UUID, EM)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_PLAYER_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"


class TestPlayerStatusMachine:
    def test_player_invalid_status_transition_rejected(self, api):
        """PRD §3.1: "Release is terminal: from either `ACTIVE` or `SUSPENDED`, a
        player moves to `RELEASED`, but only while the player holds no kit
        assignment in `ISSUED` status — otherwise the release is refused with
        `ERR_PLAYER_HAS_ISSUED_KITS`."
        PRD §3.1: "the request is rejected with `ERR_INVALID_STATE` if the player
        is in any other state."

        Design: Corner/state_machines/player_invalid_status_transition_rejected
        """
        player = create_player(full_name="Rel One")
        released = validate_success(
            api.patch_player(player["id"], {"status": "RELEASED"}, EM))
        assert released["status"] == "RELEASED"

        resp = api.patch_player(player["id"], {"status": "ACTIVE"}, EM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_player(player["id"])["status"] == "RELEASED", (
            "A RELEASED player is terminal and stays RELEASED")

    def test_player_release_blocked_by_issued_kit_rejected(self, api):
        """PRD §3.1: "Release is terminal: from either `ACTIVE` or `SUSPENDED`, a
        player moves to `RELEASED`, but only while the player holds no kit
        assignment in `ISSUED` status — otherwise the release is refused with
        `ERR_PLAYER_HAS_ISSUED_KITS`."

        Design: Corner/validations/player_release_blocked_by_issued_kit_rejected
        """
        ws = setup_issued_kit(jersey_number=73, player_name="Blk Two")
        resp = api.patch_player(ws["player"]["id"], {"status": "RELEASED"}, EM)
        validate_error(resp, ApiErrorId.ERR_PLAYER_HAS_ISSUED_KITS)
        assert get_player(ws["player"]["id"])["status"] == "ACTIVE", (
            "The player remains ACTIVE while a kit is still ISSUED")


class TestKitIssuePlayerGate:
    def test_kit_issue_blocked_for_suspended_player(self, api):
        """PRD §3.1: "Player status matters downstream: only an `ACTIVE` player
        may be issued a kit or a gear item, with violations answered by
        `ERR_PLAYER_NOT_ACTIVE`."
        PRD §3.4: "The kit must currently be `RESERVED` (`ERR_KIT_NOT_RESERVED`),
        the player must be `ACTIVE` (`ERR_PLAYER_NOT_ACTIVE`), and both pools
        must still be `ACTIVE` (`ERR_POOL_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/kit_issue_blocked_for_suspended_player
        """
        ws = setup_reserved_kit(jersey_number=21, player_name="Gate One")
        validate_success(api.patch_player(ws["player"]["id"], {"status": "SUSPENDED"}, EM))

        resp = api.issue_kit_assignment(ws["kit"]["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PLAYER_NOT_ACTIVE)
        assert get_kit(ws["kit"]["id"])["status"] == "RESERVED", (
            "The kit remains RESERVED while the player is SUSPENDED")

        validate_success(api.patch_player(ws["player"]["id"], {"status": "ACTIVE"}, EM))
        issued = validate_success(api.issue_kit_assignment(ws["kit"]["id"], EM))
        assert issued["status"] == "ISSUED", (
            "Reinstating the player unblocks the issue")

    def test_gear_issue_blocked_for_suspended_player(self, api):
        """PRD §3.1: "Player status matters downstream: only an `ACTIVE` player
        may be issued a kit or a gear item, with violations answered by
        `ERR_PLAYER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/kit_issue_blocked_for_suspended_player
        """
        player = create_player(full_name="Gate Two")
        gear = create_gear(asset_tag="HLM-GATE-1")
        validate_success(api.patch_player(player["id"], {"status": "SUSPENDED"}, EM))

        resp = api.issue_gear_item(gear["id"], {"player_id": player["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_PLAYER_NOT_ACTIVE)

        validate_success(api.patch_player(player["id"], {"status": "ACTIVE"}, EM))
        issued = validate_success(
            api.issue_gear_item(gear["id"], {"player_id": player["id"]}, EM))
        assert issued["status"] == "ISSUED"


class TestRoleBasedAccessControl:
    def test_laundry_vendor_cannot_create_player_403(self, api):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "`LaundryVendor`, the external laundry vendor who advances
        laundry cycles and otherwise only reads state."

        Design: Corner/rbac/laundry_vendor_cannot_create_player_403
        """
        resp = api.create_player(
            create_player_payload(full_name="No Perm", position_group="OFFENSE"), LV)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_equipment_manager_cannot_approve_disposition_403(self, api):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "`TeamAdmin`, the team administrator who owns supplier
        contracts, disposition approval, claim waivers and reopens, and the
        logical clock"

        Design: Corner/rbac/equipment_manager_cannot_approve_disposition_403
        """
        create_pool(season_label="2026-FALL", garment_type="SOCKS", size_code="L",
                    stock_on_hand=3)
        case = create_disposition(season_label="2026-FALL", garment_type="SOCKS",
                                  method="DONATE")
        resp = api.approve_disposition_case(case["id"], EM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_case(case["id"])["status"] == "PROPOSED", (
            "The proposing manager cannot self-approve; the case stays PROPOSED")

    def test_equipment_manager_cannot_waive_claim_403(self, api):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.7: "A `TeamAdmin` may instead waive the claim: the fee is zeroed
        in `final_fee_cents`, the claim lands in `WAIVED`, and the subject
        undergoes exactly the same mutations as a settlement."

        Design: Corner/rbac/equipment_manager_cannot_waive_claim_403
        """
        _player, _gear, claim = setup_assessed_gear_claim(
            claim_type="DAMAGED", base_value_cents=10000, grade="B",
            asset_tag="HLM-912")
        resp = api.waive_damage_claim(claim["id"], EM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_claim(claim["id"])["status"] == "ASSESSED", (
            "Waiver is TeamAdmin-exclusive; the claim stays ASSESSED")

    def test_team_admin_cannot_advance_laundry_403(self, api):
        """PRD §2.1: "All three roles may call every read endpoint; write
        privileges are partitioned per the endpoint table in §4, with the
        laundry-advance operation shared between `EquipmentManager` and
        `LaundryVendor`."
        PRD §3.6: "The laundry cycle is a parallel state dimension advanced one
        step per call — `COLLECTING → IN_WASH → READY → CLOSED` — by either the
        `LaundryVendor` or the `EquipmentManager`."

        Design: Corner/rbac/team_admin_cannot_advance_laundry_403
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=3)
        event = setup_completed_event_with_load(pool["id"], quantity=1)

        resp = api.advance_laundry(event["id"], TA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        advanced = validate_success(api.advance_laundry(event["id"], LV))
        assert advanced["laundry_status"] == "IN_WASH", (
            "The LaundryVendor's advance succeeds: COLLECTING -> IN_WASH")
