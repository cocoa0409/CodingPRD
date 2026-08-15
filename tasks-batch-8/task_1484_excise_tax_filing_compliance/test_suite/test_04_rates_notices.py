"""Rate schedule, rate windows, rate-change notices, and re-rating
(PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    apply_notice,
    create_and_activate_bond,
    create_classified_event,
    create_jurisdiction,
    create_pending_registration,
    create_product_class,
    create_registrant,
    create_tax_rate,
    create_validated_notice,
    new_admin_headers,
    new_analyst_headers,
    rate_event,
    setup_active_registration,
    setup_filed_return,
    setup_return_with_rated_event,
    validate_error,
    validate_success,
)


class TestRateWindows:
    def test_rate_window_adjacent_create_accepted(self, api):
        """PRD §3.2: "Windows of the same jurisdiction–product-class pair must
        never overlap, though adjacency — one window's `effective_from`
        equalling the prior window's `effective_to` — is allowed".

        Design: Difficulty/resource_temporal_overlap/tax_rate_half_open_window_adjacency
        """
        jur = create_jurisdiction()
        pc = create_product_class()
        create_tax_rate(jur["id"], pc["id"], 24300,
                        effective_from="2026-01-01T00:00:00Z",
                        effective_to="2026-09-01T00:00:00Z")
        adjacent = validate_success(api.create_tax_rate(
            {"jurisdiction_id": jur["id"], "product_class_id": pc["id"],
             "rate_millicents_per_unit": 30000,
             "effective_from": "2026-09-01T00:00:00Z"},
            new_admin_headers()), expected_status=201)
        assert adjacent["rate_millicents_per_unit"] == 30000

    def test_rate_window_interior_overlap_rejected(self, api):
        """PRD §3.2: "Windows of the same jurisdiction–product-class pair must
        never overlap, though adjacency — one window's `effective_from`
        equalling the prior window's `effective_to` — is allowed; an
        overlapping creation is rejected with `ERR_RATE_WINDOW_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/tax_rate_half_open_window_adjacency
        """
        jur = create_jurisdiction()
        pc = create_product_class()
        create_tax_rate(jur["id"], pc["id"], 24300,
                        effective_from="2026-01-01T00:00:00Z",
                        effective_to="2026-09-01T00:00:00Z")
        resp = api.create_tax_rate(
            {"jurisdiction_id": jur["id"], "product_class_id": pc["id"],
             "rate_millicents_per_unit": 31000,
             "effective_from": "2026-08-15T00:00:00Z",
             "effective_to": "2026-12-01T00:00:00Z"},
            new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)

    def test_rate_scheduled_to_active_on_sweep(self, api):
        """PRD §3.2: "The rate's own `status` is derived from its window
        against the logical clock: `SCHEDULED` when `effective_from` lies in
        the future, `ACTIVE` when the window contains the current instant" and
        "The clock sweep moves rates from `SCHEDULED` to `ACTIVE`".

        Design: Corner/state_machines/rate_scheduled_to_active_on_sweep
        """
        jur = create_jurisdiction()
        pc = create_product_class("GASOLINE")
        rate = create_tax_rate(jur["id"], pc["id"], 41100,
                               effective_from="2026-09-01T00:00:00Z")
        assert rate["status"] == "SCHEDULED", (
            "clock 2026-08-01 precedes effective_from 2026-09-01")

        admin = new_admin_headers()
        validate_success(api.set_clock("2026-09-01T00:00:00Z", admin))
        active = validate_success(api.get_tax_rate(rate["id"], admin))
        assert active["status"] == "ACTIVE"


class TestRateResolution:
    def test_no_applicable_rate_for_predated_event(self, api):
        """PRD §3.2: "when none does, rating fails with
        `ERR_NO_APPLICABLE_RATE`" (no rate window contains the event date).

        Design: Corner/calculations/no_applicable_rate_for_predated_event
        """
        ctx = setup_active_registration()
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            event_date="2025-12-31T00:00:00Z", quantity_units=100)
        resp = api.rate_event(ev["id"], {}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_NO_APPLICABLE_RATE)

    def test_rate_window_boundary_uses_new_rate(self, api):
        """PRD §2.7: "An event dated exactly at a window's `effective_from`
        belongs to that window; an event dated exactly at its `effective_to`
        belongs to the next window — or fails rate resolution if none exists."

        Design: Corner/calculations/rate_window_boundary_uses_new_rate
        """
        # Schedule: [2026-01-01, 2026-09-01) @24300 then [2026-09-01, ..) @30000.
        jur = create_jurisdiction()
        pc = create_product_class("DIESEL")
        create_tax_rate(jur["id"], pc["id"], 24300,
                        effective_from="2026-01-01T00:00:00Z",
                        effective_to="2026-09-01T00:00:00Z")
        create_tax_rate(jur["id"], pc["id"], 30000,
                        effective_from="2026-09-01T00:00:00Z")
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        create_and_activate_bond(rgn["id"])
        validate_success(
            api.activate_registration(rgn["id"], new_admin_headers()))
        registration = {"id": rgn["id"]}

        ev_old = create_classified_event(
            registration, jur, pc,
            event_date="2026-08-31T00:00:00Z", quantity_units=1000)
        rated_old = rate_event(ev_old["id"])
        assert rated_old["tax_cents"] == 24300, (
            "2026-08-31 still belongs to the old [01-01, 09-01) window")

        ev_new = create_classified_event(
            registration, jur, pc,
            event_date="2026-09-01T00:00:00Z", quantity_units=1000)
        rated_new = rate_event(ev_new["id"])
        assert rated_new["tax_cents"] == 30000, (
            "the seam date belongs to the new window (half-open start)")

    def test_rounding_half_up_at_exact_half_cent(self, api):
        """PRD §2.6: "each event's tax is rounded half-up to whole cents at
        rating time" — 1 unit at 24500 milli-cents is 24.5 cents, which
        rounds half-up to 25 (not banker's 24).

        Design: Corner/calculations/rounding_half_up_at_exact_half_cent
        """
        ctx = setup_active_registration(product_class_code="KEROSENE",
                                        rate_millicents=24500)
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=1)
        rated = rate_event(ev["id"])
        assert rated["tax_cents"] == 25, (
            "round_half_up(24.5) == 25; banker's rounding would give 24")


class TestRateChangeNoticeApply:
    def _setup_retroactive_notice(self):
        """DRAFT return with one rated 1000-unit event at 24300mc, plus a
        VALIDATED notice raising the class to 30000mc from 2026-08-01."""
        ctx, ev, ret = setup_return_with_rated_event()
        rate_old = ctx["rates"][ctx["product_class"]["id"]]
        ntc = create_validated_notice(
            ctx["jurisdiction"], ctx["product_class"], 30000,
            "2026-08-01T00:00:00Z", source_reference="BULL-2026-08")
        return ctx, ev, ret, rate_old, ntc

    def test_retroactive_apply_supersedes_prior_rate(self, api):
        """PRD §3.3: "Applying a `VALIDATED` notice creates a new tax rate
        whose `effective_from` equals the notice's
        `announced_effective_from`, whose `effective_to` equals the clamped
        prior window's end, whose `source_notice_id` points at the notice, and
        whose `supersedes_rate_id` points at the rate it replaces; the prior
        rate's `effective_to` is clamped to the announced start and its status
        becomes `SUPERSEDED`, and the jurisdiction's `version` increments by
        one."
        PRD §3.3: "The notice finishes in `APPLIED` with its `applied_rate_id`
        set to the rate it created."

        Design: Difficulty/transitive_cascade/retroactive_rate_apply_cascade
        """
        ctx, _ev, _ret, rate_old, ntc = self._setup_retroactive_notice()
        applied = apply_notice(ntc["id"], ctx["jurisdiction"]["id"])
        assert applied["status"] == "APPLIED"
        assert applied["applied_rate_id"], "applied_rate_id must be set"

        old = validate_success(
            api.get_tax_rate(rate_old["id"], new_admin_headers()))
        assert old["status"] == "SUPERSEDED"
        assert old["effective_to"].startswith("2026-08-01T00:00:00"), (
            "prior window is clamped to the announced start")

    def test_retroactive_apply_rerates_open_return_and_rolls_up(self, api):
        """PRD §3.3: "The retroactive cascade then re-rates every taxable
        event whose `event_date` falls inside the new window and whose status
        is `RATED`, but only while its containing return is still in `DRAFT`
        or `SUBMITTED`" and "Every affected return's totals are recomputed and
        its `version` bumped; the registrant's aggregate liability and the
        registration's bond requirement are recomputed, which may flip the
        registration between `ACTIVE` and `BOND_DEFICIENT`.".

        Design: Difficulty/transitive_cascade/retroactive_rate_apply_cascade
        """
        ctx, ev, ret, _rate_old, ntc = self._setup_retroactive_notice()
        apply_notice(ntc["id"], ctx["jurisdiction"]["id"])

        event = validate_success(
            api.get_taxable_event(ev["id"], new_analyst_headers()))
        assert event["tax_cents"] == 30000, (
            "re-rated at 30000mc (was 24300)")

        ret_after = validate_success(
            api.get_return(ret["id"], new_analyst_headers()))
        assert ret_after["gross_tax_cents"] == 30000
        assert ret_after["taxable_tax_cents"] == 30000

        rgt = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert rgt["aggregate_open_liability_cents"] == 30000


class TestNoticeApplyOcc:
    def test_occ_notice_apply_stale_jurisdiction_rejected(self, api):
        """PRD §2.8: "Applying a rate-change notice requires the request body
        to carry `expected_jurisdiction_version` equal to the jurisdiction's
        current `version`. Notice application supersedes rates and increments
        the jurisdiction's version, so a stale presentation is rejected with
        `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the rate
        schedule is stale."

        Design: Corner/cross_cutting_layers/occ_notice_apply_stale_jurisdiction_rejected
        """
        jur = create_jurisdiction()
        pc = create_product_class()
        create_tax_rate(jur["id"], pc["id"], 24300)
        ntc1 = create_validated_notice(jur, pc, 30000, "2026-08-01T00:00:00Z",
                                       source_reference="BULL-1")
        ntc2 = create_validated_notice(jur, pc, 31000, "2026-09-01T00:00:00Z",
                                       source_reference="BULL-2")
        admin = new_admin_headers()
        jv = validate_success(api.get_jurisdiction(jur["id"], admin))["version"]

        first = validate_success(api.apply_rate_change_notice(
            ntc1["id"], {"expected_jurisdiction_version": jv}, admin))
        assert first["status"] == "APPLIED"

        resp = api.apply_rate_change_notice(
            ntc2["id"], {"expected_jurisdiction_version": jv}, admin)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestPinnedSnapshot:
    def test_version_pinning_filed_return_immune_to_retro_rate(self, api):
        """PRD §3.3: "events inside `FILED` returns are never touched, because
        each filed return's pinned rate snapshot governs them."
        PRD §3.6: "The `pinned_rate_snapshot` records, for each product class
        taxed, the `product_class_id`, the `tax_rate_id`, and the
        `rate_millicents_per_unit` actually used; once filed it is immutable".

        Design: Corner/cross_cutting_layers/version_pinning_filed_return_immune_to_retro_rate
        """
        ctx, ev, filed = setup_filed_return()
        rate_old = ctx["rates"][ctx["product_class"]["id"]]
        ntc = create_validated_notice(
            ctx["jurisdiction"], ctx["product_class"], 30000,
            "2026-08-01T00:00:00Z", source_reference="BULL-RETRO")
        apply_notice(ntc["id"], ctx["jurisdiction"]["id"])

        ret = validate_success(
            api.get_return(filed["id"], new_analyst_headers()))
        assert ret["filing_status"] == "FILED"
        assert ret["gross_tax_cents"] == 24300, (
            "filed return totals are pinned, not re-rated")
        snap = ret["pinned_rate_snapshot"]
        assert len(snap) == 1
        assert snap[0]["rate_millicents_per_unit"] == 24300
        assert snap[0]["tax_rate_id"] == rate_old["id"]

        event = validate_success(
            api.get_taxable_event(ev["id"], new_analyst_headers()))
        assert event["status"] == "RETURNED"
        assert event["tax_cents"] == 24300
