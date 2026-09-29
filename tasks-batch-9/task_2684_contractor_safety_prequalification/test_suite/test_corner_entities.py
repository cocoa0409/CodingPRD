"""Corner section: entities.

Creation defaults, single-resource reads, paging, not-found codes, undeclared
computed and system fields, and the two immutable append-only entities.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_CLIENT_NOT_FOUND,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_INVALID_FIELD_VALUE,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_immutable_row,
    assert_instant_equals,
    assert_pagination_meta,
    assert_prequalification_state,
    assert_site_posture,
    assert_versioned_row,
)
from test_helpers.constants import (  # noqa: E402
    ALTERNATE_INDUSTRY_CODE,
    CANONICAL_CLIENT_NAME,
    CANONICAL_CONTRACTOR_NAME,
    CANONICAL_SITE_CODE,
    CLIENT_DEFAULTS,
    DEFAULT_SITE_MIN_GRADE,
    INITIAL_CLOCK,
)
from test_helpers.factories import (  # noqa: E402
    client_payload,
    contractor_payload,
    program_payload,
    qualification_payload,
    site_payload,
)


def test_contractor_creation_returns_201_with_computed_tier_and_active_status(
    build, api, admin_headers
):
    """One minimal body, every declared field materialized.

    PRD Section 3.1: "Registration fixes several derived fields: the contractor
    begins at `version` 1 with `status` `ACTIVE`, `incident_review_flag` false,
    `open_severe_incident_count` 0, `open_deficiency_count` 0, and an empty
    `verified_coverage_types` array."

    Design: Corner/entities/contractor_creation_returns_201_with_computed_tier_and_active_status
    """
    build.set_clock(INITIAL_CLOCK)

    response = api.create_contractor(contractor_payload(), admin_headers)
    data = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )

    assert data["legal_name"] == CANONICAL_CONTRACTOR_NAME
    assert data["scope_of_work"] == ["MECHANICAL_TRADE"]
    assert data["hazard_profile"] == ["GENERAL"]
    assert data["employee_count"] == 40

    assert_contractor_posture(
        data,
        status="ACTIVE",
        base_hazard_tier=1,
        incident_review_flag=False,
        open_severe_incident_count=0,
        open_deficiency_count=0,
        verified_coverage_types=[],
    )
    assert_versioned_row(data, 1)
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert "_" not in data["id"], f"id must carry no type prefix, got {data['id']!r}"


def test_get_site_by_id_returns_the_stored_row_with_defaults(build, api, admin_headers):
    """The read returns exactly what creation stored, with no drift.

    PRD Section 3.1: "An optional `min_grade`, one of `A`, `B` or `C` and
    defaulting to `C`, is the lowest prequalification grade the client will admit
    at that site. A new site begins with `granted_worker_count` at 0 and
    `access_gate_status` at `OPEN`."

    Design: Corner/entities/get_site_by_id_returns_the_stored_row_with_defaults
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    created = validate_success(
        api.create_site(
            client["id"],
            site_payload(required_hazard_classes=["GENERAL"]),
            build.manager_headers(client["id"]),
        ),
        201,
    )

    site = validate_success(api.get_site(created["id"], admin_headers))
    assert site["id"] == created["id"]
    assert site["client_id"] == client["id"]
    assert site["site_code"] == CANONICAL_SITE_CODE
    assert site["required_hazard_classes"] == ["GENERAL"]
    assert site["min_grade"] == DEFAULT_SITE_MIN_GRADE
    assert_site_posture(site, granted_worker_count=0, access_gate_status="OPEN")
    assert_versioned_row(site, 1)


def test_prequalification_list_paginates_with_total_count_and_has_more(
    build, api, admin_headers
):
    """Three rows for one client, paged with limit 2 and filtered before the window.

    PRD Section 2.3: "`total_count` is the number of rows matching the request's
    filters before the page window is applied, and `has_more` is true exactly
    when rows remain beyond the current window."

    Design: Corner/entities/prequalification_list_paginates_with_total_count_and_has_more
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    other_client = build.create_client(
        legal_name="Southgate Industrial", industry_code=ALTERNATE_INDUSTRY_CODE
    )

    wanted = []
    for legal_name, trade in (
        ("Acme Mechanical", "MECHANICAL_TRADE"),
        ("Bolt Rigging", "SCAFFOLDING"),
        ("Cable Crew", "ELECTRICAL_TRADE"),
    ):
        contractor = build.create_contractor(
            legal_name=legal_name, scope_of_work=[trade], hazard_profile=["GENERAL"]
        )
        wanted.append(
            build.open_prequalification(contractor["id"], client["id"])["id"]
        )

    outsider = build.create_contractor(
        legal_name="Deep Foundations", scope_of_work=["EARTHWORK"], hazard_profile=["GENERAL"]
    )
    unwanted = build.open_prequalification(outsider["id"], other_client["id"])["id"]

    first_response = api.list_prequalifications(
        admin_headers, {"client_id": client["id"], "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2, f"expected a full page of 2, got {len(first_rows)}"
    assert_pagination_meta(
        first_meta,
        expected_total=3,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )

    second_rows, second_meta = validate_paginated(
        api.list_prequalifications(
            admin_headers, {"client_id": client["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1
    assert_pagination_meta(
        second_meta, expected_total=3, expected_offset=2, expected_has_more=False
    )

    seen = [row["id"] for row in first_rows + second_rows]
    assert set(seen) == set(wanted), f"expected the three Northwind rows, got {seen}"
    assert unwanted not in seen, "the other client's row leaked into the filtered pages"
    for row in first_rows + second_rows:
        assert_prequalification_state(
            row,
            status="DRAFT",
            statistics_verification_status="NOT_SUBMITTED",
            audit_state="NOT_SELECTED",
        )


def test_get_contractor_with_unknown_id_returns_not_found(build, api, admin_headers):
    """An unknown UUID gets the contractor's own 404 code, not the generic one.

    PRD Section 2.6: "Each segment has its own not-found code: an unresolvable
    client segment yields `ERR_CLIENT_NOT_FOUND`, a contractor segment
    `ERR_CONTRACTOR_NOT_FOUND`, a prequalification segment
    `ERR_PREQUALIFICATION_NOT_FOUND`, a site segment `ERR_SITE_NOT_FOUND`, a
    worker segment `ERR_WORKER_NOT_FOUND`, an insurance-certificate segment
    `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`, and an improvement-plan segment
    `ERR_IMPROVEMENT_PLAN_NOT_FOUND`."

    Design: Corner/entities/get_contractor_with_unknown_id_returns_not_found
    """
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()

    response = api.get_contractor(NON_EXISTENT_UUID, admin_headers)
    validate_error(response, ERR_CONTRACTOR_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"

    intact = validate_success(api.get_contractor(contractor["id"], admin_headers))
    assert intact["id"] == contractor["id"], "the real row must still resolve"


def test_create_contractor_missing_required_hazard_profile_returns_invalid_request(
    build, api, admin_headers
):
    """An omitted required field is a 400 body-schema failure, not a 422.

    PRD Section 2.9: "Request-shape validation on every creating or amending
    write: every required input field present, every field of the declared JSON
    type, and no undeclared field present — `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_contractor_missing_required_hazard_profile_returns_invalid_request
    """
    build.set_clock(INITIAL_CLOCK)

    payload = contractor_payload()
    del payload["hazard_profile"]
    response = api.create_contractor(payload, admin_headers)
    validate_error(response, ERR_INVALID_REQUEST, 400)

    # No row was created, so the unique legal name is still free.
    accepted = validate_success(
        api.create_contractor(contractor_payload(), admin_headers), 201
    )
    assert accepted["legal_name"] == CANONICAL_CONTRACTOR_NAME
    assert accepted["hazard_profile"] == ["GENERAL"], (
        "the omitted array must not have been defaulted on the refused call"
    )


def test_client_creation_omitting_optional_fields_applies_declared_defaults(
    build, api, admin_headers
):
    """Fourteen optional dials all materialize their published defaults.

    PRD Section 3.1: "Four composite weights are published alongside them:
    `weight_trir` defaults to 0.40, `weight_dart` to 0.25, `weight_emr` to 0.25
    and `weight_citation` to 0.10; each must be greater than 0 and at most 1,
    carried to two decimal places, and the four together must sum to exactly
    1.00."

    Design: Corner/entities/client_creation_omitting_optional_fields_applies_declared_defaults
    """
    build.set_clock(INITIAL_CLOCK)

    data = validate_success(api.create_client(client_payload(), admin_headers), 201)
    assert data["legal_name"] == CANONICAL_CLIENT_NAME

    for field, expected in CLIENT_DEFAULTS.items():
        assert data[field] == expected, (
            f"expected default {field} == {expected}, got {data[field]}"
        )

    weight_sum = (
        data["weight_trir"]
        + data["weight_dart"]
        + data["weight_emr"]
        + data["weight_citation"]
    )
    assert round(weight_sum, 2) == 1.00, f"the four weights must sum to 1.00, got {weight_sum}"
    assert_versioned_row(data, 1)


def test_create_contractor_supplying_computed_base_hazard_tier_returns_invalid_request(
    build, api, admin_headers
):
    """The tier cannot be pinned by the caller; the server derives it from HEIGHTS.

    PRD Section 3.1: "Its `base_hazard_tier` is set to 2 when the declared
    `hazard_profile` includes at least one of the five high-hazard classes —
    `HEIGHTS`, `CONFINED_SPACE`, `ELECTRICAL`, `HOT_WORK` or `EXCAVATION` — and
    to 1 otherwise; a contractor whose profile is only `GENERAL` is a tier-1
    contractor."

    Design: Corner/entities/create_contractor_supplying_computed_base_hazard_tier_returns_invalid_request
    """
    build.set_clock(INITIAL_CLOCK)

    pinned = contractor_payload(
        legal_name="Summit Steel Erectors",
        scope_of_work=["GENERAL_BUILDING"],
        hazard_profile=["GENERAL", "HEIGHTS"],
        employee_count=120,
        base_hazard_tier=1,
    )
    validate_error(api.create_contractor(pinned, admin_headers), ERR_INVALID_REQUEST, 400)

    clean = contractor_payload(
        legal_name="Summit Steel Erectors",
        scope_of_work=["GENERAL_BUILDING"],
        hazard_profile=["GENERAL", "HEIGHTS"],
        employee_count=120,
    )
    created = validate_success(api.create_contractor(clean, admin_headers), 201)
    assert_contractor_posture(created, base_hazard_tier=2)

    reread = validate_success(api.get_contractor(created["id"], admin_headers))
    assert_contractor_posture(reread, base_hazard_tier=2)
    assert_versioned_row(reread, 1)


def test_create_prequalification_supplying_status_returns_invalid_request(build, api):
    """A system field in the body is refused; the accepted create seeds all four.

    PRD Section 3.2: "A new row begins at `DRAFT`, with
    `statistics_verification_status` at `NOT_SUBMITTED`, `document_review_status`
    at `NOT_STARTED` and `audit_state` at `NOT_SELECTED`."

    Design: Corner/entities/create_prequalification_supplying_status_returns_invalid_request
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])

    pinned = {
        "contractor_id": contractor["id"],
        "client_id": client["id"],
        "cycle_year": 2026,
        "expected_contractor_version": contractor["version"],
        "status": "APPROVED",
    }
    validate_error(api.create_prequalification(pinned, headers), ERR_INVALID_REQUEST, 400)

    accepted = validate_success(
        api.create_prequalification(
            {
                "contractor_id": contractor["id"],
                "client_id": client["id"],
                "cycle_year": 2026,
                "expected_contractor_version": contractor["version"],
            },
            headers,
        ),
        201,
    )
    assert_prequalification_state(
        accepted,
        status="DRAFT",
        statistics_verification_status="NOT_SUBMITTED",
        document_review_status="NOT_STARTED",
        audit_state="NOT_SELECTED",
        grade=None,
        deficiency_codes=[],
        final_composite_score=None,
        provisional_composite_score=None,
    )
    for field in ("effective_thresholds", "graded_at", "expires_at", "conditional_expires_at"):
        assert accepted[field] is None, f"expected {field} to begin null, got {accepted[field]!r}"

    # The accepted create advanced the contractor's own version by exactly 1.
    assert_versioned_row(build.read_contractor(contractor["id"]), contractor["version"] + 1)


def test_written_program_with_out_of_enum_program_type_is_rejected(build, api):
    """Enum membership and a future revision date are both 422 field-value failures.

    PRD Section 3.4: "Only one row per program type may exist on a
    prequalification; tendering a second document of a type already present is
    refused with `ERR_INVALID_FIELD_VALUE`, and a future-dated `revision_date` is
    refused with the same code."

    Design: Corner/entities/written_program_with_out_of_enum_program_type_is_rejected
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    out_of_enum = api.create_program(
        prequalification["id"],
        program_payload("SAFETY_CULTURE", document_ref="DOC-X-1"),
        headers,
    )
    validate_error(out_of_enum, ERR_INVALID_FIELD_VALUE, 422)

    future_dated = api.create_program(
        prequalification["id"],
        program_payload("HAZCOM", revision_date="2026-09-01T00:00:00Z"),
        headers,
    )
    validate_error(future_dated, ERR_INVALID_FIELD_VALUE, 422)

    rows, meta = validate_paginated(api.list_programs(prequalification["id"], headers))
    assert meta["total_count"] == 0, (
        f"expected no written-program rows after two refusals, got {meta['total_count']}"
    )
    assert rows == []
    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        document_review_status="NOT_STARTED",
    )


def test_worker_qualification_rows_carry_no_version_and_have_no_update_endpoint(
    build, api, admin_headers
):
    """Both immutable entities expose only id and created_at, and renewal appends.

    PRD Section 2.4: "A `Worker` row and a `WorkerQualification` row each expose
    only `id` and `created_at`: `updated_at` and `version` are absent from both,
    and no endpoint mutates either row."

    Design: Corner/entities/worker_qualification_rows_carry_no_version_and_have_no_update_endpoint
    """
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])

    worker = validate_success(
        api.create_worker(contractor["id"], {
            "full_name": "Dana Ruiz",
            "employee_ref": "EMP-1001",
            "trade_code": "MECHANICAL_TRADE",
        }, headers),
        201,
    )
    assert_immutable_row(worker)

    qualification = validate_success(
        api.create_qualification(worker["id"], qualification_payload(), headers), 201
    )
    assert_immutable_row(qualification)
    assert_instant_equals(qualification["created_at"], INITIAL_CLOCK)

    assert_immutable_row(validate_success(api.get_worker(worker["id"], admin_headers)))

    rows, meta = validate_paginated(api.list_qualifications(worker["id"], admin_headers))
    assert meta["total_count"] == 1
    assert rows[0]["qualification_code"] == "OSHA10"
    assert_instant_equals(rows[0]["expiration_date"], "2029-01-15T00:00:00Z")

    # Renewal is expressed by appending, never by replacing.
    validate_success(
        api.create_qualification(
            worker["id"],
            qualification_payload(
                qualification_code="OSHA30", evidence_ref="CERT-OSHA30-1001"
            ),
            headers,
        ),
        201,
    )
    _rows, meta = validate_paginated(api.list_qualifications(worker["id"], admin_headers))
    assert meta["total_count"] == 2, (
        f"expected two coexisting qualification rows, got {meta['total_count']}"
    )


def test_create_site_under_unknown_client_returns_not_found(build, api, admin_headers):
    """The path segment is resolved at priority 5, ahead of the ownership check.

    PRD Section 2.9: "Path-parameter resolution, left to right, on every endpoint
    that has path parameters — the dedicated 404 code of the leftmost failing
    segment, per Section 2.6."

    Design: Corner/entities/create_site_under_unknown_client_returns_not_found
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    assert client["legal_name"] == CANONICAL_CLIENT_NAME

    response = api.create_site(
        NON_EXISTENT_UUID, site_payload(), build.manager_headers(NON_EXISTENT_UUID)
    )
    validate_error(response, ERR_CLIENT_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_client_sites(client["id"], admin_headers)
    )
    assert meta["total_count"] == 0, (
        f"expected the real client to hold no sites, got {meta['total_count']}"
    )
    assert rows == []
