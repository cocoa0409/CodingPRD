"""RBAC: exclusive writes, shared reads, the identity header and the three duty bars."""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_review_appraiser_headers,
    make_staff_appraiser_headers,
    make_subrecipient_coordinator_headers,
)


ADMIN = TEST_USERS["program_administrator_headers"]
VALIDATOR = TEST_USERS["bca_validator_headers"]
APPROVER = TEST_USERS["project_approver_headers"]
STAFF = TEST_USERS["staff_appraiser_headers"]
REVIEWER = TEST_USERS["review_appraiser_headers"]
REVIEWER_2 = TEST_USERS["review_appraiser_2_headers"]
SPECIALIST = TEST_USERS["relocation_specialist_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]


# ─── One operation, one role, and four refusals around it ─────────────────────

def test_only_the_named_role_may_write_and_every_other_role_is_refused(api):
    """Four wrong roles are turned away before any state or duty check is consulted.

    "If `X-User-Role` names a role that is not permitted to invoke the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "The acting role may not invoke this operation - `ERR_UNAUTHORIZED`. Also every
    endpoint except the logical-clock capability."

    "Buyouts pay pre-event fair market value, not the depressed post-disaster value, so
    a `StaffAppraiser` records the pre-event basis on the parcel before any offer can be
    built."

    Design: Corner/rbac/only_the_named_role_may_act_and_every_other_role_is_unauthorized
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(
        api,
        project_overrides={"project_code": "RB-EXCL-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-RB-EXCL-1", "site_address": "4601 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel = state["parcel"]

    validate_error(
        api.record_pre_event_value(
            parcel["id"],
            factories.pre_event_value_payload(
                parcel["id"], pre_event_fmv_cents=20_000_000,
                pre_event_value_basis="MARKET_STUDY",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    untouched = validate_success(api.get_parcel(parcel["id"], ADMIN))
    assert untouched["pre_event_fmv_cents"] is None

    validate_error(
        api.approve_mitigation_project(
            project["id"],
            factories.approve_project_payload(project["id"], "APPROVE"),
            STAFF,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    validate_error(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(
                project["id"], apn="APN-RB-EXCL-2", site_address="4602 River Rd",
                acreage=0.41, occupancy_type="VACANT", structure_type="NONE",
            ),
            MONITOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    parcels, meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1
    assert len(parcels) == 1

    assert state["bca"]["status"] == "VALIDATED"
    validate_error(
        api.validate_benefit_cost_analysis(
            state["bca"]["id"],
            factories.validate_bca_payload(state["bca"]["id"], "VALIDATE"),
            SPECIALIST,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    permitted = validate_success(
        api.record_pre_event_value(
            parcel["id"],
            factories.pre_event_value_payload(
                parcel["id"], pre_event_fmv_cents=20_000_000,
                pre_event_value_basis="MARKET_STUDY",
            ),
            STAFF,
        )
    )
    assert permitted["pre_event_fmv_cents"] == 20_000_000
    assert permitted["pre_event_value_basis"] == "MARKET_STUDY"

    survivor = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert survivor["status"] == "APPROVED"


# ─── Read allowlists that are wide but not universal ──────────────────────────

def test_the_read_allowlists_widen_and_narrow_endpoint_by_endpoint(api):
    """The parcel list is open to everyone while the two child lists are not.

    "GET | /parcels | List parcels, optionally scoped to one project and filtered on
    either parallel state dimension. | All roles"

    "GET | /appraisals | List appraisals, filterable by parcel, by the appraisal they
    review, by type and by status. | ProgramAdministrator, SubrecipientCoordinator,
    StaffAppraiser, ReviewAppraiser, ComplianceMonitor"

    "GET | /relocation-cases | List relocation cases, filterable by parcel, displacee
    type and status. | ProgramAdministrator, SubrecipientCoordinator,
    RelocationSpecialist, ComplianceMonitor"

    Design: Corner/rbac/reads_are_shared_by_several_roles_but_not_by_all_of_them
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(
        api, project_code="RB-SHARED-1", grant_program="FMA"
    )
    parcel = fixtures.create_parcel(
        api, project, apn="APN-RB-SHARED-1", site_address="4701 River Rd",
        acreage=0.34, occupancy_type="TENANT_OCCUPIED", structure_type="MULTI_FAMILY",
    )

    for headers in (SPECIALIST, REVIEWER):
        parcels, meta = validate_paginated(
            api.list_parcels(headers, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 1
        assert len(parcels) == 1
        assert parcels[0]["id"] == parcel["id"]

    appraisals, appraisal_meta = validate_paginated(
        api.list_appraisals(MONITOR, params={"parcel_id": parcel["id"]})
    )
    assert appraisal_meta["total_count"] == 0
    assert appraisals == []

    cases, case_meta = validate_paginated(
        api.list_relocation_cases(MONITOR, params={"parcel_id": parcel["id"]})
    )
    assert case_meta["total_count"] == 0
    assert cases == []


# ─── The identity header, checked ahead of the role ───────────────────────────

def test_the_missing_identity_outranks_the_role_check_except_on_the_clock(api):
    """An empty header sinks a read and a write alike, yet the clock accepts it.

    "If `X-User-ID` is absent or empty the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is the logical-clock endpoint
    described in §2.5, which is outside the business surface and requires no identity."

    "Missing or empty `X-User-ID` - `ERR_UNAUTHENTICATED`. This applies to every
    endpoint except the logical-clock capability."

    "This capability is outside the business surface - any of the six roles may invoke
    it, it requires no `X-User-ID`, it creates and mutates nothing, it advances no
    `version`, and the only error it can return is `ERR_INVALID_REQUEST`."

    Design: Corner/rbac/an_absent_x_user_id_header_is_unauthenticated_before_any_role_check_runs
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(
        api, project_code="RB-AUTH-1", grant_program="FMA"
    )

    validate_error(
        api.get_mitigation_project(
            project["id"], build_user_headers("", "ProgramAdministrator")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    validate_error(
        api.approve_mitigation_project(
            project["id"],
            factories.approve_project_payload(project["id"], "APPROVE"),
            build_user_headers("", "StaffAppraiser"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    moved = validate_success(
        api.set_clock(
            "2026-08-02T00:00:00Z", build_user_headers("", "ProgramAdministrator")
        )
    )
    assert moved["current_utc"] == "2026-08-02T00:00:00Z"


# ─── The three duty bars, each refusing a user who holds the right role ───────

def test_the_duty_bars_refuse_the_right_role_worn_by_the_wrong_person(api):
    """Every refusal here is followed by the same call from a third party, which passes.

    "On project approval, the acting `X-User-ID` may not equal the project's
    `validated_by_user_id`, which was stamped there by whoever validated the
    benefit-cost analysis."

    "On an appraisal review decision, the acting `X-User-ID` may not equal that
    appraisal's `appraiser_user_id`. When the appraisal under decision has
    `appraisal_type` of `REVIEW`, the acting `X-User-ID` additionally may not equal the
    `appraiser_user_id` of the `INITIAL` appraisal named by `reviewed_appraisal_id`."

    "All three return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) and all three are evaluated
    at the precedence position described in §2.9."

    Design: Corner/rbac/the_three_segregation_of_duties_bars_reject_a_user_who_is_otherwise_in_role
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_validated_project(
        api,
        project_overrides={"project_code": "RB-SOD-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-RB-SOD-1", "site_address": "4801 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel_id = state["parcel"]["id"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])
    assert project["status"] == "SUBMITTED"
    assert project["validated_by_user_id"] == "pa-validator"

    validate_error(
        api.approve_mitigation_project(
            project["id"],
            factories.approve_project_payload(project["id"], "APPROVE"),
            VALIDATOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    still_submitted = validate_success(
        api.get_mitigation_project(project["id"], ADMIN)
    )
    assert still_submitted["status"] == "SUBMITTED"

    approved = validate_success(
        api.approve_mitigation_project(
            project["id"],
            factories.approve_project_payload(project["id"], "APPROVE"),
            APPROVER,
        )
    )
    assert approved["status"] == "APPROVED"

    validate_success(
        api.record_pre_event_value(
            parcel_id,
            factories.pre_event_value_payload(
                parcel_id, pre_event_fmv_cents=20_000_000,
                pre_event_value_basis="MARKET_STUDY",
            ),
            STAFF,
        )
    )
    validate_success(
        api.record_participation(
            parcel_id, factories.participation_payload(parcel_id, "INTERESTED"),
            coordinator,
        )
    )
    validate_success(
        api.record_participation(
            parcel_id,
            factories.participation_payload(
                parcel_id, "CONFIRM_VOLUNTARY",
                voluntary_acknowledgement_signed_on="2026-08-01",
            ),
            coordinator,
        )
    )

    dual_author = make_staff_appraiser_headers("dual-1")
    dual_reviewer = make_review_appraiser_headers("dual-1")

    initial = validate_success(
        api.create_appraisal(
            parcel_id,
            factories.create_appraisal_payload(
                parcel_id, appraiser_license_no="LIC-DUAL-1",
                effective_date="2026-07-01", indicated_value_cents=20_000_000,
            ),
            dual_author,
        ),
        201,
    )
    initial = validate_success(api.submit_appraisal(initial["id"], dual_author))
    assert initial["status"] == "SUBMITTED"
    assert initial["appraiser_user_id"] == "dual-1"

    validate_error(
        api.review_appraisal(
            initial["id"],
            factories.review_decision_payload(initial["id"], "ACCEPT"),
            dual_reviewer,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    unreviewed = validate_success(api.get_appraisal(initial["id"], ADMIN))
    assert unreviewed["status"] == "SUBMITTED"

    accepted_initial = validate_success(
        api.review_appraisal(
            initial["id"],
            factories.review_decision_payload(initial["id"], "ACCEPT"),
            REVIEWER,
        )
    )
    assert accepted_initial["status"] == "ACCEPTED"

    review = validate_success(
        api.create_appraisal(
            parcel_id,
            factories.create_review_appraisal_payload(
                parcel_id, initial["id"], appraiser_license_no="LIC-RA-1",
                effective_date="2026-07-05", indicated_value_cents=20_000_000,
            ),
            REVIEWER,
        ),
        201,
    )
    review = validate_success(api.submit_appraisal(review["id"], REVIEWER))
    assert review["status"] == "SUBMITTED"
    assert review["reviewed_appraisal_id"] == initial["id"]

    validate_error(
        api.review_appraisal(
            review["id"],
            factories.review_decision_payload(review["id"], "ACCEPT"),
            dual_reviewer,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    accepted_review = validate_success(
        api.review_appraisal(
            review["id"],
            factories.review_decision_payload(review["id"], "ACCEPT"),
            REVIEWER_2,
        )
    )
    assert accepted_review["status"] == "ACCEPTED"

    established = validate_success(api.get_parcel(parcel_id, ADMIN))
    assert established["acquisition_status"] == "VALUE_ESTABLISHED"
