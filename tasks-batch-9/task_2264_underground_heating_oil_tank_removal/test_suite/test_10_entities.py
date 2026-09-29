"""Row-level surface: declared fields, defaults, system fields, references, listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    fixtures as fx,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_envelope_has_only_meta_and_data
from test_helpers.factories import (
    OMIT,
    disclosure_payload,
    minimal_laboratory_payload,
    minimal_tank_project_payload,
    property_payload,
    work_order_payload,
)
from test_helpers.test_users import COMPLIANCE_OFFICER, FIELD_TECHNICIAN, PROJECT_COORDINATOR


class TestPropertyRegistration:
    def test_registration_echoes_the_inputs_and_derives_the_state_deductible(self, api):
        """PRD §3.1: "Registration also derives two read-only figures: `trust_fund_deductible_cents`, taken from the state deductible schedule for the property's `state_code`, and `open_project_count`, which starts at 0."
        PRD §3.1: "The state deductible schedule is fixed by statute and is the same schedule that later gets snapshotted onto every reimbursement claim: five hundred dollars in New Jersey, one thousand dollars in New York, and two hundred fifty dollars in Connecticut — 50,000, 100,000 and 25,000 cents respectively."
        PRD §3.1: "Two coverage figures may be supplied and otherwise take their defaults: `first_party_coverage_limit_cents`, which defaults to 2,000,000 cents — twenty thousand dollars of first-party property capacity — and `third_party_sublimit_cents`, which defaults to 5,000,000 cents, or fifty thousand dollars of liability sublimit."

        Design: Corner/entities/property_creation_returns_declared_fields_and_state_keyed_deductible
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api.create_property(
            property_payload(
                street_address="1 Corner Way",
                state_code="NJ",
                homeowner_name="Ann Hale",
                homeowner_email="ann@example.com",
                insurance_carrier_code="CARR-C-1",
            ),
            PROJECT_COORDINATOR,
        )
        created = validate_success(response, 201)

        assert created["trust_fund_deductible_cents"] == 50000, (
            "the New Jersey deductible is 50,000 cents, got "
            f"{created['trust_fund_deductible_cents']}"
        )
        assert created["open_project_count"] == 0, (
            f"a fresh site has no live projects, got {created['open_project_count']}"
        )
        assert created["version"] == 1, (
            f"a newly written row is at version 1, got {created['version']}"
        )
        assert parse_instant(created["created_at"]) == parse_instant(
            "2026-08-03T08:00:00Z"
        ), (
            "the creation instant is stamped from the logical clock, got "
            f"{created['created_at']}"
        )
        assert created["state_code"] == "NJ", (
            f"the declared input must be echoed verbatim, got {created['state_code']}"
        )
        assert created["first_party_coverage_limit_cents"] == 2000000, (
            "the omitted first-party capacity takes its 2,000,000-cent default, got "
            f"{created['first_party_coverage_limit_cents']}"
        )
        assert created["third_party_sublimit_cents"] == 5000000, (
            "the omitted liability sublimit takes its 5,000,000-cent default, got "
            f"{created['third_party_sublimit_cents']}"
        )
        assert_envelope_has_only_meta_and_data(response.json())

    def test_system_fields_are_server_minted_and_the_open_count_tracks_children(
        self, api
    ):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written. `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation."
        PRD §3.1: "`open_project_count` tracks how many of the property's projects are still live, meaning every `TankProject` on the property whose `status` is neither `CLOSED_SETTLED` nor `VOID`. It increments by 1 when a project is opened, and decrements by 1 when a project reaches either of those two terminal states."

        Design: Corner/entities/property_system_fields_are_server_minted_and_version_advances_on_child_write
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        site = fx.create_property(
            street_address="5 Corner Way",
            state_code="CT",
            county_code="FFD",
            homeowner_name="Eve Lam",
            homeowner_email="eve@example.com",
            insurance_carrier_code="CARR-C-5",
        )
        assert site["version"] == 1, (
            f"the registration is the first write, got {site['version']}"
        )
        assert site["open_project_count"] == 0, (
            f"no project has been opened yet, got {site['open_project_count']}"
        )
        assert parse_instant(site["created_at"]) == parse_instant(
            "2026-08-03T08:00:00Z"
        ), (
            f"the creation instant reads the logical clock, got {site['created_at']}"
        )

        fx.create_project(site["id"])
        reread = fx.read_property(site["id"])
        assert reread["created_at"] == site["created_at"], (
            "the creation instant never moves, got "
            f"{reread['created_at']} after {site['created_at']}"
        )
        assert reread["open_project_count"] == 1, (
            f"opening one project lifts the live count to 1, got {reread['open_project_count']}"
        )
        assert reread["trust_fund_deductible_cents"] == 25000, (
            "the Connecticut deductible is 25,000 cents, got "
            f"{reread['trust_fund_deductible_cents']}"
        )


class TestTankProjectRow:
    def test_retrieval_returns_the_row_that_creation_minted(self, api):
        """PRD §3.1: "Opening a **TankProject** requires only the `property_id`, though the coordinator may pin the excavation contract at the same time."
        PRD §2.6: "Because the graph is flat, references arrive in two places: as the single identifier in a path, and as identifier fields inside a request body."

        Design: Corner/entities/tank_project_retrieval_returns_the_stored_row
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        site = fx.create_property(
            street_address="2 Corner Way",
            homeowner_name="Bea Ives",
            homeowner_email="bea@example.com",
            insurance_carrier_code="CARR-C-2",
        )
        created = validate_success(
            api.create_tank_project(
                minimal_tank_project_payload(site["id"]), PROJECT_COORDINATOR
            ),
            201,
        )

        stored = fx.read_project(created["id"])
        assert stored["id"] == created["id"], (
            f"the read must address the same row, got {stored['id']}"
        )
        assert stored["property_id"] == site["id"], (
            f"the parent reference must be stored, got {stored['property_id']}"
        )
        assert stored["status"] == "INTAKE", (
            f"a fresh project begins in INTAKE, got {stored['status']}"
        )
        assert stored["version"] == 1, (
            f"nothing has mutated the project yet, got {stored['version']}"
        )

    def test_scope_defaults_and_the_two_opening_blockers_are_computed_on_creation(
        self, api
    ):
        """PRD §3.1: "A fresh project begins in `INTAKE` with `sampling_round` at 0, `contamination_class` at `UNCLASSIFIED`, `approved_scope_cubic_yards` equal to `baseline_scope_cubic_yards`, `remediation_cost_cents` at 0, and a blocker list that already names two obstacles — field work has not happened and contamination has not been cleared."
        PRD §3.1: "`baseline_scope_cubic_yards` is the contracted excavation volume before any change order and defaults to 8.0 cubic yards; `excavation_limit_cubic_yards` is the hard ceiling that change-order approvals are measured against and defaults to 40.0 cubic yards."
        PRD §3.9: "The resulting codes are deduplicated and sorted lexicographically ascending — never by creation time or identifier — so the list is stable and directly comparable between reads."

        Design: Corner/entities/tank_project_scope_defaults_and_computed_blockers_on_creation
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        site = fx.create_property(
            street_address="4 Corner Way",
            homeowner_name="Dee Kwon",
            homeowner_email="dee@example.com",
            insurance_carrier_code="CARR-C-4",
        )
        project = fx.create_project(
            site["id"],
            baseline_scope_cubic_yards=OMIT,
            excavation_limit_cubic_yards=OMIT,
        )

        assert project["baseline_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "the omitted baseline takes its default, got "
            f"{project['baseline_scope_cubic_yards']}"
        )
        assert project["excavation_limit_cubic_yards"] == pytest.approx(40.0, abs=0.01), (
            "the omitted ceiling takes its default, got "
            f"{project['excavation_limit_cubic_yards']}"
        )
        assert project["nfa_blockers"] == [
            "CONTAMINATION_NOT_CLEARED",
            "FIELD_WORK_INCOMPLETE",
        ], (
            "the two opening obstacles sort lexicographically ascending, got "
            f"{project['nfa_blockers']}"
        )
        assert project["status"] == "INTAKE", (
            f"a fresh project begins in INTAKE, got {project['status']}"
        )
        assert project["contamination_class"] == "UNCLASSIFIED", (
            f"nothing has been sampled yet, got {project['contamination_class']}"
        )
        assert project["remediation_cost_cents"] == 0, (
            f"no remediation has begun, got {project['remediation_cost_cents']}"
        )
        assert project["sampling_round"] == 0, (
            f"confirmation sampling has not opened, got {project['sampling_round']}"
        )
        assert project["remediation_started"] is False, (
            "the latch is untouched on a fresh project"
        )

    def test_listing_pages_by_creation_order_with_total_count_and_has_more(self, api):
        """PRD §2.3: "Collection reads are ordered by `created_at` ascending, so that a paged walk over a project's samples, change orders or claims reproduces the chronological order in which they were authored."
        PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before the window was applied, and `has_more` as a boolean indicating whether rows remain beyond the current window."

        Design: Corner/entities/tank_project_listing_paginates_with_total_count_and_has_more
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        site = fx.create_property(
            street_address="3 Corner Way",
            homeowner_name="Cal Jung",
            homeowner_email="cal@example.com",
            insurance_carrier_code="CARR-C-3",
        )
        first = fx.create_project(site["id"])
        second = fx.create_project(site["id"])
        third = fx.create_project(site["id"])

        page_one, meta_one = validate_paginated(
            api.list_tank_projects(
                PROJECT_COORDINATOR,
                params={"property_id": site["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page_one) == 2, (
            f"a limit of 2 returns two rows, got {len(page_one)}"
        )
        assert meta_one["limit"] == 2, (
            f"the resolved limit is echoed, got {meta_one['limit']}"
        )
        assert meta_one["offset"] == 0, (
            f"the resolved offset is echoed, got {meta_one['offset']}"
        )
        assert meta_one["total_count"] == 3, (
            f"three projects match the filter, got {meta_one['total_count']}"
        )
        assert meta_one["has_more"] is True, (
            "one row remains beyond the first window"
        )
        assert page_one[0]["id"] == first["id"], (
            "creation order puts the earliest project first, got "
            f"{page_one[0]['id']}"
        )

        page_two, meta_two = validate_paginated(
            api.list_tank_projects(
                PROJECT_COORDINATOR,
                params={"property_id": site["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page_two) == 1, (
            f"only the third project remains, got {len(page_two)}"
        )
        assert meta_two["has_more"] is False, (
            "nothing remains beyond the second window"
        )
        assert page_two[0]["id"] == third["id"], (
            f"the last row of the walk is the last created, got {page_two[0]['id']}"
        )
        assert {row["id"] for row in page_one + page_two} == {
            first["id"],
            second["id"],
            third["id"],
        }, "the two pages together must cover every project exactly once"

    def test_unknown_project_identifier_in_the_path_is_not_found(self, api):
        """PRD §2.6: "A path identifier that does not resolve yields `ERR_PROPERTY_NOT_FOUND`, `ERR_TANK_PROJECT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LABORATORY_NOT_FOUND`, `ERR_SOIL_SAMPLE_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_NFA_LETTER_NOT_FOUND` or `ERR_INSURANCE_NOTIFICATION_NOT_FOUND` as appropriate."
        PRD §2.11: "4. **Path identifier resolution, left to right** — the entity-specific 404 from §2.6. Applies to every endpoint that carries an identifier in its path."

        Design: Corner/entities/tank_project_with_unknown_path_id_is_not_found
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api.get_tank_project(NON_EXISTENT_UUID, PROJECT_COORDINATOR)
        validate_error(response, ApiErrorId.ERR_TANK_PROJECT_NOT_FOUND.value, 404)

    def test_creation_against_an_unknown_property_is_not_found(self, api):
        """PRD §2.6: "Body-carried references are resolved with the same entity-specific codes. The references the server resolves are `property_id`, `tank_project_id`, `crew_id`, `laboratory_id`, `work_order_id`, `retest_of_sample_id` and `supersedes_change_order_id`, and this resolution step runs on all nine creation operations: creating a tank project, a disclosure, a permit, a work order, a soil sample, a change order, a trust-fund claim, a closure letter and an insurance notification."
        PRD §2.11: "5. **Body reference resolution** — the entity-specific 404 from §2.6. Applies to the nine creation operations enumerated in §2.6."

        Design: Corner/entities/tank_project_requires_an_existing_parent_property
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api.create_tank_project(
            minimal_tank_project_payload(NON_EXISTENT_UUID), PROJECT_COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)

        _, meta = validate_paginated(api.list_tank_projects(PROJECT_COORDINATOR))
        assert meta["total_count"] == 0, (
            f"a refused create must leave no row behind, got {meta['total_count']}"
        )


class TestDisclosureParentReference:
    def test_disclosure_creation_against_an_unknown_project_is_not_found(self, api):
        """PRD §2.6: "Both are resolved before any business rule runs, and both produce the 404 that names the entity that failed to resolve."
        PRD §3.2: "A `ProjectCoordinator` sends a **HomeownerDisclosure** by naming the `tank_project_id` and the `disclosure_kind`, which is either `SWEEP_FINDINGS` for the results of the locating survey or `CONTAMINATION_FINDINGS` for the results of soil analysis."

        Design: Corner/entities/disclosure_creation_requires_an_existing_tank_project_not_found
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api.create_disclosure(
            disclosure_payload(NON_EXISTENT_UUID, disclosure_kind="SWEEP_FINDINGS"),
            PROJECT_COORDINATOR,
        )
        validate_error(response, ApiErrorId.ERR_TANK_PROJECT_NOT_FOUND.value, 404)

        _, meta = validate_paginated(api.list_disclosures(PROJECT_COORDINATOR))
        assert meta["total_count"] == 0, (
            f"a refused create must leave no notice behind, got {meta['total_count']}"
        )


class TestLaboratoryDefaults:
    def test_omitting_every_optional_threshold_applies_the_declared_defaults(self, api):
        """PRD §3.6: "`accredited` defaults to true and records whether the lab holds state accreditation; an unaccredited lab may not take custody of samples at all."
        PRD §3.6: "`committed_turnaround_hours` defaults to 72 and serves double duty — it is both the contractual turnaround the lab promises and the length of time each sample occupies one of the lab's analysis slots."
        PRD §3.6: "`max_concurrent_analyses` defaults to 2 and is the aggregate number of overlapping analysis windows the lab can sustain; it must be at least 1, while the two hour figures must both be strictly greater than zero."

        Design: Corner/entities/laboratory_defaults_applied_when_all_optional_thresholds_omitted
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        lab = validate_success(
            api.create_laboratory(
                minimal_laboratory_payload(lab_name="Default Values Lab"),
                COMPLIANCE_OFFICER,
            ),
            201,
        )

        assert lab["accredited"] is True, (
            f"accreditation defaults to true, got {lab['accredited']}"
        )
        assert lab["committed_turnaround_hours"] == pytest.approx(72.0, abs=0.01), (
            "the turnaround commitment defaults to 72 hours, got "
            f"{lab['committed_turnaround_hours']}"
        )
        assert lab["holding_time_hours"] == pytest.approx(336.0, abs=0.01), (
            "the holding time defaults to 336 hours, got "
            f"{lab['holding_time_hours']}"
        )
        assert lab["max_concurrent_analyses"] == 2, (
            "the bench capacity defaults to 2, got "
            f"{lab['max_concurrent_analyses']}"
        )
        assert lab["version"] == 1, (
            f"the registration is the first write, got {lab['version']}"
        )


class TestRequestShapeConstraints:
    def test_crew_without_a_certification_tier_is_rejected(self, api):
        """PRD §2.11: "6. **Request-body shape** — `ERR_INVALID_REQUEST` (422): a required field absent, an enum value outside its declared members, a number outside its declared range, a work-order interval whose `scheduled_end_at` is not strictly later than its `scheduled_start_at`, or a sweep survey reporting at least one tank without supplying all five tank descriptors. Applies to every write endpoint."
        PRD §3.4: "A **Crew** is registered by a `ProjectCoordinator` with a `crew_name`, a `cert_level` recording the certification tier of the crew lead — `TANK_TECH_I`, `TANK_TECH_II` or `LSP_SUPERVISED` — and a `mobilization_buffer_minutes` figure that defaults to 90 and may not be negative."

        Design: Corner/entities/crew_creation_missing_required_cert_level_is_rejected
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api.create_crew(
            {"crew_name": "Crew Missing Required Field"}, PROJECT_COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    def test_sweep_survey_with_an_undeclared_method_member_is_rejected(self, api):
        """PRD §3.1: "The sweep survey advances the project `INTAKE → SURVEYED` and records the `survey_method` used — `GPR` for ground-penetrating radar, `MAGNETOMETER`, or `PROBE_ROD` — together with `tanks_detected_count` and, stamped from the logical clock, `survey_completed_at`."
        PRD §3.1: "Recording the survey also increments the project's `version` by 1."

        Design: Corner/entities/sweep_survey_rejects_an_undeclared_survey_method_enum_member
        """
        ctx = fx.project_at_intake(
            property_overrides={
                "street_address": "6 Corner Way",
                "homeowner_name": "Fay Nero",
                "homeowner_email": "fay@example.com",
                "insurance_carrier_code": "CARR-C-6",
            }
        )

        response = api.record_sweep_survey(
            ctx["project"]["id"],
            {
                "survey_method": "SONAR",
                "tanks_detected_count": 1,
                "tank_capacity_gallons": 550,
                "tank_depth_to_top_inches": 60,
                "tank_distance_to_foundation_inches": 90,
                "tank_under_structure": False,
                "tank_material": "STEEL",
            },
            FIELD_TECHNICIAN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        stored = fx.read_project(ctx["project"]["id"])
        assert stored["status"] == "INTAKE", (
            f"the refused survey leaves the project in INTAKE, got {stored['status']}"
        )
        assert stored["survey_method"] is None, (
            f"the undeclared method is not persisted, got {stored['survey_method']}"
        )
        assert stored["method_score"] is None, (
            f"no score is derived from a refused survey, got {stored['method_score']}"
        )

    def test_work_order_whose_interval_has_zero_length_is_rejected(self, api):
        """PRD §3.4: "The interval is half-open: the start instant is inclusive and the end instant is exclusive, and the end must be strictly later than the start or the request is refused with `ERR_INVALID_REQUEST`."
        PRD §2.11: "And because the required-reason check for a method override sits at rule 12 rather than with the other shape checks, a work order whose method contradicts the recommendation and whose override justification is missing is refused only after the crew-independent checks above it have all passed, and specifically *before* the crew calendar is consulted."

        Design: Corner/entities/work_order_rejects_scheduled_end_not_after_scheduled_start
        """
        ctx = fx.project_at_surveyed(
            property_overrides={
                "street_address": "7 Corner Way",
                "homeowner_name": "Gus Oh",
                "homeowner_email": "gus@example.com",
                "insurance_carrier_code": "CARR-C-7",
            }
        )
        crew = fx.create_crew(crew_name="Crew Zero Length")

        response = api.create_work_order(
            work_order_payload(
                ctx["project"]["id"],
                crew["id"],
                scheduled_start_at="2026-08-06T13:00:00Z",
                scheduled_end_at="2026-08-06T13:00:00Z",
            ),
            PROJECT_COORDINATOR,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        _, meta = validate_paginated(
            api.list_work_orders(PROJECT_COORDINATOR, params={"crew_id": crew["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the zero-length booking must not be stored, got {meta['total_count']}"
        )
