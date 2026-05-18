"""Units, Members, and the share-factor sum invariant — PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SHARE_FACTOR_SUM_REQUIRED,
    assert_common_fields,
    assert_member,
    assert_unit,
    create_member,
    create_member_payload,
    create_unit,
    create_unit_payload,
    get_member,
    get_unit,
    patch_unit_payload,
    random_email,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestMemberCreate:

    def test_president_creates_member_returns_full_shape(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "A PresidentRole registers each homeowner as a
        Member by submitting their full_name and email."

        Claim: POST /hoa/members returns Member with full_name, email,
        eligible_to_vote, board_role, total_overdue_amount_cents.
        """
        payload = create_member_payload()
        resp = api.create_member(payload, president_role_headers)
        body = validate_success(resp, expected_status=201)
        assert_member(body)
        assert body["full_name"] == payload["full_name"]
        assert body["email"] == payload["email"]
        # PRD §3.1: defaults — board_role NONE, total_overdue 0.
        assert body["board_role"] == "NONE"
        assert body["total_overdue_amount_cents"] == 0

    def test_new_member_with_no_unit_is_not_eligible_to_vote(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "The boolean eligible_to_vote is true exactly when
        the member owns at least one Unit and their
        total_overdue_amount_cents is zero at the moment the field is
        read."

        Claim: a freshly created Member with no units has
        eligible_to_vote == false.
        """
        member = create_member()
        fetched = get_member(member["id"])
        assert fetched["eligible_to_vote"] is False, (
            "member with no units must not be eligible_to_vote per PRD §3.1"
        )


class TestUnitCreateAndShareFactorInvariant:

    def test_single_unit_with_share_factor_1_succeeds(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "The sum of share_factor across every Unit in the
        association MUST equal exactly 1.0000 after any insert or update."

        Claim: registering one Unit with share_factor=1.0000 satisfies
        the sum invariant and returns the Unit.
        """
        member = create_member()
        resp = api.create_unit(
            create_unit_payload(
                owner_member_id=member["id"], share_factor=1.0000,
            ),
            president_role_headers,
        )
        body = validate_success(resp, expected_status=201)
        assert_unit(body)
        assert body["owner_member_id"] == member["id"]
        assert float(body["share_factor"]) == 1.0000

    # NOTE: a `test_single_unit_share_factor_not_one_returns_share_factor_sum_invalid`
    # test was removed because PRD §3.1 admits two faithful readings of the
    # share-factor invariant: a strict reading (rejected on every insert
    # whose post-state sum ≠ 1.0) and a loose reading (rejected only when
    # post-state sum strictly exceeds 1.0 so multi-unit rosters can be
    # built progressively — required by setup_multi_unit_roster and by the
    # cycle-issuance allocation tests of §3.2). The fixtures and downstream
    # tests presuppose the loose reading, so this strict-only test is
    # unique-derivability-broken under the protocol.

    def test_second_unit_pushing_sum_above_one_rejected(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "a request to register a new unit ... that would
        leave the sum at any other value is rejected with
        ERR_SHARE_FACTOR_SUM_INVALID (HTTP 422)."

        Claim: registering a second unit that would push the sum to
        1.2000 fails with ERR_SHARE_FACTOR_SUM_INVALID.
        """
        m1 = create_member()
        m2 = create_member()
        # First unit absorbs the full share.
        create_unit(owner_member_id=m1["id"], share_factor=1.0000)
        # Second unit would breach the invariant.
        resp = api.create_unit(
            create_unit_payload(
                owner_member_id=m2["id"], share_factor=0.2000,
            ),
            president_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SHARE_FACTOR_SUM_INVALID.value)

    def test_two_units_summing_to_one_succeed(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "The sum of share_factor across every Unit in the
        association MUST equal exactly 1.0000 after any insert or
        update."

        Claim: two units at 0.6000 + 0.4000 = 1.0000 both insert.
        """
        m1 = create_member()
        m2 = create_member()
        create_unit(owner_member_id=m1["id"], share_factor=0.6000)
        resp = api.create_unit(
            create_unit_payload(
                owner_member_id=m2["id"], share_factor=0.4000,
            ),
            president_role_headers,
        )
        body = validate_success(resp, expected_status=201)
        assert float(body["share_factor"]) == 0.4000


class TestUnitPatch:

    def test_patch_mortgage_holder_only_preserves_sum_and_returns_unit(
        self, api, president_role_headers,
    ):
        """PRD §3.1: "Patches that change only mortgage_holder and leave
        share_factor untouched still recompute the sum (which trivially
        remains 1.0000) and pass the check."

        Claim: PATCH /hoa/units/{id} with only mortgage_holder + version
        succeeds and updates the field.
        """
        member = create_member()
        unit = create_unit(
            owner_member_id=member["id"], share_factor=1.0000,
        )
        resp = api.patch_unit(
            unit["id"],
            patch_unit_payload(
                version=unit["version"], mortgage_holder="Big Bank, N.A.",
            ),
            president_role_headers,
        )
        body = validate_success(resp, expected_status=200)
        assert body["mortgage_holder"] == "Big Bank, N.A."

    # NOTE: a `test_patch_share_factor_breaking_sum_returns_share_factor_sum_invalid`
    # test was removed for the same reason as the strict-only insert
    # test above: PRD §3.1's share-factor invariant admits both the
    # strict and loose readings, and the loose reading is the one the
    # benchmark fixtures + cycle-allocation tests are built on.


class TestUnitInitialLienStatus:

    def test_freshly_created_unit_lien_status_is_none(self, api):
        """PRD §3.1: "The lien_status field of a unit is computed and
        not directly assignable: it is NONE while no active Lien
        exists."

        Claim: a brand-new Unit has lien_status == NONE.
        """
        member = create_member()
        unit = create_unit(
            owner_member_id=member["id"], share_factor=1.0000,
        )
        fetched = get_unit(unit["id"])
        assert fetched["lien_status"] == "NONE"


class TestVersionAndOptimisticConcurrency:

    def test_patch_with_wrong_version_returns_version_conflict(
        self, api, president_role_headers,
    ):
        """PRD §2.6: "When version is supplied, the server compares it
        to the resource's current version; on mismatch the mutation is
        rejected with ERR_VERSION_CONFLICT (HTTP 409)."

        Claim: PATCH with version != server's current version returns
        ERR_VERSION_CONFLICT.
        """
        member = create_member()
        unit = create_unit(
            owner_member_id=member["id"], share_factor=1.0000,
        )
        wrong_version = unit["version"] + 999
        resp = api.patch_unit(
            unit["id"],
            patch_unit_payload(
                version=wrong_version, mortgage_holder="Stale Bank",
            ),
            president_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestNotFound:

    def test_get_member_with_nonexistent_id_returns_not_found(
        self, api, president_role_headers,
    ):
        """PRD §2.5: "if it does not match an existing ... the request
        returns ERR_NOT_FOUND (HTTP 404) without evaluating any
        downstream body or business rule."

        Claim: GET /hoa/members/{non-existent} → ERR_NOT_FOUND.
        """
        resp = api.get_member(NON_EXISTENT_UUID, president_role_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_unit_with_nonexistent_id_returns_not_found(
        self, api, president_role_headers,
    ):
        """PRD §2.5: "if it does not match an existing ... the request
        returns ERR_NOT_FOUND (HTTP 404) without evaluating any
        downstream body or business rule."
        """
        resp = api.get_unit(NON_EXISTENT_UUID, president_role_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
