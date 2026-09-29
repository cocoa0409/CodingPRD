"""The four-step clock sweep of PRD 2.5, with the per-state side effects of 3.4."""
import ledgers
from db import ordered, store, touch

LC_EXPIRABLE = ("RECEIVED", "UNDER_REVIEW", "AMENDMENT_REQUESTED", "ACCEPTED")


def _presentations_of_lc(lc_id):
    return [p for p in ordered(store.presentations) if p["letter_of_credit_id"] == lc_id]


def _presentations_of_order(order_id):
    return [p for p in store.presentations.values() if p["export_order_id"] == order_id]


def _expire_lc(lc):
    previous = lc["status"]
    order = store.orders.get(lc["export_order_id"])
    presentations = _presentations_of_order(lc["export_order_id"])

    if previous == "ACCEPTED":
        if any(p["status"] in ("COMPLIED", "HONOURED") for p in presentations):
            return
        release_money = not any(p["status"] in ("PRESENTED", "CURING", "COMPLIED")
                                for p in presentations)

    lc["status"] = "EXPIRED"
    touch(lc)

    if previous == "UNDER_REVIEW":
        for review in ordered(store.reviews):
            if review["letter_of_credit_id"] == lc["id"] and review["status"] == "DRAFTING":
                review["status"] = "SUPERSEDED"
                touch(review)

    if previous == "ACCEPTED":
        if order is not None and release_money and order["settlement_status"] == "LC_ACCEPTED":
            order["settlement_status"] = "UNSECURED"
            ledgers.release_exposure(order)
            touch(order)
        for presentation in _presentations_of_lc(lc["id"]):
            if presentation["status"] in ("PRESENTED", "CURING", "DISCREPANT"):
                presentation["status"] = "REFUSED"
                presentation["refusal_reason"] = "CREDIT_EXPIRED"
                touch(presentation)


def run_sweep(instant):
    # step 1 — letters of credit
    for lc in ordered(store.lcs):
        if lc["status"] in LC_EXPIRABLE and lc["_expiry_dt"] < instant:
            _expire_lc(lc)

    # step 2 — export licenses
    for license_row in ordered(store.licenses):
        if license_row["status"] in ("ISSUED", "ACTIVE", "EXHAUSTED") \
                and license_row["_to_dt"] < instant:
            license_row["status"] = "EXPIRED"
            touch(license_row)

    # step 3 — credit insurance policies
    affected_buyers = {}
    for policy in ordered(store.policies):
        if policy["status"] in ("ACTIVE", "EXHAUSTED") and policy["_to_dt"] < instant:
            policy["status"] = "EXPIRED"
            touch(policy)
            buyer = store.buyers.get(policy["buyer_id"])
            if buyer is not None:
                affected_buyers[buyer["id"]] = buyer
    for buyer in affected_buyers.values():
        ledgers.recompute_buyer_exposure(buyer)

    # step 4 — vessel sailings
    for sailing in ordered(store.sailings):
        if sailing["status"] not in ("OPEN", "FULL", "CUTOFF_PASSED"):
            continue
        before = sailing["status"]
        if before in ("OPEN", "FULL") and instant >= sailing["_cutoff_dt"]:
            sailing["status"] = "CUTOFF_PASSED"
        if instant >= sailing["_etd_dt"]:
            sailing["status"] = "DEPARTED"
        if sailing["status"] != before:
            touch(sailing)
