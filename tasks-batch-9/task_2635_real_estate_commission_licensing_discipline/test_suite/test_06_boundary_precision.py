"""One cent, and one score point, on either side of an inclusive threshold."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import assert_book_position, assert_posture
from test_helpers.test_users import make_analyst_headers, make_counsel_headers

OBLIGATION_CENTS = 1000000


def _firm_holding_an_obligation(client, name, broker_name):
    """A live firm whose escrow account owes a round 1,000,000 cents."""
    firm = fixtures.bootstrap_active_brokerage(client, name=name, broker_name=broker_name)
    fixtures.append_ledger_entry(
        client,
        firm["account"]["id"],
        "OBLIGATION_OPENED",
        OBLIGATION_CENTS,
        "2026-08-01",
        f"OBL-{name[:3].upper()}",
    )
    return firm


class TestShortageThresholdIsInclusiveOnTheRestrictedSide:
    """99,999 cents is only a watch; 100,000 cents restricts the firm."""

    def test_one_cent_short_of_the_threshold_grades_watch(self, client):
        """A deposit of 900,001 leaves 99,999 owing, which is merely `WATCH`.

        The PRD says "The shortage boundary is inclusive on the `RESTRICTED`
        side: a shortage of exactly 100,000 cents grades `RESTRICTED`, while
        99,999 cents grades `WATCH`."

        Design: Difficulty/boundary_precision_check/posture_shortage_threshold_99999_watch_versus_100000_restricted_on_ledger_append
        """
        firm = _firm_holding_an_obligation(client, "Alpha Realty", "Al Broker")
        fixtures.append_ledger_entry(
            client, firm["account"]["id"], "DEPOSIT", 900001, "2026-08-02", "DEP-A1"
        )

        account = fixtures.read_trust_account(client, firm["account"]["id"])
        assert account["shortage_cents"] == 99999
        brokerage = fixtures.read_brokerage(client, firm["brokerage"]["id"])
        assert brokerage["open_shortage_cents"] == 99999
        assert_posture(brokerage, "WATCH")

    def test_exactly_the_threshold_grades_restricted(self, client):
        """A deposit of 900,000 leaves exactly 100,000 owing, which restricts.

        The PRD says "Otherwise the posture is `RESTRICTED` when any of three
        conditions holds: `open_shortage_cents` is at least 100,000 cents, that
        is one thousand dollars of unreconciled client money; or the designated
        broker's `discipline_status` is `UNDER_INVESTIGATION`, `PENDING_HEARING`
        or `SANCTIONED`; or the designated broker's `license_status` is
        `INACTIVE`."

        Design: Difficulty/boundary_precision_check/posture_shortage_threshold_99999_watch_versus_100000_restricted_on_ledger_append
        """
        firm = _firm_holding_an_obligation(client, "Beta Realty", "Bea Broker")
        fixtures.append_ledger_entry(
            client, firm["account"]["id"], "DEPOSIT", 900000, "2026-08-02", "DEP-B1"
        )

        account = fixtures.read_trust_account(client, firm["account"]["id"])
        assert account["shortage_cents"] == 100000
        brokerage = fixtures.read_brokerage(client, firm["brokerage"]["id"])
        assert brokerage["open_shortage_cents"] == 100000
        assert_posture(brokerage, "RESTRICTED")

    def test_a_single_cent_of_fresh_obligation_crosses_the_line_in_place(self, client):
        """The tier tracks the live figure; no audit is involved anywhere.

        The PRD says "It is re-derived on every mutation that touches the
        brokerage, any of its trust accounts or audits, any affiliated
        licensee's `license_status` or `discipline_status`, any complaint naming
        the firm, and on every compliance sweep — as well as on every read of
        the brokerage."

        Design: Difficulty/boundary_precision_check/posture_shortage_threshold_99999_watch_versus_100000_restricted_on_ledger_append
        """
        firm = _firm_holding_an_obligation(client, "Alpha Realty", "Al Broker")
        account_id = firm["account"]["id"]
        fixtures.append_ledger_entry(
            client, account_id, "DEPOSIT", 900001, "2026-08-02", "DEP-A1"
        )
        assert_posture(fixtures.read_brokerage(client, firm["brokerage"]["id"]), "WATCH")

        fixtures.append_ledger_entry(
            client, account_id, "OBLIGATION_OPENED", 1, "2026-08-03", "OBL-A2"
        )

        account = fixtures.read_trust_account(client, account_id)
        assert account["shortage_cents"] == 100000
        assert account["status"] == "OPEN", "no audit ever restricted this account"
        assert_book_position(account, 1000001, 900001)
        assert_posture(fixtures.read_brokerage(client, firm["brokerage"]["id"]), "RESTRICTED")

        audits, _meta = validate_paginated(
            client.list_trust_audits(make_analyst_headers(), params={"trust_account_id": account_id})
        )
        assert audits == [], "the posture came from the live figure, not a remediation order"


BELOW_THE_LINE_CENTS = 2499999
ON_THE_LINE_CENTS = 2500000
INVESTIGATOR = "counsel-05"


def _two_advertising_cases_either_side_of_the_score_floor(client):
    """Two complaints differing by one cent of alleged loss, both under investigation."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    rae = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, "Rae Field")
    ken = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, "Ken Ito")

    case_a = fixtures.file_complaint(
        client, rae["id"], "ADVERTISING", BELOW_THE_LINE_CENTS, "Ora Buyer"
    )
    fixtures.dispose_complaint(client, case_a["id"], "INVESTIGATE", counsel_user_id=INVESTIGATOR)
    case_b = fixtures.file_complaint(
        client, ken["id"], "ADVERTISING", ON_THE_LINE_CENTS, "Ivo Renter"
    )
    fixtures.dispose_complaint(client, case_b["id"], "INVESTIGATE", counsel_user_id=INVESTIGATOR)
    return {
        "brokerage_id": brokerage_id,
        "rae": rae,
        "ken": ken,
        "case_a": case_a,
        "case_b": case_b,
    }


def _find_probable_cause(client, complaint_id):
    return client.complaint_disposition(
        complaint_id,
        factories.complaint_disposition_payload("PROBABLE_CAUSE"),
        make_counsel_headers(INVESTIGATOR),
    )


class TestProbableCauseScoreFloorIsInclusive:
    """A score of 39 is refused and a score of exactly 40 is accepted."""

    def test_a_score_of_thirty_nine_is_refused(self, client):
        """Base 15 plus a harm term of 24 falls one point short.

        The PRD says "and the investigation-variant `priority_score` must be at
        least 40, with anything lower refused as
        `ERR_PROBABLE_CAUSE_SCORE_TOO_LOW`."

        Design: Difficulty/boundary_precision_check/probable_cause_score_boundary_39_refused_versus_40_accepted_on_complaint_disposition
        """
        world = _two_advertising_cases_either_side_of_the_score_floor(client)
        case_a = fixtures.read_complaint(client, world["case_a"]["id"])
        assert case_a["status"] == "INVESTIGATION"
        assert case_a["priority_score"] == 39

        validate_error(
            _find_probable_cause(client, world["case_a"]["id"]),
            "ERR_PROBABLE_CAUSE_SCORE_TOO_LOW",
            expected_status=409,
        )

        assert fixtures.read_complaint(client, world["case_a"]["id"])["status"] == "INVESTIGATION"
        assert fixtures.read_licensee(client, world["rae"]["id"])["discipline_status"] == (
            "UNDER_INVESTIGATION"
        )

    def test_a_score_of_exactly_forty_is_accepted(self, client):
        """One more cent buys the twenty-fifth harm point and clears the floor.

        The PRD says "A score of exactly 40 passes."

        Design: Difficulty/boundary_precision_check/probable_cause_score_boundary_39_refused_versus_40_accepted_on_complaint_disposition
        """
        world = _two_advertising_cases_either_side_of_the_score_floor(client)
        case_b = fixtures.read_complaint(client, world["case_b"]["id"])
        assert case_b["priority_score"] == 40

        disposed = validate_success(_find_probable_cause(client, world["case_b"]["id"]))
        assert disposed["status"] == "PROBABLE_CAUSE"
        assert fixtures.read_complaint(client, world["case_a"]["id"])["status"] == (
            "INVESTIGATION"
        ), "the sibling case is untouched by its neighbour's disposition"

    def test_an_amendment_of_one_cent_band_lifts_the_refused_case_over_the_floor(
        self, client
    ):
        """The complainant's revision re-scores the very same row across the line.

        The PRD says "This returns the case `AMENDMENT_REQUESTED →
        INVESTIGATION`, increments `amendment_count` by one, overwrites
        `alleged_loss_cents` with the amended value when one was supplied, and
        re-scores the case under the investigation variant — which is precisely
        how a complainant can lift a borderline case over the probable-cause
        floor."

        Design: Difficulty/boundary_precision_check/probable_cause_score_boundary_39_refused_versus_40_accepted_on_complaint_disposition
        """
        world = _two_advertising_cases_either_side_of_the_score_floor(client)
        complaint_id = world["case_a"]["id"]
        validate_error(
            _find_probable_cause(client, complaint_id), "ERR_PROBABLE_CAUSE_SCORE_TOO_LOW"
        )

        paused = fixtures.dispose_complaint(
            client, complaint_id, "REQUEST_AMENDMENT", counsel_user_id=INVESTIGATOR
        )
        assert paused["status"] == "AMENDMENT_REQUESTED"

        validate_success(
            client.create_amendment(
                complaint_id,
                factories.amendment_payload(
                    "The buyer's revised statement raises the loss by one cent.",
                    amended_alleged_loss_cents=ON_THE_LINE_CENTS,
                ),
                make_analyst_headers(),
            )
        )

        amended = fixtures.read_complaint(client, complaint_id)
        assert amended["status"] == "INVESTIGATION"
        assert amended["amendment_count"] == 1
        assert amended["alleged_loss_cents"] == ON_THE_LINE_CENTS
        assert amended["priority_score"] == 40

        cleared = validate_success(_find_probable_cause(client, complaint_id))
        assert cleared["status"] == "PROBABLE_CAUSE"

    def test_the_firm_stays_compliant_so_no_posture_bump_enters_either_score(self, client):
        """Two open complaints is below the watch threshold, so both bumps are zero.

        The PRD says "Otherwise the posture is `WATCH` when either
        `open_shortage_cents` is greater than 0 — any shortage at all, however
        small — or `open_complaint_count` has reached 3."

        Design: Difficulty/boundary_precision_check/probable_cause_score_boundary_39_refused_versus_40_accepted_on_complaint_disposition
        """
        world = _two_advertising_cases_either_side_of_the_score_floor(client)
        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["open_complaint_count"] == 2
        assert_posture(brokerage, "COMPLIANT")

        assert fixtures.read_complaint(client, world["case_a"]["id"])["priority_score"] == 39
        assert fixtures.read_complaint(client, world["case_b"]["id"])["priority_score"] == 40
