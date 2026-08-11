"""Subscriptions, invoices, rollovers, overwinter credit, and the standing
cure cycles."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    change_plan_payload,
    create_active_host,
    create_season,
    create_site_for,
    create_agreement_for,
    create_hive_payload,
    create_subscription_for,
    create_subscription_paid,
    create_subscription_payload,
    first_invoice_for,
    list_invoices_for,
    make_host_headers,
    pay_invoice_as_host,
    rollover_season,
    setup_hive_scenario,
    sign_agreement_for,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
MGR = TEST_USERS["manager_headers"]


def _subscription_with_unpaid_first_invoice():
    """Season + ACTIVE host + BASIC subscription; first invoice UNPAID.
    Returns (season, host, subscription, first_invoice)."""
    season = create_season()
    host = create_active_host()
    sub = create_subscription_for(host, "BASIC")
    inv1 = first_invoice_for(sub["id"])
    return season, host, sub, inv1


class TestPastDueCureCycle:
    def test_partial_payment_does_not_cure(self, api):
        """PRD §3.9: "a subscription with any `OVERDUE` invoice after aging
        moves from `ACTIVE` to `PAST_DUE`, and one that entered the rollover
        already `PAST_DUE` and still has unpaid invoices moves to `SUSPENDED`."
        PRD §3.9: "When payment later leaves no `OPEN` or `OVERDUE` invoice on
        the subscription, the subscription returns from `PAST_DUE` or
        `SUSPENDED` to `ACTIVE` and, absent any other blocking condition, the
        host returns from `LIMITED` to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/subscription_past_due_cure_cycle
        """
        season, host, sub, inv1 = _subscription_with_unpaid_first_invoice()
        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        sub_now = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_now["status"] == "PAST_DUE", (
            "rollover aged invoice1 to OVERDUE and moved the subscription"
        )
        # Paying invoice1 while invoice2 remains OPEN does not cure.
        pay_invoice_as_host(inv1["id"], host)
        sub_mid = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_mid["status"] == "PAST_DUE", (
            "the cure is all-or-nothing while another invoice stays unpaid"
        )

    def test_full_payment_cures_subscription_and_host(self, api):
        """PRD §3.9: "When payment later leaves no `OPEN` or `OVERDUE` invoice
        on the subscription, the subscription returns from `PAST_DUE` or
        `SUSPENDED` to `ACTIVE` and, absent any other blocking condition, the
        host returns from `LIMITED` to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/subscription_past_due_cure_cycle
        """
        season, host, sub, inv1 = _subscription_with_unpaid_first_invoice()
        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        inv2 = list_invoices_for(sub["id"])[1]
        pay_invoice_as_host(inv1["id"], host)
        pay_invoice_as_host(inv2["id"], host)
        sub_now = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_now["status"] == "ACTIVE", (
            "paying the last unpaid invoice closes ACTIVE -> PAST_DUE -> ACTIVE"
        )
        host_now = validate_success(api.get_host(host["id"], OPS))
        assert host_now["status"] == "ACTIVE", (
            "host LIMITED -> ACTIVE via the same cure cascade"
        )


class TestRolloverCascade:
    def test_rollover_ages_invoice_and_moves_standing(self, api):
        """PRD §3.9: "For every subscription in `ACTIVE` or `PAST_DUE`, any
        unpaid invoice whose `due_at` has passed becomes `OVERDUE`; a fresh
        next-period invoice is issued per the line math above; and standing
        cascades — a subscription with any `OVERDUE` invoice after aging moves
        from `ACTIVE` to `PAST_DUE`, and one that entered the rollover already
        `PAST_DUE` and still has unpaid invoices moves to `SUSPENDED`."
        PRD §3.9: "Either way the host becomes `LIMITED` (a `SUSPENDED`
        subscription's host remains `LIMITED`)."

        Design: Difficulty/transitive_cascade/rollover_invoice_subscription_host_cascade
        """
        season, host, sub, inv1 = _subscription_with_unpaid_first_invoice()
        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        # Link 1: the rollover ages invoice1.
        inv1_now = validate_success(api.get_invoice(inv1["id"], OPS))
        assert inv1_now["status"] == "OVERDUE"
        # Link 2: the overdue invoice moves the subscription.
        sub_now = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_now["status"] == "PAST_DUE"
        # Link 3: the subscription standing moves the host.
        host_now = validate_success(api.get_host(host["id"], OPS))
        assert host_now["status"] == "LIMITED"

    def test_rollover_invoice_line_math(self, api):
        """PRD §3.9: "`carried_balance_cents` sums the `total_cents` of the
        subscription's unpaid prior invoices — those `OPEN` or `OVERDUE` — and
        is zero for the very first invoice."
        PRD §3.9: "`late_fee_cents` accrues per unpaid prior invoice: for each,
        count the full weeks overdue as the floor of the elapsed time since its
        `due_at` divided by seven days, round half-up to a whole cent three
        percent of that invoice's entire unpaid `total_cents` — prior late fees
        included, the compounding is intended — and multiply by the weeks
        overdue; the invoice's late fee is the sum across unpaid priors."
        PRD §3.9: "The invoice's `total_cents` is fee plus carried plus late
        minus credit, floored at zero."

        Design: Difficulty/transitive_cascade/rollover_invoice_subscription_host_cascade
        """
        season, host, sub, inv1 = _subscription_with_unpaid_first_invoice()
        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        inv2 = validate_success(
            api.get_invoice(list_invoices_for(sub["id"])[1]["id"], OPS),
        )
        # invoice1: issued 2026-05-01, due 2026-05-08; at 2026-06-01 it is
        # 24 days overdue -> 3 full weeks; 3 * round_half_up(2999 * 0.03) =
        # 3 * 90 = 270.
        assert inv2["carried_balance_cents"] == 2999
        assert inv2["late_fee_cents"] == 270
        assert inv2["fee_cents"] == 2999
        assert inv2["overwinter_credit_cents"] == 0, "host owns no hives"
        assert inv2["total_cents"] == 6268, "2999 fee + 2999 carried + 270 late"


class TestOverwinterVariants:
    def _overwinter_scenario(self):
        """Season frost 2026-10-15; host with BASIC subscription (invoice
        PAID) and two hives installed at the default clock (installed_at
        2026-05-01 <= frost_date)."""
        season = create_season()
        host = create_active_host()
        site = create_site_for(host)
        agreement = sign_agreement_for(create_agreement_for(host, site), host)
        sub, inv1 = create_subscription_paid(host, "BASIC")
        hive1 = validate_success(
            api_client.create_hive(
                create_hive_payload(site["id"], agreement["id"]), MGR,
            ),
            201,
        )
        hive2 = validate_success(
            api_client.create_hive(
                create_hive_payload(site["id"], agreement["id"]), MGR,
            ),
            201,
        )
        return season, host, sub, inv1, hive1, hive2

    def test_projected_counts_hives_alive_at_read(self, api):
        """PRD §3.9: "The projected variant,
        `projected_overwinter_credit_cents`, is computed live on subscription
        reads against the currently `OPEN` season's `frost_date` and the hive
        set as it stands right now — so a hive that dies between the read and
        the close still counts in the projection."
        PRD §3.9: "The overwinter credit rewards colony survival: 4000 cents
        for each of the host's hives — across all of the host's sites — whose
        `installed_at` is on or before the closing season's `frost_date` and
        whose lifecycle is `ACTIVE` or `QUARANTINED`."

        Design: Difficulty/dual_variant_calc/overwinter_credit_projected_vs_realized
        """
        season, host, sub, inv1, hive1, hive2 = self._overwinter_scenario()
        sub_now = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_now["projected_overwinter_credit_cents"] == 8000, (
            "provisional variant: both hives alive at read time"
        )

    def test_realized_counts_survivors_at_close(self, api):
        """PRD §3.9: "The realized variant is computed at rollover against the
        closing season and lands as `overwinter_credit_cents` on the
        rollover-issued invoice."
        PRD §3.9: "The invoice's `total_cents` is fee plus carried plus late
        minus credit, floored at zero."

        Design: Difficulty/dual_variant_calc/overwinter_credit_projected_vs_realized
        """
        season, host, sub, inv1, hive1, hive2 = self._overwinter_scenario()
        api_client.set_clock("2026-10-18T00:00:00Z", OPS)
        validate_success(api.mark_hive_dead(hive2["id"], MGR), 200)
        rollover_season(season["id"], at="2026-10-20T00:00:00Z")
        inv2 = validate_success(
            api.get_invoice(list_invoices_for(sub["id"])[1]["id"], OPS),
        )
        assert inv2["overwinter_credit_cents"] == 4000, (
            "realized variant: only the surviving hive counts at close"
        )
        assert inv2["fee_cents"] == 2999
        assert inv2["carried_balance_cents"] == 0
        assert inv2["late_fee_cents"] == 0
        assert inv2["total_cents"] == 0, "max(0, 2999 + 0 + 0 - 4000)"
        inv1_now = validate_success(api.get_invoice(inv1["id"], OPS))
        assert inv1_now["status"] == "PAID", (
            "paid before rollover, so no aging side effects"
        )


class TestBalanceConservation:
    def test_issue_adds_then_void_restores_balance(self, api):
        """PRD §3.9: "That balance, visible on every host read, is simply the
        sum of `total_cents` over invoices in `OPEN` or `OVERDUE` across the
        host's subscriptions."
        PRD §3.9: "`PlatformOps` may instead void an unpaid invoice, moving it
        from `OPEN` or `OVERDUE` to `VOID` — voiding a `PAID` invoice fails
        with `ERR_INVOICE_NOT_VOIDABLE` — which excludes it from the host's
        `balance_due_cents` and re-evaluates the cure cascade."

        Design: Difficulty/compensating_invariant/invoice_balance_conserved_across_issue_void
        """
        season = create_season()
        host = create_active_host()
        sub, inv1 = create_subscription_paid(host, "BASIC")
        before = validate_success(api.get_host(host["id"], OPS))
        assert before["balance_due_cents"] == 0

        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        inv2 = list_invoices_for(sub["id"])[1]
        after_issue = validate_success(api.get_host(host["id"], OPS))
        # invoice2: fee 2999 + carried 0 + late 0 - credit 0 (no hives).
        assert after_issue["balance_due_cents"] == 2999, (
            "issuance adds exactly invoice2.total_cents"
        )
        voided = validate_success(api.void_invoice(inv2["id"], OPS), 200)
        assert voided["status"] == "VOID"
        after_void = validate_success(api.get_host(host["id"], OPS))
        assert after_void["balance_due_cents"] == 0, (
            "the compensating void restores the pre-rollover balance exactly"
        )

    def test_paid_first_invoice_means_no_aging(self, api):
        """PRD §3.9: "For every subscription in `ACTIVE` or `PAST_DUE`, any
        unpaid invoice whose `due_at` has passed becomes `OVERDUE`."
        PRD §3.9: "a subscription with any `OVERDUE` invoice after aging moves
        from `ACTIVE` to `PAST_DUE`."

        Design: Difficulty/compensating_invariant/invoice_balance_conserved_across_issue_void
        """
        season = create_season()
        host = create_active_host()
        sub, inv1 = create_subscription_paid(host, "BASIC")
        rollover_season(season["id"], at="2026-06-01T00:00:00Z")
        inv1_now = validate_success(api.get_invoice(inv1["id"], OPS))
        assert inv1_now["status"] == "PAID", "paid invoices do not age"
        sub_now = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_now["status"] == "ACTIVE", "no OVERDUE invoice after aging"


class TestInvoiceStateRules:
    def test_double_pay_rejected(self, api):
        """PRD §3.9: "An `OPEN` or `OVERDUE` invoice can be paid by the owning
        host or `PlatformOps`, stamping `paid_at` and moving to `PAID`; paying
        a `PAID` or `VOID` invoice fails with `ERR_INVOICE_NOT_PAYABLE`."

        Design: Corner/state_machines/invoice_double_pay_rejected
        """
        host = create_active_host()
        sub = create_subscription_for(host, "BASIC")
        inv1 = first_invoice_for(sub["id"])
        paid = pay_invoice_as_host(inv1["id"], host)
        assert paid["status"] == "PAID"
        res = api.pay_invoice(inv1["id"], make_host_headers(host["id"]))
        validate_error(res, "ERR_INVOICE_NOT_PAYABLE")
        current = validate_success(api.get_invoice(inv1["id"], OPS))
        assert current["status"] == "PAID"
        assert current["paid_at"] == paid["paid_at"], (
            "the repeat is never silently idempotent"
        )

    def test_void_paid_invoice_rejected(self, api):
        """PRD §3.9: "`PlatformOps` may instead void an unpaid invoice, moving
        it from `OPEN` or `OVERDUE` to `VOID` — voiding a `PAID` invoice fails
        with `ERR_INVOICE_NOT_VOIDABLE`."

        Design: Corner/errors/void_paid_invoice_rejected
        """
        host = create_active_host()
        sub = create_subscription_for(host, "BASIC")
        inv1 = first_invoice_for(sub["id"])
        pay_invoice_as_host(inv1["id"], host)
        res = api.void_invoice(inv1["id"], OPS)
        validate_error(res, "ERR_INVOICE_NOT_VOIDABLE")
        current = validate_success(api.get_invoice(inv1["id"], OPS))
        assert current["status"] == "PAID"


class TestSubscriptionStateRules:
    def test_duplicate_subscription_rejected(self, api):
        """PRD §3.9: "A host may hold only one non-`CANCELLED` subscription; a
        duplicate attempt fails with `ERR_DUPLICATE_SUBSCRIPTION`."

        Design: Corner/errors/duplicate_subscription_rejected
        """
        host = create_active_host()
        create_subscription_for(host, "BASIC")
        res = api.create_subscription(
            create_subscription_payload(host["id"], "PLUS"), OPS,
        )
        validate_error(res, "ERR_DUPLICATE_SUBSCRIPTION")

    def test_invalid_plan_enum_rejected(self, api):
        """PRD §3.9: "a subscription created by `PlatformOps` with the
        `host_id` and a `plan` of `BASIC`, `PLUS`, or `PREMIUM`."
        PRD §2.12 step 5: "required fields present, enum values valid, ranges
        honored (`bees_sampled` at least 1, `quiz_score` between 0 and 100,
        `term_end_date` after `term_start_date`, `end_date` after `start_date`,
        `gross_kg` strictly above 0, `email` unique across hosts); otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/subscription_invalid_enum_rejected
        """
        host = create_active_host()
        res = api.create_subscription(
            create_subscription_payload(host["id"], "GOLD"), OPS,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_cancel_with_balance_rejected_then_allowed(self, api):
        """PRD §3.9: "Cancelling a subscription requires ownership and a zero
        `balance_due_cents`, clears `pending_plan`, and is terminal from
        `ACTIVE`, `PAST_DUE`, or `SUSPENDED`."
        PRD §2.12 step 11: "host `ACTIVE` where required (agreement creation,
        hive installation, enrollment), `balance_due_cents` equal to zero for
        removal requests, agreement termination, subscription cancellation, and
        host reactivation, and `reputation_score` of at least 50 for agreement
        creation; surfaced as `ERR_HOST_NOT_ACTIVE`, `ERR_OUTSTANDING_BALANCE`,
        or `ERR_HOST_REPUTATION_TOO_LOW`."

        Design: Corner/errors/subscription_cancel_with_balance_rejected
        """
        host = create_active_host()
        sub = create_subscription_for(host, "BASIC")
        inv1 = first_invoice_for(sub["id"])
        res = api.cancel_subscription(sub["id"], make_host_headers(host["id"]))
        validate_error(res, "ERR_OUTSTANDING_BALANCE")
        pay_invoice_as_host(inv1["id"], host)
        cancelled = validate_success(
            api.cancel_subscription(sub["id"], make_host_headers(host["id"])),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

    def test_change_plan_on_cancelled_subscription_rejected(self, api):
        """PRD §2.12 step 6: "the target resource's current state permits the
        transition, and the OCC `expected_*_version` match is evaluated at this
        step; failures surface as `ERR_INVALID_STATE`, `ERR_HIVE_NOT_OPERABLE`,
        `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INSPECTION_NOT_SUBMITTED`,
        `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_INVOICE_NOT_PAYABLE`,
        `ERR_INVOICE_NOT_VOIDABLE`, `ERR_SWARM_NOT_ACTIONABLE`,
        `ERR_REMOVAL_NOT_ACTIONABLE`, `ERR_ALLOCATION_NOT_DISTRIBUTABLE`,
        `ERR_SEASON_NOT_CLOSABLE`, `ERR_ENROLLMENT_NOT_COMPLETABLE`, or
        `ERR_STALE_VERSION` (412)."
        PRD §3.9: "Cancelling a subscription requires ownership and a zero
        `balance_due_cents`, clears `pending_plan`, and is terminal from
        `ACTIVE`, `PAST_DUE`, or `SUSPENDED`."

        Design: Corner/errors/change_plan_cancelled_subscription_rejected
        """
        host = create_active_host()
        sub, inv1 = create_subscription_paid(host, "BASIC")
        cancelled = validate_success(
            api.cancel_subscription(sub["id"], make_host_headers(host["id"])),
            200,
        )
        res = api.change_plan(
            sub["id"],
            change_plan_payload("PLUS", cancelled["version"]),
            make_host_headers(host["id"]),
        )
        validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")

    def test_change_plan_occ_stale_version(self, api):
        """PRD §2.9: "Scheduling a subscription plan change likewise requires
        `expected_subscription_version` matching the subscription's current
        `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "Success stores the choice in `pending_plan` — replacing any
        prior pending plan — and increments the subscription's `version`."

        Design: Corner/complexity_layers/occ_subscription_stale_version_412
        """
        host = create_active_host()
        sub = create_subscription_for(host, "BASIC")
        v0 = sub["version"]
        first = validate_success(
            api.change_plan(
                sub["id"], change_plan_payload("PLUS", v0),
                make_host_headers(host["id"]),
            ),
            200,
        )
        assert first["version"] == v0 + 1
        assert first["pending_plan"] == "PLUS"
        res = api.change_plan(
            sub["id"], change_plan_payload("BASIC", v0),
            make_host_headers(host["id"]),
        )
        validate_error(res, "ERR_STALE_VERSION")
        current = validate_success(api.get_subscription(sub["id"], OPS))
        assert current["pending_plan"] == "PLUS", (
            "the stale writer did not overwrite the pending plan"
        )


class TestSeasonClosure:
    def test_rollover_closed_season_rejected(self, api):
        """PRD §2.6: "attempting to create the genesis season while one
        already exists `OPEN`, or to roll over a season that is already
        `CLOSED`, is rejected with `ERR_SEASON_NOT_CLOSABLE`."
        PRD §2.6: "The response to a rollover is the successor season, not the
        closed one."

        Design: Corner/endpoints/rollover_closed_season_rejected
        """
        season = create_season()
        successor = rollover_season(season["id"])
        res = api.rollover_season(
            season["id"],
            {"name": "S2026-again", "frost_date": "2028-10-15T00:00:00Z"},
            OPS,
        )
        validate_error(res, "ERR_SEASON_NOT_CLOSABLE")
        closed = validate_success(api.get_season(season["id"], OPS))
        assert closed["status"] == "CLOSED"
        opened = validate_success(api.get_season(successor["id"], OPS))
        assert opened["status"] == "OPEN", "successor intact"
