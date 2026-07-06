"""Recordation of transfer: optimistic concurrency, supersession, and the
depth-3 ownership cascade.

Covers Difficulty queue instance recordation_transfer_depth3 and the OCC /
supersession corner instances.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Corner — OCC on recordation create
# ==========================================================================
def test_recordation_correct_version_succeeds(api, examiner_headers):
    """PRD §2.8: "A request to record a transfer must carry expected_work_version ...
    The value must equal the current version of the Work named by work_id."
    PRD §3.4: "the work's current_owner_name is set to the new transferee_name, and
    the work's version is incremented."

    Design: Corner/cross_cutting/recordation_occ_correct_version_succeeds
    """
    work = fx.create_work()
    payload = fac.create_recordation_payload(work["id"], work["version"], transferee_name="Bob")
    rec = validate_success(api.create_recordation(payload, examiner_headers), 201)
    assert rec["status"] == "RECORDED"
    refreshed = fx.get_work(work["id"])
    assert refreshed["version"] == work["version"] + 1
    assert refreshed["current_owner_name"] == "Bob"


def test_recordation_stale_version_rejected(api, examiner_headers):
    """PRD §2.8: "If a prior transfer has already been recorded against that work
    since the client last read it ... then the client's view is stale, and the
    recordation is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/recordation_occ_stale_version_rejected
    """
    work = fx.create_work()
    stale_version = work["version"]
    fx.get_success_data(
        api.create_recordation(fac.create_recordation_payload(work["id"], stale_version, transferee_name="Bob"), examiner_headers)
    )
    # Second write still carries the original (now stale) version.
    resp = api.create_recordation(
        fac.create_recordation_payload(work["id"], stale_version, transferor_name="Bob", transferee_name="Cara"),
        examiner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_second_recordation_supersedes_prior(api, examiner_headers):
    """PRD §3.4: "any prior transfer that is still RECORDED for the same work is
    moved to SUPERSEDED, the work's current_owner_name is set to the new
    transferee_name."

    Design: Corner/state_machines/recordation_supersedes_prior
    """
    work = fx.create_work()
    rec1 = fx.get_success_data(
        api.create_recordation(fac.create_recordation_payload(work["id"], work["version"], transferee_name="Bob"), examiner_headers)
    )
    w1 = fx.get_work(work["id"])
    rec2 = validate_success(
        api.create_recordation(
            fac.create_recordation_payload(work["id"], w1["version"], transferor_name="Bob", transferee_name="Cara"),
            examiner_headers,
        ),
        201,
    )
    rec1_after = validate_success(api.get_recordation(rec1["id"], examiner_headers), 200)
    assert rec1_after["status"] == "SUPERSEDED"
    assert rec2["status"] == "RECORDED"
    assert fx.get_work(work["id"])["current_owner_name"] == "Cara"


# ==========================================================================
# Difficulty — recordation_transfer_depth3
# ==========================================================================
def test_recordation_updates_current_owner(api, examiner_headers):
    """PRD §3.4: "First (link A), any prior transfer that is still RECORDED for the
    same work is moved to SUPERSEDED, the work's current_owner_name is set to the
    new transferee_name, and the work's version is incremented."

    Design: Difficulty/transitive_cascade/recordation_transfer_depth3
    """
    work, _lic, _rs = fx.setup_license_with_draft_statement()
    current = fx.get_work(work["id"])
    payload = fac.create_recordation_payload(work["id"], current["version"], transferee_name="New Owner")
    validate_success(api.create_recordation(payload, examiner_headers), 201)
    assert fx.get_work(work["id"])["current_owner_name"] == "New Owner"


def test_recordation_moves_active_license_under_review(api, examiner_headers):
    """PRD §3.4: "Second (link B), because ownership has changed, every License on
    that work that is currently ACTIVE is moved to UNDER_REVIEW."

    Design: Difficulty/transitive_cascade/recordation_transfer_depth3
    """
    work, lic, _rs = fx.setup_license_with_draft_statement()
    current = fx.get_work(work["id"])
    payload = fac.create_recordation_payload(work["id"], current["version"], transferee_name="New Owner")
    validate_success(api.create_recordation(payload, examiner_headers), 201)
    assert fx.get_license(lic["id"])["status"] == "UNDER_REVIEW"


def test_recordation_voids_draft_statement(api, examiner_headers):
    """PRD §3.4: "Third (link C), for each license so moved, every royalty statement
    under it that is still in DRAFT is moved to VOIDED."

    Design: Difficulty/transitive_cascade/recordation_transfer_depth3
    """
    work, _lic, rs = fx.setup_license_with_draft_statement()
    current = fx.get_work(work["id"])
    payload = fac.create_recordation_payload(work["id"], current["version"], transferee_name="New Owner")
    validate_success(api.create_recordation(payload, examiner_headers), 201)
    assert fx.get_royalty_statement(rs["id"])["status"] == "VOIDED"
