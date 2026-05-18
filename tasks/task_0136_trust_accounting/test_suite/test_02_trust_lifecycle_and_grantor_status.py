"""Trust lifecycle: create / activate / revoke / terminate, plus
grantor-status compatibility — PRD §3.1, §2.11."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_asset,
    add_beneficiary,
    add_tax_year,
    add_trustee,
    advance_clock_to,
    assert_trust,
    assert_trust_invariants,
    begin_close_tax_year,
    create_trust,
    create_trust_payload,
    finalize_tax_year,
    iso_instant_utc,
    patch_trust_payload,
    re_get_trust,
    setup_activatable_trust,
    setup_active_trust,
    setup_active_trust_with_principal,
    setup_closed_tax_year,
    setup_draft_trust,
    validate_error,
    validate_success,
)


# ===========================================================================
# Trust creation — PRD §3.1
# ===========================================================================
class TestTrustCreation:

    def test_create_trust_starts_in_draft(self, api, grantor_headers):
        """PRD §3.1: "The new Trust enters DRAFT status, its
        grantor_user_id is pinned to the creator's X-User-ID, and its
        principal_balance, income_balance, and gst_exemption_used all
        initialize to 0."

        Claim: created trust starts in DRAFT with zero balances.
        """
        resp = api.create_trust(
            create_trust_payload(), grantor_headers,
        )
        trust = validate_success(resp, 201)
        assert_trust(trust)
        assert trust["status"] == "DRAFT"
        assert trust["principal_balance"] == 0
        assert trust["income_balance"] == 0
        assert trust["gst_exemption_used"] == 0

    def test_create_trust_pins_grantor_user_id(
        self, api, grantor_headers,
    ):
        """PRD §3.1: "its grantor_user_id is pinned to the creator's
        X-User-ID".

        Claim: Trust.grantor_user_id equals the caller's X-User-ID.
        """
        resp = api.create_trust(
            create_trust_payload(), grantor_headers,
        )
        trust = validate_success(resp, 201)
        assert trust["grantor_user_id"] == grantor_headers["X-User-ID"]


# ===========================================================================
# Grantor-status compatibility — PRD §3.1
# ===========================================================================
class TestGrantorStatusCompatibility:

    def test_grantor_status_incompatible_irrevocable_without_powers(
        self, api, grantor_headers,
    ):
        """PRD §3.1: "A GRANTOR tax status is forbidden when the
        trust_type is IRREVOCABLE and has_grantor_powers is false;
        that combination is rejected with
        ERR_GRANTOR_STATUS_INCOMPATIBLE and HTTP 422."

        Claim: IRREVOCABLE + GRANTOR + has_grantor_powers=false ->
        ERR_GRANTOR_STATUS_INCOMPATIBLE / 422.
        """
        resp = api.create_trust(
            create_trust_payload(
                trust_type="IRREVOCABLE",
                grantor_tax_status="GRANTOR",
                has_grantor_powers=False,
            ),
            grantor_headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_GRANTOR_STATUS_INCOMPATIBLE.value,
        )

    def test_grantor_status_permitted_for_revocable(
        self, api, grantor_headers,
    ):
        """PRD §3.1: "The GRANTOR tax status is permitted whenever the
        trust is either REVOCABLE, or IRREVOCABLE with
        has_grantor_powers set to true."

        Claim: REVOCABLE + GRANTOR is allowed.
        """
        resp = api.create_trust(
            create_trust_payload(
                trust_type="REVOCABLE",
                grantor_tax_status="GRANTOR",
                has_grantor_powers=False,
            ),
            grantor_headers,
        )
        trust = validate_success(resp, 201)
        assert trust["trust_type"] == "REVOCABLE"
        assert trust["grantor_tax_status"] == "GRANTOR"

    def test_grantor_status_permitted_for_irrevocable_with_powers(
        self, api, grantor_headers,
    ):
        """PRD §3.1: "The GRANTOR tax status is permitted whenever the
        trust is either REVOCABLE, or IRREVOCABLE with
        has_grantor_powers set to true."

        Claim: IRREVOCABLE + GRANTOR + has_grantor_powers=true is OK.
        """
        resp = api.create_trust(
            create_trust_payload(
                trust_type="IRREVOCABLE",
                grantor_tax_status="GRANTOR",
                has_grantor_powers=True,
            ),
            grantor_headers,
        )
        trust = validate_success(resp, 201)
        assert trust["trust_type"] == "IRREVOCABLE"
        assert trust["has_grantor_powers"] is True


# ===========================================================================
# Activation preconditions — PRD §3.1
# ===========================================================================
class TestActivationPreconditions:

    def test_activation_requires_primary_trustee(self, api):
        """PRD §3.1: "There must be exactly one Trustee record under
        the trust with is_primary set to true and status equal to
        ACTIVE; if not, activation fails with
        ERR_NO_PRIMARY_TRUSTEE."

        Claim: activate with zero trustees -> ERR_NO_PRIMARY_TRUSTEE.
        """
        scenario = setup_draft_trust()
        # No trustees, no beneficiary, no tax year.
        resp = api.activate_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRIMARY_TRUSTEE.value)

    def test_activation_requires_beneficiary(self, api):
        """PRD §3.1: "There must be at least one Beneficiary record
        under the trust with status equal to ACTIVE; otherwise
        activation fails with ERR_NO_BENEFICIARY."

        Claim: trust with primary trustee but no beneficiary ->
        ERR_NO_BENEFICIARY at activation.
        """
        scenario = setup_draft_trust()
        # Add the primary trustee and the matching TaxYear but NO
        # beneficiary, so only the beneficiary check fails.
        add_trustee(
            scenario.trust, scenario.grantor_headers,
            is_primary=True,
        )
        add_tax_year(scenario.trust, calendar_year=2026)
        resp = api.activate_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_BENEFICIARY.value)

    def test_activation_requires_open_tax_year(self, api):
        """PRD §3.1: "A TaxYear matching the calendar year of
        inception_date must exist for the trust in OPEN status;
        otherwise activation fails with ERR_NO_OPEN_TAX_YEAR."

        Claim: trust with primary trustee and beneficiary but no
        TaxYear for inception year -> ERR_NO_OPEN_TAX_YEAR.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        add_trustee(
            scenario.trust, scenario.grantor_headers, is_primary=True,
        )
        add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            relation_class="CHILD",
            beneficiary_class="INCOME",
            distribution_tier="TIER_1",
        )
        resp = api.activate_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_TAX_YEAR.value)


# ===========================================================================
# Activation success — PRD §3.1
# ===========================================================================
class TestActivationSuccess:

    def test_activation_transitions_draft_to_active(self, api):
        """PRD §3.1: "When all three preconditions hold, activation
        transitions Trust.status from DRAFT to ACTIVE".

        Claim: trust with all preconditions met activates to ACTIVE.
        """
        scenario = setup_activatable_trust()
        old_version = scenario.trust["version"]
        resp = api.activate_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        trust = validate_success(resp, 200)
        assert trust["status"] == "ACTIVE"
        # PRD §2.4: version increments by exactly 1 on every mutation.
        assert trust["version"] == old_version + 1

    def test_activation_recomputes_principal_balance(self, api):
        """PRD §3.1: "principal_balance is set to the sum of
        book_value across all Asset records whose classification is
        PRINCIPAL and whose status is FUNDED".

        Claim: activation recomputes principal_balance from FUNDED
        PRINCIPAL assets.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=150_000.00,
        )
        assert scenario.trust["status"] == "ACTIVE"
        assert scenario.trust["principal_balance"] == pytest.approx(
            150_000.00, abs=0.01,
        )


# ===========================================================================
# Court-of-law immutability — PRD §2.11
# ===========================================================================
class TestCourtOfLawImmutability:

    def test_patch_trust_type_blocked_when_active(
        self, api,
    ):
        """PRD §2.11: "any subsequent PATCH attempting to change
        trust_type or grantor_tax_status is rejected with
        ERR_IRREVOCABLE_CANNOT_REVOKE."

        Claim: PATCH /trusts/{id} with trust_type after ACTIVE ->
        ERR_IRREVOCABLE_CANNOT_REVOKE.
        """
        scenario = setup_active_trust()
        resp = api.patch_trust(
            scenario.trust["id"],
            patch_trust_payload(
                trust_type="REVOCABLE",
                version=scenario.trust["version"],
            ),
            scenario.grantor_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_IRREVOCABLE_CANNOT_REVOKE.value,
        )

    def test_patch_grantor_status_blocked_when_active(self, api):
        """PRD §2.11: "any subsequent PATCH attempting to change
        trust_type or grantor_tax_status is rejected with
        ERR_IRREVOCABLE_CANNOT_REVOKE."

        Claim: PATCH grantor_tax_status after ACTIVE ->
        ERR_IRREVOCABLE_CANNOT_REVOKE.
        """
        scenario = setup_active_trust()
        resp = api.patch_trust(
            scenario.trust["id"],
            patch_trust_payload(
                grantor_tax_status="GRANTOR",
                version=scenario.trust["version"],
            ),
            scenario.grantor_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_IRREVOCABLE_CANNOT_REVOKE.value,
        )


# ===========================================================================
# Revocation — PRD §3.1
# ===========================================================================
class TestRevocation:

    def test_revoke_irrevocable_rejected(self, api):
        """PRD §3.1: "Revoking an IRREVOCABLE trust is rejected with
        ERR_IRREVOCABLE_CANNOT_REVOKE."

        Claim: revoke on IRREVOCABLE trust ->
        ERR_IRREVOCABLE_CANNOT_REVOKE.
        """
        scenario = setup_active_trust(trust_type="IRREVOCABLE")
        resp = api.revoke_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_IRREVOCABLE_CANNOT_REVOKE.value,
        )

    def test_revoke_revocable_succeeds_and_cascades(self, api):
        """PRD §3.1: "When revocation succeeds, the Trust transitions
        ACTIVE → REVOKED; the principal_balance and income_balance
        are returned to the grantor by being zeroed; every
        Beneficiary with status of ACTIVE transitions to TERMINATED;
        every Asset with status of FUNDED transitions to DISTRIBUTED".

        Claim: REVOCABLE + ACTIVE trust revocation moves status to
        REVOKED and zeros balances.
        """
        scenario = setup_active_trust_with_principal(
            trust_type="REVOCABLE",
            grantor_tax_status="GRANTOR",
            principal_amount=100_000.00,
        )
        resp = api.revoke_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        trust = validate_success(resp, 200)
        assert trust["status"] == "REVOKED"
        assert trust["principal_balance"] == pytest.approx(0.00, abs=0.01)
        assert trust["income_balance"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Termination — PRD §3.1
# ===========================================================================
class TestTermination:

    def test_terminate_blocked_when_funded_assets_remain(self, api):
        """PRD §3.1: "Termination requires that every Asset is in
        either DISTRIBUTED or SOLD status (otherwise
        ERR_HAS_UNDISTRIBUTED_ASSETS)".

        Claim: terminate with a FUNDED asset still on the books ->
        ERR_HAS_UNDISTRIBUTED_ASSETS.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=100_000.00,
        )
        # Drive a TaxYear to CLOSED to clear the year-state
        # precondition first.
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        # finalize would fail (insufficient income_balance for tax
        # could occur but here NON_GRANTOR with 0 DNI -> tax is 0).
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        # Now try to terminate — asset is still FUNDED.
        resp = api.terminate_trust(
            scenario.trust["id"], scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_HAS_UNDISTRIBUTED_ASSETS.value,
        )

    def test_terminate_blocked_when_nonzero_balance(self, api):
        """PRD §3.1: "both principal_balance and income_balance are
        exactly zero (otherwise ERR_NONZERO_BALANCE)".

        Claim: a CLOSED-tax-year NON_GRANTOR trust with no FUNDED
        assets but a positive residual income_balance (DNI minus
        trust_income_tax) is rejected on terminate with
        ERR_NONZERO_BALANCE. Construction: book $1.00 of ordinary
        income then close — DNI=1.00, trust_taxable_income=1.00,
        trust_income_tax=0.10 at the 10% first-band rate per PRD
        §3.8; residual income_balance = 0.90 > 0.
        """
        scenario = setup_closed_tax_year(income_amount=1.00)
        scenario.trust = re_get_trust(scenario.trust["id"])
        # Confirm preconditions: no FUNDED assets, year CLOSED, and
        # at least one of the balances is non-zero.
        assert (scenario.trust["income_balance"] > 0
                or scenario.trust["principal_balance"] > 0), (
            "fixture must leave a non-zero balance to exercise "
            "ERR_NONZERO_BALANCE; got both zero"
        )
        resp = api.terminate_trust(
            scenario.trust["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NONZERO_BALANCE.value)
