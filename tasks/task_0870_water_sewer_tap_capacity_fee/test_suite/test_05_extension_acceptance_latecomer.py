"""Project acceptance cascade, latecomer assessment variants, and pool conservation."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_pool_conservation,
    setup_accepted_project, setup_extension_ready_to_accept, create_latecomer,
    create_application, create_project_payload,
    make_reviewer_headers, make_developer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAcceptExtensionDepth3Cascade:
    """accept -> project ACCEPTED -> agreement COMPLETION_PENDING -> availability flipped."""

    def test_accept_advances_project_and_agreement(self, api):
        """PRD §3.8: "Acceptance then cascades: the project's `EXECUTED` developer agreement
        advances to `COMPLETION_PENDING`, and that in turn flips the application's availability
        determination to show both mains available and no extension required, as described in
        §2.7."

        Design: Difficulty/transitive_cascade/accept_extension_depth3_cascade
        """
        ctx = setup_extension_ready_to_accept(distance_to_main_ft=300)
        project = validate_success(api.accept_project(
            ctx["project_id"], {"actual_construction_cost_cents": 2800000},
            make_reviewer_headers("rev-1")), 200)
        assert project["status"] == "ACCEPTED"
        agreement = validate_success(api.get_agreement(
            ctx["agreement_id"], make_developer_headers("dev-1")), 200)
        assert agreement["status"] == "COMPLETION_PENDING"

    def test_accept_flips_availability_determination(self, api):
        """PRD §2.7: "that agreement transition in turn flips the referenced application's
        availability determination so that both `water_main_available` and `sewer_main_available`
        become true and `extension_required` becomes false — the extension has, in effect, made
        service available."

        Design: Difficulty/transitive_cascade/accept_extension_depth3_cascade
        """
        ctx = setup_extension_ready_to_accept(distance_to_main_ft=300)
        api.accept_project(ctx["project_id"], {"actual_construction_cost_cents": 2800000},
                           make_reviewer_headers("rev-1"))
        det = validate_success(api.get_availability_determination(
            ctx["determination_id"], make_reviewer_headers("rev-1")), 200)
        assert det["water_main_available"] is True
        assert det["extension_required"] is False


class TestLatecomerFrontFootageVsArea:
    """The same principal yields different shares under the two proration methods."""

    def test_front_footage_share(self, api):
        """PRD §3.8: "Under the `FRONT_FOOTAGE` method, the share is the principal multiplied by
        the benefiting `parcel_front_ft` divided by the project's `total_assessable_front_ft`."

        Design: Difficulty/dual_variant_calc/latecomer_front_footage_vs_area
        """
        ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                     reimbursement_cap_cents=6000000,
                                     total_assessable_front_ft=500, total_assessable_area_sqft=100000)
        ben = create_application(applicant_user_id="appl-2", parcel_id="APN-BEN1")
        res = create_latecomer(ctx["project_id"], ben["id"], "FRONT_FOOTAGE", 50, 8000,
                               ctx["project_version"])
        lc = validate_success(res, 201)
        assert lc["amount_cents"] == 500000

    def test_area_share(self, api):
        """PRD §3.8: "Under the `AREA` method, the share is the principal multiplied by the
        benefiting `parcel_area_sqft` divided by the project's `total_assessable_area_sqft`."

        Design: Difficulty/dual_variant_calc/latecomer_front_footage_vs_area
        """
        ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                     reimbursement_cap_cents=6000000,
                                     total_assessable_front_ft=500, total_assessable_area_sqft=100000)
        ben = create_application(applicant_user_id="appl-2", parcel_id="APN-BEN2")
        res = create_latecomer(ctx["project_id"], ben["id"], "AREA", 50, 8000,
                               ctx["project_version"])
        lc = validate_success(res, 201)
        assert lc["amount_cents"] == 400000


class TestReimbursementPoolConservation:
    """Collecting a latecomer moves money from outstanding to collected, conserving principal."""

    def test_collect_moves_pool_balances(self, api):
        """PRD §3.8: "Collecting it transitions `ASSESSED → COLLECTED`, and updates the project
        pool: the collected `amount_cents` is added to `reimbursed_collected_cents` and
        subtracted from `outstanding_recoverable_cents`, preserving the pool conservation
        invariant."

        Design: Difficulty/compensating_invariant/reimbursement_pool_conservation
        """
        ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                     reimbursement_cap_cents=6000000,
                                     total_assessable_front_ft=500, total_assessable_area_sqft=100000)
        ben = create_application(applicant_user_id="appl-2", parcel_id="APN-Q")
        lc = validate_success(create_latecomer(ctx["project_id"], ben["id"], "FRONT_FOOTAGE",
                                               50, 8000, ctx["project_version"]), 201)
        validate_success(api.collect_latecomer_reimbursement(lc["id"], ADMIN), 200)
        project = validate_success(api.get_project(
            ctx["project_id"], make_developer_headers("dev-1")), 200)
        assert project["reimbursable_principal_cents"] == 5000000
        assert project["reimbursed_collected_cents"] == 500000
        assert project["outstanding_recoverable_cents"] == 4500000

    def test_pool_conservation_invariant(self, api):
        """PRD §3.8: "Throughout the pool's life, the conservation invariant holds that the
        reimbursable principal always equals the collected amount plus the outstanding
        recoverable amount."

        Design: Difficulty/compensating_invariant/reimbursement_pool_conservation
        """
        ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                     reimbursement_cap_cents=6000000,
                                     total_assessable_front_ft=500, total_assessable_area_sqft=100000)
        ben = create_application(applicant_user_id="appl-2", parcel_id="APN-Q2")
        lc = validate_success(create_latecomer(ctx["project_id"], ben["id"], "FRONT_FOOTAGE",
                                               50, 8000, ctx["project_version"]), 201)
        api.collect_latecomer_reimbursement(lc["id"], ADMIN)
        project = validate_success(api.get_project(
            ctx["project_id"], make_developer_headers("dev-1")), 200)
        assert_pool_conservation(project)


def test_latecomer_against_unaccepted_project_rejected(api):
    """PRD §3.8: "The referenced project must be `ACCEPTED` with its reimbursable principal set,
    or the assessment is rejected with `ERR_PROJECT_NOT_ACCEPTED` (HTTP 422)."

    Design: Corner/validations/latecomer_against_unaccepted_project_rejected
    """
    app = create_application(parcel_id="APN-PA")
    project = validate_success(api.create_project(
        create_project_payload(app["id"], developer_user_id="dev-1", length_ft=300,
                               estimated_cost_cents=3000000, total_assessable_front_ft=300,
                               total_assessable_area_sqft=60000, reimbursement_cap_cents=4000000),
        make_developer_headers("dev-1")), 201)
    ben = create_application(applicant_user_id="appl-2", parcel_id="APN-PAB")
    res = create_latecomer(project["id"], ben["id"], "FRONT_FOOTAGE", 30, 6000,
                           project["version"])
    validate_error(res, ApiErrorId.ERR_PROJECT_NOT_ACCEPTED.value, expected_status=422)


def test_latecomer_share_exceeds_outstanding_rejected(api):
    """PRD §3.8: "The computed share may not exceed the project's current
    `outstanding_recoverable_cents`; if it would, the assessment is rejected with
    `ERR_REIMBURSEMENT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/latecomer_share_exceeds_outstanding_rejected
    """
    ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                 reimbursement_cap_cents=6000000,
                                 total_assessable_front_ft=500, total_assessable_area_sqft=100000)
    ben = create_application(applicant_user_id="appl-2", parcel_id="APN-RXB")
    # parcel_front_ft 600 > total 500 -> share 6,000,000 > 5,000,000 outstanding.
    res = create_latecomer(ctx["project_id"], ben["id"], "FRONT_FOOTAGE", 600, 8000,
                           ctx["project_version"])
    validate_error(res, ApiErrorId.ERR_REIMBURSEMENT_EXCEEDED.value, expected_status=422)


def test_latecomer_stale_project_version_conflict(api):
    """PRD §2.6: "A request that creates a latecomer reimbursement must include
    `expected_main_extension_project_version` carrying the client's last-observed `version` of
    the target `MainExtensionProject`. If that value does not equal the project's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/latecomer_occ_stale_version_conflict
    """
    ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                 reimbursement_cap_cents=6000000,
                                 total_assessable_front_ft=500, total_assessable_area_sqft=100000)
    stale_version = ctx["project_version"]
    ben1 = create_application(applicant_user_id="appl-2", parcel_id="APN-OLB1")
    ben2 = create_application(applicant_user_id="appl-3", parcel_id="APN-OLB2")
    # First assessment succeeds and advances the project version.
    validate_success(create_latecomer(ctx["project_id"], ben1["id"], "FRONT_FOOTAGE",
                                       50, 8000, stale_version), 201)
    # Second create still carries the pre-assessment (stale) version.
    res = create_latecomer(ctx["project_id"], ben2["id"], "AREA", 50, 8000, stale_version)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_latecomer_waive_leaves_pool_unchanged(api):
    """PRD §3.8: "Waiving it (optionally with a `reason`) transitions `ASSESSED → WAIVED` and
    does not touch the pool."

    Design: Corner/consistency_model/latecomer_waive_leaves_pool_unchanged
    """
    ctx = setup_accepted_project(actual_construction_cost_cents=5000000,
                                 reimbursement_cap_cents=6000000,
                                 total_assessable_front_ft=500, total_assessable_area_sqft=100000)
    ben = create_application(applicant_user_id="appl-2", parcel_id="APN-WVB")
    lc = validate_success(create_latecomer(ctx["project_id"], ben["id"], "FRONT_FOOTAGE",
                                           50, 8000, ctx["project_version"]), 201)
    waived = validate_success(api.waive_latecomer_reimbursement(
        lc["id"], ADMIN, {"reason": "duplicate"}), 200)
    assert waived["status"] == "WAIVED"
    project = validate_success(api.get_project(
        ctx["project_id"], make_developer_headers("dev-1")), 200)
    assert project["reimbursed_collected_cents"] == 0
    assert project["outstanding_recoverable_cents"] == 5000000
