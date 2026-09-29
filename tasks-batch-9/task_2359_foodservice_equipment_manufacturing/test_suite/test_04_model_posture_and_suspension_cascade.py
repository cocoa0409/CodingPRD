"""Derived model posture and the six-hop compliance cascade an agency suspension triggers."""

from test_helpers import (
    ApiErrorId,
    advance_slot,
    approve_configuration,
    create_build_line,
    create_chain_account,
    create_chain_configuration,
    create_connected_unit,
    create_construction_program,
    create_equipment_model,
    create_site_order,
    file_certification_listing,
    grant_certification_listing,
    read_build_line,
    read_chain_configuration,
    read_certification_listing,
    read_connected_unit,
    read_construction_program,
    read_equipment_model,
    read_production_slot,
    read_site_order,
    record_agency_decision,
    reserve_production_slot,
    set_clock,
    setup_passed_validation,
    setup_program_with_site_order,
    setup_released_configuration,
    submit_certification_listing,
    submit_configuration,
    validate_error,
    validate_success,
)

DUAL_MODEL = {
    "model_code": "GRL-500",
    "name": "Griddle 500",
    "category": "GRIDDLE",
    "energy_type": "DUAL",
    "base_price_cents": 1850020,
    "supported_controls_packages": ["STANDARD_DIAL", "TOUCH_PRO"],
    "rated_throughput_units_per_hour": 90,
}

PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}


def _breached_programme():
    """A programme whose only breaching site order is SITE-2, on a released ELECTRIC build."""
    state = setup_released_configuration(
        model_overrides={"supported_controls_packages": ["STANDARD_DIAL"]},
        config_overrides=PLAIN_CONFIG,
    )
    account_id = state["chain_account"]["id"]
    program = create_construction_program(account_id)
    site_one = create_site_order(
        program["id"], state["config"]["id"], account_id, site_code="SITE-1"
    )
    site_two = create_site_order(
        program["id"],
        state["config"]["id"],
        account_id,
        site_code="SITE-2",
        committed_delivery_date="2026-09-14T00:00:00Z",
        unit_count=20,
    )
    line_one = create_build_line(line_code="LN-1")
    line_two = create_build_line(line_code="LN-2")
    slot_one = reserve_production_slot(line_one["id"], site_one["id"])
    slot_two = reserve_production_slot(line_two["id"], site_two["id"], units=20)
    state.update(
        {
            "program": program,
            "site_one": site_one,
            "site_two": site_two,
            "line_one": line_one,
            "line_two": line_two,
            "slot_one": slot_one,
            "slot_two": slot_two,
        }
    )
    return state


class TestSuspensionCascade:
    def test_one_suspension_walks_six_hops_and_flips_the_programme_back_to_on_track(
        self,
    ):
        """The suspension cancels both slots, resets both site orders and un-breaches the programme.

        PRD §3.2: "**Hop five.** Each site order left with no slot in `RESERVED`,
        `CONFIRMED`, `IN_BUILD` or `COMPLETED` is reset: `fulfillment_status` back to
        `PENDING`, `commitment_status` back to `UNSCHEDULED`, and
        `projected_delivery_date` and `slack_days` back to null."

        Design: Difficulty/transitive_cascade/listing_suspension_cascades_six_hops_to_program_commit_posture
        """
        state = _breached_programme()
        account_id = state["chain_account"]["id"]
        before = read_construction_program(state["program"]["id"], account_id)
        assert before["commit_posture"] == "BREACHED", (
            "SITE-2 projects 2026-09-18 against a 2026-09-14 promise, a shortfall of "
            f"four days, so the programme starts BREACHED, got {before['commit_posture']}"
        )

        record_agency_decision(
            state["listing"]["id"],
            "SUSPEND",
            conditions_note="field failure on drain interlock",
        )

        listing = read_certification_listing(state["listing"]["id"])
        assert listing["status"] == "SUSPENDED", (
            f"hop one moves the listing to SUSPENDED, got {listing['status']}"
        )
        model = read_equipment_model(state["model"]["id"])
        assert model["certification_posture"] == "SUSPENDED", (
            f"hop two forces the model's posture to SUSPENDED, got "
            f"{model['certification_posture']}"
        )
        config = read_chain_configuration(state["config"]["id"])
        assert config["status"] == "COMPLIANCE_HOLD", (
            f"hop three pushes the released configuration onto a compliance hold, got "
            f"{config['status']}"
        )
        for key in ("slot_one", "slot_two"):
            slot = read_production_slot(state[key]["id"])
            assert slot["status"] == "CANCELLED", (
                f"hop four cancels the reserved slot {slot['id']}, got {slot['status']}"
            )
        for key in ("line_one", "line_two"):
            line = read_build_line(state[key]["id"])
            assert line["committed_units"] == 0, (
                "hop four returns every cancelled slot's units to the line, so "
                f"committed_units falls to 0, got {line['committed_units']}"
            )
        first = read_site_order(state["site_one"]["id"])
        assert first["fulfillment_status"] == "PENDING", (
            f"hop five resets the fulfilment dimension, got {first['fulfillment_status']}"
        )
        assert first["commitment_status"] == "UNSCHEDULED", (
            f"hop five resets the commitment dimension, got {first['commitment_status']}"
        )
        assert first["projected_delivery_date"] is None, (
            f"hop five clears the projection, got {first['projected_delivery_date']}"
        )
        assert first["slack_days"] is None, (
            f"hop five clears the slack, got {first['slack_days']}"
        )
        second = read_site_order(state["site_two"]["id"])
        assert second["commitment_status"] == "UNSCHEDULED", (
            "the breaching site order is reset as well, got "
            f"{second['commitment_status']}"
        )
        after = read_construction_program(state["program"]["id"], account_id)
        assert after["commit_posture"] == "ON_TRACK", (
            "hop six re-derives the posture over an all-unscheduled child set, which "
            f"flips the programme from BREACHED back to ON_TRACK, got "
            f"{after['commit_posture']}"
        )

    def test_reinstatement_restores_the_configuration_but_not_the_cancelled_schedule(
        self,
    ):
        """Reinstating the listing revives the model and the configuration, never the slots.

        PRD §3.2: "What reinstatement does **not** do is un-cancel the production slots
        hop four killed or restore the site orders hop five reset; the factory schedule
        must be rebuilt by reserving new slots."

        Design: Difficulty/transitive_cascade/listing_suspension_cascades_six_hops_to_program_commit_posture
        """
        state = _breached_programme()
        account_id = state["chain_account"]["id"]
        firm_price = state["config"]["firm_unit_price_cents"]
        record_agency_decision(
            state["listing"]["id"],
            "SUSPEND",
            conditions_note="field failure on drain interlock",
        )

        reinstated = record_agency_decision(state["listing"]["id"], "REINSTATE")

        assert reinstated["status"] == "LISTED", (
            f"REINSTATE returns the listing to LISTED, got {reinstated['status']}"
        )
        model = read_equipment_model(state["model"]["id"])
        assert model["certification_posture"] == "LISTED", (
            "with no suspended child left and full coverage the posture returns to "
            f"LISTED, got {model['certification_posture']}"
        )
        config = read_chain_configuration(state["config"]["id"])
        assert config["status"] == "RELEASED", (
            f"the held configuration returns to RELEASED, got {config['status']}"
        )
        assert config["firm_unit_price_cents"] == firm_price, (
            "a compliance hold does not re-price a configuration, so the firm price is "
            f"still {firm_price}, got {config['firm_unit_price_cents']}"
        )
        for key in ("slot_one", "slot_two"):
            slot = read_production_slot(state[key]["id"])
            assert slot["status"] == "CANCELLED", (
                f"the cancelled slot {slot['id']} is not revived, got {slot['status']}"
            )
        for key in ("line_one", "line_two"):
            line = read_build_line(state[key]["id"])
            assert line["committed_units"] == 0, (
                "no capacity is re-committed by a reinstatement, got "
                f"{line['committed_units']}"
            )
        site = read_site_order(state["site_one"]["id"])
        assert site["fulfillment_status"] == "PENDING", (
            f"the reset site order stays PENDING, got {site['fulfillment_status']}"
        )
        assert site["commitment_status"] == "UNSCHEDULED", (
            f"the reset site order stays UNSCHEDULED, got {site['commitment_status']}"
        )
        program = read_construction_program(state["program"]["id"], account_id)
        assert program["commit_posture"] == "ON_TRACK", (
            "with every child still unscheduled the programme remains ON_TRACK, got "
            f"{program['commit_posture']}"
        )

    def test_suspension_cancels_the_reserved_slot_and_spares_the_in_build_one(
        self, api, production_planner
    ):
        """Hop four skips the IN_BUILD slot, which can then no longer be completed.

        PRD §3.2: "**Hop four.** Every production slot whose `status` is `RESERVED` or
        `CONFIRMED` and whose site order references one of those newly held
        configurations moves to `CANCELLED`, and the slot's `units` are subtracted from
        its build line's `committed_units`, restoring the capacity invariant of §2.11."

        Design: Corner/state_machines/suspension_cascade_cancels_reserved_slots_but_spares_the_in_build_slot
        """
        state = setup_program_with_site_order(
            model_overrides={"supported_controls_packages": ["STANDARD_DIAL"]},
            config_overrides=PLAIN_CONFIG,
            program_overrides={"site_count_planned": 3},
            site_order_overrides={"unit_count": 10},
        )
        line = create_build_line(
            daily_capacity_units=20, supported_energy_types=["ELECTRIC"]
        )
        slot_a = reserve_production_slot(
            line["id"],
            state["site_order"]["id"],
            window_start="2026-09-07T00:00:00Z",
            window_end="2026-09-08T00:00:00Z",
            units=10,
        )
        slot_b = reserve_production_slot(
            line["id"],
            state["site_order"]["id"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
            units=10,
        )
        set_clock("2026-09-07T00:00:00Z")
        advance_slot(slot_a["id"], "CONFIRM")
        advance_slot(slot_a["id"], "START")
        assert read_build_line(line["id"])["committed_units"] == 20, (
            "a RESERVED slot and an IN_BUILD slot are both counted states, so the line "
            "holds 20 units"
        )

        record_agency_decision(
            state["listing"]["id"],
            "SUSPEND",
            conditions_note="Gas train recall on the control valve",
        )

        assert read_production_slot(slot_a["id"])["status"] == "IN_BUILD", (
            "the in-build slot is outside the cancelled set, got "
            f"{read_production_slot(slot_a['id'])['status']}"
        )
        assert read_production_slot(slot_b["id"])["status"] == "CANCELLED", (
            "the reserved slot is cancelled, got "
            f"{read_production_slot(slot_b['id'])['status']}"
        )
        assert read_build_line(line["id"])["committed_units"] == 10, (
            "only the cancelled slot's ten units leave the line's commitment, got "
            f"{read_build_line(line['id'])['committed_units']}"
        )
        assert read_chain_configuration(state["config"]["id"])["status"] == (
            "COMPLIANCE_HOLD"
        ), "the released configuration still moves onto a compliance hold"
        site = read_site_order(state["site_order"]["id"])
        assert site["fulfillment_status"] == "IN_BUILD", (
            "a surviving counted slot means hop five does not fire, got "
            f"{site['fulfillment_status']}"
        )
        assert site["commitment_status"] == "COMMITTED", (
            f"the commitment dimension is re-scored, not reset, got "
            f"{site['commitment_status']}"
        )
        assert site["projected_delivery_date"].startswith("2026-09-15T00:00:00"), (
            "the projection re-selects the surviving slot, whose window ends 2026-09-08, "
            f"plus seven transit days, got {site['projected_delivery_date']}"
        )
        assert site["slack_days"] == 10, (
            "2026-09-25 less 2026-09-15 is ten days of slack, got "
            f"{site['slack_days']}"
        )

        refused = api.advance_build_progress(
            slot_a["id"], {"progress": "COMPLETE"}, production_planner
        )
        validate_error(refused, ApiErrorId.ERR_CONFIGURATION_NOT_RELEASED.value)
        assert read_production_slot(slot_a["id"])["status"] == "IN_BUILD", (
            "the refused completion leaves the spared slot in build"
        )

    def test_coverage_activation_is_blocked_while_the_listing_is_suspended(
        self, api, warranty_adjudicator
    ):
        """ACTIVATE is refused on a suspended model and succeeds after the reinstatement.

        PRD §3.9: "`ACTIVATE` takes a unit `PENDING_INSTALL → ACTIVE` and requires the
        unit's model to hold real agency coverage — its `certification_posture` must be
        `LISTED` or `PARTIAL`, and a `SUSPENDED` or `UNLISTED` model is rejected with
        `ERR_MODEL_LISTING_SUSPENDED`."

        Design: Corner/state_machines/coverage_activation_is_guarded_by_the_models_posture_and_blocked_while_suspended
        """
        set_clock()
        model = create_equipment_model(supported_controls_packages=["STANDARD_DIAL"])
        listing = file_certification_listing(model["id"])
        grant_certification_listing(listing["id"])
        unit = create_connected_unit(model["id"], service_tier="BASE")
        assert unit["service_program_status"] == "PENDING_INSTALL", (
            f"a new unit is uninstalled, got {unit['service_program_status']}"
        )
        record_agency_decision(
            listing["id"],
            "SUSPEND",
            conditions_note="Field sanitation finding pending re-inspection",
        )

        refused = api.coverage_action(
            unit["id"], {"action": "ACTIVATE"}, warranty_adjudicator
        )
        validate_error(refused, ApiErrorId.ERR_MODEL_LISTING_SUSPENDED.value)

        held = read_connected_unit(unit["id"])
        assert held["service_program_status"] == "PENDING_INSTALL", (
            f"the refused activation leaves the unit uninstalled, got "
            f"{held['service_program_status']}"
        )
        assert held["coverage_start_date"] is None, (
            f"no coverage window is stamped, got {held['coverage_start_date']}"
        )
        assert held["reserve_balance_cents"] == 0, (
            f"no reserve is funded, got {held['reserve_balance_cents']}"
        )

        record_agency_decision(listing["id"], "REINSTATE")
        activated = validate_success(
            api.coverage_action(unit["id"], {"action": "ACTIVATE"}, warranty_adjudicator)
        )

        assert activated["service_program_status"] == "ACTIVE", (
            f"the identical call now succeeds, got {activated['service_program_status']}"
        )
        assert activated["coverage_start_date"].startswith("2026-08-01T00:00:00"), (
            "activation stamps the coverage start with the logical clock, got "
            f"{activated['coverage_start_date']}"
        )
        assert activated["coverage_end_date"].startswith("2027-08-01T00:00:00"), (
            "a BASE unit gets a full year of 365 days, got "
            f"{activated['coverage_end_date']}"
        )
        assert activated["reserve_balance_cents"] == 250000, (
            "the BASE tier reserve is two hundred fifty thousand cents, got "
            f"{activated['reserve_balance_cents']}"
        )


class TestPostureDerivation:
    def test_a_new_model_reports_its_required_scopes_with_no_coverage_at_all(self):
        """An ELECTRIC model is created with SANITATION and ELECTRICAL required and nothing covered.

        PRD §3.1: "A brand-new model starts with `covered_scopes` empty and a
        `certification_posture` of `UNLISTED`."

        Design: Corner/entities/equipment_model_creation_returns_computed_scopes_and_unlisted_posture
        """
        set_clock()

        model = create_equipment_model()

        assert model["required_scopes"] == ["SANITATION", "ELECTRICAL"], (
            "sanitation is always required and an electric model adds ELECTRICAL, in "
            f"the fixed scope order, got {model['required_scopes']}"
        )
        assert model["covered_scopes"] == [], (
            f"a model with no granted listing covers nothing, got {model['covered_scopes']}"
        )
        assert model["certification_posture"] == "UNLISTED", (
            f"the posture is never defaulted to LISTED, got {model['certification_posture']}"
        )
        assert model["base_price_cents"] == 1850020, (
            f"the catalogue price is stored as supplied, got {model['base_price_cents']}"
        )
        assert model["version"] == 1, (
            f"a freshly minted row is at version 1, got {model['version']}"
        )

    def test_granting_a_listing_rederives_the_posture_on_the_model_row(self):
        """The model flips UNLISTED to LISTED purely because a sibling listing was granted.

        PRD §3.1: "This recomputation runs on model creation, on every listing status
        change, and on every clock advance, and any change of value increments the
        model's `version` by one."

        Design: Corner/entities/equipment_model_posture_is_computed_and_rederived_when_a_listing_is_granted
        """
        set_clock()
        model = create_equipment_model(supported_controls_packages=["STANDARD_DIAL"])
        assert model["certification_posture"] == "UNLISTED", (
            f"the model starts unlisted, got {model['certification_posture']}"
        )
        listing = file_certification_listing(
            model["id"], "AGENCY_GAMMA", ["SANITATION", "ELECTRICAL"]
        )
        submit_certification_listing(listing["id"])
        record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")
        assert read_equipment_model(model["id"])["certification_posture"] == "UNLISTED", (
            "an acknowledged application still covers nothing"
        )

        record_agency_decision(listing["id"], "GRANT")

        rederived = read_equipment_model(model["id"])
        assert rederived["certification_posture"] == "LISTED", (
            "the grant closes every required scope in one step, got "
            f"{rederived['certification_posture']}"
        )
        assert rederived["covered_scopes"] == ["SANITATION", "ELECTRICAL"], (
            f"the granted scopes are now covered, got {rederived['covered_scopes']}"
        )
        assert rederived["required_scopes"] == ["SANITATION", "ELECTRICAL"], (
            f"the requirement itself is unchanged, got {rederived['required_scopes']}"
        )
        assert rederived["version"] > model["version"], (
            "the re-derivation is a mutation of the model, so its version moves past "
            f"{model['version']}, got {rederived['version']}"
        )

    def test_a_listing_still_under_review_contributes_no_coverage(self):
        """A DUAL model stays PARTIAL while its second agency application is only acknowledged.

        PRD §3.1: "Listings in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`,
        `CONDITIONS_REQUESTED` or `REJECTED` contribute nothing."

        Design: Corner/calculations/posture_counts_only_listed_children_and_ignores_one_still_under_review
        """
        set_clock()
        model = create_equipment_model(
            model_code="RNG-700",
            name="Dual Range 700",
            category="COMBI_OVEN",
            energy_type="DUAL",
            base_price_cents=2400000,
            supported_controls_packages=["STANDARD_DIAL"],
            rated_throughput_units_per_hour=60,
        )
        assert model["required_scopes"] == ["SANITATION", "GAS", "ELECTRICAL"], (
            "a dual-fuel model requires all three scopes in the fixed order, got "
            f"{model['required_scopes']}"
        )
        alpha = file_certification_listing(model["id"], "AGENCY_ALPHA", ["SANITATION"])
        grant_certification_listing(alpha["id"])
        beta = file_certification_listing(
            model["id"], "AGENCY_BETA", ["GAS", "ELECTRICAL"]
        )
        submit_certification_listing(beta["id"])

        record_agency_decision(beta["id"], "ACKNOWLEDGE_REVIEW")

        assert read_certification_listing(beta["id"])["status"] == "UNDER_REVIEW", (
            "the second application is acknowledged but undecided, got "
            f"{read_certification_listing(beta['id'])['status']}"
        )
        model = read_equipment_model(model["id"])
        assert model["covered_scopes"] == ["SANITATION"], (
            "only the granted AGENCY_ALPHA scope counts, got "
            f"{model['covered_scopes']}"
        )
        assert model["certification_posture"] == "PARTIAL", (
            "one covered scope out of three required leaves the model PARTIAL, got "
            f"{model['certification_posture']}"
        )


class TestApprovalNeedsFullScopeCoverage:
    @staticmethod
    def _dual_configuration_in_review():
        set_clock()
        model = create_equipment_model(**DUAL_MODEL)
        alpha = file_certification_listing(model["id"], "AGENCY_ALPHA", ["SANITATION"])
        grant_certification_listing(alpha["id"])
        account = create_chain_account()
        config = create_chain_configuration(
            account["id"],
            model["id"],
            account["version"],
            option_codes=["LEFT_HINGE"],
            controls_package="TOUCH_PRO",
            branding_kit="NONE",
        )
        setup_passed_validation(
            config["id"],
            menu_item_code="PATTY",
            target_throughput_units_per_hour=60.0,
            hold_temp_target_c=175.0,
        )
        config = submit_configuration(config["id"])
        return {"model": model, "config": config, "account": account}

    def test_partial_coverage_blocks_approval_until_a_second_agency_grants_the_rest(
        self, api, engineering_approver
    ):
        """The same approval call fails on a PARTIAL model and succeeds once posture reaches LISTED.

        PRD §3.5: "It additionally requires the referenced model's
        `certification_posture` to be exactly `LISTED` — a `PARTIAL` or `UNLISTED` model
        is rejected with `ERR_MODEL_NOT_LISTED`, and a `SUSPENDED` one with
        `ERR_MODEL_LISTING_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/dual_energy_configuration_approval_blocked_until_second_agency_listing_completes_scope_coverage
        """
        state = self._dual_configuration_in_review()
        assert read_equipment_model(state["model"]["id"])["certification_posture"] == (
            "PARTIAL"
        ), "one granted sanitation listing on a dual-fuel model is only partial coverage"

        refused = api.record_engineering_decision(
            state["config"]["id"], {"decision": "APPROVE"}, engineering_approver
        )
        validate_error(refused, ApiErrorId.ERR_MODEL_NOT_LISTED.value, 422)

        beta = file_certification_listing(
            state["model"]["id"], "AGENCY_BETA", ["GAS", "ELECTRICAL"]
        )
        grant_certification_listing(beta["id"])

        model = read_equipment_model(state["model"]["id"])
        assert model["certification_posture"] == "LISTED", (
            "the second grant closes the last scope gap, got "
            f"{model['certification_posture']}"
        )
        assert model["covered_scopes"] == ["SANITATION", "GAS", "ELECTRICAL"], (
            "the union of both grants is sorted into the fixed scope order, got "
            f"{model['covered_scopes']}"
        )

        approved = validate_success(
            api.record_engineering_decision(
                state["config"]["id"], {"decision": "APPROVE"}, engineering_approver
            )
        )
        assert approved["status"] == "ENG_APPROVED", (
            "the identical call now moves the configuration to ENG_APPROVED, got "
            f"{approved['status']}"
        )

    def test_the_blocked_approval_leaves_the_configuration_completely_untouched(
        self, api, engineering_approver
    ):
        """Nothing is pinned or stamped by the refusal, and the fix happens on the model alone.

        PRD §3.5: "Approval writes `pinned_model_version` with the model's current
        `version`, capturing exactly which model revision was reviewed, and records the
        acting `X-User-ID` in `approved_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/dual_energy_configuration_approval_blocked_until_second_agency_listing_completes_scope_coverage
        """
        state = self._dual_configuration_in_review()
        submitted_version = state["config"]["version"]

        refused = api.record_engineering_decision(
            state["config"]["id"], {"decision": "APPROVE"}, engineering_approver
        )
        validate_error(refused, ApiErrorId.ERR_MODEL_NOT_LISTED.value)

        held = read_chain_configuration(state["config"]["id"])
        assert held["status"] == "ENG_REVIEW", (
            f"the refused decision leaves the package in review, got {held['status']}"
        )
        assert held["pinned_model_version"] is None, (
            f"nothing was reviewed to completion, so nothing is pinned, got "
            f"{held['pinned_model_version']}"
        )
        assert held["approved_by_user_id"] is None, (
            f"no approver is recorded, got {held['approved_by_user_id']}"
        )
        assert held["version"] == submitted_version, (
            "the configuration itself is not mutated by the refusal, so its version "
            f"stays {submitted_version}, got {held['version']}"
        )

        beta = file_certification_listing(
            state["model"]["id"], "AGENCY_BETA", ["GAS", "ELECTRICAL"]
        )
        grant_certification_listing(beta["id"])
        assert read_chain_configuration(state["config"]["id"])["version"] == (
            submitted_version
        ), "granting a listing on the model does not touch the configuration row"

        approved = approve_configuration(state["config"]["id"])
        model = read_equipment_model(state["model"]["id"])
        assert approved["status"] == "ENG_APPROVED", (
            f"the unblocked approval succeeds, got {approved['status']}"
        )
        assert approved["pinned_model_version"] == model["version"], (
            "approval pins the model version it actually reviewed, got "
            f"{approved['pinned_model_version']} against a current model version of "
            f"{model['version']}"
        )
