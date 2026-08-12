"""Dividends on participating policies and optimistic concurrency control."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_funded_policy,
    create_issued_policy,
    get_policy,
    get_success_data,
    make_policyholder_headers,
    set_clock,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _ph(bundle):
    return make_policyholder_headers(bundle["insured"]["id"])


def _participating_bundle(date_of_birth="1970-02-02"):
    return create_issued_policy(
        product_type="WHOLE_LIFE_PARTICIPATING", participating=True,
        premium_mode="ANNUAL", base_rate=60, date_of_birth=date_of_birth)


class TestPaidUpAdditionsConservation:
    def test_paid_up_additions_credits_accumulation_and_face(self, api):
        """PRD §3.7: "Under `PAID_UP_ADDITIONS`, the declared amount buys additional paid-up face
        using the same conversion schedule as the reduced paid-up calculation
        of §3.8 — the age-banded rate (0.30 below age 40, 0.40 for ages 40
        through 49, 0.50 for ages 50 through 59, 0.65 at age 60 and above)
        plus the substandard loading — so the face addition is the declared
        amount divided by the adjusted rate, rounded half-up to whole cents.
        The full declared amount is applied into
        `dividend_accumulation_cents`, and the policy's `face_amount_cents`
        increases by the computed face addition."

        Insured born 1970-02-02; declaration at 2026-05-01 -> attained age 56
        -> rate 0.50 -> face addition = 5000000 / 0.50 = 10000000.

        Design: Difficulty/compensating_invariant/dividend_paid_up_additions_conserves_total_value
        """
        bundle = _participating_bundle()
        policy_id = bundle["policy"]["id"]
        before = get_policy(policy_id)
        assert before["dividend_option"] == "CASH", "option defaults to CASH (PRD §3.7)"

        changed = validate_success(api.change_dividend_option(
            policy_id, "PAID_UP_ADDITIONS", before["version"], _ph(bundle)))
        assert changed["dividend_option"] == "PAID_UP_ADDITIONS"

        decl = validate_success(api.create_dividend_declaration(
            policy_id, 1, 5_000_000, ADMIN), expected_status=201)
        assert decl["status"] == "APPLIED"
        assert decl["applied_amount_cents"] == 5_000_000

        after = get_policy(policy_id)
        assert after["dividend_accumulation_cents"] == (
            before["dividend_accumulation_cents"] + 5_000_000)
        assert after["face_amount_cents"] == before["face_amount_cents"] + 10_000_000

    def test_paid_up_additions_age_band_below_40(self, api):
        """PRD §3.7: "the face addition is the declared amount divided by the adjusted rate, rounded
        half-up to whole cents" with "the age-banded rate (0.30 below age 40, 0.40 for ages 40 through 49, 0.50 for
        ages 50 through 59, 0.65 at age 60 and above)". And: "applying moves it to `APPLIED` and increments the policy's `version`."

        Insured born 1990-01-01; declaration at 2026-05-01 -> attained age 36
        -> rate 0.30 -> face addition = round(5000000 / 0.30) = 16666667.

        Design: Difficulty/compensating_invariant/dividend_paid_up_additions_conserves_total_value
        """
        bundle = _participating_bundle(date_of_birth="1990-01-01")
        policy_id = bundle["policy"]["id"]
        before = get_policy(policy_id)
        validate_success(api.change_dividend_option(
            policy_id, "PAID_UP_ADDITIONS", before["version"], _ph(bundle)))
        mid_version = get_policy(policy_id)["version"]

        decl = validate_success(api.create_dividend_declaration(
            policy_id, 1, 5_000_000, ADMIN), expected_status=201)
        assert decl["status"] == "APPLIED"

        after = get_policy(policy_id)
        assert after["face_amount_cents"] == before["face_amount_cents"] + 16_666_667
        assert after["dividend_accumulation_cents"] == (
            before["dividend_accumulation_cents"] + 5_000_000)
        assert after["version"] == mid_version + 1, (
            "applying the declaration increments the policy's version")


class TestDividendOptionOcc:
    def test_stale_version_after_declaration_rejected(self, api):
        """PRD §3.7: "Because applying a declaration mutates the policy and advances its `version`,
        a dividend-option change submitted against the pre-declaration version
        is rejected as stale — the intended serialization point between
        declaration and option change."
        PRD §2.10: "If the policy's current `version` does not equal `expected_policy_version` —
        because another writer has advanced the policy since that read, for
        example by recording a payment or applying a dividend — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
        applied."

        Design: Corner/endpoints/occ_stale_version_on_dividend_option
        """
        bundle = _participating_bundle()
        policy_id = bundle["policy"]["id"]
        observed_version = get_policy(policy_id)["version"]
        # A dividend declaration applies immediately and advances the version.
        get_success_data(api.create_dividend_declaration(policy_id, 1, 100_000, ADMIN))

        resp = api.change_dividend_option(policy_id, "ACCUMULATE_AT_INTEREST",
                                          observed_version, _ph(bundle))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # The current version still succeeds.
        fresh_version = get_policy(policy_id)["version"]
        ok = validate_success(api.change_dividend_option(
            policy_id, "ACCUMULATE_AT_INTEREST", fresh_version, _ph(bundle)))
        assert ok["dividend_option"] == "ACCUMULATE_AT_INTEREST"


class TestModeChangeOcc:
    def test_mode_change_increments_version_and_stale_retry_rejected(self, api):
        """PRD §3.4: "the system recomputes `modal_premium_cents` under the pinned arithmetic of
        §3.3 using the new mode's factor, applies the new modal premium to
        future cycles, and increments the policy's `version` by one."
        PRD §2.10: "If the policy's current `version` does not equal `expected_policy_version` —
        because another writer has advanced the policy since that read, for
        example by recording a payment or applying a dividend — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
        applied."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_mode_change
        """
        bundle = create_issued_policy(premium_mode="MONTHLY")
        policy_id = bundle["policy"]["id"]
        observed_version = get_policy(policy_id)["version"]

        first = validate_success(api.change_mode(policy_id, "ANNUAL",
                                                 observed_version, AGENT))
        assert first["version"] == observed_version + 1
        assert first["premium_mode"] == "ANNUAL"

        resp = api.change_mode(policy_id, "QUARTERLY", observed_version, AGENT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        still = get_policy(policy_id)
        assert still["premium_mode"] == "ANNUAL", "a stale write applies no change"
        assert still["version"] == observed_version + 1


class TestNonParticipatingDividend:
    def test_declaration_on_non_participating_product_rejected(self, api):
        """PRD §3.7: "Declaring against a non-participating product is rejected with
        `ERR_PRODUCT_NOT_PARTICIPATING` (HTTP 422)."

        Design: Corner/errors/dividend_declaration_on_non_participating
        """
        bundle = create_issued_policy(
            product_type="WHOLE_LIFE_NON_PARTICIPATING", participating=False,
            premium_mode="ANNUAL")
        resp = api.create_dividend_declaration(bundle["policy"]["id"], 1,
                                               100_000, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_PARTICIPATING)
