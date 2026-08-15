"""CAQH attestation cycle: lapse boundaries, warning-window entry, and the
re-attestation cycle restart (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_caqh_profile,
    assert_timestamp_second,
    attest_provider,
    create_practice_group,
    create_provider,
    get_caqh_profile,
    make_provider_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]


class TestLapseStrictlyAfterDueAt:
    def test_profile_is_due_at_due_at_and_lapsed_one_second_later(self, api):
        """PRD §3.2: "Only when the logical clock is strictly later than
        `due_at` does the profile become `LAPSED`; at the exact instant of
        `due_at` the profile is `DUE`, never `LAPSED`."

        Design: Difficulty/boundary_precision_check/caqh_lapse_strictly_after_due_at
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        # Attested at the startup clock 2026-08-01T00:00:00Z.
        profile = attest_provider(provider["id"])
        assert_timestamp_second(profile["due_at"], "2026-11-29T00:00:00")

        set_clock("2026-11-29T00:00:00Z")  # exactly due_at
        at_due = get_caqh_profile(provider["id"])
        assert at_due["status"] == "DUE", "at exactly due_at the profile is DUE"

        set_clock("2026-11-29T00:00:01Z")  # one second past
        after = get_caqh_profile(provider["id"])
        assert after["status"] == "LAPSED", "strictly later than due_at -> LAPSED"

    def test_attestation_at_exact_due_instant_restarts_cycle(self, api):
        """PRD §3.2: "Attestation is permitted from every profile status —
        `NEVER_ATTESTED`, `ATTESTED`, `DUE`, and `LAPSED` alike — and always
        lands in `ATTESTED`."
        PRD §3.2: "Each attestation stamps `last_attested_at` with the current
        logical clock and recomputes `due_at` as exactly 120 days later, so a
        re-attestation restarts the cycle from scratch, whether it happens
        inside the warning window, after a lapse, or long before either."

        Design: Difficulty/boundary_precision_check/caqh_lapse_strictly_after_due_at
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        attest_provider(provider["id"])  # due_at 2026-11-29T00:00:00Z

        set_clock("2026-11-29T00:00:00Z")  # exactly due_at: profile is DUE
        assert get_caqh_profile(provider["id"])["status"] == "DUE"

        renewed = attest_provider(provider["id"])
        assert renewed["status"] == "ATTESTED"
        assert_timestamp_second(renewed["last_attested_at"], "2026-11-29T00:00:00")
        # 2026-11-29 + 120 days = 2027-03-29.
        assert_timestamp_second(renewed["due_at"], "2027-03-29T00:00:00")


class TestRelapseReattestCycle:
    def test_lapsed_profile_reattests_and_cycle_restarts(self, api):
        """PRD §3.2: "The cycle is unbounded: `ATTESTED` gives way to `DUE`,
        `DUE` to `LAPSED`, and a fresh attestation returns the profile to
        `ATTESTED` again."
        PRD §3.2: "Each attestation stamps `last_attested_at` with the current
        logical clock and recomputes `due_at` as exactly 120 days later, so a
        re-attestation restarts the cycle from scratch, whether it happens
        inside the warning window, after a lapse, or long before either."

        Design: Difficulty/non_linear_state_machine/caqh_relapse_reattest_cycle
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        first = attest_provider(provider["id"])
        assert first["status"] == "ATTESTED"

        set_clock("2026-11-30T00:00:01Z")  # strictly past due 2026-11-29
        lapsed = get_caqh_profile(provider["id"])
        assert lapsed["status"] == "LAPSED"

        second = attest_provider(provider["id"])
        assert_caqh_profile(second)
        assert second["status"] == "ATTESTED", "cycle restarts from LAPSED"
        assert_timestamp_second(second["last_attested_at"], "2026-11-30T00:00:01")
        # 2026-11-30 + 120 days = 2027-03-30.
        assert_timestamp_second(second["due_at"], "2027-03-30T00:00:01")

    def test_reattest_inside_warning_window_resets_due_at(self, api):
        """PRD §3.2: "Each attestation stamps `last_attested_at` with the
        current logical clock and recomputes `due_at` as exactly 120 days
        later, so a re-attestation restarts the cycle from scratch, whether it
        happens inside the warning window, after a lapse, or long before
        either."

        Design: Difficulty/non_linear_state_machine/caqh_relapse_reattest_cycle
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        attest_provider(provider["id"])  # due_at 2026-11-29

        # Window opens at 2026-10-30; 2026-11-04 is inside it.
        set_clock("2026-11-04T00:00:00Z")
        assert get_caqh_profile(provider["id"])["status"] == "DUE"

        renewed = attest_provider(provider["id"])
        assert renewed["status"] == "ATTESTED"
        # 2026-11-04 + 120 days = 2027-03-04.
        assert_timestamp_second(renewed["due_at"], "2027-03-04T00:00:00")


class TestDueWindowEntryBoundary:
    def test_window_opens_inclusively_thirty_days_before_due(self, api):
        """PRD §3.2: "A profile in `ATTESTED` enters `DUE` once the logical
        clock reaches the instant thirty days before `due_at`, and it remains
        `DUE` through `due_at` itself."

        Design: Corner/calculations/attestation_due_window_entry_boundary
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        attest_provider(provider["id"])  # due_at 2026-11-29T00:00:00Z

        set_clock("2026-10-29T00:00:00Z")  # one day before the window opens
        assert get_caqh_profile(provider["id"])["status"] == "ATTESTED"

        set_clock("2026-10-30T00:00:00Z")  # due_at - 30 days, inclusive
        assert get_caqh_profile(provider["id"])["status"] == "DUE"


class TestProfileOwnership:
    def test_provider_cannot_attest_another_providers_profile(self, api):
        """PRD §3.2: "CAQH attestation is the provider's own act, and the
        system enforces that literally: when `X-User-Role` is `Provider`, the
        caller may attest only the profile whose `provider_id` equals their
        `X-User-ID`. Any other pairing is rejected with
        `ERR_PROFILE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/provider_attesting_others_profile_rejected
        """
        group = create_practice_group()
        p1 = create_provider(group["id"], npi="NPI-P1", full_name="Dr One")
        p2 = create_provider(group["id"], npi="NPI-P2", full_name="Dr Two")
        profile_p1 = get_caqh_profile(p1["id"])

        res = api.attest_caqh_profile(
            profile_p1["id"], make_provider_headers(p2["id"])
        )
        validate_error(res, ApiErrorId.ERR_PROFILE_OWNERSHIP_MISMATCH)

        after = get_caqh_profile(p1["id"])
        assert after["status"] == "NEVER_ATTESTED"
        assert after["last_attested_at"] is None
