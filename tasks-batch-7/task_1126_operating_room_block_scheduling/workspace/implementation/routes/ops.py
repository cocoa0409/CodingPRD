"""Ops-run checkpoints: release sweep and scoring run."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import db
from middleware import require_roles
from response import success_object
from services import (
    release_block,
    run_selector,
    compute_report,
    create_report,
    create_review,
)
from util import parse_date

bp = Blueprint("ops", __name__)


@bp.route("/ops/release-sweep", methods=["POST"])
def release_sweep():
    require_roles("SchedulingAdmin")
    clock = db.clock
    today = clock.date()

    released_blocks = 0
    slots_created = 0
    slots_expired = 0
    requests_approved = 0
    requests_expired = 0

    evaluated_slots = set()

    # 1. release every ACTIVE block whose release_deadline_at <= clock
    for block in list(db.blocks.values()):
        if block["status"] != "ACTIVE":
            continue
        if parse_date_time(block["release_deadline_at"]) <= clock:
            new_slots = release_block(block)
            released_blocks += 1
            for slot in new_slots:
                slots_created += 1
                evaluated_slots.add(slot["id"])
                requests_approved += run_selector(slot)

    # 2. expire OPEN slots whose date is strictly before the clock's date,
    #    along with their PENDING requests
    for slot in list(db.slots.values()):
        if slot["status"] != "OPEN":
            continue
        if parse_date(slot["date"]) < today:
            slot["status"] = "EXPIRED"
            from services import touch

            touch(slot)
            slots_expired += 1
            for req in list(db.requests.values()):
                if req["slot_id"] == slot["id"] and req["status"] == "PENDING":
                    req["status"] = "EXPIRED"
                    touch(req)
                    requests_expired += 1

    # 3. run the selector over every remaining OPEN slot with PENDING requests
    for slot in list(db.slots.values()):
        if slot["status"] != "OPEN" or slot["id"] in evaluated_slots:
            continue
        has_pending = any(
            r["slot_id"] == slot["id"] and r["status"] == "PENDING"
            for r in db.requests.values()
        )
        if has_pending:
            requests_approved += run_selector(slot)

    return success_object(
        {
            "released_blocks": released_blocks,
            "slots_created": slots_created,
            "slots_expired": slots_expired,
            "requests_approved": requests_approved,
            "requests_expired": requests_expired,
        }
    )


def parse_date_time(value):
    from util import parse_datetime

    return parse_datetime(value)


@bp.route("/ops/scoring-run", methods=["POST"])
def scoring_run():
    require_roles("SchedulingAdmin")
    today = db.clock.date()
    period_start = today - timedelta(days=7)
    period_end = today

    reports_created = 0
    reviews_created = 0
    for line in list(db.service_lines.values()):
        metrics = compute_report(line, period_start, period_end)
        report = create_report(line, period_start, period_end, metrics)
        reports_created += 1
        # deficiency -> open a committee review (dedup on existing OPEN review)
        if Decimal(str(metrics["prime_time_utilization_pct"])) < Decimal(
            str(line["target_utilization_pct"])
        ):
            has_open = any(
                r["service_line_id"] == line["id"] and r["status"] == "OPEN"
                for r in db.reviews.values()
            )
            if not has_open:
                create_review(line, report, period_end)
                reviews_created += 1

    return success_object(
        {"reports_created": reports_created, "reviews_created": reviews_created}
    )
