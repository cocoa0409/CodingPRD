"""Regulatory inspections: conduct gate, findings cascade, re-inspection
loop, cure certification, and the unresolved-critical-findings gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    certify_unit,
    condemn_unit_with_finding,
    conduct_inspection,
    create_building,
    create_inspection,
    create_season_window,
    create_site,
    create_unit,
    get_household,
    get_summary,
    get_tenancy,
    get_unit,
    issue_findings,
    make_compliance_inspector_headers,
    open_site,
    setup_active_tenancy,
    setup_certified_site,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
INSPECTOR = TEST_USERS["compliance_inspector_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestCondemnationCascade:
    """Difficulty instance: depth-3 cascade — CRITICAL finding -> unit
    CONDEMNED -> tenancy forced NOTICE/CONDEMNATION -> household
    rehousing_priority, and the posture recomputes to RESTRICTED."""

    def _setup(self, api):
        ctx = setup_active_tenancy(
            site_name="Site X", household_name="Fam X",
            members=(("X One", "1980-01-01", "HEAD"),
                     ("X Two", "1983-03-03", "SPOUSE")))
        inspection = create_inspection(ctx["site"]["id"], "HUD",
                                       "2026-08-20", inspector_id="ci-1")
        conduct_inspection(inspection["id"], inspector_id="ci-1")
        summary = get_summary(ctx["site"]["id"])
        assert summary["compliance_posture"] == "NORMAL", "Setup failed"
        return ctx, inspection

    def test_finding_condemns_unit_and_force_notices_tenancy(
            self, api, operator_admin_headers):
        """PRD §3.7: "Every `CRITICAL` finding then condemns its cited unit:
        from `CERTIFIED`, from `OCCUPIED`, or from `HABITABILITY_HOLD`, the
        unit moves to `CONDEMNED`. Condemnation force-notices the unit's
        residents: every tenancy on the unit in `ACTIVE` or `NOTICE` moves to
        — or remains in — `NOTICE` with `notice_reason` set to
        `CONDEMNATION`, overriding any earlier `RESIDENT` or `OPERATOR`
        reason"

        Design: Difficulty/transitive_cascade/condemnation_cascade_depth3
        """
        ctx, inspection = self._setup(api)
        issued = issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "CRITICAL",
              "code": "ELEC-EXPOSED"}], inspector_id="ci-1")
        assert issued["open_critical_count"] == 1

        unit = get_unit(ctx["unit"]["id"])
        assert unit["status"] == "CONDEMNED", (
            "Link 1: the finding condemns the cited unit")

        tenancy = get_tenancy(ctx["tenancy"]["id"])
        assert tenancy["status"] == "NOTICE", (
            "Link 2: unit condemnation force-notices the tenancy")
        assert tenancy["notice_reason"] == "CONDEMNATION"

    def test_cascade_sets_rehousing_flag_and_restricted_posture(
            self, api, operator_admin_headers):
        """PRD §3.7: "and each affected household's `rehousing_priority` flips
        to true."
        PRD §2.9: "A site is `RESTRICTED` when any of its units is
        `CONDEMNED`"

        Design: Difficulty/transitive_cascade/condemnation_cascade_depth3
        """
        ctx, inspection = self._setup(api)
        issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "CRITICAL",
              "code": "ELEC-EXPOSED"}], inspector_id="ci-1")

        household = get_household(ctx["household"]["id"])
        assert household["rehousing_priority"] is True, (
            "Link 3: the forced notice sets the household rehousing flag")

        summary = get_summary(ctx["site"]["id"])
        assert summary["compliance_posture"] == "RESTRICTED", (
            "A CONDEMNED unit forces RESTRICTED regardless of other signals")


class TestInspectionReinspectionCycle:
    """Difficulty instance: FINDINGS_ISSUED -> CONDUCTED re-inspection loop,
    then cure by a different inspector than the (second) findings issuer."""

    def _setup(self, api):
        ctx = setup_certified_site(site_name="Site I", state_code="WA")
        inspection = create_inspection(ctx["site"]["id"], "STATE_HOUSING",
                                       "2026-08-15", inspector_id="ci-1")
        assert inspection["status"] == "SCHEDULED"
        return ctx, inspection

    def test_reinspection_loop_is_legal(self, api):
        """PRD §3.7: "Re-inspection is cyclic: `FINDINGS_ISSUED → CONDUCTED`
        opens another visit, with the prior `findings` and `issued_by`
        persisting."
        PRD §3.7: "The transition records the issuer as `issued_by` and sets
        `open_critical_count` to the number of `CRITICAL` findings."

        Design: Difficulty/non_linear_state_machine/inspection_reinspection_cycle
        """
        ctx, inspection = self._setup(api)
        conduct_inspection(inspection["id"], inspector_id="ci-1")
        first = issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "MINOR",
              "code": "SCR-01"}], inspector_id="ci-1")
        assert first["open_critical_count"] == 0, "Only a MINOR finding"

        looped = validate_success(api.update_regulatory_inspection(
            inspection["id"], {"status": "CONDUCTED"},
            make_compliance_inspector_headers("ci-2")))
        assert looped["status"] == "CONDUCTED", (
            "FINDINGS_ISSUED -> CONDUCTED re-inspection loop is legal")

        second = issue_findings(inspection["id"], [], inspector_id="ci-2")
        assert second["status"] == "FINDINGS_ISSUED"
        assert second["open_critical_count"] == 0

    def test_cure_certified_by_different_inspector_then_closed(self, api):
        """PRD §3.7: "Moving `FINDINGS_ISSUED → CURE_CERTIFIED` requires the
        caller's `X-User-ID` to differ from `issued_by`
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and requires
        `open_critical_count` to have reached zero"
        PRD §3.7: "A certified inspection then closes, `CURE_CERTIFIED →
        CLOSED`; `CLOSED` and `CANCELLED` are terminal."

        Design: Difficulty/non_linear_state_machine/inspection_reinspection_cycle
        """
        ctx, inspection = self._setup(api)
        conduct_inspection(inspection["id"], inspector_id="ci-1")
        issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "MINOR",
              "code": "SCR-01"}], inspector_id="ci-1")
        api.update_regulatory_inspection(
            inspection["id"], {"status": "CONDUCTED"},
            make_compliance_inspector_headers("ci-2"))
        issue_findings(inspection["id"], [], inspector_id="ci-2")

        cure = validate_success(api.update_regulatory_inspection(
            inspection["id"], {"status": "CURE_CERTIFIED"},
            make_compliance_inspector_headers("ci-1")))
        assert cure["status"] == "CURE_CERTIFIED", (
            "Cure certifier ci-1 differs from the second findings issuer "
            "ci-2 and no critical findings are open")

        closed = validate_success(api.update_regulatory_inspection(
            inspection["id"], {"status": "CLOSED"},
            make_compliance_inspector_headers("ci-1")))
        assert closed["status"] == "CLOSED"


class TestInspectionConductGate:
    """Difficulty instance: CONDUCTED requires the site OPEN (different
    entity pair: RegulatoryInspection -> HousingSite)."""

    def _setup_draft_site_with_inspection(self, api):
        site = create_site(name="Site IO", state_code="WA")
        inspection = create_inspection(site["id"], "COUNTY_HEALTH",
                                       "2026-08-15", inspector_id="ci-1")
        return site, inspection

    def test_conduct_rejected_while_site_draft(
            self, api, compliance_inspector_headers):
        """PRD §3.7: "Conducting it — `SCHEDULED → CONDUCTED` — requires the
        site to be `OPEN` (`ERR_SITE_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/inspection_conduct_requires_site_open
        """
        site, inspection = self._setup_draft_site_with_inspection(api)
        resp = api.update_regulatory_inspection(
            inspection["id"], {"status": "CONDUCTED"},
            compliance_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPEN)

    def test_conduct_succeeds_once_site_open(self, api,
                                             compliance_inspector_headers):
        """PRD §3.7: "Conducting it — `SCHEDULED → CONDUCTED` — requires the
        site to be `OPEN` (`ERR_SITE_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/inspection_conduct_requires_site_open
        """
        site, inspection = self._setup_draft_site_with_inspection(api)
        blocked = api.update_regulatory_inspection(
            inspection["id"], {"status": "CONDUCTED"},
            compliance_inspector_headers)
        validate_error(blocked, ApiErrorId.ERR_SITE_NOT_OPEN)

        # Bring the site to OPEN: certified unit + covering window.
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        certify_unit(unit["id"])
        create_season_window(site["id"])
        opened = open_site(site["id"])
        assert opened["status"] == "OPEN", "Setup failed opening site"

        conducted = validate_success(api.update_regulatory_inspection(
            inspection["id"], {"status": "CONDUCTED"},
            compliance_inspector_headers))
        assert conducted["status"] == "CONDUCTED"


class TestUnresolvedCriticalFindingsGate:
    def test_err_unresolved_critical_findings_on_cure(
            self, api, compliance_inspector_headers):
        """PRD §3.7: "Moving `FINDINGS_ISSUED → CURE_CERTIFIED` requires the
        caller's `X-User-ID` to differ from `issued_by`
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and requires
        `open_critical_count` to have reached zero — meaning every `CRITICAL`
        finding's cited unit now holds a `PASSED` certification whose
        `inspection_date` is later than the date the findings were issued;
        any shortfall is `ERR_UNRESOLVED_CRITICAL_FINDINGS`."

        Design: Corner/errors/err_unresolved_critical_findings_on_cure
        """
        ctx = setup_certified_site(site_name="S")
        inspection = create_inspection(ctx["site"]["id"], "HUD",
                                       "2026-08-15", inspector_id="ci-1")
        conduct_inspection(inspection["id"], inspector_id="ci-1")
        issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "CRITICAL",
              "code": "ELEC-01"}], inspector_id="ci-1")

        # The only PASSED certification dates from before the findings were
        # issued (both 2026-08-01), so the critical finding remains open —
        # even a different inspector cannot certify the cure yet.
        resp = api.update_regulatory_inspection(
            inspection["id"], {"status": "CURE_CERTIFIED"},
            make_compliance_inspector_headers("ci-2"))
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_CRITICAL_FINDINGS)
