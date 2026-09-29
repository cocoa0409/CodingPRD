"""Recognition allocation: four buckets, four tier multipliers and a rounding
order that is visible to the cent."""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    create_edition,
    create_sponsorship_commitment,
    get_commitment,
    get_edition,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_liaison_headers"]


def _pledge(tier, pledged_cents):
    edition = create_edition()
    commitment = create_sponsorship_commitment(
        edition["id"], sponsor_name="Cardinal Mutual", sponsor_kind="CORPORATE",
        tier=tier, pledged_cents=pledged_cents,
    )
    return edition, commitment


def _allocate(commitment_id, expected_version):
    return api_client.allocate_sponsorship_commitment(
        commitment_id, {"expected_games_edition_version": expected_version}, SPONSOR
    )


def test_silver_allocation_rounds_each_bucket_before_summing_them():
    """PRD §3.9: "The tier sets a recognition multiplier: `BRONZE` recognises the pledge at
    par, one times the pledged amount; `SILVER` at one and five hundredths; `GOLD` at
    one and twelve hundredths; and `PLATINUM` at one and a quarter."
    PRD §3.9: "The four buckets take fixed shares of the pledge and are filled in this
    declared order: `VENUE_SIGNAGE` takes forty percent, `ATHLETE_SERVICES` thirty
    percent, `MEDICAL_COVERAGE` twenty percent and `SOCIAL_PROGRAM` the remaining ten
    percent."
    PRD §3.9: "Each bucket's figure is computed independently as the `pledged_cents`
    multiplied by that bucket's share and by the tier multiplier, and each is then
    rounded to a whole number of cents on its own, with a half cent rounding upward."
    PRD §3.9: "Only after all four buckets have been rounded are they added together,
    and that sum — not a separately rounded product of pledge and multiplier — becomes
    the commitment's `recognized_cents`."
    PRD §3.9: "The four rounded figures are stored as the `allocation_map`, keyed by
    bucket name, and `recognized_cents` is added to the edition's
    `sponsorship_recognized_cents` ledger."

    A 250100-cent pledge at one and five hundredths gives bucket products of
    105042, 78781.5, 52521 and 26260.5.  Rounding each half-cent up on its own and
    only then adding gives 262606; rounding the pledge-times-multiplier total once
    would have given 262605, so the extra cent is the whole point.

    Design: Difficulty/combinatorial_formula/sponsorship_per_bucket_rounding_beats_sum_then_round_by_one_cent
    """
    edition, commitment = _pledge("SILVER", 250100)

    allocated = validate_success(_allocate(commitment["id"], edition["version"]))

    assert allocated["status"] == "ALLOCATED"
    assert allocated["recognized_cents"] == 262606
    assert allocated["recognized_cents"] != 262605
    assert allocated["allocation_map"]["VENUE_SIGNAGE"] == 105042
    assert allocated["allocation_map"]["ATHLETE_SERVICES"] == 78782
    assert allocated["allocation_map"]["MEDICAL_COVERAGE"] == 52521
    assert allocated["allocation_map"]["SOCIAL_PROGRAM"] == 26261
    assert get_edition(edition["id"])["sponsorship_recognized_cents"] == 262606


def test_the_platinum_multiplier_shows_the_same_ordering_at_a_different_rate():
    """PRD §3.9: "The tier sets a recognition multiplier: `BRONZE` recognises the pledge at
    par, one times the pledged amount; `SILVER` at one and five hundredths; `GOLD` at
    one and twelve hundredths; and `PLATINUM` at one and a quarter."
    PRD §3.9: "Each bucket's figure is computed independently as the `pledged_cents`
    multiplied by that bucket's share and by the tier multiplier, and each is then
    rounded to a whole number of cents on its own, with a half cent rounding upward."
    PRD §3.9: "Only after all four buckets have been rounded are they added together,
    and that sum — not a separately rounded product of pledge and multiplier — becomes
    the commitment's `recognized_cents`."
    PRD §2.8: "Sponsorship recognition rounds four times, once per recognition bucket,
    before the buckets are summed; rounding the multiplied total once instead is a
    different and incorrect answer."

    At one and a quarter the same pledge yields 125050, 93787.5, 62525 and
    31262.5.  Per-bucket rounding gives 312626 where a once-rounded total would
    have given 312625 — the ordering, not the tier, is what produces the cent.

    Design: Difficulty/combinatorial_formula/sponsorship_per_bucket_rounding_beats_sum_then_round_by_one_cent
    """
    edition, commitment = _pledge("PLATINUM", 250100)

    allocated = validate_success(_allocate(commitment["id"], edition["version"]))

    assert allocated["recognized_cents"] == 312626
    assert allocated["allocation_map"] == {
        "VENUE_SIGNAGE": 125050,
        "ATHLETE_SERVICES": 93788,
        "MEDICAL_COVERAGE": 62525,
        "SOCIAL_PROGRAM": 31263,
    }


def test_bronze_recognises_the_pledge_at_par_across_the_four_shares():
    """PRD §3.9: "The tier sets a recognition multiplier: `BRONZE` recognises the pledge at
    par, one times the pledged amount; `SILVER` at one and five hundredths; `GOLD` at
    one and twelve hundredths; and `PLATINUM` at one and a quarter."
    PRD §3.9: "The four buckets take fixed shares of the pledge and are filled in this
    declared order: `VENUE_SIGNAGE` takes forty percent, `ATHLETE_SERVICES` thirty
    percent, `MEDICAL_COVERAGE` twenty percent and `SOCIAL_PROGRAM` the remaining ten
    percent."
    PRD §3.9: "Each bucket's figure is computed independently as the `pledged_cents`
    multiplied by that bucket's share and by the tier multiplier, and each is then
    rounded to a whole number of cents on its own, with a half cent rounding upward."
    PRD §3.9: "The four rounded figures are stored as the `allocation_map`, keyed by
    bucket name, and `recognized_cents` is added to the edition's
    `sponsorship_recognized_cents` ledger."

    The par multiplier leaves nothing to round, so the four shares — forty, thirty,
    twenty and the remaining ten percent — must reconstruct the pledge exactly.

    Design: Difficulty/combinatorial_formula/sponsorship_per_bucket_rounding_beats_sum_then_round_by_one_cent
    """
    edition, commitment = _pledge("BRONZE", 250100)

    allocated = validate_success(_allocate(commitment["id"], edition["version"]))

    assert allocated["allocation_map"] == {
        "VENUE_SIGNAGE": 100040,
        "ATHLETE_SERVICES": 75030,
        "MEDICAL_COVERAGE": 50020,
        "SOCIAL_PROGRAM": 25010,
    }
    assert allocated["recognized_cents"] == 250100
    assert get_edition(edition["id"])["sponsorship_recognized_cents"] == 250100


def test_a_stale_edition_version_blocks_the_write_to_the_shared_ledger():
    """PRD §3.9: "The commitment must still be `PLEDGED`, the edition must not yet be
    `IMPACT_FINALIZED`, and the caller must supply an `expected_games_edition_version`
    matching the edition's current `version`, since the allocation writes to the shared
    edition ledger; a stale figure is refused with `ERR_STALE_GAMES_EDITION_VERSION`."
    PRD §2.7: "A mismatch against the edition's current `version` is rejected with
    `ERR_STALE_GAMES_EDITION_VERSION` (HTTP 412)."
    PRD §2.7: "The recognition ledger `sponsorship_recognized_cents` is a shared running
    total, so an allocation computed against a stale edition view would post onto a
    balance the client never saw."
    PRD §3.9: "Success moves the commitment `PLEDGED` → `ALLOCATED` and increments both
    the edition's `version` and the commitment's own `version`."
    PRD §3.9: "It opens `PLEDGED` with `recognized_cents` at zero and an empty
    `allocation_map`."

    Allocation writes to a ledger on the edition, so it is guarded by the
    edition's own version, which the first allocation has already advanced.  The
    second sponsor presenting that spent figure is refused and nothing moves: the
    commitment is still `PLEDGED` with an empty breakdown and the ledger still
    holds only the first sponsor's recognition.

    Design: Difficulty/combinatorial_formula/sponsorship_per_bucket_rounding_beats_sum_then_round_by_one_cent
    """
    edition, first = _pledge("BRONZE", 120000)
    stale_version = edition["version"]
    commitment = create_sponsorship_commitment(
        edition["id"], sponsor_name="Northline Bank", sponsor_kind="CORPORATE",
        tier="SILVER", pledged_cents=250100,
    )
    validate_success(_allocate(first["id"], stale_version))

    response = _allocate(commitment["id"], stale_version)

    validate_error(response, ApiErrorId.ERR_STALE_GAMES_EDITION_VERSION.value)
    stale = get_commitment(commitment["id"])
    assert stale["status"] == "PLEDGED"
    assert stale["recognized_cents"] == 0
    assert stale["allocation_map"] == {}
    assert get_edition(edition["id"])["sponsorship_recognized_cents"] == 120000
