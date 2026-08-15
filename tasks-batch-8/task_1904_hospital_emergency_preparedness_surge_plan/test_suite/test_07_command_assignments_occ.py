"""Command role assignments: OCC stale-version rejection, fresh-version success,
relieve-and-reassign, and the qualification gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assess_surge,
    assert_command_role_assignment,
    create_command_assignment,
    create_command_assignment_payload,
    create_command_qualified_staff,
    create_incident,
    create_staff_member,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_expected_incident_version_rejected(self, api):
        """PRD §2.8: "The request must carry `expected_incident_version`, set to
        the target incident's `version` as the client last observed it. If the
        incident's current `version` no longer matches the supplied value —
        because another writer has advanced it since the client last read the
        incident, for instance by creating a command assignment of their own — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412) and no assignment
        is written."
        PRD §2.11: "7. Optimistic concurrency (§2.8): `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_expected_incident_version_rejected
        """
        q1 = create_command_qualified_staff("INCIDENT_COMMANDER", full_name="Q Four")
        q2 = create_command_qualified_staff("INCIDENT_COMMANDER", full_name="Q Five")
        incident = create_incident(incident_name="MCI-occ", incident_type="HUMAN")
        assessed = assess_surge(incident["id"], 100, 50)
        observed_version = assessed["version"]

        first = validate_success(
            api.create_command_assignment(
                create_command_assignment_payload(
                    incident["id"], q1["id"], "INCIDENT_COMMANDER", observed_version
                ),
                IC,
            ),
            expected_status=201,
        )
        assert_command_role_assignment(first)

        # The first create advanced the incident's version; the second writer's
        # copy of that version is now stale.
        resp = api.create_command_assignment(
            create_command_assignment_payload(
                incident["id"], q2["id"], "SAFETY_OFFICER", observed_version
            ),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        rows, meta = validate_paginated(
            api.list_command_assignments(IC, params={"staff_member_id": q2["id"]})
        )
        assert meta["total_count"] == 0, "no assignment is written on a stale create"

    def test_occ_fresh_version_succeeds_and_increments(self, api):
        """PRD §3.5: "The new assignment stamps `assigned_at` and opens in
        `ACTIVE`, and the incident's `version` advances by one — which is precisely
        what invalidates any other commander's stale `expected_incident_version`."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every mutation of the resource, and which backs the optimistic
        concurrency control described in §2.8."

        Design: Corner/cross_cutting_layers/occ_fresh_version_succeeds_and_increments
        """
        q1 = create_command_qualified_staff("LOGISTICS_CHIEF", full_name="Q Six")
        incident = create_incident(incident_name="MCI-occ2", incident_type="HUMAN")
        observed_version = incident["version"]

        assignment = create_command_assignment(
            incident["id"], q1["id"], "LOGISTICS_CHIEF", observed_version
        )
        assert assignment["status"] == "ACTIVE"

        reread = validate_success(api.get_incident(incident["id"], IC))
        assert reread["version"] == observed_version + 1, (
            "the incident's version advances by exactly one per assignment create"
        )


class TestRelieveAndReassign:
    def test_command_assignment_reassignment_relieves_prior(self, api):
        """PRD §3.5: "Assignment is relieve-and-reassign: creating a new assignment
        for the same incident and command role automatically transitions any
        existing `ACTIVE` assignment for that pairing to `RELIEVED`, so exactly one
        holder is ever `ACTIVE` per role per incident."
        PRD §3.5: "The assignments list supports optional `incident_id`,
        `staff_member_id`, and `status` filters."

        Design: Corner/state_machines/command_assignment_reassignment_relieves_prior
        """
        q1 = create_command_qualified_staff("INCIDENT_COMMANDER", full_name="Q One")
        q2 = create_command_qualified_staff("INCIDENT_COMMANDER", full_name="Q Two")
        incident = create_incident(incident_name="MCI-relieve", incident_type="HUMAN")

        a1 = create_command_assignment(
            incident["id"], q1["id"], "INCIDENT_COMMANDER", incident["version"]
        )
        v1 = validate_success(api.get_incident(incident["id"], IC))["version"]
        a2 = create_command_assignment(
            incident["id"], q2["id"], "INCIDENT_COMMANDER", v1
        )

        first = validate_success(api.get_command_assignment(a1["id"], IC))
        assert first["status"] == "RELIEVED", "prior holder relieved automatically"
        assert_command_role_assignment(a2)
        assert a2["status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api.list_command_assignments(
                IC, params={"incident_id": incident["id"], "status": "RELIEVED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == a1["id"]


class TestQualificationGate:
    def test_command_assignment_unqualified_staff_rejected(self, api):
        """PRD §3.5: "The assignee must hold the named role in
        `role_qualifications`, otherwise the create is rejected with
        `ERR_STAFF_NOT_QUALIFIED`."

        Design: Corner/validations/command_assignment_unqualified_staff_rejected
        """
        nurse = create_staff_member(full_name="Q Three", department="NURSING",
                                    role_qualifications=["SAFETY_OFFICER"])
        incident = create_incident(incident_name="MCI-qual", incident_type="HUMAN")
        resp = api.create_command_assignment(
            create_command_assignment_payload(
                incident["id"], nurse["id"], "INCIDENT_COMMANDER", incident["version"]
            ),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_STAFF_NOT_QUALIFIED)
