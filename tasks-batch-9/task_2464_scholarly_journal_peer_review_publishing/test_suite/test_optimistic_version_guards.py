"""The three version-guarded writes: a stale read is refused, and the re-read retry succeeds."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client

FIRST_SLOT = ("2026-08-10", "2026-08-12")
SECOND_SLOT = ("2026-08-20", "2026-08-22")


def _assignment_request(manuscript_id, editor_id, expected_version, chief_headers):
    return api_client.create_editor_assignment(
        f.editor_assignment_payload(
            manuscript_id, expected_version, editor_id=editor_id
        ),
        chief_headers,
    )


def _invoice_request(manuscript_id, expected_version):
    return api_client.create_apc_invoice(
        manuscript_id,
        f.apc_invoice_payload(expected_version),
        PRODUCTION_STAFF_HEADERS,
    )


def _slot_request(job_id, slot, expected_version):
    return api_client.book_typeset_slot(
        job_id,
        f.typeset_slot_payload(slot[0], slot[1], expected_version),
        PRODUCTION_STAFF_HEADERS,
    )


def _change_license(manuscript_id, author_headers, oa_license):
    return get_success_data(
        api_client.change_licensing(
            manuscript_id, f.licensing_payload(oa_license), author_headers
        )
    )


def _setup_screened_after_read():
    """A `SUBMITTED` manuscript read before a screening bumped its `version`."""
    world = fx.setup_submitted_manuscript()
    world["stale_version"] = fx.get_manuscript_version(world["manuscript"]["id"])
    fx.file_plagiarism_screening(world["manuscript"]["id"], 5.0)
    return world


def _setup_relicensed_after_read():
    """An `IN_PRODUCTION` manuscript read before the author downgraded its licence."""
    world = fx.setup_in_production()
    world["stale_version"] = fx.get_manuscript_version(world["manuscript"]["id"])
    _change_license(
        world["manuscript"]["id"], world["author_headers"], "CC_BY_NC_ND"
    )
    return world


def test_assignment_written_against_a_pre_screening_version_is_refused():
    """The screening moved the manuscript under the chief's feet, so nothing is created.

    PRD: "A second assignment on the same manuscript legitimately supersedes an earlier `PROPOSED` one, so nothing in the assignment state machine refuses it; if `expected_manuscript_version` does not equal the manuscript's current `version` — because an integrity screening changed `integrity_status`, or a recusal cascade rewired the handling editor, since the client last read it — the create is rejected with `ERR_STALE_MANUSCRIPT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/editor_assignment_with_a_stale_manuscript_version_rejected
    """
    world = _setup_screened_after_read()

    response = _assignment_request(
        world["manuscript"]["id"],
        world["handling"]["id"],
        world["stale_version"],
        world["chief_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_MANUSCRIPT_VERSION.value, expected_status=412
    )
    assert fx.list_assignments(world["manuscript"]["id"]) == []
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 0


def test_assignment_retried_with_the_re_read_version_is_created():
    """The identical request carrying the current `version` is accepted.

    PRD: "Either way the assignment is born at `PROPOSED`, the named editor's `active_assignment_count` rises by 1, and the manuscript's `version` advances by 1."

    Design: Corner/cross_cutting_complexity_layers/editor_assignment_with_a_stale_manuscript_version_rejected
    """
    world = _setup_screened_after_read()
    manuscript_id = world["manuscript"]["id"]
    _assignment_request(
        manuscript_id,
        world["handling"]["id"],
        world["stale_version"],
        world["chief_headers"],
    )

    fresh_version = fx.get_manuscript_version(manuscript_id)
    assert fresh_version != world["stale_version"]
    assignment = validate_success(
        _assignment_request(
            manuscript_id,
            world["handling"]["id"],
            fresh_version,
            world["chief_headers"],
        ),
        expected_status=201,
    )

    a.assert_fields(
        assignment,
        state="PROPOSED",
        editor_id=world["handling"]["id"],
        selected_by="EXPLICIT",
    )
    assert fx.get_editor(world["handling"]["id"])["active_assignment_count"] == 1
    assert fx.get_manuscript(manuscript_id)["integrity_status"] == "PASS"


def test_invoice_written_against_a_pre_licence_change_version_is_refused():
    """The licence change invalidates the fees desk's reading, so no invoice is priced.

    PRD: "Re-issuing after a cancelled invoice is a legitimate operation, so the invoice state machine does not refuse a second issue; the version guard is what stops an invoice being priced from an outdated view of the manuscript's licence, page count or author waiver band."

    Design: Corner/cross_cutting_complexity_layers/apc_invoice_issue_with_a_stale_manuscript_version_rejected
    """
    world = _setup_relicensed_after_read()

    response = _invoice_request(world["manuscript"]["id"], world["stale_version"])

    validate_error(
        response, ApiErrorId.ERR_STALE_MANUSCRIPT_VERSION.value, expected_status=412
    )
    assert fx.list_invoices(world["manuscript"]["id"]) == []
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]), apc_receivable_cents=0
    )


def test_invoice_retried_with_the_re_read_version_prices_the_new_licence():
    """The retry freezes the licence the author actually holds, at 85 per cent of list.

    PRD: "The multipliers are 1.00 for `CC_BY`, 0.90 for `CC_BY_NC`, 0.85 for `CC_BY_NC_ND` and 0.00 for `GREEN_SELF_ARCHIVE` — the green self-archiving route carries no article processing charge at all."

    Design: Corner/cross_cutting_complexity_layers/apc_invoice_issue_with_a_stale_manuscript_version_rejected
    """
    world = _setup_relicensed_after_read()
    manuscript_id = world["manuscript"]["id"]
    _invoice_request(manuscript_id, world["stale_version"])

    invoice = validate_success(
        _invoice_request(manuscript_id, fx.get_manuscript_version(manuscript_id)),
        expected_status=201,
    )

    a.assert_invoice_amounts(
        invoice,
        license_at_issue="CC_BY_NC_ND",
        base_cents=153000,
        net_apc_cents=153000,
        provisional_total_cents=153000,
        surcharge_relief_pct=10,
        surcharge_cents=0,
        total_due_cents=153000,
        status="ISSUED",
    )
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]), apc_receivable_cents=153000
    )
    assert len(fx.list_invoices(manuscript_id)) == 1


def test_rebooking_against_the_pre_booking_job_version_is_refused():
    """The first booking raised the job's `version`, so replaying the old one is stale.

    PRD: "A mismatch with the job's current `version` is rejected with `ERR_STALE_PRODUCTION_JOB_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/typeset_slot_rebooking_with_a_stale_job_version_rejected
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    stale_version = world["job"]["version"]
    fx.book_typeset_slot(job_id, FIRST_SLOT[0], FIRST_SLOT[1], version=stale_version)

    response = _slot_request(job_id, SECOND_SLOT, stale_version)

    error = validate_error(
        response,
        ApiErrorId.ERR_STALE_PRODUCTION_JOB_VERSION.value,
        expected_status=412,
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_MANUSCRIPT_VERSION.value, (
        "slot booking is guarded by the production job's version, not the manuscript's"
    )
    job = fx.get_production_job(job_id)
    a.assert_fields(job, slot_start=FIRST_SLOT[0], slot_end=FIRST_SLOT[1])


def test_rebooking_with_the_re_read_job_version_moves_the_slot():
    """Rebooking is legitimate at `COPYEDITING`; only the guard separated the two attempts.

    PRD: "A successful booking stores `slot_start` and `slot_end` and advances the job's `version` by 1; rebooking is permitted while the content dimension is at `COPYEDITING` or `TYPESETTING`, subject to the same version guard."

    Design: Corner/cross_cutting_complexity_layers/typeset_slot_rebooking_with_a_stale_job_version_rejected
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    booked = fx.book_typeset_slot(
        job_id, FIRST_SLOT[0], FIRST_SLOT[1], version=world["job"]["version"]
    )
    _slot_request(job_id, SECOND_SLOT, world["job"]["version"])

    rebooked = validate_success(_slot_request(job_id, SECOND_SLOT, booked["version"]))

    a.assert_fields(rebooked, slot_start=SECOND_SLOT[0], slot_end=SECOND_SLOT[1])
    a.assert_production_stages(rebooked, "COPYEDITING", "LICENSE_PENDING")
    assert rebooked["version"] == booked["version"] + 1
