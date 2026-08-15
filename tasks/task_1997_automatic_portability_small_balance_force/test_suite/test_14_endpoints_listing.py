"""Queue B corner tests: endpoint envelope, pagination, and filter semantics."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    send_force_out_notice_and_deliver,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_list_pagination_envelope():
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to
    10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of
    items and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_pagination_envelope
    """
    for code, name in (("RK-A", "Recordkeeper A"), ("RK-B", "Recordkeeper B"),
                       ("RK-C", "Recordkeeper C")):
        get_success_data(api_client.create_recordkeeper(
            {"recordkeeper_code": code, "legal_name": name}, OPS))

    page1, meta1 = validate_paginated(api_client.list_recordkeepers(
        OPS, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(api_client.list_recordkeepers(
        OPS, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    # Defaults: limit 10 / offset 0 returns all three rows.
    page_all, meta_all = validate_paginated(api_client.list_recordkeepers(OPS))
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert len(page_all) == 3
    assert meta_all["has_more"] is False


def test_error_envelope_shape():
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope
    format"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape
    """
    res = api_client.get_recordkeeper(NON_EXISTENT_UUID, OPS)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert len(body["meta"]["api_request_id"]) > 0
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    err = body["data"]
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and len(err["message"].strip()) > 0


def test_filtered_list_cases_by_status():
    """PRD §2.3: "List endpoints also accept exact-match filter parameters, each named
    after a resource field and matching resources whose like-named field equals the
    supplied value."
    PRD §3.4: "When the delivered notice is a `FORCE_OUT_ELECTION` on an `IDENTIFIED` case,
    the case advances to `NOTIFIED`"

    Design: Corner/endpoints/filtered_list_cases_by_status
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
    p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
    batch = create_open_batch(plan["id"])
    c_a = create_case(batch["id"], plan["id"], p_a["id"],
                      separation_date_balance_cents=50000,
                      processing_date_balance_cents=50000)
    c_b = create_case(batch["id"], plan["id"], p_b["id"],
                      separation_date_balance_cents=60000,
                      processing_date_balance_cents=60000)
    get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
    # Case A -> NOTIFIED; case B gets a notice that stays SENT (still IDENTIFIED).
    send_force_out_notice_and_deliver(c_a["id"])
    get_success_data(api_client.create_notice(
        c_b["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS))

    hits, meta = validate_paginated(api_client.list_distribution_cases(
        OPS, params={"case_status": "NOTIFIED"}))
    assert meta["total_count"] == 1
    assert hits[0]["id"] == c_a["id"]

    empty, meta2 = validate_paginated(api_client.list_distribution_cases(
        OPS, params={"case_status": "EXECUTED"}))
    assert empty == []
    assert meta2["total_count"] == 0
    assert meta2["has_more"] is False
