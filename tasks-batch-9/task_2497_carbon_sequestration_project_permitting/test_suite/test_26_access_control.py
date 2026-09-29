"""Access control on the carbon storage permitting surface.

The concern under test is who may act: which role may open a project file, which
role owns the exclusive right to verify a secure-storage claim, when a landowner
who holds the role is still not the landowner of the tract, what happens when the
identity headers are incomplete, when a reviewer's own earlier technical judgement
disqualifies it from certifying closure, and which non-writing roles may still
read a project.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_USER_ID,
    LANDOWNER_1_USER_ID,
    LANDOWNER_2_USER_ID,
    SECOND_REVIEWER_USER_ID,
    ApiErrorId,
    assert_pore_space_tract,
    assert_storage_project,
    factories,
    fixtures,
    make_landowner_headers,
)
from test_helpers.constants import MISSING_CLAIM_ID, STARTUP_CLOCK_UTC


def test_open_storage_project_as_program_admin_allowed(api, program_admin_headers):
    """`ProgramAdmin` is the state program administrator: it alone opens project files and it alone controls the server's logical clock.

    Status codes follow one rule throughout: an operation that brings a new resource into existence responds with 201 Created, and every other successful operation — including every action endpoint that advances a state machine, every listing and every read — responds with 200 OK.

    A newly created project is initialised into a well-defined resting state: `status` is `DRAFT`, `operational_posture` is `OPEN`, `unitization_status` is `NOT_FILED`, and `closure_status` is `NOT_REQUESTED`.

    `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations that arrive as a cascade from a sibling or parent operation rather than as a direct request against the resource.

    At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and until it is explicitly moved it continues to read that instant — it never falls back to wall-clock time.

    Design: Corner/rbac/program_admin_creates_storage_project_allowed
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)

    response = api.create_storage_project(
        factories.create_storage_project_payload(), program_admin_headers
    )

    created = validate_success(response, 201)
    assert_storage_project(created)
    assert created["status"] == "DRAFT"
    assert created["operational_posture"] == "OPEN"
    assert created["version"] == 1

    stored = fixtures.refresh_project(api, created["id"], program_admin_headers)
    assert stored["created_at"].startswith("2026-08-01T00:00:00")
    assert stored["unitization_status"] == "NOT_FILED"


def test_open_storage_project_as_project_developer_unauthorized(
    api, program_admin_headers, project_developer_headers
):
    """`ProgramAdmin` is the state program administrator: it alone opens project files and it alone controls the server's logical clock.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/project_developer_cannot_create_storage_project_unauthorized
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)

    response = api.create_storage_project(
        factories.create_storage_project_payload(), project_developer_headers
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    projects, meta = validate_paginated(
        api.list_storage_projects(program_admin_headers)
    )
    assert meta["total_count"] == 0
    assert projects == []


def test_verify_tax_credit_claim_as_regulatory_reviewer_unauthorized(
    api, regulatory_reviewer_headers
):
    """`IndependentVerifier` is the third-party verifier of secure geologic storage reports and lifecycle-adjusted credit claims; its only mutating capability is ruling on a submitted claim.

    An `IndependentVerifier` then rules on a submitted claim with a `decision` of `ALLOW` or `DISALLOW`, optionally attaching a `verification_note`.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    The system evaluates checks in a fixed precedence ladder, and the first failing check produces the response; later checks are not evaluated.

    Design: Corner/rbac/regulatory_reviewer_cannot_verify_tax_credit_claim_unauthorized
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)

    response = api.verify_tax_credit_claim(
        MISSING_CLAIM_ID,
        {
            "decision": "ALLOW",
            "verification_note": "independent verification of secure geologic storage",
        },
        regulatory_reviewer_headers,
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}


def test_respond_to_lease_offer_as_other_landowner_forbidden(api):
    """When `X-User-Role` is `Landowner`, `X-User-ID` is an opaque identifier that is not the `id` of any persisted entity, but it is nevertheless compared: a tract stores the opaque identifier of the landowner entitled to negotiate it in its `landowner_user_id` field, and a landowner responding to an offer must present an `X-User-ID` equal to that stored value.

    A mismatch is rejected with `ERR_NOT_TRACT_LANDOWNER` (HTTP 403).

    All three require the tract to be at `OFFER_SENT` and require the acting `X-User-ID` to equal the tract's `landowner_user_id`.

    Every offer increments `negotiation_round_count` by one and sets `lease_status` to `OFFER_SENT`, bumping the tract's `version`.

    A new tract rests at `lease_status` `UNLEASED` with `negotiation_round_count`, `bonus_settlement_usd` and `net_acreage` all at 0.

    Design: Corner/rbac/landowner_responds_only_on_own_tract_forbidden
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_1_USER_ID,
    )
    offered = fixtures.send_offer(
        api, tract, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5
    )
    assert offered["lease_status"] == "OFFER_SENT"

    response = api.respond_to_lease_offer(
        tract["id"],
        factories.accept_offer_payload(),
        make_landowner_headers(LANDOWNER_2_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_NOT_TRACT_LANDOWNER.value, 403)

    stored_tract = fixtures.refresh_tract(api, tract["id"])
    assert_pore_space_tract(stored_tract)
    assert stored_tract["lease_status"] == "OFFER_SENT"
    assert stored_tract["negotiation_round_count"] == 1
    assert stored_tract["net_acreage"] == 0

    stored_project = fixtures.refresh_project(api, project["id"])
    assert stored_project["secured_acreage"] == 0


def test_read_storage_project_without_role_header_unauthenticated(
    api, program_admin_headers
):
    """Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts.

    If either header is absent, or if `X-User-Role` holds any value outside those five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

    The system evaluates checks in a fixed precedence ladder, and the first failing check produces the response; later checks are not evaluated.

    Design: Corner/rbac/missing_x_user_role_header_unauthenticated
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)

    headers_without_role = {
        "X-User-ID": ADMIN_USER_ID,
        "Content-Type": "application/json",
    }
    response = api.get_storage_project(project["id"], headers_without_role)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}

    stored = fixtures.refresh_project(api, project["id"], program_admin_headers)
    assert stored["version"] == 1


def test_certify_closure_by_permit_technical_reviewer_forbidden(
    api, second_reviewer_headers
):
    """Two duties are mutually exclusive, and the system enforces the separation on identity rather than on role.

    Closure certification requires that the acting `X-User-ID` differ from the `technical_reviewer_user_id` of every one of the project's injection well permits — a reviewer who passed technical judgement on any well of the project is disqualified from certifying that project's closure.

    Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Opening review records the reviewer's `X-User-ID` in `technical_reviewer_user_id` — the field that later disqualifies that same identity from certifying the project's closure — and moves `permit_status` `SUBMITTED → TECHNICAL_REVIEW`.

    The system evaluates checks in a fixed precedence ladder, and the first failing check produces the response; later checks are not evaluated.

    Design: Corner/rbac/certify_closure_by_the_permit_technical_reviewer_forbidden
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])
    fixtures.submit_permit(api, permit["id"], submission_note="Class VI application")
    permit = fixtures.rule_on_permit(
        api,
        permit["id"],
        "BEGIN_TECHNICAL_REVIEW",
        headers=second_reviewer_headers,
        review_note="assigned to reviewer-2",
    )
    assert permit["permit_status"] == "TECHNICAL_REVIEW"
    assert permit["technical_reviewer_user_id"] == SECOND_REVIEWER_USER_ID

    project_before = fixtures.refresh_project(api, ctx["project"]["id"])

    response = api.certify_closure(
        ctx["project"]["id"],
        {"non_endangerment_demonstrated": True, "closure_note": "attempting closure"},
        second_reviewer_headers,
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    stored = fixtures.refresh_project(api, ctx["project"]["id"])
    assert stored["status"] == "PERMITTING"
    assert stored["closure_status"] == "NOT_REQUESTED"
    assert stored["non_endangerment_demonstrated"] is False
    assert stored["closure_certified_by_user_id"] is None
    assert stored["closure_certified_at"] is None
    assert stored["version"] == project_before["version"]


def test_read_storage_project_shared_by_independent_verifier_and_landowner(
    api, independent_verifier_headers, landowner_headers
):
    """`IndependentVerifier` is the third-party verifier of secure geologic storage reports and lifecycle-adjusted credit claims; its only mutating capability is ruling on a submitted claim.

    `Landowner` is the surface and pore-space owner negotiating a storage lease, and its only mutating capability is responding to an outstanding lease offer on its own tract.

    When a single storage project is read, the server recomputes its derived fields against the current logical clock before responding — in particular `pisc_elapsed_years`, which is a function of elapsed logical time and therefore changes without any write having occurred.

    Design: Corner/rbac/independent_verifier_reads_the_project_the_landowner_can_also_read
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)

    verifier_read = validate_success(
        api.get_storage_project(project["id"], independent_verifier_headers), 200
    )
    landowner_read = validate_success(
        api.get_storage_project(project["id"], landowner_headers), 200
    )

    assert verifier_read["status"] == "DRAFT"
    assert landowner_read["status"] == "DRAFT"
    assert verifier_read["outstanding_acreage"] == 4000.0000
    assert landowner_read["outstanding_acreage"] == 4000.0000
    assert verifier_read["version"] == 1
    assert landowner_read["version"] == 1
