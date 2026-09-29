"""The consent-loss cascade and clock-driven consent lapse (PRD §3.3, §2.6)."""

import db
from db import store, touch
from util import iso, parse_dt, sorted_rows


def consent_loss_cascade(player, halt_reason, terminal_state):
    """Links 1-3 of the consent cascade (PRD §3.3).

    Link 1 moves the player's biometric release GRANTED -> WITHDRAWN/EXPIRED.
    Link 2, caused by link 1, masks every biometric-bearing, non-superseded tag
    of that player.  Link 3, caused by link 2, suspends every ACTIVE feed
    session on a game that just gained a masked tag whose scope includes
    BIOMETRIC.  Quotas stay untouched — nothing has been settled.
    """
    if player["biometric_release_state"] != "GRANTED":
        return 0

    player["biometric_release_state"] = terminal_state

    affected_games = set()
    for tag in sorted_rows(db.tags_of_player(player["id"])):
        if not tag["biometric_payload_present"]:
            continue
        if tag["review_status"] == "SUPERSEDED":
            continue
        if tag["biometric_masked"]:
            continue
        tag["biometric_masked"] = True
        touch(tag)
        player["masked_tag_count"] = player["masked_tag_count"] + 1
        game = store.games.get(tag["game_id"])
        if game is not None:
            game["masked_tag_count"] = game["masked_tag_count"] + 1
            touch(game)
            affected_games.add(game["id"])

    suspended = 0
    for session in sorted_rows(store.feed_sessions.values()):
        if session["status"] != "ACTIVE":
            continue
        if session["game_id"] not in affected_games:
            continue
        if "BIOMETRIC" not in session["scope"]:
            continue
        session["status"] = "SUSPENDED"
        session["halt_reason"] = halt_reason
        touch(session)
        suspended += 1
    return suspended


def expire_due_consent_records(new_clock, clock_stamp=None):
    """PRD §2.6: advancing the clock materialises lapsed consent.

    Records are processed in ascending ``expires_at_utc`` order with
    ``created_at`` ascending as the tie-break so the cascade order is
    deterministic.
    """
    due = []
    for record in store.consent_records.values():
        if record["status"] != "ACTIVE":
            continue
        expires = parse_dt(record["expires_at_utc"])
        if expires is not None and expires <= new_clock:
            due.append(record)

    due.sort(key=lambda r: (parse_dt(r["expires_at_utc"]),
                            r.get("created_at") or "",
                            r.get("_seq", 0)))

    expired_count = 0
    suspended_count = 0
    stamp = clock_stamp if clock_stamp is not None else iso(new_clock)
    for record in due:
        record["status"] = "EXPIRED"
        record["terminated_at_utc"] = stamp
        touch(record)
        expired_count += 1
        player = store.players.get(record["player_id"])
        if player is None:
            continue
        if player.get("active_consent_record_id") == record["id"]:
            player["active_consent_record_id"] = None
        suspended_count += consent_loss_cascade(player, "CONSENT_EXPIRED", "EXPIRED")
        touch(player)
    return expired_count, suspended_count
