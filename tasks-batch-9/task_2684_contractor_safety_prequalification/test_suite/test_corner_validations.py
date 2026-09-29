"""Corner section: validations.

Uniqueness scopes, inclusive window edges, an aggregate cross-field rule and a
site-driven conditional check.
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
    ERR_DUPLICATE_REPORTING_YEAR,
    ERR_HAZARD_PROFILE_MISMATCH,
    ERR_INVALID_FIELD_VALUE,
    ERR_REPORTING_YEAR_OUT_OF_WINDOW,
)
from test_helpers.assertions import (  # noqa: E402
    assert_grant_state,
    assert_prequalification_state,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    client_payload,
    grant_payload,
    site_payload,
    statistic_payload,
)


def _draft_standing(build):
    """A client, a tier-1 contractor and one DRAFT 2026 prequalification."""
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    return {
        "client_id": client["id"],
        "contractor_id": contractor["id"],
        "prequalification_id": prequalification["id"],
        "headers": build.contractor_headers(contractor["id"]),
    }


def test_duplicate_reporting_year_on_a_pending_statistic_returns_duplicate_reporting_year(
    build, api
):
    """The year is claimed by a merely PENDING row, and a different year is free.

    PRD Section 3.3: "Lastly, no statistic may already exist on that
    prequalification for the same `reporting_year` while holding a
    `verification_status` of `PENDING` or `VERIFIED`; if one does, the request is
    `ERR_DUPLICATE_REPORTING_YEAR`."

    Design: Corner/validations/duplicate_reporting_year_on_a_pending_statistic_returns_duplicate_reporting_year
    """
    scenario = _draft_standing(build)
    first = build.file_statistic(
        scenario["prequalification_id"], scenario["contractor_id"]
    )
    assert first["reporting_year"] == 2025
    assert first["verification_status"] == "PENDING"

    # A different hours_worked proves the refusal is keyed on the year alone.
    duplicate = api.create_statistic(
        scenario["prequalification_id"],
        statistic_payload(hours_worked=610000, source_document_ref="OSHA300A-2025-DUP"),
        scenario["headers"],
    )
    validate_error(duplicate, ERR_DUPLICATE_REPORTING_YEAR, 409)

    other_year = validate_success(
        api.create_statistic(
            scenario["prequalification_id"],
            statistic_payload(
                reporting_year=2024, source_document_ref="OSHA300A-2024"
            ),
            scenario["headers"],
        ),
        201,
    )
    assert other_year["reporting_year"] == 2024

    rows, meta = validate_paginated(
        api.list_statistics(scenario["prequalification_id"], scenario["headers"])
    )
    assert meta["total_count"] == 2, (
        f"expected the 2025 and 2024 rows, got {meta['total_count']}"
    )
    assert sorted(row["reporting_year"] for row in rows) == [2024, 2025]
    for row in rows:
        assert row["verification_status"] == "PENDING"


def test_reporting_year_at_the_lower_window_edge_is_accepted(build, api):
    """The four-year window is inclusive at both ends: 2023 and 2026 pass, 2022 fails.

    PRD Section 3.3: "The reporting year must sit inside a four-year window that
    ends at the logical clock's own year: the clock's year, or any of the three
    years before it. Anything outside is `ERR_REPORTING_YEAR_OUT_OF_WINDOW`."

    Design: Corner/validations/reporting_year_at_the_lower_window_edge_is_accepted
    """
    scenario = _draft_standing(build)

    lower_edge = validate_success(
        api.create_statistic(
            scenario["prequalification_id"],
            statistic_payload(
                reporting_year=2023, source_document_ref="OSHA300A-2023"
            ),
            scenario["headers"],
        ),
        201,
    )
    assert lower_edge["reporting_year"] == 2023
    assert lower_edge["verification_status"] == "PENDING"

    outside = api.create_statistic(
        scenario["prequalification_id"],
        statistic_payload(reporting_year=2022, source_document_ref="OSHA300A-2022"),
        scenario["headers"],
    )
    validate_error(outside, ERR_REPORTING_YEAR_OUT_OF_WINDOW, 422)

    current_year = validate_success(
        api.create_statistic(
            scenario["prequalification_id"],
            statistic_payload(
                reporting_year=2026, source_document_ref="OSHA300A-2026"
            ),
            scenario["headers"],
        ),
        201,
    )
    assert current_year["reporting_year"] == 2026

    _rows, meta = validate_paginated(
        api.list_statistics(scenario["prequalification_id"], scenario["headers"])
    )
    assert meta["total_count"] == 2, (
        f"expected only the two accepted years to persist, got {meta['total_count']}"
    )


def test_client_weights_not_summing_to_one_are_rejected(build, api, admin_headers):
    """Each weight is individually legal; the collective sum is what fails.

    PRD Section 3.1: "Supplying a partial set that breaks that sum is refused with
    `ERR_INVALID_FIELD_VALUE`."

    Design: Corner/validations/client_weights_not_summing_to_one_are_rejected
    """
    build.set_clock(INITIAL_CLOCK)

    broken = api.create_client(
        client_payload(
            weight_trir=0.50,
            weight_dart=0.30,
            weight_emr=0.20,
            weight_citation=0.10,
        ),
        admin_headers,
    )
    validate_error(broken, ERR_INVALID_FIELD_VALUE, 422)

    accepted = validate_success(
        api.create_client(
            client_payload(
                weight_trir=0.50,
                weight_dart=0.20,
                weight_emr=0.20,
                weight_citation=0.10,
            ),
            admin_headers,
        ),
        201,
    )
    assert accepted["weight_trir"] == 0.50
    assert accepted["weight_dart"] == 0.20
    assert accepted["weight_emr"] == 0.20
    assert accepted["weight_citation"] == 0.10

    stored = validate_success(api.get_client(accepted["id"], admin_headers))
    assert stored["weight_trir"] == 0.50
    assert stored["weight_dart"] == 0.20
    assert stored["weight_emr"] == 0.20
    assert stored["weight_citation"] == 0.10


def test_site_requiring_heights_blocks_a_general_only_contractor_with_hazard_profile_mismatch(
    build, api
):
    """Priority 17 fires on the site's demand before the worker check at 18.

    PRD Section 3.8: "Every hazard class in the site's `required_hazard_classes`
    must appear in the contractor's `hazard_profile`, else
    `ERR_HAZARD_PROFILE_MISMATCH`; the contractor must be qualified for everything
    the site does, though it may be qualified for more."

    Design: Corner/validations/site_requiring_heights_blocks_a_general_only_contractor_with_hazard_profile_mismatch
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    plant_nine = validate_success(
        api.create_site(
            scenario["client_id"],
            site_payload(
                site_code="PLANT-9", required_hazard_classes=["GENERAL", "HEIGHTS"]
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert scenario["contractor"]["hazard_profile"] == ["GENERAL"]
    assert_prequalification_state(
        scenario["prequalification"], status="APPROVED", grade="B"
    )

    # Dana holds OSHA10 only, so priority 18 would also fail at PLANT-9.
    refused = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            plant_nine["id"],
            scenario["prequalification_id"],
            "2026-12-31T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(refused, ERR_HAZARD_PROFILE_MISMATCH, 422)
    assert_site_posture(
        validate_success(api.get_site(plant_nine["id"], scenario["manager_headers"])),
        granted_worker_count=0,
    )

    # The same worker and the same standing are grantable at the GENERAL-only site.
    grant = validate_success(
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
    assert_grant_state(grant, status="GRANTED")
    assert grant["qualification_snapshot"] == ["OSHA10"], (
        f"expected the frozen demand set ['OSHA10'], got {grant['qualification_snapshot']}"
    )
    assert_site_posture(
        validate_success(api.get_site(scenario["site_id"], scenario["manager_headers"])),
        granted_worker_count=1,
    )

