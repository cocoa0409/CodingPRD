"""Corner section: errors.

Per-segment 404 codes and the generic fallback, body-reference order, the four
gates that demand an active contractor or a clear incident flag, both duplicate
arms, the cascade-depth ceiling, the last check in the badge ladder, and the
header check that precedes everything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_CASCADE_DEPTH_EXCEEDED,
    ERR_CONTRACTOR_NOT_ACTIVE,
    ERR_DUPLICATE_PREQUALIFICATION,
    ERR_GRADE_BELOW_SITE_MINIMUM,
    ERR_IMPROVEMENT_PLAN_NOT_FOUND,
    ERR_INCIDENT_REVIEW_ACTIVE,
    ERR_INSURANCE_CERTIFICATE_NOT_FOUND,
    ERR_PREQUALIFICATION_NOT_FOUND,
    ERR_RECORD_NOT_FOUND,
    ERR_SITE_NOT_FOUND,
    ERR_STATISTICS_UNVERIFIED,
    ERR_UNAUTHENTICATED,
    ERR_WORKER_NOT_FOUND,
)
from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_grant_state,
    assert_instant_equals,
    assert_prequalification_state,
    assert_score_equals,
    assert_site_posture,
    assert_versioned_row,
)
from test_helpers.constants import (  # noqa: E402
    ANALYST_STATISTICS,
    INITIAL_CLOCK,
    ROLE_CONTRACTOR_ADMIN,
)
from test_helpers.factories import (  # noqa: E402
    certificate_decision_payload,
    grant_payload,
    improvement_plan_submit_payload,
    link_payload,
    prequalification_payload,
    program_resubmit_payload,
    statistic_payload,
)
from test_helpers.test_users import (  # noqa: E402
    make_analyst_headers,
    make_contractor_admin_headers,
    make_headers_without_role,
    make_headers_without_user_id,
)


def test_unknown_path_ids_return_their_entity_specific_not_found_error(
    build, api, admin_headers
):
    """One bogus UUID, six endpoints, five dedicated codes and one fallback.

    PRD Section 2.6: "Leaf rows without a dedicated code — a safety statistic, a
    written program, a worker qualification, a site access grant, an incident
    report, a variance or a subcontractor link — yield `ERR_RECORD_NOT_FOUND`."

    Design: Corner/errors/unknown_path_ids_return_their_entity_specific_not_found_error
    """
    build.set_clock(INITIAL_CLOCK)

    validate_error(
        api.get_prequalification(NON_EXISTENT_UUID, admin_headers),
        ERR_PREQUALIFICATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_site(NON_EXISTENT_UUID, admin_headers), ERR_SITE_NOT_FOUND, 404
    )
    validate_error(
        api.get_worker(NON_EXISTENT_UUID, admin_headers), ERR_WORKER_NOT_FOUND, 404
    )
    validate_error(
        api.verify_certificate(
            NON_EXISTENT_UUID, certificate_decision_payload("VERIFY"), make_analyst_headers()
        ),
        ERR_INSURANCE_CERTIFICATE_NOT_FOUND,
        404,
    )

    # Priority 5 precedes the ownership check at priority 7, so an unresolvable
    # plan never reports ERR_NOT_RESOURCE_OWNER even to a stranger.
    stranger = make_contractor_admin_headers(NON_EXISTENT_UUID)
    validate_error(
        api.submit_improvement_plan(
            NON_EXISTENT_UUID, improvement_plan_submit_payload(), stranger
        ),
        ERR_IMPROVEMENT_PLAN_NOT_FOUND,
        404,
    )

    # A written program is a leaf row with no dedicated code of its own.
    validate_error(
        api.resubmit_program(
            NON_EXISTENT_UUID,
            program_resubmit_payload(document_ref="DOC-HAZCOM-9"),
            stranger,
        ),
        ERR_RECORD_NOT_FOUND,
        404,
    )


def test_site_access_grant_body_fks_resolve_in_the_declared_input_order(build, api):
    """Three probes walk the reported code down worker, site, prequalification.

    PRD Section 2.9: "References carried in a request body are resolved after
    every path segment has resolved, and they are resolved in the order the
    endpoint declares its input fields."

    Design: Corner/errors/site_access_grant_body_fks_resolve_in_the_declared_input_order
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    site = build.create_site(client["id"], required_hazard_classes=["GENERAL"])
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])
    worker = build.create_worker(contractor["id"])
    # A DRAFT row is enough: priority 6 precedes every business gate.
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    assert_prequalification_state(prequalification, status="DRAFT")

    all_bogus = api.create_grant(
        grant_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            "2026-12-31T00:00:00Z",
        ),
        headers,
    )
    validate_error(all_bogus, ERR_WORKER_NOT_FOUND, 404)

    worker_fixed = api.create_grant(
        grant_payload(
            worker["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID, "2026-12-31T00:00:00Z"
        ),
        headers,
    )
    validate_error(worker_fixed, ERR_SITE_NOT_FOUND, 404)

    site_fixed = api.create_grant(
        grant_payload(
            worker["id"], site["id"], NON_EXISTENT_UUID, "2026-12-31T00:00:00Z"
        ),
        headers,
    )
    validate_error(site_fixed, ERR_PREQUALIFICATION_NOT_FOUND, 404)

    assert_site_posture(
        validate_success(api.get_site(site["id"], build.manager_headers(client["id"]))),
        granted_worker_count=0,
    )
    rows, meta = validate_paginated(
        api.list_grants(build.admin_headers, {"site_id": site["id"]})
    )
    assert meta["total_count"] == 0, (
        f"three refused requests must have badged nobody, got {meta['total_count']}"
    )
    assert rows == []


def test_suspended_contractor_cannot_open_a_new_prequalification(build, api, admin_headers):
    """The version guard at priority 9 passes and priority 11 still refuses.

    PRD Section 3.1: "It only closes the door on new activity, surfacing as
    `ERR_CONTRACTOR_NOT_ACTIVE` on the four operations that demand an active
    contractor: opening a prequalification cycle, submitting one for review,
    requesting a site badge, and creating a subcontractor edge."

    Design: Corner/errors/suspended_contractor_cannot_open_a_new_prequalification
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    assert_versioned_row(contractor, 1)

    suspended = validate_success(
        api.patch_contractor(contractor["id"], {"status": "SUSPENDED"}, admin_headers)
    )
    assert_contractor_posture(suspended, status="SUSPENDED")
    assert_versioned_row(suspended, 2)

    # The expected version is correct, so the OCC check at priority 9 passes and
    # the refusal can only come from the status gate at priority 11.
    refused = api.create_prequalification(
        prequalification_payload(contractor["id"], client["id"], 2, 2026),
        build.contractor_headers(contractor["id"]),
    )
    validate_error(refused, ERR_CONTRACTOR_NOT_ACTIVE, 409)

    _rows, meta = validate_paginated(
        api.list_prequalifications(admin_headers, {"contractor_id": contractor["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused create must have written no row, got {meta['total_count']}"
    )
    assert_versioned_row(build.read_contractor(contractor["id"]), 2)

    restored = validate_success(
        api.patch_contractor(contractor["id"], {"status": "ACTIVE"}, admin_headers)
    )
    assert_contractor_posture(restored, status="ACTIVE")
    assert_versioned_row(restored, 3)

    accepted = validate_success(
        api.create_prequalification(
            prequalification_payload(contractor["id"], client["id"], 3, 2026),
            build.contractor_headers(contractor["id"]),
        ),
        201,
    )
    assert_prequalification_state(accepted, status="DRAFT")


def test_second_open_prequalification_for_the_same_client_is_rejected(
    build, api, admin_headers
):
    """The in-flight arm ignores the cycle year and is scoped per client pair.

    PRD Section 3.2: "The first forbids a second in-flight application: no
    prequalification may already exist for the same contractor and client with a
    `status` of `DRAFT`, `SUBMITTED` or `UNDER_REVIEW`, regardless of cycle year."

    Design: Corner/errors/second_open_prequalification_for_the_same_client_is_rejected
    """
    build.set_clock(INITIAL_CLOCK)
    northwind = build.create_client()
    southgate = build.create_client(
        legal_name="Southgate Industrial", industry_code="236210"
    )
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])

    first = build.open_prequalification(contractor["id"], northwind["id"])
    assert_prequalification_state(first, status="DRAFT")
    current = build.read_contractor(contractor["id"])["version"]

    # Same pair, a different cycle year: still one open conversation too many.
    duplicate = api.create_prequalification(
        prequalification_payload(contractor["id"], northwind["id"], current, 2027),
        headers,
    )
    validate_error(duplicate, ERR_DUPLICATE_PREQUALIFICATION, 409)

    other_client = validate_success(
        api.create_prequalification(
            prequalification_payload(contractor["id"], southgate["id"], current, 2026),
            headers,
        ),
        201,
    )
    assert_prequalification_state(other_client, status="DRAFT")
    assert other_client["client_id"] == southgate["id"]

    rows, meta = validate_paginated(
        api.list_prequalifications(admin_headers, {"contractor_id": contractor["id"]})
    )
    assert meta["total_count"] == 2, (
        f"expected the Northwind and Southgate rows only, got {meta['total_count']}"
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [first["id"], other_client["id"]]
    )


def test_submit_without_a_governing_statistic_is_rejected(build, api):
    """Priority 14 fires ahead of the missing-program check with zero programs filed.

    PRD Section 3.3: "That dimension is derived, not stored independently: it
    reads `NOT_SUBMITTED` while no statistic row exists at all; otherwise it takes
    the `verification_status` of the **governing** statistic, meaning the row with
    the greatest `reporting_year` among those whose `verification_status` is
    `PENDING` or `VERIFIED`; and it reads `REJECTED` when statistic rows exist but
    none of them is `PENDING` or `VERIFIED`."

    Design: Corner/errors/submit_without_a_governing_statistic_is_rejected
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    filed = build.file_statistic(prequalification["id"], contractor["id"])
    assert filed["reporting_year"] == 2025
    refused_row = build.decide_statistic(filed["id"], "REJECT", ANALYST_STATISTICS)
    assert refused_row["verification_status"] == "REJECTED"

    # No written program exists at all, yet 14 outranks 15.
    _rows, program_meta = validate_paginated(
        api.list_programs(prequalification["id"], headers)
    )
    assert program_meta["total_count"] == 0
    refused = api.submit_prequalification(prequalification["id"], {}, headers)
    validate_error(refused, ERR_STATISTICS_UNVERIFIED, 409)

    # One row exists and it is REJECTED, so the dimension reads REJECTED.
    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        status="DRAFT",
        statistics_verification_status="REJECTED",
        provisional_composite_score=None,
    )
    intact = validate_success(api.get_prequalification(prequalification["id"], headers))
    assert intact["status"] == "DRAFT"

    replacement = validate_success(
        api.create_statistic(
            prequalification["id"],
            statistic_payload(reporting_year=2024, source_document_ref="OSHA300A-2024"),
            headers,
        ),
        201,
    )
    assert replacement["verification_status"] == "PENDING"
    # 2024 is the greatest reporting_year among PENDING or VERIFIED rows, so the
    # merely PENDING row now governs even though the REJECTED row is newer.
    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        statistics_verification_status="PENDING",
    )

    build.accept_required_programs(
        prequalification["id"], contractor["id"], client["id"], ["GENERAL"]
    )
    submitted = validate_success(
        api.submit_prequalification(prequalification["id"], {}, headers)
    )
    assert_prequalification_state(submitted, status="SUBMITTED", grade=None)
    assert_score_equals(submitted["provisional_composite_score"], 80.51)


def test_lost_time_incident_blocks_submit_until_the_review_is_closed(build, api):
    """Priority 13 refuses a submission whose statistics and programs are already in place.

    PRD Section 3.9: "Second, when the `severity` is `LOST_TIME` or `FATALITY`,
    the contractor's `incident_review_flag` is set true; the flag reads true
    whenever at least one of the contractor's lost-time or fatal reports still has
    an open review, and while it is true the contractor can neither submit nor be
    graded."

    Design: Corner/errors/lost_time_incident_blocks_submit_until_the_review_is_closed
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(submit=False, grade=False)
    headers = scenario["contractor_headers"]
    manager = scenario["manager_headers"]
    # Priorities 14 and 15 are already satisfied: the statistic is VERIFIED and
    # both required programs are ACCEPTED.
    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]),
        status="DRAFT",
        statistics_verification_status="VERIFIED",
    )

    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="LOST_TIME",
        description="Fall from a work platform with lost workdays",
    )
    assert incident["review_status"] == "OPEN"

    refused = api.submit_prequalification(scenario["prequalification_id"], {}, headers)
    validate_error(refused, ERR_INCIDENT_REVIEW_ACTIVE, 409)
    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]), status="DRAFT"
    )
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]),
        incident_review_flag=True,
        open_severe_incident_count=1,
    )

    closed = validate_success(
        api.close_incident_review(
            incident["id"],
            {"findings_note": "Platform guardrail replaced and crew retrained"},
            manager,
        )
    )
    assert closed["review_status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], INITIAL_CLOCK)

    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]),
        incident_review_flag=False,
        open_severe_incident_count=0,
    )
    assert_site_posture(
        validate_success(api.get_site(scenario["site_id"], manager)),
        access_gate_status="OPEN",
    )

    submitted = validate_success(
        api.submit_prequalification(scenario["prequalification_id"], {}, headers)
    )
    # PRD Section 3.4: the submission itself performs the fork-join when both
    # dimensions were already satisfied before the row left DRAFT — the verified
    # statistic and the accepted required programs satisfy both here.
    assert_prequalification_state(submitted, status="UNDER_REVIEW", grade=None)
    assert_score_equals(submitted["provisional_composite_score"], 80.51)


def test_third_generation_subcontractor_link_exceeds_the_cascade_depth_limit(build, api):
    """Depths 1 and 2 stand, depth 3 is refused before the child's coverage is read.

    PRD Section 3.10: "The computed depth is then compared against the client's
    `cascade_depth_limit` — a default limit of 2 permits a prime's subcontractor
    and that subcontractor's own subcontractor, and refuses a third tier."

    Design: Corner/errors/third_generation_subcontractor_link_exceeds_the_cascade_depth_limit
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    headers = scenario["contractor_headers"]
    assert_prequalification_state(
        scenario["prequalification"], status="APPROVED", grade="B"
    )
    assert_score_equals(scenario["prequalification"]["final_composite_score"], 80.51)

    generation_one = build.create_contractor(
        legal_name="Cable Crew", scope_of_work=["ELECTRICAL_TRADE"], hazard_profile=["GENERAL"]
    )
    build.verified_certificate(generation_one["id"], "GL")
    generation_two = build.create_contractor(
        legal_name="Deep Foundations", scope_of_work=["EARTHWORK"], hazard_profile=["GENERAL"]
    )
    build.verified_certificate(generation_two["id"], "GL")
    # Summit Steel holds no certificate at all, so the coverage check at priority
    # 29 would also fail if it were ever reached.
    generation_three = build.create_contractor(
        legal_name="Summit Steel Erectors",
        scope_of_work=["GENERAL_BUILDING"],
        hazard_profile=["GENERAL"],
        employee_count=120,
    )

    first = validate_success(
        api.create_link(
            link_payload(
                scenario["contractor_id"],
                generation_one["id"],
                scenario["prequalification_id"],
                ["ELECTRICAL_TRADE"],
            ),
            headers,
        ),
        201,
    )
    assert first["depth"] == 1, f"an edge off the prime sits at depth 1, got {first['depth']}"
    assert first["status"] == "ACTIVE"

    second = validate_success(
        api.create_link(
            link_payload(
                generation_one["id"],
                generation_two["id"],
                scenario["prequalification_id"],
                ["EARTHWORK"],
            ),
            headers,
        ),
        201,
    )
    assert second["depth"] == 2, (
        f"exactly at the default cascade_depth_limit, got {second['depth']}"
    )
    assert second["status"] == "ACTIVE"

    third = api.create_link(
        link_payload(
            generation_two["id"],
            generation_three["id"],
            scenario["prequalification_id"],
            ["GENERAL_BUILDING"],
        ),
        headers,
    )
    validate_error(third, ERR_CASCADE_DEPTH_EXCEEDED, 422)

    rows, meta = validate_paginated(
        api.list_links(
            build.admin_headers, {"prequalification_id": scenario["prequalification_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"the third tier must not have been recorded, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "the collection walks the hierarchy top-down, depth ascending"
    )
    assert [row["depth"] for row in rows] == [1, 2]


def test_grade_b_prequalification_is_refused_at_a_site_requiring_grade_a(build, api):
    """The last check in the ladder refuses a grade-B badge at a grade-A site.

    PRD Section 3.8: "The site's own `min_grade` sets a base rank, with `F` at 0,
    `C` at 1, `B` at 2 and `A` at 3."

    Design: Corner/errors/grade_b_prequalification_is_refused_at_a_site_requiring_grade_a
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    manager = scenario["manager_headers"]
    approved = scenario["prequalification"]
    assert_prequalification_state(approved, status="APPROVED", grade="B")
    assert_score_equals(approved["final_composite_score"], 80.51)

    # PLANT-C is the canonical PLANT-7 site on the default min_grade C; PLANT-A
    # demands rank 3 while the standing only carries rank 2.
    plant_a = build.create_site(
        scenario["client_id"],
        site_code="PLANT-A",
        required_hazard_classes=["GENERAL"],
        min_grade="A",
    )
    assert plant_a["min_grade"] == "A"
    assert_site_posture(
        validate_success(api.get_site(plant_a["id"], manager)),
        granted_worker_count=0,
        access_gate_status="OPEN",
    )

    refused = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            plant_a["id"],
            scenario["prequalification_id"],
            "2026-12-31T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(refused, ERR_GRADE_BELOW_SITE_MINIMUM, 422)
    assert_site_posture(
        validate_success(api.get_site(plant_a["id"], manager)), granted_worker_count=0
    )

    admitted = validate_success(
        api.create_grant(
            grant_payload(
                scenario["worker_id"],
                scenario["site_id"],
                scenario["prequalification_id"],
                "2026-12-31T00:00:00Z",
            ),
            scenario["contractor_headers"],
        ),
        201,
    )
    assert_grant_state(admitted, status="GRANTED")
    assert_site_posture(
        validate_success(api.get_site(scenario["site_id"], manager)),
        granted_worker_count=1,
    )


def test_request_missing_the_x_user_id_header_returns_unauthenticated(
    build, api, admin_headers
):
    """Priority 1 answers 401 for either missing header, ahead of path resolution.

    PRD Section 2.1: "If either header is absent, present but empty, or if
    `X-User-Role` is not exactly one of the four declared role names, the request
    is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_the_x_user_id_header_returns_unauthenticated
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()

    role_only = make_headers_without_user_id(ROLE_CONTRACTOR_ADMIN)
    validate_error(
        api.get_contractor(contractor["id"], role_only), ERR_UNAUTHENTICATED, 401
    )

    # The same request against an id that does not exist is still 401, never the
    # 404 that priority 5 would otherwise produce.
    validate_error(
        api.get_contractor(NON_EXISTENT_UUID, role_only), ERR_UNAUTHENTICATED, 401
    )

    id_only = make_headers_without_role(contractor["id"])
    validate_error(
        api.create_prequalification(
            prequalification_payload(
                contractor["id"], client["id"], contractor["version"], 2026
            ),
            id_only,
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    _rows, meta = validate_paginated(
        api.list_prequalifications(admin_headers, {"contractor_id": contractor["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the unauthenticated create must have written no row, got {meta['total_count']}"
    )
    assert_versioned_row(build.read_contractor(contractor["id"]), 1)
