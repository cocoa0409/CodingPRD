"""Optimistic concurrency, version increments, cascading side effects, and immediate
consistency (queue B: Corner / cross_cutting_complexity_layers + consistency_model).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---- occ_plan_create_stale_episode_version ----
def test_plan_create_stale_episode_version_rejected(api):
    """PRD §2.8: "A request to create a payment plan must carry expected_episode_version
    holding the client's last observed version of the target Episode ... When
    expected_episode_version does not match the episode's current version, the create is
    rejected with ERR_STALE_VERSION (HTTP 412), forcing the client to re-read the episode
    before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_episode_version
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]

    stale_version = validate_success(api.get_episode(ep_id, BILLING))["version"]
    # Adjudication bumps Episode.version, making stale_version out of date.
    validate_success(api.adjudicate_claim(claim_id, f.adjudicate_payload(600000, 540000), BILLING))

    resp = api.create_payment_plan(
        f.create_payment_plan_payload(ep_id, 2, stale_version), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---- occ_booking_create_stale_room_version ----
def test_booking_create_stale_room_version_rejected(api):
    """PRD §2.8: "A request to create a booking must carry expected_room_version holding
    the client's last observed version of the target Room ... when expected_room_version
    does not match the room's current version the create is rejected with
    ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_booking_create_stale_room_version
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    room = fixtures.create_room(turnover_minutes=0)
    stale_room_version = room["version"]

    # First booking advances Room.version.
    fixtures.create_booking(e1["id"], room["id"], stale_room_version,
                            starts_at="2026-02-01T00:00:00Z", ends_at="2026-02-02T00:00:00Z")

    resp = api.create_booking(
        f.create_booking_payload(e2["id"], room["id"], stale_room_version,
                                 starts_at="2026-03-01T00:00:00Z", ends_at="2026-03-02T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---- version_increments_on_mutation ----
def test_version_increments_on_activate(api):
    """PRD §2.4: "an integer version that begins at its initial value and increments by one
    with each mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
    """
    kit, package = fixtures.create_catalog()
    client = fixtures.create_client()
    episode = validate_success(api.create_episode(
        f.create_episode_payload(client["id"], package_code=package["code"], edd="2026-08-01"), INTAKE),
        expected_status=201)
    ep_id = episode["id"]
    assert episode["version"] == 1, f"create version == 1, got {episode['version']}"

    activated = validate_success(api.activate_episode(ep_id, MIDWIFE))
    assert activated["version"] == 2, f"after activate version == 2, got {activated['version']}"


# ---- cascade_write_off_voids_charges ----
def test_write_off_voids_charges_and_zeroes_balance(api):
    """PRD §3.11: "A write-off ... voids every charge on the episode that is in DRAFT or
    BILLED, moving each to VOID."
    PRD §3.10: "Step one sums client responsibility across the episode's charges ...
    excluding charges that are VOID or PAID."

    Design: Corner/cross_cutting_complexity_layers/cascade_write_off_voids_charges
    """
    ctx = fixtures.setup_episode(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    global_charge = fixtures.get_global_fee_charge(ep_id)

    validate_success(api.write_off_episode(ep_id, BILLING))

    charge = validate_success(api.get_charge(global_charge["id"], BILLING))
    assert charge["status"] == "VOID", f"DRAFT GLOBAL_FEE charge -> VOID, got {charge['status']}"
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["financial_status"] == "WRITTEN_OFF"
    assert ep["balance_due_cents"] == 0, f"balance zeroed, got {ep['balance_due_cents']}"


# ---- immediate_balance_visible_in_create_response ----
def test_immediate_balance_visible_in_create_response(api):
    """PRD §3.1: "Finally, opening creates the bundled global-fee charge: a Charge of
    charge_kind GLOBAL_FEE in DRAFT, with amount_cents equal to the snapshotted
    global_fee_cents, and its client_responsibility_cents computed by the estimate variant"
    PRD §3.6: "the client responsibility is the gross global fee multiplied by the self-pay
    estimate fraction of 0.20"

    Design: Corner/consistency_model/immediate_balance_visible_in_create_response
    """
    kit, package = fixtures.create_catalog(global_fee_cents=800000)
    client = fixtures.create_client()
    episode = validate_success(api.create_episode(
        f.create_episode_payload(client["id"], package_code=package["code"], edd="2026-08-01"), INTAKE),
        expected_status=201)
    assert episode["balance_due_cents"] == 160000, \
        f"balance visible in same create response == 160000, got {episode['balance_due_cents']}"
