"""Clock suspensions and tolling credit, trend-snapshot materialization with
its dual rate variants and pinned rounding order, and the priority score."""
from test_helpers import (
    accept_findings,
    add_sufficient_notes,
    ApiErrorId,
    approve_letter,
    assign_investigator,
    classify_case,
    create_case,
    create_clock_suspension_payload,
    create_staff,
    create_unit,
    draft_letter,
    get_success_data,
    issue_letter,
    make_director_headers,
    open_investigation,
    set_clock,
    setup_closed_case,
    submit_findings,
    submit_letter_review,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestTollingRecomputeOrder:
    def _setup_suspended_grievance(self, api):
        """STANDARD grievance received 2026-08-01T09:00:00Z (base calendar due
        2026-08-31T09:00:00Z), acknowledged next day, suspension opened
        2026-08-20T09:00:00Z."""
        set_clock("2026-08-01T10:00:00.000Z")
        unit = create_unit("Oncology", "INPATIENT")
        case = create_case(unit["id"], patient_ref="P-4001",
                           received_at="2026-08-01T09:00:00.000Z", channel="PHONE",
                           description="Family communication concern",
                           grievance_category="COMMUNICATION")
        classify_case(case["id"], "GRIEVANCE")
        # Record the acknowledgment inside its 7-day window so the post-close
        # reading isolates the tolling/order rule (ack clock is not tolled).
        set_clock("2026-08-02T09:00:00.000Z")
        get_success_data(api.acknowledge_case(case["id"], INTAKE))
        set_clock("2026-08-20T09:00:00.000Z")
        suspension = get_success_data(api.create_clock_suspension(
            case["id"], create_clock_suspension_payload(reason="AWAITING_FAMILY"),
            INTAKE))
        return case, suspension

    def test_open_suspension_masks_and_close_recomputes_credit(self, api):
        """PRD §3.5: "Otherwise, any `OPEN` suspension makes it read
        `SUSPENDED`." PRD §3.5: "The credit is the sum of the merged durations,
        in seconds, and both response dues re-extend by it." PRD §3.5: "First
        the tolling credit is recomputed by the interval merge above; then
        `response_due_calendar_at` is recomputed as its base plus that credit;
        only then is the status read off, and the status never feeds back into
        the first two steps within the same evaluation."

        Design: Difficulty/combinatorial_formula/tolling_recompute_precedes_status_derivation
        """
        case, suspension = self._setup_suspended_grievance(api)
        set_clock("2026-08-22T09:00:00.000Z")
        mid = get_success_data(api.get_case_timeline(case["id"], INTAKE))
        assert mid["regulatory_clock_status"] == "SUSPENDED", (
            "an open suspension masks breach evaluation")

        set_clock("2026-08-25T09:00:00.000Z")
        get_success_data(api.close_clock_suspension(suspension["id"], INTAKE))
        after = get_success_data(api.get_case_timeline(case["id"], INTAKE))
        assert after["tolling_credit_seconds"] == 432000, (
            "5 days x 86400 seconds, single interval, no double counting")
        assert after["response_due_calendar_at"] == "2026-09-05T09:00:00.000Z", (
            "base 2026-08-31T09:00:00Z re-extended by the 432000s credit")

    def test_status_reads_off_recomputed_due(self, api):
        """PRD §3.5: "Suspension close therefore resolves to one of three
        readings: `ON_TRACK` when the re-extended dues are still ahead and the
        acknowledgment is satisfied or not yet due; `ACK_BREACH` when the
        acknowledgment remains unsent and its untolled due has already passed;
        or `RESPONSE_BREACH` when the clock already stands past the re-extended
        response due." and "Otherwise, once the clock passes the
        tolling-adjusted `response_due_calendar_at`, it reads
        `RESPONSE_BREACH`."

        Design: Difficulty/combinatorial_formula/tolling_recompute_precedes_status_derivation
        """
        case, suspension = self._setup_suspended_grievance(api)
        set_clock("2026-08-25T09:00:00.000Z")
        get_success_data(api.close_clock_suspension(suspension["id"], INTAKE))
        after = get_success_data(api.get_case_timeline(case["id"], INTAKE))
        assert after["regulatory_clock_status"] == "ON_TRACK", (
            "reachable only when the credit recompute precedes status "
            "derivation: the re-extended due 2026-09-05 is still ahead and the "
            "acknowledgment is satisfied")

        set_clock("2026-09-06T09:00:01.000Z")
        late = get_success_data(api.get_case_timeline(case["id"], INTAKE))
        assert late["regulatory_clock_status"] == "RESPONSE_BREACH", (
            "once the clock passes the tolling-adjusted due")


class TestDisjointSuspensions:
    def test_tolling_disjoint_suspensions_sum_and_duplicate_open_rejected(self, api):
        """PRD §3.5: "A case may hold only one `OPEN` suspension at a time; a
        second attempt meets `ERR_DUPLICATE_OPEN_SUSPENSION`." and "The case's
        `tolling_credit_seconds` is then recomputed by interval merge: gather
        every suspension interval of the case — an `OPEN` suspension
        contributes a provisional interval ending at the current clock reading
        — sort them by `started_at` ascending, and fuse any pair that overlaps
        or merely touches, so that when the next interval starts no later than
        the running interval's end the two become one interval whose end is the
        later of the two ends. The credit is the sum of the merged durations,
        in seconds, and both response dues re-extend by it."

        Design: Corner/calculations/tolling_disjoint_suspensions_sum_and_duplicate_open_rejected
        """
        set_clock("2026-08-01T10:00:00.000Z")
        unit = create_unit("Oncology", "INPATIENT")
        case = create_case(unit["id"], patient_ref="P-0204",
                           received_at="2026-08-01T09:00:00.000Z", channel="PHONE",
                           description="Records access concern",
                           grievance_category="COMMUNICATION")
        classify_case(case["id"], "GRIEVANCE")
        # Acknowledge inside the window so the final reading isolates tolling.
        set_clock("2026-08-02T09:00:00.000Z")
        get_success_data(api.acknowledge_case(case["id"], INTAKE))

        set_clock("2026-08-10T09:00:00.000Z")
        first = get_success_data(api.create_clock_suspension(
            case["id"], create_clock_suspension_payload(reason="AWAITING_RECORDS"),
            INTAKE))
        duplicate = api.create_clock_suspension(
            case["id"], create_clock_suspension_payload(reason="LANGUAGE_ACCESS"),
            INTAKE)
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_OPEN_SUSPENSION)

        set_clock("2026-08-15T09:00:00.000Z")
        get_success_data(api.close_clock_suspension(first["id"], INTAKE))
        set_clock("2026-08-16T09:00:00.000Z")
        second = get_success_data(api.create_clock_suspension(
            case["id"], create_clock_suspension_payload(reason="AWAITING_FAMILY"),
            INTAKE))
        set_clock("2026-08-18T09:00:00.000Z")
        get_success_data(api.close_clock_suspension(second["id"], INTAKE))

        timeline = get_success_data(api.get_case_timeline(case["id"], INTAKE))
        assert timeline["tolling_credit_seconds"] == 604800, (
            "two disjoint suspensions: 432000 + 172800 with no double counting")
        assert timeline["response_due_calendar_at"] == "2026-09-07T09:00:00.000Z", (
            "base 2026-08-31T09:00:00Z + 604800s")
        assert timeline["regulatory_clock_status"] == "ON_TRACK", (
            "the re-extended due is in the future at 2026-08-18 and the "
            "acknowledgment was recorded")


# ---------------------------------------------------------------------------
# Trend snapshot helpers
# ---------------------------------------------------------------------------
def _grievance_through_approved_letter(api, unit, inv, director, patient_ref,
                                       channel, description):
    """Full grievance lifecycle up to an APPROVED letter on shared staff."""
    case = create_case(unit["id"], patient_ref=patient_ref,
                       received_at="2026-08-10T10:00:00.000Z", channel=channel,
                       description=description, grievance_category="CARE_QUALITY")
    classify_case(case["id"], "GRIEVANCE")
    assign_investigator(case["id"], director["id"], inv["id"])
    investigation = open_investigation(case["id"], inv["id"])
    add_sufficient_notes(investigation["id"], inv["id"])
    submit_findings(investigation["id"], inv["id"])
    accept_findings(investigation["id"], director["id"])
    letter = draft_letter(case["id"], inv["id"])
    submit_letter_review(letter["id"], inv["id"])
    approve_letter(letter["id"], director["id"])
    return case, letter


def _fast_tracked_complaint(api, unit, inv, director, patient_ref, channel,
                            description):
    """Complaint classified, assigned, fast-tracked to RESPONSE_DRAFTING."""
    case = create_case(unit["id"], patient_ref=patient_ref,
                       received_at="2026-08-03T09:00:00.000Z", channel=channel,
                       description=description, grievance_category="BILLING")
    classify_case(case["id"], "COMPLAINT")
    assign_investigator(case["id"], director["id"], inv["id"])
    resp = api.fast_track_case(case["id"], INTAKE)
    assert resp.status_code == 200, f"Setup failed (fast-track): {resp.text}"
    return case


class TestTrendRateVariants:
    def _setup_two_grievance_closures(self, api):
        """Unit Med-Surg 4: case A issued ON_TIME at 2026-09-05T10:00:00Z,
        case B issued LATE (6 days) at 2026-09-15T10:00:00Z; both received
        2026-08-10T10:00:00Z with calendar due 2026-09-09T10:00:00Z."""
        set_clock("2026-08-10T12:00:00.000Z")
        unit = create_unit("Med-Surg 4", "INPATIENT")
        inv = create_staff("Ivy Investigator", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case_a, letter_a = _grievance_through_approved_letter(
            api, unit, inv, director, "P-2001", "EMAIL",
            "Case A discharge instructions missing")
        set_clock("2026-09-05T10:00:00.000Z")
        issue_letter(letter_a["id"])
        case_b, letter_b = _grievance_through_approved_letter(
            api, unit, inv, director, "P-2002", "PORTAL",
            "Case B rude staff interaction")
        set_clock("2026-09-15T10:00:00.000Z")
        issue_letter(letter_b["id"])
        return unit, director

    def test_headcount_variant_counts_breaches_over_closures(self, api):
        """PRD §3.9: "`grievances_closed` and `complaints_closed` count the
        cases on that unit and category whose `closed_at` falls inside the
        calendar month — on or after its first instant and strictly before the
        next month's — split by classification at closure; `breaches` counts
        those closed cases whose `resolution_timeliness` stands `LATE`" and
        "The headline `headcount_rate_bp` is the breach count multiplied by ten
        thousand and divided by the cell's total closures, rounded half-up to
        an integer basis point, and zero when the cell has no closures."

        Design: Difficulty/dual_variant_calc/unit_breach_rate_headcount_vs_exposure_variants
        """
        unit, director = self._setup_two_grievance_closures(api)
        computed = validate_success(api.compute_trend_snapshots(
            {"period": "2026-09"}, make_director_headers(director["id"])),
            expected_status=201)
        assert computed["cells_created"] == 1
        assert computed["system_rate_bp"] == 5000, "single populated cell"

        cells, _ = validate_paginated(api.list_trend_snapshots(
            make_director_headers(director["id"]),
            params={"unit_id": unit["id"], "period": "2026-09"}))
        assert len(cells) == 1
        cell = cells[0]
        assert cell["grievances_closed"] == 2
        assert cell["complaints_closed"] == 0
        assert cell["breaches"] == 1, "only case B closed late"
        assert cell["headcount_rate_bp"] == 5000, (
            "round_half_up(1 * 10000 / 2)")

    def test_exposure_variant_weights_days_late(self, api):
        """PRD §3.9: "The `exposure_weighted_rate_bp` weights severity of
        lateness: each late case contributes its days-late — the difference
        between its `closed_at` and its binding `response_due_calendar_at`,
        expressed in days — and each closed case contributes its window-days,
        the difference between its `received_at` and that calendar due measured
        at closure; the rate is the summed days-late multiplied by ten thousand
        and divided by the summed window-days, rounded half-up, and zero when
        the window-day total is zero."

        Design: Difficulty/dual_variant_calc/unit_breach_rate_headcount_vs_exposure_variants
        """
        unit, director = self._setup_two_grievance_closures(api)
        validate_success(api.compute_trend_snapshots(
            {"period": "2026-09"}, make_director_headers(director["id"])),
            expected_status=201)
        cells, _ = validate_paginated(api.list_trend_snapshots(
            make_director_headers(director["id"]),
            params={"unit_id": unit["id"], "period": "2026-09"}))
        cell = cells[0]
        assert cell["exposure_weighted_rate_bp"] == 1000, (
            "round_half_up(6 late-days * 10000 / (30+30) window-days)")
        assert cell["headcount_rate_bp"] != cell["exposure_weighted_rate_bp"], (
            "the dual variants diverge on identical closures: the headcount "
            "rate ignores how late the breach was")


class TestTrendSystemRateRoundingOrder:
    def _setup_five_complaint_closures(self, api):
        """U1: three BILLING complaints closed in 2026-08, one late.
        U2: two BILLING complaints closed in 2026-08, one late."""
        set_clock("2026-08-03T10:00:00.000Z")
        u1 = create_unit("Unit U1", "OUTPATIENT")
        u2 = create_unit("Unit U2", "SURGICAL")
        inv = create_staff("Ivy Investigator", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        cases = {
            "A": _fast_tracked_complaint(api, u1, inv, director, "P-U1-A",
                                         "PORTAL", "Billing question A"),
            "B": _fast_tracked_complaint(api, u1, inv, director, "P-U1-B",
                                         "PHONE", "Billing question B"),
            "C": _fast_tracked_complaint(api, u1, inv, director, "P-U1-C",
                                         "EMAIL", "Billing question C"),
            "D": _fast_tracked_complaint(api, u2, inv, director, "P-U2-D",
                                         "PORTAL", "Billing question D"),
            "E": _fast_tracked_complaint(api, u2, inv, director, "P-U2-E",
                                         "LETTER", "Billing question E"),
        }
        set_clock("2026-08-05T09:00:00.000Z")
        for key in ("A", "B", "D"):
            resp = api.close_case(
                cases[key]["id"],
                {"closure_note": f"Resolved at point of contact {key}"}, INTAKE)
            assert resp.status_code == 200, f"Setup failed (close {key}): {resp.text}"
        set_clock("2026-08-08T09:00:00.000Z")
        for key in ("C", "E"):
            resp = api.close_case(
                cases[key]["id"],
                {"closure_note": f"Resolved after delay {key}"}, INTAKE)
            assert resp.status_code == 200, f"Setup failed (close {key}): {resp.text}"
        set_clock("2026-09-01T00:00:00.000Z")
        return u1, u2, director

    def test_per_cell_rates_rounded_individually(self, api):
        """PRD §3.9: "The headline `headcount_rate_bp` is the breach count
        multiplied by ten thousand and divided by the cell's total closures,
        rounded half-up to an integer basis point, and zero when the cell has
        no closures."

        Design: Difficulty/combinatorial_formula/trend_system_rate_per_cell_rounding_order
        """
        u1, u2, director = self._setup_five_complaint_closures(api)
        computed = validate_success(api.compute_trend_snapshots(
            {"period": "2026-08"}, make_director_headers(director["id"])),
            expected_status=201)
        assert computed["cells_created"] == 2

        cells1, _ = validate_paginated(api.list_trend_snapshots(
            make_director_headers(director["id"]),
            params={"unit_id": u1["id"], "period": "2026-08"}))
        cells2, _ = validate_paginated(api.list_trend_snapshots(
            make_director_headers(director["id"]),
            params={"unit_id": u2["id"], "period": "2026-08"}))
        assert cells1[0]["headcount_rate_bp"] == 3333, (
            "round_half_up(1 * 10000 / 3) — per-cell rounding first")
        assert cells2[0]["headcount_rate_bp"] == 5000, "round_half_up(1 * 10000 / 2)"

    def test_system_rate_averages_per_cell_rounded_rates(self, api):
        """PRD §3.9: "each cell's headcount rate is first rounded half-up to an
        integer basis point, and only then is the mean of those per-cell
        rounded rates taken across cells with at least one closure, itself
        rounded half-up. Computing the system rate globally — summing breaches
        and closures before dividing — is expressly forbidden, because it
        yields a different figure."

        Design: Difficulty/combinatorial_formula/trend_system_rate_per_cell_rounding_order
        """
        _u1, _u2, director = self._setup_five_complaint_closures(api)
        computed = validate_success(api.compute_trend_snapshots(
            {"period": "2026-08"}, make_director_headers(director["id"])),
            expected_status=201)
        assert computed["system_rate_bp"] == 4167, (
            "round_half_up((3333 + 5000) / 2 = 4166.5); the forbidden global "
            "sum-then-round would yield 4000 (2 * 10000 / 5)")
        assert computed["system_rate_bp"] != 4000

    def test_snapshot_recompute_requires_force_flag(self, api):
        """PRD §3.9: "A cell that already exists for its unit, category, and
        period refuses recomputation with `ERR_SNAPSHOT_EXISTS` unless the
        request passes `force_recompute` true, in which case the row is
        upserted."

        Design: Corner/validations/snapshot_recompute_requires_force_flag
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Clinic", "OUTPATIENT")
        inv = create_staff("Ivy Investigator", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case = _fast_tracked_complaint(api, unit, inv, director, "P-0320",
                                       "PORTAL", "Billing question")
        set_clock("2026-08-05T09:00:00.000Z")
        resp = api.close_case(case["id"],
                              {"closure_note": "Resolved quickly at desk"}, INTAKE)
        assert resp.status_code == 200, f"Setup failed (close): {resp.text}"
        set_clock("2026-09-01T00:00:00.000Z")

        first = validate_success(api.compute_trend_snapshots(
            {"period": "2026-08"}, make_director_headers(director["id"])),
            expected_status=201)
        assert first["cells_created"] == 1

        duplicate = api.compute_trend_snapshots(
            {"period": "2026-08"}, make_director_headers(director["id"]))
        validate_error(duplicate, ApiErrorId.ERR_SNAPSHOT_EXISTS)

        forced = validate_success(api.compute_trend_snapshots(
            {"period": "2026-08", "force_recompute": True},
            make_director_headers(director["id"])), expected_status=201)
        assert forced["cells_created"] == 1, (
            "forced recompute upserts the existing cell")


class TestPriorityScore:
    def _setup_reopened_critical_case(self, api):
        """CRITICAL + vulnerable grievance closed 2026-08-02T00:00:00Z and
        reopened 2026-08-03T00:00:00Z (reopen_count 1)."""
        base = setup_closed_case(
            unit_name="ICU East", unit_category="ICU", clock="2026-08-01T01:00:00.000Z",
            received_at="2026-08-01T00:00:00.000Z", channel="IN_PERSON",
            description="Critical rights concern",
            grievance_category="RIGHTS_ABUSE", severity_tier="CRITICAL",
            vulnerable_patient_flag=True, issue_at="2026-08-02T00:00:00.000Z")
        set_clock("2026-08-03T00:00:00.000Z")
        validate_success(api.reopen_case(
            base.case["id"], {"reopen_reason": "Patient disputed findings"},
            make_director_headers(base.director["id"])))
        return base

    def test_priority_score_clamped_at_cap(self, api):
        """PRD §3.2: "The score starts from a severity base — twenty points for
        `STANDARD`, thirty-five for `URGENT`, fifty for `CRITICAL` — and adds
        fifteen points when `vulnerable_patient_flag` is true. An urgency
        component measures time pressure: the system takes the whole number of
        days remaining until `response_due_calendar_at`, discarding any partial
        day and treating an unset due as 999 days, subtracts that figure from
        ten, multiplies the difference by four, and clamps the result so it
        never falls below zero and never exceeds forty. Finally, a reopen bonus
        of ten points per reopen — the current `reopen_count` — is added, and
        the total is capped at one hundred."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_clamped_at_cap
        """
        base = self._setup_reopened_critical_case(api)
        set_clock("2026-08-15T00:00:00.000Z")
        timeline = get_success_data(api.get_case_timeline(
            base.case["id"], make_director_headers(base.director["id"])))
        # 50 (CRITICAL) + 15 (vulnerable) + min(40, max(0, (10-3)*4)) = 28
        # urgency + 10 reopen bonus = 103, clamped by the cap.
        assert timeline["priority_score"] == 100, (
            "raw sum 103 engages the 100 cap — proves the clamp branch")

    def test_reopen_reanchor_drives_days_remaining(self, api):
        """PRD §3.9: "Third, the regulatory dues are re-anchored:
        `response_due_calendar_at` becomes fifteen calendar days after the
        reopen instant and `response_due_business_at` fifteen business days
        after it, with `requires_qro_cosign` recomputed." PRD §3.5: "A computed
        timeline read on any case exposes `ack_due_at`,
        `response_due_calendar_at`, `response_due_business_at`,
        `tolling_credit_seconds`, `regulatory_clock_status`, `priority_score`,
        and `days_remaining` — the whole days left until the binding calendar
        due — in one shot."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_clamped_at_cap
        """
        base = self._setup_reopened_critical_case(api)
        set_clock("2026-08-15T00:00:00.000Z")
        timeline = get_success_data(api.get_case_timeline(
            base.case["id"], make_director_headers(base.director["id"])))
        assert timeline["response_due_calendar_at"] == "2026-08-18T00:00:00.000Z", (
            "reopen at 2026-08-03T00:00:00Z re-anchors +15 calendar days")
        assert timeline["days_remaining"] == 3, (
            "whole days from 2026-08-15T00:00:00Z to 2026-08-18T00:00:00Z")
