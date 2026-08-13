"""Ops-run sweep families: late-remittance cascade, offering expiry, and the
delinquency reinstatement loop (PRD §3.5, §3.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_pool, setup_pool_with_funded_cert, setup_delinquent_agreement,
    commit, schedule_remittance, set_clock, run_sweep,
    make_originator_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestLateRemittanceThresholdCascade:
    def _full_setup(self, api):
        """Agreement ACTIVE (threshold 2, grace 5, due day 15); OPEN offering with
        two funded 10,000,000 certificates (buyers B1, B2); one SCHEDULED
        remittance per certificate for 2026-08-01..2026-08-31 (due 2026-09-15);
        clock at 2026-09-21, past due_at + grace."""
        from test_helpers import create_funded_certificate
        ctx = setup_pool(num_buyers=2,
                         agreement_overrides={"grace_period_days": 5,
                                              "late_remittance_threshold": 2})
        originator = ctx["originator"]
        b1, b2 = ctx["buyers"]
        c1 = create_funded_certificate(ctx["offering"]["id"], b1["id"], 10_000_000)
        c2 = create_funded_certificate(ctx["offering"]["id"], b2["id"], 10_000_000)
        r1 = schedule_remittance(c1["id"], originator["id"], collections_cents=100_000)
        r2 = schedule_remittance(c2["id"], originator["id"], collections_cents=100_000)
        set_clock("2026-09-21T00:00:00Z")
        return ctx, r1, r2

    def test_sweep_marks_both_remittances_late(self, api):
        """PRD §3.9: "First, every `SCHEDULED` remittance whose `due_at` plus its agreement's `grace_period_days` lies behind the clock flips to `LATE_UNPAID`, incrementing the agreement's `late_remittance_count` and flipping the agreement to `DELINQUENT` — suspending its `OPEN` offerings — the moment the count reaches `late_remittance_threshold`."
        PRD §3.9: "The ops-run sweep is a `NetworkAdmin` capability that executes three families of time-based transitions atomically in a single request, returning a summary with `remittances_marked_late`, `exceptions_escalated`, and `offerings_expired` counts."

        Design: Difficulty/transitive_cascade/late_remittance_threshold_cascade
        """
        ctx, r1, r2 = self._full_setup(api)
        summary = validate_success(api.run_sweep(ADMIN), 200)
        assert summary["remittances_marked_late"] == 2
        assert validate_success(api.get_remittance(r1["id"], ADMIN), 200)["status"] == "LATE_UNPAID"
        assert validate_success(api.get_remittance(r2["id"], ADMIN), 200)["status"] == "LATE_UNPAID"

    def test_agreement_delinquent_and_offering_suspended(self, api):
        """PRD §3.9: "First, every `SCHEDULED` remittance whose `due_at` plus its agreement's `grace_period_days` lies behind the clock flips to `LATE_UNPAID`, incrementing the agreement's `late_remittance_count` and flipping the agreement to `DELINQUENT` — suspending its `OPEN` offerings — the moment the count reaches `late_remittance_threshold`."
        PRD §2.8: "Second, the delinquency cascade: a servicing agreement flipping to `DELINQUENT` suspends its `OPEN` offerings, and reinstatement from `DELINQUENT` to `ACTIVE` reopens them."

        Design: Difficulty/transitive_cascade/late_remittance_threshold_cascade
        """
        ctx, r1, r2 = self._full_setup(api)
        validate_success(api.run_sweep(ADMIN), 200)
        agreement = validate_success(
            api.get_servicing_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert agreement["late_remittance_count"] == 2
        assert agreement["status"] == "DELINQUENT"
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["status"] == "SUSPENDED"


class TestDelinquencyReinstatementLoop:
    def test_paying_last_late_remittance_reinstates_agreement_and_offering(self, api):
        """PRD §3.5: "Paying a remittance already in `LATE_UNPAID` lands it in `PAID_LATE` with the same penalty and the same certificate balance effects, and additionally decrements the agreement's `late_remittance_count` by one; when that decrement brings the count to zero and the agreement is `DELINQUENT`, the agreement reinstates to `ACTIVE`, and its `SUSPENDED` offerings cascade back to `OPEN` in the same request."

        Design: Corner/state_machines/delinquency_reinstatement_loop
        """
        ctx = setup_delinquent_agreement(threshold=1, grace_period_days=5,
                                         collections_cents=100_000)
        # Precondition: the sweep already flipped the agreement DELINQUENT.
        before = validate_success(
            api.get_servicing_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert before["status"] == "DELINQUENT"
        assert before["late_remittance_count"] == 1

        originator = ctx["originator"]
        paid = validate_success(
            api.pay_remittance(ctx["remittance"]["id"],
                               make_originator_headers(originator["id"])), 200)
        assert paid["status"] == "PAID_LATE"
        # 6 days late on interest 50,000 + principal 47,917: round_half_up(97,917 x 3 x 6 / 10,000) = 176
        assert paid["penalty_cents"] == 176

        agreement = validate_success(
            api.get_servicing_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert agreement["status"] == "ACTIVE"
        assert agreement["late_remittance_count"] == 0
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["status"] == "OPEN"
        cert = validate_success(api.get_commitment(ctx["certificate"]["id"], ADMIN), 200)
        assert cert["outstanding_principal_cents"] == 9_952_083


class TestOfferingExpirySweep:
    def test_offering_expiry_rescinds_pending_certificates(self, api):
        """PRD §3.9: "Third, every `OPEN` offering whose `close_at` lies behind the clock while `remaining_principal_cents` is still positive flips to `EXPIRED`, rescinding each of its certificates in `PENDING_DILIGENCE` or `COMMITTED` to `RESCINDED` and recomputing the offering's `committed_principal_cents` and each affected buyer's `total_committed_principal_cents`."

        Design: Corner/state_machines/offering_expiry_sweep_rescinds_pending_certificates
        """
        ctx = setup_pool(offering_overrides={"open_at": "2026-08-01T00:00:00Z",
                                             "close_at": "2026-09-01T00:00:00Z"})
        cert = commit(ctx["offering"]["id"], ctx["buyers"][0]["id"], 10_000_000)
        set_clock("2026-09-02T00:00:00Z")
        summary = validate_success(api.run_sweep(ADMIN), 200)
        assert summary["offerings_expired"] == 1
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["status"] == "EXPIRED"
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["status"] == "RESCINDED"

    def test_sweep_with_nothing_due_returns_zeros(self, api):
        """PRD §3.9: "The ops-run sweep is a `NetworkAdmin` capability that executes three families of time-based transitions atomically in a single request, returning a summary with `remittances_marked_late`, `exceptions_escalated`, and `offerings_expired` counts."

        Design: Corner/cross_cutting/sweep_with_nothing_due_returns_zeros
        """
        from test_helpers import register_credit_union, register_cuso
        register_credit_union(charter_number="CU-1", legal_name="First CU")
        register_cuso()
        summary = validate_success(api.run_sweep(ADMIN), 200)
        assert summary["remittances_marked_late"] == 0
        assert summary["exceptions_escalated"] == 0
        assert summary["offerings_expired"] == 0
