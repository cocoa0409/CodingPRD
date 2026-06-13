"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test). These helpers build multi-step preconditions from scratch
using only PRD-declared endpoints, threading the real RoommateProfile id into
ownership-gated calls (manager activations, member move-outs, etc.).

All setup calls use get_success_data() (the lenient validator) so a broken
precondition surfaces as a clear "Setup step failed" error rather than a
confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_profile_payload,
    create_listing_payload,
    create_match_request_payload,
    create_bill_payload,
    create_expense_payload,
    create_settlement_payload,
)
from .test_users import (
    make_roommate_headers,
    make_mediator_headers,
    make_operator_headers,
)


# ─── Primitive creators ──────────────────────────────────

def create_profile(api=api_client, **overrides) -> dict:
    """Register a RoommateProfile. Returns the created profile object."""
    payload = create_profile_payload(**overrides)
    resp = api.create_profile(payload)
    return get_success_data(resp)


def create_listing(api, lister, **overrides) -> dict:
    """Create a RoomListing owned by `lister` (a profile dict). Returns the listing."""
    payload = create_listing_payload(lister["id"], **overrides)
    resp = api.create_listing(payload, make_roommate_headers(lister["id"]))
    return get_success_data(resp)


def set_clock(api, iso: str):
    """Advance the server clock to an ISO instant (PlatformOperator capability)."""
    return get_success_data(api.set_clock(iso, make_operator_headers()))


# ─── Core composite: a household with N ACTIVE members ────

def build_household_with_members(
    api,
    member_specs,
    listing_overrides=None,
    clock=None,
):
    """Build an ACTIVE household occupied by len(member_specs) ACTIVE members.

    member_specs: list of dicts, each passed as overrides to create_profile_payload
                  for one applicant (ordered M1, M2, ...). Order of activation
                  follows this list, which fixes membership created_at ordering.
    listing_overrides: overrides for the RoomListing (split_policy, capacity, ...).
    clock: optional ISO instant to set BEFORE any listing/membership work.

    Returns dict with keys:
      lister   -> manager profile dict
      listing  -> listing dict
      household-> household dict (re-fetched, ACTIVE)
      members  -> list of member profile dicts (M1, M2, ...)
      memberships -> list of membership dicts aligned with members
    """
    listing_overrides = listing_overrides or {}

    lister = create_profile(api, full_name="Lister")
    if clock is not None:
        set_clock(api, clock)

    listing = create_listing(api, lister, **listing_overrides)
    lister_headers = make_roommate_headers(lister["id"])

    members = []
    memberships = []
    household_id = None

    for spec in member_specs:
        member = create_profile(api, **spec)
        members.append(member)

        mr = get_success_data(
            api.create_match_request(
                create_match_request_payload(listing["id"], member["id"]),
                make_roommate_headers(member["id"]),
            )
        )
        get_success_data(api.accept_match_request(mr["id"], lister_headers))

        if household_id is None:
            households = get_success_data(
                api.list_households(lister_headers, params={"manager_id": lister["id"]})
            )
            household_id = households[0]["id"]

        mem_list = get_success_data(
            api.list_memberships(
                lister_headers,
                params={"profile_id": member["id"], "household_id": household_id},
            )
        )
        membership = mem_list[0]
        get_success_data(api.activate_membership(membership["id"], lister_headers))
        # Re-fetch so the returned membership reflects ACTIVE status / proration fields.
        membership = get_success_data(api.get_membership(membership["id"], lister_headers))
        memberships.append(membership)

    household = get_success_data(api.get_household(household_id, lister_headers))
    return {
        "lister": lister,
        "listing": listing,
        "household": household,
        "members": members,
        "memberships": memberships,
    }


# ─── Higher-level scenario helpers ───────────────────────

def issue_rent_bill(api, env, total_amount_cents=200_000,
                    period_start="2026-06-01T00:00:00.000Z",
                    period_end="2026-06-30T00:00:00.000Z"):
    """Issue a RENT bill for the household in `env`. Returns the bill dict."""
    payload = create_bill_payload(
        env["household"]["id"],
        bill_type="RENT",
        total_amount_cents=total_amount_cents,
        period_start=period_start,
        period_end=period_end,
    )
    resp = api.create_bill(payload, make_roommate_headers(env["lister"]["id"]))
    return get_success_data(resp)


def issue_utilities_bill(api, env, total_amount_cents,
                         period_start="2026-07-01T00:00:00.000Z",
                         period_end="2026-07-31T00:00:00.000Z"):
    """Issue a UTILITIES bill for the household in `env`. Returns the bill dict."""
    payload = create_bill_payload(
        env["household"]["id"],
        bill_type="UTILITIES",
        total_amount_cents=total_amount_cents,
        period_start=period_start,
        period_end=period_end,
    )
    resp = api.create_bill(payload, make_roommate_headers(env["lister"]["id"]))
    return get_success_data(resp)


def post_expense(api, env, payer, participants, total_amount_cents=9_000,
                 split_mode="EQUAL", share_overrides=None, description="expense"):
    """Log a POSTED expense. payer/participants are profile dicts. Returns expense."""
    payload = create_expense_payload(
        env["household"]["id"],
        payer["id"],
        [p["id"] for p in participants],
        total_amount_cents=total_amount_cents,
        split_mode=split_mode,
        description=description,
    )
    if share_overrides is not None:
        payload["share_overrides"] = share_overrides
    resp = api.create_expense(payload, make_roommate_headers(payer["id"]))
    return get_success_data(resp)


def propose_settlement(api, env, debtor, creditor, amount_cents):
    """Propose a settlement from debtor->creditor. Returns the settlement dict."""
    payload = create_settlement_payload(
        env["household"]["id"], debtor["id"], creditor["id"], amount_cents
    )
    resp = api.create_settlement(payload, make_roommate_headers(debtor["id"]))
    return get_success_data(resp)


def current_household_version(api, env):
    """Re-fetch the household and return its current version (for OCC confirms)."""
    hh = get_success_data(
        api.get_household(env["household"]["id"], make_roommate_headers(env["lister"]["id"]))
    )
    return hh["version"]


def file_dispute_on_expense(api, env, filer, expense, reason="dispute"):
    """File a Dispute against an expense (filer is a profile dict). Returns dispute."""
    payload = {
        "household_id": env["household"]["id"],
        "expense_id": expense["id"],
        "filed_by_id": filer["id"],
        "reason": reason,
    }
    resp = api.create_dispute(payload, make_roommate_headers(filer["id"]))
    return get_success_data(resp)


def claim_dispute(api, dispute, mediator_id="med-1"):
    """A mediator claims the dispute (drives household to FROZEN). Returns dispute."""
    resp = api.claim_dispute(dispute["id"], make_mediator_headers(mediator_id))
    return get_success_data(resp)


def freeze_household_via_dispute(api, env, filer, expense, mediator_id="med-1"):
    """File a dispute on `expense` by `filer` and have a mediator claim it,
    leaving the household FROZEN. Returns the OPEN->UNDER_REVIEW dispute dict."""
    dispute = file_dispute_on_expense(api, env, filer, expense)
    return claim_dispute(api, dispute, mediator_id=mediator_id)
