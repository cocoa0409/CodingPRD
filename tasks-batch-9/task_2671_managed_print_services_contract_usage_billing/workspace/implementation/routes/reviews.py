"""Quarterly business review endpoints (PRD 3.8)."""
import re

from flask import Blueprint

import calc
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract, get_review
from store import db, new_row, touch

bp = Blueprint("reviews", __name__)

QUARTER_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")
PUBLISH_ACTIONS = ("UPGRADE", "CONSOLIDATE")


@bp.post("/quarterly-reviews")
def create_review():
    user_id, _role = require("AccountManager")
    body = v.body()
    contract_id = v.id_field(body, "contract_id")
    quarter_label = v.string_field(body, "quarter_label", max_len=16)
    if not QUARTER_RE.match(quarter_label):
        fail("ERR_INVALID_REQUEST",
             "Field 'quarter_label' must match the form YYYY-Qn (for example 2026-Q3).")
    contract = get_contract(contract_id)

    for row in db.reviews.values():
        if row["contract_id"] == contract["id"] and row["quarter_label"] == quarter_label:
            fail("ERR_QUARTER_DUPLICATE",
                 "A review for quarter %s already exists on this contract." % quarter_label)

    fleet = calc.review_fleet(contract["id"])
    baseline_savings, realized_savings = calc.tco_savings(contract, fleet)
    actions, tallies = calc.right_sizing(contract, fleet)
    trend = calc.volume_trend(contract["id"])

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "quarter_label": quarter_label,
        "status": "DRAFT",
        "authored_by_user_id": user_id,
        "approved_by_user_id": None,
        "baseline_savings_cents": baseline_savings,
        "realized_savings_cents": realized_savings,
        "volume_trend_pct": trend,
        "retain_count": tallies["RETAIN"],
        "downgrade_count": tallies["DOWNGRADE"],
        "upgrade_count": tallies["UPGRADE"],
        "consolidate_count": tallies["CONSOLIDATE"],
        "refresh_due_device_count": tallies["UPGRADE"] + tallies["CONSOLIDATE"],
    })
    # Recommendations are computed here but only published (as refresh_due) on
    # approval, so the device rows are annotated without a version bump.
    for device in fleet:
        device["right_sizing_action"] = actions[device["id"]]
    db.reviews[row["id"]] = row
    return created(serialize.review(row))


@bp.get("/quarterly-reviews/<review_id>")
def read_review(review_id):
    require("AccountManager", "BillingAnalyst", "CustomerAdmin")
    review = get_review(review_id)
    return ok(serialize.review(review))


@bp.get("/service-contracts/<contract_id>/quarterly-reviews")
def list_contract_reviews(contract_id):
    require("AccountManager", "BillingAnalyst", "CustomerAdmin")
    contract = get_contract(contract_id)
    rows = [r for r in db.sorted_rows("reviews") if r["contract_id"] == contract["id"]]
    status = v.query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, meta = v.paginate(rows, serialize.review)
    return ok_list(data, meta)


@bp.post("/quarterly-reviews/<review_id>/approve")
def approve_review(review_id):
    user_id, _role = require("AccountManager")
    review = get_review(review_id)
    v.body()
    if review["status"] != "DRAFT":
        fail("ERR_REVIEW_ALREADY_APPROVED",
             "This review has already been approved.")
    if user_id == review["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver of a review must differ from its author.")

    review["status"] = "APPROVED"
    review["approved_by_user_id"] = user_id
    touch(review)
    for device in derive.contract_devices(review["contract_id"]):
        if device["right_sizing_action"] in PUBLISH_ACTIONS:
            device["refresh_due"] = True
            touch(device)
    return ok(serialize.review(review))
