"""The FIRM panel timeline: publication, the appeal window, the letter of final
determination, and the moment a panel starts governing the map.

A panel number inside one community is a single sheet of the map revised over
time, so the checks here pin the sequencing rules that keep that timeline
single-threaded, the two temporal gates in front of the effective transition,
and the fact that map authorship belongs to the agency alone.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_map_panel,
    create_community,
    make_agency_headers,
    make_analyst_headers,
    make_borrower_headers,
    make_lender_headers,
    make_reviewer_headers,
    publish_panel,
    set_clock,
)

CLOCK = "2026-08-01T00:00:00Z"
FAMILY_A = "12086C0312K"
FAMILY_B = "12086C0314K"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 renders timestamps with three fractional digits, so the stored value
    of an instant supplied as ``2026-10-30T00:00:00Z`` reads back as
    ``2026-10-30T00:00:00.000Z``; both spellings name the same instant.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def test_appeal_period_cannot_be_opened_on_a_panel_already_in_force():
    """A first-sequence panel is born EFFECTIVE, which is not a from-state for
    either the appeal-period or the effective trigger.

    PRD §3.2: "An initial FIRM is published, not revised: when `revision_sequence` is 1 the panel's `revision_status` is set directly to `EFFECTIVE` at creation rather than to `PRELIMINARY`, its `effective_date` is stored from the request body, `supersedes_panel_id` must be null, and no other panel with the same community and `map_panel_number` may already be `EFFECTIVE`."
    PRD §3.2: "Attempting to open an appeal period on a panel in any other `revision_status` — an already `EFFECTIVE` panel, for instance — is rejected with `ERR_INVALID_PANEL_STATE` (HTTP 409)."
    PRD §3.2: "The panel must be in `LFD_ISSUED`, or the request is rejected with `ERR_INVALID_PANEL_STATE`."

    Design: Corner/state_machines/corner_appeal_period_on_effective_panel_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    panel = publish_panel(community["id"])
    assert_map_panel(panel)
    assert panel["revision_sequence"] == 1
    assert panel["supersedes_panel_id"] is None
    assert panel["revision_status"] == "EFFECTIVE"

    validate_error(
        api_client.open_appeal_period(
            panel["id"],
            {"appeal_period_end_date": "2026-10-30T00:00:00Z"},
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_INVALID_PANEL_STATE.value,
        409,
    )

    # A refused transition stores none of its inputs.
    after = validate_success(
        api_client.get_map_panel(panel["id"], headers=make_agency_headers())
    )
    assert after["revision_status"] == "EFFECTIVE"
    assert after["appeal_period_end_date"] is None
    assert after["version"] == panel["version"]

    # The effective trigger's from-state is LFD_ISSUED, so it refuses this panel too.
    validate_error(
        api_client.make_panel_effective(panel["id"], {}, headers=make_agency_headers()),
        ApiErrorId.ERR_INVALID_PANEL_STATE.value,
        409,
    )


def test_opening_the_appeal_period_defaults_the_window_to_ninety_days():
    """With no body the appeal window closes 90 days out; an explicit date in the
    body replaces that default, and neither disturbs the panel in force.

    PRD §3.2: "Every panel with `revision_sequence` of 2 or more instead enters `PRELIMINARY` and must walk the full appeal and letter-of-final-determination path before it can govern anything, and its `supersedes_panel_id` must name the currently `EFFECTIVE` panel with the same community and `map_panel_number` whose `revision_sequence` is exactly one less than the new panel's."
    PRD §3.2: "Either way `revision_round` starts at 0."
    PRD §3.2: "Opening the statutory appeal period is an agency action on a panel that is still `PRELIMINARY` and whose `revision_sequence` is 2 or more, and it moves the panel `PRELIMINARY → APPEAL_OPEN`."
    PRD §3.2: "The caller may supply `appeal_period_end_date` explicitly; when omitted, it defaults to 90 days after the current logical instant, which is the statutory appeal window."

    Design: Corner/state_machines/corner_appeal_period_transition_applies_default_end_date
    """
    set_clock(CLOCK)
    community = create_community()
    first = publish_panel(community["id"], map_panel_number=FAMILY_A)
    successor = publish_panel(
        community["id"],
        map_panel_number=FAMILY_A,
        revision_sequence=2,
        supersedes_panel_id=first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    # A sequence-2 panel is not born in force, whatever its effective_date says.
    assert successor["revision_status"] == "PRELIMINARY"
    assert successor["revision_round"] == 0
    assert successor["supersedes_panel_id"] == first["id"]

    opened = validate_success(
        api_client.open_appeal_period(successor["id"], {}, headers=make_agency_headers())
    )
    assert_map_panel(opened)
    assert opened["revision_status"] == "APPEAL_OPEN"
    # 2026-08-01 + 90 days.
    assert_instant(opened["appeal_period_end_date"], "2026-10-30T00:00:00Z")
    assert opened["lfd_issued_at"] is None
    assert opened["superseded_at"] is None
    assert opened["revision_round"] == 0

    # Opening a window on the successor does not touch the panel in force.
    predecessor = validate_success(
        api_client.get_map_panel(first["id"], headers=make_agency_headers())
    )
    assert predecessor["revision_status"] == "EFFECTIVE"
    assert predecessor["superseded_at"] is None

    # The same trigger on a second sheet, this time with the date supplied.
    other_first = publish_panel(
        community["id"], map_panel_number=FAMILY_B, base_flood_elevation_ft=8.25
    )
    other_successor = publish_panel(
        community["id"],
        map_panel_number=FAMILY_B,
        revision_sequence=2,
        supersedes_panel_id=other_first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1235P",
    )
    explicit = validate_success(
        api_client.open_appeal_period(
            other_successor["id"],
            {"appeal_period_end_date": "2026-12-01T00:00:00Z"},
            headers=make_agency_headers(),
        )
    )
    assert explicit["revision_status"] == "APPEAL_OPEN"
    assert_instant(explicit["appeal_period_end_date"], "2026-12-01T00:00:00Z")


def test_appeal_decision_is_refused_while_the_posted_window_is_still_open():
    """Both appeal outcomes wait for the posted window: before it closes the
    refusal is ERR_APPEAL_PERIOD_OPEN, and at the closing instant itself the
    same call succeeds.

    PRD §3.2: "Resolving the appeal period is the panel's branch point, and both branches are available only once the posted window has closed, meaning the current logical instant is at or after `appeal_period_end_date`; recording a decision while `appeal_period_end_date` is still in the future is rejected with `ERR_APPEAL_PERIOD_OPEN`, and recording one against a panel that is not `APPEAL_OPEN` is rejected with `ERR_INVALID_PANEL_STATE`."
    PRD §3.2: "When `outcome` is `LFD_ISSUED`, the letter of final determination is issued instead: the panel moves `APPEAL_OPEN → LFD_ISSUED` and `lfd_issued_at` is set to the current logical instant, while `revision_round` and `appeal_period_end_date` are left exactly as they were."

    Design: Corner/state_machines/corner_appeal_decision_while_period_open_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    first = publish_panel(community["id"])
    successor = publish_panel(
        community["id"],
        revision_sequence=2,
        supersedes_panel_id=first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    validate_success(
        api_client.open_appeal_period(
            successor["id"],
            {"appeal_period_end_date": "2026-10-30T00:00:00Z"},
            headers=make_agency_headers(),
        )
    )

    # Clock 2026-08-01 is still short of the posted 2026-10-30 close.
    validate_error(
        api_client.record_appeal_decision(
            successor["id"], {"outcome": "LFD_ISSUED"}, headers=make_agency_headers()
        ),
        ApiErrorId.ERR_APPEAL_PERIOD_OPEN.value,
        409,
    )
    # The gate guards the endpoint, not one outcome value.
    validate_error(
        api_client.record_appeal_decision(
            successor["id"],
            {"outcome": "REVISED_PRELIMINARY"},
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_APPEAL_PERIOD_OPEN.value,
        409,
    )

    held = validate_success(
        api_client.get_map_panel(successor["id"], headers=make_agency_headers())
    )
    assert held["revision_status"] == "APPEAL_OPEN"
    assert held["lfd_issued_at"] is None
    assert held["revision_round"] == 0

    # At exactly the closing instant the window counts as closed.
    set_clock("2026-10-30T00:00:00Z", headers=make_agency_headers())
    decided = validate_success(
        api_client.record_appeal_decision(
            successor["id"], {"outcome": "LFD_ISSUED"}, headers=make_agency_headers()
        )
    )
    assert decided["revision_status"] == "LFD_ISSUED"
    assert_instant(decided["lfd_issued_at"], "2026-10-30T00:00:00Z")
    assert decided["revision_round"] == 0
    assert_instant(decided["appeal_period_end_date"], "2026-10-30T00:00:00Z")


def test_panel_sequence_and_uniqueness_violations_rejected():
    """One rule covers three shapes — a sequence gap, a duplicate triple and a
    successor with no predecessor named — and the legal successor still lands.

    PRD §3.2: "The sequencing and uniqueness rules are enforced together and all report `ERR_PANEL_SEQUENCE_INVALID`: `revision_sequence` must equal the superseded panel's `revision_sequence` plus one; a `revision_sequence` above 1 may not be published with `supersedes_panel_id` left null; a `revision_sequence` of 1 may not be published with `supersedes_panel_id` set; the triple of community, `map_panel_number` and `revision_sequence` must be unique; and at most one panel per community and `map_panel_number` may be `EFFECTIVE` at a time."
    PRD §3.2: "A panel is identified within its community by `map_panel_number`, and the pair of `community_id` and `map_panel_number` is the map timeline key: all panels sharing that pair are successive versions of the same sheet of the map."

    Design: Corner/validations/corner_panel_sequence_and_uniqueness_violations_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    first = publish_panel(community["id"], map_panel_number=FAMILY_A)
    assert first["revision_status"] == "EFFECTIVE"

    def panel_payload(**overrides):
        payload = {
            "community_id": community["id"],
            "map_panel_number": FAMILY_A,
            "revision_sequence": 2,
            "zone_code": "VE",
            "base_flood_elevation_ft": 12.50,
            "effective_date": "2027-04-28T00:00:00Z",
        }
        payload.update(overrides)
        return payload

    # A gap: the successor of sequence 1 must be sequence 2, not 3.
    validate_error(
        api_client.create_map_panel(
            panel_payload(revision_sequence=3, supersedes_panel_id=first["id"]),
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_PANEL_SEQUENCE_INVALID.value,
        409,
    )
    # A duplicate triple, which would also leave two EFFECTIVE panels on one sheet.
    validate_error(
        api_client.create_map_panel(
            panel_payload(
                revision_sequence=1,
                zone_code="AE",
                base_flood_elevation_ft=7.75,
                effective_date="2021-06-05T00:00:00Z",
            ),
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_PANEL_SEQUENCE_INVALID.value,
        409,
    )
    # A revision with no predecessor named: only sequence 1 may stand alone.
    validate_error(
        api_client.create_map_panel(panel_payload(), headers=make_agency_headers()),
        ApiErrorId.ERR_PANEL_SEQUENCE_INVALID.value,
        409,
    )
    # A first sequence may not name a predecessor either.
    validate_error(
        api_client.create_map_panel(
            panel_payload(
                map_panel_number=FAMILY_B,
                revision_sequence=1,
                supersedes_panel_id=first["id"],
            ),
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_PANEL_SEQUENCE_INVALID.value,
        409,
    )

    legal = validate_success(
        api_client.create_map_panel(
            panel_payload(supersedes_panel_id=first["id"], study_case_number="26-04-1234P"),
            headers=make_agency_headers(),
        ),
        201,
    )
    assert legal["revision_status"] == "PRELIMINARY"
    assert legal["revision_sequence"] == 2
    assert legal["supersedes_panel_id"] == first["id"]

    predecessor = validate_success(
        api_client.get_map_panel(first["id"], headers=make_agency_headers())
    )
    assert predecessor["revision_status"] == "EFFECTIVE"
    assert predecessor["superseded_at"] is None

    rows, meta = validate_paginated(
        api_client.list_map_panels(
            headers=make_agency_headers(), params={"community_id": community["id"]}
        )
    )
    # None of the four refusals persisted a row.
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], legal["id"]}


def test_panel_lifecycle_writes_are_exclusive_to_the_agency():
    """All four panel-lifecycle writes are the agency's alone, the refusal is by
    endpoint rather than by entity, and the exclusivity runs both ways.

    PRD §2.1: "Once the caller is authenticated, the role is matched against the set of roles authorised for the target operation as listed in Section 4; a caller whose role is not in that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/flood-zone/map-panels/{map_panel_id}/appeal-period` | Open the statutory appeal period on a preliminary panel | AgencyOfficer |"
    PRD §4: "| POST | `/flood-zone/map-panels/{map_panel_id}/appeal-decision` | Resolve the appeal period: revise the preliminary map, or issue the letter of final determination | AgencyOfficer |"
    PRD §4: "| POST | `/flood-zone/map-panels/{map_panel_id}/effective` | Make a panel effective; head of the five-hop panel-effective cascade | AgencyOfficer |"
    PRD §4: "| GET | `/flood-zone/map-panels/{map_panel_id}` | Fetch one map panel with its revision status, base flood elevation and interval fields | ProviderAnalyst, ProviderReviewer, AgencyOfficer, Lender, Borrower |"
    PRD §4: "| POST | `/flood-zone/properties` | Geocode and register a property against a flood hazard map panel number | ProviderAnalyst |"
    PRD §4: "| POST | `/flood-zone/determinations` | Issue a structure-level flood zone determination against the current effective panel | ProviderAnalyst |"

    Design: Corner/rbac/corner_panel_lifecycle_is_exclusive_to_the_agency
    """
    set_clock(CLOCK)
    community = create_community()
    first = publish_panel(community["id"])
    successor = publish_panel(
        community["id"],
        revision_sequence=2,
        supersedes_panel_id=first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )

    outsiders = (
        make_analyst_headers(),
        make_reviewer_headers(),
        make_lender_headers("lender-not-a-real-row"),
        make_borrower_headers("borrower-a"),
    )
    publish_body = {
        "community_id": community["id"],
        "map_panel_number": FAMILY_B,
        "revision_sequence": 1,
        "zone_code": "AE",
        "base_flood_elevation_ft": 8.25,
        "effective_date": "2020-06-05T00:00:00Z",
    }
    for headers in outsiders:
        validate_error(
            api_client.create_map_panel(publish_body, headers=headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api_client.open_appeal_period(successor["id"], {}, headers=headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api_client.record_appeal_decision(
                successor["id"], {"outcome": "LFD_ISSUED"}, headers=headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api_client.make_panel_effective(successor["id"], {}, headers=headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    untouched = validate_success(
        api_client.get_map_panel(successor["id"], headers=make_agency_headers())
    )
    assert untouched["revision_status"] == "PRELIMINARY"
    assert untouched["version"] == successor["version"]

    opened = validate_success(
        api_client.open_appeal_period(successor["id"], {}, headers=make_agency_headers())
    )
    assert opened["revision_status"] == "APPEAL_OPEN"
    assert_instant(opened["appeal_period_end_date"], "2026-10-30T00:00:00Z")

    # Reads of the map are shared with all five roles even though writes are not.
    lender_read = validate_success(
        api_client.get_map_panel(
            successor["id"], headers=make_lender_headers("lender-not-a-real-row")
        )
    )
    assert lender_read["revision_status"] == "APPEAL_OPEN"

    # The exclusivity is symmetric: the agency is shut out of the provider's writes.
    validate_error(
        api_client.create_property(
            {
                "community_id": community["id"],
                "street_address": "11 Bayfront Rd",
                "city": "Miami",
                "postal_code": "33101",
                "map_panel_number": FAMILY_A,
                "latitude": 25.7617,
                "longitude": -80.1918,
                "geocode_method": "ROOFTOP",
                "geocode_confidence_score": 0.95,
            },
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api_client.create_determination(
            {
                "loan_folio_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                "structure_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3",
                "determination_type": "ORIGINATION",
                "expected_loan_folio_version": 1,
            },
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )


def test_panel_cannot_go_effective_before_the_lfd_waiting_period_elapses():
    """One day short of 180 days past the letter of final determination the
    effective transition is refused; at exactly the 180-day instant it lands and
    carries the supersession with it.

    PRD §3.2: "At least 180 days must have elapsed since `lfd_issued_at` — the letter-of-final-determination waiting period — and the panel's appeal period must have closed, meaning `appeal_period_end_date` is at or before the current logical instant; a premature attempt is rejected with `ERR_LFD_WAITING_PERIOD`."
    PRD §2.5: "When one request violates two rules, the violation with the smaller priority number supplies both the `error_id` and the HTTP status of the response, and the lower-priority violation is never reported."
    PRD §3.2: "In the first hop the panel itself moves `LFD_ISSUED → EFFECTIVE`."
    PRD §3.2: "In the second hop, because this panel is now effective, the predecessor panel it names in `supersedes_panel_id` moves `EFFECTIVE → SUPERSEDED` with its `superseded_at` set to the current logical instant."

    Design: Corner/state_machines/corner_panel_effective_before_lfd_waiting_period_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    first = publish_panel(community["id"])
    successor = publish_panel(
        community["id"],
        revision_sequence=2,
        supersedes_panel_id=first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    validate_success(
        api_client.open_appeal_period(
            successor["id"],
            {"appeal_period_end_date": "2026-10-30T00:00:00Z"},
            headers=make_agency_headers(),
        )
    )
    set_clock("2026-10-30T00:00:00Z", headers=make_agency_headers())
    issued = validate_success(
        api_client.record_appeal_decision(
            successor["id"], {"outcome": "LFD_ISSUED"}, headers=make_agency_headers()
        )
    )
    # 2026-10-30 + 180 days lands the waiting period on 2027-04-28.
    assert_instant(issued["lfd_issued_at"], "2026-10-30T00:00:00Z")

    set_clock("2027-04-27T00:00:00Z", headers=make_agency_headers())
    validate_error(
        api_client.make_panel_effective(successor["id"], {}, headers=make_agency_headers()),
        ApiErrorId.ERR_LFD_WAITING_PERIOD.value,
        409,
    )

    held = validate_success(
        api_client.get_map_panel(successor["id"], headers=make_agency_headers())
    )
    assert held["revision_status"] == "LFD_ISSUED"
    # The rejection suppressed the whole cascade, starting with the second hop.
    unmoved = validate_success(
        api_client.get_map_panel(first["id"], headers=make_agency_headers())
    )
    assert unmoved["revision_status"] == "EFFECTIVE"
    assert unmoved["superseded_at"] is None

    set_clock("2027-04-28T00:00:00Z", headers=make_agency_headers())
    live = validate_success(
        api_client.make_panel_effective(successor["id"], {}, headers=make_agency_headers())
    )
    assert live["revision_status"] == "EFFECTIVE"

    superseded = validate_success(
        api_client.get_map_panel(first["id"], headers=make_agency_headers())
    )
    assert superseded["revision_status"] == "SUPERSEDED"
    assert_instant(superseded["superseded_at"], "2027-04-28T00:00:00Z")


def test_successor_effective_date_must_be_strictly_later_than_its_predecessor():
    """Two sheets of the map are walked identically and differ by one day of
    ``effective_date``: the equal-dated successor is refused because a zero-width
    governing interval would exist, the one-day-later successor goes live.

    PRD §3.2: "`effective_date` is the printed effective date, and it means something precise: a panel governs the half-open interval that starts at its `effective_date` and ends at its successor's `effective_date`."
    PRD §3.2: "The panel's own `effective_date` must be at or before the current logical instant, so a future-dated panel cannot go live, and it must be strictly later than the `effective_date` of the panel named by `supersedes_panel_id`, so that the half-open governing intervals of the two panels cannot overlap; either failure is rejected with `ERR_PANEL_EFFECTIVE_DATE_OVERLAP`."
    PRD §3.2: "A panel is identified within its community by `map_panel_number`, and the pair of `community_id` and `map_panel_number` is the map timeline key: all panels sharing that pair are successive versions of the same sheet of the map."
    PRD §3.2: "In the second hop, because this panel is now effective, the predecessor panel it names in `supersedes_panel_id` moves `EFFECTIVE → SUPERSEDED` with its `superseded_at` set to the current logical instant."

    Design: Difficulty/resource_temporal_overlap/panel_effectivity_half_open_interval_strict_greater_boundary
    """
    set_clock(CLOCK)
    community = create_community()

    # Two independent sheets, both in force from the same printed date.
    a_first = publish_panel(
        community["id"], map_panel_number=FAMILY_A, base_flood_elevation_ft=7.75
    )
    b_first = publish_panel(
        community["id"], map_panel_number=FAMILY_B, base_flood_elevation_ft=8.25
    )
    assert a_first["revision_status"] == "EFFECTIVE"
    assert b_first["revision_status"] == "EFFECTIVE"

    # The successors differ only in effective_date: equal, versus one day later.
    a_second = publish_panel(
        community["id"],
        map_panel_number=FAMILY_A,
        revision_sequence=2,
        supersedes_panel_id=a_first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2020-06-05T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    b_second = publish_panel(
        community["id"],
        map_panel_number=FAMILY_B,
        revision_sequence=2,
        supersedes_panel_id=b_first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2020-06-06T00:00:00Z",
        study_case_number="26-04-1235P",
    )

    for panel_id in (a_second["id"], b_second["id"]):
        validate_success(
            api_client.open_appeal_period(
                panel_id,
                {"appeal_period_end_date": "2026-10-30T00:00:00Z"},
                headers=make_agency_headers(),
            )
        )
    set_clock("2026-10-30T00:00:00Z", headers=make_agency_headers())
    for panel_id in (a_second["id"], b_second["id"]):
        validate_success(
            api_client.record_appeal_decision(
                panel_id, {"outcome": "LFD_ISSUED"}, headers=make_agency_headers()
            )
        )
    # Past both the posted window and the 180-day wait, which ends 2027-04-28.
    set_clock("2027-05-01T00:00:00Z", headers=make_agency_headers())

    validate_error(
        api_client.make_panel_effective(a_second["id"], {}, headers=make_agency_headers()),
        ApiErrorId.ERR_PANEL_EFFECTIVE_DATE_OVERLAP.value,
        409,
    )
    stalled = validate_success(
        api_client.get_map_panel(a_second["id"], headers=make_agency_headers())
    )
    assert stalled["revision_status"] == "LFD_ISSUED"
    a_predecessor = validate_success(
        api_client.get_map_panel(a_first["id"], headers=make_agency_headers())
    )
    assert a_predecessor["revision_status"] == "EFFECTIVE"
    assert a_predecessor["superseded_at"] is None

    # One day of separation is enough: the interval ordering is on effective_date.
    live = validate_success(
        api_client.make_panel_effective(b_second["id"], {}, headers=make_agency_headers())
    )
    assert live["revision_status"] == "EFFECTIVE"
    b_predecessor = validate_success(
        api_client.get_map_panel(b_first["id"], headers=make_agency_headers())
    )
    assert b_predecessor["revision_status"] == "SUPERSEDED"
    assert_instant(b_predecessor["superseded_at"], "2027-05-01T00:00:00Z")

    # The two sheets are independent resources, one panel in force on each.
    rows, meta = validate_paginated(
        api_client.list_map_panels(
            headers=make_agency_headers(),
            params={"community_id": community["id"], "revision_status": "EFFECTIVE"},
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {a_first["id"], b_second["id"]}

    # The defect is in the stored effective_date, so no later clock repairs it.
    set_clock("2027-06-01T00:00:00Z", headers=make_agency_headers())
    validate_error(
        api_client.make_panel_effective(a_second["id"], {}, headers=make_agency_headers()),
        ApiErrorId.ERR_PANEL_EFFECTIVE_DATE_OVERLAP.value,
        409,
    )
