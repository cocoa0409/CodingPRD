"""International authentication of copies, delayed-registration hearing-slot
conflicts, and statistics-report period overlap, counts, and state remittance."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_facility,
    create_vital_event,
    create_packet,
    create_apostille,
    setup_registered_birth_event,
    setup_id_verified_copy,
    event_version,
    file_event,
    register_event,
    create_report_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / apostille_authenticate_blocked_when_copy_not_issued
# ---------------------------------------------------------------------------
def test_authenticate_apostille_copy_not_issued_blocked(api):
    """PRD §3.7: "A `StateRegistrar` authenticates a submitted request, advancing
    it from `SUBMITTED` to the terminal `AUTHENTICATED` state and stamping
    `authenticated_at`, but only when the referenced copy request is in `ISSUED`
    status; otherwise the request is rejected with `ERR_COPY_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/apostille_authenticate_blocked_when_copy_not_issued
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-18",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", id_document_type="PASSPORT",
        copy_count=1,
    )  # ID_VERIFIED, not issued
    ap = create_apostille(copy["id"], destination_country="FR", apostille_type="APOSTILLE")
    resp = api.authenticate_apostille(ap["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_COPY_NOT_ISSUED)


def test_authenticate_apostille_succeeds_after_copy_issued(api):
    """PRD §3.7: "A `StateRegistrar` authenticates a submitted request, advancing
    it from `SUBMITTED` to the terminal `AUTHENTICATED` state and stamping
    `authenticated_at`, but only when the referenced copy request is in `ISSUED`
    status; otherwise the request is rejected with `ERR_COPY_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/apostille_authenticate_blocked_when_copy_not_issued
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-18",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", id_document_type="PASSPORT",
        copy_count=1,
    )
    validate_success(api.issue_copy_request(
        copy["id"], {"expected_vital_event_version": event_version(ev["id"])}, REGISTRAR
    ))
    ap = create_apostille(copy["id"], destination_country="FR", apostille_type="APOSTILLE")
    authed = validate_success(api.authenticate_apostille(ap["id"], REGISTRAR))
    assert authed["status"] == "AUTHENTICATED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / hearing_slot_closed_interval_buffer_conflict
# ---------------------------------------------------------------------------
def _draft_event(jur="CTY-19"):
    fac = create_facility(jurisdiction_code=jur)
    ev = create_vital_event(fac["id"], jurisdiction_code=jur)
    return ev


def test_hearing_slot_within_buffer_conflict(api):
    """PRD §3.3: "concretely, a conflict exists whenever the new packet's
    `hearing_start` is no later than the other packet's `hearing_end` plus 15
    minutes and the other packet's `hearing_start` is no later than the new
    packet's `hearing_end` plus 15 minutes. A conflict is rejected with
    `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_slot_closed_interval_buffer_conflict
    """
    ev = _draft_event("CTY-19")
    pa = create_packet(
        ev["id"], packet_type="DELAYED", documentary_evidence_count=2,
        hearing_start="2026-03-10T09:00:00Z", hearing_end="2026-03-10T10:00:00Z",
        hearing_jurisdiction_code="HRG-19",
    )
    validate_success(api.accept_packet(pa["id"], REGISTRAR))
    pb = create_packet(
        ev["id"], packet_type="DELAYED", documentary_evidence_count=3,
        hearing_start="2026-03-10T10:10:00Z", hearing_end="2026-03-10T11:00:00Z",
        hearing_jurisdiction_code="HRG-19",
    )  # gap of 10 minutes (< 15-minute buffer)
    resp = api.accept_packet(pb["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_HEARING_SLOT_CONFLICT)


def test_hearing_slot_outside_buffer_accepts(api):
    """PRD §3.3: "concretely, a conflict exists whenever the new packet's
    `hearing_start` is no later than the other packet's `hearing_end` plus 15
    minutes and the other packet's `hearing_start` is no later than the new
    packet's `hearing_end` plus 15 minutes. A conflict is rejected with
    `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_slot_closed_interval_buffer_conflict
    """
    ev = _draft_event("CTY-19")
    pa = create_packet(
        ev["id"], packet_type="DELAYED", documentary_evidence_count=2,
        hearing_start="2026-03-10T09:00:00Z", hearing_end="2026-03-10T10:00:00Z",
        hearing_jurisdiction_code="HRG-19",
    )
    validate_success(api.accept_packet(pa["id"], REGISTRAR))
    pb = create_packet(
        ev["id"], packet_type="DELAYED", documentary_evidence_count=3,
        hearing_start="2026-03-10T10:16:00Z", hearing_end="2026-03-10T11:00:00Z",
        hearing_jurisdiction_code="HRG-19",
    )  # starts 16 minutes after prior end (> 15-minute buffer)
    accepted = validate_success(api.accept_packet(pb["id"], REGISTRAR))
    assert accepted["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / statistics_period_half_open_overlap_rejected
# ---------------------------------------------------------------------------
def test_report_period_overlap_rejected(api):
    """PRD §3.8: "A new report's window must not overlap an existing report in the
    same `jurisdiction_code`; adjacency is permitted, so a new window may begin
    exactly at the instant a prior window ended, but any true overlap is rejected
    with `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/statistics_period_half_open_overlap_rejected
    """
    validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-20",
                              period_start="2026-01-01T00:00:00Z",
                              period_end="2026-02-01T00:00:00Z"),
        REGISTRAR), expected_status=201)
    resp = api.create_report(
        create_report_payload(jurisdiction_code="CTY-20",
                              period_start="2026-01-15T00:00:00Z",
                              period_end="2026-03-01T00:00:00Z"),
        REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)


def test_report_period_adjacent_allowed(api):
    """PRD §3.8: "A new report's window must not overlap an existing report in the
    same `jurisdiction_code`; adjacency is permitted, so a new window may begin
    exactly at the instant a prior window ended, but any true overlap is rejected
    with `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/statistics_period_half_open_overlap_rejected
    """
    validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-20",
                              period_start="2026-01-01T00:00:00Z",
                              period_end="2026-02-01T00:00:00Z"),
        REGISTRAR), expected_status=201)
    # Adjacency (a new window beginning exactly when the prior ended) is permitted:
    # the second create must succeed with 201. PRD §3.8 is silent on the echo format
    # of period_start, so no exact-string assertion is made on it here.
    validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-20",
                              period_start="2026-02-01T00:00:00Z",
                              period_end="2026-03-01T00:00:00Z"),
        REGISTRAR), expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / state_remittance_round_per_txn_then_sum
# ---------------------------------------------------------------------------
def _two_issued_indigent_copies(api, jur="CTY-07"):
    """Registered BIRTH with two ISSUED INDIGENT copy_count=3 copies (1550c each),
    both issued at clock 2026-03-05. Returns the vital event."""
    fac, ev = setup_registered_birth_event(jurisdiction_code=jur,
                                           event_date="2026-02-25T00:00:00Z")
    set_clock("2026-03-05T00:00:00Z")
    for _ in range(2):
        copy = setup_id_verified_copy(
            ev["id"], requester_relationship="SELF", requester_category="INDIGENT",
            id_document_type="STATE_ID", copy_count=3,
        )
        validate_success(api.issue_copy_request(
            copy["id"], {"expected_vital_event_version": event_version(ev["id"])},
            REGISTRAR,
        ))
    return ev


def test_state_remittance_rounds_per_transaction_then_sums(api):
    """PRD §3.8: "The report's `state_remittance_cents` is the state's 45-percent
    share, computed per transaction and then summed: for each qualifying copy the
    system takes 45 percent of that copy's `fee_total_cents` and rounds it half up
    to a whole cent, and only then adds those rounded per-copy shares together."

    Design: Difficulty/combinatorial_formula/state_remittance_round_per_txn_then_sum
    """
    _two_issued_indigent_copies(api, "CTY-07")
    report = validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-07",
                              period_start="2026-03-01T00:00:00Z",
                              period_end="2026-04-01T00:00:00Z"),
        REGISTRAR), expected_status=201)
    assert report["state_remittance_cents"] == 1396


def test_total_fees_collected_is_plain_sum(api):
    """PRD §3.8: "The report's `total_fees_collected_cents` is the plain sum of
    `fee_total_cents` across those copies."

    Design: Difficulty/combinatorial_formula/state_remittance_round_per_txn_then_sum
    """
    _two_issued_indigent_copies(api, "CTY-07")
    report = validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-07",
                              period_start="2026-03-01T00:00:00Z",
                              period_end="2026-04-01T00:00:00Z"),
        REGISTRAR), expected_status=201)
    assert report["total_fees_collected_cents"] == 3100


# ---------------------------------------------------------------------------
# Corner: calculations / statistics_counts_births_in_period
# ---------------------------------------------------------------------------
def test_statistics_counts_births_in_period(api):
    """PRD §3.8: "Within that pool, `birth_count` is the number of `BIRTH` events,
    `death_count` the number of `DEATH` events, and `fetal_death_count` the number
    of `FETAL_DEATH` events."
    PRD §3.8: "Report creation computes its counts over the events belonging to
    the report's jurisdiction whose `status` is `REGISTERED` or `AMENDED` and
    whose `event_date` falls in the half-open window from `period_start` up to but
    not including `period_end`."

    Design: Corner/calculations/statistics_counts_births_in_period
    """
    fac = create_facility(jurisdiction_code="CTY-44")
    for name in ("One", "Two"):
        ev = create_vital_event(
            fac["id"], event_type="BIRTH", event_date="2026-02-25T00:00:00Z",
            jurisdiction_code="CTY-44", subject_first_name=name,
        )
        file_event(ev["id"], fac["id"])
        register_event(ev["id"])
    report = validate_success(api.create_report(
        create_report_payload(jurisdiction_code="CTY-44",
                              period_start="2026-02-01T00:00:00Z",
                              period_end="2026-03-01T00:00:00Z"),
        REGISTRAR), expected_status=201)
    assert report["birth_count"] == 2
    assert report["death_count"] == 0
