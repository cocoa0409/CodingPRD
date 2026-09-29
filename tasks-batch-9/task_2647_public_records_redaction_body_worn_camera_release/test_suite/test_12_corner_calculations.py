"""Corner cases of the arithmetic: double ceilings, weight precedence and hard caps.

Every figure asserted here is recomputed from the constants the PRD names, so a
formula that rounds at the wrong moment, keys a tier on the wrong intermediate
value or clamps at the wrong step produces a different number than the one pinned.
"""

from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_instant,
    assert_modified,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
    same_instant,
)
from test_helpers.factories import (
    adjudication_payload,
    exemption_claim_payload,
    fee_estimate_payload,
    inclusion_payload,
    notification_payload,
    responsive_record_payload,
    scope_clarification_payload,
)
from test_helpers.fixtures import (
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_individual,
    get_record,
    get_request,
    get_task,
    open_task,
    request_version,
    rule_inclusion,
    set_clock,
)
from test_helpers.test_users import CLERK_HEADERS, make_counsel_headers


def _three_ninety_second_recordings(api):
    """Three 90001 ms recordings differing only in classification, attached to one scoped request.

    90001 ms is one millisecond past ninety seconds, so the first ceiling yields
    two whole minutes and the review multiplier is applied to that two.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_routine = create_asset(
        api,
        incident_number="INC-2026-0620",
        device_serial="AXON-0620A",
        officer_badge="B-1120",
        recorded_start_at="2026-07-30T08:00:00Z",
        duration_ms=90001,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-30T00:00:00Z",
    )
    asset_juvenile = create_asset(
        api,
        incident_number="INC-2026-0620",
        device_serial="AXON-0620B",
        officer_badge="B-1121",
        recorded_start_at="2026-07-30T08:05:00Z",
        duration_ms=90001,
        classification="JUVENILE_CONTACT",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-30T00:00:00Z",
    )
    asset_ois = create_asset(
        api,
        incident_number="INC-2026-0620",
        device_serial="AXON-0620C",
        officer_badge="B-1122",
        recorded_start_at="2026-07-30T08:10:00Z",
        duration_ms=90001,
        classification="OFFICER_INVOLVED_SHOOTING",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-30T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0620",
        requested_date_from="2026-07-30T00:00:00Z",
        requested_date_to="2026-07-31T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0620",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="All three units",
        requested_date_from="2026-07-30T00:00:00Z",
        requested_date_to="2026-07-30T23:59:59Z",
    )
    records = {}
    for key, asset_id in (
        ("routine", asset_routine["id"]),
        ("juvenile", asset_juvenile["id"]),
        ("ois", asset_ois["id"]),
    ):
        records[key] = assert_created(
            api.attach_responsive_record(
                request["id"], responsive_record_payload(asset_id), CLERK_HEADERS
            )
        )
    return {"request_id": request["id"], "records": records}


def test_review_minutes_ceil_the_duration_before_applying_the_multiplier(api):
    """90001 ms is two whole minutes, so JUVENILE_CONTACT bills 5 minutes and OIS 6.

    PRD: "`estimated_review_minutes` is derived from the recording alone, in two steps: first the recording's `duration_ms` is divided by sixty thousand and rounded up to a whole number of minutes, then that minute count is multiplied by a review multiplier chosen by the recording's `classification` and the product is again rounded up to a whole minute."

    Design: Corner/calculations/review_minutes_ceil_the_duration_then_ceil_the_product
    """
    records = _three_ninety_second_recordings(api)["records"]

    assert records["routine"]["estimated_review_minutes"] == 2
    assert records["juvenile"]["estimated_review_minutes"] == 5
    assert records["ois"]["estimated_review_minutes"] == 6
    # Ceiling only the product would give 4 and 5 rather than 5 and 6.
    assert records["juvenile"]["estimated_review_minutes"] != 4
    assert records["ois"]["estimated_review_minutes"] != 5
    assert_fields(get_record(api, records["juvenile"]["id"]), estimated_review_minutes=5)
    assert_fields(get_record(api, records["ois"]["id"]), estimated_review_minutes=6)


def test_a_freshly_attached_record_opens_at_the_baseline_obscuration(api):
    """Two whole minutes of footage carry a one-minute baseline pass on both burden variants.

    PRD: "A freshly attached record therefore opens with both `presumptive_burden_minutes` and `adjudicated_burden_minutes` equal to that baseline figure, not at zero."

    Design: Corner/calculations/review_minutes_ceil_the_duration_then_ceil_the_product
    """
    scenario = _three_ninety_second_recordings(api)

    for key in ("routine", "juvenile", "ois"):
        assert_fields(
            scenario["records"][key],
            presumptive_burden_minutes=1,
            adjudicated_burden_minutes=1,
            inclusion_status="CANDIDATE",
            release_posture="OPEN",
            approved_labor_minutes=0,
            unadjudicated_claim_count=0,
            redacted_segment_ms=0,
            released_at=None,
        )
    assert_fields(get_request(api, scenario["request_id"]), responsive_record_count=3)


def _same_code_two_scopes(api):
    """Two 20-minute ROUTINE records, one carrying a FULL_WITHHOLD claim and one a PARTIAL_REDACT.

    Both claims name ONGOING_INVESTIGATION, so only `asserted_scope` differs and the
    baseline obscuration on each record is ceil(20 * 0.25) == 5 minutes.
    """
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0621",
        device_serial="AXON-0621A",
        officer_badge="B-1123",
        recorded_start_at="2026-07-29T10:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-29T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0621",
        device_serial="AXON-0621B",
        officer_badge="B-1124",
        recorded_start_at="2026-07-29T10:30:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-29T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0621",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-30T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0621",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both responding units",
        requested_date_from="2026-07-29T00:00:00Z",
        requested_date_to="2026-07-29T23:59:59Z",
    )
    record_a = attach_record(api, request["id"], asset_a["id"])
    record_b = attach_record(api, request["id"], asset_b["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    rule_inclusion(api, record_b["id"], "RESPONSIVE")
    claim_full = assert_created(
        api.assert_exemption_claim(
            record_a["id"],
            exemption_claim_payload("ONGOING_INVESTIGATION", "FULL_WITHHOLD"),
            make_counsel_headers(counsel["id"]),
        )
    )
    claim_partial = assert_created(
        api.assert_exemption_claim(
            record_b["id"],
            exemption_claim_payload("ONGOING_INVESTIGATION", "PARTIAL_REDACT"),
            make_counsel_headers(counsel["id"]),
        )
    )
    return {
        "request_id": request["id"],
        "record_a_id": record_a["id"],
        "record_b_id": record_b["id"],
        "counsel_id": counsel["id"],
        "claim_full": claim_full,
        "claim_partial": claim_partial,
    }


def test_full_withhold_scope_outweighs_the_exemption_code_weight(api):
    """The same ONGOING_INVESTIGATION code scores 20 minutes at FULL_WITHHOLD and 6 at PARTIAL.

    PRD: "The weight is 1.00 whenever `asserted_scope` is `FULL_WITHHOLD`, regardless of code, because withholding the whole recording means reviewing the whole recording."

    Design: Corner/calculations/full_withhold_scope_outweighs_the_exemption_code_weight
    """
    scenario = _same_code_two_scopes(api)

    assert scenario["claim_full"]["estimated_redaction_minutes"] == 20
    assert scenario["claim_full"]["estimated_redaction_minutes"] != 6
    assert scenario["claim_partial"]["estimated_redaction_minutes"] == 6
    for claim in (scenario["claim_full"], scenario["claim_partial"]):
        assert_fields(
            claim,
            status="ASSERTED",
            claim_source="STAFF_ANALYSIS",
            exemption_code="ONGOING_INVESTIGATION",
            statutory_citation="119.071(2)(c)",
            asserted_by_staff_id=scenario["counsel_id"],
            depicted_individual_id=None,
            adjudicated_by_staff_id=None,
            adjudicated_at=None,
        )


def test_asserted_claim_minutes_land_on_the_presumptive_burden_only(api):
    """A 20-minute claim lifts presumptive to 25 while adjudicated stays at the 5-minute baseline.

    PRD: "The record's two burden figures are re-derived from the baseline obscuration plus a sum over claims: `presumptive_burden_minutes` is the baseline plus the total `estimated_redaction_minutes` of every claim on the record whose `status` is `ASSERTED` or `SUSTAINED`, while `adjudicated_burden_minutes` is the baseline plus the total over claims whose `status` is `SUSTAINED` only."

    Design: Corner/calculations/full_withhold_scope_outweighs_the_exemption_code_weight
    """
    scenario = _same_code_two_scopes(api)

    assert_fields(
        get_record(api, scenario["record_a_id"]),
        presumptive_burden_minutes=25,
        adjudicated_burden_minutes=5,
        release_posture="RESTRICTED",
        unadjudicated_claim_count=1,
        inclusion_status="RESPONSIVE",
    )
    assert_fields(
        get_record(api, scenario["record_b_id"]),
        presumptive_burden_minutes=11,
        adjudicated_burden_minutes=5,
        release_posture="RESTRICTED",
        unadjudicated_claim_count=1,
        inclusion_status="RESPONSIVE",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=2,
        processing_status="EXEMPTION_REVIEW",
    )


def _dvd_boundary_scenario(api):
    """A 120-minute recording ruled RESPONSIVE and a spare one-minute recording left CANDIDATE.

    The first DVD estimate therefore prices exactly one disc, and the spare minute is
    in neither the labour set nor the media set until it is ruled responsive.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0624",
        device_serial="AXON-0624A",
        officer_badge="B-1125",
        recorded_start_at="2026-07-28T09:00:00Z",
        duration_ms=7200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-28T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0624",
        device_serial="AXON-0624B",
        officer_badge="B-1126",
        recorded_start_at="2026-07-28T11:00:00Z",
        duration_ms=60000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-28T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0624",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-29T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0624",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Primary unit, then the backup unit",
        requested_date_from="2026-07-28T00:00:00Z",
        requested_date_to="2026-07-28T23:59:59Z",
    )
    record_a = attach_record(api, request["id"], asset_a["id"])
    record_b = attach_record(api, request["id"], asset_b["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    first = assert_created(
        api.create_fee_estimate(
            request["id"],
            fee_estimate_payload(request_version(api, request["id"]), "PRESUMPTIVE", "DVD"),
            CLERK_HEADERS,
        )
    )
    return {"request_id": request["id"], "record_b_id": record_b["id"], "first": first}


def _supersede_with_the_extra_minute(api, scenario):
    """Rule the spare minute responsive and re-price, which crosses the disc boundary."""
    rule_inclusion(api, scenario["record_b_id"], "RESPONSIVE")
    return assert_created(
        api.create_fee_estimate(
            scenario["request_id"],
            fee_estimate_payload(
                request_version(api, scenario["request_id"]), "PRESUMPTIVE", "DVD"
            ),
            CLERK_HEADERS,
        )
    )


def test_one_hundred_twenty_produced_minutes_is_exactly_one_dvd(api):
    """120 produced minutes is one 500-cent disc, and the estimate totals 6120 cents.

    PRD: "For `DVD` the `disc_count` is `produced_minutes` divided by 120 and rounded up, and the cost is 500 cents per disc."

    Design: Corner/calculations/dvd_disc_boundary_at_one_hundred_twenty_produced_minutes
    """
    first = _dvd_boundary_scenario(api)["first"]

    assert_fields(
        first,
        basis="PRESUMPTIVE",
        media_type="DVD",
        status="ACTIVE",
        sequence_number=1,
        projected_review_minutes=120,
        projected_burden_minutes=30,
        billable_minutes=90,
        estimated_labor_cents=6300,
        media_production_cents=500,
        subtotal_cents=6800,
        waiver_credit_cents=680,
        estimated_total_cents=6120,
        deposit_required_cents=3060,
    )
    assert_waiver_pct(first, "effective_waiver_pct", 0.10)
    assert_money_is_integer_cents(
        first,
        "estimated_labor_cents",
        "media_production_cents",
        "subtotal_cents",
        "waiver_credit_cents",
        "estimated_total_cents",
        "deposit_required_cents",
    )


def test_one_hundred_twenty_one_produced_minutes_needs_a_second_disc(api):
    """One extra minute of footage doubles the media charge to 1000 cents.

    PRD: "The boundaries are exact: 120 produced minutes on DVD is precisely one disc and 121 minutes is two."

    Design: Corner/calculations/dvd_disc_boundary_at_one_hundred_twenty_produced_minutes
    """
    scenario = _dvd_boundary_scenario(api)

    second = _supersede_with_the_extra_minute(api, scenario)

    assert_fields(
        second,
        status="ACTIVE",
        sequence_number=2,
        projected_review_minutes=121,
        projected_burden_minutes=31,
        billable_minutes=92,
        estimated_labor_cents=6440,
        media_production_cents=1000,
        subtotal_cents=7440,
        waiver_credit_cents=744,
        estimated_total_cents=6696,
        deposit_required_cents=3348,
    )
    assert_waiver_pct(second, "effective_waiver_pct", 0.10)
    assert_fields(
        get_request(api, scenario["request_id"]),
        estimated_total_cents=6696,
        deposit_required_cents=3348,
        fee_status="DEPOSIT_DUE",
        responsive_record_count=2,
    )


def test_the_superseded_estimate_keeps_its_own_money_untouched(api):
    """The first estimate moves to SUPERSEDED but still reads 6120 cents at sequence 1.

    PRD: "Every estimate on the request whose `status` is `ACTIVE` or `STALE` moves to `SUPERSEDED`, the new estimate is created at `status` `ACTIVE`, and its `sequence_number` is the count of prior estimates on the request plus one, so the first estimate is number 1."

    Design: Corner/calculations/dvd_disc_boundary_at_one_hundred_twenty_produced_minutes
    """
    scenario = _dvd_boundary_scenario(api)
    second = _supersede_with_the_extra_minute(api, scenario)

    rows, _meta = assert_total_count(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 2
    )
    by_id = {row["id"]: row for row in rows}
    assert_fields(
        by_id[scenario["first"]["id"]],
        status="SUPERSEDED",
        sequence_number=1,
        media_production_cents=500,
        subtotal_cents=6800,
        estimated_total_cents=6120,
        deposit_required_cents=3060,
    )
    assert_fields(by_id[second["id"]], status="ACTIVE", sequence_number=2)


def _two_critical_anchors(api):
    """Two requests received on the same instant, one pointing at a February critical
    recording and one at a 25 July critical recording, each with its record still CANDIDATE."""
    requester = create_requester(api, "Nora News", "nora@example.org", "GENERAL_PUBLIC")
    asset_stale = create_asset(
        api,
        incident_number="INC-2026-0625",
        device_serial="AXON-0625",
        officer_badge="B-1127",
        recorded_start_at="2026-02-16T09:30:00Z",
        duration_ms=600000,
        classification="OFFICER_INVOLVED_SHOOTING",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-02-16T00:00:00Z",
        is_critical_incident=True,
    )
    asset_fresh = create_asset(
        api,
        incident_number="INC-2026-0626",
        device_serial="AXON-0626",
        officer_badge="B-1128",
        recorded_start_at="2026-07-25T06:00:00Z",
        duration_ms=600000,
        classification="IN_CUSTODY_DEATH",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-25T00:00:00Z",
        is_critical_incident=True,
    )
    stale_request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0625",
        requested_date_from="2026-02-16T00:00:00Z",
        requested_date_to="2026-02-17T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0625",
    )
    clarify_scope(
        api,
        stale_request["id"],
        scope_narrative="Shooting scene only",
        requested_date_from="2026-02-16T00:00:00Z",
        requested_date_to="2026-02-16T23:59:59Z",
    )
    stale_record = attach_record(api, stale_request["id"], asset_stale["id"])
    fresh_request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0626",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-26T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0626",
    )
    clarify_scope(
        api,
        fresh_request["id"],
        scope_narrative="Transport van only",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-25T23:59:59Z",
    )
    fresh_record = attach_record(api, fresh_request["id"], asset_fresh["id"])
    return {
        "stale_request_id": stale_request["id"],
        "stale_intake_deadline": stale_request["statutory_deadline_at"],
        "stale_record_id": stale_record["id"],
        "fresh_request_id": fresh_request["id"],
        "fresh_record_id": fresh_record["id"],
    }


def test_a_stale_critical_anchor_is_discarded_by_the_twenty_day_floor(api):
    """A February anchor's 45-day clock expired in April, so the 20-day floor wins.

    PRD: "**Step three applies a floor guard**: `statutory_deadline_at` is the later of the anchor advanced by the budget in whole days, and `received_at` advanced by twenty whole days."

    Design: Corner/calculations/critical_anchor_never_shortens_the_twenty_day_floor
    """
    scenario = _two_critical_anchors(api)
    assert_instant(
        scenario["stale_intake_deadline"],
        "2026-08-21T00:00:00Z",
        "stale_intake_deadline",
    )

    ruling = assert_modified(
        api.rule_inclusion(
            scenario["stale_record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
        )
    )

    assert_fields(ruling, inclusion_status="RESPONSIVE")
    request = get_request(api, scenario["stale_request_id"])
    assert_fields(
        request,
        is_critical_incident=True,
        statutory_deadline_at="2026-08-21T00:00:00Z",
        processing_status="EXEMPTION_REVIEW",
        tolled_days=0,
        extension_days_granted=0,
    )
    # The 45-day clock from 2026-02-16T09:30:00Z ran out long before the floor.
    assert not same_instant(request["statutory_deadline_at"], "2026-04-02T09:30:00Z")


def test_a_fresh_critical_anchor_pushes_the_deadline_out_past_the_floor(api):
    """A 25 July anchor plus 45 days lands on 2026-09-08T06:00:00Z with its time of day kept.

    PRD: "If the request's `is_critical_incident` is true and that gathered set is not empty, the anchor is the earliest `recorded_start_at` among those recordings; otherwise the anchor is `received_at`."

    Design: Corner/calculations/critical_anchor_never_shortens_the_twenty_day_floor
    """
    scenario = _two_critical_anchors(api)

    ruling = assert_modified(
        api.rule_inclusion(
            scenario["fresh_record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
        )
    )

    assert_fields(ruling, inclusion_status="RESPONSIVE")
    assert_fields(
        get_request(api, scenario["fresh_request_id"]),
        is_critical_incident=True,
        statutory_deadline_at="2026-09-08T06:00:00Z",
        processing_status="EXEMPTION_REVIEW",
        tolled_days=0,
        extension_days_granted=0,
    )


def _five_hour_in_custody_death(api):
    """A 300-minute IN_CUSTODY_DEATH recording ruled RESPONSIVE with no exemption claims.

    Review labour is ceil(300 * 3.0) == 900 minutes and the baseline obscuration is
    ceil(300 * 0.25) == 75, so 915 minutes remain after the free hour.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0627",
        device_serial="AXON-0627",
        officer_badge="B-1129",
        recorded_start_at="2026-07-27T02:00:00Z",
        duration_ms=18000000,
        classification="IN_CUSTODY_DEATH",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-27T00:00:00Z",
        is_critical_incident=True,
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0627",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-28T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0627",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Full five-hour continuous recording",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-27T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {"request_id": request["id"], "record_id": record["id"]}


def _capped_estimate(api, request_id):
    """Price the request on the presumptive basis with no media cost at all."""
    return assert_created(
        api.create_fee_estimate(
            request_id,
            fee_estimate_payload(
                request_version(api, request_id), "PRESUMPTIVE", "DIGITAL_DOWNLOAD"
            ),
            CLERK_HEADERS,
        )
    )


def test_the_statutory_ceiling_clamps_the_estimated_total(api):
    """A 64050-cent subtotal less a 12810-cent credit is 51240, which the 50000 ceiling clamps.

    PRD: "**Tenth**, `waiver_credit_cents` is `subtotal_cents` multiplied by `effective_waiver_pct`, rounded half up to a whole cent, and `estimated_total_cents` is the lesser of `subtotal_cents` less `waiver_credit_cents` and the statutory cost-recovery ceiling of 50000 cents."

    Design: Corner/calculations/statutory_cap_binds_the_total_and_the_deposit_follows_the_cap
    """
    scenario = _five_hour_in_custody_death(api)

    estimate = _capped_estimate(api, scenario["request_id"])

    assert_fields(
        estimate,
        status="ACTIVE",
        sequence_number=1,
        projected_review_minutes=900,
        projected_burden_minutes=75,
        billable_minutes=915,
        estimated_labor_cents=64050,
        media_production_cents=0,
        subtotal_cents=64050,
        waiver_credit_cents=12810,
        estimated_total_cents=50000,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.20)
    assert estimate["estimated_total_cents"] != 51240
    assert_money_is_integer_cents(
        estimate, "subtotal_cents", "waiver_credit_cents", "estimated_total_cents"
    )


def test_the_deposit_is_struck_from_the_capped_total(api):
    """Half of the capped 50000 is 25000, never half of the uncapped 51240.

    PRD: "**Eleventh**, `deposit_required_cents` is `estimated_total_cents` multiplied by one half and rounded half up when `estimated_total_cents` is **strictly greater** than 3500 cents, and is 0 otherwise — a total of exactly 3500 cents demands no deposit."

    Design: Corner/calculations/statutory_cap_binds_the_total_and_the_deposit_follows_the_cap
    """
    scenario = _five_hour_in_custody_death(api)

    estimate = _capped_estimate(api, scenario["request_id"])

    assert estimate["deposit_required_cents"] == 25000
    assert estimate["deposit_required_cents"] != 25620
    assert_money_is_integer_cents(estimate, "deposit_required_cents")


def test_the_capped_estimate_moves_the_request_to_deposit_due(api):
    """The request mirrors the capped figures and its deposit falls due thirty days out.

    PRD: "When `deposit_required_cents` comes out greater than 0, the request moves to `fee_status` `DEPOSIT_DUE` and `deposit_due_at` is set to the logical clock advanced by thirty whole days."

    Design: Corner/calculations/statutory_cap_binds_the_total_and_the_deposit_follows_the_cap
    """
    scenario = _five_hour_in_custody_death(api)

    _capped_estimate(api, scenario["request_id"])

    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="DEPOSIT_DUE",
        estimated_total_cents=50000,
        deposit_required_cents=25000,
        deposit_due_at="2026-08-31T00:00:00Z",
        deposit_paid_cents=0,
    )


def _july_request_without_records(api):
    """A request received on the clock's startup instant with no responsive record at all,
    so its anchor stays `received_at` and its intake deadline is the plain twenty-day floor."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    return create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0628",
        requested_date_from="2026-07-01T00:00:00Z",
        requested_date_to="2026-07-31T00:00:00Z",
        scope_narrative="Every BWC recording for July",
    )


def test_ten_extension_days_re_strike_the_deadline_ten_days_later(api):
    """The extension ceiling of ten days moves the deadline from 21 to 31 August.

    PRD: "The call then increments `scope_clarification_count` by 1, re-strikes `statutory_deadline_at` with the new extension, increments the request's `version` by 1, and marks any fee estimate on this request whose `status` is `ACTIVE` as `STALE`, because the scope it priced no longer exists."

    Design: Corner/calculations/extension_at_the_ceiling_extends_and_eleven_days_is_invalid_request
    """
    request = _july_request_without_records(api)
    assert_fields(
        request,
        statutory_deadline_at="2026-08-21T00:00:00Z",
        extension_days_granted=0,
        scope_clarification_count=0,
        version=1,
    )

    clarified = assert_modified(
        api.clarify_scope(
            request["id"],
            scope_clarification_payload(
                expected_request_version=request["version"],
                scope_narrative="Narrowed to the first week of July",
                requested_date_from="2026-07-01T00:00:00Z",
                requested_date_to="2026-07-07T23:59:59Z",
                extension_days_granted=10,
            ),
            CLERK_HEADERS,
        )
    )

    assert_fields(
        clarified,
        statutory_deadline_at="2026-08-31T00:00:00Z",
        extension_days_granted=10,
        scope_clarification_count=1,
        processing_status="SCOPING",
        version=2,
    )
    assert_fields(
        get_request(api, request["id"]),
        statutory_deadline_at="2026-08-31T00:00:00Z",
        extension_days_granted=10,
        scope_clarification_count=1,
        version=2,
    )


def _draft_task_under_a_privacy_claim(api):
    """A 20-minute responsive record with a PERSONAL_PRIVACY claim and one DRAFT FACE task."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    technician = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0629",
        device_serial="AXON-0629",
        officer_badge="B-1130",
        recorded_start_at="2026-07-26T20:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-26T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0629",
        requested_date_from="2026-07-26T00:00:00Z",
        requested_date_to="2026-07-27T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0629",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Lobby camera only",
        requested_date_from="2026-07-26T00:00:00Z",
        requested_date_to="2026-07-26T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    task = open_task(api, record["id"], technician["id"], "FACE", 0, 60000, claim["id"])
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "task_id": task["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_an_overruled_claim_cancels_its_task_and_bills_no_labour(api):
    """Overruling the claim cancels the DRAFT task it implemented and bills nothing.

    PRD: "But an overruled claim cancels only the redaction work that implemented **that specific claim**: every redaction task on the record whose `exemption_claim_id` names this claim and whose `status` is `DRAFT`, `QA_PENDING` or `QA_REJECTED` moves to `CANCELLED`, because the obscuration it performed is no longer authorised, while tasks on the same record tied to other claims or to the baseline pass are untouched."

    Design: Corner/calculations/record_with_only_cancelled_tasks_is_not_releasable
    """
    scenario = _draft_task_under_a_privacy_claim(api)
    assert get_task(api, scenario["task_id"])["status"] == "DRAFT"

    assert_modified(
        api.adjudicate_claim(
            scenario["claim_id"],
            adjudication_payload("OVERRULED", "No privacy interest survives"),
            make_counsel_headers(scenario["counsel_b_id"]),
        )
    )

    assert_fields(
        get_task(api, scenario["task_id"]),
        status="CANCELLED",
        approved_labor_minutes=0,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="OPEN",
        unadjudicated_claim_count=0,
        approved_labor_minutes=0,
        redacted_segment_ms=0,
        released_at=None,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=0,
        billable_labor_minutes=0,
    )
    assert_total_count(
        api.list_release_packages(scenario["request_id"], CLERK_HEADERS), 0
    )


def _witness_and_juvenile_awaiting_notice(api):
    """One responsive 20-minute recording depicting a WITNESS and a JUVENILE, clock at 14:30."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0630",
        device_serial="AXON-0630",
        officer_badge="B-1131",
        recorded_start_at="2026-07-24T13:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-24T00:00:00Z",
    )
    witness = create_depicted_individual(api, asset["id"], "SUBJECT-1", "WITNESS")
    juvenile = create_depicted_individual(api, asset["id"], "SUBJECT-2", "JUVENILE")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0630",
        requested_date_from="2026-07-24T00:00:00Z",
        requested_date_to="2026-07-25T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0630",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Interview room only",
        requested_date_from="2026-07-24T00:00:00Z",
        requested_date_to="2026-07-24T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    set_clock(api, "2026-08-05T14:30:00Z")
    return {
        "request_id": request["id"],
        "asset_id": asset["id"],
        "witness_id": witness["id"],
        "juvenile_id": juvenile["id"],
    }


def _issue_both_notices(api, scenario):
    """Notify both individuals in the same logical second, by different methods."""
    assert_modified(
        api.issue_notification(
            scenario["witness_id"], notification_payload("FIRST_CLASS_MAIL"), CLERK_HEADERS
        )
    )
    assert_modified(
        api.issue_notification(
            scenario["juvenile_id"], notification_payload("PERSONAL_SERVICE"), CLERK_HEADERS
        )
    )


def test_objection_window_is_ten_days_and_fifteen_for_a_juvenile(api):
    """Notified in the same second, the witness has until 15 August and the juvenile until 20.

    PRD: "Issuance moves the individual `PENDING → NOTIFIED`, stores the `notice_method`, stamps `notified_at` with the logical clock, and computes `objection_deadline_at` as `notified_at` advanced by fifteen whole days when the individual's `relationship` is `JUVENILE` and by ten whole days for every other relationship."

    Design: Corner/calculations/objection_window_is_ten_days_and_fifteen_for_a_juvenile
    """
    scenario = _witness_and_juvenile_awaiting_notice(api)

    _issue_both_notices(api, scenario)

    assert_fields(
        get_individual(api, scenario["witness_id"]),
        notification_status="NOTIFIED",
        notification_required=True,
        notice_method="FIRST_CLASS_MAIL",
        notified_at="2026-08-05T14:30:00Z",
        objection_deadline_at="2026-08-15T14:30:00Z",
    )
    assert_fields(
        get_individual(api, scenario["juvenile_id"]),
        notification_status="NOTIFIED",
        notification_required=True,
        notice_method="PERSONAL_SERVICE",
        notified_at="2026-08-05T14:30:00Z",
        objection_deadline_at="2026-08-20T14:30:00Z",
    )


def test_a_notified_individual_still_counts_as_an_open_notification(api):
    """Both notices leave open_notification_count at 2, because NOTIFIED is still open.

    PRD: "The request's `open_notification_count` counts the depicted individuals on the recordings behind this request's `RESPONSIVE` records whose `notification_status` is `PENDING`, `NOTIFIED` or `OBJECTED`."

    Design: Corner/calculations/objection_window_is_ten_days_and_fifteen_for_a_juvenile
    """
    scenario = _witness_and_juvenile_awaiting_notice(api)
    assert get_request(api, scenario["request_id"])["open_notification_count"] == 2

    _issue_both_notices(api, scenario)

    assert_fields(get_request(api, scenario["request_id"]), open_notification_count=2)
    assert_fields(get_asset(api, scenario["asset_id"]), depicted_individual_count=2)
