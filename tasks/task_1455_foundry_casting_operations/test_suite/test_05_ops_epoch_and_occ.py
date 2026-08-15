"""Ops-epoch checkpoint effects (slot expiry, cooling boundary, order closeout)
and optimistic-concurrency guards on heats and foundries."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_casting,
    add_charges,
    advance_casting,
    book_slot,
    complete_slot,
    create_certified_heat,
    create_foundry,
    create_furnace,
    create_heat,
    create_mold,
    file_claim,
    get_foundry,
    get_heat,
    get_mold,
    get_order,
    get_pour_slot,
    list_castings,
    pour_molds,
    record_sample,
    run_ops,
    set_clock,
    setup_shop,
    tap,
    validate_error,
    validate_success,
    virgin_addition,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
MELT = TEST_USERS["melt_supervisor_headers"]
SPECTRO_1 = TEST_USERS["spectro_1_headers"]
SPECTRO_2 = TEST_USERS["spectro_2_headers"]


class TestRunOpsSlotExpiry:
    def test_run_ops_expires_stale_booked_slot(self, api):
        """PRD §3.1: "every `BOOKED` pour slot whose `end_at` lies before the
        logical now transitions `BOOKED → EXPIRED` and its molds' `pour_slot_id`
        links are cleared (the molds remain `ASSEMBLED`)" and "The sweep
        increments `ops_run_index` by one and increments the foundry's `version`
        by one."

        Design: Corner/state_machines/run_ops_expires_stale_booked_slot
        """
        ctx = setup_shop()
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold["id"]])
        index_before = get_foundry(ctx["foundry"]["id"])["ops_run_index"]

        set_clock("2026-08-10T12:00:00Z")  # past end_at 11:00
        run_ops(ctx["foundry"]["id"])

        assert get_pour_slot(slot["id"])["status"] == "EXPIRED"
        mold_after = get_mold(mold["id"])
        assert mold_after["status"] == "ASSEMBLED"
        assert mold_after["pour_slot_id"] is None
        assert get_foundry(ctx["foundry"]["id"])["ops_run_index"] == index_before + 1


class TestRunOpsCoolingBoundary:
    def test_run_ops_cools_mold_at_exact_cooling_boundary(self, api):
        """PRD §3.1: "every `POURED` mold whose cooling period has fully elapsed
        — the logical now at or after its `poured_at` plus `cooling_hours` —
        transitions `POURED → COOLED`"

        Design: Corner/state_machines/run_ops_cools_mold_at_exact_cooling_boundary
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        mold_id = ctx["molds"][0]["id"]
        # Poured at 10:30 with cooling_hours 2: due 12:30:00.
        set_clock("2026-08-10T12:29:59Z")
        run_ops(ctx["foundry"]["id"])
        assert get_mold(mold_id)["status"] == "POURED"

        set_clock("2026-08-10T12:30:00Z")
        run_ops(ctx["foundry"]["id"])
        assert get_mold(mold_id)["status"] == "COOLED"


class TestRunOpsOrderCloseout:
    def test_run_ops_closes_fulfilled_order_without_open_claims(self, api):
        """PRD §3.1: "every `FULFILLED` order with no claim in `FILED`,
        `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED` referencing it
        transitions `FULFILLED → CLOSED`"

        Design: Corner/state_machines/run_ops_closes_fulfilled_order_without_open_claims
        """
        # Two orders, one shared pour: order A fulfills with no claims; order B
        # fulfills but carries a FILED claim.
        ctx = setup_shop()
        order_b = create_second_order(ctx)
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        tap(heat, 500)
        mold_a = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                             ctx["order"]["id"], sand_weight_kg=50,
                             metal_weight_kg=200, cooling_hours=2)
        mold_b = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                             order_b["id"], sand_weight_kg=50,
                             metal_weight_kg=200, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold_a["id"], mold_b["id"]])
        set_clock("2026-08-10T10:30:00Z")
        complete_slot(slot["id"])
        ca = list_castings({"mold_id": mold_a["id"]})[0]
        cb = list_castings({"mold_id": mold_b["id"]})[0]
        set_clock("2026-08-10T13:00:00Z")
        run_ops(ctx["foundry"]["id"])
        api.shakeout_mold(mold_a["id"], TEST_USERS["line_operator_headers"])
        api.shakeout_mold(mold_b["id"], TEST_USERS["line_operator_headers"])
        advance_casting(ca["id"], steps=3)
        advance_casting(cb["id"], steps=3)
        accept_casting(ca["id"])
        accept_casting(cb["id"])
        assert get_order(ctx["order"]["id"])["status"] == "FULFILLED"
        assert get_order(order_b["id"])["status"] == "FULFILLED"

        claim_ctx = dict(ctx)
        claim_ctx["order"] = get_order(order_b["id"])
        file_claim(claim_ctx, claim_type="DEFECT", claim_qty=1,
                   claimed_amount_cents=1000)

        run_ops(ctx["foundry"]["id"])
        assert get_order(ctx["order"]["id"])["status"] == "CLOSED"
        assert get_order(order_b["id"])["status"] == "FULFILLED"


def create_second_order(ctx):
    """A second order on the same pattern, placed by the admin for the customer."""
    from test_helpers import create_order
    return create_order(ctx["foundry"]["id"], ctx["customer"]["id"],
                        ctx["pattern"]["id"], quantity=1)


class TestOptimisticConcurrency:
    def test_occ_sample_with_stale_heat_version_rejected(self, api):
        """PRD §2.6: "A `POST /api/heats/{id}/samples` request must carry
        `expected_heat_version` holding the `version` of the heat as the client
        last observed it. Because a new spectro sample legitimately supersedes
        the previous reading, a client holding a stale observed version must
        re-read the heat before submitting; if the heat's current `version` does
        not match `expected_heat_version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_sample_with_stale_heat_version_rejected
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        heat = create_heat(foundry["id"], furnace["id"])
        heat = add_charges(heat, [virgin_addition(1000, {"C": 3.40})])
        observed_version = heat["version"]

        # First sample FAILS (4.50 > spec max 3.6): CHARGING -> SAMPLED, and
        # the version bumps. SAMPLED is a legal sampling state per PRD §3.4
        # ("Sampling is accepted only while the heat is `CHARGING` or
        # `SAMPLED`"), so the stale-version rejection below cannot be masked
        # by the state gate.
        first = record_sample(heat, {"C": 4.50}, SPECTRO_1)
        assert first["status"] == "SAMPLED"
        assert first["last_sample_passed"] is False

        # Second sample carrying the stale observed version is rejected.
        res = api.add_heat_sample(
            heat["id"],
            {"expected_heat_version": observed_version, "reading": {"C": 3.41}},
            SPECTRO_2)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        after = get_heat(heat["id"])
        assert after["last_sample_reading"]["C"] == pytest.approx(4.50, abs=1e-9)

    def test_occ_run_ops_with_stale_foundry_version_rejected(self, api):
        """PRD §2.6: "A `POST /api/foundries/{id}/run-ops` request must carry
        `expected_foundry_version`. Epoch advancement makes expiry, cooling, and
        closeout decisions that must observe current state; a mismatch with the
        foundry's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the foundry before retrying."

        Design: Corner/cross_cutting_layers/occ_run_ops_with_stale_foundry_version_rejected
        """
        foundry = create_foundry()
        observed_version = foundry["version"]
        first = validate_success(api.run_ops(
            foundry["id"], {"expected_foundry_version": observed_version}, ADMIN))
        assert first["ops_run_index"] == 1

        res = api.run_ops(foundry["id"],
                          {"expected_foundry_version": observed_version}, ADMIN)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
