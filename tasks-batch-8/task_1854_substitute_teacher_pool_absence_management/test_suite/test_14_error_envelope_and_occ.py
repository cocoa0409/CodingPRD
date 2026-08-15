"""Error envelope shape and the three optimistic-concurrency guards:
absence claim, absence edit, and district configuration update."""
from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    basic_world,
    get_absence,
    make_coordinator_headers,
    make_district,
    make_substitute_headers,
    onboard_substitute,
    report_absence,
    run_dispatch_batch,
    validate_error,
    validate_success,
)


def test_error_envelope_shape_on_business_failure(api):
    """PRD 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"
    PRD 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_shape_on_business_failure
    """
    ctx = basic_world()
    sub = onboard_substitute(qualifications=(("SCIENCE", "HIGH"),))
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    res = api.create_assignment(
        {"absence_id": absence["id"], "substitute_id": sub["id"]}, coord_headers
    )
    validate_error(res, ApiErrorId.ERR_QUALIFICATION_MISMATCH, expected_status=409)
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_QUALIFICATION_MISMATCH"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_occ_claim_stale_version_rejected(api, district_admin_headers):
    """PRD 2.7: "A substitute claiming an open absence must supply
    `expected_absence_version` carrying the absence's `version` as the client
    last observed it; if another writer has advanced the absence's version
    since that read — a completed claim or an applied edit — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.4: "success is atomic, creating the assignment already `ACCEPTED`
    with `offer_source` `SELF_CLAIM`, moving the absence to `ASSIGNED`,
    committing the budget, and incrementing the absence's `version` by one."

    Design: Corner/cross_cutting_layers/occ_claim_stale_version_rejected
    """
    ctx = basic_world()
    sub_a = onboard_substitute(full_name="Sub A", rate_cents=20000)
    sub_b = onboard_substitute(full_name="Sub B", rate_cents=18000)
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")

    observed = get_absence(absence["id"])
    stale_version = observed["version"]

    claim = validate_success(
        api.claim_absence(
            absence["id"], {"expected_absence_version": stale_version},
            make_substitute_headers(sub_b["id"]),
        ),
        201,
    )
    assert claim["status"] == "ACCEPTED"
    assert claim["offer_source"] == "SELF_CLAIM"
    after = get_absence(absence["id"])
    assert after["fill_status"] == "ASSIGNED"
    assert_version_incremented(after["version"], stale_version)

    res = api.claim_absence(
        absence["id"], {"expected_absence_version": stale_version},
        make_substitute_headers(sub_a["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    assert get_absence(absence["id"])["fill_status"] == "ASSIGNED", (
        "exactly one claim took effect"
    )


def test_occ_absence_edit_stale_version_rejected(api):
    """PRD 2.7: "Editing an absence's dates or requirements carries the
    identical contract: `expected_absence_version` must equal the absence's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412), because a second well-formed edit sent after another edit has
    fully completed would otherwise legitimately succeed on a stale view."
    PRD 3.3: "A successful edit increments the absence's `version` by one,
    recomputes `total_days`, and re-runs the approval computation"

    Design: Corner/cross_cutting_layers/occ_absence_edit_stale_version_rejected
    """
    ctx = basic_world()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    stale_version = absence["version"]
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    edited = validate_success(
        api.update_absence(
            absence["id"],
            {"expected_absence_version": stale_version, "end_date": "2026-08-04"},
            coord_headers,
        ),
        200,
    )
    assert edited["total_days"] == 2
    assert_version_incremented(edited["version"], stale_version)

    res = api.update_absence(
        absence["id"],
        {"expected_absence_version": stale_version, "end_date": "2026-08-05"},
        coord_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_absence(absence["id"])["total_days"] == 2


def test_occ_district_config_stale_version_rejected(api, district_admin_headers):
    """PRD 2.7: "Updating a district's pay-rule configuration requires
    `expected_district_version` matching the district's current `version`,
    with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch;
    sequential configuration updates are each legitimate, so the stale-version
    check is the only signal."
    PRD 3.1: "reconfiguration is an optimistic-concurrency-guarded update per
    §2.7, where any subset of these fields plus `name` may change and the
    district's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_district_config_stale_version_rejected
    """
    district = make_district()
    stale_version = district["version"]

    updated = validate_success(
        api.update_district(
            district["id"],
            {"expected_district_version": stale_version, "short_notice_premium_pct": 0.30},
            district_admin_headers,
        ),
        200,
    )
    assert updated["short_notice_premium_pct"] == 0.3
    assert_version_incremented(updated["version"], stale_version)

    res = api.update_district(
        district["id"],
        {"expected_district_version": stale_version, "moderate_notice_premium_pct": 0.15},
        district_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    refreshed = validate_success(api.get_district(district["id"], district_admin_headers), 200)
    assert refreshed["moderate_notice_premium_pct"] == 0.1, "the rejected update left no trace"
