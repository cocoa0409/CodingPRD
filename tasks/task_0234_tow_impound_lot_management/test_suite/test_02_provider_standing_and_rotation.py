"""Provider standing variants, rotation dispatch / decline cascade, concurrent-offer
capacity, and optimistic-concurrency on the lot version.

Covers difficulty rules: dual_variant_calc (standing), transitive_cascade (decline),
resource_temporal_overlap (capacity), cross_entity_state_dependency (suspended provider);
and corner state_machines / rbac / cross_cutting OCC instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_tow_provider_headers,
    set_clock,
    create_lot,
    create_provider,
    setup_lot_with_providers,
    setup_offered_assignment,
    dispatch_offer,
)

OP = TEST_USERS["lot_operator_headers"]


# ─── dual_variant_calc / provider_standing_raw_vs_trailing_diverge ────────────
def test_raw_and_trailing_standing_diverge_for_same_history(api):
    """PRD §3.7: "raw_standing_pct, is the all-time instantaneous variant: it is the
    provider's offers_accepted_count divided by its offers_received_count, multiplied
    by 100 and rounded half-up to two decimal places"
    PRD §3.7: "effective_standing_pct ... considers only the most recent
    trailing_window_size rotation assignments offered to the provider ... computed as
    the count accepted within that window divided by the count offered within that
    window, multiplied by 100 and rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/provider_standing_raw_vs_trailing_diverge
    """
    # Single provider, trailing_window_size=2, on a high-capacity lot so three
    # dispatches all land on this one provider. Accept only offer #1; #2 and #3
    # remain OFFERED. All-time 1/3 -> raw 33.33; trailing last-2 (both unaccepted) -> 0.00.
    lot = create_lot(max_provider_concurrent_offers=5)
    p = get_success_data(api.create_tow_provider(
        {"company_name": "PW", "license_number": "L-PW", "rotation_rank": 1,
         "trailing_window_size": 2}, OP))
    v = lot["version"]
    ra1, v = dispatch_offer(lot["id"], v)
    get_success_data(api.accept_rotation(ra1["id"], make_tow_provider_headers(p["id"])))
    ra2, v = dispatch_offer(lot["id"], v)
    ra3, v = dispatch_offer(lot["id"], v)

    fetched = validate_success(api.get_tow_provider(p["id"], OP), 200)
    assert fetched["raw_standing_pct"] == 33.33, "all-time 1 accepted / 3 received"
    assert fetched["effective_standing_pct"] == 0.00, "trailing last-2 (both unaccepted)"
    assert fetched["raw_standing_pct"] != fetched["effective_standing_pct"]


def test_raw_standing_is_100_when_no_offers_received(api):
    """PRD §3.7: "when offers_received_count is 0 the raw standing is defined as 100.00."

    Design: Difficulty/dual_variant_calc/provider_standing_raw_vs_trailing_diverge
    """
    create_lot()
    p = create_provider(company_name="Fresh", rotation_rank=1)
    fetched = validate_success(api.get_tow_provider(p["id"], OP), 200)
    assert fetched["offers_received_count"] == 0
    assert fetched["raw_standing_pct"] == 100.00


# ─── transitive_cascade / decline_cascades_reoffer_and_counter_bump ───────────
def test_decline_reoffers_to_next_provider_and_bumps_counter(api):
    """PRD §3.2: "second, the server advances the lot's rotation_cursor and dispatches
    a fresh RotationAssignment in OFFERED status to the next eligible provider under
    the same selector policy, and sets this declined row's superseded_by_id to the new
    assignment's id; third, the next provider's offers_received_count is incremented by 1
    and that provider's standing is recomputed."

    Design: Difficulty/transitive_cascade/decline_cascades_reoffer_and_counter_bump
    """
    lot, providers, ra1, v = setup_offered_assignment(
        num_providers=2, lot_overrides={"max_provider_concurrent_offers": 5})
    p1, p2 = providers
    assert ra1["provider_id"] == p1["id"], "rank-1 offered first"

    res = api.decline_rotation(ra1["id"], make_tow_provider_headers(p1["id"]))
    declined = validate_success(res, 200)
    assert declined["status"] == "DECLINED"
    assert declined["superseded_by_id"] is not None, "re-offer back-pointer set"

    p2_after = validate_success(api.get_tow_provider(p2["id"], OP), 200)
    assert p2_after["offers_received_count"] == 1, "next provider's counter bumped"


def test_decline_sets_new_offer_to_next_provider(api):
    """PRD §3.2: "A decline triggers a three-hop cascade: first this assignment moves
    OFFERED → DECLINED; second, the server advances the lot's rotation_cursor and
    dispatches a fresh RotationAssignment in OFFERED status to the next eligible provider"

    Design: Difficulty/transitive_cascade/decline_cascades_reoffer_and_counter_bump
    """
    lot, providers, ra1, v = setup_offered_assignment(
        num_providers=2, lot_overrides={"max_provider_concurrent_offers": 5})
    p1, p2 = providers
    res = api.decline_rotation(ra1["id"], make_tow_provider_headers(p1["id"]))
    declined = validate_success(res, 200)
    new_offer = validate_success(api.get_rotation_assignment(declined["superseded_by_id"], OP), 200)
    assert new_offer["status"] == "OFFERED"
    assert new_offer["provider_id"] == p2["id"], "re-offer goes to rank-2"


# ─── resource_temporal_overlap / provider_concurrent_offer_capacity_exceeded ──
def test_dispatch_with_provider_at_capacity_returns_no_eligible(api):
    """PRD §3.2: "The candidate set is the lot's ACTIVE providers whose count of
    currently OFFERED rotation assignments is strictly fewer than the lot's
    max_provider_concurrent_offers."
    PRD §3.2: "If the candidate set is empty — every active provider is already at its
    concurrent-offer cap, or there are no active providers — no offer is minted and the
    request is rejected with ERR_NO_ELIGIBLE_PROVIDER."

    Design: Difficulty/resource_temporal_overlap/provider_concurrent_offer_capacity_exceeded
    """
    lot, providers, ra1, v = setup_offered_assignment(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 1})
    res = api.dispatch_rotation(lot["id"], {"expected_lot_version": v}, OP)
    validate_error(res, "ERR_NO_ELIGIBLE_PROVIDER", expected_status=409)


def test_dispatch_with_no_active_providers_returns_no_eligible(api):
    """PRD §3.2: "If the candidate set is empty — every active provider is already at
    its concurrent-offer cap, or there are no active providers — no offer is minted and
    the request is rejected with ERR_NO_ELIGIBLE_PROVIDER."

    Design: Difficulty/resource_temporal_overlap/provider_concurrent_offer_capacity_exceeded
    """
    lot = create_lot(max_provider_concurrent_offers=1)
    res = api.dispatch_rotation(lot["id"], {"expected_lot_version": lot["version"]}, OP)
    validate_error(res, "ERR_NO_ELIGIBLE_PROVIDER", expected_status=409)


# ─── cross_entity_state_dependency / rotation_accept_blocked_by_suspended_provider ─
def test_accept_blocked_when_provider_suspended(api):
    """PRD §3.2: "and the provider must be ACTIVE, or the request is rejected with
    ERR_PROVIDER_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/rotation_accept_blocked_by_suspended_provider
    """
    lot, providers, ra, v = setup_offered_assignment(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 5})
    p = providers[0]
    get_success_data(api.suspend_provider(p["id"], OP))
    res = api.accept_rotation(ra["id"], make_tow_provider_headers(p["id"]))
    validate_error(res, "ERR_PROVIDER_NOT_ACTIVE", expected_status=409)


def test_accept_succeeds_while_provider_active(api):
    """PRD §3.2: "A successful accept moves the assignment OFFERED → ACCEPTED,
    increments the provider's offers_accepted_count by 1, and recomputes the provider's
    standing variants."

    Design: Difficulty/cross_entity_state_dependency/rotation_accept_blocked_by_suspended_provider
    """
    lot, providers, ra, v = setup_offered_assignment(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 5})
    p = providers[0]
    res = api.accept_rotation(ra["id"], make_tow_provider_headers(p["id"]))
    accepted = validate_success(res, 200)
    assert accepted["status"] == "ACCEPTED"
    p_after = validate_success(api.get_tow_provider(p["id"], OP), 200)
    assert p_after["offers_accepted_count"] == 1


# ─── Corner: state_machines / rotation_expire_before_ttl_rejected ─────────────
def test_expire_before_ttl_rejected(api):
    """PRD §3.2: "Expiry is allowed only from OFFERED (otherwise ERR_INVALID_STATE) and
    only when the current clock is strictly past expires_at; calling it before that
    instant is rejected with ERR_OFFER_NOT_EXPIRED."

    Design: Corner/state_machines/rotation_expire_before_ttl_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    lot, providers, ra, v = setup_offered_assignment(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 5})
    # clock still at offer instant, not past expires_at
    res = api.expire_rotation(ra["id"], OP)
    validate_error(res, "ERR_OFFER_NOT_EXPIRED", expected_status=409)


# ─── Corner: state_machines / rotation_accept_after_ttl_returns_offer_expired ─
def test_accept_after_ttl_returns_offer_expired(api):
    """PRD §3.2: "the current clock must be at or before expires_at, or the request is
    rejected with ERR_OFFER_EXPIRED"

    Design: Corner/state_machines/rotation_accept_after_ttl_returns_offer_expired
    """
    set_clock("2026-01-01T00:00:00Z")
    lot, providers, ra, v = setup_offered_assignment(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 5},
        offer_ttl_minutes=30)
    p = providers[0]
    set_clock("2026-01-01T01:00:00Z")  # 1h later, past 30-min TTL
    res = api.accept_rotation(ra["id"], make_tow_provider_headers(p["id"]))
    validate_error(res, "ERR_OFFER_EXPIRED", expected_status=409)


# ─── Corner: rbac / provider_cannot_accept_others_offer ───────────────────────
def test_provider_cannot_accept_offer_dispatched_to_another(api):
    """PRD §2.1: "only the provider an offer was dispatched to may accept or decline
    it: the acting X-User-ID must equal that assignment's provider_id, and a mismatch
    is rejected with ERR_FORBIDDEN_FOR_ROLE."

    Design: Corner/rbac/provider_cannot_accept_others_offer
    """
    lot, providers, ra1, v = setup_offered_assignment(
        num_providers=2, lot_overrides={"max_provider_concurrent_offers": 5})
    p1, p2 = providers
    assert ra1["provider_id"] == p1["id"]
    res = api.accept_rotation(ra1["id"], make_tow_provider_headers(p2["id"]))
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


# ─── Corner: cross_cutting / occ_dispatch_stale_lot_version ───────────────────
def test_dispatch_with_stale_lot_version_rejected(api):
    """PRD §2.7: "If expected_lot_version does not equal the lot's current version —
    because another dispatch has already advanced the lot's rotation_cursor and minted
    the next offer since the client last read the lot — the request is rejected with
    ERR_STALE_LOT_VERSION at HTTP status 412"

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_stale_lot_version
    """
    lot, providers = setup_lot_with_providers(
        num_providers=2, lot_overrides={"max_provider_concurrent_offers": 5})
    stale_version = lot["version"]
    # First dispatch consumes the version and advances it.
    get_success_data(api.dispatch_rotation(lot["id"], {"expected_lot_version": stale_version}, OP))
    res = api.dispatch_rotation(lot["id"], {"expected_lot_version": stale_version}, OP)
    validate_error(res, "ERR_STALE_LOT_VERSION", expected_status=412)


# ─── Corner: cross_cutting / occ_correct_version_succeeds_and_increments ──────
def test_dispatch_with_correct_version_increments_lot_version(api):
    """PRD §2.7: "A dispatch request must carry expected_lot_version as a required
    field, holding the client's last-observed version of the target ImpoundLot."
    PRD §3.2: "A successful dispatch selects the next eligible provider, mints a new
    RotationAssignment in status OFFERED ... as well as incrementing the lot's version by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    lot, providers = setup_lot_with_providers(
        num_providers=1, lot_overrides={"max_provider_concurrent_offers": 5})
    res = api.dispatch_rotation(lot["id"], {"expected_lot_version": lot["version"]}, OP)
    ra = validate_success(res, 201)
    assert ra["status"] == "OFFERED"
    lot_after = validate_success(api.get_impound_lot(lot["id"], OP), 200)
    assert lot_after["version"] == 2, "version 1 -> 2 after one dispatch"
