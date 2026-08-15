"""Rate schedule drafting, tap creation quoting, and tap setup lifecycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_tap,
    create_active_member,
    create_area,
    create_district,
    create_rate_schedule_payload,
    create_tap_payload,
    get_success_data,
    setup_district_with_schedule,
    setup_member_with_installed_tap,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, DIRECTOR, FIELD, TREASURER


class TestRateScheduleDrafting:
    def test_tier2_cap_must_exceed_included_gallons(self, api):
        """PRD section 3.1: "Draft sanity is checked at creation: `tier2_cap_gallons`
        must be strictly greater than `included_gallons` and all rates strictly
        positive, else `ERR_RATE_SCHEDULE_INVALID` (HTTP 422)."

        Design: Corner/validations/rate_schedule_invalid_tier_cap_rejected
        """
        district = create_district(district_name="VE")
        payload = create_rate_schedule_payload(included_gallons=10_000, tier2_cap_gallons=10_000)
        resp = api.create_rate_schedule(district["id"], payload, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_INVALID, expected_status=422)


class TestTapFeeQuoting:
    def test_tap_fee_quoted_from_member_class(self, api):
        """PRD section 3.2: "Tap creation by a `BillingClerk` takes the `member_id`
        and an optional `meter_size` (`FIVE_EIGHTS_INCH`, `THREE_QUARTER_INCH`,
        `ONE_INCH`, or `TWO_INCH`, defaulting to `FIVE_EIGHTS_INCH`) and quotes
        `tap_fee_cents` from the district's currently adopted schedule's
        `tap_fee_schedule` for the member's class, with `tap_fee_paid_cents`
        starting at 0 and status `FEE_PENDING`."

        Design: Corner/entities/tap_fee_quoted_from_member_class
        """
        district, schedule = setup_district_with_schedule()
        area = create_area(district["id"])
        res_member = create_active_member(district["id"], area["id"], member_class="RESIDENTIAL")
        com_member = create_active_member(district["id"], area["id"], member_class="COMMERCIAL")

        res_tap = get_success_data(
            api.create_tap(district["id"], create_tap_payload(res_member["id"]), CLERK),
            expected_status=201,
        )
        com_tap = get_success_data(
            api.create_tap(district["id"], create_tap_payload(com_member["id"]), CLERK),
            expected_status=201,
        )
        assert_tap(res_tap)
        assert_tap(com_tap)
        assert res_tap["tap_fee_cents"] == 75_000, (
            f"RESIDENTIAL tap fee must come from the adopted schedule, got {res_tap['tap_fee_cents']}"
        )
        assert com_tap["tap_fee_cents"] == 150_000, (
            f"COMMERCIAL tap fee must come from the adopted schedule, got {com_tap['tap_fee_cents']}"
        )
        for tap in (res_tap, com_tap):
            assert tap["status"] == "FEE_PENDING"
            assert tap["tap_fee_paid_cents"] == 0

    def test_tap_create_without_adopted_schedule_rejected(self, api):
        """PRD section 3.2: "Quoting requires an adopted schedule to exist; if the
        district has none, creation fails with `ERR_NO_ACTIVE_RATE_SCHEDULE`
        (HTTP 409)."

        Design: Corner/state_machines/bill_without_active_schedule_fails
        """
        district = create_district(district_name="DJ")
        area = create_area(district["id"])
        member = create_active_member(district["id"], area["id"])
        # A DRAFT schedule exists but is not adopted — still no adopted schedule.
        get_success_data(
            api.create_rate_schedule(district["id"], create_rate_schedule_payload(), DIRECTOR),
            expected_status=201,
        )
        resp = api.create_tap(district["id"], create_tap_payload(member["id"]), CLERK)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_SCHEDULE, expected_status=409)


class TestTapInstallAndAbandon:
    def test_install_meter_on_unpaid_fee_rejected(self, api):
        """PRD section 3.2: "Installation demands the fee fully paid (attempting it
        on a `FEE_PENDING` tap surfaces `ERR_TAP_FEE_UNPAID`, HTTP 402)".

        Design: Corner/errors/error_tap_fee_unpaid_trigger
        """
        district, schedule = setup_district_with_schedule()
        area = create_area(district["id"])
        member = create_active_member(district["id"], area["id"])
        tap = get_success_data(
            api.create_tap(district["id"], create_tap_payload(member["id"]), CLERK),
            expected_status=201,
        )
        assert tap["status"] == "FEE_PENDING"
        resp = api.install_meter(district["id"], tap["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_TAP_FEE_UNPAID, expected_status=402)
        after = get_success_data(api.get_tap(district["id"], tap["id"], FIELD))
        assert after["status"] == "FEE_PENDING"

    def test_abandon_allowed_without_billing_history(self, api):
        """PRD section 3.2: "A tap that was never put into service may be abandoned
        by a `BillingClerk` (`FEE_PENDING` or `PAID → ABANDONED`) only while no
        invoice exists for it; otherwise `ERR_TAP_HAS_BILLING_HISTORY` (HTTP 409)."
        A FEE_PENDING tap with no invoice abandons cleanly.

        Design: Corner/state_machines/tap_abandon_with_billing_history_rejected
        (success half only — the blocked half is not uniquely derivable: PRD
        scopes the named error to never-in-service taps and section 2.7 pins
        state-legality ahead of business rules without naming the generic
        invalid-state error id, so an INSTALLED tap's abandon outcome is not
        pinned by PRD prose)
        """
        district, schedule = setup_district_with_schedule()
        area = create_area(district["id"])
        member = create_active_member(district["id"], area["id"], legal_name="MB")
        fresh_tap = get_success_data(
            api.create_tap(district["id"], create_tap_payload(member["id"]), CLERK),
            expected_status=201,
        )
        assert fresh_tap["status"] == "FEE_PENDING"

        abandoned = get_success_data(api.abandon_tap(district["id"], fresh_tap["id"], CLERK))
        assert abandoned["status"] == "ABANDONED"
