"""OCC-guarded denial writes: assignment and intake correction (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assign_payload,
    correction_payload,
    make_denial,
    setup_catalog,
    triage_denial,
    validate_error,
    validate_success,
)


def test_occ_assign_stale_version_rejected(api, manager_headers):
    """PRD §2.7: "If the denial's current `version` no longer matches the supplied value —
    because a triage, an earlier assignment, a prior correction, or a cascaded update has
    advanced the version since the client last read the denial — the write is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_assign_stale_version_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2601")
    pre_triage_version = denial["version"]
    triage_denial(denial["id"])
    resp = api.assign_denial(
        denial["id"], assign_payload("spec-1", pre_triage_version), manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_denial_case(denial["id"], manager_headers))
    assert after["status"] == "TRIAGED"
    assert after["assigned_specialist_id"] is None


def test_occ_assign_fresh_version_succeeds(api, manager_headers):
    """PRD §3.3: "A first assignment moves the denial `TRIAGED` → `QUEUED`; a later
    assignment on an already-`QUEUED` denial is a reassignment that leaves the status at
    `QUEUED` and simply replaces `assigned_specialist_id`. Both forms append an `ASSIGNED`
    event and increment the denial's `version` by one."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by one with
    every modification to the resource, including mutations that only recompute derived
    fields; it underpins optimistic concurrency control."

    Design: Corner/complexity_layers/occ_assign_fresh_version_succeeds
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2602")
    triaged = triage_denial(denial["id"])
    assigned = validate_success(
        api.assign_denial(
            denial["id"], assign_payload("spec-1", triaged["version"]), manager_headers,
        )
    )
    assert assigned["status"] == "QUEUED"
    assert assigned["version"] == triaged["version"] + 1
    assert assigned["assigned_specialist_id"] == "spec-1"


def test_occ_correction_stale_version_rejected(api, manager_headers):
    """PRD §2.7: "Two write operations on a denial case are guarded by optimistic
    concurrency control: assigning (or reassigning) a specialist to a denial, and correcting
    intake fields on a denial."
    PRD §2.7: "If the denial's current `version` no longer matches the supplied value —
    because a triage, an earlier assignment, a prior correction, or a cascaded update has
    advanced the version since the client last read the denial — the write is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_correction_stale_version_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2603")
    pre_triage_version = denial["version"]
    triage_denial(denial["id"])
    resp = api.correct_denial_case(
        denial["id"],
        correction_payload(pre_triage_version, denied_amount_cents=150000),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_denial_case(denial["id"], manager_headers))
    assert after["denied_amount_cents"] == 250000


def test_derived_fields_recompute_on_intake_correction(api, manager_headers):
    """PRD §3.3: "A correction recomputes `open_balance_cents`, recomputes
    `next_appeal_deadline` from the level-1 schedule when the remittance date changed,
    recomputes the queue priority, appends an `INTAKE_CORRECTED` event, and increments
    `version`."
    PRD §3.2: "The dollar fields initialize with `recovered_amount_cents` and
    `written_off_cents` at zero, so `open_balance_cents` equals `denied_amount_cents`"

    Design: Corner/complexity_layers/derived_fields_recompute_on_intake_correction
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2604")
    triaged = triage_denial(denial["id"])
    corrected = validate_success(
        api.correct_denial_case(
            denial["id"],
            correction_payload(
                triaged["version"],
                denied_amount_cents=150000,
                remittance_received_date="2026-08-10",
            ),
            manager_headers,
        )
    )
    assert corrected["open_balance_cents"] == 150000
    assert corrected["next_appeal_deadline"] == "2026-10-09"  # 2026-08-10 + 60 days
    assert corrected["version"] == triaged["version"] + 1
