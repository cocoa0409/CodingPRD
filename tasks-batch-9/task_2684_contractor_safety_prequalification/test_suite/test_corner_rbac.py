"""Corner section: rbac.

Role-exclusive operations refused at priority 2, identity-scoped reads refused
at priority 7, and the contractor-scoped segregation bar at priority 8.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_prequalification_state  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    ANALYST_INSURANCE,
    ANALYST_STATISTICS,
    INITIAL_CLOCK,
)
from test_helpers.factories import (  # noqa: E402
    certificate_decision_payload,
    statistic_decision_payload,
)
from test_helpers.test_users import make_analyst_headers  # noqa: E402


def test_contractor_admin_cannot_grade_and_manager_cannot_verify(build, api, admin_headers):
    """Priority 2 answers on role alone, ahead of the DRAFT transition check.

    PRD Section 2.1: "A `ClientSafetyManager` can never verify a statistic or a
    certificate; verification is reserved for the independent analyst."

    Design: Corner/rbac/contractor_admin_cannot_grade_and_manager_cannot_verify
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    contractor_headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    statistic = build.file_statistic(prequalification["id"], contractor["id"])
    assert statistic["verification_status"] == "PENDING"

    # Grading is reserved to the ClientSafetyManager, so the contractor's own
    # admin is refused on role alone rather than on the DRAFT status.
    validate_error(
        api.grade_prequalification(prequalification["id"], {}, contractor_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    validate_error(
        api.verify_statistic(
            statistic["id"],
            statistic_decision_payload("VERIFY"),
            build.manager_headers(client["id"]),
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    still_pending = validate_paginated(
        api.list_statistics(prequalification["id"], admin_headers)
    )[0][0]
    assert still_pending["verification_status"] == "PENDING", (
        "the refused manager decision must not have moved the statistic"
    )
    assert still_pending["verified_by_user_id"] is None

    # The opaque operator role is barred from grading too.
    validate_error(
        api.grade_prequalification(prequalification["id"], {}, admin_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        status="DRAFT",
        grade=None,
        final_composite_score=None,
    )


def test_contractor_admin_cannot_read_another_contractors_workers(build, api, admin_headers):
    """The shared read surface is scoped by X-User-ID, and a mismatch is 403.

    PRD Section 2.1: "When `X-User-Role` is `ContractorAdmin`, `X-User-ID` is the
    `id` of the acting `Contractor`; ownership checks on any resource that
    references a `Contractor` compare the resource's contractor reference —
    reached directly or through its parent chain — to `X-User-ID`, and a mismatch
    is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/contractor_admin_cannot_read_another_contractors_workers
    """
    build.set_clock(INITIAL_CLOCK)
    acme = build.create_contractor()
    bolt = build.create_contractor(
        legal_name="Bolt Rigging", scope_of_work=["SCAFFOLDING"], hazard_profile=["GENERAL"]
    )
    dana = build.create_worker(acme["id"])
    marco = build.create_worker(
        bolt["id"], full_name="Marco Silva", employee_ref="EMP-2002", trade_code="SCAFFOLDING"
    )
    acme_headers = build.contractor_headers(acme["id"])

    validate_error(
        api.list_workers(bolt["id"], acme_headers), ERR_NOT_RESOURCE_OWNER, 403
    )
    # Reachability is judged through Worker.contractor_id, not the URL shape.
    validate_error(api.get_worker(marco["id"], acme_headers), ERR_NOT_RESOURCE_OWNER, 403)

    own_rows, own_meta = validate_paginated(api.list_workers(acme["id"], acme_headers))
    assert own_meta["total_count"] == 1, (
        f"Acme must still see its own roster, got {own_meta['total_count']}"
    )
    assert [row["id"] for row in own_rows] == [dana["id"]]

    # NetworkAdmin reads without narrowing and without an ownership check.
    admin_rows, admin_meta = validate_paginated(
        api.list_workers(bolt["id"], admin_headers)
    )
    assert admin_meta["total_count"] == 1
    assert [row["id"] for row in admin_rows] == [marco["id"]]


def test_same_analyst_cannot_verify_statistics_and_certificates_for_one_contractor(
    build, api, admin_headers
):
    """The bar is scoped to the contractor, so the same identity clears a peer's file.

    PRD Section 2.11: "The analyst identity that verified any safety statistic
    belonging to a contractor is permanently barred from verifying that same
    contractor's insurance certificates."

    Design: Corner/rbac/same_analyst_cannot_verify_statistics_and_certificates_for_one_contractor
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    acme = build.create_contractor()
    acme_certificate = build.file_certificate(acme["id"], "GL")
    prequalification = build.open_prequalification(acme["id"], client["id"])
    statistic = build.verified_statistic(prequalification["id"], acme["id"])
    assert statistic["verified_by_user_id"] == ANALYST_STATISTICS

    bolt = build.create_contractor(
        legal_name="Bolt Rigging", scope_of_work=["SCAFFOLDING"], hazard_profile=["GENERAL"]
    )
    bolt_certificate = build.file_certificate(bolt["id"], "GL")

    barred = api.verify_certificate(
        acme_certificate["id"],
        certificate_decision_payload("VERIFY"),
        make_analyst_headers(ANALYST_STATISTICS),
    )
    validate_error(barred, ERR_SEGREGATION_OF_DUTIES, 409)
    intact = validate_paginated(
        api.list_certificates(acme["id"], admin_headers, {"coverage_type": "GL"})
    )[0][0]
    assert intact["verification_status"] == "PENDING", (
        "the barred decision must leave the certificate pending"
    )
    assert intact["verified_by_user_id"] is None

    # The same identity is untouched on a different contractor's file.
    peer = validate_success(
        api.verify_certificate(
            bolt_certificate["id"],
            certificate_decision_payload("VERIFY"),
            make_analyst_headers(ANALYST_STATISTICS),
        )
    )
    assert peer["verification_status"] == "VERIFIED"
    assert peer["verified_by_user_id"] == ANALYST_STATISTICS

    second_analyst = validate_success(
        api.verify_certificate(
            acme_certificate["id"],
            certificate_decision_payload("VERIFY"),
            make_analyst_headers(ANALYST_INSURANCE),
        )
    )
    assert second_analyst["verification_status"] == "VERIFIED"
    assert second_analyst["verified_by_user_id"] == ANALYST_INSURANCE

    # The two halves of Acme's file carry two distinct verifier identities.
    filed = validate_paginated(
        api.list_statistics(prequalification["id"], admin_headers)
    )[0][0]
    assert filed["verified_by_user_id"] == ANALYST_STATISTICS
    assert filed["verified_by_user_id"] != second_analyst["verified_by_user_id"]
