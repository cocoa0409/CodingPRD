"""Grant award lifecycle, the donation pool, and the grant-then-donation funding
waterfall with its compensating reversal and conservation invariant.

Translates queue A instances cf_funding_waterfall_grant_then_donation,
nl_grant_active_suspended_cycle, tc_grant_suspend_unfunds_services,
ci_grant_funds_conservation, ce_funded_service_requires_grant_active, plus queue
B corner instances for grants, donations, funding validations, and reversal.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_grant_conservation,
    fixtures,
    factories as F,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _fund_payload(participant_id, grant_id, **overrides):
    version = fixtures.grant_version(grant_id)
    payload = F.create_funded_service_payload(
        participant_id=participant_id,
        grant_award_id=grant_id,
        expected_grant_award_version=version,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Queue B — entities / not-found / computed fields
# ---------------------------------------------------------------------------
def test_get_unknown_grant_returns_not_found(api):
    """PRD 2.6: "every id in the path and every foreign-key id in the body resolves to an existing entity, validated left to right in the order they appear, each yielding its entity-specific not-found error (HTTP 404). The entity-specific codes are `ERR_PARTICIPANT_NOT_FOUND` for a participant, `ERR_GRANT_NOT_FOUND` for a grant award ..."

    Design: Corner/entities/corner_grant_not_found_returns_404
    """
    resp = api.get_grant(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND.value)


def test_grant_available_cents_initialized_to_authorized(api):
    """PRD 3.2: "On creation the award is in `status` `DRAFT`, its `committed_cents` is 0, and its `available_cents` is initialized to `authorized_cents`."

    Design: Corner/entities/corner_grant_available_cents_initialized_to_authorized
    """
    data = validate_success(
        api.create_grant(
            F.create_grant_payload(
                title="IIIB Grant", oaa_title="IIIB", category="TRANSPORTATION",
                authorized_cents=750,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["available_cents"] == 750, f"expected 750, got {data['available_cents']}"
    assert data["committed_cents"] == 0, f"expected 0, got {data['committed_cents']}"
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"


def test_donation_restricted_flag_computed_for_earmarked_gift(api):
    """PRD 3.2: "On creation the donation's `remaining_cents` is initialized to `amount_cents`, and its `restricted` flag is computed as true exactly when `category` is not `UNRESTRICTED` (an `UNRESTRICTED` donation is unrestricted and may fund any category)."

    Design: Corner/entities/corner_donation_restricted_flag_computed
    """
    data = validate_success(
        api.create_donation(
            F.create_donation_payload(
                donor_name="Local Bank", category="CONGREGATE_MEAL", amount_cents=4000
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["restricted"] is True, f"CONGREGATE_MEAL donation must be restricted, got {data['restricted']}"
    assert data["remaining_cents"] == 4000, f"expected 4000, got {data['remaining_cents']}"


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula/cf_funding_waterfall_grant_then_donation
# ---------------------------------------------------------------------------
def test_waterfall_draws_grant_then_donation_amounts(api):
    """PRD 3.3: "The grant is drawn first: `grant_amount_cents` is the lesser of the `billable_cents` and the grant's current `available_cents`." PRD 3.3: "The donation is drawn second, and only if a `donation_id` was supplied: `donation_amount_cents` is the lesser of that remainder and the donation's `remaining_cents`; if no donation was supplied, `donation_amount_cents` is 0."

    Design: Difficulty/combinatorial_formula/cf_funding_waterfall_grant_then_donation
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=1000)
    donation = fixtures.create_donation(category="WELLNESS", amount_cents=2000)
    fs = fixtures.fund_service(
        participant["id"], grant["id"], category="WELLNESS", quantity=1,
        donation_id=donation["id"],
    )
    assert fs["billable_cents"] == 1500, f"1 * 1500 WELLNESS unit cost, got {fs['billable_cents']}"
    assert fs["grant_amount_cents"] == 1000, f"grant covers min(1500,1000)=1000, got {fs['grant_amount_cents']}"
    assert fs["donation_amount_cents"] == 500, f"donation covers min(500,2000)=500, got {fs['donation_amount_cents']}"
    assert fs["unfunded_amount_cents"] == 0, f"expected 0 unfunded, got {fs['unfunded_amount_cents']}"
    assert fs["funding_status"] == "FUNDED", f"expected FUNDED, got {fs['funding_status']}"


def test_waterfall_commits_funds_across_grant_donation_participant(api):
    """PRD 3.3: "The allocation's side effects commit the money: the grant's `committed_cents` increases by `grant_amount_cents` and its `available_cents` decreases by the same; the donation's `remaining_cents` decreases by `donation_amount_cents`; and the recipient participant's `funded_cents` increases by `grant_amount_cents` plus `donation_amount_cents`."

    Design: Difficulty/combinatorial_formula/cf_funding_waterfall_grant_then_donation
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=1000)
    donation = fixtures.create_donation(category="WELLNESS", amount_cents=2000)
    fixtures.fund_service(
        participant["id"], grant["id"], category="WELLNESS", quantity=1,
        donation_id=donation["id"],
    )
    grant_after = validate_success(api.get_grant(grant["id"], ADMIN))
    donation_after = validate_success(api.get_donation(donation["id"], ADMIN))
    participant_after = validate_success(api.get_participant(participant["id"], ADMIN))

    assert grant_after["available_cents"] == 0, f"expected 0, got {grant_after['available_cents']}"
    assert grant_after["committed_cents"] == 1000, f"expected 1000, got {grant_after['committed_cents']}"
    assert donation_after["remaining_cents"] == 1500, f"2000 - 500, got {donation_after['remaining_cents']}"
    assert participant_after["funded_cents"] == 1500, f"1000 + 500, got {participant_after['funded_cents']}"
    assert_grant_conservation(grant_after)


def test_waterfall_partial_when_grant_insufficient_and_no_donation(api):
    """PRD 3.3: "The `unfunded_amount_cents` is the remainder still left after the donation draw. From these, `funding_status` is `FUNDED` when `unfunded_amount_cents` is 0; `UNFUNDED` when the grant and donation together applied nothing (their sum is 0); and `PARTIALLY_FUNDED` in every other case."

    Design: Corner/calculations/corner_funding_waterfall_partial_when_grant_insufficient_no_donation
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=500)
    fs = fixtures.fund_service(participant["id"], grant["id"], category="WELLNESS", quantity=1)
    assert fs["grant_amount_cents"] == 500, f"grant covers min(1500,500)=500, got {fs['grant_amount_cents']}"
    assert fs["donation_amount_cents"] == 0, f"no donation, got {fs['donation_amount_cents']}"
    assert fs["unfunded_amount_cents"] == 1000, f"1500 - 500, got {fs['unfunded_amount_cents']}"
    assert fs["funding_status"] == "PARTIALLY_FUNDED", f"expected PARTIALLY_FUNDED, got {fs['funding_status']}"
    grant_after = validate_success(api.get_grant(grant["id"], ADMIN))
    assert grant_after["available_cents"] == 0, f"expected 0, got {grant_after['available_cents']}"
    participant_after = validate_success(api.get_participant(participant["id"], ADMIN))
    assert participant_after["funded_cents"] == 500, f"expected 500, got {participant_after['funded_cents']}"


# ---------------------------------------------------------------------------
# Queue B — funding preconditions
# ---------------------------------------------------------------------------
def test_funded_service_grant_category_mismatch_rejected(api):
    """PRD 3.3: "The funded service's `category` must equal the grant's `category`; a mismatch is `ERR_GRANT_CATEGORY_MISMATCH` (422)."

    Design: Corner/validations/corner_grant_category_mismatch_rejected
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=2000)
    resp = api.create_funded_service(
        _fund_payload(participant["id"], grant["id"], category="CONGREGATE_MEAL", quantity=1),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_CATEGORY_MISMATCH.value)


def test_funded_service_donation_category_mismatch_rejected(api):
    """PRD 3.3: "When a donation is supplied, that donation's `category` must either equal the funded service's `category` or be `UNRESTRICTED`; otherwise the create is rejected with `ERR_DONATION_CATEGORY_MISMATCH` (422)."

    Design: Corner/validations/corner_donation_category_mismatch_rejected
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=500)
    donation = fixtures.create_donation(category="TRANSPORTATION", amount_cents=5000)
    resp = api.create_funded_service(
        _fund_payload(
            participant["id"], grant["id"], category="WELLNESS", quantity=1,
            donation_id=donation["id"],
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_DONATION_CATEGORY_MISMATCH.value)


def test_funded_service_unknown_participant_returns_not_found(api):
    """PRD 2.6: "every id in the path and every foreign-key id in the body resolves to an existing entity, validated left to right in the order they appear, each yielding its entity-specific not-found error (HTTP 404). The entity-specific codes are `ERR_PARTICIPANT_NOT_FOUND` for a participant ..."

    Design: Corner/endpoints/corner_fk_funded_service_unknown_participant_not_found
    """
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=2000)
    version = fixtures.grant_version(grant["id"])
    payload = F.create_funded_service_payload(
        participant_id=NON_EXISTENT_UUID,
        category="WELLNESS",
        quantity=1,
        grant_award_id=grant["id"],
        expected_grant_award_version=version,
    )
    resp = api.create_funded_service(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency/ce_funded_service_requires_grant_active
# ---------------------------------------------------------------------------
def test_fund_against_draft_grant_rejected(api):
    """PRD 3.3: "The named grant must be `ACTIVE`; funding against a grant in any other status is rejected with `ERR_GRANT_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/ce_funded_service_requires_grant_active
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_grant(category="CONGREGATE_MEAL", authorized_cents=3000)  # left DRAFT
    resp = api.create_funded_service(
        _fund_payload(participant["id"], grant["id"], category="CONGREGATE_MEAL", quantity=1),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE.value)


def test_fund_against_suspended_grant_rejected(api):
    """PRD 3.3: "The named grant must be `ACTIVE`; funding against a grant in any other status is rejected with `ERR_GRANT_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/ce_funded_service_requires_grant_active
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="CONGREGATE_MEAL", authorized_cents=3000)
    fixtures.suspend_grant(grant["id"])  # now SUSPENDED
    resp = api.create_funded_service(
        _fund_payload(participant["id"], grant["id"], category="CONGREGATE_MEAL", quantity=1),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine/nl_grant_active_suspended_cycle
# ---------------------------------------------------------------------------
def test_grant_resume_returns_to_active_incrementing_version(api):
    """PRD 3.2: "Activating an award moves it into `ACTIVE`: this same activation capability serves both the initial `DRAFT → ACTIVE` transition and the `SUSPENDED → ACTIVE` resume, closing the `ACTIVE ↔ SUSPENDED` cycle."

    Design: Difficulty/non_linear_state_machine/nl_grant_active_suspended_cycle
    """
    grant = fixtures.create_active_grant(category="TRANSPORTATION", authorized_cents=5000)
    suspended = fixtures.suspend_grant(grant["id"])
    resumed = validate_success(api.activate_grant(grant["id"], ADMIN))
    assert resumed["status"] == "ACTIVE", f"resume must return to ACTIVE, got {resumed['status']}"
    assert resumed["version"] == suspended["version"] + 1, (
        f"version must increment by 1 on resume: {suspended['version']} -> {resumed['version']}"
    )


def test_grant_cycle_permits_second_suspend_after_resume(api):
    """PRD 3.2: "Suspending an award is the consequential cascade. It is permitted only from `ACTIVE` (otherwise `ERR_INVALID_STATE`, 409) and moves the award to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/nl_grant_active_suspended_cycle
    """
    grant = fixtures.create_active_grant(category="TRANSPORTATION", authorized_cents=5000)
    fixtures.suspend_grant(grant["id"])
    fixtures.activate_grant(grant["id"])  # resume to ACTIVE
    resuspended = validate_success(api.suspend_grant(grant["id"], ADMIN))
    assert resuspended["status"] == "SUSPENDED", (
        f"the ACTIVE<->SUSPENDED cycle must permit a second suspend, got {resuspended['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade/tc_grant_suspend_unfunds_services
# ---------------------------------------------------------------------------
def test_suspend_grant_reverses_its_applied_funded_service(api):
    """PRD 3.2: "It then reverses every one of that award's funded services whose `status` is `APPLIED`: each such row is set to `REVERSED`; the row's `grant_amount_cents` is returned to the award ...; the row's `funding_status` is set to `UNFUNDED`, its `grant_amount_cents` and `donation_amount_cents` are set to 0, and its `unfunded_amount_cents` is set to its `billable_cents`".

    Design: Difficulty/transitive_cascade/tc_grant_suspend_unfunds_services
    """
    ctx = fixtures.setup_active_grant_with_funded_service(authorized_cents=2000, quantity=1)
    fixtures.suspend_grant(ctx["grant"]["id"])
    grant_after = validate_success(api.get_grant(ctx["grant"]["id"], ADMIN))
    fs_after = validate_success(api.get_funded_service(ctx["funded_service"]["id"], ADMIN))
    assert grant_after["status"] == "SUSPENDED", f"expected SUSPENDED, got {grant_after['status']}"
    assert fs_after["status"] == "REVERSED", f"expected REVERSED, got {fs_after['status']}"
    assert fs_after["funding_status"] == "UNFUNDED", f"expected UNFUNDED, got {fs_after['funding_status']}"
    assert fs_after["grant_amount_cents"] == 0, f"expected 0, got {fs_after['grant_amount_cents']}"


def test_suspend_grant_cascade_returns_funds_to_grant_and_participant(api):
    """PRD 3.2: "the row's `grant_amount_cents` is returned to the award (the award's `committed_cents` decreases by that amount and its `available_cents` increases by the same amount) ...; and the recipient participant's `funded_cents` is decreased by that row's pre-reversal `grant_amount_cents` plus `donation_amount_cents`. This is a depth-three cascade from award to funded service to participant."

    Design: Difficulty/transitive_cascade/tc_grant_suspend_unfunds_services
    """
    ctx = fixtures.setup_active_grant_with_funded_service(authorized_cents=2000, quantity=1)
    fixtures.suspend_grant(ctx["grant"]["id"])
    grant_after = validate_success(api.get_grant(ctx["grant"]["id"], ADMIN))
    participant_after = validate_success(api.get_participant(ctx["participant"]["id"], ADMIN))
    assert grant_after["committed_cents"] == 0, f"expected 0, got {grant_after['committed_cents']}"
    assert grant_after["available_cents"] == 2000, f"expected 2000, got {grant_after['available_cents']}"
    assert participant_after["funded_cents"] == 0, f"expected 0, got {participant_after['funded_cents']}"
    assert_grant_conservation(grant_after)


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant/ci_grant_funds_conservation
# ---------------------------------------------------------------------------
def test_grant_conservation_holds_after_apply(api):
    """PRD 2.7: "A grant award obeys a conservation invariant at all times: its `authorized_cents` equals its `committed_cents` plus its `available_cents`. Committing funds moves cents from available to committed; reversing or suspending returns them."

    Design: Difficulty/compensating_invariant/ci_grant_funds_conservation
    """
    ctx = fixtures.setup_active_grant_with_funded_service(authorized_cents=2000, quantity=1)
    grant_after = validate_success(api.get_grant(ctx["grant"]["id"], ADMIN))
    assert grant_after["committed_cents"] == 1500, f"expected 1500, got {grant_after['committed_cents']}"
    assert grant_after["available_cents"] == 500, f"expected 500, got {grant_after['available_cents']}"
    assert grant_after["authorized_cents"] == 2000, f"expected 2000, got {grant_after['authorized_cents']}"
    assert_grant_conservation(grant_after)


def test_grant_conservation_holds_after_reverse(api):
    """PRD 3.3: "The row is then zeroed: `grant_amount_cents` and `donation_amount_cents` become 0, `unfunded_amount_cents` becomes the row's `billable_cents`, `funding_status` becomes `UNFUNDED`, and the row moves to `REVERSED`. This preserves each grant's conservation identity of `authorized_cents` equal to `committed_cents` plus `available_cents`."

    Design: Difficulty/compensating_invariant/ci_grant_funds_conservation
    """
    ctx = fixtures.setup_active_grant_with_funded_service(authorized_cents=2000, quantity=1)
    reversed_fs = validate_success(api.reverse_funded_service(ctx["funded_service"]["id"], COORD))
    assert reversed_fs["status"] == "REVERSED", f"expected REVERSED, got {reversed_fs['status']}"
    grant_after = validate_success(api.get_grant(ctx["grant"]["id"], ADMIN))
    assert grant_after["committed_cents"] == 0, f"expected 0, got {grant_after['committed_cents']}"
    assert grant_after["available_cents"] == 2000, f"expected 2000, got {grant_after['available_cents']}"
    assert grant_after["authorized_cents"] == 2000, f"expected 2000, got {grant_after['authorized_cents']}"
    assert_grant_conservation(grant_after)


# ---------------------------------------------------------------------------
# Queue B — reversal / activation state machine
# ---------------------------------------------------------------------------
def test_reverse_already_reversed_funded_service_rejected(api):
    """PRD 3.3: "Reversing a funded service is its compensating action, available to a `CenterAdmin` or `Coordinator` and permitted only while the row's `status` is `APPLIED` (otherwise `ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/corner_reverse_already_reversed_funded_service_invalid_state
    """
    ctx = fixtures.setup_active_grant_with_funded_service(authorized_cents=2000, quantity=1)
    fixtures.reverse_service(ctx["funded_service"]["id"])
    resp = api.reverse_funded_service(ctx["funded_service"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_already_active_grant_rejected(api):
    """PRD 3.2: "Activating an award moves it into `ACTIVE`: this same activation capability serves both the initial `DRAFT → ACTIVE` transition and the `SUSPENDED → ACTIVE` resume, closing the `ACTIVE ↔ SUSPENDED` cycle." PRD 2.6: "the target resource is in a state that permits the transition (for example, a grant is `ACTIVE` before it can fund, a meal day is `OPEN` before it can take reservations, a participant is `ACTIVE` for self-service writes), else the applicable state error (HTTP 409)."

    Design: Corner/state_machines/corner_activate_already_active_grant_invalid_state
    """
    grant = fixtures.create_active_grant(category="CONGREGATE_MEAL", authorized_cents=3000)
    resp = api.activate_grant(grant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
