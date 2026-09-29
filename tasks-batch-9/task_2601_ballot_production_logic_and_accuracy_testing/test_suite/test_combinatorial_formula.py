"""Rotation-adjusted printed positions on a ballot face.

The printed position of a candidate is never stored: it is derived, per (style,
contest) pair, from the election's rotation policy, the style's rotation seed,
the ordinal of the contest's district inside the style's district set, the size
of the roster admitted by the requested basis and the contest's own rotation
opt-out. These tests pin the printed layout of styles whose rosters are
deliberately identical, so that only the rotation group can explain a
difference, and they also pin the frozen contest order and the base ordering
that sit underneath the rotation.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import test_users as users
from test_helpers.constants import (
    BASIS_CERTIFIED,
    CONTEST_TYPE_MEASURE,
    DISTRICT_D07,
    DISTRICT_D12,
    DISTRICT_D19,
    DISTRICT_D99,
    ORDER_ALPHABETICAL,
    ORDER_FILING,
    ROTATION_DISTRICT,
    ROTATION_PRECINCT,
    STYLE_CODE_ALT,
    STYLE_CODE_LOW,
    STYLE_CODE_MAIN,
)

# The four ballot names are reused verbatim in every contest of the district
# scenario, so N is 4 everywhere and only the rotation group can differ.
_ALPHABETICAL_ROSTER = (
    ("Ana Alvarez", "Alvarez", "2026-06-01T09:00:00Z"),
    ("Ben Brooks", "Brooks", "2026-06-02T09:00:00Z"),
    ("Cai Chen", "Chen", "2026-06-03T09:00:00Z"),
    ("Dee Dawson", "Dawson", "2026-06-04T09:00:00Z"),
)

# Filing times deliberately run against the alphabet, so the two ordering
# methods disagree on every single position.
_REVERSE_FILED_ROSTER = (
    ("Dee Dawson", "Dawson", "2026-06-01T09:00:00Z"),
    ("Cai Chen", "Chen", "2026-06-02T09:00:00Z"),
    ("Ben Brooks", "Brooks", "2026-06-03T09:00:00Z"),
    ("Ana Alvarez", "Alvarez", "2026-06-04T09:00:00Z"),
)


def _add_roster(sc: fixtures.Scenario, contest_id: str,
                roster=_ALPHABETICAL_ROSTER) -> Dict[str, str]:
    """File one candidate per roster line and return ballot_name -> candidate id."""
    filed: Dict[str, str] = {}
    for full_name, ballot_name, filing_received_at in roster:
        filed[ballot_name] = fixtures.add_candidate(
            sc,
            contest_id=contest_id,
            full_name=full_name,
            ballot_name=ballot_name,
            filing_received_at=filing_received_at,
        )
    return filed


def _layout(sc: fixtures.Scenario, style_id: str) -> Dict[str, Any]:
    return validate_success(
        sc.client.get_layout(style_id, users.COORDINATOR, f.layout_params(BASIS_CERTIFIED)))


def _contest_block(layout: Dict[str, Any], contest_id: str) -> Dict[str, Any]:
    blocks = [entry for entry in layout["contests"] if entry.get("contest_id") == contest_id]
    assert len(blocks) == 1, (
        f"the layout must carry exactly one block for contest {contest_id}, found {len(blocks)}"
    )
    return blocks[0]


def _emitted_order(block: Dict[str, Any]) -> List[str]:
    return [entry["candidate_id"] for entry in block["candidates"]]


def _emitted_positions(block: Dict[str, Any]) -> List[int]:
    return [entry["printed_position"] for entry in block["candidates"]]


def _base_indices(block: Dict[str, Any]) -> Dict[str, int]:
    return {entry["candidate_id"]: entry["base_order_index"] for entry in block["candidates"]}


def _district_rotation_world(client) -> Dict[str, Any]:
    """Three four-name contests in three districts of one style, plus a measure.

    S-050 over D-99 is created first so that S-100 — the style under test, which
    covers D-07, D-12 and D-19 — ranks second by style_code and therefore takes
    rotation seed 1. Inside S-100 the district ordinals are 0 for D-07, 1 for
    D-12 and 2 for D-19.
    """
    sc = fixtures.new_election(
        client, rotation_policy=ROTATION_DISTRICT,
        candidate_order_method=ORDER_ALPHABETICAL)

    assessor = fixtures.add_contest(
        sc, title="County Assessor", district_code=DISTRICT_D07, rotation_required=True)
    assessor_ids = _add_roster(sc, assessor)
    fixtures.certify_contest(sc, assessor)

    sheriff = fixtures.add_contest(
        sc, title="County Sheriff", district_code=DISTRICT_D12, rotation_required=True)
    sheriff_ids = _add_roster(sc, sheriff)
    fixtures.certify_contest(sc, sheriff)

    clerk = fixtures.add_contest(
        sc, title="County Clerk", district_code=DISTRICT_D19, rotation_required=False)
    clerk_ids = _add_roster(sc, clerk)
    fixtures.certify_contest(sc, clerk)

    measure = fixtures.add_contest(
        sc, title="Bond Measure A", contest_type=CONTEST_TYPE_MEASURE,
        district_code=DISTRICT_D07, rotation_required=True)
    fixtures.certify_contest(sc, measure)

    fixtures.add_style(sc, style_code=STYLE_CODE_LOW, district_codes=[DISTRICT_D99])
    style_id = fixtures.add_style(
        sc, style_code=STYLE_CODE_MAIN,
        district_codes=[DISTRICT_D07, DISTRICT_D12, DISTRICT_D19])
    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    return {
        "sc": sc,
        "style_id": style_id,
        "assessor": assessor,
        "sheriff": sheriff,
        "clerk": clerk,
        "measure": measure,
        "assessor_ids": assessor_ids,
        "sheriff_ids": sheriff_ids,
        "clerk_ids": clerk_ids,
    }


def _precinct_rotation_world(client) -> Dict[str, Any]:
    """One four-name contest in D-12 printed by two styles of different seeds.

    S-050 over D-99 is created first, then S-100 and S-200 both over D-12, so the
    three styles rank 0, 1 and 2 by style_code and the two styles under test
    carry rotation seeds 1 and 2.
    """
    sc = fixtures.new_election(
        client, rotation_policy=ROTATION_PRECINCT, candidate_order_method=ORDER_FILING)
    contest = fixtures.add_contest(
        sc, title="County Sheriff", district_code=DISTRICT_D12, rotation_required=True)
    candidate_ids = _add_roster(sc, contest, _REVERSE_FILED_ROSTER)
    fixtures.certify_contest(sc, contest)

    fixtures.add_style(sc, style_code=STYLE_CODE_LOW, district_codes=[DISTRICT_D99])
    seed_one_style = fixtures.add_style(
        sc, style_code=STYLE_CODE_MAIN, district_codes=[DISTRICT_D12])
    seed_two_style = fixtures.add_style(
        sc, style_code=STYLE_CODE_ALT, district_codes=[DISTRICT_D12])
    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    return {
        "sc": sc,
        "contest": contest,
        "candidate_ids": candidate_ids,
        "seed_one_style": seed_one_style,
        "seed_two_style": seed_two_style,
    }


# ---- One style, one seed, three districts: the rotation group per contest ----

def test_cf_district_layout_reports_seed_contest_and_candidate_totals(client):
    """The layout of the three-district style reports seed 1 over four contests and twelve candidates.

    PRD Section 3.2: "The layout response is a computed read rather than a stored row: it reports `style_id`, `style_code`, `revision`, the `basis` it was computed under, the election's `rotation_policy`, the style's `rotation_seed_index`, the style's `contest_count`, the total `candidate_count` across the contests it printed, and the `contests` array carrying the per-contest candidate lists."

    PRD Section 3.3: "`rotation_seed_index` is recomputed for **every** ballot style of the election whose status is not `SUPERSEDED`, as the zero-based rank of `style_code` ascending among that set."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    layout = _layout(world["sc"], world["style_id"])

    asserts.assert_fields_equal(
        layout,
        {
            "style_id": world["style_id"],
            "style_code": STYLE_CODE_MAIN,
            "revision": 1,
            "basis": BASIS_CERTIFIED,
            "rotation_policy": ROTATION_DISTRICT,
            "rotation_seed_index": 1,
            "contest_count": 4,
            "candidate_count": 12,
        },
        "layout",
    )
    assert len(layout["contests"]) == 4


def test_cf_district_ordinal_zero_rotates_the_roster_by_one(client):
    """The D-07 contest, first in the style's sorted district list, rotates its four names by one.

    PRD Section 3.2: "When the policy is `DISTRICT_ROTATION` the offset is the sum of the style's `rotation_seed_index` and the contest's district offset, reduced modulo the rotation modulus, where the district offset is the zero-based position of the contest's `district_code` within the style's `district_codes` sorted ascending."

    PRD Section 3.2: "Each candidate's `printed_position` is then the sum of its `base_order_index` and the offset, reduced modulo the rotation modulus, plus one — a one-based contiguous permutation of the positions from 1 to the roster size."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    names = world["assessor_ids"]
    layout = _layout(world["sc"], world["style_id"])

    asserts.assert_printed_positions(
        layout,
        world["assessor"],
        {
            names["Alvarez"]: 2,
            names["Brooks"]: 3,
            names["Chen"]: 4,
            names["Dawson"]: 1,
        },
    )
    block = _contest_block(layout, world["assessor"])
    assert _emitted_order(block) == [
        names["Dawson"], names["Alvarez"], names["Brooks"], names["Chen"]
    ]
    assert _emitted_positions(block) == [1, 2, 3, 4]


def test_cf_district_ordinal_one_rotates_the_same_roster_by_two(client):
    """The D-12 contest, second in the same district list, rotates the identical roster by two.

    PRD Section 3.2: "When the policy is `DISTRICT_ROTATION` the offset is the sum of the style's `rotation_seed_index` and the contest's district offset, reduced modulo the rotation modulus, where the district offset is the zero-based position of the contest's `district_code` within the style's `district_codes` sorted ascending."

    PRD Section 3.2: "The layout emits, for each contest, the list of `candidate_id`, `ballot_name`, `base_order_index` and `printed_position` in `printed_position` ascending order."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    names = world["sheriff_ids"]
    layout = _layout(world["sc"], world["style_id"])

    asserts.assert_printed_positions(
        layout,
        world["sheriff"],
        {
            names["Alvarez"]: 3,
            names["Brooks"]: 4,
            names["Chen"]: 1,
            names["Dawson"]: 2,
        },
    )
    block = _contest_block(layout, world["sheriff"])
    assert _emitted_order(block) == [
        names["Chen"], names["Dawson"], names["Alvarez"], names["Brooks"]
    ]
    assert _emitted_positions(block) == [1, 2, 3, 4]


def test_cf_contest_rotation_optout_prints_the_unrotated_roster(client):
    """The D-19 contest opts out of rotation, so it prints unrotated instead of shifted by three.

    PRD Section 3.2: "When the contest's `rotation_required` is false the offset is zero as well — a per-contest opt-out overrides the election policy for that contest alone, leaving the other contests on the same style rotating normally."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    names = world["clerk_ids"]
    layout = _layout(world["sc"], world["style_id"])

    asserts.assert_printed_positions(
        layout,
        world["clerk"],
        {
            names["Alvarez"]: 1,
            names["Brooks"]: 2,
            names["Chen"]: 3,
            names["Dawson"]: 4,
        },
    )
    block = _contest_block(layout, world["clerk"])
    assert _emitted_order(block) == [
        names["Alvarez"], names["Brooks"], names["Chen"], names["Dawson"]
    ]
    assert _emitted_positions(block) == [1, 2, 3, 4]


def test_cf_measure_contest_prints_an_empty_candidate_list(client):
    """The measure contest printed on the same style carries no candidates at all.

    PRD Section 3.2: "Three boundaries deserve attention: when no candidate passes the basis filter the contest's candidate list is empty, no modulus is evaluated, and the offset is reported as zero; when exactly one candidate passes, every seed reduces to an offset of zero, so a single-candidate contest never rotates; and because the roster size differs between the two bases, the offset itself differs between them even for an identical seed — the two bases are not a relabelling of one another."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    layout = _layout(world["sc"], world["style_id"])

    block = _contest_block(layout, world["measure"])
    assert block["candidates"] == []


def test_cf_frozen_contest_order_puts_the_measure_last(client):
    """Freezing the order numbers the three candidate contests first and the D-07 measure fourth.

    PRD Section 3.1: "Those certified contests are sorted by four keys in order: first by contest type, with `CANDIDATE` contests ahead of `MEASURE` contests; then by `district_code` ascending as a byte-wise string comparison; then by `title` ascending, likewise byte-wise; and finally by `created_at` ascending as the deterministic tiebreak."

    PRD Section 3.1: "Each contest then receives `ballot_order_index` equal to its one-based position in that sequence, so the indices are contiguous and start at 1."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    sc = world["sc"]

    assert sc.read_contest(world["assessor"])["ballot_order_index"] == 1
    assert sc.read_contest(world["sheriff"])["ballot_order_index"] == 2
    assert sc.read_contest(world["clerk"])["ballot_order_index"] == 3
    assert sc.read_contest(world["measure"])["ballot_order_index"] == 4


def test_cf_base_order_index_is_identical_across_the_three_contests(client):
    """All three contests share one base ordering, so only the rotation group differs.

    PRD Section 3.2: "The roster is ordered according to the election's `candidate_order_method`: under `ALPHABETICAL_BY_BALLOT_NAME` by `ballot_name` ascending, then `filing_received_at` ascending, then `created_at` ascending; under `FILING_ORDER` by `filing_received_at` ascending, then `ballot_name` ascending, then `created_at` ascending."

    PRD Section 3.2: "Each candidate's `base_order_index` is its zero-based rank in that order."

    Design: Difficulty/combinatorial_formula/cf_rotation_district_ordinal_and_optout
    """
    world = _district_rotation_world(client)
    layout = _layout(world["sc"], world["style_id"])

    for contest_key, names_key in (
        ("assessor", "assessor_ids"),
        ("sheriff", "sheriff_ids"),
        ("clerk", "clerk_ids"),
    ):
        names = world[names_key]
        base = _base_indices(_contest_block(layout, world[contest_key]))
        assert base[names["Alvarez"]] == 0
        assert base[names["Brooks"]] == 1
        assert base[names["Chen"]] == 2
        assert base[names["Dawson"]] == 3


# ---- Two styles, two seeds, one contest ordered by filing time ----

def test_cf_filing_order_ranks_the_roster_by_filing_time(client):
    """Under filing order the base index follows the filing instant, not the ballot name.

    PRD Section 3.2: "The roster is ordered according to the election's `candidate_order_method`: under `ALPHABETICAL_BY_BALLOT_NAME` by `ballot_name` ascending, then `filing_received_at` ascending, then `created_at` ascending; under `FILING_ORDER` by `filing_received_at` ascending, then `ballot_name` ascending, then `created_at` ascending."

    Design: Difficulty/combinatorial_formula/cf_rotation_precinct_policy_with_filing_order
    """
    world = _precinct_rotation_world(client)
    names = world["candidate_ids"]
    layout = _layout(world["sc"], world["seed_one_style"])

    base = _base_indices(_contest_block(layout, world["contest"]))
    assert base[names["Dawson"]] == 0
    assert base[names["Chen"]] == 1
    assert base[names["Brooks"]] == 2
    assert base[names["Alvarez"]] == 3


def test_cf_precinct_rotation_seed_one_shifts_the_roster_by_one(client):
    """The seed-1 style rotates the filing-ordered roster by one, with the district ordinal ignored.

    PRD Section 3.2: "When the policy is `PRECINCT_ROTATION` the offset is the style's `rotation_seed_index` reduced modulo the rotation modulus."

    PRD Section 3.2: "Each candidate's `printed_position` is then the sum of its `base_order_index` and the offset, reduced modulo the rotation modulus, plus one — a one-based contiguous permutation of the positions from 1 to the roster size."

    Design: Difficulty/combinatorial_formula/cf_rotation_precinct_policy_with_filing_order
    """
    world = _precinct_rotation_world(client)
    names = world["candidate_ids"]
    layout = _layout(world["sc"], world["seed_one_style"])

    assert layout["rotation_policy"] == ROTATION_PRECINCT
    assert layout["rotation_seed_index"] == 1
    asserts.assert_printed_positions(
        layout,
        world["contest"],
        {
            names["Dawson"]: 2,
            names["Chen"]: 3,
            names["Brooks"]: 4,
            names["Alvarez"]: 1,
        },
    )
    block = _contest_block(layout, world["contest"])
    assert _emitted_order(block) == [
        names["Alvarez"], names["Dawson"], names["Chen"], names["Brooks"]
    ]


def test_cf_precinct_rotation_seed_two_shifts_the_same_roster_by_two(client):
    """The seed-2 style of the same election prints the same roster shifted by two instead.

    PRD Section 3.2: "When the policy is `PRECINCT_ROTATION` the offset is the style's `rotation_seed_index` reduced modulo the rotation modulus."

    PRD Section 3.3: "Inserting a style whose `style_code` sorts below an existing one therefore shifts the rotation seed — and so the printed candidate order — of styles that already existed."

    Design: Difficulty/combinatorial_formula/cf_rotation_precinct_policy_with_filing_order
    """
    world = _precinct_rotation_world(client)
    names = world["candidate_ids"]
    layout = _layout(world["sc"], world["seed_two_style"])

    assert layout["rotation_policy"] == ROTATION_PRECINCT
    assert layout["rotation_seed_index"] == 2
    asserts.assert_printed_positions(
        layout,
        world["contest"],
        {
            names["Dawson"]: 3,
            names["Chen"]: 4,
            names["Brooks"]: 1,
            names["Alvarez"]: 2,
        },
    )
    block = _contest_block(layout, world["contest"])
    assert _emitted_order(block) == [
        names["Brooks"], names["Alvarez"], names["Dawson"], names["Chen"]
    ]


def test_cf_neither_seeded_layout_matches_the_unrotated_orders(client):
    """Both seeded layouts are contiguous permutations that differ from the alphabet and from filing order.

    PRD Section 3.2: "Each candidate's `printed_position` is then the sum of its `base_order_index` and the offset, reduced modulo the rotation modulus, plus one — a one-based contiguous permutation of the positions from 1 to the roster size."

    Design: Difficulty/combinatorial_formula/cf_rotation_precinct_policy_with_filing_order
    """
    world = _precinct_rotation_world(client)
    names = world["candidate_ids"]
    alphabetical = [names["Alvarez"], names["Brooks"], names["Chen"], names["Dawson"]]
    unrotated_filing = [names["Dawson"], names["Chen"], names["Brooks"], names["Alvarez"]]

    for style_key in ("seed_one_style", "seed_two_style"):
        block = _contest_block(_layout(world["sc"], world[style_key]), world["contest"])
        assert _emitted_positions(block) == [1, 2, 3, 4]
        assert _emitted_order(block) != alphabetical
        assert _emitted_order(block) != unrotated_filing
