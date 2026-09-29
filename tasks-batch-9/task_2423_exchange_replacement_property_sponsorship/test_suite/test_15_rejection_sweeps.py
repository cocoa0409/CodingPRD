"""Refusals, and the exact code each refusal must carry.

The global ladder means a request that breaks several rules reports only one of
them, so every sweep below is arranged so that the rung under study is the
lowest one violated: the neighbouring rungs are satisfied on purpose, and the
assertions pin both the code and the fact that nothing moved behind it.
"""

from test_helpers import (
    ADMIN,
    CANONICAL_CAPITAL_STACK,
    CANONICAL_DISTRIBUTION,
    CANONICAL_LOAN_METRICS,
    CANONICAL_OPERATING_TRUST,
    CANONICAL_TAX_STATEMENT,
    CLOCK,
    COMPLIANCE,
    EXCHANGE_FILE_A,
    EXCHANGE_FILE_B,
    EXCHANGE_FILE_C,
    INVESTOR_A,
    INVESTOR_B,
    INVESTOR_C,
    NOT_FOUND_ERROR_IDS,
    QI,
    SPONSOR,
    TRUSTEE,
    add_qualified_investor,
    api_client,
    build_user_headers,
    close_subscription,
    create_capital_need,
    create_exchange_file,
    create_identification_payload,
    create_investor,
    create_loan_facility_payload,
    create_master_lease_payload,
    create_offering,
    create_property,
    create_property_payload,
    create_subscription,
    create_subscription_payload,
    create_tax_statement,
    create_tax_statement_payload,
    create_trust_payload,
    debt_service_payment_payload,
    declare_offering_effective,
    file_identification,
    list_ledger_entries,
    make_investor_headers,
    offering_version,
    read_capital_need,
    read_distribution,
    read_exchange_file,
    read_investor,
    read_loan_facility,
    read_offering,
    read_property,
    read_subscription,
    read_trust,
    record_exit_consent,
    return_ppm,
    review_suitability,
    revoke_identification,
    set_clock,
    setup_identified_exchange_file,
    setup_offering_and_loan,
    setup_offering_under_review,
    setup_operating_trust,
    setup_operating_with_rent_and_debt,
    setup_paid_distribution,
    setup_proposed_exit,
    setup_trust_forming,
    setup_trust_funding,
    setup_trust_funding_with_lease,
    submit_ppm,
    validate_error,
    validate_paginated,
    validate_success,
    verify_accreditation,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-00000000dead"

# The sixteen single-row reads, in the order §2.9 lists their rejection codes.
GET_BY_ID_READERS = [
    api_client.get_property,
    api_client.get_trust,
    api_client.get_offering,
    api_client.get_investor,
    api_client.get_exchange_file,
    api_client.get_identification,
    api_client.get_subscription,
    api_client.get_loan_facility,
    api_client.get_master_lease,
    api_client.get_ledger_entry,
    api_client.get_capital_need,
    api_client.get_distribution,
    api_client.get_distribution_allocation,
    api_client.get_tax_statement,
    api_client.get_exit_event,
    api_client.get_exit_consent,
]


class TestAuthenticationPrecedesAuthorisation:
    def test_a_role_outside_the_seven_is_not_authenticated(self):
        """An unrecognised role is a 401, never a 403.

        PRD: "A request missing either header, carrying an empty value, or
        naming a role outside the seven the platform recognises is rejected with
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/unauthenticated_when_the_role_header_is_not_a_declared_role
        """
        response = api_client.create_property(
            create_property_payload(), build_user_headers("auditor-1", "Auditor")
        )
        validate_error(response, "ERR_UNAUTHENTICATED", 401)

        rows, meta = validate_paginated(api_client.list_properties(SPONSOR))
        assert rows == []
        assert meta["total_count"] == 0


class TestEveryIdentifierHasItsOwnNotFound:
    def test_the_same_unknown_uuid_reports_sixteen_different_codes(self):
        """The code names the entity the identifier was meant to resolve to.

        PRD: "The mapping from identifier to rejection code is fixed:
        `ERR_PROPERTY_NOT_FOUND` for a `property_id`, `ERR_TRUST_NOT_FOUND` for a
        `trust_id`, `ERR_OFFERING_NOT_FOUND` for an `offering_id`,
        `ERR_INVESTOR_NOT_FOUND` for an `investor_id`,
        `ERR_EXCHANGE_FILE_NOT_FOUND` for an `exchange_file_id`,
        `ERR_IDENTIFICATION_NOT_FOUND` for an `identification_id`,
        `ERR_SUBSCRIPTION_NOT_FOUND` for a `subscription_id`,
        `ERR_LOAN_NOT_FOUND` for a `loan_id`, `ERR_MASTER_LEASE_NOT_FOUND` for a
        `lease_id`, `ERR_LEDGER_ENTRY_NOT_FOUND` for a `ledger_entry_id`,
        `ERR_CAPITAL_NEED_NOT_FOUND` for a `capital_need_id`,
        `ERR_DISTRIBUTION_NOT_FOUND` for a `distribution_id`,
        `ERR_ALLOCATION_NOT_FOUND` for an `allocation_id`,
        `ERR_TAX_STATEMENT_NOT_FOUND` for a `tax_statement_id`,
        `ERR_EXIT_EVENT_NOT_FOUND` for an `exit_event_id` and
        `ERR_EXIT_CONSENT_NOT_FOUND` for an `exit_consent_id`."

        PRD: "All sixteen are 404s."

        Design: Corner/errors/not_found_sweep_across_every_declared_404_code
        """
        assert len(GET_BY_ID_READERS) == len(NOT_FOUND_ERROR_IDS) == 16

        for reader, expected_error_id in zip(GET_BY_ID_READERS, NOT_FOUND_ERROR_IDS):
            validate_error(reader(UNKNOWN_UUID, ADMIN), expected_error_id, 404)


class TestActionsAlreadyTakenAreRefusedByFromState:
    def test_each_machine_reports_its_own_invalid_state_code(self):
        """Four replays on one assembled deal, four different codes.

        PRD: "Trust lifecycle status permits the operation — opening funding
        requires `FORMING`; subscription creation, subscription closing and loan
        funding require `FUNDING`; lease execution requires `FORMING` or
        `FUNDING`; capital-need funding, distribution declaration, exit proposal,
        consent tallying, rent posting and debt-service payment require
        `OPERATING`; distribution payment requires `OPERATING` or
        `WINDING_DOWN`; exit close requires `WINDING_DOWN`:
        `ERR_TRUST_INVALID_STATE`."

        PRD: "Loan facility from-state — repricing requires `COMMITTED` or
        `FUNDED` (a `FUNDED` facility passes this rung and is refused later at
        rung 34 as a prohibited refinancing, so the two codes never collide,
        while a `PAID_OFF` facility is refused here); funding requires
        `COMMITTED`; exit close and debt-service payment require the trust's
        facility to be `FUNDED`: `ERR_LOAN_INVALID_STATE`."

        PRD: "Master lease from-state — execution requires `DRAFT`, termination
        requires `EXECUTED`: `ERR_MASTER_LEASE_INVALID_STATE`."

        PRD: "Subscription from-state — closing requires `RESERVED`; rejection
        requires `RESERVED` or `REVISION_REQUIRED`; rescission requires
        `CLOSED`; and a subscription referenced by a consent, by a tax-statement
        preparation or by a tax-statement issuance must be `CLOSED`:
        `ERR_SUBSCRIPTION_INVALID_STATE`."

        Design: Corner/errors/repeat_lifecycle_action_sweep_returns_invalid_state
        """
        deal = setup_trust_funding_with_lease()
        add_qualified_investor(deal)
        subscription = create_subscription(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            offering_version(deal["offering"]["id"]),
        )
        set_clock(CLOCK["SUB_A_CLOSE"])
        subscription = close_subscription(subscription["id"])
        assert subscription["status"] == "CLOSED"

        validate_error(
            api_client.open_trust_funding(deal["trust"]["id"], TRUSTEE),
            "ERR_TRUST_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.fund_loan_facility(deal["loan"]["id"], TRUSTEE),
            "ERR_LOAN_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.execute_master_lease(deal["lease"]["id"], TRUSTEE),
            "ERR_MASTER_LEASE_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.close_subscription(subscription["id"], SPONSOR),
            "ERR_SUBSCRIPTION_INVALID_STATE",
            409,
        )

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FUNDING"
        assert trust["units_issued"] == 300
        assert trust["equity_raised_cents"] == 300_000_000
        assert trust["operating_balance_cents"] == 1_020_000_000
        assert trust["reserve_balance_cents"] == 0
        assert len(list_ledger_entries(deal["trust"]["id"])) == 2


class TestIdentificationUniquenessAndRevocation:
    def test_a_duplicate_filing_and_a_second_revocation_are_both_refused(self):
        """The pair is unique while active, and a revoked row stays revoked.

        PRD: "Filing after the file's `identification_deadline` is refused with
        `ERR_IDENTIFICATION_WINDOW_CLOSED`, and filing a second `ACTIVE` row for
        the same exchange-file-and-property pair is refused with
        `ERR_DUPLICATE_IDENTIFICATION`."

        PRD: "The intermediary may revoke an identification with an optional
        `reason`, moving it `ACTIVE → REVOKED`; revocation requires the row to be
        `ACTIVE`, the file to be `IDENTIFIED`, and the logical clock to be at or
        before the file's `identification_deadline`."

        Design: Corner/errors/identification_duplicate_filing_and_second_revoke_rejected
        """
        deal = setup_identified_exchange_file()

        duplicate = api_client.create_identification(
            create_identification_payload(
                deal["exchange_file"]["id"], deal["property"]["id"]
            ),
            QI,
        )
        validate_error(duplicate, "ERR_DUPLICATE_IDENTIFICATION", 409)

        revoked = revoke_identification(
            deal["identification"]["id"], reason="filed against the wrong asset"
        )
        assert revoked["status"] == "REVOKED"
        assert read_exchange_file(deal["exchange_file"]["id"])["status"] == "OPEN"

        second = api_client.revoke_identification(
            deal["identification"]["id"], QI, {"reason": "again"}
        )
        validate_error(second, "ERR_IDENTIFICATION_INVALID_STATE", 409)

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI, params={"exchange_file_id": deal["exchange_file"]["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestContractExpiryReachesTheTrustAbove:
    def test_an_expired_contract_blocks_the_acquisition_and_freezes_the_trust(self):
        """One dead deadline stops the property and everything above it.

        PRD: "It requires the property to still be `UNDER_CONTRACT`, and it
        requires the logical clock to be at or before the
        `contract_close_deadline`; a sponsor arriving after that instant is
        refused with `ERR_PROPERTY_CONTRACT_EXPIRED`."

        PRD: "If the property the trust was formed to hold is in status
        `CONTRACT_EXPIRED`, or the trust has any exit event in status `APPROVED`,
        the posture is `FROZEN`."

        PRD: "The sponsor submits it with a `ppm_document_reference`, moving the
        offering `DRAFT → UNDER_REVIEW`; the submission is refused if the trust's
        posture is `FROZEN`, and it records the submitting sponsor's `X-User-ID`
        as `ppm_submitted_by_user_id` for the segregation-of-duties test that
        comes later."

        Design: Corner/errors/property_contract_expiry_blocks_acquisition_and_freezes_the_trust
        """
        deal = setup_offering_and_loan()
        set_clock(CLOCK["OCTOBER"])

        refused = api_client.acquire_property(deal["property"]["id"], SPONSOR)
        validate_error(refused, "ERR_PROPERTY_CONTRACT_EXPIRED", 422)

        expired = validate_success(
            api_client.expire_property_contract(deal["property"]["id"], SPONSOR)
        )
        assert expired["status"] == "CONTRACT_EXPIRED"
        assert read_property(deal["property"]["id"])["acquired_at"] is None

        trust = read_trust(deal["trust"]["id"])
        assert trust["posture"] == "FROZEN"
        assert trust["status"] == "FORMING"

        frozen = api_client.submit_ppm(
            deal["offering"]["id"], {"ppm_document_reference": "PPM-2423-r1"}, SPONSOR
        )
        validate_error(frozen, "ERR_TRUST_FROZEN", 409)

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "DRAFT"
        assert offering["ppm_version"] == 1


class TestLoanCommitmentCreditBox:
    def test_recourse_coverage_leverage_and_a_second_facility_are_all_refused(self):
        """Four refusals, then the one facility the credit box allows.

        PRD: "Any of the three carrying a `recourse_type` of `RECOURSE` is
        refused with `ERR_RECOURSE_DEBT_PROHIBITED` (422)."

        PRD: "The enforced coverage test again uses exact integers: the
        `annual_noi_cents` multiplied by ten thousand must be at least the annual
        debt service multiplied by twelve thousand five hundred — a floor of
        1.2500 times coverage."

        PRD: "The enforced leverage test is a different computation and never
        rounds: the `principal_cents` multiplied by ten thousand must be no
        greater than the property's `appraised_value_cents` multiplied by seven
        thousand five hundred — a ceiling of seventy-five percent expressed in
        basis points."

        PRD: "A trust may hold only one live facility at a time: a second
        facility requested while one is already in `COMMITTED` or `FUNDED` status
        is refused with `ERR_MULTIPLE_LOANS_PROHIBITED` (409)."

        Design: Corner/errors/loan_creation_error_sweep_recourse_dscr_ltv_and_duplicate
        """
        deal = setup_trust_forming()
        trust_id = deal["trust"]["id"]

        recourse = api_client.create_loan_facility(
            create_loan_facility_payload(trust_id, recourse_type="RECOURSE"), TRUSTEE
        )
        validate_error(recourse, "ERR_RECOURSE_DEBT_PROHIBITED", 422)

        # 900,000,000 at 1500 bps sits exactly on the leverage ceiling, so the
        # only rung it can fail is coverage.
        thin_coverage = api_client.create_loan_facility(
            create_loan_facility_payload(
                trust_id, principal_cents=900_000_000, rate_bps=1500
            ),
            TRUSTEE,
        )
        validate_error(thin_coverage, "ERR_DSCR_BELOW_MINIMUM", 422)

        one_cent_over = api_client.create_loan_facility(
            create_loan_facility_payload(trust_id, principal_cents=900_000_001),
            TRUSTEE,
        )
        validate_error(one_cent_over, "ERR_LTV_LIMIT_EXCEEDED", 422)

        facility = validate_success(
            api_client.create_loan_facility(
                create_loan_facility_payload(trust_id), TRUSTEE
            ),
            201,
        )
        assert facility["status"] == "COMMITTED"
        assert facility["ltv_pct"] == CANONICAL_LOAN_METRICS["ltv_pct"]
        assert facility["dscr"] == CANONICAL_LOAN_METRICS["dscr"]
        assert facility["repriced_count"] == 0
        assert facility["funded_at"] is None

        second = api_client.create_loan_facility(
            create_loan_facility_payload(trust_id, lender_name="Delta River Mutual"),
            TRUSTEE,
        )
        validate_error(second, "ERR_MULTIPLE_LOANS_PROHIBITED", 409)

        rows, meta = validate_paginated(
            api_client.list_loan_facilities(TRUSTEE, params={"trust_id": trust_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == facility["id"]


class TestOnePropertyBacksOneLiveTrust:
    def test_a_second_trust_over_the_same_property_is_refused(self):
        """The property is the scarce resource, not the trust name.

        PRD: "A property may back only one live trust: if a trust already holds
        it in status `FORMING`, `FUNDING`, `OPERATING` or `WINDING_DOWN`,
        formation is refused with `ERR_PROPERTY_ALREADY_TRUSTED`."

        Design: Corner/errors/second_trust_on_an_already_trusted_property_rejected
        """
        deal = setup_trust_forming()

        response = api_client.create_trust(
            create_trust_payload(
                deal["property"]["id"], trust_name="DST 2423-B Cypress"
            ),
            TRUSTEE,
        )
        validate_error(response, "ERR_PROPERTY_ALREADY_TRUSTED", 409)

        rows, meta = validate_paginated(
            api_client.list_trusts(
                TRUSTEE, params={"property_id": deal["property"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == deal["trust"]["id"]


class TestInvestorGatesInPriorityOrder:
    def test_the_same_payload_walks_accreditation_then_suitability_then_succeeds(self):
        """One payload, three answers, driven only by the investor's row.

        PRD: "The investor's `accreditation_status` must be `VERIFIED` — an
        `UNVERIFIED` investor draws `ERR_INVESTOR_NOT_ACCREDITED` — and the
        logical clock must be **strictly before** the investor's
        `accreditation_expires_at`, so an investor whose verification expires at
        exactly this instant draws `ERR_ACCREDITATION_EXPIRED`."

        PRD: "The server stamps `accreditation_verified_at` with the current
        logical instant and sets `accreditation_expires_at` to ninety days after
        it; a verification is good for that ninety-day window and no longer."

        PRD: "Similarly, at rungs 28 through 31 an investor who is both
        unverified and unreviewed reports `ERR_INVESTOR_NOT_ACCREDITED`, and the
        suitability code only appears once accreditation is clean."

        Design: Corner/errors/subscription_gate_sweep_accreditation_then_suitability_then_accepted
        """
        deal = setup_trust_funding()
        investor = create_investor(**INVESTOR_A)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        file_identification(exchange_file["id"], deal["property"]["id"])

        payload = create_subscription_payload(
            deal["offering"]["id"],
            investor["id"],
            exchange_file["id"],
            300,
            offering_version(deal["offering"]["id"]),
        )

        unverified = api_client.create_subscription(payload, SPONSOR)
        validate_error(unverified, "ERR_INVESTOR_NOT_ACCREDITED", 422)

        verified = verify_accreditation(investor["id"], "NW-STMT-A-2026")
        assert verified["accreditation_status"] == "VERIFIED"
        assert verified["accreditation_verified_at"] == "2026-08-20T00:00:00.000Z"
        assert verified["accreditation_expires_at"] == "2026-11-18T00:00:00.000Z"
        assert verified["suitability_status"] == "NOT_REVIEWED"

        unreviewed = api_client.create_subscription(payload, SPONSOR)
        validate_error(unreviewed, "ERR_SUITABILITY_NOT_APPROVED", 422)

        reviewed = review_suitability(investor["id"], deal["offering"]["id"], "APPROVED")
        assert reviewed["suitability_status"] == "APPROVED"
        assert reviewed["suitability_cap_cents"] == 359_340_659

        accepted = validate_success(
            api_client.create_subscription(payload, SPONSOR), 201
        )
        assert accepted["status"] == "RESERVED"
        assert accepted["investment_amount_cents"] == 300_000_000
        assert read_offering(deal["offering"]["id"])["units_committed"] == 300


class TestSuitabilityIsScopedToOneOffering:
    def test_an_approval_recorded_against_another_offering_does_not_travel(self):
        """Two effective offerings, one review, and it names the other one.

        PRD: "The investor's `suitability_status` must be `APPROVED`, and the
        investor's `suitability_offering_id` must equal this subscription's
        `offering_id`, because a suitability review scoped to a different
        offering says nothing about this one — a mismatch is
        `ERR_SUITABILITY_OFFERING_MISMATCH`."

        PRD: "The review records `suitability_offering_id` as the offering
        reviewed and `suitability_reviewed_by_user_id` as the acting officer's
        `X-User-ID`, which is the value the closing sponsor will later be
        compared against."

        Design: Corner/errors/subscription_when_suitability_was_reviewed_against_another_offering_rejected
        """
        deal = setup_trust_funding()
        other = create_offering(deal["trust"]["id"])
        submit_ppm(other["id"], "PPM-2423-B-r1")
        other = declare_offering_effective(other["id"], 1)
        assert other["status"] == "EFFECTIVE"
        assert other["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )

        investor = create_investor(**INVESTOR_A)
        verify_accreditation(investor["id"], "NW-STMT-A-2026")
        reviewed = review_suitability(investor["id"], other["id"], "APPROVED")
        assert reviewed["suitability_offering_id"] == other["id"]
        assert reviewed["suitability_cap_cents"] == 359_340_659

        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        file_identification(exchange_file["id"], deal["property"]["id"])

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                investor["id"],
                exchange_file["id"],
                300,
                offering_version(deal["offering"]["id"]),
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_SUITABILITY_OFFERING_MISMATCH", 422)

        assert read_investor(investor["id"])["suitability_status"] == "APPROVED"
        assert read_offering(deal["offering"]["id"])["units_committed"] == 0
        assert read_offering(other["id"])["units_committed"] == 0

        _, meta = validate_paginated(
            api_client.list_subscriptions(SPONSOR, params={"investor_id": investor["id"]})
        )
        assert meta["total_count"] == 0


class TestConcentrationCapBitesBeforeCapacity:
    def test_an_order_the_offering_could_absorb_still_exceeds_the_investors_cap(self):
        """Four hundred units fit the raise; they do not fit the investor.

        PRD: "The cap that governs is the minimum of those three. It is compared
        against a subscription's `investment_amount_cents` at creation time, and
        an over-cap order is refused with `ERR_SUITABILITY_CAP_EXCEEDED`."

        PRD: "The **liquidity cap** is the investor's `liquid_net_worth_cents`
        multiplied by the concentration band its `entity_type` earns, floored."

        Design: Corner/errors/subscription_above_the_investor_suitability_cap_rejected
        """
        deal = setup_trust_funding()
        add_qualified_investor(
            deal,
            key="investor_b",
            investor_profile=INVESTOR_B,
            exchange_file=EXCHANGE_FILE_B,
            evidence_reference="CPA-LTR-B-2026",
        )
        assert read_investor(deal["investor_b"]["id"])["suitability_cap_cents"] == (
            350_000_000
        )

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_b"]["id"],
                deal["exchange_file_b"]["id"],
                400,
                offering_version(deal["offering"]["id"]),
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_SUITABILITY_CAP_EXCEEDED", 422)

        # 400 units would have sat inside the 620 authorised units, so the
        # refusal is the concentration cap and not the capacity rung.
        assert read_trust(deal["trust"]["id"])["total_units"] == 620
        assert read_offering(deal["offering"]["id"])["units_committed"] == 0


class TestOfferingMinimumIsAUnitCount:
    def test_one_unit_short_is_refused_and_exactly_the_minimum_is_accepted(self):
        """Fourteen units is refused; the very next call at fifteen is not.

        PRD: "The `units_requested` must be at least the offering's
        `min_units_per_investor`, or `ERR_BELOW_MINIMUM_INVESTMENT`."

        Design: Corner/errors/subscription_below_the_minimum_unit_count_rejected
        """
        deal = setup_trust_funding()
        add_qualified_investor(
            deal,
            key="investor_c",
            investor_profile=INVESTOR_C,
            exchange_file=EXCHANGE_FILE_C,
            evidence_reference="CPA-LTR-C-2026",
        )
        assert read_offering(deal["offering"]["id"])["min_units_per_investor"] == 15
        version = offering_version(deal["offering"]["id"])

        short = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_c"]["id"],
                deal["exchange_file_c"]["id"],
                14,
                version,
            ),
            SPONSOR,
        )
        validate_error(short, "ERR_BELOW_MINIMUM_INVESTMENT", 422)

        accepted = validate_success(
            api_client.create_subscription(
                create_subscription_payload(
                    deal["offering"]["id"],
                    deal["investor_c"]["id"],
                    deal["exchange_file_c"]["id"],
                    15,
                    version,
                ),
                SPONSOR,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        assert accepted["investment_amount_cents"] == 15_000_000

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 15
        assert offering["equity_committed_cents"] == 15_000_000


class TestRescissionWindowIsMeasuredFromTheClose:
    def test_a_rescission_two_months_late_leaves_the_units_issued(self):
        """The window ran from the close, and it is long gone.

        PRD: "The acting `Investor` must be the subscription's own
        `investor_id`, the subscription must be `CLOSED`, and the logical clock
        must be at or before the `rescission_deadline`, that boundary instant
        still being inside the window; arriving later is
        `ERR_RESCISSION_WINDOW_CLOSED`."

        Design: Corner/errors/subscription_rescind_after_the_window_has_closed_rejected
        """
        deal = setup_operating_trust()
        subscription = read_subscription(deal["subscription_a"]["id"])
        assert subscription["closed_at"] == "2026-09-15T00:00:00.000Z"
        assert subscription["rescission_deadline"] == "2026-09-20T00:00:00.000Z"

        response = api_client.rescind_subscription(
            subscription["id"], make_investor_headers(deal["investor_a"]["id"])
        )
        validate_error(response, "ERR_RESCISSION_WINDOW_CLOSED", 409)

        assert read_subscription(subscription["id"])["status"] == "CLOSED"
        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == CANONICAL_OPERATING_TRUST["units_issued"]
        assert trust["equity_raised_cents"] == (
            CANONICAL_OPERATING_TRUST["equity_raised_cents"]
        )
        assert list_ledger_entries(deal["trust"]["id"], entry_type="REVERSAL") == []


class TestNoNewLeaseAfterTheOfferingPeriod:
    def test_a_term_that_overlaps_nothing_is_still_refused(self):
        """The prohibition is about trustee powers, not about calendars.

        PRD: "Once the trust has left the offering period — that is, once its
        status is `OPERATING`, `WINDING_DOWN`, `TERMINATED` or `CONVERTED_LLC`,
        at which point it necessarily already holds a master lease in status
        `EXECUTED` — drafting another lease is refused with
        `ERR_NEW_LEASE_PROHIBITED` (422)."

        Design: Corner/errors/new_master_lease_prohibited_once_the_trust_is_operating
        """
        deal = setup_operating_trust()

        response = api_client.create_master_lease(
            create_master_lease_payload(
                deal["trust"]["id"],
                master_tenant_user_id="tenant-2",
                term_start_on="2034-01-01",
                term_end_on="2040-12-31",
                base_rent_annual_cents=95_000_000,
                supplemental_rent_annual_cents=1_600_000,
            ),
            TRUSTEE,
        )
        validate_error(response, "ERR_NEW_LEASE_PROHIBITED", 422)

        rows, meta = validate_paginated(
            api_client.list_master_leases(
                TRUSTEE, params={"trust_id": deal["trust"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "EXECUTED"
        assert rows[0]["master_tenant_user_id"] == "tenant-1"


class TestStructuralWorkIsNotAReserveExpense:
    def test_the_reserve_may_not_pay_for_structural_capital_expenditure(self):
        """The reserve could cover it; the trust still may not spend it.

        PRD: "the `need_type` must not be `STRUCTURAL_CAPEX` (otherwise
        `ERR_STRUCTURAL_CAPEX_PROHIBITED`, structural work being the master
        tenant's burden), and the trust's `reserve_balance_cents` must be at
        least the need's `amount_cents`, or `ERR_RESERVE_INSUFFICIENT`."

        Design: Corner/errors/structural_capex_funded_from_the_reserve_rejected
        """
        deal = setup_operating_trust()
        need = create_capital_need(
            deal["trust"]["id"],
            need_type="STRUCTURAL_CAPEX",
            amount_cents=20_000_000,
            needed_by="2027-01-31T00:00:00Z",
        )

        response = api_client.fund_capital_need(
            need["id"], {"funding_source": "RESERVE"}, TRUSTEE
        )
        validate_error(response, "ERR_STRUCTURAL_CAPEX_PROHIBITED", 422)

        stored = read_capital_need(need["id"])
        assert stored["status"] == "IDENTIFIED"
        assert stored["funding_source"] is None

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 30_000_000
        assert list_ledger_entries(deal["trust"]["id"], entry_type="RESERVE_DRAW") == []


class TestTheAcknowledgementMustNameTheCurrentRevision:
    def test_acknowledging_the_superseded_revision_is_refused(self):
        """A return-and-resubmit cycle leaves revision one behind.

        PRD: "A `ComplianceOfficer` may return the memorandum for revision with
        an optional `review_note`, moving it `UNDER_REVIEW → DRAFT` and
        incrementing `ppm_version` by exactly 1."

        PRD: "And the request's `acknowledged_ppm_version` must equal the
        offering's current `ppm_version`, or it is refused with
        `ERR_PPM_VERSION_STALE`."

        Design: Corner/errors/declare_effective_with_a_stale_acknowledged_ppm_version_rejected
        """
        deal = setup_offering_under_review()
        returned = return_ppm(deal["offering"]["id"])
        assert returned["status"] == "DRAFT"
        assert returned["ppm_version"] == 2

        resubmitted = submit_ppm(deal["offering"]["id"], "PPM-2423-r2")
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["ppm_version"] == 2

        stale = api_client.declare_offering_effective(
            deal["offering"]["id"], {"acknowledged_ppm_version": 1}, COMPLIANCE
        )
        validate_error(stale, "ERR_PPM_VERSION_STALE", 409)

        held = read_offering(deal["offering"]["id"])
        assert held["status"] == "UNDER_REVIEW"
        assert held["ppm_version"] == 2
        assert held["ppm_submitted_by_user_id"] == "sponsor-1"
        assert held["effective_at"] is None

        effective = validate_success(
            api_client.declare_offering_effective(
                deal["offering"]["id"], {"acknowledged_ppm_version": 2}, COMPLIANCE
            )
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["effective_at"] == "2026-08-20T00:00:00.000Z"
        assert effective["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )
        assert effective["sponsor_load_cents"] == (
            CANONICAL_CAPITAL_STACK["sponsor_load_cents"]
        )


class TestAuthorisedUnitsMustCarryTheGrossedUpEquity:
    def test_five_hundred_units_cannot_raise_the_pinned_target(self):
        """Capacity is tested against the grossed-up figure, not the net need.

        PRD: "Declaring effective also tests whether the trust could ever raise
        the number just computed: the authorised unit capacity, being the trust's
        `total_units` multiplied by the offering's `unit_price_cents`, must be at
        least `target_equity_cents`, and exact equality passes."

        PRD: "A shortfall is refused with `ERR_OFFERING_CAPACITY_SHORTFALL`."

        Design: Corner/errors/declare_effective_rejected_when_units_cannot_raise_the_target
        """
        deal = setup_offering_under_review(trust={"total_units": 500})

        response = api_client.declare_offering_effective(
            deal["offering"]["id"], {"acknowledged_ppm_version": 1}, COMPLIANCE
        )
        validate_error(response, "ERR_OFFERING_CAPACITY_SHORTFALL", 422)

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "UNDER_REVIEW"
        assert offering["effective_at"] is None
        assert offering["target_equity_cents"] is None
        assert read_trust(deal["trust"]["id"])["status"] == "FORMING"


class TestExitWorkflowSequencing:
    def test_the_premature_close_the_empty_tally_and_the_second_vote_are_refused(self):
        """The exit is a strict sequence over a non-empty consent set.

        PRD: "Trust lifecycle status permits the operation — opening funding
        requires `FORMING`; subscription creation, subscription closing and loan
        funding require `FUNDING`; lease execution requires `FORMING` or
        `FUNDING`; capital-need funding, distribution declaration, exit proposal,
        consent tallying, rent posting and debt-service payment require
        `OPERATING`; distribution payment requires `OPERATING` or
        `WINDING_DOWN`; exit close requires `WINDING_DOWN`:
        `ERR_TRUST_INVALID_STATE`."

        PRD: "It requires the event to be `PROPOSED`, the trust to be
        `OPERATING`, and **at least one** consent row to exist: an empty consent
        set is not a zero-percent rejection, it is an untallied event, and it is
        refused with `ERR_NO_CONSENTS_RECORDED`."

        PRD: "One vote per subscription: a second consent for the same
        `exit_event_id` and `subscription_id` pair is refused with
        `ERR_DUPLICATE_CONSENT`."

        Design: Corner/errors/exit_workflow_sequencing_and_duplicate_consent_rejected
        """
        deal = setup_proposed_exit()
        exit_id = deal["exit_event"]["id"]

        premature = api_client.close_exit_event(exit_id, TRUSTEE)
        validate_error(premature, "ERR_TRUST_INVALID_STATE", 409)

        empty_tally = api_client.tally_consents(exit_id, SPONSOR)
        validate_error(empty_tally, "ERR_NO_CONSENTS_RECORDED", 422)
        assert read_trust(deal["trust"]["id"])["status"] == "OPERATING"

        consent = record_exit_consent(
            exit_id,
            deal["subscription_a"]["id"],
            deal["investor_a"]["id"],
            "CONSENT",
        )
        assert consent["decision"] == "CONSENT"
        assert consent["units_at_consent"] == 300

        duplicate = api_client.create_exit_consent(
            {
                "exit_event_id": exit_id,
                "subscription_id": deal["subscription_a"]["id"],
                "decision": "WITHHOLD",
            },
            make_investor_headers(deal["investor_a"]["id"]),
        )
        validate_error(duplicate, "ERR_DUPLICATE_CONSENT", 409)

        _, meta = validate_paginated(
            api_client.list_exit_consents(SPONSOR, params={"exit_event_id": exit_id})
        )
        assert meta["total_count"] == 1

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "OPERATING"
        assert trust["posture"] == "OPEN"


class TestOperatingBucketIsNeverOverdrawn:
    def test_the_reserve_is_not_raided_to_cover_interest(self):
        """Thirty million sits in reserve and none of it is available.

        PRD: "The trust's facility must be in status `FUNDED`, and the trust's
        `operating_balance_cents` must be at least the amount about to leave the
        bucket, or `ERR_OPERATING_CASH_INSUFFICIENT`."

        Design: Corner/errors/debt_service_payment_above_the_operating_balance_rejected
        """
        deal = setup_operating_trust()
        assert deal["loan"]["status"] == "FUNDED"

        response = api_client.post_debt_service_payment(
            deal["trust"]["id"], debt_service_payment_payload(amount_cents=2_000_000), TRUSTEE
        )
        validate_error(response, "ERR_OPERATING_CASH_INSUFFICIENT", 422)

        trust = read_trust(deal["trust"]["id"])
        assert trust["operating_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["operating_balance_cents"]
        )
        assert trust["reserve_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["reserve_balance_cents"]
        )
        assert list_ledger_entries(deal["trust"]["id"], entry_type="DEBT_SERVICE") == []
        assert read_loan_facility(deal["loan"]["id"])["status"] == "FUNDED"


class TestPaymentIsTerminalForADistribution:
    def test_neither_a_replayed_payment_nor_a_void_moves_the_cash_again(self):
        """Both replays report the same from-state code and change nothing.

        PRD: "The distribution is `DECLARED`, on payment and on voiding:
        `ERR_DISTRIBUTION_INVALID_STATE`."

        PRD: "A declared distribution may instead be voided by the `Trustee`
        with an optional `reason`, moving it `DECLARED → VOIDED`."

        Design: Corner/errors/distribution_pay_and_void_after_payment_rejected
        """
        deal = setup_paid_distribution()
        distribution_id = deal["distribution"]["id"]

        replay = api_client.pay_distribution(distribution_id, TRUSTEE)
        validate_error(replay, "ERR_DISTRIBUTION_INVALID_STATE", 409)

        void = api_client.void_distribution(
            distribution_id, TRUSTEE, {"reason": "late correction"}
        )
        validate_error(void, "ERR_DISTRIBUTION_INVALID_STATE", 409)

        stored = read_distribution(distribution_id)
        assert stored["status"] == "PAID"
        assert stored["final_amount_cents"] == (
            CANONICAL_DISTRIBUTION["final_amount_cents"]
        )
        assert stored["reconciliation_delta_cents"] == (
            CANONICAL_DISTRIBUTION["reconciliation_delta_cents"]
        )

        trust = read_trust(deal["trust"]["id"])
        assert trust["operating_balance_cents"] == 1_098_901
        assert trust["reserve_balance_cents"] == (
            CANONICAL_DISTRIBUTION["reserve_balance_after_pay_cents"]
        )

        _, meta = validate_paginated(
            api_client.list_distribution_allocations(
                TRUSTEE, params={"distribution_id": distribution_id}
            )
        )
        assert meta["total_count"] == 2


class TestIdentificationDeadlineIsInclusiveOfItsLastMillisecond:
    def test_one_millisecond_past_the_deadline_is_outside_the_window(self):
        """The forty-fifth day ends at .999, and nothing after it counts.

        PRD: "The `identification_deadline` is forty-five days after that date,
        snapped to `23:59:59.999Z` on the forty-fifth day; the `exchange_deadline`
        is one hundred eighty days after that date, snapped to `23:59:59.999Z` on
        the one-hundred-eightieth day."

        PRD: "Filing after the file's `identification_deadline` is refused with
        `ERR_IDENTIFICATION_WINDOW_CLOSED`, and filing a second `ACTIVE` row for
        the same exchange-file-and-property pair is refused with
        `ERR_DUPLICATE_IDENTIFICATION`."

        Design: Corner/errors/identification_one_millisecond_past_the_deadline_rejected
        """
        set_clock(CLOCK["START"])
        prop = create_property()
        investor = create_investor(**INVESTOR_A)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        assert exchange_file["identification_deadline"] == "2026-09-19T23:59:59.999Z"

        set_clock(CLOCK["PAST_IDENTIFICATION_DEADLINE_A"])
        response = api_client.create_identification(
            create_identification_payload(exchange_file["id"], prop["id"]), QI
        )
        validate_error(response, "ERR_IDENTIFICATION_WINDOW_CLOSED", 422)

        stored = read_exchange_file(exchange_file["id"])
        assert stored["status"] == "OPEN"
        assert stored["identification_deadline"] == "2026-09-19T23:59:59.999Z"

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI, params={"exchange_file_id": exchange_file["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestExchangeDeadlineIsEnforcedOnItsOwn:
    def test_a_fresh_accreditation_does_not_revive_a_dead_exchange(self):
        """The only stale clock is the one hundred eightieth day.

        PRD: "The logical clock is at or before the file's `exchange_deadline`,
        on subscription creation and closing: `ERR_EXCHANGE_DEADLINE_PASSED`."

        PRD: "The exchange file must be in status `IDENTIFIED`, its
        `investor_id` must equal the subscription's `investor_id` (otherwise
        `ERR_EXCHANGE_FILE_INVESTOR_MISMATCH`), it must carry an `ACTIVE`
        identification naming the trust's `property_id` (otherwise
        `ERR_IDENTIFICATION_MISSING_FOR_TRUST` — a taxpayer may not buy into a
        property it never identified), and the logical clock must be at or before
        the file's `exchange_deadline`."

        Design: Corner/errors/subscription_after_the_exchange_deadline_rejected
        """
        deal = setup_trust_funding()
        investor = create_investor(**INVESTOR_A)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        file_identification(exchange_file["id"], deal["property"]["id"])
        assert read_exchange_file(exchange_file["id"])["exchange_deadline"] == (
            "2027-02-01T23:59:59.999Z"
        )

        # Accreditation is re-verified late in the exchange so that the only
        # expired clock the request can trip over is the exchange deadline.
        set_clock("2027-01-20T00:00:00Z")
        investor = verify_accreditation(investor["id"], "NW-STMT-A-2026")
        assert investor["accreditation_expires_at"] == "2027-04-20T00:00:00.000Z"
        review_suitability(investor["id"], deal["offering"]["id"], "APPROVED")

        set_clock("2027-02-02T00:00:00Z")
        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                investor["id"],
                exchange_file["id"],
                300,
                offering_version(deal["offering"]["id"]),
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_EXCHANGE_DEADLINE_PASSED", 422)

        assert read_exchange_file(exchange_file["id"])["status"] == "IDENTIFIED"
        assert read_investor(investor["id"])["accreditation_status"] == "VERIFIED"
        assert read_offering(deal["offering"]["id"])["units_committed"] == 0


class TestOfferingStatusOutranksTheInvestorGates:
    def test_a_draft_offering_is_refused_before_the_investors_own_gaps(self):
        """The subscriber is unverified too, and that code never appears.

        PRD: "The named offering must be in status `EFFECTIVE`, otherwise
        `ERR_OFFERING_NOT_EFFECTIVE`."

        PRD: "The offering is created in status `DRAFT` with `ppm_version` 1 and
        with `units_committed` and `equity_committed_cents` at zero."

        Design: Corner/errors/subscription_against_a_draft_offering_rejected
        """
        deal = setup_trust_funding()
        draft = create_offering(deal["trust"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["ppm_version"] == 1

        investor = create_investor(**INVESTOR_A)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        file_identification(exchange_file["id"], deal["property"]["id"])

        response = api_client.create_subscription(
            create_subscription_payload(
                draft["id"],
                investor["id"],
                exchange_file["id"],
                300,
                offering_version(draft["id"]),
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_OFFERING_NOT_EFFECTIVE", 409)

        assert read_investor(investor["id"])["accreditation_status"] == "UNVERIFIED"
        held = read_offering(draft["id"])
        assert held["status"] == "DRAFT"
        assert held["target_equity_cents"] is None

        _, meta = validate_paginated(
            api_client.list_subscriptions(SPONSOR, params={"offering_id": draft["id"]})
        )
        assert meta["total_count"] == 0


class TestTaxStatementUniquenessAndIssuance:
    def test_the_quadruple_is_unique_and_issuance_happens_once(self):
        """The same quadruple twice, and the same issuance twice.

        PRD: "A statement is unique per `trust_id`, `subscription_id`, `tax_year`
        and `allocation_variant` taken together; a second statement for that
        quadruple is refused with `ERR_DUPLICATE_TAX_STATEMENT`."

        PRD: "Issuing a statement moves it `DRAFT → ISSUED`, requires the
        statement to be `DRAFT` and its subscription still `CLOSED`, stamps
        `issued_at` from the logical clock, and renders the statement
        immutable."

        Design: Corner/errors/tax_statement_duplicate_quadruple_and_reissue_rejected
        """
        deal = setup_operating_with_rent_and_debt()
        statement = create_tax_statement(
            deal["trust"]["id"], deal["subscription_a"]["id"]
        )
        assert statement["status"] == "DRAFT"
        assert statement["issued_at"] is None

        duplicate = api_client.create_tax_statement(
            create_tax_statement_payload(
                deal["trust"]["id"], deal["subscription_a"]["id"]
            ),
            SPONSOR,
        )
        validate_error(duplicate, "ERR_DUPLICATE_TAX_STATEMENT", 409)

        issued = validate_success(
            api_client.issue_tax_statement(statement["id"], SPONSOR)
        )
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] == "2027-01-02T00:00:00.000Z"
        assert issued["net_taxable_income_cents"] == (
            CANONICAL_TAX_STATEMENT["UNITS_AT_YEAR_END"]["net_taxable_income_cents"]
        )

        reissue = api_client.issue_tax_statement(statement["id"], SPONSOR)
        validate_error(reissue, "ERR_TAX_STATEMENT_INVALID_STATE", 409)

        _, meta = validate_paginated(
            api_client.list_tax_statements(
                SPONSOR, params={"trust_id": deal["trust"]["id"], "tax_year": 2026}
            )
        )
        assert meta["total_count"] == 1
