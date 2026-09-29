"""Endpoint-surface corners: partial amendment, computed reads, list filters and sweeps.

Each test below drives one endpoint of the retransmission API to the corner where
its own contract is decided: a PATCH that must touch only the fields it was
given, a computed projection read that must recompute both fee ladders, a
rejection that must leave the negotiation's counters alone, a maintenance sweep
that must report five zeroes when nothing is due, the flat offer index and its
two foreign-key filters, a dismissal that rewinds a report only when no
substantiated sibling exists, and an execution whose cascade reaches an
extension sitting on a different agreement.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_offer,
    approve_network,
    assert_carriage_agreement,
    assert_interim_extension,
    assert_offer,
    assert_subscriber_report,
    create_election,
    create_interim_extension,
    create_subscriber_report,
    execute_agreement_payload,
    file_election,
    negotiation_of_election,
    open_audit_finding,
    read_agreement,
    read_election,
    read_negotiation,
    read_subscriber_report,
    reject_offer_payload,
    resolve_audit_finding_payload,
    setup_draft_election,
    setup_executed_agreement,
    setup_negotiation_with_report,
    setup_open_negotiation,
    setup_station_and_distributor,
    setup_submitted_station_offer,
    submit_distributor_offer,
    submit_station_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_PERIOD = {
    "period_label": "2027-02",
    "period_start_utc": "2027-02-01T00:00:00Z",
    "period_end_utc": "2027-03-01T00:00:00Z",
    "reported_subscriber_count": 104000,
}
DISTRIBUTOR_COUNTER = {
    "base_rate_per_sub_cents": 205,
    "escalator_bp_per_year": 400,
    "term_months": 36,
    "penetration_commitment_bp": 3900,
}
FORTY_EIGHT_MONTH_OFFER = {
    "base_rate_per_sub_cents": 310,
    "escalator_bp_per_year": 900,
    "term_months": 48,
    "penetration_commitment_bp": 4100,
}


def test_patch_election_revises_only_the_supplied_field(api):
    """Amending the incumbent rate alone leaves election type and tier where they were.

    PRD §3.3: "While the election is still `DRAFT`, the negotiator may amend it,
    revising any of `election_type`, `requested_tier` or
    `incumbent_rate_per_sub_cents`."
    PRD §2.4: "`version` is an integer that increments by one on every mutation of the
    resource, and it is the value the optimistic-concurrency mechanism in §2.7 compares
    against."

    Design: Corner/endpoints/corner_patch_election_amends_only_the_supplied_draft_fields
    """
    ctx = setup_draft_election()
    version_before = ctx["election"]["version"]

    response = api.amend_election(
        ctx["election"]["id"],
        {"incumbent_rate_per_sub_cents": 245},
        ctx["negotiator_headers"],
    )
    election = validate_success(response, 200)

    assert election["incumbent_rate_per_sub_cents"] == 245
    assert election["election_type"] == "RETRANS_CONSENT"
    assert election["requested_tier"] == "EXPANDED_BASIC"
    assert election["status"] == "DRAFT"
    assert election["version"] == version_before + 1


def test_patch_election_after_filing_is_refused_and_changes_nothing(api):
    """Once the election has left DRAFT the same PATCH is a 409 and no field moves.

    PRD §3.3: "Amendment is refused with `ERR_ELECTION_NOT_DRAFT` once the election has
    left `DRAFT`, and refused with `ERR_ELECTION_WINDOW_CLOSED` once the logical clock
    has passed the election deadline."

    Design: Corner/endpoints/corner_patch_election_amends_only_the_supplied_draft_fields
    """
    ctx = setup_open_negotiation()
    assert ctx["election"]["status"] == "NEGOTIATING"

    response = api.amend_election(
        ctx["election"]["id"],
        {"requested_tier": "BROADCAST_BASIC"},
        ctx["negotiator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ELECTION_NOT_DRAFT.value, 409)

    election = read_election(ctx["election"]["id"])
    assert election["requested_tier"] == "EXPANDED_BASIC"
    assert election["status"] == "NEGOTIATING"


def test_fee_projection_read_recomputes_both_ladders_and_the_divergence(api):
    """A 48-month 310-cent offer at 900 bp diverges from contract year three onward.

    PRD §3.7: "Both ladders can also be read side by side from the agreement as a
    computed projection, which reports `compound_total_fee_cents` and
    `simple_total_fee_cents` as the whole-term gross under each convention,
    `divergence_cents` as the gap between them, and the two ladders themselves as
    `year_rate_schedule_compound_cents` and `year_rate_schedule_simple_cents`."

    Design: Corner/endpoints/corner_fee_projection_computed_read_returns_both_ladders
    """
    ctx = setup_executed_agreement(
        offer=dict(FORTY_EIGHT_MONTH_OFFER),
        accept={"effective_end_utc": "2031-01-01T00:00:00Z"},
    )
    assert_offer(ctx["offer"])
    assert ctx["offer"]["year_rate_schedule_compound_cents"] == [310, 338, 368, 401]
    assert ctx["offer"]["projected_total_fee_cents"] == 1700400000
    assert_carriage_agreement(ctx["agreement"])
    assert ctx["agreement"]["contract_year_rate_schedule_cents"] == [310, 338, 366, 394]

    response = api.get_fee_projection(
        ctx["agreement"]["id"], TEST_USERS["network_representative_headers"]
    )
    projection = validate_success(response, 200)

    assert projection["year_rate_schedule_compound_cents"] == [310, 338, 368, 401]
    assert projection["year_rate_schedule_simple_cents"] == [310, 338, 366, 394]
    assert projection["compound_total_fee_cents"] == 1700400000
    assert projection["simple_total_fee_cents"] == 1689600000
    assert projection["divergence_cents"] == 10800000


def test_rejecting_an_offer_leaves_the_negotiation_counters_untouched(api):
    """Rejection stores the reason on the offer and is not a turn on the negotiation.

    PRD §3.5: "An offer may instead be **rejected** by the counterparty, who supplies a
    `rejection_reason` that is recorded on the offer as it moves `SUBMITTED ->
    REJECTED`."
    PRD §3.5: "Notably, rejection ends nothing: the negotiation's `status`, its
    `round_number` and its `version` are all left exactly as they were, so a rejection
    is a position statement rather than a turn."

    Design: Corner/endpoints/corner_reject_offer_leaves_negotiation_counters_untouched
    """
    ctx = setup_submitted_station_offer()
    before = read_negotiation(ctx["negotiation"]["id"])
    assert before["status"] == "AWAITING_DISTRIBUTOR_RESPONSE"
    assert before["round_number"] == 1
    assert before["station_offer_count"] == 1

    response = api.reject_offer(
        ctx["offer"]["id"],
        reject_offer_payload(
            rejection_reason="Rate exceeds our EXPANDED_BASIC budget"
        ),
        ctx["rep_headers"],
    )
    offer = validate_success(response, 200)

    assert offer["status"] == "REJECTED"
    assert offer["rejection_reason"] == "Rate exceeds our EXPANDED_BASIC budget"

    after = read_negotiation(ctx["negotiation"]["id"])
    assert after["status"] == before["status"]
    assert after["round_number"] == before["round_number"]
    assert after["version"] == before["version"]
    assert after["station_offer_count"] == before["station_offer_count"]


def test_sweep_reports_five_zero_counts_when_nothing_is_due(api):
    """At the default clock every time gate is still in the future, so nothing moves.

    PRD §3.9: "A `CarriageAdmin` triggers the expiration sweep, which advances every
    time-gated lifecycle in the system against the current logical clock and answers
    with five counts: `expired_agreement_count`, `lapsed_extension_count`,
    `lapsed_election_count`, `accepted_report_count` and `expired_affiliation_count`."

    Design: Corner/endpoints/corner_sweep_reports_zero_counts_when_nothing_is_due
    """
    ctx = setup_executed_agreement()
    version_after_execution = ctx["agreement"]["version"]

    response = api.run_expiration_sweep({}, TEST_USERS["carriage_admin_headers"])
    counts = validate_success(response, 200)

    assert counts["expired_agreement_count"] == 0
    assert counts["lapsed_extension_count"] == 0
    assert counts["lapsed_election_count"] == 0
    assert counts["accepted_report_count"] == 0
    assert counts["expired_affiliation_count"] == 0

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["execution_status"] == "EXECUTED"
    assert agreement["version"] == version_after_execution

    report = read_subscriber_report(ctx["report"]["id"])
    assert_subscriber_report(report)
    assert report["status"] == "REPORTED"

    affiliations, _ = validate_paginated(
        api.list_affiliation_agreements(
            ctx["station"]["id"], TEST_USERS["carriage_admin_headers"]
        )
    )
    assert [row["status"] for row in affiliations] == ["ACTIVE"]


def _two_offers_priced_off_two_reports():
    """One station offer off the 2027-01 report and one distributor counter off 2027-02."""
    ctx = setup_negotiation_with_report()
    ctx["second_report"] = create_subscriber_report(
        ctx["station"]["id"], ctx["distributor"]["id"], **SECOND_PERIOD
    )
    ctx["station_offer"] = submit_station_offer(
        ctx["negotiation"]["id"], ctx["station"]["id"], ctx["report"]["id"]
    )
    ctx["distributor_offer"] = submit_distributor_offer(
        ctx["negotiation"]["id"],
        ctx["distributor"]["id"],
        ctx["second_report"]["id"],
        **DISTRIBUTOR_COUNTER,
    )
    return ctx


def test_offer_index_filters_on_the_stored_negotiation_link(api):
    """Filtering the flat offer index by negotiation returns both offers of that round-trip.

    PRD §3.5: "Offers on one negotiation can be listed and narrowed by `offered_by` and
    `status`, and offers can also be listed across negotiations and narrowed by
    `negotiation_id`, `subscriber_report_id`, `offered_by` and `status` - the report
    filter being how a station group finds every offer that was priced against a count
    now known to have been wrong."

    Design: Corner/endpoints/corner_offer_list_filters_link_negotiation_and_report
    """
    ctx = _two_offers_priced_off_two_reports()

    data, meta = validate_paginated(
        api.list_offers(
            TEST_USERS["compliance_officer_headers"],
            {"negotiation_id": ctx["negotiation"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
    assert {row["id"] for row in data} == {
        ctx["station_offer"]["id"],
        ctx["distributor_offer"]["id"],
    }
    for row in data:
        assert row["negotiation_id"] == ctx["negotiation"]["id"]

    by_side, side_meta = validate_paginated(
        api.list_offers(
            TEST_USERS["compliance_officer_headers"],
            {
                "negotiation_id": ctx["negotiation"]["id"],
                "offered_by": "STATION_GROUP",
            },
        )
    )
    assert side_meta["total_count"] == 1
    assert by_side[0]["id"] == ctx["station_offer"]["id"]


def test_offer_index_filters_on_the_stored_subscriber_report_link(api):
    """The report filter returns only the offer that priced against that report.

    PRD §3.5: "Offers on one negotiation can be listed and narrowed by `offered_by` and
    `status`, and offers can also be listed across negotiations and narrowed by
    `negotiation_id`, `subscriber_report_id`, `offered_by` and `status` - the report
    filter being how a station group finds every offer that was priced against a count
    now known to have been wrong."
    PRD §3.5: "It also freezes `projection_basis_subscribers` as a snapshot of the
    referenced report's `billable_subscriber_basis` at submission time; that snapshot is
    never re-read afterwards, so a later audit adjustment on the report leaves the
    offer's economics exactly where they were."

    Design: Corner/endpoints/corner_offer_list_filters_link_negotiation_and_report
    """
    ctx = _two_offers_priced_off_two_reports()

    data, meta = validate_paginated(
        api.list_offers(
            TEST_USERS["compliance_officer_headers"],
            {"subscriber_report_id": ctx["second_report"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == ctx["distributor_offer"]["id"]
    assert data[0]["offered_by"] == "DISTRIBUTOR"
    assert data[0]["subscriber_report_id"] == ctx["second_report"]["id"]
    assert data[0]["projection_basis_subscribers"] == 104000


def _reported_period_under_audit(adjustment_subscribers: int, basis_note: str):
    """One station, one distributor, one 2027-01 report of 100000 and one OPEN finding."""
    ctx = setup_station_and_distributor()
    ctx["report"] = create_subscriber_report(
        ctx["station"]["id"], ctx["distributor"]["id"]
    )
    ctx["finding"] = open_audit_finding(
        ctx["report"]["id"],
        ctx["station"]["id"],
        adjustment_subscribers=adjustment_subscribers,
        basis_note=basis_note,
    )
    return ctx


def test_dismissing_the_only_finding_returns_the_report_to_reported(api):
    """With no open and no substantiated sibling left, the report rewinds to REPORTED.

    PRD §3.4: "If, after that dismissal, no finding on the report remains `OPEN` and no
    finding on it is `SUBSTANTIATED`, the report returns `UNDER_AUDIT -> REPORTED`
    with `audit_adjustment_subscribers` still at 0 and `billable_subscriber_basis` still
    equal to `as_reported_basis`."

    Design: Corner/endpoints/corner_dismissed_finding_returns_report_to_reported
    """
    ctx = _reported_period_under_audit(3000, "Disputed commercial accounts")
    assert read_subscriber_report(ctx["report"]["id"])["status"] == "UNDER_AUDIT"

    response = api.resolve_audit_finding(
        ctx["finding"]["id"],
        resolve_audit_finding_payload(
            "DISMISSED", resolution_note="Sampling does not support the claim"
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    finding = validate_success(response, 200)
    assert finding["status"] == "DISMISSED"

    report = read_subscriber_report(ctx["report"]["id"])
    assert_subscriber_report(report)
    assert report["status"] == "REPORTED"
    assert report["audit_adjustment_subscribers"] == 0
    assert report["billable_subscriber_basis"] == 100000
    assert report["billable_subscriber_basis"] == report["as_reported_basis"]


def test_dismissal_beside_a_substantiated_finding_does_not_rewind_the_report(api):
    """A dismissal cannot rewind a report that already carries a substantiated finding.

    PRD §3.4: "If a substantiated finding does exist on the report, or another finding is
    still open, the report stays where it is."
    PRD §3.4: "The `as_reported_basis` is the variant that forces
    `audit_adjustment_subscribers` to 0, so substantiated audit findings do not move it;
    it is the number a fee settlement snapshots at issuance."

    Design: Corner/endpoints/corner_dismissed_finding_returns_report_to_reported
    """
    ctx = _reported_period_under_audit(6000, "Bulk-billed MDU accounts omitted")
    validate_success(
        api.resolve_audit_finding(
            ctx["finding"]["id"],
            resolve_audit_finding_payload("SUBSTANTIATED"),
            TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )
    assert read_subscriber_report(ctx["report"]["id"])["status"] == "ADJUSTED"

    trailing = open_audit_finding(
        ctx["report"]["id"],
        ctx["station"]["id"],
        adjustment_subscribers=900,
        basis_note="Trailing hotel accounts",
    )
    assert read_subscriber_report(ctx["report"]["id"])["status"] == "UNDER_AUDIT"

    response = api.resolve_audit_finding(
        trailing["id"],
        resolve_audit_finding_payload(
            "DISMISSED", resolution_note="Withdrawn by the station group"
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    dismissed = validate_success(response, 200)
    assert dismissed["status"] == "DISMISSED"

    report = read_subscriber_report(ctx["report"]["id"])
    assert_subscriber_report(report)
    assert report["status"] != "REPORTED"
    assert report["status"] == "UNDER_AUDIT"
    assert report["audit_adjustment_subscribers"] == 6000
    assert report["billable_subscriber_basis"] == 106000
    assert report["as_reported_basis"] == 100000


def test_executing_the_successor_supersedes_the_prior_agreement_bridge_extension(api):
    """The successor's execution reaches across to the predecessor's bridge extension.

    PRD §3.7: "Because this agreement is now `EXECUTED`, every interim extension in
    status `ACTIVE` sitting on any *other* carriage agreement that shares this
    agreement's station-and-distributor slot, and whose own closed window intersects
    this agreement's half-open term from `effective_start_utc` to `effective_end_utc`,
    moves `ACTIVE -> SUPERSEDED` - the successor deal has taken over, so the stopgap
    is no longer operative."
    PRD §3.7: "And because those extensions left `ACTIVE`, each affected other agreement
    recomputes its `consumed_extension_days`, from which superseded days now drop out."

    Design: Corner/endpoints/corner_execute_supersedes_intersecting_extension_on_prior_agreement
    """
    ctx = setup_executed_agreement(
        affiliation={"term_end_utc": "2035-01-01T00:00:00Z"}
    )
    prior_agreement_id = ctx["agreement"]["id"]
    extension = create_interim_extension(
        prior_agreement_id,
        ctx["station"]["id"],
        extension_days=60,
        extension_start_utc="2030-01-01T00:00:00Z",
        extension_rate_basis="PRIOR_RATE",
    )
    assert_interim_extension(extension)
    assert extension["extension_end_utc"] == "2030-03-02T00:00:00Z"
    assert extension["effective_rate_per_sub_cents"] == 220
    assert extension["status"] == "ACTIVE"
    assert read_agreement(prior_agreement_id)["consumed_extension_days"] == 60

    successor_election = file_election(
        create_election(
            ctx["station"]["id"],
            ctx["distributor"]["id"],
            cycle_label="2030-2032",
            incumbent_expiry_utc="2030-01-01T00:00:00Z",
            incumbent_rate_per_sub_cents=250,
        )["id"],
        ctx["station"]["id"],
    )
    successor_negotiation = negotiation_of_election(successor_election["id"])
    successor_offer = submit_station_offer(
        successor_negotiation["id"],
        ctx["station"]["id"],
        ctx["report"]["id"],
        base_rate_per_sub_cents=260,
        escalator_bp_per_year=500,
        term_months=36,
    )
    successor_agreement = accept_offer(
        successor_offer["id"],
        successor_negotiation["id"],
        effective_start_utc="2030-03-02T00:00:00Z",
        effective_end_utc="2033-03-02T00:00:00Z",
    )
    approve_network(successor_agreement["id"])

    response = api.execute_agreement(
        successor_agreement["id"],
        execute_agreement_payload(
            execution_note="Successor countersigned by second counsel"
        ),
        TEST_USERS["second_group_counsel_headers"],
    )
    executed = validate_success(response, 200)

    assert_carriage_agreement(executed)
    assert executed["execution_status"] == "EXECUTED"
    assert executed["consumed_extension_days"] == 0

    superseded, meta = validate_paginated(
        api.list_interim_extensions(
            prior_agreement_id, ctx["negotiator_headers"], {"status": "SUPERSEDED"}
        )
    )
    assert meta["total_count"] == 1
    assert len(superseded) == 1
    assert superseded[0]["id"] == extension["id"]
    assert superseded[0]["status"] == "SUPERSEDED"

    prior_agreement = read_agreement(prior_agreement_id)
    assert prior_agreement["consumed_extension_days"] == 0
    assert prior_agreement["execution_status"] == "EXECUTED"
