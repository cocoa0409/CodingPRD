"""Good-standing certificate claims: the STANDARD/EXPEDITED fee variants, the
90-day validity boundary, the posture gate at request, and system auto-denial
on posture loss."""
from test_helpers import (
    SEC1,
    ApiErrorId,
    list_events,
    request_certificate,
    run_sweep,
    set_clock,
    setup_base_entity,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_certificate_fee_variants_computed(api):
    """PRD 3.10: "The `fee_cents` is computed from the jurisdiction's
    `cert_fee_cents`: the full amount for `STANDARD` delivery, or 1.5 times
    that amount rounded half-up to whole cents for `EXPEDITED` delivery."
    PRD 3.10: "The certificate begins in `REQUESTED` status with
    `requested_date` set to the current logical date."

    Design: Corner/entities/certificate_fee_variants_computed
    """
    ctx = setup_base_entity(legal_name="Cert Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]

    standard = request_certificate(entity["id"], j1["id"], "STANDARD")
    assert standard["fee_cents"] == 5000
    assert standard["status"] == "REQUESTED"
    assert standard["requested_date"] == "2026-08-01"

    expedited = request_certificate(entity["id"], j1["id"], "EXPEDITED")
    assert expedited["fee_cents"] == 7500, "round_half_up(5000 * 1.5)"
    assert expedited["status"] == "REQUESTED"
    assert expedited["requested_date"] == "2026-08-01"


def test_certificate_expiry_boundary(api):
    """PRD 3.10: "Upon issuance, `issued_date` is set to the current logical
    date and `valid_until` is set to `issued_date` plus 90 calendar days."
    PRD 3.10: "An issued certificate transitions to `EXPIRED` when the logical
    clock passes `valid_until`."

    Design: Corner/state_machines/certificate_expiry_boundary
    """
    ctx = setup_base_entity(legal_name="Certlife Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    cert = request_certificate(entity["id"], j1["id"], "STANDARD")

    issued = validate_success(api.issue_certificate(cert["id"], SEC1))
    assert issued["issued_date"] == "2026-08-01"
    assert issued["valid_until"] == "2026-10-30", "issued_date + 90 calendar days"

    # On the boundary day "passes" is still false.
    set_clock("2026-10-30T00:00:00Z")
    report = run_sweep()
    assert report["certificates_expired"] == 0
    current = validate_success(api.get_certificate(cert["id"], SEC1))
    assert current["status"] == "ISSUED"

    # The day after valid_until the certificate has lapsed.
    set_clock("2026-10-31T00:00:00Z")
    report = run_sweep()
    assert report["certificates_expired"] == 1
    expired = validate_success(api.get_certificate(cert["id"], SEC1))
    assert expired["status"] == "EXPIRED"


def test_certificate_request_when_delinquent_rejected(api):
    """PRD 3.10: "The entity's `compliance_posture` must be `GOOD_STANDING` at
    request time; otherwise the request is rejected with
    `ERR_POSTURE_NOT_GOOD_STANDING`."

    Design: Corner/errors/certificate_request_when_delinquent_rejected
    """
    ctx = setup_base_entity(legal_name="Certgate Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]

    # Past due 2026-12-31, within grace + 30: posture DELINQUENT.
    set_clock("2027-01-05T00:00:00Z")
    run_sweep()

    response = api.create_certificate_request(
        entity["id"], {"jurisdiction_id": j1["id"], "delivery_speed": "STANDARD"}, SEC1
    )
    validate_error(response, ApiErrorId.ERR_POSTURE_NOT_GOOD_STANDING)

    rows, meta = validate_paginated(
        api.list_certificates(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_certificate_auto_denied_on_posture_loss(api):
    """PRD 3.10: "A certificate may be denied while `REQUESTED`, either
    manually by a `CorporateSecretary` supplying a `reason`, or automatically
    by the system when the entity's posture leaves `GOOD_STANDING`. Denial sets
    `denial_reason` — to the supplied `reason` for a manual denial, or to
    `POSTURE_LOST` for a system-initiated denial — and appends a
    `ComplianceEvent` of type `CERTIFICATE_DENIED`."
    PRD 3.15: "The sweep response reports `filings_marked_overdue`,
    `resolutions_made_effective`, `resolutions_blocked`, `grants_expired`,
    `certificates_expired`, `certificates_auto_denied`, and `posture_changes`."

    Design: Corner/errors/certificate_auto_denied_on_posture_loss
    """
    ctx = setup_base_entity(legal_name="Autodeny Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    cert = request_certificate(entity["id"], j1["id"], "STANDARD")
    assert cert["status"] == "REQUESTED"

    # Filings flip OVERDUE -> posture DELINQUENT -> the REQUESTED cert drops.
    set_clock("2027-01-05T00:00:00Z")
    report = run_sweep()
    assert report["certificates_auto_denied"] == 1

    denied = validate_success(api.get_certificate(cert["id"], SEC1))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "POSTURE_LOST"

    events = list_events(entity["id"], event_type="CERTIFICATE_DENIED")
    assert len(events) == 1
