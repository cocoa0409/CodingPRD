"""Role authorisation, entity-backed scope and segregation of duties.

Each test builds the rows it needs through the declared endpoints, because the
harness restarts the service with an empty database before each test.
"""
from test_helpers import (
    CONTRACTS_OFFICER,
    CONTRACTS_OFFICER_2,
    FRAUD_ANALYST,
    FRAUD_ANALYST_2,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    create_issuer,
    create_member,
    create_program,
    create_window,
    get_success_data,
    hold_seats,
    investigate_case,
    loyalty_program_payload,
    make_contracts_officer_headers,
    make_issuer_representative_headers,
    make_member_headers,
    make_partner_manager_headers,
    mile_sale_agreement_payload,
    mile_transaction_payload,
    open_case,
    read_agreement,
    read_member,
    read_program,
    read_window,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_contracts_officer_cannot_create_an_agreement_but_partner_manager_can(api):
    """Drafting is the PartnerManager's act; the ratifier is refused outright.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list for the operation being invoked, which §4 tabulates; a role that is authenticated but not authorised is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.1: "A `ContractsOfficer` is the independent contract authority: it ratifies and activates agreements, and exists precisely as the counterparty control to `PartnerManager`."
    PRD §3.2: "A `PartnerManager` drafts one against an `issuer_id`, giving the term as `term_start_date` and `term_end_date` (inclusive calendar dates), the `committed_volume_miles` the issuer undertakes to buy over that term (at least one mile), and a `tier_schedule` of volume price tiers."
    Design: Corner/rbac/contracts_officer_cannot_create_an_agreement_but_partner_manager_can
    """
    program = create_program(name="SkyMiles RBAC Exclusive")
    issuer = create_issuer(program["id"], annual_mile_purchase_cap_miles=5_000_000)
    payload = mile_sale_agreement_payload(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1_000_000,
    )

    refused = api.create_mile_sale_agreement(payload, CONTRACTS_OFFICER)
    validate_error(refused, "ERR_FORBIDDEN_ROLE", 403)

    accepted = validate_success(
        api.create_mile_sale_agreement(payload, PARTNER_MANAGER),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT", (
        "the PartnerManager's identical payload drafts the agreement"
    )
    _agreements, meta = validate_paginated(
        api.list_mile_sale_agreements(
            PARTNER_MANAGER, params={"issuer_id": issuer["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "only the PartnerManager's agreement was persisted for this issuer"
    )


def test_member_role_cannot_create_a_loyalty_program_returns_forbidden_role(api):
    """A Member is authenticated but unauthorised, so the answer is 403.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list for the operation being invoked, which §4 tabulates; a role that is authenticated but not authorised is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.1: "A `Member` is a loyalty programme member acting on their own account."
    PRD §3.1: "A `ProgramAdmin` opens the system by creating a **loyalty programme**, supplying a `name` of at most 120 characters and, optionally, four settings that shape everything downstream: the settlement `currency_code`, the starting `current_period`, the `breakage_policy_mode` that will be used whenever a deferred revenue posting omits its own method, and `saver_share_default_bps`, the default share of authorised award seats reservable at the cheaper fare."
    Design: Corner/rbac/member_role_cannot_create_a_loyalty_program_returns_forbidden_role
    """
    program = create_program(name="SkyMiles RBAC Member")
    member = create_member(program["id"], external_member_ref="MBR-RBAC")

    response = api.create_loyalty_program(
        loyalty_program_payload(name="Member's Own Program"),
        make_member_headers(member["id"]),
    )

    error = validate_error(response, "ERR_FORBIDDEN_ROLE", 403)
    assert error["error_id"] != "ERR_UNAUTHENTICATED", (
        "a Member carries a declared role, so authentication itself succeeds"
    )
    _programs, meta = validate_paginated(api.list_loyalty_programs(PROGRAM_ADMIN))
    assert meta["total_count"] == 1, (
        "the Member's create must leave the programme count at the one existing row"
    )


def test_both_program_admin_and_revenue_accountant_may_post_mile_transactions(api):
    """Two authorised roles post identically; the analyst may only read.

    PRD §3.4: "A `ProgramAdmin` or a `RevenueAccountant` posts a row naming the `member_id`, the `txn_type`, and the `activity_date` on which the underlying activity occurred."
    PRD §3.4: "**Sixth**, `total_miles` is the base plus `tier_bonus_miles` plus `bonus_miles`."
    PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."
    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list for the operation being invoked, which §4 tabulates; a role that is authenticated but not authorised is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    Design: Corner/rbac/both_program_admin_and_revenue_accountant_may_post_mile_transactions
    """
    program = create_program(name="SkyMiles Shared")
    member = create_member(program["id"], external_member_ref="MBR-SHARED")
    payload = mile_transaction_payload(
        member["id"], "PARTNER_EARN", "2026-08-01", base_miles=1000
    )

    by_admin = validate_success(
        api.create_mile_transaction(payload, PROGRAM_ADMIN), expected_status=201
    )
    assert by_admin["total_miles"] == 1000, (
        "a BASE member's unpromoted partner earn credits the supplied base verbatim"
    )

    by_accountant = validate_success(
        api.create_mile_transaction(payload, REVENUE_ACCOUNTANT), expected_status=201
    )
    assert by_accountant["total_miles"] == 1000, (
        "the RevenueAccountant's identical posting behaves identically"
    )

    refused = api.create_mile_transaction(payload, FRAUD_ANALYST)
    validate_error(refused, "ERR_FORBIDDEN_ROLE", 403)

    assert read_member(member["id"])["mile_balance"] == 2000, (
        "both accepted earns are summed into the member's mile_balance"
    )
    assert read_program(program["id"])["outstanding_miles"] == 2000, (
        "both accepted earns are summed into the programme's outstanding_miles"
    )
    _rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 2, (
        "the refused posting wrote no third ledger row"
    )


def test_the_analyst_who_opened_a_case_cannot_substantiate_it(api):
    """The opener may investigate but never adjudicate; the second analyst can.

    PRD §3.7: "A `FraudAnalyst` moves an `OPEN` case to `INVESTIGATING`, and from there adjudicates it in one of two directions."
    PRD §3.7: "Both directions are governed by segregation of duties: the adjudicating analyst's `X-User-ID` must differ from `opened_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "`detection_score` is then the weighted blend of those four — 3500 basis points on geo velocity, 3000 on redemption velocity, 2500 on brokering pattern and 1000 on dormancy, meaning 35%, 30%, 25% and 10% — with the weighted sum divided by 10000, rounded half up, and capped at 100."
    PRD §3.7: "A score below 40 leaves `security_state` where it was."
    PRD §3.7: "From that basis, a `MILE_BROKERING` case claws back the lesser of the member's current `mile_balance` and the full basis; a `VELOCITY_ANOMALY` case claws back the lesser of the member's `mile_balance` and half the basis rounded down; and an `ACCOUNT_TAKEOVER` case claws back nothing at all, because those miles were stolen *from* the member rather than earned by them, and the balance is preserved for reissue."
    PRD §3.7: "The second hop, caused by the first, applies the outcome: when `clawback_miles` is greater than zero a mile ledger row of `txn_type` `ADJUSTMENT` with `total_miles` equal to the negative of `clawback_miles` is inserted and the member's `mile_balance` is debited accordingly, and the member's `security_state` moves to `CLOSED` for an `ACCOUNT_TAKEOVER` case and to `FROZEN` for either other case type."
    PRD §3.7: "The fifth hop, caused by the second hop's adjustment insert, reduces the programme's `outstanding_miles` by `clawback_miles`."
    Design: Corner/rbac/the_analyst_who_opened_a_case_cannot_substantiate_it
    """
    program = create_program(name="SkyMiles SoD Fraud")
    member = create_member(program["id"], external_member_ref="MBR-SOD")
    validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "PARTNER_EARN", "2026-07-20", base_miles=5000
            ),
            REVENUE_ACCOUNTANT,
        ),
        expected_status=201,
    )
    case = open_case(
        member["id"], "MILE_BROKERING",
        headers=FRAUD_ANALYST,
        login_geo_velocity=0,
        redemption_velocity_24h=0,
        brokering_pattern_hits=4,
        dormancy_days=0,
    )
    assert case["detection_score"] == 25, (
        "four brokering hits cap that sub-score at 100 and weight it at 2500 bps"
    )
    assert read_member(member["id"])["security_state"] == "NORMAL", (
        "a detection score below 40 leaves the member's security_state untouched"
    )
    investigate_case(case["id"], headers=FRAUD_ANALYST)

    refused = api.substantiate_fraud_case(case["id"], FRAUD_ANALYST)
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 409)
    blocked = get_success_data(api.get_fraud_case(case["id"], FRAUD_ANALYST))
    assert blocked["status"] == "INVESTIGATING", (
        "the refused adjudication leaves the case in INVESTIGATING"
    )
    assert blocked["adjudicated_by_user_id"] is None, (
        "the refused adjudication stamps no adjudicator"
    )

    adjudicated = validate_success(
        api.substantiate_fraud_case(case["id"], FRAUD_ANALYST_2), expected_status=200
    )
    assert adjudicated["status"] == "SUBSTANTIATED", (
        "the second analyst's identical call substantiates the case"
    )
    assert adjudicated["adjudicated_by_user_id"] == "fa-2", (
        "substantiation stamps the adjudicating analyst's X-User-ID"
    )
    assert adjudicated["clawback_miles"] == 5000, (
        "a MILE_BROKERING case claws back the full 90-day earn basis"
    )
    refreshed_member = read_member(member["id"])
    assert refreshed_member["security_state"] == "FROZEN", (
        "substantiating a MILE_BROKERING case freezes the member"
    )
    assert refreshed_member["mile_balance"] == 0, (
        "the clawback adjustment debits the whole balance"
    )
    assert read_program(program["id"])["outstanding_miles"] == 0, (
        "the programme's outstanding_miles falls by the clawback"
    )
    adjustments, meta = validate_paginated(
        api.list_mile_transactions(
            FRAUD_ANALYST,
            params={"member_id": member["id"], "txn_type": "ADJUSTMENT"},
        )
    )
    assert meta["total_count"] == 1, "the cascade inserts exactly one ADJUSTMENT row"
    assert adjustments[0]["total_miles"] == -5000, (
        "the ADJUSTMENT row carries the negative of clawback_miles"
    )


def test_a_contracts_officer_sharing_the_negotiators_user_id_cannot_ratify(api):
    """Segregation of duties compares user ids, not roles.

    PRD §3.2: "It stamps `negotiated_by_user_id` with the submitting operator's `X-User-ID` — the value against which segregation of duties will later be measured."
    PRD §3.2: "First, the ratifier's `X-User-ID` must differ from `negotiated_by_user_id`; whoever negotiated the deal may not approve it, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "When ratification proceeds it stamps `ratified_by_user_id` from `X-User-ID` and then propagates in three hops."
    PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."
    Design: Corner/rbac/a_contracts_officer_sharing_the_negotiators_user_id_cannot_ratify
    """
    negotiator = make_partner_manager_headers("u-7")
    program = create_program(name="SkyMiles SoD Ratify")
    issuer = create_issuer(program["id"], annual_mile_purchase_cap_miles=5_000_000)
    agreement = validate_success(
        api.create_mile_sale_agreement(
            mile_sale_agreement_payload(
                issuer["id"],
                term_start_date="2026-09-01",
                term_end_date="2027-08-31",
                committed_volume_miles=1_000_000,
            ),
            negotiator,
        ),
        expected_status=201,
    )
    submitted = submit_agreement(agreement["id"], headers=negotiator)
    assert submitted["negotiated_by_user_id"] == "u-7", (
        "submission stamps the submitting operator's X-User-ID as the negotiator"
    )

    refused = api.ratify_agreement(
        agreement["id"], make_contracts_officer_headers("u-7")
    )
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 409)
    blocked = read_agreement(agreement["id"])
    assert blocked["status"] == "ISSUER_REVIEW", (
        "the refused ratification leaves the agreement under issuer review"
    )
    assert blocked["ratified_by_user_id"] is None, (
        "the refused ratification stamps no ratifier"
    )
    issuer_before = get_success_data(
        api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN)
    )
    assert issuer_before["aggregate_committed_miles"] == 0, (
        "an unratified agreement contributes nothing to the issuer aggregate"
    )

    ratified = validate_success(
        api.ratify_agreement(agreement["id"], CONTRACTS_OFFICER_2),
        expected_status=200,
    )
    assert ratified["status"] == "RATIFIED", (
        "a ContractsOfficer with a different user id ratifies the same agreement"
    )
    assert ratified["ratified_by_user_id"] == "co-2", (
        "ratification stamps ratified_by_user_id from X-User-ID"
    )
    issuer_after = get_success_data(
        api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN)
    )
    assert issuer_after["aggregate_committed_miles"] == 1_000_000, (
        "the ratified agreement's committed volume enters the issuer aggregate"
    )
    assert issuer_after["status"] == "ACTIVE", (
        "one million miles is below the alarm on a five million mile cap"
    )


def test_a_member_cannot_read_another_members_booking(api):
    """A peer Member is scope-blocked, while the owner reads the row fine.

    PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `MemberAccount`; a `Member` may read or act only on the member account whose `id` equals `X-User-ID`, and on the award bookings, mile ledger rows and fraud cases whose `member_id` equals `X-User-ID`."
    PRD §2.1: "Any attempt to reach another member's rows is rejected with `ERR_MEMBER_SCOPE_VIOLATION` (403)."
    PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
    PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."
    Design: Corner/rbac/a_member_cannot_read_another_members_booking
    """
    program = create_program(name="SkyMiles Peer")
    owner = create_member(program["id"], external_member_ref="MBR-P1")
    peer = create_member(program["id"], external_member_ref="MBR-P2")
    window = create_window(program["id"], authorized_seats=10)
    booking = hold_seats(
        owner["id"], window["id"], window["version"],
        headers=make_member_headers(owner["id"]),
        travel_date="2026-09-10", seats=1, fare_class="FLEX",
    )

    refused = api.get_award_booking(booking["id"], make_member_headers(peer["id"]))
    error = validate_error(refused, "ERR_MEMBER_SCOPE_VIOLATION", 403)
    assert error["error_id"] != "ERR_BOOKING_NOT_FOUND", (
        "the booking id resolves, so the scope rung answers rather than the 404 rung"
    )

    own_read = validate_success(
        api.get_award_booking(booking["id"], make_member_headers(owner["id"])),
        expected_status=200,
    )
    assert own_read["id"] == booking["id"], (
        "the owning member reads their own booking"
    )
    assert own_read["quoted_miles"] == 22500, (
        "one ECONOMY FLEX seat on an empty window quotes 22500 miles for a BASE member"
    )
    assert read_window(window["id"])["seats_held"] == 1, (
        "the refused read moves no seats on the window"
    )


def test_an_issuer_representative_cannot_counter_another_issuers_agreement(api):
    """Only the issuer named on the agreement may counter it.

    PRD §2.1: "When `X-User-Role` is `IssuerRepresentative`, `X-User-ID` is the `id` of the acting `CoBrandIssuer`; ownership checks on any resource that references a `CoBrandIssuer` compare that resource's `issuer_id` to `X-User-ID`, and a mismatch is rejected with `ERR_ISSUER_SCOPE_VIOLATION` (403)."
    PRD §3.2: "The issuer's own representative may then push back, advancing `ISSUER_REVIEW → COUNTERED` and stamping `countered_price_per_mile_centicents` and `countered_committed_volume_miles` from the request's `counter_price_per_mile_centicents` and `counter_committed_volume_miles`, with an optional free-text `note`."
    PRD §3.2: "Only the issuer named on the agreement may do this: an `IssuerRepresentative` whose `X-User-ID` does not equal the agreement's `issuer_id` is refused with `ERR_ISSUER_SCOPE_VIOLATION`."
    PRD §3.2: "A drafted agreement starts in `DRAFT` with `negotiation_round` at 1, both counter fields (`countered_price_per_mile_centicents` and `countered_committed_volume_miles`) null, `ratified_by_user_id` null, and `drawn_miles` and `prepayment_balance_miles` at zero."
    Design: Corner/rbac/an_issuer_representative_cannot_counter_another_issuers_agreement
    """
    program = create_program(name="SkyMiles Issuer Scope")
    issuer_one = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5_000_000,
    )
    issuer_two = create_issuer(
        program["id"],
        name="Southbank Card Services",
        annual_mile_purchase_cap_miles=5_000_000,
    )
    agreement = validate_success(
        api.create_mile_sale_agreement(
            mile_sale_agreement_payload(
                issuer_one["id"],
                term_start_date="2026-09-01",
                term_end_date="2027-08-31",
                committed_volume_miles=1_000_000,
            ),
            PARTNER_MANAGER,
        ),
        expected_status=201,
    )
    submit_agreement(agreement["id"])
    counter_payload = {
        "counter_price_per_mile_centicents": 180,
        "counter_committed_volume_miles": 800_000,
    }

    refused = api.counter_agreement(
        agreement["id"],
        counter_payload,
        make_issuer_representative_headers(issuer_two["id"]),
    )
    validate_error(refused, "ERR_ISSUER_SCOPE_VIOLATION", 403)
    blocked = read_agreement(agreement["id"])
    assert blocked["status"] == "ISSUER_REVIEW", (
        "the refused counter leaves the agreement under issuer review"
    )
    assert blocked["countered_price_per_mile_centicents"] is None, (
        "the refused counter stamps no countered price"
    )

    countered = validate_success(
        api.counter_agreement(
            agreement["id"],
            counter_payload,
            make_issuer_representative_headers(issuer_one["id"]),
        ),
        expected_status=200,
    )
    assert countered["status"] == "COUNTERED", (
        "the named issuer's representative advances ISSUER_REVIEW -> COUNTERED"
    )
    assert countered["countered_price_per_mile_centicents"] == 180, (
        "the counter price is stamped from counter_price_per_mile_centicents"
    )
    assert countered["countered_committed_volume_miles"] == 800_000, (
        "the counter volume is stamped from counter_committed_volume_miles"
    )
    assert countered["negotiation_round"] == 1, (
        "countering does not advance negotiation_round; only revising does"
    )
    assert countered["committed_volume_miles"] == 1_000_000, (
        "a counter records the issuer's ask without replacing the agreed volume"
    )
