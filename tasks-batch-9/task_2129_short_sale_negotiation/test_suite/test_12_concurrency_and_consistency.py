"""Optimistic concurrency on the case and the offer, sheet supersession, version
bookkeeping, and the immediacy of every cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    case_version,
    create_case,
    create_junior_lien_payload,
    create_net_sheet_payload,
    is_iso8601_timestamp,
    issue_approval_letter_payload,
    lien_response_payload,
    offer_version,
    set_clock,
    setup_case_with_lien,
    setup_case_with_submitted_offer,
    setup_ready_for_issuance,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
HOLDER = TEST_USERS["junior_lien_holder_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]


def test_second_issuance_on_a_stale_case_version_is_refused(api):
    """PRD §2.8: "A newly issued letter legitimately supersedes the servicer's earlier
    view of the file — the offer it accepts, the junior-lien ledger it prices, and the
    minimum acceptable net it clears are all case-level state — so if the case's
    `version` has advanced since the client last read it, the client is working from a
    view of the file that no longer holds and the issuance is refused with
    `ERR_STALE_CASE_VERSION` and HTTP 412. Successful issuance itself increments the
    case's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_case_version_on_second_approval_letter_returns_412
    """
    scenario = setup_ready_for_issuance()
    case_id = scenario["case"]["id"]
    read_version = case_version(case_id)

    letter = validate_success(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(scenario["offer"]["id"], read_version, conditions=[]),
            ANALYST,
        ),
        201,
    )

    # The first issuance advanced the case's version, so the same echo is now stale.
    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], read_version,
                approved_net_proceeds_cents=22_500_000, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
    )

    rows, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == letter["id"]
    assert rows[0]["approved_net_proceeds_cents"] == 22_122_539
    assert rows[0]["status"] == "ACTIVE"


def test_second_net_sheet_on_a_stale_offer_version_is_refused(api):
    """PRD §2.8: "**Preparing a net sheet** requires the request body to carry
    `expected_offer_version`, likewise non-optional, whose value must equal the current
    `version` of the offer named in the path."
    PRD §2.8: "A mismatch is refused with `ERR_STALE_OFFER_VERSION` and HTTP 412.
    Successful preparation increments the offer's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_offer_version_on_second_net_sheet_returns_412
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]
    read_version = offer_version(offer_id)

    first = validate_success(
        api.create_net_sheet(
            offer_id, create_net_sheet_payload("PRELIMINARY", read_version), NEG
        ),
        201,
    )

    validate_error(
        api.create_net_sheet(
            offer_id, create_net_sheet_payload("PRELIMINARY", read_version), NEG
        ),
        ApiErrorId.ERR_STALE_OFFER_VERSION.value,
    )

    sheets = validate_success(api.list_offer_net_sheets(offer_id, NEG), 200)
    assert len(sheets) == 1
    assert sheets[0]["id"] == first["id"]
    assert sheets[0]["status"] == "CURRENT"


def test_a_new_sheet_supersedes_the_prior_sheet_of_its_own_variant(api):
    """PRD §3.8: "Preparation stamps `prepared_by_user_id`, births the sheet in `CURRENT`,
    demotes any prior sheet on that offer **of the same variant** that was `CURRENT` to
    `SUPERSEDED` — sheets of the other variant are untouched — and increments the parent
    offer's `version`."
    PRD §3.8: "A sheet is `SUPERSEDED` when a newer sheet of its own variant replaces it
    and `STALE` when an input it depended on moved."

    Design: Corner/cross_cutting_complexity_layers/net_sheet_supersedes_prior_sheet_of_the_same_variant
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]
    first = validate_success(
        api.create_net_sheet(
            offer_id, create_net_sheet_payload("PRELIMINARY", offer_version(offer_id)), NEG
        ),
        201,
    )

    second = validate_success(
        api.create_net_sheet(
            offer_id,
            create_net_sheet_payload(
                "PRELIMINARY", offer_version(offer_id), property_tax_arrears_cents=500_000
            ),
            NEG,
        ),
        201,
    )

    sheets = validate_success(api.list_offer_net_sheets(offer_id, NEG), 200)
    by_id = {sheet["id"]: sheet for sheet in sheets}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "CURRENT"
    assert second["property_tax_arrears_cents"] == 500_000

    current = validate_success(
        api.list_offer_net_sheets(offer_id, NEG, params={"status": "CURRENT"}), 200
    )
    assert len(current) == 1


def test_case_version_advances_by_one_per_mutation(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current
    instant on every mutation of that resource, and `version`, an integer that starts at 1
    when the resource is created and increases by exactly 1 on every mutation."
    PRD §3.7: "Creation raises the case's `junior_lien_count` by one, starts the lien at
    `IDENTIFIED` with `demand_cents` null and `approved_contribution_cents` at 0."

    Design: Corner/cross_cutting_complexity_layers/case_version_increments_by_one_on_each_mutation
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    before = validate_success(api.get_case(case["id"], NEG), 200)
    assert before["version"] == 1

    validate_success(
        api.create_junior_lien(case["id"], create_junior_lien_payload(), NEG), 201
    )

    after = validate_success(api.get_case(case["id"], NEG), 200)
    assert after["version"] == 2, (
        f"the case's version must advance by exactly 1, got {after['version']}"
    )
    assert after["junior_lien_count"] == 1
    assert is_iso8601_timestamp(after["updated_at"]), (
        "updated_at is refreshed alongside the version bump"
    )


def test_a_cascade_is_visible_in_the_response_that_triggered_it(api):
    """PRD §2.9: "Every hop runs inside the request that triggered it, before the response
    is written."
    PRD §3.7: "`junior_contribution_total_cents` is always the sum of
    `approved_contribution_cents` over the liens on that case whose status is `APPROVED`;
    liens in any other status contribute nothing."

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_response
    """
    case, lien = setup_case_with_lien(stage="DEMAND_SENT")
    before = validate_success(api.get_case(case["id"], NEG), 200)
    assert before["junior_contribution_total_cents"] == 0

    approved = validate_success(
        api.respond_to_lien(
            lien["id"],
            lien_response_payload("APPROVE", contribution_cents=600_000),
            HOLDER,
        ),
        200,
    )

    assert approved["status"] == "APPROVED"
    assert approved["approved_contribution_cents"] == 600_000

    after = validate_success(api.get_case(case["id"], NEG), 200)
    assert after["junior_contribution_total_cents"] == 600_000, (
        "the derived total converges without any second call"
    )
