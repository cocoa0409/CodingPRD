"""Which of several simultaneously-true failures the client is told about."""

from test_helpers import (
    BREEDER,
    OFFICER,
    ApiErrorId,
    create_production_quota_payload,
    create_propagator,
    create_propagator_agreement_payload,
    create_royalty_line_item_payload,
    create_royalty_report_payload,
    create_tag_order_payload,
    create_variety,
    licensed_quota,
    make_propagator_headers,
    read_version,
    validate_error,
    validate_success,
)


class TestFrozenQuotaOutranksTheUnitCeiling:
    """State-tier ERR_QUOTA_FROZEN beats the business-tier fiscal ceiling."""

    def _frozen_quota_with_an_oversized_request(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=1000,
            variety_overrides={
                "denomination": "Tin Roof Plum",
                "species": "Prunus domestica",
                "breeder_code": "TP",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Tinroof Propagators",
        )
        quota_version = read_version(api, api.get_production_quota, chain["quota_id"], OFFICER)
        chain["tag_order"] = validate_success(
            api.create_tag_order(
                create_tag_order_payload(chain["quota_id"], quota_version,
                                         requested_units=5000),
                chain["propagator_headers"],
            ),
            201,
        )
        validate_success(api.suspend_agreement(chain["agreement_id"], OFFICER))
        return chain

    def test_the_frozen_quota_is_reported_and_not_the_unit_ceiling(self, api):
        """5000 requested against 1000 available would also fail the fiscal
        ceiling, but the frozen-quota check sits in the state tier and fires
        first, so the client is told about the freeze.

        PRD 2.8: "Frozen-quota rejection — `ERR_QUOTA_FROZEN` (HTTP 409), when the quota an operation consumes is `FROZEN`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_quota_state_check_outranks_tag_unit_ceiling_check
        """
        chain = self._frozen_quota_with_an_oversized_request(api)

        validate_error(
            api.issue_tag_order(chain["tag_order"]["id"], OFFICER),
            ApiErrorId.ERR_QUOTA_FROZEN.value,
            409,
        )

    def test_nothing_is_committed_by_the_rejected_issue(self, api):
        """The order stays in REQUESTED and the quota's committed units stay at
        zero, so a request that was never authorized has consumed nothing.

        PRD 3.6: "`tags_committed_units` is the sum of `requested_units` over the quota's tag orders whose status is `ISSUED` or `RECONCILED`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_quota_state_check_outranks_tag_unit_ceiling_check
        """
        chain = self._frozen_quota_with_an_oversized_request(api)

        validate_error(
            api.issue_tag_order(chain["tag_order"]["id"], OFFICER),
            ApiErrorId.ERR_QUOTA_FROZEN.value,
            409,
        )

        order = validate_success(api.get_tag_order(chain["tag_order"]["id"], OFFICER))
        assert order["status"] == "REQUESTED"
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 0
        assert quota["units_available"] == 1000

    def test_the_unit_ceiling_surfaces_once_the_quota_is_thawed(self, api):
        """Reinstating the agreement thaws the quota, and the same issue attempt
        then reaches the fiscal ceiling it was always going to fail.

        PRD 3.6: "The fiscal ceiling is then checked: the order's `requested_units` must not exceed the quota's `units_available` as freshly re-derived, and an over-request is rejected with `ERR_QUOTA_UNITS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_quota_state_check_outranks_tag_unit_ceiling_check
        """
        chain = self._frozen_quota_with_an_oversized_request(api)
        validate_success(api.reinstate_agreement(chain["agreement_id"], OFFICER))

        validate_error(
            api.issue_tag_order(chain["tag_order"]["id"], OFFICER),
            ApiErrorId.ERR_QUOTA_UNITS_EXCEEDED.value,
            422,
        )


class TestAgreementActivityOutranksTheCrossCheck:
    """The agreement-active gate is the first check of the business tier."""

    def _report_on_a_suspended_agreement_and_a_foreign_quota(self, api):
        variety = create_variety(
            api, denomination="Slate Harvest", species="Malus domestica",
            breeder_code="SH", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        propagator = create_propagator(
            api, legal_name="Slatefield Nurseries", home_territory_code="US-WA"
        )
        propagator_headers = make_propagator_headers(propagator["id"])
        first = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B", territory_codes=["US-WA"]
                ),
                OFFICER,
            ),
            201,
        )
        validate_success(api.countersign_agreement(first["id"], OFFICER))
        second = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B", territory_codes=["US-OR"]
                ),
                OFFICER,
            ),
            201,
        )
        validate_success(api.countersign_agreement(second["id"], OFFICER))
        foreign_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    second["id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-OR",
                    territory_class="DOMESTIC", allocated_units=20000,
                ),
                OFFICER,
            ),
            201,
        )
        report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(first["id"]), propagator_headers
            ),
            201,
        )
        validate_success(api.suspend_agreement(first["id"], OFFICER))
        return {
            "propagator_headers": propagator_headers,
            "first_agreement_id": first["id"],
            "foreign_quota_id": foreign_quota["id"],
            "report": report,
        }

    def test_the_inactive_agreement_is_reported_and_not_the_mismatch(self, api):
        """The named quota belongs to the other agreement, which would fail the
        referential cross-check, but the agreement-activity gate is evaluated
        first within the business tier.

        PRD 2.8: "Within the business tier the ordering is likewise fixed: agreement-activity gating, then segregation of duties, then the sublicensing and release gates, then reinstatement eligibility, then referential cross-checks, then uniqueness constraints, then temporal constraints, then fiscal and capacity constraints."

        Design: Difficulty/priority_pair_validation_conflict/agreement_activity_safety_check_outranks_quota_agreement_referential_check
        """
        setup = self._report_on_a_suspended_agreement_and_a_foreign_quota(api)

        validate_error(
            api.create_royalty_line_item(
                setup["report"]["id"],
                create_royalty_line_item_payload(
                    setup["foreign_quota_id"], 500, setup["report"]["version"]
                ),
                setup["propagator_headers"],
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            409,
        )

    def test_the_rejected_line_leaves_the_report_untouched(self, api):
        """No line item comes into existence and the report's version does not
        move, because a line creation is what would have advanced it.

        PRD 3.7: "A new line is created with `billable_units` 0, `effective_rate_cents` 0.0000, `provisional_amount_cents` 0, `final_amount_cents` 0, `overrun_flagged` false and `version` 1 — all of its money is computed later, at submission and again at acceptance — and creating it increments the report's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/agreement_activity_safety_check_outranks_quota_agreement_referential_check
        """
        setup = self._report_on_a_suspended_agreement_and_a_foreign_quota(api)

        validate_error(
            api.create_royalty_line_item(
                setup["report"]["id"],
                create_royalty_line_item_payload(
                    setup["foreign_quota_id"], 500, setup["report"]["version"]
                ),
                setup["propagator_headers"],
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            409,
        )

        report = validate_success(api.get_royalty_report(setup["report"]["id"], BREEDER))
        assert report["version"] == setup["report"]["version"]

    def test_the_cross_check_surfaces_once_the_agreement_is_active_again(self, api):
        """With the gate satisfied the referential cross-check finally speaks:
        units produced under one licence may not be billed on another's report.

        PRD 3.7: "The quota must belong to the same agreement as the report: a quota whose `agreement_id` differs from the report's `agreement_id` is rejected with `ERR_QUOTA_AGREEMENT_MISMATCH` (HTTP 422), because units produced under one licence may not be billed on another's report."

        Design: Difficulty/priority_pair_validation_conflict/agreement_activity_safety_check_outranks_quota_agreement_referential_check
        """
        setup = self._report_on_a_suspended_agreement_and_a_foreign_quota(api)
        validate_success(api.reinstate_agreement(setup["first_agreement_id"], OFFICER))
        fresh_version = read_version(
            api, api.get_royalty_report, setup["report"]["id"], setup["propagator_headers"]
        )

        validate_error(
            api.create_royalty_line_item(
                setup["report"]["id"],
                create_royalty_line_item_payload(
                    setup["foreign_quota_id"], 500, fresh_version
                ),
                setup["propagator_headers"],
            ),
            ApiErrorId.ERR_QUOTA_AGREEMENT_MISMATCH.value,
            422,
        )
