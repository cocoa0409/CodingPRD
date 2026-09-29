"""Endpoint surfaces and the error ids the PRD promises for each refusal."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_IDENTITY_HEADERS,
    TEST_USERS,
    ApiErrorId,
    add_maintenance_item,
    add_package,
    approve_package,
    create_project_payload,
    create_ride_system_payload,
    open_project,
    open_review,
    raise_finding,
    read_budget_position,
    read_project,
    register_ride_system,
    submit_package,
    validate_error,
    validate_paginated,
    validate_success,
    waive_finding,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
REVIEWER = TEST_USERS["third_party_reviewer_headers"]


def test_patching_only_the_ceiling_recomputes_the_utilisation_band(api):
    """A programme patch takes the required `expected_project_version` plus any subset of `budget_ceiling_cents`, `virtual_queue_share_pct`, `design_day_attendance` and `peak_hour_share`. When `design_day_attendance` or `peak_hour_share` changes, `required_hourly_capacity_guests` is recomputed by the same rounding-up rule. Whatever changed, the patch then recomputes `committed_cost_cents`, `forecast_cost_cents` and `readiness_posture`, and may therefore cascade a scene freeze or a scene release in the same request.

    Alongside them, `headroom_cents` is `budget_ceiling_cents` less
    `committed_cost_cents`, and `restricted_utilisation_cents` is
    `budget_ceiling_cents` multiplied by ninety percent, rounded down to whole cents —
    the threshold that separates `OPEN` from `RESTRICTED` per §2.7.

    The patch is partial: sending the ceiling alone leaves the design day and its
    capacity target exactly where they were, while the utilisation band moves from
    3240000000 to 2700000000 on the very next read because it is derived rather than
    stored, and an empty ledger keeps the posture OPEN.

    Design: Corner/endpoints/project_patch_rewrites_the_ceiling_and_recomputes_the_utilisation_band
    """
    project = open_project(project_code="TAD-EP1")
    assert read_budget_position(project["id"])["restricted_utilisation_cents"] == 3240000000

    patched = validate_success(
        api.patch_project(
            project["id"],
            {"expected_project_version": project["version"],
             "budget_ceiling_cents": 3000000000},
            OWNER,
        ),
        200,
    )

    budget = read_budget_position(project["id"])
    assert patched["required_hourly_capacity_guests"] == 800
    assert patched["design_day_attendance"] == 8000
    assert patched["budget_ceiling_cents"] == 3000000000
    assert patched["version"] == 2
    assert budget["restricted_utilisation_cents"] == 2700000000
    assert budget["readiness_posture"] == "OPEN"
    assert budget["headroom_cents"] == 3000000000


def test_a_new_package_is_reachable_through_its_ride_system_filter(api):
    """A `CreativeDirector` creates one with `project_id`, `ride_system_id`, a `package_label` from the drawing-set cover sheet (1 to 80 characters), a `discipline_scope` of `SHOW_SET`, `RIDE_AND_CONTROLS`, `MEDIA_AND_AV` or `INTEGRATED`, a `base_construction_cost_cents` of at least 1, and the required `expected_project_version`.

    The two flat collection reads take richer filters: programmes may be filtered by
    `design_phase` and `readiness_posture`; scenes by `project_id`,
    `follows_scene_id`, `validating_rehearsal_run_id` and `status`; packages by
    `project_id`, `ride_system_id` and `status`.

    Fourth, `total_cost_of_work_cents` is `base_construction_cost_cents` plus
    `design_fee_cents` plus `contingency_cents`, and it is never re-rounded.

    One create writes both foreign keys and both are queryable afterwards: the
    ride-system filter returns exactly this package, already carrying its full
    515200000 price, while the programme has committed nothing because nothing has
    been approved.

    Design: Corner/endpoints/design_package_create_links_its_project_and_ride_system_for_filtered_reads
    """
    project = open_project(project_code="TAD-EP2")
    ride = register_ride_system(project["id"])

    package = add_package(project["id"], ride["id"],
                          package_label="Show Set Release 1",
                          discipline_scope="SHOW_SET",
                          base_construction_cost_cents=400000000)

    listed, meta = validate_paginated(
        api.list_design_packages(DESIGNER, params={"ride_system_id": ride["id"]}))
    assert package["total_cost_of_work_cents"] == 515200000
    assert package["project_id"] == project["id"]
    assert package["ride_system_id"] == ride["id"]
    assert len(listed) == 1
    assert listed[0]["id"] == package["id"]
    assert listed[0]["total_cost_of_work_cents"] == 515200000
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert read_budget_position(project["id"])["committed_cost_cents"] == 0


def test_a_maintenance_item_walks_the_state_stock_and_phase_refusals_in_order(api):
    """It moves the item from `DRAFT` to `APPROVED`, requires the posture not to be `FROZEN`, and records a `stocked_qty` of at least 0 that must be greater than or equal to `recommended_stock_qty`; under-stocking is refused with `ERR_SPARE_STOCK_INSUFFICIENT`.

    Handing the item to operations moves it from `APPROVED` to the terminal
    `HANDED_OVER` and is the owner's act: it requires the posture not to be `FROZEN`,
    the programme to be in `SOFT_OPEN`, and `soft_open_validated` to be true. An item
    in the wrong source status for either action is refused with
    `ERR_MAINTENANCE_STATE_INVALID`.

    Independently of the ladder, six operations are only legal inside a window of
    phases, and a request outside that window is rejected with
    `ERR_PROJECT_PHASE_INVALID` (HTTP 409).

    A frozen programme reports `ERR_PROJECT_FROZEN` in preference to any business rule
    below tier 8, but *after* the target resource's own state check at tier 7 — so a
    request to program a scene that is already `PROGRAMMED` on a frozen programme
    reports `ERR_SCENE_STATE_INVALID`, not `ERR_PROJECT_FROZEN`.

    One item walks three refusals on the same row: handing over a draft item answers
    with the state error even though the programme is also in the wrong phase; a
    single spare against a recommendation of four is under-stocked; and only once the
    item is properly approved does the phase window become the thing standing in the
    way.

    Design: Corner/endpoints/maintenance_approve_and_hand_over_are_gated_on_stock_and_on_phase
    """
    project = open_project(project_code="TAD-EP3")
    item = add_maintenance_item(
        project["id"], part_number="PN-EXACT-400",
        description="Trackless vehicle drive belt", criticality="SHOW_CRITICAL",
        annual_consumption_rate=7.3, lead_time_days=100)
    assert item["recommended_stock_qty"] == 4

    too_early = api.hand_over_maintenance_item(item["id"], {}, OWNER)
    under_stocked = api.approve_maintenance_item(item["id"], {"stocked_qty": 1}, ENGINEER)
    approved = validate_success(
        api.approve_maintenance_item(item["id"], {"stocked_qty": 4}, ENGINEER), 200)
    wrong_phase = api.hand_over_maintenance_item(item["id"], {}, OWNER)

    validate_error(too_early, ApiErrorId.ERR_MAINTENANCE_STATE_INVALID.value, 409)
    validate_error(under_stocked, ApiErrorId.ERR_SPARE_STOCK_INSUFFICIENT.value, 422)
    validate_error(wrong_phase, ApiErrorId.ERR_PROJECT_PHASE_INVALID.value, 409)
    assert approved["status"] == "APPROVED"
    assert approved["stocked_qty"] == 4
    stored = validate_success(api.get_maintenance_item(item["id"], ENGINEER))
    assert stored["status"] == "APPROVED"
    assert read_project(project["id"])["design_phase"] == "BLUE_SKY"


def test_a_request_with_no_identity_headers_is_refused_before_its_body_is_judged(api):
    """A request that omits either header, or that presents an `X-User-Role` value outside those seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

    Header presence and role validity — `ERR_UNAUTHENTICATED` (401).

    The very same body is also short of a required field, which would otherwise be a
    schema complaint, yet the identity failure is what answers and no programme is
    written.

    Design: Corner/errors/missing_identity_headers_returns_unauthenticated
    """
    payload = create_project_payload(project_code="TAD-ER1")
    payload.pop("design_day_attendance")

    response = api.create_project(payload, NO_IDENTITY_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    body = response.json()
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""
    projects, _meta = validate_paginated(api.list_projects(OWNER, params={"limit": 100}))
    assert [row for row in projects if row["project_code"] == "TAD-ER1"] == []


def test_an_unknown_project_reference_in_a_body_reports_the_project_not_found(api):
    """Only once the path resolves does the server look up body references: an unresolvable `project_id` yields `ERR_PROJECT_NOT_FOUND`, an unresolvable `ride_system_id` yields `ERR_RIDE_SYSTEM_NOT_FOUND`, an unresolvable `scene_id` or `follows_scene_id` yields `ERR_SCENE_NOT_FOUND`, an unresolvable `design_package_id` yields `ERR_PACKAGE_NOT_FOUND`, an unresolvable `safety_review_id` yields `ERR_REVIEW_NOT_FOUND`, an unresolvable `value_engineering_item_id` yields `ERR_VE_ITEM_NOT_FOUND`, and an unresolvable `rehearsal_run_id` yields `ERR_REHEARSAL_RUN_NOT_FOUND`.

    The reference is a well-formed identifier, so the schema layer has nothing to
    complain about, and the answer names the programme that could not be found rather
    than the ride system the request was trying to write.

    Design: Corner/errors/unknown_project_id_in_a_create_body_returns_project_not_found
    """
    response = api.create_ride_system(
        create_ride_system_payload(NON_EXISTENT_UUID), ENGINEER)

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)


def test_a_critical_finding_may_never_be_waived_though_a_major_one_may(api):
    """A finding whose `severity` is `CRITICAL` may never travel this path under any circumstances and is refused with `ERR_CRITICAL_FINDING_NOT_WAIVABLE`; a critical finding must be resolved and then closed.

    On the **owner-waiver path**, an `OwnerRep` waives a finding by recording a
    `justification`, which is stored as the finding's `waiver_justification` (1 to 500
    characters), moving it directly from `OPEN` to the terminal `WAIVED` with the
    owning review `FINDINGS_ISSUED`.

    Exactly one set of operations stays open, so that the freeze can be lifted:
    patching the programme (which can raise `budget_ceiling_cents`), reversing a
    ledger entry, all safety-review and safety-finding work (opening a review, raising
    a finding, resolving, closing, waiving and clearing), and the whole
    value-engineering track (proposing an item, opening its review and casting
    ballots).

    The critical finding froze the programme when it was raised, and the waiver
    attempt is still answered by the severity rule rather than by the freeze; the
    major finding beside it accepts the identical call and reaches WAIVED.

    Design: Corner/errors/critical_finding_cannot_be_waived_while_a_major_finding_can
    """
    project = open_project(project_code="TAD-ER3")
    ride = register_ride_system(project["id"])
    package = add_package(project["id"], ride["id"],
                          package_label="Show Set Release 1",
                          discipline_scope="SHOW_SET",
                          base_construction_cost_cents=400000000)
    submit_package(package["id"])
    approve_package(package["id"])
    review = open_review(package["id"])
    critical = raise_finding(
        review["id"], severity="CRITICAL",
        description="Restraint monitoring channel lacks redundancy",
        remediation_cost_estimate_cents=45000000)
    major = raise_finding(
        review["id"], severity="MAJOR",
        description="Queue gate signage below standard",
        remediation_cost_estimate_cents=1200000)
    assert read_project(project["id"])["readiness_posture"] == "FROZEN"

    refused = api.waive_safety_finding(
        critical["id"],
        {"justification": "Owner accepts residual risk pending vendor retrofit"},
        OWNER,
    )
    waived = waive_finding(
        major["id"],
        justification="Signage corrected under separate operations work order")

    validate_error(refused, ApiErrorId.ERR_CRITICAL_FINDING_NOT_WAIVABLE.value, 422)
    assert validate_success(
        api.get_safety_finding(critical["id"], REVIEWER))["status"] == "OPEN"
    assert waived["status"] == "WAIVED"
    assert read_project(project["id"])["open_critical_finding_count"] == 1


def test_a_client_may_not_post_a_commitment_entry_kind(api):
    """Any other `entry_kind` submitted directly — `COMMITMENT`, `VE_SAVING` or `REVERSAL` — is refused with `ERR_LEDGER_KIND_NOT_WRITABLE`, because those three are minted only by the side effects described in §3.5, §3.8 and below.

    Every entry, however it was minted, receives a `sequence_no`: a per-programme
    ordinal starting at 1 and taken as one greater than the programme's
    `ledger_sequence_high_water`, which then advances to that value.

    `COMMITMENT` is a declared member of the enum precisely so the ledger can record
    the side-effect rows the system mints itself, so the refusal is the writability
    rule rather than a schema complaint; the identical amount posted as a change order
    goes through as ordinal 1.

    Design: Corner/errors/client_posted_commitment_entry_kind_is_not_writable
    """
    project = open_project(project_code="TAD-ER4")

    refused = api.create_ledger_entry(
        {
            "project_id": project["id"], "entry_kind": "COMMITMENT",
            "amount_cents": 500000000, "memo": "Hand-written commitment",
            "expected_project_version": project["version"],
        },
        OWNER,
    )
    accepted = validate_success(
        api.create_ledger_entry(
            {
                "project_id": project["id"], "entry_kind": "CHANGE_ORDER",
                "amount_cents": 500000000, "memo": "Show set steelwork change order",
                "expected_project_version": project["version"],
            },
            OWNER,
        ),
        201,
    )

    validate_error(refused, ApiErrorId.ERR_LEDGER_KIND_NOT_WRITABLE.value, 422)
    assert accepted["sequence_no"] == 1
    assert accepted["entry_kind"] == "CHANGE_ORDER"
    assert read_budget_position(project["id"])["committed_cost_cents"] == 500000000
