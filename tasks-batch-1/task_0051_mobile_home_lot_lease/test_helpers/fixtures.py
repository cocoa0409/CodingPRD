"""Composite setup helpers.

The dominant precondition across the suite is an OCCUPIED lot reached through:

    community -> lot -> resident -> lease -> activate

with several workflows layered on top (rent-schedule accept/contest/apply,
utility apportionment, eviction notice/cure/adjudicate, conversion vote
open/ballot/tally). These helpers encapsulate those chains so each test focuses
on the behavior under assertion.

Every helper uses get_success_data() (lenient) for setup steps, so a broken
precondition surfaces as a clear "Setup step failed" rather than a confusing
downstream assertion error. Identity is threaded correctly: Resident calls use
make_resident_headers(resident_id) with the real Resident.id so ownership checks
resolve; ParkManager/HousingAuthority are opaque.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_resident_headers
from . import factories as f

MGR = TEST_USERS["manager_headers"]


# ─── Clock ─────────────────────────────────────────────────────

def set_clock(iso, api=api_client):
    """Set the test-driving clock; returns nothing meaningful."""
    return api.set_clock(iso, MGR)


# ─── Primitive creators ────────────────────────────────────────

def create_community(api=api_client, **overrides):
    resp = api.create_community(f.create_community_payload(**overrides), MGR)
    return get_success_data(resp)


def create_lot(community_id, api=api_client, **overrides):
    resp = api.create_lot(f.create_lot_payload(community_id, **overrides), MGR)
    return get_success_data(resp)


def create_resident(community_id, api=api_client, **overrides):
    resp = api.create_resident(f.create_resident_payload(community_id, **overrides), MGR)
    return get_success_data(resp)


def create_lease(lot_id, resident_id, api=api_client, **overrides):
    resp = api.create_lease(
        f.create_lease_payload(lot_id, resident_id, **overrides), MGR
    )
    return get_success_data(resp)


def activate_lease(lease_id, api=api_client, payload=None):
    resp = api.activate_lease(lease_id, MGR, payload=payload)
    return get_success_data(resp)


# ─── Occupancy ─────────────────────────────────────────────────

def setup_occupied_lot(api=api_client, community_overrides=None, lot_overrides=None,
                       resident_overrides=None, lease_overrides=None):
    """community -> lot -> resident -> PENDING lease -> ACTIVE (lot OCCUPIED).

    Returns (community, lot, resident, lease) with the lease ACTIVE. Re-fetches
    the lot so its post-activation status/version are current.
    """
    community = create_community(api, **(community_overrides or {}))
    lot = create_lot(community["id"], api, **(lot_overrides or {}))
    resident = create_resident(community["id"], api, **(resident_overrides or {}))
    lease = create_lease(lot["id"], resident["id"], api, **(lease_overrides or {}))
    activate_lease(lease["id"], api)
    lot = get_success_data(api.get_lot(lot["id"], MGR))
    lease = get_success_data(api.get_lease(lease["id"], MGR))
    return community, lot, resident, lease


def setup_community_with_n_occupied_lots(specs, api=api_client, community_overrides=None):
    """Build a community with N occupied lots.

    `specs` is a list of dicts, each optionally carrying lot_overrides /
    resident_overrides keys (e.g. {"lot": {"lot_number": "A1"}, "resident":
    {"household_size": 4}}). Lots are created in list order (so created_at
    ordering matches list order). Returns (community, [(lot, resident, lease), ...]).
    """
    community = create_community(api, **(community_overrides or {}))
    rows = []
    for i, spec in enumerate(specs):
        lot_ov = dict(spec.get("lot", {}))
        lot_ov.setdefault("lot_number", f"L{i+1}")
        lot = create_lot(community["id"], api, **lot_ov)
        resident = create_resident(community["id"], api, **spec.get("resident", {}))
        lease = create_lease(lot["id"], resident["id"], api)
        activate_lease(lease["id"], api)
        lot = get_success_data(api.get_lot(lot["id"], MGR))
        rows.append((lot, resident, lease))
    community = get_success_data(api.get_community(community["id"], MGR))
    return community, rows


# ─── Utility apportionment ─────────────────────────────────────

def setup_apportionment_ready(specs, bill_overrides=None, api=api_client,
                              community_overrides=None, readings=None):
    """Occupied community + a DRAFT utility bill, ready to apportion.

    `specs` -> setup_community_with_n_occupied_lots. `readings` (optional) is a
    list of (lot_index, metered_units) attached to the bill for SUB_METER runs.
    Returns (community, rows, bill).
    """
    community, rows = setup_community_with_n_occupied_lots(
        specs, api=api, community_overrides=community_overrides
    )
    bill = get_success_data(
        api.create_utility_bill(
            f.create_utility_bill_payload(community["id"], **(bill_overrides or {})),
            MGR,
        )
    )
    if readings:
        for lot_index, units in readings:
            lot = rows[lot_index][0]
            get_success_data(
                api.create_reading(
                    bill["id"], f.create_reading_payload(lot["id"], units), MGR
                )
            )
    return community, rows, bill


def apportion_and_charges(bill_id, api=api_client):
    """Run apportionment, return (bill_after, charges_list)."""
    bill_after = get_success_data(api.apportion_bill(bill_id, MGR))
    charges_resp = api.list_utility_charges(MGR, params={"utility_bill_id": bill_id})
    charges = get_success_data(charges_resp)
    if isinstance(charges, dict):
        charges = charges.get("data", charges)
    return bill_after, charges


# ─── Rent schedules ────────────────────────────────────────────

def propose_rent_schedule(lot_id, api=api_client, **overrides):
    resp = api.create_rent_schedule(
        f.create_rent_schedule_payload(lot_id, **overrides), MGR
    )
    return get_success_data(resp)


def make_effective_schedule(lot_id, resident_id, proposed_rent_cents,
                            effective_date, api=api_client):
    """propose -> resident accept -> manager apply (schedule EFFECTIVE).

    Returns the EFFECTIVE schedule. Lot.current_rent_cents is now new_rent_cents.
    """
    res_headers = make_resident_headers(resident_id)
    sched = propose_rent_schedule(
        lot_id, api=api,
        proposed_rent_cents=proposed_rent_cents, effective_date=effective_date,
    )
    get_success_data(api.accept_rent_schedule(sched["id"], res_headers))
    return get_success_data(api.apply_rent_schedule(sched["id"], MGR))


# ─── Eviction ──────────────────────────────────────────────────

def setup_nonpayment_eviction(state_code="CA", rent_cents=55000,
                              notice_iso="2026-01-01T00:00:00.000Z", api=api_client):
    """Occupied lot whose resident is in arrears >= threshold, then a NONPAYMENT
    eviction served at `notice_iso`. The opening RENT_CHARGE of rent_cents drives
    arrears (>= 50000 when rent_cents >= 50000).

    Returns (community, lot, resident, lease, eviction_case).
    """
    set_clock(notice_iso, api)
    community, lot, resident, lease = setup_occupied_lot(
        api,
        community_overrides={"state_code": state_code},
        lot_overrides={"base_rent_cents": rent_cents},
    )
    case = get_success_data(
        api.create_eviction_case(
            f.create_eviction_case_payload(lease["id"], reason="NONPAYMENT"), MGR
        )
    )
    return community, lot, resident, lease, case


def setup_lease_violation_eviction(state_code="CA",
                                   notice_iso="2026-01-01T00:00:00.000Z",
                                   api=api_client):
    """Occupied lot + a LEASE_VIOLATION eviction served at `notice_iso`.

    Returns (community, lot, resident, lease, eviction_case).
    """
    set_clock(notice_iso, api)
    community, lot, resident, lease = setup_occupied_lot(
        api, community_overrides={"state_code": state_code}
    )
    case = get_success_data(
        api.create_eviction_case(
            f.create_eviction_case_payload(lease["id"], reason="LEASE_VIOLATION"), MGR
        )
    )
    return community, lot, resident, lease, case


# ─── Conversion votes ──────────────────────────────────────────

def setup_open_vote_one_lot(quorum=0.5, state_code="CA", api=api_client):
    """Occupied CA community with one lot, a vote OPENED (lot now FROZEN).

    Returns (community, lot, resident, lease, vote).
    """
    community, lot, resident, lease = setup_occupied_lot(
        api, community_overrides={"state_code": state_code}
    )
    vote = get_success_data(
        api.create_conversion_vote(
            f.create_conversion_vote_payload(community["id"], quorum_threshold_pct=quorum),
            MGR,
        )
    )
    get_success_data(api.open_conversion_vote(vote["id"], MGR))
    vote = get_success_data(api.get_conversion_vote(vote["id"], MGR))
    return community, lot, resident, lease, vote


# ─── Home-sale supersede ───────────────────────────────────────

def setup_supersede_pending(api=api_client, raise_rent=False,
                            community_overrides=None):
    """Occupied lot by resident A, plus a PENDING successor lease for buyer B
    carrying supersedes_lease_id = A's lease and expected_lot_version = the
    current Lot.version.

    If raise_rent is True, an EFFECTIVE increase (60000 -> 63000) is applied
    before the successor lease is created, bumping the lot version.

    Returns (community, lot, resident_a, lease_a, resident_b, lease_b, lot_version).
    """
    community, lot, resident_a, lease_a = setup_occupied_lot(
        api, community_overrides=community_overrides or {"state_code": "CA"}
    )
    if raise_rent:
        make_effective_schedule(
            lot["id"], resident_a["id"], 63000, "2027-01-01", api=api
        )
        lot = get_success_data(api.get_lot(lot["id"], MGR))
    lot_version = lot["version"]
    resident_b = create_resident(community["id"], api, full_name="Buyer B")
    lease_b = create_lease(
        lot["id"], resident_b["id"], api,
        start_date="2027-02-01",
        supersedes_lease_id=lease_a["id"],
        expected_lot_version=lot_version,
    )
    return community, lot, resident_a, lease_a, resident_b, lease_b, lot_version
