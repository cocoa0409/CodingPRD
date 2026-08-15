"""Airline agreements: the countersign deadline boundary, double
countersigning, and create-with-supersede rented-space conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_rates_for_year,
    countersign,
    create_agreement,
    get_success_data,
    make_signatory_airline_headers,
    refresh_fiscal_year,
    set_clock,
    setup_open_year,
    setup_signatory_year,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]


class TestCountersignDeadline:
    def test_countersign_at_exact_deadline_succeeds(self, api):
        """PRD §3.1: "That deadline is not chosen at creation — it is stamped
        when the rate schedule is adopted, as `adopted_at` plus thirty days
        (§3.2). A countersignature arriving after the deadline is rejected with
        `ERR_COUNTERSIGN_LAPSED`"
        PRD §3.1: "A successful countersign sets `signature_status` to
        `SIGNATORY`, recomputes the year's `total_rented_space_sqft` — the
        agreement's rented space now counts — and increments the agreement's
        `version`."

        Design: Difficulty/resource_temporal_overlap/countersign_deadline_exact_boundary
        """
        ws = setup_open_year("FY_OVL2", airline_specs=[{"iata_code": "OA"}])
        adopt_rates_for_year(ws)  # adopted 2026-09-01 -> deadline 2026-10-01
        agreement = get_success_data(api.get_airline_agreement(
            ws["agreements"]["OA"]["id"], FINANCE))
        assert agreement["countersign_deadline"].startswith("2026-10-01"), (
            "countersign_deadline is adopted_at plus thirty days")

        set_clock("2026-10-01T00:00:00Z")
        signed = validate_success(api.countersign_agreement(
            agreement["id"],
            make_signatory_airline_headers(ws["airlines"]["OA"]["id"])))
        assert signed["signature_status"] == "SIGNATORY", (
            "A countersignature at exactly the deadline has not passed it")

    def test_countersign_one_second_past_deadline_rejected(self, api):
        """PRD §3.1: "That deadline is not chosen at creation — it is stamped
        when the rate schedule is adopted, as `adopted_at` plus thirty days
        (§3.2). A countersignature arriving after the deadline is rejected with
        `ERR_COUNTERSIGN_LAPSED`"
        PRD §3.1: "Every agreement begins with `signature_status` of
        `NON_SIGNATORY` and `credit_standing` of `GOOD`."

        Design: Difficulty/resource_temporal_overlap/countersign_deadline_exact_boundary
        """
        ws = setup_open_year("FY_OVL3", airline_specs=[{"iata_code": "OB"}])
        adopt_rates_for_year(ws)  # adopted 2026-09-01 -> deadline 2026-10-01
        agreement = ws["agreements"]["OB"]

        set_clock("2026-10-01T00:00:01Z")
        resp = api.countersign_agreement(
            agreement["id"],
            make_signatory_airline_headers(ws["airlines"]["OB"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COUNTERSIGN_LAPSED)

        after = get_success_data(api.get_airline_agreement(agreement["id"],
                                                           FINANCE))
        assert after["signature_status"] == "NON_SIGNATORY"


class TestDoubleCountersign:
    def test_countersign_already_signatory_rejected(self, api):
        """PRD §3.1: "countersigning an agreement that already stands
        `SIGNATORY` is rejected with `ERR_DOUBLE_COUNTERSIGN`."

        Design: Corner/validations/double_countersign_rejected
        """
        ws = setup_signatory_year("FY_DC", airline_specs=[{"iata_code": "DC"}])
        agreement = ws["agreements"]["DC"]
        assert agreement["signature_status"] == "SIGNATORY"

        resp = api.countersign_agreement(agreement["id"],
                                         ws["airline_headers"]["DC"])
        validate_error(resp, ApiErrorId.ERR_DOUBLE_COUNTERSIGN)


class TestCreateWithSupersede:
    def _setup_signatory_with_space(self, api):
        return setup_signatory_year(
            "FY_INV2",
            airline_specs=[{"iata_code": "SP", "rented_space_sqft": 1000}],
        )

    def test_supersede_links_prior_agreement(self, api):
        """PRD §3.1: "Creation is implicitly a create-with-supersede: if the
        carrier already holds an active agreement on the same fiscal year, the
        earlier row's `superseded_by_id` is set to the new agreement's `id`,
        and the year's `total_rented_space_sqft` is recomputed."
        PRD §3.1: "A successful countersign sets `signature_status` to
        `SIGNATORY`, recomputes the year's `total_rented_space_sqft` — the
        agreement's rented space now counts — and increments the agreement's
        `version`."

        Design: Difficulty/compensating_invariant/supersede_agreement_rented_space_conserved
        """
        ws = self._setup_signatory_with_space(api)
        fy = refresh_fiscal_year(ws)
        assert fy["total_rented_space_sqft"] == 1000, (
            "The countersigned agreement's space counts toward the year total")

        old = ws["agreements"]["SP"]
        new = create_agreement(ws["airlines"]["SP"]["id"], ws["fy"]["id"],
                               rented_space_sqft=1500)
        superseded = get_success_data(api.get_airline_agreement(old["id"],
                                                                FINANCE))
        assert superseded["superseded_by_id"] == new["id"], (
            "The earlier row's superseded_by_id points at the new agreement")

    def test_countersigning_successor_conserves_rented_space_total(self, api):
        """PRD §3.1: "Creation is implicitly a create-with-supersede: if the
        carrier already holds an active agreement on the same fiscal year, the
        earlier row's `superseded_by_id` is set to the new agreement's `id`,
        and the year's `total_rented_space_sqft` is recomputed."
        PRD §3.1: "A successful countersign sets `signature_status` to
        `SIGNATORY`, recomputes the year's `total_rented_space_sqft` — the
        agreement's rented space now counts — and increments the agreement's
        `version`."

        Design: Difficulty/compensating_invariant/supersede_agreement_rented_space_conserved
        """
        ws = self._setup_signatory_with_space(api)
        new = create_agreement(ws["airlines"]["SP"]["id"], ws["fy"]["id"],
                               rented_space_sqft=1500)
        countersign(new["id"], ws["airlines"]["SP"]["id"])

        fy = refresh_fiscal_year(ws)
        assert fy["total_rented_space_sqft"] == 1500, (
            "The total reflects exactly the successor's space — the superseded "
            "row is not double-counted")
