"""Optimistic concurrency on finalize/override and segregation of duties."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_organizer_headers,
    create_criteria_scores,
    create_open_event, setup_judging_event, judge_create_and_submit_sheet,
    finalize_event, list_event_awards,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


def _tabulating_judged_event(api):
    """Judged event -> TABULATING with one entry and one submitted (now locked)
    sheet. Returns (setup, registration_id)."""
    s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                            num_judges=1)
    reg_id = s["registrations"][0]["id"]
    judge_create_and_submit_sheet(
        reg_id, s["judges"][0]["id"],
        criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                               authenticity=9, condition=8))
    return s, reg_id


class TestFinalizeOcc:
    def test_finalize_occ_success_increments_version(self, api):
        """PRD §3.6: "The caller's `X-User-ID` is recorded as the event's
        `finalized_by_user_id`, and the event's `version` increments." PRD §3.6:
        "each recomputed award walks `PENDING` → `COMPUTED` → `FINALIZED` within
        the same request."

        Design: Corner/endpoints/finalize_occ_success_increments_version
        """
        s, reg_id = _tabulating_judged_event(api)
        before = validate_success(api.get_event(s["event"]["id"], ORG))
        out = validate_success(api.finalize_tabulations(
            s["event"]["id"], {"expected_event_version": before["version"]}, ORG))
        assert out["lifecycle_status"] == "FINALIZED"
        assert out["version"] == before["version"] + 1
        assert out["finalized_by_user_id"] == ORG["X-User-ID"]
        awards = list_event_awards(s["event"]["id"])
        assert len(awards) > 0
        for a in awards:
            assert a["status"] == "FINALIZED"

    def test_finalize_occ_stale_version_returns_412(self, api):
        """PRD §2.8: "Finalizing tabulation requires the request to carry
        `expected_event_version`, holding the event `version` the caller last
        observed. If the event's version has advanced since that read — a weather
        decision, a treasury-moving payment, or an earlier finalization all
        advance it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/finalize_occ_stale_version_returns_412
        """
        # A people's-choice-only event may finalize straight from JUDGING.
        ev, cls, zone = create_open_event()
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        observed = validate_success(api.get_event(ev["id"], ORG))
        first = validate_success(api.finalize_tabulations(
            ev["id"], {"expected_event_version": observed["version"]}, ORG))
        assert first["lifecycle_status"] == "FINALIZED"
        resp = api.finalize_tabulations(
            ev["id"], {"expected_event_version": observed["version"]}, ORG)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestOverrideOcc:
    def _setup_finalized_award(self, api):
        """Event finalized by 'org-final'; returns (setup, reg_id, award)."""
        s, reg_id = _tabulating_judged_event(api)
        ev = validate_success(api.get_event(s["event"]["id"], ORG))
        get_success_data(api.finalize_tabulations(
            s["event"]["id"], {"expected_event_version": ev["version"]},
            make_organizer_headers("org-final")))
        awards = list_event_awards(s["event"]["id"])
        award = next(a for a in awards
                     if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        return s, reg_id, award

    def test_override_occ_stale_returns_412(self, api):
        """PRD §2.8: "Overriding an award winner requires `expected_award_version`,
        holding the award's last observed `version`. An override legitimately
        supersedes the stored winner, so a stale view must fail rather than
        silently re-supersede a winner set by a more recent override or
        recompute; a mismatch against the award's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/override_occ_stale_returns_412
        """
        s, reg_id, award = self._setup_finalized_award(api)
        stale_version = award["version"]
        first = validate_success(api.override_winner(
            award["id"],
            {"winner_registration_id": reg_id, "expected_award_version": stale_version,
             "reason": "first override"},
            make_organizer_headers("org-second")))
        assert first["overridden"] is True
        resp = api.override_winner(
            award["id"],
            {"winner_registration_id": reg_id, "expected_award_version": stale_version,
             "reason": "stale replay"},
            make_organizer_headers("org-third"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_award(award["id"], ORG))
        assert after["version"] == first["version"], "stale replay must not bump the version"
        assert after["winner_registration_id"] == reg_id


class TestSegregationOfDuties:
    def test_override_segregation_of_duties_rejected(self, api):
        """PRD §3.6: "Segregation of duties applies: the caller must differ from
        the event's `finalized_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, so
        the organizer who finalized the tabulation cannot also hand-pick winners."
        and "A successful override sets the winner, marks the award `overridden`,
        writes `MANUAL_OVERRIDE` into `tie_break_log`, and lands the award in
        `FINALIZED`".

        Design: Corner/validations/override_segregation_of_duties_rejected
        """
        s, reg_id, award = TestOverrideOcc()._setup_finalized_award(api)
        resp = api.override_winner(
            award["id"],
            {"winner_registration_id": reg_id,
             "expected_award_version": award["version"], "reason": "recount"},
            make_organizer_headers("org-final"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_award(award["id"], ORG))
        ok = validate_success(api.override_winner(
            award["id"],
            {"winner_registration_id": reg_id,
             "expected_award_version": current["version"], "reason": "recount confirmed"},
            make_organizer_headers("org-second")))
        assert ok["overridden"] is True
        assert ok["tie_break_log"] == "MANUAL_OVERRIDE"
