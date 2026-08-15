"""Music placement spin compliance: separation order, spin cap, retired
songs and categories (PRD §3.1, §3.5)."""
from test_helpers import (
    PD,
    TD,
    ApiErrorId,
    api_client,
    create_active_clock,
    create_locked_log,
    create_music_category_payload,
    create_song_payload,
    create_station,
    get_success_data,
    validate_error,
    validate_success,
)


def _setup_music_env(song_sep=0, artist_sep=0, cap=5, songs=1):
    """Station + ACTIVE MON clock (no slots needed for music) + category +
    song(s) + LOCKED log 2026-05-04."""
    station = create_station()
    create_active_clock(station["id"], applies_weekdays=["MON"], slots=[])
    category = get_success_data(
        api_client.create_music_category(
            create_music_category_payload(
                station["id"],
                min_song_separation_min=song_sep,
                min_artist_separation_min=artist_sep,
                max_spins_per_day=cap,
            ),
            PD,
        )
    )
    song_ids = []
    for i in range(songs):
        song = get_success_data(
            api_client.create_song(
                create_song_payload(station["id"], category["id"], title=f"Song{i+1}"),
                PD,
            )
        )
        song_ids.append(song["id"])
    log = create_locked_log(station["id"], log_date="2026-05-04")
    return {"station": station, "category": category, "songs": song_ids, "log": log}


def test_song_separation_temporal_beats_spin_cap_error(api):
    """PRD §3.5: "Spin compliance is checked in a fixed order — song separation
    first, then artist separation, then the daily spin cap." and "if any
    existing placement of the same song is closer than the category's
    `min_song_separation_min`, the placement is rejected with
    `ERR_SPIN_SEPARATION_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/song_separation_temporal_beats_spin_cap_constraint
    """
    env = _setup_music_env(song_sep=180, artist_sep=240, cap=1)
    s1 = env["songs"][0]
    log_id = env["log"]["id"]
    get_success_data(api_client.place_music(log_id, {"song_id": s1, "hour": 8}, TD))

    resp = api_client.place_music(log_id, {"song_id": s1, "hour": 9}, TD)
    err = validate_error(resp, ApiErrorId.ERR_SPIN_SEPARATION_VIOLATION)
    assert resp.status_code == 422
    assert err["error_id"] != ApiErrorId.ERR_CATEGORY_SPIN_CAP_EXCEEDED, (
        "temporal tier (song separation) beats the quota tier even though a 2nd "
        "spin also breaks max_spins_per_day == 1"
    )


def test_song_separation_rejection_appends_nothing(api):
    """PRD §3.5: "Each placement carries `song_id` and `hour` and is appended
    to the log's `music_placements` array with the next `placed_seq`" — a
    rejected placement is never appended.

    Design: Difficulty/priority_pair_validation_conflict/song_separation_temporal_beats_spin_cap_constraint
    """
    env = _setup_music_env(song_sep=180, artist_sep=240, cap=1)
    s1 = env["songs"][0]
    log_id = env["log"]["id"]
    placed = get_success_data(api_client.place_music(log_id, {"song_id": s1, "hour": 8}, TD))
    assert len(placed["music_placements"]) == 1

    validate_error(
        api_client.place_music(log_id, {"song_id": s1, "hour": 9}, TD),
        ApiErrorId.ERR_SPIN_SEPARATION_VIOLATION,
    )

    log = get_success_data(api_client.get_log(log_id, TD))
    assert len(log["music_placements"]) == 1, "failed placement not appended"


def test_spin_cap_pure_violation_when_separation_zero(api):
    """PRD §3.5: "Finally, the spin cap rejects with
    `ERR_CATEGORY_SPIN_CAP_EXCEEDED` when the count of existing placements of
    the same song on this log, plus the candidate, would exceed
    `max_spins_per_day`."

    Design: Corner/validations/spin_cap_pure_violation_when_separation_zero
    """
    env = _setup_music_env(song_sep=0, artist_sep=0, cap=1)
    s1 = env["songs"][0]
    log_id = env["log"]["id"]
    get_success_data(api_client.place_music(log_id, {"song_id": s1, "hour": 8}, TD))

    resp = api_client.place_music(log_id, {"song_id": s1, "hour": 12}, TD)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_SPIN_CAP_EXCEEDED)


def test_artist_separation_pure_violation(api):
    """PRD §3.5: "Artist separation applies the same comparison to every
    existing placement of any song sharing the candidate's exact `artist`
    string against `min_artist_separation_min`, rejecting with
    `ERR_ARTIST_SEPARATION_VIOLATION`."

    Design: Corner/validations/artist_separation_pure_violation
    """
    env = _setup_music_env(song_sep=0, artist_sep=240, cap=5, songs=2)
    s1, s2 = env["songs"]
    log_id = env["log"]["id"]
    get_success_data(api_client.place_music(log_id, {"song_id": s1, "hour": 8}, TD))

    # Different song, same artist (factory default "ArtA"): 120 < 240 minutes.
    resp = api_client.place_music(log_id, {"song_id": s2, "hour": 10}, TD)
    validate_error(resp, ApiErrorId.ERR_ARTIST_SEPARATION_VIOLATION)


def test_song_retired_blocks_placement(api):
    """PRD §3.5: "Placements referencing a retired song are blocked earlier by
    `ERR_SONG_NOT_ACTIVE`". PRD §3.1: "retiring a song leaves existing
    `music_placements` intact on their logs while blocking new placements with
    `ERR_SONG_NOT_ACTIVE`."

    Design: Corner/errors/song_retired_blocks_placement
    """
    env = _setup_music_env()
    s1 = env["songs"][0]
    get_success_data(api_client.retire_song(s1, PD))

    resp = api_client.place_music(env["log"]["id"], {"song_id": s1, "hour": 8}, TD)
    validate_error(resp, ApiErrorId.ERR_SONG_NOT_ACTIVE)


def test_category_retired_blocks_placement(api):
    """PRD §3.1: "Retiring a category deliberately leaves its songs in place —
    the separation-rule engine rejects new placements with
    `ERR_CATEGORY_RETIRED` instead".

    Design: Corner/errors/category_retired_blocks_placement
    """
    env = _setup_music_env()
    s1 = env["songs"][0]
    get_success_data(api_client.retire_music_category(env["category"]["id"], PD))

    resp = api_client.place_music(env["log"]["id"], {"song_id": s1, "hour": 8}, TD)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_RETIRED)

    song = get_success_data(api_client.get_song(s1, PD))
    assert song["status"] == "ACTIVE", "no cascade onto songs"
