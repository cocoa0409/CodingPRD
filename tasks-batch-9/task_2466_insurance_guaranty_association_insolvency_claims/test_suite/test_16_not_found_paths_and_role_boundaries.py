"""Who may act, whose row it is, and what a path that resolves to nothing reports."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_GENERIC_ID,
    api_client,
    assert_covered_claim,
    claim_payload,
    close_insolvency,
    engage_vendor,
    get_success_data,
    headers_without_role,
    list_member_assessments,
    policy_payload,
    present_claim,
    read_assessment,
    read_claim,
    read_insolvency,
    read_member_assessment,
    register_other_insurance,
    remit_estate_cash,
    screen_claim,
    setup_certified_assessment,
    setup_claim_under_adjustment,
    setup_recommended_claim,
    setup_screened_claim,
    setup_triggered_insolvency,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
SECOND_ANALYST = TEST_USERS["second_coverage_analyst_headers"]
ASSESSOR = TEST_USERS["assessment_officer_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
SMALL_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
KESTREL_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
BELLWETHER_ADJUSTER = {
    "vendor_name": "Bellwether Adjusting",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 15_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
TWO_MEMBERS = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
    },
    {
        "naic_code": "20002",
        "insurer_name": "Saginaw Casualty Group",
        "direct_written_premium_cents": 30_000_000,
    },
]


class TestPathsThatResolveToNothing:
    """Each collection answers for itself, and a nested id must belong to its parent."""

    def test_every_collection_reports_its_own_not_found_code(self):
        """Failures of the first identifier report the collection-specific not-found code:
        `ERR_INSOLVENCY_NOT_FOUND` for any path rooted at `/insolvencies/{id}`,
        `ERR_CLAIM_NOT_FOUND` for any path rooted at `/claims/{id}`, `ERR_POLICY_NOT_FOUND` for any
        path rooted at `/policies/{id}`, `ERR_TRANSFER_NOT_FOUND` for any path rooted at
        `/poc-transfers/{id}`, `ERR_ASSESSMENT_NOT_FOUND` for any path rooted at `/assessments/{id}`,
        `ERR_MEMBER_ASSESSMENT_NOT_FOUND` for any path rooted at `/member-assessments/{id}`, and
        `ERR_MEMBER_INSURER_NOT_FOUND` for `GET /member-insurers/{id}` and
        `PATCH /member-insurers/{id}`. All seven are HTTP 404.

        Design: Corner/errors/unknown_ids_on_every_top_level_read_return_their_own_not_found_error
        """
        validate_error(
            api_client.get_insolvency(UNKNOWN_GENERIC_ID, ADMIN),
            "ERR_INSOLVENCY_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_policy(UNKNOWN_GENERIC_ID, ADMIN), "ERR_POLICY_NOT_FOUND", 404
        )
        validate_error(
            api_client.get_poc_transfer(UNKNOWN_GENERIC_ID, ADMIN),
            "ERR_TRANSFER_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_assessment(UNKNOWN_GENERIC_ID, ASSESSOR),
            "ERR_ASSESSMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_member_assessment(UNKNOWN_GENERIC_ID, ASSESSOR),
            "ERR_MEMBER_ASSESSMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_member_insurer(UNKNOWN_GENERIC_ID, ADMIN),
            "ERR_MEMBER_INSURER_NOT_FOUND",
            404,
        )

    def test_a_layer_belonging_to_a_sibling_claim_is_not_found_under_this_one(self):
        """Nested paths are resolved strictly left to right. The first path identifier is looked up
        first, and only if it resolves does the server look up the nested child identifier; the child
        must in addition belong to the parent named earlier in the path.

        A nested child identifier that does not resolve to a row whose parent foreign key equals the
        first path identifier yields
        `ERR_CHILD_RESOURCE_NOT_FOUND` (HTTP 404); this applies to
        `PATCH /claims/{id}/other-insurance/{coverageId}`,
        `POST /claims/{id}/vendor-assignments/{assignmentId}/invoices` and
        `POST /claims/{id}/referrals/{referralId}/respond`.

        Design: Corner/errors/patching_a_coverage_id_from_another_claim_returns_child_resource_not_found
        """
        env = setup_screened_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        first_claim = env["claim"]
        own_layer = register_other_insurance(
            env,
            carrier_name="Northern Shield Indemnity",
            policy_number="NS-77",
            coverage_type="PRIMARY",
            stated_limit_cents=1_500_000,
        )

        present_claim(
            env,
            claim_number="C-2",
            claimant_name="Cora Diaz",
            loss_date="2026-01-20",
            gross_loss_cents=900_000,
        )
        screen_claim(env)
        sibling_claim = env["claim"]
        sibling_layer = register_other_insurance(
            env,
            carrier_name="Southbank Mutual",
            policy_number="SB-12",
            coverage_type="PRIMARY",
            stated_limit_cents=800_000,
        )
        assert sibling_layer["claim_id"] == sibling_claim["id"]

        validate_error(
            api_client.update_other_insurance(
                first_claim["id"], sibling_layer["id"], {"status": "PURSUING"}, ANALYST
            ),
            "ERR_CHILD_RESOURCE_NOT_FOUND",
            404,
        )

        own_rows, _ = validate_paginated(
            api_client.list_other_insurance(first_claim["id"], ANALYST)
        )
        assert len(own_rows) == 1, len(own_rows)
        assert own_rows[0]["id"] == own_layer["id"]
        assert own_rows[0]["status"] == "UNEXHAUSTED", (
            f"the addressed parent's own layer is untouched, got {own_rows[0]['status']}"
        )

        sibling_rows, _ = validate_paginated(
            api_client.list_other_insurance(sibling_claim["id"], ANALYST)
        )
        assert len(sibling_rows) == 1, len(sibling_rows)
        assert sibling_rows[0]["status"] == "UNEXHAUSTED", (
            "and the layer named in the path is not advanced either, got "
            f"{sibling_rows[0]['status']}"
        )


class TestClosureIsTerminalForTheWholeFile:
    """Once the residue has gone back to the receiver, nothing more may be booked."""

    def test_no_further_policy_may_be_keyed_into_a_closed_file(self):
        """The governing insolvency file's `status` is anything other than `CLOSED` →
        `ERR_INSOLVENCY_CLOSED` (HTTP 409), on `POST /policies`,
        `POST /insolvencies/{id}/poc-transfers`, `POST /poc-transfers/{id}/convert`,
        `POST /insolvencies/{id}/trigger` and `POST /assessments`; and, immediately after it, the
        triggering event runs only once, requiring `status` to be `DECLARED` →
        `ERR_INSOLVENCY_ALREADY_TRIGGERED` (HTTP 409), on `POST /insolvencies/{id}/trigger`.

        When both checks clear, the file moves `TRIGGERED → CLOSED`, the whole of
        `estate_undistributed_cents` is added into `estate_returned_cents` and
        `estate_undistributed_cents` is set to 0 — which preserves the closed-ledger identity exactly,
        since the cash has merely changed bucket — and the file's `version` is incremented by one.
        `CLOSED` is terminal.

        Design: Corner/errors/writes_against_a_closed_insolvency_return_insolvency_closed
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        remit_estate_cash(env["insolvency"]["id"], 400_000, "EA-1")
        closed = close_insolvency(env["insolvency"]["id"])
        assert closed["status"] == "CLOSED", closed["status"]

        validate_error(
            api_client.create_policy(
                policy_payload(
                    env["insolvency"]["id"],
                    policy_number="PA-1002",
                    policyholder_name="Boris Ilic",
                ),
                RECEIVER,
            ),
            "ERR_INSOLVENCY_CLOSED",
            409,
        )

        after = read_insolvency(env["insolvency"]["id"])
        assert after["status"] == "CLOSED", after["status"]
        assert after["estate_returned_cents"] == 400_000, (
            f"the residue went back to the receiver at closure, got "
            f"{after['estate_returned_cents']}"
        )
        assert after["estate_undistributed_cents"] == 0, after["estate_undistributed_cents"]
        assert after["policy_count"] == 1, (
            f"the refused write minted no policy, got {after['policy_count']}"
        )

        rows, _ = validate_paginated(
            api_client.list_policies(ADMIN, {"insolvency_id": env["insolvency"]["id"]})
        )
        assert len(rows) == 1, len(rows)
        assert rows[0]["policy_number"] == "PA-1001", rows[0]["policy_number"]


class TestRoleBoundaries:
    """An unknown caller, a wrong role, and two peer roles reaching past their own rows."""

    def test_a_call_with_no_declared_role_never_reaches_the_endpoint(self):
        """Authentication — both headers present and `X-User-Role` a declared role →
        `ERR_UNAUTHENTICATED`, on every endpoint.

        Design: Corner/rbac/a_request_without_a_role_header_cannot_reach_any_endpoint
        """
        anonymous = headers_without_role()

        validate_error(
            api_client.create_insolvency(
                {
                    "insurer_name": "Great Lakes Mutual Casualty",
                    "naic_code": "10001",
                    "domiciliary_state_code": "MI",
                    "liquidation_order_date": "2026-03-01",
                },
                anonymous,
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        validate_error(
            api_client.create_coverage_profile(
                {
                    "line_of_business": "PERSONAL_AUTO",
                    "per_claim_cap_cents": 3_000_000,
                    "per_policy_aggregate_cap_cents": 5_000_000,
                    "unearned_premium_cap_cents": 1_000_000,
                    "refund_priority_class": 2,
                },
                anonymous,
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        rows, _ = validate_paginated(api_client.list_coverage_profiles(ADMIN))
        assert rows == [], "an unauthenticated create stores nothing at all"

    def test_the_analyst_who_screened_the_claim_still_cannot_approve_it(self):
        """Role authorisation — the acting role appears in the endpoint's authorised roles →
        `ERR_ROLE_NOT_PERMITTED`, on every endpoint.

        Approval is the moment the estate takes on a hard liability, and it is exclusive to
        `ClaimsCommitteeOfficer` on a claim in `RECOMMENDED`.

        Design: Corner/rbac/a_coverage_analyst_cannot_approve_a_claim
        """
        env = setup_recommended_claim(
            recommended_amount_cents=890_000,
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        claim = env["claim"]
        assert claim["status"] == "RECOMMENDED", claim["status"]

        validate_error(
            api_client.approve_claim(claim["id"], SECOND_ANALYST),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        after = read_claim(claim["id"])
        assert_covered_claim(after)
        assert after["status"] == "RECOMMENDED", (
            f"the claim waits for the committee, got {after['status']}"
        )
        assert after["approved_by_user_id"] is None, after["approved_by_user_id"]
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, (
            f"and no reserve is booked, got {insolvency['reserved_claim_cents']}"
        )

    def test_an_adjuster_may_only_recommend_on_the_claim_it_is_engaged_on(self):
        """Vendor ownership — for `ClaimsAdjuster` and `DefenseCounsel`, `X-User-ID` is the `id` of an
        `ASSIGNED` vendor engagement on the target claim whose `vendor_type` matches the role →
        `ERR_NOT_ASSIGNED_ADJUSTER`, on `POST /claims/{id}/recommend` and
        `POST /claims/{id}/vendor-assignments/{assignmentId}/invoices`.

        Design: Corner/rbac/an_adjuster_engaged_on_another_claim_cannot_recommend_on_this_one
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
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
        engage_vendor(env, **BELLWETHER_ADJUSTER)
        sibling_claim = env["claim"]
        sibling_adjuster_headers = env["adjuster_headers"]
        assert sibling_claim["status"] == "ADJUSTING", sibling_claim["status"]

        validate_error(
            api_client.recommend_claim(
                first_claim["id"],
                {"recommended_amount_cents": 500_000},
                sibling_adjuster_headers,
            ),
            "ERR_NOT_ASSIGNED_ADJUSTER",
            403,
        )

        after_first = read_claim(first_claim["id"])
        assert after_first["status"] == "ADJUSTING", after_first["status"]
        assert after_first["recommended_amount_cents"] is None, (
            "a vendor engaged elsewhere binds nothing here, got "
            f"{after_first['recommended_amount_cents']}"
        )
        assert after_first["recommended_by_vendor_name"] is None
        after_sibling = read_claim(sibling_claim["id"])
        assert after_sibling["status"] == "ADJUSTING", (
            f"its own claim is equally untouched, got {after_sibling['status']}"
        )

    def test_a_member_agent_may_only_settle_its_own_invoice(self):
        """Member ownership — for `MemberInsurerAgent`, `X-User-ID` equals the target invoice's
        `member_insurer_id` → `ERR_NOT_ASSESSED_MEMBER`, on
        `POST /member-assessments/{id}/payments`,
        `POST /member-assessments/{id}/surcharge-filings` and
        `POST /member-assessments/{id}/recoupment-remittances`.

        Design: Corner/rbac/another_members_agent_cannot_pay_this_levy
        """
        env = setup_certified_assessment(
            member_specs=TWO_MEMBERS,
            needed_amount_cents=400_000,
            policy_overrides=dict(LIVE_TERM),
        )
        invoices = env["member_assessments"]
        assert len(invoices) == 2, f"both members are levied, got {len(invoices)}"
        first_invoice = invoices[0]
        other_agent = env["agent_headers"][env["members"][1]["id"]]
        assert first_invoice["member_insurer_id"] == env["members"][0]["id"]

        validate_error(
            api_client.create_member_payment(
                first_invoice["id"],
                {"amount_cents": 50_000, "payment_ref": "WIRE-X"},
                other_agent,
            ),
            "ERR_NOT_ASSESSED_MEMBER",
            403,
        )

        after = read_member_assessment(first_invoice["id"])
        assert after["paid_amount_cents"] == 0, (
            f"the levied member's own balance is untouched, got {after['paid_amount_cents']}"
        )
        assert after["billing_status"] == "INVOICED", after["billing_status"]
        assessment = read_assessment(env["assessment"]["id"])
        assert assessment["collected_amount_cents"] == 0, (
            f"and the levy has collected nothing, got {assessment['collected_amount_cents']}"
        )
        assert len(list_member_assessments(assessment_id=assessment["id"], limit=100)) == 2


class TestSharedOperations:
    """Some operations belong to two roles at once."""

    def test_both_the_receiver_liaison_and_the_analyst_may_file_a_claim(self):
        """A covered claim may be presented by a `ReceiverLiaison` or a `CoverageAnalyst`, but only
        against a triggered insolvency file and only at or before the file's
        `proof_of_claim_deadline_utc`; a filing whose logical-clock instant falls strictly after that
        boundary is refused with `ERR_FILING_DEADLINE_PASSED`.

        Design: Corner/rbac/claim_intake_is_shared_by_the_receiver_liaison_and_the_coverage_analyst
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        insolvency_id = env["insolvency"]["id"]
        policy_id = env["policy"]["id"]

        relayed = get_success_data(
            api_client.create_claim(
                claim_payload(
                    insolvency_id,
                    policy_id,
                    claim_number="C-RL",
                    claimant_name="Ben Ortiz",
                    gross_loss_cents=900_000,
                ),
                RECEIVER,
            ),
            201,
        )
        filed_in_house = get_success_data(
            api_client.create_claim(
                claim_payload(
                    insolvency_id,
                    policy_id,
                    claim_number="C-CA",
                    claimant_name="Cora Diaz",
                    loss_date="2026-01-20",
                    gross_loss_cents=400_000,
                ),
                ANALYST,
            ),
            201,
        )

        assert_covered_claim(relayed)
        assert_covered_claim(filed_in_house)
        assert relayed["status"] == "RECEIVED", relayed["status"]
        assert filed_in_house["status"] == "RECEIVED", filed_in_house["status"]

        rows, meta = validate_paginated(
            api_client.list_claims(ANALYST, {"insolvency_id": insolvency_id, "limit": 50})
        )
        assert len(rows) == 2, f"both intake routes minted a row, got {len(rows)}"
        assert meta["total_count"] == 2, meta["total_count"]
        assert {row["claim_number"] for row in rows} == {"C-RL", "C-CA"}
