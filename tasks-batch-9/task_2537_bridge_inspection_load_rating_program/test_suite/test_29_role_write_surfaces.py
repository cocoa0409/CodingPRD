"""
Which role owns which write surface: the administrator's registries and cycle
lifecycle, the inspector's field capture, the reviewer's claim-and-decide pair, the
engineer's scour finalisation and the district engineer's authority chain.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import program_admin_headers

WINDOW_START = "2026-09-02T08:00:00Z"
WINDOW_END = "2026-09-02T16:00:00Z"
OBSERVED_AT = "2026-09-02T10:00:00Z"

# The abutment of the district-engineer scenario: four units with three of them
# poor, so the row is balanced, documented, and deficient enough to justify a
# finding without carrying any severe quantity.
UNDERMINED_ABUTMENT = f.element_condition_payload(
    "ABUTMENT",
    "EA",
    4,
    cs1_qty=0,
    cs2_qty=1,
    cs3_qty=3,
    cs4_qty=0,
    photo_count=2,
    defect_notes="Undermined footing face after high water",
)

# The three groups a ROUTINE report must cover, with the girder carrying the
# severe quantity an IMMEDIATE finding has to be anchored to.
THREE_GROUPS = (f.BASELINE_DECK, f.BASELINE_GIRDER, f.BASELINE_ABUTMENT)
DISTRICT_GROUPS = (f.BASELINE_DECK, f.BASELINE_GIRDER, UNDERMINED_ABUTMENT)


# ─── The administrator's registries and cycle lifecycle ─────────────────────
def test_the_administrator_registers_the_roster_and_the_inventory_from_an_opaque_identity(
    client,
):
    """
    The `ProgramAdmin` writes both registries without ever naming a roster row of its
    own, and the structure it registers comes back fully derived: seeded ratings, a
    two-year cycle computed from those seeds, and a due date measured from creation.

    PRD §3.1: "Everything in the program hangs off two registries that a `ProgramAdmin`
    maintains: the structure inventory and the personnel roster."
    PRD §2.1: "When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator
    identifier that is not tied to any persisted entity"
    PRD §3.1: "At creation the system also computes `inspection_interval_months` and
    `underwater_interval_months` from the freshly seeded condition per the frequency
    policy, derives `next_inspection_due_date` and `next_underwater_due_date` from the
    creation date"

    Design: Corner/rbac/program_admin_owns_inventory_and_cycle_setup
    """
    fx.pin_base_clock(client)

    person = get_success_data(
        client.create_personnel(
            f.personnel_payload(
                "Ivy Inspector", fx.CURRENT_REFRESHER, team_leader_certified=True
            ),
            program_admin_headers(),
        ),
        201,
    )
    structure = get_success_data(
        client.create_bridge(
            f.bridge_payload("STR-000001", spans_water=True), program_admin_headers()
        ),
        201,
    )

    assert person["full_name"] == "Ivy Inspector"
    assert person["team_leader_certified"] is True
    assert person["qualification_status"] == "CURRENT"

    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 7
    assert structure["min_nbi_rating"] == 7
    assert structure["inspection_interval_months"] == 24
    assert structure["underwater_interval_months"] is None
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    assert structure["next_underwater_due_date"] is None
    assert structure["service_posture"] == "OPEN"
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["version"] == 1


def test_the_administrator_reads_the_roster_entry_it_wrote(client):
    """
    Read access is the same for every role, so the administrator that registered the
    person can also retrieve them — the opaque identity is no obstacle to a shared GET.

    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API
    is available to all seven roles."
    PRD §3.1: "A person carries a `full_name`, an `agency` label for the employing
    organisation, and an `nbis_refresher_expiry_date` marking when their NBIS refresher
    training certificate lapses."

    Design: Corner/rbac/program_admin_owns_inventory_and_cycle_setup
    """
    fx.pin_base_clock(client)
    person = fx.create_person(
        client,
        f.personnel_payload(
            "Ivy Inspector", fx.CURRENT_REFRESHER, team_leader_certified=True
        ),
    )

    fetched = validate_success(
        client.get_personnel(person["id"], program_admin_headers()), 200
    )

    assert fetched["id"] == person["id"]
    assert fetched["full_name"] == "Ivy Inspector"
    a.assert_date_equals(
        fetched["nbis_refresher_expiry_date"],
        fx.CURRENT_REFRESHER,
        "nbis_refresher_expiry_date",
    )


def test_the_attribute_edit_collapses_the_cycle_to_a_single_year(client, bridge):
    """
    The same administrator revises the traffic count and flips the fracture-critical
    flag in one unversioned PATCH, and the structure comes back with its cycle floored
    at twelve months and its due date re-derived from creation rather than from the
    edit.

    PRD §3.1: "A `ProgramAdmin` may revise `name`, `adt`, `detour_length_km`,
    `fracture_critical`, `underwater_elements` and `spans_water` on an existing
    structure. Each such edit is a real mutation: it re-evaluates
    `inspection_interval_months`, `underwater_interval_months`,
    `next_inspection_due_date` and `next_underwater_due_date`, and increments the
    structure's `version` by one."
    PRD §2.11: "A structure with `fracture_critical` set to true is capped at 12
    months."
    PRD §2.9: "the structure-attribute update endpoint deliberately carries no version
    field: it has no supersede semantics, so it accepts a plain update and simply
    increments the structure's `version` as any mutation does."

    Design: Corner/rbac/program_admin_owns_inventory_and_cycle_setup
    """
    assert bridge["inspection_interval_months"] == 24

    patched = validate_success(
        client.patch_bridge(
            bridge["id"],
            {"adt": 300, "fracture_critical": True},
            program_admin_headers(),
        ),
        200,
    )

    assert patched["adt"] == 300
    assert patched["fracture_critical"] is True
    assert patched["inspection_interval_months"] == 12
    a.assert_date_equals(
        patched["next_inspection_due_date"], "2027-09-01", "next_inspection_due_date"
    )
    a.assert_version_advanced_by(patched["version"], bridge["version"], 1, "bridge")


def test_the_cycle_oscillates_between_planning_and_locked_under_the_administrator(
    client,
):
    """
    Opening, locking and reopening a programming cycle are all the administrator's, and
    the reopen deliberately keeps the lock instant on the record so the oscillation is
    auditable.

    PRD §3.8: "A new cycle opens in `PLANNING`."
    PRD §3.8: "A `ProgramAdmin` locks the cycle to freeze its programme for reporting,
    moving it `PLANNING → LOCKED` and stamping `locked_at` from the logical clock."
    PRD §3.8: "Reopening moves it `LOCKED → PLANNING` and *retains* `locked_at` as the
    instant of the most recent lock rather than clearing it, so the cycle may oscillate
    between planning and locked as many times as needed before reporting."

    Design: Corner/rbac/program_admin_owns_inventory_and_cycle_setup
    """
    fx.pin_base_clock(client)

    cycle = get_success_data(
        client.create_program_cycle(
            f.program_cycle_payload(ranking_policy="CONDITION_BASED"),
            program_admin_headers(),
        ),
        201,
    )
    assert cycle["status"] == "PLANNING"
    assert cycle["reserve_cents"] == 500000000
    assert cycle["available_cents"] == 9500000000
    assert cycle["committed_cents"] == 0
    assert cycle["remaining_cents"] == 9500000000
    assert cycle["locked_at"] is None
    a.assert_budget_identity(cycle)

    locked = validate_success(
        client.lock_program_cycle(cycle["id"], program_admin_headers()), 200
    )
    assert locked["status"] == "LOCKED"
    a.assert_instant_equals(locked["locked_at"], c.BASE_CLOCK, "locked_at")

    reopened = validate_success(
        client.reopen_program_cycle(cycle["id"], program_admin_headers()), 200
    )
    assert reopened["status"] == "PLANNING"
    a.assert_instant_equals(reopened["locked_at"], c.BASE_CLOCK, "locked_at")
    a.assert_budget_identity(reopened)


# ─── The inspector's field capture, edit, delete and void ───────────────────
def test_the_inspector_records_edits_and_deletes_rows_inside_the_draft(
    client, roster, bridge
):
    """
    The whole field-capture surface answers to one set of inspector credentials: the
    row is written, a second row is deleted again, and the redistribution re-derives
    both the row's own index and every rollup on the report.

    PRD §3.2: "Writing an element row immediately derives four values on it.
    `reported_sum` is the total of the four condition-state quantities. `balanced` is
    true exactly when `reported_sum` equals `total_quantity`. `deficient_quantity` is
    the sum of the poor and severe quantities"
    PRD §3.2: "An inspector may redistribute quantities on an existing row while the
    report is still `DRAFT`, resupplying `total_quantity`, the four condition-state
    quantities and optionally `photo_count` and `defect_notes`; the row's four derived
    values and the report's five rollups are recomputed. An inspector may also delete a
    row from a `DRAFT` report, which likewise recomputes the report's rollups."

    Design: Corner/rbac/bridge_inspector_owns_field_capture_and_void
    """
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    girder = fx.add_element(client, inspection["id"], roster, f.BASELINE_GIRDER)
    bearing = fx.add_element(client, inspection["id"], roster, f.BASELINE_BEARING)
    assert girder["element_health_index"] == 40.00
    assert fx.read_inspection(client, inspection["id"])["element_count"] == 2

    deletion = client.delete_element_condition(bearing["id"], roster.inspector_headers)
    assert deletion.status_code == 204, (
        f"deleting a DRAFT element row returns 204, got {deletion.status_code}"
    )
    if deletion.content:
        assert deletion.json()["data"] == {}

    updated = validate_success(
        client.update_element_condition(
            girder["id"],
            f.element_update_payload(
                300, 100, 100, 50, 50, photo_count=9, defect_notes="Re-measured after cleaning"
            ),
            roster.inspector_headers,
        ),
        200,
    )
    assert updated["element_health_index"] == 66.67
    a.assert_element_derived_fields(updated, 300, 100, 100, 50, 50)

    report = fx.read_inspection(client, inspection["id"])
    assert report["element_count"] == 1
    assert report["reported_quantity_total"] == 300
    assert report["deficient_quantity_total"] == 100
    assert report["photo_count_total"] == 9
    assert report["quantity_balanced"] is True
    assert report["status"] == "DRAFT"


def test_the_inspector_carries_the_shared_finding_and_scour_grants(
    client, roster, bridge
):
    """
    Two writes the inspector shares with other roles work from inspector credentials —
    a critical finding a reviewer could equally have filed, and a scour evaluation an
    engineer could equally have filed — while the finalisation of that same evaluation
    stays out of reach.

    PRD §3.5: "Either a `BridgeInspector` or a `QaReviewer` may raise a finding."
    PRD §3.6: "Either a `RatingEngineer` or a `BridgeInspector` may record an
    evaluation."
    PRD §3.6: "Only a `RatingEngineer` may finalise, and the engineer named in the
    evaluation's `evaluated_by_id` must hold `load_rating_engineer_licensed` with a
    non-null `pe_license_number` and a current refresher"

    Design: Corner/rbac/bridge_inspector_owns_field_capture_and_void
    """
    drafted = fx.draft_report_with_baseline(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    fx.submit_report(client, drafted["inspection"]["id"], roster, inspection_date=OBSERVED_AT)

    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        drafted["inspection"]["id"],
        "IMMEDIATE",
        element_condition_id=drafted["elements"]["girder"]["id"],
    )
    assert finding["severity"] == "IMMEDIATE"
    assert finding["finding_status"] == "OPEN"
    assert finding["notification_status"] == "PENDING"
    assert finding["restriction_action"] == "NONE"
    assert fx.read_bridge(client, bridge["id"])["open_critical_finding_count"] == 1

    evaluation = get_success_data(
        client.create_scour_evaluation(
            bridge["id"],
            f.scour_evaluation_payload(
                roster.inspector_id,
                5,
                evaluation_method="FIELD_OBSERVATION",
                foundation_type="PILE",
                observed_scour_depth_m=0.3,
            ),
            roster.inspector_headers,
        ),
        201,
    )
    assert evaluation["status"] == "DRAFT"
    assert evaluation["derived_scour_status"] == "LOW_RISK"

    refused = client.finalize_scour_evaluation(
        evaluation["id"], roster.inspector_headers
    )
    validate_error(refused, e.ERR_ROLE_NOT_PERMITTED, 403)
    assert fx.read_scour(client, evaluation["id"])["status"] == "DRAFT"
    assert fx.read_bridge(client, bridge["id"])["scour_status"] == "NOT_EVALUATED"


def test_the_void_releases_the_window_the_report_had_reserved(client, roster, bridge):
    """
    Voiding is the inspector's escape hatch from a submitted report, and the released
    window is immediately re-bookable by the same leader on the same structure — which
    it would not be if the voided report still counted in either overlap test.

    PRD §3.2: "Voiding is available to a `BridgeInspector` while the report is still
    `DRAFT` or `SUBMITTED` — a `DRAFT → VOIDED` or `SUBMITTED → VOIDED` move, carrying
    an optional `void_reason` — and is the intended escape hatch when weather or access
    forces a reschedule."
    PRD §3.2: "Both tests consider only inspections whose status is `DRAFT`,
    `SUBMITTED`, `IN_QA` or `ACCEPTED`; a report that has been taken to `VOIDED`
    releases the window it reserved and drops out of both tests entirely."

    Design: Corner/rbac/bridge_inspector_owns_field_capture_and_void
    """
    drafted = fx.draft_report_with_baseline(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    fx.submit_report(client, drafted["inspection"]["id"], roster, inspection_date=OBSERVED_AT)

    voided = validate_success(
        client.void_inspection(
            drafted["inspection"]["id"],
            roster.inspector_headers,
            {"void_reason": "Access denied by the property owner; re-scope the visit"},
        ),
        200,
    )
    assert voided["status"] == "VOIDED"

    replacement = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    assert replacement["status"] == "DRAFT"
    assert replacement["id"] != drafted["inspection"]["id"]
    assert replacement["element_count"] == 0


# ─── The reviewer's claim-and-decide pair ───────────────────────────────────
def _a_submitted_three_group_report(client, roster, bridge, rows=THREE_GROUPS):
    """
    A `SUBMITTED` routine report covering all three element groups, observed and
    submitted on the field day, so a reviewer may claim it immediately.
    """
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    written = [fx.add_element(client, inspection["id"], roster, row) for row in rows]
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    submitted = fx.submit_report(
        client, inspection["id"], roster, inspection_date=OBSERVED_AT
    )
    return {"inspection": submitted, "rows": written}


def test_the_reviewer_claims_the_submitted_report_and_the_claim_is_stamped(
    client, roster, bridge
):
    """
    The claim is the reviewer's own transition, and it writes the claiming identity onto
    the report from the header rather than from any payload.

    PRD §3.3: "A `SUBMITTED` report is then claimed for review. A `QaReviewer` claiming
    a report takes it from `SUBMITTED` to `IN_QA`, which sets the report's
    `qa_reviewer_id` to the claiming user's `X-User-ID` and stamps `qa_claimed_at` from
    the logical clock."
    PRD §2.1: "A `QaReviewer` performs quality assurance on inspection reports, claiming
    a submitted report and then either returning it for revision or accepting it, and
    may never review a report they themselves led."

    Design: Corner/rbac/qa_reviewer_owns_claim_and_decision
    """
    report = _a_submitted_three_group_report(client, roster, bridge)
    assert report["inspection"]["status"] == "SUBMITTED"
    assert report["inspection"]["qa_reviewer_id"] is None

    claimed = fx.qa_claim(client, report["inspection"]["id"], roster)

    assert claimed["status"] == "IN_QA"
    assert claimed["qa_reviewer_id"] == roster.reviewer_id
    a.assert_instant_equals(
        claimed["qa_claimed_at"], c.FIELD_DAY_CLOCK, "qa_claimed_at"
    )


def test_the_reviewer_files_a_finding_from_the_report_it_holds(client, roster, bridge):
    """
    The critical-finding grant is shared with the inspector, so the reviewer who spots
    the severe girder loss during review may raise it themselves — anchored to the very
    row it read, on a report whose status is one of the three the rule admits.

    PRD §3.5: "Either a `BridgeInspector` or a `QaReviewer` may raise a finding."
    PRD §3.5: "The source report must be in `SUBMITTED`, `IN_QA` or `ACCEPTED` — a
    finding cannot be raised from a report still being drafted or from one that has been
    voided."
    PRD §3.5: "Creating the finding also increments the structure's
    `open_critical_finding_count`, which counts findings on that structure whose
    `finding_status` is `OPEN` or `MITIGATED`, and increments the structure's `version`
    by one."

    Design: Corner/rbac/qa_reviewer_owns_claim_and_decision
    """
    report = _a_submitted_three_group_report(client, roster, bridge)
    girder = report["rows"][1]
    fx.qa_claim(client, report["inspection"]["id"], roster)

    finding = get_success_data(
        client.create_critical_finding(
            f.critical_finding_payload(
                bridge["id"],
                report["inspection"]["id"],
                "IMMEDIATE",
                description="Reviewer-spotted girder loss requiring immediate action",
                element_condition_id=girder["id"],
            ),
            roster.reviewer_headers,
        ),
        201,
    )

    assert finding["severity"] == "IMMEDIATE"
    assert finding["finding_status"] == "OPEN"
    assert finding["element_condition_id"] == girder["id"]
    structure = fx.read_bridge(client, bridge["id"])
    assert structure["open_critical_finding_count"] == 1
    a.assert_version_advanced_by(structure["version"], bridge["version"], 1, "bridge")


def test_the_return_sends_the_report_back_without_touching_the_inventory(
    client, roster, bridge
):
    """
    A `RETURN` is the reviewer's other branch, and it is deliberately inert against the
    structure: the report goes back to the inspector with the claim released, while the
    seeded component ratings and the routine inspection date are exactly where the
    acceptance cascade would have moved them had the decision gone the other way.

    PRD §3.3: "A `RETURN` decision — which may carry an optional `return_note` — sends
    the report from `IN_QA` back to `DRAFT`, increments `returned_count` by one, and
    clears `qa_reviewer_id` back to null so that any qualified reviewer may claim the
    next submission."
    PRD §3.3: "Each return also re-evaluates `qa_escalation_required`, which becomes
    true once `returned_count` has reached 2 or more"
    PRD §3.3: "For each element group that reported at least one row, the structure's
    corresponding component rating — `deck_rating`, `superstructure_rating` or
    `substructure_rating` — is overwritten from the report's matching computed rating"

    Design: Corner/rbac/qa_reviewer_owns_claim_and_decision
    """
    report = _a_submitted_three_group_report(client, roster, bridge)
    fx.qa_claim(client, report["inspection"]["id"], roster)

    returned = fx.qa_decide(
        client,
        report["inspection"]["id"],
        roster,
        "RETURN",
        return_note="Quantify the CS4 girder loss by span and re-photograph",
    )

    assert returned["status"] == "DRAFT"
    assert returned["returned_count"] == 1
    assert returned["qa_escalation_required"] is False
    assert returned["qa_reviewer_id"] is None

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 7
    assert structure["last_routine_inspection_date"] is None
    assert structure["bridge_health_index"] is None
    a.assert_version_unchanged(structure["version"], bridge["version"], "bridge")


def test_the_reviewer_holds_no_field_capture_grant(client, roster, bridge):
    """
    With the report back in `DRAFT` the row the reviewer asked for is perfectly legal —
    but only from the inspector's credentials, which is what makes the refusal a role
    refusal rather than a state refusal.

    PRD §2.1: "Write access is narrow and is enumerated per endpoint in §4."
    PRD §2.8: "2. **Role authorisation** — the authenticated role appears in the
    endpoint's authorised list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
    endpoint."
    PRD §3.2: "Inside a `DRAFT` report the inspector records one row per national bridge
    element."

    Design: Corner/rbac/qa_reviewer_owns_claim_and_decision
    """
    report = _a_submitted_three_group_report(client, roster, bridge)
    inspection_id = report["inspection"]["id"]
    fx.qa_claim(client, inspection_id, roster)
    fx.qa_decide(client, inspection_id, roster, "RETURN")

    refused = client.create_element_condition(
        inspection_id, f.BASELINE_BEARING, roster.reviewer_headers
    )

    validate_error(refused, e.ERR_ROLE_NOT_PERMITTED, 403)
    assert fx.read_inspection(client, inspection_id)["element_count"] == 3

    added = fx.add_element(client, inspection_id, roster, f.BASELINE_BEARING)
    assert added["element_health_index"] == 50.00
    assert fx.read_inspection(client, inspection_id)["element_count"] == 4


# ─── The engineer's scour judgement ─────────────────────────────────────────
def test_the_engineer_drafts_a_scour_critical_opinion_that_changes_nothing_yet(
    client, roster, bridge
):
    """
    A code of 3 sits on the worst edge of the three-band threshold, so the draft already
    knows it is critical — and still writes nothing through, which is what makes the
    finalisation the meaningful act rather than the recording.

    PRD §3.6: "The `derived_scour_status` is a three-band threshold on the code, computed
    the moment the evaluation is recorded: a code of 3 or below is `SCOUR_CRITICAL`, a
    code from 4 through 6 is `LOW_RISK`, and a code of 7 or above is `STABILIZED`."
    PRD §3.6: "A new evaluation is created with `status` `DRAFT` and a null
    `finalized_at`; while it remains a draft it is a working opinion and writes nothing
    through to the structure."
    PRD §3.6: "A structure that has never had a finalised evaluation keeps a
    `scour_status` of `NOT_EVALUATED`, which is not a value `derived_scour_status` can
    ever take."

    Design: Corner/rbac/rating_engineer_owns_scour_finalize_and_rating_creation
    """
    evaluation = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        3,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.1,
    )

    assert evaluation["status"] == "DRAFT"
    assert evaluation["derived_scour_status"] == "SCOUR_CRITICAL"
    assert evaluation["evaluated_by_id"] == roster.engineer_id
    assert evaluation["bridge_id"] == bridge["id"]
    assert evaluation["finalized_at"] is None

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["inspection_interval_months"] == 24
    assert structure["poa_compliant"] is True
    a.assert_version_unchanged(structure["version"], bridge["version"], "bridge")
    assert fx.plans_for_bridge(client, bridge["id"]) == []


def test_the_finalisation_publishes_the_judgement_and_opens_a_plan_obligation(
    client, roster, bridge
):
    """
    Finalisation is the engineer's exclusive act and it runs the whole cascade in one
    request: the structure's scour status, its inspection cycle, its compliance flag and
    a plan-of-action obligation that no client asked for all settle before the response
    is written.

    PRD §3.6: "**Hop 1** sets `status` to `FINAL` and stamps `finalized_at` from the
    logical clock. **Hop 2**, caused by hop 1, writes the evaluation's
    `derived_scour_status` through to the structure's `scour_status`, recomputes the
    structure's `inspection_interval_months` — where the new status is `SCOUR_CRITICAL`
    the scour ceiling applies and the interval becomes the smaller of its current value
    and 12 months — and increments the structure's `version` by one."
    PRD §3.6: "**Hop 4**, caused by the plan insert, sets the structure's `poa_compliant`
    to false, because a scour-critical structure with no approved plan is out of
    compliance."
    PRD §3.6: "Because plans of action are created by a cascade rather than by a client
    request, the plan list is the only way to discover that a plan now exists."

    Design: Corner/rbac/rating_engineer_owns_scour_finalize_and_rating_creation
    """
    evaluation = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        3,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.1,
    )

    finalised = fx.finalize_scour(client, evaluation["id"], roster)

    assert finalised["status"] == "FINAL"
    a.assert_instant_equals(finalised["finalized_at"], c.BASE_CLOCK, "finalized_at")

    structure = validate_success(
        client.get_bridge(bridge["id"], roster.engineer_headers), 200
    )
    assert structure["scour_status"] == "SCOUR_CRITICAL"
    assert structure["inspection_interval_months"] == 12
    assert structure["poa_compliant"] is False
    a.assert_version_advanced_by(structure["version"], bridge["version"], 1, "bridge")

    plans = fx.plans_for_bridge(client, bridge["id"])
    assert len(plans) == 1, f"the cascade creates exactly one plan, got {len(plans)}"
    assert plans[0]["status"] == "REQUIRED"
    assert plans[0]["bridge_id"] == bridge["id"]
    assert plans[0]["scour_evaluation_id"] == evaluation["id"]


# ─── The district engineer's authority chain ────────────────────────────────
def _an_urgent_finding_on_an_undermined_abutment(client, roster, bridge):
    """
    A `SUBMITTED` report whose abutment row carries three poor units, and the `URGENT`
    finding the inspector raised from it — the state the district engineer inherits.
    """
    report = _a_submitted_three_group_report(client, roster, bridge, DISTRICT_GROUPS)
    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        report["inspection"]["id"],
        "URGENT",
        element_condition_id=report["rows"][2]["id"],
        description="Abutment undermining after high water",
    )
    return {"report": report, "finding": finding}


def test_the_district_engineer_restricts_the_structure_and_floors_its_cycle(
    client, roster, bridge
):
    """
    Restriction authority is the district engineer's alone, and imposing it reaches
    straight into the inventory: the posture leaves `OPEN` and the inspection cycle drops
    to the tightest floor in the system.

    PRD §3.5: "Only a `DistrictEngineer` may exercise restriction authority, and the
    payload names an `action` of either `RESTRICT` or `CLOSE` together with an
    `authorized_by_id` that must equal the acting engineer's own identifier and must
    resolve to an existing roster entry."
    PRD §3.5: "Escalating to `RESTRICT` is permitted only from `restriction_action`
    `NONE`. It stores `RESTRICT`, records `restriction_authorized_by_id` and stamps
    `restriction_imposed_at` from the logical clock."
    PRD §3.5: "The structure's `inspection_interval_months` is re-derived with the
    posture floor applied, taking the smaller of its current interval and 6 months, and
    the structure's `version` is incremented by one."

    Design: Corner/rbac/district_engineer_owns_authority_and_programming_actions
    """
    state = _an_urgent_finding_on_an_undermined_abutment(client, roster, bridge)

    restricted = fx.impose(client, state["finding"]["id"], roster, "RESTRICT")

    assert restricted["restriction_action"] == "RESTRICT"
    assert restricted["restriction_authorized_by_id"] == roster.district_id
    a.assert_instant_equals(
        restricted["restriction_imposed_at"], c.FIELD_DAY_CLOCK, "restriction_imposed_at"
    )
    assert restricted["finding_status"] == "OPEN"

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "RESTRICTED"
    assert structure["inspection_interval_months"] == 6
    assert structure["open_critical_finding_count"] == 1
    a.assert_version_advanced_by(structure["version"], bridge["version"], 2, "bridge")


def test_the_chain_the_mitigation_and_the_resolution_lift_the_posture_again(
    client, roster, bridge
):
    """
    The same engineer walks the owner link of the notification chain, records interim
    mitigation that deliberately changes nothing but the finding's own status, and then
    resolves — at which point the restriction it imposed is lifted and the cycle
    lengthens back to its unfloored value.

    PRD §3.5: "A `DistrictEngineer` records each link of the chain, supplying a `tier` of
    either `BRIDGE_OWNER` or `FHWA`, a `channel` of `EMAIL`, `PHONE` or `PORTAL`
    describing the delivery route actually used, and a `recipient_label` naming the
    recipient organisation or person."
    PRD §3.5: "This advances `finding_status` `OPEN → MITIGATED` and does exactly nothing
    else: `notification_status` and `restriction_action` are untouched, and the finding
    continues to restrict the structure because a `MITIGATED` finding still counts as
    unresolved in the posture ladder."
    PRD §3.5: "Resolution stores the `resolution_note`, sets `finding_status` to
    `RESOLVED` (its terminal value), and then unwinds the structure:
    `open_critical_finding_count` is recomputed, `service_posture` is recomputed"

    Design: Corner/rbac/district_engineer_owns_authority_and_programming_actions
    """
    state = _an_urgent_finding_on_an_undermined_abutment(client, roster, bridge)
    finding_id = state["finding"]["id"]
    fx.impose(client, finding_id, roster, "RESTRICT")

    log = fx.notify_owner(
        client,
        finding_id,
        roster,
        channel="PHONE",
        recipient_label="County Highway Superintendent",
    )
    a.assert_notification_log_shape(log)
    assert log["tier"] == "BRIDGE_OWNER"
    assert log["channel"] == "PHONE"
    assert log["late"] is False
    a.assert_instant_equals(log["sent_at"], c.FIELD_DAY_CLOCK, "sent_at")
    assert fx.read_finding(client, finding_id)["notification_status"] == "OWNER_NOTIFIED"

    mitigated = fx.mitigate(
        client, finding_id, roster, note="Riprap placed and load restricted to 15 tons"
    )
    assert mitigated["finding_status"] == "MITIGATED"
    assert mitigated["notification_status"] == "OWNER_NOTIFIED"
    assert mitigated["restriction_action"] == "RESTRICT"
    still_restricted = fx.read_bridge(client, bridge["id"])
    assert still_restricted["service_posture"] == "RESTRICTED"
    assert still_restricted["inspection_interval_months"] == 6
    assert still_restricted["open_critical_finding_count"] == 1

    resolved = fx.resolve(
        client, finding_id, roster, note="Footing underpinned; restriction lifted"
    )
    assert resolved["finding_status"] == "RESOLVED"
    assert resolved["restriction_action"] == "RESTRICT"

    lifted = fx.read_bridge(client, bridge["id"])
    assert lifted["open_critical_finding_count"] == 0
    assert lifted["service_posture"] == "OPEN"
    assert lifted["inspection_interval_months"] == 24
