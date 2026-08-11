"""Alumni record lifecycle: creation defaults, validation, pagination,
optimistic concurrency, do-not-contact / suppression, and lost-alumni
research cases (PRD §3.1, §3.2)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_alumni_record,
    assert_research_case,
    assert_preference,
    create_record,
    create_event,
    setup_lost_record,
    setup_research_case,
    setup_case_in_state,
    create_preference_for_record,
    get_preference,
    TEST_USERS,
    make_committee_volunteer_headers,
    create_log_lead_payload,
)

STAFF = TEST_USERS["staff_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Record creation and defaults
# ---------------------------------------------------------------------------

def test_create_alumni_record_success_and_defaults(api):
    """PRD §3.1: "A new record starts with `status` set to `ACTIVE`, an
    `engagement_score` of 0.00, an `engagement_tier` of `LOW`, a
    `giving_propensity` of 0.00, `lifetime_giving_cents` of 0, and
    `lost_since` unset."

    Design: Corner/entities/create_alumni_record_success_and_defaults
    """
    resp = api.create_record(
        {
            "full_name": "New Alum",
            "primary_email": "newalum@x.com",
            "class_year": 2015,
            "degree_code": "BS",
        },
        STAFF,
    )
    data = validate_success(resp, 201)
    assert_alumni_record(data)
    assert data["status"] == "ACTIVE"
    assert float(data["engagement_score"]) == pytest.approx(0.00, abs=0.001)
    assert data["engagement_tier"] == "LOW"
    assert float(data["giving_propensity"]) == pytest.approx(0.00, abs=0.001)
    assert data["lifetime_giving_cents"] == 0
    assert data.get("lost_since") is None


def test_create_alumni_record_missing_required_field_rejected(api):
    """PRD §2.10: "Independently of this ordering, any request with a
    malformed body, a missing required field, or an invalid enum value is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "creates a record carrying `full_name`, `primary_email`, the
    four-digit `class_year` of the primary degree, and a `degree_code`".

    Design: Corner/entities/create_alumni_record_missing_required_field_rejected
    """
    resp = api.create_record(
        {"full_name": "No Email", "class_year": 2015, "degree_code": "BS"},
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_alumni_record_not_found(api):
    """PRD §2.6: "The first identifier in the path that does not correspond
    to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_alumni_record_not_found
    """
    resp = api.get_record(NON_EXISTENT_UUID, STAFF)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_records_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_records_pagination_envelope
    """
    for i in range(3):
        create_record(full_name=f"P{i+1}")
    resp = api.list_records(STAFF, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"Expected 2 rows under limit=2, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


# ---------------------------------------------------------------------------
# Record terminal-state lockdown
# ---------------------------------------------------------------------------

def test_terminal_state_lockdown_deceased_record(api):
    """PRD §3.1: "`status` becomes `DECEASED` (terminal, and thereafter
    read-only except for status corrections)".
    PRD §2.10: "**State** — the target resource is in a valid from-state for
    the requested transition (`ERR_INVALID_STATE`, all action endpoints)."

    Design: Corner/state_machines/terminal_state_lockdown_deceased_record
    """
    record = create_record(full_name="Dec", primary_email="dec@x.com", class_year=1980)
    deceased = validate_success(api.mark_deceased(record["id"], STAFF))
    assert deceased["status"] == "DECEASED"

    resp = api.mark_lost(record["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Optimistic concurrency on record update
# ---------------------------------------------------------------------------

def test_occ_stale_version_on_record_update(api):
    """PRD §2.7: "If the record's current `version` has advanced since then —
    for example because another writer updated contact details, or because a
    reunite cascade mutated the record — the update is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.1: "a successful update increments the record's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_record_update
    """
    record = create_record(full_name="OCC1", primary_email="occ1@x.com")
    observed_version = record["version"]

    first = validate_success(
        api.update_record(
            record["id"],
            {"full_name": "OCC1 Updated", "expected_record_version": observed_version},
            STAFF,
        )
    )
    assert first["version"] == observed_version + 1, (
        f"Successful update must increment version by one: "
        f"{first['version']} != {observed_version} + 1"
    )

    stale = api.update_record(
        record["id"],
        {"full_name": "OCC1 Again", "expected_record_version": observed_version},
        STAFF,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Do-not-contact and suppression (PRD §3.1)
# ---------------------------------------------------------------------------

def test_suppression_do_not_contact_record_blocks_channel(api):
    """PRD §3.1: "Setting the do-not-contact flag moves a record from
    `ACTIVE` to `DO_NOT_CONTACT` and immediately suppresses every preference
    row with reason `DO_NOT_CONTACT_RECORD`. Clearing it — a director-only
    decision — returns the record to `ACTIVE` and recomputes every row, since
    the global list may still suppress some channels."

    Design: Corner/cross_cutting_layers/suppression_do_not_contact_record_blocks_channel
    """
    record = create_record(full_name="Sup", primary_email="sup@x.com")
    pref = create_preference_for_record(record["id"], channel="EMAIL", opt_in=True)
    assert pref["suppressed"] is False

    validate_success(api.set_do_not_contact(record["id"], STAFF))
    row = get_preference(record["id"], pref["id"])
    assert_preference(row)
    assert row["suppressed"] is True
    assert row["suppression_reason"] == "DO_NOT_CONTACT_RECORD"

    validate_success(api.clear_do_not_contact(record["id"], DIRECTOR))
    row = get_preference(record["id"], pref["id"])
    assert row["suppressed"] is False
    assert row["suppression_reason"] == "NONE"


def test_global_suppression_list_round_trip(api):
    """PRD §3.1: "staff maintain a **global suppression list** of (alumnus,
    channel) pairs; adding a pair triggers recomputation of the matching
    preference row with suppression reason `GLOBAL_LIST`, and removing the
    pair recomputes it again."
    PRD §3.1: "The `suppression_reason` is the first matching cause in the
    fixed precedence order `DO_NOT_CONTACT_RECORD`, then `GLOBAL_LIST`, then
    `HARD_BOUNCE`, and is `NONE` when none applies."

    Design: Corner/cross_cutting_layers/global_suppression_list_round_trip
    """
    record = create_record(full_name="GS", primary_email="gs@x.com")
    pref = create_preference_for_record(record["id"], channel="MAIL", opt_in=True)

    validate_success(
        api.add_suppression({"alumni_id": record["id"], "channel": "MAIL"}, STAFF), 201
    )
    row = get_preference(record["id"], pref["id"])
    assert row["suppressed"] is True
    assert row["suppression_reason"] == "GLOBAL_LIST"

    validate_success(
        api.remove_suppression({"alumni_id": record["id"], "channel": "MAIL"}, STAFF)
    )
    row = get_preference(record["id"], pref["id"])
    assert row["suppressed"] is False
    assert row["suppression_reason"] == "NONE"


# ---------------------------------------------------------------------------
# Lost-alumni research cases (PRD §3.2)
# ---------------------------------------------------------------------------

def test_research_case_reopen_returns_to_open_and_counts(api):
    """PRD §3.2: "A verified lead that turns out bad can be reopened, cycling
    the case `VERIFIED → OPEN` and incrementing `reopened_count` by one".

    Design: Difficulty/non_linear_state_machine/research_case_verified_reopen_cycle
    """
    ctx = setup_case_in_state(
        "VERIFIED",
        case_overrides={"lead_confidence": 80},
        record_overrides={"full_name": "Lost One", "primary_email": "lost1@x.com",
                          "class_year": 1995, "degree_code": "BS"},
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["status"] == "VERIFIED"

    reopened = validate_success(api.reopen_case(case_id, STAFF))
    assert_research_case(reopened)
    assert reopened["status"] == "OPEN"
    assert reopened["reopened_count"] == 1


def test_research_case_full_reopen_cycle_reaches_verified_again(api):
    """PRD §3.2: "Logging a lead moves the case `OPEN → LEAD_LOGGED`" and
    "Verifying a lead moves the case `LEAD_LOGGED → VERIFIED`"; the reopened
    case "cycling the case `VERIFIED → OPEN`" may be walked forward again.

    Design: Difficulty/non_linear_state_machine/research_case_verified_reopen_cycle
    """
    ctx = setup_case_in_state(
        "VERIFIED",
        case_overrides={"lead_confidence": 80},
        record_overrides={"full_name": "Lost One", "primary_email": "lost1b@x.com",
                          "class_year": 1995, "degree_code": "BS"},
    )
    case_id = ctx["case"]["id"]

    validate_success(api.reopen_case(case_id, STAFF))
    logged = validate_success(
        api.log_lead(
            case_id,
            create_log_lead_payload(
                lead_source="PEER_TIP", lead_detail="Classmate tip", lead_confidence=90
            ),
            STAFF,
        )
    )
    assert logged["status"] == "LEAD_LOGGED"

    verified = validate_success(api.verify_case(case_id, STAFF))
    assert verified["status"] == "VERIFIED"
    assert verified["reopened_count"] == 1, (
        "reopened_count persists across the VERIFIED→OPEN→LEAD_LOGGED→VERIFIED cycle"
    )


def test_lead_confidence_below_threshold_rejected(api):
    """PRD §3.2: "Verifying a lead moves the case `LEAD_LOGGED → VERIFIED`
    and demands a `lead_confidence` of at least 60 — a lower confidence fails
    with `ERR_LEAD_CONFIDENCE_TOO_LOW`."

    Design: Corner/validations/lead_confidence_below_threshold_rejected
    """
    ctx = setup_case_in_state(
        "LEAD_LOGGED",
        case_overrides={"lead_source": "PEER_TIP", "lead_detail": "Weak tip",
                        "lead_confidence": 59},
        record_overrides={"full_name": "L2", "primary_email": "l2@x.com",
                          "class_year": 1990},
    )
    case_id = ctx["case"]["id"]

    resp = api.verify_case(case_id, STAFF)
    validate_error(resp, ApiErrorId.ERR_LEAD_CONFIDENCE_TOO_LOW)

    case = validate_success(api.get_research_case(case_id, STAFF))
    assert case["status"] == "LEAD_LOGGED"
