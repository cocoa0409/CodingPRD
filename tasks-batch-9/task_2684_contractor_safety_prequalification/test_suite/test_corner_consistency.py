"""Corner section: consistency model.

Every derived value a write produces is already present in that write's own
response, and an immediate follow-up read returns the identical figures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (  # noqa: E402
    assert_exact_int,
    assert_prequalification_state,
    assert_rate_equals,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    program_payload,
    program_review_payload,
    statistic_payload,
)


def test_derived_fields_are_visible_in_the_same_response_that_writes_them(build, api):
    """No read-after-write lag: the write response and the next read agree exactly.

    PRD Section 3.3: "A new statistic is born at `verification_status` `PENDING`
    and immediately advances the parent prequalification's
    `statistics_verification_status`, the first of the two parallel review
    dimensions that live on the prequalification row."

    Design: Corner/consistency model/derived_fields_are_visible_in_the_same_response_that_writes_them
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    assert_prequalification_state(
        prequalification,
        statistics_verification_status="NOT_SUBMITTED",
        document_review_status="NOT_STARTED",
    )

    written = validate_success(
        api.create_statistic(
            prequalification["id"],
            statistic_payload(
                hours_worked=400000,
                recordable_incidents=4,
                dart_cases=2,
                emr=0.95,
                citation_count_willful=1,
                citation_count_serious=2,
                citation_count_other=3,
            ),
            headers,
        ),
        201,
    )
    # 5*1 + 2*2 + 1*3 = 12, 4 * 200000 / 400000 = 2.0000, 2 * 200000 / 400000 = 1.0000.
    assert_exact_int(written["citation_points"], 12)
    assert_rate_equals(written["trir"], 2.0000)
    assert_rate_equals(written["dart_rate"], 1.0000)

    rows, meta = validate_paginated(
        api.list_statistics(prequalification["id"], headers)
    )
    assert meta["total_count"] == 1
    read_back = rows[0]
    assert read_back["id"] == written["id"]
    assert_exact_int(read_back["citation_points"], 12)
    assert_rate_equals(read_back["trir"], 2.0000)
    assert_rate_equals(read_back["dart_rate"], 1.0000)
    assert read_back["citation_points"] == written["citation_points"], (
        "the immediate read must not drift from the creation response"
    )
    assert read_back["trir"] == written["trir"]
    assert read_back["dart_rate"] == written["dart_rate"]

    program = validate_success(
        api.create_program(
            prequalification["id"], program_payload("HAZCOM"), headers
        ),
        201,
    )
    assert program["review_status"] == "SUBMITTED"

    reviewed = validate_success(
        api.review_program(
            program["id"],
            program_review_payload("DEFICIENT", "Appendix B is missing"),
            build.manager_headers(client["id"]),
        )
    )
    assert reviewed["review_status"] == "DEFICIENT"

    # One immediate parent read carries both recomputed dimensions at once.
    parent = validate_success(
        api.get_prequalification(
            prequalification["id"], build.manager_headers(client["id"])
        )
    )
    assert_prequalification_state(
        parent,
        status="DRAFT",
        statistics_verification_status="PENDING",
        document_review_status="DEFICIENT",
    )
