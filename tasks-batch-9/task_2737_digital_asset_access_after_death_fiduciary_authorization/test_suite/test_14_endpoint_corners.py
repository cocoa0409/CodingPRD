"""
Endpoint corners of the Digital Estate Fiduciary Access API.

Two endpoints in this contract are easy to conflate with the state they read.
A provider policy update rewrites the provider's own row and nothing else, so an
account's stored transferability only ever moves when a transferability review
is posted against that account. And the authority-resolution projection
re-resolves the precedence ladder on every call while an authority grant keeps
the scope it froze at decision time.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    factories as f,
    fixtures as fx,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_CONTENT_DISCLOSED,
    BASIS_ONLINE_TOOL,
    BASIS_WILL_PROVISION,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_LOYALTY_PROGRAM,
    CATEGORY_SUBSCRIPTION,
    CLAMP_NONE,
    CLOCK_EPOCH,
    DIRECTIVE_ONLINE_TOOL,
    GRANT_ACTIVE,
    LICENSE_TERMINATES_AT_DEATH,
    NON_TRANSFERABLE,
    REASON_CATEGORY_SUBSCRIPTION_LICENCE,
    REASON_PROVIDER_LICENCE_TERMINATES,
    REASON_PROVIDER_NO_TRANSFER,
    REASON_TRANSFERABLE_PROPERTY,
    REQUEST_TYPE_CONTENT_ACCESS,
    ROLE_COURT_REGISTRAR,
    ROLE_ESTATE_ADMIN,
    ROLE_FIDUCIARY,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_NONE,
    TRANSFERABLE,
)


def _cloud_estate_with_three_accounts(api, case_number):
    """A cloud provider, an authorized estate and three accounts of one provider."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, case_number)
    vault = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=200000,
    )
    points = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_LOYALTY_PROGRAM, account_handle="points-1",
        quoted_value_cents=40000, loyalty_points=20000,
    )
    sub = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_SUBSCRIPTION, account_handle="sub-1", quoted_value_cents=0,
    )
    return platform, ctx, vault, points, sub


def test_a_platform_policy_update_reclassifies_no_existing_account(api):
    """
    A cloud account inventoried while the provider's licence survives death is
    TRANSFERABLE. Flipping the provider's license_terminates_at_death flag by
    PATCH leaves that account's stored classification, and its version, exactly
    where they were: the provider row moved, the account row did not.

    PRD §3.1: Such an update is deliberately **not** retroactive: it does not rewrite any cancellation order's `refund_policy_snapshot`, does not touch the resolved scope already frozen onto a decided request, and does not reclassify any account that has already been classified.

    Design: Corner/endpoints/transferability_is_reclassified_only_when_a_review_is_posted
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C31A")
    vault = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=200000,
    )
    assert vault["transferability"] == TRANSFERABLE
    assert vault["transferability_reason"] == REASON_TRANSFERABLE_PROPERTY

    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    before = fx.read_asset(api, ctx, vault["id"])
    assert before["access_status"] == ACCESS_CATALOG_DISCLOSED

    fx.patch_platform(api, platform["id"], license_terminates_at_death=True)

    after = fx.read_asset(api, ctx, vault["id"])
    assert after["transferability"] == TRANSFERABLE
    assert after["transferability_reason"] == REASON_TRANSFERABLE_PROPERTY
    assert after["version"] == before["version"]
    assert after["access_status"] == ACCESS_CATALOG_DISCLOSED


def test_a_transferability_review_reclassifies_but_keeps_the_appraisal(api):
    """
    Posting a transferability review after the provider's licence terms changed
    answers HTTP 200, rewrites the class to LICENSE_TERMINATES_AT_DEATH with
    reason PROVIDER_LICENCE_TERMINATES, keeps the appraised value the valuation
    run wrote, keeps the disclosure posture and advances the account's version by
    exactly one. The loyalty account on the same provider is untouched by the
    licence flag, because rule three reaches CLOUD_STORAGE only.

    PRD §3.4: The review re-runs the same six-rule chain against the provider's *current* flags and rewrites `transferability` and `transferability_reason`. It deliberately does **not** clear an existing `appraised_value_cents`: an account that has just been reclassified out of `TRANSFERABLE` keeps the appraisal it already carries until a fresh valuation run replaces it. The review advances the account's `version`.

    Design: Corner/endpoints/transferability_is_reclassified_only_when_a_review_is_posted
    """
    platform, ctx, vault, points, sub = _cloud_estate_with_three_accounts(api, "PR-2737-C31B")
    assert points["transferability"] == TRANSFERABLE
    assert sub["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert sub["transferability_reason"] == REASON_CATEGORY_SUBSCRIPTION_LICENCE

    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives", relationship="child")
    run = fx.computed_valuation_run(api, ctx)
    assert run["gross_value_cents"] == 240000
    assert run["included_asset_count"] == 2

    before = fx.read_asset(api, ctx, vault["id"])
    assert before["appraised_value_cents"] == 200000
    assert before["access_status"] == ACCESS_CATALOG_DISCLOSED

    fx.patch_platform(api, platform["id"], license_terminates_at_death=True)

    reviewed = validate_success(
        api.create_transferability_review(
            vault["id"],
            f.transferability_review_payload(review_note="provider licence now terminates at death"),
            ctx.fid_headers,
        ),
        200,
    )
    assert reviewed["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert reviewed["transferability_reason"] == REASON_PROVIDER_LICENCE_TERMINATES
    assert reviewed["appraised_value_cents"] == 200000
    assert reviewed["access_status"] == ACCESS_CATALOG_DISCLOSED
    assert reviewed["version"] == before["version"] + 1

    loyalty = validate_success(
        api.create_transferability_review(
            points["id"],
            f.transferability_review_payload(review_note="loyalty programme re-checked"),
            ctx.fid_headers,
        ),
        200,
    )
    assert loyalty["transferability"] == TRANSFERABLE
    assert loyalty["transferability_reason"] == REASON_TRANSFERABLE_PROPERTY


def test_one_withdrawn_transfer_flag_splits_three_categories_on_review(api):
    """
    After the provider withdraws transfers and its licence flag is off, three
    accounts of the same provider reviewed one after another stop at three
    different rules: the cloud account falls past rule three to rule five and is
    NON_TRANSFERABLE / PROVIDER_NO_TRANSFER, the loyalty account stops at rule
    four with PROVIDER_LICENCE_TERMINATES, and the subscription account never
    gets past rule two, so its reason stays CATEGORY_SUBSCRIPTION_LICENCE.

    PRD §3.4: Rule four: an account whose `category` is `LOYALTY_PROGRAM` on a provider whose `supports_transfer` is false is `LICENSE_TERMINATES_AT_DEATH`, also with reason `PROVIDER_LICENCE_TERMINATES`.

    PRD §3.4: A `SUBSCRIPTION` account on a provider whose `supports_transfer` is false stops at rule two, so its reason is `CATEGORY_SUBSCRIPTION_LICENCE` and never `PROVIDER_NO_TRANSFER`. Conversely, a `CLOUD_STORAGE` account on a provider whose `license_terminates_at_death` is false but whose `supports_transfer` is also false falls past rule three and stops at rule five, so it is `NON_TRANSFERABLE` with reason `PROVIDER_NO_TRANSFER` rather than a terminating licence.

    Design: Corner/endpoints/transferability_is_reclassified_only_when_a_review_is_posted
    """
    platform, ctx, vault, points, sub = _cloud_estate_with_three_accounts(api, "PR-2737-C31C")

    fx.patch_platform(
        api, platform["id"], license_terminates_at_death=False, supports_transfer=False
    )

    reviewed_vault = validate_success(
        api.create_transferability_review(
            vault["id"],
            f.transferability_review_payload(review_note="provider withdrew transfers"),
            ctx.fid_headers,
        ),
        200,
    )
    assert reviewed_vault["transferability"] == NON_TRANSFERABLE
    assert reviewed_vault["transferability_reason"] == REASON_PROVIDER_NO_TRANSFER

    reviewed_points = validate_success(
        api.create_transferability_review(
            points["id"],
            f.transferability_review_payload(review_note="loyalty programme re-checked again"),
            ctx.fid_headers,
        ),
        200,
    )
    assert reviewed_points["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert reviewed_points["transferability_reason"] == REASON_PROVIDER_LICENCE_TERMINATES

    reviewed_sub = validate_success(
        api.create_transferability_review(
            sub["id"],
            f.transferability_review_payload(review_note="subscription re-checked"),
            ctx.fid_headers,
        ),
        200,
    )
    assert reviewed_sub["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert reviewed_sub["transferability_reason"] == REASON_CATEGORY_SUBSCRIPTION_LICENCE


def _estate_with_a_will_directive(api, case_number):
    """A cloud provider, an authorized estate, a catch-all will provision, one account."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, case_number)
    directive = fx.add_directive(api, ctx, instrument_reference="Will article 9.1")
    vault = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=200000,
    )
    return platform, ctx, directive, vault


def test_the_authority_resolution_projection_writes_nothing(api):
    """
    The projection echoes back the triple it was asked about together with the
    winner of the precedence ladder — a catch-all will provision granting
    CATALOG_AND_CONTENT on a provider that needs no court order — and calling it
    twice leaves the estate's version exactly where it was.

    PRD §3.3: It runs in four steps and is exposed both as a read-only projection — available to a `Fiduciary`, a `CourtRegistrar` or an `EstateAdmin`, taking a `platform_id` and an optional `asset_category` and echoing back `estate_id`, `platform_id`, `asset_category`, `resolved_scope`, `resolved_basis`, `clamp_reason` and `controlling_directive_id` without changing any state — and as the engine behind a request package's submission gate and its frozen decision, described in §3.5.

    PRD §3.3: The `clamp_reason` starts at `NONE`.

    Design: Corner/endpoints/the_authority_projection_stays_live_while_the_granted_scope_stays_frozen
    """
    platform, ctx, directive, _vault = _estate_with_a_will_directive(api, "PR-2737-C32A")

    first = validate_success(
        api.get_authority_resolution(
            ctx.estate_id, COURT_REGISTRAR_HEADERS, platform_id=platform["id"]
        ),
        200,
    )
    assert first["estate_id"] == ctx.estate_id
    assert first["platform_id"] == platform["id"]
    assert first["asset_category"] is None
    assert first["resolved_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert first["resolved_basis"] == BASIS_WILL_PROVISION
    assert first["clamp_reason"] == CLAMP_NONE
    assert first["controlling_directive_id"] == directive["id"]

    version_before = fx.read_estate(api, ctx)["version"]

    second = validate_success(
        api.get_authority_resolution(
            ctx.estate_id, ctx.fid_headers, platform_id=platform["id"]
        ),
        200,
    )
    assert second["resolved_scope"] == first["resolved_scope"]
    assert second["resolved_basis"] == first["resolved_basis"]
    assert second["controlling_directive_id"] == first["controlling_directive_id"]

    assert fx.read_estate(api, ctx)["version"] == version_before


def test_a_grant_keeps_the_scope_the_projection_has_already_moved_past(api):
    """
    The approval freezes CATALOG_AND_CONTENT onto both the decided request and
    the grant it creates, opening the grant ACTIVE from the clock instant and
    expiring it ninety days later. Recording a rank-1 online-tool directive with
    scope NONE afterwards flips the live projection to NONE / ONLINE_TOOL, yet
    the grant still reads CATALOG_AND_CONTENT and the account it disclosed stays
    CONTENT_DISCLOSED.

    PRD §3.6: A grant records the `estate_id` and `platform_id` it covers and the `platform_request_id` that produced it, freezes the `granted_scope` and `basis` that the resolution of §3.3 produced at decision time along with the `clamp_reason` that resolution carried, opens its `status` at `ACTIVE`, sets `effective_from` to the current clock instant and `expires_at` to that instant advanced by 90 days, and leaves `revocation_reason` null.

    PRD §3.3: The first key is `precedence_rank` ascending, so rank 1 — the online tool — beats rank 2 even when the will grants a wider scope.

    Design: Corner/endpoints/the_authority_projection_stays_live_while_the_granted_scope_stays_frozen
    """
    platform, ctx, directive, vault = _estate_with_a_will_directive(api, "PR-2737-C32B")

    request = fx.draft_request(
        api, ctx, platform["id"], platform["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS, requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )
    fx.submit_request(api, ctx, request["id"])
    fx.start_review(api, platform["id"], request["id"])
    decided = fx.decide_request(
        api, platform["id"], request["id"], decision_note="content released"
    )
    assert decided["resolved_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert decided["resolved_basis"] == BASIS_WILL_PROVISION
    assert decided["clamp_reason"] == CLAMP_NONE

    grant = fx.grant_for_request(api, ctx, request["id"])
    assert grant["granted_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert grant["clamp_reason"] == CLAMP_NONE
    assert grant["status"] == GRANT_ACTIVE
    assert grant["revocation_reason"] is None
    assert grant["effective_from"].startswith("2026-08-01")
    assert grant["expires_at"].startswith("2026-10-30")

    online_tool = fx.add_directive(
        api, ctx,
        directive_type=DIRECTIVE_ONLINE_TOOL,
        scope=SCOPE_NONE,
        platform_id=platform["id"],
        instrument_reference="provider legacy-contact page, opted out",
        executed_on="2025-11-30",
    )

    reprojected = validate_success(
        api.get_authority_resolution(
            ctx.estate_id, ctx.fid_headers, platform_id=platform["id"]
        ),
        200,
    )
    assert reprojected["resolved_scope"] == SCOPE_NONE
    assert reprojected["resolved_basis"] == BASIS_ONLINE_TOOL
    assert reprojected["controlling_directive_id"] == online_tool["id"]
    assert reprojected["controlling_directive_id"] != directive["id"]

    frozen = fx.read_grant(api, ctx, grant["id"])
    assert frozen["granted_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert frozen["status"] == GRANT_ACTIVE

    assert fx.read_asset(api, ctx, vault["id"])["access_status"] == ACCESS_CONTENT_DISCLOSED


@pytest.mark.parametrize("role", [ROLE_FIDUCIARY, ROLE_COURT_REGISTRAR, ROLE_ESTATE_ADMIN])
def test_the_authority_resolution_projection_answers_200_for_its_three_roles(api, role):
    """
    The projection is open to a fiduciary, the registry and the service operator
    alike, and each of them reads the same resolved triple at HTTP 200.

    PRD §3.3: It runs in four steps and is exposed both as a read-only projection — available to a `Fiduciary`, a `CourtRegistrar` or an `EstateAdmin`, taking a `platform_id` and an optional `asset_category` and echoing back `estate_id`, `platform_id`, `asset_category`, `resolved_scope`, `resolved_basis`, `clamp_reason` and `controlling_directive_id` without changing any state — and as the engine behind a request package's submission gate and its frozen decision, described in §3.5.

    Design: Corner/endpoints/the_authority_projection_stays_live_while_the_granted_scope_stays_frozen
    """
    platform, ctx, directive, _vault = _estate_with_a_will_directive(api, "PR-2737-C32C")

    headers = {
        ROLE_FIDUCIARY: ctx.fid_headers,
        ROLE_COURT_REGISTRAR: COURT_REGISTRAR_HEADERS,
        ROLE_ESTATE_ADMIN: ESTATE_ADMIN_HEADERS,
    }[role]

    projected = validate_success(
        api.get_authority_resolution(ctx.estate_id, headers, platform_id=platform["id"]),
        200,
    )
    assert projected["resolved_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert projected["resolved_basis"] == BASIS_WILL_PROVISION
    assert projected["clamp_reason"] == CLAMP_NONE
    assert projected["controlling_directive_id"] == directive["id"]
