"""
Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch through the public endpoints only.  Setup calls use
the lenient success reader; the assertions that matter belong to the test.

The logical clock is set explicitly wherever a helper's outcome depends on it:
"Before any call to this endpoint the logical clock reads exactly
`2026-08-01T00:00:00Z`."
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    DIRECTOR_HEADERS,
    FLOOR_MANAGER_HEADERS,
    REGISTRANT_HEADERS,
    SALES_REP_HEADERS,
    make_director_headers,
    make_exhibitor_headers,
)
from .types import ShowStatus

# The clock instant every composite fixture works from unless told otherwise.
SETUP_CLOCK = "2026-08-15T00:00:00Z"


# ─── Tier 0: primitives ─────────────────────────────────────────────────────
def set_clock(client: ApiClient, current_utc: str = SETUP_CLOCK,
              headers: Optional[Dict[str, str]] = None) -> None:
    """Move the server's logical clock; no business row is touched."""
    response = client.set_clock(
        f.clock_payload(current_utc), headers or DIRECTOR_HEADERS
    )
    assert response.status_code == 200, response.text


def show_version(client: ApiClient, show_id: str,
                 headers: Optional[Dict[str, str]] = None) -> int:
    """Read the live `version` that every inventory-consuming write must pin."""
    show = get_success_data(
        client.get_show(show_id, headers or DIRECTOR_HEADERS)
    )
    return show["version"]


def read_show(client: ApiClient, show_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(client.get_show(show_id, headers or DIRECTOR_HEADERS))


def read_booth(client: ApiClient, booth_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(client.get_booth(booth_id, headers or DIRECTOR_HEADERS))


def read_contract(client: ApiClient, contract_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        client.get_space_contract(contract_id, headers or DIRECTOR_HEADERS)
    )


def read_exhibitor(client: ApiClient, exhibitor_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        client.get_exhibitor(exhibitor_id, headers or DIRECTOR_HEADERS)
    )


def read_deal(client: ApiClient, deal_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        client.get_sponsorship_deal(deal_id, headers or DIRECTOR_HEADERS)
    )


def read_obligations(client: ApiClient, deal_id: str,
                     headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    response = client.list_obligations(deal_id, headers or DIRECTOR_HEADERS,
                                       {"limit": 100})
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"]


# ─── Tier 1: state progression ──────────────────────────────────────────────
def draft_venue_contract(client: ApiClient,
                         headers: Optional[Dict[str, str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """A venue contract in its initial `DRAFT` status."""
    return get_success_data(
        client.create_venue_contract(
            f.venue_contract_payload(**overrides), headers or DIRECTOR_HEADERS
        )
    )


def executed_venue_contract(client: ApiClient,
                            headers: Optional[Dict[str, str]] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """`DRAFT -> EXECUTED`, which is what unlocks show creation."""
    hdr = headers or DIRECTOR_HEADERS
    contract = draft_venue_contract(client, hdr, **overrides)
    return get_success_data(client.execute_venue_contract(contract["id"], hdr))


def planning_show(client: ApiClient,
                  venue_contract: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None,
                  vc_overrides: Optional[Dict[str, Any]] = None,
                  **show_overrides: Any) -> Dict[str, Any]:
    """
    An executed venue contract plus one edition in `PLANNING`.

    Returns {"venue_contract": ..., "show": ...}.
    """
    hdr = headers or DIRECTOR_HEADERS
    vc = venue_contract or executed_venue_contract(client, hdr, **(vc_overrides or {}))
    show = get_success_data(
        client.create_show(f.show_payload(vc["id"], **show_overrides), hdr)
    )
    return {"venue_contract": vc, "show": show}


def show_with_booths(client: ApiClient,
                     booth_payloads: Optional[List[Dict[str, Any]]] = None,
                     venue_contract: Optional[Dict[str, Any]] = None,
                     headers: Optional[Dict[str, str]] = None,
                     vc_overrides: Optional[Dict[str, Any]] = None,
                     **show_overrides: Any) -> Dict[str, Any]:
    """
    A `PLANNING` edition with its floor plan laid out but not yet published.

    Returns {"venue_contract", "show", "booths", "booth_by_number"} where the
    booth rows are in creation order.
    """
    hdr = headers or DIRECTOR_HEADERS
    env = planning_show(client, venue_contract, hdr, vc_overrides, **show_overrides)
    payloads = booth_payloads if booth_payloads is not None else [
        f.booth_payload("A100", 20, 20),
        f.inline_booth_payload("C050", 10, 20),
    ]
    booths = [
        get_success_data(client.create_booth(env["show"]["id"], payload, hdr))
        for payload in payloads
    ]
    env["booths"] = booths
    env["booth_by_number"] = {b["booth_number"]: b for b in booths}
    env["show"] = read_show(client, env["show"]["id"], hdr)
    return env


def published_show(client: ApiClient,
                   booth_payloads: Optional[List[Dict[str, Any]]] = None,
                   venue_contract: Optional[Dict[str, Any]] = None,
                   headers: Optional[Dict[str, str]] = None,
                   vc_overrides: Optional[Dict[str, Any]] = None,
                   **show_overrides: Any) -> Dict[str, Any]:
    """`PLANNING -> SPACE_SELECTION`: the floor plan is frozen and selling can start."""
    hdr = headers or DIRECTOR_HEADERS
    env = show_with_booths(client, booth_payloads, venue_contract, hdr,
                           vc_overrides, **show_overrides)
    env["show"] = get_success_data(
        client.publish_floor_plan(env["show"]["id"], hdr)
    )
    return env


def selling_show(client: ApiClient,
                 booth_payloads: Optional[List[Dict[str, Any]]] = None,
                 venue_contract: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None,
                 vc_overrides: Optional[Dict[str, Any]] = None,
                 **show_overrides: Any) -> Dict[str, Any]:
    """`SPACE_SELECTION -> SELLING`."""
    hdr = headers or DIRECTOR_HEADERS
    env = published_show(client, booth_payloads, venue_contract, hdr,
                         vc_overrides, **show_overrides)
    env["show"] = transition(client, env["show"]["id"], ShowStatus.SELLING, hdr)
    return env


def transition(client: ApiClient, show_id: str, target_status: str,
               headers: Optional[Dict[str, str]] = None,
               **overrides: Any) -> Dict[str, Any]:
    """Drive one lifecycle step of an edition."""
    return get_success_data(
        client.transition_show(
            show_id, f.transition_payload(target_status, **overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def take_show_on_site(client: ApiClient, show_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """`SELLING -> ON_SITE`, the only status under which the floor runs."""
    return transition(client, show_id, ShowStatus.ON_SITE, headers)


# ─── Tier 2: entity hierarchy ───────────────────────────────────────────────
def exhibitor(client: ApiClient, legal_name: str = "Atlas Kitchenware LLC",
              headers: Optional[Dict[str, str]] = None,
              **overrides: Any) -> Dict[str, Any]:
    """An `ACTIVE` exhibitor with every point counter at zero."""
    return get_success_data(
        client.create_exhibitor(
            f.exhibitor_payload(legal_name=legal_name, **overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def exhibitor_with_ledger_points(client: ApiClient, points: int,
                                 legal_name: str = "Atlas Kitchenware LLC",
                                 reason: str = "Migrated loyalty balance",
                                 headers: Optional[Dict[str, str]] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    """An exhibitor whose `ledger_points` were seeded by a manual adjustment."""
    hdr = headers or DIRECTOR_HEADERS
    row = exhibitor(client, legal_name, hdr, **overrides)
    return get_success_data(
        client.adjust_priority_points(
            row["id"], f.point_adjustment_payload(points, reason), hdr
        )
    )


def scheduled_appointment(client: ApiClient, show_id: str, exhibitor_id: str,
                          round_index: int = 1,
                          window_start: str = "2027-01-10T09:00:00Z",
                          window_end: str = "2027-01-10T11:00:00Z",
                          headers: Optional[Dict[str, str]] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """A selection slot in its initial `SCHEDULED` state."""
    return get_success_data(
        client.create_selection_appointment(
            show_id,
            f.appointment_payload(exhibitor_id, round_index, window_start,
                                  window_end, **overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def active_appointment(client: ApiClient, show_id: str, exhibitor_id: str,
                       round_index: int = 1,
                       window_start: str = "2027-01-10T09:00:00Z",
                       window_end: str = "2027-01-10T11:00:00Z",
                       headers: Optional[Dict[str, str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """
    A slot booked and then activated by opening its round, which is what makes it
    exercisable.
    """
    hdr = headers or DIRECTOR_HEADERS
    appointment = scheduled_appointment(client, show_id, exhibitor_id, round_index,
                                        window_start, window_end, hdr, **overrides)
    for _ in range(round_index):
        client.advance_selection_round(show_id, hdr)
    return get_success_data(
        client.get_selection_appointment(appointment["id"], hdr)
    )


# ─── Tier 3: full-lifecycle shortcuts ───────────────────────────────────────
def offered_contract(client: ApiClient, show_id: str, exhibitor_id: str,
                     requested_sqft: int,
                     booth_ids: Optional[List[str]] = None,
                     headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """A direct-sale contract in `OFFERED` with its booths `HELD` and priced."""
    hdr = headers or SALES_REP_HEADERS
    payload = f.space_contract_payload(
        show_id, exhibitor_id, show_version(client, show_id, hdr), requested_sqft,
        **overrides,
    )
    if booth_ids is not None:
        payload["booth_ids"] = booth_ids
    return get_success_data(client.create_space_contract(payload, hdr))


def sign_contract(client: ApiClient, contract: Dict[str, Any],
                  deposit_paid_cents: Optional[int] = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Sign an `OFFERED` contract as its owning exhibitor, tendering exactly the
    minimum deposit unless another figure is asked for.
    """
    hdr = headers or make_exhibitor_headers(contract["exhibitor_id"])
    deposit = (
        contract["min_deposit_cents"] if deposit_paid_cents is None
        else deposit_paid_cents
    )
    return get_success_data(
        client.sign_space_contract(
            contract["id"],
            f.sign_payload(show_version(client, contract["show_id"], hdr), deposit),
            hdr,
        )
    )


def signed_contract(client: ApiClient, show_id: str, exhibitor_id: str,
                    requested_sqft: int,
                    booth_ids: Optional[List[str]] = None,
                    deposit_paid_cents: Optional[int] = None,
                    headers: Optional[Dict[str, str]] = None,
                    **overrides: Any) -> Dict[str, Any]:
    """Open a contract and sign it: booths land `ASSIGNED` and points are awarded."""
    contract = offered_contract(client, show_id, exhibitor_id, requested_sqft,
                                booth_ids, headers, **overrides)
    return sign_contract(client, contract, deposit_paid_cents)


def signed_contract_env(client: ApiClient,
                        booth_payloads: Optional[List[Dict[str, Any]]] = None,
                        requested_sqft: int = 400,
                        booth_numbers: Optional[List[str]] = None,
                        legal_name: str = "Atlas Kitchenware LLC",
                        clock: str = SETUP_CLOCK,
                        headers: Optional[Dict[str, str]] = None,
                        vc_overrides: Optional[Dict[str, Any]] = None,
                        **show_overrides: Any) -> Dict[str, Any]:
    """
    The whole backbone in one call: clock, executed venue contract, published
    edition with booths, exhibitor, and one `SIGNED` space contract.

    Returns {"venue_contract", "show", "booths", "booth_by_number", "exhibitor",
             "contract", "exhibitor_headers"}.
    """
    hdr = headers or DIRECTOR_HEADERS
    set_clock(client, clock, hdr)
    env = published_show(client, booth_payloads, None, hdr, vc_overrides,
                         **show_overrides)
    ex = exhibitor(client, legal_name, hdr)
    booth_ids = (
        [env["booth_by_number"][n]["id"] for n in booth_numbers]
        if booth_numbers else None
    )
    env["exhibitor"] = ex
    env["exhibitor_headers"] = make_exhibitor_headers(ex["id"])
    env["contract"] = signed_contract(
        client, env["show"]["id"], ex["id"], requested_sqft, booth_ids
    )
    env["show"] = read_show(client, env["show"]["id"], hdr)
    return env


# ─── Tier 3 (continued): sponsorship, services, citations, registrations ─────
def sponsorship_package(client: ApiClient, show_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """Sponsorship inventory with its price floor, obligation codes and unit count."""
    return get_success_data(
        client.create_sponsorship_package(
            show_id, f.sponsorship_package_payload(**overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def proposed_deal(client: ApiClient, package_id: str, exhibitor_id: str,
                  negotiated_price_cents: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A `PROPOSED` deal, which is what consumes the inventory unit."""
    return get_success_data(
        client.create_sponsorship_deal(
            package_id,
            f.sponsorship_deal_payload(exhibitor_id, negotiated_price_cents),
            headers or SALES_REP_HEADERS,
        )
    )


def signed_deal(client: ApiClient, package_id: str, exhibitor_id: str,
                negotiated_price_cents: int,
                proposer_headers: Optional[Dict[str, str]] = None,
                signer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    A `SIGNED` deal, signed by a different operator than the proposer so the
    separation-of-duties rule is satisfied; signing is what mints the obligations.
    """
    deal = proposed_deal(client, package_id, exhibitor_id, negotiated_price_cents,
                         proposer_headers or SALES_REP_HEADERS)
    return get_success_data(
        client.sign_sponsorship_deal(
            deal["id"], signer_headers or make_director_headers("u_sd_2")
        )
    )


def service_order(client: ApiClient, contract_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """A `SUBMITTED` service order priced off the show's venue agreement."""
    return get_success_data(
        client.create_service_order(
            contract_id, f.service_order_payload(**overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def open_citation(client: ApiClient, contract_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """A citation in `OPEN` with `penalty_points` still at zero."""
    return get_success_data(
        client.create_rule_violation(
            contract_id, f.rule_violation_payload(**overrides),
            headers or FLOOR_MANAGER_HEADERS,
        )
    )


def upheld_citation(client: ApiClient, contract_id: str,
                    reporter_headers: Optional[Dict[str, str]] = None,
                    adjudicator_headers: Optional[Dict[str, str]] = None,
                    **overrides: Any) -> Dict[str, Any]:
    """
    A citation written and then upheld by a different operator, which is what
    charges the exhibitor's penalty points.
    """
    citation = open_citation(client, contract_id, reporter_headers, **overrides)
    return get_success_data(
        client.adjudicate(
            citation["id"], f.adjudicate_payload("UPHELD"),
            adjudicator_headers or make_director_headers("u_sd_1"),
        )
    )


def registration(client: ApiClient, show_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 **overrides: Any) -> Dict[str, Any]:
    """A registration scored and sorted in the same request that creates it."""
    return get_success_data(
        client.create_registration(
            show_id, f.registration_payload(**overrides),
            headers or DIRECTOR_HEADERS,
        )
    )


def lead_scan(client: ApiClient, contract_id: str, registration_id: str,
              scanned_at: str = "2027-03-05T10:00:00Z",
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A badge scan against a signed contract of an on-site edition."""
    return get_success_data(
        client.create_lead_scan(
            contract_id, f.lead_scan_payload(registration_id, scanned_at),
            headers or FLOOR_MANAGER_HEADERS,
        )
    )


# ─── Tier 4: accumulation and threshold targeting ───────────────────────────
def space_locked_floor(client: ApiClient,
                       clock: str = SETUP_CLOCK) -> Dict[str, Any]:
    """
    A floor whose committed ratio has crossed 85 percent, which is what puts the
    edition in `SPACE_LOCKED` without reaching the freeze.

    A 700 sqft floor holding 600 sqft commits 86 percent.
    """
    env = signed_contract_env(
        client,
        booth_payloads=[
            f.inline_booth_payload("B200", 20, 30),
            f.inline_booth_payload("D010", 10, 10),
        ],
        requested_sqft=600,
        booth_numbers=["B200"],
        clock=clock,
        gross_sqft=1000,
        aisle_ratio_pct=30,
    )
    return env


def frozen_floor(client: ApiClient, clock: str = SETUP_CLOCK) -> Dict[str, Any]:
    """
    A floor at 100 percent committed, which is what forces `FROZEN`: a single
    400 sqft booth on a floor whose sellable area is exactly 400 sqft, signed.
    """
    env = signed_contract_env(
        client,
        booth_payloads=[f.booth_payload("A100", 20, 20)],
        requested_sqft=400,
        booth_numbers=["A100"],
        clock=clock,
        gross_sqft=1000,
        aisle_ratio_pct=60,
    )
    env["show"] = read_show(client, env["show"]["id"])
    return env


def suspended_exhibitor_env(client: ApiClient,
                            clock: str = SETUP_CLOCK) -> Dict[str, Any]:
    """
    An exhibitor pushed to thirty penalty points by two upheld `SALES_CONDUCT`
    citations, which is what suspends the account.
    """
    env = signed_contract_env(client, clock=clock, requested_sqft=400,
                              booth_numbers=["A100"])
    env["show"] = transition(client, env["show"]["id"], ShowStatus.SELLING)
    env["show"] = take_show_on_site(client, env["show"]["id"])
    env["citations"] = [
        upheld_citation(client, env["contract"]["id"],
                        violation_type="SALES_CONDUCT"),
        upheld_citation(client, env["contract"]["id"],
                        violation_type="SALES_CONDUCT"),
    ]
    env["exhibitor"] = read_exhibitor(client, env["exhibitor"]["id"])
    return env


def negotiated_contract(client: ApiClient, env: Dict[str, Any],
                        requested_discount_pct: int,
                        approved_discount_pct: int,
                        reoffer_headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    """
    One full negotiation cycle on an existing offered contract: the exhibitor's
    counter followed by the producer's re-offer.
    """
    contract = env["contract"]
    ex_headers = env.get("exhibitor_headers") or make_exhibitor_headers(
        contract["exhibitor_id"]
    )
    get_success_data(
        client.negotiate(contract["id"], f.counter_payload(requested_discount_pct),
                         ex_headers)
    )
    return get_success_data(
        client.negotiate(contract["id"],
                         f.reoffer_payload(approved_discount_pct),
                         reoffer_headers or DIRECTOR_HEADERS)
    )


# ─── Tier 5: finalization and terminal states ───────────────────────────────
def closed_out_contract_env(client: ApiClient,
                            booth_payloads: Optional[List[Dict[str, Any]]] = None,
                            requested_sqft: int = 400,
                            booth_numbers: Optional[List[str]] = None,
                            clock: str = SETUP_CLOCK,
                            **show_overrides: Any) -> Dict[str, Any]:
    """
    A signed contract carried all the way through `ON_SITE` to a `CLOSED` edition,
    which is what leaves the contract `CLOSED_OUT` and rebookable.
    """
    env = signed_contract_env(client, booth_payloads, requested_sqft,
                              booth_numbers, clock=clock, **show_overrides)
    show_id = env["show"]["id"]
    transition(client, show_id, ShowStatus.SELLING)
    transition(client, show_id, ShowStatus.ON_SITE)
    env["show"] = transition(client, show_id, ShowStatus.CLOSED)
    env["contract"] = read_contract(client, env["contract"]["id"])
    env["exhibitor"] = read_exhibitor(client, env["exhibitor"]["id"])
    return env


def cancelled_contract_env(client: ApiClient,
                           booth_payloads: Optional[List[Dict[str, Any]]] = None,
                           requested_sqft: int = 400,
                           booth_numbers: Optional[List[str]] = None,
                           clock: str = SETUP_CLOCK,
                           cancel_clock: Optional[str] = None,
                           **show_overrides: Any) -> Dict[str, Any]:
    """A signed contract that the exhibitor then walks away from."""
    env = signed_contract_env(client, booth_payloads, requested_sqft,
                              booth_numbers, clock=clock, **show_overrides)
    if cancel_clock is not None:
        set_clock(client, cancel_clock)
    env["contract"] = get_success_data(
        client.cancel_space_contract(
            env["contract"]["id"], f.cancel_payload(), env["exhibitor_headers"]
        )
    )
    env["show"] = read_show(client, env["show"]["id"])
    return env


def terminated_venue_contract(client: ApiClient, venue_contract_id: str,
                              terminated_effective_date: str = "2026-09-01",
                              headers: Optional[Dict[str, str]] = None
                              ) -> Dict[str, Any]:
    """
    Terminate an executed agreement at its own pinned version, which is what fires
    the cancellation cascade down every non-terminal edition.
    """
    hdr = headers or DIRECTOR_HEADERS
    current = get_success_data(client.get_venue_contract(venue_contract_id, hdr))
    return get_success_data(
        client.terminate_venue_contract(
            venue_contract_id,
            f.terminate_payload(current["version"], terminated_effective_date),
            hdr,
        )
    )
