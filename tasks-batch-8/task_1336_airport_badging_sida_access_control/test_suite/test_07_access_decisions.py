"""Door access decisions against the fixed zone catalogue and event logging."""
from test_helpers import (
    ACS,
    BO,
    access_check_payload,
    api_client,
    assert_access_event,
    grant_escort_privilege,
    setup_issued_badge,
    suspend_badge,
    validate_paginated,
    validate_success,
)


class TestAccessDecisionRules:

    def test_access_badgeless_attempt_denied_no_badge(self):
        """PRD section 3.7: "A null `badge_id` is denied with
        `DENIED_NO_BADGE`."
        PRD section 3.7: "Each access check supplies a `zone_code`, an
        optional `badge_id` — null for a badgeless attempt — and an optional
        `escortee_count` defaulting to zero, and produces an `AccessEvent` row
        recording the `decision`, the `denial_reason` when refused, and
        `occurred_at` from the logical clock."

        Design: Corner/calculations/access_badgeless_attempt_denied_no_badge
        """
        resp = api_client.create_access_check(
            access_check_payload("PUBLIC_TERMINAL"), ACS)
        data = validate_success(resp, expected_status=201)
        assert_access_event(data)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_NO_BADGE"
        assert data["badge_id"] is None

    def test_access_zone_class_denied(self):
        """PRD section 3.7: "`SECURE_ID_AREA` admits only `SIDA` badges and
        forbids escorted entry entirely."
        PRD section 3.7: "A badge whose `badge_class` is outside the zone's
        admitted set is denied with `DENIED_ZONE_CLASS`."

        Design: Corner/calculations/access_zone_class_denied
        """
        ctx = setup_issued_badge(badge_class="STERILE", badge_number="B901")
        resp = api_client.create_access_check(
            access_check_payload("SECURE_ID_AREA", badge_id=ctx["badge"]["id"]),
            ACS)
        data = validate_success(resp, expected_status=201)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_ZONE_CLASS"
        assert data["zone_code"] == "SECURE_ID_AREA"

    def test_access_escort_zone_forbidden(self):
        """PRD section 3.7: "When the `escortee_count` is positive, three
        further tests apply in order: a zone that forbids escorted entry
        denies with `DENIED_ESCORT_NOT_PERMITTED`; a badge with no `GRANTED`
        escort privilege denies with `DENIED_ESCORT_NOT_PERMITTED`; and a
        party larger than the privilege's `max_escortees` denies with
        `DENIED_ESCORT_CAPACITY` — the boundary is inclusive, so a party
        exactly equal to `max_escortees` is admitted."

        Design: Corner/calculations/access_escort_zone_forbidden
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1001")
        badge = ctx["badge"]
        grant_escort_privilege(badge["id"], badge["version"], max_escortees=3)

        resp = api_client.create_access_check(
            access_check_payload("SECURE_ID_AREA", badge_id=badge["id"],
                                 escortee_count=1),
            ACS)
        data = validate_success(resp, expected_status=201)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_ESCORT_NOT_PERMITTED", \
            "the zone forbids escorted entry regardless of the privilege"

    def test_access_escort_without_privilege(self):
        """PRD section 3.7: "`STERILE_CONCOURSE` admits `SIDA` and `STERILE`
        badges and permits escorted entry."
        PRD section 3.7: "a badge with no `GRANTED` escort privilege denies
        with `DENIED_ESCORT_NOT_PERMITTED`".

        Design: Corner/calculations/access_escort_without_privilege
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1101")
        badge_id = ctx["badge"]["id"]

        solo = api_client.create_access_check(
            access_check_payload("STERILE_CONCOURSE", badge_id=badge_id), ACS)
        assert validate_success(solo, expected_status=201)["decision"] == "ALLOWED"

        escorted = api_client.create_access_check(
            access_check_payload("STERILE_CONCOURSE", badge_id=badge_id,
                                 escortee_count=2),
            ACS)
        data = validate_success(escorted, expected_status=201)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_ESCORT_NOT_PERMITTED"

    def test_escort_capacity_boundary_inclusive(self):
        """PRD section 3.7: "and a party larger than the privilege's
        `max_escortees` denies with `DENIED_ESCORT_CAPACITY` — the boundary is
        inclusive, so a party exactly equal to `max_escortees` is admitted."

        Design: Corner/calculations/escort_capacity_boundary_inclusive
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1201")
        badge = ctx["badge"]
        grant_escort_privilege(badge["id"], badge["version"], max_escortees=3)

        at_cap = api_client.create_access_check(
            access_check_payload("AOA_MOVEMENT", badge_id=badge["id"],
                                 escortee_count=3),
            ACS)
        assert validate_success(at_cap, expected_status=201)["decision"] == "ALLOWED", \
            "escortee_count == max_escortees is admitted"

        over_cap = api_client.create_access_check(
            access_check_payload("AOA_MOVEMENT", badge_id=badge["id"],
                                 escortee_count=4),
            ACS)
        data = validate_success(over_cap, expected_status=201)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_ESCORT_CAPACITY"


class TestAccessDecisionBadgeStatusDependency:

    def _sida_badge(self):
        ctx = setup_issued_badge(sponsor_code="AC", sponsor_name="AeroClean",
                                 badge_class="SIDA", badge_number="B1201",
                                 full_name="Wes Yost",
                                 government_id_number="G9501",
                                 date_of_birth="1994-09-27")
        return ctx["badge"]

    def test_access_allowed_while_badge_active(self):
        """PRD section 3.7: "A presentation surviving every test is logged
        with `decision` `ALLOWED` and a null `denial_reason`."

        Design: Difficulty/cross_entity_state_dependency/access_decision_flips_on_badge_status
        """
        badge = self._sida_badge()
        resp = api_client.create_access_check(
            access_check_payload("SECURE_ID_AREA", badge_id=badge["id"]), ACS)
        data = validate_success(resp, expected_status=201)
        assert data["decision"] == "ALLOWED"
        assert data["denial_reason"] is None, \
            "SIDA is in SECURE_ID_AREA's admitted set"

    def test_access_denied_once_badge_suspended(self):
        """PRD section 3.7: "A badge not in `ACTIVE` status is denied with
        `DENIED_BADGE_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/access_decision_flips_on_badge_status
        """
        badge = self._sida_badge()
        before = api_client.create_access_check(
            access_check_payload("SECURE_ID_AREA", badge_id=badge["id"]), ACS)
        assert validate_success(before, expected_status=201)["decision"] == "ALLOWED"

        suspend_badge(badge["id"], manager_id="mgr-1", reason="pending review")

        after = api_client.create_access_check(
            access_check_payload("SECURE_ID_AREA", badge_id=badge["id"]), ACS)
        data = validate_success(after, expected_status=201)
        assert data["decision"] == "DENIED"
        assert data["denial_reason"] == "DENIED_BADGE_INACTIVE", \
            "same badge, same zone — the decision keys on badge status"


class TestAccessEventLog:

    def test_access_events_recorded_and_listed_in_order(self):
        """PRD section 3.7: "A denial is a logged business outcome, not a
        fault: the check returns 201 Created with `decision` set to `DENIED`
        and the appropriate reason, never an error response."
        PRD section 2.3: "Unless otherwise specified, all list endpoints
        return resources sorted by their creation timestamp in ascending
        order."

        Design: Corner/endpoints/access_events_recorded_and_listed_in_order
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B2401")
        badge_id = ctx["badge"]["id"]

        e1 = validate_success(
            api_client.create_access_check(
                access_check_payload("AOA_MOVEMENT", badge_id=badge_id), ACS),
            expected_status=201)
        assert e1["decision"] == "ALLOWED"

        e2 = validate_success(
            api_client.create_access_check(
                access_check_payload("SECURE_ID_AREA", badge_id=badge_id,
                                     escortee_count=1),
                ACS),
            expected_status=201)
        assert e2["decision"] == "DENIED"
        assert e2["denial_reason"] == "DENIED_ESCORT_NOT_PERMITTED"

        lst, meta = validate_paginated(
            api_client.list_access_events(badge_id, BO))
        assert meta["total_count"] == 2
        assert [row["id"] for row in lst] == [e1["id"], e2["id"]], \
            "events are listed in created_at ascending order"
        assert lst[0]["zone_code"] == "AOA_MOVEMENT"
        assert lst[0]["occurred_at"] == "2026-08-01T00:00:00Z", \
            "occurred_at is stamped from the logical clock"
