"""Change control under optimistic concurrency (PRD §2.6, §3.3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_approved_model,
    create_change_request,
    create_model,
    decide_change_request,
    get_model,
    validate_error,
    validate_paginated,
    validate_success,
    assert_instant_equal,
    create_retired_pair,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]


class TestChangeRequestCreation:
    def test_change_request_creation_stamps_submitter(self, api):
        """PRD §3.3: "The request starts in `SUBMITTED` with `submitted_by_user_id`
        recorded; the change-request list can be filtered by `status`."
        PRD §3.3: "Each successfully created change request increments the model's
        `version` by one — which is precisely why a second submission carrying the same
        expected version fails: the first submission itself advanced the model."

        Design: Corner/entities/change_request_creation_stamps_submitter
        """
        model = create_model(name="CR M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        cr = validate_success(
            api.create_change_request(
                model["id"],
                {"change_type": "MINOR", "description": "retune cutoff",
                 "expected_model_version": model["version"]},
                OWNER_A,
            ),
            expected_status=201,
        )
        assert cr["status"] == "SUBMITTED"
        assert cr["submitted_by_user_id"] == "u_own_a"
        after = validate_success(api.get_model(model["id"], OWNER_A))
        assert after["version"] == model["version"] + 1, "creation increments the model's version by one"

    def test_change_request_reject_leaves_validation_due_unchanged(self, api):
        """PRD §3.3: "Approving a `MINOR` request and rejecting either kind leave the
        calendar untouched."
        PRD §3.3: "The officer's identity is recorded as `decided_by_user_id`, and the
        decision itself also increments the model's `version` by one."
        PRD §3.1: "A model's `validation_due_at` is anchored to `last_validated_at`
        when set, otherwise to `created_at`, and equals the anchor plus the tier's
        revalidation interval: six months for `TIER_1`, twelve months for `TIER_2`,
        twenty-four months for `TIER_3`."

        TIER_3 model registered at the 2026-08-01 default clock -> due 2028-08-01;
        rejecting a MINOR change leaves it untouched.

        Design: Corner/state_machines/change_request_reject_leaves_validation_due_unchanged
        """
        model = create_model(name="RejCR M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        assert_instant_equal(model["validation_due_at"], "2028-08-01T00:00:00Z", "initial validation_due_at")
        cr = create_change_request(model["id"], "MINOR", model["version"], description="doc fix")
        decided = validate_success(
            api.decide_change_request(model["id"], cr["id"], {"decision": "REJECT"}, OFFICER)
        )
        assert decided["status"] == "REJECTED"
        assert decided["decided_by_user_id"] == "u_cro"
        after = validate_success(api.get_model(model["id"], OFFICER))
        assert_instant_equal(after["validation_due_at"], "2028-08-01T00:00:00Z",
                             "validation_due_at after REJECT")

    def test_change_request_decide_twice_returns_already_decided(self, api):
        """PRD §3.3: "Only a `SUBMITTED` request is decidable; any second decision
        attempt fails with `ERR_CHANGE_REQUEST_ALREADY_DECIDED`."

        Design: Corner/state_machines/change_request_decide_twice_returns_already_decided
        """
        model = create_model(name="TwiceCR M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        cr = create_change_request(model["id"], "MINOR", model["version"], description="tweak")
        validate_success(api.decide_change_request(model["id"], cr["id"], {"decision": "APPROVE"}, OFFICER))
        err = validate_error(
            api.decide_change_request(model["id"], cr["id"], {"decision": "REJECT"}, OFFICER),
            ApiErrorId.ERR_CHANGE_REQUEST_ALREADY_DECIDED,
        )
        assert err["error_id"] == "ERR_CHANGE_REQUEST_ALREADY_DECIDED"


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected(self, api):
        """PRD §2.6: "If that value does not equal the model's current `version` —
        because another writer has advanced the model since the client read it — the
        submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never
        acts on an outdated view of the model."
        PRD §3.3: "Each successfully created change request increments the model's
        `version` by one — which is precisely why a second submission carrying the same
        expected version fails: the first submission itself advanced the model."

        Design: Corner/validations/occ_stale_version_rejected
        """
        model = create_model(name="OCC M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        create_change_request(model["id"], "MINOR", model["version"], description="first")
        err = validate_error(
            api.create_change_request(
                model["id"],
                {"change_type": "MINOR", "description": "second with stale version",
                 "expected_model_version": model["version"]},
                OWNER_A,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        assert err["error_id"] == "ERR_STALE_VERSION"
        crs, _ = validate_paginated(api.list_change_requests(model["id"], OWNER_A))
        assert len(crs) == 1, "the rejected submission must not persist a change request"

    def test_occ_fresh_version_after_stale_failure_succeeds(self, api):
        """PRD §2.6: "Change requests are allowed to coexist: a second, sequential
        submission carrying a freshly observed version legitimately succeeds."

        Design: Corner/validations/occ_fresh_version_after_stale_failure_succeeds
        """
        model = create_model(name="OCC2 M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        create_change_request(model["id"], "MINOR", model["version"], description="first")
        fresh = validate_success(api.get_model(model["id"], OWNER_A))
        assert fresh["version"] == model["version"] + 1
        cr2 = validate_success(
            api.create_change_request(
                model["id"],
                {"change_type": "MAJOR", "description": "second with fresh version",
                 "expected_model_version": fresh["version"]},
                OWNER_A,
            ),
            expected_status=201,
        )
        assert cr2["status"] == "SUBMITTED"
        crs, _ = validate_paginated(api.list_change_requests(model["id"], OWNER_A))
        assert len(crs) == 2, "change requests are allowed to coexist"

    def test_occ_version_increments_on_every_mutation(self, api):
        """PRD §3.3: "Each successfully created change request increments the model's
        `version` by one — which is precisely why a second submission carrying the same
        expected version fails: the first submission itself advanced the model."
        PRD §3.3: "The officer's identity is recorded as `decided_by_user_id`, and the
        decision itself also increments the model's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
        """
        model = create_model(name="VerMon M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        v0 = model["version"]
        create_change_request(model["id"], "MINOR", v0, description="cr1")
        v1 = get_model(model["id"])["version"]
        assert v1 == v0 + 1, "first create increments by one"
        cr2 = create_change_request(model["id"], "MINOR", v1, description="cr2")
        v2 = get_model(model["id"])["version"]
        assert v2 == v1 + 1, "second create increments by one"
        decide_change_request(model["id"], cr2["id"], "APPROVE")
        v3 = get_model(model["id"])["version"]
        assert v3 == v2 + 1, "decide increments by one"

    def test_stale_version_checked_before_state_rules(self, api):
        """PRD §2.6: "The version check runs after resource existence has been
        established but before any state or business rule is evaluated."

        A change-request create against a RETIRED model with a stale version surfaces
        ERR_STALE_VERSION, not ERR_MODEL_ALREADY_RETIRED.

        Design: Corner/validations/stale_version_checked_before_state_rules
        """
        retired, _replacement = create_retired_pair()
        stale_version = retired["version"]  # any value the client might hold is stale here
        err = validate_error(
            api.create_change_request(
                retired["id"],
                {"change_type": "MINOR", "description": "stale and retired",
                 "expected_model_version": stale_version - 1},
                OWNER_A,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        assert err["error_id"] == "ERR_STALE_VERSION"

    def test_not_found_checked_before_occ(self, api):
        """PRD §2.8: "Every request passes through a fixed pipeline of validation
        stages, and a rejection at an earlier stage masks every later stage — the
        caller always sees the earliest applicable error."
        PRD §2.6: "The version check runs after resource existence has been established
        but before any state or business rule is evaluated."

        A change-request create against a non-existent model id surfaces ERR_NOT_FOUND
        regardless of the version value.

        Design: Corner/validations/not_found_checked_before_occ
        """
        model = create_model(name="PriNF M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        err = validate_error(
            api.create_change_request(
                NON_EXISTENT_UUID,
                {"change_type": "MINOR", "description": "ghost",
                 "expected_model_version": model["version"]},
                OWNER_A,
            ),
            ApiErrorId.ERR_NOT_FOUND,
        )
        assert err["error_id"] == "ERR_NOT_FOUND"


class TestChangeDecisionCalendarEffects:
    def test_major_change_approval_compresses_validation_due(self, api):
        """PRD §3.3: "Approving a `MAJOR` request compresses the model's revalidation
        calendar: `validation_due_at` becomes the earlier of its current value and
        three months from the decision time, so a major change can bring revalidation
        forward but never push it out."

        TIER_3 model registered at 2026-08-01 (due 2028-08-01) -> min(2028-08-01,
        2026-08-01 + 3 months) = 2026-11-01.

        Design: Corner/calculations/major_change_approval_compresses_validation_due
        """
        model = create_model(name="Major M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        assert_instant_equal(model["validation_due_at"], "2028-08-01T00:00:00Z", "initial due")
        cr = create_change_request(model["id"], "MAJOR", model["version"],
                                   description="rebuild feature pipeline")
        validate_success(api.decide_change_request(model["id"], cr["id"], {"decision": "APPROVE"}, OFFICER))
        after = validate_success(api.get_model(model["id"], OFFICER))
        assert_instant_equal(after["validation_due_at"], "2026-11-01T00:00:00Z",
                             "compressed validation_due_at")

    def test_minor_change_approval_does_not_compress_validation_due(self, api):
        """PRD §3.3: "Approving a `MINOR` request and rejecting either kind leave the
        calendar untouched."

        Design: Corner/calculations/minor_change_approval_does_not_compress_validation_due
        """
        model = create_model(name="Minor M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        cr = create_change_request(model["id"], "MINOR", model["version"], description="label change")
        validate_success(api.decide_change_request(model["id"], cr["id"], {"decision": "APPROVE"}, OFFICER))
        after = validate_success(api.get_model(model["id"], OFFICER))
        assert_instant_equal(after["validation_due_at"], "2028-08-01T00:00:00Z",
                             "MINOR approvals do not compress")
