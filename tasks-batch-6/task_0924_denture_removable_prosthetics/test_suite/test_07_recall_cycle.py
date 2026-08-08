"""The recall axis: lazy banding against the logical clock, the reschedule cycle,
and the two completing outcomes — all riding alongside the warranty axis."""

from test_helpers import (
    PROSTHODONTIST_USER_ID,
    assert_money,
    assert_same_instant,
    fixtures as fx,
    validate_success,
)


def _immediate_denture_delivered():
    return fx.setup_delivered_prosthesis(
        prosthesis_type="IMMEDIATE_DENTURE",
        arch_position="MANDIBULAR",
        capture_method="PHYSICAL_IMPRESSION",
        quality_score=87,
        patient_overrides={
            "full_name": "Hilde Ferreira", "date_of_birth": "1943-05-23", "phone": "555-0288"
        },
    )


def _flexible_partial_recalled_due(name, dob, phone, arch_position="MAXILLARY"):
    ctx = fx.setup_delivered_prosthesis(
        arch_position=arch_position,
        patient_overrides={"full_name": name, "date_of_birth": dob, "phone": phone},
    )
    fx.set_clock("2027-05-02T00:00:00Z")
    return ctx


class TestParallelAxes:
    def test_the_recall_band_advances_on_the_clock_while_the_warranty_axis_stands_still(self, api, prosthodontist_headers):
        """PRD §3.6: "A row moves `RECALL_SCHEDULED → RECALL_DUE` once the logical
        clock is **at or after** `recall_due_at` — the boundary instant itself counts
        as due."
        PRD §3.6: "Every instant strictly after `recall_due_at` plus 30 days is
        overdue on both readings, and every instant before it is merely due on both
        readings; only the single boundary instant is disputed."
        PRD §3.6: "Reading one prosthesis re-evaluates both clock-driven axes against
        the logical clock before the row is projected, so a caller who advances the
        clock and then reads sees the new bands."

        Design: Difficulty/non_linear_state_machine/prosthesis_warranty_and_recall_axes_advance_independently
        """
        ctx = _immediate_denture_delivered()
        prosthesis_id = ctx["prosthesis"]["id"]

        at_delivery = fx.read_prosthesis(prosthesis_id)
        assert_same_instant(
            at_delivery["recall_due_at"], "2026-07-30T00:00:00.000Z", "Prosthesis.recall_due_at"
        )
        assert_same_instant(
            at_delivery["warranty_expires_at"],
            "2027-05-01T00:00:00.000Z",
            "Prosthesis.warranty_expires_at",
        )
        assert_same_instant(
            at_delivery["mandatory_reline_due_at"],
            "2026-10-28T00:00:00.000Z",
            "Prosthesis.mandatory_reline_due_at",
        )

        fx.set_clock("2026-08-01T00:00:00Z")
        due = validate_success(api.get_prosthesis(prosthesis_id, prosthodontist_headers), 200)
        assert due["recall_status"] == "RECALL_DUE"
        assert due["warranty_status"] == "IN_WARRANTY"

        fx.set_clock("2026-08-30T00:00:00Z")
        overdue = validate_success(api.get_prosthesis(prosthesis_id, prosthodontist_headers), 200)
        assert overdue["recall_status"] == "RECALL_OVERDUE"
        assert overdue["warranty_status"] == "IN_WARRANTY"

    def test_a_clinic_fault_verdict_moves_the_warranty_axis_and_leaves_recall_where_it_was(self, api):
        """PRD §3.6: "Warranty and recall are two independent axes riding on the same
        prosthesis row; a movement on one never implies a movement on the other."
        PRD §3.6: "`IN_WARRANTY → WARRANTY_CONSUMED` happens when a warranty claim on
        this appliance reaches `CLINIC_FAULT` or `LAB_FAULT`, provided the appliance is
        currently `IN_WARRANTY` and the logical clock is at or before
        `warranty_expires_at`. It also sets that claim's `warranty_consumed` to true."
        PRD §3.7: "- **`CLINIC_FAULT`** sets `warranty_consumed` to true,
        `lab_credit_amount` to 0.00, and `patient_charge_amount` to 0.00, stamps
        `adjudicated_at`, and moves the referenced appliance `IN_WARRANTY →
        WARRANTY_CONSUMED`. The clinic absorbs the whole cost."

        Design: Difficulty/non_linear_state_machine/prosthesis_warranty_and_recall_axes_advance_independently
        """
        ctx = _immediate_denture_delivered()
        prosthesis_id = ctx["prosthesis"]["id"]
        claim = fx.open_warranty_claim(
            prosthesis_id, "Anterior flange fractured along the midline"
        )

        fx.set_clock("2026-08-30T00:00:00Z")
        assert fx.read_prosthesis(prosthesis_id)["recall_status"] == "RECALL_OVERDUE"

        adjudicated = fx.adjudicate_warranty_claim(claim["id"], "CLINIC_FAULT")

        prosthesis = fx.read_prosthesis(prosthesis_id)
        assert prosthesis["warranty_status"] == "WARRANTY_CONSUMED"
        assert prosthesis["recall_status"] == "RECALL_OVERDUE", (
            "a movement on the warranty axis never implies a movement on the recall axis"
        )
        assert adjudicated["warranty_consumed"] is True
        assert_money(
            adjudicated["patient_charge_amount"], 0.00, "WarrantyClaim.patient_charge_amount"
        )
        assert_money(adjudicated["lab_credit_amount"], 0.00, "WarrantyClaim.lab_credit_amount")


class TestRecallOutcomes:
    def test_no_action_reschedules_the_same_row_one_interval_further_out(self, api, prosthodontist_headers):
        """PRD §3.6: "- **`NO_ACTION`** — the appliance is fine. The row returns to
        `RECALL_SCHEDULED`, `recall_cycle_count` increases by one, and `recall_due_at`
        therefore advances by one further interval of the appliance type. This is the
        recall *cycle*: a clean recall reschedules the same row instead of terminating
        it, and a complete denture recalled cleanly twice is next due three years after
        delivery. The leg is declared from `RECALL_DUE` and from `RECALL_OVERDUE`."
        PRD §3.6: "More precisely, `recall_due_at` is `delivered_at` plus the appliance
        type's interval multiplied by one more than the appliance's
        `recall_cycle_count`, so the first cycle is one interval out, the second is two
        intervals out, and so on."
        PRD §3.6: "`IN_WARRANTY → WARRANTY_EXPIRED` and `WARRANTY_CONSUMED →
        WARRANTY_EXPIRED` are both evaluated lazily, on every read or handling of the
        row, and fire when the logical clock is strictly after `warranty_expires_at`."

        Design: Corner/state_machines/recall_no_action_reschedules_the_same_row_instead_of_terminating_it
        """
        ctx = _flexible_partial_recalled_due("Otto Villanueva", "1945-04-16", "555-1013")

        rescheduled = validate_success(
            api.recall_complete(
                ctx["prosthesis"]["id"], {"recall_outcome": "NO_ACTION"}, prosthodontist_headers
            ),
            200,
        )

        assert rescheduled["recall_status"] == "RECALL_SCHEDULED"
        assert rescheduled["recall_cycle_count"] == 1
        assert_same_instant(
            rescheduled["recall_due_at"], "2028-04-30T00:00:00.000Z", "Prosthesis.recall_due_at"
        )
        assert rescheduled["warranty_status"] == "WARRANTY_EXPIRED", (
            "the parallel warranty axis passed its own expiry independently"
        )

    def test_reline_indicated_terminates_the_recall_and_mints_a_hard_reline_service(self, api, prosthodontist_headers):
        """PRD §3.6: "- **`RELINE_INDICATED`** — the row moves to `RECALL_COMPLETED`
        and a post-delivery service of `service_type` `HARD_RELINE_LAB` is
        auto-created on this appliance in `REQUESTED`. Because it is minted by the
        system rather than requested by a caller, it carries no laboratory routing of
        its own and stays in `REQUESTED`."

        Design: Corner/state_machines/recall_reline_indicated_auto_creates_a_hard_reline_service
        """
        ctx = _flexible_partial_recalled_due(
            "Pia Lundgren", "1950-05-17", "555-1014", arch_position="MANDIBULAR"
        )

        completed = validate_success(
            api.recall_complete(
                ctx["prosthesis"]["id"],
                {"recall_outcome": "RELINE_INDICATED"},
                prosthodontist_headers,
            ),
            200,
        )

        assert completed["recall_status"] == "RECALL_COMPLETED"
        assert completed["recall_cycle_count"] == 0

        services = fx.services_of(ctx["prosthesis"]["id"])
        assert len(services) == 1
        assert services[0]["service_type"] == "HARD_RELINE_LAB"
        assert services[0]["service_status"] == "REQUESTED"

    def test_remake_evaluation_terminates_the_recall_and_mints_a_recall_reason_request(self, api, prosthodontist_headers):
        """PRD §3.6: "- **`REMAKE_EVALUATION`** — the row moves to `RECALL_COMPLETED`
        and a remake request is auto-created on the parent arch in `PENDING_APPROVAL`
        with `reason_code` of `RECALL_EVALUATION` and `requested_by_user_id` set to
        the calling `X-User-ID`."
        PRD §3.7: "The counter that the ceiling watches is `remake_request_count`, and
        it counts the arch's remake requests whose `authorization_status` is
        `PENDING_APPROVAL`, `APPROVED`, or `DENIED`."
        PRD §3.7: "Separately, the arch carries `remake_count`, which counts only the
        requests that were actually approved."

        Design: Corner/state_machines/recall_remake_evaluation_auto_creates_a_recall_reason_remake_request
        """
        ctx = _flexible_partial_recalled_due(
            "Nuria Escamilla", "1948-06-06", "555-1046", arch_position="MANDIBULAR"
        )

        completed = validate_success(
            api.recall_complete(
                ctx["prosthesis"]["id"],
                {"recall_outcome": "REMAKE_EVALUATION"},
                prosthodontist_headers,
            ),
            200,
        )
        assert completed["recall_status"] == "RECALL_COMPLETED"

        requests = fx.remake_requests_of(ctx["arch"]["id"])
        assert len(requests) == 1
        remake = requests[0]
        assert remake["reason_code"] == "RECALL_EVALUATION"
        assert remake["authorization_status"] == "PENDING_APPROVAL"
        assert remake["requested_by_user_id"] == PROSTHODONTIST_USER_ID
        assert remake["attempt_number"] == 1
        assert remake["charge_basis"] == "CHARGEABLE"

        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["remake_request_count"] == 1
        assert arch["remake_count"] == 0
        assert arch["arch_status"] == "DELIVERED", (
            "the arch only moves once the request is approved"
        )
        assert fx.services_of(ctx["prosthesis"]["id"]) == []
