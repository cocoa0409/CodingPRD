"""Entity-surface corners: creation echoes, declared defaults, server-stamped
system fields, computed reads, filter-scoped listings, referential integrity and
the one append-only audit record.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TX_RULE,
    assert_no_common_field_drift,
    assert_producer_agent,
    assert_state_rate_rule,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


class TestStateRateRuleCreationEchoesEveryDeclaredField:
    """Sixteen inputs go in and sixteen come back unchanged, plus the derived
    counter and the common fields."""

    def test_creation_returns_201_with_every_input_echoed_verbatim(self, api):
        """Nothing is silently coerced on the way in.

        The PRD states: "Registering a regime supplies its `state_code`, its
        `finance_charge_method`, and the whole statutory parameter set described in
        section 2.9 — `max_annual_rate_bps`, `max_service_fee_cents`,
        `min_down_payment_bps`, `max_term_months`, `late_fee_bps`,
        `late_fee_min_cents`, `late_fee_max_cents`, `grace_period_days`,
        `noic_notice_days`, `unearned_premium_method`, `short_rate_penalty_bps`,
        `rebate_method` and `max_late_fees_per_agreement` — with `license_required`
        optional and defaulting to true."

        Design: Corner/entities/creation_state_rate_rule_returns_201_with_every_declared_field
        """
        payload = dict(TX_RULE)

        rule = validate_success(api.create_state_rate_rule(payload, COMPLIANCE), 201)

        assert_state_rate_rule(rule)
        for key, value in payload.items():
            assert rule[key] == value, f"{key} was not echoed verbatim"
        assert rule["late_fee_max_cents"] >= rule["late_fee_min_cents"]
        assert is_valid_uuid(rule["id"])
        assert rule["version"] == 1
        assert is_iso8601_timestamp(rule["created_at"])

    def test_the_derived_counter_starts_at_zero_and_is_not_an_input(self, api):
        """No agreement references the regime yet, so the counter is zero.

        The PRD states: "The new regime starts with `active_agreement_count` at
        zero."

        Design: Corner/entities/creation_state_rate_rule_returns_201_with_every_declared_field
        """
        rule = validate_success(
            api.create_state_rate_rule(dict(TX_RULE), COMPLIANCE), 201
        )

        assert rule["active_agreement_count"] == 0
        assert "active_agreement_count" not in TX_RULE, (
            "the counter is derived and was never part of the request body"
        )

    def test_the_regime_is_persisted_rather_than_merely_echoed(self, api):
        """A re-read reports the same regime and the same live counter.

        The PRD states: "Reading a regime back returns the live counter, so a
        compliance officer can see how many notes are currently exposed to that
        statute."

        Design: Corner/entities/creation_state_rate_rule_returns_201_with_every_declared_field
        """
        created = validate_success(
            api.create_state_rate_rule(dict(TX_RULE), COMPLIANCE), 201
        )

        reread = validate_success(
            api.get_state_rate_rule(created["id"], ANALYST_ORIGIN), 200
        )

        assert reread["state_code"] == "TX"
        assert reread["active_agreement_count"] == 0
        assert reread["id"] == created["id"]
        assert reread["version"] == 1


class TestDeclaredDefaultsWhenOptionalInputsAreOmitted:
    """Four optional inputs across three entities each land on their declared
    default rather than on null."""

    def test_license_required_defaults_to_true_on_an_omitted_flag(self, api):
        """A regime created without the flag is still gated.

        The PRD states: "Finally, `license_required` is a boolean that defaults to
        true and states whether an effective premium finance license is needed to
        originate in that state, and `active_agreement_count` is a derived counter,
        starting at 0, holding the number of agreements referencing this regime
        whose financing status is either `PENDING_VERIFICATION` or `ACTIVE`."

        Design: Corner/entities/default_license_required_and_reserve_balance_when_optional_inputs_omitted
        """
        payload = dict(TX_RULE, state_code="OK")
        payload.pop("license_required")

        rule = validate_success(api.create_state_rate_rule(payload, COMPLIANCE), 201)

        assert rule["license_required"] is True, (
            "defaulting the flag to false would silently disable the licensing "
            "gate for every regime created without it"
        )
        assert rule["active_agreement_count"] == 0

    def test_the_carrier_status_defaults_to_active(self, api):
        """An omitted carrier status is admitted for new financing.

        The PRD states: "Carriers are registered by a compliance officer with a
        non-empty `carrier_name`, a `naic_code` that must be unique across all
        carriers, and an optional `status` of `ACTIVE` or `INACTIVE` that defaults
        to `ACTIVE`; a carrier's status is fixed at creation and records whether the
        carrier is admitted for new financing, and there is no operation that
        changes it afterwards."

        Design: Corner/entities/default_license_required_and_reserve_balance_when_optional_inputs_omitted
        """
        insurer = validate_success(
            api.create_insurer(
                {"carrier_name": "Sooner Mutual", "naic_code": "20777"}, COMPLIANCE
            ),
            201,
        )

        assert insurer["status"] == "ACTIVE"

    def test_the_license_is_born_active_and_immediately_effective(self, api):
        """The derived flag is computed from the status, the window and the clock.

        The PRD states: "A compliance officer records one by supplying its
        `license_number`, `effective_date` and `expiration_date`; the platform
        stamps `status` as `ACTIVE` and derives `is_effective` immediately from that
        status, the recorded window and the clock date."

        Design: Corner/entities/default_license_required_and_reserve_balance_when_optional_inputs_omitted
        """
        rule = validate_success(
            api.create_state_rate_rule(dict(TX_RULE, state_code="OK"), COMPLIANCE), 201
        )

        lic = validate_success(
            api.create_license(
                rule["id"],
                factories.license_payload(license_number="PFC-OK-001"),
                COMPLIANCE,
            ),
            201,
        )

        assert lic["status"] == "ACTIVE"
        assert lic["is_effective"] is True, (
            "2026-01-01 is on or before the 2026-08-01 clock date, which is on or "
            "before 2027-12-31"
        )

    def test_the_two_optional_policy_inputs_default_to_zero_and_false(self, api):
        """An attachment without the optional pair still lands fully populated.

        The PRD states: "Each attachment names the issuing carrier through
        `insurer_id` and supplies the carrier's `policy_number`, the agency-quoted
        `gross_premium_cents` (which must be strictly positive), the quoted
        `effective_date` and `expiration_date`, an optional `min_earned_days`
        defaulting to 0, and an optional `fully_earned` flag defaulting to false."

        Design: Corner/entities/default_license_required_and_reserve_balance_when_optional_inputs_omitted
        """
        ctx = fixtures.origination_context(api)
        payload = factories.financed_policy(ctx["insurer_id"], policy_number="SM-D-1")
        payload.pop("min_earned_days")
        payload.pop("fully_earned")
        bundle = fixtures.draft_agreement(api, ctx, policies=[])

        policy = validate_success(
            api.attach_policy(bundle["agreement_id"], payload, ANALYST_ORIGIN), 201
        )

        assert policy["min_earned_days"] == 0
        assert policy["fully_earned"] is False
        assert policy["status"] == "PENDING_VERIFICATION"
        assert policy["carried_over"] is False
        assert policy["endorsed_premium_cents"] == 0
        assert policy["financed_premium_cents"] == 600000, (
            "a successful attachment provisionally sets financed_premium_cents "
            "equal to gross_premium_cents"
        )

    def test_a_zero_seed_reserve_is_honoured_rather_than_replaced(self, api):
        """A zero initial reserve is a value, not a missing input.

        The PRD states: "On creation, `chargeback_reserve_balance_cents` is set to
        the supplied initial reserve, `outstanding_chargeback_cents` is set to 0,
        and `status` is set to `ACTIVE`."

        Design: Corner/entities/default_license_required_and_reserve_balance_when_optional_inputs_omitted
        """
        agent = validate_success(
            api.create_agent(
                factories.producer_agent(
                    agency_name="Gulf Coast Agency",
                    agent_commission_bps=1000,
                    chargeback_liability_cap_cents=400000,
                    initial_reserve_balance_cents=0,
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert agent["chargeback_reserve_balance_cents"] == 0
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["status"] == "ACTIVE"


class TestSystemFieldsAreServerStampedAndInputIsIgnored:
    """The client may ask for an id, a version and a counter; it gets none of
    them."""

    _SPOOFED = {
        "id": "client-chosen-id",
        "version": 99,
        "created_at": "1999-01-01T00:00:00Z",
        "active_agreement_count": 7,
    }

    def test_the_spoofed_body_is_accepted_rather_than_rejected(self, api):
        """Schema conformance is about the declared inputs, not about extra keys.

        The PRD states: "The body conforms to the operation's input schema: required
        fields present, types correct, enum values in range, cents fields
        non-negative integers, dates well-formed ISO 8601 calendar dates, `limit`
        within 1 to 100 and `offset` not negative — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/system_fields_on_state_rate_rule_creation_are_server_stamped_input_ignored
        """
        payload = dict(TX_RULE, state_code="NM", **self._SPOOFED)

        rule = validate_success(api.create_state_rate_rule(payload, COMPLIANCE), 201)

        assert rule["state_code"] == "NM"

    def test_the_identifier_and_the_version_are_minted_by_the_server(self, api):
        """A client-chosen id and version are discarded.

        The PRD states: "Every persisted resource carries a server-minted `id`,
        which is a UUID string with no type prefix of any kind, and a `created_at`
        timestamp in ISO 8601 UTC form with three fractional digits, taken from the
        logical clock at the moment the row is written."

        Design: Corner/entities/system_fields_on_state_rate_rule_creation_are_server_stamped_input_ignored
        """
        rule = validate_success(
            api.create_state_rate_rule(
                dict(TX_RULE, state_code="NM", **self._SPOOFED), COMPLIANCE
            ),
            201,
        )

        assert rule["id"] != "client-chosen-id"
        assert is_valid_uuid(rule["id"])
        assert rule["version"] == 1, "not the 99 the body asked for"

    def test_the_timestamps_come_from_the_logical_clock(self, api):
        """created_at is stamped from the clock and updated_at matches it.

        The PRD states: "`version` starts at 1 when the row is created and increases
        by exactly 1 on every mutation of that row; `updated_at` is refreshed to the
        logical-clock instant on the same mutation."

        Design: Corner/entities/system_fields_on_state_rate_rule_creation_are_server_stamped_input_ignored
        """
        rule = validate_success(
            api.create_state_rate_rule(
                dict(TX_RULE, state_code="NM", **self._SPOOFED), COMPLIANCE
            ),
            201,
        )

        assert rule["created_at"].startswith("2026-08-01"), (
            "the clock reads exactly 2026-08-01T00:00:00Z before it has ever been "
            "set, so the stamp is neither 1999 nor host wall-clock time"
        )
        assert is_iso8601_timestamp(rule["created_at"])
        assert rule["updated_at"] == rule["created_at"]

    def test_the_derived_counter_ignores_the_supplied_value(self, api):
        """active_agreement_count is computed from live agreements.

        The PRD states: "The new regime starts with `active_agreement_count` at
        zero."

        Design: Corner/entities/system_fields_on_state_rate_rule_creation_are_server_stamped_input_ignored
        """
        rule = validate_success(
            api.create_state_rate_rule(
                dict(TX_RULE, state_code="NM", **self._SPOOFED), COMPLIANCE
            ),
            201,
        )

        assert rule["active_agreement_count"] == 0, "not the 7 the body asked for"


class TestProducerAgentRetrievalReturnsStoredAndComputedCreditFields:
    """The reserve balance is seeded from a differently named input."""

    def _agent(self, api):
        return validate_success(
            api.create_agent(
                factories.producer_agent(
                    agency_name="Bluebonnet Insurance Services",
                    agent_commission_bps=1250,
                    chargeback_basis="RESERVE_CAPPED",
                    chargeback_liability_cap_cents=750000,
                    initial_reserve_balance_cents=250000,
                ),
                COMPLIANCE,
            ),
            201,
        )

    def test_the_read_returns_the_four_stored_configuration_fields(self, api):
        """Everything the compliance officer supplied comes back on the read.

        The PRD states: "Onboarding supplies `agency_name`, the `state_code` in
        which the agency is appointed, `agent_commission_bps` — the agency's
        commission as basis points of financed premium, at least 0 and at most 3000
        — the `chargeback_basis` that decides which chargeback variant applies to
        the agency's uncollected deficiencies, a non-negative
        `chargeback_liability_cap_cents` that is the lifetime ceiling on the
        agency's outstanding chargeback exposure, and a non-negative
        `initial_reserve_balance_cents` that seeds the agency's reserve."

        Design: Corner/entities/retrieval_of_producer_agent_returns_stored_and_computed_credit_fields
        """
        created = self._agent(api)

        agent = validate_success(api.get_agent(created["id"], ANALYST_ORIGIN), 200)

        assert_producer_agent(agent)
        assert agent["agency_name"] == "Bluebonnet Insurance Services"
        assert agent["state_code"] == "TX"
        assert agent["agent_commission_bps"] == 1250
        assert agent["chargeback_basis"] == "RESERVE_CAPPED"
        assert agent["chargeback_liability_cap_cents"] == 750000

    def test_the_reserve_balance_is_seeded_from_the_initial_reserve_input(self, api):
        """The differently named input reaches the entity field.

        The PRD states: "On creation, `chargeback_reserve_balance_cents` is set to
        the supplied initial reserve, `outstanding_chargeback_cents` is set to 0,
        and `status` is set to `ACTIVE`."

        Design: Corner/entities/retrieval_of_producer_agent_returns_stored_and_computed_credit_fields
        """
        created = self._agent(api)

        agent = validate_success(api.get_agent(created["id"], ANALYST_ORIGIN), 200)

        assert agent["chargeback_reserve_balance_cents"] == 250000, (
            "a read of 0 proves the seeding was dropped"
        )
        assert "initial_reserve_balance_cents" not in agent, (
            "the seed is an endpoint input, not a field of the agency record"
        )
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["status"] == "ACTIVE"
        assert agent["version"] == 1


class TestAgreementListingIsPaginatedAndFilterScoped:
    """total_count and has_more are computed over the filtered set, not the
    table."""

    def _four_drafts(self, api):
        """Three notes for insured Alpha and one for insured Bravo, in that order."""
        ctx = fixtures.origination_context(api)
        bravo = validate_success(
            api.create_insured(
                factories.insured(
                    legal_name="Insured Bravo LLC", email="ap@bravo.example"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ids = []
        for overrides in (
            {"down_payment_cents": 100000, "installment_count": 6},
            {"down_payment_cents": 150000, "installment_count": 8},
            {
                "down_payment_cents": 200000,
                "service_fee_cents": 1000,
                "first_installment_due_date": "2026-10-14",
            },
        ):
            row = validate_success(
                api.create_agreement(
                    factories.agreement(
                        ctx["insured_id"], ctx["agent_id"], ctx["rule_id"], **overrides
                    ),
                    ANALYST_ORIGIN,
                ),
                201,
            )
            ids.append(row["id"])
        bravo_row = validate_success(
            api.create_agreement(
                factories.agreement(bravo["id"], ctx["agent_id"], ctx["rule_id"]),
                ANALYST_ORIGIN,
            ),
            201,
        )
        return ctx, ids, bravo["id"], bravo_row["id"]

    def test_the_first_page_reports_the_filtered_total_and_more_to_come(self, api):
        """Two of three filtered rows, in created_at ascending order.

        The PRD states: "List responses populate four pagination fields inside
        `meta`: the `limit` and `offset` actually applied, `total_count` giving the
        number of rows matching the filters before paging, and `has_more`, which is
        true when rows remain beyond the current page."

        Design: Corner/entities/listing_agreements_paginated_and_filtered_by_insured
        """
        ctx, alpha_ids, _bravo_id, _bravo_row = self._four_drafts(api)

        rows, meta = validate_paginated(
            api.list_agreements(
                ANALYST_ORIGIN,
                {"insured_id": ctx["insured_id"], "limit": 2, "offset": 0},
            )
        )

        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert [row["id"] for row in rows] == alpha_ids[:2], (
            "results are ordered by created_at ascending, so the oldest row appears "
            "first"
        )

    def test_the_second_page_is_non_overlapping_and_ends_the_walk(self, api):
        """One row left, has_more false against the filtered count of three.

        The PRD states: "`offset` controls the starting position: it defaults to 0
        and may not be negative."

        Design: Corner/entities/listing_agreements_paginated_and_filtered_by_insured
        """
        ctx, alpha_ids, _bravo_id, _bravo_row = self._four_drafts(api)

        rows, meta = validate_paginated(
            api.list_agreements(
                ANALYST_ORIGIN,
                {"insured_id": ctx["insured_id"], "limit": 2, "offset": 2},
            )
        )

        assert meta["total_count"] == 3, "the filtered count is unchanged by paging"
        assert meta["limit"] == 2
        assert meta["offset"] == 2
        assert meta["has_more"] is False, (
            "computing has_more from the unfiltered count of four would wrongly "
            "promise a fourth row on this filter"
        )
        assert [row["id"] for row in rows] == [alpha_ids[2]]

    def test_the_defaults_apply_when_neither_parameter_is_supplied(self, api):
        """The other borrower's single note comes back under limit 10 offset 0.

        The PRD states: "`limit` controls page size: it defaults to 10, may be no
        smaller than 1 and no larger than 100."

        Design: Corner/entities/listing_agreements_paginated_and_filtered_by_insured
        """
        _ctx, _alpha_ids, bravo_id, bravo_row = self._four_drafts(api)

        rows, meta = validate_paginated(
            api.list_agreements(ANALYST_ORIGIN, {"insured_id": bravo_id})
        )

        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [bravo_row]

    def test_the_unfiltered_status_listing_proves_the_earlier_total_was_scoped(
        self, api
    ):
        """All four drafts are visible when the borrower filter is dropped.

        The PRD states: "an agreement can be listed by borrower, agency, state
        regime, restructure predecessor, financing status or collection stage".

        Design: Corner/entities/listing_agreements_paginated_and_filtered_by_insured
        """
        _ctx, alpha_ids, _bravo_id, bravo_row = self._four_drafts(api)

        rows, meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"status": "DRAFT"})
        )

        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert set(alpha_ids + [bravo_row]) == {row["id"] for row in rows}


class TestAgreementNotFoundOnUnknownIdentifier:
    """A well-formed identifier that matches no row is a 404, on reads and on
    writes alike."""

    _MISSING = NON_EXISTENT_UUID

    def _one_real_draft(self, api):
        ctx = fixtures.origination_context(api)
        return fixtures.draft_agreement(api, ctx, policies=[])

    def test_the_read_path_reports_the_agreement_as_missing(self, api):
        """A 404 with a message, not a 500 and not an empty 200.

        The PRD states: "an unknown `agreement_id` yields
        `ERR_AGREEMENT_NOT_FOUND`".

        Design: Corner/entities/agreement_not_found_on_unknown_identifier
        """
        self._one_real_draft(api)

        error = validate_error(
            api.get_agreement(self._MISSING, ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

        assert isinstance(error["message"], str) and error["message"].strip()

    def test_existence_is_resolved_before_the_state_machine(self, api):
        """Voiding a row that does not exist cannot be a state failure.

        The PRD states: "Every identifier in the path resolves, left to right —
        otherwise the corresponding not-found code from section 2.7."

        Design: Corner/entities/agreement_not_found_on_unknown_identifier
        """
        self._one_real_draft(api)

        validate_error(
            api.void_agreement(self._MISSING, ANALYST_ORIGIN, {"reason": "probe"}),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_a_sub_resource_list_on_a_missing_parent_is_a_404(self, api):
        """The installment list does not degrade to an empty page.

        The PRD states: "Because resolution is left to right, a licence read under a
        non-existent state regime reports the state regime as missing rather than the
        licence."

        Design: Corner/entities/agreement_not_found_on_unknown_identifier
        """
        self._one_real_draft(api)

        validate_error(
            api.list_installments(self._MISSING, ANALYST_ORIGIN, {"limit": 10}),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_the_real_agreement_is_untouched_by_the_three_probes(self, api):
        """The misses leave the collection exactly as it was.

        The PRD states: "Every one of these is an HTTP 404."

        Design: Corner/entities/agreement_not_found_on_unknown_identifier
        """
        bundle = self._one_real_draft(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        validate_error(
            api.get_agreement(self._MISSING, ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.void_agreement(self._MISSING, ANALYST_ORIGIN, {"reason": "probe"}),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "DRAFT"
        assert_no_common_field_drift(before, after)


class TestAgreementCreationMissingRequiredFirstInstallmentDueDate:
    """A missing value is a shape defect, not an out-of-window date."""

    def _ready_context(self, api):
        return fixtures.origination_context(api)

    def test_the_omission_is_a_shape_failure_and_not_a_window_failure(self, api):
        """Priority 7 fires before the first-due-date window is ever consulted.

        The PRD states: "The body conforms to the operation's input schema: required
        fields present, types correct, enum values in range, cents fields
        non-negative integers, dates well-formed ISO 8601 calendar dates, `limit`
        within 1 to 100 and `offset` not negative — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/agreement_creation_missing_required_first_installment_due_date
        """
        ctx = self._ready_context(api)
        payload = factories.agreement(ctx["insured_id"], ctx["agent_id"], ctx["rule_id"])
        payload.pop("first_installment_due_date")

        validate_error(
            api.create_agreement(payload, ANALYST_ORIGIN),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_the_same_rule_governs_a_different_endpoint(self, api):
        """A borrower without a mailing state is rejected the same way.

        The PRD states: "Borrowers are registered by a `FinanceAnalyst` with a
        non-empty `legal_name`, a `mailing_state_code` of exactly two uppercase
        letters used for addressing statutory notices, and an `email` that must
        contain an at-sign."

        Design: Corner/entities/agreement_creation_missing_required_first_installment_due_date
        """
        payload = factories.insured(legal_name="No State Inc", email="ap@nostate.example")
        payload.pop("mailing_state_code")

        validate_error(
            api.create_insured(payload, ANALYST_ORIGIN),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_the_rejected_request_creates_nothing(self, api):
        """No note exists for the borrower afterwards.

        The PRD states: "an agreement can be listed by borrower, agency, state
        regime, restructure predecessor, financing status or collection stage".

        Design: Corner/entities/agreement_creation_missing_required_first_installment_due_date
        """
        ctx = self._ready_context(api)
        payload = factories.agreement(ctx["insured_id"], ctx["agent_id"], ctx["rule_id"])
        payload.pop("first_installment_due_date")

        validate_error(
            api.create_agreement(payload, ANALYST_ORIGIN),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _rows, meta = validate_paginated(
            api.list_agreements(
                ANALYST_ORIGIN, {"insured_id": ctx["insured_id"], "limit": 10}
            )
        )
        assert meta["total_count"] == 0

    def test_no_counter_moved_on_the_failed_create(self, api):
        """The regime's live counter is still zero.

        The PRD states: "`active_agreement_count` is a derived counter, starting at
        0, holding the number of agreements referencing this regime whose financing
        status is either `PENDING_VERIFICATION` or `ACTIVE`."

        Design: Corner/entities/agreement_creation_missing_required_first_installment_due_date
        """
        ctx = self._ready_context(api)
        payload = factories.agreement(ctx["insured_id"], ctx["agent_id"], ctx["rule_id"])
        payload.pop("first_installment_due_date")

        validate_error(
            api.create_agreement(payload, ANALYST_ORIGIN),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        rule = validate_success(
            api.get_state_rate_rule(ctx["rule_id"], COMPLIANCE), 200
        )
        assert rule["active_agreement_count"] == 0


class TestComputedFieldsOnFinancedPolicyDeriveFromAttestations:
    """Two agreeing corrections, not the analyst's quote, decide what is
    financed."""

    def _submitted_600k_policy(self, api):
        ctx = fixtures.origination_context(api)
        return fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[factories.financed_policy(ctx["insurer_id"], policy_number="MC-CF-1")],
        )

    def _both_corrected(self, api):
        bundle = self._submitted_600k_policy(api)
        bundle["v1"] = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(550000, note="audited exposure schedule"),
                bundle["insurer_headers"],
            ),
            201,
        )
        bundle["mid"] = fixtures.read_policy(api, bundle["policy_id"])
        bundle["v2"] = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(550000),
                bundle["agent_headers"],
            ),
            201,
        )
        return bundle

    def test_the_computed_premium_fields_are_unset_at_attachment(self, api):
        """The attestation-derived fields are null until both sides speak.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(api, ctx, policies=[])

        policy = validate_success(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-CF-1"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        assert policy["verified_premium_cents"] is None
        assert policy["verified_effective_date"] is None
        assert policy["financed_premium_cents"] == 600000, (
            "the provisional value at attachment is the quote itself, and the "
            "attestation cycle is what replaces it"
        )

    def test_the_first_attestation_derives_its_party_and_comparison_fields(self, api):
        """The carrier's correction, not the quote, becomes its effective premium.

        The PRD states: "Two derived comparison fields are then stamped: on
        `CONFIRMED`, `effective_premium_cents` takes the policy's quoted
        `gross_premium_cents` and `effective_date_asserted` takes the policy's quoted
        `effective_date`; on `CORRECTED`, they take `corrected_premium_cents` and
        `corrected_effective_date`; on `REJECTED`, both remain null."

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        bundle = self._both_corrected(api)

        assert bundle["v1"]["party"] == "INSURER", (
            "the party is derived from the acting role rather than taken from input"
        )
        assert bundle["v1"]["party_user_id"] == bundle["insurer_id"]
        assert bundle["v1"]["effective_premium_cents"] == 550000
        assert bundle["v1"]["effective_date_asserted"] == "2026-09-01"
        assert bundle["v1"]["superseded"] is False

    def test_one_attestation_is_not_enough_to_stamp_the_policy(self, api):
        """The policy waits for the second live voice.

        The PRD states: "Nothing happens to the policy while only one side has
        spoken; the policy stays `PENDING_VERIFICATION` until both parties hold a
        non-superseded record."

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        bundle = self._both_corrected(api)

        assert bundle["mid"]["status"] == "PENDING_VERIFICATION"
        assert bundle["mid"]["verified_premium_cents"] is None

    def test_the_second_attestation_agrees_on_both_dimensions(self, api):
        """The agency files the same premium and the same date.

        The PRD states: "`party` becomes `INSURER` when the caller acts as `Insurer`
        and `PRODUCER_AGENT` when the caller acts as `ProducerAgent`".

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        bundle = self._both_corrected(api)

        assert bundle["v2"]["party"] == "PRODUCER_AGENT"
        assert bundle["v2"]["party_user_id"] == bundle["agent_id"]
        assert bundle["v2"]["effective_premium_cents"] == 550000
        assert bundle["v2"]["effective_date_asserted"] == "2026-09-01"

    def test_the_agreed_correction_is_what_gets_financed(self, api):
        """550000 is stamped, and the financed premium follows it.

        The PRD states: "In that case the agreed figures are stamped as
        `verified_premium_cents` and `verified_effective_date`,
        `financed_premium_cents` is recomputed as `verified_premium_cents` plus
        `endorsed_premium_cents`, the agreement's `verified_policy_count` increases by
        1, and the policy's `version` advances."

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        bundle = self._both_corrected(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "VERIFIED"
        assert policy["verified_premium_cents"] == 550000
        assert policy["verified_effective_date"] == "2026-09-01"
        assert policy["endorsed_premium_cents"] == 0
        assert policy["financed_premium_cents"] == 550000

    def test_the_quoted_input_survives_the_computation_unchanged(self, api):
        """The computed fields diverge from the quote instead of overwriting it.

        The PRD states: "the agency-quoted `gross_premium_cents` (which must be
        strictly positive)".

        Design: Corner/entities/computed_fields_on_financed_policy_derive_from_attestations
        """
        bundle = self._both_corrected(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["gross_premium_cents"] == 600000, (
            "the historical input is preserved verbatim"
        )
        assert policy["verified_premium_cents"] != policy["gross_premium_cents"]

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["policy_count"] == 1
        assert agreement["verified_policy_count"] == 1


class TestStateRateRuleTypeConstraintsAreEnforced:
    """Four different constraint kinds on one entity all collapse to one error
    code."""

    def test_an_out_of_enum_finance_charge_method_is_rejected(self, api):
        """DISCOUNT is not one of the two declared methods.

        The PRD states: "`finance_charge_method` is either `ADD_ON` or
        `SIMPLE_INTEREST` and decides how the finance charge and the installment
        amounts are computed."

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        validate_error(
            api.create_state_rate_rule(
                dict(TX_RULE, finance_charge_method="DISCOUNT"), COMPLIANCE
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_a_rate_one_past_the_ceiling_is_rejected(self, api):
        """3001 is one basis point past the declared maximum.

        The PRD states: "`max_annual_rate_bps` is the statutory ceiling on the annual
        finance-charge rate in basis points, at least 1 and at most 3000, and it binds
        absolutely: nothing in this platform, not even an approved exception, may price
        above it."

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        validate_error(
            api.create_state_rate_rule(
                dict(TX_RULE, max_annual_rate_bps=3001), COMPLIANCE
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_an_inverted_late_fee_band_is_rejected_as_a_cross_field_defect(self, api):
        """900 and 400 are each individually legal; only the pair is illegal.

        The PRD states: "`late_fee_max_cents` is the statutory ceiling and may not be
        smaller than `late_fee_min_cents`".

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        validate_error(
            api.create_state_rate_rule(
                dict(TX_RULE, late_fee_min_cents=900, late_fee_max_cents=400),
                COMPLIANCE,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_a_lowercase_state_code_is_not_auto_upcased(self, api):
        """The case of the code is part of its shape.

        The PRD states: "The regime is identified by `state_code`, which is exactly
        two uppercase letters and must be unique across all regimes — one rate regime
        per state."

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        validate_error(
            api.create_state_rate_rule(dict(TX_RULE, state_code="tx"), COMPLIANCE),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_the_inclusive_boundaries_are_accepted(self, api):
        """3000 exactly, and a band whose floor equals its ceiling.

        The PRD states: "`late_fee_min_cents` is the statutory floor applied to a
        computed fee and may not be negative".

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        rule = validate_success(
            api.create_state_rate_rule(
                dict(
                    TX_RULE,
                    max_annual_rate_bps=3000,
                    late_fee_min_cents=500,
                    late_fee_max_cents=500,
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert rule["max_annual_rate_bps"] == 3000, "the ceiling is inclusive"
        assert rule["late_fee_min_cents"] == rule["late_fee_max_cents"] == 500, (
            "equality satisfies may-not-be-smaller-than"
        )

    def test_none_of_the_rejections_created_a_row(self, api):
        """Only the boundary create survives, and it owns the TX slot.

        The PRD states: "A second attempt to register the same `state_code` is refused
        with `ERR_DUPLICATE_STATE_RULE` (HTTP 409), because a state has exactly one
        rate regime."

        Design: Corner/entities/state_rate_rule_type_constraints_invalid_enum_and_out_of_range_rejected
        """
        for bad in (
            dict(TX_RULE, finance_charge_method="DISCOUNT"),
            dict(TX_RULE, max_annual_rate_bps=3001),
            dict(TX_RULE, late_fee_min_cents=900, late_fee_max_cents=400),
            dict(TX_RULE, state_code="tx"),
        ):
            validate_error(
                api.create_state_rate_rule(bad, COMPLIANCE),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )

        validate_success(api.create_state_rate_rule(dict(TX_RULE), COMPLIANCE), 201)
        validate_error(
            api.create_state_rate_rule(dict(TX_RULE), COMPLIANCE),
            ApiErrorId.DUPLICATE_STATE_RULE.value,
            409,
        )


class TestPremiumVerificationIsImmutableWithNoCommonFields:
    """Corrections are made by superseding, never by editing."""

    def _disputed(self, api):
        """A 600000 policy where the carrier confirmed and the agency corrected."""
        ctx = fixtures.origination_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IM-1")
            ],
        )
        bundle["v1"] = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            201,
        )
        bundle["v2"] = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(
                    590000, note="endorsement not yet booked"
                ),
                bundle["agent_headers"],
            ),
            201,
        )
        return bundle

    def test_the_disagreement_is_recorded_on_both_rows_and_on_the_policy(self, api):
        """Two live voices, two different premiums, one dispute reason.

        The PRD states: "Then `dispute_reason` is stamped by a strict precedence:
        `PARTY_REJECTED` when either record is a repudiation; otherwise
        `PREMIUM_MISMATCH` when the asserted premiums differ; otherwise
        `EFFECTIVE_DATE_MISMATCH`."

        Design: Corner/entities/premium_verification_is_immutable_with_no_common_fields
        """
        bundle = self._disputed(api)

        assert bundle["v1"]["effective_premium_cents"] == 600000
        assert bundle["v2"]["effective_premium_cents"] == 590000
        assert bundle["v2"]["note"] == "endorsement not yet booked"

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "DISPUTED"
        assert policy["dispute_reason"] == "PREMIUM_MISMATCH"

    def test_no_attestation_carries_a_version_or_an_updated_at(self, api):
        """The audit record has no common fields to mutate.

        The PRD states: "A `PremiumVerification` — the attestation a carrier or an
        agency files against a policy — is an immutable audit record: it carries only
        `id` and `created_at`. It has no `updated_at` field and no `version` field, and
        neither appears in its response payload."

        Design: Corner/entities/premium_verification_is_immutable_with_no_common_fields
        """
        bundle = self._disputed(api)

        rows, meta = validate_paginated(
            api.list_verifications(bundle["policy_id"], COMPLIANCE, {"limit": 50})
        )

        assert meta["total_count"] == 2
        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
            assert is_valid_uuid(row["id"])
            assert is_iso8601_timestamp(row["created_at"])
            assert row["superseded"] is False, "both rows are live before the reopen"

    def test_the_reopen_retires_the_rows_rather_than_deleting_them(self, api):
        """Two rows still listed, both flipped to superseded.

        The PRD states: "Reopening verification on a `DISPUTED` policy — permitted
        only while the parent agreement is in `DRAFT` or `PENDING_VERIFICATION` — sets
        `superseded` to true on every existing attestation of that policy, clears
        `dispute_reason`, moves the policy `DISPUTED` → `PENDING_VERIFICATION` and
        advances its `version`."

        Design: Corner/entities/premium_verification_is_immutable_with_no_common_fields
        """
        bundle = self._disputed(api)

        reopened = validate_success(
            api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200
        )

        assert reopened["status"] == "PENDING_VERIFICATION"
        assert reopened["dispute_reason"] is None

        rows, meta = validate_paginated(
            api.list_verifications(bundle["policy_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 2
        assert all(row["superseded"] is True for row in rows)

    def test_the_retired_content_is_exactly_what_was_filed(self, api):
        """Superseding does not rewrite a decision, a premium or a note.

        The PRD states: "Superseded records are never deleted: listing the
        attestations of a policy returns every record ever filed, superseded ones
        included, and the list may be narrowed with a `party` filter."

        Design: Corner/entities/premium_verification_is_immutable_with_no_common_fields
        """
        bundle = self._disputed(api)
        validate_success(api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200)

        rows, _meta = validate_paginated(
            api.list_verifications(bundle["policy_id"], COMPLIANCE, {"limit": 50})
        )
        by_party = {row["party"]: row for row in rows}

        assert by_party["INSURER"]["decision"] == "CONFIRMED"
        assert by_party["INSURER"]["effective_premium_cents"] == 600000
        assert by_party["PRODUCER_AGENT"]["decision"] == "CORRECTED"
        assert by_party["PRODUCER_AGENT"]["effective_premium_cents"] == 590000
        assert by_party["PRODUCER_AGENT"]["note"] == "endorsement not yet booked"

    def test_superseded_rows_stay_listable_and_filterable(self, api):
        """The party filter still finds the retired carrier record.

        The PRD states: "the list may be narrowed with a `party` filter."

        Design: Corner/entities/premium_verification_is_immutable_with_no_common_fields
        """
        bundle = self._disputed(api)
        validate_success(api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200)

        rows, meta = validate_paginated(
            api.list_verifications(
                bundle["policy_id"], COMPLIANCE, {"party": "INSURER", "limit": 50}
            )
        )

        assert meta["total_count"] == 1, (
            "retired records are not hidden from the filtered listing"
        )
        assert rows[0]["party"] == "INSURER"
        assert rows[0]["superseded"] is True


class TestFinancedPolicyUnderUnknownAgreementNotFound:
    """The nested parent resolves before the body foreign key."""

    _MISSING_AGREEMENT = "00000000-0000-4000-8000-0000000009aa"
    _MISSING_INSURER = "00000000-0000-4000-8000-0000000009bb"

    def _draft_without_policies(self, api):
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(api, ctx, policies=[])
        assert bundle["agreement"]["policy_count"] == 0
        return bundle

    def test_the_nested_parent_is_resolved_before_the_body(self, api):
        """A valid carrier in the body does not rescue an unknown note in the path.

        The PRD states: "Identifiers in a request path are resolved strictly left to
        right, and the leftmost segment that fails to resolve decides the error."

        Design: Corner/entities/financed_policy_under_unknown_agreement_not_found
        """
        bundle = self._draft_without_policies(api)

        validate_error(
            api.attach_policy(
                self._MISSING_AGREEMENT,
                factories.financed_policy(bundle["insurer_id"], policy_number="MC-PR-1"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_a_dangling_body_foreign_key_is_its_own_integrity_failure(self, api):
        """A real note plus an unknown carrier is a 404, not a 422.

        The PRD states: "An unresolvable borrower yields `ERR_INSURED_NOT_FOUND`, an
        unresolvable agency `ERR_AGENT_NOT_FOUND`, an unresolvable state regime
        `ERR_STATE_RULE_NOT_FOUND` and an unresolvable carrier
        `ERR_INSURER_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/financed_policy_under_unknown_agreement_not_found
        """
        bundle = self._draft_without_policies(api)

        validate_error(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(
                    self._MISSING_INSURER, policy_number="MC-PR-1"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURER_NOT_FOUND.value,
            404,
        )

    def test_neither_rejection_moved_the_policy_count(self, api):
        """No child row and no counter movement on the parent.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/entities/financed_policy_under_unknown_agreement_not_found
        """
        bundle = self._draft_without_policies(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        validate_error(
            api.attach_policy(
                self._MISSING_AGREEMENT,
                factories.financed_policy(bundle["insurer_id"], policy_number="MC-PR-1"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(
                    self._MISSING_INSURER, policy_number="MC-PR-1"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURER_NOT_FOUND.value,
            404,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["policy_count"] == 0
        assert_no_common_field_drift(before, after)

    def test_both_references_valid_lands_the_child_with_both_keys(self, api):
        """One key comes from the path and the other from the body.

        The PRD states: "Each attachment names the issuing carrier through
        `insurer_id` and supplies the carrier's `policy_number`, the agency-quoted
        `gross_premium_cents` (which must be strictly positive), the quoted
        `effective_date` and `expiration_date`, an optional `min_earned_days`
        defaulting to 0, and an optional `fully_earned` flag defaulting to false."

        Design: Corner/entities/financed_policy_under_unknown_agreement_not_found
        """
        bundle = self._draft_without_policies(api)

        policy = validate_success(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(bundle["insurer_id"], policy_number="MC-PR-1"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        assert policy["agreement_id"] == bundle["agreement_id"]
        assert policy["insurer_id"] == bundle["insurer_id"]

    def test_the_child_is_reverse_reachable_from_its_parent_key(self, api):
        """Listing policies by agreement finds exactly the one attachment.

        The PRD states: "Every foreign key in the model is reverse-reachable: an
        agreement can be listed by borrower, agency, state regime, restructure
        predecessor, financing status or collection stage; policies by agreement,
        carrier or status; carrier cancellation requests by agreement, policy or
        status; chargebacks by agency, agreement or status."

        Design: Corner/entities/financed_policy_under_unknown_agreement_not_found
        """
        bundle = self._draft_without_policies(api)
        policy = validate_success(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(bundle["insurer_id"], policy_number="MC-PR-1"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_policies(
                ANALYST_ORIGIN, {"agreement_id": bundle["agreement_id"], "limit": 50}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [policy["id"]]


class TestAgreementCreationWithUnknownSiblingReferencesRejected:
    """Three sibling foreign keys, three distinct 404 codes, one declared
    order."""

    _MISSING_INSURED = "00000000-0000-4000-8000-0000000009c1"
    _MISSING_AGENT = "00000000-0000-4000-8000-0000000009c2"
    _MISSING_RULE = "00000000-0000-4000-8000-0000000009c3"

    def test_an_unresolvable_borrower_is_named_specifically(self, api):
        """The borrower reference gets its own error code.

        The PRD states: "An unresolvable borrower yields `ERR_INSURED_NOT_FOUND`, an
        unresolvable agency `ERR_AGENT_NOT_FOUND`, an unresolvable state regime
        `ERR_STATE_RULE_NOT_FOUND` and an unresolvable carrier
        `ERR_INSURER_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/agreement_creation_with_unknown_state_rule_and_agent_rejected
        """
        ctx = fixtures.origination_context(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    self._MISSING_INSURED, ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURED_NOT_FOUND.value,
            404,
        )

    def test_an_unresolvable_agency_is_not_folded_into_a_shared_code(self, api):
        """The agency reference gets its own error code.

        The PRD states: "Every foreign key in the body resolves, in declared order —
        otherwise the corresponding not-found code."

        Design: Corner/entities/agreement_creation_with_unknown_state_rule_and_agent_rejected
        """
        ctx = fixtures.origination_context(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], self._MISSING_AGENT, ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGENT_NOT_FOUND.value,
            404,
        )

    def test_an_unresolvable_state_regime_is_named_specifically(self, api):
        """The regime reference gets its own error code.

        The PRD states: "A request naming a state rate regime that does not exist
        fails with `ERR_STATE_RULE_NOT_FOUND`".

        Design: Corner/entities/agreement_creation_with_unknown_state_rule_and_agent_rejected
        """
        ctx = fixtures.origination_context(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], self._MISSING_RULE
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.STATE_RULE_NOT_FOUND.value,
            404,
        )

    def test_all_three_dangling_resolves_in_the_declared_order(self, api):
        """The borrower is checked first, so the borrower is what is reported.

        The PRD states: "Foreign keys supplied in a request body are resolved in the
        order in which they are declared for that operation, which for agreement
        creation and policy attachment means `insured_id`, then `producer_agent_id`,
        then `state_rule_id`, then `insurer_id`."

        Design: Corner/entities/agreement_creation_with_unknown_state_rule_and_agent_rejected
        """
        fixtures.origination_context(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    self._MISSING_INSURED, self._MISSING_AGENT, self._MISSING_RULE
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURED_NOT_FOUND.value,
            404,
        )

    def test_four_rejections_produced_zero_writes(self, api):
        """No note under the regime and no movement of its counter.

        The PRD states: "`active_agreement_count` is a derived counter, starting at
        0, holding the number of agreements referencing this regime whose financing
        status is either `PENDING_VERIFICATION` or `ACTIVE`."

        Design: Corner/entities/agreement_creation_with_unknown_state_rule_and_agent_rejected
        """
        ctx = fixtures.origination_context(api)
        for payload, error_id in (
            (
                factories.agreement(
                    self._MISSING_INSURED, ctx["agent_id"], ctx["rule_id"]
                ),
                ApiErrorId.INSURED_NOT_FOUND.value,
            ),
            (
                factories.agreement(
                    ctx["insured_id"], self._MISSING_AGENT, ctx["rule_id"]
                ),
                ApiErrorId.AGENT_NOT_FOUND.value,
            ),
            (
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], self._MISSING_RULE
                ),
                ApiErrorId.STATE_RULE_NOT_FOUND.value,
            ),
            (
                factories.agreement(
                    self._MISSING_INSURED, self._MISSING_AGENT, self._MISSING_RULE
                ),
                ApiErrorId.INSURED_NOT_FOUND.value,
            ),
        ):
            validate_error(api.create_agreement(payload, ANALYST_ORIGIN), error_id, 404)

        _rows, meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"state_rule_id": ctx["rule_id"], "limit": 50})
        )
        assert meta["total_count"] == 0

        rule = validate_success(api.get_state_rate_rule(ctx["rule_id"], COMPLIANCE), 200)
        assert rule["active_agreement_count"] == 0
