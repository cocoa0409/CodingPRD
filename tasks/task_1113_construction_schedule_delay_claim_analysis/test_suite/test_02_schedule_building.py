"""Building the CPM schedule: activity defaults, logic-tie integrity,
and cycle safety on the schedule DAG (PRD §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_activity,
    assert_activity_relationship,
    create_activity_payload,
    create_relationship_payload,
    create_project,
    create_schedule_version,
    add_activity,
    add_relationship,
)


def _project_with_draft_baseline():
    project = create_project()
    version = create_schedule_version(project["id"], kind="BASELINE")
    return project, version


class TestActivityDefaults:
    def test_activity_remaining_duration_defaults_to_original(
        self, api, contractor_headers
    ):
        """PRD §3.2: "The `remaining_duration_days` may be supplied but defaults to
        the original duration when omitted, and it may never exceed the original
        duration."

        Design: Corner/entities/activity_remaining_duration_defaults_to_original
        """
        project, version = _project_with_draft_baseline()
        resp = api.create_activity(
            project["id"],
            version["id"],
            create_activity_payload(activity_code="X", original_duration_days=7),
            contractor_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_activity(data)
        assert data["remaining_duration_days"] == 7, (
            "omitted remaining_duration_days must default to original_duration_days"
        )


class TestRelationshipResource:
    def test_activity_relationship_carries_only_id_and_created_at(
        self, api, contractor_headers, pce_headers
    ):
        """PRD §2.5: "Two sub-resources are deliberately lighter: an activity
        relationship and a progress entry carry only `id` and `created_at`. Both
        `updated_at` and `version` are absent on them, since neither is ever mutated
        after creation."

        Design: Corner/entities/activity_relationship_immutable_no_update_endpoint
        """
        project, version = _project_with_draft_baseline()
        a = add_activity(project["id"], version["id"], "A", 5)
        b = add_activity(project["id"], version["id"], "B", 5)
        add_relationship(project["id"], version["id"], a["id"], b["id"])
        resp = api.list_relationships(project["id"], version["id"], pce_headers)
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        rel = data[0]
        assert_activity_relationship(rel)
        assert "updated_at" not in rel, "relationship must not expose updated_at"
        assert "version" not in rel, "relationship must not expose version"

    def test_self_relationship_rejected(self, api, contractor_headers):
        """PRD §3.2: "A relationship whose predecessor and successor are the same
        activity is rejected with `ERR_SELF_RELATIONSHIP`, and both ends must belong
        to the same schedule version (`ERR_ACTIVITY_NOT_IN_VERSION`)."

        Design: Corner/errors/self_relationship_rejected
        """
        project, version = _project_with_draft_baseline()
        a = add_activity(project["id"], version["id"], "A", 5)
        resp = api.create_relationship(
            project["id"],
            version["id"],
            create_relationship_payload(a["id"], a["id"]),
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SELF_RELATIONSHIP)

    def test_invalid_relationship_type_rejected(self, api, contractor_headers):
        """PRD §3.2: "Four tie types are recognized — finish-to-start (`FS`),
        start-to-start (`SS`), finish-to-finish (`FF`), and start-to-finish (`SF`);
        any other value is rejected with `ERR_INVALID_RELATIONSHIP_TYPE`."

        Design: Corner/errors/invalid_relationship_type_rejected
        """
        project, version = _project_with_draft_baseline()
        a = add_activity(project["id"], version["id"], "A", 5)
        b = add_activity(project["id"], version["id"], "B", 5)
        resp = api.create_relationship(
            project["id"],
            version["id"],
            create_relationship_payload(a["id"], b["id"], relationship_type="XX"),
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RELATIONSHIP_TYPE)


class TestCycleSafety:
    def test_back_edge_relationship_rejected_as_cycle(self, api, contractor_headers):
        """PRD §3.2: "Because the activities and their ties form a directed acyclic
        graph, every inserted tie is cycle-checked against the augmented network,
        and a tie that would close a cycle is rejected with `ERR_CYCLE_DETECTED`;
        per §2.6 this cycle check fires before the membership check."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_relationship
        """
        project, version = _project_with_draft_baseline()
        a = add_activity(project["id"], version["id"], "A", 5)
        b = add_activity(project["id"], version["id"], "B", 5)
        add_relationship(project["id"], version["id"], a["id"], b["id"])
        # Inserting B -> A closes a two-node cycle on the augmented graph.
        resp = api.create_relationship(
            project["id"],
            version["id"],
            create_relationship_payload(b["id"], a["id"]),
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_DETECTED)

    def test_three_node_cycle_rejected_as_cycle(self, api, contractor_headers):
        """PRD §3.2: "Because the activities and their ties form a directed acyclic
        graph, every inserted tie is cycle-checked against the augmented network,
        and a tie that would close a cycle is rejected with `ERR_CYCLE_DETECTED`;
        per §2.6 this cycle check fires before the membership check."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_relationship
        """
        project, version = _project_with_draft_baseline()
        a = add_activity(project["id"], version["id"], "A", 5)
        b = add_activity(project["id"], version["id"], "B", 5)
        c = add_activity(project["id"], version["id"], "C", 5)
        add_relationship(project["id"], version["id"], a["id"], b["id"])
        add_relationship(project["id"], version["id"], b["id"], c["id"])
        # Inserting C -> A closes a three-node cycle on the augmented graph.
        resp = api.create_relationship(
            project["id"],
            version["id"],
            create_relationship_payload(c["id"], a["id"]),
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_DETECTED)
