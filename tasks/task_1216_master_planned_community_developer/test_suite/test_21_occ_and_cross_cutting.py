"""Corner coverage: optimistic concurrency on both amendment endpoints, the
fixed clock epoch, derived-field reconciliation, and immediate consistency."""
from test_helpers import (
    api_client,
    create_active_community,
    create_adopted_budget,
    create_community_payload,
    create_district_with_advances,
    create_executed_agreement,
    create_open_phase,
    create_builder,
    create_phase,
    get_success_data,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.factories import (
    create_budget_payload,
    create_line_item_payload,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestOccAgreementAmendmentStaleAndSupersede:
    def _setup(self):
        community = create_active_community("OCC Oaks", 20)
        phase = create_open_phase(community["id"], "P1", 1, 10)
        builder = create_builder(community["id"], "OCC Builders", "A")
        agreement, tranches = create_executed_agreement(
            community["id"], builder["id"], phase["id"], 2,
            [("2026-06-30T00:00:00Z", 2)], earnest_money_cents=1000000,
        )
        read = get_success_data(api_client.get_agreement(agreement["id"], CTRL))
        return agreement, tranches[0], read["version"]

    def test_stale_expected_version_rejected(self):
        """PRD §2.8: "Creating a superseding takedown amendment against a lot purchase agreement (`POST /mpc/agreements/{aid}/amendments`) requires the request to carry `expected_agreement_version`, the client must supply its last-observed `version` of that agreement, and if the value does not match the agreement's current `version` the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_agreement_amendment_stale_and_supersede
        """
        agreement, tranche, version = self._setup()
        resp = api_client.amend_agreement(
            agreement["id"],
            {
                "expected_agreement_version": version - 1,
                "replacement_tranches": [
                    {"tranche_no": 2, "due_date": "2026-09-30T00:00:00Z", "lot_count_due": 2}
                ],
            },
            CTRL,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Nothing superseded: the old tranche is untouched.
        tranche_read = get_success_data(api_client.get_tranche(tranche["id"], CTRL))
        assert tranche_read["status"] == "SCHEDULED"

    def test_current_version_supersedes_schedule(self):
        """PRD §3.3: "The amendment atomically cancels the agreement's non-terminal tranches in `SCHEDULED` or `OPEN`, creates the replacements as new `SCHEDULED` tranches, and increments the agreement's `version`."
        PRD §2.8: "Creating a superseding takedown amendment against a lot purchase agreement (`POST /mpc/agreements/{aid}/amendments`) requires the request to carry `expected_agreement_version`, the client must supply its last-observed `version` of that agreement, and if the value does not match the agreement's current `version` the request is rejected with `ERR_STALE_VERSION` (HTTP 412).".

        Design: Corner/cross_cutting_complexity_layers/occ_agreement_amendment_stale_and_supersede
        """
        agreement, tranche, version = self._setup()
        amended = get_success_data(
            api_client.amend_agreement(
                agreement["id"],
                {
                    "expected_agreement_version": version,
                    "replacement_tranches": [
                        {"tranche_no": 2, "due_date": "2026-09-30T00:00:00Z", "lot_count_due": 2}
                    ],
                },
                CTRL,
            )
        )
        assert amended["version"] == version + 1, (
            f"amendment increments the agreement version, got {amended['version']} vs {version}"
        )
        old = get_success_data(api_client.get_tranche(tranche["id"], CTRL))
        assert old["status"] == "CANCELLED"

        rows, _meta = validate_paginated(
            api_client.list_tranches(CTRL, params={"agreement_id": agreement["id"]})
        )
        statuses = sorted(t["status"] for t in rows)
        assert "CANCELLED" in statuses and "SCHEDULED" in statuses, (
            f"expected the old tranche CANCELLED and the replacement SCHEDULED, got {statuses}"
        )


class TestOccBudgetAmendmentStaleAndRateCascade:
    def _setup(self):
        community = create_active_community("Amendment Acres", 10)
        budget = create_adopted_budget(community["id"], 2027, [("MANAGEMENT", 100000)])
        rate = get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2027},
                CTRL,
            )
        )
        read = get_success_data(api_client.get_budget(budget["id"], CTRL))
        return budget, rate, read["version"]

    def test_stale_budget_version_rejected(self):
        """PRD §2.8: "Creating a successor draft budget that supersedes an adopted budget (`POST /mpc/budgets/{bid}/amendments`) likewise requires `expected_budget_version` matching the budget's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch."

        Design: Corner/cross_cutting_complexity_layers/occ_budget_amendment_stale_and_rate_cascade
        """
        budget, _, version = self._setup()
        resp = api_client.amend_budget(
            budget["id"], {"expected_budget_version": version - 1}, CTRL
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_version_supersedes_and_cascades_to_rate(self):
        """PRD §3.5: "Separately, an `ADOPTED` budget can be amended: the OCC-guarded amendment (§2.8, `expected_budget_version` required) atomically marks the current budget `SUPERSEDED`, creates a successor `DRAFT` budget whose `amendment_of_id` points at its predecessor and whose line items are copied over, increments the superseded budget's `version`, and cascades to any assessment rates derived from the superseded budget in `CALCULATED` or `ARMED` status, moving them to `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/occ_budget_amendment_stale_and_rate_cascade
        """
        budget, rate, version = self._setup()
        successor = get_success_data(
            api_client.amend_budget(budget["id"], {"expected_budget_version": version}, CTRL)
        )
        assert successor["status"] == "DRAFT"
        assert successor["amendment_of_id"] == budget["id"]
        assert successor["total_expense_cents"] == 100000, (
            f"line items are copied into the successor, got {successor['total_expense_cents']}"
        )

        old = get_success_data(api_client.get_budget(budget["id"], CTRL))
        assert old["status"] == "SUPERSEDED"

        rate_read = get_success_data(api_client.get_assessment_rate(rate["id"], CTRL))
        assert rate_read["status"] == "SUPERSEDED"


class TestClockDefaultEpochFixed:
    def test_created_at_uses_fixed_logical_epoch(self):
        """PRD §2.5: "Before any clock-setting call, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."
        PRD §2.4: "an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created."

        Design: Corner/cross_cutting_complexity_layers/clock_default_epoch_fixed
        """
        community = get_success_data(
            api_client.create_community(
                create_community_payload(community_name="Epoch Edge", total_planned_units=5), EXEC
            )
        )
        assert community["created_at"] == "2026-05-01T00:00:00.000Z", (
            f"server-minted created_at must be the fixed logical epoch, got "
            f"{community['created_at']}"
        )


class TestDerivedFieldReconciliationBudgetAndDistrict:
    def test_budget_totals_and_district_interest_reconcile_per_mutation(self):
        """PRD §3.5: "The budget's `total_expense_cents` — the sum of all line amounts — and its `reserve_cents` — the sum over reserve lines only — are recomputed as lines are added."
        PRD §3.6: "The provisional figure, recomputed whenever the district is read and before any certification, is simple interest to the logical clock: for each advance, regardless of status, take its `amount_cents` times the annual rate over one hundred times the days outstanding over 365 — days outstanding being the calendar days from `advance_date` to now, or zero when the advance date is today or in the future — rounded half-up to whole cents per advance, then summed into `provisional_interest_cents`.".
        PRD §3.6: "Each advance immediately raises the district's `advance_principal_cents` and `outstanding_principal_cents` by its amount."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_budget_and_district
        """
        community = create_active_community("Reconcile Ridge", 10)
        budget = get_success_data(
            api_client.create_budget(
                create_budget_payload(community_id=community["id"], fiscal_year=2027), CTRL
            )
        )
        district, _ = create_district_with_advances(community["id"], [], "PID 9")
        prov0 = get_success_data(api_client.get_district(district["id"], CTRL))
        assert prov0["provisional_interest_cents"] == 0

        get_success_data(
            api_client.create_line_item(
                create_line_item_payload(budget_id=budget["id"], category="MANAGEMENT",
                                         amount_cents=100000),
                CTRL,
            )
        )
        read1 = get_success_data(api_client.get_budget(budget["id"], CTRL))
        assert read1["total_expense_cents"] == 100000
        assert read1["reserve_cents"] == 0

        get_success_data(
            api_client.create_line_item(
                create_line_item_payload(budget_id=budget["id"], category="RESERVE_CONTRIBUTION",
                                         amount_cents=50000, is_reserve=True),
                CTRL,
            )
        )
        read2 = get_success_data(api_client.get_budget(budget["id"], CTRL))
        assert read2["total_expense_cents"] == 150000
        assert read2["reserve_cents"] == 50000

        from test_helpers.factories import create_advance_payload
        get_success_data(
            api_client.create_advance(
                create_advance_payload(
                    district_id=district["id"], amount_cents=6000000,
                    advance_date="2026-04-01T00:00:00Z",
                ),
                CTRL,
            )
        )
        read_d = get_success_data(api_client.get_district(district["id"], CTRL))
        # 6,000,000c at 5% simple for 30 days: round_half_up(6000000*0.05*30/365) = 24658.
        assert read_d["provisional_interest_cents"] == 24658
        assert read_d["outstanding_principal_cents"] == 6000000


class TestImmediateReadAfterWrite:
    def test_phase_read_back_immediately(self):
        """PRD §3.2: "A `DeclarantExecutive` creates a `DevelopmentPhase` with a `phase_name`, a `sequence_no` (at least 1, unique within the community) that fixes its position in the rollout, and a `planned_lot_count` of at least 1; the phase starts `PLANNED` with `closed_lot_count` zero."
        PRD §2.4: "a system-managed integer that increments with every modification to the resource."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        community = create_active_community("Immediate Inlet", 10)
        phase = get_success_data(
            api_client.create_phase(
                {"community_id": community["id"], "phase_name": "P1", "sequence_no": 1,
                 "planned_lot_count": 5},
                EXEC,
            )
        )
        read = get_success_data(api_client.get_phase(phase["id"], EXEC))
        assert read["phase_name"] == "P1"
        assert read["sequence_no"] == 1
        assert read["status"] == "PLANNED"
        assert read["version"] == 1
