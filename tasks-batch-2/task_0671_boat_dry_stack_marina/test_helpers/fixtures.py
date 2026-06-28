"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: BoatOwner is entity_backed:BoatOwnerAccount. After creating
an owner, every ownership-gated BoatOwner call (vessel registration, launch,
service order, waitlist, invoice pay) uses make_boat_owner_headers(owner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_marina_payload, create_forklift_payload, create_rack_payload,
    create_owner_payload, create_vessel_payload, create_insurance_policy_payload,
    create_storage_agreement_payload, create_waitlist_payload,
    promote_waitlist_payload, create_launch_request_payload,
    create_service_order_payload, create_invoice_payload,
)
from .test_users import TEST_USERS, make_boat_owner_headers

DM = TEST_USERS["dock_master_headers"]
BC = TEST_USERS["billing_clerk_headers"]

DEFAULT_CLOCK = "2026-04-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601, headers=DM):
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def reset_clock(to_iso8601=DEFAULT_CLOCK):
    """Reset the logical clock to a known instant. Server starts at the default
    2026-04-01T00:00:00Z, but tests set it explicitly for determinism."""
    return set_clock(to_iso8601)


# --------------------------------------------------------------------------- #
# Tier 1: single-entity creators
# --------------------------------------------------------------------------- #
def create_marina(clock=DEFAULT_CLOCK, **overrides):
    """Reset clock and create a marina. Returns the marina dict."""
    reset_clock(clock)
    return get_success_data(api_client.create_marina(create_marina_payload(**overrides), DM))


def create_forklift(marina_id, **overrides):
    return get_success_data(
        api_client.create_forklift(create_forklift_payload(marina_id, **overrides), DM))


def create_rack(marina_id, **overrides):
    return get_success_data(
        api_client.create_rack(create_rack_payload(marina_id, **overrides), DM))


def create_owner(marina_id, **overrides):
    return get_success_data(
        api_client.create_owner(create_owner_payload(marina_id, **overrides), DM))


def create_vessel(marina_id, owner_id, **overrides):
    """Register a vessel as its owner (entity_backed identity threaded)."""
    return get_success_data(api_client.create_vessel(
        create_vessel_payload(marina_id, owner_id, **overrides),
        make_boat_owner_headers(owner_id)))


def create_verified_policy(vessel_id, **overrides):
    """Submit a COI for the vessel and verify it. Returns the VERIFIED policy."""
    policy = get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(vessel_id, **overrides), BC))
    return get_success_data(api_client.verify_insurance_policy(policy["id"], BC))


def create_submitted_policy(vessel_id, **overrides):
    """Submit (but do not verify) a COI. Returns the SUBMITTED policy."""
    return get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(vessel_id, **overrides), BC))


def rack_version(rack_id):
    return get_success_data(api_client.get_rack(rack_id, DM))["version"]


# --------------------------------------------------------------------------- #
# Tier 2: composite hierarchy
# --------------------------------------------------------------------------- #
def setup_owner_and_vessel(clock=DEFAULT_CLOCK, marina_overrides=None,
                           vessel_overrides=None):
    """marina + owner + OFF_SITE/UNBILLED vessel. Returns (marina, owner, vessel)."""
    marina = create_marina(clock=clock, **(marina_overrides or {}))
    owner = create_owner(marina["id"])
    vessel = create_vessel(marina["id"], owner["id"], **(vessel_overrides or {}))
    return marina, owner, vessel


def setup_pending_agreement(clock=DEFAULT_CLOCK, marina_overrides=None,
                            rack_overrides=None, vessel_overrides=None,
                            with_verified_coi=True):
    """marina + rack + owner + vessel (+ optionally a VERIFIED COI) + a
    PENDING_COI StorageAgreement binding the vessel to the rack.

    Returns dict with keys: marina, rack, owner, vessel, policy, agreement.
    `policy` is None when with_verified_coi is False.
    """
    marina = create_marina(clock=clock, **(marina_overrides or {}))
    rack = create_rack(marina["id"], **(rack_overrides or {}))
    owner = create_owner(marina["id"])
    vessel = create_vessel(marina["id"], owner["id"], **(vessel_overrides or {}))
    policy = create_verified_policy(vessel["id"]) if with_verified_coi else None
    agreement = get_success_data(api_client.create_storage_agreement(
        create_storage_agreement_payload(vessel["id"], rack["id"]), DM))
    return {
        "marina": marina, "rack": rack, "owner": owner, "vessel": vessel,
        "policy": policy, "agreement": agreement,
    }


def setup_active_agreement(clock=DEFAULT_CLOCK, marina_overrides=None,
                           rack_overrides=None, vessel_overrides=None):
    """Full progression to an ACTIVE agreement (vessel RACKED + ACTIVE_STORAGE,
    rack OCCUPIED). Returns dict: marina, rack, owner, vessel, policy, agreement.
    The returned agreement/rack reflect post-activation state (fetched fresh)."""
    ctx = setup_pending_agreement(
        clock=clock, marina_overrides=marina_overrides,
        rack_overrides=rack_overrides, vessel_overrides=vessel_overrides)
    rv = rack_version(ctx["rack"]["id"])
    ctx["agreement"] = get_success_data(api_client.activate_storage_agreement(
        ctx["agreement"]["id"], rv, DM))
    ctx["rack"] = get_success_data(api_client.get_rack(ctx["rack"]["id"], DM))
    ctx["vessel"] = get_success_data(api_client.get_vessel(ctx["vessel"]["id"], DM))
    return ctx


# --------------------------------------------------------------------------- #
# Tier 3: launch lifecycle shortcuts
# --------------------------------------------------------------------------- #
def setup_racked_vessel_with_forklift(clock=DEFAULT_CLOCK, marina_overrides=None,
                                      rack_overrides=None, vessel_overrides=None,
                                      forklift_overrides=None):
    """ACTIVE agreement (vessel RACKED) plus one AVAILABLE forklift in the marina.
    Returns dict: marina, rack, owner, vessel, policy, agreement, forklift."""
    marina = create_marina(clock=clock, **(marina_overrides or {}))
    forklift = create_forklift(marina["id"], **(forklift_overrides or {}))
    rack = create_rack(marina["id"], **(rack_overrides or {}))
    owner = create_owner(marina["id"])
    vessel = create_vessel(marina["id"], owner["id"], **(vessel_overrides or {}))
    policy = create_verified_policy(vessel["id"])
    agreement = get_success_data(api_client.create_storage_agreement(
        create_storage_agreement_payload(vessel["id"], rack["id"]), DM))
    rv = rack_version(rack["id"])
    agreement = get_success_data(
        api_client.activate_storage_agreement(agreement["id"], rv, DM))
    vessel = get_success_data(api_client.get_vessel(vessel["id"], DM))
    rack = get_success_data(api_client.get_rack(rack["id"], DM))
    return {
        "marina": marina, "forklift": forklift, "rack": rack, "owner": owner,
        "vessel": vessel, "policy": policy, "agreement": agreement,
    }


def create_launch(vessel_id, owner_id, **overrides):
    return get_success_data(api_client.create_launch_request(
        create_launch_request_payload(vessel_id, **overrides),
        make_boat_owner_headers(owner_id)))


def setup_scheduled_launch(clock=DEFAULT_CLOCK, vessel_overrides=None,
                           forklift_overrides=None, launch_overrides=None,
                           marina_overrides=None):
    """ACTIVE agreement + forklift + a launch driven through to SCHEDULED.
    Returns dict: marina, forklift, rack, owner, vessel, policy, agreement,
    launch, slot_id."""
    ctx = setup_racked_vessel_with_forklift(
        clock=clock, marina_overrides=marina_overrides,
        vessel_overrides=vessel_overrides, forklift_overrides=forklift_overrides)
    launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"],
                           **(launch_overrides or {}))
    launch = get_success_data(api_client.schedule_launch(launch["id"], DM))
    ctx["launch"] = launch
    ctx["slot_id"] = launch.get("forklift_slot_id")
    return ctx


# --------------------------------------------------------------------------- #
# Tier 4: services & invoices
# --------------------------------------------------------------------------- #
def create_service_order(vessel_id, owner_id, service_kind, **overrides):
    return get_success_data(api_client.create_service_order(
        create_service_order_payload(vessel_id, service_kind, **overrides),
        make_boat_owner_headers(owner_id)))


def issue_invoice(owner_id, source_kind, source_id, **overrides):
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(owner_id, source_kind, source_id, **overrides), BC))


def setup_paid_service_invoice(clock=DEFAULT_CLOCK, service_kind="HAUL_OUT"):
    """owner + vessel + service order + ISSUED invoice + pay it once (PAID).
    Returns dict: marina, owner, vessel, service_order, invoice."""
    marina, owner, vessel = setup_owner_and_vessel(clock=clock)
    so = create_service_order(vessel["id"], owner["id"], service_kind)
    inv = issue_invoice(owner["id"], "SERVICE_ORDER", so["id"])
    inv = get_success_data(
        api_client.pay_invoice(inv["id"], make_boat_owner_headers(owner["id"])))
    return {"marina": marina, "owner": owner, "vessel": vessel,
            "service_order": so, "invoice": inv}


# --------------------------------------------------------------------------- #
# Tier 5: waitlist
# --------------------------------------------------------------------------- #
def join_waitlist(vessel_id, owner_id, **overrides):
    return get_success_data(api_client.create_waitlist_entry(
        create_waitlist_payload(vessel_id, **overrides),
        make_boat_owner_headers(owner_id)))


def setup_offered_waitlist_entry(clock=DEFAULT_CLOCK, size_class="SMALL",
                                 deposit_paid=True, rack_overrides=None):
    """A WAITING entry promoted to OFFERED holding an AVAILABLE rack of the
    requested size class. Returns dict: marina, rack, owner, vessel, entry."""
    marina = create_marina(clock=clock)
    rack = create_rack(marina["id"], **(rack_overrides or {
        "bay_label": "S-1", "size_class": size_class,
        "max_loa_ft": 22.00, "max_beam_ft": 9.00, "max_weight_lbs": 6000,
    }))
    owner = create_owner(marina["id"])
    vessel = create_vessel(marina["id"], owner["id"],
                           loa_ft=20.00, beam_ft=8.00, dry_weight_lbs=3000)
    join_waitlist(vessel["id"], owner["id"],
                  requested_size_class=size_class, deposit_paid=deposit_paid)
    entry = get_success_data(api_client.promote_waitlist(
        promote_waitlist_payload(marina["id"], size_class), DM))
    return {"marina": marina, "rack": rack, "owner": owner,
            "vessel": vessel, "entry": entry}
