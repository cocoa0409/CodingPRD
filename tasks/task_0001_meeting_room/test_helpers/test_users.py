"""Pre-built role headers from scaffold Table 7."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "employee_headers": build_user_headers("test-employee-1", "employee"),
    "employee2_headers": build_user_headers("test-employee-2", "employee"),
    "manager_headers": build_user_headers("test-manager-1", "manager"),
    "manager2_headers": build_user_headers("test-manager-2", "manager"),
    "facility_admin_headers": build_user_headers("test-facility-admin-1", "facility_admin"),
    "facility_admin2_headers": build_user_headers("test-facility-admin-2", "facility_admin"),
}
