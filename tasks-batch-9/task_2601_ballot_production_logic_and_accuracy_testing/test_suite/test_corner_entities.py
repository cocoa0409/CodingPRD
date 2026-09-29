"""Resource-shape rules of the ballot production service.

These tests cover what a freshly created row looks like: the inputs a creation
call echoes, the defaults it applies when an optional key is omitted, the
statutory quantities the server computes for it, the identity, timestamp and
version fields every resource carries, the schema floor that refuses a
malformed payload, the pagination envelope of a list read, the parent lookup
that refuses an orphan, and the append-only custody ledger that is written only
as a side effect and never edited.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# An election_date expressed as a full UTC instant, as PRD section 2.4 requires
# of every client-supplied temporal value.
ELECTION_INSTANT = "2026-11-03T00:00:00Z"
MISSING_ELECTION_ID = "00000000-0000-0000-0000-0000000000ff"


# ---- A newly registered election ----

def test_en_election_creation_mints_identity_and_echoes_inputs(client):
    """Registering an election mints a UUID id, stamps created_at from the logical clock,
    starts version at 1 and echoes the six supplied inputs.

    PRD Section 2.4: "Every resource carries a server-minted `id` — a UUID string with no type prefix, never supplied by the client — and a `created_at` timestamp: an ISO 8601 UTC instant with exactly three fractional-second digits, read from the logical clock at creation."

    Design: Corner/entities/en_election_creation_returns_declared_initial_ledger_fields
    """
    fx.set_clock(client, c.CLOCK_START)

    payload = f.election_payload(
        name="Special District Election",
        jurisdiction=c.JURISDICTION,
        election_date="2027-03-02T00:00:00Z",
        rotation_policy=c.ROTATION_DISTRICT,
        candidate_order_method=c.ORDER_FILING,
        la_notice_hours=72,
    )
    election = validate_success(client.create_election(payload, users.DIRECTOR),
                               expected_status=201)

    assert is_valid_uuid(election["id"]), f"election id must be a UUID, got {election['id']!r}"
    a.assert_millisecond_timestamp(election["created_at"], "election.created_at")
    assert a.parse_instant(election["created_at"]) == a.parse_instant(c.CLOCK_START), (
        f"created_at must read the logical clock instant {c.CLOCK_START}, "
        f"got {election['created_at']!r}"
    )
    assert election["version"] == 1, (
        f"a freshly created election must carry version 1, got {election['version']!r}"
    )
    a.assert_fields_equal(
        election,
        {
            "name": "Special District Election",
            "jurisdiction": c.JURISDICTION,
            "rotation_policy": c.ROTATION_DISTRICT,
            "candidate_order_method": c.ORDER_FILING,
            "la_notice_hours": 72,
        },
        "election",
    )
    assert a.parse_instant(election["election_date"]) == a.parse_instant("2027-03-02T00:00:00Z"), (
        f"election_date must echo the supplied instant, got {election['election_date']!r}"
    )


def test_en_election_creation_derived_ledger_fields_at_rest(client):
    """A new election exposes every derived ledger field at its declared initial value in
    the creation response itself.

    PRD Section 3.1: "A new election lands in `SETUP` with every derived figure at rest: `certified_contest_count` 0, `committed_print_cents` 0, `deployment_readiness` `BLOCKED`, `open_seal_count` 0, `total_ballots_received` 0, `total_ballots_issued` 0, `ballot_accountability_status` `PENDING`, `net_ballot_variance` 0, and both `reconciliation_basis` and `last_reconciled_at` null."

    Design: Corner/entities/en_election_creation_returns_declared_initial_ledger_fields
    """
    fx.set_clock(client, c.CLOCK_START)

    payload = f.election_payload(
        name="Special District Election",
        election_date="2027-03-02T00:00:00Z",
        rotation_policy=c.ROTATION_DISTRICT,
        candidate_order_method=c.ORDER_FILING,
        la_notice_hours=72,
    )
    election = validate_success(client.create_election(payload, users.DIRECTOR),
                               expected_status=201)

    a.assert_fields_equal(
        election,
        {
            "status": c.PHASE_SETUP,
            "certified_contest_count": 0,
            "committed_print_cents": 0,
            "deployment_readiness": c.READINESS_BLOCKED,
            "open_seal_count": 0,
            "total_ballots_received": 0,
            "total_ballots_issued": 0,
            "ballot_accountability_status": c.ACCOUNTABILITY_PENDING,
            "net_ballot_variance": 0,
            "reconciliation_basis": None,
            "last_reconciled_at": None,
        },
        "election",
    )


# ---- Declared defaults for omitted optional inputs ----

def test_en_election_optional_inputs_take_declared_defaults(client):
    """Omitting rotation_policy, candidate_order_method and la_notice_hours yields NONE,
    ALPHABETICAL_BY_BALLOT_NAME and 48.

    PRD Section 3.1: "Three further inputs are optional and carry defaults that matter downstream: `rotation_policy`, one of `NONE`, `PRECINCT_ROTATION` or `DISTRICT_ROTATION`, defaulting to `NONE`; `candidate_order_method`, either `ALPHABETICAL_BY_BALLOT_NAME` or `FILING_ORDER`, defaulting to `ALPHABETICAL_BY_BALLOT_NAME`; and `la_notice_hours`, the minimum whole hours of public notice required before a logic-and-accuracy session may open, which must be at least 1 and defaults to 48."

    Design: Corner/entities/en_election_defaults_applied_when_optional_inputs_omitted
    """
    fx.set_clock(client, c.CLOCK_START)

    payload = f.election_payload(name="Default Probe Election", election_date=ELECTION_INSTANT)
    payload.pop("rotation_policy")
    payload.pop("candidate_order_method")
    payload.pop("la_notice_hours")

    election = validate_success(client.create_election(payload, users.DIRECTOR),
                               expected_status=201)

    a.assert_fields_equal(
        election,
        {
            "rotation_policy": c.ROTATION_NONE,
            "candidate_order_method": c.ORDER_ALPHABETICAL,
            "la_notice_hours": 48,
        },
        "election",
    )


def test_en_contest_vendor_and_unit_defaults_applied_when_omitted(client):
    """A vendor registered without a status is ACTIVE with both of its rolling figures at
    zero, while an omitted contest rotation flag, candidate party and unit firmware stay at
    their declared resting values.

    PRD Section 3.6: "Vendors are registered by an `ElectionsDirector` with a legal `name`, a `press_line_count` of at least 1 (the aggregate number of jobs the vendor can run at any one instant), a `certified_secure` flag stating whether the vendor currently holds a secure-facility certification, and optionally a `status` of `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`."

    Design: Corner/entities/en_election_defaults_applied_when_optional_inputs_omitted
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)

    contest_payload = f.contest_payload("County Clerk", district_code=c.DISTRICT_D07)
    contest_payload.pop("rotation_required")
    contest = validate_success(
        client.create_contest(sc.election_id, contest_payload, users.COORDINATOR),
        expected_status=201)

    candidate_payload = f.candidate_payload("Bea Brooks", "Brooks", "2026-06-02T09:00:00Z")
    candidate_payload.pop("party_code")
    candidate = validate_success(
        client.create_candidate(contest["id"], candidate_payload, users.COORDINATOR),
        expected_status=201)

    vendor_payload = f.print_vendor_payload(name="Larkspur Press", press_line_count=1)
    vendor_payload.pop("status")
    vendor = validate_success(client.create_print_vendor(vendor_payload, users.DIRECTOR),
                              expected_status=201)

    unit_payload = f.tabulator_payload("TAB-D01")
    unit_payload.pop("firmware_version")
    unit = validate_success(
        client.create_tabulator(sc.election_id, unit_payload, users.TECHNICIAN),
        expected_status=201)

    a.assert_fields_equal(
        vendor,
        {
            "status": c.VENDOR_ACTIVE,
            "quality_defect_rate_bp": 0,
            "active_job_count": 0,
        },
        "print vendor",
    )
    a.assert_fields_equal(
        contest,
        {
            "rotation_required": False,
            "status": c.CONTEST_DRAFT,
            "ballot_order_index": None,
        },
        "contest",
    )
    a.assert_fields_equal(candidate, {"status": c.CANDIDATE_FILED}, "candidate")
    assert candidate.get("party_code") is None, (
        f"an omitted party_code must stay null, got {candidate.get('party_code')!r}"
    )
    a.assert_fields_equal(
        unit,
        {
            "program_status": c.UNIT_UNPROGRAMMED,
            "custody_status": c.CUSTODY_IN_VAULT,
        },
        "tabulator",
    )
    assert unit.get("firmware_version") is None, (
        f"an omitted firmware_version must stay null, got {unit.get('firmware_version')!r}"
    )


# ---- The schema floor on required fields, enums and numeric bounds ----

def test_en_missing_required_fields_rejected_and_nothing_written(client):
    """An absent required field on four different writes is refused with ERR_INVALID_REQUEST
    and leaves no row behind.

    PRD Section 2.6: "A schema violation at rank 30 covers: a required field absent or null; a field of the wrong JSON type; an enum field carrying a value outside its declared set; a count, quantity or money field that is negative where its definition requires zero or more, or below one where its definition requires at least one; a window whose end is less than or equal to its start; a timestamp that is not an ISO 8601 UTC instant; a reported defect count larger than the sample size it was drawn from; and a delivery manifest that is empty or repeats a `lot_code`."

    Design: Corner/entities/en_missing_required_fields_returns_invalid_request
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    contest_id = fx.add_contest(sc)
    fx.add_candidate(sc)

    election_payload = f.election_payload(election_date=ELECTION_INSTANT)
    election_payload.pop("name")
    validate_error(client.create_election(election_payload, users.DIRECTOR),
                   errors.ERR_INVALID_REQUEST)

    vendor_payload = f.print_vendor_payload(name="Nameless Press")
    vendor_payload.pop("press_line_count")
    validate_error(client.create_print_vendor(vendor_payload, users.DIRECTOR),
                   errors.ERR_INVALID_REQUEST)

    precinct_payload = f.precinct_payload("P-900", registered_voter_count=10)
    precinct_payload.pop("polling_place")
    validate_error(
        client.create_precinct(sc.election_id, precinct_payload, users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(client.withdraw_contest(contest_id, {}, users.DIRECTOR),
                   errors.ERR_INVALID_REQUEST)

    contests, contest_meta = validate_paginated(
        client.list_contests(sc.election_id, users.DIRECTOR))
    assert contest_meta["total_count"] == 1, (
        f"the election must still hold exactly one contest, got {contest_meta['total_count']}"
    )
    a.assert_fields_equal(
        contests[0],
        {"status": c.CONTEST_DRAFT, "withdrawn_reason": None},
        "contest",
    )

    precincts, precinct_meta = validate_paginated(
        client.list_precincts(users.DIRECTOR, {"election_id": sc.election_id}))
    assert precincts == [], f"the rejected precinct must not exist, got {precincts!r}"
    assert precinct_meta["total_count"] == 0, (
        f"the rejected precinct must not be counted, got {precinct_meta['total_count']}"
    )


def test_en_out_of_set_enums_and_below_floor_counts_rejected(client):
    """An enum value outside its declared set and a count below its declared floor are both
    refused with ERR_INVALID_REQUEST.

    PRD Section 2.6: "A schema violation at rank 30 covers: a required field absent or null; a field of the wrong JSON type; an enum field carrying a value outside its declared set; a count, quantity or money field that is negative where its definition requires zero or more, or below one where its definition requires at least one; a window whose end is less than or equal to its start; a timestamp that is not an ISO 8601 UTC instant; a reported defect count larger than the sample size it was drawn from; and a delivery manifest that is empty or repeats a `lot_code`."

    Design: Corner/entities/en_field_constraints_reject_invalid_enum_and_out_of_range_values
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    fx.add_contest(sc)

    validate_error(
        client.create_election(
            f.election_payload(name="Bad Rotation", election_date=ELECTION_INSTANT,
                               rotation_policy="MONTHLY_ROTATION"),
            users.DIRECTOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(
        client.create_election(
            f.election_payload(name="Bad Notice", election_date=ELECTION_INSTANT,
                               la_notice_hours=0),
            users.DIRECTOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(
        client.create_contest(
            sc.election_id,
            f.contest_payload("Ballot Question 1", contest_type="REFERENDUM"),
            users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(
        client.create_contest(
            sc.election_id,
            f.contest_payload("Zero Seat Race", seats_open=0),
            users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload("P-901", registered_voter_count=-5,
                               polling_place="Nowhere"),
            users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)


def test_en_style_language_and_format_membership_enforced(client):
    """A language_set without EN and a required_formats without PAPER_STANDARD are both
    refused, and neither rejected style exists afterwards.

    PRD Section 3.3: "A style declares a `style_code` unique within the election, a non-empty and de-duplicated `district_codes` set naming the district combination it prints, a non-empty `language_set` of language codes that must be produced and must include `"EN"`, and a non-empty `required_formats` array that must include `"PAPER_STANDARD"` and whose members are drawn from the five recognized formats `"PAPER_STANDARD"`, `"LARGE_PRINT"`, `"AUDIO_BALLOT"`, `"BRAILLE_INDEX"` and `"ELECTRONIC_DISPLAY"`."

    Design: Corner/entities/en_field_constraints_reject_invalid_enum_and_out_of_range_values
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)

    validate_error(
        client.create_ballot_style(
            sc.election_id,
            f.ballot_style_payload("S-900", language_set=[c.LANGUAGE_ES]),
            users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)

    validate_error(
        client.create_ballot_style(
            sc.election_id,
            f.ballot_style_payload("S-901", required_formats=[c.FORMAT_LARGE_PRINT]),
            users.COORDINATOR),
        errors.ERR_INVALID_REQUEST)

    styles, meta = validate_paginated(
        client.list_ballot_styles(users.COORDINATOR, {"election_id": sc.election_id}))
    assert styles == [], f"neither rejected style may exist, got {styles!r}"
    assert meta["total_count"] == 0, (
        f"neither rejected style may be counted, got {meta['total_count']}"
    )


def test_en_system_and_computed_fields_in_payload_are_ignored(client):
    """Client-supplied id, status, version, counters and created_at are ignored rather than
    rejected, and the server-generated values win.

    PRD Section 2.6: "Unknown extra fields are **not** a schema violation — they are ignored, and the response echoes only declared fields."

    Design: Corner/entities/en_system_and_computed_fields_input_ignored
    """
    fx.set_clock(client, c.CLOCK_START)

    payload = f.election_payload(
        name="Smuggled Fields",
        election_date=ELECTION_INSTANT,
        id="00000000-0000-0000-0000-000000000099",
        status=c.PHASE_RECONCILED,
        version=77,
        certified_contest_count=42,
        committed_print_cents=999999,
        created_at="1999-01-01T00:00:00Z",
    )
    election = validate_success(client.create_election(payload, users.DIRECTOR),
                               expected_status=201)

    assert election["id"] != "00000000-0000-0000-0000-000000000099", (
        "the election id must be server-minted, not the value the client smuggled in"
    )
    assert is_valid_uuid(election["id"]), f"election id must be a UUID, got {election['id']!r}"
    a.assert_fields_equal(
        election,
        {
            "status": c.PHASE_SETUP,
            "version": 1,
            "certified_contest_count": 0,
            "committed_print_cents": 0,
        },
        "election",
    )
    assert a.parse_instant(election["created_at"]) == a.parse_instant(c.CLOCK_START), (
        f"created_at must read the logical clock, got {election['created_at']!r}"
    )


# ---- The statutory ballot requirement of a precinct ----

def test_en_precinct_required_ballot_quantity_rounds_up(client):
    """Registration derives required_ballot_quantity as the voter count times 11 divided by
    10 rounded up: 100 gives 110, 9 gives 10, 1750 gives 1925 and 0 gives 0.

    PRD Section 3.3: "Registration derives the precinct's statutory print requirement immediately: `required_ballot_quantity` is the registered voter count multiplied by 11 and divided by 10 — the statutory 110 percent floor — rounded **up** to the next whole ballot, so the floor is never undershot."

    Design: Corner/entities/en_precinct_required_ballot_quantity_computed_from_registered_voters
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)

    first = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload("P-001", [c.DISTRICT_D12], 100, c.POLLING_PLACE_1),
            users.COORDINATOR),
        expected_status=201)
    second = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload("P-002", [c.DISTRICT_D12], 9, "Grange Annex"),
            users.COORDINATOR),
        expected_status=201)
    third = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload("P-003", [c.DISTRICT_D07, c.DISTRICT_D12], 1750,
                               "Civic Center"),
            users.COORDINATOR),
        expected_status=201)
    fourth = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload("P-004", [c.DISTRICT_D19], 0, "Vacant Township Hall"),
            users.COORDINATOR),
        expected_status=201)

    a.assert_fields_equal(first, {"required_ballot_quantity": 110}, "precinct P-001")
    a.assert_fields_equal(second, {"required_ballot_quantity": 10}, "precinct P-002")
    a.assert_fields_equal(third, {"required_ballot_quantity": 1925}, "precinct P-003")
    a.assert_fields_equal(fourth, {"required_ballot_quantity": 0}, "precinct P-004")
    assert sorted(third["district_codes"]) == [c.DISTRICT_D07, c.DISTRICT_D12], (
        f"the submitted district set must be echoed, got {third['district_codes']!r}"
    )


def test_en_new_precinct_starts_not_ready_and_blocks_election_readiness(client):
    """Every freshly registered precinct is unassigned, holds no ballots and is NOT_READY, so
    the election's readiness stays BLOCKED.

    PRD Section 3.3: "A newly registered precinct has `assigned_style_id` null, `ballots_received` 0 and `deployment_status` `NOT_READY`, and its arrival forces a recomputation of the election's `deployment_readiness`, which a fresh `NOT_READY` precinct can only block."

    Design: Corner/entities/en_precinct_required_ballot_quantity_computed_from_registered_voters
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)

    created = [
        validate_success(
            client.create_precinct(
                sc.election_id,
                f.precinct_payload(code, [district], voters, place),
                users.COORDINATOR),
            expected_status=201)
        for code, district, voters, place in (
            ("P-001", c.DISTRICT_D12, 100, c.POLLING_PLACE_1),
            ("P-002", c.DISTRICT_D12, 9, "Grange Annex"),
            ("P-003", c.DISTRICT_D07, 1750, "Civic Center"),
            ("P-004", c.DISTRICT_D19, 0, "Vacant Township Hall"),
        )
    ]

    for precinct in created:
        a.assert_fields_equal(
            precinct,
            {
                "assigned_style_id": None,
                "ballots_received": 0,
                "deployment_status": c.READINESS_NOT_READY,
            },
            f"precinct {precinct.get('precinct_code')}",
        )

    election = validate_success(client.get_election(sc.election_id, users.DIRECTOR))
    a.assert_fields_equal(
        election, {"deployment_readiness": c.READINESS_BLOCKED}, "election")


# ---- Ballot style creation and the election-wide rotation seed ----

def test_en_style_creation_renumbers_rotation_seed_index(client):
    """Inserting a style whose code sorts below an existing one renumbers every
    non-superseded style of the election by style_code ascending.

    PRD Section 3.3: "`rotation_seed_index` is recomputed for **every** ballot style of the election whose status is not `SUPERSEDED`, as the zero-based rank of `style_code` ascending among that set."

    Design: Corner/entities/en_ballot_style_creation_recomputes_rotation_seed_index_across_election
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    fx.add_contest(sc)
    fx.add_candidate(sc)
    fx.certify_contest(sc)

    style_200 = validate_success(
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload("S-200", [c.DISTRICT_D12]),
            users.COORDINATOR),
        expected_status=201)
    assert style_200["rotation_seed_index"] == 0, (
        "the only non-superseded style of the election must hold seed 0, "
        f"got {style_200['rotation_seed_index']!r}"
    )

    style_100 = validate_success(
        client.create_ballot_style(
            sc.election_id,
            f.ballot_style_payload("S-100", [c.DISTRICT_D12],
                                   language_set=[c.LANGUAGE_EN, c.LANGUAGE_ES],
                                   required_formats=[c.FORMAT_PAPER_STANDARD,
                                                     c.FORMAT_LARGE_PRINT]),
            users.COORDINATOR),
        expected_status=201)
    style_300 = validate_success(
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload("S-300", [c.DISTRICT_D19]),
            users.COORDINATOR),
        expected_status=201)

    a.assert_fields_equal(style_100, {"rotation_seed_index": 0}, "style S-100")
    a.assert_fields_equal(style_300, {"rotation_seed_index": 2}, "style S-300")

    reread_200 = validate_success(client.get_ballot_style(style_200["id"], users.COORDINATOR))
    a.assert_fields_equal(reread_200, {"rotation_seed_index": 1}, "style S-200")


def test_en_style_creation_derives_contest_count_and_initial_fields(client):
    """A new style derives contest_count from the certified contests of its own districts and
    is otherwise born entirely at rest.

    PRD Section 3.3: "A new style is born in `DRAFT` with `revision` 1, `proof_cycle_count` 0, empty `translated_languages` and `certified_formats` arrays, `precinct_count` 0, both `proof_requested_by_user_id` and `proof_decided_by_user_id` null, and `contest_count` derived from the count of the election's `CERTIFIED` contests whose `district_code` falls inside the new style's district set."

    Design: Corner/entities/en_ballot_style_creation_recomputes_rotation_seed_index_across_election
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    fx.add_contest(sc)
    fx.add_candidate(sc)
    fx.certify_contest(sc)

    style_200 = validate_success(
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload("S-200", [c.DISTRICT_D12]),
            users.COORDINATOR),
        expected_status=201)
    style_100 = validate_success(
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload("S-100", [c.DISTRICT_D12]),
            users.COORDINATOR),
        expected_status=201)
    style_300 = validate_success(
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload("S-300", [c.DISTRICT_D19]),
            users.COORDINATOR),
        expected_status=201)

    a.assert_fields_equal(style_100, {"contest_count": 1}, "style S-100")
    a.assert_fields_equal(style_200, {"contest_count": 1}, "style S-200")
    a.assert_fields_equal(style_300, {"contest_count": 0}, "style S-300")

    for style in (style_100, style_200, style_300):
        a.assert_fields_equal(
            style,
            {
                "status": c.STYLE_DRAFT,
                "revision": 1,
                "proof_cycle_count": 0,
                "translated_languages": [],
                "certified_formats": [],
                "precinct_count": 0,
                "proof_requested_by_user_id": None,
                "proof_decided_by_user_id": None,
            },
            f"style {style.get('style_code')}",
        )


# ---- Reading a ballot lot's accounting line ----

def test_en_issued_lot_accounting_line_splits_received_quantity(client):
    """A single read after receipt and partial issue shows 12500 received split into 3000
    issued and 9500 unused, with the issuing custodian recorded.

    PRD Section 3.7: "On success the lot moves `RECEIVED → ISSUED`, stores `precinct_id` and `issued_quantity`, sets `unused_quantity` to the received quantity minus the issued quantity, records `issued_by_user_id` as the custodian's `X-User-ID`, appends a custody event of type `ISSUE`, and triggers the readiness chain: the precinct recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` — the sum of `issued_quantity` over its lots in `ISSUED` or `RETURNED` — and `deployment_readiness`."

    Design: Corner/entities/en_ballot_lot_retrieval_returns_stored_accounting_line
    """
    sc = fx.issued_lot(client, registered_voter_count=100, issue_quantity=3000,
                       election_overrides={"election_date": ELECTION_INSTANT})

    lot = validate_success(client.get_ballot_lot(sc.lot_id, users.CUSTODIAN))

    a.assert_fields_equal(
        lot,
        {
            "custody_state": c.LOT_ISSUED,
            "lot_code": c.LOT_CODE_1,
            "seal_number": c.SEAL_1,
            "quantity_shipped": 12500,
            "quantity_received": 12500,
            "issued_quantity": 3000,
            "unused_quantity": 9500,
            "election_id": sc.election_id,
            "print_job_id": sc.job_id,
            "precinct_id": sc.precinct_id,
            "issued_by_user_id": c.USER_CUSTODIAN,
        },
        "ballot lot",
    )
    a.assert_lot_conservation(lot)


def test_en_issued_lot_return_counters_zero(client):
    """An issued lot has not reported its board counts, so all three return figures and the
    accounted total are still 0.

    PRD Section 3.6: "An accepted manifest moves the job `QC_PASSED → DELIVERED` and creates one ballot lot per line, each in `IN_TRANSIT` with `lot_code`, `quantity_shipped` and `seal_number` copied from the line, `election_id` copied from the job, and every accounting figure at rest: `quantity_received` 0, `issued_quantity` 0, `unused_quantity` 0, `voted_quantity` 0, `spoiled_quantity` 0, `returned_unused_quantity` 0, `accounted_quantity` 0, `lot_variance` 0, and `precinct_id` and `issued_by_user_id` null."

    PRD Section 3.7: "On success the lot moves `ISSUED → RETURNED`, stores the three counts, sets `accounted_quantity` to their sum, and sets `lot_variance` to the issued quantity minus the accounted quantity — the lot's own missing-ballot figure, which stays null until the lot is returned."

    Design: Corner/entities/en_ballot_lot_retrieval_returns_stored_accounting_line
    """
    sc = fx.issued_lot(client, registered_voter_count=100, issue_quantity=3000,
                       election_overrides={"election_date": ELECTION_INSTANT})

    lot = validate_success(client.get_ballot_lot(sc.lot_id, users.CUSTODIAN))

    a.assert_fields_equal(
        lot,
        {
            "custody_state": c.LOT_ISSUED,
            "voted_quantity": 0,
            "spoiled_quantity": 0,
            "returned_unused_quantity": 0,
            "accounted_quantity": 0,
        },
        "ballot lot",
    )


# ---- Paging a contest list ----

def test_en_contest_list_page_walk_reports_total_count_and_has_more(client):
    """A limit-2 walk over three contests reports total_count 3 on both pages, flips has_more
    from true to false and returns two disjoint pages.

    PRD Section 2.3: "Both are echoed in the response envelope's `meta` object along with `total_count` (the number of items matching the request before the page window is applied) and `has_more` (true when items remain beyond the current window)."

    Design: Corner/entities/en_contest_listing_paginates_with_total_count_and_has_more
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    contest_a = fx.add_contest(sc, "Board of Supervisors", district_code=c.DISTRICT_D07,
                               seats_open=3, rotation_required=True)
    contest_b = fx.add_contest(sc, "County Sheriff")
    contest_c = fx.add_contest(sc, "Bond Measure A",
                               contest_type=c.CONTEST_TYPE_MEASURE,
                               district_code=c.DISTRICT_D07)

    first_rows, first_meta = validate_paginated(
        client.list_contests(sc.election_id, users.OBSERVER, {"limit": 2, "offset": 0}))
    assert len(first_rows) == 2, f"the first page must hold 2 rows, got {len(first_rows)}"
    a.assert_pagination_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)

    second_rows, second_meta = validate_paginated(
        client.list_contests(sc.election_id, users.OBSERVER, {"limit": 2, "offset": 2}))
    assert len(second_rows) == 1, f"the second page must hold 1 row, got {len(second_rows)}"
    a.assert_pagination_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)

    first_ids = a.ids_of(first_rows)
    second_ids = a.ids_of(second_rows)
    assert not set(first_ids) & set(second_ids), (
        f"the two pages must be disjoint, got {first_ids!r} and {second_ids!r}"
    )
    assert set(first_ids) | set(second_ids) == {contest_a, contest_b, contest_c}, (
        f"the walk must cover every contest exactly once, got {first_ids + second_ids!r}"
    )


def test_en_contest_list_pagination_defaults_and_status_filter(client):
    """An unparameterised contest list echoes limit 10 and offset 0, while a status filter of
    CERTIFIED matches none of the three draft contests.

    PRD Section 2.3: "`limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` is the number of items to skip and defaults to 0."

    Design: Corner/entities/en_contest_listing_paginates_with_total_count_and_has_more
    """
    sc = fx.new_election(client, election_date=ELECTION_INSTANT)
    fx.add_contest(sc, "Board of Supervisors", district_code=c.DISTRICT_D07,
                   seats_open=3, rotation_required=True)
    fx.add_contest(sc, "County Sheriff")
    fx.add_contest(sc, "Bond Measure A", contest_type=c.CONTEST_TYPE_MEASURE,
                   district_code=c.DISTRICT_D07)

    rows, meta = validate_paginated(client.list_contests(sc.election_id, users.OBSERVER))
    assert len(rows) == 3, f"the default page must hold all 3 contests, got {len(rows)}"
    a.assert_pagination_meta(meta, total_count=3, has_more=False,
                             limit=c.DEFAULT_LIMIT, offset=c.DEFAULT_OFFSET)

    filtered, filtered_meta = validate_paginated(
        client.list_contests(sc.election_id, users.OBSERVER,
                             {"status": c.CONTEST_CERTIFIED}))
    assert filtered == [], f"no contest is certified yet, got {filtered!r}"
    a.assert_pagination_meta(filtered_meta, total_count=0, has_more=False)


# ---- Creating a child under an election that does not exist ----

def test_en_child_creation_under_unknown_election_not_found(client):
    """Every election-parented collection resolves the parent id first, so an unknown election
    answers ERR_ELECTION_NOT_FOUND and creates nothing.

    PRD Section 2.7: "Where an operation addresses a resource through a parent collection, path segments are resolved strictly left to right: the parent is looked up first and its not-found error is returned before the child segment is even parsed."

    Design: Corner/entities/en_child_creation_under_unknown_election_returns_not_found
    """
    fx.set_clock(client, c.CLOCK_START)

    validate_error(
        client.create_contest(MISSING_ELECTION_ID, f.contest_payload(), users.COORDINATOR),
        errors.ERR_ELECTION_NOT_FOUND)
    validate_error(
        client.create_precinct(MISSING_ELECTION_ID, f.precinct_payload(), users.COORDINATOR),
        errors.ERR_ELECTION_NOT_FOUND)
    validate_error(
        client.create_ballot_style(MISSING_ELECTION_ID, f.ballot_style_payload(),
                                   users.COORDINATOR),
        errors.ERR_ELECTION_NOT_FOUND)
    validate_error(
        client.create_tabulator(MISSING_ELECTION_ID, f.tabulator_payload(), users.TECHNICIAN),
        errors.ERR_ELECTION_NOT_FOUND)
    validate_error(
        client.list_custody_events(MISSING_ELECTION_ID, users.OBSERVER),
        errors.ERR_ELECTION_NOT_FOUND)

    precincts, precinct_meta = validate_paginated(client.list_precincts(users.DIRECTOR))
    assert precincts == [] and precinct_meta["total_count"] == 0, (
        f"no precinct may have been created, got {precincts!r}"
    )
    styles, style_meta = validate_paginated(client.list_ballot_styles(users.DIRECTOR))
    assert styles == [] and style_meta["total_count"] == 0, (
        f"no ballot style may have been created, got {styles!r}"
    )
    units, unit_meta = validate_paginated(client.list_tabulators(users.DIRECTOR))
    assert units == [] and unit_meta["total_count"] == 0, (
        f"no tabulator may have been created, got {units!r}"
    )


# ---- The append-only chain-of-custody ledger ----

def test_en_custody_ledger_appends_three_chained_rows(client):
    """Delivery, receipt and issue append three ledger lines for the same lot, numbered 1, 2
    and 3 and chaining end to end.

    PRD Section 2.11: "Each ledger line — a custody event — records `election_id`, a `subject_type` of either `TABULATOR_UNIT` or `BALLOT_LOT`, the `subject_id` of the tabulator or lot it concerns, an `event_type` drawn from `TRANSFER_OUT`, `RECEIPT`, `ISSUE`, `RECALL`, `RETURN`, `SEAL_APPLIED`, `SEAL_BROKEN`, `RETENTION_SEAL` and `VOID`, the subject's `from_state` and `to_state` as strings, the `seal_number` applied or broken (null for events that touch no seal), the `actor_role` and `actor_user_id` responsible, the `occurred_at` logical-clock instant, and a `sequence_index`: the one-based position of the line among the lines sharing the same `subject_id`, ordered by `occurred_at` ascending and then `created_at` ascending."

    Design: Corner/entities/en_custody_event_ledger_is_immutable_and_append_only
    """
    sc = fx.issued_lot(client, registered_voter_count=100, issue_quantity=3000,
                       election_overrides={"election_date": ELECTION_INSTANT})

    rows, meta = validate_paginated(
        client.list_custody_events(sc.election_id, users.OBSERVER,
                                   {"subject_id": sc.lot_id, "limit": 100}))

    assert len(rows) == 3, f"the lot must carry exactly 3 ledger lines, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"the ledger must count 3 lines for the lot, got {meta['total_count']}"
    )
    assert [row["sequence_index"] for row in rows] == [1, 2, 3], (
        f"sequence_index must run 1, 2, 3 in order, got "
        f"{[row.get('sequence_index') for row in rows]!r}"
    )
    for row in rows:
        a.assert_fields_equal(
            row,
            {
                "subject_type": c.SUBJECT_BALLOT_LOT,
                "subject_id": sc.lot_id,
                "election_id": sc.election_id,
            },
            "custody event",
        )

    a.assert_custody_event(rows[0], c.EVENT_TRANSFER_OUT, to_state=c.LOT_IN_TRANSIT,
                           actor_user_id=sc.vendor_id)
    a.assert_fields_equal(rows[0], {"actor_role": c.ROLE_PRINT_VENDOR_REP}, "custody event 1")
    a.assert_custody_event(rows[1], c.EVENT_RECEIPT, from_state=c.LOT_IN_TRANSIT,
                           to_state=c.LOT_RECEIVED, seal_number=c.SEAL_1,
                           actor_user_id=c.USER_CUSTODIAN)
    a.assert_fields_equal(rows[1], {"actor_role": c.ROLE_WAREHOUSE_CUSTODIAN},
                          "custody event 2")
    a.assert_custody_event(rows[2], c.EVENT_ISSUE, from_state=c.LOT_RECEIVED,
                           to_state=c.LOT_ISSUED, actor_user_id=c.USER_CUSTODIAN)
    a.assert_fields_equal(rows[2], {"actor_role": c.ROLE_WAREHOUSE_CUSTODIAN},
                          "custody event 3")
    assert rows[1]["to_state"] == rows[2]["from_state"], (
        "the ledger must chain without gaps: the receipt's to_state is the issue's from_state"
    )


def test_en_custody_event_carries_no_version_or_updated_at(client):
    """A custody event exposes only an id and a creation stamp: no updated_at and no version,
    and its occurred_at is the logical-clock instant.

    PRD Section 2.4: "A custody event is an append-only ledger line and is therefore deliberately impoverished: it has only `id` and `created_at`; it has no `updated_at` and no `version` field at all."

    Design: Corner/entities/en_custody_event_ledger_is_immutable_and_append_only
    """
    sc = fx.issued_lot(client, registered_voter_count=100, issue_quantity=3000,
                       election_overrides={"election_date": ELECTION_INSTANT})

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.OBSERVER,
                                   {"subject_id": sc.lot_id, "limit": 100}))

    assert len(rows) == 3, f"the lot must carry exactly 3 ledger lines, got {len(rows)}"
    for index, row in enumerate(rows, start=1):
        a.assert_created_at_only(row, f"custody event {index}")
        assert a.parse_instant(row["occurred_at"]) == a.parse_instant(c.CLOCK_START), (
            f"custody event {index} occurred_at must read the logical clock "
            f"{c.CLOCK_START}, got {row['occurred_at']!r}"
        )
