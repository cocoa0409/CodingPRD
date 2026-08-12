"""Punch-list rework loop, turnover request/accept gates, readiness snapshot
pinning, OCC on acceptance, store opening, and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    accept_turnover_now,
    assert_punch_item,
    create_punch_item,
    read_punch_item,
    read_site,
    read_turnover,
    request_turnover_ok,
    setup_site_in_punch,
    setup_site_in_turnover,
    setup_site_open,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestPunchReworkLoop:
    def test_punch_item_failed_verification_reopen_cycle(self, api,
                                                         site_superintendent_headers,
                                                         operations_lead_headers):
        """PRD §3.7: "Failed verification sends the item back from `RESOLVED`
        to `OPEN`, takes a `failure_note`, increments `reopen_count` by 1, and
        recomputes the counts — the rework loop can cycle as many times as
        needed."
        PRD §3.7: "`punch_open_critical_count` must be zero
        (`ERR_PUNCH_CRITICAL_OPEN`)"

        Design: Difficulty/non_linear_state_machine/punch_item_failed_verification_reopen_cycle
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        item = create_punch_item(site_id, severity="CRITICAL",
                                 description="Broken storefront glass")
        validate_success(api.resolve_punch_item(item["id"],
                                                headers=site_superintendent_headers))

        resp = api.fail_punch_item_verification(
            item["id"], {"failure_note": "glass still cracked"},
            headers=operations_lead_headers)
        item = validate_success(resp)
        assert item["status"] == "OPEN"
        assert item["reopen_count"] == 1

        # While reopened the critical count is back to 1 and blocks turnover.
        resp = api.create_turnover({"site_id": site_id},
                                   headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_PUNCH_CRITICAL_OPEN)

        validate_success(api.resolve_punch_item(item["id"],
                                                headers=site_superintendent_headers))
        resp = api.verify_punch_item(item["id"], headers=operations_lead_headers)
        assert validate_success(resp)["status"] == "VERIFIED"
        assert read_site(site_id)["punch_open_critical_count"] == 0

    def test_reopen_count_increments_on_every_failed_verification(
            self, api, site_superintendent_headers, operations_lead_headers):
        """PRD §3.7: "Failed verification sends the item back from `RESOLVED`
        to `OPEN`, takes a `failure_note`, increments `reopen_count` by 1, and
        recomputes the counts — the rework loop can cycle as many times as
        needed."

        Design: Difficulty/non_linear_state_machine/punch_item_failed_verification_reopen_cycle
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        item = create_punch_item(site_id, severity="CRITICAL",
                                 description="Broken storefront glass")
        for expected_reopens in (1, 2):
            validate_success(api.resolve_punch_item(item["id"],
                                                    headers=site_superintendent_headers))
            resp = api.fail_punch_item_verification(
                item["id"], {"failure_note": f"still cracked pass {expected_reopens}"},
                headers=operations_lead_headers)
            item = validate_success(resp)
            assert item["status"] == "OPEN"
            assert item["reopen_count"] == expected_reopens

        validate_success(api.resolve_punch_item(item["id"],
                                                headers=site_superintendent_headers))
        resp = api.verify_punch_item(item["id"], headers=operations_lead_headers)
        item = validate_success(resp)
        assert_punch_item(item)
        assert item["status"] == "VERIFIED"
        assert read_site(site_id)["punch_open_critical_count"] == 0


class TestTurnoverCriticalGate:
    def test_critical_punch_count_zero_gate_turnover(self, api,
                                                     site_superintendent_headers,
                                                     operations_lead_headers):
        """PRD §3.7: "The site must be in `PUNCH` (`ERR_INVALID_STATE`
        otherwise), `punch_open_critical_count` must be zero
        (`ERR_PUNCH_CRITICAL_OPEN`), and no other turnover may already sit
        `REQUESTED` for the site (`ERR_TURNOVER_ALREADY_REQUESTED`)."
        PRD §3.7: "`punch_open_critical_count`, the `CRITICAL` items sitting
        in `OPEN` or `RESOLVED`"

        Design: Difficulty/boundary_precision_check/critical_punch_count_zero_gate_turnover
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        item = create_punch_item(site_id, severity="CRITICAL",
                                 description="Fire exit signage misaligned")
        # RESOLVED still counts as open until verified: count stays 1.
        validate_success(api.resolve_punch_item(item["id"],
                                                headers=site_superintendent_headers))
        assert read_site(site_id)["punch_open_critical_count"] == 1

        resp = api.create_turnover({"site_id": site_id},
                                   headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_PUNCH_CRITICAL_OPEN)

        # At exactly zero the gate opens.
        validate_success(api.verify_punch_item(item["id"],
                                               headers=operations_lead_headers))
        assert read_site(site_id)["punch_open_critical_count"] == 0
        resp = api.create_turnover({"site_id": site_id},
                                   headers=site_superintendent_headers)
        turnover = validate_success(resp, expected_status=201)
        assert turnover["status"] == "REQUESTED"
        assert read_site(site_id)["status"] == "TURNOVER"

    def test_turnover_request_ignores_noncritical_open_items(
            self, api, site_superintendent_headers):
        """PRD §3.7: "`punch_open_critical_count` must be zero
        (`ERR_PUNCH_CRITICAL_OPEN`)"
        PRD §3.7: "The request lands `REQUESTED`, pins a `readiness_snapshot`
        capturing the site's `readiness_posture`, `punch_open_critical_count`,
        `punch_open_total_count`, and `forecast_open_on` at that instant, and
        automatically moves the site from `PUNCH` to `TURNOVER`, incrementing
        its `version`."

        Design: Difficulty/boundary_precision_check/critical_punch_count_zero_gate_turnover
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        create_punch_item(site_id, severity="MAJOR", description="HVAC imbalance")

        site = read_site(site_id)
        assert site["punch_open_critical_count"] == 0
        assert site["punch_open_total_count"] == 1
        resp = api.create_turnover({"site_id": site_id},
                                   headers=site_superintendent_headers)
        turnover = validate_success(resp, expected_status=201)
        assert turnover["status"] == "REQUESTED"
        assert turnover["readiness_snapshot"]["punch_open_critical_count"] == 0
        assert turnover["readiness_snapshot"]["punch_open_total_count"] == 1
        assert read_site(site_id)["status"] == "TURNOVER"


class TestPunchWaiver:
    def test_punch_waive_critical_returns_422(self, api, operations_lead_headers):
        """PRD §3.7: "Waiver moves an item from `OPEN` or `RESOLVED` to
        `WAIVED` and recomputes the counts, but only `MAJOR` and `MINOR` items
        are waivable; waiving a `CRITICAL` item is rejected with
        `ERR_PUNCH_NOT_WAIVABLE`."

        Design: Corner/state_machines/c_punch_waive_critical_returns_422
        """
        ctx = setup_site_in_punch()
        item = create_punch_item(ctx["site"]["id"], severity="CRITICAL",
                                 description="Storefront glass cracked")

        resp = api.waive_punch_item(item["id"], headers=operations_lead_headers)
        validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_WAIVABLE)
        assert read_punch_item(item["id"])["status"] == "OPEN"


class TestTurnoverLifecycle:
    def test_turnover_readiness_snapshot_pinned(self, api,
                                                site_superintendent_headers):
        """PRD §3.7: "The request lands `REQUESTED`, pins a
        `readiness_snapshot` capturing the site's `readiness_posture`,
        `punch_open_critical_count`, `punch_open_total_count`, and
        `forecast_open_on` at that instant, and automatically moves the site
        from `PUNCH` to `TURNOVER`, incrementing its `version`."

        Design: Corner/entities/c_turnover_readiness_snapshot_pinned
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        create_punch_item(site_id, severity="MINOR", description="Paint touch-up")

        resp = api.create_turnover({"site_id": site_id},
                                   headers=site_superintendent_headers)
        turnover = validate_success(resp, expected_status=201)
        snapshot = turnover["readiness_snapshot"]
        assert snapshot["punch_open_critical_count"] == 0
        assert snapshot["punch_open_total_count"] == 1
        assert snapshot["readiness_posture"] == "SIGNAGE_HUNG"
        assert read_site(site_id)["status"] == "TURNOVER"

    def test_turnover_reject_reverts_site_to_punch(self, api,
                                                   operations_lead_headers):
        """PRD §3.7: "Rejection, carrying a `rejection_reason`, moves the
        turnover to `REJECTED` and automatically reverts the site from
        `TURNOVER` back to `PUNCH` for another round of work."

        Design: Corner/state_machines/c_turnover_reject_reverts_site_to_punch
        """
        ctx = setup_site_in_turnover()

        resp = api.reject_turnover(
            ctx["turnover"]["id"],
            {"rejection_reason": "stockroom not merchandisable"},
            headers=operations_lead_headers)
        assert validate_success(resp)["status"] == "REJECTED"
        assert read_site(ctx["site"]["id"])["status"] == "PUNCH"

    def test_second_turnover_request_rejected(self, api, site_superintendent_headers):
        """PRD §3.7: "no other turnover may already sit `REQUESTED` for the
        site (`ERR_TURNOVER_ALREADY_REQUESTED`)"
        PRD §3.7: "The site must be in `PUNCH` (`ERR_INVALID_STATE` otherwise)"

        Design: Corner/errors/c_second_turnover_request_rejected

        A second request always arrives while the site sits in TURNOVER (the
        first request auto-advanced it), so the step-5 state guard and the
        already-requested guard trip simultaneously; §2.10 does not pin the
        order between two same-level guards, so either error id satisfies the
        PRD.
        """
        ctx = setup_site_in_turnover()

        resp = api.create_turnover({"site_id": ctx["site"]["id"]},
                                   headers=site_superintendent_headers)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_TURNOVER_ALREADY_REQUESTED, ApiErrorId.ERR_INVALID_STATE])
        # Whichever guard fired, nothing was created and nothing moved.
        assert read_site(ctx["site"]["id"])["status"] == "TURNOVER"

    def test_turnover_accept_open_major_rejected_minor_waived(
            self, api, site_superintendent_headers, operations_lead_headers):
        """PRD §3.7: "The punch gate demands every `CRITICAL` and `MAJOR`
        item be `VERIFIED`, and either every `MINOR` item be `VERIFIED` or
        `WAIVED`, or the request flag `waive_open_minor` be set true —
        anything short is rejected with `ERR_PUNCH_ITEMS_OUTSTANDING`. When
        acceptance proceeds with `waive_open_minor`, remaining `MINOR` items
        in `OPEN` or `RESOLVED` are swept to `WAIVED`. Acceptance is also the
        final reconciliation: the site's `actuals_cents` is set equal to its
        `committed_cents`, program actuals recompute, and the site's `version`
        increments."

        Design: Corner/errors/c_turnover_accept_open_major_rejected_minor_waived
        """
        ctx = setup_site_in_punch()
        site_id = ctx["site"]["id"]
        major = create_punch_item(site_id, severity="MAJOR",
                                  description="HVAC imbalance")
        minor = create_punch_item(site_id, severity="MINOR",
                                  description="Paint touch-up")
        turnover = request_turnover_ok(site_id)

        # An unverified MAJOR item defeats acceptance even with the waiver
        # flag set.
        resp = accept_turnover_now(turnover["id"], site_id, waive_open_minor=True)
        validate_error(resp, ApiErrorId.ERR_PUNCH_ITEMS_OUTSTANDING)

        validate_success(api.resolve_punch_item(major["id"],
                                                headers=site_superintendent_headers))
        validate_success(api.verify_punch_item(major["id"],
                                               headers=operations_lead_headers))
        resp = accept_turnover_now(turnover["id"], site_id, waive_open_minor=True)
        assert validate_success(resp)["status"] == "ACCEPTED"
        assert read_punch_item(minor["id"])["status"] == "WAIVED"
        # Final reconciliation: actuals equal committed (9000000, no change
        # orders on this site).
        assert read_site(site_id)["actuals_cents"] == 9_000_000

    def test_occ_turnover_accept_stale_version(self, api,
                                               site_superintendent_headers,
                                               operations_lead_headers):
        """PRD §2.7: "Three write operations require the client to supply
        `expected_site_version`, carrying the `version` of the target site as
        the client last observed it: the site update operation, change-order
        approval, and turnover acceptance. If the supplied value does not
        equal the site's current `version`, the request is rejected with
        `ERR_STALE_VERSION` and HTTP status 412."
        PRD §2.4: "A mutation is any change to a resource's stored state,
        including the recomputation of derived fields triggered by a cascade
        that originated on another resource."

        Design: Corner/cross_cutting_complexity_layers/c_occ_turnover_accept_stale_version
        """
        ctx = setup_site_in_turnover()
        site_id = ctx["site"]["id"]
        stale_version = read_site(site_id)["version"]

        # Creating a punch item recomputes the site's live counts, which
        # mutates the site and advances its version.
        create_punch_item(site_id, severity="MINOR",
                          description="Late paint touch-up")
        assert read_site(site_id)["version"] > stale_version

        resp = api.accept_turnover(ctx["turnover"]["id"],
                                   {"expected_site_version": stale_version},
                                   headers=operations_lead_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert read_turnover(ctx["turnover"]["id"])["status"] == "REQUESTED"


class TestStoreOpening:
    def test_site_open_without_accepted_turnover_rejected(self, api,
                                                          operations_lead_headers):
        """PRD §3.7: "Opening the store moves the site from `TURNOVER` to
        `OPEN` and requires an `ACCEPTED` turnover to exist
        (`ERR_TURNOVER_NOT_ACCEPTED` otherwise); the site's opening commitment
        moves to `MET` and the site's `version` increments."

        Design: Corner/errors/c_site_open_without_accepted_turnover_rejected
        """
        ctx = setup_site_in_turnover()

        resp = api.open_site(ctx["site"]["id"], headers=operations_lead_headers)
        validate_error(resp, ApiErrorId.ERR_TURNOVER_NOT_ACCEPTED)
        assert read_site(ctx["site"]["id"])["status"] == "TURNOVER"

    def test_site_open_terminal_lockdown(self, api, program_director_headers):
        """PRD §3.1: "A site that must leave the program can be removed from
        any state except `OPEN`."
        PRD §2.10: "State guards — the target resource is in a from-state that
        allows the operation, terminal states reject all further transitions,
        and domain state gates hold (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`,
        `ERR_MARKET_NOT_BIDDING`, `ERR_MARKET_NOT_AWARDED`,
        `ERR_BID_PACKAGE_NOT_OPEN`, `ERR_CONTRACTOR_NOT_PREQUALIFIED`,
        `ERR_SITE_NOT_IN_BUILD`, `ERR_TURNOVER_ALREADY_REQUESTED`,
        `ERR_ACTIVE_SITES_REMAIN`, `ERR_TURNOVER_NOT_ACCEPTED`)."

        Design: Corner/state_machines/c_site_open_terminal_lockdown
        """
        ctx = setup_site_open()
        assert ctx["site"]["status"] == "OPEN"

        resp = api.remove_site(ctx["site"]["id"], headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert read_site(ctx["site"]["id"])["status"] == "OPEN"
