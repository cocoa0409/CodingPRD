"""What one row's state does to its neighbours, and the quantities that never drift.

Nothing in this programme stands alone. A checklist template that retires takes
the catalogue's future with it while leaving its open worksheets untouched; a
certification's status decides what may be advertised about the car; a dealer's
privilege decides which of its own operations still run. Two scarce resources are
shared across rows and so must be reserved without gaps and without collisions —
a technician's calendar, whose buffered slots may not even touch, and a vehicle's
coverage timeline, whose intervals may touch but never overlap. The file closes on
the two conserved quantities the programme is answerable for: the money on a
dealer's ledger and the single certification slot on a vehicle.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_certification,
    activate_many,
    adjudication_payload,
    approve_certification,
    assert_certification_number,
    assert_dealer_ledger_conservation,
    assert_instant_equals,
    assert_vehicle_slot_invariant,
    audit_samples_of,
    create_certification_payload,
    create_draft_template,
    create_inspection_payload,
    create_listing,
    create_listing_payload,
    create_published_template,
    create_technician,
    create_vehicle,
    decertify,
    documents_without_reconditioning,
    draw_audit_run,
    get_success_data,
    listings_of,
    open_inspection_for,
    passed_inspection,
    read_certification,
    read_dealer,
    read_inspection,
    read_vehicle,
    record_finding,
    record_history_event,
    reject_certification,
    set_clock,
    set_privilege,
    submit_certification,
    submitted_certification,
    syndicate_listing,
    syndicate_payload,
    validate_error,
    validate_success,
    vehicle_version,
)

DEFAULT_FEE_CENTS = 120400
LATE_CREDENTIAL_EXPIRY = "2029-01-01T00:00:00Z"


def _open_attempt(api, program, vehicle_id, template_id, started_at, **overrides):
    """The raw open-inspection call against a named template."""
    return api.create_inspection(
        create_inspection_payload(
            vehicle_id,
            program.technician_id,
            template_id,
            started_at=started_at,
            **overrides,
        ),
        program.dealer_headers,
    )


def _template(api, template_id):
    return validate_success(api.get_checklist_template(template_id, ADMIN))


def _listing(api, certification_id, listing_id):
    for row in listings_of(api, certification_id):
        if row["id"] == listing_id:
            return row
    raise AssertionError("a listing must be discoverable under its certification")


def _inspections_of(api, technician_id):
    return validate_success(
        api.list_inspections(ADMIN, params={"technician_id": technician_id})
    )


# ────────── the checklist catalogue decides what may be inspected ─────────

def test_a_retired_template_keeps_its_open_worksheets_but_takes_no_new_ones(
    api, program
):
    """Publishing a successor retires the incumbent and closes it to new work.

    PRD §3.1: "every *other* template that is currently `PUBLISHED` and whose
    `effective_from` is on or before the newly published template's
    `effective_from` is moved `PUBLISHED → RETIRED`, and each of those retired
    rows has its own `version` incremented by 1 as well."
    PRD §3.1: "Inspections already opened against a retired template keep
    referencing it and are unaffected, but no *new* inspection may name it;
    naming a template that is `DRAFT` or `RETIRED` when opening an inspection is
    rejected with `ERR_TEMPLATE_NOT_PUBLISHED`."
    PRD §3.1: "Publishing moves a template `DRAFT → PUBLISHED`, sets
    `published_at` to the logical clock, and increments the template's `version`
    by 1."

    Design: Difficulty/cross_entity_state_dependency/inspection_blocked_by_retired_template
    """
    incumbent_id = program.template_id
    in_flight = open_inspection_for(api, program)
    assert in_flight.inspection["template_id"] == incumbent_id
    standing = _template(api, incumbent_id)
    assert standing["status"] == "PUBLISHED"

    successor = create_published_template(api, effective_from="2026-02-01")
    assert successor["status"] == "PUBLISHED"
    assert_instant_equals(
        successor["published_at"], "2026-08-01T00:00:00Z", "published_at"
    )

    retired = _template(api, incumbent_id)
    assert retired["status"] == "RETIRED"
    assert retired["version"] == standing["version"] + 1

    stranded = create_vehicle(api)
    refused = _open_attempt(
        api, program, stranded["id"], incumbent_id, program.next_start()
    )
    validate_error(refused, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED)
    assert read_vehicle(api, stranded["id"])["cpo_state"] == "NOT_CERTIFIED"

    accepted = get_success_data(
        _open_attempt(
            api, program, stranded["id"], successor["id"], program.next_start()
        ),
        expected_status=201,
    )
    assert accepted["template_id"] == successor["id"]

    # The worksheet opened before the retirement is untouched by it.
    unaffected = read_inspection(api, in_flight.inspection_id)
    assert unaffected["template_id"] == incumbent_id
    assert unaffected["status"] == "DRAFT"


def test_publication_spares_a_sibling_dated_later_and_never_admits_a_draft(
    api, program
):
    """Retirement reaches only the templates a successor supersedes in time.

    PRD §3.1: "every *other* template that is currently `PUBLISHED` and whose
    `effective_from` is on or before the newly published template's
    `effective_from` is moved `PUBLISHED → RETIRED`"
    PRD §3.1: "naming a template that is `DRAFT` or `RETIRED` when opening an
    inspection is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`. `RETIRED` is
    terminal for a template."
    PRD §2.10: "8. State legality: the target resource is in a state from which
    the requested transition is declared — otherwise the state-conflict
    identifier for that resource type."

    Design: Difficulty/cross_entity_state_dependency/inspection_blocked_by_retired_template
    """
    incumbent_id = program.template_id
    later = create_published_template(api, effective_from="2026-03-01")
    earlier = create_published_template(api, effective_from="2026-02-01")

    assert _template(api, incumbent_id)["status"] == "RETIRED"
    assert _template(api, later["id"])["status"] == "PUBLISHED", (
        "a sibling effective after the newcomer keeps its standing"
    )
    assert _template(api, earlier["id"])["status"] == "PUBLISHED"

    never_published = create_draft_template(api, effective_from="2026-04-01")
    assert never_published["status"] == "DRAFT"

    car = create_vehicle(api)
    for blocked in (incumbent_id, never_published["id"]):
        validate_error(
            _open_attempt(api, program, car["id"], blocked, program.next_start()),
            ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED,
        )
    assert read_vehicle(api, car["id"])["cpo_state"] == "NOT_CERTIFIED"

    on_the_later_one = get_success_data(
        _open_attempt(api, program, car["id"], later["id"], program.next_start()),
        expected_status=201,
    )
    assert on_the_later_one["template_id"] == later["id"]
    assert read_vehicle(api, car["id"])["cpo_state"] == "CERTIFICATION_PENDING"


# ───────── the certification's status decides what may be advertised ─────────

def test_a_listing_needs_a_live_certification_at_every_step(api, program):
    """Drafting, syndicating and re-syndicating each re-read the badge's standing.

    PRD §3.8: "The certification must be live — creating a listing against one
    that is not `ACTIVE` or `UNDER_AUDIT` is rejected with
    `ERR_CERTIFICATION_NOT_ACTIVE`"
    PRD §3.8: "A new listing begins in `DRAFT` with `syndicated_at`,
    `syndicated_snapshot_version`, `withdrawn_at`, `withdrawal_reason`, and
    `removal_due_at` all null."
    PRD §3.8: "The listing must not be `WITHDRAWN` — syndicating a withdrawn
    listing is rejected with `ERR_LISTING_WITHDRAWN`"
    PRD §3.10: "The fee is credited — meaning `fee_credited_cents` is set equal
    to `fee_charged_cents` — **only** when the reason is `POST_AUDIT_FAIL`; every
    other reason leaves `fee_credited_cents` at 0"

    Design: Difficulty/cross_entity_state_dependency/listing_lifecycle_blocked_by_certification_state
    """
    walk = submitted_certification(api, program)
    premature = api.create_listing(
        create_listing_payload(walk.certification_id), program.dealer_headers
    )
    validate_error(premature, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)

    walk.certification = approve_certification(api, walk.certification_id)
    listing = create_listing(api, program.dealer_headers, walk.certification_id)
    assert listing["status"] == "DRAFT"
    assert listing["syndicated_at"] is None
    assert listing["withdrawn_at"] is None
    assert listing["removal_due_at"] is None

    live = read_certification(api, walk.certification_id)
    published = syndicate_listing(
        api, listing["id"], program.dealer_headers, live["version"]
    )
    assert published["status"] == "SYNDICATED"
    assert_instant_equals(
        published["syndicated_at"], "2026-08-01T00:00:00Z", "syndicated_at"
    )
    # §3.8 records the snapshot as the certification's `version` *as observed
    # after* the increment syndication itself performs.
    assert published["syndicated_snapshot_version"] == live["version"] + 1
    assert_instant_equals(
        read_certification(api, walk.certification_id)["listing_syndicated_at"],
        "2026-08-01T00:00:00Z",
        "listing_syndicated_at",
    )

    withdrawn_by_cascade = decertify(api, walk.certification_id, "ADMIN_ACTION")
    assert withdrawn_by_cascade["fee_credited_cents"] == 0
    cascaded = _listing(api, walk.certification_id, listing["id"])
    assert cascaded["status"] == "WITHDRAWN"
    assert cascaded["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"
    assert_instant_equals(
        cascaded["withdrawn_at"], "2026-08-01T00:00:00Z", "withdrawn_at"
    )
    assert_instant_equals(
        cascaded["removal_due_at"], "2026-08-03T00:00:00Z", "removal_due_at"
    )

    again = api.syndicate_listing(
        listing["id"],
        syndicate_payload(withdrawn_by_cascade["version"]),
        program.dealer_headers,
    )
    validate_error(again, ApiErrorId.ERR_LISTING_WITHDRAWN)

    assert read_vehicle(api, walk.vehicle_id)["cpo_state"] == "DECERTIFIED"
    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert_dealer_ledger_conservation(dealer)


def test_an_audited_certification_may_be_drafted_against_but_not_syndicated(
    api, program
):
    """`UNDER_AUDIT` is live enough to advertise against but not to publish.

    PRD §3.8: "creating a listing against one that is not `ACTIVE` or
    `UNDER_AUDIT` is rejected with `ERR_CERTIFICATION_NOT_ACTIVE`"
    PRD §3.8: "and its certification must be `ACTIVE`, otherwise
    `ERR_CERTIFICATION_NOT_ACTIVE`."
    PRD §3.10: "The certification itself moves `ACTIVE → UNDER_AUDIT`, its
    `audit_sampled` flag is set to true, and its `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/listing_lifecycle_blocked_by_certification_state
    """
    walk = active_certification(api, program)
    run = draw_audit_run(api)
    assert run["selected_certification_ids"] == [walk.certification_id]
    under_audit = read_certification(api, walk.certification_id)
    assert under_audit["status"] == "UNDER_AUDIT"

    listing = create_listing(api, program.dealer_headers, walk.certification_id)
    assert listing["status"] == "DRAFT"

    refused = api.syndicate_listing(
        listing["id"],
        syndicate_payload(under_audit["version"]),
        program.dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)
    assert _listing(api, walk.certification_id, listing["id"])["status"] == "DRAFT"

    sample = audit_samples_of(api, walk.certification_id)[-1]
    record_finding(api, sample["id"], "PASS", "NONE")
    cleared = read_certification(api, walk.certification_id)
    assert cleared["status"] == "ACTIVE"

    published = syndicate_listing(
        api, listing["id"], program.dealer_headers, cleared["version"]
    )
    assert published["status"] == "SYNDICATED"
    # §3.8: the snapshot names the generation the publication itself produced.
    assert published["syndicated_snapshot_version"] == cleared["version"] + 1


# ────────── the dealer's privilege decides which of its writes run ─────────

def test_suspension_blocks_the_inspection_and_the_submission_probation_allows(
    api, program
):
    """A suspended dealer cannot inspect or submit; a dealer on probation can do both.

    PRD §3.3: "The inspecting dealer's `privilege_status` must not be
    `SUSPENDED`, otherwise `ERR_DEALER_PRIVILEGE_SUSPENDED`."
    PRD §3.6: "The submitting dealer must not be `SUSPENDED`, otherwise
    `ERR_DEALER_PRIVILEGE_SUSPENDED`."
    PRD §3.7: "The certifying dealer's `privilege_status` must be `ACTIVE` or
    `PROBATION` — approval is the one operation that tolerates probation, and a
    `SUSPENDED` dealer is refused with `ERR_DEALER_PRIVILEGE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/dealer_privilege_gates_inspection_submission_and_syndication
    """
    walk = passed_inspection(api, program)
    observed = vehicle_version(api, walk.vehicle_id)
    set_privilege(api, program.dealer_id, "SUSPENDED")

    barred_car = create_vehicle(api)
    blocked_open = _open_attempt(
        api, program, barred_car["id"], program.template_id, program.next_start()
    )
    validate_error(blocked_open, ApiErrorId.ERR_DEALER_PRIVILEGE_SUSPENDED)
    assert read_vehicle(api, barred_car["id"])["cpo_state"] == "NOT_CERTIFIED"

    body = create_certification_payload(
        walk.vehicle_id,
        walk.inspection_id,
        observed,
        documents=documents_without_reconditioning("S"),
    )
    blocked_submit = api.create_certification(body, program.dealer_headers)
    validate_error(blocked_submit, ApiErrorId.ERR_DEALER_PRIVILEGE_SUSPENDED)
    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 0
    assert dealer["active_certification_count"] == 0

    set_privilege(api, program.dealer_id, "PROBATION")
    accepted = get_success_data(
        api.create_certification(body, program.dealer_headers), expected_status=201
    )
    assert accepted["status"] == "SUBMITTED"

    certification = approve_certification(api, accepted["id"])
    assert certification["status"] == "ACTIVE"
    assert certification["fee_charged_cents"] == DEFAULT_FEE_CENTS
    assert read_dealer(api, program.dealer_id)["privilege_status"] == "PROBATION"


def test_probation_may_draft_an_aggregator_listing_but_never_publish_it(api, program):
    """The aggregator channel demands an unblemished dealer at syndication only.

    PRD §3.8: "a listing whose `channel` is `THIRD_PARTY_AGGREGATOR` demands a
    dealer whose `privilege_status` is exactly `ACTIVE`. A dealer on `PROBATION`
    may therefore freely draft an aggregator listing but may never publish it,
    while it retains full access to `OEM_SITE` and `DEALER_SITE`; the refusal on
    the aggregator channel is `ERR_MARKETING_STANDARD_VIOLATION`, and a
    `SUSPENDED` dealer is stopped earlier and more bluntly with
    `ERR_DEALER_PRIVILEGE_SUSPENDED` on any channel."
    PRD §3.9: "listings in `DRAFT` or `SYNDICATED` withdrawn with
    `withdrawal_reason` `DEALER_SUSPENDED` and a `removal_due_at` deadline"

    Design: Difficulty/cross_entity_state_dependency/dealer_privilege_gates_inspection_submission_and_syndication
    """
    walk = active_certification(api, program)
    set_privilege(api, program.dealer_id, "PROBATION")

    aggregator = create_listing(
        api,
        program.dealer_headers,
        walk.certification_id,
        channel="THIRD_PARTY_AGGREGATOR",
    )
    assert aggregator["status"] == "DRAFT"
    live = read_certification(api, walk.certification_id)
    refused = api.syndicate_listing(
        aggregator["id"],
        syndicate_payload(live["version"]),
        program.dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_MARKETING_STANDARD_VIOLATION)
    assert _listing(api, walk.certification_id, aggregator["id"])["status"] == "DRAFT"

    house = create_listing(
        api, program.dealer_headers, walk.certification_id, channel="OEM_SITE"
    )
    published = syndicate_listing(
        api, house["id"], program.dealer_headers, live["version"]
    )
    assert published["status"] == "SYNDICATED"

    set_privilege(api, program.dealer_id, "SUSPENDED")
    for listing_id in (aggregator["id"], house["id"]):
        cascaded = _listing(api, walk.certification_id, listing_id)
        assert cascaded["status"] == "WITHDRAWN"
        assert cascaded["withdrawal_reason"] == "DEALER_SUSPENDED"
        assert_instant_equals(
            cascaded["removal_due_at"], "2026-08-03T00:00:00Z", "removal_due_at"
        )

    # A fresh listing on an untouched channel now fails on privilege, not channel.
    blunt = create_listing(
        api, program.dealer_headers, walk.certification_id, channel="DEALER_SITE"
    )
    stopped = api.syndicate_listing(
        blunt["id"],
        syndicate_payload(read_certification(api, walk.certification_id)["version"]),
        program.dealer_headers,
    )
    validate_error(stopped, ApiErrorId.ERR_DEALER_PRIVILEGE_SUSPENDED)


# ───────────── the technician's calendar: touching is colliding ────────────

def test_buffered_technician_slots_conflict_when_they_merely_touch(api, program):
    """One minute decides the calendar, on both sides of an occupied slot.

    PRD §3.3: "With the default 120-minute slot and 30-minute buffer, an
    inspection begun at 09:00 buffers to the closed interval from 08:30 to
    11:30; a second inspection by the same technician begun at 12:00 buffers to
    the closed interval from 11:30 to 14:30, touches the first at 11:30, and is
    rejected with `ERR_TECHNICIAN_SLOT_CONFLICT`, while one begun at 12:01
    buffers from 11:31 and is accepted."
    PRD §2.12: "two buffered slots that touch at a single instant do conflict."
    PRD §3.3: "An inspection occupies its technician from `started_at` for the
    programme's slot length, which defaults to 120 minutes, giving the
    inspection a derived `slot_end_at` equal to `started_at` plus that slot
    length."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_slot_adjacency_forbidden
    """
    occupied = open_inspection_for(api, program, started_at="2026-07-31T09:00:00Z")
    assert_instant_equals(
        occupied.inspection["slot_end_at"], "2026-07-31T11:00:00Z", "slot_end_at"
    )

    template_id = program.template_id
    touching_above = create_vehicle(api)
    validate_error(
        _open_attempt(
            api, program, touching_above["id"], template_id, "2026-07-31T12:00:00Z"
        ),
        ApiErrorId.ERR_TECHNICIAN_SLOT_CONFLICT,
    )
    clear_above = get_success_data(
        _open_attempt(
            api, program, touching_above["id"], template_id, "2026-07-31T12:01:00Z"
        ),
        expected_status=201,
    )
    assert_instant_equals(
        clear_above["slot_end_at"], "2026-07-31T14:01:00Z", "slot_end_at"
    )

    touching_below = create_vehicle(api)
    validate_error(
        _open_attempt(
            api, program, touching_below["id"], template_id, "2026-07-31T06:00:00Z"
        ),
        ApiErrorId.ERR_TECHNICIAN_SLOT_CONFLICT,
    )
    clear_below = get_success_data(
        _open_attempt(
            api, program, touching_below["id"], template_id, "2026-07-31T05:59:00Z"
        ),
        expected_status=201,
    )
    assert_instant_equals(
        clear_below["slot_end_at"], "2026-07-31T07:59:00Z", "slot_end_at"
    )

    assert len(_inspections_of(api, program.technician_id)) == 3


def test_the_buffer_follows_the_technician_and_not_the_dealership(api, program):
    """The same instant is booked for one inspector and free for the next.

    PRD §3.3: "The candidate is compared against every non-voided inspection of
    the same technician, regardless of which dealer it belongs to, how it turned
    out, or how long ago it happened; voided inspections release their slot
    entirely."
    PRD §3.3: "A conflict exists when the candidate's buffered low bound is at or
    before an occupied buffered high bound and that occupied buffered low bound
    is at or before the candidate's buffered high bound"
    PRD §2.6: "Scheduling: `inspection_slot_minutes` is 120 and
    `technician_buffer_minutes` is 30."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_slot_adjacency_forbidden
    """
    booked_instant = "2026-07-31T09:00:00Z"
    first = open_inspection_for(api, program, started_at=booked_instant)
    assert first.inspection["technician_id"] == program.technician_id

    same_technician = create_vehicle(api)
    validate_error(
        _open_attempt(
            api, program, same_technician["id"], program.template_id, booked_instant
        ),
        ApiErrorId.ERR_TECHNICIAN_SLOT_CONFLICT,
    )

    colleague = open_inspection_for(
        api,
        program,
        technician_id=program.other_technician_id,
        started_at=booked_instant,
    )
    assert colleague.inspection["technician_id"] == program.other_technician_id
    assert_instant_equals(
        colleague.inspection["slot_end_at"], "2026-07-31T11:00:00Z", "slot_end_at"
    )

    assert len(_inspections_of(api, program.technician_id)) == 1
    assert len(_inspections_of(api, program.other_technician_id)) == 1
    assert read_vehicle(api, same_technician["id"])["cpo_state"] == "NOT_CERTIFIED"


# ────── the vehicle's coverage timeline: touching is not colliding ─────

def test_a_retained_coverage_interval_blocks_overlap_but_admits_adjacency(
    api, program
):
    """A sold car's coverage stays reserved, and the next term may start where it ends.

    PRD §3.7: "The retained set is every *other* certification of that vehicle
    that is `ACTIVE` or `UNDER_AUDIT`, plus every certification of that vehicle
    that is `DECERTIFIED` with a decertification reason of `RETAIL_SOLD`."
    PRD §3.7: "a conflict exists when the candidate's start falls strictly
    before a retained interval's end and that retained interval's start falls
    strictly before the candidate's end; adjacency at a shared endpoint is
    explicitly not a conflict. A conflict rejects the approval with
    `ERR_COVERAGE_WINDOW_OVERLAP`."
    PRD §3.2: "A `RETURNED_TO_INVENTORY` event is accepted from either
    `RETAIL_SOLD` or `WHOLESALED` and moves `inventory_state` back to
    `IN_INVENTORY`."

    Design: Difficulty/resource_temporal_overlap/vehicle_coverage_window_adjacency_allowed
    """
    car = create_vehicle(api)
    sold = active_certification(api, program, vehicle=car)
    assert sold.certification["warranty_start_date"] == "2026-08-01"
    assert sold.certification["warranty_end_date"] == "2027-08-01"

    record_history_event(api, car["id"], "RETAIL_SOLD")
    retained = read_certification(api, sold.certification_id)
    assert retained["status"] == "DECERTIFIED"
    assert retained["decertification_reason"] == "RETAIL_SOLD"

    set_clock(api, "2027-07-01T00:00:00Z")
    record_history_event(api, car["id"], "RETURNED_TO_INVENTORY")
    inspector = create_technician(
        api, program.dealer_id, credential_expires_at=LATE_CREDENTIAL_EXPIRY
    )
    walk = passed_inspection(
        api,
        program,
        vehicle=car,
        technician_id=inspector["id"],
        started_at="2027-07-01T00:00:00Z",
        odometer_at_inspection=65000,
    )
    candidate = submit_certification(
        api, program.dealer_headers, walk.vehicle_id, walk.inspection_id
    )

    overlapping = api.adjudicate_certification(
        candidate["id"], adjudication_payload("APPROVE"), ADMIN
    )
    validate_error(overlapping, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP)
    held = read_certification(api, candidate["id"])
    assert held["status"] == "SUBMITTED"
    assert held["activated_at"] is None
    assert held["fee_charged_cents"] == 0

    set_clock(api, "2027-08-01T00:00:00Z")
    adjacent = approve_certification(api, candidate["id"])
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert adjacent["warranty_start_date"] == retained["warranty_end_date"]
    assert adjacent["warranty_end_date"] == "2028-08-01"
    assert adjacent["warranty_end_miles"] == 77000
    # 2007 days at activation is five whole years, two of them chargeable, so the
    # raw surcharge of 43000 is trimmed to the 31465-cent cap.
    assert adjacent["fee_surcharge_cents"] == 31465
    assert adjacent["fee_charged_cents"] == 121365

    assert read_vehicle(api, car["id"])["cpo_state"] == "CERTIFIED"
    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS + 121365
    assert_dealer_ledger_conservation(dealer)


def test_a_released_interval_does_not_block_an_identical_one(api, program):
    """An administratively withdrawn term frees its window completely.

    PRD §3.7: "Certifications that are `REJECTED` or `SUPERSEDED`, and those
    `DECERTIFIED` for any other reason, release their interval entirely."
    PRD §2.5: "Moving the clock is a purely forward-looking act. It never
    rewrites a stored timestamp and never recomputes a window that has already
    been persisted"
    PRD §3.3: "`cpo_state` goes `NOT_CERTIFIED → CERTIFICATION_PENDING`, or
    `DECERTIFIED → CERTIFICATION_PENDING` for a car that has been returned to
    inventory after an earlier withdrawal"

    Design: Difficulty/resource_temporal_overlap/vehicle_coverage_window_adjacency_allowed
    """
    car = create_vehicle(api)
    first = active_certification(api, program, vehicle=car)
    decertify(api, first.certification_id, "ADMIN_ACTION")
    released = read_certification(api, first.certification_id)
    assert released["status"] == "DECERTIFIED"
    assert read_vehicle(api, car["id"])["cpo_state"] == "DECERTIFIED"

    walk = passed_inspection(api, program, vehicle=car)
    assert read_vehicle(api, car["id"])["cpo_state"] == "CERTIFICATION_PENDING"
    second = submit_certification(
        api, program.dealer_headers, walk.vehicle_id, walk.inspection_id
    )
    approved = approve_certification(api, second["id"])

    assert approved["status"] == "ACTIVE"
    assert approved["warranty_start_date"] == released["warranty_start_date"]
    assert approved["warranty_end_date"] == released["warranty_end_date"]
    assert approved["warranty_end_miles"] == released["warranty_end_miles"]
    assert approved["fee_charged_cents"] == DEFAULT_FEE_CENTS

    # The released row keeps its own stored window as the historical record.
    unchanged = read_certification(api, first.certification_id)
    assert unchanged["warranty_start_date"] == "2026-08-01"
    assert unchanged["warranty_end_date"] == "2027-08-01"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == 0
    assert_dealer_ledger_conservation(dealer)


# ──────────────────── the conserved money on the ledger ───────────────────

def test_an_audit_failure_credits_its_fee_and_leaves_the_ledger_reconciled(
    api, program
):
    """The one reason that refunds, alongside one that does not, on one ledger.

    PRD §3.10: "sets its `fee_credited_cents` equal to its `fee_charged_cents`,
    because the programme's own audit invalidated the certification and the
    dealer gets its money back; the dealer's `fee_credited_cents_total` and
    `fee_balance_cents` are recomputed accordingly."
    PRD §3.2: "`fee_balance_cents` is the billed total minus the credited total.
    That balance is the conserved money quantity of the programme: no operation
    may change it except by billing a fee or crediting one, and the two totals
    must always reconcile to it."
    PRD §3.10: "every other reason leaves `fee_credited_cents` at 0, so a dealer
    that sells the car keeps paying for the badge it used."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_on_post_audit_credit
    """
    walks = activate_many(api, program, 2)
    billed = read_dealer(api, program.dealer_id)
    assert billed["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert billed["fee_balance_cents"] == 2 * DEFAULT_FEE_CENTS

    run = draw_audit_run(api)
    assert run["pool_size"] == 2
    assert run["selected_count"] == 1
    assert run["selected_certification_ids"] == [walks[0].certification_id]

    sample = audit_samples_of(api, walks[0].certification_id)[-1]
    record_finding(api, sample["id"], "FAIL", "DOCUMENTATION_MISSING")
    failed = read_certification(api, walks[0].certification_id)
    assert failed["status"] == "DECERTIFIED"
    assert failed["decertification_reason"] == "POST_AUDIT_FAIL"
    assert failed["fee_credited_cents"] == DEFAULT_FEE_CENTS

    credited = read_dealer(api, program.dealer_id)
    assert credited["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert credited["fee_credited_cents_total"] == DEFAULT_FEE_CENTS
    assert credited["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert credited["audit_fail_count"] == 1
    assert credited["audit_fail_rate"] == 1.00
    assert credited["risk_score"] == 40
    assert credited["privilege_status"] == "ACTIVE"
    assert_dealer_ledger_conservation(credited)

    withdrawn = decertify(api, walks[1].certification_id, "ADMIN_ACTION")
    assert withdrawn["fee_credited_cents"] == 0
    settled = read_dealer(api, program.dealer_id)
    assert settled["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert settled["fee_credited_cents_total"] == DEFAULT_FEE_CENTS
    assert settled["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert settled["lifetime_activated_count"] == 2
    assert settled["active_certification_count"] == 0
    assert_dealer_ledger_conservation(settled)


def test_every_other_withdrawal_reason_leaves_the_dealer_paying(api, program):
    """A disposition and a branding both end the badge without refunding it.

    PRD §3.2: "as hop 2, any certification of that vehicle in `ACTIVE` or
    `UNDER_AUDIT` moves to `DECERTIFIED` with a decertification reason of
    `RETAIL_SOLD` and its `fee_credited_cents` left at 0, because the programme
    keeps the fee on a retail sale."
    PRD §3.2: "A `TITLE_BRANDED` event sets `title_brand` to the supplied brand
    and decertifies any live certification of the vehicle with a decertification
    reason of `TITLE_BRANDED`."
    PRD §3.2: "`fee_billed_cents_total` sums the fee charged over every
    certification of the dealer that has been activated at least once"

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_on_post_audit_credit
    """
    walks = activate_many(api, program, 2)

    record_history_event(api, walks[0].vehicle_id, "RETAIL_SOLD")
    sold = read_certification(api, walks[0].certification_id)
    assert sold["decertification_reason"] == "RETAIL_SOLD"
    assert sold["fee_credited_cents"] == 0

    record_history_event(
        api, walks[1].vehicle_id, "TITLE_BRANDED", title_brand="ODOMETER_DISCREPANCY"
    )
    branded = read_certification(api, walks[1].certification_id)
    assert branded["decertification_reason"] == "TITLE_BRANDED"
    assert branded["fee_credited_cents"] == 0

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == 2 * DEFAULT_FEE_CENTS
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["active_certification_count"] == 0
    assert_dealer_ledger_conservation(dealer)


# ─────────────────── the conserved slot on the vehicle ──────────────────

def test_superseding_hands_the_slot_over_without_dipping_or_doubling(api, program):
    """The scarce slot passes from one row to the next inside a single request.

    PRD §3.6: "The earlier row moves `SUBMITTED → SUPERSEDED` and its `version`
    increments by 1, and the certification slot it occupied is handed to the new
    row within the same request, so the vehicle's `active_certification_count`
    remains 1 throughout rather than dipping to 0 or rising to 2."
    PRD §3.6: "`SUPERSEDED` is terminal, no fee was ever billed on that row, and
    its `activated_at` stays null."
    PRD §3.2: "`active_certification_count` counts the vehicle's certifications
    currently `SUBMITTED`, `ACTIVE`, or `UNDER_AUDIT`; it is the conserved *slot*
    quantity of the programme, and the invariant is that it never exceeds 1."

    Design: Difficulty/compensating_invariant/vehicle_certification_slot_conservation_on_supersede
    """
    walk = passed_inspection(api, program)
    observed = vehicle_version(api, walk.vehicle_id)
    first = submit_certification(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        walk.inspection_id,
        expected_vehicle_version=observed,
        documents=documents_without_reconditioning("1"),
    )
    holding = read_vehicle(api, walk.vehicle_id)
    assert holding["active_certification_count"] == 1
    assert_vehicle_slot_invariant(holding)

    blind = api.create_certification(
        create_certification_payload(
            walk.vehicle_id,
            walk.inspection_id,
            observed,
            documents=documents_without_reconditioning("2"),
        ),
        program.dealer_headers,
    )
    validate_error(blind, ApiErrorId.ERR_STALE_VEHICLE_VERSION)
    assert read_certification(api, first["id"])["status"] == "SUBMITTED"
    assert read_vehicle(api, walk.vehicle_id)["active_certification_count"] == 1

    second = submit_certification(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        walk.inspection_id,
        expected_vehicle_version=vehicle_version(api, walk.vehicle_id),
        documents=documents_without_reconditioning("2"),
    )
    superseded = read_certification(api, first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["activated_at"] is None
    assert superseded["fee_charged_cents"] == 0
    assert second["status"] == "SUBMITTED"
    handed_over = read_vehicle(api, walk.vehicle_id)
    assert handed_over["active_certification_count"] == 1
    assert_vehicle_slot_invariant(handed_over)

    franchise_code = program.dealer["franchise_code"]
    assert_certification_number(first["certification_number"], franchise_code, 1)
    assert_certification_number(second["certification_number"], franchise_code, 2)

    approved = approve_certification(api, second["id"])
    assert approved["status"] == "ACTIVE"
    certified = read_vehicle(api, walk.vehicle_id)
    assert certified["cpo_state"] == "CERTIFIED"
    assert certified["certified_certification_id"] == second["id"]
    assert certified["active_certification_count"] == 1
    assert_vehicle_slot_invariant(certified)

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 2
    assert dealer["lifetime_activated_count"] == 1
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS


def test_a_chain_of_supersessions_holds_the_slot_and_a_rejection_releases_it(
    api, program
):
    """Three submissions, one slot, and no fee until something is activated.

    PRD §3.6: "so the vehicle's `active_certification_count` remains 1
    throughout rather than dipping to 0 or rising to 2."
    PRD §3.7: "The vehicle's `active_certification_count` is recomputed and
    falls to 0, its `certified_certification_id` stays null, and its `cpo_state`
    moves `CERTIFICATION_PENDING → NOT_CERTIFIED`."
    PRD §3.7: "No fee is billed, `activated_at` stays null, and no coverage is
    computed."

    Design: Difficulty/compensating_invariant/vehicle_certification_slot_conservation_on_supersede
    """
    walk = passed_inspection(api, program)
    submissions = []
    for suffix in ("1", "2", "3"):
        submissions.append(
            submit_certification(
                api,
                program.dealer_headers,
                walk.vehicle_id,
                walk.inspection_id,
                expected_vehicle_version=vehicle_version(api, walk.vehicle_id),
                documents=documents_without_reconditioning(suffix),
            )
        )
        vehicle = read_vehicle(api, walk.vehicle_id)
        assert vehicle["active_certification_count"] == 1
        assert_vehicle_slot_invariant(vehicle)

    for retired in submissions[:2]:
        assert read_certification(api, retired["id"])["status"] == "SUPERSEDED"
    assert read_certification(api, submissions[2]["id"])["status"] == "SUBMITTED"

    franchise_code = program.dealer["franchise_code"]
    for sequence, submission in enumerate(submissions, start=1):
        assert_certification_number(
            submission["certification_number"], franchise_code, sequence
        )

    rejected = reject_certification(api, submissions[2]["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "ADMIN_DECISION"
    assert rejected["activated_at"] is None
    assert rejected["fee_charged_cents"] == 0
    assert rejected["warranty_start_date"] is None

    released = read_vehicle(api, walk.vehicle_id)
    assert released["active_certification_count"] == 0
    assert released["certified_certification_id"] is None
    assert released["cpo_state"] == "NOT_CERTIFIED"
    assert_vehicle_slot_invariant(released)

    # A rejection does not resurrect the rows the chain had already retired.
    for retired in submissions[:2]:
        assert read_certification(api, retired["id"])["status"] == "SUPERSEDED"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 3
    assert dealer["lifetime_activated_count"] == 0
    assert dealer["active_certification_count"] == 0
    assert dealer["fee_billed_cents_total"] == 0
    assert_dealer_ledger_conservation(dealer)
