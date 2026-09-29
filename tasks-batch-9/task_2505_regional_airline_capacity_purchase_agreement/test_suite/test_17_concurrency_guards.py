"""The two optimistic-concurrency guards, each proved inert and then satisfied.

One guard sits on the agreement and one on the settlement month. Each test sends the
same body twice — once with a version one behind the observed value and once with the
observed value — so the refusal and the success differ in exactly one integer.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_STALE_AGREEMENT_VERSION,
    ERR_STALE_CYCLE_VERSION,
)
from test_helpers.assertions import assert_money, assert_status
from test_helpers.factories import (
    make_agreement_payload,
    make_extension_offer_payload,
    make_invoice_payload,
)
from test_helpers.fixtures import (
    build_active_agreement,
    create_cycle,
    cycle_version,
    open_cycle,
    read_agreement,
    read_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, SCHEDULER_HEADERS


class TestAgreementVersionGuardOnExtensionOffers:
    """A term sheet opened against a superseded contract view is refused outright."""

    def test_an_offer_one_version_behind_is_refused_and_the_current_one_is_accepted(self, api):
        """The refused offer moves no counter; the accepted one moves three.

        PRD 2.9: "Opening an extension round against an agreement requires the request to
        carry `expected_agreement_version`, holding the `version` the client last read from
        that agreement."

        PRD 2.9: "If it does not equal the agreement's current `version`, the request is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        PRD 3.9: "It creates a negotiation in `OFFERED` status, with `counter_term_end_date`
        and `counter_block_hour_rate_usd` null, `counter_round` at 0, and `round_index`
        recording which round of bargaining this is — the agreement's `extension_round_count`
        after this offer has been counted."

        Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_extension_offer_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(term_end_date="2029-12-31"),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        observed = read_agreement(api, scenario.agreement_id)
        observed_version = observed["version"]

        validate_error(
            api.create_extension_negotiation(
                scenario.agreement_id,
                make_extension_offer_payload(
                    observed_version - 1,
                    proposed_term_end_date="2031-12-31",
                    proposed_block_hour_rate_usd=1500.00,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            ERR_STALE_AGREEMENT_VERSION,
            412,
        )

        unmoved = read_agreement(api, scenario.agreement_id)
        assert_status(unmoved, "ACTIVE")
        assert unmoved["extension_round_count"] == 0
        assert unmoved["version"] == observed_version, "a refused write mutates nothing"

        offer = validate_success(
            api.create_extension_negotiation(
                scenario.agreement_id,
                make_extension_offer_payload(
                    observed_version,
                    proposed_term_end_date="2031-12-31",
                    proposed_block_hour_rate_usd=1500.00,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            201,
        )
        assert_status(offer, "OFFERED")
        assert offer["round_index"] == 1

        renegotiating = read_agreement(api, scenario.agreement_id)
        assert_status(renegotiating, "EXTENSION_PENDING")
        assert renegotiating["extension_round_count"] == 1
        assert renegotiating["version"] == observed_version + 1


class TestCycleVersionGuardOnInvoiceCreation:
    """The month's guard carries its own field name and its own rejection code."""

    def test_an_invoice_one_version_behind_the_month_is_refused_and_bills_nothing(self, api):
        """The refused bill leaves no draft anywhere; the accepted one prices the month.

        PRD 2.9: "Creating an invoice against a settlement month requires the request to carry
        `expected_schedule_cycle_version`, holding the `version` the client last read from that
        cycle."

        PRD 2.9: "This field is likewise not optional, and a mismatch with the cycle's current
        `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

        PRD 3.8: "`fixed_component_usd` is the agreement's `fixed_monthly_fee_usd` plus the
        product of `aircraft_ownership_fee_usd` and `ownership_aircraft_count`, that product
        rounded half-up to two decimals before being added."

        PRD 3.8: "`total_usd` is then the fixed component plus the variable component plus the
        pass-through component plus the incentive component, less the penalty component and
        less the brand penalty component."

        Design: Corner/cross_cutting_complexity_layers/stale_cycle_version_on_invoice_creation_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=0
        )
        cycle = open_cycle(api, cycle["id"])
        observed_version = cycle_version(api, cycle["id"])

        validate_error(
            api.create_invoice(
                cycle["id"],
                make_invoice_payload("PROVISIONAL", observed_version - 1),
                headers=ADMIN_HEADERS,
            ),
            ERR_STALE_CYCLE_VERSION,
            412,
        )

        drafts, meta = validate_paginated(
            api.list_invoices(headers=ADMIN_HEADERS, params={"cycle_id": cycle["id"]})
        )
        assert drafts == []
        assert meta["total_count"] == 0
        assert read_agreement(api, scenario.agreement_id)["open_invoice_count"] == 0
        assert read_cycle(api, cycle["id"])["version"] == observed_version

        invoice = validate_success(
            api.create_invoice(
                cycle["id"],
                make_invoice_payload("PROVISIONAL", observed_version),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert_status(invoice, "DRAFT")
        assert invoice["variant"] == "PROVISIONAL"
        assert_money(invoice["fixed_component_usd"], 250000.00, "the flat monthly capacity fee")
        assert_money(invoice["variable_component_usd"], 0.00, "no flying was published")
        assert_money(invoice["passthrough_component_usd"], 0.00, "no cost category was opened")
        assert_money(invoice["total_usd"], 250000.00, "the provisional total")

        assert read_cycle(api, cycle["id"])["version"] == observed_version + 1
        assert read_agreement(api, scenario.agreement_id)["open_invoice_count"] == 1
