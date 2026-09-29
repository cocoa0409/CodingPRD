"""Role scoping, identity backing and the segregation of duties across the five roles."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_money, assert_sheet_counters
from test_helpers.factories import (
    build_acceptance_test_payload,
    build_ahj_reviewer_payload,
    build_engineer_payload,
    build_hazard_area_payload,
    build_qc_review_payload,
    build_record_clearance_payload,
    build_shop_drawing_payload,
    build_trade_clearance_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    CONTRACTOR_HEADERS,
    CLEARANCE_BANDS,
    build_evaluated_stage,
    build_sealed_stage,
    build_submitted_stage,
    read_calculation,
    read_project,
    read_shop_drawing,
    read_submittal,
)
from test_helpers.test_users import (
    make_ahj_reviewer_headers,
    make_design_engineer_headers,
    make_qc_reviewer_headers,
)

NEW_HIRE = dict(full_name="Sam Okafor", license_state="TX", license_number="PE-90311")
# A plain office bay: the smallest body that satisfies the hazard-area schema.
SMALL_BAY = dict(
    hazard_class="ORDINARY_1", commodity_class="CLASS_III", storage_height_ft=8.0,
    ceiling_height_ft=12.0, area_sqft=1800.0, sprinkler_system_type="WET",
    ceiling_slope_pct=None, room_area_sqft=None, enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)
HEADERLESS_AREA = dict(SMALL_BAY, label="Headerless bay")
GHOST_AREA = dict(SMALL_BAY, label="Ghost engineer bay")
ORPHAN_AREA = dict(SMALL_BAY, label="Contractor drawn bay")


class TestEachRoleOwnsItsOwnStepOfTheWalk:
    def test_01_only_the_admin_enrols_staff_and_only_a_second_engineer_passes_qc(self, client):
        """A `QcReviewer` is a second engineer performing the independent quality check. This
        role is backed by the same `Engineer` table, so when `X-User-Role` is `QcReviewer`,
        `X-User-ID` is likewise the `id` of an `Engineer` row.

        Design: Corner/rbac/each_role_can_perform_the_operation_only_it_owns
        """
        ctx = build_evaluated_stage(client)
        hire = validate_success(
            client.create_engineer(build_engineer_payload(**NEW_HIRE), ADMIN_HEADERS),
            expected_status=201,
        )
        assert hire["license_status"] == "ACTIVE"

        passed = validate_success(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(
                    disposition="PASS", review_note="Independent QC check complete"
                ),
                make_qc_reviewer_headers(ctx["second_id"]),
            )
        )
        assert passed["state"] == "QC_PASSED"
        assert passed["qc_reviewed_by_engineer_id"] == ctx["second_id"]

        # Only the engineer of record may then seal what the QC reviewer passed.
        sealed = validate_success(
            client.seal_calculation(
                ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
            )
        )
        assert sealed["state"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ctx["lead_id"]

    def test_02_the_contractor_draws_the_sheet_and_the_engineer_records_the_trades(
        self, client
    ):
        """A `Contractor` is the installing sprinkler contractor: they record hydrant flow
        tests, prepare shop drawing sheets and trade coordination items ...

        Design: Corner/rbac/each_role_can_perform_the_operation_only_it_owns
        """
        ctx = build_evaluated_stage(client)
        validate_success(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(),
                make_qc_reviewer_headers(ctx["second_id"]),
            )
        )
        validate_success(
            client.seal_calculation(
                ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
            )
        )
        sheet = validate_success(
            client.create_shop_drawing(
                build_shop_drawing_payload(
                    project_id=ctx["project_id"],
                    hydraulic_calculation_id=ctx["calculation_id"],
                    sheet_number="FP-101",
                ),
                CONTRACTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert_sheet_counters(sheet, "DRAFT", 0)

        items = []
        for trade in ("STRUCTURAL", "MECHANICAL", "LIGHTING"):
            low, high = CLEARANCE_BANDS[trade]
            items.append(
                validate_success(
                    client.create_trade_clearance(
                        sheet["id"],
                        build_trade_clearance_payload(trade, low, high),
                        CONTRACTOR_HEADERS,
                    ),
                    expected_status=201,
                )
            )
        # Opening is the contractor's; recording the outcome is the engineer's.
        for item in items:
            validate_success(
                client.record_trade_clearance(
                    item["id"],
                    build_record_clearance_payload(
                        outcome="CLEARED", note="Coordinated in the field"
                    ),
                    make_design_engineer_headers(ctx["lead_id"]),
                )
            )
        assert_sheet_counters(read_shop_drawing(client, sheet["id"]), "COORDINATED", 3)

    def test_03_the_engineer_packages_and_only_the_assigned_authority_opens_review(
        self, client
    ):
        """An `AhjReviewer` is the authority's plan examiner and witness. When `X-User-Role` is
        `AhjReviewer`, `X-User-ID` is the `id` of the acting `AhjReviewer` row ...

        Design: Corner/rbac/each_role_can_perform_the_operation_only_it_owns
        """
        ctx = build_submitted_stage(client)
        submittal = ctx["submittal"]
        assert submittal["state"] == "SUBMITTED"
        assert submittal["cycle_number"] == 1
        assert_money(submittal["review_fee_usd"], 0.00)

        opened = validate_success(
            client.begin_review(
                submittal["id"], make_ahj_reviewer_headers(ctx["reviewer_id"])
            )
        )
        assert opened["state"] == "UNDER_REVIEW"
        assert opened["reviewed_by_ahj_reviewer_id"] == ctx["reviewer_id"]
        # The walk needed all five roles; no single role could have reached here.
        assert read_calculation(client, ctx["calculation_id"])["state"] == "SEALED"
        assert read_project(client, ctx["project_id"])["status"] == "PERMIT_REVIEW"


class TestIdentityHeadersAreSeparatedByPriority:
    def test_04_a_missing_header_is_401_and_an_unknown_engineer_is_403(self, client):
        """Every request carries two headers: `X-User-ID`, identifying the acting person, and
        `X-User-Role`, naming the capacity in which that person acts. If either header is
        missing or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) ...

        Design: Corner/rbac/missing_and_unrecognised_identity_headers_are_separated_from_each_other
        """
        ctx = build_sealed_stage(client)
        headerless = client.create_hazard_area(
            build_hazard_area_payload(project_id=ctx["project_id"], **HEADERLESS_AREA), {}
        )
        validate_error(headerless, "ERR_UNAUTHENTICATED", expected_status=401)

        ghost = client.create_hazard_area(
            build_hazard_area_payload(project_id=ctx["project_id"], **GHOST_AREA),
            make_design_engineer_headers(NON_EXISTENT_UUID),
        )
        validate_error(ghost, "ERR_IDENTITY_NOT_RECOGNIZED", expected_status=403)

        rows, meta = validate_paginated(
            client.list_hazard_areas(ADMIN_HEADERS, params={"project_id": ctx["project_id"]})
        )
        assert meta["total_count"] == 1, "neither refusal left a hazard area behind"
        assert [row["label"] for row in rows] == [ctx["hazard_area"]["label"]]

    def test_05_the_identity_must_live_in_the_table_its_role_is_backed_by(self, client):
        """For the three identity-backed roles — `DesignEngineer`, `QcReviewer` and
        `AhjReviewer` — the supplied `X-User-ID` must resolve to an existing row of the backing
        table: an `Engineer` for the first two, an `AhjReviewer` for the third. A well-formed
        but unknown identifier is rejected with `ERR_IDENTITY_NOT_RECOGNIZED` (HTTP 403).

        Design: Corner/rbac/missing_and_unrecognised_identity_headers_are_separated_from_each_other
        """
        ctx = build_sealed_stage(client)
        # A perfectly valid Engineer id, but the AhjReviewer role is backed by another table.
        crossed = client.list_submittals(make_ahj_reviewer_headers(ctx["lead_id"]))
        validate_error(crossed, "ERR_IDENTITY_NOT_RECOGNIZED", expected_status=403)

        # The opaque roles skip the check entirely and carry no entity-backed identity.
        sheet = validate_success(
            client.create_shop_drawing(
                build_shop_drawing_payload(
                    project_id=ctx["project_id"],
                    hydraulic_calculation_id=ctx["calculation_id"],
                ),
                CONTRACTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert sheet["sheet_number"] == "FP-101"
        assert_sheet_counters(sheet, "DRAFT", 0)


class TestPeerRolesCannotReachAcross:
    def test_06_the_engineers_design_surface_is_closed_to_the_other_roles(self, client):
        """If the header is present but names a role that is not authorised for the endpoint
        being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/peer_roles_cannot_reach_across_into_each_others_endpoints
        """
        ctx = build_submitted_stage(client)
        # POST /hazard-areas is the engineer's alone.
        validate_error(
            client.create_hazard_area(
                build_hazard_area_payload(project_id=ctx["project_id"], **ORPHAN_AREA),
                CONTRACTOR_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            expected_status=403,
        )
        # POST /shop-drawings is the contractor's alone, even for the engineer of record.
        validate_error(
            client.create_shop_drawing(
                build_shop_drawing_payload(
                    project_id=ctx["project_id"],
                    hydraulic_calculation_id=ctx["calculation_id"],
                    sheet_number="FP-102",
                ),
                make_design_engineer_headers(ctx["lead_id"]),
            ),
            "ERR_ROLE_NOT_PERMITTED",
            expected_status=403,
        )
        # Role scoping is priority 2, ahead of the drawing and posture gates.
        validate_error(
            client.create_acceptance_test(
                build_acceptance_test_payload(
                    project_id=ctx["project_id"], test_type="SYSTEM_FLOW_TEST"
                ),
                make_ahj_reviewer_headers(ctx["reviewer_id"]),
            ),
            "ERR_ROLE_NOT_PERMITTED",
            expected_status=403,
        )

    def test_07_a_second_valid_examiner_is_still_not_this_projects_examiner(self, client):
        """Every authority write is refused with `ERR_NOT_ASSIGNED_REVIEWER` (HTTP 403) unless
        `X-User-ID` equals the project's `ahj_reviewer_id` ...

        Design: Corner/rbac/peer_roles_cannot_reach_across_into_each_others_endpoints
        """
        ctx = build_submitted_stage(client)
        stranger = validate_success(
            client.create_ahj_reviewer(
                build_ahj_reviewer_payload(
                    full_name="Tomas Rey", jurisdiction_code="TX-AUS"
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        refused = client.begin_review(
            ctx["submittal_id"], make_ahj_reviewer_headers(stranger["id"])
        )
        # Priorities 1 to 3 all pass; assignment scoping at priority 7 is what refuses him.
        validate_error(refused, "ERR_NOT_ASSIGNED_REVIEWER", expected_status=403)

        untouched = read_submittal(client, ctx["submittal_id"])
        assert untouched["state"] == "SUBMITTED"
        assert untouched["reviewed_by_ahj_reviewer_id"] is None

        opened = validate_success(
            client.begin_review(
                ctx["submittal_id"], make_ahj_reviewer_headers(ctx["reviewer_id"])
            )
        )
        assert opened["state"] == "UNDER_REVIEW"
        assert opened["reviewed_by_ahj_reviewer_id"] == ctx["reviewer_id"]


SELF_REVIEW = dict(disposition="PASS", review_note="Self review attempt")
PEER_REVIEW = dict(disposition="PASS", review_note="Independent QC check complete")


class TestSegregationOfDuties:
    def test_08_the_author_reviewing_his_own_work_is_refused_and_nothing_is_recorded(
        self, client
    ):
        """The reviewer's identifier must differ from the calculation's
        `authored_by_engineer_id`; an author reviewing their own work is refused with
        `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/rbac/the_author_of_a_calculation_may_never_be_its_qc_reviewer
        """
        ctx = build_evaluated_stage(client)
        assert ctx["calculation"]["authored_by_engineer_id"] == ctx["lead_id"]
        assert ctx["calculation"]["state"] == "CONVERGED"

        refused = client.qc_review_calculation(
            ctx["calculation_id"],
            build_qc_review_payload(**SELF_REVIEW),
            make_qc_reviewer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

        untouched = read_calculation(client, ctx["calculation_id"])
        assert untouched["state"] == "CONVERGED"
        assert untouched["qc_reviewed_by_engineer_id"] is None
        assert untouched["authored_by_engineer_id"] == ctx["lead_id"]

    def test_09_a_second_engineer_in_the_same_role_passes_the_identical_request(self, client):
        """The segregation-of-duties rule applies to this role alone: the acting QC reviewer may
        never be the author of the calculation under review, and an attempt to review one's own
        work is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/the_author_of_a_calculation_may_never_be_its_qc_reviewer
        """
        ctx = build_evaluated_stage(client)
        validate_error(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(**SELF_REVIEW),
                make_qc_reviewer_headers(ctx["lead_id"]),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )
        passed = validate_success(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(**PEER_REVIEW),
                make_qc_reviewer_headers(ctx["second_id"]),
            )
        )
        assert passed["state"] == "QC_PASSED"
        assert passed["qc_reviewed_by_engineer_id"] == ctx["second_id"]
        assert passed["authored_by_engineer_id"] == ctx["lead_id"]
