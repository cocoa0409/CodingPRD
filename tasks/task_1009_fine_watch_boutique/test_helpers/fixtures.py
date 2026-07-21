"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch — the server DB is empty at the start of
every test. Ownership-gated calls thread the acting entity's id through the
per-instance header builders in test_users.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_watch_model_payload,
    create_watchmaker_payload,
    create_watch_payload,
    create_waitlist_entry_payload,
    create_service_ticket_payload,
    create_trade_in_offer_payload,
    create_layaway_plan_payload,
)
from .test_users import TEST_USERS, make_watchmaker_headers

ASSOC = TEST_USERS["associate_headers"]


# ─── Primitives ───────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock (Associate-only)."""
    get_success_data(api_client.set_clock(to_iso8601, ASSOC))


def new_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ASSOC))


def new_model(**overrides) -> dict:
    return get_success_data(
        api_client.create_watch_model(create_watch_model_payload(**overrides), ASSOC)
    )


def new_watchmaker(**overrides) -> dict:
    return get_success_data(
        api_client.create_watchmaker(create_watchmaker_payload(**overrides), ASSOC)
    )


def new_watch(model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_watch(create_watch_payload(model_id, **overrides), ASSOC)
    )


def authenticate(watch_id: str) -> dict:
    return get_success_data(api_client.authenticate_watch(watch_id, ASSOC))


def new_authenticated_watch(model_id: str, **overrides) -> dict:
    watch = new_watch(model_id, **overrides)
    return authenticate(watch["id"])


def model_and_watch(model_over=None, watch_over=None, authenticate_watch=True) -> tuple:
    """Create a model + one watch. Returns (model, watch). Authenticates by default."""
    model = new_model(**(model_over or {}))
    watch = new_watch(model["id"], **(watch_over or {}))
    if authenticate_watch:
        watch = authenticate(watch["id"])
    return model, watch


# ─── Appraisal context (Tier 2) ───────────────────────────────────────────
def appraisable_watch(model_over=None, watch_over=None) -> dict:
    """A freshly created (UNVERIFIED, version 1) watch ready for an appraisal.

    Appraisals do not require authentication; the OCC input is the watch's
    current version. Returns {"model", "watch"}.
    """
    model = new_model(**(model_over or {}))
    watch = new_watch(model["id"], **(watch_over or {}))
    return {"model": model, "watch": watch}


# ─── Service-ticket contexts (Tiers 2 & 3) ─────────────────────────────────
def service_context(authenticate_watch=True, clock="2026-07-02T00:00:00Z",
                    model_over=None, watch_over=None) -> dict:
    """A customer, an ACTIVE model, a watch (authenticated by default) and a
    watchmaker — everything needed to open a service ticket.
    Returns {"customer", "model", "watch", "watchmaker"}.
    """
    if clock:
        set_clock(clock)
    customer = new_customer()
    model = new_model(**(model_over or {}))
    watch = new_watch(model["id"], **(watch_over or {}))
    if authenticate_watch:
        watch = authenticate(watch["id"])
    watchmaker = new_watchmaker()
    return {"customer": customer, "model": model, "watch": watch, "watchmaker": watchmaker}


def open_ticket(ctx: dict, **ticket_over) -> dict:
    """Open a RECEIVED/UNPAID service ticket for a service_context dict."""
    payload = create_service_ticket_payload(
        ctx["watch"]["id"], ctx["customer"]["id"], ctx["watchmaker"]["id"], **ticket_over
    )
    return get_success_data(api_client.create_service_ticket(payload, ASSOC))


def ticket_ready_unpaid(service_type="BATTERY", clock="2026-07-02T00:00:00Z",
                        ticket_over=None) -> dict:
    """Full chain to a READY + UNPAID ticket (diagnosed then finished, no
    payment yet). Returns {"customer","model","watch","watchmaker","ticket"}.
    """
    ctx = service_context(clock=clock)
    ticket = open_ticket(ctx, service_type=service_type, **(ticket_over or {}))
    wm_headers = make_watchmaker_headers(ctx["watchmaker"]["id"])
    get_success_data(api_client.diagnose_ticket(ticket["id"], wm_headers))
    ticket = get_success_data(api_client.finish_ticket(ticket["id"], wm_headers))
    ctx["ticket"] = ticket
    return ctx


def ticket_collected(clock="2026-07-02T00:00:00Z") -> dict:
    """Full chain through COLLECTED (diagnosed, finished, paid 12000, collected).
    A BATTERY ticket quotes exactly the 12000 floor. Returns the context.
    """
    ctx = ticket_ready_unpaid(service_type="BATTERY", clock=clock)
    tid = ctx["ticket"]["id"]
    get_success_data(api_client.pay_ticket(tid, {"amount_cents": 12000}, ASSOC))
    ctx["ticket"] = get_success_data(api_client.collect_ticket(tid, ASSOC))
    return ctx


# ─── Layaway contexts (Tiers 3 & 4) ────────────────────────────────────────
def authenticated_watch_and_customer(list_price_cents=1000000, clock=None,
                                     model_over=None) -> dict:
    """A customer plus one authenticated IN_STOCK watch at a known price.
    Returns {"customer", "model", "watch"}.
    """
    if clock:
        set_clock(clock)
    customer = new_customer()
    model = new_model(**(model_over or {}))
    watch = new_authenticated_watch(model["id"], list_price_cents=list_price_cents)
    return {"customer": customer, "model": model, "watch": watch}


def active_layaway(deposit_cents, term_months, first_due_at, list_price_cents=1000000,
                   clock=None, allocation_controlled=False, plan_over=None) -> dict:
    """An ACTIVE layaway reserving an authenticated watch. Returns
    {"customer","model","watch","plan"}.
    """
    ctx = authenticated_watch_and_customer(
        list_price_cents=list_price_cents, clock=clock,
        model_over={"allocation_controlled": allocation_controlled},
    )
    payload = create_layaway_plan_payload(
        ctx["customer"]["id"], ctx["watch"]["id"], deposit_cents, term_months,
        first_due_at, **(plan_over or {}),
    )
    ctx["plan"] = get_success_data(api_client.create_layaway_plan(payload, ASSOC))
    return ctx


def defaulted_layaway(deposit_cents, term_months, first_due_at, list_price_cents,
                      default_at, allocation_controlled=False,
                      clock="2026-07-02T00:00:00Z") -> dict:
    """An ACTIVE layaway advanced to DEFAULTED (clock moved to default_at, which
    must be >= first_due_at + 10 grace days). Returns {...,"plan"} with the
    defaulted plan.
    """
    ctx = active_layaway(
        deposit_cents, term_months, first_due_at, list_price_cents=list_price_cents,
        clock=clock, allocation_controlled=allocation_controlled,
    )
    set_clock(default_at)
    ctx["plan"] = get_success_data(api_client.default_layaway(ctx["plan"]["id"], ASSOC))
    return ctx


# ─── Waitlist / offer contexts ─────────────────────────────────────────────
def waiting_entry(model_id, customer_id=None, **entry_over) -> dict:
    """Create a WAITING waitlist entry. If customer_id is None, mints a new
    customer. Returns the entry dict.
    """
    if customer_id is None:
        customer_id = new_customer()["id"]
    payload = create_waitlist_entry_payload(customer_id, model_id, **entry_over)
    return get_success_data(api_client.create_waitlist_entry(payload, ASSOC))


def offered_watch(allocation_controlled=True, tier="VIP", deposit_cents=100000,
                  list_price_cents=3500000, clock="2026-07-02T00:00:00Z") -> dict:
    """An authenticated watch on an allocation-controlled model, a waiting VIP
    entry, and the watch offered to it. Returns
    {"customer","model","watch","entry","offer"} where offer is the WaitlistEntry
    returned by POST /watches/{id}/offer.
    """
    if clock:
        set_clock(clock)
    customer = new_customer()
    model = new_model(allocation_controlled=allocation_controlled)
    watch = new_authenticated_watch(model["id"], list_price_cents=list_price_cents)
    entry = waiting_entry(model["id"], customer_id=customer["id"],
                          priority_tier=tier, deposit_cents=deposit_cents)
    offer = get_success_data(api_client.offer_watch(watch["id"], ASSOC))
    return {"customer": customer, "model": model, "watch": watch,
            "entry": entry, "offer": offer}


# ─── Trade-in / consignment contexts ───────────────────────────────────────
def quoted_offer(disposition, customer=None, offer_over=None) -> dict:
    """A QUOTED TradeInOffer. Mints a customer if none supplied. Returns
    {"customer", "offer"}.
    """
    if customer is None:
        customer = new_customer(**(({"kyc_verified": True}) if disposition == "CONSIGNMENT" else {}))
    payload = create_trade_in_offer_payload(customer["id"], disposition, **(offer_over or {}))
    offer = get_success_data(api_client.create_trade_in_offer(payload, ASSOC))
    return {"customer": customer, "offer": offer}


def accepted_offer(disposition, customer=None, offer_over=None) -> dict:
    ctx = quoted_offer(disposition, customer=customer, offer_over=offer_over)
    ctx["offer"] = get_success_data(api_client.accept_trade_in_offer(ctx["offer"]["id"], ASSOC))
    return ctx


def settled_offer(disposition, customer=None, offer_over=None) -> dict:
    """An ACCEPTED offer settled: watch minted, store credit granted. Returns
    {"customer","offer"} with the SETTLED offer (offer.resulting_watch_id set).
    """
    ctx = accepted_offer(disposition, customer=customer, offer_over=offer_over)
    ctx["offer"] = get_success_data(api_client.settle_trade_in_offer(ctx["offer"]["id"], ASSOC))
    return ctx


# ─── Helpers used across suites ────────────────────────────────────────────
def count_in_stock(model_id: str) -> int:
    """COUNT(Watch WHERE model_id==M AND status==IN_STOCK) via the list endpoint."""
    resp = api_client.list_watches(ASSOC, params={"model_id": model_id, "status": "IN_STOCK"})
    body = resp.json()
    return body["meta"]["total_count"]


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ASSOC))


def get_watch(watch_id: str) -> dict:
    return get_success_data(api_client.get_watch(watch_id, ASSOC))


def get_layaway(plan_id: str) -> dict:
    return get_success_data(api_client.get_layaway_plan(plan_id, ASSOC))


def get_waitlist(entry_id: str) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, ASSOC))


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_trade_in_offer(offer_id, ASSOC))
