"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server's database is reset before every individual test.
Fixtures use get_success_data() (lenient validator) internally so setup failures
surface clearly as "Setup failed" rather than confusing assertion errors.

Segregation-of-duties note: both operator roles are opaque (PRD §2.1), but the
recorded operator identities (requested_by_user_id, submitted_by_user_id) ARE
compared at resolve/approve time. Fixtures therefore thread distinct operator
ids through make_registrar_headers / make_leader_headers where it matters.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_registrar_headers,
    make_leader_headers,
)
from .constants import (
    DEFAULT_CHARTER_FEE_CENTS,
    DEFAULT_YOUTH_DUES_CENTS,
    DEFAULT_ADULT_DUES_CENTS,
    DEFAULT_PROGRAM_YEAR,
    LEADER_USER_ID,
    REGISTRAR_USER_ID,
)
from .factories import (
    create_council_payload,
    create_troop_payload,
    create_member_payload,
    create_dues_invoice_payload,
    create_payment_payload,
    create_leader_credential_payload,
    create_advancement_payload,
    create_event_payload,
    create_event_registration_payload,
    create_fundraiser_payload,
    create_fundraiser_order_payload,
    create_booth_reservation_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


# --------------------------------------------------------------------------- Tier 1/2: base hierarchy
def create_council(**overrides) -> dict:
    """Create a Council. Returns the council resource."""
    resp = api_client.create_council(create_council_payload(**overrides), REG)
    return get_success_data(resp)


def create_troop(council_id, **overrides) -> dict:
    """Create a PROVISIONAL troop under a council. Returns the troop resource."""
    resp = api_client.create_troop(council_id, create_troop_payload(**overrides), REG)
    return get_success_data(resp)


def create_council_and_troop(council_overrides=None, troop_overrides=None):
    """Create a council + one PROVISIONAL troop. Returns (council, troop)."""
    council = create_council(**(council_overrides or {}))
    troop = create_troop(council["id"], **(troop_overrides or {}))
    return council, troop


def create_member(troop_id, **overrides) -> dict:
    """Create a PENDING member under a troop. Returns the member resource."""
    resp = api_client.create_member(troop_id, create_member_payload(**overrides), LEAD)
    return get_success_data(resp)


def issue_and_pay_full(member_id, base_cents, issued_on="2026-01-01"):
    """Issue a full-dues invoice (issued_on=Jan -> no proration) and pay it in
    full so the member flips PENDING -> REGISTERED. Returns (invoice, payment)."""
    inv = get_success_data(
        api_client.create_dues_invoice(member_id, create_dues_invoice_payload(issued_on=issued_on), REG)
    )
    pay = get_success_data(
        api_client.create_payment(
            create_payment_payload(inv["id"], member_id, inv["amount_cents"]), REG
        )
    )
    return inv, pay


def create_registered_youth(troop_id, youth_dues_cents=DEFAULT_YOUTH_DUES_CENTS, **member_overrides):
    """Create a YOUTH, issue full Jan dues, pay it -> REGISTERED. Returns the member."""
    member = create_member(troop_id, member_type="YOUTH", **member_overrides)
    issue_and_pay_full(member["id"], youth_dues_cents)
    return get_success_data(api_client.get_member(member["id"], REG))


def create_cleared_trained_leader(troop_id, requested_by=LEADER_USER_ID,
                                  resolver_id=REGISTRAR_USER_ID, **member_overrides):
    """Create an ADULT member, open a credential, clear the bgcheck (by a
    different operator) and complete training so the leader counts toward
    cleared_leader_count. Returns (member, credential)."""
    member = create_member(troop_id, member_type="ADULT", birthdate="1980-01-01", **member_overrides)
    cred = get_success_data(
        api_client.create_leader_credential(
            member["id"], create_leader_credential_payload(requested_by_user_id=requested_by), LEAD
        )
    )
    get_success_data(api_client.start_bgcheck(cred["id"], REG))
    get_success_data(
        api_client.resolve_bgcheck(cred["id"], {"outcome": "CLEAR"}, make_registrar_headers(resolver_id))
    )
    get_success_data(api_client.complete_training(cred["id"], REG))
    return member, get_success_data(api_client.get_leader_credential(cred["id"], REG))


# --------------------------------------------------------------------------- Fundraiser tiers
def create_live_fundraiser(council_id, **overrides) -> dict:
    """Create a fundraiser and take it LIVE. Returns the LIVE fundraiser resource."""
    fr = get_success_data(api_client.create_fundraiser(council_id, create_fundraiser_payload(**overrides), REG))
    fr_live = get_success_data(api_client.go_live_fundraiser(fr["id"], REG))
    return fr_live


def setup_live_fundraiser_with_seller(council_overrides=None, fundraiser_overrides=None):
    """Council + troop + one YOUTH seller (PENDING) + LIVE fundraiser.
    Returns (council, troop, seller, fundraiser)."""
    council, troop = create_council_and_troop(council_overrides=council_overrides)
    seller = create_member(troop["id"], member_type="YOUTH", full_name="Seller")
    fundraiser = create_live_fundraiser(council["id"], **(fundraiser_overrides or {}))
    return council, troop, seller, fundraiser


def place_order(fundraiser_id, troop_id, seller_member_id, units, expected_fundraiser_version):
    """Place a fundraiser order. Returns the PLACED order resource."""
    resp = api_client.create_fundraiser_order(
        create_fundraiser_order_payload(
            fundraiser_id, troop_id, seller_member_id, units, expected_fundraiser_version
        ),
        LEAD,
    )
    return get_success_data(resp)


def place_and_fill_order(fundraiser_id, troop_id, seller_member_id, units, expected_fundraiser_version):
    """Place then fill an order so its commission becomes SETTLED dues and cash/
    liability ledgers post. Returns the FILLED order resource."""
    order = place_order(fundraiser_id, troop_id, seller_member_id, units, expected_fundraiser_version)
    return get_success_data(api_client.fill_order(order["id"], LEAD))


# --------------------------------------------------------------------------- Events
def setup_registered_youth_with_event(council_overrides=None, event_overrides=None):
    """Council + troop + REGISTERED youth + OPEN event. Returns
    (council, troop, member, event)."""
    council, troop = create_council_and_troop(council_overrides=council_overrides)
    member = create_registered_youth(troop["id"])
    event = get_success_data(api_client.create_event(troop["id"], create_event_payload(**(event_overrides or {})), LEAD))
    return council, troop, member, event


def create_hold_registration(event_id, member_id):
    """Create a HOLD registration. Returns the registration resource."""
    return get_success_data(
        api_client.create_event_registration(event_id, create_event_registration_payload(member_id), LEAD)
    )


def create_confirmed_registration(event_id, member_id, requires_health_form):
    """Create a registration and walk it to CONFIRMED (sign permission, file
    health if required, confirm). Returns the registration resource."""
    reg = create_hold_registration(event_id, member_id)
    get_success_data(api_client.sign_permission(reg["id"], LEAD))
    if requires_health_form:
        get_success_data(api_client.file_health(reg["id"], LEAD))
    return get_success_data(api_client.confirm_registration(reg["id"], LEAD))


# --------------------------------------------------------------------------- Advancements
def setup_registered_youth_with_advancement(adv_overrides=None, council_overrides=None):
    """Council + troop + REGISTERED youth + a DRAFT advancement.
    Returns (council, troop, member, advancement)."""
    council, troop = create_council_and_troop(council_overrides=council_overrides)
    member = create_registered_youth(troop["id"])
    adv = get_success_data(
        api_client.create_advancement(member["id"], create_advancement_payload(**(adv_overrides or {})), LEAD)
    )
    return council, troop, member, adv


def sign_all_requirements(advancement_id, count):
    """Sign `count` requirements on an advancement (drives it to 100%)."""
    for _ in range(count):
        get_success_data(api_client.sign_requirement(advancement_id, LEAD))


def setup_submitted_advancement(requirements_total=1, submitter_id=LEADER_USER_ID,
                                council_overrides=None, target="TENDERFOOT", kind="RANK"):
    """Council + troop + REGISTERED youth + advancement fully signed and SUBMITTED
    by `submitter_id`. Returns (council, troop, member, advancement)."""
    council, troop, member, adv = setup_registered_youth_with_advancement(
        adv_overrides={"kind": kind, "target": target, "requirements_total": requirements_total},
        council_overrides=council_overrides,
    )
    sign_all_requirements(adv["id"], requirements_total)
    get_success_data(api_client.submit_advancement(adv["id"], make_leader_headers(submitter_id)))
    return council, troop, member, get_success_data(api_client.get_advancement(adv["id"], REG))


# --------------------------------------------------------------------------- READY + funded troop
def setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=DEFAULT_CHARTER_FEE_CENTS,
                             fill_units=600, extra_youth=0):
    """Build a troop whose recharter_posture is READY and whose SETTLED TROOP_DUES
    covers the charter fee.

    Steps:
      - council + troop + LIVE fundraiser (unit_price 500, plenty of inventory)
      - one FILLED order of `fill_units` (commission settled into TROOP_DUES,
        gross into COUNCIL_CASH) whose seller is one of the registered youth
      - `num_youth` registered youth (the seller plus extras), each paying full
        Jan dues so each is REGISTERED
      - `num_leaders` cleared+trained adult leaders
      - returns dict with ids and the live troop version captured AFTER setup.

    `extra_youth` registers additional youth beyond `num_youth` (used by the OCC
    test which drops one spare youth after reading the version while keeping the
    posture READY).

    Returns dict: {council, troop, fundraiser, seller, order, youth (list),
    leaders (list), troop_version}.
    """
    council = create_council(charter_fee_cents=charter_fee_cents)
    troop = create_troop(council["id"])
    fundraiser = create_live_fundraiser(council["id"], unit_price_cents=500,
                                        unit_cost_cents=200, total_inventory_units=2000)

    seller = create_member(troop["id"], member_type="YOUTH", full_name="Seller")
    order = place_and_fill_order(fundraiser["id"], troop["id"], seller["id"], fill_units, fundraiser["version"])

    # Register the seller (full Jan dues) and the remaining youth.
    issue_and_pay_full(seller["id"], DEFAULT_YOUTH_DUES_CENTS)
    youth = [seller]
    for i in range(1, num_youth):
        m = create_registered_youth(troop["id"], full_name=f"Y{i+1}")
        youth.append(m)

    spares = []
    for i in range(extra_youth):
        m = create_registered_youth(troop["id"], full_name=f"Yspare{i+1}")
        spares.append(m)

    leaders = []
    for i in range(num_leaders):
        member, _cred = create_cleared_trained_leader(troop["id"], full_name=f"L{i+1}")
        leaders.append(member)

    live_troop = get_success_data(api_client.get_troop(troop["id"], REG))
    return {
        "council": get_success_data(api_client.get_council(council["id"], REG)),
        "troop": live_troop,
        "fundraiser": fundraiser,
        "seller": seller,
        "order": order,
        "youth": youth,
        "spares": spares,
        "leaders": leaders,
        "troop_version": live_troop["version"],
    }


# --------------------------------------------------------------------------- Booth
def setup_live_fundraiser_with_booth(location_code="LOC-A",
                                     starts_at="2026-05-01T10:00:00Z",
                                     ends_at="2026-05-01T12:00:00Z"):
    """Council + troop + LIVE fundraiser + one BOOKED booth reservation.
    Returns (council, troop, fundraiser, booth)."""
    council, troop = create_council_and_troop()
    fundraiser = create_live_fundraiser(council["id"], total_inventory_units=1000)
    booth = get_success_data(
        api_client.create_booth_reservation(
            fundraiser["id"],
            create_booth_reservation_payload(troop["id"], location_code, starts_at, ends_at),
            LEAD,
        )
    )
    return council, troop, fundraiser, booth
