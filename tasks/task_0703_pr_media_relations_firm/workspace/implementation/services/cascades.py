"""Cascading side effects (PRD 2.5, 3.6, 3.7).

Each resource swept by a cascade has its own status advanced, its updated_at
refreshed, and its version incremented (PRD 2.5).
"""
import db
from common import touch


def archive_campaign_cascade(campaign):
    """Depth-3 cascade on campaign archive (PRD 3.7).

    Level 1: every MediaList of the campaign with status ACTIVE or EXHAUSTED
             -> ARCHIVED.
    Level 2: each such MediaList cascades to its Pitches in
             {DRAFT, SENT, RESPONDED} -> CANCELLED.
    Level 3: each such Pitch cascades to its Interviews in
             {REQUESTED, CONFIRMED} -> CANCELLED.
    """
    for ml in db.media_lists.values():
        if ml["campaign_id"] != campaign["id"]:
            continue
        if ml["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        ml["status"] = "ARCHIVED"
        touch(ml)
        # Level 2: pitches on this media list.
        for pitch in db.pitches.values():
            if pitch["media_list_id"] != ml["id"]:
                continue
            if pitch["status"] not in ("DRAFT", "SENT", "RESPONDED"):
                continue
            pitch["status"] = "CANCELLED"
            touch(pitch)
            # Level 3: interviews anchored to this pitch.
            for itv in db.interviews.values():
                if itv.get("pitch_id") != pitch["id"]:
                    continue
                if itv["status"] not in ("REQUESTED", "CONFIRMED"):
                    continue
                itv["status"] = "CANCELLED"
                touch(itv)


def deactivate_spokesperson_cascade(spokesperson):
    """Depth-2 cascade on spokesperson deactivate (PRD 3.6).

    Level 1: every Interview for this spokesperson in {REQUESTED, CONFIRMED}
             -> CANCELLED.
    Level 2: for each such cancelled Interview carrying a pitch_id whose Pitch
             is currently ACCEPTED, revert that Pitch ACCEPTED -> RESPONDED.
    """
    for itv in db.interviews.values():
        if itv["spokesperson_id"] != spokesperson["id"]:
            continue
        if itv["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        itv["status"] = "CANCELLED"
        touch(itv)
        pitch_id = itv.get("pitch_id")
        if pitch_id:
            pitch = db.pitches.get(pitch_id)
            if pitch is not None and pitch["status"] == "ACCEPTED":
                pitch["status"] = "RESPONDED"
                touch(pitch)
