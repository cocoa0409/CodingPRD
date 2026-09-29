"""Two variants of the same figure computed side by side over one fixture.

Both scenarios build a single state and then read two numbers out of it that a
single-formula implementation would collapse into one: the two burden figures of
a responsive record, and the two bases a fee estimate may be struck on.
"""

from test_helpers.assertions import (
    assert_fields,
    assert_list_response,
    assert_money_is_integer_cents,
    assert_waiver_pct,
)
from test_helpers.test_users import CLERK_HEADERS
from test_helpers.fixtures import (
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_claim,
    get_record,
    get_request,
    request_version,
    rule_inclusion,
)


def _forty_five_minute_use_of_force(api, incident_number, device_serial, recorded_start_at):
    """A 45-minute USE_OF_FORCE recording: 45 whole minutes, review multiplier 2.0."""
    return create_asset(
        api,
        incident_number=incident_number,
        device_serial=device_serial,
        officer_badge="B-4471",
        recorded_start_at=recorded_start_at,
        duration_ms=2700000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-20T00:00:00Z",
    )


def _scoped_record(api, requester_id, asset_id, incident_number, date_from, date_to, narrative):
    """Intake, clarify scope, attach the recording and rule it RESPONSIVE."""
    request = create_request(
        api,
        requester_id,
        subject_incident_number=incident_number,
        requested_date_from=date_from,
        requested_date_to=date_to,
        scope_narrative=narrative,
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Arrest sequence only",
        requested_date_from=date_from,
        requested_date_to=date_to,
    )
    record = attach_record(api, request["id"], asset_id)
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return request["id"], record["id"]


def test_asserted_claim_freezes_its_own_weighted_redaction_minutes(api):
    """A JUVENILE partial claim over 45 minutes of footage freezes 36 minutes.

    PRD: "Otherwise the weight comes from the code: 0.30 for `ONGOING_INVESTIGATION`, 0.40 for `PERSONAL_PRIVACY`, 0.50 for `MEDICAL`, 0.60 for `VICTIM_PROTECTION`, 0.80 for `JUVENILE` and 0.90 for `CONFIDENTIAL_INFORMANT`."

    Design: Difficulty/dual_variant_calc/record_burden_variants_diverge_on_responsive_record
    """
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = _forty_five_minute_use_of_force(
        api, "INC-2026-0101", "AXON-0101", "2026-07-20T14:00:00Z"
    )
    _, record_id = _scoped_record(
        api,
        requester["id"],
        asset["id"],
        "INC-2026-0101",
        "2026-07-20T00:00:00Z",
        "2026-07-20T23:59:59Z",
        "All BWC video for incident INC-2026-0101",
    )

    claim = assert_claim(api, record_id, counsel["id"], "JUVENILE", "PARTIAL_REDACT")

    assert_fields(
        claim,
        status="ASSERTED",
        claim_source="STAFF_ANALYSIS",
        estimated_redaction_minutes=36,
    )
    assert get_claim(api, claim["id"])["estimated_redaction_minutes"] == 36


def test_record_burden_variants_diverge_by_exactly_the_asserted_claim(api):
    """Presumptive counts the asserted claim, adjudicated does not: 48 against 12.

    PRD: "The record's two burden figures are re-derived from the baseline obscuration plus a sum over claims: `presumptive_burden_minutes` is the baseline plus the total `estimated_redaction_minutes` of every claim on the record whose `status` is `ASSERTED` or `SUSTAINED`, while `adjudicated_burden_minutes` is the baseline plus the total over claims whose `status` is `SUSTAINED` only."

    Design: Difficulty/dual_variant_calc/record_burden_variants_diverge_on_responsive_record
    """
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = _forty_five_minute_use_of_force(
        api, "INC-2026-0101", "AXON-0101", "2026-07-20T14:00:00Z"
    )
    _, record_id = _scoped_record(
        api,
        requester["id"],
        asset["id"],
        "INC-2026-0101",
        "2026-07-20T00:00:00Z",
        "2026-07-20T23:59:59Z",
        "All BWC video for incident INC-2026-0101",
    )
    opened = get_record(api, record_id)
    assert opened["presumptive_burden_minutes"] == 12
    assert opened["adjudicated_burden_minutes"] == 12

    assert_claim(api, record_id, counsel["id"], "JUVENILE", "PARTIAL_REDACT")

    record = get_record(api, record_id)
    assert_fields(
        record,
        estimated_review_minutes=90,
        presumptive_burden_minutes=48,
        adjudicated_burden_minutes=12,
    )
    assert record["presumptive_burden_minutes"] - record["adjudicated_burden_minutes"] == 36


def test_asserted_claim_restricts_posture_and_bubbles_the_open_count(api):
    """One asserted claim makes the record RESTRICTED and is counted on both levels.

    PRD: "Otherwise, if any claim on the record has `status` `ASSERTED` or `SUSTAINED`, the posture is `RESTRICTED`."

    Design: Difficulty/dual_variant_calc/record_burden_variants_diverge_on_responsive_record
    """
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = _forty_five_minute_use_of_force(
        api, "INC-2026-0101", "AXON-0101", "2026-07-20T14:00:00Z"
    )
    request_id, record_id = _scoped_record(
        api,
        requester["id"],
        asset["id"],
        "INC-2026-0101",
        "2026-07-20T00:00:00Z",
        "2026-07-20T23:59:59Z",
        "All BWC video for incident INC-2026-0101",
    )

    assert_claim(api, record_id, counsel["id"], "JUVENILE", "PARTIAL_REDACT")

    assert_fields(
        get_record(api, record_id),
        release_posture="RESTRICTED",
        unadjudicated_claim_count=1,
    )
    assert_fields(
        get_request(api, request_id),
        unadjudicated_claim_count=1,
        processing_status="EXEMPTION_REVIEW",
    )


def _media_scenario(api):
    """A MEDIA filer, one 45-minute USE_OF_FORCE recording, one asserted JUVENILE claim."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(
        api, "City Herald", "desk@herald.example", "MEDIA", indigency_certified=False
    )
    asset = _forty_five_minute_use_of_force(
        api, "INC-2026-0102", "AXON-0102", "2026-07-21T09:00:00Z"
    )
    request_id, record_id = _scoped_record(
        api,
        requester["id"],
        asset["id"],
        "INC-2026-0102",
        "2026-07-21T00:00:00Z",
        "2026-07-21T23:59:59Z",
        "All BWC video for incident INC-2026-0102",
    )
    claim = assert_claim(api, record_id, counsel["id"], "JUVENILE", "PARTIAL_REDACT")
    return {
        "request_id": request_id,
        "record_id": record_id,
        "claim_id": claim["id"],
        "requester_id": requester["id"],
    }


def test_presumptive_estimate_prices_the_worst_case_burden(api):
    """PRESUMPTIVE takes the 48-minute presumptive figure: 78 billable minutes, 3549 cents.

    PRD: "**Third**, `projected_burden_minutes` is the total over the labour set of `presumptive_burden_minutes` when `basis` is `PRESUMPTIVE`, or of `adjudicated_burden_minutes` when `basis` is `ADJUDICATED`."

    Design: Difficulty/dual_variant_calc/fee_estimate_basis_variants_diverge_on_request
    """
    scenario = _media_scenario(api)

    estimate = create_estimate(
        api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD"
    )

    assert_fields(
        estimate,
        sequence_number=1,
        basis="PRESUMPTIVE",
        projected_review_minutes=90,
        projected_burden_minutes=48,
        billable_minutes=78,
        estimated_labor_cents=5460,
        media_production_cents=0,
        subtotal_cents=5460,
        waiver_credit_cents=1911,
        estimated_total_cents=3549,
        deposit_required_cents=1775,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.35)
    assert_money_is_integer_cents(
        estimate,
        "estimated_labor_cents",
        "media_production_cents",
        "subtotal_cents",
        "waiver_credit_cents",
        "estimated_total_cents",
        "deposit_required_cents",
    )


def test_adjudicated_estimate_prices_only_sustained_burden_and_supersedes(api):
    """ADJUDICATED takes the 12-minute figure: 42 billable minutes, 2205 cents, no deposit.

    PRD: "Otherwise — a positive total at or under the deposit threshold — the request moves to `fee_status` `ESTIMATED`."

    Design: Difficulty/dual_variant_calc/fee_estimate_basis_variants_diverge_on_request
    """
    scenario = _media_scenario(api)
    first = create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")

    second = create_estimate(
        api,
        scenario["request_id"],
        "ADJUDICATED",
        "DIGITAL_DOWNLOAD",
        expected_request_version=request_version(api, scenario["request_id"]),
    )

    assert_fields(
        second,
        sequence_number=2,
        basis="ADJUDICATED",
        status="ACTIVE",
        projected_review_minutes=90,
        projected_burden_minutes=12,
        billable_minutes=42,
        estimated_labor_cents=2940,
        subtotal_cents=2940,
        waiver_credit_cents=735,
        estimated_total_cents=2205,
        deposit_required_cents=0,
    )
    assert_waiver_pct(second, "effective_waiver_pct", 0.25)
    assert first["estimated_total_cents"] - second["estimated_total_cents"] == 1344

    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS)
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "ACTIVE"

    assert_fields(
        get_request(api, scenario["request_id"]),
        estimated_total_cents=2205,
        deposit_required_cents=0,
        fee_status="ESTIMATED",
        processing_status="EXEMPTION_REVIEW",
    )
    assert get_claim(api, scenario["claim_id"])["status"] == "ASSERTED"
