"""RBAC and segregation-of-duties tests (PRD §2.1, §2.7)."""
from test_helpers import (
    ApiErrorId,
    MED_HEADERS,
    advance_target_to_offered,
    api_client,
    area_headers,
    create_budget,
    create_director,
    create_flag,
    create_free_agent_target,
    create_prospect,
    create_report,
    create_roster_need,
    create_scout,
    director_headers,
    get_success_data,
    submit_report,
    validate_error,
)


class TestReportOwnership:
    def test_area_scout_cannot_lock_report(self, api):
        """PRD §2.1: "Access to specific operations is further restricted by
        role; an attempt to perform an action outside the caller's designated
        role is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 scopes
        POST /scouting/reports/{id}/lock to ScoutingDirector.

        Design: Corner/rbac/area_scout_cannot_lock_report
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        resp = api_client.lock_report(r1["id"], area_headers(s1))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_scout_b_cannot_submit_other_report(self, api):
        """PRD §2.1: "Only the authoring scout — that is, a caller whose
        `X-User-ID` equals the report's `scout_id` — may submit that report or
        attach video tags to it; any other scout attempting either is rejected
        with `ERR_REPORT_NOT_OWNED` (HTTP 403)."

        Design: Corner/rbac/scout_b_cannot_submit_other_report
        """
        sa = create_scout(level="AREA", full_name="A")
        sb = create_scout(level="AREA", full_name="B")
        p1 = create_prospect(sa, full_name="P", position="QB", college="A")
        r1 = create_report(p1["id"], sa, raw_grade=7.00, scheme_fit=1.00)
        resp = api_client.submit_report(r1["id"], area_headers(sb))
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_OWNED)
        assert resp.status_code == 403


class TestFlagClearance:
    def test_area_scout_cannot_create_medical_flag(self, api):
        """PRD §2.1: "a `MEDICAL` flag may be created only by `MedicalStaff`,
        while a `CHARACTER` flag may be created only by an `AreaScout` or
        `ScoutingDirector`; crossing that boundary is rejected with
        `ERR_FLAG_ACCESS_DENIED` (HTTP 403)."

        Design: Corner/rbac/area_scout_cannot_create_medical_flag
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        resp = api_client.create_flag(
            p1["id"],
            {"flag_type": "MEDICAL", "severity": "LOW", "detail": "hamstring"},
            area_headers(s1),
        )
        validate_error(resp, ApiErrorId.ERR_FLAG_ACCESS_DENIED)
        assert resp.status_code == 403

    def test_medical_staff_cannot_create_character_flag(self, api):
        """PRD §2.1: symmetric segregation — "a `CHARACTER` flag may be
        created only by an `AreaScout` or `ScoutingDirector`"; MedicalStaff
        attempting CHARACTER is rejected `ERR_FLAG_ACCESS_DENIED`.

        Design: Corner/rbac/medical_staff_cannot_create_character_flag
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        resp = api_client.create_flag(
            p1["id"],
            {"flag_type": "CHARACTER", "severity": "LOW", "detail": "attitude"},
            MED_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FLAG_ACCESS_DENIED)
        assert resp.status_code == 403


class TestFrontOfficeExclusivity:
    def test_director_cannot_sign_target(self, api):
        """PRD §2.7: "The front-office `GeneralManager` owns scouts, budgets,
        roster needs, free-agency targets, facilities, and the post-draft
        record". PRD §4 scopes POST /scouting/free-agent-targets/{id}/sign to
        GeneralManager; a ScoutingDirector calling it is rejected
        `ERR_FORBIDDEN` (§2.1).

        Design: Corner/rbac/director_cannot_sign_target
        """
        d1 = create_director(full_name="D")
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        create_roster_need(season_year=2026, position="QB", priority_tier="P3")
        t1 = create_free_agent_target(
            player_name="Vet", position="QB", season_year=2026,
            base_salary_cents=1000, signing_bonus_cents=0, contract_years=1,
        )
        advance_target_to_offered(t1["id"])
        resp = api_client.sign_target(
            t1["id"], {"budget_id": bud["id"]}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403


class TestMedicalRedaction:
    def test_medical_detail_redacted_for_area_scout(self, api):
        """PRD §2.7: "`MedicalStaff` is the sole author of `MEDICAL` flags and
        the sole role that ever sees a MEDICAL flag's `detail` field
        unredacted; for any other role reading flags, the `detail` of a
        `MEDICAL` flag is returned as `null`."

        Design: Corner/rbac/medical_detail_redacted_for_area_scout
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        create_flag(
            p1["id"], MED_HEADERS,
            flag_type="MEDICAL", severity="HIGH", detail="torn acl",
        )
        redacted = get_success_data(api_client.list_flags(p1["id"], area_headers(s1)))
        assert redacted[0]["flag_type"] == "MEDICAL"
        assert redacted[0]["detail"] is None, "MEDICAL detail must be null for AreaScout"
        visible = get_success_data(api_client.list_flags(p1["id"], MED_HEADERS))
        assert visible[0]["detail"] == "torn acl"


class TestAuthzPrecedesExistence:
    def test_authz_precedes_existence_forbidden(self, api):
        """PRD §2.9: "2. Authorization — role permitted on the endpoint,
        entity-backed identity's scout `level` matches, report-ownership on
        submit / video-tag, flag-type clearance on flag creation
        (`ERR_FORBIDDEN`, `ERR_REPORT_NOT_OWNED`, `ERR_FLAG_ACCESS_DENIED`).
        ... 4. Existence — every referenced id resolves (`ERR_NOT_FOUND`)."
        GET /scouting/budgets/{id} is GM/Director-only (§4); an AreaScout
        reading a non-existent budget id is rejected `ERR_FORBIDDEN`, not
        `ERR_NOT_FOUND`.

        Design: Corner/validations/authz_precedes_existence_forbidden
        """
        from test_helpers import NON_EXISTENT_UUID

        s1 = create_scout(level="AREA", full_name="S")
        resp = api_client.get_budget(NON_EXISTENT_UUID, area_headers(s1))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
