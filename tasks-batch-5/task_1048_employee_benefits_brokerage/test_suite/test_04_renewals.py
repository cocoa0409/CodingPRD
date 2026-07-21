"""Renewal negotiation cycle, rate settlement cascade, floor, OCC, and state gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_renewal_payload,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine — renewal negotiation cycle
# ===========================================================================
def _two_round_negotiation(api):
    """Active policy premium 1000000; OPEN renewal initial 1000000 (side CARRIER);
    broker counters 950000, then carrier counters 980000."""
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=1_000_000)
    renewal = fx.open_renewal(policy, initial_offer_premium_cents=1_000_000)
    validate_success(api.counter_renewal(
        renewal["id"], {"proposed_premium_cents": 950_000}, CONSULTANT))
    return validate_success(api.counter_renewal(
        renewal["id"], {"proposed_premium_cents": 980_000}, CARRIER))


def test_renewal_cycle_round_count_increments(api):
    """PRD §3.4: "From NEGOTIATING a further counter keeps the renewal in NEGOTIATING (this
    is the negotiation cycle, NEGOTIATING → NEGOTIATING), but only if the acting side is not
    the side that made the standing offer — a side may not counter its own current offer,
    and an attempt to do so is rejected with ERR_INVALID_STATE."

    Design: Difficulty/non_linear_state_machine/renewal_negotiation_cycle
    """
    result = _two_round_negotiation(api)
    assert result["status"] == "NEGOTIATING"
    assert result["round_count"] == 2


def test_renewal_cycle_proposing_side_flips_back_to_carrier(api):
    """PRD §3.4: "Every counter sets current_offer_premium_cents to the proposed premium,
    sets proposing_side to the acting side (BROKER when the actor is the consultant, CARRIER
    when the actor is the carrier representative), and increments round_count by one."

    Design: Difficulty/non_linear_state_machine/renewal_negotiation_cycle
    """
    result = _two_round_negotiation(api)
    assert result["proposing_side"] == "CARRIER"
    assert result["current_offer_premium_cents"] == 980_000


# ===========================================================================
# Difficulty / transitive_cascade — accept cascades to policy then client
# ===========================================================================
def test_renewal_accept_updates_policy_premium_and_status(api):
    """PRD §3.4: "On acceptance the renewal advances to AGREED, agreed_premium_cents is set
    to the current offer, the policy's monthly_premium_cents is set to that agreed premium,
    the policy's renewal_status is set to RENEWED, the policy's estimated_commission_cents is
    recomputed from the new premium (per §3.3), and the client's active_premium_total_cents
    is recomputed across its ACTIVE policies."

    Design: Difficulty/transitive_cascade/renewal_accept_cascade_policy_then_client
    """
    client, policy, renewal = fx.setup_open_renewal(monthly_premium_cents=1_000_000,
                                                    initial_offer_premium_cents=900_000)
    settled = validate_success(api.settle_renewal(renewal["id"], {"action": "ACCEPT"}, CONSULTANT))
    assert settled["status"] == "AGREED"
    fresh_policy = validate_success(api.get_policy(policy["id"], CONSULTANT))
    assert fresh_policy["monthly_premium_cents"] == 900_000
    assert fresh_policy["renewal_status"] == "RENEWED"


def test_renewal_accept_recomputes_client_active_premium(api):
    """PRD §2.8: "settling a renewal as agreed recomputes the total across the client's
    ACTIVE policies (because the agreed policy's premium changes)."

    Design: Difficulty/transitive_cascade/renewal_accept_cascade_policy_then_client
    """
    client, policy, renewal = fx.setup_open_renewal(monthly_premium_cents=1_000_000,
                                                    initial_offer_premium_cents=900_000)
    validate_success(api.settle_renewal(renewal["id"], {"action": "ACCEPT"}, CONSULTANT))
    fresh_client = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh_client["active_premium_total_cents"] == 900_000


# ===========================================================================
# Difficulty / cross_entity_state_dependency — renewal requires ACTIVE policy
# ===========================================================================
def test_open_renewal_on_bound_policy_invalid_state(api):
    """PRD §3.4: "Opening a renewal requires the referenced policy to be in ACTIVE lifecycle
    (otherwise ERR_INVALID_STATE) and requires expected_policy_version to match the policy's
    current version (otherwise ERR_STALE_POLICY_VERSION, as described in §2.6)."

    Design: Difficulty/cross_entity_state_dependency/renewal_requires_active_policy
    """
    client = fx.create_client(legal_name="Nu Co")
    policy = fx.bind_policy(client["id"], monthly_premium_cents=1_000_000)
    resp = api.create_renewal(
        create_renewal_payload(policy["id"], policy["version"],
                               initial_offer_premium_cents=900_000), CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_rejected_renewal_leaves_bound_policy_untouched(api):
    """PRD §3.4: "Opening a renewal requires the referenced policy to be in ACTIVE lifecycle
    (otherwise ERR_INVALID_STATE) and requires expected_policy_version to match the policy's
    current version (otherwise ERR_STALE_POLICY_VERSION, as described in §2.6)."

    Design: Difficulty/cross_entity_state_dependency/renewal_requires_active_policy
    """
    client = fx.create_client(legal_name="Nu Co")
    policy = fx.bind_policy(client["id"], monthly_premium_cents=1_000_000)
    api.create_renewal(
        create_renewal_payload(policy["id"], policy["version"],
                               initial_offer_premium_cents=900_000), CONSULTANT)
    fresh = validate_success(api.get_policy(policy["id"], CONSULTANT))
    assert fresh["lifecycle_status"] == "BOUND"
    assert fresh["renewal_status"] == "NONE"


# ===========================================================================
# Difficulty / priority_pair_validation_conflict — state beats fiscal floor
# ===========================================================================
def test_accept_declined_renewal_below_floor_state_error_wins(api):
    """PRD §2.7: "When more than one validation could fire on a single request, checks are
    evaluated in the following fixed priority order, and the first failing check determines
    the error returned:"
    PRD §2.7: "State — the target resource is in a state from which the requested transition
    is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_renewal_settle
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=1_000_000)
    renewal = fx.open_renewal(policy, initial_offer_premium_cents=100_000)
    validate_success(api.settle_renewal(renewal["id"], {"action": "DECLINE"}, CONSULTANT))
    resp = api.settle_renewal(renewal["id"], {"action": "ACCEPT"}, CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_declined_renewal_stays_declined_after_rejected_accept(api):
    """PRD §2.7: "Renewal floor — a renewal acceptance's current offer is at or above the
    renewal floor; otherwise ERR_PREMIUM_BELOW_FLOOR (409)."
    PRD §2.7: "State — the target resource is in a state from which the requested transition
    is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_renewal_settle
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=1_000_000)
    renewal = fx.open_renewal(policy, initial_offer_premium_cents=100_000)
    validate_success(api.settle_renewal(renewal["id"], {"action": "DECLINE"}, CONSULTANT))
    api.settle_renewal(renewal["id"], {"action": "ACCEPT"}, CONSULTANT)
    fresh = validate_success(api.get_renewal(renewal["id"], CONSULTANT))
    assert fresh["status"] == "DECLINED"


# ===========================================================================
# Corner / state_machines — decline leaves premium unchanged
# ===========================================================================
def test_renewal_decline_leaves_policy_premium_unchanged(api):
    """PRD §3.4: "A DECLINE advances the renewal to DECLINED and resets the policy's
    renewal_status to NONE, leaving the policy's monthly_premium_cents unchanged so no
    premium drift occurs."

    Design: Corner/state_machines/renewal_decline_leaves_policy_premium_unchanged
    """
    client, policy, renewal = fx.setup_open_renewal(monthly_premium_cents=1_000_000,
                                                    initial_offer_premium_cents=900_000)
    settled = validate_success(api.settle_renewal(renewal["id"], {"action": "DECLINE"}, CONSULTANT))
    assert settled["status"] == "DECLINED"
    fresh = validate_success(api.get_policy(policy["id"], CONSULTANT))
    assert fresh["monthly_premium_cents"] == 1_000_000
    assert fresh["renewal_status"] == "NONE"


# ===========================================================================
# Corner / validations — accept below floor (fiscal check fires alone)
# ===========================================================================
def test_renewal_accept_below_floor_rejected(api):
    """PRD §3.4: "An ACCEPT is permitted only when the current offer is at or above the
    renewal floor, which is one-half of the policy's original_premium_cents (the
    renewal-floor percentage is 0.50), rounded half-up to whole cents; when the renewal is
    still OPEN the current offer equals the initial offer. An acceptance below that floor is
    rejected with ERR_PREMIUM_BELOW_FLOOR."

    Design: Corner/validations/renewal_accept_below_floor_rejected
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=1_000_000)
    renewal = fx.open_renewal(policy, initial_offer_premium_cents=400_000)
    resp = api.settle_renewal(renewal["id"], {"action": "ACCEPT"}, CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_PREMIUM_BELOW_FLOOR.value)


# ===========================================================================
# Corner / cross_cutting — OCC stale policy version on renewal create
# ===========================================================================
def test_renewal_create_stale_policy_version_rejected(api):
    """PRD §2.6: "If expected_policy_version does not equal the policy's current version —
    because another writer (for example an activation, or an earlier renewal that already
    moved the policy on) has advanced the policy's version since the caller last read it —
    the request is rejected with ERR_STALE_POLICY_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/renewal_create_stale_policy_version_rejected
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=1_000_000)
    pv = policy["version"]
    # First renewal create supersedes and advances the policy version.
    validate_success(api.create_renewal(
        create_renewal_payload(policy["id"], pv, initial_offer_premium_cents=900_000),
        CONSULTANT), 201)
    resp = api.create_renewal(
        create_renewal_payload(policy["id"], pv, initial_offer_premium_cents=880_000),
        CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value)
