"""Modification permits: tiered fees, OCC guard, expiry sweep, commencement
cascade — plus the backflow compounding late penalty."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    admin_headers,
    assert_permit,
    create_contractor,
    create_permit_for_system,
    create_permit_payload,
    create_property,
    create_system,
    get_success_data,
    parse_ts,
    set_clock,
    setup_inspection_site,
    setup_invoiced_backflow_test,
    setup_issued_permit,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestPermitFeeTiers:
    def _sprinkler_site(self, api, legal_name):
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_inspection_site(system_category="SPRINKLER", device_count=0,
                                    occupancy_class="STORAGE",
                                    legal_name=legal_name)
        return ctx

    def test_valuation_straddling_two_tiers_uses_marginal_rates(self, api):
        """PRD §3.9: "The application computes `permit_fee_cents` from the
        valuation on a marginal tier schedule: the first 200000 cents of
        valuation are charged at three percent, the next 300000 cents at two and
        a half percent, and any remainder at one and a half percent; the result
        is floored at a minimum fee of 7500 cents, and a single round-half-up to
        whole cents is applied at the very end — no per-tier rounding."

        Design: Difficulty/combinatorial_formula/permit_fee_marginal_tier_straddle
        """
        ctx = self._sprinkler_site(api, "HydroShield")
        permit = create_permit_for_system(ctx["con"], ctx["sys"], 350000)
        assert_permit(permit)
        # 200000 x 3% + 150000 x 2.5% = 6000 + 3750 = 9750 (marginal, not average).
        assert permit["permit_fee_cents"] == 9750, (
            f"expected marginal-tier fee 9750, got {permit['permit_fee_cents']}")

    def test_small_valuation_hits_minimum_fee_floor(self, api):
        """PRD §3.9: "the result is floored at a minimum fee of 7500 cents, and a
        single round-half-up to whole cents is applied at the very end — no
        per-tier rounding."

        Design: Difficulty/combinatorial_formula/permit_fee_marginal_tier_straddle
        """
        ctx = self._sprinkler_site(api, "HydroShield")
        permit = create_permit_for_system(ctx["con"], ctx["sys"], 100000)
        # 100000 x 3% = 3000 < 7500 -> the minimum floor binds.
        assert permit["permit_fee_cents"] == 7500, (
            f"expected the 7500-cent minimum, got {permit['permit_fee_cents']}")


class TestPermitOptimisticConcurrency:
    def test_stale_permit_create_rejected(self, api):
        """PRD §3.9: "Applying takes the declared `project_valuation_cents` and
        the OCC guard `expected_system_version`; the application itself
        increments the parent system's `version`, so a stale expected version is
        rejected with `ERR_STALE_VERSION` and the applicant must re-read the
        system."

        Design: Corner/cross_cutting_layers/occ_stale_permit_create_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        con = create_contractor(legal_name="Occ2 Co", state_license_no="C-99993")
        prop = create_property(con, address_line="2 Occ Ave")
        sys = create_system(con, prop, system_category="SPRINKLER")
        create_permit_for_system(con, sys, 500000)

        stale = api.create_permit(
            sys["id"],
            create_permit_payload(600000, sys["version"]),
            admin_headers(con))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_system(sys["id"], admin_headers(con)))
        assert after["version"] == sys["version"] + 1, (
            "the first application incremented the system version exactly once")


class TestPermitExpirySweep:
    def test_issued_permit_expires_after_ninety_days_without_work(self, api):
        """PRD §3.9: "Permits still `ISSUED` with no commencement when the
        logical date passes the issue date plus ninety days are swept to
        `EXPIRED` by the daily sweep."
        PRD §2.6: "5. **Transition legality** — the target resource must be in a
        state from which the requested transition exists; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_layers/scheduled_clock_sweep_expires_permit
        """
        ctx = setup_issued_permit(legal_name="Expire Co",
                                  issue_clock="2026-08-02T00:00:00Z")
        set_clock("2026-11-05T00:00:00Z")
        permit = validate_success(api.get_permit(ctx["permit"]["id"], ctx["admin"]))
        assert permit["status"] == "EXPIRED", (
            "issued 2026-08-02, swept once the clock passed issue + ninety days")
        resp = api.commence_work(permit["id"], ctx["admin"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCommencementCascade:
    def test_commence_work_auto_creates_unplanned_impairment(self, api):
        """PRD §3.9: "Commencement stamps `work_commenced_at` and has a
        structural side effect: because the system is being opened up, an
        `UNPLANNED` impairment is auto-created on the system with `discovered_at`
        set to the commencement instant, which itself requires authority
        notification within two hours and immediately re-derives the system's
        impairment status."
        PRD §3.6: "for `UNPLANNED` it is two hours after `discovered_at`"
        PRD §3.6: "otherwise, with at least one impairment in `OPEN` or
        `NOTIFIED`, it reads `IMPAIRED`"

        Design: Difficulty/transitive_cascade/permit_commencement_impairment_two_hop_cascade
        """
        ctx = setup_issued_permit(legal_name="Mod Works")
        commenced = validate_success(
            api.commence_work(ctx["permit"]["id"], ctx["admin"]))
        assert commenced["status"] == "WORK_COMMENCED"
        assert commenced["work_commenced_at"] is not None

        impairments = get_success_data(
            api.list_impairments(ctx["sys"]["id"], ctx["admin"]))
        assert len(impairments) == 1, "exactly one impairment is auto-created"
        imp = impairments[0]
        assert imp["impairment_kind"] == "UNPLANNED"
        delta = parse_ts(imp["notification_deadline"]) - parse_ts(imp["discovered_at"])
        assert delta == timedelta(hours=2), (
            "the unplanned notification deadline is two hours after discovery")

        sys_now = validate_success(api.get_system(ctx["sys"]["id"], ctx["admin"]))
        assert sys_now["impairment_status"] == "IMPAIRED"

    def test_impaired_system_blocks_second_permit_issuance(self, api):
        """PRD §3.9: "the system's `impairment_status` exactly `NORMAL` —
        issuance against an impaired or out-of-service system fails with
        `ERR_SYSTEM_IMPAIRED`."
        PRD §3.9: "an `UNPLANNED` impairment is auto-created on the system with
        `discovered_at` set to the commencement instant, which itself requires
        authority notification within two hours and immediately re-derives the
        system's impairment status."

        Design: Difficulty/transitive_cascade/permit_commencement_impairment_two_hop_cascade
        """
        ctx = setup_issued_permit(legal_name="Mod Works")
        sys_fresh = validate_success(api.get_system(ctx["sys"]["id"], ctx["admin"]))
        permit2 = create_permit_for_system(ctx["con"], sys_fresh, 600000)
        validate_success(api.commence_work(ctx["permit"]["id"], ctx["admin"]))

        sys_now = validate_success(api.get_system(ctx["sys"]["id"], ctx["admin"]))
        assert sys_now["impairment_status"] == "IMPAIRED"
        resp = api.issue_permit(permit2["id"], MARSHAL)
        validate_error(resp, ApiErrorId.ERR_SYSTEM_IMPAIRED)


class TestBackflowCompoundingPenalty:
    def test_sweep_compounds_rounded_per_month(self, api):
        """PRD §3.8: "Payment becomes due thirty days after the invoice
        transition. While the balance stands unpaid past that due date, the
        penalty compounds monthly at five percent: for each whole calendar month
        elapsed from the due date to the payment date — a partial month does not
        compound — the balance is multiplied by 1.05 and rounded half-up to whole
        cents after each monthly step, starting from the 40000-cent base."
        PRD §2.5: "The monthly compounding of unpaid backflow-test balances is
        likewise evaluated through this sweep machinery."

        Design: Difficulty/combinatorial_formula/backflow_penalty_round_per_month_compounding
        """
        ctx = setup_invoiced_backflow_test()  # invoiced 2026-08-02; due 2026-09-01
        bt_id = ctx["bt"]["id"]
        assert ctx["bt"]["unpaid_balance_cents"] == 40000

        set_clock("2026-11-02T00:00:00Z")
        two_months = validate_success(api.get_backflow_test(bt_id, ctx["admin"]))
        # 40000 -> 42000 (Sep) -> 44100 (Oct); Nov 1 -> Nov 2 is partial.
        assert two_months["unpaid_balance_cents"] == 44100, (
            f"two rounded monthly steps give 44100, got "
            f"{two_months['unpaid_balance_cents']}")

        set_clock("2026-12-02T00:00:00Z")
        three_months = validate_success(api.get_backflow_test(bt_id, ctx["admin"]))
        # 44100 -> 46305 (round_half_up after the third step).
        assert three_months["unpaid_balance_cents"] == 46305, (
            f"three rounded monthly steps give 46305, got "
            f"{three_months['unpaid_balance_cents']}")

    def test_record_payment_zeroes_balance_into_paid(self, api):
        """PRD §3.8: "Recording payment against an `INVOICED` test first computes
        this compounded penalty into `unpaid_balance_cents`, then zeroes the
        balance and lands in `PAID`."

        Design: Difficulty/combinatorial_formula/backflow_penalty_round_per_month_compounding
        """
        ctx = setup_invoiced_backflow_test()
        set_clock("2026-12-02T00:00:00Z")
        paid = validate_success(api.record_backflow_payment(ctx["bt"]["id"],
                                                            ctx["admin"]))
        assert paid["status"] == "PAID"
        assert paid["unpaid_balance_cents"] == 0, (
            "payment zeroes the balance after computing the compounded penalty")
