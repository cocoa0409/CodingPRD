"""State builders for the writers-room staffing and script development API.

The harness restarts the server and empties the store before every test, so
every builder here drives the public endpoints from an empty database. Each
builder returns a plain dict of the ids and entities it created; the composite
"world" builders stack those dicts so a test can start at whatever tier of the
staffing / scripting / clearance / credit ladder it needs.

Tier 1  agreement                    the rate card alone
Tier 2  registry                     writers, showrunner, arbiters, availability
Tier 3  season                       a season with its fiscal counters at zero
Tier 4  staffing_room                a room moved OPEN -> STAFFING
Tier 5  active_room                  two confirmed seats and the room ACTIVE
Tier 6  episode                      one ordered episode
Tier 7  assignment                   a TELEPLAY assignment with its milestones
Tier 8  delivered / approved         the milestone chain landed, then approved
Tier 9  clearance                    a review, its items and their decisions
Tier 10 locked                       the episode locked for production
Tier 11 credit                       submissions closed, panel convened, ballots
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import constants as K
from . import factories as F
from .api_client import ApiClient, api_client
from .test_users import (
    GUILD_ADMINISTRATOR_HEADERS,
    LEGAL_COUNSEL_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
    make_showrunner_headers,
    make_writer_headers,
)

World = Dict[str, Any]


# --- Tier 1: the rate card ---------------------------------------------------

def seed_agreement(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register the canonical guild agreement."""
    return get_success_data(
        api.create_guild_agreement(
            F.build_guild_agreement(**overrides), GUILD_ADMINISTRATOR_HEADERS
        )
    )


# --- Tier 2: the writer registry --------------------------------------------

def seed_writer(
    api: ApiClient,
    agreement_id: str,
    legal_name: str,
    guild_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register one writer, whose level the server determines."""
    return get_success_data(
        api.create_writer(
            F.build_writer(
                agreement_id,
                legal_name=legal_name,
                guild_member_id=guild_member_id,
                **overrides,
            ),
            GUILD_ADMINISTRATOR_HEADERS,
        )
    )


def seed_window(
    api: ApiClient,
    writer_id: str,
    commitment_type: str = "EXCLUSIVE",
    start_date: str = K.WINDOW_START_DATE,
    end_date: str = K.WINDOW_END_DATE,
) -> Dict[str, Any]:
    """Declare one availability window for a writer, acting as that writer."""
    return get_success_data(
        api.create_availability_window(
            writer_id,
            F.build_availability_window(
                commitment_type=commitment_type,
                start_date=start_date,
                end_date=end_date,
            ),
            make_writer_headers(writer_id),
        )
    )


def build_registry(api: ApiClient, agreement_id: Optional[str] = None) -> World:
    """Tier 2: the rate card plus the cast of writers the ladder needs.

    sr  - showrunner, 20 credits, PRODUCER, showrunner eligible
    w1  - STORY_EDITOR with an EXCLUSIVE window
    w2  - STORY_EDITOR with a NON_EXCLUSIVE window
    w3  - STAFF_WRITER, no credits, no window
    w8  - STORY_EDITOR enrolled in the diversity programme, with a window
    ar1, ar2, ar3 - three unrelated writers available to sit on a panel
    """
    world: World = {}
    if agreement_id is None:
        agreement = seed_agreement(api)
        world["agreement"] = agreement
        agreement_id = agreement["id"]
    else:
        world["agreement"] = get_success_data(
            api.get_guild_agreement(agreement_id, GUILD_ADMINISTRATOR_HEADERS)
        )
    world["agreement_id"] = agreement_id

    sr = seed_writer(
        api,
        agreement_id,
        "Sloane Reyes",
        "GM-SHOW",
        career_episodic_credits=20,
        is_showrunner_eligible=True,
    )
    w1 = seed_writer(api, agreement_id, "Wanda Cole", "GM-1001", career_episodic_credits=3)
    w2 = seed_writer(api, agreement_id, "Bram Ochoa", "GM-1002", career_episodic_credits=3)
    w3 = seed_writer(api, agreement_id, "Ivy Nakamura", "GM-1003", career_episodic_credits=0)
    w8 = seed_writer(
        api,
        agreement_id,
        "Dara Osei",
        "GM-4001",
        career_episodic_credits=3,
        diversity_program_participant=True,
    )
    ar1 = seed_writer(api, agreement_id, "Nadia Fields", "GM-2001", career_episodic_credits=9)
    ar2 = seed_writer(api, agreement_id, "Owen Duarte", "GM-2002", career_episodic_credits=9)
    ar3 = seed_writer(api, agreement_id, "Priya Raman", "GM-2003", career_episodic_credits=9)

    world.update(
        sr=sr,
        w1=w1,
        w2=w2,
        w3=w3,
        w8=w8,
        ar1=ar1,
        ar2=ar2,
        ar3=ar3,
        sr_id=sr["id"],
        w1_id=w1["id"],
        w2_id=w2["id"],
        w3_id=w3["id"],
        w8_id=w8["id"],
        ar1_id=ar1["id"],
        ar2_id=ar2["id"],
        ar3_id=ar3["id"],
        sr_headers=make_showrunner_headers(sr["id"]),
        w1_headers=make_writer_headers(w1["id"]),
        w2_headers=make_writer_headers(w2["id"]),
        w3_headers=make_writer_headers(w3["id"]),
        w8_headers=make_writer_headers(w8["id"]),
        ar1_headers=make_writer_headers(ar1["id"]),
        ar2_headers=make_writer_headers(ar2["id"]),
        ar3_headers=make_writer_headers(ar3["id"]),
    )

    world["aw1"] = seed_window(api, w1["id"], "EXCLUSIVE")
    world["aw2"] = seed_window(api, w2["id"], "NON_EXCLUSIVE")
    world["aw8"] = seed_window(api, w8["id"], "NON_EXCLUSIVE")
    world["aw1_id"] = world["aw1"]["id"]
    world["aw2_id"] = world["aw2"]["id"]
    world["aw8_id"] = world["aw8"]["id"]
    return world


# --- Tier 3: the season ------------------------------------------------------

def seed_season(
    api: ApiClient,
    agreement_id: str,
    showrunner_writer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a season, ordered by the studio."""
    return get_success_data(
        api.create_season(
            F.build_season(agreement_id, showrunner_writer_id, **overrides),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )


def build_season_world(api: ApiClient, **season_overrides: Any) -> World:
    """Tier 3: registry plus one season whose fiscal counters start at zero."""
    world = build_registry(api)
    season = seed_season(
        api, world["agreement_id"], world["sr_id"], **season_overrides
    )
    world["season"] = season
    world["season_id"] = season["id"]
    return world


# --- Tier 4: a room open for staffing ---------------------------------------

def seed_room(
    api: ApiClient,
    season_id: str,
    showrunner_headers: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    """Configure a writers room on the season."""
    return get_success_data(
        api.create_room(season_id, F.build_room(**overrides), showrunner_headers)
    )


def open_room(api: ApiClient, room_id: str, showrunner_headers: Dict[str, str]) -> Dict[str, Any]:
    """Move a room OPEN -> STAFFING."""
    return get_success_data(api.open_staffing(room_id, showrunner_headers))


def build_staffing_room_world(
    api: ApiClient,
    room_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 4: a season with one room already accepting seat offers."""
    world = build_season_world(api, **(season_overrides or {}))
    room = seed_room(
        api, world["season_id"], world["sr_headers"], **(room_overrides or {})
    )
    world["room"] = room
    world["room_id"] = room["id"]
    world["room"] = open_room(api, room["id"], world["sr_headers"])
    world["room_version"] = world["room"]["version"]
    return world


# --- Tier 5: confirmed seats and an active room ------------------------------

def current_room_version(api: ApiClient, room_id: str) -> int:
    """Read the room's live version, for the next optimistic-concurrency token."""
    room = get_success_data(api.get_room(room_id, STUDIO_EXECUTIVE_HEADERS))
    return room["version"]


def seed_seat(
    api: ApiClient,
    room_id: str,
    writer_id: str,
    showrunner_headers: Dict[str, str],
    expected_room_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Offer one seat, reading the room's live version when none is supplied."""
    if expected_room_version is None:
        expected_room_version = current_room_version(api, room_id)
    return get_success_data(
        api.offer_seat(
            room_id,
            F.build_seat_offer(writer_id, expected_room_version, **overrides),
            showrunner_headers,
        )
    )


def accept_seat(api: ApiClient, seat_id: str, writer_id: str) -> Dict[str, Any]:
    """Accept a seat offer as the seated writer."""
    return get_success_data(
        api.accept_seat(seat_id, make_writer_headers(writer_id))
    )


def activate_room(api: ApiClient, room_id: str) -> Dict[str, Any]:
    """Move a room STAFFING -> ACTIVE."""
    return get_success_data(api.activate_room(room_id, STUDIO_EXECUTIVE_HEADERS))


def build_active_room_world(
    api: ApiClient,
    room_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 5: two confirmed seats (w1 with a guarantee slot, w2 without) in an
    ACTIVE room."""
    world = build_staffing_room_world(
        api, room_overrides=room_overrides, season_overrides=season_overrides
    )
    s1 = seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=1,
    )
    world["s1"] = accept_seat(api, s1["id"], world["w1_id"])
    world["s1_id"] = s1["id"]

    s2 = seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )
    world["s2"] = accept_seat(api, s2["id"], world["w2_id"])
    world["s2_id"] = s2["id"]

    world["room"] = activate_room(api, world["room_id"])
    world["room_version"] = world["room"]["version"]
    return world


# --- Tier 6: episodes --------------------------------------------------------

def seed_episode(
    api: ApiClient, season_id: str, episode_number: int = 1, **overrides: Any
) -> Dict[str, Any]:
    """Order one episode of the season."""
    return get_success_data(
        api.create_episode(
            season_id, F.build_episode(episode_number, **overrides), STUDIO_EXECUTIVE_HEADERS
        )
    )


def current_episode_version(api: ApiClient, episode_id: str) -> int:
    """Read the episode's live version, for the next concurrency token."""
    episode = get_success_data(api.get_episode(episode_id, STUDIO_EXECUTIVE_HEADERS))
    return episode["version"]


def build_episode_world(
    api: ApiClient,
    episode_overrides: Optional[Dict[str, Any]] = None,
    room_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 6: an ACTIVE room plus episode 1 of the season."""
    world = build_active_room_world(
        api, room_overrides=room_overrides, season_overrides=season_overrides
    )
    episode = seed_episode(api, world["season_id"], 1, **(episode_overrides or {}))
    world["ep1"] = episode
    world["ep1_id"] = episode["id"]
    world["ep1_version"] = episode["version"]
    return world


# --- Tier 7: script assignments and their milestone chains -------------------

def seed_assignment(
    api: ApiClient,
    episode_id: str,
    writer_id: str,
    showrunner_headers: Dict[str, str],
    assignment_type: str = "TELEPLAY",
    expected_episode_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create one script assignment, reading the episode's live version if needed."""
    if expected_episode_version is None:
        expected_episode_version = current_episode_version(api, episode_id)
    return get_success_data(
        api.create_script_assignment(
            episode_id,
            F.build_script_assignment(
                writer_id,
                expected_episode_version,
                assignment_type=assignment_type,
                **overrides,
            ),
            showrunner_headers,
        )
    )


def milestones_of(api: ApiClient, assignment_id: str) -> List[Dict[str, Any]]:
    """Every milestone of one assignment, ordered by sequence_index ascending."""
    rows, _ = validate_paginated(
        api.list_milestones(
            STUDIO_EXECUTIVE_HEADERS, {"assignment_id": assignment_id, "limit": 100}
        )
    )
    return rows


def deliver_milestone(api: ApiClient, milestone_id: str, writer_id: str) -> Dict[str, Any]:
    """Deliver one milestone as the assigned writer."""
    return get_success_data(
        api.deliver_milestone(milestone_id, make_writer_headers(writer_id))
    )


def deliver_all(api: ApiClient, assignment_id: str, writer_id: str) -> List[Dict[str, Any]]:
    """Deliver every milestone of the assignment in sequence order."""
    delivered = []
    for milestone in milestones_of(api, assignment_id):
        delivered.append(deliver_milestone(api, milestone["id"], writer_id))
    return delivered


def approve_assignment(
    api: ApiClient, assignment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Approve a delivered assignment; the studio approves by default."""
    return get_success_data(
        api.approve_assignment(assignment_id, headers or STUDIO_EXECUTIVE_HEADERS)
    )


def build_assignment_world(
    api: ApiClient,
    assignment_type: str = "TELEPLAY",
    episode_overrides: Optional[Dict[str, Any]] = None,
    room_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 7: episode 1 carries one assignment for w1 with its milestone chain."""
    world = build_episode_world(
        api,
        episode_overrides=episode_overrides,
        room_overrides=room_overrides,
        season_overrides=season_overrides,
    )
    assignment = seed_assignment(
        api,
        world["ep1_id"],
        world["w1_id"],
        world["sr_headers"],
        assignment_type=assignment_type,
        expected_episode_version=world["ep1_version"],
    )
    world["a1"] = assignment
    world["a1_id"] = assignment["id"]
    world["a1_milestones"] = milestones_of(api, assignment["id"])
    world["a1_milestone_ids"] = [m["id"] for m in world["a1_milestones"]]
    return world


def build_delivered_assignment_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 8a: every milestone of a1 has landed, so a1 reads DELIVERED."""
    world = build_assignment_world(api, **kwargs)
    deliver_all(api, world["a1_id"], world["w1_id"])
    world["a1"] = get_success_data(
        api.get_script_assignment(world["a1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    world["a1_milestones"] = milestones_of(api, world["a1_id"])
    world["a1_milestone_ids"] = [m["id"] for m in world["a1_milestones"]]
    return world


def build_approved_assignment_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 8b: a1 approved by the studio, so the episode reads READY and the
    credit submission window is open."""
    world = build_delivered_assignment_world(api, **kwargs)
    world["a1"] = approve_assignment(api, world["a1_id"])
    world["ep1"] = get_success_data(
        api.get_episode(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    world["ep1_version"] = world["ep1"]["version"]
    world["a1_milestones"] = milestones_of(api, world["a1_id"])
    world["a1_milestone_ids"] = [m["id"] for m in world["a1_milestones"]]
    return world


# --- Tier 9: script clearance ------------------------------------------------

def seed_clearance_review(
    api: ApiClient, assignment_id: str, reviewed_draft_milestone_id: str
) -> Dict[str, Any]:
    """Open a clearance review over a delivered draft milestone."""
    return get_success_data(
        api.create_clearance_review(
            assignment_id,
            F.build_clearance_review(reviewed_draft_milestone_id),
            LEGAL_COUNSEL_HEADERS,
        )
    )


def seed_clearance_item(
    api: ApiClient,
    review_id: str,
    item_type: str = "NAME",
    descriptor: str = "Character surname Kowalczyk",
    scene_reference: str = "Act 1 / Scene 1",
) -> Dict[str, Any]:
    """Log one clearance item against a review."""
    return get_success_data(
        api.create_clearance_item(
            review_id,
            F.build_clearance_item(item_type, descriptor, scene_reference),
            LEGAL_COUNSEL_HEADERS,
        )
    )


def decide_item(
    api: ApiClient,
    item_id: str,
    decision: str = "CLEARED",
    conditional_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a legal decision on one clearance item."""
    return get_success_data(
        api.decide_clearance_item(
            item_id,
            F.build_item_decision(decision, conditional_note),
            LEGAL_COUNSEL_HEADERS,
        )
    )


def grant_waiver(api: ApiClient, review_id: str, memo: Optional[str] = None) -> Dict[str, Any]:
    """Grant the legal waiver on a review that sits at CONDITIONAL."""
    payload = F.build_waiver(memo) if memo else F.build_waiver()
    return get_success_data(
        api.grant_clearance_waiver(review_id, payload, LEGAL_COUNSEL_HEADERS)
    )


def last_draft_milestone(world: World) -> Dict[str, Any]:
    """The final milestone of the canonical TELEPLAY chain."""
    return world["a1_milestones"][-1]


def build_clearance_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 9a: an approved teleplay with an open clearance review over its last
    delivered draft."""
    world = build_approved_assignment_world(api, **kwargs)
    review = seed_clearance_review(
        api, world["a1_id"], last_draft_milestone(world)["id"]
    )
    world["review"] = review
    world["review_id"] = review["id"]
    return world


def build_cleared_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 9b: the review carries one item, decided CLEARED, so both the review
    and the episode read CLEARED."""
    world = build_clearance_world(api, **kwargs)
    item = seed_clearance_item(api, world["review_id"], "NAME")
    world["item1"] = item
    world["item1_id"] = item["id"]
    world["item1"] = decide_item(api, item["id"], "CLEARED")
    world["review"] = get_success_data(
        api.get_clearance_review(world["review_id"], LEGAL_COUNSEL_HEADERS)
    )
    world["ep1"] = get_success_data(
        api.get_episode(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    world["ep1_version"] = world["ep1"]["version"]
    return world


# --- Tier 10: the locked episode --------------------------------------------

def lock_episode(
    api: ApiClient, episode_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Lock an episode for production; the studio locks by default."""
    return get_success_data(
        api.lock_episode_for_production(
            episode_id, headers or STUDIO_EXECUTIVE_HEADERS
        )
    )


def build_locked_episode_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 10: episode 1 cleared and locked for production."""
    world = build_cleared_world(api, **kwargs)
    world["ep1"] = lock_episode(api, world["ep1_id"])
    world["ep1_version"] = world["ep1"]["version"]
    world["season"] = get_success_data(
        api.get_season(world["season_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    return world


# --- Tier 11: credit determination ------------------------------------------

def seed_second_assignment(api: ApiClient, world: World) -> World:
    """Give w2 an approved STORY assignment on episode 1, so both writers are
    eligible for credit."""
    a2 = seed_assignment(
        api,
        world["ep1_id"],
        world["w2_id"],
        world["sr_headers"],
        assignment_type="STORY",
    )
    world["a2"] = a2
    world["a2_id"] = a2["id"]
    world["a2_milestones"] = milestones_of(api, a2["id"])
    world["a2_milestone_ids"] = [m["id"] for m in world["a2_milestones"]]
    deliver_all(api, a2["id"], world["w2_id"])
    world["a2"] = approve_assignment(api, a2["id"])
    world["ep1"] = get_success_data(
        api.get_episode(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    world["ep1_version"] = world["ep1"]["version"]
    return world


def seed_credit_submission(
    api: ApiClient,
    episode_id: str,
    writer_id: str,
    claim_basis: str = "WRITTEN_BY",
    claimed_contribution_pct: int = 60,
) -> Dict[str, Any]:
    """File one credit claim as the claiming writer."""
    return get_success_data(
        api.create_credit_submission(
            episode_id,
            F.build_credit_submission(writer_id, claim_basis, claimed_contribution_pct),
            make_writer_headers(writer_id),
        )
    )


def build_submissions_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 11a: two approved assignments and two open credit claims (60 / 30)."""
    world = build_approved_assignment_world(api, **kwargs)
    seed_second_assignment(api, world)
    sb1 = seed_credit_submission(api, world["ep1_id"], world["w1_id"], "WRITTEN_BY", 60)
    sb2 = seed_credit_submission(api, world["ep1_id"], world["w2_id"], "STORY_BY", 30)
    world["sb1"] = sb1
    world["sb1_id"] = sb1["id"]
    world["sb2"] = sb2
    world["sb2_id"] = sb2["id"]
    return world


def close_submissions(
    api: ApiClient, episode_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Close the credit submission window, which normalises the provisional split."""
    return get_success_data(
        api.close_credit_submissions(
            episode_id, headers or GUILD_ADMINISTRATOR_HEADERS
        )
    )


def build_closed_credit_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 11b: the submission window is closed and the provisional split is
    written (67 / 33 from claims of 60 and 30)."""
    world = build_submissions_world(api, **kwargs)
    world["ep1"] = close_submissions(api, world["ep1_id"])
    world["ep1_version"] = world["ep1"]["version"]
    world["sb1"] = get_success_data(
        api.get_credit_submission(world["sb1_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    world["sb2"] = get_success_data(
        api.get_credit_submission(world["sb2_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    return world


def convene_panel(api: ApiClient, world: World) -> World:
    """Convene the three-arbiter panel on episode 1."""
    arbitration = get_success_data(
        api.convene_credit_arbitration(
            world["ep1_id"],
            F.build_arbitration(world["ar1_id"], world["ar2_id"], world["ar3_id"]),
            GUILD_ADMINISTRATOR_HEADERS,
        )
    )
    world["arbitration"] = arbitration
    world["arbitration_id"] = arbitration["id"]
    return world


def build_arbitration_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 11c: a convened panel awaiting ballots."""
    world = build_closed_credit_world(api, **kwargs)
    return convene_panel(api, world)


def cast_ballot(
    api: ApiClient,
    arbitration_id: str,
    arbiter_writer_id: str,
    vote_shares: Dict[str, int],
) -> Dict[str, Any]:
    """Cast one panel ballot as the named arbiter."""
    return get_success_data(
        api.cast_arbitration_vote(
            arbitration_id,
            F.build_ballot(vote_shares),
            make_writer_headers(arbiter_writer_id),
        )
    )


def concurring_ballots(world: World) -> List[Dict[str, int]]:
    """Three ballots whose leading-writer spread stays inside the band."""
    w1, w2 = world["w1_id"], world["w2_id"]
    return [
        {w1: 50, w2: 50},
        {w1: 40, w2: 60},
        {w1: 45, w2: 55},
    ]


def deadlocking_ballots(world: World) -> List[Dict[str, int]]:
    """Three ballots whose leading-writer spread breaks the band."""
    w1, w2 = world["w1_id"], world["w2_id"]
    return [
        {w1: 90, w2: 10},
        {w1: 10, w2: 90},
        {w1: 50, w2: 50},
    ]


def cast_full_panel(
    api: ApiClient, world: World, ballots: List[Dict[str, int]]
) -> World:
    """Cast all three ballots, one per seated arbiter, in panel order."""
    for arbiter_key, ballot in zip(("ar1_id", "ar2_id", "ar3_id"), ballots):
        world["arbitration"] = cast_ballot(
            api, world["arbitration_id"], world[arbiter_key], ballot
        )
    return world


def build_voted_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 11d: all three concurring ballots cast, determination pending."""
    world = build_arbitration_world(api, **kwargs)
    return cast_full_panel(api, world, concurring_ballots(world))


def build_deadlocked_world(api: ApiClient, **kwargs: Any) -> World:
    """Tier 11e: all three ballots cast and the panel already declared
    DEADLOCKED, so only the policy override remains."""
    world = build_arbitration_world(api, **kwargs)
    cast_full_panel(api, world, deadlocking_ballots(world))
    world["arbitration"] = get_success_data(
        api.determine_arbitration(world["arbitration_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    return world


# --- Cross-cutting helpers ---------------------------------------------------

def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Move the logical clock; this mutates no entity by itself."""
    get_success_data(api.set_clock(to_iso8601, STUDIO_EXECUTIVE_HEADERS))


def ledger_for_season(api: ApiClient, season_id: str) -> List[Dict[str, Any]]:
    """Every fee ledger row of one season, oldest first."""
    rows, _ = validate_paginated(
        api.list_fee_ledger_entries(
            STUDIO_EXECUTIVE_HEADERS, {"season_id": season_id, "limit": 100}
        )
    )
    return rows


def ledger_for_assignment(api: ApiClient, assignment_id: str) -> List[Dict[str, Any]]:
    """Every fee ledger row attributed to one assignment."""
    rows, _ = validate_paginated(
        api.list_fee_ledger_entries(
            STUDIO_EXECUTIVE_HEADERS, {"assignment_id": assignment_id, "limit": 100}
        )
    )
    return rows


def read_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_season(season_id, STUDIO_EXECUTIVE_HEADERS))


def read_room(api: ApiClient, room_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_room(room_id, STUDIO_EXECUTIVE_HEADERS))


def read_seat(api: ApiClient, seat_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_room_seat(seat_id, STUDIO_EXECUTIVE_HEADERS))


def read_episode(api: ApiClient, episode_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_episode(episode_id, STUDIO_EXECUTIVE_HEADERS))


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_script_assignment(assignment_id, STUDIO_EXECUTIVE_HEADERS)
    )


def read_milestone(api: ApiClient, milestone_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_milestone(milestone_id, STUDIO_EXECUTIVE_HEADERS))


def read_review(api: ApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_clearance_review(review_id, LEGAL_COUNSEL_HEADERS))


def read_item(api: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_clearance_item(item_id, LEGAL_COUNSEL_HEADERS))


def read_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_availability_window(window_id, GUILD_ADMINISTRATOR_HEADERS)
    )


def read_writer(api: ApiClient, writer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_writer(writer_id, GUILD_ADMINISTRATOR_HEADERS))


def read_arbitration(api: ApiClient, arbitration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_credit_arbitration(arbitration_id, GUILD_ADMINISTRATOR_HEADERS)
    )


def read_submission(api: ApiClient, submission_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_credit_submission(submission_id, GUILD_ADMINISTRATOR_HEADERS)
    )


# --- Variant worlds ---------------------------------------------------------

def build_offered_seat_world(api: ApiClient, **kwargs: Any) -> World:
    """A STAFFING room holding one seat still at OFFERED, for the withdraw and
    decline pathways."""
    world = build_staffing_room_world(api, **kwargs)
    seat = seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=1,
    )
    world["s1"] = seat
    world["s1_id"] = seat["id"]
    world["room"] = read_room(api, world["room_id"])
    world["room_version"] = world["room"]["version"]
    return world


def build_wrapped_room_world(api: ApiClient, **kwargs: Any) -> World:
    """An assignment held through a confirmed seat, then the room wrapped."""
    world = build_assignment_world(api, **kwargs)
    world["room"] = get_success_data(
        api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    world["room_version"] = world["room"]["version"]
    return world


def build_second_agreement(api: ApiClient) -> Dict[str, Any]:
    """A later, richer rate card, for checking that a season reads the agreement
    it names rather than the newest one on file."""
    return seed_agreement(
        api,
        mba_year=2028,
        script_fee_cents_by_length={"HALF_HOUR": 3000000, "ONE_HOUR": 8000000},
        level_credit_thresholds={
            "STORY_EDITOR": 5,
            "EXEC_STORY_EDITOR": 9,
            "CO_PRODUCER": 14,
            "PRODUCER": 20,
        },
    )


# --- Pytest fixtures --------------------------------------------------------

@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared client for every test in the session."""
    return api_client


@pytest.fixture
def agreement(api: ApiClient) -> Dict[str, Any]:
    return seed_agreement(api)


@pytest.fixture
def registry(api: ApiClient) -> World:
    return build_registry(api)


@pytest.fixture
def season_world(api: ApiClient) -> World:
    return build_season_world(api)


@pytest.fixture
def staffing_room_world(api: ApiClient) -> World:
    return build_staffing_room_world(api)


@pytest.fixture
def offered_seat_world(api: ApiClient) -> World:
    return build_offered_seat_world(api)


@pytest.fixture
def active_room_world(api: ApiClient) -> World:
    return build_active_room_world(api)


@pytest.fixture
def episode_world(api: ApiClient) -> World:
    return build_episode_world(api)


@pytest.fixture
def assignment_world(api: ApiClient) -> World:
    return build_assignment_world(api)


@pytest.fixture
def delivered_assignment_world(api: ApiClient) -> World:
    return build_delivered_assignment_world(api)


@pytest.fixture
def approved_assignment_world(api: ApiClient) -> World:
    return build_approved_assignment_world(api)


@pytest.fixture
def clearance_world(api: ApiClient) -> World:
    return build_clearance_world(api)


@pytest.fixture
def cleared_world(api: ApiClient) -> World:
    return build_cleared_world(api)


@pytest.fixture
def locked_episode_world(api: ApiClient) -> World:
    return build_locked_episode_world(api)


@pytest.fixture
def submissions_world(api: ApiClient) -> World:
    return build_submissions_world(api)


@pytest.fixture
def closed_credit_world(api: ApiClient) -> World:
    return build_closed_credit_world(api)


@pytest.fixture
def arbitration_world(api: ApiClient) -> World:
    return build_arbitration_world(api)


@pytest.fixture
def voted_world(api: ApiClient) -> World:
    return build_voted_world(api)


@pytest.fixture
def deadlocked_world(api: ApiClient) -> World:
    return build_deadlocked_world(api)


@pytest.fixture
def wrapped_room_world(api: ApiClient) -> World:
    return build_wrapped_room_world(api)
