"""The completion projection, its feasibility verdict, and the five rungs guarding submission."""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_USER_ID,
    build_scenario,
    change_service_level,
    feasibility,
    list_applicant_documents,
    new_applicant,
    new_catalog_item,
    new_document_requirement,
    new_order,
    order_version,
    prepare_form,
    quote,
    read_applicant,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CASE_MANAGER, COMPLIANCE, SUBMITTER


# ==========================================================================
# The deadline boundary is inclusive
# ==========================================================================
def _two_orders_on_the_projection_boundary():
    """Two STANDARD single-traveller orders that project to the same completion date,
    one whose deadline lands exactly on it and one whose deadline is a day earlier."""
    set_clock("2026-06-01T09:00:00Z")
    catalog = new_catalog_item(visa_type="TOURIST")
    edge = new_order(catalog["id"], travel_date="2026-07-01", return_date="2026-07-20")
    over = new_order(catalog["id"], travel_date="2026-06-30", return_date="2026-07-19")
    new_applicant(edge["id"], full_name="Edge One")
    new_applicant(over["id"], full_name="Over One")
    quote(edge["id"])
    quote(over["id"])
    return edge, over


def test_projection_landing_exactly_on_the_deadline_is_feasible(api):
    """PRD §3.9: "Immediately after every projection, the deadline date is computed as the
    order's `travel_date` minus **5** calendar days — a wall-calendar cushion, not a
    business-day one. `feasibility_status` is `FEASIBLE` when `projected_completion_date`
    is on or before that deadline date, and `INFEASIBLE` when it is strictly after. The
    boundary is inclusive: landing exactly on the deadline date is `FEASIBLE`."

    Design: Difficulty/boundary_precision_check/feasibility_projection_equal_to_deadline_is_feasible
    """
    edge, over = _two_orders_on_the_projection_boundary()

    edge_read = validate_success(api.get_feasibility(edge["id"], CASE_MANAGER))
    over_read = validate_success(api.get_feasibility(over["id"], CASE_MANAGER))

    assert edge_read["projected_completion_date"] == "2026-06-26", (
        f"expected the projection on 2026-06-26, got {edge_read['projected_completion_date']}"
    )
    assert edge_read["deadline_date"] == "2026-06-26", (
        "2026-07-01 minus 5 calendar days is 2026-06-26"
    )
    assert edge_read["feasibility_status"] == "FEASIBLE", "landing on the deadline is FEASIBLE"
    assert over_read["deadline_date"] == "2026-06-25"
    assert over_read["feasibility_status"] == "INFEASIBLE", (
        "one day earlier flips the verdict, because the projection is unchanged"
    )


def test_the_stored_verdict_matches_the_boundary_the_projection_landed_on(api):
    """PRD §3.9: "*Before submission* — `submitted_at` is null, and the read reports
    `variant_used` as `tier_nominal`. Start from the effective submission date computed as
    if the order were submitted at the current logical clock. Advance that by **1** business
    day for the outbound courier hop from the expediter to the agency. Advance the result by
    the agency turnaround in business days. Advance that by **1** business day for the
    return courier hop from the agency back to the expediter. Advance that by **2** business
    days for the final delivery. The date reached is `projected_completion_date`."
    PRD §3.9: "It is a pure read and writes nothing — it does not persist a recomputed
    projection onto the order, does not move the stored `feasibility_status`, and does not
    revoke an acknowledgment; the `feasibility_status` it returns is the order's stored
    value."

    Design: Difficulty/boundary_precision_check/feasibility_projection_equal_to_deadline_is_feasible
    """
    edge, over = _two_orders_on_the_projection_boundary()

    edge_read = validate_success(api.get_feasibility(edge["id"], CASE_MANAGER))
    assert edge_read["variant_used"] == "tier_nominal"
    assert edge_read["effective_submission_date"] == "2026-06-01", (
        "the clock hour 9 is strictly below the STANDARD cutoff on a business day"
    )

    assert read_order(edge["id"])["feasibility_status"] == "FEASIBLE"
    assert read_order(over["id"])["feasibility_status"] == "INFEASIBLE"


# ==========================================================================
# The empty required-document set
# ==========================================================================
def _empty_requirement_set_scenario():
    set_clock("2026-06-01T09:00:00Z")
    scenario = build_scenario(
        "quoted", visa_type="PASSPORT_RENEWAL", make_complete=False, require_passport_doc=False
    )
    return scenario


def test_a_catalogue_with_no_requirement_lines_yields_an_empty_derived_set(api):
    """PRD §3.4: "`required_doc_count` is the number of applying lines whose `is_required`
    is true."
    PRD §3.4: "A computed read exposes the derived set: it reports `required_doc_types` and
    `optional_doc_types` as the document classes in the required and non-required halves of
    the derived set, `required_doc_count` and `accepted_doc_count` as the traveller carries
    them, and `satisfied` as true exactly when `accepted_doc_count` equals
    `required_doc_count`."

    Design: Difficulty/boundary_precision_check/empty_required_document_set_leaves_applicant_complete_with_zero_documents
    """
    scenario = _empty_requirement_set_scenario()
    applicant_id = scenario["applicant_ids"][0]

    read = validate_success(api.get_required_documents(applicant_id, CASE_MANAGER))
    assert read["required_doc_count"] == 0
    assert read["accepted_doc_count"] == 0
    assert read["satisfied"] is True, "0 accepted equals 0 required, so the set is satisfied"

    _rows, meta = validate_paginated(api.list_applicant_documents(applicant_id, CASE_MANAGER))
    assert meta["total_count"] == 0, "no requirement line means no document slot at all"


def test_a_traveller_with_no_document_slots_completes_on_photo_and_form_alone(api):
    """PRD §3.7: "A traveller moves `PENDING → COMPLETE` exactly when **all four** of the
    following hold: every one of their document slots whose `is_required` is true has
    `review_status` `ACCEPTED`; exactly one of their photos has `compliance_status`
    `PASSED`; exactly one of their preparations has `prep_status` `PREPARED` or `SIGNED`
    **and** a `revision_used` equal to the `revision` of the currently `ACTIVE` form
    carrying the product's `form_code`; and, when the order's catalog item has
    `requires_appointment` true, one of their appointments has `booking_status` `ATTENDED`."

    Design: Difficulty/boundary_precision_check/empty_required_document_set_leaves_applicant_complete_with_zero_documents
    """
    scenario = _empty_requirement_set_scenario()
    applicant_id = scenario["applicant_ids"][0]
    photo = validate_success(
        api.upload_photo(
            applicant_id,
            {
                "taken_on": "2026-05-20",
                "head_height_ratio": 0.60,
                "background_code": "WHITE",
                "resolution_px": 800,
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    validate_success(
        api.run_compliance_check(photo["id"], CASE_MANAGER)
    )

    prepare_form(applicant_id, scenario["form"]["id"])

    assert read_applicant(applicant_id)["readiness_status"] == "COMPLETE", (
        "with an empty required set the photo and the preparation are the whole gate"
    )
    assert list_applicant_documents(applicant_id) == []


# ==========================================================================
# Rung 12 pre-empts rung 37 on the same submission
# ==========================================================================
def _self_submitted_order_with_a_reopened_balance():
    """A READY_FOR_SUBMISSION order quoted by cm-quote, fully collected, then upgraded
    in flight so the balance rung is armed too."""
    scenario = build_scenario("ready", require_passport_doc=True, visa_type="TOURIST")
    order_id = scenario["order_id"]
    scenario["order"] = change_service_level(order_id, "EXPEDITED")
    return scenario


def test_self_submission_reports_the_duty_violation_not_the_balance(api):
    """PRD §3.9: "Because rung 12 sits above all of them, an order that is simultaneously
    unfunded and self-submitted reports the duty violation, not the balance."
    PRD §3.9: "first the duty separation at rung 12 — the acting `X-User-ID` must differ
    from the order's `quoted_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES`, so
    the operator who priced the file may never be the operator who commits it"

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_preempts_outstanding_balance
    """
    scenario = _self_submitted_order_with_a_reopened_balance()
    order_id = scenario["order_id"]

    resp = api.submit_order(order_id, CASE_MANAGER)
    error = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert error["error_id"] != ApiErrorId.ERR_BALANCE_OUTSTANDING.value


def test_the_pre_empted_submission_leaves_the_reopened_balance_exactly_as_it_stood(api):
    """PRD §3.5: "The delta is the new subtotal minus the old subtotal, **plus a 2500-cent
    tier-upgrade administration fee**. That delta is added to `service_fee_quoted_cents`,
    and `total_quoted_cents` is recomputed as `government_fee_quoted_cents` plus the new
    `service_fee_quoted_cents`."
    PRD §3.6: "an in-flight tier upgrade that raises `total_quoted_cents` above the money
    already collected pushes a settled order from `COLLECTED` straight back to
    `PARTIALLY_COLLECTED`, writing no ledger row and leaving `workflow_status` exactly
    where it was"

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_preempts_outstanding_balance
    """
    scenario = _self_submitted_order_with_a_reopened_balance()
    order_id = scenario["order_id"]

    resp = api.submit_order(order_id, CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    stored = read_order(order_id)
    assert stored["total_quoted_cents"] == 31625
    assert stored["service_fee_quoted_cents"] == 15625
    assert stored["collected_cents"] == 26500
    assert stored["payment_status"] == "PARTIALLY_COLLECTED"
    assert stored["workflow_status"] == "READY_FOR_SUBMISSION"
    assert stored["submitted_at"] is None, "the refused submission stamps nothing"


# ==========================================================================
# Projection inputs: the cutoff hour and the turnaround override
# ==========================================================================
def test_effective_submission_date_rolls_over_at_the_cutoff_hour(api):
    """PRD §3.9: "When the calendar date of the logical clock is a business day at the
    order's consulate **and** the hour of the logical clock is strictly below that tier's
    cutoff hour, the effective submission date is that same calendar date. Otherwise it is
    that date advanced by one business day. The comparison against the cutoff is strict:
    submitting exactly *at* the cutoff hour rolls the file to the next business day."
    PRD §3.9: "The agency treats a file as submitted on a date that depends on the hour of
    day and the service level, because each tier has its own daily cutoff: hour **21** UTC
    for `STANDARD`, hour **18** UTC for `EXPEDITED` and hour **15** UTC for `RUSH`."

    Design: Corner/calculations/corner_effective_submission_date_rolls_over_at_the_cutoff_hour
    """
    set_clock("2026-06-01T20:00:00Z")
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"], service_level="STANDARD")
    new_applicant(order["id"], full_name="Cutoff One")

    before = validate_success(api.get_feasibility(order["id"], CASE_MANAGER))
    assert before["effective_submission_date"] == "2026-06-01", (
        f"hour 20 is strictly below the STANDARD cutoff of 21, got "
        f"{before['effective_submission_date']}"
    )

    set_clock("2026-06-01T21:00:00Z")
    at_cutoff = validate_success(api.get_feasibility(order["id"], CASE_MANAGER))
    assert at_cutoff["effective_submission_date"] == "2026-06-02", (
        f"exactly at the cutoff hour the file rolls forward, got "
        f"{at_cutoff['effective_submission_date']}"
    )


def test_catalog_turnaround_override_replaces_the_tier_default(api):
    """PRD §3.9: "When the order's catalog item carries a non-null
    `agency_turnaround_override_days`, that number of business days replaces the tier
    constant entirely — and the consequence is worth naming, because it is the trap in this
    calculation: upgrading the tier on such a product buys **no** turnaround improvement
    whatsoever, only a surcharge and a tighter cutoff. When the override is null, the tier
    default applies: **15** business days for `STANDARD`, **8** for `EXPEDITED`, **3** for
    `RUSH`."

    Design: Corner/calculations/corner_agency_turnaround_catalog_override_replaces_tier_default
    """
    set_clock("2026-06-01T09:00:00Z")
    overridden_catalog = new_catalog_item(
        visa_type="TOURIST", destination_country="IN", agency_turnaround_override_days=4
    )
    default_catalog = new_catalog_item(visa_type="TOURIST", destination_country="BR")
    overridden_order = new_order(overridden_catalog["id"], service_level="RUSH")
    default_order = new_order(default_catalog["id"], service_level="RUSH")
    new_applicant(overridden_order["id"], full_name="Ovr One")
    new_applicant(default_order["id"], full_name="Def One")

    overridden_read = validate_success(api.get_feasibility(overridden_order["id"], CASE_MANAGER))
    default_read = validate_success(api.get_feasibility(default_order["id"], CASE_MANAGER))

    assert overridden_read["agency_turnaround_days"] == 4, (
        f"the per-product override replaces the tier constant, got "
        f"{overridden_read['agency_turnaround_days']}"
    )
    assert default_read["agency_turnaround_days"] == 3, (
        f"RUSH defaults to 3 business days, got {default_read['agency_turnaround_days']}"
    )
    assert overridden_read["variant_used"] == "tier_nominal"


# ==========================================================================
# The submission rungs
# ==========================================================================
def test_submission_from_intake_reports_incompleteness_not_a_state_error(api):
    """PRD §2.9.2: "- **Submission:** `workflow_status` is `INTAKE` or
    `READY_FOR_SUBMISSION`. Both are admitted here on purpose — an `INTAKE` order that is
    genuinely not ready must fall through to rung 34 and report
    `ERR_REQUIRED_DOCUMENTS_INCOMPLETE`, not be masked by a state error."
    PRD §3.9: "then completeness at rung 34 — every traveller whose `readiness_status` is
    `PENDING` or `COMPLETE` must be `COMPLETE`, or the request is
    `ERR_REQUIRED_DOCUMENTS_INCOMPLETE`"

    Design: Corner/errors/corner_error_required_documents_incomplete_on_submit_from_intake
    """
    scenario = build_scenario(
        "intake", visa_type="TOURIST", require_passport_doc=True, make_complete=False
    )
    order_id = scenario["order_id"]
    applicant_id = scenario["applicant_ids"][0]
    assert scenario["order"]["workflow_status"] == "INTAKE"

    resp = api.submit_order(order_id, SUBMITTER)
    error = validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCUMENTS_INCOMPLETE.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    stored = read_order(order_id)
    assert stored["workflow_status"] == "INTAKE"
    assert stored["submitted_at"] is None
    assert read_applicant(applicant_id)["readiness_status"] == "PENDING"


def test_an_infeasible_order_submits_only_after_a_compliance_acknowledgment(api):
    """PRD §3.9: "then feasibility at rung 36 — `feasibility_status` must be `FEASIBLE` or
    `ACKNOWLEDGED_INFEASIBLE`, or the request is `ERR_TRAVEL_DATE_INFEASIBLE`"
    PRD §3.9: "The acknowledgment requires `feasibility_status` to be exactly `INFEASIBLE`
    and `workflow_status` to be `INTAKE` or `READY_FOR_SUBMISSION`; it moves `INFEASIBLE →
    ACKNOWLEDGED_INFEASIBLE` and stamps `acknowledged_by_user_id` with the acting
    `X-User-ID`."

    Design: Corner/errors/corner_error_travel_date_infeasible_on_submit
    """
    scenario = build_scenario(
        "ready", visa_type="PASSPORT_RENEWAL", travel_date="2026-06-30", return_date="2026-07-19"
    )
    order_id = scenario["order_id"]
    assert scenario["order"]["feasibility_status"] == "INFEASIBLE"

    refused = api.submit_order(order_id, SUBMITTER)
    validate_error(refused, ApiErrorId.ERR_TRAVEL_DATE_INFEASIBLE.value)

    acknowledged = validate_success(api.acknowledge_feasibility(order_id, COMPLIANCE))
    assert acknowledged["feasibility_status"] == "ACKNOWLEDGED_INFEASIBLE"
    assert acknowledged["acknowledged_by_user_id"] == COMPLIANCE_USER_ID

    submitted = validate_success(api.submit_order(order_id, SUBMITTER))
    assert submitted["workflow_status"] == "SUBMITTED"
    assert submitted["furthest_stage_reached"] == "SUBMITTED"


def test_rush_submission_at_the_cutoff_hour_is_refused_and_passes_a_minute_earlier(api):
    """PRD §3.9: "then the rush cutoff at rung 35 — when `service_level` is `RUSH`, the
    logical clock hour must be strictly below 15 and the current date must be a business
    day, or the request is `ERR_RUSH_CUTOFF_MISSED`"
    PRD §3.9: "A successful submission stamps `submitted_at` with the logical clock and
    `submitted_by_user_id` with the acting `X-User-ID`, computes and writes
    `effective_submission_date`, raises `furthest_stage_reached` to `SUBMITTED`"

    Design: Corner/errors/corner_error_rush_cutoff_missed_on_submit
    """
    scenario = build_scenario("ready", service_level="RUSH", visa_type="PASSPORT_RENEWAL")
    order_id = scenario["order_id"]
    assert scenario["order"]["total_quoted_cents"] == 32500

    set_clock("2026-06-01T15:00:00Z")
    refused = api.submit_order(order_id, SUBMITTER)
    validate_error(refused, ApiErrorId.ERR_RUSH_CUTOFF_MISSED.value)
    assert read_order(order_id)["total_quoted_cents"] == 32500

    set_clock("2026-06-01T14:59:00Z")
    submitted = validate_success(api.submit_order(order_id, SUBMITTER))
    assert submitted["workflow_status"] == "SUBMITTED"
    assert submitted["effective_submission_date"] == "2026-06-01", (
        "hour 14 is strictly below the RUSH cutoff of 15 on a business day"
    )
