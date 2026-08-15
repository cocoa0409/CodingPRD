"""One-open-transfer gate, compensating counters, counterparty kinds, and access control (PRD §2.1, §2.8, §3.2, §3.9)."""
from test_helpers import (
    ApiErrorId,
    B1,
    MGR,
    NON_EXISTENT_UUID,
    add_certified_measurement,
    build_submitted_transfer,
    create_draft_transfer,
    create_party,
    create_transfer_request_payload,
    get_lease,
    standard_portfolio,
    submit_transfer,
    validate_error,
    validate_paginated,
    withdraw_transfer,
)


def test_second_transfer_rejected_while_submitted(api):
    """PRD §3.2: "Exclusivity is enforced at creation. A lease may carry at most one non-terminal transfer — one whose `status` has not reached `EFFECTIVE`, `WITHDRAWN`, `RESCINDED`, or `CONSENT_DENIED` — and a create that would open a second is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/open_transfer_exclusive_occupancy_per_lease
    """
    ctx = build_submitted_transfer()
    ps2 = create_party("SUBTENANT", "SubTwo Corp", 7000)
    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 1

    payload = create_transfer_request_payload(
        counterparty_id=ps2["id"],
        proposed_rent_per_rsf_annual_cents=7000,
        marketing_period_days=60,
        expected_lease_version=lease["version"],
    )
    resp = api.create_transfer_request(lease["id"], payload, B1)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE, 409)
    assert get_lease(lease["id"])["open_transfer_count"] == 1


def test_gate_reopens_after_withdrawal(api):
    """PRD §3.9: "From `SUBMITTED` or `CONSENT_PENDING`, withdrawal additionally decrements that counter, increments the lease's `version`, and voids any drafted or partially-signed recognition agreement attached to the transfer."
    PRD §3.9: "Together with denial, rescission, withdrawal, and effectiveness, these doors define the transfer's terminal landscape of `CONSENT_DENIED`, `RESCINDED`, `WITHDRAWN`, and `EFFECTIVE`, each releasing the lease's one-open-transfer gate for the next deal."

    Design: Difficulty/resource_temporal_overlap/open_transfer_exclusive_occupancy_per_lease
    """
    ctx = build_submitted_transfer()
    ps2 = create_party("SUBTENANT", "SubTwo Corp", 7000)
    withdraw_transfer(ctx["transfer"]["id"], B1)
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0

    t2 = create_draft_transfer(ctx, counterparty_id=ps2["id"])
    assert t2["status"] == "DRAFT", "the terminal withdrawal releases the gate"

    transfers, _ = validate_paginated(
        api.list_lease_transfer_requests(ctx["lease"]["id"], B1)
    )
    assert len(transfers) == 2


def test_submit_withdraw_preserves_open_transfer_count(api):
    """PRD §3.4: "A successful submission stamps `submitted_at` with the logical clock, computes the `consent_deadline`, mints exactly one consent review with `decision` of `PENDING` and exactly one credit review with `outcome` of `PENDING` for the transfer, and increments both the lease's `open_transfer_count` and its `version` by one."
    PRD §3.9: "From `SUBMITTED` or `CONSENT_PENDING`, withdrawal additionally decrements that counter, increments the lease's `version`, and voids any drafted or partially-signed recognition agreement attached to the transfer."

    Design: Difficulty/compensating_invariant/submit_withdraw_preserves_open_transfer_count
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    add_certified_measurement(transfer["id"])
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0

    submit_transfer(transfer["id"])
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 1, "submit: +1"

    withdrawn = withdraw_transfer(transfer["id"], B1)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0, (
        "the compensating withdraw restores the pre-submit count"
    )


def test_withdraw_from_draft_never_touched_count(api):
    """PRD §3.9: "From `DRAFT`, withdrawal moves the transfer to `WITHDRAWN` with no change to `open_transfer_count`, which was never incremented."
    PRD §3.2: "Creation starts the transfer in `DRAFT` and increments the lease's `version` by one as the OCC anchor, but does not touch `open_transfer_count`; that counter moves only at submission."

    Design: Difficulty/compensating_invariant/submit_withdraw_preserves_open_transfer_count
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0

    withdrawn = withdraw_transfer(transfer["id"], B1)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0


def test_counterparty_kind_mismatch_assignment_rejected(api):
    """PRD §3.2: "The counterparty's kind must match the transfer flavor — a `SUBLEASE` demands a `SUBTENANT` counterparty and an `ASSIGNMENT` an `ASSIGNEE` — with mismatches rejected as `ERR_FK_MISMATCH`."

    Design: Corner/validations/counterparty_kind_mismatch_assignment_rejected
    """
    ctx = standard_portfolio()
    lease_v = get_lease(ctx["lease"]["id"])["version"]

    # ASSIGNMENT with a SUBTENANT counterparty.
    resp = api.create_transfer_request(
        ctx["lease"]["id"],
        create_transfer_request_payload(counterparty_id=ctx["ps"]["id"],
                                        transfer_type="ASSIGNMENT",
                                        expected_lease_version=lease_v),
        B1,
    )
    validate_error(resp, ApiErrorId.ERR_FK_MISMATCH, 422)

    transfers, _ = validate_paginated(
        api.list_lease_transfer_requests(ctx["lease"]["id"], B1)
    )
    assert transfers == [], "no transfer row is persisted after a rejected create"

    # The mirror: SUBLEASE with an ASSIGNEE counterparty on a fresh lease.
    pa = create_party("ASSIGNEE", "Assignee One Corp", 7000)
    lease2_v = get_lease(ctx["lease"]["id"])["version"]
    resp2 = api.create_transfer_request(
        ctx["lease"]["id"],
        create_transfer_request_payload(counterparty_id=pa["id"],
                                        transfer_type="SUBLEASE",
                                        expected_lease_version=lease2_v),
        B1,
    )
    validate_error(resp2, ApiErrorId.ERR_FK_MISMATCH, 422)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    resp = api.get_party(NON_EXISTENT_UUID, MGR)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request whose headers are missing or malformed, or whose role is not one of the six recognized role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api.list_leases(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
