"""Acquisition accounting dual variant, appraisal certification cascade, and
appraisal write-down evaluation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_property_with_certified_appraisal,
    create_appraiser,
    create_draft_appraisal,
    submit_appraisal,
    certify_appraisal,
    get_property,
    list_write_downs,
    list_ledger_entries,
    set_clock,
    make_appraiser_headers,
    make_chief_appraiser_headers,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
CHIEF = TEST_USERS["chief_appraiser_headers"]


class TestAcquisitionDualVariant:
    def test_acquisition_basis_provisional_at_creation(self, api):
        """PRD §3.1: "Intake runs the provisional variant of the acquisition
        accounting rule: fair_value_at_acquisition is set equal to bpo_value,
        and acquisition_basis is computed as fair_value_at_acquisition minus
        eight percent of fair_value_at_acquisition rounded half-up to two
        decimal places — the cost-to-sell allowance of 0.08."

        Design: Difficulty/dual_variant_calc/acquisition_basis_provisional_vs_final
        """
        prop = create_property(
            address="1420 Maple St",
            acquisition_date="2026-05-10",
            bpo_value=400000.00,
            foreclosure_debt=410000.00,
        )
        assert prop["fair_value_at_acquisition"] == 400000.00
        assert prop["acquisition_basis"] == 368000.00
        assert prop["carrying_value"] == 368000.00

    def test_acquisition_basis_final_variant_recomputes_and_posts_adjustment(self, api):
        """PRD §3.3: "If the certified appraisal's effective_date falls on or
        before acquisition_date plus 180 days, this is the first in-window
        certification and the FINAL acquisition variant runs:
        fair_value_at_acquisition is recomputed from the certified appraised_value
        (replacing the provisional bpo_value basis), acquisition_basis is
        recomputed as the new fair_value_at_acquisition minus eight percent
        rounded half-up to two decimals, and the delta between the old
        carrying_value and the new acquisition_basis is measured. A nonzero delta
        auto-creates an already-POSTED write-down with amount equal to that
        delta, reason MEASUREMENT_PERIOD_ADJUSTMENT, auto_generated true, and
        proposed_by_user_id set to the literal string system; that posting
        appends a WRITE_DOWN ledger entry carrying the negative of the delta
        amount. A zero delta creates no write-down row at all."

        Design: Difficulty/dual_variant_calc/acquisition_basis_provisional_vs_final
        """
        prop = create_property(
            address="1420 Maple St",
            acquisition_date="2026-05-10",
            bpo_value=400000.00,
            foreclosure_debt=410000.00,
        )
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser(
            name="Apex Valuations", license_number="LIC-A1", coverage_states=["CA"]
        )
        appraisal = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop["version"],
            effective_date="2026-06-01",
            appraised_value=380000.00,
        )
        submit_appraisal(appraisal["id"], appraiser["id"])
        certify_appraisal(appraisal["id"])

        after = get_property(prop["id"])
        assert after["fair_value_at_acquisition"] == 380000.00
        assert after["acquisition_basis"] == 349600.00
        # Per PRD §3.1 carrying_value identity: basis + capitalized - POSTED write-downs
        # = 349600 + 0 - 18400 = 331200
        assert after["carrying_value"] == 331200.00

        # exactly one POSTED measurement-adjustment write-down of 18400.00
        wds = list_write_downs(prop["id"])
        assert len(wds) == 1
        wd = wds[0]
        assert wd["status"] == "POSTED"
        assert wd["amount"] == 18400.00
        assert wd["reason"] == "MEASUREMENT_PERIOD_ADJUSTMENT"
        assert wd["auto_generated"] is True
        assert wd["proposed_by_user_id"] == "system"

        # ledger carries WRITE_DOWN entry with -18400.00
        entries = list_ledger_entries(prop["id"])
        wd_entries = [e for e in entries if e["entry_type"] == "WRITE_DOWN"]
        assert len(wd_entries) == 1
        assert wd_entries[0]["amount"] == -18400.00


class TestAppraisalCertificationCascade:
    def test_certification_propagates_value_to_property(self, api):
        """PRD §3.3: "Certification fires a three-link cascade. Link one records
        the certifier's X-User-ID in certified_by_user_id. Link two updates the
        property: current_fair_value becomes the certified appraised_value, and
        appraisal_status is recomputed from the certified effective_date."

        Design: Difficulty/transitive_cascade/appraisal_certification_fv_writedown_cascade
        """
        prop, appraiser, appraisal = create_property_with_certified_appraisal(
            appraised_value=400000.00
        )
        after = get_property(prop["id"])
        assert after["current_fair_value"] == 400000.00
        assert after["appraisal_status"] == "CURRENT"

    def test_certification_outside_window_creates_proposed_write_down(self, api):
        """PRD §3.3: "If instead the certified effective_date falls strictly
        after the 180-day measurement window, the write-down evaluation rule
        runs instead: the property's net_realizable_value is computed from the
        newly certified value, the required write-down is the current
        carrying_value minus net_realizable_value, and when the required amount
        is strictly greater than zero a PROPOSED write-down is auto-created with
        that amount, reason MARKET_DECLINE, and auto_generated true, raising the
        property's pending_write_down_count. When the required amount is zero or
        negative — the boundary is a strict greater-than — no row is created."

        Design: Difficulty/transitive_cascade/appraisal_certification_fv_writedown_cascade
        """
        # Property with a certified 400k appraisal (basis = carrying = 368000).
        prop, appraiser, _ = create_property_with_certified_appraisal(
            appraised_value=400000.00
        )
        # Advance clock so a second appraisal falls outside the measurement window.
        set_clock("2026-12-10T00:00:00Z")
        prop_now = get_property(prop["id"])
        appraisal2 = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop_now["version"],
            effective_date="2026-12-10",
            appraised_value=350000.00,
        )
        submit_appraisal(appraisal2["id"], appraiser["id"])
        certify_appraisal(appraisal2["id"])

        after = get_property(prop["id"])
        assert after["current_fair_value"] == 350000.00
        assert after["net_realizable_value"] == 322000.00
        # carrying still 368000 (proposal is not yet posted)
        assert after["carrying_value"] == 368000.00
        assert after["pending_write_down_count"] == 1

        wds = list_write_downs(prop["id"])
        assert len(wds) == 1
        wd = wds[0]
        assert wd["status"] == "PROPOSED"
        assert wd["amount"] == 46000.00
        assert wd["reason"] == "MARKET_DECLINE"
        assert wd["auto_generated"] is True


class TestAppraisalRejectionLoop:
    def test_reject_moves_to_draft_and_records_reason(self, api):
        """PRD §3.3: "A ChiefAppraiser rejection returns the appraisal to DRAFT
        and records the supplied rejection_reason so the appraiser can revise
        and resubmit".

        Design: Difficulty/non_linear_state_machine/appraisal_rejection_revision_loop
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        appraisal = create_draft_appraisal(
            prop["id"], appraiser["id"], prop["version"], appraised_value=400000.00
        )
        submit_appraisal(appraisal["id"], appraiser["id"])

        reject_resp = api.reject_appraisal(
            appraisal["id"],
            {"rejection_reason": "insufficient comparable sales"},
            CHIEF,
        )
        rejected = validate_success(reject_resp, expected_status=200)
        assert rejected["status"] == "DRAFT"
        assert rejected["rejection_reason"] == "insufficient comparable sales"

    def test_rejected_appraisal_can_be_resubmitted_and_certified(self, api):
        """PRD §3.3: "A ChiefAppraiser rejection returns the appraisal to DRAFT
        and records the supplied rejection_reason so the appraiser can revise
        and resubmit"; and "When the required amount is zero or negative — the
        boundary is a strict greater-than — no row is created."

        Design: Difficulty/non_linear_state_machine/appraisal_rejection_revision_loop
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        appraisal = create_draft_appraisal(
            prop["id"], appraiser["id"], prop["version"], appraised_value=400000.00
        )
        submit_appraisal(appraisal["id"], appraiser["id"])
        # reject -> DRAFT
        api.reject_appraisal(
            appraisal["id"],
            {"rejection_reason": "insufficient comparable sales"},
            CHIEF,
        )
        # resubmit the SAME row
        resub = api.submit_appraisal(
            appraisal["id"], make_appraiser_headers(appraiser["id"])
        )
        assert validate_success(resub)["status"] == "SUBMITTED"
        # certify
        cert = api.certify_appraisal(
            appraisal["id"], make_chief_appraiser_headers("chief-appraiser-1")
        )
        certified = validate_success(cert)
        assert certified["status"] == "CERTIFIED"
        # value equal to original bpo -> final delta zero -> no write-down rows
        after = get_property(prop["id"])
        assert after["current_fair_value"] == 400000.00
        wds = list_write_downs(prop["id"])
        assert len(wds) == 0


class TestWriteDownZeroBoundary:
    def test_write_down_zero_delta_creates_nothing_in_window(self, api):
        """PRD §3.3: "A zero delta creates no write-down row at all."

        Design: Difficulty/boundary_precision_check/write_down_zero_delta_creates_nothing
        """
        # appraised == bpo == 400000.00 -> FINAL delta is 0
        prop, appraiser, _ = create_property_with_certified_appraisal(
            appraised_value=400000.00
        )
        wds = list_write_downs(prop["id"])
        assert len(wds) == 0

    def test_write_down_zero_delta_creates_nothing_outside_window(self, api):
        """PRD §3.3: "When the required amount is zero or negative — the
        boundary is a strict greater-than — no row is created."

        Design: Difficulty/boundary_precision_check/write_down_zero_delta_creates_nothing
        """
        prop, appraiser, _ = create_property_with_certified_appraisal(
            appraised_value=400000.00
        )
        # outside measurement window; second appraisal at same value 400k
        set_clock("2026-12-10T00:00:00Z")
        prop_now = get_property(prop["id"])
        appraisal2 = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop_now["version"],
            effective_date="2026-12-10",
            appraised_value=400000.00,
        )
        submit_appraisal(appraisal2["id"], appraiser["id"])
        certify_appraisal(appraisal2["id"])

        # required = carrying 368000 - NRV(400000) = 0 -> no row
        wds = list_write_downs(prop["id"])
        assert len(wds) == 0
        after = get_property(prop["id"])
        assert after["carrying_value"] == 368000.00
        assert after["current_fair_value"] == 400000.00
        assert after["net_realizable_value"] == 368000.00


class TestAppraisalStatusThresholds:
    def test_appraisal_status_ages_through_thresholds(self, api):
        """PRD §3.3: "the property is CURRENT while the logical clock is on or
        before E plus 335 days — that is, the 365-day appraisal interval minus
        the 30-day due-soon window; DUE_SOON while the clock is strictly after
        E plus 335 days and on or before E plus 365 days; and OVERDUE once the
        clock is strictly after E plus 365 days."

        Design: Corner/calculations/appraisal_status_ages_through_thresholds
        """
        prop, _ap, _a = create_property_with_certified_appraisal(
            appraised_value=400000.00, effective_date="2026-06-01"
        )

        # E = 2026-06-01; E+335 = 2027-05-02; E+365 = 2027-06-01
        set_clock("2027-05-02T00:00:00Z")
        s1 = get_property(prop["id"])["appraisal_status"]
        assert s1 == "CURRENT", f"at E+335 must be CURRENT, got {s1}"

        set_clock("2027-05-03T00:00:00Z")
        s2 = get_property(prop["id"])["appraisal_status"]
        assert s2 == "DUE_SOON", f"E+335 < clock <= E+365 must be DUE_SOON, got {s2}"

        set_clock("2027-06-01T00:00:00Z")
        s3 = get_property(prop["id"])["appraisal_status"]
        assert s3 == "DUE_SOON", f"at E+365 must be DUE_SOON, got {s3}"

        set_clock("2027-06-02T00:00:00Z")
        s4 = get_property(prop["id"])["appraisal_status"]
        assert s4 == "OVERDUE", f"clock > E+365 must be OVERDUE, got {s4}"


class TestAppraisalValidations:
    def test_resubmit_submitted_appraisal_returns_invalid_state(self, api):
        """PRD §3.3: "a submit, certify, or reject attempted from the wrong
        from-state fails with ERR_APPRAISAL_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/resubmit_submitted_appraisal_returns_invalid_state
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        appraisal = create_draft_appraisal(
            prop["id"], appraiser["id"], prop["version"], appraised_value=400000.00
        )
        submit_appraisal(appraisal["id"], appraiser["id"])
        # second submit must fail
        resp = api.submit_appraisal(
            appraisal["id"], make_appraiser_headers(appraiser["id"])
        )
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_INVALID_STATE)
        # state unchanged
        assert (
            validate_success(api.get_appraisal(appraisal["id"], ADMIN))["status"]
            == "SUBMITTED"
        )

    def test_appraiser_cannot_certify_appraisal_forbidden(self, api):
        """PRD §3.3: "A ChiefAppraiser then either certifies or rejects the
        submission." Only the ChiefAppraiser role is authorized for certify.
        PRD §2.1: "A request whose role is not on the endpoint's authorized list
        is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/validations/appraiser_cannot_certify_appraisal_forbidden
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        appraisal = create_draft_appraisal(
            prop["id"], appraiser["id"], prop["version"], appraised_value=400000.00
        )
        submit_appraisal(appraisal["id"], appraiser["id"])
        # Appraiser role cannot certify
        resp = api.certify_appraisal(
            appraisal["id"], make_appraiser_headers(appraiser["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_appraiser_cannot_submit_another_appraisers_appraisal_forbidden(self, api):
        """PRD §2.1: "an appraisal-creation or appraisal-submission request is
        entity-backed, so the server compares appraiser_id on the payload (at
        creation) or appraisal.appraiser_id on the resource (at submit) against
        X-User-ID and returns ERR_FORBIDDEN on a mismatch."

        Design: Corner/validations/appraiser_cannot_submit_another_appraisers_appraisal_forbidden
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        a1 = create_appraiser(name="Apex Valuations", license_number="LIC-A1")
        a2 = create_appraiser(name="Beacon Appraisal", license_number="LIC-A2")
        appraisal = create_draft_appraisal(
            prop["id"], a1["id"], prop["version"], appraised_value=400000.00
        )
        # a2 attempts to submit a1's appraisal
        resp = api.submit_appraisal(appraisal["id"], make_appraiser_headers(a2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert (
            validate_success(api.get_appraisal(appraisal["id"], ADMIN))["status"]
            == "DRAFT"
        )

    def test_certify_by_submitting_user_returns_segregation_error(self, api):
        """PRD §3.3: "Certification refuses to let the same operator certify
        their own submission: if the certifier's X-User-ID equals
        submitted_by_user_id, the request is rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/certify_by_submitting_user_returns_segregation_error
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        appraisal = create_draft_appraisal(
            prop["id"], appraiser["id"], prop["version"], appraised_value=400000.00
        )
        submit_appraisal(appraisal["id"], appraiser["id"])
        # ChiefAppraiser role but X-User-ID matches the submitter
        resp = api.certify_appraisal(
            appraisal["id"], make_chief_appraiser_headers(appraiser["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_appraisal_effective_date_in_future_returns_422(self, api):
        """PRD §3.3: "The effective_date must not be in the future relative to
        the logical clock, or creation fails with ERR_EFFECTIVE_DATE_IN_FUTURE
        (HTTP 422)."

        Design: Corner/validations/appraisal_effective_date_in_future_returns_422
        """
        prop = create_property()
        # clock untouched at startup default 2026-05-01T00:00:00Z
        appraiser = create_appraiser()
        from test_helpers import create_appraisal_payload

        payload = create_appraisal_payload(
            property_id=prop["id"],
            appraiser_id=appraiser["id"],
            effective_date="2027-01-01",
            appraised_value=400000.00,
            expected_property_version=prop["version"],
        )
        resp = api.create_appraisal(payload, make_appraiser_headers(appraiser["id"]))
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_IN_FUTURE)

    def test_certify_duplicate_effective_date_returns_409(self, api):
        """PRD §3.3: "Certification also enforces the one-per-date rule: if
        another CERTIFIED appraisal already exists on the same property with the
        same effective_date, the request fails with
        ERR_DUPLICATE_APPRAISAL_DATE (HTTP 409)."

        Design: Corner/validations/certify_duplicate_effective_date_returns_409
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        a1 = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop["version"],
            effective_date="2026-06-01",
            appraised_value=400000.00,
        )
        submit_appraisal(a1["id"], appraiser["id"])
        certify_appraisal(a1["id"])
        # second appraisal with same effective_date
        prop_now = get_property(prop["id"])
        a2 = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop_now["version"],
            effective_date="2026-06-01",
            appraised_value=395000.00,
        )
        submit_appraisal(a2["id"], appraiser["id"])
        resp = api.certify_appraisal(a2["id"], CHIEF)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPRAISAL_DATE)
        assert (
            validate_success(api.get_appraisal(a2["id"], ADMIN))["status"]
            == "SUBMITTED"
        )

    def test_appraisal_by_out_of_state_appraiser_returns_422(self, api):
        """PRD §3.3: "The creating appraiser must be licensed in the property's
        state: the property's state_code must appear in the appraiser's
        coverage_states array, or creation fails with
        ERR_APPRAISER_NOT_ELIGIBLE (HTTP 422)."

        Design: Corner/validations/appraisal_by_out_of_state_appraiser_returns_422
        """
        prop = create_property(state_code="CA")
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser(
            name="Desert Appraisal", license_number="LIC-A9", coverage_states=["NV"]
        )
        from test_helpers import create_appraisal_payload

        payload = create_appraisal_payload(
            property_id=prop["id"],
            appraiser_id=appraiser["id"],
            effective_date="2026-06-01",
            appraised_value=400000.00,
            expected_property_version=prop["version"],
        )
        resp = api.create_appraisal(payload, make_appraiser_headers(appraiser["id"]))
        validate_error(resp, ApiErrorId.ERR_APPRAISER_NOT_ELIGIBLE)
