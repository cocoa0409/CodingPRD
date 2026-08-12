"""Conservation invariant tests: accept-transfer conserves the group-wide
ACTIVE assignment total; census reconciliation through transfer/cancel cycle.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _count_active_assignments(api):
    """Group-wide ACTIVE assignment count via the list endpoint."""
    rows, meta = validate_paginated(api.list_assignments(ADMIN, params={"status": "ACTIVE", "limit": 100}))
    return meta["total_count"]


class TestTransferConservesTotalActiveAssignments:
    """Difficulty instance: transfer_conserves_total_active_assignments."""

    def _setup(self, api):
        """H1 ACTIVE shift 06-18 and H2 ACTIVE shift 07-19, both census 0.
        Per the PRD §3.3 selector, P1 ties at score 1.0 and breaks toward the
        earlier shift start (H1 06:00), so P1 lands on H1; P2 then scores H2
        1.0 above H1's 15/16, so P2 lands on H2. Census: H1 == 1, H2 == 1;
        group total ACTIVE == 2."""
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        s2 = create_shift(h2["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="M961", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        _, asg1 = admit_and_accept(p1["id"])
        p2 = create_patient(mrn="M962", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:10:00Z")
        _, asg2 = admit_and_accept(p2["id"])
        return h1, h2, p1, p2, asg1, asg2

    def test_total_active_conserved_across_transfer(self, api):
        """PRD §2.5: "a transfer acceptance conserves the group-wide total by
        closing exactly one `ACTIVE` assignment and creating exactly one in
        the same mutation".

        Design: Difficulty/compensating_invariant/transfer_conserves_total_active_assignments
        """
        h1, h2, p1, p2, asg1, asg2 = self._setup(api)
        assert _count_active_assignments(api) == 2
        asg1_v = get_success_data(api.get_assignment(asg1, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg1,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": asg1_v},
            make_hospitalist_headers(h1["id"]),
        ))
        get_success_data(api.accept_transfer(asg1, make_hospitalist_headers(h2["id"])))
        assert _count_active_assignments(api) == 2

    def test_accept_transfer_closes_source_creates_target_with_census_moves(self, api):
        """PRD §3.4: "the pending assignment closes with `close_reason`
        `TRANSFER` and `closed_at` stamped; the source hospitalist's
        `current_census` decrements and their `distribution_eligible`
        recomputes — dropping below cap flips it back to true; a brand-new
        assignment springs up `ACTIVE` for the same patient and the target,
        with `continuity_flag` true exactly when a `CLOSED` assignment
        pairing this patient with this target closed within the 30-day
        window; the target's `current_census` increments".
        PRD §2.5: "no patient ever holds more than one `ACTIVE` assignment".

        Design: Difficulty/compensating_invariant/transfer_conserves_total_active_assignments
        """
        h1, h2, p1, p2, asg1, asg2 = self._setup(api)
        asg1_v = get_success_data(api.get_assignment(asg1, ADMIN))["version"]
        api.transfer_assignment(
            asg1,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": asg1_v},
            make_hospitalist_headers(h1["id"]),
        )
        get_success_data(api.accept_transfer(asg1, make_hospitalist_headers(h2["id"])))

        # Source assignment closed as TRANSFER
        asg1_now = get_success_data(api.get_assignment(asg1, ADMIN))
        assert asg1_now["status"] == "CLOSED"
        assert asg1_now["close_reason"] == "TRANSFER"
        # Target holds a new ACTIVE assignment for the same patient
        rows, meta = validate_paginated(api.list_assignments(
            ADMIN, params={"patient_id": p1["id"], "status": "ACTIVE"}
        ))
        assert meta["total_count"] == 1
        new_asg = rows[0]
        assert new_asg["hospitalist_id"] == h2["id"]
        assert new_asg["patient_id"] == p1["id"]
        assert new_asg["continuity_flag"] is False
        # Census moved -1 / +1 (H1 held only P1; H2 held P2 and gains P1)
        h1_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        h2_now = get_success_data(api.get_hospitalist(h2["id"], ADMIN))
        assert h1_now["current_census"] == 0
        assert h2_now["current_census"] == 2


class TestDerivedCensusReconciliationAfterCancelTransfer:
    """Corner instance: derived_census_reconciliation_after_cancel_transfer."""

    def test_census_unchanged_through_transfer_cancel_cycle(self, api):
        """PRD §3.4: "cancelling requires the assignment to be
        `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`), moves
        `PENDING_TRANSFER` → `ACTIVE` again, clears
        `transfer_target_hospitalist_id`, increments the assignment's
        `version`, and leaves both hospitalists' census fields untouched".
        PRD §2.5: "`current_census` is the count of that hospitalist's
        assignments in status `ACTIVE`, refreshed on every assignment
        mutation."

        Design: Corner/complexity_layers/derived_census_reconciliation_after_cancel_transfer
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        h2 = create_hospitalist("H Two", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="L001", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        _, asg_id = admit_and_accept(p1["id"])
        asg_v = get_success_data(api.get_assignment(asg_id, ADMIN))["version"]
        # Full cycle
        get_success_data(api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": asg_v},
            make_hospitalist_headers(h1["id"]),
        ))
        get_success_data(api.cancel_transfer(asg_id, make_hospitalist_headers(h1["id"])))
        # Census reconciled
        h1_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        h2_now = get_success_data(api.get_hospitalist(h2["id"], ADMIN))
        assert h1_now["current_census"] == 1
        assert h2_now["current_census"] == 0
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["transfer_target_hospitalist_id"] is None
        assert asg_now["status"] == "ACTIVE"
