"""Operator endpoints: the logical clock and the daily epoch sweep (PRD 2.4)."""

from flask import Blueprint

import domain as D
from db import store, bump, fmt_clock
from errors import ApiError
from middleware import get_context, require_role
from response import success_object

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = get_context()
    require_role(role, ["SystemOperator"])
    body = D.get_body()
    to_iso8601 = D.req_str(body, "to_iso8601")
    store.clock = D.parse_datetime(to_iso8601, "to_iso8601")
    return success_object({"current_utc": fmt_clock(store.clock)})


@bp.route("/_ops/run_epoch", methods=["POST"])
def run_epoch():
    _uid, role = get_context()
    require_role(role, ["SystemOperator"])
    today = D.clock_date()

    # 1. Expire credential items past expires_on, with the full dependency cascade.
    expired_credential_ids = []
    candidates = sorted(store.credential_items.values(), key=lambda r: r["_seq"])
    for item in candidates:
        if item["status"] not in D.EXPIRABLE_CREDENTIAL_STATUSES:
            continue
        if not item["expires_on"]:
            continue
        if D.parse_date(item["expires_on"], "expires_on") >= today:
            continue
        item["status"] = "EXPIRED"
        bump(item)
        expired_credential_ids.append(item["id"])
        D.cascade_credential_failure(item)
        case = store.cases.get(item["onboarding_case_id"])
        if case is not None:
            D.recompute_credential_status(case)
            D.freeze_panel_if_unready(case)
            D.recompute_posture(case)
            bump(case)

    # 2. Expire EXTENDED / COUNTERED offers whose expires_at lies in the past.
    expired_offer_ids = []
    offers = sorted(store.offers.values(), key=lambda r: r["_seq"])
    for offer in offers:
        if offer["status"] not in ("EXTENDED", "COUNTERED"):
            continue
        if D.parse_datetime(offer["expires_at"], "expires_at") >= store.clock:
            continue
        offer["status"] = "EXPIRED"
        bump(offer)
        expired_offer_ids.append(offer["id"])
        case = store.cases.get(offer["onboarding_case_id"])
        if case is not None:
            bump(case)

    # 3. Lapse PENDING milestones whose reporting window has closed.
    lapsed_milestone_ids = []
    milestones = sorted(store.milestones.values(), key=lambda r: r["_seq"])
    for milestone in milestones:
        if milestone["status"] != "PENDING":
            continue
        guarantee = D.guarantee_of_case(milestone["onboarding_case_id"])
        if guarantee is None:
            continue
        if today <= D.reporting_deadline(guarantee["start_month"], milestone["month_offset"]):
            continue
        milestone["status"] = "LAPSED"
        bump(milestone)
        lapsed_milestone_ids.append(milestone["id"])
        case = store.cases.get(milestone["onboarding_case_id"])
        if case is not None:
            D.recompute_case_counts(case)
            bump(case)

    return success_object({
        "expired_credential_ids": expired_credential_ids,
        "expired_offer_ids": expired_offer_ids,
        "lapsed_milestone_ids": lapsed_milestone_ids,
    })
