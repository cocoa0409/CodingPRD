"""Corner: optimistic concurrency (reassign, void) and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_assignment,
    create_booth,
    create_settlement,
    get_booth,
    get_transaction,
    get_zone,
    reconcile_settlement,
    report_sale,
    setup_active_assignment,
    setup_curated_with_booth,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]


class TestOccReassign:
    def test_occ_reassign_success_increments_version(self, api):
        """PRD §2.8: "Reassigning a booth assignment requires the request to carry
        `expected_assignment_version`, the client's last observed `version` of the
        assignment."
        PRD §3.3: "On success the old booth returns to `AVAILABLE`, the old zone's
        reserved totals decrease by the assignment's draw, the new booth is held
        and the new zone's totals increase, the assignment's `booth_id` and
        `zone_id` are refreshed, and its `version` increments by one while `status`
        stays put."

        Design: Corner/complexity_layers/occ_reassign_success_increments_version
        """
        scen = setup_curated_with_booth(name="OCC Fest", booth_overrides={"label": "N-01"})
        b1 = scen["booth"]
        b2 = create_booth(scen["zone"]["id"], label="N-02")
        asg = create_assignment(scen["app"]["id"], b1["id"], power_draw_amps=20)
        assert asg["version"] == 1

        data = validate_success(
            api.reassign_assignment(asg["id"],
                                    {"new_booth_id": b2["id"],
                                     "expected_assignment_version": asg["version"]},
                                    OPS)
        )
        assert data["version"] == 2, "version incremented by exactly 1"
        assert data["booth_id"] == b2["id"]
        assert data["status"] == "RESERVED", "status stays put on reassign"
        assert get_booth(b1["id"])["status"] == "AVAILABLE"
        assert get_booth(b2["id"])["status"] == "RESERVED"
        zone = get_zone(scen["zone"]["id"])
        assert zone["reserved_power_amps"] == 20, "20A moved within the same zone"

    def test_occ_reassign_stale_version_returns_412(self, api):
        """PRD §2.8: "If the assignment's current `version` has advanced beyond
        what the client observed — for example because another writer has already
        reassigned the same assignment, a legitimate state-preserving mutation
        that bumps the version — the reassignment is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/complexity_layers/occ_reassign_stale_version_returns_412
        """
        scen = setup_curated_with_booth(name="OCC2 Fest", booth_overrides={"label": "N-01"})
        b1 = scen["booth"]
        b2 = create_booth(scen["zone"]["id"], label="N-02")
        b3 = create_booth(scen["zone"]["id"], label="N-03")
        asg = create_assignment(scen["app"]["id"], b1["id"], power_draw_amps=20)
        stale_v = asg["version"]
        validate_success(
            api.reassign_assignment(asg["id"],
                                    {"new_booth_id": b2["id"],
                                     "expected_assignment_version": stale_v},
                                    OPS)
        )
        resp = api.reassign_assignment(asg["id"],
                                       {"new_booth_id": b3["id"],
                                        "expected_assignment_version": stale_v},
                                       OPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = validate_success(api.get_assignment(asg["id"], OPS))
        assert current["booth_id"] == b2["id"], "rejected reassign changed nothing"
        assert current["version"] == 2


class TestOccVoid:
    def test_occ_void_stale_settlement_version_returns_412(self, api):
        """PRD §2.8: "Voiding a point-of-sale transaction requires the request to
        carry `expected_settlement_version`, the client's last observed `version`
        of the settlement that parents the transaction's assignment. A mismatch
        with the settlement's current `version` is rejected with
        `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412). This matters because every
        successful void itself advances the settlement's `version` by one and
        recomputes its provisional figures".

        Design: Corner/complexity_layers/occ_void_stale_settlement_version_returns_412
        """
        scen = setup_active_assignment(name="OCC3 Fest")
        asg_id = scen["assignment"]["id"]
        t1 = report_sale(asg_id, scen["vendor"], 10000, "oc1")
        t2 = report_sale(asg_id, scen["vendor"], 20000, "oc2",
                         occurred_at="2026-07-10T15:00:00Z")
        stl = create_settlement(asg_id)
        stl = reconcile_settlement(stl["id"])
        captured_v = stl["version"]

        voided = validate_success(
            api.void_transaction(t1["id"], {"expected_settlement_version": captured_v}, FIN1)
        )
        assert voided["status"] == "VOIDED", "first void with the observed version succeeds"
        resp = api.void_transaction(t2["id"], {"expected_settlement_version": captured_v}, FIN1)
        validate_error(resp, ApiErrorId.ERR_STALE_SETTLEMENT_VERSION)
        assert get_transaction(t2["id"])["status"] == "REPORTED", "rejected void changed nothing"


class TestImmediateConsistency:
    def test_zone_totals_visible_immediately(self, api):
        """PRD §3.3: "A successful create stamps the assignment's `festival_id`
        and `zone_id` from the booth's chain, flips the booth from `AVAILABLE` to
        `RESERVED`, and raises the zone's reserved totals".
        PRD §3.1: "`reserved_power_amps`, the sum of `power_draw_amps` over the
        zone's assignments in `RESERVED`, `CONFIRMED`, or `ACTIVE`".

        Design: Corner/consistency_model/zone_totals_visible_immediately
        """
        scen = setup_curated_with_booth(name="ImmCon Fest")
        create_assignment(scen["app"]["id"], scen["booth"]["id"], power_draw_amps=20)
        zone = get_zone(scen["zone"]["id"])
        assert zone["reserved_power_amps"] == 20, "immediately-following read shows the reservation"
