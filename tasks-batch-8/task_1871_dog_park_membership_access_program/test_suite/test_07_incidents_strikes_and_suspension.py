"""Incident reports, strike scoring, the suspension cascade, and
reinstatement."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_report,
    check_in_dog,
    confirm_report,
    create_park_area,
    create_steward,
    file_incident_payload,
    file_report,
    get_member,
    get_membership,
    make_member_headers,
    make_steward_headers,
    purchase_guest_pass_payload,
    purchase_pass,
    register_member,
    set_clock,
    setup_active_member,
    suspend_member_via_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["park_admin_headers"]


class TestStrikeScoring:
    def test_strike_score_confirmed_vs_provisional(self, api):
        """PRD §3.7: "A subject's `strike_points` — the authoritative figure
        that drives suspension — sums severity points across the subject's
        `CONFIRMED` reports only: ten points for `MINOR`, twenty for `MAJOR`,
        thirty for `SEVERE`."
        PRD §3.7: "The advisory `provisional_strike_score` starts from the same
        confirmed total and adds half the severity points of the reports still
        pending (`FILED` or `UNDER_REVIEW`), with that half-weight term rounded
        half-up to a whole point."
        PRD §3.7: "When a report becomes `CONFIRMED`, the subject's
        `strike_points` is recomputed at full weight, and if the total reaches
        at least thirty — exactly thirty included — the member is suspended
        within the same request."

        Design: Difficulty/dual_variant_calc/strike_score_provisional_vs_confirmed
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject@x.com")
        member = bundle["member"]

        r1 = file_report(member["id"], severity="MAJOR",
                         occurred_at="2026-08-02T10:00:00Z",
                         description="fight at the gate")
        confirm_report(r1["id"])
        file_report(member["id"], severity="SEVERE",
                    occurred_at="2026-08-03T10:00:00Z",
                    description="bite reported")

        after = get_member(member["id"])
        assert after["strike_points"] == 20, "only the CONFIRMED MAJOR counts"
        assert after["provisional_strike_score"] == 35, (
            "20 confirmed + round_half_up(0.5 * 30 pending)"
        )
        assert after["status"] == "ACTIVE", "20 is below the threshold of 30"

    def test_provisional_score_recomputed_on_filing(self, api):
        """PRD §3.7: "Filing immediately recomputes the subject's
        `provisional_strike_score`, because a `FILED` report already counts at
        half weight."
        PRD §3.7: "From `FILED` the only move is `FILED → UNDER_REVIEW`, open
        to stewards — members whose `is_steward` flag is set — and to
        administrators, and it recomputes the subject's provisional score."

        Design: Difficulty/dual_variant_calc/strike_score_provisional_vs_confirmed
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject2@x.com")
        member = bundle["member"]

        file_report(member["id"], severity="SEVERE",
                    occurred_at="2026-08-02T10:00:00Z",
                    description="bite reported")
        mid = get_member(member["id"])
        assert mid["strike_points"] == 0, "nothing CONFIRMED yet"
        assert mid["provisional_strike_score"] == 15, (
            "round_half_up(0.5 * 30) on the FILED report"
        )

        reports = api.list_incident_reports(ADMIN)
        report_id = reports.json()["data"][0]["id"]
        advance_report(report_id, "UNDER_REVIEW")
        after = get_member(member["id"])
        assert after["provisional_strike_score"] == 15, (
            "UNDER_REVIEW keeps the report pending at half weight"
        )
        assert after["strike_points"] == 0
        assert after["status"] == "ACTIVE"


class TestSuspensionThreshold:
    def test_strike_threshold_exact_30_suspends(self, api):
        """PRD §3.7: "When a report becomes `CONFIRMED`, the subject's
        `strike_points` is recomputed at full weight, and if the total reaches
        at least thirty — exactly thirty included — the member is suspended
        within the same request."

        Design: Difficulty/boundary_precision_check/strike_threshold_exact_30
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject3@x.com")
        member = bundle["member"]

        r1 = file_report(member["id"], severity="MAJOR",
                         occurred_at="2026-08-02T10:00:00Z",
                         description="fight")
        confirm_report(r1["id"])
        mid = get_member(member["id"])
        assert mid["strike_points"] == 20
        assert mid["status"] == "ACTIVE", "20 stays below the threshold"

        r2 = file_report(member["id"], severity="MINOR",
                         occurred_at="2026-08-03T10:00:00Z",
                         description="lunging")
        advance_report(r2["id"], "UNDER_REVIEW")
        advance_report(r2["id"], "CONFIRMED")

        after = get_member(member["id"])
        assert after["strike_points"] == 30, "exactly at the boundary"
        assert after["status"] == "SUSPENDED", (
            "the >= boundary fires at exactly thirty"
        )

    def test_strike_total_above_threshold_suspends(self, api):
        """PRD §3.7: "When a report becomes `CONFIRMED`, the subject's
        `strike_points` is recomputed at full weight, and if the total reaches
        at least thirty — exactly thirty included — the member is suspended
        within the same request."

        Design: Difficulty/boundary_precision_check/strike_threshold_exact_30
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject4@x.com")
        member = bundle["member"]

        r1 = file_report(member["id"], severity="MAJOR",
                         occurred_at="2026-08-02T10:00:00Z",
                         description="first fight")
        confirm_report(r1["id"])
        assert get_member(member["id"])["status"] == "ACTIVE"

        r2 = file_report(member["id"], severity="MAJOR",
                         occurred_at="2026-08-03T10:00:00Z",
                         description="second fight")
        confirm_report(r2["id"])

        after = get_member(member["id"])
        assert after["strike_points"] == 40
        assert after["status"] == "SUSPENDED", (
            "at least thirty includes totals above it"
        )


class TestSuspensionCascade:
    def test_incident_confirm_suspension_cascade(self, api):
        """PRD §3.7: "The suspension flips the member `ACTIVE → SUSPENDED`;
        flips their `ACTIVE` membership to `SUSPENDED`; force-closes every
        `OPEN` visit of theirs with `close_reason` `MEMBER_SUSPENDED`, stamping
        `checked_out_at` and recomputing each affected area's
        `current_occupancy`; and flips every `ISSUED` guest pass they sponsored
        to `VOID`, recomputing `guest_passes_used_this_month` with the voided
        passes excluded so the allotment is refunded."

        Design: Difficulty/transitive_cascade/incident_confirm_suspension_cascade
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Sub Ject",
                                     email="subject5@x.com",
                                     set_clock_first=False)
        member = bundle["member"]
        visit = check_in_dog(member, bundle["dogs"][0], area)
        guest_pass = purchase_pass(member, guest_dog_size_class="SMALL",
                                   valid_on="2026-08-03")

        report = file_report(member["id"], severity="SEVERE",
                             occurred_at="2026-08-01T11:00:00Z",
                             description="bite near gate")
        advance_report(report["id"], "UNDER_REVIEW")
        advance_report(report["id"], "CONFIRMED")

        after = get_member(member["id"])
        assert after["strike_points"] == 30
        assert after["status"] == "SUSPENDED"
        assert after["guest_passes_used_this_month"] == 0, (
            "the voided pass refunds the allotment"
        )
        assert get_membership(member["id"])["status"] == "SUSPENDED"

        refreshed_visit = validate_success(api.get_visit(visit["id"], ADMIN))
        assert refreshed_visit["status"] == "FORCE_CLOSED"
        assert refreshed_visit["close_reason"] == "MEMBER_SUSPENDED"

        refreshed_pass = validate_success(
            api.get_guest_pass(guest_pass["id"], ADMIN))
        assert refreshed_pass["status"] == "VOID"

    def test_suspension_cascade_stamps_force_closed_visit(self, api):
        """PRD §3.7: "The suspension flips the member `ACTIVE → SUSPENDED`;
        flips their `ACTIVE` membership to `SUSPENDED`; force-closes every
        `OPEN` visit of theirs with `close_reason` `MEMBER_SUSPENDED`, stamping
        `checked_out_at` and recomputing each affected area's
        `current_occupancy`"
        PRD §3.7: "All of it commits atomically (§2.10), and every mutated
        entity's `version` advances by one."

        Design: Difficulty/transitive_cascade/incident_confirm_suspension_cascade
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Sub Ject",
                                     email="subject6@x.com",
                                     set_clock_first=False)
        member = bundle["member"]
        visit = check_in_dog(member, bundle["dogs"][0], area)
        assert validate_success(api.get_area(area["id"], ADMIN))[
            "current_occupancy"] == 1
        member_before = get_member(member["id"])
        membership_before = get_membership(member["id"])

        report = file_report(member["id"], severity="SEVERE",
                             occurred_at="2026-08-01T11:00:00Z",
                             description="bite near gate")
        confirm_report(report["id"])

        after = get_member(member["id"])
        assert after["status"] == "SUSPENDED"
        assert after["version"] > member_before["version"], (
            "the member's version advances in the cascade"
        )
        membership_after = get_membership(member["id"])
        assert membership_after["status"] == "SUSPENDED"
        assert membership_after["version"] > membership_before["version"]

        refreshed = validate_success(api.get_visit(visit["id"], ADMIN))
        assert refreshed["status"] == "FORCE_CLOSED"
        assert refreshed["close_reason"] == "MEMBER_SUSPENDED"
        assert refreshed["checked_out_at"] is not None, (
            "the force-close stamps checked_out_at"
        )
        assert refreshed["version"] > visit["version"]

        area_after = validate_success(api.get_area(area["id"], ADMIN))
        assert area_after["current_occupancy"] == 0, (
            "the affected area's occupancy is recomputed"
        )


class TestReinstatementCycle:
    def test_member_suspension_reinstatement_cycle(self, api):
        """PRD §3.7: "Reinstatement is an administrator's call, available only
        for a `SUSPENDED` member — any other status is
        `ERR_MEMBER_NOT_SUSPENDED` — and it always resets `strike_points` to
        zero."
        PRD §3.7: "Where the member lands depends on the membership: if the
        membership stands `SUSPENDED`, the member returns `SUSPENDED → ACTIVE`
        and the membership rides along `SUSPENDED → ACTIVE`"

        Design: Difficulty/non_linear_state_machine/member_suspension_reinstatement_cycle
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject7@x.com")
        member = bundle["member"]
        suspend_member_via_report(member["id"], severity="SEVERE")
        suspended = get_member(member["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["strike_points"] == 30
        assert get_membership(member["id"])["status"] == "SUSPENDED"

        reinstated = validate_success(api.reinstate_member(member["id"], ADMIN))
        assert reinstated["status"] == "ACTIVE", "the cycle closes"
        assert reinstated["strike_points"] == 0, "strikes reset on reinstatement"
        assert get_membership(member["id"])["status"] == "ACTIVE", (
            "the SUSPENDED membership rides along to ACTIVE"
        )

    def test_suspended_member_blocked_until_reinstated(self, api):
        """PRD §3.6: "The sponsor is taken from the caller's identity into
        `sponsor_member_id`, and only members in `ACTIVE` status may purchase —
        any other member status is rejected with `ERR_MEMBER_NOT_ACTIVE`."
        PRD §3.7: "Reinstatement is an administrator's call, available only for
        a `SUSPENDED` member — any other status is
        `ERR_MEMBER_NOT_SUSPENDED` — and it always resets `strike_points` to
        zero."

        Design: Difficulty/non_linear_state_machine/member_suspension_reinstatement_cycle
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Sub Ject",
                                     email="subject8@x.com")
        member = bundle["member"]
        suspend_member_via_report(member["id"], severity="SEVERE")
        assert get_member(member["id"])["status"] == "SUSPENDED"

        blocked = api.purchase_guest_pass(
            purchase_guest_pass_payload(guest_dog_size_class="SMALL",
                                        valid_on="2026-08-03"),
            bundle["member_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

        validate_success(api.reinstate_member(member["id"], ADMIN))
        guest_pass = purchase_pass(member, guest_dog_size_class="SMALL",
                                   valid_on="2026-08-03")
        assert guest_pass["status"] == "ISSUED", (
            "reinstatement restores purchase capability"
        )

    def test_reinstate_active_member_rejected(self, api):
        """PRD §3.7: "Reinstatement is an administrator's call, available only
        for a `SUSPENDED` member — any other status is
        `ERR_MEMBER_NOT_SUSPENDED` — and it always resets `strike_points` to
        zero."

        Design: Corner/state_machines/reinstate_active_member_rejected
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Own Er", email="owner@x.com")
        resp = api.reinstate_member(bundle["member"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_SUSPENDED)


class TestIncidentAdvanceRules:
    def test_advance_filed_to_confirmed_rejected(self, api):
        """PRD §3.7: "From `FILED` the only move is `FILED → UNDER_REVIEW`,
        open to stewards — members whose `is_steward` flag is set — and to
        administrators, and it recomputes the subject's provisional score."
        PRD §3.7: "Any advance whose target is not reachable from the report's
        current status — including anything out of the terminal `CONFIRMED` or
        `DISMISSED` states — is rejected with `ERR_INCIDENT_NOT_ADVANCABLE`."

        Design: Corner/state_machines/advance_filed_to_confirmed_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        subject = register_member(full_name="Sub Ject", email="subject@x.com")
        report = file_report(subject["id"], severity="MINOR",
                             occurred_at="2026-08-01T10:00:00Z",
                             description="rough play")
        assert report["status"] == "FILED"

        resp = api.advance_incident_report(report["id"], {"to": "CONFIRMED"},
                                           ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ADVANCABLE)

    def test_steward_triage_filed_to_under_review(self, api):
        """PRD §3.7: "From `FILED` the only move is `FILED → UNDER_REVIEW`,
        open to stewards — members whose `is_steward` flag is set — and to
        administrators, and it recomputes the subject's provisional score."

        Design: Corner/state_machines/steward_triage_filed_to_under_review
        """
        set_clock("2026-08-01T00:00:00Z")
        subject = register_member(full_name="Sub Ject", email="subject@x.com")
        steward = create_steward(full_name="Ste Ward", email="steward@x.com")
        report = file_report(subject["id"], severity="MINOR",
                             occurred_at="2026-08-01T10:00:00Z",
                             description="rough play")

        triaged = advance_report(report["id"], "UNDER_REVIEW",
                                 headers=steward["steward_headers"])
        assert triaged["status"] == "UNDER_REVIEW"

    def test_steward_flag_required_for_triage(self, api):
        """PRD §2.1: "When `X-User-Role` is `Steward`, `X-User-ID` is likewise
        the `id` of a Member, and additionally that member's `is_steward` flag
        must be true; a steward-role request from a member without the flag
        fails with `ERR_NOT_A_STEWARD` (HTTP 403)."

        Design: Corner/validations/steward_flag_required_for_triage
        """
        set_clock("2026-08-01T00:00:00Z")
        subject = register_member(full_name="Sub Ject", email="subject@x.com")
        plain = register_member(full_name="Plain Member", email="plain@x.com")
        report = file_report(subject["id"], severity="MINOR",
                             occurred_at="2026-08-01T10:00:00Z",
                             description="rough play")

        resp = api.advance_incident_report(
            report["id"], {"to": "UNDER_REVIEW"},
            make_steward_headers(plain["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_A_STEWARD)

    def test_steward_cannot_confirm_report(self, api):
        """PRD §3.7: "From `UNDER_REVIEW`, an administrator and only an
        administrator may move the report `UNDER_REVIEW → CONFIRMED` or
        `UNDER_REVIEW → DISMISSED`; a steward attempting either outcome
        receives `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/steward_cannot_confirm_report
        """
        set_clock("2026-08-01T00:00:00Z")
        subject = register_member(full_name="Sub Ject", email="subject@x.com")
        steward = create_steward(full_name="Ste Ward", email="steward@x.com")
        report = file_report(subject["id"], severity="MINOR",
                             occurred_at="2026-08-01T10:00:00Z",
                             description="rough play")
        advance_report(report["id"], "UNDER_REVIEW",
                       headers=steward["steward_headers"])

        resp = api.advance_incident_report(report["id"], {"to": "CONFIRMED"},
                                           steward["steward_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        after = validate_success(api.get_incident_report(report["id"], ADMIN))
        assert after["status"] == "UNDER_REVIEW", (
            "the denied adjudication never mutates the report"
        )

    def test_self_incident_report_rejected(self, api):
        """PRD §3.7: "Nobody may report themselves: a `subject_member_id` equal
        to the reporting member's own id is rejected with
        `ERR_SELF_REPORT_NOT_ALLOWED` (HTTP 422)."

        Design: Corner/validations/self_incident_report_rejected
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Own Er", email="owner@x.com")
        member = bundle["member"]
        resp = api.file_incident_report(
            file_incident_payload(
                member["id"], severity="MINOR",
                occurred_at="2026-08-01T10:00:00Z",
                description="my own dog"),
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SELF_REPORT_NOT_ALLOWED)

    def test_advance_unknown_report_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_incident_not_found
        """
        resp = api.advance_incident_report(NON_EXISTENT_UUID,
                                           {"to": "UNDER_REVIEW"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_FOUND)
