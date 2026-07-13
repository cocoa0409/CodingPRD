"""Plan tiers, enrollment, and the verification cascade (PRD §3.1)."""

from test_helpers import (
    ApiErrorId,
    assert_plan,
    assert_subscriber,
    create_plan,
    create_plan_payload,
    create_verified_subscriber,
    enroll_subscriber,
    enroll_subscriber_payload,
    get_bureau_profiles,
    get_subscriber,
    is_valid_uuid,
    score_refresh,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanCreation:
    def test_plan_optional_knobs_default_to_false_and_tier1(self, api, admin_headers):
        """PRD §3.1: "An operator registers a plan with a `tier` (`STANDARD`, `ADVANTAGE`, or
        `ULTIMATE`), a recurring `monthly_fee_cents` which may be zero but never negative, a
        strictly positive `insurance_limit_cents` naming the lifetime ceiling on identity-theft
        reimbursement, a `max_family_members` allowance which may be zero, a `bureau_scope` of
        either `SINGLE` or `TRI`, and two optional knobs: `child_monitoring_included`, a boolean
        defaulting to `false`, and `min_specialist_tier`, one of `TIER1`, `TIER2` or `TIER3` and
        defaulting to `TIER1`."
        PRD §2.4: "`version` (integer): a counter that increments by exactly one on every mutation
        of the resource, including mutations that only touch a derived field."

        Design: Corner/entities/plan_creation_returns_201_with_defaults_applied
        """
        payload = {
            "tier": "STANDARD",
            "monthly_fee_cents": 999,
            "insurance_limit_cents": 100000,
            "max_family_members": 1,
            "bureau_scope": "SINGLE",
        }
        plan = validate_success(api.create_plan(payload, admin_headers), 201)

        assert_plan(plan)
        assert plan["child_monitoring_included"] is False, "the flag defaults to false"
        assert plan["min_specialist_tier"] == "TIER1", "the floor defaults to TIER1"
        assert plan["version"] == 1, "a freshly created plan sits at version 1"
        assert is_valid_uuid(plan["id"])

    def test_plan_create_ignores_client_supplied_id_and_version(self, api, admin_headers):
        """PRD §2.4: "`id` (string): a server-minted UUID. There is no type prefix and no other
        encoding; the raw UUID is the identifier."
        PRD §2.4: "`version` (integer): a counter that increments by exactly one on every mutation
        of the resource, including mutations that only touch a derived field."

        Design: Corner/entities/plan_create_system_fields_input_ignored
        """
        spoofed_id = "00000000-0000-0000-0000-000000000001"
        payload = {
            "tier": "STANDARD",
            "monthly_fee_cents": 999,
            "insurance_limit_cents": 100000,
            "max_family_members": 1,
            "bureau_scope": "SINGLE",
            "id": spoofed_id,
            "version": 99,
        }
        plan = validate_success(api.create_plan(payload, admin_headers), 201)

        assert plan["id"] != spoofed_id, "the server mints its own id"
        assert is_valid_uuid(plan["id"])
        assert plan["version"] == 1, "the client cannot seed version"


class TestEnrollment:
    def test_enrollment_lands_pending_verification_with_nothing_provisioned(
        self, api, anonymous_headers, admin_headers
    ):
        """PRD §3.1: "The new **Subscriber** row lands with `enrollment_status` at
        `PENDING_VERIFICATION` and `monitoring_status` at `NOT_ENROLLED`, and the server mints a
        `verification_token` which it returns on the response. At this point nothing else exists:
        no bureau profiles, no insurance budget (`insurance_remaining_cents` sits at 0 and
        `insurance_status` at `AVAILABLE`), no scores."

        Design: Corner/entities/subscriber_enrollment_starts_pending_verification_with_no_bureau_profiles
        """
        plan = create_plan(bureau_scope="TRI")

        resp = api.enroll_subscriber(
            enroll_subscriber_payload(plan["id"], full_name="Nora Vela", ssn_last4="1111"),
            anonymous_headers,
        )
        subscriber = validate_success(resp, 201)

        assert_subscriber(subscriber)
        assert subscriber["enrollment_status"] == "PENDING_VERIFICATION"
        assert subscriber["monitoring_status"] == "NOT_ENROLLED"
        assert isinstance(subscriber["verification_token"], str)
        assert subscriber["verification_token"], "the server mints a verification_token"
        assert subscriber["insurance_remaining_cents"] == 0, "no budget before verification"
        assert subscriber["insurance_status"] == "AVAILABLE"
        assert subscriber["composite_credit_score"] is None

        profiles, _ = validate_paginated(
            api.list_bureau_profiles(subscriber["id"], admin_headers)
        )
        assert profiles == [], "no bureau profiles exist before verification"

    def test_enrollment_without_ssn_last4_is_rejected(self, api, anonymous_headers, admin_headers):
        """PRD §2.5: "Body schema — required fields present, enum members drawn from the declared
        sets, integers non-negative, `ssn_last4` exactly four decimal digits, `expenses` a
        non-empty array of well-formed line items. Any breach is `ERR_INVALID_REQUEST`."
        PRD §3.1: "The enrolling party supplies an `email` (unique across subscribers), a
        `full_name`, a `date_of_birth` in `YYYY-MM-DD` form, an `ssn_last4` consisting of exactly
        four decimal digits, and the `plan_id` of the plan being bought."

        Design: Corner/entities/subscriber_create_missing_required_ssn_last4_returns_invalid_request
        """
        plan = create_plan(bureau_scope="TRI")

        resp = api.enroll_subscriber(
            {
                "email": "gap-test@example.com",
                "full_name": "Gap Test",
                "date_of_birth": "1990-01-01",
                "plan_id": plan["id"],
            },
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        rows, _ = validate_paginated(
            api.list_subscribers(admin_headers, params={"plan_id": plan["id"]})
        )
        assert rows == [], "the rejected enrollment created no subscriber row"

    def test_enrollment_with_unknown_plan_id_is_not_found(self, api, anonymous_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/entities/plan_not_found_on_enrollment_returns_404
        """
        resp = api.enroll_subscriber(
            {
                "email": "ghost-plan@example.com",
                "full_name": "Ghost Plan",
                "date_of_birth": "1990-01-01",
                "ssn_last4": "7777",
                "plan_id": "11111111-2222-4333-8444-555555555555",
            },
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)

    def test_reading_an_unknown_subscriber_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/entities/subscriber_not_found_returns_404
        """
        resp = api.get_subscriber("9d1f7c2a-0000-4000-8000-aaaabbbbcccc", admin_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND)


class TestVerificationCascade:
    def test_verify_with_the_wrong_token_is_rejected(self, api, anonymous_headers, admin_headers):
        """PRD §3.1: "The caller — the subscriber themself, or an anonymous holder of the token —
        presents `verification_token` in the body. If it does not equal the token stored on the
        subscriber, the request is rejected with `ERR_INVALID_VERIFICATION_TOKEN`."

        Design: Corner/validations/verify_with_wrong_token_rejected
        """
        plan = create_plan(bureau_scope="TRI")
        subscriber = enroll_subscriber(plan["id"], full_name="Bad Token", ssn_last4="4444")

        resp = api.verify_subscriber(
            subscriber["id"], {"verification_token": "not-the-real-token"}, anonymous_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_TOKEN)

        after = get_subscriber(subscriber["id"])
        assert after["enrollment_status"] == "PENDING_VERIFICATION"

        profiles, _ = validate_paginated(
            api.list_bureau_profiles(subscriber["id"], admin_headers)
        )
        assert profiles == [], "a rejected verification provisions no bureau profiles"

    def test_verify_on_single_bureau_plan_provisions_only_equifax(
        self, api, anonymous_headers, admin_headers
    ):
        """PRD §3.1: "Bureau profiles are provisioned: on a `TRI` plan, three profiles are created
        in this exact order — `EQUIFAX`, then `EXPERIAN`, then `TRANSUNION`; on a `SINGLE` plan,
        only `EQUIFAX` is created."
        PRD §3.1: "The insurance budget is provisioned: `insurance_remaining_cents` is set to the
        plan's `insurance_limit_cents` and `insurance_status` to `AVAILABLE`."

        Design: Corner/state_machines/verify_on_single_bureau_plan_creates_one_profile_only
        """
        plan = create_plan(
            tier="STANDARD",
            monthly_fee_cents=999,
            insurance_limit_cents=100000,
            max_family_members=1,
            child_monitoring_included=False,
            bureau_scope="SINGLE",
        )
        subscriber = enroll_subscriber(plan["id"], full_name="Solo Bureau", ssn_last4="1919")

        resp = api.verify_subscriber(
            subscriber["id"],
            {"verification_token": subscriber["verification_token"]},
            anonymous_headers,
        )
        verified = validate_success(resp, 200)

        assert verified["enrollment_status"] == "ACTIVE"
        assert verified["monitoring_status"] == "PENDING_DATA"
        assert verified["insurance_remaining_cents"] == 100000
        assert verified["insurance_status"] == "AVAILABLE"

        profiles, _ = validate_paginated(
            api.list_bureau_profiles(subscriber["id"], admin_headers)
        )
        assert len(profiles) == 1, "a SINGLE plan provisions exactly one bureau profile"
        assert profiles[0]["bureau"] == "EQUIFAX"


class TestSubscriberStatusDimensions:
    """The enrollment and monitoring dimensions of a Subscriber move independently."""

    def test_score_refresh_moves_monitoring_only_and_leaves_enrollment_active(self, api):
        """PRD §3.1: "A subscriber crossing `PENDING_DATA → MONITORED` because a bureau finally
        reported a score does not touch their enrollment dimension at all."
        PRD §3.3: "The first refresh that yields a non-null composite is special. It carries the
        subscriber's monitoring dimension `PENDING_DATA → MONITORED`, and it writes
        `baseline_composite_credit_score` — a permanent snapshot of the composite as it stood the
        first time it existed."

        Design: Difficulty/non_linear_state_machine/subscriber_enrollment_and_monitoring_dimensions_move_independently
        """
        _, subscriber = create_verified_subscriber(full_name="Ravi Kohl", ssn_last4="2020")
        assert subscriber["enrollment_status"] == "ACTIVE"
        assert subscriber["monitoring_status"] == "PENDING_DATA"
        assert subscriber["composite_credit_score"] is None

        equifax = get_bureau_profiles(subscriber["id"])[0]
        score_refresh(equifax["id"], 700)

        after = get_subscriber(subscriber["id"])
        assert after["monitoring_status"] == "MONITORED", "the monitoring dimension advanced"
        assert after["enrollment_status"] == "ACTIVE", "the enrollment dimension is untouched"
        assert after["composite_credit_score"] == 700
        assert after["baseline_composite_credit_score"] == 700

    def test_suspend_pauses_monitoring_and_reactivate_restores_it_to_monitored(
        self, api, admin_headers
    ):
        """PRD §3.1: "The enrollment dimension moves `ACTIVE → SUSPENDED`, and if the monitoring
        dimension was in `PENDING_DATA` or `MONITORED` it moves to `PAUSED`; a monitoring dimension
        already at `NOT_ENROLLED` is left alone."
        PRD §3.1: "**Reactivation** is the mirror image: the enrollment dimension moves
        `SUSPENDED → ACTIVE`, `suspension_reason` is cleared back to null, and the monitoring
        dimension is restored intelligently — `PAUSED → MONITORED` when the subscriber already has
        a non-null `composite_credit_score`, and `PAUSED → PENDING_DATA` when they do not."

        Design: Difficulty/non_linear_state_machine/subscriber_enrollment_and_monitoring_dimensions_move_independently
        """
        _, subscriber = create_verified_subscriber(full_name="Ravi Kohl", ssn_last4="2020")
        equifax = get_bureau_profiles(subscriber["id"])[0]
        score_refresh(equifax["id"], 700)

        suspended = validate_success(
            api.suspend_subscriber(
                subscriber["id"], {"reason": "Payment method declined"}, admin_headers
            )
        )
        assert suspended["enrollment_status"] == "SUSPENDED"
        assert suspended["monitoring_status"] == "PAUSED"
        assert suspended["suspension_reason"] == "Payment method declined"

        reactivated = validate_success(
            api.reactivate_subscriber(subscriber["id"], admin_headers)
        )
        assert reactivated["enrollment_status"] == "ACTIVE"
        assert reactivated["monitoring_status"] == "MONITORED", (
            "composite_credit_score is non-null, so monitoring returns to MONITORED"
        )
        assert reactivated["suspension_reason"] is None