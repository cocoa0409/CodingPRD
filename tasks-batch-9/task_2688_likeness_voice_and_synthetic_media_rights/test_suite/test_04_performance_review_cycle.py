"""The review loop's round cap, and the money it winds back on the way out."""

from test_helpers import assertions, fixtures

REVISIONS = (
    ("trim the intro", "30 second radio spot v2", 900_000),
    ("still too breathy", "30 second radio spot v3", 2_000_000),
    ("one more pass", "30 second radio spot v4", 12_000_000),
)


def _thrice_revised_performance():
    """A submitted output taken around the revision loop its three legal times."""
    scenario = fixtures.campaign_submitted_performance()
    for review_note, description, projection in REVISIONS:
        fixtures.review_performance(
            scenario, "REQUEST_REVISION", {"review_note": review_note}
        )
        fixtures.resubmit_performance(
            scenario,
            {"intended_use_description": description, "projected_impressions": projection},
        )
    return scenario


def test_fourth_revision_request_rejects_instead_of_looping_again():
    """The same trigger that looped three times now ends the performance.

    The PRD states: "A `REQUEST_REVISION` arriving when `revision_round` has
    already reached three does not loop: it rejects the performance instead, with
    `rejection_reason` of `REVISION_LIMIT_REACHED` and the same reversal."

    Design: Difficulty/non_linear_state_machine/performance_revision_cycle_terminates_at_round_cap
    """
    scenario = _thrice_revised_performance()

    looped = fixtures.refresh_performance(scenario)
    assert looped["review_status"] == "SUBMITTED"
    assert looped["revision_round"] == 3
    assert looped["provisional_compensation_cents"] == 470_250

    fixtures.review_performance(
        scenario, "REQUEST_REVISION", {"review_note": "cannot approve this read"}
    )

    performance = fixtures.refresh_performance(scenario)
    assert performance["review_status"] == "REJECTED"
    assert performance["review_status"] != "REVISION_REQUESTED"
    assert performance["rejection_reason"] == "REVISION_LIMIT_REACHED"
    assert performance["revision_round"] == 3
    assert performance["provisional_compensation_cents"] == 0


def test_every_loop_leaves_its_accrual_and_its_reversal_behind():
    """Four provisional accruals and four reversals net back to the creation fee.

    The PRD states: "The stale accrual is not adjusted in place: a `REVERSAL`
    entry undoes the live `PER_USE_PROVISIONAL` entry, then a fresh
    `PER_USE_PROVISIONAL` entry is appended for the amount the provisional
    calculation yields on the new `projected_impressions`, and
    `provisional_compensation_cents` becomes that new amount." The projections of
    900000, 2000000 and 12000000 sit in three different reach tiers, so the four
    accruals are 346500, 247500, 346500 and 470250.

    Design: Difficulty/non_linear_state_machine/performance_revision_cycle_terminates_at_round_cap
    """
    scenario = _thrice_revised_performance()
    fixtures.review_performance(
        scenario, "REQUEST_REVISION", {"review_note": "cannot approve this read"}
    )

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
        ],
    )
    assert [entry["amount_cents"] for entry in entries] == [
        300_000,
        346_500,
        -346_500,
        247_500,
        -247_500,
        346_500,
        -346_500,
        470_250,
        -470_250,
    ]
    assertions.assert_ledger_sums_to(entries, 300_000)

    grant = fixtures.refresh_grant(scenario)
    assert grant["total_compensation_cents"] == 300_000
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )


def test_rejection_restores_the_roll_ups_to_their_pre_submission_values():
    """346500 accrues on submission and is wound back to the cent on rejection.

    The PRD states: "`REJECT` moves it `SUBMITTED → REJECTED`, stamping
    `rejection_reason` from the payload — the reasons in the vocabulary are
    `OFF_BRAND`, `OUT_OF_SCOPE`, `QUALITY`, `REVIEW_WINDOW_LAPSED` and
    `REVISION_LIMIT_REACHED` — appending a `REVERSAL` entry that exactly negates
    the live `PER_USE_PROVISIONAL` entry, including the exact negation of its
    three share columns, and setting `provisional_compensation_cents` to zero."

    Design: Difficulty/compensating_invariant/ledger_sum_restored_after_provisional_accrual_is_reversed
    """
    scenario = fixtures.campaign_approved_replica()

    grant = fixtures.refresh_grant(scenario)
    assert grant["total_compensation_cents"] == 300_000
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )
    assert len(fixtures.grant_ledger(scenario)) == 1

    fixtures.submit_performance(scenario, fixtures.CAMPAIGN_PERFORMANCE)
    assert fixtures.refresh_performance(scenario)["provisional_compensation_cents"] == 346_500
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 646_500

    fixtures.review_performance(
        scenario,
        "REJECT",
        {"review_note": "not the read we wanted", "rejection_reason": "OFF_BRAND"},
    )

    performance = fixtures.refresh_performance(scenario)
    assert performance["review_status"] == "REJECTED"
    assert performance["rejection_reason"] == "OFF_BRAND"
    assert performance["provisional_compensation_cents"] == 0
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 300_000
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )


def test_the_undo_is_a_negation_row_and_each_share_column_reconciles_alone():
    """The reversal names its predecessor and negates it column by column.

    The PRD states: "A `REVERSAL` entry is never re-derived from the percentages.
    Its `amount_cents` is the exact negation of the reversed entry's amount, and
    its three share fields are the exact negations of that entry's three share
    fields." The reversed row itself survives untouched: "A `CompensationEntry` is
    a ledger movement: once appended it is never modified, and a movement that
    stops being correct is undone by appending an opposing entry."

    Design: Difficulty/compensating_invariant/ledger_sum_restored_after_provisional_accrual_is_reversed
    """
    scenario = fixtures.campaign_approved_replica()
    fixtures.submit_performance(scenario, fixtures.CAMPAIGN_PERFORMANCE)
    fixtures.review_performance(
        scenario,
        "REJECT",
        {"review_note": "not the read we wanted", "rejection_reason": "OFF_BRAND"},
    )

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "REVERSAL"]
    )
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000, 225_000, 60_000, 15_000)
    assertions.assert_ledger_entry(
        entries[1], "PER_USE_PROVISIONAL", 346_500, 259_875, 69_300, 17_325
    )
    assertions.assert_ledger_entry(
        entries[2], "REVERSAL", -346_500, -259_875, -69_300, -17_325
    )
    assertions.assert_exact_negation(entries[2], entries[1])
    for entry in entries:
        assertions.assert_immutable_record(entry)

    assert sum(entry["talent_share_cents"] for entry in entries) == 225_000
    assert sum(entry["agency_share_cents"] for entry in entries) == 60_000
    assert sum(entry["administrator_share_cents"] for entry in entries) == 15_000
