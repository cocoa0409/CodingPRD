"""Dispatch: assignment stamping, trade matching, entry rules, vendor gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_property,
    create_resident,
    create_technician,
    create_vendor,
    create_work_order,
    dispatch_in_house,
    dispatch_payload,
    get_work_order,
    setup_property_resident_technician,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestDispatchSuccess:
    def test_dispatch_sets_assignment_fields(self, api):
        """PRD §3.3: "On a successful dispatch the system writes the assignment onto the work order: `assignment_type`, `assigned_technician_id` or `assigned_vendor_id`, `scheduled_start_at`, `scheduled_end_at`, `entry_authorization`, and `notice_posted_at`."
        PRD §3.3: "The first dispatch of a work order also stamps `first_responded_at` with the current logical clock and immediately recomputes `response_sla_breached` as whether that stamp is strictly later than `response_due_at`."
        PRD §3.3: "Every successful dispatch increments the work order's `version` by one."
        PRD §2.4: "On server boot the logical clock starts at the fixed default `2026-08-01T00:00:00Z`; it does not read wall-clock time and must not fall back to it."

        Design: Corner/endpoints/dispatch_sets_assignment_fields
        """
        bundle = setup_property_resident_technician("Disp Property", unit_number="501")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Leak",
        )
        data = dispatch_in_house(wo["id"], bundle["technician"]["id"])
        assert data["status"] == "ASSIGNED"
        assert data["assignment_type"] == "IN_HOUSE"
        assert data["assigned_technician_id"] == bundle["technician"]["id"]
        # First dispatch stamps first_responded_at from the logical clock (boot default).
        assert_instant_equals(
            data["first_responded_at"], "2026-08-01T00:00:00Z", "first_responded_at"
        )
        # Responded at creation instant, well before the 72h ROUTINE response due.
        assert data["response_sla_breached"] is False
        assert data["version"] == 2


class TestDispatchEligibility:
    def test_dispatch_trade_mismatch_rejected(self, api):
        """PRD §2.11: "Within a property, assignment additionally requires a trade match: the technician's or vendor's `trade` must equal the work order's `category`, or dispatch is rejected with `ERR_TRADE_MISMATCH` (HTTP 409)."

        Design: Corner/validations/dispatch_trade_mismatch_rejected
        """
        prop = create_property("Trade Property")
        resident = create_resident(prop["id"], unit_number="401", full_name="R Trade",
                                   email="rtrade@x.com")
        electrician = create_technician(prop["id"], full_name="T Elec", trade="ELECTRICAL")
        wo = create_work_order(prop["id"], resident["id"], category="PLUMBING",
                               priority="ROUTINE", description="Leak")
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="IN_HOUSE",
                technician_id=electrician["id"],
                scheduled_start_at="2026-08-01T10:00:00Z",
                scheduled_end_at="2026-08-01T12:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_MISMATCH)
        assert get_work_order(wo["id"])["status"] == "TRIAGED"

    def test_emergency_access_on_routine_rejected(self, api):
        """PRD §3.3: "`EMERGENCY_ACCESS` is lawful only when the work order's `priority` is `EMERGENCY`; on any other priority the dispatch is rejected with `ERR_ENTRY_RULE_VIOLATION` (HTTP 422)."

        Design: Corner/validations/emergency_access_on_routine_rejected
        """
        bundle = setup_property_resident_technician("Entry Property", unit_number="402")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Routine fix",
        )
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="IN_HOUSE",
                technician_id=bundle["technician"]["id"],
                scheduled_start_at="2026-08-01T10:00:00Z",
                scheduled_end_at="2026-08-01T12:00:00Z",
                entry_authorization="EMERGENCY_ACCESS",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_RULE_VIOLATION)
        assert get_work_order(wo["id"])["status"] == "TRIAGED"

    def test_notice_too_short_at_dispatch_rejected(self, api):
        """PRD §3.3: "`NOTICE_POSTED` requires `notice_posted_at` to be present and the scheduled start to be at least the property's `entry_notice_min_hours` after the notice timestamp; a missing notice timestamp or a window that starts inside the lead time is rejected with `ERR_ENTRY_NOTICE_TOO_SHORT` (HTTP 422)."

        Design: Corner/validations/notice_too_short_at_dispatch_rejected
        """
        bundle = setup_property_resident_technician("Notice Property", unit_number="403")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Inspection",
        )
        # 23h lead (notice 2026-08-01T10:00Z, start 2026-08-02T09:00Z) < 24h minimum.
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="IN_HOUSE",
                technician_id=bundle["technician"]["id"],
                scheduled_start_at="2026-08-02T09:00:00Z",
                scheduled_end_at="2026-08-02T11:00:00Z",
                entry_authorization="NOTICE_POSTED",
                notice_posted_at="2026-08-01T10:00:00Z",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOTICE_TOO_SHORT)

    def test_vendor_insurance_expired_rejected(self, api):
        """PRD §3.3: "The vendor's insurance must cover the start of the job: `insurance_valid_until` must be at or after `scheduled_start_at`, or the dispatch fails with `ERR_VENDOR_INSURANCE_EXPIRED` (HTTP 409)."

        Design: Corner/validations/vendor_insurance_expired_rejected
        """
        prop = create_property("Ins Property")
        resident = create_resident(prop["id"], unit_number="404", full_name="R Ins",
                                   email="rins@x.com")
        vendor = create_vendor(prop["id"], company_name="Uninsured Co", trade="PLUMBING",
                               insurance_valid_until="2026-08-10T00:00:00Z")
        wo = create_work_order(prop["id"], resident["id"], category="PLUMBING",
                               priority="ROUTINE", description="Vendor job")
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="VENDOR",
                vendor_id=vendor["id"],
                scheduled_start_at="2026-08-11T10:00:00Z",
                scheduled_end_at="2026-08-11T12:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_INSURANCE_EXPIRED)
        assert get_work_order(wo["id"])["status"] == "TRIAGED"


class TestDispatchRequiresVendorActive:
    def _setup_suspended_vendor_scenario(self, api):
        prop = create_property("XDep Property")
        resident = create_resident(prop["id"], unit_number="113", full_name="R Thirteen",
                                   email="r13@x.com")
        vendor = create_vendor(prop["id"], company_name="V Co", trade="PLUMBING",
                               insurance_valid_until="2027-01-01T00:00:00Z")
        wo = create_work_order(prop["id"], resident["id"], category="PLUMBING",
                               priority="ROUTINE", description="Needs vendor")
        return prop, resident, vendor, wo

    def test_dispatch_to_suspended_vendor_rejected(self, api):
        """PRD §3.3: "The vendor's `status` must be `ACTIVE`; dispatching to a `SUSPENDED` vendor is rejected with `ERR_VENDOR_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_vendor_active
        """
        _, _, vendor, wo = self._setup_suspended_vendor_scenario(api)
        validate_success(
            api.vendor_event(vendor["id"], {"event_type": "SUSPEND"}, MANAGER), 200
        )
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="VENDOR",
                vendor_id=vendor["id"],
                scheduled_start_at="2026-08-01T10:00:00Z",
                scheduled_end_at="2026-08-01T12:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)
        assert get_work_order(wo["id"])["status"] == "TRIAGED"

    def test_dispatch_succeeds_after_vendor_reinstated(self, api):
        """PRD §3.3: "The vendor's `status` must be `ACTIVE`; dispatching to a `SUSPENDED` vendor is rejected with `ERR_VENDOR_NOT_ACTIVE` (HTTP 409)."
        PRD §3.8: "Reinstating requires the vendor to be `SUSPENDED` and returns it to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_vendor_active
        """
        _, _, vendor, wo = self._setup_suspended_vendor_scenario(api)
        validate_success(
            api.vendor_event(vendor["id"], {"event_type": "SUSPEND"}, MANAGER), 200
        )
        validate_success(
            api.vendor_event(vendor["id"], {"event_type": "REINSTATE"}, MANAGER), 200
        )
        data = validate_success(
            api.dispatch_work_order(
                wo["id"],
                dispatch_payload(
                    assignment_type="VENDOR",
                    vendor_id=vendor["id"],
                    scheduled_start_at="2026-08-01T10:00:00Z",
                    scheduled_end_at="2026-08-01T12:00:00Z",
                    entry_authorization="RESIDENT_CONSENT",
                ),
                DISPATCHER,
            ),
            200,
        )
        # An ACTIVE vendor passes the gate: the same dispatch now assigns.
        assert data["status"] == "ASSIGNED"
        assert data["assigned_vendor_id"] == vendor["id"]
