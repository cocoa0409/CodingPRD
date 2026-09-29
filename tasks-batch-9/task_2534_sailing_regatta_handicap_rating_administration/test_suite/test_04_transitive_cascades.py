"""Multi-hop cascades in which every hop is caused by the hop before it: a
measurer's suspension travelling certificate to entry to division to race, and a
jury chair's recusal travelling seat to panel to scheduled hearing.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    build_accepted_fleet_world,
    create_protest_payload,
    evidence_payload,
    read_boat,
    read_certificate,
    read_division,
    read_entry,
    read_protest,
    read_race,
    read_regatta,
    read_standing,
    recuse_payload,
    record_result,
    schedule_hearing_payload,
    set_clock,
    suspend_certificate_payload,
)

RACE_START = "2026-08-05T14:00:00Z"
TWO_RATED_ENTRANTS = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
)


def _suspension_world():
    """A confirmed two-boat division whose floor is exactly two, with one PENDING
    race that was created while every division still met that floor."""
    return build_accepted_fleet_world(
        entrants=TWO_RATED_ENTRANTS,
        races=({"race_number": 1, "scheduled_start_utc": RACE_START},),
    )


def test_certificate_suspension_cascades_through_entry_division_and_counters(api):
    """PRD 3.2: "Hop two moves every entry that pinned this certificate and whose
    `registration_status` is `ACCEPTED` to `RATING_INVALID`; an entry still in
    `SUBMITTED` is untouched, because no edge leads from `SUBMITTED` into
    `RATING_INVALID`. Hop three has every division holding one of those entries
    re-derive `assigned_entry_count` and `accepted_entry_count`, and any division
    in status `CONFIRMED` whose refreshed `assigned_entry_count` has fallen below
    its effective floor reverts `CONFIRMED → PROVISIONAL`."

    PRD 3.2 also fixes the floor the refreshed count is measured against: "A
    division's effective floor is the greater of its own `min_entries` and the
    regatta's `fleet_minimum`, a rule that recurs throughout this document."

    Design: Difficulty/transitive_cascade/certificate_suspension_cascades_entry_division_and_race_block
    """
    world = _suspension_world()
    division_id = world["divisions"]["A"]["id"]
    before = read_division(division_id)
    assert (before["status"], before["assigned_entry_count"], before["accepted_entry_count"]) == (
        "CONFIRMED", 2, 2,
    )
    assert read_boat(world["boats"]["A"]["id"])["version"] == 3, (
        "registration, the certificate filing and the issue make three"
    )

    suspended = validate_success(
        api.suspend_certificate(
            world["certificates"]["A"]["id"],
            suspend_certificate_payload(),
            world["h"]["measurer"],
        )
    )

    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason_code"] == "MEASUREMENT_IRREGULARITY"

    invalidated = read_entry(world["entries"]["A"]["id"])
    assert invalidated["registration_status"] == "RATING_INVALID"
    assert invalidated["certificate_id"] == world["certificates"]["A"]["id"], (
        "the entry stays pinned to the certificate that was suspended"
    )

    after = read_division(division_id)
    assert after["assigned_entry_count"] == 1
    assert after["accepted_entry_count"] == 1
    assert after["status"] == "PROVISIONAL", (
        "one assigned entry is under the effective floor of two"
    )
    assert read_regatta(world["regatta_id"])["confirmed_division_count"] == 0

    control = read_entry(world["entries"]["B"]["id"])
    assert control["registration_status"] == "ACCEPTED", (
        "the cascade followed the certificate pin, not division membership"
    )
    assert control["inspection_status"] == "PASSED"
    assert read_certificate(world["certificates"]["B"]["id"])["status"] == "ISSUED"
    assert read_boat(world["boats"]["A"]["id"])["version"] == 4


def test_the_suspension_cascade_reaches_the_pending_race_start_block(api):
    """PRD 3.2: "Hop four sets `start_blocked_reason` to `DIVISION_UNDER_MINIMUM`
    on every race of that regatta whose `start_status` is still `PENDING`."

    PRD 3.7 fixes the pre-cascade value of the same field: "`start_blocked_reason`
    is set to `DIVISION_UNDER_MINIMUM` right away if some division of the regatta
    that already holds at least one assigned entry is still short of the greater
    of its `min_entries` and the regatta's `fleet_minimum`. Otherwise
    `start_blocked_reason` is null. That field is the only value it ever takes."

    Design: Difficulty/transitive_cascade/certificate_suspension_cascades_entry_division_and_race_block
    """
    world = _suspension_world()
    race_id = world["races"][1]["id"]
    assert read_race(race_id)["start_blocked_reason"] is None, (
        "no division was under its floor when the race was created"
    )

    validate_success(
        api.suspend_certificate(
            world["certificates"]["A"]["id"],
            suspend_certificate_payload(suspension_reason_code="SAIL_AREA_RECHECK"),
            world["h"]["measurer"],
        )
    )

    blocked = read_race(race_id)
    assert blocked["start_blocked_reason"] == "DIVISION_UNDER_MINIMUM"
    assert blocked["start_status"] == "PENDING", "the block does not move the start status"
    assert blocked["scoring_status"] == "NOT_SCORED"
    assert (
        read_certificate(world["certificates"]["A"]["id"])["suspension_reason_code"]
        == "SAIL_AREA_RECHECK"
    )


def _scheduled_hearing_world(api):
    """A started race whose results are recorded but not scored, with a two-judge
    SEATED panel and one protest already scheduled for a hearing."""
    world = build_accepted_fleet_world(
        entrants=TWO_RATED_ENTRANTS,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": RACE_START},),
        start_races=(1,),
    )
    set_clock("2026-08-05T18:00:00Z")
    pro_id = world["ids"]["pro"]
    race_id = world["races"][1]["id"]
    for key, elapsed in (("A", 5027.8), ("B", 5312.8)):
        record_result(race_id, world["entries"][key]["id"], pro_id, elapsed_seconds=elapsed)

    protest = validate_success(
        api.create_protest(
            create_protest_payload(
                race_id,
                world["entries"]["B"]["id"],
                world["entries"]["A"]["id"],
                "2026-08-05T14:20:00Z",
            ),
            world["h"]["helm_2"],
        ),
        expected_status=201,
    )
    validate_success(
        api.file_evidence(
            protest["id"],
            evidence_payload(world["entries"]["B"]["id"]),
            world["h"]["helm_2"],
        )
    )
    world["protest"] = validate_success(
        api.schedule_hearing(
            protest["id"],
            schedule_hearing_payload(world["panel"]["id"], "2026-08-05T19:00:00Z"),
            world["h"]["jury"],
        )
    )
    return world


def test_recusal_cascades_from_the_seat_through_the_panel_to_the_scheduled_hearing(api):
    """PRD 3.10: "Naming a seated `member_id`, hop one marks that `seats`
    element's `recused` flag true and decrements `seated_member_count`. Hop two,
    caused by the first, moves the panel `SEATED → FORMING` when the refreshed
    count has fallen below the regatta's `jury_quorum_required`. Hop three, caused
    by the second, reverts every protest bound to this panel whose status is
    `HEARING_SCHEDULED` back to `FILED`, clearing that protest's `jury_panel_id`
    and `hearing_utc` to null."

    Design: Difficulty/transitive_cascade/jury_recusal_cascades_panel_and_scheduled_protest
    """
    world = _scheduled_hearing_world(api)
    panel_id = world["panel"]["id"]
    chair_id = world["ids"]["judge_chair"]
    judge_id = world["ids"]["judge_member"]
    assert world["panel"]["status"] == "SEATED"
    assert world["panel"]["seated_member_count"] == 2
    assert world["protest"]["status"] == "HEARING_SCHEDULED"
    assert world["protest"]["hearing_utc"] == "2026-08-05T19:00:00Z"

    recused = validate_success(
        api.recuse_judge(panel_id, recuse_payload(judge_id), world["h"]["jury"])
    )

    assert recused["seated_member_count"] == 1
    seats = {seat["member_id"]: seat for seat in recused["seats"]}
    assert seats[judge_id]["recused"] is True
    assert seats[chair_id]["recused"] is False, "the chair's own seat is untouched"
    assert seats[chair_id]["seat_role"] == "CHAIR"
    assert recused["status"] == "FORMING", "one non-recused seat is under the quorum of two"
    assert recused["version"] == 3, "one increment for the seating and one for the recusal"

    protest = read_protest(world["protest"]["id"])
    assert protest["status"] == "FILED"
    assert protest["jury_panel_id"] is None
    assert protest["hearing_utc"] is None, (
        "the protest must be scheduled from scratch, not merely re-heard"
    )


def test_the_recusal_cascade_stops_at_the_panel_and_never_touches_the_scoring_chain(api):
    """PRD 3.10: "Hop three, caused by the second, reverts every protest bound to
    this panel whose status is `HEARING_SCHEDULED` back to `FILED`, clearing that
    protest's `jury_panel_id` and `hearing_utc` to null. The panel's `version`
    advances."

    Nothing further is described as following, and the two chains that could have
    been dragged along are ruled out by their own preconditions: a re-score is
    caused only by a decision, since PRD 2.9 fixes `rescore_count` as "the number
    of times a jury outcome has forced the race to be scored again", and a series
    total is only fed by races that reached `FINAL`.

    Design: Difficulty/transitive_cascade/jury_recusal_cascades_panel_and_scheduled_protest
    """
    world = _scheduled_hearing_world(api)
    validate_success(
        api.recuse_judge(
            world["panel"]["id"],
            recuse_payload(world["ids"]["judge_member"]),
            world["h"]["jury"],
        )
    )

    race = read_race(world["races"][1]["id"])
    assert race["rescore_count"] == 0
    assert race["scoring_status"] == "PROVISIONAL", "the race was never scored"
    assert race["points_pool_total"] == 0
    assert read_standing(world["entries"]["A"]["id"])["gross_points"] == 0.0
    assert read_standing(world["entries"]["B"]["id"])["gross_points"] == 0.0

    protest = read_protest(world["protest"]["id"])
    assert protest["evidence_count"] == 1, "the recusal cost the schedule, not the evidence"
    assert protest["reopen_count"] == 0
    assert protest["decision"] == "NONE"

    assert read_regatta(world["regatta_id"])["status"] == "RACING"
    assert read_division(world["divisions"]["A"]["id"])["status"] == "CONFIRMED"
