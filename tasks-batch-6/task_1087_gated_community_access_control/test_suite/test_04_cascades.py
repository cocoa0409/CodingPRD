"""Cross-entity cascades: the delinquency cascade (violation -> suspend ->
reservation cancel) and the move-out cascade (resident -> vehicle -> decal).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_vehicle, issue_decal, create_amenity, book_reservation,
    issue_violation, setup_community_and_resident,
    ADMIN,
)


class TestDelinquencyCascade:
    """Tests for the delinquency_suspend_cancels_reservations_depth3 rule (see per-test Design tags)."""

    def _setup_resident_with_booking_then_delinquent(self):
        set_clock("2026-06-03T08:00:00Z")
        community, resident = setup_community_and_resident(resident_overrides={"full_name": "Dee Delinquent"})
        amenity = create_amenity(community["id"], name="Main Pool", amenity_type="POOL",
                                 capacity=10, hourly_fee_cents=1000, deposit_cents=0,
                                 open_hour=6, close_hour=22)
        resv = book_reservation(amenity["id"], resident["id"],
                                start_at="2026-06-05T10:00:00Z", end_at="2026-06-05T12:00:00Z",
                                party_size=2)
        issue_violation(community["id"], resident["id"],
                        violation_type="GATE_TAILGATING", base_fine_cents=25000)
        return community, resident, amenity, resv

    def test_delinquency_auto_suspends_resident(self, api):
        """PRD §2.8: "when a resident's outstanding balance rises to or above the
        delinquency threshold while the resident is `ACTIVE`, the resident is
        automatically driven from `ACTIVE` to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/delinquency_suspend_cancels_reservations_depth3
        """
        _, resident, _, _ = self._setup_resident_with_booking_then_delinquent()
        r = validate_success(api.get_resident(resident["id"], ADMIN))
        assert r["standing"] == "DELINQUENT"
        assert r["status"] == "SUSPENDED"

    def test_suspension_cancels_booked_reservation(self, api):
        """PRD §2.8: "That suspension itself has two secondary effects — every one
        of the resident's amenity reservations still in `BOOKED` or `CHECKED_IN`
        is moved to `CANCELLED`, releasing its `party_size` from the amenity's
        concurrent load".

        Design: Difficulty/transitive_cascade/delinquency_suspend_cancels_reservations_depth3
        """
        _, _, _, resv = self._setup_resident_with_booking_then_delinquent()
        r = validate_success(api.get_reservation(resv["id"], ADMIN))
        assert r["status"] == "CANCELLED"


class TestMoveOutCascade:
    """Tests for the moveout_vehicle_decal_cascade_depth2 rule (see per-test Design tags)."""

    def _setup_resident_vehicle_decal_then_moveout(self, api):
        community, resident = setup_community_and_resident(resident_overrides={"full_name": "Moe Mover"})
        vehicle = create_vehicle(resident["id"], plate="CAR001", plate_state="CA")
        decal = issue_decal(vehicle["id"], vehicle["version"], tier="RESIDENT",
                            valid_from="2026-05-01T00:00:00Z", valid_until="2027-05-01T00:00:00Z")
        moved = validate_success(api.transition_resident(resident["id"], {"to_status": "MOVED_OUT"}, ADMIN))
        return community, resident, vehicle, decal, moved

    def test_moveout_inactivates_vehicle(self, api):
        """PRD §2.8: "when a resident is moved to `MOVED_OUT`, each of the
        resident's vehicles that is `ACTIVE` is set to `INACTIVE`, and each such
        vehicle transitioning to `INACTIVE` in turn revokes that vehicle's own
        `ACTIVE` decal to `REVOKED`."

        Design: Difficulty/transitive_cascade/moveout_vehicle_decal_cascade_depth2
        """
        _, _, vehicle, _, moved = self._setup_resident_vehicle_decal_then_moveout(api)
        assert moved["status"] == "MOVED_OUT"
        v = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
        assert v["status"] == "INACTIVE"

    def test_moveout_revokes_decal(self, api):
        """PRD §2.8: "each such vehicle transitioning to `INACTIVE` in turn
        revokes that vehicle's own `ACTIVE` decal to `REVOKED`."

        Design: Difficulty/transitive_cascade/moveout_vehicle_decal_cascade_depth2
        """
        _, _, _, decal, _ = self._setup_resident_vehicle_decal_then_moveout(api)
        d = validate_success(api.get_decal(decal["id"], ADMIN))
        assert d["status"] == "REVOKED"


def test_reinstate_still_owing_resident_returns_not_eligible(api):
    """PRD §3.1: "Reinstating a suspended resident is only permitted when their
    `outstanding_balance_cents` is strictly below the delinquency threshold; an
    attempt to reinstate a resident whose balance is at or above that threshold is
    refused with `ERR_RESIDENT_NOT_ELIGIBLE`."

    Design: Corner/errors/error_resident_not_eligible_reinstate_present
    """
    community, resident = setup_community_and_resident(resident_overrides={"full_name": "Still Owing"})
    issue_violation(community["id"], resident["id"],
                    violation_type="GATE_TAILGATING", base_fine_cents=30000)  # auto-suspends
    suspended = validate_success(api.get_resident(resident["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    validate_error(api.transition_resident(resident["id"], {"to_status": "ACTIVE"}, ADMIN),
                   ApiErrorId.ERR_RESIDENT_NOT_ELIGIBLE.value)
