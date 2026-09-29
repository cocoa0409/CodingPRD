"""
The programme, community-engagement and money gates of the authority.

Each test drives one submission, one work order or one demolition run into
exactly the refusal the PRD names for the single condition it breaks, and the
side-lot boundary case drives the same gate family from the other side by
meeting the minimum shared boundary exactly.
"""

from test_helpers import (
    ApiErrorId,
    DISP_1,
    INV_1,
    expected_mow_estimate_cents,
    factories,
    fixtures,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ── shared setup ─────────────────────────────────────────────────────────────
def _listed_parcel(api, *, address, structure_present, assessed_value_cents=120000,
                   lot_area_sqft=4000, vacancy_months=6):
    """A parcel carried from the registry through clear title to LISTED."""
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Programme Gate Line", authorized_cents=900000
    )
    bundle = fixtures.listed_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "address": address,
            "situs_ward": 3,
            "lot_area_sqft": lot_area_sqft,
            "assessed_value_cents": assessed_value_cents,
            "structure_present": structure_present,
            "structure_condition_grade": "C",
            "vacancy_months": vacancy_months,
        },
    )
    return bundle["property"]


def _acquired_mowable_parcel(api):
    """
    An ACQUIRED 10,000 square foot parcel and a licensed mowing crew: every
    condition of a mowing order is satisfied except the funding one under test.
    """
    acquisition_money = fixtures.create_acquisition_funding_source(
        api, name="Restriction Acquisition Line", authorized_cents=500000
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=acquisition_money,
        property_overrides={
            "address": "3130 Magnolia Ln",
            "situs_ward": 3,
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": False,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
    )
    contractor = fixtures.create_contractor(
        api,
        name="Magnolia Mowing",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )
    return acquisition_money, fixtures.read_property(api, bundle["property"]["id"]), contractor


def _assert_no_order_and_untouched_money(api, parcel, funding_sources):
    """No order was written, no cent was committed and no version moved."""
    orders, meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"property_id": parcel["id"]})
    )
    assert meta["total_count"] == 0
    assert orders == []
    for before in funding_sources:
        after = fixtures.read_funding_source(api, before["id"])
        assert after["committed_cents"] == 0
        assert after["disbursed_cents"] == 0
        assert after["version"] == before["version"]
    assert fixtures.property_version(api, parcel["id"]) == parcel["version"]


# ── the two structural gates of a side-lot transfer ──────────────────────────
def test_side_lot_on_a_parcel_that_still_carries_a_structure_is_refused(api):
    """
    A side-lot transfer of a parcel that still carries a standing structure is refused, because the programme exists only for vacant land.

    A side-lot request demands a vacant target parcel — `structure_present` false, else `ERR_SIDE_LOT_REQUIRES_VACANT` — and demands that the applicant already own the parcel next door: there must be an adjacency edge with `shared_boundary_feet` of at least 20 linking the target parcel to some parcel the applicant owns of record, in either direction of the edge, or the request is refused with `ERR_NOT_ADJACENT_OWNER`.

    Design: Corner/validations/side_lot_vacancy_and_adjacency_gates_rejected
    """
    parcel = _listed_parcel(api, address="3140 Nyssa Ln", structure_present=True)
    assert parcel["structure_present"] is True

    buyer = fixtures.create_applicant(
        api, legal_name="Nadia Okonjo", contact_email="nadia@example.test"
    )
    quote = fixtures.price_quote(api, parcel["id"], "SIDE_LOT")
    application = fixtures.draft_application(
        api,
        parcel["id"],
        buyer["id"],
        program="SIDE_LOT",
        proposed_use="Yard extension",
        offer_price_cents=quote["quoted_price_cents"],
    )
    # The gate lives at submission, not at drafting.
    assert application["status"] == "DRAFT"

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.SIDE_LOT_REQUIRES_VACANT.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["revision_round"] == 0
    assert after["version"] == application["version"]


def test_side_lot_without_an_owned_abutting_parcel_is_refused(api):
    """
    A side-lot transfer of a genuinely vacant parcel is still refused when the buyer owns no parcel sharing a boundary with it.

    A side-lot request demands a vacant target parcel — `structure_present` false, else `ERR_SIDE_LOT_REQUIRES_VACANT` — and demands that the applicant already own the parcel next door: there must be an adjacency edge with `shared_boundary_feet` of at least 20 linking the target parcel to some parcel the applicant owns of record, in either direction of the edge, or the request is refused with `ERR_NOT_ADJACENT_OWNER`.

    Design: Corner/validations/side_lot_vacancy_and_adjacency_gates_rejected
    """
    parcel = _listed_parcel(api, address="3141 Nyssa Ln", structure_present=False)
    assert parcel["structure_present"] is False

    buyer = fixtures.create_applicant(
        api, legal_name="Nadia Okonjo", contact_email="nadia@example.test"
    )
    quote = fixtures.price_quote(api, parcel["id"], "SIDE_LOT")
    application = fixtures.draft_application(
        api,
        parcel["id"],
        buyer["id"],
        program="SIDE_LOT",
        proposed_use="Yard extension",
        offer_price_cents=quote["quoted_price_cents"],
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.NOT_ADJACENT_OWNER.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["revision_round"] == 0
    assert after["version"] == application["version"]


def test_side_lot_clears_every_gate_at_exactly_twenty_shared_feet(api):
    """
    A vacant side lot abutting the buyer's own parcel along exactly twenty shared feet, offered at the full quote, clears the side-lot gates and screens clean.

    A side-lot request demands a vacant target parcel — `structure_present` false, else `ERR_SIDE_LOT_REQUIRES_VACANT` — and demands that the applicant already own the parcel next door: there must be an adjacency edge with `shared_boundary_feet` of at least 20 linking the target parcel to some parcel the applicant owns of record, in either direction of the edge, or the request is refused with `ERR_NOT_ADJACENT_OWNER`.

    Design: Corner/validations/side_lot_gate_satisfied_at_exact_twenty_shared_feet
    """
    buyer = fixtures.create_applicant(
        api, legal_name="Sofia Marchetti", contact_email="sofia@example.test"
    )
    home = fixtures.create_property(
        api,
        address="3200 Tupelo Ln",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=True,
        structure_condition_grade="B",
        vacancy_months=0,
    )
    fixtures.set_owner_of_record(api, home["id"], buyer["id"])

    side_lot = _listed_parcel(
        api,
        address="3201 Tupelo Ln",
        structure_present=False,
        lot_area_sqft=5000,
        vacancy_months=8,
    )
    edge = fixtures.create_adjacency(api, side_lot["id"], home["id"], 20)
    assert edge["shared_boundary_feet"] == 20

    # A 5,000 square foot lot charges no marginal area, so the base price stands
    # and the 25 percent assessed cap of 30,000 cents does not bind.
    quote = fixtures.price_quote(api, side_lot["id"], "SIDE_LOT")
    assert quote["marginal_area_sqft"] == 0
    assert quote["assessed_cap_cents"] == 30000
    assert quote["quoted_price_cents"] == 10000

    application = fixtures.draft_application(
        api,
        side_lot["id"],
        buyer["id"],
        program="SIDE_LOT",
        proposed_use="Yard extension and vegetable beds",
        offer_price_cents=10000,
    )

    submitted = validate_success(
        api.submit_application(application["id"], make_applicant_headers(buyer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["quoted_price_cents"] == 10000

    screening = validate_success(api.screen_application(application["id"], DISP_1), 201)
    assert screening["disqualifiers"] == []
    assert screening["outcome"] == "PASS"
    assert screening["eligibility_score"] == 100
    assert fixtures.read_application(api, application["id"])["status"] == "SCREENED"


# ── programme pairing and the nonprofit's paperwork ──────────────────────────
def test_community_use_by_an_individual_is_refused_on_the_pairing_rule(api):
    """
    Community use is reserved for nonprofits, so an individual asking for it is refused for the class of buyer it is.

    Programme and applicant class must match: `SIDE_LOT` and `HOMEOWNER_SALE` are open to an `INDIVIDUAL`, `DEVELOPER_RFP` to a `DEVELOPER` and `COMMUNITY_USE` to a `NONPROFIT`, with any other pairing refused as `ERR_APPLICANT_TYPE_NOT_ELIGIBLE`.

    Design: Corner/validations/program_pairing_and_nonprofit_registration_gates_rejected
    """
    parcel = _listed_parcel(
        api, address="3150 Osage Ln", structure_present=False, lot_area_sqft=8000,
        assessed_value_cents=200000,
    )
    # A fresh, well-supported hearing is on file, so the community-engagement
    # gates could not be what refuses this submission.
    fixtures.create_reuse_hearing(api, parcel["id"])

    buyer = fixtures.create_applicant(
        api, legal_name="Omar Silva", contact_email="omar@example.test"
    )
    assert buyer["applicant_type"] == "INDIVIDUAL"

    application = fixtures.draft_application(
        api,
        parcel["id"],
        buyer["id"],
        program="COMMUNITY_USE",
        proposed_use="Community garden",
        offer_price_cents=100,
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.APPLICANT_TYPE_NOT_ELIGIBLE.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == application["version"]


def test_community_use_nonprofit_without_a_registration_number_is_refused(api):
    """
    A correctly typed nonprofit that carries no state registration number is refused for the missing paperwork.

    A community-use applicant must additionally carry a `nonprofit_registration_no` (`ERR_NONPROFIT_REGISTRATION_REQUIRED`).

    Design: Corner/validations/program_pairing_and_nonprofit_registration_gates_rejected
    """
    parcel = _listed_parcel(
        api, address="3150 Osage Ln", structure_present=False, lot_area_sqft=8000,
        assessed_value_cents=200000,
    )
    fixtures.create_reuse_hearing(api, parcel["id"])

    buyer = fixtures.create_applicant(
        api,
        legal_name="Osage Neighbours Inc",
        applicant_type="NONPROFIT",
        contact_email="osage@example.test",
    )
    assert buyer["applicant_type"] == "NONPROFIT"
    assert buyer["nonprofit_registration_no"] is None

    application = fixtures.draft_application(
        api,
        parcel["id"],
        buyer["id"],
        program="COMMUNITY_USE",
        proposed_use="Community garden",
        offer_price_cents=100,
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.NONPROFIT_REGISTRATION_REQUIRED.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == application["version"]


# ── the community's verdict: freshness first, then sentiment ─────────────────
def _community_use_application(api, *, address, hearing_overrides):
    """A listed vacant parcel, one hearing on it, and a registered nonprofit."""
    parcel = _listed_parcel(
        api, address=address, structure_present=False, lot_area_sqft=7000,
        assessed_value_cents=200000,
    )
    hearing = fixtures.create_reuse_hearing(api, parcel["id"], **hearing_overrides)
    buyer = fixtures.create_nonprofit_applicant(
        api, legal_name="Persimmon Commons Inc", nonprofit_registration_no="NP-77160"
    )
    application = fixtures.draft_application(
        api,
        parcel["id"],
        buyer["id"],
        program="COMMUNITY_USE",
        proposed_use="Community orchard",
        offer_price_cents=100,
    )
    return parcel, hearing, buyer, application


def test_community_use_with_a_hearing_past_its_window_is_refused(api):
    """
    A community-use submission fails when the governing hearing was held longer ago than the freshness window allows, however strongly it was supported.

    That hearing must exist and have been held no more than 180 days before the current instant, or the submission fails with `ERR_HEARING_STALE`; the quorum and support test runs strictly after the freshness test, so a hearing with no comments is turned away by quorum rather than by a division.

    Design: Corner/validations/community_use_hearing_stale_and_unsupported_rejected
    """
    parcel, hearing, buyer, application = _community_use_application(
        api,
        address="3160 Persimmon Ln",
        hearing_overrides={
            "hearing_at": "2026-07-15T18:00:00Z",
            "comment_count": 8,
            "support_count": 7,
            "summary": "Strong support for a community orchard",
        },
    )
    # Quorum and sentiment are both comfortably met, so only freshness can fail.
    assert hearing["comment_count"] == 8
    assert hearing["support_ratio"] == 0.875

    # The clock moves well past the 180 days the hearing stays good for.
    fixtures.set_clock(api, "2027-03-01T00:00:00Z")

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.HEARING_STALE.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == application["version"]
    assert fixtures.read_property(api, parcel["id"])["custody_status"] == "LISTED"


def test_community_use_with_a_hearing_below_the_support_ratio_is_refused(api):
    """
    A fresh hearing that reaches quorum but musters only half its comments in support fails the support test.

    Quorum and support are one rule: the governing hearing needs at least 5 comments and a `support_ratio` of at least 0.60, failing which the submission is refused with `ERR_HEARING_SUPPORT_INSUFFICIENT`.

    Design: Corner/validations/community_use_hearing_stale_and_unsupported_rejected
    """
    parcel, hearing, buyer, application = _community_use_application(
        api,
        address="3161 Persimmon Ln",
        hearing_overrides={
            "hearing_at": "2026-07-20T18:00:00Z",
            "comment_count": 10,
            "support_count": 5,
            "summary": "Split opinion on a community orchard",
        },
    )
    # Ten comments clear the quorum of five, and the hearing is days old rather
    # than months, so the ratio is the only failing half of the rule.
    assert hearing["comment_count"] == 10
    assert hearing["support_ratio"] == 0.5

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.HEARING_SUPPORT_INSUFFICIENT.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == application["version"]
    assert fixtures.read_property(api, parcel["id"])["custody_status"] == "LISTED"


# ── what the money may pay for, and how much of it there is ─────────────────
def test_acquisition_only_money_may_not_fund_a_mowing_order(api):
    """
    A budget authorized for acquisitions alone refuses to pay for mowing, however much of it is left unspent.

    A source whose `restriction` is `ACQUISITION_ONLY` refuses maintenance orders and demolition runs; a source whose `restriction` is `DEMOLITION_ONLY` refuses acquisition packets and refuses any maintenance order whose `work_type` is not `DEMOLITION`; a source whose `restriction` is `ANY` admits every category. A restriction breach is reported as `ERR_FUNDING_RESTRICTION_VIOLATION`.

    Design: Corner/validations/funding_restriction_and_insufficiency_rejected
    """
    acquisition_money, parcel, contractor = _acquired_mowable_parcel(api)

    ledger = fixtures.read_funding_source(api, acquisition_money["id"])
    assert ledger["restriction"] == "ACQUISITION_ONLY"
    # The balance is ample, so the arithmetic gate cannot be what refuses this.
    assert ledger["available_cents"] > expected_mow_estimate_cents(10000)

    payload = factories.maintenance_order_payload(
        contractor["id"],
        acquisition_money["id"],
        parcel["version"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    response = api.create_maintenance_order(parcel["id"], payload, INV_1)
    validate_error(response, ApiErrorId.FUNDING_RESTRICTION_VIOLATION.value)

    _assert_no_order_and_untouched_money(api, parcel, [ledger])


def test_mowing_order_is_refused_when_the_balance_falls_one_cent_short(api):
    """
    A budget that admits maintenance spending still refuses a mowing order when its available balance is a single cent below the computed estimate.

    The funding source's `restriction` must admit the category, its `available_cents` must be at least the estimate (`ERR_FUNDING_INSUFFICIENT` otherwise), and on success the estimate is added to `committed_cents`, `available_cents` is recomputed, and the source's `status` follows the reserve-floor rules of §2.8 — including parking `DUE_DILIGENCE` packets in `ON_HOLD_FUNDING` when the commitment pushes the source below its floor.

    Design: Corner/validations/funding_restriction_and_insufficiency_rejected
    """
    acquisition_money, parcel, contractor = _acquired_mowable_parcel(api)

    # Ten started thousand-square-foot blocks plus county overhead.
    estimate = expected_mow_estimate_cents(10000)
    assert estimate == 19703

    thin_money = fixtures.create_funding_source(
        api,
        name="Thin Maintenance Line",
        source_type="GRANT",
        authorized_cents=estimate - 1,
        restriction="ANY",
    )
    assert thin_money["restriction"] == "ANY"
    assert thin_money["available_cents"] == estimate - 1

    payload = factories.maintenance_order_payload(
        contractor["id"],
        thin_money["id"],
        parcel["version"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    response = api.create_maintenance_order(parcel["id"], payload, INV_1)
    validate_error(response, ApiErrorId.FUNDING_INSUFFICIENT.value)

    _assert_no_order_and_untouched_money(api, parcel, [thin_money])


def test_mowing_order_on_a_registry_only_parcel_is_refused(api):
    """
    A parcel the authority has only catalogued is not inventory, so maintenance money may not be spent on it even with a fit crew, a valid window and ample funds.

    Only a parcel actually in the land bank's hands may be worked on: its `custody_status` must be `ACQUIRED`, `LISTED` or `REVERTED`, and an order against a registry-only `PROSPECT` parcel is refused with `ERR_PROPERTY_NOT_IN_INVENTORY`.

    Design: Corner/validations/maintenance_order_on_prospect_parcel_rejected
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Prospect Guard Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    parcel = fixtures.create_property(
        api,
        address="3190 Sycamore Ln",
        situs_ward=3,
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    assert parcel["custody_status"] == "PROSPECT"
    contractor = fixtures.create_contractor(
        api,
        name="Sycamore Mowing",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )
    # Everything else about the request is sound: the crew mows, the licence
    # outlives the window, and the money admits maintenance with room to spare.
    assert funding_source["available_cents"] > expected_mow_estimate_cents(10000)

    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        parcel["version"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    response = api.create_maintenance_order(parcel["id"], payload, INV_1)
    validate_error(response, ApiErrorId.PROPERTY_NOT_IN_INVENTORY.value)

    _assert_no_order_and_untouched_money(api, parcel, [funding_source])


# ── planning a run against the budget, and executing an empty one ────────────
def test_run_budget_one_cent_over_the_available_balance_is_refused(api):
    """
    A demolition run may be planned for the whole available balance but not for one cent more.

    The budget may not exceed the source's `available_cents` at planning time — a budget exactly equal to the available balance is accepted, anything larger is refused with `ERR_RUN_BUDGET_EXCEEDS_AVAILABLE` — and the source's `restriction` must admit demolition spending.

    Design: Corner/validations/run_budget_over_available_and_empty_run_rejected
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Run Budget Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="DEMOLITION_ONLY",
    )
    assert funding_source["available_cents"] == 1000000
    assert funding_source["open_run_count"] == 0

    over_budget = factories.demolition_run_payload(
        funding_source["id"],
        funding_source["available_cents"] + 1,
        funding_source["version"],
    )
    response = api.create_demolition_run(over_budget, INV_1)
    validate_error(response, ApiErrorId.RUN_BUDGET_EXCEEDS_AVAILABLE.value)

    unchanged = fixtures.read_funding_source(api, funding_source["id"])
    assert unchanged["version"] == funding_source["version"]
    assert unchanged["open_run_count"] == 0
    assert unchanged["committed_cents"] == 0

    runs, meta = validate_paginated(
        api.list_funding_source_demolition_runs(funding_source["id"], INV_1)
    )
    assert meta["total_count"] == 0
    assert runs == []

    # The same budget one cent lower - exactly the available balance - is taken.
    at_the_balance = factories.demolition_run_payload(
        funding_source["id"],
        funding_source["available_cents"],
        unchanged["version"],
    )
    planned = validate_success(api.create_demolition_run(at_the_balance, INV_1), 201)
    assert planned["status"] == "PLANNED"
    assert planned["budget_cents"] == 1000000


def test_run_with_no_candidates_may_be_planned_but_not_executed(api):
    """
    A run whose ward filter matches no eligible parcel is still planned, and only its execution is refused, leaving it planned forever.

    When the candidate pool is empty the run is still created, in `PLANNED`, with `properties_selected_count` of zero and `total_committed_cents` of zero; an attempt to execute such a run is refused with `ERR_EMPTY_RUN` and the run stays `PLANNED`, available to be examined but never executed.

    Design: Corner/validations/run_budget_over_available_and_empty_run_rejected
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Run Budget Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="DEMOLITION_ONLY",
    )

    # No parcel is registered at all, so ward 9 holds nothing to demolish.
    run = fixtures.plan_demolition_run(
        api, funding_source["id"], funding_source["available_cents"], situs_ward_filter=9
    )
    assert run["status"] == "PLANNED"
    assert run["properties_selected_count"] == 0
    assert run["selected_property_ids"] == []
    assert run["total_committed_cents"] == 0

    after_planning = fixtures.read_funding_source(api, funding_source["id"])
    assert after_planning["committed_cents"] == 0
    assert after_planning["open_run_count"] == 1

    response = api.execute_demolition_run(run["id"], INV_1)
    validate_error(response, ApiErrorId.EMPTY_RUN.value)

    runs, meta = validate_paginated(
        api.list_funding_source_demolition_runs(funding_source["id"], INV_1)
    )
    assert meta["total_count"] == 1
    assert runs[0]["status"] == "PLANNED"
    assert runs[0]["orders_created_count"] == 0
    assert runs[0]["executed_at"] is None
    assert runs[0]["version"] == run["version"]

    ledger = fixtures.read_funding_source(api, funding_source["id"])
    assert ledger["committed_cents"] == 0
    assert ledger["open_run_count"] == 1
    assert ledger["version"] == after_planning["version"]

    orders, order_meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"demolition_run_id": run["id"]})
    )
    assert order_meta["total_count"] == 0
    assert orders == []
