"""Two places where one input set feeds two different published answers.

Certificate renewal chooses between two expiry anchors, and a location publishes two
compliance rates side by side from the identical assignment set.
"""
from test_helpers import (
    TEST_USERS,
    assert_certificate,
    assert_certificate_number_format,
    assert_compliance_dashboard,
    assert_compliance_run,
    assert_same_instant,
    certificates_for_server,
    certify_one_server,
    complete_session,
    get_certificate_row,
    get_location,
    get_server,
    set_clock,
    setup_certified_server_at_location,
    setup_training_base,
    stage_second_class_ready_to_complete,
    validate_paginated,
    validate_success,
)

CERT_EXPIRY_INSTANT = "2028-08-10T18:30:00Z"


class TestAnniversaryAnchoredRenewal:
    def test_renewal_of_an_active_card_anchors_on_the_prior_expiry(self, api):
        """PRD §3.7: "**`ANNIVERSARY_ANCHORED`** applies when the prior certificate's
        `validity_state` is `ACTIVE` (an early renewal) or `GRACE` (a renewal inside the grace
        window)."
        PRD §3.7: "`expires_at` is the **prior certificate's** `expires_at` advanced by
        `certificate_validity_months` months."
        PRD §3.7: "`issued_at` is the completion instant read from the logical clock."

        Design: Difficulty/dual_variant_calc/certificate_anniversary_anchored_renewal_preserves_original_expiry_month
        """
        base = setup_training_base(
            jurisdiction_overrides={"certificate_validity_months": 24})
        walk = certify_one_server(base)
        first = walk["certificate"]
        assert_same_instant(first["expires_at"], CERT_EXPIRY_INSTANT,
                            "the first certificate's expires_at")

        staged = stage_second_class_ready_to_complete(base, walk["server"])
        completed = validate_success(api.complete_class_session(
            staged["session"]["id"], base["trainer_headers"]), 200)
        assert completed["session_status"] == "COMPLETED"

        renewal = [c for c in certificates_for_server(walk["server"]["id"])
                   if c["id"] != first["id"]][0]
        assert_certificate(renewal)
        assert renewal["expiry_anchor_mode"] == "ANNIVERSARY_ANCHORED", (
            "renewing a still-ACTIVE card anchors on the anniversary, got "
            f"{renewal['expiry_anchor_mode']}")
        assert_same_instant(renewal["expires_at"], "2030-08-10T18:30:00Z",
                            "the renewal's expires_at")
        assert_same_instant(renewal["issued_at"], "2027-05-04T17:00:00Z",
                            "the renewal's issued_at")

    def test_renewal_supersedes_the_prior_card_and_renumbers_from_the_state_counter(self, api):
        """PRD §3.7: "When a prior certificate exists, `renews_certificate_id` records its
        identifier and that prior certificate moves to `SUPERSEDED`, which removes it from all
        future candidate sets — `ACTIVE → SUPERSEDED`, `GRACE → SUPERSEDED` and `LAPSED →
        SUPERSEDED` are all reachable this way."
        PRD §3.7: "The issuing jurisdiction's `certificates_issued_count` is incremented, and
        `certificate_number` is minted as the jurisdiction's `state_code`, a hyphen, the
        four-digit year of `issued_at`, a hyphen, and the post-increment counter value rendered
        as five digits with leading zeros — so the first certificate ever issued in Texas in
        2026 reads `TX-2026-00001`. The holder's `certification_count` rises by one."
        PRD §2.8: "The server's `active_certificate_id` is re-selected, and then
        `work_eligibility` is derived from the governing certificate: no certificate at all
        yields `UNCERTIFIED`; a governing certificate whose `validity_state` is `ACTIVE` yields
        `ELIGIBLE`; `GRACE` yields `GRACE`; `LAPSED` or `SUSPENDED` yields `RESTRICTED`."

        Design: Difficulty/dual_variant_calc/certificate_anniversary_anchored_renewal_preserves_original_expiry_month
        """
        base = setup_training_base(
            jurisdiction_overrides={"certificate_validity_months": 24})
        walk = certify_one_server(base)
        first = walk["certificate"]
        assert_certificate_number_format(first["certificate_number"], "TX", 2026, 1)

        staged = stage_second_class_ready_to_complete(base, walk["server"])
        complete_session(staged["session"]["id"], base["trainer_headers"])

        renewal = [c for c in certificates_for_server(walk["server"]["id"])
                   if c["id"] != first["id"]][0]
        assert renewal["renews_certificate_id"] == first["id"], (
            "the renewal records the prior certificate it renews, got "
            f"{renewal['renews_certificate_id']}")
        assert_certificate_number_format(renewal["certificate_number"], "TX", 2027, 2)
        assert get_certificate_row(first["id"])["validity_state"] == "SUPERSEDED"

        server = get_server(walk["server"]["id"])
        assert server["active_certificate_id"] == renewal["id"], (
            "the governing certificate is now the renewal, got "
            f"{server['active_certificate_id']}")
        assert server["work_eligibility"] == "ELIGIBLE"
        assert server["certification_count"] == 2


class TestGraceRosterRateDivergence:
    def test_strict_and_grace_inclusive_rates_diverge_for_an_all_grace_roster(self, api):
        """PRD §3.8: "`assigned_server_count` counts the live assignments; of those,
        `compliant_server_count` counts the ones whose server's `work_eligibility` is
        `ELIGIBLE`, `grace_server_count` counts the ones whose server's `work_eligibility` is
        `GRACE`, and `restricted_server_count` counts the ones whose own `assignment_state` is
        `WORK_RESTRICTED`."
        PRD §3.8: "The **strict** variant, `compliance_rate_strict_pct`, is
        `compliant_server_count` divided by `assigned_server_count`, multiplied by 100, rounded
        half up to two decimals — servers in grace count *against* it."
        PRD §3.8: "The **grace-inclusive** variant, `compliance_rate_grace_inclusive_pct`, uses
        `compliant_server_count` plus `grace_server_count` as its numerator over the same
        denominator, so a location whose entire roster sits inside the renewal grace window
        reads 100.00 grace-inclusive and 0.00 strict."
        PRD §3.8: "The total live headcount is the sum of `assigned_server_count` over the
        account's locations; `account_compliance_rate_pct` is the sum of
        `compliant_server_count` divided by that total, multiplied by 100, rounded half up to
        two decimals — except that when the total live headcount is zero the account rate reads
        **0.00**, not 100.00."
        PRD §2.6: "A location's compliance dashboard returns the stored derived values exactly
        as the last mutation or compliance run left them."

        Design: Difficulty/dual_variant_calc/location_strict_rate_diverges_from_grace_inclusive_rate_for_all_grace_roster
        """
        scenario = setup_certified_server_at_location(
            jurisdiction_overrides={"certificate_validity_months": 24},
            location_specs=[{"location_name": "Alamo Taproom"}])
        set_clock(CERT_EXPIRY_INSTANT)
        validate_success(api.create_compliance_run(
            TEST_USERS["program_admin_headers"]), 201)

        location = get_location(scenario["locations"][0]["id"])
        assert location["assigned_server_count"] == 1
        assert location["compliant_server_count"] == 0
        assert location["grace_server_count"] == 1
        assert location["compliance_rate_strict_pct"] == 0.00, (
            "a grace-only roster counts against the strict rate, got "
            f"{location['compliance_rate_strict_pct']}")
        assert location["compliance_rate_grace_inclusive_pct"] == 100.00, (
            "the grace-inclusive numerator admits the same roster, got "
            f"{location['compliance_rate_grace_inclusive_pct']}")
        assert location["compliance_posture"] == "COMPLIANT"

        dashboard = validate_success(api.get_location_compliance_dashboard(
            location["id"], scenario["employer_headers"]), 200)
        assert_compliance_dashboard(dashboard, location["id"])
        assert dashboard["compliance_rate_strict_pct"] == 0.00
        assert dashboard["compliance_rate_grace_inclusive_pct"] == 100.00

        account = validate_success(api.get_employer_account(
            scenario["account"]["id"], scenario["employer_headers"]), 200)
        assert account["account_compliance_rate_pct"] == 0.00, (
            "the account roll-up uses the strict numerator, got "
            f"{account['account_compliance_rate_pct']}")

    def test_grace_transition_leaves_the_assignment_active_and_emits_one_reminder(self, api):
        """PRD §3.9: "A certificate whose `validity_state` is `ACTIVE` and whose `expires_at`
        the clock has reached moves `ACTIVE → GRACE`, incrementing `certificates_graced_count`."
        PRD §3.9: "A `GRACE` certificate moves its holder `ELIGIBLE → GRACE`, and assignments
        stay `ACTIVE` — servers in grace may still work."
        PRD §3.9: "At most one reminder is emitted per certificate per run, and only while
        `validity_state` is `ACTIVE` or `GRACE` and the clock has reached `expires_at` minus the
        jurisdiction's `reminder_lead_days`."

        Design: Difficulty/dual_variant_calc/location_strict_rate_diverges_from_grace_inclusive_rate_for_all_grace_roster
        """
        scenario = setup_certified_server_at_location(
            jurisdiction_overrides={"certificate_validity_months": 24},
            location_specs=[{"location_name": "Alamo Taproom"}])
        set_clock(CERT_EXPIRY_INSTANT)

        run = validate_success(api.create_compliance_run(
            TEST_USERS["program_admin_headers"]), 201)
        assert_compliance_run(run)
        assert run["certificates_graced_count"] == 1
        assert run["certificates_lapsed_count"] == 0, (
            "each certificate receives at most one validity transition per run, got "
            f"{run['certificates_lapsed_count']}")
        assert run["reminders_sent_count"] == 1

        assert get_certificate_row(scenario["certificate"]["id"])["validity_state"] == "GRACE"
        assert get_server(scenario["server"]["id"])["work_eligibility"] == "GRACE"

        assignments, _ = validate_paginated(api.list_location_server_assignments(
            scenario["locations"][0]["id"], scenario["employer_headers"]))
        assert assignments[0]["assignment_state"] == "ACTIVE", (
            "servers in grace may still work, got "
            f"{assignments[0]['assignment_state']}")
