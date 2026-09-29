"""
The seat pool as a shared resource: contention, cascades and the summer archive.

Three layers of the district's seat arithmetic are exercised here. The first is
contention: every write that reshapes the seat pool — provisioning an identity or
re-cutting one building's grant — must carry the version of the licence the client
last saw, so two operators working on unrelated rows of the same licence cannot
silently overwrite each other's picture of the money. The second is the summer
cascade, four hops deep, whose safety comes entirely from the state check on its
first hop: a second rollover must move nothing, because replaying a cascade would
drop already-dropped classes and refund an already-refunded seat. The third is
archival: an archived class is a class with a status, not a deleted row, so the
district still lists it and every reference into it still resolves, while the
vendor-facing feed drops it unless the caller asks for it by name.

These tests exercise those layers against a live service over HTTP.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.constants import (
    CLOCK_IN_WINDOW,
    STANDARD_PRICE_PER_SEAT_CENTS,
    TERM_ARCHIVED_ACCESS_EXPIRES_AT,
    TERM_END_DATE,
)
from test_helpers.types import (
    GradeBand,
    IdentityStatus,
    MeetingDay,
    RosterStatus,
    SeatStatus,
    SectionStatus,
    TermState,
    VendorAppStatus,
)

# The morning of the term's last day: the earliest instant at which the district
# is allowed to roll the term over.
CLOCK_ON_TERM_END = TERM_END_DATE + "T09:00:00Z"


def test_a_second_provisioning_on_a_stale_licence_view_is_refused_and_replays_cleanly(api):
    """Two identities for two different children contend through the licence version.

    Provisioning carries "`expected_vendor_app_version` equal to the current
    `version` of the license reached through the supplied `building_allocation_id`",
    and "if the license's `version` has advanced since the client read it, the
    provisioning request is rejected with `ERR_STALE_VENDOR_APP_VERSION` (HTTP 412)"
    — precisely because "provisioning a seat for a different subject is a perfectly
    legitimate act at any time, so no state precondition can stand in for this
    check". The refusal is inert: it mints no account, burns no seat and takes no
    charge, so replaying the identical request against the refreshed version
    succeeds unchanged.

    Design: Corner/Cross-Cutting Complexity Layers/occ_app_account_create_stale_vendor_app_version_rejected
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=2,
        grade_level=4,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    first_child, second_child = world["student_ids"]
    observed_version = fx.vendor_app_version(api, world["vendor_app_id"])
    assert observed_version == 2

    first_account = validate_success(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], observed_version, student_id=first_child
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert first_account["seat_status"] == SeatStatus.RESERVED
    assert first_account["seat_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS

    after_first = fx.read_vendor_app(api, world["vendor_app_id"])
    assert after_first["version"] == 3
    assert after_first["consumed_seats"] == 1

    refused = api.create_app_account(
        f.app_account_payload(
            world["allocation_id"], observed_version, student_id=second_child
        ),
        users.IDENTITY_ADMIN,
    )
    validate_error(refused, errors.ERR_STALE_VENDOR_APP_VERSION, 412)

    _rows, meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, student_id=second_child)
    )
    assert meta["total_count"] == 0

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 1
    assert allocation["allocated_seats"] == 4

    guarded = fx.read_vendor_app(api, world["vendor_app_id"])
    assert guarded["consumed_seats"] == 1
    assert guarded["committed_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS
    assert guarded["version"] == 3

    replayed = validate_success(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], guarded["version"], student_id=second_child
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert replayed["seat_status"] == SeatStatus.RESERVED

    after_replay = fx.read_vendor_app(api, world["vendor_app_id"])
    assert after_replay["version"] == 4
    assert after_replay["consumed_seats"] == 2
    assert after_replay["committed_charge_cents"] == 2 * STANDARD_PRICE_PER_SEAT_CENTS


def test_re_cutting_a_second_building_on_a_stale_licence_view_is_refused(api):
    """Two building administrators re-cut two different buildings and still collide.

    A re-cut "must carry `expected_vendor_app_version` equal to the current
    `version` of the license that owns the allocation named in the path", and "a
    mismatch is rejected with `ERR_STALE_VENDOR_APP_VERSION` (HTTP 412)" — the
    guarded counter is the parent licence's version, never the version of the row
    being written, because "re-cutting two different buildings are both legitimate
    operations that no state precondition would refuse". The refused building's own
    grant and version are therefore untouched, and the replay against the refreshed
    version lands, leaving the district pool at the licence's purchased total minus
    the two grants.

    Design: Corner/Cross-Cutting Complexity Layers/occ_building_allocation_patch_stale_vendor_app_version_rejected
    """
    world = fx.licensed_district(
        api,
        [
            {"grade_band": GradeBand.ELEMENTARY, "student_count": 2, "grade_level": 4},
            {"grade_band": GradeBand.ELEMENTARY, "student_count": 0},
        ],
        clock=CLOCK_IN_WINDOW,
        total_seats=6,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    populated_id, empty_id = world["school_ids"]
    populated_allocation = world["allocations_by_school"][populated_id]
    empty_allocation = world["allocations_by_school"][empty_id]
    assert populated_allocation["allocated_seats"] == 6
    assert empty_allocation["allocated_seats"] == 0

    observed_version = fx.vendor_app_version(api, world["vendor_app_id"])
    assert observed_version == 2

    recut = validate_success(
        api.update_building_allocation(
            populated_allocation["id"],
            f.allocation_patch(3, observed_version),
            users.building_license_admin(populated_id),
        )
    )
    assert recut["allocated_seats"] == 3
    assert recut["version"] == 2

    after_recut = fx.read_vendor_app(api, world["vendor_app_id"])
    assert after_recut["version"] == 3
    assert after_recut["unallocated_seats"] == 3

    refused = api.update_building_allocation(
        empty_allocation["id"],
        f.allocation_patch(2, observed_version),
        users.building_license_admin(empty_id),
    )
    validate_error(refused, errors.ERR_STALE_VENDOR_APP_VERSION, 412)

    untouched = fx.read_allocation(api, empty_allocation["id"])
    assert untouched["allocated_seats"] == 0
    assert untouched["version"] == 1

    guarded = fx.read_vendor_app(api, world["vendor_app_id"])
    assert guarded["unallocated_seats"] == 3
    assert guarded["version"] == 3

    replayed = validate_success(
        api.update_building_allocation(
            empty_allocation["id"],
            f.allocation_patch(2, guarded["version"]),
            users.building_license_admin(empty_id),
        )
    )
    assert replayed["allocated_seats"] == 2

    after_replay = fx.read_vendor_app(api, world["vendor_app_id"])
    assert after_replay["version"] == 4
    assert after_replay["unallocated_seats"] == 1


def test_the_licence_version_moves_on_writes_to_three_generations_and_never_on_a_read(api):
    """The licence version is a clock over the whole seat aggregate, not over one row.

    Whenever a cascade or a write reaches a record, "that record's own `updated_at`
    and `version` move, exactly as if it had been written directly", and the writes
    that reach the licence include activation, an amendment, provisioning an account
    against one of its allocations ("increments the license's `version` by one"),
    re-cutting an allocation ("the license's `unallocated_seats` is recomputed with
    the license's own `version` incremented as well") and releasing a seat. Reads
    are not writes, so a client may safely re-read the licence, the allocation or
    the account before retrying a guarded write.

    Design: Corner/Cross-Cutting Complexity Layers/occ_vendor_app_version_increments_on_every_write_and_never_on_reads
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
        activate=False,
    )
    licence_id = world["vendor_app_id"]
    assert world["vendor_app"]["version"] == 1

    activated = fx.activate_license(api, licence_id)
    assert activated["status"] == VendorAppStatus.ACTIVE
    assert activated["version"] == 2

    allocation = fx.allocation_for_school(api, licence_id, world["school_id"])
    assert allocation["allocated_seats"] == 4
    assert fx.vendor_app_version(api, licence_id) == 2

    amended = validate_success(
        api.update_vendor_app(
            licence_id,
            f.vendor_app_patch(total_seats=6),
            users.VENDOR_INTEGRATION_MANAGER,
        )
    )
    assert amended["version"] == 3
    assert fx.read_vendor_app(api, licence_id)["version"] == 3

    account = validate_success(
        api.create_app_account(
            f.app_account_payload(
                allocation["id"], 3, student_id=world["student_id"]
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert account["version"] == 1
    after_grandchild = fx.read_vendor_app(api, licence_id)
    assert after_grandchild["version"] == 4

    recut = validate_success(
        api.update_building_allocation(
            allocation["id"],
            f.allocation_patch(4, after_grandchild["version"]),
            users.DATA_GOVERNANCE_OFFICER,
        )
    )
    # The allocation was minted at version 1 by the split, then the provisioning
    # above incremented its consumed_seats -- "a counter recomputation" that
    # moves version -- so this re-cut is the allocation's third generation.
    assert recut["version"] == 3
    assert fx.read_vendor_app(api, licence_id)["version"] == 5

    released = fx.release_seat(api, account["id"])
    assert released["seat_status"] == SeatStatus.RELEASED
    assert released["version"] == 2

    after_release = fx.read_vendor_app(api, licence_id)
    assert after_release["version"] == 6
    assert after_release["consumed_seats"] == 0
    assert after_release["committed_charge_cents"] == 0
    assert after_release["unallocated_seats"] == 2

    fx.read_allocation(api, allocation["id"])
    fx.read_account(api, account["id"])
    assert fx.vendor_app_version(api, licence_id) == 6


def _rolled_over_district(api):
    """
    One building with a teacher-matched class, one enrolled child holding a seat on
    a four-seat licence, rolled over on the morning of the term's last day.
    """
    world = fx.rostered_section(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
    )
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    world["vendor_app"] = fx.activate_license(api, vendor_app["id"])
    world["vendor_app_id"] = vendor_app["id"]
    allocation = fx.allocation_for_school(api, vendor_app["id"], world["school_id"])
    world["allocation"] = allocation
    world["allocation_id"] = allocation["id"]
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=world["student_id"],
    )
    world["account"] = account
    world["account_id"] = account["id"]

    fx.set_clock(api, CLOCK_ON_TERM_END)
    world["term"] = fx.rollover_term(api, world["term_id"])
    return world


def test_a_second_summer_rollover_is_refused_and_double_refunds_nothing(api):
    """The state check on the first hop is what makes the four-hop summer cascade safe.

    Rollover requires the term to be `ACTIVE`, "else `ERR_TERM_NOT_ACTIVE`", and
    that check sits in the state tier ahead of every effect. So the second attempt
    moves nothing four hops down: the archived class stays archived, the dropped
    row keeps the drop date stamped "with the term's `end_date`", the parked
    identity keeps `seat_status` `RELEASED` with `identity_status` `SUSPENDED` — and
    since the release ran at a clock date after the term's add/drop cutoff, its
    refund was zero and stays zero, leaving `committed_charge_cents` at the one seat
    charged. Neither the allocation's `consumed_seats` nor the licence's `version`
    moves again.

    Design: Corner/Cross-Cutting Complexity Layers/cascade_second_rollover_rejected_leaves_counters_unchanged
    """
    world = _rolled_over_district(api)

    refused = api.rollover_term(world["term_id"], users.DATA_GOVERNANCE_OFFICER)
    validate_error(refused, errors.ERR_TERM_NOT_ACTIVE, 409)

    term = validate_success(api.get_term(world["term_id"], users.DATA_GOVERNANCE_OFFICER))
    assert term["state"] == TermState.ROLLED_OVER
    assert term["version"] == 3
    assert term["archived_access_expires_at"] == TERM_ARCHIVED_ACCESS_EXPIRES_AT

    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR)
    )
    assert section["status"] == SectionStatus.ARCHIVED

    enrollment = validate_success(
        api.get_enrollment(world["enrollment_id"], users.ROSTER_OPERATOR)
    )
    assert enrollment["roster_status"] == RosterStatus.DROPPED
    assert enrollment["drop_effective_date"] == TERM_END_DATE

    account = fx.read_account(api, world["account_id"])
    assert account["seat_status"] == SeatStatus.RELEASED
    assert account["identity_status"] == IdentityStatus.SUSPENDED
    assert account["refunded_charge_cents"] == 0

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 0
    assert allocation["allocated_seats"] == 4

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["consumed_seats"] == 0
    assert licence["unallocated_seats"] == 0
    assert licence["committed_charge_cents"] == STANDARD_PRICE_PER_SEAT_CENTS
    assert licence["version"] == 4


def test_an_archived_class_stays_listed_and_every_reference_into_it_still_resolves(api):
    """Archival is a status, not a deletion, so last year's class is still reachable.

    Rollover moves "every section of this term whose `status` is `ACTIVE`" to
    `ARCHIVED`; nothing in the contract removes the row, and the district's own
    section list is filtered only by the filters the caller supplies — `status`
    among them. Reading the archived section itself is permitted "while the clock
    instant is strictly earlier than `archived_access_expires_at`", which the
    morning of the term's last day is. The children of the archived class keep
    resolving too: its enrollment is `DROPPED` with the term's `end_date` stamped,
    and the parked account still names the allocation it drew its seat from.

    Design: Corner/Cross-Cutting Complexity Layers/soft_delete_archival_default_excludes_archived_but_references_stay_valid
    """
    world = _rolled_over_district(api)

    rows, meta = validate_paginated(
        api.list_sections(users.ROSTER_OPERATOR, term_id=world["term_id"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["section_id"]
    assert rows[0]["status"] == SectionStatus.ARCHIVED

    _live_rows, live_meta = validate_paginated(
        api.list_sections(
            users.ROSTER_OPERATOR,
            term_id=world["term_id"],
            status=SectionStatus.ACTIVE,
        )
    )
    assert live_meta["total_count"] == 0

    inside_window = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR)
    )
    assert inside_window["status"] == SectionStatus.ARCHIVED

    enrollment_rows, enrollment_meta = validate_paginated(
        api.list_enrollments(users.ROSTER_OPERATOR, section_id=world["section_id"])
    )
    assert enrollment_meta["total_count"] == 1
    assert enrollment_rows[0]["section_id"] == world["section_id"]
    assert enrollment_rows[0]["roster_status"] == RosterStatus.DROPPED
    assert enrollment_rows[0]["drop_effective_date"] == TERM_END_DATE

    account_rows, account_meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN, building_allocation_id=world["allocation_id"]
        )
    )
    assert account_meta["total_count"] == 1
    assert account_rows[0]["building_allocation_id"] == world["allocation_id"]
    assert account_rows[0]["seat_status"] == SeatStatus.RELEASED
    assert account_rows[0]["identity_status"] == IdentityStatus.SUSPENDED


def test_the_vendor_feed_hides_the_archived_class_until_it_is_asked_for_by_name(api):
    """The vendor-facing read is the asymmetric half of archival.

    Feed scope takes "the sections whose `term_id` matches the license's `term_id`,
    whose `status` is `ACTIVE`" for an ordinary read, so an archived class simply is
    not there; "setting `include_archived` to true reaches `ARCHIVED` sections and
    is gated by the retention window", which is open on the term's last day. The
    archived class then comes back as a shell: the enrollments in scope are only
    those whose `roster_status` is `PENDING_ADD`, `ACTIVE` or `PENDING_DROP` and
    "`DROPPED` rows are excluded", so the class the rollover emptied carries no
    students and therefore no derived usernames.

    Design: Corner/Cross-Cutting Complexity Layers/soft_delete_archival_default_excludes_archived_but_references_stay_valid
    """
    world = _rolled_over_district(api)

    default_feed = validate_success(
        api.get_roster_feed(world["vendor_app_id"], users.VENDOR_INTEGRATION_MANAGER)
    )
    assert default_feed["vendor_app_id"] == world["vendor_app_id"]
    assert default_feed["section_count"] == 0
    assert len(default_feed["sections"]) == 0
    assert default_feed["student_count"] == 0

    archived_feed = validate_success(
        api.get_roster_feed(
            world["vendor_app_id"],
            users.VENDOR_INTEGRATION_MANAGER,
            include_archived="true",
        )
    )
    assert archived_feed["section_count"] == 1
    assert len(archived_feed["sections"]) == 1
    assert archived_feed["student_count"] == 0
    assert archived_feed["teacher_count"] == 0
    assert archived_feed["usernames"] == []
