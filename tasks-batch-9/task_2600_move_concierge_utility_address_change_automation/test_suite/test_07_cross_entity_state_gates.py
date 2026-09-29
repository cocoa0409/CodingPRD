"""Gates whose decision is read from a row other than the one being written.

Three independent cross-entity dependencies live here.  A postal filing is
refused because of the state of a *consent record* on the resident, and the
scope that blocks it is the utility scope rather than the filing scope.  An
order activation is refused because of the state of a *credit-check handoff*
reached through the order's credit dimension.  A referral placement is refused
because of a boolean on the *resident* row, which no placement field mirrors.

Every precondition is built through declared endpoints, the store starts
empty for each test, and the logical clock is pinned explicitly wherever a
temporal rule participates.
"""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_version_bumped,
    get_success_data,
)
from test_helpers.test_users import (
    MOVE_OPS_AGENT_USER_ID,
    make_provider_agent_headers,
)
from test_helpers.types import (
    BlockedReason,
    ConsentGate,
    ConsentScope,
    ConsentState,
    CreditStatus,
    FilingStatus,
    MoveLifecycleStatus,
    PlacementStatus,
    ProvisionStatus,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Local derivations — a conserved quantity is measured from listings, never
# read from a convenience field.
# ---------------------------------------------------------------------------
def open_deposit_liability_cents(api: ApiClient, move_id: str, headers: Dict[str, str]) -> int:
    """Sum `deposit_amount_cents` over the move's orders still in DEPOSIT_DUE."""
    orders = get_success_data(api.list_utility_orders(headers, move_id=move_id, limit=100))
    return sum(
        order["deposit_amount_cents"]
        for order in orders
        if order["credit_status"] == CreditStatus.DEPOSIT_DUE.value
    )


# ---------------------------------------------------------------------------
# A revoked UTILITY_SETUP consent gates postal filing submission
# ---------------------------------------------------------------------------
def test_01_revoked_utility_consent_blocks_postal_filing_submission(
    api, ops_headers, compliance_headers
):
    """A withdrawn utility consent stops a filing that never needed that scope.

    The gate is derived on the move, not on the filing: "`consent_gate` is
    `BLOCKED` when any consent record linked to that move whose `scope` is
    `UTILITY_SETUP` or `USPS_FILING` is in `state` `REVOKED` or `EXPIRED`",
    and a blocked gate is refused on six operations one of which is filing
    submission, with `ERR_CONSENT_REVOKED`.  The resident here holds a
    perfectly good `USPS_FILING` consent throughout; what stops the filing is
    the unrelated utility disclosure being withdrawn.  With the consent
    component driven to 0 the move scores 30 under the post-verification
    weights: identity 100 at 0.30 and nothing else.

    Design: Difficulty/cross_entity_state_dependency/filing_submission_blocked_by_revoked_utility_consent
    """
    net = fixtures.build_network(api)
    bundle = fixtures.verified_move(
        api,
        network=net,
        scopes=[ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    move_id = bundle["move"]["id"]
    filing = fixtures.draft_filing(api, move_id)

    utility_consent = bundle["consents"][ConsentScope.UTILITY_SETUP.value]
    revoked = assert_ok(
        api.revoke_consent(utility_consent["id"], f.revocation_payload(), compliance_headers)
    )
    assert revoked["state"] == ConsentState.REVOKED.value, (
        f"expected the utility consent in REVOKED, got {revoked['state']}"
    )

    blocked_move = fixtures.read_move(api, move_id)
    assert_move_state(
        blocked_move,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        consent_gate=ConsentGate.BLOCKED.value,
        blocked_reason=BlockedReason.CONSENT_REVOKED.value,
        readiness_score=30,
    )

    assert_error(
        api.submit_filing(filing["id"], {}, ops_headers),
        ApiErrorId.CONSENT_REVOKED,
        expected_status=409,
    )

    untouched = get_success_data(api.get_filing(filing["id"], ops_headers))
    assert untouched["status"] == FilingStatus.DRAFT.value, (
        f"a refused submission must leave the filing in DRAFT, got {untouched['status']}"
    )
    assert untouched["submitted_by_user_id"] is None, (
        "a refused submission must not stamp submitted_by_user_id"
    )
    filing_consent = bundle["consents"][ConsentScope.USPS_FILING.value]
    still_granted = get_success_data(api.get_consent_record(filing_consent["id"], ops_headers))
    assert still_granted["state"] == ConsentState.GRANTED.value, (
        "the USPS_FILING consent was never withdrawn and must remain GRANTED"
    )


def test_02_revoked_marketing_consent_leaves_filing_submission_open(
    api, ops_headers, compliance_headers
):
    """The marketing scope is deliberately outside the gate, so the filing goes.

    Withdrawing `PARTNER_MARKETING` takes the other branch of the cascade
    entirely: "No move is gated, no order is suspended and no credit exposure
    is voided by this branch."  This is the discriminating sibling of the
    blocked case — same operation, same move, a revoked consent of a scope
    that is not a gate scope, and a successful submission.  Submission
    "moves `status` to `SUBMITTED`, writes `submitted_by_user_id` with the
    acting `X-User-ID`" and lifts the filing component to 60, taking the move
    from 50 to 62.

    Design: Difficulty/cross_entity_state_dependency/filing_submission_blocked_by_revoked_utility_consent
    """
    net = fixtures.build_network(api)
    bundle = fixtures.verified_move(api, network=net)
    move_id = bundle["move"]["id"]
    filing = fixtures.draft_filing(api, move_id)

    marketing_consent = bundle["consents"][ConsentScope.PARTNER_MARKETING.value]
    assert_ok(
        api.revoke_consent(marketing_consent["id"], f.revocation_payload(), compliance_headers)
    )

    open_move = fixtures.read_move(api, move_id)
    assert_move_state(
        open_move,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=50,
    )

    submitted = assert_ok(api.submit_filing(filing["id"], {}, ops_headers))
    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the filing in SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submitted_by_user_id"] == MOVE_OPS_AGENT_USER_ID, (
        f"expected submitted_by_user_id {MOVE_OPS_AGENT_USER_ID}, "
        f"got {submitted['submitted_by_user_id']}"
    )

    after = fixtures.read_move(api, move_id)
    assert_move_state(after, consent_gate=ConsentGate.OPEN.value, readiness_score=62)


def test_03_fresh_utility_consent_reopens_the_gate_and_the_filing_submits(
    api, ops_headers, compliance_headers
):
    """Restoring the withdrawn scope reopens the gate for the same filing.

    "Recording a fresh `GRANTED` consent for a previously revoked gate scope
    flips the affected moves' `consent_gate` back to `OPEN`", after which the
    filing that was refused a moment earlier submits untouched and the move
    settles at 62: identity 100, no orders, filing 60, consent 100.

    Design: Difficulty/cross_entity_state_dependency/filing_submission_blocked_by_revoked_utility_consent
    """
    net = fixtures.build_network(api)
    bundle = fixtures.verified_move(
        api,
        network=net,
        scopes=[ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    move_id = bundle["move"]["id"]
    resident_id = bundle["resident"]["id"]
    filing = fixtures.draft_filing(api, move_id)

    utility_consent = bundle["consents"][ConsentScope.UTILITY_SETUP.value]
    assert_ok(
        api.revoke_consent(utility_consent["id"], f.revocation_payload(), compliance_headers)
    )
    assert_error(
        api.submit_filing(filing["id"], {}, ops_headers),
        ApiErrorId.CONSENT_REVOKED,
        expected_status=409,
    )

    resident = fixtures.read_resident(api, resident_id)
    fixtures.grant_consent(
        api, resident_id, ConsentScope.UTILITY_SETUP.value, resident["version"]
    )

    reopened = fixtures.read_move(api, move_id)
    assert_move_state(reopened, consent_gate=ConsentGate.OPEN.value)

    submitted = assert_ok(api.submit_filing(filing["id"], {}, ops_headers))
    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the restored filing in SUBMITTED, got {submitted['status']}"
    )

    after = fixtures.read_move(api, move_id)
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        consent_gate=ConsentGate.OPEN.value,
        readiness_score=62,
    )


# ---------------------------------------------------------------------------
# A DEPOSIT_DUE credit posture gates order activation
# ---------------------------------------------------------------------------
def _gas_order_awaiting_deposit(api) -> Dict[str, Any]:
    """A scheduled gas order whose bureau answer left a deposit outstanding.

    The dispatch happens while the order is still `DRAFT`, because dispatch
    "requires its `provision_status` to be `DRAFT`", so the snapshot freezes
    before the schedule lifts the utility component: identity 100, utility 0,
    filing 0 and consent 50 give a frozen `readiness_snapshot` of 40.
    """
    net = fixtures.build_network(api)
    gas = fixtures.create_provider(api, f.gas_provider_payload())
    fixtures.create_territory(api, gas["id"], postal_code="30302", state_code="GA")

    bundle = fixtures.verified_move(
        api, network=net, scopes=[ConsentScope.UTILITY_SETUP.value]
    )
    move_id = bundle["move"]["id"]
    move = fixtures.run_mapping(api, move_id, utility_types=[UtilityType.GAS.value])
    assert move["mapped_order_count"] == 1, (
        f"expected exactly one mapped order, got {move['mapped_order_count']}"
    )

    order = fixtures.order_of_type(api, move_id, UtilityType.GAS.value)
    handoff = fixtures.dispatch_credit_check(api, order["id"])
    frozen = fixtures.read_order(api, order["id"])
    assert frozen["readiness_snapshot"] == 40, (
        f"expected a frozen readiness_snapshot of 40, got {frozen['readiness_snapshot']}"
    )
    handoff = fixtures.answer_bureau(api, handoff["id"], 639)

    scheduled = fixtures.schedule_order(
        api, order["id"], requested_service_date="2026-08-05"
    )
    return {
        **bundle,
        "gas_provider": gas,
        "handoff": handoff,
        "order": scheduled,
    }


def test_04_activation_is_refused_while_the_deposit_remains_due(api, ops_headers):
    """A scheduled order with an unpaid deposit cannot be reported live.

    "Activation additionally requires the order's `credit_status` to be one of
    `NOT_REQUIRED`, `CLEARED` or `DEPOSIT_PAID`", so the `DEPOSIT_DUE` posture
    left by the bureau answer is refused with `ERR_CREDIT_NOT_CLEARED` even
    though the provisioning dimension is faultless: the order is `SCHEDULED`,
    the clock has reached `scheduled_window_start` and the gate is `OPEN`.
    The outstanding figure is the PRD's three-factor product on a `FLAT`
    provider — base 9900, score multiplier 1.00 for a bureau score of 639 and
    readiness multiplier 1.20 for a frozen snapshot below 50 — which is 11880
    against the 14850 quoted at mapping from the worst score multiplier of
    1.50 and a neutral readiness multiplier of 1.00.

    Design: Difficulty/cross_entity_state_dependency/order_activation_blocked_by_deposit_due_handoff
    """
    setup = _gas_order_awaiting_deposit(api)
    order = setup["order"]
    move_id = setup["move"]["id"]

    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert_cents(order, "deposit_amount_cents", 11880)
    assert_cents(order, "deposit_estimate_cents", 14850)
    assert_cents(order, "deposit_paid_cents", 0)
    assert open_deposit_liability_cents(api, move_id, ops_headers) == 11880, (
        "the move's open deposit liability must equal the single unpaid deposit"
    )

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    assert_error(
        api.activate_order(
            order["id"],
            f.activation_payload(),
            make_provider_agent_headers(setup["gas_provider"]["id"]),
        ),
        ApiErrorId.CREDIT_NOT_CLEARED,
        expected_status=409,
    )

    after = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        after,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert after["confirmation_code"] is None, (
        "a refused activation must not write confirmation_code"
    )
    assert_move_state(
        fixtures.read_move(api, move_id),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        consent_gate=ConsentGate.OPEN.value,
    )


def test_05_paying_the_exact_deposit_lets_the_same_activation_through(api, ops_headers):
    """Settling the handoff's deposit is what unlocks activation.

    "A successful payment writes `deposit_paid_cents` with the paid amount,
    moves `credit_status` from `DEPOSIT_DUE` to `DEPOSIT_PAID`" and drops the
    move's open deposit liability by `deposit_amount_cents`, taking the
    measured liability from 11880 to 0.  Activation then "moves
    `provision_status` from `SCHEDULED` to `ACTIVE_SERVICE`, keeps the
    occupancy window occupied" and leaves the move at 70 — identity 100,
    utility 100, filing 0, consent 50.  The move stays in `SCHEDULING`
    because the bubble-up needs "exactly one filing of the move must be
    `CONFIRMED`" and this household has filed nothing.

    Design: Difficulty/cross_entity_state_dependency/order_activation_blocked_by_deposit_due_handoff
    """
    setup = _gas_order_awaiting_deposit(api)
    order = setup["order"]
    move_id = setup["move"]["id"]

    paid = assert_ok(
        api.pay_deposit(order["id"], f.deposit_payment_payload(11880), ops_headers)
    )
    assert_order_dimensions(
        paid,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_PAID.value,
    )
    assert_cents(paid, "deposit_paid_cents", 11880)
    assert_cents(paid, "deposit_amount_cents", 11880)
    assert open_deposit_liability_cents(api, move_id, ops_headers) == 0, (
        "paying the deposit must drop the move's open deposit liability to zero"
    )

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    activated = assert_ok(
        api.activate_order(
            order["id"],
            f.activation_payload(),
            make_provider_agent_headers(setup["gas_provider"]["id"]),
        )
    )
    assert_order_dimensions(
        activated,
        provision_status=ProvisionStatus.ACTIVE_SERVICE.value,
        credit_status=CreditStatus.DEPOSIT_PAID.value,
    )
    assert activated["confirmation_code"] == "CONF-88213", (
        f"expected the supplied confirmation_code, got {activated['confirmation_code']}"
    )
    assert activated["scheduled_window_start"] is not None, (
        "an ACTIVE_SERVICE order still holds its occupancy window"
    )

    assert_move_state(
        fixtures.read_move(api, move_id),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=70,
    )


# ---------------------------------------------------------------------------
# The resident's marketing switch gates referral placement creation
# ---------------------------------------------------------------------------
def test_06_opted_out_resident_cannot_receive_a_referral_placement(
    api, ops_headers, compliance_headers
):
    """A boolean on the resident row refuses a write against the move.

    Placement creation reads a field the placement itself never carries:
    "the resident's `marketing_opt_out` must be false, an opted-out household
    being refused with `ERR_MARKETING_OPT_OUT`" at 422.  The opt-out itself is
    stamped, since "When the value flips from false to true, the server sets
    `opted_out_at` to the logical-clock instant", and the refusal is total —
    the move keeps no placement at all.

    Design: Difficulty/cross_entity_state_dependency/placement_creation_blocked_by_resident_opt_out
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.verified_move(api)
    partner = fixtures.add_internet_partner(api)
    resident_id = bundle["resident"]["id"]

    opted_out = assert_ok(
        api.patch_marketing_preferences(
            resident_id, f.marketing_preferences_payload(True), compliance_headers
        )
    )
    assert opted_out["marketing_opt_out"] is True, "the opt-out switch must read true"
    assert opted_out["opted_out_at"] is not None, (
        "flipping the switch to true must stamp opted_out_at"
    )

    move = fixtures.read_move(api, bundle["move"]["id"])
    assert_error(
        api.create_placement(
            move["id"], f.placement_payload(partner["id"], move["version"]), ops_headers
        ),
        ApiErrorId.MARKETING_OPT_OUT,
        expected_status=422,
    )

    assert_page(api.list_placements(ops_headers, move_id=move["id"]), 0)
    unchanged = fixtures.read_move(api, move["id"])
    assert unchanged["version"] == move["version"], (
        "a refused placement must not add one to the parent move's version"
    )


def test_07_opting_back_in_clears_the_stamp_and_admits_the_placement(
    api, ops_headers, compliance_headers
):
    """The same operation succeeds the moment the resident opts back in.

    "When the value flips from true back to false, `opted_out_at` is cleared to
    null", and the placement then opens as the PRD describes: it "records
    `placed_at` as the current instant, opens in `placement_status` `PLACED`"
    and "adds one to the parent move's `version`".  This is the accepted side
    of the same cross-entity gate that refused the write a moment earlier.

    Design: Difficulty/cross_entity_state_dependency/placement_creation_blocked_by_resident_opt_out
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.verified_move(api)
    partner = fixtures.add_internet_partner(api)
    resident_id = bundle["resident"]["id"]

    assert_ok(
        api.patch_marketing_preferences(
            resident_id, f.marketing_preferences_payload(True), compliance_headers
        )
    )
    opted_in = assert_ok(
        api.patch_marketing_preferences(
            resident_id, f.marketing_preferences_payload(False), compliance_headers
        )
    )
    assert opted_in["marketing_opt_out"] is False, "the opt-out switch must read false again"
    assert opted_in["opted_out_at"] is None, (
        "flipping the switch back to false must clear opted_out_at to null"
    )

    move = fixtures.read_move(api, bundle["move"]["id"])
    placement = assert_created(
        api.create_placement(
            move["id"], f.placement_payload(partner["id"], move["version"]), ops_headers
        )
    )
    assert placement["placement_status"] == PlacementStatus.PLACED.value, (
        f"expected a new placement in PLACED, got {placement['placement_status']}"
    )
    assert placement["placed_at"] is not None, "placed_at must record the current instant"
    assert_cents(placement, "attributed_share_cents", 0)
    assert_cents(placement, "feed_source_share_cents", 0)

    assert_version_bumped(move, fixtures.read_move(api, move["id"]))


def test_08_the_opt_out_gate_is_read_per_resident_not_per_platform(
    api, ops_headers, compliance_headers
):
    """One household's opt-out leaves another household's referral untouched.

    The gate is that "the resident's `marketing_opt_out` must be false, an
    opted-out household being refused with `ERR_MARKETING_OPT_OUT`", so it is
    resolved through the move being written and no further.  Two moves share the same
    feed source and the same destination address here, which is exactly why
    the distinction matters: the refusal follows the resident, not the
    address.  The opted-out household is refused with
    `ERR_MARKETING_OPT_OUT`, while the second household's placement "opens in
    `placement_status` `PLACED`".

    Design: Difficulty/cross_entity_state_dependency/placement_creation_blocked_by_resident_opt_out
    """
    net = fixtures.build_network(api)
    partner = fixtures.add_internet_partner(api)

    first = fixtures.verified_move(api, network=net)
    second_resident = fixtures.create_second_resident(api)
    second = fixtures.verified_move(api, network={**net, "resident": second_resident})

    assert_ok(
        api.patch_marketing_preferences(
            first["resident"]["id"], f.marketing_preferences_payload(True), compliance_headers
        )
    )

    blocked_move = fixtures.read_move(api, first["move"]["id"])
    assert_error(
        api.create_placement(
            blocked_move["id"],
            f.placement_payload(partner["id"], blocked_move["version"]),
            ops_headers,
        ),
        ApiErrorId.MARKETING_OPT_OUT,
        expected_status=422,
    )

    open_move = fixtures.read_move(api, second["move"]["id"])
    placement = assert_created(
        api.create_placement(
            open_move["id"],
            f.placement_payload(partner["id"], open_move["version"]),
            ops_headers,
        )
    )
    assert placement["placement_status"] == PlacementStatus.PLACED.value, (
        f"expected the second household's placement in PLACED, "
        f"got {placement['placement_status']}"
    )
    assert placement["move_id"] == open_move["id"], (
        "the placement must belong to the household that was not opted out"
    )
    assert_page(api.list_placements(ops_headers, move_id=blocked_move["id"]), 0)
    assert_page(api.list_placements(ops_headers, move_id=open_move["id"]), 1)
