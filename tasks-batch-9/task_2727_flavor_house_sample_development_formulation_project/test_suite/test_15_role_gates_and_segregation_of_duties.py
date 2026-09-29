"""Authentication, per-endpoint authorization and the two duty-segregation pairs."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_envelope_meta, assert_pagination_meta
from test_helpers.constants import DEFAULT_LIMIT
from test_helpers.factories import (
    create_customer_brief_payload,
    create_disclosure_grant_payload,
    create_formula_revision_payload,
    create_raw_material_payload,
    formula_decision_payload,
    lot_qc_payload,
)
from test_helpers.fixtures import (
    add_material_line,
    build_approved_formula,
    compound_lot,
    cost_formula,
    create_accepted_brief,
    create_brief,
    create_formula,
    create_material,
    list_data,
    read_formula,
    read_lot,
    submit_formula,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    ALL_ROLE_NAMES,
    DIRECTOR_APPROVER,
    DIRECTOR_SECOND,
    DIRECTOR_SECOND_ID,
    DUAL_HAT_DIRECTOR,
    DUAL_HAT_FLAVORIST,
    DUAL_HAT_ID,
    FLAVORIST,
    LAB_COMPOUNDER,
    LAB_COMPOUNDER_ID,
    LAB_QC,
    LAB_QC_ID,
    PURCHASING_MANAGER,
    ROLE_HEADERS_BY_NAME,
    TECHNICAL_DIRECTOR,
)


def test_requests_without_a_valid_role_header_are_rejected_before_anything_else(api):
    """A missing role, a missing user and an unrecognised role are all 401.

    Section 2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting operator, and `X-User-Role`, declaring the capacity that operator
    is acting in.  If either header is absent, or if `X-User-Role` is not one of
    the six recognised role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)", and §2.11 makes authentication step 1 of
    the ladder, so nothing is written on the way through.

    Design: Corner/rbac/requests_without_a_valid_role_header_are_rejected_before_anything_else
    """
    no_role = api.raw_request("GET", "/customer-briefs",
                              headers={"X-User-ID": "u_am_1"})
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    no_user = api.raw_request("POST", "/customer-briefs",
                              payload=create_customer_brief_payload(
                                  brief_code="BRF-0001"),
                              headers={"X-User-Role": "AccountManager"})
    validate_error(no_user, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    bad_role = api.raw_request("GET", "/customer-briefs",
                               headers={"X-User-ID": "u_qa_1",
                                        "X-User-Role": "QualityAuditor"})
    validate_error(bad_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    for response in (no_role, no_user, bad_role):
        body = response.json()
        assert_envelope_meta(body, "error")
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != ""

    assert list_data(api, api.list_customer_briefs,
                     ACCOUNT_MANAGER)["meta"]["total_count"] == 0


def test_role_exclusive_operations_cannot_be_invoked_by_a_different_role(api):
    """Five endpoint-owning roles refuse five interlopers with ERR_UNAUTHORIZED.

    Section 2.1 splits ownership — a `Flavorist` "creates and iterates bench
    formulas", a `PurchasingManager` "maintains the raw-material catalogue and
    its list prices", a `TechnicalDirector` owns "the issuing of
    intellectual-property disclosure grants", an `AccountManager` owns "brief
    intake and re-submission", and a `LabTech` "records QC verdicts" — and says
    "If the headers are well-formed but the declared role is not among the roles
    permitted for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)".

    Design: Corner/rbac/role_exclusive_operations_cannot_be_invoked_by_a_different_role
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = compound_lot(api, formula["id"], batch_size_g=500)

    probes = [
        api.create_formula_revision(
            formula["id"],
            create_formula_revision_payload("hijacked revision",
                                            formula["version"]),
            ACCOUNT_MANAGER),
        api.create_raw_material(
            create_raw_material_payload(material_code="SNEAK-1",
                                        name="Unapproved material",
                                        cost_per_kg_cents=100,
                                        natural_status="NATURAL",
                                        potency_class="STANDARD",
                                        max_use_ppm=100000),
            ACCOUNT_MANAGER),
        api.create_disclosure_grant(
            create_disclosure_grant_payload(brief["id"], formula["id"],
                                            "TIER_1_STANDARD",
                                            "2026-12-01T00:00:00Z",
                                            redaction_level="FULL"),
            LAB_COMPOUNDER),
        api.create_customer_brief(
            create_customer_brief_payload(brief_code="BRF-0002",
                                          customer_name="Rogue Foods"),
            PURCHASING_MANAGER),
        api.record_lot_qc(lot["id"], lot_qc_payload("PASSED"),
                          TECHNICAL_DIRECTOR),
    ]

    assert len(probes) == 5
    for response in probes:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_formula(api, formula["id"])["status"] == "APPROVED"
    assert list_data(api, api.list_formulas, FLAVORIST)["meta"]["total_count"] == 1
    assert list_data(api, api.list_raw_materials,
                     PURCHASING_MANAGER)["meta"]["total_count"] == 1
    assert list_data(api, api.list_disclosure_grants,
                     DIRECTOR_APPROVER)["meta"]["total_count"] == 0
    assert list_data(api, api.list_customer_briefs,
                     ACCOUNT_MANAGER)["meta"]["total_count"] == 1

    untouched = read_lot(api, lot["id"])
    assert untouched["qc_status"] == "PENDING"
    assert untouched["qc_by_user_id"] is None


def test_the_submitting_user_cannot_approve_their_own_formula(api):
    """One operator in two role hats fails the check; a second director passes it.

    Section 2.8: "A formula's approval or rework decision may not be taken by the
    identity recorded in `submitted_by_user_id` ...  Either violation is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).  The role declared in
    `X-User-Role` is irrelevant to this check — two different
    `TechnicalDirector` operators satisfy it, and one operator wearing two role
    hats does not."  A refusal writes nothing, so §2.4's rule that `version`
    "increments by 1 on every mutation of that resource" leaves the submitted
    version untouched.

    Design: Corner/rbac/the_submitting_user_cannot_approve_their_own_formula
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], material["id"], 100.0)
    cost_formula(api, formula["id"])
    submitted = submit_formula(api, formula["id"], DUAL_HAT_FLAVORIST)
    assert submitted["submitted_by_user_id"] == DUAL_HAT_ID

    self_decision = api.decide_formula(
        formula["id"],
        formula_decision_payload("APPROVED",
                                 decision_note="self approval attempt"),
        DUAL_HAT_DIRECTOR)
    validate_error(self_decision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    still_submitted = read_formula(api, formula["id"])
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["version"] == submitted["version"]
    assert still_submitted["submitted_by_user_id"] == DUAL_HAT_ID
    assert still_submitted["approved_by_user_id"] is None

    independent = get_success_data(
        api.decide_formula(formula["id"],
                           formula_decision_payload(
                               "APPROVED", decision_note="independent review"),
                           DIRECTOR_SECOND),
        200)
    assert independent["status"] == "APPROVED"
    assert independent["approved_by_user_id"] == DIRECTOR_SECOND_ID


def test_the_compounder_cannot_record_qc_on_their_own_lot(api):
    """QC by the compounder is refused; release by the compounder is not.

    Section 3.6 requires of the verdict "the recording `X-User-ID` to differ from
    `compounded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`", and "Either
    verdict records the recorder into `qc_by_user_id`".  The release step carries
    no such comparison — its three preconditions are the lot's own disposition,
    its `qc_status` and its formula's status — so the compounder may release.

    Design: Corner/rbac/the_compounder_cannot_record_qc_on_their_own_lot
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = compound_lot(api, formula["id"], batch_size_g=500)
    assert lot["compounded_by_user_id"] == LAB_COMPOUNDER_ID

    self_qc = api.record_lot_qc(lot["id"],
                                lot_qc_payload("PASSED", qc_note="self check"),
                                LAB_COMPOUNDER)
    validate_error(self_qc, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    pending = read_lot(api, lot["id"])
    assert pending["qc_status"] == "PENDING"
    assert pending["qc_by_user_id"] is None

    passed = get_success_data(
        api.record_lot_qc(lot["id"],
                          lot_qc_payload("PASSED",
                                         qc_note="second person check"),
                          LAB_QC),
        200)
    assert passed["qc_status"] == "PASSED"
    assert passed["qc_by_user_id"] == LAB_QC_ID

    released = get_success_data(
        api.release_sample_lot(lot["id"], LAB_COMPOUNDER), 200)
    assert released["disposition_status"] == "RELEASED"
    assert released["compounded_by_user_id"] == LAB_COMPOUNDER_ID


def test_shared_read_operations_succeed_for_every_declared_role(api):
    """All six roles read the same brief list with the same pagination block.

    Section 2.1: "Every read operation in the API — every listing and every
    single-resource retrieval — is open to all six roles", the six being
    "`AccountManager`, `TechnicalDirector`, `Flavorist`, `RegulatoryAffairs`,
    `LabTech` and `PurchasingManager`".  Section 2.3 fixes the window: `limit`
    "defaults to 10 when omitted" and `offset` "defaults to 0".

    Design: Corner/rbac/shared_read_operations_succeed_for_every_declared_role
    """
    create_material(api, material_code="GUM-BASE")
    create_brief(api, brief_code="BRF-0001")

    assert len(ALL_ROLE_NAMES) == 6
    for role_name in ALL_ROLE_NAMES:
        response = api.list_customer_briefs(ROLE_HEADERS_BY_NAME[role_name])
        rows, meta = validate_paginated(response)
        assert rows[0]["brief_code"] == "BRF-0001", role_name
        assert_pagination_meta(meta, limit=DEFAULT_LIMIT, offset=0,
                              total_count=1, has_more=False)

    materials = api.list_raw_materials(ACCOUNT_MANAGER)
    rows, _ = validate_paginated(materials)
    assert rows[0]["material_code"] == "GUM-BASE"
