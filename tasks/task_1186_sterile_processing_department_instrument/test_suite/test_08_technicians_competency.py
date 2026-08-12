"""Technician standing (suspend/reinstate), the lazy certification-expiry
sweep, competency decay tiers, the rolling-vs-lifetime variants, and the
LOW_TEMP_H2O2 gating boundary.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_competency_invariants,
    make_supervisor_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]


def test_technician_suspend_reinstate_gates(api):
    """PRD §3.8: "A `SpdSupervisor` suspends an `ACTIVE` technician (else
    `ERR_TECHNICIAN_NOT_ACTIVE`) to `SUSPENDED`, and reinstates a `SUSPENDED`
    one (else `ERR_TECHNICIAN_NOT_SUSPENDED`) back to `ACTIVE`."

    Design: Corner/state_machines/technician_suspend_reinstate_gates
    """
    ta = fx.create_technician(api, name="Tech A")
    ts = fx.create_technician(api, name="Sup S", certification_level=3)
    hs = make_supervisor_headers(ts["id"])

    e1 = api.reinstate_technician(ta["id"], hs)
    validate_error(e1, ApiErrorId.ERR_TECHNICIAN_NOT_SUSPENDED)

    s1 = validate_success(api.suspend_technician(ta["id"], hs))
    assert s1["status"] == "SUSPENDED"

    e2 = api.suspend_technician(ta["id"], hs)
    validate_error(e2, ApiErrorId.ERR_TECHNICIAN_NOT_ACTIVE)

    s2 = validate_success(api.reinstate_technician(ta["id"], hs))
    assert s2["status"] == "ACTIVE"


def test_suspended_technician_cannot_start_load(api):
    """PRD §3.4: "The acting technician must exist and be in good standing: a
    `SUSPENDED` technician draws `ERR_TECHNICIAN_SUSPENDED`".

    Design: Corner/state_machines/suspended_technician_cannot_start_load
    """
    s = fx.setup_suspended_start_scenario(api)
    resp = api.start_load(s.ld["id"], make_technician_headers(s.ta["id"]))
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_SUSPENDED)
    load = validate_success(api.get_sterilization_load(s.ld["id"], ADMIN))
    assert load["status"] == "LOADING"


def test_certification_expiry_sweep_blocks_and_renewal_restores(api):
    """PRD §3.8: "the lazy certification sweep (§2.4) flips an `ACTIVE`
    technician to `CERTIFICATION_EXPIRED` the first time the technician is
    read or touched after the logical clock has passed
    `certification_expires_at`" and "renewing `certification_expires_at` to an
    instant beyond the current logical time reactivates a
    `CERTIFICATION_EXPIRED` technician back to `ACTIVE`." PRD §3.4: "a
    `CERTIFICATION_EXPIRED` one (post-sweep, §2.4) draws
    `ERR_CERTIFICATION_EXPIRED`".

    Design: Corner/state_machines/certification_expiry_sweep_blocks_and_renewal_restores
    """
    s = fx.setup_cert_expiry_scenario(api)
    e1 = api.start_load(s.ld["id"], make_technician_headers(s.ta["id"]))
    validate_error(e1, ApiErrorId.ERR_CERTIFICATION_EXPIRED)

    swept = validate_success(api.get_technician(s.ta["id"], ADMIN))
    assert swept["status"] == "CERTIFICATION_EXPIRED"

    renewed = validate_success(
        api.update_technician(
            s.ta["id"], {"certification_expires_at": "2027-01-01T00:00:00Z"}, ADMIN
        )
    )
    assert renewed["status"] == "ACTIVE"

    started = validate_success(
        api.start_load(s.ld["id"], make_technician_headers(s.ta["id"]))
    )
    assert started["status"] == "RUNNING"


def test_h2o2_competency_gate_boundary(api):
    """PRD §3.4: "For a `LOW_TEMP_H2O2` sterilizer there is one further gate:
    the technician's rolling `competency_score` must be at least 70 — a score
    of exactly 70 passes — else `ERR_COMPETENCY_BELOW_THRESHOLD`." PRD §3.8:
    "each failed assembly verification attributed to the technician costs 2
    points ... and each load that reached `FAILED_CYCLE` under their operation
    costs 8 points".

    Design: Corner/state_machines/h2o2_competency_gate_boundary
    """
    s = fx.setup_h2o2_gate_scenario(api)
    assert s.g1_started["status"] == "RUNNING", (
        "at exactly 70 (100 - 16 - 14) the H2O2 gate passes"
    )
    tech = validate_success(api.get_technician(s.ta["id"], ADMIN))
    assert tech["competency_score"] == 68, (
        "the eighth verification failure drops the score to 100 - 16 - 14 - 2"
    )
    resp = api.start_load(s.g2["id"], make_technician_headers(s.ta["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPETENCY_BELOW_THRESHOLD)
    g2 = validate_success(api.get_sterilization_load(s.g2["id"], ADMIN))
    assert g2["status"] == "LOADING"


def test_competency_decay_ladder(api):
    """PRD §3.8: "The rolling variant, surfaced as `competency_score`, counts
    only events aged at most 90 days, weighting each at 1.0 when aged at most
    30 days, at 0.5 when aged more than 30 and at most 60 days, and at 0.25
    when aged more than 60 and at most 90 days. The lifetime variant,
    surfaced as `competency_score_lifetime`, counts every event at full weight
    regardless of age".

    Design: Corner/calculations/competency_decay_ladder
    """
    tpl = fx.create_template(api)
    ta = fx.create_technician(
        api, name="Tech A", certification_level=2,
        certification_expires_at="2027-06-01T00:00:00Z",
    )
    tray = fx.create_tray(api, tpl["id"], ta["id"], label="V1")
    fx.decontaminate(api, tray["id"], ta["id"])
    h = make_technician_headers(ta["id"])
    validate_success(api.start_assembly(tray["id"], h))
    fail = validate_success(
        api.submit_assembly_verification(
            tray["id"],
            f.assembly_verification_payload(
                lines=[{"instrument_type": "SCALPEL", "counted_qty": 1}]
            ),
            h,
        ),
        201,
    )
    assert fail["result"] == "FAIL"

    fx.set_clock(api, "2026-05-31T00:00:00Z")
    s30 = validate_success(api.get_technician(ta["id"], ADMIN))
    assert s30["competency_score"] == 98, (
        "age exactly 30d stays in tier 1: 100 - 2 x 1.0"
    )

    fx.set_clock(api, "2026-06-15T00:00:00Z")
    s45 = validate_success(api.get_technician(ta["id"], ADMIN))
    assert s45["competency_score"] == 99, "age 45d: 100 - 2 x 0.5"

    fx.set_clock(api, "2026-07-31T00:00:00Z")
    s91 = validate_success(api.get_technician(ta["id"], ADMIN))
    assert s91["competency_score"] == 100, "age 91d falls outside the 90d window"
    assert s91["competency_score_lifetime"] == 98, "the lifetime variant never forgets"
    assert_competency_invariants(s91)


class TestCompetencyRollingVsLifetime:
    """Identical 100-day-old demerit history, two score variants (two tests,
    one design instance)."""

    def test_rolling_window_excludes_events_older_than_90_days(self, api):
        """PRD §3.8: "The rolling variant, surfaced as `competency_score`,
        counts only events aged at most 90 days".

        Design: Difficulty/dual_variant_calc/technician_competency_rolling_vs_lifetime
        """
        s = fx.setup_competency_history_scenario(api)
        assert s.fail_record["result"] == "FAIL", "setup sanity: the demerit recorded"
        tech = validate_success(api.get_technician(s.tech_b["id"], ADMIN))
        assert tech["competency_score"] == 100, (
            "both demerits are aged 100d > 90d and drop out of the window"
        )
        assert tech["status"] == "ACTIVE", (
            "certification_expires_at 2027-06-01 is still ahead of the clock"
        )

    def test_lifetime_counts_every_event_at_full_weight(self, api):
        """PRD §3.8: "The lifetime variant, surfaced as
        `competency_score_lifetime`, counts every event at full weight
        regardless of age — an identical event history therefore yields a
        lifetime score lower than or equal to the rolling score."

        Design: Difficulty/dual_variant_calc/technician_competency_rolling_vs_lifetime
        """
        s = fx.setup_competency_history_scenario(api)
        tech = validate_success(api.get_technician(s.tech_b["id"], ADMIN))
        assert tech["competency_score_lifetime"] == 90, (
            "100 - 2 (FAIL verification) - 8 (FAILED_CYCLE), no window"
        )
        assert_competency_invariants(tech)
