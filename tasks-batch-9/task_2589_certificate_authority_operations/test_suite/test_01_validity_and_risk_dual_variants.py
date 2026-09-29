"""Two calculations that each have a projected variant and a final variant.

The certificate validity window is forecast at validation clearance and then
recomputed for real at issuance; a subscriber's risk is scored one way for
day-to-day operations and another way when an audit opinion is filed.
"""

import pytest

from test_helpers import (
    AUDIT_UNQUALIFIED,
    CHECK_PASSED,
    DCV_METHOD_DNS_TXT,
    DCV_METHOD_HTTP_TOKEN,
    DIMENSION_AUTHORITY,
    DIMENSION_CALLBACK,
    DIMENSION_REGISTRY,
    INCIDENT_CLOSED,
    INCIDENT_DOMAIN_MISISSUANCE,
    INCIDENT_DISCLOSED,
    INCIDENT_KEY_COMPROMISE,
    LIFECYCLE_PREISSUANCE,
    PROFILE_STATE_ACTIVE,
    REVOCATION_STATUS_NONE,
    ROOT_PROGRAM_MOZILLA,
    SEVERITY_MINOR,
    VETTING_LEVEL_EV,
    advance_clock,
    approve_vetting_file,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    audit_final_risk_score,
    cleared_request,
    create_partition,
    create_profile,
    create_subscriber,
    disclosure_payload,
    ev_profile_payload,
    finding_payload,
    get_success_data,
    incident_payload,
    issue_from_request,
    operational_risk_score,
    read_certificate,
    read_profile,
    read_request,
    read_subscriber,
    subscriber_payload,
    validated_authorization,
    attested_ceremony,
    users,
)


def _ev_two_domain_setup(client, attestation_valid_days):
    """An EV profile, an EV-vetted subscriber, two proofs and a ceremony."""
    profile = create_profile(
        client,
        ev_profile_payload(
            name="ev-global-1",
            max_validity_days=90,
            dcv_reuse_days=30,
            max_dcv_reuse_count=2,
            org_vetting_reuse_days=60,
            allowed_dcv_methods=[DCV_METHOD_DNS_TXT, DCV_METHOD_HTTP_TOKEN],
            required_sct_count=2,
            base_fee_cents=10085,
            crl_trigger_threshold=100,
            max_crl_validity_hours=24,
        ),
    )
    subscriber = create_subscriber(
        client, subscriber_payload(credit_limit_cents=10_000_000)
    )
    approve_vetting_file(client, subscriber["id"], VETTING_LEVEL_EV)
    # Both proofs are answered while the clock is still at its default instant,
    # so each one expires dcv_reuse_days later, on 2026-08-31T00:00:00Z.
    auth_a = validated_authorization(
        client, subscriber["id"], profile["id"], "a.example.com", DCV_METHOD_DNS_TXT
    )
    auth_b = validated_authorization(
        client, subscriber["id"], profile["id"], "b.example.com", DCV_METHOD_HTTP_TOKEN
    )
    partition = create_partition(client)
    ceremony = attested_ceremony(
        client,
        partition["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T04:00:00Z",
        attestation_valid_days=attestation_valid_days,
    )
    return profile, subscriber, ceremony, auth_a, auth_b


class TestValidityWindowProjectedThenFinal:
    def test_final_window_is_floored_by_the_authorization_reuse_expiry(self, client):
        """The reuse floor binds at issuance although the forecast ignored it.

        PRD 3.5: "This projection deliberately ignores both the
        domain-authorization reuse floor and the ceremony attestation cap; it is
        a forecast of what the request could get, not a promise."
        PRD 3.7: "`not_after` is the earliest of those three."

        Design: Difficulty/dual_variant_calc/validity_window_projected_at_clearance_vs_final_at_issuance
        """
        profile, subscriber, ceremony, auth_a, auth_b = _ev_two_domain_setup(
            client, attestation_valid_days=120
        )
        assert_instant_equals(
            auth_a["expires_at"], "2026-08-31T00:00:00Z", "authorization expires_at"
        )
        assert_instant_equals(
            ceremony["attestation_expires_at"],
            "2026-11-30T04:00:00Z",
            "attestation_expires_at",
        )

        advance_clock(client, "2026-08-05T00:00:00Z")
        request = cleared_request(
            client,
            subscriber["id"],
            profile["id"],
            ["a.example.com", "b.example.com"],
            90,
            3072,
            True,
        )
        assert_instant_equals(
            request["projected_not_before"],
            "2026-08-05T00:00:00Z",
            "projected_not_before",
        )
        assert_instant_equals(
            request["projected_not_after"],
            "2026-11-03T00:00:00Z",
            "projected_not_after",
        )

        advance_clock(client, "2026-08-10T00:00:00Z")
        certificate = issue_from_request(client, request["id"], ceremony["id"])

        assert_instant_equals(
            certificate["not_before"], "2026-08-10T00:00:00Z", "not_before"
        )
        assert_instant_equals(
            certificate["not_after"], "2026-08-31T00:00:00Z", "not_after"
        )
        assert certificate["not_after"] != request["projected_not_after"], (
            "the final window must land earlier than the forecast when the "
            "authorization reuse floor binds"
        )
        assert certificate["validity_days_final"] == 21, (
            "validity_days_final is "
            f"{certificate['validity_days_final']}, expected the 21 whole days "
            "from 2026-08-10T00:00:00Z to 2026-08-31T00:00:00Z"
        )
        assert certificate["dcv_methods_used"] == [
            DCV_METHOD_DNS_TXT,
            DCV_METHOD_HTTP_TOKEN,
        ], "dcv_methods_used must list the distinct consumed methods, sorted ascending"
        assert_certificate_dimensions(
            certificate, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
        )

    def test_final_window_is_floored_by_the_attestation_cap(self, client):
        """A short attestation becomes the binding candidate end instant.

        PRD 3.7: "Three candidate end instants are then computed: the profile
        cap, which is the issuance clock plus the capped span in days, where the
        capped span is again the lesser of the request's
        `requested_validity_days` and the profile's `max_validity_days`; the
        domain-authorization floor, which is the earliest `expires_at` among all
        the authorizations named in `consumed_authorization_ids`; and the
        attestation cap, which is the named ceremony's
        `attestation_expires_at`."

        Design: Difficulty/dual_variant_calc/validity_window_projected_at_clearance_vs_final_at_issuance
        """
        profile, subscriber, ceremony, _auth_a, _auth_b = _ev_two_domain_setup(
            client, attestation_valid_days=10
        )
        assert_instant_equals(
            ceremony["attestation_expires_at"],
            "2026-08-12T04:00:00Z",
            "attestation_expires_at",
        )

        advance_clock(client, "2026-08-05T00:00:00Z")
        request = cleared_request(
            client,
            subscriber["id"],
            profile["id"],
            ["a.example.com", "b.example.com"],
            90,
            3072,
            True,
        )
        assert_instant_equals(
            request["projected_not_after"],
            "2026-11-03T00:00:00Z",
            "projected_not_after",
        )

        advance_clock(client, "2026-08-10T00:00:00Z")
        certificate = issue_from_request(client, request["id"], ceremony["id"])

        assert_instant_equals(
            certificate["not_after"],
            "2026-08-12T04:00:00Z",
            "not_after under a binding attestation cap",
        )
        assert certificate["validity_days_final"] == 2, (
            "validity_days_final discards the fractional day, so 2 days and "
            f"4 hours is 2, found {certificate['validity_days_final']}"
        )
        # The forecast on the request is a record of the clearance step and is
        # not rewritten by issuance.
        reread = read_request(client, request["id"])
        assert_instant_equals(
            reread["projected_not_after"],
            "2026-11-03T00:00:00Z",
            "projected_not_after after issuance",
        )


def _two_attributed_incidents(client, profile_id, subscriber_id, close_second):
    """One closed key-compromise incident and one domain-misissuance incident."""
    auditor = users.COMPLIANCE_AUDITOR
    first = get_success_data(
        client.create_incident(
            incident_payload(
                profile_id,
                category=INCIDENT_KEY_COMPROMISE,
                scope_issued_from="2026-07-01T00:00:00Z",
                scope_issued_to="2026-07-31T00:00:00Z",
                subscriber_id=subscriber_id,
                title="compromised issuing key material",
            ),
            auditor,
        ),
        201,
    )
    get_success_data(
        client.disclose_incident(first["id"], disclosure_payload(), auditor)
    )
    first = get_success_data(client.close_incident(first["id"], auditor))

    second = get_success_data(
        client.create_incident(
            incident_payload(
                profile_id,
                category=INCIDENT_DOMAIN_MISISSUANCE,
                scope_issued_from="2026-07-01T00:00:00Z",
                scope_issued_to="2026-07-31T00:00:00Z",
                subscriber_id=subscriber_id,
                title="wildcard issued outside validated scope",
            ),
            auditor,
        ),
        201,
    )
    get_success_data(
        client.disclose_incident(second["id"], disclosure_payload(), auditor)
    )
    if close_second:
        second = get_success_data(client.close_incident(second["id"], auditor))
    return first, second


def _opine_mozilla_audit(client, opinion_clock):
    auditor = users.COMPLIANCE_AUDITOR
    audit = get_success_data(
        client.create_audit(
            {
                "root_program": ROOT_PROGRAM_MOZILLA,
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-12-31T00:00:00Z",
            },
            auditor,
        ),
        201,
    )
    get_success_data(
        client.record_finding(
            audit["id"],
            finding_payload(
                SEVERITY_MINOR, "CRL publication log retained only 90 days"
            ),
            auditor,
        )
    )
    advance_clock(client, opinion_clock)
    return get_success_data(
        client.opine_audit(audit["id"], users.COMPLIANCE_AUDITOR_2)
    )


class TestSubscriberRiskOperationalThenAuditFinal:
    def test_closed_incident_is_dropped_operationally_but_readmitted_by_the_audit(
        self, client
    ):
        """Identical incident data, two different scores on the same subscriber.

        PRD 3.9: "There is no date filtering and no decay: a subscriber all of
        whose incidents are closed scores 0."
        PRD 3.9: "Each incident contributes its category weight multiplied by a
        closed multiplier of 0.5 when its `state` is `CLOSED` and 1.0 otherwise,
        multiplied by an age decay computed from the age in whole days between
        the incident's `discovered_at` and the logical clock at the moment of
        the opinion: the decay is 1 minus 0.1 for each completed 30-day step of
        that age, floored at 0.4, so an incident 89 days old decays to 0.8 and
        anything 180 days old or older sits at the 0.4 floor."

        Design: Difficulty/dual_variant_calc/subscriber_risk_operational_vs_audit_final_variant
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        _two_attributed_incidents(
            client, profile["id"], subscriber["id"], close_second=False
        )

        audit = _opine_mozilla_audit(client, "2026-10-01T00:00:00Z")

        expected_final = audit_final_risk_score(
            [
                {
                    "category": INCIDENT_KEY_COMPROMISE,
                    "discovered_at": "2026-08-01T00:00:00Z",
                    "closed": True,
                },
                {
                    "category": INCIDENT_DOMAIN_MISISSUANCE,
                    "discovered_at": "2026-08-01T00:00:00Z",
                    "closed": False,
                },
            ],
            "2026-10-01T00:00:00Z",
        )
        assert float(expected_final) == 36.00, (
            "the two incidents decay by 0.8 at 61 days of age, so the audit "
            f"score is 36.00, not {expected_final}"
        )

        reread = read_subscriber(client, subscriber["id"])
        assert reread["risk_score_operational"] == operational_risk_score(
            [INCIDENT_DOMAIN_MISISSUANCE]
        ), (
            "the operational score counts only the open domain-misissuance "
            f"incident, so 25, found {reread['risk_score_operational']}"
        )
        assert reread["risk_score_operational"] == 25
        assert reread["risk_score_audit_final"] == pytest.approx(36.00, abs=0.01), (
            "risk_score_audit_final is "
            f"{reread['risk_score_audit_final']}, expected 36.00"
        )
        assert reread["risk_score_audit_final"] != reread["risk_score_operational"], (
            "the two variants must disagree on this data"
        )

        assert audit["state"] == AUDIT_UNQUALIFIED
        assert_counters(audit, assessed_subscriber_count=1, retired_profile_count=0)
        assert read_profile(client, profile["id"])["status"] == PROFILE_STATE_ACTIVE, (
            "an unqualified opinion retires no profile"
        )

    def test_operational_score_reaches_zero_while_the_audit_score_does_not(
        self, client
    ):
        """Closing every incident empties one variant's input set but not the other's.

        PRD 3.9: "The score is the sum of category weights — 40 for
        `KEY_COMPROMISE`, 25 for `DOMAIN_MISISSUANCE`, 15 for
        `ORG_MISISSUANCE`, 5 for `PROCEDURAL` — over every incident attributed
        to that subscriber whose `state` is anything other than `CLOSED`, capped
        at 100 and carried as a whole integer in `risk_score_operational`."
        PRD 3.9: "Its input set is every incident attributed to the subscriber
        whose `discovered_at` falls inside the closed interval from
        `period_start` to `period_end` inclusive, regardless of state — so
        incidents the operational score discarded for being `CLOSED` re-enter
        here."

        Design: Difficulty/dual_variant_calc/subscriber_risk_operational_vs_audit_final_variant
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        first, second = _two_attributed_incidents(
            client, profile["id"], subscriber["id"], close_second=True
        )
        assert first["state"] == INCIDENT_CLOSED

        before_opinion = read_subscriber(client, subscriber["id"])
        assert before_opinion["risk_score_operational"] == 0, (
            "every attributed incident is closed, so the operational score is 0"
        )

        _opine_mozilla_audit(client, "2026-10-01T00:00:00Z")

        expected_final = audit_final_risk_score(
            [
                {
                    "category": INCIDENT_KEY_COMPROMISE,
                    "discovered_at": "2026-08-01T00:00:00Z",
                    "closed": True,
                },
                {
                    "category": INCIDENT_DOMAIN_MISISSUANCE,
                    "discovered_at": "2026-08-01T00:00:00Z",
                    "closed": True,
                },
            ],
            "2026-10-01T00:00:00Z",
        )
        assert float(expected_final) == 26.00, (
            f"both terms are halved and decayed by 0.8, so 26.00, not {expected_final}"
        )

        reread = read_subscriber(client, subscriber["id"])
        assert reread["risk_score_operational"] == 0
        assert reread["risk_score_audit_final"] == pytest.approx(26.00, abs=0.01), (
            "the closed incidents still contribute to the audit score, so "
            f"26.00, found {reread['risk_score_audit_final']}"
        )
