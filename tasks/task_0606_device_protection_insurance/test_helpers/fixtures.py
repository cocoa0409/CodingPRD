"""Composite setup helpers.

Every test runs against a freshly restarted, empty server. These helpers build the
preconditions each test needs from scratch using only PRD-declared endpoints. They use
get_success_data (lenient) so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from . import constants as C
from .api_client import api_client as api
from .test_users import TEST_USERS, make_subscriber_headers
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
LOGISTICS = TEST_USERS["logistics_agent_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso=C.CLOCK_DEFAULT):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# ---------------------------------------------------------------------------
# IMEI generation (15-digit, Luhn-valid, unique per call)
# ---------------------------------------------------------------------------
_imei_seq = [0]


def _luhn_ok(imei):
    """Standard Luhn validity: double every second digit from the right (1-indexed)."""
    total = 0
    for i, ch in enumerate(reversed(imei)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def fresh_imei():
    """Return a unique 15-digit Luhn-valid IMEI not equal to the suite's fixed IMEIs."""
    _imei_seq[0] += 1
    body = f"99{_imei_seq[0]:012d}"  # 14 digits, deterministic and unique
    for cd in range(10):
        candidate = body + str(cd)
        if _luhn_ok(candidate):
            return candidate
    raise AssertionError("no Luhn check digit found")  # unreachable


# ---------------------------------------------------------------------------
# Tier 1/2: reference data + enrollment progression
# ---------------------------------------------------------------------------
def create_customer(carrier_account_number="CA-AUTO-1", full_name="Test Customer"):
    return get_success_data(api.create_customer(
        F.create_customer_payload(full_name=full_name,
                                  carrier_account_number=carrier_account_number), ADMIN))


_plan_code_seq = [0]


def create_plan(**overrides):
    # Plan `code` must be unique across plans (PRD 3.1); a single test may build several
    # enrollments, so default to a fresh code per call unless the caller overrides it.
    if "code" not in overrides:
        _plan_code_seq[0] += 1
        overrides["code"] = f"PLAN_STD_{_plan_code_seq[0]}"
    return get_success_data(api.create_plan(F.create_plan_payload(**overrides), ADMIN))


def create_sku(**overrides):
    return get_success_data(api.create_replacement_sku(
        F.create_replacement_sku_payload(**overrides), ADMIN))


def create_enrollment(customer_id, plan_id, sku_id, **overrides):
    return get_success_data(api.create_enrollment(
        F.create_enrollment_payload(customer_id, plan_id, sku_id, **overrides), ADMIN))


def create_active_enrollment(carrier="CA-AUTO-1", imei=None, plan_overrides=None,
                             sku_overrides=None, purchase_date=C.PURCHASE_DATE):
    """Reference data + one ACTIVE enrollment. Returns dict of cust/plan/sku/enrollment.

    Activation is bracketed at ENROLL_CLOCK so the enrollment's ``enrolled_at`` precedes
    every incident_at the suite files; the clock is then restored to CLOCK_DEFAULT so claims
    fall strictly after activation and at/before the current clock.

    IMEI defaults to a fresh unique Luhn-valid value so multiple enrollments built within a
    single test do not collide on the PRD's IMEI-uniqueness rule; callers that exercise the
    duplicate-IMEI rule pass ``imei`` explicitly.
    """
    if imei is None:
        imei = fresh_imei()
    cust = create_customer(carrier_account_number=carrier)
    plan = create_plan(**(plan_overrides or {}))
    sku = create_sku(**(sku_overrides or {}))
    enr = create_enrollment(cust["id"], plan["id"], sku["id"],
                            imei=imei, device_purchase_date=purchase_date)
    set_clock(C.ENROLL_CLOCK)
    enr = get_success_data(api.activate_enrollment(enr["id"], ADMIN))
    set_clock(C.CLOCK_DEFAULT)
    return {"customer": cust, "plan": plan, "sku": sku, "enrollment": enr}


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def submit_claim(enrollment_id, peril="CRACKED", incident_at="2026-05-10T00:00:00Z",
                 police_report_number=None, as_headers=ADMIN):
    payload = F.create_claim_payload(enrollment_id, peril=peril, incident_at=incident_at)
    if police_report_number is not None:
        payload["police_report_number"] = police_report_number
    return get_success_data(api.create_claim(payload, as_headers))


def screen_claim(claim_id):
    return get_success_data(api.screen_claim(claim_id, ADJUSTER))


def current_enrollment_version(enrollment_id):
    return get_success_data(api.get_enrollment(enrollment_id, ADMIN))["version"]


def approve_claim(claim_id, enrollment_id):
    v = current_enrollment_version(enrollment_id)
    return get_success_data(api.approve_claim(
        claim_id, {"expected_enrollment_version": v}, ADJUSTER))


def submit_screen_approve(enrollment_id, peril="CRACKED",
                          incident_at="2026-05-10T00:00:00Z",
                          police_report_number=None):
    """Submit -> screen -> approve. Returns the APPROVED claim."""
    cl = submit_claim(enrollment_id, peril=peril, incident_at=incident_at,
                      police_report_number=police_report_number)
    screen_claim(cl["id"])
    return approve_claim(cl["id"], enrollment_id)


def deny_claim(claim_id, denial_reason="NO_COVERAGE"):
    return get_success_data(api.deny_claim(claim_id, {"denial_reason": denial_reason}, ADJUSTER))


def submit_screen_deny(enrollment_id, peril="CRACKED",
                       incident_at="2026-05-10T00:00:00Z", denial_reason="NO_COVERAGE"):
    """Submit -> screen -> deny. Returns the DENIED claim."""
    cl = submit_claim(enrollment_id, peril=peril, incident_at=incident_at)
    screen_claim(cl["id"])
    return deny_claim(cl["id"], denial_reason=denial_reason)


# ---------------------------------------------------------------------------
# Tier 3: routing helpers
# ---------------------------------------------------------------------------
def route_claim(claim_id, repair_cost_cents=None):
    payload = {}
    if repair_cost_cents is not None:
        payload["repair_cost_cents"] = repair_cost_cents
    return get_success_data(api.route_claim(claim_id, payload, ADJUSTER))


def exchange_for_claim(claim_id):
    data, _ = _list(api.list_advanced_exchanges(ADJUSTER, params={"claim_id": claim_id}))
    return data[0]


def repair_order_for_claim(claim_id):
    data, _ = _list(api.list_repair_orders(ADJUSTER, params={"claim_id": claim_id}))
    return data[0]


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


def setup_routed_replace(carrier="CA-AUTO-1", sku_overrides=None, peril="LOST"):
    """Active enrollment -> LOST claim -> screen -> approve -> route REPLACE.
    Returns dict including the RESERVED exchange and the claim's post-route version."""
    base = create_active_enrollment(carrier=carrier, sku_overrides=sku_overrides)
    enr = base["enrollment"]
    cl = submit_claim(enr["id"], peril=peril, incident_at="2026-05-10T00:00:00Z")
    screen_claim(cl["id"])
    approve_claim(cl["id"], enr["id"])
    routed = route_claim(cl["id"])
    ax = exchange_for_claim(cl["id"])
    base.update({"claim": routed, "claim_version": routed["version"], "exchange": ax})
    return base


def setup_shipped_exchange(carrier="CA-AUTO-1"):
    """setup_routed_replace -> ship the exchange. Returns dict with SHIPPED exchange."""
    base = setup_routed_replace(carrier=carrier)
    ax = base["exchange"]
    shipped = get_success_data(api.ship_advanced_exchange(
        ax["id"], {"expected_claim_version": base["claim_version"]}, LOGISTICS))
    base["exchange"] = shipped
    return base


def setup_delivered_exchange(carrier="CA-AUTO-1"):
    """Shipped -> delivered. Returns dict with DELIVERED exchange."""
    base = setup_shipped_exchange(carrier=carrier)
    delivered = get_success_data(api.deliver_advanced_exchange(base["exchange"]["id"], LOGISTICS))
    base["exchange"] = delivered
    return base


def setup_graded_trade_in(carrier="CA-AUTO-1", condition_grade="A"):
    """Delivered exchange -> trade-in received -> graded. Returns dict with GRADED trade-in."""
    base = setup_delivered_exchange(carrier=carrier)
    ti = get_success_data(api.create_trade_in(
        F.create_trade_in_payload(base["exchange"]["id"], condition_grade=condition_grade),
        LOGISTICS))
    graded = get_success_data(api.grade_trade_in(ti["id"], LOGISTICS))
    base["trade_in"] = graded
    return base


# ---------------------------------------------------------------------------
# Tier 4: fraud-velocity accumulation
# ---------------------------------------------------------------------------
def build_denied_history(enrollment_id, incident_dates):
    """Create + screen + deny one claim per incident date (in order). Returns list of claims."""
    out = []
    for d in incident_dates:
        out.append(submit_screen_deny(enrollment_id, peril="CRACKED", incident_at=d))
    return out


# ---------------------------------------------------------------------------
# Tier: billing
# ---------------------------------------------------------------------------
def issue_invoice(enrollment_id, cycle_index=0):
    return get_success_data(api.create_premium_invoice(
        F.create_premium_invoice_payload(enrollment_id, cycle_index), ADMIN))


def pay_invoice(invoice_id, enrollment_id):
    v = current_enrollment_version(enrollment_id)
    return get_success_data(api.pay_premium_invoice(
        invoice_id, {"expected_enrollment_version": v}, ADMIN))


def _current_cycle_index(enrolled_at_iso, clock_iso=C.CLOCK_DEFAULT):
    """Cycle index since activation = floor(days between enrolled_at and clock / 30)."""
    from datetime import datetime, timezone
    import math

    def _p(s):
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc)

    days = (_p(clock_iso) - _p(enrolled_at_iso)).total_seconds() / 86400.0
    return max(0, int(math.floor(days / 30.0)))


def pay_through_current_cycle(enr):
    """Issue + pay an invoice for the enrollment's current billing cycle so that
    premium_paid_through_cycle covers the current cycle (the reinstatement precondition).
    Returns the paid invoice.
    """
    cycle = _current_cycle_index(enr["enrolled_at"])
    inv = issue_invoice(enr["id"], cycle)
    return pay_invoice(inv["id"], enr["id"])
