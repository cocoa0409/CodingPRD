"""Float pool deployment: candidate selection, tie-breaks, empty-pool
fallback, release semantics, and the acuity-amendment cascade."""
import pytest

from test_helpers import (
    accept_assignment,
    ADMIN,
    api_client,
    ApiErrorId,
    create_float_nurse,
    create_float_request,
    create_full_matrix,
    create_nurse,
    create_shift,
    create_unit,
    FLOAT_COORD,
    get_shift,
    get_week_ledger,
    make_charge_nurse_headers,
    propose_assignment,
    setup_unit_with_shift,
    submit_snapshot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFloatCandidateSelection:

    def test_float_selector_tie_break_created_at(self):
        """PRD section 3.5: "Eligible candidates are ranked by their projected
        hours for the shift's week, ascending, and ties are broken by the
        nurse's `created_at` timestamp, ascending — never by identifier."

        Design: Corner/calculations/float_selector_tie_break_created_at
        """
        sc = setup_unit_with_shift(name="ICU C3", census=(4, 0, 0, 0))
        f1 = create_float_nurse(full_name="First Fred")
        f2 = create_float_nurse(full_name="Second Sally")
        data = create_float_request(sc["shift"]["id"])
        assert data["status"] == "DEPLOYED"
        assert data["deployed_nurse_id"] == f1["id"], \
            f"tie on 0.0 projected hours must break to the earlier created_at nurse {f1['id']}, got {data['deployed_nurse_id']}"
        assert data["deployed_nurse_id"] != f2["id"]

    def test_float_selector_skips_ineligible(self):
        """PRD section 3.5: "A candidate must hold the shift's unit type among
        their `competencies`, must have no live assignment (`PROPOSED`,
        `ACCEPTED`, or `CONFIRMED`) whose shift interval overlaps the target
        shift under the half-open rule of §2.11 — touching endpoints are not
        overlaps — and must have headroom in the week".

        Design: Corner/calculations/float_selector_skips_ineligible
        """
        u1 = create_unit(name="ICU C4a", unit_type="ICU")
        u2 = create_unit(name="ICU C4b", unit_type="ICU")
        create_full_matrix("ICU")
        cn = create_nurse(full_name="C4 Charge", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=7000,
                          home_unit_id=u1["id"], charge_qualified=True)
        ch = make_charge_nurse_headers(cn["id"])
        submit_snapshot(u1["id"], "2026-08-10", "DAY", (4, 0, 0, 0),
                        as_headers=ch)
        submit_snapshot(u2["id"], "2026-08-10", "DAY", (4, 0, 0, 0),
                        as_headers=ch)
        sh1 = create_shift(u1["id"], "2026-08-10", "DAY")
        sh2 = create_shift(u2["id"], "2026-08-10", "DAY")

        f1 = create_float_nurse(full_name="Not Competent",
                                competencies=["MED_SURG"])
        f2 = create_float_nurse(full_name="Busy Beth", competencies=["ICU"])
        f3 = create_float_nurse(full_name="Free Fran", competencies=["ICU"])
        # F2 holds a PROPOSED assignment on U2's DAY shift — same 07:00-19:00Z
        # interval as the target, so the overlap filter excludes her.
        propose_assignment(sh2["id"], f2["id"], ch)

        data = create_float_request(sh1["id"])
        assert data["status"] == "DEPLOYED"
        assert data["deployed_nurse_id"] == f3["id"], \
            f"F1 incompetent and F2 overlapping; expected {f3['id']}, got {data['deployed_nurse_id']}"

    def test_float_selector_empty_pool_unfulfilled(self):
        """PRD section 3.5: "An empty candidate pool leaves the request
        `UNFULFILLED` and creates no assignment."

        Design: Corner/calculations/float_selector_empty_pool_unfulfilled
        """
        sc = setup_unit_with_shift(name="ICU C5", census=(4, 0, 0, 0))
        resp = api_client.create_float_request({"shift_id": sc["shift"]["id"]},
                                               FLOAT_COORD)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "UNFULFILLED"
        assert data.get("assignment_id") is None
        assert data.get("deployed_nurse_id") is None


class TestFloatRelease:

    def _setup_deployed_float(self, name):
        sc = setup_unit_with_shift(name=name, census=(4, 0, 0, 0))
        f1 = create_float_nurse(full_name=f"{name} Float")
        fr = create_float_request(sc["shift"]["id"])
        assert fr["status"] == "DEPLOYED"
        sc.update({"f1": f1, "fr": fr})
        return sc

    def test_float_release_cancels_linked_assignment(self):
        """PRD section 3.5: "A successful release transitions the request to
        `RELEASED`, cancels the linked proposed assignment with its
        projected-hours release, and re-evaluates the shift's posture."

        Design: Corner/state_machines/float_release_cancels_linked_assignment
        """
        sc = self._setup_deployed_float("ICU A9")
        fr = sc["fr"]
        data = validate_success(
            api_client.release_float_request(fr["id"], FLOAT_COORD),
            expected_status=200)
        assert data["status"] == "RELEASED"

        asg = validate_success(
            api_client.get_assignment(fr["assignment_id"], ADMIN),
            expected_status=200)
        assert asg["status"] == "CANCELLED", \
            f"release must cancel the linked PROPOSED assignment, got {asg['status']}"
        ledger = get_week_ledger(sc["f1"]["id"], "2026-08-10")
        assert ledger["projected_hours"] == 0.0

    def test_float_release_after_accept_rejected(self):
        """PRD section 3.5: "Once the nurse has accepted, or the request is in
        any other state, release is rejected with
        `ERR_FLOAT_REQUEST_NOT_RELEASABLE`."

        Design: Corner/state_machines/float_release_after_accept_rejected
        """
        sc = self._setup_deployed_float("ICU B1")
        accept_assignment(sc["fr"]["assignment_id"], sc["f1"]["id"])
        resp = api_client.release_float_request(sc["fr"]["id"], FLOAT_COORD)
        validate_error(resp, ApiErrorId.ERR_FLOAT_REQUEST_NOT_RELEASABLE)


class TestAcuityAmendmentCascade:
    """Difficulty instance: acuity_amendment_triggers_float_deployment."""

    def _setup_amendment_scenario(self):
        """ICU unit; snapshot S1 census 2/3/2/1 (required 4) governs the DAY
        shift; one idle FLOAT_POOL ICU nurse."""
        sc = setup_unit_with_shift(name="ICU E", census=(2, 3, 2, 1))
        f1 = create_float_nurse(full_name="Flo Float", competencies=["ICU"])
        sc["f1"] = f1
        return sc

    def _fire_amendment(self, sc):
        """Submit the heavier census 2/3/4/3 (required 7) for the same slot."""
        return submit_snapshot(sc["unit"]["id"], "2026-08-10", "DAY",
                               (2, 3, 4, 3),
                               as_headers=sc["charge_headers"])

    def test_amendment_supersedes_and_recomputes_shift(self):
        """PRD section 3.2: "When a new snapshot is submitted for a slot that
        already has a `SUBMITTED` snapshot, the previous one transitions to
        `SUPERSEDED`, and the supersede fires a cascade into the matching
        shift, if one exists."
        PRD section 3.2: "the shift's `required_nurses` is recomputed from the
        new snapshot, the shift's `version` increments by one, and its staffing
        posture is re-evaluated with the `OPEN`-to-`STAFFED` reconciliation of
        §2.7 applied."

        Design: Difficulty/transitive_cascade/acuity_amendment_triggers_float_deployment
        """
        sc = self._setup_amendment_scenario()
        old_version = sc["shift"]["version"]
        s2 = self._fire_amendment(sc)
        # ceil(2/4)+ceil(3/3)+ceil(4/2)+ceil(3/1) = 1+1+2+3
        assert s2["required_nurses"] == 7

        shift = get_shift(sc["shift"]["id"])
        assert shift["required_nurses"] == 7, \
            f"shift must recompute to 7, got {shift['required_nurses']}"
        assert shift["staffing_posture"] == "CRITICAL"
        assert shift["version"] == old_version + 1, \
            f"shift version must increment by one: {old_version} -> {shift['version']}"

        s1 = validate_success(
            api_client.get_acuity_snapshot(sc["snapshot"]["id"], ADMIN),
            expected_status=200)
        assert s1["status"] == "SUPERSEDED"

    def test_amendment_auto_deploys_float_request(self):
        """PRD section 3.2: "If the recomputed posture is `CRITICAL` and the
        shift has no float request currently `DEPLOYED`, the system creates a
        float request with `origin` set to `AUTO_ACUITY` and immediately runs
        the candidate selection of §3.5 against it: a successful selection
        creates the proposed float assignment and marks the request `DEPLOYED`,
        while an empty candidate pool leaves the request `UNFULFILLED`."
        PRD section 3.5: "The winner receives a new assignment in `PROPOSED`
        status with `source` `FLOAT`".

        Design: Difficulty/transitive_cascade/acuity_amendment_triggers_float_deployment
        """
        sc = self._setup_amendment_scenario()
        self._fire_amendment(sc)

        data, _meta = validate_paginated(api_client.list_float_requests(
            ADMIN, params={"shift_id": sc["shift"]["id"]}))
        assert len(data) == 1, f"exactly one auto float request, got {len(data)}"
        fr = data[0]
        assert fr["origin"] == "AUTO_ACUITY"
        assert fr["status"] == "DEPLOYED"
        assert fr["deployed_nurse_id"] == sc["f1"]["id"]

        asg = validate_success(
            api_client.get_assignment(fr["assignment_id"], ADMIN),
            expected_status=200)
        assert asg["source"] == "FLOAT"
        assert asg["status"] == "PROPOSED"
        assert asg["nurse_id"] == sc["f1"]["id"]
