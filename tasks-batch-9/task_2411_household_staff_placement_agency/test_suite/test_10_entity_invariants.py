"""The shape of a freshly written row.

Creation responses are pinned field by field — the server-owned lifecycle
values, the declared defaults, the counters that start at zero and the figures
the server computes rather than echoes — alongside the refusals that keep a
malformed or dangling row out of the store in the first place.
"""
from test_helpers import (
    BASE_SCENARIO,
    BILLING,
    CASE_OPENER,
    CONSULTANT,
    MILESTONE_WEIGHTS_BPS,
    NON_EXISTENT_UUID,
    PRINCIPAL,
    RECORDER,
    api_client,
    assert_common_fields,
    assert_no_mutation_fields,
    create_candidate_payload,
    create_client_payload,
    create_household,
    create_payroll_handoff_payload,
    create_reference_check_payload,
    create_requisition_payload,
    extend_offer,
    is_valid_uuid,
    ledger_adjustment_payload,
    read_candidate,
    read_client,
    record_reference,
    register_candidate,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

BECKFORD = {
    "household_name": "Beckford Row",
    "primary_contact_email": "ops@beckford.example",
    "region_code": "CA",
}


class TestHouseholdRowShape:
    def test_01_a_new_household_is_a_prospect_with_an_unsigned_agreement(self):
        """Every server-owned field of a brand-new household is pinned.

        PRD §3.1: "The new household begins life with `status` `PROSPECT`,
        `confidentiality_agreement_status` `UNSIGNED`, a null `signatory_name`, a
        null `countersigned_at`, `outstanding_balance_cents` of 0,
        `placement_count` of 0, a null `non_solicitation_expires_on` and `version`
        1."

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/client_creation_returns_a_prospect_with_an_unsigned_agreement
        """
        setup_scenario(stage="clock")

        response = api_client.create_client(create_client_payload(), PRINCIPAL)
        data = validate_success(response, 201)
        assert data["household_name"] == BASE_SCENARIO["HOUSEHOLD_NAME"]
        assert data["primary_contact_email"] == BASE_SCENARIO["CONTACT_EMAIL"]
        assert data["region_code"] == BASE_SCENARIO["REGION_CODE"]
        assert data["status"] == "PROSPECT"
        assert data["confidentiality_agreement_status"] == "UNSIGNED"
        assert data["signatory_name"] is None
        assert data["countersigned_at"] is None
        assert data["outstanding_balance_cents"] == 0
        assert data["placement_count"] == 0
        assert data["non_solicitation_expires_on"] is None
        assert data["version"] == 1

        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta["api_request_timestamp"], str)

    def test_02_the_stored_household_reads_back_identically(self):
        """The read-back proves the row was stored rather than echoed.

        PRD §2.4: "Every stored row is addressed by an `id` that the server mints
        as a UUID."

        Design: Corner/entities/client_retrieval_returns_the_stored_household
        """
        setup_scenario(stage="clock")
        created = create_household()
        assert is_valid_uuid(created["id"])

        stored = validate_success(api_client.get_client(created["id"], CONSULTANT))
        assert stored["id"] == created["id"]
        assert stored["household_name"] == BASE_SCENARIO["HOUSEHOLD_NAME"]
        assert stored["region_code"] == BASE_SCENARIO["REGION_CODE"]
        assert stored["status"] == "PROSPECT"
        assert stored["confidentiality_agreement_status"] == "UNSIGNED"
        assert stored["outstanding_balance_cents"] == 0
        assert stored["placement_count"] == 0
        assert stored["version"] == 1
        assert_common_fields(stored)

    def test_03_the_household_listing_carries_all_four_pagination_fields(self):
        """A page smaller than the result set pins has_more on both pages.

        PRD §2.3: "Successful list responses carry `limit`, `offset`,
        `total_count` and `has_more` inside `meta`, where `total_count` is the
        number of rows matching the filters before pagination is applied and
        `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/client_listing_returns_the_declared_pagination_envelope
        """
        setup_scenario(stage="clock")
        first = create_household()
        second = create_household(**BECKFORD)

        rows, meta = validate_paginated(
            api_client.list_clients(PRINCIPAL, {"limit": 1, "offset": 0})
        )
        assert len(rows) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        next_rows, next_meta = validate_paginated(
            api_client.list_clients(PRINCIPAL, {"limit": 1, "offset": 1})
        )
        assert len(next_rows) == 1
        assert next_meta["offset"] == 1
        assert next_meta["total_count"] == 2
        assert next_meta["has_more"] is False
        assert {rows[0]["id"], next_rows[0]["id"]} == {first["id"], second["id"]}

    def test_04_an_unknown_household_id_is_the_household_specific_not_found(self):
        """A well-formed but unknown uuid is 404, not an empty 200.

        PRD §2.5: "The not-found error is selected by the entity the failing
        segment addresses: `ERR_CLIENT_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`,
        `ERR_REQUISITION_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`,
        `ERR_REFERENCE_CHECK_NOT_FOUND`,
        `ERR_BACKGROUND_VERIFICATION_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`,
        `ERR_ACCOMMODATION_TERM_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
        `ERR_FEE_MILESTONE_NOT_FOUND`, `ERR_REPLACEMENT_CLAIM_NOT_FOUND`,
        `ERR_PAYROLL_HANDOFF_NOT_FOUND` or
        `ERR_NON_SOLICITATION_CASE_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/unknown_client_id_returns_client_not_found
        """
        setup_scenario(stage="clock")

        response = api_client.get_client(NON_EXISTENT_UUID, PRINCIPAL)
        validate_error(response, "ERR_CLIENT_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"

    def test_05_a_household_without_a_region_code_is_refused(self):
        """One of the three required inputs is missing, so nothing is stored.

        PRD §2.11: "A field declared required by the endpoint that is absent or
        null yields `ERR_INVALID_REQUEST`; this same error also covers a string
        outside its declared length bounds and an email-shaped field that does not
        contain an `@` character."

        Design: Corner/entities/client_missing_required_region_code_is_rejected
        """
        setup_scenario(stage="clock")
        payload = create_client_payload(
            household_name="Carraway Hall",
            primary_contact_email="ops@carraway.example",
        )
        payload.pop("region_code")

        validate_error(
            api_client.create_client(payload, PRINCIPAL), "ERR_INVALID_REQUEST", 400
        )

        rows, meta = validate_paginated(api_client.list_clients(PRINCIPAL))
        assert rows == []
        assert meta["total_count"] == 0


class TestDeclaredDefaults:
    def test_06_a_new_requisition_defaults_live_in_and_leaves_the_fee_snapshot_null(self):
        """live_in_required defaults to false and all four snapshot fields wait.

        PRD §3.1: "A successfully opened requisition sits in `status` `DRAFT` with
        `scoping_round` 0, `active_trial_count` 0, a null
        `resolved_fee_schedule_id`, `fee_percent_bps`, `guarantee_window_days` and
        `provisional_fee_cents`, `created_by_user_id` stamped from the acting
        `X-User-ID`, and `version` 1."

        Design: Corner/entities/requisition_defaults_leave_live_in_required_false_and_the_fee_snapshot_null
        """
        scenario = setup_scenario(stage="onboarded")
        payload = create_requisition_payload(scenario["client"]["id"])
        assert "live_in_required" not in payload
        assert "scope_note" not in payload

        data = validate_success(
            api_client.create_requisition(payload, CONSULTANT), 201
        )
        assert data["live_in_required"] is False
        assert data["scope_note"] is None
        assert data["status"] == "DRAFT"
        assert data["scoping_round"] == 0
        assert data["active_trial_count"] == 0
        assert data["resolved_fee_schedule_id"] is None
        assert data["fee_percent_bps"] is None
        assert data["guarantee_window_days"] is None
        assert data["provisional_fee_cents"] is None
        assert data["version"] == 1

    def test_07_a_new_candidate_defaults_live_in_willing_and_zeroes_every_counter(self):
        """Omitting live_in_willing yields false; the counters start at 0, not null.

        PRD §3.3: "A fresh candidate begins at `vetting_status` `UNVETTED` and
        `availability_status` `AVAILABLE`, with `cooling_off_until` null,
        `verified_reference_count`, `reference_coverage_months`,
        `longest_contiguous_months`, `screening_score` and `placement_ready_score`
        all 0, and `version` 1."

        Design: Corner/entities/candidate_defaults_leave_live_in_willing_false_and_every_score_at_zero
        """
        setup_scenario(stage="clock")
        payload = create_candidate_payload(
            full_name="R. Okoye",
            contact_email="rokoye@mail.example",
            primary_role_type="CHAUFFEUR",
            years_experience=4,
        )
        payload.pop("live_in_willing")

        data = validate_success(api_client.create_candidate(payload, RECORDER), 201)
        assert data["live_in_willing"] is False
        assert data["vetting_status"] == "UNVETTED"
        assert data["availability_status"] == "AVAILABLE"
        assert data["cooling_off_until"] is None
        assert data["verified_reference_count"] == 0
        assert data["reference_coverage_months"] == 0
        assert data["longest_contiguous_months"] == 0
        assert data["screening_score"] == 0
        assert data["placement_ready_score"] == 0
        assert data["version"] == 1

    def test_08_a_new_payroll_handoff_defaults_its_ein_status_to_not_applied(self):
        """The default is exactly the value that later blocks attestation.

        PRD §3.7: "A `ComplianceOfficer` prepares the handoff under the placement,
        naming the `provider_name` of the payroll bureau and the
        `guidance_packet_version` of the household-employer guidance being issued,
        and optionally an opening `ein_status`; the row is created with `status`
        `PREPARED`, `ein_status` defaulting to `NOT_APPLIED`, and null
        `attested_by_name` and `attested_at`."

        Design: Corner/entities/payroll_handoff_defaults_its_ein_status_to_not_applied
        """
        scenario = setup_scenario(stage="placement_active")
        payload = create_payroll_handoff_payload(
            provider_name="Household Payroll Partners",
            guidance_packet_version="HP-2026.2",
        )
        assert "ein_status" not in payload

        data = validate_success(
            api_client.create_payroll_handoff(
                scenario["placement"]["id"], payload, CASE_OPENER
            ),
            201,
        )
        assert data["ein_status"] == "NOT_APPLIED"
        assert data["status"] == "PREPARED"
        assert data["attested_by_name"] is None
        assert data["attested_at"] is None
        assert data["version"] == 1


class TestServerComputedFields:
    def test_09_the_offer_sums_the_four_components_and_copies_the_snapshot(self):
        """The package total is computed; the band is copied, not re-resolved.

        PRD §3.6: "`actual_first_year_compensation_cents` is not supplied: it is
        computed as the exact sum of those four components and stored on the row."

        PRD §3.6: "Second, the new placement is created with `placement_status`
        `PENDING_ACCEPTANCE`, `billing_status` `UNBILLED`, `fee_variant`
        `PROVISIONAL`, `client_id` taken from the requisition,
        `snapshot_fee_schedule_id`, `fee_percent_bps` and `guarantee_window_days`
        copied from the requisition's resolved snapshot, `guarantee_expires_on`
        computed as `start_date` plus `guarantee_window_days` days, a null
        `separation_date`, a null `void_reason`, `created_by_user_id` stamped from
        `X-User-ID`, and `fee_cents` computed by the `PROVISIONAL` variant
        described in §3.2."

        Design: Corner/entities/placement_computes_its_actual_compensation_and_copies_the_fee_snapshot
        """
        scenario = setup_scenario(stage="term_accepted")
        placement = extend_offer(scenario["requisition"], scenario["candidate"])

        assert placement["actual_first_year_compensation_cents"] == (
            BASE_SCENARIO["BASE_SALARY_CENTS"]
            + BASE_SCENARIO["GUARANTEED_BONUS_CENTS"]
            + BASE_SCENARIO["ACCOMMODATION_IMPUTED_CENTS"]
            + BASE_SCENARIO["OVERTIME_ALLOWANCE_CENTS"]
        )
        assert placement["actual_first_year_compensation_cents"] == 10_000_000
        assert placement["fee_percent_bps"] == 2000
        assert placement["guarantee_window_days"] == 90
        assert placement["fee_cents"] == 2_000_000
        assert placement["fee_variant"] == "PROVISIONAL"
        assert placement["snapshot_fee_schedule_id"] == scenario["fee_schedule"]["id"]
        assert placement["client_id"] == scenario["client"]["id"]
        assert placement["placement_status"] == "PENDING_ACCEPTANCE"
        assert placement["billing_status"] == "UNBILLED"
        assert placement["separation_date"] is None
        assert placement["void_reason"] is None
        assert placement["version"] == 1

    def test_10_the_candidate_id_and_created_at_are_stamped_by_the_server(self):
        """created_at is the logical clock instant, and version opens at 1.

        PRD §2.4: "`version` is an integer that begins at 1 when the row is
        created and increments by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."

        Design: Corner/entities/candidate_system_fields_are_server_generated_and_the_version_starts_at_one
        """
        setup_scenario(stage="clock", clock="2026-08-05T12:00:00Z")
        payload = create_candidate_payload()
        assert "id" not in payload
        assert "created_at" not in payload

        data = validate_success(api_client.create_candidate(payload, RECORDER), 201)
        assert is_valid_uuid(data["id"])
        assert data["created_at"].startswith("2026-08-05T12:00:00")
        assert data["version"] == 1
        assert_common_fields(data)

    def test_11_the_three_milestone_rows_are_created_by_the_offer_itself(self):
        """The caller supplies no milestone rows, yet three appear in order.

        PRD §3.7: "Every placement carries exactly three `FeeMilestone` rows,
        created when the offer is extended, each identified by its `placement_id`,
        its `milestone_type` and its `sequence_no`: `sequence_no` 1 is the
        `ENGAGEMENT` milestone weighted at 3000 basis points, `sequence_no` 2 is
        `TRIAL_CLEARED` weighted at 3000, and `sequence_no` 3 is `START_DATE`
        weighted at 4000 — thirty, thirty and forty percent of the fee."

        Design: Corner/entities/the_three_fee_milestone_rows_are_created_by_the_placement_itself
        """
        scenario = setup_scenario(stage="placement_pending")
        placement = scenario["placement"]

        rows, meta = validate_paginated(
            api_client.list_fee_milestones(placement["id"], BILLING)
        )
        assert meta["total_count"] == 3
        assert [row["sequence_no"] for row in rows] == [1, 2, 3]
        assert [row["milestone_type"] for row in rows] == [
            "ENGAGEMENT",
            "TRIAL_CLEARED",
            "START_DATE",
        ]
        assert [row["weight_bps"] for row in rows] == [
            MILESTONE_WEIGHTS_BPS["ENGAGEMENT"],
            MILESTONE_WEIGHTS_BPS["TRIAL_CLEARED"],
            MILESTONE_WEIGHTS_BPS["START_DATE"],
        ]
        assert [row["amount_cents"] for row in rows] == [600_000, 600_000, 800_000]
        for row in rows:
            assert row["invoice_status"] == "PENDING"
            assert row["invoiced_on"] is None
            assert row["due_date"] is None
            assert row["paid_on"] is None
        assert sum(row["amount_cents"] for row in rows) == placement["fee_cents"]
        assert placement["fee_cents"] == 2_000_000


class TestAppendOnlyLedgerRow:
    def test_12_a_ledger_row_carries_its_running_balance_and_no_version(self):
        """The row is stamped once at append time and exposes no version field.

        PRD §2.12: "A `LedgerEntry` names its household through `client_id`,
        occupies a 1-based `sequence_no` that increments monotonically within that
        household, and records a `signed_amount_cents` movement, a human-readable
        `memo`, and a `balance_after_cents` snapshot stamped once at append time."

        PRD §2.4: "Ledger rows are immutable once appended, so they carry only
        `id` and `created_at`: a ledger row has **no** `updated_at` field and
        **no** `version` field, and neither appears in its response payload."

        Design: Corner/entities/ledger_entries_are_append_only_and_carry_no_version_field
        """
        scenario = setup_scenario(stage="onboarded")

        data = validate_success(
            api_client.create_ledger_adjustment(
                scenario["client"]["id"],
                ledger_adjustment_payload(
                    250_000, memo="Goodwill credit agreed with the household."
                ),
                BILLING,
            ),
            201,
        )
        assert data["client_id"] == scenario["client"]["id"]
        assert data["sequence_no"] == 1
        assert data["entry_type"] == "MANUAL_ADJUSTMENT"
        assert data["signed_amount_cents"] == 250_000
        assert data["related_ref_type"] == "NONE"
        assert data["related_ref_id"] is None
        assert data["balance_after_cents"] == 250_000
        assert_no_mutation_fields(data)
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 250_000


class TestDeclaredTypeConstraints:
    def test_13_a_region_code_outside_the_declared_five_is_refused(self):
        """The enum step is reached only once the required fields are present.

        PRD §3.1: "The payload carries the `household_name` that will appear on
        the engagement letter (a required string of 1 to 120 characters), the
        `primary_contact_email` of the household's point of contact (required, and
        it must contain an `@` character), and a `region_code` drawn from `NY`,
        `CA`, `FL`, `TX` and `MA` — the region is what later selects the
        state-specific payroll and tax guidance packet."

        PRD §2.11: "Then an enum-typed value outside its declared set yields
        `ERR_INVALID_ENUM`."

        Design: Corner/entities/unknown_region_code_enum_is_rejected
        """
        setup_scenario(stage="clock")

        response = api_client.create_client(
            create_client_payload(
                household_name="Dunmore Court",
                primary_contact_email="ops@dunmore.example",
                region_code="XX",
            ),
            PRINCIPAL,
        )
        validate_error(response, "ERR_INVALID_ENUM", 400)
        assert response.json()["response_type"] == "error"

        rows, _ = validate_paginated(api_client.list_clients(PRINCIPAL))
        assert rows == []

    def test_14_years_experience_of_sixty_one_is_out_of_band_while_sixty_is_not(self):
        """61 is one past the declared ceiling, so the bound is inclusive.

        PRD §2.11: "Then a numeric field outside its accepted band yields
        `ERR_INVALID_RANGE`; the accepted bands are: no `_cents` field may be
        negative, `years_experience` must be 0 through 60, `weekly_hours` must be
        1 through 80, `days_off_per_week` must be 0 through 7, `fee_percent_bps`
        must be 1 through 10000, `guarantee_window_days` must be 1 through 365,
        `scope_items` must be non-empty, `limit` must be 1 through 200 and
        `offset` must not be negative."

        PRD §3.3: "A fresh candidate begins at `vetting_status` `UNVETTED` and
        `availability_status` `AVAILABLE`, with `cooling_off_until` null,
        `verified_reference_count`, `reference_coverage_months`,
        `longest_contiguous_months`, `screening_score` and
        `placement_ready_score` all 0, and `version` 1."

        Design: Corner/entities/years_experience_above_sixty_is_rejected
        """
        setup_scenario(stage="clock")
        payload = create_candidate_payload(
            full_name="S. Halloran",
            contact_email="shalloran@mail.example",
            primary_role_type="CHEF",
            years_experience=61,
        )

        validate_error(
            api_client.create_candidate(payload, RECORDER), "ERR_INVALID_RANGE", 400
        )

        payload["years_experience"] = 60
        data = validate_success(api_client.create_candidate(payload, RECORDER), 201)
        assert data["years_experience"] == 60
        assert data["screening_score"] == 0


class TestParentResolutionAndOwnership:
    def test_15_an_unknown_client_id_in_the_body_is_a_household_not_found(self):
        """The parent is resolved from the body, so no dangling row is written.

        PRD §2.5: "The same catalogue is used when a foreign-key identifier
        supplied in a request *body* fails to resolve — a bad `candidate_id` in a
        trial booking is `ERR_CANDIDATE_NOT_FOUND`, a bad `source_placement_id` on
        an enforcement case is `ERR_PLACEMENT_NOT_FOUND`."

        Design: Corner/entities/requisition_for_an_unknown_client_id_returns_not_found
        """
        setup_scenario(stage="clock")

        validate_error(
            api_client.create_requisition(
                create_requisition_payload(NON_EXISTENT_UUID), CONSULTANT
            ),
            "ERR_CLIENT_NOT_FOUND",
            404,
        )

        rows, meta = validate_paginated(api_client.list_requisitions(CONSULTANT))
        assert rows == []
        assert meta["total_count"] == 0

    def test_16_a_prior_reference_owned_by_another_candidate_is_a_mismatch(self):
        """Both ids resolve, so only the ownership check can refuse the write.

        PRD §2.5: "Resolving to a row of the right entity is not sufficient; the
        rows must also belong together. When a chained reference's
        `prior_reference_id` belongs to a different candidate, when the candidate
        named in an offer has no trial engagement on the named requisition, or
        when an enforcement case's `source_placement_id` names a placement whose
        `candidate_id` differs from the case's `candidate_id`, the request is
        refused with `ERR_ENTITY_RELATIONSHIP_MISMATCH` (HTTP 409)."

        Design: Corner/entities/prior_reference_from_another_candidate_is_rejected_as_a_relationship_mismatch
        """
        setup_scenario(stage="clock")
        first = register_candidate()
        borrowed = record_reference(first)
        second = register_candidate(
            full_name="T. Vance",
            contact_email="tvance@mail.example",
            years_experience=6,
        )

        payload = create_reference_check_payload(
            principal_employer_name="Harrow Lodge",
            employment_start_month="2023-01",
            employment_end_month="2023-12",
            contact_email="harrow@mail.example",
        )
        payload["prior_reference_id"] = borrowed["id"]
        validate_error(
            api_client.create_reference_check(second["id"], payload, RECORDER),
            "ERR_ENTITY_RELATIONSHIP_MISMATCH",
            409,
        )

        after = read_candidate(second)
        assert after["vetting_status"] == "UNVETTED"
        assert after["verified_reference_count"] == 0
        rows, _ = validate_paginated(
            api_client.list_candidate_reference_checks(second["id"], RECORDER)
        )
        assert rows == []
