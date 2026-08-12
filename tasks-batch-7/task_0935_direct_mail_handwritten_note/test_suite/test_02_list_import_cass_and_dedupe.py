"""Importing recipients, CASS standardization and duplicate screening."""

from test_helpers import (
    ApiErrorId,
    EIGHT_RECORD_ROSTER,
    LIST_OPERATOR,
    SEVEN_RECORD_ROSTER,
    assert_list_partition_sums_to_record_count,
    assert_list_record,
    assert_mailing_list,
    build_mailing_list,
    create_account,
    read_list_record,
    read_mailing_list,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _seed_list(permit_number, roster, name="Spring List", cass=True):
    set_clock()
    account = create_account(permit_number=permit_number)
    mailing_list, records = build_mailing_list(
        account["id"], roster=roster, name=name, cass=cass
    )
    return account, mailing_list, records


def test_imported_records_receive_insertion_seq_and_two_derived_screening_keys(api):
    """PRD §3.3: "On acceptance the record receives `insertion_seq`, a
    monotonically increasing 1-based position within its list, and two derived
    screening keys."
    PRD §3.3: "`household_key` is formed the same way but omits the given name
    entirely, joining family name, primary street line and postal code."
    PRD §3.3: "A newly imported record begins at `cass_status` `PENDING`,
    `deliverability_tier` `UNASSIGNED`, `dedupe_status` `UNSCREENED`,
    `mail_status` `NOT_MAILED`, `move_status` `NONE`, `reprint_count` 0 and
    `last_mail_job_id` null — five independent facts about the same row, four of
    which are parallel status axes that move on their own schedules."

    Design: Corner/entities/list_record_system_fields_assigned_by_server
    """
    account, mailing_list, records = _seed_list(
        "PMT-202", [SEVEN_RECORD_ROSTER[0], SEVEN_RECORD_ROSTER[1]],
        name="Seq List", cass=False,
    )
    john, jane = records
    assert_list_record(john)

    assert john["insertion_seq"] == 1
    assert jane["insertion_seq"] == 2
    assert john["household_key"] == jane["household_key"], (
        "John and Jane Smith share a family name, street line and postal code"
    )
    assert john["exact_key"] != jane["exact_key"], (
        "their given names differ, so their exact keys differ"
    )
    assert john["cass_status"] == "PENDING"
    assert john["deliverability_tier"] == "UNASSIGNED"
    assert john["dedupe_status"] == "UNSCREENED"
    assert john["mail_status"] == "NOT_MAILED"
    assert john["move_status"] == "NONE"
    assert john["reprint_count"] == 0
    assert john["last_mail_job_id"] is None

    listed = read_mailing_list(mailing_list["id"])
    assert listed["record_count"] == 2


def test_recipient_collection_paginates_with_the_standard_meta_block(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may
    be no smaller than 1 and no larger than 100."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before pagination is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/list_records_filtered_list_paginates_with_envelope
    """
    _, mailing_list, _ = _seed_list(
        "PMT-205", SEVEN_RECORD_ROSTER[2:5], name="Page List", cass=False
    )

    response = api.list_list_records(
        LIST_OPERATOR,
        params={"mailing_list_id": mailing_list["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    body = response.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_importing_a_record_after_standardization_is_a_list_state_failure(api):
    """PRD §3.3: "A `ListOperator` (or `PlatformAdmin`) imports recipients one at
    a time, and only while the list is still `UPLOADED` — once standardization
    has run, the record set is closed and a further import attempt is refused
    with `ERR_LIST_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/record_import_after_cass_run_returns_list_invalid_state
    """
    _, mailing_list, _ = _seed_list("PMT-211", SEVEN_RECORD_ROSTER[2:3], name="Mini List")

    response = api.create_list_record(
        mailing_list["id"], dict(SEVEN_RECORD_ROSTER[3]), LIST_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_LIST_INVALID_STATE.value)

    after = read_mailing_list(mailing_list["id"])
    assert after["record_count"] == 1
    assert after["import_status"] == "CASS_RUN"


def test_a_locked_list_refuses_further_writes_at_the_lock_rung(api):
    """PRD §3.3: "`LOCKED` is terminal for the import pipeline, and it is enforced
    high on the ladder: at rung 12, every further list write — importing another
    record, re-running standardization, re-running deduplication, locking again,
    or applying a move update to any of its records — is refused with
    `ERR_LIST_LOCKED` (HTTP 409), which pre-empts the more specific
    `ERR_LIST_INVALID_STATE` those same operations would otherwise report."

    Design: Corner/state_machines/dedupe_run_after_lock_returns_list_locked
    """
    set_clock()
    account = create_account(permit_number="PMT-212")
    mailing_list, records = build_mailing_list(
        account["id"], roster=SEVEN_RECORD_ROSTER[2:3], name="Mini List",
        cass=True, dedupe_mode="EXACT", lock=True,
    )
    bob = records[0]

    dedupe = api.create_dedupe_run(mailing_list["id"], {"mode": "HOUSEHOLD"}, LIST_OPERATOR)
    validate_error(dedupe, ApiErrorId.ERR_LIST_LOCKED.value)

    move = api.create_ncoa_move(
        bob["id"], {"new_address_line1": "250 Oak Ave"}, LIST_OPERATOR
    )
    validate_error(move, ApiErrorId.ERR_LIST_LOCKED.value)

    after_list = read_mailing_list(mailing_list["id"])
    assert after_list["dedupe_mode"] == "EXACT"
    assert after_list["import_status"] == "LOCKED"
    assert read_list_record(bob["id"])["move_status"] == "NONE"


def test_a_foreign_country_code_forces_unmailable_over_a_confirmed_delivery_point(api):
    """PRD §3.3: "If the record's `country_code` is anything other than `US`, its
    `cass_status` moves `PENDING → UNMAILABLE` and its `deliverability_tier`
    becomes `UNMAILABLE`. Foreign addresses are out of scope for this service's
    postal contracts, and this clause wins over the delivery-point code even when
    that code is favourable."
    PRD §3.3: "Otherwise, if `dpv_confirmation_code` is `Y` — the delivery point
    was confirmed outright — `cass_status` moves `PENDING → STANDARDIZED` and
    `deliverability_tier` becomes `AUTOMATION`."

    Design: Corner/calculations/cass_foreign_country_forces_unmailable_despite_confirmed_dpv
    """
    set_clock()
    account = create_account(permit_number="PMT-232")
    roster = [
        dict(first_name="Bob", last_name="Jones", address_line1="200 Oak Ave",
             city="Chicago", state_code="IL", zip5="60602",
             country_code="US", dpv_confirmation_code="Y"),
        dict(first_name="Nina", last_name="Roy", address_line1="12 Maple Cr",
             city="Toronto", state_code="ON", zip5="M4B1B",
             country_code="CA", dpv_confirmation_code="Y"),
    ]
    mailing_list, records = build_mailing_list(
        account["id"], roster=roster, name="Cross Border List", cass=True
    )
    domestic, foreign = records

    domestic = read_list_record(domestic["id"])
    foreign = read_list_record(foreign["id"])
    assert domestic["deliverability_tier"] == "AUTOMATION"
    assert domestic["cass_status"] == "STANDARDIZED"
    assert foreign["deliverability_tier"] == "UNMAILABLE"
    assert foreign["cass_status"] == "UNMAILABLE"

    assert_mailing_list(mailing_list)
    assert mailing_list["unmailable_count"] == 1
    assert mailing_list["mailable_count"] == 1


def test_household_screening_collapses_the_shared_household_into_one_piece(api):
    """PRD §3.3: "Under `HOUSEHOLD`, records group on `household_key`. The
    survivor's `dedupe_status` moves `UNSCREENED → HOUSEHOLD_HEAD` and later
    members move `UNSCREENED → DUP_HOUSEHOLD`. That same husband and wife share a
    family name, street line and postal code, so they collapse into one piece."
    PRD §3.3: "After screening, the list counters are recomputed:
    `automation_count` is the number of records whose `deliverability_tier` is
    `AUTOMATION` and whose `dedupe_status` is `UNSCREENED`, `UNIQUE` or
    `HOUSEHOLD_HEAD`; `retail_count` is the same count for `RETAIL` tier;
    `duplicate_count` is the number of records whose `dedupe_status` is
    `DUP_EXACT` or `DUP_HOUSEHOLD`; `unmailable_count` is the number whose tier is
    `UNMAILABLE`; and `mailable_count` is `automation_count` plus `retail_count`."

    Design: Difficulty/dual_variant_calc/dedupe_exact_vs_household_mailable_counts
    """
    account, mailing_list, records = _seed_list("PMT-102", SEVEN_RECORD_ROSTER)
    john, jane = records[0], records[1]

    validate_success(api.create_dedupe_run(mailing_list["id"], {"mode": "EXACT"}, LIST_OPERATOR))
    after = validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "HOUSEHOLD"}, LIST_OPERATOR)
    )
    assert_mailing_list(after)

    assert after["mailable_count"] == 6
    assert after["duplicate_count"] == 1
    assert after["automation_count"] == 5
    assert after["retail_count"] == 1
    assert after["dedupe_mode"] == "HOUSEHOLD"
    assert read_list_record(john["id"])["dedupe_status"] == "HOUSEHOLD_HEAD"
    assert read_list_record(jane["id"])["dedupe_status"] == "DUP_HOUSEHOLD"


def test_exact_screening_keeps_the_shared_household_as_two_distinct_pieces(api):
    """PRD §3.3: "Under `EXACT`, records group on `exact_key`. The survivor's
    `dedupe_status` moves `UNSCREENED → UNIQUE` and later members move
    `UNSCREENED → DUP_EXACT`. A husband and wife at the same address have
    different given names, so they form two groups and remain two distinct
    pieces."
    PRD §3.3: "Whenever any two records on a list share a household key,
    `HOUSEHOLD` mode yields a strictly smaller `mailable_count` than `EXACT` mode
    over the identical data."

    Design: Difficulty/dual_variant_calc/dedupe_exact_vs_household_mailable_counts
    """
    account, mailing_list, records = _seed_list("PMT-102", SEVEN_RECORD_ROSTER)
    john, jane = records[0], records[1]

    exact = validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "EXACT"}, LIST_OPERATOR)
    )
    assert exact["mailable_count"] == 7
    assert exact["duplicate_count"] == 0
    assert exact["automation_count"] == 6
    assert exact["retail_count"] == 1
    assert exact["dedupe_mode"] == "EXACT"
    assert read_list_record(john["id"])["dedupe_status"] == "UNIQUE"
    assert read_list_record(jane["id"])["dedupe_status"] == "UNIQUE"

    household = validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "HOUSEHOLD"}, LIST_OPERATOR)
    )
    assert household["mailable_count"] < exact["mailable_count"]


def test_partition_holds_after_household_screening_of_an_eight_record_list(api):
    """PRD §3.3: "After screening, the list counters are recomputed:
    `automation_count` is the number of records whose `deliverability_tier` is
    `AUTOMATION` and whose `dedupe_status` is `UNSCREENED`, `UNIQUE` or
    `HOUSEHOLD_HEAD`; `retail_count` is the same count for `RETAIL` tier;
    `duplicate_count` is the number of records whose `dedupe_status` is
    `DUP_EXACT` or `DUP_HOUSEHOLD`; `unmailable_count` is the number whose tier is
    `UNMAILABLE`; and `mailable_count` is `automation_count` plus `retail_count`."
    PRD §3.3: "Otherwise — that is, for `N` (not confirmed) or `U` (unconfirmed or
    never run) — `cass_status` moves `PENDING → UNMAILABLE` and
    `deliverability_tier` becomes `UNMAILABLE`."

    Design: Difficulty/compensating_invariant/deliverability_partition_conserved_under_both_dedupe_modes
    """
    account, mailing_list, records = _seed_list(
        "PMT-172", EIGHT_RECORD_ROSTER, name="Partition List"
    )
    gus = records[7]

    after = validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "HOUSEHOLD"}, LIST_OPERATOR)
    )
    assert after["record_count"] == 8
    assert after["automation_count"] == 5
    assert after["retail_count"] == 1
    assert after["unmailable_count"] == 1
    assert after["duplicate_count"] == 1
    assert after["mailable_count"] == 6
    assert_list_partition_sums_to_record_count(after)
    assert read_list_record(gus["id"])["deliverability_tier"] == "UNMAILABLE"


def test_partition_holds_again_after_an_exact_rescreen_moves_pieces_between_buckets(api):
    """PRD §3.3: "A second run in a different mode is explicitly supported and can
    move counts in either direction: a record marked `DUP_HOUSEHOLD` under
    household screening travels `DUP_HOUSEHOLD → UNSCREENED` and then
    `UNSCREENED → UNIQUE` under an exact re-run, raising `mailable_count` again."
    PRD §3.3: "After screening, the list counters are recomputed:
    `automation_count` is the number of records whose `deliverability_tier` is
    `AUTOMATION` and whose `dedupe_status` is `UNSCREENED`, `UNIQUE` or
    `HOUSEHOLD_HEAD`; `retail_count` is the same count for `RETAIL` tier;
    `duplicate_count` is the number of records whose `dedupe_status` is
    `DUP_EXACT` or `DUP_HOUSEHOLD`; `unmailable_count` is the number whose tier is
    `UNMAILABLE`; and `mailable_count` is `automation_count` plus `retail_count`."

    Design: Difficulty/compensating_invariant/deliverability_partition_conserved_under_both_dedupe_modes
    """
    account, mailing_list, records = _seed_list(
        "PMT-172", EIGHT_RECORD_ROSTER, name="Partition List"
    )
    jane, gus = records[1], records[7]

    validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "HOUSEHOLD"}, LIST_OPERATOR)
    )
    after = validate_success(
        api.create_dedupe_run(mailing_list["id"], {"mode": "EXACT"}, LIST_OPERATOR)
    )

    assert after["record_count"] == 8
    assert after["automation_count"] == 6
    assert after["retail_count"] == 1
    assert after["unmailable_count"] == 1
    assert after["duplicate_count"] == 0
    assert after["mailable_count"] == 7
    assert_list_partition_sums_to_record_count(after)
    assert read_list_record(jane["id"])["dedupe_status"] == "UNIQUE"
    assert read_list_record(gus["id"])["deliverability_tier"] == "UNMAILABLE"
