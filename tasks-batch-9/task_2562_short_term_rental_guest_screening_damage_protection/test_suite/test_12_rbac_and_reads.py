"""Who may read what: a shared read, and ownership enforced inside an admitted role."""

from test_helpers import (
    ApiErrorId,
    assertions,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import ADJUDICATOR, make_host_headers


SHARED_RESERVATION_FIELDS = (
    "id",
    "stay_state",
    "screening_state",
    "screening_reason_code",
    "risk_tier_at_booking",
    "nights",
    "accommodation_cents",
    "waiver_fee_cents",
    "pre_fee_subtotal_cents",
    "trust_fee_pct",
    "trust_fee_cents",
    "total_charged_cents",
    "deposit_hold_cents",
    "version",
)


def test_both_parties_to_a_booking_read_the_same_reservation(api):
    """The guest who booked and the host who owns it see identical figures.

    The read is shared rather than owned by one side: each party is admitted through
    its own ownership tie and both get the same pinned charge and screening snapshot,
    down to the 103781-cent total. The adjudicator is admitted on role alone, with no
    ownership tie to the booking at all.

    PRD: "| GET | `/rentals/reservations/{id}` | Reads one reservation across all three state dimensions plus its pinned charge and risk snapshot. | Guest, Host, TrustAdjudicator, ComplianceOfficer, PlatformAdmin |"
    PRD: "An acting `Guest` matches the resource's guest, and an acting `Host` owns the listing or the claim — `ERR_NOT_RESOURCE_OWNER`."
    PRD: "The same listing booked at tier `ELEVATED` gives a waiver fee of 3000 multiplied by 3 and by 1.25, rounded to 11250, a `pre_fee_subtotal_cents` of 101250, a `trust_fee_pct` of 0.025, a `trust_fee_cents` of 2531, and a `total_charged_cents` of 103781."

    Design: Corner/rbac/guest_and_host_both_read_reservation
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Shared Read Guest", guest_email="sharedread@guest.test"
    )
    reservation = fixtures.book_stay(api, cast)

    guest_view = validate_success(
        api.get_reservation(reservation["id"], cast.guest_headers)
    )
    host_view = validate_success(
        api.get_reservation(reservation["id"], cast.host_headers)
    )
    for field in SHARED_RESERVATION_FIELDS:
        assert guest_view[field] == host_view[field], (
            "the two parties must read the same {0}: guest saw {1}, host saw {2}".format(
                field, guest_view[field], host_view[field]
            )
        )
    for view, label in ((guest_view, "guest read"), (host_view, "host read")):
        assertions.assert_fields(
            view,
            label,
            stay_state="REQUESTED",
            screening_state="CLEARED",
            risk_tier_at_booking="ELEVATED",
            total_charged_cents=103781,
        )

    adjudicator_view = validate_success(
        api.get_reservation(reservation["id"], ADJUDICATOR)
    )
    assertions.assert_fields(
        adjudicator_view,
        "adjudicator read",
        stay_state="REQUESTED",
        screening_state="CLEARED",
        total_charged_cents=103781,
    )


def test_a_rival_host_is_refused_a_listing_a_guest_may_read(api):
    """Host B is an admitted role on this endpoint and still gets 403.

    Role membership is not the whole of authorisation: the second host clears the
    role check and fails the ownership comparison, which is why the answer is
    ERR_NOT_RESOURCE_OWNER rather than ERR_UNAUTHORIZED. A guest, who carries no
    ownership tie to any listing, reads the very same row successfully.

    PRD: "Where an endpoint authorises `Guest` or `Host` and the acting principal is not the owner of the addressed resource, the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD: "Role membership is checked before ownership: an unrecognised or unauthorised role never reaches the ownership comparison."
    PRD: "| GET | `/rentals/properties/{id}` | Reads one listing with its listing state, sensor-compliance state, coverage posture and open counters. | Guest, Host, TrustAdjudicator, ComplianceOfficer, PlatformAdmin |"

    Design: Corner/rbac/host_cannot_read_another_hosts_property
    """
    cast = fixtures.setup_waiver_listing(
        api,
        host_name="Host A Stays LLC",
        host_email="rbachost-a@stays.test",
        guest_name="Browsing Guest",
        guest_email="browsing@guest.test",
    )
    rival = fixtures.create_host(
        api, legal_name="Host B Stays LLC", email="rbachost-b@stays.test"
    )

    refusal = validate_error(
        api.get_property(cast.property_id, make_host_headers(rival["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )
    assert refusal["error_id"] != "ERR_UNAUTHORIZED", (
        "Host is an admitted role on this endpoint, so the failure is ownership"
    )

    guest_view = validate_success(
        api.get_property(cast.property_id, cast.guest_headers)
    )
    assertions.assert_fields(
        guest_view,
        "guest read",
        id=cast.property_id,
        host_id=cast.host_id,
        listing_state="ACTIVE",
    )
    owner_view = validate_success(
        api.get_property(cast.property_id, cast.host_headers)
    )
    assertions.assert_fields(owner_view, "owner read", listing_state="ACTIVE")
