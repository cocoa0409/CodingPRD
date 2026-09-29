"""Who may act: the two segregated signatures, the disjoint back-office powers,
the shopper's own record, and the front-line credentials that cannot trade verbs."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MONTH_WINDOWS,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_member_headers,
    make_program_admin_headers,
    make_pump_terminal_headers,
    make_store_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]
SECOND_ADMIN = make_program_admin_headers("admin-9")


def test_the_admin_who_submitted_the_batch_cannot_release_its_own_money():
    """Holding the approve permission is not enough: the money moves only once a
    different operator signs for it.

    PRD: "**Self-approval.** The acting `X-User-ID` must differ from the
    identifier of whoever produced the artefact being decided — otherwise
    `ERR_SELF_APPROVAL_FORBIDDEN`."

    PRD: "**Deciding a batch.** Only a `ProgramAdmin` decides, only a `SUBMITTED`
    batch can be decided, and in both directions the acting `X-User-ID` must differ
    from the batch's `submitted_by_user_id` — a submitter approving or rejecting
    their own batch is refused with `ERR_SELF_APPROVAL_FORBIDDEN`, and that holds
    even when the submitter was itself a `ProgramAdmin`."

    PRD: "**Approval** sets `status` to `APPROVED`, records `approved_by_user_id`
    as the acting `X-User-ID`, and stamps `decided_at` from the logical clock."

    PRD: "Every claimed redemption is driven from `BATCHED` to `SETTLED` on the
    settlement dimension, and its gallons and discount stay out of the unbatched
    pool permanently."

    Design: Corner/rbac/the_admin_who_submits_a_batch_cannot_approve_it
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.dispensed_partner_fill(
        300, 12.0, points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    partner_id = program["partner"]["id"]
    redemption_id = program["redemption"]["id"]
    batch = fixtures.open_batch(partner_id, AUGUST_START, AUGUST_END)

    submitted = fixtures.submit_batch(batch["id"], partner_id, headers=SECOND_ADMIN)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "admin-9"
    assert fixtures.get_redemption(redemption_id)["settlement_status"] == "BATCHED"

    validate_error(
        api_client.approve_settlement_batch(batch["id"], SECOND_ADMIN),
        ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value,
    )
    assert fixtures.get_batch(batch["id"])["status"] == "SUBMITTED"
    assert fixtures.get_redemption(redemption_id)["settlement_status"] == "BATCHED"

    approved = fixtures.approve_batch(batch["id"])

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "admin-1"
    assert fixtures.get_redemption(redemption_id)["settlement_status"] == "SETTLED"
    assert (
        fixtures.get_site(partner_id)["settlement_balance_cents"]
        == approved["reimbursement_cents"]
    )


def test_the_admin_who_proposed_the_adjustment_cannot_sign_it():
    """One operator holding both halves of the adjustment still cannot complete it
    alone, and nothing reaches the ledger until a second one signs.

    PRD: "**Self-approval.** The acting `X-User-ID` must differ from the
    identifier of whoever produced the artefact being decided — otherwise
    `ERR_SELF_APPROVAL_FORBIDDEN`."

    PRD: "A `LoyaltyAnalyst` manages household linkage, raises and clears fraud
    signals, investigates disputes and **proposes** adjustments — but may never
    approve one."

    PRD: "Approval appends exactly one `ADJUSTMENT` ledger row whose
    `points_delta` is the `proposed_points_delta` as proposed, whose
    `point_cycle_id` is the open cycle, whose `source_kind` is `POINT_DISPUTE` and
    whose `source_ref_id` is this dispute's identifier."

    PRD: "The dispute then records `applied_ledger_entry_id` as the new row's
    identifier, `approved_by_user_id` as the acting `X-User-ID`, `resolved_at` from
    the logical clock, and `status` `RESOLVED_UPHELD`."

    Design: Corner/rbac/the_admin_who_proposes_an_adjustment_cannot_approve_it
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(
        program["household"]["id"], housemate["id"], "SECONDARY", activate=True
    )
    transfer_out = fixtures.transfer_points(
        member_id, housemate["id"], 100, headers=make_member_headers(member_id)
    )
    dispute = fixtures.file_dispute(
        member_id,
        transfer_out["id"],
        100,
        "UNAUTHORIZED_REDEMPTION",
        headers=make_member_headers(member_id),
    )
    fixtures.investigate_dispute(dispute["id"])
    proposed = fixtures.propose_adjustment(
        dispute["id"], 100, "TIER1", headers=SECOND_ADMIN
    )
    assert proposed["proposed_by_user_id"] == "admin-9"

    validate_error(
        api_client.approve_dispute_adjustment(dispute["id"], SECOND_ADMIN),
        ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value,
    )
    assert (
        validate_success(api_client.get_point_dispute(dispute["id"], ADMIN))["status"]
        == "ADJUSTMENT_PROPOSED"
    )
    _blocked, blocked_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "ADJUSTMENT"}
        )
    )
    assert blocked_meta["total_count"] == 0

    upheld = fixtures.approve_adjustment(dispute["id"], headers=ADMIN)

    assert upheld["status"] == "RESOLVED_UPHELD"
    assert upheld["approved_by_user_id"] == "admin-1"
    assert upheld["applied_ledger_entry_id"] is not None
    assert fixtures.get_member(member_id)["available_points"] == 300


def test_the_analyst_and_the_supervisor_cannot_borrow_each_others_powers():
    """Each back-office role is turned away at the operations reserved for the
    other, and nothing they touched moved.

    PRD: "A request whose role is recognised but is not listed among the roles
    authorised for the target operation in §4 is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    PRD: "A `LoyaltyAnalyst` manages household linkage, raises and clears fraud
    signals, investigates disputes and **proposes** adjustments — but may never
    approve one."

    PRD: "A `LoyaltySupervisor` runs the month-boundary close, freezes and thaws
    households, denies disputes, and approves `TIER1` and `TIER2` adjustments
    proposed by someone else."

    Design: Corner/rbac/analyst_and_supervisor_cannot_reach_into_each_others_exclusive_operations
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    cycles = fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    member = fixtures.create_member(banner["id"], alt_id="6660000001")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    link = fixtures.create_link(
        household["id"], member["id"], "PRIMARY", activate=False, headers=ANALYST
    )
    august_id = cycles["2026-08"]["id"]
    fixtures.set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api_client.begin_close_point_cycle(august_id, ANALYST),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.freeze_household(household["id"], ANALYST),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.create_fraud_signal(
            factories.fraud_signal_payload(
                household["id"], signal_type="CROSS_BANNER_VELOCITY", severity_weight=30
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.activate_household_link(link["id"], SUPERVISOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    assert validate_success(api_client.get_point_cycle(august_id, ADMIN))["status"] == "OPEN"
    household_view = fixtures.get_household(household["id"])
    assert household_view["status"] == "ACTIVE"
    assert household_view["fraud_score"] == 0
    assert fixtures.get_link(link["id"])["status"] == "PENDING"

    _signals, signal_meta = validate_paginated(
        api_client.list_household_fraud_signals(household["id"], ADMIN)
    )
    assert signal_meta["total_count"] == 0


def test_a_member_reads_only_their_own_record_and_never_the_roster():
    """The shopper is refused two different ways: as the wrong subject on a
    permitted read, and as the wrong role on a listing that excludes them.

    PRD: "One role is backed by a persisted `Member`: when `X-User-Role` is
    `Member`, `X-User-ID` is the `id` of the acting `Member`, and ownership checks
    compare the target resource's `member_id` (or the `id` of the member named
    directly in the path) to `X-User-ID`."

    PRD: "Where the check does apply and fails, the response is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD: "A request whose role is recognised but is not listed among the roles
    authorised for the target operation in §4 is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/a_member_sees_only_their_own_record_and_cannot_browse_the_roster
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    member_headers = make_member_headers(member_id)
    other = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )

    validate_error(
        api_client.get_member(other["id"], member_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    validate_error(
        api_client.list_members(member_headers, {"banner_id": program["banner"]["id"]}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    own_record = validate_success(api_client.get_member(member_id, member_headers))
    own_summary = validate_success(
        api_client.get_points_summary(member_id, member_headers)
    )

    assert own_record["id"] == member_id
    assert own_record["available_points"] == 300
    assert own_summary["member_id"] == member_id
    assert own_summary["available_points"] == 300


def test_the_program_admin_needs_no_site_identity_where_an_operator_does():
    """The lane credential is bound to its own site while the operator identity is
    bound to none, so the admin rings, posts and authorizes anywhere.

    PRD: "When `X-User-Role` is `StoreOperator`, `X-User-ID` is the `id` of the
    acting `Site`; ownership checks on any resource that references a `Site` compare
    that resource's `site_id` to `X-User-ID`."

    PRD: "The server records it where a transition writes it — as
    `proposed_by_user_id` and `approved_by_user_id` on a dispute, as
    `submitted_by_user_id` and `approved_by_user_id` on a settlement batch, and as
    `cleared_by_user_id` on a fraud signal — but never compares it to any entity's
    `id`."

    PRD: "Consequently the ownership rule described in §2.10 never applies to these
    three roles."

    Design: Corner/rbac/program_admin_acts_for_any_site_without_owning_it
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=0, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    grocery_id = program["grocery"]["id"]
    fuel_id = program["fuel"]["id"]
    basket_payload = factories.purchase_transaction_payload(
        member_id, grocery_id, "2026-08-01T00:00:00Z"
    )

    validate_error(
        api_client.create_purchase_transaction(
            basket_payload, make_store_operator_headers(fuel_id)
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    basket = validate_success(
        api_client.create_purchase_transaction(basket_payload, ADMIN), 201
    )
    posted = validate_success(api_client.post_purchase_transaction(basket["id"], ADMIN))
    assert posted["gross_points_awarded"] == 300

    redemption = validate_success(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id,
                fuel_id,
                "6660000001",
                300,
                fixtures.member_version(member_id),
            ),
            ADMIN,
        ),
        201,
    )

    assert redemption["points_debited_at_auth"] == 300
    assert fixtures.get_member(member_id)["available_points"] == 0


def test_the_lane_and_the_pump_cannot_administer_or_swap_verbs():
    """Neither front-line credential reaches the program's configuration, and
    neither reaches the other's operation.

    PRD: "A request whose role is recognised but is not listed among the roles
    authorised for the target operation in §4 is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    PRD: "A `StoreOperator` is a grocery lane or service desk: it enrolls members
    and records and posts baskets."

    PRD: "A `PumpTerminal` is an unattended dispenser controller: it looks members
    up by alternate ID, authorizes a per-gallon discount, and closes the fill out."

    Design: Corner/rbac/front_line_roles_cannot_administer_the_program_or_cross_their_lane
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    grocery_id = program["grocery"]["id"]
    fuel_id = program["fuel"]["id"]
    lane = make_store_operator_headers(grocery_id)

    validate_error(
        api_client.create_site(
            factories.grocery_site_payload(program["banner"]["id"], "G-999"), lane
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id,
                fuel_id,
                "6660000001",
                300,
                fixtures.member_version(member_id),
            ),
            lane,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.create_purchase_transaction(
            factories.purchase_transaction_payload(
                member_id,
                grocery_id,
                "2026-08-01T00:00:00Z",
                [factories.purchase_line("GROCERY", 10000, 1)],
            ),
            make_pump_terminal_headers(grocery_id),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _sites, site_meta = validate_paginated(
        api_client.list_sites(ADMIN, {"banner_id": program["banner"]["id"]})
    )
    assert site_meta["total_count"] == 2

    _redemptions, redemption_meta = validate_paginated(
        api_client.list_fuel_redemptions(ADMIN, {"member_id": member_id})
    )
    assert redemption_meta["total_count"] == 0
    assert fixtures.get_member(member_id)["available_points"] == 300
