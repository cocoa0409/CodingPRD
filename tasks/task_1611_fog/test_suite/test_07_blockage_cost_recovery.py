"""Blockage events: assessment apportionment, payment, and closure."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assess_blockage_payload,
    close_blockage,
    create_and_assess_blockage,
    create_blockage,
    create_establishment,
    get_success_data,
    make_compliance_officer_headers,
    make_inspector_headers,
    pay_share,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestCostShareApportionment:
    def test_cost_share_per_share_rounding_with_remainder(self, api):
        """PRD: "Apportionment follows a pinned rounding order: each share is
        the total cleanup cost multiplied by the contribution's weight and
        divided by 100, rounded half-up to whole cents; then the remainder
        between the total and the sum of the rounded shares — which may be
        negative — is assigned to the contribution carrying the largest
        `weight_percent`, with ties resolved in favor of the contribution
        whose establishment was created earliest."
        PRD: "Assessment records `assessed_by_user_id` and moves the event
        from `REPORTED` to `ASSESSED`."

        Design: Difficulty/combinatorial_formula/cost_share_per_share_rounding_with_remainder
        """
        ea = create_establishment(name="Cafe A", street_address="10 A St")
        eb = create_establishment(name="Cafe B", street_address="11 B St")
        ec = create_establishment(name="Cafe C", street_address="12 C St")
        blockage = create_blockage("Main St sewer segment 7")

        assessed = validate_success(api.assess_blockage_event(
            blockage["id"],
            assess_blockage_payload(10001, [
                {"establishment_id": ea["id"], "weight_percent": 33},
                {"establishment_id": eb["id"], "weight_percent": 33},
                {"establishment_id": ec["id"], "weight_percent": 34},
            ]),
            INSPECTOR))
        assert assessed["status"] == "ASSESSED"

        shares = {c["establishment_id"]: c["share_cents"]
                  for c in assessed["contributions"]}
        # round_half_up(10001*33/100) = round_half_up(3300.33) = 3300.
        assert shares[ea["id"]] == 3300
        assert shares[eb["id"]] == 3300
        # Largest weight takes the remainder: 3400 + 1.
        assert shares[ec["id"]] == 3401
        assert sum(shares.values()) == 10001, "Remainder fully reconciled"

    def test_cost_share_remainder_tie_breaks_to_earliest_establishment(self, api):
        """PRD: "then the remainder between the total and the sum of the
        rounded shares — which may be negative — is assigned to the
        contribution carrying the largest `weight_percent`, with ties resolved
        in favor of the contribution whose establishment was created
        earliest."
        PRD: "summing the unrounded shares and rounding only the total is
        forbidden, because it yields different cents."

        Design: Difficulty/combinatorial_formula/cost_share_per_share_rounding_with_remainder
        """
        first = create_establishment(name="First Fork",
                                     street_address="13 A St")
        second = create_establishment(name="Second Spoon",
                                      street_address="14 A St")
        blockage = create_blockage("Tie-break segment")
        # round_half_up(10001*50/100) = round_half_up(5000.5) = 5001 each;
        # remainder 10001 - 10002 = -1 goes to the tied contribution whose
        # establishment was created earliest.
        assessed = validate_success(api.assess_blockage_event(
            blockage["id"],
            assess_blockage_payload(10001, [
                {"establishment_id": first["id"], "weight_percent": 50},
                {"establishment_id": second["id"], "weight_percent": 50},
            ]),
            INSPECTOR))
        shares = {c["establishment_id"]: c["share_cents"]
                  for c in assessed["contributions"]}
        assert shares[first["id"]] == 5000, (
            "Negative remainder lands on the earliest-created tied contributor"
        )
        assert shares[second["id"]] == 5001
        assert sum(shares.values()) == 10001


class TestAssessmentGuards:
    def test_assess_empty_contributions_rejected(self, api):
        """PRD: "Three guards apply: every establishment named among the
        contributions must exist (`ERR_NOT_FOUND`); the array must not be
        empty (`ERR_NO_CONTRIBUTORS`, HTTP 422); and the weights must sum to
        exactly 100 (`ERR_WEIGHTS_INVALID`, HTTP 422)."

        Design: Corner/validations/c_assess_empty_contributions_rejected
        """
        blockage = create_blockage("9th Ave")
        resp = api.assess_blockage_event(
            blockage["id"], assess_blockage_payload(5000, []), INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_NO_CONTRIBUTORS, 422)
        current = validate_success(api.get_blockage_event(blockage["id"],
                                                          INSPECTOR))
        assert current["status"] == "REPORTED"

    def test_assess_weights_not_100_rejected(self, api):
        """PRD: "the weights must sum to exactly 100 (`ERR_WEIGHTS_INVALID`,
        HTTP 422)"

        Design: Corner/validations/c_assess_weights_not_100_rejected
        """
        e1 = create_establishment(name="W1", street_address="26 V St")
        e2 = create_establishment(name="W2", street_address="27 V St")
        blockage = create_blockage("10th Ave")
        resp = api.assess_blockage_event(
            blockage["id"],
            assess_blockage_payload(5000, [
                {"establishment_id": e1["id"], "weight_percent": 60},
                {"establishment_id": e2["id"], "weight_percent": 30},
            ]),
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_WEIGHTS_INVALID, 422)
        current = validate_success(api.get_blockage_event(blockage["id"],
                                                          INSPECTOR))
        assert current["status"] == "REPORTED"

    def test_close_with_unpaid_shares_rejected(self, api):
        """PRD: "Closure belongs to a `ComplianceOfficer` and is deliberately
        two-keyed: the closer's identity must differ from
        `assessed_by_user_id` (`ERR_SOD_VIOLATION`, HTTP 403), and every
        contribution must show a non-null `paid_at` (`ERR_COST_SHARE_UNPAID`,
        HTTP 409)."

        Design: Corner/validations/c_close_with_unpaid_shares_rejected
        """
        est = create_establishment(name="Unpaid Udon", street_address="28 W St")
        blockage = create_and_assess_blockage(
            5000, [{"establishment_id": est["id"], "weight_percent": 100}],
            inspector_user_id="insp-1", location_description="11th Ave")
        resp = api.close_blockage_event(
            blockage["id"], make_compliance_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_COST_SHARE_UNPAID, 409)
        current = validate_success(api.get_blockage_event(blockage["id"],
                                                          INSPECTOR))
        assert current["status"] == "ASSESSED"


class TestBlockageHappyPath:
    def test_blockage_happy_path_assess_pay_close(self, api):
        """PRD: "each share is the total cleanup cost multiplied by the
        contribution's weight and divided by 100, rounded half-up to whole
        cents"
        PRD: "An establishment contact pays its own establishment's share by
        naming its `establishment_id`; the server stamps that contribution's
        `paid_at` with the current clock."
        PRD: "A successful close records `closed_by_user_id` and moves the
        event from `ASSESSED` to the terminal `CLOSED` status."

        Design: Corner/endpoints/c_blockage_happy_path_assess_pay_close
        """
        ea = create_establishment(name="Happy A", street_address="29 X St")
        eb = create_establishment(name="Happy B", street_address="30 X St")
        blockage = create_blockage("12th Ave", inspector_user_id="insp-2")

        assessed = validate_success(api.assess_blockage_event(
            blockage["id"],
            assess_blockage_payload(20000, [
                {"establishment_id": ea["id"], "weight_percent": 50},
                {"establishment_id": eb["id"], "weight_percent": 50},
            ]),
            make_inspector_headers("insp-2")))
        assert assessed["status"] == "ASSESSED"
        shares = sorted(c["share_cents"] for c in assessed["contributions"])
        assert shares == [10000, 10000], "Even 50/50 split of 20000"

        pay_share(blockage["id"], ea["id"])
        pay_share(blockage["id"], eb["id"])
        mid = validate_success(api.get_blockage_event(blockage["id"], INSPECTOR))
        assert all(c["paid_at"] is not None for c in mid["contributions"]), (
            "Each pay stamps that contribution's paid_at"
        )

        closed = close_blockage(blockage["id"], officer_user_id="officer-2")
        assert closed["status"] == "CLOSED"
        assert closed["closed_by_user_id"] == "officer-2"
