"""Estate claims: claim window boundary, compliance gate, certificate
freeze/release cascade (PRD §2.10, §3.7)."""
from test_helpers import (
    validate_success, validate_error, api_client,
    setup_estate_claim_filed, set_clock,
    list_member_certificates, pass_resolution,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
SECRETARY = TEST_USERS["secretary_headers"]


def _probate(claim_id, probate_completed_at):
    return api_client.record_probate(
        claim_id, {"probate_completed_at": probate_completed_at}, REGISTRAR,
    )


def test_estate_window_exact_90_days_is_decidable(api):
    """PRD §3.7: "Once the probate court has closed the estate, the registrar
    records probate by supplying `probate_completed_at`, moving the claim
    `FILED` → `PROBATED`; probate may only be recorded once the logical clock
    has reached `filed_at` plus the claim window, and the boundary is
    inclusive — a claim exactly 90 days old is decidable."

    Claim FILED at 2026-01-01T00:00:00Z; clock at exactly +90 days
    (2026-04-01T00:00:00Z).

    Design: Difficulty/boundary_precision_check/estate_claim_window_exact_day_90
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-01-01T00:00:00Z", date_of_death="2026-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    assert claim["status"] == "FILED"
    set_clock("2026-04-01T00:00:00Z")
    probated = validate_success(_probate(claim["id"], "2026-03-30T00:00:00Z"))
    assert probated["status"] == "PROBATED", (
        f"A claim exactly 90 days old is decidable; got "
        f"{probated['status']}"
    )


def test_estate_window_89_days_is_not_decidable(api):
    """PRD §3.7: "probate may only be recorded once the logical clock has
    reached `filed_at` plus the claim window, and the boundary is inclusive —
    a claim exactly 90 days old is decidable."
    PRD §2.10: "Compliance gates: the estate claim window has elapsed before
    probate is recorded, the member is not `DECEASED` when a new delivery is
    booked, and no listed certificate is `FROZEN` at disbursement — otherwise
    `ERR_COMPLIANCE_GATE` (HTTP 422)."

    Claim FILED at 2026-01-01T00:00:00Z; clock at +89 days
    (2026-03-31T00:00:00Z).

    Design: Difficulty/boundary_precision_check/estate_claim_window_exact_day_90
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-01-01T00:00:00Z", date_of_death="2026-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    set_clock("2026-03-31T00:00:00Z")
    res = _probate(claim["id"], "2026-03-30T00:00:00Z")
    validate_error(res, "ERR_COMPLIANCE_GATE", expected_status=422)
    after = validate_success(api_client.get_estate_claim(claim["id"], REGISTRAR))
    assert after["status"] == "FILED"


def test_probate_at_30_days_compliance_gate(api):
    """PRD §2.10: "Compliance gates: the estate claim window has elapsed
    before probate is recorded, the member is not `DECEASED` when a new
    delivery is booked, and no listed certificate is `FROZEN` at disbursement
    — otherwise `ERR_COMPLIANCE_GATE` (HTTP 422). These gates guard delivery
    booking, redemption submission, redemption disbursement, and probate
    recording."
    PRD §3.7: "An estate claim captures the decedent's `claim_amount_cents` —
    the total outstanding equity at the moment the claim is filed — along
    with its `filed_at` timestamp and its `claim_window_days`, which defaults
    to 90."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_estate_probate
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-01-01T00:00:00Z", date_of_death="2026-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    set_clock("2026-01-31T00:00:00Z")
    res = _probate(claim["id"], "2026-01-30T00:00:00Z")
    validate_error(res, "ERR_COMPLIANCE_GATE", expected_status=422)
    after = validate_success(api_client.get_estate_claim(claim["id"], REGISTRAR))
    assert after["status"] == "FILED", (
        "Claim must remain FILED when the compliance gate rejects probate"
    )


def test_probate_at_89_days_compliance_gate(api):
    """PRD §2.10: "Compliance gates: the estate claim window has elapsed
    before probate is recorded, the member is not `DECEASED` when a new
    delivery is booked, and no listed certificate is `FROZEN` at disbursement
    — otherwise `ERR_COMPLIANCE_GATE` (HTTP 422)."

    One day short of the 90-day claim window still fails the gate.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_estate_probate
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-01-01T00:00:00Z", date_of_death="2026-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    set_clock("2026-03-31T00:00:00Z")
    res = _probate(claim["id"], "2026-03-30T00:00:00Z")
    validate_error(res, "ERR_COMPLIANCE_GATE", expected_status=422)
    after = validate_success(api_client.get_estate_claim(claim["id"], REGISTRAR))
    assert after["status"] == "FILED"


def test_certificates_frozen_until_claim_approved(api):
    """PRD §3.7: "Recording the death moves the member from `ACTIVE` to
    `DECEASED`, spawns an estate claim in `FILED` status naming the executor,
    freezes all of the decedent's `ACTIVE` certificates pending probate, and
    cancels any open redemption requests with the cancellation reason
    `ESTATE_TRANSITION`."
    PRD §2.10: "Compliance gates: the estate claim window has elapsed before
    probate is recorded, the member is not `DECEASED` when a new delivery is
    booked, and no listed certificate is `FROZEN` at disbursement — otherwise
    `ERR_COMPLIANCE_GATE` (HTTP 422)."

    Death at 2026-09-05 freezes the certificates; probate attempted at +26
    days is rejected and the certificates remain FROZEN.

    Design: Difficulty/cross_entity_state_dependency/certificate_reissue_depends_on_estate_probated
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-09-05T00:00:00Z", date_of_death="2026-09-05T00:00:00Z",
        with_certificates=True,
    )
    decedent = ctx["decedent"]
    certs = list_member_certificates(decedent["id"])
    assert len(certs) >= 1
    for cert in certs:
        assert cert["status"] == "FROZEN", (
            f"Certificate must be FROZEN pending probate, got {cert['status']}"
        )
    set_clock("2026-10-01T00:00:00Z")
    res = _probate(ctx["claim"]["id"], "2026-09-30T00:00:00Z")
    validate_error(res, "ERR_COMPLIANCE_GATE", expected_status=422)
    claim_after = validate_success(
        api_client.get_estate_claim(ctx["claim"]["id"], REGISTRAR),
    )
    assert claim_after["status"] == "FILED"
    certs_after = list_member_certificates(decedent["id"])
    for cert in certs_after:
        assert cert["status"] == "FROZEN", (
            "Rejected probate must not unfreeze certificates; got "
            f"{cert['status']}"
        )


def test_probate_rejection_preserves_frozen_certificates(api):
    """PRD §3.7: "approval requires a `PASSED` resolution of kind
    `APPROVE_ESTATE` referencing the claim and moves it to `APPROVED`,
    releasing all of the decedent's `FROZEN` certificates back to `ACTIVE` so
    they become transferable to the executor; denial moves it to `DENIED`."

    Before approval the certificates stay FROZEN; a premature probate attempt
    (89 days, one short of the window) changes nothing.

    Design: Difficulty/cross_entity_state_dependency/certificate_reissue_depends_on_estate_probated
    """
    ctx = setup_estate_claim_filed(
        death_clock="2026-09-05T00:00:00Z", date_of_death="2026-09-05T00:00:00Z",
        with_certificates=True,
    )
    decedent = ctx["decedent"]
    set_clock("2026-12-03T00:00:00Z")
    res = _probate(ctx["claim"]["id"], "2026-12-01T00:00:00Z")
    validate_error(res, "ERR_COMPLIANCE_GATE", expected_status=422)
    certs_after = list_member_certificates(decedent["id"])
    assert len(certs_after) >= 1
    for cert in certs_after:
        assert cert["status"] == "FROZEN"


def test_estate_approval_releases_certificates(api):
    """PRD §3.7: "The board then decides the claim: approval requires a
    `PASSED` resolution of kind `APPROVE_ESTATE` referencing the claim and
    moves it to `APPROVED`, releasing all of the decedent's `FROZEN`
    certificates back to `ACTIVE` so they become transferable to the
    executor; denial moves it to `DENIED`."

    Design: Difficulty/transitive_cascade/estate_claim_approval_cascades_to_disbursement
    """
    ctx = setup_estate_claim_filed(
        death_clock="2027-01-15T00:00:00Z", date_of_death="2027-01-10T00:00:00Z",
        with_certificates=True,
    )
    decedent = ctx["decedent"]
    claim = ctx["claim"]
    set_clock("2027-05-15T00:00:00Z")  # +120 days: claim window elapsed
    probated = validate_success(_probate(claim["id"], "2027-05-10T00:00:00Z"))
    assert probated["status"] == "PROBATED"
    resolution = pass_resolution(
        "APPROVE_ESTATE", claim["id"], ctx["delegate"]["id"],
    )
    decided = validate_success(
        api_client.decide_estate_claim(
            claim["id"],
            {"decision": "APPROVE", "resolution_id": resolution["id"]},
            SECRETARY,
        ),
    )
    assert decided["status"] == "APPROVED"
    certs_after = list_member_certificates(decedent["id"])
    assert len(certs_after) >= 1
    for cert in certs_after:
        assert cert["status"] == "ACTIVE", (
            "Approval must release FROZEN certificates back to ACTIVE; got "
            f"{cert['status']}"
        )


def test_probate_alone_does_not_unfreeze_certificates(api):
    """PRD §3.7: "The board then decides the claim: approval requires a
    `PASSED` resolution of kind `APPROVE_ESTATE` referencing the claim and
    moves it to `APPROVED`, releasing all of the decedent's `FROZEN`
    certificates back to `ACTIVE` so they become transferable to the
    executor; denial moves it to `DENIED`."

    Recording probate (FILED → PROBATED) is not approval: the certificates
    must remain FROZEN until the board approves.

    Design: Difficulty/transitive_cascade/estate_claim_approval_cascades_to_disbursement
    """
    ctx = setup_estate_claim_filed(
        death_clock="2027-01-15T00:00:00Z", date_of_death="2027-01-10T00:00:00Z",
        with_certificates=True,
    )
    decedent = ctx["decedent"]
    claim = ctx["claim"]
    set_clock("2027-05-15T00:00:00Z")
    probated = validate_success(_probate(claim["id"], "2027-05-10T00:00:00Z"))
    assert probated["status"] == "PROBATED"
    certs_after = list_member_certificates(decedent["id"])
    assert len(certs_after) >= 1
    for cert in certs_after:
        assert cert["status"] == "FROZEN", (
            "Probate without board approval must not unfreeze certificates; "
            f"got {cert['status']}"
        )
