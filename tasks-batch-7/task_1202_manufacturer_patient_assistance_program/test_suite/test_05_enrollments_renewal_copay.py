"""Enrollments, renewal chaining, changes of circumstance, copay cards, and the
expiry sweep (PRD §2.5, §2.8, §3.5, §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_enrollment,
    fixtures as fx,
    make_case_worker_headers,
    make_patient_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_terminated_enrollment_rejects_second_terminate():
    """PRD §3.5: "Termination is final and comes in three flavors." and "Any
    action against a terminated, expired, or closed enrollment requiring an
    active one is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/state_machines/enrollment_terminate_terminal_lockdown
    """
    ctx = fx.setup_approved_enrollment()
    first = validate_success(api_client.terminate_enrollment(
        ctx["enrollment"]["id"], {"termination_reason": "withdrew"}, fx.CW))
    assert first["status"] == "TERMINATED"

    resp = api_client.terminate_enrollment(
        ctx["enrollment"]["id"], {"termination_reason": "again"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)
    current = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert current["status"] == "TERMINATED"


def test_reinstate_active_enrollment_rejected():
    """PRD §3.5: "A `CaseWorker` may later reinstate a `SUSPENDED` enrollment
    (only `SUSPENDED`, else `ERR_ENROLLMENT_NOT_SUSPENDED`) by supplying a
    `screening_id` that references a screening of the enrollment's own patient
    and program (`ERR_SCREENING_MISMATCH` otherwise), currently `VERIFIED`
    (`ERR_SCREENING_NOT_VERIFIED`), and still within its validity window
    (`ERR_SCREENING_STALE`)."

    Design: Corner/state_machines/enrollment_reinstate_from_active_rejected
    """
    ctx = fx.setup_approved_enrollment()
    resp = api_client.reinstate_enrollment(
        ctx["enrollment"]["id"], {"screening_id": ctx["screening"]["id"]}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_SUSPENDED, expected_status=409)
    current = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert current["status"] == "ACTIVE"


def test_dismissed_circumstance_rejects_second_review():
    """PRD §3.5: "A `CaseWorker` review then resolves it: a `REPORTED`
    circumstance (else `ERR_CIRCUMSTANCE_NOT_REPORTED`) may be dismissed —
    landing in `DISMISSED` with no further effect — or applied, landing in
    `APPLIED`."

    Design: Corner/state_machines/circumstance_review_twice_rejected
    """
    ctx = fx.setup_approved_enrollment()
    coc = fx.report_circumstance_record(
        ctx["enrollment"]["id"], circumstance_type="HOUSEHOLD_CHANGE",
        new_household_size=2)
    dismissed = validate_success(api_client.review_circumstance(
        coc["id"], {"decision": "DISMISSED", "review_note": "no material change"}, fx.CW))
    assert dismissed["status"] == "DISMISSED"

    resp = api_client.review_circumstance(
        coc["id"], {"decision": "APPLIED_SUSPEND"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_CIRCUMSTANCE_NOT_REPORTED, expected_status=409)
    current = validate_success(api_client.get_circumstance(coc["id"], fx.CW))
    assert current["status"] == "DISMISSED"
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["status"] == "ACTIVE", "the dismissal left the enrollment untouched"


def test_enrollment_filter_by_patient():
    """PRD §3.5: "Enrollments are readable by all roles and filterable by
    `patient_id`, `program_id`, `application_id`, `commitment_budget_period_id`,
    and `status`."

    Design: Corner/endpoints/enrollment_reverse_lookup_by_patient
    """
    ctx = fx.setup_approved_enrollment()
    other_patient = fx.create_patient_record(full_name="Jan Jipp")

    mine, meta_mine = validate_paginated(api_client.list_enrollments(
        fx.CW, params={"patient_id": ctx["patient"]["id"]}))
    assert len(mine) == 1 and meta_mine["total_count"] == 1
    assert mine[0]["id"] == ctx["enrollment"]["id"]

    theirs, meta_theirs = validate_paginated(api_client.list_enrollments(
        fx.CW, params={"patient_id": other_patient["id"]}))
    assert theirs == [] and meta_theirs["total_count"] == 0


def test_renewal_create_stale_version_rejected():
    """PRD §2.8: "creating a renewal application against an enrollment requires
    the request to carry `expected_enrollment_version` matching that enrollment's
    current `version`; renewal creation itself advances the enrollment's
    `version` by 1 (and supersedes older non-terminal renewal applications), so a
    writer holding a stale version is acting on an out-of-date view and is
    likewise rejected with `ERR_STALE_VERSION` (HTTP 412). A successful renewal
    creation therefore invalidates any previously observed enrollment version."

    Design: Corner/complexity_layers/occ_renewal_stale_version_returns_412
    """
    ctx = fx.setup_approved_enrollment()
    fx.set_clock("2026-07-01T00:00:00Z")  # inside [end - 30d, end] = [2026-06-29, 2026-07-29]
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    observed_version = enrollment["version"]

    first = validate_success(api_client.create_renewal_application(
        ctx["enrollment"]["id"],
        {"screening_id": ctx["screening"]["id"],
         "expected_enrollment_version": observed_version},
        make_patient_headers(ctx["patient"]["id"])), expected_status=201)
    assert first["renewal_of_enrollment_id"] == ctx["enrollment"]["id"]
    bumped = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert bumped["version"] == observed_version + 1, "renewal creation advances the version"

    resp = api_client.create_renewal_application(
        ctx["enrollment"]["id"],
        {"screening_id": ctx["screening"]["id"],
         "expected_enrollment_version": observed_version},
        make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    renewals, meta = validate_paginated(api_client.list_applications(
        fx.CW, params={"renewal_of_enrollment_id": ctx["enrollment"]["id"]}))
    assert len(renewals) == 1, "no second renewal application persisted"


def test_renewal_dates_and_commitment_handover():
    """PRD §3.3: "its `start_date` is today for a fresh approval, or the day
    after the prior enrollment's `end_date` for a renewal; its `end_date` is the
    `start_date` plus `enrollment_duration_days` minus one day"
    PRD §3.5: "When a renewal is later approved (§3.3), the prior enrollment
    moves `ACTIVE → CLOSED_RENEWED`, its remaining commitment —
    `benefit_cap_cents` minus `disbursed_cents` — is released from both the
    program totals and its commitment period's `committed_cents`, and the
    successor enrollment's `start_date` is the prior `end_date` plus one day."
    PRD §3.3: "For a renewal, the prior enrollment's remaining commitment is
    released as part of the same approval before the sufficiency test is
    evaluated: a renewal replaces a commitment rather than adding to it."

    Design: Corner/calculations/renewal_enrollment_dates_and_commitment_handover
    """
    ctx = fx.setup_approved_enrollment()
    fx.set_clock("2026-07-01T00:00:00Z")  # inside the renewal window
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])

    renewal_app = validate_success(api_client.create_renewal_application(
        ctx["enrollment"]["id"],
        {"screening_id": ctx["screening"]["id"],
         "expected_enrollment_version": enrollment["version"]},
        make_patient_headers(ctx["patient"]["id"])), expected_status=201)
    assert renewal_app["renewal_of_enrollment_id"] == ctx["enrollment"]["id"]

    validate_success(api_client.claim_application(
        renewal_app["id"], make_case_worker_headers("cw_1")))
    decided = validate_success(api_client.decide_application(
        renewal_app["id"], {"decision": "APPROVED"}, make_case_worker_headers("cw_1")))
    new_enrollment = validate_success(api_client.get_enrollment(decided["enrollment_id"], fx.CW))

    old = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert old["status"] == "CLOSED_RENEWED"

    assert_enrollment(new_enrollment)
    assert new_enrollment["status"] == "ACTIVE"
    assert new_enrollment["start_date"] == "2026-07-30", "prior end_date + 1 day"
    assert new_enrollment["end_date"] == "2026-10-27", "start + 90 days - 1"
    assert new_enrollment["benefit_cap_cents"] == 900000

    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 900000, (
        "the prior 900000 is released before the new 900000 commits — no double count")
    assert utilization["posture"] == "RESTRICTED"


def test_circumstance_terminate_cascades_to_enrollment():
    """PRD §3.5: "An applied review with a suspend outcome cascades the
    enrollment `ACTIVE → SUSPENDED`; an applied review with a terminate outcome
    cascades it to `TERMINATED`; the circumstance records the `outcome` as
    `SUSPENDED` or `TERMINATED` accordingly and stores the caseworker's
    `review_note`."

    Design: Difficulty/transitive_cascade/circumstance_terminate_depth3_cascade
    """
    ctx = fx.setup_reserved_shipment(quantity_units=10, lot_number="LOT-C1",
                                     idempotency_key="ship-casc")
    coc = fx.report_circumstance_record(
        ctx["enrollment"]["id"], by_patient_id=ctx["patient"]["id"],
        circumstance_type="INSURANCE_CHANGE", new_insurance_status="INSURED_COMMERCIAL",
        note="employer coverage began")
    reviewed = validate_success(api_client.review_circumstance(
        coc["id"], {"decision": "APPLIED_TERMINATE", "review_note": "no longer eligible"},
        fx.CW))
    assert reviewed["status"] == "APPLIED"
    assert reviewed["outcome"] == "TERMINATED"

    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["status"] == "TERMINATED", "hop 1: the enrollment is terminated by cascade"


def test_circumstance_terminate_releases_shipment_and_budget():
    """PRD §3.5: "Termination and expiry share their side effects: every
    `RESERVED` shipment is cancelled with lot-release and `remaining_units`
    restoration, and the remaining commitment — `benefit_cap_cents` minus
    `disbursed_cents` — is released from the program's `total_committed_cents`
    and the commitment period's `committed_cents`, with posture recomputed."

    Design: Difficulty/transitive_cascade/circumstance_terminate_depth3_cascade
    """
    ctx = fx.setup_reserved_shipment(quantity_units=10, lot_number="LOT-C1",
                                     idempotency_key="ship-casc")
    coc = fx.report_circumstance_record(
        ctx["enrollment"]["id"], by_patient_id=ctx["patient"]["id"],
        circumstance_type="INSURANCE_CHANGE", new_insurance_status="INSURED_COMMERCIAL",
        note="employer coverage began")
    validate_success(api_client.review_circumstance(
        coc["id"], {"decision": "APPLIED_TERMINATE", "review_note": "no longer eligible"},
        fx.CW))

    shipment = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert shipment["status"] == "CANCELLED", (
        "hop 2: the RESERVED shipment is cancelled by the cascade, not a direct cancel call")
    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["quantity_on_hand"] == 100 and lot["quantity_reserved"] == 0, (
        "hop 3: the lot reservation is released")

    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["remaining_units"] == 100, "units restored to the enrollment pool"
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 0, "the remaining commitment is released"
    assert utilization["posture"] == "OPEN"


def test_enrollment_expiry_sweep_releases_commitment():
    """PRD §3.8: "Second, every `ACTIVE` or `SUSPENDED` enrollment with today
    strictly after its `end_date` becomes `EXPIRED`, with the full cascade of
    §3.5: `RESERVED` shipments cancelled with lot release and unit restoration,
    remaining commitment released, posture recomputed." and "The sweep reports
    back the identifiers it touched as `staled_screening_ids`,
    `expired_enrollment_ids`, `expired_lot_ids`, and `cancelled_shipment_ids`."

    Design: Corner/state_machines/enrollment_expiry_sweep_releases_commitment
    """
    ctx = fx.setup_reserved_shipment(quantity_units=10, lot_number="LOT-EX",
                                     idempotency_key="sweep-exp")
    fx.set_clock("2026-07-30T00:00:00Z")  # strictly after end_date 2026-07-29
    sweep = fx.run_sweep()
    assert ctx["enrollment"]["id"] in sweep["expired_enrollment_ids"]
    assert ctx["shipment"]["id"] in sweep["cancelled_shipment_ids"]

    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["status"] == "EXPIRED"
    shipment = validate_success(api_client.get_shipment(ctx["shipment"]["id"], fx.CW))
    assert shipment["status"] == "CANCELLED"
    lot = fx.refresh_lot(ctx["lot"]["id"])
    assert lot["quantity_on_hand"] == 100 and lot["quantity_reserved"] == 0

    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 0
    assert utilization["posture"] == "OPEN"


def test_suspend_terminated_card_rejected():
    """PRD §3.6: "A card's own lifecycle is simple: born `ACTIVE`, a `CaseWorker`
    may suspend it (any other state drawing `ERR_COPAY_CARD_NOT_ACTIVE`) or
    terminate it from either `ACTIVE` or `SUSPENDED`, with an optional `reason`
    stored as `termination_reason` when supplied; any action against a
    `TERMINATED` card is rejected with `ERR_COPAY_CARD_TERMINATED`."

    Design: Corner/state_machines/copay_suspend_after_terminate_rejected
    """
    ctx = fx.setup_program_with_period()
    patient = fx.create_patient_record()
    card = fx.create_copay_card_record(patient["id"], ctx["program"]["id"])
    terminated = validate_success(api_client.terminate_copay_card(
        card["id"], {"reason": "patient request"}, fx.CW))
    assert terminated["status"] == "TERMINATED"

    resp = api_client.suspend_copay_card(card["id"], fx.CW)
    validate_error(resp, ApiErrorId.ERR_COPAY_CARD_TERMINATED, expected_status=409)
    current = validate_success(api_client.get_copay_card(card["id"], fx.CW))
    assert current["status"] == "TERMINATED"


def test_copay_card_end_before_start_returns_400():
    """PRD §2.7: "Required fields present, types match, enum values valid, date
    ranges sane (`coverage_end` on or after `coverage_start`, `period_end` on or
    after `period_start`, `actual_on_hand` non-negative)" ...
    "(`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/copay_card_end_before_start_returns_400
    """
    ctx = fx.setup_program_with_period()
    patient = fx.create_patient_record()
    resp = api_client.create_copay_card(
        {"patient_id": patient["id"], "program_id": ctx["program"]["id"],
         "coverage_start": "2026-06-01", "coverage_end": "2026-05-01"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
