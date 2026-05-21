"""HQS inspections, cure windows, and abatement cycles.

PRD §3.5 — initial/annual/reinspection workflows, outcome-defects
matching, cure deadlines, abatement cascades, reinspection cures.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_by_days,
    advance_clock_by_hours,
    advance_clock_to,
    assert_inspection,
    complete_inspection,
    complete_inspection_payload,
    create_inspection_payload,
    current_clock,
    get_inspection,
    get_tenancy,
    get_unit,
    iso_utc,
    make_inspector_headers,
    new_inspector_id,
    parse_iso,
    schedule_inspection,
    setup_active_tenancy,
    setup_tenancy_pending_rent_reasonable,
    sweep_abatements,
    take_active_tenancy_to_abated,
    cure_abatement,
    validate_error,
    validate_success,
    DEFAULT_PHA_ID,
)


class TestInspectionOutcomeMatchingDefects:

    def test_pass_with_nonempty_defects_rejected(self, api):
        """PRD §3.5: "PASS requires an empty defects array, while any
        FAIL_* outcome requires a non-empty defects array — a mismatch
        yields ERR_INSPECTION_OUTCOME_MISMATCH."
        """
        # Tenancy in PENDING_INSPECTION with a SCHEDULED INITIAL inspection.
        state = setup_tenancy_pending_rent_reasonable.__wrapped__ if hasattr(
            setup_tenancy_pending_rent_reasonable, "__wrapped__",
        ) else None
        # Use a simpler bootstrap: create just the tenancy + scheduled inspection
        from test_helpers import (
            setup_eligible_applicant_with_voucher,
            setup_unit_with_payment_standard,
            create_pending_tenancy,
        )
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=voucher["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id=voucher["administering_pha_id"],
        )
        inspector_id = f"inspector-{voucher['administering_pha_id']}-x1"
        headers = make_inspector_headers(inspector_id)
        resp = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(
                outcome="PASS", defects=["D1"],
            ),
            headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTION_OUTCOME_MISMATCH.value,
        )

    def test_fail_with_empty_defects_rejected(self, api):
        """PRD §3.5: "any FAIL_* outcome requires a non-empty defects
        array — a mismatch yields ERR_INSPECTION_OUTCOME_MISMATCH."
        """
        from test_helpers import (
            setup_eligible_applicant_with_voucher,
            setup_unit_with_payment_standard,
            create_pending_tenancy,
        )
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=voucher["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id=voucher["administering_pha_id"],
        )
        inspector_id = f"inspector-{voucher['administering_pha_id']}-x2"
        headers = make_inspector_headers(inspector_id)
        resp = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(
                outcome="FAIL_NONLIFETHREATENING", defects=[],
            ),
            headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTION_OUTCOME_MISMATCH.value,
        )


class TestInspectionAlreadyCompleted:

    def test_complete_on_already_completed_inspection_rejected(self, api):
        """PRD §3.5: "Filing on an inspection already in a COMPLETED_*
        posture yields ERR_INSPECTION_ALREADY_COMPLETED."
        """
        state = setup_active_tenancy()
        # The INITIAL inspection completed during setup; trying to
        # re-file should fail.
        ins_id = state["inspection"]["id"]
        pha_id = state["voucher"]["administering_pha_id"]
        headers = make_inspector_headers(
            f"inspector-{pha_id}-redo",
        )
        resp = api.complete_inspection(
            ins_id,
            complete_inspection_payload(outcome="PASS", defects=[]),
            headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_INSPECTION_ALREADY_COMPLETED.value,
        )


class TestInspectorOutOfScope:

    def test_inspector_from_other_pha_cannot_complete_inspection(self, api):
        """PRD §3.5: "An Inspector may only complete inspections whose
        tenancy's voucher is administered by the inspector's own PHA;
        a violation returns ERR_INSPECTOR_OUT_OF_SCOPE."

        Inspector IDs encode PHA membership via prefix convention so the
        implementation can derive scope from X-User-ID.
        # difficulty: cross_entity_state_dependency/inspection_complete_requires_inspector_pha_matches_voucher_pair_inspection_voucher
        """
        from test_helpers import (
            setup_eligible_applicant_with_voucher,
            setup_unit_with_payment_standard,
            create_pending_tenancy,
        )
        # Tenancy on a voucher administered by PHA_001.
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            administering_pha_id="PHA_001",
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=voucher["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        # An Inspector from PHA_001 schedules.
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id="PHA_001",
        )
        # An Inspector from PHA_002 tries to complete.
        other_inspector = make_inspector_headers(
            "inspector-PHA_002-out-of-scope",
        )
        resp = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(outcome="PASS", defects=[]),
            other_inspector,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTOR_OUT_OF_SCOPE.value,
        )


class TestAnnualInspectionGap:
    """PRD §3.5: "A guard rejects any new ANNUAL inspection scheduled
    less than 365 days after the last passing inspection on the same
    unit; adjacency at exactly 365 days is permitted (the gap is
    closed-closed on the year boundary), and a violation returns
    ERR_INSPECTION_TOO_SOON."
    """

    def test_annual_inspection_at_364_days_rejected(self, api):
        """PRD §3.5: "less than 365 days after the last passing
        inspection on the same unit ... ERR_INSPECTION_TOO_SOON".
        # difficulty: resource_temporal_overlap/unit_annual_inspection_365_day_gap_inclusive
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        # last_inspection_passed_at is current_clock at the moment the
        # INITIAL inspection PASSED. Advance to +364 days.
        advance_clock_by_days(364)
        pha_id = state["voucher"]["administering_pha_id"]
        headers = make_inspector_headers(
            f"inspector-{pha_id}-too-soon",
        )
        resp = api.create_inspection(
            create_inspection_payload(
                tenancy_id=state["tenancy"]["id"],
                inspection_type="ANNUAL",
                scheduled_for=iso_utc(add_days(current_clock(), 1)),
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_TOO_SOON.value)

    def test_annual_inspection_at_365_days_allowed(self, api):
        """PRD §3.5: "adjacency at exactly 365 days is permitted (the
        gap is closed-closed on the year boundary)".
        # difficulty: resource_temporal_overlap/unit_annual_inspection_365_day_gap_inclusive
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        # Advance the clock to exactly +365 days from the initial pass.
        advance_clock_by_days(365)
        pha_id = state["voucher"]["administering_pha_id"]
        headers = make_inspector_headers(
            f"inspector-{pha_id}-ok",
        )
        resp = api.create_inspection(
            create_inspection_payload(
                tenancy_id=state["tenancy"]["id"],
                inspection_type="ANNUAL",
                scheduled_for=iso_utc(add_days(current_clock(), 1)),
            ),
            headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["inspection_type"] == "ANNUAL"


class TestAnnualInspectionFailToAbated:

    def test_annual_fail_nonlifethreatening_abates_tenancy(self, api):
        """PRD §3.5: "either branch on an ANNUAL inspection of an
        ACTIVE tenancy cascades the tenancy to ABATED, sets
        abatement_started_at to completed_at, generates the next-month
        HAP payment row with amount_cents of 0 and status of
        ABATED_SUSPENDED, and flips the unit's occupancy_status to
        OCCUPIED_ABATED."
        # difficulty: non_linear_state_machine/tenancy_branching_active_abated_cycle
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        out = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_NONLIFETHREATENING",
            defects=["D1"],
        )
        assert out["tenancy"]["status"] == "ABATED"
        assert out["unit"]["occupancy_status"] == "OCCUPIED_ABATED"

    def test_nonlifethreatening_cure_deadline_30_days(self, api):
        """PRD §3.5: "A FAIL_NONLIFETHREATENING outcome transitions the
        inspection to COMPLETED_FAIL_CURABLE and sets cure_deadline to
        completed_at plus 30 days."
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        out = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_NONLIFETHREATENING",
            defects=["D1"],
        )
        ins = out["annual_inspection"]
        assert ins["status"] == "COMPLETED_FAIL_CURABLE"
        completed = parse_iso(ins["completed_at"])
        cure = parse_iso(ins["cure_deadline"])
        delta_seconds = (cure - completed).total_seconds()
        assert abs(delta_seconds - 30 * 24 * 3600) < 60, (
            f"cure_deadline should be completed_at + 30d; "
            f"got delta = {delta_seconds}s"
        )

    def test_lifethreatening_cure_deadline_24_hours(self, api):
        """PRD §3.5: "A FAIL_LIFETHREATENING outcome transitions the
        inspection to COMPLETED_FAIL_LIFETHREAT and sets cure_deadline
        to completed_at plus 24 hours."
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        out = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_LIFETHREATENING",
            defects=["D1"],
        )
        ins = out["annual_inspection"]
        assert ins["status"] == "COMPLETED_FAIL_LIFETHREAT"
        completed = parse_iso(ins["completed_at"])
        cure = parse_iso(ins["cure_deadline"])
        delta_seconds = (cure - completed).total_seconds()
        assert abs(delta_seconds - 24 * 3600) < 60, (
            f"cure_deadline should be completed_at + 24h; "
            f"got delta = {delta_seconds}s"
        )


class TestReinspectionCured:

    def test_cured_reinspection_restores_active(self, api):
        """PRD §3.5: "A subsequent REINSPECTION filed with outcome CURED
        before the original cure_deadline (24 hours for life-threatening,
        30 days for non-life-threatening) transitions the failed
        inspection to CURED. If the parent tenancy was ABATED, it
        cascades back to ACTIVE, the unit's occupancy_status returns to
        OCCUPIED_ACTIVE."
        # difficulty: non_linear_state_machine/tenancy_branching_active_abated_cycle
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        abated = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_NONLIFETHREATENING",
            defects=["D1"],
        )
        cured = cure_abatement(abated)
        assert cured["tenancy"]["status"] == "ACTIVE"
        assert cured["unit"]["occupancy_status"] == "OCCUPIED_ACTIVE"


class TestAbatementSweepUncured:

    def test_uncured_abatement_terminates_tenancy_and_voucher(self, api):
        """PRD §3.5: "For an annual inspection of an ACTIVE tenancy that
        had gone to ABATED, the tenancy cascades to TERMINATED with
        termination_reason HQS_UNCURED, the voucher cascades from LEASED
        to TERMINATED (uncured HQS is a program violation, so the
        voucher is not reissued for further search), the unit's
        occupancy_status returns to VACANT, and all future scheduled
        HAP payment rows for this voucher are suppressed."
        # difficulty: transitive_cascade/cure_deadline_sweep_chain_depth_4
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        abated = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_NONLIFETHREATENING",
            defects=["D1"],
        )
        cure_deadline = parse_iso(abated["annual_inspection"]["cure_deadline"])
        # Advance past the cure_deadline; the abatement sweep then
        # terminates the Tenancy and cascades to Voucher.
        from datetime import timedelta
        advance_clock_to(cure_deadline + timedelta(minutes=1))
        sweep_abatements()
        t = get_tenancy(state["tenancy"]["id"])
        v = get_voucher_id_via_state(state)
        u = get_unit(state["unit"]["id"])
        assert t["status"] == "TERMINATED"
        assert t["termination_reason"] == "HQS_UNCURED"
        assert v["status"] == "TERMINATED"
        assert u["occupancy_status"] == "VACANT"


def get_voucher_id_via_state(state):
    from test_helpers import get_voucher
    return get_voucher(state["voucher"]["id"])
