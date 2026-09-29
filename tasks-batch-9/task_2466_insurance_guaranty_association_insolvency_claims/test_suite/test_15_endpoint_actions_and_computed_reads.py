"""What each endpoint returns and writes: the worksheet, the ledger, the batch and the links."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_covered_claim,
    assert_member_insurer,
    assert_other_insurance,
    assert_settlement_worksheet,
    assert_transferred_policy,
    assert_vendor_assignment,
    convert_poc_transfer,
    engage_vendor,
    estate_remittance_payload,
    get_success_data,
    poc_claim_record,
    poc_policy_record,
    present_claim,
    read_claim,
    read_insolvency,
    register_member_insurer,
    register_other_insurance,
    screen_claim,
    setup_claim_with_resolved_other_insurance,
    setup_delivered_poc_batch,
    setup_recommended_claim,
    setup_screened_claim,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
OFFICER = TEST_USERS["claims_committee_officer_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
BIG_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 4_500_000,
}
SMALL_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
NORTHERN_SHIELD = {
    "carrier_name": "Northern Shield Indemnity",
    "policy_number": "NS-77",
    "coverage_type": "PRIMARY",
    "stated_limit_cents": 1_500_000,
}
KESTREL_ADJUSTER = {
    "vendor_type": "ADJUSTER",
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
ALDER_COUNSEL = {
    "vendor_type": "DEFENSE_COUNSEL",
    "vendor_name": "Alder and Vance LLP",
    "settlement_authority_cents": 0,
    "hourly_rate_cents": 32_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}


class TestComputedReads:
    """The worksheet lays the computation out term by term and writes nothing."""

    def test_the_worksheet_exposes_every_term_of_the_payable_computation(self):
        """It returns `claim_id`, the governing `cap_order_mode`, `covered_basis_cents`,
        `attachment_point_cents`, `covered_layer_cents`, `other_insurance_recoverable_cents`, the
        line's `statutory_deductible_cents` and `per_claim_cap_cents`, `remaining_aggregate_cents` for
        the policy, `net_payable_cents`, `alt_net_payable_cents`, `variant_delta_cents` as the
        difference between the two payable variants, and `cap_binding`.

        Design: Corner/endpoints/settlement_worksheet_read_matches_the_stored_claim_figures
        """
        env = setup_claim_with_resolved_other_insurance(
            recovered_cents=1_200_000,
            claim_overrides=dict(BIG_LOSS_CLAIM),
            layer_overrides=dict(NORTHERN_SHIELD),
            policy_overrides=dict(LIVE_TERM),
        )
        before = read_claim(env["claim"]["id"])

        worksheet = get_success_data(
            api_client.get_settlement_worksheet(before["id"], OFFICER), 200
        )

        assert_settlement_worksheet(worksheet)
        assert worksheet["claim_id"] == before["id"]
        assert worksheet["cap_order_mode"] == "OFFSET_THEN_CAP", worksheet["cap_order_mode"]
        assert worksheet["covered_layer_cents"] == 4_500_000, worksheet["covered_layer_cents"]
        assert worksheet["other_insurance_recoverable_cents"] == 1_200_000, (
            worksheet["other_insurance_recoverable_cents"]
        )
        assert worksheet["statutory_deductible_cents"] == 10_000, (
            worksheet["statutory_deductible_cents"]
        )
        assert worksheet["per_claim_cap_cents"] == 3_000_000, worksheet["per_claim_cap_cents"]
        assert worksheet["remaining_aggregate_cents"] == 5_000_000, (
            worksheet["remaining_aggregate_cents"]
        )
        assert worksheet["net_payable_cents"] == 3_000_000, worksheet["net_payable_cents"]
        assert worksheet["alt_net_payable_cents"] == 1_790_000, (
            "capping first and offsetting afterwards yields the lower figure, got "
            f"{worksheet['alt_net_payable_cents']}"
        )
        assert abs(worksheet["variant_delta_cents"]) == 1_210_000, (
            worksheet["variant_delta_cents"]
        )
        assert worksheet["cap_binding"] == "PER_CLAIM", worksheet["cap_binding"]

        after = read_claim(before["id"])
        assert after["status"] == "SCREENED_ELIGIBLE", after["status"]
        assert after["version"] == before["version"], (
            f"a computed read must not touch the claim, got version {after['version']}"
        )


class TestLedgerAndBatchActions:
    """Cash in, and the receiver's raw records turned into rows."""

    def test_a_remittance_is_the_only_way_cash_enters_the_estate(self):
        """A `ReceiverLiaison` records each early-access payment or dividend by supplying
        `amount_cents` and a `remittance_ref`; the amount is added to `estate_remitted_cents`,
        `estate_undistributed_cents` is recomputed from the closed-ledger identity rather than
        incremented, and the insolvency file's `version` is incremented by one — which is precisely
        why a distribution run planned against a pre-remittance view of the file will be turned away
        as stale.

        Design: Corner/endpoints/estate_remittance_action_updates_the_ledger
        """
        env = setup_screened_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        before = read_insolvency(env["insolvency"]["id"])
        assert before["estate_remitted_cents"] == 0, before["estate_remitted_cents"]

        ledger = get_success_data(
            api_client.create_estate_remittance(
                before["id"], estate_remittance_payload(3_200_000, "EA-1"), RECEIVER
            ),
            200,
        )

        assert ledger["estate_remitted_cents"] == 3_200_000, ledger["estate_remitted_cents"]
        assert ledger["estate_undistributed_cents"] == 3_200_000, (
            ledger["estate_undistributed_cents"]
        )
        assert ledger["estate_distributed_cents"] == 0, ledger["estate_distributed_cents"]
        assert ledger["estate_returned_cents"] == 0, ledger["estate_returned_cents"]
        assert ledger["distribution_sequence"] == 0, (
            f"remitting cash runs no waterfall, got {ledger['distribution_sequence']}"
        )
        assert ledger["version"] == before["version"] + 1, (
            f"the remittance bumps the file's version, got {ledger['version']} after "
            f"{before['version']}"
        )

    def test_conversion_skips_the_bad_records_and_keeps_the_good_one(self):
        """When at least one element passes and at least one fails, the batch moves
        `RECEIVED → PARTIALLY_CONVERTED`: rows are created only for the passing elements,
        `converted_count` and `rejected_count` are set to their respective counts, one string per
        failing element is appended to `rejection_reasons` in `records` order, and `policy_count` is
        again recomputed.

        Each entry in `rejection_reasons` is formatted as the element's zero-based index inside
        `records`, then a colon, then the reason code — so the third element of the array failing on an
        unknown line reads exactly `2:UNKNOWN_LINE_OF_BUSINESS`.

        Design: Corner/endpoints/poc_transfer_conversion_reports_partial_success_per_record
        """
        env = setup_delivered_poc_batch(
            records=[
                poc_policy_record(
                    policy_number="PA-3001",
                    policyholder_name="Ada Renner",
                    policyholder_net_worth_cents=50_000_000,
                ),
                poc_policy_record(
                    policy_number="HO-3002",
                    line_of_business="HOMEOWNERS",
                    policyholder_name="Boris Ilic",
                    policyholder_net_worth_cents=40_000_000,
                    annual_premium_cents=900_000,
                ),
                poc_claim_record(
                    policy_number="PA-9999",
                    claimant_name="Cora Diaz",
                    gross_loss_cents=900_000,
                ),
            ],
            receiver_batch_ref="RB-002",
        )
        assert env["transfer"]["record_count"] == 3, env["transfer"]["record_count"]

        converted = convert_poc_transfer(env)

        assert converted["status"] == "PARTIALLY_CONVERTED", converted["status"]
        assert converted["converted_count"] == 1, converted["converted_count"]
        assert converted["rejected_count"] == 2, converted["rejected_count"]
        assert converted["rejection_reasons"] == [
            "1:UNKNOWN_LINE_OF_BUSINESS",
            "2:NO_MATCHING_POLICY",
        ], (
            "one zero-based entry per failing element, in records order, got "
            f"{converted['rejection_reasons']}"
        )

        policies, _ = validate_paginated(
            api_client.list_policies(RECEIVER, {"source_transfer_id": converted["id"]})
        )
        assert len(policies) == 1, f"only the good element is materialised, got {len(policies)}"
        assert_transferred_policy(policies[0])
        assert policies[0]["policy_number"] == "PA-3001", policies[0]["policy_number"]
        assert policies[0]["status"] == "IMPORTED", policies[0]["status"]

        claims, _ = validate_paginated(
            api_client.list_claims(ANALYST, {"source_transfer_id": converted["id"]})
        )
        assert claims == [], "the orphan claim element mints nothing"
        assert read_insolvency(env["insolvency"]["id"])["policy_count"] == 1


class TestConditionalAndLinkingWrites:
    """One endpoint whose side effect depends on the payload, and one that stamps a parent."""

    def test_only_the_adjuster_engagement_advances_the_claim(self):
        """Engaging an `ADJUSTER` on a claim that is in `SCREENED_ELIGIBLE` additionally advances the
        claim `SCREENED_ELIGIBLE → ADJUSTING`; an engagement created while the claim is already in
        `ADJUSTING` or `RECOMMENDED`, or an engagement of type `DEFENSE_COUNSEL` at any point, leaves
        the claim's own status where it is. Every engagement create increments the claim's `version` by
        one.

        Design: Corner/endpoints/only_an_adjuster_engagement_moves_the_claim_into_adjusting
        """
        env = setup_screened_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        screened_version = env["claim"]["version"]

        counsel = engage_vendor(env, **ALDER_COUNSEL)
        assert_vendor_assignment(counsel)
        after_counsel = read_claim(env["claim"]["id"])
        assert after_counsel["status"] == "SCREENED_ELIGIBLE", (
            f"defense counsel does not move the claim, got {after_counsel['status']}"
        )
        assert after_counsel["version"] == screened_version + 1, (
            f"but the engagement create still bumps the version, got {after_counsel['version']}"
        )

        adjuster = engage_vendor(env, **KESTREL_ADJUSTER)
        after_adjuster = read_claim(env["claim"]["id"])
        assert after_adjuster["status"] == "ADJUSTING", (
            f"only the adjuster engagement opens adjustment, got {after_adjuster['status']}"
        )
        assert after_adjuster["version"] == screened_version + 2, after_adjuster["version"]

        rows, _ = validate_paginated(
            api_client.list_vendor_assignments(after_adjuster["id"], ADMIN)
        )
        assert len(rows) == 2, f"the two vendor types coexist, got {len(rows)} engagements"
        assert {row["id"] for row in rows} == {counsel["id"], adjuster["id"]}
        for row in rows:
            assert row["status"] == "ASSIGNED", (
                f"neither vendor type supersedes the other, got {row['status']}"
            )

    def test_a_registered_layer_belongs_to_the_claim_named_in_the_path(self):
        """The payload carries `carrier_name`, the other carrier's `policy_number`, a `coverage_type`
        that is one of `PRIMARY`, `EXCESS` or `UMBRELLA`, a `stated_limit_cents` greater than 0, and
        `expected_claim_version`. The layer is created in `UNEXHAUSTED` with `recovered_cents` at 0 and
        with the next `sequence` value within that claim, and the claim's `version` is incremented by
        one.

        Design: Corner/endpoints/registering_an_other_insurance_layer_links_it_to_the_named_claim
        """
        env = setup_screened_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        first_claim = env["claim"]

        present_claim(
            env,
            claim_number="C-2",
            claimant_name="Cora Diaz",
            loss_date="2026-01-20",
            gross_loss_cents=900_000,
        )
        screen_claim(env)
        sibling_claim = env["claim"]

        env["claim"] = first_claim
        layer = register_other_insurance(
            env, **dict(NORTHERN_SHIELD, coverage_type="EXCESS")
        )

        assert_other_insurance(layer)
        assert layer["claim_id"] == first_claim["id"], (
            "the nested create resolves its parent from the path"
        )
        assert layer["sequence"] == 1, layer["sequence"]
        assert layer["status"] == "UNEXHAUSTED", layer["status"]
        assert layer["recovered_cents"] == 0, layer["recovered_cents"]

        owned, _ = validate_paginated(
            api_client.list_other_insurance(first_claim["id"], ANALYST)
        )
        assert len(owned) == 1, f"the layer is listed under its own claim, got {len(owned)}"
        assert owned[0]["id"] == layer["id"]

        elsewhere, _ = validate_paginated(
            api_client.list_other_insurance(sibling_claim["id"], ANALYST)
        )
        assert elsewhere == [], "and under no sibling claim"

    def test_an_amendment_writes_only_the_fields_it_supplies(self):
        """A member row may later be amended to change any of `direct_written_premium_cents`,
        `annual_cap_rate_bps` or `account_status`, each field optional in the amendment payload, and
        every amendment increments the member row's `version` by one. `account_status` is one of
        `ACTIVE`, `IMPAIRED` or `WITHDRAWN`, and only `ACTIVE` rows will ever enter an allocation pool.

        Design: Corner/endpoints/patching_a_member_insurer_updates_the_premium_base_and_bumps_the_version
        """
        member = register_member_insurer(
            naic_code="20001",
            insurer_name="Huron Standard Insurance",
            direct_written_premium_cents=10_000_000,
        )
        assert member["version"] == 1, member["version"]
        assert member["account_status"] == "ACTIVE", member["account_status"]

        amended = get_success_data(
            api_client.update_member_insurer(
                member["id"],
                {"direct_written_premium_cents": 20_000_000, "account_status": "IMPAIRED"},
                ADMIN,
            ),
            200,
        )

        assert_member_insurer(amended)
        assert amended["direct_written_premium_cents"] == 20_000_000, (
            amended["direct_written_premium_cents"]
        )
        assert amended["account_status"] == "IMPAIRED", amended["account_status"]
        assert amended["annual_cap_rate_bps"] == 200, (
            "the field the amendment did not name keeps its default, got "
            f"{amended['annual_cap_rate_bps']}"
        )
        assert amended["version"] == 2, amended["version"]

        reread = get_success_data(api_client.get_member_insurer(member["id"], ADMIN))
        assert reread["direct_written_premium_cents"] == 20_000_000
        assert reread["account_status"] == "IMPAIRED"


class TestImmediateConsistency:
    """The response that causes a cascade already shows it."""

    def test_the_approval_response_itself_carries_the_recomputed_figures(self):
        """Consistency in this system is immediate. Every cascade described in this document — a parent
        counter recomputation, a child state change, a version bump — is visible in the same response
        that caused it and to any subsequent read, with no deferred or eventual settling. There is no
        background reconciliation job: if an operation is specified to update six fields across three
        entities, all six are correct the instant the operation returns 200 or 201.

        Design: Corner/consistency_model/the_approval_response_already_shows_the_recomputed_payable_and_reserve
        """
        env = setup_recommended_claim(
            recommended_amount_cents=890_000,
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides={
                "vendor_name": "Kestrel Claims Services",
                "settlement_authority_cents": 900_000,
                "hourly_rate_cents": 18_000,
                "engagement_start": "2026-08-01",
                "engagement_end": "2026-08-31",
            },
            policy_overrides=dict(LIVE_TERM),
        )
        assert env["claim"]["status"] == "RECOMMENDED", env["claim"]["status"]
        assert read_insolvency(env["insolvency"]["id"])["reserved_claim_cents"] == 0

        approved = get_success_data(
            api_client.approve_claim(env["claim"]["id"], OFFICER), 200
        )

        assert_covered_claim(approved)
        assert approved["status"] == "APPROVED", approved["status"]
        assert approved["net_payable_cents"] == 890_000, (
            "the re-run payable is already in the approval response, got "
            f"{approved['net_payable_cents']}"
        )
        assert approved["approved_by_user_id"] is not None

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 890_000, (
            "and the parent counter is correct on the very next read, got "
            f"{insolvency['reserved_claim_cents']}"
        )

        claim = read_claim(approved["id"])
        assert claim["status"] == "APPROVED", claim["status"]
        assert claim["net_payable_cents"] == 890_000, claim["net_payable_cents"]
