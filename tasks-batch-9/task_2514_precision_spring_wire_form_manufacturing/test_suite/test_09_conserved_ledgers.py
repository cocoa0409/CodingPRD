"""Ledgers that must close on their own total after every compensating hop.

Three totals in the shop never move: the kilograms a heat was received with, the
cents a coiling tool was capitalised at, and the pieces a customer program was
opened against. Each of these modules' scenarios walks an operation and then the
operation that undoes it — a run opened and abandoned, a lot shipped and taken
back, a lot quarantined and released — and checks the partition at every hop
rather than only at the end, because an implementation that patches buckets
incrementally instead of transferring between them diverges exactly there.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

# The heat is received oversized so a 1 000-piece reservation is comfortably
# affordable twice over, and both coiling windows sit in the logical future.
HEAT_RECEIVED_KG = 500.0
SHORT_RUN_PIECES = 1_000
RESERVED_KG = 21.821
ON_HAND_AFTER_RESERVATION_KG = 478.179
CONSUMED_KG = 21.185
ON_HAND_AFTER_COMPLETION_KG = 478.815
RETURNED_ALLOWANCE_KG = 0.636

SECOND_WINDOW_START = "2026-08-05T12:45:00Z"
SECOND_WINDOW_END = "2026-08-05T16:00:00Z"
SECOND_WINDOW_CLOCK = "2026-08-05T13:00:00Z"


def _coiler_with_a_large_heat(api: ApiClient) -> X.World:
    """An ACTIVE setup on COIL-12 over a 500 kg CERTIFIED heat of D1's grade."""
    return X.build_world(
        api,
        "certified_wire",
        program={
            "program_code": "PGM-IND-11",
            "customer_name": "Bramble Industrial Supply",
            "committed_pieces": 100_000,
        },
        design={"part_number": "D1-MASS"},
        tooling={"tool_code": "TL-D1-M", "original_cost_cents": 1_200_000},
        machine={"machine_code": "COIL-12"},
        wire_lot={"heat_number": "HT-D1-M", "received_kg": HEAT_RECEIVED_KG},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )


def test_wire_ledger_closes_on_received_mass_at_every_posting(api: ApiClient) -> None:
    """A heat's three buckets sum to its receipt weight after every hop.

    The scenario reserves against the heat, abandons the run so the reservation
    comes back, reserves the identical figure again on a fresh window, and then
    burns part of it at completion. The partition is checked after each of those
    four postings rather than only at the end.

    PRD §2.9: "Three quantities in this system are conserved: they may move between buckets but the total may never change, and any operation that undoes an earlier posting must restore the buckets exactly."
    PRD §2.9: "A wire lot's `received_kg` is fixed at receipt and never changes."
    PRD §2.9: "Every reservation, release and consumption posting moves mass between these three and never creates or destroys any."
    PRD §3.7: "On success the reservation moves mass without creating any: `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its `reserved_kg`, leaving `received_kg` untouched."
    PRD §3.7: "`received_kg` is conserved throughout."
    Design: Difficulty/compensating_invariant/wire_mass_conserved_across_reservation_cancellation_and_completion
    """
    world = _coiler_with_a_large_heat(api)

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["received_kg"] == HEAT_RECEIVED_KG, (
        "a heat's received_kg is fixed at receipt and is the total the three "
        f"buckets must always close on, got {heat['received_kg']}"
    )

    # Hop one: the reservation moves mass out of the rack and into the hold.
    run_a = X.open_run(
        api,
        world.setup_id,
        world.wire_lot_id,
        world.design_id,
        planned_pieces=SHORT_RUN_PIECES,
    )
    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["on_hand_kg"] == ON_HAND_AFTER_RESERVATION_KG, (
        "reserving mass subtracts wire_reserved_kg from on_hand_kg and nothing "
        f"else, expected {ON_HAND_AFTER_RESERVATION_KG}, got {heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == RESERVED_KG, (
        "the same figure lands in reserved_kg, expected "
        f"{RESERVED_KG}, got {heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == 0.000, (
        "a reservation burns nothing, so consumed_kg stays at 0.000, got "
        f"{heat['consumed_kg']}"
    )
    assert heat["received_kg"] == HEAT_RECEIVED_KG, (
        "received_kg is untouched by a reservation, got "
        f"{heat['received_kg']}"
    )

    # Hop two: abandoning the run returns the whole reservation.
    validate_success(api.cancel_run(run_a["id"], PROCESS_TECHNICIAN_HEADERS))
    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["on_hand_kg"] == HEAT_RECEIVED_KG, (
        "abandoning the only run restores the rack to the full receipt weight, "
        f"expected {HEAT_RECEIVED_KG}, got {heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == 0.000, (
        "nothing is left stranded in reserved_kg after the release, got "
        f"{heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == 0.000, (
        "a cancelled run consumes nothing, got " f"{heat['consumed_kg']}"
    )

    # Hop three: an identical reservation is re-derived on a fresh window.
    machine = X.refresh_machine(api, world.machine_id)
    second_setup = X.book_setup(
        api,
        machine,
        world.design_id,
        world.tooling_id,
        window_start=SECOND_WINDOW_START,
        window_end=SECOND_WINDOW_END,
    )
    X.pin_clock(api, SECOND_WINDOW_CLOCK)
    X.activate_setup(api, second_setup["id"])
    run_b = X.open_run(
        api,
        second_setup["id"],
        world.wire_lot_id,
        world.design_id,
        planned_pieces=SHORT_RUN_PIECES,
    )
    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["on_hand_kg"] == ON_HAND_AFTER_RESERVATION_KG, (
        "the second run reserves the same kilograms from the design's stored "
        f"per-piece mass, expected {ON_HAND_AFTER_RESERVATION_KG} on hand, got "
        f"{heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == RESERVED_KG, (
        "the re-derived reservation matches the first one exactly, expected "
        f"{RESERVED_KG}, got {heat['reserved_kg']}"
    )

    # Hop four: completion splits the hold into consumption and a return.
    X.record_fai_subgroup(api, run_b["id"], world.characteristics[0])
    X.accept_first_article(api, run_b["id"])
    X.complete_run(api, run_b["id"], 900, 100)
    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["on_hand_kg"] == ON_HAND_AFTER_COMPLETION_KG, (
        "completion returns the unburned part of the reservation to the rack, "
        f"expected {ON_HAND_AFTER_COMPLETION_KG}, got {heat['on_hand_kg']}"
    )
    assert heat["reserved_kg"] == 0.000, (
        "the hold is cleared by completion, got " f"{heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == CONSUMED_KG, (
        "consumption is the only bucket that grows at completion, expected "
        f"{CONSUMED_KG}, got {heat['consumed_kg']}"
    )
    assert heat["received_kg"] == HEAT_RECEIVED_KG, (
        "received_kg survives the whole round trip unchanged, got "
        f"{heat['received_kg']}"
    )


def test_run_cancellation_hands_back_the_stored_reservation_verbatim(
    api: ApiClient,
) -> None:
    """Abandoning a run returns the run's own stored figure, not a recomputation.

    The reservation figure stays on the cancelled run as history, the rack is
    restored to the full receipt weight, and the abandonment walks the setup and
    the coiler back to rest.

    PRD §2.9: "When a reservation is released, the release uses the `wire_reserved_kg` value stored on the run verbatim; it is never recomputed from the design, because the design may have been revised in the meantime."
    PRD §3.7: "The run moves to `CANCELLED`, the whole reservation comes back using the stored `wire_reserved_kg` verbatim — subtracted from `reserved_kg`, added to `on_hand_kg`, with `consumed_kg` untouched — the setup transitions `ACTIVE → ABORTED`, and the coiler returns to `IDLE` with `active_setup_id` null and `version` increased by 1."
    Design: Difficulty/compensating_invariant/wire_mass_conserved_across_reservation_cancellation_and_completion
    """
    world = _coiler_with_a_large_heat(api)
    run = X.open_run(
        api,
        world.setup_id,
        world.wire_lot_id,
        world.design_id,
        planned_pieces=SHORT_RUN_PIECES,
    )
    stored_reservation = run["wire_reserved_kg"]
    assert stored_reservation == RESERVED_KG, (
        "the run stores the reservation it is about to hand back, expected "
        f"{RESERVED_KG}, got {stored_reservation}"
    )
    machine_before = X.refresh_machine(api, world.machine_id)

    validate_success(api.cancel_run(run["id"], PROCESS_TECHNICIAN_HEADERS))

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["reserved_kg"] == 0.000, (
        "the stored reservation is subtracted from reserved_kg in full, got "
        f"{heat['reserved_kg']}"
    )
    assert heat["on_hand_kg"] == HEAT_RECEIVED_KG, (
        "and added back to on_hand_kg in full, expected "
        f"{HEAT_RECEIVED_KG}, got {heat['on_hand_kg']}"
    )
    assert heat["consumed_kg"] == 0.000, (
        "consumed_kg is untouched by an abandonment, got "
        f"{heat['consumed_kg']}"
    )

    cancelled = X.refresh_run(api, run["id"])
    assert cancelled["process_status"] == C.PROCESS_CANCELLED, (
        "the abandoned run moves to CANCELLED, got "
        f"{cancelled['process_status']}"
    )
    assert cancelled["wire_reserved_kg"] == stored_reservation, (
        "the run keeps its wire_reserved_kg as the historical figure the "
        f"release was posted from, expected {stored_reservation}, got "
        f"{cancelled['wire_reserved_kg']}"
    )
    assert cancelled["wire_consumed_kg"] == 0.000, (
        "a cancelled run never records consumption, got "
        f"{cancelled['wire_consumed_kg']}"
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ABORTED, (
        "the abandonment takes the setup ACTIVE to ABORTED, got "
        f"{setup['setup_status']}"
    )
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "and returns the coiler to IDLE, got " f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        "with active_setup_id null once no setup on it is ACTIVE, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == machine_before["version"] + 1, (
        "the abort of an ACTIVE setup bumps the coiler's version by exactly 1, "
        f"expected {machine_before['version'] + 1}, got {machine['version']}"
    )


def test_run_completion_splits_the_reservation_into_consumption_and_returned_allowance(
    api: ApiClient,
) -> None:
    """Closing a run burns wire for scrap and good pieces alike, and returns the rest.

    A 1 000-piece run reserved a three-percent scrap allowance it did not need;
    completion at 900 good and 100 scrapped burns exactly the 1 000 pieces of
    wire and hands the over-reserved remainder back to the rack.

    PRD §3.7: "Consumption is then computed as the design's stored six-decimal `wire_mass_per_piece_kg` multiplied by the sum of `produced_pieces` and `scrapped_pieces` — scrap burns wire exactly like good product does — rounded half up to three decimal places, and written to `wire_consumed_kg`."
    PRD §3.7: "Three ledger postings follow in this exact order, each rounded half up to three decimal places: the run's stored `wire_reserved_kg` is subtracted from the heat's `reserved_kg`; `wire_consumed_kg` is added to the heat's `consumed_kg`; and the difference between the stored `wire_reserved_kg` and `wire_consumed_kg` is added back to the heat's `on_hand_kg`, returning whatever the scrap allowance over-reserved."
    PRD §3.7: "The run's setup transitions `ACTIVE → RELEASED`, and the coiler returns `PRODUCTION → IDLE` with `active_setup_id` cleared and `version` increased by 1."
    Design: Difficulty/compensating_invariant/wire_mass_conserved_across_reservation_cancellation_and_completion
    """
    world = X.build_world(
        api,
        "running",
        program={
            "program_code": "PGM-IND-11",
            "customer_name": "Bramble Industrial Supply",
            "committed_pieces": 100_000,
        },
        design={"part_number": "D1-MASS"},
        tooling={"tool_code": "TL-D1-M", "original_cost_cents": 1_200_000},
        machine={"machine_code": "COIL-12"},
        wire_lot={"heat_number": "HT-D1-M", "received_kg": HEAT_RECEIVED_KG},
        run={"planned_pieces": SHORT_RUN_PIECES},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )
    stored_reservation = world.run["wire_reserved_kg"]
    assert stored_reservation == RESERVED_KG, (
        "the run holds the inflated reservation before completion, expected "
        f"{RESERVED_KG}, got {stored_reservation}"
    )
    machine_before = X.refresh_machine(api, world.machine_id)

    completed = X.complete_run(api, world.run_id, 900, 100)

    assert completed["process_status"] == C.PROCESS_COMPLETE, (
        "the closed-out run reads COMPLETE, got "
        f"{completed['process_status']}"
    )
    assert completed["wire_consumed_kg"] == CONSUMED_KG, (
        "consumption covers produced plus scrapped pieces at the design's "
        f"stored per-piece mass, expected {CONSUMED_KG}, got "
        f"{completed['wire_consumed_kg']}"
    )
    assert completed["wire_reserved_kg"] == stored_reservation, (
        "the reservation figure the postings were driven from is left on the "
        f"run, expected {stored_reservation}, got "
        f"{completed['wire_reserved_kg']}"
    )

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    A.assert_wire_ledger_conserved(heat)
    assert heat["reserved_kg"] == 0.000, (
        "the first posting clears the whole stored reservation out of "
        f"reserved_kg, got {heat['reserved_kg']}"
    )
    assert heat["consumed_kg"] == CONSUMED_KG, (
        "the second posting adds the consumption to consumed_kg, expected "
        f"{CONSUMED_KG}, got {heat['consumed_kg']}"
    )
    assert heat["on_hand_kg"] == ON_HAND_AFTER_COMPLETION_KG, (
        "the third posting returns the over-reserved allowance to on_hand_kg "
        f"rather than stranding it, expected {ON_HAND_AFTER_COMPLETION_KG}, "
        f"got {heat['on_hand_kg']}"
    )
    assert (
        round(stored_reservation - CONSUMED_KG, 3) == RETURNED_ALLOWANCE_KG
    ), (
        "the returned remainder is the difference between the reservation and "
        f"the consumption, expected {RETURNED_ALLOWANCE_KG}, got "
        f"{round(stored_reservation - CONSUMED_KG, 3)}"
    )
    assert heat["received_kg"] == HEAT_RECEIVED_KG, (
        "received_kg is conserved across the completion, got "
        f"{heat['received_kg']}"
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_RELEASED, (
        "completing a run takes its setup ACTIVE to RELEASED, got "
        f"{setup['setup_status']}"
    )
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "and returns the coiler PRODUCTION to IDLE, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        "clearing active_setup_id, got " f"{machine['active_setup_id']}"
    )
    assert machine["version"] == machine_before["version"] + 1, (
        "completing a run bumps the coiler's version by exactly 1, expected "
        f"{machine_before['version'] + 1}, got {machine['version']}"
    )


# A deliberately cheap re-cut tool, so one 1 000-piece lot recovers the whole
# capitalised cost and the reversal has to walk a FULLY_AMORTIZED tool back.
RECUT_TOOL_COST_CENTS = 1_000
RECUT_AMORT_PER_PIECE_CENTS = 1
AMORTIZATION_BASIS_PIECES = 500_000
LOT_PIECES = 1_000
RECUT_QUOTED_UNIT_PRICE_CENTS = 21
RECUT_EXTENDED_PRICE_CENTS = 21_000


def _safety_program_with_a_cheap_tool(api: ApiClient) -> X.World:
    """A fully approved AUTOMOTIVE_SAFETY program with one PACKED lot on the dock."""
    return X.build_world(
        api,
        "packed",
        program={
            "program_code": "PGM-AUTO-7",
            "customer_name": "Northwind Drivetrain",
            "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
            "ppap_level": 3,
            "required_ppk": 1.33,
        },
        design={"part_number": "D1-CENTS"},
        tooling={
            "tool_code": "TL-RECUT",
            "original_cost_cents": RECUT_TOOL_COST_CENTS,
        },
        machine={"machine_code": "COIL-13"},
        submission={"ppap_level": 3},
        lot={"piece_count": LOT_PIECES},
        packaging_method=C.PACK_INTERLEAVED_TUBE,
    )


def test_tooling_cents_close_on_the_capitalised_cost_across_ship_and_return(
    api: ApiClient,
) -> None:
    """Recovered plus unamortized cents equal the capitalised cost at every hop.

    The tool is armed by the customer's full approval, driven to zero
    outstanding by a single shipment, and then walked back by taking that
    shipment's lot in again. The ledger identity is checked at all three points.

    PRD §2.9: "A tooling asset's `original_cost_cents` is fixed at capitalisation."
    PRD §2.9: "`recovered_cents` and `unamortized_cents` always sum to it."
    PRD §2.9: "Shipping a lot posts a recovery into the first and out of the second; taking that lot back reverses the posting using the `tooling_recovery_cents` stored on the lot verbatim."
    PRD §3.4: "The `PENDING → AMORTIZING` promotion fires as a system event when the tool's design reaches `PRODUCTION_RELEASED`, and it is the moment the amortization basis is frozen: `amortization_basis_pieces` takes the owning program's `committed_pieces`, and `amort_per_piece_cents` becomes `original_cost_cents` divided by that basis, rounded **up** to the next whole cent."
    PRD §3.4: "Once armed, each shipment posts a recovery into `recovered_cents` and out of `unamortized_cents`; when a posting drives `unamortized_cents` to exactly 0, the tool transitions `AMORTIZING → FULLY_AMORTIZED`."
    Design: Difficulty/compensating_invariant/tooling_cents_conserved_and_status_reverted_across_ship_then_return
    """
    world = _safety_program_with_a_cheap_tool(api)

    # Hop one: the approval arms the ledger without moving a cent.
    tool = X.refresh_tooling(api, world.tooling_id)
    A.assert_tooling_ledger_conserved(tool)
    assert tool["original_cost_cents"] == RECUT_TOOL_COST_CENTS, (
        "the capitalised cost is the total the two cent buckets must close on, "
        f"expected {RECUT_TOOL_COST_CENTS}, got {tool['original_cost_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the design reaching PRODUCTION_RELEASED arms the tool, got "
        f"{tool['amortization_status']}"
    )
    assert tool["amortization_basis_pieces"] == AMORTIZATION_BASIS_PIECES, (
        "the basis freezes at the program's committed_pieces, expected "
        f"{AMORTIZATION_BASIS_PIECES}, got {tool['amortization_basis_pieces']}"
    )
    assert tool["amort_per_piece_cents"] == RECUT_AMORT_PER_PIECE_CENTS, (
        "the per-piece figure is the cost over the basis rounded up to the next "
        f"whole cent, expected {RECUT_AMORT_PER_PIECE_CENTS}, got "
        f"{tool['amort_per_piece_cents']}"
    )
    assert tool["recovered_cents"] == 0, (
        "arming recovers nothing on its own, got " f"{tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == RECUT_TOOL_COST_CENTS, (
        "the whole cost is still outstanding before the first shipment, "
        f"expected {RECUT_TOOL_COST_CENTS}, got {tool['unamortized_cents']}"
    )

    # Hop two: the shipment posts a recovery that clears the balance exactly.
    shipped = X.ship_lot(api, world.lot_id)
    assert shipped["tooling_recovery_cents"] == RECUT_TOOL_COST_CENTS, (
        "the forecast recovery is the lot's pieces at the frozen per-piece rate, "
        f"capped at the outstanding balance, expected {RECUT_TOOL_COST_CENTS}, "
        f"got {shipped['tooling_recovery_cents']}"
    )
    tool = X.refresh_tooling(api, world.tooling_id)
    A.assert_tooling_ledger_conserved(tool)
    assert tool["recovered_cents"] == RECUT_TOOL_COST_CENTS, (
        "the recovery is posted into recovered_cents, expected "
        f"{RECUT_TOOL_COST_CENTS}, got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == 0, (
        "and out of unamortized_cents, which lands on exactly 0, got "
        f"{tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_FULLY_AMORTIZED, (
        "a posting that drives the outstanding balance to exactly 0 takes the "
        f"tool AMORTIZING to FULLY_AMORTIZED, got {tool['amortization_status']}"
    )
    assert tool["original_cost_cents"] == RECUT_TOOL_COST_CENTS, (
        "the capitalised cost is untouched by a recovery posting, got "
        f"{tool['original_cost_cents']}"
    )

    # Hop three: taking the lot back reverses the posting.
    validate_success(api.return_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))
    tool = X.refresh_tooling(api, world.tooling_id)
    A.assert_tooling_ledger_conserved(tool)
    assert tool["recovered_cents"] == 0, (
        "the reversal takes the historical posting back out of recovered_cents, "
        f"got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == RECUT_TOOL_COST_CENTS, (
        "and puts it back on the outstanding balance, expected "
        f"{RECUT_TOOL_COST_CENTS}, got {tool['unamortized_cents']}"
    )
    assert tool["original_cost_cents"] == RECUT_TOOL_COST_CENTS, (
        "the capitalised cost is conserved across the whole round trip, got "
        f"{tool['original_cost_cents']}"
    )


def test_lot_return_reverses_the_recovery_verbatim_and_rearms_the_tool(
    api: ApiClient,
) -> None:
    """The reversal posts the lot's historical figure and reverts the tool's status.

    The return pins each bucket movement individually: the cents come out of
    recovered and back onto the outstanding balance, the terminal
    FULLY_AMORTIZED status reverts to AMORTIZING, the lot keeps the historical
    posting amount while losing its shipment stamp, and the pieces go back on
    the commitment rather than back into allocation.

    PRD §3.11: "The stored `tooling_recovery_cents` is subtracted from the tool's `recovered_cents` and added back to `unamortized_cents` **verbatim**, using the historical posting amount rather than a recomputation, which is what keeps `original_cost_cents` conserved even when the tool's balance has moved since."
    PRD §3.11: "If the tool had reached `FULLY_AMORTIZED` and the reversal leaves `unamortized_cents` positive, its `amortization_status` returns to `AMORTIZING`."
    PRD §3.11: "The lot becomes `RETURNED`, which is terminal, `shipped_at` is cleared to null, `tooling_recovery_cents` is left as the historical posting amount, and `delivery_posture` is re-derived."
    PRD §3.11: "On the program, `shipped_pieces` decreases by `piece_count` and `open_commitment_pieces` increases by it, so returned pieces go back on the commitment rather than back into allocation."
    Design: Difficulty/compensating_invariant/tooling_cents_conserved_and_status_reverted_across_ship_then_return
    """
    world = _safety_program_with_a_cheap_tool(api)
    shipped = X.ship_lot(api, world.lot_id)
    posted_recovery = shipped["tooling_recovery_cents"]
    assert posted_recovery == RECUT_TOOL_COST_CENTS, (
        "the shipment records the historical posting on the lot, expected "
        f"{RECUT_TOOL_COST_CENTS}, got {posted_recovery}"
    )
    assert shipped["shipped_at"] is not None, (
        "a shipped lot carries a shipped_at stamp before the return, got "
        f"{shipped['shipped_at']}"
    )
    tool_after_ship = X.refresh_tooling(api, world.tooling_id)
    assert tool_after_ship["amortization_status"] == C.AMORT_FULLY_AMORTIZED, (
        "the tool is FULLY_AMORTIZED before the reversal, so the reversal has "
        f"to walk a terminal status back, got {tool_after_ship['amortization_status']}"
    )

    validate_success(api.return_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["recovered_cents"] == tool_after_ship["recovered_cents"] - posted_recovery, (
        "the lot's stored recovery is subtracted from recovered_cents exactly, "
        f"expected {tool_after_ship['recovered_cents'] - posted_recovery}, got "
        f"{tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == (
        tool_after_ship["unamortized_cents"] + posted_recovery
    ), (
        "and added back to unamortized_cents exactly, expected "
        f"{tool_after_ship['unamortized_cents'] + posted_recovery}, got "
        f"{tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "a reversal that leaves an outstanding balance takes FULLY_AMORTIZED "
        f"back to AMORTIZING, got {tool['amortization_status']}"
    )
    assert tool["amort_per_piece_cents"] == RECUT_AMORT_PER_PIECE_CENTS, (
        "the frozen per-piece rate is not disturbed by a reversal, expected "
        f"{RECUT_AMORT_PER_PIECE_CENTS}, got {tool['amort_per_piece_cents']}"
    )
    assert tool["amortization_basis_pieces"] == AMORTIZATION_BASIS_PIECES, (
        "nor is the frozen basis, expected "
        f"{AMORTIZATION_BASIS_PIECES}, got {tool['amortization_basis_pieces']}"
    )

    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_RETURNED, (
        "the taken-back lot lands on the terminal RETURNED status, got "
        f"{lot['lot_status']}"
    )
    assert lot["shipped_at"] is None, (
        "the shipment stamp is cleared to null by the return, got "
        f"{lot['shipped_at']}"
    )
    assert lot["tooling_recovery_cents"] == posted_recovery, (
        "the historical posting amount is left on the lot rather than zeroed, "
        f"expected {posted_recovery}, got {lot['tooling_recovery_cents']}"
    )
    assert lot["unit_price_cents"] == RECUT_QUOTED_UNIT_PRICE_CENTS, (
        "the commercial terms snapshotted at allocation are untouched by the "
        f"return, expected unit_price_cents {RECUT_QUOTED_UNIT_PRICE_CENTS}, got "
        f"{lot['unit_price_cents']}"
    )
    assert lot["extended_price_cents"] == RECUT_EXTENDED_PRICE_CENTS, (
        "and so is the extended price, expected "
        f"{RECUT_EXTENDED_PRICE_CENTS}, got {lot['extended_price_cents']}"
    )
    assert lot["tooling_amort_per_piece_cents"] == RECUT_AMORT_PER_PIECE_CENTS, (
        "and so is the snapshotted per-piece amortization, expected "
        f"{RECUT_AMORT_PER_PIECE_CENTS}, got "
        f"{lot['tooling_amort_per_piece_cents']}"
    )

    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["shipped_pieces"] == 0, (
        "the returned pieces leave shipped_pieces, got "
        f"{program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == AMORTIZATION_BASIS_PIECES, (
        "and go back on the commitment in full, expected "
        f"{AMORTIZATION_BASIS_PIECES}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        "a return never puts pieces back into allocation, got "
        f"{program['allocated_pieces']}"
    )


# Two 1 000-piece lots cut from one 25 500-piece run against a 4 800 000-cent
# tool, which the frozen 500 000-piece basis recovers at 10 cents per piece.
COMMITTED_PIECES = 500_000
PIECE_TOOL_COST_CENTS = 4_800_000
PIECE_AMORT_PER_PIECE_CENTS = 10
SHIPMENT_RECOVERY_CENTS = 10_000
OPEN_AFTER_TWO_LOTS = 498_000
OPEN_AFTER_QUARANTINE = 499_000


def _safety_program_with_two_allocated_lots(api: ApiClient) -> X.World:
    """A fully approved program carrying two ALLOCATED 1 000-piece lots."""
    world = X.build_world(
        api,
        "approved",
        program={
            "program_code": "PGM-AUTO-8",
            "customer_name": "Northwind Drivetrain",
            "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
            "ppap_level": 3,
            "committed_pieces": COMMITTED_PIECES,
            "required_ppk": 1.33,
        },
        design={"part_number": "D1-PIECES"},
        tooling={
            "tool_code": "TL-PIECES",
            "original_cost_cents": PIECE_TOOL_COST_CENTS,
        },
        machine={"machine_code": "COIL-14"},
        submission={"ppap_level": 3},
    )
    world.lot = X.allocate_lot(api, world.run_id, world.program_id, LOT_PIECES)
    return world


def test_piece_commitment_closes_on_the_commitment_at_every_lot_transition(
    api: ApiClient,
) -> None:
    """A program's three piece buckets sum to its commitment after every move.

    Two lots are cut from one run, one of them packed and shipped, the other
    quarantined and released, and the shipped one finally taken back. Six lot
    transitions, each of them a transfer, and the identity is checked after each.

    PRD §2.9: "Three quantities in this system are conserved: they may move between buckets but the total may never change, and any operation that undoes an earlier posting must restore the buckets exactly."
    PRD §2.9: "A program's `committed_pieces` is fixed when the program is opened."
    PRD §2.9: "`open_commitment_pieces`, `allocated_pieces` and `shipped_pieces` move as lots are allocated, shipped, quarantined, released and returned, and every one of those moves is a transfer, never a mint."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and `shipped_pieces` increases by it — `open_commitment_pieces` is untouched, because the commitment was consumed at allocation."
    Design: Difficulty/compensating_invariant/program_piece_counters_conserved_across_allocate_ship_quarantine_release_return
    """
    world = _safety_program_with_two_allocated_lots(api)
    lot_a = world.lot
    lot_b = X.allocate_lot(api, world.run_id, world.program_id, LOT_PIECES)

    # Checkpoint one: both lots allocated.
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["committed_pieces"] == COMMITTED_PIECES, (
        "the commitment is fixed when the program is opened and is the total "
        f"the buckets close on, expected {COMMITTED_PIECES}, got "
        f"{program['committed_pieces']}"
    )
    assert program["open_commitment_pieces"] == OPEN_AFTER_TWO_LOTS, (
        "each allocation takes its pieces off the open commitment, expected "
        f"{OPEN_AFTER_TWO_LOTS}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 2 * LOT_PIECES, (
        "and puts them into allocation, expected "
        f"{2 * LOT_PIECES}, got {program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == 0, (
        "nothing has shipped yet, got " f"{program['shipped_pieces']}"
    )

    # Checkpoint two: packing moves no pieces at all.
    X.pack_lot(api, lot_a["id"], C.PACK_TANGLE_FREE_TRAY)
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["open_commitment_pieces"] == OPEN_AFTER_TWO_LOTS, (
        "packing records a method and nothing else, so the open commitment is "
        f"unmoved, expected {OPEN_AFTER_TWO_LOTS}, got "
        f"{program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 2 * LOT_PIECES, (
        "and allocation is unmoved too, expected "
        f"{2 * LOT_PIECES}, got {program['allocated_pieces']}"
    )

    # Checkpoint three: the shipment moves allocated pieces to shipped only.
    X.ship_lot(api, lot_a["id"])
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["open_commitment_pieces"] == OPEN_AFTER_TWO_LOTS, (
        "the open commitment was consumed at allocation, so shipping leaves it "
        f"alone, expected {OPEN_AFTER_TWO_LOTS}, got "
        f"{program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == LOT_PIECES, (
        "the shipped lot's pieces leave allocation, expected "
        f"{LOT_PIECES}, got {program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == LOT_PIECES, (
        "and arrive in shipped_pieces, expected "
        f"{LOT_PIECES}, got {program['shipped_pieces']}"
    )

    # Checkpoint four: the quarantine puts pieces back on the commitment.
    validate_success(
        api.quarantine_lot(
            lot_b["id"],
            {"quarantine_reason": C.QUARANTINE_INSPECTOR_ACTION},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["open_commitment_pieces"] == OPEN_AFTER_QUARANTINE, (
        "quarantining a lot returns its pieces to the open commitment, expected "
        f"{OPEN_AFTER_QUARANTINE}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        "leaving nothing in allocation, got " f"{program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == LOT_PIECES, (
        "and never touching the shipped bucket, expected "
        f"{LOT_PIECES}, got {program['shipped_pieces']}"
    )

    # Checkpoint five: the release is the exact mirror of the quarantine.
    validate_success(
        api.release_lot_from_quarantine(lot_b["id"], QUALITY_INSPECTOR_HEADERS)
    )
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["open_commitment_pieces"] == OPEN_AFTER_TWO_LOTS, (
        "the release takes the pieces back off the open commitment, expected "
        f"{OPEN_AFTER_TWO_LOTS}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == LOT_PIECES, (
        "and returns them to allocation, expected "
        f"{LOT_PIECES}, got {program['allocated_pieces']}"
    )

    # Checkpoint six: the return crosses a different axis than the release did.
    validate_success(api.return_lot(lot_a["id"], PROGRAM_MANAGER_HEADERS))
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["shipped_pieces"] == 0, (
        "the returned pieces leave shipped_pieces, got "
        f"{program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == OPEN_AFTER_QUARANTINE, (
        "and land on the open commitment, expected "
        f"{OPEN_AFTER_QUARANTINE}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == LOT_PIECES, (
        "not back in allocation, which still holds only the released lot, "
        f"expected {LOT_PIECES}, got {program['allocated_pieces']}"
    )
    assert program["committed_pieces"] == COMMITTED_PIECES, (
        "the commitment is conserved across all six transitions, got "
        f"{program['committed_pieces']}"
    )


def test_quarantine_and_release_pin_the_lot_counter_the_posture_and_the_cent_ledger(
    api: ApiClient,
) -> None:
    """The compensating pair moves the quarantine counter and the posture too.

    Beyond the piece buckets, a quarantine raises the program's quarantined lot
    count and drops a healthy program to AT_RISK, the release lowers the count
    and restores ON_TRACK while forcing the lot to be packed again, the return
    unwinds the tooling cent ledger alongside the piece ledger, and none of the
    five transitions is allowed to touch the program's revision counter.

    PRD §3.11: "The lot becomes `QUARANTINED` and retains its `packaging_method`."
    PRD §3.11: "The program's `quarantined_lot_count` increases by 1, `allocated_pieces` decreases by `piece_count` and `open_commitment_pieces` increases by the same amount — the pieces go back on the commitment — and `delivery_posture` is re-derived, which is what drops a healthy program to `AT_RISK`."
    PRD §3.11: "Success returns the lot to `ALLOCATED`, clears `quarantine_reason` back to null and clears `packaging_method` to null — **the lot must be packed again**, and the packaging rules are re-applied from scratch."
    PRD §3.11: "The program's `quarantined_lot_count` decreases by 1, `allocated_pieces` increases by `piece_count`, `open_commitment_pieces` decreases by it, and `delivery_posture` is re-derived, returning to `ON_TRACK` only when the last quarantined lot has been released and no run of the program is on hold."
    PRD §3.11: "The stored `tooling_recovery_cents` is subtracted from the tool's `recovered_cents` and added back to `unamortized_cents` **verbatim**, using the historical posting amount rather than a recomputation, which is what keeps `original_cost_cents` conserved even when the tool's balance has moved since."
    PRD §2.4: "`CustomerProgram.version` is incremented **only** by the program quoting operation, `POST /customer-programs/{id}/quote`, and by nothing else."
    Design: Difficulty/compensating_invariant/program_piece_counters_conserved_across_allocate_ship_quarantine_release_return
    """
    world = _safety_program_with_two_allocated_lots(api)
    lot_a = world.lot
    lot_b = X.allocate_lot(api, world.run_id, world.program_id, LOT_PIECES)

    baseline = X.refresh_program(api, world.program_id)
    version_before = baseline["version"]
    assert baseline["quarantined_lot_count"] == 0, (
        "a program with no quarantined lots starts the scenario at 0, got "
        f"{baseline['quarantined_lot_count']}"
    )

    X.pack_lot(api, lot_a["id"], C.PACK_TANGLE_FREE_TRAY)
    shipped = X.ship_lot(api, lot_a["id"])
    expected_recovery = A.expected_forecast_recovery_cents(
        LOT_PIECES, PIECE_AMORT_PER_PIECE_CENTS, PIECE_TOOL_COST_CENTS
    )
    assert expected_recovery == SHIPMENT_RECOVERY_CENTS, (
        "the forecast recovery for a 1 000-piece lot at 10 cents a piece is "
        f"{SHIPMENT_RECOVERY_CENTS}, got {expected_recovery}"
    )
    assert shipped["tooling_recovery_cents"] == SHIPMENT_RECOVERY_CENTS, (
        "the shipment posts that recovery onto the lot, expected "
        f"{SHIPMENT_RECOVERY_CENTS}, got {shipped['tooling_recovery_cents']}"
    )
    tool = X.refresh_tooling(api, world.tooling_id)
    A.assert_tooling_ledger_conserved(tool)
    assert tool["recovered_cents"] == SHIPMENT_RECOVERY_CENTS, (
        "and into the tool's recovered_cents, expected "
        f"{SHIPMENT_RECOVERY_CENTS}, got {tool['recovered_cents']}"
    )

    # The lot to be quarantined is packed first, so the release has a method to
    # clear rather than a null to leave alone.
    X.pack_lot(api, lot_b["id"], C.PACK_TANGLE_FREE_TRAY)

    validate_success(
        api.quarantine_lot(
            lot_b["id"],
            {"quarantine_reason": C.QUARANTINE_INSPECTOR_ACTION},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    held = X.refresh_lot(api, lot_b["id"])
    assert held["lot_status"] == C.LOT_QUARANTINED, (
        "the manually held lot reads QUARANTINED, got " f"{held['lot_status']}"
    )
    assert held["quarantine_reason"] == C.QUARANTINE_INSPECTOR_ACTION, (
        "with the inspector's own reason recorded rather than a cascade reason, "
        f"got {held['quarantine_reason']}"
    )
    assert held["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        "and the packaging method retained while the lot sits in quarantine, "
        f"expected {C.PACK_TANGLE_FREE_TRAY}, got {held['packaging_method']}"
    )
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["quarantined_lot_count"] == 1, (
        "the quarantine raises the program's quarantined lot count by 1, got "
        f"{program['quarantined_lot_count']}"
    )
    assert program["delivery_posture"] == C.POSTURE_AT_RISK, (
        "which is what drops an otherwise healthy program to AT_RISK, got "
        f"{program['delivery_posture']}"
    )
    assert program["open_commitment_pieces"] == OPEN_AFTER_QUARANTINE, (
        "the held pieces go back on the commitment, expected "
        f"{OPEN_AFTER_QUARANTINE}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        "and out of allocation, got " f"{program['allocated_pieces']}"
    )
    assert program["version"] == version_before, (
        "a quarantine is a cascaded write and never bumps the program's "
        f"version, expected {version_before}, got {program['version']}"
    )

    validate_success(
        api.release_lot_from_quarantine(lot_b["id"], QUALITY_INSPECTOR_HEADERS)
    )
    released = X.refresh_lot(api, lot_b["id"])
    assert released["lot_status"] == C.LOT_ALLOCATED, (
        "the release returns the lot to ALLOCATED rather than to PACKED, got "
        f"{released['lot_status']}"
    )
    assert released["quarantine_reason"] is None, (
        "clearing the quarantine reason back to null, got "
        f"{released['quarantine_reason']}"
    )
    assert released["packaging_method"] is None, (
        "and clearing the packaging method to null so the lot must be packed "
        f"again from scratch, got {released['packaging_method']}"
    )
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["quarantined_lot_count"] == 0, (
        "the release lowers the quarantined lot count back to 0, got "
        f"{program['quarantined_lot_count']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "and with the last held lot released and no run on hold the posture "
        f"returns to ON_TRACK, got {program['delivery_posture']}"
    )
    assert program["open_commitment_pieces"] == OPEN_AFTER_TWO_LOTS, (
        "the released pieces come back off the commitment, expected "
        f"{OPEN_AFTER_TWO_LOTS}, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == LOT_PIECES, (
        "and back into allocation, expected "
        f"{LOT_PIECES}, got {program['allocated_pieces']}"
    )
    assert program["version"] == version_before, (
        "nor does a release bump the program's version, expected "
        f"{version_before}, got {program['version']}"
    )

    validate_success(api.return_lot(lot_a["id"], PROGRAM_MANAGER_HEADERS))
    tool = X.refresh_tooling(api, world.tooling_id)
    A.assert_tooling_ledger_conserved(tool)
    assert tool["recovered_cents"] == 0, (
        "the return unwinds the cent ledger alongside the piece ledger, taking "
        f"recovered_cents back to 0, got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == PIECE_TOOL_COST_CENTS, (
        "with the whole capitalised cost outstanding again, expected "
        f"{PIECE_TOOL_COST_CENTS}, got {tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "and the tool still AMORTIZING, since it never reached the terminal "
        f"status, got {tool['amortization_status']}"
    )
    program = X.refresh_program(api, world.program_id)
    A.assert_commitment_conserved(program)
    assert program["shipped_pieces"] == 0, (
        "the returned pieces leave shipped_pieces, got "
        f"{program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == OPEN_AFTER_QUARANTINE, (
        "and go back on the commitment, expected "
        f"{OPEN_AFTER_QUARANTINE}, got {program['open_commitment_pieces']}"
    )
    assert program["quarantined_lot_count"] == 0, (
        "a return is not a quarantine and leaves the held-lot count at 0, got "
        f"{program['quarantined_lot_count']}"
    )
    assert program["version"] == version_before, (
        "and after all five lot transitions the program's version is still the "
        f"one the quote left behind, expected {version_before}, got "
        f"{program['version']}"
    )
