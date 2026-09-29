"""Two conventions computed from the same inputs, kept apart on purpose.

The negotiation quote and the executed billing ladder use different escalation
conventions, and the subscriber basis is stored in an as-reported and an audited
variant. Each test below pins one variant against the other.
"""

from test_helpers import (
    TEST_USERS,
    accept_offer_payload,
    assert_fee_settlement,
    assert_offer,
    assert_settlement_conservation,
    assert_subscriber_report,
    create_offer_payload,
    negotiation_version,
    open_audit_finding,
    read_agreement,
    resolve_audit_finding_payload,
    setup_accepted_agreement,
    setup_issued_settlement,
    setup_negotiation_with_report,
    setup_submitted_station_offer,
    true_up_payload,
    validate_success,
)


def test_offer_quotes_the_compound_annual_ladder(api):
    """A submitted offer's projected ladder escalates off each already-rounded year.

    PRD §3.5: "Under the **compound-annual** convention - the one quoted during
    negotiation, stored as `year_rate_schedule_compound_cents` - year one's rate is
    `base_rate_per_sub_cents` exactly, and each later year's rate is the previous
    year's *already-rounded* rate multiplied by ten thousand plus
    `escalator_bp_per_year`, divided by ten thousand, and rounded half up to whole
    cents."

    Design: Difficulty/dual_variant_calc/offer_fee_ladder_compound_versus_simple_variant_divergence
    """
    ctx = setup_negotiation_with_report()

    response = api.create_offer(
        ctx["negotiation"]["id"],
        create_offer_payload(
            ctx["report"]["id"],
            base_rate_per_sub_cents=250,
            escalator_bp_per_year=700,
            term_months=36,
        ),
        ctx["negotiator_headers"],
    )
    offer = validate_success(response, 201)

    assert_offer(offer)
    assert offer["projection_basis_subscribers"] == 100000
    assert offer["year_rate_schedule_compound_cents"] == [250, 268, 287]
    assert offer["projected_total_fee_cents"] == 966000000
    assert offer["projected_total_fee_cents"] != 963600000


def test_accepted_agreement_bills_on_the_simple_annual_ladder(api):
    """Acceptance replaces the quoted ladder with the linear billing ladder.

    PRD §3.7: "The contrast with the negotiation ladder is concrete: for a base rate
    of 250 cents and an escalator of 700 basis points over a three-year term, the
    compound-annual ladder quoted during negotiation runs 250, 268, 287, while the
    simple-annual ladder the executed contract bills on runs 250, 268, 285."

    Design: Difficulty/dual_variant_calc/offer_fee_ladder_compound_versus_simple_variant_divergence
    """
    ctx = setup_submitted_station_offer(
        offer={
            "base_rate_per_sub_cents": 250,
            "escalator_bp_per_year": 700,
            "term_months": 36,
        }
    )

    response = api.accept_offer(
        ctx["offer"]["id"],
        accept_offer_payload(negotiation_version(ctx["negotiation"]["id"])),
        TEST_USERS["group_counsel_headers"],
    )
    agreement = validate_success(response, 201)

    assert agreement["contract_year_rate_schedule_cents"] == [250, 268, 285]
    assert agreement["contract_year_rate_schedule_cents"] != [250, 268, 287]
    assert agreement["current_year_rate_per_sub_cents"] == 250


def test_fee_projection_reports_both_ladders_and_their_divergence(api):
    """The computed projection exposes the two whole-term totals and the gap.

    PRD §3.7: "Both ladders can also be read side by side from the agreement as a
    computed projection, which reports `compound_total_fee_cents` and
    `simple_total_fee_cents` as the whole-term gross under each convention,
    `divergence_cents` as the gap between them, and the two ladders themselves as
    `year_rate_schedule_compound_cents` and `year_rate_schedule_simple_cents`."

    Design: Difficulty/dual_variant_calc/offer_fee_ladder_compound_versus_simple_variant_divergence
    """
    ctx = setup_accepted_agreement(
        offer={
            "base_rate_per_sub_cents": 250,
            "escalator_bp_per_year": 700,
            "term_months": 36,
        }
    )

    response = api.get_fee_projection(
        ctx["agreement"]["id"], TEST_USERS["group_counsel_headers"]
    )
    projection = validate_success(response, 200)

    assert projection["year_rate_schedule_compound_cents"] == [250, 268, 287]
    assert projection["year_rate_schedule_simple_cents"] == [250, 268, 285]
    assert projection["compound_total_fee_cents"] == 966000000
    assert projection["simple_total_fee_cents"] == 963600000
    assert projection["divergence_cents"] == 2400000


def test_report_stores_the_as_reported_and_audited_bases_side_by_side(api):
    """A substantiated undercount moves the audited basis and leaves as-reported alone.

    PRD §3.4: "The `as_reported_basis` is the variant that forces
    `audit_adjustment_subscribers` to 0, so substantiated audit findings do not move
    it; it is the number a fee settlement snapshots at issuance."

    Design: Difficulty/dual_variant_calc/subscriber_basis_as_reported_versus_audited_variant_divergence
    """
    ctx = setup_negotiation_with_report(report={"reported_subscriber_count": 100000})
    finding = open_audit_finding(
        ctx["report"]["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )

    response = api.resolve_audit_finding(
        finding["id"],
        resolve_audit_finding_payload("SUBSTANTIATED"),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_success(response, 200)

    report = validate_success(
        api.get_subscriber_report(
            ctx["report"]["id"], TEST_USERS["group_counsel_headers"]
        ),
        200,
    )
    assert_subscriber_report(report)
    assert report["status"] == "ADJUSTED"
    assert report["audit_adjustment_subscribers"] == 6000
    assert report["adjusted_subscriber_count"] == 106000
    assert report["billable_subscriber_basis"] == 106000
    assert report["as_reported_basis"] == 100000


def test_true_up_moves_the_settlement_onto_the_audited_variant(api):
    """True-up re-prices the whole waterfall from the audited basis.

    PRD §3.9: "True-up advances the settlement `ISSUED -> TRUED_UP`, flips
    `basis_variant` to `AUDITED`, and replaces `billable_subscriber_basis_snapshot`
    with the report's `billable_subscriber_basis` - the audited variant, which
    includes the substantiated adjustment."

    Design: Difficulty/dual_variant_calc/subscriber_basis_as_reported_versus_audited_variant_divergence
    """
    ctx = setup_issued_settlement(report={"reported_subscriber_count": 100000})
    assert ctx["settlement"]["basis_variant"] == "AS_REPORTED"
    assert ctx["settlement"]["billable_subscriber_basis_snapshot"] == 100000
    assert ctx["settlement"]["net_retained_cents"] == 11250000

    finding = open_audit_finding(
        ctx["report"]["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )
    validate_success(
        api.resolve_audit_finding(
            finding["id"],
            resolve_audit_finding_payload("SUBSTANTIATED"),
            TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )

    response = api.true_up_fee_settlement(
        ctx["settlement"]["id"],
        true_up_payload(),
        TEST_USERS["group_counsel_headers"],
    )
    settlement = validate_success(response, 200)

    assert_fee_settlement(settlement)
    assert settlement["status"] == "TRUED_UP"
    assert settlement["basis_variant"] == "AUDITED"
    assert settlement["billable_subscriber_basis_snapshot"] == 106000
    assert settlement["gross_fee_cents"] == 26500000
    assert settlement["reverse_comp_cents"] == 14575000
    assert settlement["penetration_penalty_cents"] == 0
    assert settlement["net_retained_cents"] == 11925000
    assert settlement["true_up_required"] is False
    assert_settlement_conservation(settlement)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 26500000
    assert agreement["lifetime_net_retained_cents"] == 11925000
