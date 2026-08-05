"""Renewal petitions: weighted-support verification, the approve/reject fork, four-eyes
segregation of duties, signature uniqueness/membership, and the circulation deadline."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, new_bid, add_parcel, activate,
    setup_petition_submitted, setup_petition_verified,
    make_property_owner_headers, make_board_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]


def test_verify_approve_reactivates_district(api):
    """PRD §3.6: "An approval transitions the petition VERIFIED → APPROVED, extends the
    district's authorization_expires_at by renewal_term_months, and returns the district
    RENEWAL_PENDING → ACTIVE."

    Design: Difficulty/non_linear_state_machine/petition_verify_fork_approve_vs_reject
    """
    ctx = setup_petition_verified(verifier_id="board-verifier")
    petition = validate_success(api.vote_petition(
        ctx["petition"]["id"], {"decision": "APPROVE"}, make_board_member_headers("board-voter")))
    assert petition["status"] == "APPROVED"
    bid = validate_success(api.get_bid(ctx["bid"]["id"], ADMIN))
    assert bid["status"] == "ACTIVE"


def test_verify_reject_expires_district(api):
    """PRD §3.6: "A rejection transitions the petition VERIFIED → REJECTED and transitions
    the district RENEWAL_PENDING → EXPIRED, a terminal state in which the district can no
    longer adopt new budgets or open petitions."

    Design: Difficulty/non_linear_state_machine/petition_verify_fork_approve_vs_reject
    """
    ctx = setup_petition_verified(verifier_id="board-verifier")
    petition = validate_success(api.vote_petition(
        ctx["petition"]["id"], {"decision": "REJECT"}, make_board_member_headers("board-voter")))
    assert petition["status"] == "REJECTED"
    bid = validate_success(api.get_bid(ctx["bid"]["id"], ADMIN))
    assert bid["status"] == "EXPIRED"


def test_support_exactly_at_threshold_verifies(api):
    """PRD §3.6: "If the fraction is at least the required_threshold_pct, the petition
    transitions SUBMITTED → VERIFIED".

    Design: Difficulty/boundary_precision_check/petition_support_at_exactly_threshold
    """
    ctx = setup_petition_submitted(support=True, threshold=0.50, sign=True)
    petition = validate_success(api.verify_petition(
        ctx["petition"]["id"], make_board_member_headers("board-verifier")))
    assert petition["status"] == "VERIFIED"


def test_support_ratio_computed_to_exact_half(api):
    """PRD §3.6: "The weighted_support_pct is the support weight divided by the total
    weight, carried to four decimals".

    Design: Difficulty/boundary_precision_check/petition_support_at_exactly_threshold
    """
    ctx = setup_petition_submitted(support=True, threshold=0.50, sign=True)
    petition = validate_success(api.verify_petition(
        ctx["petition"]["id"], make_board_member_headers("board-verifier")))
    # support 10000000 of total 20000000 = 0.5 exactly
    assert petition["weighted_support_pct"] == 0.5


def test_support_below_threshold_fails_petition(api):
    """PRD §3.6: "if it falls short, the petition transitions SUBMITTED → FAILED and the
    district transitions RENEWAL_PENDING → EXPIRED."

    Design: Corner/calculations/petition_below_threshold_fails
    """
    ctx = setup_petition_submitted(support=False, threshold=0.50, sign=True)
    petition = validate_success(api.verify_petition(
        ctx["petition"]["id"], make_board_member_headers("board-1")))
    assert petition["status"] == "FAILED"
    assert petition["weighted_support_pct"] == 0


def test_vote_by_verifier_rejected_for_segregation_of_duties(api):
    """PRD §3.6: "the voting member's X-User-ID must differ from the petition's
    verified_by_user_id; a vote cast by the same member who verified is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/errors/sod_vote_same_user_rejected
    """
    ctx = setup_petition_verified(verifier_id="board-1")
    resp = api.vote_petition(
        ctx["petition"]["id"], {"decision": "APPROVE"}, make_board_member_headers("board-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def _active_bid_with_circulating_petition(api, deadline="2027-06-20T00:00:00Z"):
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid()
    parcel = add_parcel(bid["id"], apn="PA-1")
    activate(bid["id"])
    petition = get_success_data(api.create_renewal_petition(
        bid["id"], {"circulation_deadline": deadline}, ADMIN))
    return bid, parcel, petition


def test_duplicate_signature_rejected(api):
    """PRD §3.6: "A parcel may sign a given petition at most once — a repeat is rejected
    with ERR_ALREADY_SIGNED".

    Design: Corner/validations/already_signed_rejected
    """
    bid, parcel, petition = _active_bid_with_circulating_petition(api)
    owner = make_property_owner_headers(parcel["id"])
    get_success_data(api.create_signature(petition["id"], {"parcel_id": parcel["id"], "support": True}, owner))
    resp = api.create_signature(petition["id"], {"parcel_id": parcel["id"], "support": True}, owner)
    validate_error(resp, ApiErrorId.ERR_ALREADY_SIGNED.value)


def test_signature_from_foreign_parcel_rejected(api):
    """PRD §3.6: "the signing parcel must be an ACTIVE parcel of the petition's district,
    else ERR_PARCEL_NOT_IN_DISTRICT."

    Design: Corner/validations/signature_parcel_not_in_district_rejected
    """
    set_clock("2027-06-01T00:00:00Z")
    bid_a = new_bid(name="A BID")
    add_parcel(bid_a["id"], apn="A-1")
    activate(bid_a["id"])
    petition = get_success_data(api.create_renewal_petition(
        bid_a["id"], {"circulation_deadline": "2027-06-20T00:00:00Z"}, ADMIN))
    bid_b = new_bid(name="B BID")
    pb = add_parcel(bid_b["id"], apn="B-1", owner_name="O2")
    owner_b = make_property_owner_headers(pb["id"])
    resp = api.create_signature(petition["id"], {"parcel_id": pb["id"], "support": True}, owner_b)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_IN_DISTRICT.value)


def test_signature_after_deadline_rejected(api):
    """PRD §3.6: "Signatures are accepted only while the logical clock is strictly before
    the circulation_deadline; at or after it, both further signing and submission are
    rejected with ERR_PETITION_DEADLINE_PASSED."

    Design: Corner/validations/petition_deadline_passed_rejected
    """
    bid, parcel, petition = _active_bid_with_circulating_petition(api, deadline="2027-06-10T00:00:00Z")
    owner = make_property_owner_headers(parcel["id"])
    set_clock("2027-06-15T00:00:00Z")
    resp = api.create_signature(petition["id"], {"parcel_id": parcel["id"], "support": True}, owner)
    validate_error(resp, ApiErrorId.ERR_PETITION_DEADLINE_PASSED.value)
