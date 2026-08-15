"""Composite setup helpers.

Every helper builds preconditions from scratch against a freshly started
server, using only PRD-declared endpoints. Setup calls go through
get_success_data() so a broken precondition fails with a clear "Setup step
failed" message rather than a confusing assertion error.

Identity threading: Member/Volunteer calls that are ownership-gated always
use make_member_headers(entity["id"]) / make_volunteer_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_checkout_payload,
    create_member_payload,
    create_packing_session_payload,
    create_seed_lot_payload,
    create_seed_variety_payload,
    create_site_payload,
    create_swap_event_payload,
    create_volunteer_payload,
    intake_item_payload,
    pack_payload,
    record_germination_test_payload,
    redeem_credits_payload,
    sign_up_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_volunteer_headers

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0/1: single-entity creation and simple transitions
# ---------------------------------------------------------------------------

def create_site(**overrides) -> dict:
    resp = api_client.create_site(create_site_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_variety(**overrides) -> dict:
    resp = api_client.create_seed_variety(create_seed_variety_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_member(home_site_id: str, **overrides) -> dict:
    resp = api_client.create_member(
        create_member_payload(home_site_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def create_volunteer(approve: bool = True, **overrides) -> dict:
    resp = api_client.create_volunteer(create_volunteer_payload(**overrides), ADMIN)
    volunteer = get_success_data(resp, 201)
    if approve:
        resp = api_client.approve_volunteer(volunteer["id"], ADMIN)
        volunteer = get_success_data(resp, 200)
    return volunteer


def create_seed_lot(variety_id: str, home_site_id: str, **overrides) -> dict:
    resp = api_client.create_seed_lot(
        create_seed_lot_payload(variety_id, home_site_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def submit_for_review(lot_id: str) -> dict:
    return get_success_data(api_client.submit_lot_for_review(lot_id, ADMIN), 200)


def record_test(
    lot_id: str, volunteer_id: str, seeds_tested: int = 100, sprouted_count: int = 90
) -> dict:
    """Volunteer records an assay; recorded_by_volunteer_id comes from the
    caller's X-User-ID (PRD §3.3)."""
    resp = api_client.record_germination_test(
        lot_id,
        record_germination_test_payload(
            seeds_tested=seeds_tested, sprouted_count=sprouted_count
        ),
        make_volunteer_headers(volunteer_id),
    )
    return get_success_data(resp, 201)


def certify_test(test_id: str, outcome: str = "PASS") -> dict:
    resp = api_client.certify_germination_test(test_id, {"outcome": outcome}, ADMIN)
    return get_success_data(resp, 200)


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_seed_lot(lot_id, ADMIN), 200)


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN), 200)


def get_packet(packet_id: str) -> dict:
    return get_success_data(api_client.get_seed_packet(packet_id, ADMIN), 200)


def get_checkout(checkout_id: str) -> dict:
    return get_success_data(api_client.get_checkout(checkout_id, ADMIN), 200)


def get_credit_summary(member_id: str) -> dict:
    return get_success_data(api_client.get_credit_summary(member_id, ADMIN), 200)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp, 200)


def run_sweep() -> dict:
    return get_success_data(api_client.run_daily_sweep(ADMIN), 200)


# ---------------------------------------------------------------------------
# Tier 2: lot lifecycle composites
# ---------------------------------------------------------------------------

def setup_quarantine_lot(
    seeds_received: int = 1000,
    provisional_viability_pct: float = 90.00,
    zone: str = "ZONE_5A",
    label_stock: int = 100,
    site_type: str = "LIBRARY_BRANCH",
    variety_overrides: dict = None,
    lot_code: str = None,
    approve_volunteer: bool = True,
) -> dict:
    """Site + variety + lot moved DRAFT -> QUARANTINE + volunteer.

    Returns {"site", "variety", "lot", "volunteer"}.
    """
    site = create_site(
        site_type=site_type, region_zone=zone, label_stock_count=label_stock
    )
    v_overrides = {"approved_zones": [zone]}
    if variety_overrides:
        v_overrides.update(variety_overrides)
    variety = create_variety(**v_overrides)
    lot_kwargs = {
        "seeds_received": seeds_received,
        "provisional_viability_pct": provisional_viability_pct,
    }
    if lot_code:
        lot_kwargs["lot_code"] = lot_code
    lot = create_seed_lot(variety["id"], site["id"], **lot_kwargs)
    volunteer = create_volunteer(approve=approve_volunteer)
    lot = submit_for_review(lot["id"])
    return {"site": site, "variety": variety, "lot": lot, "volunteer": volunteer}


def setup_active_lot(
    seeds_received: int = 1000,
    provisional_viability_pct: float = 90.00,
    zone: str = "ZONE_5A",
    label_stock: int = 100,
    site_type: str = "LIBRARY_BRANCH",
    variety_overrides: dict = None,
    lot_code: str = None,
    certified_tested: int = 100,
    certified_sprouted: int = 90,
    num_packets: int = 0,
    seeds_per_packet: int = 20,
) -> dict:
    """Full chain: site + variety + lot + volunteer + submit + record +
    certify PASS (lot ACTIVE), then optionally pack `num_packets`.

    Returns {"site", "variety", "lot", "volunteer", "test", "packet_ids"}.
    """
    ctx = setup_quarantine_lot(
        seeds_received=seeds_received,
        provisional_viability_pct=provisional_viability_pct,
        zone=zone,
        label_stock=label_stock,
        site_type=site_type,
        variety_overrides=variety_overrides,
        lot_code=lot_code,
    )
    test = record_test(
        ctx["lot"]["id"],
        ctx["volunteer"]["id"],
        seeds_tested=certified_tested,
        sprouted_count=certified_sprouted,
    )
    certify_test(test["id"], "PASS")
    ctx["test"] = test
    ctx["lot"] = get_lot(ctx["lot"]["id"])
    packet_ids = []
    if num_packets:
        packet_ids = pack_packets(
            ctx["lot"]["id"],
            ctx["volunteer"]["id"],
            packet_count=num_packets,
            seeds_per_packet=seeds_per_packet,
        )
        ctx["lot"] = get_lot(ctx["lot"]["id"])
    ctx["packet_ids"] = packet_ids
    return ctx


def pack_packets(
    lot_id: str, volunteer_id: str, packet_count: int, seeds_per_packet: int
) -> list:
    """Volunteer packs packets; returns the created packet_ids (from the pack
    response itself — no list-ordering assumptions)."""
    resp = api_client.pack_seed_lot(
        lot_id,
        pack_payload(packet_count=packet_count, seeds_per_packet=seeds_per_packet),
        make_volunteer_headers(volunteer_id),
    )
    data = get_success_data(resp, 201)
    assert data["created_count"] == packet_count, (
        f"Setup failed: pack created {data['created_count']} != {packet_count}"
    )
    return list(data["packet_ids"])


# ---------------------------------------------------------------------------
# Tier 3: checkout lifecycle composites
# ---------------------------------------------------------------------------

def borrow_packet(member: dict, packet_id: str) -> dict:
    """Member borrows a packet for themselves (member_id == X-User-ID)."""
    resp = api_client.create_checkout(
        create_checkout_payload(member["id"], packet_id),
        make_member_headers(member["id"]),
    )
    return get_success_data(resp, 201)


def borrow_packet_as_admin(member_id: str, packet_id: str) -> dict:
    resp = api_client.create_checkout(
        create_checkout_payload(member_id, packet_id), ADMIN
    )
    return get_success_data(resp, 201)


def return_checkout_as_member(checkout_id: str, member_id: str) -> dict:
    resp = api_client.return_checkout(checkout_id, make_member_headers(member_id))
    return get_success_data(resp, 200)


def verify_return(checkout_id: str) -> dict:
    return get_success_data(api_client.verify_return(checkout_id, ADMIN), 200)


def borrow_return_verify(member: dict, packet_id: str) -> dict:
    """Full happy path: borrow -> return -> verify. Returns VERIFIED checkout."""
    checkout = borrow_packet(member, packet_id)
    return_checkout_as_member(checkout["id"], member["id"])
    return verify_return(checkout["id"])


def write_off_overdue_checkout(checkout_id: str, member_id: str) -> dict:
    """Dispute an OVERDUE checkout as the owning member, then write it off as
    admin. Returns the WRITTEN_OFF checkout."""
    resp = api_client.dispute_checkout(
        checkout_id, {"reason": "lost"}, make_member_headers(member_id)
    )
    get_success_data(resp, 200)
    resp = api_client.resolve_dispute(checkout_id, {"outcome": "WRITE_OFF"}, ADMIN)
    return get_success_data(resp, 200)


def make_checkouts_overdue(iso: str = "2026-09-01T00:00:00Z") -> dict:
    """Advance the logical clock past the default due date and run the sweep.
    Returns the sweep report."""
    set_clock(iso)
    return run_sweep()


# ---------------------------------------------------------------------------
# Tier 4: member standing / threshold targeting
# ---------------------------------------------------------------------------

def setup_member_with_terminal_history(
    verified: int, written_off: int, zone: str = "ZONE_5A"
) -> dict:
    """Active lot with enough packets + a member holding exactly
    `verified` VERIFIED and `written_off` WRITTEN_OFF checkouts.

    Write-offs go through overdue -> dispute -> WRITE_OFF. Returns
    {"site", "variety", "lot", "volunteer", "packet_ids", "member",
    "remaining_packet_ids"} where remaining_packet_ids are still AVAILABLE.
    """
    total = verified + written_off
    ctx = setup_active_lot(
        zone=zone,
        num_packets=total + 6,
        seeds_per_packet=20,
        seeds_received=1000,
        certified_sprouted=90,
    )
    member = create_member(ctx["site"]["id"])
    packets = list(ctx["packet_ids"])
    for packet_id in packets[:verified]:
        borrow_return_verify(member, packet_id)
    wo_packets = packets[verified:verified + written_off]
    wo_checkouts = [borrow_packet(member, pid)["id"] for pid in wo_packets]
    if wo_checkouts:
        make_checkouts_overdue()
        for cid in wo_checkouts:
            write_off_overdue_checkout(cid, member["id"])
    ctx["member"] = member
    ctx["remaining_packet_ids"] = packets[total:]
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: swap events, intake items, credits
# ---------------------------------------------------------------------------

def create_swap_event(site_id: str, **overrides) -> dict:
    resp = api_client.create_swap_event(
        create_swap_event_payload(site_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def publish_event(event_id: str) -> dict:
    return get_success_data(api_client.publish_swap_event(event_id, ADMIN), 200)


def open_event_intake(event_id: str) -> dict:
    return get_success_data(api_client.open_intake(event_id, ADMIN), 200)


def setup_intake_open_event(
    zone: str = "ZONE_5A",
    start_at: str = "2026-09-05T10:00:00Z",
    end_at: str = "2026-09-05T12:00:00Z",
    site_type: str = "GARDEN",
) -> dict:
    """Site + event published and intake-opened. Returns {"site", "event"}."""
    site = create_site(site_type=site_type, region_zone=zone)
    event = create_swap_event(site["id"], start_at=start_at, end_at=end_at)
    publish_event(event["id"])
    event = open_event_intake(event["id"])
    return {"site": site, "event": event}


def submit_item(
    event_id: str,
    member_id: str,
    variety_id: str,
    item_type: str = "SEED_PACKET",
    condition: str = "GOOD",
) -> dict:
    """Member submits an intake item for themselves."""
    resp = api_client.submit_intake_item(
        event_id,
        intake_item_payload(
            member_id, variety_id, item_type=item_type, condition=condition
        ),
        make_member_headers(member_id),
    )
    return get_success_data(resp, 201)


def accept_item(item_id: str) -> dict:
    resp = api_client.screen_intake_item(item_id, {"outcome": "ACCEPT"}, ADMIN)
    return get_success_data(resp, 200)


def submit_and_accept(
    event_id: str,
    member_id: str,
    variety_id: str,
    item_type: str = "SEED_PACKET",
    condition: str = "GOOD",
) -> dict:
    item = submit_item(event_id, member_id, variety_id, item_type, condition)
    return accept_item(item["id"])


def redeem(event_id: str, member_id: str, credits: int) -> dict:
    resp = api_client.redeem_credits(
        event_id,
        redeem_credits_payload(member_id, credits),
        make_member_headers(member_id),
    )
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 2: packing sessions
# ---------------------------------------------------------------------------

def create_packing_session(site_id: str, **overrides) -> dict:
    resp = api_client.create_packing_session(
        create_packing_session_payload(site_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def sign_up(session_id: str, volunteer_id: str) -> dict:
    resp = api_client.sign_up_volunteer(
        session_id,
        sign_up_payload(volunteer_id),
        make_volunteer_headers(volunteer_id),
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Convenience read helpers returning validated payloads
# ---------------------------------------------------------------------------

def read_member(member_id: str) -> dict:
    return validate_success(api_client.get_member(member_id, ADMIN), 200)


def read_lot(lot_id: str) -> dict:
    return validate_success(api_client.get_seed_lot(lot_id, ADMIN), 200)


def read_site(site_id: str) -> dict:
    return validate_success(api_client.get_site(site_id, ADMIN), 200)
