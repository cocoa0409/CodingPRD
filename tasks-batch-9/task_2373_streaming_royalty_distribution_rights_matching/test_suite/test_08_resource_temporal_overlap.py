"""Overlap geometry for the two entities that occupy time windows.

A rights registration's ownership interval is half-open and treats `WORLD` as a
territory wildcard that competes for the same occupancy slot, while a rate
schedule's applicability window is closed at both ends and treats `WORLD` as a
separate specificity layer that never competes. Both the occupancy refusals and
the selection outcomes that follow from those two geometries are exercised here.
"""

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    append_line,
    approve_registration,
    assert_pool_value_conservation,
    create_batch,
    create_label,
    create_period,
    create_pool,
    create_recording,
    create_schedule,
    file_registration_under_review,
    promulgate_schedule,
    seal_and_match_batch,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["royalty_admin_headers"]
ANALYST = TEST_USERS["rights_ops_analyst_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
REGULATOR = TEST_USERS["regulatory_officer_headers"]


# ─────────────────────────────────────────────────────
# Composite setups
# ─────────────────────────────────────────────────────

def _setup_four_master_claims_under_review(api):
    """One recording and four LABEL claimants, each holding one UNDER_REVIEW
    MASTER claim of 10000 basis points except the worldwide one of a single
    basis point:

    * A — GB, 2026-01-01 to 2026-07-01, 10000 bps;
    * B — GB, 2026-07-01 to 2027-01-01, 10000 bps;
    * C — WORLD, 2026-06-01 to 2026-06-30, 1 bp;
    * D — IE, 2026-01-01 to 2026-07-01, 10000 bps.

    No usage exists anywhere, so the claim window never interferes.
    """
    fixture = {
        "holders": [
            create_label(api, legal_name="Northbeam Records", territory="GB", rate_bps=800),
            create_label(api, legal_name="Kestrel Tapes", territory="GB", rate_bps=800),
            create_label(api, legal_name="Longwave Discos", territory="GB", rate_bps=800),
            create_label(api, legal_name="Shannon Vinyl", territory="IE", rate_bps=800),
        ]
    }
    fixture["recording"] = create_recording(api)

    claims = [
        (0, 10000, ["GB"], "2026-01-01", "2026-07-01"),
        (1, 10000, ["GB"], "2026-07-01", "2027-01-01"),
        (2, 1, ["WORLD"], "2026-06-01", "2026-06-30"),
        (3, 10000, ["IE"], "2026-01-01", "2026-07-01"),
    ]
    registrations = []
    for holder_index, share_bps, territory_set, effective_from, effective_to in claims:
        registrations.append(
            file_registration_under_review(
                api,
                fixture["recording"]["id"],
                fixture["holders"][holder_index]["id"],
                right_type="MASTER",
                routing="DIRECT",
                share_bps=share_bps,
                territory_set=territory_set,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
    for registration in registrations:
        assert registration["status"] == "UNDER_REVIEW"

    fixture["registration_a"] = registrations[0]
    fixture["registration_b"] = registrations[1]
    fixture["registration_c"] = registrations[2]
    fixture["registration_d"] = registrations[3]
    return fixture


def _setup_layered_rate_schedules_and_pools(api):
    """The 2026-06 period with one sealed, matched batch carrying a GB line and
    an IE line of 450000 plays each, two identical pools differing only in
    territory, and four PROPOSED INDIVIDUAL schedules:

    * H1 — GB, 2026-01-01 to 2026-06-30, revenue share 7000 bps;
    * H2 — GB, 2026-06-30 to 2026-12-31, revenue share 6500 bps;
    * H3 — GB, 2026-07-01 to 2026-12-31, revenue share 5500 bps;
    * W — WORLD, 2026-01-01 to 2026-12-31, revenue share 6000 bps.
    """
    fixture = {"period": create_period(api)}
    fixture["recording"] = create_recording(api)
    period_id = fixture["period"]["id"]

    fixture["batch"] = create_batch(api, period_id)
    for territory_code in ("GB", "IE"):
        append_line(
            api,
            fixture["batch"]["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code=territory_code,
            subscription_tier="INDIVIDUAL",
            play_count=450000,
        )
    fixture["batch_after_match"] = seal_and_match_batch(api, fixture["batch"]["id"])

    fixture["schedule_h1"] = create_schedule(
        api,
        proceeding_ref="CRB-2026-H1",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        revenue_share_bps=7000,
        effective_from="2026-01-01",
        effective_to="2026-06-30",
    )
    fixture["schedule_h2"] = create_schedule(
        api,
        proceeding_ref="CRB-2026-H2",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        revenue_share_bps=6500,
        effective_from="2026-06-30",
        effective_to="2026-12-31",
    )
    fixture["schedule_h3"] = create_schedule(
        api,
        proceeding_ref="CRB-2026-H3",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        revenue_share_bps=5500,
        effective_from="2026-07-01",
        effective_to="2026-12-31",
    )
    fixture["schedule_world"] = create_schedule(
        api,
        proceeding_ref="CRB-2026-W",
        territory_code="WORLD",
        subscription_tier="INDIVIDUAL",
        revenue_share_bps=6000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    fixture["pool_gb"] = create_pool(
        api,
        period_id,
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    fixture["pool_ie"] = create_pool(
        api,
        period_id,
        territory_code="IE",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    return fixture


def _make_gb_and_world_layers_effective(api, fixture):
    """Bring H1, H3 and W into force — the three that can coexist."""
    fixture["schedule_h1"] = promulgate_schedule(api, fixture["schedule_h1"]["id"])
    fixture["schedule_h3"] = promulgate_schedule(api, fixture["schedule_h3"]["id"])
    fixture["schedule_world"] = promulgate_schedule(
        api, fixture["schedule_world"]["id"]
    )
    return fixture


# ─────────────────────────────────────────────────────
# registration_half_open_interval_and_world_wildcard
# ─────────────────────────────────────────────────────

class TestRegistrationHalfOpenIntervalAndWorldWildcard:

    def test_two_full_gb_claims_sharing_an_endpoint_both_approve(self, api):
        """Two 10000-bps GB claims that meet at 2026-07-01 both approve, because the half-open interval gives that day to the later claim alone.

        PRD: "A `RightsRegistration`'s ownership interval runs from `effective_from` inclusive to `effective_to` **exclusive**; equal endpoints would describe an empty interval and are therefore invalid, so `effective_to` must be strictly after `effective_from`."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_interval_and_world_wildcard
        """
        fixture = _setup_four_master_claims_under_review(api)

        approved_a = validate_success(
            api.approve_rights_registration(fixture["registration_a"]["id"], REVIEWER),
            200,
        )
        assert approved_a["status"] == "APPROVED"
        assert approved_a["effective_from"] == "2026-01-01"
        assert approved_a["effective_to"] == "2026-07-01"

        approved_b = validate_success(
            api.approve_rights_registration(fixture["registration_b"]["id"], REVIEWER),
            200,
        )
        assert approved_b["status"] == "APPROVED"
        assert approved_b["effective_from"] == "2026-07-01"
        assert approved_b["share_bps"] == 10000

    def test_worldwide_claim_overlapping_a_concrete_gb_claim_is_refused(self, api):
        """A worldwide claim of a single basis point is refused with ERR_SHARE_OVERSUBSCRIBED because WORLD intersects GB, where the overlapping total would reach 10001.

        PRD: "When two registrations are compared for territorial overlap, `WORLD` behaves as a wildcard that intersects every territory, including another `WORLD`."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_interval_and_world_wildcard
        """
        fixture = _setup_four_master_claims_under_review(api)
        approve_registration(api, fixture["registration_a"]["id"])
        approve_registration(api, fixture["registration_b"]["id"])

        response = api.approve_rights_registration(
            fixture["registration_c"]["id"], REVIEWER
        )
        validate_error(response, ApiErrorId.ERR_SHARE_OVERSUBSCRIBED.value, 409)

        refused = validate_success(
            api.get_rights_registration(fixture["registration_c"]["id"], ANALYST), 200
        )
        assert refused["status"] == "UNDER_REVIEW"
        assert refused["territory_set"] == ["WORLD"]
        assert refused["share_bps"] == 1

    def test_claim_over_a_disjoint_territory_approves_on_an_identical_interval(self, api):
        """An IE claim of 10000 bps approves over exactly the interval already held in GB, because occupancy is summed per concrete territory.

        PRD: "For the registration being approved, and for each concrete territory in its `territory_set` — or, when the set is exactly the single literal `WORLD`, for every territory already claimed on this work — the service sums `share_bps` over all `APPROVED` registrations of the same work and the same `right_type` whose `territory_set` contains that territory or the literal `WORLD` and whose half-open interval overlaps this registration's interval, then adds this registration's own `share_bps`."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_interval_and_world_wildcard
        """
        fixture = _setup_four_master_claims_under_review(api)
        approve_registration(api, fixture["registration_a"]["id"])
        approve_registration(api, fixture["registration_b"]["id"])

        response = api.approve_rights_registration(
            fixture["registration_d"]["id"], REVIEWER
        )
        approved_d = validate_success(response, 200)
        assert approved_d["status"] == "APPROVED"
        assert approved_d["territory_set"] == ["IE"]
        assert approved_d["share_bps"] == 10000
        assert approved_d["effective_from"] == "2026-01-01"
        assert approved_d["effective_to"] == "2026-07-01"
        assert approved_d["payee_holder_id"] == fixture["holders"][3]["id"]

    def test_approved_master_share_counts_only_worldwide_registrations(self, api):
        """With three concrete-territory MASTER claims approved and the worldwide one refused, the work reports approved_master_share_bps 0 and rights_state REGISTERED.

        PRD: "Alongside it, `approved_master_share_bps` reports the sum of `share_bps` over the work's `APPROVED` registrations whose `right_type` is `MASTER` and whose `territory_set` contains the literal `WORLD`; it starts at 0 and exists for observability only."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_interval_and_world_wildcard
        """
        fixture = _setup_four_master_claims_under_review(api)
        approve_registration(api, fixture["registration_a"]["id"])
        approve_registration(api, fixture["registration_b"]["id"])
        validate_error(
            api.approve_rights_registration(fixture["registration_c"]["id"], REVIEWER),
            ApiErrorId.ERR_SHARE_OVERSUBSCRIBED.value,
            409,
        )
        approve_registration(api, fixture["registration_d"]["id"])

        work = validate_success(api.get_work(fixture["recording"]["id"], ANALYST), 200)
        assert work["approved_master_share_bps"] == 0
        assert work["rights_state"] == "REGISTERED"


# ─────────────────────────────────────────────────────
# rate_schedule_closed_interval_and_specificity_layers
# ─────────────────────────────────────────────────────

class TestRateScheduleClosedIntervalAndSpecificityLayers:

    def test_schedules_touching_on_one_day_collide_on_promulgation(self, api):
        """Two GB schedules that merely share the endpoint 2026-06-30 collide, so the second is refused with ERR_RATE_SCHEDULE_OVERLAP and stays PROPOSED.

        PRD: "And occupancy must be exclusive: promulgation is refused with `ERR_RATE_SCHEDULE_OVERLAP` when another `EFFECTIVE` schedule exists for the same `territory_code` and `subscription_tier` whose closed window overlaps this one's — and touching endpoints do count as an overlap — unless `supersede_incumbent` is true, in which case the incumbent is displaced first and no conflict remains."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_and_specificity_layers
        """
        fixture = _setup_layered_rate_schedules_and_pools(api)

        effective_h1 = validate_success(
            api.promulgate_rate_schedule(fixture["schedule_h1"]["id"], REGULATOR, {}),
            200,
        )
        assert effective_h1["status"] == "EFFECTIVE"
        assert effective_h1["promulgated_at"] is not None

        response = api.promulgate_rate_schedule(
            fixture["schedule_h2"]["id"], REGULATOR, {}
        )
        validate_error(response, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP.value, 409)

        refused = validate_success(
            api.get_rate_schedule(fixture["schedule_h2"]["id"], REGULATOR), 200
        )
        assert refused["status"] == "PROPOSED"
        assert refused["promulgated_at"] is None
        assert refused["effective_from"] == "2026-06-30"

    def test_schedule_starting_one_day_after_the_incumbent_promulgates(self, api):
        """A GB schedule starting on 2026-07-01, one day after the incumbent's inclusive end, promulgates to EFFECTIVE.

        PRD: "A `RateSchedule`'s applicability window runs from `effective_from` to `effective_to` **inclusive at both ends**; equal endpoints describe a legal one-day window, so `effective_to` need only be on or after `effective_from`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_and_specificity_layers
        """
        fixture = _setup_layered_rate_schedules_and_pools(api)
        promulgate_schedule(api, fixture["schedule_h1"]["id"])

        response = api.promulgate_rate_schedule(
            fixture["schedule_h3"]["id"], REGULATOR, {}
        )
        effective_h3 = validate_success(response, 200)
        assert effective_h3["status"] == "EFFECTIVE"
        assert effective_h3["effective_from"] == "2026-07-01"
        assert effective_h3["promulgated_at"] is not None

    def test_world_schedule_does_not_collide_with_the_concrete_layer(self, api):
        """A WORLD schedule spanning the whole year promulgates alongside both effective GB schedules it intersects in time.

        PRD: "The two geometries also differ in how `WORLD` behaves for conflict detection: a worldwide registration collides with a concrete-territory registration of the same work, right and claimant, whereas a `WORLD` rate schedule does **not** collide with a concrete-territory rate schedule for the same tier, because those are separate specificity layers resolved at selection time rather than competing occupants of the same slot."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_and_specificity_layers
        """
        fixture = _setup_layered_rate_schedules_and_pools(api)
        promulgate_schedule(api, fixture["schedule_h1"]["id"])
        promulgate_schedule(api, fixture["schedule_h3"]["id"])

        response = api.promulgate_rate_schedule(
            fixture["schedule_world"]["id"], REGULATOR, {}
        )
        effective_world = validate_success(response, 200)
        assert effective_world["status"] == "EFFECTIVE"
        assert effective_world["territory_code"] == "WORLD"

        for key in ("schedule_h1", "schedule_h3"):
            incumbent = validate_success(
                api.get_rate_schedule(fixture[key]["id"], REGULATOR), 200
            )
            assert incumbent["status"] == "EFFECTIVE"

    def test_gb_pool_resolves_to_the_concrete_territory_layer(self, api):
        """The GB pool selects the GB schedule whose inclusive window ends on the period's usage_end, reaching distributable_cents 999999.

        PRD: "Among the candidates, a schedule naming the pool's concrete territory outranks a `WORLD` fallback; among schedules of equal specificity, the one with the later `effective_from` wins; a remaining tie is broken by the earlier `created_at`, and then by the lexicographically smaller `proceeding_ref`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_and_specificity_layers
        """
        fixture = _setup_layered_rate_schedules_and_pools(api)
        _make_gb_and_world_layers_effective(api, fixture)

        pool = validate_success(api.calculate_pool(fixture["pool_gb"]["id"], ADMIN), 200)
        assert pool["status"] == "CALCULATED"
        assert pool["applied_rate_schedule_id"] == fixture["schedule_h1"]["id"]
        assert pool["applied_rate_schedule_id"] != fixture["schedule_world"]["id"]
        assert pool["applied_rate_schedule_id"] != fixture["schedule_h3"]["id"]
        assert pool["total_play_count"] == 450000
        assert pool["distributable_cents"] == 999999
        assert pool["matched_attributed_cents"] == 999999
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)

    def test_ie_pool_resolves_to_the_world_fallback_layer(self, api):
        """The IE pool, identical in every input but territory, falls back to the WORLD layer and reaches distributable_cents 857142 instead.

        PRD: "The candidate set contains every rate schedule whose `status` is `EFFECTIVE`, whose `subscription_tier` equals the pool's `subscription_tier`, whose `territory_code` either equals the pool's `territory_code` or is the literal `WORLD`, and whose inclusive applicability window contains the period's `usage_end` — that is, `effective_from` is on or before `usage_end` and `effective_to` is on or after `usage_end`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_and_specificity_layers
        """
        fixture = _setup_layered_rate_schedules_and_pools(api)
        _make_gb_and_world_layers_effective(api, fixture)

        pool = validate_success(api.calculate_pool(fixture["pool_ie"]["id"], ADMIN), 200)
        assert pool["status"] == "CALCULATED"
        assert pool["applied_rate_schedule_id"] == fixture["schedule_world"]["id"]
        assert pool["applied_rate_schedule_id"] != fixture["schedule_h1"]["id"]
        assert pool["total_play_count"] == 450000
        assert pool["distributable_cents"] == 857142
        assert pool["matched_attributed_cents"] == 857142
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)
