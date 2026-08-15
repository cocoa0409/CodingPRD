"""Consent lifecycle, completeness boundaries, and lazy expiry (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_building,
    create_owner,
    add_tenant_units,
    get_report,
    make_owner_headers,
    make_tenant_rep_headers,
    request_and_grant_consent,
    request_consent,
    set_clock,
    setup_report_scenario,
    submit_report,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestConsentWindowOverlap:
    def _setup_unit_with_granted_consent(self):
        owner = create_owner()
        building = create_building(owner["id"])
        units = add_tenant_units(building["id"], owner["id"], [("U1", 20000, "OFFICE")])
        unit = units[0]
        request_and_grant_consent(unit["id"], owner["id"], "2027-01-01", "2027-12-31")
        return owner, unit

    def test_shared_boundary_date_counts_as_overlap(self, api):
        """PRD §3.3: "Two closed windows intersect exactly when the new window's
        `valid_from` falls on or before the existing window's `valid_to` **and** the
        existing window's `valid_from` falls on or before the new window's
        `valid_to`; an intersecting grant is rejected with `ERR_CONSENT_WINDOW_OVERLAP`."

        The candidate [2027-12-31, 2028-06-30] shares the single date 2027-12-31 with
        the existing [2027-01-01, 2027-12-31] — closed semantics make that an overlap.

        Design: Difficulty/resource_temporal_overlap/consent_windows_closed_interval_overlap
        """
        owner, unit = self._setup_unit_with_granted_consent()
        cg2 = request_consent(unit["id"], owner["id"])

        resp = api.grant_consent(
            cg2["id"],
            {"valid_from": "2027-12-31", "valid_to": "2028-06-30"},
            make_tenant_rep_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_WINDOW_OVERLAP)

    def test_adjacent_window_after_existing_accepted(self, api):
        """PRD §3.3: "Two closed windows intersect exactly when the new window's
        `valid_from` falls on or before the existing window's `valid_to` **and** the
        existing window's `valid_from` falls on or before the new window's
        `valid_to`; an intersecting grant is rejected with `ERR_CONSENT_WINDOW_OVERLAP`."

        [2028-01-01, 2028-12-31] starts strictly after the existing window's valid_to,
        so the first conjunct fails and no overlap exists.

        Design: Difficulty/resource_temporal_overlap/consent_windows_closed_interval_overlap
        """
        owner, unit = self._setup_unit_with_granted_consent()
        cg2 = request_consent(unit["id"], owner["id"])

        granted = validate_success(
            api.grant_consent(
                cg2["id"],
                {"valid_from": "2028-01-01", "valid_to": "2028-12-31"},
                make_tenant_rep_headers(unit["id"]),
            )
        )
        assert granted["status"] == "GRANTED"


class TestConsentDecisionRules:
    def test_regrant_of_granted_consent_rejected(self, api):
        """PRD §3.3: "The grant request must still be `REQUESTED` (else
        `ERR_INVALID_STATE_TRANSITION`)"

        Design: Corner/state_machines/s_consent_grant_from_granted_rejected
        """
        owner = create_owner()
        building = create_building(owner["id"])
        unit = add_tenant_units(building["id"], owner["id"], [("U1", 20000, "OFFICE")])[0]
        grant = request_and_grant_consent(unit["id"], owner["id"])

        resp = api.grant_consent(
            grant["id"],
            {"valid_from": "2027-01-01", "valid_to": "2027-12-31"},
            make_tenant_rep_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_consent_window_end_before_start_rejected(self, api):
        """PRD §3.3: "`valid_from` must not fall after `valid_to` (else
        `ERR_INVALID_DATE_RANGE`)"

        Design: Corner/validations/v_consent_invalid_date_range
        """
        owner = create_owner()
        building = create_building(owner["id"])
        unit = add_tenant_units(building["id"], owner["id"], [("U1", 20000, "OFFICE")])[0]
        grant = request_consent(unit["id"], owner["id"])

        resp = api.grant_consent(
            grant["id"],
            {"valid_from": "2027-12-31", "valid_to": "2027-01-01"},
            make_tenant_rep_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        still = validate_success(api.get_consent_grant(grant["id"], OFFICER))
        assert still["status"] == "REQUESTED"

    def test_second_open_consent_request_rejected(self, api):
        """PRD §3.3: "at most one `REQUESTED` grant may exist per unit at a time, and
        a second request is refused with `ERR_CONSENT_REQUEST_OPEN`."

        Design: Corner/validations/v_second_consent_request_open_rejected
        """
        owner = create_owner()
        building = create_building(owner["id"])
        unit = add_tenant_units(building["id"], owner["id"], [("U1", 20000, "OFFICE")])[0]
        request_consent(unit["id"], owner["id"])

        resp = api.create_consent_grant(unit["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUEST_OPEN)


class TestConsentLazyExpiry:
    def test_consent_expires_lazily_after_valid_to(self, api):
        """PRD §3.3: "When the logical clock's current date falls strictly after a
        grant's `valid_to`, the grant reads as `EXPIRED` and is excluded from
        completeness computation. Expiry is lazy: it is evaluated whenever a grant is
        read or a completeness recomputation runs, and no background job sweeps for
        it."

        Design: Corner/state_machines/s_consent_lazy_expiry_after_valid_to
        """
        # Report created BEFORE any consent: completeness reflects common area only.
        ctx = setup_report_scenario(consent_indexes=())
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(20.00, abs=0.005)

        grant = request_and_grant_consent(ctx["units"][0]["id"], ctx["owner"]["id"])
        assert get_report(ctx["report"]["id"])["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)

        set_clock("2028-01-02T00:00:00Z")
        grant_after = validate_success(api.get_consent_grant(grant["id"], OFFICER))
        assert grant_after["status"] == "EXPIRED", "grant reads EXPIRED once past valid_to"
        report_after = get_report(ctx["report"]["id"])
        assert report_after["data_completeness_pct"] == pytest.approx(20.00, abs=0.005), (
            "lapsed consent no longer counts toward completeness"
        )


class TestGrantRevokeCompletenessInvariant:
    def test_consent_grant_raises_report_completeness(self, api):
        """PRD §3.3: "A successful grant moves `REQUESTED → GRANTED`, stamps
        `decided_at`, and recomputes `data_completeness_pct` on the building's
        reports in `DRAFT`, `FLAGGED`, or `SUBMITTED` for every cycle whose calendar
        year the new window covers."

        Forward arm of the invariant: 20.00 (common only) -> 60.00 (u1) -> 90.00 (u2).

        Design: Difficulty/compensating_invariant/consent_grant_revoke_restores_consented_area
        """
        ctx = setup_report_scenario(consent_indexes=())
        report_id = ctx["report"]["id"]
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(20.00, abs=0.005)

        request_and_grant_consent(ctx["units"][0]["id"], ctx["owner"]["id"])
        assert get_report(report_id)["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)

        request_and_grant_consent(ctx["units"][1]["id"], ctx["owner"]["id"])
        assert get_report(report_id)["data_completeness_pct"] == pytest.approx(90.00, abs=0.005)

    def test_consent_revoke_restores_prior_completeness(self, api):
        """PRD §3.3: "Revocation recomputes `data_completeness_pct` on **all** of the
        building's reports for the affected cycles regardless of their status —
        `DRAFT`, `FLAGGED`, `SUBMITTED`, `VERIFIED`, and `CERTIFIED` alike"

        The grant+revoke pair conserves consented floor area: the report returns to
        exactly its pre-grant 60.00 with no drift.

        Design: Difficulty/compensating_invariant/consent_grant_revoke_restores_consented_area
        """
        ctx = setup_report_scenario(consent_indexes=(0,))
        report_id = ctx["report"]["id"]
        baseline = get_report(report_id)["data_completeness_pct"]
        assert baseline == pytest.approx(60.00, abs=0.005)

        grant2 = request_and_grant_consent(ctx["units"][1]["id"], ctx["owner"]["id"])
        assert get_report(report_id)["data_completeness_pct"] == pytest.approx(90.00, abs=0.005)

        validate_success(
            api.revoke_consent(grant2["id"], make_tenant_rep_headers(ctx["units"][1]["id"]))
        )
        restored = get_report(report_id)["data_completeness_pct"]
        assert restored == pytest.approx(60.00, abs=0.005), (
            "revoke returns completeness to exactly the pre-grant baseline"
        )


class TestCompletenessBoundary:
    def test_completeness_exactly_at_minimum_submits(self, api):
        """PRD §3.5: "The report's `data_completeness_pct` must be at least the
        cycle's `data_completeness_min_pct` — the threshold is inclusive — or the
        submission fails with `ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`."

        45000 of 50000 sqft consented-or-common is exactly 90.00 and submits.

        Design: Difficulty/boundary_precision_check/completeness_exactly_ninety_passes
        """
        ctx = setup_report_scenario()
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(90.00, abs=0.005)

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["status"] == "SUBMITTED"

    def test_completeness_just_below_minimum_rejected(self, api):
        """PRD §3.5: "The report's `data_completeness_pct` must be at least the
        cycle's `data_completeness_min_pct` — the threshold is inclusive — or the
        submission fails with `ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`."

        44995 of 50000 sqft is 89.99 — the adjacent representable value below the
        inclusive minimum — and is rejected.

        Design: Difficulty/boundary_precision_check/completeness_exactly_ninety_passes
        """
        ctx = setup_report_scenario(
            unit_specs=[("F1", 20000, "OFFICE"), ("F2", 14995, "RETAIL"), ("F3", 5005, "OFFICE")],
            consent_indexes=(0, 1),
        )
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(89.99, abs=0.005)

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DATA_COMPLETENESS_BELOW_THRESHOLD)
        still = get_report(ctx["report"]["id"])
        assert still["status"] == "DRAFT"
        assert still["data_completeness_pct"] == pytest.approx(89.99, abs=0.005)
