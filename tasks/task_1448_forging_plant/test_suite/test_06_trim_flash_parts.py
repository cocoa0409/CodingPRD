"""Trim tickets: flash-yield disposition boundary, per-part net allocation with
residual, and the acceptance cascade to PRODUCED + cert creation (PRD §3.6)."""
import pytest

from test_helpers import (
    cut_billets,
    get_success_data,
    install_die,
    new_alloy,
    new_certified_heat,
    new_die_set,
    new_forge_run,
    new_furnace,
    new_ready_charges,
    new_work_center,
    new_work_order,
    open_trim_ticket,
    order_parts,
    record_heat,
    record_trim,
    setup_production_ctx,
    start_run,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]
SP = TEST_USERS["sales_planner_headers"]


def _setup_two_run_trim_scenario(api):
    """Twenty billets in two READY charges (10 + 10); one order (qty 20) with
    runs A (09:00-10:30) and B (11:00-12:30, exactly the 30-minute gap) both
    driven to FORGED with ten parts each; a DRAFT trim ticket open per run."""
    alloy = new_alloy()
    heat = new_certified_heat(alloy["id"], "H-5101")
    billets = cut_billets(heat["id"], 20.0, 20)
    furnace = new_furnace()
    ids = [b["id"] for b in billets]
    charges = new_ready_charges(
        furnace["id"],
        [
            (ids[:10], "2026-08-02T08:00:00Z", "2026-08-02T11:00:00Z"),
            (ids[10:], "2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z"),
        ],
    )
    die = new_die_set("DIE-16")
    wc = new_work_center("WC-1")
    install_die(die["id"], wc["id"])
    wo = new_work_order(alloy["id"], "WO-13", ordered_qty=20)
    runs = []
    tickets = []
    for i, (start, end) in enumerate([
        ("2026-08-03T09:00:00Z", "2026-08-03T10:30:00Z"),
        ("2026-08-03T11:00:00Z", "2026-08-03T12:30:00Z"),
    ]):
        run = new_forge_run(wo["id"], die["id"], start, end, 10,
                            work_center_id=wc["id"])
        start_run(run["id"])
        record_heat(run["id"], charges[i]["id"], ids[i * 10:(i + 1) * 10],
                    parts_good=10)
        get_success_data(api.finish_forging(run["id"], FORGE))
        runs.append(get_success_data(api.get_forge_run(run["id"], FORGE)))
        tickets.append(open_trim_ticket(run["id"]))
    return {"alloy": alloy, "heat": heat, "billets": billets, "wo": wo,
            "runs": runs, "tickets": tickets}


class TestFlashYieldBoundary:
    def test_flash_yield_exactly_at_allowance_accepted(self, api):
        """PRD §3.6: "A ratio strictly greater than the allowance yields
        `FLAGGED`; a ratio exactly equal to the allowance is still
        `ACCEPTED`."
        PRD §3.6: "The displayed `flash_yield_pct` is the flash weight divided
        by the gross, times one hundred, rounded half-up to two decimal places
        — but the disposition compares the unrounded ratio against the alloy's
        `flash_allowance_pct`."

        48.00 flash on 400.00 gross is exactly 12.00% == the 12.0% allowance.

        Design: Difficulty/boundary_precision_check/flash_yield_exactly_at_allowance
        """
        ctx = _setup_two_run_trim_scenario(api)
        ticket = record_trim(ctx["tickets"][0]["id"], 400.00, 340.00, 12.00)
        assert ticket["flash_scrap_lbs"] == pytest.approx(48.00, abs=1e-9), (
            f"400.00 - 340.00 - 12.00 = 48.00, got {ticket['flash_scrap_lbs']}"
        )
        assert ticket["status"] == "ACCEPTED", (
            f"equality with the allowance must not flag, got {ticket['status']}"
        )
        assert ticket["flash_yield_pct"] == pytest.approx(12.00, abs=1e-9)

    def test_flash_yield_above_allowance_flagged_display_rounds_down(self, api):
        """PRD §3.6: "A ratio strictly greater than the allowance yields
        `FLAGGED`; a ratio exactly equal to the allowance is still
        `ACCEPTED`."
        PRD §3.6: "The displayed `flash_yield_pct` is the flash weight divided
        by the gross, times one hundred, rounded half-up to two decimal places
        — but the disposition compares the unrounded ratio against the alloy's
        `flash_allowance_pct`."

        48.01 flash on 400.00 gross is 12.0025% — strictly above the allowance
        even though the displayed percentage rounds to 12.00.

        Design: Difficulty/boundary_precision_check/flash_yield_exactly_at_allowance
        """
        ctx = _setup_two_run_trim_scenario(api)
        ticket = record_trim(ctx["tickets"][1]["id"], 400.00, 339.99, 12.00)
        assert ticket["flash_scrap_lbs"] == pytest.approx(48.01, abs=1e-9), (
            f"400.00 - 339.99 - 12.00 = 48.01, got {ticket['flash_scrap_lbs']}"
        )
        assert ticket["status"] == "FLAGGED", (
            f"12.0025%% strictly exceeds the 12.0%% allowance, got {ticket['status']}"
        )
        assert ticket["flash_yield_pct"] == pytest.approx(12.00, abs=1e-9), (
            "the displayed value rounds to 12.00 while the unrounded ratio "
            "drove the FLAGGED disposition"
        )


class TestTrimAcceptanceCascade:
    def test_trim_accept_trims_parts_and_promotes_order(self, api):
        """PRD §3.6: "All covered parts move from `FORGED` to `TRIMMED`, the
        order's `trimmed_qty` and `trimmed_net_lbs` are recomputed, and when
        `trimmed_qty` reaches `ordered_qty` the order turns `PRODUCED` —
        auto-creating one `PENDING` quality cert per distinct `mill_heat_id`
        among the order's serialized parts that lacks an existing cert."

        Ten parts forged from one heat; 430.00 net over 10 parts is 43.00
        each; the tenth trim crosses ordered_qty.

        Design: Difficulty/transitive_cascade/trim_accept_bubbles_to_produced_and_cert_creation
        """
        ctx = setup_production_ctx(qty=10, trim_gross=480.00, trim_net=430.00,
                                   trim_pierce=8.00)
        assert ctx["ticket"]["status"] == "ACCEPTED"
        parts = order_parts(ctx["wo"]["id"])
        assert len(parts) == 10
        for part in parts:
            assert part["status"] == "TRIMMED", (
                f"part {part['serial_seq']} must be TRIMMED, got {part['status']}"
            )
            assert part["net_weight_lbs"] == pytest.approx(43.00, abs=1e-9), (
                f"430.00 / 10 = 43.00 per part, got {part['net_weight_lbs']}"
            )
        wo = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo["status"] == "PRODUCED"
        assert wo["trimmed_qty"] == 10

    def test_trim_accept_auto_creates_pending_cert(self, api):
        """PRD §3.6: "All covered parts move from `FORGED` to `TRIMMED`, the
        order's `trimmed_qty` and `trimmed_net_lbs` are recomputed, and when
        `trimmed_qty` reaches `ordered_qty` the order turns `PRODUCED` —
        auto-creating one `PENDING` quality cert per distinct `mill_heat_id`
        among the order's serialized parts that lacks an existing cert."

        Exactly one cert appears, bound to the single heat the parts were
        forged from.

        Design: Difficulty/transitive_cascade/trim_accept_bubbles_to_produced_and_cert_creation
        """
        ctx = setup_production_ctx(qty=10, trim_gross=480.00, trim_net=430.00,
                                   trim_pierce=8.00)
        certs, meta = validate_paginated(
            api.list_work_order_certs(ctx["wo"]["id"], QE))
        assert len(certs) == 1 and meta["total_count"] == 1, (
            f"exactly one cert must be auto-created, got {len(certs)}"
        )
        assert certs[0]["status"] == "PENDING"
        assert certs[0]["mill_heat_id"] == ctx["heat"]["id"]


class TestPerPartNetAllocation:
    def _setup_residual_scenario(self, api):
        """Four parts forged from one heat; DRAFT trim ticket open."""
        return setup_production_ctx(
            qty=4, cut_length_in=12.0,
            order_overrides={
                "customer_name": "TinyParts",
                "part_number": "PN-025",
                "part_net_weight_lbs": 25.00,
                "billet_weight_lbs": 30.00,
            },
            record_trim_ticket=False,
        )

    def test_per_part_residual_goes_to_largest_serial(self, api):
        """PRD §3.6: "The ticket's `net_trimmed_lbs` is divided by the number
        of the run's parts currently in `FORGED`; the quotient, rounded half-up
        to two decimal places, is assigned as `net_weight_lbs` to every covered
        part (null until this moment). The residual — the ticket's net weight
        minus the per-part amount multiplied by the part count, itself rounded
        half-up to two decimals — is added to the covered part carrying the
        largest `serial_seq`. The rounding order is pinned: the per-part amount
        is rounded first, and only then is the residual reconciled."

        100.05 over 4 parts rounds to 25.01 per part; the +0.01 residual lands
        on serial_seq 4.

        Design: Difficulty/combinatorial_formula/per_part_net_weight_residual_allocation
        """
        ctx = self._setup_residual_scenario(api)
        ticket = open_trim_ticket(ctx["run"]["id"])
        recorded = record_trim(ticket["id"], 110.00, 100.05, 2.00)
        assert recorded["status"] == "ACCEPTED", (
            f"7.95 flash on 110.00 gross is 7.23%% <= 12.0%%, got "
            f"{recorded['status']}"
        )
        parts = order_parts(ctx["wo"]["id"])
        by_seq = {p["serial_seq"]: p for p in parts}
        for seq in (1, 2, 3):
            assert by_seq[seq]["net_weight_lbs"] == pytest.approx(25.01, abs=1e-9), (
                f"serial {seq} gets the rounded per-part amount 25.01, got "
                f"{by_seq[seq]['net_weight_lbs']}"
            )
        assert by_seq[4]["net_weight_lbs"] == pytest.approx(25.02, abs=1e-9), (
            f"largest serial_seq absorbs the +0.01 residual: 25.02, got "
            f"{by_seq[4]['net_weight_lbs']}"
        )

    def test_per_part_allocation_sums_to_ticket_net(self, api):
        """PRD §3.6: "The ticket's `net_trimmed_lbs` is divided by the number
        of the run's parts currently in `FORGED`; the quotient, rounded half-up
        to two decimal places, is assigned as `net_weight_lbs` to every covered
        part (null until this moment). The residual — the ticket's net weight
        minus the per-part amount multiplied by the part count, itself rounded
        half-up to two decimals — is added to the covered part carrying the
        largest `serial_seq`."
        PRD §3.5: "Trimmed output accumulates in `trimmed_net_lbs`, the summed
        `net_trimmed_lbs` over the `ACCEPTED` trim tickets of the order's
        runs."

        The residual reconciliation leaves zero drift: part nets sum exactly to
        the ticket's net.

        Design: Difficulty/combinatorial_formula/per_part_net_weight_residual_allocation
        """
        ctx = self._setup_residual_scenario(api)
        ticket = open_trim_ticket(ctx["run"]["id"])
        recorded = record_trim(ticket["id"], 110.00, 100.05, 2.00)
        assert recorded["status"] == "ACCEPTED"
        parts = order_parts(ctx["wo"]["id"])
        total = sum(p["net_weight_lbs"] for p in parts)
        assert total == pytest.approx(100.05, abs=1e-9), (
            f"part nets must sum to the ticket net 100.05 with no drift, got {total}"
        )
        for part in parts:
            assert part["status"] == "TRIMMED"
        wo = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo["trimmed_net_lbs"] == pytest.approx(100.05, abs=1e-9)
        assert wo["status"] == "PRODUCED"
