"""The slot-close cascade: visits mutated, money and credits settled, and
compensation points granted per affected guardian (PRD §3.3)."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    set_clock, reset_clock,
    create_plus_plan, setup_staff_trio, create_open_slot,
    register_guardian, guardian_headers, enroll_guardian, sign_waiver,
    add_child, create_reservation, check_in_visit, get_visit_fresh,
    get_guardian_fresh, TEST_DEFAULTS,
)
from test_helpers import api_client


def _setup_three_family_slot():
    """OPEN slot with: G1 prepaid 90-min reservation (quote 2100), G2 PLUS
    credit reservation (one credit held), G3 walk-in checked in at 14:05.
    Clock advanced to 14:35."""
    reset_clock()
    staff = setup_staff_trio()
    mh, fh = staff["mgr_headers"], staff["fd_headers"]
    plan = create_plus_plan()
    slot = create_open_slot(mh)

    g1 = register_guardian("G A", "ga@x.com", "101")
    c1 = add_child(g1, "Kid A", "2020-01-15")
    sign_waiver(g1)
    v1 = create_reservation(g1, slot, c1, booked_duration_minutes=90)
    validate_success(api_client.pay_visit(v1["id"], guardian_headers(g1)), 200)

    g2 = register_guardian("G B", "gb@x.com", "102")
    g2 = enroll_guardian(g2, plan["id"])
    sign_waiver(g2)
    c2 = add_child(g2, "Kid B", "2019-05-20")
    v2 = create_reservation(g2, slot, c2, booked_duration_minutes=60,
                            use_credit=True)

    g3 = register_guardian("G C", "gc@x.com", "103")
    c3 = add_child(g3, "Kid C", "2021-03-10")
    sign_waiver(g3)
    set_clock(TEST_DEFAULTS["CHECKIN_TIME"])  # 14:05
    v3 = get_success_data(api_client.create_visit(
        {"session_slot_id": slot["id"], "child_id": c3["id"],
         "guardian_id": g3["id"], "visit_type": "WALK_IN",
         "sock_method": "OWN_GRIP_SOCKS"}, fh))
    assert v3["admission_status"] == "CHECKED_IN"

    set_clock("2026-06-06T14:35:00Z")
    return {"staff": staff, "slot": slot,
            "g1": g1, "v1": v1, "g2": g2, "v2": v2, "g3": g3, "v3": v3}


class TestEmergencySlotCloseCascade:
    def test_close_cascades_visits_credits_refunds_and_compensation(self, api):
        """PRD §3.3: "Hop 1 moves every `RESERVED` visit on the slot to
        `CANCELLED` and every `CHECKED_IN` visit to `EVACUATED`, stamping
        `checked_out_at` from the logical clock. Hop 2 settles money and
        credits: each cancelled `RESERVED` credit visit releases its hold,
        each cancelled prepaid visit flips `payment_status` to `REFUNDED`,
        and each `EVACUATED` visit is charged a compassionate evacuation rate
        — one half of the tiered per-minute charge for the elapsed minutes
        (§3.5), rounded half-up — recorded as `final_charge_cents`".
        PRD §3.3: "Hop 3 compensates families: every guardian with a visit
        cancelled or evacuated by this close receives a +200-point
        `ADJUSTMENT` entry in their loyalty ledger, recomputing
        `points_balance` and `lifetime_points`."

        Design: Difficulty/transitive_cascade/emergency_slot_close_cascade
        """
        ctx = _setup_three_family_slot()
        mh = ctx["staff"]["mgr_headers"]

        closed = validate_success(api.close_session_slot(
            ctx["slot"]["id"], {"reason": "EMERGENCY"}, mh), 200)
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "EMERGENCY"

        v1 = get_visit_fresh(ctx["v1"]["id"], mh)
        assert v1["admission_status"] == "CANCELLED"
        assert v1["payment_status"] == "REFUNDED"  # prepaid 2100 returned

        v2 = get_visit_fresh(ctx["v2"]["id"], mh)
        assert v2["admission_status"] == "CANCELLED"
        g2 = get_guardian_fresh(ctx["g2"]["id"], mh)
        assert g2["credits_held"] == 0, "hold released, not consumed"
        assert g2["credits_available"] == 8
        assert g2["credits_consumed"] == 0

        v3 = get_visit_fresh(ctx["v3"]["id"], mh)
        assert v3["admission_status"] == "EVACUATED"
        # elapsed 30 min at 14:35 -> tiered 30*20 = 600; half = 300.
        assert v3["final_charge_cents"] == 300

        for g in (ctx["g1"], ctx["g2"], ctx["g3"]):
            fresh = get_guardian_fresh(g["id"], mh)
            assert fresh["points_balance"] == 200, \
                "each affected guardian receives the +200 compensation"

    def test_manager_close_cancels_unpaid_visit_without_refund_record(self, api):
        """PRD §3.4: "Note that only prepaid visits ever reach `REFUNDED`: a
        `PENDING` unpaid visit that is cancelled simply becomes `CANCELLED`
        with no refund record."
        PRD §3.3: "Closing a slot — a `Manager` action carrying a `reason` of
        `MANAGER_CLOSE` or `EMERGENCY`" and "the slot's `close_reason` is
        recorded".

        Design: Difficulty/transitive_cascade/emergency_slot_close_cascade
        """
        ctx = _setup_three_family_slot()
        mh = ctx["staff"]["mgr_headers"]

        closed = validate_success(api.close_session_slot(
            ctx["slot"]["id"], {"reason": "MANAGER_CLOSE"}, mh), 200)
        assert closed["close_reason"] == "MANAGER_CLOSE"

        # G2's credit reservation is cancelled; its payment dimension was
        # PENDING and must not gain a refund record.
        v2 = get_visit_fresh(ctx["v2"]["id"], mh)
        assert v2["admission_status"] == "CANCELLED"
        assert v2["payment_status"] == "PENDING"

        # The evacuated walk-in is charged the compassionate half rate:
        # elapsed 30 min -> tiered 600 -> 300.
        v3 = get_visit_fresh(ctx["v3"]["id"], mh)
        assert v3["admission_status"] == "EVACUATED"
        assert v3["final_charge_cents"] == 300
        assert v3["checked_out_at"] is not None
