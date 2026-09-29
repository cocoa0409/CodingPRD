"""Setup helpers.

Every test starts against an empty database, so all state is built through the
endpoints the PRD declares. Single-step helpers wrap one call; the ``setup_*``
composites stack them into the scenes the suite reuses.

All setup calls go through ``get_success_data`` so a broken precondition fails
loudly at the setup line instead of surfacing as a confusing assertion later.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import REQUIRED_DISCLOSURE_CODES
from .test_users import TEST_USERS, make_sales_representative_headers

MARKETING = TEST_USERS["marketing_manager_headers"]
GALLERY = TEST_USERS["gallery_manager_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
ADJUDICATOR = TEST_USERS["contract_admin_adjudicator_headers"]
DISBURSER = TEST_USERS["contract_admin_disburser_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]
UNDERWRITER = TEST_USERS["contract_admin_underwriter_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

DEFAULT_CHECK_IN_UTC = "2026-08-14T07:00:00Z"
DEFAULT_EXECUTION_UTC = "2026-08-14T09:00:00Z"


# ---------------------------------------------------------------------------
# Instant arithmetic used to drive the logical clock
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant with a trailing Z into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_instant(moment: datetime) -> str:
    """Render an aware datetime as an ISO 8601 instant with a trailing Z."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant_after(value: str, **delta) -> str:
    """An instant offset from another, e.g. ``instant_after(x, minutes=61)``."""
    return format_instant(parse_instant(value) + timedelta(**delta))


def midnight_after(value: str) -> str:
    """Midnight UTC on the day following ``value``.

    Used to place the logical clock strictly past a rescission deadline, which
    always lands at 23:59:59.999Z.
    """
    day = parse_instant(value) + timedelta(days=1)
    return day.strftime("%Y-%m-%dT00:00:00Z")


# ---------------------------------------------------------------------------
# Single-step helpers
# ---------------------------------------------------------------------------


def pin_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward to an explicit instant."""
    return get_success_data(
        api_client.set_clock(factories.set_clock_payload(to_iso8601), PLATFORM)
    )


def sweep_rescissions() -> dict:
    """Advance the rescission epoch, expiring every open agreement past due."""
    return get_success_data(api_client.run_rescission_sweep(PLATFORM))


def create_gallery(**overrides) -> dict:
    return get_success_data(
        api_client.create_sales_gallery(
            factories.create_sales_gallery_payload(**overrides), GALLERY
        )
    )


def set_gallery_status(gallery_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_gallery_status(
            gallery_id, factories.set_gallery_status_payload(status), GALLERY
        )
    )


def create_representative(gallery_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sales_representative(
            factories.create_sales_representative_payload(gallery_id, **overrides),
            GALLERY,
        )
    )


def create_representatives(gallery_id: str, count: int) -> list:
    """A rotation of ``count`` representatives at consecutive positions."""
    reps = []
    for index in range(1, count + 1):
        reps.append(
            create_representative(
                gallery_id,
                full_name=f"Representative {index}",
                license_number=f"FL-SL-41007{index}",
                rotation_position=index,
            )
        )
    return reps


def create_channel(**overrides) -> dict:
    return get_success_data(
        api_client.create_tour_channel(
            factories.create_tour_channel_payload(**overrides), MARKETING
        )
    )


def reinstate_channel(channel_id: str) -> dict:
    return get_success_data(api_client.reinstate_tour_channel(channel_id, MARKETING))


def create_prospect(**overrides) -> dict:
    return get_success_data(
        api_client.create_prospect(
            factories.create_prospect_payload(**overrides), MARKETING
        )
    )


def create_booking(channel_id: str, prospect_id: str, gallery_id: str, **overrides):
    return get_success_data(
        api_client.create_tour_booking(
            factories.create_tour_booking_payload(
                channel_id, prospect_id, gallery_id, **overrides
            ),
            MARKETING,
        )
    )


def check_in(booking_id: str, issue_incentive_gift: bool = False) -> dict:
    return get_success_data(
        api_client.check_in_tour_booking(
            booking_id, factories.check_in_payload(issue_incentive_gift), GALLERY
        )
    )


def cancel_booking(booking_id: str, reason: str = "prospect withdrew") -> dict:
    return get_success_data(
        api_client.cancel_tour_booking(
            booking_id, factories.cancel_booking_payload(reason), MARKETING
        )
    )


def mark_no_show(booking_id: str) -> dict:
    return get_success_data(api_client.mark_tour_booking_no_show(booking_id, MARKETING))


def open_presentation(booking_id: str, rep_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sales_presentation(
            factories.create_sales_presentation_payload(booking_id, **overrides),
            make_sales_representative_headers(rep_id),
        )
    )


def acknowledge_disclosure(
    presentation_id: str,
    rep_id: str,
    disclosure_code: str,
    acknowledged_by_prospect: bool = True,
    recording_timestamp_offset_seconds: int = 120,
) -> dict:
    return get_success_data(
        api_client.create_disclosure_acknowledgment(
            factories.create_disclosure_acknowledgment_payload(
                presentation_id,
                disclosure_code,
                acknowledged_by_prospect=acknowledged_by_prospect,
                recording_timestamp_offset_seconds=recording_timestamp_offset_seconds,
            ),
            make_sales_representative_headers(rep_id),
        )
    )


def acknowledge_required_disclosures(presentation_id: str, rep_id: str) -> list:
    """Append all three required acknowledgments, taking the record to COMPLETE."""
    rows = []
    for index, code in enumerate(REQUIRED_DISCLOSURE_CODES):
        rows.append(
            acknowledge_disclosure(
                presentation_id,
                rep_id,
                code,
                recording_timestamp_offset_seconds=120 * (index + 1),
            )
        )
    return rows


def file_claim_finding(
    presentation_id: str,
    severity: str,
    expected_presentation_version: int,
    claim_code: str = "RENTAL_INCOME_PROMISE",
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.create_prohibited_claim_finding(
            factories.create_prohibited_claim_finding_payload(
                presentation_id, severity, expected_presentation_version, claim_code
            ),
            headers or OFFICER_BRAVO,
        )
    )


def review_presentation(
    presentation_id: str, decision: str = "CLEAR", headers: dict = None
) -> dict:
    return get_success_data(
        api_client.review_sales_presentation(
            presentation_id, factories.review_payload(decision), headers or OFFICER
        )
    )


def complete_presentation(presentation_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.complete_sales_presentation(
            presentation_id, make_sales_representative_headers(rep_id)
        )
    )


def execute_agreement(presentation_id: str, rep_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_agreement(
            factories.create_purchase_agreement_payload(presentation_id, **overrides),
            make_sales_representative_headers(rep_id),
        )
    )


def submit_financing(
    agreement_id: str, rep_id: str, expected_agreement_version: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_financing_application(
            factories.create_financing_application_payload(
                agreement_id, expected_agreement_version, **overrides
            ),
            make_sales_representative_headers(rep_id),
        )
    )


def decide_financing(
    application_id: str, decision: str = "APPROVE", headers: dict = None
) -> dict:
    return get_success_data(
        api_client.decide_financing_application(
            application_id,
            factories.financing_decision_payload(decision),
            headers or UNDERWRITER,
        )
    )


def fund_agreement(
    agreement_id: str, collected_amount_cents: int, headers: dict = None
) -> dict:
    return get_success_data(
        api_client.fund_purchase_agreement(
            agreement_id,
            factories.fund_payload(collected_amount_cents),
            headers or FUNDER,
        )
    )


def find_closing_package(agreement_id: str) -> dict:
    """Closing packages are cascade-created, so the list is the only channel."""
    body = api_client.list_closing_packages(FUNDER, params={"agreement_id": agreement_id})
    rows = get_success_data(body)
    assert rows, f"no closing package was created for agreement {agreement_id}"
    return rows[0]


def record_closing_package(package_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_closing_package(
            package_id, factories.record_closing_package_payload(**overrides), FUNDER
        )
    )


def deliver_closing_package(package_id: str, delivery_method: str = "COURIER") -> dict:
    return get_success_data(
        api_client.deliver_closing_package(
            package_id,
            factories.deliver_closing_package_payload(delivery_method),
            FUNDER,
        )
    )


def intake_rescission(
    agreement_id: str,
    delivery_method: str = "HAND_DELIVERED",
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_rescission_request(
            factories.create_rescission_request_payload(
                agreement_id, delivery_method, **overrides
            ),
            headers or INTAKE,
        )
    )


def adjudicate_rescission(request_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.adjudicate_rescission_request(request_id, headers or ADJUDICATOR)
    )


def create_disbursement(
    rescission_request_id: str, method: str = "ACH", headers: dict = None
) -> dict:
    return get_success_data(
        api_client.create_refund_disbursement(
            factories.create_refund_disbursement_payload(rescission_request_id, method),
            headers or DISBURSER,
        )
    )


def settle_disbursement(disbursement_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.settle_refund_disbursement(
            disbursement_id, factories.settle_payload(), headers or DISBURSER
        )
    )


def assign_retraining(
    rep_id: str,
    expected_representative_version: int,
    trigger_reason: str = "DISCLOSURE_GAP",
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_retraining_assignment(
            factories.create_retraining_assignment_payload(
                rep_id, expected_representative_version, trigger_reason, **overrides
            ),
            headers or OFFICER,
        )
    )


def start_retraining(assignment_id: str) -> dict:
    return get_success_data(api_client.start_retraining_assignment(assignment_id, OFFICER))


def close_retraining(assignment_id: str, outcome: str, modules_completed: int) -> dict:
    return get_success_data(
        api_client.close_retraining_assignment(
            assignment_id,
            factories.close_retraining_payload(outcome, modules_completed),
            OFFICER,
        )
    )


def reassign_retraining(assignment_id: str) -> dict:
    return get_success_data(
        api_client.reassign_retraining_assignment(assignment_id, OFFICER)
    )


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------


def read_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_tour_booking(booking_id, MARKETING))


def read_gallery(gallery_id: str) -> dict:
    return get_success_data(api_client.get_sales_gallery(gallery_id, GALLERY))


def read_channel(channel_id: str) -> dict:
    return get_success_data(api_client.get_tour_channel(channel_id, MARKETING))


def read_representative(rep_id: str) -> dict:
    return get_success_data(api_client.get_sales_representative(rep_id, GALLERY))


def read_presentation(presentation_id: str) -> dict:
    return get_success_data(api_client.get_sales_presentation(presentation_id, OFFICER))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_purchase_agreement(agreement_id, FUNDER))


def read_prospect(prospect_id: str) -> dict:
    return get_success_data(api_client.get_prospect(prospect_id, MARKETING))


def read_financing_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_financing_application(application_id, UNDERWRITER)
    )


def read_rescission_request(request_id: str) -> dict:
    return get_success_data(api_client.get_rescission_request(request_id, INTAKE))


def read_disbursement(disbursement_id: str) -> dict:
    return get_success_data(api_client.get_refund_disbursement(disbursement_id, DISBURSER))


def read_closing_package(package_id: str) -> dict:
    return get_success_data(api_client.get_closing_package(package_id, FUNDER))


def read_retraining_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_retraining_assignment(assignment_id, OFFICER))


# ---------------------------------------------------------------------------
# Composite scenes
# ---------------------------------------------------------------------------


def setup_tour_scene(
    rep_count: int = 1,
    gallery_overrides: dict = None,
    channel_overrides: dict = None,
    prospect_overrides: dict = None,
    booking_overrides: dict = None,
) -> dict:
    """A gallery with its rotation, an active channel, a prospect and a booking.

    Returns a dict with ``gallery``, ``reps``, ``rep``, ``channel``, ``prospect``
    and ``booking``.
    """
    gallery = create_gallery(**(gallery_overrides or {}))
    reps = create_representatives(gallery["id"], rep_count)
    channel = create_channel(**(channel_overrides or {}))
    prospect = create_prospect(**(prospect_overrides or {}))
    booking = create_booking(
        channel["id"], prospect["id"], gallery["id"], **(booking_overrides or {})
    )
    return {
        "gallery": gallery,
        "reps": reps,
        "rep": reps[0] if reps else None,
        "channel": channel,
        "prospect": prospect,
        "booking": booking,
    }


def setup_checked_in_tour(
    issue_incentive_gift: bool = True,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    scene: dict = None,
    **scene_kwargs,
) -> dict:
    """A checked-in tour with a representative bound by rotation.

    Adds ``checked_in_booking`` and ``assigned_rep_id`` to the scene.
    """
    scene = scene or setup_tour_scene(**scene_kwargs)
    if check_in_at:
        pin_clock(check_in_at)
    booking = check_in(scene["booking"]["id"], issue_incentive_gift)
    scene["checked_in_booking"] = booking
    scene["assigned_rep_id"] = booking["assigned_rep_id"]
    return scene


def setup_open_presentation(
    issue_incentive_gift: bool = True,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    scene: dict = None,
    **scene_kwargs,
) -> dict:
    """A checked-in tour whose presentation record has been opened.

    Adds ``presentation``.
    """
    scene = setup_checked_in_tour(
        issue_incentive_gift=issue_incentive_gift,
        check_in_at=check_in_at,
        scene=scene,
        **scene_kwargs,
    )
    scene["presentation"] = open_presentation(
        scene["booking"]["id"], scene["assigned_rep_id"]
    )
    return scene


def setup_cleared_presentation(
    issue_incentive_gift: bool = True,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    review_headers: dict = None,
    scene: dict = None,
    **scene_kwargs,
) -> dict:
    """A fully disclosed presentation cleared by a compliance officer.

    Adds ``presentation`` in ``disclosure_status`` COMPLETE and ``review_status``
    CLEARED.
    """
    scene = setup_open_presentation(
        issue_incentive_gift=issue_incentive_gift,
        check_in_at=check_in_at,
        scene=scene,
        **scene_kwargs,
    )
    acknowledge_required_disclosures(
        scene["presentation"]["id"], scene["assigned_rep_id"]
    )
    scene["presentation"] = review_presentation(
        scene["presentation"]["id"], "CLEAR", review_headers
    )
    return scene


def setup_completed_tour(
    issue_incentive_gift: bool = True,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    scene: dict = None,
    **scene_kwargs,
) -> dict:
    """A cleared presentation completed, taking the booking to TOURED."""
    scene = setup_cleared_presentation(
        issue_incentive_gift=issue_incentive_gift,
        check_in_at=check_in_at,
        scene=scene,
        **scene_kwargs,
    )
    scene["presentation"] = complete_presentation(
        scene["presentation"]["id"], scene["assigned_rep_id"]
    )
    return scene


def setup_executed_agreement(
    execute_at: str = DEFAULT_EXECUTION_UTC,
    issue_incentive_gift: bool = True,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    scene: dict = None,
    agreement_overrides: dict = None,
    **scene_kwargs,
) -> dict:
    """An executed agreement sitting OPEN / AWAITING_FUNDING.

    Adds ``agreement``.
    """
    scene = setup_completed_tour(
        issue_incentive_gift=issue_incentive_gift,
        check_in_at=check_in_at,
        scene=scene,
        **scene_kwargs,
    )
    if execute_at:
        pin_clock(execute_at)
    scene["agreement"] = execute_agreement(
        scene["presentation"]["id"],
        scene["assigned_rep_id"],
        **(agreement_overrides or {}),
    )
    return scene


def setup_parallel_cleared_presentations(
    count: int = 2,
    issue_incentive_gift: bool = False,
    check_in_at: str = DEFAULT_CHECK_IN_UTC,
    gallery_overrides: dict = None,
    channel_overrides: dict = None,
    prospect_overrides: dict = None,
) -> dict:
    """``count`` cleared presentations, one per representative, in one window.

    Every tour shares the same prospect and the same interval, which the gallery
    absorbs while its capacity allows and which each representative absorbs
    because calendar exclusivity is a capacity-of-one test per representative.

    Returns ``gallery``, ``reps``, ``channel``, ``prospect``, ``bookings``,
    ``presentations`` and ``assigned_rep_ids``.
    """
    gallery = create_gallery(**(gallery_overrides or {}))
    reps = create_representatives(gallery["id"], count)
    channel = create_channel(**(channel_overrides or {}))
    prospect = create_prospect(**(prospect_overrides or {}))
    bookings = [
        create_booking(channel["id"], prospect["id"], gallery["id"])
        for _ in range(count)
    ]
    pin_clock(check_in_at)
    assigned_rep_ids = []
    presentations = []
    for index, booking in enumerate(bookings):
        checked_in = check_in(booking["id"], issue_incentive_gift)
        rep_id = checked_in["assigned_rep_id"]
        assigned_rep_ids.append(rep_id)
        presentation = open_presentation(
            booking["id"], rep_id, recorded_ack_reference=f"REC-000{index + 1}"
        )
        acknowledge_required_disclosures(presentation["id"], rep_id)
        presentations.append(review_presentation(presentation["id"], "CLEAR"))
    return {
        "gallery": gallery,
        "reps": reps,
        "channel": channel,
        "prospect": prospect,
        "bookings": bookings,
        "presentations": presentations,
        "assigned_rep_ids": assigned_rep_ids,
    }


def setup_approved_financing(
    scene: dict = None,
    financing_overrides: dict = None,
    **agreement_kwargs,
) -> dict:
    """An executed agreement with an APPROVED financing application.

    Adds ``financing_application``.
    """
    scene = scene or setup_executed_agreement(**agreement_kwargs)
    application = submit_financing(
        scene["agreement"]["id"],
        scene["assigned_rep_id"],
        scene["agreement"]["version"],
        **(financing_overrides or {}),
    )
    scene["financing_application"] = decide_financing(application["id"], "APPROVE")
    scene["agreement"] = read_agreement(scene["agreement"]["id"])
    return scene


def setup_expired_agreement(scene: dict = None, **kwargs) -> dict:
    """An agreement whose rescission window has been swept to EXPIRED."""
    scene = scene or setup_approved_financing(**kwargs)
    pin_clock(midnight_after(scene["agreement"]["rescission_deadline_utc"]))
    scene["sweep"] = sweep_rescissions()
    scene["agreement"] = read_agreement(scene["agreement"]["id"])
    return scene


def setup_funded_agreement(scene: dict = None, **kwargs) -> dict:
    """A funded agreement and the closing package the funding created.

    Adds ``closing_package``.
    """
    scene = scene or setup_expired_agreement(**kwargs)
    scene["agreement"] = fund_agreement(
        scene["agreement"]["id"], scene["agreement"]["financed_amount_cents"]
    )
    scene["closing_package"] = find_closing_package(scene["agreement"]["id"])
    return scene


def setup_delivered_agreement(scene: dict = None, **kwargs) -> dict:
    """A funded agreement recorded and delivered, so DOCS_DELIVERED."""
    scene = scene or setup_funded_agreement(**kwargs)
    record_closing_package(scene["closing_package"]["id"])
    scene["closing_package"] = deliver_closing_package(scene["closing_package"]["id"])
    scene["agreement"] = read_agreement(scene["agreement"]["id"])
    return scene


def setup_validated_rescission(
    scene: dict = None,
    delivery_method: str = "HAND_DELIVERED",
    intake_overrides: dict = None,
    **kwargs,
) -> dict:
    """A timely cancellation notice adjudicated as VALIDATED.

    Adds ``rescission_request``.
    """
    scene = scene or setup_executed_agreement(**kwargs)
    request = intake_rescission(
        scene["agreement"]["id"], delivery_method, **(intake_overrides or {})
    )
    scene["rescission_request"] = adjudicate_rescission(request["id"])
    scene["agreement"] = read_agreement(scene["agreement"]["id"])
    return scene


def setup_pending_refund(scene: dict = None, method: str = "ACH", **kwargs) -> dict:
    """A PENDING refund disbursement on a validated cancellation.

    Adds ``refund_disbursement``.
    """
    scene = scene or setup_validated_rescission(**kwargs)
    scene["refund_disbursement"] = create_disbursement(
        scene["rescission_request"]["id"], method
    )
    return scene


def setup_settled_refund(scene: dict = None, **kwargs) -> dict:
    """A settled refund, at which point escrow conservation is checkable."""
    scene = scene or setup_pending_refund(**kwargs)
    scene["refund_disbursement"] = settle_disbursement(
        scene["refund_disbursement"]["id"]
    )
    scene["rescission_request"] = read_rescission_request(
        scene["rescission_request"]["id"]
    )
    scene["agreement"] = read_agreement(scene["agreement"]["id"])
    return scene
