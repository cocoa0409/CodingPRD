"""Breadth probes: RBAC denials, endpoint side effects / listing, optimistic
concurrency, and immediate consistency.

Covers Corner sections `rbac`, `endpoints`, `cross_cutting`, and
`consistency_model`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_owner_headers,
    create_animal,
    create_bite_case,
    create_region,
    create_pep,
    issue_quarantine_order,
    issue_citation,
    setup_citation_issued,
    refetch_owner,
    refetch_region,
    refetch_case,
    refetch_animal,
    set_clock,
)


# ---- rbac ----

def test_intake_officer_cannot_issue_quarantine_order(api, intake_officer_headers):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/intake_officer_cannot_issue_quarantine_order_unauthorized
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case = create_bite_case(region_code="RB-C11", wound_category="CATEGORY_II",
                            body_site="ARM", animal_id=animal["id"])
    resp = api.create_quarantine_order(case["id"], {
        "expected_bite_case_version": case["version"],
        "animal_id": animal["id"],
        "order_type": "HOME_CONFINEMENT",
        "start_date": "2026-03-01T00:00:00Z"}, intake_officer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_owner_cannot_resolve_citation(api, epidemiologist_headers):
    """PRD §2.1: "A deliberate segregation of duties keeps citation **issuance**
    (an `AnimalControlOfficer` capability) separate from citation-hearing
    **resolution** (an `Epidemiologist` capability), so the same person cannot
    both write and adjudicate a fine."

    Design: Corner/rbac/owner_cannot_resolve_citation_unauthorized
    """
    state = setup_citation_issued(violations=("UNLICENSED_ANIMAL",), region_code="RB-C12")
    owner_headers = make_owner_headers(state["owner"]["id"])
    validate_success(api.contest_citation(state["citation"]["id"], {}, owner_headers), 200)
    resp = api.resolve_citation(state["citation"]["id"], {"resolution": "DISMISSED"}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` that is not one of the recognized roles, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    resp = api.get_owner(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---- endpoints ----

def test_wildlife_report_increments_region_wildlife_count(api, intake_officer_headers):
    """PRD §3.8: "Filing a report increases the region's `wildlife_exposure_count`
    by one."

    Design: Corner/endpoints/wildlife_report_increments_region_wildlife_count
    """
    region = create_region("RB-WL", positive_threshold=3)
    report = validate_success(api.create_wildlife_report(region["id"], {
        "species": "BAT", "exposure_datetime": "2026-03-01T20:00:00Z",
        "exposure_type": "INDOOR_FOUND_BAT"}, intake_officer_headers), 201)
    assert report["region_id"] == region["id"]
    assert refetch_region(region["id"])["wildlife_exposure_count"] == 1


def test_citation_contest_then_uphold_keeps_owner_delinquent(api, epidemiologist_headers):
    """PRD §3.7: "`UPHELD` moves the citation from `CONTESTED` to `UPHELD` and
    leaves it owed, while `DISMISSED` moves it from `CONTESTED` to the terminal
    `DISMISSED` and reduces the owner's `outstanding_fines_cents` by that
    citation's `total_fine_cents`, recomputing `compliance_status`."

    Design: Corner/endpoints/citation_contest_then_uphold_keeps_owner_delinquent
    """
    state = setup_citation_issued(violations=("QUARANTINE_BREACH",), region_code="RB-C13")
    owner_headers = make_owner_headers(state["owner"]["id"])
    validate_success(api.contest_citation(state["citation"]["id"], {}, owner_headers), 200)
    upheld = validate_success(api.resolve_citation(
        state["citation"]["id"], {"resolution": "UPHELD"}, epidemiologist_headers), 200)
    assert upheld["status"] == "UPHELD"
    owner = refetch_owner(state["owner"]["id"])
    assert owner["outstanding_fines_cents"] == 54250
    assert owner["compliance_status"] == "DELINQUENT"


def test_list_bite_cases_returns_paginated_array_envelope(api, epidemiologist_headers):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`,
    and `has_more` inside the envelope's `meta` object."

    Design: Corner/endpoints/list_bite_cases_returns_paginated_array_envelope
    """
    create_bite_case(region_code="RB-C14", wound_category="CATEGORY_II")
    data, meta = validate_paginated(api.list_bite_cases(epidemiologist_headers))
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta


# ---- cross_cutting: optimistic concurrency ----

def test_pep_recommendation_stale_case_version_rejected(api, epidemiologist_headers):
    """PRD §2.6: "When the submitted `expected_bite_case_version` does not equal
    the target case's current `version`, the request is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/pep_recommendation_stale_case_version_rejected
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="EXPIRED")
    case = create_bite_case(region_code="RB-C15", wound_category="CATEGORY_II",
                            body_site="ARM", animal_id=animal["id"])
    stale_version = case["version"]
    create_pep(case["id"], case["version"])  # advances the case version
    resp = api.create_pep_recommendation(
        case["id"], {"expected_bite_case_version": stale_version}, epidemiologist_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


def test_quarantine_order_stale_case_version_rejected(api, veterinarian_headers):
    """PRD §2.6: "When the submitted `expected_bite_case_version` does not equal
    the target case's current `version`, the request is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/quarantine_order_stale_case_version_rejected
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case = create_bite_case(region_code="RB-C16", wound_category="CATEGORY_II",
                            animal_id=animal["id"])
    stale_version = case["version"]
    set_clock("2026-03-01T00:00:00Z")
    issue_quarantine_order(case["id"], case["version"], animal["id"],
                           order_type="HOME_CONFINEMENT", start_date="2026-03-01T00:00:00Z")
    resp = api.create_quarantine_order(case["id"], {
        "expected_bite_case_version": stale_version,
        "animal_id": animal["id"],
        "order_type": "HOME_CONFINEMENT",
        "start_date": "2026-03-20T00:00:00Z"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


# ---- consistency_model: immediate ----

def test_quarantine_issue_immediately_flips_case_and_animal(api, veterinarian_headers):
    """PRD §3.3: "A successful issuance creates the `QuarantineOrder` in status
    `ACTIVE`, ... moves the referenced animal from `REPORTED` or `CAPTURED` to
    `UNDER_OBSERVATION`, moves the bite case from `OPEN` to `OBSERVATION_PENDING`,
    and increments the bite case's `version` by one."

    Design: Corner/consistency_model/quarantine_issue_immediately_flips_case_and_animal
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case = create_bite_case(region_code="RB-C17", wound_category="CATEGORY_II",
                            body_site="LEG", animal_id=animal["id"])
    set_clock("2026-03-01T00:00:00Z")
    order = validate_success(api.create_quarantine_order(case["id"], {
        "expected_bite_case_version": case["version"],
        "animal_id": animal["id"],
        "order_type": "HOME_CONFINEMENT",
        "start_date": "2026-03-01T00:00:00Z"}, veterinarian_headers), 201)
    assert order["status"] == "ACTIVE"
    assert refetch_case(case["id"])["status"] == "OBSERVATION_PENDING"
    assert refetch_animal(animal["id"])["status"] == "UNDER_OBSERVATION"
