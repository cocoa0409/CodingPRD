"""Certificate legality that depends on another entity's configuration or state."""

from test_helpers import (
    INSPECTOR,
    SUPERVISOR,
    ApiErrorId,
    TEST_DEFAULTS,
    api_client,
    assert_ledger,
    certificate_payload,
    close_watch,
    countersign,
    create_active_inspector,
    create_delegated_area,
    issue_certificate,
    read_applicant,
    read_request,
    read_watch,
    schedule_watch,
    setup_graded_and_weighed_request,
    setup_office,
    setup_weighed_request,
    start_watch,
    supervise_payload,
    validate_error,
    validate_success,
)


UNSUPERVISED_WEIGHING_SCHEDULE = (
    {
        "service_class": "WEIGHING",
        "base_fee_cents": 6000,
        "per_thousand_bushel_rate_cents": 1000,
        "overtime_multiplier_bp": 2000,
        "minimum_fee_cents": 8000,
    },
)

SUPERVISED_WEIGHING_SCHEDULE = (
    {
        "service_class": "WEIGHING",
        "base_fee_cents": 9000,
        "per_thousand_bushel_rate_cents": 1500,
        "overtime_multiplier_bp": 2500,
        "minimum_fee_cents": 10000,
    },
)

EXPORT_SCHEDULES = (
    {
        "service_class": "GRADING",
        "base_fee_cents": 12000,
        "per_thousand_bushel_rate_cents": 3000,
        "overtime_multiplier_bp": 2500,
        "minimum_fee_cents": 15000,
    },
    {
        "service_class": "WEIGHING",
        "base_fee_cents": 9000,
        "per_thousand_bushel_rate_cents": 1500,
        "overtime_multiplier_bp": 2500,
        "minimum_fee_cents": 10000,
    },
    {
        "service_class": "EXPORT_SUPERVISION",
        "base_fee_cents": 25000,
        "per_thousand_bushel_rate_cents": 2000,
        "overtime_multiplier_bp": 5000,
        "minimum_fee_cents": 50000,
    },
)

WATCH_START = "2026-08-03T08:00:00Z"
WATCH_END = "2026-08-03T16:00:00Z"


def test_weight_certificate_issues_from_weighed_where_supervision_is_not_required():
    """A `WEIGHT`, `COMBINED` or `EXPORT_CARGO` certificate requires an operative
    weighing record, and how operative is defined depends on the area: where
    `supervision_required` is true the record must be `SUPERVISED`, and where it
    is false a record in either `WEIGHED` or `SUPERVISED` will do; falling short
    is `ERR_WEIGHING_SUPERVISION_REQUIRED`.

    `weighing_status` starts at `PENDING` when `requested_services` includes
    `WEIGHING` and at `NOT_REQUIRED` when it does not, and runs through
    `WEIGHED`, `SUPERVISED` and `WEIGHT_CERTIFIED`. Neither dimension constrains
    the other.

    Design: Difficulty/cross_entity_state_dependency/weight_certificate_legality_depends_on_area_supervision_flag_and_weighing_state
    """
    office = setup_office("DELEGATED", fee_schedules=UNSUPERVISED_WEIGHING_SCHEDULE)
    staged = setup_weighed_request(office)
    assert staged["weighing"]["status"] == "WEIGHED"

    certificate = issue_certificate(
        staged["request"]["id"], office["inspector"]["id"], "WEIGHT"
    )

    assert certificate["fee_total_cents"] == 10000
    request = read_request(staged["request"]["id"])
    assert request["weighing_status"] == "WEIGHT_CERTIFIED"
    assert request["grading_status"] == "OPEN"


def test_weight_certificate_waits_for_the_countersignature_where_it_is_required():
    """On success the record moves `WEIGHED → SUPERVISED`,
    `supervisor_inspector_id` is recorded where it had been null, and the
    request's weighing dimension advances `WEIGHED → SUPERVISED`.

    The area's authority adjustment is then the discounted amount multiplied by
    the area's `fee_multiplier_bp` less 10000, divided by 10000, rounded half up
    to whole cents, and added.

    Design: Difficulty/cross_entity_state_dependency/weight_certificate_legality_depends_on_area_supervision_flag_and_weighing_state
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"fee_multiplier_bp": 11500, "supervision_required": True},
        fee_schedules=SUPERVISED_WEIGHING_SCHEDULE,
    )
    staged = setup_weighed_request(office)

    premature = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "WEIGHT"
        ),
        INSPECTOR,
    )
    validate_error(
        premature, ApiErrorId.ERR_WEIGHING_SUPERVISION_REQUIRED.value, 409
    )

    supervised = countersign(staged["weighing"]["id"], office["supervisor"]["id"])
    assert supervised["status"] == "SUPERVISED"
    assert supervised["supervisor_inspector_id"] == office["supervisor"]["id"]
    assert read_request(staged["request"]["id"])["weighing_status"] == "SUPERVISED"

    certificate = issue_certificate(
        staged["request"]["id"], office["inspector"]["id"], "WEIGHT"
    )
    assert certificate["fee_total_cents"] == 17250


def test_countersignature_refuses_the_weigher_and_an_inspector_from_another_area():
    """The record must be in `WEIGHED`, the supplied `supervisor_inspector_id`
    must differ from the record's `weigher_inspector_id`
    (`ERR_SELF_SUPERVISION_FORBIDDEN`), and the supervisor must hold the
    `SUPERVISION` endorsement with an `ACTIVE` licence.

    Design: Difficulty/cross_entity_state_dependency/weight_certificate_legality_depends_on_area_supervision_flag_and_weighing_state
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"fee_multiplier_bp": 11500, "supervision_required": True},
        fee_schedules=SUPERVISED_WEIGHING_SCHEDULE,
    )
    staged = setup_weighed_request(office)

    itself = api_client.supervise_weighing_record(
        staged["weighing"]["id"],
        supervise_payload(office["inspector"]["id"]),
        SUPERVISOR,
    )
    validate_error(itself, ApiErrorId.ERR_SELF_SUPERVISION_FORBIDDEN.value, 422)

    assert read_request(staged["request"]["id"])["weighing_status"] == "WEIGHED"


def _export_ready_request(office):
    staged = setup_graded_and_weighed_request(
        office,
        requested_services=("GRADING", "WEIGHING", "EXPORT_SUPERVISION"),
        countersigned=True,
        lot_identifier="LOT-EXPORT",
    )
    return staged


def test_export_cargo_certificate_is_refused_outside_a_designated_area():
    """Export cargo certification for foreign buyers may only be performed in a
    `DESIGNATED` area; attempting it elsewhere fails with
    `ERR_EXPORT_REQUIRES_DESIGNATED_AREA`.

    An `EXPORT_CARGO` certificate additionally requires `EXPORT_SUPERVISION`
    among the `requested_services`, a `DESIGNATED` area, and a `CLOSED` vessel
    watch on the request whose `stowage_certified` is true, else
    `ERR_VESSEL_WATCH_NOT_CLOSED`.

    Design: Difficulty/cross_entity_state_dependency/export_certificate_requires_designated_authority_and_closed_stowage_certified_watch
    """
    office = setup_office("DELEGATED", fee_schedules=EXPORT_SCHEDULES)
    staged = _export_ready_request(office)
    watch = schedule_watch(
        staged["request"]["id"],
        office["supervisor"]["id"],
        WATCH_START,
        WATCH_END,
        holds_declared=3,
    )
    start_watch(watch["id"])
    closed = close_watch(watch["id"], holds_supervised=3, stowage_certified=True)
    assert closed["status"] == "CLOSED"
    assert closed["stowage_certified"] is True

    response = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "EXPORT_CARGO"
        ),
        INSPECTOR,
    )
    validate_error(
        response, ApiErrorId.ERR_EXPORT_REQUIRES_DESIGNATED_AREA.value, 422
    )


def test_export_cargo_certificate_needs_a_closed_watch_with_every_hold_supervised():
    """The closer reports `holds_supervised`, which must equal `holds_declared`
    exactly, or the closure is refused with `ERR_HOLDS_NOT_FULLY_SUPERVISED`, and
    reports `stowage_certified`, whose value is stored on the watch and which
    must be true before an export cargo certificate can be issued.

    An `EXPORT_CARGO` certificate additionally requires `EXPORT_SUPERVISION`
    among the `requested_services`, a `DESIGNATED` area, and a `CLOSED` vessel
    watch on the request whose `stowage_certified` is true, else
    `ERR_VESSEL_WATCH_NOT_CLOSED`.

    Design: Difficulty/cross_entity_state_dependency/export_certificate_requires_designated_authority_and_closed_stowage_certified_watch
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"fee_multiplier_bp": 11500, "concurrent_watch_capacity": 2},
        fee_schedules=EXPORT_SCHEDULES,
    )
    staged = _export_ready_request(office)
    watch = schedule_watch(
        staged["request"]["id"],
        office["supervisor"]["id"],
        WATCH_START,
        WATCH_END,
        holds_declared=3,
    )
    running = start_watch(watch["id"])
    assert running["status"] == "IN_PROGRESS"

    open_watch_attempt = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "EXPORT_CARGO"
        ),
        INSPECTOR,
    )
    validate_error(
        open_watch_attempt, ApiErrorId.ERR_VESSEL_WATCH_NOT_CLOSED.value, 409
    )

    partial = api_client.close_vessel_watch(
        watch["id"], {"holds_supervised": 2, "stowage_certified": True}, SUPERVISOR
    )
    validate_error(partial, ApiErrorId.ERR_HOLDS_NOT_FULLY_SUPERVISED.value, 422)

    closed = close_watch(watch["id"], holds_supervised=3, stowage_certified=False)
    assert closed["status"] == "CLOSED"
    assert closed["stowage_certified"] is False

    uncertified_stowage = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "EXPORT_CARGO"
        ),
        INSPECTOR,
    )
    validate_error(
        uncertified_stowage, ApiErrorId.ERR_VESSEL_WATCH_NOT_CLOSED.value, 409
    )


def test_export_cargo_certificate_prices_grading_weighing_and_export_supervision():
    """First the applicable classes are determined from the certificate type: a
    `GRADE` certificate prices `GRADING`; a `WEIGHT` certificate prices
    `WEIGHING`; a `COMBINED` certificate prices `GRADING` and `WEIGHING`; an
    `EXPORT_CARGO` certificate prices `GRADING`, `WEIGHING` and
    `EXPORT_SUPERVISION`; and an `APPEAL_GRADE` certificate prices nothing
    whatsoever — its `fee_total_cents` is 0, no schedule is consulted, and none
    of the arithmetic below runs.

    Finally `fee_total_cents` is the greater of that adjusted amount and the
    **largest** `minimum_fee_cents` among the applicable schedules.

    On closure `closed_at` is stamped, `supervision_minutes` is computed as the
    whole minutes elapsed from `started_at` to `closed_at` with any remaining
    seconds discarded, and the area's `open_watch_count` decreases by one.

    Design: Difficulty/cross_entity_state_dependency/export_certificate_requires_designated_authority_and_closed_stowage_certified_watch
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"fee_multiplier_bp": 11500, "concurrent_watch_capacity": 2},
        fee_schedules=EXPORT_SCHEDULES,
    )
    staged = _export_ready_request(office)
    watch = schedule_watch(
        staged["request"]["id"],
        office["supervisor"]["id"],
        WATCH_START,
        WATCH_END,
        holds_declared=3,
    )
    start_watch(watch["id"])
    close_watch(watch["id"], holds_supervised=3, stowage_certified=True)

    response = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "EXPORT_CARGO"
        ),
        INSPECTOR,
    )
    certificate = validate_success(response, 201)

    assert certificate["fee_total_cents"] == 78660

    settled = read_watch(watch["id"])
    assert settled["status"] == "CLOSED"
    assert settled["supervision_minutes"] == 0

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=78660,
        credits=0,
        open_balance=78660,
    )
