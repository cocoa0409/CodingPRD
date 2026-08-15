"""Corner coverage — entities: creation defaults, required fields, enum constraints,
system-minted fields, 404s, pagination, uniqueness, and FK-reverse listing."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_vendor,
    create_instrument,
    create_instrument_payload,
    create_candidate_payload,
    create_guide_payload,
    create_vendor_payload,
    setup_active_cycle,
    setup_quorum_ready_candidate,
    create_candidate,
    invite_candidate,
    assert_vendor,
    assert_instrument,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


def test_vendor_created_with_defaults_and_envelope(api):
    """PRD §3.1: "A new vendor begins in `ACTIVE` status with a `content_copies_outstanding`
    ledger balance of zero" and "an optional `security_clearance_tier` of `TIER_1`,
    `TIER_2`, or `TIER_3` (defaulting to `TIER_2` when omitted)".
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/vendor_created_with_defaults_and_envelope
    """
    resp = api.create_vendor(create_vendor_payload(), ADMIN)
    # Envelope assertions before the entity body
    body = resp.json()
    assert body.get("response_type") == "object"
    assert body.get("meta", {}).get("api_request_id", "").startswith("req_")
    assert body.get("meta", {}).get("api_request_timestamp")
    data = validate_success(resp, expected_status=201)
    assert_vendor(data)
    assert data["status"] == "ACTIVE"
    assert data["security_clearance_tier"] == "TIER_2"
    assert data["content_copies_outstanding"] == 0
    assert data["version"] == 1
    assert data["terminated_at"] is None


def test_candidate_missing_required_field_returns_400(api):
    """PRD §3.5: "A candidate is registered — by a hiring manager or an administrator —
    with a globally unique `external_ref` (an external ATS reference; a collision is
    `ERR_DUPLICATE_CANDIDATE_REF`, HTTP 409), a `full_name`, a contact `email`, and a
    self-identified `group_code` of `GROUP_A`, `GROUP_B`, `GROUP_C`, `GROUP_D`, or
    `UNDISCLOSED` that feeds adverse-impact analysis."
    PRD §2.8: "anything of this kind without a dedicated code is `ERR_INVALID_REQUEST`".

    Omitting group_code is rejected with ERR_INVALID_REQUEST (400).

    Design: Corner/entities/candidate_missing_required_field_returns_400
    """
    resp = api.create_candidate(
        {"external_ref": "C-X", "full_name": "Cand X", "email": "cx@x.com"}, HM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_instrument_invalid_enum_returns_400(api):
    """PRD §3.2: "an `instrument_type` of `COGNITIVE_ABILITY`, `PERSONALITY`,
    `SKILLS_SIMULATION`, or `JOB_KNOWLEDGE`" — a value outside the declared enum
    (`MAGIC`) is rejected with ERR_INVALID_REQUEST (400) per PRD §2.8 tier 16
    ("invalid enum members").

    Design: Corner/entities/instrument_invalid_enum_returns_400
    """
    vendor = create_vendor()
    resp = api.create_instrument(
        create_instrument_payload(vendor["id"], instrument_type="MAGIC", title="Magic"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_system_generated_fields_input_ignored(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id` — a UUID with
    no type prefix — assigned at creation and never reused" and "a `version` integer.
    Every mutation of a resource increments its `version` by exactly one".

    Client-supplied id/version in a create body are ignored: the server mints a UUID
    and starts version at 1.

    Design: Corner/entities/system_generated_fields_input_ignored
    """
    resp = api.create_vendor(
        {"name": "Acme Assessments", "id": "client-supplied-id", "version": 99}, ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["id"] != "client-supplied-id"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1


def test_cycle_not_found_returns_404(api):
    """PRD §2.9: "the first identifier that does not resolve yields `ERR_NOT_FOUND`
    (HTTP 404)".

    Design: Corner/entities/cycle_not_found_returns_404
    """
    resp = api.get_cycle(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_instruments_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and may not
    exceed 100; the `offset` parameter defaults to 0." and "the `meta` object of a list
    response carries the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Eleven instruments: page 1 has 10 items with has_more true; offset 10 has 1 item
    with has_more false.

    Design: Corner/entities/instruments_list_pagination_defaults
    """
    vendor = create_vendor()
    for _ in range(11):
        create_instrument(vendor["id"])
    resp = api.list_instruments(ADMIN, params={"vendor_id": vendor["id"]})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 10
    assert meta1["total_count"] == 11
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    resp = api.list_instruments(ADMIN, params={"vendor_id": vendor["id"], "offset": 10})
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 11
    assert meta2["has_more"] is False


def test_duplicate_invitation_rejected(api):
    """PRD §3.5: "the pairing of cycle and candidate must be new — a second invitation
    of the same candidate into the same cycle is `ERR_DUPLICATE_INVITATION` (HTTP 409)".

    Design: Corner/entities/duplicate_invitation_rejected
    """
    ctx = setup_active_cycle()
    c1 = create_candidate()
    invite_candidate(ctx["cycle"]["id"], c1["id"])
    resp = api.create_invitation(ctx["cycle"]["id"], {"candidate_id": c1["id"]}, HM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVITATION)
    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], CO))
    assert cycle["active_candidate_count"] == 1


def test_guide_rubric_bad_weight_sum_rejected(api):
    """PRD §3.3: "weights that do not sum to exactly 1.0000 compared at four decimal
    places are `ERR_RUBRIC_WEIGHT_SUM` (HTTP 400)".

    Weights 0.5 + 0.4 = 0.9 != 1.0000.

    Design: Corner/entities/guide_rubric_bad_weight_sum_rejected
    """
    resp = api.create_guide(
        create_guide_payload(title="Bad Guide", rubric_items=[
            {"competency_code": "COMM", "weight": 0.5, "scale_max": 5},
            {"competency_code": "ANAL", "weight": 0.4, "scale_max": 5},
        ]),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RUBRIC_WEIGHT_SUM)


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §2.3: "scorecards by `session_id`, `interviewer_id`, `candidate_id`, and
    `status`; and hiring decisions by `cycle_id` and `candidate_id`." and "These
    filters double as the reverse-lookup mechanism for parent-child relationships — a
    vendor's instruments, a cycle's assessments, an interviewer's sessions".

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    cycle = ctx["cycle"]
    candidate = ctx["candidate"]
    sessions = ctx["sessions"]
    scorecards = ctx["scorecards"]
    resp = api.create_decision(
        cycle["id"],
        {"candidate_id": candidate["id"], "decision": "ADVANCE",
         "rationale": "Candidate demonstrated strong structured problem solving and communication across panels."},
        TEST_USERS["do_headers"],
    )
    decision = validate_success(resp, expected_status=201)

    data, meta = validate_paginated(api.list_decisions(CO, params={"cycle_id": cycle["id"]}))
    assert [d["id"] for d in data] == [decision["id"]]
    data, meta = validate_paginated(api.list_decisions(CO, params={"candidate_id": candidate["id"]}))
    assert [d["id"] for d in data] == [decision["id"]]
    data, meta = validate_paginated(api.list_scorecards(CO, params={"session_id": sessions[0]["id"]}))
    assert [s["id"] for s in data] == [scorecards[0]["id"]]
    data, meta = validate_paginated(api.list_scorecards(
        CO, params={"interviewer_id": ctx["interviewers"][1]["id"], "candidate_id": candidate["id"]},
    ))
    assert [s["id"] for s in data] == [scorecards[1]["id"]]
