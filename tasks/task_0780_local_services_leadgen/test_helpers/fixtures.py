"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Setup calls use get_success_data() (lenient) so misconfiguration surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Identity threading: after a Customer or Pro is created, every ownership-gated
call uses make_customer_headers(id) / make_pro_headers(id) with that entity's
actual id — never a shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers, make_pro_headers
from .factories import (
    create_customer_payload,
    create_pro_payload,
    create_service_category_payload,
    create_subscription_plan_payload,
    create_service_request_payload,
    create_quote_payload,
    create_booking_payload,
    create_slot_payload,
)
from .constants import DEFAULT_CLOCK

ADMIN = TEST_USERS["admin_headers"]
CS = TEST_USERS["cs_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(iso: str, api=api_client):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


def reset_clock(api=api_client):
    return set_clock(DEFAULT_CLOCK, api)


# --------------------------------------------------------------------------
# Primitive entity builders
# --------------------------------------------------------------------------
def create_customer(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_customer(create_customer_payload(**overrides), ADMIN))


def create_category(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_service_category(create_service_category_payload(**overrides), ADMIN)
    )


def create_plan(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_subscription_plan(create_subscription_plan_payload(**overrides), ADMIN)
    )


def register_pro(api=api_client, **overrides) -> dict:
    """POST /pros — the pro starts UNVERIFIED / PAY_PER_LEAD."""
    return get_success_data(api.create_pro(create_pro_payload(**overrides), ADMIN))


def create_verified_pro(api=api_client, wallet: int = 0, category_ids=None,
                        zip_codes=None, **overrides) -> dict:
    """Register a pro, submit for verification, admin-APPROVE, and optionally
    top up the wallet. Returns the re-fetched (VERIFIED) Pro."""
    payload = {}
    if category_ids is not None:
        payload["covered_category_ids"] = category_ids
    if zip_codes is not None:
        payload["service_zip_codes"] = zip_codes
    payload.update(overrides)
    pro = register_pro(api, **payload)
    pid = pro["id"]
    hp = make_pro_headers(pid)
    get_success_data(api.submit_verification(pid, hp))
    get_success_data(api.verify_pro(pid, {"decision": "APPROVE"}, ADMIN))
    if wallet:
        get_success_data(api.credit_topup(pid, {"amount_cents": wallet}, ADMIN))
    return get_success_data(api.get_pro(pid, ADMIN))


def create_subscription_pro(api=api_client, plan_id=None, wallet: int = 0,
                            category_ids=None, zip_codes=None, **overrides) -> dict:
    """Verified pro that subscribes to `plan_id` (SUBSCRIPTION billing)."""
    pro = create_verified_pro(api, wallet=wallet, category_ids=category_ids,
                              zip_codes=zip_codes, billing_mode="SUBSCRIPTION", **overrides)
    pid = pro["id"]
    get_success_data(api.subscribe_pro(pid, {"subscription_plan_id": plan_id}, make_pro_headers(pid)))
    return get_success_data(api.get_pro(pid, ADMIN))


def create_request(customer_id, category_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_service_request(
            create_service_request_payload(customer_id, category_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def create_slot(pro_id, start_utc, end_utc, api=api_client) -> dict:
    return get_success_data(
        api.create_availability_slot(create_slot_payload(pro_id, start_utc, end_utc),
                                     make_pro_headers(pro_id))
    )


def distribute_once(request_id, expected_version, api=api_client) -> dict:
    """One distribute call; returns the updated ServiceRequest data."""
    return get_success_data(
        api.distribute(request_id, {"expected_service_request_version": expected_version}, ADMIN)
    )


def lead_for(request_id, pro_id, api=api_client) -> dict:
    """Return the (single) Lead of `request_id` held by `pro_id`."""
    data = get_success_data(api.list_leads(ADMIN, params={"request_id": request_id, "pro_id": pro_id}))
    assert data, f"Setup failed: no lead for request {request_id} / pro {pro_id}"
    return data[0]


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_distributed_lead(api=api_client, wallet: int = 20000, cat_overrides=None,
                           zip_code="94016", set_clock_first=True):
    """Empty DB -> customer + category + one VERIFIED funded PAY_PER_LEAD pro +
    OPEN request, then one distribute. Returns a dict:
        {customer, category, pro, request, lead}
    (request/pro/lead are re-fetched to reflect post-distribute state)."""
    if set_clock_first:
        reset_clock(api)
    cat = create_category(api, **(cat_overrides or {}))
    customer = create_customer(api)
    pro = create_verified_pro(api, wallet=wallet, category_ids=[cat["id"]], zip_codes=[zip_code])
    request = create_request(customer["id"], cat["id"], api=api, zip_code=zip_code)
    updated_req = distribute_once(request["id"], request["version"], api=api)
    lead = lead_for(request["id"], pro["id"], api=api)
    return {
        "customer": customer,
        "category": cat,
        "pro": get_success_data(api.get_pro(pro["id"], ADMIN)),
        "request": updated_req,
        "lead": lead,
    }


def setup_contacted_lead(api=api_client, **kwargs):
    """setup_distributed_lead + the owning pro marks the lead CONTACTED."""
    ctx = setup_distributed_lead(api=api, **kwargs)
    pid = ctx["pro"]["id"]
    ctx["lead"] = get_success_data(api.contact_lead(ctx["lead"]["id"], make_pro_headers(pid)))
    return ctx


def setup_quoted_lead(api=api_client, amount_cents=10000, **kwargs):
    """setup_contacted_lead + the pro sends a quote (lead -> QUOTED)."""
    ctx = setup_contacted_lead(api=api, **kwargs)
    pid = ctx["pro"]["id"]
    quote = get_success_data(
        api.create_quote(create_quote_payload(ctx["lead"]["id"], amount_cents=amount_cents),
                         make_pro_headers(pid))
    )
    ctx["quote"] = quote
    ctx["lead"] = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    return ctx


def setup_confirmed_booking(api=api_client, amount_cents=10000,
                            slot_start="2026-03-05T08:00:00Z", slot_end="2026-03-05T20:00:00Z",
                            scheduled_start="2026-03-05T10:00:00Z",
                            scheduled_end="2026-03-05T11:00:00Z", **kwargs):
    """Full chain to a CONFIRMED booking. Adds a slot for the pro, quotes the
    lead, and books it. Returns ctx with {slot, quote, booking} added."""
    ctx = setup_quoted_lead(api=api, amount_cents=amount_cents, **kwargs)
    pid = ctx["pro"]["id"]
    cid = ctx["customer"]["id"]
    slot = create_slot(pid, slot_start, slot_end, api=api)
    booking = get_success_data(
        api.create_booking(
            create_booking_payload(ctx["quote"]["id"], slot["id"], scheduled_start, scheduled_end),
            make_customer_headers(cid),
        )
    )
    ctx["slot"] = get_success_data(api.get_availability_slot(slot["id"], ADMIN))
    ctx["booking"] = booking
    ctx["quote"] = get_success_data(api.get_quote(ctx["quote"]["id"], ADMIN))
    ctx["lead"] = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    return ctx


def setup_completed_booking(api=api_client, complete_at="2026-03-05T12:00:00Z", **kwargs):
    """setup_confirmed_booking + advance clock past scheduled_start + complete.
    Returns ctx with a COMPLETED booking."""
    ctx = setup_confirmed_booking(api=api, **kwargs)
    set_clock(complete_at, api)
    pid = ctx["pro"]["id"]
    ctx["booking"] = get_success_data(api.complete_booking(ctx["booking"]["id"], make_pro_headers(pid)))
    return ctx
