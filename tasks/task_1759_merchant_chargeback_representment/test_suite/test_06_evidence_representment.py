"""Evidence assembly, packet creation/submission gates, OCC, deadlines, and
the cure cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assemble_packet,
    chargeback_version,
    create_evidence_item_payload,
    create_merchant,
    create_representment_payload,
    create_rule,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    make_merchant_user_headers,
    notify,
    post_outcome,
    set_clock,
    setup_notified_case,
    setup_submitted_case,
    submit_packet,
    upload_evidence,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_invalid_evidence_type_enum_rejected(api):
    """PRD §3.6: an item carries "an `evidence_type` of `RECEIPT`, `AVS_MATCH`,
    `CVV_MATCH`, `DELIVERY_PROOF`, `SIGNED_AGREEMENT`, `REFUND_PROOF`,
    `PRIOR_TXN_HISTORY`, `IP_DEVICE_LOG`, or `CARDHOLDER_COMMUNICATION`".
    PRD §2.9: "Payload shape — required fields present, types valid
    (`ERR_INVALID_REQUEST`, 400), and enum fields carrying declared members
    (`ERR_INVALID_ENUM`, 400)."

    Design: Corner/validations/invalid_enum_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m_id = bundle["merchant"]["id"]
    resp = api.create_evidence_item(
        create_evidence_item_payload(
            chargeback_id=bundle["chargeback"]["id"],
            evidence_type="PHOTO",
            document_uri="s3://ev/p.jpg",
        ),
        make_merchant_user_headers(m_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_evidence_upload_while_suspended_rejected(api):
    """PRD §3.1: "While a merchant is `SUSPENDED`, every merchant-side action
    is rejected with `ERR_MERCHANT_SUSPENDED` — evidence upload, representment
    creation and submission, chargeback acceptance, prevention-alert action,
    remediation-plan creation and submission, and education completion".

    Design: Corner/state_machines/evidence_upload_while_suspended_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m = bundle["merchant"]
    get_success_data(api.suspend_merchant(m["id"], RISK))

    resp = api.create_evidence_item(
        create_evidence_item_payload(
            chargeback_id=bundle["chargeback"]["id"],
            evidence_type="RECEIPT",
            document_uri="s3://ev/r.pdf",
        ),
        make_merchant_user_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)


def test_evidence_attach_to_wrong_chargeback_rejected(api):
    """PRD §3.6: "every listed id must resolve to an evidence item of this
    chargeback currently in `DRAFT` (else `ERR_EVIDENCE_NOT_ATTACHABLE`)".

    Design: Corner/validations/evidence_attach_wrong_chargeback_rejected
    """
    create_rule(api)
    m = create_merchant(api, legal_name="WrongEv M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, m["id"], "T-2", 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cb1 = ingest_chargeback(api, m["id"], "T-1", "NC-WE1", 10000)
    cb2 = ingest_chargeback(api, m["id"], "T-2", "NC-WE2", 10000)
    notify(api, cb1["id"])
    notify(api, cb2["id"])
    # The item belongs to the sibling case cb2.
    ev_other = upload_evidence(api, cb2["id"], m["id"], "RECEIPT", "s3://ev/other.pdf")

    resp = api.create_representment(
        create_representment_payload(
            chargeback_id=cb1["id"],
            evidence_item_ids=[ev_other["id"]],
            expected_chargeback_version=chargeback_version(api, cb1["id"]),
        ),
        make_merchant_user_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_ATTACHABLE)


def test_empty_evidence_packet_rejected(api):
    """PRD §3.6: "the `evidence_item_ids` list must be non-empty (else
    `ERR_EMPTY_EVIDENCE_PACKET`)".

    Design: Corner/validations/empty_packet_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    cb_id = bundle["chargeback"]["id"]
    resp = api.create_representment(
        create_representment_payload(
            chargeback_id=cb_id,
            evidence_item_ids=[],
            expected_chargeback_version=chargeback_version(api, cb_id),
        ),
        make_merchant_user_headers(bundle["merchant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_EVIDENCE_PACKET)


def test_representment_already_open_rejected(api):
    """PRD §3.6: "no other packet of this case may be `ASSEMBLED` or
    `SUBMITTED` (else `ERR_REPRESENTMENT_ALREADY_OPEN` — an in-flight packet is
    caught here, before the cure check)".

    Design: Corner/validations/representment_already_open_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    ev1 = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r1.pdf")
    ev2 = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r2.pdf")
    rep1 = assemble_packet(api, cb_id, m_id, [ev1["id"]])
    assert rep1["status"] == "ASSEMBLED"

    # Fresh OCC version, so the concurrency check passes and the open-packet
    # constraint is the one that fires.
    resp = api.create_representment(
        create_representment_payload(
            chargeback_id=cb_id,
            evidence_item_ids=[ev2["id"]],
            expected_chargeback_version=chargeback_version(api, cb_id),
        ),
        make_merchant_user_headers(m_id),
    )
    validate_error(resp, ApiErrorId.ERR_REPRESENTMENT_ALREADY_OPEN)


def test_occ_stale_representment_create_rejected(api):
    """PRD §2.8: "Creating a representment requires the request to carry
    `expected_chargeback_version` equal to the target chargeback's current
    `version`; if the chargeback's version has advanced since the client last
    observed it ... the create is rejected".
    PRD §2.9: "Optimistic concurrency — on the two OCC-guarded writes, the
    expected parent version matches (`ERR_STALE_VERSION`, 412)" ranks ahead of
    the uniqueness and structural constraints.

    Design: Corner/cross_cutting/occ_stale_representment_create_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    ev1 = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r1.pdf")
    ev2 = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r2.pdf")

    stale_version = chargeback_version(api, cb_id)
    rep1 = assemble_packet(api, cb_id, m_id, [ev1["id"]])
    assert rep1["status"] == "ASSEMBLED"
    # The first create bumped the chargeback version; the caller's captured
    # version is now stale. OCC fires ahead of the ALSO-violated open-packet
    # constraint.
    assert chargeback_version(api, cb_id) != stale_version

    resp = api.create_representment(
        create_representment_payload(
            chargeback_id=cb_id,
            evidence_item_ids=[ev2["id"]],
            expected_chargeback_version=stale_version,
        ),
        make_merchant_user_headers(m_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_double_submit_rejected(api):
    """PRD §3.6: "Submission sends an `ASSEMBLED` packet to the network;
    submitting a packet in any other state fails with
    `ERR_INVALID_REPRESENTMENT_STATE`."

    Design: Corner/state_machines/double_submit_rejected
    """
    bundle = setup_submitted_case(api, received_at="2026-07-15T00:00:00Z")
    rep = bundle["representment"]
    assert rep["status"] == "SUBMITTED"

    resp = api.submit_representment(
        rep["id"], make_merchant_user_headers(bundle["merchant"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REPRESENTMENT_STATE)


def test_outcome_on_assembled_packet_rejected(api):
    """PRD §3.7: "the packet must be `SUBMITTED`, and posting an outcome for a
    packet in any other state fails with `ERR_INVALID_REPRESENTMENT_STATE`."

    Design: Corner/state_machines/outcome_on_assembled_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    ev = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r.pdf")
    rep = assemble_packet(api, cb_id, m_id, [ev["id"]])
    assert rep["status"] == "ASSEMBLED"

    resp = api.post_network_outcome(rep["id"], {"outcome": "WON"}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REPRESENTMENT_STATE)


def test_evidence_incomplete_missing_type_rejected(api):
    """PRD §3.6: "the packet must satisfy compelling-evidence completeness:
    every type listed in the governing rule's `required_evidence_types` must be
    covered by at least one `ATTACHED` item of this packet, else the submit
    fails with `ERR_EVIDENCE_INCOMPLETE` (422)."

    Design: Corner/errors/evidence_incomplete_missing_type_rejected
    """
    bundle = setup_notified_case(
        api, required_types=("RECEIPT", "DELIVERY_PROOF"),
        received_at="2026-07-15T00:00:00Z",
    )
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    # The packet covers only RECEIPT; DELIVERY_PROOF stays uncovered.
    ev = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r.pdf")
    rep = assemble_packet(api, cb_id, m_id, [ev["id"]])

    resp = api.submit_representment(rep["id"], make_merchant_user_headers(m_id))
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_INCOMPLETE)

    after = get_success_data(api.get_representment(rep["id"], OPS))
    assert after["status"] == "ASSEMBLED"


def _setup_suspended_with_packet(api):
    """Notified case with a complete ASSEMBLED packet; merchant then suspended."""
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m = bundle["merchant"]
    cb_id = bundle["chargeback"]["id"]
    ev = upload_evidence(api, cb_id, m["id"], "RECEIPT", "s3://ev/r.pdf")
    rep = assemble_packet(api, cb_id, m["id"], [ev["id"]])
    get_success_data(api.suspend_merchant(m["id"], RISK))
    return bundle, rep


def test_representment_submit_blocked_by_suspended_merchant(api):
    """PRD §3.1: "While a merchant is `SUSPENDED`, every merchant-side action
    is rejected with `ERR_MERCHANT_SUSPENDED` — evidence upload, representment
    creation and submission, chargeback acceptance, prevention-alert action,
    remediation-plan creation and submission, and education completion".

    Design: Difficulty/cross_entity_state_dependency/representment_submit_blocked_by_suspended_merchant
    """
    bundle, rep = _setup_suspended_with_packet(api)
    resp = api.submit_representment(
        rep["id"], make_merchant_user_headers(bundle["merchant"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)


def test_representment_submit_unblocked_after_reinstatement(api):
    """PRD §3.1: "Suspension is a `RiskOfficer` action that moves the merchant
    `ACTIVE` → `SUSPENDED` and bumps its `version`; reinstatement moves it
    `SUSPENDED` → `ACTIVE` with another version bump." — once the parent
    merchant is ACTIVE again, the untouched packet submits normally.

    Design: Difficulty/cross_entity_state_dependency/representment_submit_blocked_by_suspended_merchant
    """
    bundle, rep = _setup_suspended_with_packet(api)
    m_id = bundle["merchant"]["id"]
    validate_error(
        api.submit_representment(rep["id"], make_merchant_user_headers(m_id)),
        ApiErrorId.ERR_MERCHANT_SUSPENDED,
    )

    get_success_data(api.reinstate_merchant(m_id, RISK))
    submitted = validate_success(
        api.submit_representment(rep["id"], make_merchant_user_headers(m_id))
    )
    assert submitted["status"] == "SUBMITTED"


def _setup_cured_case(api):
    """Packet submitted then RETURNED_FOR_CURE; fresh evidence uploaded for the
    successor packet. Returns (bundle, rep1, ev3, ev4)."""
    bundle = setup_submitted_case(
        api, required_types=("RECEIPT", "DELIVERY_PROOF"),
        merchant_overrides={"reserve_rate_bps": 0}, received_at="2026-07-15T00:00:00Z",
    )
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    rep1 = post_outcome(api, bundle["representment"]["id"], "RETURNED_FOR_CURE")
    ev3 = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r2.pdf")
    ev4 = upload_evidence(api, cb_id, m_id, "DELIVERY_PROOF", "s3://ev/d2.pdf")
    return bundle, rep1, ev3, ev4


def test_cure_successor_supersedes_returned_packet_and_releases_evidence(api):
    """PRD §3.6: "A prior `RETURNED_FOR_CURE` packet becomes `SUPERSEDED`, and
    its attached evidence returns to `DRAFT`; each evidence item named in the
    new packet moves `DRAFT` → `ATTACHED`." and "The new packet's `cure_count`
    is 0 when the case was `MERCHANT_NOTIFIED` — a first packet — and otherwise
    one more than the superseded packet's `cure_count`."
    PRD §3.7: a cure outcome "keeps the chargeback in `REPRESENTED` with the
    cure window open".

    Design: Difficulty/non_linear_state_machine/representment_cure_cycle_supersede
    """
    bundle, rep1, ev3, ev4 = _setup_cured_case(api)
    cb_id = bundle["chargeback"]["id"]

    # A returned packet leaves the case in REPRESENTED, not a new state.
    mid = get_success_data(api.get_chargeback(cb_id, OPS))
    assert mid["case_status"] == "REPRESENTED"

    rep2 = assemble_packet(api, cb_id, bundle["merchant"]["id"], [ev3["id"], ev4["id"]])
    assert rep2["cure_count"] == 1  # lineage carried forward: 0 -> 1

    rep1_after = get_success_data(api.get_representment(rep1["id"], OPS))
    assert rep1_after["status"] == "SUPERSEDED"
    ev1_after = get_success_data(
        api.get_evidence_item(bundle["evidence"][0]["id"], OPS)
    )
    assert ev1_after["status"] == "DRAFT"  # supersede bounces evidence back


def test_cure_limit_exceeded_on_second_return(api):
    """PRD §3.7: "An `outcome` of `RETURNED_FOR_CURE` keeps the case open: it
    is allowed only while the packet's `cure_count` is below 1 (else
    `ERR_CURE_LIMIT_EXCEEDED`)".

    Design: Difficulty/non_linear_state_machine/representment_cure_cycle_supersede
    """
    bundle, _rep1, ev3, ev4 = _setup_cured_case(api)
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    rep2 = assemble_packet(api, cb_id, m_id, [ev3["id"], ev4["id"]])
    submit_packet(api, rep2["id"], m_id)

    # MAX_CURES already consumed by this lineage (cure_count == 1).
    resp = api.post_network_outcome(rep2["id"], {"outcome": "RETURNED_FOR_CURE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_CURE_LIMIT_EXCEEDED)

    won = post_outcome(api, rep2["id"], "WON")
    assert won["status"] == "WON"
    cb_final = get_success_data(api.get_chargeback(cb_id, OPS))
    assert cb_final["case_status"] == "DECIDED_WON"


def _setup_deadline_pair(api):
    """Two cases received 2026-07-15 (due 2026-08-14T00:00:00Z):
    case 1 holds an ASSEMBLED first packet; case 2 runs through a cure so the
    case sits in REPRESENTED with an ASSEMBLED cure packet."""
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="Deadline M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, m["id"], "T-2", 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cb1 = ingest_chargeback(api, m["id"], "T-1", "NC-D1", 10000)
    cb2 = ingest_chargeback(api, m["id"], "T-2", "NC-D2", 10000)
    notify(api, cb1["id"])
    notify(api, cb2["id"])
    ev1 = upload_evidence(api, cb1["id"], m["id"], "RECEIPT", "s3://ev/c1.pdf")
    ev2 = upload_evidence(api, cb2["id"], m["id"], "RECEIPT", "s3://ev/c2.pdf")
    rep1 = assemble_packet(api, cb1["id"], m["id"], [ev1["id"]])
    rep2 = assemble_packet(api, cb2["id"], m["id"], [ev2["id"]])

    set_clock(api, "2026-07-20T00:00:00Z")
    submit_packet(api, rep2["id"], m["id"])
    post_outcome(api, rep2["id"], "RETURNED_FOR_CURE")
    ev3 = upload_evidence(api, cb2["id"], m["id"], "RECEIPT", "s3://ev/c2b.pdf")
    rep2b = assemble_packet(api, cb2["id"], m["id"], [ev3["id"]])
    return m, cb1, cb2, rep1, rep2b


def test_representment_deadline_inclusive_at_exact_instant(api):
    """PRD §3.6: "the current time must be on or before the case's
    `representment_due_at` — the deadline is inclusive, and a late submit fails
    with `ERR_REPRESENTMENT_DEADLINE_PASSED`."

    Design: Difficulty/boundary_precision_check/representment_deadline_inclusive_boundary
    """
    m, _cb1, _cb2, rep1, _rep2b = _setup_deadline_pair(api)
    set_clock(api, "2026-08-14T00:00:00Z")  # exactly the deadline
    submitted = validate_success(
        api.submit_representment(rep1["id"], make_merchant_user_headers(m["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


def test_representment_deadline_passed_one_second_late(api):
    """PRD §3.6: "the current time must be on or before the case's
    `representment_due_at` — the deadline is inclusive, and a late submit fails
    with `ERR_REPRESENTMENT_DEADLINE_PASSED`."
    PRD §2.5: "any chargeback still in `RECEIVED` or `MERCHANT_NOTIFIED` whose
    `representment_due_at` has passed becomes `EXPIRED`" — a REPRESENTED case
    is outside the sweep, so the temporal gate itself answers.

    Design: Difficulty/boundary_precision_check/representment_deadline_inclusive_boundary
    """
    m, cb1, cb2, _rep1, rep2b = _setup_deadline_pair(api)
    set_clock(api, "2026-08-14T00:00:01Z")  # one second past the deadline
    # The REPRESENTED case was not swept; the deadline gate fires.
    cb2_now = get_success_data(api.get_chargeback(cb2["id"], OPS))
    assert cb2_now["case_status"] == "REPRESENTED"

    resp = api.submit_representment(rep2b["id"], make_merchant_user_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_REPRESENTMENT_DEADLINE_PASSED)


def _setup_expired_unsubmitted_packet(api):
    """Complete packet ASSEMBLED but never submitted; the clock then advances
    past the representment deadline so the expiry sweep fires."""
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="Prio M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-1", 10000)
    notify(api, cb["id"])
    ev = upload_evidence(api, cb["id"], m["id"], "RECEIPT", "s3://ev/r.pdf")
    rep = assemble_packet(api, cb["id"], m["id"], [ev["id"]])
    set_clock(api, "2026-08-15T00:00:00Z")
    return m, cb, rep


def test_expiry_sweep_supersedes_unsubmitted_packet(api):
    """PRD §3.5: "when the clock is set past `representment_due_at`, a case
    still in `RECEIVED` or `MERCHANT_NOTIFIED` becomes `EXPIRED` (terminal),
    its `funds_status` becomes `DEBIT_FINAL`, any `ASSEMBLED` packet of the
    case is superseded — its attached evidence returning to `DRAFT`".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_outranks_temporal
    """
    m, cb, rep = _setup_expired_unsubmitted_packet(api)
    cb_after = get_success_data(api.get_chargeback(cb["id"], OPS))
    assert cb_after["case_status"] == "EXPIRED"
    rep_after = get_success_data(api.get_representment(rep["id"], OPS))
    assert rep_after["status"] == "SUPERSEDED"


def test_submit_after_expiry_reports_state_error_not_deadline(api):
    """PRD §2.9: the priority order is "evaluated from first to last" with
    "5. State permissibility — the target or guarding entity is in a state that
    permits the operation" ranking ahead of "8. Deadline gates —
    `ERR_REPRESENTMENT_DEADLINE_PASSED` and `ERR_ACCEPT_WINDOW_PASSED` (both
    409), remembering that deadlines are inclusive."
    PRD §3.6: "submitting a packet in any other state fails with
    `ERR_INVALID_REPRESENTMENT_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/submit_state_outranks_temporal
    """
    m, _cb, rep = _setup_expired_unsubmitted_packet(api)
    # The packet is SUPERSEDED and the deadline has also passed; the state
    # error outranks the temporal error.
    resp = api.submit_representment(rep["id"], make_merchant_user_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REPRESENTMENT_STATE)
