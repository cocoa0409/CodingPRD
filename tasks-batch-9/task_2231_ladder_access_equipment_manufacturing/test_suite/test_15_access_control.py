"""Authentication, role authorization, listing-body ownership and the three
separation-of-duty checks."""

from test_helpers import (
    NO_AUTH_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_approved_revision,
    create_draft_revision,
    create_joint_sample_payload,
    create_listing_body,
    create_product,
    disposition_payload,
    file_listing_record,
    freeze_design_payload,
    get_corrective_action_data,
    get_incident_data,
    get_listing_record_data,
    get_lot_data,
    get_product_data,
    get_revision_data,
    make_certification_body_headers,
    make_design_approver_headers,
    open_lot,
    quarantine_lot,
    review_design_revision_payload,
    run_campaign_to_passed,
    setup_frozen_product,
    setup_open_capa,
    start_lot_production,
    submit_revision,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import DESIGN_ENGINEER_USER_ID, DESIGN_APPROVER_USER_ID

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
CONSUMER = TEST_USERS["consumer_headers"]

FIBERGLASS = {"material": "FIBERGLASS_PULTRUSION"}


def test_a_missing_or_unrecognised_role_header_is_unauthenticated_not_forbidden():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the nine role names below, the request is rejected with `ERR_UNAUTHENTICATED`. If
    the headers are well-formed but the supplied role is not listed among the target
    endpoint's authorized roles, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    product = create_product()

    headerless = api_client.get_product(product["id"], NO_AUTH_HEADERS)
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert (
        headerless.json()["data"]["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    )

    unknown_role = api_client.get_product(product["id"], UNKNOWN_ROLE_HEADERS)
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert (
        unknown_role.json()["data"]["error_id"]
        != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    )

    assert get_product_data(product["id"])["version"] == 1


def test_only_a_design_approver_may_freeze_a_design():
    """PRD §2.1: "A `DesignApprover` reviews revisions, freezes designs, and
    verifies corrective actions."
    PRD §2.5: "2. Role authorization against the endpoint's role list
    (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/production_supervisor_cannot_freeze_design
    """
    product = create_product(**FIBERGLASS)
    revision = create_approved_revision(product["id"])
    run_campaign_to_passed(
        get_product_data(product["id"]), revision["id"], "DESIGN_QUALIFICATION"
    )

    refused = api_client.freeze_design(
        product["id"], freeze_design_payload(revision["id"]), SUPERVISOR
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    still_draft = get_product_data(product["id"])
    assert still_draft["design_status"] == "DRAFT"
    assert still_draft["design_frozen_at"] is None

    allowed = validate_success(
        api_client.freeze_design(
            product["id"], freeze_design_payload(revision["id"]), APPROVER
        )
    )
    assert allowed["design_status"] == "DESIGN_FROZEN", (
        "the refusal was attributable to the role alone"
    )


def test_a_consumer_may_not_read_the_production_lot_collection():
    """PRD §2.1: "A `Consumer` is a retail purchaser who registers a unit, reports
    a field incident, and acknowledges a recall remedy."
    PRD §2.5: "2. Role authorization against the endpoint's role list
    (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/consumer_cannot_read_production_lots
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)

    single = api_client.get_production_lot(lot["id"], CONSUMER)
    validate_error(single, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert "lot_code" not in single.json()["data"]

    collection = api_client.list_production_lots(
        CONSUMER, {"product_id": ctx["product"]["id"]}
    )
    validate_error(collection, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert "lot_code" not in collection.json()["data"]

    assert get_lot_data(lot["id"])["status"] == "IN_PROCESS"


def test_a_certification_body_may_not_grant_another_bodys_listing():
    """PRD §2.1: "ownership checks on any resource that references a
    `ListingBody` compare the resource's `listing_body_id` to `X-User-ID`, so a
    certification body acting on a listing record whose `listing_body_id` is not its
    own `X-User-ID` is rejected with `ERR_LISTING_BODY_MISMATCH`."

    Design: Corner/rbac/certification_body_cannot_act_on_another_bodys_listing_record
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    owner = create_listing_body(accredited_standards=["ANSI_ASC_A14_2"])
    stranger = create_listing_body(accredited_standards=["ANSI_ASC_A14_2"])
    record = file_listing_record(
        ctx["product"]["id"], owner["id"], standard_code="ANSI_ASC_A14_2"
    )
    run_campaign_to_passed(
        ctx["product"], ctx["revision"]["id"], "CERTIFICATION_LISTING", ctx["bench"]["id"]
    )

    refused = api_client.grant_listing(
        record["id"], make_certification_body_headers(stranger["id"])
    )
    validate_error(refused, ApiErrorId.ERR_LISTING_BODY_MISMATCH.value, 403)

    reread = get_listing_record_data(record["id"])
    assert reread["status"] == "APPLIED"
    assert reread["listed_at"] is None

    granted = validate_success(
        api_client.grant_listing(
            record["id"], make_certification_body_headers(owner["id"])
        )
    )
    assert granted["status"] == "LISTED", (
        "the refusal was attributable to ownership alone"
    )


def test_the_submitting_engineer_may_not_review_the_same_revision():
    """PRD §2.1: "Two approval acts compare the caller's `X-User-ID` against a
    previously recorded operator identifier and reject a self-approval with
    `ERR_SEGREGATION_OF_DUTIES`: reviewing a design revision the caller submitted,
    and verifying a corrective action the caller authored."
    PRD §3.2: "Submitting the revision for review moves it `DRAFT` →
    `UNDER_REVIEW` and stamps `submitted_by_user_id` with the submitting engineer's
    `X-User-ID`"

    Design: Corner/rbac/submitter_cannot_review_own_design_revision
    """
    product = create_product()
    revision = create_draft_revision(
        product["id"], structural_margin_pct=6.50, rail_section_modulus_in3=0.250
    )
    revision = submit_revision(revision["id"], ENGINEER)
    assert revision["submitted_by_user_id"] == DESIGN_ENGINEER_USER_ID

    self_review = api_client.review_design_revision(
        revision["id"],
        review_design_revision_payload("APPROVE"),
        make_design_approver_headers(DESIGN_ENGINEER_USER_ID),
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    approved = validate_success(
        api_client.review_design_revision(
            revision["id"], review_design_revision_payload("APPROVE"), APPROVER
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["submitted_by_user_id"] == DESIGN_ENGINEER_USER_ID
    assert approved["reviewed_by_user_id"] == DESIGN_APPROVER_USER_ID
    assert approved["review_round"] == 1
    assert get_revision_data(revision["id"])["status"] == "APPROVED"


def test_the_authoring_engineer_may_not_verify_the_same_corrective_action():
    """PRD §3.8: "Verification belongs to a `DesignApprover`, must not be
    performed by whoever authored the action — `X-User-ID` equal to
    `authored_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`"
    PRD §3.8: "Creating the action sets its `status` to `OPEN`, stamps
    `authored_by_user_id` with the author's `X-User-ID`, leaves `verified_at` and
    `verified_by_user_id` null, moves the incident `ROOT_CAUSE_IDENTIFIED` →
    `CAPA_OPENED`"

    Design: Corner/rbac/author_cannot_verify_own_corrective_action
    """
    product = create_product()
    incident, action = setup_open_capa(
        product["id"],
        "RIVET_SHEAR_MARGIN",
        incident_type="RAIL_FRACTURE",
        injury_severity="HOSPITALIZATION",
    )
    assert action["authored_by_user_id"] == DESIGN_ENGINEER_USER_ID
    assert incident["status"] == "CAPA_OPENED"

    refused = api_client.verify_corrective_action(
        action["id"], make_design_approver_headers(DESIGN_ENGINEER_USER_ID)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    reread = get_corrective_action_data(action["id"])
    assert reread["status"] == "OPEN"
    assert reread["authored_by_user_id"] == DESIGN_ENGINEER_USER_ID
    assert reread["verified_at"] is None
    assert get_incident_data(incident["id"])["status"] == "CAPA_OPENED"
    # HOSPITALIZATION weight 12 times RAIL_FRACTURE weight 3.0, with no
    # verified action to earn the one-quarter credit.
    assert float(get_product_data(product["id"])["risk_score_mitigated"]) == 36.00


def test_a_production_supervisor_may_quarantine_but_never_scrap_a_lot():
    """PRD §2.1: "A third separation is enforced by role rather than by identity —
    scrapping a quarantined lot is reserved to a `SafetyDirector`, and a
    `ProductionSupervisor` who asks for that disposition is rejected with
    `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR` even though the same supervisor is
    authorized to quarantine the lot in the first place."

    Design: Corner/rbac/production_supervisor_cannot_scrap_a_quarantined_lot
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    # Quarantine reaches a lot that is still IN_PROCESS, moving the whole
    # work-in-process bucket across, and the supervisor is allowed to ask for it.
    quarantined = quarantine_lot(lot["id"], "JOINT_INTEGRITY")
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["units_quarantined"] == 400
    assert quarantined["units_wip"] == 0

    refused = api_client.disposition_production_lot(
        lot["id"], disposition_payload("SCRAP"), SUPERVISOR
    )
    validate_error(
        refused, ApiErrorId.ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR.value, 403
    )

    reread = get_lot_data(lot["id"])
    assert reread["status"] == "QUARANTINED"
    assert reread["disposition"] is None
    assert reread["units_quarantined"] == 400
    assert reread["units_scrapped"] == 0

    scrapped = validate_success(
        api_client.disposition_production_lot(
            lot["id"], disposition_payload("SCRAP"), DIRECTOR
        )
    )
    assert scrapped["status"] == "SCRAPPED"


def test_both_lab_and_production_roles_may_record_a_joint_sample():
    """PRD §2.1: "A `TestLabTechnician` owns the lab: benches, reservations,
    campaigns, load tests, and joint pull samples."
    PRD §3.6: "Each sample snapshots the model's `required_pull_force_lbf` at
    insert time into its own `required_pull_force_lbf`, so later changes elsewhere
    cannot rewrite history"

    Design: Corner/rbac/joint_sample_creation_is_shared_by_two_roles
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    assert float(ctx["product"]["required_pull_force_lbf"]) == 450.00
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)

    by_lab = validate_success(
        api_client.create_joint_sample(
            lot["id"], create_joint_sample_payload(1, 470.00), TECHNICIAN
        ),
        201,
    )
    by_production = validate_success(
        api_client.create_joint_sample(
            lot["id"], create_joint_sample_payload(2, 462.00), SUPERVISOR
        ),
        201,
    )

    assert int(by_lab["margin_pct"]) == 4
    assert int(by_production["margin_pct"]) == 3

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 2
    # The mean of the whole percents 4 and 3.
    assert float(reread["conformance_index"]) == 3.50

    _, meta = validate_paginated(
        api_client.list_joint_samples(lot["id"], SUPERVISOR)
    )
    assert meta["total_count"] == 2


def test_the_owning_body_grants_the_listing_and_stamps_all_three_instants():
    """PRD §3.5: "On success three instants are stamped: `listed_at` at the
    logical clock, `audit_due_at` at the logical clock advanced by the owning body's
    `audit_interval_days`, and `listing_expires_at` at the logical clock advanced by
    the listing term of 1825 days — five 365-day years."
    PRD §2.4: "Date arithmetic that adds days (a listing term, an audit interval, a
    recall window) adds exact 24-hour days to the clock reading"

    Design: Corner/rbac/certification_body_can_list_its_own_record
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    body = create_listing_body(
        accredited_standards=["ANSI_ASC_A14_2"], audit_interval_days=180
    )
    record = file_listing_record(
        ctx["product"]["id"], body["id"], standard_code="ANSI_ASC_A14_2"
    )
    run_campaign_to_passed(
        ctx["product"], ctx["revision"]["id"], "CERTIFICATION_LISTING", ctx["bench"]["id"]
    )

    listed = validate_success(
        api_client.grant_listing(
            record["id"], make_certification_body_headers(body["id"])
        )
    )

    assert listed["status"] == "LISTED"
    assert_instant_equals(listed["listed_at"], "2026-08-01T00:00:00Z", "listed_at")
    # 180 exact 24-hour days after the clock reading.
    assert_instant_equals(listed["audit_due_at"], "2027-01-28T00:00:00Z", "audit_due_at")
    # 1825 exact 24-hour days after the clock reading.
    assert_instant_equals(
        listed["listing_expires_at"], "2031-07-31T00:00:00Z", "listing_expires_at"
    )
    assert listed["suspended_at"] is None
    assert listed["suspension_reason"] is None
    assert get_product_data(ctx["product"]["id"])["market_status"] == "NOT_RELEASED"
