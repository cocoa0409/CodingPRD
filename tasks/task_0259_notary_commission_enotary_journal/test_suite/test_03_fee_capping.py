"""Session completion: fee capping under both regimes, surcharge cap, the
waterfall distribution, the zero-notarized boundary, and session window overlap.

Covers the dual-variant fee difficulty pair, the AGGREGATE waterfall combinatorial
instance, the surcharge-cap corner, the empty-set completion boundary, and the
half-open session-window temporal overlap instance.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_notary_headers,
    create_session_payload,
    TEST_USERS,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]

# Jurisdiction config reused across fee tests: ACK cap 1000, JURAT cap 600,
# aggregate session cap 1200, surcharge cap 2500.
FEE_SCHEDULES = {"ACKNOWLEDGMENT": 1000, "JURAT": 600}


def _active_fee_notary(email):
    ctx = th.setup_active_notary(
        jurisdiction_overrides={
            "state_code": "TX",
            "session_act_fee_cap_cents": 1200,
            "ron_surcharge_cap_cents": 2500,
        },
        notary_overrides={"enotary_requested": True, "email": email},
        fee_schedules=FEE_SCHEDULES,
    )
    return ctx["notary"]


# ===========================================================================
# dual_variant_calc: PER_ACT vs AGGREGATE on identical documents
# ===========================================================================
def test_per_act_basis_caps_each_act_independently(api):
    """PRD §3.6: "Under the `PER_ACT` regime, each notarized document is capped
    independently: its `capped_fee_cents` is the smaller of its own
    `requested_fee_cents` and the `max_act_fee_cents` from the fee schedule
    matching the session's `jurisdiction_id` and that document's `act_type`. The
    session's `act_fees_total_cents` is then the sum of all those per-document
    capped fees."
    PRD §3.6: "The session's `session_total_fee_cents` is then the sum of its
    `act_fees_total_cents` and its `surcharge_charged_cents`."

    Design: Difficulty/dual_variant_calc/session_fee_per_act_vs_aggregate_cap
    """
    notary = _active_fee_notary("n1-peract@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-06-11T15:00:00Z", "2026-06-11T16:00:00Z",
        documents=[("ACKNOWLEDGMENT", 1500), ("JURAT", 800)],
        session_overrides={"requested_surcharge_cents": 4000, "fee_basis": "PER_ACT"},
    )
    sess = result["session"]
    # ACK min(1500,1000)=1000; JURAT min(800,600)=600; total 1600; surcharge cap 2500
    assert sess["act_fees_total_cents"] == 1600
    assert sess["session_total_fee_cents"] == 4100


def test_aggregate_basis_caps_session_total(api):
    """PRD §3.6: "Under the `AGGREGATE` regime, the cap is applied to the whole
    session rather than act by act. First the raw total is formed as the sum of
    every notarized document's `requested_fee_cents`. The session's
    `act_fees_total_cents` is the smaller of that raw total and the jurisdiction's
    `session_act_fee_cap_cents`."
    PRD §3.6: "The session's `session_total_fee_cents` is then the sum of its
    `act_fees_total_cents` and its `surcharge_charged_cents`."

    Design: Difficulty/dual_variant_calc/session_fee_per_act_vs_aggregate_cap
    """
    notary = _active_fee_notary("n1-agg@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z",
        documents=[("ACKNOWLEDGMENT", 1500), ("JURAT", 800)],
        session_overrides={"requested_surcharge_cents": 4000, "fee_basis": "AGGREGATE"},
    )
    sess = result["session"]
    # raw 2300; min(2300, cap 1200)=1200; surcharge cap 2500; total 3700
    assert sess["act_fees_total_cents"] == 1200
    assert sess["session_total_fee_cents"] == 3700


# ===========================================================================
# combinatorial_formula: AGGREGATE per-document waterfall
# ===========================================================================
def test_aggregate_waterfall_first_doc_absorbs_then_zero(api):
    """PRD §3.6: "The capped total is then distributed back across the documents as
    a waterfall, walking the notarized documents in `created_at` ascending order: a
    running remainder begins at the session's `act_fees_total_cents`, and for each
    document in turn its `capped_fee_cents` is set to the smaller of its
    `requested_fee_cents` and the current remainder, after which the remainder is
    reduced by the amount just assigned. Documents reached after the remainder is
    exhausted therefore receive a capped fee of 0."

    Design: Difficulty/combinatorial_formula/aggregate_waterfall_nonlinear_share
    """
    notary = _active_fee_notary("n-waterfall@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z",
        documents=[("ACKNOWLEDGMENT", 1500), ("JURAT", 800)],
        session_overrides={"requested_surcharge_cents": 0, "fee_basis": "AGGREGATE"},
    )
    sess = result["session"]
    d1, d2 = result["documents"]
    # cap 1200; d1 min(1500,1200)=1200 remainder->0; d2 min(800,0)=0
    assert d1["capped_fee_cents"] == 1200
    assert d2["capped_fee_cents"] == 0
    assert sess["act_fees_total_cents"] == 1200
    assert sess["session_total_fee_cents"] == 1200


def test_aggregate_waterfall_total_equals_session_cap(api):
    """PRD §3.6: "The session's `act_fees_total_cents` is the smaller of that raw
    total and the jurisdiction's `session_act_fee_cap_cents`."
    PRD §3.6: "Documents reached after the remainder is exhausted therefore receive
    a capped fee of 0."

    Design: Difficulty/combinatorial_formula/aggregate_waterfall_nonlinear_share
    """
    notary = _active_fee_notary("n-waterfall2@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-06-12T11:00:00Z", "2026-06-12T12:00:00Z",
        documents=[("ACKNOWLEDGMENT", 1500), ("JURAT", 800)],
        session_overrides={"requested_surcharge_cents": 0, "fee_basis": "AGGREGATE"},
    )
    d1, d2 = result["documents"]
    # per-document shares must sum to act_fees_total_cents == cap 1200
    assert d1["capped_fee_cents"] + d2["capped_fee_cents"] == result["session"]["act_fees_total_cents"]
    assert result["session"]["act_fees_total_cents"] == 1200


# ===========================================================================
# Corner: surcharge capped at jurisdiction surcharge cap
# ===========================================================================
def test_surcharge_capped_at_jurisdiction_surcharge_cap(api):
    """PRD §3.6: "Independently of the regime, the session's
    `surcharge_charged_cents` is set to the smaller of the session's
    `requested_surcharge_cents` and the jurisdiction's `ron_surcharge_cap_cents`.
    The session's `session_total_fee_cents` is then the sum of its
    `act_fees_total_cents` and its `surcharge_charged_cents`."

    Design: Corner/calculations/surcharge_capped_at_jurisdiction_ron_surcharge_cap
    """
    notary = _active_fee_notary("sur@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-07-06T09:00:00Z", "2026-07-06T10:00:00Z",
        documents=[("ACKNOWLEDGMENT", 800)],
        session_overrides={"requested_surcharge_cents": 4000, "fee_basis": "PER_ACT"},
    )
    sess = result["session"]
    # ACK min(800,1000)=800; surcharge min(4000,2500)=2500; total 3300
    assert sess["surcharge_charged_cents"] == 2500
    assert sess["act_fees_total_cents"] == 800
    assert sess["session_total_fee_cents"] == 3300


# ===========================================================================
# boundary_precision_check: complete with zero notarized documents
# ===========================================================================
def test_complete_session_with_zero_notarized_returns_no_notarized_document(api):
    """PRD §3.6: "Completion requires the session to be `ACTIVE` (else
    `ERR_INVALID_STATE`) and requires that at least one document in the session
    reached `NOTARIZED`; a session with zero notarized documents cannot be
    completed and is rejected with `ERR_NO_NOTARIZED_DOCUMENT`."

    Design: Difficulty/boundary_precision_check/complete_session_with_zero_notarized_documents_empty_set
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nb2@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    built = th.setup_session_to_active(
        notary["id"], "2026-06-17T09:00:00Z", "2026-06-17T10:00:00Z",
        documents=[("JURAT", 400)],
    )
    sess = built["session"]
    doc = built["documents"][0]
    # refuse the only document so NOTARIZED count is zero
    validate_success(api.refuse_document(sess["id"], doc["id"], hdr))
    resp = api.complete_session(sess["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_NO_NOTARIZED_DOCUMENT.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "ACTIVE"


def test_complete_session_with_one_notarized_document_succeeds(api):
    """PRD §3.6: "Completion requires the session to be `ACTIVE` (else
    `ERR_INVALID_STATE`) and requires that at least one document in the session
    reached `NOTARIZED`; a session with zero notarized documents cannot be
    completed and is rejected with `ERR_NO_NOTARIZED_DOCUMENT`."
    PRD §3.6: "The transition moves the session to the terminal `COMPLETED` status"

    Design: Difficulty/boundary_precision_check/complete_session_with_zero_notarized_documents_empty_set
    """
    notary = _active_fee_notary("nb2ok@x.com")
    result = th.setup_completed_session(
        notary["id"], "2026-06-17T11:00:00Z", "2026-06-17T12:00:00Z",
        documents=[("JURAT", 400)],
        session_overrides={"fee_basis": "PER_ACT"},
    )
    assert result["session"]["status"] == "COMPLETED"


# ===========================================================================
# resource_temporal_overlap: session half-open window
# ===========================================================================
def test_session_window_overlap_rejected(api):
    """PRD §3.4: "Two half-open windows overlap when the first window's start is
    strictly before the second's end and the second window's start is strictly
    before the first's end. ... Any genuine overlap rejects the creation with
    `ERR_SESSION_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_half_open_overlap_rejected_adjacent_allowed
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nto1@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    th.create_session(notary["id"], "2026-06-20T09:00:00Z", "2026-06-20T10:00:00Z")
    overlap = create_session_payload(notary["id"], "2026-06-20T09:30:00Z", "2026-06-20T10:30:00Z")
    resp = api.create_session(overlap, hdr)
    validate_error(resp, ApiErrorId.ERR_SESSION_TIME_CONFLICT.value, expected_status=409)


def test_session_window_adjacent_allowed(api):
    """PRD §3.4: "Because the windows are half-open, adjacency is permitted: a new
    session whose start equals an existing session's end does *not* conflict."

    Design: Difficulty/resource_temporal_overlap/session_half_open_overlap_rejected_adjacent_allowed
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nto1b@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    th.create_session(notary["id"], "2026-06-20T09:00:00Z", "2026-06-20T10:00:00Z")
    adjacent = create_session_payload(notary["id"], "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    data = validate_success(api.create_session(adjacent, hdr), expected_status=201)
    assert data["status"] == "SCHEDULED"
