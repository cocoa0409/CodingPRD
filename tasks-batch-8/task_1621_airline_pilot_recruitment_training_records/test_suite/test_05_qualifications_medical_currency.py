"""Qualifications, landing currency, medical validity, and the grounding
cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    confirm_enrollment,
    enroll,
    get_enrollment,
    get_qualification,
    get_success_data,
    log_flight_activity,
    make_checkride,
    make_check_airman_headers,
    make_cleared_applicant,
    make_equipment,
    make_instructor,
    make_open_class,
    make_qualification,
    make_simulator_slot,
    pass_milestone,
    record_checkride,
    run_daily_scan,
    schedule_event,
    set_clock,
    start_class,
    start_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

TC = TEST_USERS["training_coordinator_headers"]
CS = TEST_USERS["crew_scheduler_headers"]


def _setup_currency_cycle_ctx(api):
    """Qualification driven LAPSED (2 landings in window), then REQUALIFYING
    via a recent passing SIMULATOR milestone, with a passing PRACTICAL ride
    recorded afterwards. The medical is still VALID at this point."""
    eq = make_equipment(code="A220", sim_rate=45000, ioe_hours=10,
                        landings_required=3)
    ap = make_cleared_applicant("guy@x.com", "L040", full_name="Guy Hale",
                                hours=4100, age=35)
    q = make_qualification(ap["id"], eq["id"])
    # Exactly 2 landings in the window (fleet requires 3).
    log_flight_activity(q["id"], "2026-07-20T12:00:00Z", 1, hours=2.5)
    log_flight_activity(q["id"], "2026-07-25T12:00:00Z", 1, hours=3.0)
    set_clock("2026-08-14T12:00:00Z")
    lapsed = validate_success(api.refresh_currency(q["id"], CS))
    assert lapsed["currency_state"] == "LAPSED", "Setup: 2 < 3 lapses currency"

    # Requalification ground work: a class whose dates sit after the current
    # clock, a passing SIMULATOR milestone, then a passed PRACTICAL ride.
    cls = get_success_data(api.create_training_class(
        {"equipment_id": eq["id"], "class_date": "2026-08-14T12:30:00Z",
         "seat_capacity": 10, "base_attrition_rate": 0.20}, TC))
    get_success_data(api.open_training_class(cls["id"], TC))
    en = enroll(cls["id"], ap["id"])
    confirm_enrollment(en["id"])
    set_clock("2026-08-14T12:30:00Z")
    start_class(cls["id"])
    start_enrollment(en["id"])
    ca1 = make_instructor("Rue Sim", "CHECK_AIRMAN")
    pass_milestone(en["id"], ca1["id"], "GROUND_SCHOOL",
                   "2026-08-14T13:00:00Z", "2026-08-14T15:00:00Z", score=88)
    slot = make_simulator_slot(eq["id"], "2026-08-14T15:30:00Z",
                               "2026-08-14T20:00:00Z")
    pass_milestone(en["id"], ca1["id"], "SIMULATOR",
                   "2026-08-14T16:00:00Z", "2026-08-14T18:00:00Z",
                   score=90, slot_id=slot["id"])
    requalifying = validate_success(api.requalify(q["id"], CS))
    assert requalifying["currency_state"] == "REQUALIFYING", (
        "Setup: the recent passing simulator milestone opens requalification")

    ca2 = make_instructor("Sam Ride", "CHECK_AIRMAN")
    ck = make_checkride(en["id"], ca2["id"],
                        scheduled_at="2026-08-15T09:00:00Z")
    set_clock("2026-08-15T09:00:00Z")
    record_checkride(ck["id"], "PASS", ca2["id"])
    return {"equipment": eq, "applicant": ap, "qualification": q,
            "training_class": cls, "enrollment": get_enrollment(en["id"]),
            "examiner": ca2}


class TestQualificationCurrencyCycle:
    def test_lapsed_to_requalifying_to_qualified_cycle(self, api):
        """PRD §3.6: "Comparing against the fleet's `landings_required_90d`:
        when `landings_90d` meets the requirement and the remainder after
        subtracting `landings_expiring_7d` also meets it, the next currency
        state is `QUALIFIED`; when `landings_90d` meets the requirement but
        that remainder does not, the next state is `CURRENCY_WARNING`;
        otherwise the qualification moves to `LAPSED`, and on a fresh lapse
        `lapsed_since` is stamped with the current logical time."
        PRD §3.6: "Requalification by a scheduler moves `LAPSED` →
        `REQUALIFYING` once the pilot has completed the requalification ground
        work: a `SIMULATOR`-phase `MILESTONE` event with status `COMPLETED` and
        a score of at least 80 within the 30 days preceding now."
        PRD §3.6: "Certification by a check airman then moves `REQUALIFYING` →
        `QUALIFIED` once a `PRACTICAL` checkride in `COMPLETED_PASS` exists for
        this applicant on this equipment after the transition into
        requalification; certification clears `lapsed_since`, stamps
        `last_evaluated_at`, and recomputes the landings counters."

        Design: Difficulty/non_linear_state_machine/qualification_currency_cycle_with_parallel_operating_dimension
        """
        ctx = _setup_currency_cycle_ctx(api)
        q_id = ctx["qualification"]["id"]
        certified = validate_success(api.certify_requalification(
            q_id, make_check_airman_headers(ctx["examiner"]["id"])))
        assert certified["currency_state"] == "QUALIFIED", "The cycle closes"
        assert certified["lapsed_since"] is None, "Certification clears lapsed_since"
        assert certified["operating_state"] == "ACTIVE"

    def test_grounding_leaves_currency_state_untouched(self, api):
        """PRD §2.9: "The Qualification is special: it carries two parallel,
        independent state dimensions — `currency_state` for recency of
        experience and `operating_state` for the medical gate — and a
        transition in one dimension never implies a transition in the other."
        PRD §3.6: "The moment a certificate leaves `VALID` — downgraded or
        expired by the scan, or suspended administratively — the grounding
        cascade fires: every qualification of the applicant in `operating_state`
        `ACTIVE` moves to `GROUNDED`, and every `SCHEDULED` training event
        belonging to any enrollment of that applicant moves to `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/qualification_currency_cycle_with_parallel_operating_dimension
        """
        ctx = _setup_currency_cycle_ctx(api)
        q_id = ctx["qualification"]["id"]
        validate_success(api.certify_requalification(
            q_id, make_check_airman_headers(ctx["examiner"]["id"])))
        # Suspend the pilot's only certificate: it leaves VALID, so the
        # grounding cascade fires on the operating dimension alone.
        certs, _meta = validate_paginated(
            api.list_medical_certificates(
                CS, params={"applicant_id": ctx["applicant"]["id"]}))
        assert len(certs) == 1
        validate_success(api.suspend_medical_certificate(certs[0]["id"], CS))
        after = get_qualification(q_id)
        assert after["operating_state"] == "GROUNDED", (
            "Suspension grounds the operating dimension")
        assert after["currency_state"] == "QUALIFIED", (
            "The currency dimension is untouched by grounding")


class TestMedicalGroundingCascade:
    def _setup_grounding_ctx(self):
        """Applicant with a certificate whose first-class window closes
        2026-08-31 (issued 2026-02-10 at age 45); qualification kept QUALIFIED
        by 3 in-window landings; one SCHEDULED event on 2026-09-02."""
        eq = make_equipment(code="B738", sim_rate=45000, ioe_hours=10,
                            landings_required=3)
        ap = make_cleared_applicant(
            "joe@x.com", "L060", full_name="Joe Kerr", hours=5200, age=45,
            medical_issued_at="2026-02-10T00:00:00Z")
        q = make_qualification(ap["id"], eq["id"])
        for day in ("2026-07-20", "2026-07-25", "2026-07-30"):
            log_flight_activity(q["id"], f"{day}T12:00:00Z", 1, hours=2.0)
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z",
                              seat_capacity=10, attrition=0.20)
        en = enroll(cls["id"], ap["id"])
        confirm_enrollment(en["id"])
        set_clock("2026-08-10T09:00:00Z")
        start_class(cls["id"])
        start_enrollment(en["id"])
        ins = make_instructor("Mel Gnd", "GROUND", daily_max=6)
        ev = schedule_event(en["id"], ins["id"], "GROUND_SCHOOL", "SESSION",
                            "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        return {"equipment": eq, "applicant": ap, "qualification": q,
                "event": ev}

    def test_scan_downgrades_certificate_and_grounds_qualification(self, api):
        """PRD §3.6: "First-class privileges run 12 months when the pilot was
        under 40 at issue and 6 months when the pilot was 40 or older;
        third-class privileges run 60 months under 40 and 24 months at 40 or
        older."
        PRD §3.6: "While the current date is on or before
        `first_class_valid_through` the certificate is `VALID`; past that date
        but on or before `third_class_valid_through` it is `DOWNGRADED`; and
        beyond the third-class through-date it is `EXPIRED` — including a
        `DOWNGRADED` certificate whose third-class window later closes."
        PRD §3.6: "The moment a certificate leaves `VALID` — downgraded or
        expired by the scan, or suspended administratively — the grounding
        cascade fires: every qualification of the applicant in `operating_state`
        `ACTIVE` moves to `GROUNDED`, and every `SCHEDULED` training event
        belonging to any enrollment of that applicant moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/medical_grounding_cascade_depth2
        """
        ctx = self._setup_grounding_ctx()
        run_daily_scan()
        certs, _meta = validate_paginated(
            api.list_medical_certificates(
                CS, params={"applicant_id": ctx["applicant"]["id"]}))
        assert certs[0]["status"] == "DOWNGRADED", (
            "Issued 2026-02 at age 45: first-class through 2026-08-31; the "
            "clock at 2026-09-01 is past it; third-class runs to 2028-02")
        qualification = get_qualification(ctx["qualification"]["id"])
        assert qualification["operating_state"] == "GROUNDED", (
            "Link 1: the medical transition grounds the qualification")

    def test_scan_cancels_scheduled_events_and_leaves_currency(self, api):
        """PRD §3.6: "The moment a certificate leaves `VALID` — downgraded or
        expired by the scan, or suspended administratively — the grounding
        cascade fires: every qualification of the applicant in `operating_state`
        `ACTIVE` moves to `GROUNDED`, and every `SCHEDULED` training event
        belonging to any enrollment of that applicant moves to `CANCELLED`."
        PRD §2.9: "The Qualification is special: it carries two parallel,
        independent state dimensions — `currency_state` for recency of
        experience and `operating_state` for the medical gate — and a
        transition in one dimension never implies a transition in the other."

        Design: Difficulty/transitive_cascade/medical_grounding_cascade_depth2
        """
        ctx = self._setup_grounding_ctx()
        run_daily_scan()
        event = validate_success(
            api.get_training_event(ctx["event"]["id"], TC))
        assert event["status"] == "CANCELLED", (
            "Link 2: the grounding cancels the pilot's scheduled events")
        qualification = get_qualification(ctx["qualification"]["id"])
        assert qualification["currency_state"] == "QUALIFIED", (
            "Three in-window landings keep currency QUALIFIED; the grounding "
            "does not touch the currency dimension")


class TestRecencyWindowBoundary:
    def _setup_boundary_qualification(self):
        eq = make_equipment(code="B762", sim_rate=45000, ioe_hours=10,
                            landings_required=3)
        ap = make_cleared_applicant("yan@x.com", "L090", full_name="Yan Zee",
                                    hours=6100, age=44)
        q = make_qualification(ap["id"], eq["id"])
        log_flight_activity(q["id"], "2026-05-16T12:00:00Z", 1, hours=1.5)
        log_flight_activity(q["id"], "2026-07-20T12:00:00Z", 1, hours=2.0)
        set_clock("2026-08-14T12:00:00Z")
        log_flight_activity(q["id"], "2026-08-01T12:00:00Z", 1, hours=2.2)
        return q

    def test_landing_exactly_90_days_old_is_excluded(self, api):
        """PRD §3.6: "The landing window is half-open: activity dated strictly
        more than 90 days ago is excluded, and activity at the present instant
        is included — an activity exactly 90 days old falls outside, one at 89
        days and 23 hours counts."

        Design: Difficulty/boundary_precision_check/landing_exactly_90_days_old_excluded
        """
        q = self._setup_boundary_qualification()
        refreshed = validate_success(api.refresh_currency(q["id"], CS))
        assert refreshed["landings_90d"] == 2, (
            "The 2026-05-16T12:00:00Z landing is exactly 90 days before "
            "2026-08-14T12:00:00Z and falls outside the half-open window")
        assert refreshed["currency_state"] == "LAPSED", "2 < 3 lapses"

    def test_fresh_lapse_stamps_lapsed_since_and_evaluated_at(self, api):
        """PRD §3.6: "otherwise the qualification moves to `LAPSED`, and on a
        fresh lapse `lapsed_since` is stamped with the current logical time.
        Every evaluation stamps `last_evaluated_at` and recomputes both
        counters, and the evaluation never touches `operating_state`, which the
        medical gate owns."

        Design: Difficulty/boundary_precision_check/landing_exactly_90_days_old_excluded
        """
        q = self._setup_boundary_qualification()
        refreshed = validate_success(api.refresh_currency(q["id"], CS))
        assert refreshed["currency_state"] == "LAPSED"
        assert_same_instant(refreshed["lapsed_since"], "2026-08-14T12:00:00Z",
                            "lapsed_since is stamped with the logical clock")
        assert refreshed["last_evaluated_at"] is not None
        assert refreshed["operating_state"] == "ACTIVE"


class TestCurrencyWarningBranch:
    def test_currency_warning_when_landings_cluster_at_window_edge(self, api):
        """PRD §3.6: "Within that window, `landings_90d` sums the logged
        landings, and `landings_expiring_7d` sums the landings in the window's
        oldest seven days — activity dated strictly more than 90 days ago up to
        and including 83 days ago — the landings about to age out."
        PRD §3.6: "Comparing against the fleet's `landings_required_90d`: when
        `landings_90d` meets the requirement and the remainder after
        subtracting `landings_expiring_7d` also meets it, the next currency
        state is `QUALIFIED`; when `landings_90d` meets the requirement but
        that remainder does not, the next state is `CURRENCY_WARNING`;
        otherwise the qualification moves to `LAPSED`, and on a fresh lapse
        `lapsed_since` is stamped with the current logical time."

        Design: Corner/calculations/currency_warning_branch_requires_expiring_landings
        """
        eq = make_equipment(code="CRJ7", sim_rate=40000, ioe_hours=8,
                            landings_required=3)
        ap = make_cleared_applicant("war@x.com", "L420", full_name="War Nin",
                                    hours=5000, age=40)
        q = make_qualification(ap["id"], eq["id"])
        log_flight_activity(q["id"], "2026-05-20T12:00:00Z", 1, hours=2.0)
        log_flight_activity(q["id"], "2026-05-22T12:00:00Z", 1, hours=2.0)
        set_clock("2026-08-14T12:00:00Z")
        log_flight_activity(q["id"], "2026-08-10T12:00:00Z", 1, hours=2.0)
        refreshed = validate_success(api.refresh_currency(q["id"], CS))
        assert refreshed["landings_90d"] == 3
        assert refreshed["landings_expiring_7d"] == 2, (
            "The two May landings sit in the window's oldest seven days")
        assert refreshed["currency_state"] == "CURRENCY_WARNING", (
            "3 - 2 = 1 < 3: the remainder fails, so WARNING not QUALIFIED")


class TestMedicalValidityBranches:
    def test_medical_validity_age_branch_40_plus_vs_under(self, api):
        """PRD §3.6: "Validity is computed in whole calendar months from the
        issue month, and the certificate remains valid through the last day of
        the resulting month, inclusive. First-class privileges run 12 months
        when the pilot was under 40 at issue and 6 months when the pilot was 40
        or older; third-class privileges run 60 months under 40 and 24 months
        at 40 or older. These computations land on `first_class_valid_through`
        and `third_class_valid_through`."

        Design: Corner/calculations/medical_validity_age_branch_40_plus_vs_under
        """
        ap_young = make_cleared_applicant("young@x.com", "L421",
                                          full_name="Age Young")
        ap_old = make_cleared_applicant("old@x.com", "L422",
                                        full_name="Age Old")
        young = validate_success(api.create_medical_certificate(
            {"applicant_id": ap_young["id"], "cert_class": "FIRST",
             "issued_at": "2026-07-10T00:00:00Z", "pilot_age_at_issue": 39},
            CS), 201)
        old = validate_success(api.create_medical_certificate(
            {"applicant_id": ap_old["id"], "cert_class": "FIRST",
             "issued_at": "2026-07-10T00:00:00Z", "pilot_age_at_issue": 40},
            CS), 201)
        # Issue month July 2026 + 12 months -> through 2027-07-31 (under 40).
        assert young["first_class_valid_through"][:10] == "2027-07-31"
        assert young["third_class_valid_through"][:10] == "2031-07-31"
        # July 2026 + 6 months -> through 2027-01-31 (40 or older).
        assert old["first_class_valid_through"][:10] == "2027-01-31"
        assert old["third_class_valid_through"][:10] == "2028-07-31"
        assert young["status"] == "VALID" and old["status"] == "VALID", (
            "Both certificates evaluate VALID at the 2026-08-01 clock")


class TestQualificationRules:
    def test_flight_activity_in_future_rejected(self, api):
        """PRD §3.6: "Flying is logged against the qualification with
        `activity_date` — never in the future, else `ERR_FUTURE_ACTIVITY_DATE`"

        Design: Corner/validations/flight_activity_in_future_rejected
        """
        eq = make_equipment(code="E175", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("fut@x.com", "L436", full_name="Fut Ure")
        q = make_qualification(ap["id"], eq["id"])
        resp = api.create_flight_activity(
            {"qualification_id": q["id"], "activity_date": "2026-08-02T00:00:00Z",
             "landings": 1, "hours": 2.0, "activity_type": "REVENUE"}, CS)
        validate_error(resp, ApiErrorId.ERR_FUTURE_ACTIVITY_DATE)

    def test_duplicate_qualification_pair_rejected(self, api):
        """PRD §3.6: "A new qualification starts with `currency_state`
        `QUALIFIED` and `operating_state` `ACTIVE`, stamps `qualified_at`, and
        leaves `lapsed_since` and `last_evaluated_at` null."
        PRD §3.6: "the applicant must be `CLEARED`, otherwise
        `ERR_APPLICANT_INVALID_STATE`, and only one qualification row may exist
        per applicant-and-equipment pair — a second grant for the same pair is
        rejected with `ERR_DUPLICATE_QUALIFICATION` (409)."

        Design: Corner/validations/duplicate_qualification_pair_rejected
        """
        eq = make_equipment(code="E190B", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("dupq@x.com", "L437", full_name="Dup Qual")
        first = make_qualification(ap["id"], eq["id"])
        assert first["currency_state"] == "QUALIFIED"
        assert first["operating_state"] == "ACTIVE"
        resp = api.create_qualification(
            {"applicant_id": ap["id"], "equipment_id": eq["id"]}, CS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUALIFICATION)

    def test_requalify_from_qualified_state_rejected(self, api):
        """PRD §3.6: "Either action attempted from the wrong currency state, or
        without its prerequisite evidence, is rejected with
        `ERR_QUALIFICATION_INVALID_STATE` (409)."

        Design: Corner/errors/qualification_requalify_from_wrong_state
        """
        eq = make_equipment(code="FK05", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("rq@x.com", "L456", full_name="Re Qual")
        q = make_qualification(ap["id"], eq["id"])
        assert q["currency_state"] == "QUALIFIED", "Never lapsed"
        resp = api.requalify(q["id"], CS)
        validate_error(resp, ApiErrorId.ERR_QUALIFICATION_INVALID_STATE)
