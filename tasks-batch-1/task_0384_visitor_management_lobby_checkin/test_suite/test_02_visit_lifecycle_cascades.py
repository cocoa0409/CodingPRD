"""Cross-entity cascades and dependencies across the visit/contractor/agreement
lifecycle.

Difficulty queue (A): transitive_cascade, cross_entity_state_dependency,
non_linear_state_machine (contractor cyclic).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId,
    setup_site_floor_host, setup_site_host,
    create_visit, screen_visit, create_watchlist_entry, create_agreement,
    create_contractor_pass, create_cleared_visit, get_floor_version,
    setup_contractor_covered_cleared_visit, set_clock,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_screen_deny_cascades_pending_agreement_to_void(api):
    """PRD 3.4: "On a DENY decision it auto-advances `SCREENING` to `DENIED`, a
    terminal state in which no badge is ever printed, and every `PENDING` agreement
    on the visit is cascaded to `VOID`."
    PRD 2.5: "When a visit is denied — whether automatically at screening or by a
    security officer's adjudication — every agreement attached to that visit that is
    still in `PENDING` status is cascaded to `VOID`; this is a two-level cascade from
    the visit down to its agreements."

    Depth-3: screen -> SCREENING -> DENIED -> agreement VOID.

    Design: Difficulty/transitive_cascade/tc_screen_deny_voids_agreement_depth3
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    agreement = create_agreement(visit["id"], document_kind="NDA", document_version="NDA-v3")
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "DENIED", f"expected DENIED, got {screened['status']}"

    fetched_agreement = validate_success(api.get_agreement(agreement["id"], SO))
    assert fetched_agreement["status"] == "VOID", (
        f"expected agreement VOID, got {fetched_agreement['status']}"
    )


def test_first_signin_of_covered_visit_bumps_contractor_count(api):
    """PRD 3.6: "if the visit is contractor-covered and this is the first time it has
    ever reached `SIGNED_IN`, the sponsoring contractor pass's `covered_visit_count`
    increases by one — a cross-aggregate cascade that fires once per covered visit,
    not on any later re-entry."

    First sign-in moves covered_visit_count 0 -> 1.

    Design: Difficulty/transitive_cascade/tc_signin_bumps_contractor_covered_count_depth2
    """
    site, floor, host, pass_, visit = setup_contractor_covered_cleared_visit()
    fv = get_floor_version(floor["id"])
    signed_in = validate_success(
        api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    )
    assert signed_in["status"] == "SIGNED_IN", f"expected SIGNED_IN, got {signed_in['status']}"

    fetched_pass = validate_success(api.get_contractor_pass(pass_["id"], SO))
    assert fetched_pass["covered_visit_count"] == 1, (
        f"expected covered_visit_count 1, got {fetched_pass['covered_visit_count']}"
    )


def test_contractor_pass_cyclic_active_suspended_active(api):
    """PRD 3.7: "An `ACTIVE` pass may be suspended, moving `ACTIVE → SUSPENDED`,
    after which covered visits can no longer sign in until the pass is reactivated; a
    `SUSPENDED` pass may be reactivated, moving `SUSPENDED → ACTIVE` and restoring
    coverage."

    ACTIVE -> SUSPENDED -> ACTIVE returns the pass to a state it already occupied.

    Design: Difficulty/non_linear_state_machine/nlsm_contractorpass_cyclic_active_suspended
    """
    site, host = setup_site_host()
    pass_ = create_contractor_pass(host["id"])
    get_success_data(api.suspend_contractor_pass(pass_["id"], SO))
    reactivated = validate_success(api.reactivate_contractor_pass(pass_["id"], SO))
    assert reactivated["status"] == "ACTIVE", (
        f"expected ACTIVE after reactivate, got {reactivated['status']}"
    )


def test_signin_blocked_when_contractor_pass_suspended(api):
    """PRD 3.6: "if the visit carries a `contractor_pass_id`, the referenced pass must
    be in `ACTIVE` status, or the request is rejected with `ERR_PASS_NOT_ACTIVE`".
    PRD 3.7: "after which covered visits can no longer sign in until the pass is
    reactivated".

    Entity pair Visit->ContractorPass: a CLEARED covered visit on a SUSPENDED pass
    cannot sign in.

    Design: Difficulty/cross_entity_state_dependency/cesd_signin_requires_active_contractor_pass
    """
    site, floor, host, pass_, visit = setup_contractor_covered_cleared_visit()
    get_success_data(api.suspend_contractor_pass(pass_["id"], SO))
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    validate_error(res, ApiErrorId.ERR_PASS_NOT_ACTIVE)

    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_agreement_sign_blocked_when_visit_denied(api):
    """PRD 3.5: "Once the parent visit has reached `DENIED`, `SIGNED_IN`, or
    `SIGNED_OUT`, the agreement can no longer be signed, and the attempt is rejected
    with `ERR_VISIT_NOT_SIGNABLE` (HTTP 409)."
    PRD 3.5: "Separately, an agreement reaches the terminal `VOID` state only by
    system cascade, when its parent visit transitions to `DENIED`."

    Entity pair Agreement->Visit: the PENDING agreement is voided when the visit is
    denied at screening, and signing it then returns ERR_VISIT_NOT_SIGNABLE.

    Design: Difficulty/cross_entity_state_dependency/cesd_agreement_sign_requires_visit_signable
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    agreement = create_agreement(visit["id"], document_kind="NDA", document_version="NDA-v3")
    screen_visit(visit["id"])  # -> DENIED, cascades agreement to VOID

    # PRD 3.5 makes signing illegal here for two independent reasons that fire
    # together in this scenario: the agreement is no longer PENDING (cascaded to VOID)
    # AND the parent visit has reached DENIED. The PRD names ERR_VISIT_NOT_SIGNABLE for
    # the visit-state failure but states no precedence between the agreement-PENDING
    # guard and the visit-state guard, so a faithful reader that checks agreement state
    # first reasonably returns ERR_INVALID_STATE. Accept either (ERROR PRECEDENCE
    # SILENCE relaxation).
    res = api.sign_agreement(agreement["id"], {"signer_name": "Jordan Blake"}, LA)
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_VISIT_NOT_SIGNABLE, ApiErrorId.ERR_INVALID_STATE],
    )

    fetched = validate_success(api.get_agreement(agreement["id"], SO))
    assert fetched["status"] == "VOID", f"expected VOID, got {fetched['status']}"


def test_screen_deny_leaves_visit_terminal_denied(api):
    """PRD 3.4: "On a DENY decision it auto-advances `SCREENING` to `DENIED`, a
    terminal state in which no badge is ever printed, and every `PENDING` agreement on
    the visit is cascaded to `VOID`."

    The first hop of the depth-3 chain: the screened visit is DENIED (the cascade's
    cause), with no badge ever printed.

    Design: Difficulty/transitive_cascade/tc_screen_deny_voids_agreement_depth3
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    create_agreement(visit["id"], document_kind="NDA", document_version="NDA-v3")
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "DENIED", f"expected DENIED, got {screened['status']}"
    assert screened["badge_number"] is None, "no badge is ever printed for a DENIED visit"


def test_covered_visit_signs_in_to_signed_in(api):
    """PRD 3.6: "When every guard passes, the visit moves `CLEARED → SIGNED_IN`: the
    server stamps `sign_in_at` with its clock and assigns a printed `badge_number`."

    The other half of the depth-2 chain: the contractor-covered visit itself reaches
    SIGNED_IN with a non-null badge_number, the precondition that triggers the
    covered_visit_count bump.

    Design: Difficulty/transitive_cascade/tc_signin_bumps_contractor_covered_count_depth2
    """
    site, floor, host, pass_, visit = setup_contractor_covered_cleared_visit()
    fv = get_floor_version(floor["id"])
    signed_in = validate_success(
        api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    )
    assert signed_in["status"] == "SIGNED_IN", f"expected SIGNED_IN, got {signed_in['status']}"
    assert signed_in["badge_number"] is not None, "badge_number must be assigned on sign-in"


def test_contractor_pass_suspend_then_reactivate_restores_active(api):
    """PRD 3.7: "An `ACTIVE` pass may be suspended, moving `ACTIVE → SUSPENDED`, after
    which covered visits can no longer sign in until the pass is reactivated; a
    `SUSPENDED` pass may be reactivated, moving `SUSPENDED → ACTIVE` and restoring
    coverage."

    The suspend leg of the cyclic machine: after ACTIVE -> SUSPENDED the pass is
    SUSPENDED, then reactivate returns it to ACTIVE.

    Design: Difficulty/non_linear_state_machine/nlsm_contractorpass_cyclic_active_suspended
    """
    site, host = setup_site_host()
    pass_ = create_contractor_pass(host["id"])
    suspended = validate_success(api.suspend_contractor_pass(pass_["id"], SO))
    assert suspended["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['status']}"
    )
    reactivated = validate_success(api.reactivate_contractor_pass(pass_["id"], SO))
    assert reactivated["status"] == "ACTIVE"


def test_signin_on_suspended_pass_leaves_visit_cleared(api):
    """PRD 3.6: "if the visit carries a `contractor_pass_id`, the referenced pass must
    be in `ACTIVE` status, or the request is rejected with `ERR_PASS_NOT_ACTIVE`".
    PRD 3.7: "a contractor-covered sign-in checks that the pass is `ACTIVE` at the
    moment of sign-in, so a suspended or revoked pass blocks the visitor's entry."

    The rejected sign-in must not advance the visit: it remains CLEARED.

    Design: Difficulty/cross_entity_state_dependency/cesd_signin_requires_active_contractor_pass
    """
    site, floor, host, pass_, visit = setup_contractor_covered_cleared_visit()
    get_success_data(api.suspend_contractor_pass(pass_["id"], SO))
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    validate_error(res, ApiErrorId.ERR_PASS_NOT_ACTIVE)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED"
    assert fetched["badge_number"] is None, "no badge printed when sign-in is rejected"


def test_voided_agreement_status_is_void_after_visit_denied(api):
    """PRD 3.5: "Separately, an agreement reaches the terminal `VOID` state only by
    system cascade, when its parent visit transitions to `DENIED`."
    PRD 3.5: "Once the parent visit has reached `DENIED`, `SIGNED_IN`, or
    `SIGNED_OUT`, the agreement can no longer be signed, and the attempt is rejected
    with `ERR_VISIT_NOT_SIGNABLE` (HTTP 409)."

    The agreement reaches VOID purely by the deny cascade (no explicit void call).

    Design: Difficulty/cross_entity_state_dependency/cesd_agreement_sign_requires_visit_signable
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    agreement = create_agreement(visit["id"], document_kind="NDA", document_version="NDA-v3")
    assert agreement["status"] == "PENDING"
    screen_visit(visit["id"])
    fetched = validate_success(api.get_agreement(agreement["id"], SO))
    assert fetched["status"] == "VOID", f"expected VOID, got {fetched['status']}"
