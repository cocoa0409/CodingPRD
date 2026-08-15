"""Settlement review, dispute, and finalization: the dispute-resolve cycle,
finalize preconditions and their ordering, and the finalization cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_activity,
    compute_settlement,
    create_rates_setting,
    dispute_payload,
    get_success_data,
    list_lines,
    pay_all_lines,
    publish_review,
    resolve_payload,
    set_clock,
    setup_computed_settlement,
    setup_finalized_year,
    setup_settlement_in_review,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]

CY_SPEC = [{"iata_code": "CY"}]
CY_ACTIVITY = [{"iata_code": "CY", "landed_weight_kg": 1000}]


class TestDisputeResolveCycle:
    def test_dispute_then_resolve_transitions(self, api):
        """PRD §3.6: "A valid dispute moves the settlement from
        `AIRLINE_REVIEW` to `DISPUTED`."
        PRD §3.6: "Resolving moves the settlement from `DISPUTED` to
        `RESOLVED`."

        Design: Difficulty/non_linear_state_machine/annual_settlement_dispute_resolve_cycle
        """
        ws = setup_settlement_in_review("FY_CYC", CY_SPEC, CY_ACTIVITY)
        sid = ws["settlement"]["id"]
        airline = ws["airlines"]["CY"]

        disputed = validate_success(api.dispute_settlement(
            sid, dispute_payload(airline["id"], "dispute round 1"),
            ws["airline_headers"]["CY"]))
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(api.resolve_settlement(
            sid, resolve_payload(), DIRECTOR))
        assert resolved["status"] == "RESOLVED"

    def test_redispute_reopens_resolved_settlement(self, api):
        """PRD §3.6: "A carrier whose concerns survive resolution may dispute
        again: a further dispute moves the settlement from `RESOLVED` back to
        `DISPUTED`, provided it is raised within forty-five days of the most
        recent resolve and the carrier holds a line in the settlement"

        Design: Difficulty/non_linear_state_machine/annual_settlement_dispute_resolve_cycle
        """
        ws = setup_settlement_in_review("FY_CYC2", CY_SPEC, CY_ACTIVITY)
        sid = ws["settlement"]["id"]
        airline = ws["airlines"]["CY"]

        validate_success(api.dispute_settlement(
            sid, dispute_payload(airline["id"], "round 1"),
            ws["airline_headers"]["CY"]))
        validate_success(api.resolve_settlement(sid, resolve_payload(),
                                                DIRECTOR))
        reopened = validate_success(api.dispute_settlement(
            sid, dispute_payload(airline["id"], "reopen within window"),
            ws["airline_headers"]["CY"]))
        assert reopened["status"] == "DISPUTED", (
            "The dispute-resolve cycle is not one-shot")


class TestFinalizePreconditions:
    def test_finalize_from_computed_reports_invalid_state(self, api):
        """PRD §3.6: "The `AirportDirector` may finalize a settlement standing
        either `AIRLINE_REVIEW` or `RESOLVED`"
        PRD §2.8: "Only after the request is well-formed does the server ask
        whether the target resource's current state admits the requested
        transition (`ERR_INVALID_STATE`)... Endpoint-specific business rules
        rank last of all: ... unsettled lines at finalization
        (`ERR_UNSETTLED_LINES`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_settlement_finalize
        """
        ws = setup_computed_settlement("FY_PVS", [{"iata_code": "PV"}],
                                       [{"iata_code": "PV",
                                         "landed_weight_kg": 1000}])
        sid = ws["settlement"]["id"]

        resp = api.finalize_settlement(sid, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_settlement(sid, FINANCE))
        assert after["status"] == "COMPUTED", (
            "The rejected finalize leaves the settlement untouched")

    def test_settlement_survives_rejected_finalize(self, api):
        """PRD §3.6: "A computed settlement is published to the carriers by
        `AirportFinance`, moving from `COMPUTED` to `AIRLINE_REVIEW`."
        PRD §3.6: "The `AirportDirector` may finalize a settlement standing
        either `AIRLINE_REVIEW` or `RESOLVED`, and the gate is the same from
        both: no settlement line may remain `PENDING` — every line must stand
        `PAID`, `CREDITED`, or `WRITTEN_OFF`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_settlement_finalize
        """
        ws = setup_computed_settlement("FY_PVS2", [{"iata_code": "PV"}],
                                       [{"iata_code": "PV",
                                         "landed_weight_kg": 1000}])
        sid = ws["settlement"]["id"]

        validate_error(api.finalize_settlement(sid, DIRECTOR),
                       ApiErrorId.ERR_INVALID_STATE)

        # The normal path remains available after the rejected finalize.
        publish_review(ws)
        pay_all_lines(ws)
        finalized = validate_success(api.finalize_settlement(sid, DIRECTOR))
        assert finalized["status"] == "FINALIZED"


class TestFinalizationCascade:
    def test_finalize_closes_parent_fiscal_year(self, api):
        """PRD §3.6: "Finalization sets the settlement to its terminal
        `FINALIZED` status and cascades twice: the parent fiscal year moves
        from `OPEN` to `CLOSED`, and any rate schedule on that year still
        standing `DRAFT` moves to `EXPIRED`."

        Design: Difficulty/transitive_cascade/settlement_finalize_cascade_to_fy_close_and_rates_expire
        """
        ws = setup_settlement_in_review("FY_CAS", [{"iata_code": "CA"}],
                                        [{"iata_code": "CA",
                                          "landed_weight_kg": 1000}])
        pay_all_lines(ws)

        finalized = validate_success(api.finalize_settlement(
            ws["settlement"]["id"], DIRECTOR))
        assert finalized["status"] == "FINALIZED"

        fy = get_success_data(api.get_fiscal_year(ws["fy"]["id"], FINANCE))
        assert fy["status"] == "CLOSED", (
            "The parent fiscal year closes in the same act")

    def test_finalize_expires_draft_rate_schedule(self, api):
        """PRD §3.6: "Finalization sets the settlement to its terminal
        `FINALIZED` status and cascades twice: the parent fiscal year moves
        from `OPEN` to `CLOSED`, and any rate schedule on that year still
        standing `DRAFT` moves to `EXPIRED`."
        PRD §3.2: "If the parent fiscal year closes while a schedule still
        stands `DRAFT`, that schedule transitions automatically to `EXPIRED`."

        Design: Difficulty/transitive_cascade/settlement_finalize_cascade_to_fy_close_and_rates_expire
        """
        ws = setup_settlement_in_review("FY_CAS2", [{"iata_code": "CA"}],
                                        [{"iata_code": "CA",
                                          "landed_weight_kg": 1000}])
        pay_all_lines(ws)
        # A second schedule is drafted on the year and left in DRAFT.
        draft = create_rates_setting(ws["fy"]["id"])

        validate_success(api.finalize_settlement(ws["settlement"]["id"],
                                                 DIRECTOR))

        expired = validate_success(api.get_rates_setting(draft["id"], FINANCE))
        assert expired["status"] == "EXPIRED", (
            "The still-DRAFT schedule expires when the year closes")
        fy = get_success_data(api.get_fiscal_year(ws["fy"]["id"], FINANCE))
        assert fy["status"] == "CLOSED"


class TestFinalizeAndDisputeErrors:
    def test_finalize_with_pending_lines_rejected(self, api):
        """PRD §3.6: "no settlement line may remain `PENDING` — every line must
        stand `PAID`, `CREDITED`, or `WRITTEN_OFF` — else the attempt is
        rejected with `ERR_UNSETTLED_LINES`."

        Design: Corner/errors/error_unsettled_lines_blocks_finalize
        """
        ws = setup_settlement_in_review("FY_UL", [{"iata_code": "UL"}],
                                        [{"iata_code": "UL",
                                          "landed_weight_kg": 1000}])
        lines = list_lines(ws["settlement"]["id"])
        assert all(line["payment_status"] == "PENDING" for line in lines)

        resp = api.finalize_settlement(ws["settlement"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_UNSETTLED_LINES)

    def test_dispute_after_window_rejected(self, api):
        """PRD §3.6: "The first dispute must be raised within forty-five days
        of the publish-review action; a dispute raised after that window is
        refused with `ERR_DISPUTE_WINDOW_EXPIRED`."

        Design: Corner/errors/error_dispute_window_expired
        """
        ws = setup_settlement_in_review("FY_DW", [{"iata_code": "DW"}],
                                        [{"iata_code": "DW",
                                          "landed_weight_kg": 1000}])
        # Publish-review happened with the clock at 2026-09-10; 66 days later
        # the forty-five-day window has run.
        set_clock("2026-11-15T00:00:00Z")

        airline = ws["airlines"]["DW"]
        resp = api.dispute_settlement(
            ws["settlement"]["id"], dispute_payload(airline["id"], "too late"),
            ws["airline_headers"]["DW"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)


class TestClosedYearSealed:
    def test_activity_rejected_after_year_closes(self, api):
        """PRD §3.3: "The fiscal year must still stand `OPEN`; a record filed
        against a `CLOSED` year is rejected with `ERR_FISCAL_YEAR_CLOSED`"
        PRD §2.11: "A fiscal year that has reached `CLOSED` is sealed — every
        write scoped beneath it is refused with `ERR_FISCAL_YEAR_CLOSED`."

        Design: Corner/errors/error_fiscal_year_closed_blocks_activity
        """
        ws = setup_finalized_year("FY_CL", [{"iata_code": "CL"}],
                                  [{"iata_code": "CL", "landed_weight_kg": 1000}])
        fy = get_success_data(api.get_fiscal_year(ws["fy"]["id"], FINANCE))
        assert fy["status"] == "CLOSED"

        resp = api.create_activity_record(
            ws["fy"]["id"],
            {"airline_id": ws["airlines"]["CL"]["id"],
             "activity_date": "2026-09-05T00:00:00Z",
             "landed_weight_kg": 500,
             "signature_status_at_activity": "SIGNATORY"},
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_CLOSED)
