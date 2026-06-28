"""Business-rule validations: validation-precedence pairs, boundary precision,
cross-entity gates, temporal overlap (stakeout & filing windows), and the
fiscal / territory / capacity / suspension guards.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_server_headers,
    make_notary_headers,
    setup_reference_data,
    create_submitted_request,
    offer_to_server,
    log_attempt,
    setup_active_assignment,
    setup_notarized_request,
    setup_filed_request,
    create_filing,
    get_request,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────
def test_invalid_state_beats_diligence_on_posting_service(api):
    """PRD 2.6: "Sixth, on every state-transition endpoint, a target resource that
    is not in a state from which the requested transition is defined yields
    `ERR_INVALID_STATE` (409). Only after all of these pass does the system
    evaluate the domain-specific business rules ... diligence ...".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_diligence_state_vs_business_safety
    """
    county, server, client = setup_reference_data(
        deposit_cents=0,
        county_overrides={"name": "Butte", "state_code": "CA", "min_diligent_attempts": 3},
    )
    # Request only SUBMITTED (offered but not accepted => not IN_PROGRESS), 0 attempts.
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    # POSTING service violates BOTH the state precondition (not IN_PROGRESS) and
    # diligence (0 < 3 distinct days); the state check wins.
    validate_error(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "POSTING", "served_at_utc": "2026-01-02T09:00:00Z"},
            make_server_headers(server["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_affidavit_not_notarized_beats_window_full(api):
    """PRD 3.9: "the checks read in order. The request must be in `SERVED` status
    (else `ERR_INVALID_STATE`). The linked affidavit must be in `NOTARIZED` status
    (else `ERR_AFFIDAVIT_NOT_NOTARIZED`). The county's `e_file_enabled` must be
    true (else `ERR_EFILE_NOT_ENABLED`). And the filing's e-file window must
    respect the county's aggregate concurrency cap ... (else
    `ERR_FILING_WINDOW_FULL`)."

    Design: Difficulty/priority_pair_validation_conflict/notarized_beats_window_full_business_safety_vs_business_temporal
    """
    county = get_success_data(
        api.create_county(
            {"name": "Tehama", "state_code": "CA", "e_file_enabled": True,
             "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 1}, ADMIN
        )
    )
    server = get_success_data(api.create_server({"full_name": "Win Window", "license_no": "PS-6100"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Lam Law", "email": "l@law.com"}, ADMIN))
    get_success_data(api.deposit(client["id"], {"amount_cents": 80000}, ADMIN))
    svr = make_server_headers(server["id"])

    # F_other: fully notarized + SUBMITTED, occupies the single concurrency slot [05:00,07:00).
    sr1 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T09:00:00Z", "2026-01-01T09:05:00Z", "notary-9")
    f_other = create_filing(sr1["aff_sr_id"], sr1["aff_id"], "2026-01-05T00:00:00Z", "2026-01-05T02:00:00Z")
    get_success_data(api.set_filing_state(f_other["id"], {"to_status": "SUBMITTED"}, DISPATCHER))

    # Request2: SERVED, affidavit only SIGNED (not notarized); filing window overlaps.
    sr2 = create_submitted_request(client["id"], county["id"], recipient_name="T")
    asg2 = offer_to_server(sr2["id"], server["id"], sr2["version"])
    get_success_data(api.accept_assignment(asg2["id"], svr))
    log_attempt(asg2["id"], server["id"], "2026-01-01T10:00:00Z", "CONTACT_MADE")
    get_success_data(
        api.record_service(
            sr2["id"],
            {"assignment_id": asg2["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-01T10:05:00Z"},
            svr,
        )
    )
    aff2 = get_success_data(api.list_request_affidavits(sr2["id"], svr))[0]
    get_success_data(api.sign_affidavit(aff2["id"], svr))  # SIGNED only, NOT notarized.
    f2 = create_filing(sr2["id"], aff2["id"], "2026-01-05T01:00:00Z", "2026-01-05T03:00:00Z")
    # Both affidavit-not-notarized and window-full apply; affidavit check (earlier) wins.
    validate_error(
        api.set_filing_state(f2["id"], {"to_status": "SUBMITTED"}, DISPATCHER),
        ApiErrorId.ERR_AFFIDAVIT_NOT_NOTARIZED.value,
    )


def _serve_and_notarize(api, client_id, county_id, server_id, attempt_at, served_at, notary_id):
    svr = make_server_headers(server_id)
    sr = create_submitted_request(client_id, county_id, recipient_name="O")
    asg = offer_to_server(sr["id"], server_id, sr["version"])
    get_success_data(api.accept_assignment(asg["id"], svr))
    log_attempt(asg["id"], server_id, attempt_at, "CONTACT_MADE")
    get_success_data(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": served_at},
            svr,
        )
    )
    aff = get_success_data(api.list_request_affidavits(sr["id"], svr))[0]
    get_success_data(api.sign_affidavit(aff["id"], svr))
    get_success_data(api.notarize_affidavit(aff["id"], make_notary_headers(notary_id)))
    return {"aff_sr_id": sr["id"], "aff_id": aff["id"]}


# ─── Queue A: boundary_precision_check ────────────────────────────────────
def test_diligence_boundary_two_days_rejected_for_posting(api):
    """PRD 3.4: "A county's `min_diligent_attempts` sets the floor: substitute or
    posting service, and a non-est declaration, are all legally permitted only once
    `distinct_attempt_days` is at least the county's `min_diligent_attempts`.
    Falling short yields `ERR_DILIGENCE_NOT_MET`."

    Design: Difficulty/boundary_precision_check/diligence_min_attempts_boundary_on_services_endpoint
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Colusa", "state_code": "CA", "min_diligent_attempts": 3}
    )
    svr = make_server_headers(server["id"])
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-02T09:00:00Z", "NO_ANSWER")
    out = get_request(sr["id"])
    assert out["distinct_attempt_days"] == 2, f"expected 2 distinct days, got {out['distinct_attempt_days']}"
    # 2 < 3 => POSTING rejected on diligence (state is IN_PROGRESS, so the state check passes).
    validate_error(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "POSTING", "served_at_utc": "2026-01-02T10:00:00Z"},
            svr,
        ),
        ApiErrorId.ERR_DILIGENCE_NOT_MET.value,
    )


def test_diligence_boundary_three_days_allows_posting(api):
    """PRD 3.4: substitute/posting/non-est are "permitted only once
    `distinct_attempt_days` is at least the county's `min_diligent_attempts`." At
    exactly 3 distinct days (== floor of 3) POSTING succeeds.

    Design: Difficulty/boundary_precision_check/diligence_min_attempts_boundary_on_services_endpoint
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Colusa2", "state_code": "CA", "min_diligent_attempts": 3}
    )
    svr = make_server_headers(server["id"])
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-02T09:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-03T09:00:00Z", "NO_ANSWER")
    out = get_request(sr["id"])
    assert out["distinct_attempt_days"] == 3
    service = validate_success(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "POSTING", "served_at_utc": "2026-01-03T10:00:00Z"},
            svr,
        ), 201
    )
    assert service["service_type"] == "POSTING"


def test_skiptrace_locate_empty_candidate_set_rejected(api):
    """PRD 3.7: "The successful branch — `IN_PROGRESS → LOCATED` — requires that
    `candidate_addresses` be non-empty (else `ERR_NO_CANDIDATE_ADDRESS`)".

    Design: Difficulty/boundary_precision_check/skip_trace_empty_candidate_set_boundary_on_skiptrace_state
    """
    county, server, client = setup_reference_data(
        deposit_cents=0, county_overrides={"name": "Sutter", "state_code": "CA", "min_diligent_attempts": 1}
    )
    svr = make_server_headers(server["id"])
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "4 St", "service_lat": 39.1, "service_lng": -121.6,
             "skip_trace_requested": True}, DISPATCHER
        )
    )
    st = get_success_data(api.create_skip_trace(sr["id"], {"candidate_addresses": []}, DISPATCHER))
    get_success_data(api.set_skip_trace_state(st["id"], {"to_status": "IN_PROGRESS"}, svr))
    validate_error(
        api.set_skip_trace_state(st["id"], {"to_status": "LOCATED", "located_address": "404 Nowhere"}, svr),
        ApiErrorId.ERR_NO_CANDIDATE_ADDRESS.value,
    )


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────
def test_filing_submit_requires_efile_enabled_county(api):
    """PRD 3.9: "The county's `e_file_enabled` must be true (else
    `ERR_EFILE_NOT_ENABLED`)."

    Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_efile_county_pair_filing_county
    """
    county, server, client, sr, asg, aff = setup_notarized_request(
        deposit_cents=50_000,
        county_overrides={"name": "Yuba", "state_code": "CA", "e_file_enabled": False,
                          "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2},
        notary_user_id="notary-4",
    )
    filing = create_filing(sr["id"], aff["id"], "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z")
    validate_error(
        api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER),
        ApiErrorId.ERR_EFILE_NOT_ENABLED.value,
    )
    assert get_request(sr["id"])["status"] == "SERVED"


def test_accept_requires_active_server(api):
    """PRD 3.3: "Acceptance is guarded by four checks: the server's `status` must
    be `ACTIVE` (else `ERR_SERVER_SUSPENDED`)".

    Design: Difficulty/cross_entity_state_dependency/accept_requires_server_active_pair_assignment_server
    """
    county, server, client = setup_reference_data(
        deposit_cents=0,
        county_overrides={"name": "Plumas", "state_code": "CA", "min_diligent_attempts": 1},
    )
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    get_success_data(api.set_server_state(server["id"], {"to_status": "SUSPENDED"}, ADMIN))
    validate_error(
        api.accept_assignment(asg["id"], make_server_headers(server["id"])),
        ApiErrorId.ERR_SERVER_SUSPENDED.value,
    )


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────
def test_stakeout_overlap_rejected_adjacent_allowed(api):
    """PRD 3.6: "the new window must not overlap any other non-`CANCELLED`
    stakeout for the same server, though exact adjacency — one window's end
    equalling the next window's start — is allowed because the windows are
    half-open. An overlap is rejected with `ERR_STAKEOUT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/stakeout_pairwise_halfopen_overlap_adjacent_allowed_on_server
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Modoc", "state_code": "CA", "min_diligent_attempts": 1},
        server_overrides={"full_name": "Ov Lap", "license_no": "PS-9009", "max_active_assignments": 5},
    )
    svr = make_server_headers(server["id"])
    get_success_data(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T08:00:00Z", "window_end_utc": "2026-01-02T10:00:00Z"}, svr
        )
    )
    # [09:00,11:00) overlaps [08:00,10:00) => rejected.
    validate_error(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T09:00:00Z", "window_end_utc": "2026-01-02T11:00:00Z"}, svr
        ),
        ApiErrorId.ERR_STAKEOUT_OVERLAP.value,
    )
    # [10:00,12:00) is adjacent (end==next.start) => allowed.
    adj = validate_success(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T10:00:00Z", "window_end_utc": "2026-01-02T12:00:00Z"}, svr
        ), 201
    )
    assert adj["status"] == "SCHEDULED"


def test_filing_window_aggregate_capacity_overlap_rejected(api):
    """PRD 3.9: "the half-open window from `window_start_utc` to `window_end_utc`
    may overlap strictly fewer than the county's `max_concurrent_filings` other
    `SUBMITTED` filing windows in that county ... or it is rejected with
    `ERR_FILING_WINDOW_FULL`."

    Design: Difficulty/resource_temporal_overlap/filing_window_aggregate_capacity_overlap_on_county
    """
    county = get_success_data(
        api.create_county(
            {"name": "Sierra", "state_code": "CA", "e_file_enabled": True, "min_diligent_attempts": 1,
             "filing_fee_cents": 4000, "max_concurrent_filings": 1}, ADMIN
        )
    )
    server = get_success_data(api.create_server({"full_name": "Cap City", "license_no": "PS-9100"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Rho Law", "email": "r@law.com"}, ADMIN))
    get_success_data(api.deposit(client["id"], {"amount_cents": 80000}, ADMIN))

    r1 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T09:00:00Z", "2026-01-01T09:05:00Z", "notary-5")
    f1 = create_filing(r1["aff_sr_id"], r1["aff_id"], "2026-01-05T05:00:00Z", "2026-01-05T07:00:00Z")
    get_success_data(api.set_filing_state(f1["id"], {"to_status": "SUBMITTED"}, DISPATCHER))

    r2 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T10:00:00Z", "2026-01-01T10:05:00Z", "notary-6")
    f2 = create_filing(r2["aff_sr_id"], r2["aff_id"], "2026-01-05T06:00:00Z", "2026-01-05T08:00:00Z")
    # [06:00,08:00) overlaps the SUBMITTED [05:00,07:00); cap is 1 => rejected.
    validate_error(
        api.set_filing_state(f2["id"], {"to_status": "SUBMITTED"}, DISPATCHER),
        ApiErrorId.ERR_FILING_WINDOW_FULL.value,
    )


# ─── Queue B: validations + errors ────────────────────────────────────────
def test_complete_with_insufficient_funds_rejected(api):
    """PRD 3.11: "The debit is gated on funds: if the client's
    `prepaid_balance_cents` is less than `final_fee_cents`, completion is rejected
    with `ERR_INSUFFICIENT_FUNDS` (HTTP 402) and no debit occurs."

    Design: Corner/validations/insufficient_funds_on_complete_returns_402
    """
    # FILED request, 3-page (final 7575), client never deposited (balance 0).
    county, server, client, sr, aff, filing = _filed_no_funds(api)
    sr_filed = get_request(sr["id"])
    assert sr_filed["status"] == "FILED"
    validate_error(api.complete_request(sr["id"], DISPATCHER), ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
    client_after = get_success_data(api.get_client(client["id"], DISPATCHER))
    assert client_after["prepaid_balance_cents"] == 0, "balance must be unchanged on failed debit"


def _filed_no_funds(api):
    county, server, client, sr, asg, aff, filing = setup_filed_request(
        deposit_cents=0,
        county_overrides={"name": "Nevada", "state_code": "CA", "e_file_enabled": True,
                          "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2},
        notary_user_id="notary-nf",
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
    )
    return county, server, client, sr, aff, filing


def test_offer_outside_territory_rejected(api):
    """PRD 3.3: "The offered server must cover the request's county through an
    existing ServerTerritory row, or the offer is rejected with
    `ERR_OUTSIDE_TERRITORY`."

    Design: Corner/validations/offer_outside_territory_returns_outside_territory
    """
    county_a = get_success_data(api.create_county({"name": "CountyA", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    county_b = get_success_data(api.create_county({"name": "CountyB", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    server = get_success_data(api.create_server({"full_name": "Terr Itory", "license_no": "PS-TER1"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county_a["id"]}, ADMIN))  # covers A only.
    client = get_success_data(api.create_client({"firm_name": "Tr Law", "email": "tr@law.com"}, ADMIN))
    sr = create_submitted_request(client["id"], county_b["id"])  # request is in county B.
    validate_error(
        api.offer_assignment(
            sr["id"], {"server_id": server["id"], "expected_service_request_version": sr["version"]}, DISPATCHER
        ),
        ApiErrorId.ERR_OUTSIDE_TERRITORY.value,
    )


def test_accept_server_at_capacity_rejected(api):
    """PRD 3.3: "the server's `active_assignment_count` must be strictly less than
    its `max_active_assignments` (else `ERR_SERVER_AT_CAPACITY`)".

    Design: Corner/validations/server_at_capacity_accept_returns_error
    """
    county = get_success_data(api.create_county({"name": "Cap County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    server = get_success_data(api.create_server({"full_name": "At Cap", "license_no": "PS-CAP1", "max_active_assignments": 1}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Cp Law", "email": "cp@law.com"}, ADMIN))
    svr = make_server_headers(server["id"])

    sr1 = create_submitted_request(client["id"], county["id"], recipient_name="R1")
    asg1 = offer_to_server(sr1["id"], server["id"], sr1["version"])
    get_success_data(api.accept_assignment(asg1["id"], svr))  # now at capacity (1/1).

    sr2 = create_submitted_request(client["id"], county["id"], recipient_name="R2")
    asg2 = offer_to_server(sr2["id"], server["id"], sr2["version"])
    validate_error(api.accept_assignment(asg2["id"], svr), ApiErrorId.ERR_SERVER_AT_CAPACITY.value)


def test_suspended_client_submit_rejected(api):
    """PRD 3.2: "the owning client's `status` must be `ACTIVE`, or the submit is
    rejected with `ERR_CLIENT_SUSPENDED`".

    Design: Corner/validations/client_suspended_submit_returns_error
    """
    county = get_success_data(api.create_county({"name": "Susp County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Sp Law", "email": "sp@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 36.0, "service_lng": -119.0}, DISPATCHER
        )
    )
    get_success_data(api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 1}, DISPATCHER))
    get_success_data(api.set_client_state(client["id"], {"to_status": "SUSPENDED"}, ADMIN))
    validate_error(api.submit_request(sr["id"], DISPATCHER), ApiErrorId.ERR_CLIENT_SUSPENDED.value)


def test_accept_superseded_offer_rejected(api):
    """PRD 3.3: "any prior `OFFERED` assignment for the same request is superseded
    — its status becomes `REASSIGNED` and its `superseded` flag becomes true"; and
    acceptance requires "the assignment must not be superseded (else
    `ERR_ASSIGNMENT_SUPERSEDED`)."

    Design: Corner/errors/error_assignment_superseded_on_accept_stale_offer
    """
    county = get_success_data(api.create_county({"name": "Sup County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    s1 = get_success_data(api.create_server({"full_name": "S One", "license_no": "PS-SUP1"}, ADMIN))
    s2 = get_success_data(api.create_server({"full_name": "S Two", "license_no": "PS-SUP2"}, ADMIN))
    get_success_data(api.create_territory(s1["id"], {"county_id": county["id"]}, ADMIN))
    get_success_data(api.create_territory(s2["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Su Law", "email": "su@law.com"}, ADMIN))
    sr = create_submitted_request(client["id"], county["id"])
    asg1 = offer_to_server(sr["id"], s1["id"], sr["version"])  # advances version.
    sr_v2 = get_request(sr["id"])["version"]
    offer_to_server(sr["id"], s2["id"], sr_v2)  # supersedes asg1.
    # Accepting the superseded first offer is rejected.
    validate_error(api.accept_assignment(asg1["id"], make_server_headers(s1["id"])), ApiErrorId.ERR_ASSIGNMENT_SUPERSEDED.value)
    asg1_after = validate_success(api.get_assignment(asg1["id"], DISPATCHER))
    assert asg1_after["superseded"] is True


def test_rush_service_after_deadline_rejected(api):
    """PRD 3.5: "for a `rush` request, the `served_at_utc` must be on or before the
    request's `deadline_utc` (the boundary is inclusive — equality is allowed), or
    it is rejected with `ERR_DEADLINE_PASSED`."

    Design: Corner/state_machines/rush_service_after_deadline_returns_deadline_passed
    """
    # RUSH request at default clock 2026-01-01T00:00:00Z => deadline 2026-01-03T00:00:00Z.
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Placer", "state_code": "CA", "min_diligent_attempts": 1},
        rush=True,
    )
    svr = make_server_headers(server["id"])
    log_attempt(asg["id"], server["id"], "2026-01-04T09:00:00Z", "CONTACT_MADE")
    # served_at 2026-01-04 is strictly after the 2026-01-03 deadline.
    validate_error(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-04T09:05:00Z"},
            svr,
        ),
        ApiErrorId.ERR_DEADLINE_PASSED.value,
    )


def test_skiptrace_locate_address_not_in_candidates_rejected(api):
    """PRD 3.7: "the request body supply a `located_address` that is a member of
    `candidate_addresses` (else `ERR_ADDRESS_NOT_CANDIDATE`)."

    Design: Corner/state_machines/skiptrace_located_address_not_candidate_returns_error
    """
    county, server, client = setup_reference_data(
        deposit_cents=0, county_overrides={"name": "Siskiyou", "state_code": "CA", "min_diligent_attempts": 1}
    )
    svr = make_server_headers(server["id"])
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "x", "service_lat": 41.7, "service_lng": -122.6, "skip_trace_requested": True}, DISPATCHER
        )
    )
    st = get_success_data(api.create_skip_trace(sr["id"], {"candidate_addresses": ["A St"]}, DISPATCHER))
    get_success_data(api.set_skip_trace_state(st["id"], {"to_status": "IN_PROGRESS"}, svr))
    validate_error(
        api.set_skip_trace_state(st["id"], {"to_status": "LOCATED", "located_address": "B St"}, svr),
        ApiErrorId.ERR_ADDRESS_NOT_CANDIDATE.value,
    )


# ─── Queue A second-coverage tests (≥2 per difficulty instance) ───────────
def test_substitute_service_in_submitted_state_also_invalid_state(api):
    """PRD 2.6: the state check at precedence six fires before "the
    domain-specific business rules ... diligence". SUBSTITUTE service (which would
    otherwise hit diligence) on a SUBMITTED (not IN_PROGRESS) request still yields
    ERR_INVALID_STATE first.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_diligence_state_vs_business_safety
    """
    county, server, client = setup_reference_data(
        deposit_cents=0,
        county_overrides={"name": "Butte2", "state_code": "CA", "min_diligent_attempts": 3},
    )
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    validate_error(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "SUBSTITUTE", "served_at_utc": "2026-01-02T09:00:00Z",
             "recipient_relation": "spouse"},
            make_server_headers(server["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_window_full_alone_rejects_when_affidavit_notarized(api):
    """PRD 3.9: "the filing's e-file window must respect the county's aggregate
    concurrency cap ... or it is rejected with `ERR_FILING_WINDOW_FULL`." With the
    affidavit properly NOTARIZED (so the earlier check passes), the window-capacity
    check becomes the operative rejection — the complementary half of the
    precedence pair.

    Design: Difficulty/priority_pair_validation_conflict/notarized_beats_window_full_business_safety_vs_business_temporal
    """
    county = get_success_data(
        api.create_county(
            {"name": "Tehama2", "state_code": "CA", "e_file_enabled": True,
             "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 1}, ADMIN
        )
    )
    server = get_success_data(api.create_server({"full_name": "Win2", "license_no": "PS-6101"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Lam2 Law", "email": "l2@law.com"}, ADMIN))
    get_success_data(api.deposit(client["id"], {"amount_cents": 80000}, ADMIN))

    r1 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T09:00:00Z", "2026-01-01T09:05:00Z", "notary-a")
    f1 = create_filing(r1["aff_sr_id"], r1["aff_id"], "2026-01-05T00:00:00Z", "2026-01-05T02:00:00Z")
    get_success_data(api.set_filing_state(f1["id"], {"to_status": "SUBMITTED"}, DISPATCHER))

    r2 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T10:00:00Z", "2026-01-01T10:05:00Z", "notary-b")
    f2 = create_filing(r2["aff_sr_id"], r2["aff_id"], "2026-01-05T01:00:00Z", "2026-01-05T03:00:00Z")
    # f2's affidavit IS notarized; only the window cap (1) is breached.
    validate_error(
        api.set_filing_state(f2["id"], {"to_status": "SUBMITTED"}, DISPATCHER),
        ApiErrorId.ERR_FILING_WINDOW_FULL.value,
    )


def test_skiptrace_locate_with_one_candidate_succeeds(api):
    """PRD 3.7: LOCATED "requires that `candidate_addresses` be non-empty" and a
    member `located_address`. The positive boundary: exactly one candidate that
    matches succeeds and sets located_address.

    Design: Difficulty/boundary_precision_check/skip_trace_empty_candidate_set_boundary_on_skiptrace_state
    """
    county, server, client = setup_reference_data(
        deposit_cents=0, county_overrides={"name": "Sutter2", "state_code": "CA", "min_diligent_attempts": 1}
    )
    svr = make_server_headers(server["id"])
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "4 St", "service_lat": 39.1, "service_lng": -121.6, "skip_trace_requested": True}, DISPATCHER
        )
    )
    st = get_success_data(api.create_skip_trace(sr["id"], {"candidate_addresses": ["7 Found Way"]}, DISPATCHER))
    get_success_data(api.set_skip_trace_state(st["id"], {"to_status": "IN_PROGRESS"}, svr))
    located = validate_success(
        api.set_skip_trace_state(st["id"], {"to_status": "LOCATED", "located_address": "7 Found Way"}, svr), 200
    )
    assert located["status"] == "LOCATED"
    assert located["located_address"] == "7 Found Way"


def test_filing_submit_succeeds_when_efile_enabled(api):
    """PRD 3.9: when "The county's `e_file_enabled` must be true" is satisfied (and
    affidavit notarized, window free), the filing moves PENDING → SUBMITTED. The
    positive complement to the ERR_EFILE_NOT_ENABLED gate.

    Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_efile_county_pair_filing_county
    """
    county, server, client, sr, asg, aff = setup_notarized_request(
        deposit_cents=50_000,
        county_overrides={"name": "YubaOK", "state_code": "CA", "e_file_enabled": True,
                          "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2},
        notary_user_id="notary-c",
    )
    filing = create_filing(sr["id"], aff["id"], "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z")
    submitted = validate_success(api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER), 200)
    assert submitted["status"] == "SUBMITTED"


def test_accept_succeeds_after_server_reactivated(api):
    """PRD 3.3: "the server's `status` must be `ACTIVE`" for accept. An ACTIVE
    server passes the gate. The positive complement to ERR_SERVER_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/accept_requires_server_active_pair_assignment_server
    """
    county, server, client = setup_reference_data(
        deposit_cents=0,
        county_overrides={"name": "Plumas2", "state_code": "CA", "min_diligent_attempts": 1},
    )
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    get_success_data(api.set_server_state(server["id"], {"to_status": "SUSPENDED"}, ADMIN))
    get_success_data(api.set_server_state(server["id"], {"to_status": "ACTIVE"}, ADMIN))
    accepted = validate_success(api.accept_assignment(asg["id"], make_server_headers(server["id"])), 200)
    assert accepted["status"] == "ACTIVE"


def test_stakeout_overlap_allowed_against_cancelled_stakeout(api):
    """PRD 3.6: "the new window must not overlap any other non-`CANCELLED` stakeout
    for the same server". A window overlapping a previously CANCELLED stakeout is
    allowed, because CANCELLED stakeouts are excluded from the overlap set.

    Design: Difficulty/resource_temporal_overlap/stakeout_pairwise_halfopen_overlap_adjacent_allowed_on_server
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Modoc2", "state_code": "CA", "min_diligent_attempts": 1},
        server_overrides={"full_name": "Ov Lap2", "license_no": "PS-9010", "max_active_assignments": 5},
    )
    svr = make_server_headers(server["id"])
    stk1 = get_success_data(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T08:00:00Z", "window_end_utc": "2026-01-02T10:00:00Z"}, svr
        )
    )
    get_success_data(api.set_stakeout_state(stk1["id"], {"to_status": "CANCELLED"}, svr))
    # Overlapping window is now allowed since the prior stakeout is CANCELLED.
    stk2 = validate_success(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T09:00:00Z", "window_end_utc": "2026-01-02T11:00:00Z"}, svr
        ), 201
    )
    assert stk2["status"] == "SCHEDULED"


def test_filing_window_non_overlapping_accepted_under_capacity(api):
    """PRD 3.9: a window "may overlap strictly fewer than the county's
    `max_concurrent_filings` other `SUBMITTED` filing windows". A disjoint window
    overlaps zero others (0 < cap of 1) and is accepted.

    Design: Difficulty/resource_temporal_overlap/filing_window_aggregate_capacity_overlap_on_county
    """
    county = get_success_data(
        api.create_county(
            {"name": "Sierra2", "state_code": "CA", "e_file_enabled": True, "min_diligent_attempts": 1,
             "filing_fee_cents": 4000, "max_concurrent_filings": 1}, ADMIN
        )
    )
    server = get_success_data(api.create_server({"full_name": "Cap City2", "license_no": "PS-9101"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Rho2 Law", "email": "r2@law.com"}, ADMIN))
    get_success_data(api.deposit(client["id"], {"amount_cents": 80000}, ADMIN))

    r1 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T09:00:00Z", "2026-01-01T09:05:00Z", "notary-d")
    f1 = create_filing(r1["aff_sr_id"], r1["aff_id"], "2026-01-05T05:00:00Z", "2026-01-05T07:00:00Z")
    get_success_data(api.set_filing_state(f1["id"], {"to_status": "SUBMITTED"}, DISPATCHER))

    r2 = _serve_and_notarize(api, client["id"], county["id"], server["id"], "2026-01-01T10:00:00Z", "2026-01-01T10:05:00Z", "notary-e")
    # Disjoint window [09:00,10:00) overlaps no SUBMITTED window.
    f2 = create_filing(r2["aff_sr_id"], r2["aff_id"], "2026-01-05T09:00:00Z", "2026-01-05T10:00:00Z")
    submitted = validate_success(api.set_filing_state(f2["id"], {"to_status": "SUBMITTED"}, DISPATCHER), 200)
    assert submitted["status"] == "SUBMITTED"
