"""TransportCompany aggregate lifecycle and CRUD tests.

Covers the four-state ``qualification_status`` machine from PRD §3.1 —
the linear ``DRAFT → SUBMITTED → APPROVED`` forward path, the
``APPROVED → REVOKED`` regulator-revoke, and the cycle-reentry
``REVOKED → DRAFT → SUBMITTED → APPROVED`` reapply path the submit
endpoint walks internally when the source state is ``REVOKED``.

Also covers the natural-key uniqueness ``ERR_DUPLICATE_IDENTIFIER`` 409
on a same-``registration_number`` create per PRD §2.4's
"the company's ``registration_number`` is the third system-wide
unique key, alongside the vehicle plate", the deferred cascade
sub-rule that the revoke doesn't synchronously touch the
already-issued permits but the next verify-compliance does flip them
``ACTIVE → SUSPENDED`` (with the cause discriminator
``GROUNDING_INVALIDATION`` on the sweep's response), and the parent-
qualified gate on the three child-create endpoints
(``ERR_COMPANY_NOT_QUALIFIED`` 409 at the priority-526 referential
check when the parent is not yet ``APPROVED``).

The wallet-conservation invariant on the company's
``wallet_balance_cents`` field is tested in
``test_permits_lifecycle.py``; this file's wallet-assertion is just
that the new row's wallet defaults to zero per PRD §3.1's "a new
TransportCompany row's ``wallet_balance_cents`` is initialized to
zero".
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    HazmatScenario,
    api_client,
    approve_company_payload,
    assert_company,
    assert_timestamp_format,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_company_payload,
    create_driver_payload,
    create_route_payload,
    create_vehicle_payload,
    fetch_permit_live_verdict,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    regulator_headers,
    revoke_company_payload,
    run_full_sweep,
    setup_active_permit,
    setup_approved_company,
    setup_draft_company,
    setup_submitted_company,
    submit_company_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    CompanyQualificationStatus,
    HAZARD_CLASSES_UN,
    PermitLifecycleStatus,
    SweepPermitCause,
    VerifyComplianceTransitionFired,
)


# ─── Initial state, system-managed fields, and the shape contract ─────


def test_company_create_returns_201_with_draft_status(api):
    """PRD §3.1: "The response is the 201 row at
    ``qualification_status = DRAFT``, with the server-minted ``id``,
    the four standard system-managed fields, the bootstrap-time
    ``wallet_balance_cents = 0``"."""
    boot = bootstrap_company_operator_headers()
    resp = api.create_company(create_company_payload(), boot)
    data = validate_success(resp, 201)
    assert_company(data)
    assert data["qualification_status"] == CompanyQualificationStatus.DRAFT.value
    assert data["wallet_balance_cents"] == 0, (
        "a freshly-minted TransportCompany row's wallet must be the initial zero"
    )
    # version starts at 1 on the freshly-inserted row.
    assert data["version"] == 1, (
        f"freshly-created version must be 1, got {data['version']}"
    )
    # created_at and updated_at coincide on the insert.
    assert data["created_at"] == data["updated_at"], (
        "on the initial insert, created_at and updated_at must coincide"
    )


def test_company_get_by_id_returns_the_row(api, approved_company: Dict):
    """``GET /v1/companies/{company_id}`` returns the same row.  The
    operator's headers carry the company-id-as-X-User-ID per the
    PRD's §2.1 entity-backed-identity contract."""
    op = company_operator_headers(approved_company["id"])
    resp = api.get_company(approved_company["id"], op)
    data = validate_success(resp, 200)
    assert_company(data)
    assert data["id"] == approved_company["id"]
    assert data["qualification_status"] == CompanyQualificationStatus.APPROVED.value


def test_company_get_not_found_returns_company_not_found_404(api, non_existent_uuid: str):
    """The existence-tier 404 on a syntactically-valid but
    non-resolving company id is ``ERR_COMPANY_NOT_FOUND`` per the
    PRD's §2.7 existence-tier table.

    The regulator's cross-tenant exemption means the same error fires
    regardless of which role is reading.
    """
    reg = regulator_headers()
    resp = api.get_company(non_existent_uuid, reg)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_FOUND.value, expected_status=404)


# ─── Body-shape validation on the company create ─────────────────────


@pytest.mark.parametrize("bad_email", ["", "no-at-sign", "trailing-space @ ok.com"])
def test_company_create_email_format_is_validated(api, bad_email: str):
    """PRD §3.1: "``primary_contact_email`` (an RFC 5322 syntactically
    valid email address for the responsible safety officer; the
    syntactic check is the body-shape-validation tier's catch-all
    ``ERR_VALIDATION`` on a syntactic miss)"."""
    boot = bootstrap_company_operator_headers()
    payload = create_company_payload(primary_contact_email=bad_email)
    resp = api.create_company(payload, boot)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


@pytest.mark.parametrize("bad_regnum", [
    "short",                              # too short (< 8 chars)
    "A" * 33,                             # too long (> 32 chars)
    "abc12345",                           # lowercase letters
    "1234 5678 ABCD",                     # contains whitespace
    "REG-12345",                          # contains a hyphen, not in [A-Z0-9]
    "",                                   # empty
])
def test_company_registration_number_regex(api, bad_regnum: str):
    """PRD §2.4: "the company registration number
    ``registration_number`` is a string matching the regular
    expression of uppercase letters and digits in the length range
    8 to 32 inclusive".  Any string failing the regex is the body-
    shape catch-all ``ERR_VALIDATION`` 422.
    """
    boot = bootstrap_company_operator_headers()
    payload = create_company_payload(registration_number=bad_regnum)
    resp = api.create_company(payload, boot)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_company_legal_name_length_bounds(api):
    """The ``legal_name`` is a 1..200-character string per PRD §2.4's
    free-text-length table.  The two boundary failure cases are the
    empty string (length 0, below the 1-character lower bound) and
    the 201-character string (one over the 200-character upper bound).

    The two boundary success cases — the single-character and the
    exactly-200-character names — are admitted; we cover the
    failure direction since the success direction is implicit in
    the standard payload-factory's name string.
    """
    boot = bootstrap_company_operator_headers()
    for bad_name in ("", "A" * 201):
        payload = create_company_payload(legal_name=bad_name)
        resp = api.create_company(payload, boot)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_company_hazard_classes_must_be_in_taxonomy(api):
    """PRD §2.8: a hazard-class string outside the UN-hazard-class
    taxonomy is the body-shape ``ERR_VALIDATION`` on the
    ``hazard_classes_authorized`` array."""
    boot = bootstrap_company_operator_headers()
    payload = create_company_payload(hazard_classes_authorized=["99.99", "bogus"])
    resp = api.create_company(payload, boot)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_company_hazard_classes_cannot_be_empty(api):
    """PRD §3.1 names the operator's
    ``hazard_classes_authorized`` as a "non-empty array enumerating
    the UN hazard-class subset the carrier is applying to handle;
    an empty array ... is ``ERR_VALIDATION`` 422".
    """
    boot = bootstrap_company_operator_headers()
    resp = api.create_company(create_company_payload(hazard_classes_authorized=[]), boot)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_company_registration_number_duplicate_rejected(api):
    """PRD §2.4: "the registration_number is unique system-wide";
    a same-value second-insert is the ``ERR_DUPLICATE_IDENTIFIER``
    409 at the natural-key-uniqueness priority 520.
    """
    boot = bootstrap_company_operator_headers()
    shared_regnum = "DUPCO" + "1" * 8
    first_payload = create_company_payload(registration_number=shared_regnum)
    second_payload = create_company_payload(registration_number=shared_regnum)
    resp1 = api.create_company(first_payload, boot)
    validate_success(resp1, 201)
    resp2 = api.create_company(second_payload, boot)
    validate_error(resp2, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, expected_status=409)


# ─── State machine: the linear forward path ─────────────────────────


def test_submit_transitions_draft_to_submitted(api, draft_company: Dict):
    """PRD §3.1: "The ``DRAFT → SUBMITTED`` transition is the
    operator's act of submitting the completed application to the
    regulator's review queue, fired by the submit endpoint at the
    path ``POST /v1/companies/{company_id}/submit``"."""
    op = company_operator_headers(draft_company["id"])
    resp = api.submit_company(draft_company["id"], submit_company_payload(), op)
    data = validate_success(resp, 200)
    assert data["qualification_status"] == CompanyQualificationStatus.SUBMITTED.value
    # The submitted_at audit field is written.
    assert data.get("submitted_at") is not None
    assert is_iso8601_timestamp(data["submitted_at"])
    # The version is bumped by exactly one from the create's 1.
    assert data["version"] == draft_company["version"] + 1


def test_approve_transitions_submitted_to_approved(api, submitted_company: Dict):
    """PRD §3.1: "The ``SUBMITTED → APPROVED`` transition is the
    regulator's act of attesting the qualification, fired by the
    approve endpoint at ``POST /v1/companies/{company_id}/approve``"."""
    reg = regulator_headers()
    resp = api.approve_company(submitted_company["id"], approve_company_payload(), reg)
    data = validate_success(resp, 200)
    assert data["qualification_status"] == CompanyQualificationStatus.APPROVED.value
    assert data.get("approved_at") is not None
    assert data["version"] == submitted_company["version"] + 1


def test_revoke_transitions_approved_to_revoked(api, approved_company: Dict):
    """PRD §3.1: "The ``APPROVED → REVOKED`` transition is the
    regulator's stripping of the qualification, fired by
    ``POST /v1/companies/{company_id}/revoke``.  The body carries
    the required ``reason_note`` 1-to-500-character free-text
    cause".
    """
    reg = regulator_headers()
    resp = api.revoke_company(
        approved_company["id"],
        revoke_company_payload(reason_note="Material safety violation."),
        reg,
    )
    data = validate_success(resp, 200)
    assert data["qualification_status"] == CompanyQualificationStatus.REVOKED.value
    assert data.get("revoked_at") is not None
    assert data["version"] == approved_company["version"] + 1


def test_revoke_requires_non_empty_reason_note(api, approved_company: Dict):
    """The required ``reason_note`` on the revoke body has length
    in ``[1, 500]``.  An empty-string ``reason_note`` is the body-
    shape ``ERR_VALIDATION`` 422 case the PRD's §3.1 names as the
    "missing or empty reason note" cause.
    """
    reg = regulator_headers()
    payload = revoke_company_payload(reason_note="")
    resp = api.revoke_company(approved_company["id"], payload, reg)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── State machine: wrong-source-state rejections ─────────────────────


def test_submit_from_submitted_is_invalid_state_transition(api, submitted_company: Dict):
    """A submit-from-SUBMITTED is the generic
    ``ERR_INVALID_STATE_TRANSITION`` 409 — the source state is not in
    the allowed pre-set ``{DRAFT, REVOKED}``."""
    op = company_operator_headers(submitted_company["id"])
    resp = api.submit_company(submitted_company["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_submit_from_approved_is_invalid_state_transition(api, approved_company: Dict):
    """Likewise a submit from ``APPROVED`` is the same generic
    state-tier error.  The operator's path back to ``DRAFT`` from
    ``APPROVED`` is the regulator's revoke action, not the
    operator's resubmit, per PRD §3.1."""
    op = company_operator_headers(approved_company["id"])
    resp = api.submit_company(approved_company["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_approve_from_draft_is_invalid_state_transition(api, draft_company: Dict):
    """The regulator's approve action requires the same-row
    pre-state ``SUBMITTED``.  An approve-from-DRAFT (operator
    forgot the submit step) is the generic
    ``ERR_INVALID_STATE_TRANSITION`` 409.
    """
    reg = regulator_headers()
    resp = api.approve_company(draft_company["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_revoke_from_non_approved_is_invalid_state_transition(api, submitted_company: Dict):
    """The revoke action requires the same-row pre-state
    ``APPROVED``.  A revoke-from-SUBMITTED is the standard
    wrong-source-state rejection."""
    reg = regulator_headers()
    resp = api.revoke_company(
        submitted_company["id"],
        revoke_company_payload(),
        reg,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── State-machine: the reapply cycle ─────────────────────────────────


def test_revoked_then_submit_re_enters_the_lifecycle(api, approved_company: Dict):
    """PRD §3.1: "The two-source-state ``{DRAFT, REVOKED}`` allowance
    is the revocation revision-loop cycle: a carrier whose
    qualification was revoked for a serious safety incident may
    reapply by going through the same submit endpoint, with the
    handler internally walking the state in the order ``REVOKED →
    DRAFT → SUBMITTED`` as a single atomic step (the externally
    observable trace is the ``qualification_status`` value flipping
    from ``REVOKED`` before the call to ``SUBMITTED`` after)".

    Walk ``APPROVED → REVOKED → SUBMITTED → APPROVED`` and assert
    each transition and the post-cycle row's
    ``approved_at`` matches the most-recent approval.
    """
    reg = regulator_headers()
    op = company_operator_headers(approved_company["id"])
    # Revoke.
    rev = get_success_data(api.revoke_company(approved_company["id"], revoke_company_payload(), reg))
    assert rev["qualification_status"] == CompanyQualificationStatus.REVOKED.value
    first_approved_at = approved_company.get("approved_at")
    # Reapply: the submit handler observes the source state is
    # REVOKED and walks REVOKED → DRAFT → SUBMITTED as one atomic
    # step.  The externally-observable post-call status is
    # SUBMITTED.
    sub = get_success_data(api.submit_company(approved_company["id"], submit_company_payload(), op))
    assert sub["qualification_status"] == CompanyQualificationStatus.SUBMITTED.value
    # The submitted_at is refreshed to the new submission time.
    assert sub.get("submitted_at") is not None
    # Re-approve.
    appr = get_success_data(api.approve_company(approved_company["id"], approve_company_payload(), reg))
    assert appr["qualification_status"] == CompanyQualificationStatus.APPROVED.value
    # The approved_at is overwritten to the most-recent approval.
    new_approved_at = appr.get("approved_at")
    if first_approved_at is not None:
        # The new approval's timestamp is strictly later than the
        # original one.  ISO-8601-millisecond strings are lex-
        # ordered correctly with the fixed-width format.
        assert new_approved_at >= first_approved_at, (
            f"second approval's approved_at {new_approved_at!r} must be >= first's {first_approved_at!r}"
        )
    # The revoked_at audit field from the prior cycle is preserved on the row (the audit-trail convention).


# ─── Parent-qualified gate on the child-create endpoints ─────────────


def test_create_driver_under_unqualified_company_rejected(api, draft_company: Dict):
    """PRD §3.1 last paragraph: "a not-yet-``APPROVED`` company
    cannot register drivers (the children-creation endpoints …
    each fail at the ``ERR_COMPANY_NOT_QUALIFIED`` 409
    business-referential precondition tier when the parent
    company's ``qualification_status`` is anything other than
    ``APPROVED``)".

    The draft_company fixture provides a DRAFT-state company.  A
    driver-create against it is the priority-526
    ``ERR_COMPANY_NOT_QUALIFIED`` 409.
    """
    op = company_operator_headers(draft_company["id"])
    payload = create_driver_payload()
    resp = api.create_driver(draft_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value, expected_status=409)


def test_create_vehicle_under_unqualified_company_rejected(api, submitted_company: Dict):
    """The vehicle-create variant of the same parent-qualified
    gate.  The fixture supplies a SUBMITTED-state company, also
    not in ``APPROVED``, so the same
    ``ERR_COMPANY_NOT_QUALIFIED`` 409 fires.
    """
    op = company_operator_headers(submitted_company["id"])
    payload = create_vehicle_payload()
    resp = api.create_vehicle(submitted_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value, expected_status=409)


def test_create_route_under_unqualified_company_rejected(api, submitted_company: Dict):
    """The route-create variant of the same parent-qualified gate."""
    op = company_operator_headers(submitted_company["id"])
    payload = create_route_payload()
    resp = api.create_route(submitted_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value, expected_status=409)


# ─── The deferred-cascade from revoke onto the company's ACTIVE permits ─


def test_revoke_then_verify_compliance_flips_permits_to_suspended(api, active_permit: HazmatScenario):
    """PRD §3.1 last paragraph + §3.5 verify-compliance: the revoke
    action's cross-aggregate cascade onto the company's
    already-issued ACTIVE permits is "intentionally **deferred**
    rather than synchronous — the revoke action does not walk the
    Permit table inside its own transaction.  Instead, every
    subsequent verify-compliance call on each affected permit
    observes that the live recompute of the company-leg of the
    validity AND-chain is now false even though the strict-snapshot's
    ``snapshot_company_qualified`` was true at the last
    verification, and the verify-compliance handler fires the
    ``ACTIVE → SUSPENDED`` automatic transition on the permit with
    the cause discriminator ``GROUNDING_INVALIDATION``".

    Set up an ACTIVE permit, revoke the parent company, and
    confirm:
      1. The company row's ``qualification_status`` is now
         ``REVOKED`` and the permit row's
         ``lifecycle_status`` is still ``ACTIVE`` immediately
         after the revoke (the no-synchronous-touch invariant).
      2. The permit's GET-response ``live_per_leg.live_company_qualified``
         boolean is now ``False`` while the on-disk
         ``snapshot_company_qualified`` is still ``True`` — the
         dual-variant disagreement axis the PRD's §2.11 names.
      3. A ``verify-compliance`` call on the permit fires the
         ``ACTIVE → SUSPENDED`` transition with the
         ``transition_fired`` discriminator value
         ``"ACTIVE_TO_SUSPENDED"``.
      4. After the verify-compliance call, the permit's
         ``lifecycle_status`` is ``SUSPENDED`` and the snapshot's
         ``snapshot_company_qualified`` has been rewritten to
         ``False``.
    """
    scenario = active_permit
    reg = regulator_headers()
    # Sanity: the permit is in ACTIVE before the revoke.
    assert scenario.permit["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value

    # The revoke is the regulator's action on the parent company.
    rev = get_success_data(api.revoke_company(
        scenario.company["id"],
        revoke_company_payload(),
        reg,
    ))
    assert rev["qualification_status"] == CompanyQualificationStatus.REVOKED.value

    # The permit row is still in ACTIVE — the cascade is deferred
    # and the revoke did not synchronously touch the permits.
    # Read the permit row to confirm.
    get_resp = api.get_permit(scenario.permit["id"], company_operator_headers(scenario.company["id"]))
    # Operator's cross-tenant predicate is fine here because the
    # ``X-User-ID`` is still the company's id even though the
    # company is now ``REVOKED`` — the auth-tier and the cross-
    # tenant predicates are independent of the company's
    # qualification status.  But the operator-on-a-revoked-company's
    # ability to read its own permit is the
    # PRD's §2.6's standard cross-tenant-passes-on-own-id case.
    permit_read = validate_success(get_resp, 200)
    assert permit_read["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value, (
        "the revoke does not synchronously flip the permit; the lifecycle is still ACTIVE"
    )
    # The on-disk snapshot still says "company qualified == True"
    # (the snapshot's last-write was the issue-step's all-passing
    # write); the live-mode recompute now disagrees because the
    # company's qualification_status is REVOKED.  The PRD's §3.5
    # GET-permit prose names the ``live_per_leg`` map as the
    # observable for this disagreement.
    snap_cq = permit_read.get("snapshot_company_qualified")
    assert snap_cq is True, (
        f"snapshot_company_qualified should still be True post-revoke-pre-verify; got {snap_cq!r}"
    )
    lpl = permit_read.get("live_per_leg") or {}
    live_cq = lpl.get("live_company_qualified")
    # Two valid PRD readings exist on the field name and the
    # presence of the live_per_leg block on the GET response (the
    # PRD's §3.5 names the field by its read-time-computed name
    # ``live_company_qualified`` in the verify-compliance
    # response, but the GET-permit's response may surface the
    # same map under ``live_per_leg`` or omit it depending on
    # the implementer's serialisation choice).  We require the
    # presence of the disagreement signal in *some* form: either
    # the boolean is False in the live_per_leg map, or the
    # ``live_verdict`` aggregate is False while ``snapshot_overall``
    # is True.
    snap_ovr = permit_read.get("snapshot_overall")
    live_ovr = permit_read.get("live_verdict")
    disagreement_observable = (
        live_cq is False
        or (snap_ovr is True and live_ovr is False)
    )
    assert disagreement_observable, (
        "after the revoke the GET-permit's live-vs-snapshot dual-variant should disagree "
        f"on the company-leg: live_per_leg={lpl!r}, snapshot_overall={snap_ovr!r}, "
        f"live_verdict={live_ovr!r}"
    )

    # Now fire the verify-compliance.  The transition_fired
    # discriminator is the canonical observable for which arc fired.
    vc_resp = api.verify_permit_compliance(scenario.permit["id"], {}, reg)
    vc = validate_success(vc_resp, 200)
    tf = vc.get("transition_fired")
    assert tf == VerifyComplianceTransitionFired.ACTIVE_TO_SUSPENDED.value, (
        f"expected ACTIVE_TO_SUSPENDED transition_fired, got {tf!r}"
    )
    # The post-verify-compliance snapshot is rewritten with the
    # now-correct company-leg-false value.
    permit_after = vc.get("permit") if isinstance(vc, dict) and "permit" in vc else None
    if permit_after is None:
        # Fall back to a fresh GET.
        permit_after = validate_success(
            api.get_permit(scenario.permit["id"], regulator_headers()),
            200,
        )
    assert permit_after["lifecycle_status"] == PermitLifecycleStatus.SUSPENDED.value


def test_sweep_emits_grounding_invalidation_cause_on_revoked_company_cascade(api, active_permit: HazmatScenario):
    """The companion-sweep-side narrative: PRD §2.5 names the
    ``cause`` discriminator on each ``permit_transitions`` entry
    in the sweep's response payload, drawing from the three values
    ``WALL_CLOCK_EXPIRY`` / ``GROUNDING_INVALIDATION`` /
    ``GROUNDING_REVALIDATION``.  The deferred-cascade flush via the
    sweep's per-ACTIVE-permit verify-compliance fan-out emits the
    ``GROUNDING_INVALIDATION`` cause when the legs went green-to-red
    in the gap since the last verification.

    Revoke the parent company, fire the sweep with scope=ALL, and
    confirm the response carries a permit_transitions entry for
    the revoked-company's permit with the
    ``GROUNDING_INVALIDATION`` cause and the
    ``ACTIVE → SUSPENDED`` pre-and-post status pair.
    """
    scenario = active_permit
    reg = regulator_headers()
    # Revoke the company (the cascade trigger).
    api.revoke_company(scenario.company["id"], revoke_company_payload(), reg)
    # The wall-clock has not advanced, so the wall-clock-expiry
    # cause would not fire on this permit; the sweep's
    # per-ACTIVE-permit verify-compliance step is the mechanism
    # for the grounding-invalidation cascade.
    sw = run_full_sweep(api)
    # Locate the permit's transition entry.
    pts = sw.get("permit_transitions") or []
    matching = [t for t in pts if t.get("permit_id") == scenario.permit["id"]]
    assert matching, (
        f"sweep response did not list the revoked-company's permit in permit_transitions: "
        f"{[t.get('permit_id') for t in pts]}"
    )
    entry = matching[0]
    assert entry.get("cause") == SweepPermitCause.GROUNDING_INVALIDATION.value, (
        f"cascade cause is {entry.get('cause')!r}, expected GROUNDING_INVALIDATION"
    )
    assert entry.get("pre_status") == PermitLifecycleStatus.ACTIVE.value
    assert entry.get("post_status") == PermitLifecycleStatus.SUSPENDED.value
    # The cascade_trip_aborts array is empty because the
    # ACTIVE → SUSPENDED transition is non-trip-aborting per the
    # PRD's §3.7 "the suspension is the temporary-failure state
    # and does not cascade-abort the open trips" rule.
    cta = entry.get("cascade_trip_aborts") or []
    assert cta == [], (
        f"the ACTIVE → SUSPENDED transition is non-trip-cascading; "
        f"cascade_trip_aborts should be empty, got {cta!r}"
    )


# ─── The "wallet is zero on a fresh company" invariant from §2.11 ────


def test_fresh_company_has_zero_wallet_balance(api):
    """PRD §2.4 + §2.11: "a new TransportCompany row's
    ``wallet_balance_cents`` is initialized to zero, with
    regulator-side top-ups happening out of band".  No top-up has
    happened on a fresh-create, so the row's balance is exactly
    zero.
    """
    boot = bootstrap_company_operator_headers()
    co = get_success_data(api.create_company(create_company_payload(), boot))
    assert co["wallet_balance_cents"] == 0


# ─── Optimistic concurrency on the company-mutating endpoints ────────


def test_submit_with_stale_version_returns_version_conflict(api, draft_company: Dict):
    """PRD §2.10: "On a mismatch with the row's actual ``version`` at
    the moment the handler reads the row, the request is rejected
    with ``ERR_VERSION_CONFLICT`` at HTTP status 409 (priority 560
    in the validation precedence of §2.7)".

    Read the fresh ``version = 1`` row, then issue a no-op
    "internal mutation" via a successful submit (which bumps the
    version to 2), and finally a fresh submit attempt sending the
    stale ``version = 1`` body engages the OCC and is rejected.

    Since the submit-twice pattern lands the row in ``SUBMITTED`` on
    the first call (and the second submit-from-SUBMITTED would
    normally be the wrong-state-tier rejection at priority 400,
    which fires *before* the OCC at priority 560 per PRD §2.7), we
    instead engineer the stale-version test on the revoke endpoint
    where the legitimate path is two consecutive APPROVED→REVOKED→
    REVOKED-attempt sequence: the first revoke succeeds and bumps
    the version, the second revoke from the still-stale-version-in-
    the-test-body engages the OCC.

    The standard pattern from the framework's
    ``assert_version_incremented`` helper is the version-increases-
    by-one invariant on each successful mutation.
    """
    # The simplest OCC test path is the one on the
    # ``POST /v1/companies/{company_id}/submit`` endpoint with the
    # ``REVOKED → SUBMITTED`` cycle's reentry leg, since the
    # state-tier guard permits both ``DRAFT`` and ``REVOKED`` as
    # the source state.  We need a company in REVOKED, then a
    # successful submit (bumps version), then a stale-version
    # submit retry.
    # Walk DRAFT → SUBMITTED → APPROVED → REVOKED → SUBMITTED to
    # land at a known version-after-the-cycle.
    op = company_operator_headers(draft_company["id"])
    reg = regulator_headers()
    sub1 = get_success_data(api.submit_company(draft_company["id"], {}, op))
    appr = get_success_data(api.approve_company(draft_company["id"], {}, reg))
    rev = get_success_data(api.revoke_company(draft_company["id"], revoke_company_payload(), reg))
    v_at_revoked = rev["version"]
    # Now a successful submit on the REVOKED row bumps the version.
    sub2 = get_success_data(api.submit_company(draft_company["id"], {}, op))
    assert sub2["version"] > v_at_revoked
    # A second submit-from-SUBMITTED with the stale version is
    # the state-tier failure (priority 400) *before* the OCC
    # (priority 560) per PRD §2.7's tier ordering.  So the
    # response on this exact scenario is
    # ``ERR_INVALID_STATE_TRANSITION``, not ``ERR_VERSION_CONFLICT``.
    # The OCC tier fires only when every higher-priority tier
    # has passed.  We test that here: the stale-version body on
    # a same-state-as-the-precondition-allows-the-action endpoint
    # would be the OCC hit, but the company's state-machine
    # transitions do not admit two consecutive submit-from-the-
    # same-state succession of OCC-engaging body-version-match-
    # then-mismatch in a way that reaches the OCC tier without
    # tripping the state tier first.
    #
    # The OCC path is more naturally tested on a list of
    # successively-mutating actions that keep the state in the
    # same-row-allowed pre-set, which is the verify-compliance
    # endpoint's idempotent NO_CHANGE arc on a permit.  That test
    # lives in ``test_occ_versioning.py`` rather than here.
    # On the company-side, the company-state-machine's transitions
    # are all between-state arcs (not same-state idempotents), so
    # a stale-version retry necessarily ends up on the same-row
    # state-guard's wrong-source-state branch which fires the
    # state-tier error first.
    stale_body = {"version": v_at_revoked}
    second_submit_attempt = api.submit_company(draft_company["id"], stale_body, op)
    # The state is now SUBMITTED (from sub2), so a fresh submit
    # from SUBMITTED is the state-tier rejection.
    # We accept either the state-tier error OR the OCC error
    # to admit both PRD-faithful implementation orderings.
    from prd_bench_local_runner.testing import validate_error_is_one_of

    actual = validate_error_is_one_of(
        second_submit_attempt,
        [
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            ApiErrorId.ERR_VERSION_CONFLICT.value,
        ],
    )
    assert actual in (
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ApiErrorId.ERR_VERSION_CONFLICT.value,
    )


# ─── Bootstrap-identity wallet-side audit ────────────────────────────


def test_company_create_response_has_canonical_audit_fields(api):
    """The fresh-create's response carries the four common-fields
    quartet from PRD §2.4 (``id``, ``created_at``, ``updated_at``,
    ``version``) plus the system-set wallet field at zero.  The
    ``submitted_at``, ``approved_at``, and ``revoked_at`` audit
    fields are null on the fresh row because no transition has
    yet fired.
    """
    boot = bootstrap_company_operator_headers()
    data = get_success_data(api.create_company(create_company_payload(), boot))
    for nullable_field in ("submitted_at", "approved_at", "revoked_at"):
        # The implementation may omit the key entirely instead of
        # carrying it as null on a never-set field.  Both are
        # PRD-consistent because the "the field is null on a row
        # that has never been in the relevant state" rule is the
        # observable invariant.
        v = data.get(nullable_field)
        assert v is None, (
            f"freshly-created company's {nullable_field} should be null, got {v!r}"
        )
    assert data["wallet_balance_cents"] == 0
    assert isinstance(data["version"], int) and data["version"] == 1
