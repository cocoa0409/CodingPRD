"""Agreement creation, the offer ladder, its ceilings and stale-view protection."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DUPLICATE_AGREEMENT_LABEL,
    ERR_DUPLICATE_FILING_DOCKET,
    ERR_NEGOTIATION_ROUND_LIMIT,
    ERR_OFFER_PARTY_SEQUENCE,
    ERR_RECIPROCAL_RATE_CAP_EXCEEDED,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_STALE_CARRIER_VERSION,
)
from test_helpers.assertions import (
    assert_immutable_entity,
    assert_rate,
    assert_versioned_entity,
)
from test_helpers.constants import (
    AGREEMENT_LABEL,
    BENCHMARK_INTERSTATE_RATE,
    DOCKET_LOCAL,
    POI_CAPACITY_TRUNKS,
    RECIPROCAL_RATE,
    T_2026_08_01,
    TERM_MONTHS,
)
from test_helpers.factories import (
    agreement_payload,
    counter_offer_payload,
    factor_filing_payload,
    proposal_offer_payload,
    tariff_filing_payload,
)
from test_helpers.fixtures import (
    append_counter,
    append_proposal,
    read_agreement,
    read_carrier,
    read_factor_filing,
    setup_carrier,
    setup_draft_agreement,
    setup_factor_filing,
    setup_proposed_agreement,
)


def test_agreement_retrieval_returns_the_stored_opening_ask(api, manager_headers):
    """A DRAFT agreement reads back its opening ask with every pinned term still null.

    PRD 3.1: "The new agreement lands in `DRAFT` with `negotiation_round` at 0 and `capacity_posture` at `NORMAL`."
    PRD 3.1: "Its `reciprocal_rate_per_mou_usd`, `term_months`, `poi_financial_responsibility`, `executed_at` and `terminated_at` are all null at this point, and `total_in_service_trunks` and `poi_augment_pending_count` are both 0."

    Design: Corner/entities/agreement_retrieval_returns_the_stored_opening_ask
    """
    state = setup_draft_agreement(api)

    response = api.get_agreement(state["agreement_id"], manager_headers)
    agreement = validate_success(response, expected_status=200)

    assert agreement["id"] == state["agreement_id"]
    assert agreement["carrier_id"] == state["carrier_id"]
    assert agreement["agreement_label"] == AGREEMENT_LABEL
    assert agreement["status"] == "DRAFT"
    assert agreement["negotiation_round"] == 0
    assert_rate(
        agreement["proposed_reciprocal_rate_per_mou_usd"],
        RECIPROCAL_RATE,
        "proposed_reciprocal_rate_per_mou_usd",
    )
    assert agreement["proposed_term_months"] == TERM_MONTHS
    assert agreement["reciprocal_rate_per_mou_usd"] is None
    assert agreement["term_months"] is None
    assert agreement["poi_financial_responsibility"] is None
    assert agreement["executed_at"] is None
    assert agreement["poi_facility_capacity_trunks"] == POI_CAPACITY_TRUNKS
    assert agreement["capacity_posture"] == "NORMAL"
    assert agreement["poi_augment_pending_count"] == 0
    assert agreement["total_in_service_trunks"] == 0


def test_agreement_transit_flag_defaults_to_false_when_omitted(api, manager_headers):
    """An omitted transit_traffic_allowed resolves to false, never to null.

    PRD 3.1: "An `InterconnectionManager` opens a negotiation by creating an interconnection agreement against a `carrier_id`, giving it an `agreement_label` (the docket label under which the negotiation is tracked, non-empty and unique among that carrier's agreements — a repeat is refused with `ERR_DUPLICATE_AGREEMENT_LABEL`), an opening ask consisting of `proposed_reciprocal_rate_per_mou_usd` at six decimal places and greater than zero and `proposed_term_months` between 12 and 60 inclusive, an optional `transit_traffic_allowed` flag defaulting to false, a requested commercial `effective_date`, and a `poi_facility_capacity_trunks` ceiling that must be at least 24 and an exact multiple of 24."
    PRD 3.1: "The new agreement lands in `DRAFT` with `negotiation_round` at 0 and `capacity_posture` at `NORMAL`."

    Design: Corner/entities/agreement_transit_flag_defaults_to_false_when_omitted
    """
    carrier = setup_carrier(api)
    payload = agreement_payload(carrier["id"])
    payload.pop("transit_traffic_allowed")

    response = api.create_agreement(payload, manager_headers)
    agreement = validate_success(response, expected_status=201)

    assert agreement["transit_traffic_allowed"] is False, (
        f"the omitted flag must default to false, got {agreement['transit_traffic_allowed']!r}"
    )
    assert agreement["status"] == "DRAFT"
    assert agreement["negotiation_round"] == 0
    assert agreement["capacity_posture"] == "NORMAL"
    assert_versioned_entity(agreement, expected_version=1, label="agreement")


def test_negotiation_offer_is_immutable_and_carries_no_version_field(
    api, manager_headers
):
    """A negotiation offer reads back with id and created_at but no version or updated_at.

    PRD 2.4: "Four record types are deliberately immutable-shaped ledger rows and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them entirely: negotiation offers, traffic measurements, call detail records and reserve ledger entries."
    PRD 3.1: "Each offer is born in status `OPEN` with `responded_at` null; only one offer per agreement is `OPEN` at a time, and that one is the **standing offer**."
    PRD 3.1: "The server derives the offer's `offering_party` from the acting role — `CLEC_SIDE` when an `InterconnectionManager` submits it, `COUNTERPARTY_SIDE` when a `CarrierRepresentative` does — and stamps `round_number` as the agreement's `negotiation_round` after the append, one-based."

    Design: Corner/entities/negotiation_offer_is_immutable_and_carries_no_version_field
    """
    state = setup_proposed_agreement(api)
    offer_id = state["offers"][0]["id"]

    response = api.get_offer(offer_id, manager_headers)
    offer = validate_success(response, expected_status=200)

    assert_immutable_entity(offer, label="negotiation offer")
    assert offer["round_number"] == 1
    assert offer["offering_party"] == "CLEC_SIDE"
    assert offer["status"] == "OPEN"
    assert offer["responded_at"] is None
    assert offer["agreement_id"] == state["agreement_id"]
    assert_rate(
        offer["reciprocal_rate_per_mou_usd"],
        RECIPROCAL_RATE,
        "reciprocal_rate_per_mou_usd",
    )


def test_duplicate_agreement_label_and_duplicate_filing_docket_are_refused(
    api, manager_headers, regulator_headers
):
    """A repeat agreement label and a repeat filing docket each report their own conflict.

    PRD 3.1: "An `InterconnectionManager` opens a negotiation by creating an interconnection agreement against a `carrier_id`, giving it an `agreement_label` (the docket label under which the negotiation is tracked, non-empty and unique among that carrier's agreements — a repeat is refused with `ERR_DUPLICATE_AGREEMENT_LABEL`), an opening ask consisting of `proposed_reciprocal_rate_per_mou_usd` at six decimal places and greater than zero and `proposed_term_months` between 12 and 60 inclusive, an optional `transit_traffic_allowed` flag defaulting to false, a requested commercial `effective_date`, and a `poi_facility_capacity_trunks` ceiling that must be at least 24 and an exact multiple of 24."
    PRD 3.5: "A filing names a `filing_docket` — the regulatory docket number, non-empty and globally unique, with a repeat refused as `ERR_DUPLICATE_FILING_DOCKET` — a `rate_element` drawn from `INTERSTATE_SWITCHED_ACCESS`, `INTRASTATE_SWITCHED_ACCESS` and `LOCAL_RECIPROCAL_COMP`, the `rate_per_mou_usd` it sets at six decimals and greater than zero, the carrier's own `benchmark_interstate_rate_per_mou_usd` at six decimals and greater than zero, and the `effective_date` and `expiry_date` bounding the rate's window."

    Design: Corner/errors/duplicate_agreement_label_and_duplicate_filing_docket_are_refused
    """
    state = setup_draft_agreement(api)

    duplicate_label = api.create_agreement(
        agreement_payload(
            state["carrier_id"],
            proposed_reciprocal_rate_per_mou_usd=0.055,
            proposed_term_months=24,
            poi_facility_capacity_trunks=96,
        ),
        manager_headers,
    )
    validate_error(duplicate_label, ERR_DUPLICATE_AGREEMENT_LABEL, expected_status=409)

    duplicate_docket = api.create_tariff_filing(
        tariff_filing_payload(
            filing_docket=DOCKET_LOCAL,
            rate_element="LOCAL_RECIPROCAL_COMP",
            rate_per_mou_usd=0.07,
            benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            effective_date="2027-01-01T00:00:00.000Z",
            expiry_date="2027-07-01T00:00:00.000Z",
        ),
        regulator_headers,
    )
    validate_error(duplicate_docket, ERR_DUPLICATE_FILING_DOCKET, expected_status=409)

    _, agreements_meta = validate_paginated(
        api.list_carrier_agreements(state["carrier_id"], manager_headers)
    )
    assert agreements_meta["total_count"] == 1
    _, filings_meta = validate_paginated(api.list_tariff_filings(regulator_headers))
    assert filings_meta["total_count"] == 1


def test_offer_above_the_reciprocal_cap_and_a_counter_opening_round_are_refused(
    api, manager_headers
):
    """An over-cap opening ask and an opening COUNTER each report their own refusal.

    PRD 3.1: "And the reciprocal compensation rate offered in any round may not exceed **one tenth of a dollar per minute of use** — a rate above 0.100000 is refused with `ERR_RECIPROCAL_RATE_CAP_EXCEEDED`."
    PRD 3.1: "That first offer must have `offer_type` `PROPOSAL` and must come from the CLEC side; a first offer typed `COUNTER` is refused with `ERR_OFFER_PARTY_SEQUENCE`."
    PRD 3.1: "Every append does four things. The standing `OPEN` offer, if one exists, moves `OPEN → SUPERSEDED` with its `responded_at` stamped from the logical clock; the new offer row is appended in `OPEN`; the agreement's `negotiation_round` increments by 1; and the agreement's `version` increments by 1."

    Design: Corner/errors/offer_above_the_reciprocal_cap_and_a_counter_opening_round_are_refused
    """
    state = setup_draft_agreement(api)
    assert state["agreement"]["version"] == 1

    over_cap = api.append_offer(
        state["agreement_id"],
        proposal_offer_payload(1, reciprocal_rate_per_mou_usd=0.15),
        manager_headers,
    )
    validate_error(over_cap, ERR_RECIPROCAL_RATE_CAP_EXCEEDED, expected_status=422)

    opening_counter = api.append_offer(
        state["agreement_id"],
        counter_offer_payload(
            1,
            reciprocal_rate_per_mou_usd=RECIPROCAL_RATE,
            term_months=TERM_MONTHS,
            poi_financial_responsibility="SHARED",
        ),
        state["rep_headers"],
    )
    validate_error(opening_counter, ERR_OFFER_PARTY_SEQUENCE, expected_status=409)

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["version"] == 1, "a refused append must not bump the OCC parent"
    assert agreement["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_agreement_offers(state["agreement_id"], manager_headers)
    )
    assert meta["total_count"] == 0


def test_seventh_negotiation_round_exceeds_the_round_limit(api, manager_headers):
    """After six exchanged offers a seventh append is refused by the round ceiling.

    PRD 3.1: "Rounds are capped at **six**: the round number the append would create, which is the agreement's current `negotiation_round` plus one, must be no greater than six, and an append that would exceed it is refused with `ERR_NEGOTIATION_ROUND_LIMIT`."
    PRD 3.1: "Each offer is born in status `OPEN` with `responded_at` null; only one offer per agreement is `OPEN` at a time, and that one is the **standing offer**."
    PRD 2.7: "A regulatory cap breach surfaces as its own code rather than being masked by a later capacity or fiscal check, and a state conflict always beats a business-rule breach on the same request — a dispute in the wrong status is reported as an invalid dispute state, not as a credit-amount problem."

    Design: Corner/errors/seventh_negotiation_round_exceeds_the_round_limit
    """
    state = setup_draft_agreement(api)
    append_proposal(api, state)
    append_counter(
        api, state, from_counterparty=True, reciprocal_rate_per_mou_usd=0.058, term_months=24
    )
    append_counter(
        api, state, from_counterparty=False, reciprocal_rate_per_mou_usd=0.06, term_months=30
    )
    append_counter(
        api, state, from_counterparty=True, reciprocal_rate_per_mou_usd=0.057, term_months=24
    )
    append_counter(
        api, state, from_counterparty=False, reciprocal_rate_per_mou_usd=0.059, term_months=36
    )
    append_counter(
        api, state, from_counterparty=True, reciprocal_rate_per_mou_usd=0.056, term_months=24
    )

    standing = read_agreement(api, state["agreement_id"])
    assert standing["negotiation_round"] == 6
    assert standing["status"] == "COUNTERED"

    response = api.append_offer(
        state["agreement_id"],
        counter_offer_payload(
            standing["version"],
            reciprocal_rate_per_mou_usd=0.0585,
            term_months=36,
            poi_financial_responsibility="SHARED",
        ),
        manager_headers,
    )
    validate_error(response, ERR_NEGOTIATION_ROUND_LIMIT, expected_status=409)

    offers, meta = validate_paginated(
        api.list_agreement_offers(state["agreement_id"], manager_headers)
    )
    assert meta["total_count"] == 6, "the refused append must not persist an offer"
    assert [offer["status"] for offer in offers].count("OPEN") == 1
    assert [offer["status"] for offer in offers].count("SUPERSEDED") == 5
    assert [offer["round_number"] for offer in offers] == [1, 2, 3, 4, 5, 6]
    assert [offer["offering_party"] for offer in offers] == [
        "CLEC_SIDE",
        "COUNTERPARTY_SIDE",
        "CLEC_SIDE",
        "COUNTERPARTY_SIDE",
        "CLEC_SIDE",
        "COUNTERPARTY_SIDE",
    ]

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["negotiation_round"] == 6
    assert agreement["version"] == 7
    assert agreement["status"] == "COUNTERED"


def test_offer_quoting_a_superseded_agreement_version_is_rejected(api, manager_headers):
    """A counter quoting the pre-append version is refused and changes nothing.

    PRD 2.6: "The offer-append request must therefore include `expected_agreement_version` as a required, non-optional field carrying the `version` of the `InterconnectionAgreement` the client last observed."
    PRD 2.6: "If that value does not equal the agreement's current `version`, the append is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), forcing the writer to re-read the agreement and its standing offer before trying again."

    Design: Corner/cross_cutting_complexity_layers/offer_quoting_a_superseded_agreement_version_is_rejected
    """
    state = setup_proposed_agreement(api)
    first_offer_id = state["offers"][0]["id"]
    assert state["agreement"]["version"] == 2

    response = api.append_offer(
        state["agreement_id"],
        counter_offer_payload(
            1,
            reciprocal_rate_per_mou_usd=0.058,
            term_months=24,
            poi_financial_responsibility="TERMINATOR_PAYS",
        ),
        state["rep_headers"],
    )
    validate_error(response, ERR_STALE_AGREEMENT_VERSION, expected_status=412)

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["version"] == 2
    assert agreement["negotiation_round"] == 1
    assert agreement["status"] == "PROPOSED"

    standing = validate_success(api.get_offer(first_offer_id, manager_headers))
    assert standing["status"] == "OPEN"
    assert standing["responded_at"] is None

    _, meta = validate_paginated(
        api.list_agreement_offers(state["agreement_id"], manager_headers)
    )
    assert meta["total_count"] == 1


def test_offer_quoting_the_re_read_agreement_version_succeeds_and_bumps_it(
    api, manager_headers
):
    """A counter quoting the re-read version supersedes the standing offer and counters.

    PRD 2.6: "The offer-append request must therefore include `expected_agreement_version` as a required, non-optional field carrying the `version` of the `InterconnectionAgreement` the client last observed."
    PRD 3.1: "Every append does four things. The standing `OPEN` offer, if one exists, moves `OPEN → SUPERSEDED` with its `responded_at` stamped from the logical clock; the new offer row is appended in `OPEN`; the agreement's `negotiation_round` increments by 1; and the agreement's `version` increments by 1."
    PRD 3.1: "A counter from the counterparty against a standing `CLEC_SIDE` offer moves the agreement `PROPOSED → COUNTERED`; a counter from the CLEC against a standing `COUNTERPARTY_SIDE` offer moves it `COUNTERED → PROPOSED`."

    Design: Corner/cross_cutting_complexity_layers/offer_quoting_the_re_read_agreement_version_succeeds_and_bumps_it
    """
    state = setup_proposed_agreement(api)
    first_offer_id = state["offers"][0]["id"]
    observed = read_agreement(api, state["agreement_id"])
    assert observed["version"] == 2

    response = api.append_offer(
        state["agreement_id"],
        counter_offer_payload(
            observed["version"],
            reciprocal_rate_per_mou_usd=0.058,
            term_months=24,
            poi_financial_responsibility="TERMINATOR_PAYS",
        ),
        state["rep_headers"],
    )
    counter = validate_success(response, expected_status=201)

    assert counter["status"] == "OPEN"
    assert counter["offering_party"] == "COUNTERPARTY_SIDE"
    assert counter["round_number"] == 2

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["version"] == 3
    assert agreement["negotiation_round"] == 2
    assert agreement["status"] == "COUNTERED", "a counter must not execute the agreement"

    superseded = validate_success(api.get_offer(first_offer_id, manager_headers))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["responded_at"] == T_2026_08_01


def test_factor_filing_quoting_a_superseded_carrier_version_is_rejected(
    api, analyst_headers
):
    """A second quarter's factors quoting the pre-filing carrier version are refused.

    PRD 2.6: "The second is **creating a quarterly traffic factor filing for a carrier**."
    PRD 2.6: "A mismatch with the carrier's current `version` is rejected with `ERR_STALE_CARRIER_VERSION` (HTTP 412)."
    PRD 3.6: "Creating a filing also increments the carrier's `version` by 1, and — as covered in §2.6 — requires `expected_carrier_version` to match the carrier's current `version`."

    Design: Corner/cross_cutting_complexity_layers/factor_filing_quoting_a_superseded_carrier_version_is_rejected
    """
    carrier = setup_carrier(api)
    assert carrier["version"] == 1
    first = setup_factor_filing(api, carrier)
    assert read_carrier(api, carrier["id"])["version"] == 2

    response = api.create_factor_filing(
        factor_filing_payload(
            carrier["id"],
            1,
            quarter="2026Q4",
            reported_piu_pct=45.00,
            reported_plu_pct=15.00,
        ),
        analyst_headers,
    )
    validate_error(response, ERR_STALE_CARRIER_VERSION, expected_status=412)

    assert read_carrier(api, carrier["id"])["version"] == 2

    rows, meta = validate_paginated(
        api.list_carrier_factor_filings(carrier["id"], analyst_headers)
    )
    assert meta["total_count"] == 1
    assert [row["quarter"] for row in rows] == ["2026Q3"]

    unchanged = read_factor_filing(api, first["id"])
    assert unchanged["status"] == "REPORTED"
    assert float(unchanged["effective_piu_pct"]) == 50.00


def test_agreement_negotiation_reoccupies_proposed_after_a_counter(api, manager_headers):
    """The agreement visits PROPOSED twice: DRAFT, PROPOSED, COUNTERED, PROPOSED, EXECUTED.

    PRD 3.1: "Appending the first offer to a `DRAFT` agreement moves it `DRAFT → PROPOSED`."
    PRD 3.1: "A counter from the counterparty against a standing `CLEC_SIDE` offer moves the agreement `PROPOSED → COUNTERED`; a counter from the CLEC against a standing `COUNTERPARTY_SIDE` offer moves it `COUNTERED → PROPOSED`."
    PRD 3.1: "Those two edges close the `PROPOSED → COUNTERED → PROPOSED` cycle that constitutes multi-round negotiation."
    PRD 3.2: "When the standing `OPEN` offer has `offering_party` `CLEC_SIDE` and the agreement is in `PROPOSED`, a `CarrierRepresentative` accepts it and the agreement moves `PROPOSED → EXECUTED`."

    Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycles_proposed_countered_proposed
    """
    state = setup_draft_agreement(api)
    observed = [read_agreement(api, state["agreement_id"])["status"]]

    append_proposal(
        api,
        state,
        reciprocal_rate_per_mou_usd=RECIPROCAL_RATE,
        term_months=TERM_MONTHS,
        poi_financial_responsibility="SHARED",
    )
    observed.append(read_agreement(api, state["agreement_id"])["status"])

    append_counter(
        api,
        state,
        from_counterparty=True,
        reciprocal_rate_per_mou_usd=0.085,
        term_months=24,
        poi_financial_responsibility="TERMINATOR_PAYS",
    )
    observed.append(read_agreement(api, state["agreement_id"])["status"])

    third = append_counter(
        api,
        state,
        from_counterparty=False,
        reciprocal_rate_per_mou_usd=0.07,
        term_months=30,
        poi_financial_responsibility="SHARED",
    )
    observed.append(read_agreement(api, state["agreement_id"])["status"])

    validate_success(
        api.accept_offer(third["id"], {}, state["rep_headers"]), expected_status=200
    )
    observed.append(read_agreement(api, state["agreement_id"])["status"])

    assert observed == ["DRAFT", "PROPOSED", "COUNTERED", "PROPOSED", "EXECUTED"], (
        f"PROPOSED must be occupied twice, observed {observed}"
    )
    assert read_agreement(api, state["agreement_id"])["negotiation_round"] == 3


def test_acceptance_pins_the_third_round_terms_and_leaves_the_opening_ask_intact(
    api, manager_headers
):
    """Accepting the round-3 offer pins its terms while the opening ask is preserved.

    PRD 3.2: "On acceptance the offer moves `OPEN → ACCEPTED` with `responded_at` stamped from the logical clock, and the agreement **pins** four commercial terms verbatim from that offer: `reciprocal_rate_per_mou_usd` (copied at its full six decimal places with no re-rounding), `term_months`, `poi_financial_responsibility` and `transit_traffic_allowed`."
    PRD 3.2: "The agreement's `executed_at` is stamped from the logical clock and its `version` increments by 1."
    PRD 3.1: "The agreement's `proposed_reciprocal_rate_per_mou_usd` and `proposed_term_months` are **never** overwritten by an offer — they remain the opening ask so that the pinned terms and the original position can be compared after execution."

    Design: Difficulty/non_linear_state_machine/agreement_negotiation_cycles_proposed_countered_proposed
    """
    state = setup_draft_agreement(api)
    first = append_proposal(
        api,
        state,
        reciprocal_rate_per_mou_usd=RECIPROCAL_RATE,
        term_months=TERM_MONTHS,
        poi_financial_responsibility="SHARED",
    )
    second = append_counter(
        api,
        state,
        from_counterparty=True,
        reciprocal_rate_per_mou_usd=0.085,
        term_months=24,
        poi_financial_responsibility="TERMINATOR_PAYS",
    )
    third = append_counter(
        api,
        state,
        from_counterparty=False,
        reciprocal_rate_per_mou_usd=0.07,
        term_months=30,
        poi_financial_responsibility="SHARED",
    )
    validate_success(
        api.accept_offer(third["id"], {}, state["rep_headers"]), expected_status=200
    )

    rows = {
        offer["id"]: offer
        for offer in validate_paginated(
            api.list_agreement_offers(state["agreement_id"], manager_headers)
        )[0]
    }
    assert rows[first["id"]]["status"] == "SUPERSEDED"
    assert rows[first["id"]]["offering_party"] == "CLEC_SIDE"
    assert rows[first["id"]]["round_number"] == 1
    assert rows[second["id"]]["status"] == "SUPERSEDED"
    assert rows[second["id"]]["offering_party"] == "COUNTERPARTY_SIDE"
    assert rows[second["id"]]["round_number"] == 2
    assert rows[third["id"]]["status"] == "ACCEPTED"
    assert rows[third["id"]]["offering_party"] == "CLEC_SIDE"
    assert rows[third["id"]]["round_number"] == 3

    agreement = read_agreement(api, state["agreement_id"])
    assert_rate(
        agreement["reciprocal_rate_per_mou_usd"], 0.07, "reciprocal_rate_per_mou_usd"
    )
    assert agreement["term_months"] == 30
    assert agreement["poi_financial_responsibility"] == "SHARED"
    assert_rate(
        agreement["proposed_reciprocal_rate_per_mou_usd"],
        RECIPROCAL_RATE,
        "proposed_reciprocal_rate_per_mou_usd",
    )
    assert agreement["proposed_term_months"] == TERM_MONTHS
    assert agreement["executed_at"] == T_2026_08_01
