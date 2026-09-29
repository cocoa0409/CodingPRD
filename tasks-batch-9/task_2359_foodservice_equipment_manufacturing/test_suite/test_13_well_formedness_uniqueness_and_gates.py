"""Optional fields, server-minted system fields, enum and foreign-key screening, code scopes and review gates."""

from test_helpers import (
    ApiErrorId,
    add_test_runs,
    assert_common_fields,
    assert_utc_millisecond_timestamp,
    chain_account_payload,
    chain_configuration_payload,
    create_chain_account,
    create_chain_configuration,
    create_equipment_model,
    equipment_model_payload,
    is_valid_uuid,
    open_performance_validation,
    read_chain_account,
    read_chain_configuration,
    set_clock,
    setup_listed_model,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ACCOUNT_ID = "00000000-0000-4000-8000-000000000000"
DIAL_ONLY = {"supported_controls_packages": ["STANDARD_DIAL"]}
PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}


class TestChainAccountOptionalAttribution:
    def test_the_channel_attributions_stay_null_until_a_patch_supplies_them(
        self, api, channel_manager
    ):
        """Both optional fields are null on create and settable later without side effects.

        PRD §3.3: "A `ChannelManager` opens a **chain account** with an `account_code` unique
        across all accounts, the chain's legal `name`, a `contracted_unit_volume` of zero or
        more, and optionally a `dealer_of_record` — the dealer whose specification-writing
        influence is credited on quotes for the chain — and a `consultant_firm`, the kitchen
        consultant named on the chain's specification package. Both channel attributions
        default to null."

        Design: Corner/entities/chain_account_optional_dealer_and_consultant_fields_stay_null_when_omitted
        """
        set_clock()

        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        assert account["dealer_of_record"] is None, (
            "the omitted dealer attribution defaults to null, got "
            f"{account['dealer_of_record']!r}"
        )
        assert account["consultant_firm"] is None, (
            "as does the consultant attribution, got "
            f"{account['consultant_firm']!r}"
        )

        patched = validate_success(
            api.patch_chain_account(
                account["id"],
                {
                    "dealer_of_record": "Northeast Restaurant Supply",
                    "consultant_firm": "Hearth Design Group",
                },
                channel_manager,
            )
        )
        assert patched["dealer_of_record"] == "Northeast Restaurant Supply", (
            f"the revision credits the dealer, got {patched['dealer_of_record']!r}"
        )
        assert patched["consultant_firm"] == "Hearth Design Group", (
            f"and names the consultant, got {patched['consultant_firm']!r}"
        )
        assert patched["contracted_unit_volume"] == 250, (
            "without disturbing the contracted volume, got "
            f"{patched['contracted_unit_volume']}"
        )
        assert patched["version"] == 2, (
            f"one revision means one version increment, got {patched['version']}"
        )


class TestServerMintedSystemFields:
    def test_a_new_chain_account_carries_a_bare_uuid_equal_stamps_and_version_one(
        self, api, channel_manager
    ):
        """The server mints id, created_at, updated_at and version; the client cannot.

        PRD §2.4: "**`id`** (string): a server-minted UUID. It carries no type prefix."

        PRD §2.4: "**`created_at`** (string): an ISO 8601 timestamp in UTC with three
        fractional digits (for example `2026-08-01T00:00:00.000Z`), recorded when the row was
        first created."

        PRD §2.4: "**`version`** (integer): a system-managed counter that begins at 1 and
        increments by one on every mutation of that resource."

        Design: Corner/entities/chain_account_system_fields_minted_by_server_with_version_one
        """
        set_clock()

        account = validate_success(
            api.create_chain_account(
                chain_account_payload(account_code="CHN-1"), channel_manager
            ),
            201,
        )
        assert_common_fields(account, "chain account")
        assert is_valid_uuid(account["id"]), (
            f"the identifier is a bare UUID with no type prefix, got {account['id']!r}"
        )
        assert account["version"] == 1, (
            f"a freshly minted row starts at version 1, got {account['version']}"
        )
        assert_utc_millisecond_timestamp(account["created_at"], "created_at")
        assert_utc_millisecond_timestamp(account["updated_at"], "updated_at")
        assert account["created_at"] == account["updated_at"], (
            "nothing has mutated the row since it was written, so both stamps agree, got "
            f"{account['created_at']} / {account['updated_at']}"
        )
        assert account["created_at"].startswith("2026-08-01T00:00:00"), (
            "and both read the logical clock rather than wall-clock time, got "
            f"{account['created_at']}"
        )


class TestClosedEnumScreening:
    def test_a_category_outside_the_five_families_is_a_malformed_request(
        self, api, compliance_engineer
    ):
        """`SALAMANDER` is rejected with ERR_INVALID_REQUEST and stores nothing.

        PRD §3.1: "A `ComplianceEngineer` creates one by supplying a `model_code` (between 1
        and 32 characters, unique across the catalogue; a collision is rejected with
        `ERR_DUPLICATE_RESOURCE_CODE`), a marketing `name`, a `category` drawn from `FRYER`,
        `COMBI_OVEN`, `GRIDDLE`, `DISHWASHER` and `HOLDING_CABINET`, an `energy_type` of
        `GAS`, `ELECTRIC` or `DUAL`, a `base_price_cents` of at least 1, a non-empty
        `supported_controls_packages` array drawn from `STANDARD_DIAL`, `TOUCH_PRO` and
        `CONNECT_PLUS` (`STANDARD_DIAL` is always an allowed member), and a
        `rated_throughput_units_per_hour` greater than zero that acts as the ceiling on every
        menu-item throughput target later written against the model."

        PRD §2.9: "Payload well-formedness — required fields present, enum members valid,
        integers inside their declared bounds, datetimes ISO 8601 UTC, `window_end` strictly
        later than `window_start`, `limit` between 1 and 100 inclusive, `offset` at least 0,
        and array-valued fields free of duplicate elements. Applies to every endpoint.
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/equipment_model_invalid_category_enum_returns_invalid_request
        """
        set_clock()

        refused = api.create_equipment_model(
            equipment_model_payload(
                model_code="SAL-100",
                name="Salamander 100",
                category="SALAMANDER",
                energy_type="GAS",
                base_price_cents=500000,
                supported_controls_packages=["STANDARD_DIAL"],
                rated_throughput_units_per_hour=40,
            ),
            compliance_engineer,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        data, meta = validate_paginated(
            api.list_equipment_models(compliance_engineer, {"limit": 100})
        )
        assert meta["total_count"] == 0, (
            "a plausible-but-absent enum member is never stored, got "
            f"{meta['total_count']} catalogue rows"
        )
        assert [row["model_code"] for row in data] == [], (
            f"so SAL-100 does not appear in the catalogue, got {data}"
        )


class TestForeignKeyResolutionPrecedesTheVersionToken:
    def test_an_unknown_chain_account_is_a_404_not_a_stale_version_412(
        self, api, application_engineer
    ):
        """The FK check answers first, even though the token cannot match the missing row.

        PRD §2.9: "The chain account, chain configuration, performance validation,
        construction programme or site order named in the path or body resolves. Applies to
        `GET /chain-accounts/{id}`, `PATCH /chain-accounts/{id}`, `POST /chain-configurations`,
        `GET /chain-configurations/{id}`, `GET /chain-configurations/{id}/price-quote`,
        `POST /chain-configurations/{id}/submissions`,
        `POST /chain-configurations/{id}/engineering-decisions`,
        `POST /chain-configurations/{id}/branding-signoff`,
        `POST /chain-configurations/{id}/release`, `POST /performance-validations`,
        `GET /performance-validations/{id}`, `POST /performance-validations/{id}/test-runs`,
        `POST /performance-validations/{id}/conclusion`,
        `POST /performance-validations/{id}/retest`, `POST /construction-programs`,
        `GET /construction-programs/{id}`, `POST /site-orders`, `GET /site-orders/{id}`,
        `POST /site-orders/{id}/commitment-waiver`,
        `POST /site-orders/{id}/fulfillment-events`, `POST /production-slots` and
        `POST /connected-units`. `ERR_CHAIN_RESOURCE_NOT_FOUND`."

        Design: Corner/entities/chain_configuration_with_unknown_chain_account_returns_chain_resource_not_found
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)

        missing_parent = api.create_chain_configuration(
            chain_configuration_payload(
                UNKNOWN_ACCOUNT_ID,
                model["id"],
                account["version"],
                config_code="CFG-1",
                **PLAIN_CONFIG,
            ),
            application_engineer,
        )
        validate_error(missing_parent, ApiErrorId.ERR_CHAIN_RESOURCE_NOT_FOUND.value, 404)
        assert (
            missing_parent.json()["data"]["error_id"]
            != ApiErrorId.ERR_STALE_CHAIN_ACCOUNT_VERSION.value
        ), (
            "the body's foreign key is resolved at check 8, before the version token is "
            "compared at check 13"
        )

        _data, meta = validate_paginated(
            api.list_chain_configurations(application_engineer, {"limit": 100})
        )
        assert meta["total_count"] == 0, (
            f"the refused create wrote no configuration, got {meta['total_count']}"
        )

        accepted = validate_success(
            api.create_chain_configuration(
                chain_configuration_payload(
                    account["id"],
                    model["id"],
                    account["version"],
                    config_code="CFG-1",
                    **PLAIN_CONFIG,
                ),
                application_engineer,
            ),
            201,
        )
        assert accepted["status"] == "DRAFT", (
            f"naming the real account is accepted, got {accepted['status']}"
        )
        assert accepted["chain_account_id"] == account["id"], (
            f"and files the row under it, got {accepted['chain_account_id']}"
        )


class TestControlsPackageAllowList:
    def test_a_package_outside_the_models_allow_list_is_refused(
        self, api, application_engineer
    ):
        """TOUCH_PRO on a STANDARD_DIAL-only model is 422; STANDARD_DIAL on it is 201.

        PRD §3.3: "The controls package must be a member of the model's
        `supported_controls_packages`; asking for `TOUCH_PRO` on a model that supports only
        `STANDARD_DIAL` is rejected with `ERR_CONTROLS_PACKAGE_UNSUPPORTED`."

        Design: Corner/validations/unsupported_controls_package_is_rejected_at_configuration_creation
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)

        refused = api.create_chain_configuration(
            chain_configuration_payload(
                account["id"],
                model["id"],
                account["version"],
                config_code="CFG-BAD",
                option_codes=[],
                controls_package="TOUCH_PRO",
                branding_kit="NONE",
            ),
            application_engineer,
        )
        validate_error(
            refused, ApiErrorId.ERR_CONTROLS_PACKAGE_UNSUPPORTED.value, 422
        )

        accepted = validate_success(
            api.create_chain_configuration(
                chain_configuration_payload(
                    account["id"],
                    model["id"],
                    read_chain_account(account["id"])["version"],
                    config_code="CFG-OK",
                    **PLAIN_CONFIG,
                ),
                application_engineer,
            ),
            201,
        )
        assert accepted["controls_package"] == "STANDARD_DIAL", (
            "the supported package on the same pair is accepted, got "
            f"{accepted['controls_package']}"
        )
        assert accepted["status"] == "DRAFT", (
            f"and the row is authored as a draft, got {accepted['status']}"
        )

        data, meta = validate_paginated(
            api.list_chain_configurations(application_engineer, {"limit": 100})
        )
        assert meta["total_count"] == 1, (
            "the refused request created nothing, so only CFG-OK exists, got "
            f"{meta['total_count']}"
        )
        assert [row["config_code"] for row in data] == ["CFG-OK"], (
            f"and CFG-BAD is nowhere to be found, got {[r['config_code'] for r in data]}"
        )


class TestBusinessCodeUniquenessScopes:
    def test_the_model_code_is_global_while_the_config_code_is_per_chain(
        self, api, compliance_engineer, application_engineer
    ):
        """A second FRY-900 is refused, CFG-1 is free on another chain, and repeats are not.

        PRD §3.1: "A `ComplianceEngineer` creates one by supplying a `model_code` (between 1
        and 32 characters, unique across the catalogue; a collision is rejected with
        `ERR_DUPLICATE_RESOURCE_CODE`), a marketing `name`, a `category` drawn from `FRYER`,
        `COMBI_OVEN`, `GRIDDLE`, `DISHWASHER` and `HOLDING_CABINET`, an `energy_type` of
        `GAS`, `ELECTRIC` or `DUAL`, a `base_price_cents` of at least 1, a non-empty
        `supported_controls_packages` array drawn from `STANDARD_DIAL`, `TOUCH_PRO` and
        `CONNECT_PLUS` (`STANDARD_DIAL` is always an allowed member), and a
        `rated_throughput_units_per_hour` greater than zero that acts as the ceiling on every
        menu-item throughput target later written against the model."

        PRD §3.3: "An `ApplicationEngineer` authors a **chain configuration** — a
        chain-specific build of a base model — by naming the `chain_account_id` it belongs to
        and the `equipment_model_id` being customised, giving it a `config_code` that must be
        unique within that chain account, choosing `option_codes` from `SPLIT_TANK`,
        `HIGH_ALT`, `LEFT_HINGE` and `ENERGY_SAVER` (the array may be empty and may not repeat
        a code), selecting a `controls_package` from `STANDARD_DIAL`, `TOUCH_PRO` and
        `CONNECT_PLUS`, and selecting a `branding_kit` from `NONE`, `LOGO_BADGE` and
        `FULL_WRAP`."

        Design: Corner/validations/business_code_uniqueness_is_global_for_models_but_scoped_per_chain_for_configurations
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        first = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        second = create_chain_account(
            account_code="CHN-2", name="Griddle Group", contracted_unit_volume=60
        )
        original = create_chain_configuration(
            first["id"], model["id"], config_code="CFG-1", **PLAIN_CONFIG
        )

        clone = api.create_equipment_model(
            equipment_model_payload(name="Fryer 900 Clone", base_price_cents=1900000,
                                    **DIAL_ONLY),
            compliance_engineer,
        )
        validate_error(clone, ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE.value, 409)

        elsewhere = validate_success(
            api.create_chain_configuration(
                chain_configuration_payload(
                    second["id"],
                    model["id"],
                    second["version"],
                    config_code="CFG-1",
                    **PLAIN_CONFIG,
                ),
                application_engineer,
            ),
            201,
        )
        assert elsewhere["id"] != original["id"], (
            "the same config code on a different chain account is a distinct row, got "
            f"{elsewhere['id']}"
        )
        assert elsewhere["indicative_unit_price_cents"] == 1776019, (
            "CHN-2's 60 contracted units earn the four percent tier, so 1850020 less a "
            f"74001 discount is 1776019, got {elsewhere['indicative_unit_price_cents']}"
        )

        repeat = api.create_chain_configuration(
            chain_configuration_payload(
                first["id"],
                model["id"],
                read_chain_account(first["id"])["version"],
                config_code="CFG-1",
                **PLAIN_CONFIG,
            ),
            application_engineer,
        )
        validate_error(repeat, ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE.value, 409)

        still_draft = read_chain_configuration(original["id"])
        assert still_draft["status"] == "DRAFT", (
            "the refused repeat superseded nothing, got "
            f"{still_draft['status']}"
        )


class TestReviewGatesCannotBeSkipped:
    def test_submission_needs_a_passed_validation_and_release_needs_the_approved_state(
        self, api, application_engineer
    ):
        """An IN_PROGRESS validation blocks submission; a DRAFT configuration blocks release.

        PRD §3.5: "It requires that at least one performance validation child of the
        configuration be `PASSED`; a configuration with only in-progress or failed menu-item
        tests is rejected with `ERR_PERFORMANCE_VALIDATION_NOT_PASSED`."

        PRD §3.5: "First, `branding_signed_off` must be true; a release attempted from a state
        other than `ENG_APPROVED`, or with the branding gate still open, is rejected with
        `ERR_CONFIGURATION_STATE_INVALID`."

        Design: Corner/validations/submission_needs_a_passed_validation_and_release_needs_engineering_approval
        """
        set_clock()
        listed = setup_listed_model(**DIAL_ONLY)
        assert listed["model"]["certification_posture"] == "LISTED", (
            "the model is fully listed, so no listing rule can fire here, got "
            f"{listed['model']['certification_posture']}"
        )
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        config = create_chain_configuration(
            account["id"], listed["model"]["id"], config_code="CFG-1", **PLAIN_CONFIG
        )
        assert config["status"] == "DRAFT", (
            f"the configuration is still a draft, got {config['status']}"
        )

        validation = open_performance_validation(config["id"])
        add_test_runs(validation["id"], [(95, 90, 175.0)])

        premature = api.submit_chain_configuration(
            config["id"], {}, application_engineer
        )
        validate_error(
            premature, ApiErrorId.ERR_PERFORMANCE_VALIDATION_NOT_PASSED.value, 422
        )

        skipped = api.release_chain_configuration(
            config["id"], {}, application_engineer
        )
        validate_error(skipped, ApiErrorId.ERR_CONFIGURATION_STATE_INVALID.value, 409)
        assert (
            skipped.json()["data"]["error_id"]
            != ApiErrorId.ERR_MODEL_NOT_LISTED.value
        ), (
            "the state gate at check 17 answers before the posture gate at check 26, and "
            "the model is listed anyway"
        )

        untouched = read_chain_configuration(config["id"])
        assert untouched["status"] == "DRAFT", (
            "neither refusal moved the configuration, got "
            f"{untouched['status']}"
        )
        assert untouched["firm_unit_price_cents"] is None, (
            "and nothing stamped a firm price, got "
            f"{untouched['firm_unit_price_cents']}"
        )
