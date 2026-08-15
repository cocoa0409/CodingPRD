"""Ops-run aging sweep and the test-driving logical clock (PRD 3.10, 2.5)."""

from flask import Blueprint

import clock as clockmod
import envelope
from auth import authorized
from errors import ERR_VALIDATION, raise_error
from services import close_deposit
from store import db, touch
from validate import check_allowed_fields, get_body, req_str

bp = Blueprint("ops", __name__)


@bp.route("/aging-runs", methods=["POST"])
def aging_run():
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, [])

    now = clockmod.now()
    # Select exactly the HELD deposits whose whole-day age exceeds 90 days,
    # processed in sold_at ASC order (tie-break: created_at ASC, then the
    # insertion sequence for exact clock ties).
    victims = [
        d
        for d in db.core_deposits.values()
        if d["status"] == "HELD" and clockmod.age_in_days(d["sold_at"], now) > 90
    ]
    victims.sort(key=lambda d: (d["sold_at"], d["created_at"], d["_seq"]))

    forfeited_ids = []
    bumped = set()
    for dep in victims:
        close_deposit(dep, now)  # age > 90 -> bracket pct 0 -> FORFEITED
        forfeited_ids.append(dep["id"])
        distributor = db.distributors.get(dep["distributor_id"])
        if distributor is not None and distributor["id"] not in bumped:
            # The forfeiture cascade lowers deposits_held (derived) with no
            # credit posted; bump each affected distributor once per run.
            touch(distributor)
            bumped.add(distributor["id"])

    return envelope.ok(
        {"forfeited_count": len(forfeited_ids), "forfeited_deposit_ids": forfeited_ids}
    )


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, ["to_iso8601"])
    to_iso8601 = req_str(body, "to_iso8601")
    instant = clockmod.parse_instant(to_iso8601)
    if instant is None:
        raise_error(ERR_VALIDATION, "to_iso8601 is not a well-formed ISO 8601 timestamp")
    clockmod.clock.set(instant, to_iso8601)
    return envelope.ok({"current_utc": clockmod.clock.literal})
