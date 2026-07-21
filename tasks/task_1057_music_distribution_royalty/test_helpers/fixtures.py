"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints only;
the database is empty at the start of each test. Setup calls use the lenient
get_success_data() validator so a broken precondition surfaces as a clear setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_BASE, DEFAULT_RELEASE_DATE, DEFAULT_EFFECTIVE_FROM, DEFAULT_SCHEDULED_SEND_AT,
    ADMIN_USER, OPS_USER, FIN_RECONCILER, FIN_CLOSER, FIN_APPROVER,
    PERIOD_MAY, REPORTED_MAY, isrc, upc,
)
from .factories import (
    create_subscription_plan_payload, create_store_payload, create_artist_payload,
    create_subscription_payload, create_release_payload, create_track_payload,
    create_collaborator_payload, create_split_sheet_payload, create_split_share_payload,
    create_delivery_payload, create_royalty_statement_payload, royalty_line_payload,
)
from .test_users import (
    make_artist_headers, make_collaborator_headers, make_finance_headers,
    make_ops_headers, make_admin_headers, make_fan_headers,
)


# =====================================================================
# Tier 0: single-step primitives
# =====================================================================

def set_clock(to_iso8601: str, user_id: str = ADMIN_USER) -> dict:
    """Reposition the server-wide logical clock. Mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, make_admin_headers(user_id)))


def create_plan(**overrides) -> dict:
    payload = create_subscription_plan_payload(**overrides)
    return get_success_data(api_client.create_subscription_plan(payload, make_admin_headers()))


def create_store(**overrides) -> dict:
    payload = create_store_payload(**overrides)
    return get_success_data(api_client.create_store(payload, make_admin_headers()))


def create_artist(**overrides) -> dict:
    payload = create_artist_payload(**overrides)
    return get_success_data(api_client.create_artist(payload, make_admin_headers()))


def create_pending_subscription(artist_id: str, plan_id: str, **overrides) -> dict:
    payload = create_subscription_payload(artist_id, plan_id, **overrides)
    return get_success_data(api_client.create_subscription(payload, make_admin_headers()))


def activate_subscription(subscription_id: str, payment_reference: str = "pay-1") -> dict:
    return get_success_data(
        api_client.activate_subscription(subscription_id, payment_reference, make_admin_headers())
    )


def lapse_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.lapse_subscription(subscription_id, make_admin_headers()))


def expire_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.expire_subscription(subscription_id, make_admin_headers()))


def create_active_subscription(artist_id: str, plan_id: str, **overrides) -> dict:
    """Create a PENDING subscription and drive it to ACTIVE."""
    sub = create_pending_subscription(artist_id, plan_id, **overrides)
    return activate_subscription(sub["id"], f"pay-{sub['id'][:8]}")


def create_release(artist_id: str, **overrides) -> dict:
    payload = create_release_payload(artist_id, **overrides)
    return get_success_data(api_client.create_release(payload, make_artist_headers(artist_id)))


def add_track(release_id: str, artist_id: str, **overrides) -> dict:
    payload = create_track_payload(**overrides)
    return get_success_data(
        api_client.add_track(release_id, payload, make_artist_headers(artist_id))
    )


def create_collaborator(artist_id: str, **overrides) -> dict:
    payload = create_collaborator_payload(artist_id, **overrides)
    return get_success_data(
        api_client.create_collaborator(payload, make_artist_headers(artist_id))
    )


def read_track(track_id: str, artist_id: str) -> dict:
    return get_success_data(api_client.get_track(track_id, make_artist_headers(artist_id)))


def read_release(release_id: str, artist_id: str) -> dict:
    return get_success_data(api_client.get_release(release_id, make_artist_headers(artist_id)))


def read_artist(artist_id: str) -> dict:
    return get_success_data(api_client.get_artist(artist_id, make_admin_headers()))


def read_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, make_admin_headers()))


def read_collaborator(collaborator_id: str) -> dict:
    return get_success_data(
        api_client.get_collaborator(collaborator_id, make_finance_headers(FIN_RECONCILER))
    )


def read_split_sheet(sheet_id: str, artist_id: str) -> dict:
    return get_success_data(api_client.get_split_sheet(sheet_id, make_artist_headers(artist_id)))


def read_split_share(share_id: str, artist_id: str) -> dict:
    return get_success_data(api_client.get_split_share(share_id, make_artist_headers(artist_id)))


def read_delivery(delivery_id: str) -> dict:
    return get_success_data(api_client.get_delivery(delivery_id, make_ops_headers()))


def read_statement(statement_id: str, user_id: str = FIN_RECONCILER) -> dict:
    return get_success_data(
        api_client.get_royalty_statement(statement_id, make_finance_headers(user_id))
    )


def read_payout(payout_id: str, user_id: str = FIN_APPROVER) -> dict:
    return get_success_data(api_client.get_payout(payout_id, make_finance_headers(user_id)))


def read_tax_form(form_id: str, user_id: str = FIN_APPROVER) -> dict:
    return get_success_data(api_client.get_tax_form(form_id, make_finance_headers(user_id)))


def list_payouts_for(collaborator_id: str = None, statement_id: str = None,
                     user_id: str = FIN_APPROVER) -> list:
    params = {}
    if collaborator_id:
        params["collaborator_id"] = collaborator_id
    if statement_id:
        params["royalty_statement_id"] = statement_id
    resp = api_client.list_payouts(make_finance_headers(user_id), params=params)
    return get_success_data(resp)


# =====================================================================
# Tier 1: split-sheet lifecycle (DRAFT -> PENDING_ACCEPTANCE -> LOCKED)
# =====================================================================

def create_split_sheet(track_id: str, artist_id: str, expected_track_version: int,
                       **overrides) -> dict:
    payload = create_split_sheet_payload(track_id, expected_track_version, **overrides)
    return get_success_data(
        api_client.create_split_sheet(payload, make_artist_headers(artist_id))
    )


def add_share(sheet_id: str, artist_id: str, collaborator_id: str, share_bps: int) -> dict:
    payload = create_split_share_payload(collaborator_id, share_bps)
    return get_success_data(
        api_client.add_split_share(sheet_id, payload, make_artist_headers(artist_id))
    )


def send_sheet(sheet_id: str, artist_id: str) -> dict:
    return get_success_data(
        api_client.send_split_sheet(sheet_id, make_artist_headers(artist_id))
    )


def accept_share(share_id: str, collaborator_id: str) -> dict:
    return get_success_data(
        api_client.accept_split_share(share_id, make_collaborator_headers(collaborator_id))
    )


def lock_sheet(sheet_id: str, artist_id: str) -> dict:
    return get_success_data(api_client.lock_split_sheet(sheet_id, make_artist_headers(artist_id)))


def build_locked_sheet(track_id: str, artist_id: str, allocations, expected_track_version=None,
                       effective_from: str = DEFAULT_EFFECTIVE_FROM):
    """Walk a track's split sheet all the way to LOCKED.

    allocations: list of (collaborator_id, share_bps) in the order the shares must be created,
    because level-two remainder distribution breaks ties by the share's created_at.
    Returns (sheet, [shares]) with the sheet re-read after the lock.
    """
    if expected_track_version is None:
        expected_track_version = read_track(track_id, artist_id)["version"]
    sheet = create_split_sheet(
        track_id, artist_id, expected_track_version, effective_from=effective_from
    )
    shares = [add_share(sheet["id"], artist_id, cid, bps) for cid, bps in allocations]
    send_sheet(sheet["id"], artist_id)
    for share, (cid, _bps) in zip(shares, allocations):
        accept_share(share["id"], cid)
    locked = lock_sheet(sheet["id"], artist_id)
    return locked, shares


# =====================================================================
# Tier 2: editorial pipeline
# =====================================================================

def submit_release(release_id: str, artist_id: str) -> dict:
    return get_success_data(
        api_client.submit_release(release_id, make_artist_headers(artist_id))
    )


def drive_release_to_approved(release_id: str, artist_id: str, ops_user: str = OPS_USER) -> dict:
    """DRAFT -> SUBMITTED -> IN_REVIEW -> APPROVED."""
    submit_release(release_id, artist_id)
    get_success_data(api_client.review_release(release_id, make_ops_headers(ops_user)))
    return get_success_data(api_client.approve_release(release_id, make_ops_headers(ops_user)))


# =====================================================================
# Tier 2: delivery pipeline
# =====================================================================

def queue_delivery(release_id: str, store_id: str,
                   scheduled_send_at: str = DEFAULT_SCHEDULED_SEND_AT,
                   ops_user: str = OPS_USER) -> dict:
    payload = create_delivery_payload(store_id, scheduled_send_at=scheduled_send_at)
    return get_success_data(
        api_client.queue_delivery(release_id, payload, make_ops_headers(ops_user))
    )


def send_delivery(delivery_id: str, ops_user: str = OPS_USER) -> dict:
    return get_success_data(api_client.send_delivery(delivery_id, make_ops_headers(ops_user)))


def ack_delivery(delivery_id: str, outcome: str, error_code=None, ops_user: str = OPS_USER) -> dict:
    return get_success_data(
        api_client.ack_delivery(delivery_id, outcome, make_ops_headers(ops_user), error_code)
    )


def retry_delivery(delivery_id: str, ops_user: str = OPS_USER) -> dict:
    return get_success_data(api_client.retry_delivery(delivery_id, make_ops_headers(ops_user)))


def confirm_takedown(delivery_id: str, ops_user: str = OPS_USER) -> dict:
    return get_success_data(api_client.confirm_takedown(delivery_id, make_ops_headers(ops_user)))


def deliver_release_to_store(release_id: str, store_id: str,
                             scheduled_send_at: str = DEFAULT_SCHEDULED_SEND_AT,
                             ops_user: str = OPS_USER) -> dict:
    """Queue, dispatch and accept one delivery. Returns the ACCEPTED delivery."""
    delivery = queue_delivery(release_id, store_id, scheduled_send_at, ops_user)
    send_delivery(delivery["id"], ops_user)
    return ack_delivery(delivery["id"], "ACCEPTED", ops_user=ops_user)


# =====================================================================
# Tier 3: royalty ledger
# =====================================================================

def open_statement(artist_id: str, period=PERIOD_MAY, user_id: str = FIN_RECONCILER) -> dict:
    payload = create_royalty_statement_payload(artist_id, period[0], period[1])
    return get_success_data(
        api_client.create_royalty_statement(payload, make_finance_headers(user_id))
    )


def ingest_batch(statement_id: str, expected_statement_version: int, lines: list,
                 user_id: str = FIN_RECONCILER) -> dict:
    return get_success_data(
        api_client.ingest_royalty_lines(
            statement_id, expected_statement_version, lines, make_finance_headers(user_id)
        )
    )


def reconcile_statement(statement_id: str, user_id: str = FIN_RECONCILER) -> dict:
    return get_success_data(
        api_client.reconcile_statement(statement_id, make_finance_headers(user_id))
    )


def close_statement(statement_id: str, user_id: str = FIN_CLOSER) -> dict:
    """Close must be performed by an operator other than the one who reconciled."""
    return get_success_data(
        api_client.close_statement(statement_id, make_finance_headers(user_id))
    )


# =====================================================================
# Tier 4: whole-world composites
# =====================================================================

def setup_world(plan_overrides=None, store_overrides=None, extra_stores=None,
                artist_overrides=None, release_overrides=None, tracks=None,
                payees=None, clock: str = CLOCK_BASE, with_store: bool = True) -> dict:
    """Catalogue + artist + ACTIVE subscription + one DRAFT release with tracks and payees.

    tracks: list of per-track override dicts (defaults to a single compliant track carrying
            an isrc, explicit=false and track_number 1).
    payees: list of per-collaborator override dicts (defaults to one US VERIFIED payee).
    Returns a dict keyed plan / store / stores / artist / subscription / release / tracks / payees.
    """
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))

    stores = []
    if with_store:
        stores.append(create_store(**(store_overrides or {})))
    for extra in (extra_stores or []):
        stores.append(create_store(**extra))

    artist = create_artist(**(artist_overrides or {}))
    subscription = create_active_subscription(artist["id"], plan["id"])

    release_kwargs = dict(release_overrides or {})
    release_kwargs.setdefault("upc", upc(100000000001))
    release = create_release(artist["id"], **release_kwargs)

    track_specs = tracks if tracks is not None else [{}]
    built_tracks = []
    for n, spec in enumerate(track_specs, start=1):
        kwargs = dict(spec)
        kwargs.setdefault("track_number", n)
        kwargs.setdefault("title", f"Track {n}")
        if "isrc" not in kwargs:
            kwargs["isrc"] = isrc(n)
        built_tracks.append(add_track(release["id"], artist["id"], **kwargs))

    payee_specs = payees if payees is not None else [{}]
    built_payees = []
    for n, spec in enumerate(payee_specs, start=1):
        kwargs = dict(spec)
        kwargs.setdefault("name", f"Payee {n}")
        kwargs.setdefault("email", f"payee{n}@example.com")
        built_payees.append(create_collaborator(artist["id"], **kwargs))

    return {
        "plan": plan,
        "store": stores[0] if stores else None,
        "stores": stores,
        "artist": artist,
        "artist_id": artist["id"],
        "subscription": subscription,
        "release": release,
        "release_id": release["id"],
        "tracks": built_tracks,
        "track": built_tracks[0] if built_tracks else None,
        "payees": built_payees,
        "payee": built_payees[0] if built_payees else None,
    }


def lock_sheets_for_world(world: dict, allocations_per_track=None) -> dict:
    """Give every track of the world a LOCKED split sheet.

    allocations_per_track: list (parallel to world["tracks"]) of [(collaborator_id, bps), ...].
    Defaults to giving the world's first payee the whole 10000 bps on every track.
    """
    artist_id = world["artist_id"]
    if allocations_per_track is None:
        allocations_per_track = [
            [(world["payee"]["id"], 10000)] for _ in world["tracks"]
        ]
    sheets, all_shares = [], []
    for track, allocations in zip(world["tracks"], allocations_per_track):
        sheet, shares = build_locked_sheet(track["id"], artist_id, allocations)
        sheets.append(sheet)
        all_shares.append(shares)
    world["sheets"] = sheets
    world["sheet"] = sheets[0] if sheets else None
    world["shares_per_track"] = all_shares
    world["shares"] = all_shares[0] if all_shares else []
    return world


def setup_release_ready_for_delivery(allocations_per_track=None, **world_kwargs) -> dict:
    """A world whose release is APPROVED and whose every track holds a LOCKED sheet,
    so a delivery may legally be queued."""
    world = setup_world(**world_kwargs)
    lock_sheets_for_world(world, allocations_per_track)
    world["release"] = drive_release_to_approved(world["release_id"], world["artist_id"])
    return world


def setup_delivered_release(scheduled_send_at: str = DEFAULT_SCHEDULED_SEND_AT,
                            clock_at_ack: str = None, allocations_per_track=None,
                            **world_kwargs) -> dict:
    """An APPROVED release fully DELIVERED to its single store.

    clock_at_ack: when supplied, the clock is repositioned there before the acknowledgement,
    which is what lets the arrival at DELIVERED drive the editorial dimension to LIVE.
    """
    world = setup_release_ready_for_delivery(allocations_per_track, **world_kwargs)
    delivery = queue_delivery(world["release_id"], world["store"]["id"], scheduled_send_at)
    send_delivery(delivery["id"])
    if clock_at_ack:
        set_clock(clock_at_ack)
    ack_delivery(delivery["id"], "ACCEPTED")
    world["delivery"] = read_delivery(delivery["id"])
    world["release"] = read_release(world["release_id"], world["artist_id"])
    return world


# =====================================================================
# Tier 5: ledger composites
# =====================================================================

def setup_reconciled_statement(world: dict, lines: list, period=PERIOD_MAY,
                               reconciler: str = FIN_RECONCILER) -> dict:
    """Open a statement for the world's artist, ingest one batch, and reconcile it."""
    statement = open_statement(world["artist_id"], period, reconciler)
    if lines:
        statement = ingest_batch(statement["id"], statement["version"], lines, reconciler)
    statement = reconcile_statement(statement["id"], reconciler)
    world.setdefault("statements", []).append(statement)
    world["statement"] = statement
    world["statement_id"] = statement["id"]
    return world


def setup_closed_statement(world: dict, lines: list, period=PERIOD_MAY,
                           reconciler: str = FIN_RECONCILER,
                           closer: str = FIN_CLOSER) -> dict:
    """Drive a statement all the way to CLOSED so its payouts are materialised."""
    setup_reconciled_statement(world, lines, period, reconciler)
    statement = close_statement(world["statement_id"], closer)
    world["statements"][-1] = statement
    world["statement"] = statement
    return world


def setup_single_payee_payout(gross_cents: int, payee_overrides=None,
                              plan_overrides=None, period=PERIOD_MAY,
                              reported_at: str = REPORTED_MAY,
                              source: str = "STREAMING", clock: str = CLOCK_BASE) -> dict:
    """One artist, one track, one payee holding the whole 10000 bps, one closed statement.

    The plan defaults to a zero commission_bps so the statement's commission collapses to
    the 50-cent minimum floor and the payee's payout gross is exactly gross_cents - 50.
    Returns the world with "payout" bound to the single materialised payout.
    """
    plan_kwargs = {"code": "FLAT", "name": "Flat", "commission_bps": 0,
                   "allows_content_id": False, "included_release_slots": 3}
    plan_kwargs.update(plan_overrides or {})

    world = setup_world(
        plan_overrides=plan_kwargs,
        payees=[payee_overrides or {}],
        clock=clock,
    )
    lock_sheets_for_world(world)
    lines = [royalty_line_payload(
        world["track"]["id"], world["store"]["id"], gross_cents, reported_at, source=source
    )]
    setup_closed_statement(world, lines, period=period)
    payouts = list_payouts_for(statement_id=world["statement_id"])
    world["payouts"] = payouts
    world["payout"] = payouts[0] if payouts else None
    return world


def pay_payout(payout_id: str, user_id: str = FIN_APPROVER) -> dict:
    return get_success_data(api_client.pay_payout(payout_id, make_finance_headers(user_id)))


def approve_payout(payout_id: str, user_id: str = FIN_APPROVER) -> dict:
    return get_success_data(api_client.approve_payout(payout_id, make_finance_headers(user_id)))


def reverse_payout(payout_id: str, reason_code: str = "BANK_RETURNED",
                   user_id: str = "fin-4") -> dict:
    return get_success_data(
        api_client.reverse_payout(payout_id, reason_code, make_finance_headers(user_id))
    )


def draft_tax_form(collaborator_id: str, tax_year: int = 2026,
                   user_id: str = FIN_APPROVER) -> dict:
    return get_success_data(
        api_client.create_tax_form(
            {"collaborator_id": collaborator_id, "tax_year": tax_year},
            make_finance_headers(user_id),
        )
    )
