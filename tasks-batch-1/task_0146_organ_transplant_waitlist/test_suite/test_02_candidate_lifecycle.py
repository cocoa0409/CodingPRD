"""Candidate registration, the two status dimensions, listing preconditions,
removal, and waiting-time accrual conservation.

Translates difficulty instances nlsm_candidate_parallel_medical_listing_dimensions
and ci_waiting_time_conserved_across_deactivate_reactivate, plus corner instances
for creation defaults, not-found, required/enum/duplicate validation, listing
pagination, the no-finalized-score and draft-remove preconditions.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_candidate,
    set_clock, create_center, create_candidate, create_finalized_score,
    create_listed_candidate,
    create_candidate_payload, remove_candidate_payload, create_clinical_score_payload,
    make_center_headers,
)


def test_create_candidate_returns_201_with_defaults(api):
    """PRD §3.2: "A candidate carries two independent status dimensions ... The
    first, listing_status ... a new candidate begins in DRAFT. The second,
    medical_status ... a new candidate begins ACTIVE." PRD §3.2: "The field
    current_meld_peld holds the candidate's latest finalized allocation score and
    is 0 until the first clinical score is finalized." PRD §2.4: "version — a
    system-managed integer that begins at its initial value and increments by one
    with every mutation of the resource."

    Design: Corner/entities/corner_create_candidate_returns_201_defaults
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    res = api.create_candidate(
        create_candidate_payload(center["id"], mrn="N1", organ_type="KIDNEY",
                                 blood_type="B", date_of_birth="1990-01-01T00:00:00Z",
                                 height_cm=170, weight_kg=70),
        headers)
    cand = validate_success(res, 201)
    assert_candidate(cand)
    assert cand["listing_status"] == "DRAFT"
    assert cand["medical_status"] == "ACTIVE"
    assert cand["current_meld_peld"] == 0
    assert cand["version"] == 1


def test_get_nonexistent_candidate_returns_404(api, admin_headers):
    """PRD §2.6: "the system validates referenced resources left-to-right and
    rejects the request with ERR_NOT_FOUND at the first identifier that does not
    resolve to an existing resource."

    Design: Corner/entities/corner_candidate_not_found_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_candidate("00000000-0000-4000-8000-000000000000", admin_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_candidate_missing_blood_type_rejected(api):
    """PRD §2.8: "Request shape — required body fields are present and well-typed,
    enums are in range, arrays have the correct length, and numbers are positive,
    else ERR_INVALID_REQUEST."

    Design: Corner/entities/corner_create_candidate_missing_required_field_422
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    payload = create_candidate_payload(center["id"], mrn="N2", organ_type="KIDNEY",
                                       date_of_birth="1990-01-01T00:00:00Z",
                                       height_cm=170, weight_kg=70)
    del payload["blood_type"]
    res = api.create_candidate(payload, headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_candidate_invalid_organ_type_enum_rejected(api):
    """PRD §3.2: "the organ_type sought (one of LIVER, KIDNEY, HEART, or LUNG)."
    PRD §2.8: "enums are in range ... else ERR_INVALID_REQUEST."

    Design: Corner/entities/corner_create_candidate_invalid_enum_422
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    payload = create_candidate_payload(center["id"], mrn="N3", organ_type="PANCREAS",
                                       blood_type="O", date_of_birth="1990-01-01T00:00:00Z",
                                       height_cm=170, weight_kg=70)
    res = api.create_candidate(payload, headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_center_mrn_rejected(api):
    """PRD §3.2: "The pair (center_id, mrn) must be unique — a second candidate
    with the same medical record number at the same center is rejected with
    ERR_DUPLICATE_RESOURCE."

    Design: Corner/entities/corner_candidate_duplicate_mrn_409
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    create_candidate(center, mrn="DUP", organ_type="KIDNEY", blood_type="O",
                     date_of_birth="1990-01-01T00:00:00Z", height_cm=170, weight_kg=70)
    res = api.create_candidate(
        create_candidate_payload(center["id"], mrn="DUP", organ_type="KIDNEY",
                                 blood_type="A", date_of_birth="1991-01-01T00:00:00Z",
                                 height_cm=171, weight_kg=71),
        headers)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_candidate_listing_is_paginated_array(api, admin_headers):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/corner_candidate_listing_paginated_envelope
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    create_candidate(center, mrn="L1", organ_type="KIDNEY", blood_type="O",
                     date_of_birth="1990-01-01T00:00:00Z", height_cm=170, weight_kg=70)
    res = api.list_candidates(admin_headers, params={"center_id": center["id"],
                                                     "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_candidate_without_finalized_score_rejected(api):
    """PRD §3.4: "The transition is permitted only when the candidate has at least
    one FINALIZED clinical score — equivalently, when current_meld_peld is greater
    than 0 — otherwise the request is rejected with ERR_NO_FINALIZED_SCORE."

    Design: Corner/state_machines/corner_list_candidate_without_finalized_score_blocked
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_candidate(center, mrn="S2", date_of_birth="1980-01-01T00:00:00Z")
    # Create a DRAFT (un-finalized) score only.
    validate_success(api.create_clinical_score(
        cand["id"], create_clinical_score_payload(), headers), 201)
    res = api.list_candidate(cand["id"], headers)
    validate_error(res, "ERR_NO_FINALIZED_SCORE")
    after = validate_success(api.get_candidate(cand["id"], headers), 200)
    assert after["listing_status"] == "DRAFT"


def test_remove_from_draft_rejected(api):
    """PRD §3.4: "Removal moves listing_status from LISTED to REMOVED ... Removal
    is permitted only while the candidate is LISTED."

    Design: Corner/state_machines/corner_remove_from_draft_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_candidate(center, mrn="S3", date_of_birth="1980-01-01T00:00:00Z")
    res = api.remove_candidate(cand["id"], remove_candidate_payload("OTHER"), headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_deactivate_keeps_listing_status_listed(api):
    """PRD §3.4: "A deactivated but still-listed candidate keeps its LISTED status
    yet is excluded from allocation runs." PRD §3.4: "Deactivation moves
    medical_status from ACTIVE to INACTIVE and is permitted only while the
    candidate's listing_status is DRAFT or LISTED."

    Design: Difficulty/non_linear_state_machine/nlsm_candidate_parallel_medical_listing_dimensions
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="A3", date_of_birth="1980-01-01T00:00:00Z")
    after = validate_success(api.deactivate_candidate(cand["id"], headers), 200)
    assert after["medical_status"] == "INACTIVE"
    assert after["listing_status"] == "LISTED"


def test_reactivate_restores_active_while_listed(api):
    """PRD §3.4: "Reactivation moves medical_status from INACTIVE back to ACTIVE
    and is likewise permitted only while listing_status is DRAFT or LISTED." PRD
    §3.2: "These dimensions are orthogonal: a listed candidate that is deactivated
    remains LISTED but stops competing for organs while INACTIVE."

    Design: Difficulty/non_linear_state_machine/nlsm_candidate_parallel_medical_listing_dimensions
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="A3", date_of_birth="1980-01-01T00:00:00Z")
    validate_success(api.deactivate_candidate(cand["id"], headers), 200)
    after = validate_success(api.reactivate_candidate(cand["id"], headers), 200)
    assert after["medical_status"] == "ACTIVE"
    assert after["listing_status"] == "LISTED"


def test_waiting_time_conserved_across_zero_gap_deactivate_reactivate(api):
    """PRD §3.4: "Waiting time accrues only while a candidate is simultaneously
    LISTED and ACTIVE." PRD §3.4: "The value waiting_time_days is computed by
    summing, across all intervals, the elapsed seconds of each interval — using the
    current clock instant as the end of the still-open interval — and then taking
    the whole number of days, that is, the total seconds divided by 86,400 and
    floored to an integer."

    Design: Difficulty/compensating_invariant/ci_waiting_time_conserved_across_deactivate_reactivate
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="G2", date_of_birth="1975-01-01T00:00:00Z")
    set_clock("2026-06-11T00:00:00Z")
    validate_success(api.deactivate_candidate(cand["id"], headers), 200)
    validate_success(api.reactivate_candidate(cand["id"], headers), 200)
    after = validate_success(api.get_candidate(cand["id"], headers), 200)
    assert after["waiting_time_days"] == 10


def test_waiting_time_accrues_only_while_active(api):
    """PRD §3.4: "Deactivation closes the current accrual interval at the present
    clock instant (so no further waiting time accrues while inactive)." PRD §3.4:
    "Spans during which the candidate is INACTIVE or not LISTED contribute nothing."

    Design: Difficulty/compensating_invariant/ci_waiting_time_conserved_across_deactivate_reactivate
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="G3", date_of_birth="1975-01-01T00:00:00Z")
    # Accrue 10 active days, then deactivate.
    set_clock("2026-06-11T00:00:00Z")
    validate_success(api.deactivate_candidate(cand["id"], headers), 200)
    # Advance the clock 10 more days while INACTIVE — these must NOT accrue.
    set_clock("2026-06-21T00:00:00Z")
    after = validate_success(api.get_candidate(cand["id"], headers), 200)
    assert after["waiting_time_days"] == 10
