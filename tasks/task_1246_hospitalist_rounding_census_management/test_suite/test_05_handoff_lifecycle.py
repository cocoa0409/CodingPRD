"""Handoff lifecycle: return/resubmit cycle, OCC on revision, initial state,
incomplete-submit rejection, self-accept rejection, double-submit rejection.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    create_handoff_for,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _handoff_scenario(api, mrn="M601"):
    """H1 ACTIVE shift holds P1; H2 receiver; handoff DRAFT with [P1]."""
    h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
    h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
    s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
    set_clock("2026-05-01T09:00:00Z")
    p1 = create_patient(mrn=mrn, acuity="LOW", admit_source="DIRECT",
                        stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
    a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
    get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])))
    hf = create_handoff_for(s1["id"], h1["id"], h2["id"], [p1["id"]])
    return h1, h2, s1, p1, hf


class TestHandoffReturnResubmitCycle:
    """Difficulty instance: handoff_return_resubmit_cycle."""

    def test_return_then_resubmit_then_accept(self, api):
        """PRD §3.6: "Submission moves `DRAFT` → `SUBMITTED` — or, on a later
        cycle, `RETURNED` → `SUBMITTED` — and is gated on coverage".
        PRD §3.6: "Returning instead moves `SUBMITTED` → `RETURNED` under the
        same receiver checks and the same state gate ... storing the required
        `return_reason` on the handoff and incrementing `version`, after which
        the author revises and resubmits, and the cycle repeats."
        PRD §3.6: "Acceptance moves `SUBMITTED` → `ACCEPTED`, terminal,
        stamping `reviewed_at` and incrementing `version`".

        Design: Difficulty/non_linear_state_machine/handoff_return_resubmit_cycle
        """
        h1, h2, s1, p1, hf = _handoff_scenario(api)
        # submit
        s1_resp = get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        assert s1_resp["status"] == "SUBMITTED"
        # return
        r_resp = get_success_data(api.return_handoff(
            hf["id"], {"return_reason": "missing course context"},
            make_hospitalist_headers(h2["id"]),
        ))
        assert r_resp["status"] == "RETURNED"
        assert r_resp["return_reason"] == "missing course context"
        # resubmit
        s2_resp = get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        assert s2_resp["status"] == "SUBMITTED"
        # accept
        a_resp = get_success_data(api.accept_handoff(hf["id"], make_hospitalist_headers(h2["id"])))
        assert a_resp["status"] == "ACCEPTED"
        assert a_resp["reviewed_at"] is not None
        # version: 1 (create) + 1 (submit) + 1 (return) + 1 (submit) + 1 (accept) = 5
        assert a_resp["version"] == 5

    def test_completeness_fields_recomputed_on_each_submit(self, api):
        """PRD §3.6: "Submitting recomputes all four completeness fields at
        that instant, stamps `submitted_at` with the latest submission, and
        increments `version`."

        Design: Difficulty/non_linear_state_machine/handoff_return_resubmit_cycle
        """
        h1, h2, s1, p1, hf = _handoff_scenario(api)
        s1_resp = get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        assert s1_resp["open_item_count"] == 0
        assert s1_resp["completeness_score"] == pytest.approx(1.0, abs=0.0001)
        api.return_handoff(hf["id"], {"return_reason": "missing context"},
                           make_hospitalist_headers(h2["id"]))
        s2_resp = get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        assert s2_resp["open_item_count"] == 0
        assert s2_resp["completeness_score"] == pytest.approx(1.0, abs=0.0001)
        assert s2_resp["return_reason"] == "missing context"


class TestOccHandoffReviseStale:
    """Corner instance: occ_handoff_revise_stale_returns_412."""

    def test_sequential_revisions_stale_version_rejected(self, api):
        """PRD §2.6: "Revising a handoff requires the request to carry
        `expected_handoff_version` holding the handoff's `version` as the
        client last observed it ... a value that no longer matches the
        entity's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §2.6: "A handoff may remain legitimately in `DRAFT` or `RETURNED`
        while another revision — or a submit-then-return cycle — has advanced
        its version; a stale revision would silently discard the intervening
        change."

        Design: Corner/validations/occ_handoff_revise_stale_returns_412
        """
        h1, h2, s1, p1, hf = _handoff_scenario(api, mrn="V001")
        captured_v = hf["version"]
        assert captured_v == 1
        # First revision advances version
        r1 = get_success_data(api.revise_handoff(
            hf["id"],
            {"patient_ids": [p1["id"]], "expected_handoff_version": captured_v},
            make_hospitalist_headers(h1["id"]),
        ))
        assert r1["version"] == 2
        assert r1["status"] == "DRAFT"
        # Replay with stale version
        resp = api.revise_handoff(
            hf["id"],
            {"patient_ids": [p1["id"]], "expected_handoff_version": captured_v},
            make_hospitalist_headers(h1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Version unchanged after the rejected write
        hf_now = get_success_data(api.get_handoff(hf["id"], ADMIN))
        assert hf_now["version"] == 2


class TestHandoffInitialStateDraft:
    """Corner instance: handoff_initial_state_draft."""

    def test_new_handoff_draft_with_completeness(self, api):
        """PRD §3.6: "The draft is born `DRAFT` with its completeness fields
        computed".
        PRD §3.6: "`required_patient_count` is its size;
        `covered_patient_count` counts how many of those patients appear in
        `patient_ids`; `open_item_count` is the difference;
        `completeness_score` is the covered count divided by the required
        count, rounded half up to four decimals".

        Design: Corner/state_machines/handoff_initial_state_draft
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        h2 = create_hospitalist("H Two", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S008", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])))
        hf = create_handoff_for(s1["id"], h1["id"], h2["id"], [p1["id"]])
        assert hf["status"] == "DRAFT"
        assert hf["version"] == 1
        assert hf["required_patient_count"] == 1
        assert hf["covered_patient_count"] == 1
        assert hf["open_item_count"] == 0
        assert hf["completeness_score"] == pytest.approx(1.0, abs=0.0001)


class TestHandoffSubmitTwiceRejected:
    """Corner instance: handoff_submit_twice_rejected."""

    def test_submit_on_submitted_fails(self, api):
        """PRD §3.6: "A submission from a state other than `DRAFT` or
        `RETURNED` fails with `ERR_HANDOFF_INVALID_STATE`."

        Design: Corner/errors/handoff_submit_twice_rejected
        """
        h1, h2, s1, p1, hf = _handoff_scenario(api, mrn="X004")
        get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        resp = api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_HANDOFF_INVALID_STATE)
        hf_now = get_success_data(api.get_handoff(hf["id"], ADMIN))
        assert hf_now["status"] == "SUBMITTED"


class TestHandoffSubmitIncompleteRejected:
    """Corner instance: handoff_submit_incomplete_rejected."""

    def test_submit_with_open_items_rejected(self, api):
        """PRD §3.6: "`open_item_count` must be zero, meaning `patient_ids`
        cover every `ACTIVE` assignment of the shift's hospitalist, else
        `ERR_HANDOFF_INCOMPLETE` (HTTP 422)."

        Design: Corner/errors/handoff_submit_incomplete_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        h2 = create_hospitalist("H Two", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X005", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"])))
        p2 = create_patient(mrn="X006", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:05:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        get_success_data(api.accept_admission(a2["id"], make_hospitalist_headers(h1["id"])))
        # Handoff lists only P1; P2 uncovered
        hf = create_handoff_for(s1["id"], h1["id"], h2["id"], [p1["id"]])
        resp = api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_HANDOFF_INCOMPLETE)
        hf_now = get_success_data(api.get_handoff(hf["id"], ADMIN))
        assert hf_now["status"] == "DRAFT"
        assert hf_now["required_patient_count"] == 2
        assert hf_now["covered_patient_count"] == 1


class TestHandoffAcceptBySubmitterRejected:
    """Corner instance: handoff_accept_by_submitter_rejected."""

    def test_receiver_equals_submitter_fails_self_accept(self, api):
        """PRD §3.6: "at the safety tier, after the state check — forbids the
        shift's own owner from accepting their own signout,
        `ERR_HANDOFF_SELF_ACCEPT` (HTTP 409)."

        Design: Corner/state_machines/handoff_accept_by_submitter_rejected
        """
        # receiver == submitting hospitalist (self-signout)
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S005", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"])))
        # Handoff receiver = H1 (self)
        hf = create_handoff_for(s1["id"], h1["id"], h1["id"], [p1["id"]])
        get_success_data(api.submit_handoff(hf["id"], make_hospitalist_headers(h1["id"])))
        # Accept by H1 (passes receiver check, fails self-accept)
        resp = api.accept_handoff(hf["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_HANDOFF_SELF_ACCEPT)
        hf_now = get_success_data(api.get_handoff(hf["id"], ADMIN))
        assert hf_now["status"] == "SUBMITTED"
