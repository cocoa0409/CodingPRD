"""CRUD, listing, immutability, RBAC, OCC concurrency, versioning, consistency."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_jurisdiction_payload,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_installment_plan_payload,
    create_contest_request_payload,
    create_schedule_payload,
    create_decide_payload,
    make_driver_headers,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    create_jurisdiction,
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_driver_with_uphold,
    file_contest,
    set_clock,
    list_point_ledger,
    CLERK,
    HEARING,
)


# ─── entities section ────────────────────────────────────────────────────
def test_create_citation_returns_201_with_initial_fields(api):
    """PRD §3.2: "A new citation starts with `financial_status` of `DRAFT`,
    `adjudication_status` of `NONE`, `disposition` of `OPEN`, and `version` 1."

    Design: Corner/entities/create_citation_returns_201_with_initial_fields
    """
    jur, driver = setup_jurisdiction_and_driver()
    citation = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    assert citation["financial_status"] == "DRAFT"
    assert citation["adjudication_status"] == "NONE"
    assert citation["disposition"] == "OPEN"
    assert citation["version"] == 1
    assert citation["balance_cents"] == 0


def test_get_citation_not_found_returns_404(api):
    """PRD §2.8: "For any such path, the server validates each identifier in
    left-to-right order and rejects the first one that does not resolve with
    `ERR_NOT_FOUND` (HTTP 404) before evaluating any business rule."

    Design: Corner/entities/get_citation_not_found_returns_404
    """
    create_jurisdiction()
    res = api.get_citation(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_charge_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Request-body well-formedness — required fields present, enum values
    legal, numeric fields non-negative where required, and `citation_number` and
    `license_number` unique within their jurisdiction — is enforced with
    `ERR_INVALID_REQUEST` (HTTP 400); logically this body check sits immediately
    after authentication and before resource existence, even though it is the
    lowest-numbered constraint in the rule table."
    PRD §3.3: "While a citation is still a `DRAFT`, a clerk attaches one or more
    **CitationCharge** line items, each a vehicle-code `violation_code`, a
    human-readable `description`, a statutory `base_fine_cents`, and the `points`
    (0, 1, or 2) the violation carries on the DMV ledger."

    Design: Corner/entities/create_charge_missing_required_field_returns_invalid_request
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    # Omit base_fine_cents.
    res = api.create_charge(
        {"citation_id": cit["id"], "violation_code": "VC22350",
         "description": "Unsafe speed", "points": 1},
        CLERK,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_citations_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "Citations are readable by any role and can be listed and filtered by
    `driver_id`, `citation_number`, or `financial_status`."

    Design: Corner/entities/list_citations_paginated_envelope
    """
    jur, driver = setup_jurisdiction_and_driver()
    api.create_citation(create_citation_payload(driver["id"]), CLERK)
    api.create_citation(create_citation_payload(driver["id"]), CLERK)
    data, meta = validate_paginated(api.list_citations(CLERK, params={"driver_id": driver["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(c["driver_id"] == driver["id"] for c in data)


def test_immutable_point_ledger_entry_no_version_field(api):
    """PRD §2.4: "A `PointLedgerEntry` is an append-and-mask audit record rather than
    a mutable resource; it carries only `id` and `created_at`. It has no `updated_at`
    and no `version`."

    Design: Corner/entities/immutable_point_ledger_entry_no_version_field
    """
    jur, driver, cit = setup_driver_with_uphold(points=1)
    entries = list_point_ledger(driver_id=driver["id"])
    active = [e for e in entries if e["state"] == "ACTIVE"]
    assert len(active) == 1
    entry = active[0]
    assert entry["points"] == 1
    assert "version" not in entry
    assert "updated_at" not in entry


# ─── state_machines section ──────────────────────────────────────────────
def test_assess_twice_second_returns_invalid_state(api):
    """PRD §3.3: "it must currently be in `DRAFT`, else the transition is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assess_twice_second_returns_invalid_state
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    res = api.assess_citation(cit["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE")


def test_assess_without_charges_returns_no_charges(api):
    """PRD §3.3: "The citation must already carry at least one charge — an attempt to
    assess a citation with no charges is rejected with `ERR_NO_CHARGES` — and it must
    currently be in `DRAFT`, else the transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assess_without_charges_returns_no_charges
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    res = api.assess_citation(cit["id"], CLERK)
    validate_error(res, "ERR_NO_CHARGES")


def test_void_terminal_then_assess_returns_invalid_state(api):
    """PRD §3.3: "it must currently be in `DRAFT`, else the transition is rejected
    with `ERR_INVALID_STATE`."
    PRD §3.10: "A void sets `financial_status` to `VOID`, closes the `disposition`,
    and — when voiding from `ASSESSED` — cascades to release any open hold for the
    citation and quash any active warrant."

    Design: Corner/state_machines/void_terminal_then_assess_returns_invalid_state
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    voided = validate_success(api.void_citation(cit["id"], CLERK), 200)
    assert voided["financial_status"] == "VOID"
    res = api.assess_citation(cit["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE")


# ─── endpoints section ───────────────────────────────────────────────────
def test_get_charges_filtered_list_reverse_reachability(api):
    """PRD §3.3: "Charges are immutable once created and can be listed by
    `citation_id`."

    Design: Corner/endpoints/get_charges_filtered_list_reverse_reachability
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC22107", description="Turn",
            base_fine_cents=5000, points=0,
        ),
        CLERK,
    )
    data, meta = validate_paginated(api.list_charges(CLERK, params={"citation_id": cit["id"]}))
    assert meta["total_count"] == 2
    assert all(c["citation_id"] == cit["id"] for c in data)


# ─── errors section ──────────────────────────────────────────────────────
def test_missing_auth_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/missing_auth_returns_401
    """
    jur = create_jurisdiction()
    res = api.get_jurisdiction(jur["id"], headers={})
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


# ─── rbac section ────────────────────────────────────────────────────────
def test_driver_cannot_assess_citation(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: assess is authorized for CourtClerk only.

    Design: Corner/rbac/driver_cannot_assess_citation
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    res = api.assess_citation(cit["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_court_clerk_cannot_decide_contest(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: decide is authorized for HearingOfficer only.

    Design: Corner/rbac/court_clerk_cannot_decide_contest
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    contest = file_contest(cit["id"], driver["id"])
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-01T00:00:00Z"), CLERK)
    res = api.decide_contest(contest["id"], create_decide_payload("DISMISS"), CLERK)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


# ─── cross_cutting (OCC + versioning + immediate consistency) ────────────
def test_occ_plan_create_stale_version(api):
    """PRD §2.6: "Before the plan is built, the server compares
    `expected_citation_version` against the citation's current `version`. If they do
    not match ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no
    plan is created."

    Design: Corner/cross_cutting/occ_plan_create_stale_version
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    stale_version = cit["version"]
    # First create succeeds and advances Citation.version.
    validate_success(
        api.create_installment_plan(
            cit["id"], create_installment_plan_payload(4, stale_version),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # Second create reuses the now-stale version.
    res = api.create_installment_plan(
        cit["id"], create_installment_plan_payload(6, stale_version),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    plans = validate_success(
        api.list_installment_plans(CLERK, params={"citation_id": cit["id"], "status": "ACTIVE"}), 200
    )
    rows = plans if isinstance(plans, list) else plans.get("items", [])
    assert len(rows) == 1


def test_occ_plan_create_correct_version_supersedes_prior(api):
    """PRD §2.6: "The create request must carry `expected_citation_version`, the
    `version` of the target citation the client last observed."
    PRD §3.5: "creating one supersedes any prior active plan: that prior plan moves
    from `ACTIVE` to `SUPERSEDED` and its still-`SCHEDULED` installments flip to
    `MISSED`, and the citation's `version` advances by one."

    Design: Corner/cross_cutting/occ_plan_create_correct_version_supersedes_prior
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    plan_a = validate_success(
        api.create_installment_plan(
            cit["id"], create_installment_plan_payload(4, cit["version"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    refreshed = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    plan_b = validate_success(
        api.create_installment_plan(
            cit["id"], create_installment_plan_payload(6, refreshed["version"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    assert plan_b["status"] == "ACTIVE"
    a_after = validate_success(
        api.get_installment_plan(plan_a["id"], make_driver_headers(driver["id"])), 200
    )
    assert a_after["status"] == "SUPERSEDED"


def test_version_increments_on_each_citation_mutation(api):
    """PRD §2.4: "an integer `version` that begins at 1 and increases by exactly one
    on each mutation of the resource."
    PRD §3.3: "the citation's `version` increases by one."
    PRD §3.4: "`amount_paid_cents` and `balance_cents` are recomputed and the
    citation's `version` advances by one."

    Design: Corner/cross_cutting/version_increments_on_each_citation_mutation
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    assert cit["version"] == 1
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    assert assessed["version"] == 2
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(10000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    after = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert after["version"] == 3


# ─── consistency_model section ───────────────────────────────────────────
def test_immediate_balance_visible_after_payment(api):
    """PRD §3.4: "A posted payment is recorded with `status` `POSTED` and a
    server-stamped `posted_at`, after which `amount_paid_cents` and `balance_cents`
    are recomputed and the citation's `version` advances by one."
    PRD §2.7: "no client ever has to issue a follow-up call to keep derived fields
    consistent — the server reconciles ... citation balances in the same transaction
    as the triggering write."

    Design: Corner/consistency_model/immediate_balance_visible_in_payment_response_chain
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(9000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert citation["amount_paid_cents"] == 9000
    assert citation["balance_cents"] == 20000
    assert citation["financial_status"] == "PARTIALLY_PAID"
