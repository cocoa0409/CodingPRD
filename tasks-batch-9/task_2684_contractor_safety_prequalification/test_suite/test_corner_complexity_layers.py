"""Corner section: cross-cutting complexity layers.

The two optimistic-concurrency guards, each pointed at a different parent row.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_STALE_VERSION  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_instant_equals,
    assert_prequalification_state,
    assert_score_equals,
    assert_versioned_row,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    improvement_plan_payload,
    prequalification_payload,
)


def test_prequalification_create_with_a_stale_expected_contractor_version_returns_412(
    build, api, admin_headers
):
    """The OCC field names the parent contractor, which the PATCH already advanced.

    PRD Section 2.8: "A request to `POST /prequalifications` must carry
    `expected_contractor_version`, holding the client's last observed `version` of
    the target `Contractor`."

    Design: Corner/cross-cutting complexity layers/prequalification_create_with_a_stale_expected_contractor_version_returns_412
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    assert_versioned_row(contractor, 1)
    observed = contractor["version"]

    patched = validate_success(
        api.patch_contractor(
            contractor["id"], {"hazard_profile": ["GENERAL", "HEIGHTS"]}, admin_headers
        )
    )
    assert_versioned_row(patched, 2)
    assert_contractor_posture(patched, base_hazard_tier=2)

    stale = api.create_prequalification(
        prequalification_payload(contractor["id"], client["id"], observed, 2026),
        build.contractor_headers(contractor["id"]),
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    _rows, meta = validate_paginated(
        api.list_prequalifications(admin_headers, {"contractor_id": contractor["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the stale create must have written no row, got {meta['total_count']}"
    )
    # A rejected optimistic-concurrency write bumps nothing.
    assert_versioned_row(build.read_contractor(contractor["id"]), 2)

    accepted = validate_success(
        api.create_prequalification(
            prequalification_payload(contractor["id"], client["id"], 2, 2026),
            build.contractor_headers(contractor["id"]),
        ),
        201,
    )
    assert_prequalification_state(accepted, status="DRAFT")

    rows, meta = validate_paginated(
        api.list_prequalifications(admin_headers, {"contractor_id": contractor["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


def test_improvement_plan_create_with_a_stale_expected_prequalification_version_returns_412(
    build, api
):
    """The first plan bumps the row, so the version observed at grading is already stale.

    PRD Section 2.8: "A request to `POST /prequalifications/{id}/improvement-plans`
    must carry `expected_prequalification_version`, holding the manager's last
    observed `version` of the target `Prequalification`."

    Design: Corner/cross-cutting complexity layers/improvement_plan_create_with_a_stale_expected_prequalification_version_returns_412
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides={"emr": 1.01})
    pq_id = scenario["prequalification_id"]
    manager = scenario["manager_headers"]
    graded = scenario["prequalification"]

    # 77.89 still lands in the BALANCED B band; the EMR soft breach is what makes
    # the standing conditional.
    assert_prequalification_state(
        graded, status="CONDITIONAL", grade="B", deficiency_codes=["EMR"]
    )
    assert_score_equals(graded["final_composite_score"], 77.89)
    assert_instant_equals(graded["conditional_expires_at"], "2026-10-30T00:00:00Z")
    observed = graded["version"]

    first = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=observed,
                due_date="2026-10-01T00:00:00Z",
                milestone_count=3,
            ),
            manager,
        ),
        201,
    )
    assert first["status"] == "OPEN"

    replayed = api.create_improvement_plan(
        pq_id,
        improvement_plan_payload(
            expected_prequalification_version=observed,
            due_date="2026-10-15T00:00:00Z",
            milestone_count=5,
        ),
        manager,
    )
    validate_error(replayed, ERR_STALE_VERSION, 412)

    rows, meta = validate_paginated(api.list_improvement_plans(pq_id, manager))
    assert meta["total_count"] == 1, (
        f"the refused create must have superseded nothing, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "OPEN", (
        f"the live plan must survive the 412, got {rows[0]['status']}"
    )

    fresh = build.read_prequalification(pq_id)["version"]
    assert fresh != observed, "the first plan create must have advanced the row"
    second = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=fresh,
                due_date="2026-10-15T00:00:00Z",
                milestone_count=5,
            ),
            manager,
        ),
        201,
    )
    assert second["status"] == "OPEN"
    assert second["deficiency_codes"] == ["EMR"]
    assert second["milestone_count"] == 5

    rows, meta = validate_paginated(api.list_improvement_plans(pq_id, manager))
    assert meta["total_count"] == 2
    superseded = [row for row in rows if row["id"] == first["id"]][0]
    assert superseded["status"] == "REJECTED", (
        f"the accepted create supersedes the live plan, got {superseded['status']}"
    )
    assert_instant_equals(superseded["closed_at"], INITIAL_CLOCK)

    assert_prequalification_state(
        build.read_prequalification(pq_id),
        status="CONDITIONAL",
        grade="B",
        deficiency_codes=["EMR"],
    )
