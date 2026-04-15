"""Pre-built role headers from scaffold Table 7."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "platform_admin"),
    "admin_headers_2": build_user_headers("test-admin-2", "platform_admin"),
    "restaurant_headers": build_user_headers("test-restaurant-1", "restaurant"),
    "restaurant_headers_2": build_user_headers("test-restaurant-2", "restaurant"),
    "customer_headers": build_user_headers("test-customer-1", "customer"),
    "customer_headers_2": build_user_headers("test-customer-2", "customer"),
    "rider_headers": build_user_headers("test-rider-1", "rider"),
    "rider_headers_2": build_user_headers("test-rider-2", "rider"),
    "cs_headers": build_user_headers("test-cs-1", "customer_service"),
    "cs_headers_2": build_user_headers("test-cs-2", "customer_service"),
}
