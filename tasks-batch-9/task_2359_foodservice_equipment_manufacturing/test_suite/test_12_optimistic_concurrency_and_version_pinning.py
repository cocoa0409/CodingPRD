"""Stale-parent rejection on the two versioned creates, model revision, and the release pin."""

from test_helpers import (
    ApiErrorId,
    chain_configuration_payload,
    create_chain_account,
    create_chain_configuration,
    create_equipment_model,
    engineering_decision_payload,
    performance_validation_payload,
    read_chain_account,
    read_chain_configuration,
    read_performance_validation,
    request_configuration_revision,
    set_clock,
    setup_approved_configuration,
    setup_listed_model,
    setup_passed_validation,
    sign_off_branding,
    submit_configuration,
    validate_error,
    validate_paginated,
    validate_success,
)

DIAL_ONLY = {"supported_controls_packages": ["STANDARD_DIAL"]}
PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}
REPRICED_BASE_CENTS = 2000060


class TestStaleChainAccountVersion:
    def test_a_configuration_create_must_echo_the_accounts_current_version(
        self, api, application_engineer, channel_manager
    ):
        """Version 1 is refused with 412 after a PATCH; the re-read version 2 succeeds.

        PRD §2.7: "A `POST /chain-configurations` request must carry
        `expected_chain_account_version` as a required input field, holding the `version` of
        the target `ChainAccount` as the client last read it. If that value does not equal the
        account's current `version`, the create is rejected with
        `ERR_STALE_CHAIN_ACCOUNT_VERSION` and HTTP 412."

        PRD §3.3: "The volume discount comes from the parent chain account's
        `contracted_unit_volume`, in three inclusive tiers: a contracted volume of at least
        500 units earns twelve percent, at least 200 earns eight percent, at least 50 earns
        four percent, and anything below 50 earns nothing."

        Design: Corner/cross_cutting_complexity_layers/stale_chain_account_version_blocks_configuration_creation_until_re_read
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        assert account["version"] == 1, (
            f"a freshly opened account is at version 1, got {account['version']}"
        )

        patched = validate_success(
            api.patch_chain_account(
                account["id"],
                {"dealer_of_record": "Northeast Foodservice Supply"},
                channel_manager,
            )
        )
        assert patched["version"] == 2, (
            "revising the channel attribution increments the account version, got "
            f"{patched['version']}"
        )

        stale = api.create_chain_configuration(
            chain_configuration_payload(
                account["id"], model["id"], 1, config_code="CFG-1", **PLAIN_CONFIG
            ),
            application_engineer,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CHAIN_ACCOUNT_VERSION.value, 412)

        _data, meta = validate_paginated(
            api.list_chain_configurations(application_engineer, {"limit": 100})
        )
        assert meta["total_count"] == 0, (
            "every other field was valid, but the stale token means no configuration was "
            f"written, got {meta['total_count']}"
        )

        fresh = validate_success(
            api.create_chain_configuration(
                chain_configuration_payload(
                    account["id"], model["id"], 2, config_code="CFG-1", **PLAIN_CONFIG
                ),
                application_engineer,
            ),
            201,
        )
        assert fresh["status"] == "DRAFT", (
            f"the retry against the re-read version is accepted, got {fresh['status']}"
        )
        assert fresh["indicative_unit_price_cents"] == 1702018, (
            "1850020 discounted by the eight percent tier for 250 contracted units rounds "
            f"half up to 1702018, got {fresh['indicative_unit_price_cents']}"
        )

        reread = read_chain_account(account["id"])
        assert reread["version"] == 3, (
            "the accepted create increments the parent chain account's version by one, "
            f"taking the re-read account from 2 to 3, got {reread['version']}"
        )


class TestStaleConfigurationVersion:
    def test_a_validation_create_carrying_the_old_token_supersedes_nothing(
        self, api, application_engineer
    ):
        """The stale FRIES create is refused with 412 and leaves the PASSED run alone.

        PRD §2.7: "A `POST /performance-validations` request must likewise carry
        `expected_chain_configuration_version` as a required input field, holding the
        `version` of the target `ChainConfiguration` as the client last read it. A mismatch
        with the configuration's current `version` is rejected with
        `ERR_STALE_CONFIGURATION_VERSION` and HTTP 412, because a new validation for the same
        configuration and menu item supersedes the prior one, and a writer working from a
        stale configuration view would supersede a validation produced against a
        configuration revision it never saw."

        Design: Corner/cross_cutting_complexity_layers/stale_configuration_version_blocks_a_superseding_performance_validation
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        config = create_chain_configuration(
            account["id"], model["id"], config_code="CFG-1", **PLAIN_CONFIG
        )
        stale_version = config["version"]

        first = setup_passed_validation(
            config["id"], expected_chain_configuration_version=stale_version
        )
        assert first["status"] == "PASSED", (
            f"the first FRIES series certifies the menu item, got {first['status']}"
        )

        refreshed = read_chain_configuration(config["id"])
        assert refreshed["version"] > stale_version, (
            "opening and concluding the validation moved the configuration on from "
            f"{stale_version}, got {refreshed['version']}"
        )

        refused = api.create_performance_validation(
            performance_validation_payload(config["id"], stale_version),
            application_engineer,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_CONFIGURATION_VERSION.value, 412)

        untouched = read_performance_validation(first["id"])
        assert untouched["status"] == "PASSED", (
            "the refused create superseded nothing, got "
            f"{untouched['status']}"
        )

        second = validate_success(
            api.create_performance_validation(
                performance_validation_payload(config["id"], refreshed["version"]),
                application_engineer,
            ),
            201,
        )
        assert second["status"] == "IN_PROGRESS", (
            f"the retry opens a fresh attempt, got {second['status']}"
        )

        superseded = read_performance_validation(first["id"])
        assert superseded["status"] == "SUPERSEDED", (
            "and only now does the earlier FRIES validation give way, got "
            f"{superseded['status']}"
        )


class TestModelVersionPin:
    def test_a_model_patched_after_approval_blocks_the_release(
        self, api, application_engineer, compliance_engineer, engineering_approver
    ):
        """The pin stays at 2 while the model moves to 3, so the release is refused.

        PRD §3.5: "Third, `pinned_model_version` must still equal the model's current
        `version`; if the catalogue was revised in between, the release is rejected with
        `ERR_MODEL_VERSION_PIN_STALE` and the configuration must go back through review."

        PRD §3.1: "Any successful revision increments the model's `version` by one and
        deliberately leaves the `pinned_model_version` of every already-approved
        configuration untouched, so a revision made between engineering approval and release
        is caught at release time with `ERR_MODEL_VERSION_PIN_STALE` rather than silently
        shipping an unreviewed revision."

        Design: Corner/cross_cutting_complexity_layers/a_model_patched_after_approval_invalidates_the_pin_and_blocks_release
        """
        state = setup_approved_configuration(
            model_overrides=DIAL_ONLY, config_overrides=PLAIN_CONFIG
        )
        config = state["config"]
        model_id = state["model"]["id"]

        assert config["status"] == "ENG_APPROVED", (
            f"the package cleared engineering review, got {config['status']}"
        )
        assert config["pinned_model_version"] == 2, (
            "approval pins the model revision it reviewed, which the agency grant had "
            f"already moved to 2, got {config['pinned_model_version']}"
        )

        patched = validate_success(
            api.patch_equipment_model(
                model_id, {"base_price_cents": REPRICED_BASE_CENTS}, compliance_engineer
            )
        )
        assert patched["version"] == 3, (
            f"the repricing moves the catalogue row to version 3, got {patched['version']}"
        )
        assert patched["certification_posture"] == "LISTED", (
            "and leaves the certification posture alone, got "
            f"{patched['certification_posture']}"
        )

        refused = api.release_chain_configuration(
            config["id"], {}, application_engineer
        )
        validate_error(refused, ApiErrorId.ERR_MODEL_VERSION_PIN_STALE.value)
        assert (
            refused.json()["data"]["error_id"] != ApiErrorId.ERR_MODEL_NOT_LISTED.value
        ), (
            "the model is still fully listed, so the refusal must name the stale pin rather "
            "than the posture gate"
        )

        stuck = read_chain_configuration(config["id"])
        assert stuck["status"] == "ENG_APPROVED", (
            f"the refused release left the configuration in place, got {stuck['status']}"
        )
        assert stuck["firm_unit_price_cents"] is None, (
            "and stamped no firm price, got "
            f"{stuck['firm_unit_price_cents']}"
        )
        assert stuck["pinned_model_version"] == 2, (
            "while the pin itself is never refreshed by a catalogue revision, got "
            f"{stuck['pinned_model_version']}"
        )

        reopen = api.record_engineering_decision(
            config["id"],
            engineering_decision_payload(
                "REQUEST_REVISION",
                revision_note="Re-approve against the repriced model",
            ),
            engineering_approver,
        )
        validate_error(reopen, ApiErrorId.ERR_CONFIGURATION_STATE_INVALID.value, 409)


class TestModelPatchIsPartial:
    def test_patching_the_base_price_leaves_the_other_attributes_and_bumps_the_version(
        self, api, compliance_engineer, production_planner
    ):
        """Only `base_price_cents` moves; version goes 1 to 2 and later pricing follows.

        PRD §3.1: "A `ComplianceEngineer` may also revise a model's commercial and capability
        attributes, supplying any of `base_price_cents`, `supported_controls_packages` and
        `rated_throughput_units_per_hour`."

        PRD §2.4: "**`version`** (integer): a system-managed counter that begins at 1 and
        increments by one on every mutation of that resource."

        Design: Corner/endpoints/model_patch_updates_only_the_supplied_fields_and_bumps_the_version
        """
        set_clock()
        model = create_equipment_model(
            supported_controls_packages=["STANDARD_DIAL", "TOUCH_PRO"]
        )
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        assert model["version"] == 1, (
            f"a newly catalogued model is at version 1, got {model['version']}"
        )

        patched = validate_success(
            api.patch_equipment_model(
                model["id"],
                {"base_price_cents": REPRICED_BASE_CENTS},
                compliance_engineer,
            )
        )
        assert patched["version"] == 2, (
            f"the revision counts as one mutation, got {patched['version']}"
        )
        assert patched["base_price_cents"] == REPRICED_BASE_CENTS, (
            f"the supplied field is applied, got {patched['base_price_cents']}"
        )
        assert patched["supported_controls_packages"] == ["STANDARD_DIAL", "TOUCH_PRO"], (
            "an omitted field keeps its created value, got "
            f"{patched['supported_controls_packages']}"
        )
        assert patched["rated_throughput_units_per_hour"] == 120, (
            "as does the rated throughput, got "
            f"{patched['rated_throughput_units_per_hour']}"
        )
        assert patched["created_at"] == model["created_at"], (
            f"and creation is never rewritten, got {patched['created_at']}"
        )
        assert patched["updated_at"] >= model["created_at"], (
            "while the mutation refreshes updated_at, got "
            f"{patched['updated_at']}"
        )

        seen = validate_success(
            api.get_equipment_model(model["id"], production_planner)
        )
        assert seen["base_price_cents"] == REPRICED_BASE_CENTS, (
            f"every reader sees the new base, got {seen['base_price_cents']}"
        )
        assert seen["certification_posture"] == "UNLISTED", (
            "no listing was ever granted for this model, got "
            f"{seen['certification_posture']}"
        )

        config = create_chain_configuration(
            account["id"], model["id"], config_code="CFG-1", **PLAIN_CONFIG
        )
        assert config["indicative_unit_price_cents"] == 1840055, (
            "a configuration created afterwards prices against the revised base: 2000060 "
            "less the eight percent volume discount rounds half up to 1840055, got "
            f"{config['indicative_unit_price_cents']}"
        )


class TestRequestRevisionReopensTheConfiguration:
    def test_requesting_a_revision_clears_the_branding_gate_and_reopens_review(self):
        """REQUEST_REVISION stores the note, resets the sign-off and re-submission bumps revision.

        PRD §3.5: "**Requesting a revision** takes the configuration
        `ENG_REVIEW → REVISION_REQUESTED`. It requires a non-empty `revision_note`, stores
        that text on the configuration, sets `branding_signed_off` back to false so the chain
        must re-approve artwork against the revised package, and deliberately leaves
        `pinned_model_version` null — nothing was reviewed to completion, so nothing is
        pinned."

        PRD §3.5: "Both submission paths record the acting `X-User-ID` in
        `submitted_by_user_id`; only the `REVISION_REQUESTED → ENG_REVIEW` path increments
        `revision` by one."

        Design: Corner/endpoints/request_revision_clears_the_branding_signoff_and_reopens_the_configuration
        """
        set_clock()
        listed = setup_listed_model(**DIAL_ONLY)
        account = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        config = create_chain_configuration(
            account["id"],
            listed["model"]["id"],
            config_code="CFG-1",
            option_codes=[],
            controls_package="STANDARD_DIAL",
            branding_kit="FULL_WRAP",
        )
        assert config["branding_signed_off"] is False, (
            "a new configuration has no artwork sign-off yet, got "
            f"{config['branding_signed_off']}"
        )
        assert config["revision"] == 0, (
            f"and no revisions behind it, got {config['revision']}"
        )

        validation = setup_passed_validation(config["id"])
        assert validation["status"] == "PASSED", (
            f"the menu item is proven on the package, got {validation['status']}"
        )

        in_review = submit_configuration(config["id"])
        assert in_review["status"] == "ENG_REVIEW", (
            f"submission opens engineering review, got {in_review['status']}"
        )
        assert in_review["submitted_by_user_id"] == "eng-1", (
            "and records the acting engineer, got "
            f"{in_review['submitted_by_user_id']}"
        )

        signed = sign_off_branding(
            config["id"], account["id"], approved_artwork_ref="ART-FULLWRAP-1"
        )
        assert signed["branding_signed_off"] is True, (
            "the chain may sign artwork off during review, got "
            f"{signed['branding_signed_off']}"
        )
        assert signed["status"] == "ENG_REVIEW", (
            f"which does not move the review state, got {signed['status']}"
        )

        reopened = request_configuration_revision(
            config["id"], "Move the wrap seam behind the door hinge"
        )
        assert reopened["status"] == "REVISION_REQUESTED", (
            f"the approver hands the package back, got {reopened['status']}"
        )
        assert reopened["revision_note"] == "Move the wrap seam behind the door hinge", (
            f"storing the note verbatim, got {reopened['revision_note']!r}"
        )
        assert reopened["branding_signed_off"] is False, (
            "and resetting the artwork gate so the chain must look again, got "
            f"{reopened['branding_signed_off']}"
        )
        assert reopened["pinned_model_version"] is None, (
            "nothing was reviewed to completion, so nothing is pinned, got "
            f"{reopened['pinned_model_version']}"
        )
        assert reopened["approved_by_user_id"] is None, (
            "and no approver is recorded, got "
            f"{reopened['approved_by_user_id']}"
        )

        resubmitted = submit_configuration(config["id"])
        assert resubmitted["status"] == "ENG_REVIEW", (
            f"the round trip returns the package to review, got {resubmitted['status']}"
        )
        assert resubmitted["revision"] == 1, (
            "and only this path increments the revision counter, got "
            f"{resubmitted['revision']}"
        )

        reused = read_performance_validation(validation["id"])
        assert reused["status"] == "PASSED", (
            "the passed validation is reused rather than reset, got "
            f"{reused['status']}"
        )
