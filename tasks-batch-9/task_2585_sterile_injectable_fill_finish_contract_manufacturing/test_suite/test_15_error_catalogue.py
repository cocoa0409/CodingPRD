"""Reachability of the twelve not-found codes, by path and by request body.

A single shared 404 would satisfy neither rung 5 nor rung 9 of PRD 2.10: ten
absent path identifiers must answer with ten different codes, and a foreign key
carried in a body — including an optional one — must be resolved before any
state rule runs.
"""
from __future__ import annotations

from typing import Any, Dict, List

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
)

Json = Dict[str, Any]

# Syntactically valid and present in no collection.
MISSING_ID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Design instance: every_path_id_resolves_or_returns_its_own_entity_not_found_code
# ---------------------------------------------------------------------------
def test_ten_collections_answer_the_same_absent_id_with_ten_distinct_codes(api):
    """One id, ten endpoints, ten different 404s — no shared not-found code.

    PRD 2.10: "**Path existence** — the resource-specific 404 for each path segment, resolved left to right, on every endpoint that has a path `id`."

    PRD 2.11: "Each resource type has its own not-found code: `ERR_CLIENT_PROJECT_NOT_FOUND`, `ERR_FILLING_SUITE_NOT_FOUND`, `ERR_MEDIA_FILL_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_BATCH_ORDER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_IN_PROCESS_CHECK_NOT_FOUND`, `ERR_EM_SAMPLE_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_BR_REVIEW_NOT_FOUND` and `ERR_AUDIT_ENGAGEMENT_NOT_FOUND`, all at HTTP 404."

    Design: Corner/errors/every_path_id_resolves_or_returns_its_own_entity_not_found_code
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    seen: List[str] = []
    seen.append(
        validate_error(
            api.get_client_project(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.CLIENT_PROJECT_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_media_fill(MISSING_ID, MICROBIOLOGY_ANALYST),
            ApiErrorId.MEDIA_FILL_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_qualification(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.QUALIFICATION_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_component_lot(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.COMPONENT_LOT_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_component_reservation(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.RESERVATION_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_in_process_check(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.IN_PROCESS_CHECK_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_em_sample(MISSING_ID, MICROBIOLOGY_ANALYST),
            ApiErrorId.EM_SAMPLE_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_deviation(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.DEVIATION_NOT_FOUND,
            404,
        )["error_id"]
    )
    seen.append(
        validate_error(
            api.get_batch_record_review(MISSING_ID, PROGRAM_MANAGER),
            ApiErrorId.BR_REVIEW_NOT_FOUND,
            404,
        )["error_id"]
    )
    engagement_error = validate_error(
        api.host_audit_engagement(
            MISSING_ID,
            factories.host_audit_payload(outcome="HOSTED", finding_count=1),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.AUDIT_ENGAGEMENT_NOT_FOUND,
        404,
    )
    assert engagement_error["error_id"] != ApiErrorId.CLIENT_PROJECT_NOT_FOUND
    seen.append(engagement_error["error_id"])

    assert len(seen) == 10
    assert len(set(seen)) == 10


# ---------------------------------------------------------------------------
# Design instance: body_foreign_keys_are_resolved_before_any_state_rule_not_found
# ---------------------------------------------------------------------------
def test_optional_body_foreign_keys_are_resolved_just_like_required_ones(api):
    """Five bodies, five entity-specific 404s, and not one row written.

    PRD 2.10: "**Body foreign-key existence** — the resource-specific 404, on `POST /client-projects`, `POST /media-fills`, `POST /personnel-qualifications`, `POST /batch-orders`, `POST /component-lots`, `POST /component-reservations`, `POST /in-process-checks`, `POST /em-samples`, `POST /deviations`, `POST /batch-record-reviews` and `POST /audit-engagements`."

    PRD 2.11: "The same codes are reused when a foreign key supplied in a request body fails to resolve. A `primary_suite_id` or `suite_id` that names no suite yields `ERR_FILLING_SUITE_NOT_FOUND`; a `client_project_id` that names no project yields `ERR_CLIENT_PROJECT_NOT_FOUND`; a `media_fill_id` yields `ERR_MEDIA_FILL_NOT_FOUND`; a `lead_operator_qualification_id` yields `ERR_QUALIFICATION_NOT_FOUND`; a `batch_order_id` yields `ERR_BATCH_ORDER_NOT_FOUND`; a `component_lot_id` yields `ERR_COMPONENT_LOT_NOT_FOUND`; and an `em_sample_id` yields `ERR_EM_SAMPLE_NOT_FOUND`."

    Design: Corner/errors/body_foreign_keys_are_resolved_before_any_state_rule_not_found
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    batch = fixtures.create_batch(
        api,
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
    )

    validate_error(
        api.create_em_sample(
            factories.em_sample_payload(MISSING_ID, sample_type="SURFACE", cfu_count=2),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.FILLING_SUITE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_qualification(
            factories.qualification_payload(
                "OP-E",
                program["suite_id"],
                qualification_type="GOWNING",
                media_fill_id=MISSING_ID,
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.MEDIA_FILL_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_component_lot(
            factories.component_lot_payload(
                MISSING_ID, lot_code="VL-9", quantity_received=1000
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.CLIENT_PROJECT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_in_process_check(
            factories.cci_check_payload(MISSING_ID), PRODUCTION_SUPERVISOR
        ),
        ApiErrorId.BATCH_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_deviation(
            factories.deviation_payload(
                batch["id"],
                summary="Excursion linked to a sample that does not exist.",
                em_sample_id=MISSING_ID,
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.EM_SAMPLE_NOT_FOUND,
        404,
    )

    samples, _meta = validate_paginated(
        api.list_em_samples(MICROBIOLOGY_ANALYST, {"suite_id": program["suite_id"]})
    )
    assert samples == []
    operators, _meta = validate_paginated(
        api.list_qualifications(MICROBIOLOGY_ANALYST, {"operator_name": "OP-E"})
    )
    assert operators == []
    lots, lots_meta = validate_paginated(api.list_component_lots(PROGRAM_MANAGER))
    assert lots == []
    assert lots_meta["total_count"] == 0
    checks, _meta = validate_paginated(
        api.list_in_process_checks(PROGRAM_MANAGER, {"batch_order_id": batch["id"]})
    )
    assert checks == []
    deviations, _meta = validate_paginated(
        api.list_deviations(PROGRAM_MANAGER, {"batch_order_id": batch["id"]})
    )
    assert deviations == []
