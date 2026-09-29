"""No refresh step exists: what a mutation computed is already in its own answer."""

from test_helpers import (
    BREEDER,
    OFFICER,
    OFFICER_TWO,
    ApiErrorId,
    active_agreement,
    add_line_item,
    create_production_quota_payload,
    create_tag_order_payload,
    draft_report,
    licensed_quota,
    read_version,
    released_variety,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheAcceptanceResponseAlreadyCarriesTheAuditedTotals:
    """An on-time 100-unit report under a quota with no tag activations."""

    def _submitted_report(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Larchmont Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "LM",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Larchmont Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        chain["line_item"] = add_line_item(api, chain, report["id"], 100)
        chain["line_item_id"] = chain["line_item"]["id"]
        chain["report_id"] = report["id"]
        validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        return chain

    def test_the_accept_response_body_states_the_booked_amount_itself(self, api):
        """The repricing happens inside the accepting call, so its own answer already
        names the audited total, the fee and the officer who acted.

        PRD 3.7: "`booked_amount_cents` is then `final_total_cents` plus `late_fee_cents`."

        Design: Corner/consistency_model/acceptance_response_already_carries_the_recomputed_totals
        """
        chain = self._submitted_report(api)

        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )
        assert accepted["review_status"] == "ACCEPTED"
        assert accepted["final_total_cents"] == 3500
        assert accepted["late_fee_cents"] == 0
        assert accepted["booked_amount_cents"] == 3500
        assert accepted["accepted_by_user_id"] == "officer-2"

    def test_a_following_read_returns_the_same_values(self, api):
        """Nothing settles later, so re-reading the report field by field reproduces
        exactly what the mutation already reported.

        PRD 2.6: "Derived money and quantity fields are always recomputed by full re-aggregation over their source rows, never adjusted by delta."

        Design: Corner/consistency_model/acceptance_response_already_carries_the_recomputed_totals
        """
        chain = self._submitted_report(api)
        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )

        reread = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        for field in ("review_status", "settlement_status", "final_total_cents",
                      "late_fee_cents", "booked_amount_cents",
                      "accepted_by_user_id", "version"):
            assert reread[field] == accepted[field]

    def test_the_line_and_the_ledger_moved_inside_the_same_call(self, api):
        """The child line and the propagator's payable are re-derived by the same
        acceptance, so both are already current on the very next request.

        PRD 3.7: "Among those accepted reports, `royalty_payable_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `UNSETTLED` or `REVERSED`, and `royalty_settled_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `SETTLED`."

        Design: Corner/consistency_model/acceptance_response_already_carries_the_recomputed_totals
        """
        chain = self._submitted_report(api)
        validate_success(api.accept_royalty_report(chain["report_id"], OFFICER_TWO))

        line = validate_success(
            api.get_royalty_line_item(chain["line_item_id"], OFFICER)
        )
        assert line["billable_units"] == 100
        assert line["final_amount_cents"] == 3500
        assert line["overrun_flagged"] is False

        assert validate_success(api.get_propagator(chain["propagator_id"], OFFICER))[
            "royalty_payable_cents"
        ] == 3500


class TestTheRetirementCascadeIsVisibleImmediately:
    """A released variety with one live quota and one requested tag batch under it."""

    def _released_variety_with_a_live_quota(self, api):
        released = released_variety(
            api, denomination="Marlow Bramble", species="Rubus idaeus",
            breeder_code="ML", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Marlow Nursery", home_territory_code="US-WA",
        )
        chain["variety_id"] = released["variety"]["id"]
        quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"],
                    season_code="2026S1", basis="PER_PLANT",
                    territory_code="US-WA", territory_class="DOMESTIC",
                    allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        chain["quota_id"] = quota["id"]
        quota_version = read_version(api, api.get_production_quota, quota["id"],
                                     OFFICER)
        order = validate_success(
            api.create_tag_order(
                create_tag_order_payload(quota["id"], quota_version,
                                         requested_units=400),
                chain["propagator_headers"],
            ),
            201,
        )
        chain["tag_order_id"] = order["id"]
        return chain

    def test_the_retire_response_reports_the_terminal_lifecycle(self, api):
        """Retirement is the terminal lifecycle state and the retire response
        already carries it.

        PRD 3.1: "Retirement drives `RELEASED → RETIRED` and is the terminal state of the lifecycle dimension."

        Design: Corner/consistency_model/retirement_cascade_is_visible_in_the_same_response
        """
        chain = self._released_variety_with_a_live_quota(api)

        retired = validate_success(api.retire_variety(chain["variety_id"], BREEDER))
        assert retired["lifecycle_state"] == "RETIRED"

    def test_both_cascade_levels_are_already_written_on_the_next_read(self, api):
        """The quota closure and the compensating void run inside the retirement, so
        the immediately following reads show both children already moved.

        PRD 3.1: "Level one, caused by the retirement, closes every production quota of that variety whose status is `ACTIVE` or `FROZEN`, moving each to `CLOSED`; those quotas are processed by `created_at` ascending, ties broken by `season_code` ascending."

        Design: Corner/consistency_model/retirement_cascade_is_visible_in_the_same_response
        """
        chain = self._released_variety_with_a_live_quota(api)
        validate_success(api.retire_variety(chain["variety_id"], BREEDER))

        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "CLOSED"

        order = validate_success(api.get_tag_order(chain["tag_order_id"], OFFICER))
        assert order["status"] == "VOIDED"
        assert order["voided_units"] == 400

    def test_the_listing_and_the_next_action_both_honour_the_cascade_at_once(self, api):
        """There is no interval in which the old state is still authoritative: the
        active filter is already empty and the voided batch is already terminal.

        PRD 3.6: "`RECONCILED` and `VOIDED` are the terminal states of the tag order machine."

        Design: Corner/consistency_model/retirement_cascade_is_visible_in_the_same_response
        """
        chain = self._released_variety_with_a_live_quota(api)
        validate_success(api.retire_variety(chain["variety_id"], BREEDER))

        _rows, meta = validate_paginated(
            api.list_production_quotas(OFFICER, {"status": "ACTIVE"})
        )
        assert meta["total_count"] == 0

        validate_error(
            api.issue_tag_order(chain["tag_order_id"], OFFICER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )
