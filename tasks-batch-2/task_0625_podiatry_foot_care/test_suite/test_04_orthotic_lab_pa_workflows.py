"""Prior-authorization, orthotic-Rx, and lab-order workflows: the payer revision
loop, the receive->FULFILLED bubble, cross-entity state dependencies, the
category-mismatch priority conflict, compensation on cancel, and PA guarded
transitions.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    assert_orthotic_rx, assert_lab_order, assert_prior_authorization,
    ApiErrorId, TEST_USERS, make_podiatrist_headers,
    setup_practice_provider_patient, create_encounter,
    create_approved_pa, create_requested_pa, create_denied_pa,
    create_draft_rx, create_approved_rx, create_pending_pa_rx,
    create_lab_order, create_shipped_lab_order,
    setup_approved_rx_with_shipped_lab, setup_dme_pa_and_encounter, set_clock,
)
from test_helpers import create_lab_order_payload, create_dme_dispense_payload

ADMIN = TEST_USERS["practice_admin_headers"]
FRONTDESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PAYER = TEST_USERS["payer_agent_headers"]
PODIATRIST = TEST_USERS["podiatrist_headers"]


def _orthotic_setup(authorized_units=3):
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"], service_category="ORTHOTIC",
                            hcpcs_code="L3000", authorized_units=authorized_units)
    enc = create_encounter(patient["id"], provider["id"],
                           scheduled_start="2026-06-01T13:00:00Z",
                           scheduled_end="2026-06-01T13:30:00Z")
    return practice, provider, patient, pa, enc


# ─── non_linear_state_machine / orthotic_rx_payer_revision_loop ────────────
class TestOrthoticRxRevisionLoop:
    """DRAFT -> PENDING_PA -> DRAFT (REVISE) -> PENDING_PA again."""

    def test_revise_returns_to_draft(self, api):
        """PRD §3.7: "when the decision is to revise, the prescription cycles
        back `PENDING_PA → DRAFT`, where it may be edited and resubmitted."

        Design: Difficulty/non_linear_state_machine/orthotic_rx_payer_revision_loop
        """
        practice, provider, patient, pa, enc = _orthotic_setup()
        rx = create_pending_pa_rx(enc["id"], provider["id"], pa["id"], foot_side="RIGHT")
        revised = validate_success(
            api.orthotic_rx_payer_decision(rx["id"], {"decision": "REVISE"}, PAYER), 200)
        assert_orthotic_rx(revised)
        assert revised["status"] == "DRAFT"

    def test_resubmit_after_revise_returns_to_pending_pa(self, api):
        """PRD §3.7: "The podiatrist submits the draft to the payer, advancing
        `DRAFT → PENDING_PA`"

        Design: Difficulty/non_linear_state_machine/orthotic_rx_payer_revision_loop
        """
        practice, provider, patient, pa, enc = _orthotic_setup()
        rx = create_pending_pa_rx(enc["id"], provider["id"], pa["id"], foot_side="RIGHT")
        get_success_data(api.orthotic_rx_payer_decision(rx["id"], {"decision": "REVISE"}, PAYER))
        resubmitted = validate_success(
            api.submit_orthotic_rx_to_payer(rx["id"], PODIATRIST), 200)
        assert resubmitted["status"] == "PENDING_PA"


# ─── transitive_cascade / lab_receive_bubbles_rx_to_fulfilled ──────────────
class TestLabReceiveBubblesRxFulfilled:
    """Receiving the LabOrder bubbles the parent OrthoticRx to FULFILLED."""

    def test_receive_sets_lab_received(self, api):
        """PRD §3.7: "a `FrontDesk` operator receives it, advancing
        `SHIPPED → RECEIVED`."

        Design: Difficulty/transitive_cascade/lab_receive_bubbles_rx_to_fulfilled
        """
        practice, provider, patient, pa, enc, rx, lab = setup_approved_rx_with_shipped_lab()
        received = validate_success(api.receive_lab_order(lab["id"], FRONTDESK), 200)
        assert_lab_order(received)
        assert received["status"] == "RECEIVED"

    def test_receive_bubbles_rx_to_fulfilled(self, api):
        """PRD §3.7: "Receiving cascades up: the parent `OrthoticRx` is bubbled
        to `FULFILLED`, which is terminal."

        Design: Difficulty/transitive_cascade/lab_receive_bubbles_rx_to_fulfilled
        """
        practice, provider, patient, pa, enc, rx, lab = setup_approved_rx_with_shipped_lab()
        get_success_data(api.receive_lab_order(lab["id"], FRONTDESK))
        rx_after = get_success_data(api.get_orthotic_rx(rx["id"], FRONTDESK))
        assert rx_after["status"] == "FULFILLED"


# ─── priority_pair_validation_conflict / lab_order_category_mismatch_beats_units_exceeded ─
class TestLabOrderCategoryBeatsUnits:
    """A lab order against a DME-category PA requesting more units than remain
    fails the higher-priority category check, not the units check."""

    def test_category_mismatch_reported_over_units_exceeded(self, api):
        """PRD §2.11: "then the business-referential checks for authorization
        category match (`ERR_PA_CATEGORY_MISMATCH`) and drawable state
        (`ERR_PA_NOT_DRAWABLE`); then the temporal checks ...; and finally the
        unit-budget check (`ERR_PA_UNITS_EXCEEDED`)."
        PRD §3.7: "the category must be `ORTHOTIC` (else
        `ERR_PA_CATEGORY_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/lab_order_category_mismatch_beats_units_exceeded
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        # DME PA authorized only 1 unit, linked to an OrthoticRx (wrong category).
        dme_pa = create_approved_pa(patient["id"], service_category="DME",
                                    hcpcs_code="L4360", authorized_units=1)
        enc = create_encounter(patient["id"], provider["id"],
                               scheduled_start="2026-06-01T15:00:00Z",
                               scheduled_end="2026-06-01T15:30:00Z")
        rx = create_draft_rx(enc["id"], provider["id"], dme_pa["id"], foot_side="LEFT")
        # Lab order draws 5 units (exceeds remaining 1) AND PA is wrong category.
        res = api.create_lab_order(
            create_lab_order_payload(rx["id"], units_drawn=5), BILLING)
        validate_error(res, ApiErrorId.ERR_PA_CATEGORY_MISMATCH.value)

    def test_category_mismatch_conflict_is_409(self, api):
        """PRD §3.7: "the category must be `ORTHOTIC` (else
        `ERR_PA_CATEGORY_MISMATCH`)"
        PRD §5: error code catalogue maps `ERR_PA_CATEGORY_MISMATCH` to
        "409 Conflict".

        Design: Difficulty/priority_pair_validation_conflict/lab_order_category_mismatch_beats_units_exceeded
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        dme_pa = create_approved_pa(patient["id"], service_category="DME",
                                    hcpcs_code="L4360", authorized_units=1)
        enc = create_encounter(patient["id"], provider["id"],
                               scheduled_start="2026-06-01T15:00:00Z",
                               scheduled_end="2026-06-01T15:30:00Z")
        rx = create_draft_rx(enc["id"], provider["id"], dme_pa["id"], foot_side="LEFT")
        res = api.create_lab_order(
            create_lab_order_payload(rx["id"], units_drawn=5), BILLING)
        assert res.status_code == 409, (
            f"referential-vs-constraint conflict must surface 409 "
            f"(ERR_PA_CATEGORY_MISMATCH), got {res.status_code}")


# ─── cross_entity_state_dependency / rx_payer_approve_requires_pa_approved ─
class TestRxApproveRequiresPaApproved:
    """OrthoticRx PENDING_PA -> APPROVED blocked unless linked PA is APPROVED."""

    def test_approve_blocked_when_pa_only_requested(self, api):
        """PRD §3.7: "when the decision is to approve, the prescription advances
        `PENDING_PA → APPROVED`, which additionally requires the linked
        authorization to be in `APPROVED` (else `ERR_PA_NOT_DRAWABLE`)"

        Design: Difficulty/cross_entity_state_dependency/rx_payer_approve_requires_pa_approved
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        # ORTHOTIC PA left in REQUESTED (not approved).
        pa = create_requested_pa(patient["id"], service_category="ORTHOTIC",
                                 hcpcs_code="L3000", authorized_units=2)
        enc = create_encounter(patient["id"], provider["id"],
                               scheduled_start="2026-06-01T18:00:00Z",
                               scheduled_end="2026-06-01T18:30:00Z")
        rx = create_pending_pa_rx(enc["id"], provider["id"], pa["id"], foot_side="LEFT")
        res = api.orthotic_rx_payer_decision(rx["id"], {"decision": "APPROVE"}, PAYER)
        validate_error(res, ApiErrorId.ERR_PA_NOT_DRAWABLE.value)

    def test_rx_approve_succeeds_when_pa_is_approved(self, api):
        """PRD §3.7: "when the decision is to approve, the prescription advances
        `PENDING_PA → APPROVED`, which additionally requires the linked
        authorization to be in `APPROVED` (else `ERR_PA_NOT_DRAWABLE`)"

        Design: Difficulty/cross_entity_state_dependency/rx_payer_approve_requires_pa_approved
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        # Same flow but the PA is APPROVED, so the approve must succeed.
        pa = create_approved_pa(patient["id"], service_category="ORTHOTIC",
                                hcpcs_code="L3000", authorized_units=2)
        enc = create_encounter(patient["id"], provider["id"],
                               scheduled_start="2026-06-01T18:00:00Z",
                               scheduled_end="2026-06-01T18:30:00Z")
        rx = create_pending_pa_rx(enc["id"], provider["id"], pa["id"], foot_side="LEFT")
        approved = validate_success(
            api.orthotic_rx_payer_decision(rx["id"], {"decision": "APPROVE"}, PAYER), 200)
        assert approved["status"] == "APPROVED"


# ─── cross_entity_state_dependency / rx_cancel_blocked_by_shipped_lab_order ─
class TestRxCancelBlockedByShippedLab:
    """OrthoticRx APPROVED -> CANCELLED blocked while a child LabOrder is SHIPPED."""

    def test_cancel_blocked_by_shipped_lab(self, api):
        """PRD §3.7: "A `Podiatrist` may cancel an `APPROVED` prescription,
        advancing `APPROVED → CANCELLED` (terminal), but only when no lab order
        for that prescription is in `SHIPPED` or `RECEIVED`; a cancel attempt
        that is blocked by such a lab order, or that targets a prescription not
        in `APPROVED`, is rejected with `ERR_RX_BAD_STATE`."

        Design: Difficulty/cross_entity_state_dependency/rx_cancel_blocked_by_shipped_lab_order
        """
        practice, provider, patient, pa, enc, rx, lab = setup_approved_rx_with_shipped_lab()
        res = api.cancel_orthotic_rx(rx["id"], make_podiatrist_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_RX_BAD_STATE.value)

    def test_cancel_approved_rx_without_shipped_lab_succeeds(self, api):
        """PRD §3.7: "A `Podiatrist` may cancel an `APPROVED` prescription,
        advancing `APPROVED → CANCELLED` (terminal), but only when no lab order
        for that prescription is in `SHIPPED` or `RECEIVED`"

        Design: Difficulty/cross_entity_state_dependency/rx_cancel_blocked_by_shipped_lab_order
        """
        practice, provider, patient, pa, enc = _orthotic_setup()
        # APPROVED Rx with NO lab order at all -> cancel must succeed.
        rx = create_approved_rx(enc["id"], provider["id"], pa["id"])
        cancelled = validate_success(
            api.cancel_orthotic_rx(rx["id"], make_podiatrist_headers(provider["id"])), 200)
        assert cancelled["status"] == "CANCELLED"


# ─── state_machines / pa_approve_twice_idempotency_second_rejected ─────────
def test_approve_already_approved_pa_rejected(api):
    """PRD §3.6: "Approving or denying an authorization that is not in
    `REQUESTED` is rejected with `ERR_PA_BAD_STATE`."

    Design: Corner/state_machines/pa_approve_twice_idempotency_second_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"], service_category="DME",
                            hcpcs_code="L4360", authorized_units=2)
    res = api.approve_prior_authorization(pa["id"], PAYER)
    validate_error(res, ApiErrorId.ERR_PA_BAD_STATE.value)


# ─── state_machines / pa_deny_then_dme_dispense_not_drawable ───────────────
def test_dispense_against_denied_pa_not_drawable(api):
    """PRD §3.6: "an attempt to draw against an authorization that is not
    `APPROVED` — whether `REQUESTED`, `DENIED`, or already `EXHAUSTED` — is
    rejected with `ERR_PA_NOT_DRAWABLE`."

    Design: Corner/state_machines/pa_deny_then_dme_dispense_not_drawable
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    pa = create_denied_pa(patient["id"], service_category="DME",
                          hcpcs_code="L4360", authorized_units=2)
    enc = create_encounter(patient["id"], provider["id"])
    res = api.create_dme_dispense(
        create_dme_dispense_payload(pa["id"], enc["id"], pa["version"],
                                    hcpcs_code="L4360", acquisition_mode="PURCHASE",
                                    units=1, purchase_price_cents=15000),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_PA_NOT_DRAWABLE.value)


# ─── state_machines / pa_expired_draw_auto_expires_and_rejects ─────────────
def test_dispense_past_valid_through_auto_expires(api):
    """PRD §3.6: "Expiry is evaluated at draw time against the logical clock:
    when the current logical date is past the `valid_through_date`, the
    authorization automatically transitions `APPROVED → EXPIRED` (terminal) and
    the attempted draw is rejected with `ERR_PA_EXPIRED`."

    Design: Corner/state_machines/pa_expired_draw_auto_expires_and_rejects
    """
    set_clock("2026-06-01T08:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"], service_category="DME", hcpcs_code="L4360",
                            authorized_units=2, valid_from_date="2026-01-01",
                            valid_through_date="2026-06-30")
    enc = create_encounter(patient["id"], provider["id"])
    set_clock("2026-07-01T08:00:00Z")
    res = api.create_dme_dispense(
        create_dme_dispense_payload(pa["id"], enc["id"], pa["version"],
                                    hcpcs_code="L4360", acquisition_mode="PURCHASE",
                                    units=1, purchase_price_cents=15000),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_PA_EXPIRED.value)


# ─── state_machines / orthotic_submit_with_dme_pa_category_mismatch ────────
def test_submit_rx_with_dme_pa_category_mismatch(api):
    """PRD §3.7: "this requires the prescription to be in `DRAFT` (else
    `ERR_RX_BAD_STATE`) and the linked authorization's `service_category` to be
    `ORTHOTIC` (else `ERR_PA_CATEGORY_MISMATCH`)."

    Design: Corner/state_machines/orthotic_submit_with_dme_pa_category_mismatch
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    dme_pa = create_requested_pa(patient["id"], service_category="DME",
                                 hcpcs_code="L4360", authorized_units=2)
    enc = create_encounter(patient["id"], provider["id"])
    rx = create_draft_rx(enc["id"], provider["id"], dme_pa["id"], foot_side="LEFT")
    res = api.submit_orthotic_rx_to_payer(rx["id"], PODIATRIST)
    validate_error(res, ApiErrorId.ERR_PA_CATEGORY_MISMATCH.value)


# ─── state_machines / lab_order_receive_from_queued_invalid_not_shipped ────
def test_receive_queued_lab_order_rejected(api):
    """PRD §3.7: "Any ship, receive, or cancel attempted from an illegal state
    is rejected with `ERR_LAB_ORDER_BAD_STATE`."

    Design: Corner/state_machines/lab_order_receive_from_queued_invalid_not_shipped
    """
    practice, provider, patient, pa, enc = _orthotic_setup()
    rx = create_approved_rx(enc["id"], provider["id"], pa["id"])
    lab = create_lab_order(rx["id"])  # QUEUED, not shipped
    res = api.receive_lab_order(lab["id"], FRONTDESK)
    validate_error(res, ApiErrorId.ERR_LAB_ORDER_BAD_STATE.value)


# ─── state_machines / lab_order_cancel_compensates_pa_units ────────────────
def test_cancel_queued_lab_order_restores_pa_units(api):
    """PRD §3.7: "cancellation compensates the authorization by subtracting the
    lab order's `units_drawn` from `units_consumed`, recomputing
    `remaining_units`, and — if the authorization was `EXHAUSTED` and
    `remaining_units` becomes greater than 0 — reviving it to `APPROVED`."

    Design: Corner/state_machines/lab_order_cancel_compensates_pa_units
    """
    practice, provider, patient, pa, enc = _orthotic_setup(authorized_units=2)
    rx = create_approved_rx(enc["id"], provider["id"], pa["id"])
    lab = create_lab_order(rx["id"], units_drawn=2)  # draws PA to EXHAUSTED
    get_success_data(api.cancel_lab_order(lab["id"], BILLING))
    pa_after = get_success_data(api.get_prior_authorization(pa["id"], FRONTDESK))
    assert pa_after["remaining_units"] == 2
    assert pa_after["status"] == "APPROVED"


# ─── state_machines / dme_return_twice_second_rejected_bad_state ───────────
def test_return_already_returned_dme_rejected(api):
    """PRD §3.8: "A return from any state other than `DISPENSED` is rejected
    with `ERR_DME_BAD_STATE`."

    Design: Corner/state_machines/dme_return_twice_second_rejected_bad_state
    """
    practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
        pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                      "authorized_units": 2})
    disp = get_success_data(api.create_dme_dispense(
        create_dme_dispense_payload(pa["id"], enc["id"], pa["version"],
                                    hcpcs_code="L4360", acquisition_mode="PURCHASE",
                                    units=1, purchase_price_cents=15000),
        FRONTDESK))
    get_success_data(api.return_dme_dispense(disp["id"], FRONTDESK))
    res = api.return_dme_dispense(disp["id"], FRONTDESK)
    validate_error(res, ApiErrorId.ERR_DME_BAD_STATE.value)
