"""Compensation negotiation: the provisional/final dual variant, per-item
rounding, alternation, the re-inspection loop and its cap, and agree."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_return_case,
    create_return_case_in_negotiation,
    get_checklist_items,
    make_lessee_rep_headers,
    make_tech_inspector_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestProvisionalVsFinal:
    def test_provisional_estimate_and_final_agreed_diverge(self, api):
        """PRD §3.6: "Entering negotiation computes the provisional
        compensation estimate: for each checklist item in `NON_COMPLIANT` at
        that moment, the item's `rectification_cost_estimate_cents` is
        multiplied by the severity uplift — 1.50 for `CRITICAL`, 1.25 for
        `MAJOR`, 1.10 for `MINOR` — and each line is rounded half up to whole
        cents; the sum of those per-line rounded amounts is stored as
        `provisional_estimate_cents`."
        PRD §3.6: "Agreement captures the standing proposal as
        `agreed_total_cents` — null until this moment, thereafter the final
        compensation figure, which generally differs from the provisional
        estimate for the same items — and moves the case `NEGOTIATION →
        AGREED`."

        Design: Difficulty/dual_variant_calc/return_compensation_provisional_vs_final
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 100000, "INTERIOR": 4050})
        rc_now = validate_success(api.get_return_case(rc["id"], ADMIN))
        # round(100000 x 1.25) + round(4050 x 1.10) = 125000 + 4455
        assert rc_now["provisional_estimate_cents"] == 129455, (
            f"expected 129455, got {rc_now['provisional_estimate_cents']}")
        assert rc_now["agreed_total_cents"] is None

        proposed = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 100000}, ADMIN))
        agreed = validate_success(
            api.agree_return_case(
                rc["id"], {"expected_return_case_version": proposed["version"]},
                make_lessee_rep_headers(lessee["id"])))
        assert agreed["agreed_total_cents"] == 100000, (
            f"final variant is the negotiated lump sum, got {agreed['agreed_total_cents']}")
        assert agreed["provisional_estimate_cents"] != agreed["agreed_total_cents"]

    def test_final_variant_captures_standing_proposal_not_estimate(self, api):
        """PRD §3.6: "Agreement captures the standing proposal as
        `agreed_total_cents` — null until this moment, thereafter the final
        compensation figure, which generally differs from the provisional
        estimate for the same items — and moves the case `NEGOTIATION →
        AGREED`."

        Design: Difficulty/dual_variant_calc/return_compensation_provisional_vs_final
        """
        # Same NON_COMPLIANT items as the dual-variant recipe: ENGINE est
        # 100000 (MAJOR) + INTERIOR est 4050 (MINOR) -> provisional 129455.
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 100000, "INTERIOR": 4050})
        rc_now = validate_success(api.get_return_case(rc["id"], ADMIN))
        assert rc_now["provisional_estimate_cents"] == 129455
        assert rc_now["agreed_total_cents"] is None, (
            "agreed_total_cents stays null until agreement")

        proposed = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 100000}, ADMIN))
        agreed = validate_success(
            api.agree_return_case(
                rc["id"], {"expected_return_case_version": proposed["version"]},
                make_lessee_rep_headers(lessee["id"])))
        assert agreed["status"] == "AGREED"
        # Final variant: the negotiated lump sum, not the provisional figure.
        assert agreed["agreed_total_cents"] == 100000
        assert agreed["provisional_estimate_cents"] == 129455

    def test_provisional_estimate_per_item_rounding_order(self, api):
        """PRD §3.6: "the item's `rectification_cost_estimate_cents` is
        multiplied by the severity uplift — 1.50 for `CRITICAL`, 1.25 for
        `MAJOR`, 1.10 for `MINOR` — and each line is rounded half up to whole
        cents; the sum of those per-line rounded amounts is stored as
        `provisional_estimate_cents`."
        PRD §2.6: "the provisional compensation estimate applies it per
        checklist line before summation."

        Design: Corner/calculations/provisional_estimate_per_item_rounding_order
        """
        lease, _aircraft, _lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"INTERIOR": 1005, "PAINT": 1005})
        rc_now = validate_success(api.get_return_case(rc["id"], ADMIN))
        # Per-item: round_half_up(1005 x 1.10) = 1106 twice -> 2212.
        # Sum-then-round would give 2211.
        assert rc_now["provisional_estimate_cents"] == 2212, (
            f"per-item-first rounding pinned: expected 2212, got "
            f"{rc_now['provisional_estimate_cents']}")


class TestAlternation:
    def test_double_lessor_proposal_rejected(self, api):
        """PRD §3.6: "The first proposal — when `round_count` is zero — must
        come from the `LESSOR` side; thereafter the proposing side must
        differ from `current_proposer_side`, the side that tabled the
        standing proposal. A proposal out of turn, or a first proposal from
        the lessee side, fails with `ERR_PROPOSER_ALTERNATION`."
        PRD §3.6: "Each accepted proposal increments `round_count` by one and
        overwrites `current_proposal_cents` with the new `amount_cents` and
        `current_proposer_side` with the proposer's side."

        Design: Corner/validations/proposer_alternation_double_lessor_proposal
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        first = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 200000}, ADMIN))
        assert first["round_count"] == 1
        assert first["current_proposer_side"] == "LESSOR"

        # The side holding the standing proposal cannot propose again.
        resp = api.create_proposal(rc["id"], {"amount_cents": 190000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROPOSER_ALTERNATION, expected_status=409)
        rc_mid = validate_success(api.get_return_case(rc["id"], ADMIN))
        assert rc_mid["round_count"] == 1, (
            "the rejected proposal must not increment round_count")

        counter = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 150000},
                                make_lessee_rep_headers(lessee["id"])))
        assert counter["round_count"] == 2
        assert counter["current_proposal_cents"] == 150000
        assert counter["current_proposer_side"] == "LESSEE"

    def test_first_proposal_from_lessee_rejected(self, api):
        """PRD §3.6: "The first proposal — when `round_count` is zero — must
        come from the `LESSOR` side; thereafter the proposing side must
        differ from `current_proposer_side`, the side that tabled the
        standing proposal. A proposal out of turn, or a first proposal from
        the lessee side, fails with `ERR_PROPOSER_ALTERNATION`."

        Design: Corner/validations/proposer_alternation_double_lessor_proposal
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        resp = api.create_proposal(
            rc["id"], {"amount_cents": 150000}, make_lessee_rep_headers(lessee["id"]))
        validate_error(resp, ApiErrorId.ERR_PROPOSER_ALTERNATION, expected_status=409)


class TestAgree:
    def test_agree_by_proposing_side_rejected_then_counterparty_agrees(self, api):
        """PRD §3.6: "Agreement is the handshake of the side that did not
        table the standing proposal: either a `LessorAdmin` or the owning
        `LesseeRep` may accept, provided at least one proposal exists
        (`round_count` of one or more) and the agreeing side differs from
        `current_proposer_side` — a self-accept is
        `ERR_PROPOSER_ALTERNATION`."

        Design: Corner/validations/agree_by_proposing_side_rejected
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        proposed = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 200000}, ADMIN))
        version = proposed["version"]

        # The proposing side cannot accept its own proposal.
        resp = api.agree_return_case(
            rc["id"], {"expected_return_case_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROPOSER_ALTERNATION, expected_status=409)

        # The non-proposing side can, with the same version (no bump in
        # between).
        agreed = validate_success(
            api.agree_return_case(
                rc["id"], {"expected_return_case_version": version},
                make_lessee_rep_headers(lessee["id"])))
        assert agreed["status"] == "AGREED"
        assert agreed["agreed_total_cents"] == 200000


class TestReinspectionCycle:
    def test_self_loop_and_bounded_reinspection_cycle(self, api):
        """PRD §3.6: "The lessee may force one more look at the aircraft:
        requesting re-inspection loops the case `NEGOTIATION → INSPECTION`,
        provided `reinspection_count` is still below the hard cap of one — at
        the cap the request fails with `ERR_REINSPECTION_LIMIT`. The loop
        increments `reinspection_count`, conditionally cascades every
        `NON_COMPLIANT` checklist item back to `PENDING` (items `COMPLIANT`,
        `WAIVED`, or `COMPENSATED` are untouched), and deliberately preserves
        `round_count` and both `current_proposal_` fields, so negotiation
        resumes where it left off."
        PRD §3.6: "Each accepted proposal increments `round_count` by one and
        overwrites `current_proposal_cents` with the new `amount_cents` and
        `current_proposer_side` with the proposer's side."

        Design: Difficulty/non_linear_state_machine/return_case_negotiation_self_loop_and_reinspection_cycle
        """
        lease, _aircraft, lessee, rc, inspector = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        items = get_checklist_items(rc["id"])

        # Proposal self-loop: LESSOR then LESSEE.
        p1 = validate_success(api.create_proposal(rc["id"], {"amount_cents": 200000}, ADMIN))
        p2 = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 150000},
                                make_lessee_rep_headers(lessee["id"])))
        assert p2["round_count"] == 2
        assert p2["current_proposer_side"] == "LESSEE"

        # Loop back to INSPECTION; negotiation state preserved.
        looped = validate_success(
            api.request_reinspection(rc["id"], make_lessee_rep_headers(lessee["id"])))
        assert looped["status"] == "INSPECTION"
        assert looped["reinspection_count"] == 1
        assert looped["round_count"] == 2, (
            "round_count is preserved across the re-inspection loop")

        # The NON_COMPLIANT item was reverted to PENDING and can be
        # re-inspected with a new estimate.
        engine = validate_success(
            api.inspect_checklist_item(
                items["ENGINE"]["id"],
                {"outcome": "NON_COMPLIANT", "rectification_cost_estimate_cents": 70000},
                make_tech_inspector_headers(inspector["id"])))
        assert engine["status"] == "NON_COMPLIANT"

        # Second entry to NEGOTIATION recomputes the provisional estimate.
        rc2 = advance_return_case(rc["id"], "NEGOTIATION")
        assert rc2["provisional_estimate_cents"] == 87500, (
            f"round_half_up(70000 x 1.25) = 87500, got {rc2['provisional_estimate_cents']}")

        # The cycle is bounded at one.
        resp = api.request_reinspection(rc["id"], make_lessee_rep_headers(lessee["id"]))
        validate_error(resp, ApiErrorId.ERR_REINSPECTION_LIMIT, expected_status=409)

    def test_reinspection_preserves_standing_proposal_fields(self, api):
        """PRD §3.6: "The loop increments `reinspection_count`, conditionally
        cascades every `NON_COMPLIANT` checklist item back to `PENDING`
        (items `COMPLIANT`, `WAIVED`, or `COMPENSATED` are untouched), and
        deliberately preserves `round_count` and both `current_proposal_`
        fields, so negotiation resumes where it left off."

        Design: Difficulty/non_linear_state_machine/return_case_negotiation_self_loop_and_reinspection_cycle
        """
        lease, _aircraft, lessee, rc, inspector = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        validate_success(api.create_proposal(rc["id"], {"amount_cents": 200000}, ADMIN))
        looped = validate_success(
            api.request_reinspection(rc["id"], make_lessee_rep_headers(lessee["id"])))
        assert looped["current_proposal_cents"] == 200000
        assert looped["current_proposer_side"] == "LESSOR"
        assert looped["round_count"] == 1
