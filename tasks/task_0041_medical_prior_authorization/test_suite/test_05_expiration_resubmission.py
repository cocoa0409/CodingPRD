"""Expiration, resubmission/supersession, the member-counter cascade on expire,
the conserve-counter invariant, OCC on resubmit, scheduled-expiry precondition,
and the invalid supersede target.

Translates queue A (transitive_cascade expire, compensating_invariant expire) and
queue B (cross_cutting_complexity_layers OCC/scheduled, validations supersede)
instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    register_actors,
    set_clock,
    create_approved_request,
    create_expired_request,
    create_draft_request,
    make_provider_headers,
    make_payer_headers,
)


# --------------------------------------------------------------------------
# transitive cascade: expire -> member counter (queue A)
# --------------------------------------------------------------------------

def test_expire_cascades_member_counter_depth2(api):
    """PRD §3.7: "Expiring sets the request's `status` to `EXPIRED`, decrements the
    referenced member's `active_authorization_count` by one (floored at zero) as a
    cross-aggregate cascade, and increments the request's `version` by one."

    Design: Difficulty/transitive_cascade/expire_cascades_member_counter_depth2
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    expired = create_expired_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-9",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    assert expired["status"] == "EXPIRED"
    member = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert member["active_authorization_count"] == 0, (
        f"hop2: member counter back to 0, got {member['active_authorization_count']}"
    )


def test_expire_sets_request_status_expired_side(api):
    """PRD §3.7: "Expiring sets the request's `status` to `EXPIRED`, decrements the
    referenced member's `active_authorization_count` by one (floored at zero) as a
    cross-aggregate cascade, and increments the request's `version` by one."

    Design: Difficulty/transitive_cascade/expire_cascades_member_counter_depth2
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    # member counter is 1 after approval (the hop1 origin state)
    approved = create_approved_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-E",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    before = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert before["active_authorization_count"] == 1
    set_clock("2027-06-02T00:00:00Z", payer_h)
    expired = validate_success(api.expire_request(approved["id"], payer_h))
    assert expired["status"] == "EXPIRED", f"hop1: request must be EXPIRED, got {expired['status']}"


# --------------------------------------------------------------------------
# compensating invariant: approve(+1) then expire(-1) conserves counter (queue A)
# --------------------------------------------------------------------------

def test_approve_then_expire_conserves_active_auth_count(api):
    """PRD §3.5: "the counter is incremented by one whenever one of the member's
    requests enters `APPROVED` (whether by a direct review decision or by an
    appeal overturn), and decremented by one — floored at zero — whenever an
    `APPROVED` request expires."

    Design: Difficulty/compensating_invariant/approve_then_expire_conserves_active_auth_count
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    # forward action: approve (+1)
    create_expired_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-INV",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # compensating action expire (-1) already applied by fixture; net to pre-approval 0.
    member = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert member["active_authorization_count"] == 0, (
        f"+1 approve, -1 expire net to zero drift, got {member['active_authorization_count']}"
    )


def test_approve_increments_counter_before_expire_compensates(api):
    """PRD §3.5: "the counter is incremented by one whenever one of the member's
    requests enters `APPROVED` (whether by a direct review decision or by an
    appeal overturn), and decremented by one — floored at zero — whenever an
    `APPROVED` request expires."

    Design: Difficulty/compensating_invariant/approve_then_expire_conserves_active_auth_count
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    approved = create_approved_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-INV2",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # forward action APPROVE: counter is 1.
    mid = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert mid["active_authorization_count"] == 1, (
        f"approve increments counter to 1, got {mid['active_authorization_count']}"
    )
    set_clock("2027-06-02T00:00:00Z", payer_h)
    get_success_data(api.expire_request(approved["id"], payer_h))
    # compensating action EXPIRE: back to 0.
    after = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert after["active_authorization_count"] == 0, (
        f"expire compensates back to 0, got {after['active_authorization_count']}"
    )


# --------------------------------------------------------------------------
# scheduled-action: expire only after deadline (queue B)
# --------------------------------------------------------------------------

def test_scheduled_expiry_only_after_deadline(api):
    """PRD §3.7: "Once the current clock reaches or passes that instant, the payer
    may force the request to `EXPIRED` through an explicit expire capability; the
    precondition is that the current clock is at or after `authorization_expires_at`."
    PRD §3.9: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/scheduled_expiry_only_after_deadline
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    approved = create_approved_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # clock left at 2026-06-01, before authorization_expires_at (2027-06-01).
    resp = api.expire_request(approved["id"], payer_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# OCC: resubmit-supersede happy path (queue B)
# --------------------------------------------------------------------------

def test_resubmit_supersede_happy_path_marks_superseded(api):
    """PRD §3.7: "When a valid resubmission is accepted, the targeted `EXPIRED`
    request transitions to `SUPERSEDED` and its `version` is incremented by one,
    while the new resubmission request is created in `DRAFT`, copying the
    `request_type`, `procedure_code`, `requested_units`, and `unit_cost_cents`
    from the superseded request." PRD §2.10: "The create-request endpoint, when it
    carries a `supersedes_request_id`, must also carry
    `expected_authorizationrequest_version` holding the client's last observed
    `version` of the targeted expired request."

    Design: Corner/cross_cutting_complexity_layers/resubmit_supersede_happy_path_marks_superseded
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    expired = create_expired_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-7",
                                   "requested_units": 3, "unit_cost_cents": 5000},
        approved_units=3,
    )
    cur = get_success_data(api.get_authorization_request(expired["id"], prov_h))
    resp = api.create_authorization_request(
        {"member_id": actors["member"]["id"], "provider_id": actors["provider"]["id"],
         "request_type": "DRUG", "procedure_code": "NDC-7", "requested_units": 3,
         "unit_cost_cents": 5000, "supersedes_request_id": expired["id"],
         "expected_authorizationrequest_version": cur["version"]},
        prov_h,
    )
    new_req = validate_success(resp, expected_status=201)
    assert new_req["status"] == "DRAFT", f"new request must be DRAFT, got {new_req['status']}"
    assert new_req["supersedes_request_id"] == expired["id"]
    target = get_success_data(api.get_authorization_request(expired["id"], prov_h))
    assert target["status"] == "SUPERSEDED", f"target must be SUPERSEDED, got {target['status']}"


# --------------------------------------------------------------------------
# OCC: stale version on second resubmit (queue B)
# --------------------------------------------------------------------------

def test_occ_stale_version_on_resubmit_supersede(api):
    """PRD §2.10: "If that expired request's current `version` no longer matches —
    for instance because another resubmission has already superseded it,
    legitimately advancing its `version` and flipping it to its superseded state —
    the client's view is stale and the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_resubmit_supersede
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"},
                             reviewer_overrides={"specialty": "PRIMARY_CARE"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    expired = create_expired_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # client reads the stale (pre-supersede) version
    stale = get_success_data(api.get_authorization_request(expired["id"], prov_h))
    stale_v = stale["version"]
    # first resubmission supersedes it (advances version, flips to SUPERSEDED)
    get_success_data(
        api.create_authorization_request(
            {"member_id": actors["member"]["id"], "provider_id": actors["provider"]["id"],
             "request_type": "DRUG", "procedure_code": "NDC-1", "requested_units": 1,
             "unit_cost_cents": 5000, "supersedes_request_id": expired["id"],
             "expected_authorizationrequest_version": stale_v},
            prov_h,
        )
    )
    # second resubmission with the now-stale version is rejected
    resp = api.create_authorization_request(
        {"member_id": actors["member"]["id"], "provider_id": actors["provider"]["id"],
         "request_type": "DRUG", "procedure_code": "NDC-1", "requested_units": 1,
         "unit_cost_cents": 5000, "supersedes_request_id": expired["id"],
         "expected_authorizationrequest_version": stale_v},
        prov_h,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------
# invalid supersede target (queue B)
# --------------------------------------------------------------------------

def test_invalid_supersede_target_not_expired(api):
    """PRD §3.7: "The supersede target must reference an `EXPIRED` request owned by
    the same `member_id` and `provider_id` as the new request and not already
    superseded by another request; a target that is not `EXPIRED`, belongs to a
    different member or provider, or has already been superseded is rejected with
    `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422)."

    Design: Corner/validations/invalid_supersede_target_not_expired
    """
    actors = register_actors(provider_overrides={"specialty": "PRIMARY_CARE"}, with_reviewer=False)
    prov_h = make_provider_headers(actors["provider"]["id"])
    target = create_draft_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    resp = api.create_authorization_request(
        {"member_id": actors["member"]["id"], "provider_id": actors["provider"]["id"],
         "request_type": "DRUG", "procedure_code": "NDC-1", "requested_units": 1,
         "unit_cost_cents": 5000, "supersedes_request_id": target["id"],
         "expected_authorizationrequest_version": target["version"]},
        prov_h,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE_TARGET.value)
