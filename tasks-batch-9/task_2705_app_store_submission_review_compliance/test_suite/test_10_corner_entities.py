"""Corner section: entities.

Creation defaults, server-set system fields, closed enums, required inputs,
by-id retrieval, listing envelopes and the two self-referential graph edges.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_app_record,
    add_credentials,
    add_effective_rule,
    assert_decimal_equals,
    assert_posture,
    create_app_record_payload,
    create_commerce_item_payload,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_publisher_account_payload,
    create_signing_credential_payload,
    get_success_data,
    make_auditor_headers,
    make_policy_admin_headers,
    make_reviewer_headers,
    new_account,
    set_clock,
    setup_base_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# publisher_account_create_returns_active_with_full_standing_and_two_credits
# ---------------------------------------------------------------------------
def test_a_new_account_is_active_with_a_perfect_reputation(api):
    """"A brand-new account starts with a perfect reputation: both
    `standing_score_rolling_365` and `standing_score_lifetime` are 100.00, and
    `expedite_credits_remaining` is 2."

    Design: Corner/entities/publisher_account_create_returns_active_with_full_standing_and_two_credits
    """
    set_clock(api, DEFAULT_CLOCK)

    account = validate_success(
        api.create_publisher_account(
            create_publisher_account_payload(), make_policy_admin_headers()
        ),
        201,
    )
    assert account["program_status"] == "ACTIVE"
    assert_decimal_equals(account["standing_score_rolling_365"], 100.00, 2, "rolling")
    assert_decimal_equals(account["standing_score_lifetime"], 100.00, 2, "lifetime")
    assert account["expedite_credits_remaining"] == 2


def test_a_new_account_carries_no_enforcement_no_strikes_and_no_settlements(api):
    """"Its `enforcement_reason_code` is null, its `rejection_strike_count` is 0, and its
    `settlement_finalized_periods` array is empty."

    Design: Corner/entities/publisher_account_create_returns_active_with_full_standing_and_two_credits
    """
    set_clock(api, DEFAULT_CLOCK)

    account = validate_success(
        api.create_publisher_account(
            create_publisher_account_payload(), make_policy_admin_headers()
        ),
        201,
    )
    assert account["enforcement_reason_code"] is None
    assert account["rejection_strike_count"] == 0
    assert account["settlement_finalized_periods"] == []
    assert account["version"] == 1


# ---------------------------------------------------------------------------
# publisher_account_create_with_lapsed_paid_through_starts_expired
# ---------------------------------------------------------------------------
def test_a_paid_through_instant_in_the_past_enrols_the_account_expired(api):
    """"The new account's `program_status` is set to `ACTIVE` when
    `membership_paid_through_at` is later than the current logical instant, and to
    `EXPIRED` otherwise."

    Design: Corner/entities/publisher_account_create_with_lapsed_paid_through_starts_expired
    """
    set_clock(api, DEFAULT_CLOCK)

    account = validate_success(
        api.create_publisher_account(
            create_publisher_account_payload(
                legal_name="Lapsed Labs GmbH",
                contact_email="billing@lapsed.example",
                membership_paid_through_at="2026-07-01T00:00:00Z",
            ),
            make_policy_admin_headers(),
        ),
        201,
    )
    assert account["program_status"] == "EXPIRED"
    assert account["enforcement_reason_code"] is None
    assert account["commerce_program_tier"] == "STANDARD"


# ---------------------------------------------------------------------------
# publisher_account_create_omitting_commerce_program_tier_defaults_to_standard
# ---------------------------------------------------------------------------
def test_omitting_the_commerce_tier_selects_the_standard_base_rate_branch(api):
    """"The tier is either `SMALL_BUSINESS` or `STANDARD` and defaults to `STANDARD`; it
    is what selects the base commission rate later."

    Design: Corner/entities/publisher_account_create_omitting_commerce_program_tier_defaults_to_standard
    """
    set_clock(api, DEFAULT_CLOCK)
    payload = create_publisher_account_payload(legal_name="Default Tier Studios")
    payload.pop("commerce_program_tier")

    account = validate_success(
        api.create_publisher_account(payload, make_policy_admin_headers()), 201
    )
    assert account["commerce_program_tier"] == "STANDARD"


# ---------------------------------------------------------------------------
# app_record_create_starts_draft_not_distributed_and_restricted_with_two_reason_codes
# ---------------------------------------------------------------------------
def test_a_bare_app_record_starts_draft_and_not_distributed(api):
    """"A new record starts at `DRAFT` and `NOT_DISTRIBUTED`, with `compliance_posture`
    computed immediately — `RESTRICTED` until both an active distribution certificate and
    full mapping coverage exist — and with `feature_compliance_index` at 0.00,
    `live_submission_id` null, `released_share_pct` at 0.00, `held_back_share_pct` at
    100.00 and `rollback_count` at 0."

    Design: Corner/entities/app_record_create_starts_draft_not_distributed_and_restricted_with_two_reason_codes
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)

    app = validate_success(
        api.create_app_record(
            create_app_record_payload(
                ctx.account_id,
                bundle_id="com.northwind.bare",
                display_name="Northwind Bare",
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    assert app["listing_state"] == "DRAFT"
    assert app["distribution_state"] == "NOT_DISTRIBUTED"
    assert app["live_submission_id"] is None
    assert_decimal_equals(app["released_share_pct"], 0.00, 2, "released_share_pct")
    assert_decimal_equals(app["held_back_share_pct"], 100.00, 2, "held_back_share_pct")
    assert app["rollback_count"] == 0
    assert app["version"] == 1


def test_the_empty_mapping_set_scores_zero_and_pins_both_reason_codes(api):
    """"When the contributing set is empty — an app with no mappings, or an app whose
    every mapping points at a superseded rule — the index is 0.00, not 100.00: absence of
    evidence is not evidence of compliance, and this is the boundary that keeps a
    brand-new app record `RESTRICTED` rather than `OPEN`."

    Design: Corner/entities/app_record_create_starts_draft_not_distributed_and_restricted_with_two_reason_codes
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)

    app = validate_success(
        api.create_app_record(
            create_app_record_payload(
                ctx.account_id,
                bundle_id="com.northwind.bare",
                display_name="Northwind Bare",
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    assert_decimal_equals(app["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(
        app, "RESTRICTED", ["NO_ACTIVE_DISTRIBUTION_CERT", "COMPLIANCE_INDEX_BELOW_FLOOR"]
    )


# ---------------------------------------------------------------------------
# signing_credential_status_is_server_set_to_pending_activation
# ---------------------------------------------------------------------------
def test_a_registered_certificate_is_pending_activation_and_bumps_the_account(api):
    """"Newly registered material lands in status `PENDING_ACTIVATION` with
    `revocation_reason` and `compromised_at` null and `blocked_submission_count` at 0, and
    the registration advances the owning account's `version` by one."

    Design: Corner/entities/signing_credential_status_is_server_set_to_pending_activation
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    assert ctx.account_version() == 1

    cert = validate_success(
        api.create_signing_credential(
            create_signing_credential_payload(ctx.account_id, 1), ctx.publisher_admin
        ),
        201,
    )
    assert cert["status"] == "PENDING_ACTIVATION"
    assert cert["revocation_reason"] is None
    assert cert["compromised_at"] is None
    assert cert["blocked_submission_count"] == 0
    assert cert["linked_cert_id"] is None
    assert cert["version"] == 1
    assert ctx.account_version() == 2


# ---------------------------------------------------------------------------
# app_record_display_name_of_thirty_one_characters_returns_validation
# ---------------------------------------------------------------------------
def test_a_thirty_one_character_display_name_is_a_schema_violation(api):
    """"A `PublisherAdmin` creates the shell of a store listing by supplying the owning
    `publisher_account_id`, a reverse-DNS `bundle_id` (unique per account and platform),
    the `platform`, a `display_name` of 1 to 30 characters, and a `primary_category` from
    `GAMES`, `FINANCE`, `HEALTH`, `SOCIAL`, `PRODUCTIVITY` and `KIDS`."

    Design: Corner/entities/app_record_display_name_of_thirty_one_characters_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    too_long = "Northwind Wallet Pro Max Editio"
    assert len(too_long) == 31

    validate_error(
        api.create_app_record(
            create_app_record_payload(
                ctx.account_id,
                bundle_id="com.northwind.toolong",
                display_name=too_long,
            ),
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_app_records(
            ctx.publisher_admin, {"publisher_account_id": ctx.account_id}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# publisher_account_create_without_contact_email_returns_validation
# ---------------------------------------------------------------------------
def test_enrolling_without_a_contact_email_is_a_schema_violation(api):
    """"A `PlatformPolicyAdmin` enrols a publisher into the developer program by supplying
    the registered `legal_name` (between 1 and 120 characters, and unique across all
    accounts), an operational `contact_email` (which must contain an `@` character), the
    `membership_paid_through_at` instant through which membership has been paid, and
    optionally the `commerce_program_tier`."

    Design: Corner/entities/publisher_account_create_without_contact_email_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)
    payload = create_publisher_account_payload(legal_name="No Contact Ltd")
    payload.pop("contact_email")

    validate_error(
        api.create_publisher_account(payload, make_policy_admin_headers()),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_publisher_accounts(make_policy_admin_headers())
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# signing_credential_create_without_key_custody_returns_validation
# ---------------------------------------------------------------------------
def test_registering_without_a_key_custody_declaration_is_refused(api):
    """"A `PublisherAdmin` registers signing material against the account by supplying
    `expected_publisher_account_version`, the owning `publisher_account_id`, a
    `credential_type`, the `platform` the material is for, a `key_custody` declaration,
    the validity bounds `not_before` and `not_after`, and optionally a `linked_cert_id`
    and an `entitlements` array."

    Design: Corner/entities/signing_credential_create_without_key_custody_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    payload = create_signing_credential_payload(ctx.account_id, 1)
    payload.pop("key_custody")

    validate_error(
        api.create_signing_credential(payload, ctx.publisher_admin),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    assert ctx.account_version() == 1, "a refused registration burns no revision"


# ---------------------------------------------------------------------------
# app_record_index_and_posture_are_rederived_when_the_last_mapping_passes
# ---------------------------------------------------------------------------
def _setup_single_in_progress_mapping(api):
    """The canonical chain stopped with its one mapping left IN_PROGRESS."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        mapping_advance="START",
        with_submission=False,
        with_window=False,
    )
    return ctx


def test_an_in_progress_mapping_scores_a_quarter_of_its_weight(api):
    """"Each contributing mapping has a weight equal to its `risk_weight` and a compliance
    factor determined solely by its `self_review_status`: 1.0 for `PASSED`, 1.0 for
    `WAIVED_BY_PLATFORM`, 0.5 for `STALE`, 0.25 for `IN_PROGRESS`, 0.0 for `NOT_STARTED`
    and 0.0 for `FAILED`."

    Design: Corner/entities/app_record_index_and_posture_are_rederived_when_the_last_mapping_passes
    """
    ctx = _setup_single_in_progress_mapping(api)

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 25.00, 2, "index")
    assert_posture(app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])


def test_passing_the_last_mapping_stamps_the_attestation_and_opens_the_posture(api):
    """"Passing or failing stamps `attested_by_user_id` with the acting operator and
    `attested_at` with the current logical instant, clears `staled_by_rule_id`, and
    recomputes the app's index and posture."

    Design: Corner/entities/app_record_index_and_posture_are_rederived_when_the_last_mapping_passes
    """
    ctx = _setup_single_in_progress_mapping(api)
    mapping_id = ctx.mappings["privacy"]

    passed = validate_success(
        api.self_review_mapping(
            mapping_id,
            {"outcome": "PASS", "evidence_ref": "https://evidence.northwind.example/1"},
            ctx.compliance_officer,
        ),
        200,
    )
    assert passed["self_review_status"] == "PASSED"
    assert passed["attested_by_user_id"] == f"u-compliance-{ctx.suffix}"
    assert passed["attested_at"] == DEFAULT_CLOCK
    assert passed["staled_by_rule_id"] is None

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(app, "OPEN", [])


# ---------------------------------------------------------------------------
# signing_credential_get_returns_the_stored_entitlement_set_and_validity_interval
# ---------------------------------------------------------------------------
def test_the_credential_read_echoes_its_entitlements_and_validity_bounds(api):
    """"`entitlements` is a subset of `IN_APP_PURCHASE`, `EXTERNAL_PAYMENT_LINK`,
    `PUSH_NOTIFICATIONS` and `BACKGROUND_LOCATION`, and defaults to the empty array."

    Design: Corner/entities/signing_credential_get_returns_the_stored_entitlement_set_and_validity_interval
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    cert = get_success_data(
        api.create_signing_credential(
            create_signing_credential_payload(
                ctx.account_id,
                1,
                entitlements=["IN_APP_PURCHASE", "EXTERNAL_PAYMENT_LINK"],
            ),
            ctx.publisher_admin,
        )
    )
    get_success_data(api.activate_signing_credential(cert["id"], ctx.publisher_admin))

    read = validate_success(
        api.get_signing_credential(cert["id"], make_auditor_headers()), 200
    )
    assert read["entitlements"] == ["IN_APP_PURCHASE", "EXTERNAL_PAYMENT_LINK"]
    assert read["not_before"] == "2026-07-01T00:00:00Z"
    assert read["not_after"] == "2027-07-01T00:00:00Z"
    assert read["credential_type"] == "DISTRIBUTION_CERT"
    assert read["key_custody"] == "HSM"
    assert read["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# signing_credentials_list_filters_by_status_and_reports_the_pagination_envelope
# ---------------------------------------------------------------------------
def _setup_active_cert_and_pending_profile(api):
    """One ACTIVE distribution certificate plus one still-PENDING_ACTIVATION profile."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    cert = get_success_data(
        api.create_signing_credential(
            create_signing_credential_payload(ctx.account_id, 1), ctx.publisher_admin
        )
    )
    get_success_data(api.activate_signing_credential(cert["id"], ctx.publisher_admin))
    profile = get_success_data(
        api.create_signing_credential(
            create_signing_credential_payload(
                ctx.account_id,
                ctx.account_version(),
                credential_type="PROVISIONING_PROFILE",
                key_custody="CLOUD_MANAGED",
                linked_cert_id=cert["id"],
            ),
            ctx.publisher_admin,
        )
    )
    ctx.cert_id = cert["id"]
    ctx.profile_id = profile["id"]
    return ctx


def test_the_status_filter_narrows_the_credential_list_to_the_active_row(api):
    """"Registered material is discoverable by filtering on `publisher_account_id`,
    `linked_cert_id`, `credential_type`, `platform`, `status` or `key_custody`."

    Design: Corner/entities/signing_credentials_list_filters_by_status_and_reports_the_pagination_envelope
    """
    ctx = _setup_active_cert_and_pending_profile(api)

    rows, meta = validate_paginated(
        api.list_signing_credentials(
            make_auditor_headers(),
            {"publisher_account_id": ctx.account_id, "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [ctx.cert_id]

    _all_rows, all_meta = validate_paginated(
        api.list_signing_credentials(
            make_auditor_headers(), {"publisher_account_id": ctx.account_id}
        )
    )
    assert all_meta["total_count"] == 2


def test_the_credential_list_envelope_echoes_the_default_page_window(api):
    """"The `meta` object of a list response carries `limit` and `offset` echoing the
    effective values used, `total_count` giving the number of rows matching the filter
    before pagination was applied, and `has_more` indicating whether any row remains
    beyond the current page."

    Design: Corner/entities/signing_credentials_list_filters_by_status_and_reports_the_pagination_envelope
    """
    ctx = _setup_active_cert_and_pending_profile(api)

    _rows, meta = validate_paginated(
        api.list_signing_credentials(
            make_auditor_headers(),
            {"publisher_account_id": ctx.account_id, "status": "ACTIVE"},
        )
    )
    assert meta["limit"] == 10, "limit defaults to 10"
    assert meta["offset"] == 0
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# app_record_get_with_an_unknown_uuid_returns_app_record_not_found
# ---------------------------------------------------------------------------
def test_an_unresolvable_app_record_id_names_its_own_resource_type(api):
    """"Existence yields a 404 whose code names the resource type that failed to resolve,
    drawn from a family of fifteen: `ERR_PUBLISHER_ACCOUNT_NOT_FOUND`,
    `ERR_SIGNING_CREDENTIAL_NOT_FOUND`, `ERR_APP_RECORD_NOT_FOUND`,
    `ERR_GUIDELINE_RULE_NOT_FOUND`, `ERR_FEATURE_MAPPING_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_METADATA_LOCALE_NOT_FOUND`,
    `ERR_BEHAVIOR_FINDING_NOT_FOUND`, `ERR_REJECTION_REASON_NOT_FOUND`,
    `ERR_APPEAL_REQUEST_NOT_FOUND`, `ERR_EXPEDITE_REQUEST_NOT_FOUND`,
    `ERR_REVIEW_CAPACITY_WINDOW_NOT_FOUND`, `ERR_ROLLOUT_PLAN_NOT_FOUND`,
    `ERR_COMMERCE_ITEM_NOT_FOUND` and `ERR_IMPACT_ASSESSMENT_NOT_FOUND`."

    Design: Corner/entities/app_record_get_with_an_unknown_uuid_returns_app_record_not_found
    """
    set_clock(api, DEFAULT_CLOCK)

    validate_error(
        api.get_app_record(NON_EXISTENT_UUID, make_auditor_headers()),
        ApiErrorId.ERR_APP_RECORD_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
# submission_get_with_an_unknown_uuid_returns_submission_not_found
# ---------------------------------------------------------------------------
def test_a_reviewer_reading_an_unknown_submission_gets_the_submission_code(api):
    """"Note the rung order: a malformed body sent to a non-existent submission returns
    404, not 422."

    Design: Corner/entities/submission_get_with_an_unknown_uuid_returns_submission_not_found
    """
    set_clock(api, DEFAULT_CLOCK)

    validate_error(
        api.get_submission(NON_EXISTENT_UUID, make_reviewer_headers()),
        ApiErrorId.ERR_SUBMISSION_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
# guideline_rule_safety_category_derives_weight_five_and_grace_fourteen_days
# ---------------------------------------------------------------------------
def _draft_safety_rule(api):
    return validate_success(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="1.1.4",
                title="Objectionable Content",
                category="SAFETY",
                effective_from="2026-07-15T00:00:00Z",
            ),
            make_policy_admin_headers(),
        ),
        201,
    )


def test_the_safety_category_derives_weight_five_and_a_fourteen_day_grace(api):
    """"`severity_weight` is 5 for `SAFETY`, 4 for `PRIVACY`, 3 for `COMMERCE`, 3 for
    `LEGAL` and 1 for `DESIGN`."

    Design: Corner/entities/guideline_rule_safety_category_derives_weight_five_and_grace_fourteen_days
    """
    set_clock(api, DEFAULT_CLOCK)

    rule = _draft_safety_rule(api)
    assert rule["severity_weight"] == 5
    assert rule["remediation_grace_days"] == 14


def test_a_drafted_rule_is_unpublished_and_impacts_nothing_yet(api):
    """"A drafted rule has `status` `DRAFT`, `published_at` null and `impacted_app_count`
    at 0."

    Design: Corner/entities/guideline_rule_safety_category_derives_weight_five_and_grace_fourteen_days
    """
    set_clock(api, DEFAULT_CLOCK)

    rule = _draft_safety_rule(api)
    assert rule["status"] == "DRAFT"
    assert rule["published_at"] is None
    assert rule["impacted_app_count"] == 0
    assert rule["requires_feature_mapping"] is True


# ---------------------------------------------------------------------------
# guideline_rule_create_with_an_undeclared_category_returns_validation
# ---------------------------------------------------------------------------
def test_a_category_outside_the_closed_enum_drafts_no_rule(api):
    """"A `PlatformPolicyAdmin` drafts a guideline rule by supplying a `rule_code`, a
    `title`, a `category` from `SAFETY`, `PRIVACY`, `COMMERCE`, `LEGAL` and `DESIGN`, a
    `version_label`, an `effective_from` instant, optionally a `supersedes_rule_id` naming
    the rule this one replaces, and optionally `requires_feature_mapping`, which defaults
    to true and marks whether publishers must map a feature against this rule at all."

    Design: Corner/entities/guideline_rule_create_with_an_undeclared_category_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)

    validate_error(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="9.9.9",
                title="Accessibility Baseline",
                category="ACCESSIBILITY",
            ),
            make_policy_admin_headers(),
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_guideline_rules(make_auditor_headers())
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# guideline_rules_list_with_limit_above_one_hundred_returns_validation
# ---------------------------------------------------------------------------
def test_a_limit_of_one_hundred_and_one_is_refused_rather_than_clamped(api):
    """"A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is a
    schema violation and is rejected with `ERR_VALIDATION` and HTTP 422."

    Design: Corner/entities/guideline_rules_list_with_limit_above_one_hundred_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)

    validate_error(
        api.list_guideline_rules(make_auditor_headers(), {"limit": 101}),
        ApiErrorId.ERR_VALIDATION,
        422,
    )


# ---------------------------------------------------------------------------
# feature_mapping_create_with_an_unknown_app_record_id_returns_app_record_not_found
# ---------------------------------------------------------------------------
def test_a_mapping_needs_both_ends_of_its_edge_to_exist(api):
    """"Because path identifiers precede body fields and body fields are examined in
    declaration order, a rollout-plan creation that names both an unknown app record and
    an unknown submission reports `ERR_APP_RECORD_NOT_FOUND`, since `app_record_id` is
    declared first."

    Design: Corner/entities/feature_mapping_create_with_an_unknown_app_record_id_returns_app_record_not_found
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    rule = add_effective_rule(ctx)

    validate_error(
        api.create_feature_mapping(
            create_feature_mapping_payload(NON_EXISTENT_UUID, rule["id"]),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_APP_RECORD_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, {"guideline_rule_id": rule["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# commerce_item_create_starts_draft_with_zero_gross_and_null_commission_rate
# ---------------------------------------------------------------------------
def test_a_new_commerce_item_starts_draft_with_no_reported_revenue(api):
    """"An item is created in `DRAFT` with `rejection_note` null, `reported_gross_cents` 0,
    `reported_period_label` null, `commission_rate_applied` null and `commission_cents` 0,
    and is filterable by `app_record_id`, `item_type`, `status`, `entitlement_class` and
    `reported_period_label`."

    Design: Corner/entities/commerce_item_create_starts_draft_with_zero_gross_and_null_commission_rate
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    add_credentials(ctx)
    add_app_record(ctx)

    item = validate_success(
        api.create_commerce_item(
            create_commerce_item_payload(
                ctx.app_record_id,
                reference_name="Coin Pack 100",
                price_tier_cents=1005,
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    assert item["status"] == "DRAFT"
    assert item["subscriber_retention_months"] == 0
    assert item["reported_gross_cents"] == 0
    assert item["commission_cents"] == 0
    assert item["commission_rate_applied"] is None
    assert item["reported_period_label"] is None
    assert item["external_link_url"] is None
    assert item["rejection_note"] is None


# ---------------------------------------------------------------------------
# two_app_records_share_one_guideline_rule_through_independent_junction_rows
# ---------------------------------------------------------------------------
def _setup_second_app_mapped_to_the_same_rule(api):
    """One PASSED mapping on the first app and a fresh NOT_STARTED mapping on a second
    app of the same account, both pointing at the same EFFECTIVE rule."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, with_submission=False, with_window=False)
    first_app_id = ctx.app_record_id
    add_app_record(
        ctx,
        bundle_id="com.northwind.ledger",
        display_name="Northwind Ledger",
        primary_category="PRODUCTIVITY",
    )
    second = validate_success(
        api.create_feature_mapping(
            create_feature_mapping_payload(ctx.app_record_id, ctx.rules["privacy"]),
            ctx.compliance_officer,
        ),
        201,
    )
    return ctx, first_app_id, second


def test_the_junction_row_of_the_second_app_starts_unattested(api):
    """"A new mapping starts with `self_review_status` `NOT_STARTED` and with
    `attested_by_user_id`, `attested_at`, `staled_by_rule_id` and `waiver_reason` all
    null."

    Design: Corner/entities/two_app_records_share_one_guideline_rule_through_independent_junction_rows
    """
    _ctx, _first_app_id, second = _setup_second_app_mapped_to_the_same_rule(api)

    assert second["self_review_status"] == "NOT_STARTED"
    assert second["attested_by_user_id"] is None
    assert second["attested_at"] is None
    assert second["staled_by_rule_id"] is None
    assert second["waiver_reason"] is None


def test_one_rule_carries_two_rows_and_each_app_scores_only_its_own(api):
    """"Mappings are filterable by `app_record_id`, `guideline_rule_id`,
    `staled_by_rule_id`, `attested_by_user_id`, `self_review_status` and `feature_code`."

    Design: Corner/entities/two_app_records_share_one_guideline_rule_through_independent_junction_rows
    """
    ctx, first_app_id, _second = _setup_second_app_mapped_to_the_same_rule(api)

    _rows, meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, {"guideline_rule_id": ctx.rules["privacy"]}
        )
    )
    assert meta["total_count"] == 2

    second_app = ctx.app()
    assert_decimal_equals(second_app["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(second_app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])

    first_app = get_success_data(
        api.get_app_record(first_app_id, ctx.release_manager)
    )
    assert_decimal_equals(first_app["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(first_app, "OPEN", [])


# ---------------------------------------------------------------------------
# provisioning_profile_self_referential_linked_cert_edge_is_queryable
# ---------------------------------------------------------------------------
def test_the_linked_cert_edge_is_directed_from_profile_to_certificate(api):
    """"A distribution certificate requires the opposite: `linked_cert_id` must be null,
    and its `key_custody` may not be `LOCAL_KEYCHAIN` — a root signing key held in a local
    keychain is never acceptable and is refused with `ERR_KEY_CUSTODY_NOT_PERMITTED`."

    Design: Corner/entities/provisioning_profile_self_referential_linked_cert_edge_is_queryable
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    add_credentials(ctx)

    rows, meta = validate_paginated(
        api.list_signing_credentials(
            make_auditor_headers(), {"linked_cert_id": ctx.cert_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx.profile_id
    assert rows[0]["credential_type"] == "PROVISIONING_PROFILE"

    cert = get_success_data(
        api.get_signing_credential(ctx.cert_id, make_auditor_headers())
    )
    assert cert["linked_cert_id"] is None

    _reverse, reverse_meta = validate_paginated(
        api.list_signing_credentials(
            make_auditor_headers(), {"linked_cert_id": ctx.profile_id}
        )
    )
    assert reverse_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# guideline_rule_supersedes_self_referential_edge_is_queryable
# ---------------------------------------------------------------------------
def test_the_supersedes_edge_is_queryable_before_any_cascade_runs(api):
    """"Rules are filterable by `supersedes_rule_id`, `category`, `status`,
    `version_label` and `requires_feature_mapping`."

    Design: Corner/entities/guideline_rule_supersedes_self_referential_edge_is_queryable
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    predecessor = add_effective_rule(ctx)

    successor = validate_success(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code=predecessor["rule_code"],
                title="Data Collection and Storage",
                version_label="2026.09",
                effective_from="2026-07-20T00:00:00Z",
                supersedes_rule_id=predecessor["id"],
            ),
            make_policy_admin_headers(),
        ),
        201,
    )
    assert successor["status"] == "DRAFT"
    assert successor["supersedes_rule_id"] == predecessor["id"]

    still_effective = get_success_data(
        api.get_guideline_rule(predecessor["id"], make_auditor_headers())
    )
    assert still_effective["status"] == "EFFECTIVE"

    rows, meta = validate_paginated(
        api.list_guideline_rules(
            make_auditor_headers(), {"supersedes_rule_id": predecessor["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]
