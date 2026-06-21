"""Composite setup helpers.

These encapsulate the multi-step preambles that nearly every interesting claim
needs (register a work, lock it, lock a recording, grant a rights window, open a
statement, ingest/allocate usage, finalize). They build every precondition from
scratch against an empty DB using only PRD-declared endpoints, so each test runs
against a fresh server. Setup calls use get_success_data() so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

A note on the canonical performance figure used across many fixtures:
an ASCAP work (180s, duration_weight 1.0) with one PERFORMANCE usage of
quantity 1000 and gross_revenue_cents 200000 produces
    royalty = round_half_up(200000*0.50 + 1000*12*1.0) = 112000.
With a single 100% holder, the statement gross_earnings_cents == 112000.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_administrator_headers,
    make_operator_headers,
    make_licensee_headers,
)
from .factories import (
    create_rightsholder_payload,
    create_work_payload,
    create_composition_share_payload,
    create_recording_payload,
    create_recording_share_payload,
    create_rights_window_payload,
    create_usage_event_payload,
    create_sync_license_payload,
    create_advance_payload,
    create_statement_payload,
    next_iswc,
    next_isrc,
)

ADMIN = make_administrator_headers()
OPERATOR = make_operator_headers()


# --- Primitive helpers -------------------------------------------------------

def set_clock(instant: str):
    """Pin the server clock to a deterministic UTC instant."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def create_rightsholder(**overrides) -> dict:
    return get_success_data(
        api_client.create_rightsholder(create_rightsholder_payload(**overrides), ADMIN)
    )


def create_advance(rightsholder_id, **overrides) -> dict:
    payload = create_advance_payload(rightsholder_id=rightsholder_id, **overrides)
    return get_success_data(api_client.create_advance(payload, ADMIN))


def open_statement(rightsholder_id, period_start, period_end) -> dict:
    payload = create_statement_payload(
        rightsholder_id=rightsholder_id,
        period_start=period_start,
        period_end=period_end,
    )
    return get_success_data(api_client.create_statement(payload, OPERATOR))


def finalize_statement(statement_id) -> dict:
    """Read current version, then finalize with it."""
    stmt = get_success_data(api_client.get_statement(statement_id, OPERATOR))
    return get_success_data(
        api_client.finalize_statement(statement_id, {"expected_statement_version": stmt["version"]}, OPERATOR)
    )


# --- Catalog construction ----------------------------------------------------

def create_registered_work(holder_id, pro_affiliation="ASCAP", duration_seconds=180,
                           role="WRITER", iswc=None) -> dict:
    """Create a work, give holder a 100% composition share, register (lock) it.
    Returns the registered Work."""
    work = get_success_data(api_client.create_work(
        create_work_payload(pro_affiliation=pro_affiliation, duration_seconds=duration_seconds,
                            iswc=iswc or next_iswc()), ADMIN))
    get_success_data(api_client.create_composition_share(
        create_composition_share_payload(work_id=work["id"], rightsholder_id=holder_id,
                                         role=role, split_bps=10000), ADMIN))
    return get_success_data(api_client.register_work(work["id"], ADMIN))


def create_locked_recording(work_id, holder_id, release_type="STREAMING",
                            duration_seconds=180, isrc=None) -> dict:
    """Create a recording on work_id, give holder a 100% master share, lock it.
    Returns the locked Recording."""
    rec = get_success_data(api_client.create_recording(
        create_recording_payload(work_id=work_id, release_type=release_type,
                                duration_seconds=duration_seconds, isrc=isrc or next_isrc()), ADMIN))
    get_success_data(api_client.create_recording_share(
        create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder_id,
                                       split_bps=10000), ADMIN))
    return get_success_data(api_client.lock_recording_shares(rec["id"], ADMIN))


def grant_window(recording_id, rights_type, term_start, term_end, territory="US") -> dict:
    return get_success_data(api_client.create_rights_window(
        create_rights_window_payload(recording_id=recording_id, rights_type=rights_type,
                                     territory=territory, term_start=term_start,
                                     term_end=term_end), ADMIN))


# --- Tier 2/3: single-holder pipelines --------------------------------------

def setup_single_holder_catalog(pro_affiliation="ASCAP", work_duration=180,
                                rec_release="STREAMING", rec_duration=180,
                                rights_type="PERFORMANCE",
                                term_start="2026-01-01T00:00:00.000Z",
                                term_end="2026-02-01T00:00:00.000Z",
                                territory="US", minimum_payout_cents=1,
                                withholding_pct=0):
    """Active single rightsholder + registered work + locked recording (100% to that
    holder on both composition and master) + one rights window of rights_type.

    Returns (holder, work, recording, window).
    """
    holder = create_rightsholder(party_type="WRITER", minimum_payout_cents=minimum_payout_cents,
                                 withholding_pct=withholding_pct)
    work = create_registered_work(holder["id"], pro_affiliation=pro_affiliation,
                                   duration_seconds=work_duration)
    rec = create_locked_recording(work["id"], holder["id"], release_type=rec_release,
                                   duration_seconds=rec_duration)
    window = grant_window(rec["id"], rights_type, term_start, term_end, territory=territory)
    return holder, work, rec, window


def setup_allocated_performance(clock="2026-01-15T00:00:00.000Z",
                                period_start="2026-01-01T00:00:00.000Z",
                                period_end="2026-02-01T00:00:00.000Z",
                                occurred_at="2026-01-15T00:00:00.000Z",
                                quantity=1000, gross_revenue_cents=200000,
                                pro_affiliation="ASCAP", work_duration=180,
                                minimum_payout_cents=1, withholding_pct=0,
                                territory="US"):
    """Full happy path through allocate of one PERFORMANCE usage to a single 100%
    holder, with an OPEN DRAFT statement covering the period.

    Returns dict: holder, work, recording, window, statement, usage_event.
    The usage_event dict is the post-allocate response (royalty_cents populated).
    """
    set_clock(clock)
    holder, work, rec, window = setup_single_holder_catalog(
        pro_affiliation=pro_affiliation, work_duration=work_duration,
        rec_release="STREAMING", rec_duration=work_duration,
        rights_type="PERFORMANCE", term_start=period_start, term_end=period_end,
        territory=territory, minimum_payout_cents=minimum_payout_cents,
        withholding_pct=withholding_pct,
    )
    statement = open_statement(holder["id"], period_start, period_end)
    ue = get_success_data(api_client.create_usage_event(
        create_usage_event_payload(recording_id=rec["id"], usage_type="PERFORMANCE",
                                   territory=territory, occurred_at=occurred_at,
                                   quantity=quantity, gross_revenue_cents=gross_revenue_cents), OPERATOR))
    allocated = get_success_data(api_client.allocate_usage_event(ue["id"], OPERATOR))
    return {
        "holder": holder, "work": work, "recording": rec, "window": window,
        "statement": statement, "usage_event": allocated,
    }


def setup_ingested_performance(clock="2026-01-15T00:00:00.000Z",
                               period_start="2026-01-01T00:00:00.000Z",
                               period_end="2026-02-01T00:00:00.000Z",
                               occurred_at="2026-01-15T00:00:00.000Z",
                               quantity=1000, gross_revenue_cents=200000,
                               pro_affiliation="ASCAP",
                               minimum_payout_cents=1, withholding_pct=0):
    """Same as setup_allocated_performance but stops at INGESTED (no allocate).
    Returns dict with holder/work/recording/window/statement/usage_event (INGESTED)."""
    set_clock(clock)
    holder, work, rec, window = setup_single_holder_catalog(
        pro_affiliation=pro_affiliation, work_duration=180,
        rec_release="STREAMING", rec_duration=180,
        rights_type="PERFORMANCE", term_start=period_start, term_end=period_end,
        minimum_payout_cents=minimum_payout_cents, withholding_pct=withholding_pct,
    )
    statement = open_statement(holder["id"], period_start, period_end)
    ue = get_success_data(api_client.create_usage_event(
        create_usage_event_payload(recording_id=rec["id"], usage_type="PERFORMANCE",
                                   territory="US", occurred_at=occurred_at,
                                   quantity=quantity, gross_revenue_cents=gross_revenue_cents), OPERATOR))
    return {
        "holder": holder, "work": work, "recording": rec, "window": window,
        "statement": statement, "usage_event": ue,
    }


def setup_finalized_statement(clock="2026-01-15T00:00:00.000Z",
                              period_start="2026-01-01T00:00:00.000Z",
                              period_end="2026-02-01T00:00:00.000Z",
                              occurred_at="2026-01-15T00:00:00.000Z",
                              withholding_pct=0, minimum_payout_cents=1):
    """Allocate one canonical PERFORMANCE usage (royalty 112000) then finalize.
    Returns dict with holder, recording, statement (FINALIZED), usage_event."""
    ctx = setup_allocated_performance(clock=clock, period_start=period_start,
                                      period_end=period_end, occurred_at=occurred_at,
                                      withholding_pct=withholding_pct,
                                      minimum_payout_cents=minimum_payout_cents)
    ctx["statement"] = finalize_statement(ctx["statement"]["id"])
    return ctx


def setup_paid_statement(clock="2026-07-15T00:00:00.000Z",
                         period_start="2026-07-01T00:00:00.000Z",
                         period_end="2026-08-01T00:00:00.000Z",
                         occurred_at="2026-07-15T00:00:00.000Z"):
    """Finalize a canonical 112000 statement then create a PENDING payout (statement PAID).
    Returns dict with holder, statement (PAID), payout (PENDING)."""
    ctx = setup_finalized_statement(clock=clock, period_start=period_start,
                                    period_end=period_end, occurred_at=occurred_at)
    payout = get_success_data(api_client.create_payout({"statement_id": ctx["statement"]["id"]}, OPERATOR))
    ctx["payout"] = payout
    ctx["statement"] = get_success_data(api_client.get_statement(ctx["statement"]["id"], OPERATOR))
    return ctx


# --- Multi-holder mechanical pipeline (rounding-order claim) ------------------

def setup_two_holder_mechanical(clock="2026-04-10T00:00:00.000Z",
                                period_start="2026-04-01T00:00:00.000Z",
                                period_end="2026-05-01T00:00:00.000Z",
                                occurred_at="2026-04-10T00:00:00.000Z",
                                rec_duration=200, quantity=999,
                                split_a=3333, split_b=6667):
    """Physical recording with two master share holders (split_a / split_b bps), a
    MECHANICAL window, an open statement for each holder, and one INGESTED MECHANICAL
    usage. Does NOT allocate.

    Returns dict: holder_a, holder_b, recording, statement_a, statement_b, usage_event.
    """
    set_clock(clock)
    holder_a = create_rightsholder(legal_name="Label A", party_type="LABEL", minimum_payout_cents=1)
    holder_b = create_rightsholder(legal_name="Label B", party_type="LABEL", minimum_payout_cents=1)
    work = get_success_data(api_client.create_work(
        create_work_payload(pro_affiliation="NONE", duration_seconds=rec_duration), ADMIN))
    get_success_data(api_client.create_composition_share(
        create_composition_share_payload(work_id=work["id"], rightsholder_id=holder_a["id"],
                                         role="PUBLISHER", split_bps=10000), ADMIN))
    get_success_data(api_client.register_work(work["id"], ADMIN))
    rec = get_success_data(api_client.create_recording(
        create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                duration_seconds=rec_duration), ADMIN))
    get_success_data(api_client.create_recording_share(
        create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder_a["id"],
                                       split_bps=split_a), ADMIN))
    get_success_data(api_client.create_recording_share(
        create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder_b["id"],
                                       split_bps=split_b), ADMIN))
    get_success_data(api_client.lock_recording_shares(rec["id"], ADMIN))
    grant_window(rec["id"], "MECHANICAL", period_start, period_end)
    stmt_a = open_statement(holder_a["id"], period_start, period_end)
    stmt_b = open_statement(holder_b["id"], period_start, period_end)
    ue = get_success_data(api_client.create_usage_event(
        create_usage_event_payload(recording_id=rec["id"], usage_type="MECHANICAL",
                                   territory="US", occurred_at=occurred_at,
                                   quantity=quantity, gross_revenue_cents=0), OPERATOR))
    return {
        "holder_a": holder_a, "holder_b": holder_b, "recording": rec,
        "statement_a": stmt_a, "statement_b": stmt_b, "usage_event": ue,
    }


# --- Mechanical single-holder boundary pipeline -------------------------------

def setup_locked_physical_recording_with_mechanical_window(
        clock, period_start, period_end, rec_duration=200, holder=None):
    """A locked PHYSICAL recording (rec_duration) with a 100% LABEL holder, a
    MECHANICAL window over the period, and an open statement. Does not create usage.

    If `holder` is given it is reused (so multiple recordings can share one statement).
    Returns dict: holder, work, recording, statement.
    """
    if holder is None:
        set_clock(clock)
        holder = create_rightsholder(legal_name="Label M", party_type="LABEL", minimum_payout_cents=1)
        stmt = open_statement(holder["id"], period_start, period_end)
    else:
        stmt = None
    work = get_success_data(api_client.create_work(
        create_work_payload(pro_affiliation="NONE", duration_seconds=rec_duration), ADMIN))
    get_success_data(api_client.create_composition_share(
        create_composition_share_payload(work_id=work["id"], rightsholder_id=holder["id"],
                                         role="PUBLISHER", split_bps=10000), ADMIN))
    get_success_data(api_client.register_work(work["id"], ADMIN))
    rec = get_success_data(api_client.create_recording(
        create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                duration_seconds=rec_duration), ADMIN))
    get_success_data(api_client.create_recording_share(
        create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder["id"],
                                       split_bps=10000), ADMIN))
    get_success_data(api_client.lock_recording_shares(rec["id"], ADMIN))
    grant_window(rec["id"], "MECHANICAL", period_start, period_end)
    return {"holder": holder, "work": work, "recording": rec, "statement": stmt}


def ingest_mechanical_usage(recording_id, occurred_at, quantity=100):
    return get_success_data(api_client.create_usage_event(
        create_usage_event_payload(recording_id=recording_id, usage_type="MECHANICAL",
                                   territory="US", occurred_at=occurred_at,
                                   quantity=quantity, gross_revenue_cents=0), OPERATOR))


# --- Sync licensing pipelines -------------------------------------------------

def setup_sync_catalog(clock="2026-02-01T00:00:00.000Z",
                       rec_release="PHYSICAL", rec_duration=200,
                       window_start="2026-01-01T00:00:00.000Z",
                       window_end="2027-01-01T00:00:00.000Z",
                       grant_sync_window=True, territory="US"):
    """A locked recording (100% LABEL holder) plus a distinct licensee LABEL party,
    optionally with an ACTIVE SYNC window covering territory.

    Returns dict: label, licensee, work, recording, window (or None).
    """
    set_clock(clock)
    label = create_rightsholder(legal_name="Label Owner", party_type="LABEL")
    licensee = create_rightsholder(legal_name="Licensee Co", party_type="LABEL")
    work = create_registered_work(label["id"], pro_affiliation="BMI", duration_seconds=rec_duration,
                                   role="PUBLISHER")
    rec = create_locked_recording(work["id"], label["id"], release_type=rec_release,
                                   duration_seconds=rec_duration)
    window = None
    if grant_sync_window:
        window = grant_window(rec["id"], "SYNC", window_start, window_end, territory=territory)
    return {"label": label, "licensee": licensee, "work": work, "recording": rec, "window": window}


def create_sync_license(recording_id, licensee_id, **overrides) -> dict:
    payload = create_sync_license_payload(recording_id=recording_id, licensee_id=licensee_id, **overrides)
    return get_success_data(api_client.create_sync_license(payload, OPERATOR))


def setup_draft_sync_license(clock="2026-02-01T00:00:00.000Z", media_type="FILM",
                             territory="US", term_months=24, base_fee_cents=100000,
                             grant_sync_window=True):
    """Sync catalog + one DRAFT sync license owned by the licensee.
    Returns dict: label, licensee, recording, window, sync_license."""
    ctx = setup_sync_catalog(clock=clock, grant_sync_window=grant_sync_window, territory=territory)
    sl = create_sync_license(ctx["recording"]["id"], ctx["licensee"]["id"],
                             media_type=media_type, territory=territory,
                             term_months=term_months, base_fee_cents=base_fee_cents)
    ctx["sync_license"] = sl
    return ctx
