"""Request-payload factories for the Single-Family Rental Portfolio Operations API.

Every factory returns a fresh, fully valid payload dict and accepts keyword overrides,
so a test can express "the canonical Atlanta market but with a 210 bps millage" without
restating twenty-three policy fields.  Passing ``None`` as an override value *removes*
the key, which is how the optional-input-default tests are written.

All money is a whole number of cents and all rates are basis points (PRD SS2.5).
"""


def _apply(payload, overrides):
    """Merge overrides into ``payload``; a value of ``None`` deletes the key."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- logical clock --------------------------------------------------------------------
def clock_payload(current_utc):
    """Payload for ``POST /_clock/set_current_utc``."""
    return {"current_utc": current_utc}


# --- markets --------------------------------------------------------------------------
def market_payload(**overrides):
    """The canonical Atlanta market whose policy numbers drive the PRD worked examples."""
    return _apply(
        {
            "code": "ATL",
            "name": "Atlanta",
            "tax_jurisdiction_code": "GA-FULTON",
            "millage_bps": 125,
            "rent_index_cents": 210000,
            "cost_index_bps": 10250,
            "cost_variance_tolerance_bps": 1000,
            "make_ready_target_days": 30,
            "turn_holdback_cap_bps": 1500,
            "showing_buffer_minutes": 30,
            "min_showing_duration_minutes": 30,
            "pet_deposit_per_pet_cents": 30000,
            "pet_deposit_cap_cents": 50000,
            "max_pets": 2,
            "restricted_breeds": ["PIT_BULL", "ROTTWEILER"],
            "standard_lease_term_months": 12,
            "fraud_block_threshold_bps": 6000,
            "rent_to_income_max_bps": 4000,
            "vacancy_loss_bps": 500,
            "bad_debt_bps": 100,
            "mgmt_fee_bps": 800,
            "underwriting_yield_floor_bps": 500,
            "disposition_yield_floor_bps": 540,
            "max_rent_concession_bps": 500,
        },
        overrides,
    )


def dallas_market_payload(**overrides):
    """A second market used to prove that every policy read is market-scoped."""
    # Build the Dallas defaults first, then layer the caller's overrides on top, so that a
    # test may re-override a field this factory already pins (e.g. ``millage_bps``).
    return _apply(
        market_payload(
            code="DAL",
            name="Dallas",
            tax_jurisdiction_code="TX-DALLAS",
            millage_bps=210,
            rent_index_cents=195000,
            cost_index_bps=9900,
            cost_variance_tolerance_bps=1200,
            make_ready_target_days=35,
            pet_deposit_per_pet_cents=25000,
            pet_deposit_cap_cents=45000,
            restricted_breeds=["PIT_BULL"],
            vacancy_loss_bps=550,
        ),
        overrides,
    )


def dallas_market_payload_strict(**overrides):
    """The Dallas market with every policy dial set away from Atlanta's value."""
    return _apply(
        dallas_market_payload(
            millage_bps=200,
            rent_index_cents=190000,
            cost_variance_tolerance_bps=800,
            disposition_yield_floor_bps=560,
            fraud_block_threshold_bps=5500,
            make_ready_target_days=25,
            max_pets=1,
            max_rent_concession_bps=300,
            mgmt_fee_bps=750,
            pet_deposit_cap_cents=40000,
            rent_to_income_max_bps=3800,
            showing_buffer_minutes=45,
            turn_holdback_cap_bps=1200,
            underwriting_yield_floor_bps=520,
            vacancy_loss_bps=600,
        ),
        overrides,
    )


# --- scope templates ------------------------------------------------------------------
def scope_template_paint(**overrides):
    """Interior paint, priced per HOME, requiring the ``PAINT`` certification."""
    return _apply(
        {
            "code": "PAINT_INT",
            "name": "Interior Paint",
            "certification_code": "PAINT",
            "unit": "HOME",
            "benchmark_unit_cost_cents": 285050,
            "default_crew_size": 3,
            "default_crew_days": 3,
            "safety_critical": False,
        },
        overrides,
    )


def scope_template_hvac(**overrides):
    """HVAC replacement -- the safety-critical template that bars the in-house channel."""
    return _apply(
        {
            "code": "HVAC_REPLACE",
            "name": "HVAC System Replacement",
            "certification_code": "HVAC",
            "unit": "SYSTEM",
            "benchmark_unit_cost_cents": 612450,
            "default_crew_size": 3,
            "default_crew_days": 3,
            "safety_critical": True,
        },
        overrides,
    )


def scope_template_floor(**overrides):
    """Luxury vinyl plank flooring, priced per SQFT so quantity scales the benchmark."""
    return _apply(
        {
            "code": "FLOOR_LVP",
            "name": "Luxury Vinyl Plank Flooring",
            "certification_code": "FLOOR",
            "unit": "SQFT",
            "benchmark_unit_cost_cents": 475,
            "default_crew_size": 2,
            "default_crew_days": 2,
            "safety_critical": False,
        },
        overrides,
    )


def scope_template_general(**overrides):
    """A repaint template requiring the generic ``GEN`` certification.

    Used wherever a test needs one scope line whose certification a single vendor can
    satisfy without setting up the three-trade catalogue.
    """
    return _apply(
        scope_template_paint(name="Full interior repaint", certification_code="GEN"),
        overrides,
    )


# --- homes ----------------------------------------------------------------------------
def home_payload(market_id, **overrides):
    """The canonical Atlanta home used by every PRD worked example.

    ``assessed_value_cents`` 28000000 at a 125 bps millage is the PRD's own property tax
    illustration, and ``asking_rent_cents`` 215000 feeds the underwriting example.
    """
    return _apply(
        {
            "market_id": market_id,
            "address_line1": "118 Peachtree Way",
            "city": "Atlanta",
            "state_code": "GA",
            "postal_code": "30318",
            "bedrooms": 3,
            "bathrooms": 2,
            "square_feet": 1650,
            "year_built": 1998,
            "assessed_value_cents": 28000000,
            "asking_rent_cents": 215000,
            "insurance_carrier_name": "Southeast Mutual",
            "insurance_annual_premium_cents": 180000,
            "insurance_binder_expires_on": "2027-06-30",
            "hoa_name": "Peachtree HOA",
            "hoa_annual_cents": 60000,
        },
        overrides,
    )


def home_payload_no_hoa(market_id, **overrides):
    """A home registered without any HOA inputs, to exercise the declared defaults."""
    return _apply(
        home_payload(
            market_id,
            address_line1="220 Marietta Street",
            bedrooms=4,
            bathrooms=3,
            square_feet=2100,
            year_built=2004,
            assessed_value_cents=31000000,
            asking_rent_cents=240000,
            hoa_name=None,
            hoa_annual_cents=None,
        ),
        overrides,
    )


def home_payload_second(market_id, **overrides):
    """A second, smaller Atlanta home for listing and filter coverage."""
    return _apply(
        home_payload(
            market_id,
            address_line1="330 Ponce de Leon Avenue",
            bedrooms=2,
            bathrooms=1,
            square_feet=1200,
            year_built=1975,
            assessed_value_cents=19000000,
            asking_rent_cents=165000,
        ),
        overrides,
    )


def home_payload_dallas(market_id, **overrides):
    """A home in the second market, for the cross-market mismatch rules."""
    return _apply(
        home_payload(
            market_id,
            address_line1="77 Elm Street",
            city="Dallas",
            state_code="TX",
            postal_code="75201",
            insurance_carrier_name="Lone Star Casualty",
        ),
        overrides,
    )


# --- underwriting cases ---------------------------------------------------------------
def scope_line(scope_template_id, quantity):
    """One planned scope line inside an underwriting case."""
    return {"scope_template_id": scope_template_id, "quantity": quantity}


def underwriting_case_payload(home_id, expected_home_version, planned_scope_lines, **overrides):
    """The PRD's worked underwriting case: 25000000 purchase, 750000 closing costs."""
    return _apply(
        {
            "home_id": home_id,
            "expected_home_version": expected_home_version,
            "purchase_price_cents": 25000000,
            "acquisition_closing_costs_cents": 750000,
            "estimated_monthly_rent_cents": 215000,
            "turn_reserve_annual_cents": 120000,
            "planned_scope_lines": planned_scope_lines,
        },
        overrides,
    )


def decision_payload(decision, **overrides):
    """Payload for ``POST /underwriting-cases/{caseId}/decision``."""
    return _apply({"decision": decision}, overrides)


# --- vendors --------------------------------------------------------------------------
def vendor_payload(market_id, **overrides):
    """The cheaper of the two canonical Atlanta vendors (cost 9800, quality 8600)."""
    return _apply(
        {
            "legal_name": "Peachtree Mechanical LLC",
            "market_id": market_id,
            "daily_crew_capacity": 6,
            "cost_index_bps": 9800,
            "quality_score_bps": 8600,
            "insurance_expires_on": "2027-05-31",
        },
        overrides,
    )


def vendor_certification_payload(vendor_id, certification_code, **overrides):
    """An active certification spanning the whole of 2026."""
    return _apply(
        {
            "vendor_id": vendor_id,
            "certification_code": certification_code,
            "effective_on": "2026-01-01",
            "expires_on": "2026-12-31",
        },
        overrides,
    )


def vendor_status_payload(status, **overrides):
    """Payload for ``POST /vendors/{vendorId}/status``."""
    return _apply({"status": status}, overrides)


# --- renovation projects --------------------------------------------------------------
def renovation_project_payload(home_id, approved_budget_cents=400000, **overrides):
    """An acquisition-renovation project on an acquired home."""
    return _apply(
        {
            "home_id": home_id,
            "project_type": "ACQUISITION_RENOVATION",
            "approved_budget_cents": approved_budget_cents,
        },
        overrides,
    )


def turn_project_payload(home_id, approved_budget_cents=400000, **overrides):
    """A turn project, the second project type on the same home."""
    return _apply(
        renovation_project_payload(home_id, approved_budget_cents, project_type="TURN"),
        overrides,
    )


def budget_payload(approved_budget_cents, **overrides):
    """Payload for ``POST /renovation-projects/{projectId}/budget``."""
    return _apply({"approved_budget_cents": approved_budget_cents}, overrides)


def lock_scope_payload(turn_started_on="2026-08-05", **overrides):
    """Payload for ``POST /renovation-projects/{projectId}/lock-scope``."""
    return _apply({"turn_started_on": turn_started_on}, overrides)


# --- work orders ----------------------------------------------------------------------
def work_order_payload(home_id, scope_template_id, **overrides):
    """A 300000-cent in-house renovation work order over 2026-08-10..2026-08-12."""
    return _apply(
        {
            "home_id": home_id,
            "scope_template_id": scope_template_id,
            "work_type": "RENOVATION",
            "quantity": 1,
            "crew_size": 3,
            "scheduled_start_date": "2026-08-10",
            "scheduled_end_date": "2026-08-12",
            "fulfillment_channel": "IN_HOUSE",
            "quoted_cost_cents": 300000,
        },
        overrides,
    )


def complete_work_order_payload(actual_cost_cents, completed_on, **overrides):
    """Payload for ``POST /work-orders/{workOrderId}/complete``."""
    return _apply(
        {"actual_cost_cents": actual_cost_cents, "completed_on": completed_on},
        overrides,
    )


def void_work_order_payload(void_reason="Duplicate scope line", **overrides):
    """Payload for ``POST /work-orders/{workOrderId}/void``."""
    return _apply({"void_reason": void_reason}, overrides)


# --- prospects ------------------------------------------------------------------------
def prospect_payload(market_id, **overrides):
    """The canonical prospect: credit tier B, 700000 cents declared monthly income."""
    return _apply(
        {
            "email": "p1@example.com",
            "full_name": "Paula One",
            "phone": "+1-404-555-0101",
            "market_id": market_id,
            "declared_monthly_income_cents": 700000,
            "credit_tier": "B",
            "prior_eviction_count": 0,
        },
        overrides,
    )


def identity_verification_payload(expected_prospect_version, **overrides):
    """A clean verification attempt: 9200 bps document match, liveness passed.

    The PRD's post-verification fraud example reads exactly these five factors.
    """
    return _apply(
        {
            "expected_prospect_version": expected_prospect_version,
            "document_type": "DRIVERS_LICENSE",
            "document_match_score_bps": 9200,
            "selfie_liveness_pass": True,
            "verified_monthly_income_cents": 560000,
            "device_reputation_bps": 8800,
            "ip_geo_distance_km": 15,
        },
        overrides,
    )


# --- showing slots --------------------------------------------------------------------
def showing_slot_payload(home_id, **overrides):
    """A compliant 30-minute smart-lock window on 2026-08-20."""
    return _apply(
        {
            "home_id": home_id,
            "starts_at": "2026-08-20T15:00:00Z",
            "ends_at": "2026-08-20T15:30:00Z",
            "access_mode": "SMART_LOCK",
        },
        overrides,
    )


def book_slot_payload(prospect_id, **overrides):
    """Payload for ``POST /showing-slots/{slotId}/book``."""
    return _apply({"prospect_id": prospect_id}, overrides)


def cancel_slot_payload(reason="Prospect schedule conflict", **overrides):
    """Payload for ``POST /showing-slots/{slotId}/cancel``."""
    return _apply({"reason": reason}, overrides)


# --- rental applications --------------------------------------------------------------
def rental_application_payload(home_id, prospect_id, **overrides):
    """A one-pet, twelve-month application requesting a 2026-09-20 move-in."""
    return _apply(
        {
            "prospect_id": prospect_id,
            "home_id": home_id,
            "requested_move_in_date": "2026-09-20",
            "lease_term_months": 12,
            "pet_count": 1,
            "pet_breeds": ["LABRADOR"],
        },
        overrides,
    )


# --- leases ---------------------------------------------------------------------------
def lease_payload(application_id, **overrides):
    """A twelve-month draft lease at 208000 cents -- inside the 500 bps concession band."""
    return _apply(
        {
            "application_id": application_id,
            "start_date": "2026-09-20",
            "term_months": 12,
            "monthly_rent_cents": 208000,
        },
        overrides,
    )


def deposit_payment_payload(amount_cents, **overrides):
    """Payload for ``POST /leases/{leaseId}/deposit-payments``."""
    return _apply({"amount_cents": amount_cents}, overrides)


def execute_lease_payload(signed_on="2026-09-06", **overrides):
    """Payload for ``POST /leases/{leaseId}/execute``."""
    return _apply({"signed_on": signed_on}, overrides)


def void_lease_payload(reason="Resident withdrew before signing", **overrides):
    """Payload for ``POST /leases/{leaseId}/void``."""
    return _apply({"reason": reason}, overrides)


# --- compliance obligations -----------------------------------------------------------
def obligation_payload(home_id, obligation_type="HOA_VIOLATION", severity="MINOR", **overrides):
    """A compliance obligation on a home, due 2026-12-31 by default."""
    return _apply(
        {
            "home_id": home_id,
            "obligation_type": obligation_type,
            "severity": severity,
            "description": "Mailbox paint peeling",
            "due_on": "2026-12-31",
        },
        overrides,
    )


def plan_obligation_payload(planned_resolution_on="2026-09-30", **overrides):
    """Payload for ``POST /compliance-obligations/{obligationId}/plan``."""
    return _apply({"planned_resolution_on": planned_resolution_on}, overrides)


def submit_resolution_payload(**overrides):
    """Payload for ``POST /compliance-obligations/{obligationId}/submit-resolution``.

    Both fields are optional in the payload because which one is mandatory depends on
    the obligation type, so the caller supplies exactly what the type requires.
    """
    return _apply({}, overrides)


def review_resolution_payload(decision, **overrides):
    """Payload for ``POST /compliance-obligations/{obligationId}/review-resolution``."""
    return _apply({"decision": decision}, overrides)


# --- disposition ----------------------------------------------------------------------
def disposition_payload(decision, **overrides):
    """Payload for ``POST /homes/{homeId}/disposition-decision``."""
    return _apply({"decision": decision}, overrides)


def approve_sale_payload(bpo_value_cents=30000000, disposition_mode="INDIVIDUAL", **overrides):
    """An individual-sale approval carrying the broker price opinion."""
    return _apply(
        {
            "decision": "APPROVE_SALE",
            "disposition_mode": disposition_mode,
            "bpo_value_cents": bpo_value_cents,
        },
        overrides,
    )


def close_sale_payload(net_sale_proceeds_cents=30000000, **overrides):
    """A sale-closing decision carrying the realised proceeds."""
    return _apply(
        {"decision": "CLOSE_SALE", "net_sale_proceeds_cents": net_sale_proceeds_cents},
        overrides,
    )
