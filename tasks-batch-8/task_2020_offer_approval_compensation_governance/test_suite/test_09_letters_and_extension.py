"""Offer letters, extension, expiry, declination, and the candidate's answer."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_candidate_headers, event_types,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, create_draft_offer, create_approved_offer,
    create_lettered_offer, create_extended_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def test_letter_regeneration_supersedes_prior(api):
    """PRD §3.6: "Regeneration from `LETTER_GENERATED` supersedes the currently
    `GENERATED` letter (`LETTER_SUPERSEDED`) and issues a fresh `GENERATED`
    letter with the next `sequence` and the offer's then-current version
    pinned."

    Design: Corner/state_machines/letter_regeneration_supersedes_prior
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand LG")
    offer, letter1 = create_lettered_offer(req, cand, REC, base_cents=18000000)
    letter2 = validate_success(api.create_offer_letter(offer["id"], REC), expected_status=201)
    assert letter2["sequence"] == 2
    assert letter2["status"] == "GENERATED"
    assert letter2["pinned_offer_version"] == letter1["pinned_offer_version"]
    letters = validate_success(api.list_offer_letters(offer["id"], REC))
    assert [l["sequence"] for l in letters] == [1, 2]
    assert letters[0]["status"] == "SUPERSEDED"
    assert letters[1]["status"] == "GENERATED"
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "LETTER_GENERATED"
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert types.index("LETTER_SUPERSEDED") < types.index("LETTER_GENERATED", types.index("LETTER_SUPERSEDED"))


def test_expiry_computation_literal(api):
    """PRD §2.4: "At server startup the logical clock is exactly
    `2026-08-01T00:00:00Z`."
    PRD §3.6: "Extension sets `expires_at` to the logical clock plus ten days".

    Design: Corner/calculations/expiry_computation_literal
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand EX")
    offer = create_extended_offer(req, cand, REC, base_cents=18000000)
    assert offer["expires_at"] == "2026-08-11T00:00:00Z"


def test_expiration_exactly_at_expires_at_boundary(api):
    """PRD §3.6: "The boundary is exact: a call landing precisely at
    `expires_at` expires; one second earlier it would have succeeded."

    Design: Difficulty/boundary_precision_check/expiration_exactly_at_expires_at
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand T")
    offer = create_extended_offer(req, cand, REC, base_cents=20000000)
    assert offer["expires_at"] == "2026-08-11T00:00:00Z"
    get_success_data(api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, ADMIN))
    resp = api.accept_offer(offer["id"], make_candidate_headers(cand["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)


def test_expired_offer_persisted_with_event(api):
    """PRD §3.6: "any state-changing call — or even a read of the offer — that
    finds the clock at or past `expires_at` first persists the offer as
    `EXPIRED` with its full side effects ... and the `EXPIRED` event appended —
    and a state-changing call is then rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/boundary_precision_check/expiration_exactly_at_expires_at
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand T2")
    offer = create_extended_offer(req, cand, REC, base_cents=20000000)
    get_success_data(api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, ADMIN))
    resp = api.accept_offer(offer["id"], make_candidate_headers(cand["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXPIRED"
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert "EXPIRED" in types


def test_decline_missing_reason_returns_422(api):
    """PRD §3.6: "Declination requires a `reason` drawn from `COMPETING_OFFER`,
    `COMPENSATION`, `ROLE_SCOPE`, `LOCATION`, `BENEFITS`, `PERSONAL`, `TIMING`,
    or `OTHER`, with an optional free-text `detail`; a missing or out-of-enum
    reason is rejected with `ERR_DECLINATION_REASON_REQUIRED`."

    Design: Corner/validations/decline_missing_reason_returns_422
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand DR")
    offer = create_extended_offer(req, cand, REC, base_cents=18000000)
    resp = api.decline_offer(offer["id"], {}, make_candidate_headers(cand["id"]))
    validate_error(resp, ApiErrorId.ERR_DECLINATION_REASON_REQUIRED)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXTENDED"


def test_declined_terminal_lockdown(api):
    """PRD §3.9: "`DECLINED`, `EXPIRED`, `RESCINDED`, and `WITHDRAWN` are the
    offer's terminal states; nothing leaves them."
    PRD §2.10: "offer actions illegal from the offer's current status draw
    `ERR_INVALID_OFFER_STATE`" (state tier 6 precedes OCC tier 7).

    Design: Corner/state_machines/declined_terminal_lockdown
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand DL")
    offer = create_extended_offer(req, cand, REC, base_cents=18000000)
    declined = validate_success(
        api.decline_offer(offer["id"], {"reason": "PERSONAL", "detail": "family relocation"},
                          make_candidate_headers(cand["id"]))
    )
    assert declined["status"] == "DECLINED"
    assert declined["declination_reason"] == "PERSONAL"
    dv = declined["version"]
    e_accept = api.accept_offer(offer["id"], make_candidate_headers(cand["id"]))
    validate_error(e_accept, ApiErrorId.ERR_INVALID_OFFER_STATE)
    e_patch = api.patch_offer(offer["id"], {"expected_offer_version": dv, "base_cents": 17000000}, REC)
    validate_error(e_patch, ApiErrorId.ERR_INVALID_OFFER_STATE)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["declination_reason"] == "PERSONAL"


def test_candidate_single_active_offer_occupation_blocks_second_extend(api):
    """PRD §3.6: "only when the candidate has no other offer in `EXTENDED`,
    `COUNTERED`, or `ACCEPTED`, else `ERR_CANDIDATE_ACTIVE_OFFER_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/candidate_single_active_offer_occupation
    """
    req1 = create_open_requisition(HM, title="Sr Eng 1")
    req2 = create_open_requisition(HM, title="Sr Eng 2")
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand W")
    offer1 = create_extended_offer(req1, cand, REC, base_cents=19000000)
    offer2, _ = create_lettered_offer(req2, cand, REC, base_cents=19000000)
    resp = api.extend_offer(offer2["id"], REC)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_ACTIVE_OFFER_EXISTS)
    after2 = validate_success(api.get_offer(offer2["id"], REC))
    assert after2["status"] == "LETTER_GENERATED"


def test_candidate_single_active_offer_freed_by_decline(api):
    """PRD §3.6: "only when the candidate has no other offer in `EXTENDED`,
    `COUNTERED`, or `ACCEPTED`, else `ERR_CANDIDATE_ACTIVE_OFFER_EXISTS`" — once
    the first offer leaves the occupied set (DECLINED is terminal per §3.9),
    the second extension succeeds.

    Design: Difficulty/resource_temporal_overlap/candidate_single_active_offer_occupation
    """
    req1 = create_open_requisition(HM, title="Sr Eng 1")
    req2 = create_open_requisition(HM, title="Sr Eng 2")
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand W")
    offer1 = create_extended_offer(req1, cand, REC, base_cents=19000000)
    offer2, _ = create_lettered_offer(req2, cand, REC, base_cents=19000000)
    validate_error(api.extend_offer(offer2["id"], REC), ApiErrorId.ERR_CANDIDATE_ACTIVE_OFFER_EXISTS)
    declined = validate_success(
        api.decline_offer(offer1["id"], {"reason": "COMPETING_OFFER"}, make_candidate_headers(cand["id"]))
    )
    assert declined["status"] == "DECLINED"
    assert declined["declination_reason"] == "COMPETING_OFFER"
    extended2 = validate_success(api.extend_offer(offer2["id"], REC))
    assert extended2["status"] == "EXTENDED"
