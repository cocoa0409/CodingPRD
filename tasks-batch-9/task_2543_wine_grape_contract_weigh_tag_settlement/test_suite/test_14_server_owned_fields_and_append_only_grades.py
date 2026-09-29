"""Which fields the client may actually set. A weigh tag arrives with its computed
figures pre-filled, a producer arrives with its own identity and audit trail pre-filled,
and a grading is corrected the only way an append-only record can be."""
from test_helpers import (
    LAB_TECH,
    MANAGER,
    SCALE_OPERATOR,
    SCALE_OPERATOR_USER_ID,
    ApiErrorId,
    appointment_version,
    create_weigh_tag_payload,
    dispute_grading,
    list_gradings,
    move_clock,
    read_grading,
    read_weigh_tag,
    record_grading,
    setup_harvest_ready,
    setup_scheduled_appointment,
    setup_single_load_on_pad,
    single_installment_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
SETUP_AT = "2026-08-20T08:00:00Z"
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
DISPUTE_AT = "2026-08-26T09:00:00Z"

# Everything the caller is entitled to send on the inbound pass, and everything it is not.
DECLARED_GROSS_LBS = 57000
UNDECLARED_INPUTS = {
    "net_tons": 99.000,
    "net_weight_lbs": 198000,
    "weigh_status": "NET_FINAL",
    "disposition": "ACCEPTED",
    "grade_count": 7,
    "contract_slice_tons": 99.000,
    "captured_by_user_id": "someone-else",
}


def _stamped_on_the_first(value: str) -> bool:
    """The stamp records the logical clock's instant; the PRD fixes the instant, not the
    number of fractional digits the serialisation carries."""
    return isinstance(value, str) and value.startswith("2026-08-01T00:00:00")


# --- A weigh tag whose computed figures arrived pre-filled ------------------------


def _truck_on_the_scale_asking_for_a_finished_tag(api) -> dict:
    """One scheduled slot, the truck inside its arrival window, and an inbound pass whose
    body carries the six computed fields and a foreign operator id."""
    move_clock(SETUP_AT)
    ctx = setup_harvest_ready(
        contract_overrides={
            "contract_basis": "TONNAGE",
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_CONTRACT",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
        estimated_tons=20.000,
        target_pick_at=TARGET_PICK_AT,
    )
    setup_scheduled_appointment(ctx, SLOT[0], SLOT[1], planned_tons=20.000)
    move_clock(TRUCK_ARRIVES_AT)

    payload = create_weigh_tag_payload(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        DECLARED_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
        **UNDECLARED_INPUTS,
    )
    ctx["tag"] = validate_success(api.create_weigh_tag(payload, SCALE_OPERATOR), 201)
    return ctx


def test_only_the_four_declared_inputs_reach_the_new_tag(api):
    """The gross weight is honoured because it is an input; the net weight and net tonnage
    stay null because they belong to the outbound pass, whatever the body asked for.

    PRD: "The inbound pass opens a weigh tag naming the `appointment_id` the truck presented
    in, the `block_id` the fruit on this tag came from, the loaded `gross_weight_lbs` as a
    whole number of pounds greater than 0 and at most 200000, and the mandatory
    `expected_appointment_version` described in §2.8."

    Design: Corner/entities/weigh_tag_computed_field_client_input_ignored
    """
    tag = _truck_on_the_scale_asking_for_a_finished_tag(api)["tag"]

    assert tag["gross_weight_lbs"] == DECLARED_GROSS_LBS
    assert tag["tare_weight_lbs"] is None
    assert tag["net_weight_lbs"] is None
    assert tag["net_tons"] is None


def test_both_dimensions_open_where_the_declaration_says_they_open(api):
    """The caller asked for a finished, accepted load; both dimensions still start at their
    declared initial states.

    PRD: "A new tag records `captured_by_user_id` from the acting `X-User-ID`, starts its
    weight-capture dimension at `GROSS_CAPTURED` and its receipt-decision dimension at
    `PENDING`, and leaves `tare_weight_lbs`, `net_weight_lbs` and `net_tons` all null."

    Design: Corner/entities/weigh_tag_computed_field_client_input_ignored
    """
    tag = _truck_on_the_scale_asking_for_a_finished_tag(api)["tag"]

    assert tag["weigh_status"] == "GROSS_CAPTURED"
    assert tag["disposition"] == "PENDING"


def test_the_grade_count_the_slices_and_the_two_deadlines_start_empty(api):
    """Seven gradings and 99 tons of contract slice were requested; the tag opens with a
    grade count of zero, four zeroed slices, and nothing yet to adjust or dispute.

    PRD: "A tag also carries `grade_count`, starting at 0, `active_adjustment_pct`, null
    until a grading exists, four tonnage slices — `contract_slice_tons`, `over_slice_tons`,
    `over_rejected_tons` and `excess_rejected_tons` — all starting at 0.000, and
    `dispute_deadline_at`, null until the first grading."

    Design: Corner/entities/weigh_tag_computed_field_client_input_ignored
    """
    tag = _truck_on_the_scale_asking_for_a_finished_tag(api)["tag"]

    assert tag["grade_count"] == 0
    assert float(tag["contract_slice_tons"]) == 0.000
    assert float(tag["over_slice_tons"]) == 0.000
    assert float(tag["over_rejected_tons"]) == 0.000
    assert float(tag["excess_rejected_tons"]) == 0.000
    assert tag["active_adjustment_pct"] is None
    assert tag["dispute_deadline_at"] is None


def test_the_operator_on_the_tag_is_the_acting_header_not_the_body(api):
    """Attribution is what the separation-of-duties rule later reads, so it comes from the
    acting identity and cannot be donated to someone else in the body.

    PRD: "The acting `X-User-ID` is stored on the new grading row as `graded_by_user_id`, and
    it must differ from the tag's `captured_by_user_id` — the segregation-of-duties rule that
    outranks every state question on this endpoint."

    Design: Corner/entities/weigh_tag_computed_field_client_input_ignored
    """
    ctx = _truck_on_the_scale_asking_for_a_finished_tag(api)

    assert ctx["tag"]["captured_by_user_id"] == SCALE_OPERATOR_USER_ID
    assert ctx["tag"]["captured_by_user_id"] != "someone-else"
    assert read_weigh_tag(ctx["tag"]["id"])["captured_by_user_id"] == SCALE_OPERATOR_USER_ID


# --- A producer whose identity and audit trail arrived pre-filled ------------------


CLIENT_CHOSEN_ID = "client-chosen-id"
PRESUMPTUOUS_PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
    "id": CLIENT_CHOSEN_ID,
    "created_at": "1999-01-01T00:00:00Z",
    "updated_at": "1999-01-01T00:00:00Z",
    "version": 42,
    "reliability_score_lifetime": 12.5,
    "outstanding_lien_balance_cents": 999999,
}


def test_the_server_mints_the_identifier_and_the_clients_choice_addresses_nothing(api):
    """The body proposed its own primary key; the row came back under a different one, and
    the proposed one resolves to no producer at all.

    PRD: "Every resource in the system is addressed by an `id` that the server mints: a UUID
    string with no type prefix of any kind. Clients never supply an `id`."

    Design: Corner/entities/grower_system_fields_generated_by_server_input_ignored
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRESUMPTUOUS_PRODUCER), MANAGER), 201)
    assert grower["id"] != CLIENT_CHOSEN_ID

    validate_error(
        api.get_grower(CLIENT_CHOSEN_ID, MANAGER), ApiErrorId.ERR_GROWER_NOT_FOUND.value, 404
    )


def test_the_audit_trail_comes_from_the_logical_clock_and_opens_at_version_one(api):
    """A 1999 create date and a version of 42 are both discarded: the stamps are the clock's
    and the version is the first.

    PRD: "Nothing in this system reads the wall clock. All temporal reasoning — notice
    periods, acknowledgement deadlines, arrival windows, dispute windows, installment due
    dates, renewal windows and termination effectiveness — consults a server-held **logical
    clock**, and every timestamp the server stamps (`issued_at`, `sampled_at`,
    `acknowledged_at`, `settlement_closed_at`, `voided_at`, `superseded_at`,
    `lien_released_at` and the rest) is taken from it."

    Design: Corner/entities/grower_system_fields_generated_by_server_input_ignored
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRESUMPTUOUS_PRODUCER), MANAGER), 201)
    assert _stamped_on_the_first(grower["created_at"])
    assert grower["updated_at"] == grower["created_at"]
    assert not str(grower["created_at"]).startswith("1999")
    assert grower["version"] == 1


def test_derived_standing_is_seeded_by_the_server_not_declared_by_the_client(api):
    """A producer cannot open its own file with a damaged reliability score or a debt it
    invented; both figures come back at their seeded values.

    PRD: "Registration also initialises the producer's derived standing:
    `rejected_load_count_vintage`, `expired_pick_call_count_vintage`,
    `no_show_appointment_count_vintage` and `prior_vintage_penalty_units` all start at 0,
    `outstanding_lien_balance_cents` starts at 0, and both `reliability_score_vintage` and
    `reliability_score_lifetime` start at 100.0."

    Design: Corner/entities/grower_system_fields_generated_by_server_input_ignored
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRESUMPTUOUS_PRODUCER), MANAGER), 201)
    assert float(grower["reliability_score_lifetime"]) == 100.0
    assert float(grower["reliability_score_vintage"]) == 100.0
    assert grower["outstanding_lien_balance_cents"] == 0


# --- A grading corrected the only way an append-only record can be ----------------


def _a_load_graded_disputed_and_graded_again() -> dict:
    """20.000 net tons graded clean at Brix 23.0, contested by the producer the next
    morning, then re-graded at Brix 25.0 — two lab records for one tag."""
    ctx = setup_single_load_on_pad(
        contract_overrides={
            "contract_basis": "TONNAGE",
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_CONTRACT",
            "installment_plan": single_installment_plan(),
        },
        net_tons=20.000,
        tare_weight_lbs=17000,
        estimated_tons=25.000,
        planned_tons=20.000,
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
    )
    ctx["first_grade"] = record_grading(
        ctx["tag"]["id"], brix=23.0, ta_gl=6.5, ph=3.40, rot_pct=1.0, mog_pct=0.5
    )
    move_clock(DISPUTE_AT)
    dispute_grading(
        ctx["tag"]["id"], ctx["grower"]["id"], reason="grower asks for a second sugar reading"
    )
    ctx["second_grade"] = record_grading(
        ctx["tag"]["id"], brix=25.0, ta_gl=6.5, ph=3.40, rot_pct=1.0, mog_pct=0.5
    )
    return ctx


def test_a_correction_appends_a_second_lab_record_rather_than_editing_the_first(api):
    """The re-grade is a create, not an update: a new identifier comes back and the original
    row is still addressable in its own right.

    PRD: "A grading is created with HTTP 201 and the created grading row is what comes back —
    a grading is append-only, and no update or delete for it exists anywhere in the API."

    Design: Corner/entities/quality_grade_is_immutable_and_carries_no_version_field
    """
    ctx = _a_load_graded_disputed_and_graded_again()

    assert ctx["second_grade"]["id"] != ctx["first_grade"]["id"]
    assert read_grading(ctx["first_grade"]["id"])["id"] == ctx["first_grade"]["id"]
    assert read_grading(ctx["second_grade"]["id"])["id"] == ctx["second_grade"]["id"]


def test_the_superseded_reading_keeps_its_own_numbers_and_gains_a_supersession_stamp(api):
    """Brix 23.0 sat in the dead band and priced at no adjustment; after the dispute and the
    re-grade the row still says exactly that, with the moment it was retired recorded on it.

    PRD: "A dispute unwinds the grading's financial consequences completely. The active
    grading receives `superseded_at` from the logical clock."

    Design: Corner/entities/quality_grade_is_immutable_and_carries_no_version_field
    """
    ctx = _a_load_graded_disputed_and_graded_again()

    superseded = read_grading(ctx["first_grade"]["id"])
    assert float(superseded["brix"]) == 23.0
    assert float(superseded["adjustment_pct"]) == 0.0
    assert superseded["superseded_at"] == DISPUTE_AT


def test_neither_lab_record_carries_a_version_or_an_update_stamp(api):
    """Gradings are the one family outside the common audit trail: two identifiers, two
    creation stamps, and no optimistic-concurrency field on either row.

    PRD: "**Grading rows are the single exception.** A grading is an append-only lab record:
    it carries `id` and `created_at` only. It has no `updated_at` and no `version`, because it
    is never modified after it is written — a correction is expressed by writing a newer
    grading and stamping `superseded_at` on the older one, not by editing anything."

    Design: Corner/entities/quality_grade_is_immutable_and_carries_no_version_field
    """
    ctx = _a_load_graded_disputed_and_graded_again()

    for grade_id in (ctx["first_grade"]["id"], ctx["second_grade"]["id"]):
        row = read_grading(grade_id)
        assert "version" not in row
        assert "updated_at" not in row
        assert isinstance(row["created_at"], str) and row["created_at"]


def test_the_grading_history_of_the_load_holds_both_rows(api):
    """Walking the tag's gradings returns the superseded row alongside the live one, and only
    the newest has a null supersession stamp.

    PRD: "Gradings are read individually — exposing the four components, the pre-clamp
    `raw_adjustment_pct`, the clamped `adjustment_pct`, the `recommended_disposition` and
    `superseded_at` — and listed with the optional filters `weigh_tag_id` and
    `recommended_disposition`, which is how a load's full grading history including superseded
    rows is walked."

    Design: Corner/entities/quality_grade_is_immutable_and_carries_no_version_field
    """
    ctx = _a_load_graded_disputed_and_graded_again()

    rows, meta = validate_paginated(
        api.list_quality_grades(LAB_TECH, params={"weigh_tag_id": ctx["tag"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {ctx["first_grade"]["id"], ctx["second_grade"]["id"]}
    live = [row for row in rows if row["superseded_at"] is None]
    assert [row["id"] for row in live] == [ctx["second_grade"]["id"]]
    assert len(list_gradings(weigh_tag_id=ctx["tag"]["id"])) == 2


def test_the_concurrency_guard_lives_on_the_parent_tag_which_did_advance(api):
    """The tag counts both readings and its own version moved on every write — which is why
    the guard the re-grade had to satisfy is the tag's version and not a grading's.

    PRD: "Recording a grading also writes the grading row itself, stamping `superseded_at` on
    any earlier grading of the same tag, incrementing the tag's `grade_count` by 1 —
    superseded rows still count — and setting `active_adjustment_pct` to the new grading's
    `adjustment_pct`."

    Design: Corner/entities/quality_grade_is_immutable_and_carries_no_version_field
    """
    ctx = _a_load_graded_disputed_and_graded_again()

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["grade_count"] == 2
    assert tag["version"] > int(ctx["tag"]["version"])
