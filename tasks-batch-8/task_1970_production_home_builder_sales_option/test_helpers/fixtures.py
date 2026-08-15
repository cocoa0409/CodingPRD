"""Composite setup helpers.

Most claims in this PRD require the system to be in a specific posture: a
SELLING community with an ACTIVE price phase, a RELEASED lot under a buyer's
reservation hold, a signed agreement mid-contingencies, a close-ready contract
with five completed milestones. These helpers encapsulate the multi-step
chains so tests stay focused on assertions.

All helpers hit the live API through the shared client and use the lenient
setup validator, so a broken precondition surfaces as a clear "Setup step
failed" error naming the failing call. Every helper builds its preconditions
from scratch against the freshly restarted server (empty database, logical
clock at the PRD §2.6 startup value).

Canonical scenario numbers (used throughout): phase P1 (uplift 0.03) ACTIVE at
the default clock; plan Maple 35,000,000 with elevations A(0)/B(250,000); lot
L-101 CORNER base 8,000,000 view 200,000 -> release price 9,991,000; buyer
Bea reserves, drafts, and signs -> provisional total 45,241,000.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_buyer_payload,
    create_cancel_payload,
    create_clock_payload,
    create_community_payload,
    create_contingency_clearance_payload,
    create_decide_payload,
    create_incentive_request_payload,
    create_lot_payload,
    create_option_catalog_item_payload,
    create_option_selection_payload,
    create_plan_payload,
    create_price_phase_payload,
)
from .test_users import TEST_USERS, make_buyer_headers

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["sales_director_headers"]
AGENT = TEST_USERS["sales_agent_headers"]
MANAGER = TEST_USERS["construction_manager_headers"]

QUARTZ_ITEM = dict(
    option_name="Quartz Counters", category="KITCHEN", price_cents=800_000,
    cutoff_stage="FOUNDATION", install_stage="DRYWALL",
)
EV_ITEM = dict(
    option_name="EV Outlet", category="ELECTRICAL", price_cents=150_000,
    cutoff_stage="DRYWALL", install_stage="FINAL_WALKTHROUGH",
)


# --- Logical clock -----------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """PlatformAdmin sets the logical clock, running the scheduled sweep."""
    return get_success_data(
        api_client.set_clock(create_clock_payload(to_iso8601), ADMIN)
    )


# --- Tier 1: single-entity creators ------------------------------------------

def create_community(name="Cedar Ridge", budget=1_000_000, **overrides) -> dict:
    return get_success_data(
        api_client.create_community(
            create_community_payload(
                name=name, incentive_budget_total_cents=budget, **overrides
            ),
            DIRECTOR,
        ),
        201,
    )


def get_community(community_id) -> dict:
    return get_success_data(api_client.get_community(community_id, AGENT))


def open_sales(community_id) -> dict:
    """Move a community SETUP -> SELLING; returns the updated community."""
    return get_success_data(api_client.open_community_sales(community_id, DIRECTOR))


def create_price_phase(community_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_price_phase(
            create_price_phase_payload(community_id, **overrides), DIRECTOR
        ),
        201,
    )


def create_plan(community_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan(create_plan_payload(community_id, **overrides),
                               DIRECTOR),
        201,
    )


def create_option_item(community_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_option_catalog_item(
            create_option_catalog_item_payload(community_id, **overrides), DIRECTOR
        ),
        201,
    )


def create_lot(community_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(create_lot_payload(community_id, **overrides),
                              DIRECTOR),
        201,
    )


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, AGENT))


def release_lot(lot_id) -> dict:
    """DRAFT -> RELEASED; computes and freezes release_price_cents."""
    return get_success_data(api_client.release_lot(lot_id, DIRECTOR))


def register_buyer(full_name="Bea Buyer", email="bea@example.com",
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_buyer(
            create_buyer_payload(full_name=full_name, email=email, **overrides),
            ANON,
        ),
        201,
    )


def reserve_lot(lot_id, buyer_id) -> dict:
    """Buyer reserves a RELEASED lot; returns the RESERVED lot."""
    return get_success_data(
        api_client.reserve_lot(
            lot_id, {"buyer_id": buyer_id}, make_buyer_headers(buyer_id)
        )
    )


def release_reservation(lot_id, headers) -> dict:
    return get_success_data(api_client.release_lot_reservation(lot_id, headers))


def get_agreement(agreement_id) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, AGENT))


def sign_agreement(agreement_id, buyer_id) -> dict:
    return get_success_data(
        api_client.sign_agreement(agreement_id, make_buyer_headers(buyer_id))
    )


def clear_contingency(agreement_id, expected_version, contingency_type,
                      action="CLEARED") -> dict:
    return get_success_data(
        api_client.clear_contingency(
            agreement_id,
            create_contingency_clearance_payload(
                contingency_type, action, expected_version
            ),
            AGENT,
        )
    )


def cancel_agreement(agreement_id, reason, headers) -> dict:
    return get_success_data(
        api_client.cancel_agreement(
            agreement_id, create_cancel_payload(reason), headers
        )
    )


def close_agreement(agreement_id) -> dict:
    return get_success_data(api_client.close_agreement(agreement_id, AGENT))


def create_selection(agreement_id, option_item_id, buyer_id,
                     quantity=1) -> dict:
    return get_success_data(
        api_client.create_option_selection(
            create_option_selection_payload(
                agreement_id, option_item_id, quantity=quantity
            ),
            make_buyer_headers(buyer_id),
        ),
        201,
    )


def get_selection(selection_id) -> dict:
    return get_success_data(api_client.get_option_selection(selection_id, AGENT))


def confirm_selection(selection_id, buyer_id) -> dict:
    return get_success_data(
        api_client.confirm_selection(selection_id, make_buyer_headers(buyer_id))
    )


def unconfirm_selection(selection_id, buyer_id) -> dict:
    return get_success_data(
        api_client.unconfirm_selection(selection_id, make_buyer_headers(buyer_id))
    )


def cancel_selection(selection_id, buyer_id) -> dict:
    return get_success_data(
        api_client.cancel_selection(selection_id, make_buyer_headers(buyer_id))
    )


def create_incentive(agreement_id, amount_cents,
                     incentive_type="RATE_BUYDOWN") -> dict:
    return get_success_data(
        api_client.create_incentive_request(
            create_incentive_request_payload(
                agreement_id, incentive_type=incentive_type,
                amount_cents=amount_cents,
            ),
            AGENT,
        ),
        201,
    )


def get_incentive(request_id) -> dict:
    return get_success_data(api_client.get_incentive_request(request_id, AGENT))


def decide_incentive(request_id, action) -> dict:
    return get_success_data(
        api_client.decide_incentive_request(
            request_id, create_decide_payload(action), DIRECTOR
        )
    )


# --- Tier 2: scenario bundles -------------------------------------------------

def setup_community_selling(budget=1_000_000, with_phase=True,
                            name="Cedar Ridge") -> dict:
    """Community created and opened for sales, optionally with phase P1 ACTIVE
    at the default clock. Returns {"community", "phase"}."""
    community = create_community(name=name, budget=budget)
    community = open_sales(community["id"])
    phase = (
        create_price_phase(community["id"]) if with_phase else None
    )
    return {"community": community, "phase": phase}


def setup_released_scenario(budget=1_000_000, with_phase=True, with_plan=True,
                            with_quartz=False, with_ev=False,
                            lot_overrides=None) -> dict:
    """SELLING community (+P1) + catalog + lot L-101 RELEASED + buyer Bea.
    Returns bundle dict with community, phase, plan, quartz, ev, lot, buyer."""
    bundle = setup_community_selling(budget=budget, with_phase=with_phase)
    community_id = bundle["community"]["id"]
    if with_plan:
        bundle["plan"] = create_plan(community_id)
    if with_quartz:
        bundle["quartz"] = create_option_item(community_id, **QUARTZ_ITEM)
    if with_ev:
        bundle["ev"] = create_option_item(community_id, **EV_ITEM)
    lot = create_lot(community_id, **(lot_overrides or {}))
    bundle["lot"] = release_lot(lot["id"])
    bundle["buyer"] = register_buyer()
    return bundle


def setup_reserved_scenario(**kwargs) -> dict:
    """Bundle plus Bea holding a reservation on L-101. Adds lot_version (the
    lot's current version after the reserve, for agreement OCC)."""
    bundle = setup_released_scenario(**kwargs)
    lot = reserve_lot(bundle["lot"]["id"], bundle["buyer"]["id"])
    bundle["lot"] = lot
    bundle["lot_version"] = lot["version"]
    return bundle


def setup_draft_agreement(agreement_overrides=None, **kwargs) -> dict:
    """Bundle plus a DRAFT purchase agreement against the reserved lot."""
    bundle = setup_reserved_scenario(**kwargs)
    payload = create_agreement_payload(
        buyer_id=bundle["buyer"]["id"],
        lot_id=bundle["lot"]["id"],
        plan_id=bundle["plan"]["id"],
        expected_lot_version=bundle["lot_version"],
        **(agreement_overrides or {}),
    )
    bundle["agreement"] = get_success_data(
        api_client.create_agreement(payload, AGENT), 201
    )
    return bundle


def setup_signed_agreement(agreement_overrides=None, **kwargs) -> dict:
    """Bundle plus a signed agreement in PENDING_CONTINGENCIES (lot SOLD, five
    milestones created)."""
    bundle = setup_draft_agreement(agreement_overrides, **kwargs)
    bundle["agreement"] = sign_agreement(
        bundle["agreement"]["id"], bundle["buyer"]["id"]
    )
    bundle["lot"] = get_lot(bundle["lot"]["id"])
    return bundle


def clear_all_pending_contingencies(agreement_id,
                                    action="CLEARED") -> dict:
    """Clear (or waive) every still-PENDING tracker, re-reading the agreement
    version before each OCC-guarded clearance. Returns the final agreement."""
    for ctype in ("financing", "appraisal", "sale_of_home"):
        agreement = get_agreement(agreement_id)
        if agreement[f"{ctype}_contingency_status"] == "PENDING":
            clear_contingency(agreement_id, agreement["version"], ctype, action)
    return get_agreement(agreement_id)


def setup_cleared_agreement(**kwargs) -> dict:
    """Bundle plus agreement promoted to CONTINGENCIES_CLEARED."""
    bundle = setup_signed_agreement(**kwargs)
    bundle["agreement"] = clear_all_pending_contingencies(
        bundle["agreement"]["id"]
    )
    return bundle


# --- Tier 3: milestones --------------------------------------------------------

def list_agreement_milestones(agreement_id) -> list:
    """The agreement's milestones in construction sequence order."""
    data, _meta = validate_paginated(
        api_client.list_milestones(AGENT, params={"agreement_id": agreement_id})
    )
    return data


def complete_milestones_in_order(agreement_id, count) -> list:
    """Complete the first `count` still-unstarted milestones in sequence
    order. Re-lists on every call, so repeated calls advance further.
    Returns the completed milestone payloads (in completion order)."""
    milestones = list_agreement_milestones(agreement_id)
    remaining = [m for m in milestones if m["status"] == "NOT_STARTED"]
    completed = []
    for milestone in remaining[:count]:
        completed.append(
            get_success_data(
                api_client.complete_milestone(milestone["id"], MANAGER)
            )
        )
    return completed


# --- Tier 4/5: close-ready and closed agreements -------------------------------

def setup_close_ready(**kwargs) -> dict:
    """CONTINGENCIES_CLEARED agreement with all five milestones COMPLETE."""
    bundle = setup_cleared_agreement(**kwargs)
    bundle["milestones"] = complete_milestones_in_order(
        bundle["agreement"]["id"], 5
    )
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    return bundle


def setup_closed_agreement(**kwargs) -> dict:
    """Full lifecycle through CLOSED: contingencies cleared, all milestones
    complete, close succeeded (final price set, warranty ENROLLED, lot CLOSED)."""
    bundle = setup_close_ready(**kwargs)
    bundle["agreement"] = close_agreement(bundle["agreement"]["id"])
    bundle["lot"] = get_lot(bundle["lot"]["id"])
    return bundle
