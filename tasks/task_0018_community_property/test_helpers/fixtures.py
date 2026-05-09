"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as "Setup failed" errors rather than obscure assertion failures.

Identity threading is mandatory per PRD §2.1: when an Owner is created and a
subsequent call requires the caller to be that owner (work-order creation,
reservation booking, parking application, voting, payment by the owner), the
fixture passes make_owner_headers(owner["id"]) — never the shared TEST_USERS
fallback. The fallback's X-User-ID does not match any real Owner.id, so every
ownership check would reject the call.

For the opaque roles (PropertyManager, MaintenanceStaff, CommitteeChair) the
shared headers are safe; PRD §2.1 says X-User-ID for these roles is opaque.
But MaintenanceStaff is special: PRD §3.2 enforces an equality check between
X-User-ID and the recorded WorkOrder.assigned_staff_id once a work order is
dispatched, so any maintenance fixture that dispatches an order MUST reuse the
same staff_id on the subsequent start/reject/resolve calls.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_parking_application_payload,
    cast_vote_payload,
    close_reservation_payload,
    confirm_work_order_payload,
    create_access_log_payload,
    create_facility_payload,
    create_fee_billing_rule_payload,
    create_owner_payload,
    create_parking_application_payload,
    create_parking_space_payload,
    create_payment_payload,
    create_property_payload,
    create_proposal_payload,
    create_reservation_payload,
    create_resident_payload,
    create_work_order_payload,
    dispatch_work_order_payload,
    issue_fee_bills_payload,
    iso_utc,
    patch_fee_billing_rule_payload,
    waive_fee_bill_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_chair_headers,
    make_maintenance_headers,
    make_owner_headers,
    make_property_manager_headers,
)


# ──────────────────────────────────────────────────────────
# Clock helpers
# ──────────────────────────────────────────────────────────

def advance_clock_to(to_iso: str) -> None:
    """Advance the server's logical clock to *to_iso* (PRD §2.10, §3.10).

    The clock-advance endpoint runs every auto-transition due at or before
    the supplied instant in chronological order.
    """
    get_success_data(api_client.advance_clock(to_iso, TEST_USERS["property_manager_headers"]))


def advance_clock_by(delta: timedelta, base: Optional[datetime] = None) -> str:
    """Advance the clock to (base or now) + delta and return the ISO target."""
    if base is None:
        base = datetime.now(timezone.utc)
    target = base + delta
    target_iso = iso_utc(target)
    advance_clock_to(target_iso)
    return target_iso


# ──────────────────────────────────────────────────────────
# Tier 1 — Single-entity creation
# ──────────────────────────────────────────────────────────

def create_owner(**owner_overrides: Any) -> Dict[str, Any]:
    """Create an Owner via PropertyManager. Returns the persisted Owner record."""
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(
        api_client.create_owner(create_owner_payload(**owner_overrides), pm)
    )


def create_property_for_owner(
    owner: Dict[str, Any], **property_overrides: Any
) -> Dict[str, Any]:
    """Create a Property bound to the given owner."""
    pm = TEST_USERS["property_manager_headers"]
    payload = create_property_payload(owner_id=owner["id"], **property_overrides)
    return get_success_data(api_client.create_property(payload, pm))


def create_owner_with_property(
    *,
    area_sqm: float = 80.00,
    parking_quota: int = 1,
    owner_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an Owner and a Property bound to that Owner. Returns (owner, property)."""
    owner = create_owner(**(owner_overrides or {}))
    prop_kwargs: Dict[str, Any] = {"area_sqm": area_sqm, "parking_quota": parking_quota}
    prop_kwargs.update(property_overrides or {})
    prop = create_property_for_owner(owner, **prop_kwargs)
    return owner, prop


def create_facility(
    *,
    slot_minutes: int = 60,
    capacity_per_slot: int = 1,
    cancellation_window_hours: int = 24,
    damage_deposit: float = 0.0,
    facility_type: str = "MEETING_ROOM",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Facility with explicit slot/capacity/window/deposit defaults."""
    pm = TEST_USERS["property_manager_headers"]
    payload = create_facility_payload(
        facility_type=facility_type,
        slot_minutes=slot_minutes,
        capacity_per_slot=capacity_per_slot,
        cancellation_window_hours=cancellation_window_hours,
        damage_deposit=damage_deposit,
        **overrides,
    )
    return get_success_data(api_client.create_facility(payload, pm))


def create_fee_billing_rule(
    *,
    kind: str = "PER_SQM_MONTHLY",
    rate: float = 2.50,
    late_fee_daily_rate: Optional[float] = None,
    late_fee_cap_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create an ACTIVE FeeBillingRule. Late-fee defaults follow PRD §3.3."""
    pm = TEST_USERS["property_manager_headers"]
    payload = create_fee_billing_rule_payload(kind=kind, rate=rate, **overrides)
    if late_fee_daily_rate is not None:
        payload["late_fee_daily_rate"] = late_fee_daily_rate
    if late_fee_cap_pct is not None:
        payload["late_fee_cap_pct"] = late_fee_cap_pct
    return get_success_data(api_client.create_fee_billing_rule(payload, pm))


def create_parking_space(
    *, kind: str = "FIXED", monthly_fee: float = 100.0, **overrides: Any
) -> Dict[str, Any]:
    """Create a ParkingSpace; default kind is FIXED with a non-zero monthly fee."""
    pm = TEST_USERS["property_manager_headers"]
    payload = create_parking_space_payload(kind=kind, monthly_fee=monthly_fee, **overrides)
    return get_success_data(api_client.create_parking_space(payload, pm))


# ──────────────────────────────────────────────────────────
# Tier 2 — Resident lifecycle
# ──────────────────────────────────────────────────────────

def create_family_resident(prop: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    payload = create_resident_payload(prop["id"], relation_kind="FAMILY", **overrides)
    return get_success_data(api_client.create_resident(payload, pm))


def create_tenant_resident(
    prop: Dict[str, Any],
    *,
    lease_end_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    if lease_end_at is None:
        lease_end_at = iso_utc(datetime.now(timezone.utc) + timedelta(days=180))
    payload = create_resident_payload(
        prop["id"], relation_kind="TENANT", lease_end_at=lease_end_at, **overrides
    )
    return get_success_data(api_client.create_resident(payload, pm))


def move_in_resident(resident: Dict[str, Any]) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.move_in_resident(resident["id"], pm))


def move_out_resident(resident: Dict[str, Any]) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.move_out_resident(resident["id"], pm))


# ──────────────────────────────────────────────────────────
# Tier 3 — Work-order lifecycle shortcuts
# ──────────────────────────────────────────────────────────

def submit_work_order(
    owner: Dict[str, Any], prop: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Owner submits a work order (PRD §3.2 — acting Owner = reporter_owner_id)."""
    headers = make_owner_headers(owner["id"])
    payload = create_work_order_payload(prop["id"], **overrides)
    return get_success_data(api_client.create_work_order(payload, headers))


def dispatch_work_order_to(
    wo: Dict[str, Any], staff_id: str = "test-maint-1"
) -> Dict[str, Any]:
    """PropertyManager dispatches *wo* to a maintenance operator with the given opaque id.
    Subsequent start/reject/resolve calls MUST use make_maintenance_headers(staff_id)."""
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(
        api_client.dispatch_work_order(
            wo["id"], dispatch_work_order_payload(staff_id), pm
        )
    )


def progress_work_order_to_resolved(
    owner: Dict[str, Any],
    prop: Dict[str, Any],
    *,
    staff_id: str = "test-maint-1",
) -> Tuple[Dict[str, Any], str]:
    """submit → dispatch → start → resolve. Returns (resolved_wo, staff_id used)."""
    wo = submit_work_order(owner, prop)
    dispatched = dispatch_work_order_to(wo, staff_id=staff_id)
    maint = make_maintenance_headers(staff_id)
    started = get_success_data(api_client.start_work_order(dispatched["id"], maint))
    resolved = get_success_data(api_client.resolve_work_order(started["id"], maint))
    return resolved, staff_id


# ──────────────────────────────────────────────────────────
# Tier 4 — Fee-billing scenarios (the heart of difficulty-design coverage)
# ──────────────────────────────────────────────────────────

def issue_bills_for_period(period_year: int, period_month: int) -> List[Dict[str, Any]]:
    """Issue bills for a (year, month). Returns the list of FeeBill rows produced."""
    pm = TEST_USERS["property_manager_headers"]
    data = get_success_data(
        api_client.issue_fee_bills(issue_fee_bills_payload(period_year, period_month), pm)
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        return data["items"]
    # Some implementations may return a single bill directly when only one matches.
    return [data] if isinstance(data, dict) else []


def setup_property_with_active_rule(
    *,
    area_sqm: float = 80.00,
    rule_kind: str = "PER_SQM_MONTHLY",
    rate: float = 2.50,
    late_fee_daily_rate: float = 0.0005,
    late_fee_cap_pct: float = 0.30,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Owner + Property + ACTIVE FeeBillingRule. Returns (owner, property, rule)."""
    owner, prop = create_owner_with_property(area_sqm=area_sqm)
    rule = create_fee_billing_rule(
        kind=rule_kind,
        rate=rate,
        late_fee_daily_rate=late_fee_daily_rate,
        late_fee_cap_pct=late_fee_cap_pct,
    )
    return owner, prop, rule


def issue_single_bill_for_property(
    prop: Dict[str, Any],
    period_year: int,
    period_month: int,
    *,
    rule_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue bills for the period and return THE FeeBill bound to *prop* and *rule_id*.

    PRD §3.3 issues one bill per (property, ACTIVE rule) pair. When the test DB
    holds multiple ACTIVE rules from earlier tests, the property receives one
    bill per rule. To isolate the test's intended (property, rule) target, pass
    *rule_id*; the helper returns the one bill matching that rule, and waives
    every other bill issued against the same property in this period so the
    target bill is the property's only non-waived bill (preventing spurious
    voting_status / dunning interference from sibling bills).

    Raises AssertionError if no bill matching (prop, rule_id) is found.
    """
    bills = issue_bills_for_period(period_year, period_month)
    same_property = [b for b in bills if b.get("property_id") == prop["id"]]
    assert same_property, (
        f"Setup failed: no FeeBill issued for property {prop['id']} "
        f"in period {period_year}-{period_month:02d}"
    )
    if rule_id is not None:
        target = [b for b in same_property if b.get("rule_id") == rule_id]
        assert target, (
            f"Setup failed: no FeeBill issued for property {prop['id']} bound to "
            f"rule {rule_id} in period {period_year}-{period_month:02d}"
        )
        chosen = target[0]
        # Waive sibling bills (same property, same period, different rule) so
        # the target is the property's only OPEN bill — prevents interference
        # via owner.voting_status recomputation cascades.
        pm = TEST_USERS["property_manager_headers"]
        for sibling in same_property:
            if sibling["id"] == chosen["id"]:
                continue
            try:
                get_success_data(
                    api_client.waive_fee_bill(
                        sibling["id"], waive_fee_bill_payload(reason="test isolation"), pm
                    )
                )
            except Exception:
                pass
        return chosen
    return same_property[0]


# ──────────────────────────────────────────────────────────
# Reservation scenarios
# ──────────────────────────────────────────────────────────

def book_reservation(
    owner: Dict[str, Any],
    facility: Dict[str, Any],
    slot_start_at: str,
    slot_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Owner books a slot. Threads make_owner_headers(owner.id) per PRD §2.1."""
    headers = make_owner_headers(owner["id"])
    payload = create_reservation_payload(
        facility["id"], slot_start_at, slot_end_at, **overrides
    )
    return get_success_data(api_client.create_reservation(payload, headers))


def book_default_reservation(
    owner: Dict[str, Any],
    facility: Dict[str, Any],
    *,
    starts_in_seconds: int = 3600,
) -> Dict[str, Any]:
    """Book a slot starting *starts_in_seconds* in the future for a default facility.

    Slot length follows facility.slot_minutes; start is grid-aligned to the next
    midnight-multiple of slot_minutes after the requested instant.
    """
    slot_minutes = facility["slot_minutes"]
    target = datetime.now(timezone.utc) + timedelta(seconds=starts_in_seconds)
    # Grid-align: zero-base from midnight UTC. Round UP to the next multiple.
    minutes_from_midnight = target.hour * 60 + target.minute
    bucket = ((minutes_from_midnight + slot_minutes - 1) // slot_minutes) * slot_minutes
    aligned = target.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        minutes=bucket
    )
    if aligned <= datetime.now(timezone.utc):
        aligned = aligned + timedelta(minutes=slot_minutes)
    end = aligned + timedelta(minutes=slot_minutes)
    return book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))


# ──────────────────────────────────────────────────────────
# Proposal & vote scenarios (per_household, per_area, threshold boundaries)
# ──────────────────────────────────────────────────────────

def disqualify_preexisting_eligible_owners() -> None:
    """Render every preexisting ELIGIBLE Owner INELIGIBLE_DELINQUENT.

    PRD §3.8 says proposal-open snapshots "the set of Owner rows whose voting_status
    is ELIGIBLE at the open instant" — across the entire community. Because the
    test container persists DB state across tests, voting fixtures must isolate
    their voter pool from prior tests' owners. This helper issues an OVERDUE bill
    against every preexisting (Owner, Property) so the recompute_for_owner cascade
    flips every preexisting Owner to INELIGIBLE_DELINQUENT, then resets the logical
    clock back to wall time so subsequent slot/voting timestamps remain valid.

    Voters created AFTER this call have no bills and remain ELIGIBLE — exactly
    what the test's eligibility snapshot needs.
    """
    pm = TEST_USERS["property_manager_headers"]
    # 1. Snapshot existing owners and properties via the listing endpoints.
    owners_res = api_client.list_owners(pm, params={"limit": 100, "offset": 0})
    body = owners_res.json() if owners_res.text else {}
    existing_owners = body.get("data", []) if isinstance(body.get("data"), list) else []
    eligible_owner_ids = {
        o["id"] for o in existing_owners if o.get("voting_status") == "ELIGIBLE"
    }
    if not eligible_owner_ids:
        return
    # Some owners may not yet have properties; we only need to flip those that do.
    # 2. Create a fresh ACTIVE rule (cheap) and issue bills for a period far in the past.
    rule = create_fee_billing_rule(kind="PER_SQM_MONTHLY", rate=1.00)
    # Pick a deeply-past period so its due_date is unambiguously past wall-now.
    today = datetime.now(timezone.utc).date()
    past_year = today.year - 2
    past_month = 1
    issue_bills_for_period(past_year, past_month)
    # 3. Advance clock past that period's due_date (last-day + 14d + safety) so
    #    OPEN bills auto-flip to OVERDUE → recompute_for_owner makes preexisting
    #    owners INELIGIBLE_DELINQUENT.
    target = datetime(past_year, past_month, 28, tzinfo=timezone.utc) + timedelta(days=30)
    advance_clock_to(iso_utc(target))
    # 4. Reset clock back to current wall time so later "future" timestamps in
    #    test bodies (slot_start_at, voting_ends_at) are computed against a
    #    consistent now()-equivalent.
    advance_clock_to(iso_utc(datetime.now(timezone.utc)))


def setup_proposal_voters(
    n: int,
    *,
    areas: Optional[List[float]] = None,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Create N (Owner, Property) pairs for use as proposal voters.

    Disqualifies all preexisting ELIGIBLE owners first so the proposal-open
    snapshot includes only the N freshly-created voters (PRD §3.8: the eligible
    list is the set of Owner rows whose voting_status is ELIGIBLE at the open
    instant — across the entire DB, not scoped to this test).

    If *areas* is provided and len(areas) >= n, the first n are used as area_sqm
    values for the properties; otherwise every property defaults to 100 sqm.
    All N new owners start with voting_status=ELIGIBLE per PRD §3.1.
    """
    disqualify_preexisting_eligible_owners()
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for idx in range(n):
        area = (areas[idx] if areas and idx < len(areas) else 100.0)
        pairs.append(create_owner_with_property(area_sqm=area))
    return pairs


def create_and_open_proposal(
    *,
    voting_method: str = "PER_HOUSEHOLD",
    pass_threshold_pct: Optional[float] = None,
    voting_starts_at: Optional[str] = None,
    voting_ends_at: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """CommitteeChair drafts a proposal and opens it. Returns the OPEN proposal.

    The voting window defaults to [now, now+7d) and is overridable. Caller is
    responsible for advancing the clock past voting_ends_at before tally.
    """
    chair = make_committee_chair_headers()
    payload_overrides: Dict[str, Any] = {}
    if pass_threshold_pct is not None:
        payload_overrides["pass_threshold_pct"] = pass_threshold_pct
    if title is not None:
        payload_overrides["title"] = title
    payload = create_proposal_payload(
        voting_method=voting_method,
        voting_starts_at=voting_starts_at,
        voting_ends_at=voting_ends_at,
        **payload_overrides,
    )
    draft = get_success_data(api_client.create_proposal(payload, chair))
    opened = get_success_data(api_client.open_proposal(draft["id"], chair))
    return opened


def cast_vote(
    proposal: Dict[str, Any],
    owner: Dict[str, Any],
    prop: Dict[str, Any],
    choice: str = "YES",
) -> Dict[str, Any]:
    """Owner casts a vote on *proposal* using their property as the vote subject.
    Threads make_owner_headers(owner.id) to satisfy PRD §2.1 ownership."""
    headers = make_owner_headers(owner["id"])
    payload = cast_vote_payload(prop["id"], choice=choice)
    return get_success_data(api_client.cast_vote(proposal["id"], payload, headers))


# ──────────────────────────────────────────────────────────
# Difficulty-design Tier 4 — composite scenarios for high-priority tests.
#
# These match the test_recipe.setup blocks from SCAFFOLD_DIFFICULTY_DESIGN.yaml
# verbatim so each difficulty-design test imports a single helper and focuses
# on assertions, not plumbing.
# ──────────────────────────────────────────────────────────

def setup_overdue_bill(
    *,
    area_sqm: float = 80.00,
    rate: float = 2.50,
    late_fee_daily_rate: float = 0.0005,
    late_fee_cap_pct: float = 0.30,
    days_past_due: int = 20,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Bring a single FeeBill to OVERDUE with *days_past_due* of accrual.

    Recipe (from PRD §3.3 + §3.5):
      1. Create Owner + Property(area_sqm).
      2. Create active FeeBillingRule(PER_SQM_MONTHLY, rate, late_fee_daily_rate, cap).
      3. Issue bill for last calendar month — due_date = last_day + 14d.
      4. Advance clock to due_date + days_past_due.

    Returns (owner, property, rule, overdue_bill).
    """
    owner, prop, rule = setup_property_with_active_rule(
        area_sqm=area_sqm,
        rate=rate,
        late_fee_daily_rate=late_fee_daily_rate,
        late_fee_cap_pct=late_fee_cap_pct,
    )
    # Issue for the previous calendar month so due_date is in the past relative to "now"
    # after we advance the clock to (last-day + 14 + days_past_due).
    today = datetime.now(timezone.utc).date()
    if today.month == 1:
        period_year = today.year - 1
        period_month = 12
    else:
        period_year = today.year
        period_month = today.month - 1
    bill = issue_single_bill_for_property(prop, period_year, period_month, rule_id=rule["id"])
    # Advance clock to due_date + days_past_due.
    due_iso = bill["due_date"]
    due_dt = datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
    target = due_dt + timedelta(days=days_past_due)
    advance_clock_to(iso_utc(target))
    # Re-read the bill to get the post-advance status snapshot.
    refreshed = get_success_data(
        api_client.get_fee_bill(bill["id"], TEST_USERS["property_manager_headers"])
    )
    return owner, prop, rule, refreshed


def setup_two_proposals_voting_method_split(
    areas: List[float],
) -> Tuple[
    List[Tuple[Dict[str, Any], Dict[str, Any]]],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Mirror difficulty-design instance vote_tally_per_household_vs_per_area:

    - Create N owners with properties of *areas* sqm; all ELIGIBLE.
    - Create Proposal A with PER_HOUSEHOLD, pass_threshold_pct=0.6667.
    - Create Proposal B with PER_AREA,      pass_threshold_pct=0.6667.
    - Open both proposals (so eligible_weight_total freezes for each).

    Returns (voter_pairs, proposal_a, proposal_b). The caller casts votes and
    advances the clock past voting_ends_at before tallying.
    """
    voters = setup_proposal_voters(len(areas), areas=areas)
    now = datetime.now(timezone.utc)
    starts = iso_utc(now - timedelta(seconds=10))
    ends = iso_utc(now + timedelta(days=2))
    proposal_a = create_and_open_proposal(
        voting_method="PER_HOUSEHOLD",
        pass_threshold_pct=0.6667,
        voting_starts_at=starts,
        voting_ends_at=ends,
        title="Proposal A per-household",
    )
    proposal_b = create_and_open_proposal(
        voting_method="PER_AREA",
        pass_threshold_pct=0.6667,
        voting_starts_at=starts,
        voting_ends_at=ends,
        title="Proposal B per-area",
    )
    return voters, proposal_a, proposal_b


def setup_three_open_bills(
    *,
    rate: float = 2.50,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Issue three OPEN FeeBills against three distinct properties of one owner.

    Used for the FeeBill branching-fork instance: each bill is driven down a
    different next-state from OPEN (PARTIALLY_PAID, PAID, WAIVED, OVERDUE).

    Returns (owner, props_list, rule, bills_list). Three properties → three bills,
    all status=OPEN, principal_amount derived from rate*area_sqm with area=80.
    """
    owner = create_owner()
    props = []
    for _ in range(3):
        props.append(
            create_property_for_owner(owner, area_sqm=80.00)
        )
    rule = create_fee_billing_rule(kind="PER_SQM_MONTHLY", rate=rate)
    today = datetime.now(timezone.utc).date()
    if today.month == 1:
        py, pm_ = today.year - 1, 12
    else:
        py, pm_ = today.year, today.month - 1
    bills = issue_bills_for_period(py, pm_)
    prop_ids = {p["id"] for p in props}
    same_props = [b for b in bills if b["property_id"] in prop_ids]
    # Per PRD §3.3, one bill per (property, ACTIVE rule). The test DB may carry
    # extra active rules from earlier tests, producing extra bills against each
    # of our properties. Pick the bill bound to *our* freshly-created rule for
    # each property, and waive sibling bills against the same property to
    # prevent owner.voting_status cascades from interfering.
    matched = [b for b in same_props if b.get("rule_id") == rule["id"]]
    assert len(matched) == 3, (
        f"Setup failed: expected 3 issued bills (one per property bound to test rule), "
        f"got {len(matched)} (out of {len(same_props)} property-matching bills)"
    )
    pm_headers = TEST_USERS["property_manager_headers"]
    chosen_ids = {b["id"] for b in matched}
    for sibling in same_props:
        if sibling["id"] in chosen_ids:
            continue
        try:
            get_success_data(
                api_client.waive_fee_bill(
                    sibling["id"], waive_fee_bill_payload(reason="test isolation"), pm_headers
                )
            )
        except Exception:
            pass
    matched.sort(key=lambda b: b["property_id"])
    return owner, props, rule, matched


def setup_facility_with_capacity(
    *,
    slot_minutes: int = 60,
    capacity_per_slot: int = 1,
    cancellation_window_hours: int = 24,
    damage_deposit: float = 0.0,
) -> Dict[str, Any]:
    """Single-facility wrapper for slot/capacity scenarios."""
    return create_facility(
        slot_minutes=slot_minutes,
        capacity_per_slot=capacity_per_slot,
        cancellation_window_hours=cancellation_window_hours,
        damage_deposit=damage_deposit,
    )


def setup_parking_application_pending(
    *,
    parking_quota: int = 1,
    requested_kind: str = "FIXED",
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Owner + Property(parking_quota) + PENDING ParkingApplication(requested_kind).

    Returns (owner, property, pending_application).
    """
    owner, prop = create_owner_with_property(parking_quota=parking_quota)
    headers = make_owner_headers(owner["id"])
    payload = create_parking_application_payload(prop["id"], requested_kind=requested_kind)
    pending = get_success_data(api_client.create_parking_application(payload, headers))
    return owner, prop, pending


def approve_parking_application(
    app: Dict[str, Any], space: Dict[str, Any]
) -> Dict[str, Any]:
    """PropertyManager approves *app* allocating *space* to it."""
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(
        api_client.approve_parking_application(
            app["id"], approve_parking_application_payload(space["id"]), pm
        )
    )


# ──────────────────────────────────────────────────────────
# Boundary helpers — reservation deposits & damages
# ──────────────────────────────────────────────────────────

def setup_reservation_with_deposit(
    *,
    damage_deposit: float = 500.00,
    cancellation_window_hours: int = 24,
    slot_minutes: int = 60,
    starts_in_seconds: int = 60 * 60 * 48,  # 48h ahead — well outside any reasonable cutoff.
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create owner + facility(damage_deposit, cancellation_window) + booked reservation.

    The reservation is booked *starts_in_seconds* in the future, grid-aligned. The
    deposit is held at facility.damage_deposit per PRD §3.7.

    Returns (owner, facility, reservation).
    """
    owner, _prop = create_owner_with_property()
    facility = create_facility(
        slot_minutes=slot_minutes,
        capacity_per_slot=1,
        cancellation_window_hours=cancellation_window_hours,
        damage_deposit=damage_deposit,
    )
    res = book_default_reservation(owner, facility, starts_in_seconds=starts_in_seconds)
    return owner, facility, res


def reservation_check_in(res: Dict[str, Any], owner: Dict[str, Any]) -> Dict[str, Any]:
    """Owner checks in to a booked reservation (PRD §3.7)."""
    headers = make_owner_headers(owner["id"])
    return get_success_data(api_client.check_in_reservation(res["id"], headers))


def reservation_close(res: Dict[str, Any], damage_amount: float = 0.0) -> Dict[str, Any]:
    """PropertyManager closes a CHECKED_IN reservation. damage_amount > 0 → DAMAGED."""
    pm = TEST_USERS["property_manager_headers"]
    payload = close_reservation_payload(damage_amount=damage_amount)
    return get_success_data(api_client.close_reservation(res["id"], payload, pm))


# ──────────────────────────────────────────────────────────
# Payment helpers
# ──────────────────────────────────────────────────────────

def pay_bill(
    bill: Dict[str, Any],
    owner: Dict[str, Any],
    *,
    amount: Optional[float] = None,
    channel: str = "WECHAT",
    external_txn_id: Optional[str] = None,
    paid_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Owner pays a fee bill. Defaults to paying total_due (full reconciliation).

    Threads make_owner_headers(owner.id) so PRD §2.1's ownership rule on /payments
    (Owner is allowed only to pay bills tied to their own properties) is satisfied.
    """
    headers = make_owner_headers(owner["id"])
    if amount is None:
        amount = float(bill.get("total_due", 0))
    payload = create_payment_payload(
        bill_id=bill["id"],
        amount=amount,
        channel=channel,
        external_txn_id=external_txn_id,
        paid_at=paid_at,
    )
    return get_success_data(api_client.create_payment(payload, headers))


def pay_bill_as_manager(
    bill: Dict[str, Any],
    *,
    amount: Optional[float] = None,
    channel: str = "WECHAT",
    external_txn_id: Optional[str] = None,
    paid_at: Optional[str] = None,
) -> Dict[str, Any]:
    """PropertyManager-driven payment, used when the test's identity is not the bill's
    owner (PRD §4 lists PropertyManager and Owner as authorized for /payments)."""
    pm = TEST_USERS["property_manager_headers"]
    if amount is None:
        amount = float(bill.get("total_due", 0))
    payload = create_payment_payload(
        bill_id=bill["id"],
        amount=amount,
        channel=channel,
        external_txn_id=external_txn_id,
        paid_at=paid_at,
    )
    return get_success_data(api_client.create_payment(payload, pm))


# ──────────────────────────────────────────────────────────
# Audit & data-fetch helpers
# ──────────────────────────────────────────────────────────

def list_audit_entries_for(
    *, subject_kind: Optional[str] = None, subject_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return the audit-entries list filtered by subject_kind/subject_id."""
    pm = TEST_USERS["property_manager_headers"]
    params: Dict[str, Any] = {}
    if subject_kind is not None:
        params["subject_kind"] = subject_kind
    if subject_id is not None:
        params["subject_id"] = subject_id
    res = api_client.list_audit_entries(pm, params=params)
    body = res.json() if res.text else {}
    if "data" in body and isinstance(body["data"], list):
        return body["data"]
    return []


def fetch_bill(bill_id: str) -> Dict[str, Any]:
    """Read a fee bill via PropertyManager (avoids ownership setup for diagnostic reads)."""
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.get_fee_bill(bill_id, pm))


def fetch_proposal(proposal_id: str) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.get_proposal(proposal_id, pm))


def fetch_owner(owner_id: str) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.get_owner(owner_id, pm))


def fetch_property(prop_id: str) -> Dict[str, Any]:
    pm = TEST_USERS["property_manager_headers"]
    return get_success_data(api_client.get_property(prop_id, pm))
