"""Equipment registration, profile update, retire transition.

PRD §3.1 (registration, update, retire), §2.4 (version/OCC).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_equipment,
    create_equipment_payload,
    create_lab_with_owner,
    create_verified_user,
    make_lab_owner_headers,
    register_equipment,
    setup_basic_scenario,
    update_equipment_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# POST /equipment (PRD §3.1)
# ===========================================================================
class TestRegisterEquipment:
    """PRD §3.1: 'A LabOwner registers an Equipment resource under their
    owned lab ... Equipment is registered with status AVAILABLE and
    active_billing_rule_id null; the latter is filled in when the first
    billing rule is published.'
    """

    def test_register_sets_status_available_and_no_billing_rule(self, api):
        """PRD §3.1: 'Equipment is registered with status AVAILABLE and
        active_billing_rule_id null'."""
        lab, owner = create_lab_with_owner()
        eq = register_equipment(lab=lab, owner_user=owner)
        assert_equipment(eq)
        assert eq["status"] == "AVAILABLE"
        assert eq.get("active_billing_rule_id") is None

    def test_register_with_unowned_lab_rejected(self, api):
        """PRD §2.1: 'ownership checks on any Lab compare the lab's
        contact_user_id to X-User-ID' — a different LabOwner cannot
        register equipment under someone else's lab."""
        lab, _ = create_lab_with_owner()
        stranger = create_verified_user()
        res = api.create_equipment(
            create_equipment_payload(lab_id=lab["id"]),
            make_lab_owner_headers(stranger["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# PUT /equipment/{id} retire (PRD §3.1)
# ===========================================================================
class TestRetireEquipment:
    """PRD §3.1: 'Setting status to RETIRED is a terminal step: the
    equipment must have no BOOKED or CHECKED_IN reservations remaining,
    and any future-dated MaintenanceWindow rows still in SCHEDULED are
    cascaded to REJECTED because they can no longer be accepted.'
    """

    def test_retire_with_active_reservation_rejected(self, api):
        """PRD §3.1: 'the equipment must have no BOOKED or CHECKED_IN
        reservations remaining'."""
        from test_helpers import get_equipment, setup_scenario_with_reservation
        s = setup_scenario_with_reservation()
        current_eq = get_equipment(s["equipment"]["id"])
        res = api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                status="RETIRED", version=current_eq["version"],
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_retire_with_no_reservations_succeeds(self, api):
        """PRD §3.1: when no BOOKED or CHECKED_IN reservations remain the
        retire transition is permitted."""
        from test_helpers import get_equipment
        s = setup_basic_scenario()
        current_eq = get_equipment(s["equipment"]["id"])
        res = api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                status="RETIRED", version=current_eq["version"],
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        eq = validate_success(res, 200)
        assert eq["status"] == "RETIRED"


# ===========================================================================
# Optimistic concurrency (PRD §2.4)
# ===========================================================================
class TestEquipmentVersionConflict:
    """PRD §2.4: 'When supplied, the value must equal the current version
    of the targeted row at the moment of the write; a mismatch yields
    ERR_VERSION_CONFLICT at 409.'
    """

    def test_stale_version_rejected(self, api):
        """PRD §2.4: 'a mismatch yields ERR_VERSION_CONFLICT at 409'."""
        from test_helpers import get_equipment
        s = setup_basic_scenario()
        current_eq = get_equipment(s["equipment"]["id"])
        stale = current_eq["version"]
        # First update increments version.
        first = validate_success(api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                single_user_duration_limit_hours=12, version=stale,
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        ), 200)
        # Re-using the original (stale) version must conflict.
        res = api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                single_user_duration_limit_hours=14, version=stale,
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_version_increments_on_mutation(self, api):
        """PRD §2.4: 'Every successful mutation ... increments the
        affected row's version by 1'."""
        from test_helpers import get_equipment
        s = setup_basic_scenario()
        current_eq = get_equipment(s["equipment"]["id"])
        before = current_eq["version"]
        eq = validate_success(api.update_equipment(
            current_eq["id"],
            update_equipment_payload(
                single_user_duration_limit_hours=12, version=before,
            ),
            make_lab_owner_headers(s["owner_user"]["id"]),
        ), 200)
        assert eq["version"] == before + 1
