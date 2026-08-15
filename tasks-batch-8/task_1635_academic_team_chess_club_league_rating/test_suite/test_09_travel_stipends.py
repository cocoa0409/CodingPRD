"""Travel stipend dual-variant claims (PRD §3.9)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_season,
    create_club,
    create_coach,
    create_meet,
    create_player,
    create_waived_membership,
    finalize_season,
    get_club,
    run_meet,
    schedule_meet,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

def _stipend_scenario(api):
    """Club A (travel_tier 2) with two COMPLETED meets and one SCHEDULED meet;
    season moved to FINALIZING. travel_base_cents is 1500."""
    season = create_active_season(travel_base_cents=1500)
    club_a = create_club(season["id"], name="Alpha", school_name="Alpha HS", travel_tier=2)
    club_b = create_club(season["id"], name="Beta", school_name="Beta HS", travel_tier=1)
    club_c = create_club(season["id"], name="Gamma", school_name="Gamma HS", travel_tier=1)
    coach_a = create_coach(club_a["id"], full_name="Coach A", email="coach.a@example.com")
    coach_b = create_coach(club_b["id"], full_name="Coach B", email="coach.b@example.com")
    coach_c = create_coach(club_c["id"], full_name="Coach C", email="coach.c@example.com")
    pa = create_player(club_a["id"], full_name="PA")
    pb = create_player(club_b["id"], full_name="PB")
    pc = create_player(club_c["id"], full_name="PC")
    for player in (pa, pb, pc):
        create_waived_membership(player["id"], season["id"])

    # meet 1: A (host) vs B -> COMPLETED with a draw
    run_meet(season["id"], club_a, club_b, coach_a, coach_b,
             games=[(1, 1, pa["id"], pb["id"])], scheduled_date="2026-09-05",
             results=["DRAW"], complete=True)
    # meet 2: C (host) vs A -> COMPLETED with a draw
    run_meet(season["id"], club_c, club_a, coach_c, coach_a,
             games=[(1, 1, pc["id"], pa["id"])], scheduled_date="2026-09-12",
             results=["DRAW"], complete=True)
    # meet 3: A (host) vs B -> left SCHEDULED (counts only toward PROJECTED)
    meet3 = create_meet(season["id"], club_a["id"], club_b["id"], "2026-10-03")
    schedule_meet(meet3["id"])

    finalize_season(season["id"])
    return season, club_a

def test_projected_stipend_counts_scheduled_meets(api):
    """PRD §3.9: "The forward-looking figure, exposed on every club read as
    `projected_travel_stipend_cents`, is the club's `travel_tier` multiplied by the
    season's `travel_base_cents` multiplied by the smaller of ten and the count of the
    club's meets this season in `SCHEDULED`, `PAIRINGS_PUBLISHED`, `IN_PROGRESS`, or
    `COMPLETED`."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_travel_stipend
    """
    season, club_a = _stipend_scenario(api)
    club = get_club(club_a["id"])
    # 2 (tier) x 1500 (base) x min(3 meets in the forward-looking set, 10)
    assert club["projected_travel_stipend_cents"] == 9000, (
        f"PROJECTED counts the SCHEDULED meet too; got {club['projected_travel_stipend_cents']}"
    )

def test_actual_stipend_counts_completed_only(api):
    """PRD §3.9: "The actual stipend, posted by the `Treasurer` while the season is
    `FINALIZING` (any other season state fails with `ERR_SEASON_INVALID_STATE`), counts
    only `COMPLETED` meets: `meets_counted` is the smaller of ten and the club's
    completed-meet count, and `amount_cents` is the tier times the base times
    `meets_counted`."
    PRD §3.9: "When the computed amount is positive, a `TRAVEL_STIPEND` ledger entry
    credits it and the club's balance and standing recompute, with the row linked as
    `ledger_entry_id`".

    Design: Difficulty/dual_variant_calc/projected_vs_actual_travel_stipend
    """
    season, club_a = _stipend_scenario(api)
    stipend = validate_success(
        api.create_travel_stipend({"season_id": season["id"], "club_id": club_a["id"]},
                                  TREASURER),
        201,
    )
    assert stipend["meets_counted"] == 2, "ACTUAL counts COMPLETED meets only"
    assert stipend["amount_cents"] == 6000, "2 (tier) x 1500 x min(2, 10)"
    assert stipend.get("ledger_entry_id"), "a positive stipend posts and links its row"

    rows, meta = validate_paginated(
        api.list_ledger_entries(ADMIN, params={"club_id": club_a["id"],
                                               "entry_type": "TRAVEL_STIPEND"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 6000
    assert get_club(club_a["id"])["account_balance_cents"] == 6000

def test_duplicate_stipend_rejected(api, treasurer_headers):
    """PRD §3.9: "One stipend may exist per season-and-club pair; a second posting is
    rejected with `ERR_DUPLICATE_STIPEND`."
    PRD §3.9: "when the amount is zero, no ledger row is posted at all and
    `ledger_entry_id` stays empty."

    Design: Corner/errors/duplicate_stipend_rejected
    """
    season = create_active_season()
    club = create_club(season["id"], name="Alpha", travel_tier=1)
    finalize_season(season["id"])

    first = validate_success(
        api.create_travel_stipend({"season_id": season["id"], "club_id": club["id"]},
                                  treasurer_headers),
        201,
    )
    assert first["amount_cents"] == 0, "zero completed meets -> zero stipend"
    assert first["meets_counted"] == 0
    assert not first.get("ledger_entry_id"), "no ledger row for a zero stipend"

    res = api.create_travel_stipend({"season_id": season["id"], "club_id": club["id"]},
                                    treasurer_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_STIPEND)
