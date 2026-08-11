"""Cross-entity cascades: incident posture cascade, ISP expiry cascade,
discharge fan-out, incident close release (PRD 2.10, 2.11, 3.2, 3.3, 3.7).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    admit_resident,
    assert_same_instant,
    create_active_isp,
    create_and_verify_visit,
    create_behavior_plan_payload,
    create_evv_visit_payload,
    create_incident_payload,
    get_success_data,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_claim_for_individual,
    setup_enrolled_individual,
    setup_home,
    api_client,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]
BILL1 = TEST_USERS["billing_headers"]


def _setup_home_resident_with_draft_claim(api, clock_iso="2026-06-02T08:45:00Z"):
    """Home + resident with ACTIVE bed assignment + ACTIVE ISP + ACTIVE auth +
    one verified visit swept into a DRAFT claim."""
    ctx = setup_billable_pipeline(clock_iso=clock_iso)
    home = setup_home(ctx["agency"], certified_bed_count=2)
    admit_resident(home, ctx["individual"], ctx["cm"], ctx["q"],
                   bed_label="R1", move_in_date="2026-06-01")
    create_and_verify_visit(ctx, "2026-06-02T07:00:00Z", "2026-06-02T08:00:00Z")
    claim = setup_claim_for_individual(ctx)
    return ctx, home, claim


class TestCriticalIncidentCascade:
    """Depth-3 cascade: incident -> posture -> claim HOLD -> counter (PRD 3.7)."""

    def _trigger_critical_incident(self, ctx, home):
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(ctx["individual"]["id"], home["id"]),
            ctx["d1_headers"],
        ))
        return get_success_data(api_client.submit_incident(inc["id"], ctx["d1_headers"]))

    def test_critical_submit_sets_home_posture_critical(self, api):
        """PRD 3.7: "If any open incident has `severity` equal to `CRITICAL`,
        the posture becomes `CRITICAL`". And "The compliance posture of a home
        is recomputed at two moments: on incident submission and on incident
        closure."

        Design: Difficulty/transitive_cascade/critical_incident_cascades_home_claims_agency
        """
        ctx, home, _claim = _setup_home_resident_with_draft_claim(api)
        submitted = self._trigger_critical_incident(ctx, home)
        assert submitted["status"] == "SUBMITTED"
        home_after = get_success_data(api_client.get_home(home["id"], ANY))
        assert home_after["compliance_posture"] == "CRITICAL"

    def test_critical_submit_holds_draft_claim_and_counts_it(self, api):
        """PRD 3.7: "When a submit causes the posture to become `CRITICAL`, a
        second cascade link fires: every `DRAFT` billing claim of every
        individual who holds an `ACTIVE` bed assignment at this home transitions
        to `HOLD`, and a third link recomputes the agency's
        `held_claims_count` from these claim-hold transitions."

        Design: Difficulty/transitive_cascade/critical_incident_cascades_home_claims_agency
        """
        ctx, home, claim = _setup_home_resident_with_draft_claim(api)
        assert claim["status"] == "DRAFT"
        self._trigger_critical_incident(ctx, home)
        claim_after = get_success_data(api_client.get_claim(claim["id"], ANY))
        assert claim_after["status"] == "HOLD"
        agency = get_success_data(api_client.get_agency(ctx["agency"]["id"], ANY))
        assert agency["held_claims_count"] == 1

    def test_critical_submit_computes_due_and_lateness(self, api):
        """PRD 3.7: "On submission the server stamps `submitted_at` to now and
        computes `report_due_at` as `discovered_at` plus a severity-dependent
        window: 24 hours when `severity` is `CRITICAL`".

        Design: Difficulty/transitive_cascade/critical_incident_cascades_home_claims_agency
        """
        ctx, home, _claim = _setup_home_resident_with_draft_claim(api)
        submitted = self._trigger_critical_incident(ctx, home)
        assert_same_instant(
            submitted["report_due_at"], "2026-06-03T08:30:00Z", "report_due_at",
        )
        assert submitted["is_late"] is False


class TestIspExpiryCascade:
    """Clock-driven ISP expiry cascade: ISP -> authorizations -> visits (PRD 3.3)."""

    def _setup_expiring_pipeline(self, api):
        ctx = setup_billable_pipeline(
            clock_iso="2026-06-02T00:00:00Z",
            authorized_units=24, rate_cents=1500,
            span_start="2026-01-01", span_end="2026-06-30",
            plan_year_start="2026-01-01", plan_year_end="2026-06-30",
        )
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                service_date="2026-06-15",
                check_in_at="2026-06-15T09:00:00Z",
                check_out_at="2026-06-15T10:00:00Z",
            ), ctx["d1_headers"],
        ))
        return ctx, visit

    def test_clock_crossing_plan_year_end_expires_isp_and_suspends_auth(self, api):
        """PRD 3.3: "when the logical clock advances past `plan_year_end`, an
        `ACTIVE` ISP transitions automatically to `EXPIRED`. This transition
        fires a two-link cascade: every `ACTIVE` service authorization anchored
        to this individual transitions to `SUSPENDED` (link 1)".

        Design: Difficulty/transitive_cascade/isp_expiry_cascades_authorizations_visits
        """
        ctx, _visit = self._setup_expiring_pipeline(api)
        set_clock("2026-07-01T00:00:00Z")
        isp = get_success_data(api_client.get_isp(ctx["isp"]["id"], ANY))
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert isp["status"] == "EXPIRED"
        assert auth["status"] == "SUSPENDED"

    def test_authorization_suspension_rejects_pending_visits(self, api):
        """PRD 3.3: "each such suspended authorization in turn transitions all
        of its EVV visits that are in `PENDING` or `EXCEPTION` to `REJECTED`
        (link 2)."

        Design: Difficulty/transitive_cascade/isp_expiry_cascades_authorizations_visits
        """
        ctx, visit = self._setup_expiring_pipeline(api)
        set_clock("2026-07-01T00:00:00Z")
        visit_after = get_success_data(api_client.get_evv_visit(visit["id"], ANY))
        assert visit_after["verification_status"] == "REJECTED"
        assert visit_after["billing_status"] == "UNBILLED"


class TestIndividualDischargeCascade:
    """Maximal fan-out discharge cascade (PRD 3.2)."""

    def _setup_discharge_scenario(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        isp = create_active_isp(ind, cm, q)
        from test_helpers import create_active_authorization
        auth = create_active_authorization(ind, isp, cm, q)
        # LEVEL_1 BSP fully activated.
        bp = get_success_data(api_client.create_behavior_plan(
            create_behavior_plan_payload(ind["id"], level="LEVEL_1", restrictive_interventions=[]),
            make_case_manager_headers(cm["id"]),
        ))
        get_success_data(api_client.submit_behavior_plan_hrc(bp["id"], make_case_manager_headers(cm["id"])))
        get_success_data(api_client.hrc_approve_behavior_plan(bp["id"], make_qidp_headers(q["id"])))
        bp = get_success_data(api_client.activate_behavior_plan(bp["id"], make_qidp_headers(q["id"])))
        ba = admit_resident(home, ind, cm, q, bed_label="R1")
        return {"home": home, "ind": ind, "isp": isp, "auth": auth, "bp": bp, "ba": ba, "q": q}

    def test_discharge_sets_individual_discharged_and_ends_bed_assignment(self, api):
        """PRD 3.2: "Discharge, also performed by a `QIDP`,
        transitions an `ENROLLED` individual to the terminal state
        `DISCHARGED` and triggers the widest cascade in the system. On
        discharge: every `ACTIVE` bed assignment of the individual transitions
        to `ENDED` with `move_out_date` set to today".

        Design: Corner/state_machines/individual_discharge_cascades_all_children
        """
        s = self._setup_discharge_scenario(api)
        discharged = get_success_data(api_client.discharge_individual(
            s["ind"]["id"], make_qidp_headers(s["q"]["id"]),
        ))
        assert discharged["status"] == "DISCHARGED"
        ba = get_success_data(api_client.get_bed_assignment(s["ba"]["id"], ANY))
        assert ba["status"] == "ENDED"
        assert ba["move_out_date"] == "2026-06-01"
        home = get_success_data(api_client.get_home(s["home"]["id"], ANY))
        assert home["current_occupancy"] == 0

    def test_discharge_cancels_authorization_discontinues_isp_expires_bsp(self, api):
        """PRD 3.2: "every service authorization of the individual in `PENDING`,
        `APPROVED`, `ACTIVE`, or `SUSPENDED` transitions to `CANCELLED` ...;
        every `ACTIVE` ISP of the individual transitions to `DISCONTINUED`;
        every `ACTIVE` behavior support plan of the individual transitions to
        `EXPIRED`".

        Design: Corner/state_machines/individual_discharge_cascades_all_children
        """
        s = self._setup_discharge_scenario(api)
        get_success_data(api_client.discharge_individual(
            s["ind"]["id"], make_qidp_headers(s["q"]["id"]),
        ))
        auth = get_success_data(api_client.get_authorization(s["auth"]["id"], ANY))
        assert auth["status"] == "CANCELLED"
        isp = get_success_data(api_client.get_isp(s["isp"]["id"], ANY))
        assert isp["status"] == "DISCONTINUED"
        bp = get_success_data(api_client.get_behavior_plan(s["bp"]["id"], ANY))
        assert bp["status"] == "EXPIRED"


class TestIncidentCloseReleasesHeldClaims:
    """Inverse cascade: closing the CRITICAL incident releases HOLD (PRD 3.7)."""

    def _setup_held_claim_state(self, api):
        ctx, home, claim = _setup_home_resident_with_draft_claim(api)
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(
                ctx["individual"]["id"], home["id"],
                category="ELOPEMENT", severity="CRITICAL",
                description="Resident left the home unsupervised",
            ),
            ctx["d1_headers"],
        ))
        get_success_data(api_client.submit_incident(inc["id"], ctx["d1_headers"]))
        get_success_data(api_client.start_incident_review(inc["id"], ctx["q_headers"]))
        return ctx, home, claim, inc

    def test_close_returns_claim_to_draft(self, api):
        """PRD 3.7: "When a close causes the posture to fall below `CRITICAL`,
        the inverse cascade fires: every `HOLD` billing claim of residents of
        this home transitions back to `DRAFT`".

        Design: Corner/cross_cutting_layers/incident_close_releases_held_claims
        """
        ctx, home, claim, inc = self._setup_held_claim_state(api)
        # Sanity: the claim was held by the submit cascade.
        assert get_success_data(api_client.get_claim(claim["id"], ANY))["status"] == "HOLD"
        closed = get_success_data(api_client.close_incident(inc["id"], ctx["q_headers"]))
        assert closed["status"] == "CLOSED"
        claim_after = get_success_data(api_client.get_claim(claim["id"], ANY))
        assert claim_after["status"] == "DRAFT"

    def test_close_recomputes_posture_and_held_counter(self, api):
        """PRD 3.7: "the agency's `held_claims_count` is recomputed" and
        "otherwise the posture is `GOOD_STANDING`" once no open incident
        remains.

        Design: Corner/cross_cutting_layers/incident_close_releases_held_claims
        """
        ctx, home, _claim, inc = self._setup_held_claim_state(api)
        get_success_data(api_client.close_incident(inc["id"], ctx["q_headers"]))
        home_after = get_success_data(api_client.get_home(home["id"], ANY))
        assert home_after["compliance_posture"] == "GOOD_STANDING"
        agency = get_success_data(api_client.get_agency(ctx["agency"]["id"], ANY))
        assert agency["held_claims_count"] == 0


class TestProvisionalPostureNoHold:
    """HIGH incident yields PROVISIONAL without the HOLD cascade (PRD 3.7)."""

    def test_high_incident_sets_provisional_not_critical(self, api):
        """PRD 3.7: "otherwise, if any open incident has `severity` equal to
        `HIGH`, the posture becomes `PROVISIONAL`".

        Design: Corner/calculations/posture_provisional_on_high_incident_no_hold
        """
        ctx, home, _claim = _setup_home_resident_with_draft_claim(api)
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(
                ctx["individual"]["id"], home["id"],
                severity="HIGH",
                description="Resident cut hand on broken glass",
            ),
            ctx["d1_headers"],
        ))
        get_success_data(api_client.submit_incident(inc["id"], ctx["d1_headers"]))
        home_after = get_success_data(api_client.get_home(home["id"], ANY))
        assert home_after["compliance_posture"] == "PROVISIONAL"

    def test_high_incident_does_not_hold_draft_claims(self, api):
        """PRD 3.7: "When a submit causes the posture to become `CRITICAL`, a
        second cascade link fires: every `DRAFT` billing claim ... transitions
        to `HOLD`" — the cascade is conditioned on CRITICAL, not PROVISIONAL.

        Design: Corner/calculations/posture_provisional_on_high_incident_no_hold
        """
        ctx, home, claim = _setup_home_resident_with_draft_claim(api)
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(
                ctx["individual"]["id"], home["id"],
                severity="HIGH",
                description="Resident cut hand on broken glass",
            ),
            ctx["d1_headers"],
        ))
        get_success_data(api_client.submit_incident(inc["id"], ctx["d1_headers"]))
        claim_after = get_success_data(api_client.get_claim(claim["id"], ANY))
        assert claim_after["status"] == "DRAFT"
        agency = get_success_data(api_client.get_agency(ctx["agency"]["id"], ANY))
        assert agency["held_claims_count"] == 0
