"""Message threads, e-visit conversion and the superbill loop."""

from test_helpers import (
    ApiErrorId,
    assert_encounter,
    assert_message_thread,
    assert_superbill,
    draft_superbill,
    make_nd_headers,
    read_membership,
    read_patient,
    setup_completed_encounter,
    setup_thread_at_message_threshold,
    superbill_transition,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BILLING


def _superbilled_member_visit(api, duration_minutes=75):
    """CORE member, one completed TELEHEALTH visit and a DRAFT superbill."""
    ctx = setup_completed_encounter(
        api,
        membership_tier="CORE",
        modality="TELEHEALTH",
        duration_minutes=duration_minutes,
        patient_overrides={"telehealth_consent": True},
        encounter_overrides={
            "scheduled_start": "2026-06-01T15:00:00Z",
            "scheduled_end": "2026-06-01T16:30:00Z",
        },
    )
    ctx["superbill"] = draft_superbill(api, ctx["patient"]["id"], ctx["encounter"]["id"])
    return ctx


def test_issuing_a_superbill_partitions_the_cash_from_the_covered_base_fee(api):
    """PRD §3.9: "Drafting copies the encounter's `diagnosis_codes` and
    `service_code` onto the superbill and copies the rendering practitioner's
    `npi` into `rendering_practitioner_npi`, then partitions the value three
    ways: `billable_total_cents` is the encounter's `cash_charged_cents` and
    nothing else; `non_billable_membership_cents` is the base fee that
    membership entitlement absorbed, reported for the patient's information but
    never billable; and `excluded_supplement_cents` is the value of supplements
    dispensed to that patient under the encounter's protocol, likewise reported
    and never billable."
    PRD §3.9: "**`ISSUE`** moves `DRAFT → ISSUED` and stamps `issued_at`."

    Design: Difficulty/non_linear_state_machine/encounter_scheduling_and_billing_axes_advance_independently
    """
    ctx = _superbilled_member_visit(api)
    issued = superbill_transition(api, ctx["superbill"]["id"], "ISSUE")

    assert_superbill(issued)
    assert issued["status"] == "ISSUED"
    assert issued["billable_total_cents"] == 9000
    assert issued["non_billable_membership_cents"] == 18000


def test_the_billing_axis_moves_to_superbilled_while_scheduling_stays_completed(api):
    """PRD §3.3: "An `Encounter` runs on **two entirely independent axes**."
    PRD §3.9: "On success the referenced encounter's billing axis advances to
    `SUPERBILLED`, from `ENTITLEMENT_CONSUMED` when the encounter still charged
    some cash for extended time, or from `CASH_CHARGED`."

    Design: Difficulty/non_linear_state_machine/encounter_scheduling_and_billing_axes_advance_independently
    """
    ctx = _superbilled_member_visit(api)
    superbill_transition(api, ctx["superbill"]["id"], "ISSUE")

    encounter = validate_success(
        api.get_encounter(ctx["encounter"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert_encounter(encounter)
    assert encounter["billing_status"] == "SUPERBILLED"
    assert encounter["scheduling_status"] == "COMPLETED"

    membership = read_membership(api, ctx["patient"]["id"])
    assert membership["visits_consumed"] == 1


def test_a_fully_covered_visit_leaves_the_superbill_with_nothing_to_bill(api):
    """PRD §3.3: "When the encounter reserved a visit unit at booking and its
    billing axis is `ENTITLEMENT_RESERVED`, `cash_charged_cents` is set to the
    extended-time charge alone — the base fee is absorbed by the visit unit —
    and the axis advances `ENTITLEMENT_RESERVED → ENTITLEMENT_CONSUMED`."
    PRD §3.9: "`billable_total_cents` is the encounter's `cash_charged_cents`
    and nothing else"

    Design: Difficulty/boundary_precision_check/superbill_with_zero_billable_cents_cannot_be_issued
    """
    ctx = _superbilled_member_visit(api, duration_minutes=40)

    encounter = validate_success(
        api.get_encounter(ctx["encounter"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert encounter["cash_charged_cents"] == 0
    assert encounter["billing_status"] == "ENTITLEMENT_CONSUMED"

    superbill = validate_success(api.get_superbill(ctx["superbill"]["id"], BILLING))
    assert superbill["billable_total_cents"] == 0
    assert superbill["non_billable_membership_cents"] == 18000


def test_issuing_a_superbill_with_zero_billable_cents_is_refused(api):
    """PRD §3.9: "It requires the referenced encounter's `scheduling_status` to
    be `COMPLETED`, and it requires the document to actually document cash:
    `billable_total_cents` must be greater than 0, `diagnosis_codes` must be
    non-empty, and `rendering_practitioner_npi` must not be null. An encounter
    fully absorbed by membership entitlement has a billable total of 0 and is
    refused with `ERR_SUPERBILL_NOT_BILLABLE`."

    Design: Difficulty/boundary_precision_check/superbill_with_zero_billable_cents_cannot_be_issued
    """
    ctx = _superbilled_member_visit(api, duration_minutes=40)

    response = api.create_superbill_transition(
        ctx["superbill"]["id"], {"action": "ISSUE"}, BILLING
    )
    validate_error(response, ApiErrorId.ERR_SUPERBILL_NOT_BILLABLE.value, 422)

    unchanged = validate_success(api.get_superbill(ctx["superbill"]["id"], BILLING))
    assert unchanged["status"] == "DRAFT"

    encounter = validate_success(
        api.get_encounter(ctx["encounter"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert encounter["billing_status"] == "ENTITLEMENT_CONSUMED"


def test_voiding_then_reissuing_returns_the_encounter_and_bumps_the_revision(api):
    """PRD §3.9: "**`VOID`** moves `ISSUED → VOIDED`, storing the `void_reason`,
    and sends the encounter's billing axis back the way it came: to
    `ENTITLEMENT_CONSUMED` when that encounter's `entitlement_consumed` is true,
    and to `CASH_CHARGED` otherwise. This is why `SUPERBILLED` is not an
    absorbing state."
    PRD §3.9: "**`REISSUE`** moves `VOIDED → DRAFT` and is permitted only while
    `revision_no` is still below 3. It increments `revision_no` by 1 and
    re-copies `diagnosis_codes`, `service_code`, `rendering_practitioner_npi`
    and all three money partitions from the encounter's current state, so a
    corrected encounter yields a corrected superbill."

    Design: Corner/state_machines/superbill_void_then_reissue_increments_revision_and_reverts_the_encounter
    """
    ctx = setup_completed_encounter(api, modality="IN_PERSON", duration_minutes=60)
    nd, patient, encounter = ctx["nd"], ctx["patient"], ctx["encounter"]
    assert encounter["cash_charged_cents"] == 27000

    superbill = draft_superbill(api, patient["id"], encounter["id"])
    superbill_transition(api, superbill["id"], "ISSUE")

    voided = superbill_transition(
        api, superbill["id"], "VOID", void_reason="wrong service code"
    )
    assert voided["status"] == "VOIDED"
    reverted = validate_success(
        api.get_encounter(encounter["id"], make_nd_headers(nd["id"]))
    )
    assert reverted["billing_status"] == "CASH_CHARGED"

    reissued = superbill_transition(api, superbill["id"], "REISSUE")
    assert reissued["status"] == "DRAFT"
    assert reissued["revision_no"] == 2
    assert reissued["billable_total_cents"] == 27000


def test_a_thread_at_the_message_threshold_converts_into_a_billable_evisit(api):
    """PRD §3.9: "The thread crosses the volume threshold when
    `patient_message_count` reaches 4 or when `clinical_minutes_total` reaches
    15; both comparisons are inclusive, so exactly four patient messages or
    exactly fifteen accumulated clinical minutes already qualifies, and either
    one alone is enough."
    PRD §3.9: "Conversion mints an `Encounter` with `modality` of `EVISIT`, its
    `source_thread_id` pointing back at this thread, `duration_minutes` of 15,
    and both axes already resolved: `scheduling_status` is `COMPLETED` with
    `completed_at` stamped, and `billing_status` is `CASH_CHARGED` with
    `cash_charged_cents` of 9500 — the e-visit fee."

    Design: Corner/endpoints/thread_conversion_mints_a_completed_billable_evisit_encounter
    """
    ctx = setup_thread_at_message_threshold(api, membership_tier="FOUNDATION")
    nd, patient, thread = ctx["nd"], ctx["patient"], ctx["thread"]

    assert_message_thread(thread)
    assert thread["patient_message_count"] == 4
    assert thread["evisit_conversion_eligible"] is True

    response = api.convert_thread_to_evisit(thread["id"], make_nd_headers(nd["id"]))
    encounter = validate_success(response, 201)

    assert encounter["modality"] == "EVISIT"
    assert encounter["scheduling_status"] == "COMPLETED"
    assert encounter["billing_status"] == "CASH_CHARGED"
    assert encounter["cash_charged_cents"] == 9500
    assert encounter["source_thread_id"] == thread["id"]

    converted = validate_success(
        api.get_message_thread(thread["id"], make_nd_headers(nd["id"]))
    )
    assert converted["status"] == "CONVERTED_TO_EVISIT"

    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 9500
    assert read_membership(api, patient["id"])["visits_remaining"] == 2


def test_a_messaging_inclusive_tier_suppresses_conversion_eligibility(api):
    """PRD §3.9: "But eligibility is then withheld from members who already pay
    for messaging: `evisit_conversion_eligible` is true only when the volume
    threshold is crossed **and** the patient does not hold a membership in
    status `ACTIVE` whose tier includes messaging. `CORE` and `PREMIER` include
    messaging; `FOUNDATION` does not."
    PRD §3.9: "an ineligible thread is refused with
    `ERR_DEPENDENT_STATE_INVALID`"

    Design: Corner/calculations/evisit_conversion_suppressed_when_the_tier_includes_messaging
    """
    ctx = setup_thread_at_message_threshold(api, membership_tier="CORE")
    nd, thread = ctx["nd"], ctx["thread"]

    assert thread["patient_message_count"] == 4
    assert thread["status"] == "OPEN"
    assert thread["evisit_conversion_eligible"] is False

    response = api.convert_thread_to_evisit(thread["id"], make_nd_headers(nd["id"]))
    validate_error(response, ApiErrorId.ERR_DEPENDENT_STATE_INVALID.value, 409)

    rows, meta = validate_paginated(
        api.list_encounters(
            make_nd_headers(nd["id"]), params={"source_thread_id": thread["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []
