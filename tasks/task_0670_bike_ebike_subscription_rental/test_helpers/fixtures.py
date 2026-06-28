"""Composite setup helpers.

Each fixture builds its preconditions from scratch using only PRD-declared endpoints,
since the server database is reset before every test. Fixtures use get_success_data()
(lenient) for setup steps so a setup failure surfaces clearly as "Setup failed".

Identity threading: Subscriber / FleetManager are entity_backed:Account, so every
ownership-gated call uses make_subscriber_headers(account_id) /
make_fleet_manager_headers(account_id) with the real Account.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_subscriber_headers,
    make_fleet_manager_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    make_anonymous_headers,
)
from .factories import (
    create_bike_model_payload,
    create_bike_payload,
    create_account_payload,
    create_rental_payload,
    create_delivery_payload,
    request_return_payload,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()
ANON = make_anonymous_headers()


# ---------------------------------------------------------------------------
# Primitive setup steps
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the logical clock; returns nothing meaningful (data is null)."""
    return api_client.set_clock(iso, OPS)


def create_model(**overrides) -> dict:
    """Create a BikeModel (OpsAdmin). Returns the model object."""
    payload = create_bike_model_payload(**overrides)
    return get_success_data(api_client.create_bike_model(payload, OPS))


def add_bike(model_id: str, serial_number: str) -> dict:
    """Add a physical bike to a model (OpsAdmin). Returns the bike object."""
    return get_success_data(
        api_client.create_bike(create_bike_payload(model_id, serial_number), OPS)
    )


def add_bikes(model_id: str, count: int, prefix: str = "S") -> list:
    """Add `count` bikes; returns the list of bike objects."""
    return [add_bike(model_id, f"{prefix}-{i + 1}") for i in range(count)]


def create_account(account_type: str = "SUBSCRIBER", email: str = "sam@x.com",
                   display_name: str = "Sam", rental_cap: int = 1) -> dict:
    """Open an account (Anonymous). Returns the account object."""
    payload = create_account_payload(
        account_type=account_type, email=email,
        display_name=display_name, rental_cap=rental_cap,
    )
    return get_success_data(api_client.create_account(payload, ANON))


def read_model_version(model_id: str, account_id: str, role: str = "SUBSCRIBER") -> int:
    """Read the current BikeModel.version as the holding account would observe it."""
    headers = (make_subscriber_headers(account_id) if role == "SUBSCRIBER"
               else make_fleet_manager_headers(account_id))
    data = get_success_data(api_client.get_bike_model(model_id, headers))
    return data["version"]


def reserve(account_id: str, model_id: str, expected_model_version: int,
            rental_mode: str = "MONTHLY", return_due_clock: str = "2027-06-01T00:00:00Z",
            role: str = "SUBSCRIBER") -> dict:
    """Reserve a bike (Subscriber/FleetManager). Returns the RentalAgreement."""
    headers = (make_subscriber_headers(account_id) if role == "SUBSCRIBER"
               else make_fleet_manager_headers(account_id))
    payload = create_rental_payload(
        account_id, model_id, expected_model_version,
        rental_mode=rental_mode, return_due_clock=return_due_clock,
    )
    return get_success_data(api_client.create_rental(payload, headers))


def schedule_and_complete_initial_delivery(rental_id: str,
                                           window_start="2026-06-01T08:00:00Z",
                                           window_end="2026-06-01T12:00:00Z") -> dict:
    """Schedule the INITIAL delivery (OpsAdmin) and complete it (FieldTech).
    Returns the completed delivery object."""
    delivery = get_success_data(
        api_client.create_delivery(
            create_delivery_payload(
                rental_id, "INITIAL",
                window_start_clock=window_start, window_end_clock=window_end,
            ),
            OPS,
        )
    )
    return get_success_data(api_client.complete_delivery(delivery["id"], TECH))


def activate(rental_id: str, account_id: str, role: str = "SUBSCRIBER") -> dict:
    """Activate a DELIVERED rental. Returns the updated RentalAgreement."""
    headers = (make_subscriber_headers(account_id) if role == "SUBSCRIBER"
               else make_fleet_manager_headers(account_id))
    return get_success_data(api_client.activate_rental(rental_id, headers))


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: reach a target lifecycle state
# ---------------------------------------------------------------------------
def setup_reserved_rental(rental_mode: str = "MONTHLY",
                          return_due_clock: str = "2027-06-01T00:00:00Z",
                          deposit_cents: int = 10000, fleet_size: int = 2,
                          num_bikes: int = 1, model_overrides=None,
                          clock: str = "2026-06-01T00:00:00Z",
                          rental_cap: int = 1, account_type: str = "SUBSCRIBER"):
    """Reach a RESERVED rental (no delivery yet).

    Returns dict with keys: model, bikes, account, rental, role.
    """
    set_clock(clock)
    mo = model_overrides or {}
    model = create_model(deposit_cents=deposit_cents, fleet_size=fleet_size, **mo)
    bikes = add_bikes(model["id"], num_bikes)
    role = "FLEET" if account_type == "FLEET" else "SUBSCRIBER"
    email = "fleet@x.com" if account_type == "FLEET" else "sam@x.com"
    display = "RiderCo" if account_type == "FLEET" else "Sam"
    account = create_account(account_type=account_type, email=email,
                             display_name=display, rental_cap=rental_cap)
    role_kw = "FLEET" if account_type == "FLEET" else "SUBSCRIBER"
    mv = read_model_version(model["id"], account["id"], role=role_kw)
    rental = reserve(account["id"], model["id"], mv, rental_mode=rental_mode,
                     return_due_clock=return_due_clock, role=role_kw)
    return {"model": model, "bikes": bikes, "account": account,
            "rental": rental, "role": role_kw}


def setup_active_rental(rental_mode: str = "MONTHLY",
                        return_due_clock: str = "2027-06-01T00:00:00Z",
                        deposit_cents: int = 10000, fleet_size: int = 2,
                        num_bikes: int = 1, model_overrides=None,
                        clock: str = "2026-06-01T00:00:00Z",
                        account_type: str = "SUBSCRIBER",
                        delivery_window=("2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z")):
    """Reach an ACTIVE rental (reserved -> delivered -> active).

    Returns dict with keys: model, bikes, account, rental, role.
    The returned `rental` is the activation response (lifecycle ACTIVE).
    """
    ctx = setup_reserved_rental(
        rental_mode=rental_mode, return_due_clock=return_due_clock,
        deposit_cents=deposit_cents, fleet_size=fleet_size, num_bikes=num_bikes,
        model_overrides=model_overrides, clock=clock, account_type=account_type,
    )
    schedule_and_complete_initial_delivery(
        ctx["rental"]["id"],
        window_start=delivery_window[0], window_end=delivery_window[1],
    )
    ctx["rental"] = activate(ctx["rental"]["id"], ctx["account"]["id"], role=ctx["role"])
    return ctx


def setup_return_requested_rental(rental_mode: str = "DAILY",
                                  return_due_clock: str = "2026-06-10T00:00:00Z",
                                  deposit_cents: int = 20000, **kwargs):
    """Reach a RETURN_REQUESTED rental (active -> request-return).

    Returns the same dict as setup_active_rental, with `rental` updated.
    """
    ctx = setup_active_rental(rental_mode=rental_mode, return_due_clock=return_due_clock,
                              deposit_cents=deposit_cents, **kwargs)
    headers = (make_subscriber_headers(ctx["account"]["id"]) if ctx["role"] == "SUBSCRIBER"
               else make_fleet_manager_headers(ctx["account"]["id"]))
    ctx["rental"] = get_success_data(
        api_client.request_return(ctx["rental"]["id"], request_return_payload(), headers)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts on subordinate entities
# ---------------------------------------------------------------------------
def setup_resolved_ticket(severity: str = "MINOR", issue_type: str = "BRAKE",
                          **active_kwargs):
    """ACTIVE rental + a ticket walked OPEN -> IN_PROGRESS -> RESOLVED.

    Returns dict: {ctx, ticket} where ctx is the setup_active_rental dict.
    For a CRITICAL severity the rental will be IN_SERVICE; for non-critical it stays ACTIVE.
    """
    ctx = setup_active_rental(**active_kwargs)
    acct_id = ctx["account"]["id"]
    sub = (make_subscriber_headers(acct_id) if ctx["role"] == "SUBSCRIBER"
           else make_fleet_manager_headers(acct_id))
    ticket = get_success_data(api_client.create_service_ticket(
        {"rental_id": ctx["rental"]["id"], "issue_type": issue_type,
         "severity": severity, "description": "issue"}, sub))
    get_success_data(api_client.start_service_ticket(ticket["id"], TECH))
    ticket = get_success_data(api_client.resolve_service_ticket(
        ticket["id"], {"resolution_note": "resolved"}, TECH))
    return {"ctx": ctx, "ticket": ticket}


def setup_under_review_claim(claim_type: str = "DAMAGE",
                             claimed_amount_cents: int = 20000,
                             incident_clock: str = "2026-06-02T00:00:00Z",
                             **active_kwargs):
    """ACTIVE rental + a claim FILED then moved to UNDER_REVIEW.

    Returns dict: {ctx, claim}.
    """
    ctx = setup_active_rental(**active_kwargs)
    acct_id = ctx["account"]["id"]
    sub = (make_subscriber_headers(acct_id) if ctx["role"] == "SUBSCRIBER"
           else make_fleet_manager_headers(acct_id))
    claim = get_success_data(api_client.create_coverage_claim(
        {"rental_id": ctx["rental"]["id"], "claim_type": claim_type,
         "incident_clock": incident_clock,
         "claimed_amount_cents": claimed_amount_cents}, sub))
    claim = get_success_data(api_client.review_coverage_claim(claim["id"], OPS))
    return {"ctx": ctx, "claim": claim}


def setup_quoted_buyout(expires_at_clock: str = "2026-12-01T00:00:00Z",
                        **active_kwargs):
    """ACTIVE MONTHLY rental + a QUOTED buyout offer.

    Returns dict: {ctx, offer}.
    """
    active_kwargs.setdefault("rental_mode", "MONTHLY")
    ctx = setup_active_rental(**active_kwargs)
    acct_id = ctx["account"]["id"]
    sub = (make_subscriber_headers(acct_id) if ctx["role"] == "SUBSCRIBER"
           else make_fleet_manager_headers(acct_id))
    offer = get_success_data(api_client.create_buyout_offer(
        ctx["rental"]["id"], {"expires_at_clock": expires_at_clock}, sub))
    return {"ctx": ctx, "offer": offer}


def advance_cycles(rental_id: str, n: int):
    """Call advance-cycle n times (OpsAdmin). Returns the last response data."""
    last = None
    for _ in range(n):
        last = get_success_data(api_client.advance_cycle(rental_id, OPS))
    return last


# ---------------------------------------------------------------------------
# Tier 4: accumulation / multiple-line fleet setups
# ---------------------------------------------------------------------------
def setup_fleet_with_active_monthly_lines(n_lines: int, monthly_fee_cents: int = 8333,
                                          model_class: str = "STANDARD",
                                          rental_cap: int = 6,
                                          clock: str = "2026-06-01T00:00:00Z"):
    """FLEET account with exactly n_lines ACTIVE MONTHLY rentals on one model.

    Each rental is reserved with a freshly-read (current) model version, delivered,
    and activated, so every line counts toward the fleet invoice. Returns dict:
    {model, account, rentals}.
    """
    set_clock(clock)
    model = create_model(model_class=model_class, monthly_fee_cents=monthly_fee_cents,
                         fleet_size=n_lines + 1)
    add_bikes(model["id"], n_lines)
    account = create_account(account_type="FLEET", email="fleet@x.com",
                             display_name="RiderCo", rental_cap=rental_cap)
    fm = make_fleet_manager_headers(account["id"])
    rentals = []
    for i in range(n_lines):
        mv = get_success_data(api_client.get_bike_model(model["id"], fm))["version"]
        rental = get_success_data(api_client.create_rental(
            create_rental_payload(account["id"], model["id"], mv,
                                  rental_mode="MONTHLY",
                                  return_due_clock="2027-06-01T00:00:00Z"), fm))
        delivery = get_success_data(api_client.create_delivery(
            create_delivery_payload(rental["id"], "INITIAL", address="3 C St",
                                    window_start_clock="2026-06-01T08:00:00Z",
                                    window_end_clock="2026-06-01T09:00:00Z"), OPS))
        get_success_data(api_client.complete_delivery(delivery["id"], TECH))
        get_success_data(api_client.activate_rental(rental["id"], fm))
        rentals.append(rental)
    return {"model": model, "account": account, "rentals": rentals}
