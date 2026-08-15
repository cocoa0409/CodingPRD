"""Corner queue: physician creation defaults, treasury debit, policy singleton, ownership precision."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_physician,
    create_physician,
    create_physician_payload,
    create_policy,
    create_shareholder,
    get_physician,
    get_policy,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestPhysicianCreateAssociateDefaults:
    def test_associate_defaults(self, api):
        """PRD §3.1: "Any other physician enters as an `ASSOCIATE` with zero shares."
        PRD §3.1: "The `standing` dimension starts at `GOOD_STANDING`"
        PRD §2.4: "Every entity carries an `id` that is a server-minted UUID with no
        type prefix, a `created_at` timestamp, an `updated_at` timestamp refreshed on
        every mutation, and a `version` integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that entity."

        Design: Corner/entities/physician_create_associate_defaults
        """
        create_policy(total_shares_authorized=1000000)
        resp = api.create_physician(
            create_physician_payload(full_name="Dr New", hire_date="2024-03-01T00:00:00Z"),
            TEST_USERS["board_admin_headers"],
        )
        physician = validate_success(resp, 201)
        assert_physician(physician)
        assert physician["partnership_status"] == "ASSOCIATE"
        assert physician["standing"] == "GOOD_STANDING"
        assert physician["shares_held"] == 0
        assert physician["capital_account_balance_cents"] == 0
        assert physician["version"] == 1
        assert is_valid_uuid(physician["id"])


class TestPhysicianCreateFoundingShareholder:
    def test_founding_shareholder_debits_treasury(self, api):
        """PRD §3.1: "A physician created with `founding_shareholder` set to true
        enters directly as a `SHAREHOLDER` holding `initial_shares` — which must then
        be at least 1 — and those shares are debited from treasury"
        PRD §3.1: "Treasury shares follow the companion rule:
        `total_shares_authorized` minus the sum of `shares_held` over all physicians"

        Design: Corner/entities/physician_create_founding_shareholder_debits_treasury
        """
        create_policy(total_shares_authorized=1000000)
        resp = api.create_physician(
            create_physician_payload(
                full_name="Dr F", hire_date="2010-06-01T00:00:00Z",
                founding_shareholder=True, initial_shares=500,
            ),
            TEST_USERS["board_admin_headers"],
        )
        physician = validate_success(resp, 201)
        assert physician["partnership_status"] == "SHAREHOLDER"
        assert physician["shares_held"] == 500
        assert get_policy()["treasury_shares"] == 999500


class TestPhysicianMissingRequiredField:
    def test_missing_hire_date_rejected(self, api):
        """PRD §2.7: "Second, request shape: required fields present, enum values
        valid, amounts positive integers, and the payload sub-fields required by the
        motion type present (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "A `BoardAdmin` onboards a physician with `full_name`, `hire_date`,
        and optionally `specialty`, `founding_shareholder`, and `initial_shares`."

        Design: Corner/entities/physician_missing_required_field_rejected
        """
        create_policy(total_shares_authorized=1000000)
        resp = api.create_physician({"full_name": "Dr NoHire"}, TEST_USERS["board_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPhysicianGetNotFound:
    def test_get_nonexistent_physician_returns_404(self, api):
        """PRD §2.7: "Fifth, existence: path identifiers are validated left to right,
        and foreign keys referenced in the body must resolve (`ERR_NOT_FOUND`)."

        Design: Corner/entities/physician_get_not_found_returns_404
        """
        create_policy(total_shares_authorized=1000000)
        resp = api.get_physician(NON_EXISTENT_UUID, TEST_USERS["board_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPolicySingleton:
    def test_second_create_rejected(self, api):
        """PRD §2.8: "Exactly one `GovernancePolicy` may exist. Its `singleton_key` is
        always `GLOBAL`, and attempting to create a second policy is rejected with
        `ERR_POLICY_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/entities/policy_singleton_second_create_rejected
        """
        create_policy(total_shares_authorized=1000000)
        resp = api.create_policy(
            {"total_shares_authorized": 500}, TEST_USERS["board_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_EXISTS)


class TestPhysicianOwnershipPctPrecision:
    def test_ownership_pct_six_decimal_round_half_up(self, api):
        """PRD §3.1: "`ownership_pct` is the physician's `shares_held` divided by total
        shares outstanding — the sum of `shares_held` across all physicians whose
        `partnership_status` is not `EXITED` — rounded half-up to 6 decimal places, and
        defined as 0 when no shares are outstanding."
        1000/9000 = 0.1111111... -> 0.111111; 8000/9000 = 0.8888888... -> 0.888889.

        Design: Corner/entities/physician_ownership_pct_six_decimal_precision
        """
        create_policy(total_shares_authorized=1000000)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        y = create_shareholder("Dr Y", 8000, "2011-01-01T00:00:00Z")
        assert get_physician(x["id"])["ownership_pct"] == pytest.approx(0.111111, abs=1e-9)
        assert get_physician(y["id"])["ownership_pct"] == pytest.approx(0.888889, abs=1e-9)
