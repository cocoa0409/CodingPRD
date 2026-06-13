"""Deposits and the confirmation compliance checkpoint.

Covers the deposit-payable state rule, the three confirmation gates
(verified / waiver / deposit-met), validation precedence between those gates,
appointment-version optimistic concurrency on deposits, and immediate
consistency of deposit_paid_cents.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_client_headers,
    create_artist, create_chair, create_client, create_verified_client,
    hold_appointment, pay_deposit, record_waiver, set_clock,
    setup_held_appointment,
)
from test_helpers import factories


# ---------------------------------------------------------------------------
# Consent waiver immutability (PRD §2.4)
# ---------------------------------------------------------------------------
def test_consent_waiver_immutable_no_version_field(api):
    """PRD §2.4: "The `ConsentWaiver` resource is an exception. It is an
    immutable record of a signature event and therefore carries only `id` and
    `created_at`; it has neither an `updated_at` nor a `version` field. Its
    `signed_at` field is a system-set ISO 8601 UTC timestamp recording when the
    waiver was captured, and it is always equal to the waiver's `created_at`."

    Design: Corner/entities/consent_waiver_immutable_no_version_field
    """
    ctx = setup_held_appointment(verify_client=False)
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    waiver = validate_success(
        api.record_waiver(
            appt_id, factories.waiver_payload(cid, medical_flags=["DIABETES"], aftercare_acknowledged=True),
            make_client_headers(cid),
        ),
        expected_status=201,
    )
    assert waiver["signed_at"] == waiver["created_at"], \
        f"signed_at must equal created_at, got {waiver['signed_at']} vs {waiver['created_at']}"
    assert "version" not in waiver, "immutable waiver must not expose a version field"
    assert "updated_at" not in waiver, "immutable waiver must not expose an updated_at field"

MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Deposit payable state (PRD §3.6, priority 13)
# ---------------------------------------------------------------------------
def test_deposit_on_cancelled_appointment_rejected(api):
    """PRD §3.6: "A deposit may be paid only while the appointment is `HELD` or
    `CONFIRMED`; an attempt to pay against an appointment in any other state —
    for instance one already `CANCELLED`, `COMPLETED`, or `NO_SHOW` — is rejected
    with `ERR_DEPOSIT_NOT_PAYABLE`."

    Design: Corner/validations/deposit_on_cancelled_appointment_rejected
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T11:00:00Z",
    )
    cancelled = get_success_data(
        api.cancel_appointment(appt["id"], make_client_headers(client["id"]))
    )
    resp = api.pay_deposit(
        appt["id"], factories.deposit_payload(5000, cancelled["version"]),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAYABLE.value, expected_status=422)


# ---------------------------------------------------------------------------
# Confirmation gates (PRD §3.7)
# ---------------------------------------------------------------------------
def test_confirm_deposit_not_met_rejected(api):
    """PRD §3.7: "The appointment's `deposit_paid_cents` must be at least its
    `required_deposit_cents`; if the deposit is short, confirmation is rejected
    with `ERR_DEPOSIT_NOT_MET`."

    Design: Corner/validations/confirm_deposit_not_met_rejected
    """
    ctx = setup_held_appointment()  # verified client, required_deposit 10800
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    paid = pay_deposit(appt_id, cid, 5000, ctx["appointment_version"])
    record_waiver(appt_id, cid, aftercare_acknowledged=True)
    resp = api.confirm_appointment(appt_id, make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_MET.value, expected_status=422)
    assert paid["status"] == "CONFIRMED"


def test_confirm_waiver_aftercare_not_acknowledged_rejected(api):
    """PRD §3.7: "A valid `ConsentWaiver` — one whose `aftercare_acknowledged`
    is true — must exist for the appointment; if none does, confirmation is
    rejected with `ERR_WAIVER_MISSING`."

    A waiver row exists but with aftercare_acknowledged=false, so it is not
    valid.

    Design: Corner/validations/confirm_waiver_aftercare_not_acknowledged_rejected
    """
    ctx = setup_held_appointment()
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    pay_deposit(appt_id, cid, ctx["required_deposit_cents"], ctx["appointment_version"])
    record_waiver(appt_id, cid, aftercare_acknowledged=False)
    resp = api.confirm_appointment(appt_id, make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_WAIVER_MISSING.value, expected_status=422)


def test_confirm_requires_client_verified(api):
    """PRD §3.7: "The acting client's `id_status` must be `VERIFIED`; if it is
    not, confirmation is rejected with `ERR_CLIENT_NOT_VERIFIED`."

    Deposit met AND a valid waiver present, but the client is UNVERIFIED.

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_client_verified
    """
    ctx = setup_held_appointment(verify_client=False)
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    pay_deposit(appt_id, cid, ctx["required_deposit_cents"], ctx["appointment_version"])
    record_waiver(appt_id, cid, aftercare_acknowledged=True)
    resp = api.confirm_appointment(appt_id, make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_VERIFIED.value, expected_status=422)
    after = get_success_data(api.get_appointment(appt_id, MANAGER))
    assert after["status"] == "HELD", f"appointment must stay HELD, got {after['status']}"


def test_confirm_unverified_client_stays_held(api):
    """PRD §3.7: "When all gates pass, the appointment advances from `HELD` to
    `CONFIRMED`."
    PRD §3.7: "The acting client's `id_status` must be `VERIFIED`; if it is not,
    confirmation is rejected with `ERR_CLIENT_NOT_VERIFIED`."

    A second assertion on the same cross-entity dependency: the rejected confirm
    leaves the appointment in HELD (the transition does not partially apply).

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_client_verified
    """
    ctx = setup_held_appointment(verify_client=False)
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    pay_deposit(appt_id, cid, ctx["required_deposit_cents"], ctx["appointment_version"])
    record_waiver(appt_id, cid, aftercare_acknowledged=True)
    api.confirm_appointment(appt_id, make_client_headers(cid))
    after = get_success_data(api.get_appointment(appt_id, MANAGER))
    assert after["status"] == "HELD", f"unverified confirm must not advance state, got {after['status']}"


# ---------------------------------------------------------------------------
# Validation precedence among the gates (PRD §2.9 + §3.7 ordering)
# ---------------------------------------------------------------------------
def test_confirm_state_beats_client_not_verified(api):
    """PRD §2.9: "State validity is checked fourth: an operation requested
    against a resource that is not in a state permitting the transition fails
    with `ERR_INVALID_STATE`. Only after these four layers pass does the system
    evaluate the business-specific safety, constraint, temporal, and fiscal
    rules described throughout §3, each of which carries its own dedicated error
    code."

    Confirming a CANCELLED appointment whose client is also UNVERIFIED: the
    fourth-layer state check wins over the business-safety verified check.

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_client_not_verified
    """
    set_clock("2026-06-01T12:00:00Z")
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()  # UNVERIFIED
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T13:00:00Z",
    )
    get_success_data(api.cancel_appointment(appt["id"], make_client_headers(client["id"])))
    resp = api.confirm_appointment(appt["id"], make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_confirm_cancelled_unverified_not_business_safety_error(api):
    """PRD §2.9: "State validity is checked fourth ... Only after these four
    layers pass does the system evaluate the business-specific safety,
    constraint, temporal, and fiscal rules described throughout §3, each of which
    carries its own dedicated error code."

    Second assertion on the state-beats-verified instance: the cancelled +
    unverified confirm must NOT surface the business-safety ERR_CLIENT_NOT_VERIFIED
    (the state layer pre-empts it).

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_client_not_verified
    """
    set_clock("2026-06-01T12:00:00Z")
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()  # UNVERIFIED
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-06-12T10:00:00Z", end_at="2026-06-12T13:00:00Z",
    )
    get_success_data(api.cancel_appointment(appt["id"], make_client_headers(client["id"])))
    resp = api.confirm_appointment(appt["id"], make_client_headers(client["id"]))
    body = resp.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, \
        f"state must pre-empt business-safety, got {body['error_id']}"


def test_confirm_verified_gate_beats_waiver_gate(api):
    """PRD §3.7: "The acting client's `id_status` must be `VERIFIED`; if it is
    not, confirmation is rejected with `ERR_CLIENT_NOT_VERIFIED`. A valid
    `ConsentWaiver` — one whose `aftercare_acknowledged` is true — must exist for
    the appointment; if none does, confirmation is rejected with
    `ERR_WAIVER_MISSING`."

    The §3.7 narrative orders the verified gate before the waiver gate. A HELD
    appointment whose client is UNVERIFIED and that has NO waiver surfaces the
    earlier ERR_CLIENT_NOT_VERIFIED.

    Design: Difficulty/priority_pair_validation_conflict/confirm_verified_beats_waiver_missing
    """
    ctx = setup_held_appointment(verify_client=False)
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    pay_deposit(appt_id, cid, ctx["required_deposit_cents"], ctx["appointment_version"])
    # No waiver recorded at all.
    resp = api.confirm_appointment(appt_id, make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_VERIFIED.value, expected_status=422)


def test_confirm_unverified_no_waiver_surfaces_verified_not_waiver(api):
    """PRD §3.7: "The acting client's `id_status` must be `VERIFIED`; if it is
    not, confirmation is rejected with `ERR_CLIENT_NOT_VERIFIED`. A valid
    `ConsentWaiver` — one whose `aftercare_acknowledged` is true — must exist for
    the appointment; if none does, confirmation is rejected with
    `ERR_WAIVER_MISSING`."

    Second assertion on the verified-beats-waiver instance: with both faults
    present, the surfaced error is specifically ERR_CLIENT_NOT_VERIFIED and NOT
    ERR_WAIVER_MISSING (the §3.7 narrative orders the verified gate first).

    Design: Difficulty/priority_pair_validation_conflict/confirm_verified_beats_waiver_missing
    """
    ctx = setup_held_appointment(verify_client=False)
    appt_id = ctx["appointment_id"]
    cid = ctx["client_id"]
    pay_deposit(appt_id, cid, ctx["required_deposit_cents"], ctx["appointment_version"])
    resp = api.confirm_appointment(appt_id, make_client_headers(cid))
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_WAIVER_MISSING.value, \
        f"verified gate must pre-empt waiver gate, got {body['error_id']}"
    assert body["error_id"] == ApiErrorId.ERR_CLIENT_NOT_VERIFIED.value, \
        f"expected ERR_CLIENT_NOT_VERIFIED, got {body['error_id']}"


# ---------------------------------------------------------------------------
# Appointment-version OCC on deposits (PRD §2.7)
# ---------------------------------------------------------------------------
def test_deposit_with_stale_appointment_version_rejected(api):
    """PRD §2.7: "When paying a deposit toward an appointment, the request must
    carry `expected_appointment_version`, which must equal the current `version`
    of the target `Appointment`. If a prior deposit or a forfeiting reschedule
    has legitimately mutated the appointment and advanced its `version` since the
    client last read it, the deposit attempt carries a stale appointment view and
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_deposit_stale_appointment_version
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T13:00:00Z",
    )
    original_version = appt["version"]
    pay_deposit(appt["id"], client["id"], 5000, original_version)  # bumps version
    # Second deposit reuses the stale pre-bump version.
    resp = api.pay_deposit(
        appt["id"], factories.deposit_payload(5000, original_version),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ---------------------------------------------------------------------------
# Immediate consistency (PRD §2.5)
# ---------------------------------------------------------------------------
def test_deposit_paid_cents_visible_immediately(api):
    """PRD §3.6: "Each successful payment adds its `amount_cents` to the
    appointment's `deposit_paid_cents` and advances the appointment's `version`
    by one."
    PRD §3.5: "An appointment may be fetched individually — returning its
    computed `deposit_paid_cents`, `required_deposit_cents`".

    Design: Corner/consistency_model/deposit_paid_cents_visible_immediately
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T13:00:00Z",
    )
    pay_deposit(appt["id"], client["id"], 10800, appt["version"])
    fetched = validate_success(
        api.get_appointment(appt["id"], make_client_headers(client["id"])), expected_status=200
    )
    assert fetched["deposit_paid_cents"] == 10800, \
        f"deposit_paid_cents must reflect the payment immediately, got {fetched['deposit_paid_cents']}"
