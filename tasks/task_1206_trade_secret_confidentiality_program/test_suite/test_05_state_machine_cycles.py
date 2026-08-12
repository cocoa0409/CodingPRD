"""Non-linear state-machine cycles: NDA breach loop, disclosure revision loop,
grant suspend/restore loop (PRD §3.2, §3.5, §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_obligation_payload,
    create_registered_asset,
    create_employee_record,
    create_active_employee,
    create_provisioned_grant,
    create_under_review_disclosure,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_senior_counsel_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestNdaBreachAllegationCycle:
    def _setup_active_nda_with_obligation(self, api):
        cp = create_counterparty(legal_name="Delta Logistics", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t4", governing_law="WA",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=6, classification_ceiling="CONFIDENTIAL",
        )
        api.create_obligation(
            create_obligation_payload(nda["id"], obligation_type="NON_DISCLOSURE"), IP
        )
        return cp, nda

    def test_breach_loop_returns_to_active_with_obligations_untouched(self, api):
        """PRD §3.2: "From `ACTIVE`, counsel may record a breach allegation —
        `ACTIVE → BREACH_ALLEGED` — and later close an unfounded allegation by
        returning `BREACH_ALLEGED → ACTIVE`; the loop touches neither
        obligations nor disclosures."

        Design: Difficulty/non_linear_state_machine/nda_breach_allegation_cycle
        """
        _cp, nda = self._setup_active_nda_with_obligation(api)
        validate_success(api.transition_nda(nda["id"], {"to_status": "BREACH_ALLEGED"}, IP))
        data = validate_success(api.transition_nda(nda["id"], {"to_status": "ACTIVE"}, IP))
        assert data["status"] == "ACTIVE"
        assert data["obligations_open_count"] == 1, \
            "the allegation loop must not disturb obligation counts"

    def test_breach_loop_bumps_version_per_transition(self, api):
        """PRD §2.4: "**`version` (integer):** a system-managed integer that
        increments by one on every mutation of the resource."
        PRD §3.2: "From `ACTIVE`, counsel may record a breach allegation —
        `ACTIVE → BREACH_ALLEGED` — and later close an unfounded allegation by
        returning `BREACH_ALLEGED → ACTIVE`; the loop touches neither
        obligations nor disclosures."

        Design: Difficulty/non_linear_state_machine/nda_breach_allegation_cycle
        """
        _cp, nda = self._setup_active_nda_with_obligation(api)
        pre = validate_success(api.get_nda(nda["id"], IP))
        validate_success(api.transition_nda(nda["id"], {"to_status": "BREACH_ALLEGED"}, IP))
        validate_success(api.transition_nda(nda["id"], {"to_status": "ACTIVE"}, IP))
        end = validate_success(api.get_nda(nda["id"], IP))
        assert end["version"] == pre["version"] + 2, \
            f"exactly the two loop transitions bump version: {pre['version']} -> {end['version']}"


def _setup_returned_disclosure(api):
    """Disclosure endorsed once, then RETURNED. Returns (asset, nda, emp, disc)."""
    cp = create_counterparty(legal_name="Epsilon Media", counterparty_type="CUSTOMER")
    nda = create_active_nda(
        cp["id"], template_version="t5", governing_law="TX",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
        survival_months=6, classification_ceiling="RESTRICTED",
    )
    asset = create_registered_asset(
        title="Churn model features", description="feature store",
        classification="CONFIDENTIAL", owner_department="DATA",
        exposure_estimate_cents=250000,
    )
    emp = create_employee_record(
        full_name="Hank Analyst", email="hank@x.com", department="DATA",
        role_title="Analyst", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Case study", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-07-01T00:00:00Z",
    )
    validate_success(api.endorse_disclosure(disc["id"], make_senior_counsel_headers("senior_1")))
    validate_success(api.transition_disclosure(disc["id"], {"to_status": "RETURNED"}, IP))
    return asset, nda, emp, disc


class TestDisclosureReturnRevisionCycle:
    def test_returned_to_draft_resets_endorsement(self, api):
        """PRD §3.5: "Returning (`UNDER_REVIEW → RETURNED`) sends the request
        back for revision, and the requester reopens it — `RETURNED → DRAFT` —
        which clears both pins to empty and resets `senior_endorsed` to false,
        so the loop `DRAFT → SUBMITTED → UNDER_REVIEW → RETURNED → DRAFT` always
        re-pins and re-scores on the next pass."

        Design: Difficulty/non_linear_state_machine/disclosure_return_revision_cycle
        """
        _asset, _nda, emp, disc = _setup_returned_disclosure(api)
        data = validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "DRAFT"}, make_employee_headers(emp["id"])
        ))
        assert data["status"] == "DRAFT"
        assert data["senior_endorsed"] is False, \
            "RETURNED -> DRAFT must reset the endorsement"

    def test_resubmission_repins_and_rescores(self, api):
        """PRD §3.5: "Submission pins the world: `pinned_asset_version` captures
        the asset's current `version`, `pinned_nda_version` captures the NDA's
        current `version`, and `risk_score_provisional` is computed for the
        requester's own visibility."
        PRD §3.5: "the requester reopens it — `RETURNED → DRAFT` — which clears
        both pins to empty and resets `senior_endorsed` to false, so the loop
        `DRAFT → SUBMITTED → UNDER_REVIEW → RETURNED → DRAFT` always re-pins and
        re-scores on the next pass."

        Design: Difficulty/non_linear_state_machine/disclosure_return_revision_cycle
        """
        asset, _nda, emp, disc = _setup_returned_disclosure(api)
        validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "DRAFT"}, make_employee_headers(emp["id"])
        ))
        data = validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "SUBMITTED"}, make_employee_headers(emp["id"])
        ))
        assert data["status"] == "SUBMITTED"
        asset_now = validate_success(api.get_asset(asset["id"], IP))
        assert data["pinned_asset_version"] == asset_now["version"], \
            "second SUBMITTED must re-pin the asset's current version"
        assert data["risk_score_provisional"] == pytest.approx(20.0, abs=0.01), \
            f"CONFIDENTIAL 30 - STAMPED 10 = 20 recomputed on resubmission, got {data['risk_score_provisional']}"


def _setup_provisioned_grant(api):
    emp = create_active_employee(
        full_name="Ivy Ops", email="ivy@x.com", department="OPS",
        role_title="Operator", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    asset = create_registered_asset(
        title="Line-stoppage playbook", description="plant ops",
        classification="CONFIDENTIAL", owner_department="OPS",
        exposure_estimate_cents=80000,
    )
    grant = create_provisioned_grant(
        emp["id"], asset["id"], justification="On-call duty",
        expires_at="2026-12-01T00:00:00Z",
    )
    return emp, asset, grant


class TestGrantSuspendRestoreCycle:
    def test_suspended_grant_still_counts_as_active(self, api):
        """PRD §3.4: "The count itself obeys a compensating invariant: it tallies
        the asset's grants in `APPROVED`, `PROVISIONED`, or `SUSPENDED` status."

        Design: Difficulty/non_linear_state_machine/grant_suspend_restore_cycle
        """
        _emp, asset, grant = _setup_provisioned_grant(api)
        validate_success(api.transition_grant(grant["id"], {"to_status": "SUSPENDED"}, SEC))
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["active_grant_count"] == 1, \
            "SUSPENDED still counts toward active_grant_count"

    def test_suspend_restore_loop_conserves_count(self, api):
        """PRD §3.4: "A provisioned grant may be suspended and reinstated
        (`PROVISIONED → SUSPENDED → PROVISIONED`) by security."
        PRD §3.4: "suspending and reinstating never move it."

        Design: Difficulty/non_linear_state_machine/grant_suspend_restore_cycle
        """
        _emp, asset, grant = _setup_provisioned_grant(api)
        validate_success(api.transition_grant(grant["id"], {"to_status": "SUSPENDED"}, SEC))
        data = validate_success(api.transition_grant(grant["id"], {"to_status": "PROVISIONED"}, SEC))
        assert data["status"] == "PROVISIONED"
        asset_now = validate_success(api.get_asset(asset["id"], IP))
        assert asset_now["active_grant_count"] == 1, \
            "the suspend/restore loop conserves the count at 1"
