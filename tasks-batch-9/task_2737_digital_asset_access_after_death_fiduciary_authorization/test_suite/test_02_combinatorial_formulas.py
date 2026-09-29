"""
Combinatorial formulas of the Digital Estate Fiduciary Access API.

Three outcomes in this contract are each a function of several inputs drawn
from several entities, and no single input predicts the answer:

  * the resolved authority scope, which combines a directive's precedence rank,
    its platform and category specificity, the provider's court-order policy
    and the existence of a verified court order;
  * the estate roll-up, which combines per-asset quotes, per-provider transfer
    fees, the gross-keyed deduction tier and the summed request fees of the
    approved request packages; and
  * the transferability class, where an ordered six-rule chain means the rule
    that matches *first* decides both the class and its reason.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    BASIS_DATE_OF_DEATH,
    BASIS_ONLINE_TOOL,
    BASIS_TRUST_PROVISION,
    BASIS_WILL_PROVISION,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_EMAIL,
    CATEGORY_FINANCIAL_ACCOUNT,
    CATEGORY_LOYALTY_PROGRAM,
    CATEGORY_SOCIAL_PROFILE,
    CATEGORY_SUBSCRIPTION,
    CLAMP_COURT_ORDER_REQUIRED,
    CLAMP_NONE,
    BILLING_ACTIVE,
    BILLING_NOT_APPLICABLE,
    DIRECTIVE_ONLINE_TOOL,
    DIRECTIVE_TRUST_PROVISION,
    DIRECTIVE_WILL_PROVISION,
    LICENSE_TERMINATES_AT_DEATH,
    NON_TRANSFERABLE,
    PRECEDENCE_RANK_INSTRUMENT,
    PRECEDENCE_RANK_ONLINE_TOOL,
    REASON_CATEGORY_PERSONAL,
    REASON_CATEGORY_SUBSCRIPTION_LICENCE,
    REASON_PROVIDER_LICENCE_TERMINATES,
    REASON_PROVIDER_NO_TRANSFER,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_CATALOG_ONLY,
    TRANSFERABLE,
)


# ─── Instance: the authority precedence ladder ───────────────────────────────
def _three_provider_directive_estate(api, case_number):
    """
    Three providers with different online-tool and court-order policies, and the
    same three RECORDED directives over one estate: a catch-all will provision
    granting content, a SOCIAL_PROFILE-scoped trust provision granting the
    catalogue only, and a CloudVault-scoped online-tool designation granting
    the catalogue only.
    """
    fx.set_clock(api)
    cloud = fx.register_platform(
        api,
        name="CloudVault",
        form_code="CV-FORM-1",
        supports_online_tool=True,
        requires_court_order_for_content=False,
    )
    social = fx.register_social_platform(
        api,
        name="SocialHub",
        form_code="SH-FORM-6",
        supports_online_tool=False,
        requires_court_order_for_content=False,
    )
    bank = fx.register_financial_platform(
        api,
        name="BankTrust",
        form_code="BT-FORM-2",
        supports_online_tool=True,
        requires_court_order_for_content=True,
    )
    ctx = fx.authorized_estate(api, case_number, date_of_death="2026-02-14")

    will = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_WILL_PROVISION,
        scope=SCOPE_CATALOG_AND_CONTENT,
        instrument_reference="WILL-ART-7",
        executed_on="2026-03-05",
    )
    trust = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_TRUST_PROVISION,
        scope=SCOPE_CATALOG_ONLY,
        asset_category=CATEGORY_SOCIAL_PROFILE,
        instrument_reference="TRUST-SEC-4",
        executed_on="2026-03-06",
    )
    tool = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_ONLINE_TOOL,
        scope=SCOPE_CATALOG_ONLY,
        platform_id=cloud["id"],
        instrument_reference="CV-LEGACY-CONTACT",
        executed_on="2026-03-07",
    )
    return ctx, {"cloud": cloud, "social": social, "bank": bank}, {
        "will": will,
        "trust": trust,
        "tool": tool,
    }


def _resolve(api, ctx, platform_id, asset_category=None):
    return validate_success(
        api.get_authority_resolution(
            ctx.estate_id,
            ctx.fiduciary_headers,
            platform_id=platform_id,
            asset_category=asset_category,
        ),
        200,
    )


def test_rank_one_online_tool_beats_a_will_that_grants_a_wider_scope(api):
    """
    Resolving against CloudVault with no category supplied narrows the candidate
    set to the two directives whose asset_category is null, and the online-tool
    designation's rank of 1 wins over the will's rank of 2 even though the will
    grants CATALOG_AND_CONTENT and the online tool only CATALOG_ONLY.

    "`precedence_rank` is never client-supplied: it is 1 for an `ONLINE_TOOL` directive and 2 for both `WILL_PROVISION` and `TRUST_PROVISION`, and a lower rank wins."

    "Its category binding matches when its `asset_category` is null or equals the target category — and when the caller supplies no category at all, only directives whose `asset_category` is null are candidates."

    "The first key is `precedence_rank` ascending, so rank 1 — the online tool — beats rank 2 even when the will grants a wider scope."

    "The first directive after that sort is the winner and its `id` is the `controlling_directive_id`."

    "When there is a winner, the base scope is that directive's own `scope` — which may be `NONE`, `CATALOG_ONLY` or `CATALOG_AND_CONTENT` — and the basis is `ONLINE_TOOL`, `WILL_PROVISION` or `TRUST_PROVISION` according to the winner's `directive_type`."

    Design: Difficulty/combinatorial_formula/authority_precedence_combines_rank_specificity_category_and_court_order_clamp
    """
    ctx, platforms, directives = _three_provider_directive_estate(api, "PR-2737-C1")

    assert directives["will"]["precedence_rank"] == PRECEDENCE_RANK_INSTRUMENT
    assert directives["trust"]["precedence_rank"] == PRECEDENCE_RANK_INSTRUMENT
    assert directives["tool"]["precedence_rank"] == PRECEDENCE_RANK_ONLINE_TOOL

    resolution = _resolve(api, ctx, platforms["cloud"]["id"])

    assert resolution["resolved_scope"] == SCOPE_CATALOG_ONLY
    assert resolution["resolved_basis"] == BASIS_ONLINE_TOOL
    assert resolution["clamp_reason"] == CLAMP_NONE
    assert resolution["controlling_directive_id"] == directives["tool"]["id"]


def test_specificity_breaks_the_rank_tie_only_when_a_category_is_supplied(api):
    """
    Against SocialHub both rank-2 directives are candidates when the caller
    supplies SOCIAL_PROFILE, and the category-bound trust provision's
    specificity of 1 beats the catch-all will's 0 so the scope narrows to
    CATALOG_ONLY; omitting the category drops the trust provision out of the
    candidate set entirely and the same three directives now resolve to the
    will's CATALOG_AND_CONTENT.

    "Its platform binding matches when its `platform_id` is null or equals the target provider."

    "Its category binding matches when its `asset_category` is null or equals the target category — and when the caller supplies no category at all, only directives whose `asset_category` is null are candidates."

    "The second key is specificity descending, where a directive bound to a specific provider scores 2, a directive with a null `platform_id` but a non-null `asset_category` scores 1, and a catch-all with both null scores 0."

    "When there is a winner, the base scope is that directive's own `scope` — which may be `NONE`, `CATALOG_ONLY` or `CATALOG_AND_CONTENT` — and the basis is `ONLINE_TOOL`, `WILL_PROVISION` or `TRUST_PROVISION` according to the winner's `directive_type`."

    Design: Difficulty/combinatorial_formula/authority_precedence_combines_rank_specificity_category_and_court_order_clamp
    """
    ctx, platforms, directives = _three_provider_directive_estate(api, "PR-2737-C2")

    filtered = _resolve(
        api, ctx, platforms["social"]["id"], asset_category=CATEGORY_SOCIAL_PROFILE
    )
    assert filtered["resolved_scope"] == SCOPE_CATALOG_ONLY
    assert filtered["resolved_basis"] == BASIS_TRUST_PROVISION
    assert filtered["controlling_directive_id"] == directives["trust"]["id"]

    unfiltered = _resolve(api, ctx, platforms["social"]["id"])
    assert unfiltered["resolved_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert unfiltered["resolved_basis"] == BASIS_WILL_PROVISION
    assert unfiltered["controlling_directive_id"] == directives["will"]["id"]


def test_court_order_clamp_narrows_the_winning_scope_until_an_order_is_verified(api):
    """
    Against BankTrust the catch-all will provision wins on rank and specificity
    with a base scope of CATALOG_AND_CONTENT, but the provider demands a court
    order for content and the estate has none, so the scope is clamped to
    CATALOG_ONLY with clamp_reason COURT_ORDER_REQUIRED; verifying a COURT_ORDER
    document lifts the clamp and the same directives now resolve to
    CATALOG_AND_CONTENT with clamp_reason NONE.

    "If and only if the base scope came out as `CATALOG_AND_CONTENT` *and* the provider's `requires_court_order_for_content` is true, the server looks for a `COURT_ORDER` document on the estate whose `verification_status` is `VERIFIED`."

    "If no such document exists, the base scope is narrowed to `CATALOG_ONLY` and the `clamp_reason` becomes `COURT_ORDER_REQUIRED`."

    "If such a document does exist, the scope stands and the reason stays `NONE`."

    Design: Difficulty/combinatorial_formula/authority_precedence_combines_rank_specificity_category_and_court_order_clamp
    """
    ctx, platforms, directives = _three_provider_directive_estate(api, "PR-2737-C3")

    clamped = _resolve(api, ctx, platforms["bank"]["id"])
    assert clamped["resolved_scope"] == SCOPE_CATALOG_ONLY
    assert clamped["resolved_basis"] == BASIS_WILL_PROVISION
    assert clamped["clamp_reason"] == CLAMP_COURT_ORDER_REQUIRED
    assert clamped["controlling_directive_id"] == directives["will"]["id"]

    order_doc = fx.add_document(
        api,
        ctx.estate_id,
        f.court_order_document_payload(reference_number="CO-1", issued_on="2026-07-01"),
    )
    fx.verify_document(api, order_doc["id"])

    lifted = _resolve(api, ctx, platforms["bank"]["id"])
    assert lifted["resolved_scope"] == SCOPE_CATALOG_AND_CONTENT
    assert lifted["resolved_basis"] == BASIS_WILL_PROVISION
    assert lifted["clamp_reason"] == CLAMP_NONE
    assert lifted["controlling_directive_id"] == directives["will"]["id"]


# ─── Instance: the estate roll-up across three provider fee profiles ─────────
BANK_QUOTE_CENTS = 1250033
CLOUD_QUOTE_CENTS = 400000
SKY_QUOTE_CENTS = 300000
BANK_APPRAISAL_CENTS = 1247533
CLOUD_APPRAISAL_CENTS = 400000
SKY_APPRAISAL_CENTS = 292500
ROLLUP_GROSS_CENTS = 1940033
ROLLUP_ADMIN_DEDUCTION_CENTS = 32000
ROLLUP_TAXABLE_CENTS = 1908033


def _three_profile_disclosed_estate(api, case_number):
    """
    Three providers with three different fee profiles, one transferable account
    on each, all three disclosed by their own approved catalogue request, and
    one beneficiary holding the whole estate.
    """
    fx.set_clock(api)
    bank = fx.register_financial_platform(
        api,
        name="BankTrust",
        form_code="BT-FORM-2",
        requires_court_order_for_content=False,
        supports_transfer=True,
        transfer_fee_cents=2500,
        request_fee_cents=30000,
    )
    cloud = fx.register_platform(
        api,
        name="CloudVault",
        form_code="CV-FORM-1",
        supports_transfer=True,
        license_terminates_at_death=False,
        transfer_fee_cents=0,
        request_fee_cents=0,
    )
    sky = fx.register_loyalty_platform(
        api,
        name="SkyMiles",
        form_code="SM-FORM-3",
        supports_transfer=True,
        license_terminates_at_death=False,
        transfer_fee_cents=7500,
        request_fee_cents=2000,
    )
    ctx = fx.authorized_estate(api, case_number, date_of_death="2026-02-14")

    bank_asset = fx.add_asset(
        api,
        ctx,
        bank["id"],
        category=CATEGORY_FINANCIAL_ACCOUNT,
        account_handle="bt-checking-4417",
        quoted_value_cents=BANK_QUOTE_CENTS,
    )
    cloud_asset = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-archive",
        quoted_value_cents=CLOUD_QUOTE_CENTS,
    )
    sky_asset = fx.add_asset(
        api,
        ctx,
        sky["id"],
        category=CATEGORY_LOYALTY_PROGRAM,
        account_handle="sky-9921",
        quoted_value_cents=SKY_QUOTE_CENTS,
        loyalty_points=120000,
    )
    beneficiary = fx.add_beneficiary(
        api, ctx, beneficiary_name="Ives Family Trust", share_bp=10000
    )
    for platform in (bank, cloud, sky):
        fx.approved_request(api, ctx, platform["id"], platform["form_code"])

    for asset in (bank_asset, cloud_asset, sky_asset):
        read = fx.read_asset(api, ctx, asset["id"])
        assert read["transferability"] == TRANSFERABLE, (
            f"Setup expected TRANSFERABLE, got {read['transferability']!r}"
        )

    return ctx, {"bank": bank_asset, "cloud": cloud_asset, "sky": sky_asset}, beneficiary


def test_each_appraisal_nets_its_own_providers_transfer_fee_before_the_gross(api):
    """
    On the DATE_OF_DEATH basis each of the three disclosed transferable accounts
    keeps its own quote and loses only its own provider's transfer fee — 2500 at
    BankTrust, 0 at CloudVault, 7500 at SkyMiles — so 1250033, 400000 and 300000
    appraise at 1247533, 400000 and 292500 and the run's gross is their sum.

    "Under `DATE_OF_DEATH` the gross is the account's `quoted_value_cents` exactly, with no adjustment."

    "From the gross the provider's `transfer_fee_cents` is then subtracted — the fee the provider charges to move the account to a beneficiary — and the result is floored at zero, so an account whose transfer fee exceeds its decayed gross appraises at 0 rather than a negative number."

    "`gross_value_cents` is the sum of the `appraised_value_cents` of the included accounts and `included_asset_count` is how many there were."

    Design: Difficulty/combinatorial_formula/estate_rollup_combines_three_platform_fee_and_decay_profiles_with_tiered_cap
    """
    ctx, assets, _beneficiary = _three_profile_disclosed_estate(api, "PR-2737-D1")

    run = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(fx.estate_version(api, ctx), basis=BASIS_DATE_OF_DEATH),
            ctx.fiduciary_headers,
        ),
        201,
    )

    assert fx.read_asset(api, ctx, assets["bank"]["id"])["appraised_value_cents"] == (
        BANK_APPRAISAL_CENTS
    )
    assert fx.read_asset(api, ctx, assets["cloud"]["id"])["appraised_value_cents"] == (
        CLOUD_APPRAISAL_CENTS
    )
    assert fx.read_asset(api, ctx, assets["sky"]["id"])["appraised_value_cents"] == (
        SKY_APPRAISAL_CENTS
    )

    assert run["included_asset_count"] == 3
    assert run["gross_value_cents"] == ROLLUP_GROSS_CENTS


def test_the_gross_selects_the_middle_tier_cap_while_approved_request_fees_set_the_cost(api):
    """
    The gross of 1940033 cents sits at or above 500000 but below 5000000, so the
    deduction cap is 150000 rather than 25000; the actual administrative costs
    are the summed request fees of the three approved packages — 30000 + 0 +
    2000 = 32000 — with no pursuit costs, and the smaller of the two is
    deducted, leaving a taxable digital estate of 1908033 cents mirrored onto
    the estate together with the whole gross planned for the sole beneficiary.

    "The administrative-expense deduction is capped by a tier selected **from the gross**, never from the post-deduction figure: a gross below 500000 selects a `deduction_cap_cents` of 25000, a gross below 5000000 selects 150000, and any larger gross selects 400000."

    "The estate's actual administrative costs are the sum of the `request_fee_cents` of the providers behind every one of the estate's platform requests in `APPROVED` status, plus the sum of the `pursuit_cost_cents` of every refund claim of the estate regardless of that claim's status — the money was spent whether or not the claim succeeded."

    "`admin_deduction_cents` is the smaller of the cap and those actual costs, so a frugal estate deducts only what it spent while a costly one is held to its tier."

    "`taxable_value_cents` is the gross minus the deduction, floored at zero."

    "The three figures are mirrored onto the estate as `gross_digital_estate_cents`, `admin_deduction_cents` and `taxable_digital_estate_cents`, the estate's `valuation_basis` mirrors the basis of its newest `COMPUTED` or `FINALIZED` run, and `undistributed_value_cents` is set to the gross minus the sum of `received_value_cents` across the estate's designations."

    "In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded."

    Design: Difficulty/combinatorial_formula/estate_rollup_combines_three_platform_fee_and_decay_profiles_with_tiered_cap
    """
    ctx, _assets, beneficiary = _three_profile_disclosed_estate(api, "PR-2737-D2")

    run = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(fx.estate_version(api, ctx), basis=BASIS_DATE_OF_DEATH),
            ctx.fiduciary_headers,
        ),
        201,
    )

    assert run["gross_value_cents"] == ROLLUP_GROSS_CENTS
    assert run["deduction_cap_cents"] == 150000
    assert run["admin_deduction_cents"] == ROLLUP_ADMIN_DEDUCTION_CENTS
    assert run["taxable_value_cents"] == ROLLUP_TAXABLE_CENTS

    estate = fx.read_estate(api, ctx)
    assert estate["gross_digital_estate_cents"] == ROLLUP_GROSS_CENTS
    assert estate["admin_deduction_cents"] == ROLLUP_ADMIN_DEDUCTION_CENTS
    assert estate["taxable_digital_estate_cents"] == ROLLUP_TAXABLE_CENTS
    assert estate["undistributed_value_cents"] == ROLLUP_GROSS_CENTS
    assert estate["valuation_basis"] == BASIS_DATE_OF_DEATH

    planned = fx.read_designation(api, ctx, beneficiary["id"])
    assert planned["planned_allocation_cents"] == ROLLUP_GROSS_CENTS


# ─── Instance: the ordered transferability chain ──────────────────────────────
def _lockvault_inventory(api, case_number):
    """
    One provider that refuses transfers and whose licence survives death, and
    four accounts on it whose categories send them to four different rules of
    the classification chain.
    """
    fx.set_clock(api)
    platform = fx.register_platform(
        api,
        name="LockVault",
        form_code="LV-FORM-8",
        supports_online_tool=False,
        supports_transfer=False,
        supports_memorialization=True,
        supports_deletion=True,
        requires_court_order_for_content=False,
        license_terminates_at_death=False,
        transfer_fee_cents=0,
        request_fee_cents=0,
    )
    ctx = fx.authorized_estate(api, case_number, date_of_death="2026-02-14")
    subscription = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_SUBSCRIPTION,
        account_handle="lv-plus-plan",
        quoted_value_cents=0,
    )
    cloud = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="lv-archive",
        quoted_value_cents=250000,
    )
    mail = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_EMAIL,
        account_handle="lv-mail",
        quoted_value_cents=0,
    )
    loyalty = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_LOYALTY_PROGRAM,
        account_handle="lv-points",
        quoted_value_cents=90000,
        loyalty_points=4500,
    )
    return ctx, platform, {
        "subscription": subscription,
        "cloud": cloud,
        "mail": mail,
        "loyalty": loyalty,
    }


def test_four_accounts_on_one_provider_stop_at_four_different_chain_rules(api):
    """
    All four accounts sit on the same provider — supports_transfer false,
    license_terminates_at_death false — yet the rule that matches first decides
    each one: the email account stops at rule one, the subscription at rule two
    so its reason is never PROVIDER_NO_TRANSFER, the loyalty programme at rule
    four, and the cloud-storage account falls past rule three to rule five and
    picks up exactly the reason the subscription never reaches.

    "Rule one: an account whose `category` is `EMAIL` or `SOCIAL_PROFILE` is `NON_TRANSFERABLE` with reason `CATEGORY_PERSONAL` — these are personal to the decedent and cannot be handed to anyone."

    "Rule four: an account whose `category` is `LOYALTY_PROGRAM` on a provider whose `supports_transfer` is false is `LICENSE_TERMINATES_AT_DEATH`, also with reason `PROVIDER_LICENCE_TERMINATES`."

    "A `SUBSCRIPTION` account on a provider whose `supports_transfer` is false stops at rule two, so its reason is `CATEGORY_SUBSCRIPTION_LICENCE` and never `PROVIDER_NO_TRANSFER`."

    "Conversely, a `CLOUD_STORAGE` account on a provider whose `license_terminates_at_death` is false but whose `supports_transfer` is also false falls past rule three and stops at rule five, so it is `NON_TRANSFERABLE` with reason `PROVIDER_NO_TRANSFER` rather than a terminating licence."

    "Its `subscription_billing_state` opens at `ACTIVE` when its `category` is `SUBSCRIPTION` and at `NOT_APPLICABLE` for every other category."

    Design: Difficulty/combinatorial_formula/transferability_chain_first_match_wins_over_later_matching_rule
    """
    _ctx, _platform, assets = _lockvault_inventory(api, "PR-2737-E1")

    assert assets["mail"]["transferability"] == NON_TRANSFERABLE
    assert assets["mail"]["transferability_reason"] == REASON_CATEGORY_PERSONAL

    assert assets["subscription"]["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert assets["subscription"]["transferability_reason"] == (
        REASON_CATEGORY_SUBSCRIPTION_LICENCE
    )

    assert assets["loyalty"]["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert assets["loyalty"]["transferability_reason"] == REASON_PROVIDER_LICENCE_TERMINATES

    assert assets["cloud"]["transferability"] == NON_TRANSFERABLE
    assert assets["cloud"]["transferability_reason"] == REASON_PROVIDER_NO_TRANSFER

    assert assets["subscription"]["subscription_billing_state"] == BILLING_ACTIVE
    assert assets["cloud"]["subscription_billing_state"] == BILLING_NOT_APPLICABLE
    assert assets["mail"]["subscription_billing_state"] == BILLING_NOT_APPLICABLE
    assert assets["loyalty"]["subscription_billing_state"] == BILLING_NOT_APPLICABLE


def test_a_transferability_review_moves_the_cloud_account_up_to_the_earlier_rule(api):
    """
    Flipping the provider's license_terminates_at_death to true reclassifies
    nothing on its own; only an explicit transferability review re-runs the
    chain, and now the cloud-storage account matches rule three instead of
    falling through to rule five, so its class stays LICENSE_TERMINATES_AT_DEATH
    with reason PROVIDER_LICENCE_TERMINATES while the un-reviewed subscription
    account keeps the reason rule two gave it.

    "Such an update is deliberately **not** retroactive: it does not rewrite any cancellation order's `refund_policy_snapshot`, does not touch the resolved scope already frozen onto a decided request, and does not reclassify any account that has already been classified."

    "The review re-runs the same six-rule chain against the provider's *current* flags and rewrites `transferability` and `transferability_reason`."

    "Rule three: an account whose `category` is `CLOUD_STORAGE` on a provider whose `license_terminates_at_death` is true is `LICENSE_TERMINATES_AT_DEATH` with reason `PROVIDER_LICENCE_TERMINATES`."

    "The review advances the account's `version`."

    Design: Difficulty/combinatorial_formula/transferability_chain_first_match_wins_over_later_matching_rule
    """
    ctx, platform, assets = _lockvault_inventory(api, "PR-2737-E2")

    cloud_id = assets["cloud"]["id"]
    before = fx.read_asset(api, ctx, cloud_id)
    assert before["transferability"] == NON_TRANSFERABLE
    assert before["transferability_reason"] == REASON_PROVIDER_NO_TRANSFER

    fx.patch_platform(api, platform["id"], license_terminates_at_death=True)

    unchanged = fx.read_asset(api, ctx, cloud_id)
    assert unchanged["transferability"] == NON_TRANSFERABLE
    assert unchanged["transferability_reason"] == REASON_PROVIDER_NO_TRANSFER
    assert unchanged["version"] == before["version"]

    reviewed = validate_success(
        api.create_transferability_review(
            cloud_id,
            f.transferability_review_payload(
                review_note="provider licence now terminates at death"
            ),
            ctx.fiduciary_headers,
        ),
        200,
    )
    assert reviewed["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert reviewed["transferability_reason"] == REASON_PROVIDER_LICENCE_TERMINATES
    assert reviewed["version"] == before["version"] + 1

    still_rule_two = fx.read_asset(api, ctx, assets["subscription"]["id"])
    assert still_rule_two["transferability"] == LICENSE_TERMINATES_AT_DEATH
    assert still_rule_two["transferability_reason"] == REASON_CATEGORY_SUBSCRIPTION_LICENCE
