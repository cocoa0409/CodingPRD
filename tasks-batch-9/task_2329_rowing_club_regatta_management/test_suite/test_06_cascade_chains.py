"""Two long cascades: condemning a hull out from under a seeded heat, and the
delinquency checkpoint reaching all the way down to a race entry.
"""

import pytest

from test_helpers import (
    assert_damage_report,
    assert_heat_lane_counts_conserved,
    assert_lineup_seat,
    assert_member,
    assert_shell,
    make_member_headers,
    validate_success,
)
from test_helpers.fixtures import (
    add_single,
    assign_lanes,
    condemn_report,
    declare_single_lineup,
    drive_regatta_to_racing,
    enrol_athlete,
    issue_invoice,
    lane_of_entry,
    make_confirmed_single_entry,
    open_entry,
    open_regatta,
    read_entry,
    read_heat,
    read_lane,
    read_member,
    read_regatta,
    read_shell,
    run_delinquency,
    schedule_heat,
    seats_of_entry,
    set_clock_to,
    submit_entry,
    make_condemnable_report,
)

RACING_CLOCK = "2026-08-12T09:00:00Z"
LATE_SCRATCH_DEADLINE = "2026-08-13T00:00:00Z"


@pytest.fixture
def seeded_heat_with_condemnable_hull(cast):
    """Two confirmed singles seeded into a heat, one of them on a structurally
    damaged hull awaiting condemnation."""
    regatta = open_regatta(scratch_deadline_at=LATE_SCRATCH_DEADLINE)
    heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=4)
    hulls = []
    entries = []
    rowers = []
    for index, seed in enumerate((380.0, 390.0), start=1):
        shell = add_single(hull_name=f"Hull-{index}")
        rower = enrol_athlete(f"Rower {index}", "COMPETITIVE", 80.0 + index)
        hulls.append(shell)
        rowers.append(rower)
        entries.append(
            make_confirmed_single_entry(
                regatta,
                shell,
                rower["id"],
                cast["coach_headers"],
                cast["official_headers"],
                seed_time_seconds=seed,
            )
        )
    drive_regatta_to_racing(regatta, racing_clock=RACING_CLOCK)
    heat = assign_lanes(heat["id"], cast["official_headers"])
    report = make_condemnable_report(
        hulls[0]["id"],
        rowers[0]["id"],
        make_member_headers(rowers[0]["id"]),
        cast["boatman_headers"],
    )
    return {
        "regatta": regatta,
        "heat": heat,
        "hulls": hulls,
        "entries": entries,
        "report": report,
        "lanes": [lane_of_entry(entry["id"]) for entry in entries],
    }


@pytest.fixture
def past_due_racing_commitment(cast):
    """A submitted single whose rower falls past due before the checkpoint runs."""
    regatta = open_regatta()
    shell = add_single(hull_name="Kingfisher")
    rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    entry = open_entry(
        regatta["id"],
        shell["id"],
        cast["coach_headers"],
        event_code="W1X_OPEN",
        seed_time_seconds=420.0,
    )
    entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
    entry = submit_entry(entry["id"], cast["coach_headers"])
    invoice = issue_invoice(rower["id"], billable_months=12, due_at="2026-08-05T00:00:00Z")
    set_clock_to("2026-08-06T00:00:00Z")
    return {
        "regatta": regatta,
        "entry": entry,
        "rower": rower,
        "invoice": invoice,
    }


class TestCondemnationCascade:
    def test_condemnation_retires_the_hull_and_scratches_its_crew(
        self, cast, seeded_heat_with_condemnable_hull
    ):
        """Retiring a hull scratches every entry that was going to race it.

        PRD: "From there the cascade continues: every entry racing that hull in
        status `DRAFT`, `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` is
        scratched, every session in status `PLANNED` or `CLEARED` on that hull is
        cancelled, the scratched entries' pending race lanes are voided, the
        heats holding those lanes are demoted from `LANES_ASSIGNED` back to
        `SCHEDULED`, and any trailer rack units those entries held are released
        with the owning trailer's counters recomputed."

        Design: Difficulty/transitive_cascade/condemn_hull_cascade_report_shell_entry_lane_heat_depth_five
        """
        scenario = seeded_heat_with_condemnable_hull
        report = assert_damage_report(
            condemn_report(scenario["report"]["id"], cast["boatman_headers"])
        )
        assert report["status"] == "CONDEMNED", (
            f"the structural report ends CONDEMNED, got {report['status']}"
        )
        hull = assert_shell(read_shell(scenario["hulls"][0]["id"]))
        assert hull["status"] == "RETIRED", (
            f"the condemned hull follows DAMAGED -> RETIRED, got {hull['status']}"
        )
        assert hull["condition_index_conservative"] == 100, (
            "a condemned report leaves both index input sets, so the conservative "
            f"index returns to 100, got {hull['condition_index_conservative']}"
        )
        assert hull["condition_index_optimistic"] == 100, (
            "a condemned report leaves both index input sets, so the optimistic "
            f"index returns to 100, got {hull['condition_index_optimistic']}"
        )
        scratched = read_entry(scenario["entries"][0]["id"])
        assert scratched["status"] == "SCRATCHED", (
            f"the entry racing that hull is scratched, got {scratched['status']}"
        )
        assert scratched["refund_cents"] == 2475, (
            "a scratch after the entry deadline but on or before the scratch "
            f"deadline refunds 55 percent of 4500 = 2475, got {scratched['refund_cents']}"
        )

    def test_condemnation_voids_the_whole_lane_draw_and_demotes_the_heat(
        self, cast, seeded_heat_with_condemnable_hull
    ):
        """A heat that loses a crew is re-seeded from scratch, not run a lane short.

        PRD: "Demoting the heat voids every remaining lane on it that is still
        `PENDING` and recomputes `occupied_lane_count` to 0: the whole heat must
        be re-seeded rather than run a lane short."

        Design: Difficulty/transitive_cascade/condemn_hull_cascade_report_shell_entry_lane_heat_depth_five
        """
        scenario = seeded_heat_with_condemnable_hull
        condemn_report(scenario["report"]["id"], cast["boatman_headers"])

        first_lane = read_lane(scenario["lanes"][0]["id"])
        assert first_lane["lane_status"] == "VOIDED", (
            "the scratched entry's pending lane is voided, got "
            f"{first_lane['lane_status']}"
        )
        second_lane = read_lane(scenario["lanes"][1]["id"])
        assert second_lane["lane_status"] == "VOIDED", (
            "demoting the heat voids every remaining pending lane, got "
            f"{second_lane['lane_status']}"
        )
        heat = assert_heat_lane_counts_conserved(read_heat(scenario["heat"]["id"]))
        assert heat["status"] == "SCHEDULED", (
            f"the heat is demoted LANES_ASSIGNED -> SCHEDULED, got {heat['status']}"
        )
        assert heat["occupied_lane_count"] == 0, (
            f"occupied_lane_count is recomputed to 0, got {heat['occupied_lane_count']}"
        )
        assert heat["free_lane_count"] == 4, (
            f"all four lanes are free again, got {heat['free_lane_count']}"
        )
        survivor = read_entry(scenario["entries"][1]["id"])
        assert survivor["status"] == "CONFIRMED", (
            "the crew on the sound hull keeps its confirmation, got "
            f"{survivor['status']}"
        )
        regatta = read_regatta(scenario["regatta"]["id"])
        assert regatta["net_fee_cents"] == 6525, (
            "the ledger is 4500 - 2475 for the scratched crew plus 4500 for the "
            f"survivor, expected 6525, got {regatta['net_fee_cents']}"
        )


class TestDelinquencyCascade:
    def test_checkpoint_flags_the_past_due_invoice_and_puts_the_member_on_hold(
        self, past_due_racing_commitment
    ):
        """The first two hops of the checkpoint chain.

        PRD: "Hop two: any member for whom at least one invoice transitioned
        into `DELINQUENT` *inside this same run* moves `ACTIVE → DUES_HOLD`, with
        `boathouse_access_level` recomputed to `NONE`."

        Design: Difficulty/transitive_cascade/delinquency_run_cascade_invoice_member_seat_entry_depth_four
        """
        swept = validate_success(run_delinquency(season_year=2026))
        assert isinstance(swept, list), (
            f"the checkpoint reports the invoices it moved as an array, got {type(swept)}"
        )
        assert len(swept) == 1, (
            f"exactly one invoice was past due, got {len(swept)} rows"
        )
        assert swept[0]["id"] == past_due_racing_commitment["invoice"]["id"], (
            "the swept row is the past-due invoice"
        )
        assert swept[0]["status"] == "DELINQUENT", (
            f"the swept invoice moves to DELINQUENT, got {swept[0]['status']}"
        )
        assert swept[0]["assessed_cents"] == 74000, (
            "a RECREATIONAL member billed the full season owes 61500 + 12500 = "
            f"74000, got {swept[0]['assessed_cents']}"
        )
        assert swept[0]["paid_cents"] == 0, (
            f"nothing was ever paid against it, got {swept[0]['paid_cents']}"
        )

        member = assert_member(read_member(past_due_racing_commitment["rower"]["id"]))
        assert member["membership_status"] == "DUES_HOLD", (
            f"the billed member moves ACTIVE -> DUES_HOLD, got {member['membership_status']}"
        )
        assert member["boathouse_access_level"] == "NONE", (
            f"a member on hold has no boathouse access, got {member['boathouse_access_level']}"
        )
        assert member["dues_balance_cents"] == 74000, (
            f"the balance is the whole unpaid assessment, got {member['dues_balance_cents']}"
        )

    def test_checkpoint_blocks_the_seat_and_demotes_the_racing_entry(
        self, past_due_racing_commitment
    ):
        """The last two hops reach the lineup seat and its parent entry.

        PRD: "Hop four: each seat that just became `BLOCKED_DUES` drives its
        parent entry `SUBMITTED → LINEUP_DECLARED`, and that demotion in turn
        voids the entry's pending race lanes and demotes their heats, exactly as
        described in §3.6 and §3.8."

        Design: Difficulty/transitive_cascade/delinquency_run_cascade_invoice_member_seat_entry_depth_four
        """
        run_delinquency(season_year=2026)

        seats = seats_of_entry(past_due_racing_commitment["entry"]["id"])
        assert len(seats) == 1, f"a 1X carries one seat, got {len(seats)}"
        seat = assert_lineup_seat(seats[0])
        assert seat["eligibility_status"] == "BLOCKED_DUES", (
            "the seat held by the member on hold is blocked on the fiscal gate, "
            f"got {seat['eligibility_status']}"
        )
        entry = read_entry(past_due_racing_commitment["entry"]["id"])
        assert entry["status"] == "LINEUP_DECLARED", (
            f"the blocked seat demotes its entry SUBMITTED -> LINEUP_DECLARED, got {entry['status']}"
        )
        regatta = read_regatta(past_due_racing_commitment["regatta"]["id"])
        assert regatta["net_fee_cents"] == 0, (
            "a demoted entry leaves the fee ledger's input set, got "
            f"{regatta['net_fee_cents']}"
        )
