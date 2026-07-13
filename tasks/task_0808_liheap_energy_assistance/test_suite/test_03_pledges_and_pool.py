"""Pledge creation, pool reservation/depletion, conservation, and pledge guards
(PRD §2.7, §3.1, §3.5, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_pool_conservation,
    new_funding_pool, new_enrolled_vendor, new_pending_vendor, new_household,
    new_utility_account, new_draft_application, submit_app, add_verified_income,
    setup_approved_application, add_utility_account, create_pledge_on, pool_version,
    create_pledge_payload, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["programadmin_headers"]


def _approved_ctx_submitted_only(api, pool_overrides=None, account_overrides=None,
                                 vendor=None):
    """Build an OPEN HEATING pool + enrolled vendor + household + account +
    a SUBMITTED (verified but NOT approved) application. Returns a context dict."""
    pool = new_funding_pool(api, **(pool_overrides or {}))
    vendor = vendor or new_enrolled_vendor(api)
    hh = new_household(api, annual_income_cents=1_700_000, heating_source="NATURAL_GAS")
    account = new_utility_account(api, hh["id"], vendor["id"], **(account_overrides or {}))
    app = new_draft_application(api, hh["id"])
    submit_app(api, app["id"], hh["id"])
    add_verified_income(api, app["id"], 1_700_000)
    return {"pool": pool, "pool_id": pool["id"], "vendor": vendor, "vendor_id": vendor["id"],
            "household_id": hh["id"], "account_id": account["id"], "application_id": app["id"]}


class TestPledgeReservesPoolAndStatus:
    def test_pledge_reserves_amount_and_reduces_available(self, api):
        """PRD §3.6: "On a successful create the pledge is set to `PLEDGED`, the pool's
        `reserved_cents` is increased by `pledged_amount_cents`, the pool's
        `available_cents` and `status` are re-derived (crossing into `LOW` or
        `DEPLETED` as the thresholds dictate), and the pool's `version` is bumped by one."

        Design: Difficulty/transitive_cascade/pledge_create_reserves_pool_status_chain
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 100000, "depletion_threshold_cents": 90000},
            account_overrides={"current_balance_cents": 25000})
        validate_success(create_pledge_on(api, ctx, pledge_type="HEATING",
                                           pledged_amount_cents=20000,
                                           benefit_period_start="2026-03-01T00:00:00Z",
                                           benefit_period_end="2026-03-20T00:00:00Z"),
                         expected_status=201)
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["reserved_cents"] == 20000
        assert pool["available_cents"] == 80000
        assert_pool_conservation(pool)

    def test_pledge_crossing_threshold_re_derives_status_low(self, api):
        """PRD §3.1: "when `available_cents` is above 0 but at or below
        `depletion_threshold_cents` the status is `LOW`; and when `available_cents` is
        strictly above `depletion_threshold_cents` the status is `OPEN`."

        Design: Difficulty/transitive_cascade/pledge_create_reserves_pool_status_chain
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 100000, "depletion_threshold_cents": 90000},
            account_overrides={"current_balance_cents": 25000})
        create_pledge_on(api, ctx, pledge_type="HEATING", pledged_amount_cents=20000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-20T00:00:00Z")
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["status"] == "LOW"


class TestPoolDepletionBoundary:
    def test_pledge_draining_to_zero_sets_depleted(self, api):
        """PRD §3.1: "Otherwise, when `available_cents` has reached exactly 0 the status
        is `DEPLETED`; when `available_cents` is above 0 but at or below
        `depletion_threshold_cents` the status is `LOW`; and when `available_cents` is
        strictly above `depletion_threshold_cents` the status is `OPEN`."

        Design: Difficulty/boundary_precision_check/pool_depleted_at_zero_available_boundary
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 20000, "depletion_threshold_cents": 5000},
            account_overrides={"current_balance_cents": 30000})
        create_pledge_on(api, ctx, pledged_amount_cents=20000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-15T00:00:00Z")
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["available_cents"] == 0
        assert pool["status"] == "DEPLETED"

    def test_pledge_against_depleted_pool_rejected(self, api):
        """PRD §3.6: "The pool must be neither `CLOSED` nor `DEPLETED`, or the create is
        rejected with `ERR_POOL_DEPLETED`."

        Design: Difficulty/boundary_precision_check/pool_depleted_at_zero_available_boundary
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 20000, "depletion_threshold_cents": 5000},
            account_overrides={"current_balance_cents": 30000})
        account2 = add_utility_account(api, ctx, account_number="OO-2", current_balance_cents=30000)
        create_pledge_on(api, ctx, pledged_amount_cents=20000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-15T00:00:00Z")
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], account2["id"], pool_version(api, ctx["pool_id"]),
            application_id=ctx["application_id"], pledged_amount_cents=1,
            benefit_period_start="2026-04-01T00:00:00Z", benefit_period_end="2026-04-15T00:00:00Z")
        validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_POOL_DEPLETED.value)


class TestPoolConservationOnCancel:
    def test_cancel_releases_reservation(self, api):
        """PRD §3.6: "Cancellation moves the pledge from `PLEDGED` to `CANCELLED`,
        releases the reservation by subtracting `pledged_amount_cents` from the pool's
        `reserved_cents`, re-derives the pool's `available_cents` and `status`, and
        bumps the pool's `version` by one."

        Design: Difficulty/compensating_invariant/pool_conservation_pledge_cancel
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 100000, "depletion_threshold_cents": 10000})
        pledge = validate_success(create_pledge_on(api, ctx, pledged_amount_cents=20000), expected_status=201)
        api.cancel_pledge(pledge["id"], CW)
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["reserved_cents"] == 0
        assert pool["available_cents"] == 100000

    def test_conservation_identity_holds_after_cancel(self, api):
        """PRD §2.7: "This identity — allocation equals available plus reserved plus
        disbursed — holds after every operation."

        Design: Difficulty/compensating_invariant/pool_conservation_pledge_cancel
        """
        ctx = setup_approved_application(
            api, pool_overrides={"total_allocation_cents": 100000, "depletion_threshold_cents": 10000})
        pledge = validate_success(create_pledge_on(api, ctx, pledged_amount_cents=20000), expected_status=201)
        cancelled = validate_success(api.cancel_pledge(pledge["id"], CW))
        assert cancelled["status"] == "CANCELLED"
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["disbursed_cents"] == 0
        assert_pool_conservation(pool)


class TestPledgeRequiresApprovedApplication:
    def test_pledge_on_submitted_application_rejected(self, api):
        """PRD §3.6: "When an `application_id` is present, the referenced application
        must be in `APPROVED` status, or the create is rejected with
        `ERR_APPLICATION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/pledge_requires_application_approved
        """
        ctx = _approved_ctx_submitted_only(api)
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
            application_id=ctx["application_id"], pledged_amount_cents=30000)
        validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value)

    def test_pledge_succeeds_once_application_approved(self, api):
        """PRD §3.6: "On a successful create the pledge is set to `PLEDGED`, the pool's
        `reserved_cents` is increased by `pledged_amount_cents`, the pool's
        `available_cents` and `status` are re-derived (crossing into `LOW` or
        `DEPLETED` as the thresholds dictate), and the pool's `version` is bumped by one."

        Design: Difficulty/cross_entity_state_dependency/pledge_requires_application_approved
        """
        ctx = _approved_ctx_submitted_only(api)
        api.approve_application(ctx["application_id"], CW)
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
            application_id=ctx["application_id"], pledged_amount_cents=30000)
        pledge = validate_success(api.create_pledge(payload, CW), expected_status=201)
        assert pledge["status"] == "PLEDGED"


class TestPledgeStateBeatsFiscal:
    def _depleted_pool_and_second_submitted_app(self, api):
        vendor = new_enrolled_vendor(api)
        ctx = setup_approved_application(
            api, vendor_overrides={"name": "PropanePlus", "vendor_type": "PROPANE"},
            pool_overrides={"total_allocation_cents": 20000, "depletion_threshold_cents": 5000},
            account_overrides={"current_balance_cents": 25000})
        create_pledge_on(api, ctx, pledged_amount_cents=20000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-20T00:00:00Z")  # pool now DEPLETED
        # second household with a SUBMITTED (not approved) application on the same pool
        hh2 = new_household(api, primary_applicant_name="Kim Lee", household_size=2,
                            annual_income_cents=1_500_000, heating_source="PROPANE")
        account2 = new_utility_account(api, hh2["id"], ctx["vendor_id"], account_number="PA-2",
                                       current_balance_cents=25000)
        app2 = new_draft_application(api, hh2["id"])
        submit_app(api, app2["id"], hh2["id"])
        return ctx, app2["id"], account2["id"]

    def test_state_check_reported_before_fiscal_check(self, api):
        """PRD §3.6: "When an `application_id` is present, the referenced application
        must be in `APPROVED` status, or the create is rejected with
        `ERR_APPLICATION_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_beats_fiscal
        """
        ctx, app2_id, account2_id = self._depleted_pool_and_second_submitted_app(api)
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], account2_id, pool_version(api, ctx["pool_id"]),
            application_id=app2_id, pledge_type="HEATING", pledged_amount_cents=5000,
            benefit_period_start="2026-03-01T00:00:00Z", benefit_period_end="2026-03-20T00:00:00Z")
        validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value)

    def test_pool_is_depleted_when_state_check_wins(self, api):
        """PRD §3.6: "The pool must be neither `CLOSED` nor `DEPLETED`, or the create is
        rejected with `ERR_POOL_DEPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_beats_fiscal
        """
        ctx, app2_id, account2_id = self._depleted_pool_and_second_submitted_app(api)
        pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
        assert pool["status"] == "DEPLETED"
        app2 = validate_success(api.get_application(app2_id, CW))
        assert app2["status"] == "SUBMITTED"


class TestBenefitPeriodOverlap:
    def test_overlapping_period_on_same_account_rejected(self, api):
        """PRD §3.6: "The coverage window must not overlap any existing `PLEDGED` or
        `PAID` pledge on the same `utility_account_id`, treating both windows as closed
        intervals so that sharing even a single day counts as an overlap, or the create
        is rejected with `ERR_BENEFIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pledge_benefit_period_closed_overlap
        """
        ctx = setup_approved_application(api, account_overrides={"current_balance_cents": 60000})
        create_pledge_on(api, ctx, pledged_amount_cents=15000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-20T00:00:00Z")
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
            application_id=ctx["application_id"], pledged_amount_cents=15000,
            benefit_period_start="2026-03-10T00:00:00Z", benefit_period_end="2026-03-30T00:00:00Z")
        validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_BENEFIT_PERIOD_OVERLAP.value)

    def test_disjoint_period_on_same_account_allowed(self, api):
        """PRD §3.6: "The coverage window must not overlap any existing `PLEDGED` or
        `PAID` pledge on the same `utility_account_id`, treating both windows as closed
        intervals so that sharing even a single day counts as an overlap, or the create
        is rejected with `ERR_BENEFIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pledge_benefit_period_closed_overlap
        """
        ctx = setup_approved_application(api, account_overrides={"current_balance_cents": 60000})
        create_pledge_on(api, ctx, pledged_amount_cents=15000,
                         benefit_period_start="2026-03-01T00:00:00Z",
                         benefit_period_end="2026-03-20T00:00:00Z")
        payload = create_pledge_payload(
            ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
            application_id=ctx["application_id"], pledged_amount_cents=15000,
            benefit_period_start="2026-04-01T00:00:00Z", benefit_period_end="2026-04-15T00:00:00Z")
        pledge = validate_success(api.create_pledge(payload, CW), expected_status=201)
        assert pledge["status"] == "PLEDGED"


def test_pledge_nonexistent_vendor_returns_invalid_reference(api):
    """PRD §3.6: "The referenced `vendor_id`, `funding_pool_id`, and
    `utility_account_id` must each resolve to an existing resource, or the create is
    rejected with `ERR_INVALID_REFERENCE`."

    Design: Corner/validations/pledge_nonexistent_vendor_returns_invalid_reference
    """
    ctx = setup_approved_application(api)
    payload = create_pledge_payload(
        NON_EXISTENT_UUID, ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
        application_id=ctx["application_id"], pledged_amount_cents=30000)
    validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_INVALID_REFERENCE.value)


def test_pledge_component_mismatch_returns_error(api):
    """PRD §3.6: "The `pledge_type` must map to the pool's `program_component`:
    `HEATING` maps to a `HEATING` pool, `COOLING` to a `COOLING` pool, both `CRISIS`
    and `RECONNECTION` to a `CRISIS` pool, and `ARREARAGE` to a `HEATING` pool; a
    mismatch is rejected with `ERR_POOL_COMPONENT_MISMATCH`."

    Design: Corner/validations/pledge_component_mismatch_returns_error
    """
    ctx = setup_approved_application(api)
    payload = create_pledge_payload(
        ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
        application_id=ctx["application_id"], pledge_type="COOLING", pledged_amount_cents=30000)
    validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_POOL_COMPONENT_MISMATCH.value)


def test_reconnection_pledge_on_connected_account_returns_error(api):
    """PRD §3.6: "A `RECONNECTION` pledge additionally requires that the utility
    account's `is_disconnected` be true, or the create is rejected with
    `ERR_ACCOUNT_NOT_DISCONNECTED`."

    Design: Corner/validations/reconnection_pledge_connected_account_returns_error
    """
    ctx = setup_approved_application(api)  # HEATING pool used for submit/approve
    cpool = new_funding_pool(api, program_component="CRISIS")
    payload = create_pledge_payload(
        ctx["vendor_id"], cpool["id"], ctx["account_id"], cpool["version"],
        application_id=ctx["application_id"], pledge_type="RECONNECTION", pledged_amount_cents=10000)
    validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_ACCOUNT_NOT_DISCONNECTED.value)


def test_pledge_unenrolled_vendor_returns_error(api):
    """PRD §3.6: "The vendor must be `ENROLLED`, or the create is rejected with
    `ERR_VENDOR_NOT_ENROLLED`."

    Design: Corner/validations/pledge_unenrolled_vendor_returns_error
    """
    pending_vendor = new_pending_vendor(api, name="PendingGas")
    ctx = _approved_ctx_submitted_only(api, vendor=pending_vendor)
    api.approve_application(ctx["application_id"], CW)
    payload = create_pledge_payload(
        pending_vendor["id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
        application_id=ctx["application_id"], pledged_amount_cents=30000)
    validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_VENDOR_NOT_ENROLLED.value)


def test_pledge_exceeds_available_returns_error(api):
    """PRD §3.6: "The `pledged_amount_cents` must be at or below the pool's
    `available_cents`, or the create is rejected with `ERR_BENEFIT_EXCEEDS_AVAILABLE`."

    Design: Corner/validations/pledge_exceeds_available_returns_error
    """
    ctx = setup_approved_application(
        api, pool_overrides={"total_allocation_cents": 30000, "depletion_threshold_cents": 5000},
        account_overrides={"current_balance_cents": 80000})
    payload = create_pledge_payload(
        ctx["vendor_id"], ctx["pool_id"], ctx["account_id"], pool_version(api, ctx["pool_id"]),
        application_id=ctx["application_id"], pledged_amount_cents=50000)
    validate_error(api.create_pledge(payload, CW), ApiErrorId.ERR_BENEFIT_EXCEEDS_AVAILABLE.value)
    pool = validate_success(api.get_funding_pool(ctx["pool_id"], CW))
    assert pool["available_cents"] == 30000


def test_enroll_already_enrolled_vendor_rejected(api):
    """PRD §3.5: "A vendor agent (or an administrator) then enrolls the vendor, moving
    it from `PENDING` to `ENROLLED`; enrollment requires the vendor be in `PENDING`
    status."
    PRD §2.9: "Then, for state-transition endpoints, the generic state guard — a target
    not in a state that permits the transition yields `ERR_INVALID_STATE` (409) unless
    a more specific state rule below names a different code."

    Design: Corner/state_machines/vendor_enroll_twice_returns_invalid_state
    """
    vendor = new_enrolled_vendor(api, name="TwiceGas")
    validate_error(api.enroll_vendor(vendor["id"], PA), ApiErrorId.ERR_INVALID_STATE.value)
