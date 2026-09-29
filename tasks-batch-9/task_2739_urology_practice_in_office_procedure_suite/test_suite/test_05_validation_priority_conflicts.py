"""
Multiply-invalid requests: which single error the validation ladder reports.

A single well-formed request can violate more than one business rule of the
urology suite at once. The contract fixes a total priority order over its
checks, so the caller always sees exactly one error and which one is fully
determined. The two scenarios exercised here are the pairs the contract calls
out by name: a check-in that is neither cleared nor prophylaxed, and a device
reservation against a lot that is both expired and short of stock. Each
scenario also reads the surrounding state back to prove the server knew about
both violations and chose between them rather than noticing only one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ANTIBIOTIC_NOT_ADMINISTERED,
    ERR_CASE_NOT_CLEARED,
    ERR_CONSIGNMENT_INSUFFICIENT,
    ERR_LOT_EXPIRED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_readiness,
    assert_version_unchanged,
)
from test_helpers.constants import (
    CASE_DRAFT,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    CLEARANCE_CLEARED,
    CLEARANCE_PENDING_PREP,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_STATE_NONE,
    GATE_ANTIBIOTIC_NOT_ADMINISTERED,
    GATE_CLEARANCE_NOT_GRANTED,
    ROOM_TYPE_CYSTO_SUITE,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)

# ─── Pair one: check-in clearance against prophylaxis ───────────────────────

CHECKIN_START_AT = "2026-09-14T14:00:00Z"
CHECKIN_CLOCK = "2026-09-14T14:00:00Z"
PREP_CODE_NPO_MIDNIGHT = "NPO_MIDNIGHT"


def _build_uncleared_unprophylaxed_case(api):
    """
    A cystoscopy that requires prophylaxis, sitting on the calendar with its
    clearance never granted and no antibiotic ever ordered — so both the
    clearance gate and the prophylaxis gate are unmet at the same time.

    The room is a cystoscopy suite, which carries no accreditation obligation,
    and the logical clock is moved to exactly the case's ``scheduled_start_at``
    so the early-arrival gate cannot contribute.
    """
    roster = fx.build_roster(api)
    room = fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, turnover_minutes=10)
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=True,
        consignment_required=False,
        required_prep_codes=[PREP_CODE_NPO_MIDNIGHT],
    )
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Elle Barros",
        date_of_birth="1974-09-02",
        egfr=60,
        antibiotic_allergy_class="NONE",
    )
    fx.set_clock(api, CHECKIN_CLOCK, roster.admin_headers)
    case = fx.draft_case(
        api, roster, patient, procedure_type, room, CHECKIN_START_AT
    )
    case = fx.commit_case(api, roster, case, room)
    assert_fields(
        case,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
    )
    return roster, case


def test_checkin_reports_clearance_not_granted_over_missing_prophylaxis(api):
    """PRD §2.8: "A check-in of a case that is neither cleared nor waived *and*
    has no administered prophylaxis reports `ERR_CASE_NOT_CLEARED` (priority
    40), not `ERR_ANTIBIOTIC_NOT_ADMINISTERED` (priority 48)."

    Design: Difficulty/priority_pair_validation_conflict/pp_checkin_clearance_beats_antibiotic
    """
    roster, case = _build_uncleared_unprophylaxed_case(api)

    response = api.check_in_case(case["id"], {}, roster.nurse_headers)

    # The two candidate rules differ in HTTP status as well as identifier, so
    # the registered status of ERR_CASE_NOT_CLEARED (409) is checked too: an
    # implementation reaching the prophylaxis rule first would answer 422.
    validate_error(response, ERR_CASE_NOT_CLEARED)


def test_rejected_checkin_leaves_the_case_scheduled_and_unstamped(api):
    """PRD §3.7: "On success the case's `checked_in_at` records the logical
    clock instant and `blocking_reason_codes` collapses to the empty array."
    PRD §2.8: "A check-in of a case that is neither cleared nor waived *and*
    has no administered prophylaxis reports `ERR_CASE_NOT_CLEARED` (priority
    40), not `ERR_ANTIBIOTIC_NOT_ADMINISTERED` (priority 48)."

    Design: Difficulty/priority_pair_validation_conflict/pp_checkin_clearance_beats_antibiotic
    """
    roster, case = _build_uncleared_unprophylaxed_case(api)

    validate_error(
        api.check_in_case(case["id"], {}, roster.nurse_headers), ERR_CASE_NOT_CLEARED
    )

    after = validate_success(api.get_procedure_case(case["id"], roster.nurse_headers))
    assert_fields(
        after,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
        checked_in_at=None,
    )
    assert_version_unchanged(case, after)


def test_readiness_lists_both_unmet_gates_with_clearance_first(api):
    """PRD §3.7: "That ordering is not arbitrary: it is exactly the
    validation-priority order of §2.8, which is why the first element of
    `blocking_reason_codes` is always the very gate a check-in attempt would
    report."
    PRD §3.7: "It reports the `case_id`, both dimensions as `schedule_status`
    and `clearance_status`, the ordered `blocking_reason_codes`, the
    convenience field `first_blocking_reason_code` — the first element of that
    array, or null when the array is empty — and `check_in_allowed`, a boolean
    that is true exactly when the case's `schedule_status` is `SCHEDULED` and
    the gate array is empty."

    Design: Difficulty/priority_pair_validation_conflict/pp_checkin_clearance_beats_antibiotic
    """
    roster, case = _build_uncleared_unprophylaxed_case(api)

    readiness = validate_success(
        api.get_case_readiness(case["id"], roster.nurse_headers)
    )

    # Both violations are known to the server; the projection proves it is
    # choosing between them rather than noticing only the first.
    assert_readiness(
        readiness,
        [GATE_CLEARANCE_NOT_GRANTED, GATE_ANTIBIOTIC_NOT_ADMINISTERED],
        check_in_allowed=False,
    )
    assert_fields(
        readiness,
        case_id=case["id"],
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
    )


def test_prophylaxis_gate_surfaces_once_clearance_is_granted(api):
    """PRD §2.8: "When the case's procedure type has `requires_antibiotic`
    true, at least one antibiotic order on the case has `status`
    `ADMINISTERED`. Otherwise `ERR_ANTIBIOTIC_NOT_ADMINISTERED`, HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/pp_checkin_clearance_beats_antibiotic
    """
    roster, case = _build_uncleared_unprophylaxed_case(api)

    # Discharge the higher-priority violation only: acknowledge the single
    # required instruction and grant clearance. No antibiotic is ever ordered.
    fx.acknowledge_all_prep(api, roster, case["id"], [PREP_CODE_NPO_MIDNIGHT])
    cleared = fx.clear_case(api, roster, case["id"])
    assert_fields(cleared, clearance_status=CLEARANCE_CLEARED)

    readiness = validate_success(
        api.get_case_readiness(case["id"], roster.nurse_headers)
    )
    assert_readiness(
        readiness, [GATE_ANTIBIOTIC_NOT_ADMINISTERED], check_in_allowed=False
    )

    validate_error(
        api.check_in_case(case["id"], {}, roster.nurse_headers),
        ERR_ANTIBIOTIC_NOT_ADMINISTERED,
    )


# ─── Pair two: lot expiry against insufficient stock ────────────────────────

BIOPSY_START_AT = "2026-09-14T14:00:00Z"
BIOPSY_CLOCK = "2026-09-14T08:00:00Z"
BIOPSY_NEEDLE_SKU = "BX-NEEDLE-18G"


def _build_reservation_scenario(api, lot_expires_on):
    """
    A prostate biopsy whose type demands a consigned needle, and a single-unit
    lot of exactly the catalogue number that type names — so the device
    catalogue rule is deliberately satisfied and the ladder has to be walked
    past it. The lot's expiry date is the caller's choice; the logical clock is
    at 2026-09-14, so an expiry of 2026-08-31 is a fortnight stale.

    The case stays a draft: holding units carries no calendar precondition.
    """
    roster = fx.build_roster(api)
    room = fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, turnover_minutes=10)
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        consignment_required=True,
        single_use_device_sku=BIOPSY_NEEDLE_SKU,
        required_prep_codes=[],
    )
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Ines Kovac",
        date_of_birth="1960-12-14",
        egfr=60,
    )
    lot = fx.create_lot(
        api,
        supplier_name="Meridian Devices",
        sku=BIOPSY_NEEDLE_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=1,
        unit_price_cents=1999,
        lot_expires_on=lot_expires_on,
    )
    fx.set_clock(api, BIOPSY_CLOCK, roster.admin_headers)
    case = fx.draft_case(
        api, roster, patient, procedure_type, room, BIOPSY_START_AT
    )
    assert_fields(case, schedule_status=CASE_DRAFT, device_state=DEVICE_STATE_NONE)
    return roster, case, lot


def test_device_reservation_reports_lot_expiry_over_insufficient_stock(api):
    """PRD §2.8: "A device reservation against an expired lot that also asks
    for more units than remain reports `ERR_LOT_EXPIRED` (priority 64), not
    `ERR_CONSIGNMENT_INSUFFICIENT` (priority 70)."
    PRD §3.6: "An expired lot that is also short of stock therefore reports the
    expiry, not the shortage."

    Design: Difficulty/priority_pair_validation_conflict/pp_reservation_lot_expiry_beats_insufficient
    """
    roster, case, lot = _build_reservation_scenario(api, lot_expires_on="2026-08-31")

    # Five units wanted against the one unit received: the stock rule is
    # violated as well, and both candidate rules answer HTTP 422, so only the
    # identifier can discriminate between them.
    response = api.reserve_device(
        case["id"],
        f.device_reservation_payload(lot["id"], 5, lot["version"]),
        roster.nurse_headers,
    )

    validate_error(response, ERR_LOT_EXPIRED)


def test_rejected_reservation_leaves_lot_and_case_untouched(api):
    """PRD §3.6: "On receipt `quantity_available` is set equal to
    `quantity_received` and `quantity_reserved`, `quantity_consumed`,
    `quantity_returned` and `quantity_wasted` all start at 0;
    `billed_amount_cents` starts at 0, `billing_basis` at `PROVISIONAL` and
    `billing_status` at `CONSIGNED`."
    PRD §3.6: "A successful hold writes `device_lot_id` and `device_quantity`
    onto the case and sets its `device_state` to `RESERVED`; the lot's
    `quantity_available` falls by the reserved quantity and its
    `quantity_reserved` rises by the same amount; the lot is re-billed
    provisionally, its `billing_status` re-derived and its `version`
    incremented by 1; and the case's readiness gates are recomputed."

    Design: Difficulty/priority_pair_validation_conflict/pp_reservation_lot_expiry_beats_insufficient
    """
    roster, case, lot = _build_reservation_scenario(api, lot_expires_on="2026-08-31")

    validate_error(
        api.reserve_device(
            case["id"],
            f.device_reservation_payload(lot["id"], 5, lot["version"]),
            roster.nurse_headers,
        ),
        ERR_LOT_EXPIRED,
    )

    lot_after = validate_success(
        api.get_consignment_lot(lot["id"], roster.nurse_headers)
    )
    assert_fields(
        lot_after,
        quantity_available=1,
        quantity_reserved=0,
        billed_amount_cents=0,
    )
    # No hold happened, so no optimistic-concurrency bump happened either.
    assert_version_unchanged(lot, lot_after)

    case_after = validate_success(
        api.get_procedure_case(case["id"], roster.nurse_headers)
    )
    assert_fields(case_after, device_state=DEVICE_STATE_NONE)
    assert case_after.get("device_lot_id") == case.get("device_lot_id"), (
        "a rejected reservation must not write device_lot_id onto the case: "
        f"was {case.get('device_lot_id')!r}, now {case_after.get('device_lot_id')!r}"
    )
    assert case_after.get("device_quantity") == case.get("device_quantity"), (
        "a rejected reservation must not write device_quantity onto the case: "
        f"was {case.get('device_quantity')!r}, now {case_after.get('device_quantity')!r}"
    )


def test_insufficient_stock_is_reported_once_the_lot_is_in_date(api):
    """PRD §3.6: "And the requested `quantity` must be no greater than the
    lot's `quantity_available`, or `ERR_CONSIGNMENT_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/pp_reservation_lot_expiry_beats_insufficient
    """
    # Identical to the pair scenario except that the lot is still in date, so
    # only the stock rule can fail.
    roster, case, lot = _build_reservation_scenario(api, lot_expires_on="2027-06-30")

    response = api.reserve_device(
        case["id"],
        f.device_reservation_payload(lot["id"], 5, lot["version"]),
        roster.nurse_headers,
    )

    validate_error(response, ERR_CONSIGNMENT_INSUFFICIENT)
