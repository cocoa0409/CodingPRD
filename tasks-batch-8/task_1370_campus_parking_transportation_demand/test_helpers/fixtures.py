"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD §4
endpoints and returns parsed response data (lenient `get_success_data`, so a
setup failure surfaces as a clear setup error rather than a confusing
assertion failure deep in a test).

Identity threading: ownership-gated Commuter calls always use
make_commuter_headers(<patron id>); ParkingAdmin / EnforcementOfficer /
AppealsOfficer identities are opaque operator ids.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_appeals_headers,
    make_commuter_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
APPEALS = TEST_USERS["appeals_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creation wrappers
# ---------------------------------------------------------------------------

def create_patron(**overrides) -> dict:
    resp = api_client.create_patron(factories.create_patron_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_lot(**overrides) -> dict:
    resp = api_client.create_lot(factories.create_lot_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_allocation(lot_id: str, **overrides) -> dict:
    resp = api_client.create_allocation(
        factories.create_allocation_payload(lot_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, ADMIN))


def get_allocation_version(allocation_id: str) -> int:
    return get_allocation(allocation_id)["version"]


def get_patron(patron_id: str) -> dict:
    return get_success_data(api_client.get_patron(patron_id, ADMIN))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_citation(citation_id: str) -> dict:
    return get_success_data(api_client.get_citation(citation_id, ADMIN))


def get_closure(closure_id: str) -> dict:
    return get_success_data(api_client.get_closure(closure_id, ADMIN))


def get_waitlist_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, ADMIN))


def get_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_transportation_fund(fund_id, ADMIN))


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_shuttle_route(route_id, ADMIN))


def get_incentive_account(account_id: str) -> dict:
    return get_success_data(api_client.get_incentive_account(account_id, ADMIN))


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(factories.set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(resp)


def purchase_permit(
    patron_id: str,
    allocation_id: str,
    plate_number: str,
    valid_from: str = None,
    apply_credit_cents: int = None,
    as_commuter: bool = False,
) -> dict:
    """Read the allocation version (canonical OCC read), then purchase.

    Defaults to a ParkingAdmin purchase on behalf of the patron; pass
    as_commuter=True to act as the owning Commuter.
    """
    version = get_allocation_version(allocation_id)
    overrides = {}
    if valid_from is not None:
        overrides["valid_from"] = valid_from
    if apply_credit_cents is not None:
        overrides["apply_credit_cents"] = apply_credit_cents
    payload = factories.create_permit_payload(
        patron_id, allocation_id, plate_number, version, **overrides
    )
    headers = make_commuter_headers(patron_id) if as_commuter else ADMIN
    return get_success_data(api_client.create_permit(payload, headers))


def cancel_permit(permit_id: str, patron_id: str = None) -> dict:
    """Cancel a permit; as ParkingAdmin by default, or as the owning Commuter
    when patron_id is given."""
    headers = make_commuter_headers(patron_id) if patron_id else ADMIN
    return get_success_data(api_client.cancel_permit(permit_id, headers))


def join_waitlist(patron_id: str, allocation_id: str, as_commuter: bool = False) -> dict:
    payload = factories.create_waitlist_entry_payload(patron_id, allocation_id)
    headers = make_commuter_headers(patron_id) if as_commuter else ADMIN
    return get_success_data(api_client.create_waitlist_entry(payload, headers))


def claim_offer(entry_id: str, patron_id: str, allocation_id: str) -> dict:
    """Claim an OFFERED entry as the owning Commuter against the allocation's
    current version. Returns the created Permit."""
    version = get_allocation_version(allocation_id)
    resp = api_client.claim_waitlist_entry(
        entry_id,
        factories.create_claim_payload(version),
        make_commuter_headers(patron_id),
    )
    return get_success_data(resp)


def issue_citation(lot_id: str, plate_number: str, violation_type: str,
                   officer_id: str = "off-1") -> dict:
    resp = api_client.create_citation(
        factories.create_citation_payload(lot_id, plate_number, violation_type),
        make_officer_headers(officer_id),
    )
    return get_success_data(resp)


def pay_citation(citation_id: str, patron_id: str) -> dict:
    resp = api_client.pay_citation(citation_id, make_commuter_headers(patron_id))
    return get_success_data(resp)


def appeal_citation(citation_id: str, patron_id: str, reason: str = "Contest") -> dict:
    resp = api_client.appeal_citation(
        citation_id, factories.create_appeal_payload(reason), make_commuter_headers(patron_id)
    )
    return get_success_data(resp)


def decide_appeal(citation_id: str, outcome: str, officer_id: str = "off-9",
                  reduction_pct: int = None) -> dict:
    overrides = {}
    if reduction_pct is not None:
        overrides["reduction_pct"] = reduction_pct
    resp = api_client.decide_appeal(
        citation_id,
        factories.create_decision_payload(outcome, **overrides),
        make_appeals_headers(officer_id),
    )
    return get_success_data(resp)


def create_closure(lot_id: str, **overrides) -> dict:
    resp = api_client.create_closure(factories.create_closure_payload(lot_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_fund(fund_code: str = "PTS_OPERATING") -> dict:
    resp = api_client.create_transportation_fund(
        factories.create_fund_payload(fund_code=fund_code), ADMIN
    )
    return get_success_data(resp)


def create_route(fund_id: str, **overrides) -> dict:
    resp = api_client.create_shuttle_route(
        factories.create_shuttle_route_payload(fund_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def enroll_incentive(patron_id: str) -> dict:
    resp = api_client.create_incentive_account(
        factories.create_incentive_account_payload(patron_id),
        make_commuter_headers(patron_id),
    )
    return get_success_data(resp)


def accrue_days(account_id: str, days_commuted: int) -> dict:
    resp = api_client.create_accrual(
        account_id, factories.create_accrual_payload(days_commuted), ADMIN
    )
    return get_success_data(resp)


def redeem_blocks(account_id: str, patron_id: str, blocks: int) -> dict:
    resp = api_client.redeem_incentive(
        account_id, factories.create_redeem_payload(blocks), make_commuter_headers(patron_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: entity hierarchy — patron with a permit on a fresh lot+allocation
# ---------------------------------------------------------------------------

def setup_patron_with_permit(
    name: str = "P",
    plate: str = "P111",
    campus_role: str = "STAFF",
    residency: str = "OFF_CAMPUS",
    commute_mode: str = "DRIVE_ALONE",
    eligible_roles=None,
    quota: int = 5,
    base_fee_cents: int = 80000,
    proration_policy: str = "PRORATED_WEEKLY",
    valid_from: str = None,
    apply_credit_cents: int = None,
    as_commuter: bool = False,
    lot_code: str = "LA",
) -> dict:
    """Patron + lot + OPEN allocation + one purchased permit."""
    patron = create_patron(
        full_name=name,
        campus_role=campus_role,
        residency=residency,
        primary_commute_mode=commute_mode,
    )
    lot = create_lot(lot_code=lot_code, name=f"Lot {lot_code}")
    allocation = create_allocation(
        lot["id"],
        eligible_roles=eligible_roles or [campus_role],
        quota=quota,
        base_fee_cents=base_fee_cents,
        proration_policy=proration_policy,
    )
    permit = purchase_permit(
        patron["id"],
        allocation["id"],
        plate,
        valid_from=valid_from,
        apply_credit_cents=apply_credit_cents,
        as_commuter=as_commuter,
    )
    return {
        "patron": patron,
        "lot": lot,
        "allocation": allocation,
        "permit": permit,
    }


# ---------------------------------------------------------------------------
# Tier 3/4: citation history targeting (standing / repeat-escalation states)
# ---------------------------------------------------------------------------

def issue_and_pay_citations(lot_id: str, plate: str, patron_id: str, count: int,
                            violation_type: str = "NO_VALID_PERMIT",
                            officer_id: str = "off-1") -> list:
    """Issue and immediately pay `count` citations for the plate."""
    paid = []
    for _ in range(count):
        citation = issue_citation(lot_id, plate, violation_type, officer_id)
        paid.append(pay_citation(citation["id"], patron_id))
    return paid


def setup_blocked_patron(name: str = "X", plate: str = "X666") -> dict:
    """Patron (STAFF) with a permit and an outstanding escalated citation:
    two prior paid NO_VALID_PERMIT citations push the third issue into the
    repeat-escalated schedule (11250), and the unpaid 11250 crosses the
    10000-cent block threshold, flipping standing to BLOCKED and suspending
    the patron's ACTIVE permit.
    """
    ctx = setup_patron_with_permit(name=name, plate=plate, campus_role="STAFF", quota=5)
    second_lot = create_lot(lot_code="LB", name="Lot B", zone="REMOTE")
    issue_and_pay_citations(second_lot["id"], plate, ctx["patron"]["id"], 2)
    last = issue_citation(second_lot["id"], plate, "NO_VALID_PERMIT")
    ctx["violation_lot"] = second_lot
    ctx["unpaid_citation"] = last
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: waitlist / offer states
# ---------------------------------------------------------------------------

def setup_full_allocation(occupier_name: str = "Occ", occupier_plate: str = "O111",
                          quota: int = 1, eligible_roles=None, lot_code: str = "LW") -> dict:
    """A lot with one allocation whose quota is fully occupied by the
    occupier's permit — the allocation is WAITLISTING."""
    occupier = create_patron(full_name=occupier_name, campus_role="STUDENT",
                             residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
    lot = create_lot(lot_code=lot_code, name=f"Lot {lot_code}")
    allocation = create_allocation(
        lot["id"], eligible_roles=eligible_roles or ["STUDENT", "STAFF", "FACULTY"],
        quota=quota,
    )
    permit = purchase_permit(occupier["id"], allocation["id"], occupier_plate)
    return {
        "occupier": occupier,
        "lot": lot,
        "allocation": allocation,
        "occupier_permit": permit,
    }


def setup_waitlisting_with_entry(waiter_name: str = "W", waiter_role: str = "STUDENT",
                                 waiter_residency: str = "OFF_CAMPUS", **kwargs) -> dict:
    """Full (WAITLISTING) allocation plus one WAITING entry for the waiter."""
    ctx = setup_full_allocation(**kwargs)
    waiter = create_patron(full_name=waiter_name, campus_role=waiter_role,
                           residency=waiter_residency, primary_commute_mode="DRIVE_ALONE")
    entry = join_waitlist(waiter["id"], ctx["allocation"]["id"])
    ctx["waiter"] = waiter
    ctx["entry"] = entry
    return ctx


def setup_offered_entry(**kwargs) -> dict:
    """WAITLISTING allocation + WAITING entry, then the occupier cancels:
    the cancellation cascade runs the offer selector and the entry becomes
    OFFERED (offers_outstanding 1 on the allocation)."""
    ctx = setup_waitlisting_with_entry(**kwargs)
    cancel_permit(ctx["occupier_permit"]["id"])
    ctx["entry"] = get_waitlist_entry(ctx["entry"]["id"])
    ctx["allocation"] = get_allocation(ctx["allocation"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: incentive program states
# ---------------------------------------------------------------------------

def setup_incentive_account(name: str = "M", commute_mode: str = "TRANSIT",
                            accrued_days=()) -> dict:
    """Patron enrolled in the incentive program with optional accrued days
    (each posting must be 1..31 days)."""
    patron = create_patron(full_name=name, campus_role="STAFF", residency="OFF_CAMPUS",
                           primary_commute_mode=commute_mode)
    account = enroll_incentive(patron["id"])
    for days in accrued_days:
        accrue_days(account["id"], days)
    return {"patron": patron, "account": get_incentive_account(account["id"])}


def setup_account_with_credit(name: str = "M", blocks: int = 1) -> dict:
    """Patron + incentive account with `blocks` 500-point blocks redeemed to
    credit (50 accrued days per block). Returns credit_balance_cents =
    blocks * 2500."""
    days_per_block = 50  # 500 points
    accrued = []
    for _ in range(blocks):
        accrued.extend([31, 19])
    ctx = setup_incentive_account(name=name, accrued_days=accrued)
    redeem_blocks(ctx["account"]["id"], ctx["patron"]["id"], blocks)
    ctx["account"] = get_incentive_account(ctx["account"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: construction displacement topology
# ---------------------------------------------------------------------------

def setup_construction_closure(src_quota: int = 2, dst_quota: int = 1,
                               fill_dst: bool = False) -> dict:
    """Two lots with same-permit_code allocations (SRC on lot 1, DST on lot
    2), one ACTIVE permit on SRC, and a SCHEDULED CONSTRUCTION closure on
    lot 1 with lot 2 as fallback. When fill_dst is True, DST's quota is
    already fully occupied by a second patron's permit."""
    patron = create_patron(full_name="P", campus_role="STAFF", residency="ON_CAMPUS",
                           primary_commute_mode="DRIVE_ALONE")
    lot_1 = create_lot(lot_code="L1", name="Lot 1")
    lot_2 = create_lot(lot_code="L2", name="Lot 2", zone="PERIMETER")
    alloc_src = create_allocation(lot_1["id"], permit_code="RES", eligible_roles=["STAFF"],
                                  quota=src_quota)
    alloc_dst = create_allocation(lot_2["id"], permit_code="RES", eligible_roles=["STAFF"],
                                  quota=dst_quota)
    permit = purchase_permit(patron["id"], alloc_src["id"], "D444")
    dst_permit = None
    if fill_dst:
        other = create_patron(full_name="P2", campus_role="STAFF", residency="ON_CAMPUS",
                              primary_commute_mode="DRIVE_ALONE")
        dst_permit = purchase_permit(other["id"], alloc_dst["id"], "P222")
    closure = create_closure(
        lot_1["id"],
        reason="CONSTRUCTION",
        event_name=None,
        reserved_spaces=0,
        fallback_lot_id=lot_2["id"],
        starts_at="2026-08-10T00:00:00Z",
        ends_at="2026-08-20T00:00:00Z",
    )
    return {
        "patron": patron,
        "lot_1": lot_1,
        "lot_2": lot_2,
        "alloc_src": alloc_src,
        "alloc_dst": alloc_dst,
        "permit": permit,
        "dst_permit": dst_permit,
        "closure": closure,
    }
