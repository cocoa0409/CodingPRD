"""Error-surface corners: not-found identity, per-market cell uniqueness, ledger reversal.

Three families of rejection are pinned here. First, the validation ladder of PRD
2.6: an identifier that fails to resolve is reported with the not-found error of
its own entity, and that failure outranks every payload and state rule beneath
it. Second, the quota cell uniqueness key of PRD 3.1 and the cell/market pairing
rule of PRD 3.2, which are separate rules with separate errors. Third, the
reverse-accrual precondition of PRD 3.4, which reads both the period label and
the entry's ``reversed`` flag.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import MISSING_UUID, NOT_FOUND_ERROR_IDS
from test_helpers.assertions import expected_accrued_cents
from test_helpers.factories import quota_cell_payload
from test_helpers.fixtures import PanelHarness


class TestMeasurementPathIdsReportTheirOwningEntity:
    """PRD 2.6 steps 4 and 5 on the six measurement-side entities."""

    def test_measurement_reads_report_their_own_not_found_error(self, panel: PanelHarness):
        """Each measurement entity's unresolvable id reports that entity's own 404.

        PRD 2.6: "Failures at step 4 and step 5 are reported with the not-found
        error of the entity whose identifier failed: `ERR_MARKET_NOT_FOUND`,
        `ERR_QUOTA_CELL_NOT_FOUND`, `ERR_UNIVERSE_ESTIMATE_NOT_FOUND`,
        `ERR_EDIT_RULE_SET_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
        `ERR_METER_NOT_FOUND`, `ERR_TUNING_INTERVAL_NOT_FOUND`,
        `ERR_PROCESSING_RUN_NOT_FOUND`, `ERR_HOUSEHOLD_WEIGHT_NOT_FOUND`".

        Design: Corner/errors/measurement_path_ids_that_do_not_resolve_return_the_owning_entity_error
        """
        client = panel.client
        probes = [
            ("QuotaCell", client.get_quota_cell(panel.ops, MISSING_UUID)),
            ("Household", client.get_household(panel.ops, MISSING_UUID)),
            ("Meter", client.get_meter(panel.tech, MISSING_UUID)),
            ("TuningInterval", client.get_tuning_interval(panel.statistician, MISSING_UUID)),
            ("ProcessingRun", client.get_processing_run(panel.statistician, MISSING_UUID)),
            (
                "UniverseEstimate",
                client.get_universe_estimate(panel.statistician, MISSING_UUID),
            ),
            ("EditRuleSet", client.get_edit_rule_set(panel.statistician, MISSING_UUID)),
        ]
        seen = []
        for entity, response in probes:
            expected = NOT_FOUND_ERROR_IDS[entity]
            error = validate_error(response, expected)
            # "The `meta` object for error responses contains only `api_request_id`
            # and `api_request_timestamp`" (PRD 2.2) and data holds exactly the pair.
            assert set(error) == {"error_id", "message"}, error
            assert response.json()["response_type"] == "error"
            seen.append(error["error_id"])
        assert len(set(seen)) == len(seen), f"not-found ids are not distinct: {seen}"

    def test_an_unresolvable_path_parent_outranks_payload_and_state_rules(
        self, panel: PanelHarness
    ):
        """A perfectly valid body against a missing parent is still a 404.

        PRD 2.6: "Every request walks a fixed ladder of generic checks before any
        endpoint-specific business rule is consulted, and the first failure on the
        ladder is the error the caller sees".

        Design: Corner/errors/measurement_path_ids_that_do_not_resolve_return_the_owning_entity_error
        """
        client = panel.client
        validate_error(
            client.create_quota_cell(
                panel.ops,
                MISSING_UUID,
                **quota_cell_payload(target_households=4, base_incentive_cents=1000),
            ),
            "ERR_MARKET_NOT_FOUND",
        )
        # The enumeration body is valid, so a 409 state error would prove the
        # ladder ran out of order.
        validate_error(
            client.create_enumeration(
                panel.tech, MISSING_UUID, roster_persons_count=2, tv_sets_count=1
            ),
            "ERR_HOUSEHOLD_NOT_FOUND",
        )
        validate_error(
            client.report_meter_fault(panel.tech, MISSING_UUID, fault_code="NO_SIGNAL"),
            "ERR_METER_NOT_FOUND",
        )

    def test_an_empty_collection_is_not_a_not_found(self, panel: PanelHarness):
        """A filter that matches nothing is a 200 with an empty page, never a 404.

        PRD 2.3: "Both are reflected back in the envelope's `meta` object,
        alongside `total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)."

        Design: Corner/errors/measurement_path_ids_that_do_not_resolve_return_the_owning_entity_error
        """
        rows, meta = validate_paginated(panel.client.list_quota_cells(panel.ops))
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


class TestCommercialAndGovernanceIdsReportTheirOwnError:
    """PRD 2.6 steps 4 and 5 on the commercial and governance entities."""

    def test_commercial_path_ids_report_their_own_not_found_error(self, panel: PanelHarness):
        """Client, deliverable and notification ids each carry their own 404.

        PRD 2.6: "The path identifiers used across the API are `market_id`,
        `quota_cell_id`, `universe_estimate_id`, `edit_rule_set_id`,
        `household_id`, `meter_id`, `tuning_interval_id`, `processing_run_id`,
        `household_weight_id`, `client_id`, `client_deliverable_id`,
        `client_notification_id`, `methodology_change_id` and
        `accreditation_audit_id`."

        Design: Corner/errors/commercial_and_governance_ids_that_do_not_resolve_return_their_own_error
        """
        client = panel.client
        validate_error(
            client.get_client(panel.rep, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["Client"],
        )
        # The action endpoint resolves its path id before the SUSPENDED state rule.
        validate_error(
            client.suspend_client(panel.rep, MISSING_UUID, suspended_reason="Non-payment"),
            NOT_FOUND_ERROR_IDS["Client"],
        )
        validate_error(
            client.get_client_deliverable(panel.rep, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["ClientDeliverable"],
        )
        validate_error(
            client.start_deliverable(panel.rep, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["ClientDeliverable"],
        )
        validate_error(
            client.get_client_notification(panel.rep, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["ClientNotification"],
        )
        validate_error(
            client.get_household_weight(panel.statistician, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["HouseholdWeight"],
        )

    def test_governance_path_ids_outrank_the_change_state_rules(self, panel: PanelHarness):
        """A missing change reports the change's 404, not a state conflict.

        PRD 2.6: "**Path existence** — every identifier embedded in the URL is
        resolved left to right, so the outer identifier is resolved before the
        inner one: `market_id` before `quota_cell_id`, `household_id` before
        `meter_id`, `methodology_change_id` before `client_notification_id`."

        Design: Corner/errors/commercial_and_governance_ids_that_do_not_resolve_return_their_own_error
        """
        client = panel.client
        validate_error(
            client.get_methodology_change(panel.director, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["MethodologyChange"],
        )
        # Not ERR_CHANGE_NOT_ASSESSED: priority 4 precedes the state rule.
        validate_error(
            client.notify_methodology_change(panel.director, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["MethodologyChange"],
        )
        validate_error(
            client.activate_methodology_change(panel.activator, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["MethodologyChange"],
        )
        validate_error(
            client.get_accreditation_audit(panel.auditor, MISSING_UUID),
            NOT_FOUND_ERROR_IDS["AccreditationAudit"],
        )
        validate_error(
            client.finalize_accreditation_audit(
                panel.finalizer, MISSING_UUID, outcome="ACCREDITED", limitation_disclosures=[]
            ),
            NOT_FOUND_ERROR_IDS["AccreditationAudit"],
        )

    def test_body_references_report_the_entity_of_the_reference_that_failed(
        self, panel: PanelHarness
    ):
        """An unresolvable body reference reports its own entity's 404.

        PRD 2.6: "**Body reference existence** — every reference identifier
        carried in a request body must resolve to an existing row: `market_id`,
        `quota_cell_id`, `universe_estimate_id`, `edit_rule_set_id`,
        `processing_run_id`, `client_id`, `baseline_processing_run_id`,
        `target_edit_rule_set_id`, `proposed_edit_rule_set_id`,
        `scope_edit_rule_set_id`, `meter_id`, `household_id` and
        `supersedes_change_id`."

        Design: Corner/errors/commercial_and_governance_ids_that_do_not_resolve_return_their_own_error
        """
        market = panel.create_market()
        subscriber = panel.create_client([market["id"]])
        # A resolvable path client, an unresolvable body run.
        validate_error(
            panel.client.create_scheduled_deliverable(
                panel.rep,
                subscriber["id"],
                processing_run_id=MISSING_UUID,
                requested_cell_count=0,
            ),
            NOT_FOUND_ERROR_IDS["ProcessingRun"],
        )
        # "a `target_edit_rule_set_id`, `proposed_edit_rule_set_id` or
        # `scope_edit_rule_set_id` that does not resolve reports
        # `ERR_EDIT_RULE_SET_NOT_FOUND`" (PRD 2.6).
        validate_error(
            panel.client.create_accreditation_audit(
                panel.auditor,
                market_id=market["id"],
                scope_edit_rule_set_id=MISSING_UUID,
                auditor_note="Scope names a rule set that was never drafted.",
            ),
            NOT_FOUND_ERROR_IDS["EditRuleSet"],
        )
        published = panel.published_rule_set()
        validate_error(
            panel.client.create_methodology_change(
                panel.director,
                title="A change whose proposed set does not exist",
                target_edit_rule_set_id=published["id"],
                proposed_edit_rule_set_id=MISSING_UUID,
                affected_market_ids=[market["id"]],
            ),
            NOT_FOUND_ERROR_IDS["EditRuleSet"],
        )


class TestQuotaCellUniquenessAndPairing:
    """PRD 3.1's uniqueness key and PRD 3.2's pairing rule are separate rules."""

    def test_a_repeated_triple_in_the_same_market_is_refused(self, panel: PanelHarness):
        """Re-posting the same three-part key into one market is a 409 duplicate.

        PRD 3.1: "the uniqueness check, which rejects with
        `ERR_QUOTA_CELL_DUPLICATE` if the market already holds a cell with the
        same combination of `age_band`, `income_band` and `geo_zone`."

        Design: Corner/errors/quota_cell_triple_uniqueness_and_cross_market_pairing_are_separate_rules
        """
        market = panel.create_market()
        panel.create_quota_cell(
            market["id"], target_households=4, base_incentive_cents=2000
        )
        # Different target and base, same three-part key.
        validate_error(
            panel.client.create_quota_cell(
                panel.ops,
                market["id"],
                **quota_cell_payload(target_households=8, base_incentive_cents=3000),
            ),
            "ERR_QUOTA_CELL_DUPLICATE",
        )
        after = panel.read_market(market["id"])
        assert after["quota_cell_count"] == 1
        # The refused cell reserved nothing: 2000 * 0.25 * 4 for the one cell only.
        assert after["incentive_budget_reserved_cents"] == 2000

    def test_one_differing_component_is_a_distinct_key(self, panel: PanelHarness):
        """Changing only the geo zone makes a second, acceptable cell.

        PRD 3.1: "The cell's key inside its market is the triple of `age_band`,
        `income_band` and `geo_zone`".

        Design: Corner/errors/quota_cell_triple_uniqueness_and_cross_market_pairing_are_separate_rules
        """
        market = panel.create_market()
        panel.create_quota_cell(
            market["id"], target_households=4, base_incentive_cents=2000
        )
        second = validate_success(
            panel.client.create_quota_cell(
                panel.ops,
                market["id"],
                **quota_cell_payload(
                    geo_zone="SUBURBAN", target_households=4, base_incentive_cents=2000
                ),
            ),
            201,
        )
        assert second["geo_zone"] == "SUBURBAN"
        assert panel.read_market(market["id"])["quota_cell_count"] == 2

    def test_the_key_is_scoped_to_one_market(self, panel: PanelHarness):
        """A second market may hold the identical triple.

        PRD 3.1: "the market already holds a cell with the same combination of
        `age_band`, `income_band` and `geo_zone`."

        Design: Corner/errors/quota_cell_triple_uniqueness_and_cross_market_pairing_are_separate_rules
        """
        first = panel.create_market()
        panel.create_quota_cell(first["id"], target_households=4, base_incentive_cents=2000)
        second = panel.create_market()
        twin = validate_success(
            panel.client.create_quota_cell(
                panel.ops,
                second["id"],
                **quota_cell_payload(target_households=4, base_incentive_cents=2000),
            ),
            201,
        )
        assert twin["age_band"] == "P18_34"
        assert twin["income_band"] == "MID"
        assert twin["geo_zone"] == "URBAN"
        assert twin["market_id"] == second["id"]
        assert panel.read_market(first["id"])["quota_cell_count"] == 1
        assert panel.read_market(second["id"])["quota_cell_count"] == 1

    def test_cell_existence_and_cell_market_pairing_are_separate_rules(
        self, panel: PanelHarness
    ):
        """A foreign cell is a 422 mismatch; an absent cell is a 404.

        PRD 3.2: "The referenced quota cell's own market must be the market named
        in the same payload, otherwise `ERR_QUOTA_CELL_MARKET_MISMATCH`."

        Design: Corner/errors/quota_cell_triple_uniqueness_and_cross_market_pairing_are_separate_rules
        """
        home = panel.create_market()
        home_cell = panel.create_quota_cell(
            home["id"], target_households=4, base_incentive_cents=2000
        )
        away = panel.create_market()
        away_cell = panel.create_quota_cell(
            away["id"], target_households=4, base_incentive_cents=2000
        )
        validate_error(
            panel.client.create_household(
                panel.ops,
                market_id=home["id"],
                quota_cell_id=away_cell["id"],
                recruitment_source="ADDRESS_SAMPLE",
                persons_count=3,
            ),
            "ERR_QUOTA_CELL_MARKET_MISMATCH",
        )
        # Body reference existence (ladder step 5) precedes the pairing rule.
        validate_error(
            panel.client.create_household(
                panel.ops,
                market_id=home["id"],
                quota_cell_id=MISSING_UUID,
                recruitment_source="ADDRESS_SAMPLE",
                persons_count=3,
            ),
            NOT_FOUND_ERROR_IDS["QuotaCell"],
        )
        recruited = validate_success(
            panel.client.create_household(
                panel.ops,
                market_id=home["id"],
                quota_cell_id=home_cell["id"],
                recruitment_source="ADDRESS_SAMPLE",
                persons_count=3,
            ),
            201,
        )
        assert recruited["status"] == "RECRUITED"
        # "Recruitment alone does not put a household in tab: the cell's
        # `intab_count` does not move" (PRD 3.2).
        assert panel.read_quota_cell(home_cell["id"])["intab_count"] == 0


def _one_active_home(panel: PanelHarness):
    """One market, one under-target cell and one ACTIVE household inside it."""
    market, cells = panel.market_with_cells(
        [{"target_households": 4, "base_incentive_cents": 2000}]
    )
    home = panel.active_household(market["id"], cells[0]["id"], persons_count=2)
    return market, cells[0], home["household"]


class TestReverseAccrualPreconditions:
    """PRD 3.4's reversal precondition reads both the label and the flag."""

    def test_reversing_before_any_accrual_is_refused(self, panel: PanelHarness):
        """An empty ledger has no entry to reverse.

        PRD 3.4: "The household's `accrual_periods` must hold an entry with that
        label whose `reversed` flag is false, otherwise
        `ERR_INCENTIVE_PERIOD_NOT_ACCRUED`."

        Design: Corner/errors/reverse_accrual_requires_a_period_entry_that_is_not_already_reversed
        """
        market, _cell, household = _one_active_home(panel)
        assert panel.read_household(household["id"])["accrual_periods"] == []
        validate_error(
            panel.client.reverse_accrual(
                panel.ops,
                household["id"],
                period_label="2026-08",
                memo="Nothing has been accrued for this home yet.",
            ),
            "ERR_INCENTIVE_PERIOD_NOT_ACCRUED",
        )
        assert panel.read_market(market["id"])["incentive_budget_committed_cents"] == 0

    def test_reversing_a_label_that_was_never_accrued_is_refused(self, panel: PanelHarness):
        """The precondition is keyed on the label, not on the ledger being non-empty.

        PRD 3.4: "The household's `accrual_periods` must hold an entry with that
        label whose `reversed` flag is false, otherwise
        `ERR_INCENTIVE_PERIOD_NOT_ACCRUED`."

        Design: Corner/errors/reverse_accrual_requires_a_period_entry_that_is_not_already_reversed
        """
        market, cell, household = _one_active_home(panel)
        accrued = panel.accrue(household["id"], period_label="2026-08")
        # 2000 * 1.25 boosted cell base, tenure 0 months so multiplier 1.000, no
        # compliance bonus (rolling rate 0.0000), no out-of-home meter, no fault.
        graded = panel.read_quota_cell(cell["id"])
        assert graded["effective_incentive_multiplier"] == 1.25
        expected = expected_accrued_cents(
            base_incentive_cents=2000,
            effective_incentive_multiplier=graded["effective_incentive_multiplier"],
            tenure_months=0,
            compliance_rate_rolling_30=accrued["compliance_rate_rolling_30"],
            has_installed_portable_ooh=False,
            has_faulted_meter=False,
        )
        assert expected == 2500
        assert accrued["incentive_accrued_cents"] == expected
        validate_error(
            panel.client.reverse_accrual(
                panel.ops,
                household["id"],
                period_label="2026-09",
                memo="September was never accrued against this home.",
            ),
            "ERR_INCENTIVE_PERIOD_NOT_ACCRUED",
        )
        # The refused reversal touched neither ledger.
        assert panel.read_household(household["id"])["incentive_accrued_cents"] == expected
        assert (
            panel.read_market(market["id"])["incentive_budget_committed_cents"] == expected
        )

    def test_a_reversed_entry_is_flagged_not_deleted_and_reverses_only_once(
        self, panel: PanelHarness
    ):
        """The entry survives with `reversed` true, so a second reversal is refused.

        PRD 3.4: "The matching entry's `reversed` flag becomes true and it keeps
        its `accrued_cents` for the audit trail — nothing is ever deleted from the
        ledger."

        Design: Corner/errors/reverse_accrual_requires_a_period_entry_that_is_not_already_reversed
        """
        market, cell, household = _one_active_home(panel)
        panel.accrue(household["id"], period_label="2026-08")
        reversed_home = panel.reverse(
            household["id"],
            period_label="2026-08",
            memo="The compliance figure used for August was wrong.",
        )
        assert reversed_home["incentive_accrued_cents"] == 0
        assert len(reversed_home["accrual_periods"]) == 1
        entry = reversed_home["accrual_periods"][0]
        assert entry["period_label"] == "2026-08"
        assert entry["accrued_cents"] == 2500
        assert entry["reversed"] is True
        validate_error(
            panel.client.reverse_accrual(
                panel.ops,
                household["id"],
                period_label="2026-08",
                memo="A second reversal of the same period.",
            ),
            "ERR_INCENTIVE_PERIOD_NOT_ACCRUED",
        )
        # "both figures return to their pre-accrual values with no drift" while the
        # cell's boost reservation of 2000 * 0.25 * 4 stands untouched (PRD 3.4).
        after = panel.read_market(market["id"])
        assert after["incentive_budget_committed_cents"] == 0
        assert after["incentive_budget_reserved_cents"] == 2000
        assert panel.read_quota_cell(cell["id"])["incentive_boost_active"] is True
