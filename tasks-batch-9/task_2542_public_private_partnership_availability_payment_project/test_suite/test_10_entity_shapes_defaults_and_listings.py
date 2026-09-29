"""Resource shape: defaulted fields, computed fields, immutability and discovery lists."""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_common_fields
from test_helpers.constants import CLOCK_DRAFTING
from test_helpers.factories import (
    create_concession_payload,
    create_concessionaire_payload,
    create_reserve_transaction_payload,
    create_service_period_payload,
    determine_relief_claim_payload,
    verify_service_period_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ALPHA,
    BETA,
    DELTA,
    GAMMA,
    LENDER,
    PERIOD_ONE_END,
    PERIOD_ONE_START,
    add_relief_claim,
    add_reserve_transaction,
    issue_deduction_event,
    list_reserve_rows,
    propose_refinancing,
    raise_dispute,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    reject_milestone,
    request_milestone,
    set_clock,
    setup_concession_at_financial_close,
    setup_concession_in_operations,
    setup_drafted_concession,
    setup_notified_relief_claim,
    setup_pending_service_period,
    setup_verified_period,
    submit_performance_report,
)


class TestConcessionaireDefaults:
    def test_the_registration_body_carries_the_defaulted_status_and_counter(self):
        """A sponsor vehicle is born ACTIVE with no concessions and version 1.

        PRD: "The vehicle is created in `ACTIVE` with a `concessions_count` of 0."

        Design: Corner/entities/concessionaire_creation_applies_status_and_counter_defaults
        """
        set_clock(CLOCK_DRAFTING)

        response = api_client.create_concessionaire(create_concessionaire_payload(), ADMIN)

        row = validate_success(response, 201)
        assert_common_fields(row)
        assert row["legal_name"] == "Meridian Infrastructure Partners"
        assert row["sponsor_equity_commitment_cents"] == 100000000
        assert row["status"] == "ACTIVE"
        assert row["concessions_count"] == 0
        assert row["version"] == 1
        assert row["created_at"].startswith("2026-09-01T00:00:00")
        assert row["updated_at"] == row["created_at"]


class TestConcessionDerivedBlockOnRead:
    def test_the_single_row_read_publishes_every_derived_financial_field(self):
        """Six figures no request body ever supplied are readable on the concession.

        PRD: "There is no deferred settlement, no queue and no eventual convergence:
        a concession's `availability_deduction_ytd_cents`, `deduction_points_ytd`,
        `persistent_breach_flag`, `lifecycle_reserve_balance_cents`,
        `senior_debt_drawn_cents`, `equity_drawn_cents` and `cumulative_drawn_pct`, and
        a service period's `total_deduction_cents`, `relief_credit_cents` and
        `net_payment_cents`, are always the exact functions of their inputs that this
        document defines."

        Design: Corner/entities/concession_read_returns_every_derived_financial_field
        """
        ctx = setup_concession_in_operations()

        concession = validate_success(
            api_client.get_concession(ctx["concession_id"], LENDER)
        )

        assert concession["status"] == "OPERATIONS"
        assert concession["monthly_unitary_charge_cents"] == 8604167
        assert concession["equity_drawn_cents"] == 100000000
        assert concession["senior_debt_drawn_cents"] == 20000000
        assert concession["cumulative_drawn_pct"] == 0.3
        assert concession["lifecycle_reserve_balance_cents"] == 8000000
        assert concession["ld_accrued_cents"] == 5000000
        assert concession["handback_status"] == "NOT_SURVEYED"
        assert concession["availability_deduction_ytd_cents"] == 0
        assert concession["deduction_points_ytd"] == 0
        assert concession["persistent_breach_flag"] is False


class TestDrawdownMilestoneListing:
    def test_the_status_filter_is_applied_before_the_pagination_window(self):
        """Three milestones, one rejected; a windowed REQUESTED page counts only two.

        PRD: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts the rows matching the
        filter before pagination is applied and `has_more` is true exactly when rows
        remain beyond the current window."

        Design: Corner/entities/drawdown_milestone_list_filters_by_status_and_paginates
        """
        ctx = setup_concession_at_financial_close()
        first = request_milestone(ctx, "M1 Mobilisation", 10000000)
        reject_milestone(ctx, first["id"], "cost evidence incomplete")
        refresh_concession(ctx)
        request_milestone(ctx, "M2 Design Complete", 20000000)
        refresh_concession(ctx)
        third = request_milestone(ctx, "M3 Structures Complete", 30000000)

        body = api_client.list_drawdown_milestones(
            LENDER,
            params={
                "concession_id": ctx["concession_id"],
                "status": "REQUESTED",
                "limit": 1,
                "offset": 1,
            },
        ).json()

        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == third["id"]
        assert body["data"][0]["sequence_no"] == 3
        assert body["data"][0]["status"] == "REQUESTED"
        assert body["meta"]["total_count"] == 2
        assert body["meta"]["limit"] == 1
        assert body["meta"]["offset"] == 1
        assert body["meta"]["has_more"] is False
        assert first["id"] not in [row["id"] for row in body["data"]]


class TestDeductionEventDiscoveryList:
    def test_the_system_appended_understatement_event_is_reachable_only_by_listing(self):
        """Verification returns the period, so the event it raised must be listed for.

        PRD: "Deduction events accept `service_period_id`, `performance_report_id`,
        `deduction_type` and `status`, and that list is the only way to reach the
        self-report-understatement and handback-shortfall events the cascades raise."

        Design: Corner/entities/deduction_event_listing_is_the_only_route_to_a_system_appended_event
        """
        ctx = setup_pending_service_period()
        report = submit_performance_report(ctx, 100, 2, 4)
        period = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(110, 2, 4), BETA
            )
        )

        body = api_client.list_deduction_events(
            ctx["cnr_headers"], params={"service_period_id": ctx["service_period_id"]}
        ).json()

        assert body["meta"]["total_count"] == 1
        event = body["data"][0]
        assert event["deduction_type"] == "SELF_REPORT_UNDERSTATEMENT"
        assert event["sequence_no"] == 1
        assert event["points"] == 25
        assert event["raw_amount_cents"] == 31250
        assert event["status"] == "ISSUED"
        assert event["performance_report_id"] == report["id"]
        stored_report = validate_success(
            api_client.get_performance_report(report["id"], ALPHA)
        )
        assert stored_report["variance_pct"] == 0.0625
        assert stored_report["status"] == "VERIFIED"
        assert period["total_deduction_cents"] == 31250
        assert period["net_payment_cents"] == 8572917


class TestUnknownServicePeriodRead:
    def test_an_unknown_period_id_yields_the_period_specific_not_found_error(self):
        """The 404 names the service period, not the concession and not a generic id.

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/entities/get_unknown_service_period_returns_service_period_not_found
        """
        response = api_client.get_service_period(NON_EXISTENT_UUID, ALPHA)

        validate_error(response, "ERR_SERVICE_PERIOD_NOT_FOUND", 404)
        data = response.json()["data"]
        assert isinstance(data["message"], str) and data["message"]
        assert "id" not in data
        assert "period_index" not in data


class TestConcessionRequiredFields:
    def test_a_draft_without_its_annual_payment_writes_no_row_at_all(self):
        """masp_cents has no default, so its absence is a 400 rather than a null column.

        PRD: "Schema conformance covers every create and amend operation and yields
        `ERR_INVALID_REQUEST` (HTTP 400): a required field absent, an enumeration value
        outside its declared set, an amount field that is not a non-negative integer, a
        percentage field outside the range 0 to 1 inclusive, a basis-point field that is
        not a non-negative integer, a malformed ISO 8601 date, a reversal attempted
        through the plain ledger-append operation, or a compensation calculation on
        concessionaire default that omits any of its three market-value inputs."

        Design: Corner/entities/concession_creation_without_masp_cents_is_invalid_request
        """
        set_clock(CLOCK_DRAFTING)
        concessionaire = validate_success(
            api_client.create_concessionaire(create_concessionaire_payload(), ADMIN), 201
        )
        payload = create_concession_payload(concessionaire["id"])
        del payload["masp_cents"]

        response = api_client.create_concession(payload, ALPHA)

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        body = api_client.list_concessions(
            ALPHA, params={"concessionaire_id": concessionaire["id"]}
        ).json()
        assert body["meta"]["total_count"] == 0
        stored = validate_success(
            api_client.get_concessionaire(concessionaire["id"], ADMIN)
        )
        assert stored["concessions_count"] == 0


class TestReliefRejectionDefaults:
    def test_a_rejected_claim_keeps_both_granted_figures_at_zero(self):
        """The determination omits every optional input and grants nothing.

        PRD: "A `REJECT` lands the claim in `REJECTED` and forces
        `granted_relief_days` and `granted_cost_cents` to 0 whatever the request body
        said; a rejected claim never enters the relief-credit input set and never
        excuses a late-delivery day, so no period is recomputed and the concession's
        `ld_accrued_cents` is left exactly as it stands."

        Design: Corner/entities/relief_rejection_leaves_both_granted_figures_at_their_zero_defaults
        """
        ctx = setup_notified_relief_claim(claimed_relief_days=12, claimed_cost_cents=4000000)
        claim_id = ctx["relief_claim"]["id"]

        response = api_client.determine_relief_claim(
            claim_id, determine_relief_claim_payload("REJECT"), ALPHA
        )

        claim = validate_success(response)
        assert claim["status"] == "REJECTED"
        assert claim["granted_relief_days"] == 0
        assert claim["granted_cost_cents"] == 0
        assert claim["determination_note"] is None
        assert claim["determined_at"].startswith("2027-02-05T00:00:00")
        assert claim["notified_at"].startswith("2027-02-05T00:00:00")
        assert claim["claimed_relief_days"] == 12
        assert claim["claimed_cost_cents"] == 4000000
        assert refresh_concession(ctx)["ld_accrued_cents"] == 5000000


class TestServicePeriodComputedFields:
    def test_opening_a_period_freezes_the_charge_and_derives_its_cap(self):
        """Three computed fields land in the 201 body with no matching input.

        PRD: "The period's `gross_unitary_charge_cents` is a frozen copy of the
        concession's `monthly_unitary_charge_cents` as it stands at that moment, and its
        `deduction_cap_cents` is that frozen gross charge multiplied by the concession's
        `deduction_cap_pct`, rounded half up to a whole cent, also frozen."

        Design: Corner/entities/service_period_creation_freezes_the_charge_and_derives_the_cap
        """
        ctx = setup_concession_in_operations()

        response = api_client.create_service_period(
            ctx["concession_id"],
            create_service_period_payload(1, PERIOD_ONE_START, PERIOD_ONE_END),
            ALPHA,
        )

        period = validate_success(response, 201)
        assert_common_fields(period)
        assert period["days_in_period"] == 31
        assert period["gross_unitary_charge_cents"] == 8604167
        assert period["deduction_cap_cents"] == 1720833
        assert period["reporting_status"] == "PENDING"
        assert period["payment_status"] == "UNBILLED"
        assert period["total_deduction_cents"] == 0
        assert period["relief_credit_cents"] == 0
        assert period["deduction_points_total"] == 0
        assert period["availability_ratio"] is None
        assert period["verified_at"] is None
        # A fresh period has neither deductions nor relief credit, so its net payment
        # starts equal to the frozen gross charge.
        assert period["net_payment_cents"] == 8604167
        assert period["version"] == 1


class TestDeductionEventSystemFields:
    def test_the_sequence_number_issuer_and_stamp_are_all_server_assigned(self):
        """Two events on one period number 1 then 2, each under its own officer.

        PRD: "A new event is created in status `ISSUED`, stamped with `issued_at` from
        the logical clock and with `issued_by_user_id` set to the acting officer's
        `X-User-ID`, its `withdrawal_reason` null, and its `sequence_no` set to one more
        than the highest `sequence_no` any event of that period already holds."

        Design: Corner/entities/deduction_event_sequence_no_and_issuer_are_system_assigned
        """
        ctx = setup_verified_period()
        first = issue_deduction_event(ctx, 400, "UNAVAILABILITY", headers=GAMMA)

        second = issue_deduction_event(ctx, 600, "PERFORMANCE_FAILURE", headers=DELTA)

        assert first["sequence_no"] == 1
        assert second["sequence_no"] == 2
        assert first["issued_by_user_id"] == "officer-gamma"
        assert second["issued_by_user_id"] == "officer-delta"
        assert second["issued_at"].startswith("2027-04-02T00:00:00")
        assert second["status"] == "ISSUED"
        assert second["withdrawal_reason"] is None
        assert second["performance_report_id"] is None
        assert second["raw_amount_cents"] == 750000
        assert second["allowed_amount_cents"] == 750000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 1250000
        assert period["net_payment_cents"] == 7354167


class TestConcessionPercentageRange:
    def test_an_indexation_fraction_above_one_is_refused(self):
        """1.5 is well-formed JSON but outside the declared fraction range.

        PRD: "Percentages and ratios are decimal fractions between 0 and 1 inclusive,
        held in fields whose names end in `_pct`; a return on equity is expressed in
        basis points in a field ending in `_bps`, which is converted to a fraction by
        dividing by 10,000."

        Design: Corner/entities/concession_creation_with_indexation_pct_above_one_is_invalid_request
        """
        set_clock(CLOCK_DRAFTING)
        concessionaire = validate_success(
            api_client.create_concessionaire(create_concessionaire_payload(), ADMIN), 201
        )

        response = api_client.create_concession(
            create_concession_payload(concessionaire["id"], indexation_pct=1.5), ALPHA
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        body = api_client.list_concessions(
            ALPHA, params={"concessionaire_id": concessionaire["id"]}
        ).json()
        assert body["meta"]["total_count"] == 0


class TestReserveAppendEnumIsEndpointScoped:
    def test_a_reversal_cannot_be_appended_through_the_plain_ledger_append(self):
        """REVERSAL is a member of the enum but not an admissible append value.

        PRD: "The fourth kind, `REVERSAL`, may not be appended this way at all; an
        attempt to do so is refused with `ERR_INVALID_REQUEST` (HTTP 400), because
        reversals go through their own dedicated operation."

        Design: Corner/entities/reserve_transaction_with_txn_type_reversal_is_invalid_request
        """
        ctx = setup_drafted_concession()

        response = api_client.create_reserve_transaction(
            ctx["concession_id"],
            create_reserve_transaction_payload(
                "REVERSAL", 1000000, "trying to reverse without a target"
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        _, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 0
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 0


class TestReserveLedgerImmutability:
    def test_a_later_append_never_rewrites_an_earlier_rows_running_balance(self):
        """Row 1 keeps 5,000,000 forever even though the live balance is 7,000,000.

        PRD: "A reserve transaction carries only `id` and `created_at`: it has no
        `updated_at` and no `version`, because it is append-only."

        Design: Corner/entities/reserve_ledger_rows_are_immutable_and_carry_no_version_field
        """
        ctx = setup_drafted_concession()
        first = add_reserve_transaction(
            ctx, "CONTRIBUTION", 5000000, "initial sponsor funding"
        )

        second = add_reserve_transaction(ctx, "CONTRIBUTION", 2000000, "second tranche")

        stored_first = validate_success(
            api_client.get_reserve_transaction(first["id"], ALPHA)
        )
        assert "version" not in stored_first
        assert "updated_at" not in stored_first
        assert stored_first["sequence_no"] == 1
        assert stored_first["resulting_balance_cents"] == 5000000
        assert stored_first["signed_amount_cents"] == 5000000
        assert stored_first["reverses_txn_id"] is None
        assert second["sequence_no"] == 2
        assert second["resulting_balance_cents"] == 7000000
        assert second["created_by_role"] == "Concessionaire"
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 7000000
        _, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 2


class TestConcessionBodyForeignKey:
    def test_an_unknown_sponsor_in_the_body_is_a_referenced_entity_not_found(self):
        """The owning vehicle arrives in the body, so its absence is the body-FK error.

        PRD: "Identifiers supplied in a request *body* rather than in the path are a
        separate rung: the `concessionaire_id` named when drafting a concession, the
        optional `performance_report_id` named when issuing a deduction event, and the
        reversal target named when reversing a ledger entry all yield
        `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) when they resolve to no row."

        Design: Corner/entities/concession_creation_with_an_unknown_concessionaire_id_is_referenced_entity_not_found
        """
        set_clock(CLOCK_DRAFTING)

        response = api_client.create_concession(
            create_concession_payload(NON_EXISTENT_UUID), ADMIN
        )

        validate_error(response, "ERR_REFERENCED_ENTITY_NOT_FOUND", 404)
        body = api_client.list_concessions(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestFlatSurfaceReachability:
    def test_every_row_the_workflow_minted_is_readable_at_its_own_top_level_id(self):
        """Rows created under a parent path are afterwards first-class resources.

        PRD: "Creation, by contrast, is addressed under the owning parent so that the
        parent context is unambiguous — a service period is created under its concession,
        a performance report under its service period, a dispute under its deduction
        event — after which the child is a first-class top-level resource addressed by
        its own id alone."

        Design: Corner/entities/every_entity_is_readable_by_id_after_the_full_workflow
        """
        ctx = setup_verified_period()
        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY", headers=ALPHA)
        dispute = raise_dispute(
            ctx,
            event["id"],
            "The unavailability window overlaps a notified relief event.",
        )
        claim = add_relief_claim(ctx, "RELIEF_EVENT", "2027-03-20", "2027-03-23", 3, 500000)
        reserve_row = add_reserve_transaction(
            ctx, "CONTRIBUTION", 2000000, "Scheduled lifecycle contribution"
        )
        refinancing = propose_refinancing(ctx, "2027-04-02", 300000000, 240000000, 10000000)
        action = raise_enforcement_action(
            ctx, "TERMINATION", "FORCE_MAJEURE", "2027-04-02", ALPHA
        )

        concessionaire = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        milestone = validate_success(
            api_client.get_drawdown_milestone(ctx["milestone"]["id"], ALPHA)
        )
        report = validate_success(
            api_client.get_performance_report(ctx["performance_report"]["id"], ALPHA)
        )
        stored_event = validate_success(api_client.get_deduction_event(event["id"], ALPHA))
        stored_dispute = validate_success(
            api_client.get_deduction_dispute(dispute["id"], ALPHA)
        )
        stored_claim = validate_success(api_client.get_relief_claim(claim["id"], ALPHA))
        stored_action = validate_success(
            api_client.get_enforcement_action(action["id"], ALPHA)
        )
        stored_reserve_row = validate_success(
            api_client.get_reserve_transaction(reserve_row["id"], ALPHA)
        )
        stored_refinancing = validate_success(
            api_client.get_refinancing_event(refinancing["id"], ALPHA)
        )

        assert concessionaire["legal_name"] == "Meridian Infrastructure Partners"
        assert concessionaire["status"] == "ACTIVE"
        assert milestone["status"] == "DISBURSED"
        assert milestone["equity_portion_cents"] == 100000000
        assert milestone["debt_portion_cents"] == 20000000
        assert report["status"] == "VERIFIED"
        assert report["reported_points"] == 320
        assert report["service_period_id"] == ctx["service_period_id"]
        assert stored_event["status"] == "DISPUTED"
        assert stored_event["points"] == 400
        assert stored_event["allowed_amount_cents"] == 500000
        assert stored_dispute["status"] == "RAISED"
        assert stored_dispute["round_no"] == 1
        assert stored_dispute["deduction_event_id"] == event["id"]
        assert stored_claim["status"] == "NOTIFIED"
        assert stored_claim["claimed_relief_days"] == 3
        assert stored_claim["granted_relief_days"] == 0
        assert stored_action["status"] == "NOTIFIED"
        assert stored_action["trigger_reason"] == "FORCE_MAJEURE"
        assert stored_action["cure_deadline"] is None
        assert stored_reserve_row["resulting_balance_cents"] == 10000000
        assert stored_refinancing["status"] == "PROPOSED"
        assert stored_refinancing["gross_gain_cents"] == 50000000
        listing = api_client.list_concessionaires(ADMIN).json()
        assert listing["meta"]["total_count"] == 1
        assert listing["meta"]["has_more"] is False
        assert (
            validate_success(api_client.get_deduction_event(event["id"], ALPHA))
            == stored_event
        )
