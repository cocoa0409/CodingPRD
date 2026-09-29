"""Corner-case compliance tests for the API's derived figures.

Every derived figure in this API is computed by the server from stored inputs and
is never accepted from a client (PRD 1). These tests pin the formulas, the
rounding modes and the precisions the PRD declares: monetary amounts are integer
cents rounded half up, with the endowment spending-rate slice deliberately
truncated toward zero instead (PRD 2.6, PRD 3.6); `program_overlap_index`,
`approval_ratio` and `required_ratio` carry four decimal places, while
`reserve_months`, the three component point figures and `composite_score` carry
two, each rounded half up at the stated width (PRD 2.6).

The harness restarts the server and empties the registry before every test, so
each test builds all of its own preconditions through the API.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_QUORUM_NOT_MET
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_money_equals,
    assert_status,
)
from test_helpers.test_users import (
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    PLATFORM_ADMIN,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


# ----------------------------------------------------------------------
# Board vote outcome (PRD 3.5)
# ----------------------------------------------------------------------
def test_board_vote_below_the_merger_ratio_records_a_rejected_approval(api):
    """A 9-for/6-against merger tally yields approval_ratio 0.6000, short of the 0.6667 supermajority, so the resolution is created REJECTED and draws no seats.

    PRD 3.5 sets `required_ratio` at `0.6667` for a `MERGER`, computes
    `approval_ratio` as `votes_for` divided by `votes_cast` rounded half up to four
    decimal places, and makes `decision` `APPROVED` only "when `votes_cast` is
    greater than zero and `approval_ratio` is greater than or equal to
    `required_ratio`, and `REJECTED` otherwise". The resolution's initial status is
    "directly the terminal `REJECTED` when `decision` is `REJECTED`", while
    `eligible_seats` is `seats_total` less `recusals` and `quorum_required` is
    `eligible_seats` divided by two rounded up. Recording the deal's first
    resolution still advances it `STRUCTURE_SELECTED -> BOARD_APPROVAL`, and seats
    are drawn from the reserved pool only at certification, so `allocated_seats`
    stays 0, the pool keeps the 15 seats seeded when the letter was executed
    (PRD 3.3) and `governance_seats` on the party is untouched.

    Design: Corner/calculations/board_vote_below_the_merger_ratio_records_a_rejected_approval
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    payload = f.board_approval_payload(
        deal_id,
        fx.deal_version(api, deal_id),
        "INITIATOR",
        seats_total=15,
        recusals=0,
        votes_for=9,
        votes_against=6,
        abstentions=0,
        conflict_disclosures_count=0,
        recording_secretary_ref="SEC-A-1",
    )
    approval = validate_success(
        api.create_board_approval(payload, make_board_secretary_headers(org_a)), 201
    )

    # eligible_seats = 15 - 0 = 15; quorum_required = ceil(15 / 2) = 8;
    # votes_cast = 9 + 6 = 15; approval_ratio = 9 / 15 = 0.6000 < 0.6667.
    assert_field(approval, "eligible_seats", 15)
    assert_field(approval, "quorum_required", 8)
    assert_field(approval, "votes_cast", 15)
    assert_decimal_equals(approval["approval_ratio"], 0.6000, 4, "approval_ratio")
    assert_decimal_equals(approval["required_ratio"], 0.6667, 4, "required_ratio")
    assert_field(approval, "decision", "REJECTED")
    assert_status(approval, "REJECTED")
    assert_field(approval, "allocated_seats", 0)

    deal = fx.read_deal(api, deal_id)
    assert_status(deal, "BOARD_APPROVAL")
    assert_field(deal, "reserved_seat_pool", 15)

    org = validate_success(api.get_organization(org_a, PLATFORM_ADMIN))
    assert_field(org, "governance_seats", 0)


def test_quorum_required_is_the_ceiling_of_half_the_eligible_seats(api):
    """With 15 eligible seats quorum_required is ceil(15/2) = 8, so an attendance of 7 is refused and an attendance of exactly 8 is admitted.

    PRD 3.5: "`quorum_required` is `eligible_seats` divided by two and rounded **up**
    to the next whole seat. Attendance is `votes_for` plus `votes_against` plus
    `abstentions`", and "attendance must be at least `quorum_required`, else
    `ERR_QUORUM_NOT_MET`". Per PRD 2.7 a request refused by any validation
    "increments nothing and mutates nothing", so the deal keeps its status and its
    `version` and the same pin may be re-presented. On the admitted tally
    `votes_cast` excludes abstentions and `approval_ratio` is `votes_for` divided by
    `votes_cast` rounded half up to four places, which clears the `0.6667` merger
    threshold and records the resolution `RECORDED`.

    Design: Corner/calculations/quorum_required_is_the_ceiling_of_half_the_eligible_seats
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]
    pinned_version = fx.deal_version(api, deal_id)

    # Attendance 4 + 2 + 1 = 7, one seat short of the quorum of 8.
    short_of_quorum = f.board_approval_payload(
        deal_id,
        pinned_version,
        "INITIATOR",
        seats_total=15,
        recusals=0,
        votes_for=4,
        votes_against=2,
        abstentions=1,
        conflict_disclosures_count=0,
        recording_secretary_ref="SEC-A-1",
    )
    validate_error(
        api.create_board_approval(short_of_quorum, make_board_secretary_headers(org_a)),
        ERR_QUORUM_NOT_MET,
        422,
    )

    deal = fx.read_deal(api, deal_id)
    assert_status(deal, "STRUCTURE_SELECTED")
    assert_field(deal, "version", pinned_version)

    # Attendance 6 + 2 + 0 = 8, exactly the quorum.
    at_quorum = f.board_approval_payload(
        deal_id,
        pinned_version,
        "INITIATOR",
        seats_total=15,
        recusals=0,
        votes_for=6,
        votes_against=2,
        abstentions=0,
        conflict_disclosures_count=0,
        recording_secretary_ref="SEC-A-1",
    )
    approval = validate_success(
        api.create_board_approval(at_quorum, make_board_secretary_headers(org_a)), 201
    )
    assert_field(approval, "quorum_required", 8)
    assert_field(approval, "votes_cast", 8)
    assert_decimal_equals(approval["approval_ratio"], 0.7500, 4, "approval_ratio")
    assert_field(approval, "decision", "APPROVED")
    assert_status(approval, "RECORDED")


def test_approval_ratio_rounds_two_thirds_up_to_the_exact_required_ratio(api):
    """Two of three votes cast rounds half up to exactly 0.6667, and the inclusive comparison against the merger's 0.6667 carries the motion.

    PRD 3.5: "`approval_ratio` is `votes_for` divided by `votes_cast`, rounded half
    up to four decimal places", and "`decision` is `APPROVED` when `votes_cast` is
    greater than zero and `approval_ratio` is greater than or equal to
    `required_ratio` ... the comparison is inclusive". PRD 2.6 fixes the width of
    both vote ratios at four decimal places. The same paragraph derives
    `eligible_seats` as `seats_total` less `recusals` and `quorum_required` as that
    figure divided by two rounded up, so twelve recusals leave 3 eligible seats and
    a quorum of 2 rather than a quorum keyed on `seats_total`.

    Design: Corner/calculations/approval_ratio_rounds_two_thirds_up_to_the_exact_required_ratio
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    payload = f.board_approval_payload(
        deal_id,
        fx.deal_version(api, deal_id),
        "INITIATOR",
        seats_total=15,
        recusals=12,
        votes_for=2,
        votes_against=1,
        abstentions=0,
        conflict_disclosures_count=12,
        recording_secretary_ref="SEC-A-1",
    )
    approval = validate_success(
        api.create_board_approval(payload, make_board_secretary_headers(org_a)), 201
    )

    # eligible_seats = 15 - 12 = 3; quorum_required = ceil(3 / 2) = 2;
    # votes_cast = 2 + 1 = 3; approval_ratio = 2 / 3 = 0.66666... -> 0.6667.
    assert_field(approval, "eligible_seats", 3)
    assert_field(approval, "quorum_required", 2)
    assert_field(approval, "votes_cast", 3)
    assert_decimal_equals(approval["approval_ratio"], 0.6667, 4, "approval_ratio")
    assert_decimal_equals(approval["required_ratio"], 0.6667, 4, "required_ratio")
    assert_field(approval, "decision", "APPROVED")
    assert_status(approval, "RECORDED")


# ----------------------------------------------------------------------
# Mission / programme alignment scoring (PRD 3.2)
# ----------------------------------------------------------------------
def test_composite_score_sums_three_components_at_the_exact_overlap_peak(api):
    """Two initiator programmes against four target programmes with one matching category-and-county pair give an overlap index of exactly 0.5000, the only point that pays the full 30.00.

    PRD 3.2: `included_program_count` is "the total number of admitted programs
    across both parties", `overlap_pair_count` counts the ordered pairs sharing both
    `service_category` and `county_code`, and "the denominator [is] the smaller of
    the two parties' admitted program counts", so min(2, 4) = 2 and the index is
    1 / 2 = 0.5000 at four decimal places. `program_overlap_points` is "thirty points
    multiplied by the quantity one minus twice the absolute difference between
    `program_overlap_index` and `0.5`", so "an index of exactly `0.5` yields the full
    `30.00`". Identical mission codes earn `40.00`; each party's annual expense is
    divided by twelve and rounded half up **first** and only then summed, giving
    100000002 / 12 = 8333334 twice, i.e. 16666668; a `SCREENING` snapshot nets no
    exposure so `available_unrestricted_cents` is 59916670 + 40000000 = 99916670 and
    `reserve_months` is that over 16666668 rounded half up to two places, 5.99, which
    lands in the "at least three but under six" tier worth `20.00`.

    Design: Corner/calculations/composite_score_sums_three_components_at_the_exact_overlap_peak
    """
    ctx = fx.setup_two_orgs(api)
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    fx.create_program(
        api, org_a, name="Riverside Mentor Match",
        service_category="YOUTH_MENTORING", county_code="CA-ALAMEDA",
    )
    fx.create_program(
        api, org_a, name="Riverside Weekend Pantry",
        service_category="FOOD_SECURITY", county_code="CA-SONOMA",
    )
    # Exactly one target programme shares both category and county with an
    # initiator programme.
    fx.create_program(
        api, org_b, name="Harbor Mentor Match",
        service_category="YOUTH_MENTORING", county_code="CA-ALAMEDA",
    )
    fx.create_program(
        api, org_b, name="Harbor Transitional Housing",
        service_category="HOUSING", county_code="CA-MARIN",
    )
    fx.create_program(
        api, org_b, name="Harbor Youth Studio",
        service_category="ARTS_EDUCATION", county_code="CA-NAPA",
    )
    fx.create_program(
        api, org_b, name="Harbor Trade Pathways",
        service_category="WORKFORCE_TRAINING", county_code="CA-YOLO",
    )

    ctx = fx.setup_deal_exploratory(api, ctx)
    snapshot = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], "SCREENING"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )

    assert_field(snapshot, "sequence_no", 1)
    assert_field(snapshot, "included_program_count", 6)
    assert_field(snapshot, "overlap_pair_count", 1)
    assert_decimal_equals(
        snapshot["program_overlap_index"], 0.5000, 4, "program_overlap_index"
    )
    assert_decimal_equals(
        snapshot["program_overlap_points"], 30.00, 2, "program_overlap_points"
    )
    assert_decimal_equals(
        snapshot["mission_alignment_points"], 40.00, 2, "mission_alignment_points"
    )
    assert_money_equals(
        snapshot["combined_monthly_expense_cents"], 16666668,
        "combined_monthly_expense_cents",
    )
    assert_money_equals(
        snapshot["available_unrestricted_cents"], 99916670, "available_unrestricted_cents"
    )
    assert_decimal_equals(snapshot["reserve_months"], 5.99, 2, "reserve_months")
    assert_decimal_equals(
        snapshot["sustainability_points"], 20.00, 2, "sustainability_points"
    )
    assert_decimal_equals(snapshot["composite_score"], 90.00, 2, "composite_score")
    assert_field(snapshot, "composite_rating", "STRONG")


def test_mission_family_and_unrelated_branches_apply_the_declared_point_constants(api):
    """A shared mission family earns exactly 28.00 mission points while unrelated mission codes earn exactly 12.00, dropping the composite a full rating band.

    PRD 3.2: "identical codes earn `40.00` points, different codes that nevertheless
    share a mission family (the two characters preceding the hyphen) earn `28.00`,
    and unrelated codes earn `12.00`". PRD 3.1 defines the mission family as "the two
    characters *before* the hyphen" of the `mission_code`, so `YM-YOUTH_MENTORING`
    against `YM-PEER_SUPPORT` is a family match and against `FS-FOOD_BANK` is
    unrelated. With no programmes anywhere the admitted count is 0, and PRD 3.2 pins
    "when that denominator is 0, `program_overlap_index` is `0.0000`", which puts the
    overlap component at `30.00 * (1 - 2 * |0 - 0.5|)` = `0.00`. Both deals share the
    same initiator financials, so `reserve_months` is 99916670 / 16666668 = 5.99 and
    `sustainability_points` is `20.00` in each. The composites are therefore 48.00
    (`WEAK`, "at least `40.00` but under 60") and 32.00 (`NOT_VIABLE`, "anything
    below `40.00`"). `sequence_no` is counted per deal and per variant, so each first
    `SCREENING` snapshot is 1.

    Design: Corner/calculations/mission_family_and_unrelated_branches_apply_the_declared_point_constants
    """
    org_a = fx.create_organization(
        api,
        legal_name="Riverside Youth Alliance",
        mission_code="YM-YOUTH_MENTORING",
        annual_expense_cents=100000002,
        unrestricted_net_assets_cents=59916670,
    )
    org_family = fx.create_organization(
        api,
        legal_name="Harbor Peer Support Network",
        mission_code="YM-PEER_SUPPORT",
        annual_expense_cents=100000002,
        unrestricted_net_assets_cents=40000000,
    )
    org_unrelated = fx.create_organization(
        api,
        legal_name="Delta Regional Food Bank",
        mission_code="FS-FOOD_BANK",
        annual_expense_cents=100000002,
        unrestricted_net_assets_cents=40000000,
    )
    officer = make_strategy_officer_headers(org_a["id"])

    deal_family = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_a["id"], org_family["id"]), officer
        ),
        201,
    )
    deal_unrelated = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_a["id"], org_unrelated["id"]), officer
        ),
        201,
    )

    family_snapshot = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_family["id"], "SCREENING"), officer
        ),
        201,
    )
    unrelated_snapshot = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_unrelated["id"], "SCREENING"), officer
        ),
        201,
    )

    assert_decimal_equals(
        family_snapshot["mission_alignment_points"], 28.00, 2, "mission_alignment_points"
    )
    assert_field(family_snapshot, "included_program_count", 0)
    assert_decimal_equals(
        family_snapshot["program_overlap_index"], 0.0000, 4, "program_overlap_index"
    )
    assert_decimal_equals(
        family_snapshot["program_overlap_points"], 0.00, 2, "program_overlap_points"
    )
    assert_decimal_equals(family_snapshot["reserve_months"], 5.99, 2, "reserve_months")
    assert_decimal_equals(
        family_snapshot["sustainability_points"], 20.00, 2, "sustainability_points"
    )
    assert_decimal_equals(family_snapshot["composite_score"], 48.00, 2, "composite_score")
    assert_field(family_snapshot, "composite_rating", "WEAK")
    assert_field(family_snapshot, "sequence_no", 1)

    assert_decimal_equals(
        unrelated_snapshot["mission_alignment_points"], 12.00, 2, "mission_alignment_points"
    )
    assert_decimal_equals(
        unrelated_snapshot["composite_score"], 32.00, 2, "composite_score"
    )
    assert_field(unrelated_snapshot, "composite_rating", "NOT_VIABLE")
    assert_field(unrelated_snapshot, "sequence_no", 1)


def test_diligence_adjusted_exposure_ignores_a_cleared_finding(api):
    """A CLEARED finding leaves the open-exposure input set entirely, so only the still-open finding's 33250000 is netted off the parties' unrestricted assets.

    PRD 3.2: for a `DILIGENCE_ADJUSTED` snapshot `open_diligence_exposure_cents` "is
    the sum of `exposure_cents` over the deal's diligence findings whose `status` is
    `OPEN`, `RESPONDED` or `ESCALATED` - findings already `CLEARED` or `WAIVED`
    contribute nothing", and PRD 3.4 confirms clearance "removes this row's
    `exposure_cents` from what later diligence-adjusted snapshots treat as open
    exposure". `available_unrestricted_cents` is then the two parties'
    `unrestricted_net_assets_cents` (59916670 + 40000000) less that exposure, i.e.
    66666670, and `reserve_months` is that over the summed per-organization monthly
    figure 16666668, rounded half up to two places, exactly 4.00 - inside the "at
    least three but under six" tier worth `20.00`. With identical mission codes
    (`40.00`) and no programmes (`0.00`) the composite is 60.00, banded `MODERATE`
    at "at least `60.00` but under 80".

    Design: Corner/calculations/diligence_adjusted_exposure_ignores_a_cleared_finding
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])

    cleared = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="FINANCE",
                severity="HIGH",
                summary="Unreconciled pledge receivable",
                exposure_cents=29916670,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )
    validate_success(
        api.respond_diligence_request(
            cleared["id"], f.diligence_respond_payload(response_ref="RESP-0011"), officer
        )
    )
    cleared = validate_success(
        api.clear_diligence_request(
            cleared["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2
        )
    )

    still_open = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="WORKFORCE",
                severity="HIGH",
                summary="Unfunded accrued leave liability for transferring staff",
                exposure_cents=33250000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )

    snapshot = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"), officer
        ),
        201,
    )

    assert_status(cleared, "CLEARED")
    assert_status(still_open, "OPEN")
    assert_field(snapshot, "sequence_no", 1)
    assert_money_equals(
        snapshot["open_diligence_exposure_cents"], 33250000,
        "open_diligence_exposure_cents",
    )
    assert_money_equals(
        snapshot["available_unrestricted_cents"], 66666670,
        "available_unrestricted_cents",
    )
    assert_money_equals(
        snapshot["combined_monthly_expense_cents"], 16666668,
        "combined_monthly_expense_cents",
    )
    assert_decimal_equals(snapshot["reserve_months"], 4.00, 2, "reserve_months")
    assert_decimal_equals(
        snapshot["sustainability_points"], 20.00, 2, "sustainability_points"
    )
    assert_decimal_equals(
        snapshot["mission_alignment_points"], 40.00, 2, "mission_alignment_points"
    )
    assert_decimal_equals(snapshot["composite_score"], 60.00, 2, "composite_score")
    assert_field(snapshot, "composite_rating", "MODERATE")
