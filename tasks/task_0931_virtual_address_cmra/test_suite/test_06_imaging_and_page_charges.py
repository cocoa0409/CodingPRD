"""Imaging: splitting, the retry budget, the Form 1583 gate and page charging."""

from test_helpers import (
    CMRA_OPERATOR,
    UNKNOWN_UUID_2,
    ApiErrorId,
    assert_scan_job,
    assert_usage_ledger_entry,
    log_and_match_letter,
    open_billing_cycle,
    read_mail_item,
    read_scan_job_list,
    request_scan,
    scan_job_payload,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Splitting
# ==========================================================================
def test_a_twenty_five_page_request_produces_exactly_one_job(api):
    """PRD §3.6: "The number of jobs is `requested_pages` divided by 25 and **rounded up
    to the next whole number**."
    PRD §3.6: "The boundary is inclusive: 25 requested pages produce exactly one job of
    25 pages, and 26 produce two jobs of 25 and 1."

    25 requested pages sits exactly ON the inclusive single-job edge.

    Design: Difficulty/boundary_precision_check/scan_split_boundary_twenty_five_versus_twenty_six_pages
    """
    ctx = setup_releasable_box("L-1201", "Sam Split", holder_email="sam@example.com")
    item = log_and_match_letter(ctx, interior_scan_consent=True)

    response = api.create_scan_job(
        item["id"], scan_job_payload("INTERIOR", 25), ctx["holder_headers"]
    )
    job = validate_success(response, 201)
    assert_scan_job(job)
    assert job["split_group_size"] == 1
    assert job["split_index"] == 1
    assert job["page_count"] == 25

    _, meta = validate_paginated(api.list_scan_jobs(item["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1


def test_a_twenty_six_page_request_splits_into_twenty_five_plus_one(api):
    """PRD §3.6: "Every job but the last carries exactly 25 pages in its `page_count`;
    the last carries `requested_pages` less 25 times one fewer than the job count."
    PRD §3.6: "Each job records `split_index`, its 1-based position in the group, and
    `split_group_size`, the number of jobs the request was split into; jobs are created
    in ascending `split_index` order and each stores the full `requested_pages` of the
    originating request."
    PRD §3.6: "The created resource returned to the caller is the job with `split_index`
    1."

    26 requested pages sits one page ABOVE the inclusive single-job edge.

    Design: Difficulty/boundary_precision_check/scan_split_boundary_twenty_five_versus_twenty_six_pages
    """
    ctx = setup_releasable_box("L-1201", "Sam Split", holder_email="sam@example.com")
    item = log_and_match_letter(ctx, interior_scan_consent=True)

    first = validate_success(
        api.create_scan_job(item["id"], scan_job_payload("INTERIOR", 26), ctx["holder_headers"]),
        201,
    )
    assert first["split_group_size"] == 2
    assert first["split_index"] == 1
    assert first["page_count"] == 25

    jobs, meta = validate_paginated(api.list_scan_jobs(item["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 2
    assert jobs[1]["split_index"] == 2
    assert jobs[1]["page_count"] == 1


def test_requested_pages_outside_the_declared_range_is_a_validation_failure(api):
    """PRD §3.6: "The request names a `scan_tier` — `COVER` images the exterior only,
    `INTERIOR` opens the piece, and `OCR` opens it and adds a searchable text layer —
    and `requested_pages`, the total number of pages wanted across the whole request,
    which must be at least 1 and at most 200."
    PRD §3.6: "Anything outside that range is `ERR_VALIDATION`."

    0 sits one below the inclusive lower edge, 201 one above the inclusive upper edge,
    and 200 exactly ON the upper edge.

    Design: Corner/validations/scan_request_page_count_outside_the_declared_range_is_rejected
    """
    ctx = setup_releasable_box("Z-3011", "Ned Range", holder_email="ned@example.com")
    item = log_and_match_letter(ctx, interior_scan_consent=True)

    validate_error(
        api.create_scan_job(item["id"], scan_job_payload("INTERIOR", 0), ctx["holder_headers"]),
        ApiErrorId.ERR_VALIDATION.value,
    )
    validate_error(
        api.create_scan_job(item["id"], scan_job_payload("INTERIOR", 201), ctx["holder_headers"]),
        ApiErrorId.ERR_VALIDATION.value,
    )

    job = validate_success(
        api.create_scan_job(item["id"], scan_job_payload("INTERIOR", 200), ctx["holder_headers"]),
        201,
    )
    assert job["split_group_size"] == 8
    assert job["page_count"] == 25
    _, meta = validate_paginated(api.list_scan_jobs(item["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 8


# ==========================================================================
# The retry budget
# ==========================================================================
def _setup_job_at_the_retry_ceiling(api, ctx, item_id):
    """Fail and retry twice so retry_count is 2 and the job is IN_PROGRESS."""
    job = request_scan(ctx, item_id, "COVER", 10)
    for _ in range(2):
        validate_success(api.start_scan_job(job["id"], CMRA_OPERATOR))
        validate_success(api.fail_scan_job(job["id"], CMRA_OPERATOR))
        validate_success(api.retry_scan_job(job["id"], CMRA_OPERATOR))
    validate_success(api.start_scan_job(job["id"], CMRA_OPERATOR))
    return job


def test_the_third_failure_abandons_the_job_instead_of_failing_it(api):
    """PRD §3.6: "Failing moves it out of `IN_PROGRESS` along one of two branches decided
    by the retry budget, which is capped at 2 retries: while `retry_count` is strictly
    less than 2 the job goes `IN_PROGRESS → FAILED`, and once `retry_count` has reached
    2 the very same operation instead goes `IN_PROGRESS → ABANDONED`."
    PRD §3.6: "An abandoned job is terminal and consumes no quota whatsoever: no
    usage-ledger entry is appended for it and no counter moves."

    Design: Difficulty/non_linear_state_machine/scan_job_retry_loop_capped_then_abandoned
    """
    ctx = setup_releasable_box("E-501", "Ivy Scan", holder_email="ivy@example.com")
    item = log_and_match_letter(ctx)
    job = _setup_job_at_the_retry_ceiling(api, ctx, item["id"])

    abandoned = validate_success(api.fail_scan_job(job["id"], CMRA_OPERATOR))
    assert abandoned["status"] == "ABANDONED"
    assert abandoned["retry_count"] == 2
    assert abandoned["split_group_size"] == 1
    assert abandoned["page_count"] == 10

    assert open_billing_cycle(ctx["box_id"])["scan_pages_consumed"] == 0


def test_retrying_an_abandoned_job_exhausts_the_retry_budget(api):
    """PRD §3.6: "Retrying a job that has been abandoned is `ERR_SCAN_RETRY_EXHAUSTED`."
    PRD §3.6: "Retrying a `FAILED` job moves it `FAILED → QUEUED` and increments
    `retry_count` by one, which makes `QUEUED → IN_PROGRESS → FAILED → QUEUED` a genuine
    cycle, traversable at most twice."

    Design: Difficulty/non_linear_state_machine/scan_job_retry_loop_capped_then_abandoned
    """
    ctx = setup_releasable_box("E-501", "Ivy Scan", holder_email="ivy@example.com")
    item = log_and_match_letter(ctx)
    job = _setup_job_at_the_retry_ceiling(api, ctx, item["id"])
    validate_success(api.fail_scan_job(job["id"], CMRA_OPERATOR))

    response = api.retry_scan_job(job["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_SCAN_RETRY_EXHAUSTED.value)

    jobs = read_scan_job_list(item["id"])
    assert jobs[0]["status"] == "ABANDONED"
    assert jobs[0]["retry_count"] == 2
    assert open_billing_cycle(ctx["box_id"])["scan_pages_consumed"] == 0


def test_completing_a_queued_job_before_starting_it_is_rejected(api):
    """PRD §3.6: "Starting moves it `QUEUED → IN_PROGRESS`."
    PRD §3.6: "Completing moves it `IN_PROGRESS → COMPLETED` and is where the money
    happens."
    PRD §2.9 rung 14: "The target resource sits in a state from which the requested
    transition is declared. Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/completing_a_queued_scan_job_before_starting_it_is_rejected
    """
    ctx = setup_releasable_box("Z-1006", "Nan Queue", holder_email="nan@example.com")
    item = log_and_match_letter(ctx)
    job = request_scan(ctx, item["id"], "COVER", 2)

    response = api.complete_scan_job(job["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_scan_job_list(item["id"])[0]["status"] == "QUEUED"
    assert open_billing_cycle(ctx["box_id"])["scan_pages_consumed"] == 0


def test_starting_a_scan_job_that_does_not_exist_is_a_not_found(api):
    """PRD §2.9 rung 3: "The first templated resource named in the path exists."
    PRD §5: "| `ERR_SCAN_JOB_NOT_FOUND` | 404 |"

    Design: Corner/errors/error_scan_job_not_found_on_unknown_job_id
    """
    setup_releasable_box("Z-5001", "Una Ghost", holder_email="una@example.com")

    response = api.start_scan_job(UNKNOWN_UUID_2, CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_SCAN_JOB_NOT_FOUND.value)


# ==========================================================================
# The Form 1583 gate at INTERIOR, and consent
# ==========================================================================
def test_cover_scanning_is_permitted_for_a_member_whose_id_set_is_incomplete(api):
    """PRD §2.8: "Gate C explicitly **permits** these four operations regardless of
    release eligibility:"
    PRD §3.6: "And the Form 1583 gate applies at `INTERIOR` and `OCR` but not at
    `COVER`: the exterior of an envelope may be photographed for a member with no
    paperwork at all, while opening it may not."

    Design: Difficulty/cross_entity_state_dependency/interior_scan_gated_by_recipient_id_document_set
    """
    ctx = setup_releasable_box(
        "O-1501",
        "Val Half",
        holder_email="val@example.com",
        home_address_line="5 Half St",
        file_address_document=False,
    )
    item = log_and_match_letter(ctx, interior_scan_consent=True)

    response = api.create_scan_job(
        item["id"], scan_job_payload("COVER", 1), ctx["holder_headers"]
    )
    job = validate_success(response, 201)
    assert job["scan_tier"] == "COVER"
    assert job["status"] == "QUEUED"
    assert read_mail_item(item["id"])["handling_status"] == "AWAITING_CLEARANCE"


def test_interior_scanning_is_blocked_when_a_document_class_was_never_verified(api):
    """PRD §2.9 rung 18: "The matched roster member holds an accepted form, but the
    governing `PHOTO` document or the governing `ADDRESS` document does not exist — that
    class has never reached `VERIFIED`. Then `ERR_ID_DOCUMENT_SET_INCOMPLETE` (409)."
    PRD §3.3: "2. The governing `PHOTO` document is not null and the governing
    `ADDRESS` document is not null. Otherwise `BLOCKED` with `blocked_reason`
    `ID_SET_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/interior_scan_gated_by_recipient_id_document_set
    """
    ctx = setup_releasable_box(
        "O-1501",
        "Val Half",
        holder_email="val@example.com",
        home_address_line="5 Half St",
        file_address_document=False,
    )
    item = log_and_match_letter(ctx, interior_scan_consent=True)

    response = api.create_scan_job(
        item["id"], scan_job_payload("INTERIOR", 4), ctx["holder_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ID_DOCUMENT_SET_INCOMPLETE.value)

    member = validate_success(api.get_recipient(ctx["recipient_id"], CMRA_OPERATOR))
    assert member["roster_status"] == "AUTHORIZED"
    assert member["release_eligibility"] == "BLOCKED"
    assert member["blocked_reason"] == "ID_SET_INCOMPLETE"


def test_interior_imaging_without_standing_consent_is_refused(api):
    """PRD §3.6: "An `INTERIOR` or `OCR` request requires the piece's
    `interior_scan_consent` to be true, failing which the request is
    `ERR_SCAN_CONSENT_REQUIRED`."
    PRD §2.9 rung 21: "An `INTERIOR` or `OCR` scan requires the piece's
    `interior_scan_consent` to be true. Otherwise `ERR_SCAN_CONSENT_REQUIRED` (403)."

    Design: Corner/validations/interior_scan_without_consent_is_rejected
    """
    ctx = setup_releasable_box("Z-3006", "Hal Privacy", holder_email="hal@example.com")
    item = log_and_match_letter(ctx, interior_scan_consent=False)

    cover = validate_success(
        api.create_scan_job(item["id"], scan_job_payload("COVER", 1), ctx["holder_headers"]),
        201,
    )
    assert cover["scan_tier"] == "COVER"

    blocked = api.create_scan_job(
        item["id"], scan_job_payload("OCR", 3), ctx["holder_headers"]
    )
    validate_error(blocked, ApiErrorId.ERR_SCAN_CONSENT_REQUIRED.value)

    _, meta = validate_paginated(api.list_scan_jobs(item["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1


# ==========================================================================
# Page charging and the quota partition
# ==========================================================================
def _setup_straddling_scan(api):
    ctx = setup_releasable_box(
        "V-2201",
        "Wil Quota",
        holder_email="wil@example.com",
        plan_overrides={"name": "Plus Thirty Pages", "included_scan_pages": 30},
    )
    item = log_and_match_letter(ctx, interior_scan_consent=True)
    request_scan(ctx, item["id"], "INTERIOR", 40)
    jobs = read_scan_job_list(item["id"])
    for job in jobs:
        validate_success(api.start_scan_job(job["id"], CMRA_OPERATOR))
    ctx["item_id"] = item["id"]
    ctx["jobs"] = jobs
    return ctx


def test_a_straddling_scan_request_splits_into_in_tier_and_overage_pages(api):
    """PRD §3.6: "For every other class, the remaining allowance is the tier's
    `included_scan_pages` less the cycle's `scan_pages_consumed`, floored at zero."
    PRD §3.6: "`billed_pages_in_tier` is the smaller of the job's `page_count` and that
    remaining allowance, and `billed_pages_overage` is `page_count` less
    `billed_pages_in_tier`."
    PRD §3.6: "`charge_cents` is `billed_pages_overage` multiplied by the plan's
    `overage_scan_page_cents` multiplied by that tier multiplier."

    Design: Difficulty/compensating_invariant/scan_quota_tranche_partition_across_a_straddling_request
    """
    ctx = _setup_straddling_scan(api)
    first, second = ctx["jobs"][0], ctx["jobs"][1]

    completed_first = validate_success(api.complete_scan_job(first["id"], CMRA_OPERATOR))
    assert completed_first["page_count"] == 25
    assert completed_first["billed_pages_in_tier"] == 25
    assert completed_first["billed_pages_overage"] == 0
    assert completed_first["charge_cents"] == 0

    completed_second = validate_success(api.complete_scan_job(second["id"], CMRA_OPERATOR))
    assert completed_second["page_count"] == 15
    assert completed_second["billed_pages_in_tier"] == 5
    assert completed_second["billed_pages_overage"] == 10
    assert completed_second["charge_cents"] == 250


def test_the_quota_tranche_partition_holds_across_the_straddling_request(api):
    """PRD §2.11: "Within one billing cycle and one unit type, the quantities on
    `IN_TIER` ledger entries plus the quantities on `OVERAGE` ledger entries sum exactly
    to that cycle's consumption counter for the unit type."
    PRD §3.6: "Completion then increments the cycle's `scan_pages_consumed` by the job's
    `page_count`, moves the piece's `billing_status` `UNBILLED → METERED` if it was still
    unbilled, and bumps `ScanJob.version` by one."

    Design: Difficulty/compensating_invariant/scan_quota_tranche_partition_across_a_straddling_request
    """
    ctx = _setup_straddling_scan(api)
    for job in ctx["jobs"]:
        validate_success(api.complete_scan_job(job["id"], CMRA_OPERATOR))

    cycle = open_billing_cycle(ctx["box_id"])
    assert cycle["scan_pages_consumed"] == 40

    entries, _ = validate_paginated(
        api.list_cycle_usage_entries(
            cycle["id"], CMRA_OPERATOR, params={"unit_type": "SCAN_PAGE", "limit": 100}
        )
    )
    for entry in entries:
        assert_usage_ledger_entry(entry)
    in_tier = sum(e["quantity"] for e in entries if e["tranche"] == "IN_TIER")
    overage = sum(e["quantity"] for e in entries if e["tranche"] == "OVERAGE")
    assert in_tier == 30
    assert overage == 10
    assert in_tier + overage == cycle["scan_pages_consumed"]
    assert sum(e["amount_cents"] for e in entries) == 250


def test_a_tier_that_forbids_overage_rejects_the_completion_outright(api):
    """PRD §3.12: "If the overage quantity is greater than zero and the tier's
    `allows_overage` is false, the **whole request** is rejected with
    `ERR_QUOTA_EXHAUSTED` (HTTP 402) and nothing at all is written."
    PRD §2.9 rung 36: "Overage metering does not need to write an `OVERAGE` tranche
    against a plan tier whose `allows_overage` is false. Otherwise
    `ERR_QUOTA_EXHAUSTED` (402), and nothing at all is written."

    Design: Corner/calculations/quota_exhausted_when_the_tier_forbids_overage
    """
    ctx = setup_releasable_box(
        "Z-2008",
        "Zed Cap",
        holder_email="zed@example.com",
        plan_overrides={
            "monthly_fee_cents": 1000,
            "included_scan_pages": 5,
            "included_forwards": 1,
            "allows_overage": False,
        },
    )
    item = log_and_match_letter(ctx)
    job = request_scan(ctx, item["id"], "COVER", 7)
    validate_success(api.start_scan_job(job["id"], CMRA_OPERATOR))
    cycle = open_billing_cycle(ctx["box_id"])

    response = api.complete_scan_job(job["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_QUOTA_EXHAUSTED.value)

    assert read_scan_job_list(item["id"])[0]["status"] == "IN_PROGRESS"
    assert open_billing_cycle(ctx["box_id"])["scan_pages_consumed"] == 0
    _, meta = validate_paginated(
        api.list_cycle_usage_entries(
            cycle["id"], CMRA_OPERATOR, params={"unit_type": "SCAN_PAGE"}
        )
    )
    assert meta["total_count"] == 0
