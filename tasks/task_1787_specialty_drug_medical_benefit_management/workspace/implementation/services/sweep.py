"""Time-driven transitions (PRD 2.4): applied eagerly on clock set and lazily
before every request, so observable behavior never depends on an explicit set.

Sweep order per scaffold clock endpoint side effects:
  1. SCHEDULED ASP activation (+ repricing cascade)
  2. authorization expiry
  3. redirection offer expiry
  4. biosimilar policy expiry
"""
from datetime import timedelta

from db import db
from services.pricing import reprice_for_schedule, touch
from util import CLOCK, pdate

REDIRECTION_OFFER_DAYS = 30


def activate_schedule(schedule: dict):
    """SCHEDULED -> EFFECTIVE (or born EFFECTIVE at create): supersede every other
    EFFECTIVE schedule of the same drug, then run asp_retro_repricing."""
    schedule["status"] = "EFFECTIVE"
    touch(schedule)
    for other in db["asp_schedules"].values():
        if (
            other["drug_id"] == schedule["drug_id"]
            and other["id"] != schedule["id"]
            and other["status"] == "EFFECTIVE"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    reprice_for_schedule(schedule)


def _expire_auth(auth: dict):
    was_suspended = auth["status"] == "SUSPENDED"
    auth["status"] = "EXPIRED"
    touch(auth)
    if was_suspended:
        for c in db["claims"].values():
            if (
                c["auth_id"] == auth["id"]
                and c["status"] == "PENDED"
                and c["pend_reason"] == "AUTH_SUSPENDED"
            ):
                c["status"] = "DENIED"
                c["denial_reason"] = "AUTH_EXPIRED"
                c["pend_reason"] = None
                touch(c)


def run_sweep():
    today = CLOCK.today()

    # 1. ASP schedule activation. When several schedules of one drug are due,
    #    activate in effective_start ASC order so the latest-dated ends EFFECTIVE.
    due = [
        s
        for s in db["asp_schedules"].values()
        if s["status"] == "SCHEDULED" and pdate(s["effective_start"]) <= today
    ]
    due.sort(key=lambda s: (pdate(s["effective_start"]), s["_seq"]))
    for s in due:
        activate_schedule(s)

    # 2. Authorization expiry: current date > validity_end (closed window).
    for a in db["prior_authorizations"].values():
        if (
            a["status"] in ("APPROVED", "SUSPENDED")
            and a["validity_end"] is not None
            and today > pdate(a["validity_end"])
        ):
            _expire_auth(a)

    # 3. Redirection offer lapse: more than 30 days after creation.
    for r in db["redirections"].values():
        if r["status"] == "OFFERED":
            created_date = pdate(r["created_at"][:10])
            if today > created_date + timedelta(days=REDIRECTION_OFFER_DAYS):
                r["status"] = "EXPIRED"
                touch(r)

    # 4. Biosimilar policy expiry: current date >= effective_end.
    for p in db["biosimilar_policies"].values():
        if p["status"] == "ACTIVE" and today >= pdate(p["effective_end"]):
            p["status"] = "EXPIRED"
            touch(p)
