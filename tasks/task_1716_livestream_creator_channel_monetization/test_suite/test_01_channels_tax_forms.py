"""Channel onboarding, tax-form compliance, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_channel,
    assert_instant_equals,
    assert_tax_form,
    create_channel,
    create_channel_payload,
    get_channel,
    get_success_data,
    ingest_revenue_event,
    make_creator_headers,
    open_payout,
    payout_settings_payload,
    reject_tax_form,
    run_ops,
    set_clock,
    submit_tax_form,
    submit_tax_form_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_tax_form,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestChannelOnboarding:
    def test_channel_create_defaults_and_initial_posture(self, api):
        """PRD §3.1: "Two payout preferences may be set at creation:
        `payout_schedule`, one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY` and
        defaulting to `MONTHLY`, and `payout_threshold_cents`, the minimum
        payable balance required to open a payout, defaulting to 10,000 cents
        (one hundred dollars)."
        PRD §3.1: "A freshly created channel starts with `monetization_posture`
        `RESTRICTED` — no verified tax form exists yet — with all balances at
        zero and `version` 1."
        PRD §2.5: "At startup the clock reads exactly 2026-08-01T00:00:00Z,
        and it never falls back to wall time."

        Design: Corner/entities/channel_create_defaults_and_initial_posture
        """
        channel = validate_success(
            api.create_channel(
                create_channel_payload(handle="corner_def",
                                       display_name="Corner Def",
                                       home_platform="TWITCH"),
                ADMIN),
            201)
        assert_channel(channel)
        assert channel["payout_schedule"] == "MONTHLY"
        assert channel["payout_threshold_cents"] == 10000
        assert channel["monetization_posture"] == "RESTRICTED"
        assert channel["balance_pending_cents"] == 0
        assert channel["balance_payable_cents"] == 0
        assert channel["lifetime_paid_cents"] == 0
        assert channel["active_strike_count"] == 0
        assert channel["version"] == 1
        assert_instant_equals(channel["created_at"], "2026-08-01T00:00:00Z",
                              label="created_at (default logical clock)")

    def test_channel_get_missing_returns_not_found(self, api):
        """PRD §2.9: "**Existence.** Path identifiers are validated left to
        right, then body-referenced identifiers — otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/channel_get_missing_returns_not_found
        """
        resp = api.get_channel(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthenticationAndOwnership:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_channel(
            create_channel_payload(handle="noauth", display_name="No Auth",
                                   home_platform="TWITCH"),
            {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_creator_cannot_write_foreign_channel(self, api):
        """PRD §2.1: "When `X-User-Role` is `Creator`, `X-User-ID` is the `id`
        of the acting `Channel`; ownership checks on any resource that
        references a channel compare the resource's channel foreign key to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_CHANNEL_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/creator_cannot_write_foreign_channel
        """
        channel_a = create_channel(handle="own_a", home_platform="TWITCH")
        channel_b = create_channel(handle="own_b", home_platform="YOUTUBE")

        resp = api.create_deal(
            channel_b["id"],
            {"sponsor_ref": "sponsor_x", "title": "foreign", "category": "OTHER",
             "total_value_cents": 1000,
             "flight_start": "2026-08-05T00:00:00Z",
             "flight_end": "2026-08-31T00:00:00Z",
             "required_deliverable_count": 1},
            make_creator_headers(channel_a["id"]))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_OWNERSHIP_MISMATCH)

        deals, _meta = validate_paginated(api.list_deals(channel_b["id"], ADMIN))
        assert all(d["title"] != "foreign" for d in deals), (
            "no deal may be persisted on channel B")


class TestTaxFormSupersession:
    def test_tax_form_reject_then_resubmit_cycle(self, api):
        """PRD §3.1: "A rejected form is never resurrected in place — it
        remains `REJECTED` as history while a new `SUBMITTED` row takes over
        as current, so the `REJECTED`-to-`SUBMITTED` arc is realized by
        supersession rather than by editing the old row."
        PRD §3.1: "Submission is **supersession**: the new form is born
        `SUBMITTED`, its `submitted_at` is stamped with the logical clock, the
        channel's `tax_form_current_id` swings to it, its `prior_form_id`
        chains back to the previously current form (null for a channel's first
        submission), the channel's `version` increments by 1, and posture is
        recomputed."
        PRD §2.7: "`STANDARD` requires the channel's active strike weight to
        be exactly zero **and** the channel's current tax form to be
        `VERIFIED`."

        Design: Corner/state_machines/tax_form_reject_then_resubmit_cycle
        """
        channel = create_channel(handle="sm_tax", home_platform="TWITCH")
        form1 = submit_tax_form(channel, legal_name="SM Tax LLC",
                                tax_id_last4="2002")
        rejected = reject_tax_form(form1["id"])
        assert rejected["tax_status"] == "REJECTED"
        assert rejected["rejection_reason"] == "illegible"

        channel_now = get_channel(channel["id"])
        form2 = validate_success(api.submit_tax_form(
            channel["id"],
            submit_tax_form_payload(channel_now["version"],
                                    legal_name="SM Tax LLC",
                                    tax_id_last4="2003"),
            make_creator_headers(channel["id"])), 201)
        assert_tax_form(form2)
        assert form2["tax_status"] == "SUBMITTED"
        assert form2["prior_form_id"] == form1["id"], (
            "the supersession chain links the new form to the rejected one")

        reread_form1 = get_success_data(api.get_tax_form(form1["id"], ADMIN))
        assert reread_form1["tax_status"] == "REJECTED", (
            "the rejected form remains REJECTED as history")

        verify_tax_form(form2["id"])
        channel_after = get_channel(channel["id"])
        assert channel_after["tax_form_current_id"] == form2["id"]
        assert channel_after["monetization_posture"] == "STANDARD"


class TestOptimisticConcurrency:
    def test_occ_channel_settings_stale_rejected(self, api):
        """PRD §2.8: "On each of these endpoints, if the supplied expected
        version does not match the parent entity's current `version` — because
        another writer has advanced that version since the client last read it
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
        client must re-read the entity before re-issuing."
        PRD §3.1: "A successful update increments the channel's `version`
        by 1; a stale expected version is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the caller to re-read the channel before its
        settings may replace the current ones."

        Design: Corner/cross_cutting/occ_channel_settings_stale_rejected
        """
        channel = create_channel(handle="cc_set", home_platform="TWITCH")
        submit_tax_form(channel, legal_name="CC Set LLC", tax_id_last4="9009")
        # The submission advanced Channel.version beyond the creation version.

        stale = api.update_payout_settings(
            channel["id"],
            payout_settings_payload(channel["version"],
                                    payout_threshold_cents=25000),
            make_creator_headers(channel["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_channel(channel["id"])
        updated = validate_success(api.update_payout_settings(
            channel["id"],
            payout_settings_payload(fresh["version"],
                                    payout_threshold_cents=25000),
            make_creator_headers(channel["id"])), 200)
        assert updated["payout_threshold_cents"] == 25000
        assert updated["version"] == fresh["version"] + 1, (
            "a successful update increments the channel's version by exactly 1")

    def test_occ_tax_form_supersede_stale_rejected(self, api):
        """PRD §2.8: "`POST /api/channels/{channel_id}/tax-forms` requires the
        same `expected_channel_version` input, since a submission supersedes
        the channel's current form."
        PRD §2.8: "On each of these endpoints, if the supplied expected
        version does not match the parent entity's current `version` — because
        another writer has advanced that version since the client last read it
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
        client must re-read the entity before re-issuing."

        Design: Corner/cross_cutting/occ_tax_form_supersede_stale_rejected
        """
        channel = create_channel(handle="cc_tax", home_platform="YOUTUBE")
        form1 = submit_tax_form(channel, legal_name="CC Tax LLC",
                                tax_id_last4="1010")

        stale = api.submit_tax_form(
            channel["id"],
            submit_tax_form_payload(channel["version"], form_type="W8BEN",
                                    legal_name="CC Tax Intl",
                                    tax_id_last4="1011"),
            make_creator_headers(channel["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        channel_after = get_channel(channel["id"])
        assert channel_after["tax_form_current_id"] == form1["id"], (
            "the stale supersession persists no second form")


class TestTaxFormExpiryCascade:
    def _setup_held_payout_scenario(self):
        """Verified W9 channel (verified at the default clock), one cleared
        TIP of 100000, and an open SCHEDULED payout; clock then advanced one
        year past the form's expiry."""
        channel = create_channel(handle="tc_tax", home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        form = submit_tax_form(channel, legal_name="TC Tax LLC",
                               tax_id_last4="5555")
        verify_tax_form(form["id"])
        ingest_revenue_event(channel["id"], kind="TIP", gross_cents=100000,
                             platform_fee_bps=0,
                             occurred_at="2026-08-02T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run_ops()
        payout = open_payout(channel["id"])
        set_clock("2027-08-02T00:00:00Z")
        run_ops()
        return channel, form, payout

    def test_tax_form_expiry_drops_posture_to_restricted(self, api):
        """PRD §3.1: "Forms do not stay valid forever: when an ops run finds
        the clock at or past the current form's `expires_on`, that form
        becomes `EXPIRED`, the posture is recomputed — dropping the channel to
        `RESTRICTED` when no other `VERIFIED` form remains — and the §2.7
        cascade moves the channel's `SCHEDULED` payouts to `HELD` with
        `hold_reason` `TAX_FORM`."

        Design: Difficulty/transitive_cascade/tax_form_expiry_payout_hold_cascade
        """
        channel, form, _payout = self._setup_held_payout_scenario()

        expired = get_success_data(api.get_tax_form(form["id"], ADMIN))
        assert expired["tax_status"] == "EXPIRED"
        channel_after = get_channel(channel["id"])
        assert channel_after["monetization_posture"] == "RESTRICTED", (
            "no VERIFIED form remains after expiry, so the posture drops")

    def test_tax_form_expiry_holds_scheduled_payout(self, api):
        """PRD §3.1: "Forms do not stay valid forever: when an ops run finds
        the clock at or past the current form's `expires_on`, that form
        becomes `EXPIRED`, the posture is recomputed — dropping the channel to
        `RESTRICTED` when no other `VERIFIED` form remains — and the §2.7
        cascade moves the channel's `SCHEDULED` payouts to `HELD` with
        `hold_reason` `TAX_FORM`."

        Design: Difficulty/transitive_cascade/tax_form_expiry_payout_hold_cascade
        """
        channel, _form, payout = self._setup_held_payout_scenario()

        payouts = get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
        held = [p for p in payouts if p["id"] == payout["id"]]
        assert len(held) == 1
        assert held[0]["payout_status"] == "HELD"
        assert held[0]["hold_reason"] == "TAX_FORM", (
            "the tax-expiry cascade stamps the hold reason TAX_FORM")
