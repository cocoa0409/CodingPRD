"""Cross-entity state gates: accept-transfer requires target ACTIVE shift;
shift close requires ACCEPTED handoff; priority pair temporal over fiscal.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_handoff_for,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestAcceptTransferRequiresTargetActiveShift:
    """Difficulty instance: accept_transfer_requires_target_active_shift."""

    def _setup(self, api):
        """H_T with shift SCHEDULED (never activated); H_S ACTIVE shift holds
        P1 (ASG PENDING_TRANSFER -> H_T)."""
        h_t = create_hospitalist("H T", "INTERNAL_MEDICINE", max_census_cap=16)
        h_s = create_hospitalist("H S", "ICU", max_census_cap=16)
        # H_T's shift exists but is never activated
        s_t = create_shift(h_t["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=False)
        s_s = create_shift(h_s["id"], "DAY", "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="M941", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        # H_T not eligible (no ACTIVE shift), so offered to H_S
        acc = get_success_data(api.accept_admission(
            a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])
        ))
        asg_id = acc["assignment_id"]
        asg_v = get_success_data(api.get_assignment(asg_id, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h_t["id"], "expected_assignment_version": asg_v},
            make_hospitalist_headers(h_s["id"]),
        ))
        return h_t, h_s, p1, asg_id

    def test_accept_transfer_without_active_shift_rejected(self, api):
        """PRD §3.4: "then — at the temporal tier — a covering `ACTIVE` shift
        for the target, else `ERR_NO_ACTIVE_SHIFT`".

        Design: Difficulty/cross_entity_state_dependency/accept_transfer_requires_target_active_shift
        """
        h_t, h_s, p1, asg_id = self._setup(api)
        resp = api.accept_transfer(asg_id, make_hospitalist_headers(h_t["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SHIFT)

    def test_rejected_accept_leaves_assignment_pending_and_census_unmoved(self, api):
        """PRD §3.4: "Accepting requires the assignment to be
        `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`), then — at
        the temporal tier — a covering `ACTIVE` shift for the target, else
        `ERR_NO_ACTIVE_SHIFT`".

        Design: Difficulty/cross_entity_state_dependency/accept_transfer_requires_target_active_shift
        """
        h_t, h_s, p1, asg_id = self._setup(api)
        api.accept_transfer(asg_id, make_hospitalist_headers(h_t["id"]))
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "PENDING_TRANSFER"
        h_t_now = get_success_data(api.get_hospitalist(h_t["id"], ADMIN))
        assert h_t_now["current_census"] == 0


class TestShiftCloseRequiresAcceptedHandoff:
    """Difficulty instance: shift_close_requires_accepted_handoff."""

    def _setup(self, api):
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="M951", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        hf = create_handoff_for(s1["id"], h1["id"], h2["id"], [p1["id"]])
        return h1, h2, s1, p1, hf

    def test_close_with_draft_or_submitted_handoff_rejected(self, api):
        """PRD §3.1: "Closing moves `ACTIVE` → `CLOSED`, the terminal state,
        under the same actors — but only once an `ACCEPTED` handoff exists
        for that shift; without one the close is refused with
        `ERR_SHIFT_HANDOFF_MISSING` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/shift_close_requires_accepted_handoff
        """
        h1, h2, s1, p1, hf = self._setup(api)
        # DRAFT handoff — close fails
        resp1 = api.close_shift(s1["id"], ADMIN)
        validate_error(resp1, ApiErrorId.ERR_SHIFT_HANDOFF_MISSING)
        # SUBMITTED handoff — close still fails
        get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        resp2 = api.close_shift(s1["id"], ADMIN)
        validate_error(resp2, ApiErrorId.ERR_SHIFT_HANDOFF_MISSING)

    def test_close_after_accepted_handoff_succeeds(self, api):
        """PRD §3.6: "Acceptance moves `SUBMITTED` → `ACCEPTED`, terminal,
        stamping `reviewed_at` and incrementing `version`; it also makes the
        outgoing shift closable, satisfying the shift-close precondition of
        §3.1."
        PRD §3.1: "Closing moves `ACTIVE` → `CLOSED`, the terminal state".

        Design: Difficulty/cross_entity_state_dependency/shift_close_requires_accepted_handoff
        """
        h1, h2, s1, p1, hf = self._setup(api)
        get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        get_success_data(api.accept_handoff(hf["id"], make_hospitalist_headers(h2["id"])))
        resp = api.close_shift(s1["id"], ADMIN)
        closed = validate_success(resp)
        assert closed["state"] == "CLOSED"


class TestAcceptTransferNoShiftAndCapFull:
    """Difficulty instance: accept_transfer_no_shift_and_cap_full."""

    def _setup(self, api):
        """H_T cap 1 with census 1 and its shift CLOSED via accepted handoff;
        H_S ACTIVE shift holds P2 (ASG2 PENDING_TRANSFER -> H_T).
        Both ERR_NO_ACTIVE_SHIFT and ERR_CENSUS_CAP_REACHED apply."""
        h_t = create_hospitalist("H T", "INTERNAL_MEDICINE", max_census_cap=1)
        h_s = create_hospitalist("H S", "ICU", max_census_cap=16)
        h_r = create_hospitalist("H R", "FAMILY_MEDICINE", max_census_cap=16)
        s_t = create_shift(h_t["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        s_s = create_shift(h_s["id"], "DAY", "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        # P1 -> H_T (earlier shift start wins tie)
        p1 = create_patient(mrn="M911", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h_t["id"]
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h_t["id"])))
        # H_T census 1 == cap 1. Hand off and close H_T's shift.
        hf = create_handoff_for(s_t["id"], h_t["id"], h_r["id"], [p1["id"]])
        get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h_t["id"])))
        get_success_data(api.accept_handoff(hf["id"], make_hospitalist_headers(h_r["id"])))
        get_success_data(api.close_shift(s_t["id"], ADMIN))
        # H_T now has no ACTIVE shift.
        # P2 -> H_S (H_T ineligible at cap)
        p2 = create_patient(mrn="M912", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:15:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        assert a2["offered_to_hospitalist_id"] == h_s["id"]
        acc2 = get_success_data(api.accept_admission(a2["id"], make_hospitalist_headers(h_s["id"])))
        asg2 = acc2["assignment_id"]
        asg2_v = get_success_data(api.get_assignment(asg2, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg2,
            {"target_hospitalist_id": h_t["id"], "expected_assignment_version": asg2_v},
            make_hospitalist_headers(h_s["id"]),
        ))
        return h_t, h_s, asg2

    def test_temporal_error_masks_fiscal_error(self, api):
        """PRD §2.7: "Every request passes through a nine-tier validation
        pipeline, and the tiers run in a fixed relative order — an earlier
        tier's failure masks later tiers, so callers always see the earliest
        applicable rejection."
        PRD §2.7 item 7 (temporal): "acceptance paths require a covering
        active shift — `ERR_NO_ACTIVE_SHIFT` (HTTP 422)".
        PRD §2.7 item 9 (capacity): "`ERR_CENSUS_CAP_REACHED` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/accept_transfer_no_shift_and_cap_full
        """
        h_t, h_s, asg2 = self._setup(api)
        resp = api.accept_transfer(asg2, make_hospitalist_headers(h_t["id"]))
        # Tier 7 (temporal) fires before tier 9 (fiscal)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SHIFT)

    def test_rejected_accept_leaves_state_untouched(self, api):
        """PRD §3.4: "Accepting requires the assignment to be
        `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`), then — at
        the temporal tier — a covering `ACTIVE` shift for the target, else
        `ERR_NO_ACTIVE_SHIFT`; ... and finally capacity, with the target's
        `current_census` strictly below their cap, equality rejecting as
        `ERR_CENSUS_CAP_REACHED`."

        Design: Difficulty/priority_pair_validation_conflict/accept_transfer_no_shift_and_cap_full
        """
        h_t, h_s, asg2 = self._setup(api)
        api.accept_transfer(asg2, make_hospitalist_headers(h_t["id"]))
        asg_now = get_success_data(api.get_assignment(asg2, ADMIN))
        assert asg_now["status"] == "PENDING_TRANSFER"
        h_t_now = get_success_data(api.get_hospitalist(h_t["id"], ADMIN))
        assert h_t_now["current_census"] == 1  # unchanged
