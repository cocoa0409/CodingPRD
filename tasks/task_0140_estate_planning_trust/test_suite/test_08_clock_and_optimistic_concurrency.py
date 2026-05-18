"""Logical clock advance, time-gated auto-transitions, and
optimistic-concurrency version-mismatch.

Coverage targets (PRD §2.6, §2.11, §3.16):
- POST /_clock/advance is CourtClerk-only.
- Clock advance flips PoA PENDING -> ACTIVE when effective_at reached
  and Estate.admin_phase=DRAFT.
- Clock advance flips HIPAA ACTIVE -> EXPIRED when expires_at reached.
- OCC version mismatch -> ERR_VERSION_MISMATCH.
- Guardianship effective_at must not be in the past.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    create_estate_with_executor,
    create_guardianship_payload,
    create_hipaa_payload,
    create_poa_payload,
    estate_state_payload,
    get_clock_now,
    get_success_data,
    iso_offset,
    nominate_fiduciary,
    server_offset_iso,
    setup_in_probate,
    validate_error,
    validate_success,
)


class TestClockAdvanceRole:

    def test_advance_clock_requires_court_clerk(
        self, api, executor_fallback_headers,
    ):
        """PRD §3.16: "The CourtClerk may advance the logical clock
        to a supplied to_timestamp instant".

        Claim: a non-CourtClerk attempting POST /_clock/advance ->
        ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            payload={"to_timestamp": "2099-01-01T00:00:00.000Z"},
            headers=executor_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestPoaTimeGate:

    def test_clock_advance_flips_pending_poa_to_active(self, api):
        """PRD §3.16: "PowerOfAttorney rows in PENDING whose
        effective_at has been reached, and whose estate is in DRAFT,
        move to ACTIVE."

        Claim: a PENDING POA in DRAFT estate becomes ACTIVE after
        clock-advance past its effective_at.
        """
        estate, _, exec_h = create_estate_with_executor()
        agent = nominate_fiduciary(estate["id"], scope_type="TRUSTEE")
        eff = server_offset_iso(minutes=5)
        poa = get_success_data(api_client.create_poa(
            estate["id"],
            create_poa_payload(
                agent_fiduciary_id=agent["id"],
                asset_class_scope=["FINANCIAL"],
                effective_at=eff,
            ),
            exec_h,
        ))
        assert poa["status"] == "PENDING"
        # Advance past eff.
        advance_clock_to(server_offset_iso(minutes=10))
        # Re-read.
        poa_after = get_success_data(
            api_client.get_poa(
                estate["id"], poa["id"], exec_h,
            ),
        )
        assert poa_after["status"] == "ACTIVE", (
            f"PoA must auto-transition to ACTIVE after clock "
            f"advances past effective_at, got {poa_after['status']!r}"
        )


class TestHipaaTimeGate:

    def test_clock_advance_expires_hipaa(self, api):
        """PRD §3.16: "HIPAAAuthorization rows in ACTIVE whose
        expires_at is non-null and has been reached move to
        EXPIRED."

        Claim: an ACTIVE HIPAA with expires_at in the past becomes
        EXPIRED after clock-advance.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        expires_at = server_offset_iso(minutes=5)
        hipaa = get_success_data(api_client.create_hipaa(
            estate["id"],
            create_hipaa_payload(scope="ALL",
                                  expires_at=expires_at),
            exec_h,
        ))
        assert hipaa["status"] == "ACTIVE"
        advance_clock_to(server_offset_iso(minutes=10))
        hipaa_after = get_success_data(
            api_client.get_hipaa(estate["id"], hipaa["id"], exec_h),
        )
        assert hipaa_after["status"] == "EXPIRED", (
            f"HIPAA must auto-transition to EXPIRED after "
            f"clock advances past expires_at, got "
            f"{hipaa_after['status']!r}"
        )


class TestGuardianshipEffectivePast:

    def test_create_guardianship_with_past_effective_at_rejected(
        self, api,
    ):
        """PRD §3.1: "The effective_at must be at or after the
        current logical clock — a request whose effective_at is
        strictly earlier than now is rejected with
        ERR_DIRECTIVE_EFFECTIVE_PAST."

        Claim: effective_at strictly in the past at create time ->
        ERR_DIRECTIVE_EFFECTIVE_PAST.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        # Create a minor + guardian.
        from test_helpers import add_beneficiary
        minor = add_beneficiary(
            estate["id"], is_minor=True, exec_headers=exec_h,
        )
        guard = nominate_fiduciary(estate["id"], scope_type="GUARDIAN")
        # Effective in the past.
        past = server_offset_iso(days=-1)
        resp = api_client.create_guardianship(
            estate["id"],
            create_guardianship_payload(
                minor_beneficiary_id=minor["id"],
                guardian_fiduciary_id=guard["id"],
                effective_at=past,
            ),
            exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_DIRECTIVE_EFFECTIVE_PAST.value)


class TestOptimisticConcurrency:

    def test_version_mismatch_rejected(self, api):
        """PRD §2.6: "When version is supplied, the server compares
        it to the current version of the target row before applying
        any change; a mismatch causes the request to be rejected
        with ERR_VERSION_MISMATCH and HTTP 409."

        Claim: PATCH with stale version -> ERR_VERSION_MISMATCH.
        """
        estate, _, exec_h = create_estate_with_executor()
        # PATCH with a definitely-stale version.
        resp = api_client.update_estate(
            estate["id"],
            {"testator_name": "x", "version": estate["version"] - 1},
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_omitted_version_skips_occ(self, api):
        """PRD §2.6: "When version is omitted, the OCC check is
        skipped — the caller is asserting it does not care which
        prior revision it is overwriting."

        Claim: PATCH without version field succeeds.
        """
        estate, _, exec_h = create_estate_with_executor()
        resp = api_client.update_estate(
            estate["id"],
            {"testator_name": "new name"}, exec_h,
        )
        updated = validate_success(resp)
        assert updated["testator_name"] == "new name"

    def test_version_increments_by_one(self, api):
        """PRD §2.4: "a version integer that begins at 1 and
        increments by exactly 1 on every mutation".

        Claim: each PATCH bumps version by exactly 1.
        """
        estate, _, exec_h = create_estate_with_executor()
        v0 = estate["version"]
        updated = get_success_data(api_client.update_estate(
            estate["id"], {"testator_name": "a"}, exec_h,
        ))
        assert updated["version"] == v0 + 1, (
            f"version must bump by 1: {v0} -> {updated['version']}"
        )
        again = get_success_data(api_client.update_estate(
            estate["id"], {"testator_name": "b"}, exec_h,
        ))
        assert again["version"] == v0 + 2, (
            f"version must bump by 1: {updated['version']} "
            f"-> {again['version']}"
        )
