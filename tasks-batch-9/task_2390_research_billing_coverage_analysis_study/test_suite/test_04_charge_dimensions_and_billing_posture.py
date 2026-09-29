"""Charge review: the two independent state dimensions, the posture gates, and
the order in which the routing guard and the posture guard fire.
"""

from test_helpers import (
    MANAGER_ONE,
    REVIEWER_ONE,
    api_client,
    charge_review_payload,
    determine_qct,
    item_spec,
    make_manager_headers,
    make_reviewer_headers,
    open_finding,
    post_charge,
    raise_invoice,
    read_charge,
    read_study,
    read_summary,
    review_charge,
    setup_charge_awaiting_review,
    setup_priced_study_with_sponsor_charges,
    setup_sponsor_unbilled_charge,
    submit_invoice,
    validate_error,
    validate_success,
)

SPONSOR_DRUG = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)
PROMOTIONAL_KIT = item_spec(
    "A9270",
    classification="PROMOTIONAL",
    budget_category="NOT_BUDGETED",
    charge_master_unit_cents=0,
    negotiated_unit_cents=0,
    expected_occurrences=1,
)


def _review(charge_id, decision, **overrides):
    return api_client.review_charge(
        charge_id,
        charge_review_payload(decision, **overrides),
        make_reviewer_headers(REVIEWER_ONE),
    )


class TestChargeDimensionsMoveIndependently:
    """``routing_state`` is segregation; ``billing_state`` is fiscal."""

    def _priced_study(self):
        return setup_priced_study_with_sponsor_charges(
            [],
            item_specs=[SPONSOR_DRUG, PROMOTIONAL_KIT],
            indirect_rate_pct=32.0,
            study_overrides={
                "protocol_number": "AMC-2390-L",
                "funding_source": "INDUSTRY_SPONSORED",
            },
            qct_basis=None,
        )

    def test_01_one_review_moves_the_two_dimensions_to_unrelated_values(self):
        """Holding for the sponsor moves only the segregation dimension, while
        writing off as promotional moves both — to a terminal fiscal state.

        PRD §3.7: "A `decision` of `HOLD_FOR_SPONSOR` moves the charge
        `UNROUTED → ROUTED_SPONSOR` while `billing_state` stays `UNBILLED` and
        `unbilled_since` is left exactly as it was — the charge simply becomes
        invoiceable, and its age keeps accruing from its original baseline."

        Design: Difficulty/non_linear_state_machine/charge_routing_and_billing_dimensions_move_independently
        """
        ctx = self._priced_study()
        sponsor_charge = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        promotional_charge = post_charge(
            ctx["study"]["id"],
            charge_code="A9270",
            service_date="2026-08-01",
            amount_cents=0,
        )
        baseline = sponsor_charge["unbilled_since"]

        held = validate_success(_review(sponsor_charge["id"], "HOLD_FOR_SPONSOR"), 200)
        assert held["routing_state"] == "ROUTED_SPONSOR"
        assert held["billing_state"] == "UNBILLED"
        assert held["unbilled_since"] == baseline

        written_off = validate_success(
            _review(promotional_charge["id"], "NO_CHARGE_PROMOTIONAL"), 200
        )
        assert written_off["routing_state"] == "ROUTED_NONE"
        assert written_off["billing_state"] == "WRITTEN_OFF"

        assert read_study(ctx["study"]["id"])["sponsor_unbilled_cents"] == 40000

    def test_02_invoice_submission_moves_only_the_fiscal_dimension(self):
        """The charge becomes ``INVOICED_SPONSOR`` while its routing state stays
        exactly where the review put it.

        PRD §3.8: "Every charge carrying this invoice's identifier moves
        `UNBILLED → INVOICED_SPONSOR`, and the study's `sponsor_unbilled_cents`
        and `sponsor_receivable_cents` are recomputed — their sum being
        invariant across the move."

        Design: Difficulty/non_linear_state_machine/charge_routing_and_billing_dimensions_move_independently
        """
        ctx = self._priced_study()
        sponsor_charge = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        review_charge(sponsor_charge["id"], "HOLD_FOR_SPONSOR")

        invoice = raise_invoice(ctx["study"]["id"])
        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 40000
        assert invoice["indirect_cents"] == 12800
        assert invoice["net_total_cents"] == 52800

        submitted = submit_invoice(invoice["id"])
        assert submitted["status"] == "SUBMITTED"

        charge = read_charge(sponsor_charge["id"])
        assert charge["routing_state"] == "ROUTED_SPONSOR"
        assert charge["billing_state"] == "INVOICED_SPONSOR"
        assert charge["sponsor_invoice_id"] == invoice["id"]

        summary = read_summary(ctx["study"]["id"])
        assert summary["sponsor_unbilled_cents"] == 0
        assert summary["sponsor_receivable_cents"] == 40000
        assert summary["unrouted_charge_count"] == 0


class TestAlreadyRoutedOutranksTheBillingBlock:
    """Both guards could reject the same review; the routing guard is earlier."""

    def _blocked_study(self):
        ctx = setup_sponsor_unbilled_charge(
            study_overrides={"protocol_number": "AMC-2390-M"},
        )
        ctx["unrouted_charge"] = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        ctx = dict(ctx)
        ctx["finding"] = open_finding(ctx["study"]["id"])
        ctx["study"] = read_study(ctx["study"]["id"])
        return ctx

    def test_03_a_routed_charge_on_a_blocked_study_reports_the_routing_guard(self):
        """The charge is already routed and the study is `ALL_BLOCKED`; the
        earlier check in the fixed order is the one reported.

        PRD §2.11: "When several checks could reject the same request, they are
        evaluated in the fixed order below and the first failure is the one
        reported. Text order elsewhere in this document does not imply
        precedence; this list does."

        Design: Difficulty/priority_pair_validation_conflict/already_routed_beats_billing_blocked_on_charge_review
        """
        ctx = self._blocked_study()
        assert ctx["study"]["open_finding_count"] == 1
        assert ctx["study"]["billing_hold_posture"] == "ALL_BLOCKED"
        assert ctx["charge"]["routing_state"] == "ROUTED_SPONSOR"

        validate_error(
            _review(ctx["charge"]["id"], "CLEAR_TO_PAYER"),
            "ERR_CHARGE_ALREADY_ROUTED",
            409,
        )

        unchanged = read_charge(ctx["charge"]["id"])
        assert unchanged["routing_state"] == "ROUTED_SPONSOR"
        assert unchanged["billing_state"] == "UNBILLED"

    def test_04_each_guard_fires_alone_when_only_its_own_condition_holds(self):
        """An unrouted charge on the blocked study reports the posture; the
        routed charge on an unblocked study reports the routing guard.

        PRD §2.9: "`ALL_BLOCKED` refuses every charge review decision and every
        invoice submission with `ERR_STUDY_BILLING_BLOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/already_routed_beats_billing_blocked_on_charge_review
        """
        ctx = self._blocked_study()
        validate_error(
            _review(ctx["unrouted_charge"]["id"], "HOLD_FOR_SPONSOR"),
            "ERR_STUDY_BILLING_BLOCKED",
            409,
        )

        open_posture = setup_sponsor_unbilled_charge(
            study_overrides={"protocol_number": "AMC-2390-M2"},
        )
        assert open_posture["study"]["billing_hold_posture"] == "OPEN"
        validate_error(
            _review(open_posture["charge"]["id"], "HOLD_FOR_SPONSOR"),
            "ERR_CHARGE_ALREADY_ROUTED",
            409,
        )


class TestPayerRoutingDependsOnTheStudysQctState:
    """The block lives on the study, not on the charge."""

    def _undetermined(self):
        return setup_charge_awaiting_review(
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-W"},
        )

    def test_05_clearing_to_the_payer_is_refused_while_the_study_is_undetermined(self):
        """A freshly registered protocol sits at `PAYER_BLOCKED`, and the
        refusal leaves the charge completely untouched — while the sponsor-side
        disposition is still permitted.

        PRD §2.9: "`PAYER_BLOCKED` still permits sponsor-side and promotional
        dispositions but refuses to clear anything to the payer, with
        `ERR_PAYER_BILLING_BLOCKED_NO_QCT`."

        Design: Difficulty/cross_entity_state_dependency/payer_routing_requires_study_qct_state_not_charge_state
        """
        ctx = self._undetermined()
        assert ctx["study"]["qct_determination"] == "UNDETERMINED"
        assert ctx["study"]["billing_hold_posture"] == "PAYER_BLOCKED"
        assert ctx["charge"]["routing_state"] == "UNROUTED"

        validate_error(
            _review(ctx["charge"]["id"], "CLEAR_TO_PAYER"),
            "ERR_PAYER_BILLING_BLOCKED_NO_QCT",
            409,
        )

        untouched = read_charge(ctx["charge"]["id"])
        assert untouched["routing_state"] == "UNROUTED"
        assert untouched["billing_state"] == "UNBILLED"
        assert untouched["reviewed_by_user_id"] is None
        assert untouched["reviewed_at"] is None

        held = validate_success(
            _review(
                ctx["charge"]["id"],
                "HOLD_FOR_SPONSOR",
                override_justification="Sponsor agreed to absorb the panel pending review.",
            ),
            200,
        )
        assert held["routing_state"] == "ROUTED_SPONSOR"
        assert held["billing_state"] == "UNBILLED"

    def test_06_recording_the_determination_unblocks_the_identical_decision(self):
        """Nothing about the charge changes; the study's determination does.

        PRD §3.7: "it is the one decision a `PAYER_BLOCKED` study refuses, with
        `ERR_PAYER_BILLING_BLOCKED_NO_QCT`, so it requires the posture to be
        `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/payer_routing_requires_study_qct_state_not_charge_state
        """
        ctx = self._undetermined()
        validate_error(
            _review(ctx["charge"]["id"], "CLEAR_TO_PAYER"),
            "ERR_PAYER_BILLING_BLOCKED_NO_QCT",
            409,
        )

        determined = determine_qct(
            ctx["study"]["id"], basis="DEEMED_IND_IDE", registry_number="NCT10000017"
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"
        assert determined["billing_hold_posture"] == "OPEN"

        cleared = validate_success(_review(ctx["charge"]["id"], "CLEAR_TO_PAYER"), 200)
        assert cleared["routing_state"] == "ROUTED_PAYER"
        assert cleared["billing_state"] == "BILLED_PAYER"
        assert cleared["improper_flag"] is False

        summary = validate_success(
            api_client.get_charge_review_summary(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert summary["payer_billed_cents"] == 9000
        assert summary["billing_hold_posture"] == "OPEN"
        assert summary["unrouted_charge_count"] == 0
