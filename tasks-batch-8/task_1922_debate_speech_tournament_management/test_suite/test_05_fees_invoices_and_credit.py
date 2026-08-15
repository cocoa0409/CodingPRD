"""Entry fees, late surcharges, the volume-discount invoice, and credit gates."""
from test_helpers import (
    LATE_FEE_DAY,
    LATE_FEE_STARTS_AT,
    LOCK_DAY,
    TEST_USERS,
    accept_contract,
    add_entry,
    confirm_entry,
    confirm_school,
    create_contract_for_school,
    fill_contract,
    get_entry,
    get_school,
    lock_tournament,
    make_coach_headers,
    set_clock,
    setup_registration_scenario,
    setup_school_with_shortfall,
    validate_error,
    validate_success,
    withdraw_entry,
)

DIRECTOR = TEST_USERS["director_headers"]


def _late_fee_scenario(api):
    """Tournament fee 1999 with a 15% late surcharge from 2026-08-03; clock at
    2026-08-04; school Alpha with 7 created entries. Returns (ws, entry ids)."""
    ws = setup_registration_scenario(
        name="Districts LF", prelim_round_count=4, entry_fee_cents=1999,
        late_fee_starts_at=LATE_FEE_STARTS_AT, late_fee_surcharge_pct=0.15,
        divisions=(("d", "DEBATE", "CX", "VARSITY", 8, None),),
        schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
        confirm_schools=False, lock=False)
    set_clock(LATE_FEE_DAY)
    entries = [add_entry(ws["schools"]["a"]["id"], ws["divisions"]["d"]["id"],
                         f"E-{n + 1}") for n in range(7)]
    return ws, entries


class TestLateFeeRoundingOrder:
    def test_per_entry_surcharge_rounded_half_up(self, api):
        """PRD §3.2: "if `late_fee_starts_at` is set and the current logical UTC
        is at or after it, the charged fee is the base multiplied by one plus
        `late_fee_surcharge_pct`, rounded half up to a whole cent; otherwise the
        charged fee is the base."

        Design: Difficulty/combinatorial_formula/late_fee_per_entry_rounding_order
        """
        ws, entries = _late_fee_scenario(api)
        school_id = ws["schools"]["a"]["id"]
        for entry in entries:
            confirm_entry(entry["id"], school_id)

        for entry in entries:
            fetched = get_entry(entry["id"])
            # round_half_up(1999 * 1.15) = round_half_up(2298.85) = 2299 per entry.
            assert fetched["fee_charged_cents"] == 2299, (
                "surcharge computed and rounded per entry at confirm time")
        assert get_school(school_id)["confirmed_entry_count"] == 7

    def test_invoice_sums_per_entry_rounded_fees(self, api):
        """PRD §2.9: "The late-entry surcharge is computed and rounded per entry
        at the moment that entry is confirmed, and only then summed into the
        school's fee subtotal; summing base fees first and applying the surcharge
        to the sum is forbidden because it yields a different total."

        Design: Difficulty/combinatorial_formula/late_fee_per_entry_rounding_order
        """
        ws, entries = _late_fee_scenario(api)
        school_id = ws["schools"]["a"]["id"]
        for entry in entries:
            confirm_entry(entry["id"], school_id)

        school = get_school(school_id)
        # 7 x 2299 = 16093; sum-then-round (round(13993 * 1.15) = 16092) forbidden.
        assert school["invoice_balance_cents"] == 16093


class TestVolumeDiscountTier:
    def _scenario(self, api):
        """Alpha with 11 confirmed entries at 1000 cents each (entry fees 11000,
        obligation ceil(11/2)*4 = 24) plus an 8-round hired contract (within the
        shortfall); the contract is filled and accepted."""
        ws = setup_school_with_shortfall(
            name="Districts DC", entries=11, prelim_round_count=4,
            entry_fee_cents=1000, per_school_entry_cap=12)
        school_id = ws["schools"]["a"]["id"]
        contract = create_contract_for_school(school_id, 8)
        ws["contract"] = contract
        fill_contract(contract["id"], "Hired Alpha")
        accept_contract(contract["id"], school_id)
        return ws

    def test_contract_fees_at_premium_boundary(self, api):
        """PRD §3.3: "The fee is base rounds times 5000 cents plus premium rounds
        times 7500 cents."
        PRD §3.3: "The final fee is computed under the final-invoice variant —
        same tiered formula, but the candidate set excludes `REQUESTED` contracts."

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_pre_discount
        """
        ws = self._scenario(api)
        contract = ws["contract"]
        # Cumulative position hits the 8-round premium threshold exactly: zero
        # premium rounds, so both variants price 8 x 5000 = 40000.
        assert contract["fee_quote_cents"] == 40000
        fetched = validate_success(api.get_contract(contract["id"], DIRECTOR))
        assert fetched["final_fee_cents"] == 40000

    def test_discount_tier_keyed_on_pre_discount_subtotal(self, api):
        """PRD §3.3: "The volume-discount tier is selected on that pre-discount
        value: a subtotal of at least 100000 cents earns 10 percent, a subtotal of
        at least 50000 cents earns 5 percent, and anything below earns nothing".
        PRD §2.9: "The discount tier is selected on the pre-discount subtotal, and
        the selected tier does not change even though applying the discount may
        drop the final total below the threshold that selected it."
        PRD §2.9: "the entry fees and judge fees are each multiplied by the tier
        percentage and rounded half up independently, then summed".

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_pre_discount
        """
        ws = self._scenario(api)
        school = get_school(ws["schools"]["a"]["id"])
        # pre-discount 11000 + 40000 = 51000 -> 5% tier; discount per component
        # round(550) + round(2000) = 2550; 51000 - 2550 = 48450 (< 50000, tier kept).
        assert school["invoice_balance_cents"] == 48450


class TestInvoiceConservation:
    def test_confirm_charges_fee_into_invoice(self, api):
        """PRD §3.2: "On success, the school's `confirmed_entry_count`,
        `judge_obligation_rounds`, `shortfall_rounds`, `obligation_status`, and
        `invoice_balance_cents` are recomputed".
        PRD §3.3: "The entry-fees component is the sum of `fee_charged_cents` over
        the school's entries in `CONFIRMED`, `COMPETING`, `ADVANCED`,
        `ELIMINATED`, or `FINISHED` — the invoice status set."

        Design: Difficulty/compensating_invariant/invoice_conservation_under_confirm_withdraw
        """
        ws = setup_registration_scenario(
            name="Districts IC", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        assert get_school(school_id)["invoice_balance_cents"] == 0

        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        confirm_entry(entry["id"], school_id)
        assert get_school(school_id)["invoice_balance_cents"] == 2500, (
            "the confirm added exactly one entry fee")

    def test_withdraw_restores_invoice_to_prior_value(self, api):
        """PRD §3.2: "First, the entry leaves the invoice status set, so the
        school's `confirmed_entry_count` and `judge_obligation_rounds` are
        recomputed".
        PRD §3.2: "The recorded fee is an audit trail on the entry; the school's
        invoice includes it only while the entry's status is non-`WITHDRAWN`."

        Design: Difficulty/compensating_invariant/invoice_conservation_under_confirm_withdraw
        """
        ws = setup_registration_scenario(
            name="Districts IC", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        confirm_entry(entry["id"], school_id)
        assert get_school(school_id)["invoice_balance_cents"] == 2500

        withdraw_entry(entry["id"], school_id)
        assert get_school(school_id)["invoice_balance_cents"] == 0, (
            "compensating withdraw restores the invoice exactly")
        fetched = get_entry(entry["id"])
        assert fetched["status"] == "WITHDRAWN"
        assert fetched["fee_charged_cents"] == 2500, (
            "fee retained as audit but excluded from the invoice status set")


class TestCreditLimit:
    def test_credit_boundary_exact_allowed_then_exceeded(self, api):
        """PRD §3.2: "If the school has a `credit_limit_cents` ceiling, the
        projected `invoice_balance_cents` after this confirm must not exceed it,
        otherwise the confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)."

        Design: Corner/validations/credit_limit_boundary_exact_allowed_then_exceeded
        """
        ws = setup_registration_scenario(
            name="CL", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": [],
                      "credit_limit_cents": 2500},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        e1 = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        e2 = add_entry(school_id, ws["divisions"]["d"]["id"], "A-Two")

        confirm_entry(e1["id"], school_id)  # projection 2500 <= limit 2500

        resp = api.confirm_entry(e2["id"], make_coach_headers(school_id))
        validate_error(resp, "ERR_CREDIT_LIMIT_EXCEEDED")  # projection 5000 > 2500

        school = get_school(school_id)
        assert school["invoice_balance_cents"] == 2500
        assert school["confirmed_entry_count"] == 1

    def test_phase_gate_beats_credit_limit_on_confirm(self, api):
        """PRD §2.7: "Fifth, the tournament phase gate is evaluated
        (`ERR_TOURNAMENT_PHASE_FORBIDDEN`, HTTP 409): writes into the registration
        graph are allowed only while the tournament is `REGISTRATION_OPEN`".
        PRD §2.7: "Business-rule checks then run in their own pinned relative
        order where several guard the same operation."

        Design: Difficulty/priority_pair_validation_conflict/phase_gate_beats_credit_limit_on_confirm
        """
        ws = setup_registration_scenario(
            name="Districts PP", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": [],
                      "credit_limit_cents": 2400},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        # Alpha confirms while it has zero confirmed entries (obligation 0).
        confirm_school(school_id)
        set_clock(LOCK_DAY)
        lock_tournament(ws["t"]["id"])

        # Post-lock the confirm violates the phase gate (and would also push the
        # projected invoice 2500 over the 2400 ceiling); the phase error wins.
        resp = api.confirm_entry(entry["id"], make_coach_headers(school_id))
        validate_error(resp, "ERR_TOURNAMENT_PHASE_FORBIDDEN")
        assert get_entry(entry["id"])["status"] == "REGISTERED"

    def test_rejected_confirm_leaves_invoice_untouched(self, api):
        """PRD §2.7: "Fifth, the tournament phase gate is evaluated
        (`ERR_TOURNAMENT_PHASE_FORBIDDEN`, HTTP 409): writes into the registration
        graph are allowed only while the tournament is `REGISTRATION_OPEN`".
        PRD §3.2: "Confirm requires the tournament to be `REGISTRATION_OPEN`
        (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`)".

        Design: Difficulty/priority_pair_validation_conflict/phase_gate_beats_credit_limit_on_confirm
        """
        ws = setup_registration_scenario(
            name="Districts PP", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": [],
                      "credit_limit_cents": 2400},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        confirm_school(school_id)
        set_clock(LOCK_DAY)
        lock_tournament(ws["t"]["id"])

        validate_error(
            api.confirm_entry(entry["id"], make_coach_headers(school_id)),
            "ERR_TOURNAMENT_PHASE_FORBIDDEN")

        school = get_school(school_id)
        assert school["invoice_balance_cents"] == 0, "no fee charged"
        assert school["confirmed_entry_count"] == 0
        assert get_entry(entry["id"])["fee_charged_cents"] == 0


class TestImmediateConsistency:
    def test_confirm_response_immediately_visible(self, api):
        """PRD §2.10: "Derived fields on a school — its obligation, coverage,
        shortfall, obligation posture, and invoice balance — are reconciled
        immediately whenever the underlying registration graph mutates: an entry
        confirmed or withdrawn, a judge committed or withdrawn, a contract filled,
        accepted, paid, cancelled, or auto-released."
        PRD §3.2: "the school's invoice includes it only while the entry's status
        is non-`WITHDRAWN`."

        Design: Corner/consistency_model/confirm_response_immediately_visible
        """
        ws = setup_registration_scenario(
            name="IM", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")

        resp = api.confirm_entry(entry["id"], make_coach_headers(school_id))
        body = validate_success(resp)
        assert body["status"] == "CONFIRMED", "confirm response carries the new state"
        assert body["fee_charged_cents"] == 2500

        fetched = validate_success(api.get_entry(entry["id"], DIRECTOR))
        assert fetched["status"] == "CONFIRMED"
        assert fetched["fee_charged_cents"] == 2500
        assert get_school(school_id)["invoice_balance_cents"] == 2500, (
            "no read-your-writes lag on the school's invoice")
