"""Site onboarding defaults, stall catalog uniqueness, pagination envelope,
and the rate-plan lifecycle (activation, supersession, retirement, OCC)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_booking,
    assert_rate_plan,
    assert_site,
    assert_stall,
    create_reserved_booking,
    create_site,
    create_site_payload,
    create_site_with_stalls,
    create_stall,
    register_driver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteCreation:

    def test_site_creation_applies_defaults(self):
        """PRD section 3.1: "Creation initializes the site's `posture` to
        `NORMAL` and `ops_run_index` to 0, and automatically mints a default
        rate plan in `ACTIVE` status populated with the catalog constants
        described in §3.2; this automatic plan does not count as a site
        mutation, so the new site's `version` remains 1."
        PRD section 3.1: "`no_show_grace_minutes` (default 60 minutes after the
        check-in window opens before a missing arrival is declared a no-show),
        `overstay_grace_minutes` (default 30 minutes past the checkout deadline
        before a guest is marked as overstaying), and
        `cancellation_free_window_hours` (default 24 hours before window open
        within which cancellation stops being free)."

        Design: Corner/entities/site_creation_applies_defaults_and_initial_posture
        """
        resp = api_client.create_site(
            create_site_payload(name="S", base_nightly_rate_cents=5000), ADMIN)
        site = validate_success(resp, expected_status=201)
        assert_site(site)
        assert site["no_show_grace_minutes"] == 60
        assert site["overstay_grace_minutes"] == 30
        assert site["cancellation_free_window_hours"] == 24
        assert site["posture"] == "NORMAL"
        assert site["ops_run_index"] == 0
        assert site["version"] == 1

        resp = api_client.list_rate_plans(site["id"], ADMIN,
                                          params={"status": "ACTIVE"})
        plans, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, \
            f"exactly one ACTIVE plan must exist, got {meta['total_count']}"
        assert plans[0]["status"] == "ACTIVE"

    def test_site_create_with_posture_input_ignored(self):
        """PRD section 3.8: "Posture is derived, never set directly."
        PRD section 3.1: "Creation initializes the site's `posture` to
        `NORMAL` and `ops_run_index` to 0".

        Design: Corner/entities/site_create_with_posture_input_ignored
        """
        resp = api_client.create_site(
            create_site_payload(name="S", base_nightly_rate_cents=5000,
                                posture="ESCALATED"),
            ADMIN,
        )
        site = validate_success(resp, expected_status=201)
        assert_site(site)
        assert site["posture"] == "NORMAL", (
            f"client-supplied computed field posture must be ignored, "
            f"got {site['posture']}"
        )

    def test_sites_list_pagination_envelope(self):
        """PRD section 2.3: "`limit` caps the number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        skips that many items and defaults to 0."
        PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/sites_list_pagination_envelope
        """
        for i in range(1, 13):
            create_site(name=f"S{i:02d}")
        page1, meta1 = validate_paginated(api_client.list_sites(ADMIN))
        assert len(page1) == 10, f"default page size 10, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_sites(ADMIN, params={"limit": 10, "offset": 10}))
        assert len(page2) == 2, f"offset page holds 2 items, got {len(page2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_booking_get_not_found_returns_404(self):
        """PRD section 2.6: "Requests that address nested resources validate
        path identifiers left to right, rejecting with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not exist."

        Design: Corner/entities/booking_get_not_found_returns_404
        """
        resp = api_client.get_booking(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestStallCatalog:

    def test_duplicate_stall_number_rejected(self):
        """PRD section 3.1: "Each stall carries a `stall_number` unique within
        its site (a duplicate is refused with `ERR_DUPLICATE_STALL_NUMBER`)".

        Design: Corner/entities/duplicate_stall_number_rejected
        """
        s1 = create_site(name="S1")
        s2 = create_site(name="S2")
        stall = create_stall(s1["id"], "R01", is_reservable=True)
        assert_stall(stall)

        resp = api_client.create_stall(
            s1["id"],
            {"stall_number": "R01", "stall_class": "STANDARD",
             "is_reservable": True},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STALL_NUMBER)

        resp = api_client.create_stall(
            s2["id"],
            {"stall_number": "R01", "stall_class": "STANDARD",
             "is_reservable": True},
            ADMIN,
        )
        other_site = validate_success(resp, expected_status=201)
        assert other_site["stall_number"] == "R01", \
            "uniqueness is per-site: the same number on another site is legal"


class TestRatePlanLifecycle:

    def test_rate_plan_activation_supersedes_and_keeps_pinned_rates(self):
        """PRD section 3.1: "Activation — `to` equal to `ACTIVE`, carrying the
        optimistic-concurrency field described in §2.9 — moves the plan `DRAFT`
        → `ACTIVE`, flips the site's previously `ACTIVE` plan to `SUPERSEDED`,
        and increments the site `version` by one; exactly one plan is `ACTIVE`
        per site at all times."
        PRD section 3.1: "Supersession never disturbs history: existing
        bookings keep their pinned `per_night_rates`, and only future quotes
        read the new plan."

        Design: Corner/endpoints/rate_plan_activation_supersedes_and_reprices
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-RP-1", "R Pee")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)
        assert booking["quoted_total_cents"] == 4500, \
            "default plan at 0% occupancy: 5000 * 0.9"

        resp = api_client.create_rate_plan(site["id"], {"mult_low": 1.0}, ADMIN)
        draft = validate_success(resp, expected_status=201)
        assert draft["status"] == "DRAFT"

        resp = api_client.transition_rate_plan(
            site["id"], draft["id"],
            {"to": "ACTIVE", "expected_site_version": site["version"]},
            ADMIN,
        )
        activated = validate_success(resp, expected_status=200)
        assert activated["status"] == "ACTIVE"

        plans, meta = validate_paginated(
            api_client.list_rate_plans(site["id"], ADMIN,
                                       params={"status": "SUPERSEDED"}))
        assert meta["total_count"] == 1, \
            "the default plan must flip to SUPERSEDED"
        assert plans[0]["status"] == "SUPERSEDED"

        resp = api_client.get_booking(booking["id"], ADMIN)
        before = validate_success(resp)
        assert before["quoted_total_cents"] == 4500, \
            "existing bookings keep their pinned rates after supersession"

        driver2 = register_driver("CDL-RQ-1", "R Que")
        booking2 = create_reserved_booking(driver2["id"], site["id"],
                                           "2026-08-12", 1)
        assert_booking(booking2)
        assert booking2["quoted_total_cents"] == 5000, (
            f"new quotes read the new plan (mult_low 1.0), got "
            f"{booking2['quoted_total_cents']}"
        )

    def test_retire_draft_plan_ok_retire_active_rejected(self):
        """PRD section 3.1: "Retirement — `to` equal to `RETIRED` — is
        permitted for `DRAFT` or `SUPERSEDED` plans and lands the plan in the
        terminal `RETIRED` state; retiring the currently `ACTIVE` plan is
        rejected with `ERR_INVALID_STATE`, because a replacement must be
        activated first — activation supersedes it, after which it may be
        retired."

        Design: Corner/endpoints/retire_draft_plan_ok_retire_active_rejected
        """
        site = create_site(name="S")
        resp = api_client.create_rate_plan(site["id"], {}, ADMIN)
        draft = validate_success(resp, expected_status=201)

        resp = api_client.transition_rate_plan(
            site["id"], draft["id"],
            {"to": "RETIRED", "expected_site_version": site["version"]},
            ADMIN,
        )
        retired = validate_success(resp, expected_status=200)
        assert retired["status"] == "RETIRED"

        plans, _ = validate_paginated(
            api_client.list_rate_plans(site["id"], ADMIN,
                                       params={"status": "ACTIVE"}))
        default_plan = plans[0]
        resp = api_client.transition_rate_plan(
            site["id"], default_plan["id"],
            {"to": "RETIRED", "expected_site_version": site["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_rate_plan_activation_stale_version(self):
        """PRD section 2.9: "Activating a rate plan requires the request to
        carry `expected_site_version` equal to the site's current `version`.
        Activation supersedes whatever plan is currently `ACTIVE`; a request
        still carrying the site version observed before another activation
        committed would supersede a plan the client never saw, so it is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_rate_plan_activation_stale_version
        """
        site = create_site(name="S")
        observed_version = site["version"]
        p1 = validate_success(
            api_client.create_rate_plan(site["id"], {"mult_low": 1.1}, ADMIN),
            expected_status=201)
        p2 = validate_success(
            api_client.create_rate_plan(site["id"], {"mult_low": 1.2}, ADMIN),
            expected_status=201)

        resp = api_client.transition_rate_plan(
            site["id"], p1["id"],
            {"to": "ACTIVE", "expected_site_version": observed_version},
            ADMIN,
        )
        activated = validate_success(resp, expected_status=200)
        assert activated["status"] == "ACTIVE"
        assert_rate_plan(activated)

        resp = api_client.get_site(site["id"], ADMIN)
        site_after = validate_success(resp)
        assert site_after["version"] == observed_version + 1, \
            "activation increments the site version by one"

        resp = api_client.transition_rate_plan(
            site["id"], p2["id"],
            {"to": "ACTIVE", "expected_site_version": observed_version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        plans, _ = validate_paginated(
            api_client.list_rate_plans(site["id"], ADMIN,
                                       params={"status": "DRAFT"}))
        assert any(p["id"] == p2["id"] for p in plans), \
            "the stale activation must leave the second plan DRAFT"
