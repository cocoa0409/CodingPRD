"""Pipeline diversity measurement: department and HiPo-cycle scopes."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_talent_manager, setup_manager, setup_report,
    setup_active_role, add_active_successor,
    setup_hipo_cycle, nominate, endorse_nomination, enroll_nomination,
    capture_department_snapshot, capture_cycle_snapshot,
    assert_diversity_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSnapshotShape:
    def test_diversity_snapshot_immutable_no_version(self, api):
        """PRD §2.5: "The `DiversitySnapshot` resource is the sole exception:
        it is an immutable, append-only record carrying only `id` and
        `created_at`. Both `updated_at` and `version` are absent from it, and
        no operation modifies a snapshot after creation."
        PRD §3.8: "when no role participates, both counts are 0 and
        `diversity_index` is null."

        Design: Corner/entities/diversity_snapshot_immutable_no_version
        """
        created = validate_success(api.create_diversity_snapshot(
            {"scope_type": "DEPARTMENT", "scope_ref": "NOWHERE"}, ADMIN,
        ), 201)
        assert_diversity_snapshot(created)
        assert created["total_subjects"] == 0
        assert created["underrepresented_count"] == 0
        assert created["diversity_index"] is None
        assert "version" not in created and "updated_at" not in created

        fetched = get_success_data(api.get_diversity_snapshot(created["id"], ADMIN))
        assert "version" not in fetched and "updated_at" not in fetched
        assert fetched["diversity_index"] is None


class TestDepartmentScope:
    def test_diversity_index_department_tier_weighted(self, api):
        """PRD §3.8: "Under the `DEPARTMENT` scope, the population is drawn
        from the named department's roles in `ACTIVE` or `VACANT` status,
        restricted to roles holding at least one `ACTIVE` successor entry; each
        participating role contributes a ratio — its underrepresented `ACTIVE`
        entries (those in groups `GROUP_C` and `GROUP_D`) over its total
        `ACTIVE` entries — and the `diversity_index` is the tier-weighted
        average of these ratios, with weights 3 for `TIER_1`, 2 for `TIER_2`,
        and 1 for `TIER_3`, multiplied by 100 and rounded half-up to 2 decimal
        places."
        PRD §3.8: "The snapshot's `total_subjects` sums the `ACTIVE` entries
        across participating roles and `underrepresented_count` sums the
        underrepresented ones"

        Design: Corner/calculations/diversity_index_department_tier_weighted
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(job_level=8, performance_rating="STRONG",
                                   hire_date="2019-03-01")
        dee_a = setup_employee(job_level=6, performance_rating="STRONG",
                               hire_date="2022-07-01", demographic_group="GROUP_C")
        dee_b = setup_employee(job_level=6, performance_rating="STRONG",
                               hire_date="2022-07-01", demographic_group="GROUP_A")
        dee_c = setup_employee(job_level=6, performance_rating="STRONG",
                               hire_date="2022-07-01", demographic_group="GROUP_C")
        # TIER_1 role: 2 ACTIVE entries, one underrepresented -> ratio 0.5.
        role_t1 = setup_active_role(hrbp_headers, incumbent["id"],
                                    role_title="Role T1", criticality_tier="TIER_1")
        add_active_successor(role_t1["id"], dee_a["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)
        add_active_successor(role_t1["id"], dee_b["id"], hrbp_headers,
                             readiness_rating="READY_1_2", slate_position=2)
        # TIER_2 role: 1 ACTIVE entry, underrepresented -> ratio 1.0.
        role_t2 = setup_active_role(hrbp_headers, incumbent["id"],
                                    role_title="Role T2", criticality_tier="TIER_2",
                                    assessment_method="COVERAGE")
        add_active_successor(role_t2["id"], dee_c["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)
        # TIER_3 role: empty slate -> excluded from both sums.
        setup_active_role(hrbp_headers, incumbent["id"], role_title="Role T3 empty",
                          criticality_tier="TIER_3")

        snapshot = capture_department_snapshot("ENG")
        assert_diversity_snapshot(snapshot)
        assert snapshot["total_subjects"] == 3
        assert snapshot["underrepresented_count"] == 2
        assert snapshot["diversity_index"] == pytest.approx(70.00, abs=0.001), (
            "(3*0.5 + 2*1.0)/(3+2)*100 = 70.00; the empty TIER_3 role is excluded"
        )


class TestHipoCycleScope:
    def test_diversity_index_hipo_cycle_counts_graduated(self, api):
        """PRD §3.8: "Under the `HIPO_CYCLE` scope, the population is the
        cycle's nominations in `ACTIVE`, `UNDER_REVIEW`, or `GRADUATED` status,
        and the index is the underrepresented share of that population
        multiplied by 100, rounded half-up to 2 decimal places; an empty
        population yields counts of 0 and a null index."
        PRD §3.7: "Closing the cycle — `HRAdmin` only, from `OPEN`, otherwise
        `ERR_CYCLE_INVALID_STATE` — resolves every nomination at once: those in
        `ACTIVE` or `UNDER_REVIEW` graduate to `GRADUATED`, those still
        `NOMINATED` or `ENDORSED` are `REJECTED`, and `enrolled_count`
        recomputes to zero."

        Design: Corner/calculations/diversity_index_hipo_cycle_counts_graduated
        """
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        member_a = setup_report(manager["id"], performance_rating="STRONG",
                                hire_date="2023-01-15", demographic_group="GROUP_C")
        member_b = setup_report(manager["id"], performance_rating="STRONG",
                                hire_date="2023-01-15", demographic_group="GROUP_A")
        member_c = setup_report(manager["id"], performance_rating="STRONG",
                                hire_date="2023-01-15", demographic_group="GROUP_B")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C86")
        for member in (member_a, member_b, member_c):
            nomination = nominate(cycle["id"], manager["id"], member["id"])
            endorse_nomination(nomination["id"], hrbp_headers)
            enroll_nomination(nomination["id"], tm_headers)
        validate_success(api.close_hipo_cycle(cycle["id"], ADMIN), 200)

        snapshot = capture_cycle_snapshot(cycle["id"])
        assert_diversity_snapshot(snapshot)
        assert snapshot["total_subjects"] == 3, (
            "GRADUATED members stay in the measured population"
        )
        assert snapshot["underrepresented_count"] == 1
        assert snapshot["diversity_index"] == pytest.approx(33.33, abs=0.001)
