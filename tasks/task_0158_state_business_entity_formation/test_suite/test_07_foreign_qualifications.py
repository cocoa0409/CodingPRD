"""Foreign qualification lifecycle, COGS rule, state-match rule,
duplicate rule, and rejection-cycle.

Covers PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_foreign_qualification,
    assert_foreign_qualification,
    assert_status,
    create_and_activate_entity,
    create_foreign_qualification_payload,
    create_pending_foreign_qualification,
    create_registered_agent,
    iso_now,
    add_days,
    make_filer_headers,
    patch_foreign_qualification_payload,
    server_now_iso,
    validate_error,
    validate_success,
)


class TestForeignQualificationCreate:

    def test_create_in_pending(self, api):
        """PRD §3.7: "The qualification starts with status PENDING."

        Claim: a new ForeignQualification has status=PENDING.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        agent_ny = create_registered_agent(service_state="NY")
        payload = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], server_now_iso(),
        )
        resp = api.create_foreign_qualification(
            payload, make_filer_headers(entity["id"]),
        )
        qual = validate_success(resp, expected_status=201)
        assert_foreign_qualification(qual)
        assert_status(qual, "PENDING")

    def test_foreign_state_equals_home_state_rejected(self, api):
        """PRD §3.7: "The foreign_state is a two-letter uppercase US
        state code that must not equal the entity's home_state ... an
        attempt is rejected with ERR_FOREIGN_STATE_IS_HOME and HTTP
        422."

        Claim: foreign_state == home_state → ERR_FOREIGN_STATE_IS_HOME.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        agent = create_registered_agent(service_state="DE")
        payload = create_foreign_qualification_payload(
            entity["id"], "DE", agent["id"], server_now_iso(),
        )
        resp = api.create_foreign_qualification(
            payload, make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FOREIGN_STATE_IS_HOME.value)

    def test_foreign_agent_state_mismatch_rejected(self, api):
        """PRD §3.7: "The foreign_registered_agent_id must resolve to a
        RegisteredAgent whose service_state equals the qualification's
        foreign_state — that is, the foreign agent must be authorized
        in the foreign state — and a mismatch is rejected with
        ERR_AGENT_STATE_MISMATCH."

        Claim: foreign_registered_agent.service_state != foreign_state
        → ERR_AGENT_STATE_MISMATCH.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        # Agent authorized in CA, but the qualification targets NY.
        agent_ca = create_registered_agent(service_state="CA")
        payload = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ca["id"], server_now_iso(),
        )
        resp = api.create_foreign_qualification(
            payload, make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENT_STATE_MISMATCH.value)


class TestForeignQualificationApprove:

    def test_approve_pending_to_qualified(self, api,
                                          state_registrar_headers):
        """PRD §3.7: "A StateRegistrar approves or rejects it. Approval
        transitions PENDING → QUALIFIED and requires three concurrent
        conditions: the parent entity's compliance_status is
        GOOD_STANDING ..., the certificate_of_good_standing_date is
        within sixty days of the current clock instant ..., and the
        foreign agent's status is ACTIVE and its service_state equals
        the qualification's foreign_state."

        Claim: a pending qualification with a fresh COGS and a properly
        authorized foreign agent → QUALIFIED + qualified_at set.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        qual, _ = create_pending_foreign_qualification(entity["id"], "NY")
        resp = api.approve_foreign_qualification(
            qual["id"], state_registrar_headers,
        )
        approved = validate_success(resp)
        assert_status(approved, "QUALIFIED")
        assert approved.get("qualified_at") is not None

    def test_stale_cogs_rejected(self, api, state_registrar_headers):
        """PRD §3.7: "the certificate_of_good_standing_date is within
        sixty days of the current clock instant (older COGS yields
        ERR_STALE_COGS)"

        Claim: COGS dated > 60 days before now → ERR_STALE_COGS at
        approval.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        # COGS dated 90 days in the past from "now" — use server clock
        # so we're 90 days before the SERVER's now (not Python's wall
        # clock, which may differ from the advanced server clock).
        stale_cogs = add_days(server_now_iso(), -90)
        qual, _ = create_pending_foreign_qualification(
            entity["id"], "NY", cogs_date=stale_cogs,
        )
        resp = api.approve_foreign_qualification(
            qual["id"], state_registrar_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_COGS.value)


class TestForeignQualificationRejectAndResubmit:

    def test_reject_then_resubmit_returns_to_pending(
        self, api, state_registrar_headers,
    ):
        """PRD §3.7: "Rejection transitions PENDING → REJECTED without
        preconditions; the Filer may then resubmit through the patch
        endpoint, which can carry a fresh certificate_of_good_standing_
        date, a revised foreign_registered_agent_id, and an optional
        version for OCC. Resubmission requires the supplied COGS date
        to be within sixty days of the current clock; on success the
        row cycles REJECTED → PENDING for another approval cycle."

        Claim: reject → REJECTED; PATCH with fresh COGS → PENDING.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        qual, _ = create_pending_foreign_qualification(entity["id"], "NY")
        # Reject.
        rej_resp = api.reject_foreign_qualification(
            qual["id"], state_registrar_headers,
        )
        rejected = validate_success(rej_resp)
        assert_status(rejected, "REJECTED")
        # Resubmit via PATCH with a fresh COGS.
        resp = api.patch_foreign_qualification(
            qual["id"],
            patch_foreign_qualification_payload(
                certificate_of_good_standing_date=server_now_iso(),
            ),
            make_filer_headers(entity["id"]),
        )
        resubmitted = validate_success(resp)
        assert_status(resubmitted, "PENDING")


class TestForeignQualificationDuplicate:

    def test_second_open_filing_for_same_state_rejected(self, api):
        """PRD §3.7: "Only one non-terminal qualification (that is, with
        status neither WITHDRAWN nor REVOKED) may exist for a given
        (business_entity_id, foreign_state) pair at a time; a second
        attempt yields ERR_DUPLICATE_FOREIGN_QUALIFICATION with HTTP
        409."

        Claim: a second filing for the same (entity, state) while the
        first is PENDING → ERR_DUPLICATE_FOREIGN_QUALIFICATION.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        agent_ny = create_registered_agent(service_state="NY")
        # First filing.
        first = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], iso_now(),
        )
        validate_success(
            api.create_foreign_qualification(
                first, make_filer_headers(entity["id"]),
            ),
            expected_status=201,
        )
        # Second filing — duplicate open interval.
        second = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], iso_now(),
        )
        dup_resp = api.create_foreign_qualification(
            second, make_filer_headers(entity["id"]),
        )
        validate_error(
            dup_resp, ApiErrorId.ERR_DUPLICATE_FOREIGN_QUALIFICATION.value,
        )


class TestForeignQualificationWithdraw:

    def test_filer_withdraws_qualified(self, api):
        """PRD §3.7: "A Filer may voluntarily withdraw a QUALIFIED
        qualification, transitioning it to WITHDRAWN."

        Claim: withdraw QUALIFIED → WITHDRAWN.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        qual, _ = create_pending_foreign_qualification(entity["id"], "NY")
        approved = approve_foreign_qualification(qual["id"])
        assert approved["status"] == "QUALIFIED"
        resp = api.withdraw_foreign_qualification(
            approved["id"], make_filer_headers(entity["id"]),
        )
        withdrawn = validate_success(resp)
        assert_status(withdrawn, "WITHDRAWN")
