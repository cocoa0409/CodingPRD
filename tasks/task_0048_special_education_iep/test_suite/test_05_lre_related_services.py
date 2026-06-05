"""Related services and the Least Restrictive Environment: the LRE percentage with
its pinned round-per-service-then-sum order, the setting buckets and their inclusive
floors, the add-then-discontinue conservation invariant, the push-in exclusion, the
OCC version guard on service add, and immediate consistency (PRD §3.8, §2.9, §2.5).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_case_manager_headers,
    create_related_service_payload,
    discontinue_related_service_payload,
    set_clock,
    make_draft_iep_for_eligible_student,
    add_related_service,
    discontinue_service,
    get_iep,
)

CM = make_case_manager_headers("cm_1")


class TestLreBucketBoundary:
    def test_lre_exactly_80_is_full_inclusion(self, api):
        """PRD §3.8: "When the percentage is at least 80.0, the setting is `FULL_INCLUSION`. When the percentage is below 80.0 but at least 40.0, the setting is `RESOURCE`."

        300-min day, one 300-min/week pull-out: daily = round(300/5,2)=60.00; pct =
        (300-60)/300*100 = 80.00 → lands on the inclusive 80.0 floor → FULL_INCLUSION.

        Design: Difficulty/boundary_precision_check/lre_bucket_floor_exact_80_is_full_inclusion
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Gabe Orr", "date_of_birth": "2014-02-02"},
            iep_overrides={"school_day_minutes": 300},
        )
        add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                            minutes_per_week=300, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 80.00, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "FULL_INCLUSION", after["lre_setting"]

    def test_lre_pct_at_80_setting_resolves_to_full_inclusion(self, api):
        """PRD §3.8: "When the percentage is at least 80.0, the setting is `FULL_INCLUSION`."

        Re-confirms the inclusive upper-band edge from the setting side: when
        lre_general_ed_pct computes to exactly 80.00 (300-min day, 300-min/week
        pull-out), the derived lre_setting is FULL_INCLUSION rather than RESOURCE.

        Design: Difficulty/boundary_precision_check/lre_bucket_floor_exact_80_is_full_inclusion
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Gabe Orr2", "date_of_birth": "2014-02-02"},
            iep_overrides={"school_day_minutes": 300},
        )
        add_related_service(iep["id"], iep["version"], service_type="OT",
                            minutes_per_week=300, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 80.00, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "FULL_INCLUSION", after["lre_setting"]

    def test_lre_just_below_80_is_resource(self, api):
        """PRD §3.8: "When the percentage is below 80.0 but at least 40.0, the setting is `RESOURCE`."

        300-min day, one 305-min/week pull-out: daily = round(305/5,2)=61.00; pct =
        (300-61)/300*100 = 79.67 (< 80.0 floor) → RESOURCE, just below FULL_INCLUSION.

        Design: Corner/calculations/lre_pullout_drops_below_full_inclusion_to_separate_class
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Gus Pine", "date_of_birth": "2014-04-04"},
            iep_overrides={"school_day_minutes": 300},
        )
        add_related_service(iep["id"], iep["version"], service_type="PT",
                            minutes_per_week=305, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 79.67, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "RESOURCE", after["lre_setting"]


class TestLreAggregateCapacity:
    def test_two_pullout_services_aggregate_to_86_67(self, api):
        """PRD §3.8: "Those rounded per-service daily contributions are summed, and the sum is itself rounded half-up to two decimal places to form the total daily pull-out minutes. The percentage is then the program's `school_day_minutes` minus that total daily pull-out figure, divided by `school_day_minutes`, multiplied by 100"

        360-min day with 150 + 90 min/week pull-out: daily 30.00 + 18.00 = 48.00;
        pct = (360-48)/360*100 = 86.67.

        Design: Difficulty/resource_temporal_overlap/lre_pullout_aggregate_capacity_overlap
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Ana Wells", "date_of_birth": "2014-04-04"},
            iep_overrides={"school_day_minutes": 360},
        )
        s1 = add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                                 minutes_per_week=150, delivered_in_general_ed=False)
        v2 = get_iep(iep["id"])["version"]
        add_related_service(iep["id"], v2, service_type="OT",
                            minutes_per_week=90, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 86.67, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "FULL_INCLUSION", after["lre_setting"]

    def test_single_pullout_service_per_service_share(self, api):
        """PRD §3.8: "For each such pull-out service, its weekly minutes are converted to a per-school-day share by dividing `minutes_per_week` by 5 (the number of school days per week) and rounding that per-service daily contribution half-up to two decimal places."

        360-min day with a single 150-min/week pull-out: daily 30.00; pct =
        (360-30)/360*100 = 91.67 — the first contribution in the aggregate-capacity
        computation.

        Design: Difficulty/resource_temporal_overlap/lre_pullout_aggregate_capacity_overlap
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Ana Wells2", "date_of_birth": "2014-04-04"},
            iep_overrides={"school_day_minutes": 360},
        )
        add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                            minutes_per_week=150, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 91.67, after["lre_general_ed_pct"]


class TestLreCompensatingInvariant:
    def test_add_then_discontinue_restores_pct(self, api):
        """PRD §3.8: "Discontinuing a related service does the same: a `CaseManager` may discontinue an `ACTIVE` related service, moving it `ACTIVE → DISCONTINUED` (which requires the service to be `ACTIVE` and which is terminal), and this likewise recomputes the parent program's environment percentage and setting and increments both the service's `version` and the program's `version`."
        PRD §3.8: "When a program has no active pull-out services, the percentage is 100.0."

        Adding a 120-min/week pull-out then discontinuing it returns
        lre_general_ed_pct to 100.0 (no active pull-out left).

        Design: Difficulty/compensating_invariant/lre_add_then_discontinue_service_restores_pct
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Joel Tate", "date_of_birth": "2014-05-05"},
            iep_overrides={"school_day_minutes": 360},
        )
        rs = add_related_service(iep["id"], iep["version"], service_type="PT",
                                 minutes_per_week=120, delivered_in_general_ed=False)
        v2 = get_iep(iep["id"])["version"]
        discontinue_service(rs["id"], v2)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 100.0, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "FULL_INCLUSION", after["lre_setting"]

    def test_pct_drops_then_returns_with_no_drift(self, api):
        """PRD §3.8: "When a program has no active pull-out services, the percentage is 100.0."

        The conserved LRE percentage dips while the pull-out service is ACTIVE and
        returns to exactly its pre-action 100.0 once that service is discontinued —
        no residual drift.

        Design: Difficulty/compensating_invariant/lre_add_then_discontinue_service_restores_pct
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Joel Tate2", "date_of_birth": "2014-05-05"},
            iep_overrides={"school_day_minutes": 360},
        )
        rs = add_related_service(iep["id"], iep["version"], service_type="PT",
                                 minutes_per_week=120, delivered_in_general_ed=False)
        mid = get_iep(iep["id"])
        assert mid["lre_general_ed_pct"] < 100.0, mid["lre_general_ed_pct"]
        discontinue_service(rs["id"], mid["version"])
        assert get_iep(iep["id"])["lre_general_ed_pct"] == 100.0


class TestPushInExclusion:
    def test_pushin_service_does_not_reduce_lre(self, api):
        """PRD §3.8: "Only the program's active pull-out services participate — that is, related services on the program whose status is `ACTIVE` and whose `delivered_in_general_ed` flag is false; push-in services and discontinued services do not subtract anything."

        A 300-min/week push-in (delivered_in_general_ed=true) leaves
        lre_general_ed_pct at 100.0.

        Design: Corner/calculations/pushin_service_does_not_reduce_lre
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Hal Reed", "date_of_birth": "2014-05-05"},
            iep_overrides={"school_day_minutes": 360},
        )
        add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                            minutes_per_week=300, delivered_in_general_ed=True)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 100.0, after["lre_general_ed_pct"]
        assert after["lre_setting"] == "FULL_INCLUSION", after["lre_setting"]


class TestServiceAddOcc:
    def test_stale_version_on_second_service_add_rejected(self, api):
        """PRD §2.9: "A request to add a related service must likewise carry `expected_iep_version` as a required field carrying the client's last-observed program `version`. Because each service addition recomputes the program's least-restrictive-environment percentage and bumps the program's `version`, a client whose `expected_iep_version` is outdated is working from a stale environment picture and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        The first add bumps IEP.version; a second add still carrying the pre-first
        version is rejected.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_service_add_returns_412
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Ham Ott", "date_of_birth": "2014-05-05"},
            iep_overrides={"school_day_minutes": 360},
        )
        stale_version = iep["version"]
        add_related_service(iep["id"], stale_version, service_type="SPEECH",
                            minutes_per_week=150, delivered_in_general_ed=False)
        validate_error(
            api.create_related_service(
                create_related_service_payload(
                    iep["id"], stale_version, service_type="OT",
                    minutes_per_week=90, delivered_in_general_ed=False,
                ),
                CM,
            ),
            ApiErrorId.ERR_STALE_VERSION.value,
        )


class TestImmediateConsistency:
    def test_lre_visible_in_followup_read(self, api):
        """PRD §2.5: "A change to a child or related resource that affects a parent's derived state is reflected on the parent in the same operation"
        PRD §3.8: "Adding a related service recomputes the parent program's least-restrictive-environment percentage and setting"

        After adding a 150-min/week pull-out on a 360-min day, an immediate GET shows
        lre_general_ed_pct already at 91.67.

        Design: Corner/consistency_model/immediate_consistency_lre_visible_in_followup_read
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Jay Lund", "date_of_birth": "2014-07-07"},
            iep_overrides={"school_day_minutes": 360},
        )
        add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                            minutes_per_week=150, delivered_in_general_ed=False)
        after = get_iep(iep["id"])
        assert after["lre_general_ed_pct"] == 91.67, after["lre_general_ed_pct"]
