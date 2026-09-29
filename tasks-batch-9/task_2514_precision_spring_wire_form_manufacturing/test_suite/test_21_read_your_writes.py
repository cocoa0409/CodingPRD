"""Every write is visible to the very next read, through both the resource and the list.

Nothing in this API propagates: a cascade applies all of its hops inside the
request that triggered it, so the read a client issues immediately afterwards is
already the post-write truth. These two scenarios pin that down from both ends of
the read surface. The first packs a lot and then demands that the single-resource
read, the filtered listing that should now contain it, and the filtered listing it
should have left all agree with the pack call's own response body. The second
ships a lot and then demands that the computed amortization read has been derived
from the reduced balance and the reduced commitment rather than served from a
snapshot taken before the shipment.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import PROCESS_TECHNICIAN_HEADERS, PROGRAM_MANAGER_HEADERS

# The canonical program and tool the two scenarios are built on.
COMMITTED_PIECES = 500_000
TOOLING_COST_CENTS = 4_800_000
AMORT_PER_PIECE_CENTS = 10

# One 1 000-piece lot, allocated and then shipped: the recovery it posts and what
# it leaves behind.
LOT_PIECES = 1_000
RECOVERED_CENTS = 10_000
UNAMORTIZED_CENTS = 4_790_000
OPEN_COMMITMENT_PIECES = 499_000

# Both hypothetical recoveries for the *next* 1 000 pieces, computed against the
# balance and commitment the shipment has already reduced.
FORECAST_RECOVERY_CENTS = 10_000
ACTUAL_RECOVERY_CENTS = 14_399


def test_packing_is_visible_to_the_very_next_read_and_listing(api: ApiClient) -> None:
    """The pack call's own body, the resource read and both listings tell one story.

    An `INDUSTRIAL` program permits every packaging method, so a tangle-free tray
    is accepted and the lot leaves `ALLOCATED` for `PACKED` inside that one
    request. The read issued immediately afterwards already shows the new status
    and the recorded method, the `PACKED` listing already contains the row, and
    the `ALLOCATED` listing it came from is already empty.

    PRD §2.10: "When they do, all effects are applied within the same request —
    consistency is immediate, never eventual — and each mutated row has its own
    `updated_at` refreshed and its own `version` advanced under the rules of
    section 2.4."
    PRD §3.11: "Success records the method and moves the lot `ALLOCATED →
    PACKED`."
    PRD §3.11: "A lot that survives all of that opens in `lot_status`
    `ALLOCATED` with `packaging_method` null, and it snapshots the commercial
    terms at creation: `unit_price_cents` from the program's
    `quoted_unit_price_cents`, `tooling_amort_per_piece_cents` from the program's
    `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as
    `piece_count` multiplied by `unit_price_cents`."
    PRD §3.11: "First, the method must be in the permitted set for the program's
    `application_class`: `MEDICAL_IMPLANT` and `MEDICAL_DEVICE` permit only
    `CLEANROOM_DOUBLE_BAG` and `INTERLEAVED_TUBE`; `AUTOMOTIVE_SAFETY` permits
    only `TANGLE_FREE_TRAY` and `INTERLEAVED_TUBE`; `AUTOMOTIVE_NON_SAFETY`
    permits those two plus `BAG_AND_TAG`; `INDUSTRIAL` permits all five."
    PRD §3.11: "Lots may be listed filtered by `run_id`, `program_id` and
    `lot_status`."

    Design: Corner/consistency_model/packing_is_visible_to_the_very_next_read_and_listing
    """
    world = X.build_world(api, "allocated", lot={"piece_count": LOT_PIECES})
    assert world.lot["lot_status"] == C.LOT_ALLOCATED, (
        f"the lot starts ALLOCATED, got {world.lot['lot_status']}"
    )
    assert world.lot["packaging_method"] is None, (
        f"an allocated lot has no packaging method yet, got {world.lot['packaging_method']}"
    )

    packed = validate_success(
        api.pack_lot(
            world.lot_id,
            {"packaging_method": C.PACK_TANGLE_FREE_TRAY},
            PROCESS_TECHNICIAN_HEADERS,
        )
    )
    assert packed["lot_status"] == C.LOT_PACKED, (
        f"packing moves the lot to PACKED, got {packed['lot_status']}"
    )
    assert packed["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        f"the method the technician supplied is recorded, got {packed['packaging_method']}"
    )

    # The very next read of the resource itself.
    read_back = validate_success(api.get_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))
    assert read_back["lot_status"] == packed["lot_status"], (
        "the read issued immediately after the pack agrees with the pack's own body, "
        f"expected {packed['lot_status']} got {read_back['lot_status']}"
    )
    assert read_back["packaging_method"] == packed["packaging_method"], (
        "the read carries the same recorded method as the pack response, expected "
        f"{packed['packaging_method']} got {read_back['packaging_method']}"
    )
    assert read_back["piece_count"] == packed["piece_count"], (
        f"the piece count is unchanged by packing, got {read_back['piece_count']}"
    )
    assert read_back["unit_price_cents"] == packed["unit_price_cents"], (
        "the snapshotted unit price is unchanged by packing, expected "
        f"{packed['unit_price_cents']} got {read_back['unit_price_cents']}"
    )

    # The very next listing filtered on the status the write produced.
    now_packed, packed_meta = validate_paginated(
        api.list_lots(
            PROGRAM_MANAGER_HEADERS,
            {"program_id": world.program_id, "lot_status": C.LOT_PACKED},
        )
    )
    assert packed_meta["total_count"] == 1, (
        "the PACKED bucket already contains the row the pack call produced, got "
        f"{packed_meta['total_count']}"
    )
    assert now_packed[0]["id"] == packed["id"], (
        f"the listed row is the lot that was just packed, got {now_packed[0]['id']}"
    )
    assert now_packed[0]["lot_status"] == packed["lot_status"], (
        "the listing agrees with the write's own body on the status, expected "
        f"{packed['lot_status']} got {now_packed[0]['lot_status']}"
    )
    assert now_packed[0]["packaging_method"] == packed["packaging_method"], (
        "the listing agrees with the write's own body on the method, expected "
        f"{packed['packaging_method']} got {now_packed[0]['packaging_method']}"
    )
    for field in (
        "id",
        "lot_status",
        "packaging_method",
        "piece_count",
        "unit_price_cents",
        "extended_price_cents",
        "tooling_amort_per_piece_cents",
        "tooling_recovery_cents",
        "version",
    ):
        assert now_packed[0][field] == read_back[field], (
            f"the listing row and the single-resource read agree on {field}, got "
            f"{now_packed[0][field]} and {read_back[field]}"
        )

    # And the bucket the row left is already empty.
    still_allocated, allocated_meta = validate_paginated(
        api.list_lots(
            PROGRAM_MANAGER_HEADERS,
            {"program_id": world.program_id, "lot_status": C.LOT_ALLOCATED},
        )
    )
    assert allocated_meta["total_count"] == 0, (
        "the ALLOCATED bucket has already lost the row, with no propagation window, "
        f"got {allocated_meta['total_count']}"
    )
    assert still_allocated == [], (
        f"no lot is still allocated on this program, got {still_allocated}"
    )


def test_the_amortization_read_recomputes_from_committed_state_after_a_ship(
    api: ApiClient,
) -> None:
    """The computed read is derived on demand, not served from a pre-shipment snapshot.

    Shipping 1 000 pieces posts 10 000 cents against the tool and takes 1 000
    pieces off the open commitment. The read issued immediately afterwards has to
    show both movements, and — the sharper half — has to recompute *both*
    projections for a further 1 000 pieces against the reduced figures. The
    accelerated projection is the tell: it can only come out at 14 399 cents if
    the 4 790 000-cent balance and the 499 000-piece commitment were the inputs.

    PRD §2.10: "When they do, all effects are applied within the same request —
    consistency is immediate, never eventual — and each mutated row has its own
    `updated_at` refreshed and its own `version` advanced under the rules of
    section 2.4."
    PRD §3.4: "Both variants are integral cents; there is no half-up rounding
    anywhere in this rule."
    PRD §3.4: "A computed read on the program exposes them side by side for a
    hypothetical lot of a stated `piece_count`, returning the program's own
    `amortization_method`, the `tooling_asset_id` of the newest tooling asset by
    `created_at` for the program's most recently quoted design, that tool's
    `original_cost_cents`, `recovered_cents` and `unamortized_cents`, the
    program's live `open_commitment_pieces`, and then both hypothetical figures:
    `forecast_basis_recovery_cents` and `actual_basis_recovery_cents`."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the
    amount is the lot's `piece_count` multiplied by the tool's frozen
    `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`;
    whichever of the two is smaller is posted."
    PRD §3.4: "Under `ACTUAL_BASIS` — an accelerated declining recovery — the
    amount starts from the tool's live `unamortized_cents` multiplied by an
    acceleration factor of 1.5, multiplied by the lot's `piece_count`, divided by
    the program's `open_commitment_pieces` (or by 1 if that figure is zero or
    lower, so the division is always defined), rounded **up** toward positive
    infinity to a whole cent, and then capped at the tool's live
    `unamortized_cents`; again the smaller of the two is posted."
    PRD §2.9: "`recovered_cents` and `unamortized_cents` always sum to it."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and
    `shipped_pieces` increases by it — `open_commitment_pieces` is untouched,
    because the commitment was consumed at allocation."

    Design: Corner/consistency_model/the_amortization_read_recomputes_from_committed_state_after_a_ship
    """
    world = X.build_world(api, "shipped", lot={"piece_count": LOT_PIECES})

    # The very next read after the shipment.
    computed = validate_success(
        api.get_tooling_amortization(
            world.program_id,
            PROGRAM_MANAGER_HEADERS,
            {"piece_count": LOT_PIECES},
        )
    )

    assert computed["amortization_method"] == C.FORECAST_BASIS, (
        "the read reports the program's own method, got "
        f"{computed['amortization_method']}"
    )
    assert computed["tooling_asset_id"] == world.tooling_id, (
        "the read resolves the newest tool of the most recently quoted design, got "
        f"{computed['tooling_asset_id']}"
    )
    assert computed["original_cost_cents"] == TOOLING_COST_CENTS, (
        f"the capitalised cost is fixed at 4 800 000 cents, got {computed['original_cost_cents']}"
    )
    assert computed["recovered_cents"] == RECOVERED_CENTS, (
        "the 1 000-piece shipment posted 1 000 times the frozen 10 cents, so 10 000 "
        f"cents are recovered, got {computed['recovered_cents']}"
    )
    assert computed["unamortized_cents"] == UNAMORTIZED_CENTS, (
        "the same 10 000 cents left the outstanding balance, leaving 4 790 000, got "
        f"{computed['unamortized_cents']}"
    )
    assert computed["open_commitment_pieces"] == OPEN_COMMITMENT_PIECES, (
        "allocation consumed 1 000 pieces of the 500 000-piece commitment and the "
        f"shipment left that figure alone, so 499 000 remain, got "
        f"{computed['open_commitment_pieces']}"
    )
    A.assert_tooling_ledger_conserved(computed)

    expected_forecast = A.expected_forecast_recovery_cents(
        LOT_PIECES, AMORT_PER_PIECE_CENTS, UNAMORTIZED_CENTS
    )
    assert expected_forecast == FORECAST_RECOVERY_CENTS, (
        "the straight-line projection is linear in piece count and independent of "
        f"the balance, so it is still 10 000 cents, got {expected_forecast}"
    )
    assert computed["forecast_basis_recovery_cents"] == FORECAST_RECOVERY_CENTS, (
        "the forecast projection for a further 1 000 pieces is 10 000 cents, got "
        f"{computed['forecast_basis_recovery_cents']}"
    )

    expected_actual = A.expected_actual_recovery_cents(
        UNAMORTIZED_CENTS, LOT_PIECES, OPEN_COMMITMENT_PIECES
    )
    assert expected_actual == ACTUAL_RECOVERY_CENTS, (
        "1.5 times the pro-rata share of 4 790 000 cents against 499 000 pieces, "
        f"rounded up, is 14 399 cents, got {expected_actual}"
    )
    assert computed["actual_basis_recovery_cents"] == ACTUAL_RECOVERY_CENTS, (
        "the accelerated projection was recomputed against the reduced balance and "
        f"the reduced commitment, giving 14 399 cents, got "
        f"{computed['actual_basis_recovery_cents']}"
    )

    # The computed read must agree with the rows it was derived from, read both
    # singly and through their listings.
    tool = validate_success(
        api.get_tooling_asset(world.tooling_id, PROGRAM_MANAGER_HEADERS)
    )
    assert tool["recovered_cents"] == computed["recovered_cents"], (
        "the tool's own read carries the same recovered balance as the computed "
        f"read, expected {computed['recovered_cents']} got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == computed["unamortized_cents"], (
        "the tool's own read carries the same outstanding balance, expected "
        f"{computed['unamortized_cents']} got {tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the balance did not reach zero, so the tool is still AMORTIZING, got "
        f"{tool['amortization_status']}"
    )

    tools, tools_meta = validate_paginated(
        api.list_tooling_assets(
            PROGRAM_MANAGER_HEADERS,
            {"design_id": world.design_id, "amortization_status": C.AMORT_AMORTIZING},
        )
    )
    assert tools_meta["total_count"] == 1, (
        f"the design carries exactly one armed tool, got {tools_meta['total_count']}"
    )
    for field in (
        "id",
        "amortization_status",
        "original_cost_cents",
        "recovered_cents",
        "unamortized_cents",
        "amort_per_piece_cents",
        "amortization_basis_pieces",
    ):
        assert tools[0][field] == tool[field], (
            f"the listed tool and the single-resource read agree on {field}, got "
            f"{tools[0][field]} and {tool[field]}"
        )

    program = validate_success(api.get_program(world.program_id, PROGRAM_MANAGER_HEADERS))
    assert program["open_commitment_pieces"] == computed["open_commitment_pieces"], (
        "the program's own read carries the same open commitment the computed read "
        f"divided by, expected {computed['open_commitment_pieces']} got "
        f"{program['open_commitment_pieces']}"
    )
    assert program["shipped_pieces"] == LOT_PIECES, (
        f"the 1 000 shipped pieces are counted as shipped, got {program['shipped_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        f"the only lot has left allocation, got {program['allocated_pieces']}"
    )
    assert program["committed_pieces"] == COMMITTED_PIECES, (
        "the commitment itself is fixed at 500 000 pieces and no shipment moves it, "
        f"got {program['committed_pieces']}"
    )
    A.assert_commitment_conserved(program)

    programs, programs_meta = validate_paginated(
        api.list_programs(
            PROGRAM_MANAGER_HEADERS, {"delivery_posture": C.POSTURE_ON_TRACK}
        )
    )
    assert programs_meta["total_count"] == 1, (
        "the shipped program reads ON_TRACK in the listing immediately, got "
        f"{programs_meta['total_count']}"
    )
    for field in (
        "id",
        "delivery_posture",
        "committed_pieces",
        "open_commitment_pieces",
        "allocated_pieces",
        "shipped_pieces",
        "quarantined_lot_count",
        "version",
    ):
        assert programs[0][field] == program[field], (
            f"the listed program and the single-resource read agree on {field}, got "
            f"{programs[0][field]} and {program[field]}"
        )
