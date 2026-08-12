"""Boundary precision: inclusive storage gate at the cap, and the inclusive
waste-ratio threshold crossing."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_active_home_patient, create_draft_order, get_patient,
    setup_active_patient_with_delivered_order, report_waste_return,
    verify_waste_return, list_reviews, submit_order,
    api_client, make_patient_headers, make_admin_headers,
)


class TestStorageCapacityExactFitThenOneOver:
    """The storage bound is inclusive: on_hand + total == cap submits."""

    def test_exact_fit_submits_and_one_over_rejected(self, api):
        """PRD §3.5: "The storage bound compares physical room: if
        `on_hand_units` plus `provisional_total_units` exceeds
        `storage_cap_units`, submission is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."
        PRD §3.3: "The first is `storage_cap_units`: four units per certified
        square foot, rounded down to a whole unit, and capped at 400 units."

        Design: Difficulty/boundary_precision_check/storage_capacity_exact_fit_then_one_over
        """
        # 25 sqft -> cap min(400, floor(25*4)) == 100.
        ctx = create_active_home_patient(tpw=7, upt=6, storage_area_sqft=25)
        pat = ctx["patient"]["id"]
        assert get_patient(pat)["storage_cap_units"] == 100
        may = create_draft_order(pat, "2026-05",
                                 [{"sku": "DIALYSATE_2L", "quantity": 100}])
        submitted = submit_order(may["id"], pat)
        assert submitted["order_status"] == "SUBMITTED", (
            "exactly 100 units against cap 100 fits (boundary inclusive)")
        june = create_draft_order(pat, "2026-06",
                                  [{"sku": "DIALYSATE_2L", "quantity": 101}])
        resp = api.submit_supply_order(june["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)

    def test_patched_back_to_cap_submits(self, api):
        """PRD §3.5: "A patient edits `lines` while the order is `DRAFT` or
        `CHANGES_REQUESTED` (from any other state, `ERR_ORDER_INVALID_STATE`);
        editing a `CHANGES_REQUESTED` order returns it to `DRAFT`, and every
        edit recomputes all money fields."
        PRD §3.5: "The storage bound compares physical room: if
        `on_hand_units` plus `provisional_total_units` exceeds
        `storage_cap_units`, submission is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/storage_capacity_exact_fit_then_one_over
        """
        ctx = create_active_home_patient(tpw=7, upt=6, storage_area_sqft=25)
        pat = ctx["patient"]["id"]
        june = create_draft_order(pat, "2026-06",
                                  [{"sku": "DIALYSATE_2L", "quantity": 101}])
        resp = api.submit_supply_order(june["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)
        edited = validate_success(api.patch_supply_order(
            june["id"], {"lines": [{"sku": "DIALYSATE_2L", "quantity": 100}]},
            make_patient_headers(pat)))
        assert edited["provisional_total_units"] == 100
        submitted = validate_success(api.submit_supply_order(
            june["id"], make_patient_headers(pat)))
        assert submitted["order_status"] == "SUBMITTED"


class TestWasteRatioExactlyAtThresholdEscalates:
    """1/20 = 0.05 stays quiet; the second unit lands exactly at 0.10 and the
    inclusive threshold fires."""

    def test_below_threshold_no_alert_no_review(self, api):
        """PRD §3.8: "When the ratio reaches the program's
        `waste_ratio_alert_threshold` — the comparison is inclusive — the
        patient's `waste_alert_active` latches true and, if no `PENDING` review
        exists for the patient, an `ESCALATION` ClinicalReview is created;
        posture recomputes, and the alert persists until the next review
        sign-off clears it (§3.6)."

        Design: Difficulty/boundary_precision_check/waste_ratio_exactly_at_threshold_escalates
        """
        ctx = setup_active_patient_with_delivered_order(order_qty=20,
                                                        delivered_qty=20)
        pat = ctx["patient"]["id"]
        waste = report_waste_return(
            pat, "WASTE", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 1, "expired": False}])
        verified = verify_waste_return(waste["id"], approved=True)
        assert verified["status"] == "VERIFIED"
        patient = get_patient(pat)
        assert patient["waste_alert_active"] is False, "0.05 < 0.1 stays quiet"
        assert list_reviews(pat) == [], "no review is opened below threshold"
        assert patient["on_hand_units"] == 19

    def test_exact_threshold_latches_alert_and_escalation(self, api):
        """PRD §3.8: "When the ratio reaches the program's
        `waste_ratio_alert_threshold` — the comparison is inclusive — the
        patient's `waste_alert_active` latches true and, if no `PENDING` review
        exists for the patient, an `ESCALATION` ClinicalReview is created;
        posture recomputes, and the alert persists until the next review
        sign-off clears it (§3.6)."
        PRD §2.10: "Failing that, the patient is `AT_RISK` when any of the
        following holds: no machine with status `ASSIGNED` is assigned to the
        patient; the assigned machine is `maintenance_due` or
        `UNDER_MAINTENANCE`; no EmergencyBackupPlan is `ACTIVE` (the plan is
        missing, `EXPIRED`, `SUPERSEDED`, or `CLOSED`); the `missed_log_streak`
        has reached the program's `max_missed_log_streak`; or
        `waste_alert_active` is true."

        Design: Difficulty/boundary_precision_check/waste_ratio_exactly_at_threshold_escalates
        """
        ctx = setup_active_patient_with_delivered_order(order_qty=20,
                                                        delivered_qty=20)
        pat = ctx["patient"]["id"]
        w1 = report_waste_return(
            pat, "WASTE", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 1, "expired": False}])
        verify_waste_return(w1["id"], approved=True)
        w2 = report_waste_return(
            pat, "WASTE", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 1, "expired": False}])
        verify_waste_return(w2["id"], approved=True)
        patient = get_patient(pat)
        assert patient["waste_alert_active"] is True, (
            "2/20 = 0.10 reaches the inclusive threshold")
        assert patient["posture"] == "AT_RISK"
        reviews = list_reviews(pat)
        assert len(reviews) == 1
        assert reviews[0]["due_reason"] == "ESCALATION"
        assert reviews[0]["status"] == "PENDING"
        assert patient["on_hand_units"] == 18
