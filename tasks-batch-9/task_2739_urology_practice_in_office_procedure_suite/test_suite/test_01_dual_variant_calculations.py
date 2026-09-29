"""
Dual-variant calculations of the Urology Procedure Suite contract.

Two derived values in this contract are produced by a *pair* of formulas rather
than by one, and the stored discriminator records which of the pair last ran.
A surveillance recall's ``due_on`` is measured either from the recall's own
``anchor_date`` (``PROTOCOL_ANCHORED``) or from the patient's most recent
completed surveillance case (``EVENT_ANCHORED``); a consignment lot's
``billed_amount_cents`` is assembled either from the lines a case merely holds
(``PROVISIONAL``) or from the lines a case has actually spent (``FINAL``).

Both pairs are exercised here on one unchanged set of stored inputs, so the only
thing that can move the answer is which variant ran.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_fields,
    assert_lot_counters,
    assert_lot_ledger_conserved,
)
from test_helpers.constants import (
    ALLERGY_NONE,
    BASIS_EVENT_ANCHORED,
    BASIS_PROTOCOL_ANCHORED,
    BILLING_FINAL,
    BILLING_PROVISIONAL,
    BILLING_STATUS_CONSIGNED,
    BILLING_STATUS_PARTIALLY_INVOICED,
    CASE_COMPLETED,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_STATE_CONSUMED,
    PROTOCOL_BLADDER_CANCER,
    RECALL_SCHEDULED_DUE,
    ROOM_TYPE_CYSTO_SUITE,
    TIER_INTERMEDIATE,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)

BIOPSY_NEEDLE_SKU = "BX-NEEDLE-18G"


# ─── Local setup helpers ───────────────────────────────────────────────────
def _register_patient(api, roster, **kwargs):
    """Register a patient as the practice's scheduler."""
    response = api.create_patient(
        factories.patient_payload(
            primary_urologist_id=roster.urologist["id"], **kwargs
        ),
        roster.scheduler_headers,
    )
    return get_success_data(response, 201)


def _setup_recall_opened_after_a_completed_cystoscopy(api, roster):
    """
    A patient with one COMPLETED cystoscopy on 2026-09-14, and — opened only
    afterwards, so the completion's satisfaction cascade cannot have touched it
    — one BLADDER_CANCER / INTERMEDIATE recall anchored on 2026-03-31.
    """
    room = fixtures.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fixtures.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )
    patient = _register_patient(
        api,
        roster,
        mrn="MRN-4101",
        full_name="Ivan Cole",
        date_of_birth="1962-04-11",
        egfr=60,
        anticoagulant_flag=False,
        antibiotic_allergy_class=ALLERGY_NONE,
    )

    fixtures.set_clock(api, "2026-09-14T14:00:00Z")
    case = fixtures.schedule_new_case(
        api, roster, patient, cysto_type, room, "2026-09-14T14:00:00.000Z"
    )
    fixtures.clear_case(api, roster, case["id"])
    fixtures.check_in_case(api, roster, case["id"])
    completed = fixtures.complete_case(
        api, roster, case["id"], headers=roster.urologist_headers
    )
    assert completed["schedule_status"] == CASE_COMPLETED, (
        "the surveillance cystoscopy must be COMPLETED before the recall is "
        f"opened, got {completed['schedule_status']!r}"
    )

    current_patient = fixtures.read_patient(api, roster, patient["id"])
    create_response = api.create_surveillance_recall(
        factories.surveillance_recall_payload(
            patient_id=patient["id"],
            expected_patient_version=current_patient["version"],
            protocol=PROTOCOL_BLADDER_CANCER,
            risk_tier=TIER_INTERMEDIATE,
            anchor_date="2026-03-31",
        ),
        roster.urologist_headers,
    )
    return {
        "patient": patient,
        "case": completed,
        "create_response": create_response,
    }


def _setup_biopsy_case_holding_three_needles(api, roster):
    """
    One prostate-biopsy case checked in at 2026-09-14T08:00Z holding three
    biopsy needles from a ten-unit lot priced at 1999 cents a unit.
    """
    room = fixtures.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    biopsy_type = fixtures.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=True,
        single_use_device_sku=BIOPSY_NEEDLE_SKU,
        required_prep_codes=[],
    )
    patient = _register_patient(
        api,
        roster,
        mrn="MRN-4102",
        full_name="Rosa Vance",
        date_of_birth="1958-02-02",
        egfr=60,
        anticoagulant_flag=False,
        antibiotic_allergy_class=ALLERGY_NONE,
    )
    lot = fixtures.create_lot(
        api,
        supplier_name="Meridian Devices",
        sku=BIOPSY_NEEDLE_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=1999,
        lot_expires_on="2027-06-30",
    )

    fixtures.set_clock(api, "2026-09-14T08:00:00Z")
    case = fixtures.draft_case(
        api, roster, patient, biopsy_type, room, "2026-09-14T08:00:00.000Z"
    )
    fixtures.reserve_device(api, roster, case["id"], lot, quantity=3)
    fixtures.commit_case(api, roster, case, room)
    fixtures.clear_case(api, roster, case["id"])
    fixtures.check_in_case(api, roster, case["id"])
    return {"case": case, "lot": lot, "patient": patient}


# ─── The recall due-date variant pair ──────────────────────────────────────
def test_recall_created_is_protocol_anchored_from_its_own_anchor_date(api, roster):
    """PRD §3.9: "**At creation the variant is always `PROTOCOL_ANCHORED`**: the
    interval is measured from the recall's own `anchor_date`, and the patient's
    procedure history is not consulted at all."
    PRD §3.9: "**The recall interval is a lookup on the pair of `protocol` and
    `risk_tier`, and it lands in `interval_months`.**"
    PRD §3.9: "`BLADDER_CANCER` runs on a tighter cadence: 12 months at `LOW`, 6
    at `INTERMEDIATE`, 3 at `HIGH`."
    PRD §3.9: "A recall anchored on 31 March with a six-month interval is due on
    30 September, not 1 October."

    Design: Difficulty/dual_variant_calc/dv_recall_protocol_vs_event_anchored
    """
    scene = _setup_recall_opened_after_a_completed_cystoscopy(api, roster)

    recall = validate_success(scene["create_response"], 201)

    assert_fields(
        recall,
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_INTERMEDIATE,
        anchor_date="2026-03-31",
        interval_months=6,
        due_on="2026-09-30",
        due_basis=BASIS_PROTOCOL_ANCHORED,
        status=RECALL_SCHEDULED_DUE,
        lapse_days=0,
    )
    assert recall["due_on"] == "2026-09-30", (
        "a BLADDER_CANCER / INTERMEDIATE recall anchored on 2026-03-31 is due "
        "six months later with the day clamped to the last valid day of "
        f"September, expected 2026-09-30, got {recall['due_on']!r}"
    )


def test_recall_sweep_reanchors_due_date_to_the_completed_cystoscopy(api, roster):
    """PRD §3.9: "Step 1 recomputes `due_on` for every recall whose `status` is
    `SCHEDULED_DUE` or `OVERDUE`, this time under the `EVENT_ANCHORED` variant."
    PRD §3.9: "If the set is non-empty, the anchoring case is the one with the
    latest `scheduled_start_at`, and where two share the same start instant the
    one created later wins; `due_on` becomes the interval added to the date part
    of that case's `scheduled_start_at`, and `due_basis` is written as
    `EVENT_ANCHORED`."
    PRD §3.9: "The two variants genuinely disagree on the same row — a
    `BLADDER_CANCER` recall at `INTERMEDIATE` risk anchored on 2026-03-31 is due
    2026-09-30 while it is protocol-anchored, but once a qualifying
    `CYSTOSCOPY` completes the due date moves to six months after that
    cystoscopy instead."

    Design: Difficulty/dual_variant_calc/dv_recall_protocol_vs_event_anchored
    """
    scene = _setup_recall_opened_after_a_completed_cystoscopy(api, roster)
    recall = validate_success(scene["create_response"], 201)
    assert recall["due_on"] == "2026-09-30", (
        "precondition: the freshly opened recall must be protocol-anchored on "
        f"2026-09-30, got {recall['due_on']!r}"
    )

    fixtures.run_sweep(api, roster.urologist_headers)

    swept = validate_success(
        api.get_surveillance_recall(recall["id"], roster.urologist_headers)
    )
    assert_fields(
        swept,
        due_on="2027-03-14",
        due_basis=BASIS_EVENT_ANCHORED,
        anchor_date="2026-03-31",
        interval_months=6,
    )
    assert swept["due_on"] == "2027-03-14", (
        "the event-anchored variant measures the six-month interval from the "
        "date part of the completed cystoscopy's scheduled_start_at "
        f"(2026-09-14), expected 2027-03-14, got {swept['due_on']!r}"
    )


def test_recall_sweep_leaves_a_reanchored_recall_scheduled_due_with_no_lapse(
    api, roster
):
    """PRD §3.9: "A recall sitting at `SCHEDULED_DUE` whose `due_on` is now
    strictly before the logical clock's date moves to `OVERDUE`, and
    `lapse_days` is set to the whole number of days from `due_on` to the clock
    date, floored at zero."
    PRD §3.9: "Because step 1 always runs before step 2 inside a single sweep, a
    recall whose event-anchored due date has just moved into the future never
    appears as `OVERDUE` at all in that sweep — it is recomputed first and never
    lapses."
    PRD §3.9: "Its response carries `swept_at` holding the logical clock instant
    of the sweep, `recomputed_recall_count` for the number of recalls step 1
    recomputed, `overdue_recall_count` for the number step 2 moved into
    `OVERDUE`, `restored_recall_count` for the number step 2 pulled back to
    `SCHEDULED_DUE`, and `escalated_specimen_count` for the number of
    notifications step 3 escalated."

    Design: Difficulty/dual_variant_calc/dv_recall_protocol_vs_event_anchored
    """
    scene = _setup_recall_opened_after_a_completed_cystoscopy(api, roster)
    recall = validate_success(scene["create_response"], 201)

    sweep = validate_success(api.run_recall_sweep({}, roster.urologist_headers))

    assert_fields(
        sweep,
        recomputed_recall_count=1,
        overdue_recall_count=0,
        restored_recall_count=0,
        escalated_specimen_count=0,
    )

    swept = validate_success(
        api.get_surveillance_recall(recall["id"], roster.urologist_headers)
    )
    assert_fields(swept, status=RECALL_SCHEDULED_DUE, lapse_days=0)


# ─── The consignment billing variant pair ──────────────────────────────────
def test_lot_bills_provisionally_while_the_three_needles_are_merely_reserved(
    api, roster
):
    """PRD §3.6: "The `PROVISIONAL` variant runs whenever units are merely held
    or handed back while still unspent — that is, on a device reservation, on a
    case cancellation and on a case no-show. Its factor is 1 plus the 18.5%
    consignment markup, so 1.185, and it sums only the lines whose
    `device_state` is `RESERVED`."
    PRD §3.6: "Each line's value is the lot's `unit_price_cents` multiplied by
    the applicable factor, multiplied by that case's `device_quantity`, and then
    **rounded half up to a whole number of cents**."
    PRD §3.6: "`billing_status` is a **compound status derived entirely from the
    lot's own unit counters**, never supplied by a client, and it is re-derived
    after every mutation of those counters using the following ordered tests."
    PRD §3.6: "Otherwise it remains `CONSIGNED`."

    Design: Difficulty/dual_variant_calc/dv_consignment_provisional_vs_final
    """
    scene = _setup_biopsy_case_holding_three_needles(api, roster)

    lot = validate_success(
        api.get_consignment_lot(scene["lot"]["id"], roster.admin_headers)
    )

    assert_fields(
        lot,
        unit_price_cents=1999,
        billed_amount_cents=7106,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_CONSIGNED,
    )
    assert lot["billed_amount_cents"] == 7106, (
        "one reserved line of three units at 1999 cents under the provisional "
        "1.185 factor rounds half up to 7106 cents, got "
        f"{lot['billed_amount_cents']}"
    )
    assert_lot_counters(lot, available=7, reserved=3, consumed=0, returned=0, wasted=0)


def test_case_completion_rebills_the_lot_on_the_final_basis_with_the_volume_rebate(
    api, roster
):
    """PRD §3.6: "The `FINAL` variant runs once units have actually been spent —
    that is, on a case completion and on a supplier return. Its factor is 1 plus
    the 18.5% markup, less a 5-percentage-point volume rebate whenever the lot's
    `quantity_consumed` has reached at least 3; with the rebate active the factor
    is therefore 1.135 and without it 1.185. It sums only the lines whose
    `device_state` is `CONSUMED` or `WASTED`."
    PRD §3.6: "Completing the case moves them to `CONSUMED`: `device_state`
    becomes `CONSUMED`, the lot's `quantity_reserved` falls and its
    `quantity_consumed` rises by `device_quantity`, and the lot is re-billed on
    the **final** basis."
    PRD §3.6: "Otherwise, if the sum of `quantity_consumed` and
    `quantity_wasted` is at least 1, the lot is `PARTIALLY_INVOICED`."

    Design: Difficulty/dual_variant_calc/dv_consignment_provisional_vs_final
    """
    scene = _setup_biopsy_case_holding_three_needles(api, roster)

    completed = validate_success(
        api.complete_case(scene["case"]["id"], {}, roster.urologist_headers)
    )
    assert_fields(
        completed,
        schedule_status=CASE_COMPLETED,
        device_state=DEVICE_STATE_CONSUMED,
        device_quantity=3,
    )

    lot = validate_success(
        api.get_consignment_lot(scene["lot"]["id"], roster.admin_headers)
    )
    assert_fields(
        lot,
        billed_amount_cents=6807,
        billing_basis=BILLING_FINAL,
        billing_status=BILLING_STATUS_PARTIALLY_INVOICED,
    )
    assert lot["billed_amount_cents"] == 6807, (
        "one consumed line of three units at 1999 cents under the final 1.135 "
        "factor — the volume rebate is active because quantity_consumed reached "
        f"3 — rounds half up to 6807 cents, got {lot['billed_amount_cents']}"
    )
    assert_lot_counters(lot, available=7, reserved=0, consumed=3, returned=0, wasted=0)


def test_final_and_provisional_bases_differ_by_299_cents_on_identical_unit_counts(
    api, roster
):
    """PRD §3.6: "Two variants of that calculation exist, and `billing_basis`
    records which of them last ran."
    PRD §3.6: "Its factor is 1 plus the 18.5% consignment markup, so 1.185, and
    it sums only the lines whose `device_state` is `RESERVED`."
    PRD §3.6: "Its factor is 1 plus the 18.5% markup, less a 5-percentage-point
    volume rebate whenever the lot's `quantity_consumed` has reached at least 3;
    with the rebate active the factor is therefore 1.135 and without it 1.185."
    PRD §2.10: "For a consignment lot, `quantity_received` is the conserved
    total: at every observable moment it equals the sum of `quantity_available`,
    `quantity_reserved`, `quantity_consumed`, `quantity_returned` and
    `quantity_wasted`."

    Design: Difficulty/dual_variant_calc/dv_consignment_provisional_vs_final
    """
    scene = _setup_biopsy_case_holding_three_needles(api, roster)

    provisional = validate_success(
        api.get_consignment_lot(scene["lot"]["id"], roster.admin_headers)
    )
    assert provisional["billing_basis"] == BILLING_PROVISIONAL, (
        "before completion the lot's last billing run is the provisional one, "
        f"got {provisional['billing_basis']!r}"
    )
    assert_lot_ledger_conserved(provisional)

    validate_success(api.complete_case(scene["case"]["id"], {}, roster.urologist_headers))

    final = validate_success(
        api.get_consignment_lot(scene["lot"]["id"], roster.admin_headers)
    )
    assert final["billing_basis"] == BILLING_FINAL, (
        "completion re-bills the lot on the final basis, got "
        f"{final['billing_basis']!r}"
    )
    assert_lot_ledger_conserved(final)

    assert provisional["billed_amount_cents"] == 7106, (
        "provisional total on three held units at 1999 cents must be 7106, got "
        f"{provisional['billed_amount_cents']}"
    )
    assert final["billed_amount_cents"] == 6807, (
        "final total on the same three units at 1999 cents must be 6807, got "
        f"{final['billed_amount_cents']}"
    )
    delta = final["billed_amount_cents"] - provisional["billed_amount_cents"]
    assert delta == -299, (
        "the same three units bill 299 cents less once the volume rebate turns "
        f"the 1.185 factor into 1.135, expected a delta of -299, got {delta}"
    )
