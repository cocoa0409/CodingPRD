"""Redemption creation & fulfilment, OCC stale-version guard, priority conflicts."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_member_headers,
    ApiErrorId,
    create_member, seed_balance,
    setup_suspended_member, setup_two_members_and_offer,
)


# =============================================================================
# OCC — corner instance
# =============================================================================

def test_stale_expected_member_version_rejected(api):
    """PRD §2.8: "A create-redemption request must carry expected_member_version
    as a non-optional integer field equal to the Member.version the client
    last observed. If that value does not equal the member's current
    Member.version at the moment the create is processed, the request is
    rejected with ERR_STALE_MEMBER_VERSION (HTTP 412) — the balance the
    client is spending against is no longer authoritative, and the client
    must re-read the member and retry with the current version."

    Design: Corner/cross_cutting_complexity_layers/occ_redemption_stale_version_412
    """
    m = create_member(email_prefix="occ")
    seed_balance(m["id"], 300)
    v_pre = get_success_data(api.get_member(
        m["id"], headers=make_member_headers(m["id"]),
    ))["version"]
    seed_balance(m["id"], 15, memo="bump")  # advances Member.version
    resp = api.create_redemption(
        {"member_id": m["id"], "reward_code": "FARMERS_MARKET_15",
         "expected_member_version": v_pre},
        headers=make_member_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION)


def test_current_expected_member_version_accepted(api):
    """PRD §2.8: "This is a stale-version rejection, not a race between
    simultaneous writers: the check compares the client's captured version
    to the server's current version, without regard to how many other
    writers arrived in between."

    Design: Corner/cross_cutting_complexity_layers/occ_redemption_correct_version_succeeds
    """
    m = create_member(email_prefix="occ-ok")
    seed_balance(m["id"], 300)
    v = get_success_data(api.get_member(
        m["id"], headers=make_member_headers(m["id"]),
    ))["version"]
    resp = api.create_redemption(
        {"member_id": m["id"], "reward_code": "FARMERS_MARKET_15",
         "expected_member_version": v},
        headers=make_member_headers(m["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REQUESTED"


# =============================================================================
# Corner — self-verify eligibility
# =============================================================================

def test_self_verify_rejected_with_verifier_ineligible(api):
    """PRD §2.7: "Verification is a peer act, not a self-attestation: only a
    Member whose own trust_tier is TRUSTED or ANCHOR may verify, reject, or
    request a revision on another member's credential, and a member may
    never verify a credential whose subject is themselves. A verifier who
    fails either gate is rejected with ERR_VERIFIER_INELIGIBLE."

    Design: Corner/errors/err_verifier_ineligible_self_verify
    """
    s = create_member(email_prefix="sv")
    c = get_success_data(api.create_credential(
        {"subject_member_id": s["id"], "verifier_member_id": s["id"],
         "credential_type": "ID_CHECK", "evidence_url": "https://ev/1"},
        headers=make_member_headers(s["id"]),
    ))
    resp = api.verify_credential(c["id"], headers=make_member_headers(s["id"]))
    validate_error(resp, ApiErrorId.ERR_VERIFIER_INELIGIBLE)


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================

def test_suspended_member_beats_insufficient_balance_on_exchange_create(api):
    """PRD §2.11: "then owner-match and requester-provider distinctness, then
    the suspension gate, then the fiscal balance gate — where the
    requester's forward_looking_balance_minutes must be at least the
    exchange's committed_minutes on exchange creation and at least the
    redemption's minutes_cost on redemption creation."

    Design: Difficulty/priority_pair_validation_conflict/suspended_and_insufficient_returns_suspended
    """
    ctx = setup_suspended_member()
    # This member is suspended (3 NO_SHOW strikes) AND has 0 balance.
    # Clock advanced to 2026-03-05T10:30; schedule the target for later.
    provider = create_member(email_prefix="prov-sp")
    offer = get_success_data(api.create_skill_offer(
        {"member_id": provider["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": 60},
        headers=make_member_headers(provider["id"]),
    ))
    req = get_success_data(api.create_skill_request(
        {"member_id": ctx["member"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-06T09:00:00Z",
         "latest_start_utc": "2026-03-06T18:00:00Z"},
        headers=make_member_headers(ctx["member"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": offer["id"], "request_id": req["id"],
         "scheduled_start_utc": "2026-03-06T09:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_stale_version_beats_ownership_violation_on_redemption(api):
    """PRD §2.11: "then whether the target resource is in a state that permits
    the operation (per §3), then the redemption OCC gate (§2.8), then
    owner-match and requester-provider distinctness"

    Design: Difficulty/priority_pair_validation_conflict/stale_version_and_ownership_returns_stale
    """
    m1 = create_member(email_prefix="sv1")
    m2 = create_member(email_prefix="sv2")
    seed_balance(m1["id"], 600, memo="seed m1")
    v_pre = get_success_data(api.get_member(
        m1["id"], headers=make_member_headers(m1["id"]),
    ))["version"]
    seed_balance(m1["id"], 15, memo="bump m1 version")
    # Caller acts as m1 but posts member_id=m2 (ownership violation) AND
    # expected_member_version=v_pre (stale).
    resp = api.create_redemption(
        {"member_id": m2["id"], "reward_code": "FARMERS_MARKET_15",
         "expected_member_version": v_pre},
        headers=make_member_headers(m1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION)
