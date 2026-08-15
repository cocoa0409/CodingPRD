"""Alternative-commute incentive program: enrollment gates and redemption."""
from test_helpers import (
    ApiErrorId,
    accrue_days,
    create_patron,
    enroll_incentive,
    get_incentive_account,
    make_commuter_headers,
    setup_incentive_account,
    validate_error,
    validate_success,
)


class TestEnrollment:
    def test_incentive_enrollment_drive_alone_rejected(self, api):
        """PRD §3.9: "Patrons whose `primary_commute_mode` is `DRIVE_ALONE`
        are ineligible — enrollment is rejected with
        `ERR_INELIGIBLE_COMMUTE_MODE` (HTTP 403)."

        Design: Corner/validations/incentive_enrollment_drive_alone_rejected
        """
        patron = create_patron(full_name="DA", campus_role="STAFF",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        resp = api.create_incentive_account(
            {"patron_id": patron["id"]}, make_commuter_headers(patron["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_COMMUTE_MODE, 403)

    def test_incentive_account_second_enroll_rejected(self, api):
        """PRD §3.9: "Each patron may hold exactly one account; a duplicate
        enrollment is rejected with `ERR_ACCOUNT_EXISTS` (HTTP 409)."

        Design: Corner/entities/incentive_account_second_enroll_rejected
        """
        ctx = setup_incentive_account(name="M", commute_mode="TRANSIT")
        resp = api.create_incentive_account(
            {"patron_id": ctx["patron"]["id"]},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_EXISTS, 409)


class TestRedemptionBoundary:
    def test_redemption_exact_block_succeeds(self, api):
        """PRD §3.9: "Redemption requires `points_balance` to be at least
        `blocks * 500` — equality is sufficient; otherwise the request is
        rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422). On redemption
        `points_balance` decreases by `blocks * 500` and `credit_balance_cents`
        increases by `blocks * 2500`."

        Design: Difficulty/boundary_precision_check/redemption_block_boundary_500_vs_490
        """
        # 31 + 19 accrued days = 50 days * 10 points = exactly 500 points.
        ctx = setup_incentive_account(name="M1", commute_mode="TRANSIT",
                                      accrued_days=(31, 19))
        resp = api.redeem_incentive(
            ctx["account"]["id"], {"blocks": 1},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        account = validate_success(resp, 200)
        assert account["points_balance"] == 0, (
            f"500 points exactly meets the block threshold, "
            f"got {account['points_balance']}"
        )
        assert account["credit_balance_cents"] == 2500, (
            f"one block yields 2500 cents, got {account['credit_balance_cents']}"
        )

    def test_redemption_below_block_rejected(self, api):
        """PRD §3.9: "Redemption requires `points_balance` to be at least
        `blocks * 500` — equality is sufficient; otherwise the request is
        rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/redemption_block_boundary_500_vs_490
        """
        # 31 + 18 accrued days = 49 days * 10 points = 490 points.
        ctx = setup_incentive_account(name="M2", commute_mode="BIKE",
                                      accrued_days=(31, 18))
        resp = api.redeem_incentive(
            ctx["account"]["id"], {"blocks": 1},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS, 422)
        account = get_incentive_account(ctx["account"]["id"])
        assert account["points_balance"] == 490, (
            "a rejected redemption must not debit points"
        )
        assert account["credit_balance_cents"] == 0
