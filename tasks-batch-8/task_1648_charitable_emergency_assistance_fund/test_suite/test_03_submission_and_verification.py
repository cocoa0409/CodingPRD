"""Submission preconditions, vendor guards, the verification lifecycle
(including the VERIFICATION_FAILED retry loop), and optimistic concurrency on
application-child writes."""
from test_helpers import (
    ApiErrorId,
    attach_document,
    complete_verification,
    complete_verification_payload,
    create_active_policy,
    create_application,
    create_duplication_check_payload,
    create_household,
    create_vendor,
    get_application,
    get_application_version,
    open_duplication_check,
    open_verification,
    setup_pending_decision,
    setup_submitted_application,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
    validate_paginated,
)

CW1 = TEST_USERS["caseworker_headers"]
CW2 = TEST_USERS["caseworker2_headers"]
PM1 = TEST_USERS["program_manager_headers"]


class TestSubmitGuards:
    def test_submit_without_active_policy_rejected(self, api):
        """PRD §3.3: "An eligibility policy must currently be `ACTIVE`, else
        `ERR_NO_ACTIVE_POLICY`."

        Design: Corner/validations/submit_without_active_policy_rejected
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        application = create_application(household["id"], vendor["id"])
        attach_document(application["id"], "EVICTION_NOTICE")
        resp = api.submit_application(application["id"], CW1)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY)

    def test_submit_requires_lease_ledger_when_policy_flags_it(self, api):
        """PRD §3.3: "Every document the active policy requires for the
        application's category must be attached, else `ERR_DOCUMENTS_INCOMPLETE`:
        a `RENT` application needs an `EVICTION_NOTICE` exactly when the policy's
        `require_eviction_notice` is set plus a `LEASE_LEDGER` exactly when
        `require_lease_ledger` is set, while a `UTILITY` application needs a
        `UTILITY_BILL` exactly when `require_utility_bill` is set."

        Design: Corner/validations/submit_requires_lease_ledger_when_policy_flags_it
        """
        create_active_policy(name="Strict", require_lease_ledger=True)
        vendor = create_vendor("LANDLORD")
        household = create_household()
        application = create_application(household["id"], vendor["id"])
        attach_document(application["id"], "EVICTION_NOTICE")
        resp = api.submit_application(application["id"], CW1)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)
        attach_document(application["id"], "LEASE_LEDGER")
        submitted = validate_success(api.submit_application(application["id"], CW1), 200)
        assert submitted["status"] == "SUBMITTED"

    def test_vendor_suspend_blocks_submit_and_double_suspend_rejected(self, api):
        """PRD §3.3: "And the application's vendor must be `ACTIVE`, else
        `ERR_VENDOR_SUSPENDED`."
        PRD §3.1: "A `ProgramManager` may suspend an `ACTIVE` vendor, moving it to
        `SUSPENDED`, and may reactivate a `SUSPENDED` vendor back to `ACTIVE`;
        calling either action from the wrong state fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/vendor_suspend_blocks_submit_and_double_suspend_rejected
        """
        create_active_policy()
        vendor = create_vendor("LANDLORD")
        household = create_household()
        application = create_application(household["id"], vendor["id"])
        attach_document(application["id"], "EVICTION_NOTICE")
        suspended = validate_success(api.suspend_vendor(vendor["id"], PM1), 200)
        assert suspended["status"] == "SUSPENDED"
        resp = api.submit_application(application["id"], CW1)
        validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)
        resp2 = api.suspend_vendor(vendor["id"], PM1)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
        reactivated = validate_success(api.reactivate_vendor(vendor["id"], PM1), 200)
        assert reactivated["status"] == "ACTIVE"

    def test_submit_from_withdrawn_terminal_lockdown(self, api):
        """PRD §3.3: "Submit from any state other than `INTAKE` fails with
        `ERR_INVALID_APPLICATION_STATE`."
        PRD §3.5: "Every withdrawal lands in the terminal `WITHDRAWN` state and
        bumps `version`; withdrawal attempted from any other state fails with
        `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/submit_from_withdrawn_terminal_lockdown
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        application = create_application(household["id"], vendor["id"])
        withdrawn = validate_success(api.withdraw_application(application["id"], CW1), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.submit_application(application["id"], CW1)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        assert get_application(application["id"])["status"] == "WITHDRAWN"


class TestVerificationLifecycle:
    def test_verification_complete_twice_rejected(self, api):
        """PRD §3.3: "Only a `PENDING` verification may be completed — anything
        else draws `ERR_INVALID_VERIFICATION_STATE` — and the completing
        caseworker must again differ from `intake_caseworker_id`."

        Design: Corner/state_machines/verification_complete_twice_rejected
        """
        ctx = setup_pending_decision(requested_amount_cents=5000)
        verification_id = ctx["verification"]["id"]
        assert ctx["verification"]["status"] == "PASSED"
        resp = api.complete_verification(
            verification_id, complete_verification_payload("FAILED"), CW2
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_STATE)
        verification = validate_success(api.get_verification(verification_id, CW1), 200)
        assert verification["status"] == "PASSED", "completed verification is terminal"
        assert get_application(ctx["application"]["id"])["status"] == "PENDING_DECISION"

    def test_withdraw_supersedes_pending_verification(self, api):
        """PRD §3.5: "Withdrawing from `UNDER_VERIFICATION` additionally
        supersedes any still-`PENDING` verification of the application to
        `SUPERSEDED`."

        Design: Corner/state_machines/withdraw_supersedes_pending_verification
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        app_id = ctx["application"]["id"]
        verification = open_verification(app_id, get_application_version(app_id))
        withdrawn = validate_success(api.withdraw_application(app_id, CW1), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        verification_after = validate_success(
            api.get_verification(verification["id"], CW1), 200
        )
        assert verification_after["status"] == "SUPERSEDED"

    def test_sod_verifier_cannot_be_intake_caseworker(self, api):
        """PRD §2.8: "the `Caseworker` who opens a vendor verification must differ
        from the application's `intake_caseworker_id`"
        PRD §2.8: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)."

        Design: Corner/validations/sod_verifier_cannot_be_intake_caseworker
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        app_id = ctx["application"]["id"]
        version = ctx["application"]["version"]
        resp = api.create_verification(
            app_id, {"expected_application_version": version}, CW1
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_application(app_id)["status"] == "SUBMITTED"
        verifications, meta = validate_paginated(
            api.list_verifications(CW1, params={"application_id": app_id})
        )
        assert meta["total_count"] == 0, "no verification may be created on SoD refusal"


class TestVerificationRetryCycle:
    def _failed_verification_setup(self):
        ctx = setup_submitted_application(requested_amount_cents=20000)
        app_id = ctx["application"]["id"]
        submitted_version = ctx["application"]["version"]
        first = open_verification(app_id, submitted_version)
        complete_verification(
            first["id"], "FAILED", outcome_notes="landlord unreachable"
        )
        failed_app = get_application(app_id)
        return ctx, first, submitted_version, failed_app

    def test_failed_verification_reopens_from_verification_failed(self, api):
        """PRD §3.3: "Verification opens from `SUBMITTED` or from
        `VERIFICATION_FAILED` — a second chance after a failed first attempt —
        and from nowhere else."
        PRD §3.3: "Opening creates a fresh VendorVerification in `PENDING`,
        copies the application's `vendor_id` onto it, records the acting operator
        as `verifier_id`, supersedes any still-`PENDING` earlier verification of
        the same application to `SUPERSEDED`, advances the application to
        `UNDER_VERIFICATION`, and bumps the application's `version`."

        Design: Difficulty/non_linear_state_machine/application_verification_retry_cycle
        """
        ctx, first, _, failed_app = self._failed_verification_setup()
        assert failed_app["status"] == "VERIFICATION_FAILED"
        second = open_verification(ctx["application"]["id"], failed_app["version"])
        assert second["status"] == "PENDING"
        assert second["id"] != first["id"], "a fresh verification record is created"
        first_after = validate_success(api.get_verification(first["id"], CW1), 200)
        assert first_after["status"] == "FAILED", "the FAILED record is retained"
        assert get_application(ctx["application"]["id"])["status"] == "UNDER_VERIFICATION"

    def test_retry_cycle_version_advances_and_completes_to_pending_decision(self, api):
        """PRD §3.3: "Verification opens from `SUBMITTED` or from
        `VERIFICATION_FAILED` — a second chance after a failed first attempt —
        and from nowhere else."
        PRD §2.5: "a `version` integer that starts at 1 when the resource is
        created and increments by exactly 1 on every mutation of that resource."
        PRD §3.3: "the server records it along with `completed_at` and any
        `outcome_notes`, and the application moves `UNDER_VERIFICATION →
        PENDING_DECISION`."

        Design: Difficulty/non_linear_state_machine/application_verification_retry_cycle
        """
        ctx, first, submitted_version, failed_app = self._failed_verification_setup()
        app_id = ctx["application"]["id"]
        assert failed_app["version"] > submitted_version, (
            "FAILED completion must bump the application version"
        )
        second = open_verification(app_id, failed_app["version"])
        assert get_application(app_id)["version"] > failed_app["version"], (
            "reopening a verification must bump the application version"
        )
        complete_verification(second["id"], "PASSED", confirmed_amount_cents=20000)
        assert get_application(app_id)["status"] == "PENDING_DECISION"


class TestOptimisticConcurrencyOnApplicationWrites:
    def test_occ_verification_create_stale_version_rejected(self, api):
        """PRD §2.7: "Creating a vendor verification
        (`POST /assistance/applications/{id}/verifications`) requires the request
        body to carry `expected_application_version`, holding the
        client-last-observed `version` of the application."
        PRD §2.7: "When the supplied value does not match the parent entity's
        current `version`, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_verification_create_stale_version_rejected
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        app_id = ctx["application"]["id"]
        stale_version = ctx["application"]["version"]
        # A legitimate duplication-check create advances the application version.
        open_duplication_check(app_id, stale_version)
        assert get_application_version(app_id) > stale_version
        resp = api.create_verification(
            app_id, {"expected_application_version": stale_version}, CW2
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        verifications, meta = validate_paginated(
            api.list_verifications(CW1, params={"application_id": app_id})
        )
        assert meta["total_count"] == 0, "stale write must not create a verification"

    def test_occ_duplication_check_create_stale_version_rejected(self, api):
        """PRD §2.7: "Opening a duplication check
        (`POST /assistance/applications/{id}/duplication-checks`) likewise
        requires `expected_application_version`."
        PRD §2.7: "When the supplied value does not match the parent entity's
        current `version`, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_duplication_check_create_stale_version_rejected
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        app_id = ctx["application"]["id"]
        stale_version = ctx["application"]["version"]
        # A legitimate verification create advances the application version.
        open_verification(app_id, stale_version)
        assert get_application_version(app_id) > stale_version
        resp = api.create_duplication_check(
            app_id,
            create_duplication_check_payload(stale_version),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
