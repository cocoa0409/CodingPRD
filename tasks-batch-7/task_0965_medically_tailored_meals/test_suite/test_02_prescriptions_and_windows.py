"""Diet prescription authoring, supersession, and window rules (PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_active_member, create_accepted_referral, create_draft_prescription,
    activate_prescription, create_menu_item, create_planned_cycle,
)


def _member_with_active_prescription(effective_to="2026-06-30", name="S Eight",
                                     payer_member_id="W-S8"):
    member = create_active_member(full_name=name, payer_member_id=payer_member_id)
    referral = create_accepted_referral(member["id"])
    prescription = create_draft_prescription(
        member["id"], referral["id"], effective_to=effective_to)
    prescription = activate_prescription(prescription["id"], member["id"])
    return member, referral, prescription


class TestSupersedeRepin:
    def test_supersede_repins_planned_cycle(self, api, dietitian_headers):
        """PRD §3.3: "the member's prior `ACTIVE` prescription, if one exists,
        moves to `SUPERSEDED`, and the newly activated prescription's
        `supersedes_id` is set to that prior prescription's id (or remains null
        when there was none); and every menu cycle of the member still in
        `PLANNED` that was pinned to the superseded prescription is re-pinned to
        the newly `ACTIVE` prescription with its `compliance_status` reset to
        `UNCHECKED`."
        PRD §3.2: "when a diet prescription referencing an `ACCEPTED` referral
        is activated, the referral flips automatically to `CONSUMED`".

        Design: Corner/state_machines/supersede_repins_planned_cycle
        """
        member, referral1, p1 = _member_with_active_prescription()
        item = create_menu_item("rice_bowl")
        planned = create_planned_cycle(member["id"], p1["id"], "2026-05-04",
                                       [(item["id"], 5)])
        cycle = planned["cycle"]
        assert cycle["prescription_id"] == p1["id"]

        referral2 = create_accepted_referral(member["id"],
                                             diagnosis_codes=["N18.4"],
                                             expires_at="2026-12-31")
        p2 = create_draft_prescription(member["id"], referral2["id"],
                                       daily_sodium_mg_max=1800,
                                       effective_from="2026-07-01",
                                       effective_to="2026-12-31")
        p2 = activate_prescription(p2["id"], member["id"])

        assert p2["status"] == "ACTIVE"
        assert p2["supersedes_id"] == p1["id"], \
            "the new prescription must record the superseded predecessor"
        p1_after = validate_success(api.get_prescription(p1["id"], dietitian_headers))
        assert p1_after["status"] == "SUPERSEDED"
        cycle_after = validate_success(api.get_menu_cycle(cycle["id"], dietitian_headers))
        assert cycle_after["prescription_id"] == p2["id"], \
            "PLANNED cycle must re-pin to the newly ACTIVE prescription"
        assert cycle_after["compliance_status"] == "UNCHECKED"
        referral2_after = validate_success(
            api.get_referral(referral2["id"], dietitian_headers))
        assert referral2_after["status"] == "CONSUMED"


class TestPrescriptionWindowOverlap:
    def test_shared_boundary_date_is_overlap(self, api, dietitian_headers):
        """PRD §3.3: "Two prescriptions of the same member that are both in
        `DRAFT` or `ACTIVE` may not have overlapping effective windows under
        closed-interval semantics — a shared boundary date already counts as an
        overlap — and a colliding draft is rejected with
        `ERR_PRESCRIPTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/prescription_window_closed_interval_overlap
        """
        member, _r1, _p1 = _member_with_active_prescription(name="M Fifteen",
                                                            payer_member_id="W-510")
        referral2 = create_accepted_referral(member["id"],
                                             diagnosis_codes=["N18.4"],
                                             expires_at="2026-12-31")
        resp = api.create_prescription(
            _prescription_payload(member["id"], referral2["id"],
                                  effective_from="2026-06-30",
                                  effective_to="2026-12-31"),
            dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_WINDOW_OVERLAP)

    def test_disjoint_window_accepted(self, api, dietitian_headers):
        """PRD §3.3: "Two prescriptions of the same member that are both in
        `DRAFT` or `ACTIVE` may not have overlapping effective windows under
        closed-interval semantics — a shared boundary date already counts as an
        overlap — and a colliding draft is rejected with
        `ERR_PRESCRIPTION_WINDOW_OVERLAP`."
        PRD §3.3: "A new prescription starts in `DRAFT` status."

        Design: Difficulty/resource_temporal_overlap/prescription_window_closed_interval_overlap
        """
        member, _r1, _p1 = _member_with_active_prescription(name="M Fifteen",
                                                            payer_member_id="W-510")
        referral2 = create_accepted_referral(member["id"],
                                             diagnosis_codes=["N18.4"],
                                             expires_at="2026-12-31")
        resp = api.create_prescription(
            _prescription_payload(member["id"], referral2["id"],
                                  effective_from="2026-07-01",
                                  effective_to="2026-12-31"),
            dietitian_headers)
        p2 = validate_success(resp, 201)
        assert p2["status"] == "DRAFT", \
            "a window starting the day after the existing window ends is disjoint"


def _prescription_payload(member_id, referral_id, **overrides):
    from test_helpers import create_prescription_payload
    return create_prescription_payload(member_id, referral_id,
                                       daily_sodium_mg_max=1800, **overrides)
