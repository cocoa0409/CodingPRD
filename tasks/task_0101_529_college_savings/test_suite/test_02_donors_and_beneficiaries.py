"""Donor and Beneficiary registration, retrieval, and computed counters.

PRD §3.1 covers donors and beneficiaries; this file exercises basic
CRUD shapes plus the rules around state_of_residence and
relationship_family_code.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_beneficiary,
    assert_donor,
    create_beneficiary_payload,
    create_donor_payload,
    create_donor,
    create_beneficiary,
    ensure_state_rule,
    TEST_USERS,
    build_user_headers,
    make_donor_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# Donor registration — PRD §3.1
# ===========================================================================
class TestDonorRegistration:

    def test_register_donor_returns_canonical_shape(self, api, admin_headers):
        """PRD §3.1: "A Donor is registered by a PlanAdministrator with
        full_name, state_of_residence, and ssn_last_four."

        Claim: POST /donors with valid payload returns a Donor row with
        the four common properties and zero-initialized YTD counters.
        """
        ensure_state_rule("NY")
        res = api.create_donor(
            create_donor_payload(state_of_residence="NY"), admin_headers,
        )
        donor = validate_success(res, 201)
        assert_donor(donor)
        # PRD §3.1: counters initialize at zero.
        assert donor["ytd_contribution_total_cents"] == 0
        assert donor["ytd_state_deduction_used_cents"] == 0

    def test_register_donor_pa_only(self, api):
        """PRD §4 endpoint table: POST /donors authorized role is
        PlanAdministrator.

        Claim: a Donor cannot register another donor → ERR_FORBIDDEN.
        """
        ensure_state_rule("NY")
        res = api.create_donor(
            create_donor_payload(state_of_residence="NY"),
            build_user_headers("rogue-donor-1", "Donor"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_register_donor_state_of_residence_must_be_two_upper(
        self, api, admin_headers,
    ):
        """PRD §3.1: "state_of_residence must be exactly two uppercase
        letters matching a StateRule.state_code."

        Claim: state_of_residence="ny" (lowercase) is malformed and the
        server rejects it with the generic validation error
        ERR_VALIDATION_FAILED.
        """
        ensure_state_rule("NY")
        res = api.create_donor(
            create_donor_payload(state_of_residence="ny"),
            admin_headers,
        )
        # Either generic validation failure or invalid input — PRD §5
        # only names ERR_VALIDATION_FAILED for "generic request-shape
        # failure ... bad enum", so we assert that.
        validate_error(res, "ERR_VALIDATION_FAILED")

    def test_register_donor_ssn_last_four_must_be_four_digits(
        self, api, admin_headers,
    ):
        """PRD §3.1: "ssn_last_four must be exactly four digits."

        Claim: ssn_last_four with three digits → ERR_VALIDATION_FAILED.
        """
        ensure_state_rule("NY")
        res = api.create_donor(
            create_donor_payload(
                state_of_residence="NY", ssn_last_four="123",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION_FAILED")


# ===========================================================================
# Donor retrieval — PRD §3.1 + §4 (PlanAdministrator, Donor)
# ===========================================================================
class TestDonorGet:

    def test_donor_can_read_self(self, api, admin_headers):
        """PRD §4 endpoint table: GET /donors/{id} is authorized for
        PlanAdministrator and Donor.

        Claim: a Donor reading their own record receives a 200 with the
        Donor entity.
        """
        ensure_state_rule("NY")
        donor = create_donor(state_of_residence="NY")
        res = api.get_donor(donor["id"], make_donor_headers(donor["id"]))
        retrieved = validate_success(res, 200)
        assert retrieved["id"] == donor["id"]
        assert_donor(retrieved)


# ===========================================================================
# Beneficiary registration — PRD §3.1
# ===========================================================================
class TestBeneficiaryRegistration:

    def test_register_beneficiary_returns_canonical_shape(
        self, api, admin_headers,
    ):
        """PRD §3.1: "A Beneficiary is registered by either a
        PlanAdministrator or a Donor with full_name, date_of_birth,
        ssn_last_four, and relationship_family_code."

        Claim: POST /beneficiaries with valid payload returns a
        Beneficiary row with k12_ytd_qualified_cents initialized to 0.
        """
        res = api.create_beneficiary(
            create_beneficiary_payload(relationship_family_code="CHILD"),
            admin_headers,
        )
        ben = validate_success(res, 201)
        assert_beneficiary(ben)
        assert ben["k12_ytd_qualified_cents"] == 0

    def test_register_beneficiary_donor_also_allowed(self, api, admin_headers):
        """PRD §4 endpoint table: POST /beneficiaries is authorized for
        BOTH PlanAdministrator AND Donor.

        Claim: a Donor can register a beneficiary directly.
        """
        ensure_state_rule("NY")
        donor = create_donor(state_of_residence="NY")
        res = api.create_beneficiary(
            create_beneficiary_payload(relationship_family_code="CHILD"),
            make_donor_headers(donor["id"]),
        )
        ben = validate_success(res, 201)
        assert_beneficiary(ben)

    @pytest.mark.parametrize("relationship", [
        "SELF", "CHILD", "SIBLING", "NIECE_NEPHEW", "PARENT",
        "COUSIN", "SPOUSE", "IN_LAW", "FIRST_COUSIN_ONCE_REMOVED",
    ])
    def test_register_beneficiary_accepts_all_irs_codes(
        self, api, admin_headers, relationship,
    ):
        """PRD §3.1: "relationship_family_code ... must be exactly one
        of SELF, CHILD, SIBLING, NIECE_NEPHEW, PARENT, COUSIN, SPOUSE,
        IN_LAW, or FIRST_COUSIN_ONCE_REMOVED."

        Claim: each IRS family code is accepted at registration time
        (the permissible-family check for beneficiary changes is
        separate per PRD §3.6).
        """
        res = api.create_beneficiary(
            create_beneficiary_payload(relationship_family_code=relationship),
            admin_headers,
        )
        ben = validate_success(res, 201)
        assert ben["relationship_family_code"] == relationship

    def test_register_beneficiary_rejects_invalid_relationship(
        self, api, admin_headers,
    ):
        """PRD §3.1: "relationship_family_code ... must be exactly one
        of SELF, CHILD, SIBLING, NIECE_NEPHEW, PARENT, COUSIN, SPOUSE,
        IN_LAW, or FIRST_COUSIN_ONCE_REMOVED."

        Claim: an out-of-set code ("FRIEND") → ERR_VALIDATION_FAILED.
        """
        res = api.create_beneficiary(
            create_beneficiary_payload(
                relationship_family_code="FRIEND",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION_FAILED")

    def test_register_beneficiary_rejects_blank_full_name(
        self, api, admin_headers,
    ):
        """PRD §3.1: "The full_name must be a non-empty string of at
        most 200 characters."

        Claim: an empty full_name → ERR_VALIDATION_FAILED.
        """
        res = api.create_beneficiary(
            create_beneficiary_payload(full_name=""),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION_FAILED")
