"""Template lifecycle and cycle opening: publication, issuance, OCC, pinning
(PRD §3.2, §3.3, §2.6, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_cycle,
    assert_instant_equal,
    create_cycle_payload,
    create_template_payload,
    create_vendor_payload,
    get_success_data,
    issue_cycle,
    open_cycle,
    register_vendor,
    create_published_template,
    setup_active_policy,
    setup_issued_cycle,
    TEST_USERS,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["risk_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestTemplateLifecycle:
    def test_publish_already_published_template_rejected(self, api):
        """PRD §3.2: "Publication moves a template `DRAFT → PUBLISHED`."
        PRD §2.9: "State permission — the target resource must be in a state that
        permits the requested transition; failures yield `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/template_publish_from_published_returns_invalid_state
        """
        template = create_published_template(tiers=("TIER_1",))
        res = api.publish_template(template["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_retire_blocked_while_cycle_references_template(self, api):
        """PRD §3.2: "Retirement moves a template `PUBLISHED → RETIRED`, the terminal
        state, and is blocked with `ERR_TEMPLATE_IN_USE` (HTTP 409) while any
        assessment cycle still references the template in a non-terminal status —
        that is, in `DRAFT`, `ISSUED`, `RESPONSE_RECEIVED`, `SCORED`,
        `EVIDENCE_REVIEW`, `REMEDIATION`, or `RISK_ACCEPTANCE_REVIEW`."

        Design: Corner/state_machines/template_retire_blocked_while_in_use
        """
        ctx = setup_issued_cycle()  # cycle ISSUED against the template
        res = api.retire_template(ctx["template"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_TEMPLATE_IN_USE)

    def test_issue_against_unpublished_template_rejected(self, api):
        """PRD §3.3: "A `RiskAnalyst` may issue the cycle only when the vendor's
        posture is `ONBOARDING`, `APPROVED`, or `CONDITIONAL`, when the cycle is
        exactly the vendor's current active cycle, when the pinned template is
        `PUBLISHED` at issue time (otherwise `ERR_TEMPLATE_NOT_PUBLISHED`,
        HTTP 422), and when no other cycle for the vendor sits in a non-terminal
        state."

        Design: Corner/errors/error_template_not_published_on_issue
        """
        setup_active_policy()
        template = get_success_data(api.create_template(create_template_payload(), ANALYST))
        assert template["status"] == "DRAFT"
        vendor, _contact = register_vendor()
        cycle = open_cycle(vendor["id"], template["id"])
        res = api.issue_cycle(vendor["id"], cycle["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED)


class TestCycleOpening:
    def test_new_cycle_starts_in_draft(self, api):
        """PRD §3.3: "A new cycle starts in `DRAFT`, immediately becomes the vendor's
        `active_cycle_id`, and bumps the vendor's `version` by one."

        Design: Corner/state_machines/cycle_initial_state_is_draft
        """
        setup_active_policy()
        template = create_published_template(tiers=("TIER_2",))
        vendor, _contact = register_vendor(tier="TIER_2")
        cycle = validate_success(
            api.create_cycle(
                vendor["id"],
                create_cycle_payload(template["id"], vendor["version"]),
                ANALYST,
            ),
            201,
        )
        assert_cycle(cycle)
        assert cycle["status"] == "DRAFT"
        assert cycle["vendor_id"] == vendor["id"]

    def test_second_active_cycle_rejected(self, api):
        """PRD §3.3: "A vendor may have at most one non-terminal cycle at a time;
        attempting to open a second while one is in flight is rejected with
        `ERR_CYCLE_ALREADY_ACTIVE` (HTTP 409)."

        Design: Corner/validations/cycle_create_second_active_cycle_rejected
        """
        setup_active_policy()
        template = create_published_template()
        vendor, _contact = register_vendor()
        open_cycle(vendor["id"], template["id"])
        fresh = get_success_data(api.get_vendor(vendor["id"], ANALYST))
        res = api.create_cycle(
            vendor["id"],
            create_cycle_payload(template["id"], fresh["version"]),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_CYCLE_ALREADY_ACTIVE)

    def test_cycle_create_with_stale_vendor_version_rejected(self, api):
        """PRD §2.7: "Creating an assessment cycle requires `expected_vendor_version`,
        carrying the client's last-observed `version` of the target vendor. If the
        vendor's current `version` has advanced beyond that value — because another
        writer has since issued, closed, or otherwise mutated the vendor — the create
        is rejected with `ERR_STALE_VENDOR_VERSION` (HTTP 412), so the client cannot
        act on a vendor record it has not observed."
        PRD §3.1: "The result is stored on the vendor as `current_tier`, and any
        attribute revision also refreshes the vendor's `risk_score` and increments
        the vendor's `version` by one."

        Design: Corner/endpoints/occ_cycle_create_stale_vendor_version
        """
        setup_active_policy()
        template = create_published_template()
        vendor, _contact = register_vendor()
        stale_version = vendor["version"]
        # An attribute revision advances the vendor's version (PRD §3.1).
        get_success_data(api.patch_vendor(vendor["id"], {"legal_name": "Renamed Co"}, ANALYST))
        res = api.create_cycle(
            vendor["id"],
            create_cycle_payload(template["id"], stale_version),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VENDOR_VERSION)

    def test_issuance_pins_template_version(self, api):
        """PRD §3.3: "It then pins the questionnaire contract: the cycle's
        `template_id` and `template_version` are set to the template's current
        `published_version`, and later re-publication of that template never affects
        the in-flight cycle."

        Design: Corner/cross_cutting_layers/version_pinning_template_on_cycle_issuance
        """
        setup_active_policy()
        template = create_published_template()
        published = get_success_data(api.get_template(template["id"], ANALYST))
        vendor, _contact = register_vendor()
        cycle = open_cycle(vendor["id"], template["id"])
        cycle = issue_cycle(vendor["id"], cycle["id"])
        assert cycle["template_id"] == template["id"]
        assert cycle["template_version"] == published["published_version"]
        # A revision creates an independent DRAFT and does not disturb the pin.
        revised = validate_success(api.revise_template(template["id"], ANALYST), 201)
        assert revised["status"] == "DRAFT"
        assert revised["id"] != template["id"]
        cycle_after = get_success_data(api.get_cycle(cycle["id"], ANALYST))
        assert cycle_after["template_version"] == published["published_version"]

    def test_issuance_uses_default_clock_and_tier_window(self, api):
        """PRD §2.6: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, every time-dependent
        rule evaluates against that instant."
        PRD §3.3: "The cycle's `issued_at` is set to the current clock, and
        `response_due_at` is computed as `issued_at` plus the tier's response
        window — 45 days for `TIER_1`, 30 days for `TIER_2`, 21 days for `TIER_3`,
        and 14 days for `TIER_4`."

        Design: Corner/cross_cutting_layers/scheduled_deferred_clock_default
        """
        setup_active_policy()
        template = create_published_template()
        vendor, _contact = register_vendor()
        cycle = open_cycle(vendor["id"], template["id"])
        cycle = issue_cycle(vendor["id"], cycle["id"])
        assert_instant_equal(cycle["issued_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(cycle["response_due_at"], "2026-09-15T00:00:00Z")


class TestReverseReachability:
    def test_child_collections_reachable_from_parent(self, api):
        """PRD §3.3: "A vendor's cycles can be listed with a `status` filter, and
        any cycle can be fetched directly by its `id`."
        PRD §3.8: "Alerts can be listed with a `status` filter."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        from test_helpers import create_alert, validate_paginated

        ctx = setup_issued_cycle()
        alert = create_alert(ctx["vendor"]["id"], signal="SCAN_FINDING", severity="LOW")
        cycles, _meta = validate_paginated(api.list_cycles(ctx["vendor"]["id"], ANALYST))
        assert any(c["id"] == ctx["cycle"]["id"] for c in cycles), "Cycle must appear under its vendor"
        alerts, _meta = validate_paginated(api.list_alerts(ctx["vendor"]["id"], ANALYST))
        assert any(a["id"] == alert["id"] for a in alerts), "Alert must appear under its vendor"
