"""Access control: authentication of the role header, per-endpoint
authorization, and the three segregation-of-duties comparisons.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_graded_lot,
    create_lab_submitted_lot,
    create_leaf_lot,
    create_leaf_lot_payload,
    create_supplier,
    create_supplier_payload,
    get_batch,
    get_lot,
    setup_single_lot_scenario,
    validate_error,
    validate_success,
    set_clock_payload,
)

PL = TEST_USERS["procurement_lead_headers"]
GR = TEST_USERS["sensory_grader_headers"]
PP = TEST_USERS["production_planner_headers"]
BM = TEST_USERS["blend_master_headers"]
QA = TEST_USERS["qa_manager_headers"]


def test_create_supplier_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request with a missing or invalid header, or whose
    role is not one of these nine, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    `UnknownRole` is outside the nine declared roles — an authentication
    failure, not an authorization failure.

    Design: Corner/rbac/create_supplier_unknown_role_returns_unauthenticated
    """
    res = api.create_supplier(
        create_supplier_payload(name="X", origin_region="Y"),
        build_user_headers("mystery-1", "UnknownRole"))
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_sensory_grader_cannot_create_supplier(api):
    """PRD §2.1: "A request whose role is valid but not among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "The system recognizes exactly nine roles: `ProcurementLead`
    (supplier registry and leaf-lot intake), `SensoryGrader` (sensory
    grading), `QALabAnalyst` (pesticide residue testing), `QAManager`
    (release and recall of lots and batches), `BlendMaster` (flavorings,
    recipes, batches, blending and flavoring application),
    `ProductionPlanner` (packaging lines and production runs),
    `AccountManager` (private-label contracts), `CertificationOfficer`
    (organic and fair-trade certificate grants), and `PlatformAdmin`
    (operations-only control of the logical clock)."

    Supplier registration belongs to ProcurementLead; SensoryGrader is a
    valid role but lacks the right.

    Design: Corner/rbac/sensory_grader_cannot_create_supplier
    """
    res = api.create_supplier(
        create_supplier_payload(name="X", origin_region="Y"), GR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_blend_master_cannot_set_clock(api):
    """PRD §2.1: "and `PlatformAdmin` (operations-only control of the
    logical clock)."
    PRD §2.1: "A request whose role is valid but not among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    The logical-clock endpoint is PlatformAdmin-exclusive; BlendMaster is
    denied.

    Design: Corner/rbac/blend_master_cannot_set_clock
    """
    res = api.set_clock(set_clock_payload("2026-08-02T00:00:00Z"), BM)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_planner_cannot_release_lot(api):
    """PRD §2.1: "A request whose role is valid but not among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "`QAManager` (release and recall of lots and batches)"

    Lot release is QAManager-exclusive; ProductionPlanner is denied even
    though the lot sits in a releasable state (role check precedes state
    checks per PRD §2.10).

    Design: Corner/rbac/planner_cannot_release_lot
    """
    supplier = create_supplier(name="RBAC Co")
    lot = create_lab_submitted_lot(supplier["id"], leaf_type="BLACK")
    res = api.release_lot(lot["id"], PP)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert get_lot(lot["id"])["status"] == "LAB_SUBMITTED"


def test_sod_grader_is_registrar_rejected(api):
    """PRD §2.9: "The grader of a lot must differ from the operator who
    registered it, recorded as the lot's `registered_by_user_id`."
    PRD §3.2: "an operator may not grade a lot they registered
    themselves, and the attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES`"

    The same operator id under a different role is still the same
    person: pl-1 registered the lot, so pl-1 may not grade it.

    Design: Corner/rbac/sod_grader_is_registrar_rejected
    """
    supplier = create_supplier(name="SoD Co")
    lot = create_leaf_lot(supplier["id"], leaf_type="BLACK")
    assert lot["registered_by_user_id"] == "pl-1"

    res = api.create_grade_assessment(
        lot["id"],
        {"aroma_score": 90, "briskness_score": 88, "appearance_score": 92},
        build_user_headers("pl-1", "SensoryGrader"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_lot(lot["id"])["status"] == "REGISTERED"


def test_sod_lot_release_by_tester_rejected(api):
    """PRD §2.9: "The QA manager releasing a lot must differ from the
    analyst recorded as `submitted_by_user_id` on that lot's latest
    residue test."
    PRD §2.9: "A violation of any of the three is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    The lot is LAB_SUBMITTED with the passing test submitted by an-1;
    release by operator an-1 under the QAManager role is refused.

    Design: Corner/rbac/sod_lot_release_by_tester_rejected
    """
    supplier = create_supplier(name="SoD2 Co")
    lot = create_lab_submitted_lot(supplier["id"], leaf_type="BLACK",
                                   measured_residue_ppm=0.20)

    res = api.release_lot(lot["id"], build_user_headers("an-1", "QAManager"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_lot(lot["id"])["status"] == "LAB_SUBMITTED"

    released = validate_success(api.release_lot(lot["id"], QA), 200)
    assert released["status"] == "RELEASED", (
        "release by a different QA manager succeeds")


def test_sod_batch_release_by_blender_rejected(api):
    """PRD §2.9: "The QA manager releasing a batch must differ from the
    blend master recorded as the batch's `blended_by_user_id`."
    PRD §3.5: "The releaser must not be the operator who blended the
    batch, else `ERR_SEGREGATION_OF_DUTIES`."

    The batch was blended by bm-1; release by operator bm-1 under the
    QAManager role is refused, then a different QA manager releases.

    Design: Corner/rbac/sod_batch_release_by_blender_rejected
    """
    ctx = setup_single_lot_scenario(advance_to="QC_REVIEW",
                                    pack_format="LOOSE_PACK")
    batch = ctx["batch"]
    assert batch["blended_by_user_id"] == "bm-1"

    res = api.release_batch(batch["id"],
                            build_user_headers("bm-1", "QAManager"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_batch(batch["id"])["status"] == "QC_REVIEW"

    released = validate_success(api.release_batch(batch["id"], QA), 200)
    assert released["status"] == "RELEASED"
