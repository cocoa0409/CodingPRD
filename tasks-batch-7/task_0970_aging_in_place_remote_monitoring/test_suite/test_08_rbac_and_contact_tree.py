"""Authentication and role enforcement, validation pipeline ordering, and
contact-tree referential/fiscal checks plus delete semantics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_senior,
    factories,
    fixtures,
    get_success_data,
    make_caregiver_headers,
    setup_senior_with_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HUB = TEST_USERS["device_hub_headers"]


class TestAuthentication:
    def test_seniors_list_missing_auth_headers_returns_401(self, api):
        """PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, declaring the caller's
        operational capacity. A request missing either header, or carrying a
        role the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/seniors_list_missing_auth_headers_returns_401
        """
        resp = api.list_seniors({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_devicehub_cannot_read_admin_resources(self, api):
        """PRD 2.1: "Once authenticated, the caller's role must appear in the
        endpoint's authorized role list; otherwise the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD 4: "| GET | `/v1/seniors` | List seniors | PlatformAdmin,
        MonitoringAgent |"
        PRD 4: "| POST | `/v1/telemetry` | Ingest one device sensor event |
        DeviceHub |"

        Design: Corner/rbac/devicehub_cannot_read_admin_resources
        """
        resp = api.list_seniors(HUB)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestPipelineOrdering:
    def test_forbidden_role_beats_schema_validation(self, api):
        """PRD 2.9: "Authentication comes first: header presence and role
        recognition, then membership of the caller's role in the endpoint's
        authorized list. Next the request body is checked for well-formedness —
        every required field present, every type correct — with violations
        rejected as `ERR_INVALID_REQUEST`; when the offending content is an
        enum field carrying an undeclared member, the rejection is specifically
        `ERR_INVALID_ENUM`."

        Design: Corner/validations/forbidden_role_beats_schema_validation
        """
        senior = create_senior(full_name="Pv Senior")
        caregiver = fixtures.add_caregiver(senior["id"], full_name="Cg Pv")
        # Malformed body (undeclared tier member, missing required fields), but
        # Caregiver is not in the endpoint's role list, so the role check fires
        # first.
        resp = api.create_subscription_plan(
            {"tier": "GOLD"}, make_caregiver_headers(caregiver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestContactTreeValidationOrder:
    """Referential check outranks the fiscal contact-limit check (PRD 3.5)."""

    def _setup(self):
        """Plan with max_contacts 1; main senior with caregiver + one ACTIVE
        entry (tree full); other senior with own caregiver."""
        ctx = setup_senior_with_subscription(
            plan_overrides={"tier": "ESSENTIAL", "max_contacts": 1}
        )
        other_senior = create_senior(full_name="Other Senior")
        cg_main = fixtures.add_caregiver(
            ctx["senior"]["id"], full_name="Cg M", phone="555-3"
        )
        cg_other = fixtures.add_caregiver(
            other_senior["id"], full_name="Cg O", phone="555-4"
        )
        fixtures.add_contact_entry(
            ctx["senior"]["id"], cg_main["id"], priority_rank=1
        )
        ctx.update({"other_senior": other_senior, "cg_other": cg_other})
        return ctx

    def test_contact_create_mismatched_caregiver_returns_referential_error(self, api):
        """PRD 3.5: "The checks run in a fixed order: `priority_rank` must be
        unique among the senior's `ACTIVE` entries (else `ERR_RANK_CONFLICT`);
        the referenced caregiver must serve the same senior (else
        `ERR_CAREGIVER_SENIOR_MISMATCH`); and the senior's `ACTIVE` entries
        must remain below the plan's `max_contacts` (else
        `ERR_CONTACT_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/contact_create_mismatched_caregiver_and_full_tree_returns_referential_error
        """
        ctx = self._setup()
        resp = api.create_contact_tree_entry(
            factories.create_contact_tree_entry_payload(
                ctx["senior"]["id"],
                ctx["cg_other"]["id"],
                priority_rank=2,
                min_severity="LOW",
                response_timeout_seconds=3600,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_SENIOR_MISMATCH)

    def test_contact_create_referential_error_beats_contact_limit(self, api):
        """PRD 3.5: "The checks run in a fixed order: `priority_rank` must be
        unique among the senior's `ACTIVE` entries (else `ERR_RANK_CONFLICT`);
        the referenced caregiver must serve the same senior (else
        `ERR_CAREGIVER_SENIOR_MISMATCH`); and the senior's `ACTIVE` entries
        must remain below the plan's `max_contacts` (else
        `ERR_CONTACT_LIMIT_EXCEEDED`)."
        (Here the tree is already at max_contacts 1, yet the caregiver-senior
        mismatch must surface and no entry may be created.)

        Design: Difficulty/priority_pair_validation_conflict/contact_create_mismatched_caregiver_and_full_tree_returns_referential_error
        """
        ctx = self._setup()
        error_data = validate_error(
            api.create_contact_tree_entry(
                factories.create_contact_tree_entry_payload(
                    ctx["senior"]["id"],
                    ctx["cg_other"]["id"],
                    priority_rank=2,
                    min_severity="LOW",
                    response_timeout_seconds=3600,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_CAREGIVER_SENIOR_MISMATCH,
        )
        assert error_data["error_id"] != "ERR_CONTACT_LIMIT_EXCEEDED"
        entries, _meta = validate_paginated(
            api.list_contact_tree_entries(
                ADMIN, params={"senior_id": ctx["senior"]["id"]}
            )
        )
        assert len(entries) == 1, "the rejected entry must not be created"


class TestContactTreeDelete:
    def test_contact_tree_delete_removes_and_preserves_ranks(self, api):
        """PRD 3.5: "A `PlatformAdmin` may later update an entry's
        `priority_rank`, `min_severity`, or `response_timeout_seconds` — the
        entry is addressed by its `entry_id`, and rank uniqueness is
        re-enforced on update — or remove the entry, which sets its status to
        `REMOVED`; removal never renumbers the survivors."
        PRD 3.1: "Escalation capacity is capped by `max_contacts`, the maximum
        number of `ACTIVE` contact-tree entries a senior on this plan may
        have."

        Design: Corner/endpoints/contact_tree_delete_removes_and_preserves_ranks
        """
        ctx = setup_senior_with_subscription(
            plan_overrides={"tier": "PLUS", "max_contacts": 2}
        )
        senior_id = ctx["senior"]["id"]
        cg1 = fixtures.add_caregiver(senior_id, full_name="Cg C1", phone="555-41")
        cg2 = fixtures.add_caregiver(senior_id, full_name="Cg C2", phone="555-42")
        cg3 = fixtures.add_caregiver(senior_id, full_name="Cg C3", phone="555-43")
        entry1 = fixtures.add_contact_entry(senior_id, cg1["id"], priority_rank=1)
        entry2 = fixtures.add_contact_entry(senior_id, cg2["id"], priority_rank=2)

        get_success_data(api.delete_contact_tree_entry(entry1["id"], ADMIN))

        removed = get_success_data(api.get_contact_tree_entry(entry1["id"], ADMIN))
        assert removed["status"] == "REMOVED", (
            "removal is a soft state; the entry must remain queryable"
        )
        survivor = get_success_data(api.get_contact_tree_entry(entry2["id"], ADMIN))
        assert survivor["status"] == "ACTIVE"
        assert survivor["priority_rank"] == 2, "removal never renumbers survivors"

        # The REMOVED entry no longer counts against the max_contacts budget.
        entry3 = get_success_data(
            api.create_contact_tree_entry(
                factories.create_contact_tree_entry_payload(
                    senior_id, cg3["id"], priority_rank=3
                ),
                ADMIN,
            )
        )
        assert entry3["status"] == "ACTIVE"
        assert entry3["priority_rank"] == 3
