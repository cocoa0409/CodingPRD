"""Declared edges, refused edges and the side effects each edge owns.

One valid transition per machine is walked with all of its stamped fields and
ledger legs; the refused ones are fired from the wrong state or against an
unmet precondition; and the two directions of propagation — parent down to
child, child up to parent — are each exercised once.
"""

from test_helpers import (
    CANONICAL_CAPITAL_STACK,
    CANONICAL_DEPRECIABLE_BASIS_CENTS,
    CANONICAL_OPERATING_TRUST,
    COMPLIANCE,
    QI,
    SPONSOR,
    TRUSTEE,
    add_qualified_investor,
    api_client,
    create_capital_need,
    create_exit_event_payload,
    create_property,
    create_subscription,
    declare_offering_effective,
    fund_loan_facility,
    open_trust_funding,
    read_capital_need,
    read_exchange_file,
    read_exit_event,
    read_loan_facility,
    read_offering,
    read_property,
    read_subscription,
    read_trust,
    record_exit_consent,
    reprice_loan_payload,
    revoke_identification,
    set_clock,
    setup_funding_with_investor_a,
    setup_identified_exchange_file,
    setup_offering_and_loan,
    setup_offering_effective,
    setup_operating_trust,
    setup_proposed_exit,
    setup_reserved_subscription_a,
    setup_trust_forming,
    submit_ppm,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_offering,
)


class TestPropertyAcquisitionEdge:
    def test_acquisition_stamps_the_instant_and_mints_the_basis_in_one_call(self):
        """Both declared side effects land together.

        PRD: "Acquisition drives `UNDER_CONTRACT → ACQUIRED` and is available
        only to the sponsor."

        Design: Corner/state_machines/property_acquire_valid_transition_sets_acquired_at
        """
        deal = setup_trust_forming()
        set_clock("2026-08-20T00:00:00Z")

        acquired = validate_success(
            api_client.acquire_property(deal["property"]["id"], SPONSOR)
        )

        assert acquired["status"] == "ACQUIRED"
        assert acquired["acquired_at"] == "2026-08-20T00:00:00.000Z"
        assert acquired["depreciable_basis_cents"] == CANONICAL_DEPRECIABLE_BASIS_CENTS
        assert acquired["version"] == 2

    def test_a_second_acquisition_is_refused_and_does_not_re_stamp_the_instant(self):
        """The anchor of the depreciation period is written once.

        PRD: "Property from-state — both acquisition and contract expiry require
        `UNDER_CONTRACT`: `ERR_PROPERTY_INVALID_STATE`."

        Design: Corner/state_machines/property_acquire_twice_second_attempt_rejected
        """
        prop = create_property()
        set_clock("2026-08-20T00:00:00Z")
        validate_success(api_client.acquire_property(prop["id"], SPONSOR))
        set_clock("2026-09-01T00:00:00Z")

        response = api_client.acquire_property(prop["id"], SPONSOR)
        validate_error(response, "ERR_PROPERTY_INVALID_STATE", 409)

        again = read_property(prop["id"])
        assert again["acquired_at"] == "2026-08-20T00:00:00.000Z"
        assert again["status"] == "ACQUIRED"
        assert again["version"] == 2


class TestTrustOpenFundingPreconditions:
    def test_opening_funding_names_the_property_precondition_it_violated(self):
        """An effective offering and a committed facility are not enough.

        PRD: "The trust's property is `ACQUIRED`, on opening funding and on loan
        funding: `ERR_PROPERTY_NOT_ACQUIRED`."

        Design: Corner/state_machines/trust_open_funding_requires_acquired_property
        """
        deal = setup_offering_and_loan()
        submit_ppm(deal["offering"]["id"])
        offering = declare_offering_effective(deal["offering"]["id"], 1)
        assert offering["status"] == "EFFECTIVE"

        response = api_client.open_trust_funding(deal["trust"]["id"], TRUSTEE)
        validate_error(response, "ERR_PROPERTY_NOT_ACQUIRED", 409)

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FORMING"
        assert trust["property_acquired_at"] is None
        assert read_property(deal["property"]["id"])["status"] == "UNDER_CONTRACT"


class TestLoanFundingEdge:
    def test_funding_stamps_the_facility_and_books_the_proceeds_leg(self):
        """The trust's cash appears as a journal row, not as a counter.

        PRD: "On success `funded_at` is stamped from the logical clock, a
        `LOAN_PROCEEDS` entry is booked into the `OPERATING` bucket for the full
        `principal_cents` as a positive amount with `source_kind`
        `LOAN_FUNDING`, the trust's `operating_balance_cents` is recomputed and
        the trust's `version` advances."

        Design: Corner/state_machines/loan_fund_books_loan_proceeds_and_stamps_funded_at
        """
        deal = setup_offering_effective()
        open_trust_funding(deal["trust"]["id"])
        assert read_trust(deal["trust"]["id"])["operating_balance_cents"] == 0

        funded = fund_loan_facility(deal["loan"]["id"])

        assert funded["status"] == "FUNDED"
        assert funded["funded_at"] == "2026-08-20T00:00:00.000Z"

        rows, meta = validate_paginated(
            api_client.list_ledger_entries(
                TRUSTEE, params={"trust_id": deal["trust"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "LOAN_PROCEEDS"
        assert rows[0]["bucket"] == "OPERATING"
        assert rows[0]["amount_cents"] == 720_000_000
        assert rows[0]["source_kind"] == "LOAN_FUNDING"
        assert rows[0]["occurred_at"] == "2026-08-20T00:00:00.000Z"

        trust = read_trust(deal["trust"]["id"])
        assert trust["operating_balance_cents"] == 720_000_000
        assert trust["reserve_balance_cents"] == 0
        assert trust["units_issued"] == 0


class TestOfferingEdgesRefusedByFromState:
    def test_resubmitting_the_memorandum_of_an_effective_offering_is_refused(self):
        """Submission is declared from DRAFT only.

        PRD: "Offering from-state for the requested transition — memorandum
        submission requires `DRAFT`; memorandum return and declaring effective
        require `UNDER_REVIEW`; withdrawal requires `DRAFT` or `UNDER_REVIEW`:
        `ERR_OFFERING_INVALID_STATE`."

        Design: Corner/state_machines/offering_submit_ppm_from_effective_state_rejected
        """
        deal = setup_offering_effective()

        response = api_client.submit_ppm(
            deal["offering"]["id"], {"ppm_document_reference": "PPM-2423-r9"}, SPONSOR
        )
        validate_error(response, "ERR_OFFERING_INVALID_STATE", 409)

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "EFFECTIVE"
        assert offering["ppm_version"] == 1
        assert offering["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )

    def test_nothing_leaves_the_withdrawn_terminal_state(self):
        """Neither a second withdrawal nor a fresh submission resurrects it.

        PRD: "A `ComplianceOfficer` may withdraw one that is still `DRAFT` or
        `UNDER_REVIEW`, with an optional `reason`, driving it to `WITHDRAWN`; in
        the same operation every subscription on that offering in status
        `RESERVED` or `REVISION_REQUIRED` is driven to `REJECTED`."

        Design: Corner/state_machines/offering_withdraw_from_withdrawn_terminal_state_rejected
        """
        deal = setup_offering_and_loan()
        withdrawn = withdraw_offering(deal["offering"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"

        second = api_client.withdraw_offering(
            deal["offering"]["id"], COMPLIANCE, {"reason": "again"}
        )
        validate_error(second, "ERR_OFFERING_INVALID_STATE", 409)

        resubmit = api_client.submit_ppm(
            deal["offering"]["id"], {"ppm_document_reference": "PPM-2423-r2"}, SPONSOR
        )
        validate_error(resubmit, "ERR_OFFERING_INVALID_STATE", 409)

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "WITHDRAWN"
        assert offering["ppm_version"] == 1


class TestSubscriptionInitialState:
    def test_a_new_subscription_starts_reserved_with_no_closing_fields(self):
        """A reservation commits the offering's capacity, not the trust's units.

        PRD: "It is created in status `RESERVED`, and its
        `investment_amount_cents` is the `units_requested` multiplied by the
        offering's `unit_price_cents`."

        Design: Corner/state_machines/subscription_initial_state_is_reserved
        """
        deal = setup_funding_with_investor_a()

        subscription = create_subscription(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            deal["offering_version"],
        )

        assert subscription["status"] == "RESERVED"
        assert subscription["closed_at"] is None
        assert subscription["closing_sequence_no"] is None
        assert subscription["rescission_deadline"] is None

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 300
        assert offering["equity_committed_cents"] == 300_000_000

        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == 0
        assert trust["equity_raised_cents"] == 0


class TestOfferingWithdrawalCascadesDownward:
    def test_withdrawal_rejects_the_revision_required_subscription(self):
        """The parent's terminal move sweeps the child, and only the child.

        PRD: "Subscriptions also reach `REJECTED` without anyone asking, by
        three system paths: the hop-four sweep just described, an offering
        withdrawal, and an exchange-file expiry."

        Design: Corner/state_machines/offering_withdraw_cascades_revision_required_subscription_to_rejected
        """
        deal = setup_offering_effective()
        open_trust_funding(deal["trust"]["id"])
        add_qualified_investor(deal, key="investor_a")
        subscription = create_subscription(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            read_offering(deal["offering"]["id"])["version"],
        )
        validate_success(
            api_client.reprice_loan_facility(
                deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
            )
        )
        assert read_subscription(subscription["id"])["status"] == "REVISION_REQUIRED"

        withdrawn = withdraw_offering(
            deal["offering"]["id"], reason="lender pulled the term sheet"
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert read_subscription(subscription["id"])["status"] == "REJECTED"
        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 0
        assert offering["equity_committed_cents"] == 0

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FUNDING"
        assert trust["units_issued"] == 0
        assert trust["equity_raised_cents"] == 0

        _, meta = validate_paginated(
            api_client.list_ledger_entries(
                TRUSTEE, params={"trust_id": deal["trust"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_loan_facility(deal["loan"]["id"])["status"] == "COMMITTED"


class TestIdentificationRevocationBubblesUpward:
    def test_revoking_the_last_active_row_walks_the_file_back_without_new_time(self):
        """The parent's status is derived from its children.

        PRD: "Revoking the last `ACTIVE` row on a file walks it back
        `IDENTIFIED → OPEN`, which is the file's revision loop — identification
        can be unwound while the forty-five-day window is still open."

        Design: Corner/state_machines/identification_revoke_bubbles_exchange_file_back_to_open
        """
        deal = setup_identified_exchange_file()

        revoked = revoke_identification(
            deal["identification"]["id"], reason="wrong property"
        )

        assert revoked["status"] == "REVOKED"
        exchange_file = read_exchange_file(deal["exchange_file"]["id"])
        assert exchange_file["status"] == "OPEN"
        assert exchange_file["identification_deadline"] == "2026-09-19T23:59:59.999Z"
        assert exchange_file["exchange_deadline"] == "2027-02-01T23:59:59.999Z"

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI,
                params={
                    "exchange_file_id": deal["exchange_file"]["id"],
                    "status": "ACTIVE",
                },
            )
        )
        assert meta["total_count"] == 0


class TestCapitalNeedVoidIsConditionalOnFunding:
    def test_voiding_an_unfunded_need_writes_no_ledger_row_at_all(self):
        """Same trigger, no compensation, because nothing was ever booked.

        PRD: "Voiding an `IDENTIFIED` need has no ledger effect, the need never
        having been funded."

        Design: Corner/state_machines/capital_need_void_before_funding_books_no_ledger_entry
        """
        deal = setup_operating_trust()
        need = create_capital_need(
            deal["trust"]["id"],
            need_type="TENANT_IMPROVEMENT",
            amount_cents=12_000_000,
            needed_by="2026-12-31T00:00:00Z",
        )
        assert need["status"] == "IDENTIFIED"

        voided = validate_success(
            api_client.void_capital_need(
                need["id"], TRUSTEE, {"reason": "tenant withdrew the request"}
            )
        )

        assert voided["status"] == "VOIDED"
        stored = read_capital_need(need["id"])
        assert stored["funding_source"] is None
        assert stored["funded_at"] is None

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["reserve_balance_cents"]
        )
        assert trust["operating_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["operating_balance_cents"]
        )

        for entry_type in ("REVERSAL", "RESERVE_DRAW"):
            _, meta = validate_paginated(
                api_client.list_ledger_entries(
                    TRUSTEE,
                    params={
                        "trust_id": deal["trust"]["id"],
                        "entry_type": entry_type,
                    },
                )
            )
            assert meta["total_count"] == 0


class TestExitAndSubscriptionAlternateTerminals:
    def test_abandoning_a_proposal_leaves_the_trust_exactly_as_it_was(self):
        """Only an approved exit freezes a trust.

        PRD: "The sponsor may instead abandon a proposed exit with an optional
        `reason`, moving it `PROPOSED → ABANDONED`; abandonment leaves the
        trust's `status` and `posture` completely untouched, and is itself exempt
        from posture gating."

        Design: Corner/state_machines/exit_event_abandoned_leaves_the_trust_operating
        """
        deal = setup_proposed_exit()
        consent = record_exit_consent(
            deal["exit_event"]["id"],
            deal["subscription_a"]["id"],
            deal["investor_a"]["id"],
            "WITHHOLD",
        )

        abandoned = validate_success(
            api_client.abandon_exit_event(
                deal["exit_event"]["id"], SPONSOR, {"reason": "buyer withdrew"}
            )
        )
        assert abandoned["status"] == "ABANDONED"

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "OPERATING"
        assert trust["posture"] == "OPEN"
        assert trust["springing_llc_armed"] is False
        assert trust["units_issued"] == CANONICAL_OPERATING_TRUST["units_issued"]
        assert trust["equity_raised_cents"] == (
            CANONICAL_OPERATING_TRUST["equity_raised_cents"]
        )

        tally = api_client.tally_consents(deal["exit_event"]["id"], SPONSOR)
        validate_error(tally, "ERR_EXIT_INVALID_STATE", 409)
        assert read_exit_event(deal["exit_event"]["id"])["consented_units"] == 0

        rows, meta = validate_paginated(
            api_client.list_exit_consents(
                SPONSOR, params={"exit_event_id": deal["exit_event"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == consent["id"]
        assert rows[0]["decision"] == "WITHHOLD"

        successor = validate_success(
            api_client.create_exit_event(
                create_exit_event_payload(
                    deal["trust"]["id"],
                    exit_mode="SECTION_721_CONVERSION",
                    expected_close_on="2027-04-01T00:00:00Z",
                ),
                SPONSOR,
            ),
            201,
        )
        assert successor["status"] == "PROPOSED"
        assert successor["exit_mode"] == "SECTION_721_CONVERSION"

    def test_a_compliance_rejection_frees_the_reserved_units_and_locks_the_row(self):
        """Rejection is the manual counterpart of the automatic sweep.

        PRD: "Rejecting a `RESERVED` row removes its units and dollars from the
        offering's committed totals; rejecting a `REVISION_REQUIRED` row has no
        ledger effect and no committed-total effect, because the repricing
        cascade already removed it."

        Design: Corner/state_machines/reserved_subscription_rejected_by_compliance_frees_the_units
        """
        deal = setup_reserved_subscription_a(300)
        version_before = read_offering(deal["offering"]["id"])["version"]

        rejected = validate_success(
            api_client.reject_subscription(
                deal["subscription_a"]["id"],
                COMPLIANCE,
                {"reason": "source of funds unclear"},
            )
        )
        assert rejected["status"] == "REJECTED"

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 0
        assert offering["equity_committed_cents"] == 0
        assert offering["version"] > version_before

        close = api_client.close_subscription(deal["subscription_a"]["id"], SPONSOR)
        validate_error(close, "ERR_SUBSCRIPTION_INVALID_STATE", 409)

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FUNDING"
        assert trust["units_issued"] == 0
        assert trust["equity_raised_cents"] == 0
        assert read_exchange_file(deal["exchange_file_a"]["id"])["status"] == (
            "IDENTIFIED"
        )

        _, meta = validate_paginated(
            api_client.list_ledger_entries(
                TRUSTEE,
                params={
                    "trust_id": deal["trust"]["id"],
                    "entry_type": "EQUITY_CONTRIBUTION",
                },
            )
        )
        assert meta["total_count"] == 0
