"""The version token is a counter, and the money it guards is conserved.

Two write endpoints carry a token the client must have observed, and both are
defended on the token alone: the replay is refused while the identical body with a
fresh token is accepted. Underneath that guard the custody arithmetic has to hold
across a whole lifecycle — a hold recomputed by successive receipts, a conversion
that moves the hold plus its earnings, and a release that restores availability to
the cent, all without a money source ever being touched by a hold.
"""

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_ap_account_totals,
    assert_case_dimensions,
    assert_conserved,
    assert_derived_from_money_sources,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
    assert_settlement,
    assert_statuses_in_order,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_15
from test_helpers.test_users import ADMIN_HEADERS
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DISTRIBUTION_CODE_2,
    DISTRIBUTION_ISSUED,
    DISTRIBUTION_VOIDED,
    DRAFT_SUPERSEDED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    ELECTION_CASH,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    HOLD_RELEASED,
    REVIEW_INTAKE,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SEGREGATION_NONE,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
)

OCC_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}

# The conservation scenario needs the four-source mix and the 548-day window, so
# the plan is spelled out in full rather than leaning on the defaults.
CONSERVATION_PLAN = dict(
    OCC_PLAN,
    review_period_days=45,
    segregation_period_days=548,
    resubmission_window_days=60,
    max_revisions=3,
)

# The two snapshots that make the conversion credit 300 bps of growth: the
# valuation date, then the first snapshot on or after the segregation date.
CONSERVATION_SNAPSHOTS = (("2026-06-30", 4000000), ("2026-12-31", 4120000))

WRONA = {
    "full_name": "Casimir Wrona",
    "ssn_last4": "8080",
    "date_of_birth": "1969-09-09",
    "participation_start_date": "1999-01-01",
}
WRONA_CASE = {
    "alternate_payee_name": "Wanda Wrona",
    "alternate_payee_dob": "1981-07-05",
    "marital_period_start": "2012-03-01",
    "marital_period_end": "2026-02-01",
}

# What the four sources hold once the conversion has debited them.
SOURCES_AFTER_CONVERSION = {
    SOURCE_AFTER_TAX: 58800,
    SOURCE_EMPLOYER_MATCH: 876193,
    SOURCE_PRE_TAX_DEFERRAL: 1417006,
    SOURCE_LOAN_RECEIVABLE: 300000,
}


def _case_in_intake(client, plan_name):
    """A funded account and a case that has never seen a draft order."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        fixtures.SINGLE_SOURCE,
        (("2026-06-30", 1000000),),
        plan_overrides=OCC_PLAN,
        participant_overrides={
            "full_name": "Vidar Holmstrom",
            "ssn_last4": "9101",
            "date_of_birth": "1974-10-10",
            "participation_start_date": "2010-01-01",
        },
    )
    fixtures.set_clock(client, CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Gudrun Holmstrom",
        alternate_payee_dob="1976-11-11",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    assert_case_dimensions(setup["case"], REVIEW_INTAKE, SEGREGATION_NONE, version=1)
    return setup


def test_a_receipt_replayed_on_the_version_it_already_consumed_is_refused(client):
    """The first receipt makes the client's own token stale, and the replay changes nothing.

    PRD: "If `expected_case_version` does not equal the target case's current
    `version`, the receipt is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412),
    preventing the client from overwriting terms it has not observed."

    Design: Corner/cross_cutting_complexity_layers/a_second_draft_filed_on_a_stale_case_version_is_refused_and_supersedes_nothing
    """
    setup = _case_in_intake(client, "Concurrency Plan")
    case_id = setup["case"]["id"]
    account_id = setup["account"]["id"]
    stale_version = setup["case"]["version"]

    first = fixtures.receive_draft(
        client, case_id, stale_version, document_reference="DRO-2663-OCC-1"
    )
    assert first["status"] == DRAFT_UNDER_REVIEW
    fresh = fixtures.read_case(client, case_id)
    assert_case_dimensions(fresh, REVIEW_UNDER_REVIEW, SEGREGATION_HELD, version=2)

    # Everything in the replay is valid except the token it carries.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                case_id,
                stale_version,
                document_reference="DRO-2663-OCC-replay",
                proposed_percentage_bps=3000,
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_STALE_CASE_VERSION,
        412,
    )

    # The live draft's own terms were not overwritten by the refused replay.
    live = fixtures.read_draft(client, first["id"])
    assert live["status"] == DRAFT_UNDER_REVIEW
    assert live["proposed_percentage_bps"] == 4000
    assert len(fixtures.read_holds(client, qdro_case_id=case_id)) == 1
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )

    # The identical body with the observed token does supersede, so only the stale
    # token was ever the obstacle.
    second = fixtures.receive_draft(
        client,
        case_id,
        fresh["version"],
        document_reference="DRO-2663-OCC-2",
        proposed_percentage_bps=3000,
    )
    assert second["status"] == DRAFT_UNDER_REVIEW
    assert fixtures.read_draft(client, first["id"])["status"] == DRAFT_SUPERSEDED
    assert fixtures.read_case(client, case_id)["version"] == 3
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=300000,
        available_balance_cents=700000,
    )


def test_a_void_makes_the_pre_void_token_stale_though_the_balance_matches(client):
    """A duplicate election is refused, and the version keeps moving where money does not.

    PRD: "If `expected_ap_account_version` does not equal the target payee account's
    current `version`, the distribution is rejected with
    `ERR_STALE_AP_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_distribution_elected_against_a_stale_payee_account_version_is_refused
    """
    setup = fixtures.setup_qualified_separate_interest(
        client,
        "Election Plan",
        participant_overrides={
            "full_name": "Petra Loewen",
            "ssn_last4": "9202",
            "date_of_birth": "1973-12-12",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Hedda Loewen",
            "alternate_payee_dob": "1978-02-02",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-OCC-AP"},
    )
    ap_account = setup["ap_account"]
    ap_id = ap_account["id"]
    payee = fixtures.payee_headers(ap_account)
    assert ap_account["version"] == 1
    assert ap_account["balance_cents"] == 400000

    first = fixtures.issue_distribution(
        client, ap_id, ap_account["version"], 100000, headers=payee,
        election=ELECTION_CASH,
    )
    assert_settlement(
        first,
        gross_amount_cents=100000,
        basis_recovery_cents=0,
        taxable_amount_cents=100000,
        federal_withheld_cents=20000,
        net_before_fee_cents=80000,
        admin_fee_cents=2500,
        net_amount_cents=77500,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    # The duplicate submission is the double payment this guard exists to stop.
    assert_error_envelope(
        client.create_distribution(
            ap_id,
            factories.distribution_payload(
                ap_account["version"], 100000, election=ELECTION_CASH
            ),
            payee,
        ),
        api_errors.ERR_STALE_AP_ACCOUNT_VERSION,
        412,
    )
    issued = fixtures.read_distributions(client, ap_id, status=DISTRIBUTION_ISSUED)
    assert len(issued) == 1, f"a second payment was made: {issued}"

    after_first = fixtures.read_ap_account(client, ap_id, headers=payee)
    assert after_first["version"] == 2
    assert after_first["balance_cents"] == 300000

    # The retry with the observed token is accepted on identical terms.
    second = fixtures.issue_distribution(
        client, ap_id, after_first["version"], 100000, headers=payee,
        election=ELECTION_CASH,
    )
    assert_settlement(second, net_amount_cents=77500, admin_fee_cents=2500)

    voided = fixtures.void_distribution(client, second["id"])
    assert voided["status"] == DISTRIBUTION_VOIDED
    restored = fixtures.read_ap_account(client, ap_id, headers=payee)
    assert restored["balance_cents"] == 300000, (
        "the void restored the balance the client saw when it captured the token"
    )

    # Same money, later counter: the token is not a checksum of the money fields.
    assert_error_envelope(
        client.create_distribution(
            ap_id,
            factories.distribution_payload(
                after_first["version"], 100000, election=ELECTION_CASH
            ),
            payee,
        ),
        api_errors.ERR_STALE_AP_ACCOUNT_VERSION,
        412,
    )
    assert restored["version"] == 4, (
        "the issuance and the void each incremented the payee account version"
    )
    assert_ap_account_totals(
        restored,
        fixtures.read_distributions(client, ap_id),
        established_balance_cents=400000,
        established_basis_cents=0,
    )


def _conservation_account(client, plan_name):
    """The four-source account whose custody arithmetic has to balance."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        fixtures.FOUR_SOURCE_MIX,
        CONSERVATION_SNAPSHOTS,
        plan_overrides=CONSERVATION_PLAN,
        participant_overrides=WRONA,
    )
    # The loan bucket counts toward the vested balance but not the assignable base.
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=4300000,
        assignable_base_cents=4000000,
        after_tax_basis_cents=60000,
        held_amount_cents=0,
        available_balance_cents=4300000,
    )
    fixtures.set_clock(client, CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client, setup["participant"]["id"], **WRONA_CASE
    )
    return setup


def test_successive_receipts_resize_one_hold_and_debit_no_source(client):
    """Each supersede recomputes the single hold in place and leaves the buckets alone.

    PRD: "Any existing draft order on the case that is still `UNDER_REVIEW` or
    `DEFICIENT` moves to `SUPERSEDED`, and every rejection notice on that superseded
    row that was still `ISSUED` moves to `EXPIRED`. No correspondence entry is
    appended on account of the superseded row itself. If the case was sitting at
    `review_status` `DEFICIENT`, the superseding receipt returns it to `UNDER_REVIEW`;
    the case's five operative terms are overwritten from the new draft in either
    event. The existing hold is **not** re-placed: `placed_at` and therefore
    `expires_at` survive from the first receipt, and only `hold_amount_cents` is
    recomputed from the new terms, after which the account's derived balances are
    recomputed."

    Design: Difficulty/compensating_invariant/custody_conservation_across_supersede_conversion_and_release
    """
    setup = _conservation_account(client, "Conservation Plan")
    case_id = setup["case"]["id"]
    account_id = setup["account"]["id"]
    opening_sources = fixtures.money_source_balances(client, account_id)

    first = fixtures.receive_draft(
        client, case_id, 1, document_reference="DRO-2663-V1"
    )
    assert_hold(
        fixtures.hold_for_case(client, case_id),
        status=HOLD_HELD,
        hold_amount_cents=1600000,
        placed_at=CLOCK_2026_09_01,
        expires_at="2028-03-02T00:00:00Z",
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=1600000,
        available_balance_cents=2700000,
    )

    # Down: the superseding receipt resizes the same hold rather than stacking one.
    second = fixtures.receive_draft(
        client,
        case_id,
        fixtures.read_case(client, case_id)["version"],
        document_reference="DRO-2663-V2",
        proposed_percentage_bps=2000,
    )
    holds = fixtures.read_holds(client, qdro_case_id=case_id)
    assert len(holds) == 1, f"the supersede stacked a second hold: {holds}"
    assert_hold(holds[0], status=HOLD_HELD, hold_amount_cents=800000)
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=800000,
        available_balance_cents=3500000,
    )
    assert fixtures.read_draft(client, first["id"])["status"] == DRAFT_SUPERSEDED

    # Up again: the recomputation is bidirectional and does not restart the window.
    third = fixtures.receive_draft(
        client,
        case_id,
        fixtures.read_case(client, case_id)["version"],
        document_reference="DRO-2663-V3",
    )
    assert_hold(
        fixtures.hold_for_case(client, case_id),
        status=HOLD_HELD,
        hold_amount_cents=1600000,
        placed_at=CLOCK_2026_09_01,
        expires_at="2028-03-02T00:00:00Z",
        segregation_date=None,
    )
    account = fixtures.read_plan_account(client, account_id)
    assert_plan_account_figures(
        account,
        vested_balance_cents=4300000,
        assignable_base_cents=4000000,
        after_tax_basis_cents=60000,
        held_amount_cents=1600000,
        available_balance_cents=2700000,
    )

    # A hold reserves; it never debits. Both directions of the reconciliation.
    assert fixtures.money_source_balances(client, account_id) == opening_sources
    assert_derived_from_money_sources(
        account,
        fixtures.read_money_sources(client, account_id),
        holds=fixtures.read_holds(client, plan_account_id=account_id),
    )
    assert_statuses_in_order(
        fixtures.read_holds(client, qdro_case_id=case_id), [HOLD_HELD]
    )
    on_the_case = [
        fixtures.read_draft(client, draft["id"])["status"]
        for draft in (first, second, third)
    ]
    assert on_the_case == [DRAFT_SUPERSEDED, DRAFT_SUPERSEDED, DRAFT_UNDER_REVIEW]
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        REVIEW_UNDER_REVIEW,
        SEGREGATION_HELD,
        version=4,
    )


def test_the_conversion_moves_the_hold_and_its_earnings_and_the_release_restores_the_rest(client):
    """Money and basis both balance across the conversion, and the release drifts nowhere.

    PRD: "Because the payee account was funded, the participant's side is debited —
    but only in the separate-interest shape. Each assignable money source, in
    `source_code` ascending order, is debited by the sum of its allocated share and
    its own per-source earnings figure, both from §3.5. Because money source balances
    changed, the account's `vested_balance_cents`, `assignable_base_cents`, and
    `after_tax_basis_cents` are recomputed; and because the hold left `HELD`,
    `held_amount_cents` drops to 0 and `available_balance_cents` is recomputed with
    it."

    Design: Difficulty/compensating_invariant/custody_conservation_across_supersede_conversion_and_release
    """
    setup = _conservation_account(client, "Conservation Plan B")
    case_id = setup["case"]["id"]
    account_id = setup["account"]["id"]
    opening = fixtures.read_plan_account(client, account_id)

    draft = fixtures.receive_draft(
        client, case_id, 1, document_reference="DRO-2663-V3"
    )
    fixtures.set_clock(client, CLOCK_2026_09_15)
    fixtures.qualify(client, draft["id"])

    # The carved-out pot is the hold plus the earnings credited on the way out.
    payee = fixtures.ap_account_for_case(client, case_id)
    assert payee["balance_cents"] == 1648001
    assert payee["after_tax_basis_cents"] == 24000
    assert_ap_account_totals(payee, [], established_balance_cents=1648001)
    converted = fixtures.hold_for_case(client, case_id)
    assert_hold(
        converted,
        status=HOLD_CONVERTED,
        hold_amount_cents=1600000,
        segregation_date="2026-09-15",
        earnings_growth_bps=300,
        earnings_adjustment_cents=48001,
    )

    after_conversion = fixtures.read_plan_account(client, account_id)
    assert_plan_account_figures(
        after_conversion,
        vested_balance_cents=2651999,
        assignable_base_cents=2351999,
        after_tax_basis_cents=36000,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )
    # Nothing was created and nothing was lost on either quantity.
    assert_conserved(
        opening["vested_balance_cents"],
        [after_conversion["vested_balance_cents"], payee["balance_cents"]],
        label="money",
    )
    assert_conserved(
        opening["after_tax_basis_cents"],
        [after_conversion["after_tax_basis_cents"], payee["after_tax_basis_cents"]],
        label="after-tax basis",
    )
    # The same conclusion read bottom-up from the buckets themselves: the debit is
    # each source's allocated share plus its own share of the earnings.
    balances = fixtures.money_source_balances(client, account_id)
    assert balances == SOURCES_AFTER_CONVERSION
    assert sum(balances.values()) == after_conversion["vested_balance_cents"]
    debits = [
        opening_balance - balances[source_code]
        for source_code, opening_balance in (
            (SOURCE_AFTER_TAX, 100000),
            (SOURCE_EMPLOYER_MATCH, 1490125),
            (SOURCE_PRE_TAX_DEFERRAL, 2409875),
        )
    ]
    assert debits == [41200, 613932, 992869]
    assert_conserved(payee["balance_cents"], debits, label="per-source debit")
    assert balances[SOURCE_LOAN_RECEIVABLE] == 300000, (
        "the non-assignable bucket takes part in nothing"
    )

    # A second, merely adjacent marital period on the same participant is priced
    # against the POST-conversion assignable base.
    second_case = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Zofia Wrona",
        alternate_payee_dob="1979-11-11",
        marital_period_start="2000-01-01",
        marital_period_end="2012-03-01",
    )
    faulty = fixtures.receive_draft(
        client,
        second_case["id"],
        second_case["version"],
        document_reference="DRO-2663-V4",
        uses_model_language=False,
    )
    assert faulty["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    second_hold = fixtures.hold_for_case(client, second_case["id"])
    assert_hold(second_hold, status=HOLD_HELD, hold_amount_cents=940799)

    fixtures.deny(client, faulty["id"], DENIAL_ORDER_NOT_QUALIFIABLE)
    released = fixtures.release_hold(client, second_hold["id"])
    assert released["status"] == HOLD_RELEASED

    # The release restores availability to the cent and touched no bucket.
    final = fixtures.read_plan_account(client, account_id)
    assert_plan_account_figures(
        final,
        vested_balance_cents=2651999,
        assignable_base_cents=2351999,
        after_tax_basis_cents=36000,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )
    assert fixtures.money_source_balances(client, account_id) == SOURCES_AFTER_CONVERSION
    assert_derived_from_money_sources(
        final,
        fixtures.read_money_sources(client, account_id),
        holds=fixtures.read_holds(client, plan_account_id=account_id),
    )
    assert_statuses_in_order(
        fixtures.read_holds(client, plan_account_id=account_id),
        [HOLD_CONVERTED, HOLD_RELEASED],
    )
    assert_hold(
        fixtures.hold_for_case(client, second_case["id"]),
        status=HOLD_RELEASED,
        hold_amount_cents=940799,
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    # A denied case never establishes a payee account, so no phantom custody exists.
    assert len(fixtures.read_ap_accounts(client, case_id)) == 1
    assert fixtures.read_ap_accounts(client, second_case["id"]) == []
