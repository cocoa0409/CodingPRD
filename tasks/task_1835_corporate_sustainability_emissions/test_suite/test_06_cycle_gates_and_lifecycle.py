"""Reporting-cycle gates and lifecycle: lock preconditions, library pinning,
attestation, disclosure, terminal lockdown, and the cyclic reopen loop."""
from test_helpers import (
    ApiErrorId, create_activity_record_payload, create_approved_record,
    drive_cycle_to_locked, get_cycle, get_inventory_for_cycle,
    make_collecting_cycle, make_cycle, make_engagement, make_factor, make_site,
    recalc_inventory, setup_assured_cycle, setup_disclosed_cycle,
    setup_under_assurance_cycle, submit_record, transition_cycle,
    transition_payload, validate_error, validate_success,
)


def test_cycle_lock_rejected_with_open_records(api, manager_headers, steward_headers):
    """PRD §3.2: "Locking the cycle — `UNDER_REVIEW` to `LOCKED` — is the
    first hard gate, and its three checks run in this order: no activity
    record of the cycle may remain in `SUBMITTED` or `UNDER_REVIEW`
    (otherwise `ERR_OPEN_RECORDS_REMAIN`); every supplier engagement of the
    cycle must have reached `ACCEPTED` or `CLOSED_NO_DATA` (otherwise
    `ERR_OPEN_ENGAGEMENTS_REMAIN`); and the inventory must be `CURRENT`
    rather than `STALE` (otherwise `ERR_INVENTORY_STALE`)."

    Design: Corner/state_machines/cycle_lock_rejected_with_open_records
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    recalc_inventory(cycle["id"])
    transition_cycle(cycle["id"], "UNDER_REVIEW")

    resp = api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_RECORDS_REMAIN, 409)
    assert get_cycle(cycle["id"])["status"] == "UNDER_REVIEW"


def test_cycle_lock_rejected_with_open_engagements(api, manager_headers):
    """PRD §3.2: "every supplier engagement of the cycle must have reached
    `ACCEPTED` or `CLOSED_NO_DATA` (otherwise `ERR_OPEN_ENGAGEMENTS_REMAIN`)".

    Design: Corner/state_machines/cycle_lock_rejected_with_open_engagements
    """
    cycle = make_collecting_cycle()
    make_engagement(cycle["id"], contact_user_id="supplier-1")
    recalc_inventory(cycle["id"])
    transition_cycle(cycle["id"], "UNDER_REVIEW")

    resp = api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_ENGAGEMENTS_REMAIN, 409)
    assert get_cycle(cycle["id"])["status"] == "UNDER_REVIEW"


def test_cycle_lock_rejected_when_inventory_stale(api, manager_headers):
    """PRD §3.2: "and the inventory must be `CURRENT` rather than `STALE`
    (otherwise `ERR_INVENTORY_STALE`)." PRD §3.7: "Any mutation to the
    composition of the approved set — record approval or voiding, engagement
    respond, acceptance, or automatic closure, instrument retirement or
    void-retirement — drops a `CURRENT` inventory back to `STALE`."

    Design: Corner/state_machines/cycle_lock_rejected_when_inventory_stale
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    create_approved_record(cycle["id"], site["id"], factor["id"], quantity=10)
    # Approval marked the inventory STALE; deliberately skip recalculation.
    transition_cycle(cycle["id"], "UNDER_REVIEW")

    resp = api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVENTORY_STALE, 409)
    assert get_cycle(cycle["id"])["status"] == "UNDER_REVIEW"


def test_cycle_lock_pins_max_published_library_version(api, manager_headers):
    """PRD §3.2: "A successful lock pins the factor library:
    `pinned_library_version` is set to the highest `library_version` among
    `PUBLISHED` factors, or to 0 if none are published, and the inventory
    transitions from `CURRENT` to `FROZEN`."

    Design: Corner/state_machines/cycle_lock_pins_max_published_library_version
    """
    make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4, library_version=1,
    )
    make_factor(
        scope_category="SCOPE3_EEIO_SPEND", region_code="GLOBAL", unit="USD",
        value_tco2e_per_unit=0.0005, library_version=2,
    )
    cycle = make_collecting_cycle()
    recalc_inventory(cycle["id"])
    transition_cycle(cycle["id"], "UNDER_REVIEW")

    locked = validate_success(
        api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    )
    assert locked["status"] == "LOCKED"
    assert locked["pinned_library_version"] == 2, (
        "pin is the max library_version across PUBLISHED factors (1 and 2)"
    )
    assert get_inventory_for_cycle(cycle["id"])["status"] == "FROZEN"


def test_attest_requires_provider_role_and_statement(api, manager_headers, assurer_headers):
    """PRD §3.2: "Attestation belongs to the `AssuranceProvider` alone: they
    advance the cycle from `UNDER_ASSURANCE` to `ASSURED` by supplying a
    non-empty `assurance_statement`, which is stored on the cycle. An empty
    or missing statement fails with `ERR_INVALID_REQUEST`, and if the
    inventory is no longer `FROZEN` the attestation fails with
    `ERR_INVENTORY_STALE`." PRD §2.1: "individual workflow steps name a
    single permitted actor — only an `AssuranceProvider` may attest a cycle,
    only a `SustainabilityManager` may void an approved record — and a wrong
    actor is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/state_machines/attest_requires_provider_role_and_statement_then_stores_it
    """
    bundle = setup_under_assurance_cycle(quantity=100)
    cycle_id = bundle["cycle"]["id"]

    wrong_actor = api.transition_cycle(
        cycle_id, transition_payload("ASSURED", assurance_statement="x"), manager_headers
    )
    validate_error(wrong_actor, ApiErrorId.ERR_UNAUTHORIZED, 403)

    missing_statement = api.transition_cycle(
        cycle_id, transition_payload("ASSURED"), assurer_headers
    )
    validate_error(missing_statement, ApiErrorId.ERR_INVALID_REQUEST, 400)

    attested = validate_success(
        api.transition_cycle(
            cycle_id,
            transition_payload("ASSURED", assurance_statement="Limited assurance, ISAE 3410"),
            assurer_headers,
        )
    )
    assert attested["status"] == "ASSURED"
    assert attested["assurance_statement"] == "Limited assurance, ISAE 3410", (
        "the supplied assurance_statement is stored on the cycle"
    )


def test_cycle_cannot_skip_from_draft_to_locked(api, manager_headers):
    """PRD §3.2: "Naming a `to_state` that is not a legal successor of the
    cycle's current state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cycle_cannot_skip_from_draft_to_locked
    """
    cycle = make_cycle()
    resp = api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_cycle(cycle["id"])["status"] == "DRAFT"


def test_disclose_without_submitted_questionnaire_returns_error(api, manager_headers):
    """PRD §3.2: "Finally, the manager may move an `ASSURED` cycle to the
    terminal `DISCLOSED` state only once at least one questionnaire response
    for the cycle has been `SUBMITTED`; otherwise the gate fails with
    `ERR_NO_SUBMITTED_QUESTIONNAIRE`."

    Design: Corner/validations/disclose_without_submitted_questionnaire_returns_error
    """
    bundle = setup_assured_cycle(quantity=100)
    cycle_id = bundle["cycle"]["id"]
    resp = api.transition_cycle(cycle_id, transition_payload("DISCLOSED"), manager_headers)
    validate_error(resp, ApiErrorId.ERR_NO_SUBMITTED_QUESTIONNAIRE, 409)
    assert get_cycle(cycle_id)["status"] == "ASSURED"


def test_disclosed_cycle_terminal_lockdown(api, manager_headers, steward_headers):
    """PRD §3.2: "Finally, the manager may move an `ASSURED` cycle to the
    terminal `DISCLOSED` state only once at least one questionnaire response
    for the cycle has been `SUBMITTED`; otherwise the gate fails with
    `ERR_NO_SUBMITTED_QUESTIONNAIRE`." PRD §2.10: "State gates — the target
    entity's own state permits the requested transition
    (`ERR_INVALID_STATE`), and, for child mutations, the parent cycle sits in
    `DATA_COLLECTION` or `UNDER_REVIEW` (`ERR_CYCLE_NOT_COLLECTING`)."

    Design: Corner/state_machines/disclosed_cycle_terminal_lockdown
    """
    bundle = setup_disclosed_cycle()
    cycle = bundle["cycle"]
    assert cycle["status"] == "DISCLOSED"

    transition_attempt = api.transition_cycle(
        cycle["id"], transition_payload("UNDER_REVIEW"), manager_headers
    )
    validate_error(transition_attempt, ApiErrorId.ERR_INVALID_STATE, 409)

    create_attempt = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], bundle["site"]["id"], bundle["factor"]["id"],
            quantity=5, period_start="2026-03-01T00:00:00Z",
            period_end="2026-04-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_error(create_attempt, ApiErrorId.ERR_CYCLE_NOT_COLLECTING, 409)


def test_cycle_lock_reopen_lock_loop(api, manager_headers):
    """PRD §3.2: "The `LOCKED` to `UNDER_REVIEW` to `LOCKED` loop is legal
    and repeatable, and `pinned_library_version` is retained after a reopen
    for audit." PRD §3.7: "Cycle lock moves `CURRENT` to `FROZEN`, and
    either reopen edge moves `FROZEN` back to `STALE`."

    Design: Difficulty/non_linear_state_machine/cycle_lock_reopen_lock_loop
    """
    cycle = make_collecting_cycle()
    recalc_inventory(cycle["id"])
    drive_cycle_to_locked(cycle["id"])

    reopened = validate_success(
        api.transition_cycle(cycle["id"], transition_payload("UNDER_REVIEW"), manager_headers)
    )
    assert reopened["status"] == "UNDER_REVIEW", "LOCKED -> UNDER_REVIEW reopen is legal"
    assert get_inventory_for_cycle(cycle["id"])["status"] == "STALE", (
        "reopen moves the FROZEN inventory back to STALE"
    )

    recalc_inventory(cycle["id"])
    relocked = validate_success(
        api.transition_cycle(cycle["id"], transition_payload("LOCKED"), manager_headers)
    )
    assert relocked["status"] == "LOCKED", "the full LOCKED -> UNDER_REVIEW -> LOCKED loop is legal"


def test_cycle_reopen_retains_pinned_library_version(api, manager_headers):
    """PRD §3.2: "The `LOCKED` to `UNDER_REVIEW` to `LOCKED` loop is legal
    and repeatable, and `pinned_library_version` is retained after a reopen
    for audit."

    Design: Difficulty/non_linear_state_machine/cycle_lock_reopen_lock_loop
    """
    make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4, library_version=1,
    )
    make_factor(
        scope_category="SCOPE3_EEIO_SPEND", region_code="GLOBAL", unit="USD",
        value_tco2e_per_unit=0.0005, library_version=2,
    )
    cycle = make_collecting_cycle()
    recalc_inventory(cycle["id"])
    drive_cycle_to_locked(cycle["id"])
    assert get_cycle(cycle["id"])["pinned_library_version"] == 2

    reopened = transition_cycle(cycle["id"], "UNDER_REVIEW")
    assert reopened["pinned_library_version"] == 2, (
        "the pin is retained for audit after the reopen"
    )
    recalc_inventory(cycle["id"])
    relocked = transition_cycle(cycle["id"], "LOCKED")
    assert relocked["pinned_library_version"] == 2
