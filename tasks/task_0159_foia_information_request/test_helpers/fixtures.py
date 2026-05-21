"""Composite setup helpers — multi-step preambles tests can reuse.

The FOIA lifecycle takes 5-15 API calls to reach interesting states
(an estimate-accepted request, a closed search with mixed dispositions,
a remand cycle, a tolled clock at the cap). Each fixture composes the
lower-level steps so test bodies focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is `Requester`, the value of `X-User-ID` is
    interpreted as the `id` of the acting `Requester` entity; any
    ownership check on a resource that references a requester ...
    compares the resource's foreign-key field to `X-User-ID`."

After a Requester is created, fixtures act as that requester by
minting headers via `make_requester_headers(requester["id"])` — never
by reusing the shared TEST_USERS["requester_headers"] placeholder for
ownership-gated calls (file, withdraw, accept-fee, file-appeal). The
placeholder is reserved for tests that probe RBAC failure modes
without exercising ownership.

CLOCK ANCHORING — PRD §2.7:

    "the system exposes a clock-operator capability that advances the
    server's logical clock to a supplied `to_iso_datetime` and runs
    the sweep automatically".

The logical clock is shared across the test process. Fixtures advance
the clock to specific moments using ClockOperator headers; they never
make absolute clock assumptions — only relative durations from
"wherever the clock currently is".

Setup calls use `get_success_data` (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    add_seconds,
    clock_advance_payload,
    create_appeal_payload,
    create_exemption_claim_payload,
    create_fee_assessment_payload,
    create_request_payload,
    create_requester_payload,
    create_responsive_record_payload,
    create_third_party_notice_payload,
    decide_appeal_payload,
    issue_glomar_payload,
    object_third_party_payload,
    parse_iso,
    patch_record_disposition_payload,
    random_suffix,
    start_tolling_payload,
    unique_third_party_id,
)
from .test_users import (
    TEST_USERS,
    make_appeal_authority_headers,
    make_officer_headers,
    make_requester_headers,
    make_third_party_headers,
    OFFICER_SHARED_ID,
    OFFICER_SECONDARY_ID,
    APPEAL_AUTHORITY_SHARED_ID,
    APPEAL_AUTHORITY_SECONDARY_ID,
)


# ===========================================================================
# Clock helpers
# ===========================================================================
def get_server_clock_iso() -> str:
    """Read the current logical clock as an ISO 8601 UTC string."""
    h = TEST_USERS["clock_operator_headers"]
    resp = api_client.get_clock(h)
    data = get_success_data(resp)
    # Implementations expose the clock under either "now" or "clock"
    # or as a flat ISO string — accept any of the obvious shapes.
    if isinstance(data, str):
        return data
    for key in ("now", "clock", "current_time", "server_time"):
        if key in data and isinstance(data[key], str):
            return data[key]
    raise AssertionError(
        f"Could not extract current server clock from {data!r}"
    )


def advance_clock_to_iso(target_iso: str) -> None:
    """Advance the logical clock to `target_iso` (PRD §2.7)."""
    h = TEST_USERS["clock_operator_headers"]
    payload = clock_advance_payload(to_iso_datetime=target_iso)
    resp = api_client.clock_advance(payload, h)
    get_success_data(resp)


def advance_clock_by_days(days: int) -> str:
    """Advance the clock by `days` calendar days from the current
    server clock. Returns the new clock value."""
    current = get_server_clock_iso()
    new_iso = add_seconds(current, days * 24 * 60 * 60)
    advance_clock_to_iso(new_iso)
    return new_iso


def advance_clock_by_seconds(seconds: int) -> str:
    current = get_server_clock_iso()
    new_iso = add_seconds(current, seconds)
    advance_clock_to_iso(new_iso)
    return new_iso


def run_sweep() -> None:
    h = TEST_USERS["clock_operator_headers"]
    resp = api_client.sweep_run(h)
    get_success_data(resp)


# ===========================================================================
# Read helpers — used by tests and other fixtures
# ===========================================================================
def get_requester(requester_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_requester_headers(requester_id)
    return get_success_data(api_client.get_requester(requester_id, h))


def get_request(request_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_request(request_id, h))


def get_responsive_record(record_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_responsive_record(record_id, h))


def get_third_party_notice(notice_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_third_party_notice(notice_id, h))


def get_appeal(appeal_id: str) -> Dict[str, Any]:
    h = TEST_USERS["appeal_authority_headers"]
    return get_success_data(api_client.get_appeal(appeal_id, h))


def get_fee_assessment(assessment_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_fee_assessment(assessment_id, h))


def list_audit_entries(**params: Any) -> List[Dict[str, Any]]:
    """List audit entries with the given filters, paging through ALL
    pages so the caller is not silently truncated to the first page.
    PRD §2.3: limit max is 100; the cumulative audit log can exceed 100
    entries across many tests so we walk has_more pages."""
    h = TEST_USERS["officer_headers"]
    # If the caller did not request a specific page, walk all pages.
    user_supplied_offset = "offset" in params
    page_params = dict(params)
    page_params.setdefault("limit", 100)
    all_entries: List[Dict[str, Any]] = []
    offset = page_params.get("offset", 0)
    while True:
        page_params["offset"] = offset
        resp = api_client.list_audit_entries(h, params=page_params)
        entries, meta = validate_paginated(resp)
        all_entries.extend(entries)
        if user_supplied_offset:
            # Caller asked for one specific page; respect it.
            return entries
        if not meta.get("has_more"):
            break
        offset += page_params["limit"]
    return all_entries


def list_responsive_records_for_request(request_id: str) -> List[Dict[str, Any]]:
    """List responsive records by paging through the audit trail.
    The PRD §4 endpoint table does not expose a list endpoint for
    responsive records by request_id, so we read them back through the
    request fetch + per-id GETs the tests track explicitly.
    """
    raise NotImplementedError(
        "No list endpoint declared for responsive records. "
        "Tests track record ids explicitly from create_*."
    )


# ===========================================================================
# Tier 1 — Requester / Request preambles
# ===========================================================================
def create_requester(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    full_name: Optional[str] = None,
    contact_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Requester. Returns the persisted Requester."""
    payload = create_requester_payload(
        full_name=full_name,
        contact_email=contact_email,
        requester_tier=requester_tier,
        tier_justification=tier_justification,
    )
    # POST /foia/requesters allows {Requester, Officer}; use Officer to
    # avoid the ownership-loop on the Requester role (the new requester
    # id doesn't exist until after the call returns).
    resp = api_client.create_requester(payload, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def file_request(
    *,
    requester: Dict[str, Any],
    subject_summary: Optional[str] = None,
    fee_waiver_requested: bool = False,
) -> Dict[str, Any]:
    """File a new request as the given requester. Returns the Request
    in INTAKE status."""
    headers = make_requester_headers(requester["id"])
    payload = create_request_payload(
        requester_id=requester["id"],
        subject_summary=subject_summary,
        fee_waiver_requested=fee_waiver_requested,
    )
    resp = api_client.create_request(payload, headers)
    return get_success_data(resp)


def acknowledge_request(request_id: str,
                        officer_headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """Acknowledge a request as an Officer. Returns the ACKNOWLEDGED
    Request."""
    h = officer_headers or TEST_USERS["officer_headers"]
    resp = api_client.acknowledge_request(request_id, h)
    return get_success_data(resp)


def create_acknowledged_request(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    fee_waiver_requested: bool = False,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Requester + Request walked through to ACKNOWLEDGED. Returns
    (requester, request)."""
    requester = create_requester(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
    )
    request = file_request(
        requester=requester, fee_waiver_requested=fee_waiver_requested,
    )
    ack = acknowledge_request(request["id"], officer_headers)
    return requester, ack


# ===========================================================================
# Tier 2 — Fee assessment lifecycle
# ===========================================================================
def create_fee_assessment(
    *,
    request_id: str,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
) -> Dict[str, Any]:
    payload = create_fee_assessment_payload(
        request_id=request_id,
        estimated_pages=estimated_pages,
        estimated_search_hours=estimated_search_hours,
        estimated_review_hours=estimated_review_hours,
    )
    resp = api_client.create_fee_assessment(
        payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def estimate_fee_assessment(assessment_id: str) -> Dict[str, Any]:
    resp = api_client.estimate_fee_assessment(
        assessment_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def accept_fee_assessment(assessment_id: str,
                          requester_id: str) -> Dict[str, Any]:
    """Accept a fee estimate as the owning requester. PRD §3.3 requires
    X-User-ID == Request.requester_id."""
    resp = api_client.accept_fee_assessment(
        assessment_id, make_requester_headers(requester_id),
    )
    return get_success_data(resp)


def waive_fee_assessment(assessment_id: str) -> Dict[str, Any]:
    resp = api_client.waive_fee_assessment(
        assessment_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def setup_request_with_estimated_fee(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
    fee_waiver_requested: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Requester + ACKNOWLEDGED Request + ESTIMATED FeeAssessment.
    Returns (requester, request, fee_assessment)."""
    requester, request = create_acknowledged_request(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        fee_waiver_requested=fee_waiver_requested,
    )
    fa = create_fee_assessment(
        request_id=request["id"],
        estimated_pages=estimated_pages,
        estimated_search_hours=estimated_search_hours,
        estimated_review_hours=estimated_review_hours,
    )
    fa = estimate_fee_assessment(fa["id"])
    return requester, request, fa


def setup_request_with_accepted_fee(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Requester + Request + ACCEPTED FeeAssessment, ready to /start-search."""
    requester, request, fa = setup_request_with_estimated_fee(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        estimated_pages=estimated_pages,
        estimated_search_hours=estimated_search_hours,
        estimated_review_hours=estimated_review_hours,
    )
    fa = accept_fee_assessment(fa["id"], requester["id"])
    return requester, request, fa


# ===========================================================================
# Tier 3 — SEARCH-state preambles and record creation
# ===========================================================================
def start_search(request_id: str) -> Dict[str, Any]:
    resp = api_client.start_search(
        request_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def setup_request_in_search(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk the full preamble: Requester + Request + FeeAssessment
    (ACCEPTED) + Request.start-search. Returns (requester, request_in_search,
    fee_assessment)."""
    requester, request, fa = setup_request_with_accepted_fee(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        estimated_pages=estimated_pages,
        estimated_search_hours=estimated_search_hours,
        estimated_review_hours=estimated_review_hours,
    )
    request = start_search(request["id"])
    return requester, request, fa


def create_responsive_record(
    *,
    request_id: str,
    page_count: int = 10,
    title: Optional[str] = None,
    contains_third_party_info: bool = False,
    third_party_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_responsive_record_payload(
        request_id=request_id,
        page_count=page_count,
        title=title,
        contains_third_party_info=contains_third_party_info,
        third_party_id=third_party_id,
    )
    resp = api_client.create_responsive_record(
        payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def patch_record_disposition(record_id: str,
                             *,
                             disposition: str,
                             version: int) -> Dict[str, Any]:
    payload = patch_record_disposition_payload(
        disposition=disposition, version=version,
    )
    resp = api_client.patch_record_disposition(
        record_id, payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def create_exemption_claim(
    *,
    record_id: str,
    exemption_code: str = "B5",
    redaction_scope: str = "FULL",
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_exemption_claim_payload(
        record_id=record_id,
        exemption_code=exemption_code,
        redaction_scope=redaction_scope,
        rationale=rationale,
    )
    resp = api_client.create_exemption_claim(
        payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3.5 — Closed-search and full determination preambles
# ===========================================================================
def close_search(request_id: str) -> Dict[str, Any]:
    resp = api_client.close_search(
        request_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def determine_request(request_id: str) -> Dict[str, Any]:
    resp = api_client.determine_request(
        request_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def setup_records_with_dispositions(
    *,
    request_id: str,
    dispositions: List[Tuple[int, str, Optional[str]]],
) -> List[Dict[str, Any]]:
    """Create N records with (page_count, target_disposition,
    exemption_code-or-None) tuples; transition each to its target
    disposition. WITHHELD_FULL records get a B5 exemption claim before
    the disposition update; RELEASED_REDACTED records get a partial-B5
    claim. RELEASED_FULL records get no exemption.
    Returns the list of records in their final state.
    """
    records: List[Dict[str, Any]] = []
    for page_count, target_disp, exemption_code in dispositions:
        rec = create_responsive_record(
            request_id=request_id, page_count=page_count,
        )
        if target_disp == "WITHHELD_FULL":
            ex_code = exemption_code or "B5"
            create_exemption_claim(
                record_id=rec["id"],
                exemption_code=ex_code,
                redaction_scope="FULL",
            )
        elif target_disp == "RELEASED_REDACTED":
            ex_code = exemption_code or "B5"
            create_exemption_claim(
                record_id=rec["id"],
                exemption_code=ex_code,
                redaction_scope="PARTIAL",
            )
        rec = patch_record_disposition(
            rec["id"], disposition=target_disp, version=rec["version"],
        )
        records.append(rec)
    return records


def setup_request_in_determination_pending(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
    dispositions: Optional[List[Tuple[int, str, Optional[str]]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
          List[Dict[str, Any]]]:
    """Walk through to DETERMINATION_PENDING with the supplied records.
    `dispositions` is a list of (page_count, disposition, exemption_code|None).
    Default: 100 RELEASED_FULL + 30 RELEASED_REDACTED + 20 WITHHELD_FULL
    (the recipe used by Rule 1 / Rule 4 instance #1 in the difficulty-design
    index).
    Returns (requester, request_in_DET_PENDING, fee_assessment, records).
    """
    if dispositions is None:
        dispositions = [
            (100, "RELEASED_FULL", None),
            (30, "RELEASED_REDACTED", "B5"),
            (20, "WITHHELD_FULL", "B5"),
        ]
    requester, request, fa = setup_request_in_search(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        estimated_pages=estimated_pages,
        estimated_search_hours=estimated_search_hours,
        estimated_review_hours=estimated_review_hours,
    )
    records = setup_records_with_dispositions(
        request_id=request["id"], dispositions=dispositions,
    )
    request_after_close = close_search(request["id"])
    fa_after_close = get_fee_assessment(fa["id"])
    return requester, request_after_close, fa_after_close, records


def setup_denied_request(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    estimated_pages: int = 150,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Drive a Request to DENIED with one WITHHELD_FULL record + B5 claim.
    Returns (requester, denied_request, records).
    The officer who issues the determination is identified by `officer_headers`
    so segregation-of-duties tests can later pin the actor_id.
    """
    requester, request, _fa = setup_request_in_search(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        estimated_pages=estimated_pages,
    )
    rec = create_responsive_record(
        request_id=request["id"], page_count=20,
    )
    create_exemption_claim(
        record_id=rec["id"], exemption_code="B5", redaction_scope="FULL",
    )
    rec = patch_record_disposition(
        rec["id"], disposition="WITHHELD_FULL", version=rec["version"],
    )
    h = officer_headers or TEST_USERS["officer_headers"]
    close_resp = api_client.close_search(request["id"], h)
    get_success_data(close_resp)
    det_resp = api_client.determine_request(request["id"], h)
    denied = get_success_data(det_resp)
    return requester, denied, [rec]


def setup_glomar_issued_request(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    glomar_basis: Optional[List[str]] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a Request through to GLOMAR_ISSUED. Glomar requests have
    zero ResponsiveRecords (PRD §3.5). The walking path: requester ->
    request -> acknowledge -> fee_assessment (low pages so estimate <=
    threshold) -> estimate (collapses to 0 under free-threshold) ->
    start-search -> close-search (would fail with no records — instead
    we go through DETERMINATION_PENDING via the glomar-friendly path
    described in PRD §3.5: Glomar is reached as a terminal determination
    from DETERMINATION_PENDING; procedurally bypasses search entirely
    in the sense that the request must have zero records.

    PRD §3.5 wording leaves the path-of-arrival to the implementation;
    the only hard requirements are zero records, glomar_invoked=true,
    and non-empty glomar_exemption_basis from {B1,B6,B7C}. We trigger
    issue-glomar from DETERMINATION_PENDING after walking acknowledge
    -> fee (estimate $0) -> start-search -> close-search (close-search
    succeeds with zero third-party-marked records and zero records full
    stop, per PRD §3.8: the missing-notice rule is only triggered by
    records WITH contains_third_party_info=true).
    """
    requester, request = create_acknowledged_request(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
    )
    # Low-cost fee so estimate collapses below free threshold and
    # start-search can proceed without acceptance.
    fa = create_fee_assessment(
        request_id=request["id"],
        estimated_pages=1,
        estimated_search_hours=0,
        estimated_review_hours=0,
    )
    fa = estimate_fee_assessment(fa["id"])
    h = officer_headers or TEST_USERS["officer_headers"]
    # start-search
    get_success_data(api_client.start_search(request["id"], h))
    # close-search succeeds because zero third-party-info records.
    get_success_data(api_client.close_search(request["id"], h))
    # issue-glomar from DETERMINATION_PENDING.
    basis = glomar_basis if glomar_basis is not None else ["B1"]
    payload = issue_glomar_payload(glomar_exemption_basis=basis)
    glomar_resp = api_client.issue_glomar(request["id"], payload, h)
    glomar_req = get_success_data(glomar_resp)
    return requester, glomar_req


# ===========================================================================
# Tier 4 — Third-party notice preambles
# ===========================================================================
def create_third_party_notice(
    *,
    request_id: str,
    record_id: str,
) -> Dict[str, Any]:
    payload = create_third_party_notice_payload(
        request_id=request_id, record_id=record_id,
    )
    resp = api_client.create_third_party_notice(
        payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def consent_third_party_notice(notice_id: str,
                               third_party_id: str) -> Dict[str, Any]:
    """Consent on behalf of the third party. PRD §3.7 requires
    X-User-ID == ThirdPartyNotice.third_party_id."""
    resp = api_client.consent_third_party_notice(
        notice_id, make_third_party_headers(third_party_id),
    )
    return get_success_data(resp)


def object_third_party_notice(notice_id: str,
                              third_party_id: str,
                              *,
                              objection_grounds: Optional[str] = None,
                              ) -> Dict[str, Any]:
    payload = object_third_party_payload(objection_grounds=objection_grounds)
    resp = api_client.object_third_party_notice(
        notice_id, payload, make_third_party_headers(third_party_id),
    )
    return get_success_data(resp)


def override_third_party_notice(
    notice_id: str,
    appeal_auth_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = appeal_auth_headers or TEST_USERS["appeal_authority_headers"]
    resp = api_client.override_third_party_notice(notice_id, h)
    return get_success_data(resp)


def setup_request_with_third_party_notice(
    *,
    estimated_pages: int = 150,
    record_pages: int = 50,
    third_party_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
          Dict[str, Any]]:
    """SEARCH-state request with one third-party-marked record and a
    PENDING_RESPONSE ThirdPartyNotice. Returns
    (requester, request, record, notice)."""
    tp_id = third_party_id or unique_third_party_id()
    requester, request, _fa = setup_request_in_search(
        estimated_pages=estimated_pages,
    )
    rec = create_responsive_record(
        request_id=request["id"],
        page_count=record_pages,
        contains_third_party_info=True,
        third_party_id=tp_id,
    )
    notice = create_third_party_notice(
        request_id=request["id"], record_id=rec["id"],
    )
    return requester, request, rec, notice


# ===========================================================================
# Tier 5 — Appeal preambles
# ===========================================================================
def file_appeal(
    *,
    request: Dict[str, Any],
    appellant_id: str,
    appellant_role: str = "REQUESTER",
    grounds: Optional[str] = None,
) -> Dict[str, Any]:
    """File an appeal. For REQUESTER appeals, the calling X-User-ID is
    the requester's id; for THIRD_PARTY appeals, it is the third party's
    opaque id."""
    payload = create_appeal_payload(
        request_id=request["id"],
        appellant_role=appellant_role,
        grounds=grounds,
    )
    if appellant_role == "REQUESTER":
        headers = make_requester_headers(appellant_id)
    else:
        headers = make_third_party_headers(appellant_id)
    resp = api_client.create_appeal(payload, headers)
    return get_success_data(resp)


def accept_appeal_for_review(
    appeal_id: str,
    appeal_authority_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Accept-for-review. Caller must pass headers built for the
    AppealAuthority whose X-User-ID differs from the original deciding
    Officer (PRD §2.8)."""
    resp = api_client.accept_appeal_for_review(
        appeal_id, appeal_authority_headers,
    )
    return get_success_data(resp)


def decide_appeal(
    appeal_id: str,
    *,
    decision: str,
    appeal_authority_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Decide an appeal with `decision` in {UPHELD, REVERSED, REMANDED}.
    Caller passes the same headers used at accept-for-review (PRD §2.8
    pins the deciding identity)."""
    payload = decide_appeal_payload(decision=decision)
    resp = api_client.decide_appeal(
        appeal_id, payload, appeal_authority_headers,
    )
    return get_success_data(resp)


def setup_denied_request_with_distinct_authority(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    officer_operator_id: str = OFFICER_SHARED_ID,
    appeal_authority_operator_id: str = APPEAL_AUTHORITY_SHARED_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str],
          Dict[str, str]]:
    """Drive a Request to DENIED using a specific Officer operator id,
    so the DETERMINATION_ISSUED audit entry's actor_id is known.
    Returns (requester, denied_request, officer_headers, distinct_auth_headers).
    The distinct authority headers are pre-built for a different X-User-ID
    so segregation-of-duties does not block accept-for-review.
    """
    officer_headers = make_officer_headers(officer_operator_id)
    requester, denied, _records = setup_denied_request(
        requester_tier=requester_tier,
        tier_justification=tier_justification,
        officer_headers=officer_headers,
    )
    if appeal_authority_operator_id == officer_operator_id:
        raise AssertionError(
            "Test setup error: appeal authority operator id must differ "
            "from the determining officer's operator id."
        )
    auth_headers = make_appeal_authority_headers(appeal_authority_operator_id)
    return requester, denied, officer_headers, auth_headers


def setup_remand_ready_appeal(
    *,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    officer_operator_id: str = OFFICER_SHARED_ID,
    appeal_authority_operator_id: str = APPEAL_AUTHORITY_SHARED_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
          Dict[str, str]]:
    """Build a denied request + a REQUESTER appeal accepted for review
    by a distinct AppealAuthority, ready for /decide with REMANDED.
    Returns (requester, denied_request, appeal_under_review, auth_headers).
    """
    requester, denied, _off_h, auth_h = (
        setup_denied_request_with_distinct_authority(
            requester_tier=requester_tier,
            tier_justification=tier_justification,
            officer_operator_id=officer_operator_id,
            appeal_authority_operator_id=appeal_authority_operator_id,
        )
    )
    appeal = file_appeal(
        request=denied, appellant_id=requester["id"],
        appellant_role="REQUESTER",
    )
    appeal = accept_appeal_for_review(appeal["id"], auth_h)
    return requester, denied, appeal, auth_h


def setup_glomar_then_remand_ready(
    *,
    glomar_basis: Optional[List[str]] = None,
    officer_operator_id: str = OFFICER_SHARED_ID,
    appeal_authority_operator_id: str = APPEAL_AUTHORITY_SHARED_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
          Dict[str, str]]:
    """GLOMAR_ISSUED request + REQUESTER appeal under review, by a
    distinct AppealAuthority. Returns (requester, glomar_request,
    appeal_under_review, auth_headers).
    """
    officer_headers = make_officer_headers(officer_operator_id)
    requester, glomar_req = setup_glomar_issued_request(
        glomar_basis=glomar_basis, officer_headers=officer_headers,
    )
    auth_h = make_appeal_authority_headers(appeal_authority_operator_id)
    appeal = file_appeal(
        request=glomar_req, appellant_id=requester["id"],
        appellant_role="REQUESTER",
    )
    appeal = accept_appeal_for_review(appeal["id"], auth_h)
    return requester, glomar_req, appeal, auth_h


# ===========================================================================
# Tier 6 — Tolling and clock-driven preambles
# ===========================================================================
def start_tolling(request_id: str,
                  *,
                  reason: Optional[str] = None) -> Dict[str, Any]:
    payload = start_tolling_payload(reason=reason)
    resp = api_client.start_tolling(
        request_id, payload, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def resume_clock(request_id: str) -> Dict[str, Any]:
    resp = api_client.resume_clock(
        request_id, TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def drive_tolling_to_cap(
    *,
    request_id: str,
    days_per_cycle: int = 5,
    target_days: int = 30,
) -> Dict[str, Any]:
    """Repeatedly /start-tolling + advance clock + /resume-clock until
    tolling_days_consumed == `target_days`. Returns the Request at the
    target. PRD §3.4: tolling_days_consumed accumulates business days
    elapsed between TOLLING_STARTED and TOLLING_ENDED; we advance the
    clock by calendar days large enough to cover the desired business
    days conservatively (7 calendar days per 5 business days).
    """
    if days_per_cycle <= 0:
        raise ValueError("days_per_cycle must be positive")
    request = get_request(request_id)
    while request.get("tolling_days_consumed", 0) < target_days:
        remaining = target_days - request["tolling_days_consumed"]
        chunk = min(days_per_cycle, remaining)
        # Calendar days = chunk + buffer to cover weekends.
        calendar_chunk = chunk + (2 if chunk >= 5 else 0)
        start_tolling(request_id)
        advance_clock_by_days(calendar_chunk)
        request = resume_clock(request_id)
    return request


# ===========================================================================
# Tier 7 — Audit lookups
# ===========================================================================
def find_audit_entries(
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_code: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Filter the audit log by any combination of subject_type,
    subject_id, event_code. PRD §2.6: "Audit entries are listable by
    any combination of subject_type, subject_id, and event_code."
    """
    params: Dict[str, Any] = {"limit": limit}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if event_code is not None:
        params["event_code"] = event_code
    return list_audit_entries(**params)


__all__ = [
    "get_server_clock_iso",
    "advance_clock_to_iso",
    "advance_clock_by_days",
    "advance_clock_by_seconds",
    "run_sweep",
    "get_requester", "get_request", "get_responsive_record",
    "get_third_party_notice", "get_appeal", "get_fee_assessment",
    "list_audit_entries",
    "create_requester",
    "file_request",
    "acknowledge_request",
    "create_acknowledged_request",
    "create_fee_assessment",
    "estimate_fee_assessment",
    "accept_fee_assessment",
    "waive_fee_assessment",
    "setup_request_with_estimated_fee",
    "setup_request_with_accepted_fee",
    "start_search",
    "setup_request_in_search",
    "create_responsive_record",
    "patch_record_disposition",
    "create_exemption_claim",
    "close_search",
    "determine_request",
    "setup_records_with_dispositions",
    "setup_request_in_determination_pending",
    "setup_denied_request",
    "setup_glomar_issued_request",
    "create_third_party_notice",
    "consent_third_party_notice",
    "object_third_party_notice",
    "override_third_party_notice",
    "setup_request_with_third_party_notice",
    "file_appeal",
    "accept_appeal_for_review",
    "decide_appeal",
    "setup_denied_request_with_distinct_authority",
    "setup_remand_ready_appeal",
    "setup_glomar_then_remand_ready",
    "start_tolling",
    "resume_clock",
    "drive_tolling_to_cap",
    "find_audit_entries",
]
