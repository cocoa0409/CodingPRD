"""Tour retirement gates, terminal lockdown, and the retirement cascade
(PRD §3.3, §3.9)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    create_and_sign_contract,
    create_contract_payload,
    create_marketing_kit_payload,
    issue_certificate,
)

TM = TEST_USERS["tour_manager_headers"]


class TestRetireGates:
    def test_retire_with_contracted_stop_rejected(self, api):
        """PRD §3.9: "Regardless of posture, retirement is refused with
        `ERR_TOUR_NOT_RETIREABLE` while any stop remains in `CONTRACTED`,
        `INSTALLING`, `OPEN`, or `TEARDOWN`, or while any damage claim is still
        open in `FILED`, `UNDER_REVIEW`, or `APPROVED`."

        Design: Corner/validations/tour_not_retireable_with_active_stop
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Print Hall")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        create_and_sign_contract(
            tour["id"], stop["id"], base_fee_cents=100000, sponsorship_credit_cents=0
        )
        # Stop is CONTRACTED after SIGN.
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "CONTRACTED"
        res = api.transition_tour(tour["id"], {"action": "RETIRE"}, TM)
        validate_error(res, ApiErrorId.ERR_TOUR_NOT_RETIREABLE)

    def test_retire_with_only_tentative_stops_succeeds(self, api):
        """PRD §3.9: "Retirement is the tour's deliberate end — a `TourManager`
        transition (`action` `RETIRE`) available from `BOOKING`, `ON_TOUR`, or
        `IN_REFURBISHMENT`, landing in the terminal `RETIRED`."
        PRD §3.9: "from `BOOKING`, no stop may sit in `CONTRACTED`,
        `INSTALLING`, `OPEN`, or `TEARDOWN`".

        Design: Corner/validations/tour_not_retireable_with_active_stop
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Print Hall")
        book_stop(tour["id"], venue["id"], projected_attendance=100)
        res = api.transition_tour(tour["id"], {"action": "RETIRE"}, TM)
        retired = validate_success(res, 200)
        assert retired["status"] == "RETIRED"


class TestRetiredTourTerminal:
    def test_open_booking_on_retired_tour_rejected(self, api):
        """PRD §3.9: "Retirement is the tour's deliberate end — a `TourManager`
        transition (`action` `RETIRE`) available from `BOOKING`, `ON_TOUR`, or
        `IN_REFURBISHMENT`, landing in the terminal `RETIRED`."
        PRD §2.8: "then transition state validity — a transition attempted from a
        state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/retired_tour_is_terminal_for_transitions
        """
        tour, _ = create_and_open_booking()
        validate_success(api.transition_tour(tour["id"], {"action": "RETIRE"}, TM), 200)
        res = api.transition_tour(tour["id"], {"action": "OPEN_BOOKING"}, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_double_retire_rejected(self, api):
        """PRD §3.9: "landing in the terminal `RETIRED`."
        PRD §2.8: "then transition state validity — a transition attempted from a
        state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/retired_tour_is_terminal_for_transitions
        """
        tour, _ = create_and_open_booking()
        validate_success(api.transition_tour(tour["id"], {"action": "RETIRE"}, TM), 200)
        res = api.transition_tour(tour["id"], {"action": "RETIRE"}, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestRetirementCascade:
    def _setup_cascade_scenario(self, api):
        """Tour BOOKING with TENTATIVE stop, DRAFT contract, PLANNED kit, ISSUED cert."""
        tour, _ = create_and_open_booking(
            title="Posters",
            exhibit_code="POST-2026",
            declared_value_cents=500000,
            refurbishment_gap_days=2,
        )
        venue = create_venue(
            name="Poster House", city="NYC", max_gallery_sqm=500,
            local_sponsorship_cap_cents=50000,
        )
        stop = book_stop(
            tour["id"],
            venue["id"],
            install_start="2026-09-01T00:00:00Z",
            open_date="2026-09-04T00:00:00Z",
            close_date="2026-10-04T00:00:00Z",
            teardown_end="2026-10-07T00:00:00Z",
            projected_attendance=2000,
        )
        contract = get_success_data(
            api.create_contract(
                tour["id"],
                stop["id"],
                create_contract_payload(
                    base_fee_cents=300000, sponsorship_credit_cents=0
                ),
                TM,
            )
        )
        kit = get_success_data(
            api.create_marketing_kit(
                tour["id"],
                stop["id"],
                create_marketing_kit_payload(language_count=2, sponsor_logo_slots=1),
                TM,
            )
        )
        cert = issue_certificate(
            tour["id"],
            stop["id"],
            500000,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-11-01T00:00:00Z",
        )
        return tour, stop, contract, kit, cert

    def test_retire_cascades_stop_and_contract(self, api):
        """PRD §3.9: "Every `TENTATIVE` stop is cancelled."
        PRD §3.3: "cancelling a `TENTATIVE` stop finalizes any non-finalized
        contract on it with `final_fee_cents` of zero — no fee is due on a stop
        that never contracted".

        Design: Difficulty/transitive_cascade/tour_retire_cascades_stop_contract_marketing_certificate
        """
        tour, stop, contract, kit, cert = self._setup_cascade_scenario(api)
        res = api.transition_tour(tour["id"], {"action": "RETIRE"}, TM)
        retired = validate_success(res, 200)
        assert retired["status"] == "RETIRED"
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "CANCELLED"
        contracts = validate_success(api.get_contract(tour["id"], stop["id"], TM), 200)
        finalized = [c for c in contracts if c["id"] == contract["id"]][0]
        assert finalized["status"] == "FINALIZED"
        assert finalized["final_fee_cents"] == 0

    def test_retire_cascades_marketing_kit_and_certificate(self, api):
        """PRD §3.9: "Every marketing kit still `PLANNED` or `PRODUCED` is
        retired. Every certificate still `ISSUED` or `ACTIVE` is voided."

        Design: Difficulty/transitive_cascade/tour_retire_cascades_stop_contract_marketing_certificate
        """
        tour, stop, contract, kit, cert = self._setup_cascade_scenario(api)
        validate_success(api.transition_tour(tour["id"], {"action": "RETIRE"}, TM), 200)
        kits = validate_success(api.get_marketing_kit(tour["id"], stop["id"], TM), 200)
        target_kit = [k for k in kits if k["id"] == kit["id"]][0]
        assert target_kit["status"] == "RETIRED"
        cert_after = validate_success(
            api.get_certificate(tour["id"], cert["id"], TM), 200
        )
        assert cert_after["status"] == "VOID"
