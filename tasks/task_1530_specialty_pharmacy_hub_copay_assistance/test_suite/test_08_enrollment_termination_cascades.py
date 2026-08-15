"""Cascade workflows: PA approval chains down to assistance activation and
shipment scheduling; discontinuation cancels pending shipments and releases
assistance with its undisbursed remainder."""
from test_helpers import (
    api_client,
    create_approved_with_card,
    deliver,
    get_enrollment,
    pa_decision_payload,
    request_shipment,
    set_clock,
    ship,
    setup_pa_pending_with_reserved_card_and_requested_shipment,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]
PR = TEST_USERS["payer_reviewer_headers"]


class TestPaApprovalCascade:

    def test_pa_approval_activates_reserved_assistance(self):
        """PRD section 3.3: "An `APPROVED` outcome moves the authorization
        `SUBMITTED` → `APPROVED` or `APPEALED` → `APPROVED` — `APPROVED` is
        terminal — and cascades the enrollment `PA_PENDING` → `APPROVED`
        with the full approval cascade: a `RESERVED` assistance activates,
        and `REQUESTED` shipments whose financial clearance is now open move
        to `SCHEDULED`."
        PRD section 3.4: "The record is born `RESERVED`, unless the
        enrollment already stands in `APPROVED` or `ACTIVE`, in which case
        it activates immediately."

        Design: Difficulty/transitive_cascade/pa_approval_cascade_activates_assistance_and_shipment
        """
        ctx = setup_pa_pending_with_reserved_card_and_requested_shipment(
            patient_ref="PAT-H")
        assert ctx["assistance"]["status"] == "RESERVED"

        pa = validate_success(api_client.record_pa_decision(
            ctx["pa"]["id"],
            pa_decision_payload("APPROVED", rationale="criteria met"),
            PR), expected_status=200)
        assert pa["status"] == "APPROVED"

        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["status"] == "APPROVED"

        data, _ = validate_paginated(api_client.list_copay_assistances(
            ctx["enrollment"]["id"], FC))
        assert data[0]["status"] == "ACTIVE", \
            "the enrollment transition activates the reservation"

    def test_pa_approval_schedules_waiting_shipment(self):
        """PRD section 3.3: "An `APPROVED` outcome moves the authorization
        `SUBMITTED` → `APPROVED` or `APPEALED` → `APPROVED` — `APPROVED` is
        terminal — and cascades the enrollment `PA_PENDING` → `APPROVED`
        with the full approval cascade: a `RESERVED` assistance activates,
        and `REQUESTED` shipments whose financial clearance is now open move
        to `SCHEDULED`."
        PRD section 3.6: "Whenever the enrollment reaches approval or an
        assistance activates, the system re-evaluates waiting shipments: a
        `REQUESTED` shipment on an `APPROVED` or `ACTIVE` enrollment with no
        `RESERVED` assistance moves to `SCHEDULED`."

        Design: Difficulty/transitive_cascade/pa_approval_cascade_activates_assistance_and_shipment
        """
        ctx = setup_pa_pending_with_reserved_card_and_requested_shipment(
            patient_ref="PAT-H2")
        assert ctx["fill"]["status"] == "REQUESTED"

        validate_success(api_client.record_pa_decision(
            ctx["pa"]["id"],
            pa_decision_payload("APPROVED", rationale="criteria met"),
            PR), expected_status=200)

        data, _ = validate_paginated(api_client.list_shipments(
            ctx["enrollment"]["id"], CM))
        assert data[0]["id"] == ctx["fill"]["id"]
        assert data[0]["status"] == "SCHEDULED", \
            "financial clearance opened by the cascade schedules the fill"


class TestDiscontinueCascade:

    def test_enrollment_discontinue_cascades_to_children(self):
        """PRD section 3.2: "Discontinuation lands the enrollment in
        `DISCONTINUED` and cascades: every non-terminal assistance is
        released with its undisbursed funds returned to the funding source,
        and every shipment still `REQUESTED` or `SCHEDULED` is cancelled."
        PRD section 3.4: "Release computes `returned_cents` as the
        `annual_benefit_cap_cents` minus the cumulative `disbursed_cents` —
        for an `EXHAUSTED` record this equals the full cap, since
        disbursement has reached the cap — and, for a `FOUNDATION` grant,
        credits that amount back to the pool's `remaining_balance_cents`."

        Design: Corner/state_machines/enrollment_discontinue_cascades_to_children
        """
        ctx = create_approved_with_card(patient_ref="PAT-S5")
        enr_id = ctx["enrollment"]["id"]

        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-01")
        ship(fill_1["id"])
        deliver(fill_1["id"], "2026-08-01")

        set_clock("2026-08-21T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-22")
        assert fill_2["status"] == "SCHEDULED"

        enr = validate_success(api_client.discontinue_enrollment(
            enr_id, {"reason": "therapy stopped"}, CM), expected_status=200)
        assert enr["status"] == "DISCONTINUED"

        fills, _ = validate_paginated(api_client.list_shipments(enr_id, CM))
        by_id = {f["id"]: f for f in fills}
        assert by_id[fill_2["id"]]["status"] == "CANCELLED", \
            "the SCHEDULED refill is cancelled by the cascade"
        assert by_id[fill_1["id"]]["status"] == "DELIVERED", \
            "the cascade hits non-terminal children only"

        cards, _ = validate_paginated(
            api_client.list_copay_assistances(enr_id, FC))
        assert cards[0]["status"] == "RELEASED"
        assert cards[0]["returned_cents"] == 85_000, \
            "100000 cap minus 15000 disbursed returns to the funding source"
