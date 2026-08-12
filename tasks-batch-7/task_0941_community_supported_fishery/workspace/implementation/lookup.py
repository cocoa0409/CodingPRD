"""Screening-ladder rungs 7 to 21 -- existence (PRD 2.5)."""
import store
from errors import ApiError

_RUNGS = [
    ("Season", "ERR_SEASON_NOT_FOUND"),
    ("catalog", "ERR_CATALOG_NOT_FOUND"),
    ("Member", "ERR_MEMBER_NOT_FOUND"),
    ("Subscription", "ERR_SUBSCRIPTION_NOT_FOUND"),
    ("Vessel", "ERR_VESSEL_NOT_FOUND"),
    ("QuotaLedger", "ERR_QUOTA_LEDGER_NOT_FOUND"),
    ("Trip", "ERR_TRIP_NOT_FOUND"),
    ("LandingLot", "ERR_LANDING_LOT_NOT_FOUND"),
    ("SubLot", "ERR_SUB_LOT_NOT_FOUND"),
    ("ShareDelivery", "ERR_SHARE_DELIVERY_NOT_FOUND"),
    ("SubstitutionEvent", "ERR_SUBSTITUTION_NOT_FOUND"),
    ("SkipRequest", "ERR_SKIP_REQUEST_NOT_FOUND"),
    ("SettlementStatement", "ERR_SETTLEMENT_NOT_FOUND"),
    ("ShareTransfer", "ERR_SHARE_TRANSFER_NOT_FOUND"),
    ("RecallNotice", "ERR_RECALL_NOT_FOUND"),
]


def _fetch(kind, rec_id, error_id):
    rec = store.get(kind, rec_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def season(rec_id):
    return _fetch("Season", rec_id, "ERR_SEASON_NOT_FOUND")          # rung 7


def share_plan(rec_id):
    return _fetch("SharePlan", rec_id, "ERR_CATALOG_NOT_FOUND")      # rung 8


def delivery_zone(rec_id):
    return _fetch("DeliveryZone", rec_id, "ERR_CATALOG_NOT_FOUND")   # rung 8


def pickup_hub(rec_id):
    return _fetch("PickupHub", rec_id, "ERR_CATALOG_NOT_FOUND")      # rung 8


def pickup_window(rec_id):
    return _fetch("PickupWindow", rec_id, "ERR_CATALOG_NOT_FOUND")   # rung 8


def member(rec_id):
    return _fetch("Member", rec_id, "ERR_MEMBER_NOT_FOUND")          # rung 9


def subscription(rec_id):
    return _fetch("Subscription", rec_id, "ERR_SUBSCRIPTION_NOT_FOUND")  # rung 10


def vessel(rec_id):
    return _fetch("Vessel", rec_id, "ERR_VESSEL_NOT_FOUND")          # rung 11


def quota_ledger(rec_id):
    return _fetch("QuotaLedger", rec_id, "ERR_QUOTA_LEDGER_NOT_FOUND")   # rung 12


def trip(rec_id):
    return _fetch("Trip", rec_id, "ERR_TRIP_NOT_FOUND")              # rung 13


def landing_lot(rec_id):
    return _fetch("LandingLot", rec_id, "ERR_LANDING_LOT_NOT_FOUND")  # rung 14


def sub_lot(rec_id):
    return _fetch("SubLot", rec_id, "ERR_SUB_LOT_NOT_FOUND")         # rung 15


def share_delivery(rec_id):
    return _fetch("ShareDelivery", rec_id, "ERR_SHARE_DELIVERY_NOT_FOUND")  # rung 16


def substitution(rec_id):
    return _fetch("SubstitutionEvent", rec_id, "ERR_SUBSTITUTION_NOT_FOUND")  # rung 17


def skip_request(rec_id):
    return _fetch("SkipRequest", rec_id, "ERR_SKIP_REQUEST_NOT_FOUND")  # rung 18


def settlement(rec_id):
    return _fetch("SettlementStatement", rec_id, "ERR_SETTLEMENT_NOT_FOUND")  # rung 19


def share_transfer(rec_id):
    return _fetch("ShareTransfer", rec_id, "ERR_SHARE_TRANSFER_NOT_FOUND")  # rung 20


def recall(rec_id):
    return _fetch("RecallNotice", rec_id, "ERR_RECALL_NOT_FOUND")    # rung 21


# --- silent resolution helpers (never raise) -------------------------------

def maybe(kind, rec_id):
    return store.get(kind, rec_id)


def season_of_trip(trip_rec):
    return store.get("Season", trip_rec["season_id"])


def season_of_lot(lot):
    t = store.get("Trip", lot["trip_id"])
    return store.get("Season", t["season_id"]) if t else None


def trip_of_lot(lot):
    return store.get("Trip", lot["trip_id"])


def plan_of_subscription(sub):
    return store.get("SharePlan", sub["share_plan_id"])


def member_of_subscription(sub):
    return store.get("Member", sub["member_id"])


def subscription_of_delivery(delivery):
    return store.get("Subscription", delivery["subscription_id"])
