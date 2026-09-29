"""DefaultNotice issuance, cure and escalation to termination (PRD 3.10)."""

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from db import clock_date
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER
from routing import route

CURED_ITEM_STATUSES = ("WORK_COMPLETE", "ACCEPTED", "REMOVED_BY_DISPUTE")


def _uncured(notice):
    """The snapshotted items that have not yet been brought into compliance."""
    remaining = []
    for item_id in notice["breached_item_ids"]:
        item = repo.find("items", item_id)
        if item is None or item["status"] not in CURED_ITEM_STATUSES:
            remaining.append(item_id)
    return remaining


@route("/pip/default-notices", ["POST"], (BRAND_MANAGER,))
def create_notice():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")

    v.require(body, "plan_id", "cure_period_days")
    days = v.get_int(body, "cure_period_days")
    if days < 1 or days > calc.CURE_MAX_DAYS:
        raise ApiError(
            "ERR_CURE_PERIOD_OUT_OF_RANGE",
            "cure_period_days must be between 1 and %d" % calc.CURE_MAX_DAYS,
        )

    breached = [i for i in domain.plan_items(plan["id"]) if i.get("is_overdue")]

    # band 6 — the life-safety cure ceiling precedes the breach-existence check.
    if (
        any(i["category"] == "LIFE_SAFETY" for i in breached)
        and days > calc.LIFE_SAFETY_CURE_MAX_DAYS
    ):
        raise ApiError(
            "ERR_CURE_PERIOD_TOO_LONG_FOR_LIFE_SAFETY",
            "a life-safety breach may be given at most %d days to cure"
            % calc.LIFE_SAFETY_CURE_MAX_DAYS,
        )

    # band 7
    if not breached:
        raise ApiError(
            "ERR_NO_BREACH_TO_NOTICE", "no item of this plan is overdue"
        )

    breached.sort(
        key=lambda i: (
            i["priority_rank"] is None,
            i["priority_rank"] if i["priority_rank"] is not None else 0,
            i["created_at"],
            i["_seq"],
        )
    )
    damages = calc.liquidated_damages_cents(breached)

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "cure_period_days": days,
            "cure_deadline_date": calc.fmt_date(calc.add_days(clock_date(), days)),
            "breached_item_ids": [i["id"] for i in breached],
            "liquidated_damages_cents": damages,
            "status": "ISSUED",
            "issued_by_user_id": g.user_id,
        }
    )
    repo.insert("notices", row)

    domain.append_ledger(
        plan["id"],
        None,
        "DEFAULT_ISSUED",
        damages,
        "default notice issued over %d overdue item(s)" % len(breached),
    )
    domain.recompute_property(domain.property_of_plan(plan))
    return repo.single(row, 201)


@route("/pip/default-notices/<row_id>", ["GET"], ANY_ROLE)
def get_notice(row_id):
    return repo.single(repo.must_find("notices", row_id))


@route("/pip/default-notices", ["GET"], ANY_ROLE)
def list_notices():
    limit, offset = v.pagination()
    rows = repo.rows("notices")
    for field in ("plan_id", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/default-notices/<row_id>/cure", ["POST"], (BRAND_MANAGER,))
def cure_notice(row_id):
    notice = repo.must_find("notices", row_id)
    plan = repo.find("plans", notice["plan_id"])

    if notice["status"] != "ISSUED":
        raise ApiError(
            "ERR_NOTICE_NOT_ACTIONABLE", "only an ISSUED notice may be actioned"
        )
    if _uncured(notice):
        raise ApiError(
            "ERR_BREACH_NOT_CURED",
            "%d of the snapshotted items are not yet complete" % len(_uncured(notice)),
        )

    notice["status"] = "CURED"
    repo.touch(notice)

    domain.append_ledger(
        notice["plan_id"],
        None,
        "DEFAULT_CURED",
        0,
        "default notice %s cured" % notice["id"],
    )
    if plan is not None:
        domain.recompute_property(domain.property_of_plan(plan))
    return repo.single(notice)


@route("/pip/default-notices/<row_id>/escalate", ["POST"], (BRAND_MANAGER,))
def escalate_notice(row_id):
    notice = repo.must_find("notices", row_id)
    plan = repo.find("plans", notice["plan_id"])

    if notice["status"] != "ISSUED":
        raise ApiError(
            "ERR_NOTICE_NOT_ACTIONABLE", "only an ISSUED notice may be actioned"
        )

    # band 7 — strictly after the deadline; on the deadline date itself, refused.
    deadline = calc.parse_date(notice["cure_deadline_date"])
    if deadline is not None and not clock_date() > deadline:
        raise ApiError(
            "ERR_CURE_PERIOD_NOT_ELAPSED",
            "the cure period runs through %s" % notice["cure_deadline_date"],
        )

    if not _uncured(notice):
        raise ApiError(
            "ERR_BREACH_ALREADY_CURED",
            "every snapshotted item has been brought into compliance",
        )

    notice["status"] = "ESCALATED_TO_TERMINATION"
    repo.touch(notice)

    domain.terminate_plan_cascade(plan, notice)
    return repo.single(notice)
