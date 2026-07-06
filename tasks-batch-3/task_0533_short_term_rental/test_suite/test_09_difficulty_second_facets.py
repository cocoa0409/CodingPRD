"""Second-facet coverage for difficulty queue A instances.

Each difficulty-design instance requires at least two tests. The primary facet
lives in test_01..test_05; this file asserts a distinct, independently
PRD-grounded facet of the same instance (a complementary field, side effect, or
status outcome) so every instance carries >= 2 tests.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    PermitStatus, HostStanding, TaxFilingStatus,
    make_host_headers, TEST_USERS,
    setup_issued_permit, setup_active_permit, setup_draft_permit,
    setup_filed_filing, setup_delinquent_filing, setup_active_permit_in_renewal_window,
    setup_lottery_pending_permit, create_draft_filing, create_draft_permit,
    create_zone, create_host, create_property, attest_primary, file_open_complaint,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TAX_OFFICER = TEST_USERS["tax_officer_headers"]


def test_tot_due_file_sets_filed_status(api):
    """PRD §3.8: "On a successful file, the system computes tot_due_cents (below),
    sets due_at to the last day of the reported period plus 30 days, moves the
    filing from DRAFT to FILED, and increments its version."

    The file transition both computes tot_due_cents and lands the filing FILED.

    Design: Difficulty/dual_variant_calc/tot_due_cost_accounting_on_tax_filing
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], nights_booked=10, gross_revenue_cents=500000)
    data = validate_success(api.file_tax_filing(draft["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.FILED.value
    assert data["tot_due_cents"] == 43000


def test_penalty_delinquent_transition_sets_status(api):
    """PRD §2.5: "A tax filing in FILED status whose due_at is at or before the
    current clock time and which remains underpaid auto-transitions to DELINQUENT
    on the next touch, at which point its late penalty is computed and frozen."

    The 60-days-late cap-branch filing lands DELINQUENT with the frozen penalty.

    Design: Difficulty/combinatorial_formula/tax_penalty_min_of_interest_and_cap_branch
    """
    _, host, _, permit, filing = setup_delinquent_filing(
        "2026-06-29T00:00:00Z",
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000},
    )
    assert filing["status"] == TaxFilingStatus.DELINQUENT.value
    assert filing["penalty_cents"] == 10750


def test_tot_due_straddle_status_filed(api):
    """PRD §3.8: "moves the filing from DRAFT to FILED, and increments its
    version."

    The straddle-tier file both lands FILED and yields the per-share-rounded
    tot_due of 61200.

    Design: Difficulty/combinatorial_formula/tot_due_straddle_round_per_share_then_sum
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], nights_booked=20, gross_revenue_cents=600000)
    data = validate_success(api.file_tax_filing(draft["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.FILED.value
    assert data["tot_due_cents"] == 61200


def test_amend_then_refile_recomputes_tot_due(api):
    """PRD §3.8: "A successful amendment moves the filing from FILED back to DRAFT,
    resets both tot_due_cents and due_at to null."
    PRD §3.8: "the officer can then correct and re-file."

    After the amend loop resets tot_due to null, re-filing recomputes it.

    Design: Difficulty/non_linear_state_machine/tax_filing_cyclic_amend_loop
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    amended = validate_success(api.amend_tax_filing(filed["id"], TAX_OFFICER))
    assert amended["due_at"] is None
    refiled = validate_success(api.file_tax_filing(filed["id"], TAX_OFFICER))
    assert refiled["status"] == TaxFilingStatus.FILED.value
    assert refiled["tot_due_cents"] == 43000


def test_uphold_revoke_permit_reaches_revoked(api):
    """PRD §3.6: "When the cumulative upheld strike total reaches four, the permit
    is revoked: from ACTIVE (or from SUSPENDED) it moves to REVOKED."

    The permit endpoint of the depth-3 cascade: two upheld OVER_OCCUPANCY (2+2)
    drives cumulative to 4 => REVOKED.

    Design: Difficulty/transitive_cascade/uphold_revoke_frees_seat_and_bars_host_depth3
    """
    zone, host, _, permit = setup_active_permit()
    c1 = file_open_complaint(permit["id"], "OVER_OCCUPANCY")
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = file_open_complaint(permit["id"], "OVER_OCCUPANCY")
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))
    permit_after = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert permit_after["status"] == PermitStatus.REVOKED.value


def test_lottery_draw_awarded_permit_ids_recorded(api):
    """PRD §3.5: "The round records the ordered list of awarded permit ids in
    awarded_permit_ids, sets its status to DRAWN, and increments its own version."

    The awarded pending permit id appears in the round's awarded_permit_ids and
    the round becomes DRAWN.

    Design: Difficulty/transitive_cascade/lottery_draw_award_issues_and_counts_seat_depth2
    """
    zone, host_a, permit_a, host_b, permit_b, rnd, rv = setup_lottery_pending_permit()
    data = validate_success(
        api.draw_lottery_round(rnd["id"], {"expected_lottery_round_version": rv}, REGISTRAR)
    )
    assert data["status"] == "DRAWN"
    assert permit_b["id"] in data["awarded_permit_ids"]


def test_reissue_issued_permit_does_not_change_status(api):
    """PRD §2.9: "if the requested transition is not defined from the resource's
    current state, the request is rejected with ERR_INVALID_STATE (HTTP 409)."

    The rejected re-issue leaves the permit ISSUED (the state check pre-empts any
    write).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_issue
    """
    _, host, _, permit = setup_issued_permit()
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert after["status"] == PermitStatus.ISSUED.value


def test_safety_gate_precedes_cap_second_zone(api):
    """PRD §3.4: "Next the safety gate: safety_attested must be true, otherwise
    ERR_SAFETY_NOT_ATTESTED (HTTP 422)."
    PRD §3.4: "The final gate is the density cap."

    Even in a full zone, an unsafe DRAFT permit fails at the safety gate, which
    is evaluated before the cap gate.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_issue
    """
    zone = create_zone(permit_cap=1, lottery_enabled=False)
    host_a = create_host()
    host_b = create_host()
    prop_a = create_property(host_a["id"], zone["id"], street_address="SafeB-A St")
    prop_b = create_property(host_b["id"], zone["id"], street_address="SafeB-B St")
    attest_primary(host_a["id"], prop_a["id"])
    attest_primary(host_b["id"], prop_b["id"])
    permit_a = create_draft_permit(prop_a["id"], permit_type="PRIMARY_RESIDENCE")
    validate_success(api.issue_permit(permit_a["id"], REGISTRAR))
    permit_b = create_draft_permit(prop_b["id"], permit_type="PRIMARY_RESIDENCE", safety_attested=False)
    validate_error(api.issue_permit(permit_b["id"], REGISTRAR), ApiErrorId.ERR_SAFETY_NOT_ATTESTED)


def test_occupancy_below_max_boundary_issues(api):
    """PRD §3.4: "the occupancy gate: attested_occupancy must be at least one and
    at most the property's max_occupancy, otherwise ERR_OCCUPANCY_EXCEEDS_MAX."

    On a 3-bedroom property (max 7), attested_occupancy 6 (X-1) issues.

    Design: Difficulty/boundary_precision_check/occupancy_at_max_boundary_issue_succeeds
    """
    _, host, _, permit = setup_draft_permit(
        prop_overrides={"bedroom_count": 3},
        permit_overrides={"attested_occupancy": 6},
    )
    data = validate_success(api.issue_permit(permit["id"], REGISTRAR))
    assert data["status"] == PermitStatus.ISSUED.value


def test_file_one_night_boundary_succeeds(api):
    """PRD §3.8: "It further requires nights_booked to be at least one, since a
    zero-night period has nothing to file."

    nights_booked 1 (the inclusive minimum) files successfully, confirming the
    zero-night rejection is a strict boundary.

    Design: Difficulty/boundary_precision_check/no_nights_zero_count_file_rejected
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], nights_booked=1, gross_revenue_cents=50000)
    data = validate_success(api.file_tax_filing(draft["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.FILED.value


def test_issue_into_ineligible_zone_leaves_permit_draft(api):
    """PRD §3.4: "The zoning gate comes first: the referenced property's zone must
    be short-term-rental eligible, and if its str_eligible is false the issue is
    rejected with ERR_ZONE_INELIGIBLE (HTTP 422)."

    The rejected issue leaves the permit in DRAFT (no transition on gate failure).

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_zone_str_eligible
    """
    _, host, _, permit = setup_draft_permit(
        zone_overrides={"str_eligible": False, "whole_home_allowed": False},
    )
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_ZONE_INELIGIBLE)
    after = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert after["status"] == PermitStatus.DRAFT.value


def test_uphold_on_expired_permit_not_enforceable(api):
    """PRD §3.7: "Upholding ... is available only when the target permit is
    currently enforceable - that is, in ISSUED, ACTIVE, or SUSPENDED status;
    upholding against a permit outside that set is rejected with
    ERR_PERMIT_NOT_ENFORCEABLE (HTTP 422)."

    A permit expired via clock advance is outside the enforceable set.

    Design: Difficulty/cross_entity_state_dependency/complaint_uphold_requires_permit_enforceable
    """
    _, host, _, permit = setup_issued_permit()
    complaint = file_open_complaint(permit["id"], "NOISE")
    validate_success(api.set_clock("2027-05-01T00:00:00Z", REGISTRAR))
    validate_success(api.get_permit(permit["id"], REGISTRAR))  # trigger expiry
    validate_error(
        api.uphold_complaint(complaint["id"], REGISTRAR),
        ApiErrorId.ERR_PERMIT_NOT_ENFORCEABLE,
    )


def test_cap_reached_lottery_disabled_leaves_permit_draft(api):
    """PRD §3.4: "when lottery is disabled, the issue is rejected with
    ERR_PERMIT_CAP_REACHED (HTTP 422)."

    The blocked issue leaves the second permit in DRAFT.

    Design: Difficulty/resource_temporal_overlap/permit_cap_density_overlap_within_zone
    """
    zone = create_zone(permit_cap=1, lottery_enabled=False)
    host_a = create_host()
    host_b = create_host()
    prop_a = create_property(host_a["id"], zone["id"], street_address="Cap2-A St")
    prop_b = create_property(host_b["id"], zone["id"], street_address="Cap2-B St")
    attest_primary(host_a["id"], prop_a["id"])
    attest_primary(host_b["id"], prop_b["id"])
    permit_a = create_draft_permit(prop_a["id"], permit_type="PRIMARY_RESIDENCE")
    validate_success(api.issue_permit(permit_a["id"], REGISTRAR))
    permit_b = create_draft_permit(prop_b["id"], permit_type="PRIMARY_RESIDENCE")
    validate_error(api.issue_permit(permit_b["id"], REGISTRAR), ApiErrorId.ERR_PERMIT_CAP_REACHED)
    after = validate_success(api.get_permit(permit_b["id"], REGISTRAR))
    assert after["status"] == PermitStatus.DRAFT.value


def test_duplicate_filing_period_first_filing_persists(api):
    """PRD §3.8: "The triple of permit, year, and month must be unique; a second
    filing for an already-filed period is rejected with ERR_DUPLICATE_FILING_PERIOD
    (HTTP 409)."

    The first (permit, 2026, 3) filing is accepted; only the colliding second is
    rejected.

    Design: Difficulty/resource_temporal_overlap/tax_filing_period_uniqueness_overlap
    """
    _, host, _, permit = setup_issued_permit()
    first = create_draft_filing(permit["id"], period_year=2026, period_month=3,
                                nights_booked=10, gross_revenue_cents=500000)
    assert first["status"] == TaxFilingStatus.DRAFT.value
    validate_error(
        api.create_tax_filing(
            {"permit_id": permit["id"], "period_year": 2026, "period_month": 3,
             "nights_booked": 5, "gross_revenue_cents": 250000},
            TAX_OFFICER,
        ),
        ApiErrorId.ERR_DUPLICATE_FILING_PERIOD,
    )


def test_seat_conservation_count_one_while_active(api):
    """PRD §2.6: "issuing a permit into ISSUED (or awarding it through a lottery)
    increments the zone's active permit count by one."
    PRD §3.6: "its zone's active permit count is decremented by one to free the
    density seat."

    The active permit holds exactly one seat before revocation frees it; the two
    upheld UNPERMITTED complaints (2+2) then revoke and release the seat.

    Design: Difficulty/compensating_invariant/zone_seat_conservation_issue_then_revoke
    """
    zone, host, _, permit = setup_active_permit()
    zone_before = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_before["active_permit_count"] == 1
    c1 = file_open_complaint(permit["id"], "UNPERMITTED")
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = file_open_complaint(permit["id"], "UNPERMITTED")
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 0


def test_delinquent_partial_payment_stays_delinquent(api):
    """PRD §3.8: "From DELINQUENT, a remittance transitions the filing to REMITTED
    only once the cumulative amount_remitted_cents reaches or exceeds
    tot_due_cents plus penalty_cents; a partial payment is recorded and the
    filing stays DELINQUENT."

    Paying 46574 (one cent short of 43000+3575) stays DELINQUENT; the money
    conservation boundary is strict.

    Design: Difficulty/compensating_invariant/filing_money_conservation_remit_covers_due_plus_penalty
    """
    _, host, _, permit, filing = setup_delinquent_filing(
        "2026-05-05T00:00:00Z",
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000},
    )
    assert filing["penalty_cents"] == 3575
    data = validate_success(
        api.remit_tax_filing(filing["id"], {"payment_cents": 46574}, make_host_headers(host["id"]))
    )
    assert data["status"] == TaxFilingStatus.DELINQUENT.value
    assert data["amount_remitted_cents"] == 46574


def test_renew_does_not_change_zone_count(api):
    """PRD §3.6: "it is a self-loop on the ACTIVE state and does not touch the
    zone's active permit count."

    A successful renewal leaves the zone's active permit count unchanged at 1.

    Design: Difficulty/non_linear_state_machine/permit_cyclic_active_renew_self_loop
    """
    zone, host, _, permit, ver = setup_active_permit_in_renewal_window("2027-04-15T00:00:00Z")
    validate_success(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, make_host_headers(host["id"]))
    )
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 1


def test_amend_resets_due_at_to_null(api):
    """PRD §3.8: "A successful amendment moves the filing from FILED back to DRAFT,
    resets both tot_due_cents and due_at to null, and increments the filing's
    version."

    Design: Difficulty/non_linear_state_machine/tax_filing_cyclic_amend_loop
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    data = validate_success(api.amend_tax_filing(filed["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.DRAFT.value
    assert data["due_at"] is None


def test_host_standing_stays_good_below_threshold(api):
    """PRD §3.7: "The host's standing is GOOD while that aggregate is strictly
    below three and becomes BARRED once it reaches three."

    Two upheld NOISE complaints (1+1 = 2, below 3) keep standing GOOD.

    Design: Difficulty/dual_variant_calc/host_strike_standing_risk_scoring_on_host
    """
    zone, host, _, permit = setup_active_permit()
    c1 = file_open_complaint(permit["id"], "NOISE")
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = file_open_complaint(permit["id"], "NOISE")
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))
    host_data = validate_success(api.get_host(host["id"], REGISTRAR))
    assert host_data["strike_total"] == 2
    assert host_data["standing"] == HostStanding.GOOD.value
