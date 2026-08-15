"""Filing profiles, policy issuance, and insured interests.

Covers profile activation/retirement gates, issuance validation, policy
defaults, the append-only premium ledger shape, pagination, and interest
scoping.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_insured_interest,
    assert_ledger_entry,
    assert_no_return_entries,
    assert_policy,
    attach_interest,
    create_active_profile,
    create_holder,
    create_policy_payload,
    create_state_profile_payload,
    get_success_data,
    issue_policy,
    make_policyholder_headers,
    api_client,
    cancel_policy_effective,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestPolicyIssuanceValidation:
    def test_create_policy_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.2: "Issuance against a profile that is not `ACTIVE`, a
        `term_end_date` that does not fall strictly after the `term_start_date`,
        a non-positive premium, or any missing or invalid field is rejected as
        malformed with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_policy_missing_required_field_returns_invalid_request
        """
        profile = create_active_profile("AK")
        holder = create_holder(full_name="Ak Insured", email="ak@x.com")

        payload = create_policy_payload(holder["id"], profile["id"], "P-AK-1")
        del payload["total_premium_cents"]
        resp = api.create_policy(payload, UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, _meta = validate_paginated(
            api.list_policies(OFFICER, params={"policyholder_id": holder["id"]})
        )
        assert data == [], "no Policy row may be created by a rejected issuance"

    def test_term_end_not_after_start_rejected(self, api):
        """PRD §3.2: "Issuance against a profile that is not `ACTIVE`, a
        `term_end_date` that does not fall strictly after the `term_start_date`,
        a non-positive premium, or any missing or invalid field is rejected as
        malformed with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/term_end_not_after_start_rejected
        """
        profile = create_active_profile("FL")
        holder = create_holder(full_name="Fl Insured", email="fl@x.com")

        resp = api.create_policy(
            create_policy_payload(
                holder["id"],
                profile["id"],
                "P-FL-1",
                term_start_date="2026-06-01",
                term_end_date="2026-06-01",
                total_premium_cents=10000,
            ),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_policy_default_fields_applied_on_creation(self, api):
        """PRD §3.2: "A newly issued policy is `ACTIVE`, with
        `reinstatements_used` at zero, `cancellation_effective_date` unset, and
        `lapse_flag` false; issuance also posts the policy's first ledger line,
        a `WRITTEN` entry for the full premium."

        Design: Corner/entities/policy_default_fields_applied_on_creation
        """
        profile = create_active_profile("HI")
        holder = create_holder(full_name="Hi Insured", email="hi@x.com")

        resp = api.create_policy(
            create_policy_payload(holder["id"], profile["id"], "P-HI-1", total_premium_cents=30000),
            UNDERWRITER,
        )
        policy = validate_success(resp, expected_status=201)
        assert_policy(policy)
        assert policy["status"] == "ACTIVE"
        assert policy["reinstatements_used"] == 0
        assert policy["lapse_flag"] is False
        assert policy["cancellation_effective_date"] is None

    def test_policy_initial_state_active(self, api):
        """PRD §3.2: "A newly issued policy is `ACTIVE`, with
        `reinstatements_used` at zero, `cancellation_effective_date` unset, and
        `lapse_flag` false; issuance also posts the policy's first ledger line,
        a `WRITTEN` entry for the full premium."

        Design: Corner/state_machines/policy_initial_state_active
        """
        profile = create_active_profile("IN")
        holder = create_holder(full_name="In Insured", email="in@x.com")

        resp = api.create_policy(
            create_policy_payload(holder["id"], profile["id"], "P-IN-1", total_premium_cents=10000),
            UNDERWRITER,
        )
        policy = validate_success(resp, expected_status=201)
        assert policy["status"] == "ACTIVE", f"New policy must be ACTIVE, got {policy['status']}"

    def test_get_nonexistent_policy_returns_not_found(self, api):
        """PRD §2.7: "the server resolves each identifier in turn, and the
        first identifier that does not resolve to an existing resource rejects
        the request immediately with `ERR_NOT_FOUND`; later identifiers in the
        path are never consulted once an earlier one fails."

        Design: Corner/entities/get_nonexistent_policy_returns_not_found
        """
        resp = api.get_policy("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_policies_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it may never be less than 1 or
        greater than 100. The `offset` parameter states how many items to skip
        and defaults to 0." and "Paginated list responses carry `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/list_policies_pagination_envelope
        """
        profile = create_active_profile("CT")
        holder = create_holder(full_name="Ct Insured", email="ct@x.com")
        for i in range(1, 13):
            issue_policy(profile["id"], holder["id"], f"P-CT-{i:02d}", total_premium_cents=10000)

        page1, meta1 = validate_paginated(
            api.list_policies(OFFICER, params={"policyholder_id": holder["id"], "limit": 10, "offset": 0})
        )
        assert len(page1) == 10, f"page 1 must hold 10 rows, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_policies(OFFICER, params={"policyholder_id": holder["id"], "limit": 10, "offset": 10})
        )
        assert len(page2) == 2, f"page 2 must hold 2 rows, got {len(page2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestPolicyNumberUniqueness:
    def test_duplicate_policy_number_rejected(self, api):
        """PRD §3.2: "Policy issuance then binds a policyholder to a filing
        profile: the request carries the `policyholder_id`, the
        `state_profile_id` of the governing profile — pinned at issuance for
        the life of the policy — a carrier-visible `policy_number` that must
        be globally unique across all policies, the `term_start_date` and
        `term_end_date`, and the `total_premium_cents` written for the full
        term. A duplicate `policy_number` is rejected with
        `ERR_DUPLICATE_POLICY_NUMBER`."

        Design: Corner/errors/duplicate_policy_number_rejected
        """
        profile = create_active_profile("PR")
        holder1 = create_holder(full_name="Dup One", email="d1@x.com")
        holder2 = create_holder(full_name="Dup Two", email="d2@x.com")
        issue_policy(profile["id"], holder1["id"], "P-DUP-1", total_premium_cents=10000)

        resp = api.create_policy(
            create_policy_payload(holder2["id"], profile["id"], "P-DUP-1", total_premium_cents=10000),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER)


class TestPremiumLedgerShape:
    def test_ledger_entry_is_immutable_no_update_endpoint(self, api):
        """PRD §2.5: "The premium ledger is the one exception to the
        common-fields convention: a PremiumLedgerEntry is immutable once
        posted, carries only `id` and `created_at`, and has neither
        `updated_at` nor `version`."
        PRD §2.9: "Issuing a policy posts a `WRITTEN` entry for the full
        `total_premium_cents`."

        Design: Corner/entities/ledger_entry_is_immutable_no_update_endpoint
        """
        profile = create_active_profile("AR")
        holder = create_holder(full_name="Ar Insured", email="ar@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-AR-1", total_premium_cents=30000)

        entries = get_success_data(api.list_policy_ledger_entries(policy["id"], OFFICER))
        assert len(entries) == 1, f"issuance posts exactly one ledger line, got {len(entries)}"
        entry = entries[0]
        assert_ledger_entry(entry)
        assert entry["entry_kind"] == "WRITTEN"
        assert entry["amount_cents"] == 30000


class TestInsuredInterests:
    def test_invalid_enum_on_interest_type_rejected(self, api):
        """PRD §3.2: "the `Underwriter` may attach insured interests to it —
        each recording an `interest_type` of `MORTGAGEE`, `LIENHOLDER`, or
        `ADDITIONAL_INTEREST`, the `institution_name`, a notice
        `mailing_address`, and an optional external `loan_number` that
        defaults to empty." A value outside that enumeration is not a valid
        interest and the request is malformed (`ERR_INVALID_REQUEST`, the
        catalogue's only 400 for malformed bodies, PRD §5).

        Design: Corner/entities/invalid_enum_on_interest_type_rejected
        """
        profile = create_active_profile("DE")
        holder = create_holder(full_name="De Insured", email="de@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-DE-1", total_premium_cents=10000)

        resp = api.create_interest(
            policy["id"],
            {"interest_type": "FRIEND", "institution_name": "Buddy", "mailing_address": "1 F St"},
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        interests = get_success_data(api.list_interests(policy["id"], OFFICER))
        assert interests == [], "a rejected interest must not persist"

    def test_fk_reverse_reachability_interests_under_policy(self, api):
        """PRD §2.7: "This ordering applies equally to reads and to nested
        creation, so an interest can never be attached beneath a policy that
        does not exist." Interests are listed beneath their own policy: the
        list under the attaching policy returns the record, the list under a
        sibling policy does not.

        Design: Corner/entities/fk_reverse_reachability_interests_under_policy
        """
        profile = create_active_profile("MD")
        holder = create_holder(full_name="Md Insured", email="md@x.com")
        policy_a = issue_policy(profile["id"], holder["id"], "P-MD-A", total_premium_cents=10000)
        policy_b = issue_policy(profile["id"], holder["id"], "P-MD-B", total_premium_cents=10000)
        interest = attach_interest(
            policy_a["id"], interest_type="MORTGAGEE", institution_name="Bank A"
        )
        assert_insured_interest(interest)

        list_a = get_success_data(api.list_interests(policy_a["id"], OFFICER))
        assert len(list_a) == 1 and list_a[0]["id"] == interest["id"]

        list_b = get_success_data(api.list_interests(policy_b["id"], OFFICER))
        assert list_b == [], "interests must be scoped to their own policy"


class TestProfileGatesIssuance:
    def test_issuance_against_draft_profile_rejected(self, api):
        """PRD §3.2: "Issuance against a profile that is not `ACTIVE`, a
        `term_end_date` that does not fall strictly after the `term_start_date`,
        a non-positive premium, or any missing or invalid field is rejected as
        malformed with `ERR_INVALID_REQUEST`."

        Design: Difficulty/cross_entity_state_dependency/policy_issuance_gated_on_profile_active
        """
        resp = api_client.create_state_profile(create_state_profile_payload(state_code="KS"), OFFICER)
        profile = validate_success(resp, expected_status=201)
        assert profile["status"] == "DRAFT"
        holder = create_holder(full_name="Ks Insured", email="ks@x.com")

        resp = api.create_policy(
            create_policy_payload(holder["id"], profile["id"], "P-KS-1", total_premium_cents=30000),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, _meta = validate_paginated(
            api.list_policies(OFFICER, params={"policyholder_id": holder["id"]})
        )
        assert data == [], "no policy may exist after a rejected issuance"

    def test_issuance_succeeds_after_profile_activation(self, api):
        """PRD §3.1: "Activation moves a profile `DRAFT → ACTIVE`, and only
        `ACTIVE` profiles are consulted by calculations."
        PRD §3.2: "Issuance against a profile that is not `ACTIVE`, a
        `term_end_date` that does not fall strictly after the `term_start_date`,
        a non-positive premium, or any missing or invalid field is rejected as
        malformed with `ERR_INVALID_REQUEST`."

        Design: Difficulty/cross_entity_state_dependency/policy_issuance_gated_on_profile_active
        """
        resp = api_client.create_state_profile(create_state_profile_payload(state_code="KS"), OFFICER)
        profile = validate_success(resp, expected_status=201)
        holder = create_holder(full_name="Ks Insured", email="ks@x.com")

        rejected = api.create_policy(
            create_policy_payload(holder["id"], profile["id"], "P-KS-1", total_premium_cents=30000),
            UNDERWRITER,
        )
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)

        activated = validate_success(api.activate_state_profile(profile["id"], OFFICER))
        assert activated["status"] == "ACTIVE"

        issued = validate_success(
            api.create_policy(
                create_policy_payload(holder["id"], profile["id"], "P-KS-1", total_premium_cents=30000),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        assert_policy(issued)
        assert issued["status"] == "ACTIVE"


class TestProfileActivationOverlap:
    def test_second_activation_same_state_code_rejected(self, api):
        """PRD §3.1: "At most one profile per `state_code` may be `ACTIVE` at
        any moment: activating a profile while another `ACTIVE` profile carries
        the same code is rejected with `ERR_STATE_PROFILE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/state_profile_activation_overlap_on_same_state_code
        """
        profile1 = create_active_profile("IA")
        resp = api_client.create_state_profile(
            create_state_profile_payload(
                state_code="IA",
                permissible_grounds=["NONPAYMENT", "LICENSE_SUSPENSION"],
                nonpayment_notice_days=15,
                nonrenewal_notice_days=75,
                reinstatement_window_days=30,
                max_reinstatements=1,
            ),
            OFFICER,
        )
        profile2 = validate_success(resp, expected_status=201)

        conflict = api.activate_state_profile(profile2["id"], OFFICER)
        validate_error(conflict, ApiErrorId.ERR_STATE_PROFILE_CONFLICT)

        still_draft = validate_success(api.get_state_profile(profile2["id"], OFFICER))
        assert still_draft["status"] == "DRAFT"
        assert profile1["status"] == "ACTIVE"

    def test_activation_succeeds_after_first_profile_retired(self, api):
        """PRD §3.1: "At most one profile per `state_code` may be `ACTIVE` at
        any moment: activating a profile while another `ACTIVE` profile carries
        the same code is rejected with `ERR_STATE_PROFILE_CONFLICT`." Once the
        first profile leaves `ACTIVE`, the second activation is permitted.

        Design: Difficulty/resource_temporal_overlap/state_profile_activation_overlap_on_same_state_code
        """
        profile1 = create_active_profile("IA")
        resp = api_client.create_state_profile(create_state_profile_payload(state_code="IA"), OFFICER)
        profile2 = validate_success(resp, expected_status=201)

        conflict = api.activate_state_profile(profile2["id"], OFFICER)
        validate_error(conflict, ApiErrorId.ERR_STATE_PROFILE_CONFLICT)

        retired = validate_success(api.retire_state_profile(profile1["id"], OFFICER))
        assert retired["status"] == "RETIRED"

        activated = validate_success(api.activate_state_profile(profile2["id"], OFFICER))
        assert activated["status"] == "ACTIVE"

        data, _meta = validate_paginated(
            api.list_state_profiles(OFFICER, params={"state_code": "IA", "status": "ACTIVE"})
        )
        assert len(data) == 1 and data[0]["id"] == profile2["id"]


class TestProfileRetireGate:
    def test_retire_with_live_policy_rejected(self, api):
        """PRD §3.1: "Retirement moves a profile `ACTIVE → RETIRED`, but only
        once no policy in `ACTIVE`, `CANCEL_PENDING`, or `NONRENEWAL_PENDING`
        status still references it — a retire attempted while such live
        policies exist is rejected with `ERR_STATE_PROFILE_IN_USE`."

        Design: Difficulty/cross_entity_state_dependency/profile_retire_gated_on_live_policy_references
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("MO")
        holder = create_holder(full_name="Mo Insured", email="mo@x.com")
        issue_policy(profile["id"], holder["id"], "P-MO-1", total_premium_cents=30000)

        resp = api.retire_state_profile(profile["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_STATE_PROFILE_IN_USE)

        current = validate_success(api.get_state_profile(profile["id"], OFFICER))
        assert current["status"] == "ACTIVE"

    def test_retire_succeeds_once_policy_reaches_terminal_cancelled(self, api):
        """PRD §3.1: "Retirement moves a profile `ACTIVE → RETIRED`, but only
        once no policy in `ACTIVE`, `CANCEL_PENDING`, or `NONRENEWAL_PENDING`
        status still references it — a retire attempted while such live
        policies exist is rejected with `ERR_STATE_PROFILE_IN_USE`."

        Design: Difficulty/cross_entity_state_dependency/profile_retire_gated_on_live_policy_references
        """
        bundle = cancel_policy_effective(
            "MO",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            premium_cents=30000,
            policy_number="P-MO-1",
        )
        assert bundle["policy"]["status"] == "CANCELLED"

        retired = validate_success(api.retire_state_profile(bundle["profile"]["id"], OFFICER))
        assert retired["status"] == "RETIRED"
