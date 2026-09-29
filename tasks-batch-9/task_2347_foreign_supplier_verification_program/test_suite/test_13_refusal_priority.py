"""Requests that break two rules at once, where only the earlier rung may answer.

Each scenario is arranged so the natural implementation order returns the wrong
error, which is the whole point of asserting the winner and the loser together.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_errors as err
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_pair_dimensions, assert_supplier_performance
from test_helpers.factories import (
    activity_payload,
    attestation_payload,
    entry_submission_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    make_qualified_individual_headers,
)


# --- Blocked eligibility outranks a mismatched identifier -------------------
def _blocked_by_revoked_exemption(api: ApiClient) -> SimpleNamespace:
    """A juice pair that reached eligibility by exemption and then lost it."""
    world = fx.exempt_program(api, exemption_type="JUICE_HACCP_CONTROL")
    fx.determine_exemption(
        api,
        world.pair_id,
        "REVOKE",
        determination_note="Processor lost its juice HACCP coverage, so the exemption no longer holds",
    )
    return world


WRONG_IDENTIFIERS = dict(
    entry_number="ENT2026777",
    entry_line_number=1,
    dnb_number_submitted="999999999",
    ufi_submitted="UFI-WRONG-9999",
    arrival_date="2026-09-20T00:00:00Z",
)


def test_blocked_pair_is_reported_before_the_transmitted_identifiers_are_compared(
    api: ApiClient,
) -> None:
    """The eligibility gate is the first of the four and answers alone.

    "Four compliance gates stand between a filing and an accepted line, and they
    run in a fixed order. First the combination's `entry_eligibility_status` must
    be `ELIGIBLE`; a `PENDING` or `BLOCKED` combination is refused with
    `ERR_PAIR_ENTRY_BLOCKED`." Only "Last of all, the identifiers must match".

    Design: Difficulty/priority_pair_validation_conflict/entry_blocked_masks_identifier_mismatch_on_entry_filing
    """
    world = _blocked_by_revoked_exemption(api)

    response = api.create_entry_submission(
        entry_submission_payload(world.pair_id, **WRONG_IDENTIFIERS),
        ENTRY_FILER_HEADERS,
    )

    error = validate_error(response, err.ERR_PAIR_ENTRY_BLOCKED)
    assert error["error_id"] != err.ERR_IDENTIFIER_MISMATCH
    assert error["error_id"] != err.ERR_PAIR_VERIFICATION_INCOMPLETE


def test_refused_entry_filing_writes_no_entry_line(api: ApiClient) -> None:
    """The refusal is total: no row, and the pair keeps the state it was in.

    "Rules are evaluated in ascending priority order, the first violated rule
    determines the response, and no later rule is evaluated." Revocation had
    already moved `entry_eligibility_status` `ELIGIBLE -> BLOCKED` because
    `verification_status` offered no independent basis.

    Design: Difficulty/priority_pair_validation_conflict/entry_blocked_masks_identifier_mismatch_on_entry_filing
    """
    world = _blocked_by_revoked_exemption(api)

    api.create_entry_submission(
        entry_submission_payload(world.pair_id, **WRONG_IDENTIFIERS),
        ENTRY_FILER_HEADERS,
    )

    rows, meta = validate_paginated(
        api.list_entry_submissions(COMPLIANCE_OFFICER_HEADERS, {"pair_id": world.pair_id})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id),
        verification_status="DRAFT",
        entry_eligibility_status="BLOCKED",
        exemption_status="REVOKED",
    )


# --- Tenancy outranks the acting individual's training currency -------------
def _foreign_lapsed_individual(api: ApiClient) -> SimpleNamespace:
    """An analyzed pair at one importer, and a lapsed individual at another."""
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    second_importer = fx.create_second_importer(api)
    qi_c = fx.create_qualified_individual(
        api,
        second_importer["id"],
        full_name="Cleo Nkemdi",
        email="cleo@southbay.example",
        qualification_summary=(
            "Qualified individual for the Southbay compliance office with audit training"
        ),
        training_completed_at="2025-08-01T00:00:00Z",
    )
    fx.designate_qualified_individual(
        api,
        qi_c["id"],
        "LAPSE",
        note="Training file could not be produced during the internal audit",
    )
    world.second_importer_id = second_importer["id"]
    world.qi_c_id = qi_c["id"]
    return world


def _foreign_activity_payload(world: SimpleNamespace) -> dict:
    return activity_payload(
        world.pair_id,
        world.qi_c_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=2,
        justification_text=(
            "Semiannual sampling proposed by a qualified individual of another importer"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )


def test_cross_importer_activity_proposal_reports_scope_before_training_currency(
    api: ApiClient,
) -> None:
    """Rung 14 answers, so the lapsed designation at rung 26 is never reached.

    "14. Single-importer scope -- `ERR_IMPORTER_SCOPE_MISMATCH` (409), on
    combination create, activity create, activity revision and hazard-analysis
    create." The training-currency rule sits far below it: "26. The acting
    qualified individual has `status` equal to `ACTIVE` and `training_valid_until`
    at or after the logical clock".

    Design: Difficulty/priority_pair_validation_conflict/importer_scope_mismatch_masks_lapsed_qi_on_activity_create
    """
    world = _foreign_lapsed_individual(api)

    response = api.create_verification_activity(
        _foreign_activity_payload(world),
        make_qualified_individual_headers(world.qi_c_id),
    )

    error = validate_error(response, err.ERR_IMPORTER_SCOPE_MISMATCH)
    assert error["error_id"] != err.ERR_QI_DESIGNATION_INVALID


def test_cross_importer_activity_proposal_creates_no_activity(api: ApiClient) -> None:
    """A refusal at the scope rung leaves the other importer's plan empty.

    "The importer is the tenancy boundary." On activity create "the
    `assigned_qi_id` must belong to the combination's importer, and the
    combination's importer must match the acting qualified individual's own
    importer".

    Design: Difficulty/priority_pair_validation_conflict/importer_scope_mismatch_masks_lapsed_qi_on_activity_create
    """
    world = _foreign_lapsed_individual(api)

    api.create_verification_activity(
        _foreign_activity_payload(world),
        make_qualified_individual_headers(world.qi_c_id),
    )

    rows, meta = validate_paginated(
        api.list_verification_activities(
            COMPLIANCE_OFFICER_HEADERS, {"pair_id": world.pair_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


# --- Training currency outranks segregation of duties ----------------------
def _lapsed_submitter_with_received_record(api: ApiClient) -> SimpleNamespace:
    """The submitter of a received record, lapsed after filing it."""
    world = fx.onsite_only_program(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    world.record = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-09-12T00:00:00Z",
        performed_end="2026-09-14T00:00:00Z",
        findings_count=0,
        document_reference="AUD-2026-0912-RV",
    )
    world.record_id = world.record["id"]
    fx.designate_qualified_individual(
        api,
        world.qi_a_id,
        "LAPSE",
        note="Training certificate expired during the internal program review",
    )
    return world


def test_lapsed_attester_is_reported_before_the_self_attestation(
    api: ApiClient,
) -> None:
    """Rung 26 wins over rung 43 even though self-attestation is the louder fault.

    "the record must be `RECEIVED` (otherwise `ERR_RECORD_NOT_ATTESTABLE`), the
    attester must be `ACTIVE` with current training (otherwise
    `ERR_QI_DESIGNATION_INVALID`), and the attester's `X-User-ID` must differ from
    the record's `submitted_by_qi_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)" --
    and the ladder places rung 26 above rung "43. Segregation of duties".

    Design: Difficulty/priority_pair_validation_conflict/lapsed_qi_masks_segregation_of_duties_on_attestation
    """
    world = _lapsed_submitter_with_received_record(api)

    response = api.post_record_attestation(
        world.record_id,
        attestation_payload(
            attestation_note="Self-attestation attempted by the submitting qualified individual"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )

    error = validate_error(response, err.ERR_QI_DESIGNATION_INVALID)
    assert error["error_id"] != err.ERR_SEGREGATION_OF_DUTIES


def test_refused_attestation_admits_nothing_into_the_final_score(
    api: ApiClient,
) -> None:
    """The record stays received, so the final variant still has no input at all.

    "If the weight total is 0.00 the score is exactly 100.00 -- no evidence is not
    bad evidence". The FINAL variant "takes only records whose `record_status` is
    `ATTESTED`", and the refused attestation left the record where it was.

    Design: Difficulty/priority_pair_validation_conflict/lapsed_qi_masks_segregation_of_duties_on_attestation
    """
    world = _lapsed_submitter_with_received_record(api)

    api.post_record_attestation(
        world.record_id,
        attestation_payload(
            attestation_note="Self-attestation attempted by the submitting qualified individual"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )

    assert fx.get_record(api, world.record_id)["record_status"] == "RECEIVED"
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id), final=100.00, weight_total=0.00
    )
