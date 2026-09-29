"""
Compensating actions and the two conserved ledgers of the practice.

Two quantities in this contract are conserved totals: the unit ledger of a
consignment lot and the visit ledger of a pelvic health referral. Both are
exercised here through their compensating paths — a cancellation that reverses a
device hold in full against a no-show that destroys the same unit, and a voided
therapy visit that gives one unit back against a withdrawal that forfeits
whatever is left. In every case the ledger identity must still balance
afterwards, even though the buckets the units sit in differ completely.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_lot_counters,
    assert_lot_ledger_conserved,
    assert_null_fields,
    assert_visit_counters,
    assert_visit_ledger_conserved,
)
from test_helpers.constants import (
    BILLING_PROVISIONAL,
    BILLING_STATUS_CONSIGNED,
    BILLING_STATUS_PARTIALLY_INVOICED,
    CASE_CANCELLED,
    CASE_NO_SHOW,
    CLEANUP_LOW,
    CLEARANCE_DECISION_CLEAR,
    DECISION_ACCEPT,
    DECISION_WITHDRAW,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_STATE_RELEASED,
    DEVICE_STATE_WASTED,
    NO_SHOW_CANCEL_REASON_CODE,
    PROGRAM_BEHAVIORAL_TRAINING,
    REFERRAL_ACCEPTED,
    REFERRAL_COMPLETED,
    REFERRAL_WITHDRAWN,
    ROLE_TYPE_PELVIC_COORDINATOR,
    ROLE_TYPE_RN,
    ROLE_TYPE_SCHEDULER,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    ROOM_TYPE_URODYNAMICS_LAB,
    TYPE_PROSTATE_BIOPSY,
    TYPE_URODYNAMICS,
    VISIT_ACTION_LOG,
    VISIT_ACTION_VOID_LAST,
)
from test_helpers.test_users import (
    make_pelvic_health_coordinator_headers,
    make_practice_admin_headers,
    make_procedure_nurse_headers,
    make_scheduler_headers,
    make_urologist_headers,
)

# ─── The consignment scenario ──────────────────────────────────────────────
BIOPSY_SKU = "BX-NEEDLE-18G"
BIOPSY_CASE_START = "2026-09-14T09:00:00Z"
BIOPSY_CLOCK_BEFORE = "2026-09-14T08:00:00Z"
# One minute past the fifteen-minute grace allowance on a 09:00 start.
BIOPSY_CLOCK_PAST_GRACE = "2026-09-14T09:16:00Z"
CANCEL_REASON = "PATIENT_REQUEST"

# ─── The pelvic health scenario ────────────────────────────────────────────
URODYNAMICS_CASE_START = "2026-09-16T10:00:00Z"
FIRST_VISIT_DATE = "2026-09-20"
SECOND_VISIT_DATE = "2026-09-27"
THERAPY_START_BY = "2026-10-16"


def _stand_up_consignment_practice(api):
    """
    A prostate biopsy service whose procedure type consumes one consigned
    single-use needle, and a lot of ten of them priced at 1999 cents each.
    """
    admin_headers = make_practice_admin_headers()
    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )
    nurse = fx.create_provider(
        api, ROLE_TYPE_RN, full_name="Nina Park", npi="1000000003"
    )
    patient = fx.create_patient(
        api,
        urologist,
        mrn="MRN-4217",
        full_name="Dario Vess",
        date_of_birth="1961-01-09",
        egfr=60,
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        consignment_required=True,
        single_use_device_sku=BIOPSY_SKU,
        required_prep_codes=[],
    )
    lot = fx.create_lot(
        api,
        supplier_name="Meridian Devices",
        sku=BIOPSY_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=1999,
        lot_expires_on="2027-06-30",
    )
    fx.set_clock(api, BIOPSY_CLOCK_BEFORE, admin_headers)
    return {
        "admin_headers": admin_headers,
        "urologist": urologist,
        "scheduler_headers": make_scheduler_headers(scheduler["id"]),
        "nurse_headers": make_procedure_nurse_headers(nurse["id"]),
        "patient": patient,
        "room": room,
        "procedure_type": procedure_type,
        "lot": lot,
    }


def _draft_biopsy_case(api, stage, scheduled_start_at=BIOPSY_CASE_START):
    """Draft one biopsy case; a draft holds neither the room nor the urologist."""
    return get_success_data(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=stage["patient"]["id"],
                procedure_type_id=stage["procedure_type"]["id"],
                room_id=stage["room"]["id"],
                primary_provider_id=stage["urologist"]["id"],
                scheduled_start_at=scheduled_start_at,
            ),
            stage["scheduler_headers"],
        ),
        201,
    )


def _hold_one_needle(api, stage, case_id, expected_lot_version):
    """Hold a single needle for a case, carrying the lot version just read."""
    return get_success_data(
        api.reserve_device(
            case_id,
            f.device_reservation_payload(
                stage["lot"]["id"], 1, expected_lot_version
            ),
            stage["nurse_headers"],
        )
    )


def _read_lot(api, stage):
    return validate_success(
        api.get_consignment_lot(stage["lot"]["id"], stage["nurse_headers"])
    )


def _refer_off_a_completed_urodynamics_case(api):
    """
    Carry one urodynamics case all the way to completion in an accredited lab,
    then enter a behavioural-training referral asking for two therapy visits.
    """
    admin_headers = make_practice_admin_headers()
    urologist = fx.create_provider(
        api,
        ROLE_TYPE_UROLOGIST,
        full_name="Dr Ada Nour",
        npi="1000000001",
        ultrasound_accreditation_expires_on="2027-03-31",
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )
    nurse = fx.create_provider(
        api, ROLE_TYPE_RN, full_name="Nina Park", npi="1000000003"
    )
    coordinator = fx.create_provider(
        api, ROLE_TYPE_PELVIC_COORDINATOR, full_name="Cleo Vance", npi="1000000008"
    )
    urologist_headers = make_urologist_headers(urologist["id"])
    scheduler_headers = make_scheduler_headers(scheduler["id"])
    nurse_headers = make_procedure_nurse_headers(nurse["id"])
    coordinator_headers = make_pelvic_health_coordinator_headers(coordinator["id"])

    patient = fx.create_patient(
        api,
        urologist,
        mrn="MRN-4218",
        full_name="Sena Ibarra",
        date_of_birth="1975-12-01",
        egfr=60,
    )
    room = fx.create_room(
        api,
        ROOM_TYPE_URODYNAMICS_LAB,
        name="Uro Lab",
        turnover_minutes=8,
        accreditation_body="AIUM",
        accreditation_expires_on="2027-01-31",
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_URODYNAMICS,
        base_minutes=45,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_URODYNAMICS_LAB,
        requires_scope=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )
    # The clock is pinned at the case's own start instant, so the completion
    # stamp — and therefore the therapy deadline derived from it — is exact.
    fx.set_clock(api, URODYNAMICS_CASE_START, admin_headers)

    case = get_success_data(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at=URODYNAMICS_CASE_START,
            ),
            scheduler_headers,
        ),
        201,
    )
    get_success_data(
        api.schedule_case(
            case["id"], f.schedule_payload(room["version"]), scheduler_headers
        )
    )
    get_success_data(
        api.review_clearance(
            case["id"],
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            nurse_headers,
        )
    )
    get_success_data(api.check_in_case(case["id"], {}, nurse_headers))
    completed = get_success_data(
        api.complete_case(
            case["id"],
            f.complete_case_payload(outcome_note="multichannel urodynamics complete"),
            urologist_headers,
        )
    )
    referral = get_success_data(
        api.create_pelvic_health_referral(
            f.referral_payload(
                patient_id=patient["id"],
                source_case_id=case["id"],
                program=PROGRAM_BEHAVIORAL_TRAINING,
                requested_visits=2,
            ),
            urologist_headers,
        ),
        201,
    )
    return {
        "coordinator_headers": coordinator_headers,
        "completed_case": completed,
        "referral": referral,
    }


def _accept_two_visits(api, bundle):
    return validate_success(
        api.decide_pelvic_health_referral(
            bundle["referral"]["id"],
            f.referral_decision_payload(DECISION_ACCEPT, authorized_visits=2),
            bundle["coordinator_headers"],
        )
    )


def _log_visit(api, bundle, visit_date):
    return validate_success(
        api.log_referral_visit(
            bundle["referral"]["id"],
            f.referral_visit_payload(VISIT_ACTION_LOG, visit_date=visit_date),
            bundle["coordinator_headers"],
        )
    )


def _void_last_visit(api, bundle):
    return validate_success(
        api.log_referral_visit(
            bundle["referral"]["id"],
            f.referral_visit_payload(VISIT_ACTION_VOID_LAST),
            bundle["coordinator_headers"],
        )
    )


# ─── The consignment unit ledger: cancel reverses, no-show destroys ─────────
def test_cancelling_a_drafted_case_totally_reverses_the_consigned_unit(api):
    """PRD §3.6: "A successful hold writes `device_lot_id` and `device_quantity`
    onto the case and sets its `device_state` to `RESERVED`; the lot's
    `quantity_available` falls by the reserved quantity and its
    `quantity_reserved` rises by the same amount; the lot is re-billed
    provisionally, its `billing_status` re-derived and its `version` incremented
    by 1; and the case's readiness gates are recomputed."
    PRD §3.3: "If the case's `device_state` is `RESERVED`, it becomes
    `RELEASED`, the lot's `quantity_reserved` is reduced by the case's
    `device_quantity` and its `quantity_available` increased by the same amount,
    the lot's `version` increments by 1, and the lot is re-billed under the
    provisional basis described in §3.6."
    PRD §3.6: "The `PROVISIONAL` variant runs whenever units are merely held or
    handed back while still unspent — that is, on a device reservation, on a case
    cancellation and on a case no-show. Its factor is 1 plus the 18.5%
    consignment markup, so 1.185, and it sums only the lines whose
    `device_state` is `RESERVED`."
    PRD §3.6: "Rounding once at the end, over the summed raw products, is not
    the rule and produces a different figure: with a `unit_price_cents` of 1999,
    a markup factor of 1.185 and three reserved lines of one unit each, the
    pinned per-line-then-sum order gives 2369 cents a line and 7107 cents in
    total, whereas summing first would give 7106 cents."
    PRD §3.6: "Lines whose `device_state` is `RELEASED` are selected by neither
    variant, and neither variant ever reads a lot's history — each run
    recomputes `billed_amount_cents` from the lines standing at that moment."
    PRD §3.6: "`billing_status` is a **compound status derived entirely from the
    lot's own unit counters**, never supplied by a client, and it is re-derived
    after every mutation of those counters using the following ordered tests."
    PRD §3.6: "Otherwise it remains `CONSIGNED`."

    Design: Difficulty/compensating_invariant/ci_consignment_unit_conservation_cancel_vs_noshow
    """
    stage = _stand_up_consignment_practice(api)
    case = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case["id"], stage["lot"]["version"])

    held = _read_lot(api, stage)
    assert_lot_counters(held, available=9, reserved=1, consumed=0, returned=0, wasted=0)
    assert_fields(
        held,
        billed_amount_cents=2369,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_CONSIGNED,
    )

    cancelled = validate_success(
        api.cancel_case(
            case["id"], f.cancel_payload(CANCEL_REASON), stage["scheduler_headers"]
        )
    )
    assert_fields(
        cancelled,
        schedule_status=CASE_CANCELLED,
        cancel_reason_code=CANCEL_REASON,
        device_state=DEVICE_STATE_RELEASED,
    )

    released = _read_lot(api, stage)
    assert_lot_counters(
        released, available=10, reserved=0, consumed=0, returned=0, wasted=0
    )
    assert_fields(
        released,
        billed_amount_cents=0,
        billing_status=BILLING_STATUS_CONSIGNED,
    )
    assert released["version"] > held["version"], (
        "releasing the held units is a mutation of the lot, so its version must "
        f"advance past {held['version']}, got {released['version']}"
    )


def test_no_show_wastes_the_held_unit_and_partially_invoices_the_lot(api):
    """PRD §3.3: "A no-show happens after the room was set up, the package *was*
    opened, and the units are unrecoverable: `device_state` becomes `WASTED`,
    the lot's `quantity_reserved` is reduced by `device_quantity` and its
    `quantity_wasted` increased by the same amount, the lot's `version`
    increments by 1, and the lot is re-billed provisionally."
    PRD §3.3: "The case's `cancel_reason_code` is then set to the constant
    string `NO_SHOW_GRACE_ELAPSED` — the client does not supply it."
    PRD §3.6: "Otherwise, if the sum of `quantity_consumed` and
    `quantity_wasted` is at least 1, the lot is `PARTIALLY_INVOICED`."

    Design: Difficulty/compensating_invariant/ci_consignment_unit_conservation_cancel_vs_noshow
    """
    stage = _stand_up_consignment_practice(api)

    # The first case gives the unit back in full, so the lot is pristine again.
    case_a = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case_a["id"], stage["lot"]["version"])
    get_success_data(
        api.cancel_case(
            case_a["id"], f.cancel_payload(CANCEL_REASON), stage["scheduler_headers"]
        )
    )
    after_cancel = _read_lot(api, stage)
    assert_lot_counters(
        after_cancel, available=10, reserved=0, consumed=0, returned=0, wasted=0
    )

    # A cancelled draft never took a room block, so the room version stands.
    case_b = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case_b["id"], after_cancel["version"])
    get_success_data(
        api.schedule_case(
            case_b["id"],
            f.schedule_payload(stage["room"]["version"]),
            stage["scheduler_headers"],
        )
    )
    fx.set_clock(api, BIOPSY_CLOCK_PAST_GRACE, stage["admin_headers"])

    no_showed = validate_success(
        api.no_show_case(case_b["id"], {}, stage["scheduler_headers"])
    )
    assert_fields(
        no_showed,
        schedule_status=CASE_NO_SHOW,
        cancel_reason_code=NO_SHOW_CANCEL_REASON_CODE,
        device_state=DEVICE_STATE_WASTED,
    )

    wasted_lot = _read_lot(api, stage)
    assert_lot_counters(
        wasted_lot, available=9, reserved=0, consumed=0, returned=0, wasted=1
    )
    assert_fields(
        wasted_lot,
        billed_amount_cents=0,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_PARTIALLY_INVOICED,
    )


def test_no_showed_case_keeps_its_device_audit_trail(api):
    """PRD §3.6: "The case retains `device_lot_id` for the rest of its life,
    including after the units have been consumed, because the practice needs the
    billing trace even years later."

    Design: Difficulty/compensating_invariant/ci_consignment_unit_conservation_cancel_vs_noshow
    """
    stage = _stand_up_consignment_practice(api)
    case = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case["id"], stage["lot"]["version"])
    get_success_data(
        api.schedule_case(
            case["id"],
            f.schedule_payload(stage["room"]["version"]),
            stage["scheduler_headers"],
        )
    )
    fx.set_clock(api, BIOPSY_CLOCK_PAST_GRACE, stage["admin_headers"])
    get_success_data(api.no_show_case(case["id"], {}, stage["scheduler_headers"]))

    read_back = validate_success(
        api.get_procedure_case(case["id"], stage["scheduler_headers"])
    )
    assert_fields(
        read_back,
        schedule_status=CASE_NO_SHOW,
        device_state=DEVICE_STATE_WASTED,
        device_lot_id=stage["lot"]["id"],
        device_quantity=1,
    )


def test_cancel_and_no_show_both_conserve_the_lot_unit_ledger(api):
    """PRD §2.10: "For a consignment lot, `quantity_received` is the conserved
    total: at every observable moment it equals the sum of
    `quantity_available`, `quantity_reserved`, `quantity_consumed`,
    `quantity_returned` and `quantity_wasted`."
    PRD §3.3: "Both branches leave `quantity_received` untouched, as §2.10
    requires — the units simply sit in a different bucket, and the practice is
    invoiced for the wasted ones."

    Design: Difficulty/compensating_invariant/ci_consignment_unit_conservation_cancel_vs_noshow
    """
    stage = _stand_up_consignment_practice(api)

    case_a = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case_a["id"], stage["lot"]["version"])
    get_success_data(
        api.cancel_case(
            case_a["id"], f.cancel_payload(CANCEL_REASON), stage["scheduler_headers"]
        )
    )
    after_cancel = _read_lot(api, stage)
    assert_lot_ledger_conserved(after_cancel)
    assert after_cancel["quantity_received"] == 10, (
        "a cancellation moves units between buckets and must never change "
        f"quantity_received, got {after_cancel['quantity_received']}"
    )

    case_b = _draft_biopsy_case(api, stage)
    _hold_one_needle(api, stage, case_b["id"], after_cancel["version"])
    get_success_data(
        api.schedule_case(
            case_b["id"],
            f.schedule_payload(stage["room"]["version"]),
            stage["scheduler_headers"],
        )
    )
    fx.set_clock(api, BIOPSY_CLOCK_PAST_GRACE, stage["admin_headers"])
    get_success_data(api.no_show_case(case_b["id"], {}, stage["scheduler_headers"]))

    after_no_show = _read_lot(api, stage)
    assert_lot_ledger_conserved(after_no_show)
    assert after_no_show["quantity_received"] == 10, (
        "a no-show destroys a unit into quantity_wasted but must never change "
        f"quantity_received, got {after_no_show['quantity_received']}"
    )
    assert_lot_counters(
        after_no_show, available=9, reserved=0, consumed=0, returned=0, wasted=1
    )


# ─── The therapy visit ledger: void gives back, withdraw forfeits ───────────
def test_accepting_a_referral_opens_the_visit_ledger(api):
    """PRD §3.9: "On acceptance `visits_authorized` becomes the smallest of
    three numbers — the `requested_visits` recorded on the referral, the
    `authorized_visits` the payer approved, and the programme's own ceiling,
    which is 8 visits for `PELVIC_FLOOR_PT`, 4 for `BEHAVIORAL_TRAINING` and 6
    for `BIOFEEDBACK`."
    PRD §3.9: "`visits_remaining` is set equal to `visits_authorized`,
    `visits_used` and `visits_forfeited` are set to 0, `waitlist_position` is
    cleared back to null, and `therapy_start_by` is set to the source case's
    `completed_at` date plus 30 days — or, for a direct referral with no source
    case, to the logical clock date plus 30 days."

    Design: Difficulty/compensating_invariant/ci_referral_visit_ledger_conservation
    """
    bundle = _refer_off_a_completed_urodynamics_case(api)

    accepted = _accept_two_visits(api, bundle)
    assert_fields(accepted, status=REFERRAL_ACCEPTED, therapy_start_by=THERAPY_START_BY)
    assert_visit_counters(accepted, authorized=2, used=0, remaining=2, forfeited=0)
    assert_null_fields(accepted, "waitlist_position")


def test_logging_the_last_authorised_visit_completes_the_referral(api):
    """PRD §3.9: "`LOG` moves one unit across the ledger: `visits_used`
    increases by 1, `visits_remaining` decreases by 1, and `first_visit_date`
    holds the earliest logged visit date still standing."
    PRD §3.9: "When that log drives `visits_remaining` to 0 the referral
    auto-advances from `ACCEPTED` to `COMPLETED` in the same operation, with no
    further ledger movement beyond the unit just logged."

    Design: Difficulty/compensating_invariant/ci_referral_visit_ledger_conservation
    """
    bundle = _refer_off_a_completed_urodynamics_case(api)
    _accept_two_visits(api, bundle)

    after_first = _log_visit(api, bundle, FIRST_VISIT_DATE)
    assert_fields(
        after_first, status=REFERRAL_ACCEPTED, first_visit_date=FIRST_VISIT_DATE
    )
    assert_visit_counters(after_first, authorized=2, used=1, remaining=1, forfeited=0)

    after_second = _log_visit(api, bundle, SECOND_VISIT_DATE)
    assert_fields(after_second, status=REFERRAL_COMPLETED)
    assert_visit_counters(after_second, authorized=2, used=2, remaining=0, forfeited=0)


def test_voiding_the_completing_visit_returns_the_referral_to_accepted(api):
    """PRD §3.9: "`VOID_LAST` reverses the most recent log: `visits_used`
    decreases by 1, `visits_remaining` increases by 1, and `first_visit_date` is
    recomputed as the earliest remaining logged visit date, or null when the
    ledger has been emptied."
    PRD §3.9: "Voiding the very visit that completed a referral returns it from
    `COMPLETED` to `ACCEPTED` with the unit restored, so a coordinator who logs
    a session in error can undo it without reopening the authorisation."

    Design: Difficulty/compensating_invariant/ci_referral_visit_ledger_conservation
    """
    bundle = _refer_off_a_completed_urodynamics_case(api)
    _accept_two_visits(api, bundle)
    _log_visit(api, bundle, FIRST_VISIT_DATE)
    _log_visit(api, bundle, SECOND_VISIT_DATE)

    voided = _void_last_visit(api, bundle)
    assert_fields(
        voided, status=REFERRAL_ACCEPTED, first_visit_date=FIRST_VISIT_DATE
    )
    assert_visit_counters(voided, authorized=2, used=1, remaining=1, forfeited=0)


def test_withdrawing_forfeits_the_visit_the_void_gave_back(api):
    """PRD §3.9: "Whatever is left in `visits_remaining` is added to
    `visits_forfeited` and `visits_remaining` is then set to 0, so units leave
    the available bucket without ever leaving the referral; for a waitlisted or
    completed referral the amount moved happens to be zero."
    PRD §3.9: "After every one of these calls the ledger identity holds exactly:
    `visits_authorized` equals `visits_remaining` plus `visits_used` plus
    `visits_forfeited`."

    Design: Difficulty/compensating_invariant/ci_referral_visit_ledger_conservation
    """
    bundle = _refer_off_a_completed_urodynamics_case(api)

    stages = [_accept_two_visits(api, bundle)]
    stages.append(_log_visit(api, bundle, FIRST_VISIT_DATE))
    stages.append(_log_visit(api, bundle, SECOND_VISIT_DATE))
    stages.append(_void_last_visit(api, bundle))

    withdrawn = validate_success(
        api.decide_pelvic_health_referral(
            bundle["referral"]["id"],
            f.referral_decision_payload(DECISION_WITHDRAW),
            bundle["coordinator_headers"],
        )
    )
    stages.append(withdrawn)
    assert_fields(withdrawn, status=REFERRAL_WITHDRAWN)
    assert_visit_counters(withdrawn, authorized=2, used=1, remaining=0, forfeited=1)

    for index, stage in enumerate(stages, start=1):
        assert_visit_ledger_conserved(stage)
        assert stage["visits_authorized"] == 2, (
            f"visits_authorized is the conserved total and must stay 2 at every "
            f"stage, got {stage['visits_authorized']} after ledger call {index}"
        )

    read_back = validate_success(
        api.get_pelvic_health_referral(
            bundle["referral"]["id"], bundle["coordinator_headers"]
        )
    )
    assert_fields(read_back, status=REFERRAL_WITHDRAWN)
    assert_visit_counters(read_back, authorized=2, used=1, remaining=0, forfeited=1)
