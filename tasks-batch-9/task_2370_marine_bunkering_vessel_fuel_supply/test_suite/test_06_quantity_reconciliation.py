"""Settling the delivered tonnage and the paperwork that waits on it.

Three figures are recorded at the end of every transfer, but which one governs the
money is dictated by the buyer's contract rather than by whoever files them. The
MARPOL note then waits on the measurement dimension specifically, not on the
physical one.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    OPS,
    SURVEYOR,
    api_client,
    assert_bunker_delivery_note,
    assert_order_state,
    build_agreed_order,
    build_delivered_order,
    build_joint_survey_context,
    create_bdn_payload,
    file_joint_survey,
    issue_bdn,
    joint_survey_payload,
    make_customer_rep_headers,
    quantity_decision_payload,
    read_order,
    submit_quantity_decision,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAgreedQuantityBasis:
    """The same three figures settle differently under the two contract bases."""

    def test_surveyed_figure_governs_on_the_joint_survey_basis(self):
        """PRD §3.5: "The surveyor then closes the loop with a quantity `decision`
        of `AGREE`, advancing `RESURVEYED → AGREED` provided `surveyed_mt` is not
        null: the surveyor's figure governs, so `agreed_quantity_mt` is
        `surveyed_mt` rounded to three decimal places, `measurement_basis` is set to
        `JOINT_SURVEY`, and `shortfall_mt` is `barge_sounding_mt` minus
        `agreed_quantity_mt`, rounded to three decimal places — normally a positive
        difference the supplier absorbs."
        PRD §3.5: "`meter_mt` exists only to police the barge sounding through the
        one-tonne cross-check at completion."

        Design: Difficulty/dual_variant_calc/agreed_quantity_supplier_vs_joint_survey_basis
        """
        ctx = build_delivered_order(build_joint_survey_context())
        assert_order_state(ctx["order"], "DELIVERED", "FIGURES_RECORDED")

        file_joint_survey(ctx, 1191.850)
        assert_order_state(ctx["order"], "DELIVERED", "RESURVEYED")
        order = submit_quantity_decision(ctx, "AGREE")

        assert_order_state(order, "DELIVERED", "AGREED")
        assert order["measurement_basis"] == "JOINT_SURVEY", (
            "The independent survey basis must be recorded, got "
            f"{order['measurement_basis']}"
        )
        assert order["agreed_quantity_mt"] == pytest.approx(1191.850, abs=0.0005), (
            f"The surveyed figure governs, got {order['agreed_quantity_mt']}"
        )
        assert order["shortfall_mt"] == pytest.approx(6.600, abs=0.0005), (
            "1198.450 pumped less 1191.850 settled is a 6.600 mt shortfall, got "
            f"{order['shortfall_mt']}"
        )
        assert order["barge_sounding_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The supplier figure is still recorded even though it does not govern, "
            f"got {order['barge_sounding_mt']}"
        )

    def test_barge_sounding_governs_in_the_same_request_on_the_supplier_basis(self):
        """PRD §3.5: "**On the supplier-figures branch** — taken when the customer's
        `settlement_basis` is `SUPPLIER_FIGURES` — the measurement dimension advances
        `FIGURES_RECORDED → AGREED` inside the very same completion request."
        PRD §3.5: "The supplier's own barge tank sounding governs:
        `agreed_quantity_mt` is `barge_sounding_mt` rounded to three decimal places,
        `measurement_basis` is set to `SUPPLIER_FIGURES`, and `shortfall_mt` is
        0.000, because the governing figure and the pumped figure are one and the
        same."

        Design: Difficulty/dual_variant_calc/agreed_quantity_supplier_vs_joint_survey_basis
        """
        ctx = build_delivered_order()
        order = ctx["order"]

        assert_order_state(order, "DELIVERED", "AGREED")
        assert order["measurement_basis"] == "SUPPLIER_FIGURES", (
            f"Expected the supplier basis, got {order['measurement_basis']}"
        )
        assert order["agreed_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The barge sounding governs on this branch, got "
            f"{order['agreed_quantity_mt']}"
        )
        assert order["shortfall_mt"] == pytest.approx(0.000, abs=0.0005), (
            "The governing and pumped figures coincide, so there is no shortfall, "
            f"got {order['shortfall_mt']}"
        )

    def test_the_contract_not_the_caller_selects_the_basis(self):
        """PRD §3.5: "From `FIGURES_RECORDED` the measurement dimension forks, and
        which branch is taken is dictated by the customer's contract, never chosen
        freely."
        PRD §3.5: "that filing requires the order's `logistics_status` to be
        `DELIVERED` and its `measurement_status` to be either `FIGURES_RECORDED` or
        `DISPUTED`, and an illegal measurement state is rejected with
        `ERR_INVALID_MEASUREMENT_STATE` (HTTP 409)."

        A `SUPPLIER_FIGURES` buyer's order is already `AGREED` when pumping closes,
        so nobody can file a survey to move it onto the other variant.

        Design: Difficulty/dual_variant_calc/agreed_quantity_supplier_vs_joint_survey_basis
        """
        ctx = build_delivered_order()
        assert_order_state(ctx["order"], "DELIVERED", "AGREED")

        response = api_client.file_joint_survey(
            ctx["order"]["id"], joint_survey_payload(1191.850), SURVEYOR
        )

        validate_error(response, ApiErrorId.ERR_INVALID_MEASUREMENT_STATE)
        assert ctx["order"]["agreed_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The settled tonnage must remain the barge sounding"
        )


class TestDeliveryNoteWaitsOnMeasurement:
    """The note depends on the measurement dimension, not the physical one."""

    def test_note_is_refused_while_the_survey_is_outstanding(self):
        """PRD §3.7: "Issuance requires the order's `measurement_status` to be
        `AGREED` with a non-null `agreed_quantity_mt`, or the request is rejected
        with `ERR_MEASUREMENT_NOT_AGREED` (HTTP 409) — which is how the
        `JOINT_SURVEY_MANDATORY` settlement basis makes a surveyor's figure a
        precondition of paperwork."
        PRD §3.5: "**On the joint-survey branch** — mandatory when the customer's
        `settlement_basis` is `JOINT_SURVEY_MANDATORY` — the completion request
        leaves the order in `FIGURES_RECORDED` awaiting an independent figure, and
        `agreed_quantity_mt`, `measurement_basis` and `shortfall_mt` all stay null."

        Design: Difficulty/cross_entity_state_dependency/bdn_issuance_blocked_until_measurement_agreed
        """
        ctx = build_delivered_order(build_joint_survey_context())
        assert_order_state(ctx["order"], "DELIVERED", "FIGURES_RECORDED")
        assert ctx["order"]["agreed_quantity_mt"] is None, (
            "The settled tonnage stays null until the surveyor files, got "
            f"{ctx['order']['agreed_quantity_mt']}"
        )

        response = api_client.create_bunker_delivery_note(
            create_bdn_payload(ctx["order"]["id"]), OPS
        )

        validate_error(response, ApiErrorId.ERR_MEASUREMENT_NOT_AGREED)
        notes, _meta = validate_paginated(
            api_client.list_bunker_delivery_notes(
                OPS, params={"delivery_order_id": ctx["order"]["id"]}
            )
        )
        assert notes == [], (
            f"The refused issuance must leave no note behind, got {notes}"
        )

    def test_note_snapshots_the_surveyed_tonnage_once_measurement_agrees(self):
        """PRD §3.7: "A newly issued note snapshots `delivered_quantity_mt` from the
        order's `agreed_quantity_mt` at the moment of issuance, sets `status` to
        `ISSUED`, and starts the sample custody clock: `sample_retention_until` is
        the note's `created_at` plus a 90-day retention period,
        `sample_custody_status` begins as `RETAINED`, and `sample_released_at` is
        null."

        Design: Difficulty/cross_entity_state_dependency/bdn_issuance_blocked_until_measurement_agreed
        """
        ctx = build_agreed_order(build_joint_survey_context(), surveyed_mt=1191.850)
        assert_order_state(ctx["order"], "DELIVERED", "AGREED")

        note = issue_bdn(ctx)

        assert_bunker_delivery_note(note)
        assert note["status"] == "ISSUED", (
            f"A fresh note opens ISSUED, got {note['status']}"
        )
        assert note["delivered_quantity_mt"] == pytest.approx(1191.850, abs=0.0005), (
            "The note must carry the surveyed tonnage, not the barge sounding, got "
            f"{note['delivered_quantity_mt']}"
        )
        assert note["sample_custody_status"] == "RETAINED", (
            f"Custody opens RETAINED, got {note['sample_custody_status']}"
        )
        assert note["sample_released_at"] is None, (
            f"Nothing has gone to the laboratory yet, got {note['sample_released_at']}"
        )
        assert note["sample_retention_until"].startswith("2026-11-08T14:30:00"), (
            "90 days after the 2026-08-10T14:30:00Z creation instant is "
            f"2026-11-08T14:30:00Z, got {note['sample_retention_until']}"
        )

    def test_note_issuance_succeeds_only_after_the_agree_decision(self):
        """PRD §3.7: "The MARPOL bunker delivery note is the legal evidence of what
        was delivered, and it may only be issued once the tonnage is settled."
        PRD §3.5: "A `Surveyor` then files `surveyed_mt`, advancing the measurement
        dimension to `RESURVEYED`"

        The physical dimension is already `DELIVERED` throughout, so the refusal and
        the later success turn purely on the measurement dimension.

        Design: Difficulty/cross_entity_state_dependency/bdn_issuance_blocked_until_measurement_agreed
        """
        ctx = build_delivered_order(build_joint_survey_context())

        validate_error(
            api_client.create_bunker_delivery_note(
                create_bdn_payload(ctx["order"]["id"]), OPS
            ),
            ApiErrorId.ERR_MEASUREMENT_NOT_AGREED,
        )

        file_joint_survey(ctx, 1191.850)
        validate_error(
            api_client.create_bunker_delivery_note(
                create_bdn_payload(ctx["order"]["id"]), OPS
            ),
            ApiErrorId.ERR_MEASUREMENT_NOT_AGREED,
        )
        assert ctx["order"]["logistics_status"] == "DELIVERED", (
            "The physical dimension never moved, got "
            f"{ctx['order']['logistics_status']}"
        )

        submit_quantity_decision(ctx, "AGREE")
        note = validate_success(
            api_client.create_bunker_delivery_note(
                create_bdn_payload(ctx["order"]["id"]), OPS
            ),
            201,
        )
        assert note["delivered_quantity_mt"] == pytest.approx(1191.850, abs=0.0005), (
            f"Expected the settled 1191.850 mt on the note, got "
            f"{note['delivered_quantity_mt']}"
        )


class TestQuantityDecisionGuards:
    """Three guards on one endpoint, answered in the declared order."""

    def test_the_note_outranks_the_missing_discrepancy_on_a_dispute(self):
        """PRD §3.5: "That dispute right is exercised by the buyer's representative
        through a quantity `decision` of `DISPUTE`, which moves the measurement dimension
        `AGREED → DISPUTED` and clears `agreed_quantity_mt`, `measurement_basis` and
        `shortfall_mt` back to null. Two conditions guard it. No bunker delivery note in
        status `ISSUED` may exist for the order, because a note already fixes the
        delivered figure on MARPOL paperwork — an attempt after issuance is rejected with
        `ERR_BDN_ALREADY_ISSUED`. And the customer must actually have evidence of a
        shortfall: `vessel_sounding_mt` must be strictly less than `barge_sounding_mt`, or
        the dispute is rejected with `ERR_NO_MEASUREMENT_DISCREPANCY`."
        PRD §2.8: "State legality, in this internal order: nomination state, compliance
        approval, order logistics state, measurement agreement, measurement state
        legality, an already-issued delivery note, a not-yet-issued delivery note, an
        already-existing invoice, invoice state legality, invoice issuance for a claim,
        claim state legality, sample release, retest limit, off-spec finding, measurement
        discrepancy, asset quarantine, asset state legality, open spill incident, and
        spill incident state."
        PRD §2.8: "The order's `measurement_status` legality check guards two operations
        with `ERR_INVALID_MEASUREMENT_STATE`: filing a joint survey and submitting a
        quantity decision."

        The vessel received 1199.000 against a barge sounding of 1198.450, so there is no
        shortfall to dispute. Before the note is issued that is the only defect and it is
        reported; after issuance the same request breaks both rules at once and must
        report the already-issued note, which sits earlier in the state-legality order.

        Design: Corner/validations/measurement_decision_guard_errors_rejected
        """
        ctx = build_delivered_order(
            figures={
                "barge_sounding_mt": 1198.450,
                "vessel_sounding_mt": 1199.000,
                "meter_mt": 1197.800,
            }
        )
        assert_order_state(ctx["order"], "DELIVERED", "AGREED")

        premature_agree = api_client.submit_quantity_decision(
            ctx["order"]["id"], quantity_decision_payload("AGREE"), SURVEYOR
        )
        validate_error(premature_agree, ApiErrorId.ERR_INVALID_MEASUREMENT_STATE)

        no_shortfall = api_client.submit_quantity_decision(
            ctx["order"]["id"],
            quantity_decision_payload("DISPUTE"),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(no_shortfall, ApiErrorId.ERR_NO_MEASUREMENT_DISCREPANCY)
        order = read_order(ctx)
        assert_order_state(order, "DELIVERED", "AGREED")
        assert order["agreed_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The refused dispute must not clear the settled figure, got "
            f"{order['agreed_quantity_mt']}"
        )
        assert order["measurement_basis"] == "SUPPLIER_FIGURES", (
            "The refused dispute must not clear the basis, got "
            f"{order['measurement_basis']}"
        )
        note = issue_bdn(ctx, bdn_number="BDN-2026-0100", sample_seal_number="SEAL-0100")
        assert note["delivered_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            f"The note fixes the settled figure, got {note['delivered_quantity_mt']}"
        )

        after_the_note = api_client.submit_quantity_decision(
            ctx["order"]["id"],
            quantity_decision_payload("DISPUTE"),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )

        validate_error(after_the_note, ApiErrorId.ERR_BDN_ALREADY_ISSUED)
        final = read_order(ctx)
        assert_order_state(final, "DELIVERED", "AGREED")
        assert final["measurement_basis"] == "SUPPLIER_FIGURES", (
            "Nothing in this test may move the settlement basis, got "
            f"{final['measurement_basis']}"
        )
