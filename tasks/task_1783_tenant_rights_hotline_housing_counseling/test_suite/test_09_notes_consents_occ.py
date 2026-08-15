"""Case notes (append-only log), consent lifecycle, and optimistic concurrency
control on Case/Caller versions (PRD §2.4, §2.6, §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_case_note,
    assert_consent_record,
    assert_instant_equal,
    create_caller,
    create_self_help_resource,
    get_case,
    get_case_notes,
    get_caller,
    grant_consent,
    list_consents,
    make_caller_headers,
    move_case_in_progress,
    open_case,
    run_time_sweep,
    set_clock,
    setup_hotline,
    start_active_session,
    transition_case_ok,
    validate_error,
    validate_success,
)


def _case_in_progress(api):
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    return {**bundle, "caller": caller, "session": session, "case": case}


def test_case_note_immutable(api):
    """PRD §2.4: "The single exception is the `CaseNote`. Case notes form an
    immutable, append-only log: a note carries only `id` and `created_at`;
    `updated_at` and `version` are absent entirely, and no update or delete
    operation exists for notes."
    PRD §3.7: "The note's `counselor_id` is taken from the actor's `X-User-ID`,
    except on system-generated notes where it is null."

    Design: Corner/entities/case_note_immutable
    """
    bundle = _case_in_progress(api)
    case = bundle["case"]
    created = validate_success(api.create_case_note(
        case["id"],
        {"body": "intake summary", "is_confidential": False,
         "expected_case_version": case["version"]},
        bundle["worker_headers"],
    ), expected_status=201)
    assert_case_note(created)

    notes = get_case_notes(bundle, case["id"])
    found = [n for n in notes if n["id"] == created["id"]]
    assert len(found) == 1
    note = found[0]
    assert_case_note(note)
    for key in ("id", "created_at", "case_id", "counselor_id", "body",
                "is_confidential", "system_generated"):
        assert key in note, f"note must carry {key}"
    assert note["case_id"] == case["id"]
    assert note["counselor_id"] == bundle["worker"]["id"]
    assert note["system_generated"] is False


def test_occ_note_stale_version(api):
    """PRD §2.6: "Appending a note to a case requires the request to carry
    `expected_case_version`; proposing a referral on a case likewise requires
    `expected_case_version`; and granting a consent on a caller requires
    `expected_caller_version`."
    PRD §2.6: "If the parent's version has advanced since that observation —
    because another writer appended a note, proposed a referral, edited case facts,
    or triggered a cascade that legitimately mutated the parent — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412). A successful guarded write itself
    advances the parent's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_note_stale_version
    """
    bundle = _case_in_progress(api)
    case = bundle["case"]
    observed = case["version"]

    validate_success(api.create_case_note(
        case["id"], {"body": "first", "is_confidential": False,
                     "expected_case_version": observed},
        bundle["worker_headers"],
    ), expected_status=201)
    fresh = get_case(bundle, case["id"])
    assert fresh["version"] == observed + 1

    replay = api.create_case_note(
        case["id"], {"body": "stale", "is_confidential": False,
                     "expected_case_version": observed},
        bundle["worker_headers"],
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    validate_success(api.create_case_note(
        case["id"], {"body": "fresh", "is_confidential": True,
                     "expected_case_version": fresh["version"]},
        bundle["worker_headers"],
    ), expected_status=201)
    assert len(get_case_notes(bundle, case["id"])) == 2


def test_occ_referral_stale_version(api):
    """PRD §2.6: "Appending a note to a case requires the request to carry
    `expected_case_version`; proposing a referral on a case likewise requires
    `expected_case_version`; and granting a consent on a caller requires
    `expected_caller_version`."
    PRD §2.6: "If the parent's version has advanced since that observation —
    because another writer appended a note, proposed a referral, edited case facts,
    or triggered a cascade that legitimately mutated the parent — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412). A successful guarded write itself
    advances the parent's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_referral_stale_version
    """
    bundle = _case_in_progress(api)
    case = bundle["case"]
    resource = create_self_help_resource(bundle, bundle["script"]["id"],
                                         title="FAQ")
    observed = case["version"]

    # An intervening note advances the case version past the observed value.
    validate_success(api.create_case_note(
        case["id"], {"body": "intervening note", "is_confidential": False,
                     "expected_case_version": observed},
        bundle["worker_headers"],
    ), expected_status=201)

    stale = api.create_referral(
        case["id"],
        {"referral_type": "SELF_HELP", "self_help_resource_id": resource["id"],
         "expected_case_version": observed},
        bundle["worker_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    referrals = validate_success(api.list_referrals(bundle["worker_headers"]))
    assert referrals == [], "the stale proposal created no referral"


def test_occ_consent_stale_version(api):
    """PRD §2.6: "Appending a note to a case requires the request to carry
    `expected_case_version`; proposing a referral on a case likewise requires
    `expected_case_version`; and granting a consent on a caller requires
    `expected_caller_version`."
    PRD §2.6: "If the parent's version has advanced since that observation —
    because another writer appended a note, proposed a referral, edited case facts,
    or triggered a cascade that legitimately mutated the parent — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412). A successful guarded write itself
    advances the parent's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_consent_stale_version
    """
    caller = create_caller()
    headers = make_caller_headers(caller["id"])
    observed = caller["version"]

    validate_success(api.grant_consent(
        caller["id"], {"consent_type": "RECORDING",
                       "expected_caller_version": observed}, headers,
    ), expected_status=201)
    fresh = get_caller(caller["id"], headers=headers)
    assert fresh["version"] == observed + 1

    replay = api.grant_consent(
        caller["id"], {"consent_type": "DATA_SHARING",
                       "expected_caller_version": observed}, headers,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    validate_success(api.grant_consent(
        caller["id"], {"consent_type": "DATA_SHARING",
                       "expected_caller_version": fresh["version"]}, headers,
    ), expected_status=201)
    consents = list_consents(caller["id"], headers=headers)
    assert len(consents) == 2
    assert all(c["status"] == "GRANTED" for c in consents)


def test_stale_version_beats_state(api):
    """PRD §2.10: "**Optimistic concurrency.** A stale `expected_case_version` or
    `expected_caller_version` is rejected with `ERR_STALE_VERSION` — before any
    state-machine question is considered."
    PRD §2.10: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order and the first failing check determines
    the error returned; ordering matters because an early rejection masks later
    ones."

    Design: Corner/validations/stale_version_beats_state
    """
    bundle = _case_in_progress(api)
    case = bundle["case"]
    observed = case["version"]
    transition_case_ok(bundle, case["id"], "RESOLVED")
    transition_case_ok(bundle, case["id"], "CLOSED",
                       headers=TEST_USERS["supervisor_headers"])

    # The captured version is stale after RESOLVED/CLOSED: OCC (priority 6)
    # fires before the CLOSED state check (priority 7).
    resp = api.create_case_note(
        case["id"], {"body": "late note", "is_confidential": False,
                     "expected_case_version": observed},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_consent_expiry_ttl_boundary(api):
    """PRD §3.4: "The record is created `GRANTED` with `granted_at` set to the
    current logical time and `expires_at` computed as `granted_at` plus the type's
    time-to-live: seven days for `RECORDING`, thirty days for `FOLLOW_UP`, ninety
    days for `LEGAL_AID_RELEASE`, and three hundred sixty-five days for
    `DATA_SHARING`."
    PRD §3.4: "When the logical clock moves strictly past a consent's `expires_at`,
    the record transitions `GRANTED` → `EXPIRED`; exactly at `expires_at` it remains
    `GRANTED`."

    Design: Corner/state_machines/consent_expiry_ttl_boundary
    """
    caller = create_caller()
    consent = grant_consent(caller["id"], "FOLLOW_UP")
    assert_consent_record(consent)
    assert consent["status"] == "GRANTED"
    assert_instant_equal(consent["expires_at"], "2026-08-31T00:00:00Z",
                         "FOLLOW_UP TTL of 30 days from 2026-08-01")

    set_clock("2026-08-31T00:00:00Z")
    first = run_time_sweep()
    assert first["consents_expired"] == 0, (
        "exactly at expires_at the strict-> boundary keeps it GRANTED"
    )

    set_clock("2026-08-31T00:00:01Z")
    second = run_time_sweep()
    assert second["consents_expired"] == 1
    current = [c for c in list_consents(caller["id"]) if c["id"] == consent["id"]]
    assert current[0]["status"] == "EXPIRED"
