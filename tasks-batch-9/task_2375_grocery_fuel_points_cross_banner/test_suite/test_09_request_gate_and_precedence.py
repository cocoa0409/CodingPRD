"""Precedence: which of several simultaneously broken rules the answer names,
from the authentication gate down to the business rules of a transfer."""
from test_helpers import (
    ADMIN,
    ANALYST,
    SUPERVISOR,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    factories,
    fixtures,
    make_member_headers,
    make_pump_terminal_headers,
    make_store_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_HOUSEHOLD_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-000000000004"


def test_an_unauthenticated_probe_never_reveals_whether_a_banner_exists():
    """A caller who presents no usable role is answered at the gate, so the
    unresolvable identifier in the path is never even looked up.

    PRD: "When a request violates more than one rule, the response is determined
    by the **first** violated rule in the ordering below; no later rule is
    evaluated."

    PRD: "**Authentication.** Both headers present and non-empty, and
    `X-User-Role` one of the seven roles — otherwise `ERR_UNAUTHENTICATED`."

    PRD: "**Path existence.** Every identifier embedded in the request path
    resolves, validated strictly left to right, so the leftmost unresolvable
    identifier determines the error."

    Design: Corner/validations/missing_auth_headers_are_refused_before_any_id_is_looked_up
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    bare = validate_error(
        api_client.get_banner(NON_EXISTENT_UUID),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    unknown_role = validate_error(
        api_client.get_banner(
            NON_EXISTENT_UUID, {"X-User-Role": "NotARole", "X-User-ID": "u1"}
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    assert bare["error_id"] != ApiErrorId.ERR_BANNER_NOT_FOUND.value
    assert unknown_role["error_id"] != ApiErrorId.ERR_BANNER_NOT_FOUND.value


def test_a_lane_terminal_is_screened_out_before_the_unknown_banner_is_resolved():
    """The role screen answers first; the same call from an authorised role gets
    as far as the path and reports the missing banner.

    PRD: "**Authorization.** The acting role appears among the roles authorised
    for the endpoint — otherwise `ERR_UNAUTHORIZED`."

    PRD: "**Path existence.** Every identifier embedded in the request path
    resolves, validated strictly left to right, so the leftmost unresolvable
    identifier determines the error."

    Design: Corner/validations/a_forbidden_role_is_refused_before_the_unknown_path_id
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    grocery = fixtures.create_grocery_site(banner["id"], "G-100")

    validate_error(
        api_client.suspend_banner(
            NON_EXISTENT_UUID, make_store_operator_headers(grocery["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.suspend_banner(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_BANNER_NOT_FOUND.value,
    )

    assert validate_success(api_client.get_banner(banner["id"], ADMIN))["status"] == "ACTIVE"


def test_a_linkage_proposal_reports_the_first_unresolvable_body_reference():
    """With both body references broken the household is named, because the
    household is the first identifier the proposal lists.

    PRD: "**Body existence.** Every identifier in the request body resolves,
    validated in the order the fields are listed for that endpoint, drawing on the
    same 404 family."

    PRD: "A linkage is proposed by naming a `household_id`, a `member_id` and a
    `link_role` of either `PRIMARY` or `SECONDARY`."

    Design: Corner/validations/body_reference_ids_are_resolved_in_declared_input_order
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    fixtures.create_member(banner["id"], alt_id="6660000001")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")

    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(
                UNKNOWN_HOUSEHOLD_ID, UNKNOWN_MEMBER_ID, "PRIMARY"
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(
                household["id"], UNKNOWN_MEMBER_ID, "PRIMARY"
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_MEMBER_NOT_FOUND.value,
    )

    _links, meta = validate_paginated(
        api_client.list_household_links(ADMIN, {"household_id": household["id"]})
    )
    assert meta["total_count"] == 0
    assert fixtures.get_household(household["id"])["linked_member_count"] == 0


def test_the_pump_identity_is_matched_against_the_site_named_in_the_body():
    """A terminal keyed to the grocery lane cannot authorize at the fuel centre
    even though the fuel centre is the site the body names.

    PRD: "**Resource ownership.** For the three `Site`-backed roles and the
    `Member` role, the acting `X-User-ID` must own the referenced resource as
    described in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER`."

    PRD: "The same holds for `PumpTerminal` and for `SettlementClerk`: in both
    cases `X-User-ID` is the `id` of the acting `Site`, and ownership checks
    compare the target resource's `site_id` — or the `id` of the site named
    directly in the path — to `X-User-ID`."

    Design: Corner/validations/a_pump_terminal_cannot_authorize_a_redemption_for_another_site
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    grocery_id = program["grocery"]["id"]
    observed_version = fixtures.member_version(member_id)
    payload = factories.fuel_redemption_payload(
        member_id, fuel_id, "6660000001", 300, observed_version
    )

    validate_error(
        api_client.create_fuel_redemption(
            payload, make_pump_terminal_headers(grocery_id)
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    assert fixtures.get_member(member_id)["available_points"] == 300

    redemption = validate_success(
        api_client.create_fuel_redemption(
            payload, make_pump_terminal_headers(fuel_id)
        ),
        201,
    )

    assert redemption["points_debited_at_auth"] == 300
    assert fixtures.get_member(member_id)["available_points"] == 0


def test_the_recipient_relationship_answers_before_the_block_multiple_does():
    """A transfer that is both misdirected and misdenominated reports the
    relationship, and the amount rule only surfaces once the recipient is linked.

    PRD: "Four business rules apply beyond the generic ladder, and their relative
    order matters."

    PRD: "The **recipient relationship** comes next: the recipient must hold a
    linkage in `ACTIVE` status to the same household as the sender, and
    `recipient_member_id` must not equal the sending `member_id`."

    PRD: "The **amount granularity** comes next: `points` must be a positive whole
    multiple of the banner's `points_per_discount_block`, so at the default block
    size a transfer moves 100, 200, 300 points and so on, and never 150."

    Design: Corner/validations/transfer_recipient_membership_is_checked_before_the_block_multiple_rule
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    sender_id = program["member"]["id"]
    sender_headers = make_member_headers(sender_id)
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(
        program["household"]["id"], housemate["id"], "SECONDARY", activate=True
    )
    stranger = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000008", card_number="4100000000000008"
    )

    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, stranger["id"], 150),
            sender_headers,
        ),
        ApiErrorId.ERR_RECIPIENT_NOT_IN_HOUSEHOLD.value,
    )
    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, sender_id, 100),
            sender_headers,
        ),
        ApiErrorId.ERR_RECIPIENT_NOT_IN_HOUSEHOLD.value,
    )
    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, housemate["id"], 150),
            sender_headers,
        ),
        ApiErrorId.ERR_INVALID_TRANSFER_AMOUNT.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": sender_id, "entry_type": "TRANSFER_OUT"}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.get_member(sender_id)["available_points"] == 300


def test_the_count_limit_answers_before_the_emptied_balance_does():
    """Three transfers exhaust both the allowance and the balance, and the fourth
    is refused for the allowance.

    The transfer that reaches the allowance also raises an `OPEN` `RAPID_TRANSFER`
    signal, and that lock is evaluated ahead of the count limit; the signal is
    therefore cleared first so that the count limit is the rule left to fire.

    PRD: "The **fraud lock** comes first: the sending member's household must
    carry fewer than two fraud signals in `OPEN` status, and none of its open
    signals may have a `signal_type` of `RAPID_TRANSFER` or `ALT_ID_SHARING`."

    PRD: "When the transfer brings the household's count of `TRANSFER_OUT` rows
    against the open cycle up to the banner's `max_transfers_per_cycle`, a fraud
    signal is appended for that household with `signal_type` `RAPID_TRANSFER`,
    `severity_weight` 25, `source` `SYSTEM` and `status` `OPEN`, and the
    household's `fraud_score` is recomputed — which may itself freeze the
    household, as §3.9 describes."

    PRD: "The **per-cycle count limit** comes last of the four: the sender's
    household must have recorded fewer than the banner's `max_transfers_per_cycle`
    `TRANSFER_OUT` ledger rows against the currently open cycle."

    PRD: "Separately, the sender's `available_points` must be at least the
    requested `points`, or the transfer fails with `ERR_INSUFFICIENT_POINTS`; and
    the transfer also requires a banner that is `ACTIVE`, a cycle that is `OPEN`
    and containing the logical clock, and no frozen household reachable from the
    sender."

    Design: Corner/validations/the_fourth_transfer_in_a_cycle_is_refused_before_the_balance_is_consulted
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300,
        alt_id="6660000001",
        banner_code="CORE",
        name="Corner Banner",
        max_transfers_per_cycle=3,
    )
    sender_id = program["member"]["id"]
    household_id = program["household"]["id"]
    sender_headers = make_member_headers(sender_id)
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(household_id, housemate["id"], "SECONDARY", activate=True)
    for _ in range(3):
        fixtures.transfer_points(
            sender_id, housemate["id"], 100, headers=sender_headers
        )

    open_signals, signal_meta = validate_paginated(
        api_client.list_household_fraud_signals(
            household_id, ADMIN, {"status": "OPEN", "signal_type": "RAPID_TRANSFER"}
        )
    )
    assert signal_meta["total_count"] == 1
    fixtures.clear_signal(open_signals[0]["id"])

    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, housemate["id"], 100),
            sender_headers,
        ),
        ApiErrorId.ERR_TRANSFER_LIMIT_EXCEEDED.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": sender_id, "entry_type": "TRANSFER_OUT"}
        )
    )
    assert meta["total_count"] == 3
    assert fixtures.get_member(sender_id)["available_points"] == 0
    assert fixtures.get_member(housemate["id"])["available_points"] == 300
    assert fixtures.get_household(household_id)["aggregate_available_points"] == 300


def test_the_tier_ceiling_bites_at_proposal_and_the_tier_authority_at_approval():
    """Six hundred points cannot be claimed under the lowest tier, and the tier
    that does carry them cannot be signed by a supervisor.

    PRD: "The magnitude of the proposal must be within that tier's ceiling:
    `TIER1` permits a magnitude up to and including 500 points, `TIER2` up to and
    including 5,000 points, and `TIER3` is unbounded."

    PRD: "A successful proposal writes `proposed_points_delta`, `authority_tier`
    and `proposed_by_user_id` — the latter being the acting `X-User-ID` — and moves
    the dispute to `ADJUSTMENT_PROPOSED`."

    PRD: "The tier then decides who may act at all — a `TIER3` proposal requires
    the acting `X-User-Role` to be `ProgramAdmin`, while `TIER1` and `TIER2` accept
    `LoyaltySupervisor` or `ProgramAdmin`, and a violation is
    `ERR_TIER_AUTHORITY_REQUIRED`."

    PRD: "The dispute then records `applied_ledger_entry_id` as the new row's
    identifier, `approved_by_user_id` as the acting `X-User-ID`, `resolved_at` from
    the logical clock, and `status` `RESOLVED_UPHELD`."

    Design: Corner/validations/adjustment_authority_ceiling_and_tier_are_enforced_at_different_steps
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

    validate_error(
        api_client.propose_dispute_adjustment(
            dispute["id"], factories.propose_adjustment_payload(600, "TIER1"), ANALYST
        ),
        ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_AUTHORITY.value,
    )
    assert (
        validate_success(api_client.get_point_dispute(dispute["id"], ADMIN))["status"]
        == "INVESTIGATING"
    )

    proposed = fixtures.propose_adjustment(dispute["id"], 600, "TIER3")
    assert proposed["status"] == "ADJUSTMENT_PROPOSED"
    assert proposed["proposed_by_user_id"] == "analyst-1"

    validate_error(
        api_client.approve_dispute_adjustment(dispute["id"], SUPERVISOR),
        ApiErrorId.ERR_TIER_AUTHORITY_REQUIRED.value,
    )
    _blocked, blocked_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "ADJUSTMENT"}
        )
    )
    assert blocked_meta["total_count"] == 0

    upheld = fixtures.approve_adjustment(dispute["id"], headers=ADMIN)

    assert upheld["status"] == "RESOLVED_UPHELD"
    assert upheld["applied_ledger_entry_id"] is not None
    assert upheld["approved_by_user_id"] == "admin-1"
    assert fixtures.get_member(member_id)["available_points"] == 800
