"""The two multi-step money formulas whose evaluation order is pinned.

The issuance charge has six ordered steps with rounding at three of them; the
remediation penalty rounds every certificate's share before the batch total is
summed.
"""

import pytest

from test_helpers import (
    DCV_METHOD_DNS_TXT,
    DCV_METHOD_HTTP_TOKEN,
    INCIDENT_DOMAIN_MISISSUANCE,
    INCIDENT_PROCEDURAL,
    INCIDENT_REMEDIATED,
    REASON_PRIVILEGE_WITHDRAWN,
    REASON_UNSPECIFIED,
    REVOCATION_STATUS_REVOKED,
    SUBSCRIBER_ACTIVE,
    VALIDATION_TYPE_EV,
    VALIDATION_TYPE_OV,
    VETTING_LEVEL_EV,
    VETTING_LEVEL_OV,
    advance_clock,
    approve_vetting_file,
    assert_counters,
    assert_instant_equals,
    attested_ceremony,
    build_environment,
    cleared_request,
    create_partition,
    create_profile,
    create_subscriber,
    disclosure_payload,
    ev_profile_payload,
    get_success_data,
    incident_payload,
    issuance_charge_breakdown,
    issue_from_request,
    ov_profile_payload,
    profile_payload,
    read_certificate,
    read_incident,
    read_request,
    read_subscriber,
    seconds_between,
    subscriber_payload,
    users,
    validated_authorization,
)


class TestIssuanceChargeSixPinnedSteps:
    def test_band_from_the_pre_discount_subtotal_and_unit_rounded_first(self, client):
        """Two domains at 10085 cents on an EV profile settle on 56729 cents.

        PRD 3.5: "The band is keyed on this pre-discount, pre-expedite subtotal
        and is never re-derived afterwards, even when the discounted subtotal or
        the final total would fall in a different band."
        PRD 3.5: "Rounding happens at the first, fourth and fifth steps only —
        rounding the base-fee-times-multiplier-times-domains product in one shot
        instead yields a different and incorrect subtotal whenever the unit price
        has a fractional part."

        Design: Difficulty/combinatorial_formula/issuance_charge_pinned_six_step_evaluation_order
        """
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
        validated_authorization(
            client, subscriber["id"], profile["id"], "a.example.com", DCV_METHOD_DNS_TXT
        )
        validated_authorization(
            client,
            subscriber["id"],
            profile["id"],
            "b.example.com",
            DCV_METHOD_HTTP_TOKEN,
        )
        partition = create_partition(client)
        ceremony = attested_ceremony(
            client,
            partition["id"],
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-02T04:00:00Z",
            attestation_valid_days=120,
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

        breakdown = issuance_charge_breakdown(10085, VALIDATION_TYPE_EV, 2, True)
        assert breakdown["unit_cents"] == 25213, "the unit price rounds up from 25212.5"
        assert breakdown["subtotal_cents"] == 50426
        assert breakdown["discount_percent"] == 10
        assert breakdown["discounted_cents"] == 45383
        assert breakdown["total_cents"] == 56729

        assert request["projected_charge_cents"] == 56729, (
            "projected_charge_cents is "
            f"{request['projected_charge_cents']}, expected 56729"
        )
        assert request["projected_charge_cents"] != 63033, (
            "63033 is what skipping the volume discount, or charging the "
            "expedite fee on the pre-discount subtotal, would produce"
        )
        assert request["projected_charge_cents"] != 56728, (
            "56728 is what rounding 10085 * 2.5 * 2 in one shot would produce "
            "instead of rounding the 25213 unit price first"
        )

        certificate = issue_from_request(client, request["id"], ceremony["id"])
        assert certificate["charged_amount_cents"] == 56729, (
            "issuance re-runs the identical pinned order, so "
            f"56729, found {certificate['charged_amount_cents']}"
        )

        reread = read_subscriber(client, subscriber["id"])
        assert reread["outstanding_balance_cents"] == 56729
        assert (
            reread["outstanding_balance_cents"] <= reread["credit_limit_cents"]
        ), "the debit must stay inside the credit limit"

    def test_unit_price_is_rounded_before_the_domain_count_multiplies_it(self, client):
        """A half-cent unit price on three domains proves the rounding order.

        PRD 3.5: "First, the per-domain unit price is the profile's
        `base_fee_cents` multiplied by the validation-tier multiplier — 1.0 for a
        `DV` profile, 1.5 for an `OV` profile and 2.5 for an `EV` profile — with
        the product rounded half up to a whole cent at this point, before any
        multiplication by the domain count."

        Design: Difficulty/combinatorial_formula/issuance_charge_pinned_six_step_evaluation_order
        """
        domains = ["a.example.org", "b.example.org", "c.example.org"]
        environment = build_environment(
            client,
            profile_payload=ov_profile_payload(base_fee_cents=3333),
            subscriber_payload=subscriber_payload(credit_limit_cents=1_000_000),
            domains=domains,
            vetting_level=VETTING_LEVEL_OV,
        )

        breakdown = issuance_charge_breakdown(3333, VALIDATION_TYPE_OV, 3, False)
        assert breakdown["unit_cents"] == 5000, (
            "3333 * 1.5 is 4999.5, which rounds half up to 5000"
        )
        assert breakdown["total_cents"] == 15000

        request = cleared_request(
            client, environment.subscriber_id, environment.profile_id, domains
        )
        assert request["projected_charge_cents"] == 15000, (
            "projected_charge_cents is "
            f"{request['projected_charge_cents']}, expected 15000"
        )
        assert request["projected_charge_cents"] != 14999, (
            "14999 is what rounding the 14998.5 product of fee, multiplier and "
            "domain count would produce"
        )

        certificate = issue_from_request(
            client, request["id"], environment.ceremony_id
        )
        assert certificate["charged_amount_cents"] == 15000
        assert read_subscriber(client, environment.subscriber_id)[
            "outstanding_balance_cents"
        ] == 15000


def _two_short_lived_certificates(client, category):
    """Two certificates whose windows are 4000 and 8000 seconds long."""
    profile = create_profile(
        client,
        profile_payload(
            name="dv-short-1",
            max_validity_days=90,
            dcv_reuse_days=1,
            max_dcv_reuse_count=1,
            allowed_dcv_methods=[DCV_METHOD_DNS_TXT],
            required_sct_count=1,
            base_fee_cents=8000,
            crl_trigger_threshold=100,
            max_crl_validity_hours=24,
        ),
    )
    subscriber = create_subscriber(
        client, subscriber_payload(credit_limit_cents=1_000_000)
    )
    validated_authorization(
        client, subscriber["id"], profile["id"], "a.example.net", DCV_METHOD_DNS_TXT
    )
    partition = create_partition(client)
    ceremony = attested_ceremony(
        client,
        partition["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T00:30:00Z",
        attestation_valid_days=30,
    )
    first_request = cleared_request(
        client, subscriber["id"], profile["id"], ["a.example.net"]
    )

    advance_clock(client, "2026-08-01T02:00:00Z")
    validated_authorization(
        client, subscriber["id"], profile["id"], "b.example.net", DCV_METHOD_DNS_TXT
    )
    second_request = cleared_request(
        client, subscriber["id"], profile["id"], ["b.example.net"]
    )

    advance_clock(client, "2026-08-01T22:53:20Z")
    first = issue_from_request(client, first_request["id"], ceremony["id"])
    advance_clock(client, "2026-08-01T23:46:40Z")
    second = issue_from_request(client, second_request["id"], ceremony["id"])

    incident = get_success_data(
        client.create_incident(
            incident_payload(
                profile["id"],
                category=category,
                scope_issued_from="2026-08-01T00:00:00Z",
                scope_issued_to="2026-08-02T00:00:00Z",
                subscriber_id=subscriber["id"],
                title="two certificates issued from an unvetted CAA state",
            ),
            users.COMPLIANCE_AUDITOR,
        ),
        201,
    )
    get_success_data(
        client.disclose_incident(
            incident["id"], disclosure_payload(), users.COMPLIANCE_AUDITOR
        )
    )
    advance_clock(client, "2026-08-01T23:50:01Z")
    return profile, subscriber, incident, first, second


class TestRemediationPenaltyRoundsPerCertificate:
    def test_two_certificate_batch_rounds_each_share_before_summing(self, client):
        """299.5 and 1949.75 become 300 and 1950, totalling 2250 rather than 2249.

        PRD 3.9: "The rounding order is pinned: each per-certificate penalty is
        rounded half up to whole cents *before* entering the sum, and the batch
        total is the sum of those rounded amounts."

        Design: Difficulty/combinatorial_formula/remediation_penalty_round_per_certificate_then_sum
        """
        profile, subscriber, incident, first, second = _two_short_lived_certificates(
            client, INCIDENT_DOMAIN_MISISSUANCE
        )
        assert_instant_equals(
            first["not_after"], "2026-08-02T00:00:00Z", "first not_after"
        )
        assert seconds_between(first["not_before"], first["not_after"]) == 4000
        assert_instant_equals(
            second["not_after"], "2026-08-02T02:00:00Z", "second not_after"
        )
        assert seconds_between(second["not_before"], second["not_after"]) == 8000

        batch = get_success_data(
            client.mass_revoke(incident["id"], users.REVOCATION_OFFICER)
        )

        assert batch["penalty_total_cents"] == 2250, (
            "the residuals 599/4000 and 7799/8000 at weight 2.0 give 299.5 and "
            "1949.75, which round to 300 and 1950 for a total of 2250, found "
            f"{batch['penalty_total_cents']}"
        )
        assert batch["penalty_total_cents"] != 2249, (
            "2249 is what summing 299.5 + 1949.75 and rounding once would produce"
        )
        assert_counters(batch, revoked_certificate_count=2, remaining_scope_count=0)
        assert batch["state"] == INCIDENT_REMEDIATED

        for certificate_id in (first["id"], second["id"]):
            reread = read_certificate(client, certificate_id)
            assert reread["revocation_status"] == REVOCATION_STATUS_REVOKED
            assert reread["revocation_reason_code"] == REASON_PRIVILEGE_WITHDRAWN, (
                "a domain misissuance batch records PRIVILEGE_WITHDRAWN"
            )

        assert (
            read_subscriber(client, subscriber["id"])["account_status"]
            == SUBSCRIBER_ACTIVE
        ), "only a key-compromise batch terminates the subscriber"

    def test_lighter_category_weight_still_rounds_each_share_first(self, client):
        """At weight 0.5 the two shares are 74.875 and 487.4375, totalling 562.

        PRD 3.9: "The per-certificate penalty is 1000 cents multiplied by the
        category penalty weight — 3.0 for `KEY_COMPROMISE`, 2.0 for
        `DOMAIN_MISISSUANCE`, 1.5 for `ORG_MISISSUANCE`, 0.5 for `PROCEDURAL` —
        multiplied by that residual fraction."

        Design: Difficulty/combinatorial_formula/remediation_penalty_round_per_certificate_then_sum
        """
        profile, subscriber, incident, first, second = _two_short_lived_certificates(
            client, INCIDENT_PROCEDURAL
        )

        batch = get_success_data(
            client.mass_revoke(incident["id"], users.REVOCATION_OFFICER)
        )

        assert batch["penalty_total_cents"] == 562, (
            "74.875 rounds to 75 and 487.4375 rounds to 487, so 562, found "
            f"{batch['penalty_total_cents']}"
        )
        assert batch["penalty_total_cents"] != 561, (
            "561 is what summing 74.875 + 487.4375 and rounding once would produce"
        )
        assert read_certificate(client, first["id"])["revocation_reason_code"] == (
            REASON_UNSPECIFIED
        ), "a procedural batch records UNSPECIFIED"
        assert read_incident(client, incident["id"])["penalty_total_cents"] == 562, (
            "the batch total is what accumulates on the incident"
        )
