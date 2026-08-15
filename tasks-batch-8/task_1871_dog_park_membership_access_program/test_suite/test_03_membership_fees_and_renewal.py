"""Membership purchase, proration, renewal flavors, OCC on renewal, and the
membership/member expiry cascade."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_dog,
    assert_instant_equals,
    confirm_report,
    file_report,
    get_member,
    get_membership,
    make_member_headers,
    purchase_membership,
    register_member,
    renew_membership_payload,
    run_nightly,
    set_clock,
    setup_active_member,
    suspend_member_via_report,
    validate_error,
    validate_success,
    verify_dog,
)

ADMIN = TEST_USERS["park_admin_headers"]


class TestInitialPurchase:
    def test_initial_purchase_term_pinned_to_calendar_year(self, api):
        """PRD §3.3: "On success the Membership is created in `ACTIVE` status
        with `term_start` at the purchase instant and `term_end` pinned to the
        final instant of the calendar year — December 31 at 23:59:59 UTC — and
        the member flips `PENDING_VERIFICATION → ACTIVE` with the member's
        `version` incremented by one."
        PRD §3.3: "`renewal_count` begins at 0."

        Design: Corner/entities/membership_term_end_dec31_on_initial_purchase
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner@x.com")
        verify_dog(add_dog(member["id"])["id"])

        membership = purchase_membership(member["id"])
        assert membership["status"] == "ACTIVE"
        assert_instant_equals(membership["term_start"], "2026-08-01T00:00:00Z",
                              "term_start")
        assert_instant_equals(membership["term_end"], "2026-12-31T23:59:59Z",
                              "term_end")
        assert membership["renewal_count"] == 0

        after = get_member(member["id"])
        assert after["status"] == "ACTIVE", (
            "the first purchase flips PENDING_VERIFICATION to ACTIVE"
        )
        assert after["version"] == member["version"] + 1

    def test_initial_fee_proration_aug1_two_dogs(self, api):
        """PRD §3.3: "Count the whole days from the purchase date (inclusive)
        through December 31 (inclusive) — the days remaining. The base line is
        12000 cents (a $120 annual fee) multiplied by the days remaining and
        divided by the 365 days of the year, rounded half-up to a whole cent.
        The per-dog line covers every verified dog beyond the first: take the
        count of the member's dogs in `VERIFIED` status at purchase time,
        subtract one, and floor the result at zero; multiply that count by 3000
        cents ($30 per additional dog), then by the days remaining, divide by
        365, and round half-up to a whole cent."
        Purchase on 2026-08-01 leaves 153 days: round_half_up(12000*153/365)
        = 5030 plus round_half_up(3000*1*153/365) = 1258.

        Design: Corner/calculations/initial_fee_proration_aug1_two_dogs
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=2,
                                     full_name="Two Dogs", email="two@x.com")
        assert bundle["membership"]["charged_fee_cents"] == 6288


class TestInitialFeeRoundingOrder:
    def test_initial_fee_per_line_rounding_two_dogs(self, api):
        """PRD §3.3: "`charged_fee_cents` is the sum of the two independently
        rounded lines — rounding happens per line before summation, never once
        on the total."
        Purchase on 2026-11-01 leaves 61 days with 2 verified dogs:
        round_half_up(12000*61/365) = 2005 and round_half_up(3000*1*61/365)
        = 501, summing to 2506 (sum-then-round would yield 2507).

        Design: Difficulty/combinatorial_formula/initial_fee_per_line_rounding_order
        """
        bundle = setup_active_member(clock="2026-11-01T00:00:00Z", num_dogs=2,
                                     full_name="Ned N", email="ned@x.com")
        assert bundle["membership"]["charged_fee_cents"] == 2506, (
            "per-line round-half-up then sum: 2005 + 501"
        )

    def test_initial_fee_per_line_rounding_single_dog(self, api):
        """PRD §3.3: "The per-dog line covers every verified dog beyond the
        first: take the count of the member's dogs in `VERIFIED` status at
        purchase time, subtract one, and floor the result at zero"
        Purchase on 2026-11-01 with a single verified dog: the dog line floors
        at zero, leaving round_half_up(12000*61/365) = 2005.

        Design: Difficulty/combinatorial_formula/initial_fee_per_line_rounding_order
        """
        bundle = setup_active_member(clock="2026-11-01T00:00:00Z", num_dogs=1,
                                     full_name="Solo S", email="solo@x.com")
        assert bundle["membership"]["charged_fee_cents"] == 2005


class TestRenewalFlavors:
    def test_early_vs_lapsed_renewal_fee_lifecycle(self, api):
        """PRD §3.3: "Each fee line takes a ten-percent early-bird discount:
        the base line is 12000 cents at nine-tenths, rounded half-up (10800
        cents); the per-dog line is 3000 cents times the verified dogs beyond
        the first, at nine-tenths, rounded half-up; `charged_fee_cents` is the
        sum of the rounded lines."
        PRD §3.3: "The fee is the full, undiscounted calendar year with no
        proration: 12000 cents plus 3000 cents for each verified dog beyond the
        first, plus a flat 2500-cent reinstatement fee."
        PRD §3.3: "`term_start` restarts at the renewal instant and `term_end`
        lands on December 31 of the current year."
        PRD §3.8: "2. Expire memberships whose `term_end` is before the run's
        logical time — `ACTIVE → EXPIRED` or `SUSPENDED → EXPIRED`; where the
        prior status was `ACTIVE`, the owning member lapses `ACTIVE → LAPSED`
        in the same run, while a `SUSPENDED` member remains suspended."

        Design: Difficulty/dual_variant_calc/membership_fee_early_vs_lapsed_renewal
        """
        # Vaccination outlives the 2028-01-15 expiry run below, so both dogs
        # still stand VERIFIED at lapsed-renewal time (PRD §3.8 stage 6) and
        # the lapsed fee counts one dog beyond the first (PRD §3.3).
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=2,
                                     vaccination_expires_on="2029-06-01",
                                     full_name="Alice A", email="alice@x.com")
        member = bundle["member"]
        membership = bundle["membership"]
        headers = bundle["member_headers"]
        assert membership["charged_fee_cents"] == 6288
        assert membership["version"] == 1

        early = validate_success(api.renew_membership(
            membership["id"], renew_membership_payload(1), headers))
        assert early["charged_fee_cents"] == 13500, (
            "early-bird lines 10800 + 2700 while ACTIVE"
        )

        set_clock("2028-01-15T00:00:00Z")
        summary = run_nightly()
        assert summary["memberships_expired"] == 1
        assert summary["members_lapsed"] == 1

        current = get_membership(member["id"])
        lapsed = validate_success(api.renew_membership(
            membership["id"],
            renew_membership_payload(current["version"]),
            headers,
        ))
        assert lapsed["charged_fee_cents"] == 17500, (
            "full lines 12000 + 3000 plus 2500 reinstatement while EXPIRED"
        )
        assert_instant_equals(lapsed["term_end"], "2028-12-31T23:59:59Z",
                              "lapsed renewal term_end")

    def test_early_renewal_extends_term_one_year(self, api):
        """PRD §3.3: "The term extends — `term_end` moves to December 31 of the
        year after the current `term_end` — making this transition a self-loop,
        `ACTIVE → ACTIVE`."
        PRD §3.3: "Both flavors increment `renewal_count` by one and the
        membership's `version` by one, and record the freshly computed
        `charged_fee_cents`."

        Design: Difficulty/dual_variant_calc/membership_fee_early_vs_lapsed_renewal
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Solo S", email="solo2@x.com")
        membership = bundle["membership"]
        headers = bundle["member_headers"]
        assert_instant_equals(membership["term_end"], "2026-12-31T23:59:59Z",
                              "initial term_end")

        renewed = validate_success(api.renew_membership(
            membership["id"], renew_membership_payload(1), headers))
        assert renewed["status"] == "ACTIVE", "early renewal is a self-loop"
        assert_instant_equals(renewed["term_end"], "2027-12-31T23:59:59Z",
                              "term_end after early renewal")
        assert renewed["renewal_count"] == 1
        assert renewed["version"] == membership["version"] + 1


class TestRenewalOptimisticConcurrency:
    def test_occ_renew_stale_version(self, api):
        """PRD §2.6: "Renewing a membership (`POST
        /dog-park/memberships/{membershipId}/renew`) requires
        `expected_membership_version` matched against the Membership's current
        `version`; because successive early renewals legitimately extend the
        term by one year each, a renewal carrying a stale version would
        silently double-extend the term, and it is instead rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_renew_stale_version
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Own Er", email="owner@x.com")
        membership = bundle["membership"]
        headers = bundle["member_headers"]
        assert membership["version"] == 1

        first = validate_success(api.renew_membership(
            membership["id"], renew_membership_payload(1), headers))
        assert first["renewal_count"] == 1
        assert first["version"] == 2

        stale = api.renew_membership(
            membership["id"], renew_membership_payload(1), headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_membership(bundle["member"]["id"])
        assert after["renewal_count"] == 1, (
            "the rejected replay never double-extends the term"
        )

    def test_renew_unknown_membership_returns_404(self, api):
        """PRD §2.7: "6. **Existence** — path identifiers exist, validated left
        to right (§2.8): the 404 family."
        PRD §2.7: "7. **Optimistic concurrency** — `expected_member_version` or
        `expected_membership_version` matches the entity's current `version`:
        `ERR_STALE_VERSION`."

        Design: Corner/errors/error_membership_not_found
        """
        register_member(full_name="Own Er", email="owner@x.com")
        resp = api.renew_membership(
            NON_EXISTENT_UUID, renew_membership_payload(1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND)


class TestRenewalMemberStateGate:
    def test_renewal_blocked_when_member_suspended(self, api):
        """PRD §3.3: "**Early renewal** applies when the membership is `ACTIVE`
        at renewal time. The member must be `ACTIVE` — evaluated before the
        membership's own state, with `ERR_MEMBER_NOT_ACTIVE` greeting any other
        member status."
        PRD §3.3: "A membership in any other status has no renewal path."

        Design: Difficulty/cross_entity_state_dependency/renewal_blocked_when_member_suspended
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject@x.com")
        member = bundle["member"]
        membership = bundle["membership"]
        suspend_member_via_report(member["id"], severity="SEVERE")
        assert get_member(member["id"])["status"] == "SUSPENDED"

        current = get_membership(member["id"])
        assert current["status"] == "SUSPENDED"
        resp = api.renew_membership(
            membership["id"],
            renew_membership_payload(current["version"]),
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

        after = get_membership(member["id"])
        assert after["status"] == "SUSPENDED"
        assert after["renewal_count"] == 0, "the rejected renewal never lands"

    def test_renewal_stale_version_checked_before_member_state(self, api):
        """PRD §3.3: "Renewal keeps the term alive and comes in two flavors,
        both flowing through the same OCC-guarded renewal capability (§2.6), on
        which the version check fires first, before any member-state or
        membership-state evaluation:"

        Design: Difficulty/cross_entity_state_dependency/renewal_blocked_when_member_suspended
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject2@x.com")
        member = bundle["member"]
        membership = bundle["membership"]
        stale_version = membership["version"]
        suspend_member_via_report(member["id"], severity="SEVERE")
        assert get_member(member["id"])["status"] == "SUSPENDED"

        resp = api.renew_membership(
            membership["id"],
            renew_membership_payload(stale_version),
            bundle["member_headers"],
        )
        # The OCC check fires before any member-state evaluation: even though
        # the member is SUSPENDED, the stale version surfaces ERR_STALE_VERSION.
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestExpiryCascade:
    def test_nightly_run_expires_membership_and_lapses_member(self, api):
        """PRD §3.8: "2. Expire memberships whose `term_end` is before the
        run's logical time — `ACTIVE → EXPIRED` or `SUSPENDED → EXPIRED`; where
        the prior status was `ACTIVE`, the owning member lapses `ACTIVE →
        LAPSED` in the same run, while a `SUSPENDED` member remains suspended."
        PRD §3.8: "The run's response reports the epoch's yield as integer
        tallies: `visits_force_closed`, `memberships_expired`,
        `members_lapsed`, `guest_passes_expired`, `closures_activated`,
        `closures_completed`, `dogs_expired`, and `stations_flagged`."

        Design: Difficulty/transitive_cascade/nightly_run_expiry_cascade
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject3@x.com")
        member = bundle["member"]

        set_clock("2027-01-10T00:00:00Z")
        summary = run_nightly()
        assert summary["memberships_expired"] == 1
        assert summary["members_lapsed"] == 1

        membership = get_membership(member["id"])
        assert membership["status"] == "EXPIRED"
        assert get_member(member["id"])["status"] == "LAPSED"

    def test_membership_not_expired_before_term_end_boundary(self, api):
        """PRD §3.8: "2. Expire memberships whose `term_end` is before the
        run's logical time — `ACTIVE → EXPIRED` or `SUSPENDED → EXPIRED`; where
        the prior status was `ACTIVE`, the owning member lapses `ACTIVE →
        LAPSED` in the same run, while a `SUSPENDED` member remains suspended."
        A run at exactly 2026-12-31T23:59:59Z does not expire the membership
        (the term end is not before the run time); the next instant's run does.

        Design: Difficulty/transitive_cascade/nightly_run_expiry_cascade
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject4@x.com")
        member = bundle["member"]

        set_clock("2026-12-31T23:59:59Z")
        first = run_nightly()
        assert first["memberships_expired"] == 0, (
            "term_end equal to the run time is not before it"
        )
        assert first["members_lapsed"] == 0
        assert get_membership(member["id"])["status"] == "ACTIVE"
        assert get_member(member["id"])["status"] == "ACTIVE"

        set_clock("2027-01-01T00:00:00Z")
        second = run_nightly()
        assert second["memberships_expired"] == 1
        assert second["members_lapsed"] == 1


class TestReinstateIntoLapsed:
    def test_reinstate_with_expired_membership_yields_lapsed(self, api):
        """PRD §3.7: "Where the member lands depends on the membership: if the
        membership stands `SUSPENDED`, the member returns `SUSPENDED → ACTIVE`
        and the membership rides along `SUSPENDED → ACTIVE`; if the membership
        has already run to `EXPIRED`, the member instead lands `SUSPENDED →
        LAPSED` — strikes cleared, membership still expired — and the road back
        to `ACTIVE` is the lapsed renewal of §3.3."
        PRD §3.8: "where the prior status was `ACTIVE`, the owning member
        lapses `ACTIVE → LAPSED` in the same run, while a `SUSPENDED` member
        remains suspended."
        PRD §3.3: "The fee is the full, undiscounted calendar year with no
        proration: 12000 cents plus 3000 cents for each verified dog beyond the
        first, plus a flat 2500-cent reinstatement fee."
        PRD §3.3: "The same request cascades the member `LAPSED → ACTIVE`."

        Design: Corner/state_machines/reinstate_with_expired_membership_yields_lapsed
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     size_class="LARGE",
                                     full_name="Sub Ject",
                                     email="subject5@x.com")
        member = bundle["member"]
        membership = bundle["membership"]
        suspend_member_via_report(member["id"], severity="SEVERE")
        assert get_member(member["id"])["status"] == "SUSPENDED"

        set_clock("2027-01-10T00:00:00Z")
        summary = run_nightly()
        assert summary["memberships_expired"] == 1
        assert summary["members_lapsed"] == 0, (
            "a SUSPENDED member remains suspended through the expiry run"
        )

        reinstated = validate_success(
            api.reinstate_member(member["id"], ADMIN))
        assert reinstated["status"] == "LAPSED", (
            "membership already EXPIRED, so reinstatement lands on LAPSED"
        )
        assert reinstated["strike_points"] == 0
        assert get_membership(member["id"])["status"] == "EXPIRED"

        current = get_membership(member["id"])
        renewed = validate_success(api.renew_membership(
            membership["id"],
            renew_membership_payload(current["version"]),
            bundle["member_headers"],
        ))
        assert renewed["charged_fee_cents"] == 14500, (
            "12000 base + 0 extra-dog + 2500 reinstatement"
        )
        assert_instant_equals(renewed["term_end"], "2027-12-31T23:59:59Z",
                              "lapsed renewal term_end")
        assert get_member(member["id"])["status"] == "ACTIVE"
