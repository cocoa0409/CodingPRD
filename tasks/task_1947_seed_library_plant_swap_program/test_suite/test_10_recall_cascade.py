"""Certify-FAIL recall cascade: lot -> packets -> checkouts (three hops)."""
from test_helpers import (
    api_client,
    borrow_packet,
    certify_test,
    create_member,
    get_lot,
    get_packet,
    record_test,
    setup_active_lot,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_recalled_lot():
    """ACTIVE lot (300 seeds, certified 90.00) with 3 packets of 10:
    packet[0] AVAILABLE, packet[1] and packet[2] CHECKED_OUT to two members.
    Lot then rechecked and a failing assay (40/100 = 40.00) recorded."""
    ctx = setup_active_lot(
        seeds_received=300,
        provisional_viability_pct=90.00,
        num_packets=3,
        seeds_per_packet=10,
        label_stock=10,
    )
    member1 = create_member(ctx["site"]["id"])
    member2 = create_member(ctx["site"]["id"])
    c1 = borrow_packet(member1, ctx["packet_ids"][1])
    c2 = borrow_packet(member2, ctx["packet_ids"][2])
    resp = api_client.recheck_seed_lot(ctx["lot"]["id"], ADMIN)
    validate_success(resp, 200)
    failing = record_test(
        ctx["lot"]["id"], ctx["volunteer"]["id"],
        seeds_tested=100, sprouted_count=40,
    )
    assert failing["result_pct"] == 40.0
    return ctx, member1, member2, c1, c2, failing


class TestRecallCascade:
    def test_certify_fail_recalls_all_lot_packets(self):
        """PRD §3.3: "A `FAIL` on a lot that has already circulated packets (a
        post-recheck failure) triggers the recall cascade. Hop one: every
        packet of the lot in `AVAILABLE`, `CHECKED_OUT`, or `RETURNED` becomes
        `RECALLED`, each packet's `version` advancing."
        PRD §3.3: "The lot itself returns to `QUARANTINE` and may be tested
        again."

        Design: Difficulty/transitive_cascade/certify_fail_recall_cascade_depth3
        """
        ctx, _, _, _, _, failing = _setup_recalled_lot()
        certified = certify_test(failing["id"], "FAIL")
        assert certified["status"] == "CERTIFIED"
        lot = get_lot(ctx["lot"]["id"])
        assert lot["status"] == "QUARANTINE", (
            f"hop 1 origin: lot returns to QUARANTINE, got {lot['status']}"
        )
        for pid in ctx["packet_ids"]:
            packet = get_packet(pid)
            assert packet["status"] == "RECALLED", (
                f"hop 1: every AVAILABLE/CHECKED_OUT/RETURNED packet becomes "
                f"RECALLED, got {packet['status']}"
            )

    def test_certify_fail_flags_recall_required_on_live_checkouts(self):
        """PRD §3.3: "Hop two: every checkout holding a recalled packet while
        itself in `ACTIVE` or `OVERDUE` has its `recall_required` flag set
        true, each such checkout's `version` advancing. Hop three: the members
        holding those flagged checkouts are counted by the next daily sweep —
        the cascade performs no immediate member mutation; standing is
        recomputed only when the sweep runs."

        Design: Difficulty/transitive_cascade/certify_fail_recall_cascade_depth3
        """
        ctx, member1, member2, c1, c2, failing = _setup_recalled_lot()
        certify_test(failing["id"], "FAIL")
        for checkout_id in (c1["id"], c2["id"]):
            checkout = validate_success(
                api_client.get_checkout(checkout_id, ADMIN), 200
            )
            assert checkout["recall_required"] is True, (
                f"hop 2: checkout holding a recalled packet must be flagged, "
                f"got {checkout['recall_required']}"
            )
        for member in (member1, member2):
            after = validate_success(
                api_client.get_member(member["id"], ADMIN), 200
            )
            assert after["status"] == "ACTIVE", (
                "hop 3: the cascade performs no immediate member mutation"
            )
