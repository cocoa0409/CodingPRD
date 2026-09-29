"""Authorisation: reserved operations, ownership boundaries and duty segregation.

The eight roles are not a hierarchy.  Some operations are held exclusively by
one role and are refused to every other, in both directions; some are shared
by three roles that otherwise have nothing in common; and for the four roles
whose `X-User-ID` names a row of the domain, holding the right role is not
enough — the addressed resource has to be the caller's own.  Every test here
therefore builds the acting identity out of the id of a row it created, and
each refusal is checked for the *right* refusal: a caller stopped at the role
or ownership rung must never be told about the state rung underneath it, and
the row it addressed must be untouched afterwards.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_unchanged,
    assert_version_bumped,
    assert_versioned_resource,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_ALT_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    MOVE_OPS_AGENT_USER_ID,
    make_feed_integrator_headers,
    make_partner_agent_headers,
    make_provider_agent_headers,
    make_resident_headers,
)
from test_helpers.types import (
    ConsentScope,
    ConsentState,
    CreditStatus,
    FilingStatus,
    MoveLifecycleStatus,
    PlacementStatus,
    ProviderStatus,
    ProvisionStatus,
    UtilityType,
    VerificationMethod,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# Exclusive operations are refused in both directions
# ---------------------------------------------------------------------------
def test_01_a_compliance_officer_cannot_run_provider_mapping(api, compliance_headers, ops_headers):
    """Mapping is reserved to operations, so compliance is refused and the move stands still.

    PRD: "Provider mapping, attention clearance, move completion, order
    scheduling, credit-check dispatch, order waiver and referral placement are
    reserved to `MoveOpsAgent` and `PlatformAdmin`."

    Design: Corner/rbac/rbac_exclusive_operations_are_forbidden_across_roles_in_both_directions
    """
    bundle = fixtures.verified_move(api)
    payload = factories.mapping_payload([UtilityType.ELECTRIC.value])

    refused = api.run_provider_mapping(bundle["move"]["id"], payload, compliance_headers)
    assert_error(refused, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    parked = fixtures.read_move(api, bundle["move"]["id"])
    assert_move_state(parked, lifecycle_status=MoveLifecycleStatus.VERIFIED.value)
    assert_unchanged(bundle["move"], parked)

    allowed = assert_ok(api.run_provider_mapping(bundle["move"]["id"], payload, ops_headers))
    assert allowed["lifecycle_status"] == MoveLifecycleStatus.SCHEDULING.value, (
        f"the identical body must succeed for operations, got {allowed['lifecycle_status']}"
    )


def test_02_a_compliance_officer_cannot_toggle_a_provider_status(api, compliance_headers, admin_headers):
    """Provider status toggles belong to the admin alone; the provider stays ACTIVE.

    PRD: "Feed, provider and partner registration and their status toggles,
    referral settlement, and the logical-clock control are reserved to
    `PlatformAdmin`."
    PRD: "an admin may toggle that to `INACTIVE` and back"

    Design: Corner/rbac/rbac_exclusive_operations_are_forbidden_across_roles_in_both_directions
    """
    provider = fixtures.create_provider(api, factories.electric_provider_payload())
    payload = factories.status_payload("provider_status", ProviderStatus.INACTIVE.value)

    refused = api.patch_provider_status(provider["id"], payload, compliance_headers)
    assert_error(refused, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    still_active = assert_ok(api.get_utility_provider(provider["id"], admin_headers))
    assert still_active["provider_status"] == ProviderStatus.ACTIVE.value, (
        f"the provider must still be ACTIVE, got {still_active['provider_status']}"
    )
    assert_unchanged(provider, still_active)

    toggled = assert_ok(api.patch_provider_status(provider["id"], payload, admin_headers))
    assert toggled["provider_status"] == ProviderStatus.INACTIVE.value, (
        f"the admin must be able to deactivate, got {toggled['provider_status']}"
    )


def test_03_an_operations_agent_is_stopped_at_the_role_rung_of_an_activation(api, ops_headers):
    """Activation is a provider operation, and the role refusal outranks the state refusal.

    PRD: "Order activation and provision-failure reporting are reserved to
    `ProviderAgent` and `PlatformAdmin`"
    PRD: "2. The acting role is authorised for the target endpoint, including the
    reserved-operation restrictions of §2.1 — otherwise `ERR_FORBIDDEN_ROLE`
    (403). Applies to every endpoint."

    Design: Corner/rbac/rbac_exclusive_operations_are_forbidden_across_roles_in_both_directions
    """
    bundle = fixtures.mapped_move(api, utility_types=[UtilityType.WATER.value])
    order = bundle["orders_by_type"][UtilityType.WATER.value]

    refused = api.activate_order(order["id"], factories.activation_payload(), ops_headers)
    assert_error(refused, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    after = fixtures.read_order(api, order["id"])
    assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
    assert_unchanged(order, after)


# ---------------------------------------------------------------------------
# The manual override is reserved on a path operations otherwise shares
# ---------------------------------------------------------------------------
def test_04_operations_may_not_record_a_manual_override_on_a_path_it_shares(api, ops_headers):
    """A MoveOpsAgent entitled to open a KBA attempt is refused the override method.

    PRD: "Recording an identity verification with `method` `MANUAL_OVERRIDE` and
    cancelling a postal filing are reserved to `ComplianceOfficer` and
    `PlatformAdmin` — which means a `MoveOpsAgent` that is entirely entitled to
    open a `KBA` verification attempt on the very same path is refused the
    override with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/rbac_manual_override_is_reserved_to_compliance_on_a_path_shared_with_move_ops
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)

    refused = api.create_identity_verification(
        move["id"], factories.manual_override_payload(), ops_headers
    )
    assert_error(refused, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    after = fixtures.read_move(api, move["id"])
    assert after["identity_attempt_count"] == 0, (
        f"a refused override must not consume an attempt, got {after['identity_attempt_count']}"
    )
    assert_move_state(after, lifecycle_status=MoveLifecycleStatus.INTAKE.value)
    assert_unchanged(move, after)


def test_05_compliance_clears_the_role_rung_and_is_then_judged_on_the_body(api, compliance_headers):
    """With the role gate satisfied the same call falls through to body validation.

    PRD: "plus an `override_reason` that is required and must be non-empty when
    the method is `MANUAL_OVERRIDE` and is otherwise omitted"
    PRD: "An override submitted without a non-empty `override_reason` is refused
    as a malformed request."

    Design: Corner/rbac/rbac_manual_override_is_reserved_to_compliance_on_a_path_shared_with_move_ops
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)
    payload = factories.manual_override_payload()
    payload.pop("override_reason")

    response = api.create_identity_verification(move["id"], payload, compliance_headers)

    assert_error(response, ApiErrorId.INVALID_REQUEST, expected_status=422)
    after = fixtures.read_move(api, move["id"])
    assert after["identity_attempt_count"] == 0, (
        f"a rejected body must not consume an attempt, got {after['identity_attempt_count']}"
    )


def test_06_the_override_stamps_the_acting_compliance_officer_as_reviewer(api, compliance_headers):
    """A well-formed override passes identity immediately and records who signed it.

    PRD: "the row is created directly in `status` `PASSED` with `decided_at` set
    to the current instant, `kba_score` left null, and `reviewer_user_id`
    stamped with the acting `X-User-ID`"
    PRD: "Every successfully opened attempt, of either method, increments
    `identity_attempt_count` by one."

    Design: Corner/rbac/rbac_manual_override_is_reserved_to_compliance_on_a_path_shared_with_move_ops
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)

    verification = assert_created(
        api.create_identity_verification(
            move["id"], factories.manual_override_payload(), compliance_headers
        )
    )

    assert verification["method"] == VerificationMethod.MANUAL_OVERRIDE.value, (
        f"unexpected method {verification['method']}"
    )
    assert verification["status"] == VerificationStatus.PASSED.value, (
        f"an override is decided synchronously, got {verification['status']}"
    )
    assert verification["reviewer_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        f"unexpected reviewer_user_id {verification['reviewer_user_id']}"
    )
    assert_versioned_resource(verification, expected_version=1)

    after = fixtures.read_move(api, move["id"])
    assert_move_state(after, lifecycle_status=MoveLifecycleStatus.VERIFIED.value)
    assert after["identity_attempt_count"] == 1, (
        f"expected identity_attempt_count 1, got {after['identity_attempt_count']}"
    )


# ---------------------------------------------------------------------------
# Peer roles cannot reach a sibling owner's resource
# ---------------------------------------------------------------------------
def test_07_a_feed_integrator_cannot_ingest_a_move_naming_another_feed(api, admin_headers):
    """A second feed's integrator is refused a body that credits the first feed.

    PRD: "A `FeedIntegrator` may therefore ingest a move only when the
    `feed_source_id` in the body equals its own identifier"
    PRD: "Any attempt by one of those four roles to address a resource it does
    not own is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/rbac_peer_roles_cannot_reach_a_sibling_owner_resource
    """
    network = fixtures.build_network(api)
    sibling_feed = fixtures.create_feed_source(api, name="Northside PM Feed")
    payload = factories.move_payload(
        network["resident"]["id"],
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        network["destination_address"]["id"],
    )

    refused = api.create_move(payload, make_feed_integrator_headers(sibling_feed["id"]))
    assert_error(refused, ApiErrorId.OWNERSHIP_VIOLATION, expected_status=403)

    assert_page(api.list_moves(admin_headers), total_count=0, has_more=False)

    accepted = assert_created(
        api.create_move(payload, make_feed_integrator_headers(network["feed_source"]["id"]))
    )
    assert accepted["feed_source_id"] == network["feed_source"]["id"], (
        "the owning integrator must be able to ingest the identical body"
    )


def test_08_a_provider_agent_is_stopped_at_ownership_before_the_state_rung(api):
    """The water provider's agent addressing the DRAFT electric order gets the ownership error.

    PRD: "A `ProviderAgent` may act on a service order only when that order's
    `provider_id` equals its own identifier"
    PRD: "5. For an entity-backed role, `X-User-ID` owns the addressed resource
    per §2.1 — otherwise `ERR_OWNERSHIP_VIOLATION` (403)."

    Design: Corner/rbac/rbac_peer_roles_cannot_reach_a_sibling_owner_resource
    """
    bundle = fixtures.mapped_move(api)
    electric_order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    intruder = make_provider_agent_headers(bundle["water_provider"]["id"])

    refused = api.activate_order(electric_order["id"], factories.activation_payload(), intruder)

    assert_error(refused, ApiErrorId.OWNERSHIP_VIOLATION, expected_status=403)
    after = fixtures.read_order(api, electric_order["id"])
    assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
    assert_unchanged(electric_order, after)


def test_09_a_partner_agent_cannot_accept_a_sibling_partners_placement(api, admin_headers):
    """A second internet partner's agent is refused, and the owner then accepts.

    PRD: "ownership checks on any resource that references a `ReferralPartner`
    compare the resource's `partner_id` to `X-User-ID`"
    PRD: "placement acceptance, decline and conversion are reserved to
    `PartnerAgent` and `PlatformAdmin`"

    Design: Corner/rbac/rbac_peer_roles_cannot_reach_a_sibling_owner_resource
    """
    owner = fixtures.add_internet_partner(api)
    sibling = fixtures.create_partner(api, factories.alternate_internet_partner_payload())
    bundle = fixtures.placed_referral(api, partner=owner)
    placement_id = bundle["placement"]["id"]

    refused = api.accept_placement(placement_id, {}, make_partner_agent_headers(sibling["id"]))
    assert_error(refused, ApiErrorId.OWNERSHIP_VIOLATION, expected_status=403)

    untouched = assert_ok(api.get_placement(placement_id, admin_headers))
    assert untouched["placement_status"] == PlacementStatus.PLACED.value, (
        f"the placement must still be PLACED, got {untouched['placement_status']}"
    )
    assert_unchanged(bundle["placement"], untouched)

    accepted = assert_ok(
        api.accept_placement(placement_id, {}, make_partner_agent_headers(owner["id"]))
    )
    assert accepted["placement_status"] == PlacementStatus.ACCEPTED.value, (
        f"the owning partner must be able to accept, got {accepted['placement_status']}"
    )


def test_10_a_resident_cannot_revoke_a_sibling_residents_consent(api, admin_headers):
    """The consent of one resident is unreachable to another, and stays GRANTED.

    PRD: "ownership checks compare the addressed resident's `id`, or a consent
    record's `resident_id`, to `X-User-ID`"
    PRD: "The record is created in `state` `GRANTED` with `granted_at` set to the
    current instant and with `revoked_at` and `revocation_reason` both null."

    Design: Corner/rbac/rbac_peer_roles_cannot_reach_a_sibling_owner_resource
    """
    owner = fixtures.create_resident(api)
    sibling = fixtures.create_second_resident(api)
    consent = fixtures.grant_consent(api, owner["id"], ConsentScope.UTILITY_SETUP.value, 1)

    refused = api.revoke_consent(
        consent["id"], factories.revocation_payload(), make_resident_headers(sibling["id"])
    )
    assert_error(refused, ApiErrorId.OWNERSHIP_VIOLATION, expected_status=403)

    untouched = assert_ok(api.get_consent_record(consent["id"], admin_headers))
    assert untouched["state"] == ConsentState.GRANTED.value, (
        f"the consent must still be GRANTED, got {untouched['state']}"
    )
    assert untouched["revoked_at"] is None, "revoked_at must still be null"
    assert_unchanged(consent, untouched)

    revoked = assert_ok(
        api.revoke_consent(
            consent["id"], factories.revocation_payload(), make_resident_headers(owner["id"])
        )
    )
    assert revoked["state"] == ConsentState.REVOKED.value, (
        f"the owning resident must be able to revoke, got {revoked['state']}"
    )


# ---------------------------------------------------------------------------
# Shared operations span three roles that share nothing else
# ---------------------------------------------------------------------------
def _order_awaiting_a_deposit(api):
    """An electric order in DEPOSIT_DUE for 27000 cents on a frozen snapshot of 40."""
    network = fixtures.build_network(api)
    fixtures.grant_consent(api, network["resident"]["id"], ConsentScope.UTILITY_SETUP.value, 1)
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])
    fixtures.run_mapping(api, move["id"], utility_types=[UtilityType.ELECTRIC.value])
    order = fixtures.order_of_type(api, move["id"], UtilityType.ELECTRIC.value)
    handoff = fixtures.dispatch_credit_check(api, order["id"])
    fixtures.answer_bureau(api, handoff["id"], 580)
    return {"network": network, "order": fixtures.read_order(api, order["id"])}


def test_11_the_deposit_is_closed_to_compliance_and_open_to_the_resident(api, compliance_headers):
    """Compliance is refused the exact-match payment the owning resident may make.

    PRD: "Paying a deposit is an exact-match operation open to a `MoveOpsAgent`,
    a `PlatformAdmin` or the `Resident` itself."
    PRD: "A `DEPOSIT_REQUIRED` result moves `credit_status` to `DEPOSIT_DUE`"
    PRD: "1.50 for a score from 580 through 599"
    PRD: "1.20 when the snapshot is below 50"

    Design: Corner/rbac/rbac_shared_operation_deposit_and_marketing_writes_span_three_roles
    """
    world = _order_awaiting_a_deposit(api)
    order = world["order"]
    assert_order_dimensions(order, credit_status=CreditStatus.DEPOSIT_DUE.value)
    assert order["readiness_snapshot"] == 40, (
        f"expected a frozen readiness_snapshot of 40, got {order['readiness_snapshot']}"
    )
    assert_cents(order, "deposit_amount_cents", 27000)
    payload = factories.deposit_payment_payload(27000)

    refused = api.pay_deposit(order["id"], payload, compliance_headers)
    assert_error(refused, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)
    assert_unchanged(order, fixtures.read_order(api, order["id"]))

    paid = assert_ok(
        api.pay_deposit(
            order["id"], payload, make_resident_headers(world["network"]["resident"]["id"])
        )
    )
    assert_order_dimensions(paid, credit_status=CreditStatus.DEPOSIT_PAID.value)


def test_12_the_marketing_switch_is_shared_but_still_ownership_bound(api, admin_headers):
    """A resident may flip its own opt-out and not a sibling's, even on a shared endpoint.

    PRD: "ownership checks compare the addressed resident's `id`, or a consent
    record's `resident_id`, to `X-User-ID`"
    PRD: "an integer that starts at 1 on creation and increments by one on every
    mutation of that row"

    Design: Corner/rbac/rbac_shared_operation_deposit_and_marketing_writes_span_three_roles
    """
    owner = fixtures.create_resident(api)
    sibling = fixtures.create_second_resident(api)
    payload = factories.marketing_preferences_payload(True)

    refused = api.patch_marketing_preferences(
        sibling["id"], payload, make_resident_headers(owner["id"])
    )
    assert_error(refused, ApiErrorId.OWNERSHIP_VIOLATION, expected_status=403)

    untouched = assert_ok(api.get_resident(sibling["id"], admin_headers))
    assert untouched["marketing_opt_out"] is False, (
        f"the sibling must still be opted in, got {untouched['marketing_opt_out']}"
    )
    assert_unchanged(sibling, untouched)

    updated = assert_ok(
        api.patch_marketing_preferences(owner["id"], payload, make_resident_headers(owner["id"]))
    )
    assert updated["marketing_opt_out"] is True, (
        f"the owning resident must be able to opt out, got {updated['marketing_opt_out']}"
    )
    assert_version_bumped(owner, updated)


# ---------------------------------------------------------------------------
# Segregation of duties on the postal filing
# ---------------------------------------------------------------------------
def _filing_reviewed_by_the_first_officer(api):
    """A DRAFT filing on a move whose identity was overridden by compliance-user-c1."""
    network = fixtures.build_network(api)
    fixtures.grant_consent(api, network["resident"]["id"], ConsentScope.USPS_FILING.value, 1)
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_override(api, move["id"], COMPLIANCE_OFFICER_USER_ID)
    filing = fixtures.draft_filing(api, move["id"])
    return {"network": network, "move": move, "filing": filing}


def test_13_the_override_reviewer_may_not_submit_the_filing_it_unlocked(api, compliance_headers):
    """The officer who waved identity through by hand is refused the postal submission.

    PRD: "19. The submitting `X-User-ID` differs from the `reviewer_user_id` of
    every passed `MANUAL_OVERRIDE` verification on the same move — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403). Applies to filing submission."
    PRD: "The filing opens in `status` `DRAFT` with `submitted_by_user_id`,
    `usps_confirmation_code`, `reject_reason`, `mail_forwarding_confirmed_at` and
    `cancellation_reason` all null and `resubmit_count` at 0."

    Design: Corner/rbac/rbac_segregation_of_duties_the_override_reviewer_cannot_submit_the_filing
    """
    world = _filing_reviewed_by_the_first_officer(api)

    refused = api.submit_filing(world["filing"]["id"], {}, compliance_headers)
    assert_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, expected_status=403)

    still_draft = assert_ok(api.get_filing(world["filing"]["id"], compliance_headers))
    assert still_draft["status"] == FilingStatus.DRAFT.value, (
        f"the filing must still be DRAFT, got {still_draft['status']}"
    )
    assert still_draft["submitted_by_user_id"] is None, (
        f"submitted_by_user_id must still be null, got {still_draft['submitted_by_user_id']}"
    )
    assert_unchanged(world["filing"], still_draft)


def test_14_a_second_compliance_officer_submits_the_identical_body(api, compliance_headers, compliance_headers_alt):
    """The bar is per identifier, so the other officer's submission goes through.

    PRD: "a different compliance officer may submit the filing freely"
    PRD: "Successful submission moves `status` to `SUBMITTED`, writes
    `submitted_by_user_id` with the acting `X-User-ID`, and lifts the move's
    readiness filing component to 60."
    PRD: "a `forward_start_date` of 2026-08-20 yields a `forward_end_date` of
    2027-08-19"

    Design: Corner/rbac/rbac_segregation_of_duties_the_override_reviewer_cannot_submit_the_filing
    """
    world = _filing_reviewed_by_the_first_officer(api)
    assert_error(
        api.submit_filing(world["filing"]["id"], {}, compliance_headers),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    submitted = assert_ok(api.submit_filing(world["filing"]["id"], {}, compliance_headers_alt))

    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submitted_by_user_id"] == COMPLIANCE_OFFICER_ALT_USER_ID, (
        f"unexpected submitted_by_user_id {submitted['submitted_by_user_id']}"
    )
    assert submitted["forward_end_date"] == "2027-08-19", (
        f"unexpected forward_end_date {submitted['forward_end_date']}"
    )


def test_15_an_operations_agent_who_granted_nothing_is_unconstrained(api, ops_headers):
    """A MoveOpsAgent submits freely, and the successful filing lifts readiness to 52.

    PRD: "A different reviewer, or a `MoveOpsAgent` who granted nothing, submits
    without obstruction, and the bar applies only within the move whose override
    that user granted."
    PRD: "lifts the move's readiness filing component to 60"
    PRD: "50 when exactly one of those two scopes is covered"

    Design: Corner/rbac/rbac_segregation_of_duties_the_override_reviewer_cannot_submit_the_filing
    """
    world = _filing_reviewed_by_the_first_officer(api)

    submitted = assert_ok(api.submit_filing(world["filing"]["id"], {}, ops_headers))

    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submitted_by_user_id"] == MOVE_OPS_AGENT_USER_ID, (
        f"unexpected submitted_by_user_id {submitted['submitted_by_user_id']}"
    )
    after = fixtures.read_move(api, world["move"]["id"])
    assert_move_state(after, readiness_score=52)
