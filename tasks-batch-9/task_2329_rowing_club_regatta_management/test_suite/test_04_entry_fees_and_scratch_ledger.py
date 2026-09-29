"""Submitting entries: the pinned fee order, the closed-entries gate that
outranks a delinquent seat, and the regatta fee ledger across full refunds.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_entry_fee_components_sum,
    assert_regatta_entry,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    declare_coxed_four_lineup,
    declare_single_lineup,
    enrol_athlete,
    enrol_coxswain,
    issue_invoice,
    move_regatta_to,
    open_away_regatta,
    open_entry,
    open_regatta,
    read_entry,
    read_member,
    read_regatta,
    scratch_entry,
    set_clock_to,
    submit_entry,
)

SPRINTS_ENTRY_DEADLINE = "2026-08-05T00:00:00Z"
SPRINTS_SUBMISSION_CLOCK = "2026-08-06T09:00:00Z"


@pytest.fixture
def late_away_coxed_four(cast):
    """A coxed four entered for an away regatta, declared but not yet submitted."""
    regatta = open_away_regatta(
        name="Riverside Sprints",
        race_date_at="2026-08-08T08:00:00Z",
        entry_deadline_at=SPRINTS_ENTRY_DEADLINE,
        scratch_deadline_at="2026-08-07T00:00:00Z",
        weigh_in_opens_at="2026-08-07T06:00:00Z",
        weigh_in_closes_at="2026-08-07T10:00:00Z",
    )
    shell = add_coxed_four(hull_name="Heron")
    cox = enrol_coxswain("Kip Cox", 52.0)
    rowers = [enrol_athlete(f"Rower {index}", "COMPETITIVE", 80.0) for index in range(1, 5)]
    entry = open_entry(
        regatta["id"],
        shell["id"],
        cast["coach_headers"],
        event_code="MIXED_4PLUS_OPEN",
        boat_class="4+",
        seed_time_seconds=400.0,
    )
    entry = declare_coxed_four_lineup(
        entry, cox["id"], [rower["id"] for rower in rowers], cast["coach_headers"]
    )
    return {"regatta": regatta, "shell": shell, "entry": entry}


@pytest.fixture
def delinquent_crew_after_deadline(cast):
    """A declared entry whose only rower is in arrears, on a regatta that has closed."""
    regatta = open_regatta()
    shell = add_single(hull_name="Kingfisher")
    rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    issue_invoice(rower["id"], billable_months=12, due_at="2026-09-01T00:00:00Z")
    entry = open_entry(
        regatta["id"], shell["id"], cast["coach_headers"], event_code="W1X_OPEN"
    )
    entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
    set_clock_to(regatta["entry_deadline_at"])
    regatta = move_regatta_to(regatta["id"], "ENTRIES_CLOSED")
    return {"regatta": regatta, "entry": entry, "rower": rower}


@pytest.fixture
def two_declared_home_singles(cast):
    """Two singles declared for a home head race, neither submitted yet."""
    regatta = open_regatta(name="Club Head Race")
    entries = []
    for index, (hull_name, seed) in enumerate(
        (("Kingfisher", 380.0), ("Cygnet", 385.0)), start=1
    ):
        shell = add_single(hull_name=hull_name)
        rower = enrol_athlete(f"Rower {index}", "COMPETITIVE", 80.0 + index)
        entry = open_entry(
            regatta["id"], shell["id"], cast["coach_headers"], seed_time_seconds=seed
        )
        entries.append(declare_single_lineup(entry, rower["id"], cast["coach_headers"]))
    return {"regatta": regatta, "entries": entries}


class TestLateFeeKeyedOnSubtotal:
    def test_late_percentage_reads_the_subtotal_not_the_total(self, cast, late_away_coxed_four):
        """The threshold is tested against base plus levy, before any late fee.

        PRD: "Step four: the late-fee percentage is keyed on that subtotal — 15
        percent (0.15) when the subtotal is 25000 cents or more, and 10 percent
        (0.10) otherwise."

        Design: Difficulty/combinatorial_formula/entry_fee_late_pct_keyed_on_presubtotal_mode_c
        """
        set_clock_to(SPRINTS_SUBMISSION_CLOCK)
        entry = assert_regatta_entry(
            submit_entry(late_away_coxed_four["entry"]["id"], cast["coach_headers"])
        )
        assert entry["base_fee_cents"] == 13500, (
            f"a 4+ costs 13500 cents to enter, got {entry['base_fee_cents']}"
        )
        assert entry["transport_levy_cents"] == 10000, (
            "a 4+ occupies two rack units, levied at 5000 cents each for an away "
            f"regatta, got {entry['transport_levy_cents']}"
        )
        assert entry["late_fee_cents"] == 2350, (
            "a subtotal of 23500 is below the 25000-cent threshold, so the late "
            f"fee is 10 percent of 23500 = 2350, got {entry['late_fee_cents']}"
        )
        assert entry["status"] == "SUBMITTED", (
            f"a late submission is still accepted, got {entry['status']}"
        )

    def test_total_rejects_the_circular_total_keyed_reading(self, cast, late_away_coxed_four):
        """Keying the percentage on the total would make the definition circular.

        PRD: "A `4+` racing away and submitted late therefore has a subtotal of
        23500 cents, which is below the 25000-cent threshold, so the percentage
        is 10 percent, the late fee is 2350 cents and the total is 25850 cents —
        not the 27025 cents that the circular reading would settle on."

        Design: Difficulty/combinatorial_formula/entry_fee_late_pct_keyed_on_presubtotal_mode_c
        """
        set_clock_to(SPRINTS_SUBMISSION_CLOCK)
        entry = assert_entry_fee_components_sum(
            submit_entry(late_away_coxed_four["entry"]["id"], cast["coach_headers"])
        )
        assert entry["total_fee_cents"] == 25850, (
            f"the total is 23500 + 2350 = 25850, got {entry['total_fee_cents']}"
        )
        assert entry["late_fee_cents"] != 3525, (
            "3525 is 15 percent of 23500; the threshold test itself must read the "
            "subtotal, not a higher band"
        )
        assert entry["total_fee_cents"] != 27025, (
            "27025 is the circular reading in which the percentage is keyed on the "
            "total; the subtotal is the only key"
        )
        regatta = read_regatta(late_away_coxed_four["regatta"]["id"])
        assert regatta["net_fee_cents"] == 25850, (
            f"the regatta ledger picks up the whole fee, got {regatta['net_fee_cents']}"
        )


class TestEntriesClosedOutranksDelinquentSeat:
    def test_closed_entries_are_reported_ahead_of_the_fiscal_block(
        self, cast, delinquent_crew_after_deadline
    ):
        """Two gates fail at once; the regatta-state gate is the one reported.

        PRD: "The regatta must still be `OPEN_FOR_ENTRY`
        (`ERR_REGATTA_ENTRIES_CLOSED`), the entry must be `LINEUP_DECLARED`
        (`ERR_ENTRY_NOT_DECLARED`), the hull's `condition_index_conservative`
        must be at least 60 (`ERR_SHELL_CONDITION_TOO_LOW`)"

        Design: Difficulty/priority_pair_validation_conflict/submit_entries_closed_state_outranks_seat_dues_fiscal_block
        """
        response = api_client.submit_regatta_entry(
            delinquent_crew_after_deadline["entry"]["id"], {}, cast["coach_headers"]
        )
        validate_error(response, ApiErrorId.ERR_REGATTA_ENTRIES_CLOSED.value)

    def test_refused_submission_assesses_no_fee_and_moves_no_state(
        self, cast, delinquent_crew_after_deadline
    ):
        """Nothing on the submission path runs when the entry window has shut.

        PRD: "Submission stamps `submitted_at` from the logical clock, assesses
        the fee, moves every `COXSWAIN` seat's `weigh_in_status` from
        `NOT_REQUIRED` to `PENDING`, recomputes the regatta's `net_fee_cents`,
        and moves the entry `LINEUP_DECLARED → SUBMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_entries_closed_state_outranks_seat_dues_fiscal_block
        """
        api_client.submit_regatta_entry(
            delinquent_crew_after_deadline["entry"]["id"], {}, cast["coach_headers"]
        )
        entry = assert_regatta_entry(read_entry(delinquent_crew_after_deadline["entry"]["id"]))
        assert entry["status"] == "LINEUP_DECLARED", (
            f"the refused entry stays LINEUP_DECLARED, got {entry['status']}"
        )
        assert entry["submitted_at"] is None, (
            f"no submission instant is stamped, got {entry['submitted_at']}"
        )
        assert entry["total_fee_cents"] == 0, (
            f"no fee is assessed on a refusal, got {entry['total_fee_cents']}"
        )
        regatta = read_regatta(delinquent_crew_after_deadline["regatta"]["id"])
        assert regatta["net_fee_cents"] == 0, (
            f"the regatta ledger is untouched, got {regatta['net_fee_cents']}"
        )
        rower = read_member(delinquent_crew_after_deadline["rower"]["id"])
        assert rower["dues_balance_cents"] == 74000, (
            "the rower's arrears are unaffected by the refusal, expected 74000, "
            f"got {rower['dues_balance_cents']}"
        )


class TestNetFeeLedgerRoundTrip:
    def test_each_submission_adds_its_whole_fee_to_the_ledger(
        self, cast, two_declared_home_singles
    ):
        """The ledger is the running sum over fee-bearing entries.

        PRD: "A regatta's `net_fee_cents` is at all times the sum, over its
        entries in status `SUBMITTED`, `CONFIRMED`, `RACED` or `SCRATCHED`, of
        `total_fee_cents` less `refund_cents` where a refund has been computed."

        Design: Difficulty/compensating_invariant/regatta_net_fee_ledger_returns_to_zero_after_full_refund_scratches
        """
        regatta_id = two_declared_home_singles["regatta"]["id"]
        assert read_regatta(regatta_id)["net_fee_cents"] == 0, (
            "a regatta with no submitted entries carries a zero ledger"
        )
        submit_entry(two_declared_home_singles["entries"][0]["id"], cast["coach_headers"])
        assert read_regatta(regatta_id)["net_fee_cents"] == 4500, (
            "one submitted single puts 4500 cents on the ledger"
        )
        submit_entry(two_declared_home_singles["entries"][1]["id"], cast["coach_headers"])
        assert read_regatta(regatta_id)["net_fee_cents"] == 9000, (
            "two submitted singles put 9000 cents on the ledger"
        )
        assert read_regatta(regatta_id)["deposit_held_cents"] == 0, (
            "entry fees never touch the protest deposit ledger"
        )

    def test_full_refund_scratches_return_the_ledger_to_zero(
        self, cast, two_declared_home_singles
    ):
        """A scratch before the entry deadline refunds the whole fee.

        PRD: "When the logical clock at the scratch is at or before the
        regatta's `entry_deadline_at`, the percentage is 100 percent (1.00);
        otherwise, when it is at or before `scratch_deadline_at`, it is 55
        percent (0.55); after that it is zero (0.00)."

        Design: Difficulty/compensating_invariant/regatta_net_fee_ledger_returns_to_zero_after_full_refund_scratches
        """
        regatta_id = two_declared_home_singles["regatta"]["id"]
        entries = two_declared_home_singles["entries"]
        for entry in entries:
            submit_entry(entry["id"], cast["coach_headers"])

        first = scratch_entry(entries[0]["id"], cast["coach_headers"])
        assert first["refund_cents"] == 4500, (
            f"a full refund returns the entire 4500-cent fee, got {first['refund_cents']}"
        )
        assert read_regatta(regatta_id)["net_fee_cents"] == 4500, (
            "the scratched entry now contributes nothing, leaving the other 4500"
        )

        second = scratch_entry(entries[1]["id"], cast["coach_headers"])
        assert second["refund_cents"] == 4500, (
            f"the second scratch also refunds in full, got {second['refund_cents']}"
        )
        regatta = read_regatta(regatta_id)
        assert regatta["net_fee_cents"] == 0, (
            f"the ledger closes back at zero, got {regatta['net_fee_cents']}"
        )
        assert regatta["deposit_held_cents"] == 0, (
            "the deposit ledger never moved"
        )

        rows, _meta = validate_paginated(
            api_client.list_regatta_entries(cast["coach_headers"], {"regatta_id": regatta_id})
        )
        assert len(rows) == 2, (
            f"both scratched entries are still listed, got {len(rows)} rows"
        )
        for row in rows:
            assert row["status"] == "SCRATCHED", (
                f"entry {row['id']} should read SCRATCHED, got {row['status']}"
            )
