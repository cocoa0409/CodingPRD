"""Safety observation loop, escalation cascade, media linkage and day bounds."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_delivery,
    add_incident,
    add_media,
    add_safety_observation,
    assert_instant_equal,
    create_media_attachment_payload,
    get_report,
    get_safety_observation,
    make_active_project,
    make_delivery_zone,
    make_report,
    make_report_bundle,
    make_work_area,
    set_clock,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SO = TEST_USERS["safety_officer_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestObservationLoop:
    def test_mitigated_reopen_cycle_and_verify_close_from_open_rejected(self, api):
        """PRD section 3.5: "A mitigated finding can regress: reopening moves
        `MITIGATED` back to `OPEN`. Any of these actions from the wrong status
        fails with `ERR_OBSERVATION_INVALID_TRANSITION`".

        Design: Corner/state_machines/safety_observation_reopen_cycle
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        obs = add_safety_observation(ctx["report"]["id"], ctx["area"]["id"],
                                     description="Unguarded edge")
        mitigated = validate_success(api.mitigate_observation(obs["id"], _SO))
        assert mitigated["status"] == "MITIGATED"

        reopened = validate_success(api.reopen_observation(obs["id"], _SO))
        assert reopened["status"] == "OPEN"

        # verify-close is defined only from MITIGATED; from OPEN it is invalid.
        resp = api.verify_close_observation(
            obs["id"], {"X-User-ID": "so-2", "X-User-Role": "SafetyOfficer",
                        "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_OBSERVATION_INVALID_TRANSITION)
        assert resp.status_code == 409

    def test_escalate_creates_linked_incident_and_holds_distribution(self, api):
        """PRD section 3.5: "escalation moves it from `OPEN` to the terminal
        `ESCALATED` and simultaneously creates a linked incident." and "The
        created incident references the observation through
        `safety_observation_id`, stamps `occurred_at` with the logical clock,
        starts at severity `MEDICAL_TREATMENT` in `REPORTED` status" and "The
        new open incident immediately recomputes the report's posture flags:
        `has_open_incident` flips to true, `distribution_hold` follows it to
        true, and every `PENDING` distribution record on the report flips to
        `BLOCKED`".

        Design: Corner/state_machines/escalate_creates_linked_incident_and_blocks_distribution
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        set_clock("2026-08-05T17:00:00Z")
        obs = add_safety_observation(
            ctx["report"]["id"], ctx["area"]["id"],
            description="Repeat ladder violation observed at stairwell 3 east "
                        "during the morning safety walk")

        escalated = validate_success(api.escalate_observation(obs["id"], _SO))
        assert escalated["status"] == "ESCALATED"
        assert escalated["incident_id"], "escalation must set incident_id"

        incident = validate_success(api.get_incident(escalated["incident_id"], _SO))
        assert incident["status"] == "REPORTED"
        assert incident["safety_observation_id"] == obs["id"]
        assert incident["severity"] == "MEDICAL_TREATMENT"
        assert incident["recordable"] is True
        assert_instant_equal(incident["occurred_at"], "2026-08-05T17:00:00Z")

        report = get_report(ctx["report"]["id"])
        assert report["has_open_incident"] is True
        assert report["distribution_hold"] is True
        assert report["retention_class"] == "CLAIMS_HOLD"

    def test_high_risk_observation_requires_media(self, api):
        """PRD section 3.5: "A `HIGH`-risk observation must be evidenced: it is
        rejected without a `media_attachment_id`, failing with
        `ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA`".

        Design: Corner/validations/high_risk_observation_requires_media
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)

        resp = api.create_safety_observation(
            {"report_id": ctx["report"]["id"], "work_area_id": ctx["area"]["id"],
             "description": "Live exposed conductor", "risk_level": "HIGH"},
            _SO)
        validate_error(resp, ApiErrorId.ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA)
        assert resp.status_code == 422

        ok = validate_success(api.create_safety_observation(
            {"report_id": ctx["report"]["id"], "work_area_id": ctx["area"]["id"],
             "description": "Housekeeping debris", "risk_level": "MEDIUM"},
            _SO), 201)
        assert ok["status"] == "OPEN"


class TestMediaAttachment:
    def test_link_constraint_and_gps_pair(self, api):
        """PRD section 3.6: "supplying exactly one of `gps_lat` and `gps_lng` is
        rejected with `ERR_GPS_INCOMPLETE_PAIR`. A single attachment supports at
        most one evidentiary link — `linked_incident_id` or `linked_delivery_id`,
        never both, else `ERR_MEDIA_LINK_CONSTRAINT`".

        Design: Corner/validations/media_link_constraint_and_gps_pair
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        zone = make_delivery_zone(project["id"])
        report = make_report(project["id"])
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=10,
                                unit="LF", material_description="Pipe")
        set_clock("2026-08-05T17:00:00Z")
        incident = add_incident(report["id"], area["id"],
                                occurred_at="2026-08-05T10:00:00Z")

        both_links = api.create_media_attachment(
            create_media_attachment_payload(
                report["id"], area["id"], captured_at="2026-08-05T11:00:00Z",
                linked_incident_id=incident["id"],
                linked_delivery_id=delivery["id"]),
            _SUPT)
        validate_error(both_links, ApiErrorId.ERR_MEDIA_LINK_CONSTRAINT)
        assert both_links.status_code == 422

        half_gps = api.create_media_attachment(
            create_media_attachment_payload(
                report["id"], area["id"], captured_at="2026-08-05T11:00:00Z",
                gps_lat=37.77),
            _SUPT)
        validate_error(half_gps, ApiErrorId.ERR_GPS_INCOMPLETE_PAIR)
        assert half_gps.status_code == 422

    def test_captured_at_day_boundary_half_open(self, api):
        """PRD section 3.6: "the `captured_at` instant — which, like a weather
        observation, must fall within the `report_date` calendar day from
        midnight UTC inclusive to the following midnight exclusive, else
        `ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE`."

        Design: Corner/validations/media_captured_at_day_boundary
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]

        inside = validate_success(api.create_media_attachment(
            create_media_attachment_payload(rid, aid, media_type="PHOTO",
                                            captured_at="2026-08-05T00:00:00Z"),
            _SUPT), 201)
        assert inside["id"]

        outside = api.create_media_attachment(
            create_media_attachment_payload(rid, aid, media_type="PHOTO",
                                            captured_at="2026-08-06T00:00:00Z"),
            _SUPT)
        validate_error(outside, ApiErrorId.ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE)
        assert outside.status_code == 422

    def test_purge_blocked_when_linked_and_clears_observation_reference(self, api):
        """PRD section 3.6: "media linked to an incident may never be purged —
        the attempt fails with `ERR_MEDIA_LINKED_TO_INCIDENT`. When purged media
        was referenced by an `OPEN` or `MITIGATED` safety observation's
        `media_attachment_id`, the purge clears that reference to null."

        Design: Corner/cross_cutting_layers/media_purge_blocked_when_linked_to_incident
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T17:00:00Z")

        incident = add_incident(rid, aid, occurred_at="2026-08-05T09:00:00Z")
        m1 = add_media(rid, aid, role="SafetyOfficer", user_id="so-1",
                       captured_at="2026-08-05T09:05:00Z",
                       linked_incident_id=incident["id"])
        m2 = add_media(rid, aid, captured_at="2026-08-05T09:10:00Z")
        obs = add_safety_observation(rid, aid, risk_level="HIGH",
                                     media_attachment_id=m2["id"],
                                     description="Unguarded rebar caps missing "
                                                 "at deck edge")

        blocked = api.purge_media_attachment(m1["id"], _SUPT)
        validate_error(blocked, ApiErrorId.ERR_MEDIA_LINKED_TO_INCIDENT)
        assert blocked.status_code == 409

        purged = validate_success(api.purge_media_attachment(m2["id"], _SUPT))
        assert purged["status"] == "PURGED"

        obs_after = get_safety_observation(obs["id"])
        assert obs_after["media_attachment_id"] is None, \
            "purge must clear the referencing observation's media_attachment_id"
