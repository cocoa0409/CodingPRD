"""Version tokens, inclusive triggers and reads that never lag a write.

Two guards protect a caller from destroying a picture it has not observed; a
third layer scores solicitation activity on inclusive comparisons; and every
derived field a write touches is already correct on the very next read.
"""

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    api_client,
    approve_filing,
    create_financial_statement,
    create_organization,
    create_solicitation_activity,
    decide_extension,
    extension_request_payload,
    financial_statement_payload,
    list_financial_statements,
    open_filing,
    read_organization,
    read_registration,
    request_extension,
    seed_state_profile,
    setup_submitted_filing,
    solicitation_activity_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleOrganizationToken:
    """The token spent on the first statement cannot pay for the second."""

    def test_reusing_the_organization_version_on_a_second_statement_is_refused(self):
        """PRD §2.10: "`POST /financial-statements` requires a non-optional
        `expected_organization_version` field carrying the `version` of the target
        `Organization` as the client last observed it." PRD §2.5: "`version`, an integer
        that starts at 1 on creation and increments by exactly one on every mutation of
        that row."

        Design: Corner/cross_cutting_layers/stale_organization_version_blocks_a_second_statement
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        assert organization["version"] == 1, (
            f"A freshly created charity is at version 1, got {organization['version']}"
        )
        first = validate_success(
            api_client.create_financial_statement(
                financial_statement_payload(
                    organization["id"],
                    organization["version"],
                    fiscal_year=2025,
                    total_revenue_cents=18_000_000,
                    contributions_cents=15_000_000,
                    program_expense_cents=12_000_000,
                    fundraising_expense_cents=3_000_000,
                    management_expense_cents=1_500_000,
                ),
                COMPLIANCE,
            ),
            201,
        )

        # PRD §2.5: the charity's `version` "increments by exactly one on every
        # mutation of that row", and PRD §3.1 makes an amendment such a mutation, so
        # the amendment spends the token the client is still holding.
        amended = validate_success(
            api_client.update_organization(
                organization["id"],
                {"legal_name": "Harbor Light Foundation Inc"},
                COMPLIANCE,
            )
        )
        assert amended["version"] == 2, (
            f"The amendment is the second mutation, got {amended['version']}"
        )

        response = api_client.create_financial_statement(
            financial_statement_payload(organization["id"], organization["version"]),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_STALE_ORGANIZATION_VERSION.value)
        assert read_organization(organization["id"])["version"] == 2, (
            "The refused create left the charity's version exactly where the "
            "amendment put it"
        )
        statements = list_financial_statements(organization["id"])
        assert len(statements) == 1, (
            f"The refused create filed nothing, got {len(statements)}"
        )
        assert statements[0]["id"] == first["id"], (
            "Only the 2025 statement exists"
        )
        assert statements[0]["statement_status"] == "CURRENT", (
            f"And it is still current, got {statements[0]['statement_status']}"
        )


class TestStaleRegistrationToken:
    """The supersede is silent, so the token is the only guard there is."""

    def test_reusing_the_filing_version_on_a_second_extension_request_is_refused(self):
        """PRD §2.10: "Creating the request drives every earlier extension request on
        that filing to `SUPERSEDED`, which can silently discard an already-granted
        extension and reset the filing's deadline, so the server compares
        `expected_registration_version` against the registration's current `version` and
        rejects any mismatch with `ERR_STALE_REGISTRATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_registration_version_blocks_the_superseding_extension
        """
        seed_state_profile(
            "CA",
            assurance_basis="GROSS_REVENUE",
            extension_allowed=True,
            extension_max_days=90,
        )
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")
        assert filing["version"] == 1, (
            f"A newly opened filing is at version 1, got {filing['version']}"
        )
        first = request_extension(filing["id"], filing["version"], "STATE_HARDSHIP", 45)
        # PRD §3.5: on a grant "the linked filing has its `extended_due_date` set to
        # `renewal_due_date` plus `granted_days`, its `effective_due_date` recomputed,
        # and its `version` incremented" — the very comfortable deadline a second,
        # superseding request would silently destroy.
        validate_success(decide_extension(first["id"], "GRANT"))

        response = api_client.create_extension_request(
            extension_request_payload(
                filing["id"], filing["version"], "IRS_990_EXTENSION", 60
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value)
        reread = read_registration(filing["id"])
        assert reread["version"] == 2, (
            f"The grant advanced the filing, got {reread['version']}"
        )
        assert reread["extended_due_date"] is not None, (
            "The refused create did not destroy the granted deadline, got "
            f"{reread['extended_due_date']}"
        )
        assert reread["effective_due_date"] == reread["extended_due_date"], (
            "effective_due_date is extended_due_date while an extension stands, got "
            f"{reread['effective_due_date']}"
        )
        requests, meta = validate_paginated(
            api_client.list_registration_extension_requests(filing["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 1, (
            f"The refused create recorded nothing, got {meta['total_count']}"
        )
        assert requests[0]["id"] == first["id"], "The standing request survives"
        assert requests[0]["status"] == "GRANTED", (
            f"And it was not superseded, got {requests[0]['status']}"
        )


class TestOrganizationVersionAdvancesOnChildWritesToo:
    """An amendment and a restatement both spend the token."""

    def test_the_version_moves_for_an_amendment_and_again_for_a_statement(self):
        """PRD §2.5: "`version`, an integer that starts at 1 on creation and increments
        by exactly one on every mutation of that row — including mutations the server
        performs on its own initiative while cascading a change that originated on some
        other resource." PRD §3.2 names one such cascading mutation on a child write:
        "The restating write also increments `Organization.version` by one."

        Design: Corner/cross_cutting_layers/organization_version_advances_on_every_write_that_touches_it
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()

        amended = validate_success(
            api_client.update_organization(
                organization["id"],
                {"legal_name": "Harbor Light Foundation Inc"},
                COMPLIANCE,
            )
        )
        original = validate_success(
            api_client.create_financial_statement(
                financial_statement_payload(organization["id"], amended["version"]),
                COMPLIANCE,
            ),
            201,
        )
        before_restatement = read_organization(organization["id"])["version"]
        statement = validate_success(
            api_client.create_financial_statement(
                financial_statement_payload(
                    organization["id"],
                    before_restatement,
                    total_revenue_cents=27_000_000,
                ),
                COMPLIANCE,
            ),
            201,
        )
        final = read_organization(organization["id"])

        assert organization["version"] == 1, (
            f"Creation lands at 1, got {organization['version']}"
        )
        assert amended["version"] == 2, (
            f"The amendment is the second mutation, got {amended['version']}"
        )
        assert final["version"] == before_restatement + 1, (
            "The restating write increments the charity's version by exactly one, "
            f"got {final['version']} from {before_restatement}"
        )
        assert final["legal_name"] == "Harbor Light Foundation Inc", (
            f"The amended name is what is read back, got {final['legal_name']}"
        )
        assert statement["statement_status"] == "CURRENT", (
            f"The statement is current, got {statement['statement_status']}"
        )
        superseded = [
            s for s in list_financial_statements(organization["id"])
            if s["id"] == original["id"]
        ]
        assert superseded and superseded[0]["statement_status"] == "SUPERSEDED", (
            "The restatement pushed the prior statement out of CURRENT, got "
            f"{superseded and superseded[0]['statement_status']}"
        )


class TestRegistrationTriggersAreInclusive:
    """One donor and one cent below fires nothing; landing on both fires all three."""

    def test_the_trigger_clauses_are_inclusive_and_reported_in_canonical_order(self):
        """PRD §3.1: "The first fires when `donor_count` is at least the state's
        `donor_count_trigger`, which defaults to 25 donors, and it contributes the reason
        `DONOR_COUNT`. The second fires when `contributions_cents` is at least the
        state's `contribution_trigger_cents`, which defaults to $25,000 — that is,
        2,500,000 cents — and contributes `CONTRIBUTION_TOTAL`. The third fires when the
        state's `online_presence_counts` flag is true (its default is false) and
        `channels` contains `WEB_TARGETED`, and contributes
        `TARGETED_ONLINE_PRESENCE`... All three comparisons are inclusive at the trigger
        value. `trigger_reasons` lists whichever clauses fired in the canonical order
        `DONOR_COUNT`, then `CONTRIBUTION_TOTAL`, then `TARGETED_ONLINE_PRESENCE`."

        Design: Corner/cross_cutting_layers/registration_triggers_are_inclusive_at_every_threshold
        """
        profile = seed_state_profile(
            "CA", assurance_basis="GROSS_REVENUE", online_presence_counts=True
        )
        organization = create_organization()

        under = create_solicitation_activity(
            organization["id"],
            "CA",
            donor_count=24,
            contributions_cents=2_499_999,
            channels=["MAIL"],
        )
        exactly_at = validate_success(
            api_client.create_solicitation_activity(
                solicitation_activity_payload(
                    organization["id"],
                    "CA",
                    donor_count=25,
                    contributions_cents=2_500_000,
                    channels=["MAIL", "WEB_TARGETED"],
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert profile["donor_count_trigger"] == 25, (
            f"The donor trigger defaults to 25, got {profile['donor_count_trigger']}"
        )
        assert profile["contribution_trigger_cents"] == 2_500_000, (
            "The contribution trigger defaults to 2,500,000 cents, got "
            f"{profile['contribution_trigger_cents']}"
        )
        assert under["triggers_registration"] is False, (
            "One donor and one cent short fires nothing, got "
            f"{under['triggers_registration']}"
        )
        assert under["trigger_reasons"] == [], (
            f"And names no reason, got {under['trigger_reasons']}"
        )
        assert exactly_at["triggers_registration"] is True, (
            "Landing exactly on both triggers fires, got "
            f"{exactly_at['triggers_registration']}"
        )
        assert exactly_at["trigger_reasons"] == [
            "DONOR_COUNT",
            "CONTRIBUTION_TOTAL",
            "TARGETED_ONLINE_PRESENCE",
        ], (
            "All three clauses in canonical order, got "
            f"{exactly_at['trigger_reasons']}"
        )


class TestApprovalIsVisibleEverywhereAtOnce:
    """The approval response, the charity's counters and the calendar all agree."""

    def test_the_reads_after_an_approval_already_show_every_recomputed_field(self):
        """PRD §3.4: "The transition then sets `registered_at` to the current logical
        clock, sets `review_status` to `ACCEPTED` on every document of the filing, and
        refreshes the organization's `registered_state_count` and `ceased_state_codes`."

        Design: Corner/consistency_model/approval_counters_are_readable_with_no_lag
        """
        ctx = setup_submitted_filing()

        approved = validate_success(approve_filing(ctx["registration"]["id"]))
        organization = read_organization(ctx["organization"]["id"])
        calendar = validate_success(
            api_client.get_compliance_calendar(ctx["organization"]["id"], COMPLIANCE)
        )
        documents, _meta = validate_paginated(
            api_client.list_registration_documents(
                COMPLIANCE,
                params={"registration_id": ctx["registration"]["id"], "limit": 100},
            )
        )

        assert approved["status"] == "REGISTERED", (
            f"The response itself already registers the filing, got {approved['status']}"
        )
        assert approved["registered_at"] == "2026-08-01T00:00:00.000Z", (
            f"Stamped at the logical clock, got {approved['registered_at']}"
        )
        assert organization["registered_state_count"] == 1, (
            "The counter is correct on the very next read, got "
            f"{organization['registered_state_count']}"
        )
        assert organization["filing_posture"] == "CURRENT", (
            f"And so is the posture, got {organization['filing_posture']}"
        )
        assert calendar["entries"][0]["status"] == "REGISTERED", (
            "The calendar entry shows the new status with no re-poll, got "
            f"{calendar['entries'][0]['status']}"
        )
        assert calendar["entries"][0]["effective_due_date"] == "2026-11-14T00:00:00.000Z", (
            "And the deadline it derives, got "
            f"{calendar['entries'][0]['effective_due_date']}"
        )
        assert {doc["review_status"] for doc in documents} == {"ACCEPTED"}, (
            "Every document of the filing reads as accepted, got "
            f"{[doc['review_status'] for doc in documents]}"
        )


class TestRestatementIsVisibleOnTheVeryNextRead:
    """Three rows the caller never named are already rewritten."""

    def test_a_restatement_knocks_the_submitted_filing_back_and_repoints_it_at_once(self):
        """PRD §3.2: "Every registration pointing at the superseded statement through
        `financial_statement_id` whose `status` is `DRAFT`, `SUBMITTED` or `DEFICIENT` is
        repointed to the new statement's identifier, has its
        `required_financial_attestation` re-derived against the new numbers, and has its
        `version` incremented. And where such a repointed registration was sitting in
        `SUBMITTED`, and its freshly re-derived attestation requirement now outranks the
        new statement's `assurance_level` on the ordered scale in which `NONE` is
        weakest, `REVIEW` sits above it and `AUDIT` is strongest, that registration is
        pushed back `SUBMITTED` → `DEFICIENT` with `deficiency_reasons` set to a
        single-element list holding `ASSURANCE_LEVEL_INSUFFICIENT` and
        `deficiency_round_count` incremented by one."

        Design: Corner/consistency_model/no_stale_read_survives_a_restatement
        """
        ctx = setup_submitted_filing()

        restatement = create_financial_statement(
            ctx["organization"],
            total_revenue_cents=250_000_000,
            contributions_cents=210_000_000,
            program_expense_cents=180_000_000,
            fundraising_expense_cents=40_000_000,
            management_expense_cents=20_000_000,
            assurance_level="REVIEW",
        )
        filing = read_registration(ctx["registration"]["id"])

        assert filing["status"] == "DEFICIENT", (
            "A review-level statement cannot carry an audit requirement, got "
            f"{filing['status']}"
        )
        assert filing["financial_statement_id"] == restatement["id"], (
            "The filing was repointed at the restatement, got "
            f"{filing['financial_statement_id']}"
        )
        assert filing["required_financial_attestation"] == "AUDIT", (
            "250,000,000 of gross revenue is above the audit threshold, got "
            f"{filing['required_financial_attestation']}"
        )
        assert filing["deficiency_reasons"] == ["ASSURANCE_LEVEL_INSUFFICIENT"], (
            f"The reason is recorded verbatim, got {filing['deficiency_reasons']}"
        )
        by_id = {
            row["id"]: row
            for row in list_financial_statements(ctx["organization"]["id"])
        }
        assert (
            by_id[ctx["financial_statement"]["id"]]["statement_status"] == "SUPERSEDED"
        ), "The predecessor reads as superseded immediately"
        assert by_id[restatement["id"]]["statement_status"] == "CURRENT", (
            "And the restatement as current, got "
            f"{by_id[restatement['id']]['statement_status']}"
        )
        assert by_id[restatement["id"]]["assurance_level"] == "REVIEW", (
            "The restatement's own assurance is unchanged by the cascade, got "
            f"{by_id[restatement['id']]['assurance_level']}"
        )
