"""Composite setup helpers.

Because the harness restarts the API server with an empty database before every
individual test, every helper here builds its state from scratch through the
endpoints the PRD declares.  Setup steps read their result with
``get_success_data`` so a broken setup surfaces as a clear message rather than a
mysterious KeyError.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START_UTC
from .test_users import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_ALT_HEADERS,
    SPONSORSHIP_HEADERS,
    TREASURER_HEADERS,
)

Json = Dict[str, Any]


# ============================================== tier 1: single-step steps ====


def set_clock(api, instant: str, headers: Optional[Dict[str, str]] = None) -> Json:
    """Move the logical clock, which every deadline in the system reads."""
    return get_success_data(api.set_clock(instant, headers or DIRECTOR_HEADERS))


def new_outing(api, **overrides: Any) -> Json:
    return get_success_data(api.create_outing(f.outing_payload(**overrides), DIRECTOR_HEADERS))


def new_contract(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_contract(f.contract_payload(outing_id, **overrides), COURSE_HEADERS)
    )


def sign_contract(api, contract_id: str) -> Json:
    return get_success_data(
        api.contract_lifecycle(contract_id, f.contract_lifecycle_payload("SIGN"), COURSE_HEADERS)
    )


def amend_contract(api, contract_id: str, **terms: Any) -> Json:
    return get_success_data(
        api.contract_lifecycle(
            contract_id, f.contract_lifecycle_payload("AMEND", **terms), COURSE_HEADERS
        )
    )


def new_tier(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_package_tier(f.package_tier_payload(outing_id, **overrides), DIRECTOR_HEADERS)
    )


def new_sponsor_tier(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_package_tier(f.sponsor_tier_payload(outing_id, **overrides), DIRECTOR_HEADERS)
    )


def drive_play(api, outing_id: str, action: str, **overrides: Any) -> Json:
    return get_success_data(
        api.play_transition(outing_id, f.play_transition_payload(action, **overrides), DIRECTOR_HEADERS)
    )


def open_registration(api, outing_id: str) -> Json:
    return drive_play(api, outing_id, "OPEN_REGISTRATION")


def lock_field(api, outing_id: str) -> Json:
    return drive_play(api, outing_id, "LOCK_FIELD")


def reopen_field(api, outing_id: str) -> Json:
    return drive_play(api, outing_id, "OPEN_REGISTRATION")


def start_play(api, outing_id: str) -> Json:
    return drive_play(api, outing_id, "START_PLAY")


def finalize_scoring(api, outing_id: str) -> Json:
    return drive_play(api, outing_id, "FINALIZE_SCORING")


def new_registration(api, outing_id: str, tier_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_registration(
            f.registration_payload(outing_id, tier_id, **overrides), DIRECTOR_HEADERS
        )
    )


def pay_registration(
    api, registration_id: str, amount_cents: int, headers: Optional[Dict[str, str]] = None
) -> Json:
    return get_success_data(
        api.record_registration_payment(
            registration_id, f.payment_payload(amount_cents), headers or TREASURER_HEADERS
        )
    )


def check_in_registration(
    api, registration_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    """Walk a registration to CHECKED_IN — "check-in belongs to the course"."""
    return get_success_data(
        api.registration_lifecycle(
            registration_id,
            f.registration_lifecycle_payload("CHECK_IN"),
            headers or COURSE_HEADERS,
        )
    )


def new_player(api, registration_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_player(f.player_payload(registration_id, **overrides), DIRECTOR_HEADERS)
    )


def new_team(api, outing_id: str, player_ids: Sequence[str], team_name: str = "ALPHA") -> Json:
    return get_success_data(
        api.create_team(
            f.team_payload(outing_id, list(player_ids), team_name=team_name), DIRECTOR_HEADERS
        )
    )


def new_asset(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_sponsorship_asset(
            f.sponsorship_asset_payload(outing_id, **overrides), SPONSORSHIP_HEADERS
        )
    )


def withdraw_asset(api, asset_id: str) -> Json:
    return get_success_data(
        api.asset_inventory(asset_id, f.inventory_payload("WITHDRAW"), SPONSORSHIP_HEADERS)
    )


def restore_asset(api, asset_id: str) -> Json:
    return get_success_data(
        api.asset_inventory(asset_id, f.inventory_payload("RESTORE"), SPONSORSHIP_HEADERS)
    )


def new_allocation(
    api,
    registration_id: str,
    asset_id: str,
    source: str = "PACKAGE_ENTITLEMENT",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_sponsor_allocation(
            f.sponsor_allocation_payload(registration_id, asset_id, source, **overrides),
            headers or SPONSORSHIP_HEADERS,
        )
    )


def drive_fulfillment(
    api, allocation_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Json:
    return get_success_data(
        api.allocation_fulfillment(
            allocation_id,
            f.fulfillment_payload(action, **overrides),
            headers or SPONSORSHIP_HEADERS,
        )
    )


def new_contest(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_contest(f.contest_payload(outing_id, **overrides), DIRECTOR_HEADERS)
    )


def bind_contest_insurance(api, contest_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.bind_insurance(contest_id, f.insurance_payload(**overrides), SPONSORSHIP_HEADERS)
    )


def drive_contest(api, contest_id: str, action: str) -> Json:
    return get_success_data(
        api.contest_status(contest_id, f.contest_status_payload(action), DIRECTOR_HEADERS)
    )


def new_item(api, outing_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_fundraising_item(
            f.fundraising_item_payload(outing_id, **overrides), TREASURER_HEADERS
        )
    )


def sell_item(
    api,
    item_id: str,
    buyer_registration_id: str,
    bid_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    return get_success_data(
        api.record_item_sale(
            item_id,
            f.item_sale_payload(buyer_registration_id, bid_cents),
            headers or TREASURER_HEADERS,
        )
    )


def pay_item(api, item_id: str, amount_cents: int) -> Json:
    return get_success_data(
        api.record_item_payment(item_id, f.payment_payload(amount_cents), TREASURER_HEADERS)
    )


def issue_registration_receipt(
    api, outing_id: str, registration_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    return get_success_data(
        api.create_receipt(
            f.registration_receipt_payload(outing_id, registration_id),
            headers or TREASURER_HEADERS,
        )
    )


def issue_item_receipt(
    api, outing_id: str, item_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    return get_success_data(
        api.create_receipt(
            f.item_receipt_payload(outing_id, item_id), headers or TREASURER_HEADERS
        )
    )


def reverse_receipt(
    api, receipt_id: str, reason: str = "Reissued to a subsidiary",
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    return get_success_data(
        api.reverse_receipt(receipt_id, f.reversal_payload(reason), headers or TREASURER_HEADERS)
    )


# ================================================ current-version readers ====


def outing_version(api, outing_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return get_success_data(api.get_outing(outing_id, headers or DIRECTOR_HEADERS))["version"]


def registration_version(api, registration_id: str) -> int:
    return get_success_data(api.get_registration(registration_id, DIRECTOR_HEADERS))["version"]


def team_version(api, team_id: str) -> int:
    return get_success_data(api.get_team(team_id, COURSE_HEADERS))["version"]


def read_outing(api, outing_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_outing(outing_id, headers or DIRECTOR_HEADERS))


def read_contract(api, contract_id: str) -> Json:
    return get_success_data(api.get_contract(contract_id, COURSE_HEADERS))


def read_tier(api, tier_id: str) -> Json:
    return get_success_data(api.get_package_tier(tier_id, DIRECTOR_HEADERS))


def read_registration(api, registration_id: str) -> Json:
    return get_success_data(api.get_registration(registration_id, DIRECTOR_HEADERS))


def read_player(api, player_id: str) -> Json:
    return get_success_data(api.get_player(player_id, DIRECTOR_HEADERS))


def read_team(api, team_id: str) -> Json:
    return get_success_data(api.get_team(team_id, DIRECTOR_HEADERS))


def read_asset(api, asset_id: str) -> Json:
    return get_success_data(api.get_sponsorship_asset(asset_id, SPONSORSHIP_HEADERS))


def read_allocation(api, allocation_id: str) -> Json:
    return get_success_data(api.get_sponsor_allocation(allocation_id, SPONSORSHIP_HEADERS))


def read_contest(api, contest_id: str) -> Json:
    return get_success_data(api.get_contest(contest_id, DIRECTOR_HEADERS))


def read_item(api, item_id: str) -> Json:
    return get_success_data(api.get_fundraising_item(item_id, TREASURER_HEADERS))


def read_receipt(api, receipt_id: str) -> Json:
    return get_success_data(api.get_receipt(receipt_id, TREASURER_HEADERS))


# ============================================ tier 2: entity hierarchies =====


def signed_contract_outing(
    api,
    clock: Optional[str] = CLOCK_START_UTC,
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
) -> Json:
    """An outing in DRAFT whose course contract has been signed."""
    if clock is not None:
        set_clock(api, clock)
    o = new_outing(api, **(outing or {}))
    c = new_contract(api, o["id"], **(contract or {}))
    c = sign_contract(api, c["id"])
    return {"outing": o, "contract": c, "outing_id": o["id"], "contract_id": c["id"]}


def open_outing(
    api,
    clock: Optional[str] = CLOCK_START_UTC,
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    sponsor_tier: bool = False,
) -> Json:
    """A signed, tiered outing whose play dimension has been driven to OPEN."""
    ctx = signed_contract_outing(api, clock=clock, outing=outing, contract=contract)
    if sponsor_tier:
        t = new_sponsor_tier(api, ctx["outing_id"], **(tier or {}))
    else:
        t = new_tier(api, ctx["outing_id"], **(tier or {}))
    ctx["tier"] = t
    ctx["tier_id"] = t["id"]
    ctx["tiers"] = [t]
    ctx["outing"] = open_registration(api, ctx["outing_id"])
    return ctx


def add_tier(api, ctx: Json, sponsor: bool = False, **overrides: Any) -> Json:
    """Publish an extra tier on an existing outing and record it on the context."""
    maker = new_sponsor_tier if sponsor else new_tier
    tier = maker(api, ctx["outing_id"], **overrides)
    ctx.setdefault("tiers", []).append(tier)
    return tier


def pending_registration(
    api, ctx: Json, players: Sequence[float] = (), **overrides: Any
) -> Json:
    """A registration left in PENDING_PAYMENT, optionally already peopled."""
    payload: Dict[str, Any] = dict(overrides)
    payload.setdefault("player_count", len(players))
    registration = new_registration(api, ctx["outing_id"], ctx["tier_id"], **payload)
    rows = [
        new_player(
            api,
            registration["id"],
            full_name=f"Golfer {index + 1}",
            handicap_index=index_value,
        )
        for index, index_value in enumerate(players)
    ]
    return {
        "registration": registration,
        "registration_id": registration["id"],
        "players": rows,
        "player_ids": [p["id"] for p in rows],
    }


def confirmed_registration(
    api,
    ctx: Json,
    players: Sequence[float] = (),
    amount_cents: Optional[int] = None,
    tier_id: Optional[str] = None,
    names: Optional[Sequence[str]] = None,
    amateur_statuses: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Json:
    """A registration paid at its tier price, with its golfers already added.

    Confirmation snapshots ``handicap_index_at_confirm`` on every player and
    derives their ``course_handicap``, so the players are added before payment.
    """
    target_tier_id = tier_id or ctx["tier_id"]
    price = amount_cents
    if price is None:
        price = read_tier(api, target_tier_id)["price_cents"]
    payload: Dict[str, Any] = dict(overrides)
    payload.setdefault("player_count", len(players))
    registration = new_registration(api, ctx["outing_id"], target_tier_id, **payload)
    rows = []
    for index, index_value in enumerate(players):
        player_overrides: Dict[str, Any] = {
            "full_name": (names[index] if names else f"Golfer {index + 1}"),
            "handicap_index": index_value,
        }
        if amateur_statuses:
            player_overrides["amateur_status"] = amateur_statuses[index]
        rows.append(new_player(api, registration["id"], **player_overrides))
    registration = pay_registration(api, registration["id"], price)
    rows = [read_player(api, row["id"]) for row in rows]
    return {
        "registration": registration,
        "registration_id": registration["id"],
        "players": rows,
        "player_ids": [p["id"] for p in rows],
    }


def team_from(api, ctx: Json, reg: Json, team_name: str = "ALPHA") -> Json:
    """Group every golfer of one registration into a single team."""
    team = new_team(api, ctx["outing_id"], reg["player_ids"], team_name=team_name)
    return team


def foursome_outing(
    api,
    handicap_indexes: Sequence[float] = (12.0, 18.4, 8.2, 24.0),
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    clock: Optional[str] = CLOCK_START_UTC,
    team_name: str = "ALPHA",
    amateur_statuses: Optional[Sequence[str]] = None,
) -> Json:
    """An OPEN outing carrying one confirmed foursome grouped into one team."""
    ctx = open_outing(api, clock=clock, outing=outing, contract=contract, tier=tier)
    reg = confirmed_registration(
        api, ctx, players=handicap_indexes, amateur_statuses=amateur_statuses
    )
    team = team_from(api, ctx, reg, team_name=team_name)
    ctx.update(
        {
            "registration": reg["registration"],
            "registration_id": reg["registration_id"],
            "players": reg["players"],
            "player_ids": reg["player_ids"],
            "team": team,
            "team_id": team["id"],
            "teams": [team],
        }
    )
    return ctx


def sponsor_outing(
    api,
    clock: Optional[str] = CLOCK_START_UTC,
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    asset: Optional[Json] = None,
    buyer_name: str = "Anchor Insurance",
    pay: bool = True,
) -> Json:
    """An OPEN outing with a sponsor tier, a sponsor registration and one unit."""
    ctx = open_outing(api, clock=clock, outing=outing, contract=contract, tier=tier,
                      sponsor_tier=True)
    if pay:
        reg = confirmed_registration(api, ctx, players=(), buyer_name=buyer_name, player_count=0)
    else:
        reg = pending_registration(api, ctx, players=(), buyer_name=buyer_name, player_count=0)
    unit = new_asset(api, ctx["outing_id"], **(asset or {}))
    ctx.update(
        {
            "registration": reg["registration"],
            "registration_id": reg["registration_id"],
            "asset": unit,
            "asset_id": unit["id"],
        }
    )
    return ctx


def allocation_walked_to(
    api,
    allocation_id: str,
    target_status: str,
    approve_headers: Optional[Dict[str, str]] = None,
    verify_headers: Optional[Dict[str, str]] = None,
    waived_reason: str = "The printer never delivered the sign",
) -> Json:
    """Walk one allocation forward from RESERVED to the requested status."""
    path = {
        "RESERVED": [],
        "COMMITTED": ["COMMIT"],
        "ARTWORK_APPROVED": ["COMMIT", "APPROVE_ARTWORK"],
        "INSTALLED": ["COMMIT", "APPROVE_ARTWORK", "INSTALL"],
        "VERIFIED": ["COMMIT", "APPROVE_ARTWORK", "INSTALL", "VERIFY"],
        "WAIVED": ["COMMIT", "WAIVE"],
        "RELEASED": ["RELEASE"],
    }[target_status]
    # Verification is the segregation-of-duties point, so the two stamps must
    # come from different users unless a test deliberately overrides them.
    approve_headers = approve_headers or SPONSORSHIP_HEADERS
    verify_headers = verify_headers or SPONSORSHIP_ALT_HEADERS
    row = read_allocation(api, allocation_id)
    for action in path:
        if action == "APPROVE_ARTWORK":
            row = drive_fulfillment(api, allocation_id, action, headers=approve_headers)
        elif action == "VERIFY":
            row = drive_fulfillment(api, allocation_id, action, headers=verify_headers)
        elif action == "WAIVE":
            row = drive_fulfillment(api, allocation_id, action, waived_reason=waived_reason)
        else:
            row = drive_fulfillment(api, allocation_id, action)
    return row


# ======================================= tier 3: full-lifecycle shortcuts ====


def assign_tee(
    api,
    team_id: str,
    wave: str = "A",
    starting_hole: int = 1,
    tee_time: str = f.DEFAULT_WAVE_A_START,
    cart_number: int = 1,
    headers: Optional[Dict[str, str]] = None,
    expected_team_version: Optional[int] = None,
    **overrides: Any,
) -> Json:
    """Write a tee assignment, re-reading the team's version unless one is given."""
    version = expected_team_version
    if version is None:
        version = team_version(api, team_id)
    return get_success_data(
        api.tee_assignment(
            team_id,
            f.tee_assignment_payload(
                version,
                wave=wave,
                starting_hole=starting_hole,
                tee_time=tee_time,
                cart_number=cart_number,
                **overrides,
            ),
            headers or COURSE_HEADERS,
        )
    )


def post_score(api, team_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Json:
    return get_success_data(
        api.post_score(team_id, f.score_payload(**overrides), headers or DIRECTOR_HEADERS)
    )


def locked_field_outing(
    api,
    handicap_indexes: Sequence[float] = (12.0, 18.4, 8.2, 24.0),
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    clock: Optional[str] = CLOCK_START_UTC,
    amateur_statuses: Optional[Sequence[str]] = None,
) -> Json:
    """One confirmed foursome, one team, field locked so the sandbag cap applies."""
    ctx = foursome_outing(
        api,
        handicap_indexes=handicap_indexes,
        outing=outing,
        contract=contract,
        tier=tier,
        clock=clock,
        amateur_statuses=amateur_statuses,
    )
    ctx["outing"] = lock_field(api, ctx["outing_id"])
    ctx["team"] = read_team(api, ctx["team_id"])
    ctx["players"] = [read_player(api, pid) for pid in ctx["player_ids"]]
    return ctx


def in_play_outing(
    api,
    handicap_indexes: Sequence[float] = (12.0, 18.4, 8.2, 24.0),
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    clock: Optional[str] = CLOCK_START_UTC,
    tee_time: str = f.DEFAULT_WAVE_A_START,
    amateur_statuses: Optional[Sequence[str]] = None,
) -> Json:
    """A locked field placed on the tee sheet and driven to IN_PLAY."""
    ctx = locked_field_outing(
        api,
        handicap_indexes=handicap_indexes,
        outing=outing,
        contract=contract,
        tier=tier,
        clock=clock,
        amateur_statuses=amateur_statuses,
    )
    ctx["team"] = assign_tee(api, ctx["team_id"], tee_time=tee_time)
    ctx["outing"] = start_play(api, ctx["outing_id"])
    return ctx


def scored_outing(
    api,
    handicap_indexes: Sequence[float] = (12.0, 18.4, 8.2, 24.0),
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    clock: Optional[str] = CLOCK_START_UTC,
    score: Optional[Json] = None,
    amateur_statuses: Optional[Sequence[str]] = None,
) -> Json:
    """A single-team outing carried all the way to SCORED on the play dimension."""
    ctx = in_play_outing(
        api,
        handicap_indexes=handicap_indexes,
        outing=outing,
        contract=contract,
        tier=tier,
        clock=clock,
        amateur_statuses=amateur_statuses,
    )
    ctx["team"] = post_score(api, ctx["team_id"], **(score or {}))
    ctx["outing"] = finalize_scoring(api, ctx["outing_id"])
    ctx["team"] = read_team(api, ctx["team_id"])
    return ctx


def reconcile(api, outing_id: str, expected_outing_version: Optional[int] = None) -> Json:
    version = expected_outing_version
    if version is None:
        version = outing_version(api, outing_id, TREASURER_HEADERS)
    return get_success_data(
        api.finance_transition(
            outing_id, f.finance_transition_payload("RECONCILE", version), TREASURER_HEADERS
        )
    )


def reopen_finance(api, outing_id: str, expected_outing_version: Optional[int] = None) -> Json:
    version = expected_outing_version
    if version is None:
        version = outing_version(api, outing_id, TREASURER_HEADERS)
    return get_success_data(
        api.finance_transition(
            outing_id, f.finance_transition_payload("REOPEN", version), TREASURER_HEADERS
        )
    )


def remit(
    api,
    outing_id: str,
    remittance_cents: int,
    reference: str = "WIRE-2026-0001",
    expected_outing_version: Optional[int] = None,
) -> Json:
    version = expected_outing_version
    if version is None:
        version = outing_version(api, outing_id, TREASURER_HEADERS)
    return get_success_data(
        api.finance_transition(
            outing_id,
            f.remit_payload(version, remittance_cents, reference),
            TREASURER_HEADERS,
        )
    )


def reconciled_outing(api, **kwargs: Any) -> Json:
    """A SCORED outing whose finance dimension has been moved to RECONCILED."""
    ctx = scored_outing(api, **kwargs)
    ctx["outing"] = reconcile(api, ctx["outing_id"])
    return ctx


# ================================= tier 4: accumulation and threshold setups ==


def field_at_capacity(
    api,
    field_capacity_teams: int = 1,
    first_players: Sequence[float] = (12.0, 12.0, 12.0, 12.0),
    second_players: Sequence[float] = (12.0, 12.0, 12.0, 12.0),
    clock: Optional[str] = CLOCK_START_UTC,
    tier: Optional[Json] = None,
) -> Json:
    """Fill the field exactly, then leave a second paid package on the waitlist.

    The capacity in player slots is ``field_capacity_teams`` multiplied by four,
    so a payment landing exactly on that figure confirms and the next one
    waitlists.
    """
    ctx = open_outing(
        api,
        clock=clock,
        outing={"field_capacity_teams": field_capacity_teams},
        tier=tier,
    )
    price = read_tier(api, ctx["tier_id"])["price_cents"]
    first = confirmed_registration(
        api, ctx, players=first_players, buyer_name="First Four", amount_cents=price
    )
    second = confirmed_registration(
        api, ctx, players=second_players, buyer_name="Second Four", amount_cents=price
    )
    ctx.update(
        {
            "first": first,
            "second": second,
            "tier_price_cents": price,
        }
    )
    return ctx


def upsell_allocation(
    api,
    ctx: Json,
    asset: Optional[Json] = None,
    source: str = "UPSELL",
    **allocation_overrides: Any,
) -> Json:
    """One unit plus one allocation on it, for revenue-recognition scenarios."""
    unit = new_asset(api, ctx["outing_id"], **(asset or {}))
    allocation = new_allocation(
        api, ctx["registration_id"], unit["id"], source, **allocation_overrides
    )
    return {
        "asset": unit,
        "asset_id": unit["id"],
        "allocation": allocation,
        "allocation_id": allocation["id"],
    }


def paid_fundraising_item(
    api,
    ctx: Json,
    buyer_registration_id: str,
    bid_cents: int,
    item: Optional[Json] = None,
    sale_headers: Optional[Dict[str, str]] = None,
) -> Json:
    """A fundraising item carried LISTED -> SOLD -> PAID so its cash is in the ledger."""
    row = new_item(api, ctx["outing_id"], **(item or {}))
    sell_item(api, row["id"], buyer_registration_id, bid_cents, headers=sale_headers)
    row = pay_item(api, row["id"], bid_cents)
    return {"item": row, "item_id": row["id"]}


# ==================================== tier 5: finalization and terminal state ==


def remit_ready_outing(
    api,
    handicap_indexes: Sequence[float] = (12.0, 18.4, 8.2, 24.0),
    outing: Optional[Json] = None,
    contract: Optional[Json] = None,
    tier: Optional[Json] = None,
    clock: Optional[str] = CLOCK_START_UTC,
    score: Optional[Json] = None,
) -> Json:
    """A RECONCILED outing whose only revenue-recognized registration is receipted.

    That satisfies the unreceipted-items gate, so the remaining remittance
    conditions can be exercised one at a time.  The foursome is checked in
    while the field still permits it, because the final treatment bills the
    turnout: "the billable player count becomes ``checked_in_player_count``,
    the turnout that actually walked the course".  Check-in "requires the
    outing's play dimension to be ``FIELD_LOCKED`` or ``IN_PLAY``", so it has
    to happen before scoring is finalized.
    """
    ctx = in_play_outing(
        api,
        handicap_indexes=handicap_indexes,
        outing=outing,
        contract=contract,
        tier=tier,
        clock=clock,
    )
    ctx["registration"] = check_in_registration(api, ctx["registration_id"])
    ctx["team"] = post_score(api, ctx["team_id"], **(score or {}))
    ctx["outing"] = finalize_scoring(api, ctx["outing_id"])
    ctx["team"] = read_team(api, ctx["team_id"])
    ctx["receipt"] = issue_registration_receipt(api, ctx["outing_id"], ctx["registration_id"])
    ctx["outing"] = reconcile(api, ctx["outing_id"])
    return ctx


# ================================================================ listings ====


def list_data(response) -> List[Json]:
    """The rows of a list response, read leniently for setup use."""
    body = response.json()
    return body["data"]
