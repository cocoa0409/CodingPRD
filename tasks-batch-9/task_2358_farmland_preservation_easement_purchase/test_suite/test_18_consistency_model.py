"""Consistency: the longest cascade is already visible in its own response.

Acceptance touches the negotiation log, every commitment, every parent source and
a freshly created requirement set. Nothing about it is deferred to a sweep or to a
second write, so the acceptance body and the child reads taken straight afterwards
must agree.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    CLOCK_2026_10_12,
    TEST_USERS,
    api_client,
    make_landowner_headers,
    set_clock,
    setup_funded_application,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestAcceptanceIsImmediatelyConsistent:
    """One write, then four reads that add nothing new."""

    def test_the_acceptance_body_already_carries_every_cascaded_change(self):
        """The response, then the commitments, the source, the file and the log.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/the_acceptance_response_itself_already_shows_every_cascaded_change
        """
        scenario = setup_funded_application()
        application_id = scenario["application"]["id"]
        local_id = scenario["sources"]["local"]["id"]
        landowner = make_landowner_headers(scenario["landowner"]["id"])
        set_clock(CLOCK_2026_10_12)

        accepted = validate_success(
            api_client.accept_application(application_id, landowner)
        )
        # Every one of these is written by the acceptance cascade itself.
        assert accepted["status"] == "ACCEPTED"
        assert accepted["agreed_price_cents"] == 175_550_000
        assert accepted["funding_plan_status"] == "OBLIGATED"
        assert accepted["closing_status"] == "PENDING_REQUIREMENTS"
        assert accepted["requirement_total"] == 3
        assert accepted["requirement_satisfied_count"] == 0

        commitments, commitment_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id}
            )
        )
        assert commitment_meta["total_count"] == 3
        assert {row["status"] for row in commitments} == {"OBLIGATED"}

        local = validate_success(api_client.get_funding_source(local_id, ADMIN))
        assert local["committed_cents"] == 56_127_723
        # 60,000,000 authorised less the committed take; reservations are not
        # netted out.
        assert local["available_cents"] == 3_872_277
        assert local["version"] > 1

        requirements, requirement_meta = validate_paginated(
            api_client.list_closing_requirements(application_id, ADMIN)
        )
        assert requirement_meta["total_count"] == 3
        assert {row["requirement_type"] for row in requirements} == {
            "TITLE_COMMITMENT",
            "MORTGAGE_SUBORDINATION",
            "BOUNDARY_SURVEY",
        }
        assert {row["status"] for row in requirements} == {"OUTSTANDING"}

        log, log_meta = validate_paginated(
            api_client.list_negotiation_rounds(
                application_id, ADMIN, {"kind": "ACCEPTANCE"}
            )
        )
        assert log_meta["total_count"] == 1
        assert log[0]["amount_cents"] == 175_550_000
