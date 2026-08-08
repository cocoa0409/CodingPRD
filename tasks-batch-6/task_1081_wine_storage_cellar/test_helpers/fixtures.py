"""Composite setup helpers for the Wine-Storage Cellar API.

All helpers use get_success_data() (lenient) internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch using only PRD-declared endpoints, because the
test harness restarts the server (empty DB) before every individual test.

Identity threading: CellarMember is entity-backed, so any ownership-gated call uses
make_cellar_member_headers(member_id) with the real member id. Appraiser create and
finalize use two distinct identities to satisfy segregation of duties.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_cellar_member_headers,
    make_appraiser_headers,
)
from .constants import APPRAISER_ALPHA, APPRAISER_BETA
from . import factories

MGR = TEST_USERS["cellar_manager_headers"]
BROKER = TEST_USERS["auction_broker_headers"]
AGENT = TEST_USERS["insurance_agent_headers"]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, MGR))


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #
def onboard_member(api, tier="STANDARD", activate=True, **overrides):
    """Create a member; activate to ACTIVE unless activate=False."""
    payload = factories.create_member_payload(membership_tier=tier, **overrides)
    member = get_success_data(api.create_member(payload, MGR))
    if activate:
        member = get_success_data(api.activate_member(member["id"], MGR))
    return member


# --------------------------------------------------------------------------- #
# Lockers
# --------------------------------------------------------------------------- #
def create_locker(api, size_tier="MEDIUM", climate_zone="RED", capacity=3, **overrides):
    payload = factories.create_locker_payload(
        size_tier=size_tier, climate_zone=climate_zone, capacity_bottles=capacity, **overrides
    )
    return get_success_data(api.create_locker(payload, MGR))


def assign_locker(api, locker_id, member_id):
    return get_success_data(api.assign_locker(locker_id, {"member_id": member_id}, MGR))


def setup_active_member_with_locker(
    api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="STANDARD"
):
    """ACTIVE member + one ASSIGNED locker of the given shape. Returns (member, locker)."""
    member = onboard_member(api, tier=tier)
    locker = create_locker(api, size_tier=size_tier, climate_zone=climate_zone, capacity=capacity)
    locker = assign_locker(api, locker["id"], member["id"])
    return member, locker


# --------------------------------------------------------------------------- #
# Bottles
# --------------------------------------------------------------------------- #
def store_bottle(api, locker_id, member_id, **overrides):
    """Deposit a STORED bottle into the member's assigned locker (member-owned call)."""
    payload = factories.create_bottle_payload(locker_id=locker_id, **overrides)
    return get_success_data(
        api.create_bottle(payload, make_cellar_member_headers(member_id))
    )


def setup_member_locker_bottle(
    api,
    size_tier="MEDIUM",
    climate_zone="RED",
    capacity=3,
    tier="STANDARD",
    bottle_overrides=None,
):
    """ACTIVE member + ASSIGNED locker + one STORED bottle. Returns (member, locker, bottle)."""
    member, locker = setup_active_member_with_locker(
        api, size_tier=size_tier, climate_zone=climate_zone, capacity=capacity, tier=tier
    )
    bottle = store_bottle(api, locker["id"], member["id"], **(bottle_overrides or {}))
    return member, locker, bottle


# --------------------------------------------------------------------------- #
# Appraisals
# --------------------------------------------------------------------------- #
def create_appraisal(api, bottle_id, method="MARKET_COMPARABLE", base_value_cents=1_000_000,
                     creator=APPRAISER_ALPHA):
    payload = factories.create_appraisal_payload(
        bottle_id=bottle_id, method=method, base_value_cents=base_value_cents
    )
    return get_success_data(api.create_appraisal(payload, make_appraiser_headers(creator)))


def finalize_appraisal(api, appraisal_id, expected_bottle_version, finalizer=APPRAISER_BETA):
    return get_success_data(
        api.finalize_appraisal(
            appraisal_id,
            {"expected_bottle_version": expected_bottle_version},
            make_appraiser_headers(finalizer),
        )
    )


def create_finalized_appraisal(api, bottle, method="MARKET_COMPARABLE", base_value_cents=700):
    """Create + finalize an appraisal against `bottle` (a bottle dict carrying version).
    Returns the finalized appraisal. Satisfies SoD via alpha creator / beta finalizer."""
    appraisal = create_appraisal(api, bottle["id"], method=method, base_value_cents=base_value_cents)
    return finalize_appraisal(api, appraisal["id"], bottle["version"])


def setup_bottle_with_finalized_appraisal(
    api, method="MARKET_COMPARABLE", base_value_cents=700, provenance_status="DOCUMENTED",
    capacity=3, size_tier="MEDIUM", climate_zone="RED", tier="PREMIUM",
):
    """ACTIVE member + ASSIGNED locker + one STORED bottle whose appraised_value_cents
    has been set via a FINALIZED appraisal. Returns (member, locker, bottle_after)."""
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier=size_tier, climate_zone=climate_zone, capacity=capacity, tier=tier,
        bottle_overrides={"provenance_status": provenance_status},
    )
    create_finalized_appraisal(api, bottle, method=method, base_value_cents=base_value_cents)
    bottle_after = get_success_data(api.get_bottle(bottle["id"], MGR))
    return member, locker, bottle_after


# --------------------------------------------------------------------------- #
# Movement requests
# --------------------------------------------------------------------------- #
def create_intake_request(api, member_id, locker_id, quantity):
    payload = factories.create_movement_request_payload(
        member_id=member_id, locker_id=locker_id, request_type="INTAKE", quantity=quantity
    )
    return get_success_data(
        api.create_movement_request(payload, make_cellar_member_headers(member_id))
    )


def create_withdrawal_request(api, member_id, locker_id, bottle_ids):
    payload = factories.create_movement_request_payload(
        member_id=member_id, locker_id=locker_id, request_type="WITHDRAWAL",
        quantity=len(bottle_ids), bottle_ids=bottle_ids,
    )
    return get_success_data(
        api.create_movement_request(payload, make_cellar_member_headers(member_id))
    )


def withdraw_bottles(api, member_id, locker_id, bottle_ids):
    """Create + approve + complete a WITHDRAWAL so the listed bottles become WITHDRAWN."""
    mr = create_withdrawal_request(api, member_id, locker_id, bottle_ids)
    get_success_data(api.approve_movement_request(mr["id"], MGR))
    get_success_data(api.complete_movement_request(mr["id"], MGR))
    return mr


# --------------------------------------------------------------------------- #
# Consignments
# --------------------------------------------------------------------------- #
def open_consignment(api, member_id, bottle_id, reserve_price_cents):
    payload = factories.create_consignment_payload(
        bottle_id=bottle_id, reserve_price_cents=reserve_price_cents
    )
    return get_success_data(
        api.create_consignment(payload, make_cellar_member_headers(member_id))
    )


def setup_listed_consignment(api, reserve_price_cents=3_000_000, base_value_cents=None):
    """DOCUMENTED STORED bottle opened + LISTED. Returns (member, locker, bottle, consignment)."""
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents)
    cn = get_success_data(api.list_consignment(cn["id"], BROKER))
    return member, locker, bottle, cn


def setup_offered_consignment(api, offer_price_cents, reserve_price_cents=3_000_000):
    """Listed then OFFERED at offer_price_cents. Returns (member, locker, bottle, consignment)."""
    member, locker, bottle, cn = setup_listed_consignment(
        api, reserve_price_cents=reserve_price_cents
    )
    cn = get_success_data(
        api.offer_consignment(cn["id"], {"offer_price_cents": offer_price_cents}, BROKER)
    )
    return member, locker, bottle, cn


def setup_accepted_consignment(api, offer_price_cents, reserve_price_cents=3_000_000, capacity=3):
    """Listed, offered, and ACCEPTED. Returns (member, locker, bottle, consignment)."""
    member = onboard_member(api, tier="PREMIUM")
    locker = create_locker(api, size_tier="MEDIUM", climate_zone="RED", capacity=capacity)
    locker = assign_locker(api, locker["id"], member["id"])
    bottle = store_bottle(api, locker["id"], member["id"], provenance_status="DOCUMENTED")
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents)
    cn = get_success_data(api.list_consignment(cn["id"], BROKER))
    cn = get_success_data(
        api.offer_consignment(cn["id"], {"offer_price_cents": offer_price_cents}, BROKER)
    )
    cn = get_success_data(api.accept_consignment(cn["id"], make_cellar_member_headers(member["id"])))
    return member, locker, bottle, cn


# --------------------------------------------------------------------------- #
# Insurance policies
# --------------------------------------------------------------------------- #
def quote_policy(api, member_id, covered_bottle_ids, coverage_tier="FULL"):
    payload = factories.create_insurance_policy_payload(
        member_id=member_id, coverage_tier=coverage_tier, covered_bottle_ids=covered_bottle_ids
    )
    return get_success_data(api.create_insurance_policy(payload, AGENT))


# --------------------------------------------------------------------------- #
# Delivery orders
# --------------------------------------------------------------------------- #
def schedule_delivery(api, member_id, bottle_ids, courier_ref, slot_start, slot_end):
    payload = factories.create_delivery_order_payload(
        member_id=member_id, bottle_ids=bottle_ids, courier_ref=courier_ref,
        slot_start=slot_start, slot_end=slot_end,
    )
    return get_success_data(api.create_delivery_order(payload, MGR))


# --------------------------------------------------------------------------- #
# Maintenance windows
# --------------------------------------------------------------------------- #
def schedule_maintenance(api, locker_id, window_start, window_end, reason="service"):
    payload = factories.create_maintenance_window_payload(
        locker_id=locker_id, window_start=window_start, window_end=window_end, reason=reason
    )
    return get_success_data(api.create_maintenance_window(payload, MGR))


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def post_ledger_adjustment(api, member_id, entry_type, amount_cents, reason="adj"):
    payload = factories.create_ledger_adjustment_payload(
        entry_type=entry_type, amount_cents=amount_cents, reason=reason
    )
    return get_success_data(api.create_ledger_adjustment(member_id, payload, MGR))
