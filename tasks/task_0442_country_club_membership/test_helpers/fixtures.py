"""Composite setup helpers for the Country Club Membership API.

These encapsulate the multi-step API-call preambles that the design-index test
recipes share, so test bodies focus on the trigger + assertions. All setup calls
use get_success_data() (lenient 2xx) so a broken precondition surfaces as a clear
"Setup step failed" error.

Identity threading: Member is entity-backed. Any ownership-gated Member call uses
make_member_headers(membership["id"]) with the real Membership.id, never the
shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_member_headers,
)

_MANAGER = TEST_USERS["club_manager_headers"]
_CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / 2: base club + category + membership construction
# ---------------------------------------------------------------------------
def create_club(**overrides) -> dict:
    """POST /clubs. Pass policy knobs via overrides (fb_minimum_carryover_allowed,
    resignation_refund_pct, guest_visits_cap_per_period)."""
    payload = {"name": overrides.pop("name", "Test Club")}
    payload.update(overrides)
    return get_success_data(api_client.create_club(payload, _MANAGER))


def create_category(club_id, **overrides) -> dict:
    """POST /membership-categories. Sensible defaults; override per scenario."""
    payload = {
        "club_id": club_id,
        "code": "SOCIAL",
        "initiation_fee_cents": 0,
        "refundable_equity_cents": 0,
        "monthly_dues_cents": 15000,
        "fb_minimum_cents": 0,
        "capacity": 50,
        "guest_fee_cents": 5000,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_category(payload, _MANAGER))


def create_membership(club_id, category_id, holder_name="M", **overrides) -> dict:
    payload = {"club_id": club_id, "category_id": category_id, "holder_name": holder_name}
    payload.update(overrides)
    return get_success_data(api_client.create_membership(payload, _MANAGER))


def activate_membership(membership_id) -> dict:
    return get_success_data(api_client.activate_membership(membership_id, _MANAGER))


def create_and_activate_membership(club_id, category_id, holder_name="M", **overrides) -> dict:
    """Create a PENDING membership and activate it to ACTIVE. Returns the activated
    membership data."""
    m = create_membership(club_id, category_id, holder_name=holder_name, **overrides)
    return activate_membership(m["id"])


def setup_club_category(category_overrides=None, **club_overrides):
    """Active club + one category. Returns (club, category)."""
    club = create_club(**club_overrides)
    cat = create_category(club["id"], **(category_overrides or {}))
    return club, cat


def setup_club_category_member(category_overrides=None, holder_name="M", activate=True,
                               **club_overrides):
    """Club + category + one membership (activated by default).
    Returns (club, category, membership)."""
    club, cat = setup_club_category(category_overrides=category_overrides, **club_overrides)
    if activate:
        m = create_and_activate_membership(club["id"], cat["id"], holder_name=holder_name)
    else:
        m = create_membership(club["id"], cat["id"], holder_name=holder_name)
    return club, cat, m


# ---------------------------------------------------------------------------
# Resources + reservations
# ---------------------------------------------------------------------------
def create_resource(club_id, kind="COURT", label="Test Resource", **overrides) -> dict:
    payload = {"club_id": club_id, "kind": kind, "label": label}
    payload.update(overrides)
    return get_success_data(api_client.create_resource(payload, _MANAGER))


def get_resource_version(resource_id) -> int:
    data = get_success_data(api_client.get_resource(resource_id, _MANAGER))
    return data["version"]


def create_reservation(club_id, resource_id, membership_id, starts_at, ends_at,
                       expected_resource_version, party_size=None) -> dict:
    """Book a window as the owning Member (ownership-gated -> real membership_id)."""
    payload = {
        "club_id": club_id,
        "resource_id": resource_id,
        "membership_id": membership_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_resource_version": expected_resource_version,
    }
    if party_size is not None:
        payload["party_size"] = party_size
    return get_success_data(
        api_client.create_reservation(payload, make_member_headers(membership_id))
    )


def setup_reservation(category_overrides=None, kind="COURT", turnaround_minutes=0,
                      seat_capacity=None, starts_at="2026-02-01T10:00:00Z",
                      ends_at="2026-02-01T11:00:00Z", allows_golf=True):
    """Club + golf-allowing category + active Member + resource + one CONFIRMED
    reservation. Returns (club, category, membership, resource, reservation)."""
    cat_over = {"allows_golf": allows_golf}
    if category_overrides:
        cat_over.update(category_overrides)
    code = "GOLF" if allows_golf else "SOCIAL"
    cat_over.setdefault("code", code)
    club, cat, m = setup_club_category_member(category_overrides=cat_over)
    res_kwargs = {"turnaround_minutes": turnaround_minutes}
    if seat_capacity is not None:
        res_kwargs["seat_capacity"] = seat_capacity
    resource = create_resource(club["id"], kind=kind, label="R", **res_kwargs)
    rsv = create_reservation(
        club["id"], resource["id"], m["id"], starts_at, ends_at, resource["version"],
    )
    return club, cat, m, resource, rsv


# ---------------------------------------------------------------------------
# Chits
# ---------------------------------------------------------------------------
def post_chit(club_id, membership_id, amount_cents, kind) -> dict:
    payload = {
        "club_id": club_id,
        "membership_id": membership_id,
        "amount_cents": amount_cents,
        "kind": kind,
    }
    return get_success_data(api_client.create_chit(payload, _CLERK))


# ---------------------------------------------------------------------------
# Guest passes
# ---------------------------------------------------------------------------
def register_guest_pass(club_id, sponsor_membership_id, guest_name="G",
                        visit_date="2026-01-05T12:00:00Z") -> dict:
    """Register a guest pass as the sponsoring Member (ownership-gated)."""
    payload = {
        "club_id": club_id,
        "sponsor_membership_id": sponsor_membership_id,
        "guest_name": guest_name,
        "visit_date": visit_date,
    }
    return get_success_data(
        api_client.create_guest_pass(payload, make_member_headers(sponsor_membership_id))
    )


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------
def create_waitlist_entry(club_id, category_id, applicant_name="W") -> dict:
    payload = {"club_id": club_id, "category_id": category_id, "applicant_name": applicant_name}
    return get_success_data(api_client.create_waitlist_entry(payload, _MANAGER))


def offer_waitlist_entry(entry_id) -> dict:
    return get_success_data(api_client.offer_waitlist_entry(entry_id, _MANAGER))


def get_category_version(category_id) -> int:
    data = get_success_data(api_client.get_category(category_id, _MANAGER))
    return data["version"]


# ---------------------------------------------------------------------------
# Capital assessments
# ---------------------------------------------------------------------------
def create_assessment(club_id, total_target_cents, allocation_basis,
                      description="Assessment") -> dict:
    payload = {
        "club_id": club_id,
        "description": description,
        "total_target_cents": total_target_cents,
        "allocation_basis": allocation_basis,
    }
    return get_success_data(api_client.create_assessment(payload, _MANAGER))


# ---------------------------------------------------------------------------
# Tier 4 / 5: billing-period mechanics (open-statements + close-period)
# ---------------------------------------------------------------------------
def get_club_version(club_id) -> int:
    data = get_success_data(api_client.get_club(club_id, _MANAGER))
    return data["version"]


def open_statements(club_id) -> None:
    get_success_data(api_client.open_statements(club_id, _MANAGER))


def close_period(club_id) -> dict:
    """Open statements for the current period, then close it. The close carries the
    OCC field expected_club_version read fresh from the club (PRD §3.7)."""
    open_statements(club_id)
    version = get_club_version(club_id)
    return get_success_data(
        api_client.close_period(club_id, {"expected_club_version": version}, _MANAGER)
    )


def get_period_statement(club_id, membership_id, period_index) -> dict:
    """Fetch the single statement for this membership in a given period. Asserts
    exactly one exists."""
    body = get_success_data(
        api_client.list_statements(
            _MANAGER,
            params={"membership_id": membership_id, "club_id": club_id,
                    "period_index": period_index},
        )
    )
    stmts = [s for s in body if s["period_index"] == period_index]
    assert len(stmts) >= 1, (
        f"Setup expected a statement for membership {membership_id} "
        f"in period {period_index}, found none"
    )
    return stmts[0]


def get_member_assessment_charge(membership_id) -> dict:
    """Fetch the single AssessmentCharge for a membership. Asserts exactly one."""
    body = get_success_data(
        api_client.list_assessment_charges(_MANAGER, params={"membership_id": membership_id})
    )
    assert len(body) >= 1, f"Setup expected an assessment charge for {membership_id}"
    return body[0]


def list_member_chits(membership_id) -> list:
    return get_success_data(
        api_client.list_chits(_MANAGER, params={"membership_id": membership_id})
    )


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _MANAGER))
