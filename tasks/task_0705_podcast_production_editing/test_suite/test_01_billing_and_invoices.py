"""Per-episode invoice arithmetic, late-fee tiers, and the void-conserves-ledger
invariant. Covers difficulty rules combinatorial_formula, boundary_precision_check,
compensating_invariant (invoice side) and the matching corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_show_owner_headers,
    make_producer_eng_headers,
    make_platform_admin_headers,
    create_show_with_active_contract,
    create_engineer,
    drive_episode_to_published,
    publish_one_episode,
    get_episode_invoice,
    set_clock,
    assert_invoice_total_consistent,
)

ADMIN = make_platform_admin_headers()


class TestInvoiceTotalCombinatorial:
    def test_rush_with_transcript_extra_tracks_discount_cap(self, api):
        """PRD §3.5: "the tier base price keyed on the contract's tier, where STANDARD
        is 15000 cents, PRIORITY is 22000 cents, and RUSH is 35000 cents; plus a
        transcript charge of 4000 cents when the episode requested a transcript and 0
        otherwise; plus an extra-track charge equal to 2500 cents for every track beyond
        the second, i.e. the frozen raw_track_count reduced by an extra-track floor of 2
        (never below zero) multiplied by 2500 cents."
        PRD §3.5: "the raw discount is the subtotal multiplied by the contract's
        loyalty_discount_pct, rounded half up to whole cents, and the stored
        discount_cents is that raw discount capped at a maximum of 5000 cents."

        Design: Difficulty/combinatorial_formula/invoice_total_nonlinear_tier_discount_cap_extra_track
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="RUSH", engagement_type="PER_EPISODE", fmt="PANEL",
            loyalty_discount_pct=0.5)
        engineer = create_engineer(name="Eng I")
        episode = drive_episode_to_published(
            show, contract, engineer, planned_track_count=4, raw_track_count=4,
            transcript_requested=True, title="Ep I")

        invoice = get_episode_invoice(episode["id"])
        assert invoice["subtotal_cents"] == 44000, (
            f"RUSH 35000 + transcript 4000 + (4-2)*2500=5000 -> 44000, "
            f"got {invoice['subtotal_cents']}")
        assert invoice["discount_cents"] == 5000, (
            f"raw 44000*0.5=22000 capped at 5000, got {invoice['discount_cents']}")
        assert invoice["late_fee_cents"] == 0
        assert invoice["total_cents"] == 39000, (
            f"44000 - 5000 + 0 = 39000, got {invoice['total_cents']}")

    def test_priority_discount_uncapped_with_extra_tracks(self, api):
        """PRD §3.5: "the tier base price keyed on the contract's tier, where STANDARD is
        15000 cents, PRIORITY is 22000 cents, and RUSH is 35000 cents; plus a transcript
        charge of 4000 cents when the episode requested a transcript and 0 otherwise; plus
        an extra-track charge equal to 2500 cents for every track beyond the second"
        PRD §3.5: "the raw discount is the subtotal multiplied by the contract's
        loyalty_discount_pct, rounded half up to whole cents, and the stored discount_cents
        is that raw discount capped at a maximum of 5000 cents."

        PRIORITY base 22000 + (3-2)*2500 = 24500 subtotal; discount 24500*0.1=2450
        (below the 5000 cap, so the raw product binds, not the cap); total 22050.

        Design: Difficulty/combinatorial_formula/invoice_total_nonlinear_tier_discount_cap_extra_track
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="PRIORITY", engagement_type="PER_EPISODE", loyalty_discount_pct=0.1)
        engineer = create_engineer(name="Eng P2")
        episode = drive_episode_to_published(
            show, contract, engineer, planned_track_count=3, raw_track_count=3,
            title="Ep P2")
        invoice = get_episode_invoice(episode["id"])
        assert invoice["subtotal_cents"] == 24500, (
            f"PRIORITY 22000 + (3-2)*2500=2500 -> 24500, got {invoice['subtotal_cents']}")
        assert invoice["discount_cents"] == 2450, (
            f"round_half_up(24500*0.1)=2450, below 5000 cap, "
            f"got {invoice['discount_cents']}")
        assert invoice["total_cents"] == 22050, (
            f"24500 - 2450 + 0 = 22050, got {invoice['total_cents']}")

    def test_standard_at_extra_track_floor_no_extra_charge(self, api):
        """PRD §3.5: "plus an extra-track charge equal to 2500 cents for every track
        beyond the second, i.e. the frozen raw_track_count reduced by an extra-track
        floor of 2 (never below zero) multiplied by 2500 cents."

        Design: Corner/calculations/invoice_total_input_set_no_extra_track_below_floor
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Fl")
        episode = drive_episode_to_published(
            show, contract, engineer, planned_track_count=2, raw_track_count=2,
            title="Ep Fl")

        invoice = get_episode_invoice(episode["id"])
        assert invoice["subtotal_cents"] == 15000, (
            f"STANDARD base 15000, extra-track term 0 at raw=2, "
            f"got {invoice['subtotal_cents']}")
        assert invoice["total_cents"] == 15000, (
            f"no discount, no late fee, got {invoice['total_cents']}")
        assert_invoice_total_consistent(invoice)


class TestLateFeeTierBoundary:
    def test_late_fee_silver_tier_at_exact_40000_snapshot(self, api):
        """PRD §3.7: "the tier is GOLD when the snapshot is at least 80000 cents, SILVER
        when the snapshot is at least 40000 cents (but below the gold threshold), and
        BRONZE otherwise. When the delivery was late, late_fee_cents is the quantity
        (subtotal minus discount) multiplied by the tier's late-fee rate — 0.02 for
        BRONZE, 0.035 for SILVER, and 0.05 for GOLD — rounded half up to whole cents."
        PRD §3.6: "delivered_late is set to true exactly when the approval-time clock
        reading is strictly after the final turnaround_due_utc, and false otherwise."

        Design: Difficulty/boundary_precision_check/late_fee_tier_boundary_silver_threshold_exact
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng L")
        eng = make_producer_eng_headers(engineer["id"])

        # Seed episode: subtotal 15000 + (12-2)*2500 = 40000, on time -> lifetime 40000.
        seed = drive_episode_to_published(
            show, contract, engineer, planned_track_count=12, raw_track_count=12,
            record_start="2026-03-02T08:00:00Z", record_end="2026-03-02T09:00:00Z",
            title="Seed1")
        seed_inv = get_episode_invoice(seed["id"])
        assert seed_inv["subtotal_cents"] == 40000
        assert seed_inv["total_cents"] == 40000
        show_now = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert show_now["lifetime_billed_cents"] == 40000, (
            f"snapshot before boundary invoice must be 40000, "
            f"got {show_now['lifetime_billed_cents']}")

        # Boundary episode: STANDARD on-time recording 2026-03-02, approve 2026-04-01
        # (after 72h turnaround) -> delivered_late, snapshot 40000 -> SILVER.
        boundary = drive_episode_to_published(
            show, contract, engineer, planned_track_count=1, raw_track_count=1,
            record_start="2026-03-02T12:00:00Z", record_end="2026-03-02T13:00:00Z",
            approve_at="2026-04-01T00:00:00Z", title="Boundary")
        boundary_ep = get_success_data(api_client.get_episode(boundary["id"], eng))
        assert boundary_ep["delivered_late"] is True
        inv = get_episode_invoice(boundary["id"])
        assert inv["late_fee_cents"] == 525, (
            f"round_half_up(15000*0.035)=525 at SILVER tier, got {inv['late_fee_cents']}")

    def test_late_fee_consistent_total_after_publish(self, api):
        """PRD §3.5: "the invoice's total_cents equals the subtotal minus the discount
        plus the late fee."
        PRD §3.7: "When the delivery was not late, late_fee_cents is 0 regardless of tier."

        Design: Difficulty/boundary_precision_check/late_fee_tier_boundary_silver_threshold_exact
        """
        # On-time delivery -> late_fee 0 regardless of tier; total == subtotal.
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        inv = get_episode_invoice(episode["id"])
        assert inv["late_fee_cents"] == 0
        assert_invoice_total_consistent(inv)
        assert inv["total_cents"] == inv["subtotal_cents"] - inv["discount_cents"]


class TestVoidConservesLedger:
    def test_publish_then_void_returns_lifetime_to_zero(self, api):
        """PRD §2.9: "This figure is increased by the total_cents of each invoice the
        moment that invoice is issued ... and it is decreased by an invoice's total_cents
        when that invoice is voided, reversing the original billing."
        PRD §3.9: "Voiding additionally reverses the original billing by decreasing the
        show's lifetime_billed_cents by the voided invoice's total_cents before the
        posture is recomputed."

        Design: Difficulty/compensating_invariant/invoice_void_conserves_show_lifetime_billed
        """
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        owner = make_show_owner_headers(show["id"])
        invoice = get_episode_invoice(episode["id"])
        assert invoice["total_cents"] == 15000

        before = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert before["lifetime_billed_cents"] == 15000, (
            "forward billing applied at publish")

        get_success_data(api_client.dispute_invoice(invoice["id"], owner))
        get_success_data(api_client.void_invoice(invoice["id"], ADMIN))

        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["lifetime_billed_cents"] == 0, (
            f"void reverses 15000 -> back to 0 with zero drift, "
            f"got {after['lifetime_billed_cents']}")

    def test_void_subtracts_only_its_own_total_from_lifetime(self, api):
        """PRD §2.9: "it is decreased by an invoice's total_cents when that invoice is
        voided, reversing the original billing."
        PRD §3.9: "Voiding additionally reverses the original billing by decreasing the
        show's lifetime_billed_cents by the voided invoice's total_cents before the posture
        is recomputed."

        Two published episodes accumulate lifetime 30000; voiding one subtracts exactly
        that invoice's 15000, leaving 15000 with zero drift.

        Design: Difficulty/compensating_invariant/invoice_void_conserves_show_lifetime_billed
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng V2")
        owner = make_show_owner_headers(show["id"])
        ep1 = drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-02T08:00:00Z",
            record_end="2026-03-02T09:00:00Z", title="V1")
        ep2 = drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-03T08:00:00Z",
            record_end="2026-03-03T09:00:00Z", title="V2")

        before = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert before["lifetime_billed_cents"] == 30000, (
            f"two STANDARD invoices accumulate 30000, "
            f"got {before['lifetime_billed_cents']}")

        inv1 = get_episode_invoice(ep1["id"])
        get_success_data(api_client.dispute_invoice(inv1["id"], owner))
        get_success_data(api_client.void_invoice(inv1["id"], ADMIN))

        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["lifetime_billed_cents"] == 15000, (
            f"void subtracts only the voided invoice's 15000 -> 15000, "
            f"got {after['lifetime_billed_cents']}")

    def test_void_disputed_invoice_reaches_void_status(self, api):
        """PRD §3.9: "a DISPUTED invoice may later go to PAID or VOID ... A platform
        operator marks an ISSUED invoice OVERDUE, and may void a DISPUTED invoice,
        moving it to VOID."

        Design: Difficulty/non_linear_state_machine/invoice_disputed_branching_pay_or_void
        """
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        owner = make_show_owner_headers(show["id"])
        invoice = get_episode_invoice(episode["id"])
        get_success_data(api_client.dispute_invoice(invoice["id"], owner))

        voided = validate_success(api_client.void_invoice(invoice["id"], ADMIN))
        assert voided["status"] == "VOID", (
            f"DISPUTED->VOID branch chosen, got {voided['status']}")
        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["lifetime_billed_cents"] == 0, (
            "VOID branch reverses lifetime; PAID branch would have left 15000")
