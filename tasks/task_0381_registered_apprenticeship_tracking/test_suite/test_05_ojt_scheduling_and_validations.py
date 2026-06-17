"""On-the-job scheduling constraints (apprentice session overlap, journeyworker
supervision buffer), time-range and date validations, and the duplicate /
sponsor-mismatch / pagination validation corners.

Covers resource_temporal_overlap and the validations corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_sponsor,
    create_qualified_journeyworker,
    create_apprentice,
    create_draft_program,
    create_active_program,
    create_active_agreement,
    setup_active_agreement,
    register_agreement,
    log_ojt_entry,
    AGENCY,
)
from test_helpers.test_users import make_sponsor_headers


# ===========================================================================
# Difficulty: resource_temporal_overlap / apprentice_session_overlap_adjacency_allowed
# ===========================================================================
def test_apprentice_session_true_overlap_rejected(api):
    """PRD §3.4: "The new window must not overlap any other on-the-job entry for
    the same apprentice on the same `work_date`; windows that merely touch at an
    endpoint - where one window's end equals the next window's start - are
    permitted, but any true overlap is rejected with
    `ERR_APPRENTICE_SESSION_OVERLAP`."

    An existing [480,600] window and a new [540,660] window truly overlap on the
    same work_date -> ERR_APPRENTICE_SESSION_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/apprentice_session_overlap_adjacency_allowed
    """
    sc = setup_active_agreement()
    log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 600, 2, work_date="2026-02-01")
    res = api.create_ojt_entry(
        {"agreement_id": sc.agreement_id, "work_date": "2026-02-01",
         "start_time": 540, "end_time": 660, "credited_hours": 2},
        make_sponsor_headers(sc.sponsor_id),
    )
    validate_error(res, ApiErrorId.ERR_APPRENTICE_SESSION_OVERLAP.value)


def test_apprentice_session_touching_endpoint_allowed(api):
    """PRD §3.4: "windows that merely touch at an endpoint - where one window's
    end equals the next window's start - are permitted, but any true overlap is
    rejected with `ERR_APPRENTICE_SESSION_OVERLAP`."

    An existing [480,600] window and a new [600,720] window touch exactly at 600
    on the same work_date and are accepted (201).

    Design: Difficulty/resource_temporal_overlap/apprentice_session_overlap_adjacency_allowed
    """
    sc = setup_active_agreement()
    log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 600, 2, work_date="2026-02-01")
    res = api.create_ojt_entry(
        {"agreement_id": sc.agreement_id, "work_date": "2026-02-01",
         "start_time": 600, "end_time": 720, "credited_hours": 2},
        make_sponsor_headers(sc.sponsor_id),
    )
    entry = validate_success(res, 201)
    assert entry["status"] == "PENDING"


# ===========================================================================
# Difficulty: resource_temporal_overlap / journeyworker_supervision_buffer_conflict
# ===========================================================================
def test_journeyworker_supervision_buffer_conflict(api):
    """PRD §3.4: "across all on-the-job entries supervised by the agreement's
    journeyworker on the same `work_date`, the new window must be separated from
    every existing window by at least the supervision buffer of fifteen minutes -
    there must be neither overlap nor a gap smaller than that buffer - or the
    entry is rejected with `ERR_JOURNEYWORKER_SUPERVISION_CONFLICT`."

    One journeyworker supervises two apprentices. AGR1 has [480,540] on 2026-02-01;
    a new AGR2 window [550,610] is only 10 minutes later (< 15) -> conflict.

    Design: Difficulty/resource_temporal_overlap/journeyworker_supervision_buffer_conflict
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])

    agr1 = create_active_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    agr2 = create_active_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    log_ojt_entry(sponsor["id"], agr1["id"], 480, 540, 1, work_date="2026-02-01")
    res = api.create_ojt_entry(
        {"agreement_id": agr2["id"], "work_date": "2026-02-01",
         "start_time": 550, "end_time": 610, "credited_hours": 1},
        headers,
    )
    validate_error(res, ApiErrorId.ERR_JOURNEYWORKER_SUPERVISION_CONFLICT.value)


def test_journeyworker_supervision_beyond_buffer_allowed(api):
    """PRD §3.4: "the new window must be separated from every existing window by
    at least the supervision buffer of fifteen minutes - there must be neither
    overlap nor a gap smaller than that buffer - or the entry is rejected with
    `ERR_JOURNEYWORKER_SUPERVISION_CONFLICT`."

    A second window starting 15 minutes after the first ends ([480,540] then
    [555,615], a 15-minute gap) meets the buffer exactly and is accepted (201).

    Design: Difficulty/resource_temporal_overlap/journeyworker_supervision_buffer_conflict
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])

    agr1 = create_active_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    agr2 = create_active_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    log_ojt_entry(sponsor["id"], agr1["id"], 480, 540, 1, work_date="2026-02-01")
    res = api.create_ojt_entry(
        {"agreement_id": agr2["id"], "work_date": "2026-02-01",
         "start_time": 555, "end_time": 615, "credited_hours": 1},
        headers,
    )
    entry = validate_success(res, 201)
    assert entry["status"] == "PENDING"


# ===========================================================================
# Corner: validations / ojt_invalid_time_range_rejected
# ===========================================================================
def test_ojt_invalid_time_range_rejected(api):
    """PRD §3.4: "The time window must be well-formed: `start_time` must be
    strictly less than `end_time`, both must lie within 0 through 1440 inclusive,
    and `credited_hours` must be greater than zero; any violation yields
    `ERR_INVALID_TIME_RANGE`."

    start_time == end_time (600 == 600) violates strict ordering.

    Design: Corner/validations/ojt_invalid_time_range_rejected
    """
    sc = setup_active_agreement()
    res = api.create_ojt_entry(
        {"agreement_id": sc.agreement_id, "work_date": "2026-02-01",
         "start_time": 600, "end_time": 600, "credited_hours": 1},
        make_sponsor_headers(sc.sponsor_id),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


# ===========================================================================
# Corner: validations / ojt_work_date_before_agreement_start_rejected
# ===========================================================================
def test_ojt_work_date_before_agreement_start_rejected(api):
    """PRD §3.4: "The `work_date` must be on or after the agreement's
    `start_date`, or the entry is rejected with `ERR_DATE_BEFORE_AGREEMENT_START`."

    A work_date of 2026-02-15 against a start_date of 2026-03-01 is too early.

    Design: Corner/validations/ojt_work_date_before_agreement_start_rejected
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"])
    agr = create_active_agreement(
        sponsor["id"], program["id"], ap["id"], jw["id"], start_date="2026-03-01"
    )
    res = api.create_ojt_entry(
        {"agreement_id": agr["id"], "work_date": "2026-02-15",
         "start_time": 480, "end_time": 600, "credited_hours": 2},
        make_sponsor_headers(sponsor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DATE_BEFORE_AGREEMENT_START.value)


# ===========================================================================
# Corner: validations / duplicate_wage_step_number_rejected
# ===========================================================================
def test_duplicate_wage_step_number_rejected(api):
    """PRD §3.1: "Attempting to create a second wage step with an existing
    `step_number` for the same program, or a second milestone with an existing
    `sequence`, is rejected with `ERR_DUPLICATE_RESOURCE`."

    A second WageStep with step_number 1 on the same DRAFT program is rejected.

    Design: Corner/validations/duplicate_wage_step_number_rejected
    """
    sponsor = create_sponsor()
    program = get_success_data(
        api.create_program(
            {"sponsor_id": sponsor["id"], "occupation_code": "47-2111.00",
             "occupation_title": "Electrician", "completion_type": "HOURS_BASED",
             "ojt_hours_required": 16, "rti_hours_required": 8,
             "base_journeyworker_wage_cents": 4000, "journeyman_ratio": 4},
            make_sponsor_headers(sponsor["id"]),
        )
    )
    headers = make_sponsor_headers(sponsor["id"])
    validate_success(
        api.create_wage_step(
            {"program_id": program["id"], "step_number": 1,
             "ojt_hours_threshold": 0, "wage_pct": 0.50},
            headers,
        ), 201
    )
    res = api.create_wage_step(
        {"program_id": program["id"], "step_number": 1,
         "ojt_hours_threshold": 5, "wage_pct": 0.60},
        headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ===========================================================================
# Corner: validations / agreement_sponsor_mismatch_rejected
# ===========================================================================
def test_agreement_sponsor_mismatch_rejected(api):
    """PRD §3.3: "At create time the system enforces sponsor scoping: the
    supervising journeyworker's `sponsor_id` and the apprentice's `sponsor_id`
    must both equal the program's `sponsor_id`. If either belongs to a different
    sponsor, the create is rejected with `ERR_SPONSOR_MISMATCH`."

    A journeyworker owned by sponsor S2 used on a program/apprentice owned by S1
    is rejected.

    Design: Corner/validations/agreement_sponsor_mismatch_rejected
    """
    s1 = create_sponsor(ein="35-3636363")
    s2 = create_sponsor(ein="36-3737373")
    jw2 = create_qualified_journeyworker(s2["id"])
    ap1 = create_apprentice(s1["id"])
    program = create_active_program(s1["id"])
    res = api.create_agreement(
        {"program_id": program["id"], "apprentice_id": ap1["id"],
         "journeyworker_id": jw2["id"], "start_date": "2026-01-01"},
        make_sponsor_headers(s1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SPONSOR_MISMATCH.value)


# ===========================================================================
# Corner: validations / pagination_limit_out_of_bounds_rejected
# ===========================================================================
def test_pagination_limit_out_of_bounds_rejected(api, sponsor_headers):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or an `offset` below
    0, is rejected with `ERR_INVALID_PAGINATION`."

    A list call with limit=500 (> 100) is rejected.

    Design: Corner/validations/pagination_limit_out_of_bounds_rejected
    """
    res = api.list_sponsors(sponsor_headers, params={"limit": 500})
    validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)
