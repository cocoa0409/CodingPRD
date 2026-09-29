"""Version tokens on designs, coilers and quotes, and the counters a ship must reconcile.

Three writes in this shop can silently destroy another writer's work, so each one
carries the parent row's revision counter as a required field: a revision quotes
the design's counter, a setup booking quotes the coiler's, and a quote quotes the
program's. Every scenario here first performs a genuine intervening write that
moves the counter, then replays the token the client was holding, and checks both
the refusal and that the refused call left every field of the target row exactly
where the accepted write had put it.

The last two scenarios follow the same discipline into the ledgers: a prototype
abandoned before any approval package existed writes its tooling off without
zeroing the balance, and one partial shipment out of two allocated lots has to
leave five derived figures — shipped, allocated and open pieces on the program,
and recovered and unamortized cents on the tool — agreeing with each other.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_STALE_DESIGN_VERSION,
    ERR_STALE_MACHINE_VERSION,
    ERR_STALE_PROGRAM_VERSION,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
)

# D1 re-coiled at 10 active coils, and at the 12 coils the refused replay asked
# for. Both sets follow from the PRD's own spring-rate and wire-mass formulas on
# the canonical 2.5 mm chrome-silicon geometry.
TEN_COIL_SPRING_RATE = 7.225
TEN_COIL_WIRE_MASS_KG = 0.025422
TWELVE_COIL_SPRING_RATE = 6.021
TWELVE_COIL_WIRE_MASS_KG = 0.029659

# A second coiling window a clear hour after the first one closes, so the 45
# minute changeover buffer is honoured and only the stale token can refuse it.
SECOND_WINDOW_START = "2026-08-05T13:00:00Z"
SECOND_WINDOW_END = "2026-08-05T15:00:00Z"

# The canonical 26 000-piece price, and the 3 000-piece re-price the refused
# replay would have produced had it ever reached the pricing steps.
QUOTED_SUBTOTAL_CENTS = 552_690
QUOTED_DISCOUNT_PCT = 0.06
QUOTED_AMORT_PER_PIECE_CENTS = 4
QUOTED_UNIT_PRICE_CENTS = 24
QUOTED_TOTAL_CENTS = 749_000
REPRICE_UNIT_PRICE_CENTS = 26
REPRICE_TOTAL_CENTS = 203_000

# The canonical tool and commitment the ledger assertions balance against.
TOOLING_COST_CENTS = 4_800_000
COMMITTED_PIECES = 500_000
AMORT_PER_PIECE_CENTS = 10

# The partial-shipment split: two lots off one completed run, the larger shipped.
LOT_A_PIECES = 20_000
LOT_B_PIECES = 5_000
LOT_A_EXTENDED_PRICE_CENTS = 480_000
LOT_A_RECOVERY_CENTS = 200_000


def test_second_revision_replaying_the_first_expected_design_version_is_refused(
    api: ApiClient,
) -> None:
    """The revision writer is the design's own concurrency token, so it burns once.

    One accepted revision takes D1 to ten active coils and advances the counter.
    Replaying the very token that revision was authorised with, this time asking
    for twelve coils, is refused at 412 and the ten-coil geometry survives
    untouched — the twelve-coil spring rate and mass are never written.

    PRD §2.7: "Three write operations can silently destroy work that another
    writer has already done, so all three are guarded by optimistic concurrency
    control against a parent row's `version`."
    PRD §2.7: "If the value does not equal the parent row's current `version`,
    the write is rejected and nothing is mutated."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_DESIGN_VERSION` (HTTP 412)."
    PRD §2.4: "`SpringDesign.version` follows the general rule, and the revision
    operation increments it by 1 like any other mutation of the design row."
    PRD §3.3: "An accepted revision does the following bookkeeping:
    `superseded_revision_no` is set to the value `current_revision_no` held
    before the revision, `current_revision_no` is increased by 1,
    `release_status` returns to `DRAFT`, `reviewed_by_user_id` is cleared to
    null, and `created_by_user_id` is re-stamped with the revising engineer's
    `X-User-ID` — so the segregation-of-duties gate on the next review is
    measured against whoever cut the latest revision."
    PRD §3.3: "Every computed engineering field is then recalculated from the
    post-revision geometry: spring rate, all four stress fields, the fatigue
    criterion and margin, the life tier, the per-piece wire mass, and the
    tangle-risk index and class."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal
    shear modulus multiplied by the wire diameter raised to the fourth power,
    divided by the product of eight, the mean coil diameter cubed, and the
    active coil count, with the result rounded half up to three decimal places."

    Design: Corner/complexity_layers/second_revision_replaying_the_first_expected_design_version_is_stale
    """
    world = X.build_world(api, "prototype")
    observed_version = world.design["version"]

    # The write that genuinely supersedes the token: ten active coils, accepted.
    first = validate_success(
        api.revise_design(
            world.design_id,
            F.revision_payload(observed_version, active_coils=10),
            DESIGN_ENGINEER_HEADERS,
        )
    )
    assert first["version"] == observed_version + 1, (
        "an accepted revision advances the design's counter by exactly one, from "
        f"{observed_version} to {first['version']}"
    )
    assert first["active_coils"] == 10, (
        f"the accepted revision re-coiled D1 to ten coils, got {first['active_coils']}"
    )
    assert first["spring_rate_n_per_mm"] == TEN_COIL_SPRING_RATE, (
        "ten active coils on the canonical geometry give a 7.225 N/mm rate, got "
        f"{first['spring_rate_n_per_mm']}"
    )
    assert first["current_revision_no"] == 2, (
        f"the revision increases current_revision_no to 2, got {first['current_revision_no']}"
    )
    assert first["superseded_revision_no"] == 1, (
        "superseded_revision_no takes the revision number held before the cut, got "
        f"{first['superseded_revision_no']}"
    )
    assert first["release_status"] == C.RELEASE_DRAFT, (
        f"a revision returns the design to DRAFT, got {first['release_status']}"
    )

    # The replay: the same token, now one behind, asking for twelve coils.
    refused = api.revise_design(
        world.design_id,
        F.revision_payload(observed_version, active_coils=12),
        DESIGN_ENGINEER_HEADERS,
    )
    validate_error(refused, ERR_STALE_DESIGN_VERSION, 412)

    design = X.refresh_design(api, world.design_id)
    assert design["version"] == first["version"], (
        "the refused revision mutated nothing, so the counter still reads the value "
        f"the accepted revision left, expected {first['version']} got {design['version']}"
    )
    assert design["active_coils"] == 10, (
        f"the ten-coil geometry survives the refused replay, got {design['active_coils']}"
    )
    assert design["spring_rate_n_per_mm"] == TEN_COIL_SPRING_RATE, (
        "the stored spring rate is still the ten-coil figure 7.225 N/mm, got "
        f"{design['spring_rate_n_per_mm']}"
    )
    assert design["spring_rate_n_per_mm"] != TWELVE_COIL_SPRING_RATE, (
        "the twelve-coil rate 6.021 N/mm was never computed, because the refused "
        "call never reached the engineering stack"
    )
    assert design["wire_mass_per_piece_kg"] == TEN_COIL_WIRE_MASS_KG, (
        "the stored per-piece mass is still the ten-coil figure 0.025422 kg, got "
        f"{design['wire_mass_per_piece_kg']}"
    )
    assert design["wire_mass_per_piece_kg"] != TWELVE_COIL_WIRE_MASS_KG, (
        "the twelve-coil mass 0.029659 kg was never written"
    )
    assert design["release_status"] == C.RELEASE_DRAFT, (
        f"the design still sits in the DRAFT the accepted revision left it in, got "
        f"{design['release_status']}"
    )
    assert design["current_revision_no"] == 2, (
        "the refused replay did not cut a third revision, got "
        f"{design['current_revision_no']}"
    )


def test_second_setup_replaying_the_machine_version_from_creation_is_refused(
    api: ApiClient,
) -> None:
    """Booking a window bumps the coiler, so the next booking must re-read it.

    The 13:00–15:00Z window is a clear hour past the end of the 08:00–12:00Z
    window already on the machine, so it clears the 45 minute changeover buffer
    on both sides and is legal on every temporal and physical ground. Replaying
    the version captured at commissioning is nevertheless refused at 412, and
    the schedule the stale writer would have superseded is still intact. Booking
    the identical window with the coiler's current version then succeeds and
    performs exactly the supersession the guard was protecting.

    PRD §2.7: "A mismatch is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412)."
    PRD §2.7: "If the value does not equal the parent row's current `version`,
    the write is rejected and nothing is mutated."
    PRD §2.4: "`CoilingMachine.version` is incremented by every operation that
    changes the coiler's occupancy: scheduling a machine setup, activating a
    setup, aborting a setup that was `ACTIVE`, opening a production run,
    completing a run, cancelling a run, and rejecting a first article (which
    cancels the run)."
    PRD §2.4: "Each of those increments the counter by exactly 1."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the
    technician's `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and
    increases the coiler's `version` by 1."
    PRD §3.6: "It also performs a supersession sweep: every **other** setup on
    the same machine for the same design whose `setup_status` is `SCHEDULED`
    transitions `SCHEDULED → SUPERSEDED`, and each superseded row's
    `superseded_by_setup_id` is set to the id of the setup that has just been
    created."
    PRD §3.6: "Two windows conflict when the new window's start is strictly
    earlier than the existing window's end plus the buffer **and** the existing
    window's start is strictly earlier than the new window's end plus the buffer."
    PRD §2.10: "`MachineSetup.superseded_by_setup_id` is likewise a
    denormalised pointer to the setup whose creation superseded this one, and is
    null unless the row's `setup_status` is `SUPERSEDED`."

    Design: Corner/complexity_layers/second_setup_replaying_the_machine_version_from_creation_is_stale
    """
    world = X.build_world(api, "tooling")
    machine = X.commission_machine(api)
    observed_version = machine["version"]

    first_setup = X.book_setup(api, machine, world.design_id, world.tooling_id)
    assert first_setup["setup_status"] == C.SETUP_SCHEDULED, (
        f"the first booking opens SCHEDULED, got {first_setup['setup_status']}"
    )
    after_first = X.refresh_machine(api, machine["id"])
    assert after_first["version"] == observed_version + 1, (
        "scheduling a setup increases the coiler's counter by exactly one, from "
        f"{observed_version} to {after_first['version']}"
    )

    # The replay: the commissioning token against a legal, non-conflicting window.
    refused = api.create_setup(
        F.setup_payload(
            machine["id"],
            world.design_id,
            world.tooling_id,
            observed_version,
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(refused, ERR_STALE_MACHINE_VERSION, 412)

    setups, meta = validate_paginated(
        api.list_setups(PROCESS_TECHNICIAN_HEADERS, {"machine_id": machine["id"]})
    )
    assert meta["total_count"] == 1, (
        "the refused booking created no setup row, so the coiler still carries one "
        f"window, got {meta['total_count']}"
    )
    assert len(setups) == 1, "exactly one setup row exists on the coiler"

    survivor = X.refresh_setup(api, first_setup["id"])
    assert survivor["setup_status"] == C.SETUP_SCHEDULED, (
        "the schedule the stale writer would have swept is still SCHEDULED, got "
        f"{survivor['setup_status']}"
    )
    assert survivor["superseded_by_setup_id"] is None, (
        "nothing superseded the surviving window, so its pointer is still null, got "
        f"{survivor['superseded_by_setup_id']}"
    )

    coiler = X.refresh_machine(api, machine["id"])
    assert coiler["machine_state"] == C.MACHINE_IDLE, (
        f"a booking never occupies the coiler, which reads IDLE, got {coiler['machine_state']}"
    )
    assert coiler["version"] == observed_version + 1, (
        "the refused booking mutated nothing, so the coiler's counter still reads "
        f"{observed_version + 1}, got {coiler['version']}"
    )
    assert coiler["active_setup_id"] is None, (
        f"no setup is ACTIVE, so active_setup_id is null, got {coiler['active_setup_id']}"
    )

    # The same window, re-read token: legal on every ground, and it sweeps.
    second_setup = validate_success(
        api.create_setup(
            F.setup_payload(
                machine["id"],
                world.design_id,
                world.tooling_id,
                coiler["version"],
                window_start=SECOND_WINDOW_START,
                window_end=SECOND_WINDOW_END,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        201,
    )
    assert second_setup["setup_status"] == C.SETUP_SCHEDULED, (
        "the 13:00–15:00Z window clears the 45 minute buffer and books, got "
        f"{second_setup['setup_status']}"
    )
    swept = X.refresh_setup(api, first_setup["id"])
    assert swept["setup_status"] == C.SETUP_SUPERSEDED, (
        "the accepted booking swept the earlier window for the same machine and "
        f"design to SUPERSEDED, got {swept['setup_status']}"
    )
    assert swept["superseded_by_setup_id"] == second_setup["id"], (
        "the swept row points at the booking that superseded it, got "
        f"{swept['superseded_by_setup_id']}"
    )


def test_requote_replaying_the_program_version_from_creation_is_refused(
    api: ApiClient,
) -> None:
    """The quote is the only writer of the program's counter, so it invalidates itself.

    The 26 000-piece price is computed and the counter advances. A second quote
    replaying the version the program was opened with — this time for 3 000
    pieces, which would land in a different discount tier and a different
    amortization cap — is refused at 412, and every frozen figure on the program
    is still the 26 000-piece answer.

    PRD §2.7: "A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."
    PRD §2.7: "If the value does not equal the parent row's current `version`,
    the write is rejected and nothing is mutated."
    PRD §2.4: "`CustomerProgram.version` is incremented **only** by the program
    quoting operation, `POST /customer-programs/{id}/quote`, and by nothing else."
    PRD §3.11: "The endpoint also increments the program's `version` by 1."
    PRD §3.11: "`quoted_pre_discount_subtotal_cents` is the base unit cost
    multiplied by `quoted_qty`, rounded to whole cents."
    PRD §3.11: "`quoted_volume_discount_pct` is read off that subtotal against
    the breakpoints 50000, 250000 and 1000000 cents: below 50000 it is 0.00,
    below 250000 it is 0.03, below 1000000 it is 0.06, and at or above 1000000 it
    is 0.09."
    PRD §3.11: "`quoted_unit_price_cents` is the discounted unit cost plus that
    per-piece amortization, rounded to whole cents."
    PRD §3.11: "`quoted_total_cents` is `quoted_unit_price_cents` multiplied by
    `quoted_qty` plus the flat setup fee of 125000 cents."
    PRD §3.1: "`quote_frozen` starts false and every quoted figure —
    `quoted_qty`, `quoted_pre_discount_subtotal_cents`,
    `quoted_volume_discount_pct`, `quoted_tooling_amort_per_piece_cents`,
    `quoted_unit_price_cents` and `quoted_total_cents` — starts null."

    Design: Corner/complexity_layers/requote_replaying_the_program_version_from_creation_is_stale
    """
    world = X.build_world(api, "tooling")
    observed_version = world.program["version"]

    priced = X.price_program(api, world.program, world.design_id, quoted_qty=26_000)
    assert priced["quoted_qty"] == 26_000, (
        f"the accepted quote priced 26 000 pieces, got {priced['quoted_qty']}"
    )
    assert priced["version"] == observed_version + 1, (
        "the quoting endpoint advances the program's counter by exactly one, from "
        f"{observed_version} to {priced['version']}"
    )

    # The replay: the opening token against a quantity in a different tier.
    refused = api.quote_program(
        world.program_id,
        F.quote_payload(world.design_id, observed_version, quoted_qty=3_000),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(refused, ERR_STALE_PROGRAM_VERSION, 412)

    program = X.refresh_program(api, world.program_id)
    assert program["version"] == priced["version"], (
        "the refused quote mutated nothing, so the counter still reads "
        f"{priced['version']}, got {program['version']}"
    )
    assert program["quoted_qty"] == 26_000, (
        "the frozen quantity is still the accepted 26 000, not the refused 3 000, got "
        f"{program['quoted_qty']}"
    )
    assert program["quoted_pre_discount_subtotal_cents"] == QUOTED_SUBTOTAL_CENTS, (
        "the pre-discount subtotal is still the 26 000-piece figure 552 690 cents, got "
        f"{program['quoted_pre_discount_subtotal_cents']}"
    )
    assert program["quoted_volume_discount_pct"] == QUOTED_DISCOUNT_PCT, (
        "552 690 cents sits in the 0.06 tier and the refused replay did not re-read "
        f"the ladder, got {program['quoted_volume_discount_pct']}"
    )
    assert (
        program["quoted_tooling_amort_per_piece_cents"] == QUOTED_AMORT_PER_PIECE_CENTS
    ), (
        "the per-piece amortization is still the cap-bound 4 cents from the accepted "
        f"quote, got {program['quoted_tooling_amort_per_piece_cents']}"
    )
    assert program["quoted_unit_price_cents"] == QUOTED_UNIT_PRICE_CENTS, (
        f"the frozen unit price is still 24 cents, got {program['quoted_unit_price_cents']}"
    )
    assert program["quoted_unit_price_cents"] != REPRICE_UNIT_PRICE_CENTS, (
        "the 3 000-piece unit price of 26 cents was never computed, because the "
        "refused call never reached the eleven pricing steps"
    )
    assert program["quoted_total_cents"] == QUOTED_TOTAL_CENTS, (
        f"the frozen total is still 749 000 cents, got {program['quoted_total_cents']}"
    )
    assert program["quoted_total_cents"] != REPRICE_TOTAL_CENTS, (
        "the 3 000-piece total of 203 000 cents was never written"
    )
    assert program["quote_frozen"] is False, (
        "no customer has granted the package, so the quote is still unfrozen and the "
        f"refusal was purely the version guard, got {program['quote_frozen']}"
    )


def test_obsoleting_a_prototype_writes_its_pending_tooling_off_without_zeroing_it(
    api: ApiClient,
) -> None:
    """A write-off records the loss; it does not clear the ledger it lost.

    The tool was capitalised but its design never reached production, so the
    amortization basis was never frozen and not one cent was ever recovered.
    Retiring the design takes the tool straight from `PENDING` to `WRITTEN_OFF`
    with the whole 4 800 000 cents still sitting in `unamortized_cents`, and the
    program's posture is re-derived to `BLOCKED`.

    PRD §3.3: "On success the design moves to `OBSOLETE`; every tooling asset of
    the design whose `amortization_status` is `PENDING` or `AMORTIZING`
    transitions to `WRITTEN_OFF`, with `unamortized_cents` and `recovered_cents`
    left exactly as they stood — a write-off records the loss, it does not zero
    the ledger; every machine setup of the design still in `SCHEDULED`
    transitions to `ABORTED`; and the owning program's `delivery_posture` is
    re-derived, which lands on `BLOCKED`."
    PRD §3.3: "A prototype abandoned before its approval package was ever
    granted writes its tooling off directly from `PENDING` rather than from
    `AMORTIZING`."
    PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING`
    with `recovered_cents` at 0 and `unamortized_cents` equal to
    `original_cost_cents`."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay
    null: until the customer has granted full approval, nobody knows over how
    many pieces the tool will be recovered."
    PRD §3.4: "From either `PENDING` or `AMORTIZING`, the design's retirement
    drives the tool to `WRITTEN_OFF` and freezes both ledger figures where they
    stood."
    PRD §2.9: "`recovered_cents` and `unamortized_cents` always sum to it."
    PRD §3.1: "If no submission of the program is in either granted status, the
    posture is `BLOCKED`."

    Design: Corner/complexity_layers/obsoleting_a_prototype_design_writes_its_pending_tooling_off
    """
    world = X.build_world(api, "tooling")
    assert world.tooling["amortization_status"] == C.AMORT_PENDING, (
        "the tool starts PENDING because no package has been granted, got "
        f"{world.tooling['amortization_status']}"
    )

    retired = validate_success(
        api.obsolete_design(world.design_id, ENGINEERING_MANAGER_HEADERS)
    )
    assert retired["release_status"] == C.RELEASE_OBSOLETE, (
        f"retirement is terminal and lands on OBSOLETE, got {retired['release_status']}"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_WRITTEN_OFF, (
        "the retirement took the PENDING tool straight to WRITTEN_OFF, got "
        f"{tool['amortization_status']}"
    )
    assert tool["unamortized_cents"] == TOOLING_COST_CENTS, (
        "the write-off froze the balance where it stood, so all 4 800 000 cents are "
        f"still outstanding, got {tool['unamortized_cents']}"
    )
    assert tool["recovered_cents"] == 0, (
        "no shipment ever posted against this tool, so nothing was recovered, got "
        f"{tool['recovered_cents']}"
    )
    assert tool["amort_per_piece_cents"] is None, (
        "the basis was never armed, so the per-piece figure is still null, got "
        f"{tool['amort_per_piece_cents']}"
    )
    assert tool["amortization_basis_pieces"] is None, (
        f"the basis piece count is still null, got {tool['amortization_basis_pieces']}"
    )
    A.assert_tooling_ledger_conserved(tool)

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no granted package survives the retirement, so the re-derived posture is "
        f"BLOCKED, got {program['delivery_posture']}"
    )


def test_program_counters_and_the_tooling_ledger_reconcile_after_a_partial_ship(
    api: ApiClient,
) -> None:
    """Shipping one of two lots has to move four counters and leave both totals intact.

    Two lots — 20 000 and 5 000 pieces — are cut from one completed run, and only
    the larger one is packed and shipped. The commitment ledger must show the
    shipped pieces leaving allocation without touching the open commitment, which
    was consumed back at allocation time, and the tooling ledger must show
    exactly the straight-line recovery for 20 000 pieces moving from
    `unamortized_cents` into `recovered_cents` while their sum stays at the
    capitalised cost.

    PRD §3.11: "On the program, `open_commitment_pieces` decreases by
    `piece_count` and `allocated_pieces` increases by it, conserving
    `committed_pieces`, and `delivery_posture` is re-derived."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and
    `shipped_pieces` increases by it — `open_commitment_pieces` is untouched,
    because the commitment was consumed at allocation."
    PRD §3.11: "Shipping then posts the tooling recovery computed under the
    program's `amortization_method` as described in section 3.4, writes it to the
    lot's `tooling_recovery_cents`, adds it to the tool's `recovered_cents` and
    subtracts it from `unamortized_cents`, and takes the tool `AMORTIZING →
    FULLY_AMORTIZED` if that leaves `unamortized_cents` at zero."
    PRD §3.11: "The lot becomes `SHIPPED` with `shipped_at` stamped from the
    logical clock, and `delivery_posture` is re-derived."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the
    amount is the lot's `piece_count` multiplied by the tool's frozen
    `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`;
    whichever of the two is smaller is posted."
    PRD §2.9: "`recovered_cents` and `unamortized_cents` always sum to it."
    PRD §2.9: "A program's `committed_pieces` is fixed when the program is
    opened."
    PRD §3.1: "Otherwise the posture is `ON_TRACK`."

    Design: Corner/complexity_layers/program_counters_and_the_tooling_ledger_reconcile_after_a_partial_ship
    """
    world = X.build_world(api, "approved")
    armed_tool = X.refresh_tooling(api, world.tooling_id)
    assert armed_tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the customer's full approval armed the tool, got "
        f"{armed_tool['amortization_status']}"
    )
    assert armed_tool["amort_per_piece_cents"] == AMORT_PER_PIECE_CENTS, (
        "the frozen per-piece figure is the 4 800 000-cent cost over the 500 000-piece "
        f"basis, rounded up to 10 cents, got {armed_tool['amort_per_piece_cents']}"
    )
    assert armed_tool["amortization_basis_pieces"] == COMMITTED_PIECES, (
        "the basis is the program's committed pieces, got "
        f"{armed_tool['amortization_basis_pieces']}"
    )

    lot_a = X.allocate_lot(api, world.run_id, world.program_id, LOT_A_PIECES)
    lot_b = X.allocate_lot(api, world.run_id, world.program_id, LOT_B_PIECES)
    X.pack_lot(api, lot_a["id"])
    shipped = X.ship_lot(api, lot_a["id"])

    expected_recovery = A.expected_forecast_recovery_cents(
        LOT_A_PIECES, AMORT_PER_PIECE_CENTS, TOOLING_COST_CENTS
    )
    assert expected_recovery == LOT_A_RECOVERY_CENTS, (
        "20 000 pieces at 10 cents is 200 000 cents, well under the outstanding "
        f"balance, so the cap does not bind, got {expected_recovery}"
    )

    assert shipped["lot_status"] == C.LOT_SHIPPED, (
        f"the packed lot ships, got {shipped['lot_status']}"
    )
    assert shipped["shipped_at"] is not None, (
        "shipping stamps shipped_at from the logical clock, got "
        f"{shipped['shipped_at']}"
    )
    assert shipped["extended_price_cents"] == LOT_A_EXTENDED_PRICE_CENTS, (
        "the lot snapshotted 20 000 pieces at the frozen 24-cent unit price, giving "
        f"480 000 cents, got {shipped['extended_price_cents']}"
    )
    assert shipped["unit_price_cents"] == QUOTED_UNIT_PRICE_CENTS, (
        f"the lot carries the quote's 24-cent unit price, got {shipped['unit_price_cents']}"
    )
    assert shipped["tooling_amort_per_piece_cents"] == QUOTED_AMORT_PER_PIECE_CENTS, (
        "the lot snapshotted the quote's cap-bound 4 cents, which is a different "
        "figure from the tool's frozen 10 cents, got "
        f"{shipped['tooling_amort_per_piece_cents']}"
    )
    assert shipped["tooling_recovery_cents"] == LOT_A_RECOVERY_CENTS, (
        "the posting is driven by the tool's frozen 10 cents, not the lot's 4-cent "
        f"snapshot, so 200 000 cents were recovered, got {shipped['tooling_recovery_cents']}"
    )

    held_back = X.refresh_lot(api, lot_b["id"])
    assert held_back["lot_status"] == C.LOT_ALLOCATED, (
        "the second lot was never packed, so it is still ALLOCATED, got "
        f"{held_back['lot_status']}"
    )
    assert held_back["tooling_recovery_cents"] == 0, (
        "an unshipped lot has posted nothing against the tool, got "
        f"{held_back['tooling_recovery_cents']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == LOT_A_PIECES, (
        f"the 20 000 shipped pieces are counted as shipped, got {program['shipped_pieces']}"
    )
    assert program["allocated_pieces"] == LOT_B_PIECES, (
        "only the 5 000-piece lot is still allocated, got "
        f"{program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == COMMITTED_PIECES - (
        LOT_A_PIECES + LOT_B_PIECES
    ), (
        "both allocations consumed the commitment and the shipment left it alone, so "
        f"475 000 pieces remain open, got {program['open_commitment_pieces']}"
    )
    assert program["quarantined_lot_count"] == 0, (
        f"no lot was quarantined, got {program['quarantined_lot_count']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "a granted package with no quarantined lot and no held run reads ON_TRACK, got "
        f"{program['delivery_posture']}"
    )
    A.assert_commitment_conserved(program)

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["recovered_cents"] == LOT_A_RECOVERY_CENTS, (
        f"the tool recovered 200 000 cents, got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == TOOLING_COST_CENTS - LOT_A_RECOVERY_CENTS, (
        "the same 200 000 cents left the outstanding balance, leaving 4 600 000, got "
        f"{tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the balance did not reach zero, so the tool is still AMORTIZING, got "
        f"{tool['amortization_status']}"
    )
    A.assert_tooling_ledger_conserved(tool)

    lots, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"program_id": world.program_id})
    )
    assert meta["total_count"] == 2, (
        f"the run carries exactly the two lots that were cut, got {meta['total_count']}"
    )
    posted = sum(row["tooling_recovery_cents"] for row in lots)
    assert posted == tool["recovered_cents"], (
        "the tool's recovered balance is the sum of what the lots posted, expected "
        f"{tool['recovered_cents']} got {posted}"
    )
