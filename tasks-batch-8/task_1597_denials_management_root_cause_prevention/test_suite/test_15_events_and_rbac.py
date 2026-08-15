"""Audit event trail and remaining role gates (PRD §2.11, §3.2, §4)."""
from test_helpers import (
    ApiErrorId,
    assert_denial_event,
    clock_payload,
    make_denial,
    setup_catalog,
    triage_denial,
    validate_error,
    validate_paginated,
)


def test_denial_events_recorded_for_actions(api, auditor_headers):
    """PRD §2.11: "Every significant occurrence in a denial's life appends an immutable
    **DenialEvent** to an audit trail. An event records `denial_case_id` (the denial it
    belongs to), an `event_type` drawn from a fixed vocabulary, the acting `actor_role` and
    `actor_user_id`, and a `detail` string — a deterministic summary that includes the key
    amounts and statuses of the occurrence, such as the `recovered_amount_cents` figure after
    an outcome."
    PRD §3.2: "An `INTAKE` event is appended to the denial's audit trail."
    PRD §3.2: "Finally triage appends a `TRIAGED` event, increments the denial's `version`,
    and recomputes its queue priority."

    Design: Corner/endpoints/denial_events_recorded_for_actions
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2406")
    triage_denial(denial["id"], preventable_flag=False)
    rows, meta = validate_paginated(
        api.list_denial_events(auditor_headers, params={"denial_case_id": denial["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    for event in rows:
        assert_denial_event(event)
    assert sorted(e["event_type"] for e in rows) == ["INTAKE", "TRIAGED"]
    assert all(e["actor_role"] == "DenialsSpecialist" for e in rows)


def test_specialist_cannot_set_clock(api, specialist_headers):
    """PRD §2.8: "**Authorization.** The authenticated role must appear in the endpoint's
    authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint."
    PRD §4: "| POST | `/rcm/_clock/set_current_utc` | Set the server logical clock and run
    the timely-filing expiry sweep | RevenueCycleDirector |"

    Design: Corner/rbac/specialist_cannot_set_clock
    """
    resp = api.set_clock(clock_payload("2026-09-01T00:00:00Z"), specialist_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_triage_on_triaged_denial_rejected(api, specialist_headers):
    """PRD §3.2: "**Triage** moves a denial from `RECEIVED` to `TRIAGED` and is performed by
    a `DenialsSpecialist`; attempting it from any other status yields
    `ERR_DENIAL_INVALID_STATE`."

    Design: Corner/state_machines/triage_on_triaged_denial_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2101")
    triage_denial(denial["id"], preventable_flag=False)
    resp = api.triage_denial(denial["id"], {"preventable_flag": True}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_DENIAL_INVALID_STATE, expected_status=409)
    from test_helpers import get_denial
    after = get_denial(denial["id"])
    assert after["status"] == "TRIAGED"
    assert after["preventable_flag"] is False, "no partial mutation"
