"""Dispatch and interpreter selection: weighted scoring, empty pool -> UNFULFILLABLE,
optimistic concurrency, and no-qualified-interpreter outcomes."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_client, create_language_pair, create_rate_plan, create_interpreter,
    add_certification, add_language_grant, create_request, dispatch_request,
    create_ended_session, set_clock,
    make_interpreter_headers, make_client_headers, coordinator_headers, admin_headers,
    factories,
)


def test_selection_picks_higher_weighted_score_not_first_come(api):
    """PRD 3.3: "The score is the sum of three terms: the rating contribution multiplied
    by 100 and then by the rating weight of 0.5; plus the candidate's acceptance_pct
    multiplied by the acceptance weight of 0.3; plus the value of one minus the ratio of
    active_load to max_concurrent_load, multiplied by 100 and then by the load weight of 0.2."

    Design: Difficulty/combinatorial_formula/interpreter_selection_three_factor_nonlinear_score
    """
    # Seed a rated 5.0 interpreter (itpB) and an unrated interpreter (itpA, default 4.0).
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")

    itpB = create_interpreter(full_name="B Star")
    add_certification(itpB["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itpB["id"], lp["id"])

    set_clock("2026-03-10T09:00:00Z")
    # Run a full session for itpB and rate it 5 so rating_avg becomes 5.0.
    _, _, sseed = create_ended_session(
        client["id"], lp["id"], itpB["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:30:00Z",
    )
    validate_success(
        api.rate_session(sseed["id"], factories.rating_payload(5), make_client_headers(client["id"])),
        expected_status=201,
    )

    # Now onboard the unrated itpA (default rating 4.0).
    itpA = create_interpreter(full_name="A New")
    add_certification(itpA["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itpA["id"], lp["id"])

    req = create_request(client["id"], lp["id"])
    asg = validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers()),
        expected_status=201,
    )
    # itpB score 5.0*50 + 100*0.3 + 100*0.2 = 300 ; itpA 4.0*50 + 30 + 20 = 250. itpB wins.
    assert asg["interpreter_id"] == itpB["id"], (
        f"expected higher-scored itpB, got {asg['interpreter_id']}"
    )


def test_unrated_interpreter_uses_default_rating_in_score(api):
    """PRD 3.3: "take its rating contribution as rating_avg when rating_count is greater
    than 0, and otherwise substitute the default rating of 4.0 (so a brand-new interpreter
    is not ranked as though it scored zero)."

    Design: Difficulty/combinatorial_formula/interpreter_selection_three_factor_nonlinear_score
    """
    # A single unrated interpreter is still dispatchable (default 4.0 keeps score positive,
    # so the request advances to ASSIGNED rather than UNFULFILLABLE).
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Fresh")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    set_clock("2026-03-10T09:00:00Z")

    req = create_request(client["id"], lp["id"])
    asg = validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers()),
        expected_status=201,
    )
    assert asg["interpreter_id"] == itp["id"]
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    assert request["status"] == "ASSIGNED"


def test_empty_candidate_pool_drives_request_unfulfillable(api):
    """PRD 3.3: "If the eligible set is empty for an ordinary reason, dispatch instead
    drives the request from OPEN to UNFULFILLABLE (still incrementing version by 1)."

    Design: Difficulty/boundary_precision_check/empty_candidate_pool_yields_unfulfillable
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    # A qualified interpreter exists (valid MEDICAL cert + the pair) but is OFFLINE, so the
    # eligible set is empty "for an ordinary reason" (availability), not because no
    # interpreter holds a valid required-tier cert for the pair.
    itp = create_interpreter(full_name="Offline I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    validate_success(api.set_interpreter_status(itp["id"], {"status": "OFFLINE"}, admin_headers()))
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(client["id"], lp["id"])

    dispatched = validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers())
    )
    # dispatch returns the request driven to UNFULFILLABLE (no Assignment minted).
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    assert request["status"] == "UNFULFILLABLE", f"expected UNFULFILLABLE, got {request['status']}"


def test_no_assignment_created_for_unfulfillable_request(api):
    """PRD 3.3: "If the eligible set is empty for an ordinary reason, dispatch instead
    drives the request from OPEN to UNFULFILLABLE (still incrementing version by 1)."

    Design: Difficulty/boundary_precision_check/empty_candidate_pool_yields_unfulfillable
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    # Qualified-but-OFFLINE interpreter => eligible set empty for an ordinary reason.
    itp = create_interpreter(full_name="Offline I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    validate_success(api.set_interpreter_status(itp["id"], {"status": "OFFLINE"}, admin_headers()))
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(client["id"], lp["id"])
    validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers())
    )
    data, meta = None, None
    resp = api.list_assignments(coordinator_headers(), params={"request_id": req["id"]})
    from test_helpers import validate_paginated
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, f"no assignment should exist, found {meta['total_count']}"


def test_dispatch_with_stale_version_after_decline_rejected(api):
    """PRD 2.8: "The server compares this value against the request's current `version`. If
    they do not match — because another coordinator has already dispatched the request,
    creating an assignment that legitimately advanced the request to `ASSIGNED` and
    incremented its `version` — the dispatch is rejected with `ERR_STALE_REQUEST_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_request_version_on_redispatch
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Med I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    set_clock("2026-03-10T09:00:00Z")

    req = create_request(client["id"], lp["id"])
    create_v = req["version"]  # version 1 at create
    live = validate_success(api.get_request(req["id"], coordinator_headers()))
    asg = dispatch_request(req["id"], live["version"])  # advances to ASSIGNED (version up)
    # Decline bounces the request back to OPEN and bumps version again.
    validate_success(api.decline_assignment(asg["id"], make_interpreter_headers(itp["id"])))

    # Re-dispatch carrying the original create-time version (now stale).
    resp = api.dispatch_request(req["id"], factories.dispatch_payload(create_v), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_REQUEST_VERSION.value)
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    assert request["status"] == "OPEN", "state check passed; only OCC rejected"


def test_dispatch_with_expired_cert_returns_no_qualified_interpreter(api):
    """PRD 3.3: "When dispatch is attempted but no interpreter holds a valid required-tier
    certification for the language pair, the operation is rejected with
    `ERR_NO_QUALIFIED_INTERPRETER` (HTTP 409)."

    Design: Corner/errors/no_qualified_interpreter_expired_cert
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Expired I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2026-03-05T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    set_clock("2026-03-10T09:00:00Z")  # clock past expiry -> no VALID cert holder for the pair

    req = create_request(client["id"], lp["id"])
    resp = api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_INTERPRETER.value)
