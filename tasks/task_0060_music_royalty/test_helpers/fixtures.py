"""Composite setup helpers for the Music Royalty test suite.

Most interesting test claims need the system in a specific state reached
through many API calls (rights-holder → work → share → submit →
take-review → approve → playback-ingest → distribution-rule → pool →
close → ...). These helpers encapsulate those preambles so test bodies
stay focused on assertions.

Identity threading (PRD §2.1):
- RightsHolder is ENTITY-BACKED. PRD §2.1: 'When X-User-Role is
  RightsHolder, X-User-ID is the id of the acting RightsHolder; ownership
  checks on any resource that references a RightsHolder compare the
  resource's foreign-key field to X-User-ID.' Every ownership-gated
  RightsHolder call MUST use make_rights_holder_headers(holder['id']).
- PlatformAdmin, RegistrationReviewer, FinanceOps, DisputeOfficer,
  PlaybackSource are OPAQUE — shared constants are safe.

Setup helpers use get_success_data() (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion failure
inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    DEFAULT_PLAYBACK_SECRET,
    abandon_payment_payload,
    clock_advance_payload,
    compute_hmac_signature,
    create_agency_binding_payload,
    create_composition_work_payload,
    create_dispute_payload,
    create_distribution_rule_payload,
    create_individual_rights_holder_payload,
    create_minor_rights_holder_payload,
    create_payout_batch_payload,
    create_playback_batch_payload,
    create_recording_work_payload,
    create_rights_holder_payload,
    create_rights_share_payload,
    create_royalty_pool_payload,
    make_playback_event,
    psp_callback_payload,
    reject_work_payload,
    resolve_dispute_payload,
    submit_evidence_payload,
    unique_cycle_tag,
    unique_isrc,
    unique_iswc,
    unique_source_identifier,
    unique_version_tag,
    utc_iso,
)
from .test_users import (
    TEST_USERS,
    make_rights_holder_headers,
)


# ===========================================================================
# Shared opaque-role headers (PRD §2.1).
# ===========================================================================
PA = TEST_USERS["platform_admin_headers"]
PA_ALT = TEST_USERS["platform_admin_headers_alt"]
REV = TEST_USERS["registration_reviewer_headers"]
REV_ALT = TEST_USERS["registration_reviewer_headers_alt"]
FIN = TEST_USERS["finance_ops_headers"]
FIN_ALT = TEST_USERS["finance_ops_headers_alt"]
DOFF = TEST_USERS["dispute_officer_headers"]
DOFF_ALT = TEST_USERS["dispute_officer_headers_alt"]
PSRC = TEST_USERS["playback_source_headers"]


# ---------------------------------------------------------------------------
# Monotonic per-pool offset.
#
# PRD §3.8 says pool eligibility filters by region/channel/period/work; it
# does NOT scope events to "the events created during this pool's setup".
# When tests run sequentially against the same process, two pools sharing
# region+channel+period will see each other's events, contaminating
# distributions.
#
# We give each setup_closeable_pool_for_works call a unique period window
# (sliding back in 1-minute increments) so each pool's eligibility filter
# sees only its own batch's events. This is purely a test-isolation
# device; the implementation behaves exactly per PRD.
# ---------------------------------------------------------------------------
_POOL_OFFSET_COUNTER = 0


def _next_pool_offset_minutes() -> int:
    global _POOL_OFFSET_COUNTER
    _POOL_OFFSET_COUNTER += 1
    return _POOL_OFFSET_COUNTER


# ===========================================================================
# Time helpers
# ===========================================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return utc_iso(dt)


# ===========================================================================
# Clock and sweep helpers (PRD §3.14)
# ===========================================================================
def advance_clock(to_iso: str) -> Dict[str, Any]:
    return get_success_data(api_client.advance_clock(
        clock_advance_payload(to=to_iso), PA,
    ))


def run_sweep() -> Dict[str, Any]:
    return get_success_data(api_client.run_sweep(PA))


# ===========================================================================
# Rights-holder helpers (PRD §3.5)
# ===========================================================================
def create_rights_holder(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_rights_holder(
        create_rights_holder_payload(**overrides), PA,
    ))


def create_individual_holder(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_rights_holder(
        create_individual_rights_holder_payload(**overrides), PA,
    ))


def create_org_holder(**overrides: Any) -> Dict[str, Any]:
    """Adult ORGANIZATION holder — common parent / guardian shape."""
    return get_success_data(api_client.create_rights_holder(
        create_rights_holder_payload(holder_kind="ORGANIZATION", **overrides),
        PA,
    ))


def setup_minor_with_guardian(
    minor_dob: str = "2018-01-01",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """PRD §3.5: minor's guardian must be ORGANIZATION or adult INDIVIDUAL."""
    guardian = create_org_holder(legal_name="Guardian Org")
    minor = get_success_data(api_client.create_rights_holder(
        create_minor_rights_holder_payload(
            guardian_holder_id=guardian["id"], date_of_birth=minor_dob,
        ), PA,
    ))
    return minor, guardian


# ===========================================================================
# Agency-binding helpers (PRD §3.4)
# ===========================================================================
def create_agency_binding(
    rights_holder_id: str,
    *,
    effective_from: Optional[str] = None,
    effective_until: Optional[str] = None,
    territory: str = "WW",
    **overrides: Any,
) -> Dict[str, Any]:
    if effective_from is None:
        effective_from = iso(now_utc() - timedelta(days=30))
    return get_success_data(api_client.create_agency_binding(
        create_agency_binding_payload(
            rights_holder_id=rights_holder_id,
            effective_from=effective_from,
            effective_until=effective_until,
            territory=territory,
            **overrides,
        ),
        make_rights_holder_headers(rights_holder_id),
    ))


# ===========================================================================
# Work / share helpers (PRD §3.1, §3.2, §3.3)
# ===========================================================================
def create_work_draft(holder_id: str,
                      *,
                      rights_type: str = "RECORDING",
                      **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT Work owned by holder_id. PRD §2.1: the acting
    RightsHolder must be the work's owner — entity-backed identity."""
    if rights_type in {"RECORDING", "PERFORMANCE"}:
        payload = create_recording_work_payload(rights_type=rights_type,
                                                **overrides)
    else:
        payload = create_composition_work_payload(rights_type=rights_type,
                                                  **overrides)
    return get_success_data(api_client.create_work(
        payload, make_rights_holder_headers(holder_id),
    ))


def create_share(work_id: str, work_owner_id: str,
                 share_rights_holder_id: str,
                 share_percent: float,
                 *,
                 agency_binding_id: Optional[str] = None) -> Dict[str, Any]:
    """Add a RightsShare. PRD §3.3: only the owning RightsHolder (or admin)
    may add shares on a work. We use the work's OWNER headers."""
    extra: Dict[str, Any] = {}
    if agency_binding_id is not None:
        extra["agency_binding_id"] = agency_binding_id
    return get_success_data(api_client.create_share(
        work_id,
        create_rights_share_payload(
            rights_holder_id=share_rights_holder_id,
            share_percent=share_percent,
            **extra,
        ),
        make_rights_holder_headers(work_owner_id),
    ))


def submit_work(work_id: str, holder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_work(
        work_id, make_rights_holder_headers(holder_id),
    ))


def take_review(work_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.take_review_work(work_id, REV))


def approve_work(work_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.approve_work(work_id, REV))


def reject_work(work_id: str,
                reason: str = "Insufficient proof.") -> Dict[str, Any]:
    return get_success_data(api_client.reject_work(
        work_id, reject_work_payload(reject_reason=reason), REV,
    ))


def return_to_draft(work_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.return_to_draft_work(work_id, REV))


def withdraw_work(work_id: str, holder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.withdraw_work(
        work_id, make_rights_holder_headers(holder_id),
    ))


def setup_approved_recording_work(
    *,
    holder_legal_name: str = "Recording Holder",
    duration_seconds: int = 300,
    **work_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create RightsHolder → Work (RECORDING) → 100% share → submit →
    take-review → approve. Returns (holder, work, share). Work is APPROVED,
    posture CLEAR."""
    holder = create_rights_holder(legal_name=holder_legal_name)
    work = create_work_draft(
        holder["id"], rights_type="RECORDING",
        duration_seconds=duration_seconds, **work_overrides,
    )
    share = create_share(work["id"], holder["id"], holder["id"], 100.00)
    submit_work(work["id"], holder["id"])
    take_review(work["id"])
    approved = approve_work(work["id"])
    return holder, approved, share


def setup_approved_composition_work(
    *,
    holder_legal_name: str = "Composition Holder",
    duration_seconds: int = 300,
    **work_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Same as recording flow but rights_type=COMPOSITION (PRD §3.1: ISWC,
    routes to MECHANICAL sub-pool)."""
    holder = create_rights_holder(legal_name=holder_legal_name)
    work = create_work_draft(
        holder["id"], rights_type="COMPOSITION",
        duration_seconds=duration_seconds, **work_overrides,
    )
    share = create_share(work["id"], holder["id"], holder["id"], 100.00)
    submit_work(work["id"], holder["id"])
    take_review(work["id"])
    approved = approve_work(work["id"])
    return holder, approved, share


def setup_approved_work_with_multi_share(
    share_specs: List[Tuple[float, Optional[str]]],
    *,
    rights_type: str = "RECORDING",
    duration_seconds: int = 300,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create work with multiple ACTIVE RightsShares summing to 100.

    share_specs: list of (percent, legal_name_or_None). The first holder
    in share_specs is the work owner. Returns (work, holders, shares)."""
    if not share_specs:
        raise ValueError("share_specs must contain at least one entry")
    total = sum(p for p, _ in share_specs)
    if abs(total - 100.0) > 1e-6:
        raise ValueError("share percents must sum to 100.00")
    holders: List[Dict[str, Any]] = []
    for idx, (_, name) in enumerate(share_specs):
        h = create_rights_holder(legal_name=name or f"Holder {idx + 1}")
        holders.append(h)
    owner = holders[0]
    if rights_type in {"RECORDING", "PERFORMANCE"}:
        work = create_work_draft(
            owner["id"], rights_type=rights_type,
            duration_seconds=duration_seconds,
        )
    else:
        work = create_work_draft(
            owner["id"], rights_type=rights_type,
            duration_seconds=duration_seconds,
        )
    shares: List[Dict[str, Any]] = []
    for (percent, _), h in zip(share_specs, holders):
        s = create_share(work["id"], owner["id"], h["id"], percent)
        shares.append(s)
    submit_work(work["id"], owner["id"])
    take_review(work["id"])
    approved = approve_work(work["id"])
    return approved, holders, shares


# ===========================================================================
# Distribution-rule helpers (PRD §3.7)
# ===========================================================================
def create_distribution_rule(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_distribution_rule(
        create_distribution_rule_payload(**overrides), PA,
    ))


def create_per_play_rule(*, channel: str = "STREAMING",
                        minimum_payout_cents: int = 0,
                        micro_accumulation_cap_cents: int = 100_000,
                        playback_type_weights: Optional[Dict[str, float]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    weights = playback_type_weights or {
        "FULL_PLAY": 1.00, "SKIP": 1.00,
        "BACKGROUND": 1.00, "FOREGROUND": 1.00,
    }
    return create_distribution_rule(
        distribution_mode="PER_PLAY",
        channel=channel,
        playback_type_weights=weights,
        minimum_payout_cents=minimum_payout_cents,
        micro_accumulation_cap_cents=micro_accumulation_cap_cents,
        per_play_weight=1.00,
        **overrides,
    )


def create_per_duration_rule(*, channel: str = "STREAMING",
                             minimum_payout_cents: int = 0,
                             micro_accumulation_cap_cents: int = 100_000,
                             playback_type_weights: Optional[Dict[str, float]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    weights = playback_type_weights or {
        "FULL_PLAY": 1.00, "SKIP": 1.00,
        "BACKGROUND": 1.00, "FOREGROUND": 1.00,
    }
    return create_distribution_rule(
        distribution_mode="PER_DURATION",
        channel=channel,
        playback_type_weights=weights,
        minimum_payout_cents=minimum_payout_cents,
        micro_accumulation_cap_cents=micro_accumulation_cap_cents,
        per_duration_weight=1.00,
        **overrides,
    )


# ===========================================================================
# Playback ingest helpers (PRD §3.6)
# ===========================================================================
def ingest_playback_batch(
    events: List[Dict[str, Any]],
    *,
    source_identifier: Optional[str] = None,
    channel: str = "STREAMING",
    reporting_period_start: Optional[str] = None,
    reporting_period_end: Optional[str] = None,
    source_secret: Optional[str] = None,
    source_signature: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Ingest a playback batch under PlaybackSource role.

    PRD §2.8 / §3.6: server validates signature against the secret
    pre-registered against the reporting source_identifier. PRD does not
    expose a registration endpoint, so the deterministic per-source key
    is the source_identifier itself; the factory therefore signs with
    secret == source_identifier by default (caller can override).

    Defaults: a 24-hour reporting window ending ~1h ago to satisfy PRD
    §2.10 priority 21 (end <= now and span <= 31 days)."""
    if source_identifier is None:
        source_identifier = unique_source_identifier()
    now = now_utc()
    if reporting_period_end is None:
        reporting_period_end = iso(now - timedelta(hours=1))
    if reporting_period_start is None:
        reporting_period_start = iso(now - timedelta(hours=25))
    payload = create_playback_batch_payload(
        events=events,
        source_identifier=source_identifier,
        reporting_period_start=reporting_period_start,
        reporting_period_end=reporting_period_end,
        channel=channel,
        source_secret=source_secret,
        source_signature=source_signature,
        **overrides,
    )
    return get_success_data(api_client.create_playback_batch(payload, PSRC))


# ===========================================================================
# Royalty-pool helpers (PRD §3.8, §3.9, §3.10)
# ===========================================================================
def create_pool(
    *,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    distribution_rule_version_id: Optional[str] = None,
    region: str = "WW",
    revenue_source: str = "STREAMING",
    gross_revenue_cents: int = 20_000_000,
    platform_share_percent: float = 30.00,
    mechanical_split_percent: float = 0.00,
    pool_currency: str = "USD",
    **overrides: Any,
) -> Dict[str, Any]:
    now = now_utc()
    if period_end is None:
        period_end = iso(now - timedelta(hours=1))
    if period_start is None:
        period_start = iso(now - timedelta(days=14))
    return get_success_data(api_client.create_pool(
        create_royalty_pool_payload(
            period_start=period_start,
            period_end=period_end,
            distribution_rule_version_id=distribution_rule_version_id,
            region=region,
            revenue_source=revenue_source,
            gross_revenue_cents=gross_revenue_cents,
            platform_share_percent=platform_share_percent,
            mechanical_split_percent=mechanical_split_percent,
            pool_currency=pool_currency,
            **overrides,
        ),
        FIN,
    ))


def close_pool(pool_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_pool(pool_id, FIN))


def finalize_pool(pool_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_pool(pool_id, FIN))


def list_pool_distributions(pool_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_pool_distributions(pool_id, FIN, params={"limit": 100})
    data, _meta = validate_paginated(resp)
    return data


# ===========================================================================
# Composite: pool with ingested playback ready to close (PRD §3.8, §3.9)
# ===========================================================================
def setup_closeable_pool_for_works(
    works: List[Dict[str, Any]],
    *,
    revenue_source: str = "STREAMING",
    region: Optional[str] = None,
    gross_revenue_cents: int = 20_000_000,
    platform_share_percent: float = 30.00,
    mechanical_split_percent: float = 0.00,
    distribution_mode: str = "PER_PLAY",
    minimum_payout_cents: int = 0,
    micro_accumulation_cap_cents: int = 100_000,
    playback_type_weights: Optional[Dict[str, float]] = None,
    events_per_work: int = 1,
    play_duration_per_event: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build a closeable pool for the given list of APPROVED works.

    Steps: distribution-rule → period window → playback batch with one
    event per work → pool open (rule pinned). Caller closes when ready.
    Returns (pool, distribution_rule).
    """
    weights = playback_type_weights or {
        "FULL_PLAY": 1.00, "SKIP": 1.00,
        "BACKGROUND": 1.00, "FOREGROUND": 1.00,
    }
    rule = create_distribution_rule(
        distribution_mode=distribution_mode,
        channel=revenue_source,
        playback_type_weights=weights,
        minimum_payout_cents=minimum_payout_cents,
        micro_accumulation_cap_cents=micro_accumulation_cap_cents,
        per_play_weight=(
            1.00 if distribution_mode == "PER_PLAY"
            else (0.40 if distribution_mode == "HYBRID" else None)
        ),
        per_duration_weight=(
            1.00 if distribution_mode == "PER_DURATION"
            else (0.60 if distribution_mode == "HYBRID" else None)
        ),
    )

    now = now_utc()
    # Per-call unique offset + unique region to keep this pool's
    # eligibility window from overlapping with any other pool's window.
    # PRD §3.8 eligibility is region+channel+period; WW matches any
    # region, which without isolation lets every other test's events
    # contaminate this pool. Each fixture call therefore picks a fresh
    # 2-letter region by default; callers who actively need WW
    # behaviour pass region="WW" explicitly.
    offset_minutes = _next_pool_offset_minutes()
    period_end = now - timedelta(hours=1) - timedelta(minutes=offset_minutes)
    period_start = period_end - timedelta(days=10)
    if region is None:
        hi = (offset_minutes // 26) % 26
        lo = offset_minutes % 26
        region = chr(ord("A") + hi) + chr(ord("A") + lo)
    event_region = region if region != "WW" else (
        chr(ord("A") + ((offset_minutes // 26) % 26))
        + chr(ord("A") + (offset_minutes % 26))
    )

    events: List[Dict[str, Any]] = []
    played_at = iso(period_start + timedelta(hours=1))
    for w in works:
        dur = play_duration_per_event or w.get("duration_seconds", 300)
        for _ in range(events_per_work):
            events.append(make_playback_event(
                work_id=w["id"],
                play_duration_seconds=dur,
                played_at=played_at,
                region=event_region,
            ))

    ingest_playback_batch(
        events,
        reporting_period_start=iso(period_start),
        reporting_period_end=iso(period_end),
        channel=revenue_source,
    )

    pool = create_pool(
        period_start=iso(period_start),
        period_end=iso(period_end),
        distribution_rule_version_id=rule["id"],
        revenue_source=revenue_source,
        region=region,
        gross_revenue_cents=gross_revenue_cents,
        platform_share_percent=platform_share_percent,
        mechanical_split_percent=mechanical_split_percent,
    )
    return pool, rule


def setup_closed_pool_for_works(
    works: List[Dict[str, Any]],
    **pool_kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """As above plus invoking close. Returns (pool_after_close, rule,
    distributions)."""
    pool, rule = setup_closeable_pool_for_works(works, **pool_kwargs)
    closed = close_pool(pool["id"])
    dists = list_pool_distributions(pool["id"])
    return closed, rule, dists


def setup_distributed_pool_for_works(
    works: List[Dict[str, Any]],
    **pool_kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Close + finalize so PENDING → RELEASED (PRD §3.10). Returns
    (pool_after_finalize, rule, distributions_after)."""
    closed, rule, _ = setup_closed_pool_for_works(works, **pool_kwargs)
    finalize_pool(closed["id"])
    dists = list_pool_distributions(closed["id"])
    return closed, rule, dists


# ===========================================================================
# Dispute helpers (PRD §3.11)
# ===========================================================================
def open_dispute(work_id: str, claimant_holder_id: str,
                 *, dispute_kind: str = "OWNERSHIP",
                 claim_summary: str = "Test claim.") -> Dict[str, Any]:
    return get_success_data(api_client.create_dispute(
        create_dispute_payload(
            work_id=work_id, dispute_kind=dispute_kind,
            claim_summary=claim_summary,
        ),
        make_rights_holder_headers(claimant_holder_id),
    ))


def submit_evidence(dispute_id: str,
                    submitter_holder_id: Optional[str] = None,
                    *,
                    url: str = "https://example.com/evidence.pdf",
                    as_officer: bool = False) -> Dict[str, Any]:
    headers = (DOFF if as_officer
               else make_rights_holder_headers(submitter_holder_id))
    return get_success_data(api_client.submit_evidence(
        dispute_id, submit_evidence_payload(url=url), headers,
    ))


def start_investigation(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_investigation(dispute_id, DOFF))


def advance_to_mediation(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.advance_to_mediation(dispute_id, DOFF))


def reopen_investigation(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reopen_investigation(dispute_id, DOFF))


def advance_to_arbitration(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.advance_to_arbitration(dispute_id, DOFF))


def resolve_dispute(dispute_id: str, *,
                    outcome: str = "DISMISSED",
                    arbitration_decision: str = "No merit.",
                    **extra: Any) -> Dict[str, Any]:
    return get_success_data(api_client.resolve_dispute(
        dispute_id,
        resolve_dispute_payload(
            outcome=outcome, arbitration_decision=arbitration_decision, **extra,
        ),
        DOFF,
    ))


def withdraw_dispute(dispute_id: str,
                     claimant_holder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.withdraw_dispute(
        dispute_id, make_rights_holder_headers(claimant_holder_id),
    ))


def setup_dispute_through_arbitration(
    work_id: str, claimant_holder_id: str,
    *, dispute_kind: str = "OWNERSHIP",
) -> Dict[str, Any]:
    """Open dispute → investigate → 2 evidence → mediation → arbitration.

    Returns the most-recent response (which represents the dispute in
    ARBITRATION status). PRD §3.11 / §4 do not expose a standalone GET on
    /disputes/{id}, so callers consume the body of the final mutation."""
    disp = open_dispute(work_id, claimant_holder_id,
                        dispute_kind=dispute_kind)
    start_investigation(disp["id"])
    submit_evidence(disp["id"], claimant_holder_id,
                    url="https://example.com/ev1.pdf")
    submit_evidence(disp["id"], as_officer=True,
                    url="https://example.com/ev2.pdf")
    advance_to_mediation(disp["id"])
    return advance_to_arbitration(disp["id"])


# ===========================================================================
# Payout / payment helpers (PRD §3.12, §3.13)
# ===========================================================================
def create_payout_batch(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_payout_batch(
        create_payout_batch_payload(**overrides), FIN,
    ))


def execute_payout_batch(batch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.execute_payout_batch(batch_id, FIN))


def list_batch_payments(batch_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_batch_payments(batch_id, FIN, params={"limit": 100})
    data, _meta = validate_paginated(resp)
    return data


def psp_callback_success(payment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.psp_callback(
        psp_callback_payload(payment_id=payment_id, outcome="SUCCESS"), PA,
    ))


def psp_callback_failure(payment_id: str,
                         reason: str = "psp_timeout") -> Dict[str, Any]:
    return get_success_data(api_client.psp_callback(
        psp_callback_payload(payment_id=payment_id, outcome="FAILURE",
                             reason=reason),
        PA,
    ))


def retry_payment(payment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.retry_payment(payment_id, FIN))


def abandon_payment(payment_id: str,
                    policy: str = "RETURN_TO_MICRO") -> Dict[str, Any]:
    return get_success_data(api_client.abandon_payment(
        payment_id, abandon_payment_payload(policy=policy), FIN,
    ))


def get_micro_balance(holder_id: str) -> List[Dict[str, Any]]:
    resp = api_client.get_micro_balance(
        holder_id, make_rights_holder_headers(holder_id),
    )
    data = get_success_data(resp)
    # PRD §3.15 returns a list.
    return data if isinstance(data, list) else [data]


# ===========================================================================
# Difficulty-design composite helpers.
# These are pinned to instances in SCAFFOLD_DIFFICULTY_DESIGN.yaml so that
# the corresponding tests can build the required state by name.
# ===========================================================================

def setup_minimum_payout_boundary(
    *,
    minimum_payout_cents: int = 500,
    micro_accumulation_cap_cents: int = 2000,
    target_gross_cents_h1: int = 500,
    target_gross_cents_h2: int = 499,
) -> Dict[str, Any]:
    """Difficulty-design: minimum_payout_threshold_exact_equal_inclusive.

    Build two holders so that batch generation produces:
      H1: a candidate gross EXACTLY equal to minimum_payout_cents → Payment.
      H2: a candidate gross JUST UNDER threshold → no Payment, MicroBalance bumps.

    Strategy: each holder owns 100% of a small APPROVED work with one
    eligible playback event; pool sizes are chosen so net-after-commission
    matches the targets. Both works are RECORDING (PERFORMANCE sub-pool).
    Two SEPARATE pools so cents are deterministic per work.
    """
    h1 = create_rights_holder(legal_name="Boundary H1")
    h2 = create_rights_holder(legal_name="Boundary H2")
    w1 = create_work_draft(h1["id"], rights_type="RECORDING",
                           duration_seconds=300, isrc=unique_isrc())
    create_share(w1["id"], h1["id"], h1["id"], 100.00)
    submit_work(w1["id"], h1["id"]); take_review(w1["id"]); approve_work(w1["id"])

    w2 = create_work_draft(h2["id"], rights_type="RECORDING",
                           duration_seconds=300, isrc=unique_isrc())
    create_share(w2["id"], h2["id"], h2["id"], 100.00)
    submit_work(w2["id"], h2["id"]); take_review(w2["id"]); approve_work(w2["id"])

    # Pool sizes: gross_revenue_cents * (1 - platform/100) ≈ net_distributable.
    # With platform=0 and admin tier 1 = 5% (PRD §3.8), 5% of gross is
    # deducted. To target 500 cents per holder after tier-1 fee:
    #   target = round(gross * 0.95). For target 500 → gross = 527 cents
    #     gross 527 → tier1 fee round(527 * 0.05) = 26; net = 501. Use 526
    #     net = 526 - round(526*0.05=26.3 → 26) = 500. Use 526.
    # Build separate pool for each holder with carefully chosen gross.
    # H1 target 500:
    pool1_gross = 526
    # H2 target 499:
    pool2_gross = 525  # 525 - round(525*0.05=26.25 → 26) = 499.

    rule = create_per_play_rule(
        channel="STREAMING",
        minimum_payout_cents=minimum_payout_cents,
        micro_accumulation_cap_cents=micro_accumulation_cap_cents,
    )

    now = now_utc()
    # Per-pool unique region + offset so other tests' WW events do not
    # leak into this fixture's eligibility window. PRD §3.8 region rule:
    # "two-letter country code" (regex [A-Z]{2}).
    off1 = _next_pool_offset_minutes()
    off2 = _next_pool_offset_minutes()
    region1 = chr(ord("A") + ((off1 // 26) % 26)) + chr(ord("A") + (off1 % 26))
    region2 = chr(ord("A") + ((off2 // 26) % 26)) + chr(ord("A") + (off2 % 26))
    p_end = now - timedelta(hours=1) - timedelta(minutes=off1)
    p_start = p_end - timedelta(days=5)

    # Pool 1 — H1
    ingest_playback_batch(
        [make_playback_event(work_id=w1["id"], play_duration_seconds=300,
                             played_at=iso(p_start + timedelta(hours=1)),
                             region=region1)],
        reporting_period_start=iso(p_start),
        reporting_period_end=iso(p_end),
        channel="STREAMING",
        source_identifier=unique_source_identifier(),
    )
    pool1 = create_pool(
        period_start=iso(p_start), period_end=iso(p_end),
        distribution_rule_version_id=rule["id"],
        revenue_source="STREAMING", region=region1,
        gross_revenue_cents=pool1_gross,
        platform_share_percent=0.00, mechanical_split_percent=0.00,
    )
    close_pool(pool1["id"]); finalize_pool(pool1["id"])

    # Pool 2 — H2; offset window further so it does not overlap pool 1.
    p_end2 = now - timedelta(hours=1) - timedelta(minutes=off2)
    p_start2 = p_end2 - timedelta(days=5)
    ingest_playback_batch(
        [make_playback_event(work_id=w2["id"], play_duration_seconds=300,
                             played_at=iso(p_start2 + timedelta(hours=1)),
                             region=region2)],
        reporting_period_start=iso(p_start2),
        reporting_period_end=iso(p_end2),
        channel="STREAMING",
        source_identifier=unique_source_identifier(),
    )
    pool2 = create_pool(
        period_start=iso(p_start2), period_end=iso(p_end2),
        distribution_rule_version_id=rule["id"],
        revenue_source="STREAMING", region=region2,
        gross_revenue_cents=pool2_gross,
        platform_share_percent=0.00, mechanical_split_percent=0.00,
    )
    close_pool(pool2["id"]); finalize_pool(pool2["id"])

    return {
        "h1": h1, "h2": h2,
        "w1": w1, "w2": w2,
        "pool1": pool1, "pool2": pool2,
        "rule": rule,
    }


def setup_per_play_vs_per_duration_pair(
    *,
    work_duration: int = 300,
) -> Dict[str, Any]:
    """Difficulty-design: pool_net_distributable_pricing_variant_per_play_vs_per_duration.

    Two pools sharing identical input shape but pinned to PER_PLAY vs
    PER_DURATION rule. Each pool covers TWO works (HolderA = both 100%
    of each work) with one 5s event and one 305s event, so the PER_PLAY
    split is 50/50 and the PER_DURATION split is 5/(5+305) vs 305/(5+305)
    → strictly different per-work gross."""
    holder = create_rights_holder(legal_name="HolderA")

    def _approved_recording(dur: int) -> Dict[str, Any]:
        w = create_work_draft(holder["id"], rights_type="RECORDING",
                              duration_seconds=dur, isrc=unique_isrc())
        create_share(w["id"], holder["id"], holder["id"], 100.00)
        submit_work(w["id"], holder["id"]); take_review(w["id"])
        return approve_work(w["id"])

    w_short = _approved_recording(5)
    w_long = _approved_recording(work_duration)

    rule_play = create_per_play_rule(channel="STREAMING")
    rule_dur = create_per_duration_rule(channel="STREAMING")

    now = now_utc()

    def _build_pool(rule_id: str, src: str) -> Dict[str, Any]:
        # Per-pool unique region + offset isolates from prior tests.
        off = _next_pool_offset_minutes()
        region = chr(ord("A") + ((off // 26) % 26)) + chr(ord("A") + (off % 26))
        p_end = now - timedelta(hours=1) - timedelta(minutes=off)
        p_start = p_end - timedelta(days=5)
        ingest_playback_batch(
            [
                make_playback_event(work_id=w_short["id"],
                                    play_duration_seconds=5,
                                    played_at=iso(p_start + timedelta(hours=1)),
                                    region=region),
                make_playback_event(work_id=w_long["id"],
                                    play_duration_seconds=305 if work_duration >= 305
                                    else work_duration,
                                    played_at=iso(p_start + timedelta(hours=2)),
                                    region=region),
            ],
            reporting_period_start=iso(p_start),
            reporting_period_end=iso(p_end),
            channel="STREAMING",
            source_identifier=src,
        )
        pool = create_pool(
            period_start=iso(p_start), period_end=iso(p_end),
            distribution_rule_version_id=rule_id,
            revenue_source="STREAMING", region=region,
            gross_revenue_cents=20_000_000,
            platform_share_percent=30.00, mechanical_split_percent=0.00,
        )
        close_pool(pool["id"])
        return pool

    p_play = _build_pool(rule_play["id"], unique_source_identifier())
    p_dur = _build_pool(rule_dur["id"], unique_source_identifier())

    return {
        "holder": holder,
        "w_short": w_short, "w_long": w_long,
        "rule_play": rule_play, "rule_dur": rule_dur,
        "pool_play": p_play, "pool_dur": p_dur,
    }


def setup_dispute_open_freezes_distribution() -> Dict[str, Any]:
    """Difficulty-design: dispute_open_cascade_depth_2.

    Approve work → ingest playback → close pool (PENDING distribution
    exists) → open Dispute → PENDING distribution flips to FROZEN."""
    h1, w1, _share = setup_approved_recording_work()
    closed, _rule, dists_before = setup_closed_pool_for_works(
        [w1], gross_revenue_cents=20_000_000,
    )
    # Open dispute by the same holder.
    disp = open_dispute(w1["id"], h1["id"], dispute_kind="OWNERSHIP")
    return {
        "holder": h1, "work": w1, "pool": closed,
        "dispute": disp, "distributions_before": dists_before,
    }


def setup_frozen_distributions_for_finalize_block() -> Dict[str, Any]:
    """Difficulty-design: pool_finalize_depends_on_distribution_states.

    Identical to above; the test asserts finalize is blocked."""
    return setup_dispute_open_freezes_distribution()


def setup_payment_failed_payment_for_abandon(
    *,
    enough_gross_cents: int = 200_000,
) -> Dict[str, Any]:
    """Build a holder with a single APPROVED RECORDING work, distribution
    finalized → payout batch generated → execute → PSP failure → retry
    saturates → ready to abandon. Returns dict with all entities.

    Uses a fat pool so that net-after-commission for the single holder is
    well above the minimum_payout (use min=0).
    """
    holder, work, _share = setup_approved_recording_work(
        holder_legal_name="Failed Payment Holder",
    )
    closed, _rule, _dists = setup_distributed_pool_for_works(
        [work], gross_revenue_cents=enough_gross_cents,
        minimum_payout_cents=0,
    )
    batch = create_payout_batch()
    execute_payout_batch(batch["id"])
    payments = list_batch_payments(batch["id"])
    pay = next(p for p in payments if p["rights_holder_id"] == holder["id"])
    # PSP failure → FAILED.
    psp_callback_failure(pay["id"], reason="psp_timeout")
    return {
        "holder": holder, "work": work, "pool": closed,
        "batch": batch, "payment": pay,
    }


def setup_dispute_cyclic_through_resolved(
    *, holder: Optional[Dict[str, Any]] = None,
    work: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Difficulty-design: dispute_cyclic_mediation_investigation_loop.

    Open dispute → start-investigation → 2 evidence → mediation →
    reopen-investigation → mediation (again) → arbitration → resolve
    DISMISSED."""
    if holder is None or work is None:
        holder, work, _ = setup_approved_recording_work()
    disp = open_dispute(work["id"], holder["id"], dispute_kind="OWNERSHIP")
    start_investigation(disp["id"])
    submit_evidence(disp["id"], holder["id"], url="https://example.com/e1.pdf")
    submit_evidence(disp["id"], as_officer=True,
                    url="https://example.com/e2.pdf")
    med_response_1 = advance_to_mediation(disp["id"])
    reopen_response = reopen_investigation(disp["id"])
    med_response_2 = advance_to_mediation(disp["id"])
    arb_response = advance_to_arbitration(disp["id"])
    resolved = resolve_dispute(disp["id"], outcome="DISMISSED",
                               arbitration_decision="no merit")
    return {
        "holder": holder, "work": work, "dispute": disp,
        "mediation_1": med_response_1, "reopen": reopen_response,
        "mediation_2": med_response_2, "arbitration": arb_response,
        "resolved": resolved,
    }


__all__ = [
    "PA", "PA_ALT", "REV", "REV_ALT", "FIN", "FIN_ALT",
    "DOFF", "DOFF_ALT", "PSRC",
    "now_utc", "iso",
    "advance_clock", "run_sweep",
    "create_rights_holder", "create_individual_holder", "create_org_holder",
    "setup_minor_with_guardian",
    "create_agency_binding",
    "create_work_draft", "create_share",
    "submit_work", "take_review", "approve_work", "reject_work",
    "return_to_draft", "withdraw_work",
    "setup_approved_recording_work", "setup_approved_composition_work",
    "setup_approved_work_with_multi_share",
    "create_distribution_rule", "create_per_play_rule", "create_per_duration_rule",
    "ingest_playback_batch",
    "create_pool", "close_pool", "finalize_pool", "list_pool_distributions",
    "setup_closeable_pool_for_works", "setup_closed_pool_for_works",
    "setup_distributed_pool_for_works",
    "open_dispute", "submit_evidence",
    "start_investigation", "advance_to_mediation", "reopen_investigation",
    "advance_to_arbitration", "resolve_dispute", "withdraw_dispute",
    "setup_dispute_through_arbitration",
    "create_payout_batch", "execute_payout_batch", "list_batch_payments",
    "psp_callback_success", "psp_callback_failure",
    "retry_payment", "abandon_payment",
    "get_micro_balance",
    "setup_minimum_payout_boundary",
    "setup_per_play_vs_per_duration_pair",
    "setup_dispute_open_freezes_distribution",
    "setup_frozen_distributions_for_finalize_block",
    "setup_payment_failed_payment_for_abandon",
    "setup_dispute_cyclic_through_resolved",
]
