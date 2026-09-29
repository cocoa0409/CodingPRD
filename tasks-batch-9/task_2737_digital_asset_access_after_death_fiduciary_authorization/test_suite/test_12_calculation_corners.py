"""
Calculation corners of the Digital Estate Fiduciary Access API.

Each test here builds its own world from an empty database whose logical clock
sits at the fresh-server epoch and then pins one arithmetic or resolution result
to the exact figure the contract derives: the precedence ladder's outcome, the
per-account disclosure level, the appraisal roll-up, the alternate-date decay,
the refund entitlement and the administrative deduction. Every money figure is
an integer number of cents and is recomputed here from the contract's own
formula rather than copied from an implementation.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    assert_fields,
    assert_null_fields,
    factories as f,
    fixtures as fx,
)
from test_helpers.api_errors import (
    ERR_ALTERNATE_DATE_NOT_REACHED,
    ERR_ONLINE_TOOL_UNSUPPORTED,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_CONTENT_DISCLOSED,
    ACCESS_UNVERIFIED,
    BASIS_ALTERNATE,
    BASIS_DATE_OF_DEATH,
    BASIS_ONLINE_TOOL,
    BASIS_STATUTORY_DEFAULT,
    BASIS_WILL_PROVISION,
    BILLING_INTERVAL_ANNUAL,
    BILLING_INTERVAL_MONTHLY,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_EMAIL,
    CATEGORY_FINANCIAL_ACCOUNT,
    CATEGORY_LOYALTY_PROGRAM,
    CATEGORY_SOCIAL_PROFILE,
    CLAIM_ACTION_DENY,
    CLAIM_ACTION_START_REVIEW,
    CLAIM_DENIED,
    CLAIM_FILED,
    CLAMP_FINANCIAL_REQUIRES_ONLINE_TOOL,
    CLAMP_NONE,
    DECISION_DENIED,
    DEDUCTION_TIER_1_CAP,
    DIRECTIVE_ONLINE_TOOL,
    DIRECTIVE_STATUS_RECORDED,
    DIRECTIVE_WILL_PROVISION,
    METHOD_PRORATA_DAILY,
    METHOD_UNUSED_PERIOD,
    NON_TRANSFERABLE,
    PHASE_DISCLOSURE,
    PLATFORM_STATUS_PARTICIPATING,
    PLATFORM_STATUS_SUSPENDED,
    PRECEDENCE_RANK_INSTRUMENT,
    PRECEDENCE_RANK_ONLINE_TOOL,
    REFUND_POLICY_PRORATA_DAILY,
    REFUND_POLICY_UNUSED_PERIOD,
    REQUEST_DENIED,
    REQUEST_TYPE_CONTENT_ACCESS,
    RUN_COMPUTED,
    RUN_SUPERSEDED,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_CATALOG_ONLY,
    SCOPE_NONE,
    TRANSFERABLE,
)
from test_helpers.test_users import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    make_platform_compliance_headers,
)


def test_resolution_falls_back_to_the_statutory_default_and_the_suspended_gate_wins(api):
    """
    An estate with no recorded directive at all resolves to the statutory
    default, and the clamp cannot fire on that narrow scope even though the
    provider demands a court order for content. Suspending the provider then
    overrides the default outright and collapses the scope to NONE.

    PRD: "When the candidate set is empty there is no winner, and the statutory default applies: the base scope is `CATALOG_ONLY` and the basis is `STATUTORY_DEFAULT`."

    PRD: "Step zero is the provider gate: if the provider's `status` is `SUSPENDED`, resolution stops immediately and returns a `resolved_scope` of `NONE`, a `resolved_basis` of `STATUTORY_DEFAULT`, a `clamp_reason` of `NONE` and a null `controlling_directive_id`."

    Design: Corner/calculations/authority_resolution_returns_the_statutory_default_and_the_suspended_gate
    """
    fx.set_clock(api)
    platform = fx.register_social_platform(
        api,
        name="SocialSphere",
        form_code="SS-FORM-2",
        review_window_days=30,
        requires_court_order_for_content=True,
        license_terminates_at_death=True,
    )
    assert platform["status"] == PLATFORM_STATUS_PARTICIPATING
    estate = fx.open_estate(api, court_case_number="PR-2737-C20")
    before = validate_success(api.get_estate(estate["id"], ESTATE_ADMIN_HEADERS), 200)

    no_category = validate_success(
        api.get_authority_resolution(
            estate["id"], ESTATE_ADMIN_HEADERS, platform_id=platform["id"]
        ),
        200,
    )
    assert_fields(
        no_category,
        estate_id=estate["id"],
        platform_id=platform["id"],
        resolved_scope=SCOPE_CATALOG_ONLY,
        resolved_basis=BASIS_STATUTORY_DEFAULT,
        clamp_reason=CLAMP_NONE,
    )
    assert_null_fields(no_category, "controlling_directive_id")

    with_category = validate_success(
        api.get_authority_resolution(
            estate["id"],
            ESTATE_ADMIN_HEADERS,
            platform_id=platform["id"],
            asset_category=CATEGORY_SOCIAL_PROFILE,
        ),
        200,
    )
    assert_fields(
        with_category,
        asset_category=CATEGORY_SOCIAL_PROFILE,
        resolved_scope=SCOPE_CATALOG_ONLY,
        resolved_basis=BASIS_STATUTORY_DEFAULT,
        clamp_reason=CLAMP_NONE,
    )
    assert_null_fields(with_category, "controlling_directive_id")

    suspended = fx.patch_platform(api, platform["id"], status=PLATFORM_STATUS_SUSPENDED)
    assert suspended["status"] == PLATFORM_STATUS_SUSPENDED

    gated = validate_success(
        api.get_authority_resolution(
            estate["id"],
            ESTATE_ADMIN_HEADERS,
            platform_id=platform["id"],
            asset_category=CATEGORY_SOCIAL_PROFILE,
        ),
        200,
    )
    assert_fields(
        gated,
        resolved_scope=SCOPE_NONE,
        resolved_basis=BASIS_STATUTORY_DEFAULT,
        clamp_reason=CLAMP_NONE,
    )
    assert_null_fields(gated, "controlling_directive_id")

    # The projection is read-only: three resolutions leave the estate untouched.
    after = validate_success(api.get_estate(estate["id"], ESTATE_ADMIN_HEADERS), 200)
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]


def test_an_online_tool_directive_leaves_the_candidate_set_when_the_provider_drops_the_tool(api):
    """
    A rank-1 online tool directive beats a wider will provision while the
    provider offers the tool. Turning the provider's tool off drops that
    directive from the candidate set, so the will underneath takes over without
    the directive itself changing status, and no further online tool directive
    can be recorded against that provider.

    PRD: "One directive is then thrown out of the candidate set entirely: an `ONLINE_TOOL` directive is dropped whenever the target provider's `supports_online_tool` is false, which lets the will-and-trust layer beneath it take over rather than blocking on an honour the provider does not offer."

    PRD: "One guard applies at recording time: an `ONLINE_TOOL` directive may only be recorded against a specific provider that actually offers an online tool, so a null `platform_id` or a provider whose `supports_online_tool` is false is rejected with `ERR_ONLINE_TOOL_UNSUPPORTED`."

    Design: Corner/calculations/an_online_tool_directive_is_dropped_when_the_platform_offers_no_tool
    """
    fx.set_clock(api)
    platform = fx.register_platform(api)
    assert platform["supports_online_tool"] is True
    ctx = fx.authorized_estate(api, "PR-2737-C21")

    tool = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_ONLINE_TOOL,
        scope=SCOPE_CATALOG_AND_CONTENT,
        platform_id=platform["id"],
        instrument_reference="CloudVault legacy contact screen",
        executed_on="2025-11-02",
    )
    will = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_WILL_PROVISION,
        scope=SCOPE_CATALOG_ONLY,
        instrument_reference="Will article 7.2",
        executed_on="2025-06-01",
    )
    assert tool["precedence_rank"] == PRECEDENCE_RANK_ONLINE_TOOL
    assert will["precedence_rank"] == PRECEDENCE_RANK_INSTRUMENT

    with_tool = validate_success(
        api.get_authority_resolution(
            ctx.estate_id, ctx.fid_headers, platform_id=platform["id"]
        ),
        200,
    )
    assert_fields(
        with_tool,
        resolved_scope=SCOPE_CATALOG_AND_CONTENT,
        resolved_basis=BASIS_ONLINE_TOOL,
        clamp_reason=CLAMP_NONE,
        controlling_directive_id=tool["id"],
    )

    patched = fx.patch_platform(api, platform["id"], supports_online_tool=False)
    assert patched["supports_online_tool"] is False

    without_tool = validate_success(
        api.get_authority_resolution(
            ctx.estate_id, ctx.fid_headers, platform_id=platform["id"]
        ),
        200,
    )
    assert_fields(
        without_tool,
        resolved_scope=SCOPE_CATALOG_ONLY,
        resolved_basis=BASIS_WILL_PROVISION,
        clamp_reason=CLAMP_NONE,
        controlling_directive_id=will["id"],
    )

    # Dropping is a resolution-time filter, not a status change on the record.
    assert (
        validate_success(api.get_authority_directive(tool["id"], ctx.fid_headers), 200)[
            "status"
        ]
        == DIRECTIVE_STATUS_RECORDED
    )

    bound_to_toolless_provider = api.create_authority_directive(
        ctx.estate_id,
        f.directive_payload(
            directive_type=DIRECTIVE_ONLINE_TOOL,
            scope=SCOPE_CATALOG_AND_CONTENT,
            platform_id=platform["id"],
            instrument_reference="second legacy contact screen",
            executed_on="2026-01-05",
        ),
        COURT_REGISTRAR_HEADERS,
    )
    validate_error(bound_to_toolless_provider, ERR_ONLINE_TOOL_UNSUPPORTED)

    bound_to_no_provider = api.create_authority_directive(
        ctx.estate_id,
        f.directive_payload(
            directive_type=DIRECTIVE_ONLINE_TOOL,
            scope=SCOPE_CATALOG_AND_CONTENT,
            instrument_reference="instrument-wide legacy contact",
            executed_on="2026-01-06",
        ),
        COURT_REGISTRAR_HEADERS,
    )
    validate_error(bound_to_no_provider, ERR_ONLINE_TOOL_UNSUPPORTED)


def test_financial_content_stays_clamped_until_an_online_tool_grant_arrives(api):
    """
    One approval on a will provision discloses a financial account and a loyalty
    account through the same grant, yet only the loyalty account reaches content
    level: the financial account is held at catalogue level with a machine
    readable clamp. A second approval resting on the decedent's own online tool
    designation widens the financial account without rewriting the first
    disclosure stamp.

    PRD: "If the `granted_scope` is `CATALOG_AND_CONTENT` but the account's `category` is `FINANCIAL_ACCOUNT` and the grant's `basis` is anything other than `ONLINE_TOOL`, the account moves only to `CATALOG_DISCLOSED` and its `content_clamp_reason` becomes `FINANCIAL_REQUIRES_ONLINE_TOOL`: financial accounts surrender their contents only on the decedent's own online-tool designation, never on a will, a trust or the statutory default, no matter how broadly the provider granted."

    PRD: "A second approval that widens an account from `CATALOG_DISCLOSED` to `CONTENT_DISCLOSED` leaves the original `disclosed_at` untouched — the timestamp records first disclosure, not the latest one — and resets `content_clamp_reason` to `NONE`, because the clamp that once held has been lifted."

    Design: Corner/calculations/financial_account_content_is_clamped_until_an_online_tool_grant_arrives
    """
    fx.set_clock(api)
    bank = fx.register_financial_platform(
        api,
        name="FirstMeridian Bank",
        form_code="FM-FORM-7",
        review_window_days=14,
        requires_court_order_for_content=False,
        transfer_fee_cents=0,
        request_fee_cents=0,
    )
    assert bank["supports_online_tool"] is True
    ctx = fx.authorized_estate(api, "PR-2737-C22")
    fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_WILL_PROVISION,
        scope=SCOPE_CATALOG_AND_CONTENT,
        instrument_reference="Will article 9.1",
        executed_on="2025-06-01",
    )
    financial = fx.add_asset(
        api,
        ctx,
        bank["id"],
        category=CATEGORY_FINANCIAL_ACCOUNT,
        account_handle="chk-4417",
        quoted_value_cents=400000,
    )
    loyalty = fx.add_asset(
        api,
        ctx,
        bank["id"],
        category=CATEGORY_LOYALTY_PROGRAM,
        account_handle="rewards-9",
        quoted_value_cents=60000,
        loyalty_points=45000,
    )
    assert financial["transferability"] == TRANSFERABLE
    assert loyalty["transferability"] == TRANSFERABLE

    on_the_will = fx.approved_request(
        api,
        ctx,
        bank["id"],
        bank["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )
    assert_fields(
        on_the_will,
        resolved_scope=SCOPE_CATALOG_AND_CONTENT,
        resolved_basis=BASIS_WILL_PROVISION,
        clamp_reason=CLAMP_NONE,
    )

    clamped = fx.read_asset(api, ctx, financial["id"])
    assert_fields(
        clamped,
        access_status=ACCESS_CATALOG_DISCLOSED,
        content_clamp_reason=CLAMP_FINANCIAL_REQUIRES_ONLINE_TOOL,
    )
    assert clamped["disclosed_at"] is not None
    assert clamped["disclosed_at"].startswith("2026-08-01")
    wide_open = fx.read_asset(api, ctx, loyalty["id"])
    assert_fields(
        wide_open,
        access_status=ACCESS_CONTENT_DISCLOSED,
        content_clamp_reason=CLAMP_NONE,
    )

    fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_ONLINE_TOOL,
        scope=SCOPE_CATALOG_AND_CONTENT,
        platform_id=bank["id"],
        instrument_reference="bank legacy access designation",
        executed_on="2026-01-05",
    )
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    on_the_tool = fx.approved_request(
        api,
        ctx,
        bank["id"],
        bank["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )
    assert_fields(
        on_the_tool,
        resolved_scope=SCOPE_CATALOG_AND_CONTENT,
        resolved_basis=BASIS_ONLINE_TOOL,
        clamp_reason=CLAMP_NONE,
    )

    widened = fx.read_asset(api, ctx, financial["id"])
    assert_fields(
        widened,
        access_status=ACCESS_CONTENT_DISCLOSED,
        content_clamp_reason=CLAMP_NONE,
    )
    assert widened["disclosed_at"] == clamped["disclosed_at"]

    estate = fx.read_estate(api, ctx)
    assert_fields(
        estate,
        disclosed_asset_count=2,
        inventory_total_count=2,
        administration_phase=PHASE_DISCLOSURE,
    )


def test_the_roll_up_counts_only_accounts_that_are_both_transferable_and_disclosed(api):
    """
    Three accounts, one appraisal. A disclosed email account fails the
    transferability half of the inclusion test and an undisclosed cloud account
    fails the disclosure half, so only the disclosed cloud account carries value
    into the estate's gross figure and the count of included accounts is one.

    PRD: "An account enters the roll-up only if its `transferability` is exactly `TRANSFERABLE` **and** its `access_status` is `CATALOG_DISCLOSED` or `CONTENT_DISCLOSED`."

    PRD: "Excluded accounts contribute 0 and are not counted in `included_asset_count`."

    Design: Corner/calculations/valuation_counts_only_disclosed_transferable_assets
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C23")

    included = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    personal = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_EMAIL,
        account_handle="mail-1",
        quoted_value_cents=50000,
    )
    assert included["transferability"] == TRANSFERABLE
    assert personal["transferability"] == NON_TRANSFERABLE

    fx.approved_request(api, ctx, cloud["id"], cloud["form_code"])

    # Inventoried after the approval, so this one was never disclosed.
    undisclosed = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-2",
        quoted_value_cents=300000,
    )
    assert undisclosed["access_status"] == ACCESS_UNVERIFIED
    assert undisclosed["transferability"] == TRANSFERABLE

    designation = fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives")
    assert designation["allocation_rank"] == 1

    estate = fx.read_estate(api, ctx)
    assert_fields(estate, inventory_total_count=3, disclosed_asset_count=2)

    run = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(estate["version"], basis=BASIS_DATE_OF_DEATH),
            ctx.fid_headers,
        ),
        201,
    )
    assert_fields(
        run,
        status=RUN_COMPUTED,
        basis=BASIS_DATE_OF_DEATH,
        included_asset_count=1,
        gross_value_cents=200000,
        deduction_cap_cents=DEDUCTION_TIER_1_CAP,
        admin_deduction_cents=0,
        taxable_value_cents=200000,
        allocation_remainder_cents=0,
    )
    assert_null_fields(run, "finalized_at")

    assert_fields(
        fx.read_asset(api, ctx, included["id"]),
        appraised_value_cents=200000,
        appraised_basis=BASIS_DATE_OF_DEATH,
    )
    assert_null_fields(
        fx.read_asset(api, ctx, personal["id"]), "appraised_value_cents", "appraised_basis"
    )
    assert_null_fields(
        fx.read_asset(api, ctx, undisclosed["id"]), "appraised_value_cents", "appraised_basis"
    )

    mirrored = fx.read_estate(api, ctx)
    assert_fields(
        mirrored,
        gross_digital_estate_cents=200000,
        admin_deduction_cents=0,
        taxable_digital_estate_cents=200000,
        undistributed_value_cents=200000,
        valuation_basis=BASIS_DATE_OF_DEATH,
    )
    assert_fields(
        fx.read_designation(api, ctx, designation["id"]),
        planned_allocation_cents=200000,
        received_value_cents=0,
    )


def test_an_alternate_run_waits_for_the_six_month_date_and_then_decays_the_cloud_account(api):
    """
    The alternate basis is refused on the day before the estate's alternate
    valuation date and accepted on the date itself, and when it lands it decays a
    cloud-storage account by fifty basis points a month for six months: 200000
    times 9700 divided by 10000 is exactly 194000 cents.

    PRD: "An `ALTERNATE` run additionally requires the clock's calendar date to have reached the estate's `alternate_valuation_date`; the boundary is inclusive, so a run on exactly that date is accepted while a run one day earlier is rejected with `ERR_ALTERNATE_DATE_NOT_REACHED`."

    PRD: "The gross is then `quoted_value_cents` multiplied by the quantity 10000 minus the total decay basis points, divided by 10000, rounded half up to a whole cent."

    Design: Corner/calculations/an_alternate_basis_run_is_refused_until_the_six_month_date_is_reached
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api)
    assert cloud["transfer_fee_cents"] == 0
    ctx = fx.authorized_estate(api, "PR-2737-C24", date_of_death="2026-02-14")
    assert fx.read_estate(api, ctx)["alternate_valuation_date"] == "2026-08-14"

    vault = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    fx.approved_request(api, ctx, cloud["id"], cloud["form_code"])
    designation = fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives")

    on_death_basis = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert_fields(
        on_death_basis,
        status=RUN_COMPUTED,
        included_asset_count=1,
        gross_value_cents=200000,
        taxable_value_cents=200000,
    )

    version = fx.estate_version(api, ctx)
    too_early = api.create_valuation_run(
        ctx.estate_id,
        f.valuation_run_payload(version, basis=BASIS_ALTERNATE),
        ctx.fid_headers,
    )
    validate_error(too_early, ERR_ALTERNATE_DATE_NOT_REACHED)

    fx.set_clock(api, "2026-08-13T00:00:00Z")
    day_before = api.create_valuation_run(
        ctx.estate_id,
        f.valuation_run_payload(version, basis=BASIS_ALTERNATE),
        ctx.fid_headers,
    )
    validate_error(day_before, ERR_ALTERNATE_DATE_NOT_REACHED)

    fx.set_clock(api, "2026-08-14T00:00:00Z")
    on_alternate_basis = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(version, basis=BASIS_ALTERNATE),
            ctx.fid_headers,
        ),
        201,
    )
    assert_fields(
        on_alternate_basis,
        status=RUN_COMPUTED,
        basis=BASIS_ALTERNATE,
        included_asset_count=1,
        gross_value_cents=194000,
        taxable_value_cents=194000,
        allocation_remainder_cents=0,
    )
    assert fx.read_run(api, ctx, on_death_basis["id"])["status"] == RUN_SUPERSEDED

    assert_fields(
        fx.read_asset(api, ctx, vault["id"]),
        appraised_value_cents=194000,
        appraised_basis=BASIS_ALTERNATE,
    )
    assert fx.read_designation(api, ctx, designation["id"])["planned_allocation_cents"] == 194000
    assert_fields(
        fx.read_estate(api, ctx),
        gross_digital_estate_cents=194000,
        taxable_digital_estate_cents=194000,
        undistributed_value_cents=194000,
        valuation_basis=BASIS_ALTERNATE,
    )


def test_refund_rounding_lands_on_a_half_cent_and_a_sub_month_claim_collapses_to_zero(api):
    """
    A pro-rata claim whose exact entitlement is 500.5 cents rounds half up to
    501, while an unused-period claim of 29 days holds no complete thirty-day
    block and is worth nothing at all; a 30-day claim on the same term pays for
    exactly thirty days.

    PRD: "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    PRD: "A `UNUSED_PERIOD` claim shorter than 30 days therefore yields an entitlement of exactly 0 even though it passed the seven-day minimum, and a 59-day claim is paid as 30 days, not 59."

    Design: Corner/calculations/refund_rounding_lands_on_a_half_cent_and_a_sub_month_claim_collapses_to_zero
    """
    fx.set_clock(api)
    prorata = fx.register_subscription_platform(api)
    unused = fx.register_subscription_platform(
        api,
        name="ReadRoom",
        form_code="RR-FORM-5",
        refund_policy=REFUND_POLICY_UNUSED_PERIOD,
    )
    ctx = fx.authorized_estate(api, "PR-2737-C25", date_of_death="2026-01-10")

    half_cent = fx.subscription_with_confirmed_order(
        api,
        ctx,
        prorata,
        account_handle="stream-basic",
        term_overrides={
            "term_start_date": "2026-02-01",
            "term_end_date": "2026-02-28",
            "billing_interval": BILLING_INTERVAL_MONTHLY,
            "period_fee_cents": 1001,
        },
        effective_date="2026-03-01",
        platform_reference="SO-CXL-1",
    )
    blocks = fx.subscription_with_confirmed_order(
        api,
        ctx,
        unused,
        account_handle="read-basic",
        term_overrides={
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "billing_interval": BILLING_INTERVAL_ANNUAL,
            "period_fee_cents": 11999,
        },
        effective_date="2026-03-01",
        platform_reference="RR-CXL-1",
    )
    assert half_cent["term"]["term_days"] == 28
    assert blocks["term"]["term_days"] == 365
    assert half_cent["order"]["refund_policy_snapshot"] == REFUND_POLICY_PRORATA_DAILY
    assert blocks["order"]["refund_policy_snapshot"] == REFUND_POLICY_UNUSED_PERIOD

    # 1001 * 14 / 28 = 500.5 exactly, which rounds half up to 501.
    rounded_up = fx.file_refund_claim(
        api, ctx, half_cent["order"]["id"], "2026-02-01", "2026-02-14"
    )
    assert_fields(
        rounded_up,
        status=CLAIM_FILED,
        method=METHOD_PRORATA_DAILY,
        claimed_days=14,
        claimed_cents=501,
        credited_cents=0,
    )

    # 29 days holds no complete 30-day block, so the entitlement is 0.
    no_block = fx.file_refund_claim(api, ctx, blocks["order"]["id"], "2026-05-01", "2026-05-29")
    assert_fields(
        no_block,
        status=CLAIM_FILED,
        method=METHOD_UNUSED_PERIOD,
        claimed_days=29,
        claimed_cents=0,
    )

    # 30 days is exactly one block: 11999 * 30 / 365 = 986.2192..., so 986.
    one_block = fx.file_refund_claim(api, ctx, blocks["order"]["id"], "2026-06-01", "2026-06-30")
    assert_fields(
        one_block,
        status=CLAIM_FILED,
        method=METHOD_UNUSED_PERIOD,
        claimed_days=30,
        claimed_cents=986,
    )

    assert fx.read_term(api, ctx, half_cent["term"]["id"])["claimed_days_total"] == 14
    assert fx.read_term(api, ctx, blocks["term"]["id"])["claimed_days_total"] == 59
    # Filing entitles nobody: only a credit moves the estate's recovery figure.
    assert fx.read_estate(api, ctx)["refund_recovered_cents"] == 0


def test_only_approved_request_fees_enter_the_deduction_while_every_claim_cost_does(api):
    """
    Three request packages are filed and only two are approved, so only their
    providers' request fees are administrative costs; the denied package's fee is
    not. A refund claim's pursuit cost counts even after the provider denies the
    claim, and the total stays well under the tier cap the gross selects.

    PRD: "The estate's actual administrative costs are the sum of the `request_fee_cents` of the providers behind every one of the estate's platform requests in `APPROVED` status, plus the sum of the `pursuit_cost_cents` of every refund claim of the estate regardless of that claim's status — the money was spent whether or not the claim succeeded."

    PRD: "`admin_deduction_cents` is the smaller of the cap and those actual costs, so a frugal estate deducts only what it spent while a costly one is held to its tier."

    Design: Corner/calculations/only_approved_request_fees_enter_the_deduction_while_every_claim_cost_does
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api, request_fee_cents=1500)
    stream = fx.register_subscription_platform(api, request_fee_cents=900)
    social = fx.register_social_platform(
        api,
        name="SocialSphere",
        form_code="SS-FORM-2",
        review_window_days=30,
        request_fee_cents=700,
    )
    ctx = fx.authorized_estate(api, "PR-2737-C26")

    vault = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    assert vault["transferability"] == TRANSFERABLE
    subscription = fx.add_subscription_asset(api, ctx, stream["id"], account_handle="stream-basic")
    term = fx.add_subscription_term(api, ctx, subscription["id"])
    assert term["term_days"] == 365

    fx.approved_request(api, ctx, cloud["id"], cloud["form_code"])
    fx.approved_request(api, ctx, stream["id"], stream["form_code"])

    refused = fx.draft_request(api, ctx, social["id"], social["form_code"])
    fx.submit_request(api, ctx, refused["id"])
    fx.start_review(api, social["id"], refused["id"])
    decided = fx.decide_request(
        api,
        social["id"],
        refused["id"],
        decision=DECISION_DENIED,
        decision_note="No memorialization instruction on file for this decedent.",
    )
    assert decided["status"] == REQUEST_DENIED

    order = fx.cancellation_order_for_asset(api, ctx, subscription["id"])
    fx.confirmed_cancellation_order(
        api,
        ctx,
        stream["id"],
        order["id"],
        effective_date="2026-04-01",
        platform_reference="SO-CXL-2",
    )
    claim = fx.file_refund_claim(
        api, ctx, order["id"], "2026-05-01", "2026-06-30", pursuit_cost_cents=300
    )
    # 11999 * 61 / 365 = 2005.3123..., so 2005.
    assert_fields(claim, claimed_days=61, claimed_cents=2005, pursuit_cost_cents=300)

    desk = make_platform_compliance_headers(stream["id"])
    validate_success(
        api.transition_refund_claim(
            claim["id"], f.claim_transition_payload(CLAIM_ACTION_START_REVIEW), desk
        ),
        200,
    )
    denied_claim = validate_success(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(
                CLAIM_ACTION_DENY,
                denial_reason="The term fell outside the provider's refund policy.",
            ),
            desk,
        ),
        200,
    )
    assert denied_claim["status"] == CLAIM_DENIED

    fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives")
    estate = fx.read_estate(api, ctx)
    run = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(estate["version"], basis=BASIS_DATE_OF_DEATH),
            ctx.fid_headers,
        ),
        201,
    )
    # 1500 + 900 approved request fees + 300 pursuit cost = 2700, under the
    # 25000 cap that a gross of 200000 selects.
    assert_fields(
        run,
        status=RUN_COMPUTED,
        included_asset_count=1,
        gross_value_cents=200000,
        deduction_cap_cents=DEDUCTION_TIER_1_CAP,
        admin_deduction_cents=2700,
        taxable_value_cents=197300,
        allocation_remainder_cents=0,
    )
    assert_fields(
        fx.read_estate(api, ctx),
        gross_digital_estate_cents=200000,
        admin_deduction_cents=2700,
        taxable_digital_estate_cents=197300,
        refund_recovered_cents=0,
    )
    # The denial released the claimed interval.
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0
