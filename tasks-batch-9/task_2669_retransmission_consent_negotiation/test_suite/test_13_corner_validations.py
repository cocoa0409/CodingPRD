"""Validation corners: the rules that refuse a write, and the boundary that lets it through.

Every test here drives one refusal named in the PRD's rejection precedence and,
where the same rule has an inside-the-window or inside-the-grant counterpart,
the passing case that proves the rule is measured where the PRD says it is.
"""

from test_helpers import (
    ACCEPTING_COUNSEL_USER_ID,
    ApiErrorId,
    accept_offer,
    agreement_version,
    append_good_faith_entry,
    approve_network,
    create_affiliation_agreement,
    create_audit_finding_payload,
    create_blackout_notice_payload,
    create_distributor,
    create_election,
    create_election_payload,
    create_fee_settlement_payload,
    create_interim_extension_payload,
    create_offer_payload,
    create_rights_dispute_payload,
    create_station,
    create_subscriber_report,
    create_subscriber_report_payload,
    declare_impasse_payload,
    execute_agreement,
    file_election,
    make_carriage_admin_headers,
    make_compliance_officer_headers,
    make_distributor_rep_headers,
    make_group_counsel_headers,
    make_station_negotiator_headers,
    open_audit_finding,
    read_agreement,
    read_blackout_notices,
    read_election,
    read_extensions,
    read_negotiation,
    read_settlements,
    read_station,
    read_subscriber_report,
    run_expiration_sweep,
    serve_blackout_notice,
    set_clock,
    setup_accepted_agreement,
    setup_executed_agreement,
    setup_issued_settlement,
    setup_negotiation_with_report,
    setup_open_negotiation,
    setup_submitted_station_offer,
    submit_distributor_offer,
    true_up_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_carriage_admin_headers()
COMPLIANCE = make_compliance_officer_headers()
COUNSEL = make_group_counsel_headers(ACCEPTING_COUNSEL_USER_ID)


def _affiliation_paper(network_name, permitted_tiers):
    """An affiliation payload that omits the three grantable-rights flags."""
    return {
        "network_name": network_name,
        "term_end_utc": "2032-01-01T00:00:00Z",
        "reverse_comp_floor_per_sub_cents": 90,
        "split_premium_bp": 500,
        "permitted_tiers": permitted_tiers,
    }


# ------------------------------------------------ corner_duplicate_election_on_same_slot_rejected
def _station_distributor_and_draft_election():
    station = create_station()
    distributor = create_distributor()
    election = create_election(station["id"], distributor["id"], cycle_label="2027-2029")
    return station, distributor, election


def test_a_second_election_on_the_same_station_distributor_cycle_slot_is_refused(api):
    """A live election holds the slot even against a differently-typed replacement.

    PRD §3.3: "If an election already exists for the same station, distributor and
    `cycle_label` combination whose status is neither `CONSENT_GRANTED` nor
    `ELECTION_LAPSED`, a second one is refused with `ERR_DUPLICATE_ELECTION`."

    Design: Corner/validations/corner_duplicate_election_on_same_slot_rejected
    """
    station, distributor, election = _station_distributor_and_draft_election()

    response = api.create_election(
        create_election_payload(
            station["id"],
            distributor["id"],
            cycle_label="2027-2029",
            election_type="MUST_CARRY",
            requested_tier="BROADCAST_BASIC",
            incumbent_rate_per_sub_cents=0,
        ),
        make_station_negotiator_headers(station["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ELECTION.value, 422)

    held = read_election(election["id"])
    assert held["status"] == "DRAFT"
    assert held["election_type"] == "RETRANS_CONSENT"
    assert read_station(station["id"])["filed_election_count"] == 0


def test_a_different_cycle_label_on_the_same_slot_opens_its_own_draft_election(api):
    """Uniqueness is keyed on the cycle too, so the next cycle is not a duplicate.

    PRD §3.3: "If an election already exists for the same station, distributor and
    `cycle_label` combination whose status is neither `CONSENT_GRANTED` nor
    `ELECTION_LAPSED`, a second one is refused with `ERR_DUPLICATE_ELECTION`."

    Design: Corner/validations/corner_duplicate_election_on_same_slot_rejected
    """
    station, distributor, _ = _station_distributor_and_draft_election()

    response = api.create_election(
        create_election_payload(
            station["id"],
            distributor["id"],
            cycle_label="2030-2032",
            incumbent_expiry_utc="2030-01-01T00:00:00Z",
            incumbent_rate_per_sub_cents=240,
        ),
        make_station_negotiator_headers(station["id"]),
    )
    second = validate_success(response, 201)

    assert second["cycle_label"] == "2030-2032"
    assert second["status"] == "DRAFT"
    assert read_station(station["id"])["filed_election_count"] == 0


# --------------------------------------------------- corner_duplicate_report_period_rejected
def _station_distributor_and_january_report():
    station = create_station()
    distributor = create_distributor()
    report = create_subscriber_report(
        station["id"],
        distributor["id"],
        period_label="2027-01",
        reported_subscriber_count=100000,
    )
    return station, distributor, report


def test_a_second_report_for_the_same_period_label_is_refused_not_upserted(api):
    """The duplicate period is refused outright and the filed count is left alone.

    PRD §3.4: "At most one report may exist for a given station, distributor and
    `period_label` combination; a second is refused with `ERR_REPORT_PERIOD_DUPLICATE`."

    Design: Corner/validations/corner_duplicate_report_period_rejected
    """
    station, distributor, report = _station_distributor_and_january_report()

    response = api.create_subscriber_report(
        create_subscriber_report_payload(
            station["id"],
            period_label="2027-01",
            reported_subscriber_count=101000,
        ),
        make_distributor_rep_headers(distributor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_DUPLICATE.value, 422)

    kept = read_subscriber_report(report["id"])
    assert kept["reported_subscriber_count"] == 100000
    assert kept["status"] == "REPORTED"


def test_the_next_period_label_is_accepted_and_prices_its_own_basis(api):
    """A February report is a different slot and takes its own billable basis.

    PRD §3.4: "Under `BILLED_HOUSEHOLDS` the basis is the adjusted count unchanged,
    because a billed household already is a household."

    Design: Corner/validations/corner_duplicate_report_period_rejected
    """
    station, distributor, _ = _station_distributor_and_january_report()

    response = api.create_subscriber_report(
        create_subscriber_report_payload(
            station["id"],
            period_label="2027-02",
            period_start_utc="2027-02-01T00:00:00Z",
            period_end_utc="2027-03-01T00:00:00Z",
            reported_subscriber_count=101000,
        ),
        make_distributor_rep_headers(distributor["id"]),
    )
    february = validate_success(response, 201)

    assert february["period_label"] == "2027-02"
    assert february["billable_subscriber_basis"] == 101000
    assert february["as_reported_basis"] == 101000


# ------------------------------------------- corner_affiliation_network_mismatch_rejected
def _cbs_and_independent_stations():
    cbs = create_station(call_sign="WXYZ", network_affiliation="CBS")
    independent = create_station(call_sign="KIND", network_affiliation="INDEPENDENT")
    return cbs, independent


def test_an_affiliation_paper_naming_the_wrong_network_or_an_independent_station_is_refused(api):
    """A CBS station cannot hold NBC paper, and an INDEPENDENT station holds none at all.

    PRD §3.1: "A mismatch is refused with `ERR_NETWORK_MISMATCH`, and so is any attempt
    to attach an affiliation agreement at all to a station whose `network_affiliation`
    is `INDEPENDENT` - an independent station has no network counterparty and therefore
    no affiliation contract to hold."

    Design: Corner/validations/corner_affiliation_network_mismatch_rejected
    """
    cbs, independent = _cbs_and_independent_stations()

    validate_error(
        api.create_affiliation_agreement(
            cbs["id"], _affiliation_paper("NBC", ["BROADCAST_BASIC"]), ADMIN
        ),
        ApiErrorId.ERR_NETWORK_MISMATCH.value,
        422,
    )
    validate_error(
        api.create_affiliation_agreement(
            independent["id"], _affiliation_paper("CBS", ["BROADCAST_BASIC"]), ADMIN
        ),
        ApiErrorId.ERR_NETWORK_MISMATCH.value,
        422,
    )

    _, cbs_meta = validate_paginated(api.list_affiliation_agreements(cbs["id"], ADMIN))
    assert cbs_meta["total_count"] == 0
    _, ind_meta = validate_paginated(
        api.list_affiliation_agreements(independent["id"], ADMIN)
    )
    assert ind_meta["total_count"] == 0


def test_matching_affiliation_paper_attaches_active_with_every_right_withheld(api):
    """The matching network attaches, and rights the paper never mentions stay withheld.

    PRD §3.1: "Each defaults to false when omitted, meaning that unless the network has
    explicitly licensed the station to pass a right along, the station may not offer it."

    Design: Corner/validations/corner_affiliation_network_mismatch_rejected
    """
    cbs, _ = _cbs_and_independent_stations()

    response = api.create_affiliation_agreement(
        cbs["id"],
        _affiliation_paper("CBS", ["BROADCAST_BASIC", "EXPANDED_BASIC"]),
        ADMIN,
    )
    paper = validate_success(response, 201)

    assert paper["status"] == "ACTIVE"
    assert paper["digital_rights_grantable"] is False
    assert paper["ooh_rights_grantable"] is False
    assert paper["streaming_rights_grantable"] is False
    assert paper["permitted_tiers"] == ["BROADCAST_BASIC", "EXPANDED_BASIC"]


# ------------------------------------ corner_election_filing_window_boundary_and_closure
def _two_slots_awaiting_filing():
    station = create_station()
    create_affiliation_agreement(station["id"])
    dist_a = create_distributor(name="Cascade Cable", distributor_type="CABLE")
    dist_b = create_distributor(
        name="Rainier Broadband",
        distributor_type="TELCO",
        video_household_count=120000,
    )
    election_a = create_election(station["id"], dist_a["id"])
    election_b = create_election(
        station["id"], dist_b["id"], incumbent_rate_per_sub_cents=200
    )
    return station, election_a, election_b


def test_filing_exactly_at_the_election_deadline_instant_is_permitted(api):
    """The deadline instant itself is inside the filing window.

    PRD §2.5: "The election deadline, `ELECTION_DEADLINE_UTC`, is
    `2026-10-01T00:00:00Z`: a carriage election may be amended, filed or withdrawn only
    while the logical clock is at or before that instant, and acting exactly at the
    deadline instant is permitted."

    Design: Corner/validations/corner_election_filing_window_boundary_and_closure
    """
    station, election_a, _ = _two_slots_awaiting_filing()
    set_clock("2026-10-01T00:00:00Z")

    response = api.file_election(
        election_a["id"], {}, make_station_negotiator_headers(station["id"])
    )
    filed = validate_success(response, 200)

    assert filed["status"] == "NEGOTIATING"
    assert filed["filed_at_utc"] == "2026-10-01T00:00:00Z"
    assert read_station(station["id"])["filed_election_count"] == 1


def test_filing_one_day_past_the_deadline_is_refused_and_opens_no_negotiation(api):
    """Past the deadline the fork never happens: no filing stamp, no negotiation.

    PRD §2.8: "The logical clock is at or before `ELECTION_DEADLINE_UTC` -
    `ERR_ELECTION_WINDOW_CLOSED`. Applies to amending, filing and withdrawing an
    election."

    Design: Corner/validations/corner_election_filing_window_boundary_and_closure
    """
    station, election_a, election_b = _two_slots_awaiting_filing()
    set_clock("2026-10-01T00:00:00Z")
    file_election(election_a["id"], station["id"])

    set_clock("2026-10-02T00:00:00Z")
    validate_error(
        api.file_election(
            election_b["id"], {}, make_station_negotiator_headers(station["id"])
        ),
        ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value,
        422,
    )

    late = read_election(election_b["id"])
    assert late["status"] == "DRAFT"
    assert late["filed_at_utc"] is None
    _, meta = validate_paginated(api.list_election_negotiations(election_b["id"], ADMIN))
    assert meta["total_count"] == 0
    assert read_station(station["id"])["filed_election_count"] == 1


# ------------------------------ corner_rate_cap_measured_across_whole_projected_ladder
def test_a_compliant_base_rate_whose_year_three_escalation_breaches_the_cap_is_refused(api):
    """560 cents at 700 basis points reaches 641 in year three and the offer dies there.

    PRD §3.5: "If any per-subscriber rate in the projected ladder exceeds 600 cents, the
    offer is refused with `ERR_RATE_CAP_EXCEEDED` - a base rate that is itself compliant
    but whose year-N escalated rate breaches the ceiling is still rejected."

    Design: Corner/validations/corner_rate_cap_measured_across_whole_projected_ladder
    """
    ctx = setup_negotiation_with_report()

    response = api.create_offer(
        ctx["negotiation"]["id"],
        create_offer_payload(
            ctx["report"]["id"],
            base_rate_per_sub_cents=560,
            escalator_bp_per_year=700,
            term_months=36,
        ),
        ctx["negotiator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_RATE_CAP_EXCEEDED.value, 422)

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["round_number"] == 0
    assert negotiation["station_offer_count"] == 0
    assert negotiation["status"] == "OPEN"


def test_the_same_base_rate_over_a_two_year_ladder_stays_inside_the_cap(api):
    """Over 24 months the ladder stops at 599 cents and the offer is priced.

    PRD §3.5: "Under the **compound-annual** convention - the one quoted during
    negotiation, stored as `year_rate_schedule_compound_cents` - year one's rate is
    `base_rate_per_sub_cents` exactly, and each later year's rate is the previous year's
    *already-rounded* rate multiplied by ten thousand plus `escalator_bp_per_year`,
    divided by ten thousand, and rounded half up to whole cents."

    Design: Corner/validations/corner_rate_cap_measured_across_whole_projected_ladder
    """
    ctx = setup_negotiation_with_report()

    response = api.create_offer(
        ctx["negotiation"]["id"],
        create_offer_payload(
            ctx["report"]["id"],
            base_rate_per_sub_cents=560,
            escalator_bp_per_year=700,
            term_months=24,
        ),
        ctx["negotiator_headers"],
    )
    offer = validate_success(response, 201)

    assert offer["year_rate_schedule_compound_cents"] == [560, 599]
    assert offer["round_number"] == 1
    assert read_negotiation(ctx["negotiation"]["id"])["station_offer_count"] == 1


# ------------------------- corner_report_from_another_distributor_is_not_priceable
def test_an_offer_priced_against_another_distributors_report_is_not_priceable(api):
    """The report must come from the election's own counterparty pair, or 422.

    PRD §3.5: "Fourth, the referenced subscriber report must belong to the same
    station-and-distributor pair as the parent election and must be in status
    `REPORTED`, `UNDER_AUDIT`, `ADJUSTED` or `ACCEPTED`; a report drawn from a different
    counterparty pair is refused with `ERR_REPORT_NOT_PRICEABLE`."

    Design: Corner/validations/corner_report_from_another_distributor_is_not_priceable
    """
    ctx = setup_negotiation_with_report()
    other_distributor = create_distributor(
        name="Rainier Broadband",
        distributor_type="TELCO",
        video_household_count=120000,
    )
    foreign_report = create_subscriber_report(
        ctx["station"]["id"],
        other_distributor["id"],
        reported_subscriber_count=60000,
    )

    validate_error(
        api.create_offer(
            ctx["negotiation"]["id"],
            create_offer_payload(foreign_report["id"]),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_REPORT_NOT_PRICEABLE.value,
        422,
    )

    priced = validate_success(
        api.create_offer(
            ctx["negotiation"]["id"],
            create_offer_payload(ctx["report"]["id"]),
            ctx["negotiator_headers"],
        ),
        201,
    )
    assert priced["projection_basis_subscribers"] == 100000

    untouched = read_subscriber_report(foreign_report["id"])
    assert untouched["billable_subscriber_basis"] == 60000
    assert untouched["status"] == "REPORTED"


# ------------- corner_offer_outside_affiliation_grant_rejected_on_tier_and_rights
def test_an_unpermitted_tier_and_an_ungranted_right_each_refuse_the_offer(api):
    """The affiliation gates both dimensions of an offer with its own error each.

    PRD §3.5: "Third, the offered `tier` must appear in that affiliation agreement's
    `permitted_tiers`, or the refusal is `ERR_TIER_NOT_PERMITTED`."

    Design: Corner/validations/corner_offer_outside_affiliation_grant_rejected_on_tier_and_rights
    """
    ctx = setup_negotiation_with_report()

    validate_error(
        api.create_offer(
            ctx["negotiation"]["id"],
            create_offer_payload(ctx["report"]["id"], tier="DIGITAL_TIER"),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_TIER_NOT_PERMITTED.value,
        422,
    )
    validate_error(
        api.create_offer(
            ctx["negotiation"]["id"],
            create_offer_payload(ctx["report"]["id"], includes_ooh_rights=True),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_RIGHTS_NOT_GRANTABLE.value,
        422,
    )

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["round_number"] == 0
    assert negotiation["station_offer_count"] == 0
    assert ctx["affiliation"]["ooh_rights_grantable"] is False


def test_an_offer_breaching_both_the_grant_and_the_tier_reports_the_rights_failure(api):
    """The grantable-rights check is evaluated before the tier check, so rights wins.

    PRD §2.8: "Every right inside the offer is grantable under the station's affiliation
    contract - `ERR_RIGHTS_NOT_GRANTABLE`. Applies to submitting an offer."

    Design: Corner/validations/corner_offer_outside_affiliation_grant_rejected_on_tier_and_rights
    """
    ctx = setup_negotiation_with_report()

    response = api.create_offer(
        ctx["negotiation"]["id"],
        create_offer_payload(
            ctx["report"]["id"], tier="DIGITAL_TIER", includes_ooh_rights=True
        ),
        ctx["negotiator_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_RIGHTS_NOT_GRANTABLE.value, 422)

    assert error["error_id"] != ApiErrorId.ERR_TIER_NOT_PERMITTED.value
    assert read_negotiation(ctx["negotiation"]["id"])["round_number"] == 0


# --------------------- corner_audit_window_boundary_at_one_hundred_eighty_days
def _reported_january_report():
    station = create_station()
    distributor = create_distributor()
    report = create_subscriber_report(station["id"], distributor["id"])
    return station, distributor, report


def test_a_finding_opened_on_the_one_hundred_eightieth_day_is_inside_the_window(api):
    """180 days from a 2027-02-01 period end lands on 2027-07-31, still auditable.

    PRD §3.4: "The audit-rights window runs for 180 days from the report's
    `period_end_utc`, and a finding may be opened only while the logical clock is at or
    before that instant - the boundary day itself is inside the window."

    Design: Corner/validations/corner_audit_window_boundary_at_one_hundred_eighty_days
    """
    station, _, report = _reported_january_report()
    set_clock("2027-07-31T00:00:00Z")

    response = api.create_audit_finding(
        report["id"],
        create_audit_finding_payload(adjustment_subscribers=6000),
        make_station_negotiator_headers(station["id"]),
    )
    finding = validate_success(response, 201)

    assert finding["status"] == "OPEN"
    assert finding["opened_at_utc"] == "2027-07-31T00:00:00Z"
    assert read_subscriber_report(report["id"])["status"] == "UNDER_AUDIT"


def test_a_finding_opened_one_day_past_the_window_is_refused(api):
    """One day past the boundary the audit right is gone and nothing is recorded.

    PRD §3.4: "Past it, the request is refused with `ERR_AUDIT_WINDOW_EXPIRED`."

    Design: Corner/validations/corner_audit_window_boundary_at_one_hundred_eighty_days
    """
    station, _, report = _reported_january_report()
    set_clock("2027-07-31T00:00:00Z")
    open_audit_finding(report["id"], station["id"], adjustment_subscribers=6000)

    set_clock("2027-08-01T00:00:00Z")
    validate_error(
        api.create_audit_finding(
            report["id"],
            create_audit_finding_payload(
                adjustment_subscribers=1200,
                basis_note="Second look at commercial accounts",
            ),
            make_station_negotiator_headers(station["id"]),
        ),
        ApiErrorId.ERR_AUDIT_WINDOW_EXPIRED.value,
        422,
    )

    findings, meta = validate_paginated(api.list_audit_findings(report["id"], ADMIN))
    assert meta["total_count"] == 1
    assert findings[0]["status"] == "OPEN"
    assert read_subscriber_report(report["id"])["audit_adjustment_subscribers"] == 0


# ------------------------------ corner_blackout_notice_after_deadline_rejected
def test_a_notice_served_exactly_on_the_deadline_instant_is_timely(api):
    """For a CABLE distributor the deadline is the incumbent expiry less 30 days.

    PRD §3.6: "The **blackout notice deadline** is derived when the negotiation is
    created and re-read whenever a notice is served: the required notice period is 30
    days for a distributor whose `distributor_type` is `CABLE`, `DBS` or `TELCO`, and 14
    days for a `VMVPD`, which is exactly the value carried on the distributor as
    `required_blackout_notice_days`; the deadline instant,
    `blackout_notice_deadline_utc`, is the parent election's `incumbent_expiry_utc` with
    that many whole days subtracted."

    Design: Corner/validations/corner_blackout_notice_after_deadline_rejected
    """
    ctx = setup_open_negotiation()
    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["blackout_notice_deadline_utc"] == "2026-12-02T00:00:00Z"

    set_clock("2026-12-02T00:00:00Z")
    response = api.create_blackout_notice(
        ctx["negotiation"]["id"],
        create_blackout_notice_payload(notice_channel="BILL_INSERT"),
        COMPLIANCE,
    )
    notice = validate_success(response, 201)

    assert notice["served_at_utc"] == "2026-12-02T00:00:00Z"
    assert notice["required_notice_days_snapshot"] == 30
    assert notice["status"] == "SERVED"
    assert (
        read_negotiation(ctx["negotiation"]["id"])["notice_compliance_status"]
        == "NOTICE_SERVED"
    )


def test_a_notice_served_one_day_after_the_deadline_is_refused(api):
    """Late service is refused and the already-served notice is left alone.

    PRD §3.6: "Service after the deadline is refused with `ERR_BLACKOUT_NOTICE_LATE`, and
    service on a `CONSENTED` or `CANCELLED` negotiation with `ERR_NEGOTIATION_NOT_OPEN`."

    Design: Corner/validations/corner_blackout_notice_after_deadline_rejected
    """
    ctx = setup_open_negotiation()
    set_clock("2026-12-02T00:00:00Z")
    serve_blackout_notice(ctx["negotiation"]["id"], notice_channel="BILL_INSERT")

    set_clock("2026-12-03T00:00:00Z")
    validate_error(
        api.create_blackout_notice(
            ctx["negotiation"]["id"],
            create_blackout_notice_payload(notice_channel="ON_AIR_CRAWL"),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_BLACKOUT_NOTICE_LATE.value,
        422,
    )

    notices = read_blackout_notices(ctx["negotiation"]["id"])
    assert len(notices) == 1
    assert notices[0]["status"] == "SERVED"


# ------------------------------- corner_impasse_requires_offers_from_both_sides
def _three_meetings_and_one_station_offer():
    ctx = setup_submitted_station_offer()
    negotiation_id = ctx["negotiation"]["id"]
    append_good_faith_entry(
        negotiation_id,
        ctx["negotiator_headers"],
        occurred_at_utc="2026-08-05T00:00:00Z",
        summary="Opening session in Seattle",
    )
    append_good_faith_entry(
        negotiation_id,
        ctx["rep_headers"],
        occurred_at_utc="2026-08-12T00:00:00Z",
        summary="Second session on rate structure",
    )
    ctx["third_entry"] = append_good_faith_entry(
        negotiation_id,
        COMPLIANCE,
        occurred_at_utc="2026-08-19T00:00:00Z",
        summary="Third session on tier placement",
    )
    return ctx


def test_impasse_with_three_meetings_but_only_a_station_offer_is_refused(api):
    """The good-faith count is satisfied, so the bilateral-offer test is what fails.

    PRD §3.6: "Separately, at least one offer must exist from each side - at least one
    with `offered_by` of `STATION_GROUP` and at least one with `offered_by` of
    `DISTRIBUTOR` - and a negotiation where only one side has ever tabled anything is
    refused with `ERR_NO_OFFERS_EXCHANGED`."

    Design: Corner/validations/corner_impasse_requires_offers_from_both_sides
    """
    ctx = _three_meetings_and_one_station_offer()
    assert ctx["third_entry"]["sequence_index"] == 3

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["good_faith_meeting_count"] == 3
    assert negotiation["station_offer_count"] == 1
    assert negotiation["distributor_offer_count"] == 0

    error = validate_error(
        api.declare_impasse(
            ctx["negotiation"]["id"],
            declare_impasse_payload(
                impasse_statement="No movement on rate after three sessions"
            ),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_NO_OFFERS_EXCHANGED.value,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_GOOD_FAITH_NOT_SATISFIED.value
    assert read_negotiation(ctx["negotiation"]["id"])["status"] != "IMPASSE"


def test_impasse_succeeds_the_moment_the_distributor_counters(api):
    """With both sides on record the declaration lands and notice becomes pending.

    PRD §3.6: "Declaring impasse stamps `impasse_declared_at_utc` from the current
    logical clock, recomputes `notice_compliance_status`, and increments the
    negotiation's `version` by one."

    Design: Corner/validations/corner_impasse_requires_offers_from_both_sides
    """
    ctx = _three_meetings_and_one_station_offer()
    submit_distributor_offer(
        ctx["negotiation"]["id"],
        ctx["distributor"]["id"],
        ctx["report"]["id"],
        base_rate_per_sub_cents=190,
        escalator_bp_per_year=300,
        penetration_commitment_bp=3800,
    )

    response = api.declare_impasse(
        ctx["negotiation"]["id"],
        declare_impasse_payload(
            impasse_statement="No movement on rate after three sessions"
        ),
        ctx["negotiator_headers"],
    )
    negotiation = validate_success(response, 200)

    assert negotiation["status"] == "IMPASSE"
    assert negotiation["impasse_declared_at_utc"] == "2026-08-01T00:00:00Z"
    assert negotiation["notice_compliance_status"] == "NOTICE_PENDING"
    assert negotiation["station_offer_count"] == 1
    assert negotiation["distributor_offer_count"] == 1


# ------- corner_extension_basis_needing_a_station_offer_rejected_when_none_exists
def _executed_agreement_off_a_distributor_offer():
    ctx = setup_negotiation_with_report()
    ctx["offer"] = submit_distributor_offer(
        ctx["negotiation"]["id"],
        ctx["distributor"]["id"],
        ctx["report"]["id"],
        base_rate_per_sub_cents=210,
        escalator_bp_per_year=500,
        penetration_commitment_bp=3900,
    )
    ctx["agreement"] = accept_offer(ctx["offer"]["id"], ctx["negotiation"]["id"])
    ctx["agreement"] = approve_network(ctx["agreement"]["id"])
    ctx["agreement"] = execute_agreement(ctx["agreement"]["id"])
    return ctx


def test_extension_bases_reading_the_station_offer_pool_fail_when_it_is_empty(api):
    """Consent taken off a distributor offer leaves no station offer to read.

    PRD §3.8: "Because `PRIOR_RATE` never touches the offer pool, an empty candidate set
    is an error only for `LAST_STATION_OFFER` and `MIDPOINT`, and in those two cases the
    request is refused with `ERR_NO_STATION_OFFER_ON_RECORD`."

    Design: Corner/validations/corner_extension_basis_needing_a_station_offer_rejected_when_none_exists
    """
    ctx = _executed_agreement_off_a_distributor_offer()
    assert ctx["offer"]["offered_by"] == "DISTRIBUTOR"
    version_before = agreement_version(ctx["agreement"]["id"])

    for basis in ("LAST_STATION_OFFER", "MIDPOINT"):
        validate_error(
            api.create_interim_extension(
                ctx["agreement"]["id"],
                create_interim_extension_payload(
                    version_before,
                    extension_days=30,
                    extension_start_utc="2030-01-01T00:00:00Z",
                    extension_rate_basis=basis,
                ),
                ctx["negotiator_headers"],
            ),
            ApiErrorId.ERR_NO_STATION_OFFER_ON_RECORD.value,
            422,
        )

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 0
    assert agreement["version"] == version_before
    assert read_extensions(ctx["agreement"]["id"]) == []


def test_prior_rate_extension_succeeds_at_the_elections_incumbent_rate(api):
    """PRIOR_RATE never consults the offer pool, so it bills the incumbent 220 cents.

    PRD §3.8: "The prior rate is the `incumbent_rate_per_sub_cents` of the election
    reached from the agreement through its negotiation."

    Design: Corner/validations/corner_extension_basis_needing_a_station_offer_rejected_when_none_exists
    """
    ctx = _executed_agreement_off_a_distributor_offer()
    version_before = agreement_version(ctx["agreement"]["id"])

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            version_before,
            extension_days=30,
            extension_start_utc="2030-01-01T00:00:00Z",
            extension_rate_basis="PRIOR_RATE",
        ),
        ctx["negotiator_headers"],
    )
    extension = validate_success(response, 201)

    assert extension["effective_rate_per_sub_cents"] == 220
    assert extension["extension_end_utc"] == "2030-01-31T00:00:00Z"
    assert extension["status"] == "ACTIVE"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 30
    assert agreement["version"] == version_before + 1


# ------- corner_settlement_gated_on_execution_and_true_up_precondition
def test_a_settlement_issued_before_execution_is_refused(api):
    """Money only moves once the agreement is EXECUTED, not merely accepted.

    PRD §2.8: "Network approval and execution require `execution_status` equal to
    `PENDING_EXECUTION`; creating an interim extension, raising a rights dispute and
    issuing a fee settlement all require `execution_status` equal to `EXECUTED`."

    Design: Corner/validations/corner_settlement_gated_on_execution_and_true_up_precondition
    """
    ctx = setup_accepted_agreement()
    assert ctx["agreement"]["execution_status"] == "PENDING_EXECUTION"

    validate_error(
        api.create_fee_settlement(
            ctx["agreement"]["id"],
            create_fee_settlement_payload(ctx["report"]["id"]),
            COUNSEL,
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_PENDING_EXECUTION.value,
        409,
    )

    assert read_settlements(ctx["agreement"]["id"]) == []
    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 0
    assert agreement["lifetime_net_retained_cents"] == 0


def test_truing_up_an_unadjusted_report_is_refused_and_leaves_the_split_intact(api):
    """The issued split stands and an unadjusted report has nothing to reconcile.

    PRD §3.9: "A `GroupCounsel` trues up a settlement by supplying a `true_up_note`; the
    settlement must be in `ISSUED`, and the referenced subscriber report's
    `audit_adjustment_subscribers` must be non-zero - an unadjusted report has nothing to
    true up, and the attempt is refused with `ERR_TRUE_UP_NOT_REQUIRED`."

    Design: Corner/validations/corner_settlement_gated_on_execution_and_true_up_precondition
    """
    ctx = setup_issued_settlement()
    settlement = ctx["settlement"]
    assert settlement["contract_year_index"] == 1
    assert settlement["rate_per_sub_cents"] == 250
    assert settlement["basis_variant"] == "AS_REPORTED"
    assert settlement["gross_fee_cents"] == 25000000
    assert settlement["reverse_comp_split_bp"] == 5500
    assert settlement["reverse_comp_cents"] == 13750000
    assert settlement["actual_penetration_bp"] == 4166
    assert settlement["penetration_shortfall_bp"] == 34
    assert settlement["penetration_penalty_cents"] == 0
    assert settlement["net_retained_cents"] == 11250000
    assert settlement["true_up_required"] is False

    validate_error(
        api.true_up_fee_settlement(settlement["id"], true_up_payload(), COUNSEL),
        ApiErrorId.ERR_TRUE_UP_NOT_REQUIRED.value,
        422,
    )

    after = read_settlements(ctx["agreement"]["id"])[0]
    assert after["status"] == "ISSUED"
    assert after["basis_variant"] == "AS_REPORTED"
    assert after["net_retained_cents"] == 11250000


# ------------------- corner_dispute_on_term_outside_granted_scope_rejected
def test_a_dispute_over_a_right_the_grant_never_carried_is_refused(api):
    """Out-of-home was withheld upstream, so there is nothing to contest downstream.

    PRD §3.8: "A dispute may only contest a right that was actually granted: the
    `disputed_term` must be a member of the agreement's `granted_rights_scope` at
    creation, and a term that was never granted is refused with `ERR_TERM_NOT_IN_GRANT`."

    Design: Corner/validations/corner_dispute_on_term_outside_granted_scope_rejected
    """
    ctx = setup_executed_agreement()
    assert ctx["agreement"]["granted_rights_scope"] == ["DIGITAL", "STREAMING"]

    validate_error(
        api.create_rights_dispute(
            ctx["agreement"]["id"],
            create_rights_dispute_payload(
                "OUT_OF_HOME", claimed_definition="Bar and restaurant viewing"
            ),
            ctx["rep_headers"],
        ),
        ApiErrorId.ERR_TERM_NOT_IN_GRANT.value,
        422,
    )

    granted = validate_success(
        api.create_rights_dispute(
            ctx["agreement"]["id"],
            create_rights_dispute_payload(
                "DIGITAL",
                claimed_definition="Simulcast on owned-and-operated apps only",
            ),
            ctx["rep_headers"],
        ),
        201,
    )
    assert granted["disputed_term"] == "DIGITAL"
    assert granted["status"] == "RAISED"
    assert granted["credit_bp_applied"] == 0
    assert read_agreement(ctx["agreement"]["id"])["rights_credit_bp_total"] == 0


# ------------ corner_state_check_outranks_window_check_on_accepted_report
def test_an_audit_finding_on_a_swept_report_reports_the_state_not_the_window(api):
    """The report is both ACCEPTED and past its window; the state rule is numbered lower.

    PRD §2.8: "Subscriber report is auditable, meaning its status is `REPORTED`,
    `UNDER_AUDIT` or `ADJUSTED` - `ERR_REPORT_NOT_AUDITABLE`. Applies to opening an audit
    finding; an `ACCEPTED` report is closed to audit."

    Design: Corner/validations/corner_state_check_outranks_window_check_on_accepted_report
    """
    station, _, report = _reported_january_report()
    set_clock("2027-08-01T00:00:00Z")
    counts = run_expiration_sweep()
    assert counts["accepted_report_count"] == 1
    assert read_subscriber_report(report["id"])["status"] == "ACCEPTED"

    error = validate_error(
        api.create_audit_finding(
            report["id"],
            create_audit_finding_payload(
                adjustment_subscribers=6000,
                basis_note="Late look at bulk-billed accounts",
            ),
            make_station_negotiator_headers(station["id"]),
        ),
        ApiErrorId.ERR_REPORT_NOT_AUDITABLE.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_AUDIT_WINDOW_EXPIRED.value

    _, meta = validate_paginated(api.list_audit_findings(report["id"], ADMIN))
    assert meta["total_count"] == 0
    assert read_subscriber_report(report["id"])["audit_adjustment_subscribers"] == 0
