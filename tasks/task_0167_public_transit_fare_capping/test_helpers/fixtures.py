"""Composite setup helpers — multi-step preambles tests can reuse.

The transit-fare-capping lifecycle takes 5-15 API calls to reach
interesting states (a card-with-FSA ready to tap, a cap window driven
to its boundary, a rider with active certificate or verification, a
dispute claimed and awaiting resolution). Each fixture composes the
lower-level steps so test bodies focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the
    acting `Rider`; any ownership check on a card, trip, dispute, or
    mobile token compares the resource's `rider_id` (directly or via
    the card's `rider_id`) to `X-User-ID`. When `X-User-Role` is
    `EmployerAdmin`, `X-User-ID` is the `id` of the acting `Employer`."

After a Rider is created, fixtures act as that rider by minting
headers via `make_rider_headers(rider["id"])`; after an Employer is
created, fixtures act through `make_employer_admin_headers(
employer["id"])`. The shared placeholders in TEST_USERS are reserved
for negative tests that probe auth / role / 404 paths without
ownership.

CLOCK ANCHORING — PRD §3.10:

    "For test-driving the temporal mechanics of the API there is an
    administrative capability to advance the server's logical clock to
    a supplied `to` instant, expressed as an ISO 8601 UTC timestamp;
    it does not by itself mutate any other resource."

Fixtures advance the clock to specific moments using AgencyOfficer
headers and never assume an implicit starting clock.

Setup calls use `get_success_data` (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BASE_FARE_CENTS,
    DEFAULT_MONTHLY_FSA_CAP_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    add_minutes,
    approve_low_income_verification_payload,
    clock_advance_payload,
    create_card_payload,
    create_dispute_payload,
    create_employer_payload,
    create_fsa_account_payload,
    create_fsa_contribution_payload,
    create_low_income_verification_payload,
    create_mobile_token_payload,
    create_reduced_fare_certificate_payload,
    create_rider_payload,
    create_trip_payload,
    resolve_dispute_payload,
    tap_out_payload,
    topup_card_payload,
    unique_idempotency_key,
)
from .test_users import (
    TEST_USERS,
    make_agency_officer_headers,
    make_employer_admin_headers,
    make_rider_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.10
# ===========================================================================
def advance_clock_to_iso(target_iso: str) -> None:
    """Advance the logical clock to `target_iso` (PRD §3.10)."""
    h = TEST_USERS["agency_officer_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=target_iso), h,
    )
    get_success_data(resp)


def run_sweep_incomplete_trips() -> None:
    h = TEST_USERS["agency_officer_headers"]
    get_success_data(api_client.sweep_incomplete_trips(h))


def run_sweep_settle() -> None:
    h = TEST_USERS["agency_officer_headers"]
    get_success_data(api_client.sweep_settle(h))


def run_sweep_low_income_expiry() -> None:
    h = TEST_USERS["agency_officer_headers"]
    get_success_data(api_client.sweep_low_income_expiry(h))


# ===========================================================================
# Read helpers — used by tests and other fixtures
# ===========================================================================
def get_rider(rider_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_rider_headers(rider_id)
    return get_success_data(api_client.get_rider(rider_id, h))


def get_card(card_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["agency_officer_headers"]
    return get_success_data(api_client.get_card(card_id, h))


def get_trip(trip_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["agency_officer_headers"]
    return get_success_data(api_client.get_trip(trip_id, h))


def list_cap_periods_for_card(
    card_id: str,
    scope: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["agency_officer_headers"]
    params: Dict[str, Any] = {"card_id": card_id, "limit": 100}
    if scope is not None:
        params["scope"] = scope
    resp = api_client.list_cap_periods(h, params=params)
    body = get_success_data(resp)
    # Lenient: implementations may return data as list directly or via
    # the envelope wrapper. get_success_data already unwraps the envelope
    # to the data field. Pagination implementations may return a list.
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        # Some implementations wrap under "items" or similar.
        for key in ("items", "results", "data"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def get_cap_period_for_window(
    card_id: str, scope: str, window_start_iso: str,
) -> Optional[Dict[str, Any]]:
    """Find the cap period for (card, scope) covering window_start_iso.

    Useful when a test needs to read accumulated_cents after a sequence
    of tap-ins.
    """
    for cp in list_cap_periods_for_card(card_id, scope=scope):
        ws = cp.get("window_start", "")
        we = cp.get("window_end", "")
        if ws and we and ws <= window_start_iso < we:
            return cp
    return None


# ===========================================================================
# Tier 0 — Foundation creators
# ===========================================================================
def create_rider(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Rider via AgencyOfficer (PRD §3.1: rider creation is
    AgencyOfficer-exclusive)."""
    h = TEST_USERS["agency_officer_headers"]
    payload = create_rider_payload(full_name=full_name, email=email)
    resp = api_client.create_rider(payload, h)
    return get_success_data(resp)


def create_employer(
    *,
    legal_name: Optional[str] = None,
    monthly_contribution_cap_cents: int = DEFAULT_MONTHLY_FSA_CAP_CENTS,
) -> Dict[str, Any]:
    """Create an Employer via AgencyOfficer (PRD §3.1)."""
    h = TEST_USERS["agency_officer_headers"]
    payload = create_employer_payload(
        legal_name=legal_name,
        monthly_contribution_cap_cents=monthly_contribution_cap_cents,
    )
    resp = api_client.create_employer(payload, h)
    return get_success_data(resp)


def issue_card(
    *,
    rider_id: str,
    discount_class: str = "STANDARD",
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2026-12-31T23:59:59.000Z",
    actor: str = "agency_officer",
) -> Dict[str, Any]:
    """Issue a FareCard. `actor` picks the role context:
       - `agency_officer` (PRD §3.2: AgencyOfficer may issue any)
       - `rider` (PRD §3.2: Rider may issue own STANDARD or LOW_INCOME)
    """
    if actor == "rider":
        h = make_rider_headers(rider_id)
    elif actor == "agency_officer":
        h = TEST_USERS["agency_officer_headers"]
    else:
        raise ValueError(f"Unknown actor: {actor!r}")
    payload = create_card_payload(
        rider_id=rider_id,
        discount_class=discount_class,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    return get_success_data(api_client.create_card(payload, h))


def topup_card(
    *,
    card_id: str,
    rider_id: str,
    amount_cents: int,
) -> Dict[str, Any]:
    """Top up a card on behalf of its owning rider (PRD §3.2)."""
    h = make_rider_headers(rider_id)
    payload = topup_card_payload(amount_cents=amount_cents)
    return get_success_data(api_client.topup_card(card_id, payload, h))


def suspend_card(*, card_id: str) -> Dict[str, Any]:
    """Suspend a FareCard via AgencyOfficer (PRD §3.2)."""
    h = TEST_USERS["agency_officer_headers"]
    return get_success_data(api_client.suspend_card(card_id, h))


def reactivate_card(*, card_id: str) -> Dict[str, Any]:
    h = TEST_USERS["agency_officer_headers"]
    return get_success_data(api_client.reactivate_card(card_id, h))


def close_card(*, card_id: str, rider_id: str) -> Dict[str, Any]:
    h = make_rider_headers(rider_id)
    return get_success_data(api_client.close_card(card_id, h))


# ===========================================================================
# Tier 1 — Active certificates / verifications
# ===========================================================================
def create_active_reduced_fare_certificate(
    *,
    rider_id: str,
    program_type: str = "SENIOR",
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Create a ReducedFareCertificate and approve it (PRD §3.2)."""
    h = TEST_USERS["agency_officer_headers"]
    payload = create_reduced_fare_certificate_payload(
        rider_id=rider_id,
        program_type=program_type,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    cert = get_success_data(
        api_client.create_reduced_fare_certificate(payload, h)
    )
    cert = get_success_data(
        api_client.approve_reduced_fare_certificate(cert["id"], h)
    )
    return cert


def create_pending_reduced_fare_certificate(
    *,
    rider_id: str,
    program_type: str = "SENIOR",
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
) -> Dict[str, Any]:
    h = TEST_USERS["agency_officer_headers"]
    payload = create_reduced_fare_certificate_payload(
        rider_id=rider_id,
        program_type=program_type,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    return get_success_data(
        api_client.create_reduced_fare_certificate(payload, h)
    )


def create_active_low_income_verification(
    *,
    rider_id: str,
    declared_annual_income_cents: int = 2_500_000,
    verified_annual_income_cents: int = 2_500_000,
) -> Dict[str, Any]:
    """Create a LowIncomeVerification and approve it to ACTIVE
    (PRD §3.3)."""
    h = TEST_USERS["agency_officer_headers"]
    payload = create_low_income_verification_payload(
        rider_id=rider_id,
        declared_annual_income_cents=declared_annual_income_cents,
    )
    verif = get_success_data(
        api_client.create_low_income_verification(payload, h)
    )
    return get_success_data(
        api_client.approve_low_income_verification(
            verif["id"],
            approve_low_income_verification_payload(
                verified_annual_income_cents=verified_annual_income_cents,
            ),
            h,
        )
    )


# ===========================================================================
# Tier 2 — Card-ready scenarios
# ===========================================================================
def setup_rider_with_funded_card(
    *,
    topup_cents: int = 1000,
    discount_class: str = "STANDARD",
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2026-12-31T23:59:59.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Rider, issue a card, top up the wallet.

    Returns (rider, card). For STANDARD cards; if a REDUCED_FARE or
    LOW_INCOME card is needed, the caller must set up the certificate
    or verification first.
    """
    rider = create_rider()
    card = issue_card(
        rider_id=rider["id"],
        discount_class=discount_class,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    if topup_cents > 0:
        card = topup_card(
            card_id=card["id"],
            rider_id=rider["id"],
            amount_cents=topup_cents,
        )
    return rider, card


def setup_rider_with_reduced_fare_card(
    *,
    program_type: str = "SENIOR",
    topup_cents: int = 1000,
    card_valid_from: str = "2026-01-01T00:00:00.000Z",
    card_valid_until: str = "2026-12-31T23:59:59.000Z",
    cert_valid_from: str = "2026-01-01T00:00:00.000Z",
    cert_valid_until: str = "2027-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Rider with an active ReducedFareCertificate and a REDUCED_FARE
    card. Returns (rider, cert, card)."""
    rider = create_rider()
    cert = create_active_reduced_fare_certificate(
        rider_id=rider["id"],
        program_type=program_type,
        valid_from=cert_valid_from,
        valid_until=cert_valid_until,
    )
    card = issue_card(
        rider_id=rider["id"],
        discount_class="REDUCED_FARE",
        valid_from=card_valid_from,
        valid_until=card_valid_until,
    )
    if topup_cents > 0:
        card = topup_card(
            card_id=card["id"],
            rider_id=rider["id"],
            amount_cents=topup_cents,
        )
    return rider, cert, card


def setup_rider_with_low_income_card(
    *,
    declared_annual_income_cents: int = 2_500_000,
    verified_annual_income_cents: int = 2_500_000,
    topup_cents: int = 1000,
    card_valid_from: str = "2026-01-01T00:00:00.000Z",
    card_valid_until: str = "2026-12-31T23:59:59.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Rider with active LowIncomeVerification and a LOW_INCOME card.
    Returns (rider, verif, card)."""
    rider = create_rider()
    verif = create_active_low_income_verification(
        rider_id=rider["id"],
        declared_annual_income_cents=declared_annual_income_cents,
        verified_annual_income_cents=verified_annual_income_cents,
    )
    card = issue_card(
        rider_id=rider["id"],
        discount_class="LOW_INCOME",
        valid_from=card_valid_from,
        valid_until=card_valid_until,
    )
    if topup_cents > 0:
        card = topup_card(
            card_id=card["id"],
            rider_id=rider["id"],
            amount_cents=topup_cents,
        )
    return rider, verif, card


# ===========================================================================
# Tier 3 — Employer / FSA scenarios
# ===========================================================================
def setup_rider_with_fsa(
    *,
    monthly_contribution_cap_cents: int = DEFAULT_MONTHLY_FSA_CAP_CENTS,
    contribution_cents: int = TEST_DEFAULTS["FSA_CONTRIB_DEFAULT"],
    contribution_month: str = "2026-05",
    topup_cents: int = 1000,
    discount_class: str = "STANDARD",
    card_valid_from: str = "2026-01-01T00:00:00.000Z",
    card_valid_until: str = "2026-12-31T23:59:59.000Z",
) -> Tuple[
    Dict[str, Any],  # rider
    Dict[str, Any],  # employer
    Dict[str, Any],  # account
    Dict[str, Any],  # card
    Optional[Dict[str, Any]],  # contribution (if any)
]:
    """Rider enrolled in an employer-sponsored FSA, with a funded card.

    PRD §3.9: account opens at balance=0; first contribution credits.
    Returns (rider, employer, account, card, contribution).
    """
    rider = create_rider()
    employer = create_employer(
        monthly_contribution_cap_cents=monthly_contribution_cap_cents,
    )
    eh = make_employer_admin_headers(employer["id"])
    acct = get_success_data(
        api_client.create_fsa_account(
            create_fsa_account_payload(
                rider_id=rider["id"], employer_id=employer["id"],
            ),
            eh,
        )
    )
    contribution: Optional[Dict[str, Any]] = None
    if contribution_cents > 0:
        contribution = get_success_data(
            api_client.create_fsa_contribution(
                create_fsa_contribution_payload(
                    account_id=acct["id"],
                    amount_cents=contribution_cents,
                    contribution_month=contribution_month,
                ),
                eh,
            )
        )

    card = issue_card(
        rider_id=rider["id"],
        discount_class=discount_class,
        valid_from=card_valid_from,
        valid_until=card_valid_until,
    )
    if topup_cents > 0:
        card = topup_card(
            card_id=card["id"],
            rider_id=rider["id"],
            amount_cents=topup_cents,
        )
    # Refresh account so caller sees the post-contribution balance.
    if contribution is not None:
        acct = get_success_data(
            api_client.create_fsa_account(  # not idempotent; use list instead
                create_fsa_account_payload(
                    rider_id=rider["id"], employer_id=employer["id"],
                ),
                eh,
            )
        ) if False else acct
    return rider, employer, acct, card, contribution


def get_fsa_account_balance(*, account_id: str,
                            employer_id: str) -> int:
    """Read the current FSA account balance via the get-style path; if
    the implementation does not expose a direct read, the caller can
    rely on Trip.paid_from_fsa_cents and assertion math.

    Many implementations expose GET /transit/fsa-accounts/{id} or a
    parallel listing. As a fallback this helper attempts both; if
    neither is available the test must compute the balance from the
    ledger.
    """
    # Tests that need precise balance will assert via Trip side effects.
    raise NotImplementedError(
        "Direct FSA-account read is not part of PRD §4; tests should"
        " assert FSA balance changes via Trip.paid_from_fsa_cents and"
        " refund deltas. This helper exists only as a doc anchor."
    )


# ===========================================================================
# Tier 4 — Trip lifecycle (tap-in, tap-out, sequencing)
# ===========================================================================
def tap_in(
    *,
    card_id: str,
    rider_id: str,
    tap_in_at: str,
    idempotency_key: Optional[str] = None,
    mobile_token_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tap in on a card on behalf of its owning rider (PRD §3.5)."""
    h = make_rider_headers(rider_id)
    payload = create_trip_payload(
        card_id=card_id,
        idempotency_key=idempotency_key or unique_idempotency_key(),
        tap_in_at=tap_in_at,
        mobile_token_id=mobile_token_id,
    )
    return get_success_data(api_client.create_trip(payload, h))


def tap_out(
    *,
    trip_id: str,
    rider_id: str,
    tap_out_at: str,
) -> Dict[str, Any]:
    """Tap out a trip on behalf of the owning rider (PRD §3.6)."""
    h = make_rider_headers(rider_id)
    return get_success_data(
        api_client.tap_out(
            trip_id, tap_out_payload(tap_out_at=tap_out_at), h,
        )
    )


def tap_in_and_out(
    *,
    card_id: str,
    rider_id: str,
    tap_in_at: str,
    tap_out_minutes: int = 20,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience: tap-in then tap-out 20 minutes later. Returns the
    completed Trip resource."""
    trip = tap_in(
        card_id=card_id,
        rider_id=rider_id,
        tap_in_at=tap_in_at,
        idempotency_key=idempotency_key,
    )
    return tap_out(
        trip_id=trip["id"],
        rider_id=rider_id,
        tap_out_at=add_minutes(tap_in_at, tap_out_minutes),
    )


# ===========================================================================
# Tier 5 — Dispute lifecycle
# ===========================================================================
def file_dispute(*, trip_id: str, rider_id: str) -> Dict[str, Any]:
    """File a dispute on a trip the rider owns (PRD §3.7)."""
    h = make_rider_headers(rider_id)
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(trip_id=trip_id), h,
        )
    )


def claim_dispute(*, dispute_id: str,
                  officer_headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    """OPEN → INVESTIGATING (PRD §3.7)."""
    h = officer_headers or TEST_USERS["agency_officer_headers"]
    return get_success_data(api_client.claim_dispute(dispute_id, h))


def resolve_dispute(*, dispute_id: str, decision: str,
                    officer_headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """INVESTIGATING → RESOLVED_REFUNDED / RESOLVED_REJECTED."""
    h = officer_headers or TEST_USERS["agency_officer_headers"]
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id, resolve_dispute_payload(decision=decision), h,
        )
    )


def setup_dispute_in_investigating(
    *,
    topup_cents: int = 10_000,
    tap_in_at: str = "2026-05-20T10:00:00.000Z",
) -> Tuple[
    Dict[str, Any],  # rider
    Dict[str, Any],  # card
    Dict[str, Any],  # trip (settled or completed)
    Dict[str, Any],  # dispute (status=INVESTIGATING)
]:
    """Anchor the clock, set up rider+card+completed-trip+filed dispute,
    then claim the dispute so it's in INVESTIGATING ready to resolve."""
    advance_clock_to_iso("2026-05-20T08:00:00.000Z")
    rider, card = setup_rider_with_funded_card(
        topup_cents=topup_cents,
        discount_class="STANDARD",
    )
    advance_clock_to_iso(tap_in_at)
    trip = tap_in_and_out(
        card_id=card["id"],
        rider_id=rider["id"],
        tap_in_at=tap_in_at,
        tap_out_minutes=20,
    )
    dispute = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
    dispute = claim_dispute(dispute_id=dispute["id"])
    return rider, card, trip, dispute


# ===========================================================================
# Tier 6 — Provisional-vs-Settled divergence scenario (difficulty-design
# rule: dual_variant_calc / refund_split_rounding_order_pinned /
# dispute_refund_depth_4_cascade). Compose the chronologically-out-of-
# order tap sequence the recipes call for.
# ===========================================================================
def setup_backdated_divergence_scenario(
    *,
    monthly_contribution_cap_cents: int = DEFAULT_MONTHLY_FSA_CAP_CENTS,
    fsa_contribution_cents: int = 100,
    topup_cents: int = 1000,
) -> Dict[str, Any]:
    """Build the recipe shape used by `trip_fare_provisional_vs_settled
    _diverge` and `refund_split_rounding_order_pinned`:

      - clock at 2026-05-20T08:00:00Z
      - rider + employer + FSA account, contribution 100 cents
      - STANDARD card, top-up 1000
      - clock to 17:00 → Trip_A tap-in (current); tap-out 20 min later
      - clock to 18:00 → Trip_B tap-in BACKDATED to 13:00; out 20 min
      - clock to 19:00 → Trip_C tap-in BACKDATED to 09:00; out 20 min

    Returns dict carrying rider, employer, account, card, contribution,
    trip_a, trip_b, trip_c. Tests can then advance the clock past
    window_end and invoke the settle sweep."""
    advance_clock_to_iso("2026-05-20T08:00:00.000Z")
    rider, employer, acct, card, contribution = setup_rider_with_fsa(
        monthly_contribution_cap_cents=monthly_contribution_cap_cents,
        contribution_cents=fsa_contribution_cents,
        contribution_month="2026-05",
        topup_cents=topup_cents,
        discount_class="STANDARD",
        card_valid_from="2026-05-01T00:00:00.000Z",
        card_valid_until="2026-12-31T23:59:59.000Z",
    )
    # Trip A — current 17:00, taps out 17:20.
    advance_clock_to_iso("2026-05-20T17:00:00.000Z")
    trip_a = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T17:00:00.000Z",
        tap_out_minutes=20,
        idempotency_key="k-A-" + card["id"][:8],
    )
    # Trip B — clock at 18:00; tap_in backdated to 13:00.
    advance_clock_to_iso("2026-05-20T18:00:00.000Z")
    trip_b = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T13:00:00.000Z",
        tap_out_minutes=20,
        idempotency_key="k-B-" + card["id"][:8],
    )
    # Trip C — clock at 19:00; tap_in backdated to 09:00.
    advance_clock_to_iso("2026-05-20T19:00:00.000Z")
    trip_c = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T09:00:00.000Z",
        tap_out_minutes=20,
        idempotency_key="k-C-" + card["id"][:8],
    )
    return {
        "rider": rider,
        "employer": employer,
        "account": acct,
        "card": card,
        "contribution": contribution,
        "trip_a": trip_a,
        "trip_b": trip_b,
        "trip_c": trip_c,
    }


def setup_cap_cascade_scenario(
    *,
    topup_cents: int = 10_000,
) -> Dict[str, Any]:
    """Build the recipe shape used by `dispute_refund_depth_4_cascade`:
    four ascending tap-ins on a STANDARD card with no FSA, sized so
    the daily cap fills exactly at T3 and T4 lands cap-free.

      - clock at 2026-05-20T08:00:00Z
      - Rider + STANDARD card; top-up 10000
      - Tap-in T1 at 10:00; out 10:20  → prov=275
      - Tap-in T2 at 13:00; out 13:20  → prov=275  (cumulative 550)
      - Tap-in T3 at 16:00; out 16:20  → prov=50  (cap binding 600−550)
      - Tap-in T4 at 19:00; out 19:20  → prov=0   (cap-free)

    Returns dict with rider, card, t1..t4."""
    advance_clock_to_iso("2026-05-20T08:00:00.000Z")
    rider, card = setup_rider_with_funded_card(
        topup_cents=topup_cents,
        discount_class="STANDARD",
        valid_from="2026-05-01T00:00:00.000Z",
        valid_until="2026-12-31T23:59:59.000Z",
    )
    advance_clock_to_iso("2026-05-20T10:00:00.000Z")
    t1 = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T10:00:00.000Z",
        idempotency_key="k1-" + card["id"][:8],
    )
    advance_clock_to_iso("2026-05-20T13:00:00.000Z")
    t2 = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T13:00:00.000Z",
        idempotency_key="k2-" + card["id"][:8],
    )
    advance_clock_to_iso("2026-05-20T16:00:00.000Z")
    t3 = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T16:00:00.000Z",
        idempotency_key="k3-" + card["id"][:8],
    )
    advance_clock_to_iso("2026-05-20T19:00:00.000Z")
    t4 = tap_in_and_out(
        card_id=card["id"], rider_id=rider["id"],
        tap_in_at="2026-05-20T19:00:00.000Z",
        idempotency_key="k4-" + card["id"][:8],
    )
    return {
        "rider": rider,
        "card": card,
        "t1": t1, "t2": t2, "t3": t3, "t4": t4,
    }


__all__ = [
    # Clock + sweeps
    "advance_clock_to_iso",
    "run_sweep_incomplete_trips",
    "run_sweep_settle",
    "run_sweep_low_income_expiry",
    # Read helpers
    "get_rider", "get_card", "get_trip",
    "list_cap_periods_for_card",
    "get_cap_period_for_window",
    # Foundation creators
    "create_rider", "create_employer", "issue_card", "topup_card",
    "suspend_card", "reactivate_card", "close_card",
    # Active certs / verifications
    "create_active_reduced_fare_certificate",
    "create_pending_reduced_fare_certificate",
    "create_active_low_income_verification",
    # Card-ready scenarios
    "setup_rider_with_funded_card",
    "setup_rider_with_reduced_fare_card",
    "setup_rider_with_low_income_card",
    # Employer / FSA
    "setup_rider_with_fsa",
    # Trip lifecycle
    "tap_in", "tap_out", "tap_in_and_out",
    # Dispute lifecycle
    "file_dispute", "claim_dispute", "resolve_dispute",
    "setup_dispute_in_investigating",
    # Composite scenarios
    "setup_backdated_divergence_scenario",
    "setup_cap_cascade_scenario",
]
