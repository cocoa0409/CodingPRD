"""Customer standing dimensions evolve independently and in parallel."""
from test_helpers import (
    create_approved_certificate,
    create_onboarded_customer,
    open_campaign_with_samples,
    setup_tenant_config,
    validate_success,
)


class TestCustomerParallelStandings:
    def test_customer_holds_three_standings_simultaneously(self, api, auditor_headers):
        """PRD §3.2: "Every customer carries three independent, parallel standing dimensions. Transitions on one dimension never preclude or imply transitions on the others; all three are recomputed continuously as certificates, samples, and remediation actions change."
        PRD §3.2: "When every footprint state has at least one approved, unexpired certificate whose `ship_to_state` covers it, standing moves `PARTIAL` → `COMPLIANT`, again recomputing `blocked_exposure_cents`."
        PRD §3.2: "When any approved certificate for the customer comes within the renewal window — that is, the number of days from the current logical day to the certificate's `expiration_date` is forty-five or fewer, a certificate expiring exactly forty-five days out included — standing moves `CURRENT` → `RENEWAL_DUE`."

        Design: Difficulty/non_linear_state_machine/customer_parallel_state_dimensions
        """
        # Certificate expires on day 30 (2026-08-01 + 30 days), inside the
        # forty-five-day renewal window already at day 0.
        tenant = setup_tenant_config(rule_specs=[{
            "state_code": "CA", "validity_window_days": 30, "anchor_rule": "EFFECTIVE_DATE",
        }])
        cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="CA")
        create_approved_certificate(
            tenant["id"], cust["id"],
            cert_overrides={"signed_date": "2026-08-01", "effective_date": "2026-08-01"},
            version_overrides={"signed_date": "2026-08-01", "effective_date": "2026-08-01"})
        open_campaign_with_samples(tid=tenant["id"], population_state_filter=["CA"],
                                   floor_sample_size=1)

        after = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        assert after["cert_standing"] == "COMPLIANT", (
            "the single footprint state CA is covered by an approved certificate")
        assert after["audit_standing"] == "SAMPLED", (
            "the audit sample row naming this customer drives audit_standing")
        assert after["collection_standing"] == "RENEWAL_DUE", (
            "expiration 30 days out is within the 45-day renewal window")

    def test_parallel_standings_are_per_customer_independent(self, api, auditor_headers):
        """PRD §3.2: "Every customer carries three independent, parallel standing dimensions. Transitions on one dimension never preclude or imply transitions on the others; all three are recomputed continuously as certificates, samples, and remediation actions change."
        PRD §3.2: "A customer starts at `NOT_UNDER_AUDIT` and moves to `SAMPLED` the moment an audit sample row naming the customer is created during campaign sampling."

        Design: Difficulty/non_linear_state_machine/customer_parallel_state_dimensions
        """
        tenant = setup_tenant_config(rule_specs=[
            {"state_code": "CA", "validity_window_days": 30, "anchor_rule": "EFFECTIVE_DATE"},
            {"state_code": "TX", "validity_window_days": 0, "anchor_rule": "EFFECTIVE_DATE"},
        ])
        # C1: CA cert expiring at day 30 -> COMPLIANT + RENEWAL_DUE once approved.
        c1 = create_onboarded_customer(tid=tenant["id"], external_ref="C1",
                                       legal_name="Cust 1", primary_ship_to_state="CA")
        create_approved_certificate(
            tenant["id"], c1["id"], cert_overrides={"ship_to_state": "CA",
                                                    "signed_date": "2026-08-01",
                                                    "effective_date": "2026-08-01"},
            version_overrides={"signed_date": "2026-08-01", "effective_date": "2026-08-01"})
        # C2: TX cert that never expires -> COMPLIANT + CURRENT.
        c2 = create_onboarded_customer(tid=tenant["id"], external_ref="C2",
                                       legal_name="Cust 2", primary_ship_to_state="TX")
        create_approved_certificate(
            tenant["id"], c2["id"], cert_overrides={"ship_to_state": "TX"},
            version_overrides={"file_uri": "s3://c2.pdf"})

        # Population restricted to CA: only C1's certificate is sampled.
        open_campaign_with_samples(tid=tenant["id"], population_state_filter=["CA"],
                                   floor_sample_size=1)

        c1_after = validate_success(api.get_customer(tenant["id"], c1["id"], auditor_headers), 200)
        assert (c1_after["cert_standing"], c1_after["audit_standing"], c1_after["collection_standing"]) == (
            "COMPLIANT", "SAMPLED", "RENEWAL_DUE")

        c2_after = validate_success(api.get_customer(tenant["id"], c2["id"], auditor_headers), 200)
        assert (c2_after["cert_standing"], c2_after["audit_standing"], c2_after["collection_standing"]) == (
            "COMPLIANT", "NOT_UNDER_AUDIT", "CURRENT"), (
            "sampling C1 must not disturb C2's audit standing, and C2's never-expiring "
            "certificate keeps its collection standing CURRENT")
