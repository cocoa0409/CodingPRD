"""
The declared shape of the resources: echoed inputs, seeded and derived fields,
system-managed fields, and the one entity that has none of them.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import program_admin_headers

FIELD_DAY = "2026-09-02T12:00:00Z"


def _envelope(response):
    """The whole JSON body, for the tests that read the envelope rather than the data."""
    return response.json()


# ─── Creating a structure ───────────────────────────────────────────────────
def test_creating_a_structure_returns_the_declared_success_envelope(client, roster):
    """
    The create answers in the standard envelope: a request id, a request timestamp,
    an object response type, and the created resource in `data`.

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/entities/bridge_create_returns_declared_envelope_and_seeded_ratings
    """
    response = client.create_bridge(
        f.bridge_payload(
            "STR-000001",
            spans_water=True,
            initial_deck_rating=6,
            initial_superstructure_rating=7,
            initial_substructure_rating=8,
        ),
        program_admin_headers(),
    )

    body = _envelope(response)
    assert response.status_code == 201
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert a.is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    a.assert_common_fields(body["data"], "bridge")


def test_a_created_structure_echoes_its_inputs_and_seeds_its_ratings(client, roster):
    """
    The eight inventory inputs come back unchanged, the three seeds populate the
    live component ratings, and the smallest of the three is published as the
    inventory rating that drives frequency.

    PRD §3.1: "These three seeds populate `deck_rating`, `superstructure_rating` and
    `substructure_rating` respectively; from that moment forward the three live
    ratings are owned by the acceptance of inspection reports and the seeds are never
    consulted again. The derived `min_nbi_rating` is the smallest of the three live
    component ratings."
    PRD §2.11: "Failing either the poor-condition test or the extension test, the
    base is the standard 24 months."

    Design: Corner/entities/bridge_create_returns_declared_envelope_and_seeded_ratings
    """
    structure = fx.create_cedar_creek(
        client,
        initial_deck_rating=6,
        initial_superstructure_rating=7,
        initial_substructure_rating=8,
    )

    assert structure["nbi_structure_number"] == "STR-000001"
    assert structure["name"] == "Cedar Creek Bridge"
    assert structure["structure_type"] == "GIRDER"
    assert structure["deck_area_sqm"] == 1000
    assert structure["year_built"] == 1972
    assert structure["adt"] == 12000
    assert structure["detour_length_km"] == 8.5
    assert structure["spans_water"] is True

    assert structure["deck_rating"] == 6
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 8
    assert structure["min_nbi_rating"] == 6
    assert structure["inspection_interval_months"] == 24
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    a.assert_instant_equals(structure["created_at"], "2026-09-01T00:00:00Z", "created_at")


def test_a_created_structure_starts_with_every_derived_field_at_its_initial_value(
    client, roster
):
    """
    Nothing about condition, posture, rating or compliance is guessed at creation:
    the posture and compliance fields take their declared initial values and every
    event-populated field is null.

    PRD §3.1: "`service_posture` starts at `OPEN`, `scour_status` at `NOT_EVALUATED`,
    `poa_compliant` at true, `open_critical_finding_count` at 0, `posting_required`
    at false, `deficiency_pct` and `inventoried_quantity_total` at 0, and
    `bridge_health_index`, `posted_limit_tons`, `operating_rating_tons`,
    `inventory_rating_tons`, `governing_load_rating_id`,
    `last_routine_inspection_date` and `last_underwater_inspection_date` all null
    until the events that populate them occur."

    Design: Corner/entities/bridge_create_returns_declared_envelope_and_seeded_ratings
    """
    structure = fx.create_cedar_creek(
        client,
        initial_deck_rating=6,
        initial_superstructure_rating=7,
        initial_substructure_rating=8,
    )

    assert structure["service_posture"] == "OPEN"
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["poa_compliant"] is True
    assert structure["open_critical_finding_count"] == 0
    assert structure["posting_required"] is False
    assert structure["deficiency_pct"] == 0
    assert structure["inventoried_quantity_total"] == 0
    for nullable in (
        "bridge_health_index",
        "posted_limit_tons",
        "operating_rating_tons",
        "inventory_rating_tons",
        "governing_load_rating_id",
        "last_routine_inspection_date",
        "last_underwater_inspection_date",
    ):
        assert structure[nullable] is None, f"{nullable} must start null"
    assert structure["underwater_interval_months"] is None
    assert structure["next_underwater_due_date"] is None


# ─── Reading a roster entry ─────────────────────────────────────────────────
def _person_expiring_today(client):
    """A roster entry whose refresher expires on the very date the clock reads."""
    fx.pin_base_clock(client)
    return fx.create_person(
        client,
        f.personnel_payload("Ivy Inspector", "2026-09-01", team_leader_certified=True),
    )


def test_a_roster_entry_returns_its_stored_fields_and_the_unset_flags_false(client):
    """
    The stored inputs come back unchanged and the capability flags that were never
    supplied read false rather than null, with no licence number invented.

    PRD §3.1: "Their four capability flags — `team_leader_certified`,
    `underwater_diver_certified`, `fracture_critical_certified` and
    `load_rating_engineer_licensed` — each default to false, and `pe_license_number`
    records the professional engineer licence number, left null for anyone
    unlicensed."

    Design: Corner/entities/personnel_get_by_id_returns_stored_fields_and_derived_qualification
    """
    person = _person_expiring_today(client)

    stored = fx.read_person(client, person["id"])

    assert stored["full_name"] == "Ivy Inspector"
    assert stored["nbis_refresher_expiry_date"][:10] == "2026-09-01"
    assert stored["team_leader_certified"] is True
    assert stored["underwater_diver_certified"] is False
    assert stored["fracture_critical_certified"] is False
    assert stored["load_rating_engineer_licensed"] is False
    assert stored["pe_license_number"] is None
    a.assert_common_fields(stored, "personnel")


def test_an_expiry_on_the_clock_date_is_still_current_and_a_day_later_is_not(client):
    """
    The qualification comparison is inclusive on the expiry date and is re-derived on
    every read, so the same stored record reads `CURRENT` today and `EXPIRED`
    tomorrow with nothing stored having changed.

    PRD §2.10: "the derived `qualification_status` reads `CURRENT` when that expiry
    date falls on or after the logical clock's current UTC calendar date, and
    `EXPIRED` when the expiry date is strictly earlier than that calendar date."
    PRD §2.10: "Because the comparison reads the logical clock,
    `qualification_status` is recomputed on every read of a roster entry and
    re-evaluated at every operation that names the person".

    Design: Corner/entities/personnel_get_by_id_returns_stored_fields_and_derived_qualification
    """
    person = _person_expiring_today(client)
    today = fx.read_person(client, person["id"])
    assert today["qualification_status"] == "CURRENT"

    fx.set_clock(client, "2026-09-02T00:00:00Z")
    tomorrow = fx.read_person(client, person["id"])

    assert tomorrow["qualification_status"] == "EXPIRED"
    assert tomorrow["nbis_refresher_expiry_date"] == today["nbis_refresher_expiry_date"]
    assert tomorrow["full_name"] == today["full_name"]
    assert tomorrow["team_leader_certified"] == today["team_leader_certified"]
    assert tomorrow["version"] == today["version"], "a read never mutates the record"


# ─── Optional inputs and their declared defaults ────────────────────────────
def test_omitting_every_optional_flag_applies_the_declared_defaults(client, roster):
    """
    A structure created from the required fields alone carries all three feature
    flags false and all three component ratings at the 7 default, so the smallest
    live rating is 7.

    PRD §3.1: "The creation payload accepts `initial_deck_rating`,
    `initial_superstructure_rating` and `initial_substructure_rating`, each an
    integer from 0 through 9 and each defaulting to 7 when omitted."

    Design: Corner/entities/bridge_create_optional_flags_defaults_applied
    """
    structure = fx.create_bridge(client, f.bridge_payload("STR-000001"))

    assert structure["spans_water"] is False
    assert structure["underwater_elements"] is False
    assert structure["fracture_critical"] is False
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 7
    assert structure["min_nbi_rating"] == 7


def test_with_the_seeds_defaulted_the_extension_test_turns_on_age_and_traffic_alone(
    client, roster
):
    """
    Two structures differing only in build year and traffic split on the extension
    test: the 1972 crossing keeps the standard cycle while the modern, lightly
    trafficked one earns the four-year cycle.

    PRD §2.11: "Otherwise, if the structure satisfies all three extension tests at
    once — `min_nbi_rating` of at least 7, `year_built` of 1990 or later, and `adt` of
    at most 5000 — the base extends to 48 months, four years between routine
    inspections."

    Design: Corner/entities/bridge_create_optional_flags_defaults_applied
    """
    old = fx.create_bridge(client, f.bridge_payload("STR-000001"))
    modern = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Granite Ridge Overpass",
            structure_type="ARCH",
            deck_area_sqm=800,
            year_built=1995,
            adt=4000,
            detour_length_km=5.0,
        ),
    )

    assert old["inspection_interval_months"] == 24
    a.assert_date_equals(
        old["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    assert modern["inspection_interval_months"] == 48
    a.assert_date_equals(
        modern["next_inspection_due_date"], "2030-09-01", "next_inspection_due_date"
    )
    for structure in (old, modern):
        assert structure["service_posture"] == "OPEN"
        assert structure["scour_status"] == "NOT_EVALUATED"
        assert structure["poa_compliant"] is True
        assert structure["underwater_interval_months"] is None
        assert structure["deficiency_pct"] == 0
        assert structure["inventoried_quantity_total"] == 0


# ─── An element row and its parent's rollups ────────────────────────────────
def test_one_element_row_derives_its_four_values_from_the_condition_quantities(
    client, roster, bridge
):
    """
    A girder row reporting nothing good and a third of its length severe derives its
    sum, its balance, its deficient quantity and its weighted index in the write
    itself, and its group is fixed by its element key rather than chosen.

    PRD §3.2: "`element_health_index` scores the element on a 0-to-100 scale:
    multiply the good quantity by a full weight of 1.00, the fair quantity by 0.80,
    the poor quantity by 0.40 and the severe quantity by 0.00, sum those four
    products, divide by `total_quantity`, multiply by 100, and round the result half
    up to two decimal places."
    PRD §3.2: "an element of total quantity 300 reporting 0 good, 100 fair, 100 poor
    and 100 severe scores 40.00".

    Design: Corner/entities/element_condition_computed_fields_derived_from_condition_quantities
    """
    inspection = fx.open_inspection(client, bridge["id"], roster)

    row = fx.add_element(client, inspection["id"], roster, f.BASELINE_GIRDER)

    assert row["inspection_id"] == inspection["id"]
    assert row["element_group"] == "SUPERSTRUCTURE"
    a.assert_element_group_for_key(row)
    a.assert_element_derived_fields(row, 300, 0, 100, 100, 100)
    assert row["element_health_index"] == 40.00
    a.assert_common_fields(row, "element condition")


def test_the_element_write_rolls_the_report_forward_but_publishes_nothing(
    client, roster, bridge
):
    """
    The parent report's five rollups are refreshed inside the same request, while the
    report's own index and the structure's index both stay null — condition data is
    published only at acceptance.

    PRD §3.2: "Each element write also refreshes the parent report's rollup counters:
    `element_count` (the number of element rows), `reported_quantity_total` (the sum
    of `total_quantity` across rows), `deficient_quantity_total` (the sum of
    poor-plus-severe quantities across rows), `photo_count_total` (the sum of
    `photo_count` across rows), and `quantity_balanced`, which is true only when
    *every* row on the report is individually balanced."
    PRD §3.3: "Submission moves the report from `DRAFT` to `SUBMITTED` and is the
    point at which the report's condition arithmetic is computed and frozen for
    review."

    Design: Corner/entities/element_condition_computed_fields_derived_from_condition_quantities
    """
    inspection = fx.open_inspection(client, bridge["id"], roster)
    fx.add_element(client, inspection["id"], roster, f.BASELINE_GIRDER)

    report = fx.read_inspection(client, inspection["id"])
    assert report["element_count"] == 1
    assert report["reported_quantity_total"] == 300
    assert report["deficient_quantity_total"] == 200
    assert report["photo_count_total"] == 8
    assert report["quantity_balanced"] is True
    assert report["bridge_health_index"] is None
    assert fx.read_bridge(client, bridge["id"])["bridge_health_index"] is None


# ─── System-managed fields are not client inputs ────────────────────────────
def test_a_new_report_takes_its_state_and_parent_from_the_system_not_the_payload(
    client, roster, bridge
):
    """
    A creation payload that also names a status, a different structure, a submission
    instant and a return count gets none of them: the report opens in draft against
    the structure in the path with its counters at their stamped values.

    PRD §3.2: "The report is created in `DRAFT`".
    PRD §3.2: "The new report is stamped with `returned_count` 0, `element_count` 0,
    a `bridge_id` copied from the structure being inspected, a null `qa_reviewer_id`
    until a reviewer actually claims it, and every derived condition field null."

    Design: Corner/entities/inspection_create_system_fields_input_ignored
    """
    other = fx.create_bridge(
        client, f.bridge_payload("STR-000002", name="Willow Slough Bridge")
    )

    report = get_success_data(
        client.create_inspection(
            bridge["id"],
            f.inspection_payload(
                roster.inspector_id,
                fx.FIELD_WINDOW_START,
                fx.FIELD_WINDOW_END,
                status="ACCEPTED",
                bridge_id=other["id"],
                submitted_at="2026-01-01T00:00:00Z",
                returned_count=5,
            ),
            roster.inspector_headers,
        ),
        201,
    )

    assert report["status"] == "DRAFT"
    assert report["bridge_id"] == bridge["id"]
    assert report["submitted_at"] is None
    assert report["qa_claimed_at"] is None
    assert report["accepted_at"] is None
    assert report["returned_count"] == 0
    assert report["element_count"] == 0
    assert report["qa_reviewer_id"] is None
    assert fx.inspections_for_bridge(client, other["id"])["meta"]["total_count"] == 0


# ─── The one entity with no system-managed fields ───────────────────────────
def _urgent_finding_on_a_submitted_report(client, roster, bridge):
    """An `URGENT` finding with no element anchor, raised from a submitted report."""
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)
    fx.submit_report(client, draft["inspection"]["id"], roster)
    return fx.raise_finding(
        client,
        roster,
        bridge["id"],
        draft["inspection"]["id"],
        "URGENT",
        description="Advancing section loss requires monitoring",
    )


def test_a_notification_log_entry_carries_no_version_and_no_updated_at(
    client, roster, bridge
):
    """
    The audit row is the single exception to the common field set: it has an id and a
    creation instant and nothing else the system manages.

    PRD §2.5: "The single exception is the notification log. A notification log entry
    is an immutable audit record: it carries `id` and `created_at` only. It has no
    `updated_at` field and no `version` field at all, and once written it is never
    modified."
    PRD §3.5: "Each link creates an immutable notification log entry carrying its
    `critical_finding_id`, its `tier`, its `channel`, its `recipient_label`, a
    `sent_at` stamped from the logical clock, and a `late` flag."

    Design: Corner/entities/notification_log_immutability_no_version_and_no_mutator
    """
    finding = _urgent_finding_on_a_submitted_report(client, roster, bridge)
    fx.notify_owner(
        client, finding["id"], roster, recipient_label="County bridge superintendent"
    )

    logs = fx.logs_for_finding(client, finding["id"])
    assert len(logs) == 1
    log = logs[0]

    a.assert_notification_log_shape(log)
    assert log["critical_finding_id"] == finding["id"]
    assert log["tier"] == "BRIDGE_OWNER"
    assert log["channel"] == "EMAIL"
    assert log["recipient_label"] == "County bridge superintendent"
    assert log["late"] is False
    a.assert_instant_equals(log["sent_at"], FIELD_DAY, "sent_at")


def test_the_audit_row_stays_frozen_while_its_finding_moves_on(client, roster, bridge):
    """
    Mitigating the finding and advancing the clock three days changes nothing the log
    recorded: it is written once and never modified.

    PRD §2.5: "It has no `updated_at` field and no `version` field at all, and once
    written it is never modified."
    PRD §3.5: "Lateness is measured only against the owner deadline. A log entry's
    `late` is true when its `tier` is `BRIDGE_OWNER` and its `sent_at` falls strictly
    after the finding's `notification_due_at`".

    Design: Corner/entities/notification_log_immutability_no_version_and_no_mutator
    """
    finding = _urgent_finding_on_a_submitted_report(client, roster, bridge)
    fx.notify_owner(
        client, finding["id"], roster, recipient_label="County bridge superintendent"
    )
    written = fx.logs_for_finding(client, finding["id"])[0]

    fx.mitigate(client, finding["id"], roster)
    fx.set_clock(client, "2026-09-05T00:00:00Z")

    reread = validate_success(
        client.get_notification_log(written["id"], program_admin_headers()), 200
    )
    assert reread["id"] == written["id"]
    assert reread["late"] is False
    a.assert_instant_equals(reread["sent_at"], FIELD_DAY, "sent_at")
    a.assert_notification_log_shape(reread)
    assert len(fx.logs_for_finding(client, finding["id"])) == 1
