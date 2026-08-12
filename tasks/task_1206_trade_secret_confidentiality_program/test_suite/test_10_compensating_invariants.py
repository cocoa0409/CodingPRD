"""Compensating invariants: active_grant_count conservation across
approve/revoke/suspend (PRD §3.4) and NDA obligation bucket conservation
(PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_nda_payload,
    create_obligation_payload,
    create_registered_asset,
    create_active_employee,
    create_grant_request,
    make_counterparty_rep_headers,
    make_security_officer_headers,
    make_obligations_overdue,
    assert_nda_obligation_bucket_invariant,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]


def _setup_grant_invariant(api):
    emp = create_active_employee(
        full_name="Tess Guard", email="tess@x.com", department="OPS",
        role_title="Guard", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    asset = create_registered_asset(
        title="Gate rotation plan", description="physical security",
        classification="CONFIDENTIAL", owner_department="OPS",
        exposure_estimate_cents=50000,
    )
    # A denied grant: never enters the active set
    denied = create_grant_request(emp["id"], asset["id"], justification="round 1",
                                  expires_at="2026-12-01T00:00:00Z")
    validate_success(api.transition_grant(denied["id"], {"to_status": "DENIED"}, SEC))
    return emp, asset


class TestGrantApproveRevokeCountConservation:
    def test_denied_grant_never_enters_active_set(self, api):
        """PRD §3.4: "The count itself obeys a compensating invariant: it
        tallies the asset's grants in `APPROVED`, `PROVISIONED`, or `SUSPENDED`
        status."
        PRD §3.4: "Denial — `REQUESTED → DENIED` — is unconditional and
        terminal."

        Design: Difficulty/compensating_invariant/grant_approve_revoke_count_conservation
        """
        _emp, asset = _setup_grant_invariant(api)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["active_grant_count"] == 0, \
            "DENIED grant never entered the active set"

    def test_approve_suspend_revoke_sequence_returns_count_to_zero(self, api):
        """PRD §3.4: "A forward approval paired with its compensating revocation
        returns the count to its prior value; suspending and reinstating never
        move it; denial never entered it; and sweep-driven expiry of an approved
        or provisioned grant is the only other decrement."
        PRD §3.4: "Approving stamps `approved_by_user_id` and adds one to the
        asset's `active_grant_count`."
        PRD §3.4: "Revocation — from `APPROVED`, `PROVISIONED`, or `SUSPENDED` —
        is available to security or counsel and subtracts one from the asset's
        `active_grant_count`."

        Design: Difficulty/compensating_invariant/grant_approve_revoke_count_conservation
        """
        emp, asset = _setup_grant_invariant(api)
        grant = create_grant_request(emp["id"], asset["id"], justification="round 2",
                                     expires_at="2026-12-01T00:00:00Z")
        validate_success(api.transition_grant(
            grant["id"], {"to_status": "APPROVED"}, make_security_officer_headers("sec_officer_1")
        ))
        c1 = validate_success(api.get_asset(asset["id"], IP))["active_grant_count"]
        assert c1 == 1, "APPROVED +1"
        validate_success(api.transition_grant(grant["id"], {"to_status": "PROVISIONED"}, SEC))
        validate_success(api.transition_grant(grant["id"], {"to_status": "SUSPENDED"}, SEC))
        c2 = validate_success(api.get_asset(asset["id"], IP))["active_grant_count"]
        assert c2 == 1, "SUSPENDED still counted"
        validate_success(api.transition_grant(grant["id"], {"to_status": "REVOKED"}, SEC))
        c3 = validate_success(api.get_asset(asset["id"], IP))["active_grant_count"]
        assert c3 == 0, "REVOKE compensates APPROVE exactly; no drift"


class TestObligationBucketTotalConservation:
    def _setup_nda_with_three_obligations(self, api):
        cp = create_counterparty(legal_name="Mu Analytics", counterparty_type="CONSULTANT")
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t12", governing_law="CO",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
                survival_months=6, classification_ceiling="INTERNAL",
            ), IP
        )
        nda = validate_success(resp, expected_status=201)
        ids = []
        for otype, kwargs in [
            ("NON_DISCLOSURE", {}),
            ("NON_USE", {}),
            ("AUDIT_RIGHT", {"due_at": "2026-05-10T00:00:00Z"}),
        ]:
            resp = api.create_obligation(
                create_obligation_payload(nda["id"], obligation_type=otype, **kwargs), IP
            )
            ids.append(validate_success(resp, expected_status=201)["id"])
        return cp, nda, ids

    def test_fulfill_moves_bucket_without_changing_total(self, api):
        """PRD §3.2: "The open, fulfilled, and waived buckets always sum to the
        total; fulfilling or waiving moves a row between buckets without
        changing the total."

        Design: Difficulty/compensating_invariant/obligation_bucket_total_conservation
        """
        cp, nda, ids = self._setup_nda_with_three_obligations(api)
        validate_success(api.transition_obligation(
            ids[0], {"to_status": "FULFILLED"}, make_counterparty_rep_headers(cp["id"])
        ))
        nda_now = validate_success(api.get_nda(nda["id"], IP))
        assert nda_now["obligations_total_count"] == 3
        assert nda_now["obligations_open_count"] == 2, \
            "fulfill moved one row out of the open bucket; total conserved"
        assert_nda_obligation_bucket_invariant(nda_now)

    def test_fulfill_waive_escalate_conserves_total(self, api):
        """PRD §3.2: "Each agreement tracks four computed obligation counters:
        `obligations_total_count` over all of its obligations,
        `obligations_open_count` over those in `PENDING`, `OVERDUE`, or
        `ESCALATED`, `obligations_fulfilled_count`, and
        `obligations_waived_count`. The open, fulfilled, and waived buckets
        always sum to the total; fulfilling or waiving moves a row between
        buckets without changing the total."

        Design: Difficulty/compensating_invariant/obligation_bucket_total_conservation
        """
        cp, nda, ids = self._setup_nda_with_three_obligations(api)
        validate_success(api.transition_obligation(
            ids[0], {"to_status": "FULFILLED"}, make_counterparty_rep_headers(cp["id"])
        ))
        validate_success(api.transition_obligation(ids[1], {"to_status": "WAIVED"}, IP))
        api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
        validate_success(api.run_sweep(IP))
        validate_success(api.transition_obligation(ids[2], {"to_status": "ESCALATED"}, IP))
        nda_now = validate_success(api.get_nda(nda["id"], IP))
        assert nda_now["obligations_total_count"] == 3
        assert nda_now["obligations_open_count"] == 1, "ESCALATED stays open"
        assert nda_now["obligations_fulfilled_count"] == 1
        assert nda_now["obligations_waived_count"] == 1
        assert_nda_obligation_bucket_invariant(nda_now)
