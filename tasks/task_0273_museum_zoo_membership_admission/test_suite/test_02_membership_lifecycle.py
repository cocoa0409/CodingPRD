"""Membership lifecycle: renewal-fee variants, the ACTIVE<->GRACE cycle,
auto-renew and expiry jobs, OCC on renew, and system-assigned fields.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures as fx,
    make_patron_headers,
)


def _membership_id_of(api, patron_id):
    data = validate_success(api.list_memberships(fx.ADMIN, {"primary_patron_id": patron_id}))
    assert len(data) >= 1
    return data[0]["id"]


# ─── Difficulty: renewal_fee early vs lapsed ──────────────────────────

def test_lapsed_reinstatement_fee_includes_reinstatement_surcharge(api):
    """PRD §3.2: "The lapsed variant applies when a membership in GRACE is
    reinstated; the fee is annual_fee_cents plus the plan's
    reinstatement_fee_cents, and the term restarts from the current clock time
    rather than stacking. Every renewal writes the resulting amount to
    last_paid_fee_cents."

    annual 12000 + reinstatement 3000 == 15000 written to last_paid_fee_cents
    after a GRACE reinstatement renewal.

    Design: Difficulty/dual_variant_calc/renewal_fee_early_vs_lapsed_diverge_on_membership_domain
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000,
                        "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    graced = fx.drive_membership_to_grace(m["id"], patron["id"])
    assert graced["status"] == "GRACE"

    renewed = validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": graced["version"]},
        make_patron_headers(patron["id"]),
    ))
    assert renewed["status"] == "ACTIVE"
    assert renewed["last_paid_fee_cents"] == 15000, \
        f"lapsed fee should be 15000, got {renewed['last_paid_fee_cents']}"


def test_early_renewal_fee_is_plain_annual_fee_no_reinstatement(api):
    """PRD §3.2: "The early variant applies when an ACTIVE membership is renewed
    before it expires, whether by a patron's manual early renewal or by the
    auto-renew job; the fee is exactly annual_fee_cents with no proration."

    An early manual renew on an ACTIVE membership charges only annual_fee_cents
    (12000), with no reinstatement surcharge, distinguishing it from the lapsed
    variant.

    Design: Difficulty/dual_variant_calc/renewal_fee_early_vs_lapsed_diverge_on_membership_domain
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000,
                        "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    # Still ACTIVE, clock before expiry -> early variant.
    renewed = validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": m["version"]},
        make_patron_headers(patron["id"]),
    ))
    assert renewed["status"] == "ACTIVE"
    assert renewed["last_paid_fee_cents"] == 12000, \
        f"early fee should be the plain annual fee 12000, got {renewed['last_paid_fee_cents']}"


# ─── Difficulty: cyclic ACTIVE -> GRACE -> ACTIVE ─────────────────────

def test_membership_cycles_grace_back_to_active_via_reinstatement(api):
    """PRD §3.3: "reinstatement renewal moves it from GRACE to ACTIVE, and is
    permitted only while the current clock is at or before grace_until."

    The expiry job moves ACTIVE -> GRACE, then a reinstatement renew returns the
    membership to ACTIVE - the same status it held before.

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_grace_active_via_reinstatement
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000,
                        "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    graced = fx.drive_membership_to_grace(m["id"], patron["id"])
    assert graced["status"] == "GRACE"

    renewed = validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": graced["version"]},
        make_patron_headers(patron["id"]),
    ))
    assert renewed["status"] == "ACTIVE"


def test_reinstatement_increments_term_count(api):
    """PRD §3.3: "On success it sets started_at to the current clock time,
    expires_at to the current clock time plus the plan's term length in days, and
    clears grace_until to null; ... increments term_count by one; and increments
    version by one."

    Second test of the cycle: after the GRACE -> ACTIVE reinstatement the
    term_count is 2.

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_grace_active_via_reinstatement
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000,
                        "household_max": 0, "reinstatement_fee_cents": 3000},
        membership_overrides={"auto_renew": False},
    )
    graced = fx.drive_membership_to_grace(m["id"], patron["id"])
    renewed = validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": graced["version"]},
        make_patron_headers(patron["id"]),
    ))
    assert renewed["term_count"] == 2, \
        f"term_count should be 2 after reinstatement, got {renewed['term_count']}"


# ─── Difficulty + Corner: OCC stale version on renew ──────────────────

def test_renew_with_stale_version_rejected_412(api):
    """PRD §2.7: "The server compares expected_membership_version against the
    membership's current version; if they do not match, the renewal is rejected
    with ERR_STALE_VERSION (HTTP 412) and nothing is mutated."

    A first renew advances version; replaying the original (now stale) version
    on a second renew is rejected with ERR_STALE_VERSION.

    Design: Corner/errors/stale_version_renew_excluded
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000, "household_max": 0},
        membership_overrides={"auto_renew": False},
    )
    observed = validate_success(api.get_membership(m["id"], make_patron_headers(patron["id"])))
    stale_version = observed["version"]
    # First renew with the observed version succeeds and advances version.
    validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": stale_version},
        make_patron_headers(patron["id"]),
    ))
    # Replaying the stale version is rejected.
    resp = api.renew_membership(
        m["id"], {"expected_membership_version": stale_version},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_renew_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.3: "Early renewal requires that expected_membership_version match
    the membership's current version per Section 2.7; on success it ... increments
    term_count by one, and increments the membership's version by one."

    A renew carrying the current version succeeds (200), extends the term, and
    leaves term_count at 2.

    Design: Corner/errors/renew_correct_version_succeeds_and_bumps_version
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000, "household_max": 0},
        membership_overrides={"auto_renew": False},
    )
    observed = validate_success(api.get_membership(m["id"], make_patron_headers(patron["id"])))
    renewed = validate_success(api.renew_membership(
        m["id"], {"expected_membership_version": observed["version"]},
        make_patron_headers(patron["id"]),
    ), expected_status=200)
    assert renewed["term_count"] == 2, \
        f"term_count should be 2 after a successful renew, got {renewed['term_count']}"
    assert renewed["version"] > observed["version"], \
        "version must increment on a successful renew"


# ─── Corner: expiry & auto-renew jobs ─────────────────────────────────

def test_expiry_job_moves_active_to_grace_and_expires_unused_passes(api):
    """PRD §3.3: "an ACTIVE membership whose expires_at is at or before the
    current clock and whose auto_renew is false moves from ACTIVE to GRACE. On
    that transition the system sets grace_until to the membership's expires_at
    plus thirty days, and every guest pass of the membership still in UNUSED
    status expires, moving to EXPIRED."

    Design: Corner/state_machines/expiry_job_active_to_grace_expires_unused_passes
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
        membership_overrides={"auto_renew": False},
    )
    fx.set_clock("2027-06-15T00:00:00Z")
    validate_success(api.run_expirations(fx.ADMIN))

    graced = validate_success(api.get_membership(m["id"], make_patron_headers(patron["id"])))
    assert graced["status"] == "GRACE"
    assert fx.count_guest_passes(m["id"], "EXPIRED") == 2, \
        "both UNUSED passes should expire on ACTIVE -> GRACE"


def test_auto_renew_job_renews_active_membership(api):
    """PRD §3.3: "when run, it renews every ACTIVE membership whose auto_renew is
    true and whose expires_at is at or before the current clock, applying the
    early fee variant to each."
    PRD §3.2: "the fee is exactly annual_fee_cents with no proration."

    run_renewals renews an ACTIVE auto_renew membership past expiry: status stays
    ACTIVE, term_count becomes 2, last_paid_fee_cents == 12000 (early fee).

    Design: Corner/state_machines/auto_renew_job_renews_active_membership
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "INDIVIDUAL", "annual_fee_cents": 12000, "household_max": 0},
        membership_overrides={"auto_renew": True},
    )
    fx.set_clock("2027-06-02T00:00:00Z")
    validate_success(api.run_renewals(fx.ADMIN))

    renewed = validate_success(api.get_membership(m["id"], make_patron_headers(patron["id"])))
    assert renewed["status"] == "ACTIVE"
    assert renewed["term_count"] == 2, f"term_count should be 2, got {renewed['term_count']}"
    assert renewed["last_paid_fee_cents"] == 12000, \
        f"early fee should be 12000, got {renewed['last_paid_fee_cents']}"


# ─── Corner: membership system fields & invalid transitions ───────────

def test_new_membership_is_pending_payment_version_one(api):
    """PRD §3.2: "The new membership's status is PENDING_PAYMENT, its term_count
    begins at 1, and its grace_until is null."
    PRD §2.4: "The version field is an integer that starts at 1."

    POST /memberships returns a server-set status=PENDING_PAYMENT and version==1.

    Design: Corner/entities/membership_id_and_version_are_system_assigned
    """
    plan = fx.create_plan(tier="INDIVIDUAL", household_max=0)
    patron = fx.create_patron()
    m = validate_success(api.create_membership(
        {"plan_id": plan["id"], "primary_patron_id": patron["id"]},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    assert m["status"] == "PENDING_PAYMENT", f"got {m['status']}"
    assert m["version"] == 1, f"got {m['version']}"


def test_cancel_already_cancelled_membership_invalid_state(api):
    """PRD §3.3: "A renewal that targets a membership not in a renewable state, a
    reinstatement attempted after grace_until, or a cancellation of an
    already-terminal membership are all rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_already_cancelled_membership_returns_invalid_state
    """
    plan = fx.create_plan(tier="INDIVIDUAL", household_max=0)
    patron = fx.create_patron()
    m = fx.create_pending_membership(plan["id"], patron["id"])
    validate_success(api.cancel_membership(m["id"], make_patron_headers(patron["id"])))
    resp = api.cancel_membership(m["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
