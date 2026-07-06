"""Client creation, defaults, computed tier volume, and not-found reads.

Note: the corner instance entities/create_close_task_negative_weight_422 is
SKIPPED. PRD §3.4 requires CloseTask weight to be "an integer `weight` of at
least 1" but never names which error a weight of 0 yields; the §5 table lists
ERR_NEGATIVE_AMOUNT only as a code, and PRD §2.9 routes a generic non-positive
field to ERR_INVALID_REQUEST. Two PRD-only implementers could legitimately return
either code, so the asserted ERR_NEGATIVE_AMOUNT outcome is not uniquely derivable
(Core rule).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID,
    create_client_payload,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]


class TestClientCreation:
    def test_create_client_minimal_required_fields(self, api):
        """PRD §3.1: "the client begins life with `onboarding_status` of `LEAD` and
        `engagement_status` of `PROSPECT`."

        Design: Corner/entities/create_client_minimal_required_fields_201
        """
        resp = api.create_client(
            create_client_payload(legal_name="New Co", retainer_tier="ESSENTIALS"), CFO)
        data = validate_success(resp, expected_status=201)
        assert data["onboarding_status"] == "LEAD"
        assert data["engagement_status"] == "PROSPECT"
        assert data["catchup_active"] is False
        assert data["version"] == 1

    def test_create_client_missing_retainer_tier_rejected(self, api):
        """PRD §3.1: "a `CFO` (or a `PlatformAdmin`) creates one by supplying the
        `legal_name`, the two-letter uppercase `state_code` of incorporation, and
        the `retainer_tier`, which must be one of `ESSENTIALS`, `GROWTH`, or `CFO`."
        PRD §2.9: "generic request-shape validation that catches a missing or
        wrong-typed field with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_client_missing_required_retainer_tier_400
        """
        resp = api.create_client(
            {"legal_name": "No Tier Co", "state_code": "CA"}, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_client_invalid_tier_enum_rejected(self, api):
        """PRD §3.1: "the `retainer_tier`, which must be one of `ESSENTIALS`,
        `GROWTH`, or `CFO`."
        PRD §2.9: "generic request-shape validation that catches a missing or
        wrong-typed field with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_client_invalid_tier_enum_400
        """
        resp = api.create_client(
            {"legal_name": "Bad Tier", "state_code": "CA", "retainer_tier": "PLATINUM"}, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_covenant_floor_defaults_to_zero(self, api):
        """PRD §3.1: "An optional `covenant_floor_cents` may be supplied to declare
        the minimum projected cash balance the client's bank covenant requires; when
        omitted it is zero."

        Design: Corner/entities/client_covenant_floor_default_zero
        """
        resp = api.create_client(
            create_client_payload(legal_name="Default Floor", retainer_tier="GROWTH"), CFO)
        data = validate_success(resp, expected_status=201)
        assert data["covenant_floor_cents"] == 0

    def test_included_txn_count_computed_from_growth_tier(self, api):
        """PRD §2.5: "Its `included_txn_count` is copied from the tier table the
        moment `retainer_tier` is set, taking the value 200 for `ESSENTIALS`, 500
        for `GROWTH`, and 1200 for `CFO`."

        Design: Corner/entities/client_included_txn_count_computed_from_tier
        """
        resp = api.create_client(
            create_client_payload(legal_name="Growth Co", retainer_tier="GROWTH"), CFO)
        data = validate_success(resp, expected_status=201)
        assert data["included_txn_count"] == 500


class TestClientRead:
    def test_get_missing_client_not_found(self, api):
        """PRD §2.8: "the first identifier that does not resolve to an existing
        resource causes an immediate `ERR_NOT_FOUND`."

        Design: Corner/entities/get_client_not_found_404
        """
        resp = api.get_client(NON_EXISTENT_UUID, CFO)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestMonthlyClosePeriodValidation:
    def test_create_close_bad_month_rejected(self, api):
        """PRD §3.4: "The `period_month` must be an integer from 1 through 12, and a
        month outside that range is rejected with `ERR_INVALID_PERIOD`."

        Design: Corner/entities/create_monthly_close_bad_month_422
        """
        client = get_success_data(api.create_client(
            create_client_payload(legal_name="Per Co", retainer_tier="ESSENTIALS"), CFO))
        resp = api.create_monthly_close(
            client["id"], {"period_year": 2026, "period_month": 13, "txn_count": 5},
            TEST_USERS["bookkeeper_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)
