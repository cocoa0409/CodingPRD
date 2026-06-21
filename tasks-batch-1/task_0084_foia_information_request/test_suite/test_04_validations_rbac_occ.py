"""Validation errors, precedence, RBAC, OCC, and intake/lifecycle corners.

Difficulty queue: priority_pair_validation_conflict (state vs glomar-safety).
Corner queue: validations, errors, rbac, OCC, and entity/state-machine intake basics.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, NO_AUTH_HEADERS, TEST_USERS, fixtures,
)


# ─────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/state_vs_glomar_safety_precedence
# ─────────────────────────────────────────────────────
def test_glomar_on_perfected_request_reports_invalid_state(api):
    """PRD §3.6: "Invoking it is OCC-guarded by `expected_request_version` and requires the
    request to be in `PROCESSING`."
    PRD §2.6: "Only after all of those pass does the system evaluate whether the target
    resource is in a state that permits the requested transition (`ERR_INVALID_STATE`), and
    then the domain-specific business rules described throughout Section 3."

    The request is only PERFECTED (not PROCESSING), so the state check (ERR_INVALID_STATE)
    pre-empts the glomar-precondition business rule.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_glomar_safety_precedence
    """
    officer, off_h = fixtures.create_officer(can_invoke_glomar=True)
    requester, _ = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    fixtures.perfect_request(off_h, request["id"], fee_category="OTHER")  # PERFECTED, not PROCESSING
    v0 = fixtures.current_version(off_h, request["id"])
    resp = api.invoke_glomar(request["id"], {"expected_request_version": v0}, off_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/occ_determination_stale_version
# ─────────────────────────────────────────────────────
def test_occ_determination_stale_version_rejected(api):
    """PRD §3.6: "A determination resolves a processing request into a final outcome and is
    OCC-guarded: the officer supplies `expected_request_version`, and a mismatch with the
    request's current `version` is rejected with `ERR_STALE_REQUEST_VERSION`."
    PRD §2.9: "Applying an extension ... advances the version".

    Design: Corner/cross_cutting_complexity_layers/occ_determination_stale_version
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec = fixtures.add_record(off_h, rid, title="doc", page_count=1)
    fixtures.review_record(off_h, rec["id"], "RELEASABLE")
    v_stale = fixtures.current_version(off_h, rid)
    fixtures.extend_request(off_h, rid)  # an intervening write advances the version
    resp = api.issue_determination(rid, {"expected_request_version": v_stale}, off_h)
    validate_error(resp, ApiErrorId.ERR_STALE_REQUEST_VERSION.value)


# ─────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/occ_version_increments_on_fee_estimate
# ─────────────────────────────────────────────────────
def test_fee_estimate_increments_version_by_one(api):
    """PRD §3.4: "Recording the estimate runs the tiered fee calculation, sets the estimate's
    `assessed_fee_cents`, recomputes the requester's `outstanding_balance_cents`, advances the
    request's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_fee_estimate
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    v_before = fixtures.current_version(off_h, rid)
    fixtures.assess_fee(off_h, rid, search_hours=1, review_hours=0, billable_pages=10, expected_version=v_before)
    v_after = fixtures.current_version(off_h, rid)
    assert v_after == v_before + 1, (v_before, v_after)


# ─────────────────────────────────────────────────────
# Corner/validations
# ─────────────────────────────────────────────────────
def test_payment_amount_mismatch_rejected(api):
    """PRD §3.4: "The payment body carries `amount_cents`, which must equal the request's
    currently assessed fee due; a payment whose amount does not match the assessed fee is
    rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`, as partial payments are not accepted."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    ctx = fixtures.setup_awaiting_payment(
        declared_category="COMMERCIAL", fee_category="COMMERCIAL",
        search_hours=6, review_hours=4, billable_pages=500,
    )
    resp = api.pay_request(ctx["request"]["id"], {"amount_cents": 1000}, ctx["requester_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


def test_invalid_exemption_code_rejected(api):
    """PRD §3.3: "The `exemption_code` must be one of the nine statutory codes `B1`, `B2`,
    `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, or `B9`; anything outside that set — or a request-level
    exemption whose code is not one of `B1` or `B7` — is rejected with
    `ERR_INVALID_EXEMPTION_CODE`."

    Design: Corner/validations/invalid_exemption_code_rejected
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rec = fixtures.add_record(off_h, ctx["request"]["id"], title="doc", page_count=1)
    resp = api.create_exemption(
        ctx["request"]["id"],
        {"applies_to_kind": "RECORD", "exemption_code": "B99", "justification": "bad code",
         "record_id": rec["id"]},
        off_h,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_EXEMPTION_CODE.value)


def test_request_level_exemption_b3_rejected(api):
    """PRD §3.3: "anything outside that set — or a request-level exemption whose code is not
    one of `B1` or `B7` — is rejected with `ERR_INVALID_EXEMPTION_CODE`."

    Design: Corner/validations/request_level_exemption_b3_rejected
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    resp = api.create_exemption(
        ctx["request"]["id"],
        {"applies_to_kind": "REQUEST", "exemption_code": "B3", "justification": "statute"},
        ctx["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_EXEMPTION_CODE.value)


def test_submitter_info_record_missing_submitter_id(api):
    """PRD §3.3: "a record flagged as containing submitter information without an accompanying
    `submitter_id`, or a downstream objection whose `submitter_id` does not equal the record's
    `submitter_id`, is rejected with `ERR_SUBMITTER_MISMATCH`."

    Design: Corner/validations/submitter_info_record_missing_submitter_id
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    resp = api.create_record(
        ctx["request"]["id"],
        {"title": "doc", "page_count": 1, "contains_submitter_info": True},
        ctx["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUBMITTER_MISMATCH.value)


def test_appeal_against_processing_not_appealable(api):
    """PRD §3.7: "An appeal may only be filed against a request that has reached a
    determination state — `GRANTED`, `PARTIALLY_GRANTED`, `DENIED`, or `GLOMAR_INVOKED`;
    filing against a request in any other state is rejected with `ERR_NOT_APPEALABLE`."

    Design: Corner/validations/appeal_against_processing_not_appealable
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    resp = api.file_appeal(
        ctx["request"]["id"],
        {"appellant_id": ctx["requester"]["id"], "grounds": "premature",
         "filed_at": "2026-01-20T00:00:00.000Z"},
        ctx["requester_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_APPEALABLE.value)


def test_appeal_window_closed_after_90_days(api):
    """PRD §3.7: "The appeal must be filed within 90 calendar days of the determination: when
    the interval from the determination to `filed_at` exceeds 90 calendar days, the filing is
    rejected with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_window_closed_after_90_days
    """
    officer, off_h = fixtures.create_officer()
    fixtures.set_clock(off_h, "2026-02-02T00:00:00.000Z")
    requester, req_h = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    fixtures.perfect_request(off_h, request["id"], fee_category="OTHER")
    fixtures.assign_request(off_h, request["id"])
    rec = fixtures.add_record(off_h, request["id"], title="memo", page_count=1)
    fixtures.add_record_exemption(off_h, request["id"], rec["id"], exemption_code="B5", justification="deliberative")
    fixtures.review_record(off_h, rec["id"], "WITHHELD")
    fixtures.issue_determination(off_h, request["id"])  # DENIED, determination at ~2026-02-02
    fixtures.set_clock(off_h, "2026-09-01T00:00:00.000Z")
    resp = api.file_appeal(
        request["id"],
        {"appellant_id": requester["id"], "grounds": "late", "filed_at": "2026-09-01T00:00:00.000Z"},
        req_h,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)


# ─────────────────────────────────────────────────────
# Corner/errors/error_submitter_mismatch_objection_triggerable
# ─────────────────────────────────────────────────────
def test_objection_submitter_mismatch_rejected(api):
    """PRD §3.8: "An officer opens a Reverse-FOIA notice against such a record, supplying the
    `submitter_id` of the originating business (which must equal the record's own
    `submitter_id`)".
    PRD §3.3: "a downstream objection whose `submitter_id` does not equal the record's
    `submitter_id`, is rejected with `ERR_SUBMITTER_MISMATCH`."

    Design: Corner/errors/error_submitter_mismatch_objection_triggerable
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    sub_a, _ = fixtures.create_submitter(off_h)
    sub_b, _ = fixtures.create_submitter(off_h)
    record = fixtures.add_submitter_record(off_h, ctx["request"]["id"], sub_a["id"])
    resp = api.create_objection(
        record["id"], {"submitter_id": sub_b["id"], "objection_text": "wrong submitter"}, off_h
    )
    validate_error(resp, ApiErrorId.ERR_SUBMITTER_MISMATCH.value)


# ─────────────────────────────────────────────────────
# Corner/rbac
# ─────────────────────────────────────────────────────
def test_requester_cannot_perfect_request_forbidden(api):
    """PRD §4 (endpoint table): "POST `/requests/{id}/perfect` ... Authorized Role(s):
    FoiaOfficer".
    PRD §2.1: "When an authenticated user attempts an operation their role is not permitted to
    perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/requester_cannot_perfect_request_forbidden
    """
    officer, off_h = fixtures.create_officer()
    requester, req_h = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    resp = api.perfect_request(request["id"], {"fee_category": "OTHER"}, req_h)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_officer_cannot_decide_appeal_segregation_of_duties(api):
    """PRD §2.1: "Segregation of duties is structural: officers and appeal authorities are
    disjoint roles".
    PRD §2.1: "When an authenticated user attempts an operation their role is not permitted to
    perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/officer_cannot_decide_appeal_segregation_of_duties
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=1, exemption_code="B5")
    # The officer (not the appeal authority) attempts the decide.
    resp = api.decide_appeal(ctx["appeal"]["id"], {"decision": "AFFIRM"}, ctx["officer_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_payment_by_non_owner_requester_denied(api):
    """PRD §2.1: "a requester may pay, withdraw, or file an appeal against a request only when
    the request's `requester_id` equals the acting requester's `id` ... A violation of any of
    these ownership conditions is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/payment_by_non_owner_requester_denied
    """
    ctx = fixtures.setup_awaiting_payment(
        declared_category="COMMERCIAL", fee_category="COMMERCIAL",
        search_hours=6, review_hours=4, billable_pages=500,
    )
    other_requester, other_h = fixtures.create_requester(ctx["officer_headers"], declared_category="OTHER")
    resp = api.pay_request(ctx["request"]["id"], {"amount_cents": 45000}, other_h)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares
    the capacity in which they act. If either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    officer, off_h = fixtures.create_officer()
    requester, _ = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    resp = api.get_request(request["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_submitter_cannot_object_other_submitters_objection(api):
    """PRD §2.1: "a submitter may formally object only when the objection's `submitter_id`
    equals the acting submitter's `id`. A violation of any of these ownership conditions is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/submitter_cannot_object_other_submitters_objection
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    sub_a, _ = fixtures.create_submitter(off_h)
    sub_b, sub_b_h = fixtures.create_submitter(off_h)
    record = fixtures.add_submitter_record(off_h, ctx["request"]["id"], sub_a["id"])
    objection = fixtures.open_objection(off_h, record["id"], sub_a["id"])
    resp = api.object_to_disclosure(objection["id"], sub_b_h)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─────────────────────────────────────────────────────
# Corner/entities
# ─────────────────────────────────────────────────────
def test_create_foia_request_returns_201_and_defaults(api):
    """PRD §3.2: "A newly submitted request begins with its lifecycle `status` set to
    `SUBMITTED` and immediately gets a first audit event of type `SUBMITTED`."
    PRD §3.2: "The submission may also carry an `expedited` flag indicating that a compelling
    need for expedited processing was invoked (defaulting to false)".
    PRD §2.4: "`version` (integer): a system-managed integer that begins at its initial value
    and increments by one on every mutation of the resource."

    Design: Corner/entities/create_foia_request_returns_201_and_defaults
    """
    officer, off_h = fixtures.create_officer()
    requester, req_h = fixtures.create_requester(off_h, declared_category="OTHER")
    created = validate_success(api.create_request(
        {"requester_id": requester["id"], "subject_description": "docs",
         "received_at": "2026-01-05T00:00:00.000Z"},
        req_h,
    ), expected_status=201)
    assert created["status"] == "SUBMITTED", created
    assert created["expedited"] is False, created
    assert created["version"] == 1, created


def test_get_request_not_found_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource causes
    the request to be rejected immediately with `ERR_NOT_FOUND`".

    Design: Corner/entities/get_request_not_found_returns_404
    """
    officer, off_h = fixtures.create_officer()
    resp = api.get_request(NON_EXISTENT_UUID, off_h)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_request_missing_subject_description_returns_422(api):
    """PRD §2.6: "the structural validity of the request body — required fields present and
    well-typed ... (`ERR_INVALID_REQUEST`)".
    PRD §3.2: "provides the `requester_id` of the person on whose behalf it is filed, a
    non-empty `subject_description` of the records sought".

    Design: Corner/entities/create_request_missing_subject_description_returns_422
    """
    officer, off_h = fixtures.create_officer()
    requester, req_h = fixtures.create_requester(off_h, declared_category="OTHER")
    resp = api.create_request(
        {"requester_id": requester["id"], "received_at": "2026-01-05T00:00:00.000Z"},
        req_h,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_request_unknown_requester_fk_returns_404(api):
    """PRD §2.5: "any foreign key supplied in a request body — such as a `requester_id`,
    `submitter_id`, `record_id`, `request_id`, `room_id`, or `station_id` — must reference an
    existing entity; a dangling body foreign key is rejected with `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/create_request_unknown_requester_fk_returns_404
    """
    officer, off_h = fixtures.create_officer()
    resp = api.create_request(
        {"requester_id": "11111111-1111-4111-8111-111111111111",
         "subject_description": "x", "received_at": "2026-01-05T00:00:00.000Z"},
        off_h,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_list_requests_pagination_envelope(api):
    """PRD §2.3: "List responses include the following fields in the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_requests_pagination_envelope
    """
    officer, off_h = fixtures.create_officer()
    requester, _ = fixtures.create_requester(off_h, declared_category="OTHER")
    fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    data, meta = validate_paginated(api.list_requests(off_h))
    assert meta["total_count"] >= 1, meta
    assert isinstance(meta["has_more"], bool), meta


# ─────────────────────────────────────────────────────
# Corner/state_machines: perfect, assign-invalid, extend
# ─────────────────────────────────────────────────────
def test_perfect_from_submitted_starts_clock(api):
    """PRD §3.2: "Perfection advances the request from `SUBMITTED` to `PERFECTED`, creates the
    request's processing deadline with a `base_due_at` of the receipt instant plus 20 working
    days and an `effective_due_at` computed from it, sets the deadline dimension to `RUNNING`".

    Design: Corner/state_machines/perfect_from_submitted_starts_clock
    """
    officer, off_h = fixtures.create_officer()
    requester, _ = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    perfected = validate_success(api.perfect_request(request["id"], {"fee_category": "OTHER"}, off_h))
    assert perfected["status"] == "PERFECTED", perfected
    assert perfected["deadline_status"] == "RUNNING", perfected

    deadline = validate_success(api.get_deadline(request["id"], off_h))
    if isinstance(deadline, list):
        deadline = deadline[0]
    # received Mon 2026-01-05 + 20 working days = 2026-02-02
    assert deadline["base_due_at"].startswith("2026-02-02"), deadline


def test_extend_twice_rejected(api):
    """PRD §3.5: "The extension is permitted only when no extension has yet been applied —
    that is, when `extension_days_added` is still 0 ... A second extension attempt is rejected
    with `ERR_EXTENSION_ALREADY_USED`."

    Design: Corner/state_machines/extend_twice_rejected
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    validate_success(api.extend_request(ctx["request"]["id"], off_h))
    resp = api.extend_request(ctx["request"]["id"], off_h)
    validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_USED.value)


def test_extend_adds_ten_working_days(api):
    """PRD §3.5: "Applying it sets `extension_days_added` to 10 working days, recomputes
    `effective_due_at`, sets the deadline dimension to `EXTENDED`".

    Design: Corner/state_machines/extend_adds_ten_working_days
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    validate_success(api.extend_request(ctx["request"]["id"], off_h))
    deadline = validate_success(api.get_deadline(ctx["request"]["id"], off_h))
    if isinstance(deadline, list):
        deadline = deadline[0]
    assert deadline["extension_days_added"] == 10, deadline
    # base_due 2026-02-02 + 10 working days = 2026-02-16
    assert deadline["effective_due_at"].startswith("2026-02-16"), deadline
    req = validate_success(api.get_request(ctx["request"]["id"], off_h))
    assert req["deadline_status"] == "EXTENDED", req
