"""Authorization: permitted role lists, segregation of duties, and the order in
which authentication, authorization and body validation are decided.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_instant,
    assert_page,
)
from test_helpers.constants import (
    CLOCK_DEFAULT_UTC,
    ENGINEER_USER_ID,
    PEER_USER_ID,
    SPONSOR_USER_ID,
    UNBOUND_PURCHASER_USER_ID,
    UNBOUND_TENANT_USER_ID,
)
from test_helpers.factories import (
    component_payload,
    roof_standard,
    peer_review_payload,
    project_payload,
    report_payload,
)
from test_helpers.fixtures import (
    make_component,
    make_household,
    make_project,
    make_report,
    submit_report,
)
from test_helpers.test_users import (
    admin_headers,
    engineer_headers,
    escrow_headers,
    headers_without_auth,
    lender_headers,
    peer_headers,
    purchaser_headers,
    regulator_headers,
    sponsor_headers,
    tenant_headers,
)

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_sponsor_and_peer_reviewer_cannot_submit_an_engineering_report(api):
    """PRD: When the inventory is complete the `LicensedEngineer` submits the report,
    moving its `status` `DRAFT → SUBMITTED`.

    Design: Corner/rbac/sponsor_and_peer_reviewer_cannot_submit_an_engineering_report
    """
    project = make_project(api, *STD_PROJECT)
    report = validate_success(
        api.create_report(project["id"], report_payload(), sponsor_headers()),
        expected_status=201,
    )
    make_component(api, report["id"], component_payload("ROOF", 30, 10, 10000000))

    before = validate_success(api.get_report(report["id"], engineer_headers()))
    assert before["status"] == "DRAFT"

    validate_error(
        api.submit_report(report["id"], sponsor_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.submit_report(report["id"], peer_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    still_draft = validate_success(api.get_report(report["id"], engineer_headers()))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["revision_round"] == 0

    submitted = validate_success(api.submit_report(report["id"], engineer_headers()))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 1
    assert submitted["submitted_by_user_id"] == ENGINEER_USER_ID


def test_peer_review_by_the_submitting_user_is_refused(api):
    """PRD: Last on this rung, a peer-review decision whose acting `X-User-ID` equals
    the report's `submitted_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`, HTTP 403.

    Design: Corner/rbac/peer_review_by_the_submitting_user_is_refused
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api, report["id"], component_payload("ROOF", 30, 10, 10000000)
    )
    submit_report(api, report["id"])
    validate_success(api.verify_component(component["id"], True, peer_headers()))

    before = validate_success(api.get_report(report["id"], peer_headers()))
    assert before["submitted_by_user_id"] == ENGINEER_USER_ID
    assert before["verified_component_count"] == 1

    validate_error(
        api.peer_review(
            report["id"],
            peer_review_payload("ACCEPT", ENGINEER_USER_ID),
            peer_headers(ENGINEER_USER_ID),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=403,
    )
    refused = validate_success(api.get_report(report["id"], peer_headers()))
    assert refused["status"] == "SUBMITTED"
    assert refused["reviewed_by_user_id"] is None

    accepted = validate_success(
        api.peer_review(
            report["id"], peer_review_payload("ACCEPT", PEER_USER_ID), peer_headers()
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewed_by_user_id"] == PEER_USER_ID


def test_batch_release_is_escrow_agent_only_and_still_blocked_by_restricted_posture(api):
    """PRD: A `RESTRICTED` posture rejects exactly one operation — releasing a
    closing batch — with `ERR_PROJECT_RESTRICTED` (HTTP 409); every other write is
    permitted.

    Design: Corner/rbac/batch_release_is_escrow_agent_only_and_still_blocked_by_restricted_posture
    """
    project = make_project(api, *STD_PROJECT)
    batch = validate_success(
        api.create_batch(
            project["id"],
            {
                "batch_sequence_no": 1,
                "window_start_at": "2026-09-01T00:00:00Z",
                "window_end_at": "2026-10-01T00:00:00Z",
                "min_presale_threshold_pct": 50,
                "min_absolute_unit_count": 1,
            },
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "posture"
    ] == "RESTRICTED"
    assert batch["status"] == "DRAFT"

    validate_error(
        api.release_batch(batch["id"], sponsor_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.release_batch(batch["id"], regulator_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.release_batch(batch["id"], escrow_headers()),
        "ERR_PROJECT_RESTRICTED",
        expected_status=409,
    )
    after = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert after["status"] == "DRAFT"
    assert after["released_at"] is None
    assert after["version"] == batch["version"]


def test_tenant_occupant_and_purchaser_cannot_drive_sponsor_workflows(api):
    """PRD: Second, a well-formed identity acting on an operation its role is not
    authorised for is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

    Design: Corner/rbac/tenant_occupant_and_purchaser_cannot_drive_sponsor_workflows
    """
    project = make_project(api, *STD_PROJECT)
    household = make_household(
        api, project["id"], "H-1", "2020-01-01T00:00:00Z", 150000
    )

    validate_error(
        api.serve_notice(household["id"], tenant_headers(household["id"])),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    unchanged = validate_success(
        api.get_household(household["id"], sponsor_headers())
    )
    assert unchanged["notice_status"] == "PRE_NOTICE"
    assert unchanged["notice_served_at"] is None

    validate_error(
        api.create_project(
            project_payload("9 Elm Street, Bangor ME", 1972, 3, "sponsor-2"),
            purchaser_headers(UNBOUND_PURCHASER_USER_ID),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    _, meta = validate_paginated(api.list_projects(sponsor_headers()))
    assert_page(meta, total_count=1)

    rows, meta = validate_paginated(
        api.list_units(
            tenant_headers(household["id"]), params={"conversion_project_id": project["id"]}
        )
    )
    assert_page(meta, total_count=0)
    assert rows == []
    validate_paginated(
        api.list_units(
            purchaser_headers(UNBOUND_PURCHASER_USER_ID),
            params={"conversion_project_id": project["id"]},
        )
    )


def test_only_the_converter_sponsor_may_create_a_conversion_project(api):
    """PRD: A `ConverterSponsor` opens the file by registering a **conversion
    project**, supplying the `building_address` of the building being converted (a
    non-empty string of at most 200 characters), the `year_built` of original
    construction (a whole year no earlier than 1800 and no later than 2026, both
    endpoints accepted), the `total_unit_count` that the plat is expected to define
    (a whole number of at least 2 and at most 400, both endpoints accepted), and the
    `sponsor_user_id` that identifies the sponsoring operator.

    Design: Corner/rbac/only_the_converter_sponsor_may_create_a_conversion_project
    """
    seed = make_project(api, "1 Seed Road, Bangor ME", 1960, 2, "sponsor-0")
    payload = project_payload(*STD_PROJECT)

    for headers in (
        regulator_headers(),
        lender_headers(),
        escrow_headers(),
        admin_headers(),
    ):
        validate_error(
            api.create_project(payload, headers),
            "ERR_ROLE_NOT_PERMITTED",
            expected_status=403,
        )
    _, meta = validate_paginated(api.list_projects(sponsor_headers()))
    assert_page(meta, total_count=1)

    patched = validate_success(
        api.patch_project(seed["id"], {"total_unit_count": 4}, admin_headers())
    )
    assert patched["total_unit_count"] == 4

    created = validate_success(api.create_project(payload, sponsor_headers()), 201)
    assert created["sponsor_user_id"] == SPONSOR_USER_ID
    _, meta = validate_paginated(api.list_projects(sponsor_headers()))
    assert_page(meta, total_count=2)


def test_project_read_is_shared_by_seven_roles_and_closed_to_the_other_two(api):
    """PRD: The acting role must appear in the target operation's permitted role
    list, or the request fails with `ERR_ROLE_NOT_PERMITTED`, HTTP 403.

    Design: Corner/rbac/project_read_is_shared_by_seven_roles_and_closed_to_the_other_two
    """
    project = make_project(api, *STD_PROJECT)

    for headers in (
        sponsor_headers(),
        regulator_headers(),
        lender_headers(),
        escrow_headers(),
        admin_headers(),
        engineer_headers(),
        peer_headers(),
    ):
        data = validate_success(api.get_project(project["id"], headers))
        assert data["id"] == project["id"]
        assert data["status"] == "FEASIBILITY"
        assert data["posture"] == "RESTRICTED"

    validate_error(
        api.get_project(project["id"], purchaser_headers(UNBOUND_PURCHASER_USER_ID)),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.get_project(project["id"], tenant_headers(UNBOUND_TENANT_USER_ID)),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    assert validate_success(api.get_project(project["id"], sponsor_headers()))["version"] == 1


def test_component_edits_and_component_verification_are_split_between_the_peer_roles(api):
    """PRD: A `PeerReviewEngineer` — never the authoring `LicensedEngineer` — marks a
    component `VERIFIED`, which recomputes the parent report's
    `verified_component_count`.

    Design: Corner/rbac/component_edits_and_component_verification_are_split_between_the_peer_roles
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(api, report["id"], roof_standard())

    edited = validate_success(
        api.patch_component(
            component["id"], {"remaining_useful_life_years": 26}, engineer_headers()
        )
    )
    assert edited["remaining_useful_life_years"] == 26
    assert edited["verification_status"] == "UNVERIFIED"

    validate_error(
        api.verify_component(component["id"], True, engineer_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    still = validate_success(api.get_component(component["id"], engineer_headers()))
    assert still["verification_status"] == "UNVERIFIED"
    parent = validate_success(api.get_report(report["id"], engineer_headers()))
    assert parent["verified_component_count"] == 0

    verified = validate_success(
        api.verify_component(component["id"], True, peer_headers())
    )
    assert verified["verification_status"] == "VERIFIED"
    parent = validate_success(api.get_report(report["id"], engineer_headers()))
    assert parent["verified_component_count"] == 1

    validate_error(
        api.patch_component(
            component["id"], {"remaining_useful_life_years": 12}, peer_headers()
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    final = validate_success(api.get_component(component["id"], peer_headers()))
    assert final["remaining_useful_life_years"] == 26
    assert final["verification_status"] == "VERIFIED"


def test_clock_control_is_limited_to_the_five_declared_roles(api):
    """PRD: On startup that clock reads exactly `2026-08-01T00:00:00Z`.

    Design: Corner/rbac/clock_control_is_limited_to_the_five_declared_roles
    """
    tenant_read = validate_success(
        api.get_clock(tenant_headers(UNBOUND_TENANT_USER_ID))
    )
    assert_instant(tenant_read["current_utc"], CLOCK_DEFAULT_UTC)

    validate_error(
        api.set_clock("2027-01-01T00:00:00Z", engineer_headers()),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.set_clock(
            "2027-01-01T00:00:00Z", purchaser_headers(UNBOUND_PURCHASER_USER_ID)
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    buyer_read = validate_success(
        api.get_clock(purchaser_headers(UNBOUND_PURCHASER_USER_ID))
    )
    assert_instant(buyer_read["current_utc"], CLOCK_DEFAULT_UTC)

    validate_success(api.set_clock("2027-01-01T00:00:00Z", admin_headers()))
    peer_read = validate_success(api.get_clock(peer_headers()))
    assert_instant(peer_read["current_utc"], "2027-01-01T00:00:00Z")


def test_role_denial_precedes_project_existence_lookup(api):
    """PRD: Rung 2 — role, identity and separation of duties. … Rung 3 — existence of
    every referenced entity.

    Design: Corner/validations/role_denial_precedes_project_existence_lookup
    """
    project = make_project(api, *STD_PROJECT)

    validate_error(
        api.create_report(
            NON_EXISTENT_UUID,
            report_payload(submitted_by_user_id=UNBOUND_TENANT_USER_ID),
            tenant_headers(UNBOUND_TENANT_USER_ID),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.create_report(
            NON_EXISTENT_UUID,
            report_payload(submitted_by_user_id=ENGINEER_USER_ID),
            engineer_headers(),
        ),
        "ERR_PROJECT_NOT_FOUND",
        expected_status=404,
    )
    _, meta = validate_paginated(api.list_reports(project["id"], engineer_headers()))
    assert_page(meta, total_count=0)


def test_missing_auth_headers_precede_role_and_body_validation(api):
    """PRD: Rung 1 — authentication. A request missing `X-User-ID` or `X-User-Role`
    fails with `ERR_MISSING_AUTH_HEADERS`, HTTP 401, before anything else is
    considered.

    Design: Corner/validations/missing_auth_headers_precede_role_and_body_validation
    """
    make_project(api, *STD_PROJECT)
    malformed = {
        "building_address": "9 Nowhere St",
        "total_unit_count": 2,
        "sponsor_user_id": UNBOUND_TENANT_USER_ID,
    }

    validate_error(
        api.create_project(malformed, headers_without_auth()),
        "ERR_MISSING_AUTH_HEADERS",
        expected_status=401,
    )
    validate_error(
        api.create_project(malformed, tenant_headers(UNBOUND_TENANT_USER_ID)),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    validate_error(
        api.create_project(
            dict(malformed, sponsor_user_id=SPONSOR_USER_ID), sponsor_headers()
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    _, meta = validate_paginated(api.list_projects(sponsor_headers()))
    assert_page(meta, total_count=1)
