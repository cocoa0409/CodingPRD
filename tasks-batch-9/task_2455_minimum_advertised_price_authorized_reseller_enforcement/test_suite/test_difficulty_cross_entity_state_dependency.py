"""Operations whose legality is decided by the state of a row the request never
names. Activation reads the referenced policy; a downstream shipment reads the
target reseller's supply axis.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import ApiErrorId, BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import assert_same_instant
from test_helpers.factories import policy_withdraw_payload, ship_downstream_payload
from test_helpers.fixtures import (
    create_active_agreement,
    create_countersigned_agreement,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    hold_supply,
    pin_clock,
    read_agreement,
    read_policy,
    read_reseller,
    read_serial_unit,
    release_supply,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
WITHDRAWN_REASON = "Distribution programme paused for antitrust re-review."


# --------------------------------------------------------------------------- #
# Instance 1 — activation is gated by the state of the referenced policy
# --------------------------------------------------------------------------- #
def _setup_countersigned_under_withdrawn_policy():
    """A countersigned agreement whose referenced policy has since been withdrawn."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    reseller = create_reseller(primary_channel="PHYSICAL_RETAIL")
    agreement = create_countersigned_agreement(
        reseller["id"], policy["id"], permitted_channels=["PHYSICAL_RETAIL"]
    )
    policy = validate_success(
        api_client.withdraw_policy(
            policy["id"],
            policy_withdraw_payload(withdrawn_reason=WITHDRAWN_REASON),
            COUNSEL_HEADERS,
        )
    )
    return {"policy": policy, "reseller": reseller, "agreement": agreement}


def test_activation_is_refused_because_the_referenced_policy_is_no_longer_published():
    """The agreement itself is in a perfectly legal state; the policy is not.

    PRD: "Activation is a `BrandChannelManager` act moving the agreement
    `COUNTERSIGNED → ACTIVE`. It requires the agreement to be `COUNTERSIGNED`, requires
    the referenced policy to still be in status `PUBLISHED`, and — when that policy has
    `non_negotiation_ack_required` set to true — requires `non_negotiation_acknowledged`
    on the agreement to be true, else the activation is rejected with
    `ERR_NON_NEGOTIATION_ACK_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_by_withdrawn_policy_state
    """
    world = _setup_countersigned_under_withdrawn_policy()
    assert world["agreement"]["status"] == "COUNTERSIGNED"
    assert world["agreement"]["non_negotiation_acknowledged"] is True

    validate_error(
        api_client.activate_agreement(world["agreement"]["id"], BCM_HEADERS),
        ApiErrorId.ERR_POLICY_NOT_PUBLISHED.value,
    )


def test_the_refused_activation_leaves_the_agreement_exactly_where_it_stood():
    """No partial write: the countersignature stands and activated_at stays null.

    PRD: "Activation stamps `activated_at` with the current clock and advances the
    agreement's `version`, and it moves the reseller on both axes at once:
    `authorization_status` to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason` to
    `NONE`, with the reseller's `version` advanced."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_by_withdrawn_policy_state
    """
    world = _setup_countersigned_under_withdrawn_policy()
    version_before = world["agreement"]["version"]
    api_client.activate_agreement(world["agreement"]["id"], BCM_HEADERS)

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "COUNTERSIGNED"
    assert agreement["activated_at"] is None
    assert agreement["closed_reason"] is None
    assert agreement["version"] == version_before

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "PENDING_AGREEMENT"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"


def test_withdrawal_closed_the_gate_without_disturbing_the_rows_that_cite_it():
    """The policy sits in a terminal state and the citation is still intact.

    PRD: "Withdrawal deliberately cascades to nothing: products keep their governing
    policy reference and open violations keep their citation."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_blocked_by_withdrawn_policy_state
    """
    world = _setup_countersigned_under_withdrawn_policy()

    policy = read_policy(world["policy"]["id"])
    assert policy["status"] == "WITHDRAWN"
    assert policy["withdrawn_reason"] == WITHDRAWN_REASON

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["policy_id"] == world["policy"]["id"]


# --------------------------------------------------------------------------- #
# Instance 2 — a downstream shipment is gated by the reseller's supply axis
# --------------------------------------------------------------------------- #
def _setup_unit_ready_to_ship():
    """A registered unit, its distributor, and an authorized reseller to ship it to."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"], serialization_enabled=True)
    distributor = create_distributor(legal_name="West Distribution")
    reseller = create_reseller(
        primary_channel="OWN_WEBSITE", sourcing_distributor_id=distributor["id"]
    )
    agreement = create_active_agreement(
        reseller["id"], policy["id"], permitted_channels=["OWN_WEBSITE"]
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-50", lot_code="LOT-F"
    )
    return {
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "agreement": agreement,
        "unit": unit,
    }


def test_a_freshly_registered_unit_starts_in_the_distributors_custody():
    """Registration lands the unit on the distributor with no downstream hop yet.

    PRD: "The unit is created in custody state `SHIPPED_TO_DISTRIBUTOR` with
    `downstream_reseller_id`, `shipped_downstream_at` and `traced_at` all null, and the
    named distributor's `shipped_units_total` — which counts every unit whose
    `shipped_distributor_id` is that distributor, in any custody state — is increased
    accordingly."

    Design: Difficulty/cross_entity_state_dependency/serial_ship_downstream_gated_by_reseller_supply_axis
    """
    world = _setup_unit_ready_to_ship()
    unit = world["unit"]
    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unit["downstream_reseller_id"] is None
    assert unit["shipped_downstream_at"] is None
    assert unit["traced_at"] is None
    assert unit["version"] == 1


def test_a_supply_hold_on_the_target_reseller_blocks_the_downstream_shipment():
    """The unit and the acting distributor are both fine; the third row is not.

    PRD: "Three preconditions apply: the unit must be in `SHIPPED_TO_DISTRIBUTOR`, the
    acting distributor's `X-User-ID` must equal the unit's `shipped_distributor_id`, and
    the target reseller's `supply_status` must be `OPEN` — a distributor may not ship to
    a reseller the brand has put on hold or cut off, which is precisely the mechanism a
    supply hold is meant to be."

    Design: Difficulty/cross_entity_state_dependency/serial_ship_downstream_gated_by_reseller_supply_axis
    """
    world = _setup_unit_ready_to_ship()
    held = hold_supply(world["reseller"]["id"])
    assert held["supply_status"] == "HOLD"
    assert held["authorization_status"] == "AUTHORIZED"

    # The refusal is a transition-legality failure; the PRD leaves the brand free to
    # report it as either of the two codes it declares for a blocked supply axis.
    validate_error_is_one_of(
        api_client.ship_downstream(
            world["unit"]["id"],
            ship_downstream_payload(world["reseller"]["id"]),
            make_distributor_headers(world["distributor"]["id"]),
        ),
        [
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION.value,
        ],
    )

    unit = read_serial_unit(world["unit"]["id"])
    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unit["downstream_reseller_id"] is None
    assert unit["version"] == 1


def test_releasing_the_hold_lets_the_very_same_shipment_through():
    """Only the reseller's supply axis changed between the refusal and the success.

    PRD: "Supplying a `downstream_reseller_id` moves a unit `SHIPPED_TO_DISTRIBUTOR →
    SHIPPED_TO_RESELLER`, setting `downstream_reseller_id` and stamping
    `shipped_downstream_at` with the current clock, and advancing the unit's `version`."

    Design: Difficulty/cross_entity_state_dependency/serial_ship_downstream_gated_by_reseller_supply_axis
    """
    world = _setup_unit_ready_to_ship()
    hold_supply(world["reseller"]["id"])
    api_client.ship_downstream(
        world["unit"]["id"],
        ship_downstream_payload(world["reseller"]["id"]),
        make_distributor_headers(world["distributor"]["id"]),
    )
    released = release_supply(world["reseller"]["id"])
    assert released["supply_status"] == "OPEN"
    assert released["authorization_status"] == "AUTHORIZED"

    shipped = ship_unit_downstream(
        world["unit"]["id"], world["distributor"]["id"], world["reseller"]["id"]
    )
    assert shipped["status"] == "SHIPPED_TO_RESELLER"
    assert shipped["downstream_reseller_id"] == world["reseller"]["id"]
    assert_same_instant(shipped["shipped_downstream_at"], CLOCK_AUG_01, "shipped_downstream_at")
    assert shipped["version"] == 2

    # The shipment is a unit-level fact; the reseller's own axes are unchanged by it.
    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
