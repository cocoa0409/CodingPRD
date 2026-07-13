"""Entity creation, system defaults, config immutability, and role-based access.

Translates queue B (Corner) instances from the `entities` and `rbac` sections.
"""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


# --------------------------------------------------------------------------- #
# entities
# --------------------------------------------------------------------------- #
def test_create_dock_defaults_is_reciprocal_false(api, admin):
    """PRD §3.2: "a slip `capacity` of at least one, and an `is_reciprocal` flag
    that defaults to false and marks a partner dock rather than a home-club dock."

    Design: Corner/entities/create_dock_returns_201_with_fields
    """
    resp = api.create_dock({"name": "Harbor One", "location_code": "H1", "capacity": 12}, admin)
    data = validate_success(resp, 201)
    th.assert_dock(data)
    assert data["is_reciprocal"] is False, "is_reciprocal must default to false"


def test_create_member_applies_system_defaults(api, admin):
    """PRD §3.1: "A newly enrolled member starts in `PENDING_ORIENTATION` status
    with `certification_level` of `NONE`, `orientation_completed` set to false,
    and `no_show_strikes` at zero."

    Design: Corner/entities/create_member_applies_system_defaults
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    resp = api.create_member(
        th.create_member_payload("SAIL", dock["id"]), admin
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_ORIENTATION"
    assert data["certification_level"] == "NONE"
    assert data["orientation_completed"] is False
    assert data["no_show_strikes"] == 0


def test_get_member_not_found_returns_404(api, admin):
    """PRD §2.8: "the first one that does not exist produces that entity's specific
    not-found error — `ERR_DOCK_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_BOAT_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, ... each HTTP 404 — before any deeper business rule is evaluated."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member("00000000-0000-4000-8000-000000000000", admin)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)


def test_create_reservation_missing_end_time_returns_validation(api, member_hdr):
    """PRD §2.8: "body well-formedness on write endpoints — required fields present,
    enum values in range, numeric ranges honoured (for example an end strictly after
    a start) — else `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_reservation_missing_required_field_returns_400
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    payload = {
        "member_id": m,
        "dock_id": ctx["dock_id"],
        "boat_type": "PONTOON",
        "start_time": "2026-05-05T10:00:00Z",
    }
    resp = api.create_reservation(payload, member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_reservation_end_before_start_returns_validation(api, member_hdr):
    """PRD §3.3: "the window must be half-open with `end_time` strictly after
    `start_time`, or the request fails body validation."

    Design: Corner/entities/create_reservation_end_before_start_returns_400
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    payload = th.create_reservation_payload(
        m, ctx["dock_id"], "PONTOON", "2026-05-05T12:00:00Z", "2026-05-05T10:00:00Z"
    )
    resp = api.create_reservation(payload, member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_membership_tier_is_config_without_version(api, admin):
    """PRD §2.4: "A `MembershipTier` is a configuration record keyed by its natural
    code, and it carries only an `id` and a `created_at`; it has no `updated_at` and
    no `version` field at all."

    Design: Corner/entities/membership_tier_is_immutable_config
    """
    th.make_tier("SAIL")
    resp = api.get_tier("SAIL", admin)
    data = validate_success(resp, 200)
    th.assert_membership_tier(data)
    assert "version" not in data, "MembershipTier must not carry a version field"
    assert "updated_at" not in data, "MembershipTier must not carry an updated_at field"


# --------------------------------------------------------------------------- #
# rbac
# --------------------------------------------------------------------------- #
def test_member_cannot_create_boat_unauthorized(api, member_hdr):
    """PRD §2.1: "When a recognized user invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_boat_unauthorized
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    member = th.make_member("SAIL", dock["id"])
    resp = api.create_boat(th.create_boat_payload(dock["id"], "PONTOON"), member_hdr(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_dockstaff_cannot_create_membership_tier_unauthorized(api, staff):
    """PRD §2.1: "When a recognized user invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/dockstaff_cannot_create_membership_tier_unauthorized
    """
    resp = api.create_tier(th.create_tier_payload("SAIL"), staff)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_member_cannot_pay_other_members_invoice_forbidden(api, admin, member_hdr):
    """PRD §2.1: "may only pay a dues invoice whose `member_id` equals their
    `X-User-ID`. A violation of this ownership rule is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_pay_other_members_invoice_forbidden
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    m1 = th.make_member("SAIL", dock["id"], "M1", "m1@x.com")["id"]
    m2 = th.make_member("SAIL", dock["id"], "M2", "m2@x.com")["id"]
    mv = th.get_member_version(m1)
    inv = th.issue_dues_invoice(m1, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv)
    resp = api.pay_dues_invoice(inv["id"], member_hdr(m2))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_create_dock_missing_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the capacity in which they act. If either
    header is missing or the role is not recognized, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/create_dock_unauthenticated_missing_headers
    """
    resp = api.create_dock({"name": "Home", "location_code": "HM", "capacity": 10}, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_clubadmin_can_perform_dockstaff_assess(api, admin):
    """PRD §2.1: "A `ClubAdmin` is a superset operator who can perform every
    `DockStaff` action, every `Member`-facing action, and the configuration and
    housekeeping operations besides."

    Design: Corner/rbac/clubadmin_can_perform_dockstaff_assess_override
    """
    ctx = th.setup_active_basic_member("SAIL")
    m, dock, b1 = ctx["member_id"], ctx["dock_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    dr = th.file_damage_report(r["id"], b1, "MODERATE", 20000)
    resp = api.assess_damage_report(dr["id"], admin)  # ClubAdmin performing a DockStaff action
    data = validate_success(resp, 200)
    assert data["status"] == "ASSESSED"
