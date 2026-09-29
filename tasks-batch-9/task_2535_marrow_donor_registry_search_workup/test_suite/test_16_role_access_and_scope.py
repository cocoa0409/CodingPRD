"""Operator identity, role eligibility and peer scope.

Three concerns live here, all of them decided before any state or safety rule
runs: header presence and role recognition, role-versus-endpoint eligibility on
the operations one role owns exclusively, and the two entity-backed scopes plus
patient ownership that isolate one peer's resources from another's.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    constants as C,
    factories as f,
    fixtures,
    make_center_ops_headers,
    make_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# One exclusive operation per role, each called by a role that is not listed
# for the endpoint.  Four of them deliberately name an identifier that does not
# exist, so a 404 would prove the eligibility rung runs too late.
# ---------------------------------------------------------------------------

WRONG_ROLE_DENIALS = [
    ("MedicalDirector", "md-1", "create_patient"),
    ("TransplantCoordinator", "tc-1", "create_registry"),
    ("CollectionCenterOps", "cc-unknown", "create_donor"),
    ("RegistryOperations", "ops-1", "record_clearance_result"),
    ("RegistryOperations", "ops-1", "decide_collection_method"),
    ("MedicalDirector", "md-1", "record_screening"),
    ("MedicalDirector", "md-1", "create_collection_booking"),
    ("TransplantCoordinator", "tc-1", "run_deadline_sweep"),
    ("CollectionCenterOps", "cc-unknown", "set_clock"),
]

WRONG_ROLE_IDS = [
    "patient_registration_refuses_medical_director",
    "registry_registration_refuses_coordinator",
    "donor_registration_refuses_center_ops",
    "clearance_result_refuses_operations",
    "collection_method_refuses_operations",
    "screening_refuses_medical_director",
    "booking_create_refuses_medical_director",
    "deadline_sweep_refuses_coordinator",
    "clock_set_refuses_center_ops",
]


def _call_exclusive_operation(api, action, headers, registry_id):
    """Issue one write that belongs exclusively to a role other than `headers`."""
    if action == "create_patient":
        return api.create_patient(f.create_patient_payload(), headers)
    if action == "create_registry":
        return api.create_registry(f.create_international_registry_payload(), headers)
    if action == "create_donor":
        return api.create_donor(f.create_donor_payload(registry_id), headers)
    if action == "record_clearance_result":
        return api.record_clearance_result(
            NON_EXISTENT_UUID, f.clearance_result_payload(), headers
        )
    if action == "decide_collection_method":
        return api.decide_collection_method(
            NON_EXISTENT_UUID, f.collection_method_payload(), headers
        )
    if action == "record_screening":
        return api.record_screening(NON_EXISTENT_UUID, f.screening_payload(), headers)
    if action == "create_collection_booking":
        return api.create_collection_booking(
            f.create_booking_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, "2026-08-11T08:00:00Z", 1
            ),
            headers,
        )
    if action == "run_deadline_sweep":
        return api.run_deadline_sweep(NON_EXISTENT_UUID, headers)
    if action == "set_clock":
        return api.set_clock("2026-08-20T00:00:00Z", headers)
    raise AssertionError(f"unknown exclusive operation {action!r}")


@pytest.mark.parametrize("role, user_id, action", WRONG_ROLE_DENIALS, ids=WRONG_ROLE_IDS)
def test_exclusive_operations_refuse_every_other_role(api, role, user_id, action):
    """PRD §2.1: "If the headers are well-formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `TransplantCoordinator` owns a patient case end to end: it registers the patient, opens the registry search, raises confirmatory-typing requests, opens the donor workup, and shares the conditioning timeline with the `MedicalDirector`."
    PRD §2.1: "A `DonorRegistryLiaison` speaks for exactly one donor registry: it registers that registry's donors, answers confirmatory-typing requests, records health screening outcomes, maintains donor calendars, and files follow-ups."
    PRD §2.1: "A `CollectionCenterOps` operator acts for exactly one collection centre: it creates, confirms and cancels bookings, records the collected product, and files courier events shared with `RegistryOperations`."
    PRD §2.1: "A `RegistryOperations` operator is purely operational — it maintains registries and collection centres, runs the deadline sweep, finalises reimbursement claims and drives the logical clock — and is barred from every clinical write: it may not record a clearance result, decide a collection method, drive a conditioning action, or record a screening outcome."
    PRD §2.9: "The first two rungs are authentication and authorisation: header presence and role recognition (`ERR_UNAUTHENTICATED`), then role-versus-endpoint eligibility (`ERR_UNAUTHORIZED`)."
    PRD §2.9: "The fifth rung resolves path identifiers left to right, and the sixth resolves body foreign keys in declaration order, both as described in §2.8."

    Design: Corner/rbac/exclusive_operations_refuse_every_other_role_and_unknown_headers
    """
    registry = fixtures.create_registry()

    response = _call_exclusive_operation(
        api, action, build_user_headers(user_id, role), registry["id"]
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    # The refusal is inert, and it never leaks the existence of the ids it named.
    donors, meta = validate_paginated(
        api.list_donors(TEST_USERS["operations_headers"], params={"limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"an unauthorised {role} write must create nothing, found {meta['total_count']} donors"
    )
    assert donors == []


# ---------------------------------------------------------------------------
# Header variants that never reach the eligibility rung at all.
# ---------------------------------------------------------------------------

BAD_HEADER_VARIANTS = [
    (
        "unknown_role_name",
        {"X-User-ID": "tc-1", "X-User-Role": "RegistryAdministrator", "Content-Type": "application/json"},
    ),
    (
        "role_name_wrong_case",
        {"X-User-ID": "tc-1", "X-User-Role": "transplantcoordinator", "Content-Type": "application/json"},
    ),
    (
        "missing_user_id_header",
        {"X-User-Role": "TransplantCoordinator", "Content-Type": "application/json"},
    ),
    (
        "missing_user_role_header",
        {"X-User-ID": "tc-1", "Content-Type": "application/json"},
    ),
]


@pytest.mark.parametrize(
    "variant, headers",
    BAD_HEADER_VARIANTS,
    ids=[variant for variant, _ in BAD_HEADER_VARIANTS],
)
@pytest.mark.parametrize("endpoint", ["write", "read"])
def test_unrecognised_or_missing_operator_headers_are_unauthenticated(
    api, variant, headers, endpoint
):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts."
    PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the five role names the system recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The five roles, spelled exactly as they must appear in the header, are `TransplantCoordinator`, `DonorRegistryLiaison`, `MedicalDirector`, `CollectionCenterOps` and `RegistryOperations`."
    PRD §2.9: "The first two rungs are authentication and authorisation: header presence and role recognition (`ERR_UNAUTHENTICATED`), then role-versus-endpoint eligibility (`ERR_UNAUTHORIZED`)."

    Design: Corner/rbac/exclusive_operations_refuse_every_other_role_and_unknown_headers
    """
    if endpoint == "write":
        response = api.create_patient(f.create_patient_payload(), headers)
    else:
        response = api.list_donors(headers)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    # The very same call, with the headers spelled as §2.1 requires, is accepted:
    # only header presence and role recognition were ever at issue.
    if endpoint == "write":
        accepted = api.create_patient(
            f.create_patient_payload(), TEST_USERS["coordinator_headers"]
        )
        validate_success(accepted, expected_status=201)
    else:
        accepted = api.list_donors(TEST_USERS["operations_headers"])
        rows, meta = validate_paginated(accepted)
        assert rows == [] and meta["total_count"] == 0, (
            f"the rejected {variant} read must have left an empty donor store"
        )


# ---------------------------------------------------------------------------
# Shared operations: the endpoint's role list, not one owning role, admits.
# ---------------------------------------------------------------------------

def _shared_booking_cancellation(api):
    """Cancel is shared between the centre that created the slot and a physician."""
    ctx = fixtures.setup_pipeline("booking_held", method="PBSC")
    booking = ctx["booking"]
    assert booking["status"] == "HELD", (
        f"Setup failed: booking must open HELD, got {booking['status']!r}"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "Setup failed: a held PBSC slot must commit its 300 minutes"
    )

    # The physician cancels a slot the collection centre created.
    reason = "Center apheresis suite closed for maintenance."
    cancelled = validate_success(
        api.cancel_collection_booking(
            booking["id"], f.cancel_booking_payload(reason=reason), TEST_USERS["physician_headers"]
        )
    )
    assert cancelled["status"] == "CANCELLED", (
        f"a MedicalDirector cancellation must move HELD -> CANCELLED, got {cancelled['status']!r}"
    )
    assert cancelled["cancel_reason"] == reason, (
        f"cancel_reason must record the supplied reason, got {cancelled['cancel_reason']!r}"
    )
    assert cancelled["cancelled_after_confirmation"] is False, (
        "cancelling from HELD leaves cancelled_after_confirmation false"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 0, (
        "cancellation releases the booking's duration_minutes from the centre"
    )
    assert fixtures.read_workup_case(ctx["workup_case_id"])["logistics_status"] == "METHOD_SET", (
        "with no live booking left the case reverts BOOKED -> METHOD_SET"
    )

    # The other permitted role cancels the next slot on the very same case.
    second = fixtures.advance_to_booking_held(ctx)
    assert second["status"] == "HELD"
    centre_cancelled = validate_success(
        api.cancel_collection_booking(
            second["id"],
            f.cancel_booking_payload(reason="Centre releasing the slot itself."),
            ctx["center_ops_headers"],
        )
    )
    assert centre_cancelled["status"] == "CANCELLED", (
        "the collection centre is equally admitted to the shared cancel capability"
    )
    assert centre_cancelled["cancelled_after_confirmation"] is False


def _shared_courier_custody(api):
    """One shipment, one event from the centre and the next from operations."""
    ctx = fixtures.setup_pipeline("collected", method="PBSC")
    shipment = ctx["shipment"]
    assert shipment["status"] == "SCHEDULED" and shipment["transit_event_count"] == 0, (
        f"Setup failed: a fresh shipment opens SCHEDULED with no events, got "
        f"{shipment['status']!r}/{shipment['transit_event_count']}"
    )

    departed = validate_success(
        api.create_shipment_event(
            shipment["id"], f.shipment_event_payload("DEPARTED"), ctx["center_ops_headers"]
        )
    )
    assert departed["status"] == "IN_TRANSIT", (
        f"DEPARTED moves the shipment SCHEDULED -> IN_TRANSIT, got {departed['status']!r}"
    )
    assert departed["transit_event_count"] == 1, (
        f"every accepted event raises transit_event_count by one, got {departed['transit_event_count']}"
    )

    fixtures.set_clock(C.TIMELINE["DELIVERY_AT"])
    delivered = validate_success(
        api.create_shipment_event(
            shipment["id"],
            f.shipment_event_payload("DELIVERED", note="Delivery confirmed centrally."),
            TEST_USERS["operations_headers"],
        )
    )
    assert delivered["status"] == "DELIVERED", (
        f"a DELIVERED event filed at or before must_infuse_by moves IN_TRANSIT -> DELIVERED, "
        f"got {delivered['status']!r}"
    )
    assert delivered["transit_event_count"] == 2, (
        f"the second accepted event brings transit_event_count to 2, got "
        f"{delivered['transit_event_count']}"
    )
    assert fixtures.read_workup_case(ctx["workup_case_id"])["logistics_status"] == "DELIVERED"


def _shared_donor_follow_up(api):
    """One donor, one row from the liaison and one from the physician."""
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)

    contact = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload("DAY_7_CONTACT", 0, description="Day-7 contact by the liaison."),
            ctx["liaison_headers"],
        ),
        expected_status=201,
    )
    assert contact["event_type"] == "DAY_7_CONTACT" and contact["severity_grade"] == 0
    assert contact["triggered_permanent_deferral"] is False, (
        "a scheduled contact row never triggers a permanent deferral"
    )

    event = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload("ADVERSE_EVENT", 2, description="Physician-reviewed grade 2 event."),
            TEST_USERS["physician_headers"],
        ),
        expected_status=201,
    )
    assert event["event_type"] == "ADVERSE_EVENT" and event["severity_grade"] == 2
    assert event["triggered_permanent_deferral"] is False, (
        "grade 2 is below the grade-4 threshold, so triggered_permanent_deferral stays false"
    )

    rows, meta = validate_paginated(
        api.list_follow_ups(donor["id"], ctx["liaison_headers"], params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, (
        f"both roles' rows must persist against the same donor, got {meta['total_count']}"
    )
    assert [row["event_type"] for row in rows] == ["DAY_7_CONTACT", "ADVERSE_EVENT"], (
        f"the default list ordering is created_at ascending, got {[r['event_type'] for r in rows]}"
    )
    refreshed = fixtures.read_donor(donor["id"])
    assert refreshed["adverse_event_count"] == 1, (
        f"only the ADVERSE_EVENT row raises adverse_event_count, got {refreshed['adverse_event_count']}"
    )
    assert refreshed["availability_status"] == "AVAILABLE"


SHARED_OPERATIONS = {
    "booking_cancellation": _shared_booking_cancellation,
    "courier_custody": _shared_courier_custody,
    "donor_follow_up": _shared_donor_follow_up,
}


@pytest.mark.parametrize("operation", sorted(SHARED_OPERATIONS))
def test_shared_operations_accept_either_declared_role(api, operation):
    """PRD §3.7: "Cancelling a booking is shared between the collection centre and a `MedicalDirector`, and it requires a `reason`."
    PRD §3.7: "Cancellation records the supplied reason in `cancel_reason`, releases the booking's `duration_minutes` from the centre's `committed_slot_minutes`, and moves any `COLLECTION_WINDOW` window that this booking sourced to `RELEASED`, restoring the donor's `blocked_day_count` to exactly its pre-confirmation value."
    PRD §3.7: "Whether the booking had been confirmed matters for the money: cancelling from `HELD → CANCELLED` leaves `cancelled_after_confirmation` false and costs the programme nothing, whereas cancelling from `CONFIRMED → CANCELLED` sets `cancelled_after_confirmation` true, which adds a cancellation line to the case's final claim."
    PRD §3.7: "Finally, if the case is left with no booking in `HELD` or `CONFIRMED` status, the case's logistics dimension reverts `BOOKED → METHOD_SET` while its clearance dimension is untouched — the case is bookable again without redoing any clinical work."
    PRD §3.7: "Transit events are filed by the collection centre or by `RegistryOperations`, each supplying an `event_type` of `DEPARTED`, `DELIVERED` or `LOST` and an optional `note`."
    PRD §3.7: "Every accepted event increments the shipment's `transit_event_count` by one."
    PRD §3.7: "A `DEPARTED` event stamps `departed_at` from the logical clock and moves the shipment `SCHEDULED → IN_TRANSIT`, carrying the case `COLLECTED → IN_TRANSIT`."
    PRD §3.7: "A `DELIVERED` event filed at or before `must_infuse_by` stamps `delivered_at` and moves the shipment `IN_TRANSIT → DELIVERED`, carrying the case `IN_TRANSIT → DELIVERED`, at which point the recipient may be infused."
    PRD §3.9: "A liaison or a `MedicalDirector` files each contact against the donor with an `event_type` of `DAY_7_CONTACT`, `DAY_30_CONTACT`, `ONE_YEAR_CONTACT` or `ADVERSE_EVENT`, a `severity_grade` from 0 to 5 on the standard toxicity scale, and an optional free-text `description` of up to four hundred characters."
    PRD §3.9: "An `ADVERSE_EVENT` row additionally raises the donor's `adverse_event_count` by one."
    PRD §2.3: "Unless a specific list endpoint documents a different ordering, list results are sorted by `created_at` ascending."

    Design: Corner/rbac/shared_operations_accept_either_declared_role_on_the_same_resource
    """
    SHARED_OPERATIONS[operation](api)


def test_peer_scoped_roles_cannot_touch_another_peers_resources(api):
    """PRD §2.1: "Instead, ownership is enforced by comparing the target patient's recorded `coordinating_user_id` to `X-User-ID`; only the coordinator who created a patient may drive that patient's search, typing, workup and conditioning writes, and any other coordinator is rejected with `ERR_PATIENT_NOT_OWNED` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `DonorRegistryLiaison`, `X-User-ID` is the `id` of the acting `Registry`; ownership checks on any resource that references a `Registry` compare the resource's foreign-key field to `X-User-ID`, so a donor write requires that the target `DonorProfile` carries a `registry_id` equal to `X-User-ID`, and a typing response or screening write requires that the candidate's donor carries a `registry_id` equal to `X-User-ID`."
    PRD §2.1: "A mismatch is rejected with `ERR_REGISTRY_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `CollectionCenterOps`, `X-User-ID` is the `id` of the acting `CollectionCenter`; a booking or shipment write requires that the booking's `collection_center_id` equals `X-User-ID`, and a mismatch is rejected with `ERR_CENTER_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.11: "Registry scope is enforced on the same principle of accountability, and it guards exactly six writes: registering a donor, blocking a donor's calendar, releasing a donor calendar window, filing a donor follow-up, answering a confirmatory-typing request, and recording a screening outcome."
    PRD §2.11: "In all six the rejection code is `ERR_REGISTRY_SCOPE_VIOLATION`."
    PRD §2.11: "Collection-centre scope likewise guards exactly five writes: creating a booking, confirming a booking, cancelling a booking, recording the collected product against a booking, and filing a courier event against that booking's shipment."
    PRD §2.11: "In all five the rejection code is `ERR_CENTER_SCOPE_VIOLATION`."
    PRD §2.9: "Rungs seven through ten are the scope and duty checks, in this order: patient ownership for a `TransplantCoordinator` (`ERR_PATIENT_NOT_OWNED`), registry scope for a `DonorRegistryLiaison` (`ERR_REGISTRY_SCOPE_VIOLATION`), collection-centre scope for a `CollectionCenterOps` operator (`ERR_CENTER_SCOPE_VIOLATION`), and finally the two-physician rule on the collection-method decision (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/peer_scoped_roles_cannot_touch_another_peers_resources
    """
    ctx = fixtures.setup_pipeline("booking_confirmed", method="PBSC")
    booking = ctx["booking"]
    assert booking["status"] == "CONFIRMED", (
        f"Setup failed: booking must be CONFIRMED, got {booking['status']!r}"
    )

    # A second registry and a second collection centre give one peer identity per
    # entity-backed role; tc-2 is the peer for the opaque coordinator identity.
    peer_registry = fixtures.create_international_registry()
    peer_liaison = make_liaison_headers(peer_registry["id"])
    peer_center = fixtures.create_collection_center()
    peer_center_ops = make_center_ops_headers(peer_center["id"])
    peer_coordinator = build_user_headers("tc-2", "TransplantCoordinator")

    patient_version = fixtures.read_patient(
        ctx["patient_id"], ctx["coordinator_headers"]
    )["version"]
    case_version = fixtures.read_workup_case(ctx["workup_case_id"])["version"]

    # --- rung 7: patient ownership, for the coordinator that does not own it ---
    validate_error(
        api.create_search_request(
            f.create_search_request_payload(ctx["patient_id"]), peer_coordinator
        ),
        ApiErrorId.ERR_PATIENT_NOT_OWNED.value,
    )
    validate_error(
        api.create_typing_request(
            ctx["candidate_id"], f.create_typing_request_payload(priority_flag=True),
            peer_coordinator,
        ),
        ApiErrorId.ERR_PATIENT_NOT_OWNED.value,
    )
    validate_error(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload(
                "ABORT", patient_version, reason="A coordinator who does not own this patient."
            ),
            peer_coordinator,
        ),
        ApiErrorId.ERR_PATIENT_NOT_OWNED.value,
    )

    # --- rung 8: registry scope, for the liaison of the other registry ---------
    validate_error(
        api.create_donor(f.create_donor_payload(ctx["registry_id"]), peer_liaison),
        ApiErrorId.ERR_REGISTRY_SCOPE_VIOLATION.value,
    )
    validate_error(
        api.respond_typing_request(
            ctx["typing_request_id"],
            f.typing_response_payload(donor_available_flag=False),
            peer_liaison,
        ),
        ApiErrorId.ERR_REGISTRY_SCOPE_VIOLATION.value,
    )
    validate_error(
        api.record_screening(
            ctx["candidate_id"],
            f.screening_payload(outcome="FAIL", deferral_type="PERMANENT"),
            peer_liaison,
        ),
        ApiErrorId.ERR_REGISTRY_SCOPE_VIOLATION.value,
    )
    validate_error(
        api.create_follow_up(
            ctx["donor_id"],
            f.create_follow_up_payload("ADVERSE_EVENT", 4, description="Foreign registry."),
            peer_liaison,
        ),
        ApiErrorId.ERR_REGISTRY_SCOPE_VIOLATION.value,
    )

    # --- rung 9: collection-centre scope, for the rival centre ----------------
    validate_error(
        api.confirm_collection_booking(booking["id"], peer_center_ops),
        ApiErrorId.ERR_CENTER_SCOPE_VIOLATION.value,
    )
    validate_error(
        api.cancel_collection_booking(
            booking["id"],
            f.cancel_booking_payload(reason="A rival centre releasing another centre's slot."),
            peer_center_ops,
        ),
        ApiErrorId.ERR_CENTER_SCOPE_VIOLATION.value,
    )
    validate_error(
        api.create_collection_booking(
            f.create_booking_payload(
                ctx["workup_case_id"], ctx["center_id"], "2026-10-12T08:00:00Z", case_version
            ),
            peer_center_ops,
        ),
        ApiErrorId.ERR_CENTER_SCOPE_VIOLATION.value,
    )

    # --- none of the ten refusals mutated anything ---------------------------
    still = fixtures.read_booking(booking["id"])
    assert still["status"] == "CONFIRMED", (
        f"a scope refusal must not move the booking, got {still['status']!r}"
    )
    assert still["collection_center_id"] == ctx["center_id"], (
        "the booking still belongs to the centre that created it"
    )
    assert still["cancel_reason"] is None
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["availability_status"] == "AVAILABLE", (
        "the refused grade-4 adverse event never landed, so the donor is not deferred"
    )
    assert donor["adverse_event_count"] == 0
    assert fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])["status"] == (
        "WORKUP_OPEN"
    ), "the refused screening write must not have moved the candidate"
    assert fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])["version"] == (
        patient_version
    ), "the refused abort must not have bumped the patient's version"

    # --- reads are not peer-scoped: the guards list writes only ---------------
    peer_read = validate_success(api.get_collection_booking(booking["id"], peer_center_ops))
    assert peer_read["collection_center_id"] == ctx["center_id"], (
        "the rival centre may read the booking and sees its true owner"
    )
    assert peer_read["status"] == "CONFIRMED"
    peer_donor_read = validate_success(api.get_donor(ctx["donor_id"], peer_liaison))
    assert peer_donor_read["availability_status"] == "AVAILABLE"
    owner_read = validate_success(
        api.get_collection_booking(booking["id"], ctx["center_ops_headers"])
    )
    assert owner_read["status"] == peer_read["status"], (
        "the owner's own read returns the identical status the peer saw"
    )
