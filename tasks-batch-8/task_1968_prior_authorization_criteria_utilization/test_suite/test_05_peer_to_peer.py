"""Peer-to-peer conferences: scheduling geometry, gating, resolution (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    basic_um_environment,
    escalated_request,
    get_determination,
    list_conferences,
    list_request_determinations,
    make_medical_director_headers,
    md_decide,
    resolve_conference,
    scheduled_conference,
    validate_error,
)


def _three_escalated_requests(provider_id, criteria_set_id):
    return [
        escalated_request(
            provider_id, criteria_set_id, member_ref=f"M-{i:02d}",
            reviewer_user_id="u-rev-1",
        )
        for i in range(1, 4)
    ]


class TestHalfOpenIntervalGeometry:
    def test_adjacent_conferences_allowed(self, api):
        """PRD §3.3: "Two conflict rules guard the calendar under `ERR_P2P_SCHEDULE_CONFLICT` (HTTP 409): the new half-open interval must not intersect any other `SCHEDULED` conference of the same medical director — intervals that merely touch at an endpoint do not conflict — and a request may have at most one `SCHEDULED` conference at a time."

        Design: Difficulty/resource_temporal_overlap/p2p_half_open_adjacency_vs_overlap
        """
        provider, cs, _gv = basic_um_environment()
        r1, r2, _r3 = _three_escalated_requests(provider["id"], cs["id"])
        c1 = scheduled_conference(
            r1["id"], md_user_id="u-md-9",
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T11:00:00Z",
        )
        assert c1["status"] == "SCHEDULED"
        # Starts exactly when c1 ends: touching endpoints do not conflict.
        c2 = scheduled_conference(
            r2["id"], md_user_id="u-md-9",
            scheduled_start="2026-08-10T11:00:00Z",
            scheduled_end="2026-08-10T12:00:00Z",
        )
        assert c2["status"] == "SCHEDULED"

    def test_overlapping_conference_rejected(self, api):
        """PRD §3.3: "Two conflict rules guard the calendar under `ERR_P2P_SCHEDULE_CONFLICT` (HTTP 409): the new half-open interval must not intersect any other `SCHEDULED` conference of the same medical director — intervals that merely touch at an endpoint do not conflict — and a request may have at most one `SCHEDULED` conference at a time."

        Design: Difficulty/resource_temporal_overlap/p2p_half_open_adjacency_vs_overlap
        """
        provider, cs, _gv = basic_um_environment()
        r1, r2, r3 = _three_escalated_requests(provider["id"], cs["id"])
        scheduled_conference(
            r1["id"], md_user_id="u-md-9",
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T11:00:00Z",
        )
        scheduled_conference(
            r2["id"], md_user_id="u-md-9",
            scheduled_start="2026-08-10T11:00:00Z",
            scheduled_end="2026-08-10T12:00:00Z",
        )
        # 10:30-11:30 intersects [10:00,11:00) for the same medical director.
        resp = api.schedule_p2p_conference(
            r3["id"],
            {"scheduled_start": "2026-08-10T10:30:00Z",
             "scheduled_end": "2026-08-10T11:30:00Z"},
            make_medical_director_headers("u-md-9"),
        )
        validate_error(resp, ApiErrorId.ERR_P2P_SCHEDULE_CONFLICT)


class TestConferenceGatesMdDenial:
    def test_md_deny_blocked_while_conference_scheduled(self, api):
        """PRD §3.3: "`DENY` requires one of the three denial reason codes and is additionally blocked while any peer-to-peer conference for the request is `SCHEDULED` — that block surfaces `ERR_P2P_CONFERENCE_OUTSTANDING`."
        PRD §2.8: "Finally, a medical-director denial is blocked while any conference for the same request remains `SCHEDULED`, surfacing `ERR_P2P_CONFERENCE_OUTSTANDING` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/md_deny_blocked_by_scheduled_p2p
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(provider["id"], cs["id"], reviewer_user_id="u-rev-1")
        scheduled_conference(req["id"], md_user_id="u-md-1")
        resp = api.md_decision(
            req["id"],
            {"decision": "DENY", "reason_code": "MEDICAL_NECESSITY_NOT_MET"},
            make_medical_director_headers("u-md-1"),
        )
        validate_error(resp, ApiErrorId.ERR_P2P_CONFERENCE_OUTSTANDING)

    def test_denial_allowed_after_conference_resolved(self, api):
        """PRD §3.3: "The scheduling medical director later resolves the conference by supplying an `outcome` of `COMPLETED` or `NO_SHOW`; resolution requires the conference to be `SCHEDULED` (`ERR_P2P_NOT_RESOLVABLE`) and the caller to equal `md_user_id` (`ERR_NOT_ASSIGNED_MD`). Either resolution unblocks the medical-director denial path for the request."

        Design: Difficulty/cross_entity_state_dependency/md_deny_blocked_by_scheduled_p2p
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(provider["id"], cs["id"], reviewer_user_id="u-rev-1")
        conference = scheduled_conference(req["id"], md_user_id="u-md-1")
        resp = api.md_decision(
            req["id"],
            {"decision": "DENY", "reason_code": "MEDICAL_NECESSITY_NOT_MET"},
            make_medical_director_headers("u-md-1"),
        )
        validate_error(resp, ApiErrorId.ERR_P2P_CONFERENCE_OUTSTANDING)
        resolved = resolve_conference(conference["id"], "NO_SHOW", md_user_id="u-md-1")
        assert resolved["status"] == "NO_SHOW"
        denied = md_decide(
            req["id"], "DENY", reason_code="MEDICAL_NECESSITY_NOT_MET",
            user_id="u-md-1",
        )
        assert denied["status"] == "DENIED"
        det = get_determination(list_request_determinations(req["id"])[0]["id"])
        assert det["decided_by_role"] == "MEDICAL_DIRECTOR"
        assert det["reason_code"] == "MEDICAL_NECESSITY_NOT_MET"


class TestResolveRules:
    def test_resolve_after_completed_rejected(self, api):
        """PRD §3.3: "The scheduling medical director later resolves the conference by supplying an `outcome` of `COMPLETED` or `NO_SHOW`; resolution requires the conference to be `SCHEDULED` (`ERR_P2P_NOT_RESOLVABLE`) and the caller to equal `md_user_id` (`ERR_NOT_ASSIGNED_MD`)."

        Design: Corner/state_machines/p2p_resolve_after_completed_rejected
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(provider["id"], cs["id"], reviewer_user_id="u-rev-1")
        conference = scheduled_conference(req["id"], md_user_id="u-md-1")
        resolve_conference(conference["id"], "COMPLETED", md_user_id="u-md-1")
        resp = api.resolve_p2p_conference(
            conference["id"], {"outcome": "NO_SHOW"},
            make_medical_director_headers("u-md-1"),
        )
        validate_error(resp, ApiErrorId.ERR_P2P_NOT_RESOLVABLE)
        assert list_conferences(req["id"])[0]["status"] == "COMPLETED"

    def test_resolve_by_other_md_rejected(self, api):
        """PRD §2.8: "A peer-to-peer conference must be resolved by the medical director who scheduled it — the caller must equal the conference's `md_user_id`, else `ERR_NOT_ASSIGNED_MD`."

        Design: Corner/validations/resolve_by_other_md_rejected
        """
        provider, cs, _gv = basic_um_environment()
        req = escalated_request(provider["id"], cs["id"], reviewer_user_id="u-rev-1")
        conference = scheduled_conference(req["id"], md_user_id="u-md-1")
        resp = api.resolve_p2p_conference(
            conference["id"], {"outcome": "COMPLETED"},
            make_medical_director_headers("u-md-2"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_MD)
        assert list_conferences(req["id"])[0]["status"] == "SCHEDULED", (
            "unresolved"
        )
