"""Breadth tests for the entity surfaces: fields, defaults and the read channels.

The claims here are about what a row *is* -- which fields the caller writes, which
the server derives no matter what the caller sends, what a list's pagination meta
reports about the unpaged set, and which 404 a dangling identifier earns.
"""

import uuid

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_ACCREDITATION_NOT_APPLICABLE,
    ERR_CLIENT_NOT_FOUND,
    ERR_MATTER_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    assert_page_meta,
    assert_row_count,
    assert_utc_millis,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import accept_intake, minimal_world, set_clock
from test_helpers.test_users import program_director_headers

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"
_MISSING_CLIENT_ID = "00000000-0000-4000-8000-000000000999"
_MISSING_MATTER_ID = "00000000-0000-4000-8000-000000000777"

_ROSA = {
    "full_name": "Rosa Mena",
    "preferred_language_code": "es",
    "country_of_birth_code": "GT",
    "date_of_birth": "1990-04-11",
    "household_size": 3,
    "annual_household_income_cents": 2000000,
}
_LUIS = {
    "full_name": "Luis Paz",
    "preferred_language_code": "en",
    "country_of_birth_code": "HN",
    "date_of_birth": "1985-02-02",
    "household_size": 1,
    "annual_household_income_cents": 1000000,
}
_ANA = {
    "full_name": "Ana Diaz",
    "preferred_language_code": "ht",
    "country_of_birth_code": "HT",
    "date_of_birth": "1995-06-06",
    "household_size": 2,
    "annual_household_income_cents": 500000,
}


def _clock(api):
    """Pin the clock so every date_of_birth used here is strictly in the past."""
    set_clock(api, _CLOCK_UTC)
    return program_director_headers()


def _register(api, headers, spec, **extra):
    payload = dict(spec)
    payload.update(extra)
    return api.create_client(payload, headers=headers)


# ---------------------------------------------------------------------------
# client_create_returns_201_with_every_declared_field
# ---------------------------------------------------------------------------


def test_a_client_create_echoes_every_written_field_verbatim(api):
    """Six inputs plus the optional alien number come back exactly as supplied.

    Nothing in this payload is normalized, defaulted or reshaped: the response is
    a 201 whose data block is the row the caller described, wrapped in the object
    envelope rather than a list.

    Design: Corner/entities/client_create_returns_201_with_every_declared_field
    """
    headers = _clock(api)
    written = created(
        _register(
            api,
            headers,
            _ROSA,
            a_number="A123456789",
            confidentiality_consent_scope="FUNDER_IDENTIFIED",
        )
    )
    assert_fields(
        written,
        full_name="Rosa Mena",
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth="1990-04-11",
        household_size=3,
        annual_household_income_cents=2000000,
        a_number="A123456789",
        confidentiality_consent_scope="FUNDER_IDENTIFIED",
        status="ACTIVE",
        open_matter_count=0,
    )
    assert_common_fields(written)
    assert_fields(ok(api.get_client(written["id"], headers=headers)), id=written["id"])


# ---------------------------------------------------------------------------
# client_get_by_id_returns_stored_row_unchanged
# ---------------------------------------------------------------------------


def test_the_single_read_reports_the_same_poverty_percentage_the_create_computed(api):
    """A household of three against $20,000 is 77.76 percent, on both channels.

    The guideline is $15,080.00 plus $5,320.00 for each additional member, so
    $25,720.00 here; the quotient 77.7605... rounds half up to two places. Reading
    the row back must not recompute it into a different figure.

    Design: Corner/entities/client_get_by_id_returns_stored_row_unchanged
    """
    headers = _clock(api)
    written = created(_register(api, headers, _ROSA))
    assert_decimal_equals(written["fpl_percent"], "77.76", 2)

    read_back = ok(api.get_client(written["id"], headers=headers))
    assert_decimal_equals(read_back["fpl_percent"], "77.76", 2)
    assert_fields(
        read_back,
        household_size=3,
        annual_household_income_cents=2000000,
        open_matter_count=0,
        version=1,
    )


# ---------------------------------------------------------------------------
# clients_list_returns_pagination_meta_with_limit_and_offset
# ---------------------------------------------------------------------------


def test_a_narrow_page_still_reports_the_whole_unpaged_total(api):
    """Two rows come back out of three, and has_more is false at the last page.

    total_count counts the rows matching the filter *before* pagination, so an
    offset of 1 with a limit of 2 exhausts the set: two rows are returned and
    nothing remains beyond them.

    Design: Corner/entities/clients_list_returns_pagination_meta_with_limit_and_offset
    """
    headers = _clock(api)
    for spec in (_ROSA, _LUIS, _ANA):
        created(_register(api, headers, spec))

    items = assert_page_meta(
        api.list_clients(params={"limit": 2, "offset": 1}, headers=headers),
        limit=2,
        offset=1,
        total_count=3,
        has_more=False,
    )
    assert len(items) == 2, "a limit of 2 over three rows from offset 1 returns 2"

    first_page = assert_page_meta(
        api.list_clients(params={"limit": 2, "offset": 0}, headers=headers),
        limit=2,
        offset=0,
        total_count=3,
        has_more=True,
    )
    assert len(first_page) == 2, "the first page is full and reports more behind it"


# ---------------------------------------------------------------------------
# clients_list_filter_by_preferred_language_narrows_set
# ---------------------------------------------------------------------------


def test_a_language_filter_narrows_the_total_and_not_just_the_page(api):
    """Filtering to 'ht' leaves one row, and total_count follows the filter.

    A filter never changes the meaning of total_count -- it always reflects the
    filtered set -- so an implementation that reports the table size here is wrong
    even though the returned page is right.

    Design: Corner/entities/clients_list_filter_by_preferred_language_narrows_set
    """
    headers = _clock(api)
    created(_register(api, headers, _ROSA))
    created(_register(api, headers, _LUIS))
    ana = created(_register(api, headers, _ANA))

    matched = only_row(
        api.list_clients(params={"preferred_language_code": "ht"}, headers=headers)
    )
    assert_fields(matched, id=ana["id"], preferred_language_code="ht")
    assert_page_meta(
        api.list_clients(params={"preferred_language_code": "ht"}, headers=headers),
        total_count=1,
        has_more=False,
    )
    assert_no_rows(
        api.list_clients(params={"preferred_language_code": "pt"}, headers=headers)
    )
    assert_row_count(api.list_clients(headers=headers), 3)


# ---------------------------------------------------------------------------
# client_get_with_unknown_uuid_returns_client_not_found
# ---------------------------------------------------------------------------


def test_an_unknown_client_id_earns_the_entity_specific_404(api):
    """The client read is named explicitly, so the generic 404 is not correct here.

    The table is non-empty, which rules out an implementation that only reaches the
    specific id when it has rows to compare against.

    Design: Corner/entities/client_get_with_unknown_uuid_returns_client_not_found
    """
    headers = _clock(api)
    created(_register(api, headers, _ROSA))
    assert_error(
        api.get_client(_MISSING_CLIENT_ID, headers=headers), ERR_CLIENT_NOT_FOUND
    )
    assert_row_count(api.list_clients(headers=headers), 1)


# ---------------------------------------------------------------------------
# client_create_without_household_size_returns_validation
# ---------------------------------------------------------------------------


def test_a_missing_household_size_is_a_validation_failure_and_writes_nothing(api):
    """household_size has no default, so its absence is a shape failure.

    The rest of the payload is impeccable, which is exactly why a lenient
    implementation is tempted to substitute 1 and compute a poverty percentage from
    it; the contract requires a refusal and an empty table afterwards.

    Design: Corner/entities/client_create_without_household_size_returns_validation
    """
    headers = _clock(api)
    payload = dict(_ROSA)
    del payload["household_size"]
    assert_error(api.create_client(payload, headers=headers), ERR_VALIDATION)
    assert_no_rows(api.list_clients(headers=headers))


# ---------------------------------------------------------------------------
# client_create_omitting_consent_scope_defaults_to_program_only
# ---------------------------------------------------------------------------


def test_an_omitted_consent_scope_lands_on_the_narrowest_useful_level(api):
    """The default is PROGRAM_ONLY, which is one step below funder aggregate.

    The distinction is load-bearing rather than cosmetic: PROGRAM_ONLY suffices for
    an aggregate-only report but is suppressed at the de-identified case level, so
    defaulting the other way would silently widen every client's disclosure.

    Design: Corner/entities/client_create_omitting_consent_scope_defaults_to_program_only
    """
    headers = _clock(api)
    written = created(_register(api, headers, _ROSA))
    assert_fields(written, confidentiality_consent_scope="PROGRAM_ONLY")
    assert_null_fields(written, "a_number")
    assert_fields(
        ok(api.get_client(written["id"], headers=headers)),
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    assert_no_rows(
        api.list_clients(
            params={"confidentiality_consent_scope": "FUNDER_AGGREGATE"}, headers=headers
        )
    )
    assert_row_count(
        api.list_clients(
            params={"confidentiality_consent_scope": "PROGRAM_ONLY"}, headers=headers
        ),
        1,
    )


# ---------------------------------------------------------------------------
# client_interpreter_required_is_computed_and_ignores_supplied_value
# ---------------------------------------------------------------------------


def test_a_supplied_interpreter_flag_is_overwritten_by_the_derivation(api):
    """'ht' is not 'en', so the flag is true however emphatically false was sent.

    The field is accepted in the payload, which makes the trap concrete: echoing
    the caller's value is the natural implementation and it is wrong.

    Design: Corner/entities/client_interpreter_required_is_computed_and_ignores_supplied_value
    """
    headers = _clock(api)
    written = created(_register(api, headers, _ANA, interpreter_required=False))
    assert_fields(written, preferred_language_code="ht", interpreter_required=True)
    assert_fields(
        ok(api.get_client(written["id"], headers=headers)), interpreter_required=True
    )


# ---------------------------------------------------------------------------
# client_english_speaker_computes_interpreter_required_false
# ---------------------------------------------------------------------------


def test_an_english_speaker_is_the_one_case_that_needs_no_interpreter(api):
    """'en' is the sole value that derives false, and that flag opens a later gate.

    This is the flag that switches off the read-back requirement on declaration
    certification, so it is not merely descriptive.

    Design: Corner/entities/client_english_speaker_computes_interpreter_required_false
    """
    headers = _clock(api)
    written = created(_register(api, headers, _LUIS))
    assert_fields(written, preferred_language_code="en", interpreter_required=False)
    assert_fields(
        ok(api.get_client(written["id"], headers=headers)), interpreter_required=False
    )


# ---------------------------------------------------------------------------
# client_system_fields_are_server_minted
# ---------------------------------------------------------------------------


def test_the_identity_and_version_of_a_fresh_row_are_server_minted(api):
    """A newly registered client is at version 1 with a server-chosen identifier.

    None of the four shared fields appears in the payload, so all four are minted:
    the version starts at exactly 1 rather than 0, the identifier is a uuid the
    caller never chose, and both timestamps are real millisecond-precision instants
    read off the logical clock.

    Design: Corner/entities/client_system_fields_are_server_minted
    """
    headers = _clock(api)
    written = created(_register(api, headers, _ROSA))
    assert_common_fields(written)
    assert_fields(written, version=1, created_at=_CLOCK_UTC, updated_at=_CLOCK_UTC)
    assert_utc_millis(written["created_at"])
    assert uuid.UUID(str(written["id"])), "the identifier is a server-minted uuid"

    second = created(_register(api, headers, _LUIS))
    assert second["id"] != written["id"], "each row gets its own identifier"
    assert_fields(ok(api.get_client(written["id"], headers=headers)), version=1)


# ---------------------------------------------------------------------------
# intake_create_with_out_of_enum_case_type_returns_validation
# ---------------------------------------------------------------------------


def test_a_case_type_outside_the_enum_is_refused_after_both_ids_resolve(api):
    """Both foreign keys are good, so the only complaint left is the enum member.

    Shape is checked after identifier resolution, which means this request has
    already passed the two 404 gates by the time it fails; the refusal must not
    leave a draft screening behind.

    Design: Corner/entities/intake_create_with_out_of_enum_case_type_returns_validation
    """
    headers = _clock(api)
    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(cycle_label="FY26-H2"), headers=headers
        )
    )
    client = created(_register(api, headers, _ROSA))

    assert_error(
        api.create_intake(
            {
                "client_id": client["id"],
                "cycle_id": cycle["id"],
                "case_type": "ASYLUM_SOMETHING",
                "detained": False,
            },
            headers=headers,
        ),
        ERR_VALIDATION,
    )
    assert_no_rows(api.list_intakes(headers=headers))


# ---------------------------------------------------------------------------
# capacity_cycle_reserved_greater_than_total_returns_validation
# ---------------------------------------------------------------------------


def test_a_reservation_larger_than_the_cycle_is_refused(api):
    """Eleven reserved seats out of ten is the declared bound's failing side.

    The same error id carries every declared numeric bound, so this is not a
    bespoke capacity complaint; and no cycle may be written from a refused create.

    Design: Corner/entities/capacity_cycle_reserved_greater_than_total_returns_validation
    """
    headers = _clock(api)
    assert_error(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-BAD", total_case_slots=10, reserved_detained_slots=11
            ),
            headers=headers,
        ),
        ERR_VALIDATION,
    )
    assert_no_rows(api.list_capacity_cycles(headers=headers))


# ---------------------------------------------------------------------------
# capacity_cycle_reserved_equal_to_total_is_legal_and_zeroes_general_pool
# ---------------------------------------------------------------------------


def test_a_fully_reserved_cycle_is_legal_and_has_no_general_pool_at_all(api):
    """Three of three reserved is the bound's passing side, and the general pool is 0.

    The aggregate availability still reports the whole cycle, because the aggregate
    count subtracts consumption rather than the reservation -- so an implementation
    that conflates the two reports 0 here and refuses every later accept.

    Design: Corner/entities/capacity_cycle_reserved_equal_to_total_is_legal_and_zeroes_general_pool
    """
    headers = _clock(api)
    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-ALLRESERVED",
                total_case_slots=3,
                reserved_detained_slots=3,
            ),
            headers=headers,
        )
    )
    assert_fields(
        cycle,
        total_case_slots=3,
        reserved_detained_slots=3,
        general_slots_consumed=0,
        detained_slots_consumed=0,
        available_slot_count=3,
        waitlisted_count=0,
        capacity_posture="OPEN",
        checkpoint_epoch=1,
        last_checkpoint_utc=_CLOCK_UTC,
    )
    assert_decimal_equals(cycle["utilization_ratio"], "0.0000", 4)
    assert_null_fields(cycle, "posture_override_until_utc")
    assert_fields(
        only_row(api.list_capacity_cycles(headers=headers)),
        id=cycle["id"],
        available_slot_count=3,
    )


# ---------------------------------------------------------------------------
# evidence_item_create_against_unknown_matter_returns_matter_not_found
# ---------------------------------------------------------------------------


def test_a_dangling_matter_on_an_evidence_create_is_reported_before_the_weight(api):
    """The parent 404 precedes every bound the payload could also have broken.

    The payload here is otherwise valid, so the only observable claim is which of
    the two candidate ids comes back -- the matter-specific 404, never the generic
    one.

    Design: Corner/entities/evidence_item_create_against_unknown_matter_returns_matter_not_found
    """
    headers = _clock(api)
    assert_error(
        api.create_evidence(
            factories.evidence_payload(
                _MISSING_MATTER_ID,
                item_type="IDENTITY_DOCUMENT",
                tier="REQUIRED",
                weight_points=8,
                source_language_code="en",
                due_date="2026-09-01",
            ),
            headers=headers,
        ),
        ERR_MATTER_NOT_FOUND,
    )
    assert_no_rows(api.list_evidence(headers=headers))


# ---------------------------------------------------------------------------
# accreditation_for_staff_attorney_parent_is_not_applicable
# ---------------------------------------------------------------------------


def test_a_staff_attorney_cannot_be_the_parent_of_an_accreditation(api):
    """Both identifiers resolve, so the refusal is about the parent's type alone.

    An attorney's authority comes from the bar, so the accreditation surface is
    closed to them entirely rather than merely redundant -- the id is neither a 404
    nor a validation complaint.

    Design: Corner/entities/accreditation_for_staff_attorney_parent_is_not_applicable
    """
    headers = _clock(api)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                recognition_number="REC-0001", expiry_date="2030-12-31"
            ),
            headers=headers,
        )
    )
    attorney = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz", bar_number="BAR-1001"
            ),
            headers=headers,
        )
    )
    assert_error(
        api.create_accreditation(
            factories.accreditation_payload(
                attorney["id"],
                recognition["id"],
                accreditation_type="FULL",
                requested_forums=["USCIS"],
            ),
            headers=headers,
        ),
        ERR_ACCREDITATION_NOT_APPLICABLE,
    )
    assert_no_rows(api.list_accreditations(headers=headers))
    assert_fields(
        ok(api.get_representative(attorney["id"], headers=headers)),
        authorization_status="AUTHORIZED_ATTORNEY",
    )


# ---------------------------------------------------------------------------
# case_assignment_junction_is_queryable_from_both_endpoints_of_the_graph
# ---------------------------------------------------------------------------


def test_the_assignment_junction_is_reachable_from_either_of_its_two_edges(api):
    """One representative across two matters: two rows by rep, one row by matter.

    The assignment row is the only join between a representative and a matter, and
    both of its foreign keys are declared filters -- so the same two rows must be
    reachable from either direction, with the totals disagreeing precisely because
    the filters do.

    Design: Corner/entities/case_assignment_junction_is_queryable_from_both_endpoints_of_the_graph
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    client = created(
        api.create_client(
            dict(_ROSA, confidentiality_consent_scope="FUNDER_IDENTIFIED"),
            headers=env.director,
        )
    )
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz", bar_number="BAR-1001"
            ),
            headers=env.director,
        )
    )

    first = accept_intake(env, client["id"], case_type="U_VISA", detained=False)
    second = accept_intake(
        env, client["id"], case_type="ADJUSTMENT_OF_STATUS", detained=False
    )
    assert first["id"] != second["id"], "two acceptances mint two distinct matters"

    leads = []
    for matter in (first, second):
        leads.append(
            created(
                api.create_assignment(
                    factories.assignment_payload(
                        matter["id"],
                        ada["id"],
                        env.matter_version(matter["id"]),
                        role_on_case="LEAD",
                    ),
                    headers=env.supervisor,
                )
            )
        )

    by_representative = assert_page_meta(
        api.list_assignments(
            params={"representative_id": ada["id"]}, headers=env.director
        ),
        total_count=2,
        has_more=False,
    )
    assert set(row["id"] for row in by_representative) == set(
        lead["id"] for lead in leads
    ), "both edges of the junction belong to the one representative"

    by_matter = only_row(
        api.list_assignments(params={"matter_id": second["id"]}, headers=env.director)
    )
    assert_fields(
        by_matter,
        id=leads[1]["id"],
        matter_id=second["id"],
        representative_id=ada["id"],
        role_on_case="LEAD",
        status="PROPOSED",
    )
    assert_fields(env.assignment(leads[0]["id"]), status="PROPOSED")
    assert_fields(
        env.representative(ada["id"]), active_case_load=0, supervisee_count=0
    )
