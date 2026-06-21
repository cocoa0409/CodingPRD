"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly five peer roles: ShopAdmin, Estimator, Scheduler,
MaterialController, and Inspector. For all five roles X-User-ID is an opaque
operator identifier that the server never compares against any entity's id;
ownership is never determined by matching X-User-ID against a stored foreign key.
There are therefore no entity_backed roles and no per-instance header builders —
the shared constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shopadmin-1", "ShopAdmin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "material_controller_headers": build_user_headers("test-material-1", "MaterialController"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}
