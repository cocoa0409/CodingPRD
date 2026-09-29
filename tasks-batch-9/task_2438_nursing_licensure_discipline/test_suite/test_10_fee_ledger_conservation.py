"""The two conserved quantities: the money ledger and the open-complaint count."""
from test_helpers import (
    ANALYST,
    BOARD_DEFAULTS,
    INVESTIGATOR,
    ApiClient,
    assert_fee_ledger_identity,
    assert_license_dimensions,
    assert_renewal_dimensions,
    dispose_complaint,
    reread_complaint,
    reread_license,
    reread_nurse,
    reread_renewal,
    seed_active_license,
    seed_evidence_complete_complaint,
    seed_licensed_renewal_context,
    validate_paginated,
    validate_success,
)

BASE_FEE_CENTS = BOARD_DEFAULTS["renewal_base_fee_cents"]


def _paid_filing_awaiting_finalisation(api: ApiClient):
    """A paid renewal filing standing at CE_VERIFIED, ready to be granted or denied."""
    ctx = seed_licensed_renewal_context(
        api,
        stage="CE_VERIFIED",
        attested_practice_hours=1600,
        program_overrides={
            "program_code": "OH-BSN-33",
            "program_name": "Athens BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8750,
        },
        nurse_overrides={"full_name": "Emeka Balogun", "birth_year": 1982,
                         "ssn_last4": "3131"},
        ce_minutes=1800,
        ce_completion_date="2027-10-10T00:00:00Z",
    )
    return ctx


def test_denial_moves_the_applied_fee_into_the_nurses_credit(api: ApiClient):
    """PRD §3.4: "A denial moves `renewal_status` to the terminal `DENIED` and
    performs the compensating fiscal action: the filing's `fee_applied_cents` is
    added to the nurse's `fee_credit_cents` and then set to 0, while
    `fee_paid_cents` and the nurse's `fee_paid_total_cents` are left exactly as
    they were, so the ledger identity of §2.12 still balances."

    PRD §2.12: "The invariant is this: a nurse's `fee_paid_total_cents` always
    equals that nurse's `fee_credit_cents` plus the sum of `fee_applied_cents`
    across every renewal filing on that nurse's credentials whose
    `renewal_status` is not `WITHDRAWN`."

    PRD §2.12: "Neither one ever reduces `fee_paid_cents` or
    `fee_paid_total_cents`."

    Design: Difficulty/compensating_invariant/renewal_denial_moves_fee_to_credit_conserving_the_ledger
    """
    ctx = _paid_filing_awaiting_finalisation(api)
    before = reread_renewal(api, ctx["renewal_id"])
    assert_renewal_dimensions(before, "CE_VERIFIED", "NOT_SELECTED")
    assert before["fee_applied_cents"] == BASE_FEE_CENTS, (
        f"An on-time filing is charged the base fee, got {before['fee_applied_cents']}"
    )
    nurse_before = reread_nurse(api, ctx["nurse_id"])
    assert nurse_before["fee_paid_total_cents"] == BASE_FEE_CENTS
    assert nurse_before["fee_credit_cents"] == 0

    denied = validate_success(
        api.finalize_renewal_application(ctx["renewal_id"], {"outcome": "DENIED"}, ANALYST)
    )

    assert denied["renewal_status"] == "DENIED"
    assert denied["fee_applied_cents"] == 0, (
        f"The applied charge is zeroed on denial, got {denied['fee_applied_cents']}"
    )
    assert denied["fee_paid_cents"] == BASE_FEE_CENTS, (
        f"Received money is append-only, got {denied['fee_paid_cents']}"
    )

    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["fee_credit_cents"] == BASE_FEE_CENTS, (
        f"The zeroed charge reappears as credit, got {nurse['fee_credit_cents']}"
    )
    assert nurse["fee_paid_total_cents"] == BASE_FEE_CENTS, (
        f"The lifetime paid figure never drops, got {nurse['fee_paid_total_cents']}"
    )
    assert_fee_ledger_identity(nurse, [denied])


def test_denial_leaves_the_credential_and_its_expiry_exactly_as_they_were(
    api: ApiClient,
):
    """PRD §3.4: "A grant moves `renewal_status` to the terminal `RENEWED`,
    advances the credential's `expires_on` by the board's `renewal_period_months`
    from its prior value, returns `license_status` from `EXPIRED` to `ACTIVE` (or
    leaves an `ACTIVE` credential `ACTIVE`), re-runs the privilege determination
    under `RESIDENCY_DECLARED`, and advances the credential's `version` by one."

    PRD §3.4: "A denial carries one further consequence when the practice-hour
    audit stands `FAILED`: the system opens a fresh complaint against the
    credential on its own initiative, with `complainant_type` `BOARD_INITIATED`,
    `violation_category` `FRAUD`, status `RECEIVED`, and
    `employer_custodian_codes` populated from the employer names appearing in the
    audited `practice_hour_periods`."

    PRD §2.12: "That asymmetry is intentional: the received-money figures are
    append-only, which is what makes the identity auditable and what makes a
    refund observable as a credit rather than as a disappearance."

    Design: Difficulty/compensating_invariant/renewal_denial_moves_fee_to_credit_conserving_the_ledger
    """
    ctx = _paid_filing_awaiting_finalisation(api)
    credential_before = reread_license(api, ctx["license_id"])
    assert credential_before["expires_on"].startswith("2028-08-01"), (
        f"A credential issued on the default clock expires two years later, got "
        f"{credential_before['expires_on']}"
    )

    validate_success(
        api.finalize_renewal_application(ctx["renewal_id"], {"outcome": "DENIED"}, ANALYST)
    )

    credential = reread_license(api, ctx["license_id"])
    assert credential["expires_on"] == credential_before["expires_on"], (
        f"A denial grants no extra time: expiry moved from "
        f"{credential_before['expires_on']} to {credential['expires_on']}"
    )
    assert_license_dimensions(credential, "ACTIVE", "CLEAR")
    assert credential["version"] == credential_before["version"], (
        f"A denial does not touch the credential: version moved from "
        f"{credential_before['version']} to {credential['version']}"
    )

    complaints, meta = validate_paginated(
        api.list_complaints(INVESTIGATOR,
                            params={"license_id": ctx["license_id"], "limit": 100})
    )
    assert complaints == [], (
        f"No audit stood FAILED, so no board-initiated complaint opens, got {complaints}"
    )
    assert meta["total_count"] == 0


def _two_open_investigations_on_one_credential(api: ApiClient):
    """One credential carrying two independent open complaints, both with their
    evidence gathering finished."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-44",
            "program_name": "Xenia BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8350,
        },
        nurse_overrides={"full_name": "Junko Marchetti", "birth_year": 1995,
                         "ssn_last4": "5757"},
    )
    first = seed_evidence_complete_complaint(
        api, ctx["license_id"], page_count=9,
        evidence_overrides={
            "record_class": "EMPLOYER_INCIDENT",
            "custodian_code": "MERCY-GEN",
            "hold_start_at": "2026-08-03T00:00:00Z",
            "hold_end_at": "2026-08-28T00:00:00Z",
        },
        complainant_type="PATIENT",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-06-10T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    second = seed_evidence_complete_complaint(
        api, ctx["license_id"], page_count=14,
        evidence_overrides={
            "record_class": "EMPLOYER_INCIDENT",
            "custodian_code": "ST-LUKE",
            "hold_start_at": "2026-08-03T00:00:00Z",
            "hold_end_at": "2026-08-28T00:00:00Z",
        },
        complainant_type="EMPLOYER",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-06-28T00:00:00Z",
        employer_custodian_codes=["ST-LUKE"],
    )
    ctx["first_complaint_id"] = first["id"]
    ctx["second_complaint_id"] = second["id"]
    return ctx


def test_dismissing_the_second_of_two_complaints_returns_the_count_to_zero(
    api: ApiClient,
):
    """PRD §2.7: "The count is a conserved quantity: opening an investigation
    raises it by exactly one, and dismissing that complaint — whether by
    investigator disposition or by panel dismissal — lowers it by exactly one,
    leaving no drift."

    PRD §3.6: "Two concurrent investigations against the same credential therefore
    leave `encumbrance_status` at `INVESTIGATION_PENDING` with
    `open_encumbrance_count` at 2, and closing only one of them must not clear the
    encumbrance; the reconciliation rule of §2.7 is what enforces that."

    PRD §3.6: "Dismissing moves `status` to the terminal `DISMISSED`, withdraws
    every records demand on the complaint still standing at `REQUESTED`, and
    reconciles the credential's encumbrance: `open_encumbrance_count` is
    decremented, and if it reaches zero the credential returns to `CLEAR` and the
    privilege determination is re-run, restoring compact standing where the
    propagation rules allow."

    Design: Difficulty/compensating_invariant/complaint_dismissals_restore_open_encumbrance_count_to_zero
    """
    ctx = _two_open_investigations_on_one_credential(api)
    both_open = reread_license(api, ctx["license_id"])
    assert both_open["open_encumbrance_count"] == 2, (
        f"Two complaints sit in the open set, got {both_open['open_encumbrance_count']}"
    )

    dispose_complaint(api, ctx["first_complaint_id"], "DISMISS")
    halfway = reread_license(api, ctx["license_id"])
    assert halfway["open_encumbrance_count"] == 1, (
        f"One dismissal lowers the count by exactly one, got "
        f"{halfway['open_encumbrance_count']}"
    )
    assert_license_dimensions(halfway, "ACTIVE", "INVESTIGATION_PENDING")

    validate_success(
        api.dispose_complaint(ctx["second_complaint_id"], {"disposition": "DISMISS"},
                              INVESTIGATOR)
    )

    credential = reread_license(api, ctx["license_id"])
    assert credential["open_encumbrance_count"] == 0, (
        f"Both complaints have left the open set, got "
        f"{credential['open_encumbrance_count']}"
    )
    assert_license_dimensions(credential, "ACTIVE", "CLEAR")
    assert credential["multistate_privilege_status"] == "MULTISTATE", (
        "The re-run determination restores compact standing on a clean credential, "
        f"got {credential['multistate_privilege_status']}"
    )


def test_clearing_the_last_complaint_returns_the_nurse_to_active(api: ApiClient):
    """PRD §2.7: "A nurse's aggregate `status` follows the credentials. It is
    `ACTIVE` by default, becomes `ENCUMBERED` when a credential of that nurse
    becomes encumbered, returns to `ACTIVE` when no credential of that nurse
    carries `RESTRICTED`, `SUSPENDED`, or `REVOKED` and no open complaint remains,
    and becomes `REVOKED` once every credential belonging to that nurse carries
    `encumbrance_status` `REVOKED`."

    PRD §2.7: "Whenever a complaint enters or leaves the open set, and whenever a
    disciplinary order issues, the credential's `open_encumbrance_count` is
    recomputed in full — never incrementally patched — as the number of complaints
    whose `license_id` is this credential, whose `consolidated_into_complaint_id`
    is null, and whose status is one of the six open states `INVESTIGATION_OPEN`,
    `EVIDENCE_COMPLETE`, `ATD_OFFERED`, `ATD_ACTIVE`, `REFERRED_FOR_HEARING`, and
    `PROCEEDING_OPENED`."

    PRD §3.1: "`prior_discipline_count` starts at 0 and equals the number of
    disciplinary proceedings against that nurse that reached `ORDER_ISSUED` with
    an adopted sanction other than `NONE`."

    Design: Difficulty/compensating_invariant/complaint_dismissals_restore_open_encumbrance_count_to_zero
    """
    ctx = _two_open_investigations_on_one_credential(api)
    assert reread_nurse(api, ctx["nurse_id"])["status"] == "ENCUMBERED"

    dispose_complaint(api, ctx["first_complaint_id"], "DISMISS")
    assert reread_nurse(api, ctx["nurse_id"])["status"] == "ENCUMBERED", (
        "One complaint is still open, so the nurse stays encumbered"
    )

    validate_success(
        api.dispose_complaint(ctx["second_complaint_id"], {"disposition": "DISMISS"},
                              INVESTIGATOR)
    )

    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["status"] == "ACTIVE", (
        f"No open complaint and no order in force returns the nurse to ACTIVE, got "
        f"{nurse['status']}"
    )
    assert nurse["prior_discipline_count"] == 0, (
        f"A dismissal is not discipline, got {nurse['prior_discipline_count']}"
    )
    for complaint_id in (ctx["first_complaint_id"], ctx["second_complaint_id"]):
        complaint = reread_complaint(api, complaint_id)
        assert complaint["status"] == "DISMISSED", (
            f"Both complaints reached the terminal DISMISSED, got {complaint['status']}"
        )
        assert complaint["disposition_at"] is not None, (
            "Disposing stamps disposition_at from the logical clock"
        )
