"""Long propagation chains: one refusal, and one clock movement.

A registry rejection travels from a submission row all the way to a voided insurance
document inside a single request; a certificate expiry needs two compliance runs to travel
the same kind of distance.
"""
from test_helpers import (
    assert_dram_shop_document,
    assert_employer_location,
    assert_posture_matches_grace_inclusive_rate,
    assert_same_instant,
    assert_server_assignment,
    assignments_at_location,
    get_account,
    get_certificate_row,
    get_location,
    get_server,
    list_dram_shop_documents_for,
    run_compliance,
    set_clock,
    setup_certified_server_at_location,
    setup_documented_employer,
    transmit_and_reject,
)

TRANSMIT_CLOCK = "2026-08-20T10:00:00Z"
EXPIRY_INSTANT = "2028-08-10T18:30:00Z"
GRACE_END_INSTANT = "2028-09-09T18:30:00Z"
TWO_LOCATIONS = [
    {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
    {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
]


def _reject_the_registry_record():
    scenario = setup_documented_employer(location_specs=TWO_LOCATIONS)
    set_clock(TRANSMIT_CLOCK)
    submission = transmit_and_reject(scenario["certificate"]["id"], "NAME_MISMATCH")
    return scenario, submission


class TestRegistryRejectionCascade:
    def test_the_refusal_suspends_the_certificate_and_restricts_the_holder(self, api):
        """PRD §3.7: "A rejected result moves the submission `TRANSMITTED → REJECTED` and
        requires a `rejection_code` that is supplied and not `NONE`; the vocabulary is
        `DUPLICATE_SERVER_RECORD`, `INVALID_COURSE_APPROVAL` and `NAME_MISMATCH` alongside the
        default `NONE`."
        PRD §3.7: "The cascade then runs in four hops. The certificate's `registry_state` moves
        `SUBMITTED → RESUBMIT_REQUIRED`."
        PRD §3.7: "Because the registry refused the record, the certificate's `validity_state`
        moves to `SUSPENDED` — reachable from `ACTIVE` or `GRACE`, and only where the
        jurisdiction actually requires registry submission."
        PRD §3.7: "Because the governing certificate is now `SUSPENDED`, stage one of the
        recompute chain sets the holder's `work_eligibility` to `RESTRICTED` and stamps
        `restricted_since`."

        Design: Difficulty/transitive_cascade/registry_rejection_cascades_six_hops_to_dram_shop_document_void
        """
        scenario, submission = _reject_the_registry_record()

        assert submission["submission_state"] == "REJECTED"
        assert submission["rejection_code"] == "NAME_MISMATCH"
        assert_same_instant(submission["acknowledged_at"], TRANSMIT_CLOCK, "acknowledged_at")

        certificate = get_certificate_row(scenario["certificate"]["id"])
        assert certificate["registry_state"] == "RESUBMIT_REQUIRED"
        assert certificate["validity_state"] == "SUSPENDED", (
            "the refusal suspends the card itself, got "
            f"{certificate['validity_state']}")

        server = get_server(scenario["server"]["id"])
        assert server["work_eligibility"] == "RESTRICTED"
        assert_same_instant(server["restricted_since"], TRANSMIT_CLOCK, "restricted_since")

    def test_the_refusal_reaches_the_staffed_location_and_voids_the_insurance_document(
            self, api):
        """PRD §3.7: "And because the server is `RESTRICTED`, stage two moves each of their
        assignments at mandated locations to `WORK_RESTRICTED` with `restriction_reason`
        `REGISTRY_SUSPENDED`, after which stages three and four recompute the location and
        account metrics."
        PRD §3.8: "`ACTIVE → WORK_RESTRICTED` stamps `restricted_at`, sets
        `restriction_reason` per cause, raises the location's `restricted_server_count` by one
        and recomputes both rates — but leaves `assigned_server_count` untouched, because
        restricting a server does not remove them from the payroll."
        PRD §3.8: "Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above
        but below 95.00, and `NON_COMPLIANT` below 80.00."
        PRD §3.9: "Stage five then voids documentation: an account's `ISSUED` document moves to
        `VOIDED` with `void_reason` `COMPLIANCE_RATE_FELL_BELOW_FLOOR` when the recomputed
        `account_compliance_rate_pct` is below 80.00, and with `void_reason`
        `COVERAGE_PERIOD_ENDED` when the clock has reached the document's
        `coverage_period_end`; either way the account's `dram_shop_discount_status` becomes
        `EXPIRED`."
        PRD §3.8: "When `assigned_server_count` is zero — an empty location has nothing out of
        compliance — both rates read 100.00."

        Design: Difficulty/transitive_cascade/registry_rejection_cascades_six_hops_to_dram_shop_document_void
        """
        scenario, submission = _reject_the_registry_record()

        staffed = assignments_at_location(scenario["locations"][0]["id"])[0]
        assert_server_assignment(staffed)
        assert staffed["assignment_state"] == "WORK_RESTRICTED"
        assert staffed["restriction_reason"] == "REGISTRY_SUSPENDED"
        assert_same_instant(staffed["restricted_at"], TRANSMIT_CLOCK, "restricted_at")

        location_a = get_location(scenario["locations"][0]["id"])
        assert_employer_location(location_a)
        assert location_a["assigned_server_count"] == 1, (
            "restriction does not remove the server from the payroll, got "
            f"{location_a['assigned_server_count']}")
        assert location_a["restricted_server_count"] == 1
        assert location_a["compliance_rate_strict_pct"] == 0.00
        assert location_a["compliance_rate_grace_inclusive_pct"] == 0.00
        assert location_a["compliance_posture"] == "NON_COMPLIANT"
        assert_posture_matches_grace_inclusive_rate(location_a)

        location_b = get_location(scenario["locations"][1]["id"])
        assert location_b["compliance_rate_strict_pct"] == 100.00, (
            "the unstaffed sibling location is untouched, got "
            f"{location_b['compliance_rate_strict_pct']}")
        assert location_b["compliance_posture"] == "COMPLIANT"

        account = get_account(scenario["account"]["id"])
        assert account["account_compliance_rate_pct"] == 0.00
        assert account["dram_shop_discount_status"] == "EXPIRED"

        document = [d for d in list_dram_shop_documents_for(account["id"])
                    if d["id"] == scenario["document"]["id"]][0]
        assert_dram_shop_document(document)
        assert document["document_state"] == "VOIDED"
        assert document["void_reason"] == "COMPLIANCE_RATE_FELL_BELOW_FLOOR"
        assert document["discount_credit_cents"] == 607917, (
            "the certified credit is frozen at issuance and the void does not recompute it, "
            f"got {document['discount_credit_cents']}")


class TestEpochDrivenLapseCascade:
    def test_the_first_run_only_reaches_grace_and_leaves_the_assignment_alone(self, api):
        """PRD §3.9: "Each certificate is evaluated exactly once per run and receives **at
        most one** validity transition, so a certificate whose expiry and whose whole grace
        window have both already elapsed needs two runs to reach `LAPSED` — `ACTIVE → GRACE` on
        the first run and `GRACE → LAPSED` on the second."
        PRD §3.9: "A `GRACE` certificate moves its holder `ELIGIBLE → GRACE`, and assignments
        stay `ACTIVE` — servers in grace may still work."
        PRD §3.9: "Assignments moving `ACTIVE → WORK_RESTRICTED` increment
        `assignments_restricted_count`; assignments moving `WORK_RESTRICTED → ACTIVE` increment
        `assignments_restored_count`."
        PRD §3.9: "Each reminder raises `reminder_sent_count` by one and stamps
        `last_reminder_at` from the clock, and reminders stop once `reminder_sent_count` reaches
        2."

        Design: Difficulty/transitive_cascade/epoch_driven_certificate_lapse_cascades_four_hops_across_two_runs
        """
        scenario = setup_certified_server_at_location(
            location_specs=[{"location_name": "Alamo Taproom",
                             "annual_premium_cents": 4821734}],
            sponsor_enrollment=False)

        set_clock(GRACE_END_INSTANT)
        first_run = run_compliance()
        assert first_run["certificates_graced_count"] == 1
        assert first_run["certificates_lapsed_count"] == 0, (
            "one validity transition per certificate per run, got "
            f"{first_run['certificates_lapsed_count']}")
        assert first_run["assignments_restricted_count"] == 0
        assert first_run["reminders_sent_count"] == 1

        assert get_certificate_row(scenario["certificate"]["id"])["validity_state"] == "GRACE"
        assert get_server(scenario["server"]["id"])["work_eligibility"] == "GRACE"
        staffed = assignments_at_location(scenario["locations"][0]["id"])[0]
        assert staffed["assignment_state"] == "ACTIVE"
        assert staffed["restriction_reason"] == "NONE"

    def test_the_second_run_lapses_the_card_and_the_restriction_reaches_the_account(self, api):
        """PRD §3.9: "A certificate whose `validity_state` is `GRACE` and where the clock has
        reached `expires_at` plus the jurisdiction's `renewal_grace_days` moves `GRACE →
        LAPSED`, incrementing `certificates_lapsed_count`."
        PRD §3.9: "A `LAPSED` certificate moves its holder `GRACE → RESTRICTED`, stamping
        `restricted_since`."
        PRD §3.9: "Because the server is `RESTRICTED`, phase six moves each of their
        assignments at mandated locations from `ACTIVE` to `WORK_RESTRICTED` with
        `restriction_reason` `CERTIFICATE_LAPSED`."
        PRD §3.9: "Stage four recomputes each affected account's `location_count` and
        `account_compliance_rate_pct`, promoting `dram_shop_discount_status` from
        `NOT_DOCUMENTED` to `ELIGIBLE` where the recomputed rate is at least 80.00."
        PRD §3.9: "Stage five then voids documentation: an account's `ISSUED` document moves to
        `VOIDED` with `void_reason` `COMPLIANCE_RATE_FELL_BELOW_FLOOR` when the recomputed
        `account_compliance_rate_pct` is below 80.00, and with `void_reason`
        `COVERAGE_PERIOD_ENDED` when the clock has reached the document's
        `coverage_period_end`; either way the account's `dram_shop_discount_status` becomes
        `EXPIRED`. `documents_voided_count` totals the voidings."

        Design: Difficulty/transitive_cascade/epoch_driven_certificate_lapse_cascades_four_hops_across_two_runs
        """
        scenario = setup_certified_server_at_location(
            location_specs=[{"location_name": "Alamo Taproom",
                             "annual_premium_cents": 4821734}],
            sponsor_enrollment=False)

        set_clock(EXPIRY_INSTANT)
        run_compliance()
        set_clock(GRACE_END_INSTANT)
        second_run = run_compliance()

        assert second_run["certificates_lapsed_count"] == 1
        assert second_run["certificates_graced_count"] == 0
        assert second_run["assignments_restricted_count"] == 1
        assert second_run["reminders_sent_count"] == 0, (
            "the single reminder was already spent on the first run, got "
            f"{second_run['reminders_sent_count']}")
        assert second_run["documents_voided_count"] == 0, (
            "this account never held an issued document, got "
            f"{second_run['documents_voided_count']}")

        assert get_certificate_row(scenario["certificate"]["id"])["validity_state"] == "LAPSED"
        server = get_server(scenario["server"]["id"])
        assert server["work_eligibility"] == "RESTRICTED"
        assert_same_instant(server["restricted_since"], GRACE_END_INSTANT,
                            "restricted_since")

        staffed = assignments_at_location(scenario["locations"][0]["id"])[0]
        assert staffed["assignment_state"] == "WORK_RESTRICTED"
        assert staffed["restriction_reason"] == "CERTIFICATE_LAPSED"

        location = get_location(scenario["locations"][0]["id"])
        assert location["assigned_server_count"] == 1
        assert location["restricted_server_count"] == 1
        assert location["compliance_rate_strict_pct"] == 0.00
        assert location["compliance_rate_grace_inclusive_pct"] == 0.00
        assert location["compliance_posture"] == "NON_COMPLIANT"

        account = get_account(scenario["account"]["id"])
        assert account["account_compliance_rate_pct"] == 0.00
        assert account["dram_shop_discount_status"] == "ELIGIBLE", (
            "the roll-up promoted the account while the rate was still 100.00 and nothing "
            f"has demoted it since, got {account['dram_shop_discount_status']}")
