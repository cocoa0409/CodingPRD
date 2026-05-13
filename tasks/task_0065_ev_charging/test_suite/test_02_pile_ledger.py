"""Operator / Station / Pile ledger CRUD and Pile state machine.

PRD §3.1 (Operators, Stations, the Pile Ledger).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_operator,
    assert_pile,
    assert_station,
    create_operator,
    create_pile,
    create_platform_operator_row,
    create_station,
    create_station_owner_operator,
    decommission_pile,
    emit_grid_pile_offline,
    emit_grid_pile_online,
    get_pile,
    off_shelve_pile,
    patch_pile,
    setup_operator_station_pile_off_shelf,
    setup_operator_station_shelved_pile,
    setup_ready_to_charge,
    setup_reservation_held,
    shelve_pile,
    validate_error,
    validate_success,
    PO,
    make_station_owner_headers,
)


# ===========================================================================
# Operator creation
# ===========================================================================
class TestOperatorCreation:
    """PRD §3.1: 'each carrying a name ... a role_kind ... a tax_id'."""

    def test_create_platform_operator_returns_201(self, api):
        """PRD §4: 'a new resource creation ... returns HTTP 201.'"""
        from test_helpers import create_operator_payload
        res = api.create_operator(
            create_operator_payload(role_kind="PLATFORM"), PO,
        )
        body = validate_success(res, expected_status=201)
        assert_operator(body)
        assert body["role_kind"] == "PLATFORM"

    def test_create_station_owner_operator_returns_201(self, api):
        """PRD §3.1: 'a role_kind (one of PLATFORM, STATION_OWNER,
        ROAMING_PARTNER)'."""
        from test_helpers import create_operator_payload
        res = api.create_operator(
            create_operator_payload(role_kind="STATION_OWNER"), PO,
        )
        body = validate_success(res, expected_status=201)
        assert body["role_kind"] == "STATION_OWNER"


# ===========================================================================
# Station creation
# ===========================================================================
class TestStationCreation:
    """PRD §3.1: 'A Station carries ... an operator_id ... a
    station_owner_id ... and a status of either ACTIVE or SUSPENDED that
    defaults to ACTIVE.'"""

    def test_create_station_defaults_to_active(self, api):
        """PRD §3.1: 'a status of either ACTIVE or SUSPENDED that
        defaults to ACTIVE.'"""
        operator = create_platform_operator_row()
        station_owner = create_station_owner_operator()
        from test_helpers import create_station_payload
        res = api.create_station(
            create_station_payload(
                operator_id=operator["id"],
                station_owner_id=station_owner["id"],
            ),
            PO,
        )
        body = validate_success(res, expected_status=201)
        assert_station(body)
        assert body["status"] == "ACTIVE"


# ===========================================================================
# Pile lifecycle — new pile starts OFF_SHELF
# ===========================================================================
class TestPileInitialState:
    """PRD §3.1: 'New piles start OFF_SHELF.'"""

    def test_new_pile_is_off_shelf_with_null_operational_state(self, api):
        """PRD §3.1: 'New piles start OFF_SHELF. ... The
        operational_state is meaningful only while lifecycle_state is
        ON_SHELF and is otherwise null.'"""
        ctx = setup_operator_station_pile_off_shelf()
        pile = ctx["pile"]
        assert_pile(pile)
        assert pile["lifecycle_state"] == "OFF_SHELF"
        assert pile["operational_state"] is None


# ===========================================================================
# Pile shelve
# ===========================================================================
class TestPileShelve:
    """PRD §3.1: 'The shelving action, performed by a StationOwner,
    moves the pile from OFF_SHELF to ON_SHELF ... the pile's
    operational_state is simultaneously set to IDLE.'"""

    def test_shelve_off_shelf_pile_moves_to_on_shelf_idle(self, api):
        ctx = setup_operator_station_shelved_pile()
        pile = ctx["pile"]
        assert pile["lifecycle_state"] == "ON_SHELF"
        assert pile["operational_state"] == "IDLE"

    def test_shelve_pile_already_on_shelf_rejected(self, api):
        """PRD §3.1: precondition 'pile is currently OFF_SHELF'."""
        ctx = setup_operator_station_shelved_pile()
        res = api.shelve_pile(
            ctx["pile"]["id"],
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Pile off-shelve
# ===========================================================================
class TestPileOffShelve:
    """PRD §3.1: 'The off-shelving action returns the pile from ON_SHELF
    back to OFF_SHELF provided no charging session exists on this pile
    with status in PENDING_AUTH, CHARGING, or SETTLING, and no
    reservation on this pile is in status HELD.'"""

    def test_off_shelve_idle_pile_succeeds_and_clears_operational(self, api):
        """PRD §3.1: 'On successful off-shelving the operational_state
        is cleared to null.'"""
        ctx = setup_operator_station_shelved_pile()
        pile = off_shelve_pile(
            pile_id=ctx["pile"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert pile["lifecycle_state"] == "OFF_SHELF"
        assert pile["operational_state"] is None

    def test_off_shelve_pile_with_held_reservation_rejected(self, api):
        """PRD §3.1: 'no reservation on this pile is in status HELD; if
        either dependent exists, the request is rejected with
        ERR_PILE_HAS_DEPENDENTS.'"""
        ctx = setup_reservation_held()
        res = api.off_shelve_pile(
            ctx["pile"]["id"],
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_HAS_DEPENDENTS.value)

    def test_off_shelve_pile_with_active_session_rejected(self, api):
        """PRD §3.1: 'no charging session exists on this pile with
        status in PENDING_AUTH, CHARGING, or SETTLING ... otherwise
        ERR_PILE_HAS_DEPENDENTS.'"""
        from test_helpers import setup_charging_session
        ctx = setup_charging_session()
        res = api.off_shelve_pile(
            ctx["pile"]["id"],
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_HAS_DEPENDENTS.value)


# ===========================================================================
# Pile decommission
# ===========================================================================
class TestPileDecommission:
    """PRD §3.1: 'Decommissioning, performed by a PlatformOperator, is
    a one-way transition from OFF_SHELF to DECOMMISSIONED.'"""

    def test_decommission_off_shelf_pile_succeeds(self, api):
        ctx = setup_operator_station_pile_off_shelf()
        pile = decommission_pile(pile_id=ctx["pile"]["id"])
        assert pile["lifecycle_state"] == "DECOMMISSIONED"
        assert pile["operational_state"] is None

    def test_decommission_on_shelf_pile_rejected(self, api):
        """PRD §3.1: 'the pile may not be in ON_SHELF at the moment of
        decommission, otherwise the request is rejected as an invalid
        state.'"""
        ctx = setup_operator_station_shelved_pile()
        res = api.decommission_pile(ctx["pile"]["id"], PO)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Pile grid online/offline (PRD §3.1 + §3.8)
# ===========================================================================
class TestPileGridEvents:
    """PRD §3.1: 'A grid offline event sets the operational state to
    OFFLINE from any of IDLE, IN_USE, or FAULT; a grid online event
    returns it to IDLE from OFFLINE.'"""

    def test_grid_offline_event_moves_pile_to_offline(self, api):
        ctx = setup_operator_station_shelved_pile()
        emit_grid_pile_offline(ctx["pile"]["id"])
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "OFFLINE"
        # lifecycle_state must remain ON_SHELF (orthogonal axes).
        assert pile["lifecycle_state"] == "ON_SHELF"

    def test_grid_online_event_returns_offline_pile_to_idle(self, api):
        """PRD §3.1: 'a grid online event returns it to IDLE from
        OFFLINE.'"""
        ctx = setup_operator_station_shelved_pile()
        emit_grid_pile_offline(ctx["pile"]["id"])
        emit_grid_pile_online(ctx["pile"]["id"])
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"


# ===========================================================================
# Pile metadata patch (optimistic concurrency)
# ===========================================================================
class TestPilePatch:
    """PRD §3.1: 'Pile metadata (model_code, firmware_version,
    rated_power_kw) is updated by the StationOwner through the pile-edit
    capability and accepts an optional version for optimistic
    concurrency.'"""

    def test_patch_pile_updates_model_code(self, api):
        ctx = setup_operator_station_pile_off_shelf()
        before_version = ctx["pile"]["version"]
        pile = patch_pile(
            pile_id=ctx["pile"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
            model_code="NEW-MODEL",
        )
        assert pile["model_code"] == "NEW-MODEL"
        assert pile["version"] == before_version + 1

    def test_patch_pile_version_mismatch_rejected(self, api):
        """PRD §2.4: 'if the request body supplies a version value, the
        server compares it to the stored value and rejects the request
        with ERR_VERSION_CONFLICT on mismatch.'"""
        ctx = setup_operator_station_pile_off_shelf()
        from test_helpers import patch_pile_payload
        # Wrong version (much higher than current).
        res = api.patch_pile(
            ctx["pile"]["id"],
            patch_pile_payload(model_code="X", version=9999),
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)
