"""Approved sources, material certs, counterfeit containment, process windows (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_material_cert,
    assert_ncr,
    assert_source,
    assert_process_approval,
    create_approved_source,
    create_material_cert_payload,
    create_process_approval,
    create_serial_batch_payload,
    create_source_payload,
    create_accepted_cert,
    create_released_po,
    create_work_order,
    get_serial,
    get_success_data,
    get_work_order,
    make_headers,
    setup_wo_in_production,
    validate_error,
    validate_success,
)

SCM = TEST_USERS["supply_chain_manager"]
MP = TEST_USERS["manufacturing_planner"]
QM = TEST_USERS["quality_manager"]
QI = TEST_USERS["quality_inspector"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / material_revoke_counterfeit_cascade
# ---------------------------------------------------------------------------

def test_cert_revocation_quarantines_serials(api):
    """PRD §3.3: "The revocation cascade then runs four links. First, every
    serial number machined from this cert — every serial whose
    `material_cert_id` references it — that is still `CREATED` moves to
    `QUARANTINED`. Second, every work order owning a serial that just became
    `QUARANTINED`, and currently `IN_PRODUCTION`, moves to `QUALITY_HOLD`."

    Design: Difficulty/transitive_cascade/material_revoke_counterfeit_cascade
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    cert = bundle["cert"]
    revoked = validate_success(
        api_client.revoke_material_cert(cert["id"], {"reason": "suspect counterfeit mill cert"}, QM)
    )
    assert_material_cert(revoked)
    assert revoked["status"] == "REVOKED"
    for serial in bundle["serials"]:
        after = get_serial(serial["id"])
        assert after["status"] == "QUARANTINED", (
            f"every CREATED serial machined from the revoked cert must be "
            f"quarantined, got {after['status']}"
        )


def test_cert_revocation_holds_work_order_and_opens_ncr(api):
    """PRD §3.3: "Second, every work order owning a serial that just became
    `QUARANTINED`, and currently `IN_PRODUCTION`, moves to `QUALITY_HOLD`.
    Third, each work order pushed to `QUALITY_HOLD` gets an auto-created
    nonconformance report with `origin` `AUTO_COUNTERFEIT`, `defect_code`
    `COUNTERFEIT_SUSPECT`, `quantity_affected` equal to the number of serials
    quarantined on that work order, and status `OPEN`."

    Design: Difficulty/transitive_cascade/material_revoke_counterfeit_cascade
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    validate_success(
        api_client.revoke_material_cert(
            bundle["cert"]["id"], {"reason": "suspect counterfeit mill cert"}, QM
        )
    )
    wo = get_work_order(bundle["wo"]["id"])
    assert wo["status"] == "QUALITY_HOLD", (
        f"the in-production WO owning quarantined serials must be held, got "
        f"{wo['status']}"
    )
    ncrs = get_success_data(api_client.list_ncrs(QM, params={"wo_id": bundle['wo']['id']}))
    assert isinstance(ncrs, list) and len(ncrs) == 1, (
        f"exactly one counterfeit-suspect NCR must be auto-created, got {len(ncrs)}"
    )
    ncr = ncrs[0]
    assert_ncr(ncr)
    assert ncr["origin"] == "AUTO_COUNTERFEIT"
    assert ncr["defect_code"] == "COUNTERFEIT_SUSPECT"
    assert ncr["quantity_affected"] == 2, (
        f"quantity_affected equals the quarantined serial count, got "
        f"{ncr['quantity_affected']}"
    )
    assert ncr["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / serial_create_safety_beats_fiscal
# ---------------------------------------------------------------------------

def test_serial_create_revoked_cert_masks_quantity_error(api):
    """PRD §3.5: "The work order must be `RELEASED` or `IN_PRODUCTION`,
    failing with `ERR_WO_NOT_ACCEPTING_SERIALS` otherwise; per §2.11 this state
    check precedes the certificate checks, which precede the quantity checks.
    The referenced certification must be `ACCEPTED`: a cert still `RECEIVED`
    fails with `ERR_MATERIAL_CERT_NOT_ACCEPTED`, and a `REVOKED` cert fails
    with `ERR_MATERIAL_CERT_REVOKED`. The batch size may not exceed the cert's
    `quantity_available` (`ERR_INSUFFICIENT_MATERIAL_QUANTITY`, equality
    allowed), and `serials_created_count` plus the batch `count` may not exceed
    the work order's `quantity` (`ERR_SERIAL_BATCH_EXCEEDS_QUANTITY`)."

    Design: Difficulty/priority_pair_validation_conflict/serial_create_safety_beats_fiscal
    """
    bundle = create_released_po(quantity=10)
    wo = create_work_order(bundle["po"]["id"], quantity=10)
    get_success_data(api_client.release_work_order(wo["id"], MP))
    cert = create_accepted_cert(quantity_received=5)
    validate_success(
        api_client.revoke_material_cert(cert["id"], {"reason": "suspect counterfeit"}, QM)
    )
    # Both the revoked-cert safety gate and the quantity capacity check are
    # violated (count 10 > available 5); the certificate error is reported.
    resp = api_client.create_serial_batch(
        wo["id"], create_serial_batch_payload(material_cert_id=cert["id"], count=10), MP
    )
    err = validate_error(resp, ApiErrorId.ERR_MATERIAL_CERT_REVOKED.value)
    assert err["error_id"] != "ERR_INSUFFICIENT_MATERIAL_QUANTITY", (
        "the certificate safety check must mask the fiscal quantity check"
    )


def test_serial_create_revoked_cert_rejected_within_quantity(api):
    """PRD §3.5: "The referenced certification must be `ACCEPTED`: a cert
    still `RECEIVED` fails with `ERR_MATERIAL_CERT_NOT_ACCEPTED`, and a
    `REVOKED` cert fails with `ERR_MATERIAL_CERT_REVOKED`."

    Design: Difficulty/priority_pair_validation_conflict/serial_create_safety_beats_fiscal
    """
    bundle = create_released_po(quantity=10)
    wo = create_work_order(bundle["po"]["id"], quantity=10)
    get_success_data(api_client.release_work_order(wo["id"], MP))
    cert = create_accepted_cert(quantity_received=5)
    validate_success(
        api_client.revoke_material_cert(cert["id"], {"reason": "suspect counterfeit"}, QM)
    )
    # A count within the available quantity still fails on the revoked cert.
    resp = api_client.create_serial_batch(
        wo["id"], create_serial_batch_payload(material_cert_id=cert["id"], count=3), MP
    )
    validate_error(resp, ApiErrorId.ERR_MATERIAL_CERT_REVOKED.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / spa_half_open_adjacency
# ---------------------------------------------------------------------------

def test_spa_overlapping_window_rejected(api):
    """PRD §3.3: "The window is half-open: it covers dates from `valid_from`
    inclusive up to but not including `valid_to`, and a `valid_to` not later
    than `valid_from` is rejected with `ERR_INVALID_WINDOW` (400). Two `ACTIVE`
    windows for the same source and `process_code` may not overlap — a
    conflicting grant is rejected with `ERR_APPROVAL_WINDOW_OVERLAP` (409) —
    but because the window is half-open, adjacency is permitted: a new window
    whose `valid_from` equals an existing window's `valid_to` does not overlap
    it."

    Design: Difficulty/resource_temporal_overlap/spa_half_open_adjacency
    """
    source = create_approved_source(approval_scope="SPECIAL_PROCESS")
    first = create_process_approval(
        source["id"],
        process_code="HEAT_TREAT",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        cert_reference="NADCAP-HT-1",
    )
    assert_process_approval(first)
    assert first["status"] == "ACTIVE"
    resp = api_client.create_process_approval(
        {
            "source_id": source["id"],
            "process_code": "HEAT_TREAT",
            "valid_from": "2026-06-01",
            "valid_to": "2026-09-01",
            "cert_reference": "NADCAP-HT-2",
        },
        SCM,
    )
    validate_error(resp, ApiErrorId.ERR_APPROVAL_WINDOW_OVERLAP.value)


def test_spa_adjacent_window_allowed(api):
    """PRD §3.3: "Two `ACTIVE` windows for the same source and `process_code`
    may not overlap — a conflicting grant is rejected with
    `ERR_APPROVAL_WINDOW_OVERLAP` (409) — but because the window is half-open,
    adjacency is permitted: a new window whose `valid_from` equals an existing
    window's `valid_to` does not overlap it."

    Design: Difficulty/resource_temporal_overlap/spa_half_open_adjacency
    """
    source = create_approved_source(approval_scope="SPECIAL_PROCESS")
    create_process_approval(
        source["id"],
        process_code="HEAT_TREAT",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        cert_reference="NADCAP-HT-1",
    )
    adjacent = create_process_approval(
        source["id"],
        process_code="HEAT_TREAT",
        valid_from="2026-07-01",
        valid_to="2027-01-01",
        cert_reference="NADCAP-HT-3",
    )
    assert_process_approval(adjacent)
    assert adjacent["status"] == "ACTIVE", (
        "adjacency at valid_from == existing valid_to is permitted (half-open)"
    )


# ---------------------------------------------------------------------------
# Corner: validations / cert_create_unapproved_source_rejected
# ---------------------------------------------------------------------------

def test_cert_create_unapproved_source_rejected(api):
    """PRD §3.3: "A `SupplyChainManager` registers a mill cert with
    `source_id`, `heat_number`, a `material_spec` such as AMS 5643, and a
    positive `quantity_received`. The source must be `APPROVED` with
    `RAW_MATERIAL` or `DISTRIBUTOR` scope, failing with
    `ERR_SOURCE_NOT_APPROVED` otherwise."

    Design: Corner/validations/cert_create_unapproved_source_rejected
    """
    src = validate_success(
        api_client.create_source(create_source_payload(), SCM), expected_status=201
    )
    assert src["status"] == "PROVISIONAL"
    resp = api_client.create_material_cert(
        create_material_cert_payload(source_id=src["id"], quantity_received=5), SCM
    )
    validate_error(resp, ApiErrorId.ERR_SOURCE_NOT_APPROVED.value)


# ---------------------------------------------------------------------------
# Corner: validations / source_approve_high_risk_rejected
# ---------------------------------------------------------------------------

def test_source_approve_high_risk_rejected(api):
    """PRD §3.3: "Approval moves `PROVISIONAL → APPROVED` (from any other
    state, `ERR_SOURCE_NOT_APPROVABLE`), with one counterfeit gate: a source
    rated `HIGH` risk may not be approved for the `RAW_MATERIAL` or
    `DISTRIBUTOR` scope, the attempt failing with
    `ERR_COUNTERFEIT_RISK_TOO_HIGH`."

    Design: Corner/validations/source_approve_high_risk_rejected
    """
    src = validate_success(
        api_client.create_source(
            create_source_payload(
                approval_scope="RAW_MATERIAL", counterfeit_risk_rating="HIGH"
            ),
            SCM,
        ),
        expected_status=201,
    )
    resp = api_client.approve_source(src["id"], SCM)
    validate_error(resp, ApiErrorId.ERR_COUNTERFEIT_RISK_TOO_HIGH.value)
    after = validate_success(api_client.get_source(src["id"], SCM))
    assert after["status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Corner: validations / cert_accept_by_creator_forbidden
# ---------------------------------------------------------------------------

def test_cert_accept_by_creator_forbidden(api):
    """PRD §2.9: "Third, the inspector who accepts a material certification at
    receiving inspection must not be the person who registered it: the
    acceptor's `X-User-ID` must differ from the certification's
    `created_by_user_id`."
    PRD §2.9: "Three operations enforce segregation of duties by comparing the
    caller's `X-User-ID` to an identifier anchored on the resource, rejecting
    a match with `ERR_SOD_VIOLATION` (403)."

    Design: Corner/validations/cert_accept_by_creator_forbidden
    """
    source = create_approved_source()
    cert = validate_success(
        api_client.create_material_cert(
            create_material_cert_payload(source_id=source["id"], quantity_received=5),
            SCM,  # created by scm-1
        ),
        expected_status=201,
    )
    # Accept under the QualityInspector role but with the creator's user id.
    resp = api_client.accept_material_cert(
        cert["id"], make_headers("scm-1", "QualityInspector")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ---------------------------------------------------------------------------
# Corner: errors / cert_accept_twice_rejected
# ---------------------------------------------------------------------------

def test_cert_accept_twice_rejected(api):
    """PRD §3.3: "Receiving inspection moves `RECEIVED → ACCEPTED` — from any
    other state, `ERR_CERT_NOT_ACCEPTABLE` — under segregation of duties: the
    accepting inspector's `X-User-ID` must differ from `created_by_user_id`,
    failing with `ERR_SOD_VIOLATION` on a match."

    Design: Corner/errors/cert_accept_twice_rejected
    """
    cert = create_accepted_cert(quantity_received=5)
    assert cert["status"] == "ACCEPTED"
    resp = api_client.accept_material_cert(cert["id"], QI)
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_ACCEPTABLE.value)


# ---------------------------------------------------------------------------
# Corner: errors / cert_revoke_twice_rejected
# ---------------------------------------------------------------------------

def test_cert_revoke_twice_rejected(api):
    """PRD §3.3: "A `QualityManager` revokes a cert — recording a `reason` —
    from `RECEIVED` or `ACCEPTED` to the terminal `REVOKED` state; revoking an
    already-`REVOKED` cert fails with `ERR_CERT_ALREADY_REVOKED`."

    Design: Corner/errors/cert_revoke_twice_rejected
    """
    cert = create_accepted_cert(quantity_received=5)
    revoked = validate_success(
        api_client.revoke_material_cert(cert["id"], {"reason": "suspect"}, QM)
    )
    assert revoked["status"] == "REVOKED"
    resp = api_client.revoke_material_cert(cert["id"], {"reason": "again"}, QM)
    validate_error(resp, ApiErrorId.ERR_CERT_ALREADY_REVOKED.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / source_disqualify_suspends_process_approvals
# ---------------------------------------------------------------------------

def test_source_disqualify_suspends_process_approvals(api):
    """PRD §3.3: "Disqualification moves `APPROVED → DISQUALIFIED` (from any
    other state, `ERR_SOURCE_NOT_APPROVABLE`), records a `reason`, and — as a
    containment side effect — suspends every special-process approval of that
    source currently `ACTIVE`."

    Design: Corner/state_machines/source_disqualify_suspends_process_approvals
    """
    source = create_approved_source(approval_scope="SPECIAL_PROCESS")
    pa = create_process_approval(
        source["id"],
        process_code="HEAT_TREAT",
        valid_from="2026-01-01",
        valid_to="2027-01-01",
        cert_reference="NADCAP-1",
    )
    assert pa["status"] == "ACTIVE"
    disqualified = validate_success(
        api_client.disqualify_source(source["id"], {"reason": "fraudulent certs"}, SCM)
    )
    assert_source(disqualified)
    assert disqualified["status"] == "DISQUALIFIED"
    pa_after = validate_success(api_client.get_process_approval(pa["id"], SCM))
    assert pa_after["status"] == "SUSPENDED", (
        f"disqualifying the source suspends its ACTIVE approvals, got "
        f"{pa_after['status']}"
    )


# ---------------------------------------------------------------------------
# Corner: state_machines / spa_suspend_reinstate_cycle
# ---------------------------------------------------------------------------

def test_spa_suspend_reinstate_cycle(api):
    """PRD §3.3: "Suspension moves `ACTIVE → SUSPENDED` and reinstatement
    moves `SUSPENDED → ACTIVE`, each from its named state only
    (`ERR_INVALID_STATE` otherwise); reinstatement re-applies the
    window-overlap rule against the source's other `ACTIVE` approvals of the
    same process, failing with `ERR_APPROVAL_WINDOW_OVERLAP` on conflict."

    Design: Corner/state_machines/spa_suspend_reinstate_cycle
    """
    source = create_approved_source(approval_scope="SPECIAL_PROCESS")
    pa = create_process_approval(
        source["id"],
        process_code="NDT",
        valid_from="2026-01-01",
        valid_to="2027-01-01",
        cert_reference="NADCAP-2",
    )
    suspended = validate_success(api_client.suspend_process_approval(pa["id"], SCM))
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api_client.reinstate_process_approval(pa["id"], SCM))
    assert reinstated["status"] == "ACTIVE", (
        "with no overlapping ACTIVE window, reinstatement restores ACTIVE"
    )
