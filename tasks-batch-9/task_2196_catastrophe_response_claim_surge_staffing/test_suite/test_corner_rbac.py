"""§1.9 Scaffold Corner Design — section: rbac.

One test per non-stub design instance. These are deliberately negative tests: each
issues a request under a role or identity the endpoint does not permit and asserts
the denial plus the absence of any side effect.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_adjuster_headers,
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

MGR = make_catastrophe_manager_headers("mgr-01")
COORD = make_deployment_coordinator_headers("coord-01")
ALICE = make_claims_examiner_headers("examiner-alice")
BOB = make_claims_examiner_headers("examiner-bob")
CAROL = make_claims_examiner_headers("user-carol")
# The same opaque X-User-ID wearing the manager role, which is what the batch
# segregation-of-duties check compares against.
CAROL_AS_MANAGER = make_catastrophe_manager_headers("user-carol")
COMPLIANCE = make_compliance_officer_headers("compliance-01")
# POST /vendor-firms mints the row, so there is no firm id yet to bind the caller to.
REGISTRAR = make_vendor_coordinator_headers("vendor-registrar")


# ---------------------------------------------------------------------------
# Shared setup. The server restarts per test, so each test rebuilds from scratch.
# ---------------------------------------------------------------------------
def _declared_fl_event(api, cat_code):
    """A HURRICANE/FL event moved MONITORING → DECLARED with the clock at 2026-09-01."""
    validate_success(api.set_clock(CLOCK, MGR))
    event = validate_success(
        api.create_event(
            {
                "cat_code": cat_code,
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-09-01T00:00:00.000Z",
                "exposure_count": 1000,
                "avg_insured_value": 250000,
                "expected_severity_index": 0.1000,
            },
            MGR,
        ),
        201,
    )
    return validate_success(api.declare_event(event["id"], MGR))


def _fl_claim(api, event_id, policy_number):
    """A cat-coded INTAKE claim: reported 8000 against one DWELLING line
    300000 / 5000 / 120000."""
    return validate_success(
        api.create_claim(
            {
                "policy_number": policy_number,
                "loss_state": "FL",
                "loss_date_utc": "2026-09-02T00:00:00.000Z",
                "reported_loss_amount": 8000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 300000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 120000,
                    }
                ],
                "event_id": event_id,
            },
            ALICE,
        ),
        201,
    )


def _triaged_fl_claim(api, event_id, policy_number):
    """The same claim triaged: severity round(2.6667 * 1.15 + 20 * 0.1000, 2) = 5.07,
    tier FAST_TRACK, mode DESK (8000 <= 10000.00), case_reserve 115000 * 0.25 =
    28750.00, advance_cap round(34500.00 * 0.40, 2) = 13800.00."""
    claim = _fl_claim(api, event_id, policy_number)
    return validate_success(api.triage_claim(claim["id"], ALICE))


def _desk_adjuster(api, full_name="Dana Reyes", **overrides):
    payload = {
        "full_name": full_name,
        "employment_type": "STAFF",
        "home_state": "FL",
        "licensed_states": ["FL"],
        "license_expiry_utc": "2027-12-31T00:00:00.000Z",
        "max_open_claims": 5,
        "daily_rate": 700,
        "per_diem_rate": 100,
        "desk_certified": True,
        "aerial_certified": False,
    }
    payload.update(overrides)
    return validate_success(api.create_adjuster(payload, COORD), 201)


def _desk_assignment(api, claim_id, adjuster_id):
    """A SCHEDULED DESK assignment inside the already-open 2026-09-01 window. Desk
    assignments name no funding deployment."""
    return validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_id,
                "mode": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-02T00:00:00.000Z",
                "adjuster_id": adjuster_id,
            },
            COORD,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# corner_rbac_deployment_coordinator_denied_claim_triage
# ---------------------------------------------------------------------------
def test_a_deployment_coordinator_may_not_triage_a_claim(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A `DeploymentCoordinator` owns adjuster supply, housing logistics and
    inspection scheduling, and may not triage, pay or close claims."
    PRD §3.6: "Triage stamps `severity_score` and `triage_tier`, stamps `inspection_mode`,
    stamps `deadline_utc`, and appends an `INITIAL_CASE` entry to the reserve ledger whose
    case-reserve movement comes from the initial-reserve rule and whose paid movement is
    exactly 0.00, taking the next per-event sequence number."

    Design: Corner/rbac/corner_rbac_deployment_coordinator_denied_claim_triage
    """
    event = _declared_fl_event(api, "CAT-2026-114")
    claim = _fl_claim(api, event["id"], "POL-1001")

    validate_error(
        api.triage_claim(claim["id"], COORD), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
    )

    refreshed = validate_success(api.get_claim(claim["id"], ALICE))
    assert refreshed["handling_status"] == "INTAKE"
    assert_money_equals(refreshed["severity_score"], 0.00, "severity_score")
    assert refreshed["triage_tier"] is None
    # No INITIAL_CASE entry was appended.
    _, row_meta = validate_paginated(
        api.list_reserve_entries(ALICE, params={"claim_id": claim["id"]})
    )
    assert row_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# corner_rbac_claims_examiner_denied_event_declare
# ---------------------------------------------------------------------------
def test_a_claims_examiner_may_not_declare_an_event(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A `CatastropheManager` owns the event lifecycle, loss estimation and
    reserve governance: creating events, declaring them, activating surge, demobilizing,
    closing, minting loss-estimate snapshots, and accepting or rejecting file-transfer
    batches."
    PRD §3.1: "A newly registered event begins with `status` of `MONITORING`, a `posture`
    of `OPEN`, a `version` of 1, and a `declared_at_utc` of null."

    Design: Corner/rbac/corner_rbac_claims_examiner_denied_event_declare
    """
    validate_success(api.set_clock(CLOCK, MGR))
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-115",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-09-01T00:00:00.000Z",
                "exposure_count": 500,
                "avg_insured_value": 180000,
                "expected_severity_index": 0.0500,
            },
            MGR,
        ),
        201,
    )

    validate_error(
        api.declare_event(event["id"], ALICE), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
    )

    refreshed = validate_success(api.get_event(event["id"], MGR))
    assert refreshed["status"] == "MONITORING"
    assert refreshed["declared_at_utc"] is None
    assert refreshed["version"] == 1


# ---------------------------------------------------------------------------
# corner_rbac_catastrophe_manager_denied_adjuster_registration
# ---------------------------------------------------------------------------
def test_a_catastrophe_manager_can_read_the_roster_but_not_add_to_it(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "The six roles are `CatastropheManager`, `DeploymentCoordinator`,
    `ClaimsExaminer`, `ComplianceOfficer`, `Adjuster`, and `VendorCoordinator`. Their
    duties are deliberately disjoint."
    PRD §2.1: "A `DeploymentCoordinator` owns adjuster supply, housing logistics and
    inspection scheduling, and may not triage, pay or close claims."

    Design: Corner/rbac/corner_rbac_catastrophe_manager_denied_adjuster_registration
    """
    validate_success(api.set_clock(CLOCK, MGR))

    validate_error(
        api.create_adjuster(
            {
                "full_name": "Dana Reyes",
                "employment_type": "STAFF",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2027-12-31T00:00:00.000Z",
                "max_open_claims": 5,
                "daily_rate": 700,
                "per_diem_rate": 100,
                "desk_certified": True,
                "aerial_certified": False,
            },
            MGR,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # The role model is segregation of duties, not hierarchical override: the shared
    # read is permitted for the very role the exclusive write refused.
    rows, meta = validate_paginated(api.list_adjusters(MGR))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# corner_rbac_compliance_officer_denied_advance_payment_issuance
# ---------------------------------------------------------------------------
def test_a_compliance_officer_may_not_issue_advance_money(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A `ComplianceOfficer` owns regulatory bulletins and emergency licence
    waivers, and may not declare events, pay claims or schedule work."
    PRD §3.8: "Issuance creates the advance in `ISSUED`, refreshes the claim's
    `advance_cap`, and appends a `PAYMENT` ledger entry whose paid movement is the issued
    `amount` and whose case-reserve movement is the negation of that amount, recording
    that row's identifier in the advance's `reserve_entry_id`."

    Design: Corner/rbac/corner_rbac_compliance_officer_denied_advance_payment_issuance
    """
    event = _declared_fl_event(api, "CAT-2026-116")
    claim = _triaged_fl_claim(api, event["id"], "POL-1002")
    assert claim["triage_tier"] == "FAST_TRACK"
    assert_money_equals(claim["advance_cap"], 13800.00, "advance_cap")

    validate_error(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 1000, "basis": "STRUCTURE_PARTIAL"},
            COMPLIANCE,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, advance_meta = validate_paginated(
        api.list_advance_payments(ALICE, params={"claim_id": claim["id"]})
    )
    assert advance_meta["total_count"] == 0

    refreshed = validate_success(api.get_claim(claim["id"], ALICE))
    assert refreshed["payment_status"] == "NONE"
    assert_money_equals(refreshed["advance_paid_total"], 0.00, "advance_paid_total")
    assert_money_equals(refreshed["case_reserve"], 28750.00, "case_reserve")

    rows, row_meta = validate_paginated(
        api.list_reserve_entries(ALICE, params={"claim_id": claim["id"]})
    )
    assert row_meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"


# ---------------------------------------------------------------------------
# corner_rbac_vendor_coordinator_denied_dispatching_work_to_itself
# ---------------------------------------------------------------------------
def test_a_vendor_firm_may_not_dispatch_work_to_itself(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.9: "**Dispatching work** is a `ClaimsExaminer` action, since it is the claim
    that needs a tarp on its roof."
    PRD §3.9: "A created assignment is `DISPATCHED`, stamps `dispatched_at_utc` at the
    current logical-clock instant, records `EXPLICIT_VENDOR` or `SELECTOR_RANKED` in
    `selection_reason`, and triggers a recompute of the firm's `open_job_count`."

    Design: Corner/rbac/corner_rbac_vendor_coordinator_denied_dispatching_work_to_itself
    """
    event = _declared_fl_event(api, "CAT-2026-117")
    claim = _triaged_fl_claim(api, event["id"], "POL-1003")

    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Gulf Tarp Co",
                "vendor_type": "TARP",
                "service_states": ["FL"],
                "max_concurrent_jobs": 5,
                "performance_score": 90.00,
            },
            REGISTRAR,
        ),
        201,
    )
    firm = validate_success(
        api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, REGISTRAR)
    )
    assert firm["status"] == "ACTIVATED"

    # The firm is on the panel and has spare capacity, but it cannot hand itself a job.
    as_the_firm = make_vendor_coordinator_headers(firm["id"])
    validate_error(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 4000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm["id"],
            },
            as_the_firm,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, job_meta = validate_paginated(
        api.list_vendor_assignments(ALICE, params={"claim_id": claim["id"]})
    )
    assert job_meta["total_count"] == 0

    refreshed_firm = validate_success(api.get_vendor_firm(firm["id"], REGISTRAR))
    assert refreshed_firm["status"] == "ACTIVATED"
    assert refreshed_firm["activated_for_event_id"] == event["id"]
    assert refreshed_firm["open_job_count"] == 0


# ---------------------------------------------------------------------------
# corner_rbac_adjuster_denied_cancelling_own_assignment
# ---------------------------------------------------------------------------
def test_an_adjuster_may_not_cancel_their_own_inspection_assignment(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.7: "A `DeploymentCoordinator` may cancel directly, and the system cancels
    assignments on its own behalf as link three of the demobilization cascade and as the
    credential-lapse and waiver-loss cascades of §3.3."
    PRD §3.7: "Either source state behaves identically: the adjuster's
    `open_assignment_count` and `surge_capacity_score` are recomputed, and when the claim
    has no assignment left in `SCHEDULED` or `IN_PROGRESS`, the claim regresses
    `INSPECTION_PENDING → TRIAGED` and the event's posture is recomputed — which is how a
    mass demobilization can tighten an event's posture without anyone touching the event."

    Design: Corner/rbac/corner_rbac_adjuster_denied_cancelling_own_assignment
    """
    event = _declared_fl_event(api, "CAT-2026-118")
    claim = _triaged_fl_claim(api, event["id"], "POL-1004")
    assert claim["inspection_mode"] == "DESK"
    adjuster = _desk_adjuster(api)
    assignment = _desk_assignment(api, claim["id"], adjuster["id"])
    assert assignment["status"] == "SCHEDULED"

    # Ownership is not authority: the assignment is theirs, the cancel verb is not.
    validate_error(
        api.cancel_inspection_assignment(
            assignment["id"], make_adjuster_headers(adjuster["id"])
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    rows, meta = validate_paginated(
        api.list_inspection_assignments(COORD, params={"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SCHEDULED"

    refreshed_claim = validate_success(api.get_claim(claim["id"], ALICE))
    assert refreshed_claim["handling_status"] == "INSPECTION_PENDING"

    # Availability term 100 * (1 - 1/5) = 80, VALID credential, no fatigue, desk bonus 5.
    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], COORD))
    assert refreshed_adjuster["open_assignment_count"] == 1
    assert_money_equals(
        refreshed_adjuster["surge_capacity_score"], 85.00, "surge_capacity_score"
    )


# ---------------------------------------------------------------------------
# corner_rbac_vendor_coordinator_list_claims_denied_single_read_allowed
# ---------------------------------------------------------------------------
def test_a_vendor_firm_may_read_one_claim_but_not_the_claim_list(api):
    """PRD §2.1: "If the role is recognised but is not among the roles authorised for the
    target endpoint in §4, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A `VendorCoordinator` registers and activates vendor firms and acts on its
    own dispatched jobs."
    PRD §4: "The table lists only the method, path, purpose and authorised roles; request
    payloads, response contents and side effects are specified in §2 and §3 and must be
    read from there."

    Design: Corner/rbac/corner_rbac_vendor_coordinator_list_claims_denied_single_read_allowed
    """
    event = _declared_fl_event(api, "CAT-2026-119")
    claim = _fl_claim(api, event["id"], "POL-1005")
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Panhandle Mitigation",
                "vendor_type": "MITIGATION",
                "service_states": ["FL"],
                "max_concurrent_jobs": 3,
                "performance_score": 75.50,
            },
            REGISTRAR,
        ),
        201,
    )
    as_the_firm = make_vendor_coordinator_headers(firm["id"])

    # The collection is closed to the firm even unfiltered...
    validate_error(
        api.list_claims(as_the_firm), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
    )
    # ...while the single-resource read on the very same entity is open to it.
    read = validate_success(api.get_claim(claim["id"], as_the_firm))
    assert read["id"] == claim["id"]
    assert read["handling_status"] == "INTAKE"

    rows, meta = validate_paginated(
        api.list_claims(ALICE, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == claim["id"]


# ---------------------------------------------------------------------------
# corner_rbac_adjuster_denied_starting_another_adjusters_assignment
# ---------------------------------------------------------------------------
def test_an_adjuster_may_not_start_another_adjusters_inspection(api):
    """PRD §2.1: "When `X-User-Role` is `Adjuster`, `X-User-ID` is the `id` of the acting
    `Adjuster` row; ownership checks on any resource that references an adjuster compare
    the resource's adjuster reference to `X-User-ID`, so starting, completing or reporting
    no access on an inspection assignment whose `adjuster_id` differs from `X-User-ID` is
    rejected with `ERR_NOT_ASSIGNED_ADJUSTER` (HTTP 403)."
    PRD §3.7: "**Starting** the inspection moves it `SCHEDULED → IN_PROGRESS`; the
    assignment must be `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`), the clock must have
    reached or passed `window_start_utc` (`ERR_ASSIGNMENT_WINDOW_NOT_STARTED`), and the
    adjuster's `credential_status` must be `VALID`, `EXPIRING` or `WAIVED`
    (`ERR_ADJUSTER_CREDENTIAL_INVALID`) — a licence that lapsed between scheduling and
    arrival stops the work at the door."

    Design: Corner/rbac/corner_rbac_adjuster_denied_starting_another_adjusters_assignment
    """
    event = _declared_fl_event(api, "CAT-2026-120")
    claim = _triaged_fl_claim(api, event["id"], "POL-1006")
    owner = _desk_adjuster(api, full_name="Dana Reyes")
    intruder = _desk_adjuster(api, full_name="Miles Okafor")
    assignment = _desk_assignment(api, claim["id"], owner["id"])

    # Carrying the right role but the wrong row id is an ownership failure, not a
    # permission failure: the Adjuster role is authorised for this endpoint.
    validate_error(
        api.start_inspection(assignment["id"], make_adjuster_headers(intruder["id"])),
        ApiErrorId.ERR_NOT_ASSIGNED_ADJUSTER,
        403,
    )
    still_scheduled = validate_success(
        api.get_inspection_assignment(assignment["id"], COORD)
    )
    assert still_scheduled["status"] == "SCHEDULED"

    started = validate_success(
        api.start_inspection(assignment["id"], make_adjuster_headers(owner["id"]))
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["adjuster_id"] == owner["id"]


# ---------------------------------------------------------------------------
# corner_rbac_vendor_firm_denied_accepting_another_firms_job
# ---------------------------------------------------------------------------
def _two_activated_firms(api, event_id):
    firms = []
    for name in ("Coastline Tarp", "Inland Tarp"):
        firm = validate_success(
            api.create_vendor_firm(
                {
                    "firm_name": name,
                    "vendor_type": "TARP",
                    "service_states": ["FL"],
                    "max_concurrent_jobs": 4,
                    "performance_score": 80.00,
                },
                REGISTRAR,
            ),
            201,
        )
        firms.append(
            validate_success(
                api.activate_vendor_firm(firm["id"], {"event_id": event_id}, REGISTRAR)
            )
        )
    return firms


def test_a_vendor_firm_may_not_accept_another_firms_job(api):
    """PRD §2.1: "When `X-User-Role` is `VendorCoordinator`, `X-User-ID` is the `id` of the
    acting `VendorFirm` row; accepting, declining or completing a vendor assignment whose
    `vendor_firm_id` differs from `X-User-ID` is rejected with `ERR_NOT_ASSIGNED_VENDOR`
    (HTTP 403)."
    PRD §3.9: "**Accepting** moves the assignment `DISPATCHED → ACCEPTED`; the assignment
    must be `DISPATCHED` (`ERR_VENDOR_ASSIGNMENT_NOT_DISPATCHED`), the firm's own `status`
    must be `ACTIVATED` and not `CAPACITY_HOLD` or `SUSPENDED` (`ERR_VENDOR_NOT_ACTIVATED`),
    and its `open_job_count` must be strictly below `max_concurrent_jobs`
    (`ERR_VENDOR_CAPACITY_EXCEEDED`); the firm's `open_job_count` is recomputed, taking it
    `ACTIVATED → CAPACITY_HOLD` when the count reaches the ceiling."

    Design: Corner/rbac/corner_rbac_vendor_firm_denied_accepting_another_firms_job
    """
    event = _declared_fl_event(api, "CAT-2026-121")
    claim = _triaged_fl_claim(api, event["id"], "POL-1007")
    firm_a, firm_b = _two_activated_firms(api, event["id"])

    assignment = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 6000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm_a["id"],
            },
            ALICE,
        ),
        201,
    )
    assert assignment["status"] == "DISPATCHED"
    assert assignment["vendor_firm_id"] == firm_a["id"]
    # Snapshot both occupancy figures so the denial can be shown to move neither.
    a_before = validate_success(api.get_vendor_firm(firm_a["id"], ALICE))
    b_before = validate_success(api.get_vendor_firm(firm_b["id"], ALICE))

    validate_error(
        api.accept_vendor_assignment(
            assignment["id"], make_vendor_coordinator_headers(firm_b["id"])
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_VENDOR,
        403,
    )

    still_dispatched = validate_success(api.get_vendor_assignment(assignment["id"], ALICE))
    assert still_dispatched["status"] == "DISPATCHED"
    assert still_dispatched["vendor_firm_id"] == firm_a["id"]

    a_after = validate_success(api.get_vendor_firm(firm_a["id"], ALICE))
    b_after = validate_success(api.get_vendor_firm(firm_b["id"], ALICE))
    assert a_after["open_job_count"] == a_before["open_job_count"]
    assert b_after["open_job_count"] == b_before["open_job_count"]
    assert a_after["status"] == "ACTIVATED"
    assert b_after["status"] == "ACTIVATED"


# ---------------------------------------------------------------------------
# corner_rbac_close_claim_denied_for_advance_issuing_examiner
# corner_rbac_close_claim_allowed_for_non_issuing_examiner
# ---------------------------------------------------------------------------
def _inspected_claim_alice_once_paid(api, event_id, policy_number):
    """A claim in INSPECTED whose advance was issued and then voided by
    examiner-alice, so `advance_issuing_examiner_user_id` is retained while the
    payment axis is back on NONE.

    Ledger: INITIAL_CASE, PAYMENT, REVERSAL, REVISION. The revision lands the claim
    on 90000 verified less the 5000 deductible = 85000.00 whatever the payment
    history was.
    """
    claim = _triaged_fl_claim(api, event_id, policy_number)
    advance = validate_success(
        api.create_advance_payment(
            {
                "claim_id": claim["id"],
                "requested_amount": 1000,
                "basis": "STRUCTURE_PARTIAL",
            },
            ALICE,
        ),
        201,
    )
    assert advance["status"] == "ISSUED"
    assert_money_equals(advance["amount"], 1000.00, "amount")
    validate_success(
        api.void_advance_payment(
            advance["id"], {"void_reason": "Issued against the wrong file"}, ALICE
        )
    )

    adjuster = _desk_adjuster(api)
    assignment = _desk_assignment(api, claim["id"], adjuster["id"])
    validate_success(
        api.start_inspection(assignment["id"], make_adjuster_headers(adjuster["id"]))
    )
    validate_success(
        api.complete_inspection(
            assignment["id"],
            {"verified_damage_amount": 90000},
            make_adjuster_headers(adjuster["id"]),
        )
    )
    inspected = validate_success(api.get_claim(claim["id"], ALICE))
    assert inspected["handling_status"] == "INSPECTED"
    assert inspected["payment_status"] == "NONE"
    assert inspected["advance_issuing_examiner_user_id"] == "examiner-alice"
    return inspected


def test_the_examiner_who_released_advance_money_may_not_close_the_file(api):
    """PRD §3.6: "The acting `X-User-ID` must differ from the claim's
    `advance_issuing_examiner_user_id`, so that whoever released advance money on this file
    is not also the person who signs it shut (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
    PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED → NONE` on
    the payment axis when `advance_paid_total` returns to exactly 0.00 — and
    `advance_issuing_examiner_user_id` is **retained**, because a void does not erase the
    fact that this user once released money on the file."
    PRD §3.6: "Closure records the acting `X-User-ID` in `closing_examiner_user_id` and
    recomputes the event's `open_claim_count` and posture."

    Design: Corner/rbac/corner_rbac_close_claim_denied_for_advance_issuing_examiner
    """
    event = _declared_fl_event(api, "CAT-2026-122")
    claim = _inspected_claim_alice_once_paid(api, event["id"], "POL-1008")

    # The money is back, the payment axis is clean, and alice is still barred.
    validate_error(
        api.close_claim(claim["id"], ALICE), ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403
    )

    refreshed = validate_success(api.get_claim(claim["id"], ALICE))
    assert refreshed["handling_status"] == "INSPECTED"
    assert refreshed["closing_examiner_user_id"] is None
    assert refreshed["payment_status"] == "NONE"
    assert_money_equals(refreshed["advance_paid_total"], 0.00, "advance_paid_total")
    assert refreshed["advance_issuing_examiner_user_id"] == "examiner-alice"
    assert_money_equals(refreshed["case_reserve"], 85000.00, "case_reserve")


def test_a_second_examiner_closes_the_file_the_first_one_could_not(api):
    """PRD §3.6: "The acting `X-User-ID` must differ from the claim's
    `advance_issuing_examiner_user_id`, so that whoever released advance money on this file
    is not also the person who signs it shut (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
    PRD §3.6: "Closure records the acting `X-User-ID` in `closing_examiner_user_id` and
    recomputes the event's `open_claim_count` and posture."
    PRD §3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."

    Design: Corner/rbac/corner_rbac_close_claim_allowed_for_non_issuing_examiner
    """
    event = _declared_fl_event(api, "CAT-2026-123")
    claim = _inspected_claim_alice_once_paid(api, event["id"], "POL-1009")

    closed = validate_success(api.close_claim(claim["id"], BOB))
    assert closed["handling_status"] == "CLOSED"
    assert closed["closing_examiner_user_id"] == "examiner-bob"
    # The anchor is not overwritten by whoever ends up closing the file.
    assert closed["advance_issuing_examiner_user_id"] == "examiner-alice"

    refreshed_event = validate_success(api.get_event(event["id"], MGR))
    assert refreshed_event["open_claim_count"] == 0


# ---------------------------------------------------------------------------
# corner_rbac_batch_accept_denied_for_submitting_user_id
# ---------------------------------------------------------------------------
def _demobilizing_event_with_one_closed_claim(api, cat_code, policy_number):
    """Walk the whole wind-down: DECLARED, ACTIVE housing, a claim inspected and
    closed, a fresh loss estimate, SURGE_ACTIVE, then DEMOBILIZING.

    Returns ``(event, claim)``.
    """
    event = _declared_fl_event(api, cat_code)
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Bayfront Suites",
                "city": "Tampa",
                "rooms_total": 4,
                "nightly_rate": 160,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-08T00:00:00.000Z",
            },
            COORD,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], COORD))

    claim = _triaged_fl_claim(api, event["id"], policy_number)
    adjuster = _desk_adjuster(api)
    assignment = _desk_assignment(api, claim["id"], adjuster["id"])
    as_adjuster = make_adjuster_headers(adjuster["id"])
    validate_success(api.start_inspection(assignment["id"], as_adjuster))
    validate_success(
        api.complete_inspection(
            assignment["id"], {"verified_damage_amount": 90000}, as_adjuster
        )
    )

    current = validate_success(api.get_event(event["id"], MGR))
    validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": current["version"],
            },
            MGR,
        ),
        201,
    )
    validate_success(api.activate_surge(event["id"], MGR))

    # No advance was ever issued here, so the closing examiner is unconstrained.
    closed_claim = validate_success(api.close_claim(claim["id"], BOB))
    assert closed_claim["handling_status"] == "CLOSED"
    event = validate_success(api.demobilize_event(event["id"], MGR))
    assert event["status"] == "DEMOBILIZING"
    return event, closed_claim


def test_the_user_who_submitted_a_batch_may_not_accept_it_wearing_the_manager_role(api):
    """PRD §3.9: "The batch must be `SUBMITTED` (`ERR_BATCH_NOT_SUBMITTED`), and the
    accepting `X-User-ID` must differ from the `X-User-ID` recorded at submission
    (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403) — nobody signs off their own hand-off."
    PRD §3.9: "Submission stamps `submitted_at_utc` at the current instant, records the
    submitting `X-User-ID` for the later segregation-of-duties check, moves every member
    claim `CLOSED → TRANSFERRED` — a member found in any other handling status, or whose
    `transfer_batch_id` no longer points at this batch, makes the submission fail with
    `ERR_CLAIM_NOT_TRANSFERABLE` — and recomputes the event's `open_claim_count` and
    posture."
    PRD §3.9: "`claim_count` is simply the number of claims pointing at the batch;
    `blocking_claim_count` is the number of those whose `payment_status` is
    `ADVANCE_ISSUED` **or** whose `case_reserve` is exactly zero — the first because money
    is still out on the file, the second because a file carrying no reserve at all is a
    bookkeeping error the receiving unit will not accept."

    Design: Corner/rbac/corner_rbac_batch_accept_denied_for_submitting_user_id
    """
    event, claim = _demobilizing_event_with_one_closed_claim(api, "CAT-2026-124", "POL-1010")

    batch = validate_success(
        api.create_batch({"event_id": event["id"], "target_unit": "PROPERTY-EAST"}, CAROL),
        201,
    )
    batch = validate_success(
        api.add_claim_to_batch(batch["id"], {"claim_id": claim["id"]}, CAROL)
    )
    assert batch["claim_count"] == 1
    assert batch["blocking_claim_count"] == 0
    batch = validate_success(api.submit_batch(batch["id"], CAROL))
    assert batch["status"] == "SUBMITTED"

    # The check compares X-User-ID, not role: the same human changing hats is caught.
    validate_error(
        api.accept_batch(batch["id"], CAROL_AS_MANAGER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    still_submitted = validate_success(api.get_batch(batch["id"], MGR))
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["claim_count"] == 1
    transferred = validate_success(api.get_claim(claim["id"], ALICE))
    assert transferred["handling_status"] == "TRANSFERRED"

    accepted = validate_success(api.accept_batch(batch["id"], MGR))
    assert accepted["status"] == "ACCEPTED"
