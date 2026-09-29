"""Release trains and the remediation budget waterfall (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint

from calc import allocation_candidates, issue_ask_cents
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import obj_response
from serialize import train_out
from validate import (
    body,
    fk_product,
    path_train,
    v_date,
    v_int,
    v_str,
)

bp = Blueprint("trains", __name__)


def _train_issues(train_id):
    return [i for i in db.issues.values() if i.get("release_train_id") == train_id]


def _sync_unallocated(train):
    granted = sum(i["funded_cents"] for i in _train_issues(train["id"]))
    train["unallocated_cents"] = train["remediation_budget_cents"] - granted


@bp.post("/release-trains")
@endpoint(["AccessibilityLead"])
def create_train():
    data = body()
    name = v_str(data, "name", required=True, min_len=1, max_len=120)
    start_raw, start = v_date(data, "window_start", required=True)
    end_raw, end = v_date(data, "window_end", required=True)
    if end < start:
        raise bad_request("'window_end' must be on or after 'window_start'")
    freeze_days = v_int(data, "freeze_days", min_value=0, max_value=60, default=0)
    window_length = (end - start).days + 1
    if freeze_days >= window_length:
        raise bad_request("'freeze_days' must be fewer than the %d days in the window"
                          % window_length)
    capacity = v_int(data, "effort_capacity_points", required=True,
                     min_value=1, max_value=1000)
    budget = v_int(data, "remediation_budget_cents", required=True,
                   min_value=0, max_value=100000000)

    # step 25: windows must be separated by at least one full calendar day
    for existing in db.trains.values():
        if (start <= existing["_window_end"] + timedelta(days=1)
                and end >= existing["_window_start"] - timedelta(days=1)):
            raise ApiError("ERR_TRAIN_WINDOW_ADJACENT",
                           "Release train %s occupies an overlapping or abutting "
                           "window" % existing["id"])

    # step 35: uniqueness
    for existing in db.trains.values():
        if existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_TRAIN_NAME",
                           "Release train name %s is already in use" % name)

    row = new_row({
        "name": name,
        "window_start": start_raw,
        "window_end": end_raw,
        "freeze_days": freeze_days,
        "effort_capacity_points": capacity,
        "committed_effort_points": 0,
        "remediation_budget_cents": budget,
        "unallocated_cents": budget,
        "allocation_state": "UNALLOCATED",
    })
    row["_window_start"] = start
    row["_window_end"] = end
    db.trains[row["id"]] = row
    return obj_response(train_out(row), 201)


@bp.get("/release-trains/<train_id>")
@endpoint(ALL_ROLES)
def get_train(train_id):
    return obj_response(train_out(path_train(train_id)))


@bp.post("/release-trains/<train_id>/allocate-budget")
@endpoint(["AccessibilityLead"])
def allocate_budget(train_id):
    train = path_train(train_id)
    data = body()
    product = fk_product(data.get("product_id"))          # step 5
    v_str(data, "product_id", required=True, min_len=1)

    # step 14: allocation state
    if train["allocation_state"] == "ALLOCATED":
        raise ApiError("ERR_TRAIN_BUDGET_ALREADY_ALLOCATED",
                       "Release train %s has already allocated its budget"
                       % train["id"])
    # step 15: posture gate
    if product["publication_posture"] == "FROZEN":
        raise ApiError("ERR_PRODUCT_POSTURE_FROZEN",
                       "Product %s is FROZEN" % product["id"])

    candidates = allocation_candidates(train, product["id"])
    # step 39: at least one fundable issue
    if not candidates:
        raise ApiError("ERR_NO_FUNDABLE_ISSUES",
                       "Release train %s has no fundable issues for product %s"
                       % (train["id"], product["id"]))

    remaining = train["remediation_budget_cents"]
    for issue in candidates:
        ask = issue_ask_cents(issue)                # rounded per issue, before spending
        grant = ask if ask <= remaining else remaining
        issue["funded_cents"] = grant
        if grant == 0:
            issue["funding_state"] = "UNFUNDED"
        elif grant == ask:
            issue["funding_state"] = "FULLY_FUNDED"
        else:
            issue["funding_state"] = "PARTIALLY_FUNDED"
        remaining -= grant
        touch(issue)

    _sync_unallocated(train)
    train["allocation_state"] = "ALLOCATED"
    touch(train)
    return obj_response(train_out(train))


@bp.post("/release-trains/<train_id>/deallocate-budget")
@endpoint(["AccessibilityLead"])
def deallocate_budget(train_id):
    train = path_train(train_id)
    data = body()
    product = fk_product(data.get("product_id"))          # step 5
    v_str(data, "product_id", required=True, min_len=1)
    v_str(data, "reason", required=True, min_len=1, max_len=2000)

    # step 14: allocation state
    if train["allocation_state"] != "ALLOCATED":
        raise ApiError("ERR_TRAIN_BUDGET_NOT_ALLOCATED",
                       "Release train %s has no allocation to reverse" % train["id"])

    for issue in _train_issues(train["id"]):
        if issue["product_id"] != product["id"]:
            continue
        if issue["funded_cents"] == 0 and issue["funding_state"] == "UNFUNDED":
            continue
        issue["funded_cents"] = 0
        issue["funding_state"] = "UNFUNDED"
        touch(issue)

    _sync_unallocated(train)
    train["allocation_state"] = "UNALLOCATED"
    touch(train)
    return obj_response(train_out(train))
