"""Compliance scoring: provisional vs audited variants, posture thresholds,
and the daily license-expiry sweep."""
from test_helpers import (
    add_days,
    create_impairment_payload,
    create_property,
    get_event_report,
    get_success_data,
    iso_utc,
    list_event_deficiencies,
    parse_date,
    record_alarm,
    record_and_assess_alarm,
    record_deficiency,
    schedule_event,
    set_clock,
    setup_inspection_site,
    setup_published_plan,
    setup_scheduled_event,
    start_event,
    complete_event,
    validate_success,
)
from test_helpers import TEST_USERS, create_contractor

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestProvisionalVsAuditedScore:
    def _mixed_ledger_contractor(self, api):
        """One contractor carrying every flavor of deduction plus one on-time
        completed event; clock parked past every correction deadline.

        Deductions: 1 overdue OPEN CRITICAL (-40), 2 overdue OPEN NONCRITICAL
        (-20), 1 late SUBMITTED report (-25), 1 late NOTIFIED impairment (-60),
        1 ASSESSED NEGLIGENCE alarm (-15) -> provisional 840; the on-time event
        adds +2 in the audited variant -> 842.
        """
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_inspection_site(install_date="2026-05-01",
                                    license_expires_on="2027-06-01",
                                    legal_name="Delta Fire")
        setup_published_plan(ctx)
        ev = schedule_event(ctx["con"], ctx["plan"], ctx["sys"], ctx["tech"],
                            scheduled_start="2026-08-02T09:00:00Z",
                            scheduled_end="2026-08-02T11:00:00Z")
        start_event(ctx["tech"], ev)
        record_deficiency(ctx["tech"], ev, ctx["dev"], classification="CRITICAL")
        record_deficiency(ctx["tech"], ev, ctx["dev"], classification="NONCRITICAL")
        record_deficiency(ctx["tech"], ev, ctx["dev"], classification="NONCRITICAL")
        ev = complete_event(ctx["tech"], ev)  # completed 2026-06-01, on time
        ctx["ev"] = ev

        set_clock("2026-06-03T08:00:00Z")
        imp = get_success_data(api.create_impairment(
            ctx["sys"]["id"],
            create_impairment_payload(impairment_kind="UNPLANNED",
                                      planned_start="2026-06-03T08:00:00Z",
                                      planned_end="2026-06-03T12:00:00Z"),
            ctx["admin"]), 201)
        set_clock("2026-06-03T11:00:00Z")  # notify 3h after discovery -> late
        validate_success(api.notify_authority(imp["id"], ctx["admin"]))
        validate_success(api.restore_impairment(imp["id"], ctx["admin"]))

        alarm = record_alarm(ctx["prop"], "2026-06-04T03:00:00Z", "NEGLIGENCE")
        validate_success(api.assess_false_alarm(alarm["id"], MARSHAL))

        set_clock("2026-06-12T00:00:00Z")  # report_due was 2026-06-08 -> late
        report = get_event_report(ctx["con"], ev)
        submitted = validate_success(api.submit_report(report["id"], ctx["admin"]))
        assert submitted["is_late"] is True

        # Park the clock past every deficiency deadline so all three are overdue,
        # without ever moving the clock backward.
        deadlines = [parse_date(d["correction_deadline"])
                     for d in list_event_deficiencies(ctx["con"], ev)]
        audit_date = max(parse_date("2026-06-13"), add_days(max(deadlines), 1))
        set_clock(iso_utc(audit_date))
        return ctx

    def test_audit_score_returns_divergent_variants(self, api):
        """PRD §2.9: "The **audited** score is computed on demand through a
        `FireMarshal`-only audit capability and is not persisted; the response
        carries both `audited_score` and `provisional_score`."
        PRD §2.9: "The provisional score is the base formula exactly — no bonuses
        and no license deduction — floored at 0."
        PRD §2.9: "The audited variant takes the provisional base, adds an
        on-time bonus of 2 points per inspection event completed within the
        trailing 90 days whose completion was on time, with the bonus capped at
        50 points total, and subtracts 100 points if any technician of the
        contractor holds a license record in `EXPIRED` or `REVOKED` at audit
        time."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_audited_diverge
        """
        ctx = self._mixed_ledger_contractor(api)
        result = validate_success(api.audit_score(ctx["con"]["id"], MARSHAL))
        # -40 critical, -20 two noncritical, -25 late report, -60 late notice,
        # -15 negligence -> 1000 - 160.
        assert result["provisional_score"] == 840, (
            f"provisional base is 840, got {result['provisional_score']}")
        assert result["audited_score"] == 842, (
            f"one on-time completed event adds +2 with no license deduction, "
            f"got {result['audited_score']}")
        assert result["audited_score"] != result["provisional_score"]

    def test_audit_does_not_persist_and_posture_is_probation(self, api):
        """PRD §2.9: "The **audited** score is computed on demand through a
        `FireMarshal`-only audit capability and is not persisted"
        PRD §2.9: "The contractor is `SUSPENDED` when the score is below 600 or
        the open-overdue-critical count is at least 3; otherwise `PROBATION` when
        the score is below 850 or that count is at least 1; otherwise
        `GOOD_STANDING`."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_audited_diverge
        """
        ctx = self._mixed_ledger_contractor(api)
        validate_success(api.audit_score(ctx["con"]["id"], MARSHAL))
        con = validate_success(api.get_contractor(ctx["con"]["id"], MARSHAL))
        assert con["compliance_score"] == 840, (
            "the persisted score is the provisional variant; the audit leaves "
            "it untouched")
        assert con["posture"] == "PROBATION", (
            "840 is below 850 and one open overdue critical remains")


class TestPostureThresholds:
    def test_threshold_boundaries(self, api):
        """PRD §2.9: "The contractor is `SUSPENDED` when the score is below 600
        or the open-overdue-critical count is at least 3; otherwise `PROBATION`
        when the score is below 850 or that count is at least 1; otherwise
        `GOOD_STANDING`."
        PRD §2.9: "15 for each false-alarm case in `ASSESSED` or `PAID` whose
        `cause_code` is `NEGLIGENCE`"
        PRD §2.9: "40 for each `OPEN` `CRITICAL` deficiency whose
        `correction_deadline` has passed"

        Design: Corner/calculations/posture_threshold_boundaries
        """
        # Contractor A: a single assessed NEGLIGENCE alarm (-15).
        set_clock("2026-08-01T00:00:00Z")
        con_a = create_contractor(legal_name="Boundary A", state_license_no="C-9960")
        prop_a = create_property(con_a, address_line="1 A St")
        record_and_assess_alarm(prop_a, "2026-08-02T01:00:00Z", "NEGLIGENCE")

        # Contractor C: three OPEN CRITICAL deficiencies driven overdue.
        ctx = setup_scheduled_event(legal_name="Critical C",
                                    scheduled_start="2026-08-02T09:00:00Z",
                                    scheduled_end="2026-08-02T10:00:00Z")
        set_clock("2026-08-02T09:30:00Z")
        start_event(ctx["tech"], ctx["ev"])
        for _ in range(3):
            record_deficiency(ctx["tech"], ctx["ev"], ctx["dev"],
                              classification="CRITICAL")
        ev = complete_event(ctx["tech"], ctx["ev"])
        deadlines = [parse_date(d["correction_deadline"])
                     for d in list_event_deficiencies(ctx["con"], ev)]
        set_clock(iso_utc(add_days(max(deadlines), 1)))

        con_a_after = validate_success(api.get_contractor(con_a["id"], MARSHAL))
        assert con_a_after["compliance_score"] == 985, (
            f"1000 - 15 negligence, got {con_a_after['compliance_score']}")
        assert con_a_after["posture"] == "GOOD_STANDING", (
            "985 >= 850 with zero overdue criticals")

        con_c_after = validate_success(api.get_contractor(ctx["con"]["id"], MARSHAL))
        assert con_c_after["compliance_score"] == 880, (
            f"1000 - 3 x 40 overdue critical deductions, got "
            f"{con_c_after['compliance_score']}")
        assert con_c_after["posture"] == "SUSPENDED", (
            "three open overdue critical deficiencies force SUSPENDED even "
            "though 880 >= 600")


class TestLicenseExpirySweep:
    def test_license_expires_when_clock_passes_expiry(self, api):
        """PRD §3.1: "When the logical date passes a record's `expires_on`, the
        daily sweep moves the record to `EXPIRED`, refreshes the owning
        technician's `updated_at`, increments the technician's `version`, and
        triggers a compliance-score recompute for the contractor."
        PRD §2.5: "Setting the clock runs the daily-sweep logic for the new
        date. The sweep performs five jobs: it expires license records whose
        expiry date has passed"

        Design: Corner/state_machines/license_expiry_sweep_transition
        """
        ctx = setup_inspection_site(license_expires_on="2026-08-10",
                                    legal_name="Sweep Co")
        lic = ctx["lic"]
        assert lic["status"] == "ACTIVE"
        set_clock("2026-08-11T00:00:00Z")
        swept = validate_success(api.get_license_record(lic["id"], MARSHAL))
        assert swept["status"] == "EXPIRED", (
            "the daily sweep expires records whose expiry date has passed")
