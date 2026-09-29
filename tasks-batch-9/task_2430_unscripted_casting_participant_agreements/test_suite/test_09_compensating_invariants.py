"""Two conserved production figures and the compensating actions that must
return them to precisely where they stood, with no residual cents: the
committed stipend against voiding, and the blocked minor trust against both the
participant's withdrawal and an ordinary business void.
"""

from test_helpers import (
    TEST_USERS,
    assert_conserved,
    assert_money,
    get_agreement,
    get_production,
    make_applicant_headers,
    setup_cleared_applicant,
    setup_executed_agreement,
    setup_minor_protection,
    setup_production,
    setup_published_casting_call,
    setup_trust_deposit,
    validate_paginated,
    validate_success,
    void_agreement,
    withdraw_payload,
)

PA = TEST_USERS["production_admin_headers"]
BA1 = TEST_USERS["business_affairs_headers"]

# A six-episode limited-licence deal with a ninety-day exclusivity window, two
# contracted junkets and a reunion taping.
RICH_TERMS = {
    "exclusivity_window_days": 90,
    "confidentiality_tier": "ENHANCED",
    "depiction_rights_scope": "LIMITED",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 250_000,
    "episodes_committed": 6,
    "press_appearance_obligation_count": 2,
    "reunion_obligation": True,
}

# A two-episode flat deal with no exclusivity, no junkets and no reunion.
PLAIN_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "FLAT",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
    "press_appearance_obligation_count": 0,
    "reunion_obligation": False,
}

RICH_TOTAL = 2_106_625
PLAIN_TOTAL = 220_000

# 2,106,625 x 0.15 is 315,993.75; over six installments that is 52,665.625
# each, rounded half up to 52,666, and the deposited figure is that rounded
# installment times six, not rounded again.
RICH_INSTALLMENT = 52_666
RICH_TRUST = 315_996


class TestStipendPoolConservedAcrossExecuteThenVoid:
    """Committed stipend is a full re-summation over executed agreements, so
    voiding either of two executed rows must leave exactly the other one."""

    def _two_executed_agreements(self, title: str, season_number: int):
        production = setup_production(
            title=title, season_number=season_number, minor_participant_cap=0
        )
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=90
        )
        rich_applicant = setup_cleared_applicant(
            call["id"], legal_name="Tess Auber", date_of_birth="1992-02-02"
        )
        rich = setup_executed_agreement(
            rich_applicant["id"], production["id"], **RICH_TERMS
        )
        plain_applicant = setup_cleared_applicant(
            call["id"], legal_name="Uma Field", date_of_birth="1989-09-09"
        )
        plain = setup_executed_agreement(
            plain_applicant["id"], production["id"], **PLAIN_TERMS
        )

        # 250,000 x 6 x 1.15 = 1,725,000 base, 172,500 hazard, three 40,000
        # exclusivity blocks, 50,000 of press and 150,000 of reunion, then a
        # five-hundredths limited-licence discount of 110,875.
        assert_money(rich["total_stipend_commitment_cents"], RICH_TOTAL, "rich total")
        # 100,000 x 2 x 1.00 = 200,000 base plus 20,000 hazard and nothing else.
        assert_money(
            plain["total_stipend_commitment_cents"], PLAIN_TOTAL, "plain total"
        )

        committed_pre = get_production(production["id"])["stipend_committed_cents"]
        assert_money(committed_pre, RICH_TOTAL + PLAIN_TOTAL, "committed stipend")
        return production, rich, plain, committed_pre

    def test_voiding_the_larger_row_leaves_exactly_the_smaller_one(self, api):
        """PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."
        PRD §2.11: "Agreements in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED`
        status contribute nothing, and `VOIDED` agreements both fall outside the
        summed set and carry a zeroed `total_stipend_commitment_cents`, so
        voiding is an exact reversal of executing."
        PRD §3.6: "Where the prior status was `EXECUTED` the full unwind follows:
        `total_stipend_commitment_cents` is zeroed, the production's
        `stipend_committed_cents` is recomputed by full re-summation,
        `minor_participant_count` is recomputed, every post-production obligation
        of the agreement still in `SCHEDULED` status moves to `EXCUSED`, every
        minor-protection packet of the applicant moves to `RELEASED` with its
        `trust_deposited_cents` zeroed, and the production's
        `trust_escrow_balance_cents` is recomputed."

        Design: Difficulty/compensating_invariant/stipend_pool_conserved_across_execute_then_void
        """
        production, rich, plain, committed_pre = self._two_executed_agreements(
            "Island Trials S12", 12
        )

        voided = void_agreement(rich["id"], "BUSINESS_AFFAIRS_VOID")
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "BUSINESS_AFFAIRS_VOID"
        assert_money(
            voided["total_stipend_commitment_cents"], 0, "voided row's own total"
        )

        after = get_production(production["id"])
        assert_money(after["stipend_committed_cents"], PLAIN_TOTAL, "committed stipend")
        assert_conserved(
            committed_pre,
            after["stipend_committed_cents"],
            -RICH_TOTAL,
            "committed stipend",
        )
        # The surviving row is untouched, and 220,000 against a 50,000,000 pool
        # is nowhere near the utilisation gate.
        surviving = get_agreement(plain["id"])
        assert surviving["status"] == "EXECUTED"
        assert_money(
            surviving["total_stipend_commitment_cents"], PLAIN_TOTAL, "plain total"
        )
        assert after["casting_posture"] == "OPEN"

        rows, meta = validate_paginated(api.list_post_obligations(rich["id"], BA1))
        assert meta["total_count"] == 3, "two junkets and one reunion taping"
        assert [row["status"] for row in rows] == ["EXCUSED"] * 3

    def test_voiding_the_smaller_row_leaves_exactly_the_larger_one(self, api):
        """PRD §2.11: "Each is defined as a full recomputation over its
        contributing child records, never as an incremental delta applied to the
        previous value, and each is recomputed in the same request as the write
        that changed its inputs."
        PRD §2.11: "The invariant this buys is exact: for every forward action
        there is a compensating action, and after the compensating action the
        figure returns to precisely the value it held before, with no drift of
        even one cent."
        PRD §3.9: "An obligation is instead moved `SCHEDULED → EXCUSED`, with its
        `version` incremented by one, when the owning agreement is voided for any
        reason."

        Design: Difficulty/compensating_invariant/stipend_pool_conserved_across_execute_then_void
        """
        production, rich, plain, committed_pre = self._two_executed_agreements(
            "Island Trials S13", 13
        )

        voided = void_agreement(plain["id"], "BUSINESS_AFFAIRS_VOID")
        assert voided["status"] == "VOIDED"
        assert_money(
            voided["total_stipend_commitment_cents"], 0, "voided row's own total"
        )

        after = get_production(production["id"])
        # Executing the plain row raised the figure by 220,000; voiding it lowers
        # the figure by exactly 220,000 and by nothing else.
        assert_money(after["stipend_committed_cents"], RICH_TOTAL, "committed stipend")
        assert_conserved(
            committed_pre,
            after["stipend_committed_cents"],
            -PLAIN_TOTAL,
            "committed stipend",
        )

        surviving = get_agreement(rich["id"])
        assert surviving["status"] == "EXECUTED"
        assert_money(
            surviving["total_stipend_commitment_cents"], RICH_TOTAL, "rich total"
        )
        # The plain deal owed no appearances at all, so there was nothing to
        # excuse, while the surviving deal's three obligations still stand.
        _plain_rows, plain_meta = validate_paginated(
            api.list_post_obligations(plain["id"], BA1)
        )
        assert plain_meta["total_count"] == 0
        rich_rows, rich_meta = validate_paginated(
            api.list_post_obligations(rich["id"], BA1)
        )
        assert rich_meta["total_count"] == 3
        assert [row["status"] for row in rich_rows] == ["SCHEDULED"] * 3


class TestMinorTrustEscrowConservedAcrossDepositThenRefund:
    """The blocked trust is a second, differently shaped conserved quantity, and
    releasing a packet is a refund that leaves no residue."""

    def _minor_with_a_funded_trust(self, title: str, season_number: int):
        production = setup_production(
            title=title, season_number=season_number, minor_participant_cap=2
        )
        assert_money(
            get_production(production["id"])["trust_escrow_balance_cents"],
            0,
            "escrow before any deposit",
        )
        call = setup_published_casting_call(
            production["id"], min_age=13, max_age=45, exclusivity_window_days=90
        )
        applicant = setup_cleared_applicant(
            call["id"],
            minor=True,
            legal_name="Vic Lorne",
            date_of_birth="2011-05-20",
            guardian_name="Wren Lorne",
        )
        assert applicant["is_minor"] is True
        packet = setup_minor_protection(
            applicant["id"],
            work_permit_number="CA-WP-77120",
            permit_expires_on="2027-03-31",
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )
        assert packet["status"] == "COMPLETE"

        agreement = setup_executed_agreement(
            applicant["id"], production["id"], **RICH_TERMS
        )
        assert_money(
            agreement["total_stipend_commitment_cents"], RICH_TOTAL, "final stipend"
        )

        funded = setup_trust_deposit(packet["id"], 6)
        assert_money(funded["per_installment_cents"], RICH_INSTALLMENT, "installment")
        assert_money(funded["trust_deposited_cents"], RICH_TRUST, "deposited trust")

        before = get_production(production["id"])
        assert_money(before["trust_escrow_balance_cents"], RICH_TRUST, "escrow")
        assert_money(before["stipend_committed_cents"], RICH_TOTAL, "committed stipend")
        assert before["minor_participant_count"] == 1
        return production, call, applicant, packet, agreement, before

    def test_the_participants_withdrawal_refunds_the_trust_to_zero(self, api):
        """PRD §3.3: "Fourth, because the agreement was voided, every
        minor-protection packet of that applicant whose `status` is `INCOMPLETE`,
        `COMPLETE` or `LAPSED` moves to `RELEASED`, its `trust_deposited_cents`
        and `per_installment_cents` are zeroed, and the production's
        `trust_escrow_balance_cents` is recomputed."
        PRD §3.3: "Second, because the applicant has withdrawn, every participant
        agreement of that applicant whose `status` is `DRAFTED`, `SENT`,
        `COUNTERED`, `REVISED` or `EXECUTED` moves to `VOIDED` with `void_reason`
        set to `APPLICANT_WITHDRAWN`."
        PRD §2.11: "Trust escrow is the sum of `trust_deposited_cents` over the
        minor-protection packets reachable from the production through its
        applicants' agreements whose packet `status` is `INCOMPLETE`, `COMPLETE`
        or `LAPSED`; `RELEASED` packets are excluded from the sum and also have
        their deposit figures zeroed, so a trust refund likewise leaves zero
        residue."

        Design: Difficulty/compensating_invariant/minor_trust_escrow_conserved_across_deposit_then_withdrawal
        """
        (
            production,
            _call,
            applicant,
            _packet,
            agreement,
            before,
        ) = self._minor_with_a_funded_trust("Teen Trials S4", 4)

        withdrawn = validate_success(
            api.withdraw_applicant(
                applicant["id"],
                withdraw_payload(),
                make_applicant_headers(applicant["id"]),
            )
        )
        assert withdrawn["screening_status"] == "WITHDRAWN"

        after = get_production(production["id"])
        assert_money(after["trust_escrow_balance_cents"], 0, "escrow")
        assert_conserved(
            before["trust_escrow_balance_cents"],
            after["trust_escrow_balance_cents"],
            -RICH_TRUST,
            "trust escrow",
        )
        assert_money(after["stipend_committed_cents"], 0, "committed stipend")
        assert after["minor_participant_count"] == 0
        assert after["casting_posture"] == "OPEN"

        packets, _pmeta = validate_paginated(
            api.list_minor_protections(applicant["id"], PA)
        )
        assert [row["status"] for row in packets] == ["RELEASED"]
        assert_money(packets[0]["trust_deposited_cents"], 0, "released deposit")
        assert_money(packets[0]["per_installment_cents"], 0, "released installment")

        cascaded = get_agreement(agreement["id"])
        assert cascaded["status"] == "VOIDED"
        assert cascaded["void_reason"] == "APPLICANT_WITHDRAWN"
        assert_money(cascaded["total_stipend_commitment_cents"], 0, "voided total")

        rows, meta = validate_paginated(api.list_post_obligations(agreement["id"], BA1))
        assert meta["total_count"] == 3
        assert [row["status"] for row in rows] == ["EXCUSED"] * 3

    def test_a_refund_removes_one_packets_deposit_and_leaves_the_others(self, api):
        """PRD §3.5: "And whenever the applicant's agreement moves to `VOIDED`,
        every packet of that applicant that is not already `RELEASED` — that is,
        any packet in `INCOMPLETE`, `COMPLETE` or `LAPSED` — moves to `RELEASED`
        with `trust_deposited_cents` and `per_installment_cents` zeroed and the
        production's `trust_escrow_balance_cents` recomputed."
        PRD §3.5: "Releasing the trust is a refund, and because both the packet's
        deposit figure and the escrow rollup are recomputed from scratch, the
        refund leaves the production's escrow figure exactly where it stood
        before the deposit."
        PRD §3.6: "Voiding conserves both committed stipend and trust escrow
        exactly."

        Design: Difficulty/compensating_invariant/minor_trust_escrow_conserved_across_deposit_then_withdrawal
        """
        (
            production,
            call,
            _applicant,
            _packet,
            agreement,
            single,
        ) = self._minor_with_a_funded_trust("Teen Trials S5", 5)

        # A second minor on the same production, so the rollup keeps a live
        # contributor after the first packet is released.
        second = setup_cleared_applicant(
            call["id"],
            minor=True,
            legal_name="Wes Marek",
            date_of_birth="2010-08-08",
            guardian_name="Xan Marek",
        )
        second_packet = setup_minor_protection(
            second["id"],
            work_permit_number="CA-WP-77121",
            permit_expires_on="2027-03-31",
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )
        setup_executed_agreement(second["id"], production["id"], **PLAIN_TERMS)
        # 220,000 x 0.15 is 33,000, which divides into four exact 8,250 shares.
        second_funded = setup_trust_deposit(second_packet["id"], 4)
        assert_money(second_funded["per_installment_cents"], 8_250, "installment")
        assert_money(second_funded["trust_deposited_cents"], 33_000, "deposited trust")

        both = get_production(production["id"])
        assert_money(
            both["trust_escrow_balance_cents"], RICH_TRUST + 33_000, "escrow"
        )
        assert both["minor_participant_count"] == 2

        voided = void_agreement(agreement["id"], "BUSINESS_AFFAIRS_VOID")
        assert voided["status"] == "VOIDED"

        after = get_production(production["id"])
        # The escrow falls by exactly the released packet's deposit, back to the
        # value it held before that packet was ever funded.
        assert_money(after["trust_escrow_balance_cents"], 33_000, "escrow")
        assert_conserved(
            both["trust_escrow_balance_cents"],
            after["trust_escrow_balance_cents"],
            -RICH_TRUST,
            "trust escrow",
        )
        assert_conserved(
            single["trust_escrow_balance_cents"],
            both["trust_escrow_balance_cents"],
            33_000,
            "trust escrow across the second deposit",
        )
        assert_money(after["stipend_committed_cents"], PLAIN_TOTAL, "committed stipend")
        assert after["minor_participant_count"] == 1
        assert after["casting_posture"] == "OPEN"

        survivors, _smeta = validate_paginated(
            api.list_minor_protections(second["id"], PA)
        )
        assert [row["status"] for row in survivors] == ["COMPLETE"]
        assert_money(survivors[0]["trust_deposited_cents"], 33_000, "surviving deposit")
