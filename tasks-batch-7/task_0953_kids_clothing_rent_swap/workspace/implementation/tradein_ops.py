"""Shared Pipeline T operations (PRD 3.9)."""

import calc
import constants as K
import store


def resolve_demand_band(declared_size_code):
    candidates = [s for s in store.all_rows("styles")
                  if s["status"] == "ACTIVE" and s["size_code"] == declared_size_code]
    if not candidates:
        return "MEDIUM"
    candidates.sort(key=lambda s: (K.DEMAND_BAND_ORDINALS[s["demand_band"]], store.order_key(s)))
    return candidates[0]["demand_band"]


def apply_confirmed_grade(item, grade):
    """Confirmation of a TRADE_IN assessment drives both axes."""
    item["assessed_grade"] = grade
    if K.GRADE_ORDINALS[grade] <= 3:
        item["grading_status"] = "GRADED"
        item["demand_band"] = resolve_demand_band(item["declared_size_code"])
        item["credit_cents"] = calc.tradein_item_credit(
            grade, item["declared_brand_tier"], item["demand_band"])
    else:
        item["grading_status"] = "REJECTED"
        item["credit_cents"] = 0
        if item["disposition_status"] == "NONE":
            item["disposition_status"] = "AWAITING_ELECTION"
    store.touch(item)
    return item


def submission_items(submission_id):
    return [i for i in store.all_rows("trade_in_items") if i["submission_id"] == submission_id]


def maybe_close_submission(submission):
    """CREDITED -> CLOSED once no garment is left hanging."""
    if submission["status"] != "CREDITED":
        return
    for item in submission_items(submission["id"]):
        if item["disposition_status"] in ("NONE", "AWAITING_ELECTION"):
            return
    submission["status"] = "CLOSED"
    store.touch(submission)
