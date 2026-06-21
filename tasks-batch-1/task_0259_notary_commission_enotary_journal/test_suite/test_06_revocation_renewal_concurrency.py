"""Revocation cascade, bond coverage overlap, renewal grace, the OCC renewal
guard, and the state-beats-referential priority conflict on begin-identity.

Covers the revoke cascade, the closed-interval bond overlap, the renewal grace
evaluation-order instance, the OCC corners, and the state/referential priority
pair.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_notary_headers,
    create_bond_payload,
    create_renewal_payload,
    TEST_USERS,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]


# ===========================================================================
# transitive_cascade: revoke terminates sessions, refuses documents
# ===========================================================================
def test_revoke_terminates_session_and_refuses_documents(api):
    """PRD §3.9: "Revocation is terminal and may be triggered from either `ACTIVE`
    or `SUSPENDED` by a `CommissionAuthority` operator ... Revocation sets
    `enotary_authorized` to `false`, cascades the notary's bond to the terminal
    `CANCELLED` status ... When revocation is driven from `ACTIVE`, every
    non-terminal session of the notary is additionally cascaded to `TERMINATED` and
    each such session's `PENDING` documents to `REFUSED`, exactly as for
    suspension."

    Design: Difficulty/transitive_cascade/revoke_terminates_session_refuses_documents
    """
    ctx = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nrev@x.com"})
    notary, bond = ctx["notary"], ctx["bond"]
    built = th.setup_session_to_active(
        notary["id"], "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z",
        documents=[("JURAT", 400)],
    )
    sess = built["session"]
    doc = built["documents"][0]
    revoked = validate_success(api.revoke_notary(notary["id"], CA))
    assert revoked["status"] == "REVOKED"
    refreshed_sess = validate_success(api.get_session(sess["id"], CA))
    assert refreshed_sess["status"] == "TERMINATED"
    refreshed_doc = validate_success(api.get_document(doc["id"], CA))
    assert refreshed_doc["status"] == "REFUSED"
    refreshed_bond = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed_bond["status"] == "CANCELLED"


def test_revoke_cancels_bond(api):
    """PRD §3.9: "Revocation sets `enotary_authorized` to `false`, cascades the
    notary's bond to the terminal `CANCELLED` status, and writes an audit record."

    Design: Difficulty/transitive_cascade/revoke_terminates_session_refuses_documents
    """
    ctx = th.setup_active_notary(notary_overrides={"email": "nrev2@x.com"})
    notary, bond = ctx["notary"], ctx["bond"]
    revoked = validate_success(api.revoke_notary(notary["id"], CA))
    assert revoked["status"] == "REVOKED"
    assert revoked["enotary_authorized"] is False
    refreshed_bond = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed_bond["status"] == "CANCELLED"


# ===========================================================================
# resource_temporal_overlap: closed bond interval, touching endpoints conflict
# ===========================================================================
def test_bond_coverage_touching_endpoints_conflict(api):
    """PRD §3.3: "Bond coverage intervals are treated as **closed** on both ends ...
    Crucially, touching endpoints conflict — if one bond's coverage ends at the
    very instant another's begins, they are considered overlapping. Any such
    overlap rejects the activation with `ERR_BOND_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bond_closed_interval_touching_endpoints_conflict
    """
    jx = th.create_jurisdiction(state_code="TX")
    notary = th.register_notary(jx["id"], email="nto2@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:00Z", coverage_end_at="2034-06-01T00:00:00Z")
    resp = api.activate_bond(bond2["id"], CA)
    validate_error(resp, ApiErrorId.ERR_BOND_COVERAGE_OVERLAP.value, expected_status=409)
    refreshed = validate_success(api.get_bond(bond2["id"], CA))
    assert refreshed["status"] == "PENDING"


def test_bond_coverage_non_touching_intervals_allowed(api):
    """PRD §3.3: "When a bond is activated, the server compares its coverage
    interval against every *other* `ACTIVE` bond of the same notary ... Two closed
    intervals overlap when the first interval's start is at or before the second's
    end and the second interval's start is at or before the first's end."
    PRD §3.2: "Activating a bond moves it from `PENDING` to `ACTIVE`"

    Design: Difficulty/resource_temporal_overlap/bond_closed_interval_touching_endpoints_conflict
    """
    jx = th.create_jurisdiction(state_code="TX")
    notary = th.register_notary(jx["id"], email="nto2b@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    # second bond starts strictly after the first ends (no shared endpoint)
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:01Z", coverage_end_at="2034-06-01T00:00:00Z")
    data = validate_success(api.activate_bond(bond2["id"], CA))
    assert data["status"] == "ACTIVE"


# ===========================================================================
# combinatorial_formula: renewal grace deadline evaluation order
# ===========================================================================
def test_renewal_filed_past_grace_deadline_blocks_approval(api):
    """PRD §3.10: "the grace deadline is computed as the notary's
    `commission_expires_at` plus the jurisdiction's `renewal_grace_days` days, and
    `filed_within_grace` is `true` exactly when the current clock instant is at or
    before that deadline"
    PRD §3.10: "requires `filed_within_grace` to be `true` — a renewal that was
    filed outside the grace window cannot be approved and is rejected with
    `ERR_RENEWAL_OUT_OF_GRACE` even though it could still be submitted"

    Design: Difficulty/combinatorial_formula/renewal_grace_deadline_evaluation_order
    """
    th.set_clock("2026-06-01T00:00:00Z")
    jx = th.create_jurisdiction(state_code="TX", commission_term_months=48, renewal_grace_days=30)
    notary = th.register_notary(jx["id"], email="ngrace@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    validate_success(api.commission_notary(notary["id"], CA))
    validate_success(api.activate_notary(notary["id"], CA))
    current = validate_success(api.get_notary(notary["id"], CA))
    # second bond for the renewed term (non-touching window)
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:01Z", coverage_end_at="2034-06-01T00:00:00Z")
    th.activate_bond(bond2["id"])
    # commission expires 2030-06-01; grace deadline 2030-07-01; file at 2030-07-02 (past)
    th.set_clock("2030-07-02T00:00:00Z")
    rnw = validate_success(
        api.create_renewal(
            create_renewal_payload(notary["id"], current["version"], bond2["id"]), CA
        ),
        201,
    )
    assert rnw["filed_within_grace"] is False
    resp = api.approve_renewal(rnw["id"], CA)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_OUT_OF_GRACE.value, expected_status=409)
    refreshed = validate_success(api.get_renewal(rnw["id"], CA))
    assert refreshed["status"] == "SUBMITTED"


def test_renewal_filed_within_grace_can_be_approved(api):
    """PRD §3.10: "`filed_within_grace` is `true` exactly when the current clock
    instant is at or before that deadline — a renewal filed at the very instant of
    the deadline is still within grace."
    PRD §3.10: "Approving a renewal is performed by a `CommissionAuthority`
    operator and moves the renewal from `SUBMITTED` to the terminal `APPROVED`
    status."

    Design: Difficulty/combinatorial_formula/renewal_grace_deadline_evaluation_order
    """
    th.set_clock("2026-06-01T00:00:00Z")
    jx = th.create_jurisdiction(state_code="TX", commission_term_months=48, renewal_grace_days=30)
    notary = th.register_notary(jx["id"], email="ngrace2@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    validate_success(api.commission_notary(notary["id"], CA))
    validate_success(api.activate_notary(notary["id"], CA))
    current = validate_success(api.get_notary(notary["id"], CA))
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:01Z", coverage_end_at="2034-06-01T00:00:00Z")
    th.activate_bond(bond2["id"])
    # file at the grace deadline exactly (2030-07-01) — within grace (inclusive)
    th.set_clock("2030-07-01T00:00:00Z")
    rnw = validate_success(
        api.create_renewal(
            create_renewal_payload(notary["id"], current["version"], bond2["id"]), CA
        ),
        201,
    )
    assert rnw["filed_within_grace"] is True
    approved = validate_success(api.approve_renewal(rnw["id"], CA))
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Corner: OCC on renewal create
# ===========================================================================
def test_renewal_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "When a renewal is submitted, the request must carry
    `expected_notary_version`, which is the `version` of the target `Notary` that
    the client last observed. The server compares this value against the notary's
    current `version`."
    PRD §3.10: "Submitting a renewal increments the notary's `version` by one,
    which is precisely why a second, stale submission will fail the version check."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_renewal_succeeds_and_bumps_version
    """
    th.set_clock("2026-06-01T00:00:00Z")
    jx = th.create_jurisdiction(state_code="TX")
    notary = th.register_notary(jx["id"], email="occ2@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    validate_success(api.commission_notary(notary["id"], CA))
    validate_success(api.activate_notary(notary["id"], CA))
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:01Z", coverage_end_at="2034-06-01T00:00:00Z")
    th.activate_bond(bond2["id"])
    current = validate_success(api.get_notary(notary["id"], CA))
    vcur = current["version"]
    rnw = validate_success(
        api.create_renewal(create_renewal_payload(notary["id"], vcur, bond2["id"]), CA), 201
    )
    assert rnw["status"] == "SUBMITTED"
    refreshed = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed["version"] == vcur + 1


def test_renewal_with_stale_version_returns_stale_version(api):
    """PRD §2.7: "If they do not match — meaning another writer has advanced the
    notary since the client read it — the submission is rejected with
    `ERR_STALE_VERSION` and HTTP status 412."
    PRD §3.10: "Submitting a renewal increments the notary's `version` by one,
    which is precisely why a second, stale submission will fail the version check."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_notary_version_on_renewal_returns_412
    """
    th.set_clock("2026-06-01T00:00:00Z")
    jx = th.create_jurisdiction(state_code="TX")
    notary = th.register_notary(jx["id"], email="occ@x.com")
    bond1 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2026-06-01T00:00:00Z", coverage_end_at="2030-06-01T00:00:00Z")
    th.activate_bond(bond1["id"])
    validate_success(api.commission_notary(notary["id"], CA))
    validate_success(api.activate_notary(notary["id"], CA))
    v0 = validate_success(api.get_notary(notary["id"], CA))["version"]
    bond2 = th.create_bond(notary["id"], jx["id"],
                          coverage_start_at="2030-06-01T00:00:01Z", coverage_end_at="2034-06-01T00:00:00Z")
    th.activate_bond(bond2["id"])
    # first renewal supersedes the notary (version advances)
    validate_success(api.create_renewal(create_renewal_payload(notary["id"], v0, bond2["id"]), CA), 201)
    # second renewal carries the now-stale pre-advance version
    resp = api.create_renewal(create_renewal_payload(notary["id"], v0, bond2["id"]), CA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ===========================================================================
# priority_pair_validation_conflict: state beats referential on begin-identity
# ===========================================================================
def test_begin_identity_wrong_state_beats_enotary_gate(api):
    """PRD §2.9: "State validity is checked fifth: a resource that is not in a legal
    state for the requested transition yields `ERR_INVALID_STATE` (409). Only once
    all of these pass does the system evaluate the domain-specific business rules —
    ... e-notary authorization"
    PRD §3.5: "This step requires the session to be `SCHEDULED` (else
    `ERR_INVALID_STATE`), the presiding notary's `enotary_authorized` to be `true`
    (else `ERR_ENOTARY_NOT_AUTHORIZED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_begin_identity
    """
    ctx = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "npp1@x.com"})
    notary = ctx["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-06-16T09:00:00Z", "2026-06-16T10:00:00Z")
    th.add_signer(sess["id"], notary["id"])
    # drive session to IDENTITY_PENDING, then suspend the notary (enotary drops to false)
    validate_success(api.begin_identity(sess["id"], hdr))
    validate_success(api.suspend_notary(notary["id"], CA))
    # second begin-identity violates BOTH state (not SCHEDULED) and referential (not authorized)
    resp = api.begin_identity(sess["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_begin_identity_after_suspend_session_already_terminated(api):
    """PRD §3.9: "Suspension sets `enotary_authorized` to `false` and winds down the
    notary's live RON work: every session of that notary in `SCHEDULED`,
    `IDENTITY_PENDING`, `ID_VERIFIED`, or `ACTIVE` status is cascaded to
    `TERMINATED`"
    PRD §3.5: "This step requires the session to be `SCHEDULED` (else
    `ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_begin_identity
    """
    ctx = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "npp1b@x.com"})
    notary = ctx["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-06-16T11:00:00Z", "2026-06-16T12:00:00Z")
    th.add_signer(sess["id"], notary["id"])
    validate_success(api.begin_identity(sess["id"], hdr))
    validate_success(api.suspend_notary(notary["id"], CA))
    # the suspension cascade terminated the session; it is no longer SCHEDULED
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "TERMINATED"
    resp = api.begin_identity(sess["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
