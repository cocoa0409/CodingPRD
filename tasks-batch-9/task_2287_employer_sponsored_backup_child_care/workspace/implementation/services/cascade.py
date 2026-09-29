"""Provider posture transitions, withdrawal cascade, maintenance sweep."""

from datetime import date

from db import clock, db
from util import D, utc_date

from services.calc import plan_of
from services.core import (
    append_ledger,
    has_full_credentials,
    sort_created,
    touch,
)
from services.matching import expire_offers

PROVIDER_TRANSITIONS = {
    "PENDING": set(),
    "CREDENTIALED": {"PROBATION", "SUSPENDED", "DEPROVISIONED"},
    "PROBATION": {"CREDENTIALED", "SUSPENDED", "DEPROVISIONED"},
    "SUSPENDED": {"CREDENTIALED", "DEPROVISIONED"},
    "DEPROVISIONED": set(),
}


def transition_allowed(current, target):
    return target in PROVIDER_TRANSITIONS.get(current, set())


def withdraw_future_confirmed(provider):
    """CONFIRMED -> MATCHING for every future confirmed reservation of the provider."""
    withdrawn = 0
    for reservation in sort_created(list(db.reservations.values())):
        if reservation["matched_provider_id"] != provider["id"]:
            continue
        if reservation["fulfillment_status"] != "CONFIRMED":
            continue
        if not reservation["care_start_utc"] > clock():
            continue
        block = db.capacity_blocks.get(reservation["matched_capacity_block_id"])
        append_ledger(
            reservation["employee_id"],
            reservation["id"],
            "RELEASE",
            -D(reservation["days_charged_provisional"]),
            0,
            "PROVIDER_WITHDRAWN",
        )
        reservation["fulfillment_status"] = "MATCHING"
        reservation["matched_provider_id"] = None
        reservation["matched_capacity_block_id"] = None
        reservation["confirmation_code"] = None
        reservation["days_charged_provisional"] = D(0)
        reservation["covered_days"] = D(0)
        reservation["overage_days"] = D(0)
        reservation["copay_cents"] = 0
        reservation["overage_cents"] = 0
        reservation["overage_tier_multiplier"] = D(1)
        touch(reservation)
        if block is not None:
            touch(block)
        withdrawn += 1
    return withdrawn


def set_provider_status(provider, target, reason_code):
    provider["network_status"] = target
    provider["last_status_reason_code"] = reason_code
    touch(provider)
    if target in ("SUSPENDED", "DEPROVISIONED"):
        return withdraw_future_confirmed(provider)
    return 0


def apply_no_show(reservation, reason_code=None):
    plan = plan_of(reservation)
    penalty = plan["no_show_charge_cents"] if plan is not None else 0
    days = D(reservation["days_charged_provisional"])
    block = db.capacity_blocks.get(reservation["matched_capacity_block_id"])

    reservation["penalty_cents"] = penalty
    reservation["fulfillment_status"] = "NO_SHOW"
    reservation["billing_status"] = "ACCRUED"
    touch(reservation)

    append_ledger(
        reservation["employee_id"], reservation["id"], "RELEASE", -days, 0, "NO_SHOW_RELEASE"
    )
    append_ledger(
        reservation["employee_id"], reservation["id"], "COMMIT", days, 0, "NO_SHOW_COMMIT"
    )
    append_ledger(
        reservation["employee_id"],
        reservation["id"],
        "NO_SHOW_CHARGE",
        0,
        penalty,
        "NO_SHOW",
    )
    if block is not None:
        touch(block)


def run_maintenance():
    counters = {
        "credentials_expired": 0,
        "providers_suspended": 0,
        "reservations_unfulfilled": 0,
        "offers_expired": 0,
        "blocks_closed": 0,
        "reservations_no_showed": 0,
        "reservations_withdrawn": 0,
    }
    clock_date = utc_date(clock())

    # step 1 — credential expiry
    for credential in sort_created(list(db.credentials.values())):
        if credential["status"] != "VALID":
            continue
        if date.fromisoformat(credential["expires_on"]) < clock_date:
            credential["status"] = "EXPIRED"
            touch(credential)
            counters["credentials_expired"] += 1

    # step 2 — providers that lost a required credential
    for provider in sort_created(list(db.providers.values())):
        if provider["network_status"] not in ("CREDENTIALED", "PROBATION"):
            continue
        if has_full_credentials(provider["id"], clock_date):
            continue
        counters["reservations_withdrawn"] += set_provider_status(
            provider, "SUSPENDED", "CREDENTIAL_EXPIRED"
        )
        counters["providers_suspended"] += 1

    # step 3 — reservations whose care window elapsed
    for reservation in sort_created(list(db.reservations.values())):
        if reservation["fulfillment_status"] not in ("INTAKE", "MATCHING", "OFFERED"):
            continue
        if not reservation["care_start_utc"] < clock():
            continue
        if reservation["fulfillment_status"] == "OFFERED":
            expire_offers(
                reservation["id"], ("PROPOSED", "SELECTED"), "CARE_WINDOW_ELAPSED"
            )
            reservation["matched_provider_id"] = None
        reservation["fulfillment_status"] = "UNFULFILLED"
        reservation["unfulfilled_reason_code"] = "CARE_WINDOW_ELAPSED"
        touch(reservation)
        counters["reservations_unfulfilled"] += 1

    # step 4 — offers past their TTL
    for offer in sort_created(list(db.match_offers.values())):
        if offer["offer_status"] not in ("PROPOSED", "SELECTED"):
            continue
        if offer["offer_expires_at"] < clock():
            offer["offer_status"] = "EXPIRED"
            offer["reason_code"] = "OFFER_TTL_ELAPSED"
            touch(offer)
            counters["offers_expired"] += 1

    # step 5 — past-dated capacity blocks
    for block in sort_created(list(db.capacity_blocks.values())):
        if block.get("closed"):
            continue
        if date.fromisoformat(block["service_date"]) < clock_date:
            block["closed"] = True
            touch(block)
            counters["blocks_closed"] += 1

    # step 6 — confirmed care that never happened
    for reservation in sort_created(list(db.reservations.values())):
        if reservation["fulfillment_status"] != "CONFIRMED":
            continue
        if reservation["care_end_utc"] < clock():
            apply_no_show(reservation)
            counters["reservations_no_showed"] += 1

    return counters
