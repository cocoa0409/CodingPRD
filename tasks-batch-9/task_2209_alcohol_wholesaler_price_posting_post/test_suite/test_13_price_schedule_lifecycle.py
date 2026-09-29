"""Price schedule state machine: birth, filing, certification, withdrawal and the posting run.

Every test builds its own program, wholesaler, staff, brand and schedule through
PRD-declared endpoints, because the server is restarted against an empty database
before each test.
"""

from test_helpers import (
    certify_schedule,
    create_posting_run_payload,
    create_price_schedule_payload,
    create_retailer_invoice_payload,
    new_item,
    new_schedule,
    new_tier,
    read_item,
    read_schedule,
    read_tier,
    read_wholesaler,
    regulator_headers,
    return_for_correction_payload,
    run_posting,
    set_clock,
    setup_certified_schedule,
    setup_draft_schedule,
    setup_licensee_base,
    setup_submitted_schedule,
    submit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_schedule,
)


def test_01_price_schedule_and_retailer_invoice_are_born_in_their_declared_initial_states(api):
    """PRD §3.3: "A schedule always begins in `DRAFT`, with `filed_at`,
    `filed_by_user_id`, `certified_at`, `certified_by_user_id`,
    `hold_window_ends_at`, `return_reason` and `superseded_by_schedule_id` all
    unset, with `is_late` `false`, and with `return_count`, `correction_count`
    and `item_count` all 0."
    PRD §3.8: "A new invoice has `validation_status` `DRAFT` and `audit_status`
    `NOT_AUDITED`, an unset `audit_id`, and `line_count`, `subtotal_cents`,
    `surcharge_cents`, `total_cents`, `total_allowance_cents`,
    `off_posted_line_count` and `total_variance_cents` all 0."

    Design: Corner/state_machines/price_schedule_and_retailer_invoice_are_born_in_their_declared_initial_states
    """
    scene = setup_licensee_base(with_certifier=False, with_brand=False)

    schedule = validate_success(
        api.create_price_schedule(
            create_price_schedule_payload(
                scene["wholesaler"]["id"], scene["program"]["id"], posting_month="2026-09"
            ),
            scene["agent_headers"],
        ),
        201,
    )
    invoice = validate_success(
        api.create_retailer_invoice(
            create_retailer_invoice_payload(
                scene["wholesaler"]["id"],
                "2026-08-15T00:00:00Z",
                retailer_license_number="R-500",
            ),
            scene["agent_headers"],
        ),
        201,
    )

    assert schedule["status"] == "DRAFT", (
        f"a new price schedule must begin in DRAFT, got {schedule['status']!r}"
    )

    assert invoice["validation_status"] == "DRAFT", (
        f"a new invoice must begin with validation_status DRAFT, "
        f"got {invoice['validation_status']!r}"
    )
    assert invoice["audit_status"] == "NOT_AUDITED", (
        f"a new invoice must begin with audit_status NOT_AUDITED, "
        f"got {invoice['audit_status']!r}"
    )
    assert invoice.get("audit_id") is None, (
        f"a new invoice's audit_id must be unset, got {invoice.get('audit_id')!r}"
    )
    for field in (
        "line_count",
        "subtotal_cents",
        "surcharge_cents",
        "total_cents",
        "total_allowance_cents",
        "off_posted_line_count",
        "total_variance_cents",
    ):
        assert invoice[field] == 0, (
            f"a new invoice's {field} must be 0, got {invoice[field]!r}"
        )


def test_02_price_schedule_submit_moves_draft_to_submitted_and_stamps_the_filing_agent(api):
    """PRD §3.3: "Filing sets `filed_at` to the current server time, sets
    `filed_by_user_id` to the acting licensee user, and advances the schedule's
    `version` by 1."
    PRD §3.3: "`is_late` is set to `true` when `filed_at` is strictly after the
    deadline instant and to `false` otherwise; a `filed_at` exactly equal to the
    deadline instant is on time."
    PRD §3.3: "When `is_late` comes out `false`, none of this happens: no counter
    moves, no penalty accrues, and the wholesaler's `version` and `updated_at`
    are left exactly as they were."
    PRD §3.3: "Items remain `DRAFT` right through submission; it is
    certification, not filing, that posts them."

    Design: Corner/state_machines/price_schedule_submit_moves_draft_to_submitted_and_stamps_the_filing_agent
    """
    scene = setup_licensee_base()
    setup_draft_schedule(scene, posting_month="2026-09")

    data = validate_success(
        api.submit_price_schedule(scene["schedule"]["id"], scene["agent_headers"]), 200
    )

    assert data["status"] == "SUBMITTED", (
        f"submit must move the schedule to SUBMITTED, got {data['status']!r}"
    )
    assert data["filed_at"] == "2026-08-01T00:00:00.000Z", (
        f"filed_at must be the logical clock instant 2026-08-01T00:00:00.000Z, "
        f"got {data['filed_at']!r}"
    )
    assert data["filed_by_user_id"] == scene["agent"]["id"], (
        f"filed_by_user_id must be the acting licensee user {scene['agent']['id']}, "
        f"got {data['filed_by_user_id']!r}"
    )
    assert data["is_late"] is False, (
        "a filing at 2026-08-01, before the 2026-09-10 deadline instant, is on time"
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["late_filing_count"] == 0, (
        f"an on-time filing must not move late_filing_count, "
        f"got {wholesaler['late_filing_count']}"
    )
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0, (
        f"an on-time filing must accrue no late filing penalty, "
        f"got {wholesaler['late_filing_penalty_accrued_cents']}"
    )
    assert wholesaler["penalty_exposure_cents"] == 0, (
        f"penalty_exposure_cents must remain 0, got {wholesaler['penalty_exposure_cents']}"
    )

    item = read_item(scene["items"][0]["id"])
    assert item["status"] == "DRAFT", (
        f"submission does not post items; the item must stay DRAFT, got {item['status']!r}"
    )


def test_03_price_schedule_submit_on_an_already_submitted_schedule_returns_invalid_state(api):
    """PRD §2.10: "The target entity is in a state from which the requested
    transition is defined."
    PRD §2.10: "Otherwise `ERR_INVALID_STATE` (409). Applies to every transition
    endpoint plus `POST /hold-amendments`, `POST /error-corrections` and
    `POST /invoice-lines`."
    PRD §2.5: "Conversely, a record whose stored fields are not changed by a
    request keeps its `updated_at` and its `version` untouched."

    Design: Corner/state_machines/price_schedule_submit_on_an_already_submitted_schedule_returns_invalid_state
    """
    scene = setup_submitted_schedule(posting_month="2026-09")
    version_after_first_submit = scene["schedule"]["version"]

    set_clock("2026-09-20T00:00:00Z")

    response = api.submit_price_schedule(scene["schedule"]["id"], scene["agent_headers"])
    assert response.status_code == 409, (
        f"re-submitting a SUBMITTED schedule must be a 409 conflict, "
        f"got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    schedule = read_schedule(scene["schedule"]["id"])
    assert schedule["filed_at"] == "2026-08-01T00:00:00.000Z", (
        f"the refused submit must not restamp filed_at, got {schedule['filed_at']!r}"
    )
    assert schedule["is_late"] is False, (
        "the refused submit must not re-evaluate lateness against the moved clock"
    )
    assert schedule["version"] == version_after_first_submit, (
        f"a refused request changes no stored field, so version must stay "
        f"{version_after_first_submit}, got {schedule['version']}"
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["late_filing_count"] == 0, (
        f"no second filing occurred, so late_filing_count must stay 0, "
        f"got {wholesaler['late_filing_count']}"
    )
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0, (
        f"no late filing penalty may accrue from a refused submit, "
        f"got {wholesaler['late_filing_penalty_accrued_cents']}"
    )


def test_04_price_schedule_certify_directly_from_draft_returns_invalid_state(api):
    """PRD §3.4: "The schedule must of course be in `SUBMITTED`; otherwise
    `ERR_INVALID_STATE` is returned at priority 8, ahead of all three."
    PRD §3.4: "Certification stamps `certified_at` with the current server time,
    records the acting user in `certified_by_user_id`, and computes
    `hold_window_ends_at` as `certified_at` advanced by the program's
    `hold_window_days` multiplied by 86,400 seconds."

    Design: Corner/state_machines/price_schedule_certify_directly_from_draft_returns_invalid_state
    """
    scene = setup_licensee_base()
    setup_draft_schedule(scene, posting_month="2026-09")

    response = api.certify_price_schedule(
        scene["schedule"]["id"], scene["certifier_headers"]
    )
    assert response.status_code == 409, (
        f"certifying a DRAFT schedule must be a 409 conflict, got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    schedule = read_schedule(scene["schedule"]["id"])
    assert schedule["status"] == "DRAFT", (
        f"the refused certify must leave the schedule in DRAFT, got {schedule['status']!r}"
    )
    assert schedule.get("certified_at") is None, (
        f"certified_at must stay unset, got {schedule.get('certified_at')!r}"
    )
    assert schedule.get("certified_by_user_id") is None, (
        f"certified_by_user_id must stay unset, got {schedule.get('certified_by_user_id')!r}"
    )
    assert schedule.get("hold_window_ends_at") is None, (
        f"hold_window_ends_at must stay unset, got {schedule.get('hold_window_ends_at')!r}"
    )

    item = read_item(scene["items"][0]["id"])
    assert item["status"] == "DRAFT", (
        f"no item may be posted by a refused certify, got {item['status']!r}"
    )
    assert item.get("certified_case_price_cents") is None, (
        f"certified_case_price_cents must stay unset, "
        f"got {item.get('certified_case_price_cents')!r}"
    )


def test_05_withdrawn_price_schedule_is_terminal_and_every_further_trigger_is_refused(api):
    """PRD §3.3: "`WITHDRAWN` is terminal for a schedule."
    PRD §3.3: "Withdrawal moves every one of the schedule's items to `WITHDRAWN`
    regardless of the status each item was in, and advances the schedule's
    `version` by 1."
    PRD §3.3: "A `ComplianceOfficer` who finds a filed schedule deficient sends
    it back: the `SUBMITTED → DRAFT` transition requires the schedule to be in
    `SUBMITTED` (otherwise `ERR_INVALID_STATE`), records the supplied
    `return_reason`, increments `return_count` by 1, and advances the schedule's
    `version` by 1."
    PRD §3.4: "The schedule must of course be in `SUBMITTED`; otherwise
    `ERR_INVALID_STATE` is returned at priority 8, ahead of all three."

    Design: Corner/state_machines/withdrawn_price_schedule_is_terminal_and_every_further_trigger_is_refused
    """
    scene = setup_submitted_schedule(posting_month="2026-09")
    withdrawn = withdraw_schedule(scene["schedule"]["id"], scene["agent_headers"])
    version_after_withdraw = withdrawn["version"]
    schedule_id = scene["schedule"]["id"]

    triggers = {
        "submit": api.submit_price_schedule(schedule_id, scene["agent_headers"]),
        "return-for-correction": api.return_price_schedule_for_correction(
            schedule_id,
            return_for_correction_payload("regulator wants a revision"),
            regulator_headers(),
        ),
        "certify": api.certify_price_schedule(schedule_id, scene["certifier_headers"]),
    }

    for name, response in triggers.items():
        assert response.status_code == 409, (
            f"{name} against a WITHDRAWN schedule must be a 409 conflict, "
            f"got {response.status_code}"
        )
        validate_error(response, "ERR_INVALID_STATE")

    schedule = read_schedule(schedule_id)
    assert schedule["status"] == "WITHDRAWN", (
        f"WITHDRAWN is terminal, got {schedule['status']!r}"
    )
    assert schedule["return_count"] == 0, (
        f"the refused return-for-correction must not increment return_count, "
        f"got {schedule['return_count']}"
    )
    assert schedule.get("return_reason") is None, (
        f"the refused return-for-correction must not record a return_reason, "
        f"got {schedule.get('return_reason')!r}"
    )
    assert schedule.get("certified_at") is None, (
        f"the refused certify must not stamp certified_at, got {schedule.get('certified_at')!r}"
    )
    assert schedule["version"] == version_after_withdraw, (
        f"three refused requests change no stored field, so version must stay "
        f"{version_after_withdraw}, got {schedule['version']}"
    )

    item = read_item(scene["items"][0]["id"])
    assert item["status"] == "WITHDRAWN", (
        f"the cascaded item must stay WITHDRAWN, got {item['status']!r}"
    )


def test_06_price_schedule_certify_cascades_every_draft_item_to_posted_and_snapshots_certified_prices(api):
    """PRD §3.4: "Certification stamps `certified_at` with the current server
    time, records the acting user in `certified_by_user_id`, and computes
    `hold_window_ends_at` as `certified_at` advanced by the program's
    `hold_window_days` multiplied by 86,400 seconds."
    PRD §3.4: "Every item of the schedule that is in `DRAFT` moves to `POSTED`,
    and for each such item the system snapshots the prices as filed:
    `case_price_cents` is copied into `certified_case_price_cents` and
    `unit_price_cents` into `certified_unit_price_cents`."
    PRD §3.4: "The schedule's own `version` is advanced by 1."
    PRD §2.7: "A three-day hold window is 259,200 seconds after `certified_at`;
    a fifteen-day correction window is 1,296,000 seconds after `certified_at`; a
    seven-day cooldown buffer is 604,800 seconds."

    Design: Corner/state_machines/price_schedule_certify_cascades_every_draft_item_to_posted_and_snapshots_certified_prices
    """
    item_specs = [
        {
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 120_000,
            "unit_price_cents": 11_000,
        },
        {
            "size_ml": 1000,
            "bottles_per_case": 6,
            "case_price_cents": 90_000,
            "unit_price_cents": 16_000,
        },
    ]
    scene = setup_submitted_schedule(posting_month="2026-09", item_specs=item_specs)
    version_after_submit = scene["schedule"]["version"]

    data = validate_success(
        api.certify_price_schedule(scene["schedule"]["id"], scene["certifier_headers"]),
        200,
    )

    assert data["status"] == "POSTED", (
        f"certify must move the schedule to POSTED, got {data['status']!r}"
    )
    assert data["certified_at"] == "2026-08-01T00:00:00.000Z", (
        f"certified_at must be the current server time 2026-08-01T00:00:00.000Z, "
        f"got {data['certified_at']!r}"
    )
    assert data["certified_by_user_id"] == scene["certifier"]["id"], (
        f"certified_by_user_id must be the acting certifying officer "
        f"{scene['certifier']['id']}, got {data['certified_by_user_id']!r}"
    )
    assert data["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        f"hold_window_ends_at must be certified_at plus 3 * 86,400 seconds, "
        f"got {data['hold_window_ends_at']!r}"
    )
    assert data["version"] == version_after_submit + 1, (
        f"certification advances the schedule version by exactly 1, expected "
        f"{version_after_submit + 1}, got {data['version']}"
    )
    assert data["item_count"] == 2, (
        f"item_count must track the two attached items, got {data['item_count']}"
    )

    first = read_item(scene["items"][0]["id"])
    assert first["status"] == "POSTED", (
        f"the 750ml item must be POSTED, got {first['status']!r}"
    )
    assert first["certified_case_price_cents"] == 120_000, (
        f"the 750ml item's certified_case_price_cents must snapshot 120000, "
        f"got {first['certified_case_price_cents']}"
    )
    assert first["certified_unit_price_cents"] == 11_000, (
        f"the 750ml item's certified_unit_price_cents must snapshot 11000, "
        f"got {first['certified_unit_price_cents']}"
    )

    second = read_item(scene["items"][1]["id"])
    assert second["status"] == "POSTED", (
        f"the 1000ml item must be POSTED, got {second['status']!r}"
    )
    assert second["certified_case_price_cents"] == 90_000, (
        f"the 1000ml item must snapshot its OWN case price 90000, "
        f"got {second['certified_case_price_cents']}"
    )
    assert second["certified_unit_price_cents"] == 16_000, (
        f"the 1000ml item must snapshot its OWN unit price 16000, "
        f"got {second['certified_unit_price_cents']}"
    )

    _, meta = validate_paginated(
        api.list_price_schedule_items(
            regulator_headers(),
            params={"schedule_id": scene["schedule"]["id"], "status": "POSTED"},
        )
    )
    assert meta["total_count"] == 2, (
        f"both items of the certified schedule must be POSTED, got {meta['total_count']}"
    )


def test_07_posting_run_deactivates_only_the_tiers_of_items_it_superseded(api):
    """PRD §3.7: "Every quantity discount tier of a superseded item that was
    `ACTIVE` moves to `INACTIVE` — the old tiers stop being usable for invoice
    pricing the instant their item is displaced."
    PRD §3.7: "Then, for each newly effective item, the run looks for the prior
    item in `EFFECTIVE` status carrying the same posting key and, when it finds
    one, moves that older item to `SUPERSEDED` and records the older item's
    identifier in the newer item's `supersedes_item_id`."
    PRD §3.5: "The tier's own price is derived, never supplied:
    `discounted_case_price_cents` is the item's `case_price_cents` multiplied by
    the quantity one minus `discount_pct`, rounded half up to whole cents."

    Design: Corner/state_machines/posting_run_deactivates_only_the_tiers_of_items_it_superseded
    """
    scene = setup_certified_schedule(posting_month="2026-09")
    september_item = scene["items"][0]
    september_tier = new_tier(
        september_item["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10
    )

    october_schedule = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-10",
    )
    october_item = new_item(
        october_schedule["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(october_schedule["id"], scene["agent_headers"])
    certify_schedule(october_schedule["id"], scene["certifier_headers"])

    set_clock("2026-10-01T00:00:00Z")
    run_posting(scene["program"]["id"])

    set_clock("2026-11-01T00:00:00Z")
    october_tier = new_tier(
        october_item["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10
    )

    validate_success(
        api.create_posting_run(
            create_posting_run_payload(scene["program"]["id"]), regulator_headers()
        ),
        200,
    )

    old_tier = read_tier(september_tier["id"])
    assert old_tier["status"] == "INACTIVE", (
        f"the tier of the superseded September item must move to INACTIVE, "
        f"got {old_tier['status']!r}"
    )
    assert old_tier["discounted_case_price_cents"] == 108_000, (
        f"the superseded item's tier price stays frozen at round_half_up(120000 * 0.90) "
        f"= 108000, got {old_tier['discounted_case_price_cents']}"
    )

    new_tier_read = read_tier(october_tier["id"])
    assert new_tier_read["status"] == "ACTIVE", (
        f"the tier of the newly effective October item must stay ACTIVE, "
        f"got {new_tier_read['status']!r}"
    )
    assert new_tier_read["discounted_case_price_cents"] == 112_500, (
        f"the October tier price must be round_half_up(125000 * 0.90) = 112500, "
        f"got {new_tier_read['discounted_case_price_cents']}"
    )

    _, meta_old = validate_paginated(
        api.list_quantity_discount_tiers(
            regulator_headers(),
            params={"item_id": september_item["id"], "status": "ACTIVE"},
        )
    )
    assert meta_old["total_count"] == 0, (
        f"the superseded item must retain no ACTIVE tier, got {meta_old['total_count']}"
    )

    rows, meta_active = validate_paginated(
        api.list_quantity_discount_tiers(regulator_headers(), params={"status": "ACTIVE"})
    )
    assert meta_active["total_count"] == 1, (
        f"exactly one tier in the program may remain ACTIVE, got {meta_active['total_count']}"
    )
    assert rows[0]["id"] == october_tier["id"], (
        f"the surviving ACTIVE tier must be the October item's tier "
        f"{october_tier['id']}, got {rows[0]['id']}"
    )
