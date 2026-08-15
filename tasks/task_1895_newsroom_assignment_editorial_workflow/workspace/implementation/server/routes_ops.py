"""Operations checkpoint and logical clock per PRD 2.4 and 3.5."""

from .auth import require
from .blueprint import bp
from .envelope import ok_obj
from .errors import bad_request
from .store import STORE, now, touch
from .util import body, fmt_dt, parse_dt


@bp.post("/newsroom/ops/run-publication-scheduler")
def run_publication_scheduler():
    require(["NewsDirector"])
    current = now()
    published_story_ids = []
    expired_call_in_ids = []

    for s in list(STORE.stories.values()):
        if s["status"] != "SCHEDULED":
            continue
        slot = STORE.slots.get(s.get("slot_id"))
        if slot is None:
            continue
        if slot["window_start"] > current:
            continue
        if s["embargo_until"] is not None and s["embargo_until"] > current:
            continue
        s["status"] = "PUBLISHED"
        s["published_at"] = current
        touch(s)
        published_story_ids.append(s["id"])

    for ci in list(STORE.call_ins.values()):
        if ci["status"] == "PAGED" and ci["expires_at"] <= current:
            ci["status"] = "EXPIRED"
            touch(ci)
            expired_call_in_ids.append(ci["id"])

    return ok_obj({
        "published_story_ids": published_story_ids,
        "expired_call_in_ids": expired_call_in_ids,
    })


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(["NewsDirector"])
    b = body()
    dt = parse_dt(b.get("to_iso8601"))
    if dt is None:
        bad_request("to_iso8601 must be a valid ISO8601 timestamp")
    STORE.clock = dt
    return ok_obj({"current_utc": fmt_dt(dt)})
