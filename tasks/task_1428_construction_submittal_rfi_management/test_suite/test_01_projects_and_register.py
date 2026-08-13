"""Project setup, documented defaults, and submittal register generation (PRD §2.4, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_project,
    activate_spec_section,
    add_spec_section,
    assert_project,
    assert_submittal,
    create_active_project,
    create_project,
    create_project_payload,
    create_spec_section_payload,
    lli_of_submittal,
    submittals_of_section,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PA = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestProjectCreationDefaults:
    def test_project_creation_applies_documented_defaults(self, api):
        """PRD §2.5: "A new project begins in `SETUP`."
        PRD §3.1: "The contractual `rfi_response_days` sets the RFI answer window in
        business days (default ten, at least one). The `ack_required_days` sets how many
        business days a subcontractor has to acknowledge a distribution (default five,
        at least one). The `mobilization_buffer_days` sets the required calendar-day gap
        between two installation windows of the same subcontractor (default two, and zero
        is permitted). The `long_lead_threshold_days` marks the boundary at which a
        procurement becomes long-lead (default thirty business days, at least one). The
        `expedite_window_days` sets how close a required on-site date may loom — in
        calendar days — before the system begins expediting on its own (default ten, zero
        permitted). The `holiday_dates` array lists non-working days excluded from
        business-day math and defaults to empty."
        PRD §2.7: "At project creation the reserved and spent balances start at zero and
        the available balance equals the seed."
        PRD §2.11: "Each successful scan increments the project's `ops_scan_index`, a
        monotonic counter starting at zero, by exactly one and bumps the Project's
        `version`."

        Design: Corner/entities/project_creation_applies_documented_defaults
        """
        resp = api.create_project(create_project_payload("Defaults"), PA)
        project = validate_success(resp, 201)
        assert_project(project)
        assert project["posture"] == "SETUP"
        assert project["rfi_response_days"] == 10
        assert project["ack_required_days"] == 5
        assert project["mobilization_buffer_days"] == 2
        assert project["long_lead_threshold_days"] == 30
        assert project["expedite_window_days"] == 10
        assert project["holiday_dates"] == []
        assert project["contingency_reserved_cents"] == 0
        assert project["contingency_spent_cents"] == 0
        assert project["contingency_available_cents"] == 0, (
            "initial_contingency_cents defaults to zero, so the available balance is zero"
        )
        assert project["ops_scan_index"] == 0

    def test_action_endpoint_success_returns_updated_entity_envelope(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by
        exactly one on every mutation of the resource, including system-driven cascade
        mutations."
        PRD §2.5: "A `ProjectManager` activates it (`SETUP` → `ACTIVE`)"

        Design: Corner/endpoints/action_endpoint_success_returns_updated_entity_envelope
        """
        project = create_project("Envelope")
        resp = api.activate_project(project["id"], PM)
        body = resp.json()
        assert body["response_type"] == "object", (
            "a single-resource action returns the object envelope"
        )
        updated = validate_success(resp, 200)
        assert_project(updated)
        assert updated["posture"] == "ACTIVE"
        assert updated["version"] == project["version"] + 1, (
            "activation bumps the Project's version by exactly one"
        )


class TestSpecSectionShapeValidation:
    def test_spec_section_missing_required_section_number_returns_invalid_request(self, api):
        """PRD §3.1: "Each section carries a `section_number` that must be unique within
        the project" — every other creation input carries a documented default, so
        `section_number` is the one required field.
        PRD §2.10: "Fifth, request shape: required fields must be present, types must be
        correct, enum members must be valid, and array members must be valid and free of
        duplicates (notably within `required_submittal_kinds`); violations fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/spec_section_missing_required_section_number_returns_invalid_request
        """
        project = create_project("P")
        resp = api.create_spec_section(project["id"], {"title": "no number"}, PE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_spec_section_invalid_enum_kind_rejected(self, api):
        """PRD §3.1: "a `required_submittal_kinds` array drawn from `PRODUCT_DATA`,
        `SHOP_DRAWINGS`, `SAMPLES`, `MOCKUP`, `CERTIFICATES`, and `O_AND_M_MANUALS`"
        PRD §2.10: "enum members must be valid, and array members must be valid and free
        of duplicates (notably within `required_submittal_kinds`); violations fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/spec_section_invalid_enum_kind_rejected
        """
        project = create_project("P")
        resp = api.create_spec_section(
            project["id"],
            create_spec_section_payload("099999", required_submittal_kinds=["BOGUS_KIND"]),
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_spec_section_duplicate_kinds_rejected(self, api):
        """PRD §3.1: "duplicate kinds in the array are rejected with
        `ERR_INVALID_REQUEST`"

        Design: Corner/entities/spec_section_duplicate_kinds_rejected
        """
        project = create_project("P")
        resp = api.create_spec_section(
            project["id"],
            create_spec_section_payload(
                "033000", required_submittal_kinds=["SAMPLES", "SAMPLES"]
            ),
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_spec_section_responsible_subcontractor_fk_must_exist(self, api):
        """PRD §2.10: "after which identifiers supplied in the request body
        (`spec_section_id`, `submittal_id`, `reviewer_id`, `subcontractor_id`) must also
        exist within the same project, failing with the corresponding 404."

        Design: Corner/entities/spec_section_responsible_subcontractor_fk_must_exist
        """
        project = create_project("P")
        resp = api.create_spec_section(
            project["id"],
            create_spec_section_payload(
                "033000", responsible_subcontractor_id=NON_EXISTENT_UUID
            ),
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_NOT_FOUND, 404)


class TestRegisterGeneration:
    def test_register_generation_assigns_item_numbers_and_initial_states(self, api):
        """PRD §3.1: "For each kind in `required_submittal_kinds`, taken in array order,
        the system creates one Submittal whose `submittal_kind` records that kind and
        whose `item_number` is the section's `section_number` followed by a hyphen and
        the kind's one-based index zero-padded to two digits (so a section `03 30 00`
        requiring two kinds yields `03 30 00-01` and `03 30 00-02`)."
        PRD §3.1: "Each generated submittal starts with `review_status` `REGISTERED`,
        `expediting_status` `NOT_REQUIRED`, `deferral_status` `NONE`, `revision_count`
        zero, and a `required_on_site_date` initialized from the section's
        `default_need_date`."
        PRD §3.1: "A generated submittal whose section `lead_time_days` is at least the
        project's `long_lead_threshold_days` is flagged `is_long_lead`"

        Design: Corner/entities/register_generation_assigns_item_numbers_and_initial_states
        """
        project = create_active_project("P")
        section = add_spec_section(
            project["id"],
            "033000",
            lead_time_days=5,
            default_need_date="2026-10-30",
            required_submittal_kinds=["PRODUCT_DATA", "SHOP_DRAWINGS", "SAMPLES"],
        )
        activate_spec_section(section["id"])

        submittals = submittals_of_section(project["id"], "033000")
        assert len(submittals) == 3, "one register item per required kind"
        # item_number's NN suffix is the kind's one-based index in the array; pair
        # each kind with its index rather than relying on list ordering.
        by_kind = {s["submittal_kind"]: s for s in submittals}
        assert by_kind["PRODUCT_DATA"]["item_number"] == "033000-01"
        assert by_kind["SHOP_DRAWINGS"]["item_number"] == "033000-02"
        assert by_kind["SAMPLES"]["item_number"] == "033000-03"
        for submittal in submittals:
            assert_submittal(submittal)
            assert submittal["review_status"] == "REGISTERED"
            assert submittal["expediting_status"] == "NOT_REQUIRED"
            assert submittal["is_long_lead"] is False, (
                "lead_time_days 5 is below the default long-lead threshold of 30"
            )

    def test_long_lead_item_created_only_at_or_above_threshold(self, api):
        """PRD §3.1: "A generated submittal whose section `lead_time_days` is at least
        the project's `long_lead_threshold_days` is flagged `is_long_lead`; for each such
        submittal the system additionally creates exactly one linked LongLeadItem in
        `IDENTIFIED` status, mirrors the submittal's `required_on_site_date` onto it,
        computes its `escalation_level` and `priority_score` against the current clock
        date, and moves the submittal's `expediting_status` to `MONITORING`."
        PRD §3.4: "Fetching the long-lead item of a submittal returns an array of zero
        or one element."
        Lead 30 meets the default threshold 30 (at least); lead 29 falls below it.

        Design: Corner/entities/long_lead_item_created_only_at_or_above_threshold
        """
        project = create_active_project("P")
        sec_a = add_spec_section(
            project["id"], "051200", lead_time_days=30, default_need_date="2026-10-30"
        )
        sec_b = add_spec_section(
            project["id"], "033000", lead_time_days=29, default_need_date="2026-10-30"
        )
        activate_spec_section(sec_a["id"])
        activate_spec_section(sec_b["id"])

        sub_a = submittals_of_section(project["id"], "051200")[0]
        sub_b = submittals_of_section(project["id"], "033000")[0]
        assert sub_a["is_long_lead"] is True
        assert sub_a["expediting_status"] == "MONITORING"
        assert sub_b["is_long_lead"] is False

        lli = lli_of_submittal(sub_a["id"])
        assert lli is not None, "a long-lead submittal carries exactly one linked item"
        assert lli["status"] == "IDENTIFIED"
        assert lli["required_on_site_date"] == sub_a["required_on_site_date"]

        resp = api.get_submittal_long_lead_item(sub_b["id"], PE)
        items = validate_success(resp, 200)
        assert items == [], "a below-threshold submittal has no long-lead item"


class TestSubmittalRetrieval:
    def test_submittal_get_unknown_id_returns_not_found(self, api):
        """PRD §2.10: "Fourth, existence: every resource identifier in the URL path is
        validated in left-to-right order, and the request is rejected with the 404 error
        of the first identifier that does not resolve" — the catalogue includes
        `ERR_SUBMITTAL_NOT_FOUND`.

        Design: Corner/entities/submittal_get_unknown_id_returns_not_found
        """
        resp = api.get_submittal(NON_EXISTENT_UUID, PE)
        validate_error(resp, ApiErrorId.ERR_SUBMITTAL_NOT_FOUND, 404)
