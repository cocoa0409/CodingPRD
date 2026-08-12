"""Medication orders, MAR events, behavior support plans (PRD 3.6, 3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_admin_event,
    assert_same_instant,
    create_admin_event_payload,
    create_behavior_plan_payload,
    create_individual_payload,
    create_medication_order_payload,
    get_success_data,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_enrolled_individual,
    setup_staff,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


def _setup_med_pipeline(api):
    """Agency + cm/q/d1(MED_CERT) + ENROLLED individual + clock 2026-06-01."""
    base = setup_agency_with_clinical_staff()
    ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
    set_clock("2026-06-01T00:00:00Z")
    return base, ind


def _create_order(api, ind, q, **overrides):
    return get_success_data(api_client.create_medication_order(
        create_medication_order_payload(ind["id"], **overrides),
        make_qidp_headers(q["id"]),
    ))


class TestMedAdminBlockedWhenOrderDiscontinued:
    """MAR events rejected against a DISCONTINUED order (PRD 3.6)."""

    def test_admin_event_on_discontinued_order_rejected(self, api):
        """PRD 3.6: "once discontinued, no further administration events may be
        recorded against the order (a recording attempt rejects with
        `ERR_MED_ORDER_DISCONTINUED`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/med_admin_blocked_when_order_discontinued
        """
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        get_success_data(api_client.discontinue_medication_order(
            mo["id"], make_qidp_headers(base["q"]["id"]),
        ))
        resp = api_client.create_admin_event(
            create_admin_event_payload(mo["id"]),
            make_dsp_headers(base["d1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MED_ORDER_DISCONTINUED)

    def test_rejected_event_not_persisted(self, api):
        """PRD 3.6: "no further administration events may be recorded against
        the order" — the rejected write leaves no record.

        Design: Difficulty/cross_entity_state_dependency/med_admin_blocked_when_order_discontinued
        """
        from test_helpers import make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        get_success_data(api_client.discontinue_medication_order(
            mo["id"], make_qidp_headers(base["q"]["id"]),
        ))
        validate_error(
            api_client.create_admin_event(
                create_admin_event_payload(mo["id"]),
                make_dsp_headers(base["d1"]["id"]),
            ),
            ApiErrorId.ERR_MED_ORDER_DISCONTINUED,
        )
        _data, meta = validate_paginated(api_client.list_admin_events(
            ANY, params={"medication_order_id": mo["id"]},
        ))
        assert meta["total_count"] == 0


class TestMedAdminEventImmutability:
    """MAR event shape: id + created_at only, no version (PRD 2.4)."""

    def test_admin_event_carries_no_version_or_updated_at(self, api):
        """PRD 2.4: "It carries only `id` and `created_at`; both `updated_at`
        and `version` are absent, and the record is immutable once written."

        Design: Corner/entities/med_admin_event_immutable_no_version_field
        """
        from test_helpers import assert_admin_event, make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        ev = get_success_data(api_client.create_admin_event(
            create_admin_event_payload(mo["id"]),
            make_dsp_headers(base["d1"]["id"]),
        ))
        assert_admin_event(ev)

    def test_admin_event_records_administrator_from_user_header(self, api):
        """PRD 3.6: "On creation the system writes `administered_by_staff_id`
        from the caller's `X-User-ID`."

        Design: Corner/entities/med_admin_event_immutable_no_version_field
        """
        from test_helpers import make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        ev = get_success_data(api_client.create_admin_event(
            create_admin_event_payload(mo["id"]),
            make_dsp_headers(base["d1"]["id"]),
        ))
        assert ev["administered_by_staff_id"] == base["d1"]["id"]


class TestMarWindowBoundary:
    """+/- 60 minute administration window (PRD 3.6)."""

    def test_administered_75_minutes_late_rejected(self, api):
        """PRD 3.6: "when present it must lie within sixty minutes before or
        after the `scheduled_time`; a deviation outside that window rejects
        with `ERR_OUT_OF_SPAN` (HTTP 422)."

        Design: Corner/validations/admin_event_outside_sixty_minute_window_rejected
        """
        from test_helpers import make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        resp = api_client.create_admin_event(
            create_admin_event_payload(
                mo["id"],
                scheduled_time="2026-06-02T08:00:00Z",
                administered_time="2026-06-02T09:15:00Z",
            ),
            make_dsp_headers(base["d1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_SPAN)

    def test_administered_exactly_60_minutes_late_accepted(self, api):
        """PRD 3.6: "it must lie within sixty minutes before or after the
        `scheduled_time`" — exactly 60 minutes is within the window.

        Design: Corner/validations/admin_event_outside_sixty_minute_window_rejected
        """
        from test_helpers import make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"])
        ev = get_success_data(api_client.create_admin_event(
            create_admin_event_payload(
                mo["id"],
                scheduled_time="2026-06-03T08:00:00Z",
                administered_time="2026-06-03T09:00:00Z",
            ),
            make_dsp_headers(base["d1"]["id"]),
        ))
        assert ev["outcome"] == "GIVEN"


class TestWitnessRules:
    """Witness requirement conditional on requires_witness + GIVEN (PRD 3.6)."""

    def _setup_witness_order(self, api):
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"], drug_name="Oxycodone", dosage="5mg",
                           requires_witness=True)
        return base, mo

    def test_given_without_witness_rejected(self, api):
        """PRD 3.6: "when the linked order's `requires_witness` is `true` and
        the `outcome` is `GIVEN`, the `witness_staff_id` must be present and
        must not equal `administered_by_staff_id`; a missing or self-witness
        rejects with `ERR_WITNESS_REQUIRED` (HTTP 400)."

        Design: Corner/validations/witness_required_rules_for_controlled_med
        """
        from test_helpers import make_dsp_headers
        base, mo = self._setup_witness_order(api)
        resp = api_client.create_admin_event(
            create_admin_event_payload(mo["id"]),
            make_dsp_headers(base["d1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WITNESS_REQUIRED)

    def test_given_with_self_witness_rejected(self, api):
        """PRD 3.6: "the `witness_staff_id` must be present and must not equal
        `administered_by_staff_id`; a missing or self-witness rejects with
        `ERR_WITNESS_REQUIRED` (HTTP 400)."

        Design: Corner/validations/witness_required_rules_for_controlled_med
        """
        from test_helpers import make_dsp_headers
        base, mo = self._setup_witness_order(api)
        resp = api_client.create_admin_event(
            create_admin_event_payload(mo["id"], witness_staff_id=base["d1"]["id"]),
            make_dsp_headers(base["d1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WITNESS_REQUIRED)

    def test_refused_without_witness_accepted(self, api):
        """PRD 3.6: the witness rule applies "when the linked order's
        `requires_witness` is `true` and the `outcome` is `GIVEN`" — REFUSED is
        outside the condition.

        Design: Corner/validations/witness_required_rules_for_controlled_med
        """
        from test_helpers import make_dsp_headers
        base, mo = self._setup_witness_order(api)
        ev = get_success_data(api_client.create_admin_event(
            create_admin_event_payload(mo["id"], outcome="REFUSED"),
            make_dsp_headers(base["d1"]["id"]),
        ))
        assert ev["outcome"] == "REFUSED"

    def test_given_with_distinct_witness_accepted(self, api):
        """PRD 3.6: a present, non-self witness satisfies the rule.

        Design: Corner/validations/witness_required_rules_for_controlled_med
        """
        from test_helpers import make_dsp_headers
        base, mo = self._setup_witness_order(api)
        ev = get_success_data(api_client.create_admin_event(
            create_admin_event_payload(mo["id"], witness_staff_id=base["q"]["id"]),
            make_dsp_headers(base["d1"]["id"]),
        ))
        assert ev["witness_staff_id"] == base["q"]["id"]


class TestMedAdherence:
    """30-day closed-window adherence computation (PRD 3.6)."""

    def _setup_adherence_events(self, api):
        from test_helpers import make_dsp_headers
        base, ind = _setup_med_pipeline(api)
        mo = _create_order(api, ind, base["q"],
                           schedule_times=["08:00", "12:00"], start_date="2026-05-01")
        d1_h = make_dsp_headers(base["d1"]["id"])
        events = [
            # Boundary: exactly as_of - 30d -> included.
            ("2026-05-31T12:00:00Z", "2026-05-31T12:00:00Z", "GIVEN"),
            # One minute before the window -> excluded.
            ("2026-05-31T11:59:00Z", "2026-05-31T11:59:00Z", "GIVEN"),
            ("2026-06-15T08:00:00Z", "2026-06-15T08:10:00Z", "REFUSED"),
            # At as_of itself -> included.
            ("2026-06-30T12:00:00Z", "2026-06-30T12:00:00Z", "GIVEN"),
        ]
        for sched, admin, outcome in events:
            get_success_data(api_client.create_admin_event(
                create_admin_event_payload(
                    mo["id"], scheduled_time=sched,
                    administered_time=admin, outcome=outcome,
                ), d1_h,
            ))
        return ind

    def test_closed_window_includes_lower_bound_excludes_before(self, api):
        """PRD 3.6: "The window is the thirty-day span ending at `as_of`,
        closed on both ends - an event whose `scheduled_time` falls exactly at
        `as_of` minus thirty days is included."

        Design: Corner/calculations/med_adherence_closed_window_boundary
        """
        ind = self._setup_adherence_events(api)
        data = validate_success(api.get_med_adherence(ind["id"], ANY, "2026-06-30T12:00:00Z"))
        assert_same_instant(data["window_start"], "2026-05-31T12:00:00Z", "window_start")
        assert data["total_events"] == 3

    def test_adherence_percentage_floored(self, api):
        """PRD 3.6: "The adherence percentage is the floor of one hundred times
        the count of events with `outcome` equal to `GIVEN` divided by the
        total event count."

        Design: Corner/calculations/med_adherence_closed_window_boundary
        """
        ind = self._setup_adherence_events(api)
        data = validate_success(api.get_med_adherence(ind["id"], ANY, "2026-06-30T12:00:00Z"))
        assert data["given_count"] == 2
        assert data["adherence_pct"] == 66  # floor(100 * 2/3)

    def test_empty_window_returns_null_adherence(self, api):
        """PRD 3.6: "When the window contains no events, `adherence_pct` is
        null."

        Design: Corner/calculations/med_adherence_empty_window_returns_null
        """
        base, ind = _setup_med_pipeline(api)
        _create_order(api, ind, base["q"])
        data = validate_success(api.get_med_adherence(ind["id"], ANY, "2026-06-30T12:00:00Z"))
        assert data["total_events"] == 0
        assert data["adherence_pct"] is None


class TestMedOrderRequiresEnrolledIndividual:
    """Medication order creation gated on enrollment (PRD 3.2, 3.6)."""

    def test_order_for_applicant_rejected(self, api):
        """PRD 3.2: "an individual must be `ENROLLED` for ISP activation,
        behavior-plan activation, service-authorization creation, bed-assignment
        creation, medication-order creation, incident creation, EVV visit
        creation, transport-leg inclusion, and claim generation; when the rule
        bites, the rejection is `ERR_INDIVIDUAL_NOT_ENROLLED` (HTTP 409)."

        Design: Corner/validations/med_order_requires_enrolled_individual
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        # Individual registered but never enrolled (stays APPLICANT).
        ind = get_success_data(api_client.create_individual(
            create_individual_payload(agency["id"]),
            make_case_manager_headers(cm["id"]),
        ))
        resp = api_client.create_medication_order(
            create_medication_order_payload(ind["id"]),
            make_qidp_headers(q["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INDIVIDUAL_NOT_ENROLLED)


class TestBspLevelInterventionMismatch:
    """LEVEL vs restrictive_interventions consistency at submit-hrc (PRD 3.7)."""

    def _setup_two_mismatched_plans(self, api):
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        bp_l2_empty = get_success_data(api_client.create_behavior_plan(
            create_behavior_plan_payload(ind["id"], level="LEVEL_2", restrictive_interventions=[]),
            make_case_manager_headers(base["cm"]["id"]),
        ))
        bp_l1_filled = get_success_data(api_client.create_behavior_plan(
            create_behavior_plan_payload(ind["id"], level="LEVEL_1",
                                         restrictive_interventions=["locked-door"]),
            make_case_manager_headers(base["cm"]["id"]),
        ))
        return base, bp_l2_empty, bp_l1_filled

    def test_level2_with_empty_interventions_rejected(self, api):
        """PRD 3.7: "a `LEVEL_2` plan must carry a non-empty
        `restrictive_interventions` array, and a `LEVEL_1` plan must carry an
        empty one; a mismatch rejects with
        `ERR_RESTRICTIVE_INTERVENTION_MISMATCH` (HTTP 400)."

        Design: Corner/validations/bsp_level_restrictive_intervention_mismatch
        """
        base, bp_l2_empty, _ = self._setup_two_mismatched_plans(api)
        resp = api_client.submit_behavior_plan_hrc(
            bp_l2_empty["id"], make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTIVE_INTERVENTION_MISMATCH)

    def test_level1_with_interventions_rejected_and_stays_draft(self, api):
        """PRD 3.7: "a `LEVEL_1` plan must carry an empty one; a mismatch
        rejects with `ERR_RESTRICTIVE_INTERVENTION_MISMATCH` (HTTP 400)."

        Design: Corner/validations/bsp_level_restrictive_intervention_mismatch
        """
        base, bp_l2_empty, bp_l1_filled = self._setup_two_mismatched_plans(api)
        resp = api_client.submit_behavior_plan_hrc(
            bp_l1_filled["id"], make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTIVE_INTERVENTION_MISMATCH)
        # Both plans remain DRAFT.
        assert get_success_data(api_client.get_behavior_plan(bp_l2_empty["id"], ANY))["status"] == "DRAFT"
        assert get_success_data(api_client.get_behavior_plan(bp_l1_filled["id"], ANY))["status"] == "DRAFT"


class TestBspActivateSupersedesPrior:
    """BSP activation supersedes prior ACTIVE and sets review_due_at (PRD 3.7)."""

    def _setup_two_level2_plans(self, api):
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        cm_h = make_case_manager_headers(base["cm"]["id"])
        q_h = make_qidp_headers(base["q"]["id"])

        def walk(plan_overrides):
            bp = get_success_data(api_client.create_behavior_plan(
                create_behavior_plan_payload(ind["id"], **plan_overrides), cm_h,
            ))
            get_success_data(api_client.submit_behavior_plan_hrc(bp["id"], cm_h))
            get_success_data(api_client.hrc_approve_behavior_plan(bp["id"], q_h))
            return bp

        bp1 = walk({"level": "LEVEL_2", "restrictive_interventions": ["locked-door"]})
        bp1_active = get_success_data(api_client.activate_behavior_plan(bp1["id"], q_h))
        bp2 = walk({"level": "LEVEL_2",
                    "restrictive_interventions": ["locked-door", "chemical-restraint-review"]})
        return bp1_active, bp2, q_h, ind

    def test_level2_activation_sets_review_due_180_days(self, api):
        """PRD 3.7: "sets `review_due_at` to `approved_at` plus 180 days for a
        `LEVEL_2` plan or plus 365 days for a `LEVEL_1` plan".

        Design: Corner/state_machines/bsp_activate_supersedes_prior_and_sets_review_due
        """
        bp1_active, _bp2, _q_h, _ind = self._setup_two_level2_plans(api)
        # approved 2026-06-01 (clock) + 180 days = 2026-11-28.
        assert bp1_active["status"] == "ACTIVE"
        assert_same_instant(bp1_active["review_due_at"], "2026-11-28T00:00:00Z", "review_due_at")

    def test_second_activation_supersedes_first(self, api):
        """PRD 3.7: "supersedes any other `ACTIVE` plan for the same individual
        (that prior plan transitions to `SUPERSEDED`)".

        Design: Corner/state_machines/bsp_activate_supersedes_prior_and_sets_review_due
        """
        bp1_active, bp2, q_h, ind = self._setup_two_level2_plans(api)
        bp2_active = get_success_data(api_client.activate_behavior_plan(bp2["id"], q_h))
        assert bp2_active["status"] == "ACTIVE"
        assert_same_instant(bp2_active["review_due_at"], "2026-11-28T00:00:00Z", "review_due_at")
        superseded, meta = validate_paginated(api_client.list_behavior_plans(
            ANY, params={"individual_id": ind["id"], "status": "SUPERSEDED"},
        ))
        assert meta["total_count"] == 1
        assert superseded[0]["id"] == bp1_active["id"]
