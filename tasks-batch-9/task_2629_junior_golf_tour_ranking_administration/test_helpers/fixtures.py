"""Composite state builders.

Every builder starts from an empty database and drives the documented endpoints in
order, so a test can ask for the exact stage of the tour it needs — a scheduled
tournament, a set field, a peer-verified round, a completed event — without
restating the whole preamble.
"""

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .test_users import (
    CHIEF_REFEREE,
    COACH,
    CONDUCT_COMMITTEE,
    RULES_OFFICIAL,
    TOUR_ADMIN,
    member_headers,
)
from .types import (
    AID_DECISION_APPROVED,
    COACH_DECISION_GRANTED,
    CONDUCT_DECISION_SANCTIONED,
    DECISION_VERIFIED,
    INCIDENT_PHYSICAL_ALTERCATION,
    PEER_VERIFY,
    SCOPE_RESULTS_ONLY,
)

# Named instants on the logical tour clock.
CLOCK_BEFORE_ENTRY_OPEN = "2026-08-02T00:00:00Z"
CLOCK_ENTRY_WINDOW = "2026-08-10T00:00:00Z"
CLOCK_AFTER_ENTRY_CLOSE = "2026-09-01T00:00:00Z"
CLOCK_BEFORE_WITHDRAWAL_DEADLINE = "2026-09-03T00:00:00Z"
CLOCK_AFTER_WITHDRAWAL_DEADLINE = "2026-09-06T00:00:00Z"
CLOCK_ROUND_ONE = "2026-09-10T12:00:00Z"
CLOCK_ROUND_TWO = "2026-09-11T12:00:00Z"

TEE_TIME_ROUND_ONE = "2026-09-10T13:00:00Z"
TEE_TIME_ROUND_TWO = "2026-09-11T13:00:00Z"


# ------------------------------------------------------------ tier 1: atoms
def set_clock(api, when):
    """Move the logical tour clock and return the reported instants."""
    return validate_success(api.set_clock(when), 200)


def create_season(api, **overrides):
    return validate_success(
        api.create_season(f.season_payload(**overrides), TOUR_ADMIN), 201
    )


def register_member(api, season_id, builder=f.member_payload, **overrides):
    return validate_success(
        api.register_member(builder(season_id, **overrides), TOUR_ADMIN), 201
    )


def verify_member(api, member_id):
    return validate_success(
        api.verify_eligibility(
            member_id, f.eligibility_payload(DECISION_VERIFIED), TOUR_ADMIN
        ),
        200,
    )


def read_member(api, member_id):
    return validate_success(api.get_member(member_id, TOUR_ADMIN), 200)


def member_version(api, member_id):
    return read_member(api, member_id)["version"]


def read_tournament(api, tournament_id):
    return validate_success(api.get_tournament(tournament_id, TOUR_ADMIN), 200)


def read_entry(api, entry_id):
    return validate_success(api.get_entry(entry_id, TOUR_ADMIN), 200)


def read_round(api, round_id):
    return validate_success(api.get_round(round_id, TOUR_ADMIN), 200)


def read_season(api, season_id):
    return validate_success(api.get_season(season_id, TOUR_ADMIN), 200)


def create_tournament(api, season_id, builder=f.tournament_payload, **overrides):
    return validate_success(
        api.create_tournament(builder(season_id, **overrides), TOUR_ADMIN), 201
    )


# ------------------------------------------- tier 2: a season with juniors on it
_MEMBER_BUILDERS = (
    f.member_payload,
    f.second_member_payload,
    f.third_member_payload,
    f.fourth_member_payload,
)


def verified_roster(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                    member_overrides=None):
    """Open a season and register `member_count` juniors, all verified.

    Returns a context dict with the season, the member rows and their ids.
    """
    if clock is not None:
        set_clock(api, clock)
    season = create_season(api)
    overrides = member_overrides or {}
    members = []
    for index in range(member_count):
        builder = _MEMBER_BUILDERS[index]
        members.append(
            register_member(api, season["id"], builder, **overrides.get(index, {}))
        )
    for member in members:
        verify_member(api, member["id"])
    return {
        "season": season,
        "season_id": season["id"],
        "members": members,
        "member_ids": [m["id"] for m in members],
    }


def scheduled_tournament(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                         member_overrides=None, **tournament_overrides):
    """A verified roster plus a tournament still in its SCHEDULED state."""
    ctx = verified_roster(api, member_count, clock, member_overrides)
    ctx["tournament"] = create_tournament(
        api, ctx["season_id"], **tournament_overrides
    )
    ctx["tournament_id"] = ctx["tournament"]["id"]
    return ctx


def entry_open_tournament(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                          member_overrides=None, **tournament_overrides):
    """A tournament whose entry window has been opened."""
    ctx = scheduled_tournament(api, member_count, clock, member_overrides,
                               **tournament_overrides)
    ctx["tournament"] = validate_success(
        api.open_entries(ctx["tournament_id"], TOUR_ADMIN), 200
    )
    return ctx


def submit_entry(api, member_id, tournament_id, **overrides):
    return validate_success(
        api.submit_entry(
            f.entry_payload(member_id, tournament_id, **overrides),
            member_headers(member_id),
        ),
        201,
    )


def applied_field(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                  member_overrides=None, **tournament_overrides):
    """Every junior on the roster has submitted an entry, all still APPLIED."""
    ctx = entry_open_tournament(api, member_count, clock, member_overrides,
                                **tournament_overrides)
    ctx["entries"] = [
        submit_entry(api, member_id, ctx["tournament_id"])
        for member_id in ctx["member_ids"]
    ]
    ctx["entry_ids"] = [e["id"] for e in ctx["entries"]]
    return ctx


# --------------------------------------- tier 3: a field that has been selected
def field_set(api, member_count=2, clock=CLOCK_ENTRY_WINDOW, member_overrides=None,
              close_clock=CLOCK_AFTER_ENTRY_CLOSE, **tournament_overrides):
    """Entries closed and the selector run, so slots and the waitlist are settled."""
    ctx = applied_field(api, member_count, clock, member_overrides,
                        **tournament_overrides)
    set_clock(api, close_clock)
    validate_success(api.close_entries(ctx["tournament_id"], TOUR_ADMIN), 200)
    ctx["tournament"] = validate_success(
        api.set_field(ctx["tournament_id"], TOUR_ADMIN), 200
    )
    ctx["entries"] = [read_entry(api, entry_id) for entry_id in ctx["entry_ids"]]
    return ctx


def pay_entry(api, member_id, entry_id, amount_cents=None):
    """Settle an entry's net fee due in full."""
    if amount_cents is None:
        amount_cents = read_entry(api, entry_id)["net_fee_due_cents"]
    return validate_success(
        api.pay_entry(entry_id, f.payment_payload(amount_cents),
                      member_headers(member_id)),
        200,
    )


def settled_field(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                  member_overrides=None, **tournament_overrides):
    """Every accepted entry has paid its net fee due."""
    ctx = field_set(api, member_count, clock, member_overrides, **tournament_overrides)
    for member_id, entry in zip(ctx["member_ids"], ctx["entries"]):
        if entry["net_fee_due_cents"] > 0 and entry["entry_status"] == "ACCEPTED":
            pay_entry(api, member_id, entry["id"])
    ctx["entries"] = [read_entry(api, entry_id) for entry_id in ctx["entry_ids"]]
    return ctx


def tournament_in_progress(api, member_count=2, clock=CLOCK_ENTRY_WINDOW,
                           member_overrides=None, start_clock=CLOCK_ROUND_ONE,
                           **tournament_overrides):
    """A paid, started tournament: the field is in play."""
    ctx = settled_field(api, member_count, clock, member_overrides,
                        **tournament_overrides)
    set_clock(api, start_clock)
    ctx["tournament"] = validate_success(
        api.start_tournament(ctx["tournament_id"], TOUR_ADMIN), 200
    )
    return ctx


# ------------------------------------------------- tier 4: rounds and scoring
def create_round(api, entry_id, marker_member_id, round_number=1,
                 tee_time=TEE_TIME_ROUND_ONE, headers=CHIEF_REFEREE, **overrides):
    return validate_success(
        api.create_round(
            f.round_payload(entry_id, round_number, tee_time, marker_member_id,
                            **overrides),
            headers,
        ),
        201,
    )


def scheduled_round(api, clock=CLOCK_ENTRY_WINDOW, member_overrides=None,
                    **tournament_overrides):
    """Two juniors in play and a round on the tee sheet for the first of them.

    The second junior is the marker, which is what the tee sheet requires.
    """
    ctx = tournament_in_progress(api, 2, clock, member_overrides,
                                 **tournament_overrides)
    ctx["round"] = create_round(
        api, ctx["entry_ids"][0], ctx["member_ids"][1], 1, TEE_TIME_ROUND_ONE
    )
    ctx["round_id"] = ctx["round"]["id"]
    return ctx


def submitted_round(api, gross_strokes=72, clock=CLOCK_ENTRY_WINDOW,
                    member_overrides=None, **tournament_overrides):
    """A round whose card has been handed in and awaits the marker."""
    ctx = scheduled_round(api, clock, member_overrides, **tournament_overrides)
    ctx["round"] = validate_success(
        api.submit_score(
            ctx["round_id"], f.score_payload(gross_strokes),
            member_headers(ctx["member_ids"][0]),
        ),
        200,
    )
    return ctx


def peer_verified_round(api, gross_strokes=72, clock=CLOCK_ENTRY_WINDOW,
                        member_overrides=None, **tournament_overrides):
    """A round the marker has attested, ready for certification."""
    ctx = submitted_round(api, gross_strokes, clock, member_overrides,
                          **tournament_overrides)
    ctx["round"] = validate_success(
        api.peer_verify(
            ctx["round_id"], f.peer_verify_payload(PEER_VERIFY),
            member_headers(ctx["member_ids"][1]),
        ),
        200,
    )
    return ctx


def certified_round(api, gross_strokes=72, clock=CLOCK_ENTRY_WINDOW,
                    member_overrides=None, **tournament_overrides):
    """A certified round carrying its scoring differential."""
    ctx = peer_verified_round(api, gross_strokes, clock, member_overrides,
                              **tournament_overrides)
    ctx["round"] = validate_success(
        api.certify_round(ctx["round_id"], RULES_OFFICIAL), 200
    )
    return ctx


def build_tee_sheet(api, ctx, round_number, tee_time, pairs=((0, 1), (1, 0))):
    """Put a whole day's cards on the tee sheet before any of them is played.

    PRD 3.6 requires that a round's marker "must themselves hold an `ACCEPTED`
    or `COMPETING` entry in the same tournament", and PRD 3.7 moves an entry to
    `FINISHED` as soon as its last round is certified. The tee sheet is
    therefore built in advance — as the PRD says it is — so that every marker
    still holds a playing slot at the moment its neighbour's card is created.

    Returns a dict keyed by entry index.
    """
    return {
        entry_index: create_round(
            api, ctx["entry_ids"][entry_index], ctx["member_ids"][marker_index],
            round_number, tee_time,
        )
        for entry_index, marker_index in pairs
    }


def play_round(api, ctx, entry_index, marker_index, round_number, tee_time,
               gross_strokes, certify=True, round_row=None):
    """Drive one entry's round from the tee sheet through to certification.

    Pass `round_row` to play a card that is already on the tee sheet.
    """
    entry_id = ctx["entry_ids"][entry_index]
    member_id = ctx["member_ids"][entry_index]
    marker_id = ctx["member_ids"][marker_index]
    if round_row is None:
        round_row = create_round(api, entry_id, marker_id, round_number, tee_time)
    validate_success(
        api.submit_score(round_row["id"], f.score_payload(gross_strokes),
                         member_headers(member_id)),
        200,
    )
    validate_success(
        api.peer_verify(round_row["id"], f.peer_verify_payload(PEER_VERIFY),
                        member_headers(marker_id)),
        200,
    )
    if certify:
        round_row = validate_success(api.certify_round(round_row["id"], RULES_OFFICIAL), 200)
    return round_row


def completed_event(api, first_scores=(66, 72), second_scores=(74, 76),
                    clock=CLOCK_ENTRY_WINDOW, **tournament_overrides):
    """A two-junior, two-round event driven all the way to COMPLETED.

    `first_scores` are the two rounds of the first junior and `second_scores` the
    two rounds of the second, so the finish order is decided by total strokes.
    """
    ctx = tournament_in_progress(api, 2, clock, None, **tournament_overrides)
    ctx["rounds"] = []
    day_one = build_tee_sheet(api, ctx, 1, TEE_TIME_ROUND_ONE)
    ctx["rounds"].append(
        play_round(api, ctx, 0, 1, 1, TEE_TIME_ROUND_ONE, first_scores[0],
                   round_row=day_one[0])
    )
    ctx["rounds"].append(
        play_round(api, ctx, 1, 0, 1, TEE_TIME_ROUND_ONE, second_scores[0],
                   round_row=day_one[1])
    )
    set_clock(api, CLOCK_ROUND_TWO)
    day_two = build_tee_sheet(api, ctx, 2, TEE_TIME_ROUND_TWO)
    ctx["rounds"].append(
        play_round(api, ctx, 0, 1, 2, TEE_TIME_ROUND_TWO, first_scores[1],
                   round_row=day_two[0])
    )
    ctx["rounds"].append(
        play_round(api, ctx, 1, 0, 2, TEE_TIME_ROUND_TWO, second_scores[1],
                   round_row=day_two[1])
    )
    ctx["tournament"] = read_tournament(api, ctx["tournament_id"])
    ctx["entries"] = [read_entry(api, entry_id) for entry_id in ctx["entry_ids"]]
    return ctx


# --------------------------- tier 5: assistance, recruiting access, sanctions
def submit_aid_application(api, member_id, season_id, household_income_cents=1000000,
                           dependents=1, **overrides):
    version = member_version(api, member_id)
    return validate_success(
        api.submit_aid_application(
            f.aid_application_payload(
                member_id, season_id, version, household_income_cents, dependents,
                **overrides
            ),
            member_headers(member_id),
        ),
        201,
    )


def approved_aid_application(api, member_id, season_id,
                             household_income_cents=1000000, dependents=1):
    """An assistance application already approved, so an entry may draw on it."""
    application = submit_aid_application(
        api, member_id, season_id, household_income_cents, dependents
    )
    return validate_success(
        api.decide_aid_application(
            application["id"], f.aid_decision_payload(AID_DECISION_APPROVED),
            TOUR_ADMIN,
        ),
        200,
    )


def requested_coach_grant(api, member_id, headers=COACH, scope=SCOPE_RESULTS_ONLY,
                          coach_school="State University"):
    version = member_version(api, member_id)
    return validate_success(
        api.request_coach_access(
            f.coach_access_payload(member_id, version, scope, coach_school), headers
        ),
        201,
    )


def granted_coach_grant(api, member_id, headers=COACH, scope=SCOPE_RESULTS_ONLY):
    """A live recruiting access grant the junior has agreed to."""
    grant = requested_coach_grant(api, member_id, headers, scope)
    return validate_success(
        api.decide_coach_access(
            grant["id"], f.coach_decision_payload(COACH_DECISION_GRANTED),
            member_headers(member_id),
        ),
        200,
    )


def file_conduct_case(api, member_id, tournament_id, incident_code, headers=RULES_OFFICIAL,
                      **overrides):
    return validate_success(
        api.file_conduct_case(
            f.conduct_case_payload(member_id, tournament_id, incident_code, **overrides),
            headers,
        ),
        201,
    )


def sanction_conduct_case(api, case_id):
    return validate_success(
        api.decide_conduct_case(
            case_id, f.conduct_decision_payload(CONDUCT_DECISION_SANCTIONED),
            CONDUCT_COMMITTEE,
        ),
        200,
    )


def suspend_member(api, member_id, tournament_id):
    """Suspend a junior the only way the tour allows: a sanctioned conduct case.

    A physical altercation carries enough points on its own to reach the
    suspension tier.
    """
    case = file_conduct_case(
        api, member_id, tournament_id, INCIDENT_PHYSICAL_ALTERCATION,
        subject_name="Marcus Stone",
        narrative="shoved a volunteer marshal beside the 18th green",
    )
    return sanction_conduct_case(api, case["id"])


def create_exemption_grant(api, member_id, tournament_id, category, expires_at):
    return validate_success(
        api.create_exemption_grant(
            f.exemption_grant_payload(member_id, tournament_id, category, expires_at),
            TOUR_ADMIN,
        ),
        201,
    )


def run_ranking(api, season_id, as_of_date=None):
    return validate_success(
        api.run_ranking(season_id, f.ranking_run_payload(as_of_date), TOUR_ADMIN), 200
    )


def read_ranking(api, member_id, headers=TOUR_ADMIN):
    return validate_success(api.get_ranking(member_id, headers), 200)
