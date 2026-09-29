"""The credential's registration and disciplinary dimensions move independently."""
from test_helpers import (
    INVESTIGATOR,
    ApiClient,
    assert_license_dimensions,
    change_status,
    complete_evidence,
    reread_complaint,
    reread_license,
    reread_nurse,
    seed_active_license,
    seed_investigated_complaint,
    seed_produced_evidence_request,
    validate_success,
)


def _inactive_credential_under_investigation(api: ApiClient):
    """A credential placed on inactive status while a complaint is still open."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-21",
            "program_name": "Maumee BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8500,
        },
        nurse_overrides={"full_name": "Lena Whitfield", "birth_year": 1992,
                         "ssn_last4": "5566"},
    )
    complaint = seed_investigated_complaint(
        api, ctx["license_id"],
        complainant_type="PATIENT",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-07-02T00:00:00Z",
        employer_custodian_codes=["RIVERSIDE-1"],
    )
    ctx["license"] = change_status(api, ctx["license_id"], "INACTIVE")
    seed_produced_evidence_request(
        api, complaint["id"], page_count=12,
        record_class="EMPLOYER_INCIDENT",
        custodian_code="RIVERSIDE-1",
        hold_start_at="2026-08-03T00:00:00Z",
        hold_end_at="2026-08-31T00:00:00Z",
    )
    ctx["complaint"] = complete_evidence(api, complaint["id"])
    ctx["complaint_id"] = complaint["id"]
    return ctx


def test_dismissal_clears_encumbrance_without_touching_registration_standing(
    api: ApiClient,
):
    """PRD §2.7: "A credential carries `license_status` for its registration
    standing (`ACTIVE`, `INACTIVE`, `EXPIRED`, `LAPSED`, `SURRENDERED`, with
    `LAPSED` and `SURRENDERED` terminal) and `encumbrance_status` for its
    disciplinary standing (`CLEAR`, `INVESTIGATION_PENDING`, `RESTRICTED`,
    `SUSPENDED`, `REVOKED`, with `REVOKED` terminal)."

    PRD §2.7: "Two resources in this system carry two status dimensions each, and
    the dimensions are genuinely independent: neither one is derivable from the
    other, and each has its own set of legal transitions and its own set of
    actors."

    PRD §3.6: "Dismissing moves `status` to the terminal `DISMISSED`, withdraws
    every records demand on the complaint still standing at `REQUESTED`, and
    reconciles the credential's encumbrance: `open_encumbrance_count` is
    decremented, and if it reaches zero the credential returns to `CLEAR` and the
    privilege determination is re-run, restoring compact standing where the
    propagation rules allow."

    Design: Difficulty/non_linear_state_machine/license_registration_and_encumbrance_dimensions_move_independently
    """
    ctx = _inactive_credential_under_investigation(api)
    assert_license_dimensions(ctx["license"], "INACTIVE", "INVESTIGATION_PENDING")

    dismissed = validate_success(
        api.dispose_complaint(ctx["complaint_id"], {"disposition": "DISMISS"}, INVESTIGATOR)
    )

    assert dismissed["status"] == "DISMISSED", (
        f"Dismissal is terminal on the complaint, got {dismissed['status']}"
    )
    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "INACTIVE", "CLEAR")
    assert credential["open_encumbrance_count"] == 0, (
        f"The only open complaint closed, got {credential['open_encumbrance_count']}"
    )


def test_cleared_encumbrance_still_yields_not_eligible_on_an_inactive_credential(
    api: ApiClient,
):
    """PRD §3.3: "Otherwise, if the credential's `license_status` is anything
    other than `ACTIVE`, the answer is `NOT_ELIGIBLE`."

    PRD §3.3: "The determination is a guard chain evaluated strictly top to
    bottom, and the first guard that matches decides the answer."

    PRD §2.7: "It is `ACTIVE` by default, becomes `ENCUMBERED` when a credential
    of that nurse becomes encumbered, returns to `ACTIVE` when no credential of
    that nurse carries `RESTRICTED`, `SUSPENDED`, or `REVOKED` and no open
    complaint remains, and becomes `REVOKED` once every credential belonging to
    that nurse carries `encumbrance_status` `REVOKED`."

    Design: Difficulty/non_linear_state_machine/license_registration_and_encumbrance_dimensions_move_independently
    """
    ctx = _inactive_credential_under_investigation(api)

    validate_success(
        api.dispose_complaint(ctx["complaint_id"], {"disposition": "DISMISS"}, INVESTIGATOR)
    )

    credential = reread_license(api, ctx["license_id"])
    assert credential["multistate_privilege_status"] == "NOT_ELIGIBLE", (
        "A cleared encumbrance cannot restore privilege while registration is "
        f"INACTIVE, got {credential['multistate_privilege_status']}"
    )
    complaint = reread_complaint(api, ctx["complaint_id"])
    assert complaint["status"] == "DISMISSED"
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["status"] == "ACTIVE", (
        f"With no encumbrance and no open complaint the nurse returns to ACTIVE, "
        f"got {nurse['status']}"
    )
