"""Validation precedence, cross-entity preconditions, temporal-overlap and
in-flight-duplicate guards, business errors, and optimistic-concurrency control.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    NON_EXISTENT_UUID,
    create_request_payload, create_document_payload, create_id_verification_payload,
    create_ron_session_payload, create_apostille_order_payload, create_loan_package_payload,
    create_journal_entry_payload,
    TEST_USERS, make_notary_headers,
    setup_world, setup_world_no_fee, setup_quoted_request, setup_assigned_request,
    setup_scheduled_session, setup_submitted_apostille, setup_loan_package, scrub_package,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["apostille_clerk_headers"]
VIEWER = TEST_USERS["viewer_headers"]


# ─── Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_assign

def test_assign_draft_request_returns_invalid_state_over_ron_auth(api):
    """PRD §2.8: "Sixth, the target resource's current state is checked for transition
    legality, yielding `ERR_INVALID_STATE`. Only after all of these pass are the
    domain-specific business rules of §3 evaluated."
    PRD §3.5: "Assigning a notary moves a `QUOTED` request to `ASSIGNED`."

    A DRAFT (never-quoted) RON request assigned to a non-ron_authorized notary violates
    both the state check (request not QUOTED) and RON authorization; the state check runs
    first -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_assign
    """
    world = setup_world(notary_overrides={"ron_authorized": False, "nsa_certified": False})
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="RON",
                               expected_stamp_count=1), COORD))
    res = api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": request["version"]},
        COORD)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_assign_quoted_request_to_unauthorized_ron_notary_returns_ron_error(api):
    """PRD §3.5: "When the request's `delivery_mode` is `RON`, the notary must have
    `ron_authorized` set to true, otherwise `ERR_RON_NOT_AUTHORIZED`."

    Once the request IS QUOTED (state check passes), the business-safety check fires.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_assign
    """
    world = setup_world(notary_overrides={"ron_authorized": False, "nsa_certified": False})
    world, request, document = setup_quoted_request(
        world=world,
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1})
    res = api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": request["version"]},
        COORD)
    validate_error(res, "ERR_RON_NOT_AUTHORIZED", expected_status=409)


# ─── Difficulty/priority_pair_validation_conflict/existence_beats_state_on_start_session

def test_start_session_on_missing_request_returns_not_found(api):
    """PRD §2.8: "Third, referenced-resource existence is checked left-to-right, yielding
    `ERR_NOT_FOUND`."
    PRD §2.7: "When a path or body references a resource, existence is validated
    left-to-right: a missing resource anywhere in the chain yields `ERR_NOT_FOUND` before
    any later check runs."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_start_session
    """
    world = setup_world_no_fee()
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.start_session(NON_EXISTENT_UUID, nheaders)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_complete_on_missing_request_returns_not_found(api):
    """PRD §2.7: "When a path or body references a resource, existence is validated
    left-to-right: a missing resource anywhere in the chain yields `ERR_NOT_FOUND` before
    any later check runs."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_start_session
    """
    world = setup_world_no_fee()
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.complete_request(NON_EXISTENT_UUID, {}, nheaders)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Difficulty/boundary_precision_check/quote_empty_document_set_rejected ───

def test_quote_with_no_documents_rejected(api):
    """PRD §3.2: "Quoting moves the request from `DRAFT` to `QUOTED`. It requires that
    the request have at least one document, otherwise `ERR_NO_DOCUMENTS`".

    Design: Difficulty/boundary_precision_check/quote_empty_document_set_rejected
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    res = api.quote_request(request["id"], COORD)
    validate_error(res, "ERR_NO_DOCUMENTS", expected_status=409)


def test_quote_with_one_document_succeeds(api):
    """PRD §3.2: "Quoting moves the request from `DRAFT` to `QUOTED`. It requires that
    the request have at least one document, otherwise `ERR_NO_DOCUMENTS`, and that a fee
    schedule exist for the request's `state_code`, otherwise `ERR_FEE_SCHEDULE_MISSING`."

    Design: Difficulty/boundary_precision_check/quote_empty_document_set_rejected
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    get_success_data(api.create_document(create_document_payload(request["id"]), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    assert quoted["status"] == "QUOTED"


# ─── Difficulty/cross_entity_state_dependency/start_session_requires_pass_idverification

def test_start_session_without_verification_rejected(api):
    """PRD §3.6: "This requires exactly one RON session for the request to be in
    `session_status` `SCHEDULED`, otherwise `ERR_NO_SCHEDULED_SESSION`, and a `PASS`
    identity verification to exist for the pairing of the request and the request's
    signer, otherwise `ERR_ID_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/start_session_requires_pass_idverification
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.start_session(request["id"], nheaders)
    validate_error(res, "ERR_ID_NOT_VERIFIED", expected_status=409)


def test_start_session_with_pass_verification_succeeds(api):
    """PRD §3.6: "A notary starts the signing by moving the request from `ASSIGNED` to
    `IN_SESSION`."
    PRD §3.6: "and a `PASS` identity verification to exist for the pairing of the request
    and the request's signer, otherwise `ERR_ID_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/start_session_requires_pass_idverification
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=True)
    nheaders = make_notary_headers(world["notary"]["id"])
    started = get_success_data(api.start_session(request["id"], nheaders))
    assert started["status"] == "IN_SESSION"


# ─── Difficulty/cross_entity_state_dependency/apostille_route_requires_request_completed

def test_route_apostille_for_uncompleted_request_rejected(api):
    """PRD §3.8: "From `SUBMITTED` a clerk may route it to `ROUTED`, but only if the
    referenced document's signing request is `COMPLETED`, otherwise
    `ERR_DOCUMENT_NOT_NOTARIZED`".

    Design: Difficulty/cross_entity_state_dependency/apostille_route_requires_request_completed
    """
    world, request, document, order = setup_submitted_apostille(
        destination_country="DE",
        doc_overrides={"title": "Diploma", "doc_type": "DIPLOMA",
                       "requires_apostille": True, "signing_fee_cents": 1000},
        complete_request=False)
    res = api.route_apostille_order(order["id"], CLERK)
    validate_error(res, "ERR_DOCUMENT_NOT_NOTARIZED", expected_status=409)


def test_route_apostille_for_completed_request_succeeds(api):
    """PRD §3.8: "From `SUBMITTED` a clerk may route it to `ROUTED`, but only if the
    referenced document's signing request is `COMPLETED`, otherwise
    `ERR_DOCUMENT_NOT_NOTARIZED`".

    Design: Difficulty/cross_entity_state_dependency/apostille_route_requires_request_completed
    """
    world, request, document, order = setup_submitted_apostille(
        destination_country="DE", complete_request=True)
    routed = get_success_data(api.route_apostille_order(order["id"], CLERK))
    assert routed["status"] == "ROUTED"


# ─── Difficulty/resource_temporal_overlap/ron_session_half_open_overlap_rejected

def test_overlapping_session_for_same_notary_rejected(api):
    """PRD §3.4: "The new session's half-open interval from `scheduled_start` up to but
    not including `scheduled_end` must not overlap any other non-`ENDED` session for the
    same notary, and the end must be strictly after the start; an overlap or an inverted
    interval yields `ERR_SESSION_OVERLAP`."

    First session [10:00,11:00); second [10:30,11:30) overlaps -> ERR_SESSION_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/ron_session_half_open_overlap_rejected
    """
    world, req_a, doc_a, session_a = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    # Second ASSIGNED request on the same notary.
    world, req_b, doc_b = setup_assigned_request(
        world=world,
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1})
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.create_ron_session(
        create_ron_session_payload(req_b["id"], "2026-03-02T10:30:00Z", "2026-03-02T11:30:00Z"),
        nheaders)
    validate_error(res, "ERR_SESSION_OVERLAP", expected_status=409)


def test_adjacent_touching_session_accepted(api):
    """PRD §3.4: "The new session's half-open interval from `scheduled_start` up to but
    not including `scheduled_end` must not overlap any other non-`ENDED` session for the
    same notary".

    First session [10:00,11:00); second [11:00,12:00) touches at the boundary but the
    half-open intervals do not overlap -> accepted.

    Design: Difficulty/resource_temporal_overlap/ron_session_half_open_overlap_rejected
    """
    world, req_a, doc_a, session_a = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    world, req_b, doc_b = setup_assigned_request(
        world=world,
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1})
    nheaders = make_notary_headers(world["notary"]["id"])
    session_b = get_success_data(api.create_ron_session(
        create_ron_session_payload(req_b["id"], "2026-03-02T11:00:00Z", "2026-03-02T12:00:00Z"),
        nheaders))
    assert session_b["session_status"] == "SCHEDULED"


# ─── Difficulty/resource_temporal_overlap/apostille_duplicate_inflight_same_document

def test_duplicate_inflight_apostille_for_same_document_rejected(api):
    """PRD §3.8: "The system refuses a duplicate: a new order is rejected with
    `ERR_DUPLICATE_APOSTILLE` when an in-flight order — one in `SUBMITTED` or `ROUTED` —
    already exists for the same `document_id`."

    Design: Difficulty/resource_temporal_overlap/apostille_duplicate_inflight_same_document_rejected
    """
    world, request, document, order = setup_submitted_apostille(
        destination_country="JP", complete_request=False)
    res = api.create_apostille_order(
        create_apostille_order_payload(document["id"], destination_country="JP",
                                       sos_office_state="CA"), CLERK)
    validate_error(res, "ERR_DUPLICATE_APOSTILLE", expected_status=409)


def test_second_apostille_after_rejection_allowed(api):
    """PRD §3.8: "The system refuses a duplicate: a new order is rejected with
    `ERR_DUPLICATE_APOSTILLE` when an in-flight order — one in `SUBMITTED` or `ROUTED` —
    already exists for the same `document_id`."

    Once the first order leaves the in-flight set (REJECTED), a second order for the same
    document is accepted.

    Design: Difficulty/resource_temporal_overlap/apostille_duplicate_inflight_same_document_rejected
    """
    world, request, document, order = setup_submitted_apostille(
        destination_country="JP", complete_request=False)
    get_success_data(api.reject_apostille_order(order["id"], CLERK))
    order2 = get_success_data(api.create_apostille_order(
        create_apostille_order_payload(document["id"], destination_country="JP",
                                       sos_office_state="CA"), CLERK))
    assert order2["status"] == "SUBMITTED"


# ─── Corner/validations/assign_to_expired_commission_rejected ────────────────

def test_assign_to_expired_commission_rejected(api):
    """PRD §3.5: "The target notary must be in `status` `ACTIVE`, otherwise
    `ERR_NOTARY_NOT_ACTIVE`, and the notary's `commission_expires_at` must be strictly
    after the logical clock, otherwise `ERR_COMMISSION_EXPIRED`."

    Design: Corner/validations/assign_to_expired_commission_rejected
    """
    world = setup_world(notary_overrides={"commission_expires_at": "2026-04-01T00:00:00Z"})
    get_success_data(api.set_clock("2026-06-01T00:00:00Z", COORD))
    world, request, document = setup_quoted_request(
        world=world,
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1})
    res = api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": request["version"]},
        COORD)
    validate_error(res, "ERR_COMMISSION_EXPIRED", expected_status=409)


# ─── Corner/validations/session_cap_exceeded_rejected ────────────────────────

def test_fourth_scheduled_session_exceeds_cap(api):
    """PRD §3.4: "the notary's `active_session_count` — the count of their `SCHEDULED`
    and `LIVE` sessions — must be strictly less than the concurrent-session cap of 3
    before a new scheduled session is accepted; at or above the cap the request is
    rejected with `ERR_SESSION_CAP_EXCEEDED`."

    Design: Corner/validations/session_cap_exceeded_rejected
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    windows = [("08:00", "09:00"), ("10:00", "11:00"), ("12:00", "13:00")]
    for start, end in windows:
        world, req, doc = setup_assigned_request(
            world=world,
            request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                               "expected_stamp_count": 1})
        get_success_data(api.create_ron_session(
            create_ron_session_payload(req["id"], f"2026-03-02T{start}:00Z",
                                       f"2026-03-02T{end}:00Z"), nheaders))
    # Fourth assigned request -> scheduling the 4th session exceeds the cap.
    world, req4, doc4 = setup_assigned_request(
        world=world,
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1})
    res = api.create_ron_session(
        create_ron_session_payload(req4["id"], "2026-03-02T14:00:00Z", "2026-03-02T15:00:00Z"),
        nheaders)
    validate_error(res, "ERR_SESSION_CAP_EXCEEDED", expected_status=409)


# ─── Corner/errors/nsa_not_certified_on_loan_assign ──────────────────────────

def test_assign_loan_request_to_non_nsa_notary_rejected(api):
    """PRD §3.5: "When the request's `doc_category` is `LOAN_SIGNING`, the notary must
    have `nsa_certified` set to true, otherwise `ERR_NSA_NOT_CERTIFIED`."

    Design: Corner/errors/nsa_not_certified_on_loan_assign
    """
    world = setup_world(notary_overrides={"ron_authorized": True, "nsa_certified": False})
    world, request, document = setup_quoted_request(
        world=world,
        request_overrides={"doc_category": "LOAN_SIGNING", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1},
        doc_overrides={"title": "Deed", "doc_type": "DEED", "signing_fee_cents": 5000})
    res = api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": request["version"]},
        COORD)
    validate_error(res, "ERR_NSA_NOT_CERTIFIED", expected_status=409)


# ─── Corner/errors/fee_schedule_missing_on_quote ─────────────────────────────

def test_quote_without_fee_schedule_rejected(api):
    """PRD §3.2: "and that a fee schedule exist for the request's `state_code`, otherwise
    `ERR_FEE_SCHEDULE_MISSING`."

    Design: Corner/errors/fee_schedule_missing_on_quote
    """
    world = setup_world_no_fee(account_overrides={"default_state_code": "TX"})
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               state_code="TX", doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    get_success_data(api.create_document(create_document_payload(request["id"]), COORD))
    res = api.quote_request(request["id"], COORD)
    validate_error(res, "ERR_FEE_SCHEDULE_MISSING", expected_status=409)


# ─── Corner/errors/loan_package_against_non_loan_request_rejected ────────────

def test_loan_package_for_non_loan_request_rejected(api):
    """PRD §3.9: "It is created against a request via `request_id` whose `doc_category`
    must be `LOAN_SIGNING` — a package raised against any other category is rejected with
    `ERR_NOT_LOAN_SIGNING`".

    Design: Corner/errors/loan_package_against_non_loan_request_rejected
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.create_loan_package(
        create_loan_package_payload(request["id"], lender_ref="LN-X"), nheaders)
    validate_error(res, "ERR_NOT_LOAN_SIGNING", expected_status=409)


# ─── Corner/cross_cutting_complexity_layers/occ_assign_correct_version_succeeds

def test_assign_with_current_version_succeeds_and_bumps_version(api):
    """PRD §2.9: "Assigning a notary to a signing request requires the request body to
    carry `expected_request_version`, the request `version` the client last observed."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by exactly
    one on each mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_assign_correct_version_succeeds
    """
    world, request, document = setup_quoted_request(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1})
    quoted_version = request["version"]
    assigned = get_success_data(api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": quoted_version},
        COORD))
    assert assigned["status"] == "ASSIGNED"
    assert assigned["version"] == quoted_version + 1


# ─── Corner/cross_cutting_complexity_layers/occ_fund_stale_package_rejected ──

def test_fund_with_stale_package_version_rejected(api):
    """PRD §2.9: "funding a loan package requires `expected_package_version` carrying the
    package `version` the client last observed; if a re-scrub has advanced the package's
    `version` since the client read it, funding against that stale snapshot is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_fund_stale_package_rejected
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    # COMPLETED LOAN_SIGNING request.
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="LOAN_SIGNING", delivery_mode="RON",
                               expected_stamp_count=1), COORD))
    document = get_success_data(api.create_document(
        create_document_payload(request["id"], title="Deed", doc_type="DEED",
                                signing_fee_cents=5000), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    get_success_data(api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": quoted["version"]},
        COORD))
    get_success_data(api.create_id_verification(
        create_id_verification_payload(request["id"], world["signer"]["id"],
                                       kba_score=80, credential_score=95, biometric_score=80),
        nheaders))
    get_success_data(api.create_ron_session(
        create_ron_session_payload(request["id"], "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"),
        nheaders))
    get_success_data(api.start_session(request["id"], nheaders))
    get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="ACKNOWLEDGMENT"),
        nheaders))
    get_success_data(api.complete_request(request["id"], {}, nheaders))

    package = get_success_data(api.create_loan_package(
        create_loan_package_payload(request["id"], lender_ref="LN-9", package_discount_pct=0),
        nheaders))
    scrubbed = get_success_data(api.scrub_loan_package(package["id"], nheaders))
    stale_version = scrubbed["version"]
    # Re-scrub cycle advances the package version past stale_version.
    get_success_data(api.unscrub_loan_package(package["id"], nheaders))
    get_success_data(api.scrub_loan_package(package["id"], nheaders))

    res = api.fund_loan_package(
        package["id"], {"expected_package_version": stale_version}, COORD)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
