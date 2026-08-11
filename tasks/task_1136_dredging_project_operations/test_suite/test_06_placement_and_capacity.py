"""Placement ticketing, capacity accounting, exact-fill boundary, confirm/void
compensation, and the measurement segregation split (PRD §2.8, §2.9, §2.11,
§3.7).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, CONTRACTOR_ID,
    create_placement_ticket_payload,
    assert_capacity_invariant,
    set_clock, add_site, report_ticket, confirm_ticket, get_site,  # noqa: F401
    setup_dredging_reach, setup_completed_event, setup_second_completed_event,
    setup_confirmed_ticket, open_event,
    make_site_operator_headers,
)


class TestExactFillBoundary:
    def test_disposal_exact_fill_allowed(self, api):
        """PRD §3.7: "the capacity gate must pass — the site's `used_cy` plus
        this `witnessed_volume_cy` must be no more than `capacity_cy`, with
        exact fill allowed — else `ERR_DISPOSAL_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §3.7: "when remaining reaches exactly zero the site flips from
        `OPEN` to `FULL` automatically".

        Design: Difficulty/boundary_precision_check/disposal_exact_fill_boundary
        """
        ctx = setup_completed_event()
        site = add_site(name="SITE-EQ", site_type="UPLAND_CONFINED",
                        capacity_cy=3218, bulking_factor=1.6)
        ticket = report_ticket(ctx["event"]["id"], site["id"],
                               "2026-05-12T12:00:00Z", 3218)
        # 0 + 3218 == 3218: exact fill is allowed.
        confirmed = confirm_ticket(ticket["id"], 3218)
        assert confirmed["status"] == "CONFIRMED"
        site_after = get_site(site["id"])
        assert site_after["used_cy"] == pytest.approx(3218, abs=1e-4)
        assert site_after["remaining_cy"] == pytest.approx(0, abs=1e-4)
        assert site_after["status"] == "FULL"
        assert_capacity_invariant(site_after)

    def test_disposal_one_unit_over_rejected(self, api, site_operator_headers):
        """PRD §3.7: "the capacity gate must pass — the site's `used_cy` plus
        this `witnessed_volume_cy` must be no more than `capacity_cy`, with
        exact fill allowed — else `ERR_DISPOSAL_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/disposal_exact_fill_boundary
        """
        ctx = setup_completed_event()
        site = add_site(name="SITE-UNDER", site_type="UPLAND_CONFINED",
                        capacity_cy=3217, bulking_factor=1.6)
        ticket = report_ticket(ctx["event"]["id"], site["id"],
                               "2026-05-12T12:00:00Z", 3218)
        # 0 + 3218 > 3217: one unit over the capacity is rejected.
        res = api.confirm_placement_ticket(
            ticket["id"], {"witnessed_volume_cy": 3218}, site_operator_headers
        )
        validate_error(res, ApiErrorId.ERR_DISPOSAL_CAPACITY_EXCEEDED,
                       expected_status=409)
        site_after = get_site(site["id"])
        assert site_after["used_cy"] == pytest.approx(0, abs=1e-4)
        assert site_after["status"] == "OPEN"


class TestConfirmCascadeToFull:
    def _site_filled_to_capacity(self):
        """Two completed events; site capacity 3218; first ticket confirmed at
        the exact capacity, flipping the site to FULL."""
        ctx = setup_completed_event()
        ctx = setup_second_completed_event(ctx)
        ctx = setup_confirmed_ticket(
            ctx, event_key="event", placed_utc="2026-05-12T12:00:00Z",
            declared_volume_cy=3218, witnessed_volume_cy=3218,
            site_overrides={"name": "SITE-C", "site_type": "UPLAND_CONFINED",
                            "capacity_cy": 3218, "bulking_factor": 1.6},
        )
        return ctx

    def test_ticket_confirm_debits_capacity_to_full(self, api):
        """PRD §3.7: "The site's `used_cy` increases by the full
        `witnessed_volume_cy` and `remaining_cy` is recomputed as capacity minus
        used; when remaining reaches exactly zero the site flips from `OPEN` to
        `FULL` automatically".

        Design: Difficulty/transitive_cascade/ticket_confirm_cascade_to_site_full
        """
        ctx = self._site_filled_to_capacity()
        site_after = get_site(ctx["site"]["id"])
        # Link 1: capacity debited by the full witnessed volume.
        assert site_after["used_cy"] == pytest.approx(3218, abs=1e-4)
        assert site_after["remaining_cy"] == pytest.approx(0, abs=1e-4)
        # Link 2: the zero remainder flips the site automatically.
        assert site_after["status"] == "FULL"

    def test_full_site_rejects_new_ticket(self, api, contractor_headers):
        """PRD §3.7: "a `FULL` site rejects all further ticket creation with
        `ERR_DISPOSAL_SITE_NOT_OPEN`."

        Design: Difficulty/transitive_cascade/ticket_confirm_cascade_to_site_full
        """
        ctx = self._site_filled_to_capacity()
        # Link 3: the FULL state gates the next placement.
        res = api.create_placement_ticket(
            create_placement_ticket_payload(
                ctx["event2"]["id"], ctx["site"]["id"],
                placed_utc="2026-05-13T09:00:00Z", declared_volume_cy=100,
            ),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_DISPOSAL_SITE_NOT_OPEN,
                       expected_status=409)


class TestConfirmVoidCompensation:
    def _confirm_then_void(self):
        ctx = setup_completed_event()
        ctx = setup_confirmed_ticket(
            ctx, placed_utc="2026-05-12T12:00:00Z", declared_volume_cy=3218,
            witnessed_volume_cy=3218,
            site_overrides={"name": "SITE-INV", "site_type": "UPLAND_CONFINED",
                            "capacity_cy": 3218, "bulking_factor": 1.6},
        )
        return ctx

    def test_confirm_void_restores_capacity_invariant_mid(self, api):
        """PRD §3.7: "The site's `used_cy` increases by the full
        `witnessed_volume_cy` and `remaining_cy` is recomputed as capacity minus
        used; when remaining reaches exactly zero the site flips from `OPEN` to
        `FULL` automatically".

        Design: Difficulty/compensating_invariant/confirm_void_restores_capacity_invariant
        """
        ctx = self._confirm_then_void()
        mid = get_site(ctx["site"]["id"])
        assert mid["used_cy"] == pytest.approx(3218, abs=1e-4)
        assert mid["remaining_cy"] == pytest.approx(0, abs=1e-4)
        assert mid["status"] == "FULL"
        assert_capacity_invariant(mid)

    def test_confirm_void_restores_capacity_invariant_end(self, api,
                                                          site_operator_headers):
        """PRD §3.7: "Voiding compensates a confirmation: a `CONFIRMED` ticket
        moves to `VOIDED`, the site's `used_cy` decreases by the ticket's
        `witnessed_volume_cy`, `remaining_cy` is recomputed, and if the site was
        `FULL` and remaining is again above zero it reopens from `FULL` to
        `OPEN`. Confirm and void together leave the capacity invariant — used
        plus remaining equals capacity — unchanged net."

        Design: Difficulty/compensating_invariant/confirm_void_restores_capacity_invariant
        """
        ctx = self._confirm_then_void()
        res = api.void_placement_ticket(ctx["ticket"]["id"],
                                        site_operator_headers)
        voided = validate_success(res, 200)
        assert voided["status"] == "VOIDED"
        end = get_site(ctx["site"]["id"])
        assert end["used_cy"] == pytest.approx(0, abs=1e-4)
        assert end["remaining_cy"] == pytest.approx(3218, abs=1e-4)
        assert end["status"] == "OPEN"
        assert_capacity_invariant(end)


class TestConfirmCheckOrdering:
    def _ticket_out_of_window_and_over_capacity(self):
        """Ticket placed outside every ISSUED permit window whose witnessed
        volume also exceeds the site's entire capacity."""
        ctx = setup_completed_event()
        site = add_site(name="SITE-S", site_type="UPLAND_CONFINED",
                        capacity_cy=1000, bulking_factor=1.3)
        ticket = report_ticket(ctx["event"]["id"], site["id"],
                               "2026-09-15T09:00:00Z", 2000)
        return ctx, site, ticket

    def test_temporal_beats_capacity_on_ticket_confirm(self, api,
                                                       site_operator_headers):
        """PRD §3.7: "The checks fire in the order of §2.9: ... the ticket's
        `placed_utc` must fall inside an `ISSUED` permit's closed window of the
        event's project at confirm time, else `ERR_PLACEMENT_OUT_OF_WINDOW`
        (HTTP 409); and the capacity gate must pass ... else
        `ERR_DISPOSAL_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §2.9: "the first failing class produces the response — earlier
        failures mask later ones rather than accumulating" (class 9 temporal
        precedes class 10 capacity).

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_ticket_confirm
        """
        ctx, site, ticket = self._ticket_out_of_window_and_over_capacity()
        res = api.confirm_placement_ticket(
            ticket["id"], {"witnessed_volume_cy": 2000}, site_operator_headers
        )
        validate_error(res, ApiErrorId.ERR_PLACEMENT_OUT_OF_WINDOW,
                       expected_status=409)

    def test_rejected_confirm_leaves_capacity_untouched(self, api,
                                                        site_operator_headers,
                                                        owner_headers):
        """PRD §3.7: "the ticket's `placed_utc` must fall inside an `ISSUED`
        permit's closed window of the event's project at confirm time, else
        `ERR_PLACEMENT_OUT_OF_WINDOW` (HTTP 409)"; PRD §3.7: "Only `CONFIRMED`
        tickets that have not been voided count toward `used_cy`; `REPORTED`
        and `REJECTED` tickets never debit."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_ticket_confirm
        """
        ctx, site, ticket = self._ticket_out_of_window_and_over_capacity()
        res = api.confirm_placement_ticket(
            ticket["id"], {"witnessed_volume_cy": 2000}, site_operator_headers
        )
        validate_error(res, ApiErrorId.ERR_PLACEMENT_OUT_OF_WINDOW,
                       expected_status=409)
        site_after = get_site(site["id"])
        assert site_after["used_cy"] == pytest.approx(0, abs=1e-4)
        ticket_after = validate_success(
            api.get_placement_ticket(ticket["id"], owner_headers)
        )
        assert ticket_after["status"] == "REPORTED"


class TestTicketCreationGates:
    def test_ticket_create_on_active_event_rejected(self, api,
                                                    contractor_headers):
        """PRD §3.7: "The referenced event must be `COMPLETED`, else
        `ERR_EVENT_NOT_COMPLETED` (HTTP 409)".

        Design: Corner/validations/ticket_create_on_active_event_rejected
        """
        ctx = setup_dredging_reach()
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        site = add_site(name="SITE-T", bulking_factor=1.3)
        res = api.create_placement_ticket(
            create_placement_ticket_payload(event["id"], site["id"],
                                            placed_utc="2026-05-10T12:00:00Z",
                                            declared_volume_cy=500),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_EVENT_NOT_COMPLETED,
                       expected_status=409)

    def test_segregation_ticket_confirmer_is_reporter_rejected(
        self, api, owner_headers
    ):
        """PRD §2.8: "Placement-ticket confirmation and rejection compare
        against the ticket's `reported_by_user_id`." — an exact match "is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/endpoints/segregation_ticket_confirmer_is_reporter_rejected
        """
        ctx = setup_completed_event()
        site = add_site(name="SITE-S", capacity_cy=5000, bulking_factor=1.3)
        ticket = report_ticket(ctx["event"]["id"], site["id"],
                               "2026-05-12T12:00:00Z", 500)
        # SiteOperator role carrying the reporter's id (ops-1).
        res = api.confirm_placement_ticket(
            ticket["id"], {"witnessed_volume_cy": 500},
            make_site_operator_headers(CONTRACTOR_ID),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        site_after = get_site(site["id"])
        assert site_after["used_cy"] == pytest.approx(0, abs=1e-4)
        ticket_after = validate_success(
            api.get_placement_ticket(ticket["id"], owner_headers)
        )
        assert ticket_after["status"] == "REPORTED"


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api, owner_headers):
        """PRD §3.7: "The ticket's `in_situ_volume_cy` is computed as
        `witnessed_volume_cy` divided by the site's `bulking_factor`, rounded
        half up to 2 decimal places — per ticket, at confirm time, before any
        summation".
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.7: "The site's `used_cy` increases by the full
        `witnessed_volume_cy` and `remaining_cy` is recomputed as capacity minus
        used".

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        ctx = setup_completed_event()
        site = add_site(name="SITE-I", capacity_cy=5000, bulking_factor=1.3)
        ticket = report_ticket(ctx["event"]["id"], site["id"],
                               "2026-05-12T12:00:00Z", 1609)
        confirmed = confirm_ticket(ticket["id"], 1609)
        # Confirm response itself carries the per-ticket rounded conversion.
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["in_situ_volume_cy"] == pytest.approx(1237.69,
                                                               abs=1e-4)
        # A follow-up read in the same flow already shows the debit.
        site_after = get_site(site["id"])
        assert site_after["used_cy"] == pytest.approx(1609, abs=1e-4)
        assert site_after["remaining_cy"] == pytest.approx(3391, abs=1e-4)
        assert_capacity_invariant(site_after)
